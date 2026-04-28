"""G-5 진화: 베이스라인 비교 자동화.

각 predictor가 베이스라인을 이기는지 검증. Stage 1~6 검증 게이트에서 사용.

베이스라인 종류:
  - rolling_mean: 직전 N회차 평균 (스칼라 지표용)
  - uniform: 1/N_classes (카테고리 분류용)
  - frequency: 학습 데이터 빈도 분포 (분포형 지표용)
  - last_value: 직전 회차 값 그대로 (변화 적은 지표용)

지표:
  - MAE / RMSE (스칼라)
  - CrossEntropy / KL (분포)
  - Top-k accuracy (분류)
"""

from __future__ import annotations

from collections import Counter
from typing import Callable, Optional

import numpy as np


class BaselineRunner:
    """베이스라인 비교 + 개선율 출력."""

    @staticmethod
    def rolling_mean(history: np.ndarray, window: int = 20) -> float:
        """직전 window 회차 평균. history: (T,) 또는 (T, D)."""
        if len(history) == 0:
            return 0.0
        recent = history[-window:]
        return recent.mean(axis=0)

    @staticmethod
    def uniform_distribution(n_classes: int) -> np.ndarray:
        return np.full(n_classes, 1.0 / n_classes)

    @staticmethod
    def frequency_distribution(history: np.ndarray, n_classes: int) -> np.ndarray:
        """history: (T,) 정수 라벨. 빈도 분포 normalize."""
        if len(history) == 0:
            return BaselineRunner.uniform_distribution(n_classes)
        counter = Counter(int(x) for x in history)
        total = sum(counter.values())
        return np.array([counter.get(c, 0) / total for c in range(n_classes)])

    @staticmethod
    def last_value(history: np.ndarray) -> float:
        return history[-1] if len(history) > 0 else 0.0

    # ────────────────── 메트릭 ──────────────────

    @staticmethod
    def mae(pred: np.ndarray, target: np.ndarray) -> float:
        return float(np.mean(np.abs(pred - target)))

    @staticmethod
    def rmse(pred: np.ndarray, target: np.ndarray) -> float:
        return float(np.sqrt(np.mean((pred - target) ** 2)))

    @staticmethod
    def cross_entropy(pred_dist: np.ndarray, target_label: int, eps: float = 1e-9) -> float:
        return -float(np.log(pred_dist[target_label] + eps))

    @staticmethod
    def kl_divergence(pred_dist: np.ndarray, target_dist: np.ndarray, eps: float = 1e-9) -> float:
        p = np.asarray(pred_dist) + eps
        q = np.asarray(target_dist) + eps
        return float(np.sum(p * np.log(p / q)))

    @staticmethod
    def topk_accuracy(pred_ranking: list[int], target_label: int, k: int = 5) -> float:
        return 1.0 if target_label in pred_ranking[:k] else 0.0

    # ────────────────── 비교 ──────────────────

    def compare_scalar(
        self,
        predictor_fn: Callable[[np.ndarray], float],
        history: np.ndarray,
        targets: np.ndarray,
        window: int = 20,
    ) -> dict:
        """walk-forward로 predictor vs rolling_mean 베이스라인 MAE 비교.

        Returns:
            {"predictor_mae", "baseline_mae", "improvement_pct"}
        """
        predictor_preds, baseline_preds = [], []
        for i in range(window, len(history)):
            sub_history = history[:i]
            predictor_preds.append(predictor_fn(sub_history))
            baseline_preds.append(self.rolling_mean(sub_history, window))

        actual = targets[window:]
        p_mae = self.mae(np.array(predictor_preds), actual)
        b_mae = self.mae(np.array(baseline_preds), actual)
        improvement = (b_mae - p_mae) / max(b_mae, 1e-9) * 100
        return {
            "predictor_mae": p_mae,
            "baseline_mae": b_mae,
            "improvement_pct": improvement,
            "wins": p_mae < b_mae,
        }

    def compare_distribution(
        self,
        predictor_fn: Callable[[np.ndarray], np.ndarray],
        history: np.ndarray,
        targets: np.ndarray,
        n_classes: int,
        window: int = 50,
    ) -> dict:
        """분포형 predictor vs uniform/frequency 베이스라인 CE 비교."""
        p_ce_total, u_ce_total, f_ce_total, n = 0.0, 0.0, 0.0, 0
        for i in range(window, len(history)):
            sub = history[:i]
            target_label = int(targets[i])
            p = predictor_fn(sub)
            u = self.uniform_distribution(n_classes)
            f = self.frequency_distribution(sub, n_classes)
            p_ce_total += self.cross_entropy(p, target_label)
            u_ce_total += self.cross_entropy(u, target_label)
            f_ce_total += self.cross_entropy(f, target_label)
            n += 1

        if n == 0:
            return {"insufficient_data": True}

        p_ce = p_ce_total / n
        u_ce = u_ce_total / n
        f_ce = f_ce_total / n
        return {
            "predictor_ce": p_ce,
            "uniform_ce": u_ce,
            "frequency_ce": f_ce,
            "improvement_vs_uniform_pct": (u_ce - p_ce) / max(u_ce, 1e-9) * 100,
            "improvement_vs_frequency_pct": (f_ce - p_ce) / max(f_ce, 1e-9) * 100,
            "wins_uniform": p_ce < u_ce,
            "wins_frequency": p_ce < f_ce,
        }


def main():
    """python -m langchain-backend.validation.baseline_runner --smoke.

    Stage 0 검증 게이트: rolling_mean 베이스라인 출력.
    """
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()

    runner = BaselineRunner()
    if args.smoke:
        # 1100 회차 가짜 sum 데이터 (mean 138, std 30)
        rng = np.random.default_rng(42)
        sums = rng.normal(138, 30, size=1100)
        result = runner.compare_scalar(
            predictor_fn=lambda h: h[-5:].mean(),  # 가짜 predictor: 5회 평균
            history=sums,
            targets=sums,
            window=20,
        )
        print("[BaselineRunner] smoke test - fake sum data")
        print(f"  predictor_mae    = {result['predictor_mae']:.3f}")
        print(f"  baseline_mae     = {result['baseline_mae']:.3f}")
        print(f"  improvement_pct  = {result['improvement_pct']:.2f}%")
        print(f"  wins             = {result['wins']}")


if __name__ == "__main__":
    main()
