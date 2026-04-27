# 🎯 커스텀 연산 시뮬레이터 & 수동 필터 대시보드 종합 계획서

> **작성일**: 2026-04-25  
> **버전**: v1.0  
> **프로젝트 위치**: `c:\Users\psdet\Documents\lottoanalysis`  
> **연동 DB**: Supabase (기존 `lotto_draws` 테이블 + 신규 `manual_filters` 테이블)

---

## 1. 시스템 개요 (System Overview)

사용자가 **직접 수학적 연산 규칙을 정의**하고, 이를 국내/해외 다양한 로또 데이터베이스에 **실시간으로 투영**하여 당첨 성적을 시뮬레이션하는 개인화 분석 시스템입니다.

검증된 규칙은 **수동 필터(Manual Filter)** 로 등록되어 대시보드에서 지속적으로 관리·성적 추적됩니다.

### 핵심 가치
- 기존 분석 사이트에서는 불가능한 **사용자 정의 수식 검증** 환경 제공
- '회차별 합집합 리스트화' + '보정 로직' 결합 → **강력한 개인화 분석 도구**
- 실시간 연산은 **클라이언트 메모리(로컬)** 에서 처리 → Supabase 부하 최소화

---

## 2. 전체 아키텍처 (Architecture Overview)

```
┌─────────────────────────────────────────────────────────┐
│                    사용자 인터페이스 (UI)                    │
│  [DB 선택기] → [연산 수식 입력기] → [N회차 슬라이더]           │
│  [시뮬레이션 결과 테이블] → [필터 저장 버튼] → [대시보드]        │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│               데이터 선택 모듈 (Selection Module)           │
│  동행로또 DB ─┐                                            │
│  MEGA 777  ──┼─→ [데이터 표준화 레이어] → 규격화된 데이터 객체  │
│  Powerball ──┘                                            │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│               실시간 연산 엔진 (Calculation Engine)         │
│  [순차 연산 처리기] + [수치 보정 로직]                        │
│  입력: 회차 데이터 + 메타 데이터 → 출력: 예측 번호 세트         │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│          N회차 누적 합집합 생성기 (Sliding Window)            │
│  슬라이딩 윈도우 방식으로 [회차|대상번호|실제당첨|Hit수] 행렬 생성  │
└────────────────────────┬────────────────────────────────┘
                         │
                ┌────────┴────────┐
                ▼                 ▼
  ┌─────────────────────┐  ┌──────────────────────┐
  │  결과 시각화 (UI)    │  │  Supabase DB 저장     │
  │  차트 / 행렬 테이블  │  │  (확정 필터만 저장)    │
  └─────────────────────┘  └──────────────────────┘
```

---

## 3. 데이터 소스 및 선택 엔진 (Selection Module)

### 3.1 대상 DB 목록

| DB 식별자 | 로또 이름 | 번호 범위 | 보너스볼 | 데이터 위치 |
|---|---|---|---|---|
| `korea` | 동행복권 (기본) | 1 ~ 45 | 있음 (1개) | Supabase `lotto_draws` |
| `mega777` | MEGA 777 | 1 ~ 77 | 없음 | `globallotto/` CSV 또는 Supabase |
| `powerball` | Powerball | 1 ~ 69 (+ PB 1~26) | 있음 (PB) | `globallotto/` CSV 또는 Supabase |
| `belgium` | Belgium Lotto | 1 ~ 45 | 있음 | `globallotto/Belgium_Lotto.csv` |

> **확장 원칙**: DB 선택기는 `lottoDB` 설정 객체 배열로 관리하여, 새 로또 추가 시 배열에 항목만 추가하면 자동 지원되도록 설계합니다.

### 3.2 데이터 표준화 포맷 (Normalized Draw Object)

```javascript
// 어떤 로또 DB를 선택해도 이 포맷으로 변환되어 엔진에 전달됩니다.
{
  drawNo: 1177,            // 회차 번호 (정수)
  drawDate: "2026-04-19", // 추첨일
  numbers: [3, 12, 24, 33, 40, 45], // 본 번호 배열 (오름차순 정렬)
  bonus: 7,               // 보너스볼 (없으면 null)
  maxBall: 45,            // 해당 로또의 최대 번호 (보정 로직에 사용)
  dbId: "korea"           // DB 식별자
}
```

---

## 4. 실시간 연산 엔진 (Calculation Engine)

