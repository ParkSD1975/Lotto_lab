"""
smart_query.py - 분석타입별 Supabase 통계 계산 + LLM Q&A 엔드포인트
POST /api/smart-query

기존 /api/analyze는 JS가 미리 계산한 텍스트를 받아서 LLM에 전달하는 방식.
이 엔드포인트는 Python에서 Supabase 데이터로 직접 통계를 계산한 후 LLM에 전달.
→ 전이행렬, 조건부확률, streak/gap 패턴 등 심층 통계 제공 가능.
"""

import json
import re
from collections import defaultdict, Counter
from fastapi import APIRouter
from pydantic import BaseModel
from langchain.prompts import PromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.schema.output_parser import StrOutputParser

import config
from db.supabase_client import fetch_all_draws

router = APIRouter(prefix="/api", tags=["smart-query"])


class SmartQueryRequest(BaseModel):
    question: str
    analysis_type: str = "general"
    target_round: int = 0
    subject_round: int = 0


ANALYSIS_TYPE_TO_TOPIC = {
    "ac_value": "AC값(Arithmetic Complexity)",
    "total_sum": "총합 분석",
    "odd_even": "홀짝 비율",
    "carryover": "이월수 패턴",
    "hot_cold": "핫/콜드 번호",
    "missing": "미출현(Gap) 분석",
    "tail_digit": "끝수 분석",
    "tail_sum": "끝수합 분석",
    "low_high": "고저 비율",
    "multiple": "배수 그룹",
    "consecutive_number": "연번 패턴",
    "prime_number": "소수 분석",
    "composite_number": "합성수 분석",
    "square_number": "제곱수 분석",
    "triangular_number": "삼각수 분석",
    "twin_number": "동형수 분석",
    "neighbor_number": "이웃수 분석",
    "number_range": "번호 구간대 분포",
    "magic_square": "9궁 패턴",
    "lotto_paper": "로또용지 패턴",
    "stats_by_number": "번호별 통계",
    "regression": "회귀 분석",
    "properties_matrix": "속성 매트릭스",
    "custom": "사용자 지정 분석",
}

# ============================================================
# 공통 유틸리티
# ============================================================

def build_transition_matrix(series: list) -> dict:
    """전이행렬 계산: {from_val: {to_val: 확률%}} - 내림차순 정렬"""
    counts: dict = defaultdict(lambda: defaultdict(int))
    for i in range(len(series) - 1):
        counts[series[i]][series[i + 1]] += 1
    matrix = {}
    for from_val, to_counts in counts.items():
        total = sum(to_counts.values())
        matrix[from_val] = {
            to_val: round(cnt / total * 100, 1)
            for to_val, cnt in sorted(to_counts.items(), key=lambda x: x[1], reverse=True)
        }
    return matrix


def detect_streak(series: list, target_val) -> int:
    """시리즈 끝에서 target_val의 연속 등장 횟수"""
    streak = 0
    for v in reversed(series):
        if v == target_val:
            streak += 1
        else:
            break
    return streak


def compute_after_streak(series: list, target_val, streak_len: int) -> dict:
    """N연속 후 다음값 분포: {next_val: 'X.X% (N/M회)'}"""
    next_vals = []
    for i in range(len(series) - streak_len):
        if all(series[i + k] == target_val for k in range(streak_len)):
            if i + streak_len < len(series):
                next_vals.append(series[i + streak_len])
    total = len(next_vals)
    if total == 0:
        return {}
    counter = Counter(next_vals)
    return {
        val: f"{round(cnt / total * 100, 1)}% ({cnt}/{total}회)"
        for val, cnt in sorted(counter.items(), key=lambda x: x[1], reverse=True)[:6]
    }


def format_transition(matrix: dict, current_val) -> str:
    """전이행렬 포맷팅"""
    tm = matrix.get(current_val, {})
    if not tm:
        return f"  ({current_val} 이후 데이터 부족)"
    return "\n".join(f"  → {k}: {v}%" for k, v in list(tm.items())[:6])


# ============================================================
# AC값 통계
# ============================================================

def compute_ac_value(numbers: list) -> int:
    """AC값 계산: 고유 절댓값 차이의 수"""
    sorted_nums = sorted(numbers)
    diffs = set()
    for i in range(len(sorted_nums)):
        for j in range(i + 1, len(sorted_nums)):
            diffs.add(sorted_nums[j] - sorted_nums[i])
    return len(diffs)


