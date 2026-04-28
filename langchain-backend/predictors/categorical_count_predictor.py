"""CategoricalCountPredictor — 카운트형 카테고리 지표 (5 변형) 통합 7-class 분류기.

Master Plan Stage 1 Phase 1 적용 — 고저(low_high) / 홀짝(odd_even) /
이월수 정확(carryover_exact) / 이월수 보너스포함(carryover_with_bonus) /
이웃수(neighbor) / 연번(consecutive) 의 6 target_type 을 단일 클래스로 통합.

ICP(IndependentCountPredictor) 베이스를 컴포지션으로 활용해 11 base 모델을
재구현하지 않고, target_type 에 맞는 single-category 7-class 분류만 한다.

각 target_type 은 매 회차의 단일 정수(count) 시계열을 학습:
  - low_high: 1~22 의 개수 (0~6)
  - odd_even: 홀수의 개수 (0~6)
  - carryover_exact: 직전 6번호 ∩ 현재 6번호 (0~6)
  - carryover_with_bonus: 직전 (6+보너스) ∩ 현재 6번호 (0~6)
  - neighbor: 직전 6번호 ±1 풀 ∩ 현재 6번호 (0~6)
  - consecutive: 정렬한 현재 6번호 인접쌍 개수 (0~5)
"""

from __future__ import annotations

import os
import pickle
from typing import Any, Optional

import numpy as np

import config
from features.categorical_features import (
    CategoricalFeatureConfig,
    DEFAULT_CFG,
    build_categorical_features,
)
from predictors.independent_count_predictor import (
    IndependentCountPredictor,
    PredictorOutput,
)


# ────────────────── target_type 메타 ──────────────────


_VALID_TYPES: tuple[str, ...] = (
    "low_high",
    "odd_even",
    "carryover_exact",
    "carryover_with_bonus",
    "neighbor",
    "consecutive",
)


def _resolve_meta(target_type: str) -> tuple[int, int, str]:
    """target_type 에 맞는 (n_classes, pool_size, feature_target_type) 반환.

    feature_target_type 은 features/categorical_features.py 가 인식하는
    축약 키("low_high"/"odd_even"/"carryover"/"neighbor"/"consecutive").
    """
    if target_type not in _VALID_TYPES:
        raise ValueError(
            f"unknown target_type={target_type}, expected one of {_VALID_TYPES}"
        )

    if target_type == "consecutive":
        return 6, 6, "consecutive"
    if target_type in ("low_high", "odd_even"):
        return 7, 6, target_type
    if target_type in ("carryover_exact", "carryover_with_bonus"):
        return 7, 6, "carryover"
    # neighbor
    return 7, 6, "neighbor"


def _recommended_models(target_type: str) -> tuple[str, ...]:
    """target_type 별 active_models 추천."""
    if target_type in ("carryover_exact", "carryover_with_bonus", "neighbor"):
        # GNN 집계가 강한 시그널이라 트리·attention + Markov + bayes 위주
        return ("xgboost", "catboost", "tabnet", "markov", "bayesian_nn", "mhn")
    if target_type == "consecutive":
        return ("xgboost", "catboost", "markov", "bayesian_nn", "mhn")
    # low_high / odd_even — 평형 시계열, 트리 + Markov 충분
    return ("xgboost", "catboost", "markov", "bayesian_nn")


# ────────────────── 카운트 추출기 ──────────────────


def _count_for_target(
    target_type: str,
    numbers: list[int],
    bonus: int | None,
    prev_numbers: list[int] | None,
    prev_bonus: int | None,
) -> int:
    """단일 회차의 target_type 카운트 정수."""
    nums = set(int(n) for n in numbers)

    if target_type == "low_high":
        return sum(1 for n in nums if n <= 22)

    if target_type == "odd_even":
        return sum(1 for n in nums if n % 2 == 1)

    if target_type == "carryover_exact":
        if not prev_numbers:
            return 0
        return len(nums & set(int(p) for p in prev_numbers))

    if target_type == "carryover_with_bonus":
        if not prev_numbers:
            return 0
        prev_pool = set(int(p) for p in prev_numbers)
        if prev_bonus is not None:
            prev_pool.add(int(prev_bonus))
        return len(nums & prev_pool)

    if target_type == "neighbor":
        if not prev_numbers:
            return 0
        pool: set[int] = set()
        for p in prev_numbers:
            pool.update({int(p) - 1, int(p) + 1})
        pool &= set(range(1, 46))
        return len(nums & pool)

    if target_type == "consecutive":
        s = sorted(nums)
        return sum(1 for i in range(len(s) - 1) if s[i + 1] - s[i] == 1)

    raise ValueError(f"unknown target_type={target_type}")


