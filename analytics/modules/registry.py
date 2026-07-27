from analytics.modules.pace_adjusted import PaceAdjusted
from analytics.modules.pace_by_stint import PaceByStint
from analytics.modules.tyre_degradation_advanced import TyreDegradationAdvanced

MODULES = {
    PaceByStint.name: PaceByStint(),
    TyreDegradationAdvanced.name: TyreDegradationAdvanced(),
    PaceAdjusted.name: PaceAdjusted(),
}


def get_module(name):
    return MODULES.get(name)
