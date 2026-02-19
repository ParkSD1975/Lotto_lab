from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class ReportRequest(BaseModel):
    round: int | None = None


@router.post("/report")
async def report(req: ReportRequest):
    from chains.report_chain import generate_report

    result = await generate_report(target_round=req.round)
    return result
