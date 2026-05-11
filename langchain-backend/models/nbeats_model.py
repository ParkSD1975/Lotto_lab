"""N-BEATS wrapper (univariate 시계열 분해).

스칼라 지표(sum/AC/끝수합) 시계열에 대해 trend/seasonality/residual 분해 head 노출.
narrative XAI 입력으로 활용.
"""

from __future__ import annotations

import os
from typing import Any

import numpy as np

import config

try:
    import torch
    import pandas as pd
    from pytorch_forecasting import NBeats, TimeSeriesDataSet
    from pytorch_forecasting.metrics import MAE
    import lightning.pytorch as pl

    PYTORCH_FORECASTING_AVAILABLE = True
except ImportError:
    PYTORCH_FORECASTING_AVAILABLE = False
    torch = None  # type: ignore
    pd = None  # type: ignore
    NBeats = None  # type: ignore
    TimeSeriesDataSet = None  # type: ignore
    MAE = None  # type: ignore
    pl = None  # type: ignore


class LottoNBeats:
    """N-BEATS univariate 시계열 wrapper.

    backcast/forecast 분리 + generic basis trend / seasonal basis 분해 노출.
    """

    def __init__(
        self,
        seq_length: int = 50,
        prediction_length: int = 1,
        num_blocks: tuple = (3, 3),
        expansion_coefficient_lengths: tuple = (3, 5),
        widths: tuple = (32, 512),
        sharing: tuple = (True, True),
        backcast_loss_ratio: float = 0.1,
        learning_rate: float = 1e-3,
        random_seed: int | None = None,
        device: str | None = None,
    ) -> None:
        if not PYTORCH_FORECASTING_AVAILABLE:
            raise ImportError(
                "[nbeats_model] requires pytorch-forecasting library, "
                "install with: pip install pytorch-forecasting"
            )

        self.seq_length = int(seq_length)
        self.prediction_length = int(prediction_length)
        self.num_blocks = tuple(num_blocks)
        self.expansion_coefficient_lengths = tuple(expansion_coefficient_lengths)
        self.widths = tuple(widths)
        self.sharing = tuple(sharing)
        self.backcast_loss_ratio = backcast_loss_ratio
        self.learning_rate = learning_rate
        self.random_seed = random_seed if random_seed is not None else config.RANDOM_SEED

        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = device

        self.model: Any = None
        self.training_dataset: Any = None
        self.trainer: Any = None

        torch.manual_seed(self.random_seed)
        np.random.seed(self.random_seed)

    def _series_to_df(self, series: np.ndarray, group_id: str = "0"):
        """1D 시계열을 N-BEATS용 DataFrame으로 변환."""
        arr = np.asarray(series, dtype=np.float32).reshape(-1)
        return pd.DataFrame(
            {
                "time_idx": np.arange(len(arr), dtype=np.int64),
                "group_id": [group_id] * len(arr),
                "target": arr,
            }
        )

    def _build_dataset(
        self,
        df,
        is_train: bool = True,
        from_dataset: Any = None,
    ):
        """N-BEATS는 univariate. time_varying_unknown_reals=['target']만."""
        if from_dataset is not None:
            return TimeSeriesDataSet.from_dataset(
                from_dataset, df, predict=not is_train, stop_randomization=True
            )

        return TimeSeriesDataSet(
            df,
            time_idx="time_idx",
            target="target",
            group_ids=["group_id"],
            max_encoder_length=self.seq_length,
            max_prediction_length=self.prediction_length,
            time_varying_unknown_reals=["target"],
            target_normalizer=None,  # NBeats는 raw 시계열 그대로 처리
            add_relative_time_idx=False,
            add_target_scales=False,
            add_encoder_length=False,
            allow_missing_timesteps=True,
        )

    def _build_model_from_dataset(self, dataset: Any) -> None:
        """TimeSeriesDataSet 기반 N-BEATS 인스턴스 생성."""
        self.model = NBeats.from_dataset(
            dataset,
            learning_rate=self.learning_rate,
            log_interval=0,
            log_val_interval=0,
            weight_decay=1e-2,
            widths=list(self.widths),
            backcast_loss_ratio=self.backcast_loss_ratio,
            num_blocks=list(self.num_blocks),
            expansion_coefficient_lengths=list(self.expansion_coefficient_lengths),
            sharing=list(self.sharing),
            stack_types=["trend", "seasonality"],
            loss=MAE(),
        )

    def train(
        self,
        series: np.ndarray,
        val_series: np.ndarray | None = None,
        max_epochs: int = 30,
        batch_size: int = 64,
    ) -> dict:
        """학습 수행. univariate 시계열 (1D ndarray)."""
        df_tr = self._series_to_df(series, group_id="train")
        train_dataset = self._build_dataset(df_tr, is_train=True)
        self.training_dataset = train_dataset

        val_dataset = None
        if val_series is not None:
            # train tail + val 결합 (encoder window 확보)
            tail_len = min(self.seq_length, len(series))
            tail = np.asarray(series, dtype=np.float32)[-tail_len:]
            val_full = np.concatenate(
                [tail, np.asarray(val_series, dtype=np.float32).reshape(-1)]
            )
            df_val = self._series_to_df(val_full, group_id="val")
            val_dataset = self._build_dataset(
                df_val, is_train=False, from_dataset=train_dataset
            )

        self._build_model_from_dataset(train_dataset)

        train_loader = train_dataset.to_dataloader(
            train=True, batch_size=batch_size, num_workers=0
        )
        val_loader = None
        if val_dataset is not None:
            val_loader = val_dataset.to_dataloader(
                train=False, batch_size=batch_size, num_workers=0
            )

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
            "max_epochs": int(max_epochs),
            "device": self.device,
            "stack_types": ["trend", "seasonality"],
        }

    def predict(self, series: np.ndarray, steps: int = 1) -> np.ndarray:
        """예측. series 마지막 seq_length를 입력으로 steps만큼 forecast."""
        if self.model is None:
            raise RuntimeError("Model is not trained yet")
        if self.training_dataset is None:
            raise RuntimeError("training_dataset is missing; call train() first")

        arr = np.asarray(series, dtype=np.float32).reshape(-1)
        # forecast horizon은 prediction_length 고정 → steps>prediction_length면 반복 forecast
        if steps > self.prediction_length:
            preds = []
            cur = arr.copy()
            remaining = steps
            while remaining > 0:
                horizon = min(self.prediction_length, remaining)
                df = self._series_to_df(cur, group_id="pred")
                ds = self._build_dataset(df, is_train=False, from_dataset=self.training_dataset)
                loader = ds.to_dataloader(train=False, batch_size=1, num_workers=0)
                raw = self.model.predict(loader, mode="prediction")
                if hasattr(raw, "cpu"):
                    raw = raw.cpu().numpy()
                step_pred = np.asarray(raw, dtype=np.float32).reshape(-1)[:horizon]
                preds.append(step_pred)
                cur = np.concatenate([cur, step_pred])
                remaining -= horizon
            return np.concatenate(preds)

        df = self._series_to_df(arr, group_id="pred")
        ds = self._build_dataset(df, is_train=False, from_dataset=self.training_dataset)
        loader = ds.to_dataloader(train=False, batch_size=1, num_workers=0)
        raw = self.model.predict(loader, mode="prediction")
        if hasattr(raw, "cpu"):
            raw = raw.cpu().numpy()
        return np.asarray(raw, dtype=np.float32).reshape(-1)[:steps]

    def decompose(self, series: np.ndarray) -> dict:
        """N-BEATS basis 기반 분해.

        반환:
          - "trend": (T,) trend stack 출력
          - "seasonality": (T,) seasonal stack 출력
          - "residual": (T,) target - (trend+seasonality)
        """
        if self.model is None:
            raise RuntimeError("Model is not trained yet")
        if self.training_dataset is None:
            raise RuntimeError("training_dataset is missing; call train() first")

        arr = np.asarray(series, dtype=np.float32).reshape(-1)
        df = self._series_to_df(arr, group_id="dec")
        ds = self._build_dataset(df, is_train=False, from_dataset=self.training_dataset)
        loader = ds.to_dataloader(train=False, batch_size=1, num_workers=0)

        raw_predictions, x = self.model.predict(loader, mode="raw", return_x=True)

        # NBeats raw 출력: dict with "prediction", "backcast", and per-block decomposition
        # interpret_output 또는 직접 stack-level 출력 사용
        try:
            interp = self.model.interpret_output(raw_predictions)
        except Exception:
            interp = {}

        def _to_np(t):
            if t is None:
                return np.zeros((0,), dtype=np.float32)
            if hasattr(t, "cpu"):
                t = t.cpu().numpy()
            return np.asarray(t, dtype=np.float32).reshape(-1)

        trend = _to_np(interp.get("trend", None))
        seasonality = _to_np(interp.get("seasonality", None))

        # backcast 길이만큼 입력 tail과 비교해 residual 산출
        backcast = raw_predictions.get("backcast", None) if isinstance(raw_predictions, dict) else None
        backcast_np = _to_np(backcast)
        prediction_np = _to_np(
            raw_predictions.get("prediction", None) if isinstance(raw_predictions, dict) else None
        )

        # residual: target tail - (trend + seasonality) (길이 정합 시도)
        if trend.size > 0 and seasonality.size > 0:
            ref_len = min(trend.size, seasonality.size)
            tail = arr[-ref_len:] if ref_len > 0 else arr
            residual = tail[:ref_len] - (trend[:ref_len] + seasonality[:ref_len])
        else:
            # fallback: backcast 잔차
            if backcast_np.size > 0:
                tail = arr[-backcast_np.size:]
                residual = tail - backcast_np
            else:
                residual = np.zeros((0,), dtype=np.float32)

        return {
            "trend": trend,
            "seasonality": seasonality,
            "residual": np.asarray(residual, dtype=np.float32),
            "backcast": backcast_np,
            "prediction": prediction_np,
        }

    def save(self, path: str) -> None:
        """모델 직렬화."""
        if self.model is None:
            raise RuntimeError("Model is not trained yet")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        torch.save(
            {
                "state_dict": self.model.state_dict(),
                "hparams": dict(self.model.hparams),
                "seq_length": self.seq_length,
                "prediction_length": self.prediction_length,
            },
            path,
        )

    def load(self, path: str) -> None:
        """모델 로드 (state_dict만 복원, train()으로 dataset/model 재구성 필요)."""
        if not os.path.exists(path):
            raise FileNotFoundError(f"Model file not found: {path}")
        ckpt = torch.load(path, map_location=self.device, weights_only=False)
        if self.model is not None:
            self.model.load_state_dict(ckpt["state_dict"])

    @classmethod
    def load_from_checkpoint(cls, model_dir: str, filename: str = "nbeats_sum.pt") -> "LottoNBeats":
        """saved_models/nbeats_sum.pt 로드 + 인스턴스 반환.

        Args:
            model_dir: 모델 디렉토리 (config.MODEL_DIR)
            filename: 모델 파일명 (기본 nbeats_sum.pt)

        Returns:
            학습된 가중치를 로드한 LottoNBeats 인스턴스
        """
        path = os.path.join(model_dir, filename)
        if not os.path.exists(path):
            raise FileNotFoundError(f"NBeats model not found: {path}")

        ckpt = torch.load(path, map_location="cpu", weights_only=False)

        # 저장된 하이퍼파라미터로 인스턴스 생성
        seq_length = ckpt.get("seq_length", 50)
        prediction_length = ckpt.get("prediction_length", 1)

        instance = cls(
            seq_length=seq_length,
            prediction_length=prediction_length,
            device="cpu",
        )

        # 모델 구조 재구성을 위해 dummy dataset 필요 (최소 시계열 생성)
        dummy_series = np.zeros(seq_length + prediction_length, dtype=np.float32)
        df = instance._series_to_df(dummy_series, group_id="dummy")
        dataset = instance._build_dataset(df, is_train=True)
        instance.training_dataset = dataset
        instance._build_model_from_dataset(dataset)

        # state_dict 로드
        instance.model.load_state_dict(ckpt["state_dict"])
        instance.model.eval()

        return instance


