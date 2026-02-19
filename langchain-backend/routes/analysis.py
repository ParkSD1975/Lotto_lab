from fastapi import APIRouter
from pydantic import BaseModel
from typing import Any

router = APIRouter()

# analysis_type -> topic 자동 매핑
ANALYSIS_TYPE_TO_TOPIC = {
    'ac_value': 'AC값(Arithmetic Complexity)',
    'carryover': '이월수 패턴',
    'number_range': '번호 구간대 분포',
    'odd_even': '홀짝 비율',
    'high_low': '고저 비율',
    'sum': '총합 분석',
    'total_sum': '총합 분석',
    'consecutive': '연번 패턴',
    'prime': '소수 분석',
    'composite': '합성수 분석',
    'tail_sum': '끝수합',
    'gap': '출현 간격',
    'frequency': '출현 빈도',
    'color': '색상 분포',
    'decade': '번호대 분포',
    'hot_cold': '핫/콜드 번호',
    'pattern': '패턴 분석',
    'custom': '사용자 지정 분석',
}


class AnalysisRequest(BaseModel):
    prompt: str
    analysis_type: str = ""
    target_round: int = 0
    subject_round: int = 0
    response_style: str = "default"
    topic: str = ""
    session_id: str | None = None
    history_data: list[Any] | None = None


@router.post("/analyze")
async def analyze(req: AnalysisRequest):
    try:
        from chains.analysis_chain import run_analysis
        import traceback

        # topic 결정: 프론트에서 보냈으면 사용, 없으면 analysis_type에서 유도
        topic = req.topic
        if not topic:
            topic = ANALYSIS_TYPE_TO_TOPIC.get(req.analysis_type, '')

        result = await run_analysis(
            context=req.prompt,
            analysis_type=req.analysis_type,
            target_round=req.target_round,
            subject_round=req.subject_round,
            response_style=req.response_style,
            history_data=req.history_data,
            topic=topic
        )
        return result
    except Exception as e:
        print(f"[FAIL] Analysis Endpoint Error: {str(e).encode('ascii', 'replace').decode('ascii')}")
        traceback.print_exc()
        return {
            "trend": f"Server Error: {str(e)}",
            "pattern": "Please check server logs.",
            "recommendation": "System Error"
        }
