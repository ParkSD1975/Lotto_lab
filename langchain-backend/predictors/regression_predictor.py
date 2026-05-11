"""Stage 2 Tier 1 — DynamicIndependentCountPredictor.

회귀 N 정의 (Master Plan Stage 2):
  - 직전 N회차 본번호 풀(unique)과 현 회차 본번호(6개)의 교집합 크기
  - 회귀 1: 직전 1회차 본번호와 겹치는 수 (이월수)
  - 회귀 2~200: 직전 N회차 본번호 unique 풀과 겹치는 수
  - 본번호 6개만 사용 (보너스 제외)

활성 N: 과거 회차에서 의미 있는 패턴 발생 (sample >= 10) N 값 (매 회차 16~30개 동적)
신뢰 N: sample >= 50, XGBoost + CatBoost + Markov 통합
Sparse N: sample < 50, 빈도 + Bayesian uncertainty

11 base 중 가벼운 모델 (XGBoost / CatBoost / Markov) 한정.
"""

from __future__ import annotations

import os
import pickle
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

import config


# 회귀 기본 파라미터 (config에 설정 없으면 본 default 사용)
_REGRESSION_N_RANGE: tuple[int, int] = getattr(config, "REGRESSION_N_RANGE", (1, 200))
_REGRESSION_SAMPLE_THRESHOLD: int = getattr(config, "REGRESSION_SAMPLE_THRESHOLD", 50)
_REGRESSION_N_CLASSES: int = 7  # 0~6 count (본번호 6개 매칭 최대 6)


# ────────────────── 데이터 클래스 ──────────────────


@dataclass
class _NHead:
    """단일 N에 대한 헤드. 신뢰 N은 model 보유, sparse N은 prior만."""

    N: int
    n_classes: int = _REGRESSION_N_CLASSES
    sample_count: int = 0
    is_reliable: bool = False
    prior: np.ndarray = field(default_factory=lambda: np.ones(_REGRESSION_N_CLASSES) / _REGRESSION_N_CLASSES)
    base_models: dict = field(default_factory=dict)  # {model_name: estimator}


# ────────────────── 풀/카운트 추출 유틸 ──────────────────


def _draw_main_numbers(d: dict) -> set[int]:
    """단일 회차 본번호 6개만 (보너스 제외). Stage 2 회귀 정의."""
    nums: set[int] = set()
    for n in d.get("numbers", []):
        try:
            nums.add(int(n))
        except (TypeError, ValueError):
            continue
    return nums


def _ordered_draws(draws: list[dict]) -> list[dict]:
    """draws (최신순/시간순 모두 허용) → 시간순 정렬."""
    return sorted(draws, key=lambda d: int(d.get("round", 0)))


def _round_idx_map(ordered: list[dict]) -> dict[int, int]:
    """round 번호 → ordered list 인덱스."""
    return {int(d.get("round", 0)): i for i, d in enumerate(ordered)}


# ────────────────── 활성 N + 회귀 카운트 ──────────────────


def compute_active_n(
    target_round: int,
    draws: list[dict],
    n_range: tuple[int, int] = _REGRESSION_N_RANGE,
) -> dict[int, list[int]]:
    """target_round의 활성 N 식별. {N: pool_members_list (1명 이상 회귀한 멤버)}.

    활성 정의: N회 전 풀 멤버 중 1명 이상이 target_round 본 회차에 등장한 N.
    """
    ordered = _ordered_draws(draws)
    idx_map = _round_idx_map(ordered)
    if target_round not in idx_map:
        return {}
    t_idx = idx_map[target_round]
    target_pool = _draw_main_numbers(ordered[t_idx])

    n_min, n_max = int(n_range[0]), int(n_range[1])
    active: dict[int, list[int]] = {}
    for N in range(n_min, n_max + 1):
        prev_idx = t_idx - N
        if prev_idx < 0:
            continue
        prev_pool = _draw_main_numbers(ordered[prev_idx])
        overlap = sorted(prev_pool & target_pool)
        if overlap:
            active[N] = overlap
    return active


