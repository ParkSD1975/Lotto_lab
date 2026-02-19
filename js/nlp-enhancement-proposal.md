# 🎯 자연어 명령 처리 고도화 방안

## 현재 시스템 분석

### 기존 아키텍처
```
사용자 입력 → [자연어 파싱] → analysis 객체 생성 → DB 저장 → UI 렌더링
                    ↓
              type: static|dynamic|manual|group
              rules: { formula, value, expression, filters }
              target_numbers: []
              config: { groups, combineLogic }
```

### 현재 지원 분석 유형
| 유형 | 설명 | 예시 명령 |
|------|------|-----------|
| `static` | 고정 번호 분석 | "3, 7, 15, 22 번호 분석해줘" |
| `dynamic` | 수식 기반 동적 | "전회차 +1 패턴 분석" |
| `manual/direct` | 직접 입력 | "매주 내가 번호 직접 선택" |
| `group` | 그룹 조건 | "고온수+저온수 조합" |

### 현재 한계점
1. **키워드 기반 파싱** - 정확한 키워드가 없으면 인식 실패
2. **문맥 이해 부족** - 암시적 조건 파악 불가
3. **오류 복구 없음** - 파싱 실패 시 사용자 가이드 부재
4. **한국어 특수 표현 미지원** - 끝수, 대소, AC값 등

---

## 🚀 고도화 방안 1: 의도 분류 강화 (Intent Classification)

### 1.1 멀티레이어 의도 분류기

```javascript
// js/nlp/IntentClassifier.js
class IntentClassifier {
    constructor() {
        this.intentPatterns = new Map();
        this.confidenceThreshold = 0.7;
        this.initializePatterns();
    }

    initializePatterns() {
        // 1차: 핵심 의도 패턴 (높은 우선순위)
        this.intentPatterns.set('dynamic_formula', {
            patterns: [
                /(?:전|직전|이전|지난)\s*(?:회차|회|번)?\s*(?:번호|당첨번호)?\s*[+\-]\s*(\d+)/i,
                /(\d+)\s*(?:더하|빼|플러스|마이너스)/i,
                /(?:연속|이월|캐리오버)/i,
                /(?:당첨일|추첨일)\s*(?:끝수|날짜)/i,
            ],
            extractor: this.extractDynamicParams,
            priority: 10
        });

        this.intentPatterns.set('static_numbers', {
            patterns: [
                /(\d{1,2}(?:\s*,\s*|\s+)\d{1,2}(?:\s*,\s*|\s+)*)+/,
                /(?:번호|숫자)\s*[:：]?\s*(\d+)/,
                /(\d{1,2})\s*번/g
            ],
            extractor: this.extractStaticNumbers,
            priority: 8
        });

        this.intentPatterns.set('group_condition', {
            patterns: [
                /(?:그룹|묶음|조합)\s*(?:분석|조건)/i,
                /(?:고온|저온|핫|콜드)\s*(?:번호|수)/i,
                /(\d+)(?:~|에서|부터)\s*(\d+)\s*(?:까지|범위)/i,
                /(?:홀수|짝수|홀짝)/i,
            ],
            extractor: this.extractGroupParams,
            priority: 9
        });

        this.intentPatterns.set('statistical', {
            patterns: [
                /(?:미출현|안\s*나온|출현\s*안\s*한)\s*(?:\d+)?\s*(?:회|번)/i,
                /(?:연속|스트레이트|스트릭)\s*(?:\d+)?\s*(?:회|번)/i,
                /(?:확률|통계|빈도)/i,
            ],
            extractor: this.extractStatisticalParams,
            priority: 7
        });

        // 2차: 보조 의도 (조건 추가)
        this.intentPatterns.set('filter_condition', {
            patterns: [
                /(?:최소|최대|min|max)\s*(\d+)\s*(?:개|번호)/i,
                /(\d+)\s*(?:~|에서)\s*(\d+)\s*(?:개|번호)/i,
                /(?:제외|빼고|없이)\s*(?:분석|보여)/i,
            ],
            extractor: this.extractFilterParams,
            priority: 5
        });
    }

    classify(input) {
        const normalizedInput = this.normalizeInput(input);
        const candidates = [];

        for (const [intentType, config] of this.intentPatterns) {
            for (const pattern of config.patterns) {
                const match = normalizedInput.match(pattern);
                if (match) {
                    const confidence = this.calculateConfidence(match, normalizedInput, config);
                    candidates.push({
                        intent: intentType,
                        match: match,
                        confidence: confidence,
                        priority: config.priority,
                        extractor: config.extractor
                    });
                }
            }
        }

        // 우선순위 + 신뢰도 기준 정렬
        candidates.sort((a, b) => {
            if (b.priority !== a.priority) return b.priority - a.priority;
            return b.confidence - a.confidence;
        });

        return candidates.length > 0 ? candidates[0] : { intent: 'unknown', confidence: 0 };
    }

    normalizeInput(input) {
        return input
            .replace(/\s+/g, ' ')
            .replace(/，/g, ',')
            .replace(/[""]/g, '"')
            .trim()
            .toLowerCase();
    }

    calculateConfidence(match, input, config) {
        // 매칭 범위 비율
        const coverageScore = match[0].length / input.length;
        // 패턴 특이성 (복잡한 패턴일수록 높은 점수)
        const specificityScore = (match.length - 1) * 0.1;
        // 기본 점수
        const baseScore = 0.5;
        
        return Math.min(1.0, baseScore + coverageScore * 0.3 + specificityScore);
    }

    // 동적 수식 파라미터 추출
    extractDynamicParams(match, input) {
        const params = { type: 'dynamic', rules: {} };
        
        // +N / -N 패턴
        const plusMinus = input.match(/[+\-]\s*(\d+)/);
        if (plusMinus) {
            params.rules.formula = plusMinus[0].includes('+') ? 'prev_plus_n' : 'prev_minus_n';
            params.rules.value = parseInt(plusMinus[1]);
        }
        
        // 이월/캐리오버
        if (/(?:이월|캐리오버|carryover)/i.test(input)) {
            params.rules.formula = 'carryover';
        }
        
        // 날짜 끝수
        if (/(?:당첨일|추첨일)\s*(?:끝수|날짜)/i.test(input)) {
            params.rules.formula = 'draw_date_end';
        }
        
        // 수식 표현 (x+5, n*2 등)
        const mathExpr = input.match(/(?:수식|계산)\s*[:：]?\s*([xn]\s*[+\-*/]\s*\d+)/i);
        if (mathExpr) {
            params.rules.formula = 'math_expression';
            params.rules.expression = mathExpr[1].replace(/\s/g, '').replace('x', 'n');
        }
        
        return params;
    }

    // 고정 번호 추출
    extractStaticNumbers(match, input) {
        const numbers = [];
        const numPattern = /\d{1,2}/g;
        let m;
        while ((m = numPattern.exec(input)) !== null) {
            const num = parseInt(m[0]);
            if (num >= 1 && num <= 45) numbers.push(num);
        }
        return {
            type: 'static',
            target_numbers: [...new Set(numbers)].sort((a, b) => a - b)
        };
    }

    // 그룹 조건 추출
    extractGroupParams(match, input) {
        const groups = [];
        
        // 범위 그룹 (예: "1~10", "11에서 20까지")
        const rangePattern = /(\d+)(?:~|에서|부터)\s*(\d+)/g;
        let rm;
        while ((rm = rangePattern.exec(input)) !== null) {
            const start = parseInt(rm[1]);
            const end = parseInt(rm[2]);
            groups.push({
                name: `${start}-${end} 범위`,
                numbers: Array.from({ length: end - start + 1 }, (_, i) => start + i).filter(n => n <= 45),
                condition: { min: 1, max: 6 }
            });
        }
        
        // 고온/저온
        if (/고온|핫|hot/i.test(input)) {
            groups.push({ name: '고온수', numbers: [], type: 'hot', condition: { min: 1, max: 3 } });
        }
        if (/저온|콜드|cold/i.test(input)) {
            groups.push({ name: '저온수', numbers: [], type: 'cold', condition: { min: 1, max: 3 } });
        }
        
        // 홀짝
        if (/홀수/i.test(input)) {
            groups.push({ name: '홀수', numbers: [1,3,5,7,9,11,13,15,17,19,21,23,25,27,29,31,33,35,37,39,41,43,45], condition: { min: 2, max: 4 } });
        }
        if (/짝수/i.test(input)) {
            groups.push({ name: '짝수', numbers: [2,4,6,8,10,12,14,16,18,20,22,24,26,28,30,32,34,36,38,40,42,44], condition: { min: 2, max: 4 } });
        }
        
        return {
            type: 'group',
            config: { groups, combineLogic: 'AND' }
        };
    }

    // 통계 조건 추출
    extractStatisticalParams(match, input) {
        const params = { type: 'statistical', rules: {} };
        
        // 미출현 N회 이상
        const gapMatch = input.match(/미출현\s*(\d+)\s*(?:회|번)/i);
        if (gapMatch) {
            params.rules.minGap = parseInt(gapMatch[1]);
        }
        
        return params;
    }

    // 필터 조건 추출
    extractFilterParams(match, input) {
        const filters = {};
        
        // 개수 조건
        const countMatch = input.match(/(\d+)\s*(?:~|에서)\s*(\d+)\s*(?:개|번호)/i);
        if (countMatch) {
            filters.min = parseInt(countMatch[1]);
            filters.max = parseInt(countMatch[2]);
        }
        
        // 제외 번호
        const excludeMatch = input.match(/(?:제외|빼고)\s*[:：]?\s*([\d,\s]+)/i);
        if (excludeMatch) {
            filters.exclude = excludeMatch[1].match(/\d+/g).map(Number);
        }
        
        return { filter_config: filters };
    }
}

export default IntentClassifier;
```

