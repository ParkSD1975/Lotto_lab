"""v4 통합 설정 - 딥러닝 + LangChain/RAG."""

import os
from dotenv import load_dotenv

load_dotenv(override=True)

# ── Supabase ──
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# ── Google / Gemma / Gemini ──
# 여러 변수명 순서대로 확인 (HF Space 시크릿 변수명이 다를 수 있음)
GOOGLE_API_KEY = (
    os.getenv("GOOGLE_API_KEY") or
    os.getenv("GEMMA_API_KEY") or
    os.getenv("GEMINI_API_KEY") or
    os.getenv("GOOGLE_GEMMA_KEY") or
    ""
)
EMBEDDING_MODEL = "models/text-embedding-004"
LLM_MODEL = "gemma-4-31b-it"

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
LSTM_SEQ_LEN = 30                # 최근 30회차를 시퀀스로
LSTM_INPUT_DIM = 65              # T-1 결정 A: 동결 (Phase 1~4 출력은 posthoc gate)
LSTM_HIDDEN_DIM = 64             # G-2: 128→64 (1,100회차 데이터 적합)
LSTM_NUM_LAYERS = 1              # G-2: 2→1
LSTM_BIDIRECTIONAL = False       # G-2: True→False
LSTM_DROPOUT = 0.2
LSTM_EPOCHS = 100
LSTM_BATCH_SIZE = 64
LSTM_LR = 0.001
LSTM_WEIGHT_DECAY = 1e-5
LSTM_EARLY_STOP_PATIENCE = 15
LSTM_POS_WEIGHT = 6.5            # G-1: BCEWithLogitsLoss + pos_weight 단일 보정
# G-1 적용 — Focal Loss 폐기 (이중 보정 mode collapse 위험)
# LSTM_FOCAL_GAMMA, LSTM_FOCAL_ALPHA 제거됨

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

# ── GNN 모델 설정 (G-7 / Stage 1-4-D-2-fix-9) ──
# 이전: gnn_model.py 24~33줄 내부 하드코딩 → config.py로 통합
# fix-9: GAT layer-1/2의 W·a·LayerNorm 가중치가 0으로 죽는 mode collapse 잔존
#        → LayerNorm 제거(elementwise_affine=False) + WD 0 + LR 상향 + BCE 비중 강화
GNN_NODE_FEAT_DIM = 10
GNN_HIDDEN_DIM = 64               # GAT layer 1 출력
GNN_HEAD_DIM_2 = 32               # GAT layer 2 출력
GNN_HEADS = [4, 2]                # [layer1_heads, layer2_heads]
GNN_DROPOUT = 0.20                # fix-9: 0.25 → 0.20 (mode collapse 방지)
GNN_LR = 0.002                    # fix-9: 0.0008 → 0.002 (강한 학습)
GNN_WEIGHT_DECAY = 0.0            # fix-9: 1e-4 → 0 (W가 0으로 죽는 현상 방지)
GNN_EPOCHS = 250                  # fix-9: 80 → 250 (epoch 150에서 아직 학습 진행 중)
GNN_PATIENCE = 30                 # fix-9: 15 → 30
GNN_MIN_HIST = 50                 # 학습 샘플 생성 최소 이력 회차
GNN_TOPK = 15                     # G-7-C: 10 → 15 (dense graph 정보 손실 방지)
GNN_POS_WEIGHT = 6.5              # BCE 보조 손실 (G-1과 동일 정책)
GNN_BCE_AUX_WEIGHT = 0.6          # fix-9: 0.3 → 0.6 (BCE 비중 강화 — multi-label 강화)
GNN_FEATURE_NORMALIZE = True      # G-7-D: PowerTransformer (Yeo-Johnson) 적용
GNN_FEATURE_NORMALIZE_INDICES = [0, 1, 2, 3, 4, 6]  # freq×3, gap×2, hot_streak (long-tail)