# ────────────────── 학습 라벨 보정 ──────────────────


def _ensure_all_classes_present(
    X: np.ndarray, Y: np.ndarray, n_classes: int
) -> tuple[np.ndarray, np.ndarray]:
    """xgboost 류가 학습 시 라벨 unique 만으로 num_class 를 추론하는 문제 방지.

    누락 클래스마다 평균 feature row + 해당 라벨을 1행씩 prepend.
    데이터 양이 50회+ 라면 분포 영향은 미미.
    """
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
    """feature dict → (vector, names) tuple. names 미제공 시 생성."""
    if feature_names is None:
        feature_names = sorted(feats.keys())
    vec = np.array(
        [float(feats.get(k, 0.0)) for k in feature_names], dtype=np.float32
    )
    return vec, feature_names


# ────────────────── CategoricalCountPredictor ──────────────────


class CategoricalCountPredictor:
    """카운트형 카테고리 지표 통합 분류기.

    내부에 IndependentCountPredictor (n_categories=1) 를 보관하고
    target_type 별 카운트 시계열을 단일 카테고리로 학습/추론한다.
    """

    def __init__(
        self,
        target_type: str,
        n_classes: int | None = None,
        feature_dim: int = 0,
        active_models: Optional[tuple[str, ...]] = None,
        feature_cfg: CategoricalFeatureConfig = DEFAULT_CFG,
    ):
        self.target_type = target_type
        n_cls, pool, feat_key = _resolve_meta(target_type)
        self.n_classes = int(n_classes) if n_classes is not None else n_cls
        self.pool_size = pool
        self._feature_target_type = feat_key
        self.feature_dim = feature_dim
        self.feature_cfg = feature_cfg
        self.active_models = active_models or _recommended_models(target_type)

        self._feature_names: Optional[list[str]] = None
        self._icp: Optional[IndependentCountPredictor] = None
        self._is_trained = False

    # ────── feature ──────

    def build_features(
        self,
        history: np.ndarray,
        prev_round_numbers: list[int] | None,
        gnn_data: dict[str, Any] | None = None,
    ) -> np.ndarray:
        """단일 시점 feature vector. shape (feature_dim,)."""
        gnn_data = gnn_data or {}
        feats = build_categorical_features(
            history=history,
            target_type=self._feature_target_type,
            cfg=self.feature_cfg,
            prev_round_numbers=prev_round_numbers,
            gnn_probs=gnn_data.get("gnn_probs"),
            gnn_top10=gnn_data.get("gnn_top10"),
            gnn_edge_probs=gnn_data.get("gnn_edge_probs"),
            hot_streak=gnn_data.get("hot_streak"),
            dormancy=gnn_data.get("dormancy"),
        )
        vec, names = _features_dict_to_vector(feats, self._feature_names)
        if self._feature_names is None:
            self._feature_names = names
            self.feature_dim = len(names)
        return vec

    # ────── 시계열/매트릭스 추출 ──────

    def _extract_count_series(self, draws: list[dict]) -> np.ndarray:
        """draws (최신순) → 시간순 (T,) 카운트 시계열."""
        ordered = sorted(draws, key=lambda d: int(d.get("round", 0)))
        counts: list[int] = []
        for i, d in enumerate(ordered):
            prev_nums = ordered[i - 1].get("numbers") if i > 0 else None
            prev_bonus = ordered[i - 1].get("bonus") if i > 0 else None
            c = _count_for_target(
                self.target_type,
                d.get("numbers", []),
                d.get("bonus"),
                prev_nums,
                prev_bonus,
            )
            counts.append(int(c))
        return np.array(counts, dtype=np.int64)

    def _build_training_matrix(
        self,
        draws: list[dict],
        gnn_data_per_round: dict[int, dict] | None = None,
        min_history: int = 20,
    ) -> tuple[np.ndarray, np.ndarray]:
        """walk-forward 매트릭스. X: (N, D), Y: (N, 1)."""
        ordered = sorted(draws, key=lambda d: int(d.get("round", 0)))
        counts = self._extract_count_series(ordered)
        rng_offset = max(int(min_history), 1)

        X_rows: list[np.ndarray] = []
        Y_rows: list[int] = []

        for i in range(rng_offset, len(ordered)):
            history = counts[:i]
            prev_d = ordered[i - 1]
            prev_nums = prev_d.get("numbers")
            gd = None
            if gnn_data_per_round is not None:
                gd = gnn_data_per_round.get(int(prev_d.get("round", 0)))
            vec = self.build_features(history, prev_nums, gd)
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
        gnn_data_per_round: dict[int, dict] | None = None,
        min_history: int = 20,
        val_ratio: float = 0.0,
    ) -> dict:
        """target_type 카운트 시계열 학습. ICP 위임."""
        if not draws:
            raise ValueError("empty draws")

        X, Y = self._build_training_matrix(
            draws, gnn_data_per_round=gnn_data_per_round, min_history=min_history
        )
        if X.shape[0] < 5:
            raise ValueError(
                f"insufficient training rows after walk-forward: got {X.shape[0]} (min_history={min_history})"
            )

        # base 분류기(특히 xgboost)가 unique 라벨 개수를 자동 추론하지 않도록
        # 모든 클래스 (0..n_classes-1) 가 학습 라벨에 최소 1회 등장하게 보정.
        X, Y = _ensure_all_classes_present(X, Y, self.n_classes)

        # ICP 인스턴스 생성 (단일 카테고리)
        self.feature_dim = int(X.shape[1])
        self._icp = IndependentCountPredictor(
            indicator_name=f"categorical_count::{self.target_type}",
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

    def predict(
        self,
        draws_so_far: list[dict],
        gnn_data: dict[str, Any] | None = None,
        min_history: int = 1,
    ) -> dict:
        """가장 최근 회차 직후 다음 회차 분포 추정.

        draws_so_far: 최신순 또는 시간순 모두 허용.
        """
        if not self._is_trained or self._icp is None:
            return self._baseline_payload()
        if not draws_so_far:
            return self._baseline_payload()

        ordered = sorted(draws_so_far, key=lambda d: int(d.get("round", 0)))
        counts = self._extract_count_series(ordered)
        if len(counts) < min_history:
            return self._baseline_payload()

        latest = ordered[-1]
        prev_nums = latest.get("numbers")
        vec = self.build_features(counts, prev_nums, gnn_data)
        X = vec.reshape(1, -1).astype(np.float32)
        out = self._icp.predict(X)
        payload = out.per_category.get(self.target_type, {}).copy()
        payload["target_type"] = self.target_type
        payload["pool_size"] = self.pool_size
        payload["n_classes"] = self.n_classes

        # narrative 보강
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
            "feature_target_type": self._feature_target_type,
            "feature_dim": self.feature_dim,
            "active_models": list(self.active_models),
            "feature_names": self._feature_names,
            "is_trained": self._is_trained,
        }
        with open(path, "wb") as f:
            pickle.dump(meta, f)

        if self._icp is not None and self._is_trained:
            icp_path = path + ".icp"
            self._icp.save(icp_path)
        return path

    def load(self, path: str) -> None:
        with open(path, "rb") as f:
            meta = pickle.load(f)
        self.target_type = meta["target_type"]
        self.n_classes = int(meta["n_classes"])
        self.pool_size = int(meta["pool_size"])
        self._feature_target_type = meta["feature_target_type"]
        self.feature_dim = int(meta.get("feature_dim", 0))
        self.active_models = tuple(meta.get("active_models", ()))
        self._feature_names = meta.get("feature_names")
        self._is_trained = bool(meta.get("is_trained", False))

        icp_path = path + ".icp"
        if self._is_trained and os.path.exists(icp_path):
            self._icp = IndependentCountPredictor(
                indicator_name=f"categorical_count::{self.target_type}",
                n_categories=1,
                category_labels=[self.target_type],
                n_classes=self.n_classes,
                feature_dim=self.feature_dim,
                active_models=self.active_models,
                category_pool_sizes=[self.pool_size],
            )
            self._icp.load(icp_path)


