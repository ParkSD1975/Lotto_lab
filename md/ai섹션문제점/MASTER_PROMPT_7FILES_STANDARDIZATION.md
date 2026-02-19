# 🎯 7개 파일 공통 수정 마스터 프롬프트

> 이 프롬프트를 사용하여 7개 파일을 일괄적으로 수정하세요:
> square_number.html, stats_by_number.html, tail_digit.html, tail_sum.html, total_sum.html, triangular_number.html, twin_number.html

---

## 📋 **공통 수정 사항 (모든 7개 파일에 적용)**

### **1️⃣ AI 챗봇 모달 추가**

#### 1-1) HTML에서 `</body>` 직전에 추가:

```html
<!-- AI Sidebar Modal -->
<div id="aiModal" class="fixed inset-0 z-50 flex items-end md:items-center hidden">
    <!-- 반투명 배경 -->
    <div id="aiModalBg" class="absolute inset-0 bg-black/50" onclick="closeAIModal()"></div>
    
    <!-- 모달 본체 -->
    <div class="relative bg-white rounded-t-xl md:rounded-xl md:max-w-2xl md:mx-auto w-full md:w-full h-[80vh] md:h-[80vh] flex flex-col shadow-2xl">
        <!-- 헤더 -->
        <div class="flex items-center justify-between p-4 border-b border-gray-100">
            <h2 class="text-lg font-bold text-gray-900">AI 분석 챗봇</h2>
            <button onclick="closeAIModal()" class="p-2 hover:bg-gray-100 rounded-lg transition-colors">
                <span class="material-symbols-outlined">close</span>
            </button>
        </div>
        
        <!-- 채팅 영역 -->
        <div id="aiQnaContent" class="flex-1 p-5 overflow-y-auto custom-scrollbar flex flex-col gap-4"></div>
        
        <!-- 입력 영역 -->
        <div class="p-4 border-t border-gray-100 flex-shrink-0">
            <div class="relative flex gap-2">
                <input type="text" id="aiModalInput"
                    class="flex-1 pl-4 pr-4 py-3 bg-gray-50 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 transition-all placeholder-gray-400"
                    placeholder="추가 질문..."
                    onkeyup="if(event.key === 'Enter') submitModalFollowUp()">
                <button onclick="submitModalFollowUp()"
                    class="px-4 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors">
                    <span class="material-symbols-outlined text-xl">send</span>
                </button>
            </div>
        </div>
    </div>
</div>
```

#### 1-2) JavaScript에서 `<script>` 내부에 추가:

```javascript
// AI Modal Functions
function openAIModal(initialPrompt = '') {
    const modal = document.getElementById('aiModal');
    const content = document.getElementById('aiQnaContent');
    if (modal) {
        modal.classList.remove('hidden');
        content.innerHTML = '';
        chatHistory = [];
        if (initialPrompt) {
            const userMsg = `<div class="flex justify-end mb-4"><div class="bg-blue-600 text-white px-4 py-2 rounded-2xl shadow-sm text-sm">${initialPrompt}</div></div>`;
            content.innerHTML += userMsg;
        }
    }
}

function closeAIModal() {
    const modal = document.getElementById('aiModal');
    if (modal) modal.classList.add('hidden');
}

let chatHistory = [];

async function submitModalFollowUp() {
    const input = document.getElementById('aiModalInput');
    if (!input || !input.value.trim()) return;
    
    const userMessage = input.value.trim();
    input.value = '';
    
    const content = document.getElementById('aiQnaContent');
    content.innerHTML += `<div class="flex justify-end mb-4"><div class="bg-blue-600 text-white px-4 py-2 rounded-2xl shadow-sm text-sm">${userMessage}</div></div>`;
    
    const uniqueId = 'ai-res-' + Date.now();
    content.innerHTML += `<div class="flex mb-4"><div class="w-7 h-7 rounded-full bg-blue-500 flex items-center justify-center text-white text-[10px] mr-2 flex-shrink-0">AI</div><div id="${uniqueId}" class="bg-white border text-gray-800 px-4 py-2 rounded-2xl shadow-sm text-sm min-h-[40px] flex-1"></div></div>`;
    
    // 컨텍스트 데이터 준비
    const recentDraws = allDrawData.slice(0, 10).map(d => `[${d.round}회]`).join(', ');
    const contextData = `최근 10회차: ${recentDraws}`;
    
    await executeLocalAIAnalysis({
        containerId: uniqueId,
        userPrompt: userMessage,
        contextData: contextData
    });
    
    content.scrollTop = content.scrollHeight;
}
```

---

### **2️⃣ executeLocalAIAnalysis 함수 추가 (아직 없는 파일들)**

다음 파일들에만 추가하세요:
- square_number.html
- stats_by_number.html
- tail_sum.html
- total_sum.html
- twin_number.html