# ── [Stage 1-4-D-2-fix-41] 가중치 floor + epoch 증가 + categorical feature ──
# 사용자 결정: TabNet/CatBoost/MHN 가중치 ≤ 0.03 → ensemble 비활성 문제 해소
TASK_WEIGHT_FLOOR = 0.05         # 활성 모델 최소 가중치 (DEPRECATED 제외)
TABNET_MAX_EPOCHS = 200          # 100 -> 200 (수렴 부족 보강)
CATBOOST_ITERATIONS = 1000       # 500 -> 1000
MHN_MAX_EPOCHS = 60              # 30 -> 60
ENABLE_CATEGORICAL_FEATURES = True  # TabNet/CatBoost endings/decade/odd_even/high_low 인코딩

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

# ── M-1: MetaLearner 재구축 ──
# alpha 기본값 (학습 전 first-run seed). fit_alpha()로 walk-forward 갱신.
META_ALPHA_DEFAULT = 0.30
# AE 게이트 boolean 임계값 — 학습 fold AE 재구성오차 분포의 95p
AE_GATE_PERCENTILE = 95
# fit_alpha() 동작에 필요한 최소 검증 데이터
META_ALPHA_MIN_VAL_SAMPLES = 50

# Task 8종 → 21지표 재설계 predictor 매핑 (M-1 결정 A)
# 7개 base 모델(LSTM/CNN/Transformer/XGBoost/GNN/Markov/AE)과 별개로,
# 향후 Phase 1~4 predictor가 추가되면 task별로 어느 predictor를 사용할지 결정.
# 현재는 placeholder — 21지표 PR이 들어올 때 활성화.
TASK_PREDICTOR_MAP = {
    "recommend_top":         ["main_45"],                    # 메인 1~45 모델만
    "exclude":               ["main_45", "ae"],              # AE 강화
    "filter_range":          ["sum", "ac", "endings_sum"],   # 스칼라 지표
    "filter_count_attr":     ["high_low", "odd_even", "carryover", "neighbor", "consecutive"],
    "filter_count_temporal": ["hotcold_12", "missing_4"],
    "filter_count_relation": ["decade_5", "gung_9", "paper_14", "multiple_6", "prime_3"],
    "filter_spatial":        ["paper_14", "gung_9"],
    "regression":            ["regression"],
}

# Task 가중치 매트릭스 외부화 (M-1 결정 F)
# True면 saved_models/task_weights.json에서 로드, 없으면 ensemble.py 하드코딩 default 사용
TASK_WEIGHTS_EXTERNAL = True
TASK_WEIGHTS_FILE = "task_weights.json"  # MODEL_DIR 상대 경로

# ── 모델 저장 경로 ──
MODEL_DIR = os.path.join(os.path.dirname(__file__), "saved_models")
os.makedirs(MODEL_DIR, exist_ok=True)

# ── S-1: SLA 한도 ──
# HF Spaces 무료 단계 기준 (RAM 15GB / 2 cores / 120s timeout)
SLA_TRAIN_WALL_TIME_MAX = 86400      # 주간 학습 ≤ 24h (cron 1회/주)
SLA_INFER_WALL_TIME_MAX = 30          # 단일 회차 추론 ≤ 30s
SLA_INFER_MEM_MAX_GB = 12             # 추론 메모리 peak ≤ 12GB (안전마진 3GB)
SLA_TRAIN_MEM_MAX_GB = 14             # 학습 메모리 peak ≤ 14GB
SLA_API_TIMEOUT = 120                 # API timeout (초)
SLA_HISTORY_FILE = "sla_history.parquet"   # MODEL_DIR 상대

# ── 랜덤 기준선 ──
RANDOM_BASELINE = 1.0 / 45.0  # 기본 확률 (약 0.022)

# ── G-6: 재현성 (Random Seed) ──
# 모든 모델·numpy·torch·random 초기화에 사용. validation.seed_utils.set_global_seed() 호출.
RANDOM_SEED = 42

# ── 소수 집합 ──
PRIMES = {2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43}
SQUARES = {1, 4, 9, 16, 25, 36}
TRIANGULARS = {1, 3, 6, 10, 15, 21, 28, 36, 45}

