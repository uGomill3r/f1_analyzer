# analytics/services/pace_correction.py
"""
Servicio compartido de corrección de ritmo, usado por:

- analytics/modules/pace_adjusted.py: expone el ritmo corregido como
  métricas/serie por piloto (excluye vueltas en tráfico del ajuste).
- analytics/modules/lap_times_traffic.py: agrega un campo corrected_time
  por vuelta al heatmap de tiempos (incluye vueltas en tráfico, ya que ese
  módulo tiene su propia columna de traffic_pct).

Orden de aplicación: excluir outliers (Lap.is_outlier: pits, track_status
no verde, vuelta 1) -> excluir tráfico (Lap.in_traffic, opcional) ->
corrección de combustible (aditiva, sobre lap_number real) -> corrección
de degradación por (stint, compound), descartando las vueltas desde el
"cliff" de cada stint y limitando cuánto se extrapola la pendiente más
allá de la fase estable (ver analytics/modules/degradation.py) ->
evolución de pista (ajustada sobre los residuales de todos los pilotos,
ya sin combustible ni degradación).
"""

import logging
from collections import defaultdict

import numpy as np

from analytics.modules.degradation import capped_extrapolation_index, fit_degradation_curve

logger = logging.getLogger(__name__)

MIN_LAPS_DEFAULT = 5


