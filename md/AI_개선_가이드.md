# AI 분석 코드 개선 가이드

> ac_value.html에 적용한 개선사항을 나머지 22개 기초분석 HTML 파일에도 동일하게 적용하기 위한 가이드

---

## 0. 치명적 발견: aiProxy.js 누락 (Phase 0 — 최우선 수정)

**현재 `aiProxy.js`를 포함하는 파일은 3개뿐:**
- `ai_deep_learning.html`
- `custom_analysis.html`
- `number_range.html` (방금 추가)

**나머지 모든 기초분석 HTML에 `aiProxy.js`가 빠져 있어서 `window.AIProxy`가 항상 `undefined`**
→ `common_v2.js`의 `executeAnalysis()`에서 항상 Edge Function 폴백으로 빠짐
→ Python RAG/딥러닝 파이프라인이 전혀 사용되지 않음

### 수정 방법
각 HTML 파일의 `<head>` 내 스크립트 영역에서 `common_v2.js` 뒤에 추가:
```html
<script src="js/aiProxy.js"></script>
```

### 추가 대상 파일 (19개)
- carryover.html, consecutive_number.html, composite_number.html
- hot_cold.html, low_high.html, odd_even.html, missing.html
- tail_digit.html, tail_sum.html, total_sum.html
- stats_by_number.html, neighbor_number.html, multiple.html
- square_number.html, triangular_number.html
- twin_number.html, magic_square.html, regression.html
- lotto_paper.html, properties_matrix.html

**ac_value.html도 확인 필요** — `executeLocalAIAnalysis`에서 `window.AIProxy`를 사용하도록 수정했지만 `aiProxy.js`가 로드되지 않으면 항상 Edge Function 폴백.

### 0-1. aiProxy.js 타임아웃 버그 수정 (완료)

`aiProxy.js`를 추가하면 AI 분석 로딩이 멈추는 현상이 발생했음.
- **원인**: `invokeEdgeFunction()`에 타임아웃이 없어서, Edge Function이 응답하지 않으면 무한 대기
- **수정 내용** (`js/aiProxy.js`):
  1. `invokeEdgeFunction()`: `Promise.race`로 TIMEOUT(30초) 제한 추가
  2. `invoke()` 내 Python 요청: `AbortController` + `signal`로 TIMEOUT 제한 추가
- **결과**: 30초 내 응답 없으면 타임아웃 에러 → `getErrorUI()` 표시 (무한 로딩 방지)

---

## 1. 개선 대상 파일 목록 (22개)

| # | 파일명 | 분석 유형 | refreshAIAnalysis | submitCustomAIAnalysis | executeLocalAIAnalysis |
|---|--------|-----------|:-:|:-:|:-:|
| 1 | carryover.html | 이월수 | L1317 | L1075 | L1465 |
| 2 | consecutive_number.html | 연번 | L1378 | L1342 | L1583 |
| 3 | composite_number.html | 합성수 (완료) | L888 | L1468 | L803 |
| 4 | hot_cold.html | 핫/콜드 (완료) | L1232 | L1367 | L1457 |
| 5 | low_high.html | 저고 비율 | L1462 | L1229 | L1167, L1382 |
| 6 | odd_even.html | 홀짝 (완료) | L1455 | L1227 | L1289 |
| 7 | missing.html | 미출현 | L1911 | L1828, L2139 | L2055 |
| 8 | tail_digit.html | 끝수 | L1003 | L1698 | L1592 |
| 9 | tail_sum.html | 끝수합 | L1818 | L1886 | L1220 |
| 10 | total_sum.html | 총합 | L1545 | L1423, L1620 | L1344 |
| 11 | stats_by_number.html | 번호별 통계 | L1098 | L1070 | L1025 |
| 12 | number_range.html | 번호대 (완료) | L1471 | L1362 | L1250 |
| 13 | neighbor_number.html | 이웃수 (완료) | L1341 | L1148 | L1203 |
| 14 | multiple.html | 배수 | L1339 | L1117 | L1171 |
| 15 | prime_number.html | 소수 (완료) | L1829 | L1536 | L1738 |
| 16 | square_number.html | 제곱수 | L1593 | L1502 | L1411 |
| 17 | triangular_number.html | 삼각수 | L1479 | L1342 | L1239 |
| 18 | twin_number.html | 동형수(쌍수) | L1816 | L1527 | L1725 |
| 19 | magic_square.html | 마방진 | L1087, L1259 | L1209 | L1400 |
| 20 | regression.html | 회귀 분석 | L1536 | L1160 | L1234 |
| 21 | lotto_paper.html | 로또용지 | L1050 | L1012 | L1153 |
| 22 | properties_matrix.html | 성질 매트릭스 (완료) | L2721 (특수) | L4065 | L2610 |

