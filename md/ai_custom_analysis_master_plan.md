# 📘 AI 커스텀 로또 분석 시스템 구축 종합 보고서 (Master Plan)

> **작성일**: 2026-01-31  
> **비전**: "사용자가 만드는 무한한 분석기 (User-Generated Analysis Platform)"

---

## 1. 개요 (Project Overview)

본 프로젝트는 기존의 정적인 분석 페이지를 넘어, 사용자가 **자연어(Prompt)**로 원하는 분석 로직을 정의하면 AI가 이를 해석하여 **전용 분석 페이지**를 동적으로 생성하고, 클라이언트 사이드에서 **과거 1회부터 현재까지의 전수 통계(Gap, Straight, Max/Min)**를 실시간으로 산출하여 제공하는 플랫폼을 구축하는 것을 목표로 합니다.

- **비전:** "사용자가 만드는 무한한 분석기 (User-Generated Analysis Platform)"
- **핵심 기술:** SPA(Single Page Application) 템플릿 + 클라이언트 사이드 고속 연산 + Supabase DB 연동.

---

## 2. 데이터베이스 설계 (Database Architecture)

기존 `lotto_draws` 데이터를 활용하되, 커스텀 분석 정의를 저장할 신규 테이블이 필요합니다.

### 2-1. `ai_custom_analyses` 테이블 스키마 (최종)

AI 해석의 결과물인 **'대상 번호 집합'**을 저장하는 것이 핵심입니다.

```sql
CREATE TABLE ai_custom_analyses (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES auth.users(id),  -- (선택사항) 사용자별 관리 시 필요
    title VARCHAR(100) NOT NULL,             -- 분석명 (예: 피보나치 수열)
    prompt TEXT NOT NULL,                    -- 원본 프롬프트
    target_numbers INTEGER[] NOT NULL,       -- [중요] 분석 대상 번호 배열 (예: [1, 2, 3, 5, 8...])
    description TEXT,                        -- AI가 생성한 분석 설명
    filter_config JSONB DEFAULT '{"min": 1, "max": 3, "enabled": false}'::jsonb, -- 필터 설정
    memo TEXT,                               -- 사용자 개인 메모 (추가됨)
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- LNB 로딩 속도 최적화를 위한 인덱스
CREATE INDEX idx_custom_analyses_created ON ai_custom_analyses(created_at DESC);
```

---

## 3. UI/UX 디자인 및 페이지 구성 계획 (Page Design)

기존 `theme.js`의 컬러 팔레트와 `layout.js`의 레이아웃 규격을 준수합니다.

### 3-1. 페이지 레이아웃 구조 (`custom_analysis.html`)

화면은 **Top-Down** 방식으로 정보의 중요도 순으로 배치합니다.

#### **Zone A. 헤더 & 아이덴티티 (Header)**

- **위치:** 최상단
- **구성:**
  - `Badge`: "AI Custom Analysis" (보라색 계열 `bg-lotto-purple/10 text-lotto-purple`)
  - `Title`: 분석명 (H1, Pretendard Bold 24px)
  - `Description`: 분석 설명 (Text Gray-500)
  - `Target Visual`: 분석 대상 번호들을 **로또 볼** 형태로 나열 (포함 안 된 번호는 흐리게 처리하거나 숨김)

#### **Zone B. 통계 대시보드 (Dashboard) - ⭐ 핵심 컨텐츠**

사용자가 강조한 통계 지표를 카드 형태로 시각화합니다. (3단 그리드)

| 카드 1: 현재 흐름 (Current) | 카드 2: 역사적 기록 (Records) | 카드 3: 확률/성능 (Stats) |
|---------------------------|----------------------------|-------------------------|
| **현재 Gap:** 5회 (경고색) | **Max Gap:** 18회 | **총 당첨률:** 78.5% |
| **현재 연속:** 0회 | **Max Straight:** 12회 | **평균 개수:** 1.8개 |
| **직전 결과:** 0개 (미출현) | **Max Hit:** 5개 | **임박 지수:** 85% |

- **디자인:** `bg-white`, `rounded-xl`, `shadow-sm`, `border-gray-200`. 중요 숫자는 `text-3xl`, `font-bold` 적용.

#### **Zone C. 트렌드 차트 (Trend Chart)**

