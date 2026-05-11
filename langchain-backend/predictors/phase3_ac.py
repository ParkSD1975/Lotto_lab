"""Phase 3 ACPredictor — AC값 스칼라 quantile 회귀.

AC값 정의: 본번호 6개 쌍별 차이(unique) 개수 - (n-1)
  diffs = {|a-b| for all pairs} → AC = len(diffs) - 5 (n=6)
범위: 보통 4~10

Phase cross-feedback:
  - Phase 1: 고저/홀짝/번호대 expected_count
  - Phase 2: 끝수합 expected_value
  - AC 고유: ac_to_sum_ratio, ac_to_consecutive_count (scalar_features.py)

NBeats trend/seasonality 분해 + XGBoost quantile 회귀 + Markov 7-bucket
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


# ────────────────── Markov 7-bucket (AC 범위) ──────────────────


class _ACMarkov7:
    """AC값 7-bucket 전이행렬. 범위 4~10."""

    BUCKETS = [(0, 3), (4, 4), (5, 5), (6, 6), (7, 7), (8, 8), (9, 15)]

    def __init__(self) -> None:
        n = len(self.BUCKETS)
        self.transition = np.full((n, n), 1.0 / n)

    def _bucket(self, value: float) -> int:
        for k, (lo, hi) in enumerate(self.BUCKETS):
            if lo <= value <= hi:
                return k
        return len(self.BUCKETS) - 1 if value > self.BUCKETS[-1][1] else 0

    def fit(self, series: np.ndarray) -> None:
        n = len(self.BUCKETS)
        T = np.zeros((n, n), dtype=np.float64)
        for i in range(len(series) - 1):
            a = self._bucket(float(series[i]))
            b = self._bucket(float(series[i + 1]))
            T[a, b] += 1.0
        T += 1.0
        T = T / T.sum(axis=1, keepdims=True)
        self.transition = T

    def predict_proba(self, last_value: float) -> np.ndarray:
        idx = self._bucket(float(last_value))
        return self.transition[idx].copy()

    def expected_value(self, last_value: float) -> float:
        probs = self.predict_proba(last_value)
        means = np.array([(lo + hi) / 2.0 for lo, hi in self.BUCKETS])
        return float((probs * means).sum())


# ────────────────── AC 계산 ──────────────────


def _compute_ac(numbers: list[int]) -> int:
    """AC값 = unique diff 개수 - (n-1)."""
    if len(numbers) < 2:
        return 0
    diffs = set()
    for i in range(len(numbers)):
        for j in range(i + 1, len(numbers)):
            diffs.add(abs(numbers[i] - numbers[j]))
    return len(diffs) - (len(numbers) - 1)


# ────────────────── Phase 3 ACPredictor ──────────────────


class Phase3ACPredictor:
    """Phase 3 predictor. AC값 quantile 회귀 + Phase 1+2 cross-feedback."""

    DEFAULT_MODELS = ("xgboost", "nbeats", "markov7", "bayesian")

    def __init__(
        self,
        feature_dim: int = 30,
        active_models: tuple[str, ...] | None = None,
    ) -> None:
        self.feature_dim = int(feature_dim)
        self.active_models = active_models or self.DEFAULT_MODELS

        self.xgb_q10: Any = None
        self.xgb_q50: Any = None
        self.xgb_q90: Any = None
        self.nbeats_model: Any = None
        self.markov7: _ACMarkov7 | None = None
        self.bayes_model: Any = None

        self._feature_names: list[str] | None = None
        self._train_series: np.ndarray | None = None
        self._train_sum: np.ndarray | None = None
        self._train_consecutive: np.ndarray | None = None
        self._is_trained = False

    # ────── 시계열 추출 ──────

    def _extract_series(self, draws: list[dict]) -> np.ndarray:
        """회차별 AC값 추출 (순서대로)."""
        ordered = sorted(draws, key=lambda d: int(d.get("round", 0)))
        ac_vals = []
        for d in ordered:
            nums = d.get("numbers", [])
            ac_vals.append(_compute_ac(nums))
        return np.array(ac_vals, dtype=np.float64)

    def _extract_sum_series(self, draws: list[dict]) -> np.ndarray:
        """회차별 총합 추출 (AC cross-feature용)."""
        ordered = sorted(draws, key=lambda d: int(d.get("round", 0)))
        sums = [sum(d.get("numbers", [])) for d in ordered]
        return np.array(sums, dtype=np.float64)

    def _extract_consecutive_series(self, draws: list[dict]) -> np.ndarray:
        """회차별 연번 개수 추출 (AC cross-feature용)."""
        ordered = sorted(draws, key=lambda d: int(d.get("round", 0)))
        counts = []
        for d in ordered:
            nums = sorted(d.get("numbers", []))
            cnt = 0
            for i in range(len(nums) - 1):
                if nums[i + 1] - nums[i] == 1:
                    cnt += 1
            counts.append(cnt)
        return np.array(counts, dtype=np.float64)

    # ────── feature ──────

    def _build_features_at(
        self,
        ac_history: np.ndarray,
        sum_history: np.ndarray | None = None,
        consecutive_history: np.ndarray | None = None,
        phase1_outputs: dict | None = None,
        phase2_endings: dict | None = None,
    ) -> dict:
        """단일 시점 feature dict (24 scalar + AC cross + Phase 1+2 cross)."""
        feats = build_scalar_features(ac_history, SCALAR_CFG)

        # AC 고유 cross-feature
        if sum_history is not None and len(sum_history) == len(ac_history):
            ac_cross = build_ac_cross_features(sum_history, ac_history, consecutive_history)
            feats.update(ac_cross)
        else:
            feats["ac_to_sum_ratio_lag_1"] = 0.0
            feats["ac_to_consecutive_count_lag_1"] = 0.0

        # cross-feedback: Phase 2 끝수합
        if phase2_endings is not None:
            scalar = phase2_endings.get("scalar", {}) or {}
            q50 = float(scalar.get("q50", 22.5) or 22.5)
            feats["cf_p2_endings_q50"] = q50
        else:
            feats["cf_p2_endings_q50"] = 22.5

        # cross-feedback: Phase 1 고저/홀짝/번호대
        if phase1_outputs is not None:
            feats["cf_p1_high_count_expected"] = float(
                phase1_outputs.get("expected_high_count", 3.0) or 3.0
            )
            feats["cf_p1_even_count_expected"] = float(
                phase1_outputs.get("expected_even_count", 3.0) or 3.0
            )
            decade = phase1_outputs.get("expected_decade_dist") or phase1_outputs.get("decade_distribution")
            if isinstance(decade, (list, tuple, np.ndarray)):
                d_arr = list(decade)[:5]
                while len(d_arr) < 5:
                    d_arr.append(0.0)
                for i, v in enumerate(d_arr):
                    feats[f"cf_p1_decade_{i}"] = float(v)
            else:
                for i in range(5):
                    feats[f"cf_p1_decade_{i}"] = 0.0
        else:
            feats["cf_p1_high_count_expected"] = 3.0
            feats["cf_p1_even_count_expected"] = 3.0
            for i in range(5):
                feats[f"cf_p1_decade_{i}"] = 0.0

        return feats

    def _build_training_matrix(
        self,
        ac_series: np.ndarray,
        sum_series: np.ndarray | None = None,
        consecutive_series: np.ndarray | None = None,
        min_history: int = 20,
        phase1_outputs: dict | None = None,
        phase2_endings: dict | None = None,
    ) -> tuple[np.ndarray, np.ndarray, list[str]]:
        rows = []
        names = None
        for i in range(min_history, len(ac_series)):
            sum_hist = sum_series[:i] if sum_series is not None else None
            consec_hist = consecutive_series[:i] if consecutive_series is not None else None
            feats = self._build_features_at(
                ac_series[:i],
                sum_history=sum_hist,
                consecutive_history=consec_hist,
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

        ac_series = self._extract_series(draws)
        sum_series = self._extract_sum_series(draws)
        consecutive_series = self._extract_consecutive_series(draws)

        if len(ac_series) < min_history + 5:
            raise ValueError(
                f"insufficient draws: got {len(ac_series)} need >= {min_history + 5}"
            )

        self._train_series = ac_series.copy()
        self._train_sum = sum_series.copy()
        self._train_consecutive = consecutive_series.copy()

        X, y, names = self._build_training_matrix(
            ac_series,
            sum_series=sum_series,
            consecutive_series=consecutive_series,
            min_history=min_history,
            phase1_outputs=phase1_outputs,
            phase2_endings=phase2_endings,
        )
        if X.shape[0] < 5:
            raise ValueError(f"too few training rows: {X.shape[0]}")
        self._feature_names = names
        self.feature_dim = int(X.shape[1])

        history: dict[str, Any] = {"trained_models": [], "n_train_rows": int(X.shape[0])}

        # ── XGBoost Quantile (메인) ──
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

        # ── N-BEATS (분해 head) ──
        if "nbeats" in self.active_models and NBEATS_AVAIL:
            try:
                self.nbeats_model = LottoNBeats(seq_length=min(50, len(ac_series) // 3))
                self.nbeats_model.train(ac_series.astype(np.float32))
                history["trained_models"].append("nbeats")
            except Exception as e:
                print(f"  [ac] nbeats train fail: {e}")
                self.nbeats_model = None

        # ── Markov 7-bucket ──
        if "markov7" in self.active_models:
            self.markov7 = _ACMarkov7()
            self.markov7.fit(ac_series)
            history["trained_models"].append("markov7")

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

        ac_series = self._extract_series(draws_so_far)
        sum_series = self._extract_sum_series(draws_so_far)
        consecutive_series = self._extract_consecutive_series(draws_so_far)

        if len(ac_series) < min_history:
            return self._baseline_payload()

        feats = self._build_features_at(
            ac_series,
            sum_history=sum_series,
            consecutive_history=consecutive_series,
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

        # N-BEATS: 분해 + 점예측
        nbeats_pred = None
        nbeats_decomp = {"trend": None, "seasonality": None, "residual": None}
        if self.nbeats_model is not None:
            try:
                pred = self.nbeats_model.predict(ac_series.astype(np.float32), steps=1)
                nbeats_pred = float(pred[0]) if len(pred) > 0 else None
                if nbeats_pred is not None:
                    q50s.append(nbeats_pred)
                try:
                    dec = self.nbeats_model.decompose(ac_series.astype(np.float32))
                    nbeats_decomp = {
                        "trend": float(dec["trend"][-1]) if dec.get("trend") is not None and len(dec["trend"]) > 0 else None,
                        "seasonality": float(dec["seasonality"][-1]) if dec.get("seasonality") is not None and len(dec["seasonality"]) > 0 else None,
                        "residual": float(dec["residual"][-1]) if dec.get("residual") is not None and len(dec["residual"]) > 0 else None,
                    }
                except Exception:
                    pass
            except Exception:
                pass

        # Markov 7-bucket
        markov_expected = None
        if self.markov7 is not None:
            markov_expected = self.markov7.expected_value(float(ac_series[-1]))
            q50s.append(markov_expected)

        # Bayesian
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

        # 빈도 베이스라인 (frequency baseline)
        freq_dist = self._compute_freq_dist(ac_series)
        freq_expected = self._dist_to_expected(freq_dist)
        q50s.append(freq_expected)

        if not q50s:
            last = float(ac_series[-1])
            q10_final = max(0, last - 2.0)
            q50_final = last
            q90_final = min(15, last + 2.0)
        else:
            q10_final = float(np.mean(q10s)) if q10s else (np.mean(q50s) - 2.0)
            q50_final = float(np.mean(q50s))
            q90_final = float(np.mean(q90s)) if q90s else (np.mean(q50s) + 2.0)

        # 범위 제약 (AC는 보통 4~10이지만 극단값 허용)
        q10_final = max(0, min(15, q10_final))
        q50_final = max(0, min(15, q50_final))
        q90_final = max(0, min(15, q90_final))

        # 7-class 분포 (bucket별)
        absolute_dist = self._quantile_to_dist(q10_final, q50_final, q90_final)

        # narrative
        iqr = q90_final - q10_final
        bucket_idx = self._find_bucket(q50_final)
        bucket_range = _ACMarkov7.BUCKETS[bucket_idx]
        narrative = (
            f"AC값 추정 {q50_final:.1f}, 최빈 bucket {bucket_range[0]}~{bucket_range[1]} "
            f"(q10={q10_final:.1f}, q90={q90_final:.1f}, IQR={iqr:.1f})"
        )
        if nbeats_decomp.get("trend") is not None:
            narrative += f", nbeats_trend={nbeats_decomp['trend']:.1f}"
        if bayes_sigma is not None:
            narrative += f", bayes_sigma={bayes_sigma:.2f}"

        return {
            "expected_value": q50_final,
            "absolute_dist": absolute_dist.tolist(),
            "current_pool_size": None,
            "expected_ratio": None,
            "narrative": narrative,
            "model_contributions": {
                "xgboost": 0.4 if self.xgb_q10 is not None else 0.0,
                "nbeats": 0.2 if nbeats_pred is not None else 0.0,
                "markov7": 0.2 if markov_expected is not None else 0.0,
                "bayesian": 0.1 if bayes_sigma is not None else 0.0,
                "frequency": 0.1,
            },
            "q10": q10_final,
            "q50": q50_final,
            "q90": q90_final,
            "nbeats_decomposition": nbeats_decomp,
            "components": {
                "markov_expected": markov_expected,
                "nbeats_pred": nbeats_pred,
                "bayes_sigma": bayes_sigma,
                "freq_expected": freq_expected,
            },
        }

    def _baseline_payload(self) -> dict:
        return {
            "expected_value": 7.0,
            "absolute_dist": [0.05, 0.10, 0.15, 0.25, 0.20, 0.15, 0.10],
            "current_pool_size": None,
            "expected_ratio": None,
            "narrative": "AC값 미학습, prior 7.0 +/- 2",
            "model_contributions": {},
            "q10": 5.0,
            "q50": 7.0,
            "q90": 9.0,
            "nbeats_decomposition": {"trend": None, "seasonality": None, "residual": None},
            "components": {},
        }

    def _compute_freq_dist(self, series: np.ndarray) -> np.ndarray:
        """빈도 분포 (7-class bucket)."""
        counts = np.zeros(7, dtype=np.float64)
        for val in series:
            idx = self._find_bucket(val)
            counts[idx] += 1.0
        total = counts.sum()
        return counts / max(total, 1.0)

    def _find_bucket(self, value: float) -> int:
        """값이 속한 bucket 인덱스."""
        for k, (lo, hi) in enumerate(_ACMarkov7.BUCKETS):
            if lo <= value <= hi:
                return k
        return 6 if value > _ACMarkov7.BUCKETS[-1][1] else 0

    def _dist_to_expected(self, dist: np.ndarray) -> float:
        """분포 → 기댓값."""
        means = np.array([(lo + hi) / 2.0 for lo, hi in _ACMarkov7.BUCKETS])
        return float((dist * means).sum())

    def _quantile_to_dist(self, q10: float, q50: float, q90: float) -> np.ndarray:
        """quantile → 7-class 분포 (간단 근사: 정규분포 가정)."""
        dist = np.zeros(7, dtype=np.float64)
        means = np.array([(lo + hi) / 2.0 for lo, hi in _ACMarkov7.BUCKETS])

        # 정규분포 근사 (IQR 기반)
        iqr = q90 - q10
        sigma = iqr / (2 * 1.28)  # 80% CI → sigma

        for i, m in enumerate(means):
            # 각 bucket 중심에서의 밀도
            z = (m - q50) / max(sigma, 1e-6)
            dist[i] = np.exp(-0.5 * z * z)

        total = dist.sum()
        if total > 1e-9:
            dist /= total
        else:
            dist = np.full(7, 1.0 / 7)

        return dist

    # ────── persistence ──────

    def save(self, path: str) -> str:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        meta = {
            "feature_dim": self.feature_dim,
            "active_models": list(self.active_models),
            "feature_names": self._feature_names,
            "is_trained": self._is_trained,
            "train_series": self._train_series,
            "train_sum": self._train_sum,
            "train_consecutive": self._train_consecutive,
        }
        with open(path, "wb") as f:
            pickle.dump(meta, f)

        side: dict[str, Any] = {}
        if self.xgb_q10 is not None:
            side["xgb_q10"] = self.xgb_q10
            side["xgb_q50"] = self.xgb_q50
            side["xgb_q90"] = self.xgb_q90
        if self.markov7 is not None:
            side["markov7"] = self.markov7
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
        self._train_series = meta.get("train_series")
        self._train_sum = meta.get("train_sum")
        self._train_consecutive = meta.get("train_consecutive")

        side_path = path + ".side"
        if os.path.exists(side_path):
            with open(side_path, "rb") as f:
                side = pickle.load(f)
            self.xgb_q10 = side.get("xgb_q10")
            self.xgb_q50 = side.get("xgb_q50")
            self.xgb_q90 = side.get("xgb_q90")
            self.markov7 = side.get("markov7")


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


def main() -> None:
    """python -m predictors.phase3_ac --smoke."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()

    if not args.smoke:
        return

    print("[ac] generating 100 fake draws...")
    draws = _generate_fake_draws(100)

    pred = Phase3ACPredictor(active_models=("xgboost", "markov7", "bayesian"))
    print("[ac] training...")
    info = pred.train(
        draws, phase1_outputs=None, phase2_endings=None,
        min_history=20, bayes_epochs=10,
    )
    print(f"  trained models: {info['trained_models']}")
    print(f"  feature_dim: {info['feature_dim']}, n_train_rows: {info['n_train_rows']}")

    print("\n[ac] predicting next round...")
    out = pred.predict(draws, phase1_outputs=None, phase2_endings=None, min_history=20)
    print(f"  expected_value={out['expected_value']:.1f}")
    print(f"  q10={out['q10']:.1f}, q50={out['q50']:.1f}, q90={out['q90']:.1f}")
    print(f"  absolute_dist (7-class): {[f'{x:.3f}' for x in out['absolute_dist']]}")
    print(f"  narrative: {out['narrative']}")


if __name__ == "__main__":
    main()