def compute_ac_stats(draws: list, question: str) -> str:
    sorted_draws = sorted(draws, key=lambda d: d["round"])
    ac_series = [compute_ac_value(d["numbers"]) for d in sorted_draws]
    if not ac_series:
        return "데이터 없음"

    current = ac_series[-1]
    streak = detect_streak(ac_series, current)
    recent5 = ac_series[-5:]
    transition = build_transition_matrix(ac_series)
    after_streak = compute_after_streak(ac_series, current, streak)
    counter = Counter(ac_series)
    total = len(ac_series)

    lines = [
        f"### AC값 분석 통계 (총 {total}회차)",
        f"최근 5회 AC값: {recent5}",
        f"현재 AC값: AC{current} (최근 {streak}회 연속)",
        "",
        f"#### 현재 AC{current} 이후 전이 확률:",
        format_transition(transition, current),
    ]
    if after_streak:
        lines.append(f"\n#### AC{current}가 {streak}회 연속일 때 다음 분포:")
        for val, info in after_streak.items():
            lines.append(f"  AC{val}: {info}")

    lines.append("\n#### 전체 AC값 빈도:")
    for k in range(0, 15):
        if k in counter:
            lines.append(f"  AC{k}: {counter[k]}회 ({round(counter[k] / total * 100, 1)}%)")

    # 질문에서 특정 AC값 언급 시 추가 전이 정보
    nums_in_q = list(map(int, re.findall(r"\d+", question)))
    for n in nums_in_q:
        if 0 <= n <= 14 and n != current and n in transition:
            lines.append(f"\n#### 질문 관련 - AC{n} 이후 전이 확률:")
            lines.append(format_transition(transition, n))

    return "\n".join(lines)


# ============================================================
# 총합 통계
# ============================================================

def get_sum_range(s: int) -> str:
    if s <= 80:
        return "60~80"
    if s <= 100:
        return "81~100"
    if s <= 120:
        return "101~120"
    if s <= 140:
        return "121~140"
    return "141~175"


def compute_sum_stats(draws: list, question: str) -> str:
    sorted_draws = sorted(draws, key=lambda d: d["round"])
    sum_series = [sum(d["numbers"]) for d in sorted_draws]
    range_series = [get_sum_range(s) for s in sum_series]

    current_sum = sum_series[-1]
    current_range = range_series[-1]
    streak = detect_streak(range_series, current_range)
    transition = build_transition_matrix(range_series)
    after_streak = compute_after_streak(range_series, current_range, streak)
    counter = Counter(range_series)
    total = len(range_series)
    avg = sum(sum_series) / total
    recent5_avg = sum(sum_series[-5:]) / 5

    lines = [
        f"### 총합 분석 통계 (총 {total}회차)",
        f"최근 5회 총합: {sum_series[-5:]}",
        f"현재 총합: {current_sum} (구간: {current_range}, 최근 {streak}회 연속 해당 구간)",
        f"전체 평균: {avg:.1f}, 최근 5회 평균: {recent5_avg:.1f}",
        "",
        f"#### 현재 구간 '{current_range}' 이후 전이 확률:",
        format_transition(transition, current_range),
    ]
    if after_streak:
        lines.append(f"\n#### '{current_range}' 구간 {streak}회 연속 후 다음 분포:")
        for val, info in after_streak.items():
            lines.append(f"  {val}: {info}")
    lines.append("\n#### 구간별 빈도:")
    for rng in ["60~80", "81~100", "101~120", "121~140", "141~175"]:
        cnt = counter.get(rng, 0)
        lines.append(f"  {rng}: {cnt}회 ({round(cnt / total * 100, 1)}%)")

    return "\n".join(lines)


# ============================================================
# 홀짝 비율 통계
# ============================================================

def get_odd_even_ratio(numbers: list) -> str:
    odd = sum(1 for n in numbers if n % 2 == 1)
    return f"{odd}:{6 - odd}"


def compute_odd_even_stats(draws: list, question: str) -> str:
    sorted_draws = sorted(draws, key=lambda d: d["round"])
    ratio_series = [get_odd_even_ratio(d["numbers"]) for d in sorted_draws]

    current = ratio_series[-1]
    streak = detect_streak(ratio_series, current)
    transition = build_transition_matrix(ratio_series)
    after_streak = compute_after_streak(ratio_series, current, streak)
    counter = Counter(ratio_series)
    total = len(ratio_series)

    lines = [
        f"### 홀짝 비율 분석 통계 (총 {total}회차)",
        f"최근 5회 홀짝: {ratio_series[-5:]}",
        f"현재 비율: 홀:짝 = {current} (최근 {streak}회 연속)",
        "",
        f"#### 현재 비율 '{current}' 이후 전이 확률:",
        format_transition(transition, current),
    ]
    if after_streak:
        lines.append(f"\n#### '{current}' {streak}회 연속 후 다음 분포:")
        for val, info in after_streak.items():
            lines.append(f"  {val}: {info}")
    lines.append("\n#### 비율별 빈도:")
    for r in ["6:0", "5:1", "4:2", "3:3", "2:4", "1:5", "0:6"]:
        cnt = counter.get(r, 0)
        lines.append(f"  홀:짝 {r}: {cnt}회 ({round(cnt / total * 100, 1)}%)")

    return "\n".join(lines)


