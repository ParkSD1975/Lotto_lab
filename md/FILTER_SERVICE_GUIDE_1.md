# 🔌 FilterService.js 적용 가이드

## 1. HTML에 스크립트 추가

```html
<head>
    <!-- 기존 스크립트들 -->
    <script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
    <script src="js/theme.js"></script>
    <script src="js/common_v2.js"></script>
    
    <!-- ✅ FilterService 추가 -->
    <script src="js/filter/FilterService.js"></script>
    
    <script src="js/layout.js"></script>
</head>
```

---

## 2. 기존 코드 수정

### 변경 전 (localStorage 사용)
```javascript
// 저장
function saveFilterSettings() {
    const data = {
        min: parseInt(minInput.value),
        max: parseInt(maxInput.value),
        enabled: toggle.checked
    };
    window.Utils.saveFilter('ac_filter', data);
}

// 로드
function loadFilterSettings() {
    const saved = window.Utils.loadFilter('ac_filter');
    if (saved) {
        minInput.value = saved.min;
        maxInput.value = saved.max;
        toggle.checked = saved.enabled;
    }
}
```

### 변경 후 (DB 사용)
```javascript
// 저장 (async로 변경)
async function saveFilterSettings() {
    const data = {
        min: parseInt(minInput.value),
        max: parseInt(maxInput.value),
        enabled: toggle.checked
    };
    
    // ✅ DB에 저장 (FilterService 사용)
    await window.Utils.saveFilter('ac_value', data);  // 키 변경: ac_filter → ac_value
}

// 로드 (async로 변경)
async function loadFilterSettings() {
    // ✅ DB에서 로드
    const saved = await window.Utils.loadFilter('ac_value');
    
    if (saved) {
        minInput.value = saved.min ?? 0;
        maxInput.value = saved.max ?? 10;
        toggle.checked = saved.enabled ?? false;
    }
}
```

---

## 3. 페이지 초기화 수정

### 변경 전
```javascript
document.addEventListener('DOMContentLoaded', async function() {
    await loadDrawsAndFeatures();
    loadFilterSettings();  // 동기 호출
    // ...
});
```

### 변경 후
```javascript
document.addEventListener('DOMContentLoaded', async function() {
    // ✅ FilterService 초기화 (필수!)
    await initFilterService();
    
    await loadDrawsAndFeatures();
    await loadFilterSettings();  // ✅ async 호출
    // ...
});
```

---

## 4. 필터 키 매핑 (전체 22개)

| # | HTML 페이지 | localStorage 키 | DB filter_key |
|---|------------|-----------------|---------------|
| 1 | total_sum.html | `total_sum_filter` | `total_sum` |
| 2 | tail_sum.html | `tail_sum_filter` | `last_digit_sum` |
| 3 | tail_digit.html | `tail_digit_filter` | `end_digit_X_count` (10개) |
| 4 | ac_value.html | `ac_filter` | `ac_value` |
| 5 | odd_even.html | `odd_even_filter` | `odd_even_pattern` |
| 6 | low_high.html | `low_high_filter` | `high_low_pattern` |
| 7 | prime_number.html | `prime_filter` | `prime_count` |
| 8 | composite_number.html | `composite_filter` | `composite_count` |
| 9 | square_number.html | `square_filter` | `square_count` |
| 10 | twin_number.html | `twin_filter` | `twin_count` |
| 11 | multiple.html | `multiple_filter` | `multiple_X_count` (7개) |
| 12 | consecutive_number.html | `consecutive_filter` | `consecutive_count` |
| 13 | carryover.html | `carryover_filter` | `carryover_count` |
| 14 | neighbor_number.html | `neighbor_filter` | `neighbor_count` |
| 15 | number_range.html | `number_range_filter` | `zone_3_pattern` |
| 16 | stats_by_number.html | `stats_by_number_filter` | (통계용) |
| 17 | hot_cold.html | `hot_cold_filter` | `hot_cold_X` (4개) |
| 18 | missing.html | `missing_filter` | `long_term_miss` |
| 19 | regression.html | (storageKey 변수) | `regression_analysis` |
| 20 | lotto_paper.html | `lotto_paper_filter` | `lotto_paper_pattern` |
| 21 | magic_square.html | `gung_filter` | `magic_square_pattern` |
| 22 | triangular_number.html | `triangular_filter` | `triangular_count` |