> `L숫자` = 해당 함수가 시작되는 라인 번호 (참고용, 수정 시 반드시 실제 라인 확인)

---

## 2. 수정해야 할 3가지 함수

### 2-1. `refreshAIAnalysis()` — AI Insight 기본 리포트

#### 현재 문제
```
모든 파일이 동일한 패턴:
- 최근 5~10회 데이터를 단순 문자열로 변환
- 1~3줄의 빈약한 contextData만 전송
- customRules에 "에너지 진단" 등 유사과학 표현 포함
```

#### 수정 방향
각 분석 유형에 맞는 **풍부한 통계 데이터**를 계산하여 contextData에 포함시킨다.

#### 공통 추가 데이터 (모든 파일에 적용)
```javascript
// ── 1. 기본 통계 ──
const avg = ...; // 전체 평균
const stdDev = ...; // 표준편차
const min = ...; const max = ...; // 최소/최대

// ── 2. 분포 데이터 ──
// 각 값별 출현 횟수와 비율 (%)

// ── 3. 최근 30회차 상세 데이터 ──
// 회차별 값 + 당첨번호 나열

// ── 4. 이동평균 비교 ──
const recent5Avg = ...;
const recent10Avg = ...;
const recent20Avg = ...;
const trendDirection = recent5Avg > recent10Avg ? '상승세' : '하락세';

// ── 5. 연속 패턴 ──
// 최대 연속 상승/하락/동일값 횟수

// ── 6. 구간별 빈도 ──
// 저/중/고 또는 분석 유형별 구간 분류
```

#### customRules 수정
```
변경 전: "에너지 진단", "에너지가 응축/폭발" 등
변경 후: "통계 진단", "출현 빈도가 침체/과열" 등

모든 customRules에 아래 금지어 목록 추가:
"에너지, 기운, 파동, 운세, 소액 투자, 분산 투자, 고액 투자 지양, 투자 전략,
 100% 보장은 없다, 참고용, 책임지지 않습니다, 재미로, 행운을 빕니다,
 당첨을 기원, 감이 좋다, 직감, 필승, 대박"
```

#### 파일별 추가 데이터 가이드

