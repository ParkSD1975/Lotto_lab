"""최신 회차로 Phase 2+3 검증."""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.supabase_client import fetch_all_draws
from predictors.phase2_endings_sum import Phase2EndingsSumPredictor
from predictors.phase3_ac import Phase3ACPredictor, _compute_ac


def compute_endings_sum(numbers: list[int]) -> int:
    return sum(int(n) % 10 for n in numbers)


all_draws = fetch_all_draws()
max_round = max(int(d.get("round", 0)) for d in all_draws)

print(f"최신 회차: {max_round}")

# 최신 회차 예측
target_round = max_round
train_draws = [d for d in all_draws if int(d.get("round", 0)) < target_round]

# Phase 2 끝수합
print("\n[Phase 2 끝수합]")
p2_pred = Phase2EndingsSumPredictor(active_models=("xgboost", "markov7"))
p2_pred.train(train_draws, phase1_outputs=None, min_history=20, bayes_epochs=5)
p2_out = p2_pred.predict(train_draws, phase1_outputs=None, min_history=20)

print(f"  끝수합 예측: {p2_out['expected_value']:.1f}")
print(f"  q10={p2_out['scalar']['q10']:.1f}, q50={p2_out['scalar']['q50']:.1f}, q90={p2_out['scalar']['q90']:.1f}")

# Phase 3 AC
print("\n[Phase 3 AC]")
p3_pred = Phase3ACPredictor(active_models=("xgboost", "markov7"))
p3_pred.train(train_draws, phase1_outputs=None, phase2_endings=None, min_history=20, bayes_epochs=5)
p3_out = p3_pred.predict(train_draws, phase1_outputs=None, phase2_endings=None, min_history=20)

print(f"  AC값 예측: {p3_out['expected_value']:.1f}")
print(f"  q10={p3_out['q10']:.1f}, q50={p3_out['q50']:.1f}, q90={p3_out['q90']:.1f}")

# 실제값
actual_draw = [d for d in all_draws if int(d.get("round", 0)) == target_round]
if actual_draw:
    actual_nums = actual_draw[0].get("numbers", [])
    actual_endings_sum = compute_endings_sum(actual_nums)
    actual_ac = _compute_ac(actual_nums)

    print(f"\n실제 {target_round}회차:")
    print(f"  번호: {actual_nums}")
    print(f"  끝수합: {actual_endings_sum} (예측: {p2_out['expected_value']:.1f}, 오차: {abs(actual_endings_sum - p2_out['expected_value']):.1f})")
    print(f"  AC값: {actual_ac} (예측: {p3_out['expected_value']:.1f}, 오차: {abs(actual_ac - p3_out['expected_value']):.1f})")
