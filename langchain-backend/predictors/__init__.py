"""IndependentCountPredictor 패키지.

Stage 1 (21지표): independent_count_predictor 통합 패턴 + 22 인스턴스 (Phase 1~4)
Stage 2 (회귀): regression_predictor (DynamicIndependentCountPredictor)

각 predictor는 11 base 모델을 통합하며 SSL pretrained backbone을 공유한다.
"""

from .independent_count_predictor import (
    IndependentCountPredictor,
    CategoryHead,
    PredictorOutput,
)
from .sum_predictor import SumPredictor
from .phase1_endings_distribution import EndingsDistributionPredictor
from .phase1_high_low import HighLowPredictor
from .phase1_odd_even import OddEvenPredictor
from .phase1_decade import DecadePredictor
from .phase1_gung import GungPredictor
from .phase1_carryover import CarryoverPredictor
from .phase1_neighbor import NeighborPredictor
from .phase1_consecutive import ConsecutivePredictor
from .phase1_lotto_paper import LottoPaperPredictor
from .phase1_multiple import MultiplePredictor
from .phase1_special_number import SpecialNumberPredictor
from .phase1_missing_group import MissingGroupPredictor
from .phase1_hotcold import HotColdPredictor
from .phase2_endings_sum import Phase2EndingsSumPredictor
from .phase3_ac import Phase3ACPredictor
from .regression_predictor import DynamicIndependentCountPredictor

__all__ = [
    "IndependentCountPredictor",
    "CategoryHead",
    "PredictorOutput",
    "SumPredictor",
    "EndingsDistributionPredictor",
    "HighLowPredictor",
    "OddEvenPredictor",
    "DecadePredictor",
    "GungPredictor",
    "CarryoverPredictor",
    "NeighborPredictor",
    "ConsecutivePredictor",
    "LottoPaperPredictor",
    "MultiplePredictor",
    "SpecialNumberPredictor",
    "MissingGroupPredictor",
    "HotColdPredictor",
    "Phase2EndingsSumPredictor",
    "Phase3ACPredictor",
    "DynamicIndependentCountPredictor",
]
