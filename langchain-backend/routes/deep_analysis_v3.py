"""딥러닝 심층 분석 v3 API - LLM 전략 분석 통합 버전.

v3 특징:
  - v2의 LLM 전략 분석 기능 통합
  - 이력 저장 기능 추가
  - 5중 앙상블 모델 (Transformer, LSTM, CNN, XGBoost, Markov)
  - 12+ 필터별 모델 예상 범위
  - Hot/Cold 상태 분석, 9궁 분석
"""

import json
import traceback
print("\n" + "!"*60 + "\nANTIGRAVITY DEBUG: deep_analysis_v3.py LOADED\n" + "!"*60 + "\n")
import time
import re
import numpy as np
import random
from collections import Counter
from datetime import datetime, timezone
from fastapi import APIRouter, Request
from starlette.responses import Response

from db.supabase_client import fetch_all_draws, get_client, fetch_missing_counts
from models.ensemble import LottoEnsemble, CombinationGenerator
from chains.memo_parser import parse_expert_memo
import config

router = APIRouter(prefix="/api/deep-analysis/v3", tags=["deep-analysis-v3"])

class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.integer, int)): return int(obj)
        if isinstance(obj, (np.floating, float)): return float(obj)
        if isinstance(obj, np.ndarray): return obj.tolist()
        return super().default(obj)

def _json_response(data: dict):
    return Response(content=json.dumps(data, cls=NumpyEncoder, ensure_ascii=False), 
                    status_code=200, media_type="application/json")

# ------------------------------------------------------------------
# 1. 기초분석 시뮬레이터 (15종+)
# ------------------------------------------------------------------
def simulate_all_filters(model_probs, history_draws, n_sim=1000):
    nums = list(model_probs.keys())
    probs = list(model_probs.values())
    total_prob = sum(probs)
    if total_prob == 0:
        return {}, {}
    norm_probs = [p/total_prob for p in probs]

    stats = {k: [] for k in ["sum", "ac", "odd", "high", "prime", "consecutive", "tail_sum", "composite", "square", "triangular", "twin", "mul3", "mul4", "mul5", "non_multiple", "hot10", "missing", "neighbor", "carryover"]}
    PRIMES = {2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43}
    SQUARES = {1, 4, 9, 16, 25, 36}
    TRIANGULARS = {1, 3, 6, 10, 15, 21, 28, 36, 45}
    TWINS = {11, 22, 33, 44}
    MUL3_NUMS = {3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36, 39, 42, 45}
    MUL4_NUMS = {4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44}
    MUL5_NUMS = {5, 10, 15, 20, 25, 30, 35, 40, 45}
    MULTIPLE_ALL = MUL3_NUMS | MUL4_NUMS | MUL5_NUMS
    
    # 핫10, 장기미출현, 이웃수, 이월수 기준 데이터 준비
    last_10 = [set(d.get("numbers", [])) for d in history_draws[:10]]
    hot10_nums = set().union(*last_10) if last_10 else set()
    
    missing_nums = set()
    for n in range(1, 46):
        gap = 0
        for d in history_draws:
            if n in d.get("numbers", []): break
            gap += 1
        if gap >= 10: missing_nums.add(n)
        
    latest_nums = set(history_draws[0].get("numbers", [])) if history_draws else set()
    neighbor_nums = set()
    for n in latest_nums:
        for offset in [-1, 1]:
            neighbor = n + offset
            if 1 <= neighbor <= 45: neighbor_nums.add(neighbor)

    for _ in range(n_sim):
        c = sorted(np.random.choice(nums, 6, replace=False, p=norm_probs))
        c_int = [int(x) for x in c]

        stats["sum"].append(sum(c_int))
        diffs = set()
        for i in range(6):
            for j in range(i+1, 6): diffs.add(c_int[j]-c_int[i])
        stats["ac"].append(len(diffs)-5)
        stats["odd"].append(sum(1 for x in c_int if x%2!=0))
        stats["high"].append(sum(1 for x in c_int if x>22))
        stats["tail_sum"].append(sum(x%10 for x in c_int))
        stats["prime"].append(sum(1 for x in c_int if x in PRIMES))
        stats["composite"].append(6 - sum(1 for x in c_int if x in PRIMES))
        stats["square"].append(sum(1 for x in c_int if x in SQUARES))
        stats["triangular"].append(sum(1 for x in c_int if x in TRIANGULARS))
        stats["twin"].append(sum(1 for x in c_int if x in TWINS))
        stats["mul3"].append(sum(1 for x in c_int if x%3==0))
        stats["mul4"].append(sum(1 for x in c_int if x%4==0))
        stats["mul5"].append(sum(1 for x in c_int if x%5==0))
        stats["consecutive"].append(sum(1 for i in range(5) if c_int[i+1]-c_int[i]==1))
        stats["non_multiple"].append(sum(1 for x in c_int if x not in MULTIPLE_ALL))
        stats["hot10"].append(sum(1 for x in c_int if x in hot10_nums))
        stats["missing"].append(sum(1 for x in c_int if x in missing_nums))
        stats["neighbor"].append(sum(1 for x in c_int if x in neighbor_nums))
        stats["carryover"].append(sum(1 for x in c_int if x in latest_nums))

    ranges = {}
    filter_settings = {}
    for k, v in stats.items():
        v.sort()
        if k in ["sum", "tail_sum"]:
            low, high = v[int(n_sim*0.2)], v[int(n_sim*0.8)]
            ranges[k] = [int(low), int(high)]
            if k == "sum": filter_settings["sum_range"] = {"min": int(low), "max": int(high)}
        else:
            low, high = v[int(n_sim*0.1)], v[int(n_sim*0.9)]
            ranges[k] = f"{low}~{high}"
            
    return ranges, filter_settings

# ------------------------------------------------------------------
# 1.5. 숫자별 모델 근거 생성
# ------------------------------------------------------------------
def get_number_model_reasons(num: int, streak: int, gap: int, freq: float, history_draws: list):
    """숫자별 각 모델의 근거 텍스트 생성"""
    reasons = {}

    # LSTM: 시계열 기반
    if streak >= 3:
        reasons["lstm"] = f"최근 {streak}회 연속 출현 | 시계열 강한 상승추세"
    elif gap <= 2:
        reasons["lstm"] = f"{gap}회 전 출현 | 즉시 재출현 패턴 감지"
    elif gap >= 15:
        reasons["lstm"] = f"장시간 미출현({gap}회) | 주기 회귀 신호 감지"
    elif gap >= 8:
        reasons["lstm"] = f"중기 회복({gap}회 경과) | 약한 상승신호"
    else:
        reasons["lstm"] = f"안정적 주기 상태(Gap={gap}회) | 중립적 신호"

    # XGBoost: 빈도 기반
    if freq > 0.16:
        reasons["xgboost"] = f"높은 빈도({freq:.1%}) | 통계 패턴 매우 강함"
    elif freq > 0.10:
        reasons["xgboost"] = f"높은 빈도({freq:.1%}) | 빈도 기반 신뢰도 높음"
    elif freq >= 0.06:
        reasons["xgboost"] = f"중간 빈도({freq:.1%}) | 평균적 패턴"
    elif freq >= 0.04:
        reasons["xgboost"] = f"낮은 빈도({freq:.1%}) | 패턴 약함"
    else:
        reasons["xgboost"] = f"매우 낮은 빈도({freq:.1%}) | 통계 신호 약함"

    # CNN: 이웃 그룹 분석
    neighbors = [num-1, num, num+1] if 2 <= num <= 44 else ([num, num+1, num+2] if num == 1 else [num-2, num-1, num])
    neighbor_freq = sum(1 for d in history_draws[-20:] for neighbor in neighbors if neighbor in d["numbers"]) / (20 * 3) if history_draws else 0
    if neighbor_freq > 0.35:
        reasons["cnn"] = f"이웃그룹 활성({neighbor_freq:.1%}) | 공간 시너지 매우 높음"
    elif neighbor_freq > 0.25:
        reasons["cnn"] = f"이웃그룹 활성({neighbor_freq:.1%}) | 공간 응집도 양호"
    elif neighbor_freq > 0.15:
        reasons["cnn"] = f"이웃그룹 중간({neighbor_freq:.1%}) | 약한 공간 신호"
    else:
        reasons["cnn"] = f"이웃그룹 고립({neighbor_freq:.1%}) | 공간 신호 약함"

    # Transformer: 주기 패턴
    period_occurrences = []
    current_gap = 0
    for d in history_draws[-50:]:
        if num in d["numbers"]:
            if current_gap > 0:
                period_occurrences.append(current_gap)
            current_gap = 0
        else:
            current_gap += 1

    if period_occurrences:
        avg_period = sum(period_occurrences) / len(period_occurrences)
        reasons["transformer"] = f"주기패턴 ~{avg_period:.0f}회 | 주기성 규칙도: {len(period_occurrences)}회"
    else:
        reasons["transformer"] = f"주기분석 불충분 | 데이터 부족"

    # Markov: 전이 확률
    recent_count = sum(1 for d in history_draws[-20:] if num in d["numbers"])
    transition_prob = recent_count / min(20, len(history_draws)) if history_draws else 0
    if transition_prob >= 0.20:
        reasons["markov"] = f"높은 전이({transition_prob:.1%}) | 상태 강하게 지속"
    elif transition_prob >= 0.10:
        reasons["markov"] = f"중간 전이({transition_prob:.1%}) | 상태 지속 신호"
    elif transition_prob >= 0.05:
        reasons["markov"] = f"낮은 전이({transition_prob:.1%}) | 상태 약화 신호"
    else:
        reasons["markov"] = f"매우 낮은 전이({transition_prob:.1%}) | 상태 전환"
        
    # Autoencoder: 차원 압축 기반
    if freq >= 0.15:
        reasons["autoencoder"] = f"주요 특징 추출({freq:.1%}) | 핵심 패턴 일치"
    elif gap >= 15:
        reasons["autoencoder"] = f"잠재 패턴 활성화(Gap={gap}) | 복원 신호 감지"
    elif streak >= 2:
        reasons["autoencoder"] = f"연속 특징 유지({streak}회) | 단기 트렌드 강함"
    else:
        reasons["autoencoder"] = f"압축 특징 평이 | 기저 상태 유지"

    # GNN: 그래프 및 관계망 기반
    if freq >= 0.12 and streak >= 2:
        reasons["gnn"] = f"핵심 노드 편입 유력 (초고빈도+연속성)"
    elif neighbor_freq > 0.25:
        reasons["gnn"] = f"이웃 노드 연결망 활성 (강한 관계망)"
    elif gap >= 15:
        reasons["gnn"] = f"장기 휴면 그래프 (연결 끊김, 회복 대기)"
    else:
        reasons["gnn"] = f"일반 노드 상태 유지 (특이 단서 부족)"

    return reasons

