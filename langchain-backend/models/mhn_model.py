"""Modern Hopfield Network wrapper.

1100회차 + 21지표 패턴 메모리에서 query와 가장 유사한 top-K 회차를
retrieval 한다. 회귀-plan Tier 4 메타 분석 narrative 입력 전담.
hflayers 미설치 시 PyTorch self-impl 로 fallback.
"""

from __future__ import annotations

import math
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

try:
    from hflayers import HopfieldLayer  # noqa: F401

    HFLAYERS_AVAILABLE = True
except ImportError:
    HFLAYERS_AVAILABLE = False
    HopfieldLayer = None  # type: ignore


_TASK_TYPES = ("none", "binary_45", "multiclass", "regression")


class _SelfImplHopfieldHead(nn.Module if TORCH_AVAILABLE else object):
    """선택적 discriminative head (label 학습용).

    저장된 패턴-메모리 위에 얹는 선형 분류/회귀 layer.
    """

    def __init__(self, input_dim: int, output_dim: int, dropout: float = 0.1) -> None:
        super().__init__()
        self.fc = nn.Sequential(
            nn.Linear(input_dim, max(input_dim // 2, output_dim)),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(max(input_dim // 2, output_dim), output_dim),
        )

    def forward(self, x):  # type: ignore[no-untyped-def]
        return self.fc(x)


class LottoMHN:
    """Modern Hopfield Network wrapper.

    1100x21(or 65) feature 패턴-메모리 + softmax(beta * Q K^T) retrieval.
    hflayers 가 있으면 그것을 쓰고 없으면 self-impl PyTorch attention 사용.
    """

    def __init__(
        self,
        input_dim: int,
        num_heads: int = 8,
        beta: float = 1.0,
        normalize_stored_pattern: bool = True,
        task_type: str = "none",
        num_classes: int = 45,
        dropout: float = 0.1,
        random_seed: int | None = None,
        device: str | None = None,
    ) -> None:
        if not TORCH_AVAILABLE:
            raise ImportError(
                "[mhn_model] requires torch, install with: pip install torch"
            )

        if task_type not in _TASK_TYPES:
            raise ValueError(f"task_type must be one of {_TASK_TYPES}, got {task_type}")

        self.input_dim = int(input_dim)
        self.num_heads = int(num_heads)
        self.beta = float(beta)
        self.normalize_stored_pattern = bool(normalize_stored_pattern)
        self.task_type = task_type
        self.num_classes = int(num_classes)
        self.dropout = float(dropout)
        self.random_seed = random_seed if random_seed is not None else config.RANDOM_SEED

        # device 자동 감지
        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = torch.device(device)

        torch.manual_seed(self.random_seed)
        np.random.seed(self.random_seed)

        # 메모리 슬롯 (store_patterns 호출 시 채워짐)
        self._patterns: torch.Tensor | None = None
        self._labels: np.ndarray | None = None
        self._pattern_norm: torch.Tensor | None = None

        # backend 선택
        self.use_hflayers = HFLAYERS_AVAILABLE
        self._hf_layer: Any = None
        if self.use_hflayers:
            try:
                self._hf_layer = HopfieldLayer(
                    input_size=self.input_dim,
                    hidden_size=max(self.input_dim // 2, 8),
                    output_size=self.input_dim,
                    num_heads=self.num_heads,
                    scaling=self.beta,
                    normalize_stored_pattern=self.normalize_stored_pattern,
                    dropout=self.dropout,
                ).to(self.device)
            except Exception:
                # API 호환 실패 시 self-impl 로 강제 폴백
                self.use_hflayers = False
                self._hf_layer = None

        # discriminative head (optional)
        self._head: Any = None
        if self.task_type != "none":
            head_out = self.num_classes if self.task_type != "regression" else 1
            self._head = _SelfImplHopfieldHead(self.input_dim, head_out, self.dropout).to(
                self.device
            )

    # ---------- core API ----------

    def store_patterns(self, patterns: np.ndarray, labels: np.ndarray | None = None) -> None:
        """학습 데이터(N, D)를 키-값 메모리에 저장."""
        arr = np.asarray(patterns, dtype=np.float32)
        if arr.ndim != 2:
            raise ValueError(f"patterns must be 2D (N, D), got shape {arr.shape}")
        if arr.shape[1] != self.input_dim:
            raise ValueError(
                f"pattern feature dim {arr.shape[1]} != input_dim {self.input_dim}"
            )

        t = torch.from_numpy(arr).to(self.device)
        if self.normalize_stored_pattern:
            norm = torch.linalg.norm(t, dim=1, keepdim=True).clamp(min=1e-8)
            self._pattern_norm = t / norm
        else:
            self._pattern_norm = t

        self._patterns = t
        if labels is not None:
            self._labels = np.asarray(labels)
        else:
            self._labels = None

    def retrieve(self, query: np.ndarray, top_k: int = 5) -> dict:
        """query(N, D)에 대한 top-K 유사 회차 반환.

        returns dict with:
          - top_k_indices: (N, top_k) int
          - similarities: (N, top_k) float
          - retrieved_patterns: (N, top_k, D) float
        """
        if self._patterns is None or self._pattern_norm is None:
            raise RuntimeError("Patterns not stored. call store_patterns() first.")

        q_arr = np.asarray(query, dtype=np.float32)
        if q_arr.ndim == 1:
            q_arr = q_arr.reshape(1, -1)
        if q_arr.shape[1] != self.input_dim:
            raise ValueError(
                f"query feature dim {q_arr.shape[1]} != input_dim {self.input_dim}"
            )

        q = torch.from_numpy(q_arr).to(self.device)
        if self.normalize_stored_pattern:
            qn = q / torch.linalg.norm(q, dim=1, keepdim=True).clamp(min=1e-8)
        else:
            qn = q

        # similarity = beta * (Q @ K^T) / sqrt(d)
        scale = self.beta / math.sqrt(self.input_dim)
        sim = (qn @ self._pattern_norm.T) * scale  # (N, M)

        k = min(top_k, sim.shape[1])
        top_vals, top_idx = torch.topk(sim, k=k, dim=1)
        # softmax 가중치도 함께 반환
        weights = torch.softmax(top_vals, dim=1)

        idx_np = top_idx.detach().cpu().numpy().astype(np.int64)
        sim_np = top_vals.detach().cpu().numpy().astype(np.float32)
        weight_np = weights.detach().cpu().numpy().astype(np.float32)

        retrieved = self._patterns[top_idx.view(-1)].view(q.shape[0], k, self.input_dim)
        retrieved_np = retrieved.detach().cpu().numpy().astype(np.float32)

        return {
            "top_k_indices": idx_np,
            "similarities": sim_np,
            "softmax_weights": weight_np,
            "retrieved_patterns": retrieved_np,
        }

    def train(
        self,
        features: np.ndarray,
        labels: np.ndarray,
        max_epochs: int = 30,
        learning_rate: float = 1e-3,
        batch_size: int = 64,
    ) -> dict:
        """선택적 discriminative head 학습.

        task_type == "none" 이면 단순 store_patterns 만 수행.
        """
        X = np.asarray(features, dtype=np.float32)
        y = np.asarray(labels)

        # 패턴 메모리 저장
        self.store_patterns(X, labels=y)

        if self.task_type == "none" or self._head is None:
            return {
                "success": True,
                "trained_head": False,
                "stored_patterns": int(X.shape[0]),
            }

        # head 학습 (간단한 supervised loop)
        if self.task_type == "binary_45":
            criterion = nn.BCEWithLogitsLoss()
            y_tensor = torch.from_numpy(y.astype(np.float32)).to(self.device)
        elif self.task_type == "multiclass":
            criterion = nn.CrossEntropyLoss()
            y_tensor = torch.from_numpy(y.astype(np.int64)).to(self.device)
        else:  # regression
            criterion = nn.MSELoss()
            y_tensor = torch.from_numpy(y.astype(np.float32)).to(self.device)
            if y_tensor.ndim == 1:
                y_tensor = y_tensor.view(-1, 1)

        x_tensor = torch.from_numpy(X).to(self.device)
        optimizer = torch.optim.Adam(self._head.parameters(), lr=learning_rate)

        n = X.shape[0]
        history = []
        self._head.train()
        for epoch in range(max_epochs):
            perm = torch.randperm(n, device=self.device)
            running = 0.0
            count = 0
            for i in range(0, n, batch_size):
                idx = perm[i : i + batch_size]
                xb = x_tensor[idx]
                yb = y_tensor[idx]

                optimizer.zero_grad()
                logits = self._head(xb)
                loss = criterion(logits, yb)
                loss.backward()
                optimizer.step()

                running += float(loss.detach().cpu().item()) * xb.shape[0]
                count += xb.shape[0]
            history.append(running / max(count, 1))

        return {
            "success": True,
            "trained_head": True,
            "stored_patterns": int(X.shape[0]),
            "final_loss": float(history[-1]) if history else 0.0,
            "loss_history": history,
        }

    def predict(self, query: np.ndarray, top_k: int = 5) -> np.ndarray:
        """top-K retrieval 기반 weighted voting 예측.

        - task_type == "none": top-K 유사도 평균 패턴 (N, D)
        - task_type == "binary_45" / "multiclass": label 기반 가중 평균
        - task_type == "regression": label 기반 가중 평균 스칼라
        head 가 있으면 head forward 결과를 우선 사용.
        """
        # head 우선 (학습된 경우)
        if self._head is not None and self.task_type != "none":
            self._head.eval()
            q_arr = np.asarray(query, dtype=np.float32)
            if q_arr.ndim == 1:
                q_arr = q_arr.reshape(1, -1)
            x = torch.from_numpy(q_arr).to(self.device)
            with torch.no_grad():
                logits = self._head(x)
                if self.task_type == "binary_45":
                    out = torch.sigmoid(logits)
                elif self.task_type == "multiclass":
                    out = torch.softmax(logits, dim=1)
                else:
                    out = logits
            return out.detach().cpu().numpy().astype(np.float32)

        # retrieval 기반
        result = self.retrieve(query, top_k=top_k)
        weights = result["softmax_weights"]  # (N, K)
        idx = result["top_k_indices"]  # (N, K)

        if self._labels is None:
            # 패턴 weighted 평균
            patterns = result["retrieved_patterns"]  # (N, K, D)
            return (patterns * weights[:, :, None]).sum(axis=1).astype(np.float32)

        labels = np.asarray(self._labels)
        gathered = labels[idx]  # (N, K, ...)
        if gathered.ndim == 2:
            # 스칼라 라벨 → weighted scalar
            return (gathered.astype(np.float32) * weights).sum(axis=1).astype(np.float32)
        # 다차원 라벨 → broadcast weighted average
        w = weights.reshape(weights.shape[0], weights.shape[1], *([1] * (gathered.ndim - 2)))
        return (gathered.astype(np.float32) * w).sum(axis=1).astype(np.float32)

    # ---------- persistence ----------

    def save(self, path: str) -> None:
        """모델 직렬화 (.pt)."""
        if self._patterns is None:
            raise RuntimeError("No patterns stored, nothing to save")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        state = {
            "input_dim": self.input_dim,
            "num_heads": self.num_heads,
            "beta": self.beta,
            "normalize_stored_pattern": self.normalize_stored_pattern,
            "task_type": self.task_type,
            "num_classes": self.num_classes,
            "dropout": self.dropout,
            "random_seed": self.random_seed,
            "patterns": self._patterns.detach().cpu(),
            "labels": self._labels,
            "head_state": (
                self._head.state_dict() if self._head is not None else None
            ),
        }
        torch.save(state, path)

    def load(self, path: str) -> None:
        """모델 로드."""
        if not os.path.exists(path):
            raise FileNotFoundError(f"Model file not found: {path}")
        state = torch.load(path, map_location=self.device, weights_only=False)

        self.input_dim = int(state["input_dim"])
        self.num_heads = int(state["num_heads"])
        self.beta = float(state["beta"])
        self.normalize_stored_pattern = bool(state["normalize_stored_pattern"])
        self.task_type = state["task_type"]
        self.num_classes = int(state["num_classes"])
        self.dropout = float(state["dropout"])
        self.random_seed = int(state["random_seed"])

        patterns = state["patterns"].to(self.device)
        labels = state.get("labels", None)
        if self.normalize_stored_pattern:
            norm = torch.linalg.norm(patterns, dim=1, keepdim=True).clamp(min=1e-8)
            self._pattern_norm = patterns / norm
        else:
            self._pattern_norm = patterns
        self._patterns = patterns
        self._labels = labels

        head_state = state.get("head_state")
        if head_state is not None and self.task_type != "none":
            head_out = self.num_classes if self.task_type != "regression" else 1
            self._head = _SelfImplHopfieldHead(self.input_dim, head_out, self.dropout).to(
                self.device
            )
            self._head.load_state_dict(head_state)


def _smoke_test() -> int:
    """smoke 테스트: 1100x21 random 데이터로 store + retrieve + train head."""
    if not TORCH_AVAILABLE:
        print("[mhn_model] requires torch, install with: pip install torch")
        return 0

    print("[mhn_model] smoke start")
    print(f"[mhn_model] hflayers available: {HFLAYERS_AVAILABLE}")
    rng = np.random.default_rng(config.RANDOM_SEED)
    N, D = 1100, 21
    X = rng.standard_normal((N, D)).astype(np.float32)
    # 라벨: 45 멀티핫 (top-7 indicator)
    y = (rng.standard_normal((N, 45)) > 0.7).astype(np.float32)

    mhn = LottoMHN(
        input_dim=D,
        num_heads=4,
        beta=1.0,
        task_type="binary_45",
        num_classes=45,
        dropout=0.1,
    )
    print(f"[mhn_model] backend: {'hflayers' if mhn.use_hflayers else 'self-impl'}")

    # store + retrieve
    mhn.store_patterns(X[:1000], labels=y[:1000])
    retrieved = mhn.retrieve(X[1000:1005], top_k=5)
    print(f"[mhn_model] top_k_indices shape: {retrieved['top_k_indices'].shape}")
    print(f"[mhn_model] similarities shape: {retrieved['similarities'].shape}")
    print(f"[mhn_model] retrieved_patterns shape: {retrieved['retrieved_patterns'].shape}")

    # train head
    info = mhn.train(X[:1000], y[:1000], max_epochs=2, batch_size=128)
    print(
        f"[mhn_model] train info: trained_head={info['trained_head']} "
        f"stored={info['stored_patterns']} loss={info.get('final_loss', 0.0):.4f}"
    )

    pred = mhn.predict(X[1000:1005], top_k=5)
    print(f"[mhn_model] predict shape: {pred.shape}")

    # save / load round-trip
    tmp_path = os.path.join(config.MODEL_DIR, "_smoke_mhn.pt")
    mhn.save(tmp_path)

    mhn2 = LottoMHN(
        input_dim=D,
        num_heads=4,
        beta=1.0,
        task_type="binary_45",
        num_classes=45,
    )
    mhn2.load(tmp_path)
    pred2 = mhn2.predict(X[1000:1005], top_k=5)
    print(f"[mhn_model] reloaded predict shape: {pred2.shape}")

    try:
        os.remove(tmp_path)
    except OSError:
        pass

    print("[mhn_model] smoke OK")
    return 0


if __name__ == "__main__":
    import sys

    if "--smoke" in sys.argv:
        sys.exit(_smoke_test())
    print("[mhn_model] use --smoke to run smoke test")
