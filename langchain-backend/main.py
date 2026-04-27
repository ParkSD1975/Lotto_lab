import sys
import os

# 프로젝트 루트를 PYTHONPATH에 추가
sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from routes import analysis, chat, report, interpret, vectors
from routes import predictions, performance, explain, pipeline, deep_analysis_v3
from routes import smart_query, llm_filter
from routes import predictions_v4           # P: Single Source of Truth API v4

from apscheduler.schedulers.asyncio import AsyncIOScheduler
# T-1 결정 C: v1 (WeeklyPipeline) 폐기 — v2가 single source of truth
from pipeline.weekly_pipeline_v2 import WeeklyPipelineV2

scheduler = AsyncIOScheduler()

app = FastAPI(title="Lotto AI Backend v4", version="4.0.0")

def _run_weekly_pipeline_v2():
    """WeeklyPipelineV2 동기 래퍼 (APScheduler ThreadPoolExecutor용)"""
    pipeline = WeeklyPipelineV2()
    return pipeline.run()


@app.on_event("startup")
async def start_scheduler():
    """앱 시작 시 APScheduler 스케줄러 및 주간 파이프라인 등록"""
    try:
        scheduler.add_job(_run_weekly_pipeline_v2, 'cron', day_of_week='sat', hour=21, minute=30, id='weekly_analysis_v2')
        scheduler.start()
        print("[INFO] Weekly Pipeline V2 Scheduler started (APScheduler: Sat 21:30).")
    except Exception as e:
        print(f"[WARN] Scheduler 시작 실패 (무시하고 계속): {e}")

@app.on_event("shutdown")
async def shutdown_scheduler():
    """앱 종료 시 스케줄러 안전하게 종료"""
    if scheduler.running:
        scheduler.shutdown()
    print("[INFO] Weekly Pipeline Scheduler shut down.")

# CORS 설정: allow_credentials=True일 경우 origins에 "*"를 포함하면 안 됩니다.
origins = [
    "http://127.0.0.1:5500",
    "http://127.0.0.1:5505",
    "http://127.0.0.1:5506",
    "http://127.0.0.1:5507",
    "http://127.0.0.1:5508",
    "http://localhost:5500",
    "http://localhost:5505",
    "http://localhost:5506",
    "http://localhost:5507",
    "http://localhost:8000",
    "http://localhost:3000",
    "http://localhost:5508",
]

# 모든 오리진 허용이 필요하다면 아래와 같이 하되 credentials는 False여야 함
# 여기서는 로컬 개발 환경을 위해 명시적 목록을 사용합니다.

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 불필요하고 충돌 가능성이 있는 커스텀 CORS 미들웨어 삭제 (CORSMiddleware로 충분)

# ── 기존 라우트 ──
app.include_router(analysis.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(report.router, prefix="/api")
app.include_router(interpret.router)
app.include_router(vectors.router, prefix="/api")

# ── v4 신규 라우트 ──
app.include_router(predictions.router)
app.include_router(performance.router)
app.include_router(explain.router)
app.include_router(pipeline.router)
app.include_router(deep_analysis_v3.router)
app.include_router(smart_query.router)
app.include_router(llm_filter.router)
app.include_router(predictions_v4.router)  # P: weekly_* 읽기 전용 엔드포인트


@app.get("/debug-env")
async def debug_env():
    """임시 디버그: 어떤 API 키 환경변수가 설정돼 있는지 확인 (키 앞 8자리 표시)"""
    import os
    checks = ["GOOGLE_API_KEY", "GEMMA_API_KEY", "GEMINI_API_KEY", "GOOGLE_GEMMA_KEY", "HF_TOKEN", "HUGGINGFACE_TOKEN"]
    result = {}
    for k in checks:
        val = os.getenv(k, "")
        result[k] = val[:8] + "****" if val else "(not set)"

    # Gemini API 직접 테스트
    import httpx
    key = os.getenv("GOOGLE_API_KEY", "")
    if key:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/gemma-4-31b-it:generateContent?key={key}",
                    json={"contents": [{"parts": [{"text": "hi"}]}]}
                )
                result["api_test"] = f"HTTP {resp.status_code}: {resp.text[:200]}"
        except Exception as e:
            result["api_test"] = f"request error: {str(e)[:200]}"
    else:
        result["api_test"] = "no key"

    # 전체 환경변수에서 GOOGLE 관련 키 스캔
    google_vars = {k: v[:8]+"****" for k, v in os.environ.items() if "google" in k.lower() or "gemma" in k.lower() or "gemini" in k.lower()}
    result["google_env_scan"] = google_vars

    return result


@app.get("/health")
async def health():
    from db.vector_store import get_document_count

    try:
        count = get_document_count()
    except Exception:
        count = 0

    # 모델 존재 여부 확인 (5중 앙상블)
    import config

    models_status = {
        "transformer": os.path.exists(os.path.join(config.MODEL_DIR, "transformer_model.pt")),
        "lstm": os.path.exists(os.path.join(config.MODEL_DIR, "lstm_model.pt")),
        "cnn": os.path.exists(os.path.join(config.MODEL_DIR, "cnn_model.pt")),
        "xgboost": os.path.exists(os.path.join(config.MODEL_DIR, "xgboost_models.pkl")),
        "markov": os.path.exists(os.path.join(config.MODEL_DIR, "markov_matrices.json")),
        "ensemble_weights": os.path.exists(
            os.path.join(config.MODEL_DIR, "ensemble_weights.json")
        ),
    }

    return {
        "status": "ok",
        "backend": "langchain-v4",
        "ensemble": "5-model (Transformer+LSTM+CNN+XGBoost+Markov)",
        "vector_documents": count,
        "models": models_status,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
