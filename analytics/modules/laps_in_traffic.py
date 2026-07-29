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

    Las vueltas completadas bajo SC / VSC / bandera no tienen traffic_pct
    (se excluyen desde la ingesta, ver load_fastf1.py) pero SÍ se incluyen
    en la respuesta con track_status_label (ej: "SC", "VSC", "Y", "R") para
    que el frontend pueda señalizarlas en vez de dejarlas como un hueco sin
    explicación. Solo quedan afuera las vueltas sin traffic_pct NI motivo de
    track_status (típicamente, telemetría insuficiente para calcular el gap).
    """

    name = "laps_in_traffic"

    def get_queryset(self, filters):
        qs = Lap.objects.select_related(
            "driver", "driver__team", "race"
        ).filter(
            race_id=filters["race_id"],
            lap_time__isnull=False,
        )

        if filters.get("driver"):
            qs = qs.filter(driver__code__in=filters["driver"])

        if filters.get("team"):
            qs = qs.filter(driver__team__name__in=filters["team"])

        return qs.order_by("driver__code", "lap_number")

    # -----------------------------

    def transform(self, qs, filters):
        by_driver = {}
        track_status_laps = 0
        skipped_laps = 0

        for lap in qs:
            track_status_label = lap.track_status_label

            # Sin traffic_pct y sin motivo de track_status: típicamente
            # telemetría insuficiente para calcular el gap. No aporta nada
            # al heatmap, se descarta (queda como hueco en blanco).
            if lap.traffic_pct is None and track_status_label is None:
                skipped_laps += 1
                continue

            entry = by_driver.setdefault(lap.driver.code, {
                "driver": lap.driver.code,
                "team": lap.driver.team.name,
                "laps": [],
            })

            lap_entry = {
                "lap": lap.lap_number,
                "traffic_pct": round(lap.traffic_pct, 1) if lap.traffic_pct is not None else None,
                "in_traffic": lap.in_traffic,
                "track_status_label": track_status_label,
            }
            entry["laps"].append(lap_entry)

            if track_status_label is not None:
                track_status_laps += 1

        result = list(by_driver.values())

        logger.info(
            "laps_in_traffic: race_id=%s -> %s piloto(s), %s vuelta(s) con track_status, "
            "%s vuelta(s) descartadas (sin traffic_pct ni track_status)",
            filters.get("race_id"), len(result), track_status_laps, skipped_laps,
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