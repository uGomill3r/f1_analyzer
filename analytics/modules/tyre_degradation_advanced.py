# analytics/modules/tyre_degradation_advanced.py

import logging
from collections import defaultdict

import numpy as np

from analytics.modules.base import BaseAnalysisModule
from analytics.modules.degradation import fit_degradation_curve
from core.models import Lap

logger = logging.getLogger(__name__)


class TyreDegradationAdvanced(BaseAnalysisModule):
    name = "tyre_degradation_advanced"

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

        if filters.get("compound"):
            qs = qs.filter(compound__in=filters["compound"])

        return qs.order_by("driver__code", "stint__stint_number", "lap_number")

    # -----------------------------

    def transform(self, qs, filters):
        grouped = defaultdict(list)
        excluded_outliers = 0

        for lap in qs:
            if lap.is_outlier:
                excluded_outliers += 1
                continue

            key = (
                lap.driver.code,
                lap.stint.stint_number if lap.stint else 0
            )
            grouped[key].append(lap)

        results = []

        for (driver_code, stint_number), laps in grouped.items():
            if len(laps) < self.MIN_LAPS:
                continue

            laps = sorted(laps, key=lambda lap: lap.lap_number)
            lap_times = np.array([lap.lap_time for lap in laps])
            lap_numbers = np.array([lap.lap_number for lap in laps])

            # -----------------------------
            # Recorte estadístico adicional
            # -----------------------------
            # Ya se excluyeron pits/track_status/vuelta 1 arriba (vía
            # is_outlier); esto recorta además errores puntuales o tráfico
            # no capturado por gap_to_front, sobre un set ya limpio.

            p95 = np.percentile(lap_times, 95)
            mask = lap_times < p95

            lap_times = lap_times[mask]
            lap_numbers = lap_numbers[mask]

            if len(lap_times) < self.MIN_LAPS:
                continue

            curve = fit_degradation_curve(lap_times, lap_numbers)
            if curve is None:
                continue

            results.append({
                "driver": driver_code,
                "team": laps[0].driver.team.name,
                "stint": stint_number,
                "compound": laps[0].compound,
                "laps": len(lap_times),

                # métricas clave
                "degradation_slope": round(curve["degradation_slope"], 5),
                "total_degradation": round(float(curve["delta_times"][-1]), 3),
                "consistency": round(curve["consistency"], 3),
                "cliff_lap": curve["cliff_lap"],

                # fases
                "warmup_avg": curve["warmup_avg"],
                "stable_avg": curve["stable_avg"],
                "dropoff_avg": curve["dropoff_avg"],

                # curva completa
                "curve": [
                    {
                        "lap": int(lap_numbers[i]),
                        "delta": float(curve["delta_times"][i])
                    }
                    for i in range(len(lap_times))
                ]
            })

        logger.info(
            "tyre_degradation_advanced: race_id=%s -> %s stint(s) procesados, "
            "%s vuelta(s) descartadas por outlier",
            filters.get("race_id"), len(results), excluded_outliers
        )

        return results

    # -----------------------------

    def serialize(self, data):
        return {
            "module": self.name,
            "total_stints": len(data),
            "data": data
        }