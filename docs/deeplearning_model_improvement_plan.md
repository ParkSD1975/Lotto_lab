# 딥러닝 모델 로직 변경 계획

> 작성일: 2026-04-20  
> 최종 수정: 2026-04-26 (Phase 0 응급 처치 + GNN 실제 GAT 구현 + 전 모델 감사 완료)  
> 목적: AI 강력 추천 5 적중률 향상, AI 제외수 제외율 향상, 앙상블 재설계, 필터 범위 Supabase 연동

---

## Phase 0 — 응급 처치 (즉시 실행, 코드 감사 결과)

> 코드 감사(2026-04-26)에서 발견된 **치명적 버그 3건** 및 **회차별 예측 변화 부재** 문제.  
> Phase 1 이전에 반드시 수정해야 하는 항목들. ✅ 완료 표시된 항목은 이미 수정됨.

### Phase 0.1 — Autoencoder `predict_exclusions()` return 누락 수정 ✅

**버그**: `predict_exclusions()` 함수가 모델을 로드하고 `return` 없이 종료 → 항상 `None` 반환.  
앙상블의 `ae_exclusions = self.models["autoencoder"].predict_exclusions(draws)` 호출이 **항상 빈 딕셔너리**처럼 동작 → 제외 패널티 전혀 적용 안 됨.

**실제 제외 로직**은 `predict()` 함수 내 `return` 문 **이후**(=dead code)에 존재하여 절대 실행되지 않았음.

**수정 내용** (`langchain-backend/models/autoencoder_model.py`):
- `predict_exclusions()` 내에 실제 복원오차 계산 로직 이전
- dead code(predict 함수 return 이후 중복 블록) 삭제

---

### Phase 0.2 — GNN 임시 비활성화 → Phase 0.5에서 실제 GAT 구현으로 대체 ✅

**버그**: `gnn_model.py`의 `GNNTrainer`는 실제 그래프 신경망(GNN)이 아님.  
45×45 동반출현 카운트 행렬을 합산하는 단순 집계 로직 — PyTorch가 import되어 있을 뿐 사용되지 않음.  
앙상블에 `gnn: 0.15` 가중치로 포함 → 정보량이 없는 신호가 예측에 15% 기여.

**1단계 수정** (`langchain-backend/models/ensemble.py`): `DISABLED_MODELS = {"gnn"}` 로 임시 비활성화  
→ **Phase 0.5에서 실제 GAT 구현 후 해제됨** (아래 참조)

---

### Phase 0.5 — GNN 실제 Graph Attention Network 구현 ✅

**구현 내용** (`langchain-backend/models/gnn_model.py`):

| 항목 | 내용 |
|------|------|
| 아키텍처 | 2-layer Graph Attention Network (Veličković et al., 2018) |
| 노드 | 45개 번호 (1~45) |
| 엣지 | 동반출현 횟수 가중치 (대칭 정규화) |
| 노드 피처 | 10차원: 출현빈도(3윈도우), GAP(현재/평균/편차), 핫스트릭, 홀짝, 고저, 위치 |
| GAT Layer 1 | 10 → 64 차원 (4-head attention, dropout=0.3) |
| GAT Layer 2 | 64 → 32 차원 (2-head attention, dropout=0.21) |
| Classifier | 32 → 32 → 1 (per-node 출현 로짓) |
| Loss | BCEWithLogitsLoss (pos_weight=6.5, 6양성/39음성 불균형 보정) |
| Optimizer | Adam (lr=1e-3, weight_decay=1e-4) + ReduceLROnPlateau |
| Early stopping | patience=25 epoch |
| 학습 파라미터 | 4,161개 |

**후속 조치**:
- `DISABLED_MODELS = set()` (빈 집합) — GNN 비활성화 해제
- `ensemble_weights.json`: gnn=0.15 복원 (전체 합계 1.0)
- `TASK_WEIGHTS`: recommend(gnn=0.10), filter(gnn=0.15), exclude(gnn=0.07)로 용도별 가중치 추가
- `default_weights`: xgboost=0.25, lstm=0.20, transformer=0.18, gnn=0.15, cnn=0.10, markov=0.08, autoencoder=0.04

---

### Phase 0.3 — XGBoost 피처 실질 변화 시그널 추가 ✅

