# 🎯 로또AI 커스텀 분석 구현 가이드

> **작성일:** 2026-01-17  
> **목적:** 커스텀 분석 메뉴 구현을 위한 상세 설계 문서  
> **참조:** 기존 기초분석 코드 패턴 100% 준수

---

## 📐 1. 기존 프로젝트 아키텍처 분석

### 1.1 GNB 메뉴 구조 (10개)

```
┌────────┬────────┬────────┬────────┬────────┬────────┬────────┬────────┬────────┬────────┐
│대시보드│당첨번호│기초분석│커스텀  │AI분석  │ 필터   │  조합  │AI조합  │  출력  │  검증  │
│   0    │   1    │   2    │분석 3  │   4    │   5    │   6    │   7    │   8    │   9    │
└────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┘
```

### 1.2 기술 스택

| 항목 | 기술 |
|------|------|
| CSS Framework | Tailwind CSS (CDN) |
| Icons | Material Symbols Outlined |
| Charts | Chart.js 4.4.0 |
| Database | Supabase (PostgreSQL) |
| AI | Supabase Edge Function (`analyze-lotto`) |
| Font | Pretendard |

### 1.3 공통 파일 구조

```
components/
├── header.html      ← GNB (10개 메뉴)
├── sidebar.html     ← 기초분석 LNB (19개 메뉴)
└── sidebar_custom.html  ← 커스텀분석 LNB (동적 생성)

css/
└── common.css       ← 공통 스타일 (볼, 슬라이더, 애니메이션)

js/
├── common.js        ← Supabase 클라이언트, 유틸리티
├── layout.js        ← 레이아웃 동적 로드
└── theme.js         ← 테마 관리
```

### 1.4 Supabase 연동 패턴 (기존 코드)

```javascript
// js/common.js - 전역 클라이언트
const SUPABASE_CONFIG = {
  URL: 'https://dkcflmyoscudawleglzb.supabase.co',
  KEY: 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...'
};
window.supabaseClient = supabase.createClient(SUPABASE_CONFIG.URL, SUPABASE_CONFIG.KEY);

// 데이터 조회 (hot_cold.html 등)
const { data, error } = await supabaseClient
  .from('lotto_draws')
  .select('*')
  .order('round', { ascending: false });

// AI 분석 호출
const { data: analysis, error } = await supabaseClient.functions.invoke('analyze-lotto', {
  body: { currentRange, recentDraws, type: '핫/콜드' }
});
```

### 1.5 AI 응답 포맷팅 (기존 코드)

```javascript
// js/common.js - Utils.formatAIResponse
window.Utils = {
  formatAIResponse: (text) => {
    return text
      .replace(/{{number:(.*?)}}/g, '<span class="text-red-600 bg-red-50 font-bold px-1 rounded">$1</span>')
      .replace(/{{up:(.*?)}}/g, '<span class="text-green-600 bg-green-50 font-bold px-1 rounded">$1</span>')
      .replace(/{{down:(.*?)}}/g, '<span class="text-orange-600 bg-orange-50 font-bold px-1 rounded">$1</span>')
      // ... 기타 태그
  }
};
```

---

## 📊 2. 커스텀 분석 4가지 유형 상세 설계

### 2.1 유형별 모달 설정 범위

| 유형 | 모달에서 설정 | 생성된 페이지에서 설정 |
|------|-------------|---------------------|
| **직접입력형** | 분석명만 | 번호 선택 (1~45개) + 필터 |
| **그룹형** | 분석명 + 그룹 정의 (이름, 번호, 조건) | 결과 확인 + 필터 |
| **수식형** | 분석명 + 수식 설정 (탭 3가지) | 결과 확인 + 필터 |
| **AI 자연어형** | 분석명 + 자연어 → AI 변환 | 결과 확인 + 필터 |

### 2.2 공통 필터 기능 (모든 유형 필수)

