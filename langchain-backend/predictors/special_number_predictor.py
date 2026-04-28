"""SpecialNumberPredictor — 소수/합성수/1/삼각수/제곱수/동형수 단일 카테고리 카운트 분류기.

Master Plan Stage 1 Phase 1 적용 — 6 target_type 을 단일 클래스로 통합.

각 target_type 은 매 회차의 (해당 집합 ∩ 6번호) 카운트를 학습:
  - prime: 소수 14개 ({2,3,5,7,11,13,17,19,23,29,31,37,41,43})
  - composite: 합성수 30개 (4~45 중 1·소수 제외)
  - one: 1 출현 0/1 (M=1)
  - triangular: 삼각수 9개 ({1,3,6,10,15,21,28,36,45})
  - square: 제곱수 6개 ({1,4,9,16,25,36})
  - twin: 동형수 4개 ({11,22,33,44})

scalar_features.build_scalar_features 를 카운트 시계열에 적용 (lag/rolling/zscore/diff/...).
"""

from __future__ import annotations

import os
import pickle
from typing import Optional

import numpy as np

import config
from features.scalar_features import (
    DEFAULT_CFG as SCALAR_CFG,
    ScalarFeatureConfig,
    build_scalar_features,
)
from predictors.independent_count_predictor import IndependentCountPredictor


# ────────────────── target_type 메타 ──────────────────


_VALID_TYPES: tuple[str, ...] = (
    "prime",
    "composite",
    "one",
    "triangular",
    "square",
    "twin",
)


def _resolve_target_set(target_type: str) -> set[int]:
    """target_type 의 집합 (1~45)."""
    if target_type == "prime":
        return set(int(p) for p in config.PRIMES)
    if target_type == "composite":
        primes = set(int(p) for p in config.PRIMES)
        return {n for n in range(2, 46) if n not in primes}
    if target_type == "one":
        return {1}
    if target_type == "triangular":
        return set(int(t) for t in config.TRIANGULARS)
    if target_type == "square":
        return set(int(s) for s in config.SQUARES)
    if target_type == "twin":
        return {11, 22, 33, 44}
    raise ValueError(f"unknown target_type={target_type}")


def _resolve_meta(target_type: str) -> tuple[int, int]:
    """(n_classes, pool_size) — pool_size = M (집합 카디널리티)."""
    if target_type not in _VALID_TYPES:
        raise ValueError(
            f"unknown target_type={target_type}, expected one of {_VALID_TYPES}"
        )

    pool = len(_resolve_target_set(target_type))

    # one: 0 또는 1 만 가능. n_classes=2 이면 여러 base 가 단일 클래스 학습 시 실패.
    # 안전하게 7-class 유지 (P(0), P(1) 만 의미). twin: M=4 라 7-class 중 0~4 만 의미.
    n_classes = 7
    return n_classes, pool


def _recommended_models() -> tuple[str, ...]:
    """모든 target_type 공통 추천."""
    return ("xgboost", "catboost", "markov", "bayesian_nn")


# ────────────────── 카운트 추출 ──────────────────


def _count_for_target(target_type: str, numbers: list[int]) -> int:
    """단일 회차 6번호 ∩ 집합 카운트."""
    target_set = _resolve_target_set(target_type)
    return sum(1 for n in numbers if int(n) in target_set)


# ────────────────── 학습 라벨 보정 ──────────────────


def _ensure_all_classes_present(
    X: np.ndarray, Y: np.ndarray, n_classes: int
) -> tuple[np.ndarray, np.ndarray]:
    """누락 클래스마다 평균 feature row + 라벨을 prepend (xgboost num_class 보정)."""
    if X.shape[0] == 0:
        return X, Y
    present = set(int(v) for v in Y.flatten().tolist())
    missing = [c for c in range(int(n_classes)) if c not in present]
    if not missing:
        return X, Y
    mean_row = X.mean(axis=0, keepdims=True)
    pad_X = np.repeat(mean_row, len(missing), axis=0).astype(X.dtype)
    pad_Y = np.array(missing, dtype=Y.dtype).reshape(-1, 1)
    new_X = np.concatenate([pad_X, X], axis=0)
    new_Y = np.concatenate([pad_Y, Y], axis=0)
    return new_X, new_Y


# ────────────────── feature dict → vector ──────────────────


def _features_dict_to_vector(
    feats: dict, feature_names: Optional[list[str]] = None
) -> tuple[np.ndarray, list[str]]:
    if feature_names is None:
        feature_names = sorted(feats.keys())
    vec = np.array(
        [float(feats.get(k, 0.0)) for k in feature_names], dtype=np.float32
    )
    return vec, feature_names


# ────────────────── SpecialNumberPredictor ──────────────────