def compute_pool_size_for_n(
    target_round: int,
    draws: list[dict],
    N: int,
) -> int:
    """N회 전 풀 사이즈 = 통상 7. 데이터 결손 시 0."""
    ordered = _ordered_draws(draws)
    idx_map = _round_idx_map(ordered)
    if target_round not in idx_map:
        return 0
    t_idx = idx_map[target_round]
    prev_idx = t_idx - N
    if prev_idx < 0:
        return 0
    return len(_draw_main_numbers(ordered[prev_idx]))


def _count_regression_at(
    ordered: list[dict],
    t_idx: int,
    N: int,
) -> Optional[int]:
    """ordered[t_idx]의 N 회귀 카운트. 데이터 결손이면 None."""
    prev_idx = t_idx - N
    if prev_idx < 0:
        return None
    target_pool = _draw_main_numbers(ordered[t_idx])
    prev_pool = _draw_main_numbers(ordered[prev_idx])
    return len(target_pool & prev_pool)


# ────────────────── 가벼운 base wrapper ──────────────────


class _MarkovHead:
    """N별 8-state 전이행렬. count_t -> count_{t+1}."""

    def __init__(self, n_classes: int = _REGRESSION_N_CLASSES) -> None:
        self.n_classes = n_classes
        self.transition = np.full((n_classes, n_classes), 1.0 / n_classes)
        self.last_count = 0

    def fit(self, sequence: np.ndarray) -> None:
        if len(sequence) < 2:
            return
        T = np.zeros((self.n_classes, self.n_classes), dtype=np.float64)
        for i in range(len(sequence) - 1):
            a = int(sequence[i])
            b = int(sequence[i + 1])
            if 0 <= a < self.n_classes and 0 <= b < self.n_classes:
                T[a, b] += 1
        T += 1.0  # Laplace
        T = T / T.sum(axis=1, keepdims=True)
        self.transition = T
        self.last_count = int(sequence[-1]) if len(sequence) else 0

    def predict_proba(self) -> np.ndarray:
        c = max(0, min(self.last_count, self.n_classes - 1))
        return self.transition[c].copy()


def _instantiate_xgb(n_classes: int):
    try:
        import xgboost as xgb

        return xgb.XGBClassifier(
            objective="multi:softprob",
            num_class=n_classes,
            n_estimators=getattr(config, "XGB_N_ESTIMATORS", 200),
            max_depth=getattr(config, "XGB_MAX_DEPTH", 6),
            learning_rate=getattr(config, "XGB_LEARNING_RATE", 0.05),
            random_state=config.RANDOM_SEED,
            eval_metric="mlogloss",
            verbosity=0,
        )
    except ImportError:
        return None


def _instantiate_bayes(input_dim: int, n_classes: int):
    try:
        from models.bayesian_nn_model import LottoBayesianNN

        return LottoBayesianNN(
            input_dim=input_dim,
            num_classes=n_classes,
            mc_samples=10,
            task_type="multiclass",
        )
    except ImportError:
        return None
    except Exception:
        return None


# ────────────────── feature 빌더 (per-N) ──────────────────


def _build_n_features(
    history_counts: np.ndarray,
    pool_size: int,
    dormancy: int,
    feature_dim: int,
) -> np.ndarray:
    """N별 단일 시점 feature vector. shape (feature_dim,).

    구성: lag_1~5 / rolling_mean_5/10/20 / rolling_std_5/10 /
          dormancy / pool_size / sum_recent_5 / max_recent_10 / N_active_ratio_20 / pad
    """
    feats: list[float] = []
    history_counts = np.asarray(history_counts, dtype=np.float64)

    # lag 1~5
    for lag in (1, 2, 3, 5, 7):
        feats.append(float(history_counts[-lag]) if len(history_counts) >= lag else 0.0)

    # rolling mean 5/10/20
    for w in (5, 10, 20):
        if len(history_counts) >= w:
            feats.append(float(history_counts[-w:].mean()))
        else:
            feats.append(float(history_counts.mean()) if len(history_counts) > 0 else 0.0)

    # rolling std 5/10
    for w in (5, 10):
        if len(history_counts) >= w:
            feats.append(float(history_counts[-w:].std()))
        else:
            feats.append(0.0)

    feats.append(float(dormancy))
    feats.append(float(pool_size))

    # sum_recent_5
    feats.append(float(history_counts[-5:].sum()) if len(history_counts) >= 5 else float(history_counts.sum()))
    # max_recent_10
    feats.append(float(history_counts[-10:].max()) if len(history_counts) >= 10 else 0.0)
    # active ratio (last 20)
    if len(history_counts) >= 20:
        feats.append(float((history_counts[-20:] > 0).mean()))
    else:
        feats.append(float((history_counts > 0).mean()) if len(history_counts) > 0 else 0.0)

    # zero-pad to feature_dim
    while len(feats) < feature_dim:
        feats.append(0.0)
    return np.asarray(feats[:feature_dim], dtype=np.float32)


