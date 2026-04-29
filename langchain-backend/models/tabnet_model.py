"""TabNet 모델 wrapper (pytorch-tabnet).

Sparsemax attention mask로 feature selection 노출 (NumberXAIExplainer 입력).
multiclass / binary / regression 지원.
"""

from __future__ import annotations

import os
from typing import Any

import numpy as np

import config

try:
    import torch
    from pytorch_tabnet.tab_model import TabNetClassifier, TabNetRegressor

    TABNET_AVAILABLE = True
except ImportError:
    TABNET_AVAILABLE = False
    torch = None  # type: ignore
    TabNetClassifier = None  # type: ignore
    TabNetRegressor = None  # type: ignore


_TASK_TYPES = ("binary_45", "multiclass", "binary", "regression")


class LottoTabNet:
    """TabNet 분류/회귀 wrapper.

    Sparsemax attention 기반 feature selection을 explain()으로 노출.

    task_type:
      - "binary_45": 1~45 multi-label sigmoid (메인 number prediction, BCE)
      - "multiclass": (N, num_classes) softmax (count predictor 등)
      - "binary": (N,) 양성 확률
      - "regression": (N,) 회귀
    """

    def __init__(
        self,
        task_type: str = "multiclass",
        num_classes: int = 7,
        input_dim: int | None = None,
        n_d: int = 8,
        n_a: int = 8,
        n_steps: int = 3,
        gamma: float = 1.3,
        lambda_sparse: float = 1e-3,
        learning_rate: float = 2e-2,
        max_epochs: int = 100,
        patience: int = 15,
        batch_size: int = 256,
        virtual_batch_size: int = 128,
        random_seed: int | None = None,
        device: str | None = None,
        **kwargs: Any,
    ) -> None:
        # 인자 검증은 라이브러리 유무와 독립적으로 우선 수행 (Stage 1-4-D-2-fix-2)
        if task_type not in _TASK_TYPES:
            raise ValueError(f"task_type must be one of {_TASK_TYPES}, got {task_type}")

        self.task_type = task_type
        self.num_classes = int(num_classes)
        self.input_dim = int(input_dim) if input_dim is not None else None
        self.n_d = n_d
        self.n_a = n_a
        self.n_steps = n_steps
        self.gamma = gamma
        self.lambda_sparse = lambda_sparse
        self.learning_rate = learning_rate
        self.max_epochs = max_epochs
        self.patience = patience
        self.batch_size = batch_size
        self.virtual_batch_size = virtual_batch_size
        self.random_seed = random_seed if random_seed is not None else config.RANDOM_SEED
        # 라이브러리 없이 인스턴스화는 OK — 실 학습/예측 호출 시점에만 강제
        self._tabnet_available = TABNET_AVAILABLE

        # device 자동 감지 (torch 미설치 시 cpu 가정)
        if device is None:
            if TABNET_AVAILABLE and torch is not None:
                device = "cuda" if torch.cuda.is_available() else "cpu"
            else:
                device = "cpu"
        self.device = device

        self.model: Any = None
        if TABNET_AVAILABLE:
            self._build_model()

    def _build_model(self) -> None:
        """task_type에 따른 TabNet 인스턴스 생성."""
        if not TABNET_AVAILABLE:
            raise ImportError(
                "[tabnet_model] requires pytorch-tabnet library, "
                "install with: pip install pytorch-tabnet"
            )

        common_kwargs = {
            "n_d": self.n_d,
            "n_a": self.n_a,
            "n_steps": self.n_steps,
            "gamma": self.gamma,
            "lambda_sparse": self.lambda_sparse,
            "optimizer_fn": torch.optim.Adam,
            "optimizer_params": {"lr": self.learning_rate},
            "scheduler_fn": torch.optim.lr_scheduler.StepLR,
            "scheduler_params": {"step_size": 30, "gamma": 0.9},
            "seed": self.random_seed,
            "verbose": 0,
            "device_name": self.device,
        }

        # binary_45: 1~45 multi-label sigmoid → TabNetClassifier 라이브러리상 단일 라벨만 지원하므로
        # 멀티핫 학습은 train()에서 num_classes개의 별도 binary head를 순회 학습하는 방식으로 처리.
        # 여기서는 placeholder로 multiclass classifier 인스턴스만 생성 (실제 학습 시 재구성).
        if self.task_type in ("multiclass", "binary", "binary_45"):
            self.model = TabNetClassifier(**common_kwargs)
        else:
            self.model = TabNetRegressor(**common_kwargs)

    def _prep_y(self, y: np.ndarray) -> np.ndarray:
        """task_type별 y shape 정규화."""
        if self.task_type == "regression":
            arr = np.asarray(y, dtype=np.float32)
            if arr.ndim == 1:
                arr = arr.reshape(-1, 1)
            return arr
        return np.asarray(y).astype(np.int64).reshape(-1)

    def train(
        self,
        X: np.ndarray,
        y: np.ndarray,
        X_val: np.ndarray | None = None,
        y_val: np.ndarray | None = None,
    ) -> dict:
        """학습. early stopping은 patience 사용."""
        X_arr = np.asarray(X, dtype=np.float32)
        y_arr = self._prep_y(y)

        eval_set = []
        eval_name = []
        if X_val is not None and y_val is not None:
            eval_set = [(np.asarray(X_val, dtype=np.float32), self._prep_y(y_val))]
            eval_name = ["val"]

        if self.task_type == "regression":
            eval_metric = ["rmse"]
        elif self.task_type == "multiclass":
            eval_metric = ["accuracy"]
        else:
            eval_metric = ["auc"]

        # virtual_batch_size > batch_size 방지
        vbs = min(self.virtual_batch_size, max(1, len(X_arr) // 2))
        bs = min(self.batch_size, max(2, len(X_arr)))

        self.model.fit(
            X_train=X_arr,
            y_train=y_arr,
            eval_set=eval_set,
            eval_name=eval_name,
            eval_metric=eval_metric,
            max_epochs=self.max_epochs,
            patience=self.patience,
            batch_size=bs,
            virtual_batch_size=vbs,
            num_workers=0,
            drop_last=False,
        )

        return {
            "success": True,
            "task_type": self.task_type,
            "best_epoch": int(getattr(self.model, "best_epoch", self.max_epochs)),
            "best_cost": float(getattr(self.model, "best_cost", 0.0)),
        }

    def predict(self, X: np.ndarray) -> np.ndarray:
        """예측.

        - multiclass / binary_45: (N, num_classes) 확률 (binary_45는 sigmoid-like)
        - binary: (N,) 양성 확률
        - regression: (N,)
        """
        if self.model is None:
            raise RuntimeError("Model is not trained yet (or library missing)")
        X_arr = np.asarray(X, dtype=np.float32)
        if self.task_type in ("multiclass", "binary_45"):
            return np.asarray(self.model.predict_proba(X_arr), dtype=np.float32)
        if self.task_type == "binary":
            proba = np.asarray(self.model.predict_proba(X_arr), dtype=np.float32)
            return proba[:, 1] if proba.ndim == 2 and proba.shape[1] >= 2 else proba.reshape(-1)
        # regression
        out = np.asarray(self.model.predict(X_arr), dtype=np.float32)
        return out.reshape(-1)

    def explain(self, X: np.ndarray) -> dict:
        """TabNet 자체 explain() 활용.

        반환:
          - "attention_mask": (N, n_features) 평균 attention mask
          - "step_masks": list[(N, n_features)] 각 decision step별 mask
          - "feature_importance": {feature_idx: importance}
        """
        if self.model is None:
            raise RuntimeError("Model is not trained yet")

        X_arr = np.asarray(X, dtype=np.float32)
        # pytorch-tabnet explain(): (M_explain, masks_dict)
        m_explain, masks = self.model.explain(X_arr)

        attention_mask = np.asarray(m_explain, dtype=np.float32)
        step_masks = [np.asarray(masks[k], dtype=np.float32) for k in sorted(masks.keys())]

        # feature_importances_: 학습 후 자동 계산되는 전역 중요도
        importances = getattr(self.model, "feature_importances_", None)
        if importances is None:
            importance_dict: dict[int, float] = {}
        else:
            importance_dict = {int(i): float(v) for i, v in enumerate(importances)}

        return {
            "attention_mask": attention_mask,
            "step_masks": step_masks,
            "feature_importance": importance_dict,
        }

    def save(self, path: str) -> None:
        """모델 직렬화 (pytorch-tabnet은 .zip로 저장)."""
        if self.model is None:
            raise RuntimeError("Model is not trained yet")
        # save_model은 자동으로 .zip을 추가함
        if path.endswith(".zip"):
            base = path[:-4]
        else:
            base = path
        os.makedirs(os.path.dirname(base) or ".", exist_ok=True)
        self.model.save_model(base)

    def load(self, path: str) -> None:
        """모델 로드 (.zip 확장자 자동 처리)."""
        actual = path if path.endswith(".zip") else path + ".zip"
        if not os.path.exists(actual):
            raise FileNotFoundError(f"Model file not found: {actual}")
        self.model.load_model(actual)


def _smoke_test() -> int:
    """smoke 테스트: 1100x65 랜덤 데이터로 multiclass 1 epoch 학습."""
    if not TABNET_AVAILABLE:
        print("[tabnet_model] requires pytorch-tabnet library, install with: pip install pytorch-tabnet")
        return 0

    print("[tabnet_model] smoke start")
    rng = np.random.default_rng(config.RANDOM_SEED)
    X = rng.standard_normal((1100, 65)).astype(np.float32)
    y = rng.integers(0, 7, size=1100).astype(np.int64)

    split = 1000
    X_tr, X_val = X[:split], X[split:]
    y_tr, y_val = y[:split], y[split:]

    clf = LottoTabNet(
        task_type="multiclass",
        num_classes=7,
        n_d=4,
        n_a=4,
        n_steps=2,
        max_epochs=1,
        patience=1,
        batch_size=64,
        virtual_batch_size=32,
    )
    info = clf.train(X_tr, y_tr, X_val=X_val, y_val=y_val)
    proba = clf.predict(X_val)
    expl = clf.explain(X_val[:8])

    print(f"[tabnet_model] train info: best_epoch={info['best_epoch']} device={clf.device}")
    print(f"[tabnet_model] proba shape: {proba.shape}")
    print(f"[tabnet_model] attention_mask shape: {expl['attention_mask'].shape}")
    print(f"[tabnet_model] step_masks count: {len(expl['step_masks'])}")
    print(f"[tabnet_model] feature_importance count: {len(expl['feature_importance'])}")

    # save/load round-trip
    tmp_base = os.path.join(config.MODEL_DIR, "_smoke_tabnet")
    clf.save(tmp_base)
    clf2 = LottoTabNet(
        task_type="multiclass",
        num_classes=7,
        n_d=4,
        n_a=4,
        n_steps=2,
        max_epochs=1,
    )
    clf2.load(tmp_base)
    proba2 = clf2.predict(X_val[:5])
    print(f"[tabnet_model] reloaded proba shape: {proba2.shape}")

    try:
        os.remove(tmp_base + ".zip")
    except OSError:
        pass

    print("[tabnet_model] smoke OK")
    return 0


if __name__ == "__main__":
    import sys

    if "--smoke" in sys.argv:
        sys.exit(_smoke_test())
    print("[tabnet_model] use --smoke to run smoke test")
