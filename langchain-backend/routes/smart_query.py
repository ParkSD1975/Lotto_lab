"""
smart_query.py
분석 타입별 Supabase 전체 데이터 기반 통계 계산 후 LangChain(Gemini)에 전달
- 전이행렬, Gap 분석, 조건부확률, 연속패턴 서버사이드 계산
- Gemini는 설명만 담당 (계산 X)
"""
from fastapi import APIRouter
from pydantic import BaseModel
from collections import Counter, defaultdict
from typing import Any

from db.supabase_client import fetch_all_draws
from chains.analysis_chain import run_analysis

router = APIRouter(prefix="/api", tags=["smart-query"])

TOPIC_MAP = {
    "ac_value": "AC값(Arithmetic Complexity) 통계",
    "total_sum": "총합 구간 전이 통계",
    "tail_sum": "끝수합 구간 전이 통계",
    "tail_digit": "끝수 패턴 통계",
    "hot_cold": "Hot/Cold 상태 전이 통계",
    "missing": "미출현 Gap 분포 및 복귀율 통계",
    "triangular_number": "삼각수 개수 전이 통계",
    "regression": "회귀 주기별 적중률 분포 통계",
    "properties_matrix": "번호 속성 조합 빈도 통계",
    "odd_even": "홀짝 비율 전이 통계",
    "low_high": "저고 비율 전이 통계",
    "carryover": "이월수 조건부확률 통계",
    "consecutive_number": "연번 개수 전이 통계",
    "prime_number": "소수 개수 전이 통계",
    "composite_number": "합성수 개수 전이 통계",
    "twin_number": "동형수 출현 통계",
    "square_number": "제곱수 개수 전이 통계",
    "neighbor_number": "이웃수 분포 통계",
    "number_range": "번호대별 분포 전이 통계",
    "magic_square": "9궁 출현 분포 통계",
    "lotto_paper": "번호별 출현 빈도 통계",
    "multiple": "배수 그룹 분포 통계",
    "stats_by_number": "번호별 출현 빈도 및 동반 통계",
}


class SmartQueryRequest(BaseModel):
    question: str
    analysis_type: str = "general"
    target_round: int = 0
    subject_round: int = 0


# ─── 공통 유틸 ────────────────────────────────────────────────────────

def compute_ac_value(numbers: list) -> int:
    """AC값 계산: 차이값 집합 크기 - 5"""
    nums = sorted(numbers)
    diffs = set()
    for i in range(len(nums)):
        for j in range(i + 1, len(nums)):
            diffs.add(nums[j] - nums[i])
    return len(diffs) - 5


def compute_transition_matrix(values: list, top_n: int = 5) -> dict:
    """전이 행렬 P(next=X | current=Y) - 상위 N개만 반환"""
    transitions = defaultdict(Counter)
    for i in range(len(values) - 1):
        transitions[values[i]][values[i + 1]] += 1
    result = {}
    for curr, nexts in transitions.items():
        total = sum(nexts.values())
        result[str(curr)] = {
            str(nxt): round(cnt / total, 3)
            for nxt, cnt in sorted(nexts.items(), key=lambda x: -x[1])[:top_n]
        }
    return result


def compute_streak_after(values: list, streak_len: int = 2) -> dict:
    """N연속 동일값 이후 다음 값 분포"""
    after = defaultdict(Counter)
    i = 0
    while i < len(values) - streak_len:
        curr = values[i]
        if all(values[i + k] == curr for k in range(streak_len)):
            next_idx = i + streak_len
            if next_idx < len(values):
                after[str(curr)][str(values[next_idx])] += 1
            i += streak_len
        else:
            i += 1
    result = {}
    for curr, nexts in after.items():
        total = sum(nexts.values())
        result[curr] = {nxt: round(cnt / total, 3) for nxt, cnt in sorted(nexts.items(), key=lambda x: -x[1])[:5]}
    return result


def compute_frequency_table(values: list) -> dict:
    """빈도 테이블: {값: {count, rate%}}"""
    counter = Counter(values)
    total = len(values)
    return {
        str(k): {"count": v, "rate_pct": round(v / total * 100, 1)}
        for k, v in sorted(counter.items())
    }


def get_current_gap(draws: list, extract_fn) -> dict:
    """각 대상의 현재 Gap (draws=최신순)"""
    seen = {}
    for i, draw in enumerate(draws):
        vals = extract_fn(draw)
        if not isinstance(vals, (list, set)):
            vals = [vals]
        for v in vals:
            if v not in seen:
                seen[v] = i
    return {str(k): v for k, v in seen.items()}


