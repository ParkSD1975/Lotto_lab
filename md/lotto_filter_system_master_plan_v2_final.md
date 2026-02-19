# 🚀 로또 AI 동적 필터 시스템 - 종합 개발 계획서 v2.0

---

## 📌 1. 프로젝트 개요

### 1.1 목표
하드코딩된 개별 HTML 필터 페이지를 **DB 기반의 중앙 관리형 시스템**으로 전환하고, AI가 생성한 필터 전략을 즉시 적용할 수 있는 유연한 아키텍처 구축.

### 1.2 핵심 가치

| 가치 | 설명 |
|------|------|
| **유연성** | DB 설정 변경만으로 모든 페이지의 UI/로직 즉시 반영 |
| **확장성** | '불연속 값(Discrete Value)' 선택 지원으로 분석 정밀도 향상 |
| **동기화** | 기기 간 설정 동기화 및 과거 분석 이력(Snapshot) 완벽 복원 |
| **AI 통합** | AI가 발견한 패턴을 즉시 시스템 필터로 자동 생성 및 배포 |

### 1.3 결정사항 요약

| 항목 | 결정 | 설명 |
|------|------|------|
| 회차별 저장 | **둘 다** | 프리셋 + 회차별 이력 테이블 모두 구현 |
| 불연속 값 선택 | **지원** | selectedValues 배열로 개별 값 선택 가능 |
| 검증 시스템 | **Phase 2** | 전체 시스템 완성 후 추가 |
| HTML 수정 범위 | **전면 리팩토링** | 동적 UI 렌더링으로 전환 |
| AI 자동 필터 | **처음부터** | 설계 단계부터 포함 |

---

## 📌 2. 시스템 아키텍처

### 2.1 전체 구조도

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Supabase Database                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────┐    ┌─────────────────────┐                        │
│  │ filter_definitions  │    │ user_filter_presets │                        │
│  │ (필터 메타데이터)     │    │ (사용자 프리셋)      │                        │
│  │                     │    │                     │                        │
│  │ - system 필터       │    │ - 프리셋 그룹        │                        │
│  │ - custom 필터       │    │ - is_default        │                        │
│  │ - ai_generated 필터 │    └──────────┬──────────┘                        │
│  └──────────┬──────────┘               │                                   │
│             │                          │                                   │
│             │         ┌────────────────┴────────────────┐                  │
│             │         │                                 │                  │
│             ▼         ▼                                 ▼                  │
│  ┌─────────────────────────────┐    ┌─────────────────────────────┐       │
│  │     filter_settings         │    │    analysis_history         │       │
│  │     (필터 설정값)            │    │    (분석 이력 스냅샷)        │       │
│  │                             │    │                             │       │
│  │ - preset_id (FK)            │    │ - target_round              │       │
│  │ - filter_definition_id (FK) │    │ - filter_snapshot (JSONB)   │       │
│  │ - settings (JSONB)          │    │ - analysis_type             │       │
│  │ - target_round (선택)       │    │ - result_summary            │       │
│  └─────────────────────────────┘    └─────────────────────────────┘       │
│                                                                             │
│  ┌─────────────────────────────┐  (Phase 2에서 추가)                        │
│  │ filter_verification_stats   │                                           │
│  │ (필터 검증 통계)             │                                           │
│  └─────────────────────────────┘                                           │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Frontend (JavaScript)                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐          │
│  │ FilterService.js │  │DynamicRenderer.js│  │ FilterState.js   │          │
│  │                  │  │                  │  │                  │          │
│  │ - DB CRUD        │  │ - JSON Schema    │  │ - 전역 상태 관리  │          │
│  │ - 활성필터 조회   │  │   → UI 자동생성  │  │ - 변경 감지      │          │
│  │ - AI 데이터 포맷  │  │ - 이벤트 바인딩  │  │ - 자동 저장      │          │
│  │ - 캐싱           │  │                  │  │                  │          │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘          │
│                                    │                                        │
│                                    ▼                                        │
│  ┌──────────────────────────────────────────────────────────────┐          │
│  │                    각 분석 페이지 (HTML)                       │          │
│  │                                                              │          │
│  │  <div id="filter-container"></div>  ← 동적 렌더링 영역        │          │
│  │                                                              │          │
│  └──────────────────────────────────────────────────────────────┘          │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 데이터베이스 테이블 요약

| 테이블명 | 역할 | 핵심 컬럼 |
|----------|------|-----------|
| **`filter_definitions`** | 필터 설계도 (메타데이터) | `filter_key`, `settings_schema` (JSON), `ui_config`, `filter_type`, `ai_metadata` |
| **`user_filter_presets`** | 사용자 설정 그룹 | `preset_name`, `is_default`, `tags` |
| **`filter_settings`** | 실제 적용된 설정값 | `preset_id`, `settings` (JSON), `enabled`, `target_round` |
| **`analysis_history`** | 분석 시점 스냅샷 | `target_round`, `filter_snapshot` (당시 설정 전체 복사본), `result_summary` |

### 2.3 프론트엔드 모듈 구조