# ------------------------------------------------------------------
# 1.6. 필터별 모델 예상 범위
# ------------------------------------------------------------------
def get_model_filter_expectations(filter_name: str, history_draws: list, model_contributions: dict):
    """필터별 5개 모델의 예상 범위를 계산"""
    models = ["lstm", "xgboost", "cnn", "transformer", "markov", "autoencoder", "gnn"]
    PRIMES = {2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43}
    COMPOSITES = {4, 6, 8, 9, 10, 12, 14, 15, 16, 18, 20, 21, 22, 24, 25, 26, 27, 28, 30, 32, 33, 34, 35, 36, 38, 39, 40, 42, 44, 45}
    SQUARES = {1, 4, 9, 16, 25, 36}
    TRIANGULARS = {1, 3, 6, 10, 15, 21, 28, 36, 45}
    TWINS = {11, 22, 33, 44}
    MUL3_NUMS = {3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36, 39, 42, 45}
    MUL4_NUMS = {4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44}
    MUL5_NUMS = {5, 10, 15, 20, 25, 30, 35, 40, 45}
    
    # 동적 컨텍스트 데이터 계산 (Hot10, Missing, Neighbor, Carryover)
    last_10 = [set(d.get("numbers", [])) for d in history_draws[:10]]
    hot10_nums = set().union(*last_10) if last_10 else set()
    
    missing_nums = set()
    for n in range(1, 46):
        gap = 0
        for d in history_draws:
            if n in d.get("numbers", []): break
            gap += 1
        if gap >= 10: missing_nums.add(n)
        
    latest_nums = set(history_draws[0].get("numbers", [])) if history_draws else set()
    neighbor_nums = set()
    for n in latest_nums:
        for offset in [-1, 1]:
            neighbor = n + offset
            if 1 <= neighbor <= 45: neighbor_nums.add(neighbor)

    # 각 모델의 상위 15개 번호 추출 (확률 비례 포함)
    model_top15 = {}
    model_top15_probs = {}
    for m in models:
        m_probs = model_contributions.get(m, {})
        sorted_nums = sorted(m_probs.items(), key=lambda x: x[1], reverse=True)[:15]
        model_top15[m] = [int(num) for num, _ in sorted_nums]
        raw_probs = [float(p) for _, p in sorted_nums]
        total_p = sum(raw_probs) or 1.0
        model_top15_probs[m] = [p / total_p for p in raw_probs]

    def _sim_filter(pool, probs, filter_fn, n_sim=500, lo=0.2, hi=0.8):
        """pool 15개에서 6개 비복원 시뮬레이션 → 필터값 분포의 lo~hi 분위수 반환"""
        if len(pool) < 6:
            return 0, 999  # 데이터가 부족하면 매우 넓은 범위 반환

        vals = []
        pool_arr = np.array(pool)
        prob_arr = np.array(probs, dtype=float)
        
        # 확률 합이 0인 경우 예외 처리
        prob_sum = prob_arr.sum()
        if prob_sum == 0:
            return 0, 999
            
        prob_arr /= prob_sum  # 명시적 정규화
        for _ in range(n_sim):
            chosen = sorted(np.random.choice(pool_arr, 6, replace=False, p=prob_arr).tolist())
            vals.append(filter_fn(chosen))
        vals.sort()
        return vals[int(n_sim * lo)], vals[int(n_sim * hi)]

    def _ac(nums):
        diffs = set()
        for i in range(len(nums)):
            for j in range(i + 1, len(nums)):
                diffs.add(abs(nums[i] - nums[j]))
        return len(diffs) - 5  # AC = 차이값 집합 크기 - (6-1)

    expectations = {}
    MULTIPLE_ALL = MUL3_NUMS | MUL4_NUMS | MUL5_NUMS

    # 필터별 함수 정의
    FILTER_FN = {
        "sum":          lambda c: sum(c),
        "tail_sum":     lambda c: sum(x % 10 for x in c),
        "ac":           _ac,
        "odd":          lambda c: sum(1 for x in c if x % 2 == 1),
        "high":         lambda c: sum(1 for x in c if x >= 23),
        "prime":        lambda c: sum(1 for x in c if x in PRIMES),
        "composite":    lambda c: sum(1 for x in c if x in COMPOSITES),
        "consecutive":  lambda c: sum(1 for i in range(5) if c[i+1] - c[i] == 1),
        "square":       lambda c: sum(1 for x in c if x in SQUARES),
        "triangular":   lambda c: sum(1 for x in c if x in TRIANGULARS),
        "twin":         lambda c: sum(1 for x in c if x in TWINS),
        "mul3":         lambda c: sum(1 for x in c if x in MUL3_NUMS),
        "mul4":         lambda c: sum(1 for x in c if x in MUL4_NUMS),
        "mul5":         lambda c: sum(1 for x in c if x in MUL5_NUMS),
        "non_multiple": lambda c: sum(1 for x in c if x not in MULTIPLE_ALL),
        # [New] 추가 필터
        "hot10":        lambda c: sum(1 for x in c if x in hot10_nums),
        "missing":      lambda c: sum(1 for x in c if x in missing_nums),
        "neighbor":     lambda c: sum(1 for x in c if x in neighbor_nums),
        "carryover":    lambda c: sum(1 for x in c if x in latest_nums),
    }

    # 필터별 물리적 상한/하한 (6개 번호 기준 절대 범위)
    FILTER_CLAMP = {
        "sum":          (21, 255),
        "tail_sum":     (0,  54),
        "ac":           (0,  10),
        "odd":          (0,   6),
        "high":         (0,   6),
        "prime":        (0,   6),
        "composite":    (0,   6),
        "consecutive":  (0,   5),
        "square":       (0,   6),
        "triangular":   (0,   6),
        "twin":         (0,   6),
        "mul3":         (0,   6),
        "mul4":         (0,   6),
        "mul5":         (0,   6),
        "non_multiple": (0,   6),
        "hot10":        (0,   6),
        "missing":      (0,   6),
        "neighbor":     (0,   6),
        "carryover":    (0,   6),
    }

    fn = FILTER_FN.get(filter_name)
    clamp = FILTER_CLAMP.get(filter_name, (0, 999))

    if fn is not None:
        for m in models:
            pool  = model_top15[m]
            probs = model_top15_probs[m]
            lo, hi = _sim_filter(pool, probs, fn)
            # 물리적 범위 내로 클램핑
            lo = max(clamp[0], lo)
            hi = min(clamp[1], hi)
            if lo > hi:
                lo, hi = hi, lo
            # 대표값 (중앙값 계산용)
            mid = round((lo + hi) / 2)
            expectations[m] = {
                "min": int(lo),
                "max": int(hi),
                "reasoning": f"시뮬레이션 20~80분위 범위 (대표값:{mid})"
            }

    return expectations

# ------------------------------------------------------------------
# 1.7. 커스텀 그룹 필터 추천
# ------------------------------------------------------------------
def recommend_filters_for_group(group_nums: list, contribs: dict):
    """커스텀 그룹 사용 시 필요한 보완 필터 추천"""
    if not group_nums:
        return {}

    PRIMES = {2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43}
    COMPOSITES = {4, 6, 8, 9, 10, 12, 14, 15, 16, 18, 20, 21, 22, 24, 25, 26, 27, 28, 30, 32, 33, 34, 35, 36, 38, 39, 40, 42, 44, 45}
    SQUARES = {1, 4, 9, 16, 25, 36}
    TRIANGULARS = {1, 3, 6, 10, 15, 21, 28, 36, 45}
    TWINS = {11, 22, 33, 44}
    MUL3_NUMS = {3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36, 39, 42, 45}
    MUL4_NUMS = {4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44}
    MUL5_NUMS = {5, 10, 15, 20, 25, 30, 35, 40, 45}
    MULTIPLE_ALL = MUL3_NUMS | MUL4_NUMS | MUL5_NUMS

    recommendations = {}

    # Sum 추천
    group_sum = sum(group_nums)
    if group_sum < 80:
        recommendations["sum"] = {"min": group_sum + 40, "max": 170, "reason": "합계 부족"}
    elif group_sum > 160:
        recommendations["sum"] = {"min": 80, "max": group_sum - 40, "reason": "합계 과다"}
    else:
        recommendations["sum"] = {"min": max(80, group_sum - 15), "max": min(180, group_sum + 15), "reason": "합계 적정"}

    # AC 추천
    group_sorted = sorted(group_nums)
    group_diffs = set()
    for i in range(len(group_sorted)):
        for j in range(i+1, len(group_sorted)):
            group_diffs.add(group_sorted[j] - group_sorted[i])
    group_ac = len(group_diffs) - 5
    recommendations["ac"] = {"min": max(0, group_ac - 2), "max": min(35, group_ac + 2), "reason": f"AC값: {group_ac}"}

    # Odd/Even 추천
    group_odd = sum(1 for n in group_nums if n % 2 == 1)
    if group_odd <= 1:
        recommendations["odd"] = {"min": group_odd + 2, "max": 5, "reason": "홀수 부족"}
    elif group_odd >= 5:
        recommendations["odd"] = {"min": 1, "max": group_odd - 2, "reason": "홀수 과다"}
    else:
        recommendations["odd"] = {"min": max(2, group_odd - 1), "max": min(4, group_odd + 1), "reason": "홀짝 적정"}

    # High/Low 추천
    group_high = sum(1 for n in group_nums if n >= 23)
    if group_high == 0:
        recommendations["high"] = {"min": 2, "max": 4, "reason": "고번호 없음"}
    elif group_high == len(group_nums):
        recommendations["high"] = {"min": 0, "max": len(group_nums) - 2, "reason": "저번호 없음"}
    else:
        recommendations["high"] = {"min": max(1, group_high - 1), "max": min(5, group_high + 1), "reason": "저고 적정"}

    # Tail Sum 추천
    group_tail_sum = sum(n % 10 for n in group_nums)
    recommendations["tail_sum"] = {"min": max(0, group_tail_sum - 12), "max": min(45, group_tail_sum + 12), "reason": f"끝수합: {group_tail_sum}"}

    # Prime 추천
    group_prime = sum(1 for n in group_nums if n in PRIMES)
    recommendations["prime"] = {"min": max(0, group_prime - 1), "max": min(6, group_prime + 1), "reason": f"소수: {group_prime}개"}

    # Composite 추천
    group_composite = sum(1 for n in group_nums if n in COMPOSITES)
    recommendations["composite"] = {"min": max(0, group_composite - 1), "max": min(6, group_composite + 1), "reason": f"합성수: {group_composite}개"}

    # Consecutive 추천
    consecutive_count = sum(1 for i in range(len(group_sorted)-1) if group_sorted[i+1] - group_sorted[i] == 1)
    recommendations["consecutive"] = {"min": max(0, consecutive_count - 1), "max": min(5, consecutive_count + 2), "reason": f"연속쌍: {consecutive_count}개"}

    # Square 추천
    group_square = sum(1 for n in group_nums if n in SQUARES)
    recommendations["square"] = {"min": max(0, group_square - 1), "max": min(6, group_square + 1), "reason": f"제곱수: {group_square}개"}

    # Triangular 추천
    group_triangular = sum(1 for n in group_nums if n in TRIANGULARS)
    recommendations["triangular"] = {"min": max(0, group_triangular - 1), "max": min(6, group_triangular + 1), "reason": f"삼각수: {group_triangular}개"}

    # Twin (동형수) 추천
    group_twin = sum(1 for n in group_nums if n in TWINS)
    recommendations["twin"] = {"min": max(0, group_twin - 1), "max": min(6, group_twin + 1), "reason": f"동형수: {group_twin}개"}

    # Mul3 추천
    group_mul3 = sum(1 for n in group_nums if n in MUL3_NUMS)
    recommendations["mul3"] = {"min": max(0, group_mul3 - 1), "max": min(6, group_mul3 + 1), "reason": f"3배수: {group_mul3}개"}

    # Mul4 추천
    group_mul4 = sum(1 for n in group_nums if n in MUL4_NUMS)
    recommendations["mul4"] = {"min": max(0, group_mul4 - 1), "max": min(6, group_mul4 + 1), "reason": f"4배수: {group_mul4}개"}

    # Mul5 추천
    group_mul5 = sum(1 for n in group_nums if n in MUL5_NUMS)
    recommendations["mul5"] = {"min": max(0, group_mul5 - 1), "max": min(6, group_mul5 + 1), "reason": f"5배수: {group_mul5}개"}

    # Non-multiple 추천
    group_non_mul = sum(1 for n in group_nums if n not in MULTIPLE_ALL)
    recommendations["non_multiple"] = {"min": max(0, group_non_mul - 1), "max": min(6, group_non_mul + 1), "reason": f"배수외: {group_non_mul}개"}

    return recommendations

