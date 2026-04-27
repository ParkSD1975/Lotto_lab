from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any

from chains.llm_filter_chain import run_llm_filter

router = APIRouter(prefix="/api/llm-filter", tags=["LLM Filter"])


class LLMFilterRequest(BaseModel):
    combinations: List[Dict[str, Any]]


@router.post("/")
async def get_llm_filter_recommendations(request: LLMFilterRequest):
    """LLM(Gemini)을 통한 필터 범위 추천"""
    try:
        if not request.combinations:
            raise HTTPException(status_code=400, detail="combinations is required")

        recommendations, error = await run_llm_filter(request.combinations)
        return {"recommendations": recommendations, "source": "llm", "error": error}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
