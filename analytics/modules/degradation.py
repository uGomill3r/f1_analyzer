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

# Tope de la corrección de degradación aplicada por vuelta, expresado como
# múltiplo de la variabilidad de la fase estable (consistency = std de esa
# fase). La pendiente se ajusta solo con datos de la fase estable; sobre
# stints largos, extrapolarla sin límite puede acumular correcciones de
# varios segundos sin respaldo real en los datos (visto en pace_debug.csv:
# un stint sin cliff detectado donde el ritmo mejoraba, no degradaba,
# terminó con ~4-5s de corrección acumulada). Escalar el tope con la propia
# variabilidad del stint (en vez de un número fijo de vueltas) evita que un
# tope único resulte demasiado laxo en stints cortos y sin efecto real —
# como pasó al probar con un tope en cantidad de vueltas.
#
# None desactiva el límite (vuelve al comportamiento anterior: corrección
# sin tope) — para revertir este cambio, alcanza con poner esta constante
# en None.
MAX_CORRECTION_STD_MULTIPLIER = 3.0

# Piso absoluto (segundos) para el tope, para el caso de una fase estable
# casi sin variabilidad (consistency ~ 0): sin este piso, el tope colapsaría
# a ~0 y anularía toda corrección de degradación, aunque sea legítima.
MIN_CORRECTION_CAP_SECONDS = 0.5


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

    if MAX_CORRECTION_STD_MULTIPLIER is None:
        max_correction = None
    else:
        max_correction = max(
            MAX_CORRECTION_STD_MULTIPLIER * consistency, MIN_CORRECTION_CAP_SECONDS
        )

    return {
        "baseline": float(baseline),
        "delta_times": delta_times,
        "degradation_slope": degradation_slope,
        "consistency": consistency,
        "cliff_lap": cliff_lap,
        # Tope (segundos) para la corrección aplicada por vuelta, ver
        # cap_correction. None si MAX_CORRECTION_STD_MULTIPLIER está
        # desactivado.
        "max_correction": max_correction,
        "warmup_avg": float(np.mean(warmup)) if len(warmup) else 0.0,
        "stable_avg": float(np.mean(stable)) if len(stable) else 0.0,
        "dropoff_avg": float(np.mean(dropoff)) if len(dropoff) else 0.0,
    }


def cap_correction(raw_correction, max_correction):
    """
    Acota (en valor absoluto) la corrección de degradación calculada como
    degradation_slope * índice de vuelta dentro del grupo, a max_correction
    segundos. max_correction=None desactiva el tope (devuelve raw_correction
    sin modificar).
    """
    if max_correction is None:
        return raw_correction

    return np.clip(raw_correction, -max_correction, max_correction)