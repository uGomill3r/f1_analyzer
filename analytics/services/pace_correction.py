# analytics/services/pace_correction.py
"""
Servicio compartido de corrección de ritmo, usado por:

- analytics/modules/pace_adjusted.py: expone el ritmo corregido como
  métricas/serie por piloto (excluye vueltas en tráfico del ajuste).
- analytics/modules/lap_times_traffic.py: agrega un campo corrected_time
  por vuelta al heatmap de tiempos (incluye vueltas en tráfico, ya que ese
  módulo tiene su propia columna de traffic_pct).

Orden de aplicación: excluir outliers (Lap.is_outlier: pits, track_status
no verde, vuelta 1) -> corrección de combustible (aditiva, sobre lap_number
real) -> corrección de degradación por (stint, compound) -> evolución de
pista (ajustada sobre los residuales de todos los pilotos, ya sin
combustible ni degradación).
"""

import logging
from collections import defaultdict

import numpy as np

from analytics.modules.degradation import fit_degradation_curve

logger = logging.getLogger(__name__)

MIN_LAPS_DEFAULT = 5


def compute_pace_corrections(
    qs,
    fuel_coef,
    min_laps=MIN_LAPS_DEFAULT,
    exclude_traffic=True,
    traffic_gap_threshold=1.5,
):
    """
    Calcula, por piloto, el ritmo corregido a partir de un queryset de Lap
    ya filtrado por race_id (y opcionalmente driver/team/compound) por el
    módulo que llama.

    Se excluyen SIEMPRE las vueltas outlier (Lap.is_outlier), porque el
    ajuste de combustible/degradación/pista no es válido sobre ellas
    (pits, SC/VSC/bandera, vuelta 1). La exclusión de vueltas "en tráfico"
    (gap_to_front < traffic_gap_threshold) es opcional vía exclude_traffic,
    para que cada módulo consumidor decida según su propósito.

    Devuelve un dict {driver_code: {...}} con arrays numpy paralelos
    (mismo orden, por lap_number ascendente):
    - laps: objetos Lap originales
    - lap_numbers, raw, fuel_corrected, tyre_corrected, track_corrected

    Pilotos con menos de min_laps vueltas válidas tras los filtros no
    aparecen en el resultado. Devuelve {} si ningún piloto llega al mínimo.
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

        if exclude_traffic and lap.gap_to_front is not None and lap.gap_to_front < traffic_gap_threshold:
            excluded_traffic += 1
            continue

        grouped[lap.driver.code].append(lap)

    # -----------------------------
    # 1. Combustible + degradación por piloto
    # -----------------------------

    per_driver_data = {}
    residual_lap_numbers = []
    residual_values = []

    for driver_code, laps in grouped.items():
        if len(laps) < min_laps:
            continue

        laps = sorted(laps, key=lambda lap: lap.lap_number)
        lap_numbers = np.array([lap.lap_number for lap in laps])
        lap_times = np.array([lap.lap_time for lap in laps])

        # Combustible: se SUMA el tiempo "ganado" por menor carga, para
        # neutralizarlo (restar exagera el efecto en vez de corregirlo).
        fuel_corrected = lap_times + lap_numbers * fuel_coef

        # Degradación: por (stint, compound), usando la pendiente de la
        # fase estable de cada grupo (ver fit_degradation_curve). Si un
        # grupo no tiene vueltas suficientes para un ajuste confiable, se
        # deja sin corregir.
        tyre_corrected = np.array(fuel_corrected, copy=True)
        stint_groups = defaultdict(list)
        for idx, lap in enumerate(laps):
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
            tyre_corrected[idxs] = group_times - curve["degradation_slope"] * local_idx

        per_driver_data[driver_code] = {
            "laps": laps,
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
            "(%s vuelta(s) evaluadas, %s por outlier, %s por tráfico)",
            total_laps, excluded_outliers, excluded_traffic
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
        "%s vuelta(s) descartadas por outlier, %s por tráfico",
        total_laps, len(per_driver_data), excluded_outliers, excluded_traffic
    )

    return per_driver_data