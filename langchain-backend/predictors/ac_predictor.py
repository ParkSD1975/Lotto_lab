"""ACPredictor (Phase 3) — AC값 스칼라 quantile 회귀.

AC = (조합 distinct 차이값 개수) - 5. AC 0~10 이산.
Markov 11-state 가 가장 자연 (AC 0~10). Phase 1+2 cross-feedback 흡수.
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
    build_ac_cross_features,
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
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    torch = None  # type: ignore

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


# ────────────────── Markov 11-state (AC 0~10) ──────────────────


class _ACMarkov11:
    """AC 0~10 11-state 전이행렬. Laplace smoothing."""

    N_STATES = 11

    def __init__(self) -> None:
        n = self.N_STATES
        self.transition = np.full((n, n), 1.0 / n)

    def _state(self, value: float) -> int:
        idx = int(round(float(value)))
        return max(0, min(self.N_STATES - 1, idx))

    def fit(self, series: np.ndarray) -> None:
        n = self.N_STATES
        T = np.zeros((n, n), dtype=np.float64)
        for i in range(len(series) - 1):
            a = self._state(series[i])
            b = self._state(series[i + 1])
            T[a, b] += 1.0
        T += 1.0  # Laplace
        T = T / T.sum(axis=1, keepdims=True)
        self.transition = T

    def predict_proba(self, last_value: float) -> np.ndarray:
        idx = self._state(last_value)
        return self.transition[idx].copy()

    def expected_value(self, last_value: float) -> float:
        probs = self.predict_proba(last_value)
        states = np.arange(self.N_STATES, dtype=np.float64)
        return float((probs * states).sum())

    def quantile(self, last_value: float, q: float) -> float:
        """누적분포로 quantile 추정."""
        probs = self.predict_proba(last_value)
        cdf = np.cumsum(probs)
        idx = int(np.searchsorted(cdf, q))
        return float(min(idx, self.N_STATES - 1))


# ────────────────── AC 계산 ──────────────────


def _compute_ac(numbers: list[int]) -> int:
    """AC = distinct(차이) - 5. numbers 6개 정수.

    각 쌍의 절댓값 차이를 모두 모은 뒤 distinct 개수에서 5를 뺀다.
    """
    if len(numbers) < 2:
        return 0
    nums = sorted(int(n) for n in numbers)
    diffs = set()
    for i in range(len(nums)):
        for j in range(i + 1, len(nums)):
            diffs.add(abs(nums[j] - nums[i]))
    return max(0, len(diffs) - 5)


def _consecutive_count(numbers: list[int]) -> int:
    """정렬한 6번호의 인접쌍 (n+1) 개수."""
    nums = sorted(int(n) for n in numbers)
    return sum(1 for i in range(len(nums) - 1) if nums[i + 1] - nums[i] == 1)


# ────────────────── ACPredictor 본체 ──────────────────


class ACPredictor:
    """Phase 3 predictor. AC값 quantile 회귀 + Markov 11-state."""

    DEFAULT_MODELS = ("xgboost", "tft", "markov11", "nbeats", "bayesian")

    def __init__(
        self,
        feature_dim: int = 26,  # 24 scalar + 2 AC cross
        active_models: tuple[str, ...] | None = None,
    ) -> None:
        self.feature_dim = int(feature_dim)
        self.active_models = active_models or self.DEFAULT_MODELS

        self.xgb_q10: Any = None
        self.xgb_q50: Any = None
        self.xgb_q90: Any = None
        self.tft_model: Any = None
        self.nbeats_model: Any = None
        self.markov11: _ACMarkov11 | None = None
        self.bayes_model: Any = None

        self._feature_names: list[str] | None = None
        self._train_ac: np.ndarray | None = None
        self._train_sum: np.ndarray | None = None
        self._train_consec: np.ndarray | None = None
        self._is_trained = False

    # ────── 시계열 추출 ──────

    def _extract_series(
        self, draws: list[dict]
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """draws -> (ac_series, sum_series, consec_series). 시간순."""
        ordered = sorted(draws, key=lambda d: int(d.get("round", 0)))
        acs, sums, consec = [], [], []
        for d in ordered:
            nums = list(d.get("numbers", []))
            acs.append(_compute_ac(nums))
            sums.append(sum(int(n) for n in nums))
            consec.append(_consecutive_count(nums))
        return (
            np.array(acs, dtype=np.float64),
            np.array(sums, dtype=np.float64),
            np.array(consec, dtype=np.float64),
        )

    # ────── feature 빌드 ──────

    def _build_features_at(
        self,
        ac_history: np.ndarray,
        sum_history: np.ndarray,
        consec_history: np.ndarray,
        phase1_outputs: dict | None = None,
        phase2_endings: dict | None = None,
    ) -> dict:
        """단일 시점 feature dict (24 scalar + 2 AC cross + cross-feedback)."""
        feats = build_scalar_features(ac_history, SCALAR_CFG)
        cross = build_ac_cross_features(sum_history, ac_history, consec_history)
        feats.update(cross)

        # cross-feedback: phase1 (consecutive_count expected, high_count expected)
        if phase1_outputs is not None:
            feats["cf_p1_consec_expected"] = float(
                phase1_outputs.get("consecutive_expected", 0.0) or 0.0
            )
            feats["cf_p1_high_count_expected"] = float(
                phase1_outputs.get("high_count_expected", 3.0) or 3.0
            )
            feats["cf_p1_odd_count_expected"] = float(
                phase1_outputs.get("odd_count_expected", 3.0) or 3.0
            )
        else:
            feats["cf_p1_consec_expected"] = 0.0
            feats["cf_p1_high_count_expected"] = 3.0
            feats["cf_p1_odd_count_expected"] = 3.0

        # cross-feedback: phase2 (endings_sum q50)
        if phase2_endings is not None:
            scalar = phase2_endings.get("scalar", {}) or {}
            feats["cf_p2_endings_q50"] = float(scalar.get("q50", 22.5) or 22.5)
        else:
            feats["cf_p2_endings_q50"] = 22.5

        return feats

    def _build_training_matrix(
        self,
        ac_series: np.ndarray,
        sum_series: np.ndarray,
        consec_series: np.ndarray,
        min_history: int = 20,
        phase1_outputs: dict | None = None,
        phase2_endings: dict | None = None,
    ) -> tuple[np.ndarray, np.ndarray, list[str]]:
        rows = []
        names = None
        for i in range(min_history, len(ac_series)):
            feats = self._build_features_at(
                ac_series[:i],
                sum_series[:i],
                consec_series[:i],
                phase1_outputs=phase1_outputs,
                phase2_endings=phase2_endings,
            )
            if names is None:
                names = sorted(feats.keys())
            rows.append([feats[k] for k in names])
        if not rows:
            return np.zeros((0, 0)), np.zeros((0,)), names or []
        X = np.array(rows, dtype=np.float64)
        y = ac_series[min_history:]
        return X, y, names or []

    # ────── 학습 ──────

    def train(
        self,
        draws: list[dict],
        phase1_outputs: dict | None = None,
        phase2_endings: dict | None = None,
        min_history: int = 20,
        bayes_epochs: int = 30,
    ) -> dict:
        if not draws:
            raise ValueError("empty draws")

        ac_series, sum_series, consec_series = self._extract_series(draws)
        if len(ac_series) < min_history + 5:
            raise ValueError(
                f"insufficient draws: got {len(ac_series)} need >= {min_history + 5}"
            )

        self._train_ac = ac_series.copy()
        self._train_sum = sum_series.copy()
        self._train_consec = consec_series.copy()

        X, y, names = self._build_training_matrix(
            ac_series, sum_series, consec_series,
            min_history=min_history,
            phase1_outputs=phase1_outputs,
            phase2_endings=phase2_endings,
        )
        if X.shape[0] < 5:
            raise ValueError(f"too few training rows: {X.shape[0]}")
        self._feature_names = names
        self.feature_dim = int(X.shape[1])

        history: dict[str, Any] = {"trained_models": [], "n_train_rows": int(X.shape[0])}

        # ── XGBoost Quantile ──
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
                self.xgb_q10.fit(X, y)
                self.xgb_q50.fit(X, y)
                self.xgb_q90.fit(X, y)
                history["trained_models"].append("xgboost_quantile")
            except Exception as e:
                print(f"  [ac] xgboost train fail: {e}")
                self.xgb_q10 = self.xgb_q50 = self.xgb_q90 = None

        # ── TFT ──
        if "tft" in self.active_models and TFT_AVAIL:
            try:
                self.tft_model = LottoTFT(
                    input_dim=self.feature_dim, output_size=3, task_type="regression"
                )
                self.tft_model.train(X, y)
                history["trained_models"].append("tft")
            except Exception as e:
                print(f"  [ac] tft train fail: {e}")
                self.tft_model = None

        # ── Markov 11-state (메인) ──
        if "markov11" in self.active_models:
            self.markov11 = _ACMarkov11()
            self.markov11.fit(ac_series)
            history["trained_models"].append("markov11")

        # ── N-BEATS ──
        if "nbeats" in self.active_models and NBEATS_AVAIL:
            try:
                self.nbeats_model = LottoNBeats(seq_length=min(30, len(ac_series) // 3))
                self.nbeats_model.train(ac_series.astype(np.float32))
                history["trained_models"].append("nbeats")
            except Exception as e:
                print(f"  [ac] nbeats train fail: {e}")
                self.nbeats_model = None

        # ── Bayesian sigma ──
        if "bayesian" in self.active_models and BAYES_AVAIL:
            try:
                self.bayes_model = LottoBayesianNN(
                    input_dim=self.feature_dim,
                    num_classes=1,
                    task_type="regression",
                    mc_samples=20,
                )
                self.bayes_model.train(
                    X.astype(np.float32),
                    y.astype(np.float32).reshape(-1, 1),
                    max_epochs=bayes_epochs,
                )
                history["trained_models"].append("bayesian")
            except Exception as e:
                print(f"  [ac] bayesian train fail: {e}")
                self.bayes_model = None

        self._is_trained = True
        history["feature_dim"] = self.feature_dim
        return history

    # ────── 추론 ──────

    def predict(
        self,
        draws_so_far: list[dict],
        phase1_outputs: dict | None = None,
        phase2_endings: dict | None = None,
        min_history: int = 20,
    ) -> dict:
        if not self._is_trained:
            return self._baseline_payload()
        if not draws_so_far:
            return self._baseline_payload()

        ac_series, sum_series, consec_series = self._extract_series(draws_so_far)
        if len(ac_series) < min_history:
            return self._baseline_payload()

        feats = self._build_features_at(
            ac_series, sum_series, consec_series,
            phase1_outputs=phase1_outputs,
            phase2_endings=phase2_endings,
        )
        names = self._feature_names or sorted(feats.keys())
        x_query = np.array([[feats.get(k, 0.0) for k in names]], dtype=np.float32)

        # ── quantile 집계 ──
        q10s, q50s, q90s = [], [], []

        if self.xgb_q10 is not None:
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

        markov_dist = None
        markov_expected = None
        if self.markov11 is not None:
            markov_dist = self.markov11.predict_proba(float(ac_series[-1]))
            markov_expected = self.markov11.expected_value(float(ac_series[-1]))
            q10s.append(self.markov11.quantile(float(ac_series[-1]), 0.10))
            q50s.append(markov_expected)
            q90s.append(self.markov11.quantile(float(ac_series[-1]), 0.90))

        nbeats_pred = None
        if self.nbeats_model is not None:
            try:
                pred = self.nbeats_model.predict(ac_series.astype(np.float32), steps=1)
                nbeats_pred = float(pred[0]) if len(pred) > 0 else None
                if nbeats_pred is not None:
                    q50s.append(nbeats_pred)
            except Exception:
                nbeats_pred = None

        bayes_sigma = None
        if self.bayes_model is not None:
            try:
                out = self.bayes_model.predict_with_uncertainty(x_query)
                q10s.append(float(out["q10"][0]))
                q50s.append(float(out["q50"][0]))
                q90s.append(float(out["q90"][0]))
                bayes_sigma = float(out["std"][0])
            except Exception:
                pass

        if not q50s:
            last = float(ac_series[-1])
            q10_final = max(0.0, last - 2.0)
            q50_final = last
            q90_final = min(10.0, last + 2.0)
        else:
            q10_final = float(np.mean(q10s)) if q10s else (np.mean(q50s) - 2.0)
            q50_final = float(np.mean(q50s))
            q90_final = float(np.mean(q90s)) if q90s else (np.mean(q50s) + 2.0)

        # clip to [0, 10]
        q10_final = max(0.0, min(10.0, q10_final))
        q50_final = max(0.0, min(10.0, q50_final))
        q90_final = max(0.0, min(10.0, q90_final))

        # Markov 분포
        if markov_dist is None:
            markov_dist = np.full(11, 1.0 / 11)

        # narrative
        last_consec = int(consec_series[-1])
        last_ac = float(ac_series[-1])
        z_short = float(feats.get("zscore_short", 0.0))
        narrative = (
            f"AC ~ {q50_final:.2f} (z={z_short:.2f}, q10={q10_final:.2f}, q90={q90_final:.2f}), "
            f"prev_AC={last_ac:.0f}, prev_consec={last_consec} pair -> AC range [{q10_final:.0f},{q90_final:.0f}]"
        )
        if bayes_sigma is not None:
            narrative += f", sigma={bayes_sigma:.2f}"

        return {
            "q10": q10_final,
            "q50": q50_final,
            "q90": q90_final,
            "markov_11state_dist": np.asarray(markov_dist, dtype=np.float64).tolist(),
            "narrative": narrative,
            "components": {
                "markov_expected": markov_expected,
                "nbeats_pred": nbeats_pred,
                "bayes_sigma": bayes_sigma,
            },
        }

    def _baseline_payload(self) -> dict:
        return {
            "q10": 5.0,
            "q50": 7.0,
            "q90": 9.0,
            "markov_11state_dist": [1.0 / 11] * 11,
            "narrative": "AC not trained, uniform prior",
            "components": {},
        }

    # ────── persistence ──────

    def save(self, path: str) -> str:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        meta = {
            "feature_dim": self.feature_dim,
            "active_models": list(self.active_models),
            "feature_names": self._feature_names,
            "is_trained": self._is_trained,
            "train_ac": self._train_ac,
            "train_sum": self._train_sum,
            "train_consec": self._train_consec,
        }
        with open(path, "wb") as f:
            pickle.dump(meta, f)

        side: dict[str, Any] = {}
        if self.xgb_q10 is not None:
            side["xgb_q10"] = self.xgb_q10
            side["xgb_q50"] = self.xgb_q50
            side["xgb_q90"] = self.xgb_q90
        if self.markov11 is not None:
            side["markov11"] = self.markov11
        if side:
            with open(path + ".side", "wb") as f:
                pickle.dump(side, f)
        return path

    def load(self, path: str) -> None:
        with open(path, "rb") as f:
            meta = pickle.load(f)
        self.feature_dim = int(meta["feature_dim"])
        self.active_models = tuple(meta.get("active_models", self.DEFAULT_MODELS))
        self._feature_names = meta.get("feature_names")
        self._is_trained = bool(meta.get("is_trained", False))
        self._train_ac = meta.get("train_ac")
        self._train_sum = meta.get("train_sum")
        self._train_consec = meta.get("train_consec")

        side_path = path + ".side"
        if os.path.exists(side_path):
            with open(side_path, "rb") as f:
                side = pickle.load(f)
            self.xgb_q10 = side.get("xgb_q10")
            self.xgb_q50 = side.get("xgb_q50")
            self.xgb_q90 = side.get("xgb_q90")
            self.markov11 = side.get("markov11")


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


def _generate_fake_phase_inputs(seed: int = config.RANDOM_SEED) -> tuple[dict, dict]:
    rng = np.random.default_rng(seed)
    p1 = {
        "consecutive_expected": float(rng.uniform(0.5, 1.5)),
        "high_count_expected": float(rng.uniform(2.5, 3.5)),
        "odd_count_expected": float(rng.uniform(2.5, 3.5)),
    }
    p2 = {
        "scalar": {
            "q10": float(rng.uniform(15, 20)),
            "q50": float(rng.uniform(20, 26)),
            "q90": float(rng.uniform(26, 32)),
        }
    }
    return p1, p2


def main() -> None:
    """python -m predictors.ac_predictor --smoke."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()

    if not args.smoke:
        return

    print("[ac] generating 100 fake draws...")
    draws = _generate_fake_draws(100)
    p1, p2 = _generate_fake_phase_inputs()

    pred = ACPredictor(active_models=("xgboost", "markov11", "bayesian"))
    print("[ac] training...")
    info = pred.train(
        draws, phase1_outputs=p1, phase2_endings=p2,
        min_history=20, bayes_epochs=10,
    )
    print(f"  trained models: {info['trained_models']}")
    print(f"  feature_dim: {info['feature_dim']}, n_train_rows: {info['n_train_rows']}")

    print("\n[ac] predicting next round...")
    out = pred.predict(draws, phase1_outputs=p1, phase2_endings=p2, min_history=20)
    print(f"  q10={out['q10']:.2f}, q50={out['q50']:.2f}, q90={out['q90']:.2f}")
    md = out["markov_11state_dist"]
    print(f"  markov_11state_dist: sum={sum(md):.3f}, top3_states={np.argsort(-np.array(md))[:3].tolist()}")
    print(f"  narrative: {out['narrative']}")


if __name__ == "__main__":
    main()