HTML은 껍데기 역할만 하며, 실제 UI는 자바스크립트가 동적으로 생성합니다.

```
js/filter/
├── FilterService.js      # DB 통신 담당 (CRUD, 캐싱, 데이터 포맷팅)
├── FilterState.js        # 전역 상태 관리 (설정 변경 감지 및 자동 저장)
├── DynamicRenderer.js    # JSON Schema를 해석하여 UI 자동 생성
├── FilterValidator.js    # 유효성 검사 (Min > Max 등 논리 오류 차단)
└── renderers/            # 개별 UI 컴포넌트
    ├── RangeRenderer.js
    ├── DiscreteSelectRenderer.js  # 범위/개별선택 하이브리드
    ├── MultiSelectRenderer.js
    ├── CategoryRangeRenderer.js
    ├── ToggleButtonsRenderer.js
    ├── CheckboxGroupRenderer.js
    ├── DragDropRenderer.js
    └── CustomRenderer.js
```

---

## 📌 3. 데이터베이스 스키마 상세

### 3.1 filter_definitions (필터 정의 테이블)

```sql
CREATE TABLE filter_definitions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  
  -- 기본 정보
  filter_key VARCHAR(100) UNIQUE NOT NULL,    -- 'ac_filter', 'custom_ai_123'
  filter_name VARCHAR(100) NOT NULL,          -- 'AC값', 'AI 패턴 분석'
  filter_name_en VARCHAR(100),                -- 영문명 (옵션)
  description TEXT,                           -- 필터 설명
  
  -- 분류
  category VARCHAR(50) NOT NULL DEFAULT 'system',
    -- 'system': 시스템 기본 필터 (18개)
    -- 'custom': 사용자 커스텀 필터
    -- 'ai_generated': AI가 자동 생성한 필터
  
  filter_type VARCHAR(20) NOT NULL,
    -- 'TYPE_A': Set 기반 (개수/비율 선택)
    -- 'TYPE_B': 범위 + 개별값 선택 (불연속 지원)
    -- 'TYPE_C': 다중 카테고리 범위
    -- 'TYPE_D': 불리언 조합
    -- 'TYPE_E': 고정/제외
    -- 'TYPE_CUSTOM': AI/사용자 커스텀
  
  -- 소유권 (시스템 필터는 NULL)
  owner_user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  
  -- 스키마 정의 (핵심!)
  settings_schema JSONB NOT NULL DEFAULT '{}',    -- UI 렌더링 규칙
  default_settings JSONB NOT NULL DEFAULT '{"enabled": false}',
  
  -- UI 설정
  ui_config JSONB DEFAULT '{}',               -- 아이콘, 색상 등
  display_order INTEGER DEFAULT 999,          -- 정렬 순서
  
  -- 상태
  is_active BOOLEAN DEFAULT true,
  is_public BOOLEAN DEFAULT false,            -- 다른 사용자에게 공개 여부
  
  -- AI 생성 메타데이터
  ai_metadata JSONB DEFAULT NULL,
    -- {"confidence": 0.85, "source_rounds": [1140, 1141], "pattern_type": "..."}
  
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 인덱스
CREATE INDEX idx_filter_def_key ON filter_definitions(filter_key);
CREATE INDEX idx_filter_def_category ON filter_definitions(category);
CREATE INDEX idx_filter_def_owner ON filter_definitions(owner_user_id);
CREATE INDEX idx_filter_def_active ON filter_definitions(is_active);
CREATE INDEX idx_filter_def_order ON filter_definitions(display_order);
```

### 3.2 user_filter_presets (사용자 프리셋 테이블)

```sql
CREATE TABLE user_filter_presets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  
  preset_name VARCHAR(100) NOT NULL,          -- '기본 설정', '공격적 필터'
  description TEXT,
  is_default BOOLEAN DEFAULT false,
  
  -- 프리셋 메타데이터
  tags VARCHAR(50)[] DEFAULT '{}',            -- ['공격적', '보수적', '고배당']
  
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  
  UNIQUE(user_id, preset_name)
);

-- 인덱스
CREATE INDEX idx_presets_user ON user_filter_presets(user_id);
CREATE INDEX idx_presets_default ON user_filter_presets(user_id, is_default);
```

### 3.3 filter_settings (필터 설정값 테이블)

```sql
CREATE TABLE filter_settings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  
  preset_id UUID NOT NULL REFERENCES user_filter_presets(id) ON DELETE CASCADE,
  filter_definition_id UUID NOT NULL REFERENCES filter_definitions(id) ON DELETE CASCADE,
  
  -- 설정값 (JSONB - 유연한 구조)
  settings JSONB NOT NULL DEFAULT '{}',
  enabled BOOLEAN DEFAULT false,
  
  -- 회차 지정 (선택적)
  target_round INTEGER DEFAULT NULL,
    -- NULL: 범용 설정 (기본 프리셋)
    -- 숫자: 특정 회차용 설정
  
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  
  -- 복합 유니크 제약
  UNIQUE(preset_id, filter_definition_id, COALESCE(target_round, 0))
);

-- 인덱스
CREATE INDEX idx_settings_preset ON filter_settings(preset_id);
CREATE INDEX idx_settings_def ON filter_settings(filter_definition_id);
CREATE INDEX idx_settings_round ON filter_settings(target_round);
CREATE INDEX idx_settings_enabled ON filter_settings(enabled);
CREATE INDEX idx_settings_jsonb ON filter_settings USING GIN (settings);
```