def compute_pace_corrections(qs, fuel_coef, min_laps=MIN_LAPS_DEFAULT, exclude_traffic=True):
    """
    Calcula, por piloto, el ritmo corregido a partir de un queryset de Lap
    ya filtrado por race_id (y opcionalmente driver/team/compound) por el
    módulo que llama.

    Se excluyen SIEMPRE las vueltas outlier (Lap.is_outlier: pits,
    SC/VSC/bandera, vuelta 1). La exclusión de vueltas "en tráfico" es
    opcional vía exclude_traffic, y usa Lap.in_traffic (traffic_pct por
    encima de Lap.IN_TRAFFIC_THRESHOLD_PCT) — el mismo criterio que ya usan
    laps_in_traffic y lap_times_traffic, en vez de un umbral propio sobre
    gap_to_front promedio (que podía dejar pasar vueltas "medio sucias").

    Dentro de cada grupo (stint, compound), además se descartan las
    vueltas desde el "cliff" detectado por fit_degradation_curve en
    adelante (la pendiente no es válida para extrapolar sobre el dropoff),
    y la extrapolación de la pendiente sobre el resto del stint se limita
    vía capped_extrapolation_index, para no acumular correcciones de varios
    segundos sin respaldo real cuando un stint largo no dispara ningún
    cliff pero tampoco sostiene la tendencia de la fase estable.

    Devuelve un dict {driver_code: {...}} con arrays numpy paralelos
    (mismo orden, por lap_number ascendente, ya sin las vueltas excluidas):
    - laps: objetos Lap originales
    - lap_numbers, raw, fuel_corrected, tyre_corrected, track_corrected

    Pilotos con menos de min_laps vueltas válidas tras TODOS los filtros
    (outliers, tráfico, y cliff) no aparecen en el resultado. Devuelve {}
    si ningún piloto llega al mínimo.
    """
    grouped = defaultdict(list)
    total_laps = 0
    excluded_outliers = 0
    excluded_traffic = 0

    for lap in qs:
        total_laps += 1

        if lap.is_outlier:
            excluded_outliers += 1
            continue

        if exclude_traffic and lap.in_traffic:
            excluded_traffic += 1
            continue

        grouped[lap.driver.code].append(lap)

    # -----------------------------
    # 1. Combustible + degradación (con exclusión de cliff, extrapolación
    #    acotada) por piloto
    # -----------------------------

    per_driver_data = {}
    residual_lap_numbers = []
    residual_values = []
    excluded_cliff_total = 0

    for driver_code, driver_laps in grouped.items():
        driver_laps = sorted(driver_laps, key=lambda lap: lap.lap_number)
        lap_numbers = np.array([lap.lap_number for lap in driver_laps])
        lap_times = np.array([lap.lap_time for lap in driver_laps])

        # Combustible: se SUMA el tiempo "ganado" por menor carga, para
        # neutralizarlo (restar exagera el efecto en vez de corregirlo).
        fuel_corrected = lap_times + lap_numbers * fuel_coef

        tyre_corrected = np.array(fuel_corrected, copy=True)
        keep_mask = np.ones(len(driver_laps), dtype=bool)

        stint_groups = defaultdict(list)
        for idx, lap in enumerate(driver_laps):
            stint_groups[(lap.stint_id, lap.compound)].append(idx)

        for (stint_id, compound), idxs in stint_groups.items():
            idxs = sorted(idxs, key=lambda i: lap_numbers[i])
            group_times = fuel_corrected[idxs]
            group_numbers = lap_numbers[idxs]

            curve = fit_degradation_curve(group_times, group_numbers)
            if curve is None:
                logger.debug(
                    "compute_pace_corrections: %s stint=%s compound=%s -> sin vueltas "
                    "suficientes para corregir degradación, se deja sin corregir",
                    driver_code, stint_id, compound
                )
                continue

            local_idx = np.arange(len(idxs))
            applied_idx = capped_extrapolation_index(local_idx, curve["stable_end_idx"])
            corrected = group_times - curve["degradation_slope"] * applied_idx
            cliff_lap = curve["cliff_lap"]

            for pos, idx in enumerate(idxs):
                if cliff_lap is not None and group_numbers[pos] >= cliff_lap:
                    keep_mask[idx] = False
                    continue
                tyre_corrected[idx] = corrected[pos]

        n_excluded_cliff = int((~keep_mask).sum())
        excluded_cliff_total += n_excluded_cliff

        if n_excluded_cliff:
            driver_laps = [lap for lap, keep in zip(driver_laps, keep_mask) if keep]
            lap_numbers = lap_numbers[keep_mask]
            lap_times = lap_times[keep_mask]
            fuel_corrected = fuel_corrected[keep_mask]
            tyre_corrected = tyre_corrected[keep_mask]

        if len(driver_laps) < min_laps:
            continue

        per_driver_data[driver_code] = {
            "laps": driver_laps,
            "lap_numbers": lap_numbers,
            "raw": lap_times,
            "fuel_corrected": fuel_corrected,
            "tyre_corrected": tyre_corrected,
        }
        residual_lap_numbers.extend(lap_numbers.tolist())
        residual_values.extend(tyre_corrected.tolist())

    if not per_driver_data:
        logger.warning(
            "compute_pace_corrections: sin pilotos con vueltas suficientes tras filtros "
            "(%s vuelta(s) evaluadas, %s por outlier, %s por tráfico, %s por cliff)",
            total_laps, excluded_outliers, excluded_traffic, excluded_cliff_total
        )
        return {}

    # -----------------------------
    # 2. Evolución de pista sobre residuales
    # -----------------------------

    try:
        track_model = np.polyfit(
            np.array(residual_lap_numbers), np.array(residual_values), 1
        )
    except Exception:
        logger.warning(
            "compute_pace_corrections: no se pudo ajustar el modelo de evolución de "
            "pista, se usa un modelo plano (sin corrección)"
        )
        track_model = [0, 0]

    # Se resta SOLO la pendiente (evolución de pista: la tendencia de que la
    # pista se pone más rápida con las vueltas), NO el intercept completo.
    # El intercept del ajuste captura el nivel de ritmo absoluto de la
    # grilla (ej: ~87s), no un efecto a corregir; restarlo entero dejaba
    # track_corrected como un residual cercano a 0 (o negativo), sin
    # significado físico como tiempo de vuelta. Restando solo la pendiente,
    # track_corrected queda en la misma escala de segundos que
    # tyre_corrected, y el nivel de ritmo propio de cada piloto no se ve
    # alterado por el ajuste de pista.
    track_slope = track_model[0]
    for driver_code, data in per_driver_data.items():
        track_delta = track_slope * data["lap_numbers"]
        data["track_corrected"] = data["tyre_corrected"] - track_delta

    logger.info(
        "compute_pace_corrections: %s vuelta(s) evaluadas -> %s piloto(s) con datos, "
        "%s vuelta(s) descartadas por outlier, %s por tráfico, %s por cliff",
        total_laps, len(per_driver_data), excluded_outliers, excluded_traffic, excluded_cliff_total
    )

    return per_driver_data