### 1.2 컨텍스트 인식 파서

```javascript
// js/nlp/ContextAwareParser.js
class ContextAwareParser {
    constructor(intentClassifier) {
        this.classifier = intentClassifier;
        this.conversationHistory = [];
        this.maxHistoryLength = 5;
    }

    parse(input) {
        // 1차: 의도 분류
        const classification = this.classifier.classify(input);
        
        // 신뢰도 낮으면 컨텍스트 참조
        if (classification.confidence < 0.5) {
            return this.parseWithContext(input, classification);
        }
        
        // 2차: 파라미터 추출
        const params = classification.extractor?.(classification.match, input) || {};
        
        // 3차: 컨텍스트 병합 (이전 분석 참조)
        const mergedParams = this.mergeWithContext(params);
        
        // 히스토리 업데이트
        this.updateHistory(input, mergedParams);
        
        return {
            success: true,
            intent: classification.intent,
            confidence: classification.confidence,
            params: mergedParams
        };
    }

    parseWithContext(input, classification) {
        // 대명사 해소 ("그거", "이전 거", "같은 방식으로")
        const pronounResolved = this.resolvePronoun(input);
        
        if (pronounResolved !== input) {
            return this.parse(pronounResolved);
        }
        
        // 이전 분석 수정 요청 감지
        if (this.isModificationRequest(input)) {
            const lastAnalysis = this.conversationHistory[this.conversationHistory.length - 1];
            if (lastAnalysis) {
                return this.createModification(lastAnalysis, input);
            }
        }
        
        return {
            success: false,
            intent: 'unknown',
            confidence: classification.confidence,
            suggestions: this.generateSuggestions(input)
        };
    }

    resolvePronoun(input) {
        const pronouns = {
            '그거': 'previousAnalysis',
            '이전거': 'previousAnalysis',
            '그것': 'previousAnalysis',
            '같은 방식': 'previousMethod',
            '동일하게': 'previousMethod'
        };
        
        for (const [pronoun, reference] of Object.entries(pronouns)) {
            if (input.includes(pronoun) && this.conversationHistory.length > 0) {
                const last = this.conversationHistory[this.conversationHistory.length - 1];
                if (reference === 'previousAnalysis') {
                    return input.replace(pronoun, last.description || '');
                }
            }
        }
        
        return input;
    }

    isModificationRequest(input) {
        return /(?:바꿔|변경|수정|추가|빼|제외|대신)/i.test(input);
    }

    createModification(lastAnalysis, input) {
        const modification = { ...lastAnalysis.params };
        
        // 번호 추가
        const addMatch = input.match(/(\d+)\s*(?:추가|더해|넣어)/i);
        if (addMatch && modification.target_numbers) {
            modification.target_numbers.push(parseInt(addMatch[1]));
        }
        
        // 번호 제거
        const removeMatch = input.match(/(\d+)\s*(?:빼|제외|삭제)/i);
        if (removeMatch && modification.target_numbers) {
            const toRemove = parseInt(removeMatch[1]);
            modification.target_numbers = modification.target_numbers.filter(n => n !== toRemove);
        }
        
        return {
            success: true,
            intent: 'modification',
            params: modification,
            basedOn: lastAnalysis
        };
    }

    mergeWithContext(params) {
        // 이전 분석에서 누락된 정보 보완
        if (this.conversationHistory.length > 0) {
            const last = this.conversationHistory[this.conversationHistory.length - 1];
            
            // 타입이 지정되지 않았으면 이전 타입 유지
            if (!params.type && last.params?.type) {
                params.type = params.type || last.params.type;
            }
        }
        
        return params;
    }

    generateSuggestions(input) {
        const suggestions = [];
        
        // 부분 매칭 기반 제안
        if (/번호|숫자|\d+/.test(input)) {
            suggestions.push({
                text: '특정 번호를 분석하고 싶으시면 "3, 7, 15, 22 번호 분석" 형태로 입력해주세요.',
                example: '3, 7, 15, 22, 35 번호 분석해줘'
            });
        }
        
        if (/전|이전|지난|회차/.test(input)) {
            suggestions.push({
                text: '이전 회차 기반 분석을 원하시면 수식을 명시해주세요.',
                example: '전회차 +1 패턴 분석',
                example2: '전회차 번호 그대로 (이월 분석)'
            });
        }
        
        if (/조합|그룹|묶음/.test(input)) {
            suggestions.push({
                text: '그룹 조건 분석은 범위와 조건을 명시해주세요.',
                example: '1~10 범위에서 2~3개, 21~30 범위에서 1~2개 조합'
            });
        }
        
        // 기본 제안
        if (suggestions.length === 0) {
            suggestions.push(
                { text: '번호 분석', example: '3, 7, 15, 22 번호 분석' },
                { text: '동적 수식', example: '전회차 +1 패턴' },
                { text: '그룹 조건', example: '고온수 + 저온수 조합' },
                { text: '통계 기반', example: '미출현 5회 이상 번호' }
            );
        }
        
        return suggestions;
    }

    updateHistory(input, params) {
        this.conversationHistory.push({
            input,
            params,
            timestamp: Date.now(),
            description: this.generateDescription(params)
        });
        
        if (this.conversationHistory.length > this.maxHistoryLength) {
            this.conversationHistory.shift();
        }
    }

    generateDescription(params) {
        if (params.type === 'static') {
            return `고정 번호 분석: ${params.target_numbers?.join(', ')}`;
        }
        if (params.type === 'dynamic') {
            return `동적 분석: ${params.rules?.formula}`;
        }
        return '분석';
    }
}

export default ContextAwareParser;
```

