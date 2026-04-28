"""DynamicIndependentCountPredictor — 회귀(2~200) Tier 1 가변 카테고리 ICP.

회귀 N=k 정의:
  t회차 분석에서 (t-k)회차의 6번호 + 보너스 = N=k 풀 (7명).
  t회차 본 풀 멤버 중 1명 이상이 다시 등장 → N=k 활성.

활성 N은 매 회차 16~30개 동적 변동.
신뢰 N (sample >= threshold)만 11 base 학습, sparse N은 빈도 fallback.

본 베이스의 IndependentCountPredictor를 199개 N에 일괄 적용하는 것은 비효율 →
가벼운 모델(XGBoost / Markov / Bayesian) 한정 + 신뢰 N만 ML.
"""

from __future__ import annotations

import os
import pickle
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

import config


# 회귀 기본 파라미터 (config에 설정 없으면 본 default 사용)
_REGRESSION_N_RANGE: tuple[int, int] = getattr(config, "REGRESSION_N_RANGE", (2, 200))
_REGRESSION_SAMPLE_THRESHOLD: int = getattr(config, "REGRESSION_SAMPLE_THRESHOLD", 50)
_REGRESSION_N_CLASSES: int = 8  # 0~7 count (풀 7명까지 가능)


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


def _draw_seven(d: dict) -> set[int]:
    """단일 회차의 6번호 + 보너스 = 7명 풀."""
    nums: set[int] = set()
    for n in d.get("numbers", []):
        try:
            nums.add(int(n))
        except (TypeError, ValueError):
            continue
    bonus = d.get("bonus")
    if bonus is not None:
        try:
            nums.add(int(bonus))
        except (TypeError, ValueError):
            pass
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
    target_pool = _draw_seven(ordered[t_idx])

    n_min, n_max = int(n_range[0]), int(n_range[1])
    active: dict[int, list[int]] = {}
    for N in range(n_min, n_max + 1):
        prev_idx = t_idx - N
        if prev_idx < 0:
            continue
        prev_pool = _draw_seven(ordered[prev_idx])
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
    return len(_draw_seven(ordered[prev_idx]))


