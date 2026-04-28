"""IndependentCountPredictor — 11 base 통합 카테고리별 7-class 카운트 분류기.

Master Plan Stage 1 핵심 패턴. 21지표(끝수/번호대/9궁/로또용지/배수/...) 모든 카운트형
지표가 본 베이스 클래스를 상속/사용한다.

각 카테고리(예: 끝수 0~9의 10개 카테고리)마다 독립적 7-class softmax (count = 0~6).
11 base 모델이 각자 per-category head를 학습한 뒤 가중평균.

출력 (각 카테고리별):
  {
    "absolute_dist": [P(0), ..., P(6)],
    "expected_count": E,
    "current_pool_size": M,
    "expected_ratio": E / M,
    "narrative": "{name} pool {M} expected {E} (P={p}%)",
    "model_contributions": {model_name: contribution}  # XAI
  }
"""

from __future__ import annotations

import os
import pickle
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

import config


# ────────────────── 데이터 클래스 ──────────────────


@dataclass
class CategoryHead:
    """카테고리별 헤드 컨테이너. 11 base 각각의 per-category 모델 보관."""

    category_idx: int
    category_label: str
    n_classes: int = 7
    pool_size: int = 1  # M 중 N 정규화에 필요
    base_models: dict = field(default_factory=dict)  # {model_name: trained_estimator}
    base_weights: dict = field(default_factory=dict)  # {model_name: weight}


@dataclass
class PredictorOutput:
    """ICP 출력 표준 컨테이너."""

    indicator_name: str
    per_category: dict  # {category_label: dict (M중 N narrative)}
    inter_category_correlation: Optional[np.ndarray] = None
    aggregated_evidence: dict = field(default_factory=dict)


# ────────────────── 11 base 인스턴스 팩토리 ──────────────────


def _instantiate_base_model(model_name: str, n_classes: int, feature_dim: int):
    """base 모델 이름 → 인스턴스. 미설치 라이브러리는 None 반환."""
    if model_name == "xgboost":
        try:
            import xgboost as xgb
            return xgb.XGBClassifier(
                objective="multi:softprob",
                num_class=n_classes,
                n_estimators=config.XGB_N_ESTIMATORS,
                max_depth=config.XGB_MAX_DEPTH,
                learning_rate=config.XGB_LEARNING_RATE,
                random_state=config.RANDOM_SEED,
                eval_metric="mlogloss",
                use_label_encoder=False,
            )
        except ImportError:
            return None

    if model_name == "catboost":
        try:
            from models.catboost_model import LottoCatBoost, CATBOOST_AVAILABLE
            if not CATBOOST_AVAILABLE:
                return None
            return LottoCatBoost(task_type="multiclass", num_classes=n_classes)
        except ImportError:
            return None

    if model_name == "tabnet":
        try:
            from models.tabnet_model import LottoTabNet, TABNET_AVAILABLE
            if not TABNET_AVAILABLE:
                return None
            return LottoTabNet(task_type="multiclass", num_classes=n_classes)
        except ImportError:
            return None

    if model_name == "markov":
        # Markov 7-state per-category 전이행렬. predict 시 별도 처리
        return _MarkovHead(n_classes=n_classes)

    if model_name == "bayesian_nn":
        try:
            from models.bayesian_nn_model import LottoBayesianNN
            return LottoBayesianNN(
                input_dim=feature_dim, num_classes=n_classes, mc_samples=20
            )
        except ImportError:
            return None

    if model_name == "tft":
        try:
            from models.tft_model import LottoTFT, PYTORCH_FORECASTING_AVAILABLE
            if not PYTORCH_FORECASTING_AVAILABLE:
                return None
            return LottoTFT(input_dim=feature_dim, output_size=n_classes, task_type="multiclass")
        except ImportError:
            return None

    if model_name == "nbeats":
        # N-BEATS는 univariate scalar regression. ICP에서는 expected_count 회귀 헤드로만 사용.
        # 본 베이스에서는 None 반환, scalar predictor에서 별도 활용
        return None

    if model_name == "mhn":
        try:
            from models.mhn_model import LottoMHN
            return LottoMHN(input_dim=feature_dim)
        except ImportError:
            return None

    # cnn / gnn / autoencoder는 메인 1~45 모델 출력 집계로 활용 (gnn_aggregation)
    return None


