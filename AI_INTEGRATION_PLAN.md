# 로또 AI Q&A 통합 개선 설계서
> 작성일: 2026-03-07
> 목적: 전 분석 페이지 AI Q&A 품질 통일 및 Supabase/백엔드 완전 활용

---

## 1. 현재 문제 요약

### 근본 원인
- 23개 분석 페이지가 **각자 JS에서 기본통계만 텍스트로 조립** → Python 백엔드 전달
- AI(Gemini)가 받는 데이터: 평균, 표준편차, 이동평균뿐
- **전이행렬, 조건부확률, streak/gap, 연속패턴** 등 계산 불가
- 결과: "AC값이 높게 유지되었으므로..." 같은 근거 없는 답변 반복

### 증상 예시
```
질문: "AC=8이 연속 4번 나왔을 때 다음 확률 순위"
현재 답변: 전체 평균 7.82... (질문과 무관한 일반 통계)
올바른 답변: AC=8 이후 전이확률 - AC8:36.2%, AC7:24.1%, AC9:18.3%...
```

---

## 2. 목표 아키텍처

```
[23개 분석 페이지]
     │ AIProxy.smartQuery({ question, analysisType, targetRound })
     ▼
[js/aiProxy.js] ← smartQuery() 메서드 추가 (기존 invoke() 유지)
     │ POST /api/smart-query
     ▼
[Python: routes/smart_query.py] ← 신규
     │ 1. Supabase fetch_all_draws()
     │ 2. 분석타입별 통계 계산
     │    - 전이행렬 P(next=X | current=Y)
     │    - 연속패턴 후 분포
     │    - Gap/Streak 분석
     │    - 조건부확률
     │ 3. 계산된 데이터 → LangChain(Gemini)
     ▼
[Gemini] ← 설명만 담당 (계산 X)
     ▼
[구조화된 답변] → 모든 페이지 동일 렌더링
```

---

## 3. 변경 파일 목록

### 3-1. 신규 생성

| 파일 | 설명 |
|---|---|
| `langchain-backend/routes/smart_query.py` | 핵심: 분석타입별 Supabase 계산 엔드포인트 |
| `js/aiQnA.js` | 공통 submitCustomAIAnalysis / executeLocalAIAnalysis |

### 3-2. 수정

| 파일 | 수정 내용 |
|---|---|
| `js/aiProxy.js` | `smartQuery()` 메서드 추가 |
| `langchain-backend/main.py` | smart_query 라우터 등록 |
| `js/customAnalysis.js` | smartQuery 호출로 전환 |

### 3-3. 페이지별 수정 (우선순위순)

#### 🔴 긴급: 기능 자체가 불완전
| 파일 | 문제 | 할 것 |
|---|---|---|
| `composite_number.html` | executeLocalAI ❌, AIProxy ❌ | 추가 |
| `twin_number.html` | executeLocalAI ❌, AIProxy ❌ | 추가 |
| `triangular_number.html` | AIProxy ❌ | 추가 |

#### 🟠 중요: QnA 모달(채팅창) 자체가 없음
| 파일 | 현재 버튼수 | 할 것 |
|---|---|---|
| `regression.html` | 1개 | QnA 모달 추가 |
| `square_number.html` | 11개 | QnA 모달 추가 |
| `stats_by_number.html` | 16개 | QnA 모달 추가 |
| `tail_sum.html` | 1개 | QnA 모달 추가 |
| `total_sum.html` | 1개 | QnA 모달 추가 |

#### 🟡 표준화: analysisType 한글 → 영어
| 파일 | 현재값 | 변경값 |
|---|---|---|
| `carryover.html` | `이월수패턴정밀분석` | `carryover` |
| `lotto_paper.html` | `로또용지패턴` | `lotto_paper` |
| `magic_square.html` | `9궁패턴` | `magic_square` |
| `triangular_number.html` | `삼각수패턴정밀분석` | `triangular_number` |
| `twin_number.html` | `동형수분석챗봇` | `twin_number` |
| `missing.html` | `미출현심층질문` | `missing` |

#### 🟡 퀵버튼 보강 필요 (버튼 0~2개)
| 파일 | 현재 | 목표 |
|---|---|---|
| `missing.html` | 0개 | 8~10개 |
| `hot_cold.html` | 2개 | 8~10개 |
| `properties_matrix.html` | 1개 | 6~8개 |
| `regression.html` | 1개 | 6~8개 |
| `tail_sum.html` | 1개 | 6~8개 |
| `total_sum.html` | 1개 | 6~8개 |
| `triangular_number.html` | 1개 | 6~8개 |

---

## 4. 분석타입별 백엔드 계산 명세

### smart_query.py 에서 분석타입별로 계산할 통계