| 파일 | 핵심 메트릭 | 추가해야 할 통계 |
|------|------------|----------------|
| carryover.html | carryoverCount | 이월수 개수별 분포(0~6), 연속 멸(0개) 최대 기록, 이월 번호 빈도 TOP5 |
| consecutive_number.html | neighborCount | 연번 쌍수별 분포(0~3쌍), 연번 포함 번호 빈도, 3연번 이상 발생 비율 |
| composite_number.html | compositeCount | 합성수 개수별 분포, 소수 vs 합성수 비율 추이, 최근 30회 상세 |
| hot_cold.html | Hot/Cold/Neutral 분류 | 구간별(10/15/20/25/30회) Hot/Cold 개수 변화, 전환율(Hot→Cold, Cold→Hot) |
| low_high.html | low:high 비율 | 비율별 분포(6:0~0:6), 연속 동일비율 기록, 평균 회귀 주기 |
| odd_even.html | odd:even 비율 | 비율별 분포(6:0~0:6), 연속 동일비율 기록, 평균 회귀 주기 |
| missing.html | gap (미출현 기간) | 대상 번호의 전체 미출현 기록, 역대 최대 gap, 평균 출현 주기, 최근 출현 이후 경과 |
| tail_digit.html | 끝수(0~9) 분포 | 끝수별 출현 빈도, 연속 출현/미출현 기록, 끝수합 통계 |
| tail_sum.html | tailSum | 끝수합 분포(구간별), 이동평균, 표준편차, 연속 상승/하락 기록 |
| total_sum.html | totalSum | 총합 분포(구간별), 이동평균, 표준편차, 평균 회귀 분석 |
| stats_by_number.html | 번호별 출현빈도 | Hot/Cold 번호 리스트, gap 상위 번호, 최근 출현 빈도 TOP/BOTTOM 10 |
| number_range.html | 번호대별 분포 | 번호대별(단번/10번/20번/30번/40번) 출현 개수 분포, 멸 구간 기록 |
| neighbor_number.html | 이웃수 개수 | 이웃수 개수별 분포, 보너스볼 이웃수 비율, 연속 출현/멸 기록 |
| multiple.html | 배수별 개수 | 3배수/4배수/5배수별 출현 분포, 공배수 출현율, 멸 구간 기록 |
| prime_number.html | primeCount | 소수 개수별 분포(0~6), 각 소수(2,3,5,7,11,...) 개별 출현율, 이월 소수 비율 |
| square_number.html | squareCount | 제곱수 개수별 분포, 각 제곱수(1,4,9,16,25,36) 개별 출현율 |
| triangular_number.html | triangularCount | 삼각수 개수별 분포, 각 삼각수 개별 출현율, 멸/다출 주기 |
| twin_number.html | twinCount | 동형수(11,22,33,44) 개별 출현율, 동형수 개수별 분포, 멸 주기 |
| magic_square.html | 9궁 분포 | 각 궁별 출현 개수 분포, 멸 궁 기록, 중심궁(5궁) 집중도 |
| regression.html | 회귀 적중 여부 | 현재 Step의 적중률, 연속 적중/미적중 기록, 최적 Step 후보 |
| lotto_paper.html | 가로/세로 라인 분포 | 라인별 출현 개수, 멸 라인 비율, 쏠림 라인 기록 |
| properties_matrix.html | 번호별 성질 종합 | (특수 구조 — 별도 처리 필요) |

---

### 2-2. `submitCustomAIAnalysis()` — 퀵버튼 / 사용자 질문

#### 현재 문제
```javascript
// 모든 파일 동일 패턴 (예: carryover.html L1142)
const recentTrend = allDrawData.slice(0, 10).map(d => `${d.round}회(${d.carryoverCount}개)`).join(', ');
await executeLocalAIAnalysis({
    contextData: `- 최근 10회 이월수 흐름: ${recentTrend}`  // ← 이게 전부
});
```

#### 수정 방향
`refreshAIAnalysis`에서 계산한 통계를 축약 버전으로 포함시킨다.

#### 수정 템플릿
```javascript
// submitCustomAIAnalysis() 내부, AI 호출 직전
const data = allDrawData.slice(0, currentRange);
const allValues = data.map(d => d.{메트릭필드});  // 분석 유형에 맞는 필드

// 기본 통계
const avg = allValues.reduce((a, b) => a + b, 0) / allValues.length;
const variance = allValues.reduce((s, v) => s + Math.pow(v - avg, 2), 0) / allValues.length;
const stdDev = Math.sqrt(variance);

// 이동평균
const recent5Avg = data.slice(0, 5).reduce((s, d) => s + d.{메트릭필드}, 0) / Math.min(5, data.length);
const recent10Avg = data.slice(0, 10).reduce((s, d) => s + d.{메트릭필드}, 0) / Math.min(10, data.length);
const trendDirection = recent5Avg > recent10Avg ? '상승세' : '하락세';

// 분포 계산
const dist = {};
allValues.forEach(v => { dist[v] = (dist[v] || 0) + 1; });
const distText = Object.entries(dist).sort((a,b) => a[0]-b[0]).map(([k, v]) => `${k}:${v}회`).join(', ');

// 최근 20회 상세
const recent20 = data.slice(0, 20).map(d => `${d.round}회(${d.{메트릭필드}})`).join(', ');

const richContext = `
- 최근 20회: ${recent20}
- 평균: ${avg.toFixed(2)} | 표준편차: ${stdDev.toFixed(2)} | 추세: ${trendDirection}
- 5회 이동평균: ${recent5Avg.toFixed(2)} | 10회 이동평균: ${recent10Avg.toFixed(2)}
- 분포(${currentRange}회): ${distText}
`;
```

