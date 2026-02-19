from fastapi import APIRouter, BackgroundTasks
from pipeline.weekly_pipeline import WeeklyPipeline

router = APIRouter(
    prefix="/api/pipeline",
    tags=["Pipeline"]
)

pipeline = WeeklyPipeline()

@router.post("/run")
async def run_pipeline(background_tasks: BackgroundTasks, new_round: int = None):
    """주간 분석 파이프라인 수동 실행 (백그라운드)."""
    # 백그라운드 작업으로 등록하여 API 응답은 즉시 반환
    background_tasks.add_task(pipeline.run, new_round)
    return {"status": "started", "message": "주간 분석 파이프라인이 백그라운드에서 시작되었습니다."}

@router.get("/status")
async def get_pipeline_status():
    """파이프라인 상태 확인 (구현 예정)."""
    # 실제 상태 관리는 Redis나 DB가 필요하지만 여기선 간단히 리턴
    return {"status": "idle", "last_run": "unknown"}