# ============================================================
# 이월수 통계
# ============================================================

def compute_carryover_stats(draws: list, question: str) -> str:
    sorted_draws = sorted(draws, key=lambda d: d["round"])
    carryover_series = []
    for i in range(1, len(sorted_draws)):
        prev = set(sorted_draws[i - 1]["numbers"])
        curr = set(sorted_draws[i]["numbers"])
        carryover_series.append(len(prev & curr))
    if not carryover_series:
        return "데이터 부족"

    current = carryover_series[-1]
    streak = detect_streak(carryover_series, current)
    transition = build_transition_matrix(carryover_series)
    after_streak = compute_after_streak(carryover_series, current, streak)
    counter = Counter(carryover_series)
    total = len(carryover_series)

    lines = [
        f"### 이월수 분석 통계 (총 {total}회차)",
        f"최근 5회 이월수: {carryover_series[-5:]}",
        f"현재 이월수: {current}개 (최근 {streak}회 연속)",
        "",
        f"#### 이월수 {current}개 이후 전이 확률:",
        format_transition(transition, current),
    ]
    if after_streak:
        lines.append(f"\n#### 이월수 {current}개 {streak}회 연속 후 다음 분포:")
        for val, info in after_streak.items():
            lines.append(f"  {val}개: {info}")
    lines.append("\n#### 이월수별 빈도:")
    for k in range(0, 7):
        cnt = counter.get(k, 0)
        if cnt > 0:
            lines.append(f"  이월수 {k}개: {cnt}회 ({round(cnt / total * 100, 1)}%)")

    return "\n".join(lines)


# ============================================================
# 핫/콜드 통계
# ============================================================

def compute_hot_cold_stats(draws: list, question: str) -> str:
    sorted_draws = sorted(draws, key=lambda d: d["round"])
    total = len(sorted_draws)
    recent10 = sorted_draws[-10:]

    num_freq_10: dict = defaultdict(int)
    for d in recent10:
        for n in d["numbers"]:
            num_freq_10[n] += 1

    hot_nums = [(n, f) for n, f in num_freq_10.items() if f >= 3]
    cold_nums = [(n, 0) for n in range(1, 46) if num_freq_10.get(n, 0) == 0]
    hot_nums.sort(key=lambda x: x[1], reverse=True)

    num_freq_all: Counter = Counter()
    for d in sorted_draws:
        for n in d["numbers"]:
            num_freq_all[n] += 1

    latest_round = sorted_draws[-1]["round"]
    gaps = {}
    for n in range(1, 46):
        for d in reversed(sorted_draws):
            if n in d["numbers"]:
                gaps[n] = latest_round - d["round"]
                break
        else:
            gaps[n] = latest_round

    sorted_gaps = sorted(gaps.items(), key=lambda x: x[1], reverse=True)[:10]

    lines = [
        f"### 핫/콜드 분석 통계 (총 {total}회차, 최근 10회 기준)",
        "",
        f"#### 핫 번호 (최근 10회 중 3회 이상 출현):",
        (", ".join(f"{n}번({f}회)" for n, f in hot_nums[:10]) or "없음"),
        "",
        f"#### 콜드 번호 (최근 10회 미출현, 현재 Gap):",
        (", ".join(f"{n}번(갭:{gaps[n]})" for n, _ in cold_nums[:15]) or "없음"),
        "",
        f"#### 역대 상위 출현 번호 TOP 10:",
        ", ".join(f"{n}번({cnt}회)" for n, cnt in num_freq_all.most_common(10)),
        "",
        f"#### 역대 하위 출현 번호 (희소):",
        ", ".join(f"{n}번({cnt}회)" for n, cnt in num_freq_all.most_common()[-10:]),
        "",
        f"#### 콜드 번호 Gap 상위 10:",
    ]
    for n, g in sorted_gaps:
        lines.append(f"  {n}번: {g}회차 미출현")

    return "\n".join(lines)


# ============================================================
# 미출현(Gap) 통계
# ============================================================

