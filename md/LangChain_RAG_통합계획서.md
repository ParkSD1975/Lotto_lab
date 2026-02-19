# LangChain/RAG 로또 프로젝트 통합 계획서

## 1. 개요

### 배경
현재 로또 분석 프로젝트(`C:\Users\psdet\Desktop\로또개발`)는 32개 HTML 분석 페이지 + Supabase Edge Function(Gemini 2.0 Flash)으로 AI 분석을 수행 중이다. 그러나 현재 AI는 **1회성 호출(프롬프트→응답)** 방식이라 기억/맥락이 없고, 과거 유사 패턴 참조가 불가능하며, Q&A 대화가 안 된다.

### 목표
LangChain/RAG를 적용하여:
1. **AI 분석 고도화** - RAG로 과거 유사 패턴을 자동 참조하여 분석 품질 향상
2. **Q&A 챗봇** - 1200+회차 데이터 기반 자연어 질의응답
3. **주간 보고서 자동 생성** - 17개 분석 결과를 종합한 보고서

---

## 2. 아키텍처 설계

### 현재 구조
```
HTML 페이지 → common_v2.js → Supabase Edge Function → Gemini 2.0 Flash → JSON 응답
```

### 변경 후 구조
```
HTML 페이지 → common_v2.js → AIProxy(라우터) → FastAPI(LangChain+RAG) → Gemini + RAG 컨텍스트
                                     └→ (fallback) Supabase Edge Function → Gemini
```

### 핵심 전략: AIProxy 패턴
- `js/aiProxy.js`가 라우터 역할
- LangChain 서버 실행 중이면 자동으로 LangChain으로 라우팅
- 서버가 꺼져있으면 기존 Edge Function으로 자동 fallback
- 기존 기능 100% 유지하면서 점진적 전환 가능

---

## 3. 변경 파일 상세

### 3.1 수정되는 기존 파일

#### `js/common_v2.js` (6줄 변경)
| 위치 | 현재 | 변경 후 |
|------|------|---------|
| `executeAnalysis()` 라인 ~420 | `window.supabaseClient.functions.invoke('analyze-lotto', { body: { context: prompt } })` | `window.AIProxy.invoke({ context: prompt, analysisType, targetRound, subjectRound })` |
| `analyzePattern()` 라인 ~755 | `window.supabaseClient.functions.invoke('analyze-lotto', { body: { context: fullContext } })` | `window.AIProxy.invoke({ context: fullContext, type: 'analyze' })` |

#### `js/config.js` (5줄 추가)
```javascript
LANGCHAIN: {
    URL: 'http://localhost:8000',
    ENABLED: true,
    FALLBACK_TO_EDGE: true
}
```

#### 32개 HTML 분석 페이지 (각 2~5줄 변경)
**공통 변경 1**: `<head>`에 script 태그 2개 추가
```html
<script src="js/aiProxy.js"></script>
<script src="js/ChatbotWidget.js"></script>
```

**공통 변경 2**: 각 페이지의 직접 Edge Function 호출을 AIProxy로 교체
- Find: `window.supabaseClient.functions.invoke('analyze-lotto',`
- Replace: `window.AIProxy.invoke(`
- 영향 함수: `submitCustomAIAnalysis()`, `submitModalFollowUp()`, 일부 `refreshAIAnalysis()`
- 페이지당 약 2~3곳

**해당 페이지 전체 목록:**
| # | 파일명 | AI 호출 지점 수 |
|---|--------|----------------|
| 1 | total_sum.html | 3곳 |
| 2 | tail_sum.html | 3곳 |
| 3 | tail_digit.html | 3곳 |
| 4 | ac_value.html | 3곳 |
| 5 | odd_even.html | 3곳 |
| 6 | low_high.html | 3곳 |
| 7 | prime_number.html | 3곳 |
| 8 | composite_number.html | 3곳 |
| 9 | square_number.html | 3곳 |
| 10 | triangular_number.html | 3곳 |
| 11 | twin_number.html | 3곳 |
| 12 | multiple.html | 3곳 |
| 13 | consecutive_number.html | 3곳 |
| 14 | carryover.html | 3곳 |
| 15 | neighbor_number.html | 3곳 |
| 16 | number_range.html | 3곳 |
| 17 | lotto_paper.html | 3곳 |
| 18 | magic_square.html | 3곳 |
| 19 | stats_by_number.html | 3곳 |
| 20 | hot_cold.html | 3곳 |
| 21 | missing.html | 3곳 |
| 22 | regression.html | 3곳 |
| 23 | custom_analysis.html | 3곳 |
| 24 | customgeneration.html | 2곳 |
| 25 | winning-numbers.html | 1곳 |
| 26 | dashboard.html | 1곳 |
| 27 | properties_matrix.html | 1곳 |
| 28 | db_data_generator.html | 1곳 |

