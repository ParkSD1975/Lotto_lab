"""Stage 3-B-1 — 4 Pillar 통합 NumberScorer.

4 Pillar 점수 시스템 (단일 진실 공급원: docs/MASTER_PLAN.md Stage 3):

    final_score(n) = MetaLearner.predict([
        pillar_1_ensemble_prob(n),     # 11 base 가중평균 + Bayesian sigma
        pillar_2_filter_compliance(n), # 21지표 필터 통과도 가중 합산
        pillar_3_individual_state(n),  # 핫콜드 + 미출현 + 회귀 + carryover + 이웃
        pillar_4_consensus_score(n),   # ConsensusAnalyzer 점수
    ])

Ridge regression 메타러너로 4 Pillar 동적 가중치를 학습하며,
walk-forward backtest 결과에 따라 가중치를 갱신한다.
"""
from __future__ import annotations

import json
import os
from typing import Any

import numpy as np

try:
    import config  # type: ignore
    _RANDOM_SEED = int(getattr(config, "RANDOM_SEED", 42))
    _PILLAR_PATH = str(getattr(
        config,
        "PILLAR_META_LEARNER_PATH",
        os.path.join(getattr(config, "MODEL_DIR", "saved_models"), "pillar_meta_weights.json"),
    ))
    _BACKTEST_WIN = int(getattr(config, "RECOMMENDATION_BACKTEST_WINDOW", 50))
    _RIDGE_ALPHA = float(getattr(config, "PILLAR_RIDGE_ALPHA", 1.0))
except Exception:
    _RANDOM_SEED = 42
    _PILLAR_PATH = os.path.join("saved_models", "pillar_meta_weights.json")
    _BACKTEST_WIN = 50
    _RIDGE_ALPHA = 1.0


# 4 Pillar 컬럼 인덱스
PILLAR_NAMES: list[str] = [
    "pillar_1_ensemble",
    "pillar_2_filter",
    "pillar_3_individual",
    "pillar_4_consensus",
]

# Pillar 3 가중치 default (5 신호 합산)
_P3_W_HOTCOLD    = 0.30
_P3_W_DORMANCY   = 0.25
_P3_W_REGRESSION = 0.20
_P3_W_CARRYOVER  = 0.10
_P3_W_NEIGHBOR   = 0.15

# Pillar 2 21지표 default 가중치 (모두 동일 1/21 출발 — 학습으로 보정)
_P2_DEFAULT_W = 1.0 / 21.0


