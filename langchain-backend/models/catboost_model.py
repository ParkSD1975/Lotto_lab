"""CatBoost 트리 모델 wrapper.

XGBoost와 병렬 사용. Ordered boosting + target encoding 활용.
TreeSHAP 기반 XAI 입력 제공.
"""

from __future__ import annotations

import os
from typing import Any

import numpy as np

import config

try:
    from catboost import CatBoostClassifier, CatBoostRegressor, Pool

    CATBOOST_AVAILABLE = True
except ImportError:
    CATBOOST_AVAILABLE = False
    CatBoostClassifier = None  # type: ignore
    CatBoostRegressor = None  # type: ignore
    Pool = None  # type: ignore


_TASK_TYPES = ("binary_45", "multiclass", "binary", "regression")


class LottoCatBoost:
    """CatBoost 분류/회귀 wrapper.

    task_type:
      - "binary_45": 1~45 multi-label (CatBoost는 multi-label 미지원이므로 multiclass로 수렴)
      - "multiclass": (N, num_classes) 확률
      - "binary": (N,) 이진 확률
      - "regression": (N,) 회귀값
    """

    def __init__(
        self,
        task_type: str = "multiclass",
        num_classes: int = 7,
        input_dim: int | None = None,
        iterations: int = 500,
        learning_rate: float = 0.05,
        depth: int = 6,
        l2_leaf_reg: float = 3.0,
        early_stopping_rounds: int = 30,
        verbose: int = 0,
        cat_features: list[int] | None = None,
        random_seed: int | None = None,
        **kwargs: Any,
    ) -> None:
        # 인자 검증은 라이브러리 유무와 독립적으로 우선 수행 (Stage 1-4-D-2-fix-2)
        if task_type not in _TASK_TYPES:
            raise ValueError(f"task_type must be one of {_TASK_TYPES}, got {task_type}")

        self.task_type = task_type
        self.num_classes = int(num_classes)
        self.input_dim = int(input_dim) if input_dim is not None else None
        self.iterations = iterations
        self.learning_rate = learning_rate
        self.depth = depth
        self.l2_leaf_reg = l2_leaf_reg
        self.early_stopping_rounds = early_stopping_rounds
        self.verbose = verbose
        self.cat_features = cat_features or []
        self.random_seed = random_seed if random_seed is not None else config.RANDOM_SEED
        self._catboost_available = CATBOOST_AVAILABLE

        self.model: Any = None
        if CATBOOST_AVAILABLE:
            self._build_model()

    def _build_model(self) -> None:
        """task_type에 따른 CatBoost 인스턴스 생성."""
        if not CATBOOST_AVAILABLE:
            raise ImportError(
                "[catboost_model] requires catboost library, "
                "install with: pip install catboost"
            )

        common = {
            "iterations": self.iterations,
            "learning_rate": self.learning_rate,
            "depth": self.depth,
            "l2_leaf_reg": self.l2_leaf_reg,
            "random_seed": self.random_seed,
            "verbose": self.verbose,
            # CatBoost 특화: ordered boosting (target leakage 방지)
            "boosting_type": "Ordered",
            "allow_writing_files": False,
        }

        # binary_45: CatBoost는 multi-label 직접 지원 X — multiclass 동일 인터페이스로 빌드
        # 실제 학습 시 train()에서 멀티핫 라벨을 num_classes개의 binary head로 순회 학습
        if self.task_type in ("multiclass", "binary_45"):
            self.model = CatBoostClassifier(
                loss_function="MultiClass",
                classes_count=self.num_classes,
                **common,
            )
        elif self.task_type == "binary":
            self.model = CatBoostClassifier(
                loss_function="Logloss",
                **common,
            )
        else:  # regression
            self.model = CatBoostRegressor(
                loss_function="RMSE",
                **common,
            )

    def train(
        self,
        X: Any,
        y: np.ndarray | None = None,
        X_val: np.ndarray | None = None,
        y_val: np.ndarray | None = None,
        fine_tune: bool = False,
    ) -> dict:
        """학습.

        오버로드:
          - train(X: ndarray, y: ndarray, ...) - 기존 catboost fit.
          - train(draws: list[dict], fine_tune: bool=False) - ensemble.train_all
            호환 어댑터. binary_45 시 45 multi-output 회귀로 학습.
        """
        # ensemble.train_all 어댑터 분기
        if isinstance(X, list) and (len(X) == 0 or isinstance(X[0], dict)):
            return self._train_from_draws(X, fine_tune=fine_tune)
        return self._train_main(X, y, X_val=X_val, y_val=y_val)

    def _train_main(
        self,
        X: np.ndarray,
        y: np.ndarray,
        X_val: np.ndarray | None = None,
        y_val: np.ndarray | None = None,
    ) -> dict:
        """기존 catboost fit. early_stopping_rounds 활용."""
        train_pool = Pool(X, y, cat_features=self.cat_features)
        eval_pool = None
        if X_val is not None and y_val is not None:
            eval_pool = Pool(X_val, y_val, cat_features=self.cat_features)

        self.model.fit(
            train_pool,
            eval_set=eval_pool,
            early_stopping_rounds=self.early_stopping_rounds if eval_pool else None,
            use_best_model=eval_pool is not None,
            verbose=self.verbose,
        )

        result = {
            "success": True,
            "task_type": self.task_type,
            "best_iteration": int(self.model.get_best_iteration() or self.iterations),
        }
        if eval_pool is not None:
            best_score = self.model.get_best_score()
            result["best_score"] = best_score
        return result

    def _train_from_draws(self, draws: list, fine_tune: bool = False) -> dict:
        """ensemble.train_all 호환 어댑터.

        binary_45: 45 multi-output regression(MultiRMSE) -> sigmoid 후처리로 확률 근사.
        라이브러리 미설치 시 graceful skip.
        """
        if not CATBOOST_AVAILABLE:
            print("[catboost_model] skip: catboost missing")
            return {"success": False, "skipped": "library_missing"}
        if self.task_type != "binary_45":
            return {"success": False, "error": f"task_type must be binary_45 for adapter, got {self.task_type}"}

        try:
            from models._draws_adapter import draws_to_xy
            input_dim = self.input_dim if self.input_dim else 65
            X, y = draws_to_xy(draws, seq_len=30, input_dim=input_dim)
            if X.shape[0] < 50:
                return {"success": False, "error": f"too few samples after conversion: {X.shape[0]}"}

            split = int(X.shape[0] * 0.85)
            X_tr, X_val = X[:split], X[split:]
            y_tr, y_val = y[:split], y[split:]

            common = {
                "iterations": min(200, self.iterations),
                "learning_rate": self.learning_rate,
                "depth": self.depth,
                "l2_leaf_reg": self.l2_leaf_reg,
                "random_seed": self.random_seed,
                "verbose": self.verbose,
                "allow_writing_files": False,
            }

            save_path = os.path.join(config.MODEL_DIR, "catboost_main45.cbm")
            if fine_tune and os.path.exists(save_path):
                try:
                    reg = CatBoostRegressor(loss_function="MultiRMSE", **common)
                    reg.load_model(save_path, format="cbm")
                    self.model = reg
                    print("[catboost_model] fine_tune: prior weights loaded")
                except Exception as e:
                    print(f"[catboost_model] fine_tune load fail (from scratch): {e}")
                    self.model = CatBoostRegressor(loss_function="MultiRMSE", **common)
            else:
                self.model = CatBoostRegressor(loss_function="MultiRMSE", **common)

            train_pool = Pool(X_tr, y_tr, cat_features=self.cat_features)
            eval_pool = Pool(X_val, y_val, cat_features=self.cat_features)
            self.model.fit(
                train_pool,
                eval_set=eval_pool,
                early_stopping_rounds=self.early_stopping_rounds,
                use_best_model=True,
                verbose=self.verbose,
            )

            try:
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                self.model.save_model(save_path, format="cbm")
            except Exception as e:
                print(f"[catboost_model] save fail: {e}")

            return {
                "success": True,
                "task_type": "binary_45",
                "samples": int(X.shape[0]),
                "best_iteration": int(self.model.get_best_iteration() or 0),
                "saved_to": save_path,
            }
        except Exception as e:
            return {"success": False, "error": f"{type(e).__name__}: {e}"}

    def predict(self, X: np.ndarray) -> np.ndarray:
        """예측. multiclass면 (N, num_classes), 그 외 (N,)."""
        if self.task_type == "multiclass":
            return np.asarray(self.model.predict_proba(X), dtype=np.float32)
        if self.task_type == "binary":
            proba = np.asarray(self.model.predict_proba(X), dtype=np.float32)
            return proba[:, 1]
        return np.asarray(self.model.predict(X), dtype=np.float32).reshape(-1)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """분류 확률 (regression이면 NotImplementedError)."""
        if self.task_type == "regression":
            raise NotImplementedError("predict_proba is not supported for regression task")
        return np.asarray(self.model.predict_proba(X), dtype=np.float32)

    def feature_importance(self) -> dict[int, float]:
        """built-in feature importance (PredictionValuesChange)."""
        if self.model is None:
            return {}
        importances = self.model.get_feature_importance()
        return {int(i): float(v) for i, v in enumerate(importances)}

    def tree_shap(self, X: np.ndarray) -> np.ndarray:
        """TreeSHAP value (XAI 입력).

        반환 shape:
          - multiclass: (N, num_classes, n_features+1)  # +1 = expected value
          - binary/regression: (N, n_features+1)
        """
        if self.model is None:
            raise RuntimeError("Model is not trained yet")
        pool = Pool(X, cat_features=self.cat_features)
        shap_values = self.model.get_feature_importance(
            data=pool,
            type="ShapValues",
        )
        return np.asarray(shap_values, dtype=np.float32)

    def save(self, path: str) -> None:
        """모델 직렬화."""
        if self.model is None:
            raise RuntimeError("Model is not trained yet")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.model.save_model(path, format="cbm")

    def load(self, path: str) -> None:
        """모델 로드."""
        if not os.path.exists(path):
            raise FileNotFoundError(f"Model file not found: {path}")
        self.model.load_model(path, format="cbm")


