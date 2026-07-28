# analytics/modules/pace_by_stint.py

import logging

import numpy as np
from collections import defaultdict

from analytics.modules.base import BaseAnalysisModule
from core.models import Lap

logger = logging.getLogger(__name__)


class PaceByStint(BaseAnalysisModule):
    name = "pace_by_stint"

    MIN_LAPS_FOR_STATS = 3

    def get_queryset(self, filters):
        # Nota: ya NO se excluyen acá las vueltas de pits / outliers.
        # Se devuelven todas las vueltas válidas (con tiempo registrado) y cada
        # una viaja con su flag is_outlier + outlier_reasons, para que el
        # frontend decida si incluirlas o no.
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
        total_outliers = 0

        for (driver_code, stint_number), laps in grouped.items():
            if len(laps) < self.MIN_LAPS_FOR_STATS:
                continue  # ignorar stints muy cortos

            # las métricas de ritmo (mean/consistency/degradation) se calculan
            # sobre las vueltas "limpias"; si no alcanzan, se usa el set completo
            clean_laps = [lap for lap in laps if not lap.is_outlier]
            reference_laps = clean_laps if len(clean_laps) >= self.MIN_LAPS_FOR_STATS else laps

            lap_times = np.array([lap.lap_time for lap in reference_laps])
            lap_numbers = np.array([lap.lap_number for lap in reference_laps])

            mean_pace = lap_times.mean()
            std_dev = lap_times.std()

            try:
                slope = np.polyfit(lap_numbers, lap_times, 1)[0]
            except Exception:
                logger.warning(
                    "No se pudo calcular la degradación para %s stint %s; se usa 0.",
                    driver_code, stint_number
                )
                slope = 0

            stint_outliers = sum(1 for lap in laps if lap.is_outlier)
            total_outliers += stint_outliers

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
                        "gap_to_front": lap.gap_to_front,
                        # marca si la vuelta no es representativa del ritmo real
                        "is_outlier": lap.is_outlier,
                        "outlier_reasons": lap.outlier_reasons,
                    } for lap in laps
                ]
            })

        logger.info(
            "pace_by_stint: race_id=%s -> %s stints procesados, %s vuelta(s) marcada(s) como outlier",
            filters.get("race_id"), len(result), total_outliers
        )

        return result

    # -----------------------------

    def serialize(self, data):
        return {
            "module": self.name,
            "total_stints": len(data),
            "data": data
        }