```
┌─────────────────────────────────────────────────────────────┐
│ [필터 설정]                                                  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  당첨 개수 범위: 최소 [  0  ▼] ~ 최대 [  6  ▼]             │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ [✓] 필터 적용                                       │   │
│  │     → 이 페이지 테이블에 필터 적용 여부             │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ [필터 바로가기 →]                                    │   │
│  │     → 필터 메뉴로 이동 (이 분석 필터가 등록됨)       │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ※ 설정된 필터는 적용 ON/OFF와 관계없이                    │
│    "필터" 메뉴에 자동 등록됩니다.                          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 🗄️ 3. 데이터 저장 전략 (핵심!)

### 3.1 필요한 데이터 종류

| 데이터 | 용량 예상 | 저장 위치 | 이유 |
|--------|----------|----------|------|
| 당첨번호 (1~1200회) | 약 50KB | Supabase `lotto_draws` | 이미 존재 |
| 커스텀 분석 설정 | 분석당 1~5KB | Supabase `custom_analyses` | 영구 저장, 다기기 동기화 |
| 회차별 계산 결과 | 분석당 ~500KB | **Supabase** 또는 **클라이언트 계산** | 선택 필요 |
| 필터 설정 | 분석당 ~1KB | Supabase `custom_analyses` 내 JSONB | 통합 관리 |

### 3.2 Supabase 테이블 스키마

#### 테이블 1: `custom_analyses` (커스텀 분석 설정)

```sql
CREATE TABLE custom_analyses (
  -- 기본 정보
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  
  -- 분석 정보
  name VARCHAR(100) NOT NULL,
  type VARCHAR(20) NOT NULL CHECK (type IN ('direct', 'group', 'formula', 'ai')),
  
  -- 설정 데이터 (유형별로 다름)
  config JSONB NOT NULL,
  
  -- 필터 설정 (모든 유형 공통)
  filter_settings JSONB NOT NULL DEFAULT '{
    "min": 0,
    "max": 6,
    "enabled": false
  }',
  
  -- 메타 데이터
  is_active BOOLEAN DEFAULT true,
  display_order INT DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  
  -- 인덱스
  CONSTRAINT unique_user_analysis_name UNIQUE (user_id, name)
);

-- 인덱스
CREATE INDEX idx_custom_analyses_user ON custom_analyses(user_id, display_order);
CREATE INDEX idx_custom_analyses_type ON custom_analyses(type);
```

#### 테이블 2: `analysis_results` (회차별 계산 결과 캐시)

```sql
CREATE TABLE analysis_results (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  analysis_id UUID REFERENCES custom_analyses(id) ON DELETE CASCADE,
  round INT NOT NULL,
  
  -- 계산 결과
  generated_numbers INT[] DEFAULT NULL,  -- 수식형: 생성된 번호
  match_count INT NOT NULL DEFAULT 0,    -- 매칭 개수
  match_numbers INT[] DEFAULT '{}',      -- 매칭된 번호들
  is_condition_met BOOLEAN DEFAULT NULL, -- 그룹형: 조건 충족 여부
  
  -- 그룹형 상세 (JSONB)
  group_details JSONB DEFAULT NULL,      -- { "그룹A": 3, "그룹B": 2 }
  
  -- 메타
  calculated_at TIMESTAMPTZ DEFAULT NOW(),
  
  -- 인덱스
  CONSTRAINT unique_analysis_round UNIQUE (analysis_id, round)
);

-- 인덱스
CREATE INDEX idx_analysis_results_lookup ON analysis_results(analysis_id, round DESC);
```

### 3.3 Config JSONB 구조 (유형별)

#### 직접입력형

```javascript
{
  "type": "direct",
  "numbers": [7, 14, 21, 28, 35, 42],  // 사용자 선택 번호 (1~45개)
  "lastModified": "2026-01-17T12:00:00Z"
}
```

#### 그룹형

```javascript
{
  "type": "group",
  "groups": [
    {
      "id": "g1",
      "name": "저번호",
      "numbers": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
      "color": "#22C55E",
      "condition": { "min": 3, "max": 4 }
    },
    {
      "id": "g2", 
      "name": "고번호",
      "numbers": [31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45],
      "color": "#EF4444",
      "condition": { "min": 2, "max": 3 }
    }
  ],
  "combineLogic": "AND"  // 모든 그룹 조건 충족 필요
}
```

#### 수식형 (통합 3탭)

```javascript
{
  "type": "formula",
  "mode": "quick",  // "quick" | "custom" | "advanced"
  
  // 빠른 선택 모드
  "quickTemplates": ["plus1", "neighbor"],
  
  // 직접 설정 모드
  "rules": [
    { "id": "r1", "target": "prev", "operation": "add", "value": 1 },
    { "id": "r2", "target": "prev", "operation": "subtract", "value": 1 }
  ],
  
  // 고급 모드 (블록 기반)
  "blocks": [
    { "id": "b1", "type": "source", "value": "prev" },
    { "id": "b2", "type": "operation", "op": "add", "value": 1, "input": "b1" },
    { "id": "b3", "type": "combine", "method": "union", "inputs": ["b2", "b4"] }
  ],
  
  // 공통 옵션
  "combine": "union",  // "union" | "intersection"
  "options": {
    "removeDuplicates": true,
    "wrapAround": true,       // 46→1, 0→45
    "excludeOutOfRange": false
  }
}
```

#### AI 자연어형

```javascript
{
  "type": "ai",
  "originalPrompt": "홀수 3개, 총합 120~180",
  "interpretedType": "group",  // AI가 변환한 유형
  "interpretedConfig": {
    // 변환된 설정 (group/formula/direct 구조)
    "groups": [
      { "name": "홀수", "numbers": [1,3,5,...,45], "condition": {"min":3,"max":3} }
    ],
    "additionalFilters": {
      "sumRange": { "min": 120, "max": 180 }
    }
  },
  "confidence": 0.92,
  "aiModel": "claude-sonnet-4-20250514",
  "interpretedAt": "2026-01-17T12:00:00Z"
}
```

### 3.4 데이터 저장 전략 결정

#### 옵션 A: 모든 회차 결과 Supabase 저장 (권장 ❌)

```
장점: 
- 한번 계산하면 캐시됨
- 다기기 동기화

