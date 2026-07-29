# core/services/traffic.py
"""
Cálculo de "tráfico" por vuelta a partir de telemetría de FastF1.

Criterio (chart de referencia "Laps in traffic"):
- Se calcula el % de cada vuelta en que el piloto estuvo a menos de
  TRAFFIC_GAP_THRESHOLD_SECONDS del auto que tiene inmediatamente adelante.
- No se incluyen vueltas completadas bajo SC / VSC / bandera (eso lo filtra
  el caller, ver core/management/commands/load_fastf1.py, usando
  Lap.NON_GREEN_TRACK_STATUS_CODES).
- Un piloto se marca "en tráfico" si ese % supera Lap.IN_TRAFFIC_THRESHOLD_PCT
  (33%, ver core/models.py).

Enfoque (mismo principio que el "gap to leader" de F1 TV / la mayoría de
herramientas de análisis con FastF1): para cada piloto se arma una curva
monótona (distancia acumulada en la sesión -> tiempo de sesión), usando
`lap.get_car_data().add_distance()` de FastF1 y offseteando cada vuelta por
la distancia acumulada de las anteriores. Para saber el gap de un piloto A
respecto de otro piloto B en el instante t, se interpola en la curva de B
en qué instante pasó por la misma distancia que A recorrió hasta t: la
diferencia de tiempos es el gap.

Nota: la distancia se acumula vuelta a vuelta usando el último valor de
`Distance` de cada vuelta como "largo de vuelta". Es una aproximación (la
distancia real de pit lane, corte de chicanas, etc. puede variar levemente),
suficiente para clasificar tráfico con umbral de 2s, pero no para telemetría
de precisión milimétrica.
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Umbral de gap (segundos) para considerar que un piloto está "en tráfico"
# en un instante dado.
TRAFFIC_GAP_THRESHOLD_SECONDS = 2.0


def _pick_driver_laps(session_laps, driver_code):
    """Wrapper de pick_drivers/pick_driver (distintas versiones de FastF1)."""
    return (
        session_laps.pick_drivers(driver_code)
        if hasattr(session_laps, "pick_drivers")
        else session_laps.pick_driver(driver_code)
    )


def build_distance_time_curve(session, driver_code):
    """
    Arma la curva (distancia acumulada en la sesión, tiempo de sesión) de un
    piloto, concatenando la telemetría de todas sus vueltas.

    Devuelve (distance_arr, time_arr): dos arrays de numpy del mismo largo,
    ordenados por tiempo, con distancia estrictamente no decreciente (apta
    para np.interp). Arrays vacíos si no hay telemetría disponible.
    """
    driver_laps = _pick_driver_laps(session.laps, driver_code)

    distances = []
    times = []
    cumulative_offset = 0.0

    for _, lap in driver_laps.sort_values("LapNumber").iterrows():
        try:
            car_data = lap.get_car_data().add_distance()
        except Exception:
            logger.warning(
                "traffic: sin telemetría para %s vuelta %s; se omite del cálculo de gap.",
                driver_code, lap.get("LapNumber"),
            )
            continue

        if car_data.empty:
            continue

        lap_distance = car_data["Distance"].to_numpy() + cumulative_offset
        lap_time = car_data["Time"].dt.total_seconds().to_numpy()

        distances.append(lap_distance)
        times.append(lap_time)
        cumulative_offset += float(car_data["Distance"].iloc[-1])

    if not distances:
        return np.array([]), np.array([])

    distance_arr = np.concatenate(distances)
    time_arr = np.concatenate(times)

    order = np.argsort(time_arr)
    distance_arr = distance_arr[order]
    time_arr = time_arr[order]
    # np.interp exige x creciente; forzamos monotonía estricta ante ruido
    # de telemetría (ej: pequeñas oscilaciones en Distance).
    distance_arr = np.maximum.accumulate(distance_arr)

    return distance_arr, time_arr


def gap_to_front_series(target_time, target_dist, other_curves):
    """
    Calcula, para cada muestra (target_time[i], target_dist[i]) de un piloto,
    el gap (segundos) al auto más cercano por delante entre todos los de
    other_curves.

    other_curves: dict {driver_code: (dist_arr, time_arr)} de los demás pilotos.
    Devuelve un array del mismo largo que target_time, con np.inf donde no
    hay ningún auto de referencia por delante (ej: líder en vuelta 1).
    """
    if target_time.size == 0:
        return np.array([])

    best_gap = np.full(target_time.shape, np.inf)

    for other_code, (other_dist, other_time) in other_curves.items():
        if other_dist.size == 0:
            continue

        # instante en que el otro piloto pasó por la misma distancia
        other_time_at_dist = np.interp(
            target_dist, other_dist, other_time, left=np.nan, right=np.nan
        )
        gap = target_time - other_time_at_dist
        # solo cuenta si el otro auto ya pasó por ahí antes (gap positivo)
        valid = ~np.isnan(gap) & (gap > 0)
        best_gap = np.where(valid & (gap < best_gap), gap, best_gap)

    return best_gap


def lap_traffic_pct(lap_start, lap_end, sample_times, gaps):
    """% (0-100) de muestras dentro de [lap_start, lap_end] con gap < umbral.

    Devuelve None si no hay muestras válidas en la ventana de la vuelta.
    """
    if sample_times.size == 0:
        return None

    mask = (sample_times >= lap_start) & (sample_times <= lap_end)
    samples = gaps[mask]

    finite = samples[np.isfinite(samples)]
    if finite.size == 0:
        return None

    in_traffic = finite < TRAFFIC_GAP_THRESHOLD_SECONDS
    return float(np.mean(in_traffic) * 100)


def compute_traffic_by_driver(session):
    """
    Calcula, para cada piloto y cada una de sus vueltas, el % de tiempo en
    tráfico y el gap promedio al auto de adelante.

    Devuelve: { driver_code: { lap_number(int): {"traffic_pct": float,
    "mean_gap": float | None} } }

    Vueltas sin telemetría suficiente (o sin auto de referencia) quedan
    ausentes del dict interno del piloto; el caller decide qué hacer
    (típicamente, dejar traffic_pct/gap_to_front en None para esa vuelta).
    """
    driver_codes = session.laps["Driver"].unique()

    logger.info("traffic: construyendo curvas distancia-tiempo para %s piloto(s)...", len(driver_codes))
    curves = {code: build_distance_time_curve(session, code) for code in driver_codes}

    result = {}

    for code in driver_codes:
        target_dist, target_time = curves[code]
        other_curves = {c: v for c, v in curves.items() if c != code}
        gaps = gap_to_front_series(target_time, target_dist, other_curves)

        driver_laps = _pick_driver_laps(session.laps, code)

        per_lap = {}
        for _, lap in driver_laps.iterrows():
            if pd.isna(lap.get("LapStartTime")) or pd.isna(lap.get("Time")):
                continue

            lap_start = lap["LapStartTime"].total_seconds()
            lap_end = lap["Time"].total_seconds()

            pct = lap_traffic_pct(lap_start, lap_end, target_time, gaps)
            if pct is None:
                continue

            window_mask = (target_time >= lap_start) & (target_time <= lap_end)
            window_gaps = gaps[window_mask]
            finite_gaps = window_gaps[np.isfinite(window_gaps)]
            mean_gap = float(np.mean(finite_gaps)) if finite_gaps.size else None

            per_lap[int(lap["LapNumber"])] = {"traffic_pct": pct, "mean_gap": mean_gap}

        result[code] = per_lap

    logger.info("traffic: cálculo de tráfico completo.")
    return result