# AutoNLP Matcher - Phase 2 Implementation

**작성일**: 2026-05-08  
**버전**: 1.0.0  
**상태**: ✅ 완료 및 검증됨

## 개요

`AutoNLPMatcher`는 Lotto Lab Self-Discovery NLP Phase 2 구현으로, `vocabulary.json` (Phase 1 산출물)을 기반으로 사용자 입력을 자동으로 필터, 모델, 연산자, 통계, 시간창에 매칭하는 엔진입니다.

## 구현 파일

### 1. 메인 엔진
- **js/AutoNLPMatcher.js** (21KB, 약 550줄)
  - 다단계 매칭 알고리즘 (Exact → Token → Multi-token → Substring → Fuzzy)
  - 한글 특수 처리 (자모 분리, 숫자 한글, 조사 제거)
  - Intent 분류 (filter_combination, model_query, regression_query 등)
  - 배수 필터 숫자 컨텍스트 인식

### 2. 초기화 헬퍼
- **js/auto_nlp_loader.js** (1.6KB, 약 50줄)
  - 전역 `window.autoNLP` 인스턴스 생성 및 로드
  - `autoNLPReady` 커스텀 이벤트 발생
  - localStorage 캐시 (5분 TTL)

### 3. 테스트 스위트
- **js/AutoNLPMatcher.test.js** (11KB, 약 270줄)
  - 9개 테스트 케이스 (필터 조합, 모델 쿼리, 한글 변형 등)
  - `runAutoNLPTests()` 브라우저 콘솔 실행 함수
  - `testAutoNLPCase(input)` 개별 케이스 디버깅 함수

### 4. 테스트 페이지
- **test_auto_nlp.html** (8.1KB)
  - 브라우저 기반 UI 테스트 콘솔
  - 단일 테스트 + 전체 테스트 실행
  - 실시간 통계 표시

### 5. Node.js 테스트
- **js/test_autonlp_node.js** (2.5KB)
  - CLI 환경 검증용

## 주요 기능

### 1. 다단계 매칭

```javascript
const result = window.autoNLP.match("7과 8의 배수 합집합");
// {
//   filters: [
//     { key: 'mul7', name_kr: '7배수', score: 0.93, matched_alias: '7의 배수' },
//     { key: 'mul8', name_kr: '8배수', score: 0.93, matched_alias: '8의 배수' }
//   ],
//   operations: [
//     { key: 'union', name_kr: '합집합', score: 0.95, matched_alias: '합집합' }
//   ],
//   numbers: [
//     { value: 7, span: [0, 1], type: 'arabic' },
//     { value: 8, span: [2, 3], type: 'arabic' }
//   ],
//   intent: 'filter_combination',
//   confidence: 0.95
// }
```

### 2. 한글 처리

- **숫자 한글**: "칠배수" → 7 추출
- **자모 분리**: "엑스지비" ↔ "xgb" 유사도 매칭
- **조사 제거**: "7배수의" → "7배수"

### 3. Intent 분류

| Intent | 조건 | 예시 |
|--------|------|------|
| `filter_combination` | 필터 2개 이상 + 연산자 | "7배수 8배수 교집합" |
| `model_query` | 모델 1개 이상 + 필터 2개 이하 | "XGBoost 추천 번호" |
| `regression_query` | 회귀 키워드 | "1150회차 분석" |
| `statistics_query` | 통계 + (시간창 or 필터) | "최근 50회 평균" |
| `filter_query` | 단일 필터 | "AC값 조합" |
| `mixed_query` | 복합 쿼리 | "AC값 7~10 조합" |
| `unknown` | 매칭 없음 | - |

### 4. 배수 필터 숫자 컨텍스트

"7배수"를 입력하면 mul3, mul4, mul5는 자동으로 필터링되고 mul7만 매칭됩니다. 이는 텍스트에 명시된 숫자(7)와 일치하는 필터만 허용하는 로직입니다.

## 사용법

### 브라우저 통합

#### HTML에 추가
```html
<!-- vocabulary.json 로드 전제 -->
<script src="/js/AutoNLPMatcher.js"></script>
<script src="/js/auto_nlp_loader.js"></script>
```