**문제**: 기존 25개 피처 중 `freq_diff`, `gap_position`, `momentum_dup` 3개가 항상 `0.0` 더미값.  
회차가 바뀌어도 이 피처들이 변하지 않아 **인접 회차 간 예측값이 거의 동일**한 현상 발생.

> 참고: `past_draws = draws[target_idx + 1:]` 코드(49번 줄)는 **정상** (draws가 최신순이므로 과거 데이터만 사용).  
> 데이터 누수 없음 — 이전 감사의 오진이었음.

**수정 내용** (`langchain-backend/models/xgboost_model.py`):
| 피처명 | 이전 | 이후 |
|--------|------|------|
| `freq_delta` | 항상 `0.0` | 최근 5회 출현수 − 직전 5회 출현수 (빈도 가속도) |
| `gap_acceleration` | 항상 `0.0` | 현재 GAP − 직전 GAP (GAP 증가 속도) |
| `hot_streak` | 항상 `0.0` | 직전 연속 출현 회차 수 (STR 패턴) |

- 피처명도 `freq_diff/gap_position/momentum_dup` → `freq_delta/gap_acceleration/hot_streak`로 변경
- 모델 재학습 필요 (기존 `xgboost_models.pkl` 피처 벡터 크기는 동일 25개, 순서 그대로)

---

### Phase 0.4 — task-specific 가중치 매트릭스 (신규 항목)

**문제**: 현재 앙상블이 **번호 추천 / 필터 분석 / 제외수** 세 용도에 동일한 가중치 적용.  
- 번호 추천 → LSTM·XGBoost가 강점 (시계열 패턴, 이진 분류)
- 필터 분석 → Transformer·Markov가 강점 (통계 분포, 전이 패턴)
- 제외수 판별 → Autoencoder가 강점 (비정상 패턴 복원오차)

**설계**:
```python
# ensemble.py 또는 deep_analysis_v3.py에 추가
TASK_WEIGHTS = {
    "recommend": {  # 번호 추천 (Top 5/20)
        "xgboost": 0.35, "lstm": 0.30, "cnn": 0.10,
        "transformer": 0.15, "markov": 0.10, "autoencoder": 0.00, "gnn": 0.00
    },
    "filter": {     # 필터 범위 예측
        "xgboost": 0.15, "lstm": 0.15, "cnn": 0.10,
        "transformer": 0.30, "markov": 0.25, "autoencoder": 0.05, "gnn": 0.00
    },
    "exclude": {    # 제외수 10개 선출
        "xgboost": 0.20, "lstm": 0.20, "cnn": 0.10,
        "transformer": 0.10, "markov": 0.10, "autoencoder": 0.30, "gnn": 0.00
    }
}
```

- `predict()` 호출 시 `task="recommend"|"filter"|"exclude"` 파라미터로 가중치 선택
- 추후 Phase 1.1 동적 가중치와 병합 시 `task_base_weight × performance_multiplier`로 조합
- **구현 위치**: `deep_analysis_v3.py` 앙상블 호출 구간

---

## 사전 확정 사항

| 항목 | 결정 |
|------|------|
| LLM 호출 주기 | 매 회차 자동 실행 — 단, 주 1회(매주 토요일 추첨 후)만 |
| 모델별 필터 예측 출처 | AI 프리미엄 전략 리포트에 적용된 모델별 필터 값을 기준으로 확인 |
| 회귀 분석 페이지 위치 | `ai_deep_learning.html` 내 회귀 분석 탭 |
| 자동 학습 주기 | 매주 토요일 추첨 후 회차 업데이트 시 자동 재학습 |

---

## 문제 1 — AI 강력 추천 5 적중률이 너무 낮음

### 현상
- 7개 모델(LSTM, XGBoost, CNN, Transformer, Markov, Autoencoder, GNN)의 예측 결과를 단순 가중치 합산으로 Top 5 선출
- 고정 가중치 사용 → 최근 성과가 반영되지 않음
- 모델별 강점 영역(번호 대역, 연속성, 주기성 등) 미분리

### 원인
- `model_predictions` 테이블에 `hit_count`가 누적되고 있으나, 앙상블 가중치에 실제로 피드백되지 않음
- 최근 N회차 적중률로 동적 가중치 재계산 로직 없음

### Phase 1 — 동적 가중치 앙상블