def compute_missing_stats(draws: list, question: str) -> str:
    sorted_draws = sorted(draws, key=lambda d: d["round"])
    total = len(sorted_draws)
    latest_round = sorted_draws[-1]["round"]

    gaps = {}
    last_appear = {}
    for n in range(1, 46):
        for d in reversed(sorted_draws):
            if n in d["numbers"]:
                gaps[n] = latest_round - d["round"]
                last_appear[n] = d["round"]
                break
        else:
            gaps[n] = latest_round
            last_appear[n] = None

    # Gap별 출현 확률 (역대)
    gap_outcomes: dict = defaultdict(list)
    for i in range(1, len(sorted_draws)):
        curr = sorted_draws[i]
        for n in range(1, 46):
            g = 0
            for j in range(i - 1, max(i - 35, -1), -1):
                if n in sorted_draws[j]["numbers"]:
                    g = sorted_draws[i - 1]["round"] - sorted_draws[j]["round"]
                    break
                g += 1
            appeared = 1 if n in curr["numbers"] else 0
            gap_outcomes[min(g, 30)].append(appeared)

    gap_prob = {
        g: round(sum(outcomes) / len(outcomes) * 100, 1)
        for g, outcomes in gap_outcomes.items()
        if outcomes
    }

    long_missing = sorted(
        [(n, g) for n, g in gaps.items() if g >= 10],
        key=lambda x: x[1],
        reverse=True,
    )

    lines = [
        f"### 미출현(Gap) 분석 통계 (총 {total}회차)",
        f"최신 회차: {latest_round}회",
        "",
        f"#### 현재 장기 미출현 번호 (Gap ≥ 10):",
    ]
    if long_missing:
        for n, g in long_missing[:10]:
            lines.append(
                f"  {n}번: {g}회차 미출현 (마지막 출현: {last_appear.get(n, '없음')}회)"
            )
    else:
        lines.append("  (Gap ≥ 10인 번호 없음)")

    lines.append("\n#### Gap별 역대 출현 확률:")
    for g in range(0, 25):
        if g in gap_prob:
            lines.append(f"  Gap {g:2d}: {gap_prob[g]}% ({len(gap_outcomes[g])}건)")

    return "\n".join(lines)


# ============================================================
# 끝수(Tail Digit) 통계
# ============================================================

def compute_tail_digit_stats(draws: list, question: str) -> str:
    sorted_draws = sorted(draws, key=lambda d: d["round"])
    total = len(sorted_draws)

    tail_counter: Counter = Counter()
    for d in sorted_draws:
        for n in d["numbers"]:
            tail_counter[n % 10] += 1

    recent5 = [sorted([n % 10 for n in d["numbers"]]) for d in sorted_draws[-5:]]
    tail_dominant = [
        Counter(n % 10 for n in d["numbers"]).most_common(1)[0][0]
        for d in sorted_draws
    ]
    transition = build_transition_matrix(tail_dominant)
    current_dom = tail_dominant[-1]
    total_tails = sum(tail_counter.values())

    lines = [
        f"### 끝수 분석 통계 (총 {total}회차)",
        f"최근 5회 끝수 세트: {recent5}",
        f"현재 최빈 끝수: {current_dom}",
        "",
        f"#### 끝수별 역대 출현 빈도:",
    ]
    for t in range(10):
        cnt = tail_counter.get(t, 0)
        lines.append(f"  끝수 {t}: {cnt}회 ({round(cnt / total_tails * 100, 1)}%)")
    lines.append(f"\n#### 최빈 끝수 {current_dom} 이후 전이 확률:")
    lines.append(format_transition(transition, current_dom))

    return "\n".join(lines)


# ============================================================
# 끝수합 통계
# ============================================================

def get_tailsum_range(s: int) -> str:
    if s <= 15:
        return "0~15"
    if s <= 25:
        return "16~25"
    if s <= 35:
        return "26~35"
    if s <= 45:
        return "36~45"
    return "46+"


def compute_tailsum_stats(draws: list, question: str) -> str:
    sorted_draws = sorted(draws, key=lambda d: d["round"])
    total = len(sorted_draws)
    tailsums = [sum(n % 10 for n in d["numbers"]) for d in sorted_draws]
    range_series = [get_tailsum_range(s) for s in tailsums]

    current = tailsums[-1]
    current_range = range_series[-1]
    streak = detect_streak(range_series, current_range)
    transition = build_transition_matrix(range_series)
    after_streak = compute_after_streak(range_series, current_range, streak)
    counter = Counter(range_series)
    avg = sum(tailsums) / total
    recent5_avg = sum(tailsums[-5:]) / 5

    lines = [
        f"### 끝수합 분석 통계 (총 {total}회차)",
        f"최근 5회 끝수합: {tailsums[-5:]}",
        f"현재 끝수합: {current} (구간: {current_range}, {streak}회 연속)",
        f"전체 평균: {avg:.1f}, 최근 5회 평균: {recent5_avg:.1f}",
        "",
        f"#### 현재 구간 '{current_range}' 이후 전이 확률:",
        format_transition(transition, current_range),
    ]
    if after_streak:
        lines.append(f"\n#### '{current_range}' 구간 {streak}회 연속 후 다음 분포:")
        for val, info in after_streak.items():
            lines.append(f"  {val}: {info}")
    lines.append("\n#### 구간별 빈도:")
    for rng in ["0~15", "16~25", "26~35", "36~45", "46+"]:
        cnt = counter.get(rng, 0)
        lines.append(f"  {rng}: {cnt}회 ({round(cnt / total * 100, 1)}%)")

    return "\n".join(lines)