### 3.4 analysis_history (분석 이력 테이블)

```sql
CREATE TABLE analysis_history (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  
  -- 분석 대상
  target_round INTEGER NOT NULL,              -- 분석 대상 회차
  analysis_type VARCHAR(50) NOT NULL,
    -- 'basic': 기본 분석
    -- 'custom': 커스텀 분석
    -- 'ai': AI 분석
  
  -- 당시 사용한 필터 스냅샷 (완전한 복사본) - 핵심!
  preset_id UUID REFERENCES user_filter_presets(id) ON DELETE SET NULL,
  preset_name VARCHAR(100),                   -- 프리셋 삭제되어도 이름은 보존
  filter_snapshot JSONB NOT NULL,
    -- 당시 활성화된 모든 필터와 설정값의 완전한 복사본
    -- [{"filter_key": "ac_filter", "filter_name": "AC값", "settings": {...}, "enabled": true}, ...]
  
  -- 분석 결과 요약
  result_summary JSONB,
    -- {"generated_numbers": [[1,2,3,4,5,6], ...], "ai_comment": "..."}
  
  -- 메타데이터
  notes TEXT,                                 -- 사용자 메모
  
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 인덱스
CREATE INDEX idx_history_user ON analysis_history(user_id);
CREATE INDEX idx_history_round ON analysis_history(target_round);
CREATE INDEX idx_history_user_round ON analysis_history(user_id, target_round);
CREATE INDEX idx_history_type ON analysis_history(analysis_type);
CREATE INDEX idx_history_created ON analysis_history(created_at DESC);
```

### 3.5 filter_verification_stats (Phase 2에서 구현)

```sql
-- Phase 2에서 추가 예정
CREATE TABLE filter_verification_stats (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  
  round INTEGER NOT NULL,                     -- 검증 대상 회차
  filter_key VARCHAR(100) NOT NULL,
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  
  -- 당시 설정 (스냅샷)
  setting_min INTEGER,
  setting_max INTEGER,
  setting_values INTEGER[],                   -- 불연속 선택의 경우
  
  -- 실제 결과
  actual_value INTEGER NOT NULL,              -- 실제 해당 회차의 값
  
  -- 판정
  result_status VARCHAR(20) NOT NULL,
    -- 'SUCCESS': 범위 내 적중
    -- 'FAIL_LOW': 설정 미만
    -- 'FAIL_HIGH': 설정 초과
    -- 'FAIL_NOT_IN_SET': 불연속 집합에 미포함
  
  is_success BOOLEAN GENERATED ALWAYS AS (result_status = 'SUCCESS') STORED,
  
  created_at TIMESTAMPTZ DEFAULT NOW(),
  
  UNIQUE(round, filter_key, user_id)
);

-- 인덱스
CREATE INDEX idx_verify_user ON filter_verification_stats(user_id);
CREATE INDEX idx_verify_round ON filter_verification_stats(round);
CREATE INDEX idx_verify_filter ON filter_verification_stats(filter_key);
CREATE INDEX idx_verify_success ON filter_verification_stats(is_success);
```

### 3.6 RLS (Row Level Security) 정책

```sql
-- filter_definitions RLS
ALTER TABLE filter_definitions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Anyone can read system and public filters"
  ON filter_definitions FOR SELECT
  USING (category = 'system' OR owner_user_id = auth.uid() OR is_public = true);

CREATE POLICY "Owners can manage their filters"
  ON filter_definitions FOR ALL
  USING (owner_user_id = auth.uid())
  WITH CHECK (owner_user_id = auth.uid());

CREATE POLICY "Authenticated users can create custom filters"
  ON filter_definitions FOR INSERT
  WITH CHECK (auth.uid() IS NOT NULL AND category IN ('custom', 'ai_generated'));

-- user_filter_presets RLS
ALTER TABLE user_filter_presets ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can manage their own presets"
  ON user_filter_presets FOR ALL
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

-- filter_settings RLS
ALTER TABLE filter_settings ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can manage settings through their presets"
  ON filter_settings FOR ALL
  USING (
    EXISTS (
      SELECT 1 FROM user_filter_presets
      WHERE id = filter_settings.preset_id AND user_id = auth.uid()
    )
  );

-- analysis_history RLS
ALTER TABLE analysis_history ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can manage their own history"
  ON analysis_history FOR ALL
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());
```

---

## 📌 4. 핵심 기능 상세

### 4.1 불연속 값 선택 (Discrete Selection)

기존의 단순 범위(Min~Max) 선택을 넘어, **특정 값만 콕 집어 선택**할 수 있는 기능.

