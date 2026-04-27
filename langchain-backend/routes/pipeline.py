"""파이프라인 라우터 (T-1 결정 C 마이그레이션).

v1(WeeklyPipeline) 폐기 → v2(WeeklyPipelineV2)가 single source of truth.
기존 /run 엔드포인트는 *호환 유지*를 위해 v2로 위임.
"""
from fastapi import APIRouter, BackgroundTasks
from pipeline.weekly_pipeline_v2 import WeeklyPipelineV2

router = APIRouter(
    prefix="/api/pipeline",
    tags=["Pipeline"]
)

_pipeline_v2 = None


def get_pipeline_v2():
    global _pipeline_v2
    if _pipeline_v2 is None:
        _pipeline_v2 = WeeklyPipelineV2()
    return _pipeline_v2


@router.post("/run")
async def run_pipeline(background_tasks: BackgroundTasks, new_round: int = None):
    """주간 분석 파이프라인 수동 실행 (백그라운드).

    T-1 결정 C: v1 폐기 후 v2로 위임. new_round 인자는 v2의 target_round로 매핑.
    """
    background_tasks.add_task(get_pipeline_v2().run, new_round)
    return {"status": "started",
            "message": "주간 분석 파이프라인(V2)이 백그라운드에서 시작되었습니다."}


@router.post("/run-v2")
async def run_pipeline_v2(background_tasks: BackgroundTasks):
    """명시적 V2 실행 엔드포인트 (호환 유지)."""
    background_tasks.add_task(get_pipeline_v2().run)
    return {"status": "started", "message": "WeeklyPipelineV2 백그라운드 실행 시작"}


@router.post("/train")
async def train_all_models(background_tasks: BackgroundTasks, force_retrain: bool = False):
    """7개 딥러닝 모델 전체 파인튜닝 (백그라운드 실행).

    force_retrain=true: 초기 상태에서 완전 재학습
    force_retrain=false (기본): 기존 가중치 위에 파인튜닝
    """
    async def _train():
        from db.supabase_client import fetch_all_draws
        import logging
        logger = logging.getLogger("TrainAll")
        try:
            p = get_pipeline_v2()
            draws = fetch_all_draws()
            logger.info(f"[Train] {len(draws)}회차 데이터로 전체 모델 파인튜닝 시작 (force={force_retrain})")
            result = p.ensemble.train_all(draws, force_retrain=force_retrain)
            logger.info(f"[Train] 완료: {result}")
        except Exception as e:
            logger.error(f"[Train] 실패: {e}")

    background_tasks.add_task(_train)
    return {"status": "started",
            "message": f"7개 모델 파인튜닝 시작 (force_retrain={force_retrain}). 완료까지 수분 소요."}


@router.get("/status")
async def get_pipeline_status():
    """파이프라인 상태 확인."""
    return {"status": "idle", "last_run": "unknown"}
