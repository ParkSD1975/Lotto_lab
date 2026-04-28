"""EndingsPredictor (Phase 2) — 끝수합 스칼라 회귀 + 끝수 0~9 분포 10D head.

두 head 산술 동치: endings_sum = Sigma(k * digit_count_k).
Phase 1 출력 (digit_distribution 10D)을 cross-feedback 입력으로 활용.
"""

from __future__ import annotations

import os
import pickle
from typing import Any

import numpy as np

import config
from features.scalar_features import (
    DEFAULT_CFG as SCALAR_CFG,
    build_scalar_features,
    build_scalar_feature_matrix,
)
from features.gnn_aggregation import (
    aggregate_endings_distribution,
    aggregate_endings_sum,
)


# ────────────────── 가용성 플래그 ──────────────────


try:
    import xgboost as xgb
    XGB_AVAILABLE = True
except ImportError:
    XGB_AVAILABLE = False
    xgb = None  # type: ignore

try:
    import torch
    import torch.nn as nn
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    torch = None  # type: ignore
    nn = None  # type: ignore

try:
    from models.tft_model import LottoTFT, PYTORCH_FORECASTING_AVAILABLE as TFT_AVAIL
except ImportError:
    TFT_AVAIL = False
    LottoTFT = None  # type: ignore

try:
    from models.nbeats_model import LottoNBeats, PYTORCH_FORECASTING_AVAILABLE as NBEATS_AVAIL
except ImportError:
    NBEATS_AVAIL = False
    LottoNBeats = None  # type: ignore

try:
    from models.bayesian_nn_model import LottoBayesianNN
    BAYES_AVAIL = TORCH_AVAILABLE
except ImportError:
    BAYES_AVAIL = False
    LottoBayesianNN = None  # type: ignore


# ────────────────── Markov 6-bucket (끝수합 범위) ──────────────────


class _EndingsMarkov6:
    """끝수합 6-bucket 전이행렬. 끝수합은 0~54 (단순 균등 6분할)."""

    BUCKETS = [(0, 9), (10, 18), (19, 27), (28, 36), (37, 45), (46, 60)]

    def __init__(self) -> None:
        n = len(self.BUCKETS)
        self.transition = np.full((n, n), 1.0 / n)

    def _bucket(self, value: float) -> int:
        for k, (lo, hi) in enumerate(self.BUCKETS):
            if lo <= value <= hi:
                return k
        return len(self.BUCKETS) - 1

    def fit(self, series: np.ndarray) -> None:
        n = len(self.BUCKETS)
        T = np.zeros((n, n))
        for i in range(len(series) - 1):
            a = self._bucket(float(series[i]))
            b = self._bucket(float(series[i + 1]))
            T[a, b] += 1.0
        T += 1.0  # Laplace
        T = T / T.sum(axis=1, keepdims=True)
        self.transition = T

    def predict_proba(self, last_value: float) -> np.ndarray:
        idx = self._bucket(float(last_value))
        return self.transition[idx].copy()

    def expected_value(self, last_value: float) -> float:
        probs = self.predict_proba(last_value)
        means = np.array([(lo + hi) / 2.0 for lo, hi in self.BUCKETS])
        return float((probs * means).sum())


# ────────────────── 1D-CNN endings distribution head ──────────────────


if TORCH_AVAILABLE:

    class _EndingsCNN(nn.Module):
        """10채널 끝수 분포 학습용 1D-CNN. input: (B, 1, T) -> 10 logits."""

        def __init__(self, seq_len: int = 30, hidden: int = 32):
            super().__init__()
            self.seq_len = seq_len
            self.conv = nn.Sequential(
                nn.Conv1d(1, hidden, kernel_size=3, padding=1),
                nn.ReLU(),
                nn.Conv1d(hidden, hidden, kernel_size=3, padding=1),
                nn.ReLU(),
                nn.AdaptiveAvgPool1d(1),
            )
            self.head = nn.Linear(hidden, 10)

        def forward(self, x):  # x: (B, 1, T)
            h = self.conv(x).squeeze(-1)
            return self.head(h)
