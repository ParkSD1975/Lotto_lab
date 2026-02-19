# 📋 7파일 수정 필요 항목 체크리스트

## 📊 **현재 상태 분석**

| 파일명 | 크기 | AI Insight | executeLocal | 샘플버튼 | 상태 |
|--------|------|-----------|-------------|----------|------|
| square_number | 1218줄 | ✅ | ❌ 필요 | 10개 | 🟡 부분 |
| stats_by_number | 1169줄 | ✅ | ❌ 필요 | 11개 | 🟡 부분 |
| tail_digit | 1218줄 | ✅ | ✅ | 10개 | 🟢 양호 |
| tail_sum | 1492줄 | ✅ | ❌ 필요 | 10개 | 🟡 부분 |
| total_sum | 1359줄 | ✅ | ❌ 필요 | 5개 | 🔴 부족 |
| triangular_number | 1370줄 | ✅ | ✅ | 9개 | 🟡 부분 |
| twin_number | 1187줄 | ✅ | ❌ 필요 | 10개 | 🟡 부분 |

---

## ✅ **파일별 수정 체크리스트**

### **square_number.html**
- [ ] AI 챗봇 모달 HTML 추가
- [ ] executeLocalAIAnalysis 함수 추가
- [ ] submitCustomAIAnalysis 함수 추가/수정
- [ ] 프롬프트 라이브러리 버튼 추가
- [ ] 샘플 버튼 10개 질문 확인
- [ ] 리스트 data-round 속성 추가
- [ ] 하이라이트 함수 추가
- [ ] refreshAIAnalysis 확인

### **stats_by_number.html**
- [ ] AI 챗봇 모달 HTML 추가
- [ ] executeLocalAIAnalysis 함수 추가
- [ ] submitCustomAIAnalysis 함수 추가/수정
- [ ] 프롬프트 라이브러리 버튼 추가
- [ ] 샘플 버튼 10개로 수정 (현재 11개)
- [ ] 리스트 data-round 속성 추가
- [ ] 하이라이트 함수 추가
- [ ] refreshAIAnalysis 확인

### **tail_digit.html**
- [ ] AI 챗봇 모달 HTML 추가
- [ ] submitCustomAIAnalysis 함수 추가/수정
- [ ] 프롬프트 라이브러리 버튼 추가
- [ ] 샘플 버튼 10개 질문 확인
- [ ] 리스트 data-round 속성 추가
- [ ] 하이라이트 함수 추가
- [ ] refreshAIAnalysis 확인
- [ ] executeLocalAIAnalysis 확인

### **tail_sum.html**
- [ ] AI 챗봇 모달 HTML 추가
- [ ] executeLocalAIAnalysis 함수 추가
- [ ] submitCustomAIAnalysis 함수 추가/수정
- [ ] 프롬프트 라이브러리 버튼 추가
- [ ] 샘플 버튼 10개 질문 확인
- [ ] 리스트 data-round 속성 추가
- [ ] 하이라이트 함수 추가
- [ ] refreshAIAnalysis 확인

### **total_sum.html** ⚠️
- [ ] AI 챗봇 모달 HTML 추가
- [ ] executeLocalAIAnalysis 함수 추가
- [ ] submitCustomAIAnalysis 함수 추가/수정
- [ ] 프롬프트 라이브러리 버튼 추가
- [ ] **샘플 버튼 5개 → 10개로 확대** (🔴 우선)
- [ ] 리스트 data-round 속성 추가
- [ ] 하이라이트 함수 추가
- [ ] refreshAIAnalysis 확인

### **triangular_number.html**
- [ ] AI 챗봇 모달 HTML 추가
- [ ] submitCustomAIAnalysis 함수 추가/수정
- [ ] 프롬프트 라이브러리 버튼 추가
- [ ] **샘플 버튼 9개 → 10개로 확대**
- [ ] 리스트 data-round 속성 추가
- [ ] 하이라이트 함수 추가
- [ ] refreshAIAnalysis 확인
- [ ] executeLocalAIAnalysis 확인

