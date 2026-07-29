from analytics.modules.pace_adjusted import PaceAdjusted
from analytics.modules.pace_by_stint import PaceByStint
from analytics.modules.pace_gap_comparison import PaceGapComparison
from analytics.modules.tyre_degradation_advanced import TyreDegradationAdvanced
from analytics.modules.laps_in_traffic import LapsInTraffic
from analytics.modules.lap_times_traffic import LapTimesTraffic

MODULES = {
    PaceByStint.name: PaceByStint(),
    TyreDegradationAdvanced.name: TyreDegradationAdvanced(),
    PaceAdjusted.name: PaceAdjusted(),
    LapsInTraffic.name: LapsInTraffic(),
    PaceGapComparison.name: PaceGapComparison(),
    LapTimesTraffic.name: LapTimesTraffic(),
}


def get_module(name):
    return MODULES.get(name)