class SpecialNumberPredictor:
    """특수번호 6 변형 (prime/composite/one/triangular/square/twin) 통합 분류기.

    내부에 IndependentCountPredictor (n_categories=1) 를 보관.
    """

    def __init__(
        self,
        target_type: str,
        feature_dim: int = 0,
        active_models: Optional[tuple[str, ...]] = None,
        feature_cfg: ScalarFeatureConfig = SCALAR_CFG,
    ):
        self.target_type = target_type
        n_cls, pool = _resolve_meta(target_type)
        self.n_classes = n_cls
        self.pool_size = pool
        self.feature_dim = feature_dim
        self.feature_cfg = feature_cfg
        self.active_models = active_models or _recommended_models()

        self._feature_names: Optional[list[str]] = None
        self._icp: Optional[IndependentCountPredictor] = None
        self._is_trained = False

    # ────── feature ──────

    def build_features(self, history: np.ndarray) -> np.ndarray:
        """count 시계열 → scalar feature vector. shape (feature_dim,)."""
        feats = build_scalar_features(history, cfg=self.feature_cfg)
        vec, names = _features_dict_to_vector(feats, self._feature_names)
        if self._feature_names is None:
            self._feature_names = names
            self.feature_dim = len(names)
        return vec

    # ────── 시계열/매트릭스 ──────

    def _extract_count_series(self, draws: list[dict]) -> np.ndarray:
        """draws → 시간순 카운트 시계열."""
        ordered = sorted(draws, key=lambda d: int(d.get("round", 0)))
        counts = [
            int(_count_for_target(self.target_type, d.get("numbers", [])))
            for d in ordered
        ]
        return np.array(counts, dtype=np.int64)

    def _build_training_matrix(
        self, draws: list[dict], min_history: int = 20
    ) -> tuple[np.ndarray, np.ndarray]:
        ordered = sorted(draws, key=lambda d: int(d.get("round", 0)))
        counts = self._extract_count_series(ordered)
        rng_offset = max(int(min_history), 1)

        X_rows: list[np.ndarray] = []
        Y_rows: list[int] = []
        for i in range(rng_offset, len(ordered)):
            history = counts[:i].astype(np.float64)
            vec = self.build_features(history)
            X_rows.append(vec)
            cnt = int(counts[i])
            cnt = max(0, min(cnt, self.n_classes - 1))
            Y_rows.append(cnt)

        if not X_rows:
            return np.zeros((0, max(self.feature_dim, 1)), dtype=np.float32), np.zeros(
                (0, 1), dtype=np.int64
            )
        X = np.stack(X_rows, axis=0)
        Y = np.array(Y_rows, dtype=np.int64).reshape(-1, 1)
        return X, Y

    # ────── 학습 ──────

    def train(
        self,
        draws: list[dict],
        min_history: int = 20,
        val_ratio: float = 0.0,
    ) -> dict:
        if not draws:
            raise ValueError("empty draws")

        X, Y = self._build_training_matrix(draws, min_history=min_history)
        if X.shape[0] < 5:
            raise ValueError(
                f"insufficient training rows: got {X.shape[0]} (min_history={min_history})"
            )

        X, Y = _ensure_all_classes_present(X, Y, self.n_classes)

        self.feature_dim = int(X.shape[1])
        self._icp = IndependentCountPredictor(
            indicator_name=f"special_number::{self.target_type}",
            n_categories=1,
            category_labels=[self.target_type],
            n_classes=self.n_classes,
            feature_dim=self.feature_dim,
            active_models=self.active_models,
            category_pool_sizes=[self.pool_size],
        )

        if val_ratio and 0.0 < val_ratio < 0.5:
            n_val = max(int(len(X) * val_ratio), 1)
            X_tr, X_val = X[:-n_val], X[-n_val:]
            Y_tr, Y_val = Y[:-n_val], Y[-n_val:]
            history = self._icp.train(X_tr, Y_tr, X_val=X_val, Y_val=Y_val)
        else:
            history = self._icp.train(X, Y)

        self._is_trained = True
        history["target_type"] = self.target_type
        history["n_classes"] = self.n_classes
        history["pool_size"] = self.pool_size
        history["feature_dim"] = self.feature_dim
        history["n_train_rows"] = int(X.shape[0])
        return history

    # ────── 추론 ──────

    def predict(self, draws_so_far: list[dict], min_history: int = 1) -> dict:
        if not self._is_trained or self._icp is None:
            return self._baseline_payload()
        if not draws_so_far:
            return self._baseline_payload()

        counts = self._extract_count_series(draws_so_far)
        if len(counts) < min_history:
            return self._baseline_payload()

        vec = self.build_features(counts.astype(np.float64))
        X = vec.reshape(1, -1).astype(np.float32)
        out = self._icp.predict(X)
        payload = out.per_category.get(self.target_type, {}).copy()
        payload["target_type"] = self.target_type
        payload["pool_size"] = self.pool_size
        payload["n_classes"] = self.n_classes

        top_class = int(payload.get("top_class", 0))
        top_prob = float(payload.get("top_class_prob", 0.0))
        payload["narrative"] = (
            f"{self.target_type} pool {self.pool_size} expected {top_class} "
            f"out of {self.pool_size} (P={top_prob * 100:.1f}%)"
        )
        return payload

    def _baseline_payload(self) -> dict:
        uniform = [1.0 / self.n_classes] * self.n_classes
        return {
            "target_type": self.target_type,
            "pool_size": self.pool_size,
            "n_classes": self.n_classes,
            "absolute_dist": uniform,
            "expected_count": float(np.mean(np.arange(self.n_classes))),
            "current_pool_size": self.pool_size,
            "expected_ratio": float(np.mean(np.arange(self.n_classes)))
            / max(self.pool_size, 1),
            "top_class": 0,
            "top_class_prob": 1.0 / self.n_classes,
            "narrative": f"{self.target_type} not trained, uniform prior",
            "model_contributions": {},
        }

    # ────── XAI ──────

    def explain(self) -> dict:
        if self._icp is None:
            return {
                "target_type": self.target_type,
                "is_trained": False,
                "n_classes": self.n_classes,
                "pool_size": self.pool_size,
                "active_models": list(self.active_models),
            }
        info = self._icp.explain()
        info["target_type"] = self.target_type
        info["is_trained"] = self._is_trained
        return info

    # ────── persistence ──────

    def save(self, path: str) -> str:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        meta = {
            "target_type": self.target_type,
            "n_classes": self.n_classes,
            "pool_size": self.pool_size,
            "feature_dim": self.feature_dim,
            "active_models": list(self.active_models),
            "feature_names": self._feature_names,
            "is_trained": self._is_trained,
        }
        with open(path, "wb") as f:
            pickle.dump(meta, f)
        if self._icp is not None and self._is_trained:
            self._icp.save(path + ".icp")
        return path

    def load(self, path: str) -> None:
        with open(path, "rb") as f:
            meta = pickle.load(f)
        self.target_type = meta["target_type"]
        self.n_classes = int(meta["n_classes"])
        self.pool_size = int(meta["pool_size"])
        self.feature_dim = int(meta.get("feature_dim", 0))
        self.active_models = tuple(meta.get("active_models", ()))
        self._feature_names = meta.get("feature_names")
        self._is_trained = bool(meta.get("is_trained", False))

        icp_path = path + ".icp"
        if self._is_trained and os.path.exists(icp_path):
            self._icp = IndependentCountPredictor(
                indicator_name=f"special_number::{self.target_type}",
                n_categories=1,
                category_labels=[self.target_type],
                n_classes=self.n_classes,
                feature_dim=self.feature_dim,
                active_models=self.active_models,
                category_pool_sizes=[self.pool_size],
            )
            self._icp.load(icp_path)