# ============================================================
# 고저 비율 통계
# ============================================================

def get_low_high_ratio(numbers: list) -> str:
    low = sum(1 for n in numbers if n <= 22)
    return f"{low}:{6 - low}"


def compute_low_high_stats(draws: list, question: str) -> str:
    sorted_draws = sorted(draws, key=lambda d: d["round"])
    ratio_series = [get_low_high_ratio(d["numbers"]) for d in sorted_draws]

    current = ratio_series[-1]
    streak = detect_streak(ratio_series, current)
    transition = build_transition_matrix(ratio_series)
    after_streak = compute_after_streak(ratio_series, current, streak)
    counter = Counter(ratio_series)
    total = len(ratio_series)

    lines = [
        f"### 고저 비율 분석 통계 (총 {total}회차, 기준: 1-22=저, 23-45=고)",
        f"최근 5회 고저: {ratio_series[-5:]}",
        f"현재 비율: 저:고 = {current} (최근 {streak}회 연속)",
        "",
        f"#### 현재 비율 '{current}' 이후 전이 확률:",
        format_transition(transition, current),
    ]
    if after_streak:
        lines.append(f"\n#### '{current}' {streak}회 연속 후 다음 분포:")
        for val, info in after_streak.items():
            lines.append(f"  {val}: {info}")
    lines.append("\n#### 비율별 빈도:")
    for r in ["6:0", "5:1", "4:2", "3:3", "2:4", "1:5", "0:6"]:
        cnt = counter.get(r, 0)
        lines.append(f"  저:고 {r}: {cnt}회 ({round(cnt / total * 100, 1)}%)")

    return "\n".join(lines)


# ============================================================
# 특수 번호 그룹 (소수, 합성수, 제곱수, 삼각수, 동형수)
# ============================================================

_PRIMES = {2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43}
_COMPOSITES = {n for n in range(4, 46) if n not in _PRIMES}
_SQUARES = {1, 4, 9, 16, 25, 36}
_TRIANGULARS = {1, 3, 6, 10, 15, 21, 28, 36, 45}
_TWINS = {11, 22, 33, 44}

_SPECIAL_MAP = {
    "prime_number": (_PRIMES, "소수"),
    "composite_number": (_COMPOSITES, "합성수"),
    "square_number": (_SQUARES, "제곱수"),
    "triangular_number": (_TRIANGULARS, "삼각수"),
    "twin_number": (_TWINS, "동형수"),
}


def compute_special_number_stats(draws: list, question: str, analysis_type: str) -> str:
    spec_set, spec_name = _SPECIAL_MAP.get(analysis_type, (_PRIMES, "소수"))
    sorted_draws = sorted(draws, key=lambda d: d["round"])
    total = len(sorted_draws)

    count_series = [len(set(d["numbers"]) & spec_set) for d in sorted_draws]
    current = count_series[-1]
    streak = detect_streak(count_series, current)
    transition = build_transition_matrix(count_series)
    after_streak = compute_after_streak(count_series, current, streak)
    counter = Counter(count_series)

    latest_round = sorted_draws[-1]["round"]
    spec_gaps = {}
    for n in sorted(spec_set):
        for d in reversed(sorted_draws):
            if n in d["numbers"]:
                spec_gaps[n] = latest_round - d["round"]
                break
        else:
            spec_gaps[n] = latest_round

    lines = [
        f"### {spec_name} 분석 통계 (총 {total}회차)",
        f"대상 번호: {sorted(spec_set)}",
        f"최근 5회 {spec_name} 개수: {count_series[-5:]}",
        f"현재 {spec_name} 수: {current}개 (최근 {streak}회 연속)",
        "",
        f"#### 현재 {current}개 이후 전이 확률:",
        format_transition(transition, current),
    ]
    if after_streak:
        lines.append(f"\n#### {current}개 {streak}회 연속 후 다음 분포:")
        for val, info in after_streak.items():
            lines.append(f"  {val}개: {info}")
    lines.append(f"\n#### 개수별 빈도:")
    for k in range(0, len(spec_set) + 1):
        cnt = counter.get(k, 0)
        if cnt > 0:
            lines.append(f"  {k}개: {cnt}회 ({round(cnt / total * 100, 1)}%)")
    lines.append(f"\n#### 개별 {spec_name} 번호 현재 Gap:")
    for n, g in spec_gaps.items():
        lines.append(f"  {n}번: {g}회차 미출현")

    return "\n".join(lines)


# ============================================================
# 연번 통계
# ============================================================

def count_consecutive_pairs(numbers: list) -> int:
    s = sorted(numbers)
    return sum(1 for i in range(len(s) - 1) if s[i + 1] == s[i] + 1)


