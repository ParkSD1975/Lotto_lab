"""필터별 통계 분석 엔진.

lotto_draws 데이터로부터 21+ 필터 유형의 통계를 계산하고
각 필터별 추천 범위/값 + 근거(evidence)를 생성한다.

사용 (기존 — predictor 미주입):
    from services.filter_stats import FilterStatsComputer
    computer = FilterStatsComputer(draws)  # draws: round 내림차순
    result = computer.compute_all()

사용 (Stage 1-4-A — predictor 주입):
    from predictors.phase1_registry import Phase1Registry
    from predictors.endings_predictor import EndingsPredictor
    from predictors.ac_predictor import ACPredictor
    from predictors.sum_predictor import SumPredictor

    p1 = Phase1Registry(); p1.register_default(); p1.train_all(draws)
    p2 = EndingsPredictor(); p2.train(draws)
    p3 = ACPredictor(); p3.train(draws)
    p4 = SumPredictor(); p4.train(draws)

    computer = FilterStatsComputer(
        draws,
        phase1_registry=p1, phase2_endings=p2,
        phase3_ac=p3, phase4_sum=p4,
    )
    result = computer.compute_all()

P2 추가: Poisson-Binomial PMF 기반 필터값 분포 계산
- count-type 22개 필터: PB PMF (O(n^2) DP, 정확)
- range-type 2개 (sum, tail_sum): 전체 45개 사용 개선 MC
- complex 2개 (ac, consecutive): 기존 방식 유지

Stage 1-4-A: 22 predictor 결과를 ml_recommendation 필드로 통합.
- predictor 미주입 시: 기존 동작 100% 유지 (ml_recommendation=None, fallback_used=True)
- predictor 주입 시: ml_recommendation 채워짐 (fallback_used=False)
"""

import math
from collections import Counter
from typing import Any, Callable

import numpy as np

# ──────────────────────────────────────────────────────────────────────────────
# P2: 모듈 상수 (Poisson-Binomial 적용 대상 필터 집합 및 속성 집합)
# ──────────────────────────────────────────────────────────────────────────────
PRIMES = {2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43}
COMPOSITES = {4, 6, 8, 9, 10, 12, 14, 15, 16, 18, 20, 21, 22, 24, 25, 26, 27, 28,
              30, 32, 33, 34, 35, 36, 38, 39, 40, 42, 44, 45}
SQUARES = {1, 4, 9, 16, 25, 36}
TRIANGULARS = {1, 3, 6, 10, 15, 21, 28, 36, 45}
TWINS = {11, 22, 33, 44}
MUL3 = {3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36, 39, 42, 45}
MUL4 = {4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44}
MUL5 = {5, 10, 15, 20, 25, 30, 35, 40, 45}
MUL7 = {7, 14, 21, 28, 35, 42}
MUL8 = {8, 16, 24, 32, 40}
MUL34 = MUL3 & MUL4
MUL35 = MUL3 & MUL5
MUL45 = MUL4 & MUL5
MULTIPLE_ALL = MUL3 | MUL4 | MUL5 | MUL7 | MUL8

# count-type 필터 이름 집합 (Poisson-Binomial 적용 대상)
# [Stage 1-4-D-2-fix-77] prime_hot/prime_cold 신설 — 최근 3회차 기준 핫/콜드 소수 세분화
# [Stage 1-4-D-2-fix-79] composite_hot/composite_cold 신설 — 동일 패턴 합성수 30개 분할
COUNT_TYPE_FILTERS = {
    "odd", "high", "prime", "prime_hot", "prime_cold",
    "composite", "composite_hot", "composite_cold",
    "square", "triangular", "twin",
    "mul3", "mul4", "mul5", "mul7", "mul8", "mul34", "mul35", "mul45", "non_multiple",
    "hot10", "neutral10", "cold10", "missing", "neighbor", "carryover",
    *{f"digit{i}" for i in range(10)},
}


# ──────────────────────────────────────────────────────────────────────────────
# P2: Poisson-Binomial PMF 계산
# ──────────────────────────────────────────────────────────────────────────────

def poisson_binomial_pmf(probs: list) -> np.ndarray:
    """DP로 정확한 Poisson-Binomial PMF 계산.

    Args:
        probs: 각 속성 번호의 출현 확률 리스트 (클램프 0~1 자동 적용)

    Returns:
        PMF 배열 [P(k=0), P(k=1), ..., P(k=len(probs))]
    """
    n = len(probs)
    dp = np.zeros(n + 1)
    dp[0] = 1.0
    for p in probs:
        p = min(1.0, max(0.0, float(p)))
        for k in range(len(dp) - 1, 0, -1):
            dp[k] = dp[k] * (1 - p) + dp[k - 1] * p
        dp[0] *= (1 - p)
    return dp


def pmf_percentile_range(pmf: np.ndarray, lo: float = 0.20, hi: float = 0.80) -> tuple:
    """PMF의 누적분포에서 lo~hi 분위수 구간 추출.

    Args:
        pmf: poisson_binomial_pmf() 반환값
        lo: 하한 분위수 (기본 0.20)
        hi: 상한 분위수 (기본 0.80)

    Returns:
        (lo_val, hi_val) 정수 튜플
    """
    cdf = np.cumsum(pmf)
    lo_val = int(np.searchsorted(cdf, lo, side="left"))
    hi_val = int(np.searchsorted(cdf, hi, side="left"))
    # 인덱스 범위 보호
    lo_val = min(lo_val, len(pmf) - 1)
    hi_val = min(hi_val, len(pmf) - 1)
    if lo_val > hi_val:
        lo_val, hi_val = hi_val, lo_val
    return lo_val, hi_val


def build_dynamic_attr_sets(history_draws: list) -> dict:
    """히스토리 기반 동적 집합 계산 (한 번만 계산, 재사용).

    Args:
        history_draws: 역순(최신->과거) 정렬된 당첨 이력

    Returns:
        {
            "hot10_nums": set,
            "neutral10_nums": set,
            "cold10_nums": set,
            "missing_nums": set,   # 10회 이상 미출현
            "latest_nums": set,    # 직전 회차 당첨번호 (이월수)
            "neighbor_nums": set,  # latest_nums의 +/-1 번호
            "prime_hot_nums": set, # [fix-77] 최근 3회차 등장 소수
            "prime_cold_nums": set,# [fix-77] 최근 3회차 미등장 소수
        }
    """
    # [fix-77/79] 최근 3회 핫/콜드 — 소수(PRIMES) + 합성수(COMPOSITES) 동일 패턴
    last_3 = [d.get("numbers", []) for d in history_draws[:3]]
    last_3_set: set = set()
    for draw_nums in last_3:
        for n in draw_nums:
            last_3_set.add(n)
    prime_hot_nums = PRIMES & last_3_set
    prime_cold_nums = PRIMES - last_3_set
    composite_hot_nums = COMPOSITES & last_3_set      # [fix-79]
    composite_cold_nums = COMPOSITES - last_3_set     # [fix-79]

    # 최근 10회 출현 빈도 (hot=3회이상 / neutral=1~2회 / cold=0회)
    last_10 = [d.get("numbers", []) for d in history_draws[:10]]
    appear_count: dict = {}
    for draw_nums in last_10:
        for n in draw_nums:
            appear_count[n] = appear_count.get(n, 0) + 1

    hot10_nums = {n for n in range(1, 46) if appear_count.get(n, 0) >= 3}
    neutral10_nums = {n for n in range(1, 46) if 1 <= appear_count.get(n, 0) <= 2}
    cold10_nums = {n for n in range(1, 46) if appear_count.get(n, 0) == 0}

    # 10회 이상 미출현 번호
    missing_nums: set = set()
    for n in range(1, 46):
        gap = 0
        for d in history_draws:
            if n in d.get("numbers", []):
                break
            gap += 1
        if gap >= 10:
            missing_nums.add(n)

    # 직전 회차 당첨번호 및 이웃수
    latest_nums = set(history_draws[0].get("numbers", [])) if history_draws else set()
    neighbor_nums: set = set()
    for n in latest_nums:
        for offset in (-1, 1):
            nb = n + offset
            if 1 <= nb <= 45:
                neighbor_nums.add(nb)

    return {
        "hot10_nums":          hot10_nums,
        "neutral10_nums":      neutral10_nums,
        "cold10_nums":         cold10_nums,
        "missing_nums":        missing_nums,
        "latest_nums":         latest_nums,
        "neighbor_nums":       neighbor_nums,
        "prime_hot_nums":      prime_hot_nums,        # [fix-77]
        "prime_cold_nums":     prime_cold_nums,       # [fix-77]
        "composite_hot_nums":  composite_hot_nums,    # [fix-79]
        "composite_cold_nums": composite_cold_nums,   # [fix-79]
    }


