# 세션 재개 가이드 — AI 파이프라인 v2 (Phase 1~7 완료)

> 작성일: 2026-02-26
> 상태: **101개 테스트 전체 통과** ✅

---

## Claude Code 시작 방법

```powershell
# PowerShell 또는 명령 프롬프트에서 실행
claude --directory "C:\Users\psdet\Desktop\로또개발"
```

---

## 지금까지 완료된 작업

| Phase | 내용 | 상태 |
|-------|------|------|
| Phase 1 | 동반출현 행렬 + 모델 성적 DB 추적 | ✅ |
| Phase 2 | Meta-Learning 동적 가중치 (EWMA + Softmax) | ✅ |
| Phase 3 | GNN 경량 궁합 분석 | ✅ |
| Phase 4 | RL Monte Carlo 조합 생성기 (7,000회) | ✅ |
| Phase 5 | Anomaly Detection 게이트 | ✅ |
| Phase 6 | LLM 리포트 생성 (2차 Gemini 호출) | ✅ |
| Phase 7 | E2E 파이프라인 테스트 (101개 전체 통과) | ✅ |

---

## 새로 생성된 주요 파일들

```
supabase/functions/ai-lotto-analyst/
├── types.ts                          공통 타입 정의
├── PIPELINE_ARCHITECTURE.md          전체 아키텍처 문서
├── modules/
│   ├── cooccurrence.ts               동반출현 행렬 계산
│   ├── modelPerformance.ts           모델 성적 DB 추적
│   ├── metaLearning.ts               동적 가중치
│   ├── gnn.ts                        GNN 궁합 분석
│   ├── filters.ts                    필터 조건 & 완화
│   ├── rlCombinator.ts               RL Monte Carlo 생성기
│   └── anomalyDetection.ts           이상 탐지
└── __tests__/
    ├── cooccurrence.test.ts
    ├── modelPerformance.test.ts
    ├── metaLearning.test.ts
    ├── gnn.test.ts
    ├── rlCombinator.test.ts
    ├── anomalyDetection.test.ts
    └── e2e_pipeline.test.ts

supabase/migrations/
└── 20260226_model_predictions.sql    DB 마이그레이션
```

**수정된 파일:**
- `supabase/functions/ai-lotto-analyst/index.ts` — 파이프라인 통합
- `js/ai_deep_learning.js` — 프론트엔드 파이프라인 UI
- `ai_deep_learning.html` — 컨테이너 div 추가

---

## 남은 작업 (2번부터 진행)

### 2번: DB 마이그레이션 실행

1. **Supabase Dashboard** 접속: https://supabase.com/dashboard
2. 프로젝트 선택 → **SQL Editor** 클릭
3. 아래 SQL 복사 후 실행:

```sql
CREATE TABLE IF NOT EXISTS model_predictions (
    id           SERIAL PRIMARY KEY,
    round_number INT  NOT NULL,
    model_name   TEXT NOT NULL,
    predicted_top10 INT[] NOT NULL,
    actual_numbers  INT[] DEFAULT NULL,
    hit_count       INT  DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(round_number, model_name)
);

CREATE INDEX IF NOT EXISTS idx_model_predictions_round
    ON model_predictions(round_number DESC);
CREATE INDEX IF NOT EXISTS idx_model_predictions_model
    ON model_predictions(model_name);
```

또는 파일 경로에서 복사:
`supabase/migrations/20260226_model_predictions.sql`

---

### 3번: Edge Function 배포

> ⚠️ **주의**: 프론트엔드는 `analyze-lotto` 함수명으로 호출함.
> 로컬 폴더는 `ai-lotto-analyst`. 배포 시 이름 확인 필요.

```powershell
# Supabase CLI 로그인 (최초 1회)
supabase login

# 배포 (ai-lotto-analyst 폴더 → 서버에 deploy)
supabase functions deploy ai-lotto-analyst

# 만약 기존 analyze-lotto 함수가 있다면:
# supabase functions deploy analyze-lotto --import-map supabase/functions/ai-lotto-analyst/
```

**함수 이름 불일치 해결 방법:**
- 옵션 A: `js/ai_deep_learning.js`에서 URL의 `analyze-lotto` → `ai-lotto-analyst`로 변경
- 옵션 B: 배포 시 `--name analyze-lotto` 옵션으로 이름 지정

---

### 4번: 프로덕션 테스트

1. `ai_deep_learning.html` 브라우저에서 열기
2. 로또 분석 요청 → 응답에 `pipeline` 필드 확인
3. 모델 컨디션 바와 AI 리포트 카드가 표시되는지 확인

---

## 테스트 재실행 방법

```bash
# Deno 위치: C:\Users\psdet\.deno\bin\deno.exe
# PATH에 추가되어 있으면:
deno test supabase/functions/ai-lotto-analyst/__tests__/ --allow-hrtime

# 특정 파일만:
deno test supabase/functions/ai-lotto-analyst/__tests__/anomalyDetection.test.ts
deno test supabase/functions/ai-lotto-analyst/__tests__/e2e_pipeline.test.ts --allow-hrtime
```

---

## 주요 설정값 (변경 필요 시)

| 모듈 | 파라미터 | 현재값 |
|------|----------|--------|
| RL | 시뮬레이션 횟수 | 7,000회 |
| RL | 조기 종료 | 500회 연속 개선 없으면 |
| GNN | 보정 강도 | 0.2 |
| Anomaly | 연속번호 허용 | 3개 미만 |
| Anomaly | 등차수열 탐지 | 4개 이상 |
| Anomaly | 총합 정상 범위 | 60 ~ 220 |

---

## Claude Code에게 전달할 수 있는 컨텍스트 문구

다음 세션 시작 시 Claude Code에게 이렇게 말하면 됩니다:

```
C:\Users\psdet\Desktop\로또개발 프로젝트입니다.
supabase/functions/ai-lotto-analyst/ 에 AI 파이프라인 Phase 1~7이
이미 구현 완료되어 있고, 101개 테스트가 통과된 상태입니다.
PIPELINE_ARCHITECTURE.md 와 이 가이드를 참고해주세요.
이제 DB 마이그레이션과 Edge Function 배포를 진행하려 합니다.
```
