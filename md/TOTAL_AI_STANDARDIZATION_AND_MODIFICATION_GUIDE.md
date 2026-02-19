# 🏆 로또 분석 AI 섹션 표준화 및 수정 내역 통합 마스터 가이드

이 문서는 7개 주요 분석 파일의 AI 섹션 표준화 지침과 `regression.html`의 핵심 기능 개선 사항을 하나로 통합한 최종 가이드입니다.

---

## 📋 1. 7개 파일 수정 필요 항목 체크리스트

### **📊 현재 상태 분석**
| 파일명 | 상태 | AI Insight | executeLocal | 샘플버튼 | 비고 |
|--------|------|-----------|-------------|----------|------|
| square_number | 🟡 | ✅ | ❌ 필요 | 10개 | - |
| stats_by_number | 🟡 | ✅ | ❌ 필요 | 11개 | 10개로 조정 필요 |
| tail_digit | 🟢 | ✅ | ✅ | 10개 | 양호 |
| tail_sum | 🟡 | ✅ | ❌ 필요 | 10개 | - |
| total_sum | 🔴 | ✅ | ❌ 필요 | 5개 | 10개로 확대 필요 |
| triangular_number | 🟡 | ✅ | ✅ | 9개 | 10개로 확대 필요 |
| twin_number | 🟡 | ✅ | ❌ 필요 | 10개 | - |

### **🎯 공통 필수 수정 항목**
1. **AI 챗봇 모달**: 모든 파일에 `aiModal` HTML 및 관련 JS 함수 추가
2. **함수 표준화**: `executeLocalAIAnalysis`, `submitCustomAIAnalysis` 함수 구현
3. **샘플 버튼**: 파일별 특화 질문 10개로 표준화
4. **하이라이트**: 최근 10회차 자동 하이라이트(`data-round`, `applyRecent10Highlight`)

---

## 🚀 2. 빠른 시작 가이드 (Quick Start)

### **핵심 수정 단계**
1. **마스터 프롬프트 코드 복사**: 아래 3절의 표준 코드를 활용합니다.
2. **HTML/JS 적용**: 모든 파일의 `</body>` 직전과 `<script>` 내부에 코드를 삽입합니다.
3. **파일명 치환**: `openPromptLibraryModal` 호출 시 각 파일에 맞는 이름을 넣습니다.
4. **테스트**: AI 버튼 클릭, 샘플 질문 실행, 리스트 하이라이트 여부를 확인합니다.

---

## 🎯 3. 공통 수정 마스터 프롬프트 (코드 템플릿)

### **3-1. AI 챗봇 모달 (HTML)**
```html
<div id="aiModal" class="fixed inset-0 z-50 flex items-end md:items-center hidden">
    <div id="aiModalBg" class="absolute inset-0 bg-black/50" onclick="closeAIModal()"></div>
    <div class="relative bg-white rounded-t-xl md:rounded-xl md:max-w-2xl md:mx-auto w-full md:w-full h-[80vh] md:h-[80vh] flex flex-col shadow-2xl">
        <div class="flex items-center justify-between p-4 border-b border-gray-100">
            <h2 class="text-lg font-bold text-gray-900">AI 분석 챗봇</h2>
            <button onclick="closeAIModal()" class="p-2 hover:bg-gray-100 rounded-lg transition-colors">
                <span class="material-symbols-outlined">close</span>
            </button>
        </div>
        <div id="aiQnaContent" class="flex-1 p-5 overflow-y-auto custom-scrollbar flex flex-col gap-4"></div>
        <div class="p-4 border-t border-gray-100 flex-shrink-0">
            <div class="relative flex gap-2">
                <input type="text" id="aiModalInput" class="flex-1 px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl text-sm" placeholder="추가 질문..." onkeyup="if(event.key === 'Enter') submitModalFollowUp()">
                <button onclick="submitModalFollowUp()" class="px-4 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700">
                    <span class="material-symbols-outlined">send</span>
                </button>
            </div>
        </div>
    </div>
</div>
```

### **3-2. 핵심 분석 로직 (JavaScript)**
```javascript
async function executeLocalAIAnalysis(params) {
    const { containerId, userPrompt, contextData } = params;
    // ... Supabase analyze-lotto 호출 및 결과 렌더링 로직 ...
}

async function submitCustomAIAnalysis() {
    const userPrompt = document.getElementById('aiUserPrompt').value.trim();
    if (!userPrompt) return;
    openAIModal(userPrompt);
    // ... 컨텍스트 준비 및 executeLocalAIAnalysis 호출 ...
}
```

---

## 🛠️ 4. regression.html 전용 고도화 및 기술 수정 내역

`regression.html`의 안정성과 분석 품질을 높이기 위해 적용된 핵심 기술적 변경 사항입니다.

### **4-1. AI Insight 기능 복구 및 엔진 최적화**
- **로직 복구**: 구문 오류를 해결하고 `prime_number.html`의 검증된 로직을 이식하여 `refreshAIAnalysis` 기능을 정상화했습니다.
- **3섹션 리포트**: AI 분석 결과가 **'흐름 진단', '패턴 분석', '필승 공략'**의 3단계로 명확히 구분되어 출력되도록 개선했습니다.
- **자동 데이터 연동**: 회귀 주기, 평균 적중률, 미출현(Gap) 상태 등의 실시간 통계가 AI 프롬프트에 자동 포함되어 분석의 신뢰도를 높였습니다.

### **4-2. 데이터 시각화 및 UI 레이아웃 정규화**
- **정밀 레이아웃 조정**: 필터 범위 선택창과 버튼의 너비를 **`w-48`**로 통일하고, 일괄 적용 버튼 간격을 대폭 확대(**`gap-8`**), **필터 적용 토글 우측 하단 배치**, **AI Insight 테두리 완전 제거**, **AI 섹션 배경 화이트 통합** 등을 통해 조작 편의성과 시각적 완성도를 극대화했습니다.
- **STR (연속 적중) 지표**: 0회 적중 시 **빨간색 원형 '미'** 배지를, 1회 이상 적중 시 **녹색 숫자**를 표시하여 연속 당첨 흐름을 한눈에 파악할 수 있게 했습니다.
- **GAP (미출현) 지표**: 0회(당첨 회차)일 경우 **파란색 '당'** 배지를 표시하여 시각적 직관성을 강화했습니다.
- **번호 색상화**: 당첨 번호는 로또 고유 색상을, 미당첨 번호는 무채색(`miss`)으로 처리하여 당첨 여부가 즉각 대비되도록 구현했습니다.

---
*본 가이드를 준수하여 모든 분석 페이지의 AI 인터페이스를 상향 평준화하시기 바랍니다.*