```python
ANALYSIS_STATS = {
    "ac_value": [
        "transition_matrix",      # P(next AC=X | current AC=Y)
        "streak_distribution",    # N연속 후 다음값 분포
        "gap_analysis",           # 각 AC값 미출현 회차
        "consecutive_patterns",   # 연속 동일값 빈도
    ],
    "total_sum": [
        "sum_transition",         # 구간 전이 확률
        "streak_after_range",     # 특정 구간 N연속 후 분포
        "range_frequency",        # 구간별 빈도
    ],
    "odd_even": [
        "ratio_transition",       # 3:3→다음비율 전이
        "extreme_after_pattern",  # 6:0 출현 후 패턴
        "consecutive_same_ratio", # 동일비율 연속 빈도
    ],
    "carryover": [
        "carryover_by_count",     # 이월수 개수별 조건부확률
        "number_carryover_rate",  # 번호별 이월 빈도
        "streak_carryover",       # N연속 이월 후 패턴
    ],
    "hot_cold": [
        "status_transition",      # hot→cold→hot 전이
        "gap_by_number",          # 번호별 현재 Gap
        "streak_by_number",       # 번호별 현재 Streak
        "revival_pattern",        # cold 후 복귀 주기
    ],
    "missing": [
        "gap_distribution",       # Gap 분포 (현재 Gap별 출현 확률)
        "long_missing_revival",   # 장기미출현 후 복귀 패턴
        "gap_streak_same",        # Gap = Streak (동일 개념)
    ],
    "tail_digit": [
        "tail_transition",        # 끝수 전이행렬
        "same_tail_coappearance", # 동끝 동반출현 빈도
        "tail_gap",               # 끝수별 Gap
    ],
    "tail_sum": [
        "tailsum_transition",     # 끝수합 구간 전이
        "tailsum_range_freq",     # 구간별 빈도
    ],
    "low_high": [
        "ratio_transition",       # 비율 전이행렬
        "extreme_freq",           # 극단비율(6:0, 0:6) 빈도/주기
    ],
    "odd_even": [
        "ratio_transition",
        "extreme_freq",
    ],
    "multiple": [
        "group_transition",       # 배수그룹 전이
        "zero_group_pattern",     # 멸(0개) 그룹 빈도
    ],
    "consecutive_number": [
        "consec_transition",      # 연번수 전이
        "zero_consec_freq",       # 연번 없음 빈도
    ],
    "prime_number": [
        "prime_count_transition",
        "zero_prime_freq",
    ],
    "composite_number": [
        "composite_count_transition",
    ],
    "square_number": [
        "square_count_transition",
        "gap_by_square_num",      # 1,4,9,16,25,36 각 Gap
    ],
    "triangular_number": [
        "triangular_count_transition",
    ],
    "twin_number": [
        "twin_count_transition",
        "gap_by_twin_num",        # 11,22,33,44 각 Gap
        "each_twin_probability",  # 11/22/33/44 개별 확률
    ],
    "neighbor_number": [
        "neighbor_transition",
        "neighbor_by_range",      # 번호대별 이웃수 빈도
    ],
    "number_range": [
        "range_transition",       # 번호대별 전이
        "zero_range_freq",        # 구간 멸 빈도
    ],
    "magic_square": [
        "palace_transition",      # 9궁 전이
        "zero_palace_freq",       # 궁 멸 빈도
        "center_palace_freq",     # 5궁 출현 패턴
    ],
    "lotto_paper": [
        "number_freq",            # 전체 번호별 빈도
        "gap_by_number",          # 번호별 Gap
        "hot_cold_status",        # 현재 hot/cold 상태
    ],
    "stats_by_number": [
        "number_freq_all",        # 전체 번호별 출현 빈도
        "gap_by_number",
        "coappearance_top",       # 동반출현 상위 쌍
        "bonus_freq",             # 보너스볼 빈도
    ],
    "regression": [
        "regression_hit_dist",    # 회귀분석 적중 분포
        "model_transition",       # 모델별 전이
    ],
    "properties_matrix": [
        "property_combination_freq", # 속성 조합 빈도
    ],
    "custom": [
        "dynamic",                # 사용자 조합 기준 맞춤
    ],
}
```

---

## 5. 퀵버튼 질문 설계 원칙

### ✅ 올바른 질문 유형 (백엔드 계산 가능)
- "AC=8 다음에 나올 값의 확률 순위"
- "최근 N회 연속 같은 패턴 후 다음 분포"
- "현재 Gap이 X인 값들의 역대 출현 확률"
- "특정 비율이 N연속 후 전이 패턴"

### ❌ 잘못된 질문 유형 (답 불가 → 제거)
- "다음 회차에 나올 번호 추천해줘"
- "꺾일 때가 됐나요?"
- "이번에 나올 타이밍인가요?"

### Gap = Streak (동일 개념)
- Gap: 마지막 출현 후 경과 회차 (미출현 길이)
- Streak: 연속 출현 회차 수
- → 별도 페이지 불필요, 기존 missing.html + hot_cold.html에 통합

---

## 6. 구현 순서 (세션별)