(`tail_digit.html`, `triangular_number.html`는 이미 있음)

```javascript
async function executeLocalAIAnalysis(params) {
    const { containerId, userPrompt, contextData } = params;
    const container = document.getElementById(containerId);
    
    if (container) {
        container.innerHTML = `
            <div class="flex items-center gap-3 p-2 text-gray-500">
                <div class="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
                <span class="text-xs">AI 분석 중...</span>
            </div>`;
    }
    
    try {
        const prompt = `
# Role: 로또 분석 전문가
# Context: ${contextData}
# User Question: "${userPrompt}"

# Instructions:
1. 답변은 **핵심만 요약된 단일 단락**으로 작성하시오.
2. 중요 키워드는 JSON의 highlights 배열에 담아주세요. 본문에는 태그를 쓰지 마세요.
3. 응답은 **반드시 유효한 JSON 포맷**이어야 합니다.
4. JSON 구조: 
{
  "response": "순수 텍스트 답변 내용",
  "highlights": [
    {"text": "키워드", "type": "good" | "warn" | "trend"}
  ]
}
`;
        
        const { data, error } = await window.supabaseClient.functions.invoke('analyze-lotto', { 
            body: { context: prompt } 
        });
        
        if (error) throw error;
        
        let content = '';
        let highlights = [];
        
        if (typeof data === 'string') {
            try {
                const parsed = JSON.parse(data);
                content = parsed.response || parsed.recommendation || JSON.stringify(parsed);
                if (parsed.highlights) highlights = parsed.highlights;
            } catch (e) {
                content = data;
            }
        } else {
            content = data.response || data.recommendation || JSON.stringify(data);
            if (data.highlights) highlights = data.highlights;
        }
        
        if (container) {
            let safeContent = content.replace(/</g, "&lt;").replace(/>/g, "&gt;");
            
            if (highlights.length > 0) {
                const tagColors = { good: 'text-blue-600', warn: 'text-red-600', trend: 'text-teal-600' };
                highlights.forEach(h => {
                    const color = tagColors[h.type] || 'text-blue-600';
                    const escapedText = h.text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                    const regex = new RegExp(escapedText, 'g');
                    safeContent = safeContent.replace(regex, `<span class="${color} font-bold">${h.text}</span>`);
                });
            }
            
            container.innerHTML = `<div class="prose prose-sm max-w-none text-gray-800 leading-relaxed">${safeContent}</div>`;
            chatHistory.push({ role: 'assistant', content: content });
        }
    } catch (err) {
        console.error('Local AI Error:', err);
        if (container) {
            container.textContent = `분석 실패: ${err.message}`;
            container.className = 'text-red-500 text-xs p-2';
        }
    }
}
```

---

### **3️⃣ AI Insight 섹션 최적화 (모든 파일)**

각 파일의 AI Insight 섹션을 다음과 같이 확인 & 수정하세요:

#### 3-1) Header 부분:
```html
<div class="flex items-center justify-between mb-6">
    <div class="flex items-baseline gap-2">
        <h3 class="text-2xl font-extrabold text-gray-900 tracking-tight">AI Insight</h3>
        <span id="aiTargetInfo" class="text-sm text-gray-500 font-medium"></span>
    </div>
    <button onclick="window.AIAnalysis.openPromptLibraryModal('[파일명]', event)"
        class="flex items-center gap-1.5 px-3 py-1.5 bg-blue-50 text-blue-600 rounded-lg text-sm font-medium hover:bg-blue-100 transition-colors">
        <span class="material-symbols-outlined text-lg">library_books</span>
        프롬프트 라이브러리
    </button>
</div>
```

**[파일명] 자리에 다음을 넣으세요:**
- square_number.html → `'square_number'`
- stats_by_number.html → `'stats_by_number'`
- tail_digit.html → `'tail_digit'`
- tail_sum.html → `'tail_sum'`
- total_sum.html → `'total_sum'`
- triangular_number.html → `'triangular_number'`
- twin_number.html → `'twin_number'`

#### 3-2) Content 부분:
```html
<div id="aiAnalysisContent" class="min-h-[100px] flex items-center justify-center">
    <div class="flex items-center gap-2 text-gray-500">
        <span class="material-symbols-outlined text-lg animate-spin">progress_activity</span>
        <span>AI가 분석하고 있습니다...</span>
    </div>
</div>
```

#### 3-3) 샘플 버튼 10개 (표준화):
```html
<div class="flex gap-2 overflow-x-auto pb-2 scrollbar-hide">
    <button onclick="document.getElementById('aiUserPrompt').value='[질문1]'; submitCustomAIAnalysis()"
        class="px-3 py-1.5 text-xs font-medium bg-blue-50 text-blue-600 rounded-full hover:bg-blue-100 transition-colors whitespace-nowrap">
        [아이콘1] [버튼명1]
    </button>
    <!-- 반복... 총 10개까지 -->
</div>
```