# ────────────────── smoke ──────────────────


def _generate_fake_draws(n_rounds: int, seed: int = config.RANDOM_SEED) -> list[dict]:
    rng = np.random.default_rng(seed)
    draws: list[dict] = []
    pool = np.arange(1, 46)
    for r in range(n_rounds):
        nums = sorted(rng.choice(pool, size=6, replace=False).tolist())
        bonus_pool = [n for n in pool if n not in nums]
        bonus = int(rng.choice(bonus_pool))
        draws.append({"round": 2000 + r, "numbers": nums, "bonus": bonus})
    return list(reversed(draws))


def main() -> None:
    """python -m predictors.special_number_predictor --smoke --type prime."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--type", default="prime", choices=list(_VALID_TYPES))
    parser.add_argument("--rounds", type=int, default=100)
    args = parser.parse_args()

    if not args.smoke:
        parser.print_help()
        return

    print(f"[SpecialNumberPredictor] smoke target_type={args.type}")
    draws = _generate_fake_draws(args.rounds)
    print(f"  generated {len(draws)} fake draws")

    smoke_models = ("xgboost", "markov")
    predictor = SpecialNumberPredictor(
        target_type=args.type, active_models=smoke_models
    )

    print("  training...")
    history = predictor.train(draws, min_history=20)
    print(
        f"    rows={history['n_train_rows']} feature_dim={history['feature_dim']} "
        f"n_classes={history['n_classes']} pool_size={history['pool_size']}"
    )
    trained_models = history.get("per_category", {}).get(0, {}).get(
        "trained_models", []
    )
    print(f"    trained_models={trained_models}")

    print("  predicting...")
    out = predictor.predict(draws)
    dist = out.get("absolute_dist", [])
    dist_str = ", ".join(f"{p:.3f}" for p in dist)
    print(
        f"    top_class={out.get('top_class')} P={out.get('top_class_prob', 0.0):.3f}"
    )
    print(f"    dist=[{dist_str}]")
    print(f"    narrative: {out.get('narrative')}")
    print("  smoke OK")


if __name__ == "__main__":
    main()
