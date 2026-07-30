# analytics/modules/pace_adjusted.py

import logging

import numpy as np
from django.conf import settings

from analytics.modules.base import BaseAnalysisModule
from analytics.services.pace_correction import compute_pace_corrections
from core.models import Lap

logger = logging.getLogger(__name__)


class PaceAdjusted(BaseAnalysisModule):
    """
    Ritmo ajustado por piloto: descuenta combustible, degradación de
    neumáticos y evolución de pista para dejar un valor comparable entre
    vueltas y pilotos. El cálculo en sí vive en
    analytics/services/pace_correction.py (compartido con
    lap_times_traffic.py); acá solo se arma la respuesta por piloto.

    A diferencia de lap_times_traffic, este módulo SÍ excluye del ajuste
    las vueltas "en tráfico" (Lap.in_traffic): al ser un módulo de ritmo
    puro por piloto (no un heatmap con su propia columna de tráfico), esas
    vueltas distorsionarían el ajuste de degradación y evolución de pista.
    """

    name = "pace_adjusted"

    MIN_LAPS = 5

    # -----------------------------

    def get_queryset(self, filters):
        # Nota: no se filtra is_pit acá (ya no existe como campo de DB, es
        # una @property combinando is_pit_in/is_pit_out). La exclusión de
        # pits, track_status no verde y vuelta 1 se hace en
        # compute_pace_corrections vía Lap.is_outlier.
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
        per_driver_data = compute_pace_corrections(
            qs,
            fuel_coef=settings.FUEL_CORRECTION_PER_LAP,
            min_laps=self.MIN_LAPS,
            exclude_traffic=True,
        )

        if not per_driver_data:
            logger.warning(
                "pace_adjusted: race_id=%s -> sin pilotos con vueltas suficientes tras filtros",
                filters.get("race_id")
            )
            return []

        results = []

        for driver_code, data in per_driver_data.items():
            lap_numbers = data["lap_numbers"]
            track_corrected = data["track_corrected"]

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
                        "raw": float(data["raw"][i]),
                        "fuel_corrected": float(data["fuel_corrected"][i]),
                        "tyre_corrected": float(data["tyre_corrected"][i]),
                        "track_corrected": float(track_corrected[i]),
                        "delta": float(adjusted_delta[i])
                    }
                    for i in range(len(track_corrected))
                ]
            })

        logger.info(
            "pace_adjusted: race_id=%s -> %s piloto(s) procesados",
            filters.get("race_id"), len(results)
        )

        return results

    # -----------------------------

    def serialize(self, data):
        return {
            "module": self.name,
            "drivers": len(data),
            "data": data
        }