---

### 2-3. `executeLocalAIAnalysis()` — 로컬 AI 실행 함수

#### 현재 문제 (모든 파일 동일)
```javascript
// 1. AIProxy를 사용하지 않고 Edge Function 직접 호출 → 딥러닝 우회
const { data, error } = await window.supabaseClient.functions.invoke('analyze-lotto', { body: { context: prompt } });

// 2. 프롬프트에 금지어 없음
const prompt = `
# Role: 로또 ${분석유형} 분석 전문가
# Target: ${targetRound}회차 전략
# Context: ${contextData}
# User Question: "${userPrompt}"
# Instructions:
1. 답변은 핵심만 요약된 단일 단락으로 작성하시오.
...
`;
```

#### 수정 방향: AIProxy 우선 사용 + 금지어 추가

#### 수정 템플릿 (ac_value.html 기준)
```javascript
async function executeLocalAIAnalysis(params) {
    const { containerId, subjectRound, targetRound, userPrompt, contextData } = params;
    const container = document.getElementById(containerId);
    if (container) {
        container.innerHTML = `로딩 UI...`;
    }
    try {
        const prompt = `
# Role: 로또 ${분석유형} 데이터 분석 전문가
# Target: ${targetRound}회차 전략
# Context Data:
${contextData}
# User Question: "${userPrompt}"

# 절대 금지어 (어떤 경우에도 사용 금지):
에너지, 기운, 파동, 흐름이 좋다, 운세, 소액 투자, 분산 투자, 고액 투자 지양, 투자 전략,
100% 보장은 없다, 참고용, 책임지지 않습니다, 재미로, 행운을 빕니다, 당첨을 기원,
감이 좋다, 직감, 필승, 대박

# 분석 규칙:
1. 반드시 Context Data에 제공된 실제 숫자를 인용하며 분석하라
2. 구체적 수치를 근거로 제시하라
3. 제공되지 않은 데이터를 창작하지 마라
4. 답변은 3~5문장의 핵심 분석으로 작성하라
5. 중요 수치는 highlights 배열에 담아라

# JSON 구조:
{
  "response": "데이터 인용 기반 분석 답변 (3~5문장)",
  "highlights": [
    {"text": "키워드나 수치", "type": "good" | "warn" | "trend"}
  ]
}
`;

        // ★ 핵심 변경: AIProxy 우선 사용
        let data, error;
        if (window.AIProxy) {
            try {
                data = await window.AIProxy.invoke({
                    prompt: prompt,
                    analysisType: '${분석타입_영문}',
                    targetRound: targetRound,
                    subjectRound: subjectRound,
                    responseStyle: 'chat'
                });
            } catch (proxyErr) {
                console.warn('AIProxy failed, falling back to Edge Function:', proxyErr);
                const result = await window.supabaseClient.functions.invoke('analyze-lotto', { body: { context: prompt } });
                data = result.data;
                error = result.error;
            }
        } else {
            const result = await window.supabaseClient.functions.invoke('analyze-lotto', { body: { context: prompt } });
            data = result.data;
            error = result.error;
        }
        if (error) throw error;

        // ... 이하 응답 처리 코드는 기존과 동일 ...
    }
}
```

---

## 3. 파일별 `analysisType` 값 매핑