#### `components/sidebar.html` (6줄 추가)
- 네비게이션 하단에 AI 챗봇 토글 링크 추가

#### `lotto-auto-update/update_lotto.py` (5줄 추가)
- 데이터 삽입 후 벡터 인덱스 업데이트 HTTP 호출
- try/except로 감싸서 서버 미실행 시 무시

---

### 3.2 신규 추가 파일

#### JavaScript (3개 파일)

**`js/aiProxy.js`** (~100줄)
- AI 호출 라우터: Edge Function ↔ LangChain 자동 전환
- health check로 LangChain 서버 가용성 자동 감지
- 응답 형식을 기존과 동일하게 래핑하여 호환성 유지

**`js/ChatbotWidget.js`** (~200줄)
- 모든 페이지에 표시되는 플로팅 RAG Q&A 챗봇
- 현재 페이지 컨텍스트 자동 인식 (예: 소수 분석 페이지에서는 소수 관련 데이터 포함)
- 대화 기록 유지 (세션 기반)
- 출처 표시 (어느 회차 데이터를 참고했는지)

**`js/ReportViewer.js`** (~100줄)
- 주간 보고서 표시 컴포넌트
- JSON 보고서를 스타일된 HTML로 렌더링

#### Python LangChain 백엔드 (새 디렉토리)

```
langchain-backend/
├── main.py                     # FastAPI 진입점, CORS, 라우트 등록
├── config.py                   # 환경변수 관리
├── requirements.txt            # Python 의존성
├── .env                        # API 키 (git 제외)
│
├── db/
│   ├── supabase_client.py      # Supabase Python 클라이언트
│   └── vector_store.py         # ChromaDB 초기화/관리
│
├── chains/
│   ├── analysis_chain.py       # 통계 분석 체인 (Edge Function analyze 대체)
│   ├── chat_chain.py           # RAG Q&A 대화 체인 (신규 기능)
│   ├── report_chain.py         # 주간 보고서 생성 체인 (신규 기능)
│   └── interpret_chain.py      # NLP 필터 해석 체인 (custom_interpret 대체)
│
├── rag/
│   ├── embedder.py             # lotto_draws → 벡터 임베딩 파이프라인
│   ├── retriever.py            # 커스텀 검색기 (시맨틱 + 최신성 가중치)
│   └── data_loader.py          # DB 데이터 → LangChain 문서 변환
│
├── routes/
│   ├── analysis.py             # POST /api/analyze
│   ├── chat.py                 # POST /api/chat
│   ├── report.py               # POST /api/report
│   └── interpret.py            # POST /api/interpret
│
├── prompts/
│   ├── analysis_prompts.py     # 분석 유형별 프롬프트 템플릿
│   ├── chat_prompts.py         # 챗봇 시스템 프롬프트
│   └── report_prompts.py       # 보고서 생성 프롬프트
│
├── memory/
│   └── session_store.py        # 세션별 대화 기록 관리 (최대 10턴)
│
└── scripts/
    ├── build_vectors.py        # 초기 벡터 인덱스 전체 빌드
    └── update_vectors.py       # 새 회차 데이터 증분 업데이트
```

**Python 의존성 (`requirements.txt`):**
```
fastapi==0.115.0
uvicorn[standard]==0.32.0
langchain==0.3.0
langchain-google-genai==2.0.0
langchain-community==0.3.0
chromadb==0.5.0
supabase==2.10.0
python-dotenv==1.0.1
pydantic==2.9.0
```

---

### 3.3 변경되지 않는 것

