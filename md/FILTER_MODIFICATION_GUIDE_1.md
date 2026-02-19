# 필터 DB 저장 수정 지시서

## 목표
HTML 분석 페이지의 필터 저장 방식을 **localStorage → Supabase DB**로 변경

---

## 적용 대상 파일
- ac_value.html
- total_sum.html
- tail_sum.html
- tail_digit.html
- odd_even.html
- low_high.html
- prime_number.html
- composite_number.html
- square_number.html
- twin_number.html
- multiple.html
- consecutive_number.html
- carryover.html
- neighbor_number.html
- number_range.html
- hot_cold.html
- missing.html
- regression.html
- lotto_paper.html
- magic_square.html
- triangular_number.html

---

## 수정 사항 (총 5곳)

### 1. 스크립트 태그 추가

**찾을 코드:**
```html
<script src="js/common_v2.js"></script>  
<script src="js/layout.js"></script>
```

**변경할 코드:**
```html
<script src="js/common_v2.js"></script>  
<script src="js/filter/FilterService.js"></script>
<script src="js/layout.js"></script>
```

---

### 2. saveFilterSettings 함수 교체

**찾을 코드 패턴:**
```javascript
function saveFilterSettings() {
```
로 시작하는 함수 전체

**변경할 코드:**
```javascript
async function saveFilterSettings() {
    const minInput = document.getElementById('minFilter');
    const maxInput = document.getElementById('maxFilter');
    const toggle = document.getElementById('applyFilterCheck');

    const settings = {
        min: (minInput && minInput.value !== '') ? parseInt(minInput.value) : 0,
        max: (maxInput && maxInput.value !== '') ? parseInt(maxInput.value) : 10
    };
    const enabled = toggle ? toggle.checked : false;

    // DB 저장 (FilterService 사용)
    if (window.filterService && window.filterService.initialized) {
        await window.filterService.saveSetting('{{FILTER_KEY}}', settings, enabled);
    } else if (window.Utils && window.Utils.saveFilter) {
        // Fallback: localStorage
        window.Utils.saveFilter('{{LOCALSTORAGE_KEY}}', { ...settings, enabled });
    }
}
```

**{{FILTER_KEY}}와 {{LOCALSTORAGE_KEY}} 매핑:**

| 파일 | {{LOCALSTORAGE_KEY}} | {{FILTER_KEY}} |
|------|---------------------|----------------|
| ac_value.html | ac_filter | ac_value |
| total_sum.html | total_sum_filter | total_sum |
| tail_sum.html | tail_sum_filter | last_digit_sum |
| odd_even.html | odd_even_filter | odd_even_pattern |
| low_high.html | low_high_filter | high_low_pattern |
| prime_number.html | prime_filter | prime_count |
| composite_number.html | composite_filter | composite_count |
| square_number.html | square_filter | square_count |
| twin_number.html | twin_filter | twin_count |
| consecutive_number.html | consecutive_filter | consecutive_count |
| carryover.html | carryover_filter | carryover_count |
| neighbor_number.html | neighbor_filter | neighbor_count |
| hot_cold.html | hot_cold_filter | hot_cold_10 |
| missing.html | missing_filter | long_term_miss |
| lotto_paper.html | lotto_paper_filter | lotto_paper_pattern |
| magic_square.html | gung_filter | magic_square_pattern |
| triangular_number.html | triangular_filter | triangular_count |

---

### 3. loadFilterSettings 함수 교체

**찾을 코드 패턴:**
```javascript
function loadFilterSettings() {
```
로 시작하는 함수 전체

**변경할 코드:**
```javascript
async function loadFilterSettings() {
    let saved = null;

    // DB에서 로드 (FilterService 사용)
    if (window.filterService && window.filterService.initialized) {
        const data = await window.filterService.loadSetting('{{FILTER_KEY}}');
        if (data) {
            saved = { ...data.settings, enabled: data.enabled };
        }
    }
    
    // Fallback: localStorage
    if (!saved && window.Utils && window.Utils.loadFilter) {
        saved = window.Utils.loadFilter('{{LOCALSTORAGE_KEY}}');
    }

    if (saved) {
        const minInput = document.getElementById('minFilter');
        const maxInput = document.getElementById('maxFilter');
        const toggle = document.getElementById('applyFilterCheck');

        if (minInput) minInput.value = saved.min;
        if (maxInput) maxInput.value = saved.max;
        if (toggle) toggle.checked = saved.enabled;
        return true;
    }
    return false;
}
```

**{{FILTER_KEY}}와 {{LOCALSTORAGE_KEY}}는 위 2번 매핑표 참고**

---

### 4. DOMContentLoaded 안에 initFilterService 추가

**찾을 코드:**
```javascript
if (!client) throw new Error("Supabase Client가 초기화되지 않았습니다.");
```

**변경할 코드 (바로 다음 줄에 추가):**
```javascript
if (!client) throw new Error("Supabase Client가 초기화되지 않았습니다.");

// FilterService 초기화 (DB 필터 저장용)
if (window.initFilterService) {
    await window.initFilterService();
}
```

---

### 5. loadFilterSettings 호출을 await로 변경

**찾을 코드:**
```javascript
if (!loadFilterSettings()) {
```

**변경할 코드:**
```javascript
const filterLoaded = await loadFilterSettings();
if (!filterLoaded) {
```

---

## 주의사항

1. **js/filter/FilterService.js** 파일이 서버에 있어야 함
2. 파일을 `file://`로 열지 말고 **Live Server** 또는 로컬 서버로 실행해야 함
3. 각 파일마다 saveFilterSettings/loadFilterSettings 함수 구조가 조금씩 다를 수 있음 (min/max 외에 다른 필드가 있는 경우 해당 필드도 유지)

---

## 특수 케이스 (함수 구조가 다른 파일)

### tail_digit.html, hot_cold.html, multiple.html 등
이 파일들은 단순 min/max가 아닌 복잡한 구조를 가짐.
기존 settings 구조를 그대로 유지하면서 저장/로드 부분만 DB로 변경해야 함.

**예시 (기존 구조 유지):**
```javascript
async function saveFilterSettings() {
    // 기존 settings 수집 로직 그대로 유지
    const data = { /* 기존 구조 */ };
    
    const { enabled, ...settings } = data;
    
    if (window.filterService && window.filterService.initialized) {
        await window.filterService.saveSetting('{{FILTER_KEY}}', settings, enabled);
    } else if (window.Utils && window.Utils.saveFilter) {
        window.Utils.saveFilter('{{LOCALSTORAGE_KEY}}', data);
    }
}
```
