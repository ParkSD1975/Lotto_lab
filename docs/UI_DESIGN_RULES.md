# Lotto Lab UI 디자인 규칙 (절대 원칙)

> 이 파일은 설계 원칙이자 검수 기준입니다. 모든 UI 작업은 구현 전·후에 이 문서를 기준으로 점검합니다.

---

## ❌ 절대 금지 사항 (극혐 목록)

### 1. 좌우 스크롤 (Horizontal Scroll) — **극혐·절대 금지**
- 페이지 단위에서 `overflow-x: auto` 또는 `overflow-x: scroll` 사용 **금지**
- 넓은 테이블은 반드시 **컬럼 수를 줄이거나 화면 너비 안에 들어오도록 재설계**
- 테이블 컨테이너에 `overflow-x-auto` 걸어 넘기기도 **최대한 회피**
  - 불가피한 경우 해당 테이블 하나에만 국소적으로 적용, 섹션 전체·페이지 전체 사용 금지

### 2. 한 줄로 표시 가능한 텍스트를 두 줄로 표시 — **극혐·절대 금지**
- 설명 문구(description, subtitle, label)가 한 줄에 맞지 않아 줄바꿈되는 경우 **금지**
- 긴 설명은 반드시 **짧은 문구로 축약** (예시 아래 참조)
- 테이블 셀 내용이 열 너비 부족으로 2줄이 되는 경우도 **금지** → 열 너비를 늘리거나 텍스트를 줄일 것
- `whitespace-nowrap` 또는 `truncate` 를 적극 활용할 것

#### 축약 예시
| 원문 (금지) | 축약 (올바름) |
|---|---|
| "10 base 메인 모델 + 4 Pillar 합의 추천/제외의 회차당 평균 적중을 베이스라인(랜덤 0.67) 대비로 표시합니다." | "10-base 모델 · 추천/제외 평균 적중 vs 베이스라인(0.67)" |
| "최근 50회차의 추천 적중(실선) 및 제외 적중(점선) 분포. 랜덤 베이스라인 0.67 기준선 표시." | "50회차 추천/제외 적중 시계열 · 베이스라인 0.67" |
| "딥러닝 회귀분석 결과 — N개 회귀 패턴 · ai_deep_learning 페이지와 동일 데이터" | "회귀분석 결과 · N개 패턴" |

### 3. 테이블 컬럼 너비 배분 불균형 — **못참겠어·절대 금지**
- 테이블에는 반드시 명시적 컬럼 너비(`<col style="width:...">` 또는 `style="width:..."`)를 지정할 것
- 브라우저 자동 배분에 의존하는 `<table class="w-full">` 단독 사용 **금지**
- 숫자/상태 컬럼은 최소 너비 명시, 텍스트가 긴 컬럼은 최대 너비 + `truncate`
- 번호 볼(ball) 표시 컬럼은 최대 너비를 제한하여 줄바꿈 방지

#### 컬럼 너비 원칙
- **회차/ID 컬럼**: `width: 60px` 고정
- **번호볼 컬럼**: `width: 200px` 상한 (초과분은 행 분리 대신 컬럼 추가)
- **숫자/퍼센트 컬럼**: `width: 60~80px` 고정
- **상태/뱃지 컬럼**: `width: 80~100px` 고정
- **텍스트 설명 컬럼**: 나머지 너비 자동 + `truncate`

### 4. 디자인 통일성 위반 — **아주 싫음·절대 금지**
- 같은 페이지 내 서브탭 간 카드 스타일, 헤더 스타일, 폰트 크기가 일관되지 않으면 **금지**
- 색상 토큰(CSS 변수)은 하드코딩 없이 반드시 미리 정의된 시스템 변수 사용
- 아이콘 크기, 패딩, border-radius 등 수치는 Tailwind 표준 클래스 기준 통일

---

## ✅ 반드시 따라야 하는 원칙

### 레이아웃
- 최대 너비: `max-w-6xl mx-auto` (전 페이지 동일)
- 섹션 카드: `rounded-2xl border border-gray-200 shadow-sm bg-white`
- 섹션 간격: `mb-6`
- 내부 여백: `px-4 py-3` (헤더), `px-4 py-2` (바디 행)

### 타이포그래피
- 섹션 제목: `text-[15px] font-bold text-slate-800`
- 서브 레이블: `text-[12px] font-bold text-slate-600`
- 설명 텍스트: `text-[12px] text-slate-500`
- 메타/보조 텍스트: `text-[11px] text-slate-400`
- 모노스페이스 숫자: `font-mono text-[13px]`

### 빈 데이터 처리
- `null` / `undefined` / `0` / `—` 그대로 표시 **금지**
- 데이터가 없는 항목: "데이터 없음" 또는 섹션 자체를 숨길 것
- 로딩 중: `LOADING_HTML` 스피너 사용
- 오류: `emptyState(icon, message)` 헬퍼 사용

### 테이블 구조
```html
<div class="rounded-2xl border border-gray-200 shadow-sm bg-white mb-6">
  <table class="w-full text-xs table-fixed">
    <colgroup>
      <col style="width:60px">
      <col style="width:200px">
      <col style="width:70px">
      <!-- ... -->
    </colgroup>
    <thead>...</thead>
    <tbody>...</tbody>
  </table>
</div>
```

### ECharts 차트
- 컨테이너: `height: 280px` (기본), `height: 400px` (큰 차트)
- 히트맵: `height: auto` (행 수 × 36px, 최소 200px)
- 반응형: `chart.resize()` → `window.addEventListener('resize', ...)`
- 차트 초기화 guard: `dataset.rendered = '1'`

---

## 모델 색상 토큰

```css
--c-ens:     #4F46E5;   /* 앙상블 */
--c-xgb:     #3B82F6;   /* XGBoost */
--c-cat:     #14B8A6;   /* CatBoost */
--c-tab:     #A855F7;   /* TabNet */
--c-cnn:     #EC4899;   /* CNN */
--c-gnn:     #EF4444;   /* GNN */
--c-mkv:     #10B981;   /* Markov */
--c-ae:      #8B5CF6;   /* AutoEncoder */
--c-tft:     #F97316;   /* TFT */
--c-mhn:     #84CC16;   /* MHN */
--c-bay:     #F59E0B;   /* Bayesian NN */
```

---

*최초 작성: 2026-05-06 · 작성 이유: 검증 페이지 DL탭 재설계 중 사용자 디자인 원칙 문서화*