# ------------------------------------------------------------------
# 1.75 과출현 패널티 + Gap 주기 보정
# ------------------------------------------------------------------
def calc_stat_correction(history_draws: list, final_probs: dict) -> dict:
    """
    두 가지 보정 계수를 번호별로 계산:
    1) over_penalty  : 최근 N회 과출현 번호 → 점수 하향
       - 기대 출현 횟수 = N × 6/45
       - 실제 출현 횟수 / 기대 = over_ratio
       - over_ratio >= 2.5 → penalty 강, 1.8~2.5 → 중간, else → 없음
    2) gap_boost     : 번호별 고유 주기를 초과한 번호 → 점수 상향
       - 역대 출현 간격(gap) 평균 = personal_avg_gap
       - 현재 gap / personal_avg_gap = gap_ratio
       - gap_ratio >= 1.0 → boost (주기 이미 초과, 출현 임박)
    반환: {num: {"over_ratio": float, "penalty": float,
                 "gap_ratio": float, "boost": float,
                 "adj_factor": float}}  # adj_factor = 최종 곱셈 계수
    """
    WINDOW_LIST = [5, 10, 20]   # 단기/중기/중장기 모두 반영
    EXPECTED_BASE = 6 / 45      # 회차당 기대 출현 확률

    result = {}
    for num in range(1, 46):
        # ── 1. 과출현 패널티 계산 ──────────────────────────────
        max_over_ratio = 0.0
        for w in WINDOW_LIST:
            recent = history_draws[:w]
            actual = sum(1 for d in recent if num in d.get("numbers", []))
            expected = w * EXPECTED_BASE
            ratio = actual / expected if expected > 0 else 0.0
            if ratio > max_over_ratio:
                max_over_ratio = ratio

        # 패널티 계수 (1.0 = 패널티 없음, 0.x = 하향)
        if max_over_ratio >= 3.0:
            penalty = 0.30   # 극심한 과출현 → 70% 하향
        elif max_over_ratio >= 2.5:
            penalty = 0.45   # 강한 과출현 → 55% 하향
        elif max_over_ratio >= 1.8:
            penalty = 0.65   # 중간 과출현 → 35% 하향
        else:
            penalty = 1.0    # 정상 범위

        # ── 2. Gap 주기 부스트 계산 ──────────────────────────────
        # 역대 출현 회차 인덱스 목록 (최신=0, 과거=큰값)
        appear_indices = [idx for idx, d in enumerate(history_draws)
                          if num in d.get("numbers", [])]
        # 연속 출현 간격 계산 (인덱스 차이)
        gaps_list = []
        for i in range(len(appear_indices) - 1):
            gap_between = appear_indices[i+1] - appear_indices[i]
            if gap_between > 0:
                gaps_list.append(gap_between)
        # 역대 평균 gap (2회 이상 간격 데이터가 있을 때만)
        personal_avg_gap = sum(gaps_list) / len(gaps_list) if len(gaps_list) >= 2 else None

        # 현재 gap (마지막 출현 이후 경과 회차)
        current_gap = 0
        for d in history_draws:
            if num in d.get("numbers", []):
                break
            current_gap += 1

        # gap_ratio: 현재 gap / 개인 평균 gap
        if personal_avg_gap and personal_avg_gap > 0:
            gap_ratio = current_gap / personal_avg_gap
        else:
            # 데이터 부족 시 전체 기대 gap(45/6=7.5) 기준으로 보정
            gap_ratio = current_gap / 7.5

        # 부스트 계수 (1.0 = 부스트 없음, 1.x = 상향)
        if gap_ratio >= 2.0:
            boost = 1.50    # 주기 2배 초과 → 50% 상향
        elif gap_ratio >= 1.5:
            boost = 1.30    # 주기 1.5배 초과 → 30% 상향
        elif gap_ratio >= 1.0:
            boost = 1.15    # 주기 초과 → 15% 상향
        else:
            boost = 1.0     # 아직 주기 미달

        # ── 3. 최종 보정 계수 (패널티 × 부스트) ────────────────
        # 과출현이면서 gap도 짧으면 패널티 우선 (boost 무효화)
        if penalty < 1.0 and gap_ratio < 0.5:
            boost = 1.0  # 이미 많이 나왔고 최근에 나왔다 → 부스트 없음

        adj_factor = penalty * boost

        result[num] = {
            "over_ratio": round(max_over_ratio, 2),
            "penalty": round(penalty, 2),
            "gap_ratio": round(gap_ratio, 2),
            "boost": round(boost, 2),
            "adj_factor": round(adj_factor, 2),
            "current_gap": current_gap,
            "personal_avg_gap": round(personal_avg_gap, 1) if personal_avg_gap else None,
        }

    return result


# ------------------------------------------------------------------
# 1.8 Hot/Cold 상태 분석
# ------------------------------------------------------------------
def get_number_status(num: int, history_draws: list):
    """번호의 gap을 계산하고 상태를 반환"""
    gap = 0
    for draw in history_draws:
        if num in draw.get("numbers", []):
            break
        gap += 1

    if gap <= 2: return "hot"
    elif gap <= 7: return "active"
    elif gap <= 15: return "cooling"
    elif gap <= 25: return "cold"
    else: return "deadcold"

def analyze_hot_cold(final_probs, history_draws, contribs):
    """Hot/Cold 상태 분석 - 모델별 점수 포함"""
    models = ["lstm", "xgboost", "cnn", "transformer", "markov", "autoencoder", "gnn"]

    # 각 번호별 gap 계산
    num_gaps = {}
    for num in range(1, 46):
        gap = 0
        for draw in history_draws:
            if num in draw.get("numbers", []):
                break
            gap += 1
        num_gaps[num] = gap

    # 상태별 번호 분류
    STATUS_CRITERIA = [
        ("hot",      lambda g: g <= 2),
        ("active",   lambda g: 3 <= g <= 7),
        ("cooling",  lambda g: 8 <= g <= 15),
        ("cold",     lambda g: 16 <= g <= 25),
        ("deadcold", lambda g: g > 25),
    ]
    status_groups = {s: [] for s, _ in STATUS_CRITERIA}
    for num in range(1, 46):
        for status, fn in STATUS_CRITERIA:
            if fn(num_gaps[num]):
                status_groups[status].append(num)
                break

    final_probs_sorted = sorted(final_probs.items(), key=lambda x: x[1], reverse=True)
    top_nums = set([int(num) for num, _ in final_probs_sorted[:15]])

    # 모델별 전체 순위 사전 계산
    model_ranks = {}
    for m in models:
        m_probs = [(n, contribs.get(m, {}).get(n, 0)) for n in range(1, 46)]
        m_probs.sort(key=lambda x: x[1], reverse=True)
        model_ranks[m] = {num: (idx + 1) for idx, (num, _) in enumerate(m_probs)}

    status_analysis = {}
    for status, nums in status_groups.items():
        if not nums:
            status_analysis[status] = {
                "count": 0, "numbers": [], "top_count": 0,
                "avg_prob": 0.0, "avg_gap": 0.0,
                "model_scores": {m: {"avg_rank": 0, "top_count": 0, "signal": "neutral"} for m in models}
            }
            continue

        avg_prob = sum(final_probs.get(n, 0) for n in nums) / len(nums)
        avg_gap = sum(num_gaps[n] for n in nums) / len(nums)
        top_count = sum(1 for n in nums if n in top_nums)

        # 모델별 점수
        model_scores = {}
        for m in models:
            ranks = [model_ranks[m].get(n, 45) for n in nums]
            avg_rank = sum(ranks) / len(ranks)
            m_top = sum(1 for n in nums if model_ranks[m].get(n, 45) <= 15)

            # 신호 판정: 평균 순위 기준
            if avg_rank <= 15:
                signal = "positive"   # 모델이 이 구간 선호
            elif avg_rank <= 25:
                signal = "neutral"    # 중립
            else:
                signal = "negative"   # 모델이 이 구간 기피

            model_scores[m] = {
                "avg_rank": round(avg_rank, 1),
                "top_count": m_top,
                "signal": signal
            }

        # 번호별 상세 (전체 번호 포함)
        num_details = []
        for n in sorted(nums):
            per_model = {}
            for m in models:
                rank = model_ranks[m].get(n, 45)
                prob = contribs.get(m, {}).get(n, 0)
                per_model[m] = {"rank": rank, "prob": round(float(prob) * 100, 2)}
            num_details.append({
                "num": n,
                "gap": num_gaps[n],
                "ensemble_prob": round(float(final_probs.get(n, 0)) * 100, 2),
                "is_top15": n in top_nums,
                "models": per_model
            })

        status_analysis[status] = {
            "count": len(nums),
            "numbers": nums,
            "top_count": top_count,
            "avg_prob": round(float(avg_prob), 4),
            "avg_gap": round(avg_gap, 1),
            "model_scores": model_scores,
            "num_details": num_details
        }

    return status_analysis

# ------------------------------------------------------------------
# 1.9 9궁(9-Palace) 분석
# ------------------------------------------------------------------
def get_palace_info(num: int):
    """번호의 9궁 위치 반환"""
    if 1 <= num <= 5: return {"position": "상좌", "index": 0}
    elif 6 <= num <= 10: return {"position": "상중", "index": 1}
    elif 11 <= num <= 15: return {"position": "상우", "index": 2}
    elif 16 <= num <= 20: return {"position": "중좌", "index": 3}
    elif 21 <= num <= 25: return {"position": "중중", "index": 4}
    elif 26 <= num <= 30: return {"position": "중우", "index": 5}
    elif 31 <= num <= 35: return {"position": "하좌", "index": 6}
    elif 36 <= num <= 40: return {"position": "하중", "index": 7}
    elif 41 <= num <= 45: return {"position": "하우", "index": 8}
    return None