#### 적용 대상
- `ac_filter` (AC값): 0~10
- `total_sum_filter` (총합): 21~255
- `tail_sum_filter` (끝수합): 0~54

#### settings 구조
```json
{
  "min": 5,
  "max": 9,
  "selectedValues": [5, 7, 9],
  "useDiscreteSelection": true,
  "enabled": true
}
```

#### UI 설계
```
┌─────────────────────────────────────────────┐
│  [범위 선택]  [개별 선택]  ← 탭으로 모드 전환 │
├─────────────────────────────────────────────┤
│                                             │
│  【범위 모드】                               │
│  최소 [5] ──────────── 최대 [9]             │
│                                             │
│  【개별 선택 모드】                          │
│  ┌────┬────┬────┬────┬────┬────┐           │
│  │ 0  │ 1  │ 2  │ 3  │ 4  │ 5✓ │           │
│  ├────┼────┼────┼────┼────┼────┤           │
│  │ 6  │ 7✓ │ 8  │ 9✓ │ 10 │    │           │
│  └────┴────┴────┴────┴────┴────┘           │
│  [전체 선택] [전체 해제]                     │
└─────────────────────────────────────────────┘
```

#### 효과
- "AC값 6, 7, 8만 포함" 같은 정밀 필터링 가능
- 통계 모달에서 체크박스 선택 시 자동으로 개별 선택 모드 전환

### 4.2 AI 자동 필터 생성 (AI-Generated Filters)

AI가 발견한 패턴을 시스템이 이해할 수 있는 필터로 **자동 변환**.

#### 프로세스
```
AI 패턴 발견 
    ↓
filter_definitions에 TYPE_CUSTOM으로 INSERT
    ↓
사용자에게 새 필터 알림
    ↓
즉시 사용 가능
```

#### 저장 예시
```json
{
  "filter_key": "ai_abc123_1705312800000",
  "filter_name": "AI 발견: 홀짝 연속 패턴",
  "category": "ai_generated",
  "filter_type": "TYPE_CUSTOM",
  "settings_schema": {
    "type": "object",
    "properties": {
      "conditions": { "type": "array" },
      "confidence": { "type": "number" }
    }
  },
  "ai_metadata": {
    "confidence": 0.85,
    "discovered_at": "2024-01-15T10:00:00Z",
    "source_rounds": [1140, 1141, 1142],
    "pattern_type": "odd_even_sequence"
  }
}
```

### 4.3 분석 이력 및 스냅샷

단순 결과 저장이 아니라, **"당시 어떤 필터 조합으로 분석했는지"** 완벽 저장.

#### 저장 내용
- 활성화된 모든 필터의 ID, 이름, 설정값, ON/OFF 상태
- 분석 대상 회차
- 분석 유형 (기본/커스텀/AI)
- 결과 요약

#### 활용
- 과거 1등 당첨 시점의 분석 환경을 **원클릭으로 복원(Recall)** 가능
- "1150회차 때 어떤 필터 썼더라?" 조회 가능

#### filter_snapshot 예시
```json
[
  {
    "filter_key": "ac_filter",
    "filter_name": "AC값",
    "settings": {"min": 7, "max": 10, "useDiscreteSelection": false},
    "enabled": true
  },
  {
    "filter_key": "carryover_filter",
    "filter_name": "이월수",
    "settings": {"selectedCounts": [1, 2, 3]},
    "enabled": true
  },
  {
    "filter_key": "prime_filter",
    "filter_name": "소수",
    "settings": {"selectedCounts": [2, 3], "excludedNumbers": [43]},
    "enabled": false
  }
]
```

---

## 📌 5. settings_schema 구조 정의

### 5.1 기본 인터페이스

```typescript
interface SettingsSchema {
  type: 'object';
  properties: Record<string, PropertyDefinition>;
  uiHints: UIHints;
}

interface PropertyDefinition {
  type: 'integer' | 'number' | 'string' | 'boolean' | 'array' | 'object';
  minimum?: number;
  maximum?: number;
  items?: PropertyDefinition;
  enum?: (string | number)[];
  description?: string;
}

interface UIHints {
  renderType: 'range_slider' | 'range_with_discrete' | 'multi_select' | 
              'checkbox_group' | 'toggle_buttons' | 'category_ranges' | 
              'drag_drop' | 'custom';
  valueRange?: [number, number];
  selectableValues?: number[] | string[];
  categories?: string[];
  numberSet?: number[];
  chartType?: 'distribution' | 'trend' | 'none';
  hasStatsModal?: boolean;
  gridColumns?: number;
}
```

### 5.2 필터 타입별 스키마 예시

#### TYPE_A (Set 기반) - 소수 필터
```json
{
  "settings_schema": {
    "type": "object",
    "properties": {
      "selectedCounts": {
        "type": "array",
        "items": {"type": "integer", "minimum": 0, "maximum": 6}
      },
      "excludedNumbers": {
        "type": "array",
        "items": {"type": "integer", "minimum": 1, "maximum": 45}
      }
    },
    "uiHints": {
      "renderType": "multi_select",
      "valueRange": [0, 6],
      "numberSet": [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43],
      "hasStatsModal": true,
      "gridColumns": 7
    }
  }
}
```

