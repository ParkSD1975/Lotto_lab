"""Phase 2 끝수합 + Phase 3 AC 실제 데이터 검증.

target_round 1223 예측 + 50회차 walk-forward 백테스트.
"""

import sys
import os

# langchain-backend를 sys.path에 추가
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
from db.supabase_client import fetch_all_draws
from predictors.phase2_endings_sum import Phase2EndingsSumPredictor
from predictors.phase3_ac import Phase3ACPredictor, _compute_ac


def compute_endings_sum(numbers: list[int]) -> int:
    """끝수합 계산."""
    return sum(int(n) % 10 for n in numbers)


def compute_frequency_baseline(series: np.ndarray, num_buckets: int = 7) -> dict:
    """빈도 베이스라인 기댓값 (균등 분포)."""
    if len(series) == 0:
        return {"expected": 0.0, "std": 0.0}
    mean_val = float(series.mean())
    std_val = float(series.std())
    return {"expected": mean_val, "std": std_val}


def compute_cross_entropy(predicted_dist: np.ndarray, true_bucket: int, num_buckets: int = 7) -> float:
    """Cross-entropy: -log(p[true_bucket])."""
    prob = max(predicted_dist[true_bucket], 1e-9)
    return -np.log(prob)


def main():
    print("[validate] Phase 2 끝수합 + Phase 3 AC 검증")
    print("=" * 70)

    # 전체 데이터 가져오기
    all_draws = fetch_all_draws()
    print(f"총 회차 수: {len(all_draws)}")

    # 1. target_round 1223 예측
    print("\n[1] target_round 1223 예측")
    print("-" * 70)

    target_round = 1223
    train_draws = [d for d in all_draws if int(d.get("round", 0)) < target_round]

    # Phase 2 끝수합
    print("\n[Phase 2 끝수합]")
    p2_pred = Phase2EndingsSumPredictor(active_models=("xgboost", "markov7", "bayesian"))
    p2_train_info = p2_pred.train(train_draws, phase1_outputs=None, min_history=20, bayes_epochs=20)
    print(f"  학습 완료: {p2_train_info['trained_models']}, feature_dim={p2_train_info['feature_dim']}")

    p2_out = p2_pred.predict(train_draws, phase1_outputs=None, min_history=20)
    print(f"  끝수합 예측: {p2_out['expected_value']:.1f}")
    print(f"  q10={p2_out['scalar']['q10']:.1f}, q50={p2_out['scalar']['q50']:.1f}, q90={p2_out['scalar']['q90']:.1f}")
    print(f"  narrative: {p2_out['narrative']}")

    # Phase 3 AC
    print("\n[Phase 3 AC]")
    p3_pred = Phase3ACPredictor(active_models=("xgboost", "markov7", "bayesian"))
    p3_train_info = p3_pred.train(train_draws, phase1_outputs=None, phase2_endings=None, min_history=20, bayes_epochs=20)
    print(f"  학습 완료: {p3_train_info['trained_models']}, feature_dim={p3_train_info['feature_dim']}")

    p3_out = p3_pred.predict(train_draws, phase1_outputs=None, phase2_endings=None, min_history=20)
    print(f"  AC값 예측: {p3_out['expected_value']:.1f}")
    print(f"  q10={p3_out['q10']:.1f}, q50={p3_out['q50']:.1f}, q90={p3_out['q90']:.1f}")
    print(f"  narrative: {p3_out['narrative']}")

    # 실제값 확인 (1223회차)
    target_draw = [d for d in all_draws if int(d.get("round", 0)) == target_round]
    if target_draw:
        actual_nums = target_draw[0].get("numbers", [])
        actual_endings_sum = compute_endings_sum(actual_nums)
        actual_ac = _compute_ac(actual_nums)
        print(f"\n  실제 1223회차:")
        print(f"    번호: {actual_nums}")
        print(f"    끝수합: {actual_endings_sum} (예측: {p2_out['expected_value']:.1f}, 오차: {abs(actual_endings_sum - p2_out['expected_value']):.1f})")
        print(f"    AC값: {actual_ac} (예측: {p3_out['expected_value']:.1f}, 오차: {abs(actual_ac - p3_out['expected_value']):.1f})")

    # 2. 50회차 walk-forward 백테스트
    print("\n\n[2] 50회차 walk-forward 백테스트")
    print("-" * 70)

    max_round = max(int(d.get("round", 0)) for d in all_draws)
    start_round = max_round - 49

    p2_ce_list = []
    p2_freq_ce_list = []
    p3_ce_list = []
    p3_freq_ce_list = []

    p2_mae_list = []
    p3_mae_list = []

    for r in range(start_round, max_round + 1):
        train = [d for d in all_draws if int(d.get("round", 0)) < r]
        if len(train) < 50:
            continue

        # Phase 2 끝수합
        p2 = Phase2EndingsSumPredictor(active_models=("xgboost", "markov7"))
        try:
            p2.train(train, phase1_outputs=None, min_history=20, bayes_epochs=5)
            p2_result = p2.predict(train, phase1_outputs=None, min_history=20)

            # 실제값
            actual = [d for d in all_draws if int(d.get("round", 0)) == r]
            if actual:
                actual_endings_sum = compute_endings_sum(actual[0].get("numbers", []))
                p2_bucket = p2._find_bucket(actual_endings_sum)
                p2_ce = compute_cross_entropy(np.array(p2_result["absolute_dist"]), p2_bucket, 7)
                p2_ce_list.append(p2_ce)

                # 빈도 베이스라인
                series = p2._extract_series(train)
                freq_dist = p2._compute_freq_dist(series)
                freq_ce = compute_cross_entropy(freq_dist, p2_bucket, 7)
                p2_freq_ce_list.append(freq_ce)

                # MAE
                p2_mae_list.append(abs(actual_endings_sum - p2_result["expected_value"]))
        except Exception as e:
            print(f"  [Phase 2] round {r} 실패: {e}")

        # Phase 3 AC
        p3 = Phase3ACPredictor(active_models=("xgboost", "markov7"))
        try:
            p3.train(train, phase1_outputs=None, phase2_endings=None, min_history=20, bayes_epochs=5)
            p3_result = p3.predict(train, phase1_outputs=None, phase2_endings=None, min_history=20)

            # 실제값
            if actual:
                actual_ac = _compute_ac(actual[0].get("numbers", []))
                p3_bucket = p3._find_bucket(actual_ac)
                p3_ce = compute_cross_entropy(np.array(p3_result["absolute_dist"]), p3_bucket, 7)
                p3_ce_list.append(p3_ce)

                # 빈도 베이스라인
                series = p3._extract_series(train)
                freq_dist = p3._compute_freq_dist(series)
                freq_ce = compute_cross_entropy(freq_dist, p3_bucket, 7)
                p3_freq_ce_list.append(freq_ce)

                # MAE
                p3_mae_list.append(abs(actual_ac - p3_result["expected_value"]))
        except Exception as e:
            print(f"  [Phase 3] round {r} 실패: {e}")

    print(f"\n백테스트 완료: {len(p2_ce_list)} 회차")

    # Phase 2 결과
    if p2_ce_list:
        p2_mean_ce = np.mean(p2_ce_list)
        p2_freq_mean_ce = np.mean(p2_freq_ce_list) if p2_freq_ce_list else float("inf")
        p2_mean_mae = np.mean(p2_mae_list)
        p2_wins = p2_mean_ce < p2_freq_mean_ce
        print(f"\n[Phase 2 끝수합]")
        print(f"  Predictor CE: {p2_mean_ce:.4f}")
        print(f"  Frequency CE: {p2_freq_mean_ce:.4f}")
        print(f"  MAE: {p2_mean_mae:.2f}")
        print(f"  PASS: {p2_wins} (predictor CE < freq CE)")

    # Phase 3 결과
    if p3_ce_list:
        p3_mean_ce = np.mean(p3_ce_list)
        p3_freq_mean_ce = np.mean(p3_freq_ce_list) if p3_freq_ce_list else float("inf")
        p3_mean_mae = np.mean(p3_mae_list)
        p3_wins = p3_mean_ce < p3_freq_mean_ce
        print(f"\n[Phase 3 AC]")
        print(f"  Predictor CE: {p3_mean_ce:.4f}")
        print(f"  Frequency CE: {p3_freq_mean_ce:.4f}")
        print(f"  MAE: {p3_mean_mae:.2f}")
        print(f"  PASS: {p3_wins} (predictor CE < freq CE)")

    print("\n검증 완료.")


if __name__ == "__main__":
    main()
