"""LottoPaperPredictor — 로또용지 14 카테고리 (5 행 + 9 열) 그리드 분류기.

Stage 1 / Phase 1.

그리드 정의: 1~45 -> row=(n-1)//9, col=(n-1)%9 (5x9 그리드)
  - 가로 5 행: row 0 (1~9), row 1 (10~18), ..., row 4 (37~45)
  - 세로 9 열: col 0 (1,10,19,28,37), col 1 (2,11,20,29,38), ...

총 14 카테고리 (정적 풀):
  row_0(9), row_1(9), row_2(9), row_3(9), row_4(9)
  col_0(5), col_1(5), col_2(5), col_3(5), col_4(5),
  col_5(5), col_6(5), col_7(5), col_8(5)

CNN 그리드 입력은 (batch, seq, 5, 9) 시퀀스 매트릭스. 본 predictor 는 ICP 베이스를
사용하되 CNN-grid 보조 헤드를 추가하여 공간 구조를 활용한다.
"""

from __future__ import annotations

import os
import pickle
from typing import Optional

import numpy as np

import config
from predictors.independent_count_predictor import IndependentCountPredictor


GRID_ROWS = 5
GRID_COLS = 9

ROW_LABELS = tuple(f"row_{r}" for r in range(GRID_ROWS))
COL_LABELS = tuple(f"col_{c}" for c in range(GRID_COLS))
ALL_LABELS = ROW_LABELS + COL_LABELS  # 14
N_CATEGORIES = len(ALL_LABELS)


def _row_of(n: int) -> int:
    return (n - 1) // GRID_COLS


def _col_of(n: int) -> int:
    return (n - 1) % GRID_COLS


def _row_pool(r: int) -> list[int]:
    return [n for n in range(1, 46) if _row_of(n) == r]


def _col_pool(c: int) -> list[int]:
    return [n for n in range(1, 46) if _col_of(n) == c]


def _draw_numbers(d: dict) -> list[int]:
    nums = d.get("numbers")
    if nums is None:
        nums = d.get("nums") or []
    return [int(n) for n in nums if 1 <= int(n) <= 45]


def _augment_class_coverage(
    X: np.ndarray, Y: np.ndarray, n_classes: int = 7
) -> tuple[np.ndarray, np.ndarray]:
    """ICP/XGBoost 학습 안전망 — 누락 클래스 더미 샘플 보충."""
    if X.shape[0] == 0:
        return X, Y
    n_cat = Y.shape[1]
    avg_row = X.mean(axis=0, keepdims=True)
    extra_X: list[np.ndarray] = []
    extra_Y: list[np.ndarray] = []
    for ci in range(n_cat):
        present = set(np.unique(Y[:, ci]).tolist())
        missing = [c for c in range(n_classes) if c not in present]
        for cls in missing:
            extra_X.append(avg_row.copy())
            row = Y[0:1].copy()
            row[0, ci] = cls
            extra_Y.append(row)
    if not extra_X:
        return X, Y
    X_aug = np.concatenate([X] + extra_X, axis=0)
    Y_aug = np.concatenate([Y] + extra_Y, axis=0)
    return X_aug, Y_aug


# ──────────────── CNN 보조 헤드 (5x9) ────────────────


def _try_import_torch():
    try:
        import torch
        import torch.nn as nn
        return torch, nn
    except ImportError:
        return None, None


