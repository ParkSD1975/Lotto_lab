# Lotto Lab — Project Guide

한국 로또 분석 웹 애플리케이션. 데이터 기반 패턴 분석, 11개 base 모델 앙상블 딥러닝, 4 Pillar Scoring, Hard Filter 3계층 추천/제외 시스템.

## Tech Stack

- **Frontend**: 정적 HTML + Tailwind CSS (CDN) + Pretendard 폰트
- **Charts**: Chart.js (기존) · ECharts 5 (Stage 5 시각화 신설)
- **Data**: Supabase (PostgreSQL) — `lotto_draws`, `ai_custom_analyses`, `manual_filters`, `weekly_*`, `analysis_history` 등
- **Backend**: Python langchain-backend (HF Spaces 배포, 16GB RAM)
- **JS**: ES2020+, IIFE 또는 모듈 네임스페이스 패턴

## Design Context

### Users
한국 로또 분석 도구의 진지한 사용자 — 매주 회차 분석, 패턴 탐색, 추천/제외 번호 결정에 데이터를 활용한다. 분석 도구 사용에 익숙하고, 수치·통계·도표를 읽을 수 있는 분석가 성향. 우연·점괘가 아니라 데이터 기반 판단을 신뢰한다.

### Brand Personality
**프리미엄 · 심플 · 모던** — 3 단어.

- Voice: 절제된 자신감, 데이터로 말하기. 과장된 수식어 금지.
- Tone: 차분함, 정확함, 투명함. 어필 X, 증거 O.
- 감정 목표: 신뢰, 명료함, 통제감. (놀이·재미 X, 공포·다급함 X)

### Aesthetic Direction
**라이트 모드 only · 미니멀 데이터 표현 · Apple/Stripe 계열의 절제된 프리미엄.**

- 배경: 따뜻한 화이트 (`#FAFAFA`~`#FCFCFD`). 순백색(`#FFFFFF`) 회피.
- 텍스트: 깊은 그레이 (`#0F172A`~`#1E293B`). 순흑(`#000`) 회피.
- 액센트: 단일 강조색 (Lotto 블루 `#3B82F6` 계열) 한 톤만. 다중 액센트 X.
- 타이포그래피: Pretendard, 모듈러 스케일. 굵기·크기로만 위계. 컬러로 위계 X.
- 데이터 시각화: 단일 차트 안에서 1~2색만 강조.
- 공간: 넉넉한 여백, 그리드 의도적 깨기. 모든 카드를 같은 사이즈로 깔지 X.

### Anti-References (절대 금지)
- ❌ **AI 슬롭**: cyan-on-dark, purple→blue gradient, neon glow, glassmorphism
- ❌ **파스텔 톤**: 부드럽고 흐릿한 색상, 모든 요소가 연한 색감
- ❌ **박스형 일변도**: 동일 사이즈 카드 grid, 아이콘+제목+텍스트 반복 패턴
- ❌ **컬러풀 아이콘**: 둥근 모서리에 채워진 컬러 아이콘이 모든 헤딩 위에 박힌 형태
- ❌ **광고·도박·운세 느낌**: 화려한 그라디언트, 반짝이는 버튼, 도박장 UI, 운세 분위기·아이콘
- ❌ **과장 카피**: "99% 적중률", "AI가 떨어진다!" 같은 마케팅 과장
- ❌ **bounce/elastic easing**: 데이터 도구다운 톤 깨짐

### Design Principles
1. **데이터가 주인공** — 시각 장식은 데이터 보조용. 차트 1개에 색상 1~2개, 장식 그래픽 절제.
2. **위계는 타이포로** — 굵기·크기·여백으로 계층. 컬러나 박스로 시각 위계 만들지 않음.
3. **여백을 두려워 X** — 빽빽한 정보 밀도보다 차분한 호흡. 섹션 간 충분한 separation.
4. **수치는 정밀하게** — `font-feature-settings: "tnum"` (tabular-nums), 끝맞춤, 일관된 소수점.
5. **차별화는 정확함에서** — '와 멋지다' < '아 정확하구나'. 11 모델 합의도, 4 Pillar 분해, XAI evidence 같은 구조 자체가 차별화.

### Component Conventions