def analyze_9palace(combination: list, history_draws: list):
    """9궁 분석 수행"""
    palace_distribution = {
        "상좌": 0, "상중": 0, "상우": 0,
        "중좌": 0, "중중": 0, "중우": 0,
        "하좌": 0, "하중": 0, "하우": 0
    }

    for num in combination:
        palace = get_palace_info(num)
        if palace:
            palace_distribution[palace["position"]] += 1

    values = list(palace_distribution.values())
    max_count = max(values) if values else 0
    min_count = min([v for v in values if v > 0]) if any(v > 0 for v in values) else 0

    if max_count - min_count >= 3: balance = "편중 심함"
    elif max_count - min_count >= 2: balance = "편중 있음"
    else: balance = "균형 좋음"

    recent_palace = {
        "상좌": 0, "상중": 0, "상우": 0,
        "중좌": 0, "중중": 0, "중우": 0,
        "하좌": 0, "하중": 0, "하우": 0
    }
    for draw in history_draws[:50]:
        for num in draw.get("numbers", []):
            palace = get_palace_info(num)
            if palace:
                recent_palace[palace["position"]] += 1

    return {
        "distribution": palace_distribution,
        "balance": balance,
        "recent_frequency": recent_palace
    }

# ------------------------------------------------------------------
# 2. 끝수 정밀 분석
# ------------------------------------------------------------------
def analyze_tail_detailed(final_probs, history_draws, model_contributions=None):
    tails = []
    models = ["lstm", "xgboost", "cnn", "transformer", "markov", "autoencoder", "gnn"]

    # 앙상블 확률 정규화 (합=1)
    ens_total = sum(final_probs.values())
    if ens_total == 0:
        norm_final = {n: 0 for n in final_probs}
    else:
        norm_final = {int(n): v / ens_total for n, v in final_probs.items()}

    # 모델별 확률 정규화 캐시 (한 번만 계산)
    norm_model = {}
    if model_contributions:
        for m in models:
            m_probs = model_contributions.get(m, {})
            m_total = sum(m_probs.values())
            if m_total == 0:
                norm_model[m] = {}
            else:
                norm_model[m] = {int(n): v / m_total for n, v in m_probs.items()}

    for t in range(10):
        t_nums = [n for n in range(1, 46) if n % 10 == t]
        # 정규화 후 *6 (6개 번호 기준 기대값)
        ens_exp = sum(norm_final.get(n, 0) for n in t_nums) * 6

        # Gap: 해당 끝수가 마지막으로 출현한 이후 경과 회차
        gap = 0
        for draw in history_draws:
            if t in [n % 10 for n in draw["numbers"]]: break
            gap += 1

        # STR: 가장 최근 연속 출현 횟수
        str_count = 0
        for draw in history_draws:
            if t in [n % 10 for n in draw["numbers"]]:
                str_count += 1
            else:
                break

        rec = "보통"
        if ens_exp > 1.2: rec = "필출(강력)"
        elif ens_exp > 0.7: rec = "유력"
        elif ens_exp < 0.3: rec = "제외"

        # 모델별 기대값 (정규화 후 *6)
        model_exp = {}
        if model_contributions:
            for m in models:
                nm = norm_model.get(m, {})
                model_exp[m] = round(sum(nm.get(n, 0) for n in t_nums) * 6, 2)

        tails.append({
            "tail": t,
            "exp": round(ens_exp, 2),
            "gap": gap,
            "str": str_count,
            "rec": rec,
            "model_exp": model_exp
        })
    return tails

# ------------------------------------------------------------------
# 3. 회귀 전수 조사
# ------------------------------------------------------------------
def analyze_all_regressions(history_draws, final_probs, model_contributions=None):
    """N회귀 대상번호(N회 전 당첨번호)가 이번 회차에 몇 개 출현할지 예측.
    - Gap: 해당 번호 그룹의 마지막 출현 후 연속 미출현 회차
    - STR: 가장 최근부터 연속 출현 회차
    - hit_dist: 과거 전체 이력에서 대상번호 중 실제 출현 개수 분포 {0:N, 1:N, 2:N, 3:N, 4:N, 5:N, 6:N}
    - avg_hit: 과거 평균 출현 개수
    """
    results = []

    total_draws = len(history_draws)

    for w in range(2, 201):
        if total_draws < w + 20: break  # 검증을 위한 최소 표본 확보
        
        # [수정] 현재 대상 번호(target_nums)는 '오늘' 분석을 위한 것이 아니라 
        # '이 방식(w 회귀)'이 과거에 얼마나 잘 맞았는지를 계산해야 함.
        
        hit_counts = []
        # 과거 이력을 돌며 w 전 번호가 이번에 얼마나 나왔는지 체크
        # 최신 100회차 정도만 샘플링 (성능 및 최신 트렌드 반영)
        sample_limit = min(100, total_draws - w - 1)
        for i in range(sample_limit):
            past_draw = history_draws[i + w] # 더 과거
            current_draw = history_draws[i]  # 그보다 w회 뒤 (상대적 최신)
            
            p_nums = set(past_draw.get("numbers", []))
            c_nums = set(current_draw.get("numbers", []))
            hit_counts.append(len(p_nums & c_nums))
        
        if not hit_counts: continue
        
        avg_hit = sum(hit_counts) / len(hit_counts)
        # 히스토그램 (0~6개)
        hit_dist = {i: hit_counts.count(i) for i in range(7)}
        
        # 현재(오늘) 분석을 위한 타겟: N회 전 추첨된 번호를 기반으로 함 (w-1 인덱스 사용).
        # history_draws[0]이 저번 주 당첨 번호라면, history_draws[w-1]는 정확히 w주기 전 번호가 됨.
        # 이번 주(미래) 회차에 나오기를 기대하는 "대상번호"를 산출하는 과정. 
        if total_draws > w - 1:
            target_nums = history_draws[w - 1]["numbers"]
        else:
            target_nums = []
        
        # GAP: w 주기로 연속 미출현 횟수
        gap = 0
        cur = 0 # 가장 최근부터 역순으로
        while True:
            idx = cur + w
            if idx >= total_draws: break
            # 현재(0)와 idx(w), idx와 idx+w... 간의 결합 확인
            if set(history_draws[cur]["numbers"]) & set(history_draws[idx]["numbers"]): break
            gap += 1
            cur = idx
            if gap > 50: break
            
        # STR: w 주기로 연속 출현 횟수
        str_count = 0
        cur = 0
        if set(history_draws[0]["numbers"]) & set(history_draws[w]["numbers"]):
            str_count = 1
            while True:
                idx = cur + w
                nxt = idx + w
                if nxt >= total_draws: break
                if set(history_draws[idx]["numbers"]) & set(history_draws[nxt]["numbers"]): 
                    str_count += 1
                else: break
                cur = idx
                if str_count > 50: break

        results.append({
            "id": w,
            "targets": sorted(target_nums),
            "gap": gap,
            "str": str_count,
            "avg_hit": avg_hit,
            "hit_dist": hit_dist,
            "sample_count": len(hit_counts),
        })
    return results

# ------------------------------------------------------------------
# 4-1. 로또용지 분석
# ------------------------------------------------------------------
def analyze_lotto_paper(final_probs, history_draws, model_contributions=None):
    """
    로또 용지 기준 가로/세로 라인 분석
    """
    models = ["lstm", "xgboost", "cnn", "transformer", "markov", "autoencoder", "gnn"]

    # 앙상블 확률 정규화
    ens_total = sum(final_probs.values())
    if ens_total == 0:
        norm_final = {n: 0 for n in final_probs}
    else:
        norm_final = {int(n): v / ens_total for n, v in final_probs.items()}

    # 모델별 확률 정규화
    norm_model = {}
    if model_contributions:
        for m in models:
            m_probs = model_contributions.get(m, {})
            m_total = sum(m_probs.values())
            if m_total == 0:
                norm_model[m] = {}
            else:
                norm_model[m] = {int(n): v / m_total for n, v in m_probs.items()}

    # 가로 라인 정의 (실제 로또 용지 7열 기준)
    rows = [
        {"label": "가로1", "nums": [1, 2, 3, 4, 5, 6, 7]},
        {"label": "가로2", "nums": [8, 9, 10, 11, 12, 13, 14]},
        {"label": "가로3", "nums": [15, 16, 17, 18, 19, 20, 21]},
        {"label": "가로4", "nums": [22, 23, 24, 25, 26, 27, 28]},
        {"label": "가로5", "nums": [29, 30, 31, 32, 33, 34, 35]},
        {"label": "가로6", "nums": [36, 37, 38, 39, 40, 41, 42]},
        {"label": "가로7", "nums": [43, 44, 45]},
    ]
    # 세로 라인 정의 (실제 로또 용지 7행 기준)
    cols = [
        {"label": "세로1", "nums": [1, 8, 15, 22, 29, 36, 43]},
        {"label": "세로2", "nums": [2, 9, 16, 23, 30, 37, 44]},
        {"label": "세로3", "nums": [3, 10, 17, 24, 31, 38, 45]},
        {"label": "세로4", "nums": [4, 11, 18, 25, 32, 39]},
        {"label": "세로5", "nums": [5, 12, 19, 26, 33, 40]},
        {"label": "세로6", "nums": [6, 13, 20, 27, 34, 41]},
        {"label": "세로7", "nums": [7, 14, 21, 28, 35, 42]},
    ]

    def _calc_gap(nums, draws):
        """해당 라인의 번호가 마지막 출현 이후 경과 회차 (미출현 연속 횟수)"""
        gap = 0
        for draw in draws:
            if any(n in draw.get("numbers", []) for n in nums):
                break
            gap += 1
        return gap

    def _calc_str(nums, draws):
        """해당 라인의 번호가 가장 최근 연속 출현한 횟수"""
        streak = 0
        for draw in draws:
            if any(n in draw.get("numbers", []) for n in nums):
                streak += 1
            else:
                break
        return streak

    def _build_section(items):
        result = []
        for item in items:
            nums = item["nums"]
            # 정규화 후 *6
            ens_exp = round(sum(norm_final.get(n, 0) for n in nums) * 6, 2)
            # Gap / STR
            gap = _calc_gap(nums, history_draws)
            str_count = _calc_str(nums, history_draws)
            # 모델별 기대값 (정규화 후 *6)
            model_exp = {}
            if model_contributions:
                for m in models:
                    nm = norm_model.get(m, {})
                    model_exp[m] = round(sum(nm.get(n, 0) for n in nums) * 6, 2)

            result.append({
                "label": item["label"],
                "nums": nums,
                "exp": ens_exp,
                "gap": gap,
                "str": str_count,
                "model_exp": model_exp
            })
        return result

    return {
        "rows": _build_section(rows),
        "cols": _build_section(cols)
    }


