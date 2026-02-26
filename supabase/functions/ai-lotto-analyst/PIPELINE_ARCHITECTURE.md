# 고급 AI 파이프라인 아키텍처

## 개요

Supabase Edge Function `ai-lotto-analyst` 에 구현된 4단계 AI 파이프라인.
Gemini API 응답을 기반으로 Meta-Learning → GNN → RL → Anomaly Detection 순서로 처리한 뒤 최적 조합 10게임을 반환한다.

---

## 데이터 흐름

```
[클라이언트 요청]
    │  body: { context: prompt }
    ▼
[Edge Function: analyze 모드]
    │
    ├─ [Gemini API 호출]
    │   └─ 응답: { success, analysis: { number_probabilities, model_weights, ... },
    │              strategy, combinations }
    │
    ├─ [Phase 3] GNN 궁합 보정
    │   ├─ lotto_draws 테이블 조회 (최대 1,300회차)
    │   ├─ buildCoOccurrenceMatrix() → 45×45 동반출현 행렬
    │   ├─ buildGNNContext() → 이웃 평균 점수 1회 메시지 패싱
    │   ├─ applyGNNCorrection() → number_probabilities 보정
    │   │   finalScore[n] = geminiScore[n] × (1 + avgCompat[n] × 0.2)
    │   └─ pipeline.topCompatiblePairs 추가
    │
    ├─ [Phase 6] LLM 리포트 생성 (2차 Gemini 호출)
    │   └─ pipeline.aiReport 한국어 자연어 2~3문단
    │
    ├─ [Phase 2] Meta-Learning 동적 가중치
    │   ├─ model_predictions 테이블 조회 (최근 10회차)
    │   ├─ calcEWMAScore() → 지수 가중 이동평균
    │   ├─ softmax() → 확률 분포 정규화
    │   ├─ applyMinWeight() → 최소 5% 하한선
    │   └─ analysis.model_weights 교체 + pipeline.modelWeights 추가
    │
    ├─ [Phase 4] RL 조합 생성 (7,000회 Monte Carlo)
    │   ├─ 번호 점수 softmax → 선택 확률
    │   ├─ 비복원 샘플링 → 6개 번호 추출
    │   ├─ 보상 R = Σ점수 + 0.3×궁합 + 0.2
    │   ├─ 필터 미충족 → R=0 (폐기)
    │   ├─ 조기 종료 (500회 연속 개선 없으면 종료)
    │   ├─ 다양성 보장 (4개 이상 겹침 조합 배제)
    │   └─ 필터 완화 3단계 재시도 (sumRange±20 → 홀짝/저고 제거 → 총합만)
    │
    ├─ [Phase 5] Anomaly Detection 게이트
    │   ├─ 3연번 이상 → severity: medium
    │   ├─ 등차수열 4개+ → severity: high
    │   ├─ 간격 편차 극단 → severity: medium
    │   ├─ 10단위 편중 4개+ → severity: low
    │   ├─ 총합 <60 or >220 → severity: high
    │   ├─ 불합격 조합 폐기 → 최대 2회 재생성
    │   └─ pipeline.anomalyResults 기록
    │
    └─ [응답 반환]
        ├─ 기존 필드 (analysis, strategy, combinations, filter_stats) — 불변
        └─ 신규 필드 pipeline: {
               modelWeights, weightReasons,     ← Phase 2
               topCompatiblePairs,              ← Phase 3
               rlGenerated,                     ← Phase 4
               anomalyResults,                  ← Phase 5
               aiReport                         ← Phase 6
           }
```

---

## 모듈 구조