### 4.1 연산 방식: 순차 연산 (Sequential Processing)

> **핵심 원칙**: 수학적 우선순위(곱셈·나눗셈 우선)를 **무시**하고, 사용자가 입력한 **좌→우 순서대로** 연산을 진행합니다.  
> (직관성과 일관성을 최우선으로)

**연산 대상 항목**

| 항목 유형 | 표기 예시 | 설명 |
|---|---|---|
| 회차 당첨번호 | `N-1[1]` ~ `N-1[6]` | N-1회차의 1번째~6번째 번호 |
| 회차 끝수(일의 자리) | `N-1[1]%10` | N-1회차 1번째 번호의 끝수 |
| 회차 번호 자릿수 합 | `drawNo.digitSum` | 회차 번호의 각 자릿수 합 (예: 1177 → 1+1+7+7=16) |
| 메타 계산값 | `drawNo.digitSum % 45` | 회차 번호 기반 파생값 |

**수식 입력 예시**

```
N-1[1] + N-2[3] - drawNo.digitSum
→ (N-1회차의 1번째 번호) + (N-2회차의 3번째 번호) - (현재 회차 번호 자릿수 합)
→ 순서대로: 3 + 24 = 27, 27 - 16 = 11  ← 최종값 11
```

### 4.2 수치 보정 로직 (Normalization Rules)

연산 결과가 유효한 로또 번호 범위(1 ~ maxBall)를 벗어날 경우 **강제 적용**합니다.

```
┌─────────────────────────────────────────────────────────┐
│  연산 결과값(result)에 대한 보정 우선순위                      │
│                                                         │
│  1. 나눗셈 연산인 경우 → 나머지(remainder)를 최종값으로 채택    │
│     예: 57 ÷ 45 → 나머지 12 → 최종값 12                    │
│                                                         │
│  2. result === 0 → 해당 값 즉시 제거 (연산 대상에서 탈락)      │
│                                                         │
│  3. result < 0 (음수) → -1부터 역산 적용                    │
│     예: -1 → maxBall, -2 → maxBall-1, -3 → maxBall-2   │
│     (maxBall=45 기준: -1→45, -2→44, -3→43)              │
│                                                         │
│  4. result > maxBall (초과) → 1부터 순환 적용              │
│     예: 46 → 1, 47 → 2, 90 → 45, 91 → 1                │
└─────────────────────────────────────────────────────────┘
```

**보정 로직 JavaScript 의사코드**

```javascript
function normalize(result, maxBall) {
  // [수정] 0 처리 → 제거 신호 반환
  if (result === 0) return null;

  // [수정] 음수 처리 → 역산
  if (result < 0) {
    // -1 → maxBall, -2 → maxBall-1 ...
    result = maxBall + (result % maxBall);
    if (result === 0) return null; // 역산 후에도 0이면 제거
  }

  // [수정] 초과 처리 → 순환
  if (result > maxBall) {
    result = ((result - 1) % maxBall) + 1;
  }

  return result;
}
```

---

## 5. N회차 누적 합집합 리스트화 (Sliding Window)

### 5.1 개념 설명

단순 1회 계산이 아니라, **시계열 흐름**을 파악하기 위해 회차별로 반복 연산합니다.

> **예시**: 사용자가 N=3을 선택한 경우  
> - T회차 시뮬레이션 대상 = `{T-1, T-2, T-3}` 회차 당첨번호의 **합집합(중복 제거)**  
> - 이 작업을 DB의 모든 회차에 대해 반복 → **회차별 성적 행렬** 생성

### 5.2 결과 행렬 구조 (Output Matrix)

| 회차(T) | 대상 번호 리스트 | 실제 당첨번호 | Hit 수 | Hit율 |
|---|---|---|---|---|
| 1175 | [3,7,12,15,19,24,33,40,45...] | [5,11,19,24,30,38] | 2 | 33% |
| 1176 | [7,12,19,24,33,40,43,45...] | [3,12,24,33,40,45] | 5 | 83% |
| 1177 | [5,11,19,24,30,38,40,43...] | [2,7,21,28,37,42] | 0 | 0% |

### 5.3 처리 흐름 (Pseudocode)