#### TYPE_B (범위 + 불연속) - AC값 필터
```json
{
  "settings_schema": {
    "type": "object",
    "properties": {
      "min": {"type": "integer", "minimum": 0, "maximum": 10},
      "max": {"type": "integer", "minimum": 0, "maximum": 10},
      "selectedValues": {
        "type": "array",
        "items": {"type": "integer", "minimum": 0, "maximum": 10}
      },
      "useDiscreteSelection": {"type": "boolean"}
    },
    "uiHints": {
      "renderType": "range_with_discrete",
      "valueRange": [0, 10],
      "selectableValues": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
      "hasStatsModal": true,
      "chartType": "distribution"
    }
  }
}
```

#### TYPE_C (다중 카테고리) - 번호대별 필터
```json
{
  "settings_schema": {
    "type": "object",
    "properties": {
      "ranges": {
        "type": "object",
        "additionalProperties": {
          "type": "object",
          "properties": {
            "min": {"type": "integer"},
            "max": {"type": "integer"}
          }
        }
      }
    },
    "uiHints": {
      "renderType": "category_ranges",
      "categories": ["단번대", "10번대", "20번대", "30번대", "40번대"]
    }
  }
}
```

#### TYPE_CUSTOM (AI 생성) - 동적 조건
```json
{
  "settings_schema": {
    "type": "object",
    "properties": {
      "conditions": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "field": {"type": "string"},
            "operator": {"enum": ["eq", "gt", "lt", "gte", "lte", "in", "between"]},
            "value": {}
          }
        }
      },
      "logic": {"enum": ["AND", "OR"]},
      "confidence": {"type": "number"}
    },
    "uiHints": {
      "renderType": "custom",
      "displayType": "ai_pattern"
    }
  }
}
```

---

## 📌 6. 프론트엔드 모듈 상세

### 6.1 FilterService.js 핵심 메서드

```javascript
class FilterService {
  constructor(supabaseClient) {
    this.client = supabaseClient;
    this.cache = new Map();  // 성능 최적화용 캐시
  }

  // ========== 필터 정의 ==========
  async loadDefinitions(userId = null)           // 모든 활성 필터 정의 로드
  async getDefinitionByKey(filterKey)            // 특정 필터 정의 조회
  async getOrCreateRegressionFilter(filterKey)   // 회귀 필터 동적 생성 (2~200)

  // ========== 프리셋 ==========
  async getPresets(userId)                       // 사용자 프리셋 목록
  async getOrCreateDefaultPreset(userId)         // 기본 프리셋 조회/생성

  // ========== 설정값 ==========
  async loadSettings(presetId, targetRound)      // 프리셋의 필터 설정 로드
  async saveSetting(presetId, defId, settings)   // 단일 필터 설정 저장
  async saveSettingsBulk(presetId, settingsArr)  // 여러 필터 일괄 저장

  // ========== 분석 이력 ==========
  async saveAnalysisHistory(...)                 // 분석 이력 저장 (스냅샷 포함)
  async getAnalysisHistory(userId, round, limit) // 분석 이력 조회

  // ========== AI 통합 ==========
  formatFiltersForAI(activeFilters)              // AI 프롬프트용 텍스트 생성
  async createAIGeneratedFilter(userId, pattern) // AI 필터 자동 생성

  // ========== 마이그레이션 ==========
  async migrateFromLocalStorage(userId)          // localStorage → DB 이관
}
```

### 6.2 DynamicRenderer.js 핵심 구조

```javascript
class DynamicRenderer {
  constructor(containerId, filterService, filterState) {
    this.container = document.getElementById(containerId);
    this.filterService = filterService;
    this.filterState = filterState;
    this.renderers = new Map();
    this._registerDefaultRenderers();
  }

  _registerDefaultRenderers() {
    this.renderers.set('range_slider', RangeRenderer);
    this.renderers.set('range_with_discrete', DiscreteSelectRenderer);
    this.renderers.set('multi_select', MultiSelectRenderer);
    this.renderers.set('toggle_buttons', ToggleButtonsRenderer);
    this.renderers.set('category_ranges', CategoryRangeRenderer);
    this.renderers.set('checkbox_group', CheckboxGroupRenderer);
    this.renderers.set('drag_drop', DragDropRenderer);
    this.renderers.set('custom', CustomRenderer);
  }

  render(definitions, currentSettings)     // 전체 필터 UI 렌더링
  _renderSingleFilter(definition, setting) // 개별 필터 렌더링
  _createHeader(definition, setting)       // 필터 헤더 (이름 + 토글)
  refresh(filterKey)                       // 특정 필터 UI 새로고침
}
```

### 6.3 FilterState.js 핵심 구조