| 파일 | analysisType 값 |
|------|-----------------|
| carryover.html | `'carryover'` |
| consecutive_number.html | `'consecutive_number'` |
| composite_number.html | `'composite'` |
| hot_cold.html | `'hot_cold'` |
| low_high.html | `'low_high'` |
| odd_even.html | `'odd_even'` |
| missing.html | `'missing_number'` |
| tail_digit.html | `'tail_digit'` |
| tail_sum.html | `'tail_sum'` |
| total_sum.html | `'total_sum'` |
| stats_by_number.html | `'stats_by_number'` |
| number_range.html | `'number_range'` |
| neighbor_number.html | `'neighbor_number'` |
| multiple.html | `'multiple'` |
| prime_number.html | `'prime_number'` |
| square_number.html | `'square_number'` |
| triangular_number.html | `'triangular_number'` |
| twin_number.html | `'twin_number'` |
| magic_square.html | `'magic_square'` |
| regression.html | `'regression'` |
| lotto_paper.html | `'lotto_paper'` |
| properties_matrix.html | `'properties_matrix'` (특수 구조) |

---

## 4. 파일별 핵심 데이터 필드 (allDrawData 구조)

각 파일의 `allDrawData` 배열 내 객체가 가진 핵심 필드:

| 파일 | 핵심 필드 | 설명 |
|------|-----------|------|
| carryover.html | `carryoverCount`, `carryoverNumbers`, `bonusCarryover`, `gap` | 이월수 개수, 이월된 번호 목록, 보너스 이월 여부, 미출현 갭 |
| consecutive_number.html | `neighborCount`, `consecutivePairs` | 연번 쌍 수, 연번 목록 |
| composite_number.html | `compositeCount`, `primeCount` | 합성수 개수, 소수 개수 |
| hot_cold.html | `hotCount`, `coldCount`, `neutralCount` | 핫/콜드/중립 번호 개수 |
| low_high.html | `lowCount`, `highCount` | 저번호(1~22) 개수, 고번호(23~45) 개수 |
| odd_even.html | `oddCount`, `evenCount` | 홀수 개수, 짝수 개수 |
| missing.html | `gap`, `numbers`, `bonus` | 미출현 기간, 당첨번호, 보너스 |
| tail_digit.html | `tailDigits`, `tailSum` | 끝수 배열, 끝수 합 |
| tail_sum.html | `tailSum` | 끝수 합계 |
| total_sum.html | `totalSum` | 번호 총합 |
| stats_by_number.html | `numbers`, `bonus`, `freq`, `gap` | 번호별 통계 |
| number_range.html | `rangeDistribution` | 번호대별 분포 {단번대, 10번대, ...} |
| neighbor_number.html | `neighborCount`, `neighborNumbers` | 이웃수 개수, 이웃수 목록 |
| multiple.html | `multipleCount` (3배수/4배수/5배수별) | 배수 개수 |
| prime_number.html | `primeCount`, `primeNumbers` | 소수 개수, 소수 목록 |
| square_number.html | `squareCount`, `squareNumbers` | 제곱수 개수, 제곱수 목록 |
| triangular_number.html | `triangularCount`, `triangularNumbers` | 삼각수 개수, 삼각수 목록 |
| twin_number.html | `twinCount`, `twinNumbers` | 동형수 개수, 동형수 목록 |
| magic_square.html | `magicSquareDistribution` | 9궁별 번호 분포 |
| regression.html | `regressionHit`, `step`, `hitRate` | 회귀 적중 여부, 주기, 적중률 |
| lotto_paper.html | `rowDistribution`, `colDistribution` | 가로/세로 라인별 분포 |

> 실제 필드명은 파일마다 다를 수 있으므로, 수정 시 해당 파일의 `allDrawData` 구조를 반드시 확인할 것

---

## 5. "에너지" 표현이 포함된 파일 (즉시 수정 필요)

| 파일 | 라인 | 현재 표현 | 수정 후 |
|------|------|----------|--------|
| carryover.html | L1385 | `[에너지 진단]: 현재 이월수가 계속 쏟아져 나오는 '과열' 상태인지` | `[통계 진단]: 현재 이월수가 계속 쏟아져 나오는 '과열' 상태인지` |
| composite_number.html | L928 | `현재 합성수의 출현 에너지가 '응축(침체)' 중인지 '폭발(과열)' 중인지` | `현재 합성수의 출현 빈도가 '침체' 중인지 '과열' 중인지` |
| hot_cold.html | L1280 | `[에너지 진단]: 현재 핫넘버의 '재발동' 임계점인지` | `[통계 진단]: 현재 핫넘버의 '재발동' 임계점인지` |
| tail_digit.html | L1063 | `최근 끝수 합의 에너지 흐름이 '상승' 중인지` | `최근 끝수 합의 통계적 흐름이 '상승' 중인지` |