#### Phase 1.1 — 모델별 최근 적중률 기반 동적 가중치 계산
```sql
-- 최근 20회차 기준 모델별 적중률 집계
SELECT model_name,
       AVG(hit_count) AS avg_hit,
       COUNT(*) AS rounds
FROM model_predictions
WHERE round_number >= (SELECT MAX(round_number) FROM winning_numbers) - 20
GROUP BY model_name;
```

- **2단계 정규화 공식** (최솟값 5% 보정 후 합계 100% 보장):
  ```python
  # 1단계: 성과 기반 가중치 계산
  raw_weights = {m: avg_hit[m] / sum(avg_hit.values()) for m in models}

  # 2단계: 최솟값 5% 적용 + 재정규화
  MIN_W = 0.05
  adjusted = {m: max(w, MIN_W) for m, w in raw_weights.items()}
  total = sum(adjusted.values())  # 보정으로 1.0 초과 가능
  final_weights = {m: w / total for m, w in adjusted.items()}  # 합계 1.0 재보장
  ```
- 최솟값 보정: 적중 0인 모델도 최소 5% 가중치 유지 (학습 기회 보존)
- 적용: `langchain-backend/routes/deep_analysis_v3.py` 앙상블 호출 직전 동적으로 가중치 벡터 생성

#### Phase 1.2 — 출력 보정 루프 (GAP 구간별 이중 처리)

**GAP 처리 정책** — Phase 2.1과 충돌 없이 구간 분담:

| GAP 구간 | 해석 | 처리 |
|----------|------|------|
| 1~7회 (평균 주기 이하) | 최근 출현, 냉각기 | 중립 (조정 0) |
| 8~18회 (평균 주기 1.5~2.5배) | **출현 임박** (STR 패턴) | ✅ 가산점 (최대 +0.3) |
| 19회+ (평균 주기 2.5배 초과) | **극냉각** (패턴 이탈) | ❌ Phase 2.1에서 제외 처리 |

```python
def get_gap_adjustment(gap, avg_period=7.5):
    if gap < avg_period:
        return 0.0                                   # 중립
    elif gap < avg_period * 2.5:                     # 8~18회
        boost = (gap - avg_period) / (avg_period * 1.5)
        return +boost * 0.3                          # 최대 +0.3 가산
    else:                                            # 19회+
        return 0.0                                   # Phase 2.1에서 제외 처리
```

- Top 5 선출 후, 직전 3회차에서 모두 등장한 번호는 패널티 부여 (과적합 방지)
- 각 번호에 `get_gap_adjustment()` 가산점 부여 후 재정렬하여 최종 Top 5 확정

#### Phase 1.3 — 회차별 성과 자동 기록
- 추첨 후 당첨번호와 예측 Top 5를 자동 비교
- `model_predictions.hit_count` 업데이트 (기존 구조 활용)
- 매주 토요일 자동 실행 (회차 업데이트 트리거)

---

## 문제 2 — AI 제외수 10 제외율이 낮고 1~2개 번호가 계속 당첨에 등장

### 현상
- AI 제외수 10개 중 실제 당첨번호가 1~2개 지속 포함됨
- 현재 제외수 선출 로직이 추천수 역방향(낮은 점수 순) 단순 정렬

### 원인
- 번호별 "제외 안전도" 지표 없음
- 특정 번호가 주기적으로 등장하는 패턴(STR, GAP) 미반영
- 제외수 성과 별도 추적 테이블 없음

### Phase 2 — 전용 제외 분류기

#### Phase 2.1 — 제외 안전도 스코어 계산

**GAP 구간 기준** (Phase 1.2와 상호 배타):
- GAP 1~7회: 최근 출현 → 당분간 안 나올 가능성 (**제외 안전**)
- GAP 8~18회: **Phase 1.2에서 추천 가산점 처리 영역 → 제외 후보에서 제외**
- GAP 19회+ (극냉각): 패턴에서 이탈한 "죽은 번호" 가능성 → **제외 권장**

각 번호에 대해 다음을 종합하여 제외 안전도 계산:
- 최근 10회차 출현 여부 (최근 출현 → 냉각기 → 제외 안전)
- GAP 19회+ 여부 (극냉각 → 제외 권장)
- STR 연속 출현 중인 번호 (연속 중 → 다음 회차 미출현 확률 높음 → 제외 안전)
- 앙상블 점수 하위 20개 중 위 조건 충족 번호만 최종 10개 선출

