"""v4 통합 설정 - 딥러닝 + LangChain/RAG."""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Supabase ──
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# ── Google / Gemini ──
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
EMBEDDING_MODEL = "models/gemini-embedding-001"
LLM_MODEL = "gemini-2.0-flash"

# ── ChromaDB ──
# Note: Korean characters in path can cause HNSW native library issues.
# Use user home directory with ASCII-only path as fallback.
_default_chroma = os.path.join(os.path.dirname(__file__), "chroma_db")
_ascii_chroma = os.path.join(os.path.expanduser("~"), ".lotto_ai", "chroma_db")

# Check if project path contains non-ASCII characters
try:
    _default_chroma.encode("ascii")
    CHROMA_DB_PATH = _default_chroma
except UnicodeEncodeError:
    CHROMA_DB_PATH = _ascii_chroma
    os.makedirs(CHROMA_DB_PATH, exist_ok=True)

# ── LSTM 모델 설정 ──
LSTM_SEQ_LEN = 30          # 최근 30회차를 시퀀스로
LSTM_INPUT_DIM = 65        # 57 + 8 (Cyclical/FFT Features)
LSTM_HIDDEN_DIM = 128
LSTM_NUM_LAYERS = 2
LSTM_DROPOUT = 0.2          # 과적합 방지를 위해 20% 뉴런 무작위 비활성화
LSTM_EPOCHS = 100
LSTM_BATCH_SIZE = 64        # 한 번에 학습할 데이터 묶음 크기
LSTM_LR = 0.001
LSTM_WEIGHT_DECAY = 1e-5
LSTM_EARLY_STOP_PATIENCE = 15
LSTM_POS_WEIGHT = 6.5      # 양성 가중치 (45개 중 6개)
LSTM_FOCAL_GAMMA = 2.0     # [New] Focal Loss Gamma
LSTM_FOCAL_ALPHA = 0.25    # [New] Focal Loss Alpha

# ── XGBoost 설정 ──
XGB_N_ESTIMATORS = 200
XGB_MAX_DEPTH = 6
XGB_LEARNING_RATE = 0.05
XGB_SUBSAMPLE = 0.8
XGB_COLSAMPLE = 0.8
XGB_REG_ALPHA = 0.1
XGB_REG_LAMBDA = 1.0
XGB_MIN_CHILD_WEIGHT = 5

# ── Transformer 모델 설정 ──
TRANSFORMER_SEQ_LEN = 30      # LSTM과 동일 시퀀스 길이
TRANSFORMER_INPUT_DIM = 65    # LSTM과 동일 입력 차원
TRANSFORMER_D_MODEL = 128     # 임베딩 차원
TRANSFORMER_NHEAD = 4         # 멀티 헤드 어텐션 개수
TRANSFORMER_NUM_LAYERS = 2    # 인코더 레이어 층수
TRANSFORMER_DIM_FF = 256      # Feed-forward 차원
TRANSFORMER_DROPOUT = 0.2
TRANSFORMER_EPOCHS = 100
TRANSFORMER_BATCH_SIZE = 64
TRANSFORMER_LR = 0.0005
TRANSFORMER_WEIGHT_DECAY = 1e-5
TRANSFORMER_EARLY_STOP_PATIENCE = 15

# ── 1D-CNN 모델 설정 ──
CNN_SEQ_LEN = 30              # LSTM과 동일 시퀀스 길이
CNN_INPUT_DIM = 65            # LSTM과 동일 입력 차원
CNN_FILTERS_1 = 64            # 1층 필터 개수
CNN_FILTERS_2 = 128           # 2층 필터 개수
CNN_KERNEL_SIZE = 3           # 3회차 묶음 분석
CNN_DROPOUT = 0.2
CNN_EPOCHS = 100
CNN_BATCH_SIZE = 64
CNN_LR = 0.001
CNN_WEIGHT_DECAY = 1e-5
CNN_EARLY_STOP_PATIENCE = 15

# ── 앙상블 설정 ──
ENSEMBLE_INITIAL_WEIGHTS = {
    "transformer": 0.30,
    "lstm": 0.20,
    "cnn": 0.20,
    "xgboost": 0.20,
    "markov": 0.10,
}
ENSEMBLE_MIN_WEIGHT = 0.05
ENSEMBLE_BLEND_RATIO = 0.7   # 기존 가중치 유지 비율

# ── 모델 저장 경로 ──
MODEL_DIR = os.path.join(os.path.dirname(__file__), "saved_models")
os.makedirs(MODEL_DIR, exist_ok=True)

# ── 랜덤 기준선 ──
RANDOM_BASELINE = 1.0 / 45.0  # 기본 확률 (약 0.022)

# ── 소수 집합 ──
PRIMES = {2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43}
SQUARES = {1, 4, 9, 16, 25, 36}
TRIANGULARS = {1, 3, 6, 10, 15, 21, 28, 36, 45}