def format_context(stats: dict, question: str) -> str:
    """통계 dict → LangChain 컨텍스트 문자열"""
    import json
    return f"""# 백엔드 계산 통계 (Supabase 전체 {stats.get('total_rounds', '?')}회차 기반)

{json.dumps(stats, ensure_ascii=False, indent=2)}

# User Question: "{question}"
위 통계 데이터를 근거로 사용자 질문에 구체적인 수치를 인용하여 답변하세요.
"""


# ─── 분석타입별 통계 계산 ─────────────────────────────────────────────

def stats_ac_value(draws: list) -> dict:
    ac_vals = [compute_ac_value(d["numbers"]) for d in draws]
    freq = compute_frequency_table(ac_vals)
    matrix = compute_transition_matrix(ac_vals[:300])
    streak2 = compute_streak_after(ac_vals[:300], 2)
    streak3 = compute_streak_after(ac_vals[:300], 3)
    current = ac_vals[0] if ac_vals else None
    return {
        "analysis_type": "ac_value",
        "current_ac": current,
        "recent_5": ac_vals[:5],
        "frequency": freq,
        "transition_from_current": matrix.get(str(current), {}),
        "full_transition_matrix": matrix,
        "after_2_consecutive_same": streak2,
        "after_3_consecutive_same": streak3,
        "total_rounds": len(draws),
    }


def stats_total_sum(draws: list) -> dict:
    sums = [sum(d["numbers"]) for d in draws]

    def to_range(s):
        if s < 100: return "100미만"
        elif s < 130: return "100~129"
        elif s < 160: return "130~159"
        elif s < 190: return "160~189"
        else: return "190이상"

    ranges = [to_range(s) for s in sums]
    freq = compute_frequency_table(ranges)
    matrix = compute_transition_matrix(ranges[:300])
    streak2 = compute_streak_after(ranges[:300], 2)

    # 극단값 이후 분포
    extreme_after = [to_range(sums[i + 1]) for i, s in enumerate(sums[:-1]) if s < 100 or s > 190]
    extreme_freq = compute_frequency_table(extreme_after) if extreme_after else {}

    current_range = to_range(sums[0]) if sums else "N/A"
    avg = round(sum(sums) / len(sums), 1) if sums else 0

    return {
        "analysis_type": "total_sum",
        "current_sum": sums[0] if sums else 0,
        "current_range": current_range,
        "average_sum": avg,
        "recent_5_sums": sums[:5],
        "range_frequency": freq,
        "transition_from_current_range": matrix.get(current_range, {}),
        "full_transition_matrix": matrix,
        "after_2_consecutive_same_range": streak2,
        "after_extreme_value_dist": extreme_freq,
        "total_rounds": len(draws),
    }


def stats_tail_sum(draws: list) -> dict:
    def tail_sum_fn(nums): return sum(n % 10 for n in nums)

    ts_vals = [tail_sum_fn(d["numbers"]) for d in draws]

    def to_range(s):
        if s < 10: return "10미만"
        elif s < 20: return "10~19"
        elif s < 30: return "20~29"
        else: return "30이상"

    ranges = [to_range(s) for s in ts_vals]
    freq = compute_frequency_table(ranges)
    matrix = compute_transition_matrix(ranges[:300])
    streak2 = compute_streak_after(ranges[:300], 2)
    extreme_after = [to_range(ts_vals[i + 1]) for i, s in enumerate(ts_vals[:-1]) if s < 5 or s > 30]
    extreme_freq = compute_frequency_table(extreme_after) if extreme_after else {}

    current_range = to_range(ts_vals[0]) if ts_vals else "N/A"

    return {
        "analysis_type": "tail_sum",
        "current_tail_sum": ts_vals[0] if ts_vals else 0,
        "current_range": current_range,
        "average_tail_sum": round(sum(ts_vals) / len(ts_vals), 1) if ts_vals else 0,
        "recent_5": ts_vals[:5],
        "range_frequency": freq,
        "transition_from_current_range": matrix.get(current_range, {}),
        "full_transition_matrix": matrix,
        "after_2_consecutive_same_range": streak2,
        "after_extreme_value_dist": extreme_freq,
        "total_rounds": len(draws),
    }


