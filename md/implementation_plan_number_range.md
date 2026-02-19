
# 📋 number_range.html AI 구현 표준화 플랜

## 🛠 목표
`number_range.html` 파일을 `prime_number.html`과 동일한 구조로 표준화하여 AI 분석의 안정성과 일관성을 확보합니다.

## 📝 주요 변경 사항

### 1️⃣ `executeLocalAIAnalysis` 함수 추가 (라인 1000 이전에 삽입)
- `prime_number.html`의 1554라인에 있는 함수를 가져와서 `number_range`에 맞게 조정합니다.
- **기능**:
    - Supabase Edge Function (`analyze-lotto`) 호출
    - JSON 파싱 및 에러 처리
    - 결과를 HTML로 렌더링
    - 핵심 키워드 하이라이팅 (good, warn, trend 등)

### 2️⃣ `submitCustomAIAnalysis` 수정 (라인 1000)
- **변경 전**: `window.AIAnalysis.executeAnalysis({})` 직접 호출
- **변경 후**: `executeLocalAIAnalysis({})` 호출로 변경
- **이유**: 에러 핸들링 및 UI 렌더링 제어를 파일 내부에서 직접 하기 위함

### 3️⃣ `refreshAIAnalysis` 수정 (라인 1072)
- **변경 전**: `window.AIAnalysis.executeAnalysis({})` 직접 호출
- **변경 후**: `window.AIAnalysis`가 있으면 사용하되, 에러 발생 시 `executeLocalAIAnalysis` 로직과 유사한 fallback 메커니즘 검토 (일단은 유지하되 구조만 맞춤)
- **참고**: `refreshAIAnalysis`는 보통 자동 분석이므로 `window.AIAnalysis`를 사용하는 것이 맞을 수도 있으나, `prime_number.html`과 통일성을 위해 `executeLocalAIAnalysis` 사용을 고려합니다. `odd_even`은 `refresh`에서도 `window.AIAnalysis`를 씁니다. 따라서 **`refresh`는 `window.AIAnalysis`를 쓰고, `custom`은 `executeLocal`을 쓰는 패턴**으로 통일합니다.

## 🚀 상세계획

### Step 1: `executeLocalAIAnalysis` 함수 삽입
```javascript
async function executeLocalAIAnalysis(params) {
    const { containerId, targetRound, userPrompt, contextData } = params;
    const container = document.getElementById(containerId);

    if (container) {
        container.innerHTML = `
            <div class="flex items-center gap-3 p-2 text-gray-500">
                <div class="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
                <span class="text-xs">AI 번호대 분석 중...</span>
            </div>`;
    }

    try {
        const prompt = `
# Role: 로또 번호대 분석 전문가
# Target: ${targetRound}회차 전략
# Context: ${contextData}
# User Question: "${userPrompt}"

# Instructions:
1. 답변은 **핵심만 요약된 단일 단락**으로 작성하시오.
2. 번호대 분석에서는 '필출 구간', '멸 구간', '과열 주의'가 핵심입니다.
3. 응답은 **반드시 유효한 JSON 포맷**이어야 합니다.
4. 중요 키워드는 JSON의 highlights 배열에 담아주세요.

JSON 구조:
{
  "response": "순수 텍스트 답변 내용",
  "highlights": [
    {"text": "키워드", "type": "good|warn|trend"}
  ]
}
`;

        const { data, error } = await window.supabaseClient.functions.invoke('analyze-lotto', {
            body: { context: prompt }
        });
        if (error) throw error;

        // ... (JSON 파싱 및 렌더링 로직: prime_number.html 참고) ...
    } catch (err) {
        // ... (에러 처리) ...
    }
}
```

### Step 2: `submitCustomAIAnalysis` 내 호출부 변경
```javascript
// 기존
await window.AIAnalysis.executeAnalysis({ ... });

// 변경
await executeLocalAIAnalysis({
    containerId: uniqueId,
    targetRound,
    userPrompt,
    contextData: contextStr + `\n\nHistory:\n${memoryStr}`
});
```

### Step 3: `submitModalFollowUp` 내 호출부 변경
- 모달 내 대화에서도 `executeLocalAIAnalysis`를 사용하도록 변경합니다.

## ✅ 기대 효과
1. **안정성**: 외부 라이브러리(`window.AIAnalysis`) 의존성을 줄이고 파일 자체적으로 AI 기능을 완결성 있게 수행
2. **일관성**: `prime_number`, `odd_even` (수정본)과 동일한 코드 패턴 유지보수 용이
3. **디버깅**: 에러 발생 시 파일 내에서 즉시 확인 가능
