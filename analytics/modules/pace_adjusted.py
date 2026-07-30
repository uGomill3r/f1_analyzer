# analytics/modules/pace_adjusted.py

import logging
from collections import defaultdict

import numpy as np
from django.conf import settings

from analytics.modules.base import BaseAnalysisModule
from analytics.modules.degradation import fit_degradation_curve
from core.models import Lap

logger = logging.getLogger(__name__)


class PaceAdjusted(BaseAnalysisModule):
    """
    Ritmo ajustado por piloto: descuenta combustible, degradación de
    neumáticos y evolución de pista para dejar un valor comparable entre
    vueltas y pilotos.

    Orden de aplicación (cada paso opera sobre el resultado del anterior):
    1. Se excluyen outliers (pits, track_status no verde, vuelta 1 -> ver
       Lap.outlier_reasons) y vueltas en tráfico (gap_to_front).
    2. Corrección de combustible: aditiva y determinística sobre el
       lap_number real (no sobre el índice post-filtrado), usando
       settings.FUEL_CORRECTION_PER_LAP.
    3. Corrección de degradación: por (stint, compound) de cada piloto,
       usando la pendiente de la fase estable (fit_degradation_curve).
    4. Evolución de pista: ajustada por regresión lineal sobre los
       residuales de TODOS los pilotos ya corregidos por combustible y
       degradación (no sobre tiempos crudos), para evitar colinealidad.
    """

    name = "pace_adjusted"

    TRAFFIC_GAP_THRESHOLD = 1.5  # segundos
    MIN_LAPS = 5

    # -----------------------------

    def get_queryset(self, filters):
        # Nota: no se filtra is_pit acá (ya no existe como campo de DB, es
        # una @property combinando is_pit_in/is_pit_out). La exclusión de
        # pits, track_status no verde y vuelta 1 se hace en transform() vía
        # Lap.is_outlier, para tener un único criterio compartido con el
        # resto de los módulos.
        qs = Lap.objects.select_related(
            "driver", "driver__team", "race", "stint"
        ).filter(
            race_id=filters["race_id"],
            lap_time__isnull=False,
        )

        if filters.get("driver"):
            qs = qs.filter(driver__code__in=filters["driver"])

        if filters.get("team"):
            qs = qs.filter(driver__team__name__in=filters["team"])

        if filters.get("compound"):
            qs = qs.filter(compound__in=filters["compound"])

        return qs.order_by("driver__code", "lap_number")

    # -----------------------------

    def transform(self, qs, filters):
        fuel_coef = settings.FUEL_CORRECTION_PER_LAP

        grouped = defaultdict(list)
        total_laps = 0
        excluded_outliers = 0
        excluded_traffic = 0

        for lap in qs:
            total_laps += 1

            if lap.is_outlier:
                excluded_outliers += 1
                continue

            if lap.gap_to_front is not None and lap.gap_to_front < self.TRAFFIC_GAP_THRESHOLD:
                excluded_traffic += 1
                continue

            grouped[lap.driver.code].append(lap)

        # -----------------------------
        # 1. Combustible + degradación por piloto
        # -----------------------------
        # Se calculan primero para poder ajustar la evolución de pista sobre
        # los residuales (paso 2), evitando la colinealidad de ajustar sobre
        # tiempos crudos (combustible y degradación también corren con
        # lap_number).

        per_driver_data = {}
        residual_lap_numbers = []
        residual_values = []

        for driver_code, laps in grouped.items():
            if len(laps) < self.MIN_LAPS:
                continue

            laps = sorted(laps, key=lambda lap: lap.lap_number)
            lap_numbers = np.array([lap.lap_number for lap in laps])
            lap_times = np.array([lap.lap_time for lap in laps])

            # Combustible: se SUMA el tiempo "ganado" por menor carga, para
            # neutralizarlo (el auto ya es más rápido con menos combustible;
            # restar exagera el efecto en vez de corregirlo).
            fuel_corrected = lap_times + lap_numbers * fuel_coef

            # Degradación: por (stint, compound), usando la pendiente de la
            # fase estable de cada grupo. Si un grupo no tiene vueltas
            # suficientes para un ajuste confiable, se deja sin corregir.
            tyre_corrected = np.array(fuel_corrected, copy=True)
            stint_groups = defaultdict(list)
            for idx, lap in enumerate(laps):
                stint_groups[(lap.stint_id, lap.compound)].append(idx)

            for (stint_id, compound), idxs in stint_groups.items():
                idxs = sorted(idxs, key=lambda i: lap_numbers[i])
                group_times = fuel_corrected[idxs]
                group_numbers = lap_numbers[idxs]

                curve = fit_degradation_curve(group_times, group_numbers)
                if curve is None:
                    logger.debug(
                        "pace_adjusted: %s stint=%s compound=%s -> sin vueltas suficientes "
                        "para corregir degradación, se deja sin corregir",
                        driver_code, stint_id, compound
                    )
                    continue

                local_idx = np.arange(len(idxs))
                tyre_corrected[idxs] = group_times - curve["degradation_slope"] * local_idx

            per_driver_data[driver_code] = {
                "laps": laps,
                "lap_numbers": lap_numbers,
                "lap_times": lap_times,
                "fuel_corrected": fuel_corrected,
                "tyre_corrected": tyre_corrected,
            }
            residual_lap_numbers.extend(lap_numbers.tolist())
            residual_values.extend(tyre_corrected.tolist())

        if not per_driver_data:
            logger.warning(
                "pace_adjusted: race_id=%s -> sin pilotos con vueltas suficientes tras filtros",
                filters.get("race_id")
            )
            return []

        # -----------------------------
        # 2. Evolución de pista sobre residuales
        # -----------------------------

        try:
            track_model = np.polyfit(
                np.array(residual_lap_numbers), np.array(residual_values), 1
            )
        except Exception:
            logger.warning(
                "pace_adjusted: race_id=%s -> no se pudo ajustar el modelo de evolución de pista, "
                "se usa un modelo plano (sin corrección)",
                filters.get("race_id")
            )
            track_model = [0, 0]

        # -----------------------------
        # 3. Resultado final por piloto
        # -----------------------------

        results = []

        for driver_code, data in per_driver_data.items():
            lap_numbers = data["lap_numbers"]
            tyre_corrected = data["tyre_corrected"]

            track_delta = np.polyval(track_model, lap_numbers)
            track_corrected = tyre_corrected - track_delta

            baseline = np.min(track_corrected)
            adjusted_delta = track_corrected - baseline

            mean_pace = np.mean(track_corrected)
            consistency = np.std(track_corrected)
            best_lap = float(np.min(track_corrected))

            laps = data["laps"]

            results.append({
                "driver": driver_code,
                "team": laps[0].driver.team.name,
                "laps_used": len(track_corrected),

                "mean_pace_adjusted": round(float(mean_pace), 3),
                "consistency": round(float(consistency), 3),
                "best_lap_adjusted": round(best_lap, 3),

                "series": [
                    {
                        "lap": int(lap_numbers[i]),
                        "raw": float(data["lap_times"][i]),
                        "fuel_corrected": float(data["fuel_corrected"][i]),
                        "tyre_corrected": float(tyre_corrected[i]),
                        "track_corrected": float(track_corrected[i]),
                        "delta": float(adjusted_delta[i])
                    }
                    for i in range(len(track_corrected))
                ]
            })

        logger.info(
            "pace_adjusted: race_id=%s -> %s vuelta(s) evaluadas, %s piloto(s) procesados, "
            "%s vuelta(s) descartadas por outlier, %s por tráfico",
            filters.get("race_id"), total_laps, len(results), excluded_outliers, excluded_traffic
        )

        return results

    # -----------------------------

    def serialize(self, data):
        return {
            "module": self.name,
            "drivers": len(data),
            "data": data
        }