# 로또 AI 플랫폼 - 작업 로그

## 🚀 최근 작업 완료 (2026-04-13)

### 1. 총합 분석 (`total_sum.html`) UI/UX 표준화
- **문제**: 레이아웃 시프트(스크롤 튐), JS 에러, 비표준 디자인
- **수정**: 
    - 배지 영역 위치 조정으로 레이아웃 고정
    - 프리미엄 로또 볼 디자인 및 다크 테마 헤더 적용
    - `total_sum_filter_isManual` 플래그 도입으로 동기화 로직 정밀화
- **효과**: 사용자 경험(UX) 개선 및 디자인 일관성 확보

### 2. 끝수합 분석 (`tail_sum.html`) 신규 기능 및 표준화
- **신규 기능**: `끝수합차` (전회차 대비 변동폭) 컬럼 추가
- **수정**: 
    - 총합 분석과 동일한 프리미엄 디자인 시스템 적용
    - 레이아웃 시프트 해결 및 필터 badge 애니메이션 최적화
- **효과**: 데이터 분석 가시성 증대

### 3. AI 인사이트 및 데이터 동기화 최적화 (`js/customAnalysis.js`, `js/deep_insight_panel.js`)
- **문제**: 1212회차 이후 AI 예측 데이터 누락 및 차기 회차 매핑 오류
- **수정**:
    - `ensureAIHistoryLoaded` 로직 개선 (1212회차~최신+1회차 전수 로드)
    - `extractTargetsFromAIData` 통합 헬퍼 도입으로 데이터 정합성 확보
    - `deep_insight_panel.js` v2.0 표준화로 모든 분석 페이지 공통 AI 리포트 제공
- **효과**: AI 분석 신뢰도 및 시스템 안정성 향상

---

## ✅ 이전 완료 목록 (2026-03-20)

### 대상 파일
- `js/filter_dashboard.js`
- `missing.html`
- `js/common_v2.js`

---

## ✅ 완료된 수정 목록

### 1. missing_period 키 통일 (`js/common_v2.js`)
- **문제**: `Utils.saveFilter`가 `missing_period → long_term_miss`로 키 변환 → 대시보드와 분석페이지가 서로 다른 Supabase 행 읽기/쓰기
- **수정**: `saveFilter` / `loadFilter` 양쪽 keyMap에서 `missing_period → missing_period`로 통일
- **효과**: 대시보드 ↔ missing.html 필터 동기화 정상화

### 2. `Utils.loadFilter` localStorage fallback 버그 (`js/common_v2.js`)
- **문제**: fallback 시 `pageKey`로 읽는데 데이터는 `standardKey`로 저장되어 항상 null 반환
- **수정**: standardKey 변환을 `if(filterService)` 블록 밖으로 이동, fallback도 standardKey 사용

### 3. `updateMissingPeriodFilter` 저장 방식 (`js/filter_dashboard.js`)
- **문제**: `Utils.saveFilter`만 호출 → `target_round = null` 행만 저장, 특정 회차 행 미반영
- **수정**: `this._saveDashboardFilter()` 사용으로 IS NULL + round-specific 행 모두 저장

### 4. missing_custom_filter 자동 초기화 버그 (`js/filter_dashboard.js`)
- **문제**: 회차 비교 `currentRound = latestDraw`인데 저장값은 `targetRound = latestDraw+1` → 항상 불일치 → 필터 그룹 자동 삭제
- **수정**: 자동 삭제 로직 제거. 회차 불일치 시 `targetRound`만 갱신, **그룹 데이터는 절대 삭제하지 않음**

### 5. missing.html `loadSavedFilters` 새 회차 초기화 제거 (`missing.html`)
- **문제**: 새 회차 감지 시 `customFilters = []` + DB 저장 → 사용자 그룹 삭제
- **수정**: `targetRound`만 갱신하고 필터 그룹 유지

### 6. 대시보드 localStorage 병합 복원 (`js/filter_dashboard.js`)
- **문제**: DB에 `filters: []`이어도 localStorage에 실제 데이터가 있으면 무시됨
- **수정**: Merge #7 추가 — DB 빈 배열 + localStorage 동일 회차 데이터 존재 시 복원

### 7. 카드 제목 동적 표시 (`js/filter_dashboard.js`)
- **문제**: `displayName = '미출현 커스텀'` 하드코딩
- **수정**: 그룹 1개 → 그룹 이름 (예: `미출현5-15`), 2개+ → `미출현 커스텀 (N개)`, 0개 → `미출현 커스텀`

### 8. MIN/MAX 입력창 UI 개선 (`js/filter_dashboard.js`)
- **문제**: `w-9 h-6` (36×24px) 너무 좁아 스핀버튼 잘림, `onchange`는 포커스 아웃 시에만 발동
- **수정**: `style="width:64px;height:32px;"` + `oninput`으로 변경 (화살표 즉시 반응)