```javascript
class FilterState {
  constructor() {
    this.state = new Map();       // filterKey → settings
    this.listeners = [];          // 변경 감지 리스너
    this.autoSaveEnabled = true;
  }

  get(filterKey)                           // 설정값 조회
  set(filterKey, settings)                 // 설정값 저장
  setEnabled(filterKey, enabled)           // 활성화 토글
  updateSettings(filterKey, partialUpdate) // 부분 업데이트
  
  getActiveFilters()                       // 활성화된 필터만 반환
  
  onChange(callback)                       // 변경 감지 리스너 등록
  _notifyChange(filterKey, settings)       // 리스너에 변경 알림
}
```

---

## 📌 7. HTML 페이지 변경 가이드

### 7.1 변경 전 (현재)

```html
<!-- ac_value.html - 하드코딩된 방식 -->
<div class="filter-section">
  <div class="flex gap-2">
    <input type="number" id="minFilter" min="0" max="10" value="0">
    <span>~</span>
    <input type="number" id="maxFilter" min="0" max="10" value="10">
  </div>
  <label>
    <input type="checkbox" id="applyFilterCheck"> 필터 적용
  </label>
</div>

<script>
function saveFilterSettings() {
  const data = {
    min: parseInt(document.getElementById('minFilter').value),
    max: parseInt(document.getElementById('maxFilter').value),
    enabled: document.getElementById('applyFilterCheck').checked
  };
  window.Utils.saveFilter('ac_filter', data);  // localStorage
}
</script>
```

### 7.2 변경 후 (동적 방식)

```html
<!-- ac_value.html - 동적 렌더링 방식 -->
<div id="filter-container"></div>

<script src="js/filter/FilterService.js"></script>
<script src="js/filter/FilterState.js"></script>
<script src="js/filter/DynamicRenderer.js"></script>
<script src="js/filter/renderers/DiscreteSelectRenderer.js"></script>

<script>
document.addEventListener('DOMContentLoaded', async () => {
  // 1. 서비스 초기화
  const filterService = new FilterService(window.supabaseClient);
  const filterState = new FilterState();
  const renderer = new DynamicRenderer('filter-container', filterService, filterState);
  
  // 2. 사용자 인증 확인
  const { data: { user } } = await supabaseClient.auth.getUser();
  if (!user) {
    // 비로그인 시 localStorage 모드로 fallback
    return;
  }
  
  // 3. localStorage → DB 마이그레이션 (최초 1회)
  await filterService.migrateFromLocalStorage(user.id);
  
  // 4. 필터 정의 및 설정 로드
  const definition = await filterService.getDefinitionByKey('ac_filter');
  const preset = await filterService.getOrCreateDefaultPreset(user.id);
  const settings = await filterService.loadSettings(preset.id);
  
  // 5. UI 렌더링
  renderer.render([definition], settings);
  
  // 6. 상태 변경 시 자동 저장
  filterState.onChange(async (filterKey, newSettings) => {
    await filterService.saveSetting(
      preset.id, 
      definition.id, 
      newSettings, 
      newSettings.enabled
    );
  });
});
</script>
```

### 7.3 통계 모달 변경

```javascript
// 기존: 체크박스 → Min/Max로 변환
function toggleAcFilter(acValue, checked) {
  minFilterInput.value = Math.min(...checkedValues);
  maxFilterInput.value = Math.max(...checkedValues);
}

// 변경: 체크박스 → 개별 선택 모드로 자동 전환
function toggleStatsCheckbox(value, checked) {
  const state = filterState.get('ac_filter');
  
  // 자동으로 개별 선택 모드로 전환
  state.useDiscreteSelection = true;
  
  if (!state.selectedValues) state.selectedValues = [];
  
  if (checked) {
    if (!state.selectedValues.includes(value)) {
      state.selectedValues.push(value);
      state.selectedValues.sort((a, b) => a - b);
    }
  } else {
    state.selectedValues = state.selectedValues.filter(v => v !== value);
  }
  
  filterState.update('ac_filter', state);
  renderer.refresh('ac_filter');  // 메인 UI도 업데이트
}
```

### 7.4 페이지별 변경 범위

| 페이지 | 현재 상태 | 변경 사항 |
|--------|----------|-----------|
| **ac_value.html** | Min/Max만 | 불연속 선택 모드 추가, 모달 연동 |
| **total_sum.html** | Min/Max만 | 불연속 선택 모드 추가 |
| **tail_sum.html** | Min/Max만 | 불연속 선택 모드 추가 |
| **prime_number.html** | 개수+제외 | 이미 잘됨, 통합만 |
| **square_number.html** | 개수+제외 | 이미 잘됨, 통합만 |
| **composite_number.html** | ❌ 미구현 | 신규 구현 (prime과 동일) |
| **hot_cold.html** | 범위만 | 제외수/고정수 저장 추가 |
| **regression.html** | 단일 키 | 회귀별 분리 (2~200) |
| **missing.html** | localStorage 직접 | Utils 패턴으로 통일 |
| 기타 페이지들 | 다양 | 동적 렌더링으로 통일 |

---

## 📌 8. 단계별 구현 로드맵

### Phase 1: 인프라 구축 (1.5일)