# ------------------------------------------------------------------
# 4-3. 9궁 분석 (magic_square.html gungDefinitions와 동일)
# ------------------------------------------------------------------
def analyze_magic_square(final_probs, history_draws, model_contributions=None):
    """
    9궁 분석: 45개 번호를 5개씩 9구간으로 분류 (magic_square.html 기준)
    - 1궁(1-5), 2궁(6-10), 3궁(11-15), 4궁(16-20), 5궁(21-25)
    - 6궁(26-30), 7궁(31-35), 8궁(36-40), 9궁(41-45)
    - 각 궁별 Gap(미출현 연속 횟수), STR(연속 출현 횟수), 추천도 포함
    """
    models = ["lstm", "xgboost", "cnn", "transformer", "markov", "autoencoder", "gnn"]

    # 앙상블 확률 정규화
    ens_total = sum(final_probs.values())
    if ens_total == 0:
        norm_final = {n: 0 for n in final_probs}
    else:
        norm_final = {int(n): v / ens_total for n, v in final_probs.items()}

    # 모델별 확률 정규화
    norm_model = {}
    if model_contributions:
        for m in models:
            m_probs = model_contributions.get(m, {})
            m_total = sum(m_probs.values())
            if m_total == 0:
                norm_model[m] = {}
            else:
                norm_model[m] = {int(n): v / m_total for n, v in m_probs.items()}

    # 9궁 정의 (magic_square.html gungDefinitions와 완전히 동일)
    gung_defs = [
        {"label": "1궁", "nums": [1, 2, 3, 4, 5]},
        {"label": "2궁", "nums": [6, 7, 8, 9, 10]},
        {"label": "3궁", "nums": [11, 12, 13, 14, 15]},
        {"label": "4궁", "nums": [16, 17, 18, 19, 20]},
        {"label": "5궁", "nums": [21, 22, 23, 24, 25]},
        {"label": "6궁", "nums": [26, 27, 28, 29, 30]},
        {"label": "7궁", "nums": [31, 32, 33, 34, 35]},
        {"label": "8궁", "nums": [36, 37, 38, 39, 40]},
        {"label": "9궁", "nums": [41, 42, 43, 44, 45]},
    ]

    result = []
    for gung in gung_defs:
        nums = gung["nums"]

        # 앙상블 기대값 (정규화 후 *6)
        ens_exp = round(sum(norm_final.get(n, 0) for n in nums) * 6, 2)

        # Gap: 마지막 출현 이후 연속 미출현 회차
        gap = 0
        for draw in history_draws:
            if any(n in draw.get("numbers", []) for n in nums):
                break
            gap += 1

        # STR: 가장 최근 연속 출현 횟수
        str_count = 0
        for draw in history_draws:
            if any(n in draw.get("numbers", []) for n in nums):
                str_count += 1
            else:
                break

        # 모델별 기대값
        model_exp = {}
        if model_contributions:
            for m in models:
                nm = norm_model.get(m, {})
                model_exp[m] = round(sum(nm.get(n, 0) for n in nums) * 6, 2)

        result.append({
            "label": gung["label"],
            "nums": nums,
            "exp": ens_exp,
            "gap": gap,
            "str": str_count,
            "model_exp": model_exp
        })

    return result


# ------------------------------------------------------------------
# 5. 번호대별 분석
# ------------------------------------------------------------------
def analyze_number_band(final_probs, history_draws, model_contributions=None):
    """
    번호대별(10단위 구간) 분석:
    01~10, 11~20, 21~30, 31~40, 41~45
    """
    models = ["lstm", "xgboost", "cnn", "transformer", "markov", "autoencoder", "gnn"]

    # 앙상블 확률 정규화
    ens_total = sum(final_probs.values())
    if ens_total == 0:
        norm_final = {n: 0 for n in final_probs}
    else:
        norm_final = {int(n): v / ens_total for n, v in final_probs.items()}

    # 모델별 확률 정규화
    norm_model = {}
    if model_contributions:
        for m in models:
            m_probs = model_contributions.get(m, {})
            m_total = sum(m_probs.values())
            if m_total == 0:
                norm_model[m] = {}
            else:
                norm_model[m] = {int(n): v / m_total for n, v in m_probs.items()}

    bands = [
        {"label": "01~10",  "nums": list(range(1,  11))},
        {"label": "11~20",  "nums": list(range(11, 21))},
        {"label": "21~30",  "nums": list(range(21, 31))},
        {"label": "31~40",  "nums": list(range(31, 41))},
        {"label": "41~45",  "nums": list(range(41, 46))},
    ]

    result = []
    for band in bands:
        nums = band["nums"]
        # 정규화 후 *6
        ens_exp = round(sum(norm_final.get(n, 0) for n in nums) * 6, 2)

        # Gap: 해당 구간 번호가 마지막 출현 이후 경과 회차
        gap = 0
        for draw in history_draws:
            if any(n in draw["numbers"] for n in nums): break
            gap += 1

        # STR: 가장 최근 연속 출현 횟수
        str_count = 0
        for draw in history_draws:
            if any(n in draw["numbers"] for n in nums):
                str_count += 1
            else:
                break

        # 모델별 기대값 (정규화 후 *6)
        model_exp = {}
        if model_contributions:
            for m in models:
                nm = norm_model.get(m, {})
                model_exp[m] = round(sum(nm.get(n, 0) for n in nums) * 6, 2)

        result.append({
            "label": band["label"],
            "nums": nums,
            "exp": ens_exp,
            "gap": gap,
            "str": str_count,
            "model_exp": model_exp
        })
    return result


# ------------------------------------------------------------------
# LLM 전략 분석 (v2에서 통합)
# ------------------------------------------------------------------
async def _ask_llm_strategy_v3(target_round, top_5, exclude_10, history_draws, combinations, range_analysis):
    """LLM에게 전략 분석을 요청한다."""
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        
        if not config.GOOGLE_API_KEY:
            return _fallback_strategy_v3(top_5, exclude_10)
        
        llm = ChatGoogleGenerativeAI(
            model=config.LLM_MODEL,
            google_api_key=config.GOOGLE_API_KEY,
            temperature=0.4,
        )

        recent_5 = history_draws[:5]
        recent_text = "\n".join(
            f"  {d['round']}회: {d['numbers']} (합계:{sum(d['numbers'])})"
            for d in recent_5
        )

        # 조합 텍스트 - raw 점수 대신 순위만 표시 (소수점 확률값 LLM 노출 방지)
        combo_text = "\n".join(
            f"  #{i+1}순위 조합: {c['numbers']}"
            for i, c in enumerate(combinations[:5])
        )

        # 필터 요약 - raw 수치 대신 사람이 읽기 쉬운 형식으로 변환
        FILTER_NAMES = {
            "sum": "총합", "tail_sum": "끝수합", "ac": "AC값",
            "odd": "홀짝", "high": "저고", "prime": "소수",
            "consecutive": "연속수", "composite": "합성수", "square": "제곱수",
            "triangular": "삼각수", "twin": "쌍둥이수", "mul3": "3의 배수",
            "mul4": "4의 배수", "mul5": "5의 배수", "non_multiple": "비배수",
            "hot10": "최근 10회 출현", "missing": "장기 미출현", "neighbor": "이웃수", "carryover": "이월수"
        }
        filter_summary = []
        for key, val in range_analysis.items():
            if isinstance(val, dict) and "range" in val:
                raw = val["range"]
                name = FILTER_NAMES.get(key, key)
                if isinstance(raw, list) and len(raw) == 2:
                    range_str = f"{raw[0]}~{raw[1]}"
                elif isinstance(raw, str):
                    range_str = raw
                else:
                    range_str = str(raw)
                filter_summary.append(f"- {name}: 추천범위 {range_str}")
        filter_text = "\n".join(filter_summary)

        prompt = f"""당신은 로또 번호 분석 전문가입니다.
{target_round}회차 예측을 위한 전략을 한국어로 수립하세요.

[앙상블 모델 추천 결과]
- 고정 후보 번호 (상위 5개): {top_5}
- 제외 후보 번호 (하위 10개): {exclude_10}

[최근 5회 당첨 결과]
{recent_text}

[추천 조합 후보]
{combo_text}

[통계 필터 분석]
{filter_text}

[응답 작성 규칙 - 반드시 준수]
1. 반드시 순수 한국어만 사용하세요. 영문 단어(XGBoost, LSTM, momentum, probability 등) 사용 절대 금지.
2. 소수점 확률값(예: 0.5775, 0.3421)을 절대 출력하지 마세요. 대신 "출현 가능성 높음/보통/낮음"으로 표현하세요.
3. "통계적 유의성", "앙상블 확률" 같은 학술 전문용어 사용 금지. 일반인이 쉽게 이해할 수 있는 표현만 사용하세요.
5. **반드시 아래 제공된 19개 항목의 필터를 하나도 빠짐없이 전부 분석하여 응답하세요.** 데이터가 부족하더라도 '통계 기반' 근거를 활용하여 범위를 추천해야 합니다.
6. 반드시 아래 JSON 형식으로만 응답하세요. 마크다운 없이 순수 JSON만 반환하세요.

{{
  "confidence": 72,
  "summary": "최근 출현 동향을 바탕으로 한 3~5문장의 이번 회차 전략 요약 (일반인이 이해하기 쉽게)",
  "keywords": ["#키워드1", "#키워드2", "#키워드3", "#키워드4"],
  "fixed_numbers": {{
    "numbers": [가장 유력한 고정수 3~4개],
    "evidence": "이 번호를 고정수로 추천하는 이유 (출현 주기, 미출현 기간 등 근거)"
  }},
  "exclude_numbers": {{
    "numbers": [강력 제외수 5~6개],
    "evidence": "이 번호를 제외하는 이유 (최근 과출현, 냉각 중 등 근거)"
  }},
  "filter_recommendations": [
    {"filter": "총합", "min": 100, "max": 180, "evidence": "근거"},
    {"filter": "끝수합", "min": 15, "max": 35, "evidence": "근거"},
    {"filter": "AC값", "min": 7, "max": 10, "evidence": "근거"},
    {"filter": "홀짝", "pattern": "3:3", "evidence": "근거"},
    {"filter": "저고", "pattern": "3:3", "evidence": "근거"},
    {"filter": "소수", "min": 1, "max": 3, "evidence": "근거"},
    {"filter": "합성수", "min": 2, "max": 4, "evidence": "근거"},
    {"filter": "제곱수", "min": 0, "max": 1, "evidence": "근거"},
    {"filter": "삼각수", "min": 0, "max": 2, "evidence": "근거"},
    {"filter": "쌍둥이수", "min": 0, "max": 1, "evidence": "근거"},
    {"filter": "연속수", "min": 0, "max": 1, "evidence": "근거"},
    {"filter": "3의 배수", "min": 1, "max": 3, "evidence": "근거"},
    {"filter": "4의 배수", "min": 0, "max": 2, "evidence": "근거"},
    {"filter": "5의 배수", "min": 0, "max": 2, "evidence": "근거"},
    {"filter": "비배수", "min": 1, "max": 3, "evidence": "근거"},
    {"filter": "최근 10회 출현", "min": 3, "max": 5, "evidence": "근거"},
    {"filter": "장기 미출현", "min": 0, "max": 2, "evidence": "근거"},
    {"filter": "이웃수", "min": 1, "max": 3, "evidence": "근거"},
    {"filter": "이월수", "min": 0, "max": 1, "evidence": "근거"}
  ],
  "hot_cold_analysis": {
    "hot_ratio": 60,
    "cold_ratio": 40,
    "trend_text": "최근 번호 강세 예상 또는 미출현 번호 회귀 분석 결과"
  },
  "risk_assessment": {
    "risk_score": 75,
    "risk_level": "위험/주의/안정",
    "warning_text": "연속수/이월수 등 패턴 쏠림 주의사항 1문장"
  },
  "overall_strategy": {
    "key_actions": ["핵심필터1", "핵심필터2"],
    "short_advice": "이번 회차 최종 한줄 조언"
  }
}}"""

        result = await llm.ainvoke(prompt)
        content = result.content

        json_match = re.search(r"\{[\s\S]*\}", content)
        if json_match:
            parsed = json.loads(json_match.group(0))
            if "fixed_numbers" in parsed and isinstance(parsed["fixed_numbers"], list):
                parsed["fixed_numbers"] = {"numbers": parsed["fixed_numbers"], "evidence":"LLM 분석 기반 추천"}
            if "exclude_numbers" in parsed and isinstance(parsed["exclude_numbers"], list):
                parsed["exclude_numbers"] = {"numbers": parsed["exclude_numbers"], "evidence": "LLM 분석 기반 제외"}
            return parsed
        else:
            return _fallback_strategy_v3(top_5, exclude_10)

    except Exception as e:
        print(f"LLM 전략 분석 실패: {e}")
        return _fallback_strategy_v3(top_5, exclude_10)


