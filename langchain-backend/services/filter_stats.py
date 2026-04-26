"""필터별 통계 분석 엔진.

lotto_draws 데이터로부터 18+ 필터 유형의 통계를 계산하고
각 필터별 추천 범위/값 + 근거(evidence)를 생성한다.

사용:
    from services.filter_stats import FilterStatsComputer
    computer = FilterStatsComputer(draws)  # draws: round 내림차순
    result = computer.compute_all()

P2 추가: Poisson-Binomial PMF 기반 필터값 분포 계산
- count-type 22개 필터: PB PMF (O(n²) DP, 정확)
- range-type 2개 (sum, tail_sum): 전체 45개 사용 개선 MC
- complex 2개 (ac, consecutive): 기존 방식 유지
"""

import math
from collections import Counter
from typing import Any

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
COUNT_TYPE_FILTERS = {
    "odd", "high", "prime", "composite", "square", "triangular", "twin",
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
        history_draws: 역순(최신→과거) 정렬된 당첨 이력

    Returns:
        {
            "hot10_nums": set,
            "neutral10_nums": set,
            "cold10_nums": set,
            "missing_nums": set,   # 10회 이상 미출현
            "latest_nums": set,    # 직전 회차 당첨번호 (이월수)
            "neighbor_nums": set,  # latest_nums의 ±1 번호
        }
    """
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
        "hot10_nums":     hot10_nums,
        "neutral10_nums": neutral10_nums,
        "cold10_nums":    cold10_nums,
        "missing_nums":   missing_nums,
        "latest_nums":    latest_nums,
        "neighbor_nums":  neighbor_nums,
    }


def get_attr_set(filter_name: str, dynamic_sets: dict):
    """filter_name → 해당 속성 번호 집합 반환.

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
        "hot10":     dynamic_sets.get("hot10_nums", set()),
        "neutral10": dynamic_sets.get("neutral10_nums", set()),
        "cold10":    dynamic_sets.get("cold10_nums", set()),
        "missing":   dynamic_sets.get("missing_nums", set()),
        "neighbor":  dynamic_sets.get("neighbor_nums", set()),
        "carryover": dynamic_sets.get("latest_nums", set()),
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

    # ── 입력 정규화 (BUGFIX) ────────────────────────────────────────────
    # model_probs의 입력 스케일이 모델마다 다름:
    #   - LSTM/CNN/Transformer 등 sigmoid 출력: 각 n별 P(n in draw) ≈ 0.13, 합 ≈ 6
    #   - XGBoost/Markov softmax 출력: 합 ≈ 1.0 (확률분포)
    # 어느 쪽이든 합=1로 정규화한 뒤 ×draw_size 하면 P(n in draw)가 됨.
    # 이전 버그: 입력 스케일을 가정하지 않고 무조건 ×draw_size 하여
    # sigmoid 출력의 경우 attr_probs가 1.0에 saturate되어 PMF가 attr_set
    # 크기에 근접하는 가짜 결과 발생 (예: composite max=30, twin=4~4).
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


class FilterStatsComputer:
    """모든 필터 유형에 대한 통계를 계산한다."""

    def __init__(self, draws: list[dict], recent_n: int = 50):
        """
        Args:
            draws: lotto_draws 테이블 데이터 (round 내림차순)
            recent_n: '최근' 기준 회차 수
        """
        self.draws = draws
        self.recent_n = recent_n
        self.all_numbers = [d.get("numbers", []) for d in draws if d.get("numbers")]
        self.recent_numbers = self.all_numbers[:recent_n]
        self.total_rounds = len(self.all_numbers)
        self.recent_rounds = len(self.recent_numbers)

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
        ]
        return filters

    # ─────────────────────────────────────────
    # 1. 총합 (Total Sum)
    # ─────────────────────────────────────────
    def _total_sum(self) -> dict:
        all_vals = [sum(nums) for nums in self.all_numbers]
        recent_vals = [sum(nums) for nums in self.recent_numbers]
        return self._build_range_filter(
            key="total_sum",
            name="총합 (Total Sum)",
            icon="functions",
            all_vals=all_vals,
            recent_vals=recent_vals,
            description="6개 번호의 합계. 역대 평균 약 133, 표준편차 약 32.",
        )

    # ─────────────────────────────────────────
    # 2. 끝수합 (Tail Digit Sum)
    # ─────────────────────────────────────────
    def _tail_sum(self) -> dict:
        def calc(nums):
            return sum(n % 10 for n in nums)

        all_vals = [calc(nums) for nums in self.all_numbers]
        recent_vals = [calc(nums) for nums in self.recent_numbers]
        return self._build_range_filter(
            key="tail_sum",
            name="끝수합 (Tail Sum)",
            icon="pin",
            all_vals=all_vals,
            recent_vals=recent_vals,
            description="각 번호의 일의 자리 합계.",
        )

    # ─────────────────────────────────────────
    # 3. AC값 (Arithmetic Complexity)
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
        return self._build_range_filter(
            key="ac_value",
            name="AC값 (Arithmetic Complexity)",
            icon="calculate",
            all_vals=all_vals,
            recent_vals=recent_vals,
            description="번호 간 차이값의 다양성 지표. 높을수록 고루 분포.",
        )

    # ─────────────────────────────────────────
    # 4. 홀짝 비율 (Odd/Even)
    # ─────────────────────────────────────────
    def _odd_even(self) -> dict:
        def calc(nums):
            return sum(1 for n in nums if n % 2 == 1)

        all_vals = [calc(nums) for nums in self.all_numbers]
        recent_vals = [calc(nums) for nums in self.recent_numbers]

        # 패턴 분포 (예: "3:3", "4:2", ...)
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

        # 패턴별 분포 추가
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
        return base

    # ─────────────────────────────────────────
    # 5. 저고 비율 (Low/High)
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
        return base

    # ─────────────────────────────────────────
    # 6. 연속번호 (Consecutive Numbers)
    # ─────────────────────────────────────────
    def _consecutive(self) -> dict:
        def calc(nums):
            s = sorted(nums)
            return sum(1 for i in range(len(s) - 1) if s[i + 1] - s[i] == 1)

        all_vals = [calc(nums) for nums in self.all_numbers]
        recent_vals = [calc(nums) for nums in self.recent_numbers]
        return self._build_range_filter(
            key="consecutive",
            name="연속번호 (Consecutive)",
            icon="linear_scale",
            all_vals=all_vals,
            recent_vals=recent_vals,
            description="인접 연속번호 쌍의 개수.",
        )

    # ─────────────────────────────────────────
    # 7. 이월수 (Carryover)
    # ─────────────────────────────────────────
    def _carryover(self) -> dict:
        all_vals = []
        for i in range(len(self.all_numbers) - 1):
            curr = set(self.all_numbers[i])
            prev = set(self.all_numbers[i + 1])
            all_vals.append(len(curr & prev))
        recent_vals = all_vals[:self.recent_n]

        return self._build_range_filter(
            key="carryover",
            name="이월수 (Carryover)",
            icon="replay",
            all_vals=all_vals,
            recent_vals=recent_vals,
            description="직전 회차와 동일한 번호 개수.",
        )

    # ─────────────────────────────────────────
    # 8. 소수 개수 (Prime Count)
    # ─────────────────────────────────────────
    def _prime_count(self) -> dict:
        def calc(nums):
            return sum(1 for n in nums if n in config.PRIMES)

        all_vals = [calc(nums) for nums in self.all_numbers]
        recent_vals = [calc(nums) for nums in self.recent_numbers]
        return self._build_range_filter(
            key="prime_count",
            name="소수 개수 (Prime)",
            icon="looks_one",
            all_vals=all_vals,
            recent_vals=recent_vals,
            description="6개 중 소수(2,3,5,7,11,13,17,19,23,29,31,37,41,43)의 개수.",
        )

    # ─────────────────────────────────────────
    # 9. 합성수 개수 (Composite Count)
    # ─────────────────────────────────────────
    def _composite_count(self) -> dict:
        non_primes = set(range(1, 46)) - config.PRIMES - {1}

        def calc(nums):
            return sum(1 for n in nums if n in non_primes)

        all_vals = [calc(nums) for nums in self.all_numbers]
        recent_vals = [calc(nums) for nums in self.recent_numbers]
        return self._build_range_filter(
            key="composite_count",
            name="합성수 개수 (Composite)",
            icon="looks_two",
            all_vals=all_vals,
            recent_vals=recent_vals,
            description="6개 중 합성수(1과 소수를 제외한 자연수)의 개수.",
        )

    # ─────────────────────────────────────────
    # 10. 제곱수 개수 (Square Count)
    # ─────────────────────────────────────────
    def _square_count(self) -> dict:
        def calc(nums):
            return sum(1 for n in nums if n in config.SQUARES)

        all_vals = [calc(nums) for nums in self.all_numbers]
        recent_vals = [calc(nums) for nums in self.recent_numbers]
        return self._build_range_filter(
            key="square_count",
            name="제곱수 개수 (Square)",
            icon="crop_square",
            all_vals=all_vals,
            recent_vals=recent_vals,
            description="6개 중 제곱수(1,4,9,16,25,36)의 개수.",
        )

    # ─────────────────────────────────────────
    # 11. 삼각수 개수 (Triangular Count)
    # ─────────────────────────────────────────
    def _triangular_count(self) -> dict:
        def calc(nums):
            return sum(1 for n in nums if n in config.TRIANGULARS)

        all_vals = [calc(nums) for nums in self.all_numbers]
        recent_vals = [calc(nums) for nums in self.recent_numbers]
        return self._build_range_filter(
            key="triangular_count",
            name="삼각수 개수 (Triangular)",
            icon="change_history",
            all_vals=all_vals,
            recent_vals=recent_vals,
            description="6개 중 삼각수(1,3,6,10,15,21,28,36,45)의 개수.",
        )

    # ─────────────────────────────────────────
    # 12. 쌍수 (Twin Numbers)
    # ─────────────────────────────────────────
    def _twin_count(self) -> dict:
        def calc(nums):
            """같은 끝자리를 가진 번호 쌍 수."""
            tails = [n % 10 for n in nums]
            cnt = Counter(tails)
            return sum(v - 1 for v in cnt.values() if v > 1)

        all_vals = [calc(nums) for nums in self.all_numbers]
        recent_vals = [calc(nums) for nums in self.recent_numbers]
        return self._build_range_filter(
            key="twin_count",
            name="쌍수 (Twin Numbers)",
            icon="group",
            all_vals=all_vals,
            recent_vals=recent_vals,
            description="같은 끝자리를 가진 번호 쌍의 수.",
        )

    # ─────────────────────────────────────────
    # 13. 핫/콜드 (최근 출현빈도)
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
        return base

    # ─────────────────────────────────────────
    # 14. 번호 범위 (Number Range = max - min)
    # ─────────────────────────────────────────
    def _number_range(self) -> dict:
        def calc(nums):
            return max(nums) - min(nums)

        all_vals = [calc(nums) for nums in self.all_numbers]
        recent_vals = [calc(nums) for nums in self.recent_numbers]
        return self._build_range_filter(
            key="number_range",
            name="번호 범위 (Range)",
            icon="expand",
            all_vals=all_vals,
            recent_vals=recent_vals,
            description="최대번호 - 최소번호. 번호의 분산도 지표.",
        )

    # ─────────────────────────────────────────
    # 15. 이웃수 (Neighbor Count)
    # ─────────────────────────────────────────
    def _neighbor_count(self) -> dict:
        """직전회차 번호의 ±1 범위에 있는 번호 개수."""
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

        return self._build_range_filter(
            key="neighbor_count",
            name="이웃수 (Neighbor)",
            icon="share_location",
            all_vals=all_vals,
            recent_vals=recent_vals,
            description="직전 회차 번호의 ±1 범위에 해당하는 번호 개수.",
        )

    # ─────────────────────────────────────────
    # 16. 3의 배수 개수
    # ─────────────────────────────────────────
    def _multiple_3(self) -> dict:
        def calc(nums):
            return sum(1 for n in nums if n % 3 == 0)

        all_vals = [calc(nums) for nums in self.all_numbers]
        recent_vals = [calc(nums) for nums in self.recent_numbers]
        return self._build_range_filter(
            key="multiple_3",
            name="3의 배수 개수",
            icon="filter_3",
            all_vals=all_vals,
            recent_vals=recent_vals,
            description="6개 중 3의 배수(3,6,9,...,45)의 개수.",
        )

    # ─────────────────────────────────────────
    # 16b. 7의 배수 개수
    # ─────────────────────────────────────────
    def _multiple_7(self) -> dict:
        MUL7 = {7, 14, 21, 28, 35, 42}

        def calc(nums):
            return sum(1 for n in nums if n in MUL7)

        all_vals = [calc(nums) for nums in self.all_numbers]
        recent_vals = [calc(nums) for nums in self.recent_numbers]
        return self._build_range_filter(
            key="multiple_7",
            name="7의 배수 개수",
            icon="filter_7",
            all_vals=all_vals,
            recent_vals=recent_vals,
            description="6개 중 7의 배수(7,14,21,28,35,42)의 개수.",
        )

    # ─────────────────────────────────────────
    # 16c. 8의 배수 개수
    # ─────────────────────────────────────────
    def _multiple_8(self) -> dict:
        MUL8 = {8, 16, 24, 32, 40}

        def calc(nums):
            return sum(1 for n in nums if n in MUL8)

        all_vals = [calc(nums) for nums in self.all_numbers]
        recent_vals = [calc(nums) for nums in self.recent_numbers]
        return self._build_range_filter(
            key="multiple_8",
            name="8의 배수 개수",
            icon="filter_8",
            all_vals=all_vals,
            recent_vals=recent_vals,
            description="6개 중 8의 배수(8,16,24,32,40)의 개수.",
        )

    # ─────────────────────────────────────────
    # 17. 구간 패턴 (Zone 1~15/16~30/31~45)
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

        return {
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

    # ─────────────────────────────────────────
    # 18. 10단위 분포 (Decade Distribution)
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

        return {
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

        # 추천 범위: 최근 N회 mean ± 1 std (정수로)
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
            f"추천 범위: {rec_min}~{rec_max} (최근 평균 ± 1표준편차)"
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