---

## 5. 이벤트 핸들러 수정

### 입력 필드 변경 시 자동 저장
```javascript
// Min/Max 입력 필드
document.getElementById('minFilter').addEventListener('change', saveFilterSettings);
document.getElementById('maxFilter').addEventListener('change', saveFilterSettings);

// 토글 체크박스
document.getElementById('applyFilterCheck').addEventListener('change', saveFilterSettings);
```

---

## 6. 전체 예시 (AC값 페이지)

```html
<script>
    // 전역 변수
    let allDrawData = [];
    let featuresMap = new Map();
    
    // ✅ 필터 설정 저장 (DB)
    async function saveFilterSettings() {
        const minInput = document.getElementById('minFilter');
        const maxInput = document.getElementById('maxFilter');
        const toggle = document.getElementById('applyFilterCheck');

        const data = {
            min: (minInput?.value !== '') ? parseInt(minInput.value) : 0,
            max: (maxInput?.value !== '') ? parseInt(maxInput.value) : 10,
            enabled: toggle?.checked ?? false
        };

        // DB에 저장
        if (window.filterService?.initialized) {
            await window.filterService.saveSetting('ac_value', data, data.enabled);
        } else {
            // fallback: localStorage
            localStorage.setItem('ac_filter', JSON.stringify(data));
        }
    }

    // ✅ 필터 설정 로드 (DB)
    async function loadFilterSettings() {
        let saved = null;
        
        // DB에서 로드 시도
        if (window.filterService?.initialized) {
            const data = await window.filterService.loadSetting('ac_value');
            if (data) {
                saved = { ...data.settings, enabled: data.enabled };
            }
        }
        
        // fallback: localStorage
        if (!saved) {
            const stored = localStorage.getItem('ac_filter');
            if (stored) saved = JSON.parse(stored);
        }
        
        // UI에 적용
        if (saved) {
            const minInput = document.getElementById('minFilter');
            const maxInput = document.getElementById('maxFilter');
            const toggle = document.getElementById('applyFilterCheck');

            if (minInput) minInput.value = saved.min ?? 0;
            if (maxInput) maxInput.value = saved.max ?? 10;
            if (toggle) toggle.checked = saved.enabled ?? false;
            
            return true;
        }
        return false;
    }

    // ✅ 페이지 초기화
    document.addEventListener('DOMContentLoaded', async function() {
        // 1. FilterService 초기화
        await initFilterService();
        
        // 2. 데이터 로드
        await loadDrawsAndFeatures();
        
        // 3. 필터 설정 로드
        await loadFilterSettings();
        
        // 4. 차트 및 통계 업데이트
        updateStatistics(currentRange);
        changeChartMode('distribution');
        
        // 5. AI 분석 실행
        refreshAIAnalysis();
    });
</script>
```

---

## 7. 비로그인 사용자 처리

FilterService는 로그인 사용자만 DB 저장을 지원합니다.
비로그인 시 자동으로 localStorage fallback이 동작합니다.

```javascript
if (window.filterService?.initialized) {
    // ✅ 로그인 상태: DB 사용
    await window.filterService.saveSetting('ac_value', data, enabled);
} else {
    // ⚠️ 비로그인 상태: localStorage 사용
    localStorage.setItem('ac_filter', JSON.stringify(data));
}
```

---

## 8. AI 분석에 필터 정보 포함

```javascript
async function refreshAIAnalysis() {
    // ✅ 활성화된 필터 정보를 AI에 전달
    let filterInfo = '';
    if (window.filterService?.initialized) {
        filterInfo = await window.filterService.formatFiltersForAI();
    }
    
    await window.AIAnalysis.executeAnalysis({
        containerId: 'aiAnalysisContent',
        analysisType: 'AC값 분석',
        subjectRound: subjectRound,
        targetRound: targetRound,
        customData: `
# [AC값 분석 데이터]
- 분석 범위: 최근 ${currentRange}회
- 평균 AC값: ${avg}
- 최근 10회차 추이: ${recentDraws}

${filterInfo}
        `,
        customRules: `...`
    });
}
```

---

## 📁 파일 구조

```
js/
├── common_v2.js      # 기존 (수정 없음)
├── layout.js         # 기존 (수정 없음)
├── theme.js          # 기존 (수정 없음)
└── filter/
    └── FilterService.js  # ✅ 새로 추가
```
