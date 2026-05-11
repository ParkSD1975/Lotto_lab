# Lotto Lab Self-Discovery NLP Phase 3 — 회귀 검증 시나리오

## 개요
AutoNLPMatcher 페이지 통합 후 브라우저 manual test 가이드

**작성일**: 2026-05-08  
**Phase**: Phase 3 (fix-203)  
**관련 파일**: `js/layout.js`, `js/AutoNLPMatcher.js`, `js/auto_nlp_loader.js`

---

## 테스트 환경 설정

### 1. 로컬 서버 실행
```bash
cd C:/Users/psdet/Documents/lottoanalysis
python -m http.server 8000
# 또는 Live Server VSCode Extension 사용
```

### 2. 브라우저 콘솔 열기
- Chrome DevTools: `F12` → Console 탭
- Network 탭도 함께 열어둘 것 (AI 호출 횟수 확인용)

### 3. 페이지 선택
아래 23개 페이지 중 아무 페이지나 사용 가능 (모두 AutoNLP 통합):
- `custom_analysis.html`
- `missing.html`
- `lotto_paper.html`
- `hot_cold.html`
- `tail_digit.html`
- `prime_number.html`
- `composite_number.html`
- `number_range.html`
- `neighbor_number.html`
- `ac_value.html`
- `magic_square.html`
- `tail_sum.html`
- `total_sum.html`
- `multiple.html`
- `twin_number.html`
- `triangular_number.html`
- `stats_by_number.html`
- `square_number.html`
- `regression.html`
- `odd_even.html`
- `low_high.html`
- `consecutive_number.html`
- `carryover.html`

---

## 필수 테스트 케이스 (7가지)

### 케이스 1: 배수 합집합 (AutoNLP 즉시 처리)

**입력**:
- Title: `7과 8 합집합`
- Prompt: `7과 8의 배수 합집합`

**예상 결과**:
```javascript
// 콘솔 로그:
[AutoNLP] Loaded successfully: {...}
[analyzePrompt fix-203] AutoNLP intent: filter_combination conf: 0.95
[analyzePrompt fix-203] AutoNLP 직접 계산: {...}
```

**검증 항목**:
- [ ] Network 탭에서 `ai-lotto-analyst` Edge Function 호출 **0회**
- [ ] 미리보기 모달 즉시 표시 (< 50ms)
- [ ] target_numbers에 7의 배수 + 8의 배수 union 결과 표시
- [ ] description: "7배수, 8배수 합집합 (총 N개 번호)"

---

### 케이스 2: 배수 교집합 (AutoNLP 즉시 처리)

**입력**:
- Title: `칠팔교집합`
- Prompt: `칠배수 팔배수 교집합`

**예상 결과**:
```javascript
[analyzePrompt fix-203] AutoNLP intent: filter_combination conf: 0.90
[analyzePrompt fix-203] AutoNLP 직접 계산: {...}
```

**검증 항목**:
- [ ] Network 탭에서 `ai-lotto-analyst` 호출 **0회**
- [ ] 미리보기 모달 즉시 표시
- [ ] target_numbers: [7, 14, 21, 28, 35, 42] (7과 8의 공배수 = 56의 배수, 45 이하만)
  - 실제: [14, 28, 42] (56의 배수가 45 이하인 것)
- [ ] description: "칠배수, 팔배수 교집합 (총 3개 번호)"

---

### 케이스 3: 배수 3개 합집합 (AutoNLP 즉시 처리)

**입력**:
- Title: `3567배수`
- Prompt: `3배수 5배수 7배수 합집합`

**예상 결과**:
```javascript
[analyzePrompt fix-203] AutoNLP intent: filter_combination conf: 0.92
[analyzePrompt fix-203] AutoNLP 직접 계산: {...}
```

**검증 항목**:
- [ ] AI 호출 **0회**
- [ ] target_numbers: 3, 5, 6, 7, 9, 10, 12, 14, 15, ... (3/5/7 배수 union)

---

### 케이스 4: AC값 범위 (mixed_query → regex fallback 또는 AI)

**입력**:
- Title: `AC중간`
- Prompt: `AC값 7~10인 조합`

