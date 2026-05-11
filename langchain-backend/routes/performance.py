from fastapi import APIRouter
from typing import List, Dict, Any
from db.supabase_client import get_client

router = APIRouter(
    prefix="/api/performance",
    tags=["Performance"]
)

# ──────────────────────────────────────────────────────────────────────
# [P2 PATCH] 11-base 정합 fallback 가중치
# 근거: Lotto_lab_Root_Cause_Diagnosis.md (Finding #4)
# 패치 일자: 2026-05-11
#
# 변경 이유:
#   - 기존 fallback (lstm/xgboost/markov 3개)에서
#     LSTM이 deprecated 됐는데 35% 비중 유지 (stage-0에서 archive 처리됨)
#   - 11-base 중 8개 모델이 fallback에 누락
#
# 변경 후:
#   - 11-base 11개 모델 전체 포함
#   - LSTM, Transformer 제외 (deprecated, saved_models/_archive/)
#   - 합 = 1.0 정규화 (import 시점 assert 검증)
# ──────────────────────────────────────────────────────────────────────
DEFAULT_WEIGHTS: Dict[str, float] = {
    "xgboost":     0.15,
    "catboost":    0.12,
    "tabnet":      0.08,
    "cnn":         0.10,
    "gnn":         0.13,
    "markov":      0.09,
    "autoencoder": 0.05,
    "tft":         0.15,
    "mhn":         0.05,
    "bayesian_nn": 0.05,
    "nbeats":      0.03,
}
assert abs(sum(DEFAULT_WEIGHTS.values()) - 1.0) < 0.001, \
    f"DEFAULT_WEIGHTS sum != 1.0: {sum(DEFAULT_WEIGHTS.values())}"


@router.get("/summary")
async def get_performance_summary():
    """모델별 평균 적중률 요약."""
    supabase = get_client()

    # 최근 20회차 데이터 기준 성능 평균 계산 (DB 함수 대신 파이썬에서 집계)
    response = supabase.table("model_performance_log")\
        .select("model_name, hit_count, round")\
        .order("round", desc=True)\
        .limit(100)\
        .execute()

    data = response.data
    summary = {}

    for row in data:
        model = row['model_name']
        if model not in summary:
            summary[model] = {'total_hits': 0, 'count': 0, 'rounds': []}

        summary[model]['total_hits'] += row['hit_count']
        summary[model]['count'] += 1
        summary[model]['rounds'].append(row['round'])

    result = []
    for model, stats in summary.items():
        avg_hit = stats['total_hits'] / stats['count'] if stats['count'] > 0 else 0
        result.append({
            "model_name": model,
            "avg_hit": round(avg_hit, 2),
            "sample_size": stats['count'],
            "last_round": max(stats['rounds']) if stats['rounds'] else 0
        })

    return result


@router.get("/weights")
async def get_ensemble_weights():
    """현재 앙상블 모델 가중치 조회.

    우선순위:
      1. ai_predictions 최신 레코드의 ensemble_weights
      2. DEFAULT_WEIGHTS (11-base 정합 fallback)  ← [P2 PATCH]
    """
    try:
        supabase = get_client()
        # ai_predictions 테이블의 최신 레코드에서 가중치 정보 추출
        response = supabase.table("ai_predictions")\
            .select("ensemble_weights")\
            .order("created_at", desc=True)\
            .limit(1)\
            .execute()

        if response.data and response.data[0].get('ensemble_weights'):
            return response.data[0]['ensemble_weights']

        # [P2 PATCH] 기본값 반환 (11-base fallback)
        return DEFAULT_WEIGHTS
    except Exception:
        # [P2 PATCH] 예외 시 11-base fallback
        return DEFAULT_WEIGHTS