def stats_hot_cold(draws: list) -> dict:
    """Hot/Cold 전이 분석 - 효율적 버전"""
    N = len(draws)
    SAMPLE = min(100, N - 1)

    def get_gaps_at(idx: int) -> dict:
        """idx 위치(최신=0) 기준 각 번호의 gap"""
        g = {n: min(30, N - idx) for n in range(1, 46)}
        for j in range(idx, min(idx + 31, N)):
            for n in draws[j]["numbers"]:
                if g[n] == min(30, N - idx):  # 아직 미발견
                    g[n] = j - idx
        return g

    def gap_to_status(gap: int) -> str:
        if gap <= 5: return "Hot"
        elif gap <= 20: return "Neutral"
        else: return "Cold"

    # 전이 행렬 계산
    transitions = defaultdict(Counter)
    for i in range(min(SAMPLE, 50)):
        g_curr = get_gaps_at(i)
        g_prev = get_gaps_at(i + 1)
        for n in range(1, 46):
            transitions[gap_to_status(g_prev[n])][gap_to_status(g_curr[n])] += 1

    trans_probs = {}
    for from_s, nexts in transitions.items():
        total = sum(nexts.values())
        trans_probs[from_s] = {to_s: round(cnt / total, 3) for to_s, cnt in sorted(nexts.items(), key=lambda x: -x[1])}

    # 현재 상태
    g_now = get_gaps_at(0)
    status_map = {n: gap_to_status(g) for n, g in g_now.items()}
    hot_nums = sorted([n for n, s in status_map.items() if s == "Hot"])
    cold_nums = sorted([n for n, s in status_map.items() if s == "Cold"])
    neutral_nums = sorted([n for n, s in status_map.items() if s == "Neutral"])

    # Hot 연속 기록 (번호별 streak)
    hot_streaks = {}
    for n in range(1, 46):
        streak = 0
        for draw in draws:
            if n in draw["numbers"]:
                streak += 1
            else:
                break
        hot_streaks[n] = streak

    return {
        "analysis_type": "hot_cold",
        "current_hot_numbers": hot_nums,
        "current_cold_numbers": cold_nums,
        "current_neutral_numbers": neutral_nums,
        "hot_count": len(hot_nums),
        "cold_count": len(cold_nums),
        "neutral_count": len(neutral_nums),
        "transition_matrix": trans_probs,
        "current_hot_streaks": {n: hot_streaks[n] for n in hot_nums if hot_streaks[n] > 1},
        "total_rounds_analyzed": SAMPLE,
    }


def stats_missing(draws: list) -> dict:
    """미출현 Gap 분석 - 효율적 버전"""
    N = len(draws)

    # 현재 Gap (최신순 탐색)
    current_gaps = {}
    for i, draw in enumerate(draws):
        for n in draw["numbers"]:
            if n not in current_gaps:
                current_gaps[n] = i
    for n in range(1, 46):
        if n not in current_gaps:
            current_gaps[n] = N

    # Gap 구간별 역대 출현율 계산 (최대 200회 샘플)
    gap_bucket_hits = defaultdict(lambda: [0, 0])  # [appeared, total]
    SAMPLE = min(200, N - 1)

    # 각 번호의 과거 gap 이력을 효율적으로 계산
    # last_seen[i][n] = i회차 기준 n번 마지막 출현까지의 gap
    for i in range(SAMPLE):
        appeared_this = set(draws[i]["numbers"])
        for n in range(1, 46):
            # i+1 이후에서 n의 마지막 출현 찾기 (최대 50회 전까지)
            g = None
            for j in range(i + 1, min(i + 51, N)):
                if n in draws[j]["numbers"]:
                    g = j - i - 1
                    break
            if g is None:
                g = min(50, N - i - 1)

            bucket = f"{(g // 5) * 5}~{(g // 5) * 5 + 4}회"
            gap_bucket_hits[bucket][1] += 1
            if n in appeared_this:
                gap_bucket_hits[bucket][0] += 1

    gap_appearance_rate = {}
    for bucket in sorted(gap_bucket_hits.keys()):
        v = gap_bucket_hits[bucket]
        gap_appearance_rate[bucket] = {
            "rate_pct": round(v[0] / v[1] * 100, 2) if v[1] > 0 else 0,
            "total_cases": v[1],
        }

    top10 = sorted(current_gaps.items(), key=lambda x: -x[1])[:10]
    avg_gap = round(sum(current_gaps.values()) / 45, 1)

    return {
        "analysis_type": "missing",
        "current_gaps_all_numbers": current_gaps,
        "top_10_longest_gap": [[n, g] for n, g in top10],
        "gap_appearance_rate": gap_appearance_rate,
        "average_gap": avg_gap,
        "total_rounds": N,
    }