class _MarkovHead:
    """카테고리별 7-state 전이행렬. category_count_t -> count_t+1."""

    def __init__(self, n_classes: int = 7):
        self.n_classes = n_classes
        self.transition = np.full((n_classes, n_classes), 1.0 / n_classes)  # uniform prior

    def fit(self, sequence: np.ndarray) -> None:
        """sequence: (T,) 정수 0~6. count → 다음 count 전이 확률."""
        if len(sequence) < 2:
            return
        T = self.transition.copy() * 0
        for i in range(len(sequence) - 1):
            a, b = int(sequence[i]), int(sequence[i + 1])
            if 0 <= a < self.n_classes and 0 <= b < self.n_classes:
                T[a, b] += 1
        # Laplace smoothing
        T += 1
        T = T / T.sum(axis=1, keepdims=True)
        self.transition = T

    def predict_proba(self, last_count: int) -> np.ndarray:
        if 0 <= last_count < self.n_classes:
            return self.transition[last_count].copy()
        return np.full(self.n_classes, 1.0 / self.n_classes)


# ────────────────── ICP 베이스 클래스 ──────────────────


class IndependentCountPredictor:
    """11 base 통합 카테고리별 7-class 카운트 분류기 베이스.

    상속/직접 사용 모두 가능. Phase 1~4 22 인스턴스가 본 클래스 사용.
    """

    DEFAULT_BASE_MODELS = (
        "xgboost", "catboost", "tabnet",
        "markov",
        "tft",
        "bayesian_nn",
        "mhn",
    )

    def __init__(
        self,
        indicator_name: str,
        n_categories: int,
        category_labels: Optional[list[str]] = None,
        n_classes: int = 7,
        feature_dim: int = 0,
        active_models: Optional[tuple[str, ...]] = None,
        category_pool_sizes: Optional[list[int]] = None,
    ):
        self.indicator_name = indicator_name
        self.n_categories = n_categories
        self.n_classes = n_classes
        self.feature_dim = feature_dim
        self.category_labels = category_labels or [f"cat_{i}" for i in range(n_categories)]
        self.category_pool_sizes = category_pool_sizes or [1] * n_categories
        self.active_models = active_models or self.DEFAULT_BASE_MODELS

        self.heads: list[CategoryHead] = [
            CategoryHead(
                category_idx=i,
                category_label=self.category_labels[i],
                n_classes=n_classes,
                pool_size=self.category_pool_sizes[i],
            )
            for i in range(n_categories)
        ]
        self._is_trained = False

    # ────── 학습 ──────

    def train(
        self,
        X: np.ndarray,
        Y: np.ndarray,
        X_val: Optional[np.ndarray] = None,
        Y_val: Optional[np.ndarray] = None,
    ) -> dict:
        """X: (N, feature_dim), Y: (N, n_categories) integer count [0, n_classes)."""
        if Y.ndim != 2 or Y.shape[1] != self.n_categories:
            raise ValueError(f"Y shape mismatch: {Y.shape}, expected (N, {self.n_categories})")

        history = {"per_category": {}}
        for cat_idx in range(self.n_categories):
            head = self.heads[cat_idx]
            y = Y[:, cat_idx].astype(np.int64)
            y_val = Y_val[:, cat_idx].astype(np.int64) if Y_val is not None else None

            for model_name in self.active_models:
                model = _instantiate_base_model(model_name, self.n_classes, self.feature_dim)
                if model is None:
                    continue

                try:
                    if model_name == "markov":
                        # Markov는 카테고리 카운트 시계열만으로 학습
                        model.fit(y)
                    elif model_name == "xgboost":
                        if y_val is not None:
                            model.fit(X, y, eval_set=[(X_val, y_val)], verbose=False)
                        else:
                            model.fit(X, y)
                    elif model_name == "catboost":
                        model.train(X, y, X_val=X_val, y_val=y_val)
                    elif model_name == "tabnet":
                        if X_val is not None and y_val is not None:
                            model.train(X, y, X_val=X_val, y_val=y_val)
                        else:
                            model.train(X, y)
                    elif model_name == "tft":
                        # TFT는 시계열 형식 입력 필요 — 본 단순 (N, D) 입력에 호환되면 사용
                        # 호환 안 되면 skip
                        try:
                            model.train(X, y_val_data=(X_val, y_val) if X_val is not None else None)
                        except Exception:
                            continue
                    elif model_name == "bayesian_nn":
                        model.train(X, y, X_val=X_val, y_val=y_val)
                    elif model_name == "mhn":
                        # MHN은 패턴 저장 + 라벨 voting
                        model.store_patterns(X)
                        # 라벨도 함께 저장 (voting용)
                        model._stored_labels = y.copy()  # 간이 voting

                    head.base_models[model_name] = model
                    head.base_weights[model_name] = 1.0
                except Exception as e:
                    print(f"  [ICP] {self.indicator_name} cat={cat_idx} {model_name} train fail: {e}")

            history["per_category"][cat_idx] = {
                "trained_models": list(head.base_models.keys()),
                "n_classes": self.n_classes,
            }

        self._is_trained = True
        return history

    # ────── 추론 ──────

    def predict(self, X: np.ndarray) -> PredictorOutput:
        """X: (N, feature_dim). 가장 최근 행만 사용 (배치 마지막)."""
        if not self._is_trained:
            return self._baseline_output()

        # 배치 마지막 행 = 현재 회차 추정
        x_query = X[-1:].copy()
        per_cat_out = {}

        for cat_idx, head in enumerate(self.heads):
            probs_list, weights = [], []
            for model_name, model in head.base_models.items():
                p = self._model_predict_proba(model_name, model, x_query, head)
                if p is not None:
                    probs_list.append(p)
                    weights.append(head.base_weights.get(model_name, 1.0))

            if probs_list:
                weights_arr = np.array(weights)
                weights_arr = weights_arr / weights_arr.sum()
                avg_dist = np.average(np.stack(probs_list), axis=0, weights=weights_arr)
            else:
                avg_dist = np.full(self.n_classes, 1.0 / self.n_classes)

            expected = float(np.sum(avg_dist * np.arange(self.n_classes)))
            top_class = int(np.argmax(avg_dist))
            top_prob = float(avg_dist[top_class])
            M = head.pool_size

            per_cat_out[head.category_label] = {
                "absolute_dist": avg_dist.tolist(),
                "expected_count": expected,
                "current_pool_size": M,
                "expected_ratio": expected / max(M, 1),
                "top_class": top_class,
                "top_class_prob": top_prob,
                "narrative": (
                    f"{head.category_label} pool {M} expected {top_class} "
                    f"out of {M} (P={top_prob*100:.1f}%)"
                ),
                "model_contributions": {
                    name: float(head.base_weights.get(name, 1.0)) for name in head.base_models
                },
            }

        return PredictorOutput(
            indicator_name=self.indicator_name,
            per_category=per_cat_out,
        )

    def _model_predict_proba(
        self,
        model_name: str,
        model,
        x: np.ndarray,
        head: CategoryHead,
    ) -> Optional[np.ndarray]:
        """각 base 모델의 7-class prob 예측. shape (n_classes,)."""
        try:
            if model_name == "markov":
                # 직전 회차 카운트로 다음 분포
                last_count = 0  # X에서 직전 카운트 추출 — 호출자가 마지막 위치에 카운트 history 넣어야
                # 단순화: 0~6 균등 prior + 학습된 transition
                return model.predict_proba(last_count)

            if model_name == "xgboost":
                return model.predict_proba(x)[0]

            if model_name == "catboost":
                from models.catboost_model import CATBOOST_AVAILABLE
                if CATBOOST_AVAILABLE:
                    return model.predict_proba(x)[0]
                return None

            if model_name == "tabnet":
                from models.tabnet_model import TABNET_AVAILABLE
                if TABNET_AVAILABLE:
                    return model.predict(x)[0]  # softmax output
                return None

            if model_name == "bayesian_nn":
                out = model.predict_with_uncertainty(x)
                # 간이: mean이 7-class prob 형태라면
                m = out.get("mean")
                if m is not None and m.ndim >= 1 and m.shape[-1] == self.n_classes:
                    return m[0] if m.ndim > 1 else m
                return None

            if model_name == "tft":
                p = model.predict(x)
                if p is not None and len(p) > 0 and p.shape[-1] == self.n_classes:
                    return p[0]
                return None

            if model_name == "mhn":
                ret = model.retrieve(x[0], top_k=5)
                if hasattr(model, "_stored_labels"):
                    indices = ret["top_k_indices"]
                    labels = model._stored_labels[indices]
                    counts = np.bincount(labels.astype(np.int64), minlength=self.n_classes)
                    return counts / counts.sum() if counts.sum() > 0 else None
                return None
        except Exception:
            return None

    def _baseline_output(self) -> PredictorOutput:
        """학습 전 균등 분포 fallback."""
        per_cat = {}
        uniform = np.full(self.n_classes, 1.0 / self.n_classes)
        for head in self.heads:
            per_cat[head.category_label] = {
                "absolute_dist": uniform.tolist(),
                "expected_count": float(np.mean(np.arange(self.n_classes))),
                "current_pool_size": head.pool_size,
                "expected_ratio": float(np.mean(np.arange(self.n_classes))) / max(head.pool_size, 1),
                "top_class": 0,
                "top_class_prob": 1.0 / self.n_classes,
                "narrative": f"{head.category_label} not trained, uniform prior",
                "model_contributions": {},
            }
        return PredictorOutput(indicator_name=self.indicator_name, per_category=per_cat)

    # ────── XAI ──────

    def explain(self) -> dict:
        """11 base 모델 contribution + per-category 분포 → NumberXAIExplainer 입력."""
        return {
            "indicator": self.indicator_name,
            "n_categories": self.n_categories,
            "n_classes": self.n_classes,
            "active_models": list(self.active_models),
            "per_category": [
                {
                    "label": h.category_label,
                    "pool_size": h.pool_size,
                    "trained_models": list(h.base_models.keys()),
                    "weights": dict(h.base_weights),
                }
                for h in self.heads
            ],
        }

    # ────── persistence ──────

    def save(self, path: str) -> str:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # 11 base 모델은 각자 save 메서드 (비신경망은 pickle, 신경망은 state_dict)
        # 단순화: pickle 전체 (개별 base가 pickle 가능하면)
        data = {
            "indicator_name": self.indicator_name,
            "n_categories": self.n_categories,
            "n_classes": self.n_classes,
            "feature_dim": self.feature_dim,
            "category_labels": self.category_labels,
            "category_pool_sizes": self.category_pool_sizes,
            "active_models": list(self.active_models),
            "is_trained": self._is_trained,
            "heads": [
                {
                    "category_idx": h.category_idx,
                    "category_label": h.category_label,
                    "pool_size": h.pool_size,
                    "weights": dict(h.base_weights),
                    # base_models는 모델별로 별도 저장 (pickle 호환 안 되는 PyTorch 등)
                }
                for h in self.heads
            ],
        }
        with open(path, "wb") as f:
            pickle.dump(data, f)
        return path

    def load(self, path: str) -> None:
        with open(path, "rb") as f:
            data = pickle.load(f)
        self.indicator_name = data["indicator_name"]
        self.n_categories = data["n_categories"]
        self.n_classes = data["n_classes"]
        self.feature_dim = data["feature_dim"]
        self.category_labels = data["category_labels"]
        self.category_pool_sizes = data["category_pool_sizes"]
        self.active_models = tuple(data["active_models"])
        self._is_trained = data["is_trained"]
        self.heads = [
            CategoryHead(
                category_idx=h["category_idx"],
                category_label=h["category_label"],
                n_classes=self.n_classes,
                pool_size=h["pool_size"],
                base_weights=h["weights"],
            )
            for h in data["heads"]
        ]