def compute_consecutive_stats(draws: list, question: str) -> str:
    sorted_draws = sorted(draws, key=lambda d: d["round"])
    total = len(sorted_draws)
    count_series = [count_consecutive_pairs(d["numbers"]) for d in sorted_draws]

    current = count_series[-1]
    streak = detect_streak(count_series, current)
    transition = build_transition_matrix(count_series)
    after_streak = compute_after_streak(count_series, current, streak)
    counter = Counter(count_series)

    lines = [
        f"### 연번 분석 통계 (총 {total}회차)",
        f"최근 5회 연번 쌍 수: {count_series[-5:]}",
        f"현재 연번 쌍: {current}개 (최근 {streak}회 연속)",
        "",
        f"#### 현재 {current}쌍 이후 전이 확률:",
        format_transition(transition, current),
    ]
    if after_streak:
        lines.append(f"\n#### {current}쌍 {streak}회 연속 후 다음 분포:")
        for val, info in after_streak.items():
            lines.append(f"  {val}쌍: {info}")
    lines.append("\n#### 연번 쌍 수별 빈도:")
    for k in range(0, 6):
        cnt = counter.get(k, 0)
        if cnt > 0:
            lines.append(f"  {k}쌍: {cnt}회 ({round(cnt / total * 100, 1)}%)")

    return "\n".join(lines)


# ============================================================
# 번호 구간 통계
# ============================================================

def get_number_range_counts(numbers: list) -> dict:
    ranges = {"1~10": 0, "11~20": 0, "21~30": 0, "31~40": 0, "41~45": 0}
    for n in numbers:
        if n <= 10:
            ranges["1~10"] += 1
        elif n <= 20:
            ranges["11~20"] += 1
        elif n <= 30:
            ranges["21~30"] += 1
        elif n <= 40:
            ranges["31~40"] += 1
        else:
            ranges["41~45"] += 1
    return ranges


def compute_number_range_stats(draws: list, question: str) -> str:
    sorted_draws = sorted(draws, key=lambda d: d["round"])
    total = len(sorted_draws)
    range_keys = ["1~10", "11~20", "21~30", "31~40", "41~45"]

    range_totals = {k: 0 for k in range_keys}
    zero_counts = {k: 0 for k in range_keys}
    for d in sorted_draws:
        rng = get_number_range_counts(d["numbers"])
        for k in range_keys:
            v = rng[k]
            range_totals[k] += v
            if v == 0:
                zero_counts[k] += 1

    lines = [
        f"### 번호 구간 분석 통계 (총 {total}회차)",
        "\n#### 구간별 평균 출현 번호 수 (회차당) 및 멸(0개) 빈도:",
    ]
    for k in range_keys:
        avg = round(range_totals[k] / total, 2)
        zero_pct = round(zero_counts[k] / total * 100, 1)
        lines.append(f"  {k}: 평균 {avg}개, 멸(0개) {zero_pct}%")

    lines.append(f"\n#### 최근 5회 구간 현황:")
    for d in sorted_draws[-5:]:
        rng = get_number_range_counts(d["numbers"])
        lines.append(f"  {d['round']}회: {rng}")

    return "\n".join(lines)


# ============================================================
# 9궁(마법진) 통계
# ============================================================

def get_palace(n: int) -> int:
    """9궁 계산: 1-45를 5개씩 9개 궁으로 나눔 (궁 1~9)"""
    return (n - 1) // 5 + 1  # 1~9


def compute_magic_square_stats(draws: list, question: str) -> str:
    sorted_draws = sorted(draws, key=lambda d: d["round"])
    total = len(sorted_draws)

    palace_counts_all: dict = defaultdict(list)
    for d in sorted_draws:
        pc = Counter(get_palace(n) for n in d["numbers"])
        for p in range(1, 10):
            palace_counts_all[p].append(pc.get(p, 0))

    lines = [
        f"### 9궁 분석 통계 (총 {total}회차)",
        "\n#### 궁별 평균 출현수 및 멸(0개) 빈도:",
    ]
    for p in range(1, 10):
        cnts = palace_counts_all[p]
        avg = round(sum(cnts) / len(cnts), 2)
        zero_pct = round(cnts.count(0) / len(cnts) * 100, 1)
        lines.append(f"  {p}궁: 평균 {avg}개, 멸 {zero_pct}%")

    lines.append("\n#### 최근 5회 9궁 현황:")
    for d in sorted_draws[-5:]:
        pc = Counter(get_palace(n) for n in d["numbers"])
        lines.append(f"  {d['round']}회: {dict(sorted(pc.items()))}")

    return "\n".join(lines)


# ============================================================
# 번호별 통계 (stats_by_number, lotto_paper)
# ============================================================