```python
def exclude_safety_score(num, gap, recent10_hit, str_count, ensemble_score):
    if gap >= 19:
        return 1.0  # 극냉각 → 최우선 제외
    if recent10_hit:
        return 0.7  # 최근 출현 → 제외 안전
    if str_count >= 2:
        return 0.6  # 연속 출현 중 → 다음 회차 제외 안전
    if 8 <= gap <= 18:
        return 0.0  # Phase 1.2 영역 → 제외 금지
    return 0.3  # 일반
```

#### Phase 2.2 — 제외수 성과 추적
```sql
-- 제외수 성과 추적 컬럼 추가 (deep_analysis_history 활용)
-- analysis_data JSONB 내 exclude_hit_count 필드 추가
{
  "top_5": [...],
  "exclude_10": [...],
  "exclude_hit_count": 0,   -- 제외수 중 실제 당첨번호 포함 수 (0이 최선)
  "exclude_accuracy": 1.0   -- (10 - exclude_hit_count) / 10
}
```

#### Phase 2.3 — 제외수 자동 피드백

**기준선 계산** (무작위 대비 상대 평가):
- 무작위 기대 제외 적중수 = 10 × (6/45) ≈ **1.33개**
- 무작위 기대 `exclude_accuracy` ≈ **0.867**
- 목표: 최근 10회차 평균 `exclude_accuracy` ≥ **0.90** (무작위 대비 +3%p 이상)

```
- 추첨 후 exclude_hit_count 자동 업데이트
- 최근 10회차 평균 exclude_accuracy < 0.90 → 제외 안전도 스코어 파라미터 자동 조정
- 최근 10회차 평균 exclude_accuracy < 0.867 (무작위 이하) → 경고 알림 (운영자 확인)
```

---

## 문제 3 — 앙상블 로직 재설계 (LLM 판단 레이어 삽입)

### 현상
- 7개 모델 결과를 단순 가중치 합산(산술 평균)으로만 앙상블
- 회차별 특수 패턴(연속번호 급증, 끝수 쏠림 등) 미반영
- 역사적 유사 회차 데이터를 판단에 활용하지 않음

### Phase 3 — LLM 보정 앙상블

#### Phase 3.1 — 컨텍스트 패키징

**유사 과거 회차 검색 알고리즘** (하이브리드 코사인 유사도):

두 벡터를 7:3 가중 평균하여 상위 5개 유사 회차 선출:

```python
def find_similar_rounds(current_round, top_k=5):
    # 1. GAP 벡터 (45차원): 각 번호의 현재 GAP
    gap_vec = [current_gap[n] for n in range(1, 46)]

    # 2. 통계 지표 벡터 (8차원): 필터 지표
    stat_vec = [
        total_sum, tail_sum, ac_value,
        odd_count, high_count, consecutive_max,
        hot_count, missing_count
    ]

    # 정규화 (Min-Max 또는 Z-score)
    gap_vec_norm = normalize(gap_vec)
    stat_vec_norm = normalize(stat_vec)

    scores = []
    for past_round in all_past_rounds:
        gap_sim = cosine_similarity(gap_vec_norm, past_round.gap_vec)
        stat_sim = cosine_similarity(stat_vec_norm, past_round.stat_vec)
        combined = 0.7 * gap_sim + 0.3 * stat_sim  # GAP 중심 가중
        scores.append((past_round, combined))

    return sorted(scores, key=lambda x: -x[1])[:top_k]
```

**선정 근거**:
- GAP 벡터(70%): 현재 번호의 냉각/과열 분포가 유사한 회차를 찾아 다음 당첨 패턴 참고
- 통계 지표(30%): 필터 지표 수준(총합/홀짝 등)이 유사한 맥락 보강
- 구현 난이도 낮음 (pgvector 불필요, 단순 SQL + numpy)

**LLM 입력 구성**:
```json
{
  "current_round": 1234,
  "ensemble_top15": [7, 12, 23, ...],
  "recent_5_results": [[1,5,12,...], ...],
  "gap_status": {"7": 3, "23": 8, ...},
  "str_status": {"12": 2, ...},
  "similar_historical_rounds": [
    {"round": 987, "similarity": 0.92, "numbers": [...], "next_round_hit": [...]},
    {"round": 654, "similarity": 0.88, "numbers": [...], "next_round_hit": [...]}
  ],
  "model_weights": {"LSTM": 0.18, "XGBoost": 0.22, ...}
}
```
- `next_round_hit`: 유사 회차 **다음 회차**의 당첨번호 (LLM이 패턴 참고용으로 사용)