def get_attr_set(filter_name: str, dynamic_sets: dict):
    """filter_name -> 해당 속성 번호 집합 반환.

    count-type이 아닌 경우 None 반환.

    Args:
        filter_name: 필터 이름 문자열
        dynamic_sets: build_dynamic_attr_sets() 반환값

    Returns:
        set | None
    """
    if filter_name not in COUNT_TYPE_FILTERS:
        return None

    # 정적 집합
    static_map = {
        "odd":          {n for n in range(1, 46) if n % 2 == 1},
        "high":         {n for n in range(1, 46) if n >= 23},
        "prime":        PRIMES,
        "composite":    COMPOSITES,
        "square":       SQUARES,
        "triangular":   TRIANGULARS,
        "twin":         TWINS,
        "mul3":         MUL3,
        "mul4":         MUL4,
        "mul5":         MUL5,
        "mul7":         MUL7,
        "mul8":         MUL8,
        "mul34":        MUL34,
        "mul35":        MUL35,
        "mul45":        MUL45,
        "non_multiple": {n for n in range(1, 46) if n not in MULTIPLE_ALL},
    }

    if filter_name in static_map:
        return static_map[filter_name]

    # 동적 집합
    dynamic_map = {
        "hot10":      dynamic_sets.get("hot10_nums", set()),
        "neutral10":  dynamic_sets.get("neutral10_nums", set()),
        "cold10":     dynamic_sets.get("cold10_nums", set()),
        "missing":    dynamic_sets.get("missing_nums", set()),
        "neighbor":   dynamic_sets.get("neighbor_nums", set()),
        "carryover":  dynamic_sets.get("latest_nums", set()),
        # [fix-77] prime 핫/콜드 — 최근 3회차 등장/미등장 소수
        "prime_hot":      dynamic_sets.get("prime_hot_nums", set()),
        "prime_cold":     dynamic_sets.get("prime_cold_nums", set()),
        # [fix-79] composite 핫/콜드 — 동일 패턴 합성수 30개
        "composite_hot":  dynamic_sets.get("composite_hot_nums", set()),
        "composite_cold": dynamic_sets.get("composite_cold_nums", set()),
    }

    if filter_name in dynamic_map:
        return dynamic_map[filter_name]

    # digit0~9
    if filter_name.startswith("digit") and len(filter_name) == 6:
        try:
            d = int(filter_name[5])
            return {n for n in range(1, 46) if n % 10 == d}
        except ValueError:
            pass

    return None


def compute_pb_range(
    filter_name: str,
    model_probs: dict,
    dynamic_sets: dict,
    draw_size: int = 6,
    lo: float = 0.20,
    hi: float = 0.80,
) -> tuple:
    """Poisson-Binomial PMF로 count-type 필터 범위 계산.

    Args:
        filter_name: 필터 이름
        model_probs: 모델의 번호별 확률 {num: prob}
        dynamic_sets: build_dynamic_attr_sets() 반환값
        draw_size: 추첨 번호 개수 (기본 6)
        lo: 하한 분위수
        hi: 상한 분위수

    Returns:
        (lo_val, hi_val) — count-type이 아닌 경우 (0, 999)
    """
    attr_set = get_attr_set(filter_name, dynamic_sets)
    if attr_set is None:
        return (0, 999)

    if not attr_set:
        return (0, 0)

    # 입력 정규화 (BUGFIX): 모델별 출력 스케일 통일
    raw = {n: max(0.0, float(model_probs.get(n, 0.0))) for n in range(1, 46)}
    total = sum(raw.values())
    if total <= 0:
        return (0, 0)
    norm = {n: v / total for n, v in raw.items()}     # 합=1 정규화
    attr_probs = [
        min(1.0, draw_size * norm[n])                  # P(n in 6 picks)
        for n in attr_set
    ]
    pmf = poisson_binomial_pmf(attr_probs)
    return pmf_percentile_range(pmf, lo, hi)


def compute_mc_range_full(
    filter_fn,
    model_probs: dict,
    n_sim: int = 300,
    lo: float = 0.20,
    hi: float = 0.80,
) -> tuple:
    """개선된 MC: 전체 45개 번호를 사용하여 필터값 분포의 lo~hi 분위수 반환.

    기존 top-15 대신 전체 45개 번호 사용으로 정확도 향상.

    Args:
        filter_fn: 정렬된 조합 리스트를 받아 필터값을 반환하는 함수
        model_probs: 모델의 번호별 확률 {num: prob}
        n_sim: 시뮬레이션 횟수
        lo: 하한 분위수
        hi: 상한 분위수

    Returns:
        (lo_val, hi_val)
    """
    nums = list(range(1, 46))
    probs = np.array([float(model_probs.get(n, 0.0)) for n in nums], dtype=float)
    prob_sum = probs.sum()
    if prob_sum <= 0:
        probs = np.ones(45) / 45.0
    else:
        probs /= prob_sum  # 정규화

    vals = []
    for _ in range(n_sim):
        combo = sorted(np.random.choice(nums, 6, replace=False, p=probs).tolist())
        vals.append(filter_fn(combo))
    vals.sort()
    lo_idx = int(n_sim * lo)
    hi_idx = int(n_sim * hi)
    lo_idx = min(lo_idx, len(vals) - 1)
    hi_idx = min(hi_idx, len(vals) - 1)
    return vals[lo_idx], vals[hi_idx]

import config


# ──────────────────────────────────────────────────────────────────────────────
# Stage 1-4-A: predictor 출력 정규화 helper (모듈 레벨)
# ──────────────────────────────────────────────────────────────────────────────

def _safe_float(v: Any, default: float | None = None) -> float | None:
    """안전하게 float 변환 (None/NaN/예외 시 default)."""
    if v is None:
        return default
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except Exception:
        return default