#### Step 1: DB 테이블 생성 (1일)
```
□ 1-1. filter_definitions 테이블 생성
□ 1-2. user_filter_presets 테이블 생성
□ 1-3. filter_settings 테이블 생성 (target_round 포함)
□ 1-4. analysis_history 테이블 생성
□ 1-5. RLS 정책 설정
□ 1-6. 인덱스 생성
□ 1-7. updated_at 자동 갱신 트리거 생성
```

#### Step 2: 시스템 필터 Seed (0.5일)
```
□ 2-1. TYPE_A 필터 7개 INSERT (이월수, 홀짝, 저고, 쌍수, 소수, 제곱수, 합성수)
□ 2-2. TYPE_B 필터 4개 INSERT (AC값, 총합, 끝수합, 이웃수)
□ 2-3. TYPE_B 회귀 템플릿 INSERT
□ 2-4. TYPE_C 필터 4개 INSERT (번호대, 배수, 핫콜드, 끝수별)
□ 2-5. TYPE_D 필터 1개 INSERT (연속번호)
□ 2-6. TYPE_E 필터 1개 INSERT (번호별통계)
□ 2-7. settings_schema에 불연속 지원(useDiscreteSelection) 추가
```

### Phase 2: 코어 모듈 개발 (2일)

#### Step 3: 공통 JS 모듈 (2일)
```
□ 3-1. FilterService.js 구현
       - DB CRUD 메서드
       - 캐싱 로직
       - 회귀 필터 동적 생성
       - localStorage 마이그레이션
       - AI 포맷팅
□ 3-2. FilterState.js 구현
       - 전역 상태 관리
       - 변경 감지 및 자동 저장
□ 3-3. DynamicRenderer.js 구현
       - JSON Schema 파싱
       - 렌더러 등록 및 호출
□ 3-4. DiscreteSelectRenderer.js 구현 (핵심!)
       - 범위/개별선택 하이브리드 UI
       - 모드 전환 탭
□ 3-5. 기타 렌더러 구현
       - RangeRenderer.js
       - MultiSelectRenderer.js
       - CategoryRangeRenderer.js
       - ToggleButtonsRenderer.js
       - DragDropRenderer.js
       - CustomRenderer.js
□ 3-6. FilterValidator.js 구현
       - Min > Max 등 논리 오류 차단
```

### Phase 3: 화면 전환 및 마이그레이션 (3일)

#### Step 4: 기존 HTML 마이그레이션 (3일)
```
□ 4-1. common_v2.js 수정
       - 마이그레이션 로직 추가
       - 비로그인 시 fallback 처리
□ 4-2. ac_value.html 전환 (불연속 선택 포함) - 파일럿
□ 4-3. total_sum.html 전환
□ 4-4. tail_sum.html 전환
□ 4-5. prime_number.html 전환
□ 4-6. square_number.html 전환
□ 4-7. composite_number.html 신규 구현
□ 4-8. hot_cold.html 전환 (제외수/고정수 저장 추가)
□ 4-9. regression.html 전환 (회귀별 분리)
□ 4-10. 나머지 페이지들 순차 전환
        - carryover.html
        - odd_even.html
        - low_high.html
        - twin_number.html
        - neighbor_number.html
        - number_range.html
        - multiple.html
        - tail_digit.html
        - consecutive_number.html
        - stats_by_number.html
        - missing.html (localStorage → Utils 통일)
```

### Phase 4: 통합 및 고도화 (1.5일)

#### Step 5: 커스텀분석 페이지 통합 (1일)
```
□ 5-1. 필터 선택 통합 UI 구축
       - 모든 필터를 한눈에 보고 제어
□ 5-2. 분석 실행 시 analysis_history 저장
       - filter_snapshot 생성
       - result_summary 저장
□ 5-3. AI customData에 활성 필터 정보 포함
       - formatFiltersForAI() 호출
□ 5-4. 과거 분석 이력 조회/복원 UI
```

#### Step 6: AI 자동 필터 생성 (0.5일)
```
□ 6-1. AI 분석 결과에서 패턴 감지 로직
□ 6-2. createAIGeneratedFilter() 호출 연동
□ 6-3. 사용자에게 새 필터 알림 UI
□ 6-4. 커스텀 필터 관리 UI (활성화/비활성화/삭제)
```

### Phase 5: 검증 시스템 (추후)

#### Step 7: 검증 시스템 (Phase 2에서 구현)
```
□ 7-1. filter_verification_stats 테이블 생성
□ 7-2. 추첨 후 자동 검증 Edge Function 개발
       - actual_value 계산
       - result_status 판정
□ 7-3. 적중률 통계 API
□ 7-4. 적중률 대시보드 UI
□ 7-5. AI 보정 제안 기능
       - "범위를 1~4로 넓히세요" 등
```

---

## 📌 9. 개발 전략 및 주의사항

### 9.1 마이그레이션 안전장치

기존 사용자의 설정이 날아가지 않도록, **최초 접속 시 localStorage 데이터를 DB로 백업**하는 로직 필수.