#### Phase 3.2 — LLM 보정 실행 (LangChain 체인 래핑)

**LangChain 체인 구조** — 기존 `langchain-backend/chains/` 패턴에 맞춰 구현:

```python
# langchain-backend/chains/llm_correction_chain.py (신규)
from langchain.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import JsonOutputParser

class LLMCorrectionChain:
    def __init__(self, llm):
        self.llm = llm  # 기존 Gemma 4 LLM 인스턴스 주입
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", LLM_CORRECTION_SYSTEM_PROMPT),
            ("human", "{context_json}")
        ])
        self.parser = JsonOutputParser()
        self.chain = self.prompt | self.llm | self.parser

    async def invoke(self, context: dict) -> dict:
        return await self.chain.ainvoke({"context_json": json.dumps(context)})
```

- 입력: Phase 3.1 컨텍스트 JSON
- 출력: `{"top_5": [...], "exclude_10": [...], "reasoning": "..."}`
- 호출 시점: 매주 토요일 추첨 후 회차 업데이트 시 자동 1회
- 비용 통제: 입력 토큰 최소화를 위해 컨텍스트를 압축 포맷으로 전달
- LLM 실패 시 fallback: 앙상블 원본(pre-LLM) 결과 사용

#### Phase 3.3 — 하이브리드 결과 저장
```sql
-- deep_analysis_history.analysis_data JSONB 구조 확장
{
  "top_5": [7, 12, 23, 34, 41],           -- LLM 보정 최종 결과
  "top_5_pre_llm": [7, 12, 23, 35, 42],  -- LLM 보정 전 앙상블 원본
  "exclude_10": [...],
  "llm_reasoning": "GAP 8 상태인 23번 유지, STR 연속 중인 35번 34번으로 교체...",
  "llm_called": true,
  "llm_backend": "langchain",
  "llm_model": "gemma-2-4b"
}
```

#### Phase 3.4 — 자기 개선 루프 (알림 전용, 자동 비활성화 금지)
- 추첨 후 LLM 보정 결과 vs 앙상블 원본 결과 성과 비교
- LLM 보정이 최근 5회차 연속 성과 저하 시 → **운영자 알림만 발송** (자동 비활성화는 수행하지 않음)
- 시스템이 핵심 판단 레이어(LLM)를 자동으로 끄는 구조는 위험하므로, 알림 수신 후 운영자가 수동으로 비활성화 여부 결정
- 컨텍스트 품질 개선 방향 로그 기록 (`llm_correction_audit` 테이블 또는 파일 로그)

---

## 문제 4 — 필터 범위 페이지 통일 (기존 분석 결과 재활용)

### 현상
- `ai_deep_learning.html`의 **필터 분석 탭**에서 이미 7개 모델별 필터 예상 범위를 계산·표시 중
  (백엔드: `deep_analysis_v3.py` → `range_analysis` 생성 → `deep_analysis_history.analysis_data.range_analysis`에 저장)
- 그러나 `filter.html`, `custom_analysis.html`, `ai_combination.html`은 이 데이터를 **읽지 않음**
- 각 페이지가 독자적으로 필터 기본값을 관리하여 **데이터 출처 분산**

### 원칙 — 기존 데이터 재활용
**신규 DB 테이블 불필요.** `deep_analysis_history.analysis_data.range_analysis` 하나를 단일 출처(Single Source of Truth)로 삼고 4개 페이지가 동일한 데이터를 읽어 표시.

```
deep_analysis_history.analysis_data.range_analysis
├── ai_deep_learning.html (필터 분석 탭)     ← 현재 표시 중 (유지)
├── ai_deep_learning.html (회귀 분석 탭)     ← 신규 연동
├── filter.html                              ← 신규 연동
├── custom_analysis.html                     ← 신규 연동
└── ai_combination.html                      ← 신규 연동
```

### Phase 4 — FilterService 통일 API 추가 및 UI 반영

#### Phase 4.1 — FilterService에 `loadAIRanges()` API 추가

