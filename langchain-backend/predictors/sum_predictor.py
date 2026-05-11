"""SumPredictor (Phase 4) — 총합 스칼라 quantile 회귀.

모든 Phase 1+2+3 시그널 흡수 + sum 카르텟 (decades/gungs/horizontal/prime_composite).
N-BEATS trend/seasonality 분해 head 노출 (narrative).
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
from features.gnn_aggregation import aggregate_sum


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

# Stage 1-5 임시 비활성: LottoAutoencoder는 7x7 grid 전용 (input_dim 인자 없음)
# sum 스칼라 feature와 호환 안 됨. 향후 sum 전용 AE 또는 feature 변환으로 별도 통합.
AE_AVAIL = False
LottoAutoencoder = None  # type: ignore


# ────────────────── Markov 6-bucket (sum range) ──────────────────


class _SumMarkov6:
    """sum 6-bucket 전이행렬. sum 범위 분할 21~255."""

    BUCKETS = [(21, 90), (91, 110), (111, 130), (131, 150), (151, 175), (176, 255)]

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


# ────────────────── Sum 카르텟 ──────────────────


def _safe_get_dist(d: dict | None, *keys, default: list | None = None) -> list:
    """phase1 dict 안전 추출."""
    if d is None:
        return default or []
    cur: Any = d
    for k in keys:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return default or []
    if isinstance(cur, (list, tuple, np.ndarray)):
        return list(cur)
    return default or []


def compute_carrier_quartet(phase1_outputs: dict | None) -> dict:
    """4 추정치 (decades/gungs/horizontal/prime_composite). phase1 미제공 시 0."""
    out = {
        "from_decades": 0.0,
        "from_gungs": 0.0,
        "from_horizontal": 0.0,
        "from_prime_composite": 0.0,
    }
    if phase1_outputs is None:
        return out

    # decades 5D: [1-9, 10-19, 20-29, 30-39, 40-45]
    decade = phase1_outputs.get("decade_distribution")
    if decade is None:
        decade = phase1_outputs.get("expected_decade_dist")
    if isinstance(decade, dict):
        labels = ["1-9", "10-19", "20-29", "30-39", "40-45"]
        d_expected = []
        for lab in labels:
            entry = decade.get(lab) or decade.get("per_category", {}).get(lab, {})
            if isinstance(entry, dict):
                d_expected.append(float(entry.get("expected_count", 0.0)))
            else:
                d_expected.append(float(entry) if entry is not None else 0.0)
    elif isinstance(decade, (list, tuple, np.ndarray)):
        d_expected = [float(x) for x in decade][:5]
        while len(d_expected) < 5:
            d_expected.append(0.0)
    else:
        d_expected = [0.0] * 5
    d_means = [5.0, 14.5, 24.5, 34.5, 42.5]
    out["from_decades"] = float(sum(m * e for m, e in zip(d_means, d_expected)))

    # 9궁: [1-5,6-10,11-15,16-20,21-25,26-30,31-35,36-40,41-45]
    gung = phase1_outputs.get("gung_distribution")
    if isinstance(gung, dict):
        keys9 = ["1-5", "6-10", "11-15", "16-20", "21-25", "26-30", "31-35", "36-40", "41-45"]
        g_expected = []
        for k in keys9:
            entry = gung.get(k) or gung.get("per_category", {}).get(k, {})
            if isinstance(entry, dict):
                g_expected.append(float(entry.get("expected_count", 0.0)))
            else:
                g_expected.append(float(entry) if entry is not None else 0.0)
    elif isinstance(gung, (list, tuple, np.ndarray)):
        g_expected = [float(x) for x in gung][:9]
        while len(g_expected) < 9:
            g_expected.append(0.0)
    else:
        g_expected = [0.0] * 9
    g_means = [3.0, 8.0, 13.0, 18.0, 23.0, 28.0, 33.0, 38.0, 43.0]
    out["from_gungs"] = float(sum(m * e for m, e in zip(g_means, g_expected)))

    # horizontal: 5×9 grid 행 평균
    horiz = phase1_outputs.get("horizontal_distribution")
    if horiz is None:
        horiz = phase1_outputs.get("lotto_paper_distribution")
    if isinstance(horiz, (list, tuple, np.ndarray)):
        h_expected = [float(x) for x in horiz][:5]
        while len(h_expected) < 5:
            h_expected.append(0.0)
    elif isinstance(horiz, dict):
        h_expected = [float(horiz.get(f"row_{i}", 0.0)) for i in range(5)]
    else:
        h_expected = [0.0] * 5
    h_means = [4.0, 13.0, 22.0, 31.0, 40.0]
    out["from_horizontal"] = float(sum(m * e for m, e in zip(h_means, h_expected)))

    # prime/composite/one
    prime = float(phase1_outputs.get("expected_prime_count", 0.0) or 0.0)
    composite = float(phase1_outputs.get("expected_composite_count", 0.0) or 0.0)
    one = float(phase1_outputs.get("expected_one_count", 0.0) or 0.0)
    out["from_prime_composite"] = 19.43 * prime + 25.40 * composite + 1.0 * one

    return out


# ────────────────── SumPredictor 본체 ──────────────────


class SumPredictor:
    """Phase 4 predictor. 총합 quantile 회귀 + 카르텟 + N-BEATS 분해."""

    DEFAULT_MODELS = ("xgboost", "tft", "nbeats", "markov6", "bayesian", "autoencoder", "gnn")

    def __init__(
        self,
        feature_dim: int = 24,
        active_models: tuple[str, ...] | None = None,
    ) -> None:
        self.feature_dim = int(feature_dim)
        self.active_models = active_models or self.DEFAULT_MODELS

        self.xgb_q10: Any = None
        self.xgb_q50: Any = None
        self.xgb_q90: Any = None
        self.tft_model: Any = None
        self.nbeats_model: Any = None
        self.markov6: _SumMarkov6 | None = None
        self.bayes_model: Any = None
        self.ae_model: Any = None

        self._feature_names: list[str] | None = None
        self._train_sum: np.ndarray | None = None
        self._is_trained = False

    # ────── 시계열 추출 ──────

    def _extract_series(self, draws: list[dict]) -> np.ndarray:
        ordered = sorted(draws, key=lambda d: int(d.get("round", 0)))
        sums = [sum(int(n) for n in d.get("numbers", [])) for d in ordered]
        return np.array(sums, dtype=np.float64)

    # ────── feature ──────

    def _build_features_at(
        self,
        sum_history: np.ndarray,
        phase1_outputs: dict | None = None,
        phase2_endings: dict | None = None,
        phase3_ac: dict | None = None,
    ) -> dict:
        """단일 시점 feature dict (24 scalar + cross-feedback)."""
        feats = build_scalar_features(sum_history, SCALAR_CFG)

        # cross-feedback: phase2 endings_sum
        if phase2_endings is not None:
            scalar = phase2_endings.get("scalar", {}) or {}
            q10 = float(scalar.get("q10", 18.0) or 18.0)
            q50 = float(scalar.get("q50", 22.5) or 22.5)
            q90 = float(scalar.get("q90", 27.0) or 27.0)
            feats["cf_p2_endings_q50"] = q50
            feats["cf_p2_endings_iqr"] = q90 - q10
        else:
            feats["cf_p2_endings_q50"] = 22.5
            feats["cf_p2_endings_iqr"] = 9.0

        # cross-feedback: phase1 high_count, decade
        if phase1_outputs is not None:
            feats["cf_p1_high_count_expected"] = float(
                phase1_outputs.get("expected_high_count", 3.0) or 3.0
            )
            feats["cf_p1_high_count_extreme"] = float(
                phase1_outputs.get("high_count_extremity", 0.0) or 0.0
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
            feats["cf_p1_high_count_extreme"] = 0.0
            for i in range(5):
                feats[f"cf_p1_decade_{i}"] = 0.0

        # cross-feedback: phase3 ac
        if phase3_ac is not None:
            q10 = float(phase3_ac.get("q10", 5.0) or 5.0)
            q50 = float(phase3_ac.get("q50", 7.0) or 7.0)
            q90 = float(phase3_ac.get("q90", 9.0) or 9.0)
            feats["cf_p3_ac_q50"] = q50
            feats["cf_p3_ac_iqr"] = q90 - q10
        else:
            feats["cf_p3_ac_q50"] = 7.0
            feats["cf_p3_ac_iqr"] = 4.0

        return feats

    def _build_training_matrix(
        self,
        sum_series: np.ndarray,
        min_history: int = 20,
        phase1_outputs: dict | None = None,
        phase2_endings: dict | None = None,
        phase3_ac: dict | None = None,
    ) -> tuple[np.ndarray, np.ndarray, list[str]]:
        rows = []
        names = None
        for i in range(min_history, len(sum_series)):
            feats = self._build_features_at(
                sum_series[:i],
                phase1_outputs=phase1_outputs,
                phase2_endings=phase2_endings,
                phase3_ac=phase3_ac,
            )
            if names is None:
                names = sorted(feats.keys())
            rows.append([feats[k] for k in names])
        if not rows:
            return np.zeros((0, 0)), np.zeros((0,)), names or []
        X = np.array(rows, dtype=np.float64)
        y = sum_series[min_history:]
        return X, y, names or []

    # ────── 학습 ──────

    def train(
        self,
        draws: list[dict],
        phase1_outputs: dict | None = None,
        phase2_endings: dict | None = None,
        phase3_ac: dict | None = None,
        min_history: int = 20,
        bayes_epochs: int = 30,
    ) -> dict:
        if not draws:
            raise ValueError("empty draws")

        sum_series = self._extract_series(draws)
        if len(sum_series) < min_history + 5:
            raise ValueError(
                f"insufficient draws: got {len(sum_series)} need >= {min_history + 5}"
            )

        self._train_sum = sum_series.copy()

        X, y, names = self._build_training_matrix(
            sum_series, min_history=min_history,
            phase1_outputs=phase1_outputs,
            phase2_endings=phase2_endings,
            phase3_ac=phase3_ac,
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
                print(f"  [sum] xgboost train fail: {e}")
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
                print(f"  [sum] tft train fail: {e}")
                self.tft_model = None

        # ── N-BEATS (분해 head) ──
        if "nbeats" in self.active_models and NBEATS_AVAIL:
            try:
                self.nbeats_model = LottoNBeats(seq_length=min(50, len(sum_series) // 3))
                self.nbeats_model.train(sum_series.astype(np.float32))
                history["trained_models"].append("nbeats")
            except Exception as e:
                print(f"  [sum] nbeats train fail: {e}")
                self.nbeats_model = None

        # ── Markov 6-bucket ──
        if "markov6" in self.active_models:
            self.markov6 = _SumMarkov6()
            self.markov6.fit(sum_series)
            history["trained_models"].append("markov6")

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
                print(f"  [sum] bayesian train fail: {e}")
                self.bayes_model = None

        # ── Autoencoder 게이트 (이상 회차 감지) ──
        if "autoencoder" in self.active_models and AE_AVAIL:
            try:
                self.ae_model = LottoAutoencoder(input_dim=self.feature_dim)
                self.ae_model.train(X.astype(np.float32), max_epochs=20)
                history["trained_models"].append("autoencoder")
            except Exception as e:
                print(f"  [sum] autoencoder train fail: {e}")
                self.ae_model = None

        self._is_trained = True
        history["feature_dim"] = self.feature_dim
        return history

    # ────── 추론 ──────

    def predict(
        self,
        draws_so_far: list[dict],
        phase1_outputs: dict | None = None,
        phase2_endings: dict | None = None,
        phase3_ac: dict | None = None,
        min_history: int = 20,
    ) -> dict:
        if not self._is_trained:
            return self._baseline_payload(phase1_outputs)
        if not draws_so_far:
            return self._baseline_payload(phase1_outputs)

        sum_series = self._extract_series(draws_so_far)
        if len(sum_series) < min_history:
            return self._baseline_payload(phase1_outputs)

        feats = self._build_features_at(
            sum_series, phase1_outputs=phase1_outputs,
            phase2_endings=phase2_endings, phase3_ac=phase3_ac,
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

        # N-BEATS: 분해 + 점예측 (SLA 측정 추가 — model_latency_log 누락 방지)
        nbeats_pred = None
        nbeats_decomp = {"trend": None, "seasonality": None, "residual": None}
        if self.nbeats_model is not None:
            try:
                # [신규] SLAMonitor로 nbeats predict 측정 → sla_history.parquet 기록
                try:
                    from pipeline.sla_monitor import SLAMonitor
                    with SLAMonitor("ensemble_nbeats_predict"):
                        pred = self.nbeats_model.predict(sum_series.astype(np.float32), steps=1)
                except ImportError:
                    pred = self.nbeats_model.predict(sum_series.astype(np.float32), steps=1)
                nbeats_pred = float(pred[0]) if len(pred) > 0 else None
                if nbeats_pred is not None:
                    q50s.append(nbeats_pred)
                try:
                    dec = self.nbeats_model.decompose(sum_series.astype(np.float32))
                    nbeats_decomp = {
                        "trend": float(dec["trend"][-1]) if dec.get("trend") is not None and len(dec["trend"]) > 0 else None,
                        "seasonality": float(dec["seasonality"][-1]) if dec.get("seasonality") is not None and len(dec["seasonality"]) > 0 else None,
                        "residual": float(dec["residual"][-1]) if dec.get("residual") is not None and len(dec["residual"]) > 0 else None,
                    }
                except Exception:
                    pass
            except Exception:
                pass

        # Markov 6-bucket
        markov_expected = None
        if self.markov6 is not None:
            markov_expected = self.markov6.expected_value(float(sum_series[-1]))
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

        # GNN aggregation
        gnn_sum = None
        if phase1_outputs is not None:
            gnn_probs = phase1_outputs.get("gnn_probs45")
            if gnn_probs is not None:
                try:
                    gnn_sum = float(aggregate_sum(np.asarray(gnn_probs)))
                    q50s.append(gnn_sum)
                except Exception:
                    pass

        if not q50s:
            last = float(sum_series[-1])
            q10_final = last - 30.0
            q50_final = last
            q90_final = last + 30.0
        else:
            q10_final = float(np.mean(q10s)) if q10s else (np.mean(q50s) - 30.0)
            q50_final = float(np.mean(q50s))
            q90_final = float(np.mean(q90s)) if q90s else (np.mean(q50s) + 30.0)

        # ── 카르텟 ──
        carrier = compute_carrier_quartet(phase1_outputs)
        c_values = list(carrier.values())
        # carrier_consistency: 0 인 값 (phase1 없음) 무시한 표준편차
        nonzero = [v for v in c_values if v > 1e-6]
        if len(nonzero) >= 2:
            carrier_consistency = float(np.std(nonzero))
        else:
            carrier_consistency = 0.0

        # AE 게이트 (이상 회차)
        anomaly_score = None
        if self.ae_model is not None:
            try:
                if hasattr(self.ae_model, "anomaly_score"):
                    anomaly_score = float(self.ae_model.anomaly_score(x_query)[0])
                elif hasattr(self.ae_model, "predict"):
                    rec = self.ae_model.predict(x_query)
                    anomaly_score = float(np.mean((np.asarray(rec) - x_query) ** 2))
            except Exception:
                pass

        # narrative
        iqr = q90_final - q10_final
        narrative = (
            f"Sum ~ {q50_final:.0f} +/- {iqr/2:.0f} (q50={q50_final:.0f}, IQR={iqr:.0f}), "
            f"carrier_consistency_sigma={carrier_consistency:.2f}"
        )
        if nbeats_decomp.get("trend") is not None:
            narrative += f", nbeats_trend={nbeats_decomp['trend']:.1f}"
        if bayes_sigma is not None:
            narrative += f", bayes_sigma={bayes_sigma:.2f}"
        if anomaly_score is not None:
            narrative += f", AE_anomaly={anomaly_score:.3f}"

        return {
            "q10": q10_final,
            "q50": q50_final,
            "q90": q90_final,
            "carrier_quartet": carrier,
            "carrier_consistency": carrier_consistency,
            "nbeats_decomposition": nbeats_decomp,
            "narrative": narrative,
            "components": {
                "markov_expected": markov_expected,
                "nbeats_pred": nbeats_pred,
                "gnn_sum": gnn_sum,
                "bayes_sigma": bayes_sigma,
                "anomaly_score": anomaly_score,
            },
        }

    def _baseline_payload(self, phase1_outputs: dict | None = None) -> dict:
        carrier = compute_carrier_quartet(phase1_outputs)
        return {
            "q10": 110.0,
            "q50": 138.0,
            "q90": 165.0,
            "carrier_quartet": carrier,
            "carrier_consistency": 0.0,
            "nbeats_decomposition": {"trend": None, "seasonality": None, "residual": None},
            "narrative": "Sum not trained, prior 138 +/- 30",
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
            "train_sum": self._train_sum,
        }
        with open(path, "wb") as f:
            pickle.dump(meta, f)

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
        self._feature_names = meta.get("feature_names")
        self._is_trained = bool(meta.get("is_trained", False))
        self._train_sum = meta.get("train_sum")

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


def _generate_fake_phase_inputs(seed: int = config.RANDOM_SEED) -> tuple[dict, dict, dict]:
    rng = np.random.default_rng(seed)
    gnn_probs = rng.dirichlet(np.ones(45)).astype(np.float32)
    p1 = {
        "gnn_probs45": gnn_probs,
        "expected_high_count": float(rng.uniform(2.5, 3.5)),
        "high_count_extremity": float(rng.uniform(0.0, 1.0)),
        "decade_distribution": (rng.dirichlet(np.ones(5)) * 6.0).tolist(),
        "expected_decade_dist": (rng.dirichlet(np.ones(5)) * 6.0).tolist(),
        "gung_distribution": (rng.dirichlet(np.ones(9)) * 6.0).tolist(),
        "horizontal_distribution": (rng.dirichlet(np.ones(5)) * 6.0).tolist(),
        "expected_prime_count": float(rng.uniform(1.5, 2.5)),
        "expected_composite_count": float(rng.uniform(2.5, 3.5)),
        "expected_one_count": float(rng.uniform(0.0, 0.3)),
    }
    p2 = {
        "scalar": {
            "q10": float(rng.uniform(15, 20)),
            "q50": float(rng.uniform(20, 26)),
            "q90": float(rng.uniform(26, 32)),
        }
    }
    p3 = {
        "q10": float(rng.uniform(4, 6)),
        "q50": float(rng.uniform(6, 8)),
        "q90": float(rng.uniform(8, 10)),
    }
    return p1, p2, p3


def main() -> None:
    """python -m predictors.sum_predictor --smoke."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()

    if not args.smoke:
        return

    print("[sum] generating 100 fake draws...")
    draws = _generate_fake_draws(100)
    p1, p2, p3 = _generate_fake_phase_inputs()

    pred = SumPredictor(active_models=("xgboost", "markov6", "bayesian", "gnn"))
    print("[sum] training...")
    info = pred.train(
        draws, phase1_outputs=p1, phase2_endings=p2, phase3_ac=p3,
        min_history=20, bayes_epochs=10,
    )
    print(f"  trained models: {info['trained_models']}")
    print(f"  feature_dim: {info['feature_dim']}, n_train_rows: {info['n_train_rows']}")

    print("\n[sum] predicting next round...")
    out = pred.predict(draws, phase1_outputs=p1, phase2_endings=p2, phase3_ac=p3, min_history=20)
    print(f"  q10={out['q10']:.1f}, q50={out['q50']:.1f}, q90={out['q90']:.1f}")
    cq = out["carrier_quartet"]
    print(f"  carrier_quartet:")
    for k, v in cq.items():
        print(f"    {k:25s} = {v:.2f}")
    print(f"  carrier_consistency_sigma = {out['carrier_consistency']:.3f}")
    nb = out["nbeats_decomposition"]
    print(f"  nbeats_decomposition: trend={nb.get('trend')}, season={nb.get('seasonality')}, residual={nb.get('residual')}")
    print(f"  narrative: {out['narrative']}")


if __name__ == "__main__":
    main()
