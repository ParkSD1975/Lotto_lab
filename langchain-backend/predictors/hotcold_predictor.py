"""HotColdPredictor — 핫콜드 12 카테고리 (4 윈도우 x 3 그룹) 동적 풀 분류기.

Stage 1 / Phase 1. unified-plan #6 결정에 따라:
  - 4 윈도우: 5 / 10 / 15 / 20 회차
  - 3 그룹 (각 윈도우 내):
      Hot     : freq >= mean + 1*std
      Neutral : mean - 1*std < freq < mean + 1*std
      Cold    : freq <= mean - 1*std
  - 총 12 카테고리: w_5_hot, w_5_neutral, w_5_cold, w_10_hot, ..., w_20_cold

12 카테고리 모두 동적 풀 (매 회차 풀 크기 변동). 각 카테고리 출현 카운트 0~6 을
7-class softmax 로 학습한다 (ICP 베이스 활용).
"""

from __future__ import annotations

import os
import pickle
from typing import Optional

import numpy as np

import config
from predictors.independent_count_predictor import IndependentCountPredictor


WINDOWS = (5, 10, 15, 20)
GROUPS = ("hot", "neutral", "cold")
N_CATEGORIES = len(WINDOWS) * len(GROUPS)  # 12


def _category_label(window: int, group: str) -> str:
    return f"w_{window}_{group}"


def _all_labels() -> list[str]:
    return [_category_label(w, g) for w in WINDOWS for g in GROUPS]


def _draw_numbers(d: dict) -> list[int]:
    """draw dict 에서 번호 6개를 안전하게 추출."""
    nums = d.get("numbers")
    if nums is None:
        nums = d.get("nums") or []
    return [int(n) for n in nums if 1 <= int(n) <= 45]


def _augment_class_coverage(
    X: np.ndarray, Y: np.ndarray, n_classes: int = 7
) -> tuple[np.ndarray, np.ndarray]:
    """ICP/XGBoost 학습 안전망 — 누락 클래스 더미 샘플 보충."""
    if X.shape[0] == 0:
        return X, Y
    n_cat = Y.shape[1]
    avg_row = X.mean(axis=0, keepdims=True)
    extra_X: list[np.ndarray] = []
    extra_Y: list[np.ndarray] = []
    for ci in range(n_cat):
        present = set(np.unique(Y[:, ci]).tolist())
        missing = [c for c in range(n_classes) if c not in present]
        for cls in missing:
            extra_X.append(avg_row.copy())
            row = Y[0:1].copy()
            row[0, ci] = cls
            extra_Y.append(row)
    if not extra_X:
        return X, Y
    X_aug = np.concatenate([X] + extra_X, axis=0)
    Y_aug = np.concatenate([Y] + extra_Y, axis=0)
    return X_aug, Y_aug