단점:
- 분석 1개 × 1200회 = 1200 rows
- 분석 100개 = 120,000 rows
- DB 비용 증가
- 새 회차 추가 시 모든 분석 재계산 필요
```

#### 옵션 B: 클라이언트 실시간 계산 (권장 ✅)

```
장점:
- DB 저장 최소화 (설정만 저장)
- 항상 최신 데이터 반영
- 비용 효율적

단점:
- 매번 계산 필요 (하지만 1200회 계산은 <1초)

구현:
1. Supabase에는 custom_analyses (설정)만 저장
2. 페이지 로드 시 lotto_draws + config로 실시간 계산
3. 계산 결과는 메모리에서 관리
```

#### 최종 결정: **옵션 B (클라이언트 실시간 계산)**

```javascript
// 페이지 로드 시
async function loadAnalysis(analysisId) {
  // 1. 분석 설정 로드
  const { data: analysis } = await supabaseClient
    .from('custom_analyses')
    .select('*')
    .eq('id', analysisId)
    .single();
  
  // 2. 당첨번호 전체 로드 (이미 캐시되어 있으면 재사용)
  const { data: draws } = await supabaseClient
    .from('lotto_draws')
    .select('*')
    .order('round', { ascending: false });
  
  // 3. 클라이언트에서 실시간 계산
  const results = calculateResults(analysis.config, draws);
  
  // 4. 화면 렌더링
  renderDrawsList(results);
}

function calculateResults(config, draws) {
  return draws.map(draw => {
    const matchCount = countMatches(config, draw.numbers);
    return {
      round: draw.round,
      numbers: draw.numbers,
      matchCount,
      matchNumbers: getMatchedNumbers(config, draw.numbers)
    };
  });
}
```

---

## 🎨 4. UI/UX 디자인 가이드 (기존 패턴 준수)

### 4.1 페이지 레이아웃 (기초분석과 동일)

```html
<body class="bg-[#F9FAFB] font-sans antialiased">
  <div class="flex flex-col h-screen w-full">
    
    <!-- GNB 헤더 -->
    <div id="gnb-container"></div>
    
    <!-- 메인 영역 -->
    <div class="flex flex-1 overflow-hidden">
      
      <!-- LNB 사이드바 -->
      <aside class="w-56 bg-white border-r border-gray-200 overflow-y-auto custom-scrollbar flex-shrink-0" 
             id="lnb-container">
      </aside>
      
      <!-- 컨텐츠 영역 -->
      <main class="flex-1 overflow-y-auto p-8 custom-scrollbar">
        <div class="max-w-7xl mx-auto space-y-6">
          
          <!-- 페이지 제목 -->
          <div>
            <h1 class="text-2xl font-bold text-gray-900 mb-2">분석명</h1>
            <p class="text-sm text-gray-600">설명...</p>
          </div>
          
          <!-- AI 인사이트 섹션 (그라데이션) -->
          <div class="ai-section rounded-2xl p-6 mb-6">
            ...
          </div>
          
          <!-- 메인 컨텐츠 -->
          <div class="bg-white rounded-xl p-6 border border-gray-200 shadow-sm">
            ...
          </div>
          
        </div>
      </main>
      
    </div>
  </div>