# ────────────────── 메인 클래스 ──────────────────


class DynamicIndependentCountPredictor:
    """가변 카테고리 ICP. 매 회차 활성 N 16~30개에 대해 7-class 분포 산출."""

    DEFAULT_BASE_MODELS = ("xgboost", "markov", "bayesian_nn")

    def __init__(
        self,
        feature_dim: int = 24,
        sample_threshold: int = _REGRESSION_SAMPLE_THRESHOLD,
        n_range: tuple[int, int] = _REGRESSION_N_RANGE,
        active_models: Optional[tuple[str, ...]] = None,
        n_classes: int = _REGRESSION_N_CLASSES,
    ) -> None:
        self.feature_dim = int(feature_dim)
        self.sample_threshold = int(sample_threshold)
        self.n_range = (int(n_range[0]), int(n_range[1]))
        self.active_models = active_models or self.DEFAULT_BASE_MODELS
        self.n_classes = int(n_classes)

        self.heads: dict[int, _NHead] = {}
        self._is_trained = False
        self._train_history_size = 0  # train 시점에 사용된 ordered 길이

    # ────── 활성 N 노출 (외부 API) ──────

    def compute_active_n(
        self,
        target_round: int,
        draws: list[dict],
        n_range: Optional[tuple[int, int]] = None,
    ) -> dict[int, list[int]]:
        """공개 wrapper. {N: overlap_members}."""
        rng = n_range or self.n_range
        return compute_active_n(target_round, draws, rng)

    # ────── 학습 ──────

    def train(self, draws: list[dict]) -> dict:
        """walk-forward 매트릭스 빌드 + 신뢰 N 학습.

        Returns: dict (학습 통계).
        """
        ordered = _ordered_draws(draws)
        T = len(ordered)
        if T < 30:
            raise ValueError(f"insufficient draws for regression train: T={T}")

        n_min, n_max = self.n_range

        # 각 N별 (t_idx, count) 시계열 구성
        n_series: dict[int, list[tuple[int, int]]] = {}
        for N in range(n_min, n_max + 1):
            series: list[tuple[int, int]] = []
            for t in range(N, T):
                c = _count_regression_at(ordered, t, N)
                if c is None:
                    continue
                series.append((t, int(c)))
            if series:
                n_series[N] = series

        history: dict[str, object] = {
            "n_total_candidates": len(n_series),
            "trained_n": [],
            "fallback_n": [],
            "per_N_sample_count": {},
        }

        # 각 N별 학습 또는 fallback 구성
        for N, series in n_series.items():
            sample_count = len(series)
            head = _NHead(N=N, n_classes=self.n_classes, sample_count=sample_count)
            history["per_N_sample_count"][N] = sample_count

            counts_arr = np.asarray([c for _, c in series], dtype=np.int64)
            counts_arr = np.clip(counts_arr, 0, self.n_classes - 1)

            # prior (빈도 베이스라인)
            bins = np.bincount(counts_arr, minlength=self.n_classes).astype(np.float64)
            bins += 1.0  # Laplace
            head.prior = bins / bins.sum()

            if sample_count >= self.sample_threshold:
                # 신뢰 N — feature 매트릭스 구성 후 학습
                head.is_reliable = True
                X_rows: list[np.ndarray] = []
                Y_rows: list[int] = []
                history_seq: list[int] = []  # 누적 카운트 시계열 (t_idx 기준 미연속 — 0 패딩)
                # 누적 카운트 시계열을 dense 시간축(0..T)으로 빌드
                dense = np.zeros(T, dtype=np.float32)
                for t, c in series:
                    dense[t] = float(c)

                # walk-forward feature 빌드
                last_active_t = -1
                for t, c in series:
                    sub = dense[:t]
                    dormancy = (t - last_active_t - 1) if last_active_t >= 0 else min(t, 100)
                    pool_size = compute_pool_size_for_n(int(ordered[t].get("round", t)), ordered, N)
                    vec = _build_n_features(sub, pool_size, dormancy, self.feature_dim)
                    X_rows.append(vec)
                    Y_rows.append(int(c))
                    if c > 0:
                        last_active_t = t

                X = np.stack(X_rows, axis=0).astype(np.float32)
                Y = np.asarray(Y_rows, dtype=np.int64)

                # 모든 클래스 등장 보정 (xgboost label encoder 안정화)
                missing = [c for c in range(self.n_classes) if c not in set(Y.tolist())]
                if missing:
                    mean_row = X.mean(axis=0, keepdims=True)
                    pad_X = np.repeat(mean_row, len(missing), axis=0)
                    pad_Y = np.asarray(missing, dtype=np.int64)
                    X = np.concatenate([pad_X, X], axis=0)
                    Y = np.concatenate([pad_Y, Y], axis=0)

                # base 모델 학습
                for name in self.active_models:
                    try:
                        if name == "xgboost":
                            mdl = _instantiate_xgb(self.n_classes)
                            if mdl is None:
                                continue
                            mdl.fit(X, Y)
                            head.base_models[name] = mdl
                        elif name == "markov":
                            mk = _MarkovHead(self.n_classes)
                            mk.fit(counts_arr)
                            head.base_models[name] = mk
                        elif name == "bayesian_nn":
                            mdl = _instantiate_bayes(self.feature_dim, self.n_classes)
                            if mdl is None:
                                continue
                            mdl.train(X, Y)
                            head.base_models[name] = mdl
                    except Exception as e:
                        # 단일 N의 단일 모델 실패는 silent skip
                        print(f"  [DICP] N={N} {name} train fail: {type(e).__name__}: {str(e)[:80]}")

                if head.base_models:
                    history["trained_n"].append(int(N))
                else:
                    head.is_reliable = False
                    history["fallback_n"].append(int(N))
            else:
                # sparse N — prior fallback만 사용
                head.is_reliable = False
                history["fallback_n"].append(int(N))

            self.heads[int(N)] = head

        self._is_trained = True
        self._train_history_size = T
        return history

    # ────── 추론 ──────

    def predict(self, draws_so_far: list[dict], target_round: int | None = None) -> dict:
        """target_round에 대한 활성 N별 분포 산출. predictor 표준 출력 형식.

        Args:
            draws_so_far: target_round 미만 회차 리스트
            target_round: 예측 대상 회차 (None이면 draws_so_far 마지막 + 1)

        Returns:
          {
            "per_n": {
                N: {
                    "absolute_dist": [P(0)~P(6)],
                    "expected_count": E,
                    "regression_pool_size": M,
                    "expected_ratio": E / M,
                    "narrative": "...",
                    "confidence": "high|low",
                    "sample_size": int,
                    "model_contributions": {model_name: weight},
                },
                ...
            },
            "active_n_count": int,
            "dense_n_count": int,
            "aggregated_expected": float,
          }
        """
        if not draws_so_far:
            return self._empty_payload()

        ordered = _ordered_draws(draws_so_far)
        T = len(ordered)
        if T < 2:
            return self._empty_payload()

        # target_round 결정
        latest_round = int(ordered[-1].get("round", 0))
        if target_round is None:
            target_round_val = latest_round + 1
        else:
            target_round_val = int(target_round)

        # 활성 N 식별 (historical 회차 중 활성 N 패턴 10회 이상인 N)
        n_min, n_max = self.n_range
        active_set: list[int] = []
        for N in range(n_min, min(n_max + 1, T)):
            # N회 전 데이터가 있는지 확인
            if T < N:
                continue
            # 과거 회차 중 N 활성 패턴 샘플 수
            count_samples = 0
            for t in range(N, T):
                prev_idx = t - N
                if prev_idx >= 0:
                    count_samples += 1
            # 최소 10 샘플 이상이면 활성
            if count_samples >= 10:
                active_set.append(N)

        per_n: dict[int, dict] = {}
        expected_list: list[float] = []
        dense_count = 0

        # 각 활성 N별 예측
        for N in active_set:
            head = self.heads.get(N)

            # 회귀 풀 크기 (직전 N회차 unique 본번호)
            pool: set[int] = set()
            for i in range(min(N, T)):
                pool.update(_draw_main_numbers(ordered[T - 1 - i]))
            pool_size = len(pool)

            # 누적 카운트 시계열
            dense = np.zeros(T, dtype=np.float32)
            for t in range(N, T):
                c = _count_regression_at(ordered, t, N)
                if c is not None:
                    dense[t] = float(min(c, 6))  # 0~6 clipping

            count_hist = dense[dense > 0] if (dense > 0).any() else dense[N:]
            sample_size = int((dense[N:] >= 0).sum())  # N 이후 모든 회차

            # dormancy
            active_idx = np.where(dense > 0)[0]
            dormancy = T - 1 - int(active_idx[-1]) if len(active_idx) > 0 else T

            # 학습 안 된 N → uniform prior
            if head is None:
                dist = np.full(self.n_classes, 1.0 / self.n_classes)
                expected = float(np.sum(dist * np.arange(self.n_classes)))
                per_n[N] = {
                    "absolute_dist": dist.tolist(),
                    "expected_count": expected,
                    "regression_pool_size": pool_size,
                    "expected_ratio": expected / max(pool_size, 1),
                    "narrative": f"회귀 N={N} 풀 {pool_size}개 중 {expected:.1f}개 매칭 가능성 (prior)",
                    "confidence": "low",
                    "sample_size": sample_size,
                }
                expected_list.append(expected)
                continue

            # feature 벡터
            vec = _build_n_features(dense[:T], pool_size, dormancy, self.feature_dim)

            # base 모델 앙상블
            probs_list: list[np.ndarray] = []
            model_weights: dict[str, float] = {}

            if head.is_reliable and head.base_models:
                for name, mdl in head.base_models.items():
                    p = self._model_proba(name, mdl, vec)
                    if p is not None:
                        probs_list.append(self._normalize_prob_shape(p))
                        model_weights[name] = 1.0 / len(head.base_models)

            if probs_list:
                avg = np.mean(np.stack(probs_list, axis=0), axis=0)
                if avg.sum() > 0:
                    avg = avg / avg.sum()
                else:
                    avg = head.prior.copy()
                confidence = "high"
                if head.is_reliable:
                    dense_count += 1
            else:
                avg = head.prior.copy()
                confidence = "low"
                model_weights = {"frequency": 1.0}

            expected = float(np.sum(avg * np.arange(self.n_classes)))

            per_n[N] = {
                "absolute_dist": avg.tolist(),
                "expected_count": expected,
                "regression_pool_size": pool_size,
                "expected_ratio": expected / max(pool_size, 1),
                "narrative": (
                    f"회귀 N={N} 풀 {pool_size}개 중 {expected:.1f}개 매칭 가능성 "
                    f"({'신뢰도 높음' if confidence == 'high' else '신뢰도 낮음'}, sample={sample_size})"
                ),
                "confidence": confidence,
                "sample_size": sample_size,
                "model_contributions": model_weights,
            }
            expected_list.append(expected)

        return {
            "per_n": per_n,
            "active_n_count": len(active_set),
            "dense_n_count": dense_count,
            "aggregated_expected": float(np.mean(expected_list)) if expected_list else 0.0,
        }

    def _model_proba(self, name: str, mdl, vec: np.ndarray) -> Optional[np.ndarray]:
        try:
            if name == "markov":
                return mdl.predict_proba()
            if name == "xgboost":
                p = mdl.predict_proba(vec.reshape(1, -1))
                return np.asarray(p[0], dtype=np.float64)
            if name == "bayesian_nn":
                out = mdl.predict_with_uncertainty(vec.reshape(1, -1))
                m = out.get("mean")
                if m is None:
                    return None
                m = np.asarray(m, dtype=np.float64)
                if m.ndim > 1:
                    m = m[0]
                return m
        except Exception:
            return None
        return None

    def _normalize_prob_shape(self, p: np.ndarray) -> np.ndarray:
        """다양한 prob shape를 (n_classes,)로 정렬."""
        p = np.asarray(p, dtype=np.float64).flatten()
        if p.shape[0] == self.n_classes:
            return p
        if p.shape[0] < self.n_classes:
            padded = np.zeros(self.n_classes, dtype=np.float64)
            padded[: p.shape[0]] = p
            leftover = max(0.0, 1.0 - padded.sum())
            if self.n_classes - p.shape[0] > 0:
                padded[p.shape[0]:] = leftover / (self.n_classes - p.shape[0])
            return padded
        return p[: self.n_classes]

    def _empty_payload(self) -> dict:
        return {
            "per_n": {},
            "active_n_count": 0,
            "dense_n_count": 0,
            "aggregated_expected": 0.0,
        }

    # ────── persistence ──────

    def save(self, path: str) -> str:
        """헤드 메타+prior+markov만 pickle. xgboost/bayes는 메모리 안에서만."""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        data = {
            "feature_dim": self.feature_dim,
            "sample_threshold": self.sample_threshold,
            "n_range": list(self.n_range),
            "active_models": list(self.active_models),
            "n_classes": self.n_classes,
            "is_trained": self._is_trained,
            "train_history_size": self._train_history_size,
            "heads": {
                int(N): {
                    "N": int(h.N),
                    "n_classes": int(h.n_classes),
                    "sample_count": int(h.sample_count),
                    "is_reliable": bool(h.is_reliable),
                    "prior": h.prior.tolist(),
                    "trained_models": list(h.base_models.keys()),
                    # Markov 전이행렬은 plain numpy — pickle safe
                    "markov_transition": (
                        h.base_models["markov"].transition.tolist()
                        if "markov" in h.base_models
                        else None
                    ),
                    "markov_last_count": (
                        int(h.base_models["markov"].last_count)
                        if "markov" in h.base_models
                        else None
                    ),
                }
                for N, h in self.heads.items()
            },
        }
        with open(path, "wb") as f:
            pickle.dump(data, f)
        return path

    def load(self, path: str) -> None:
        with open(path, "rb") as f:
            data = pickle.load(f)
        self.feature_dim = int(data["feature_dim"])
        self.sample_threshold = int(data["sample_threshold"])
        self.n_range = tuple(data["n_range"])
        self.active_models = tuple(data["active_models"])
        self.n_classes = int(data["n_classes"])
        self._is_trained = bool(data["is_trained"])
        self._train_history_size = int(data.get("train_history_size", 0))
        self.heads = {}
        for N_str, hd in data["heads"].items():
            N = int(N_str)
            head = _NHead(
                N=N,
                n_classes=int(hd["n_classes"]),
                sample_count=int(hd["sample_count"]),
                is_reliable=bool(hd["is_reliable"]),
                prior=np.asarray(hd["prior"], dtype=np.float64),
            )
            mt = hd.get("markov_transition")
            if mt is not None:
                mk = _MarkovHead(self.n_classes)
                mk.transition = np.asarray(mt, dtype=np.float64)
                mk.last_count = int(hd.get("markov_last_count", 0))
                head.base_models["markov"] = mk
            self.heads[N] = head


