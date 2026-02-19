# 필터 조합 페이지 (combination.html) 구현 계획

> 작성일: 2026-02-18
> 상태: 구현 완료 예정

---

## 개요

분석 페이지에서 설정한 조합 필터들을 한 곳에서 확인하고, 조합 버튼을 누르면 조건에 맞는 로또 번호 조합을 생성하는 페이지.

### 필터 종류 2가지

1. **기초 분석 필터** (`filter_settings` 테이블)
   - `filterService.getActiveFilters()`로 로드
   - filter_key → filter_name은 `filter_definitions` 테이블 참조

2. **커스텀분석 필터** (`ai_custom_analyses` 테이블의 `filter_config` 컬럼)
   - `filterService.getCustomAnalysisFilters()`로 매번 새로 로드
   - `filter_config.enabled === true`인 것만 포함
   - 삭제된 분석은 Hard Delete이므로 자동 제외

---

## 화면 구성

### 1. 상단 - 총 조합수 디지털 디스플레이
- 검정 배경 LCD/세그먼트 디스플레이 스타일
- 초록색 글로우 숫자 (디지털 느낌)
- 조합 생성 중 실시간 카운팅 애니메이션

### 2. 중간 - 활성 필터 카드 (2섹션)

**섹션 A: 기초 분석 필터**
- 카드: 필터 이름(클릭→분석 페이지), 설정값, 임시 토글
- 스킵 필터(이월수/핫콜드/미출현)는 "조합 생성 미적용" 안내

**섹션 B: 커스텀분석 필터**
- 카드: 분석 제목(클릭→`custom_analysis.html?id=...`), 번호 미리보기(최대 5개), 포함범위(min~max개), 임시 토글
- 새로고침 버튼으로 최신 상태 반영

### 3. 하단 - 조합 생성 & 결과
- "조합 생성" 버튼 + 중단 버튼
- 진행 상태바 (C(45,6)=8,145,060개 탐색)
- 결과 카드 (번호볼 + 합/홀짝/AC값)
- 최대 100개 표시, 더보기

---

## 필터 → 분석 페이지 URL 매핑

```javascript
const FILTER_PAGE_MAP = {
    'ac_value':                   'ac_value.html',
    'total_sum_patterns':         'total_sum.html',
    'tail_sum_patterns':          'tail_sum.html',
    'carryover_count':            'carryover.html',
    'odd_even_patterns':          'odd_even.html',
    'low_high_ratio':             'low_high.html',
    'prime_number_patterns':      'prime_number.html',
    'composite_count':            'composite_number.html',
    'square_number_patterns':     'square_number.html',
    'twin_number_patterns':       'twin_number.html',
    'consecutive_count':          'consecutive_number.html',
    'hot_cold_v2':                'hot_cold.html',
    'missing_period':             'missing.html',
    'multiple_patterns':          'multiple.html',
    'neighbor_number_patterns':   'neighbor_number.html',
    'number_range_patterns':      'number_range.html',
    'tail_digit_patterns':        'tail_digit.html',
    'triangular_number_patterns': 'triangular_number.html',
    'magic_square_patterns':      'magic_square.html',
    'lotto_paper_patterns':       'lotto_paper.html',
};
```

---

## 조합 검증 로직

### 기초 분석 필터 (filter_key별 settings 구조 및 검증)

| filter_key | settings 구조 | 검증 방법 |
|---|---|---|
| `ac_value` | `{ min, max }` | AC값이 min~max |
| `total_sum_patterns` | `{ min, max, excluded: [] }` | sum이 min~max AND excluded에 없음 |
| `tail_sum_patterns` | `{ min, max, excluded: [] }` | 일의자리합이 min~max AND excluded에 없음 |
| `odd_even_patterns` | `{ selectedRatios: ["3:3",...] }` | 홀:짝 비율이 selectedRatios 포함 |
| `low_high_ratio` | `{ selectedRatios: ["3:3",...] }` | 저(1~22):고(23~45) 비율 포함 |
| `prime_number_patterns` | `{ activeCounts: [], excludedPrimes: [] }` | 소수 개수 + 특정 소수 제외 |
| `composite_count` | `{ activeFilters: [], excludedComposites: [] }` | 합성수 개수 |
| `square_number_patterns` | `{ activeCounts: [], excludedNumbers: [] }` | 제곱수(1,4,9,16,25,36) 개수 |
| `twin_number_patterns` | `{ activeFilters: [], excludedTwins: [] }` | 쌍수(11,22,33,44) 개수 |
| `consecutive_count` | `{ selectedCounts: [], runFilters: {...} }` | 연속 번호쌍 개수 |
| `multiple_patterns` | `{ filters: { [type]: { min, max } } }` | 배수별 개수 |
| `neighbor_number_patterns` | `{ min, max }` | 이웃수 개수 |
| `number_range_patterns` | `{ ranges: { [type]: { min, max } } }` | 구간별 개수 |
| `tail_digit_patterns` | `{ filters: { [digit]: { min, max } } }` | 끝자리별 개수 |
| `triangular_number_patterns` | `{ activeCounts: [], excludedTriangular: [] }` | 삼각수 개수 |
| `magic_square_patterns` | `{ filters: { [type]: { min, max } } }` | 마방진 구역별 개수 |
| `lotto_paper_patterns` | `{ groups: { [type]: { min, max } } }` | 로또 용지 라인별 개수 |

> **조합 생성 미적용 필터** (실시간 데이터 필요): `carryover_count`, `hot_cold_v2`, `missing_period`

### 커스텀분석 필터
```javascript
// FilterService.validateCombinationWithCustomFilters(combination, customFilters) 사용
// target_numbers 중 combination에 포함된 수가 min~max개인지 확인
```

### 조합 생성 (청크 방식)
- 10,000개씩 처리 후 UI 업데이트 (UI 블로킹 방지)
- 중단 버튼 지원

---

## 수정 파일 목록

| 파일 | 수정 내용 |
|---|---|
| `combination.html` | 신규 생성 |
| `components/header.html` | 필터 탭 href → `combination.html` |
| `js/layout.js` | PAGE_CONFIG에 combination.html 추가 (gnbIndex: 5) |
| `ac_value.html` 외 20개 분석 페이지 | `goToFilterPage()` → `combination.html` 이동 |