---

## 🚀 고도화 방안 2: 한국어 특화 처리

### 2.1 로또 도메인 어휘 사전

```javascript
// js/nlp/LottoDictionary.js
const LottoDictionary = {
    // 동의어 매핑
    synonyms: {
        // 분석 관련
        '분석': ['분석', '검토', '확인', '체크', '살펴', '알아'],
        '패턴': ['패턴', '규칙', '법칙', '추세', '트렌드', '흐름'],
        '번호': ['번호', '숫자', '넘버', '볼', '공'],
        
        // 수식 관련
        '더하기': ['더하기', '플러스', '+', '추가', '더해서', '증가'],
        '빼기': ['빼기', '마이너스', '-', '감소', '줄여서'],
        '이월': ['이월', '캐리오버', '유지', '그대로', '동일'],
        
        // 통계 관련
        '미출현': ['미출현', '안나온', '출현안한', '빠진', '없던'],
        '연속': ['연속', '스트레이트', '연달아', '이어서', '계속'],
        '출현': ['출현', '나온', '당첨된', '등장'],
        
        // 범위 관련
        '고온수': ['고온수', '핫넘버', '자주나온', '빈출'],
        '저온수': ['저온수', '콜드넘버', '안나온', '희귀'],
        '끝수': ['끝수', '일의자리', '마지막자리', '끝자리'],
        
        // 그룹 관련
        '홀수': ['홀수', '홀', '기수'],
        '짝수': ['짝수', '짝', '우수'],
        '소수': ['소수', '프라임'],
        '합성수': ['합성수', '비소수'],
    },

    // 복합 표현 패턴
    compoundPatterns: {
        'AC값': /AC\s*(?:값|지수)?|(?:인접|조합)\s*(?:차이|복잡도)/i,
        '고저비': /고저\s*(?:비|비율)|(?:높은|낮은)\s*번호\s*비율/i,
        '홀짝비': /홀짝\s*(?:비|비율)|홀수\s*짝수\s*비율/i,
        '총합범위': /(?:합계|총합|합)\s*(?:범위|조건)?/i,
        '연번': /(?:연속|인접)\s*(?:번호|숫자)|연번/i,
        '구간별': /(?:\d+)대|(?:구간|범위)별/i,
    },

    // 숫자 표현 변환
    koreanNumbers: {
        '하나': 1, '둘': 2, '셋': 3, '넷': 4, '다섯': 5,
        '여섯': 6, '일곱': 7, '여덟': 8, '아홉': 9, '열': 10,
        '한': 1, '두': 2, '세': 3, '네': 4,
        '일': 1, '이': 2, '삼': 3, '사': 4, '오': 5,
        '육': 6, '칠': 7, '팔': 8, '구': 9, '십': 10,
    },

    // 접미사/단위
    suffixes: {
        '개': 'count',
        '회': 'round',
        '번': 'times',
        '이상': 'min',
        '이하': 'max',
        '초과': 'above',
        '미만': 'below',
    }
};

// 정규화 함수
function normalizeKorean(input) {
    let normalized = input;
    
    // 1. 한국어 숫자를 아라비아 숫자로 변환
    for (const [korean, number] of Object.entries(LottoDictionary.koreanNumbers)) {
        normalized = normalized.replace(new RegExp(korean + '(?=\\s*개|\\s*회|\\s*번)', 'g'), number);
    }
    
    // 2. 동의어 정규화 (대표어로 변환)
    for (const [standard, synonymList] of Object.entries(LottoDictionary.synonyms)) {
        for (const synonym of synonymList) {
            if (synonym !== standard) {
                normalized = normalized.replace(new RegExp(synonym, 'gi'), standard);
            }
        }
    }
    
    // 3. 띄어쓰기 정규화
    normalized = normalized.replace(/\s+/g, ' ').trim();
    
    return normalized;
}

export { LottoDictionary, normalizeKorean };
```