def _icp_payload_to_ml_block(payload: dict, pool_size: int | None = None) -> dict:
    """ICP / categorical / special predictor 출력을 ml_recommendation 표준 블록으로 변환.

    payload 예시 (ICP):
        {
            "absolute_dist": [...7개],
            "expected_count": float,
            "current_pool_size": int,
            "top_class": int,
            "top_class_prob": float,
            "narrative": str,
            "model_contributions": {...},
        }
    """
    if not isinstance(payload, dict):
        return {
            "min": None,
            "max": None,
            "median": None,
            "narrative": "invalid payload",
            "model_contributions": {},
        }

    expected = _safe_float(payload.get("expected_count"))
    top_class = payload.get("top_class")
    top_prob = _safe_float(payload.get("top_class_prob"))
    abs_dist = payload.get("absolute_dist") or []
    narrative = payload.get("narrative") or ""
    contributions = payload.get("model_contributions") or {}
    M = int(pool_size) if pool_size is not None else int(payload.get("current_pool_size") or payload.get("pool_size") or 0)

    # quantile 추출 (CDF on 7-class dist, classes = 0..6)
    q10 = q50 = q90 = None
    try:
        if abs_dist:
            arr = np.asarray(abs_dist, dtype=np.float64)
            s = arr.sum()
            if s > 0:
                arr = arr / s
                cdf = np.cumsum(arr)
                q10 = int(np.searchsorted(cdf, 0.10, side="left"))
                q50 = int(np.searchsorted(cdf, 0.50, side="left"))
                q90 = int(np.searchsorted(cdf, 0.90, side="left"))
                last = len(arr) - 1
                q10 = min(max(q10, 0), last)
                q50 = min(max(q50, 0), last)
                q90 = min(max(q90, 0), last)
    except Exception:
        pass

    # quantile 산출 실패 시 expected_count 기반 fallback
    if q50 is None and expected is not None:
        q50 = int(round(expected))
    if q10 is None and q50 is not None:
        q10 = max(0, q50 - 1)
    if q90 is None and q50 is not None:
        q90 = q50 + 1

    block = {
        "min": q10,
        "max": q90,
        "median": q50,
        "expected_count": expected,
        "top_class": top_class,
        "top_class_prob": top_prob,
        "absolute_dist": list(abs_dist) if abs_dist else None,
        "pool_size": M if M > 0 else None,
        "narrative": narrative,
        "model_contributions": dict(contributions) if isinstance(contributions, dict) else {},
    }
    return block


def _scalar_predictor_to_ml_block(payload: dict, extra_keys: tuple = ()) -> dict:
    """endings/ac/sum predictor 출력을 ml_recommendation 표준 블록으로 변환.

    각 predictor는 q10/q50/q90 (scalar 형태) + components 등을 반환.
    """
    if not isinstance(payload, dict):
        return {
            "min": None,
            "max": None,
            "median": None,
            "narrative": "invalid payload",
            "model_contributions": {},
        }

    # endings_predictor의 경우 scalar key 안에 q10/q50/q90 있음
    scalar = payload.get("scalar")
    if isinstance(scalar, dict):
        q10 = _safe_float(scalar.get("q10"))
        q50 = _safe_float(scalar.get("q50"))
        q90 = _safe_float(scalar.get("q90"))
    else:
        q10 = _safe_float(payload.get("q10"))
        q50 = _safe_float(payload.get("q50"))
        q90 = _safe_float(payload.get("q90"))

    components = payload.get("components") or {}
    contrib = {}
    if isinstance(components, dict):
        for k, v in components.items():
            f = _safe_float(v)
            if f is not None:
                contrib[k] = f

    block = {
        "min": q10,
        "max": q90,
        "median": q50,
        "narrative": payload.get("narrative") or "",
        "model_contributions": contrib,
    }
    # 추가 키 노출 (carrier_quartet, nbeats_decomposition, distribution_10d 등)
    for k in extra_keys:
        if k in payload:
            block[k] = payload[k]
    return block


