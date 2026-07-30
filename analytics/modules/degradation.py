# analytics/modules/degradation.py
"""
Lógica compartida para ajustar la curva de degradación de neumáticos
(segmentación en fases warmup/stable/dropoff, pendiente de degradación y
detección de "cliff"), usada por:

- tyre_degradation_advanced.py: reporta la curva directamente.
- pace_adjusted.py: usa la pendiente de la fase estable para descontar el
  efecto de la degradación por (stint, compound) antes de ajustar la
  evolución de pista.
"""

import logging

import numpy as np

logger = logging.getLogger(__name__)

MIN_LAPS_FOR_CURVE = 5

# Máximo de vueltas más allá del final de la fase estable en las que se
# sigue extrapolando linealmente la pendiente de degradación al corregir
# tiempos (ver capped_extrapolation_index). Más allá de ese límite, la
# corrección se "congela" en el valor alcanzado ahí en vez de seguir
# creciendo sin control — la pendiente se ajustó solo con datos de la fase
# estable, y extrapolarla indefinidamente sobre stints largos puede
# producir correcciones de varios segundos sin respaldo real en los datos
# (visto en pace_debug.csv: un stint sin cliff detectado donde el ritmo
# mejoraba, no degradaba, terminó con ~4s de corrección acumulada).
#
# None desactiva el límite (vuelve al comportamiento anterior: extrapolación
# lineal sin tope sobre todo el resto del stint) — para revertir este
# cambio, alcanza con poner esta constante en None.
MAX_EXTRAPOLATION_LAPS_BEYOND_STABLE = 5


def fit_degradation_curve(lap_times, lap_numbers):
    """
    Ajusta la curva de degradación sobre un set de vueltas de un mismo
    stint/compuesto, ya ordenadas por lap_number.

    Segmenta el stint en warmup (primer 20%, mínimo 2 vueltas) / stable
    (siguiente 40%) / dropoff (resto), calcula la pendiente de degradación
    sobre la fase estable (el tramo representativo del desgaste real), y
    detecta el "cliff" (caída de rendimiento) buscando SOLO en la fase
    dropoff (posterior a stable), nunca en warmup, para no confundir una
    vuelta de calentamiento lenta con una caída real de rendimiento.

    Devuelve None si no hay vueltas suficientes para un ajuste confiable.
    """
    lap_times = np.asarray(lap_times, dtype=float)
    lap_numbers = np.asarray(lap_numbers, dtype=float)

    if len(lap_times) < MIN_LAPS_FOR_CURVE:
        logger.debug(
            "fit_degradation_curve: %s vuelta(s), insuficientes (mínimo %s)",
            len(lap_times), MIN_LAPS_FOR_CURVE
        )
        return None

    baseline = np.min(lap_times)
    delta_times = lap_times - baseline

    warmup_laps = max(2, int(len(lap_times) * 0.2))
    stable_laps = int(len(lap_times) * 0.6)

    warmup = delta_times[:warmup_laps]
    stable = delta_times[warmup_laps:stable_laps]
    dropoff = delta_times[stable_laps:]

    if len(stable) > 2:
        stable_idx = np.arange(len(stable))
        degradation_slope = float(np.polyfit(stable_idx, stable, 1)[0])
    else:
        logger.debug(
            "fit_degradation_curve: fase estable muy corta (%s vuelta(s)), degradation_slope=0",
            len(stable)
        )
        degradation_slope = 0.0

    consistency = float(np.std(stable)) if len(stable) > 1 else 0.0

    cliff_lap = None
    if len(stable) > 1:
        cliff_threshold = np.mean(stable) + 2 * np.std(stable)
        for i, val in enumerate(dropoff):
            if val > cliff_threshold:
                cliff_lap = int(lap_numbers[stable_laps + i])
                break

    return {
        "baseline": float(baseline),
        "delta_times": delta_times,
        "degradation_slope": degradation_slope,
        "consistency": consistency,
        "cliff_lap": cliff_lap,
        # Índice (0-based, dentro del grupo) donde termina la fase estable
        # y empieza el dropoff. Se usa en capped_extrapolation_index para
        # limitar cuánto se extrapola la pendiente más allá de donde se
        # ajustó realmente.
        "stable_end_idx": stable_laps,
        "warmup_avg": float(np.mean(warmup)) if len(warmup) else 0.0,
        "stable_avg": float(np.mean(stable)) if len(stable) else 0.0,
        "dropoff_avg": float(np.mean(dropoff)) if len(dropoff) else 0.0,
    }


def capped_extrapolation_index(local_idx, stable_end_idx):
    """
    Limita el índice usado para extrapolar la pendiente de degradación al
    corregir tiempos vuelta a vuelta: más allá de
    stable_end_idx + MAX_EXTRAPOLATION_LAPS_BEYOND_STABLE, el índice queda
    "congelado" en ese tope (la corrección deja de crecer, pero no
    desaparece del todo). Si MAX_EXTRAPOLATION_LAPS_BEYOND_STABLE es None,
    devuelve local_idx sin modificar (extrapolación lineal sin límite,
    comportamiento anterior a este cambio).
    """
    if MAX_EXTRAPOLATION_LAPS_BEYOND_STABLE is None:
        return local_idx

    cap = stable_end_idx + MAX_EXTRAPOLATION_LAPS_BEYOND_STABLE
    return np.minimum(local_idx, cap)