### 2.2 의미론적 슬롯 채움 (Slot Filling)

```javascript
// js/nlp/SlotFiller.js
class SlotFiller {
    constructor() {
        this.slots = {
            'dynamic_formula': {
                formula: { required: true, type: 'enum', values: ['prev_plus_n', 'prev_minus_n', 'carryover', 'draw_date_end', 'math_expression'] },
                value: { required: false, type: 'number', default: 1 },
                expression: { required: false, type: 'string' }
            },
            'static_numbers': {
                target_numbers: { required: true, type: 'array', itemType: 'number', minItems: 1 }
            },
            'group_condition': {
                groups: { required: true, type: 'array', minItems: 1 },
                combineLogic: { required: false, type: 'enum', values: ['AND', 'OR'], default: 'AND' }
            },
            'filter': {
                min: { required: false, type: 'number' },
                max: { required: false, type: 'number' },
                exclude: { required: false, type: 'array', itemType: 'number' }
            }
        };
    }

    fill(intent, extractedData) {
        const slotDefinition = this.slots[intent];
        if (!slotDefinition) return extractedData;

        const result = { ...extractedData };
        const missingRequired = [];
        const warnings = [];

        for (const [slotName, config] of Object.entries(slotDefinition)) {
            const value = result[slotName];
            
            // 필수 슬롯 체크
            if (config.required && (value === undefined || value === null)) {
                missingRequired.push({
                    slot: slotName,
                    description: this.getSlotDescription(slotName)
                });
                continue;
            }

            // 기본값 적용
            if (value === undefined && config.default !== undefined) {
                result[slotName] = config.default;
            }

            // 타입 검증 및 변환
            if (value !== undefined) {
                const validated = this.validateAndConvert(value, config);
                if (validated.error) {
                    warnings.push({ slot: slotName, error: validated.error });
                } else {
                    result[slotName] = validated.value;
                }
            }
        }

        return {
            data: result,
            complete: missingRequired.length === 0,
            missingSlots: missingRequired,
            warnings
        };
    }

    validateAndConvert(value, config) {
        switch (config.type) {
            case 'number':
                const num = Number(value);
                if (isNaN(num)) return { error: '숫자가 아닙니다' };
                return { value: num };
                
            case 'array':
                if (!Array.isArray(value)) return { error: '배열 형식이 아닙니다' };
                if (config.minItems && value.length < config.minItems) {
                    return { error: `최소 ${config.minItems}개 항목이 필요합니다` };
                }
                return { value };
                
            case 'enum':
                if (!config.values.includes(value)) {
                    return { error: `허용된 값: ${config.values.join(', ')}` };
                }
                return { value };
                
            default:
                return { value };
        }
    }

    getSlotDescription(slotName) {
        const descriptions = {
            'formula': '분석 수식 (예: 전회차 +1, 이월)',
            'target_numbers': '분석할 번호 목록',
            'groups': '그룹 조건 설정',
            'min': '최소 개수',
            'max': '최대 개수'
        };
        return descriptions[slotName] || slotName;
    }

    // 대화형 슬롯 채움을 위한 질문 생성
    generateQuestion(missingSlot) {
        const questions = {
            'formula': '어떤 수식을 적용할까요? (예: +1, -1, 이월, 날짜 끝수)',
            'target_numbers': '분석할 번호를 입력해주세요. (예: 3, 7, 15, 22)',
            'groups': '어떤 그룹 조건을 설정할까요? (예: 1~10 범위에서 2개)',
            'min': '최소 몇 개 이상 나와야 하나요?',
            'max': '최대 몇 개까지 허용할까요?',
            'value': '몇을 더하거나 뺄까요?'
        };
        return questions[missingSlot.slot] || `${missingSlot.description}을(를) 입력해주세요.`;
    }
}

export default SlotFiller;
```

---

## 🚀 고도화 방안 3: 에러 복구 및 사용자 피드백

### 3.1 스마트 에러 핸들러

