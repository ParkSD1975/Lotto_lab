from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Any

from db.supabase_client import get_client

router = APIRouter(
    prefix="/api/predictions",
    tags=["Predictions"]
)

class PredictionResponse(BaseModel):
    model_config = {"protected_namespaces": ()}
    target_round: int
    prediction_type: str
    predicted_numbers: List[int]
    confidence_score: float
    model_version: str
    hit_count: Optional[int] = None
    analysis_detail: Optional[Dict[str, Any]] = None

@router.get("/latest", response_model=List[PredictionResponse])
async def get_latest_predictions(limit: int = 10):
    """최신 예측 결과 조회."""
    supabase = get_client()
    
    # ai_predictions 테이블에서 최신순 조회
    response = supabase.table("ai_predictions")\
        .select("*")\
        .order("created_at", desc=True)\
        .limit(limit)\
        .execute()
        
    return response.data

@router.get("/{round_num}", response_model=List[PredictionResponse])
async def get_predictions_by_round(round_num: int):
    """특정 회차 예측 결과 조회."""
    supabase = get_client()
    
    response = supabase.table("ai_predictions")\
        .select("*")\
        .eq("target_round", round_num)\
        .execute()
        
    return response.data