def _smoke_test() -> int:
    """smoke 테스트: 가짜 1D 시계열 200스텝으로 1 epoch 학습."""
    if not PYTORCH_FORECASTING_AVAILABLE:
        print(
            "[nbeats_model] requires pytorch-forecasting library, "
            "install with: pip install pytorch-forecasting"
        )
        return 0

    print("[nbeats_model] smoke start")
    rng = np.random.default_rng(config.RANDOM_SEED)
    t = np.arange(200, dtype=np.float32)
    series = (
        np.sin(2 * np.pi * t / 12.0).astype(np.float32)
        + 0.05 * t
        + 0.1 * rng.standard_normal(size=200).astype(np.float32)
    )
    val = series[-30:]
    train = series[:-10]

    model = LottoNBeats(
        seq_length=20,
        prediction_length=1,
        num_blocks=(2, 2),
        expansion_coefficient_lengths=(3, 5),
        widths=(16, 32),
        learning_rate=1e-3,
    )

    info = model.train(train, val_series=val, max_epochs=1, batch_size=16)
    print(
        f"[nbeats_model] train info: epochs={info['max_epochs']} "
        f"device={info['device']} stacks={info['stack_types']}"
    )

    pred = model.predict(train, steps=3)
    print(f"[nbeats_model] predict shape: {pred.shape} values: {pred[:3].tolist()}")

    try:
        dec = model.decompose(train)
        print(
            f"[nbeats_model] decompose trend={dec['trend'].shape} "
            f"seasonality={dec['seasonality'].shape} residual={dec['residual'].shape}"
        )
    except Exception as exc:
        print(f"[nbeats_model] decompose skipped: {type(exc).__name__}: {exc}")

    tmp_path = os.path.join(config.MODEL_DIR, "_smoke_nbeats.pt")
    model.save(tmp_path)
    print(f"[nbeats_model] saved to {tmp_path}")

    try:
        os.remove(tmp_path)
    except OSError:
        pass

    print("[nbeats_model] smoke OK")
    return 0


if __name__ == "__main__":
    import sys

    if "--smoke" in sys.argv:
        sys.exit(_smoke_test())
    print("[nbeats_model] use --smoke to run smoke test")
