# analytics/modules/lap_times_traffic.py

import logging

from analytics.modules.laps_in_traffic import LapsInTraffic
from core.models import RaceResult

logger = logging.getLogger(__name__)


class LapTimesTraffic(LapsInTraffic):
    """
    Heatmap piloto x vuelta con el TIEMPO de cada vuelta (no el % de tráfico
    como LapsInTraffic), pensado para dashboard/static/dashboard/modules/
    lap_times_traffic.html: pilotos en el eje X, número de vuelta en el eje Y.

    A diferencia de LapsInTraffic, acá se incluyen TODAS las vueltas con
    lap_time (no se descartan las que no tienen traffic_pct ni track_status),
    porque el objetivo es mostrar el tiempo de cada vuelta siempre; el color
    de fondo es solo una señal adicional:
    - is_pit_in / is_pit_out       -> fondo celeste (entrada/salida de pits),
                                       distinguidas en el frontend con badge
                                       "IN" / "OUT"
    - track_status_label presente  -> fondo amarillo (SC/VSC/bandera)
    - traffic_pct disponible       -> degradado verde (aire limpio) a rojo
                                       (tráfico), quiebre en el umbral
                                       Lap.IN_TRAFFIC_THRESHOLD_PCT (33%)
    - ninguno de los anteriores    -> sin dato de tráfico (fondo neutro)

    Reutiliza get_queryset de LapsInTraffic (mismo filtro: lap_time no nulo,
    driver/team opcionales) y serialize (genérico sobre "data"/"laps").
    """

    name = "lap_times_traffic"

    def transform(self, qs, filters):
        race_id = filters.get("race_id")
        positions_by_driver = dict(
            RaceResult.objects.filter(race_id=race_id).values_list("driver__code", "position")
        )

        by_driver = {}
        pit_in_laps = 0
        pit_out_laps = 0
        track_status_laps = 0
        laps_without_traffic_data = 0

        for lap in qs:
            entry = by_driver.setdefault(lap.driver.code, {
                "driver": lap.driver.code,
                "team": lap.driver.team.name,
                "laps": [],
            })

            track_status_label = lap.track_status_label

            lap_entry = {
                "lap": lap.lap_number,
                "time": round(lap.lap_time, 3),
                "traffic_pct": round(lap.traffic_pct, 1) if lap.traffic_pct is not None else None,
                "is_pit_in": lap.is_pit_in,
                "is_pit_out": lap.is_pit_out,
                "track_status_label": track_status_label,
            }
            entry["laps"].append(lap_entry)

            if lap.is_pit_in:
                pit_in_laps += 1
            if lap.is_pit_out:
                pit_out_laps += 1
            if track_status_label is not None:
                track_status_laps += 1
            if lap.traffic_pct is None and not lap.is_pit and track_status_label is None:
                laps_without_traffic_data += 1

        for driver_code, entry in by_driver.items():
            entry["final_position"] = positions_by_driver.get(driver_code)

        result = list(by_driver.values())

        # Mismo criterio de orden que LapsInTraffic: clasificación final real
        # primero; pilotos sin RaceResult (sesión no reimportada) al final.
        result.sort(key=lambda d: (d["final_position"] is None, d["final_position"] or 0))

        logger.info(
            "lap_times_traffic: race_id=%s -> %s piloto(s), %s vuelta(s) de pit-in, "
            "%s vuelta(s) de pit-out, %s vuelta(s) con track_status, "
            "%s vuelta(s) sin dato de tráfico",
            race_id, len(result), pit_in_laps, pit_out_laps,
            track_status_laps, laps_without_traffic_data,
        )

        return result