| 항목 | 이유 |
|------|------|
| 각 분석 페이지의 차트/통계/UI | 순수 JS 통계 로직이라 AI와 무관 |
| NLPProcessor.js, NLPInputComponent.js, BasicAnalysisNLP.js | NLP 엔진은 그대로, AI 호출 부분만 라우팅 변경 |
| FilterService.js | 필터 관리는 AI와 독립적 |
| Supabase DB 스키마 | 기존 테이블 구조 유지 |
| CSS/테마/레이아웃 | UI 변경 없음 |
| Supabase Edge Function (analyze-lotto-updated.ts) | fallback으로 유지 |
| lotto.csv | 로컬 백업 그대로 |

---

## 4. 각 분석 페이지 AI 기능 변경 상세

### 공통 패턴 (모든 분석 페이지 동일)

| AI 기능 | 현재 | 변경 후 | 사용자 체감 |
|---------|------|---------|------------|
| `refreshAIAnalysis()` 자동 분석 | Edge Function → Gemini (현재 데이터만 전달) | AIProxy → FastAPI → **RAG로 유사 과거 패턴 10개 검색** + Gemini | 더 풍부하고 근거있는 분석 |
| `submitCustomAIAnalysis()` 질문 | Edge Function → 1회성 응답 | AIProxy → FastAPI → RAG 컨텍스트 포함 응답 | 과거 사례 기반 답변 |
| `submitModalFollowUp()` 후속 질문 | Edge Function → 이전 대화 기억 X | **AIProxy.chat()** → 대화 기록 유지 (10턴) | 연속 질문 가능 |
| Quick Buttons (10개 프리셋) | `submitCustomAIAnalysis()` 호출 | 변경 없음 (같은 함수, 내부만 라우팅 변경) | 차이 없음 |
| Prompt Library (200+ 템플릿) | 선택 → `submitCustomAIAnalysis()` | 변경 없음 | 차이 없음 |
| AI Section UI 렌더링 | `{trend, pattern, recommendation}` | **동일 JSON 형식** (FastAPI가 호환 형식 반환) | UI 변화 없음 |
| NLP Input | 명령어 파싱 → 데이터 조작 | 변경 없음 | 차이 없음 |
| **[신규] 플로팅 챗봇** | 없음 | 모든 페이지 우하단에 RAG Q&A 위젯 | 어디서든 자유 질문 가능 |

### 분석 품질 향상 예시

**현재 (소수 분석 페이지):**
```
사용자: "다음 회차 소수 추천"
→ Gemini에 현재 페이지 통계만 전달
→ "소수 평균 2.1개, 최근 상승 추세..."
```

**변경 후:**
```
사용자: "다음 회차 소수 추천"
→ RAG가 소수 패턴이 비슷했던 과거 10개 회차 검색
→ Gemini에 현재 통계 + 유사 과거 패턴 10개 함께 전달
→ "소수 평균 2.1개, 최근 상승 추세. 과거 유사 패턴(1150회, 1098회, 1045회...)에서는
   소수 3개 이상 출현 확률 68%. 특히 소수 3,7,41이 활발. 추천: 소수 3개 조합"
```

---

## 5. RAG 파이프라인 상세

### 5.1 벡터화 대상

| 데이터 소스 | 문서 수 | 문서 내용 예시 |
|------------|---------|--------------|
| `lotto_draws` | ~1200개 | "1200회차: 번호 3,7,15,22,35,41. 총합 133, 홀짝비 4:2, AC값 8, 소수 3개(3,7,41), 연번 0쌍, 이월수 1개" |
| `ai_custom_analyses` | ~수십개 | 사용자 생성 분석 규칙과 필터 조건 |
| `ai분석명령/` 프롬프트 | ~20개 | 분석 유형별 전문가 프롬프트 |

### 5.2 기술 선택

| 항목 | 선택 | 이유 |
|------|------|------|
| Vector DB | ChromaDB (로컬) | ~1200문서로 충분, 무료, 설치 간편 |
| Embedding | Google text-embedding-004 | Gemini API 키 재사용, 한국어 우수 |
| LLM | Gemini 2.0 Flash | 기존과 동일 (비용 효율적) |
| 검색 전략 | 시맨틱 + 최신성 가중치 | 최근 100회차 1.5배 부스트 |