#### 3-4) 입력 필드:
```html
<div class="relative">
    <input type="text" id="aiUserPrompt"
        class="w-full pl-4 pr-12 py-3 bg-gray-50 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 transition-all placeholder-gray-400"
        placeholder="질문을 입력해주세요..."
        onkeyup="if(event.key === 'Enter') submitCustomAIAnalysis()">
    <button onclick="submitCustomAIAnalysis()"
        class="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 text-blue-600 hover:bg-blue-100 rounded-lg transition-colors">
        <span class="material-symbols-outlined text-xl">send</span>
    </button>
</div>
```

---

### **4️⃣ submitCustomAIAnalysis 함수 (모든 파일)**

```javascript
async function submitCustomAIAnalysis() {
    const inputEl = document.getElementById('aiUserPrompt');
    const userPrompt = inputEl.value.trim();
    if (!userPrompt) return;
    
    openAIModal(userPrompt);
    inputEl.value = '';
    
    // 컨텍스트 데이터 준비
    const recentDraws = allDrawData.slice(0, 10).map(d => `[${d.round}회]`).join(', ');
    const contextData = `최근 10회차: ${recentDraws}`;
    
    const qnaContent = document.getElementById('aiQnaContent');
    if (qnaContent) {
        const uniqueId = 'ai-res-' + Date.now();
        qnaContent.innerHTML += `<div class="flex mb-4"><div class="w-7 h-7 rounded-full bg-blue-500 flex items-center justify-center text-white text-[10px] mr-2 flex-shrink-0">AI</div><div id="${uniqueId}" class="bg-white border text-gray-800 px-4 py-2 rounded-2xl shadow-sm text-sm min-h-[40px] flex-1"></div></div>`;
        
        executeLocalAIAnalysis({
            containerId: uniqueId,
            userPrompt,
            contextData
        });
        
        qnaContent.scrollTop = qnaContent.scrollHeight;
    }
}
```

---

### **5️⃣ 최근 10회차 필터 로직 (모든 파일)**

#### 5-1) HTML 리스트에 클래스 추가:

현재 리스트 구조를 찾아서, 각 행에 `data-round` 속성과 클릭 이벤트 추가:

```html
<!-- 기존: -->
<tr>
    <td>...</td>
</tr>

<!-- 변경: -->
<tr data-round="1000" onclick="highlightRecent10Rows(1000)" 
    class="cursor-pointer hover:bg-gray-50 transition-colors">
    <td>...</td>
</tr>
```

#### 5-2) JavaScript에 함수 추가:

```javascript
function highlightRecent10Rows(round) {
    // 기존 하이라이트 제거
    document.querySelectorAll('tr[data-round]').forEach(row => {
        row.style.backgroundColor = '';
    });
    
    // 최근 10회차 하이라이트 (옅은 주황색)
    const recent10Rounds = allDrawData.slice(0, 10).map(d => d.round);
    document.querySelectorAll('tr[data-round]').forEach(row => {
        const rowRound = parseInt(row.getAttribute('data-round'));
        if (recent10Rounds.includes(rowRound)) {
            row.style.backgroundColor = '#FFF3E0'; // 옅은 주황색
        }
    });
    
    // 선택된 행 강조 (더 진한 주황색)
    const selectedRow = document.querySelector(`tr[data-round="${round}"]`);
    if (selectedRow) {
        selectedRow.style.backgroundColor = '#FFE0B2'; // 진한 주황색
    }
}

// 페이지 로드 시 자동 적용
function applyRecent10Highlight() {
    const recent10Rounds = allDrawData.slice(0, 10).map(d => d.round);
    document.querySelectorAll('tr[data-round]').forEach(row => {
        const rowRound = parseInt(row.getAttribute('data-round'));
        if (recent10Rounds.includes(rowRound)) {
            row.style.backgroundColor = '#FFF3E0'; // 옅은 주황색
        }
    });
}
```

#### 5-3) 페이지 로드 후 호출:

데이터 로드 완료 후 (예: `initPage()` 또는 `loadData()` 함수 끝에):
```javascript
applyRecent10Highlight();
```

---

### **6️⃣ refreshAIAnalysis 함수 (모든 파일)**

기존 함수가 있다면 다음과 같이 수정:

```javascript
async function refreshAIAnalysis() {
    const subjectData = allDrawData[0] || { round: 0 };
    const subjectRound = subjectData.round;
    const targetRound = subjectRound + 1;
    
    // 최근 10회 데이터
    const recentData = allDrawData.slice(0, 10);
    const contextData = `최근 10회차: ${recentData.map(d => `[${d.round}회]`).join(', ')}`;
    
    if (window.AIAnalysis) {
        await window.AIAnalysis.executeAnalysis({
            containerId: 'aiAnalysisContent',
            analysisType: '[파일 특화 분석명]',  // 예: '제곱수', '끝수'
            subjectRound,
            targetRound,
            customData: contextData,
            customRules: `추세/패턴/추천을 분석하시오.`
        });
    }
}
```

