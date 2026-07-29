# analytics/modules/pace_gap_comparison.py

import logging

import numpy as np

from analytics.modules.base import BaseAnalysisModule
from core.models import DriverTelemetryCurve, Lap

logger = logging.getLogger(__name__)


class PaceGapComparison(BaseAnalysisModule):
    """
    Compara dos pilotos vuelta a vuelta: tiempo de vuelta de cada uno
    (alineados por número de vuelta, para graficar dos líneas) y el gap
    real entre ellos al final de cada vuelta del piloto A.

    El gap NO se aproxima por diferencia acumulada de lap_time (esa sería
    la "Opción B": más simple, pero sensible a vueltas bajo SC/VSC o a
    diferencias de vuelta cuando hay autos doblados). Acá se usa telemetría
    real (Opción A): para cada vuelta de A se toma la distancia acumulada
    que A tenía al cruzar la línea (Lap.cum_distance_end) y se interpola en
    la curva distancia-tiempo completa de B (DriverTelemetryCurve, ver
    core/services/traffic.py:build_distance_time_curve) en qué instante B
    pasó por esa misma distancia.

    gap_seconds = tiempo_B_en_esa_distancia - tiempo_A_al_final_de_la_vuelta
    Positivo -> B todavía no había llegado ahí (B va detrás de A).
    Negativo -> B ya había pasado por ahí (B va adelante de A).

    Filtro: se reutiliza el parámetro repetible "driver" de la API
    (?driver=VER&driver=HAM). El orden en que llegan define quién es
    piloto A (referencia de distancia) y quién es piloto B. Requiere
    exactamente 2 códigos de piloto.
    """

    name = "pace_gap_comparison"

    def get_queryset(self, filters):
        driver_codes = filters.get("driver") or []
        if len(driver_codes) != 2:
            raise ValueError(
                "pace_gap_comparison requiere exactamente 2 pilotos "
                f"(?driver=XXX&driver=YYY); se recibieron {len(driver_codes)}."
            )

        qs = Lap.objects.select_related("driver", "driver__team").filter(
            race_id=filters["race_id"],
            driver__code__in=driver_codes,
            lap_time__isnull=False,
        ).order_by("driver__code", "lap_number")

        return qs

    # -----------------------------

    def transform(self, qs, filters):
        driver_a_code, driver_b_code = filters["driver"][0], filters["driver"][1]
        race_id = filters["race_id"]

        laps_by_driver = {driver_a_code: {}, driver_b_code: {}}
        team_by_driver = {}

        for lap in qs:
            laps_by_driver.setdefault(lap.driver.code, {})[lap.lap_number] = lap
            team_by_driver[lap.driver.code] = lap.driver.team.name

        if not laps_by_driver.get(driver_a_code):
            raise ValueError(f"No hay vueltas cargadas para '{driver_a_code}' en esta carrera.")
        if not laps_by_driver.get(driver_b_code):
            raise ValueError(f"No hay vueltas cargadas para '{driver_b_code}' en esta carrera.")

        curve_b = DriverTelemetryCurve.objects.filter(
            race_id=race_id, driver__code=driver_b_code
        ).first()

        if curve_b is None:
            logger.warning(
                "pace_gap_comparison: race_id=%s -> sin DriverTelemetryCurve para %s "
                "(reimportá la sesión con load_fastf1 para calcular el gap real).",
                race_id, driver_b_code,
            )
            b_distance_curve, b_time_curve = np.array([]), np.array([])
        else:
            b_distance_curve = np.array(curve_b.distance)
            b_time_curve = np.array(curve_b.session_time)

        all_lap_numbers = sorted(
            set(laps_by_driver[driver_a_code].keys()) | set(laps_by_driver[driver_b_code].keys())
        )

        laps_payload = []
        gaps_computed = 0
        gaps_out_of_range = 0

        for lap_number in all_lap_numbers:
            lap_a = laps_by_driver[driver_a_code].get(lap_number)
            lap_b = laps_by_driver[driver_b_code].get(lap_number)

            gap_seconds = None
            if lap_a is not None and lap_a.cum_distance_end is not None and b_time_curve.size:
                interpolated = np.interp(
                    lap_a.cum_distance_end, b_distance_curve, b_time_curve,
                    left=np.nan, right=np.nan,
                )
                if not np.isnan(interpolated) and lap_a.session_time_end is not None:
                    gap_seconds = round(float(interpolated - lap_a.session_time_end), 3)
                    gaps_computed += 1
                else:
                    gaps_out_of_range += 1

            laps_payload.append({
                "lap": lap_number,
                "lap_time_a": lap_a.lap_time if lap_a else None,
                "lap_time_b": lap_b.lap_time if lap_b else None,
                "is_outlier_a": lap_a.is_outlier if lap_a else None,
                "is_outlier_b": lap_b.is_outlier if lap_b else None,
                "gap_seconds": gap_seconds,
            })

        logger.info(
            "pace_gap_comparison: race_id=%s %s vs %s -> %s vuelta(s), gap calculado en %s, "
            "fuera de rango de telemetría en %s",
            race_id, driver_a_code, driver_b_code, len(laps_payload),
            gaps_computed, gaps_out_of_range,
        )

        return {
            "driver_a": driver_a_code,
            "driver_b": driver_b_code,
            "team_a": team_by_driver.get(driver_a_code),
            "team_b": team_by_driver.get(driver_b_code),
            "laps": laps_payload,
        }

    # -----------------------------

    def serialize(self, data):
        return {
            "module": self.name,
            **data,
        }