```javascript
// js/nlp/ErrorHandler.js
class NLPErrorHandler {
    constructor() {
        this.errorPatterns = new Map();
        this.initializePatterns();
    }

    initializePatterns() {
        // 흔한 오류 패턴과 수정 제안
        this.errorPatterns.set('out_of_range', {
            detector: (params) => {
                if (params.target_numbers) {
                    return params.target_numbers.some(n => n < 1 || n > 45);
                }
                return false;
            },
            message: '로또 번호는 1~45 사이여야 합니다.',
            fixer: (params) => {
                if (params.target_numbers) {
                    params.target_numbers = params.target_numbers
                        .filter(n => n >= 1 && n <= 45);
                }
                return params;
            }
        });

        this.errorPatterns.set('duplicate_numbers', {
            detector: (params) => {
                if (params.target_numbers) {
                    return new Set(params.target_numbers).size !== params.target_numbers.length;
                }
                return false;
            },
            message: '중복된 번호가 있습니다. 자동으로 제거됩니다.',
            fixer: (params) => {
                if (params.target_numbers) {
                    params.target_numbers = [...new Set(params.target_numbers)];
                }
                return params;
            }
        });

        this.errorPatterns.set('empty_group', {
            detector: (params) => {
                if (params.config?.groups) {
                    return params.config.groups.some(g => !g.numbers || g.numbers.length === 0);
                }
                return false;
            },
            message: '비어있는 그룹이 있습니다.',
            fixer: (params) => {
                if (params.config?.groups) {
                    params.config.groups = params.config.groups.filter(g => g.numbers?.length > 0);
                }
                return params;
            }
        });

        this.errorPatterns.set('invalid_range', {
            detector: (params) => {
                if (params.filter_config) {
                    const { min, max } = params.filter_config;
                    return min !== undefined && max !== undefined && min > max;
                }
                return false;
            },
            message: '최소값이 최대값보다 큽니다. 값을 교환합니다.',
            fixer: (params) => {
                if (params.filter_config) {
                    const { min, max } = params.filter_config;
                    params.filter_config.min = Math.min(min, max);
                    params.filter_config.max = Math.max(min, max);
                }
                return params;
            }
        });
    }

    validate(params) {
        const errors = [];
        const warnings = [];
        let fixedParams = { ...params };

        for (const [errorType, config] of this.errorPatterns) {
            if (config.detector(fixedParams)) {
                warnings.push({
                    type: errorType,
                    message: config.message
                });
                fixedParams = config.fixer(fixedParams);
            }
        }

        return {
            valid: errors.length === 0,
            params: fixedParams,
            errors,
            warnings,
            autoFixed: warnings.length > 0
        };
    }
}

export default NLPErrorHandler;
```

### 3.2 유사 명령 제안기

```javascript
// js/nlp/SuggestionEngine.js
class SuggestionEngine {
    constructor() {
        this.commandTemplates = [
            {
                pattern: /번호.*분석/,
                template: '{numbers} 번호 분석해줘',
                example: '3, 7, 15, 22, 35 번호 분석해줘',
                description: '특정 번호들의 출현 패턴 분석'
            },
            {
                pattern: /전회차|이전/,
                template: '전회차 {operator}{value} 패턴 분석',
                example: '전회차 +1 패턴 분석',
                description: '이전 당첨번호 기반 동적 분석'
            },
            {
                pattern: /이월|캐리/,
                template: '이월 번호 분석',
                example: '전회차 번호 이월 분석',
                description: '연속 출현 번호 분석'
            },
            {
                pattern: /끝수|날짜/,
                template: '당첨일 끝수 분석',
                example: '추첨일 끝수 기반 분석',
                description: '추첨일 날짜의 끝수에 해당하는 번호 분석'
            },
            {
                pattern: /미출현|안나온/,
                template: '미출현 {n}회 이상 번호 분석',
                example: '미출현 5회 이상 번호 분석',
                description: '연속 미출현 번호 분석'
            },
            {
                pattern: /고온|핫|자주/,
                template: '최근 {n}회 고온수 분석',
                example: '최근 10회 고온수 분석',
                description: '최근 자주 출현한 번호 분석'
            },
            {
                pattern: /저온|콜드|안나온/,
                template: '최근 {n}회 저온수 분석',
                example: '최근 20회 저온수 분석',
                description: '최근 출현하지 않은 번호 분석'
            },
            {
                pattern: /그룹|조합|범위/,
                template: '{range1} 범위에서 {min1}~{max1}개 + {range2} 범위에서 {min2}~{max2}개',
                example: '1~10 범위 2~3개, 21~30 범위 1~2개 조합',
                description: '다중 그룹 조건 분석'
            },
            {
                pattern: /홀짝|홀수|짝수/,
                template: '홀수 {min1}~{max1}개, 짝수 {min2}~{max2}개 조건',
                example: '홀수 3~4개, 짝수 2~3개 조건 분석',
                description: '홀짝 비율 조건 분석'
            },
            {
                pattern: /수식|계산|공식/,
                template: '수식: {expression} 적용 분석',
                example: '수식: n*2+1 적용 분석',
                description: '사용자 정의 수식 기반 분석'
            }
        ];
    }

    // 레벤슈타인 거리 계산
    levenshteinDistance(a, b) {
        const matrix = [];
        
        for (let i = 0; i <= b.length; i++) {
            matrix[i] = [i];
        }
        for (let j = 0; j <= a.length; j++) {
            matrix[0][j] = j;
        }
        
        for (let i = 1; i <= b.length; i++) {
            for (let j = 1; j <= a.length; j++) {
                if (b.charAt(i - 1) === a.charAt(j - 1)) {
                    matrix[i][j] = matrix[i - 1][j - 1];
                } else {
                    matrix[i][j] = Math.min(
                        matrix[i - 1][j - 1] + 1,
                        matrix[i][j - 1] + 1,
                        matrix[i - 1][j] + 1
                    );
                }
            }
        }
        
        return matrix[b.length][a.length];
    }

    // 유사도 계산
    calculateSimilarity(input, template) {
        const normalizedInput = input.toLowerCase().replace(/\s+/g, '');
        const normalizedTemplate = template.example.toLowerCase().replace(/\s+/g, '');
        
        const distance = this.levenshteinDistance(normalizedInput, normalizedTemplate);
        const maxLength = Math.max(normalizedInput.length, normalizedTemplate.length);
        
        return 1 - (distance / maxLength);
    }

    // 키워드 매칭 점수
    calculateKeywordScore(input, template) {
        const inputWords = input.toLowerCase().split(/\s+/);
        const exampleWords = template.example.toLowerCase().split(/\s+/);
        
        let matchCount = 0;
        for (const word of inputWords) {
            if (exampleWords.some(ew => ew.includes(word) || word.includes(ew))) {
                matchCount++;
            }
        }
        
        return matchCount / Math.max(inputWords.length, exampleWords.length);
    }

    suggest(input, limit = 3) {
        const suggestions = this.commandTemplates.map(template => {
            const patternMatch = template.pattern.test(input) ? 0.5 : 0;
            const similarity = this.calculateSimilarity(input, template);
            const keywordScore = this.calculateKeywordScore(input, template);
            
            const totalScore = patternMatch + similarity * 0.3 + keywordScore * 0.2;
            
            return {
                ...template,
                score: totalScore
            };
        });
        
        return suggestions
            .sort((a, b) => b.score - a.score)
            .slice(0, limit)
            .map(({ template, example, description, score }) => ({
                template,
                example,
                description,
                confidence: Math.round(score * 100)
            }));
    }

    // 자동 완성 제안
    autocomplete(partialInput) {
        if (partialInput.length < 2) return [];
        
        const matches = [];
        
        for (const template of this.commandTemplates) {
            if (template.example.toLowerCase().includes(partialInput.toLowerCase())) {
                matches.push({
                    suggestion: template.example,
                    description: template.description
                });
            }
        }
        
        return matches.slice(0, 5);
    }
}

export default SuggestionEngine;
```