**카드/섹션**:
```html
<!-- 주요 시각화 (anchor) — 카드 1개로 강조 -->
<div class="bg-white rounded-xl border border-gray-200 p-8 mt-16">
    <h3 class="text-lg font-bold tracking-tight mb-2">제목</h3>
    <p class="text-xs text-gray-500 mb-6">서브타이틀</p>
    <!-- 차트/데이터 -->
</div>

<!-- 보조 분석 — 카드 X, 직접 배치 (박스 일변도 회피) -->
<section class="mt-16">
    <h3 class="text-lg font-bold tracking-tight mb-2">제목</h3>
    <p class="text-xs text-gray-500 mb-6">서브타이틀</p>
    <!-- 표 또는 차트 직접 -->
</section>
```

**숫자 표시**:
```css
.metric { font-feature-settings: "tnum"; letter-spacing: -0.01em; }
```

**입력 폼 (underline-only, 박스 X)**:
```css
.input-underline {
    background: transparent;
    border: 0;
    border-bottom: 1px solid #E5E7EB;
    padding: 6px 0;
}
.input-underline:focus { border-bottom-color: #3B82F6; }
```

**섹션 간격**: `margin-top: 64px` (mt-16) — 빽빽함 회피.

### 11 모델 색상 토큰 (데이터 라벨 한정)

```css
--c-xgb: #3B82F6;     --c-cat: #14B8A6;     --c-tabnet: #A855F7;
--c-cnn: #EC4899;     --c-gnn: #EF4444;
--c-markov: #10B981;  --c-ae: #8B5CF6;
--c-tft: #F97316;     --c-nbeats: #06B6D4;
--c-mhn: #84CC16;     --c-bayesian: #F59E0B;
```

위 토큰은 **데이터 시각화 라벨용만**. UI/아이콘/배경에 사용 X.

## Filter Key Synchronization Rule (CRITICAL)

필터 키는 **4계층 모두 동일 표기**여야 한다. 강제 룰:

| 계층 | 위치 | 표기 |
|---|---|---|
| ① 프론트 | `js/filter/FilterRuleEngine.js::FILTER_KEYS`, `js/filter_dashboard.js::AI_KEY_MAP`, 각 분석 페이지 saveSetting key | 표준 키 |
| ② 백엔드 | `langchain-backend/services/filter_stats.py` 각 메서드의 `key=` | 표준 키 |
| ③ DB 정의 | `filter_definitions.filter_key`, `weekly_filter_predictions.filter_key` | 표준 키 |
| ④ DB 컬럼 | `model_filter_predictions.<key>_min/_max` | 표준 키 prefix |

**표준 키 35종** (2026-05-14 기준): `ac_value, total_sum, tail_sum, tail_digit_patterns, carryover_count, prime_number_patterns, square_number_patterns, triangular_number_patterns, odd_even_pattern, twin_number_patterns, neighbor_number_patterns, high_low_pattern, lotto_paper_pattern, magic_square_pattern, number_range_patterns, composite_count, consecutive_count, hot_cold_5/10/15/20, missing_period, missing_custom_filter, multiple_3/4/5/7/8_count, multiple_3_4_count, multiple_3_5_count, multiple_4_5_count, no_multiple_count, fixed_numbers, excluded_numbers, regression_analysis`.

### 변경 시 절차 (필수)
1. 새 필터 추가 / 키 변경 / 삭제 → **4계층 동시 PR**
2. PR 본문에 4계층 비교 표 첨부
3. `node scripts/verify_filter_keys.js` 실행 결과 첨부 (불일치 0 확인)
4. `AI_KEY_MAP` 같은 강제 매핑 레이어 신규 추가 금지 (레거시는 점진 제거)

### 바스켓 정책 (DB-first)
- `Basket`(`js/basket.js`)은 **DB가 단일 출처**. localStorage는 캐시.
- DB 저장 실패 시 사용자 토스트로 노출 (silent fail 금지).
- 회차 업데이트 감지 시 `fixed` · `exclude` **모두** 리셋 (영구 제외수 사고 방지).

## Project Structure

- 분석 페이지 22개 — 각 지표마다 (`ac_value.html`, `total_sum.html`, `tail_sum.html` 등)
- 딥러닝/AI 분석 — `ai_deep_learning.html`, `ai_combination.html`
- 시뮬레이터 — `custom_simulator.html` (v5-multi 워크스페이스 + 결합 op)
- 필터 대시보드 — `filter.html` (4 탭: 기초/회귀/커스텀/수동)
- 검증 — `verification.html` (7 탭)

## See Also

- `.impeccable.md` — 더 상세한 디자인 가이드 (이 문서의 원본)
- `docs/MASTER_PLAN.md` — Lotto_lab 딥러닝 전면 개편 마스터 플랜 (17주 7 Stage)
- `docs/lotto-deeplearning-system.md` — 11 base 모델 토폴로지