def _count_regression_at(
    ordered: list[dict],
    t_idx: int,
    N: int,
) -> Optional[int]:
    """ordered[t_idx]의 N 회귀 카운트. 데이터 결손이면 None."""
    prev_idx = t_idx - N
    if prev_idx < 0:
        return None
    target_pool = _draw_seven(ordered[t_idx])
    prev_pool = _draw_seven(ordered[prev_idx])
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

    def predict(self, draws_so_far: list[dict]) -> dict:
        """가장 최근 회차의 다음 회차에 대한 활성 N별 분포 산출.

        Returns:
          {
            "active_N_set": list[int],
            "per_N_dist": {N: list[float] len=n_classes},
            "per_N_expected": {N: float},
            "per_N_pool_size": {N: int},
            "per_N_narrative": {N: str},
          }
        """
        if not draws_so_far:
            return self._empty_payload()

        ordered = _ordered_draws(draws_so_far)
        T = len(ordered)
        if T < 2:
            return self._empty_payload()

        # 다음 회차 = ordered 마지막 직후. 가장 최근 회차의 round 번호 + 1을
        # 사용하지만 실제 데이터에 없으니 t_idx = T (가상). prev pool은 ordered[T - N].
        latest_round = int(ordered[-1].get("round", 0))
        target_round_virtual = latest_round + 1

        # 활성 N 식별 — 가상 회차의 풀이 없으므로 "이전 풀들의 멤버 중 다음 회차 출현
        # 가능성"이 1 이상인 N = (T-N)이 0 이상이고 prev pool != empty
        # 활성 정의를 학습 시점 직전 회차 기준으로 (latest 회차 t_idx = T-1)
        # 활성 N: (T-1) 회차 본 풀과 (T-1-N) 풀 overlap >= 1
        active_now = compute_active_n(latest_round, ordered, self.n_range)
        active_set = sorted(active_now.keys())

        per_N_dist: dict[int, list[float]] = {}
        per_N_exp: dict[int, float] = {}
        per_N_pool: dict[int, int] = {}
        per_N_narr: dict[int, str] = {}

        # 누적 dense 카운트 시계열 (각 N별 history)
        for N in active_set:
            head = self.heads.get(N)
            # 다음 회차(가상)의 N회 전 풀 = ordered[T - N] (target_idx = T, prev_idx = T - N)
            prev_idx = T - N
            pool_size = len(_draw_seven(ordered[prev_idx])) if 0 <= prev_idx < T else 0
            # target_round_virtual의 N회 전 = ordered[T - N] (T-1+1-N = T-N)
            # 학습 안 된 N (n_range 안이지만 head 없는 경우) → uniform
            if head is None:
                dist = np.full(self.n_classes, 1.0 / self.n_classes)
                expected = float(np.sum(dist * np.arange(self.n_classes)))
                per_N_dist[N] = dist.tolist()
                per_N_exp[N] = expected
                per_N_pool[N] = pool_size
                per_N_narr[N] = (
                    f"N={N} pool {pool_size} expected {int(round(expected))} (uniform prior)"
                )
                continue

            # 각 base의 prob 결합
            dense = np.zeros(T, dtype=np.float32)
            for t in range(N, T):
                c = _count_regression_at(ordered, t, N)
                if c is not None:
                    dense[t] = float(c)
            sub = dense.copy()
            # dormancy: 마지막 활성(>0) idx 부터 T까지 거리
            active_idx = np.where(dense > 0)[0]
            if len(active_idx) > 0:
                dormancy = T - 1 - int(active_idx[-1])
            else:
                dormancy = T
            vec = _build_n_features(sub, pool_size, dormancy, self.feature_dim)

            probs_list: list[np.ndarray] = []
            if head.is_reliable and head.base_models:
                for name, mdl in head.base_models.items():
                    p = self._model_proba(name, mdl, vec)
                    if p is not None:
                        probs_list.append(self._normalize_prob_shape(p))

            if probs_list:
                avg = np.mean(np.stack(probs_list, axis=0), axis=0)
                if avg.sum() > 0:
                    avg = avg / avg.sum()
                else:
                    avg = head.prior.copy()
            else:
                avg = head.prior.copy()

            expected = float(np.sum(avg * np.arange(self.n_classes)))
            top_class = int(np.argmax(avg))
            top_p = float(avg[top_class])

            per_N_dist[N] = avg.tolist()
            per_N_exp[N] = expected
            per_N_pool[N] = pool_size
            per_N_narr[N] = (
                f"N={N} pool {pool_size} expected {top_class} (P={top_p * 100:.1f}%)"
            )

        return {
            "active_N_set": active_set,
            "per_N_dist": per_N_dist,
            "per_N_expected": per_N_exp,
            "per_N_pool_size": per_N_pool,
            "per_N_narrative": per_N_narr,
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
            "active_N_set": [],
            "per_N_dist": {},
            "per_N_expected": {},
            "per_N_pool_size": {},
            "per_N_narrative": {},
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
    """python -m predictors.regression_predictor --smoke."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--rounds", type=int, default=200)
    args = parser.parse_args()

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
    active_set = out["active_N_set"]
    print(f"    active N at predict: {len(active_set)} (range {min(active_set) if active_set else None}~{max(active_set) if active_set else None})")

    # per_N_dist 정합 (각 dist 합 ~= 1)
    bad = []
    for N, dist in out["per_N_dist"].items():
        s = sum(dist)
        if abs(s - 1.0) > 1e-3:
            bad.append((N, s))
    print(f"    dist normalization OK: {len(out['per_N_dist']) - len(bad)}/{len(out['per_N_dist'])}")
    if bad:
        print(f"    misnormalized: {bad[:5]}")

    # 활성 N 16~30개 확인 (200 회차 가짜 데이터에서 자연 회귀 발생 빈도)
    # plan은 실제 lotto 1100 회차 가정 — 200으로는 더 많을 수도 있음
    print(f"    plan target: active N 16~30 per round (current: {len(active_set)})")

    # 1~3 sample narrative
    for N in active_set[:3]:
        print(f"    {out['per_N_narrative'][N]}")

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