---

## 🚀 고도화 방안 4: 통합 NLP 엔진

### 4.1 메인 NLP 프로세서

```javascript
// js/nlp/NLPProcessor.js
import IntentClassifier from './IntentClassifier.js';
import ContextAwareParser from './ContextAwareParser.js';
import SlotFiller from './SlotFiller.js';
import NLPErrorHandler from './ErrorHandler.js';
import SuggestionEngine from './SuggestionEngine.js';
import { normalizeKorean } from './LottoDictionary.js';

class NLPProcessor {
    constructor() {
        this.classifier = new IntentClassifier();
        this.parser = new ContextAwareParser(this.classifier);
        this.slotFiller = new SlotFiller();
        this.errorHandler = new NLPErrorHandler();
        this.suggestionEngine = new SuggestionEngine();
        
        this.debug = false;
    }

    process(rawInput) {
        const startTime = performance.now();
        const result = {
            success: false,
            input: rawInput,
            params: null,
            suggestions: [],
            warnings: [],
            errors: [],
            processingTime: 0
        };

        try {
            // 1단계: 전처리 (한국어 정규화)
            const normalizedInput = normalizeKorean(rawInput);
            if (this.debug) console.log('[NLP] Normalized:', normalizedInput);

            // 2단계: 의도 분류
            const classification = this.classifier.classify(normalizedInput);
            if (this.debug) console.log('[NLP] Classification:', classification);

            // 3단계: 신뢰도 체크 및 컨텍스트 파싱
            let parseResult;
            if (classification.confidence >= 0.5) {
                const extractedParams = classification.extractor?.(classification.match, normalizedInput) || {};
                parseResult = {
                    success: true,
                    intent: classification.intent,
                    confidence: classification.confidence,
                    params: extractedParams
                };
            } else {
                parseResult = this.parser.parse(normalizedInput);
            }

            if (!parseResult.success) {
                result.suggestions = this.suggestionEngine.suggest(normalizedInput);
                result.errors.push({
                    code: 'PARSE_FAILED',
                    message: '명령을 이해하지 못했습니다. 아래 제안을 참고해주세요.'
                });
                return this.finalize(result, startTime);
            }

            // 4단계: 슬롯 채움
            const slotResult = this.slotFiller.fill(parseResult.intent, parseResult.params);
            if (this.debug) console.log('[NLP] Slot filling:', slotResult);

            if (!slotResult.complete) {
                result.params = slotResult.data;
                result.warnings = slotResult.warnings;
                result.missingSlots = slotResult.missingSlots.map(slot => ({
                    ...slot,
                    question: this.slotFiller.generateQuestion(slot)
                }));
                result.needsMoreInfo = true;
                return this.finalize(result, startTime);
            }

            // 5단계: 검증 및 에러 수정
            const validation = this.errorHandler.validate(slotResult.data);
            if (this.debug) console.log('[NLP] Validation:', validation);

            result.success = true;
            result.intent = parseResult.intent;
            result.confidence = parseResult.confidence;
            result.params = validation.params;
            result.warnings = [...result.warnings, ...validation.warnings];
            
            if (validation.autoFixed) {
                result.autoFixed = true;
            }

        } catch (error) {
            result.errors.push({
                code: 'PROCESSING_ERROR',
                message: error.message
            });
            result.suggestions = this.suggestionEngine.suggest(rawInput, 5);
        }

        return this.finalize(result, startTime);
    }

    finalize(result, startTime) {
        result.processingTime = Math.round(performance.now() - startTime);
        return result;
    }

    // 대화형 슬롯 채움 (missing slot에 대한 응답 처리)
    fillSlot(slotName, value, previousResult) {
        if (!previousResult || !previousResult.params) {
            return { success: false, error: '이전 컨텍스트가 없습니다.' };
        }

        const updatedParams = { ...previousResult.params, [slotName]: value };
        const slotResult = this.slotFiller.fill(previousResult.intent, updatedParams);
        
        if (slotResult.complete) {
            const validation = this.errorHandler.validate(slotResult.data);
            return {
                success: true,
                params: validation.params,
                warnings: validation.warnings
            };
        }

        return {
            success: false,
            params: slotResult.data,
            missingSlots: slotResult.missingSlots
        };
    }

    // 자동 완성 지원
    autocomplete(partialInput) {
        return this.suggestionEngine.autocomplete(partialInput);
    }

    // 디버그 모드 토글
    setDebug(enabled) {
        this.debug = enabled;
    }
}

// 싱글톤 인스턴스
const nlpProcessor = new NLPProcessor();
export default nlpProcessor;
```