# ============================================================
# Stage 0 (2026-04-28 Master Plan 기반) — 11 base 토폴로지 + T-1 A 폐기
# 단일 진실 공급원: docs/MASTER_PLAN.md
# ============================================================

# 본 plan 결정 #24: 11 base 모델 전면 도입 (LSTM/Transformer 폐기, TFT 흡수)
MODEL_TOPOLOGY = [
    "xgboost", "catboost", "tabnet",   # 트리·attention
    "cnn", "gnn",                       # 그리드·그래프
    "markov",                            # 전이
    "autoencoder",                       # 이상치 + MoE 게이트로 진화
    "tft", "nbeats",                     # 시계열 통합·분해
    "mhn",                               # 패턴 매칭 메모리
    "bayesian_nn",                       # 불확실성 분포
]
LEGACY_MODELS = {"lstm", "transformer"}  # TFT가 흡수, saved_models/_archive/

# 본 plan 결정 #23: T-1 결정 A 폐기 — 메인 1~45 INPUT_DIM 동결 해제
INPUT_DIM_FROZEN = False
MAIN_MODEL_INPUT_DIM = None  # 학습 시점에 21지표·회귀 압축·메모 합류 후 자동 결정

# G-8: Self-Supervised Pretraining backbone
SSL_BACKBONE_PATH = os.path.join(MODEL_DIR, "ssl_backbone.pt")
SSL_PRETRAIN_EPOCHS = 50
SSL_MASK_RATIO = 0.15
SSL_CONTRASTIVE_TEMP = 0.07

# M-1 진화: MoE 라우팅 (4 expert: normal/anomaly/regression/memo)
MOE_NUM_EXPERTS = 4
MOE_EXPERT_NAMES = ["normal", "anomaly", "regression", "memo"]
MOE_GATING_PATH = os.path.join(MODEL_DIR, "moe_gating.pt")

# Predictor 캐시 (Stage 1~2 산출물)
PREDICTOR_CACHE_DIR = os.path.join(MODEL_DIR, "cache")
os.makedirs(PREDICTOR_CACHE_DIR, exist_ok=True)
for _phase in (1, 2, 3, 4, "regression"):
    os.makedirs(os.path.join(PREDICTOR_CACHE_DIR, f"phase_{_phase}"), exist_ok=True)

# ── Stage 2 (회귀 4 Tier) 상수 ──
REGRESSION_N_RANGE = (2, 200)
REGRESSION_SAMPLE_THRESHOLD = 50  # Tier 1 신뢰 N 최소 sample
REGRESSION_DECADE_CLUSTER_THRESHOLD = 3  # Tier 3-C 군집 트리거 임계값
REGRESSION_LINE_MISS_THRESHOLD = 5  # Tier 3-A 라인 미출 감지
REGRESSION_CONSECUTIVE_RULE_LOOKBACK = 4  # Tier 3-D 룰 2 (1회귀 4연번)
REGRESSION_DEAD_CARRYOVER_THRESHOLD = 2  # Tier 3-E 데드 카운트 임계값
REGRESSION_META_FREQUENCY_MIN = 0.20
REGRESSION_META_SUPPORT_MIN = 10
REGRESSION_META_PATTERNS_PATH = os.path.join(MODEL_DIR, "regression_meta_patterns.json")

# ── Stage 3-B-1 (NumberScorer 4 Pillar 통합) 상수 ──
# Ridge MetaLearner 가중치 저장 경로 (4 Pillar -> final_score)
PILLAR_META_LEARNER_PATH = os.path.join(MODEL_DIR, "pillar_meta_weights.json")
# 최근 N회차 backtest 윈도우로 Pillar 가중치 동적 갱신
RECOMMENDATION_BACKTEST_WINDOW = 50
# Pillar 1~4 Ridge 메타러너 정규화 강도 (sklearn Ridge alpha)
PILLAR_RIDGE_ALPHA = 1.0