```javascript
function runSimulation(draws, formula, N) {
  const results = [];

  for (let i = N; i < draws.length; i++) {
    // 슬라이딩 윈도우: T-1 ~ T-N 회차 당첨번호 합집합
    const windowNumbers = new Set();
    for (let k = 1; k <= N; k++) {
      draws[i - k].numbers.forEach(n => windowNumbers.add(n));
    }

    // 수식 적용 → 보정 → 결과 번호 세트 생성
    const predicted = applyFormula(formula, draws[i - 1], draws[i]);
    const predictedNormalized = predicted.map(normalize).filter(Boolean);

    // 실제 당첨번호와 교집합 계산
    const actual = new Set(draws[i].numbers);
    const hits = predictedNormalized.filter(n => actual.has(n));

    results.push({
      drawNo: draws[i].drawNo,
      targetList: [...windowNumbers],
      actualNumbers: draws[i].numbers,
      hitCount: hits.length,
      hitRate: (hits.length / draws[i].numbers.length * 100).toFixed(1)
    });
  }

  return results;
}
```

---

## 6. Supabase 데이터 스키마 (DB Schema)

### 6.1 신규 테이블: `manual_filters`

```sql
CREATE TABLE manual_filters (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at    TIMESTAMPTZ DEFAULT now(),
  filter_name   TEXT NOT NULL,           -- 사용자 지정 필터명 (예: "끝수-회차합산 전략")
  db_id         TEXT NOT NULL,           -- 적용 DB ('korea', 'mega777', 'powerball' 등)
  formula       JSONB NOT NULL,          -- 연산 수식 정의 (구조화된 JSON)
  window_n      INTEGER NOT NULL,        -- N회차 슬라이딩 윈도우 크기
  result_numbers INTEGER[],             -- 도출된 번호 세트 (최근 회차 기준)
  last_hit_count INTEGER,               -- 최근 회차 Hit 수
  last_evaluated_draw INTEGER,          -- 마지막 성적 평가 회차
  notes         TEXT                    -- 메모
);
```

### 6.2 `formula` JSONB 예시

```json
{
  "steps": [
    { "operand": "N-1[1]", "operator": "+", "value": "N-2[3]" },
    { "operand": "result",  "operator": "-", "value": "drawNo.digitSum" }
  ],
  "description": "N-1 1번째 + N-2 3번째 - 현재회차 자릿수합"
}
```

---

## 7. 수동 필터 대시보드 UI 구성

### 7.1 필터 카드 위젯 (Filter Card Widget)

각 저장된 필터는 카드 형태로 대시보드에 표시됩니다.

```
┌──────────────────────────────────────────────────────┐
│  🎯 끝수-회차합산 전략             [동행복권] [N=3]     │
│  ─────────────────────────────────────────────────── │
│  수식: N-1[1] + N-2[3] - drawNo.digitSum             │
│  예측번호: 7, 14, 22, 31, 38                          │
│  ─────────────────────────────────────────────────── │
│  최근 성적: 1177회 ● Hit 2개  (1176회 ★ Hit 5개)      │
│  누적 평균 Hit율: 34.2%   최고 Hit: 5개               │
│  ─────────────────────────────────────────────────── │
│  [📊 전체 성적 보기]  [✏️ 수정]  [🗑️ 삭제]            │
└──────────────────────────────────────────────────────┘
```

### 7.2 대시보드 로드 시 실시간 성적 업데이트

```
1. Supabase에서 manual_filters 목록 전체 로드
2. Supabase에서 최신 회차 데이터 로드
3. 각 필터의 formula를 최신 회차에 대입 → 예측 번호 재계산
4. 예측 번호 vs 실제 당첨번호 → Hit 수 계산
5. 카드 UI 업데이트 (last_hit_count, result_numbers 갱신)
6. 변경사항 Supabase에 upsert 저장 (선택)
```

### 7.3 회차 연산 시각화 (Chart & Table)

- **라인 차트**: 회차별 Hit율 추이 (Chart.js 활용)
- **행렬 테이블**: [회차 | 대상 번호 | 실제 당첨 | Hit 수 | Hit율] 표시
- **히트맵**: 번호별 적중 빈도 색상 표현

---

## 8. 개발 로드맵 (Development Roadmap)

### 🏁 1단계: 로또 DB 선택기 + 기본 연산 엔진

**파일**: `custom_simulator.html` (신규 생성)

- [ ] DB 선택 셀렉터 UI 구현 (동행/해외 선택)
- [ ] 데이터 표준화 레이어 구현 (`normalizeDrawData()`)
- [ ] 수식 입력 UI (텍스트 기반 또는 단계별 빌더)
- [ ] 순차 연산 처리기 구현 (`applyFormula()`)
- [ ] 수치 보정 로직 구현 (`normalize()`)
- [ ] 단일 회차 결과 출력 테스트