```
supabase/functions/ai-lotto-analyst/
├── index.ts                          메인 Edge Function
├── types.ts                          공통 타입 정의
├── modules/
│   ├── cooccurrence.ts     Phase 1   동반출현 행렬 계산
│   ├── modelPerformance.ts Phase 1   모델 성적 DB 추적
│   ├── metaLearning.ts     Phase 2   동적 가중치 (EWMA + Softmax)
│   ├── gnn.ts              Phase 3   경량 GNN 궁합 분석
│   ├── filters.ts          Phase 4   필터 조건 검사 & 완화
│   ├── rlCombinator.ts     Phase 4   RL Monte Carlo 조합 생성기
│   └── anomalyDetection.ts Phase 5   이상 조합 탐지 & 게이트
└── __tests__/
    ├── cooccurrence.test.ts           11개 테스트
    ├── modelPerformance.test.ts       11개 테스트
    ├── metaLearning.test.ts           11개 테스트
    ├── gnn.test.ts                    12개 테스트
    ├── rlCombinator.test.ts           11개 테스트
    ├── anomalyDetection.test.ts       23개 테스트
    └── e2e_pipeline.test.ts           14개 테스트  ← Phase 7
```

---

## DB 스키마 (신규)

```sql
-- model_predictions: 모델 예측 기록 및 적중률 추적
CREATE TABLE model_predictions (
    id           SERIAL PRIMARY KEY,
    round_number INT  NOT NULL,
    model_name   TEXT NOT NULL,
    predicted_top10 INT[] NOT NULL,
    actual_numbers  INT[] DEFAULT NULL,
    hit_count       INT  DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(round_number, model_name)
);
```

마이그레이션 파일: `supabase/migrations/20260226_model_predictions.sql`

---

## 설정 파라미터

| 모듈 | 파라미터 | 기본값 | 설명 |
|------|----------|--------|------|
| Meta-Learning | windowSize | 10 | 성적 참고 회차 수 |
| Meta-Learning | minWeight | 0.05 | 최소 가중치 하한선 |
| Meta-Learning | decayFactor | 2.0 | 지수 감쇠율 |
| GNN | gnnWeight | 0.2 | 궁합 보정 강도 |
| RL | simulations | 7,000 | 시뮬레이션 횟수 |
| RL | ALPHA | 0.3 | 궁합 점수 가중치 |
| RL | BETA | 0.2 | 필터 보너스 |
| Anomaly | maxConsecutive | 3 | 연속번호 허용 임계 |
| Anomaly | minArithmetic | 4 | 등차수열 탐지 임계 |
| Anomaly | sumMin/sumMax | 60/220 | 총합 정상 범위 |

---

## 롤백 전략

각 모듈은 독립적이며 삭제해도 기존 동작이 즉시 복원된다.

| Phase | 롤백 방법 |
|-------|-----------|
| Phase 2 | `metaLearning.ts` 삭제 → 기본 균등 가중치 사용 |
| Phase 3 | `gnn.ts` 삭제 → GNN 보정 스킵 |
| Phase 4 | `rlCombinator.ts` 삭제 → Gemini 조합 직접 사용 |
| Phase 5 | `anomalyDetection.ts` 삭제 → RL 결과 그대로 반환 |
| Phase 6 프론트 | `renderPipelineInfo()` 제거, HTML 컨테이너 제거 |

---

## 테스트 실행

```bash
# Deno 설치 (Windows PowerShell)
irm https://deno.land/install.ps1 | iex

# 단위 테스트 (모듈별)
deno test supabase/functions/ai-lotto-analyst/__tests__/cooccurrence.test.ts
deno test supabase/functions/ai-lotto-analyst/__tests__/metaLearning.test.ts
deno test supabase/functions/ai-lotto-analyst/__tests__/gnn.test.ts
deno test supabase/functions/ai-lotto-analyst/__tests__/rlCombinator.test.ts
deno test supabase/functions/ai-lotto-analyst/__tests__/anomalyDetection.test.ts

# E2E + 성능 벤치마크
deno test supabase/functions/ai-lotto-analyst/__tests__/e2e_pipeline.test.ts --allow-hrtime

# 전체 테스트 (93개)
deno test supabase/functions/ai-lotto-analyst/__tests__/ --allow-hrtime
```
