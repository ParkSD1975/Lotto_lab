"""Phase 1 predictor variance 재측정 (재학습 후 차별화 확인)."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
from db.supabase_client import fetch_all_draws

# Phase 1 predictor import
from predictors.phase1_endings_distribution import EndingsDistributionPredictor
from predictors.phase1_high_low import HighLowPredictor
from predictors.phase1_odd_even import OddEvenPredictor


def measure_variance_detailed(predictor, draws, val_rounds):
    """Phase 1 predictor의 expected_ratio variance 상세 측정."""
    all_ratios = []

    for target_round in val_rounds:
        try:
            pred = predictor.predict(draws, target_round)

            # Phase 1 구조: {'per_category': {'cat_name': {'expected_ratio': ...}}}
            if isinstance(pred, dict) and 'per_category' in pred:
                per_cat = pred['per_category']
                for cat_name, cat_data in per_cat.items():
                    if isinstance(cat_data, dict) and 'expected_ratio' in cat_data:
                        ratio = cat_data['expected_ratio']
                        all_ratios.append(float(ratio))
        except Exception as e:
            print(f"  [WARN] round {target_round} predict fail: {e}")
            continue

    if len(all_ratios) == 0:
        return {
            'mean': 0.0,
            'std': 0.0,
            'min': 0.0,
            'max': 0.0,
            'count': 0,
        }

    return {
        'mean': float(np.mean(all_ratios)),
        'std': float(np.std(all_ratios)),
        'min': float(np.min(all_ratios)),
        'max': float(np.max(all_ratios)),
        'count': len(all_ratios),
    }


def main():
    print("Phase 1 Variance Test (재학습 후 차별화 확인)")
    print("=" * 80)

    # 데이터 로드
    all_draws = fetch_all_draws()
    all_draws = [d for d in all_draws if int(d.get('round', 0)) <= 1222]
    train_draws = [d for d in all_draws if 31 <= int(d.get('round', 0)) <= 1100]

    val_rounds = list(range(1051, 1101))  # 50회

    print(f"\n학습 데이터: {len(train_draws)} 회차 (31~1100)")
    print(f"검증 회차: 1051~1100 (50회 walk-forward)\n")

    # 3개 predictor 테스트
    predictors = [
        ("endings_distribution", EndingsDistributionPredictor()),
        ("high_low", HighLowPredictor()),
        ("odd_even", OddEvenPredictor()),
    ]

    for name, predictor in predictors:
        print(f"\n[{name}]")
        print(f"  학습 중...")
        predictor.train(train_draws)

        print(f"  Variance 측정 중 (50회)...")
        stats = measure_variance_detailed(predictor, all_draws, val_rounds)

        print(f"    Count:  {stats['count']}")
        print(f"    Mean:   {stats['mean']:.6f}")
        print(f"    Std:    {stats['std']:.6f}")
        print(f"    Min:    {stats['min']:.6f}")
        print(f"    Max:    {stats['max']:.6f}")
        print(f"    Range:  {stats['max'] - stats['min']:.6f}")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