### 5.3 검색 흐름
```
사용자 질문: "최근 연번이 자주 나오나?"
    ↓
1. 임베딩 변환 (text-embedding-004)
    ↓
2. ChromaDB 시맨틱 검색 (유사도 top 20)
    ↓
3. 메타데이터 필터링 (연번 관련 문서 우선)
    ↓
4. 최신성 가중치 적용 (최근 회차 부스트)
    ↓
5. Top 10 문서 반환 → LLM 프롬프트에 포함
```

---

## 6. 구현 순서

### Phase 1: 백엔드 기반 (1~2주차)
- [ ] `langchain-backend/` 디렉토리 구조 생성
- [ ] FastAPI + CORS + health check 구현
- [ ] Supabase Python 클라이언트 연결
- [ ] data_loader.py: lotto_draws → 문서 변환
- [ ] embedder.py: ChromaDB 벡터 인덱스 빌드
- [ ] analysis_chain.py: 기존 Edge Function과 동일 출력 형식
- [ ] `/api/analyze` 엔드포인트 테스트

### Phase 2: 프록시 연결 (3주차)
- [ ] `js/aiProxy.js` 생성
- [ ] `common_v2.js` 수정 (2곳)
- [ ] 32개 HTML 페이지에 script 태그 추가
- [ ] 32개 HTML 페이지의 직접 호출을 AIProxy로 find-replace
- [ ] `config.js` 업데이트
- [ ] Edge Function fallback 동작 확인

### Phase 3: Q&A 챗봇 (4주차)
- [ ] chat_chain.py: ConversationalRetrievalChain 구현
- [ ] session_store.py: 세션 메모리 관리
- [ ] `ChatbotWidget.js` 생성
- [ ] 각 페이지 `submitModalFollowUp()` 전환
- [ ] 멀티턴 대화 테스트

### Phase 4: 주간 보고서 (5주차)
- [ ] report_chain.py: 종합 보고서 생성 체인
- [ ] `ReportViewer.js` 생성
- [ ] `/api/report` 엔드포인트
- [ ] 대시보드에 보고서 버튼 추가

### Phase 5: 안정화 (6주차~)
- [ ] 모든 페이지 통합 테스트
- [ ] RAG 검색 품질 튜닝
- [ ] 에러 핸들링 강화
- [ ] Edge Function 의존도 모니터링

---

## 7. 검증 방법

| 테스트 | 방법 | 기대 결과 |
|--------|------|----------|
| API 호환성 | 동일 프롬프트로 Edge Function vs FastAPI 결과 비교 | 동일 JSON 형식 (`{trend, pattern, recommendation}`) |
| Fallback | FastAPI 서버 종료 후 페이지 AI 분석 실행 | 자동으로 Edge Function 사용, 에러 없음 |
| RAG 품질 | "1200회차와 비슷한 패턴은?" 질의 | 총합/홀짝비/AC값이 유사한 회차 반환 |
| 대화 기억 | 챗봇에서 3턴 연속 질문 | 이전 맥락 유지 |
| 보고서 | `/api/report?round=latest` 호출 | 6개 섹션 포함 종합 보고서 |

### 실행 명령
```bash
# 1. 백엔드 설치 및 실행
cd C:\Users\psdet\Desktop\로또개발\langchain-backend
pip install -r requirements.txt
python scripts/build_vectors.py      # 초기 벡터 빌드 (1회)
uvicorn main:app --reload --port 8000

# 2. 브라우저에서 분석 페이지 열기
# → AIProxy가 자동으로 LangChain 백엔드 감지
# → RAG 기반 분석 시작
```

---

## 8. 변경 범위 요약

| 구분 | 파일 수 | 변경량 |
|------|---------|--------|
| 수정되는 기존 파일 | 35개 | 각 2~6줄 |
| 신규 JavaScript | 3개 | ~400줄 |
| 신규 Python 백엔드 | 20+개 | ~2000줄 |
| 변경 없는 기존 파일 | 나머지 전부 | 0줄 |
| **전체 기존 코드 영향도** | | **~5% 이하** |