</body>
```

### 4.2 색상 팔레트 (기존 유지)

```css
/* 메인 컬러 */
--emerald-500: #10B981;  /* 로고, 활성 상태 */
--blue-500: #3B82F6;     /* 버튼, 링크 */
--blue-600: #2563EB;     /* 버튼 호버 */

/* 그라데이션 (AI 섹션) */
.ai-section { 
  background: linear-gradient(135deg, #E0E7FF 0%, #EDE9FE 50%, #FCE7F3 100%); 
}

/* 상태 색상 */
--red-500: #EF4444;      /* Hot, 에러 */
--green-500: #22C55E;    /* 성공, 필터 ON */
--gray-500: #6B7280;     /* 비활성 */
```

### 4.3 컴포넌트 스타일

#### 버튼

```html
<!-- Primary 버튼 -->
<button class="px-6 py-2.5 text-sm font-bold text-white 
               bg-gradient-to-r from-blue-600 to-indigo-600 
               hover:from-blue-500 hover:to-indigo-500 
               rounded-lg shadow-lg shadow-blue-500/30 transition-all">
  생성하기
</button>

<!-- Secondary 버튼 -->
<button class="px-6 py-2.5 text-sm font-semibold text-gray-700 
               bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors">
  취소
</button>
```

#### 카드

```html
<div class="bg-white rounded-xl p-6 border border-gray-200 shadow-sm">
  <h3 class="text-lg font-bold text-gray-900 mb-4">제목</h3>
  ...
</div>
```

#### 테이블 행

```html
<div class="flex items-center gap-4 py-4 border-b border-gray-100 
            hover:bg-gray-50 transition-colors cursor-pointer">
  <span class="text-sm font-bold text-gray-600 w-16 text-center">1150회</span>
  <div class="flex gap-2 flex-1 justify-center">
    <!-- 번호 볼들 -->
  </div>
  <span class="text-lg font-bold text-red-600 w-20 text-center">3개</span>
</div>
```

---

## 🔧 5. 수식형 통합 UI 상세 설계

### 5.1 탭 구조

```
┌─────────────────────────────────────────────────────────────┐
│ ┌─────────────┬─────────────┬─────────────┐                │
│ │  빠른 선택  │  직접 설정  │  고급 모드  │                │
│ │     ✓      │            │            │                │
│ └─────────────┴─────────────┴─────────────┘                │
│                                                             │
│  [탭 내용 영역]                                             │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  [미리보기] ── 모든 탭 공통 하단                            │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 빠른 선택 템플릿 목록

| 템플릿 ID | 이름 | 설명 | 수식 |
|-----------|------|------|------|
| `plus1` | +1 | 전회차 번호 +1 | `prev.map(n => n+1)` |
| `minus1` | -1 | 전회차 번호 -1 | `prev.map(n => n-1)` |
| `plus2` | +2 | 전회차 번호 +2 | `prev.map(n => n+2)` |
| `minus2` | -2 | 전회차 번호 -2 | `prev.map(n => n-2)` |
| `plus10` | +10 | 전회차 번호 +10 | `prev.map(n => n+10)` |
| `neighbor` | 이웃수 | 전회차 ±1 | `prev ± 1 합집합` |
| `complement` | 보수 | 46 - 전회차 | `prev.map(n => 46-n)` |
| `union2` | 2회 합집합 | 전회차 + 전전회차 | `prev ∪ prev2` |
| `intersect2` | 2회 교집합 | 전회차 ∩ 전전회차 | `prev ∩ prev2` |
| `sameTail` | 끝수 동일 | 전회차와 끝수 같은 번호 | `끝수 매칭` |

### 5.3 직접 설정 연산자 목록

| 연산자 | 이름 | 설명 |
|--------|------|------|
| `add` | + 더하기 | 값을 더함 |
| `subtract` | - 빼기 | 값을 뺌 |
| `multiply` | × 곱하기 | 값을 곱함 |
| `divide` | ÷ 나누기 | 값으로 나눔 (정수) |
| `complement` | 보수 | 46 - N |
| `sameTail` | 끝수 동일 | 끝수가 같은 모든 번호 |

### 5.4 대상 (Target) 목록

| 대상 | 설명 |
|------|------|
| `prev` | 전회차 당첨번호 (6개) |
| `prev2` | 전전회차 당첨번호 |
| `prev3` | 3회전 당첨번호 |
| `prev4` | 4회전 당첨번호 |
| `prev5` | 5회전 당첨번호 |

---

## 🤖 6. AI 연동 설계

### 6.1 AI 자연어 해석 (커스텀 분석 생성 시)

```javascript
// Claude API 호출 (Supabase Edge Function)
async function interpretNaturalLanguage(userPrompt) {
  const { data, error } = await supabaseClient.functions.invoke('interpret-custom-analysis', {
    body: {
      prompt: userPrompt,
      availableTypes: ['direct', 'group', 'formula']
    }
  });
  
  if (error) throw error;
  return data;  // { type, config, confidence }
}
```

### 6.2 AI 분석 인사이트 (결과 페이지)

```javascript
// 기존 패턴과 동일
async function refreshAIAnalysis(analysisConfig, results) {
  const summary = generateSummary(analysisConfig, results);
  
  const { data: analysis, error } = await supabaseClient.functions.invoke('analyze-lotto', {
    body: {
      type: '커스텀분석',
      config: analysisConfig,
      summary: summary
    }
  });
  
  // Utils.formatAIResponse 사용
  document.getElementById('aiAnalysisContent').innerHTML = `
    <div class="flex items-start gap-3">
      <span class="material-symbols-outlined text-purple-600 text-2xl mt-1">insights</span>
      <div class="flex-1">
        <h4 class="font-bold text-gray-900 mb-1">AI 분석</h4>
        <p class="text-sm text-gray-700 leading-relaxed">${Utils.formatAIResponse(analysis.insight)}</p>
      </div>
    </div>
  `;
}
```

---

## 📋 7. 구현 체크리스트

### Phase 1: 기본 구조 (1주)

- [ ] Supabase 테이블 생성 (`custom_analyses`)
- [ ] 커스텀 분석 메인 페이지 레이아웃
- [ ] LNB 동적 메뉴 렌더링
- [ ] 새 분석 모달 (유형 선택)

### Phase 2: 직접입력형 완성 (1주)

- [ ] 분석 생성 (이름만)
- [ ] 번호 선택 UI (1~45개)
- [ ] 회차별 당첨 개수 테이블
- [ ] 필터 설정 및 저장
- [ ] 필터 바로가기

### Phase 3: 그룹형 완성 (1주)

- [ ] 그룹 설정 모달 UI
- [ ] 동적 그룹 추가/삭제
- [ ] 그룹별 당첨 통계 계산
- [ ] 조건 충족 여부 표시

### Phase 4: 수식형 완성 (2주)

- [ ] 3탭 통합 UI
- [ ] 빠른 선택 템플릿
- [ ] 직접 설정 규칙 빌더
- [ ] 고급 모드 블록 빌더 (선택)
- [ ] 실시간 미리보기
- [ ] 수식 실행 엔진

### Phase 5: AI 자연어형 (1주)

- [ ] Edge Function 생성 (`interpret-custom-analysis`)
- [ ] 자연어 입력 UI
- [ ] AI 해석 결과 표시
- [ ] 해석 결과 수정 기능

### Phase 6: 필터 메뉴 연동 (1주)

- [ ] 필터 메뉴에 커스텀 분석 필터 표시
- [ ] 필터 ON/OFF 동기화
- [ ] 조합 생성 시 커스텀 필터 적용

---

## 🎯 8. 결론

### 핵심 결정 사항

| 항목 | 결정 |
|------|------|
| **데이터 저장** | 설정만 Supabase, 결과는 클라이언트 계산 |
| **디자인** | 기존 기초분석 100% 동일 패턴 |
| **AI 연동** | Supabase Edge Function 활용 |
| **수식형** | 3탭 통합 (빠른선택 + 직접설정 + 고급) |

### 예상 개발 기간

| Phase | 기간 | 누적 |
|-------|------|------|
| Phase 1 (기본 구조) | 1주 | 1주 |
| Phase 2 (직접입력형) | 1주 | 2주 |
| Phase 3 (그룹형) | 1주 | 3주 |
| Phase 4 (수식형) | 2주 | 5주 |
| Phase 5 (AI 자연어) | 1주 | 6주 |
| Phase 6 (필터 연동) | 1주 | **7주** |

**총 예상 개발 기간: 7주 (약 1.5개월)**

---

*이 문서는 기존 프로젝트 코드를 직접 분석하여 작성되었습니다.*