---

## 6. common_v2.js 수정 사항 (이미 완료)

### 완료된 항목
- [x] `generatePrompt()` default 스타일: `"패턴 및 에너지 분석"` → `"통계 패턴 분석 - 수치 근거 기반"`
- [x] 3가지 스타일(simple/chat/default) 모두 금지어 목록 추가
- [x] 3가지 스타일 모두 "데이터 인용 필수, 창작 금지" 규칙 추가
- [x] AC값 프롬프트 라이브러리 3개 → 10개 확장
- [x] 프롬프트 라이브러리 모달 위치: 버튼 아래 fixed 기준

---

## 7. 작업 순서 권장

### Phase 1: executeLocalAIAnalysis 일괄 수정 (가장 영향 큰 부분)
- 22개 파일 모두 동일 패턴이므로 일괄 적용 가능
- AIProxy 우선 사용 + 금지어 추가 + 프롬프트 강화
- 변경 포인트:
  - `supabaseClient.functions.invoke` 직접 호출 → `window.AIProxy.invoke` 우선 + 폴백
  - 프롬프트에 금지어 블록 추가
  - Role 텍스트에 "데이터" 명시 (예: `로또 이월수 데이터 분석 전문가`)

### Phase 2: submitCustomAIAnalysis 데이터 보강
- 22개 파일 각각의 분석 유형에 맞는 통계 데이터 계산 코드 추가
- `contextData`에 평균, 표준편차, 이동평균, 분포, 구간별 빈도 포함

### Phase 3: refreshAIAnalysis 데이터 보강
- 가장 개별화가 필요한 부분 (파일마다 메트릭이 다름)
- 각 파일의 핵심 통계를 최대한 풍부하게 계산하여 contextData에 포함
- customRules에서 "에너지" 표현 제거, 금지어 추가

### Phase 4: 특수 파일 처리
- `properties_matrix.html` — 구조가 완전히 다름 (refreshAIAnalysis가 submitAIAnalysis 호출). 별도 분석 필요
- `missing.html` — submitCustomAIAnalysis가 2개 정의됨 (L1828, L2139). 중복 제거 확인 필요
- `low_high.html` — executeLocalAIAnalysis가 2개 정의됨 (L1167, L1382). 중복 제거 확인 필요
- `magic_square.html` — refreshAIAnalysis가 2개 정의됨 (L1087, L1259). 중복 제거 확인 필요
- `total_sum.html` — submitCustomAIAnalysis가 2개 정의됨 (L1423, L1620). 중복 제거 확인 필요

---

## 8. 수정 체크리스트

각 파일 수정 시 아래 항목을 확인:

- [x] `refreshAIAnalysis()` — contextData에 최소 5가지 통계 카테고리 포함
- [x] `refreshAIAnalysis()` — customRules에서 "에너지" 표현 제거
- [x] `refreshAIAnalysis()` — customRules에 금지어 목록 추가
- [x] `submitCustomAIAnalysis()` — contextData에 평균/표준편차/이동평균/분포 포함
- [x] `executeLocalAIAnalysis()` — `window.AIProxy` 우선 사용 + Edge Function 폴백
- [x] `executeLocalAIAnalysis()` — 프롬프트에 금지어 블록 추가
- [x] `executeLocalAIAnalysis()` — 프롬프트에 "데이터 인용 필수, 창작 금지" 규칙 추가
- [x] `executeLocalAIAnalysis()` — analysisType이 올바른 값으로 설정됨 (hot_cold)
- [ ] 중복 함수 정의가 없는지 확인 (missing, low_high, magic_square, total_sum)