def _fallback_strategy_v3(top_5: list, exclude_10: list) -> dict:
    """LLM 실패 시 폴백 전략."""
    return {
        "confidence": 55,
        "summary": "LLM 미사용 - 5중 앙상블 딥러닝 모델(Transformer, LSTM, CNN, XGBoost, Markov)의 분석 결과입니다.",
        "keywords": ["#모델분석전용", "#통계기반", "#앙상블예측"],
        "fixed_numbers": {"numbers": top_5[:4], "evidence": "앙상블 모델 상위 확률 기반 (LLM 미사용)"},
        "exclude_numbers": {"numbers": exclude_10[:6], "evidence": "앙상블 모델 하위 확률 기반 (LLM 미사용)"},
        "filter_recommendations": [
            {"filter": "총합", "min": 100, "max": 180, "evidence": "통계적 1표준편차 범위"},
            {"filter": "끝수합", "min": 15, "max": 35, "evidence": "역대 평균 기반"},
            {"filter": "AC값", "min": 7, "max": 10, "evidence": "역대 평균 기반"},
            {"filter": "홀짝", "pattern": "3:3 또는 4:2", "evidence": "최빈 패턴"},
            {"filter": "저고", "pattern": "3:3", "evidence": "균형 분포"},
            {"filter": "소수", "min": 1, "max": 3, "evidence": "평균 출현 기대치"},
            {"filter": "합성수", "min": 2, "max": 4, "evidence": "확률적 최빈 구간"},
            {"filter": "제곱수", "min": 0, "max": 1, "evidence": "자연 발생 확률"},
            {"filter": "삼각수", "min": 0, "max": 2, "evidence": "일반적 패턴 확률"},
            {"filter": "쌍둥이수", "min": 0, "max": 1, "evidence": "일반적 패턴 확률"},
            {"filter": "연속수", "min": 0, "max": 1, "evidence": "자주 관측되는 구간"},
            {"filter": "최근 10회 출현", "min": 3, "max": 4, "evidence": "모멘텀 회귀 구간"},
            {"filter": "장기 미출현", "min": 0, "max": 1, "evidence": "콜드 번호 출현 확률"},
            {"filter": "3의 배수", "min": 1, "max": 2, "evidence": "균등 분포 1/3 할당"},
            {"filter": "4의 배수", "min": 0, "max": 2, "evidence": "통계 기반 할당"},
            {"filter": "5의 배수", "min": 0, "max": 2, "evidence": "통계 기반 할당"},
            {"filter": "비배수", "min": 1, "max": 3, "evidence": "확률적 할당"},
            {"filter": "이웃수", "min": 1, "max": 2, "evidence": "회귀 분석 기반 평균"},
            {"filter": "이월수", "min": 0, "max": 1, "evidence": "최근 5회 이월비율 고려"}
        ],
        "hot_cold_analysis": {
            "hot_ratio": 50,
            "cold_ratio": 50,
            "trend_text": "균형적인 흐름 예상"
        },
        "risk_assessment": {
            "risk_score": 30,
            "risk_level": "안정",
            "warning_text": "특이 패턴 출현 확률 낮음"
        },
        "overall_strategy": {
            "key_actions": [
                "통계적 평균치 수렴",
                "골고루 분산 투자"
            ],
            "short_advice": "기속 필터 위주의 안정적 조합 권장"
        }
    }