**예상 결과**:
```javascript
[analyzePrompt fix-203] AutoNLP intent: mixed_query conf: 0.65
// (신뢰도 < 0.8이므로 AutoNLP 우회 실패)
[analyzePrompt fix-106] regex fallback: null
// → AI 호출
```

**검증 항목**:
- [ ] Network 탭에서 `ai-lotto-analyst` 호출 **1회**
- [ ] AI 응답 type: `dynamic` (formula: ...) 또는 `static`
- [ ] 정상 미리보기 표시

---

### 케이스 5: 모델 추천 (model_query → AI 필수)

**입력**:
- Title: `XGB추천`
- Prompt: `XGBoost가 추천한 1등 번호`

**예상 결과**:
```javascript
[analyzePrompt fix-203] AutoNLP intent: model_query conf: 0.88
// (현재 model_query는 AI 우회 대상 아님)
// → 단계 3 regex fallback null
// → AI 호출
```

**검증 항목**:
- [ ] AI 호출 **1회**
- [ ] type: `ai_model_top` 또는 `ai_ensemble_fixed`
- [ ] rules.model: `xgboost`

---

### 케이스 6: 한글 변형 모델명 (model_query → AI)

**입력**:
- Title: `엑스지비`
- Prompt: `엑스지비 추천`

**예상 결과**:
```javascript
[analyzePrompt fix-203] AutoNLP intent: model_query conf: 0.75
// (신뢰도 < 0.8 → AI 호출)
```

**검증 항목**:
- [ ] AI 호출 **1회**
- [ ] AI가 "엑스지비" → "XGBoost" 매핑 처리
- [ ] 정상 응답

---

### 케이스 7: 알 수 없는 입력 (unknown → AI fallback)

**입력**:
- Title: `테스트`
- Prompt: `asdf qwer zxcv`

**예상 결과**:
```javascript
[analyzePrompt fix-203] AutoNLP intent: unknown conf: 0.0
// → regex fallback null
// → AI 호출 (에러 가능)
```

**검증 항목**:
- [ ] AI 호출 **1회**
- [ ] AI 응답 에러 또는 default static type
- [ ] alert 또는 에러 메시지 표시

---

## 추가 검증 항목

### AutoNLP 로드 확인
페이지 로드 직후 콘솔:
```javascript
[AutoNLP] Loaded successfully: {
  loadTime: "XXms",
  version: "1.0.0",
  filters: 77,
  models: 11,
  operations: 5,
  statistics: 3,
  time_windows: 3,
  total_aliases: XXXX
}
```

**확인**:
- [ ] loadTime < 50ms
- [ ] window.autoNLP.loaded === true
- [ ] vocabulary.json 캐시 localStorage 저장 확인

### 성능 측정
브라우저 콘솔에서:
```javascript
// AutoNLP 매칭 성능
console.time('match');
window.autoNLP.match('7배수 8배수 합집합');
console.timeEnd('match');
// → < 10ms 예상
```

### 역호환 확인
기존 정규식 패턴도 여전히 동작해야 함:
- "7배수 8배수 합집합" → AutoNLP 우선
- "7배수, 8배수 합집합" → AutoNLP 우선
- (AutoNLP 실패 시) → regex fallback 정상 동작

---

## 발견된 이슈 보고 양식

### 이슈 템플릿
```markdown
**케이스**: [케이스 번호]  
**브라우저**: [Chrome 131 / Firefox 125 / etc]  
**현상**: [실제 동작 설명]  
**예상**: [기대 동작]  
**콘솔 로그**: [에러 메시지 복사]  
**스크린샷**: [첨부 가능 시]  
```

---

## 다음 단계 (Phase 4)

Phase 3 검증 완료 후:
1. `customAnalysis.js` handleNLPResult AutoNLP 통합
2. `BasicAnalysisNLP.js` 점진적 마이그레이션
3. 사용 로그 수집 → alias 자동 확장
4. model_query intent AI 우회 가능 여부 검토 (backend /v4/model-top-k endpoint 연동)

---

## 참고 문서

- **Phase 1**: `docs/VOCABULARY_GENERATION_SUMMARY.md`
- **Phase 2**: `docs/AUTO_NLP_MATCHER_README.md`
- **Master Plan**: `docs/MASTER_PLAN.md` (Stage 1-4-D Self-Discovery NLP)