def compute_stats_by_number(draws: list, question: str) -> str:
    sorted_draws = sorted(draws, key=lambda d: d["round"])
    total = len(sorted_draws)
    latest_round = sorted_draws[-1]["round"]

    freq: Counter = Counter()
    bonus_freq: Counter = Counter()
    for d in sorted_draws:
        for n in d["numbers"]:
            freq[n] += 1
        if d.get("bonus"):
            bonus_freq[d["bonus"]] += 1

    gaps = {}
    for n in range(1, 46):
        for d in reversed(sorted_draws):
            if n in d["numbers"]:
                gaps[n] = latest_round - d["round"]
                break
        else:
            gaps[n] = latest_round

    top10 = freq.most_common(10)
    bot10 = freq.most_common()[-10:]
    long_miss = sorted(gaps.items(), key=lambda x: x[1], reverse=True)[:10]

    lines = [
        f"### 번호별 통계 (총 {total}회차)",
        "",
        f"#### 상위 출현 번호 TOP 10:",
        ", ".join(f"{n}번({cnt}회/{round(cnt / total * 100, 1)}%)" for n, cnt in top10),
        "",
        f"#### 하위 출현 번호 (희소):",
        ", ".join(f"{n}번({cnt}회)" for n, cnt in bot10),
        "",
        f"#### 현재 장기 미출현 번호 (Gap 상위):",
        "\n".join(f"  {n}번: {g}회차 미출현" for n, g in long_miss),
        "",
        f"#### 보너스볼 상위 번호:",
        ", ".join(f"{n}번({cnt}회)" for n, cnt in bonus_freq.most_common(10)),
    ]
    return "\n".join(lines)


# ============================================================
# 배수 그룹 통계
# ============================================================

def compute_multiple_stats(draws: list, question: str) -> str:
    sorted_draws = sorted(draws, key=lambda d: d["round"])
    total = len(sorted_draws)

    mult3 = set(range(3, 46, 3))
    mult5 = set(range(5, 46, 5))
    mult7 = set(range(7, 46, 7))

    s3 = [len(set(d["numbers"]) & mult3) for d in sorted_draws]
    s5 = [len(set(d["numbers"]) & mult5) for d in sorted_draws]
    s7 = [len(set(d["numbers"]) & mult7) for d in sorted_draws]

    t3 = build_transition_matrix(s3)
    t5 = build_transition_matrix(s5)
    t7 = build_transition_matrix(s7)
    cur3, cur5, cur7 = s3[-1], s5[-1], s7[-1]

    lines = [
        f"### 배수 그룹 분석 통계 (총 {total}회차)",
        f"3배수 번호: {sorted(mult3)}",
        f"5배수 번호: {sorted(mult5)}",
        f"7배수 번호: {sorted(mult7)}",
        "",
        f"최근 5회 3배수 개수: {s3[-5:]} (현재: {cur3}개)",
        f"#### 3배수 {cur3}개 이후 전이:",
        format_transition(t3, cur3),
        "",
        f"최근 5회 5배수 개수: {s5[-5:]} (현재: {cur5}개)",
        f"#### 5배수 {cur5}개 이후 전이:",
        format_transition(t5, cur5),
        "",
        f"최근 5회 7배수 개수: {s7[-5:]} (현재: {cur7}개)",
        f"#### 7배수 {cur7}개 이후 전이:",
        format_transition(t7, cur7),
    ]
    return "\n".join(lines)


# ============================================================
# 이웃수 통계
# ============================================================

def compute_neighbor_stats(draws: list, question: str) -> str:
    sorted_draws = sorted(draws, key=lambda d: d["round"])
    total = len(sorted_draws)
    neighbor_counts = []

    for i in range(1, len(sorted_draws)):
        prev_nums = set(sorted_draws[i - 1]["numbers"])
        neighbors = set()
        for n in prev_nums:
            if n - 1 >= 1:
                neighbors.add(n - 1)
            if n + 1 <= 45:
                neighbors.add(n + 1)
        neighbors -= prev_nums
        curr_nums = set(sorted_draws[i]["numbers"])
        neighbor_counts.append(len(neighbors & curr_nums))

    counter = Counter(neighbor_counts)
    avg = sum(neighbor_counts) / len(neighbor_counts) if neighbor_counts else 0
    current = neighbor_counts[-1] if neighbor_counts else 0
    streak = detect_streak(neighbor_counts, current)
    transition = build_transition_matrix(neighbor_counts)
    after_streak = compute_after_streak(neighbor_counts, current, streak)

    lines = [
        f"### 이웃수 분석 통계 (총 {total}회차)",
        f"평균 이웃수 출현: {avg:.2f}개",
        f"최근 5회 이웃수 출현수: {neighbor_counts[-5:]}",
        f"현재 이웃수 출현: {current}개 (최근 {streak}회 연속)",
        "",
        f"#### 이웃수 {current}개 이후 전이 확률:",
        format_transition(transition, current),
    ]
    if after_streak:
        lines.append(f"\n#### {current}개 {streak}회 연속 후 다음 분포:")
        for val, info in after_streak.items():
            lines.append(f"  {val}개: {info}")
    lines.append("\n#### 이웃수 개수별 빈도:")
    nc_total = len(neighbor_counts)
    for k in range(0, 7):
        cnt = counter.get(k, 0)
        if cnt > 0:
            lines.append(f"  {k}개: {cnt}회 ({round(cnt / nc_total * 100, 1)}%)")

    return "\n".join(lines)