# ──────────────────────────────────────────────────────────────────────
# 정규화 헬퍼
# ──────────────────────────────────────────────────────────────────────
def _safe_float(v: Any, default: float = 0.0) -> float:
    """안전한 float 변환 — None/NaN/Inf는 default."""
    try:
        f = float(v)
        if not np.isfinite(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


def _zscore(arr: np.ndarray) -> np.ndarray:
    """벡터 표준화 (StandardScaler 단일 컬럼). std=0이면 0 벡터."""
    a = np.asarray(arr, dtype=np.float64)
    mu = float(a.mean())
    sd = float(a.std(ddof=0))
    if sd <= 1e-12:
        return np.zeros_like(a, dtype=np.float64)
    return (a - mu) / sd


def _minmax01(arr: np.ndarray) -> np.ndarray:
    """0~1 min-max 정규화. 범위 0이면 모두 0.5."""
    a = np.asarray(arr, dtype=np.float64)
    mn = float(a.min())
    mx = float(a.max())
    rng = mx - mn
    if rng <= 1e-12:
        return np.full_like(a, 0.5, dtype=np.float64)
    return (a - mn) / rng


# ──────────────────────────────────────────────────────────────────────
# NumberScorer
# ──────────────────────────────────────────────────────────────────────
class NumberScorer:
    """4 Pillar 통합 + Ridge MetaLearner 동적 가중치 학습."""

    def __init__(self, meta_path: str | None = None):
        """Ridge 메타러너 + Pillar 정규화 scaler 초기화.

        Args:
            meta_path: pillar_meta_weights.json 경로 (None이면 config default)
        """
        self.meta_path: str = str(meta_path) if meta_path else _PILLAR_PATH
        self._seed: int = _RANDOM_SEED

        # sklearn Ridge — 학습 시점에 lazy 초기화
        self._ridge = None
        self._ridge_fitted: bool = False

        # Pillar 별 학습 fold 통계 (StandardScaler 대신 mu/sigma 보관)
        self._p3_mu: float = 0.0
        self._p3_sigma: float = 1.0
        self._p4_mu: float = 0.0
        self._p4_sigma: float = 1.0

        # backtest 동적 가중치 (4 Pillar)
        self.pillar_weights: np.ndarray = np.full(4, 0.25, dtype=np.float64)

        # 21지표 가중치 (Pillar 2)
        self.filter_weights: dict[str, float] = {}

        # 자동 로드
        self._try_load(self.meta_path)

    # ------------------------------------------------------------------
    # Pillar 1 — 11 base 앙상블 prob (Bayesian sigma 보정)
    # ------------------------------------------------------------------
    def _compute_pillar_1(
        self,
        ensemble_probs: dict[int, float] | None,
        bayesian_sigma: dict[int, float] | None = None,
    ) -> np.ndarray:
        """11 base 가중평균 prob 벡터 (45,).

        Args:
            ensemble_probs : {n: prob} — LottoEnsemble.predict() 결과
            bayesian_sigma : {n: sigma} — bayesian_nn 불확실성. 클수록 감점.

        Returns:
            shape (45,) float64. 합 != 1 (sigma 보정 적용 후 raw).
        """
        out = np.zeros(45, dtype=np.float64)
        if not isinstance(ensemble_probs, dict) or not ensemble_probs:
            # graceful: uniform fallback
            out[:] = 1.0 / 45.0
            return out

        for n in range(1, 46):
            v = ensemble_probs.get(n, ensemble_probs.get(str(n), 0.0))
            out[n - 1] = _safe_float(v, 0.0)

        # sigma 보정: prob * exp(-sigma_norm) — 불확실성 클수록 감점
        if isinstance(bayesian_sigma, dict) and bayesian_sigma:
            sig = np.zeros(45, dtype=np.float64)
            for n in range(1, 46):
                sig[n - 1] = _safe_float(
                    bayesian_sigma.get(n, bayesian_sigma.get(str(n), 0.0)), 0.0,
                )
            sig_norm = _minmax01(sig)  # 0~1
            out = out * np.exp(-0.5 * sig_norm)

        return out

    # ------------------------------------------------------------------
    # Pillar 2 — 21지표 필터 통과도
    # ------------------------------------------------------------------
    def _compute_pillar_2(
        self,
        filter_stats_result: list[dict] | dict | None,
        draws_so_far: list[dict] | None,
    ) -> np.ndarray:
        """번호별 21지표 필터 통과도 가중 합산.

        Args:
            filter_stats_result: FilterStatsComputer.compute_all() 결과 list[dict]
                                 또는 {key: filter_dict} 형태도 허용.
            draws_so_far       : 직전 회차 history (carryover/neighbor 추정용)

        Returns:
            shape (45,) float64 — 0~1 정규화된 통과도.
        """
        compliance = np.zeros(45, dtype=np.float64)

        filters: list[dict] = []
        if isinstance(filter_stats_result, list):
            filters = [f for f in filter_stats_result if isinstance(f, dict)]
        elif isinstance(filter_stats_result, dict):
            filters = [v for v in filter_stats_result.values() if isinstance(v, dict)]

        if not filters:
            # graceful: 0.5 uniform (중립 통과도)
            compliance[:] = 0.5
            return compliance

        for n in range(1, 46):
            score = 0.0
            total_w = 0.0
            for fdict in filters:
                key = str(fdict.get("key", "")) or str(fdict.get("name", ""))
                w = float(self.filter_weights.get(key, _P2_DEFAULT_W))
                comp = self._compliance_one(n, fdict, draws_so_far or [])
                score += w * comp
                total_w += w
            compliance[n - 1] = score / total_w if total_w > 0 else 0.0

        return compliance

    @staticmethod
    def _compliance_one(n: int, fdict: dict, draws_so_far: list[dict]) -> float:
        """단일 번호 n의 단일 필터 통과도 (0~1)."""
        key = str(fdict.get("key", ""))
        ml = fdict.get("ml_recommendation") or {}

        # 일반 ML 블록의 min/max/median 활용
        q10 = ml.get("min")
        q50 = ml.get("median")
        q90 = ml.get("max")

        # 1) 합산형 필터 (total_sum, tail_sum, ac_value) — n이 통계 평균 근접도
        if key in {"total_sum", "tail_sum", "ac_value"}:
            try:
                med = float(q50) if q50 is not None else None
                if med is None:
                    return 0.5
                # n이 단일 번호이므로 sum 평균/6 근접도로 환산
                if key == "total_sum":
                    target = med / 6.0
                    return max(0.0, 1.0 - abs(n - target) / 22.5)
                if key == "tail_sum":
                    target = (med / 6.0) % 10
                    return max(0.0, 1.0 - abs((n % 10) - target) / 9.0)
                # ac_value: 모든 번호 동일 기여 — 0.5 중립
                return 0.5
            except Exception:
                return 0.5

        # 2) low/high
        if key == "low_high":
            top_class = ml.get("top_class")
            try:
                tc = int(top_class) if top_class is not None else None
            except Exception:
                tc = None
            if tc is None:
                return 0.5
            # tc = 저구간(1~22) 개수. tc>=3이면 저구간 강세
            if n <= 22:
                return 0.5 + 0.5 * max(0.0, (tc - 3) / 3.0)
            return 0.5 + 0.5 * max(0.0, (3 - tc) / 3.0)

        # 3) odd_even
        if key == "odd_even":
            top_class = ml.get("top_class")
            try:
                tc = int(top_class) if top_class is not None else None
            except Exception:
                tc = None
            if tc is None:
                return 0.5
            if (n % 2 == 1):
                return 0.5 + 0.5 * max(0.0, (tc - 3) / 3.0)
            return 0.5 + 0.5 * max(0.0, (3 - tc) / 3.0)

        # 4) endings (끝수) — distribution_10d 활용
        if key == "tail_sum":
            dist = ml.get("distribution_10d")
            if isinstance(dist, (list, tuple)) and len(dist) == 10:
                arr = np.asarray(dist, dtype=np.float64)
                s = arr.sum()
                if s > 0:
                    return float(arr[n % 10] / s)
            return 0.5

        # 5) hot_cold — 핫콜드 그룹 매칭 (per_category 활용)
        if key == "hot_cold":
            per_cat = ml.get("per_category") or {}
            if isinstance(per_cat, dict):
                # 'hot' 풀에 n 포함 시 ↑
                hot_pool = per_cat.get("hot_pool") or per_cat.get("hot") or []
                cold_pool = per_cat.get("cold_pool") or per_cat.get("cold") or []
                if isinstance(hot_pool, (list, tuple)) and n in hot_pool:
                    return 0.8
                if isinstance(cold_pool, (list, tuple)) and n in cold_pool:
                    return 0.3
            return 0.5

        # 6) decade (번호대) — 9궁/decade는 n의 십의자리 매칭
        if key in {"decade_distribution", "zone_pattern", "number_range"}:
            per_cat = ml.get("per_category") or {}
            if isinstance(per_cat, dict):
                decade = (n - 1) // 10  # 0..4
                hit = per_cat.get(f"decade_{decade}") or per_cat.get(str(decade))
                if hit is not None:
                    return _safe_float(hit, 0.5)
            return 0.5

        # 7) prime/composite/square/triangular/multiple_3/7/8 — 멤버십
        if key in {"prime_count", "composite_count", "square_count",
                   "triangular_count", "multiple_3", "multiple_7", "multiple_8"}:
            try:
                import config as _cfg  # type: ignore
                primes = getattr(_cfg, "PRIMES", set())
                squares = getattr(_cfg, "SQUARES", set())
                triangulars = getattr(_cfg, "TRIANGULARS", set())
            except Exception:
                primes, squares, triangulars = set(), set(), set()

            in_set = False
            if key == "prime_count":
                in_set = n in primes
            elif key == "composite_count":
                in_set = (n not in primes) and n != 1
            elif key == "square_count":
                in_set = n in squares
            elif key == "triangular_count":
                in_set = n in triangulars
            elif key == "multiple_3":
                in_set = (n % 3 == 0)
            elif key == "multiple_7":
                in_set = (n % 7 == 0)
            elif key == "multiple_8":
                in_set = (n % 8 == 0)

            try:
                med = float(q50) if q50 is not None else None
            except Exception:
                med = None
            if med is None:
                return 0.5 if in_set else 0.5
            # 강한 기대 (med>=2)면 in_set 통과도 ↑, 아니면 ↓
            return 0.7 if in_set and med >= 2 else (0.4 if in_set else 0.5)

        # 8) carryover — 직전 회차 출현
        if key == "carryover":
            if draws_so_far:
                last = draws_so_far[0].get("numbers", []) if isinstance(draws_so_far[0], dict) else []
                if n in last:
                    return 0.7
                return 0.4
            return 0.5

        # 9) neighbor — 이웃수 풀
        if key == "neighbor_count":
            if draws_so_far:
                last = draws_so_far[0].get("numbers", []) if isinstance(draws_so_far[0], dict) else []
                if any(abs(n - m) == 1 for m in last):
                    return 0.65
            return 0.5

        # 10) consecutive
        if key == "consecutive":
            return 0.5

        # 11) twin_count
        if key == "twin_count":
            return 0.5

        # 12) missing_group — n이 미출현 풀이면 약간 가산
        if key == "missing_group":
            per_cat = ml.get("per_category") or {}
            if isinstance(per_cat, dict):
                missing = per_cat.get("missing_pool") or per_cat.get("missing") or []
                if isinstance(missing, (list, tuple)) and n in missing:
                    return 0.6
            return 0.5

        # default: 0.5 중립
        return 0.5

    # ------------------------------------------------------------------
    # Pillar 3 — 번호별 동적 상태 (5 신호 합산)
    # ------------------------------------------------------------------
    def _compute_pillar_3(
        self,
        predictor_pipeline_outputs: dict | None,
        draws_so_far: list[dict] | None,
    ) -> np.ndarray:
        """번호별 동적 상태 점수 (5 신호 가중합).

        Args:
            predictor_pipeline_outputs: PredictorPipeline.predict_all() 결과
            draws_so_far              : 직전 회차 history

        Returns:
            shape (45,) float64
        """
        out = np.zeros(45, dtype=np.float64)
        outs = predictor_pipeline_outputs or {}

        # 1) hotcold_signal — phase1["hotcold"]
        hot = self._extract_hotcold(outs)
        # 2) dormancy_signal — phase1["missing_group"]
        dorm = self._extract_dormancy(outs, draws_so_far)
        # 3) regression_signal — outs["regression"]
        regr = self._extract_regression(outs)
        # 4) carryover_signal — 직전 회차 멤버십
        carry = self._extract_carryover(draws_so_far)
        # 5) neighbor_signal — 이웃수 풀 멤버십
        nbr = self._extract_neighbor(draws_so_far)

        out = (
            _P3_W_HOTCOLD    * hot
            + _P3_W_DORMANCY   * dorm
            + _P3_W_REGRESSION * regr
            + _P3_W_CARRYOVER  * carry
            + _P3_W_NEIGHBOR   * nbr
        )
        return out

    @staticmethod
    def _extract_hotcold(outs: dict) -> np.ndarray:
        """phase1.hotcold per_category에서 n 위치 추출 (0/0.5/1)."""
        v = np.full(45, 0.5, dtype=np.float64)
        phase1 = outs.get("phase1") or {}
        if not isinstance(phase1, dict):
            return v
        payload = phase1.get("hotcold") or phase1.get("hotcold_12") or {}
        if not isinstance(payload, dict):
            return v
        per_cat = payload.get("per_category") or {}
        if not isinstance(per_cat, dict):
            return v
        hot_pool = per_cat.get("hot_pool") or per_cat.get("hot") or []
        cold_pool = per_cat.get("cold_pool") or per_cat.get("cold") or []
        if isinstance(hot_pool, (list, tuple)):
            for n in hot_pool:
                if isinstance(n, int) and 1 <= n <= 45:
                    v[n - 1] = 1.0
        if isinstance(cold_pool, (list, tuple)):
            for n in cold_pool:
                if isinstance(n, int) and 1 <= n <= 45:
                    v[n - 1] = 0.0
        return v

    @staticmethod
    def _extract_dormancy(outs: dict, draws_so_far: list[dict] | None) -> np.ndarray:
        """미출현 그룹 + 마지막 출현 후 경과 회차 정규화."""
        v = np.full(45, 0.5, dtype=np.float64)

        # missing_group payload 우선
        phase1 = outs.get("phase1") or {}
        if isinstance(phase1, dict):
            payload = phase1.get("missing_group") or {}
            if isinstance(payload, dict):
                per_cat = payload.get("per_category") or {}
                if isinstance(per_cat, dict):
                    missing = per_cat.get("missing_pool") or per_cat.get("missing") or []
                    if isinstance(missing, (list, tuple)):
                        for n in missing:
                            if isinstance(n, int) and 1 <= n <= 45:
                                v[n - 1] = 0.8

        # draws에서 last_seen 산출
        if draws_so_far:
            last_seen = {n: -1 for n in range(1, 46)}
            for idx, d in enumerate(draws_so_far):  # draws_so_far[0] = 최신
                if not isinstance(d, dict):
                    continue
                for nn in d.get("numbers", []) or []:
                    if isinstance(nn, int) and 1 <= nn <= 45 and last_seen[nn] < 0:
                        last_seen[nn] = idx
            max_gap = max([g for g in last_seen.values() if g >= 0], default=1) or 1
            for n in range(1, 46):
                gap = last_seen[n]
                if gap < 0:
                    v[n - 1] = max(v[n - 1], 0.9)  # 한 번도 안 나온 번호
                else:
                    v[n - 1] = max(v[n - 1], min(1.0, gap / max_gap))
        return v

    @staticmethod
    def _extract_regression(outs: dict) -> np.ndarray:
        """regression Tier 1 active_N_set 멤버십 + Tier 3 룰 가산."""
        v = np.full(45, 0.5, dtype=np.float64)
        regr = outs.get("regression") or {}
        if not isinstance(regr, dict):
            return v
        tier1 = regr.get("tier1") or {}
        active = tier1.get("active_N_set") or []
        if isinstance(active, (list, tuple, set)):
            for n in active:
                if isinstance(n, int) and 1 <= n <= 45:
                    v[n - 1] = 0.75

        # Tier 3 자동 룰 — recommended/excluded
        tier3 = regr.get("tier3_rules") or {}
        if isinstance(tier3, dict):
            recs = tier3.get("recommended_numbers") or []
            excs = tier3.get("excluded_numbers") or []
            if isinstance(recs, (list, tuple)):
                for n in recs:
                    if isinstance(n, int) and 1 <= n <= 45:
                        v[n - 1] = max(v[n - 1], 0.85)
            if isinstance(excs, (list, tuple)):
                for n in excs:
                    if isinstance(n, int) and 1 <= n <= 45:
                        v[n - 1] = min(v[n - 1], 0.15)
        return v

    @staticmethod
    def _extract_carryover(draws_so_far: list[dict] | None) -> np.ndarray:
        """직전 회차 출현 시 1, 아니면 0."""
        v = np.zeros(45, dtype=np.float64)
        if not draws_so_far:
            return v
        last = draws_so_far[0]
        if not isinstance(last, dict):
            return v
        for n in last.get("numbers", []) or []:
            if isinstance(n, int) and 1 <= n <= 45:
                v[n - 1] = 1.0
        return v

    @staticmethod
    def _extract_neighbor(draws_so_far: list[dict] | None) -> np.ndarray:
        """직전 회차 번호의 ±1 이웃수 풀 멤버십."""
        v = np.zeros(45, dtype=np.float64)
        if not draws_so_far:
            return v
        last = draws_so_far[0]
        if not isinstance(last, dict):
            return v
        nums = last.get("numbers", []) or []
        for n in range(1, 46):
            if any(isinstance(m, int) and abs(n - m) == 1 for m in nums):
                v[n - 1] = 1.0
        return v

    # ------------------------------------------------------------------
    # Pillar 4 — Consensus Score
    # ------------------------------------------------------------------
    def _compute_pillar_4(self, consensus_metrics: dict[int, dict] | None) -> np.ndarray:
        """ConsensusAnalyzer.compute_metrics() 출력에서 consensus_score 추출."""
        v = np.zeros(45, dtype=np.float64)
        if not isinstance(consensus_metrics, dict) or not consensus_metrics:
            return v
        for n in range(1, 46):
            m = consensus_metrics.get(n) or {}
            v[n - 1] = _safe_float(m.get("consensus_score", 0.0), 0.0)
        return v

    # ------------------------------------------------------------------
    # 4 Pillar 통합
    # ------------------------------------------------------------------
    def compute_4pillars(
        self,
        ensemble_probs: dict[int, float] | None,
        filter_stats_result: list[dict] | dict | None,
        predictor_pipeline_outputs: dict | None,
        consensus_metrics: dict[int, dict] | None,
        draws_so_far: list[dict] | None = None,
        bayesian_sigma: dict[int, float] | None = None,
    ) -> np.ndarray:
        """4 Pillar 점수 매트릭스 산출.

        Returns:
            shape (45, 4) — 컬럼 순서: PILLAR_NAMES
        """
        p1 = self._compute_pillar_1(ensemble_probs, bayesian_sigma)
        p2 = self._compute_pillar_2(filter_stats_result, draws_so_far)
        p3 = self._compute_pillar_3(predictor_pipeline_outputs, draws_so_far)
        p4 = self._compute_pillar_4(consensus_metrics)

        mat = np.zeros((45, 4), dtype=np.float64)
        mat[:, 0] = p1
        mat[:, 1] = p2
        mat[:, 2] = p3
        mat[:, 3] = p4
        return mat

    def _normalize_for_predict(self, mat: np.ndarray) -> np.ndarray:
        """학습 fold 통계로 Pillar 3/4 표준화 (Pillar 1/2는 그대로)."""
        out = mat.astype(np.float64).copy()
        # Pillar 3 (학습 fold mu/sigma 적용)
        if self._p3_sigma > 1e-12:
            out[:, 2] = (out[:, 2] - self._p3_mu) / self._p3_sigma
        # Pillar 4
        if self._p4_sigma > 1e-12:
            out[:, 3] = (out[:, 3] - self._p4_mu) / self._p4_sigma
        return out

    # ------------------------------------------------------------------
    # 메타러너 학습 / 예측
    # ------------------------------------------------------------------
    def _ensure_ridge(self):
        """sklearn Ridge lazy import."""
        if self._ridge is not None:
            return
        try:
            from sklearn.linear_model import Ridge
            self._ridge = Ridge(alpha=_RIDGE_ALPHA, random_state=self._seed)
        except Exception as e:
            print(f"[NumberScorer] sklearn Ridge import fail: {e}")
            self._ridge = None

    def train_meta(
        self,
        historical_pillars: np.ndarray,
        historical_labels: np.ndarray,
    ) -> dict:
        """walk-forward 4 Pillar -> 실제 출현 binary 라벨로 Ridge 학습.

        Args:
            historical_pillars: shape (n_samples, 4)
            historical_labels : shape (n_samples,) — 0/1

        Returns:
            {success, n_samples, coef, intercept, r2}
        """
        X = np.asarray(historical_pillars, dtype=np.float64)
        y = np.asarray(historical_labels, dtype=np.float64).ravel()

        if X.ndim != 2 or X.shape[1] != 4:
            return {"success": False, "error": f"X shape must be (n, 4), got {X.shape}"}
        if X.shape[0] != y.shape[0]:
            return {"success": False, "error": "X / y length mismatch"}
        if X.shape[0] < 10:
            return {"success": False, "error": f"insufficient samples ({X.shape[0]} < 10)"}

        # 학습 fold 통계 (Pillar 3/4)
        self._p3_mu = float(X[:, 2].mean())
        self._p3_sigma = float(X[:, 2].std(ddof=0)) or 1.0
        self._p4_mu = float(X[:, 3].mean())
        self._p4_sigma = float(X[:, 3].std(ddof=0)) or 1.0

        X_norm = X.copy()
        X_norm[:, 2] = (X_norm[:, 2] - self._p3_mu) / self._p3_sigma
        X_norm[:, 3] = (X_norm[:, 3] - self._p4_mu) / self._p4_sigma

        self._ensure_ridge()
        if self._ridge is None:
            return {"success": False, "error": "sklearn unavailable"}

        self._ridge.fit(X_norm, y)
        self._ridge_fitted = True

        # Pillar 가중치 = |coef| 정규화 (음수 coef도 절대값으로 영향력 측정)
        coef = np.asarray(self._ridge.coef_, dtype=np.float64).ravel()
        abs_coef = np.abs(coef)
        s = abs_coef.sum()
        self.pillar_weights = (abs_coef / s) if s > 0 else np.full(4, 0.25, dtype=np.float64)

        # R^2 (학습 fold)
        y_pred = self._ridge.predict(X_norm)
        ss_res = float(((y - y_pred) ** 2).sum())
        ss_tot = float(((y - y.mean()) ** 2).sum())
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0

        return {
            "success": True,
            "n_samples": int(X.shape[0]),
            "coef": [float(c) for c in coef],
            "intercept": float(self._ridge.intercept_),
            "pillar_weights": [float(w) for w in self.pillar_weights],
            "r2_train": float(r2),
        }

    def score_numbers(
        self,
        ensemble_probs: dict[int, float] | None,
        filter_stats_result: list[dict] | dict | None,
        predictor_pipeline_outputs: dict | None,
        consensus_metrics: dict[int, dict] | None,
        draws_so_far: list[dict] | None = None,
        bayesian_sigma: dict[int, float] | None = None,
    ) -> dict[int, float]:
        """4 Pillar -> Ridge -> final_score 1~45 매핑.

        Returns:
            {n: final_score} 1~45 — Ridge 미학습 시 pillar_weights 가중합 fallback.
        """
        mat = self.compute_4pillars(
            ensemble_probs,
            filter_stats_result,
            predictor_pipeline_outputs,
            consensus_metrics,
            draws_so_far,
            bayesian_sigma,
        )
        mat_norm = self._normalize_for_predict(mat)

        if self._ridge_fitted and self._ridge is not None:
            try:
                scores = self._ridge.predict(mat_norm)
            except Exception as e:
                print(f"[NumberScorer] ridge.predict fail: {e}, fallback weighted sum")
                scores = mat_norm @ self.pillar_weights
        else:
            # Ridge 미학습: pillar_weights 가중합 fallback
            scores = mat_norm @ self.pillar_weights

        return {n: float(scores[n - 1]) for n in range(1, 46)}

    # ------------------------------------------------------------------
    # backtest 기반 동적 가중치 갱신
    # ------------------------------------------------------------------
    def update_weights_from_backtest(self, backtest_results: dict) -> dict:
        """최근 N회차 hit 기여도 측정 -> Pillar 가중치 동적 갱신.

        Args:
            backtest_results: {
                "rounds": [
                    {"pillars": np.ndarray (45, 4), "actual": list[int]},
                    ...
                ],
                "window": int (option)
            }

        Returns:
            {success, n_rounds_used, hit_contrib, new_pillar_weights}
        """
        rounds = backtest_results.get("rounds") if isinstance(backtest_results, dict) else None
        if not isinstance(rounds, list) or not rounds:
            return {"success": False, "error": "no rounds in backtest_results"}

        win = int(backtest_results.get("window", _BACKTEST_WIN))
        recent = rounds[-win:] if len(rounds) > win else rounds

        # Pillar 별 hit 기여도: actual 번호의 Pillar 값 평균
        hit_contrib = np.zeros(4, dtype=np.float64)
        n_used = 0
        for r in recent:
            pillars = r.get("pillars") if isinstance(r, dict) else None
            actual = r.get("actual") if isinstance(r, dict) else None
            if pillars is None or actual is None:
                continue
            try:
                arr = np.asarray(pillars, dtype=np.float64)
            except Exception:
                continue
            if arr.shape != (45, 4):
                continue
            idx = [int(a) - 1 for a in actual if isinstance(a, int) and 1 <= a <= 45]
            if not idx:
                continue
            # 각 Pillar에서 actual 번호 점수 평균 - 전체 평균 (기여도)
            hit_mean = arr[idx].mean(axis=0)
            all_mean = arr.mean(axis=0)
            contrib = hit_mean - all_mean
            hit_contrib += contrib
            n_used += 1

        if n_used == 0:
            return {"success": False, "error": "no valid rounds"}

        # 양수 기여도만 사용 (음수는 0 클립), 정규화
        contrib_clip = np.clip(hit_contrib / n_used, a_min=0.0, a_max=None)
        s = contrib_clip.sum()
        if s > 1e-12:
            new_w = contrib_clip / s
        else:
            # 모든 기여 0 또는 음수 -> uniform
            new_w = np.full(4, 0.25, dtype=np.float64)

        # blend (기존 0.5 + 신규 0.5) — 급변 방지
        self.pillar_weights = 0.5 * self.pillar_weights + 0.5 * new_w
        s2 = self.pillar_weights.sum()
        if s2 > 0:
            self.pillar_weights = self.pillar_weights / s2

        return {
            "success": True,
            "n_rounds_used": int(n_used),
            "hit_contrib": [float(c) for c in (hit_contrib / n_used)],
            "new_pillar_weights": [float(w) for w in self.pillar_weights],
        }

    # ------------------------------------------------------------------
    # persistence
    # ------------------------------------------------------------------
    def save(self, path: str | None = None) -> str:
        """Ridge 계수 + 학습 fold 통계 + Pillar 가중치 저장."""
        target = str(path) if path else self.meta_path
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)

        coef: list[float] = []
        intercept: float = 0.0
        if self._ridge is not None and self._ridge_fitted:
            try:
                coef = [float(c) for c in np.asarray(self._ridge.coef_).ravel()]
                intercept = float(self._ridge.intercept_)
            except Exception:
                coef = []

        payload = {
            "pillar_names": PILLAR_NAMES,
            "ridge_alpha": _RIDGE_ALPHA,
            "ridge_coef": coef,
            "ridge_intercept": intercept,
            "ridge_fitted": bool(self._ridge_fitted),
            "p3_mu": self._p3_mu,
            "p3_sigma": self._p3_sigma,
            "p4_mu": self._p4_mu,
            "p4_sigma": self._p4_sigma,
            "pillar_weights": [float(w) for w in self.pillar_weights],
            "filter_weights": dict(self.filter_weights),
            "random_seed": self._seed,
        }
        with open(target, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        return target

    def load(self, path: str | None = None) -> bool:
        """저장된 Ridge 계수 + 통계 로드."""
        target = str(path) if path else self.meta_path
        if not os.path.exists(target):
            return False
        try:
            with open(target, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as e:
            print(f"[NumberScorer] load fail: {e}")
            return False

        self._p3_mu = float(payload.get("p3_mu", 0.0))
        self._p3_sigma = float(payload.get("p3_sigma", 1.0)) or 1.0
        self._p4_mu = float(payload.get("p4_mu", 0.0))
        self._p4_sigma = float(payload.get("p4_sigma", 1.0)) or 1.0

        pw = payload.get("pillar_weights")
        if isinstance(pw, list) and len(pw) == 4:
            arr = np.asarray(pw, dtype=np.float64)
            if arr.sum() > 0:
                self.pillar_weights = arr / arr.sum()

        fw = payload.get("filter_weights")
        if isinstance(fw, dict):
            self.filter_weights = {str(k): float(v) for k, v in fw.items()}

        coef = payload.get("ridge_coef")
        intercept = payload.get("ridge_intercept", 0.0)
        fitted = bool(payload.get("ridge_fitted", False))
        if fitted and isinstance(coef, list) and len(coef) == 4:
            self._ensure_ridge()
            if self._ridge is not None:
                # Ridge 재구성: coef_ / intercept_ 직접 주입
                # sklearn Ridge는 fit 없이 coef_ 주입 시 predict 가능
                self._ridge.coef_ = np.asarray(coef, dtype=np.float64)
                self._ridge.intercept_ = float(intercept)
                self._ridge_fitted = True
        return True

    def _try_load(self, path: str) -> None:
        """초기화 시 자동 로드 (실패해도 무시)."""
        try:
            self.load(path)
        except Exception as e:
            print(f"[NumberScorer] auto-load skip: {e}")


# ──────────────────────────────────────────────────────────────────────
# Smoke main
# ──────────────────────────────────────────────────────────────────────
def main() -> None:
    """smoke: 가짜 4 Pillar 입력 -> Ridge 학습 -> score_numbers + backtest 갱신 검증."""
    print("[NumberScorer] smoke start")

    rng = np.random.default_rng(_RANDOM_SEED)

    # 1. 가짜 4 Pillar 입력 1회분 (45, 4)
    fake_p1 = {n: float(rng.dirichlet(np.ones(45) * 0.6)[n - 1]) for n in range(1, 46)}
    fake_filter = [
        {"key": "total_sum",  "ml_recommendation": {"min": 100, "median": 132, "max": 165}},
        {"key": "tail_sum",   "ml_recommendation": {"min": 15, "median": 20, "max": 28}},
        {"key": "ac_value",   "ml_recommendation": {"min": 5, "median": 8, "max": 10}},
        {"key": "odd_even",   "ml_recommendation": {"top_class": 3}},
        {"key": "low_high",   "ml_recommendation": {"top_class": 3}},
        {"key": "carryover",  "ml_recommendation": {}},
        {"key": "neighbor_count", "ml_recommendation": {}},
        {"key": "prime_count", "ml_recommendation": {"median": 2}},
        {"key": "hot_cold",   "ml_recommendation": {"per_category": {"hot_pool": [3, 17, 23], "cold_pool": [1, 9, 44]}}},
        {"key": "missing_group", "ml_recommendation": {"per_category": {"missing_pool": [40, 41, 42]}}},
    ]
    fake_predictor = {
        "phase1": {
            "hotcold": {"per_category": {"hot_pool": [3, 17, 23, 38], "cold_pool": [1, 9, 44, 45]}},
            "missing_group": {"per_category": {"missing_pool": [40, 41, 42]}},
        },
        "regression": {
            "tier1": {"active_N_set": [3, 17, 23, 38]},
            "tier3_rules": {"recommended_numbers": [3, 38], "excluded_numbers": [44, 45]},
        },
    }
    fake_consensus = {
        n: {"consensus_score": float(rng.normal(loc=0, scale=10))}
        for n in range(1, 46)
    }
    # boost/sink 조정
    for n in [3, 17, 23, 38]:
        fake_consensus[n]["consensus_score"] += 15.0
    for n in [1, 9, 44, 45]:
        fake_consensus[n]["consensus_score"] -= 15.0

    fake_draws = [{"round": 1100, "numbers": [5, 12, 19, 28, 33, 41]}]

    # 2. NumberScorer 인스턴스
    tmp_path = os.path.join(os.path.dirname(__file__), "..", "saved_models", "_smoke_pillar_meta.json")
    tmp_path = os.path.abspath(tmp_path)
    scorer = NumberScorer(meta_path=tmp_path)

    # 3. 4 Pillar 매트릭스 산출
    mat = scorer.compute_4pillars(
        ensemble_probs=fake_p1,
        filter_stats_result=fake_filter,
        predictor_pipeline_outputs=fake_predictor,
        consensus_metrics=fake_consensus,
        draws_so_far=fake_draws,
    )
    print(f"  [1] compute_4pillars shape={mat.shape} dtype={mat.dtype}")
    print(f"      pillar_1 range = [{mat[:,0].min():.4f}, {mat[:,0].max():.4f}]")
    print(f"      pillar_2 range = [{mat[:,1].min():.4f}, {mat[:,1].max():.4f}]")
    print(f"      pillar_3 range = [{mat[:,2].min():.4f}, {mat[:,2].max():.4f}]")
    print(f"      pillar_4 range = [{mat[:,3].min():.4f}, {mat[:,3].max():.4f}]")
    assert mat.shape == (45, 4)

    # 4. 가짜 학습 데이터 (200 rounds * 45 numbers = 9000 samples)
    n_rounds = 200
    X_hist = np.zeros((n_rounds * 45, 4), dtype=np.float64)
    y_hist = np.zeros(n_rounds * 45, dtype=np.float64)
    for r_i in range(n_rounds):
        # Pillar 1: 합리적 prob (0~0.05)
        p1 = rng.dirichlet(np.ones(45) * 0.6)
        # Pillar 2: 0~1
        p2 = rng.uniform(0.3, 0.8, 45)
        # Pillar 3: -1~1
        p3 = rng.normal(0, 1, 45)
        # Pillar 4: -20~20
        p4 = rng.normal(0, 10, 45)

        # 라벨: Pillar 1, 4가 큰 번호일수록 출현 (가짜 ground-truth)
        true_score = 50 * p1 + 0.05 * p4 + 0.1 * p3
        actual_idx = np.argsort(-true_score)[:6]
        y = np.zeros(45)
        y[actual_idx] = 1.0

        block = np.column_stack([p1, p2, p3, p4])
        X_hist[r_i * 45:(r_i + 1) * 45] = block
        y_hist[r_i * 45:(r_i + 1) * 45] = y

    train_res = scorer.train_meta(X_hist, y_hist)
    print(f"\n  [2] train_meta: {train_res}")
    assert train_res["success"], "train_meta must succeed"
    assert len(train_res["coef"]) == 4

    # 5. score_numbers
    scores = scorer.score_numbers(
        ensemble_probs=fake_p1,
        filter_stats_result=fake_filter,
        predictor_pipeline_outputs=fake_predictor,
        consensus_metrics=fake_consensus,
        draws_so_far=fake_draws,
    )
    assert len(scores) == 45
    top5 = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:5]
    bot5 = sorted(scores.items(), key=lambda kv: kv[1])[:5]
    print(f"\n  [3] score_numbers top5    = {[(n, round(s,4)) for n,s in top5]}")
    print(f"      score_numbers bottom5 = {[(n, round(s,4)) for n,s in bot5]}")

    # boost 번호 (3, 17, 23, 38)가 top10에 일부 포함되어야 함
    top10_nums = {n for n, _ in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:10]}
    boost_in_top = top10_nums & {3, 17, 23, 38}
    print(f"      boost & top10 = {sorted(boost_in_top)}")
    assert len(boost_in_top) >= 1, "at least one boost number expected in top10"

    # 6. backtest 갱신
    backtest = {
        "rounds": [
            {
                "pillars": X_hist[r_i * 45:(r_i + 1) * 45],
                "actual": [int(i) + 1 for i in np.where(y_hist[r_i * 45:(r_i + 1) * 45] > 0)[0]],
            }
            for r_i in range(n_rounds)
        ],
        "window": 50,
    }
    upd = scorer.update_weights_from_backtest(backtest)
    print(f"\n  [4] update_weights_from_backtest: {upd}")
    assert upd["success"], "backtest update must succeed"
    assert len(upd["new_pillar_weights"]) == 4
    s_w = sum(upd["new_pillar_weights"])
    assert abs(s_w - 1.0) < 1e-6, f"weights must sum to 1, got {s_w}"

    # 7. save / load round-trip
    saved = scorer.save(tmp_path)
    print(f"\n  [5] save: {saved}")
    assert os.path.exists(saved)

    scorer2 = NumberScorer(meta_path=tmp_path)
    ok = scorer2.load(tmp_path)
    print(f"      load ok={ok}, pillar_weights={[round(w,4) for w in scorer2.pillar_weights]}")
    assert ok
    np.testing.assert_allclose(
        scorer.pillar_weights, scorer2.pillar_weights, rtol=1e-6,
        err_msg="pillar_weights must match after load",
    )

    # 8. 재현성 — score_numbers 동일 입력 동일 출력
    scores2 = scorer2.score_numbers(
        ensemble_probs=fake_p1,
        filter_stats_result=fake_filter,
        predictor_pipeline_outputs=fake_predictor,
        consensus_metrics=fake_consensus,
        draws_so_far=fake_draws,
    )
    diffs = [abs(scores[n] - scores2[n]) for n in range(1, 46)]
    print(f"\n  [6] reproducibility: max abs diff = {max(diffs):.6e}")
    assert max(diffs) < 1e-6, "scores must be reproducible after save/load"

    # 9. None fallback (predictor 미학습)
    scores_empty = scorer.score_numbers(
        ensemble_probs=None,
        filter_stats_result=None,
        predictor_pipeline_outputs=None,
        consensus_metrics=None,
        draws_so_far=None,
    )
    assert len(scores_empty) == 45
    print(f"\n  [7] None-fallback OK (45 scores)")

    # cleanup smoke artifact
    try:
        os.remove(tmp_path)
    except Exception:
        pass

    print("\n[NumberScorer] smoke OK")


if __name__ == "__main__":
    main()