### 세션 1: 공통 인프라
1. `langchain-backend/routes/smart_query.py` 생성
   - `/api/smart-query` POST 엔드포인트
   - 분석타입별 Supabase 계산 함수
   - LangChain(Gemini) 호출
2. `langchain-backend/main.py` 라우터 등록
3. `js/aiProxy.js` → `smartQuery()` 메서드 추가

### 세션 2: 불완전 페이지 수정
- composite_number.html (executeLocal + AIProxy 추가)
- twin_number.html (executeLocal + AIProxy 추가)
- triangular_number.html (AIProxy 추가)
- analysisType 한글 → 영어 표준화 (6개 파일)

### 세션 3: QnA 모달 없는 페이지
- regression.html, square_number.html, stats_by_number.html
- tail_sum.html, total_sum.html
- 공통 QnA 모달 HTML 스니펫 삽입

### 세션 4: 퀵버튼 전면 재설계
- 각 분석타입별 올바른 질문 8~10개로 교체
- missing.html, hot_cold.html 등 부족한 페이지 보강
- Gap/Streak 질문을 missing + hot_cold에 통합

### 세션 5: 테스트 및 마무리
- 각 페이지 AI Q&A 동작 확인
- 답변 품질 검증 (수치 인용 여부)
- sessionStorage 캐싱 동작 확인

---

## 7. 핵심 코드 스니펫 (다음 세션 참고용)

### smart_query.py 기본 구조
```python
from fastapi import APIRouter
from db.supabase_client import fetch_all_draws
from chains.analysis_chain import run_analysis

router = APIRouter(prefix="/api", tags=["smart-query"])

@router.post("/smart-query")
async def smart_query(req: SmartQueryRequest):
    # 1. Supabase에서 전체 데이터 로드
    draws = fetch_all_draws()

    # 2. 분석타입별 통계 계산
    stats = compute_stats(draws, req.analysis_type, req.question)

    # 3. 계산된 통계 + 질문 → LangChain
    result = await run_analysis(
        context=format_context(stats),
        analysis_type=req.analysis_type,
        target_round=req.target_round,
        topic=ANALYSIS_TYPE_TO_TOPIC[req.analysis_type]
    )
    return result

def compute_stats(draws, analysis_type, question):
    """분석타입별 Supabase 계산 라우터"""
    if analysis_type == "ac_value":
        return compute_ac_stats(draws, question)
    elif analysis_type == "total_sum":
        return compute_sum_stats(draws, question)
    # ...
```

### aiProxy.js smartQuery 추가
```javascript
async smartQuery({ question, analysisType, targetRound, subjectRound }) {
    const isAlive = await this.checkHealth();
    if (isAlive) {
        const res = await fetch(`${CURRENT_BASE_URL}/api/smart-query`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                question,
                analysis_type: analysisType,
                target_round: targetRound || 0,
                subject_round: subjectRound || 0
            })
        });
        if (res.ok) return await res.json();
    }
    // 폴백: 기존 invoke() 사용
    return await this.invokeEdgeFunction({ prompt: question, analysisType });
}
```

### 공통 submitCustomAIAnalysis 패턴 (각 페이지 적용)
```javascript
async function submitCustomAIAnalysis(directPrompt) {
    const userPrompt = (typeof directPrompt === 'string' && directPrompt.trim())
        ? directPrompt.trim()
        : document.getElementById('aiUserPrompt')?.value?.trim();
    if (!userPrompt) return;

    // ← 각 페이지에서 이 두 값만 설정하면 됨
    const ANALYSIS_TYPE = 'ac_value';  // 페이지별 고정값
    const targetRound = /* 페이지에서 계산 */;

    if (window.AIProxy) {
        return await window.AIProxy.smartQuery({
            question: userPrompt,
            analysisType: ANALYSIS_TYPE,
            targetRound
        });
    }
}
```

---

## 8. 참고: 현재 Python 백엔드 구조

```
langchain-backend/
├── main.py                    # FastAPI 앱, 라우터 등록
├── routes/
│   ├── analysis.py            # /api/analyze (현재 사용중)
│   ├── deep_analysis_v3.py    # /api/deep-analysis/v3/analysis
│   └── smart_query.py         # ← 신규 생성 예정
├── chains/
│   └── analysis_chain.py      # LangChain + Gemini 실행
├── db/
│   └── supabase_client.py     # fetch_all_draws() 등
├── models/
│   ├── ensemble.py            # 5중 앙상블 (번호예측용)
│   └── markov_model.py        # Gap 기반 전이확률
└── rag/
    ├── data_loader.py          # lotto_draws → Document 변환 (AC값 계산 포함)
    └── retriever.py            # RAG 검색
```

### Supabase 테이블
- `lotto_draws`: 전체 회차 당첨번호 (round, numbers, bonus, date)
- `number_features_by_round`: 번호별 missing_count
- `ai_predictions`: AI 예측 이력

---

*이 문서를 다음 세션에서 참고하여 순서대로 구현*