class _CNN59Head:
    """5x9 그리드 시퀀스 -> 14 카테고리 카운트 회귀 보조 헤드.

    seq -> Conv2d -> GlobalPool -> per-category (n_classes) softmax.
    """

    def __init__(self, seq_len: int = 30, n_classes: int = 7, n_categories: int = N_CATEGORIES):
        self.seq_len = seq_len
        self.n_classes = n_classes
        self.n_categories = n_categories
        self.model = None
        self.device = None

    def _build(self):
        torch, nn = _try_import_torch()
        if torch is None:
            return None

        seq = self.seq_len
        nc = self.n_classes
        ncat = self.n_categories

        class Net(nn.Module):
            def __init__(self):
                super().__init__()
                self.conv1 = nn.Sequential(
                    nn.Conv2d(seq, 32, kernel_size=3, padding=1),
                    nn.BatchNorm2d(32),
                    nn.ReLU(),
                )
                self.conv2 = nn.Sequential(
                    nn.Conv2d(32, 64, kernel_size=3, padding=1),
                    nn.BatchNorm2d(64),
                    nn.ReLU(),
                )
                self.gap = nn.AdaptiveAvgPool2d(1)
                self.heads = nn.ModuleList([nn.Linear(64, nc) for _ in range(ncat)])

            def forward(self, x):
                h = self.conv1(x)
                h = self.conv2(h)
                h = self.gap(h).view(x.size(0), -1)
                logits = [head(h) for head in self.heads]
                return logits  # list of (B, n_classes)

        return Net()

    def fit(self, X_seq: np.ndarray, Y: np.ndarray, epochs: int = 5, lr: float = 1e-3) -> bool:
        """X_seq: (N, seq, 5, 9), Y: (N, 14) integer 0~6."""
        torch, nn = _try_import_torch()
        if torch is None:
            return False
        if X_seq.shape[0] == 0:
            return False

        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = self._build()
        if self.model is None:
            return False
        self.model = self.model.to(self.device)

        x = torch.from_numpy(X_seq.astype(np.float32)).to(self.device)
        y = torch.from_numpy(Y.astype(np.int64)).to(self.device)

        opt = torch.optim.Adam(self.model.parameters(), lr=lr)
        ce = nn.CrossEntropyLoss()
        self.model.train()
        for _ in range(epochs):
            opt.zero_grad()
            logits_list = self.model(x)
            loss = sum(ce(logits, y[:, ci]) for ci, logits in enumerate(logits_list))
            loss.backward()
            opt.step()
        return True

    def predict_proba(self, x_seq: np.ndarray) -> Optional[np.ndarray]:
        """x_seq: (1, seq, 5, 9) -> (n_categories, n_classes)."""
        torch, nn = _try_import_torch()
        if torch is None or self.model is None:
            return None
        self.model.eval()
        with torch.no_grad():
            x = torch.from_numpy(x_seq.astype(np.float32)).to(self.device)
            logits_list = self.model(x)
            probs = []
            for logits in logits_list:
                p = torch.softmax(logits, dim=-1).cpu().numpy()[0]
                probs.append(p)
        return np.stack(probs, axis=0)

    def state_dict(self):
        if self.model is None:
            return None
        return self.model.state_dict()

    def load_state_dict(self, sd):
        if sd is None:
            return
        if self.model is None:
            self.model = self._build()
            torch, _ = _try_import_torch()
            if torch is None or self.model is None:
                return
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            self.model = self.model.to(self.device)
        self.model.load_state_dict(sd)


# ──────────────── LottoPaperPredictor ────────────────