class HotColdPredictor:
    """핫콜드 12 카테고리 동적 풀 predictor.

    AE 는 풀 변동 감지에 강하다. 기본 active_models 에 ae 포함.
    """

    def __init__(
        self,
        feature_dim: int = 36,
        active_models: tuple[str, ...] = (
            "xgboost", "catboost", "tabnet", "markov", "ae", "tft",
        ),
    ):
        self.feature_dim = feature_dim
        self.active_models = active_models
        self.category_labels = _all_labels()

        icp_models = tuple(m for m in active_models if m != "ae")
        if not icp_models:
            icp_models = ("xgboost", "markov")

        self.icp = IndependentCountPredictor(
            indicator_name="hotcold_12",
            n_categories=N_CATEGORIES,
            category_labels=self.category_labels,
            n_classes=7,
            feature_dim=feature_dim,
            active_models=icp_models,
            category_pool_sizes=[1] * N_CATEGORIES,
        )

        self._ae_trainer = None
        self._is_trained = False

    # ────── 빈도 / 분류 ──────

    def compute_window_freq(self, draws_so_far: list[dict], window: int) -> dict[int, int]:
        """최근 window 회차에서 1~45 각 번호의 출현 횟수."""
        sub = draws_so_far[:window]
        freq = {n: 0 for n in range(1, 46)}
        for d in sub:
            for n in _draw_numbers(d):
                freq[n] += 1
        return freq

    def classify_hot_cold(self, freq: dict[int, int], window: int) -> dict[str, list[int]]:
        """평균 +- 1 sigma 로 Hot/Neutral/Cold 분류.

        45 개 번호의 빈도를 기준으로 산출. window 미사용이지만 추후 확장 여지.
        """
        values = np.array([freq[n] for n in range(1, 46)], dtype=np.float32)
        mean = float(values.mean())
        std = float(values.std())

        hot, neutral, cold = [], [], []
        upper = mean + std
        lower = mean - std
        for n in range(1, 46):
            v = freq[n]
            if v >= upper and std > 0:
                hot.append(n)
            elif v <= lower and std > 0:
                cold.append(n)
            else:
                neutral.append(n)
        return {"hot": hot, "neutral": neutral, "cold": cold}

    def compute_all_categories(self, draws_so_far: list[dict]) -> dict[str, list[int]]:
        """12 카테고리 동적 풀."""
        result: dict[str, list[int]] = {}
        for w in WINDOWS:
            freq = self.compute_window_freq(draws_so_far, w)
            cls = self.classify_hot_cold(freq, w)
            for g in GROUPS:
                result[_category_label(w, g)] = cls[g]
        return result

    # ────── feature ──────

    def build_features(self, draws_so_far: list[dict]) -> np.ndarray:
        """단일 feature 행 (D,).

        구성:
          - 4 윈도우 x [mean, std, max, min, sum] = 20
          - 12 카테고리 풀 크기 = 12
          - 4 윈도우 미출현 번호 갯수 = 4
        """
        if not draws_so_far:
            return np.zeros(self.feature_dim, dtype=np.float32)

        feat: list[float] = []
        for w in WINDOWS:
            freq = self.compute_window_freq(draws_so_far, w)
            values = np.array([freq[n] for n in range(1, 46)], dtype=np.float32)
            feat.extend([
                float(values.mean()),
                float(values.std()),
                float(values.max()),
                float(values.min()),
                float(values.sum()),
            ])

        cats = self.compute_all_categories(draws_so_far)
        for label in self.category_labels:
            feat.append(float(len(cats.get(label, []))))

        for w in WINDOWS:
            freq = self.compute_window_freq(draws_so_far, w)
            miss = sum(1 for n in range(1, 46) if freq[n] == 0)
            feat.append(float(miss))

        arr = np.array(feat, dtype=np.float32)
        if arr.size < self.feature_dim:
            arr = np.pad(arr, (0, self.feature_dim - arr.size))
        elif arr.size > self.feature_dim:
            arr = arr[: self.feature_dim]
        return arr

    # ────── 학습 데이터 ──────

    def _build_training_set(self, draws: list[dict]) -> tuple[np.ndarray, np.ndarray, list[list[int]]]:
        """과거 시점 t 마다 X = features(t), Y = 다음 회차 12 카테고리 출현 카운트."""
        N = len(draws)
        if N < max(WINDOWS) + 2:
            return (
                np.zeros((0, self.feature_dim), dtype=np.float32),
                np.zeros((0, N_CATEGORIES), dtype=np.int64),
                [],
            )

        X_rows: list[np.ndarray] = []
        Y_rows: list[list[int]] = []
        size_rows: list[list[int]] = []

        for t in range(N - 1, 0, -1):
            history = draws[t:]
            if len(history) < max(WINDOWS):
                continue
            x = self.build_features(history)
            cats = self.compute_all_categories(history)
            target_nums = set(_draw_numbers(draws[t - 1]))

            counts: list[int] = []
            sizes: list[int] = []
            for label in self.category_labels:
                pool = set(cats.get(label, []))
                cnt = len(pool & target_nums)
                if cnt > 6:
                    cnt = 6
                counts.append(cnt)
                sizes.append(len(pool))

            X_rows.append(x)
            Y_rows.append(counts)
            size_rows.append(sizes)

        X = np.stack(X_rows, axis=0).astype(np.float32) if X_rows else np.zeros((0, self.feature_dim), dtype=np.float32)
        Y = np.array(Y_rows, dtype=np.int64) if Y_rows else np.zeros((0, N_CATEGORIES), dtype=np.int64)
        return X, Y, size_rows

    # ────── 학습 ──────

    def train(self, draws: list[dict]) -> dict:
        """draws (최신순) 로 ICP 학습."""
        X, Y, size_rows = self._build_training_set(draws)
        if X.shape[0] < 5:
            print("[HotCold] not enough samples for training")
            return {"success": False, "reason": "insufficient_data"}

        avg_pools = np.mean(np.array(size_rows, dtype=np.float32), axis=0).astype(int).tolist()
        for ci, head in enumerate(self.icp.heads):
            head.pool_size = max(1, int(avg_pools[ci]))
        self.icp.category_pool_sizes = [h.pool_size for h in self.icp.heads]

        cut = max(1, int(X.shape[0] * 0.8))
        X_tr, Y_tr = _augment_class_coverage(X[:cut], Y[:cut], n_classes=7)
        X_val, Y_val = X[cut:], Y[cut:]
        if X_val.shape[0] > 0:
            X_val, Y_val = _augment_class_coverage(X_val, Y_val, n_classes=7)
        history = self.icp.train(X_tr, Y_tr, X_val=X_val if X_val.shape[0] > 0 else None,
                                 Y_val=Y_val if X_val.shape[0] > 0 else None)

        if "ae" in self.active_models:
            self._train_ae(draws)

        self._is_trained = True
        return {"success": True, "samples": int(X.shape[0]), "icp_history": history}

    def _train_ae(self, draws: list[dict]) -> None:
        try:
            from models.autoencoder_model import AutoencoderTrainer
            self._ae_trainer = AutoencoderTrainer()
            self._ae_trainer.train(draws)
        except Exception as e:
            print(f"[HotCold] AE train skipped: {e}")
            self._ae_trainer = None

    # ────── 추론 ──────

    def predict(self, draws_so_far: list[dict]) -> dict:
        """현재 회차 시점 12 카테고리 분포 (동적 M 반영)."""
        if not draws_so_far:
            return {"per_category": {}, "narrative": "no draws"}

        cats = self.compute_all_categories(draws_so_far)
        dynamic_sizes = [len(cats.get(label, [])) for label in self.category_labels]
        for ci, head in enumerate(self.icp.heads):
            head.pool_size = max(1, dynamic_sizes[ci])
        self.icp.category_pool_sizes = list(dynamic_sizes)

        x = self.build_features(draws_so_far)
        X = np.expand_dims(x, axis=0)
        out = self.icp.predict(X)

        per_category = {}
        for ci, label in enumerate(self.category_labels):
            payload = dict(out.per_category.get(label, {}))
            payload["members"] = cats.get(label, [])
            payload["dynamic_pool_size"] = dynamic_sizes[ci]
            top_class = payload.get("top_class", 0)
            top_prob = payload.get("top_class_prob", 0.0)
            M = dynamic_sizes[ci]
            payload["narrative"] = (
                f"{label} pool {M} expected {top_class} out of {M} "
                f"(P={top_prob * 100:.1f}%)"
            )
            per_category[label] = payload

        return {
            "indicator": "hotcold_12",
            "per_category": per_category,
            "dynamic_pool_sizes": dynamic_sizes,
            "windows": list(WINDOWS),
            "groups": list(GROUPS),
        }

    # ────── persistence ──────

    def save(self, path: str) -> str:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        icp_path = path + ".icp.pkl"
        self.icp.save(icp_path)
        meta = {
            "feature_dim": self.feature_dim,
            "active_models": list(self.active_models),
            "is_trained": self._is_trained,
            "icp_path": icp_path,
        }
        with open(path, "wb") as f:
            pickle.dump(meta, f)
        return path

    def load(self, path: str) -> None:
        with open(path, "rb") as f:
            meta = pickle.load(f)
        self.feature_dim = meta["feature_dim"]
        self.active_models = tuple(meta["active_models"])
        self._is_trained = meta["is_trained"]
        self.icp.load(meta["icp_path"])


