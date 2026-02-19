# AI 시스템 v4 구현 상세 가이드

**작성일**: 2026-02-07
**기반 문서**: ai_master_plan_v4_unified.md
**목적**: 파일 단위별 구현 방법 + 기존 24개 분석 페이지 AI 적용 방법 상세 기술

---

## 목차

1. [현재 AI 분석 구조 (AS-IS)](#1-현재-ai-분석-구조-as-is)
2. [변경 후 AI 분석 구조 (TO-BE)](#2-변경-후-ai-분석-구조-to-be)
3. [디렉토리 구조 변경 내역](#3-디렉토리-구조-변경-내역)
4. [신규 생성 파일 상세](#4-신규-생성-파일-상세)
5. [기존 수정 파일 상세](#5-기존-수정-파일-상세)
6. [기존 24개 분석 페이지 AI 적용 방법](#6-기존-24개-분석-페이지-ai-적용-방법)
7. [DB 마이그레이션 SQL](#7-db-마이그레이션-sql)
8. [실행 순서 및 의존 관계](#8-실행-순서-및-의존-관계)

---

## 1. 현재 AI 분석 구조 (AS-IS)

### 1.1 현재 흐름

```
[사용자가 분석 페이지 접속 또는 AI 버튼 클릭]
        │
        ▼
[각 HTML 페이지의 refreshAIAnalysis()]
  ├── 페이지별 데이터 수집 (allDrawData, 통계 계산)
  ├── customData 문자열 조립
  └── window.AIAnalysis.executeAnalysis(config) 호출
        │
        ▼
[js/common_v2.js → generatePrompt(config)]
  ├── Role + Task + 데이터 + 분석 규칙 → 프롬프트 생성
  └── supabaseClient.functions.invoke('analyze-lotto', {body: {context: prompt}})
        │
        ▼
[Supabase Edge Function: analyze-lotto]
  ├── Google Gemini 2.0 Flash API 호출
  └── JSON 응답 반환: {trend, pattern, recommendation}
        │
        ▼
[js/common_v2.js → renderAnalysis()]
  ├── JSON 파싱 (extractFirstJsonObject → parseLooseTriple 순)
  ├── formatText()로 태그 변환: {{good:}} {{warn:}} {{range:}} → HTML 컬러 span
  └── containerId에 HTML 삽입 (흐름 진단 / 패턴 분석 / 필승 공략 3섹션)
```

### 1.2 현재 한계

| 항목 | 현재 상태 | 문제점 |
|------|----------|--------|
| 예측 근거 | Gemini LLM의 "감"에 의존 | 통계적 근거 없음, 매번 다른 답변 |
| 추천/제외수 | LLM이 자유롭게 생성 | 모델 학습 기반이 아님 |
| ai_predictions 테이블 | 스키마만 존재, 데이터 없음 | 딥러닝 예측이 구현되지 않음 |
| 모델 성능 추적 | 없음 | 예측이 맞았는지 검증 불가 |
| 벡터 검색(RAG) | 없음 | 과거 유사 패턴 참조 불가 |

---

## 2. 변경 후 AI 분석 구조 (TO-BE)

### 2.1 새로운 흐름

```
[사용자가 분석 페이지 접속]
        │
        ▼
[각 HTML 페이지의 refreshAIAnalysis()]  ← 기존과 동일한 진입점
  ├── 페이지별 데이터 수집 (기존과 동일)
  ├── customData 문자열 조립 (기존과 동일)
  └── window.AIProxy.invoke(config) 호출  ← ★ 변경점: AIProxy 경유
        │
        ├── [LangChain 서버 실행 중?] ──YES──→ Python FastAPI 서버
        │                                       │
        │                                       ├── ai_predictions에서 딥러닝 예측 로드
        │                                       ├── RAG로 유사 과거 패턴 10건 검색
        │                                       ├── XGBoost feature importance 로드
        │                                       ├── Markov reasoning 로드
        │                                       ├── 전체 컨텍스트 → Gemini LLM 호출
        │                                       └── JSON 응답 반환
        │
        └── [LangChain 서버 없음?] ──NO──→ 기존 Edge Function (fallback)
                                             └── 기존과 동일하게 작동
        │
        ▼
[js/common_v2.js → renderAnalysis()]  ← 기존과 동일한 렌더링
  └── JSON 형식이 동일하므로 프론트엔드 변경 최소화
```

### 2.2 핵심 변경 요약

| 항목 | 변경 전 | 변경 후 |
|------|---------|---------|
| **AI 호출 경로** | `window.AIAnalysis.executeAnalysis()` | `window.AIProxy.invoke()` (Auto fallback) |
| **예측 근거** | Gemini LLM만 | LSTM + XGBoost + Markov → Gemini 해석 |
| **추천/제외수** | LLM 자유 생성 | ai_predictions DB에서 로드 (학습 기반) |
| **과거 패턴 참조** | 없음 | ChromaDB RAG 벡터 검색 |
| **프론트엔드 수정** | - | `common_v2.js`에 AIProxy 추가 (약 50줄) |
| **HTML 페이지 수정** | - | **수정 없음** (AIProxy가 호환 인터페이스 제공) |
| **응답 JSON 형식** | `{trend, pattern, recommendation}` | **동일** (하위 호환) |

---

## 3. 디렉토리 구조 변경 내역

### 3.1 전체 구조

```
로또개발/
├── langchain-backend/              ← Python AI 서버
│   ├── config.py                   [수정] 딥러닝 설정 추가
│   ├── requirements.txt            [수정] PyTorch, XGBoost 의존성 추가
│   ├── main.py                     [수정] 새 라우터 등록
│   ├── .env.example                [유지]
│   │
│   ├── models/                     [신규 디렉토리]
│   │   ├── __init__.py             [신규]
│   │   ├── lstm_model.py           [신규] LSTM + Attention
│   │   ├── xgboost_model.py        [신규] XGBoost 45개 분류기
│   │   ├── markov_model.py         [신규] 마르코프 체인
│   │   └── ensemble.py             [신규] 앙상블 + 조합 생성기
│   │
│   ├── pipeline/                   [신규 디렉토리]
│   │   ├── __init__.py             [신규]
│   │   └── weekly_pipeline.py      [신규] 7단계 주간 파이프라인
│   │
│   ├── chains/
│   │   ├── analysis_chain.py       [수정] v2: 딥러닝 예측 통합
│   │   ├── chat_chain.py           [유지]
│   │   ├── report_chain.py         [수정] v2: 모델 성능 + 딥러닝 통합
│   │   ├── interpret_chain.py      [유지]
│   │   └── explain_chain.py        [신규] 설명 가능한 AI (XAI)
│   │
│   ├── routes/
│   │   ├── analysis.py             [유지]
│   │   ├── chat.py                 [유지]
│   │   ├── report.py               [유지]
│   │   ├── interpret.py            [유지]
│   │   ├── vectors.py              [유지]
│   │   ├── predictions.py          [신규] 예측 결과 조회 API
│   │   ├── performance.py          [신규] 모델 성능 조회 API
│   │   ├── explain.py              [신규] XAI 설명 API
│   │   └── pipeline.py             [신규] 파이프라인 실행 API
│   │
│   ├── db/
│   │   ├── supabase_client.py      [수정] fetch_all_draws 추가
│   │   └── vector_store.py         [유지]
│   │
│   ├── rag/
│   │   ├── data_loader.py          [수정] ai_predictions 벡터화 추가
│   │   ├── embedder.py             [유지]
│   │   └── retriever.py            [유지]
│   │
│   ├── memory/
│   │   └── session_store.py        [유지]
│   │
│   ├── scripts/
│   │   ├── build_vectors.py        [유지]
│   │   ├── update_vectors.py       [유지]
│   │   └── train_models.py         [신규] 전체 모델 학습 스크립트
│   │
│   └── saved_models/               [신규 디렉토리 - 자동 생성]
│       ├── lstm_model.pt           (학습 후 생성)
│       ├── xgboost_models.pkl      (학습 후 생성)
│       ├── markov_matrices.json    (학습 후 생성)
│       └── ensemble_weights.json   (학습 후 생성)
│
├── js/
│   ├── config.js                   [수정] LANGCHAIN 섹션 추가
│   └── common_v2.js                [수정] AIProxy 객체 추가 (~50줄)
│
├── *.html (24개 분석 페이지)        [수정 없음] ← 핵심: HTML 변경 불필요
│
└── md/
    ├── ai_master_plan_v4_unified.md         (설계서)
    └── ai_implementation_guide_v4.md        (이 문서)
```

---

## 4. 신규 생성 파일 상세

### 4.1 models/lstm_model.py

**역할**: 시계열 번호 출현 확률 예측 (Bidirectional LSTM + Attention)

**핵심 클래스/함수**:
```python
class LottoSequenceDataset(Dataset)
    # 역할: lotto_draws 데이터를 (seq_len=30, features=57) 시퀀스로 변환
    # 입력: draws (회차 리스트)
    # 출력: (X: 시퀀스 텐서, y: 45차원 binary 레이블)
    #
    # 피처 구성 (57차원):
    #   - 45차원: 각 번호 출현 여부 (0/1)
    #   - 12차원: 총합, 홀수비, 저번호비, AC값, 연번쌍, 끝수합,
    #             소수비, 이월수, 총합추세, Gap엔트로피, 핫비율, 콜드비율

class LottoLSTM(nn.Module)
    # 역할: 양방향 LSTM + Attention 메커니즘으로 다음 회차 번호 확률 예측
    # 구조: LSTM(57→128, 2층, 양방향) → Attention → FC(256→128→45→Sigmoid)
    # 입력: (batch, 30, 57)
    # 출력: (batch, 45) 확률 + (batch, 30) Attention 가중치

class LSTMTrainer
    # train(draws) → 모델 학습 + 저장 (saved_models/lstm_model.pt)
    # predict(draws) → {번호: 확률} dict 반환
    # get_attention_weights(draws) → {회차: 가중치} (XAI용)
```

**DB 의존**: `lotto_draws` (numbers 컬럼)
**저장 파일**: `saved_models/lstm_model.pt`

---

### 4.2 models/xgboost_model.py

**역할**: 45개 번호 각각에 대해 독립적인 이진 분류 (출현/미출현)

**핵심 클래스/함수**:
```python
class LottoXGBoost
    # 역할: 번호당 1개씩, 총 45개 XGBClassifier 관리
    #
    # build_features_for_number(num, draws, round_idx)
    #   → 특정 번호에 대해 32차원 피처 벡터 생성
    #   → ★ 미래 정보 누출 방지: round_idx 이전 데이터만 사용
    #
    #   피처 구성 (32차원):
    #   [번호 자체 15개]
    #     total_freq, recent_10_freq, recent_50_freq,
    #     current_gap, avg_gap, max_gap, std_gap, gap_percentile,
    #     momentum, trend_slope, is_prime, is_odd, decade, tail_digit, is_low
    #   [패턴 12개]
    #     last_sum, last_odd, last_low, last_ac, last_consec, last_tail_sum,
    #     avg_sum, sum_std, carryover, freq_diff, gap_position, momentum_dup
    #   [동반 출현 5개]
    #     top_partner, avg_partner, partner_diversity,
    #     same_tail_active, same_decade_active
    #
    # train(draws) → 45개 모델 학습 + 저장
    # predict(draws) → {번호: 확률} dict 반환
    # get_top_features(num, top_k=5) → [(피처명, 중요도)] 반환 (XAI용)
```

**DB 의존**: `lotto_draws`
**저장 파일**: `saved_models/xgboost_models.pkl`

---

### 4.3 models/markov_model.py

**역할**: 번호별 Gap 기반 전이 확률 계산

**핵심 클래스/함수**:
```python
class MarkovLottoModel
    # 상태 정의: "현재 연속 미출현 횟수" (Gap)
    # 전이: Gap N → 출현(리셋) or Gap N+1(계속)
    #
    # train(draws) → 전이 확률 행렬 구성 (45개 번호 × Gap 상태)
    # predict(draws) → {번호: {probability, current_gap, confidence, reasoning}}
    #   - 관측된 Gap → 전이 확률 사용
    #   - 미관측 Gap → 베이지안 사전확률 (평균 회귀)
    # _generate_reasoning(num, gap, prob) → 자연어 추론 문장 (XAI용)
    #   예: "번호 7은 12회 연속 미출현 중이며, 과거 동일 상황에서 출현 확률은 35.2%입니다 (근거: 8회)"
```

**DB 의존**: `lotto_draws`
**저장 파일**: `saved_models/markov_matrices.json`

---

### 4.4 models/ensemble.py

**역할**: 3개 모델 통합 + 동적 가중치 + 조합 생성

**핵심 클래스/함수**:
```python
class LottoEnsemble
    # 초기 가중치: LSTM 0.35, XGBoost 0.40, Markov 0.25
    #
    # train_all(draws) → 3개 모델 순차 학습
    # predict(draws, custom_rules=None) → {
    #     probabilities: {번호: 최종확률},
    #     recommended: [Top 10 추천수],
    #     excluded: [Bottom 10 제외수],
    #     top_6: [최고 확률 6개],
    #     model_contributions: {모델명: {번호: 확률}},
    #     markov_reasoning: {번호: 추론문장},
    #     xgb_feature_importance: {번호: [(피처, 중요도)]},
    #     weights_used: {모델명: 가중치}
    # }
    #
    # update_weights(actual_numbers, predictions)
    #   → 실제 당첨번호와 비교하여 모델별 적중률 계산
    #   → 가중치 블렌딩: 70% 기존 + 30% 새 가중치
    #   → 최소 가중치 0.10 보장

class CombinationGenerator
    # generate(ensemble_result, filter_settings, n=5)
    #   → Monte Carlo 가중 샘플링으로 필터 통과하는 6번호 조합 생성
    #   → 필터: sum_range, odd_count, low_count, ac_value, consecutive
```

**DB 의존**: `lotto_draws`, `ai_custom_analyses` (커스텀 룰)
**저장 파일**: `saved_models/ensemble_weights.json`

---

### 4.5 pipeline/weekly_pipeline.py

**역할**: 매주 토요일 추첨 후 실행되는 7단계 자동 파이프라인

```python
class WeeklyPipeline
    # async run(new_round=None)
    #
    # Stage 1: Data Ingestion 확인
    #   → lotto_draws 최신 회차 확인 (update_lotto.py가 이미 크롤링)
    #   → 소요: ~1초
    #
    # Stage 2: Previous Prediction Verification
    #   → 직전 예측의 hit_count 업데이트
    #   → model_performance_log INSERT (모델별 적중률)
    #   → 앙상블 가중치 동적 조정
    #   → 소요: ~3초
    #
    # Stage 3: Stats Update
    #   → stats_summary UPSERT (회차별 종합 통계)
    #   → 소요: ~2초
    #
    # Stage 4: Deep Learning Prediction
    #   → 앙상블 예측 실행 (LSTM + XGBoost + Markov)
    #   → 조합 생성 (Monte Carlo)
    #   → ai_predictions INSERT (4가지 타입: exclusion/recommendation/filter/combination)
    #   → 소요: ~30초
    #
    # Stage 5: Custom Rule Evaluation
    #   → is_ai_enabled=true인 커스텀 룰의 적중률 재계산
    #   → ai_evaluation 업데이트 (is_hot, contribution_to_ai)
    #   → 소요: ~5초
    #
    # Stage 6: RAG Vector Update
    #   → 새 회차 데이터 → ChromaDB 벡터화
    #   → ai_predictions → 벡터화
    #   → 소요: ~15초
    #
    # Stage 7: Report Generation
    #   → LangChain ReportChain v2 실행 → 주간 보고서 생성
    #   → 소요: ~20초
    #
    # 전체 소요: ~90초
```

**DB 의존**: `lotto_draws`, `ai_predictions`, `model_performance_log`, `stats_summary`, `ai_custom_analyses`

---

### 4.6 chains/explain_chain.py

**역할**: "왜 번호 7을 추천했어?" → 자연어 설명 생성

```python
async def run_explain(number: int, target_round: int) → dict
    # 1. ai_predictions에서 해당 번호의 추천/제외 여부 확인
    # 2. model_contributions에서 모델별 확률 로드
    # 3. XGBoost feature_importance에서 해당 번호의 핵심 피처 로드
    # 4. Markov reasoning에서 해당 번호의 Gap 추론 로드
    # 5. model_performance_log에서 최근 모델 신뢰도 로드
    # 6. 전체 데이터 → Gemini LLM → 자연어 설명 생성
    #
    # 반환: {
    #     explanation: "번호 7은 ...",
    #     model_contributions: {lstm: "...", xgboost: "...", markov: "..."},
    #     key_factors: ["현재 12회 미출현", "최근 모멘텀 상승", "동반 출현 활발"],
    #     confidence_assessment: "신뢰도 평가"
    # }
```

---

### 4.7 routes/ 신규 라우트

| 파일 | 엔드포인트 | 역할 |
|------|-----------|------|
| `predictions.py` | `GET /api/predictions/{round}` | 특정 회차 딥러닝 예측 결과 |
| | `GET /api/predictions/` | 최근 예측 목록 |
| `performance.py` | `GET /api/performance/` | 모델별 성능 요약 |
| | `GET /api/performance/history` | 성능 이력 상세 |
| | `GET /api/performance/weights` | 현재 앙상블 가중치 |
| `explain.py` | `POST /api/explain/` | 번호별 추천/제외 근거 설명 |
| `pipeline.py` | `POST /api/pipeline/run` | 주간 파이프라인 실행 |
| | `GET /api/pipeline/status` | 파이프라인 상태 확인 |
| | `POST /api/pipeline/train` | 모델 전체 재학습 |

---

### 4.8 scripts/train_models.py

**역할**: 커맨드라인에서 전체 모델 학습을 실행하는 스크립트

```python
# 사용법: python scripts/train_models.py
#
# 1. Supabase에서 전체 lotto_draws 로드
# 2. LottoEnsemble.train_all(draws) 실행
# 3. 학습 결과 출력
# 4. saved_models/에 모델 파일 저장
#
# 최초 1회 실행 필수. 이후 파이프라인이 자동 재학습.
```

---

## 5. 기존 수정 파일 상세

### 5.1 config.py (수정)

**변경 내용**: 딥러닝 모델 관련 설정 상수 추가

```python
# 추가되는 설정:
LSTM_SEQ_LEN = 30           # LSTM 시퀀스 길이
LSTM_INPUT_DIM = 57         # LSTM 입력 차원
LSTM_HIDDEN_DIM = 128       # LSTM 은닉층 크기
LSTM_EPOCHS = 100           # 최대 학습 에폭
LSTM_POS_WEIGHT = 6.5       # 양성 가중치 (45개 중 6개)

XGB_N_ESTIMATORS = 200      # XGBoost 트리 수
XGB_MAX_DEPTH = 6           # 트리 깊이

ENSEMBLE_INITIAL_WEIGHTS = {"lstm": 0.35, "xgboost": 0.40, "markov": 0.25}
ENSEMBLE_MIN_WEIGHT = 0.10  # 최소 가중치

MODEL_DIR = "saved_models/"  # 모델 저장 경로
PRIMES = {2,3,5,7,11,...}    # 소수 집합
```

**기존 코드 영향**: 없음 (상수 추가만)

---

### 5.2 requirements.txt (수정)

**추가되는 의존성**:
```
torch>=2.1.0          # LSTM 모델 (PyTorch)
xgboost>=2.0.0        # XGBoost 분류기
numpy>=1.26.0         # 수치 연산
scikit-learn>=1.4.0   # 데이터 분할 유틸
joblib>=1.3.0         # 모델 직렬화
```

---

### 5.3 main.py (수정)

**변경 내용**: 신규 라우터 4개 등록

```python
# 기존 라우터 (유지)
app.include_router(analysis_router)
app.include_router(chat_router)
app.include_router(report_router)
app.include_router(interpret_router)
app.include_router(vectors_router)

# 추가 라우터
app.include_router(predictions_router)   # /api/predictions
app.include_router(performance_router)   # /api/performance
app.include_router(explain_router)       # /api/explain
app.include_router(pipeline_router)      # /api/pipeline
```

---

### 5.4 db/supabase_client.py (수정)

**추가되는 함수**:
```python
def fetch_all_draws() -> list:
    """전체 lotto_draws를 round 내림차순으로 반환.
    딥러닝 학습 시 사용. numbers를 list로 변환."""

# 기존 함수 유지: get_client(), fetch_recent_draws()
```

---

### 5.5 chains/analysis_chain.py (수정)

**변경 내용**: v2 - 딥러닝 예측 결과를 프롬프트에 통합

```
기존 프롬프트 구성:
  [Role] + [페이지 데이터] + [분석 규칙] → Gemini

변경 후 프롬프트 구성:
  [Role] + [페이지 데이터]
  + [ai_predictions에서 딥러닝 예측 로드]     ← 추가
  + [XGBoost feature importance 로드]         ← 추가
  + [Markov reasoning 로드]                   ← 추가
  + [RAG 유사 패턴 10건 검색]                ← 추가
  + [분석 규칙]
  → Gemini
```

**응답 형식**: 기존과 동일 `{trend, pattern, recommendation}` → **프론트엔드 수정 불필요**

---

### 5.6 chains/report_chain.py (수정)

**변경 내용**: v2 - 보고서에 딥러닝 예측 + 모델 성능 + 커스텀 룰 Hot 통합

**추가 데이터 소스**:
- `ai_predictions` → 4가지 예측 타입 + 앙상블 가중치
- `model_performance_log` → 모델별 평균 적중률
- `ai_custom_analyses` → Hot 상태인 룰 목록

---

### 5.7 rag/data_loader.py (수정)

**추가되는 함수**:
```python
def prediction_to_document(prediction, draw) -> Document:
    """ai_predictions 레코드를 RAG 문서로 변환.
    예측 번호 + 실제 번호 + 적중 수 + 모델 버전 + 추론 포함."""

# 기존 함수 유지: _compute_stats(), draw_to_document(), draws_to_documents()
```

---

### 5.8 js/config.js (수정)

**추가되는 설정**:
```javascript
// 기존
SUPABASE_CONFIG = { URL: '...', KEY: '...' }

// 추가
LANGCHAIN_CONFIG = {
    URL: 'http://localhost:8000',   // Python 서버 주소
    ENABLED: true,                  // LangChain 사용 여부
    TIMEOUT: 30000                  // 타임아웃 (ms)
}
```

---

### 5.9 js/common_v2.js (수정)

**추가되는 코드**: `window.AIProxy` 객체 (~50줄)

```javascript
window.AIProxy = {
    backend: 'auto',  // 'auto' | 'langchain' | 'edge'

    async invoke(config) {
        // 1. LangChain 서버 실행 확인 (health check, 2초 타임아웃)
        // 2. 실행 중이면 → Python 서버로 요청
        // 3. 실행 안 되면 → 기존 Edge Function으로 fallback
        // 4. 응답 형식은 동일: {trend, pattern, recommendation}
    },

    async getPredictions(targetRound) {
        // ai_predictions에서 딥러닝 예측 직접 조회
    },

    async getModelPerformance(limit) {
        // 모델 성능 요약 조회
    },

    async explain(number, targetRound) {
        // "왜 이 번호를 추천했어?" 설명 요청
    }
}
```

**기존 코드 수정점**:
```javascript
// executeAnalysis() 함수 내 Edge Function 호출 부분을 AIProxy로 대체:

// 변경 전 (common_v2.js 420줄):
const response = await window.supabaseClient.functions.invoke('analyze-lotto', {
    body: { context: prompt }
});

// 변경 후:
const response = await window.AIProxy.invoke({
    prompt,
    analysisType: config.analysisType,
    targetRound: config.targetRound,
    subjectRound: config.subjectRound,
    responseStyle: config.responseStyle || 'default'
});
```

**핵심**: `executeAnalysis()`의 호출 부분만 1줄 변경. 나머지 프롬프트 생성, 응답 파싱, UI 렌더링은 모두 기존과 동일하게 유지됨.

---

## 6. 기존 24개 분석 페이지 AI 적용 방법

### 6.1 HTML 파일 수정: 없음

```
★★★ 핵심: 24개 분석 HTML 파일은 수정하지 않습니다 ★★★

이유:
1. 모든 페이지가 window.AIAnalysis.executeAnalysis(config)를 호출
2. executeAnalysis()는 common_v2.js에 정의되어 있음
3. common_v2.js의 executeAnalysis() 내부만 수정 (Edge → AIProxy)
4. 응답 JSON 형식이 동일하므로 renderAnalysis()도 수정 불필요
```

### 6.2 AI가 적용된 24개 분석 페이지 목록

| # | 파일 | 분석 유형 | AI 변경 효과 |
|---|------|----------|-------------|
| 1 | ac_value.html | AC값 분석 | 딥러닝 근거로 "AC 7~10 구간 추천" 신뢰도 향상 |
| 2 | carryover.html | 이월수 분석 | 마르코프 Gap 확률로 이월 예측 강화 |
| 3 | composite_number.html | 합성수 분석 | XGBoost 피처에 합성수 비율 반영 |
| 4 | consecutive_number.html | 연번 분석 | 앙상블 확률로 연번 출현 가능성 제시 |
| 5 | custom_analysis.html | 커스텀 분석 | RAG로 유사 패턴 검색 + 딥러닝 근거 추가 |
| 6 | hot_cold.html | 핫/콜드 분석 | LSTM attention으로 핫 번호 근거 제시 |
| 7 | lotto_paper.html | 로또페이퍼 | 전체 앙상블 확률 기반 하이라이트 |
| 8 | low_high.html | 저/고 분석 | XGBoost의 is_low 피처 중요도로 근거 강화 |
| 9 | magic_square.html | 매직스퀘어 | 앙상블 확률로 매직스퀘어 패턴 분석 |
| 10 | missing.html | 미출현 분석 | 마르코프 Gap 확률이 핵심 근거로 작용 |
| 11 | multiple.html | 배수 분석 | XGBoost decade 피처로 배수 패턴 분석 |
| 12 | neighbor_number.html | 이웃 번호 | 동반 출현 피처로 이웃 번호 연관성 분석 |
| 13 | number_range.html | 번호 범위 | 번호대별 활성도 피처 반영 |
| 14 | odd_even.html | 홀짝 분석 | XGBoost is_odd 피처 + 홀짝 비율 예측 |
| 15 | prime_number.html | 소수 분석 | XGBoost is_prime 피처로 소수 출현 근거 |
| 16 | properties_matrix.html | 속성 행렬 | 전체 앙상블의 multi-label 확률 활용 |
| 17 | regression.html | 회귀 분석 | regression_details DB 연계 피처 활용 |
| 18 | square_number.html | 제곱수 분석 | 제곱수 번호의 개별 확률 제공 |
| 19 | stats_by_number.html | 번호별 통계 | 번호별 앙상블 확률 + 피처 중요도 표시 |
| 20 | tail_digit.html | 끝수 분석 | same_tail_active 피처로 끝수 활성도 분석 |
| 21 | tail_sum.html | 끝수합 분석 | 끝수합 관련 통계 + 딥러닝 예측 통합 |
| 22 | total_sum.html | 총합 분석 | LSTM의 총합 추세 학습 + sum_range 필터 |
| 23 | triangular_number.html | 삼각수 분석 | 삼각수 번호의 개별 확률 제공 |
| 24 | twin_number.html | 쌍둥이수 분석 | 동반 출현 피처로 쌍둥이수 관계 분석 |

### 6.3 페이지별 AI 분석 변경 전/후 비교 (예시: odd_even.html)

#### 변경 전 AI 분석 응답
```
"trend": "최근 10회차에서 홀수가 3~4개 출현하는 패턴이 지속되고 있습니다.
         짝수 우세 흐름에서 홀수 반등 가능성이 엿보입니다."

"recommendation": "다음 회차는 홀수 3개, 짝수 3개의 균형 조합을 권장합니다.
                  번호 7, 15, 23을 주목하세요."
```
→ **문제**: "번호 7, 15, 23을 주목" ← 근거가 없는 LLM 자유 생성

#### 변경 후 AI 분석 응답
```
"trend": "최근 10회차에서 홀수가 3~4개 출현하는 패턴이 지속되고 있습니다.
         딥러닝 앙상블(LSTM 0.35 + XGBoost 0.40 + Markov 0.25) 분석 결과,
         다음 회차 홀수 3개 출현 확률이 {{range:42.3%}}로 가장 높습니다."

"recommendation": "AI 앙상블이 추천하는 홀수 번호는 {{good:7}}(앙상블 확률 0.218,
                  XGBoost 근거: 최근 10회 출현빈도 30%, 현재 Gap 3),
                  {{good:15}}(마르코프 확률: 5회 미출현 시 출현율 28.5%),
                  {{good:23}}(LSTM attention: 1198회차 패턴 유사도 0.15)입니다.
                  {{warn:2}}와 {{warn:44}}는 제외를 권장합니다 (앙상블 확률 하위 10%)."
```
→ **개선**: 모든 추천/제외에 모델별 근거(확률, 피처, Gap) 첨부

### 6.4 분석 페이지 AI 연동 상세 흐름 (변경 후)

```
[odd_even.html 접속]
    │
    ▼
refreshAIAnalysis() 실행  ← 기존 코드 (수정 없음)
    │
    ├── allDrawData에서 최근 10회차 홀짝비 수집
    ├── customData = "최근 10회차 비율 흐름: 3:3, 4:2, ..."
    └── window.AIAnalysis.executeAnalysis(config) 호출  ← 기존 코드 (수정 없음)
            │
            ▼
        common_v2.js: executeAnalysis()
            │
            ├── generatePrompt(config) → 프롬프트 생성  ← 기존 코드 (수정 없음)
            │
            └── window.AIProxy.invoke(...)  ← ★ 이 부분만 변경 (1줄)
                    │
                    ├── [LangChain 서버 ON?]
                    │       │
                    │       ▼ YES
                    │   POST http://localhost:8000/api/analyze
                    │       │
                    │       ├── (1) ai_predictions 테이블에서 이번 회차 예측 로드
                    │       │       → "추천수: [7,15,23,...], 제외수: [2,44,...], 신뢰도: 75%"
                    │       │
                    │       ├── (2) XGBoost feature importance 로드
                    │       │       → "번호 7: recent_10_freq(0.30), current_gap(3), momentum(+0.1)"
                    │       │
                    │       ├── (3) Markov reasoning 로드
                    │       │       → "번호 15: 5회 미출현, 과거 동일 Gap에서 출현률 28.5%"
                    │       │
                    │       ├── (4) ChromaDB RAG 검색
                    │       │       → "유사 패턴: 1050회(홀3:짝3, 총합135), 1123회(홀4:짝2, 총합142)"
                    │       │
                    │       └── (5) 전체 컨텍스트 → Gemini LLM → JSON 생성
                    │               → {trend, pattern, recommendation}
                    │
                    └── [LangChain 서버 OFF?]
                            │
                            ▼ NO (fallback)
                        기존 Edge Function 호출 → 기존과 동일하게 작동
            │
            ▼
        renderAnalysis(response)  ← 기존 코드 (수정 없음)
            │
            ├── JSON 파싱 (기존 로직)
            ├── formatText()로 {{good:}} {{warn:}} 태그 변환 (기존 로직)
            └── 3섹션 HTML 렌더링: 흐름 진단 / 패턴 분석 / 필승 공략 (기존 로직)
```

---

## 7. DB 마이그레이션 SQL

### 7.1 신규 테이블

```sql
-- 모델 성능 추적 테이블
CREATE TABLE IF NOT EXISTS model_performance_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    round INTEGER NOT NULL,
    model_name VARCHAR(50) NOT NULL,
    prediction_type VARCHAR(50) NOT NULL,
    predicted_numbers INTEGER[],
    actual_numbers INTEGER[],
    hit_count INTEGER DEFAULT 0,
    precision_at_6 DECIMAL(5,4),
    precision_at_10 DECIMAL(5,4),
    weight_at_prediction DECIMAL(5,4),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(round, model_name, prediction_type)
);

CREATE INDEX idx_perf_round ON model_performance_log(round DESC);
CREATE INDEX idx_perf_model ON model_performance_log(model_name);
```

### 7.2 기존 테이블 확장

```sql
-- ai_custom_analyses 확장
ALTER TABLE ai_custom_analyses ADD COLUMN IF NOT EXISTS
    ai_evaluation JSONB DEFAULT '{}';
ALTER TABLE ai_custom_analyses ADD COLUMN IF NOT EXISTS
    evaluation_history JSONB DEFAULT '[]';
ALTER TABLE ai_custom_analyses ADD COLUMN IF NOT EXISTS
    is_ai_enabled BOOLEAN DEFAULT TRUE;

-- ai_predictions 확장
ALTER TABLE ai_predictions ADD COLUMN IF NOT EXISTS
    model_contributions JSONB DEFAULT '{}';
ALTER TABLE ai_predictions ADD COLUMN IF NOT EXISTS
    ensemble_weights JSONB DEFAULT '{}';
```

---

## 8. 실행 순서 및 의존 관계

### 8.1 구현 단계 (권장 순서)

```
Phase 0: DB 마이그레이션
  └── Supabase SQL Editor에서 위 SQL 실행

Phase 1: Python 백엔드 기반
  ├── config.py (수정)
  ├── requirements.txt (수정)
  ├── db/supabase_client.py (수정)
  └── pip install -r requirements.txt

Phase 2: 딥러닝 모델
  ├── models/__init__.py
  ├── models/lstm_model.py
  ├── models/xgboost_model.py
  ├── models/markov_model.py
  └── models/ensemble.py

Phase 3: 최초 모델 학습
  ├── scripts/train_models.py (신규)
  └── python scripts/train_models.py 실행

Phase 4: 체인 + RAG 업데이트
  ├── chains/analysis_chain.py (수정)
  ├── chains/explain_chain.py (신규)
  ├── chains/report_chain.py (수정)
  └── rag/data_loader.py (수정)

Phase 5: API 라우트 + 서버
  ├── routes/predictions.py (신규)
  ├── routes/performance.py (신규)
  ├── routes/explain.py (신규)
  ├── routes/pipeline.py (신규)
  └── main.py (수정)

Phase 6: 파이프라인
  └── pipeline/weekly_pipeline.py (신규)

Phase 7: 프론트엔드 연동
  ├── js/config.js (수정: LANGCHAIN_CONFIG 추가)
  └── js/common_v2.js (수정: AIProxy 추가 + executeAnalysis 1줄 변경)

Phase 8: 테스트
  ├── Python 서버 기동: python main.py
  ├── 브라우저에서 분석 페이지 접속
  └── LangChain 서버 ON/OFF 양쪽 테스트
```

### 8.2 의존 관계 다이어그램

```
[Phase 0: DB]
    │
    ▼
[Phase 1: Python 기반] ─────────────────────────┐
    │                                            │
    ▼                                            │
[Phase 2: 딥러닝 모델]                           │
    │                                            │
    ▼                                            │
[Phase 3: 모델 학습]                              │
    │                                            │
    ├─────────────┬──────────────┐               │
    ▼             ▼              ▼               │
[Phase 4]    [Phase 5]    [Phase 6]              │
 체인 수정    API 라우트    파이프라인             │
    │             │              │               │
    └─────────────┴──────────────┘               │
                  │                              │
                  ▼                              │
          [Phase 7: 프론트엔드 연동] ◄────────────┘
                  │
                  ▼
          [Phase 8: 통합 테스트]
```

### 8.3 Fallback 안전장치

```
★ LangChain 서버가 꺼져 있어도 기존 시스템은 정상 작동합니다.

AIProxy.invoke() 내부 로직:
  1. LangChain 서버 health check (2초 타임아웃)
  2. 응답 있으면 → LangChain 경로 (딥러닝 통합 분석)
  3. 응답 없으면 → 기존 Edge Function 경로 (Gemini만)
  4. 사용자 입장에서는 차이를 느끼지 못함 (같은 UI)

따라서 Phase 7까지 완료 전에도,
기존 시스템은 Phase 0~6 작업 중 영향 받지 않습니다.
```

---

## 부록: 파일별 코드량 예상

| 파일 | 신규/수정 | 예상 라인 수 |
|------|----------|-------------|
| models/lstm_model.py | 신규 | ~280줄 |
| models/xgboost_model.py | 신규 | ~210줄 |
| models/markov_model.py | 신규 | ~160줄 |
| models/ensemble.py | 신규 | ~270줄 |
| pipeline/weekly_pipeline.py | 신규 | ~300줄 |
| chains/explain_chain.py | 신규 | ~170줄 |
| chains/analysis_chain.py | 수정 | ~190줄 (기존 72줄 → 190줄) |
| chains/report_chain.py | 수정 | ~195줄 (기존 80줄 → 195줄) |
| routes/predictions.py | 신규 | ~70줄 |
| routes/performance.py | 신규 | ~100줄 |
| routes/explain.py | 신규 | ~25줄 |
| routes/pipeline.py | 신규 | ~90줄 |
| scripts/train_models.py | 신규 | ~30줄 |
| rag/data_loader.py | 수정 | +50줄 추가 |
| db/supabase_client.py | 수정 | +20줄 추가 |
| main.py | 수정 | +10줄 추가 |
| js/config.js | 수정 | +5줄 추가 |
| js/common_v2.js | 수정 | +50줄 추가 |
| **합계** | | **~2,215줄** |