```javascript
// FilterService.js 초기화 시
async initialize(userId) {
  const migrationKey = `lotto_filter_migrated_${userId}`;
  
  if (!localStorage.getItem(migrationKey)) {
    const result = await this.migrateFromLocalStorage(userId);
    if (result.migrated > 0) {
      localStorage.setItem(migrationKey, 'true');
      console.log(`✅ ${result.migrated}개 필터 마이그레이션 완료`);
    }
  }
}
```

### 9.2 성능 최적화

필터 정의(`filter_definitions`)는 자주 바뀌지 않으므로 **캐싱** 활용.

```javascript
class FilterService {
  constructor() {
    this.definitionsCache = null;
    this.cacheExpiry = null;
    this.CACHE_TTL = 5 * 60 * 1000; // 5분
  }

  async loadDefinitions(userId) {
    // 캐시 유효한 경우 바로 반환
    if (this.definitionsCache && Date.now() < this.cacheExpiry) {
      return this.definitionsCache;
    }
    
    // DB 조회
    const data = await this._fetchDefinitionsFromDB(userId);
    
    // 캐시 저장
    this.definitionsCache = data;
    this.cacheExpiry = Date.now() + this.CACHE_TTL;
    
    return data;
  }
}
```

### 9.3 오류 방지

`FilterValidator.js`를 통해 논리적 오류를 **입력 단계에서 차단**.

```javascript
class FilterValidator {
  static validateTypeB(settings) {
    const errors = [];
    
    if (settings.min > settings.max) {
      errors.push('최소값이 최대값보다 클 수 없습니다.');
    }
    
    if (settings.useDiscreteSelection && 
        (!settings.selectedValues || settings.selectedValues.length === 0)) {
      errors.push('개별 선택 모드에서 최소 1개 이상 선택해야 합니다.');
    }
    
    return { isValid: errors.length === 0, errors };
  }
}
```

### 9.4 비로그인 사용자 처리

로그인하지 않은 사용자는 기존 localStorage 방식으로 **fallback**.

```javascript
async function initializeFilterSystem() {
  const { data: { user } } = await supabaseClient.auth.getUser();
  
  if (user) {
    // 로그인 사용자: DB 기반
    return new FilterService(supabaseClient);
  } else {
    // 비로그인: localStorage 기반 (기존 방식)
    return new LocalStorageFilterService();
  }
}
```

---

## 📌 10. 파일 산출물 목록

```
📁 supabase_migrations/
├── 001_create_filter_definitions.sql
├── 002_create_user_filter_presets.sql
├── 003_create_filter_settings.sql
├── 004_create_analysis_history.sql
├── 005_create_rls_policies.sql
├── 006_create_indexes_triggers.sql
└── 007_seed_system_filters.sql

📁 js/filter/
├── FilterService.js          # DB CRUD, 캐싱, 마이그레이션
├── FilterState.js            # 전역 상태 관리
├── DynamicRenderer.js        # UI 동적 생성
├── FilterValidator.js        # 유효성 검사
├── LocalStorageFilterService.js  # 비로그인 fallback
└── renderers/
    ├── RangeRenderer.js
    ├── DiscreteSelectRenderer.js   # 핵심! 불연속 선택
    ├── MultiSelectRenderer.js
    ├── CategoryRangeRenderer.js
    ├── ToggleButtonsRenderer.js
    ├── CheckboxGroupRenderer.js
    ├── DragDropRenderer.js
    └── CustomRenderer.js

📁 수정될 HTML 파일/ (18개)
├── ac_value.html
├── total_sum.html
├── tail_sum.html
├── prime_number.html
├── square_number.html
├── composite_number.html     # 신규 구현
├── hot_cold.html
├── regression.html
├── carryover.html
├── odd_even.html
├── low_high.html
├── twin_number.html
├── neighbor_number.html
├── number_range.html
├── multiple.html
├── tail_digit.html
├── consecutive_number.html
├── stats_by_number.html
└── missing.html

📁 신규 페이지/
└── custom_analysis.html      # 커스텀 분석 통합 페이지
```

---

## 📌 11. 일정 요약

| Phase | Step | 내용 | 예상 기간 |
|-------|------|------|-----------|
| **Phase 1** | Step 1 | DB 테이블 생성 | 1일 |
| | Step 2 | 시스템 필터 Seed | 0.5일 |
| **Phase 2** | Step 3 | 공통 JS 모듈 | 2일 |
| **Phase 3** | Step 4 | HTML 마이그레이션 | 3일 |
| **Phase 4** | Step 5 | 커스텀분석 통합 | 1일 |
| | Step 6 | AI 자동 필터 | 0.5일 |
| **총계** | | | **8일** |
| **Phase 5** | Step 7 | 검증 시스템 (추후) | TBD |

---

## 📌 12. 다음 단계

이 계획서가 확정되면:

1. **Step 1-1**: `001_create_filter_definitions.sql` 파일 생성
2. **Step 1-2**: `002_create_user_filter_presets.sql` 파일 생성
3. **Step 1-3**: 이하 순차 진행

**진행하시겠습니까?**