# ────────────────── 가짜 데이터 + smoke ──────────────────


def _generate_fake_draws(n_rounds: int, seed: int = config.RANDOM_SEED) -> list[dict]:
    """smoke 용 가짜 lotto 회차. 회귀 발생도 자연스럽게 시뮬레이트."""
    rng = np.random.default_rng(seed)
    pool = np.arange(1, 46)
    draws: list[dict] = []
    for r in range(n_rounds):
        nums = sorted(rng.choice(pool, size=6, replace=False).tolist())
        bonus_pool = [int(n) for n in pool if n not in nums]
        bonus = int(rng.choice(bonus_pool))
        draws.append({"round": 1000 + r, "numbers": nums, "bonus": bonus})
    return draws


def main() -> None:
    """python -m predictors.regression_predictor --smoke | --target-round 1223 | --validate 50."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--rounds", type=int, default=200)
    parser.add_argument("--target-round", type=int, help="predict for target round (Supabase)")
    parser.add_argument("--validate", type=int, help="walk-forward validate last N rounds")
    args = parser.parse_args()

    # ──── target-round ────
    if args.target_round:
        from db.supabase_client import get_client

        print(f"[regression_predictor] target_round={args.target_round}")
        try:
            supabase = get_client()
            response = (
                supabase.table("lotto_draws")
                .select("round, numbers, bonus")
                .order("round", desc=False)
                .execute()
            )
            raw = response.data if hasattr(response, "data") else response
        except Exception as e:
            print(f"  [FAIL] supabase error: {e}")
            return

        if not raw:
            print("  [FAIL] no draws from supabase")
            return

        draws = []
        for r in raw:
            nums = r.get("numbers")
            if not nums or len(nums) != 6:
                continue
            draws.append(
                {
                    "round": r["round"],
                    "numbers": list(nums),
                    "bonus": r.get("bonus"),
                }
            )
        print(f"  loaded {len(draws)} draws")

        # 학습 (전체 데이터)
        predictor = DynamicIndependentCountPredictor(
            feature_dim=24,
            sample_threshold=50,
            n_range=(2, 200),
            active_models=("xgboost", "markov"),  # bayesian_nn은 선택적
        )
        print("  training...")
        history = predictor.train(draws)
        print(f"    candidates: {history['n_total_candidates']}")
        print(f"    trained N: {len(history['trained_n'])}")
        print(f"    fallback N: {len(history['fallback_n'])}")

        # 추론 (target_round 이전 회차만 사용)
        train_subset = [d for d in draws if int(d.get("round", 0)) < args.target_round]
        print(f"  predicting (train_subset={len(train_subset)} rounds)...")
        out = predictor.predict(train_subset, args.target_round)
        print(f"    active_n_count: {out['active_n_count']}")
        print(f"    dense_n_count: {out['dense_n_count']}")
        print(f"    aggregated_expected: {out['aggregated_expected']:.2f}")

        # 출력 예시 3~5개
        sample_N = sorted(out["per_n"].keys())[:5]
        print("\n  sample output (first 5 N):")
        for N in sample_N:
            res = out["per_n"][N]
            print(f"    N={N} (sample={res['sample_size']}, conf={res['confidence']})")
            print(f"      expected_count={res['expected_count']:.2f}")
            print(f"      expected_ratio={res['expected_ratio']:.3f}")
            print(f"      narrative={res['narrative']}")
            print(f"      model_contributions={res['model_contributions']}")
        return

    # ──── validate ────
    if args.validate:
        from db.supabase_client import get_client

        print(f"[regression_predictor] walk-forward validate last {args.validate} rounds")
        try:
            supabase = get_client()
            response = (
                supabase.table("lotto_draws")
                .select("round, numbers, bonus")
                .order("round", desc=False)
                .execute()
            )
            raw = response.data if hasattr(response, "data") else response
        except Exception as e:
            print(f"  [FAIL] supabase error: {e}")
            return

        draws = []
        for r in raw:
            nums = r.get("numbers")
            if not nums or len(nums) != 6:
                continue
            draws.append(
                {
                    "round": r["round"],
                    "numbers": list(nums),
                    "bonus": r.get("bonus"),
                }
            )
        if len(draws) < args.validate:
            print(f"  [FAIL] not enough draws ({len(draws)} < {args.validate})")
            return

        ordered = _ordered_draws(draws)
        train_draws = ordered[: -args.validate]
        test_rounds = ordered[-args.validate :]

        predictor = DynamicIndependentCountPredictor(
            feature_dim=24,
            sample_threshold=50,
            n_range=(2, 200),
            active_models=("xgboost", "markov"),
        )
        print("  training...")
        predictor.train(train_draws)
        print(f"    active N (from heads): {len(predictor.heads)}")

        # walk-forward 검증 (CE 계산)
        total_ce = 0.0
        total_count = 0
        for test_d in test_rounds:
            target_round = int(test_d["round"])
            # target_round 이전 회차만 사용
            train_subset = [
                d for d in ordered if int(d.get("round", 0)) < target_round
            ]
            out = predictor.predict(train_subset, target_round)
            if not out["per_n"]:
                continue

            # 실제 회귀 매칭 카운트 계산
            test_six = set(test_d.get("numbers", []))
            for N in out["per_n"].keys():
                # (target_round - N) 회차 풀
                ref_round = target_round - N
                ref_d = next(
                    (d for d in ordered if int(d.get("round", 0)) == ref_round), None
                )
                if ref_d is None:
                    continue
                # N회 전 unique 풀 (본번호만)
                pool: set[int] = set()
                for i in range(min(N, len(ordered))):
                    d_idx = next(
                        (
                            idx
                            for idx, d in enumerate(ordered)
                            if int(d.get("round", 0)) == target_round - 1 - i
                        ),
                        None,
                    )
                    if d_idx is not None:
                        pool.update(_draw_main_numbers(ordered[d_idx]))
                true_count = len(pool & test_six)
                true_count = min(true_count, 6)  # clamp 0~6

                pred_dist = np.asarray(
                    out["per_n"][N]["absolute_dist"], dtype=np.float64
                )
                # cross-entropy
                ce = -np.log(pred_dist[true_count] + 1e-9)
                total_ce += ce
                total_count += 1

        avg_ce = total_ce / max(total_count, 1)
        print(
            f"\n  walk-forward validate: avg CE={avg_ce:.4f} (over {total_count} N-pairs)"
        )
        # 빈도 베이스라인과 비교 (reference)
        print("    (lower CE is better; frequency baseline ~ 1.8~2.2)")
        return

    # ──── smoke ────
    if not args.smoke:
        parser.print_help()
        return

    print("[regression_predictor] smoke start")
    draws = _generate_fake_draws(args.rounds)
    print(f"  fake draws: {len(draws)}")

    # 활성 N 탐색 — 마지막 회차
    last_round = int(draws[-1]["round"])
    active = compute_active_n(last_round, draws, n_range=(2, 200))
    print(f"  active N at round {last_round}: {len(active)} N values")
    print(f"    sample N keys: {sorted(active.keys())[:10]}...")

    # 학습 (smoke: sample_threshold 낮춤)
    predictor = DynamicIndependentCountPredictor(
        feature_dim=24,
        sample_threshold=30,  # smoke: 200 회차 데이터에서도 신뢰 N 다수 확보 위해 낮춤
        n_range=(2, 50),  # smoke: 50까지만 학습 (시간 단축)
        active_models=("xgboost", "markov"),  # smoke: 의존성 적은 2개
    )
    print("  training (smoke)...")
    history = predictor.train(draws)
    print(f"    candidates: {history['n_total_candidates']}")
    print(f"    trained N: {len(history['trained_n'])} (first 10: {history['trained_n'][:10]})")
    print(f"    fallback N: {len(history['fallback_n'])} (first 10: {history['fallback_n'][:10]})")

    # 추론
    print("  predicting (smoke)...")
    out = predictor.predict(draws)
    per_n = out["per_n"]
    active_n_count = out["active_n_count"]
    print(f"    active N at predict: {active_n_count} (dense: {out['dense_n_count']})")
    print(f"    aggregated_expected: {out['aggregated_expected']:.2f}")

    # per_n dist 정합 (각 dist 합 ~= 1)
    bad = []
    for N, result in per_n.items():
        dist = result["absolute_dist"]
        s = sum(dist)
        if abs(s - 1.0) > 1e-3:
            bad.append((N, s))
    print(f"    dist normalization OK: {len(per_n) - len(bad)}/{len(per_n)}")
    if bad:
        print(f"    misnormalized: {bad[:5]}")

    # 활성 N 16~30개 확인 (200 회차 가짜 데이터에서 자연 회귀 발생 빈도)
    # plan은 실제 lotto 1100 회차 가정 — 200으로는 더 많을 수도 있음
    print(f"    plan target: active N 16~30 per round (current: {active_n_count})")

    # 1~3 sample narrative
    for N in sorted(per_n.keys())[:3]:
        print(f"    {per_n[N]['narrative']}")

    # save / load 검증
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as f:
        tmp_path = f.name
    predictor.save(tmp_path)
    p2 = DynamicIndependentCountPredictor()
    p2.load(tmp_path)
    print(f"    save/load: head count restored = {len(p2.heads)}")
    os.unlink(tmp_path)

    print("  smoke OK")


if __name__ == "__main__":
    main()
