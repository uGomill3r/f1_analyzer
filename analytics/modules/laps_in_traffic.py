# analytics/modules/laps_in_traffic.py

import logging

from analytics.modules.base import BaseAnalysisModule
from core.models import Lap

logger = logging.getLogger(__name__)


class LapsInTraffic(BaseAnalysisModule):
    """
    Heatmap piloto x vuelta: % de cada vuelta que el piloto pasó a menos de
    2s del auto de adelante ("en tráfico"). Ver core/services/traffic.py
    para el cálculo (telemetría FastF1) y Lap.IN_TRAFFIC_THRESHOLD_PCT para
    el umbral de clasificación (33%).

    Nota: no incluye vueltas completadas bajo SC / VSC / bandera (traffic_pct
    queda en None para esas vueltas desde la ingesta, ver load_fastf1.py), ni
    vueltas sin telemetría suficiente para calcular el gap.
    """

    name = "laps_in_traffic"

    def get_queryset(self, filters):
        qs = Lap.objects.select_related(
            "driver", "driver__team", "race"
        ).filter(
            race_id=filters["race_id"],
            lap_time__isnull=False,
            traffic_pct__isnull=False,  # excluye SC/VSC y vueltas sin telemetría
        )

        if filters.get("driver"):
            qs = qs.filter(driver__code__in=filters["driver"])

        if filters.get("team"):
            qs = qs.filter(driver__team__name__in=filters["team"])

        return qs.order_by("driver__code", "lap_number")

    # -----------------------------

    def transform(self, qs, filters):
        by_driver = {}

        for lap in qs:
            entry = by_driver.setdefault(lap.driver.code, {
                "driver": lap.driver.code,
                "team": lap.driver.team.name,
                "laps": [],
            })
            entry["laps"].append({
                "lap": lap.lap_number,
                "traffic_pct": round(lap.traffic_pct, 1),
                "in_traffic": lap.in_traffic,
            })

        result = list(by_driver.values())

        logger.info(
            "laps_in_traffic: race_id=%s -> %s piloto(s) con datos de tráfico",
            filters.get("race_id"), len(result),
        )

        return result

    # -----------------------------

    def serialize(self, data):
        max_lap = max(
            (lap["lap"] for driver in data for lap in driver["laps"]),
            default=0,
        )
        return {
            "module": self.name,
            "max_lap": max_lap,
            "drivers": len(data),
            "data": data,
        }