### 9. `updateMissingCustomMinMax` 중복 제거 (`js/filter_dashboard.js`)
- **문제**: 동일 함수 2개 정의 (line 1835, line 2612) → 마지막 정의(2612)가 덮어써 디바운스 없이 매 입력마다 DB 호출
- **수정**: line 2612 중복 제거, line 1835 (디바운스 400ms + `_saveDashboardFilter`) 버전만 유지

### 10. 저장 버튼 async 처리 (`missing.html`)
- **문제**: `onclick="saveFilters(); alert(...)"` — 저장 완료 전 alert 발동, 에러 무시
- **수정**: `saveFilters().then(() => alert(...)).catch(e => alert('저장 실패: ' + e.message))`

### 11. `saveFilters` filterService 재초기화 (`missing.html`)
- **문제**: filterService 미초기화 시 Supabase 저장 스킵 → localStorage만 저장
- **수정**: 저장 전 미초기화 상태면 `filterService.initialize()` 재시도

### 12. 대시보드 missing_custom_filter 빈 카드 표시 (`js/filter_dashboard.js`)
- **문제**: `hasGroups === false`이면 카드 자체를 렌더링하지 않음 → 사용자가 편집 링크를 볼 수 없음
- **수정**: 빈 상태 안내 UI + "미출현 페이지에서 그룹 추가 →" 링크 표시

---

## 📋 다음 작업 (TODO)

### 🔴 높은 우선순위

#### A. 전체 필터 페이지 동기화 점검
현재 missing.html만 수정됨. 아래 페이지들도 동일 패턴으로 대시보드 ↔ 분석페이지 동기화 검증 필요:
- `lotto_paper.html` — `lotto_paper_pattern` 필터
- `magic_square.html` — `magic_square_pattern` 필터
- `hot_cold.html` (5/10/15/20) — hot_cold 필터
- `consecutive_number.html` — consecutive_count 필터
- `multiple.html` — multiple_3_count 필터

**확인 포인트**:
- 대시보드에서 값 변경 → 분석페이지 반영 여부
- recent10 버튼 상태 동기화
- 필터 토글(on/off) 동기화

#### B. missing.html 기타 동기화 이슈
- `loadFilterSettings()` 호출 후 recent10 버튼 상태 UI 갱신 확인
- 대시보드 토글 OFF → missing.html에서 토글 OFF 반영 확인

### 🟡 중간 우선순위

#### C. 다른 분석 페이지 `checkAndResetOnNewDraw` 로직 점검
- missing.html처럼 새 회차 감지 시 강제 recent10 적용하는 페이지들 확인
- 사용자 수동 설정값을 덮어쓰는 케이스 방지

#### D. StorageEvent 기반 실시간 동기화 검증
- 대시보드에서 필터 변경 → 같은 탭의 다른 페이지 즉시 반영 (cross-tab)
- `window.addEventListener('storage', ...)` 리스너가 모든 분석 페이지에 구현되어 있는지 확인

### 🟢 낮은 우선순위

#### E. filter_dashboard.js 레거시 코드 정리
- 사용되지 않는 `long_term_miss` 관련 분기 코드 제거
- `standardKeyMapping` 내 구 키 호환 코드 정리

#### F. 대시보드 UX 개선
- missing_custom_filter 카드에서 그룹 enabled 토글 추가 (현재 missing.html에서만 가능)
- 그룹 이름이 길 때 말줄임표 처리 (현재 `truncate` 적용됨, 툴팁 추가 고려)

---

## 🔧 기술 메모

### Supabase filter_settings 구조
| filter_key | target_round | 용도 |
|---|---|---|
| `missing_period` | null | 기본값 (StorageEvent 브로드캐스트용) |
| `missing_period` | 1216 | 특정 회차 설정 |
| `missing_custom_filter` | null | 커스텀 그룹 (단일 행, 회차 무관 유지) |
| `missing_custom_filter` | 1216 | `_saveDashboardFilter`가 추가 저장하는 행 |

### 핵심 저장 함수 역할
- `Utils.saveFilter(key, settings, enabled)` — `target_round = null` 행 저장 + StorageEvent 발행
- `filterService.saveSetting(key, settings, enabled, round)` — 특정 회차 행 저장
- `_saveDashboardFilter(key, settings, enabled)` — 위 두 함수 모두 호출 (대시보드 변경 시 사용)

### missing_custom_filter targetRound 규칙
- `missing.html` 저장: `targetRound = allData[0].round + 1` (다음 회차 번호)
- 그룹은 회차 변경과 무관하게 **영구 유지**, 회차 불일치 시 targetRound만 갱신
