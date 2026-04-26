from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from chains.explain_chain import explain_number
from db.supabase_client import fetch_all_draws

router = APIRouter(
    prefix="/api/explain",
    tags=["Explain"]
)

class ExplainRequest(BaseModel):
    number: int
    user_query: str = "이 번호를 추천한 이유가 뭐야?"
    target_round: Optional[int] = None

@router.post("/")
async def explain_number_reasoning(request: ExplainRequest):
    """특정 번호에 대한 AI 추천/제외 근거 설명."""
    try:
        # 전체 데이터 로드 (모델 예측용)
        draws = fetch_all_draws()

        # 설명 체인 실행
        explanation = await explain_number(
            number=request.number,
            user_query=request.user_query,
            target_round=request.target_round,
            draws_data=draws
        )

        return {"number": request.number, "explanation": explanation}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