# ------------------------------------------------------------------
# 이력 저장 (v2에서 통합)
# ------------------------------------------------------------------
def _save_analysis_history(target_round: int, result: dict):
    """분석 결과를 Supabase deep_analysis_history 테이블에 저장."""
    try:
        client = get_client()
        strategy = result.get("strategy", {})

        row = {
            "target_round": target_round,
            "confidence": strategy.get("confidence", 0),
            "summary": (strategy.get("summary", ""))[:500],
            "analysis_data": json.dumps(result, cls=NumpyEncoder, ensure_ascii=False),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        client.table("deep_analysis_history").insert(row).execute()
        print(f"[OK] 분석 이력 저장 완료: {target_round}회차")
    except Exception as e:
        print(f"이력 저장 실패 (무시): {e}")


# ------------------------------------------------------------------
# 미출현 그룹 분석
# ------------------------------------------------------------------
def analyze_missing_group(target_round: int, final_probs: dict, history_draws: list) -> dict:
    """number_features_by_round에서 missing_count를 가져와 4개 구간으로 분류."""

    # Supabase에서 missing_count 조회
    missing_counts = fetch_missing_counts(target_round)

    # DB 조회 실패 시 history_draws로 직접 계산 (fallback)
    if not missing_counts:
        for n in range(1, 46):
            gap = 0
            for d in history_draws:
                if n in d.get("numbers", []):
                    break
                gap += 1
            missing_counts[n] = gap

    def get_group(mc: int) -> int:
        if mc <= 5:  return 1
        if mc <= 10: return 2
        if mc <= 15: return 3
        return 4

    GROUP_LABELS = {
        1: {"label": "1~5회 (최근)", "range": "1~5회", "color": "#ef4444"},
        2: {"label": "6~10회 (중기)", "range": "6~10회", "color": "#f97316"},
        3: {"label": "11~15회 (장기)", "range": "11~15회", "color": "#3b82f6"},
        4: {"label": "16회+ (극장기)", "range": "16회+", "color": "#94a3b8"},
    }

    # 총 앙상블 확률 합산
    total_prob = sum(final_probs.values()) or 1.0

    groups = {g: {"label": GROUP_LABELS[g]["label"], "range": GROUP_LABELS[g]["range"],
                  "color": GROUP_LABELS[g]["color"], "numbers": [], "count": 0,
                  "avg_prob": 0.0, "top_count": 0} for g in range(1, 5)}

    # top_15 집합 (상위 15개 번호)
    sorted_probs = sorted(final_probs.items(), key=lambda x: x[1], reverse=True)
    top_15 = {n for n, _ in sorted_probs[:15]}

    for n in range(1, 46):
        mc = missing_counts.get(n, 0)
        g = get_group(mc)
        prob_pct = round(final_probs.get(n, 0) / total_prob * 100, 2)
        groups[g]["numbers"].append({
            "num": n,
            "missing_count": mc,
            "prob": prob_pct,
            "is_top15": n in top_15,
        })

    for g in range(1, 5):
        nums = groups[g]["numbers"]
        groups[g]["count"] = len(nums)
        groups[g]["top_count"] = sum(1 for x in nums if x["is_top15"])
        groups[g]["avg_prob"] = round(sum(x["prob"] for x in nums) / len(nums), 3) if nums else 0
        # 확률 높은 순 정렬
        groups[g]["numbers"].sort(key=lambda x: x["prob"], reverse=True)

    return {"groups": groups, "missing_counts": {str(k): v for k, v in missing_counts.items()}}


# ------------------------------------------------------------------
# 6. 이력 조회 (v2에서 통합)
# ------------------------------------------------------------------
@router.get("/history")
async def get_history():
    """저장된 분석 이력 목록 조회."""
    try:
        client = get_client()
        result = (
            client.table("deep_analysis_history")
            .select("id, target_round, created_at, confidence, summary")
            .order("created_at", desc=True)
            .limit(30)
            .execute()
        )
        return _json_response({"success": True, "history": result.data or []})
    except Exception as e:
        print(f"이력 조회 실패: {e}")
        return _json_response({"success": True, "history": []})


@router.get("/history/{history_id}")
async def get_history_detail(history_id: int):
    """특정 이력의 상세 데이터 조회."""
    try:
        client = get_client()
        result = (
            client.table("deep_analysis_history")
            .select("*")
            .eq("id", history_id)
            .single()
            .execute()
        )
        if result.data:
            return _json_response({"success": True, "data": result.data})
        return _json_response({"success": False, "error": "이력을 찾을 수 없습니다"})
    except Exception as e:
        return _json_response({"success": False, "error": str(e)})


# ------------------------------------------------------------------
# Main API
# ------------------------------------------------------------------
@router.get("/analysis")
async def get_deep_analysis(round_num: int = None):
    start_time = time.time()
    client = get_client() # [Fix] Define client for DB operations
    
    try:
        all_draws = fetch_all_draws()
        if not all_draws: return _json_response({"success": False})

        target_round = int(round_num) if round_num else (all_draws[0]["round"] + 1)
        history_draws = [d for d in all_draws if d["round"] < target_round]
        
        # [추가] 전문가 메모(Expert Memo) 가져오기 및 파싱
        human_rules = None
        expert_memo_data = None
        try:
            # [추가] 전문가 메모(Expert Memo) 가령: 모든 메모를 합쳐서 분석
            memo_res = client.table("user_checkpoints")\
                .select("*")\
                .eq("round", target_round)\
                .order("created_at", desc=False)\
                .execute()
            
            if memo_res.data:
                # 모든 메모 텍스트 합치기
                all_memo_texts = [row.get("memo", "") for row in memo_res.data if row.get("memo")]
                memo_text = "\n".join(all_memo_texts)
                expert_memo_data = {"memo": memo_text} # [Fix] 모든 메모가 합쳐진 텍스트를 저장
                
                if memo_text.strip():
                    print(f"[{target_round}회] 전문가 메모({len(all_memo_texts)}개) 합산 분석 시작...")
                    human_rules = parse_expert_memo(memo_text)
                    print(f"-> 파싱된 통합 규칙: {human_rules}")
        except Exception as e:
            print(f"전문가 메모 로드 실패: {e}")

        # 모델 실행
        ensemble = LottoEnsemble()
        try: 
            prediction = ensemble.predict(history_draws, human_rules=human_rules)
        except Exception as e:
            print(f"예측 오류: {e}")
            traceback.print_exc()
            prediction = {"probabilities": {}, "model_contributions": {}}
        
        final_probs = prediction.get("probabilities", {})
        contribs = prediction.get("model_contributions", {})
        # 전문가 메모 파싱 완료
        current_memo_raw = expert_memo_data.get("memo") if expert_memo_data else None

        try:
            # [CACHE BYPASS] 디버깅을 위해 캐시를 완전히 무시하고 항상 새로 계산합니다.
            pass
        except Exception as e:
            if str(e) not in ["stale_cache_detected", "memo_changed"]:
                print(f"캐시 체크 실패 (정상 분석 진행): {e}")

        models = ["lstm", "xgboost", "cnn", "transformer", "markov", "autoencoder", "gnn"]

        # Streak 계산
        streak_count = {n: 0 for n in range(1, 46)}
        for n in range(1, 46):
            current_streak = 0
            for d in history_draws:
                if n in d["numbers"]:
                    current_streak += 1
                else:
                    break
            streak_count[n] = current_streak

        # [0] 과출현 패널티 + Gap 주기 보정 계수 계산
        stat_corrections = calc_stat_correction(history_draws, final_probs)

        # 보정된 확률 생성 (원본 final_probs × adj_factor 후 재정규화)
        corrected_probs = {}
        for n in range(1, 46):
            orig = final_probs.get(n, 0)
            adj = stat_corrections[n]["adj_factor"]
            corrected_probs[n] = orig * adj
        # 재정규화
        total_cp = sum(corrected_probs.values())
        if total_cp > 0:
            corrected_probs = {n: v / total_cp for n, v in corrected_probs.items()}

        # [1] 기초분석
        range_analysis_simple, filter_settings = simulate_all_filters(corrected_probs, history_draws)
        range_analysis = {}
        for filter_key, filter_value in range_analysis_simple.items():
            model_expectations = get_model_filter_expectations(filter_key, history_draws, contribs)
            range_analysis[filter_key] = {
                "range": filter_value,
                "model_expectations": model_expectations if model_expectations else {}
            }
        
        # [2] 커스텀분석 (ai_custom_analyses 테이블 기반 배치 처리)
        try:
            client = get_client()
            res = client.table("ai_custom_analyses").select("id,title,type,target_numbers,rules").execute()
            custom_analyses = res.data or []
            print(f"[custom] ai_custom_analyses 조회 완료: {len(custom_analyses)}개")
        except Exception as e:
            print(f"[custom] ai_custom_analyses 조회 실패: {e}")
            custom_analyses = []

        # 최신 회차(draws[0]) 기준으로 각 분석의 현재 대상번호 계산
        latest_draw = history_draws[0] if history_draws else None
        prev_draw = history_draws[1] if len(history_draws) > 1 else None

        def calc_custom_targets(analysis, latest, prev):
            """커스텀분석의 현재 회차 대상번호를 JS 로직과 동일하게 계산"""
            a_type = analysis.get("type", "static")
            rules = analysis.get("rules") or {}
            formula = rules.get("formula", "prev_plus_n")
            val = rules.get("value", 1)
            try: val = int(val)
            except: val = 1
            global_targets = analysis.get("target_numbers") or []

            if a_type == "static":
                return [int(n) for n in global_targets if 1 <= int(n) <= 45]

            elif a_type == "dynamic":
                if formula in ("draw_date_end", "draw_date_math", "round_end_digit"):
                    if formula == "round_end_digit":
                        # [New] 회차 번호 끝수 기준 (예: 1103회 -> 3끝수)
                        digit = target_round % 10
                        start = 10 if digit == 0 else digit
                        return list(range(start, 46, 10))
                    
                    # 날짜 기반 - 최신 당첨일 기준
                    if not latest: return []
                    date_str = latest.get("date", "")
                    if not date_str: return []
                    try:
                        from datetime import datetime
                        d = datetime.fromisoformat(date_str[:10])
                        day = d.day
                        if formula == "draw_date_end":
                            digit = day % 10
                            start = 10 if digit == 0 else digit
                            return list(range(start, 46, 10))
                        else:
                            return []  # draw_date_math는 복잡하므로 스킵
                    except:
                        return []

                # regression_step 처리
                step = int(rules.get("regression_step", 0))
                if step > 0:
                    if step < len(history_draws):
                        base = history_draws[step]
                        return [int(n) for n in base.get("numbers", []) if 1 <= int(n) <= 45]
                    return []

                # 전회차 기반 (prev_plus_n / prev_minus_n / carryover)
                base_nums = latest.get("numbers", []) if latest else []
                if not base_nums: return []
                base_nums = [int(n) for n in base_nums]

                if formula == "carryover":
                    targets = base_nums[:]
                elif formula in ("prev_plus_n", "prev_minus_n"):
                    targets = []
                    for n in base_nums:
                        nxt = (n + val) if formula == "prev_plus_n" else (n - val)
                        while nxt > 45: nxt -= 45
                        while nxt < 1: nxt += 45
                        targets.append(nxt)
                else:
                    targets = base_nums[:]

                return sorted(set(t for t in targets if 1 <= t <= 45))

            elif a_type == "manual":
                # 매뉴얼: target_numbers 사용
                return [int(n) for n in global_targets if 1 <= int(n) <= 45]

            elif a_type == "group":
                # 그룹: target_numbers 사용 (config 컬럼 미포함)
                return [int(n) for n in global_targets if global_targets and 1 <= int(n) <= 45]

            return [int(n) for n in global_targets if global_targets and 1 <= int(n) <= 45]

        def score_for_nums(nums):
            """번호 목록에 대한 모델 점수, 과거적중분포, avg_hit, GAP/STR 계산"""
            if not nums:
                return {}, 0, 0, 0, 0, {}

            nums_set = set(nums)

            # GAP/STR 계산 (최신 이력 기준, 대상번호 중 1개 이상 출현 여부)
            gap = 0
            streak = 0
            for i, draw in enumerate(history_draws[:100]):
                draw_nums = set(draw.get("numbers", []))
                hit = bool(nums_set & draw_nums)
                if i == 0:
                    if not hit: gap = 1
                    else: streak = 1
                else:
                    if not hit and gap > 0: gap += 1
                    elif not hit and streak > 0: gap = 1; streak = 0
                    elif hit and streak > 0: streak += 1
                    elif hit and gap > 0: streak = 1; gap = 0
                    if gap == 0 and streak == 0: break

            # 과거 적중 분포 + avg_hit (전체 이력 기준)
            hit_dist = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0}
            hit_total = 0
            sample_count_hit = 0
            try:
                for draw in history_draws:
                    actual = set(draw.get("numbers", []))
                    h = len(nums_set & actual)
                    hit_dist[min(h, 6)] = hit_dist.get(min(h, 6), 0) + 1
                    hit_total += h
                    sample_count_hit += 1
                avg_hit = round(hit_total / sample_count_hit, 2) if sample_count_hit > 0 else 0
            except Exception as e:
                print(f"ANTIGRAVITY ERROR in score_for_nums (stats): {e}")
                avg_hit = 0

            # 모델별 점수 (백분위 기반 — 해당 번호들이 각 모델에서 얼마나 상위권인지)
            model_scores = {}
            for m in models:
                m_contrib = contribs.get(m, {})
                # [Fix] 모델 결과가 없어도 0점으로 초기화하여 항상 반환 보장
                if not m_contrib:
                    model_scores[m] = {"score": 0, "reasoning": "모델 데이터 없음"}
                    continue

                all_vals = sorted(m_contrib.values(), reverse=True)
                total_cnt = len(all_vals)

                # 균등 분포 감지: 모든 확률이 동일하면 모델이 번호를 구분 못함 → 50점(중립)
                val_range = (all_vals[0] - all_vals[-1]) if all_vals else 0
                if val_range < 1e-9:
                    if all_vals and all_vals[0] == 0.0:
                        model_scores[m] = {"score": 0, "reasoning": "점수 계산 실패 (모든 값 0.0)"}
                    else:
                        model_scores[m] = {"score": 50, "reasoning": "모델 예측 분산 미미 (균등 분포 — 참고용)"}
                    continue

                m_scores_for_nums = []
                for n in nums:
                    v = m_contrib.get(n, 0)
                    # 동점자 처리: 자신보다 높은 값을 가진 개수 확인
                    higher_cnt = sum(1 for x in all_vals if x > v)
                    # 백분위 계산 (0~95, 균등분포 방지용 상한)
                    percentile = min((total_cnt - higher_cnt) / max(total_cnt, 1) * 100, 95)
                    m_scores_for_nums.append(percentile)

                m_avg = sum(m_scores_for_nums) / len(m_scores_for_nums) if m_scores_for_nums else 0

                # 원점수(확률값) 평균도 참고하여 가중치 부여 (만약 확률이 너무 낮으면 점수 하락)
                avg_prob = sum(m_contrib.get(n, 0) for n in nums) / len(nums) if nums else 0
                baseline = sum(m_contrib.values()) / max(len(m_contrib), 1)

                final_score = m_avg
                if avg_prob < baseline * 0.5: # 평균 이하 확률이면 감점
                    final_score *= 0.5

                model_scores[m] = {
                    "score": int(max(0, min(100, final_score))),
                    "reasoning": f"모델 상위 {int(m_avg)}% (상대확률 {avg_prob/max(baseline, 0.001):.1f}배)"
                }

            return model_scores, gap, streak, avg_hit, sample_count_hit, hit_dist

        custom_evaluations = []
        for analysis in custom_analyses:
            try:
                nums = calc_custom_targets(analysis, latest_draw, prev_draw)
                print(f"[custom] {analysis.get('title')} -> nums={nums}")
                if not nums:
                    continue
            except Exception as e:
                print(f"ANTIGRAVITY ERROR in calc_custom_targets: {e}")
                nums = []
                continue

            try:
                res = score_for_nums(nums)
                model_scores, gap, streak, avg_hit, sample_count_hit, hit_dist = res
            except Exception as e:
                print(f"ANTIGRAVITY ERROR during score_for_nums call: {e}")
                traceback.print_exc()
                model_scores, gap, streak, avg_hit, sample_count_hit, hit_dist = {}, 0, 0, 0, 0, {}

            custom_evaluations.append({
                "id": analysis.get("id"),
                "title": analysis.get("title", ""),
                "type": analysis.get("type", "static"),
                "targets": nums, # Changed from 'numbers' to match frontend if needed, but 'target_numbers' was used before. Let's keep consistency.
                "avg_hit": avg_hit,
                "hit_dist": hit_dist,
                "sample_count": sample_count_hit,
                "gap": gap,
                "str": streak,
                "model_scores": model_scores,
            })

        # [3] 회귀분석
        regression_analysis = analyze_all_regressions(history_draws, final_probs, model_contributions=contribs)
        
        # [4] 끝수분석 (STR + 모델별 기대값 포함)
        tail_analysis = analyze_tail_detailed(final_probs, history_draws, model_contributions=contribs)

        # [4-1] 로또용지 분석
        lotto_paper_analysis = analyze_lotto_paper(final_probs, history_draws, model_contributions=contribs)

        # [4-2] 번호대별 분석
        number_band_analysis = analyze_number_band(final_probs, history_draws, model_contributions=contribs)

        # [4-3] 9궁 분석
        magic_square_analysis = analyze_magic_square(final_probs, history_draws, model_contributions=contribs)

        # [4-4] 핫/콜드 분석 (모델별 포함)
        hot_cold_data = analyze_hot_cold(final_probs, history_draws, contribs)
        missing_group_data = analyze_missing_group(target_round, final_probs, history_draws)

        # [5] 번호별 분석 (Matrix)
        model_all_probs = {}
        model_is_flat = {}  # 균등 분포(분산 없음) 감지
        for m in models:
            probs = [(n, contribs.get(m, {}).get(n, 0)) for n in range(1, 46)]
            vals = [p for _, p in probs]
            val_range = max(vals) - min(vals) if vals else 0
            model_is_flat[m] = val_range < 1e-9  # 모든 확률이 동일하면 flat
            probs.sort(key=lambda x: x[1], reverse=True)
            model_all_probs[m] = {num: (idx, prob) for idx, (num, prob) in enumerate(probs)}

        matrix_data = []
        for n in range(1, 46):
            m_scores = {}
            total_model_score = 0
            for m in models:
                if model_is_flat.get(m, False):
                    # 균등 분포 → 모든 번호에 동일 점수 (인위적 순위 방지)
                    norm_score = 50
                elif n in model_all_probs[m]:
                    rank, raw_prob = model_all_probs[m][n]
                    percentile_score = max(0, (45 - rank) / 45 * 100)
                    norm_score = percentile_score
                else:
                    norm_score = 0
                m_scores[m] = int(norm_score)
                total_model_score += norm_score

            gap = stat_corrections[n]["current_gap"]

            if history_draws and len(history_draws) > 0:
                freq = sum(1 for d in history_draws[-50:] if n in d["numbers"]) / min(50, len(history_draws))
            else:
                freq = 0.0

            model_reasons = get_number_model_reasons(n, streak_count[n], gap, freq, history_draws)

            m_details = {}
            for m in models:
                m_details[m] = {"score": m_scores[m], "reason": model_reasons.get(m, "분석 진행 중")}

            freq_rounded = float(round(freq, 2)) if freq is not None else 0.0
            sc = stat_corrections[n]

            # 보정 score 표시: 기본 모델들의 평균 점수를 근간으로 하되 adj_factor 적용
            avg_model_score = total_model_score / len(models) if models else 0
            
            # 최종 점수는 평균 점수를 1000배 스케일링하여 정규화한 뒤, 보정치를 반영
            raw_score = float(round(avg_model_score * 1000, 2))
            corrected_score = float(round(avg_model_score * 1000 * sc["adj_factor"], 2))
            
            # 전문가 메모의 제외수 반영 (하드 필터링)
            excluded_via_memo = False
            if human_rules and "excluded_numbers" in human_rules:
                memo_excluded_list = [int(x) for x in human_rules.get("excluded_numbers", []) if str(x).isdigit()]
                if n in memo_excluded_list:
                    excluded_via_memo = True
                    corrected_score = 0.0
                    print(f"🚫 [Memo Filter] {n}번 제외 (전문가 메모 반영)")

            matrix_data.append({
                "num": n,
                "total": corrected_score,           # 보정 후 점수
                "raw_total": raw_score,             # 원본 점수
                "memo_excluded": excluded_via_memo, # 메모에 의한 제외 여부
                "models": m_details,
                "gap": gap,
                "hot": streak_count[n],
                "freq": freq_rounded,
                # 보정 정보
                "over_ratio": sc["over_ratio"],
                "penalty": sc["penalty"],
                "gap_ratio": sc["gap_ratio"],
                "boost": sc["boost"],
                "adj_factor": sc["adj_factor"],
                "personal_avg_gap": sc["personal_avg_gap"],
            })
            
        matrix_data.sort(key=lambda x: x["total"], reverse=True)
        # 상위 5개 추출 (단, 제외된 번호(점수 0)는 절대 포함하지 않음)
        top_5 = [x["num"] for x in matrix_data if x["total"] > 0][:5]
        
        # 만약 모델 점수가 다 0이라서 top_5가 비어버린다면?
        if not top_5:
            # 제외되지 않은 번호 중 앞선 순서대로 5개 추천
            remaining_nums = [x["num"] for x in matrix_data if not x.get("memo_excluded")]
            top_5 = remaining_nums[:5]

        exclude_10 = [x["num"] for x in matrix_data[-10:]]

        # [6] 조합 (10게임) - corrected_probs 기반
        gen_probs = corrected_probs.copy()
        for n in exclude_10: gen_probs[n] = 0
        pred_obj = prediction.copy()
        pred_obj["probabilities"] = gen_probs
        combinations = CombinationGenerator.generate(pred_obj, filter_settings=filter_settings, n_combinations=10)

        # [9] LLM 전략 분석 (신규 통합)
        strategy = await _ask_llm_strategy_v3(
            target_round, top_5, exclude_10, 
            history_draws, combinations, range_analysis
        )

        # [NEW] LLM이 누락한 필터 강제 병합 및 특수 분석 결과 통합
        FILTER_NAMES_KO = {
            "sum": "총합", "tail_sum": "끝수합", "ac": "AC값",
            "odd": "홀짝비율", "high": "저고비율", "prime": "소수",
            "composite": "합성수", "consecutive": "연속수", "square": "제곱수",
            "triangular": "삼각수", "twin": "동형수", "mul3": "3의 배수", # [수정] 쌍둥이수 -> 동형수
            "mul4": "4의 배수", "mul5": "5의 배수", "non_multiple": "배수외", # [수정] 비배수 -> 배수외
            "hot10": "최근 10회 출현", "missing": "장기 미출현", 
            "neighbor": "이웃수", "carryover": "이월수"
        }
        
        if "filter_recommendations" not in strategy:
            strategy["filter_recommendations"] = []
            
        existing_filters = {str(f.get("filter", "")).replace(" ", "") for f in strategy["filter_recommendations"]}
        
        # 1. 일반 수치형 필터 추가
        for key, name in FILTER_NAMES_KO.items():
            alt_name = name.replace("비율", "")
            if name.replace(" ", "") not in existing_filters and alt_name.replace(" ", "") not in existing_filters:
                if key in range_analysis:
                    val = range_analysis[key].get("range")
                    rec = {"filter": name, "evidence": "앙상블 시뮬레이션 기반 자동 추천"}
                    if isinstance(val, list) and len(val) == 2:
                        rec["min"] = val[0]
                        rec["max"] = val[1]
                    elif isinstance(val, str) and "~" in val:
                        parts = val.split("~")
                        try:
                            rec["min"] = int(parts[0])
                            rec["max"] = int(parts[1])
                        except:
                            rec["pattern"] = val
                    else:
                        rec["pattern"] = str(val)
                    strategy["filter_recommendations"].append(rec)

        # 2. [신규] 복합 분석 필터 추가 (핫콜드, 미출현, 번호대, 9궁, 용지)
        
        # (1) 핫/콜드: 가장 번호가 많은 구간 추천
        try:
            if hot_cold_data:
                # hot/cold 중 가장 카운트가 높은 상태 찾기
                top_status = max(hot_cold_data.items(), key=lambda x: x[1].get('count', 0))
                status_key = top_status[0] # hot, cold 등
                status_label = {"hot": "Hot(최근)", "active": "Active(활성)", "cooling": "Cooling(보통)", "cold": "Cold(장기)", "deadcold": "Dead(초장기)"}.get(status_key, status_key)
                count = top_status[1].get('count', 0)
                strategy["filter_recommendations"].append({
                    "filter": "핫콜드",
                    "pattern": f"{status_label} 강세",
                    "evidence": f"해당 구간에 {count}개 번호 집중 분포"
                })
        except: pass

        # (2) 미출현 그룹: 가장 확률 높은 그룹 추천
        try:
            if missing_group_data and "groups" in missing_group_data:
                groups = missing_group_data["groups"]
                # avg_prob가 가장 높은 그룹 찾기
                top_grp_key = max(groups.keys(), key=lambda k: groups[k].get('avg_prob', 0))
                top_grp = groups[top_grp_key]
                strategy["filter_recommendations"].append({
                    "filter": "미출현그룹",
                    "pattern": f"{top_grp['label']} 구간",
                    "evidence": f"평균 당첨확률 {top_grp['avg_prob']}%로 최대 기대"
                })
        except: pass

        # (3) 번호대별: 앙상블 기대값(exp)이 가장 높은 구간
        try:
            if number_band_analysis:
                top_band = max(number_band_analysis, key=lambda x: x.get('exp', 0))
                strategy["filter_recommendations"].append({
                    "filter": "번호대별",
                    "pattern": f"{top_band['label']} 집중",
                    "evidence": f"앙상블 기대 출현값 {top_band['exp']}개로 최대"
                })
        except: pass

        # (4) 9궁 분석: 기대값(exp) 높은 상위 2개 궁
        try:
            if magic_square_analysis:
                sorted_gung = sorted(magic_square_analysis, key=lambda x: x.get('exp', 0), reverse=True)
                top_gungs = [g['label'] for g in sorted_gung[:2]]
                strategy["filter_recommendations"].append({
                    "filter": "9궁분석",
                    "pattern": ", ".join(top_gungs),
                    "evidence": "모델 예측 밀도 상위 구간"
                })
        except: pass

        # (5) 로또용지: 가로/세로 중 가장 강한 라인 1개씩
        try:
            if lotto_paper_analysis:
                rows = lotto_paper_analysis.get('rows', [])
                cols = lotto_paper_analysis.get('cols', [])
                if rows and cols:
                    top_row = max(rows, key=lambda x: x.get('exp', 0))
                    top_col = max(cols, key=lambda x: x.get('exp', 0))
                    strategy["filter_recommendations"].append({
                        "filter": "로또용지",
                        "pattern": f"{top_row['label']}, {top_col['label']}",
                        "evidence": "가로/세로 라인별 출현 기대값 분석"
                    })
        except: pass

        elapsed = round(time.time() - start_time, 2)

        # JS renderPipelineInfo()가 읽는 pipeline 객체 구성
        _evidence = prediction.get("evidence", {})
        _model_weights = _evidence.get("model_weights", {})
        pipeline_obj = {
            "modelWeights": _model_weights,
            "weightReasons": "딥러닝 7중 앙상블 (LSTM·XGBoost·CNN·Transformer·Markov·AE·GNN) 파인튜닝 완료",
            "rlGenerated": True,
            "topCompatiblePairs": []
        }

        result = {
            "success": True,
            "target_round": target_round,
            "elapsed_seconds": elapsed,
            "top_5": top_5,
            "exclude_10": exclude_10,
            "combinations": combinations,
            "strategy": strategy,  # LLM 전략
            "evidence": _evidence,  # XAI 근거 데이터
            "pipeline": pipeline_obj,  # JS status탭 모델 컨디션 바용
            "expert_memo": {
                "raw": expert_memo_data.get("memo") if expert_memo_data else None,
                "parsed": human_rules
            },
            # 통계 데이터들을 "analysis" 객체 안으로 모두 집어넣습니다!
            "analysis": {
                "matrix_data": matrix_data,
                "range_analysis": range_analysis,
                "custom_evaluations": custom_evaluations,
                "tail_analysis": tail_analysis,
                "lotto_paper_analysis": lotto_paper_analysis,
                "magic_square_analysis": magic_square_analysis,
                "number_band_analysis": number_band_analysis,
                "hot_cold_data": hot_cold_data,
                "missing_group_data": missing_group_data,
                "regression_analysis": regression_analysis,
            }
        }

        # [10] 이력 저장 (비동기, 실패해도 무시)
        try:
            _save_analysis_history(target_round, result)
        except Exception as e:
            print(f"이력 저장 실패 (무시): {e}")

        return _json_response(result)

    except Exception as e:
        traceback.print_exc()
        return _json_response({"success": False, "error": str(e)})
