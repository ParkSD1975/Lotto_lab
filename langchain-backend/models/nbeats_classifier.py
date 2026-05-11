"""N-BEATS based binary classifier for main 1~45 (옵션 B 사용자 결정).

원본 LottoNBeats(`models/nbeats_model.py`)는 sum/AC 등 *스칼라 시계열*만 예측.
사용자 결정 (2026-05-12): 11-base 11개 모델 *모두* 메인 1~45 binary classifier 활성화.

본 모듈은 N-BEATS theoretical decomposition (trend/seasonality stack)을 흉내내는
MLP backbone + sigmoid 45-D head로 *번호별 binary classifier* 제공.

설계:
  - 본질: bayesian_nn_model.py의 binary_45 패턴 그대로 카피
  - 차이점:
    1. N-BEATS 아이덴티티 유지를 위해 *trend/seasonality 분해 가설*에 따른 stack 구조
       (실제로는 residual MLP block 2개로 근사)
    2. MC Dropout 제거 (deterministic forecast, N-BEATS 본질 일치)
    3. saved_models/nbeats_main45.pt 별도 저장 (기존 nbeats_sum.pt와 분리)

호환 인터페이스:
  - train(draws, fine_tune=False): ensemble.train_all 자동 호출
  - predict(draws): {1~45: float} 반환 (ensemble.predict 호환)
"""

from __future__ import annotations

import os
from typing import Any

import numpy as np

import config

try:
    import torch
    import torch.nn as nn

    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    torch = None  # type: ignore
    nn = None  # type: ignore


class _NBeatsResidualBlock(nn.Module if TORCH_AVAILABLE else object):
    """N-BEATS basis block — 4-layer MLP + backcast/forecast residual.

    원본 N-BEATS는 lookback → (backcast, forecast)를 동시 출력하고 residual 학습.
    여기서는 forecast head만 사용 (binary 45 output).
    """

    def __init__(self, input_dim: int, hidden_dim: int, dropout: float = 0.2):
        super().__init__()
        self.mlp = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
        )
        # backcast (input_dim) + forecast (45)
        self.backcast_head = nn.Linear(hidden_dim, input_dim)
        self.forecast_head = nn.Linear(hidden_dim, 45)

    def forward(self, x):
        h = self.mlp(x)
        backcast = self.backcast_head(h)
        forecast = self.forecast_head(h)
        return backcast, forecast


class _LottoNBeatsBackbone(nn.Module if TORCH_AVAILABLE else object):
    """N-BEATS doubly-residual stack — 2 blocks (trend + seasonality 가설).

    실제 trend/seasonality basis 강제 X (generic). residual 학습으로 분해 효과.
    """

    def __init__(self, input_dim: int, hidden_dim: int, dropout: float = 0.2):
        super().__init__()
        self.block_trend = _NBeatsResidualBlock(input_dim, hidden_dim, dropout)
        self.block_season = _NBeatsResidualBlock(input_dim, hidden_dim, dropout)

    def forward(self, x):
        # 첫 block: trend
        backcast_t, forecast_t = self.block_trend(x)
        residual = x - backcast_t
        # 둘째 block: seasonality (잔차에서)
        _, forecast_s = self.block_season(residual)
        # forecast는 두 block 합
        return forecast_t + forecast_s