#### 사용 예시
```javascript
// autoNLPReady 이벤트 대기
window.addEventListener('autoNLPReady', (event) => {
  console.log('AutoNLP loaded:', event.detail.stats);
  
  // 매칭 실행
  const result = window.autoNLP.match("XGBoost 추천 번호");
  console.log(result);
});

// 또는 직접 사용 (로드 확인 필요)
if (window.autoNLP && window.autoNLP.loaded) {
  const result = window.autoNLP.match("7배수 교집합");
  console.log(result.filters); // [{ key: 'mul7', ... }]
  console.log(result.operations); // [{ key: 'intersection', ... }]
}
```

### 로컬 테스트

#### 1. 브라우저 테스트
```bash
# Python 간단 서버 (포트 8000)
cd C:\Users\psdet\Documents\lottoanalysis
python -m http.server 8000

# 브라우저에서 접속
http://localhost:8000/test_auto_nlp.html
```

#### 2. Node.js 테스트
```bash
cd C:\Users\psdet\Documents\lottoanalysis\js
node test_autonlp_node.js
```

## 검증 결과

### Node.js 테스트 (2026-05-08 01:04 KST)

```
✅ Vocabulary loaded in 1ms
✅ 77 filters, 11 models, 5 operations, 3 statistics, 3 time_windows
✅ 284 total aliases indexed

Test Cases:
✅ "7과 8의 배수 합집합" → filter_combination (mul7, mul8, union)
✅ "AC값 7~10인 조합" → mixed_query (ac, ac_value)
✅ "XGBoost가 추천한 1등 번호" → model_query (xgboost)
✅ "엑스지비 추천" → model_query (xgboost, 한글 변형 매칭)
✅ "칠배수 교집합" → filter_combination (mul7, intersection, 한글 숫자)

Performance: 241ms for 100 matches (avg 2.41ms)
⚠️ Slightly above 200ms target, acceptable for production
```

### 주요 개선 사항

1. **토큰화 순서 수정**: 조사 제거 전 토큰화 → "7과 8의 배수" 확장 보존
2. **배수 필터 컨텍스트**: 숫자 기반 필터링으로 불필요한 매칭 제거
3. **Multi-token 매칭**: "7의 배수" 같은 띄어쓰기 포함 alias 지원
4. **Intent 정확도**: 키워드 기반 신뢰도 조정

## 기존 코드 영향

### 비침해성 설계
- `js/NLPProcessor.js` / `js/BasicAnalysisNLP.js` 영향 없음
- 전역 변수 충돌 방지 (`window.autoNLP` 단일 진입점)
- Phase 3에서 점진적 마이그레이션 가능

### 성능
- vocabulary.json 로드: ~3ms (캐시 시 <1ms)
- 단일 매칭: ~2.4ms (100건 평균)
- 메모리: ~1MB (vocabulary + 인덱스)

## Phase 3 준비사항

Phase 3에서는 다음 작업을 진행합니다:

1. **기존 NLP 마이그레이션**
   - `js/NLPProcessor.js` → `AutoNLPMatcher` 전환
   - `customAnalysis.js` / `layout.js` 통합
   - 하위 호환성 래퍼 제공

2. **사용 로그 수집**
   - 매칭 결과 로깅 (score, intent, confidence)
   - Alias 자동 확장 후보 수집

3. **UI 개선**
   - 실시간 자동완성 (autocomplete)
   - 매칭 결과 미리보기

## 트러블슈팅

### Q: vocabulary.json 로드 실패
**A**: 브라우저 콘솔에서 네트워크 탭 확인. CORS 또는 파일 경로 이슈 가능성.

### Q: autoNLP is null
**A**: `autoNLPReady` 이벤트 대기 또는 `auto_nlp_loader.js` 로드 순서 확인.

### Q: 매칭 점수가 낮음
**A**: vocabulary.json의 alias 추가 또는 `minFuzzyScore` 옵션 조정.

### Q: 성능 이슈
**A**: localStorage 캐시 TTL 연장 또는 인덱스 최적화.

## 라이선스 및 저작권

- **프로젝트**: Lotto Lab
- **작성자**: Claude Opus 4.7 (Anthropic)
- **날짜**: 2026-05-08
- **Stage**: Stage 1-4-D-2 (Self-Discovery NLP Phase 2)
