"""A3: Phase 1 13개 + Phase 2/3 + Regression 재학습 스크립트 (Stage 1 차별화 강화)."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import time
import numpy as np
from db.supabase_client import fetch_all_draws

# Phase 1 13개 predictor import
from predictors.phase1_endings_distribution import EndingsDistributionPredictor
from predictors.phase1_high_low import HighLowPredictor
from predictors.phase1_odd_even import OddEvenPredictor
from predictors.phase1_decade import DecadePredictor
from predictors.phase1_gung import GungPredictor
from predictors.phase1_carryover import CarryoverPredictor
from predictors.phase1_neighbor import NeighborPredictor
from predictors.phase1_consecutive import ConsecutivePredictor
from predictors.phase1_lotto_paper import LottoPaperPredictor
from predictors.phase1_multiple import MultiplePredictor
from predictors.phase1_special_number import SpecialNumberPredictor
from predictors.phase1_missing_group import MissingGroupPredictor
from predictors.phase1_hotcold import HotColdPredictor

# Phase 2/3 import
from predictors.phase2_endings_sum import Phase2EndingsSumPredictor
from predictors.phase3_ac import Phase3ACPredictor

# Regression import
from predictors.regression_predictor import DynamicIndependentCountPredictor


def measure_variance(predictor, draws, val_rounds):
    """Walk-forward validation으로 예측 분산 측정.

    Args:
        predictor: 학습된 predictor 인스턴스
        draws: 전체 회차 데이터
        val_rounds: validation 대상 회차 리스트 (예: [1051, 1052, ..., 1100])

    Returns:
        (mean, std): 예측 expected_ratio의 평균과 표준편차
    """
    ratios = []
    for target_round in val_rounds:
        try:
            pred = predictor.predict(draws, target_round)
            if isinstance(pred, dict) and 'expected_ratio' in pred:
                ratios.extend(pred['expected_ratio'].values())
            elif isinstance(pred, dict):
                # Phase 4 sum_predictor는 expected_values
                if 'expected_values' in pred:
                    ratios.extend(pred['expected_values'])
        except Exception as e:
            print(f"  [WARN] round {target_round} predict fail: {e}")
            continue

    if len(ratios) == 0:
        return 0.0, 0.0

    return float(np.mean(ratios)), float(np.std(ratios))


def main():
    print("=" * 80)
    print("A3: Phase 1~3 + Regression 재학습 (차별화 강화)")
    print("=" * 80)

    # 데이터 로드 (회차 31~1100, 1070개)
    print("\n[1/5] 데이터 로드 중...")
    all_draws = fetch_all_draws()
    all_draws = [d for d in all_draws if int(d.get('round', 0)) <= 1222]
    train_draws = [d for d in all_draws if 31 <= int(d.get('round', 0)) <= 1100]
    print(f"  학습 데이터: {len(train_draws)} 회차 (31~1100)")
    print(f"  검증 회차: 1051~1100 (50회 walk-forward variance 측정)")

    val_rounds = list(range(1051, 1101))

    # Phase 1 13개 predictor 정의
    phase1_predictors = [
        ("endings_distribution", EndingsDistributionPredictor()),
        ("high_low", HighLowPredictor()),
        ("odd_even", OddEvenPredictor()),
        ("decade", DecadePredictor()),
        ("gung", GungPredictor()),
        ("carryover", CarryoverPredictor()),
        ("neighbor", NeighborPredictor()),
        ("consecutive", ConsecutivePredictor()),
        ("lotto_paper", LottoPaperPredictor()),
        ("multiple", MultiplePredictor()),
        ("special_number", SpecialNumberPredictor()),
        ("missing_group", MissingGroupPredictor()),
        ("hotcold", HotColdPredictor()),
    ]

    results = []

    print("\n[2/5] Phase 1 학습 시작 (13개)...")
    for i, (name, predictor) in enumerate(phase1_predictors, 1):
        print(f"\n  [{i}/13] {name} 학습 중...")
        start_t = time.time()

        try:
            train_result = predictor.train(train_draws)
            elapsed = time.time() - start_t

            # Walk-forward variance 측정
            mean_ratio, std_ratio = measure_variance(predictor, all_draws, val_rounds)

            results.append({
                'name': f'P1_{name}',
                'time': elapsed,
                'result': train_result,
                'mean_ratio': mean_ratio,
                'std_ratio': std_ratio,
            })

            print(f"    OK 완료: {elapsed:.1f}s | mean={mean_ratio:.4f}, std={std_ratio:.4f}")

        except Exception as e:
            print(f"    FAIL 실패: {e}")
            results.append({
                'name': f'P1_{name}',
                'time': 0,
                'result': {'error': str(e)},
                'mean_ratio': 0.0,
                'std_ratio': 0.0,
            })

    # Phase 2/3 학습
    print("\n[3/5] Phase 2/3 학습 시작...")

    phase23_predictors = [
        ("P2_endings_sum", Phase2EndingsSumPredictor()),
        ("P3_ac", Phase3ACPredictor()),
    ]

    for name, predictor in phase23_predictors:
        print(f"\n  {name} 학습 중...")
        start_t = time.time()

        try:
            train_result = predictor.train(train_draws)
            elapsed = time.time() - start_t

            mean_ratio, std_ratio = measure_variance(predictor, all_draws, val_rounds)

            results.append({
                'name': name,
                'time': elapsed,
                'result': train_result,
                'mean_ratio': mean_ratio,
                'std_ratio': std_ratio,
            })

            print(f"    OK 완료: {elapsed:.1f}s | mean={mean_ratio:.4f}, std={std_ratio:.4f}")

        except Exception as e:
            print(f"    FAIL 실패: {e}")
            results.append({
                'name': name,
                'time': 0,
                'result': {'error': str(e)},
                'mean_ratio': 0.0,
                'std_ratio': 0.0,
            })

    # Regression 학습
    print("\n[4/5] Regression (DynamicIndependentCount) 학습 시작...")
    reg_predictor = DynamicIndependentCountPredictor()
    start_t = time.time()

    try:
        # Regression train (tier 인자 없이 전체 학습)
        train_result = reg_predictor.train(train_draws)
        elapsed = time.time() - start_t

        # Regression은 expected_ratio 개념이 다름 (직접 번호 예측)
        results.append({
            'name': 'Regression',
            'time': elapsed,
            'result': train_result,
            'mean_ratio': 0.0,
            'std_ratio': 0.0,
        })

        print(f"    OK 완료: {elapsed:.1f}s")

    except Exception as e:
        print(f"    FAIL 실패: {e}")
        results.append({
            'name': 'Regression',
            'time': 0,
            'result': {'error': str(e)},
            'mean_ratio': 0.0,
            'std_ratio': 0.0,
        })

    # 결과 요약
    print("\n" + "=" * 80)
    print("[5/5] 학습 결과 요약")
    print("=" * 80)

    print(f"\n{'Predictor':<30} {'Time(s)':<10} {'Mean Ratio':<12} {'Std Ratio':<12}")
    print("-" * 80)

    total_time = 0
    for r in results:
        total_time += r['time']
        print(f"{r['name']:<30} {r['time']:<10.1f} {r['mean_ratio']:<12.4f} {r['std_ratio']:<12.4f}")

    print("-" * 80)
    print(f"{'TOTAL':<30} {total_time:<10.1f}")

    # 차별화 진단
    print("\n[차별화 진단]")
    p1_stds = [r['std_ratio'] for r in results if r['name'].startswith('P1_')]
    p2_stds = [r['std_ratio'] for r in results if r['name'].startswith('P2_')]

    if p1_stds:
        print(f"  P1 평균 표준편차: {np.mean(p1_stds):.4f}")
    if p2_stds:
        print(f"  P2 평균 표준편차: {np.mean(p2_stds):.4f}")

    print("\n재학습 완료!")
    return results


if __name__ == "__main__":
    main()