def stats_triangular(draws: list) -> dict:
    TRIANGULAR = {1, 3, 6, 10, 15, 21, 28, 36, 45}
    counts = [len([n for n in d["numbers"] if n in TRIANGULAR]) for d in draws]
    freq = compute_frequency_table(counts)
    matrix = compute_transition_matrix(counts[:300])
    streak2 = compute_streak_after(counts[:300], 2)

    # 각 삼각수 번호별 Gap
    tri_gaps = {}
    for t in sorted(TRIANGULAR):
        for i, draw in enumerate(draws):
            if t in draw["numbers"]:
                tri_gaps[t] = i
                break
        if t not in tri_gaps:
            tri_gaps[t] = len(draws)

    current = counts[0] if counts else 0
    return {
        "analysis_type": "triangular_number",
        "current_count": current,
        "recent_5_counts": counts[:5],
        "frequency": freq,
        "transition_from_current_count": matrix.get(str(current), {}),
        "full_transition_matrix": matrix,
        "after_2_consecutive_same": streak2,
        "each_triangular_number_gap": tri_gaps,
        "total_rounds": len(draws),
    }


def stats_regression(draws: list) -> dict:
    """회귀 주기별 적중률 통계"""
    N = len(draws)
    period_stats = {}

    for period in [50, 100, 150, 200]:
        if N < period + 10:
            continue
        gaps = {}
        for i, draw in enumerate(draws[:period]):
            for n in draw["numbers"]:
                if n not in gaps:
                    gaps[n] = i
        gap_vals = list(gaps.values())
        freq_by_5 = Counter(g // 5 for g in gap_vals)
        period_stats[f"period_{period}"] = {
            "avg_gap": round(sum(gap_vals) / len(gap_vals), 1) if gap_vals else 0,
            "max_gap": max(gap_vals) if gap_vals else 0,
            "min_gap": min(gap_vals) if gap_vals else 0,
            "gap_freq_by_5": {f"{k*5}~{k*5+4}회": v for k, v in sorted(freq_by_5.items())},
        }

    return {
        "analysis_type": "regression",
        "period_gap_stats": period_stats,
        "total_rounds": N,
    }


def stats_properties_matrix(draws: list) -> dict:
    PRIMES = {2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43}
    TRIANGULAR = {1, 3, 6, 10, 15, 21, 28, 36, 45}
    SQUARES = {1, 4, 9, 16, 25, 36}

    odd_even = Counter()
    low_high = Counter()
    prime_comp = Counter()
    tri_count = Counter()
    sq_count = Counter()

    for d in draws:
        nums = d["numbers"]
        odd = sum(1 for n in nums if n % 2 == 1)
        odd_even[f"{odd}홀{6 - odd}짝"] += 1
        low = sum(1 for n in nums if n <= 22)
        low_high[f"저{low}고{6 - low}"] += 1
        p = sum(1 for n in nums if n in PRIMES)
        prime_comp[f"소수{p}합성{6 - p}"] += 1
        t = sum(1 for n in nums if n in TRIANGULAR)
        tri_count[f"삼각{t}"] += 1
        s = sum(1 for n in nums if n in SQUARES)
        sq_count[f"제곱{s}"] += 1

    total = len(draws)

    def to_pct(counter):
        return {k: {"count": v, "rate_pct": round(v / total * 100, 1)} for k, v in counter.most_common(8)}

    return {
        "analysis_type": "properties_matrix",
        "odd_even_frequency": to_pct(odd_even),
        "low_high_frequency": to_pct(low_high),
        "prime_composite_frequency": to_pct(prime_comp),
        "triangular_count_frequency": to_pct(tri_count),
        "square_count_frequency": to_pct(sq_count),
        "total_rounds": total,
    }


def stats_generic_count(draws: list, analysis_type: str, extract_count_fn, label: str) -> dict:
    """범용: 개수 기반 분석 (소수, 합성수, 연번, 제곱수 등)"""
    counts = [extract_count_fn(d["numbers"]) for d in draws]
    freq = compute_frequency_table(counts)
    matrix = compute_transition_matrix(counts[:300])
    streak2 = compute_streak_after(counts[:300], 2)
    current = counts[0] if counts else 0
    return {
        "analysis_type": analysis_type,
        "current_count": current,
        "recent_5_counts": counts[:5],
        "frequency": freq,
        "transition_from_current_count": matrix.get(str(current), {}),
        "full_transition_matrix": matrix,
        "after_2_consecutive_same": streak2,
        "label": label,
        "total_rounds": len(draws),
    }


def stats_odd_even(draws: list) -> dict:
    counts = [sum(1 for n in d["numbers"] if n % 2 == 1) for d in draws]
    ratios = [f"{c}:{6 - c}" for c in counts]
    freq = compute_frequency_table(ratios)
    matrix = compute_transition_matrix(ratios[:300])
    streak2 = compute_streak_after(ratios[:300], 2)
    current = ratios[0] if ratios else "N/A"
    return {
        "analysis_type": "odd_even",
        "current_ratio": current,
        "recent_5_ratios": ratios[:5],
        "frequency": freq,
        "transition_from_current": matrix.get(current, {}),
        "full_transition_matrix": matrix,
        "after_2_consecutive_same": streak2,
        "total_rounds": len(draws),
    }


def stats_low_high(draws: list) -> dict:
    counts = [sum(1 for n in d["numbers"] if n <= 22) for d in draws]
    ratios = [f"저{c}고{6 - c}" for c in counts]
    freq = compute_frequency_table(ratios)
    matrix = compute_transition_matrix(ratios[:300])
    streak2 = compute_streak_after(ratios[:300], 2)
    current = ratios[0] if ratios else "N/A"
    return {
        "analysis_type": "low_high",
        "current_ratio": current,
        "recent_5_ratios": ratios[:5],
        "frequency": freq,
        "transition_from_current": matrix.get(current, {}),
        "full_transition_matrix": matrix,
        "after_2_consecutive_same": streak2,
        "total_rounds": len(draws),
    }


def stats_carryover(draws: list) -> dict:
    """이월수: 전 회차 당첨번호 중 이번 회차에 다시 나온 번호"""
    carryover_counts = []
    for i in range(len(draws) - 1):
        prev = set(draws[i + 1]["numbers"])
        curr = set(draws[i]["numbers"])
        carryover_counts.append(len(prev & curr))

    freq = compute_frequency_table(carryover_counts)
    matrix = compute_transition_matrix(carryover_counts[:300])
    streak2 = compute_streak_after(carryover_counts[:300], 2)
    current = carryover_counts[0] if carryover_counts else 0

    return {
        "analysis_type": "carryover",
        "current_carryover_count": current,
        "recent_5_counts": carryover_counts[:5],
        "frequency": freq,
        "transition_from_current_count": matrix.get(str(current), {}),
        "full_transition_matrix": matrix,
        "after_2_consecutive_same": streak2,
        "total_rounds": len(draws),
    }


def stats_number_range(draws: list) -> dict:
    """번호대(1-10, 11-20, 21-30, 31-40, 41-45)별 개수 분포"""
    def count_ranges(nums):
        r1 = sum(1 for n in nums if 1 <= n <= 10)
        r2 = sum(1 for n in nums if 11 <= n <= 20)
        r3 = sum(1 for n in nums if 21 <= n <= 30)
        r4 = sum(1 for n in nums if 31 <= n <= 40)
        r5 = sum(1 for n in nums if 41 <= n <= 45)
        return f"{r1}-{r2}-{r3}-{r4}-{r5}"

    patterns = [count_ranges(d["numbers"]) for d in draws]
    freq = compute_frequency_table(patterns)
    current = patterns[0] if patterns else "N/A"

    # 구간별 0개(전멸) 빈도
    zero_freq = {}
    for label, low, high in [("1~10", 1, 10), ("11~20", 11, 20), ("21~30", 21, 30), ("31~40", 31, 40), ("41~45", 41, 45)]:
        zero_cnt = sum(1 for d in draws if not any(low <= n <= high for n in d["numbers"]))
        zero_freq[label] = {"zero_count": zero_cnt, "rate_pct": round(zero_cnt / len(draws) * 100, 1)}

    return {
        "analysis_type": "number_range",
        "current_pattern": current,
        "recent_5_patterns": patterns[:5],
        "frequency": dict(list(freq.items())[:10]),
        "zero_range_frequency": zero_freq,
        "total_rounds": len(draws),
    }


def stats_lotto_paper(draws: list) -> dict:
    """번호별 출현 빈도 및 Gap"""
    all_nums = [n for d in draws for n in d["numbers"]]
    freq = Counter(all_nums)
    total_draws = len(draws)

    # 각 번호 Gap
    gaps = {}
    for n in range(1, 46):
        for i, draw in enumerate(draws):
            if n in draw["numbers"]:
                gaps[n] = i
                break
        if n not in gaps:
            gaps[n] = total_draws

    return {
        "analysis_type": "lotto_paper",
        "number_frequency": {
            n: {"count": freq.get(n, 0), "rate_pct": round(freq.get(n, 0) / total_draws * 100, 1)}
            for n in range(1, 46)
        },
        "number_gaps": gaps,
        "top_10_frequent": [[n, freq[n]] for n, _ in Counter(freq).most_common(10)],
        "bottom_10_frequent": [[n, freq.get(n, 0)] for n in sorted(freq, key=lambda x: freq[x])[:10]],
        "total_rounds": total_draws,
    }


# ─── 분석타입 → 계산 함수 매핑 ────────────────────────────────────────

STATS_MAP = {
    "ac_value": stats_ac_value,
    "total_sum": stats_total_sum,
    "tail_sum": stats_tail_sum,
    "hot_cold": stats_hot_cold,
    "missing": stats_missing,
    "triangular_number": stats_triangular,
    "regression": stats_regression,
    "properties_matrix": stats_properties_matrix,
    "odd_even": stats_odd_even,
    "low_high": stats_low_high,
    "carryover": stats_carryover,
    "number_range": stats_number_range,
    "lotto_paper": stats_lotto_paper,
}

# 공통 패턴 분석타입 (extract_count_fn 기반)
_PRIME_SET = {2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43}
_COMPOSITE_SET = set(range(1, 46)) - _PRIME_SET - {1}
_SQUARE_SET = {1, 4, 9, 16, 25, 36}
_TRIANGULAR_SET = {1, 3, 6, 10, 15, 21, 28, 36, 45}
_TWIN_SET = {11, 22, 33, 44}


def _consec_count(nums):
    s = sorted(nums)
    return sum(1 for i in range(len(s) - 1) if s[i + 1] - s[i] == 1)


GENERIC_MAP = {
    "prime_number": (lambda nums: sum(1 for n in nums if n in _PRIME_SET), "소수"),
    "composite_number": (lambda nums: sum(1 for n in nums if n in _COMPOSITE_SET), "합성수"),
    "square_number": (lambda nums: sum(1 for n in nums if n in _SQUARE_SET), "제곱수"),
    "twin_number": (lambda nums: sum(1 for n in nums if n in _TWIN_SET), "동형수"),
    "consecutive_number": (_consec_count, "연속번호"),
}


# ─── 엔드포인트 ───────────────────────────────────────────────────────

@router.post("/smart-query")
async def smart_query(req: SmartQueryRequest):
    try:
        draws = fetch_all_draws()
        if not draws:
            return {"trend": "데이터 없음", "pattern": "Supabase 연결 실패", "recommendation": ""}

        # 통계 계산
        if req.analysis_type in STATS_MAP:
            stats = STATS_MAP[req.analysis_type](draws)
        elif req.analysis_type in GENERIC_MAP:
            fn, label = GENERIC_MAP[req.analysis_type]
            stats = stats_generic_count(draws, req.analysis_type, fn, label)
        else:
            # 미지원 타입 → 기본 총합 통계
            sums = [sum(d["numbers"]) for d in draws[:100]]
            stats = {
                "analysis_type": req.analysis_type,
                "recent_sums": sums[:10],
                "avg_sum": round(sum(sums) / len(sums), 1) if sums else 0,
                "total_rounds": len(draws),
            }

        topic = TOPIC_MAP.get(req.analysis_type, req.analysis_type)
        context = format_context(stats, req.question)

        result = await run_analysis(
            context=context,
            analysis_type=req.analysis_type,
            target_round=req.target_round,
            subject_round=req.subject_round,
            topic=topic,
        )
        return result

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "trend": f"Smart Query 오류: {str(e)}",
            "pattern": "서버 로그를 확인하세요.",
            "recommendation": "",
        }