# ────────────────── CLI smoke ──────────────────


def _make_fake_draws(n: int = 100, seed: int = 42) -> list[dict]:
    rng = np.random.default_rng(seed)
    draws = []
    for i in range(n):
        nums = sorted(rng.choice(np.arange(1, 46), size=6, replace=False).tolist())
        draws.append({"round": n - i, "numbers": nums})
    return draws


def main():
    """python -m predictors.hotcold_predictor --smoke."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()

    if not args.smoke:
        return

    draws = _make_fake_draws(100, seed=config.RANDOM_SEED)
    pred = HotColdPredictor(
        feature_dim=36,
        active_models=("xgboost", "markov"),
    )

    print("[HotCold] training (smoke)...")
    res = pred.train(draws)
    print(f"  result: success={res.get('success')} samples={res.get('samples')}")

    print("\n[HotCold] predict (smoke)...")
    out = pred.predict(draws[:50])
    print(f"  dynamic_pool_sizes (12): {out['dynamic_pool_sizes']}")
    sample_labels = ["w_5_hot", "w_10_neutral", "w_20_cold"]
    for label in sample_labels:
        payload = out["per_category"].get(label, {})
        print(f"  {label}: M={payload.get('dynamic_pool_size')} top={payload.get('top_class')} P={payload.get('top_class_prob', 0):.3f}")
        print(f"    narrative: {payload.get('narrative')}")


if __name__ == "__main__":
    main()
