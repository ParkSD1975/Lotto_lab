from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from chains.interpret_chain import interpret_query

router = APIRouter(
    prefix="/api/interpret",
    tags=["NLP"]
)

class InterpretRequest(BaseModel):
    query: str

@router.post("/")
async def interpret_command(request: InterpretRequest):
    """자연어 명령을 해석하여 JSON 파라미터 반환"""
    result = await interpret_query(request.query)
    return result