---

### **7️⃣ 샘플 버튼 질문 예시 (파일별)**

#### square_number.html (제곱수):
1. ✨ 다음 회차 제곱수 예상
2. 📊 최근 10회 제곱수 추세
3. 🔥 제곱수 집중 구간
4. 🧊 제곱수 미출현
5. ⚖️ 평균 회귀
6. 📈 상승세 제곱수
7. 📉 하락세 제곱수
8. 🔄 이월수 제곱수
9. 🎯 필터값 추천
10. 🚫 멸 구간

#### stats_by_number.html (번호별 통계):
1. ✨ 다음 회차 추천 번호
2. 📊 번호별 최근 추세
3. 🔥 과열 번호
4. 🧊 부활 가능 번호
5. ⚖️ 평균 회귀 번호
6. 📈 상승세 번호
7. 📉 하락세 번호
8. 🔄 이월수 분석
9. 🎯 최적 번호
10. 🚫 제외 번호

#### tail_digit.html (끝수):
1. ✨ 다음 회차 끝수 예상
2. 📊 최근 10회 끝수 패턴
3. 🔥 과열 끝수
4. 🧊 미출현 끝수
5. ⚖️ 평균 회귀 끝수
6. 📈 상승세 끝수
7. 📉 하락세 끝수
8. 🔄 이월수 끝수
9. 🎯 최적 끝수
10. 🚫 제외 끝수

#### tail_sum.html (끝수 합):
1. ✨ 다음 회차 끝수 합 예상
2. 📊 끝수 합 패턴 분석
3. 🔥 과열 합계 범위
4. 🧊 미출현 합계
5. ⚖️ 평균 회귀 합계
6. 📈 상승세 합계
7. 📉 하락세 합계
8. 🔄 이월수 합계
9. 🎯 최적 합계 범위
10. 🚫 제외 합계

#### total_sum.html (전체 합):
1. ✨ 다음 회차 전체 합 예상
2. 📊 전체 합 추세
3. 🔥 과열 합계 구간
4. 🧊 미출현 합계
5. ⚖️ 평균 회귀

#### triangular_number.html (삼각수):
1. ✨ 다음 회차 삼각수 예상
2. 📊 최근 10회 삼각수 추세
3. 🔥 삼각수 집중 구간
4. 🧊 삼각수 미출현
5. ⚖️ 평균 회귀
6. 📈 상승세 삼각수
7. 📉 하락세 삼각수
8. 🔄 이월수 삼각수
9. 🎯 필터값 추천
10. 🚫 멸 구간

#### twin_number.html (쌍수):
1. ✨ 다음 회차 쌍수 예상
2. 📊 최근 10회 쌍수 패턴
3. 🔥 쌍수 과열
4. 🧊 쌍수 부활 가능
5. ⚖️ 평균 회귀
6. 📈 상승세 쌍수
7. 📉 하락세 쌍수
8. 🔄 이월수 쌍수
9. 🎯 최적 쌍수
10. 🚫 제외 쌍수

---

## 📋 **수정 순서**

1. **각 파일별로:**
   - Step 1: AI 챗봇 모달 HTML 추가 (`</body>` 전)
   - Step 2: executeLocalAIAnalysis 함수 추가 (아직 없는 파일만)
   - Step 3: AI Insight 섹션 헤더 프롬프트 라이브러리 버튼 수정
   - Step 4: 샘플 버튼 10개 질문 맞게 수정
   - Step 5: submitCustomAIAnalysis 함수 추가/수정
   - Step 6: 리스트 HTML에 data-round 속성 추가
   - Step 7: 하이라이트 함수 추가
   - Step 8: refreshAIAnalysis 함수 확인 및 수정

2. **테스트:**
   - AI 버튼 클릭 → 모달 열림
   - 샘플 버튼 클릭 → 질문 입력 & AI 분석
   - 리스트 클릭 → 옅은 주황색 하이라이트
   - 최근 10회차 자동 주황색 처리

---

## 🎯 **핵심 포인트**

✅ **모든 파일에 동일한 구조 적용**
✅ **AI 챗봇 모달은 재사용 가능**
✅ **executeLocalAIAnalysis는 표준화된 구현**
✅ **프롬프트 라이브러리는 파일명만 변경**
✅ **샘플 버튼은 파일 특화 질문 적용**
✅ **하이라이트는 모든 리스트에 적용**

이 프롬프트를 따라 각 파일을 수정하면 모두 동일한 UX/UI 표준을 가질 수 있습니다! 🚀