else:

    class _EndingsCNN:  # type: ignore
        """torch 미설치 시 plain stub."""

        def __init__(self, *_a, **_k) -> None:
            raise ImportError("torch required for _EndingsCNN")


# ────────────────── EndingsPredictor 본체 ──────────────────


class EndingsPredictor:
    """Phase 2 predictor. 끝수합 quantile + 끝수 분포 10D 통합."""

    DEFAULT_MODELS = ("xgboost", "tft", "nbeats", "markov6", "bayesian", "cnn", "gnn")

    def __init__(
        self,
        feature_dim: int = 24,
        active_models: tuple[str, ...] | None = None,
        cnn_seq_len: int = 30,
    ) -> None:
        self.feature_dim = int(feature_dim)
        self.active_models = active_models or self.DEFAULT_MODELS
        self.cnn_seq_len = int(cnn_seq_len)

        # scalar head 모델
        self.xgb_q10: Any = None
        self.xgb_q50: Any = None
        self.xgb_q90: Any = None
        self.tft_model: Any = None
        self.nbeats_model: Any = None
        self.markov6: _EndingsMarkov6 | None = None
        self.bayes_model: Any = None
        # distribution head
        self.cnn_model: Any = None
        self._cnn_device: Any = None

        self._feature_names: list[str] | None = None
        self._train_history: np.ndarray | None = None
        self._train_dist_history: np.ndarray | None = None  # (T, 10)
        self._is_trained = False

    # ────── 시계열 추출 ──────

    @staticmethod
    def _endings_sum(numbers: list[int]) -> int:
        return int(sum(int(n) % 10 for n in numbers))

    @staticmethod
    def _endings_distribution(numbers: list[int]) -> np.ndarray:
        out = np.zeros(10, dtype=np.float32)
        for n in numbers:
            out[int(n) % 10] += 1.0
        return out

    def _extract_series(self, draws: list[dict]) -> tuple[np.ndarray, np.ndarray]:
        """draws -> (sum_series (T,), dist_series (T, 10)) 시간순."""
        ordered = sorted(draws, key=lambda d: int(d.get("round", 0)))
        sums: list[int] = []
        dists: list[np.ndarray] = []
        for d in ordered:
            nums = list(d.get("numbers", []))
            sums.append(self._endings_sum(nums))
            dists.append(self._endings_distribution(nums))
        return np.array(sums, dtype=np.float64), np.stack(dists, axis=0).astype(np.float32)

    # ────── 학습 ──────

    def train(
        self,
        draws: list[dict],
        phase1_outputs: dict | None = None,
        min_history: int = 20,
        cnn_epochs: int = 30,
        bayes_epochs: int = 30,
    ) -> dict:
        """끝수합 시계열 + 끝수 분포 10D 동시 학습."""
        if not draws:
            raise ValueError("empty draws")

        sum_series, dist_series = self._extract_series(draws)
        if len(sum_series) < min_history + 5:
            raise ValueError(
                f"insufficient draws: got {len(sum_series)} need >= {min_history + 5}"
            )

        self._train_history = sum_series.copy()
        self._train_dist_history = dist_series.copy()

        # ── (1) scalar feature matrix 구성 ──
        X, names = build_scalar_feature_matrix(sum_series, min_history=min_history)
        # X[i] = features built from sum_series[:min_history+i], target = sum_series[min_history+i]
        # walk-forward: feature 사용 시점이 i 시점까지 -> 다음 회차 예측이 target
        # build_scalar_feature_matrix returns rows for i in [min_history, len], 마지막 row 는 inference 용
        # 학습 시 마지막 행 제외, target 은 한 칸 shift
        if X.shape[0] < 2:
            raise ValueError("not enough rows for training")
        X_train = X[:-1]
        y_train = sum_series[min_history:]  # length matches X_train
        self._feature_names = names
        self.feature_dim = int(X_train.shape[1])

        history: dict[str, Any] = {"trained_models": [], "n_train_rows": int(X_train.shape[0])}

        # ── (2) XGBoost Quantile 회귀 ──
        if "xgboost" in self.active_models and XGB_AVAILABLE:
            try:
                common = dict(
                    n_estimators=config.XGB_N_ESTIMATORS,
                    max_depth=config.XGB_MAX_DEPTH,
                    learning_rate=config.XGB_LEARNING_RATE,
                    random_state=config.RANDOM_SEED,
                )
                self.xgb_q10 = xgb.XGBRegressor(
                    objective="reg:quantileerror", quantile_alpha=0.10, **common
                )
                self.xgb_q50 = xgb.XGBRegressor(
                    objective="reg:quantileerror", quantile_alpha=0.50, **common
                )
                self.xgb_q90 = xgb.XGBRegressor(
                    objective="reg:quantileerror", quantile_alpha=0.90, **common
                )
                self.xgb_q10.fit(X_train, y_train)
                self.xgb_q50.fit(X_train, y_train)
                self.xgb_q90.fit(X_train, y_train)
                history["trained_models"].append("xgboost_quantile")
            except Exception as e:
                print(f"  [endings] xgboost train fail: {e}")
                self.xgb_q10 = self.xgb_q50 = self.xgb_q90 = None

        # ── (3) TFT (선택) ──
        if "tft" in self.active_models and TFT_AVAIL:
            try:
                self.tft_model = LottoTFT(
                    input_dim=self.feature_dim, output_size=3, task_type="regression"
                )
                self.tft_model.train(X_train, y_train)
                history["trained_models"].append("tft")
            except Exception as e:
                print(f"  [endings] tft train fail: {e}")
                self.tft_model = None

        # ── (4) N-BEATS (선택) ──
        if "nbeats" in self.active_models and NBEATS_AVAIL:
            try:
                self.nbeats_model = LottoNBeats(seq_length=min(30, len(sum_series) // 3))
                self.nbeats_model.train(sum_series.astype(np.float32))
                history["trained_models"].append("nbeats")
            except Exception as e:
                print(f"  [endings] nbeats train fail: {e}")
                self.nbeats_model = None

        # ── (5) Markov 6-bucket ──
        if "markov6" in self.active_models:
            self.markov6 = _EndingsMarkov6()
            self.markov6.fit(sum_series)
            history["trained_models"].append("markov6")

        # ── (6) Bayesian sigma ──
        if "bayesian" in self.active_models and BAYES_AVAIL:
            try:
                self.bayes_model = LottoBayesianNN(
                    input_dim=self.feature_dim,
                    num_classes=1,
                    task_type="regression",
                    mc_samples=20,
                )
                self.bayes_model.train(
                    X_train.astype(np.float32),
                    y_train.astype(np.float32).reshape(-1, 1),
                    max_epochs=bayes_epochs,
                )
                history["trained_models"].append("bayesian")
            except Exception as e:
                print(f"  [endings] bayesian train fail: {e}")
                self.bayes_model = None

        # ── (7) 1D-CNN distribution head ──
        if "cnn" in self.active_models and TORCH_AVAILABLE:
            try:
                self._train_cnn(sum_series, dist_series, epochs=cnn_epochs)
                history["trained_models"].append("cnn_dist")
            except Exception as e:
                print(f"  [endings] cnn train fail: {e}")
                self.cnn_model = None

        self._is_trained = True
        history["feature_dim"] = self.feature_dim
        return history

    # ────── CNN 학습 ──────

    def _train_cnn(
        self,
        sum_series: np.ndarray,
        dist_series: np.ndarray,
        epochs: int = 30,
    ) -> None:
        """sum 시계열 -> 다음 끝수 분포 10D (multinomial CE).

        target 은 dist_series[t+1] 의 정규화된 확률 (합이 6 이므로 /6).
        """
        device = "cuda" if torch.cuda.is_available() else "cpu"
        self._cnn_device = device

        seq = self.cnn_seq_len
        T = len(sum_series)
        if T < seq + 2:
            raise ValueError(f"too short for CNN: need {seq + 2}, got {T}")

        X_list = []
        Y_list = []
        for i in range(seq, T - 1):
            window = sum_series[i - seq : i].astype(np.float32)
            target = dist_series[i + 1].astype(np.float32) / 6.0  # to prob
            X_list.append(window)
            Y_list.append(target)
        X_arr = np.stack(X_list)[:, None, :]  # (N, 1, seq)
        Y_arr = np.stack(Y_list)  # (N, 10)

        x = torch.from_numpy(X_arr).to(device)
        y = torch.from_numpy(Y_arr).to(device)

        self.cnn_model = _EndingsCNN(seq_len=seq).to(device)
        opt = torch.optim.Adam(self.cnn_model.parameters(), lr=1e-3, weight_decay=1e-5)

        n = X_arr.shape[0]
        bs = min(64, max(8, n // 4))
        for ep in range(epochs):
            self.cnn_model.train()
            perm = torch.randperm(n, device=device)
            for i in range(0, n, bs):
                idx = perm[i : i + bs]
                logits = self.cnn_model(x[idx])
                logp = torch.log_softmax(logits, dim=-1)
                loss = -(y[idx] * logp).sum(dim=-1).mean()
                opt.zero_grad()
                loss.backward()
                opt.step()

    # ────── 추론 ──────

    def predict(
        self,
        draws_so_far: list[dict],
        phase1_outputs: dict | None = None,
        min_history: int = 20,
    ) -> dict:
        """다음 회차 끝수합 quantile + 분포 10D + 산술 일치 체크."""
        if not self._is_trained or self._train_history is None:
            return self._baseline_payload()
        if not draws_so_far:
            return self._baseline_payload()

        sum_series, dist_series = self._extract_series(draws_so_far)
        if len(sum_series) < min_history:
            return self._baseline_payload()

        # 단일 시점 feature
        feats = build_scalar_features(sum_series, SCALAR_CFG)
        names = self._feature_names or sorted(feats.keys())
        x_query = np.array([[feats.get(k, 0.0) for k in names]], dtype=np.float32)

        # ── scalar quantile 집계 ──
        q10s, q50s, q90s = [], [], []

        if self.xgb_q10 is not None and self.xgb_q50 is not None and self.xgb_q90 is not None:
            try:
                q10s.append(float(self.xgb_q10.predict(x_query)[0]))
                q50s.append(float(self.xgb_q50.predict(x_query)[0]))
                q90s.append(float(self.xgb_q90.predict(x_query)[0]))
            except Exception:
                pass

        if self.tft_model is not None:
            try:
                p = self.tft_model.predict(x_query)
                if p is not None:
                    arr = np.asarray(p).reshape(-1)
                    if arr.size >= 3:
                        q10s.append(float(arr[0]))
                        q50s.append(float(arr[1]))
                        q90s.append(float(arr[2]))
                    elif arr.size >= 1:
                        q50s.append(float(arr[0]))
            except Exception:
                pass

        # N-BEATS: trend/seasonality 분해 + 점예측
        nbeats_pred = None
        if self.nbeats_model is not None:
            try:
                pred = self.nbeats_model.predict(sum_series.astype(np.float32), steps=1)
                nbeats_pred = float(pred[0]) if len(pred) > 0 else None
                if nbeats_pred is not None:
                    q50s.append(nbeats_pred)
            except Exception:
                nbeats_pred = None

        # Markov 6-bucket: 기댓값
        markov_expected = None
        if self.markov6 is not None:
            markov_expected = self.markov6.expected_value(float(sum_series[-1]))
            q50s.append(markov_expected)

        # Bayesian: sigma + quantile
        bayes_q10 = bayes_q50 = bayes_q90 = bayes_sigma = None
        if self.bayes_model is not None:
            try:
                out = self.bayes_model.predict_with_uncertainty(x_query)
                bayes_q10 = float(out["q10"][0])
                bayes_q50 = float(out["q50"][0])
                bayes_q90 = float(out["q90"][0])
                bayes_sigma = float(out["std"][0])
                q10s.append(bayes_q10)
                q50s.append(bayes_q50)
                q90s.append(bayes_q90)
            except Exception:
                pass

        # 합산
        if not q50s:
            # fallback: 직전값
            last = float(sum_series[-1])
            q10_final = last - 5.0
            q50_final = last
            q90_final = last + 5.0
        else:
            q10_final = float(np.mean(q10s)) if q10s else (np.mean(q50s) - 5.0)
            q50_final = float(np.mean(q50s))
            q90_final = float(np.mean(q90s)) if q90s else (np.mean(q50s) + 5.0)

        # ── distribution head ──
        dist_candidates: list[np.ndarray] = []

        # CNN
        if self.cnn_model is not None and TORCH_AVAILABLE:
            try:
                seq = self.cnn_seq_len
                if len(sum_series) >= seq:
                    window = sum_series[-seq:].astype(np.float32)[None, None, :]
                    self.cnn_model.eval()
                    with torch.no_grad():
                        x_in = torch.from_numpy(window).to(self._cnn_device)
                        logits = self.cnn_model(x_in)
                        probs = torch.softmax(logits, dim=-1).cpu().numpy()[0]
                    dist_candidates.append(probs * 6.0)  # back to expected count
            except Exception:
                pass

        # GNN aggregation (phase1_outputs.gnn_probs)
        gnn_probs = None
        if phase1_outputs is not None:
            gnn_probs = phase1_outputs.get("gnn_probs45")
        if gnn_probs is not None:
            try:
                dist_from_gnn = aggregate_endings_distribution(np.asarray(gnn_probs))
                dist_candidates.append(dist_from_gnn * 6.0)
            except Exception:
                pass

        # phase1 직접 출력 (digit_distribution 형태)
        if phase1_outputs is not None and "digit_distribution" in phase1_outputs:
            dd = phase1_outputs["digit_distribution"]
            try:
                arr = np.asarray(dd, dtype=np.float64).reshape(-1)
                if arr.size == 10:
                    dist_candidates.append(arr)
            except Exception:
                pass

        # default: 균등 (각 끝수 0.6 expected count)
        if dist_candidates:
            distribution_10d = np.mean(np.stack(dist_candidates, axis=0), axis=0)
        else:
            distribution_10d = np.full(10, 0.6, dtype=np.float64)

        # ── 산술 동치 체크: scalar_q50 vs sum(k * dist_k) ──
        dist_arr = np.asarray(distribution_10d, dtype=np.float64)
        scalar_from_dist = float(np.sum(np.arange(10) * dist_arr))
        consistency_check = float(abs(q50_final - scalar_from_dist))

        # ── narrative ──
        last_sum = int(sum_series[-1])
        narrative = (
            f"endings_sum ~ {q50_final:.1f} (q10={q10_final:.1f}, q90={q90_final:.1f}), "
            f"prev={last_sum}, dist_consistency={consistency_check:.2f}"
        )
        if bayes_sigma is not None:
            narrative += f", sigma={bayes_sigma:.2f}"

        return {
            "scalar": {
                "q10": q10_final,
                "q50": q50_final,
                "q90": q90_final,
            },
            "distribution_10d": dist_arr.tolist(),
            "consistency_check": consistency_check,
            "narrative": narrative,
            "components": {
                "markov_expected": markov_expected,
                "nbeats_pred": nbeats_pred,
                "bayes_sigma": bayes_sigma,
            },
        }

    def _baseline_payload(self) -> dict:
        return {
            "scalar": {"q10": 18.0, "q50": 22.5, "q90": 27.0},
            "distribution_10d": [0.6] * 10,
            "consistency_check": 0.0,
            "narrative": "endings not trained, uniform prior",
            "components": {},
        }

    # ────── persistence ──────

    def save(self, path: str) -> str:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        meta = {
            "feature_dim": self.feature_dim,
            "active_models": list(self.active_models),
            "cnn_seq_len": self.cnn_seq_len,
            "feature_names": self._feature_names,
            "is_trained": self._is_trained,
            "train_history": self._train_history,
            "train_dist_history": self._train_dist_history,
        }
        with open(path, "wb") as f:
            pickle.dump(meta, f)

        # XGB / Markov는 추가 파일 (pickle 가능)
        side: dict[str, Any] = {}
        if self.xgb_q10 is not None:
            side["xgb_q10"] = self.xgb_q10
            side["xgb_q50"] = self.xgb_q50
            side["xgb_q90"] = self.xgb_q90
        if self.markov6 is not None:
            side["markov6"] = self.markov6
        if side:
            with open(path + ".side", "wb") as f:
                pickle.dump(side, f)
        return path

    def load(self, path: str) -> None:
        with open(path, "rb") as f:
            meta = pickle.load(f)
        self.feature_dim = int(meta["feature_dim"])
        self.active_models = tuple(meta.get("active_models", self.DEFAULT_MODELS))
        self.cnn_seq_len = int(meta.get("cnn_seq_len", 30))
        self._feature_names = meta.get("feature_names")
        self._is_trained = bool(meta.get("is_trained", False))
        self._train_history = meta.get("train_history")
        self._train_dist_history = meta.get("train_dist_history")

        side_path = path + ".side"
        if os.path.exists(side_path):
            with open(side_path, "rb") as f:
                side = pickle.load(f)
            self.xgb_q10 = side.get("xgb_q10")
            self.xgb_q50 = side.get("xgb_q50")
            self.xgb_q90 = side.get("xgb_q90")
            self.markov6 = side.get("markov6")


# ────────────────── smoke ──────────────────


def _generate_fake_draws(n: int, seed: int = config.RANDOM_SEED) -> list[dict]:
    rng = np.random.default_rng(seed)
    draws = []
    pool = np.arange(1, 46)
    for r in range(n):
        nums = sorted(rng.choice(pool, size=6, replace=False).tolist())
        bonus_pool = [int(x) for x in pool if x not in nums]
        bonus = int(rng.choice(bonus_pool))
        draws.append({"round": 1000 + r, "numbers": nums, "bonus": bonus})
    return list(reversed(draws))


def _generate_fake_phase1_outputs(seed: int = config.RANDOM_SEED) -> dict:
    rng = np.random.default_rng(seed)
    gnn_probs = rng.dirichlet(np.ones(45)).astype(np.float32)
    return {
        "gnn_probs45": gnn_probs,
        "digit_distribution": (rng.dirichlet(np.ones(10)) * 6.0).tolist(),
    }


def main() -> None:
    """python -m predictors.endings_predictor --smoke."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()

    if not args.smoke:
        return

    print("[endings] generating 100 fake draws...")
    draws = _generate_fake_draws(100)
    phase1 = _generate_fake_phase1_outputs()

    pred = EndingsPredictor(feature_dim=24, active_models=("xgboost", "markov6", "bayesian", "cnn", "gnn"))
    print("[endings] training...")
    info = pred.train(draws, phase1_outputs=phase1, min_history=20, cnn_epochs=10, bayes_epochs=10)
    print(f"  trained models: {info['trained_models']}")
    print(f"  feature_dim: {info['feature_dim']}, n_train_rows: {info['n_train_rows']}")

    print("\n[endings] predicting next round...")
    out = pred.predict(draws, phase1_outputs=phase1, min_history=20)
    print(f"  scalar: q10={out['scalar']['q10']:.2f}, q50={out['scalar']['q50']:.2f}, q90={out['scalar']['q90']:.2f}")
    dist = out["distribution_10d"]
    print(f"  distribution_10d: sum={sum(dist):.3f}")
    print(f"    {[round(v, 3) for v in dist]}")
    print(f"  consistency_check: {out['consistency_check']:.3f}")
    print(f"  narrative: {out['narrative']}")


if __name__ == "__main__":
    main()