### **twin_number.html**
- [ ] AI 챗봇 모달 HTML 추가
- [ ] executeLocalAIAnalysis 함수 추가
- [ ] submitCustomAIAnalysis 함수 추가/수정
- [ ] 프롬프트 라이브러리 버튼 추가
- [ ] 샘플 버튼 10개 질문 확인
- [ ] 리스트 data-round 속성 추가
- [ ] 하이라이트 함수 추가
- [ ] refreshAIAnalysis 확인

---

## 🎯 **공통 수정 항목 (모든 파일)**

### **필수 추가:**
1. ✅ AI 챗봇 모달 (openAIModal, closeAIModal, submitModalFollowUp)
2. ✅ executeLocalAIAnalysis 함수 (아직 없는 파일)
3. ✅ submitCustomAIAnalysis 함수 (모든 파일)
4. ✅ 프롬프트 라이브러리 버튼 (onclick에 파일명 맞게)
5. ✅ 샘플 버튼 질문 (파일별 특화 질문)
6. ✅ 하이라이트 함수 (applyRecent10Highlight, highlightRecent10Rows)
7. ✅ 리스트 HTML (data-round, onclick 추가)
8. ✅ refreshAIAnalysis 확인 (이미 있으면 유지)

### **UI 표준:**
- 모달: 화면 하단 80vh (모바일), 중앙 (데스크톱)
- 색상: 옅은 주황색 #FFF3E0, 진한 주황색 #FFE0B2
- 버튼: 10개 표준화
- 로딩: 회전 애니메이션 + 텍스트
- 입력: Enter 키 지원

---

## 📈 **수정 우선순위**

### **🔴 우선 (중요)**
1. total_sum.html (샘플 버튼 5개 → 10개)
2. triangular_number.html (샘플 버튼 9개 → 10개)
3. stats_by_number.html (샘플 버튼 11개 → 10개)

### **🟡 보통 (필요)**
4. square_number.html (executeLocalAIAnalysis 없음)
5. tail_sum.html (executeLocalAIAnalysis 없음)
6. twin_number.html (executeLocalAIAnalysis 없음)

### **🟢 보조 (확인만)**
7. tail_digit.html (이미 대부분 있음)
8. triangular_number.html (이미 대부분 있음)

---

## 📝 **수정 방법**

### **방법 1: 마스터 프롬프트 사용 (추천)**
```
MASTER_PROMPT_7FILES_STANDARDIZATION.md 파일을 참고하여
각 파일별로 같은 구조로 수정하세요.
```

### **방법 2: 복사 & 붙여넣기**
```
1. prime_number.html (또는 lotto_paper.html) 참고
2. AI 섹션 코드 복사
3. 각 파일에 맞게 조정
4. 파일명만 변경
```

### **방법 3: 단계적 수정**
```
1. 모든 파일에 AI 모달 추가
2. 모든 파일에 executeLocalAIAnalysis 추가
3. 모든 파일에 submitCustomAIAnalysis 추가
4. 각 파일별 샘플 버튼 질문 수정
5. 모든 파일에 하이라이트 함수 추가
6. 테스트
```

---

## ✅ **완성 후 검증**

각 파일마다:
- [ ] 프롬프트 라이브러리 버튼 클릭 → 모달 열림
- [ ] 샘플 버튼 클릭 → 질문 입력 & AI 분석
- [ ] Enter 키 → AI 분석 실행
- [ ] 리스트 클릭 → 주황색 하이라이트
- [ ] 페이지 로드 → 최근 10회차 자동 주황색
- [ ] 콘솔 에러 없음

---

## 📥 **제공 파일**

1. **MASTER_PROMPT_7FILES_STANDARDIZATION.md** - 완전한 수정 가이드
2. **이 파일** - 체크리스트 & 우선순위

---

**이 프롬프트를 따르면 7개 파일 모두 동일한 표준을 유지할 수 있습니다!** ✅