class LottoPaperPredictor:
    """로또용지 5 행 + 9 열 = 14 카테고리. CNN 메인 + ICP base 통합."""

    def __init__(
        self,
        feature_dim: int = 24,
        active_models: tuple[str, ...] = (
            "xgboost", "catboost", "tabnet", "cnn", "gnn", "tft",
        ),
        seq_len: int = 30,
    ):
        self.feature_dim = feature_dim
        self.active_models = active_models
        self.seq_len = seq_len
        self.category_labels = list(ALL_LABELS)

        # 풀 크기는 정적이지만 ICP 표준 인터페이스 유지를 위해 명시.
        pool_sizes = [len(_row_pool(r)) for r in range(GRID_ROWS)] + [len(_col_pool(c)) for c in range(GRID_COLS)]

        # ICP 에는 cnn / gnn 이 없다. cnn 은 본 predictor 의 _CNN59Head 로 대체.
        icp_models = tuple(m for m in active_models if m not in ("cnn", "gnn"))
        if not icp_models:
            icp_models = ("xgboost", "markov")

        self.icp = IndependentCountPredictor(
            indicator_name="lotto_paper_14",
            n_categories=N_CATEGORIES,
            category_labels=list(self.category_labels),
            n_classes=7,
            feature_dim=feature_dim,
            active_models=icp_models,
            category_pool_sizes=pool_sizes,
        )

        self._cnn_head: Optional[_CNN59Head] = None
        if "cnn" in active_models:
            self._cnn_head = _CNN59Head(seq_len=seq_len, n_classes=7, n_categories=N_CATEGORIES)

        self._is_trained = False

    # ────── grid sequence ──────

    def build_grid_sequence(self, draws_so_far: list[dict], seq_len: int = 30) -> np.ndarray:
        """shape (seq_len, 5, 9) 1/0 매트릭스. 최신 회차 = 마지막 인덱스."""
        seq = np.zeros((seq_len, GRID_ROWS, GRID_COLS), dtype=np.float32)
        # draws_so_far 는 최신순. 마지막 인덱스 = 가장 최근 -> reversed
        sub = list(reversed(draws_so_far[:seq_len]))
        # 만약 부족하면 앞쪽이 0 padding
        offset = seq_len - len(sub)
        for t, d in enumerate(sub):
            for n in _draw_numbers(d):
                r, c = _row_of(n), _col_of(n)
                seq[offset + t, r, c] = 1.0
        return seq

    # ────── feature ──────

    def build_features(self, draws_so_far: list[dict]) -> np.ndarray:
        """단일 feature 행 (D,).

        구성 (24):
          - 5 행 최근 1 회차 출현 카운트
          - 9 열 최근 1 회차 출현 카운트
          - 5 행 최근 10 회차 평균 출현 카운트
          - 9 열 최근 10 회차 평균 출현 카운트
          (위 합 28 -> feature_dim 24 로 자르거나 패딩)
        """
        if not draws_so_far:
            return np.zeros(self.feature_dim, dtype=np.float32)

        feat: list[float] = []
        recent = draws_so_far[0]
        nums = _draw_numbers(recent)
        row_cnt = [0] * GRID_ROWS
        col_cnt = [0] * GRID_COLS
        for n in nums:
            row_cnt[_row_of(n)] += 1
            col_cnt[_col_of(n)] += 1
        feat.extend(float(x) for x in row_cnt)
        feat.extend(float(x) for x in col_cnt)

        window = draws_so_far[: min(10, len(draws_so_far))]
        row_sum = [0] * GRID_ROWS
        col_sum = [0] * GRID_COLS
        for d in window:
            for n in _draw_numbers(d):
                row_sum[_row_of(n)] += 1
                col_sum[_col_of(n)] += 1
        denom = max(1, len(window))
        feat.extend(float(x) / denom for x in row_sum)
        feat.extend(float(x) / denom for x in col_sum)

        arr = np.array(feat, dtype=np.float32)
        if arr.size < self.feature_dim:
            arr = np.pad(arr, (0, self.feature_dim - arr.size))
        elif arr.size > self.feature_dim:
            arr = arr[: self.feature_dim]
        return arr

    # ────── training set ──────

    def _build_training_set(self, draws: list[dict]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """X (N, D), X_seq (N, seq, 5, 9), Y (N, 14)."""
        N = len(draws)
        if N < self.seq_len + 2:
            return (
                np.zeros((0, self.feature_dim), dtype=np.float32),
                np.zeros((0, self.seq_len, GRID_ROWS, GRID_COLS), dtype=np.float32),
                np.zeros((0, N_CATEGORIES), dtype=np.int64),
            )

        X_rows: list[np.ndarray] = []
        X_seq_rows: list[np.ndarray] = []
        Y_rows: list[list[int]] = []

        for t in range(N - 1, 0, -1):
            history = draws[t:]
            if len(history) < 1:
                continue
            x = self.build_features(history)
            x_seq = self.build_grid_sequence(history, seq_len=self.seq_len)

            target_nums = set(_draw_numbers(draws[t - 1]))
            counts: list[int] = []
            for r in range(GRID_ROWS):
                pool = set(_row_pool(r))
                cnt = len(pool & target_nums)
                counts.append(min(cnt, 6))
            for c in range(GRID_COLS):
                pool = set(_col_pool(c))
                cnt = len(pool & target_nums)
                counts.append(min(cnt, 6))

            X_rows.append(x)
            X_seq_rows.append(x_seq)
            Y_rows.append(counts)

        X = np.stack(X_rows, axis=0).astype(np.float32) if X_rows else np.zeros((0, self.feature_dim), dtype=np.float32)
        X_seq = np.stack(X_seq_rows, axis=0).astype(np.float32) if X_seq_rows else np.zeros((0, self.seq_len, GRID_ROWS, GRID_COLS), dtype=np.float32)
        Y = np.array(Y_rows, dtype=np.int64) if Y_rows else np.zeros((0, N_CATEGORIES), dtype=np.int64)
        return X, X_seq, Y

    # ────── 학습 ──────

    def train(self, draws: list[dict]) -> dict:
        """draws (최신순) 로 ICP + CNN 학습."""
        X, X_seq, Y = self._build_training_set(draws)
        if X.shape[0] < 5:
            print("[LottoPaper] not enough samples for training")
            return {"success": False, "reason": "insufficient_data"}

        cut = max(1, int(X.shape[0] * 0.8))
        X_tr, Y_tr = _augment_class_coverage(X[:cut], Y[:cut], n_classes=7)
        X_val, Y_val = X[cut:], Y[cut:]
        if X_val.shape[0] > 0:
            X_val, Y_val = _augment_class_coverage(X_val, Y_val, n_classes=7)
        history = self.icp.train(X_tr, Y_tr, X_val=X_val if X_val.shape[0] > 0 else None,
                                 Y_val=Y_val if X_val.shape[0] > 0 else None)

        cnn_ok = False
        if self._cnn_head is not None:
            try:
                cnn_ok = self._cnn_head.fit(X_seq[:cut], Y[:cut], epochs=5)
            except Exception as e:
                print(f"[LottoPaper] CNN head train fail: {e}")
                cnn_ok = False

        self._is_trained = True
        return {
            "success": True,
            "samples": int(X.shape[0]),
            "icp_history": history,
            "cnn_trained": cnn_ok,
        }

    # ────── 추론 ──────

    def predict(self, draws_so_far: list[dict]) -> dict:
        """14 카테고리 분포 (per-row + per-col)."""
        if not draws_so_far:
            return {"per_row": {}, "per_col": {}, "narrative": "no draws"}

        x = self.build_features(draws_so_far)
        X = np.expand_dims(x, axis=0)
        out = self.icp.predict(X)

        # CNN 보조 헤드 — 가중평균 대상에 추가
        cnn_probs = None
        if self._cnn_head is not None:
            try:
                x_seq = self.build_grid_sequence(draws_so_far, seq_len=self.seq_len)
                cnn_probs = self._cnn_head.predict_proba(x_seq[None, ...])
            except Exception:
                cnn_probs = None

        per_row: dict = {}
        per_col: dict = {}

        for ci, label in enumerate(self.category_labels):
            payload = dict(out.per_category.get(label, {}))
            base_dist = np.array(payload.get("absolute_dist") or [1.0 / 7] * 7, dtype=np.float32)

            # CNN 보조 결합 (단순 평균)
            if cnn_probs is not None and cnn_probs.shape[0] == N_CATEGORIES:
                merged = (base_dist + cnn_probs[ci]) / 2.0
                merged = merged / max(merged.sum(), 1e-9)
                payload["absolute_dist"] = merged.tolist()
                payload["expected_count"] = float(np.sum(merged * np.arange(7)))
                payload["top_class"] = int(np.argmax(merged))
                payload["top_class_prob"] = float(merged[int(np.argmax(merged))])
                payload["model_contributions"] = dict(payload.get("model_contributions", {}))
                payload["model_contributions"]["cnn"] = 1.0

            if label in ROW_LABELS:
                pool = _row_pool(int(label.split("_")[1]))
            else:
                pool = _col_pool(int(label.split("_")[1]))
            payload["members"] = pool
            M = len(pool)
            payload["current_pool_size"] = M
            top_class = payload.get("top_class", 0)
            top_prob = payload.get("top_class_prob", 0.0)
            payload["narrative"] = (
                f"{label} pool {M} expected {top_class} out of {M} "
                f"(P={top_prob * 100:.1f}%)"
            )

            if label in ROW_LABELS:
                per_row[label] = payload
            else:
                per_col[label] = payload

        return {
            "indicator": "lotto_paper_14",
            "per_row": per_row,
            "per_col": per_col,
        }

    # ────── persistence ──────

    def save(self, path: str) -> str:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        icp_path = path + ".icp.pkl"
        self.icp.save(icp_path)

        cnn_state = self._cnn_head.state_dict() if self._cnn_head is not None else None
        meta = {
            "feature_dim": self.feature_dim,
            "active_models": list(self.active_models),
            "seq_len": self.seq_len,
            "is_trained": self._is_trained,
            "icp_path": icp_path,
            "has_cnn": cnn_state is not None,
        }
        with open(path, "wb") as f:
            pickle.dump(meta, f)

        if cnn_state is not None:
            try:
                import torch
                torch.save(cnn_state, path + ".cnn.pt")
            except Exception as e:
                print(f"[LottoPaper] cnn save skipped: {e}")
        return path

    def load(self, path: str) -> None:
        with open(path, "rb") as f:
            meta = pickle.load(f)
        self.feature_dim = meta["feature_dim"]
        self.active_models = tuple(meta["active_models"])
        self.seq_len = meta["seq_len"]
        self._is_trained = meta["is_trained"]
        self.icp.load(meta["icp_path"])

        if meta.get("has_cnn") and "cnn" in self.active_models:
            try:
                import torch
                sd = torch.load(path + ".cnn.pt", map_location="cpu")
                if self._cnn_head is None:
                    self._cnn_head = _CNN59Head(seq_len=self.seq_len)
                self._cnn_head.load_state_dict(sd)
            except Exception as e:
                print(f"[LottoPaper] cnn load skipped: {e}")


# ────────────────── CLI smoke ──────────────────


def _make_fake_draws(n: int = 100, seed: int = 42) -> list[dict]:
    rng = np.random.default_rng(seed)
    draws = []
    for i in range(n):
        nums = sorted(rng.choice(np.arange(1, 46), size=6, replace=False).tolist())
        draws.append({"round": n - i, "numbers": nums})
    return draws


def main():
    """python -m predictors.lotto_paper_predictor --smoke."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()

    if not args.smoke:
        return

    draws = _make_fake_draws(100, seed=config.RANDOM_SEED)
    pred = LottoPaperPredictor(
        feature_dim=24,
        active_models=("xgboost", "markov"),  # smoke: CNN/GNN 제외
        seq_len=30,
    )

    print("[LottoPaper] training (smoke)...")
    res = pred.train(draws)
    print(f"  result: success={res.get('success')} samples={res.get('samples')} cnn={res.get('cnn_trained')}")

    print("\n[LottoPaper] predict (smoke)...")
    out = pred.predict(draws[:50])
    print(f"  per_row: {len(out['per_row'])} rows")
    print(f"  per_col: {len(out['per_col'])} cols")
    for label in ("row_0", "row_4"):
        payload = out["per_row"].get(label, {})
        print(f"  {label}: M={payload.get('current_pool_size')} top={payload.get('top_class')} P={payload.get('top_class_prob', 0):.3f}")
        print(f"    narrative: {payload.get('narrative')}")
    for label in ("col_0", "col_8"):
        payload = out["per_col"].get(label, {})
        print(f"  {label}: M={payload.get('current_pool_size')} top={payload.get('top_class')} P={payload.get('top_class_prob', 0):.3f}")
        print(f"    narrative: {payload.get('narrative')}")


if __name__ == "__main__":
    main()