- **내용:** 최근 50회차 당첨 개수 막대그래프 + **이론적 평균선(점선)**.
- **목적:** 최근에 몰아서 나오는지, 띄엄띄엄 나오는지 시각적 확인.
- **스타일:** `Chart.js` 활용, 막대 색상은 `lotto-blue` (#3B82F6) 사용.

#### **Zone D. AI 인사이트 (Insight)**

- **구성:** 기존 `multiple.html` 등에서 사용된 채팅형 인터페이스 재사용.
- **기능:** 사용자가 통계 데이터를 보고 질문하면 AI가 해석 (예: "지금 Gap 5인데 들어갈 타이밍이야?").

#### **Zone E. 필터 컨트롤 & 저장 (Filter)**

- **구성:**
  - **On/Off 스위치:** 필터 활성화 여부 토글.
  - **개수 버튼:** [0] [1] [2] [3]... (다중 선택 가능).
  - **저장 버튼:** 변경된 필터 설정 DB 업데이트.
- **UX:** 스위치를 켜면 LNB 메뉴에 **초록색 점(🟢)**이 즉시 반영되도록 구현.

#### **Zone F. 상세 히스토리 (Evidence Table)**

- **내용:** 전체 회차 리스트 테이블.
- **컬럼:** 회차, 당첨번호(타겟 하이라이트), 결과(O/X), 당시 Gap, 당시 Straight.
- **추가:** 엑셀 다운로드 버튼.

---

## 4. 시스템 연동 계획 (Integration)

기존 시스템 파일들과의 유기적인 결합 방법입니다.

### 4-1. `header.html` (GNB)

- **새 분석 버튼:** 기존 `+ 새 분석` 버튼에 모달 트리거(`onclick="openCreateModal()"`) 연결.
- **모달 디자인:**
  - 중앙 팝업, `backdrop-blur`.
  - 입력창 1: 분석명 (예: 피보나치).
  - 입력창 2: 프롬프트 (예: 피보나치 수열 분석해줘).
  - 실행 버튼: AI API 호출 및 결과 미리보기.
- **보정 단계:** AI 결과(번호 리스트)를 사용자가 직접 클릭해서 수정 가능하게 구현.

### 4-2. `sidebar.html` & `layout.js` (LNB 동적화)

기존 `layout.js`는 정적 HTML(`sidebar.html`)을 로드하는 방식입니다. 이를 수정해야 합니다.

- **변경 전략:**
  1. `sidebar_custom.html`을 기본 뼈대로 로드.
  2. `layout.js` 내부에 `renderLNB()` 함수 추가.
  3. `renderLNB()`에서 Supabase `ai_custom_analyses` 테이블 조회.
  4. 조회된 리스트를 LNB 하단에 `appendChild`로 추가.
- **상태 표시:** DB의 `filter_config.enabled` 값이 `true`면 메뉴명 옆에 **🟢**, `false`면 **⚪** 배지 표시.
- **적중 알림:** 직전 회차에 필터 조건 만족 시 **🔥(불꽃)** 아이콘 표시.

### 4-3. `FilterService.js` (조합기 연동)

- **수정:** `FilterService` 초기화 시, `ai_custom_analyses` 테이블에서 `enabled: true`인 항목들을 함께 로드하여 메모리에 캐싱.
- **적용:** 조합 생성 알고리즘(`generator.js` 등)에서 `customFilters` 배열을 순회하며 조건 검사.

### 4-4. `filter.html` (필터 메뉴 페이지)

- **역할:** 통합 관제 센터.
- **기능:** 모든 커스텀 분석 리스트 로드 (활성/비활성 모두).
- **동작:** 여기서 스위치를 켜고 끄면 DB가 업데이트되고, 커스텀 분석 페이지 및 조합기에 실시간 반영.

---

## 5. 개발 로드맵 (Roadmap)

| 단계 | 작업 내용 | 예상 소요 | 비고 |
|------|----------|----------|------|
| **1단계** | **DB & 인프라**<br>- Supabase 테이블 생성 및 RLS 정책 설정<br>- `layout.js`에 LNB 동적 렌더링 로직 추가 | 1일 | 기반 공사 |
| **2단계** | **템플릿 페이지 (`custom_analysis.html`)**<br>- UI 레이아웃 퍼블리싱 (Zone A~F 구현)<br>- `customAnalysis.js` 통계 산출 엔진(Gap/Straight 계산) 구현 | 1.5일 | 핵심 기능 |
| **3단계** | **AI 생성 모달**<br>- 프롬프트 입력 및 OpenAI API 연동<br>- 번호 추출 및 **수동 보정 UI** 구현<br>- DB 저장 로직 | 1일 | 생성 기능 |
| **4단계** | **필터 연동 & 통합 관리**<br>- 필터 On/Off에 따른 DB 업데이트<br>- `filter.html`에 커스텀 필터 목록 추가<br>- `FilterService.js`와 조합기 연동 테스트 | 1일 | 연동 |
| **5단계** | **통합 테스트 & 디자인 폴리싱**<br>- 전체 플로우 점검, 모바일 반응형 확인<br>- 엑셀 다운로드, 메모 기능 추가 | 0.5일 | 마무리 |

---

## 6. 결론

본 계획서는 기존 **Lotto Lab**의 디자인 시스템을 100% 계승하면서, 사용자가 가장 중요하게 여기는 **"과거 데이터 검증(Backtesting)"** 기능을 극대화하는 방향으로 설계되었습니다.

특히 **DB 구조를 단순화(번호 배열 저장)**함으로써 시스템의 속도와 안정성을 확보하였으며, **단일 템플릿(SPA)** 방식을 통해 유지보수 효율성을 높였습니다. 

또한, **번호 수동 보정, 적중 알림, 임박 지수** 등 사용자의 신뢰도를 높이는 장치를 추가하여 완성도를 끌어올렸습니다. 

이 설계대로 진행 시, 사용자에게 매우 강력하고 전문적인 분석 경험을 제공할 수 있을 것입니다.