class LottoNBeatsBinary:
    """N-BEATS basis로 메인 1~45 binary classifier.

    사용자 결정 (2026-05-12): 옵션 B — 11 base 모두 binary 활성.
    """

    def __init__(
        self,
        input_dim: int = 65,
        hidden_dim: int = 64,
        dropout: float = 0.2,
        learning_rate: float = 1e-3,
        weight_decay: float = 1e-5,
        random_seed: int | None = None,
        device: str | None = None,
        **kwargs: Any,
    ) -> None:
        self.input_dim = int(input_dim)
        self.hidden_dim = int(hidden_dim)
        self.dropout = float(dropout)
        self.learning_rate = float(learning_rate)
        self.weight_decay = float(weight_decay)
        self.random_seed = random_seed if random_seed is not None else getattr(config, "RANDOM_SEED", 42)
        self.task_type = "binary_45"  # ensemble 어댑터 호환
        self._torch_available = TORCH_AVAILABLE

        if not TORCH_AVAILABLE:
            self.device = "cpu"
            self.model = None
            return

        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = torch.device(device)

        torch.manual_seed(self.random_seed)
        np.random.seed(self.random_seed)

        self.model: Any = _LottoNBeatsBackbone(self.input_dim, self.hidden_dim, self.dropout).to(self.device)

    # ---------- ensemble.train_all 어댑터 ----------

    def train(self, draws, fine_tune: bool = False, verbose: bool = False, **kwargs) -> dict:
        """ensemble.train_all 호환 — draws → (X, y) 변환 후 학습.

        Args:
            draws: list[dict] (lotto_draws fetch 결과)
            fine_tune: True면 기존 nbeats_main45.pt 가중치에서 재학습
        """
        if not TORCH_AVAILABLE:
            return {"success": False, "skipped": "library_missing"}

        if not isinstance(draws, list) or not draws:
            return {"success": False, "error": "draws must be non-empty list"}

        try:
            from models._draws_adapter import draws_to_xy
            X, y = draws_to_xy(draws, seq_len=30, input_dim=self.input_dim)
            if X.shape[0] < 50:
                return {"success": False, "error": f"too few samples: {X.shape[0]}"}

            split = int(X.shape[0] * 0.85)
            X_tr, X_val = X[:split], X[split:]
            y_tr, y_val = y[:split], y[split:]

            ckpt_path = os.path.join(config.MODEL_DIR, "nbeats_main45.pt")
            if fine_tune and os.path.exists(ckpt_path):
                try:
                    self.load(ckpt_path)
                    if verbose:
                        print("[nbeats_classifier] fine_tune: prior weights loaded")
                except Exception as e:
                    print(f"[nbeats_classifier] fine_tune load fail (from scratch): {e}")
                    self.model = _LottoNBeatsBackbone(self.input_dim, self.hidden_dim, self.dropout).to(self.device)
            else:
                self.model = _LottoNBeatsBackbone(self.input_dim, self.hidden_dim, self.dropout).to(self.device)

            info = self._train_loop(X_tr, y_tr, X_val=X_val, y_val=y_val,
                                     max_epochs=20, batch_size=64, verbose=verbose)
            try:
                self.save(ckpt_path)
                info["saved_to"] = ckpt_path
            except Exception as e:
                info["save_error"] = str(e)
            return info
        except Exception as e:
            return {"success": False, "error": f"{type(e).__name__}: {e}"}

    def _train_loop(self, X, y, X_val=None, y_val=None,
                     max_epochs: int = 20, batch_size: int = 64,
                     verbose: bool = False) -> dict:
        X_arr = np.asarray(X, dtype=np.float32)
        y_arr = np.asarray(y, dtype=np.float32)
        x_tensor = torch.from_numpy(X_arr).to(self.device)
        y_tensor = torch.from_numpy(y_arr).to(self.device)

        criterion = nn.BCEWithLogitsLoss()
        optimizer = torch.optim.Adam(self.model.parameters(),
                                      lr=self.learning_rate, weight_decay=self.weight_decay)

        n = X_arr.shape[0]
        history: list[float] = []
        val_history: list[float] = []

        for epoch in range(max_epochs):
            self.model.train()
            perm = torch.randperm(n, device=self.device)
            running = 0.0
            count = 0
            for i in range(0, n, batch_size):
                idx = perm[i:i + batch_size]
                xb = x_tensor[idx]
                yb = y_tensor[idx]
                optimizer.zero_grad()
                logits = self.model(xb)
                loss = criterion(logits, yb)
                loss.backward()
                optimizer.step()
                running += float(loss.detach().cpu().item()) * xb.shape[0]
                count += xb.shape[0]
            avg = running / max(count, 1)
            history.append(avg)

            if X_val is not None and y_val is not None:
                vloss = self._eval_loss(X_val, y_val, criterion)
                val_history.append(vloss)
                if verbose:
                    print(f"[nbeats_classifier] epoch {epoch + 1}: train={avg:.4f} val={vloss:.4f}")
            elif verbose:
                print(f"[nbeats_classifier] epoch {epoch + 1}: train={avg:.4f}")

        return {
            "success": True,
            "task_type": self.task_type,
            "epochs": max_epochs,
            "final_train_loss": history[-1] if history else 0.0,
            "final_val_loss": val_history[-1] if val_history else None,
            "train_loss_history": history,
            "val_loss_history": val_history,
        }

    def _eval_loss(self, X_val, y_val, criterion):
        self.model.eval()
        with torch.no_grad():
            xb = torch.from_numpy(np.asarray(X_val, dtype=np.float32)).to(self.device)
            yb = torch.from_numpy(np.asarray(y_val, dtype=np.float32)).to(self.device)
            logits = self.model(xb)
            loss = criterion(logits, yb)
        return float(loss.detach().cpu().item())

    # ---------- inference ----------

    def predict(self, draws_or_X, **kwargs):
        """Polymorphic 예측.

        - draws_or_X 가 list[dict]: {1~45: float} 반환 (ensemble.predict 호환).
        - 그 외 (ndarray): logits 또는 sigmoid 평균.
        """
        if isinstance(draws_or_X, list) and draws_or_X and isinstance(draws_or_X[0], dict):
            return self._predict_from_draws(draws_or_X)
        return self._predict_main(draws_or_X)

    def _predict_main(self, X: np.ndarray) -> np.ndarray:
        if not TORCH_AVAILABLE or self.model is None:
            return np.full((len(X) if hasattr(X, "__len__") else 1, 45), 1.0 / 45.0, dtype=np.float32)
        X_arr = np.asarray(X, dtype=np.float32)
        self.model.eval()
        with torch.no_grad():
            x_tensor = torch.from_numpy(X_arr).to(self.device)
            logits = self.model(x_tensor)
            probs = torch.sigmoid(logits)
        return probs.detach().cpu().numpy().astype(np.float32)

    def _predict_from_draws(self, draws: list) -> dict:
        if not TORCH_AVAILABLE:
            return {n: 1.0 / 45.0 for n in range(1, 46)}

        try:
            from models._draws_adapter import draws_to_xy
            X, _ = draws_to_xy(draws, seq_len=30, input_dim=self.input_dim)
            if X is None or len(X) == 0:
                return {n: 1.0 / 45.0 for n in range(1, 46)}

            # 모델 ckpt 로드 (필요 시)
            ckpt_path = os.path.join(config.MODEL_DIR, "nbeats_main45.pt")
            if self.model is None:
                if not os.path.exists(ckpt_path):
                    return {n: 1.0 / 45.0 for n in range(1, 46)}
                try:
                    self.load(ckpt_path)
                except Exception:
                    return {n: 1.0 / 45.0 for n in range(1, 46)}

            if self.model is None:
                return {n: 1.0 / 45.0 for n in range(1, 46)}

            x_query = X[-1:].astype(np.float32)
            probs = self._predict_main(x_query)
            if probs.ndim == 2 and probs.shape[-1] == 45:
                flat = probs[0]
            elif probs.ndim == 1 and probs.shape[0] == 45:
                flat = probs
            else:
                return {n: 1.0 / 45.0 for n in range(1, 46)}
            return {int(n): float(flat[n - 1]) for n in range(1, 46)}
        except Exception as e:
            print(f"[nbeats_classifier] predict_from_draws fail (graceful): {type(e).__name__}: {e}")
            return {n: 1.0 / 45.0 for n in range(1, 46)}

    # ---------- persistence ----------

    def save(self, path: str) -> None:
        if self.model is None:
            raise RuntimeError("Model not built")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        state = {
            "input_dim": self.input_dim,
            "hidden_dim": self.hidden_dim,
            "dropout": self.dropout,
            "learning_rate": self.learning_rate,
            "weight_decay": self.weight_decay,
            "random_seed": self.random_seed,
            "task_type": self.task_type,
            "model_state": self.model.state_dict(),
        }
        torch.save(state, path)

    def load(self, path: str) -> None:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Model file not found: {path}")
        state = torch.load(path, map_location=self.device, weights_only=False)
        self.input_dim = int(state["input_dim"])
        self.hidden_dim = int(state["hidden_dim"])
        self.dropout = float(state["dropout"])
        self.learning_rate = float(state["learning_rate"])
        self.weight_decay = float(state["weight_decay"])
        self.random_seed = int(state["random_seed"])
        self.task_type = state.get("task_type", "binary_45")

        self.model = _LottoNBeatsBackbone(self.input_dim, self.hidden_dim, self.dropout).to(self.device)
        self.model.load_state_dict(state["model_state"])