class FilterStatsComputer:
    """모든 필터 유형에 대한 통계를 계산한다."""

    def __init__(
        self,
        draws: list[dict],
        recent_n: int = 50,
        phase1_registry: Any | None = None,
        phase2_endings: Any | None = None,
        phase3_ac: Any | None = None,
        phase4_sum: Any | None = None,
    ):
        """
        Args:
            draws: lotto_draws 테이블 데이터 (round 내림차순)
            recent_n: '최근' 기준 회차 수
            phase1_registry: Phase1Registry 인스턴스 (선택, 16~17 predictor)
            phase2_endings: EndingsPredictor 인스턴스 (선택)
            phase3_ac: ACPredictor 인스턴스 (선택)
            phase4_sum: SumPredictor 인스턴스 (선택)

        predictor가 모두 None이면 기존 룰베이스만 동작 (회귀 호환).
        """
        self.draws = draws
        self.recent_n = recent_n
        self.all_numbers = [d.get("numbers", []) for d in draws if d.get("numbers")]
        self.recent_numbers = self.all_numbers[:recent_n]
        self.total_rounds = len(self.all_numbers)
        self.recent_rounds = len(self.recent_numbers)

        # Stage 1-4-A: predictor 주입
        self.phase1_registry = phase1_registry
        self.phase2_endings = phase2_endings
        self.phase3_ac = phase3_ac
        self.phase4_sum = phase4_sum

        # Phase1 predict_all 캐시 (한 회차 분석에서 17 메서드가 같은 출력 공유)
        self._phase1_cache: dict | None = None
        self._phase2_cache: dict | None = None
        self._phase3_cache: dict | None = None
        self._phase4_cache: dict | None = None

    # ─────────────────────────────────────────
    # Stage 1-4-A: predictor 호출 helper
    # ─────────────────────────────────────────

    def _try_predictor_call(self, predictor_name: str, fn: Callable) -> Any | None:
        """predictor 호출 실패 시 None 반환 + ASCII 로그."""
        try:
            return fn()
        except Exception as e:
            print(f"  [filter_stats] {predictor_name} fail: {type(e).__name__}: {e}")
            return None

    def _get_phase1_outputs(self) -> dict | None:
        """Phase1Registry.predict_all 결과 캐시. 없으면 None."""
        if self.phase1_registry is None:
            return None
        if self._phase1_cache is not None:
            return self._phase1_cache
        result = self._try_predictor_call(
            "phase1_registry.predict_all",
            lambda: self.phase1_registry.predict_all(self.draws),
        )
        if result is not None:
            self._phase1_cache = result
        return result

    def _get_phase2_endings_output(self, phase1_outputs: dict | None = None) -> dict | None:
        if self.phase2_endings is None:
            return None
        if self._phase2_cache is not None:
            return self._phase2_cache
        result = self._try_predictor_call(
            "phase2_endings.predict",
            lambda: self.phase2_endings.predict(self.draws, phase1_outputs=phase1_outputs),
        )
        if result is not None:
            self._phase2_cache = result
        return result

    def _get_phase3_ac_output(
        self,
        phase1_outputs: dict | None = None,
        phase2_endings: dict | None = None,
    ) -> dict | None:
        if self.phase3_ac is None:
            return None
        if self._phase3_cache is not None:
            return self._phase3_cache
        result = self._try_predictor_call(
            "phase3_ac.predict",
            lambda: self.phase3_ac.predict(
                self.draws,
                phase1_outputs=phase1_outputs,
                phase2_endings=phase2_endings,
            ),
        )
        if result is not None:
            self._phase3_cache = result
        return result

    def _get_phase4_sum_output(
        self,
        phase1_outputs: dict | None = None,
        phase2_endings: dict | None = None,
        phase3_ac: dict | None = None,
    ) -> dict | None:
        if self.phase4_sum is None:
            return None
        if self._phase4_cache is not None:
            return self._phase4_cache
        result = self._try_predictor_call(
            "phase4_sum.predict",
            lambda: self.phase4_sum.predict(
                self.draws,
                phase1_outputs=phase1_outputs,
                phase2_endings=phase2_endings,
                phase3_ac=phase3_ac,
            ),
        )
        if result is not None:
            self._phase4_cache = result
        return result

    def _attach_ml_block(self, base: dict, ml_block: dict | None) -> dict:
        """결과 dict에 ml_recommendation / fallback_used 필드 부착."""
        if ml_block is not None:
            base["ml_recommendation"] = ml_block
            base["fallback_used"] = False
        else:
            base["ml_recommendation"] = None
            base["fallback_used"] = True
        return base

    def _phase1_payload(self, key: str) -> dict | None:
        """Phase1Registry predict_all 출력에서 특정 indicator payload 추출.

        ICP 직접 인스턴스(digit/decade/gung/multiple)는 indicator + per_category dict.
        그 외(categorical/special/missing/hotcold/lotto_paper)는 predictor별 형식.
        """
        outs = self._get_phase1_outputs()
        if outs is None:
            return None
        payload = outs.get(key)
        if payload is None:
            return None
        if isinstance(payload, dict) and "error" in payload:
            return None
        return payload

    def compute_all(self) -> list[dict]:
        """모든 필터에 대한 통계를 계산하여 리스트로 반환한다."""
        filters = [
            self._total_sum(),
            self._tail_sum(),
            self._ac_value(),
            self._odd_even(),
            self._low_high(),
            self._consecutive(),
            self._carryover(),
            self._prime_count(),
            self._composite_count(),
            self._square_count(),
            self._triangular_count(),
            self._twin_count(),
            self._hot_cold(),
            self._number_range(),
            self._neighbor_count(),
            self._multiple_3(),
            self._multiple_7(),
            self._multiple_8(),
            self._zone_pattern(),
            self._decade_distribution(),
            self._missing_group(),
        ]
        return filters

    # ─────────────────────────────────────────
    # 1. 총합 (Total Sum) — Phase 4 sum_predictor
    # ─────────────────────────────────────────
    def _total_sum(self) -> dict:
        all_vals = [sum(nums) for nums in self.all_numbers]
        recent_vals = [sum(nums) for nums in self.recent_numbers]
        base = self._build_range_filter(
            key="total_sum",
            name="총합 (Total Sum)",
            icon="functions",
            all_vals=all_vals,
            recent_vals=recent_vals,
            description="6개 번호의 합계. 역대 평균 약 133, 표준편차 약 32.",
        )

        # ML: phase4_sum (q10/q50/q90 + carrier_quartet + nbeats_decomposition)
        ml_block = None
        phase1_outs = self._get_phase1_outputs()
        phase2_out = self._get_phase2_endings_output(phase1_outs)
        phase3_out = self._get_phase3_ac_output(phase1_outs, phase2_out)
        phase4_out = self._get_phase4_sum_output(phase1_outs, phase2_out, phase3_out)
        if phase4_out is not None:
            ml_block = _scalar_predictor_to_ml_block(
                phase4_out,
                extra_keys=("carrier_quartet", "carrier_consistency", "nbeats_decomposition"),
            )

        return self._attach_ml_block(base, ml_block)

    # ─────────────────────────────────────────
    # 2. 끝수합 (Tail Digit Sum) — Phase 2 endings_predictor
    # ─────────────────────────────────────────
    def _tail_sum(self) -> dict:
        def calc(nums):
            return sum(n % 10 for n in nums)

        all_vals = [calc(nums) for nums in self.all_numbers]
        recent_vals = [calc(nums) for nums in self.recent_numbers]
        base = self._build_range_filter(
            key="tail_sum",
            name="끝수합 (Tail Sum)",
            icon="pin",
            all_vals=all_vals,
            recent_vals=recent_vals,
            description="각 번호의 일의 자리 합계.",
        )

        ml_block = None
        phase1_outs = self._get_phase1_outputs()
        phase2_out = self._get_phase2_endings_output(phase1_outs)
        if phase2_out is not None:
            ml_block = _scalar_predictor_to_ml_block(
                phase2_out,
                extra_keys=("distribution_10d", "consistency_check"),
            )

        return self._attach_ml_block(base, ml_block)

    # ─────────────────────────────────────────
    # 3. AC값 (Arithmetic Complexity) — Phase 3 ac_predictor
    # ─────────────────────────────────────────
    def _ac_value(self) -> dict:
        def calc(nums):
            diffs = set()
            for i in range(len(nums)):
                for j in range(i + 1, len(nums)):
                    diffs.add(abs(nums[i] - nums[j]))
            return len(diffs) - (len(nums) - 1)  # AC = diff_count - 5

        all_vals = [calc(nums) for nums in self.all_numbers]
        recent_vals = [calc(nums) for nums in self.recent_numbers]
        base = self._build_range_filter(
            key="ac_value",
            name="AC값 (Arithmetic Complexity)",
            icon="calculate",
            all_vals=all_vals,
            recent_vals=recent_vals,
            description="번호 간 차이값의 다양성 지표. 높을수록 고루 분포.",
        )

        ml_block = None
        phase1_outs = self._get_phase1_outputs()
        phase2_out = self._get_phase2_endings_output(phase1_outs)
        phase3_out = self._get_phase3_ac_output(phase1_outs, phase2_out)
        if phase3_out is not None:
            ml_block = _scalar_predictor_to_ml_block(
                phase3_out,
                extra_keys=("markov_11state_dist",),
            )

        return self._attach_ml_block(base, ml_block)

    # ─────────────────────────────────────────
    # 4. 홀짝 비율 (Odd/Even) — Phase 1 categorical_odd_even
    # ─────────────────────────────────────────
    def _odd_even(self) -> dict:
        def calc(nums):
            return sum(1 for n in nums if n % 2 == 1)

        all_vals = [calc(nums) for nums in self.all_numbers]
        recent_vals = [calc(nums) for nums in self.recent_numbers]

        all_patterns = [f"{v}:{6 - v}" for v in all_vals]
        recent_patterns = [f"{v}:{6 - v}" for v in recent_vals]

        base = self._build_range_filter(
            key="odd_even",
            name="홀짝 비율 (Odd:Even)",
            icon="contrast",
            all_vals=all_vals,
            recent_vals=recent_vals,
            description="6개 번호 중 홀수 개수. 패턴은 홀:짝 형태.",
        )

        # 패턴별 분포
        all_counter = Counter(all_patterns)
        recent_counter = Counter(recent_patterns)
        patterns = []
        for pat in sorted(all_counter.keys(), key=lambda x: all_counter[x], reverse=True):
            patterns.append({
                "pattern": pat,
                "all_count": all_counter[pat],
                "all_pct": round(all_counter[pat] / self.total_rounds * 100, 1),
                "recent_count": recent_counter.get(pat, 0),
                "recent_pct": round(recent_counter.get(pat, 0) / max(self.recent_rounds, 1) * 100, 1),
            })
        base["patterns"] = patterns

        # ML: categorical_odd_even
        ml_block = None
        payload = self._phase1_payload("categorical_odd_even")
        if payload is not None:
            ml_block = _icp_payload_to_ml_block(payload)
        return self._attach_ml_block(base, ml_block)

    # ─────────────────────────────────────────
    # 5. 저고 비율 (Low/High) — Phase 1 categorical_low_high
    # ─────────────────────────────────────────
    def _low_high(self) -> dict:
        def calc(nums):
            return sum(1 for n in nums if n <= 22)

        all_vals = [calc(nums) for nums in self.all_numbers]
        recent_vals = [calc(nums) for nums in self.recent_numbers]

        all_patterns = [f"{v}:{6 - v}" for v in all_vals]
        recent_patterns = [f"{v}:{6 - v}" for v in recent_vals]

        base = self._build_range_filter(
            key="low_high",
            name="저고 비율 (Low:High)",
            icon="swap_vert",
            all_vals=all_vals,
            recent_vals=recent_vals,
            description="22이하(저) vs 23이상(고) 비율.",
        )

        all_counter = Counter(all_patterns)
        recent_counter = Counter(recent_patterns)
        patterns = []
        for pat in sorted(all_counter.keys(), key=lambda x: all_counter[x], reverse=True):
            patterns.append({
                "pattern": pat,
                "all_count": all_counter[pat],
                "all_pct": round(all_counter[pat] / self.total_rounds * 100, 1),
                "recent_count": recent_counter.get(pat, 0),
                "recent_pct": round(recent_counter.get(pat, 0) / max(self.recent_rounds, 1) * 100, 1),
            })
        base["patterns"] = patterns

        ml_block = None
        payload = self._phase1_payload("categorical_low_high")
        if payload is not None:
            ml_block = _icp_payload_to_ml_block(payload)
        return self._attach_ml_block(base, ml_block)

    # ─────────────────────────────────────────
    # 6. 연속번호 (Consecutive Numbers) — Phase 1 categorical_consecutive
    # ─────────────────────────────────────────
    def _consecutive(self) -> dict:
        def calc(nums):
            s = sorted(nums)
            return sum(1 for i in range(len(s) - 1) if s[i + 1] - s[i] == 1)

        all_vals = [calc(nums) for nums in self.all_numbers]
        recent_vals = [calc(nums) for nums in self.recent_numbers]
        base = self._build_range_filter(
            key="consecutive",
            name="연속번호 (Consecutive)",
            icon="linear_scale",
            all_vals=all_vals,
            recent_vals=recent_vals,
            description="인접 연속번호 쌍의 개수.",
        )

        ml_block = None
        payload = self._phase1_payload("categorical_consecutive")
        if payload is not None:
            ml_block = _icp_payload_to_ml_block(payload)
        return self._attach_ml_block(base, ml_block)

    # ─────────────────────────────────────────
    # 7. 이월수 (Carryover) — Phase 1 categorical_carryover_exact
    # ─────────────────────────────────────────
    def _carryover(self) -> dict:
        all_vals = []
        for i in range(len(self.all_numbers) - 1):
            curr = set(self.all_numbers[i])
            prev = set(self.all_numbers[i + 1])
            all_vals.append(len(curr & prev))
        recent_vals = all_vals[:self.recent_n]

        base = self._build_range_filter(
            key="carryover",
            name="이월수 (Carryover)",
            icon="replay",
            all_vals=all_vals,
            recent_vals=recent_vals,
            description="직전 회차와 동일한 번호 개수.",
        )

        ml_block = None
        payload = self._phase1_payload("categorical_carryover_exact")
        if payload is not None:
            ml_block = _icp_payload_to_ml_block(payload)
        return self._attach_ml_block(base, ml_block)

    # ─────────────────────────────────────────
    # 8. 소수 개수 (Prime Count) — Phase 1 special_prime
    # ─────────────────────────────────────────
    def _prime_count(self) -> dict:
        def calc(nums):
            return sum(1 for n in nums if n in config.PRIMES)

        all_vals = [calc(nums) for nums in self.all_numbers]
        recent_vals = [calc(nums) for nums in self.recent_numbers]
        base = self._build_range_filter(
            key="prime_count",
            name="소수 개수 (Prime)",
            icon="looks_one",
            all_vals=all_vals,
            recent_vals=recent_vals,
            description="6개 중 소수(2,3,5,7,11,13,17,19,23,29,31,37,41,43)의 개수.",
        )

        ml_block = None
        payload = self._phase1_payload("special_prime")
        if payload is not None:
            ml_block = _icp_payload_to_ml_block(payload)
        return self._attach_ml_block(base, ml_block)

    # ─────────────────────────────────────────
    # 9. 합성수 개수 (Composite Count) — Phase 1 special_composite
    # ─────────────────────────────────────────
    def _composite_count(self) -> dict:
        non_primes = set(range(1, 46)) - config.PRIMES - {1}

        def calc(nums):
            return sum(1 for n in nums if n in non_primes)

        all_vals = [calc(nums) for nums in self.all_numbers]
        recent_vals = [calc(nums) for nums in self.recent_numbers]
        base = self._build_range_filter(
            key="composite_count",
            name="합성수 개수 (Composite)",
            icon="looks_two",
            all_vals=all_vals,
            recent_vals=recent_vals,
            description="6개 중 합성수(1과 소수를 제외한 자연수)의 개수.",
        )

        ml_block = None
        payload = self._phase1_payload("special_composite")
        if payload is not None:
            ml_block = _icp_payload_to_ml_block(payload)
        return self._attach_ml_block(base, ml_block)

    # ─────────────────────────────────────────
    # 10. 제곱수 개수 (Square Count) — Phase 1 special_square
    # ─────────────────────────────────────────
    def _square_count(self) -> dict:
        def calc(nums):
            return sum(1 for n in nums if n in config.SQUARES)

        all_vals = [calc(nums) for nums in self.all_numbers]
        recent_vals = [calc(nums) for nums in self.recent_numbers]
        base = self._build_range_filter(
            key="square_count",
            name="제곱수 개수 (Square)",
            icon="crop_square",
            all_vals=all_vals,
            recent_vals=recent_vals,
            description="6개 중 제곱수(1,4,9,16,25,36)의 개수.",
        )

        ml_block = None
        payload = self._phase1_payload("special_square")
        if payload is not None:
            ml_block = _icp_payload_to_ml_block(payload)
        return self._attach_ml_block(base, ml_block)

    # ─────────────────────────────────────────
    # 11. 삼각수 개수 (Triangular Count) — Phase 1 special_triangular
    # ─────────────────────────────────────────
    def _triangular_count(self) -> dict:
        def calc(nums):
            return sum(1 for n in nums if n in config.TRIANGULARS)

        all_vals = [calc(nums) for nums in self.all_numbers]
        recent_vals = [calc(nums) for nums in self.recent_numbers]
        base = self._build_range_filter(
            key="triangular_count",
            name="삼각수 개수 (Triangular)",
            icon="change_history",
            all_vals=all_vals,
            recent_vals=recent_vals,
            description="6개 중 삼각수(1,3,6,10,15,21,28,36,45)의 개수.",
        )

        ml_block = None
        payload = self._phase1_payload("special_triangular")
        if payload is not None:
            ml_block = _icp_payload_to_ml_block(payload)
        return self._attach_ml_block(base, ml_block)

    # ─────────────────────────────────────────
    # 12. 쌍수 (Twin Numbers) — Phase 1 special_twin
    # ─────────────────────────────────────────
    def _twin_count(self) -> dict:
        def calc(nums):
            """같은 끝자리를 가진 번호 쌍 수."""
            tails = [n % 10 for n in nums]
            cnt = Counter(tails)
            return sum(v - 1 for v in cnt.values() if v > 1)

        all_vals = [calc(nums) for nums in self.all_numbers]
        recent_vals = [calc(nums) for nums in self.recent_numbers]
        base = self._build_range_filter(
            key="twin_count",
            name="쌍수 (Twin Numbers)",
            icon="group",
            all_vals=all_vals,
            recent_vals=recent_vals,
            description="같은 끝자리를 가진 번호 쌍의 수.",
        )

        ml_block = None
        payload = self._phase1_payload("special_twin")
        if payload is not None:
            ml_block = _icp_payload_to_ml_block(payload)
        return self._attach_ml_block(base, ml_block)

    # ─────────────────────────────────────────
    # 13. 핫/콜드 (최근 출현빈도) — Phase 1 hotcold
    # ─────────────────────────────────────────
    def _hot_cold(self) -> dict:
        # 최근 10회 출현 빈도
        recent_10 = self.all_numbers[:10]
        freq = Counter()
        for nums in recent_10:
            freq.update(nums)

        hot_nums = [n for n, _ in freq.most_common(10)]
        cold_nums = [n for n in range(1, 46) if freq.get(n, 0) == 0]
        if len(cold_nums) < 5:
            cold_nums = [n for n, _ in freq.most_common()[-10:]]

        # 최근 10회 평균 핫넘버 적중수
        all_vals = []
        for nums in self.all_numbers:
            hit = sum(1 for n in nums if n in hot_nums)
            all_vals.append(hit)
        recent_vals = all_vals[:self.recent_n]

        base = self._build_range_filter(
            key="hot_cold",
            name="핫/콜드 분석 (Hot/Cold)",
            icon="local_fire_department",
            all_vals=all_vals,
            recent_vals=recent_vals,
            description="최근 10회 출현 빈도 기반 핫넘버 적중 수.",
        )
        base["hot_numbers"] = hot_nums[:10]
        base["cold_numbers"] = cold_nums[:10]

        # ML: hotcold predictor의 per_category 12 카테고리 — narrative 통합
        ml_block = None
        payload = self._phase1_payload("hotcold")
        if isinstance(payload, dict) and "per_category" in payload:
            per_cat = payload["per_category"]
            # 카테고리별 narrative 통합
            narratives = []
            sub_categories = {}
            for label, cat_payload in (per_cat or {}).items():
                if not isinstance(cat_payload, dict):
                    continue
                sub_block = _icp_payload_to_ml_block(cat_payload, pool_size=cat_payload.get("dynamic_pool_size"))
                sub_block["members"] = cat_payload.get("members", [])
                sub_categories[label] = sub_block
                if cat_payload.get("narrative"):
                    narratives.append(f"{label}: {cat_payload['narrative']}")
            ml_block = {
                "min": None,
                "max": None,
                "median": None,
                "narrative": " | ".join(narratives[:4]) if narratives else "hotcold ready",
                "model_contributions": {},
                "per_category": sub_categories,
                "dynamic_pool_sizes": payload.get("dynamic_pool_sizes"),
                "windows": payload.get("windows"),
                "groups": payload.get("groups"),
            }
        return self._attach_ml_block(base, ml_block)

    # ─────────────────────────────────────────
    # 14. 번호 범위 (Number Range = max - min) — Phase 1 decade_distribution
    # ─────────────────────────────────────────
    def _number_range(self) -> dict:
        def calc(nums):
            return max(nums) - min(nums)

        all_vals = [calc(nums) for nums in self.all_numbers]
        recent_vals = [calc(nums) for nums in self.recent_numbers]
        base = self._build_range_filter(
            key="number_range",
            name="번호 범위 (Range)",
            icon="expand",
            all_vals=all_vals,
            recent_vals=recent_vals,
            description="최대번호 - 최소번호. 번호의 분산도 지표.",
        )

        # ML: decade_distribution payload (5 카테고리 분포 -> 범위 지표 reference)
        ml_block = None
        payload = self._phase1_payload("decade_distribution")
        if isinstance(payload, dict) and "per_category" in payload:
            per_cat = payload["per_category"]
            sub_categories = {}
            narratives = []
            for label, cat_payload in (per_cat or {}).items():
                if not isinstance(cat_payload, dict):
                    continue
                sub_categories[label] = _icp_payload_to_ml_block(cat_payload)
                if cat_payload.get("narrative"):
                    narratives.append(cat_payload["narrative"])
            ml_block = {
                "min": None,
                "max": None,
                "median": None,
                "narrative": " | ".join(narratives[:3]) if narratives else "decade ready",
                "model_contributions": {},
                "per_category": sub_categories,
                "indicator": "decade_distribution",
            }
        return self._attach_ml_block(base, ml_block)

    # ─────────────────────────────────────────
    # 15. 이웃수 (Neighbor Count) — Phase 1 categorical_neighbor
    # ─────────────────────────────────────────
    def _neighbor_count(self) -> dict:
        """직전회차 번호의 +/-1 범위에 있는 번호 개수."""
        all_vals = []
        for i in range(len(self.all_numbers) - 1):
            curr = self.all_numbers[i]
            prev = set(self.all_numbers[i + 1])
            neighbors = set()
            for p in prev:
                neighbors.update([p - 1, p, p + 1])
            hit = sum(1 for n in curr if n in neighbors)
            all_vals.append(hit)
        recent_vals = all_vals[:self.recent_n]

        base = self._build_range_filter(
            key="neighbor_count",
            name="이웃수 (Neighbor)",
            icon="share_location",
            all_vals=all_vals,
            recent_vals=recent_vals,
            description="직전 회차 번호의 +/-1 범위에 해당하는 번호 개수.",
        )

        ml_block = None
        payload = self._phase1_payload("categorical_neighbor")
        if payload is not None:
            ml_block = _icp_payload_to_ml_block(payload)
        return self._attach_ml_block(base, ml_block)

    # ─────────────────────────────────────────
    # 16. 3의 배수 개수 — Phase 1 multiple_distribution[m3]
    # ─────────────────────────────────────────
    def _multiple_3(self) -> dict:
        def calc(nums):
            return sum(1 for n in nums if n % 3 == 0)

        all_vals = [calc(nums) for nums in self.all_numbers]
        recent_vals = [calc(nums) for nums in self.recent_numbers]
        base = self._build_range_filter(
            key="multiple_3",
            name="3의 배수 개수",
            icon="filter_3",
            all_vals=all_vals,
            recent_vals=recent_vals,
            description="6개 중 3의 배수(3,6,9,...,45)의 개수.",
        )

        ml_block = self._extract_multiple_ml("m3")
        return self._attach_ml_block(base, ml_block)

    # ─────────────────────────────────────────
    # 16b. 7의 배수 개수 — Phase 1 multiple_distribution[m7]
    # ─────────────────────────────────────────
    def _multiple_7(self) -> dict:
        MUL7_LOCAL = {7, 14, 21, 28, 35, 42}

        def calc(nums):
            return sum(1 for n in nums if n in MUL7_LOCAL)

        all_vals = [calc(nums) for nums in self.all_numbers]
        recent_vals = [calc(nums) for nums in self.recent_numbers]
        base = self._build_range_filter(
            key="multiple_7",
            name="7의 배수 개수",
            icon="filter_7",
            all_vals=all_vals,
            recent_vals=recent_vals,
            description="6개 중 7의 배수(7,14,21,28,35,42)의 개수.",
        )

        ml_block = self._extract_multiple_ml("m7")
        return self._attach_ml_block(base, ml_block)

    # ─────────────────────────────────────────
    # 16c. 8의 배수 개수 — Phase 1 multiple_distribution[m8]
    # ─────────────────────────────────────────
    def _multiple_8(self) -> dict:
        MUL8_LOCAL = {8, 16, 24, 32, 40}

        def calc(nums):
            return sum(1 for n in nums if n in MUL8_LOCAL)

        all_vals = [calc(nums) for nums in self.all_numbers]
        recent_vals = [calc(nums) for nums in self.recent_numbers]
        base = self._build_range_filter(
            key="multiple_8",
            name="8의 배수 개수",
            icon="filter_8",
            all_vals=all_vals,
            recent_vals=recent_vals,
            description="6개 중 8의 배수(8,16,24,32,40)의 개수.",
        )

        ml_block = self._extract_multiple_ml("m8")
        return self._attach_ml_block(base, ml_block)

    def _extract_multiple_ml(self, label_key: str) -> dict | None:
        """multiple_distribution payload에서 특정 카테고리(m3/m4/m5/m7/m8/other) 추출."""
        payload = self._phase1_payload("multiple_distribution")
        if not isinstance(payload, dict):
            return None
        per_cat = payload.get("per_category") or {}
        cat_payload = per_cat.get(label_key)
        if not isinstance(cat_payload, dict):
            return None
        return _icp_payload_to_ml_block(cat_payload)

    # ─────────────────────────────────────────
    # 17. 구간 패턴 (Zone 1~15/16~30/31~45) — Phase 1 lotto_paper (보조)
    # ─────────────────────────────────────────
    def _zone_pattern(self) -> dict:
        def calc(nums):
            z1 = sum(1 for n in nums if 1 <= n <= 15)
            z2 = sum(1 for n in nums if 16 <= n <= 30)
            z3 = sum(1 for n in nums if 31 <= n <= 45)
            return f"{z1}:{z2}:{z3}"

        all_patterns = [calc(nums) for nums in self.all_numbers]
        recent_patterns = [calc(nums) for nums in self.recent_numbers]

        all_counter = Counter(all_patterns)
        recent_counter = Counter(recent_patterns)

        patterns = []
        for pat in sorted(all_counter.keys(), key=lambda x: all_counter[x], reverse=True):
            patterns.append({
                "pattern": pat,
                "all_count": all_counter[pat],
                "all_pct": round(all_counter[pat] / self.total_rounds * 100, 1),
                "recent_count": recent_counter.get(pat, 0),
                "recent_pct": round(recent_counter.get(pat, 0) / max(self.recent_rounds, 1) * 100, 1),
            })

        # 상위 5개 패턴 추천
        top_patterns = patterns[:5]
        evidence = f"역대 {self.total_rounds}회 중 상위 패턴: "
        evidence += ", ".join(f"{p['pattern']}({p['all_pct']}%)" for p in top_patterns[:3])
        evidence += f". 최근 {self.recent_rounds}회 1위: {patterns[0]['pattern'] if patterns else '-'}"

        result = {
            "key": "zone_pattern",
            "name": "구간 패턴 (Zone)",
            "icon": "view_column",
            "type": "pattern",
            "description": "1~15/16~30/31~45 구간별 번호 분배 패턴.",
            "patterns": patterns[:10],
            "recommendation": {
                "recommended_patterns": [p["pattern"] for p in top_patterns[:3]],
                "evidence": evidence,
            },
        }

        # ML: lotto_paper predictor (14 카테고리 — row+col)
        ml_block = None
        payload = self._phase1_payload("lotto_paper")
        if isinstance(payload, dict) and ("per_row" in payload or "per_col" in payload):
            per_row_in = payload.get("per_row") or {}
            per_col_in = payload.get("per_col") or {}
            per_row_blk = {k: _icp_payload_to_ml_block(v) for k, v in per_row_in.items() if isinstance(v, dict)}
            per_col_blk = {k: _icp_payload_to_ml_block(v) for k, v in per_col_in.items() if isinstance(v, dict)}
            narrative_pieces = []
            for k, v in list(per_row_in.items())[:2]:
                if isinstance(v, dict) and v.get("narrative"):
                    narrative_pieces.append(v["narrative"])
            for k, v in list(per_col_in.items())[:2]:
                if isinstance(v, dict) and v.get("narrative"):
                    narrative_pieces.append(v["narrative"])
            ml_block = {
                "min": None,
                "max": None,
                "median": None,
                "narrative": " | ".join(narrative_pieces[:4]) if narrative_pieces else "lotto_paper ready",
                "model_contributions": {},
                "per_row": per_row_blk,
                "per_col": per_col_blk,
                "indicator": "lotto_paper_14",
            }
        return self._attach_ml_block(result, ml_block)

    # ─────────────────────────────────────────
    # 18. 10단위 분포 (Decade Distribution) — Phase 1 decade_distribution (전체)
    # ─────────────────────────────────────────
    def _decade_distribution(self) -> dict:
        def calc(nums):
            d1 = sum(1 for n in nums if 1 <= n <= 10)
            d2 = sum(1 for n in nums if 11 <= n <= 20)
            d3 = sum(1 for n in nums if 21 <= n <= 30)
            d4 = sum(1 for n in nums if 31 <= n <= 40)
            d5 = sum(1 for n in nums if 41 <= n <= 45)
            return f"{d1}:{d2}:{d3}:{d4}:{d5}"

        all_patterns = [calc(nums) for nums in self.all_numbers]
        recent_patterns = [calc(nums) for nums in self.recent_numbers]

        all_counter = Counter(all_patterns)
        recent_counter = Counter(recent_patterns)

        patterns = []
        for pat in sorted(all_counter.keys(), key=lambda x: all_counter[x], reverse=True):
            patterns.append({
                "pattern": pat,
                "all_count": all_counter[pat],
                "all_pct": round(all_counter[pat] / self.total_rounds * 100, 1),
                "recent_count": recent_counter.get(pat, 0),
                "recent_pct": round(recent_counter.get(pat, 0) / max(self.recent_rounds, 1) * 100, 1),
            })

        top_patterns = patterns[:5]
        evidence = f"역대 상위 분포: "
        evidence += ", ".join(f"{p['pattern']}({p['all_pct']}%)" for p in top_patterns[:3])

        result = {
            "key": "decade_distribution",
            "name": "10단위 분포 (Decade)",
            "icon": "equalizer",
            "type": "pattern",
            "description": "1~10/11~20/21~30/31~40/41~45 대별 번호 분배.",
            "patterns": patterns[:10],
            "recommendation": {
                "recommended_patterns": [p["pattern"] for p in top_patterns[:3]],
                "evidence": evidence,
            },
        }

        # ML: decade_distribution payload 전체 5 카테고리
        ml_block = None
        payload = self._phase1_payload("decade_distribution")
        if isinstance(payload, dict) and "per_category" in payload:
            per_cat = payload["per_category"]
            sub_categories = {}
            narratives = []
            for label, cat_payload in (per_cat or {}).items():
                if not isinstance(cat_payload, dict):
                    continue
                sub_categories[label] = _icp_payload_to_ml_block(cat_payload)
                if cat_payload.get("narrative"):
                    narratives.append(cat_payload["narrative"])
            ml_block = {
                "min": None,
                "max": None,
                "median": None,
                "narrative": " | ".join(narratives[:5]) if narratives else "decade ready",
                "model_contributions": {},
                "per_category": sub_categories,
                "indicator": "decade_distribution",
            }
        return self._attach_ml_block(result, ml_block)

    # ─────────────────────────────────────────
    # 19. 미출현 그룹 (Missing Group) — Phase 1 missing_group (광역 4 카테고리)
    # ─────────────────────────────────────────
    def _missing_group(self) -> dict:
        """미출현그룹 광역 4 카테고리 분포 (predictor only — fallback은 dormancy 룰베이스)."""
        # 룰베이스 fallback: 직전 N회 미출현 회차 분포
        max_gap_per_num = {}
        for n in range(1, 46):
            gap = 0
            for d in self.draws:
                if n in d.get("numbers", []):
                    break
                gap += 1
            max_gap_per_num[n] = gap

        # 4 그룹 분류 (단순 규칙: 0회=핫, 1~5=따뜻, 6~15=식음, 16+=초장기)
        groups_count = {"hot": 0, "warm": 0, "cool": 0, "cold": 0}
        for n, gap in max_gap_per_num.items():
            if gap == 0:
                groups_count["hot"] += 1
            elif gap <= 5:
                groups_count["warm"] += 1
            elif gap <= 15:
                groups_count["cool"] += 1
            else:
                groups_count["cold"] += 1

        evidence = (
            f"룰베이스 4 그룹 분포: "
            f"hot={groups_count['hot']}, warm={groups_count['warm']}, "
            f"cool={groups_count['cool']}, cold={groups_count['cold']}"
        )

        result = {
            "key": "missing_group",
            "name": "미출현 그룹 (Missing Group)",
            "icon": "schedule",
            "type": "categorical",
            "description": "전체 45번호를 미출현 길이별로 4그룹(hot/warm/cool/cold)으로 분류한 분포.",
            "groups_count": groups_count,
            "recommendation": {
                "evidence": evidence,
            },
        }

        # ML: missing_group predictor (4 카테고리)
        ml_block = None
        payload = self._phase1_payload("missing_group")
        if isinstance(payload, dict) and "per_group" in payload:
            per_grp = payload["per_group"]
            sub_groups = {}
            narratives = []
            for label, grp_payload in (per_grp or {}).items():
                if not isinstance(grp_payload, dict):
                    continue
                sub_block = _icp_payload_to_ml_block(grp_payload, pool_size=grp_payload.get("dynamic_pool_size"))
                sub_block["members"] = grp_payload.get("members", [])
                sub_groups[label] = sub_block
                if grp_payload.get("narrative"):
                    narratives.append(grp_payload["narrative"])
            ml_block = {
                "min": None,
                "max": None,
                "median": None,
                "narrative": " | ".join(narratives[:4]) if narratives else "missing_group ready",
                "model_contributions": {},
                "per_group": sub_groups,
                "dynamic_pool_sizes": payload.get("dynamic_pool_sizes"),
                "indicator": "missing_group_4",
            }
        return self._attach_ml_block(result, ml_block)

    # ═════════════════════════════════════════
    # 공통 빌더
    # ═════════════════════════════════════════
    def _build_range_filter(
        self,
        key: str,
        name: str,
        icon: str,
        all_vals: list,
        recent_vals: list,
        description: str,
    ) -> dict:
        """범위형(range) 필터의 통계 + 추천 + 근거를 생성한다."""
        if not all_vals:
            return {
                "key": key, "name": name, "icon": icon,
                "type": "range", "description": description,
                "stats": {}, "recommendation": {}, "distribution": {},
            }

        # 전체 통계
        all_mean = sum(all_vals) / len(all_vals)
        all_sorted = sorted(all_vals)
        all_median = all_sorted[len(all_sorted) // 2]
        all_mode = Counter(all_vals).most_common(1)[0][0]
        all_std = math.sqrt(sum((v - all_mean) ** 2 for v in all_vals) / len(all_vals))
        all_min = min(all_vals)
        all_max = max(all_vals)

        # 최근 N회 통계
        rec_mean = sum(recent_vals) / len(recent_vals) if recent_vals else all_mean
        rec_sorted = sorted(recent_vals) if recent_vals else all_sorted
        rec_median = rec_sorted[len(rec_sorted) // 2] if rec_sorted else all_median
        rec_mode = Counter(recent_vals).most_common(1)[0][0] if recent_vals else all_mode
        rec_std = math.sqrt(sum((v - rec_mean) ** 2 for v in recent_vals) / len(recent_vals)) if recent_vals else all_std

        # 추천 범위: 최근 N회 mean +/- 1 std (정수로)
        rec_min = max(all_min, int(rec_mean - rec_std))
        rec_max = min(all_max, int(rec_mean + rec_std + 0.5))

        # 분포 (히스토그램 데이터)
        all_counter = Counter(all_vals)
        recent_counter = Counter(recent_vals) if recent_vals else Counter()

        # 값 범위 내 분포
        dist_keys = sorted(set(all_vals))
        distribution = []
        for v in dist_keys:
            distribution.append({
                "value": v,
                "all_count": all_counter[v],
                "all_pct": round(all_counter[v] / self.total_rounds * 100, 1),
                "recent_count": recent_counter.get(v, 0),
                "recent_pct": round(recent_counter.get(v, 0) / max(self.recent_rounds, 1) * 100, 1),
            })

        # 트렌드: 최근 10회의 값
        trend = all_vals[:10] if len(all_vals) >= 10 else all_vals

        # 근거 문자열 생성
        trend_direction = "상승" if len(trend) >= 2 and trend[0] > sum(trend) / len(trend) else "하락" if len(trend) >= 2 and trend[0] < sum(trend) / len(trend) else "보합"
        evidence = (
            f"역대 {self.total_rounds}회 평균 {all_mean:.1f} (표준편차 {all_std:.1f}). "
            f"최근 {self.recent_rounds}회 평균 {rec_mean:.1f} (표준편차 {rec_std:.1f}). "
            f"최빈값: 역대 {all_mode}, 최근 {rec_mode}. "
            f"최근 추세: {trend_direction}. "
            f"추천 범위: {rec_min}~{rec_max} (최근 평균 +/- 1표준편차)"
        )

        return {
            "key": key,
            "name": name,
            "icon": icon,
            "type": "range",
            "description": description,
            "stats": {
                "all": {
                    "mean": round(all_mean, 2),
                    "median": all_median,
                    "mode": all_mode,
                    "std": round(all_std, 2),
                    "min": all_min,
                    "max": all_max,
                    "count": self.total_rounds,
                },
                "recent": {
                    "mean": round(rec_mean, 2),
                    "median": rec_median,
                    "mode": rec_mode,
                    "std": round(rec_std, 2),
                    "min": min(recent_vals) if recent_vals else all_min,
                    "max": max(recent_vals) if recent_vals else all_max,
                    "count": self.recent_rounds,
                },
            },
            "distribution": distribution,
            "trend": trend,
            "recommendation": {
                "min": rec_min,
                "max": rec_max,
                "evidence": evidence,
            },
        }