### 4.2 UI 통합 예시

```javascript
// js/nlp/NLPInput.js
import nlpProcessor from './NLPProcessor.js';

class NLPInputComponent {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        this.currentResult = null;
        this.render();
        this.bindEvents();
    }

    render() {
        this.container.innerHTML = `
            <div class="nlp-input-container relative">
                <!-- 메인 입력 -->
                <div class="relative">
                    <input type="text" 
                           id="nlpInput"
                           placeholder="분석 조건을 자연어로 입력하세요..."
                           class="w-full px-4 py-3 pr-12 border-2 border-gray-200 rounded-xl 
                                  focus:border-blue-500 focus:ring-2 focus:ring-blue-200 
                                  transition-all text-lg"
                           autocomplete="off">
                    <button id="nlpSubmit" 
                            class="absolute right-2 top-1/2 -translate-y-1/2 
                                   w-10 h-10 bg-blue-600 text-white rounded-lg
                                   hover:bg-blue-700 transition-colors flex items-center justify-center">
                        <span class="material-symbols-outlined">send</span>
                    </button>
                </div>

                <!-- 자동 완성 드롭다운 -->
                <div id="autocompleteDropdown" 
                     class="hidden absolute top-full left-0 right-0 mt-1 
                            bg-white border border-gray-200 rounded-xl shadow-lg z-50 overflow-hidden">
                </div>

                <!-- 결과/피드백 영역 -->
                <div id="nlpFeedback" class="mt-3 hidden">
                </div>

                <!-- 누락 슬롯 질문 -->
                <div id="missingSlotArea" class="mt-3 hidden">
                </div>
            </div>
        `;
    }

    bindEvents() {
        const input = this.container.querySelector('#nlpInput');
        const submitBtn = this.container.querySelector('#nlpSubmit');
        
        // 입력 시 자동 완성
        input.addEventListener('input', (e) => this.handleInput(e.target.value));
        
        // 엔터 키 처리
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                this.processInput(input.value);
            }
            if (e.key === 'Escape') {
                this.hideAutocomplete();
            }
        });
        
        // 제출 버튼
        submitBtn.addEventListener('click', () => this.processInput(input.value));
    }

    handleInput(value) {
        if (value.length < 2) {
            this.hideAutocomplete();
            return;
        }

        const suggestions = nlpProcessor.autocomplete(value);
        this.showAutocomplete(suggestions);
    }

    showAutocomplete(suggestions) {
        const dropdown = this.container.querySelector('#autocompleteDropdown');
        
        if (suggestions.length === 0) {
            dropdown.classList.add('hidden');
            return;
        }

        dropdown.innerHTML = suggestions.map(s => `
            <div class="autocomplete-item px-4 py-3 hover:bg-gray-50 cursor-pointer border-b border-gray-100 last:border-0"
                 data-value="${s.suggestion}">
                <div class="font-medium text-gray-900">${s.suggestion}</div>
                <div class="text-xs text-gray-500">${s.description}</div>
            </div>
        `).join('');

        dropdown.classList.remove('hidden');
        
        // 클릭 이벤트 바인딩
        dropdown.querySelectorAll('.autocomplete-item').forEach(item => {
            item.addEventListener('click', () => {
                this.container.querySelector('#nlpInput').value = item.dataset.value;
                this.hideAutocomplete();
            });
        });
    }

    hideAutocomplete() {
        this.container.querySelector('#autocompleteDropdown').classList.add('hidden');
    }

    processInput(value) {
        if (!value.trim()) return;

        const result = nlpProcessor.process(value);
        this.currentResult = result;
        this.displayFeedback(result);
    }

    displayFeedback(result) {
        const feedbackEl = this.container.querySelector('#nlpFeedback');
        const missingSlotEl = this.container.querySelector('#missingSlotArea');
        
        feedbackEl.classList.remove('hidden');

        if (result.success) {
            feedbackEl.innerHTML = `
                <div class="bg-green-50 border border-green-200 rounded-xl p-4">
                    <div class="flex items-center gap-2 text-green-800 font-bold mb-2">
                        <span class="material-symbols-outlined">check_circle</span>
                        분석 조건이 설정되었습니다
                    </div>
                    <div class="text-sm text-green-700">
                        <strong>유형:</strong> ${this.getTypeLabel(result.intent)}<br>
                        <strong>신뢰도:</strong> ${Math.round(result.confidence * 100)}%
                    </div>
                    ${result.warnings.length > 0 ? `
                        <div class="mt-2 text-yellow-700 text-sm">
                            ⚠️ ${result.warnings.map(w => w.message).join(', ')}
                        </div>
                    ` : ''}
                    <button onclick="window.createAnalysis(${JSON.stringify(result.params).replace(/"/g, '&quot;')})"
                            class="mt-3 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors">
                        이 조건으로 분석 생성
                    </button>
                </div>
            `;
            missingSlotEl.classList.add('hidden');
        } 
        else if (result.needsMoreInfo) {
            feedbackEl.innerHTML = `
                <div class="bg-yellow-50 border border-yellow-200 rounded-xl p-4">
                    <div class="flex items-center gap-2 text-yellow-800 font-bold">
                        <span class="material-symbols-outlined">help</span>
                        추가 정보가 필요합니다
                    </div>
                </div>
            `;
            this.showMissingSlotInput(result.missingSlots[0]);
        }
        else {
            feedbackEl.innerHTML = `
                <div class="bg-red-50 border border-red-200 rounded-xl p-4">
                    <div class="flex items-center gap-2 text-red-800 font-bold mb-2">
                        <span class="material-symbols-outlined">error</span>
                        ${result.errors[0]?.message || '명령을 이해하지 못했습니다'}
                    </div>
                    ${result.suggestions.length > 0 ? `
                        <div class="mt-3 space-y-2">
                            <div class="text-sm text-gray-600 font-medium">이런 명령은 어떠세요?</div>
                            ${result.suggestions.map(s => `
                                <div class="bg-white rounded-lg p-3 border border-gray-200 cursor-pointer hover:border-blue-300"
                                     onclick="document.querySelector('#nlpInput').value='${s.example}'">
                                    <div class="text-blue-600 font-medium">${s.example}</div>
                                    <div class="text-xs text-gray-500">${s.description}</div>
                                </div>
                            `).join('')}
                        </div>
                    ` : ''}
                </div>
            `;
        }
    }

    showMissingSlotInput(missingSlot) {
        const missingSlotEl = this.container.querySelector('#missingSlotArea');
        missingSlotEl.classList.remove('hidden');
        
        missingSlotEl.innerHTML = `
            <div class="bg-blue-50 border border-blue-200 rounded-xl p-4">
                <label class="block text-blue-800 font-medium mb-2">${missingSlot.question}</label>
                <div class="flex gap-2">
                    <input type="text" 
                           id="missingSlotInput"
                           class="flex-1 px-3 py-2 border border-blue-300 rounded-lg focus:ring-2 focus:ring-blue-200"
                           placeholder="입력...">
                    <button onclick="window.nlpInputComponent.fillMissingSlot('${missingSlot.slot}')"
                            class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700">
                        확인
                    </button>
                </div>
            </div>
        `;
    }

    fillMissingSlot(slotName) {
        const value = this.container.querySelector('#missingSlotInput').value;
        const result = nlpProcessor.fillSlot(slotName, value, this.currentResult);
        
        if (result.success) {
            this.currentResult.params = result.params;
            this.currentResult.success = true;
            this.displayFeedback(this.currentResult);
        } else {
            this.currentResult.missingSlots = result.missingSlots;
            this.showMissingSlotInput(result.missingSlots[0]);
        }
    }

    getTypeLabel(intent) {
        const labels = {
            'static_numbers': '고정 번호 분석',
            'dynamic_formula': '동적 수식 분석',
            'group_condition': '그룹 조건 분석',
            'statistical': '통계 기반 분석'
        };
        return labels[intent] || intent;
    }
}

// 글로벌 인스턴스 등록
window.nlpInputComponent = null;
window.initNLPInput = (containerId) => {
    window.nlpInputComponent = new NLPInputComponent(containerId);
};

export default NLPInputComponent;
```

