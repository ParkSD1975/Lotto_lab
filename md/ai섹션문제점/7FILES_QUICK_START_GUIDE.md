# 🚀 7파일 공통 수정 최종 가이드

## 📋 **7개 파일 목록**

```
1. square_number.html (1218줄)
2. stats_by_number.html (1169줄)
3. tail_digit.html (1218줄)
4. tail_sum.html (1492줄)
5. total_sum.html (1359줄) ⚠️ 우선
6. triangular_number.html (1370줄) ⚠️ 우선
7. twin_number.html (1187줄)
```

---

## 🎯 **필요한 수정 사항 (공통)**

### **1️⃣ AI 챗봇 모달 추가** (모든 파일)
- 사이드바 모달 HTML 추가 (`</body>` 전)
- `openAIModal()`, `closeAIModal()` 함수 추가
- `submitModalFollowUp()` 함수 추가

### **2️⃣ executeLocalAIAnalysis 함수** (5개 파일 필요)
- square_number.html ❌
- stats_by_number.html ❌
- tail_digit.html ✅
- tail_sum.html ❌
- total_sum.html ❌
- triangular_number.html ✅
- twin_number.html ❌

### **3️⃣ submitCustomAIAnalysis 함수** (모든 파일)
- 모달 열기
- AI 분석 실행
- 대화 이력 관리

### **4️⃣ AI Insight 섹션 최적화** (모든 파일)
- 프롬프트 라이브러리 버튼 추가
- 샘플 버튼 질문 확인
- 입력 필드 + 전송 버튼

### **5️⃣ 리스트 하이라이트 로직** (모든 파일)
- `data-round` 속성 추가
- `highlightRecent10Rows()` 함수 추가
- `applyRecent10Highlight()` 함수 추가
- 색상: 옅은 주황색 (#FFF3E0)

### **6️⃣ 샘플 버튼 질문** (모든 파일)
- 파일별 특화 질문 10개 (표준화)
- total_sum.html: 5개 → **10개로 확대** 🔴
- triangular_number.html: 9개 → **10개로 확대** 🔴
- stats_by_number.html: 11개 → **10개로 축소** 🟡

### **7️⃣ refreshAIAnalysis 함수** (모든 파일)
- 기존 함수 확인
- 컨텍스트 데이터 업데이트
- window.AIAnalysis 호출

---

## 📊 **파일별 수정 필요도**

```
🔴 우선 (높음):
- total_sum.html (샘플 버튼 5개 → 10개)
- triangular_number.html (샘플 버튼 9개 → 10개)

🟡 필요 (중간):
- square_number.html (executeLocalAIAnalysis 없음)
- stats_by_number.html (샘플 버튼 11개 → 10개)
- tail_sum.html (executeLocalAIAnalysis 없음)
- twin_number.html (executeLocalAIAnalysis 없음)

🟢 보조 (낮음):
- tail_digit.html (이미 대부분 있음)
```

---

## 📥 **제공된 자료**

### **1️⃣ MASTER_PROMPT_7FILES_STANDARDIZATION.md** ⭐ (최중요)
```
완전한 코드 & 구현 가이드
- AI 모달 HTML 코드
- executeLocalAIAnalysis 함수 (복사 & 붙여넣기)
- submitCustomAIAnalysis 함수
- 하이라이트 함수들
- AI Insight HTML 템플릿
- 파일별 샘플 버튼 질문

→ 이 파일의 코드를 직접 복사해서 사용하면 됩니다!
```

### **2️⃣ 7FILES_MODIFICATION_CHECKLIST.md**
```
파일별 체크리스트
- 현재 상태 분석
- 파일별 수정 항목
- 공통 수정 항목
- 우선순위
- 검증 방법

→ 수정을 진행하면서 체크하세요!
```

---

## 🚀 **빠른 시작 (5분 안에)**

### **Step 1: 마스터 프롬프트 읽기 (1분)**
- MASTER_PROMPT_7FILES_STANDARDIZATION.md 검토

### **Step 2: 첫 파일 수정 (2분)**
- 예: total_sum.html (우선순위 🔴)
- AI 모달 HTML 복사
- executeLocalAIAnalysis 함수 복사
- submitCustomAIAnalysis 함수 수정
- 샘플 버튼 10개로 확대

### **Step 3: 나머지 파일 동일하게 적용 (2분 × 6개)**
- 같은 방식으로 반복
- 파일명만 변경

### **Step 4: 테스트**
- 각 파일 AI 기능 확인
- 리스트 하이라이트 확인

---

## 💡 **핵심 포인트**

### **✅ 모든 파일에 동일한 구조**
- AI 모달 (동일)
- executeLocalAIAnalysis (동일, 파일명만 변경)
- submitCustomAIAnalysis (동일)
- 하이라이트 로직 (동일)

### **✅ 파일별로만 다른 것**
- 샘플 버튼 질문 (파일 특화)
- 프롬프트 라이브러리 버튼의 파일명

### **✅ 복사 & 붙여넣기 가능**
- 코드를 그대로 복사
- 파일명만 변경
- 샘플 버튼 질문만 조정

---

## 📌 **수정 시 주의사항**

⚠️ **DO:**
```
✅ 마스터 프롬프트의 코드를 정확히 복사
✅ 파일명을 맞게 변경 (openPromptLibraryModal 부분)
✅ 샘플 버튼 질문을 파일에 맞게 조정
✅ 각 파일마다 테스트
```

❌ **DON'T:**
```
❌ 코드를 수정하거나 변형하지 마세요
❌ 구조를 바꾸지 마세요
❌ 샘플 버튼을 임의로 추가/삭제하지 마세요
```

---

## 🎯 **최종 체크리스트**

완성 후 각 파일마다:
```
□ AI 모달 열림 (버튼 클릭)
□ 샘플 버튼 클릭 → AI 분석 실행
□ Enter 키 → 분석 실행
□ 리스트 클릭 → 옅은 주황색 하이라이트
□ 페이지 로드 → 최근 10회차 자동 주황색
□ 콘솔 에러 없음
```

---

## 📞 **질문이 있으신가요?**

1. **마스터 프롬프트 참고**: MASTER_PROMPT_7FILES_STANDARDIZATION.md
2. **체크리스트 확인**: 7FILES_MODIFICATION_CHECKLIST.md
3. **모범 사례**: prime_number.html 또는 lotto_paper.html 참고

---

## ✨ **완성되면**

7개 파일이 모두:
- ✅ 동일한 UI/UX 표준
- ✅ 동일한 AI 챗봇 기능
- ✅ 동일한 하이라이트 로직
- ✅ 동일한 코드 구조

**→ 유지보수가 쉽고, 사용자 경험이 일관된 완벽한 웹앱!** 🎉

