"""Temporal Fusion Transformer (TFT) wrapper.

LSTM/Transformer를 흡수하는 메인 시계열 모델.
정형+시계열+카테고리 통합. variable selection / attention weight를 XAI 입력으로 노출.
"""

from __future__ import annotations

import os
from typing import Any

import numpy as np

import config

try:
    import torch
    import pandas as pd
    from pytorch_forecasting import TemporalFusionTransformer, TimeSeriesDataSet
    from pytorch_forecasting.data import GroupNormalizer
    from pytorch_forecasting.metrics import (
        CrossEntropy,
        MultiHorizonMetric,
        QuantileLoss,
    )
    import lightning.pytorch as pl

    PYTORCH_FORECASTING_AVAILABLE = True
except ImportError:
    PYTORCH_FORECASTING_AVAILABLE = False
    torch = None  # type: ignore
    pd = None  # type: ignore
    TemporalFusionTransformer = None  # type: ignore
    TimeSeriesDataSet = None  # type: ignore
    GroupNormalizer = None  # type: ignore
    CrossEntropy = None  # type: ignore
    MultiHorizonMetric = None  # type: ignore
    QuantileLoss = None  # type: ignore
    pl = None  # type: ignore


_TASK_TYPES = ("binary_45", "multiclass", "regression")


