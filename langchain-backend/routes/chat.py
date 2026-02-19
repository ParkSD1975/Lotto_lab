from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    analysis_type: str | None = None
    context_data: str | None = None


@router.post("/chat")
async def chat(req: ChatRequest):
    from chains.chat_chain import run_chat

    result = await run_chat(
        message=req.message,
        session_id=req.session_id,
        analysis_type=req.analysis_type,
        context_data=req.context_data,
    )
    return result
