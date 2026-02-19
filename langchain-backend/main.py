import sys
import os

# 프로젝트 루트를 PYTHONPATH에 추가
sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from routes import analysis, chat, report, interpret, vectors
from routes import predictions, performance, explain, pipeline, deep_analysis
from routes import deep_analysis_v2, deep_analysis_v3

app = FastAPI(title="Lotto AI Backend v4", version="4.0.0")

origins = [
    "http://127.0.0.1:5505",
    "http://127.0.0.1:5506",
    "http://127.0.0.1:5507",
    "http://localhost:5500",
    "http://localhost:5505",
    "http://localhost:5506",
    "http://localhost:5507",
    "http://localhost:8000",
    "http://localhost:3000",
    "http://127.0.0.1:5500",
    "http://127.0.0.1:5508",
    "http://localhost:5508",
    "*"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_cors_headers(request: Request, call_next):
    try:
        response = await call_next(request)
    except Exception as e:
        print(f"[ERROR] Unhandled Server Error: {str(e).encode('ascii', 'replace').decode('ascii')}")
        response = JSONResponse(
            content={"detail": str(e)}, 
            status_code=500
        )
    
    origin = request.headers.get("origin")
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "*"
    
    return response

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
app.include_router(deep_analysis.router)
app.include_router(deep_analysis_v2.router)
app.include_router(deep_analysis_v3.router)


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