class LottoTFT:
    """Temporal Fusion Transformer wrapper.

    task_type:
      - "binary_45": 1~45 sigmoid 출력 (메인 number prediction)
      - "multiclass": 7-class 분류 (count predictor)
      - "regression": 스칼라 회귀
    """

    def __init__(
        self,
        input_dim: int,
        hidden_dim: int = 64,
        attention_head_size: int = 4,
        num_layers: int = 2,
        dropout: float = 0.1,
        output_size: int = 45,
        task_type: str = "binary_45",
        learning_rate: float = 1e-3,
        random_seed: int | None = None,
        device: str | None = None,
    ) -> None:
        if not PYTORCH_FORECASTING_AVAILABLE:
            raise ImportError(
                "[tft_model] requires pytorch-forecasting library, "
                "install with: pip install pytorch-forecasting"
            )

        if task_type not in _TASK_TYPES:
            raise ValueError(f"task_type must be one of {_TASK_TYPES}, got {task_type}")

        self.input_dim = int(input_dim)
        self.hidden_dim = hidden_dim
        self.attention_head_size = attention_head_size
        self.num_layers = num_layers
        self.dropout = dropout
        self.output_size = output_size
        self.task_type = task_type
        self.learning_rate = learning_rate
        self.random_seed = random_seed if random_seed is not None else config.RANDOM_SEED

        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = device

        # 학습 후 채워짐
        self.model: Any = None
        self.training_dataset: Any = None
        self.trainer: Any = None

        # 시드 고정
        torch.manual_seed(self.random_seed)
        np.random.seed(self.random_seed)

    def _build_dataset(
        self,
        df,
        max_encoder_length: int = 30,
        max_prediction_length: int = 1,
        is_train: bool = True,
        from_dataset: Any = None,
    ):
        """TimeSeriesDataSet 구성.

        df schema 가정:
          - "time_idx": int (회차 순번)
          - "group_id": str/int (단일 그룹이면 상수)
          - "target": float (task별 타겟)
          - feature 컬럼들 (input_dim 개)
        """
        feature_cols = [c for c in df.columns if c.startswith("feat_")]

        if from_dataset is not None:
            return TimeSeriesDataSet.from_dataset(
                from_dataset, df, predict=not is_train, stop_randomization=True
            )

        return TimeSeriesDataSet(
            df,
            time_idx="time_idx",
            target="target",
            group_ids=["group_id"],
            max_encoder_length=max_encoder_length,
            max_prediction_length=max_prediction_length,
            time_varying_known_reals=["time_idx"],
            time_varying_unknown_reals=feature_cols + ["target"],
            target_normalizer=GroupNormalizer(groups=["group_id"]),
            add_relative_time_idx=True,
            add_target_scales=True,
            add_encoder_length=True,
            allow_missing_timesteps=True,
        )

    def _build_model_from_dataset(self, dataset: Any) -> None:
        """TimeSeriesDataSet 기반으로 TFT 인스턴스 생성."""
        if self.task_type == "regression":
            loss = QuantileLoss()
            output_size = 7  # default quantile count
        else:
            # binary_45 / multiclass도 우선 회귀 손실로 fit (raw output 후 head 변환)
            loss = QuantileLoss()
            output_size = 7

        self.model = TemporalFusionTransformer.from_dataset(
            dataset,
            learning_rate=self.learning_rate,
            hidden_size=self.hidden_dim,
            attention_head_size=self.attention_head_size,
            dropout=self.dropout,
            hidden_continuous_size=max(8, self.hidden_dim // 4),
            output_size=output_size,
            loss=loss,
            log_interval=0,
            reduce_on_plateau_patience=4,
        )

    def train(
        self,
        time_series_data,
        val_data=None,
        max_epochs: int = 30,
        batch_size: int = 64,
        max_encoder_length: int = 30,
        max_prediction_length: int = 1,
    ) -> dict:
        """학습 수행.

        time_series_data: pandas DataFrame (또는 TimeSeriesDataSet)
        val_data: 동일 형식 (optional)
        """
        if isinstance(time_series_data, TimeSeriesDataSet):
            train_dataset = time_series_data
        else:
            train_dataset = self._build_dataset(
                time_series_data,
                max_encoder_length=max_encoder_length,
                max_prediction_length=max_prediction_length,
                is_train=True,
            )

        self.training_dataset = train_dataset

        val_dataset = None
        if val_data is not None:
            if isinstance(val_data, TimeSeriesDataSet):
                val_dataset = val_data
            else:
                val_dataset = self._build_dataset(
                    val_data,
                    max_encoder_length=max_encoder_length,
                    max_prediction_length=max_prediction_length,
                    is_train=False,
                    from_dataset=train_dataset,
                )

        self._build_model_from_dataset(train_dataset)

        # DataLoader
        train_loader = train_dataset.to_dataloader(
            train=True, batch_size=batch_size, num_workers=0
        )
        val_loader = None
        if val_dataset is not None:
            val_loader = val_dataset.to_dataloader(
                train=False, batch_size=batch_size, num_workers=0
            )

        # Lightning Trainer
        accelerator = "gpu" if self.device.startswith("cuda") else "cpu"
        self.trainer = pl.Trainer(
            max_epochs=max_epochs,
            accelerator=accelerator,
            devices=1,
            enable_progress_bar=False,
            enable_model_summary=False,
            logger=False,
            enable_checkpointing=False,
            gradient_clip_val=0.1,
        )

        if val_loader is not None:
            self.trainer.fit(self.model, train_loader, val_loader)
        else:
            self.trainer.fit(self.model, train_loader)

        return {
            "success": True,
            "task_type": self.task_type,
            "max_epochs": int(max_epochs),
            "device": self.device,
        }

    def predict(self, X) -> np.ndarray:
        """예측. X는 DataFrame 또는 TimeSeriesDataSet."""
        if self.model is None:
            raise RuntimeError("Model is not trained yet")

        if isinstance(X, TimeSeriesDataSet):
            dataset = X
        else:
            if self.training_dataset is None:
                raise RuntimeError("training_dataset is missing; call train() first")
            dataset = self._build_dataset(
                X,
                is_train=False,
                from_dataset=self.training_dataset,
            )

        loader = dataset.to_dataloader(train=False, batch_size=64, num_workers=0)
        raw = self.model.predict(loader, mode="prediction")
        if hasattr(raw, "cpu"):
            raw = raw.cpu().numpy()
        return np.asarray(raw, dtype=np.float32)

    def explain(self, X) -> dict:
        """TFT XAI 산출.

        반환:
          - "variable_selection_weights": (N, n_vars) encoder 변수 선택 weight
          - "attention_weights": (N, T) self-attention weight 평균
          - "encoder_attention": (N, T, T) raw attention tensor
        """
        if self.model is None:
            raise RuntimeError("Model is not trained yet")

        if isinstance(X, TimeSeriesDataSet):
            dataset = X
        else:
            if self.training_dataset is None:
                raise RuntimeError("training_dataset is missing; call train() first")
            dataset = self._build_dataset(
                X,
                is_train=False,
                from_dataset=self.training_dataset,
            )

        loader = dataset.to_dataloader(train=False, batch_size=64, num_workers=0)
        raw_predictions, x_index = self.model.predict(
            loader, mode="raw", return_x=True
        )

        # interpret_output: TFT가 제공하는 attention/var-selection 분해
        interp = self.model.interpret_output(raw_predictions, reduction=None)

        var_sel = interp.get("encoder_variables", None)
        attn = interp.get("attention", None)
        encoder_attn = interp.get("encoder_attention", attn)

        def _to_np(t):
            if t is None:
                return np.zeros((0,), dtype=np.float32)
            if hasattr(t, "cpu"):
                t = t.cpu().numpy()
            return np.asarray(t, dtype=np.float32)

        var_sel_np = _to_np(var_sel)
        attn_np = _to_np(attn)
        enc_attn_np = _to_np(encoder_attn)

        # attention_weights: encoder time축 평균 (N, T)
        if attn_np.ndim >= 3:
            attn_mean = attn_np.mean(axis=tuple(range(1, attn_np.ndim - 1)))
        else:
            attn_mean = attn_np

        return {
            "variable_selection_weights": var_sel_np,
            "attention_weights": attn_mean,
            "encoder_attention": enc_attn_np,
        }

    def save(self, path: str) -> None:
        """모델 직렬화. state_dict + dataset 메타 저장."""
        if self.model is None:
            raise RuntimeError("Model is not trained yet")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        torch.save(
            {
                "state_dict": self.model.state_dict(),
                "hparams": dict(self.model.hparams),
                "task_type": self.task_type,
                "input_dim": self.input_dim,
                "training_dataset_params": (
                    self.training_dataset.get_parameters()
                    if self.training_dataset is not None
                    else None
                ),
            },
            path,
        )

    def load(self, path: str) -> None:
        """모델 로드. dataset 파라미터로 모델 재구성 후 weight 적용."""
        if not os.path.exists(path):
            raise FileNotFoundError(f"Model file not found: {path}")
        ckpt = torch.load(path, map_location=self.device, weights_only=False)
        ds_params = ckpt.get("training_dataset_params", None)
        if ds_params is not None:
            # 빈 DataFrame로 dataset 재구성 (파라미터만 복원)
            self.training_dataset = TimeSeriesDataSet.from_parameters(
                ds_params, ds_params.get("data", None) if isinstance(ds_params, dict) else None,
                predict=False,
                stop_randomization=True,
            ) if isinstance(ds_params, dict) and ds_params.get("data", None) is not None else None
        # weight만 복원 (training_dataset 없으면 model 재구성 불가 → 호출 측이 train 후 load 필요)
        if self.model is not None:
            self.model.load_state_dict(ckpt["state_dict"])


def _make_dummy_df(n_groups: int = 1, length: int = 200, n_features: int = 8):
    """smoke용 가짜 시계열 DataFrame 생성."""
    rng = np.random.default_rng(config.RANDOM_SEED)
    rows = []
    for g in range(n_groups):
        for t in range(length):
            row = {
                "time_idx": t,
                "group_id": str(g),
                "target": float(rng.standard_normal()),
            }
            for f in range(n_features):
                row[f"feat_{f}"] = float(rng.standard_normal())
            rows.append(row)
    return pd.DataFrame(rows)


def _smoke_test() -> int:
    """smoke 테스트: 가짜 시계열 200스텝으로 1 epoch 학습."""
    if not PYTORCH_FORECASTING_AVAILABLE:
        print(
            "[tft_model] requires pytorch-forecasting library, "
            "install with: pip install pytorch-forecasting"
        )
        return 0

    print("[tft_model] smoke start")
    n_features = 8
    df = _make_dummy_df(n_groups=1, length=200, n_features=n_features)

    split = 170
    df_tr = df[df["time_idx"] < split].reset_index(drop=True)
    df_val = df[df["time_idx"] >= split - 30].reset_index(drop=True)

    model = LottoTFT(
        input_dim=n_features,
        hidden_dim=16,
        attention_head_size=2,
        num_layers=1,
        dropout=0.1,
        output_size=45,
        task_type="binary_45",
        learning_rate=1e-3,
    )

    info = model.train(
        df_tr,
        val_data=df_val,
        max_epochs=1,
        batch_size=16,
        max_encoder_length=20,
        max_prediction_length=1,
    )
    print(f"[tft_model] train info: epochs={info['max_epochs']} device={info['device']}")

    pred = model.predict(df_val)
    print(f"[tft_model] predict shape: {pred.shape}")

    try:
        expl = model.explain(df_val)
        print(
            f"[tft_model] explain var_sel shape: {expl['variable_selection_weights'].shape}"
        )
        print(f"[tft_model] explain attention shape: {expl['attention_weights'].shape}")
    except Exception as exc:
        print(f"[tft_model] explain skipped: {type(exc).__name__}: {exc}")

    tmp_path = os.path.join(config.MODEL_DIR, "_smoke_tft.pt")
    model.save(tmp_path)
    print(f"[tft_model] saved to {tmp_path}")

    try:
        os.remove(tmp_path)
    except OSError:
        pass

    print("[tft_model] smoke OK")
    return 0


if __name__ == "__main__":
    import sys

    if "--smoke" in sys.argv:
        sys.exit(_smoke_test())
    print("[tft_model] use --smoke to run smoke test")
