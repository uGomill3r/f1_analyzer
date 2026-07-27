# analytics/modules/pace_by_stint.py

import logging

import numpy as np
from collections import defaultdict

from analytics.modules.base import BaseAnalysisModule
from core.models import Lap

logger = logging.getLogger(__name__)


class PaceByStint(BaseAnalysisModule):
    name = "pace_by_stint"

    def get_queryset(self, filters):
        qs = Lap.objects.select_related(
            "driver", "driver__team", "race", "stint"
        ).filter(
            race_id=filters["race_id"]
        )

        if filters.get("driver"):
            qs = qs.filter(driver__code__in=filters["driver"])

        if filters.get("team"):
            qs = qs.filter(driver__team__name__in=filters["team"])

        if filters.get("compound"):
            qs = qs.filter(compound__in=filters["compound"])

        # excluir vueltas inválidas
        qs = qs.filter(
            lap_time__isnull=False,
            is_pit=False
        )

        return qs.order_by("driver__code", "stint__stint_number", "lap_number")

    # -----------------------------

    def transform(self, qs, filters):
        grouped = defaultdict(list)

        # agrupar por (driver, stint)
        for lap in qs:
            key = (
                lap.driver.code,
                lap.stint.stint_number if lap.stint else 0
            )
            grouped[key].append(lap)

        result = []

        for (driver_code, stint_number), laps in grouped.items():
            lap_times = np.array([lap.lap_time for lap in laps])

            if len(lap_times) < 3:
                continue  # ignorar stints muy cortos

            lap_numbers = np.array([lap.lap_number for lap in laps])

            # métricas
            mean_pace = lap_times.mean()
            std_dev = lap_times.std()

            # degradación (pendiente)
            try:
                slope = np.polyfit(lap_numbers, lap_times, 1)[0]
            except Exception:
                logger.warning(
                    "No se pudo calcular la degradación para %s stint %s; se usa 0.",
                    driver_code, stint_number
                )
                slope = 0

            result.append({
                "driver": driver_code,
                "team": laps[0].driver.team.name,
                "stint": stint_number,
                "compound": laps[0].compound,
                "lap_count": len(lap_times),
                "mean_pace": round(mean_pace, 3),
                "consistency": round(std_dev, 3),
                "degradation": round(slope, 5),
                "laps": [
                    {
                        "lap": lap.lap_number,
                        "time": lap.lap_time,
                        # gap al auto de adelante (para clasificar tráfico en el frontend)
                        "gap_to_front": lap.gap_to_front
                    } for lap in laps
                ]
            })

        logger.info(
            "pace_by_stint: race_id=%s -> %s stints procesados",
            filters.get("race_id"), len(result)
        )

        return result

    # -----------------------------

    def serialize(self, data):
        return {
            "module": self.name,
            "total_stints": len(data),
            "data": data
        }