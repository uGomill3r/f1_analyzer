# analytics/modules/tyre_degradation_advanced.py

import numpy as np
from collections import defaultdict

from analytics.modules.base import BaseAnalysisModule
from core.models import Lap


class TyreDegradationAdvanced(BaseAnalysisModule):
    name = "tyre_degradation_advanced"

    MIN_LAPS = 5

    # -----------------------------

    def get_queryset(self, filters):
        qs = Lap.objects.select_related(
            "driver", "driver__team", "race", "stint"
        ).filter(
            race_id=filters["race_id"],
            lap_time__isnull=False,
            is_pit=False
        )

        if filters.get("driver"):
            qs = qs.filter(driver__code__in=filters["driver"])

        if filters.get("compound"):
            qs = qs.filter(compound__in=filters["compound"])

        return qs.order_by("driver__code", "stint__stint_number", "lap_number")

    # -----------------------------

    def transform(self, qs, filters):
        grouped = defaultdict(list)

        for lap in qs:
            key = (
                lap.driver.code,
                lap.stint.stint_number if lap.stint else 0
            )
            grouped[key].append(lap)

        results = []

        for (driver_code, stint_number), laps in grouped.items():
            if len(laps) < self.MIN_LAPS:
                continue

            lap_times = np.array([lap.lap_time for lap in laps])
            lap_numbers = np.array([lap.lap_number for lap in laps])

            # -----------------------------
            # 1. LIMPIEZA AVANZADA
            # -----------------------------

            # eliminar outliers (tráfico / errores)
            p95 = np.percentile(lap_times, 95)
            mask = lap_times < p95

            lap_times = lap_times[mask]
            lap_numbers = lap_numbers[mask]

            if len(lap_times) < self.MIN_LAPS:
                continue

            # -----------------------------
            # 2. NORMALIZACIÓN RELATIVA
            # -----------------------------

            baseline = np.min(lap_times)
            delta_times = lap_times - baseline

            # -----------------------------
            # 3. SEGMENTACIÓN DEL STINT
            # -----------------------------

            warmup_laps = max(2, int(len(lap_times) * 0.2))
            stable_laps = int(len(lap_times) * 0.6)

            warmup = delta_times[:warmup_laps]
            stable = delta_times[warmup_laps:stable_laps]
            dropoff = delta_times[stable_laps:]

            # -----------------------------
            # 4. MÉTRICAS
            # -----------------------------

            # degradación en fase estable (clave real)
            if len(stable) > 2:
                stable_laps_idx = np.arange(len(stable))
                degradation_slope = np.polyfit(
                    stable_laps_idx, stable, 1
                )[0]
            else:
                degradation_slope = 0

            # variabilidad
            consistency = np.std(stable) if len(stable) > 1 else 0

            # cliff detection
            cliff_lap = None
            cliff_threshold = np.mean(stable) + 2 * np.std(stable)

            for i, val in enumerate(delta_times):
                if val > cliff_threshold:
                    cliff_lap = int(lap_numbers[i])
                    break

            # desgaste total
            total_deg = float(delta_times[-1])

            results.append({
                "driver": driver_code,
                "team": laps[0].driver.team.name,
                "stint": stint_number,
                "compound": laps[0].compound,
                "laps": len(delta_times),

                # métricas clave
                "degradation_slope": round(float(degradation_slope), 5),
                "total_degradation": round(total_deg, 3),
                "consistency": round(float(consistency), 3),
                "cliff_lap": cliff_lap,

                # fases
                "warmup_avg": float(np.mean(warmup)) if len(warmup) else 0,
                "stable_avg": float(np.mean(stable)) if len(stable) else 0,
                "dropoff_avg": float(np.mean(dropoff)) if len(dropoff) else 0,

                # curva completa
                "curve": [
                    {
                        "lap": int(lap_numbers[i]),
                        "delta": float(delta_times[i])
                    }
                    for i in range(len(delta_times))
                ]
            })

        return results

    # -----------------------------

    def serialize(self, data):
        return {
            "module": self.name,
            "total_stints": len(data),
            "data": data
        }