# ────────────────── 가짜 회차 생성 + smoke ──────────────────


def _generate_fake_draws(n_rounds: int, seed: int = config.RANDOM_SEED) -> list[dict]:
    """smoke 용 가짜 lotto 회차 데이터 (최신순)."""
    rng = np.random.default_rng(seed)
    draws: list[dict] = []
    pool = np.arange(1, 46)
    for r in range(n_rounds):
        nums = sorted(rng.choice(pool, size=6, replace=False).tolist())
        bonus_pool = [n for n in pool if n not in nums]
        bonus = int(rng.choice(bonus_pool))
        draws.append({"round": 1000 + r, "numbers": nums, "bonus": bonus})
    return list(reversed(draws))


def main() -> None:
    """python -m predictors.categorical_count_predictor --smoke --type low_high."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--type", default="low_high", choices=list(_VALID_TYPES))
    parser.add_argument("--rounds", type=int, default=100)
    args = parser.parse_args()

    if not args.smoke:
        parser.print_help()
        return

    print(f"[CategoricalCountPredictor] smoke target_type={args.type}")
    draws = _generate_fake_draws(args.rounds)
    print(f"  generated {len(draws)} fake draws")

    # smoke 는 의존성 적은 모델만 사용
    smoke_models = ("xgboost", "markov")
    predictor = CategoricalCountPredictor(
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
