from fastapi import APIRouter
from typing import List, Dict, Any
from db.supabase_client import get_client

router = APIRouter(
    prefix="/api/performance",
    tags=["Performance"]
)

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
    """현재 앙상블 모델 가중치 조회."""
    # 실제로는 ensemble_weights.json 파일을 읽거나 DB에서 조회
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
        
        # 기본값 반환
        return {"lstm": 0.35, "xgboost": 0.40, "markov": 0.25}
    except Exception:
        return {"lstm": 0.35, "xgboost": 0.40, "markov": 0.25}