```javascript
// js/filter/FilterService.js 에 추가
async loadAIRanges(targetRound = null) {
  let query = window.supabaseClient
    .from('deep_analysis_history')
    .select('target_round, analysis_data')
    .order('target_round', { ascending: false })
    .limit(1);

  if (targetRound) query = query.eq('target_round', targetRound);

  const { data, error } = await query.maybeSingle();
  if (error || !data) return null;

  const analysis = typeof data.analysis_data === 'string'
    ? JSON.parse(data.analysis_data)
    : data.analysis_data;

  // range_analysis 구조: { sum: {range, model_expectations}, odd: {...}, ... }
  return {
    target_round: data.target_round,
    ranges: analysis?.range_analysis || analysis?.analysis?.range_analysis || null
  };
}
```

- LLM 보정 결과가 `top_5`/`exclude_10`만 변경하는 경우 `range_analysis`는 앙상블 원본 그대로 사용
- 캐시: 5분 이내 동일 회차 호출 시 로컬 캐시 반환 (Supabase 왕복 감소)

#### Phase 4.2 — 4개 페이지 UI 반영

| 페이지 | 파일 | 적용 위치 |
|--------|------|-----------|
| 필터 분석 | `filter.html` + `filter_dashboard.js` | 각 필터 항목 min/max 기본값 옆 AI 추천 뱃지 |
| 회귀 분석 | `ai_deep_learning.html` 회귀 탭 | 회귀 행 min/max 입력 기본값 |
| 커스텀 분석 | `custom_analysis.html` | 필터 범위 추천값 표시 |
| 조합 생성 | `ai_combination.html` | 조합 필터 범위 기본값 |

**공통 UI 패턴**:
- 기존 수동 입력값 옆에 `AI 추천: X ~ Y` 뱃지 표시
- 뱃지 클릭 시 AI 추천값으로 자동 입력 (클릭 = 명시적 승인)
- 뱃지 우측에 출처 라벨: `(앙상블 기반)` 또는 `(LLM 보정)`

#### Phase 4.3 — 추첨 후 필터 범위 정확도 검증 (JSONB 확장)

**별도 테이블 대신 `deep_analysis_history.analysis_data.range_analysis_validation` 필드 추가**:

```json
{
  "range_analysis": { ... },
  "range_analysis_validation": {
    "validated_at": "2026-04-26T10:00:00Z",
    "actual_values": { "sum": 148, "odd": 3, "ac": 8, ... },
    "in_range": { "sum": true, "odd": true, "ac": false, ... },
    "accuracy": 0.85
  }
}
```

- 매주 토요일 추첨 후 자동 업데이트
- 별도 테이블 신설 불필요 (기존 JSONB 컬럼 확장만)
- 필터 범위 정확도 통계를 대시보드에 추가 표시

---

## 구현 우선순위

| 순서 | Phase | 작업 내용 | 예상 공수 | 상태 |
|------|-------|-----------|-----------|------|
| 0 | **0.1** | Autoencoder return 누락 수정 | 0.5일 | ✅ 완료 |
| 0 | **0.2** | GNN 가중치 0 비활성화 + default_weights 재배분 | 0.25일 | ✅ 완료 |
| 0 | **0.3** | XGBoost 더미 피처 → 실제 변화 시그널 교체 | 0.5일 | ✅ 완료 |
| 0 | **0.4** | task-specific 가중치 매트릭스 설계 | 0.5일 | 🔲 대기 |
| 1 | 1.1 | 동적 가중치 계산 로직 + 2단계 정규화 (Python) | 1일 | 🔲 대기 |
| 2 | 1.2 | 출력 보정 루프 (GAP 구간별 이중 처리) | 0.5일 | 🔲 대기 |
| 3 | 2.1 | 제외 안전도 스코어 + 제외수 선출 개선 | 1일 | 🔲 대기 |
| 4 | 2.2 | 제외수 성과 추적 (JSONB 필드 추가) | 0.5일 | 🔲 대기 |
| 5 | 4.1 | `FilterService.loadAIRanges()` API (기존 테이블 재활용) | 0.5일 | 🔲 대기 |
| 6 | 4.2 | 4개 페이지 UI 반영 (필터·회귀·커스텀·조합) | 2일 | 🔲 대기 |
| 7 | 3.1 | 유사 회차 검색 (GAP+통계 하이브리드) + 컨텍스트 패키징 | 1일 | 🔲 대기 |
| 8 | 3.2 | LangChain 체인 래핑 (`llm_correction_chain.py`) | 1일 | 🔲 대기 |
| 9 | 3.3~3.4 | 하이브리드 저장 + 자기개선 루프 (알림 전용) | 1일 | 🔲 대기 |
| 10 | 1.3, 2.3, 4.3 | 추첨 후 자동 피드백 통합 (JSONB 검증 필드) | 1일 | 🔲 대기 |

