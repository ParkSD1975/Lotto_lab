"""Bayesian Neural Network wrapper (MC Dropout).

가중치 분포 근사를 MC Dropout 으로 구현. 추론 시 dropout 활성 상태로
mc_samples 회 forward 하여 평균/분산/quantile 을 노출한다.
4 Pillar Pillar 1(Bayesian sigma) + NumberXAIExplainer 입력 전담.
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


_TASK_TYPES = ("binary_45", "multiclass", "regression")


class _MCDropoutMLP(nn.Module if TORCH_AVAILABLE else object):
    """MC Dropout MLP. dropout 은 학습/추론 모두 활성 상태 유지."""

    def __init__(
        self,
        input_dim: int,
        hidden_dim: int,
        num_layers: int,
        output_dim: int,
        dropout: float,
    ) -> None:
        super().__init__()
        layers: list[Any] = []
        prev = input_dim
        for _ in range(num_layers):
            layers.append(nn.Linear(prev, hidden_dim))
            layers.append(nn.ReLU())
            layers.append(nn.Dropout(dropout))
            prev = hidden_dim
        layers.append(nn.Linear(prev, output_dim))
        self.net = nn.Sequential(*layers)

    def forward(self, x):  # type: ignore[no-untyped-def]
        return self.net(x)


class LottoBayesianNN:
    """MC Dropout 기반 Bayesian NN wrapper.

    predict_with_uncertainty() 는 mc_samples 회 forward 후
    mean/std/q10/q50/q90 을 반환 (sigma 노출 핵심).
    """

    def __init__(
        self,
        input_dim: int,
        hidden_dim: int = 64,
        num_layers: int = 2,
        dropout: float = 0.2,
        num_classes: int = 45,
        mc_samples: int = 50,
        task_type: str = "binary_45",
        learning_rate: float = 1e-3,
        weight_decay: float = 1e-5,
        random_seed: int | None = None,
        device: str | None = None,
        **kwargs: Any,
    ) -> None:
        # 인자 검증은 라이브러리 유무와 독립적으로 우선 수행 (Stage 1-4-D-2-fix-2)
        if task_type not in _TASK_TYPES:
            raise ValueError(f"task_type must be one of {_TASK_TYPES}, got {task_type}")

        self.input_dim = int(input_dim)
        self.hidden_dim = int(hidden_dim)
        self.num_layers = int(num_layers)
        self.dropout = float(dropout)
        self.num_classes = int(num_classes)
        self.mc_samples = int(mc_samples)
        self.task_type = task_type
        self.learning_rate = float(learning_rate)
        self.weight_decay = float(weight_decay)
        self.random_seed = random_seed if random_seed is not None else config.RANDOM_SEED
        self._torch_available = TORCH_AVAILABLE

        if not TORCH_AVAILABLE:
            # 라이브러리 미설치 시 lazy 모드 — 인스턴스화만 OK, 학습/예측 호출 시 ImportError
            self.device = "cpu"
            self.model = None
            np.random.seed(self.random_seed)
            return

        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = torch.device(device)

        torch.manual_seed(self.random_seed)
        np.random.seed(self.random_seed)

        out_dim = self._resolve_out_dim()
        self.model: Any = _MCDropoutMLP(
            self.input_dim, self.hidden_dim, self.num_layers, out_dim, self.dropout
        ).to(self.device)

    def _resolve_out_dim(self) -> int:
        if self.task_type == "binary_45":
            return self.num_classes  # 45 멀티핫
        if self.task_type == "multiclass":
            return self.num_classes
        return 1  # regression

    def _criterion(self) -> Any:
        if self.task_type == "binary_45":
            return nn.BCEWithLogitsLoss()
        if self.task_type == "multiclass":
            return nn.CrossEntropyLoss()
        return nn.MSELoss()

    def _prep_y(self, y: np.ndarray) -> Any:
        if self.task_type == "binary_45":
            return torch.from_numpy(np.asarray(y, dtype=np.float32)).to(self.device)
        if self.task_type == "multiclass":
            return torch.from_numpy(np.asarray(y, dtype=np.int64).reshape(-1)).to(self.device)
        # regression
        arr = np.asarray(y, dtype=np.float32).reshape(-1, 1)
        return torch.from_numpy(arr).to(self.device)

    # ---------- training ----------

    def train(
        self,
        X: Any,
        y: np.ndarray | None = None,
        X_val: np.ndarray | None = None,
        y_val: np.ndarray | None = None,
        max_epochs: int = 50,
        batch_size: int = 64,
        verbose: bool = False,
        fine_tune: bool = False,
    ) -> dict:
        """학습.

        오버로드:
          - train(X: ndarray, y: ndarray, ...) - 기존 supervised 학습.
          - train(draws: list[dict], fine_tune: bool=False) - ensemble.train_all
            호환 어댑터. draws -> (X, y) 변환 후 위임.
        """
        # ensemble.train_all 어댑터 분기 — 첫 인자가 draws 리스트인지 검사
        if isinstance(X, list) and (len(X) == 0 or isinstance(X[0], dict)):
            return self._train_from_draws(X, fine_tune=fine_tune, verbose=verbose)

        return self._train_main(
            X, y, X_val=X_val, y_val=y_val,
            max_epochs=max_epochs, batch_size=batch_size, verbose=verbose,
        )

    def _train_main(
        self,
        X: np.ndarray,
        y: np.ndarray,
        X_val: np.ndarray | None = None,
        y_val: np.ndarray | None = None,
        max_epochs: int = 50,
        batch_size: int = 64,
        verbose: bool = False,
    ) -> dict:
        """BCE/CE/MSE 학습. dropout 은 학습/추론 모두 활성."""
        X_arr = np.asarray(X, dtype=np.float32)
        y_tensor = self._prep_y(y)
        x_tensor = torch.from_numpy(X_arr).to(self.device)

        criterion = self._criterion()
        optimizer = torch.optim.Adam(
            self.model.parameters(),
            lr=self.learning_rate,
            weight_decay=self.weight_decay,
        )

        n = X_arr.shape[0]
        history: list[float] = []
        val_history: list[float] = []

        for epoch in range(max_epochs):
            self.model.train()
            perm = torch.randperm(n, device=self.device)
            running = 0.0
            count = 0
            for i in range(0, n, batch_size):
                idx = perm[i : i + batch_size]
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
                    print(f"[bayesian_nn_model] epoch {epoch + 1}: train={avg:.4f} val={vloss:.4f}")
            elif verbose:
                print(f"[bayesian_nn_model] epoch {epoch + 1}: train={avg:.4f}")

        return {
            "success": True,
            "task_type": self.task_type,
            "epochs": max_epochs,
            "final_train_loss": history[-1] if history else 0.0,
            "final_val_loss": val_history[-1] if val_history else None,
            "train_loss_history": history,
            "val_loss_history": val_history,
        }

    def _eval_loss(self, X_val: np.ndarray, y_val: np.ndarray, criterion: Any) -> float:
        self.model.eval()
        with torch.no_grad():
            xb = torch.from_numpy(np.asarray(X_val, dtype=np.float32)).to(self.device)
            yb = self._prep_y(y_val)
            logits = self.model(xb)
            loss = criterion(logits, yb)
        return float(loss.detach().cpu().item())

    def _train_from_draws(
        self, draws: list, fine_tune: bool = False, verbose: bool = False
    ) -> dict:
        """ensemble.train_all 호환 어댑터. draws -> (X, y) -> _train_main."""
        if not TORCH_AVAILABLE:
            print("[bayesian_nn_model] skip: torch missing")
            return {"success": False, "skipped": "library_missing"}
        if self.task_type != "binary_45":
            return {"success": False, "error": f"task_type must be binary_45 for adapter, got {self.task_type}"}

        try:
            from models._draws_adapter import draws_to_xy
            X, y = draws_to_xy(draws, seq_len=30, input_dim=self.input_dim)
            if X.shape[0] < 50:
                return {"success": False, "error": f"too few samples after conversion: {X.shape[0]}"}

            split = int(X.shape[0] * 0.85)
            X_tr, X_val = X[:split], X[split:]
            y_tr, y_val = y[:split], y[split:]

            if fine_tune:
                ckpt_path = os.path.join(config.MODEL_DIR, "bayesian_nn_main45.pt")
                if os.path.exists(ckpt_path):
                    try:
                        self.load(ckpt_path)
                        print("[bayesian_nn_model] fine_tune: prior weights loaded")
                    except Exception as e:
                        print(f"[bayesian_nn_model] fine_tune load fail (from scratch): {e}")
                        out_dim = self._resolve_out_dim()
                        self.model = _MCDropoutMLP(
                            self.input_dim, self.hidden_dim, self.num_layers, out_dim, self.dropout
                        ).to(self.device)
            else:
                out_dim = self._resolve_out_dim()
                self.model = _MCDropoutMLP(
                    self.input_dim, self.hidden_dim, self.num_layers, out_dim, self.dropout
                ).to(self.device)

            info = self._train_main(
                X_tr, y_tr, X_val=X_val, y_val=y_val,
                max_epochs=20, batch_size=64, verbose=verbose,
            )
            try:
                save_path = os.path.join(config.MODEL_DIR, "bayesian_nn_main45.pt")
                self.save(save_path)
                info["saved_to"] = save_path
            except Exception as e:
                info["save_error"] = str(e)
            return info
        except Exception as e:
            return {"success": False, "error": f"{type(e).__name__}: {e}"}

    # ---------- inference ----------

    def _activate(self, logits: Any) -> Any:
        if self.task_type == "binary_45":
            return torch.sigmoid(logits)
        if self.task_type == "multiclass":
            return torch.softmax(logits, dim=1)
        return logits  # regression

    def predict(self, draws_or_X, **kwargs):
        """Polymorphic 예측.

        - draws_or_X 가 list[dict] (ensemble.predict 호환): {1~45: float} 반환.
        - 그 외 (ndarray 등): 기존 ndarray 반환 (mean).
        """
        if isinstance(draws_or_X, list) and draws_or_X and isinstance(draws_or_X[0], dict):
            return self._predict_from_draws(draws_or_X)
        return self._predict_main(draws_or_X, **kwargs)

    def _predict_main(self, X: np.ndarray, **kwargs: Any) -> np.ndarray:
        """MC Dropout 평균 (mc_samples 회 forward 평균)."""
        result = self.predict_with_uncertainty(X)
        return result["mean"]

    def _is_main_trained(self) -> bool:
        """binary_45 메인 가중치 학습 여부."""
        if not TORCH_AVAILABLE:
            return False
        if self.model is not None:
            # 가중치가 있는지 — 인스턴스 model이 _MCDropoutMLP면 OK
            return True
        save_path = os.path.join(config.MODEL_DIR, "bayesian_nn_main45.pt")
        return os.path.exists(save_path)

    def _predict_from_draws(self, draws: list) -> dict:
        """draws -> {1~45: float} (메인 1~45 binary)."""
        if not TORCH_AVAILABLE:
            return {n: 0.0 for n in range(1, 46)}

        try:
            from models._draws_adapter import draws_to_xy
            X, _ = draws_to_xy(draws, seq_len=30, input_dim=self.input_dim)
            if X is None or len(X) == 0:
                return {n: 0.0 for n in range(1, 46)}

            # 메인 모델 확보 — 없으면 ckpt 로드
            if self.model is None:
                save_path = os.path.join(config.MODEL_DIR, "bayesian_nn_main45.pt")
                if not os.path.exists(save_path):
                    return {n: 0.0 for n in range(1, 46)}
                try:
                    self.load(save_path)
                except Exception:
                    return {n: 0.0 for n in range(1, 46)}

            if self.model is None:
                return {n: 0.0 for n in range(1, 46)}

            x_query = X[-1:].astype(np.float32)
            result = self.predict_with_uncertainty(x_query)
            mean = result["mean"]
            if mean.ndim == 2 and mean.shape[-1] == 45:
                flat = mean[0]
            elif mean.ndim == 1 and mean.shape[0] == 45:
                flat = mean
            else:
                return {n: 0.0 for n in range(1, 46)}
            return {n: float(flat[n - 1]) for n in range(1, 46)}
        except Exception as e:
            print(f"[bayesian_nn_model] predict_from_draws fail (graceful): {type(e).__name__}: {e}")
            return {n: 0.0 for n in range(1, 46)}

    def predict_with_uncertainty(self, X: np.ndarray) -> dict:
        """mc_samples 회 forward 후 평균/분산/quantile 반환.

        반환 dict: mean, std, q10, q50, q90 (각 ndarray, shape 동일)
        """
        X_arr = np.asarray(X, dtype=np.float32)
        x_tensor = torch.from_numpy(X_arr).to(self.device)

        # MC Dropout: train mode 유지하여 dropout 활성
        self.model.train()
        samples: list[np.ndarray] = []
        with torch.no_grad():
            for _ in range(self.mc_samples):
                logits = self.model(x_tensor)
                act = self._activate(logits)
                samples.append(act.detach().cpu().numpy().astype(np.float32))

        stacked = np.stack(samples, axis=0)  # (S, N, ...)
        mean = stacked.mean(axis=0)
        std = stacked.std(axis=0)
        q10 = np.percentile(stacked, 10.0, axis=0).astype(np.float32)
        q50 = np.percentile(stacked, 50.0, axis=0).astype(np.float32)
        q90 = np.percentile(stacked, 90.0, axis=0).astype(np.float32)

        # regression 출력 (N, 1) → (N,) 정리
        if self.task_type == "regression":
            mean = mean.reshape(-1)
            std = std.reshape(-1)
            q10 = q10.reshape(-1)
            q50 = q50.reshape(-1)
            q90 = q90.reshape(-1)

        return {
            "mean": mean.astype(np.float32),
            "std": std.astype(np.float32),
            "q10": q10,
            "q50": q50,
            "q90": q90,
        }

    # ---------- persistence ----------

    def save(self, path: str) -> None:
        """모델 직렬화 (state_dict + 하이퍼파라미터)."""
        if self.model is None:
            raise RuntimeError("Model not built")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        state = {
            "input_dim": self.input_dim,
            "hidden_dim": self.hidden_dim,
            "num_layers": self.num_layers,
            "dropout": self.dropout,
            "num_classes": self.num_classes,
            "mc_samples": self.mc_samples,
            "task_type": self.task_type,
            "learning_rate": self.learning_rate,
            "weight_decay": self.weight_decay,
            "random_seed": self.random_seed,
            "model_state": self.model.state_dict(),
        }
        torch.save(state, path)

    def load(self, path: str) -> None:
        """모델 로드."""
        if not os.path.exists(path):
            raise FileNotFoundError(f"Model file not found: {path}")
        state = torch.load(path, map_location=self.device, weights_only=False)

        self.input_dim = int(state["input_dim"])
        self.hidden_dim = int(state["hidden_dim"])
        self.num_layers = int(state["num_layers"])
        self.dropout = float(state["dropout"])
        self.num_classes = int(state["num_classes"])
        self.mc_samples = int(state["mc_samples"])
        self.task_type = state["task_type"]
        self.learning_rate = float(state["learning_rate"])
        self.weight_decay = float(state["weight_decay"])
        self.random_seed = int(state["random_seed"])

        out_dim = self._resolve_out_dim()
        self.model = _MCDropoutMLP(
            self.input_dim, self.hidden_dim, self.num_layers, out_dim, self.dropout
        ).to(self.device)
        self.model.load_state_dict(state["model_state"])


def _smoke_test() -> int:
    """smoke 테스트: 1100x21 random 데이터 1 epoch 학습 + uncertainty 출력."""
    if not TORCH_AVAILABLE:
        print("[bayesian_nn_model] requires torch, install with: pip install torch")
        return 0

    print("[bayesian_nn_model] smoke start")
    rng = np.random.default_rng(config.RANDOM_SEED)
    N, D = 1100, 21
    X = rng.standard_normal((N, D)).astype(np.float32)
    y = (rng.standard_normal((N, 45)) > 0.7).astype(np.float32)

    split = 1000
    X_tr, X_val = X[:split], X[split:]
    y_tr, y_val = y[:split], y[split:]

    bnn = LottoBayesianNN(
        input_dim=D,
        hidden_dim=32,
        num_layers=2,
        dropout=0.2,
        num_classes=45,
        mc_samples=20,
        task_type="binary_45",
    )
    info = bnn.train(X_tr, y_tr, X_val=X_val, y_val=y_val, max_epochs=1, batch_size=128)
    print(
        f"[bayesian_nn_model] train info: epochs={info['epochs']} "
        f"train_loss={info['final_train_loss']:.4f} "
        f"val_loss={info['final_val_loss']:.4f}"
    )

    # uncertainty
    unc = bnn.predict_with_uncertainty(X_val[:5])
    print(f"[bayesian_nn_model] mean shape: {unc['mean'].shape}")
    print(f"[bayesian_nn_model] std shape: {unc['std'].shape}")
    print(
        f"[bayesian_nn_model] std[0,:3]: {unc['std'][0, :3].round(4).tolist()} "
        f"q10[0,:3]: {unc['q10'][0, :3].round(4).tolist()} "
        f"q90[0,:3]: {unc['q90'][0, :3].round(4).tolist()}"
    )

    # save/load round-trip
    tmp_path = os.path.join(config.MODEL_DIR, "_smoke_bayesian.pt")
    bnn.save(tmp_path)

    bnn2 = LottoBayesianNN(
        input_dim=D,
        hidden_dim=32,
        num_layers=2,
        dropout=0.2,
        num_classes=45,
        mc_samples=20,
        task_type="binary_45",
    )
    bnn2.load(tmp_path)
    unc2 = bnn2.predict_with_uncertainty(X_val[:5])
    print(f"[bayesian_nn_model] reloaded mean shape: {unc2['mean'].shape}")

    try:
        os.remove(tmp_path)
    except OSError:
        pass

    print("[bayesian_nn_model] smoke OK")
    return 0


if __name__ == "__main__":
    import sys

    if "--smoke" in sys.argv:
        sys.exit(_smoke_test())
    print("[bayesian_nn_model] use --smoke to run smoke test")