# ============================================================
# 메인 디스패처
# ============================================================

def compute_stats(draws: list, analysis_type: str, question: str) -> str:
    dispatch = {
        "ac_value": compute_ac_stats,
        "total_sum": compute_sum_stats,
        "odd_even": compute_odd_even_stats,
        "carryover": compute_carryover_stats,
        "hot_cold": compute_hot_cold_stats,
        "missing": compute_missing_stats,
        "tail_digit": compute_tail_digit_stats,
        "tail_sum": compute_tailsum_stats,
        "low_high": compute_low_high_stats,
        "consecutive_number": compute_consecutive_stats,
        "number_range": compute_number_range_stats,
        "magic_square": compute_magic_square_stats,
        "stats_by_number": compute_stats_by_number,
        "lotto_paper": compute_stats_by_number,
        "multiple": compute_multiple_stats,
        "neighbor_number": compute_neighbor_stats,
    }

    special_types = {
        "prime_number", "composite_number", "square_number",
        "triangular_number", "twin_number",
    }

    if analysis_type in dispatch:
        return dispatch[analysis_type](draws, question)
    elif analysis_type in special_types:
        return compute_special_number_stats(draws, question, analysis_type)
    else:
        # 기본: AC값 + 총합 기본 통계
        ac = compute_ac_stats(draws, question)
        sm = compute_sum_stats(draws, question)
        return ac + "\n\n" + sm


# ============================================================
# LLM 실행 (Q&A 전용 프롬프트)
# ============================================================

SMART_QUERY_PROMPT = """당신은 로또 통계 데이터를 기반으로 정확한 수치를 인용하는 분석 엔진입니다.

## 분석 주제: {topic}

## Python 계산 통계 데이터:
{stats_context}

## 사용자 질문:
{question}

---

## 필수 작성 규칙:
[R1] 첫 문장: 반드시 통계 데이터의 실제 수치를 그대로 인용하여 시작 (현재 상태 수치 포함)
[R2] 두 번째 문장: 전이 확률 또는 조건부 확률 수치를 인용하여 질문에 직접 답변
[R3] 세 번째 문장: 연속 패턴 또는 갭 데이터 기반 추가 근거 제시
[R4] "높다", "낮다" 등 형용사 단독 사용 금지 — 반드시 숫자로 수식
[R5] 데이터에 없는 내용은 절대 추론하지 말 것

## 절대 금지:
- "에너지", "흐름", "기운", "시나리오", "추천합니다", "가능성이 있습니다"
- "소액으로", "분산 투자", "재미로", "책임", "맹신"
- 데이터가 없는 수치 지어내기

## JSON 응답 형식 (순수 JSON만 출력, 마크다운 코드블록 금지):
{{"response": "[R1]. [R2]. [R3].", "highlights": [{{"text": "수치포함키워드", "type": "good"}}, {{"text": "수치포함키워드2", "type": "warn"}}]}}"""


async def run_smart_query(stats_context: str, question: str, analysis_type: str) -> dict:
    topic = ANALYSIS_TYPE_TO_TOPIC.get(analysis_type, "로또 통계 분석")
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
        temperature=0.1,
        google_api_key=config.GOOGLE_API_KEY,
    )
    prompt = PromptTemplate(
        template=SMART_QUERY_PROMPT,
        input_variables=["topic", "stats_context", "question"],
    )
    chain = prompt | llm | StrOutputParser()
    try:
        result_text = await chain.ainvoke(
            {"topic": topic, "stats_context": stats_context, "question": question}
        )
        cleaned = result_text.replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(cleaned)
        except Exception:
            return {"response": cleaned, "highlights": []}
    except Exception as e:
        return {"response": f"분석 오류: {str(e)}", "highlights": []}


# ============================================================
# 라우터 엔드포인트
# ============================================================

@router.post("/smart-query")
async def smart_query(req: SmartQueryRequest):
    """
    분석타입별 Supabase 통계 계산 후 LLM Q&A 실행
    기존 /api/analyze보다 더 깊은 통계(전이행렬, 조건부확률, streak/gap) 제공
    """
    try:
        draws = fetch_all_draws()
        if not draws:
            return {"response": "데이터를 불러올 수 없습니다.", "highlights": []}

        stats_context = compute_stats(draws, req.analysis_type, req.question)
        result = await run_smart_query(stats_context, req.question, req.analysis_type)
        return result

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"response": f"서버 오류: {str(e)}", "highlights": []}