**총 예상 공수: 약 11일 (Phase 0 포함, 병렬 작업 시 7~8일)**
- Phase 0: 긴급 버그 3건 수정 → 기존 앙상블 정확도 즉시 향상 기대
- Phase 4의 별도 테이블 생성 작업 제거로 0.5일 단축
- 기존 `deep_analysis_history` 활용으로 마이그레이션 리스크 감소

### Phase 1.2 재설계 — GAP 보정 방식 변경

> 기존 Phase 1.2는 딥러닝 모델 출력을 **휴리스틱으로 덮어쓰는** 구조(문제점: 모델이 배운 것을 수작업 규칙이 무효화).  
> 수정: GAP 가산점을 별도 score로 계산하되 **앙상블 점수와 가중 혼합(blend)**하는 방식으로 변경.

```python
# 기존 (문제)
final_probs[n] += get_gap_adjustment(gap)   # 임의 덧셈 → 스케일 불일치

# 변경 후 (안전한 혼합)
gap_score = get_gap_score_normalized(gap)   # 0~1 정규화된 GAP 점수
final_probs[n] = 0.85 * ensemble_score[n] + 0.15 * gap_score  # 85:15 혼합
```
- GAP 보정 비중 최대 15%로 제한 → 모델 예측 주도권 유지
- `get_gap_score_normalized()`: GAP 구간별 점수를 0~1로 Min-Max 정규화

---

## 자동화 트리거 구조

```
[매주 토요일 추첨 완료]
         │
         ▼
[회차 업데이트 감지]
         │
         ├─► 모델 재학습 (LSTM, XGBoost, CNN, Transformer, Markov, Autoencoder, GNN)
         │
         ├─► 앙상블 실행 → 동적 가중치 계산 (Phase 1.1, 2단계 정규화)
         │
         ├─► GAP 구간별 출력 보정 (Phase 1.2)
         │     - 8~18회: 출현 임박 가산점
         │     - 19회+: 극냉각 (Phase 2.1 제외 대상)
         │
         ├─► 필터 범위 예측 → deep_analysis_history.range_analysis (기존 JSONB 활용)
         │
         ├─► 유사 과거 회차 검색 (Phase 3.1, GAP+통계 하이브리드)
         │
         ├─► LangChain 체인 LLM 보정 실행 (Phase 3.2) → 보정 결과 저장 (Phase 3.3)
         │
         ├─► 직전 회차 성과 검증:
         │     - model_predictions.hit_count 업데이트
         │     - exclude_hit_count 업데이트 (JSONB)
         │     - range_analysis_validation 업데이트 (JSONB)
         │     - LLM 보정 성과 저하 시 알림만 발송 (Phase 3.4, 자동 비활성화 없음)
         │
         └─► 대시보드 통계 갱신
```

---

## 관련 파일 목록

| 파일 | 역할 |
|------|------|
| `langchain-backend/routes/deep_analysis_v3.py` | 앙상블, 동적 가중치(2단계 정규화), GAP 구간별 보정 |
| `langchain-backend/chains/llm_correction_chain.py` (신규) | LangChain 체인으로 LLM 보정 래핑 |
| `langchain-backend/models/ensemble.py` | 가중치 계산 로직 업데이트 |
| `js/filter/FilterService.js` | `loadAIRanges()` API 추가 (deep_analysis_history 재활용) |
| `js/filter_dashboard.js` | 필터 탭 AI 추천 범위 표시 |
| `js/ai_deep_learning.js` | 회귀 탭 AI 추천 범위 표시 |
| `ai_deep_learning.html` | 회귀 분석 탭 UI (필터 범위 기본값) |
| `filter.html` | 필터 항목 AI 추천 뱃지 |
| `custom_analysis.html` | 커스텀 필터 AI 추천 범위 |
| `ai_combination.html` | 조합 필터 AI 범위 기본값 |

**DB 변경사항** — 신규 테이블 없음. `deep_analysis_history.analysis_data` JSONB 확장만:
- `exclude_hit_count`, `exclude_accuracy` 추가 (Phase 2.2)
- `top_5_pre_llm`, `llm_reasoning`, `llm_called`, `llm_backend`, `llm_model` 추가 (Phase 3.3)
- `range_analysis_validation` 추가 (Phase 4.3)