**예상 소요**: 1~2일

---

### 🏁 2단계: N회차 슬라이딩 윈도우 + 행렬 생성

**파일**: `custom_simulator.html` (기능 추가)

- [ ] N값 슬라이더 UI 구현
- [ ] 슬라이딩 윈도우 합집합 생성 로직 (`runSimulation()`)
- [ ] 회차별 결과 행렬 테이블 렌더링
- [ ] Hit 수 / Hit율 컬럼 계산 및 표시
- [ ] 결과 행렬 CSV 내보내기 기능

**예상 소요**: 1~2일

---

### 🏁 3단계: Supabase 저장 + 대시보드 UI

**파일**: `custom_simulator.html` + `filter_dashboard.html` (신규)

- [ ] Supabase `manual_filters` 테이블 생성 (마이그레이션)
- [ ] 필터 저장 버튼 및 저장 로직 구현
- [ ] `filter_dashboard.html` 신규 페이지 생성
- [ ] 필터 카드 위젯 렌더링 (`renderFilterCard()`)
- [ ] 대시보드 로드 시 실시간 성적 업데이트 로직
- [ ] 필터 수정 / 삭제 기능
- [ ] `dashboard.html` 메인 대시보드 네비게이션 연동

**예상 소요**: 2~3일

---

### 🏁 4단계: 성능 최적화 + 예외 처리

**파일**: 전체

- [ ] 대용량 회차 데이터 처리 시 렌더링 최적화 (가상 스크롤 또는 페이지네이션)
- [ ] 데이터 누락 회차 예외 처리 (null 가드)
- [ ] 연산 중 오류 발생 시 사용자 친화적 에러 메시지
- [ ] 해외 로또 CSV 파일 → Supabase 마이그레이션 스크립트 정비
- [ ] 모바일 반응형 UI 적용

**예상 소요**: 1~2일

---

## 9. 기술 스택 및 제약사항

| 항목 | 내용 |
|---|---|
| **프론트엔드** | Vanilla HTML + CDN Vue 3 + Bootstrap 5 (기존 프로젝트 동일) |
| **차트 라이브러리** | Chart.js (기존 사용 중) |
| **백엔드 DB** | Supabase (PostgreSQL) |
| **실시간 연산 위치** | 클라이언트 메모리 (서버 부하 최소화) |
| **영구 저장 대상** | 확정된 필터 정의만 Supabase에 저장 |
| **빌드 도구** | 없음 (CDN 기반, `npm` 불필요) |
| **해외 로또 데이터** | `globallotto/` 디렉터리의 CSV 파일 또는 Supabase |

---

## 10. 오픈 이슈 및 추후 결정 사항

> **결정 필요**: 아래 항목은 1단계 개발 시작 전 사용자 확인이 필요합니다.

| # | 이슈 | 옵션 A | 옵션 B |
|---|---|---|---|
| 1 | **수식 입력 방식** | 텍스트 자유 입력 (파서 필요) | 드롭다운 빌더 (단계별 선택) |
| 2 | **해외 로또 데이터 소스** | CSV 파일 직접 파싱 (클라이언트) | Supabase 테이블로 통합 |
| 3 | **필터 대시보드 위치** | 별도 `filter_dashboard.html` 신규 생성 | 기존 `dashboard.html`에 탭으로 통합 |
| 4 | **결과 행렬 저장** | 저장 안 함 (매번 재계산) | Supabase에 캐싱 저장 |

---

## 11. 성공 기준 (Definition of Done)

각 단계의 완료 기준입니다.

- **1단계 완료**: 사용자가 수식을 입력하면, 특정 회차에 대해 보정된 예측 번호가 UI에 출력된다.
- **2단계 완료**: N=3 선택 시 전체 회차에 대한 Hit율 행렬 테이블이 3초 이내에 렌더링된다.
- **3단계 완료**: 필터를 저장하면 Supabase에 등록되고, 대시보드 재방문 시 최신 성적이 자동 업데이트된다.
- **4단계 완료**: 1,000회차 이상 데이터에서도 시뮬레이션이 끊김 없이 작동하며, 데이터 누락 시 오류 없이 건너뛴다.

---

*© 2026 Lotto Analysis Project*