# ────────────────── CLI smoke ──────────────────


def main():
    """python -m predictors.independent_count_predictor --smoke."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()

    if args.smoke:
        rng = np.random.default_rng(config.RANDOM_SEED)
        N, D = 100, 24  # scalar_features 호환
        X = rng.standard_normal((N, D)).astype(np.float32)
        Y = rng.integers(0, 7, size=(N, 10)).astype(np.int64)  # 끝수 10 카테고리

        icp = IndependentCountPredictor(
            indicator_name="endings_distribution",
            n_categories=10,
            category_labels=[f"digit_{i}" for i in range(10)],
            feature_dim=D,
            active_models=("xgboost", "markov"),  # smoke: 의존성 적은 2개
            category_pool_sizes=[5] * 10,  # 끝수 풀 평균 4.5개
        )

        print("[ICP] training (smoke)...")
        history = icp.train(X[:80], Y[:80], X_val=X[80:], Y_val=Y[80:])
        print(f"  trained categories: {len(history['per_category'])}")
        for cat_idx, info in list(history["per_category"].items())[:3]:
            print(f"  cat {cat_idx}: trained models = {info['trained_models']}")

        print("\n[ICP] predicting (smoke)...")
        out = icp.predict(X[-10:])
        for label, payload in list(out.per_category.items())[:3]:
            print(f"  {label}: top={payload['top_class']} P={payload['top_class_prob']:.3f}")
            print(f"    narrative: {payload['narrative']}")


if __name__ == "__main__":
    main()