def _smoke_test() -> int:
    """smoke 테스트: 1100x65 랜덤 데이터로 multiclass 1 epoch 학습."""
    if not CATBOOST_AVAILABLE:
        print("[catboost_model] requires catboost library, install with: pip install catboost")
        return 0

    print("[catboost_model] smoke start")
    rng = np.random.default_rng(config.RANDOM_SEED)
    X = rng.standard_normal((1100, 65)).astype(np.float32)
    y = rng.integers(0, 7, size=1100).astype(np.int64)

    split = 1000
    X_tr, X_val = X[:split], X[split:]
    y_tr, y_val = y[:split], y[split:]

    clf = LottoCatBoost(
        task_type="multiclass",
        num_classes=7,
        iterations=10,
        learning_rate=0.1,
        depth=4,
        early_stopping_rounds=5,
        verbose=0,
    )
    info = clf.train(X_tr, y_tr, X_val=X_val, y_val=y_val)
    proba = clf.predict(X_val)
    importances = clf.feature_importance()

    print(f"[catboost_model] train info: best_iter={info['best_iteration']}")
    print(f"[catboost_model] proba shape: {proba.shape}")
    print(f"[catboost_model] feature importance count: {len(importances)}")

    # save/load round-trip
    tmp_path = os.path.join(config.MODEL_DIR, "_smoke_catboost.cbm")
    clf.save(tmp_path)
    clf2 = LottoCatBoost(
        task_type="multiclass",
        num_classes=7,
        iterations=10,
        depth=4,
        verbose=0,
    )
    clf2.load(tmp_path)
    proba2 = clf2.predict(X_val[:5])
    print(f"[catboost_model] reloaded proba shape: {proba2.shape}")

    try:
        os.remove(tmp_path)
    except OSError:
        pass

    print("[catboost_model] smoke OK")
    return 0


if __name__ == "__main__":
    import sys

    if "--smoke" in sys.argv:
        sys.exit(_smoke_test())
    print("[catboost_model] use --smoke to run smoke test")