---

## 📊 고도화 효과 예상

| 지표 | 현재 (추정) | 개선 후 (예상) |
|------|------------|---------------|
| 의도 인식률 | 60~70% | 85~95% |
| 파라미터 추출 정확도 | 50~60% | 80~90% |
| 오류 복구율 | 0% | 70~80% |
| 사용자 재시도율 | 40%+ | 15% 미만 |
| 평균 입력 시도 횟수 | 2~3회 | 1.2회 |

---

## 🛠️ 구현 로드맵

### Phase 1: 핵심 기능 (2주)
- [ ] IntentClassifier 구현
- [ ] 한국어 정규화 사전 구축
- [ ] 기본 파라미터 추출기 구현

### Phase 2: 사용자 경험 (2주)
- [ ] SuggestionEngine 구현
- [ ] 자동 완성 UI
- [ ] 에러 피드백 시스템

### Phase 3: 고급 기능 (2주)
- [ ] 컨텍스트 인식 파싱
- [ ] 대화형 슬롯 채움
- [ ] 학습 기반 개선 (사용자 피드백 수집)

### Phase 4: 최적화 (1주)
- [ ] 성능 최적화
- [ ] A/B 테스트
- [ ] 문서화 및 배포

---

## 💡 추가 개선 아이디어

### 1. 음성 입력 지원
```javascript
// Web Speech API 활용
const recognition = new webkitSpeechRecognition();
recognition.lang = 'ko-KR';
recognition.onresult = (e) => nlpProcessor.process(e.results[0][0].transcript);
```

### 2. 예시 기반 학습
```javascript
// 사용자가 선택한 제안을 학습
function learnFromSelection(userInput, selectedSuggestion) {
    // 로컬 스토리지에 패턴 저장
    const patterns = JSON.parse(localStorage.getItem('nlp_patterns') || '[]');
    patterns.push({ input: userInput, mapped: selectedSuggestion });
    localStorage.setItem('nlp_patterns', JSON.stringify(patterns.slice(-100)));
}
```

### 3. 다국어 지원 준비
```javascript
// i18n 구조화
const i18n = {
    ko: { patterns: koreanPatterns, dictionary: koreanDict },
    en: { patterns: englishPatterns, dictionary: englishDict }
};
```

---

## 📝 결론

이 고도화 방안은 기존 로또 분석 시스템의 자연어 처리 능력을 크게 향상시킬 수 있습니다. 특히:

1. **의도 분류 정확도 향상** - 멀티레이어 패턴 매칭으로 다양한 표현 인식
2. **한국어 특화 처리** - 도메인 특화 어휘 사전 및 정규화
3. **사용자 친화적 피드백** - 오류 시 구체적인 제안 제공
4. **대화형 인터페이스** - 누락 정보 자연스럽게 수집

이를 통해 사용자가 복잡한 UI 없이도 자연스러운 언어로 분석 조건을 설정할 수 있게 됩니다.
