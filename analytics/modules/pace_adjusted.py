# analytics/modules/pace_adjusted.py

import numpy as np
from collections import defaultdict

from analytics.modules.base import BaseAnalysisModule
from core.models import Lap


class PaceAdjusted(BaseAnalysisModule):
    name = "pace_adjusted"

    FUEL_CORRECTION_PER_LAP = 0.035  # segundos por vuelta
    TRAFFIC_GAP_THRESHOLD = 1.5      # segundos
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

        return qs.order_by("driver__code", "lap_number")

    # -----------------------------

    def transform(self, qs, filters):
        grouped = defaultdict(list)

        for lap in qs:
            grouped[lap.driver.code].append(lap)

        results = []

        # -----------------------------
        # 1. Track evolution baseline
        # -----------------------------

        all_laps = [lap for lap in qs]
        global_lap_times = np.array([lap.lap_time for lap in all_laps])
        global_lap_numbers = np.array([lap.lap_number for lap in all_laps])

        # modelo simple de evolución pista
        try:
            track_model = np.polyfit(global_lap_numbers, global_lap_times, 1)
        except:
            track_model = [0, 0]

        # -----------------------------

        for driver_code, laps in grouped.items():

            if len(laps) < self.MIN_LAPS:
                continue

            lap_times = []
            lap_numbers = []

            # -----------------------------
            # 2. Filtrar tráfico
            # -----------------------------

            for lap in laps:
                # asumimos que tienes gap_to_front
                if hasattr(lap, "gap_to_front") and lap.gap_to_front:
                    if lap.gap_to_front < self.TRAFFIC_GAP_THRESHOLD:
                        continue

                lap_times.append(lap.lap_time)
                lap_numbers.append(lap.lap_number)

            if len(lap_times) < self.MIN_LAPS:
                continue

            lap_times = np.array(lap_times)
            lap_numbers = np.array(lap_numbers)

            # -----------------------------
            # 3. Corrección combustible
            # -----------------------------

            fuel_corrected = []

            for i, lap_time in enumerate(lap_times):
                correction = i * self.FUEL_CORRECTION_PER_LAP
                fuel_corrected.append(lap_time - correction)

            fuel_corrected = np.array(fuel_corrected)

            # -----------------------------
            # 4. Corrección track evolution
            # -----------------------------

            track_corrected = []

            for lap_time, lap_num in zip(fuel_corrected, lap_numbers):
                track_delta = np.polyval(track_model, lap_num)
                track_corrected.append(lap_time - track_delta)

            track_corrected = np.array(track_corrected)

            # -----------------------------
            # 5. Normalización final
            # -----------------------------

            baseline = np.min(track_corrected)
            adjusted_delta = track_corrected - baseline

            # -----------------------------
            # 6. Métricas
            # -----------------------------

            mean_pace = np.mean(track_corrected)
            consistency = np.std(track_corrected)

            # mejor vuelta real
            best_lap = float(np.min(track_corrected))

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
                        "raw": float(lap_times[i]),
                        "fuel_corrected": float(fuel_corrected[i]),
                        "track_corrected": float(track_corrected[i]),
                        "delta": float(adjusted_delta[i])
                    }
                    for i in range(len(track_corrected))
                ]
            })

        return results

    # -----------------------------

    def serialize(self, data):
        return {
            "module": self.name,
            "drivers": len(data),
            "data": data
        }