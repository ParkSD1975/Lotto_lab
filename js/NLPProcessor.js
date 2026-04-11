/**
 * Lotto AI - 자연어 명령 처리 고도화 모듈
 * NLPProcessor.js - 통합 NLP 엔진
 */

// ===== 1. 로또 도메인 어휘 사전 =====
const LottoDictionary = {
    synonyms: {
        '분석': ['분석', '검토', '확인', '체크', '살펴', '알아', '조사', '해줘'],
        '패턴': ['패턴', '규칙', '법칙', '추세', '트렌드', '흐름', '경향'],
        '번호': ['번호', '숫자', '넘버', '볼', '공', '수'],
        '더하기': ['더하기', '플러스', '+', '추가', '더해서', '증가', '올려'],
        '빼기': ['빼기', '마이너스', '-', '감소', '줄여서', '내려'],
        '이월': ['이월', '캐리오버', '유지', '그대로', '동일', '같은'],
        '미출현': ['미출현', '안나온', '출현안한', '빠진', '없던', '미등장'],
        '연속': ['연속', '스트레이트', '연달아', '이어서', '계속', '직행'],
        '출현': ['출현', '나온', '당첨된', '등장', '출몰'],
        '고온수': ['고온수', '핫넘버', '자주나온', '빈출', '핫', '뜨거운'],
        '저온수': ['저온수', '콜드넘버', '안나온', '희귀', '콜드', '차가운'],
        '끝수': ['끝수', '일의자리', '마지막자리', '끝자리'],
        '홀수': ['홀수', '홀', '기수', '홀번'],
        '짝수': ['짝수', '짝', '우수', '짝번'],
        '소수': ['소수', '프라임', 'prime'],
        '삼각수': ['삼각수', 'triangular'],
        '제곱수': ['제곱수', 'square'],
        '피보나치': ['피보나치', 'fibonacci', '파보나치'],
        '루카스': ['루카스', 'lucas', '루카수'], // [New] 루카스 동의어 추가
        '동형수': ['동형수', '거울수', 'mirror'],
        '쌍수': ['쌍수', '트윈', 'twin'],
        '중첩수': ['중첩수', '중첩', '빈도', 'overlap'],
        '전회차': ['전회차', '이전회차', '지난회차', '직전회', '바로전']
    },

    koreanNumbers: {
        '하나': 1, '둘': 2, '셋': 3, '넷': 4, '다섯': 5,
        '여섯': 6, '일곱': 7, '여덟': 8, '아홉': 9, '열': 10,
        '한': 1, '두': 2, '세': 3, '네': 4,
        '일': 1, '이': 2, '삼': 3, '사': 4, '오': 5,
        '육': 6, '칠': 7, '팔': 8, '구': 9, '십': 10
    },

    suffixes: {
        '개': 'count', '회': 'round', '번': 'times',
        '이상': 'min', '이하': 'max', '초과': 'above', '미만': 'below'
    }
};

// 한국어 정규화 함수
function normalizeKorean(input) {
    let normalized = input;

    // 1. 한국어 숫자를 아라비아 숫자로
    for (const [korean, number] of Object.entries(LottoDictionary.koreanNumbers)) {
        normalized = normalized.replace(
            new RegExp(korean + '(?=\\s*개|\\s*회|\\s*번)', 'g'),
            String(number)
        );
    }

    // 2. 동의어 정규화
    for (const [standard, synonymList] of Object.entries(LottoDictionary.synonyms)) {
        for (const synonym of synonymList) {
            if (synonym !== standard) {
                const escapedSynonym = synonym.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                normalized = normalized.replace(new RegExp(escapedSynonym, 'gi'), standard);
            }
        }
    }

    // 3. 띄어쓰기 및 특수문자 정규화
    // [Fix] 쉼표 주변 공백 유연화 및 특수 쉼표 처리 강화
    normalized = normalized
        .replace(/，/g, ',') // 전각 쉼표 변환
        .replace(/\s*,\s*/g, ',') // 쉼표 주변 공백 제거하여 표준화 (1, 2 -> 1,2)
        .replace(/[""]/g, '"')
        .replace(/\s+/g, ' ')
        .trim();

    return normalized;
}

// ===== 2. 의도 분류기 (Intent Classifier) =====
class IntentClassifier {
    constructor() {
        this.intentPatterns = new Map();
        this.initializePatterns();
    }

    initializePatterns() {
        // 동적 수식 분석
        this.intentPatterns.set('dynamic_formula', {
            patterns: [
                /(?:전전회차|전회차|이전|지난|직전)\s*(?:회차|회|번)?\s*(?:번호|당첨번호)?\s*([+\-])\s*(\d+)/i,
                /(\d+)\s*(?:더하|빼|플러스|마이너스)/i,
                /(?:연속|이월|캐리오버|carryover)/i,
                /(?:당첨일|추첨일|날짜).{0,15}(?:조합|파생|연산|끝수|기준|기반)/i,
                /(?:회차|회).{0,5}(?:끝수|일의\s*자리)/i, // [New] 회차 끝수 패턴 추가
                /수식\s*[:：]?\s*([nxN]\s*[+\-*/]\s*\d+)/i
            ],
            extractor: this.extractDynamicParams.bind(this),
            priority: 10
        });

        // 고정 번호 분석
        this.intentPatterns.set('static_numbers', {
            patterns: [
                // [Fix] 쉼표(,) 패턴 인식 강화: (숫자+쉼표+숫자) 반복 패턴
                /(\d{1,2}(?:,\d{1,2})+)/,
                // 공백 또는 쉼표로 구분된 숫자 나열
                /(?:번호|숫자)\s*[:：]?\s*([\d\s,]+)/,
                /(\d{1,2})\s*번.*분석/
            ],
            extractor: this.extractStaticNumbers.bind(this),
            priority: 8
        });

        // 그룹 조건 분석
        this.intentPatterns.set('group_condition', {
            patterns: [
                /(?:그룹|묶음|조합)\s*(?:분석|조건)/i,
                /(?:고온수?|저온수?|핫|콜드)\s*(?:번호|수)?/i,
                /(\d+)\s*(?:~|에서|부터)\s*(\d+)\s*(?:까지|범위|대)/i,
                /(?:홀수|짝수|홀짝)/i,
                // [New] 루카스, 피보나치 등 특수 수열 키워드 직접 매칭
                /(?:소수|삼각수|제곱수|피보나치|루카스|쌍수|동형수)/i,
                /(\d+)\s*대\s*(?:번호|숫자|에서)/i
            ],
            extractor: this.extractGroupParams.bind(this),
            priority: 9
        });

        // 통계 기반 분석
        this.intentPatterns.set('statistical', {
            patterns: [
                /미출현\s*(\d+)\s*(?:회|번)\s*(?:이상)?/i,
                /(?:연속|스트레이트)\s*(\d+)\s*(?:회|번)/i,
                /(?:확률|통계|빈도)\s*(?:분석|조회)/i,
                /(\d+)\s*(?:회|번)\s*(?:연속|이상)\s*(?:미출현|안나온)/i
            ],
            extractor: this.extractStatisticalParams.bind(this),
            priority: 7
        });

        // 필터 조건 (보조)
        this.intentPatterns.set('filter_condition', {
            patterns: [
                /(?:최소|min)\s*(\d+)\s*(?:개|번호)/i,
                /(?:최대|max)\s*(\d+)\s*(?:개|번호)/i,
                /(\d+)\s*(?:~|에서)\s*(\d+)\s*개/i,
                /(?:제외|빼고|없이)\s*([\d,\s]+)/i
            ],
            extractor: this.extractFilterParams.bind(this),
            priority: 5
        });

        // 하이라이트/강조
        this.intentPatterns.set('highlight_property', {
            patterns: [
                /(?:강조|하이라이트|표시|체크)\s*(?:해줘)?\s*(.*)/i,
                /(.*)\s*(?:강조|하이라이트|보여줘)/i
            ],
            extractor: this.extractHighlightParams.bind(this),
            priority: 11
        });

        // 필터링 (데이터 뷰 제어)
        this.intentPatterns.set('filter_data', {
            patterns: [
                /(\d+)\s*(?:회|번)\s*(?:이상|이하|초과|미만)\s*(?:만\s*)?(?:보여|조회|필터)/i,
                /(?:합계|총합|AC)\s*(?:가|이)?\s*(\d+)\s*(?:이상|이하)/i,
                /(?:필터|걸러|남겨)\s*(?:줘|서)?/i
            ],
            extractor: this.extractFilterControlParams.bind(this),
            priority: 10
        });

        // 네비게이션/이동
        this.intentPatterns.set('navigate', {
            patterns: [
                /(?:이동|가기|가줘|스크롤)\s*(?:해줘)?/i,
                /(\d+)\s*(?:회차|번|회)(?:로|에)?\s*(?:이동|가기)/i
            ],
            extractor: this.extractNavigationParams.bind(this),
            priority: 12
        });

        // 설명 요청
        this.intentPatterns.set('explain_view', {
            patterns: [
                /(?:설명|알려줘|이건 뭐야|뜻)/i,
                /(?:어떻게|사용법)/i
            ],
            extractor: (m, i) => ({ type: 'explain', query: i }),
            priority: 6
        });

        // 회귀 스캔 (Exhaustive Scan)
        this.intentPatterns.set('regression_scan', {
            patterns: [
                /(?:회귀)\s*(?:전수조사|스캔|검색|조사)/i,
                /(\d+)\s*(?:회귀)\s*(?:까지)?\s*(?:전수조사|스캔)/i,
                /(?:전수조사|전수검사|전수스캔)/i
            ],
            extractor: (match, input) => {
                const limitMatch = input.match(/(\d+)\s*회귀/);
                return {
                    type: 'regression_scan',
                    limit: limitMatch ? parseInt(limitMatch[1]) : 200
                };
            },
            priority: 15
        });

        // 회귀 중첩 분석 (Regression Overlap)
        this.intentPatterns.set('regression_overlap', {
            patterns: [
                /(\d+)\s*(?:에서|~)\s*(\d+)\s*회귀\s*중첩수\s*(?:그룹|분석)/i,
                /회귀\s*중첩수\s*(?:분석|그룹)/i
            ],
            extractor: this.extractRegressionOverlapParams.bind(this),
            priority: 16
        });

        // 모드 전환 (View Switching)
        this.intentPatterns.set('switch_view', {
            patterns: [
                /(?:기본|원래|번호)\s*(?:분석|화면|모드|뷰)?\s*(?:로)?\s*(?:돌아가|보여)/i,
                /(?:회귀)\s*(?:화면|모드|뷰)\s*(?:보여|전환)/i
            ],
            extractor: (match, input) => {
                const target = /(?:회귀)/.test(input) ? 'regression' : 'number';
                return { type: 'switch_view', target };
            },
            priority: 14
        });
    }

    classify(input) {
        const normalizedInput = normalizeKorean(input);
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

        candidates.sort((a, b) => {
            if (b.priority !== a.priority) return b.priority - a.priority;
            return b.confidence - a.confidence;
        });

        return candidates.length > 0
            ? candidates[0]
            : { intent: 'unknown', confidence: 0, match: null, extractor: null };
    }

    calculateConfidence(match, input, config) {
        const coverageScore = match[0].length / input.length;
        const specificityScore = (match.length - 1) * 0.1;
        const baseScore = 0.5;
        return Math.min(1.0, baseScore + coverageScore * 0.3 + specificityScore);
    }

    // === 파라미터 추출 메서드들 ===

    extractDynamicParams(match, input) {
        const params = { type: 'dynamic', rules: {} };

        let step = 1;
        const prevMatches = input.match(/전/g);
        if (prevMatches) step = prevMatches.length;

        const numericStepMatch = input.match(/(\d+)\s*(?:회차|회|번)?\s*전/);
        if (numericStepMatch) step = parseInt(numericStepMatch[1]);

        params.rules.regression_step = step;

        if (/(?:당첨일|추첨일|날짜)/i.test(input)) {
            if (/(?:조합|파생|연산|복합|기반)/i.test(input)) {
                params.rules.formula = 'draw_date_math';
            } else {
                params.rules.formula = 'draw_date_end';
            }
        } else if (/(?:회차|회).{0,5}(?:끝수|일의\s*자리)/i.test(input)) {
            // [New] 회차 끝수 분석 (예: 1103회 -> 3끝수 분석)
            params.rules.formula = 'round_end_digit';
        }

        const plusMinusMatch = input.match(/([+\-])\s*(\d+)/);
        if (plusMinusMatch) {
            params.rules.formula = plusMinusMatch[1] === '+' ? 'prev_plus_n' : 'prev_minus_n';
            params.rules.value = parseInt(plusMinusMatch[2]);
        }

        if (!params.rules.formula) {
            params.rules.formula = 'prev_plus_n';
            params.rules.value = params.rules.value || 1;
        }

        return params;
    }

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

    extractGroupParams(match, input) {
        const groups = [];

        // 소수 그룹
        if (/(?:소수|프라임)/i.test(input)) {
            groups.push({
                name: '소수 그룹',
                numbers: [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43],
                condition: { min: 1, max: 3 }
            });
        }

        // [New] 루카스 수 포함한 특수 수열 정의 추가
        const definitions = {
            '삼각수': [1, 3, 6, 10, 15, 21, 28, 36, 45],
            '제곱수': [1, 4, 9, 16, 25, 36],
            '피보나치': [1, 2, 3, 5, 8, 13, 21, 34],
            '루카스': [1, 3, 4, 7, 11, 18, 29, 47], // [New] 루카스 수 추가
            '쌍수': [11, 22, 33, 44],
            '동형수': [12, 21, 13, 31, 14, 41, 23, 32, 34, 43]
        };

        for (const [name, nums] of Object.entries(definitions)) {
            if (new RegExp(name).test(input)) {
                // 1~45 범위 내 숫자만 필터링
                const validNums = nums.filter(n => n >= 1 && n <= 45);
                groups.push({ name: `${name} 그룹`, numbers: validNums, condition: { min: 1, max: 3 } });
            }
        }

        // 합성수 그룹
        if (/(?:합성수)/i.test(input)) {
            groups.push({
                name: '합성수 그룹',
                numbers: [4, 6, 8, 9, 10, 12, 14, 15, 16, 18, 20, 21, 22, 24, 25, 26, 27, 28, 30, 32, 33, 34, 35, 36, 38, 39, 40, 42, 44, 45],
                condition: { min: 2, max: 4 }
            });
        }

        // 범위 그룹
        const rangePattern = /(\d+)\s*(?:~|에서|부터)\s*(\d+)/g;
        let rm;
        while ((rm = rangePattern.exec(input)) !== null) {
            const start = parseInt(rm[1]);
            const end = parseInt(rm[2]);
            if (start <= 45 && end <= 45) {
                groups.push({
                    name: `${start}-${end} 범위`,
                    numbers: Array.from({ length: end - start + 1 }, (_, i) => start + i).filter(n => n >= 1 && n <= 45),
                    condition: { min: 1, max: 3 }
                });
            }
        }

        // N대 표현
        const decadePattern = /(\d)0\s*대/g;
        while ((rm = decadePattern.exec(input)) !== null) {
            const decade = parseInt(rm[1]);
            const start = decade * 10 + 1;
            const end = Math.min((decade + 1) * 10, 45);
            groups.push({
                name: `${decade}0대`,
                numbers: Array.from({ length: end - start + 1 }, (_, i) => start + i),
                condition: { min: 1, max: 3 }
            });
        }

        // 고온/저온, 홀짝 처리 로직 유지
        if (/고온|핫|hot/i.test(input)) {
            groups.push({ name: '고온수', numbers: [], type: 'hot', condition: { min: 1, max: 3 } });
        }
        if (/저온|콜드|cold/i.test(input)) {
            groups.push({ name: '저온수', numbers: [], type: 'cold', condition: { min: 1, max: 3 } });
        }
        if (/홀수/i.test(input)) {
            groups.push({
                name: '홀수',
                numbers: [1, 3, 5, 7, 9, 11, 13, 15, 17, 19, 21, 23, 25, 27, 29, 31, 33, 35, 37, 39, 41, 43, 45],
                condition: { min: 2, max: 4 }
            });
        }
        if (/짝수/i.test(input)) {
            groups.push({
                name: '짝수',
                numbers: [2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30, 32, 34, 36, 38, 40, 42, 44],
                condition: { min: 2, max: 4 }
            });
        }

        const combineLogic = /(?:또는|or|이거나)/i.test(input) ? 'OR' : 'AND';

        return {
            type: 'group',
            config: { groups, combineLogic }
        };
    }

    extractRegressionOverlapParams(match, input) {
        const range = input.match(/(\d+)\s*(?:에서|~)\s*(\d+)/);
        return {
            type: 'regression_overlap',
            config: {
                startStep: range ? parseInt(range[1]) : 2,
                endStep: range ? parseInt(range[2]) : 200,
                combineLogic: 'AND'
            }
        };
    }

    extractStatisticalParams(match, input) {
        const params = { type: 'statistical', rules: {} };
        const gapMatch = input.match(/미출현\s*(\d+)\s*(?:회|번)/i) ||
            input.match(/(\d+)\s*(?:회|번)\s*(?:연속|이상)\s*미출현/i);
        if (gapMatch) params.rules.minGap = parseInt(gapMatch[1]);

        const streakMatch = input.match(/(?:연속|스트레이트)\s*(\d+)\s*(?:회|번)/i);
        if (streakMatch) params.rules.minStreak = parseInt(streakMatch[1]);

        return params;
    }

    extractFilterParams(match, input) {
        const filters = {};
        const rangeMatch = input.match(/(\d+)\s*(?:~|에서)\s*(\d+)\s*개/i);
        if (rangeMatch) {
            filters.min = parseInt(rangeMatch[1]);
            filters.max = parseInt(rangeMatch[2]);
        }
        const minMatch = input.match(/(?:최소|min)\s*(\d+)\s*개/i);
        const maxMatch = input.match(/(?:최대|max)\s*(\d+)\s*개/i);
        if (minMatch) filters.min = parseInt(minMatch[1]);
        if (maxMatch) filters.max = parseInt(maxMatch[1]);

        if (excludeMatch) {
            const matches = excludeMatch[1].match(/\d+/g);
            filters.exclude = matches ? matches.map(Number) : [];
        }
        return { filter_config: filters };
    }

    extractHighlightParams(match, input) {
        const params = { type: 'highlight', target: null, numbers: [] };
        const numberMatches = input.match(/\d+/g);
        if (numberMatches) {
            params.numbers = numberMatches.map(Number).filter(n => n >= 1 && n <= 45);
        }
        if (/(?:소수|프라임)/.test(input)) params.target = 'prime';
        else if (/(?:합성수)/.test(input)) params.target = 'composite';
        else if (/(?:3배수)/.test(input)) params.target = 'multiple3';
        else if (/(?:이월)/.test(input)) params.target = 'carryover';
        else if (/(?:연속)/.test(input)) params.target = 'consecutive';
        else if (input.includes('10회')) params.target = 'recent10';
        return params;
    }

    extractFilterControlParams(match, input) {
        const params = { type: 'filter', condition: null, value: null };
        const roundMatch = input.match(/(\d+)\s*(?:회|번)\s*(?:이상|부터)/);
        if (roundMatch) {
            params.condition = 'round_ge';
            params.value = parseInt(roundMatch[1]);
        }
        const sumMatch = input.match(/(?:합|AC).*(\d+)\s*(?:이상|초과)/);
        if (sumMatch) {
            params.condition = 'value_ge';
            params.value = parseInt(sumMatch[1]);
        }
        return params;
    }

    extractNavigationParams(match, input) {
        const numMatch = input.match(/(\d+)/);
        return {
            type: 'navigation',
            targetRound: numMatch ? parseInt(numMatch[1]) : 'latest'
        };
    }
}

// ===== 3. 에러 핸들러 및 슬롯 필러는 기존 유지 =====
class NLPErrorHandler {
    constructor() {
        this.errorPatterns = [
            {
                name: 'out_of_range',
                detector: (params) => params.target_numbers && params.target_numbers.some(n => n < 1 || n > 45),
                message: '로또 번호는 1~45 사이여야 합니다. 범위 밖 번호는 자동으로 제거됩니다.',
                fixer: (params) => {
                    if (params.target_numbers) {
                        params.target_numbers = params.target_numbers.filter(n => n >= 1 && n <= 45);
                    }
                    return params;
                }
            },
            {
                name: 'duplicate_numbers',
                detector: (params) => params.target_numbers && new Set(params.target_numbers).size !== params.target_numbers.length,
                message: '중복된 번호가 자동으로 제거되었습니다.',
                fixer: (params) => {
                    if (params.target_numbers) {
                        params.target_numbers = [...new Set(params.target_numbers)];
                    }
                    return params;
                }
            },
            {
                name: 'empty_targets',
                detector: (params) => params.type === 'static' && (!params.target_numbers || params.target_numbers.length === 0),
                message: '분석할 번호가 없습니다. 번호를 입력해주세요.',
                fixer: null
            },
            {
                name: 'invalid_filter_range',
                detector: (params) => {
                    const fc = params.filter_config;
                    return fc && fc.min !== undefined && fc.max !== undefined && fc.min > fc.max;
                },
                message: '필터 범위가 잘못되었습니다. 자동으로 수정됩니다.',
                fixer: (params) => {
                    if (params.filter_config) {
                        const { min, max } = params.filter_config;
                        params.filter_config.min = Math.min(min, max);
                        params.filter_config.max = Math.max(min, max);
                    }
                    return params;
                }
            }
        ];
    }

    validate(params) {
        const warnings = [];
        const errors = [];
        let fixedParams = { ...params };

        for (const pattern of this.errorPatterns) {
            if (pattern.detector(fixedParams)) {
                if (pattern.fixer) {
                    warnings.push({ type: pattern.name, message: pattern.message });
                    fixedParams = pattern.fixer(fixedParams);
                } else {
                    errors.push({ type: pattern.name, message: pattern.message });
                }
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

class SlotFiller {
    constructor() {
        this.slots = {
            'dynamic_formula': {
                formula: { required: true, type: 'enum', values: ['prev_plus_n', 'prev_minus_n', 'carryover', 'draw_date_end', 'round_end_digit', 'math_expression'] },
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
            'filter_condition': {
                filter_config: { required: true, type: 'object' }
            }
        };
    }

    fill(intent, extractedData) {
        const slotDefinition = this.slots[intent];
        if (!slotDefinition) return { data: extractedData, complete: true, missingSlots: [], warnings: [] };

        const result = { ...extractedData };
        const missingRequired = [];
        const warnings = [];

        if (intent === 'dynamic_formula' && !result.rules) result.rules = {};
        if (intent === 'group_condition' && !result.config) result.config = {};

        for (const [slotName, config] of Object.entries(slotDefinition)) {
            let value;
            if (intent === 'dynamic_formula') {
                if (['formula', 'value', 'expression'].includes(slotName)) {
                    value = (result.rules && result.rules[slotName]) ? result.rules[slotName] : undefined;
                }
            } else if (intent === 'group_condition') {
                if (['groups', 'combineLogic'].includes(slotName)) {
                    value = (result.config && result.config[slotName]) ? result.config[slotName] : undefined;
                }
            } else if (intent === 'static_numbers') {
                if (slotName === 'target_numbers') value = result.target_numbers;
            } else {
                value = result[slotName];
            }

            if (config.required && (value === undefined || value === null)) {
                if (config.default !== undefined) {
                    this.setValue(result, intent, slotName, config.default);
                } else {
                    missingRequired.push({
                        slot: slotName,
                        description: this.getSlotDescription(slotName)
                    });
                }
                continue;
            }

            if (value === undefined && config.default !== undefined) {
                this.setValue(result, intent, slotName, config.default);
            }
        }

        return {
            data: result,
            complete: missingRequired.length === 0,
            missingSlots: missingRequired,
            warnings
        };
    }

    setValue(obj, intent, key, val) {
        if (intent === 'dynamic_formula') {
            if (!obj.rules) obj.rules = {};
            obj.rules[key] = val;
        } else if (intent === 'group_condition') {
            if (!obj.config) obj.config = {};
            obj.config[key] = val;
        } else {
            obj[key] = val;
        }
    }

    getSlotDescription(slotName) {
        const descriptions = {
            'formula': '분석 수식 (예: 전회차 +1)',
            'target_numbers': '분석할 번호',
            'groups': '그룹 조건',
            'expression': '수식 내용'
        };
        return descriptions[slotName] || slotName;
    }
}

class ContextAwareParser {
    constructor(intentClassifier) {
        this.classifier = intentClassifier;
        this.conversationHistory = [];
        this.maxHistoryLength = 5;
    }

    parse(input) {
        const classification = this.classifier.classify(input);
        let params = classification.extractor
            ? classification.extractor(classification.match, input)
            : {};

        if (this.isModificationRequest(input) && this.conversationHistory.length > 0) {
            const lastAnalysis = this.conversationHistory[this.conversationHistory.length - 1];
            return this.createModification(lastAnalysis, input);
        }

        if (/(?:그거|이전|아까)\s*(?:비슷|처럼|같이)/.test(input) && this.conversationHistory.length > 0) {
            const last = this.conversationHistory[this.conversationHistory.length - 1];
            if (last.intent) {
                classification.intent = last.intent;
                params = { ...last.params, ...params };
                classification.confidence = 0.8;
            }
        }

        return {
            intent: classification.intent,
            confidence: classification.confidence,
            params: params,
            match: classification.match
        };
    }

    isModificationRequest(input) {
        return /(?:추가|빼|제외|삭제|변경|수정|바꿔)/.test(input) &&
            !/(?:분석|해줘|보여)/.test(input);
    }

    createModification(lastAnalysis, input) {
        const modification = JSON.parse(JSON.stringify(lastAnalysis.params));
        let modType = 'modification';
        let confidence = 0.8;
        const matches = input.match(/\d+/g);
        const numbers = matches ? matches.map(Number) : [];

        if (/(?:추가|더해|넣어)/.test(input)) {
            if (modification.target_numbers) {
                modification.target_numbers.push(...numbers);
                modification.target_numbers = [...new Set(modification.target_numbers)].sort((a, b) => a - b);
            }
        } else if (/(?:빼|제외|삭제)/.test(input)) {
            if (modification.target_numbers) {
                const toRemove = new Set(numbers);
                modification.target_numbers = modification.target_numbers.filter(n => !toRemove.has(n));
            }
        }

        return {
            intent: modType,
            confidence: confidence,
            params: modification,
            originalIntent: lastAnalysis.intent
        };
    }

    updateHistory(input, result) {
        this.conversationHistory.push({
            input,
            intent: result.intent,
            params: result.params,
            timestamp: Date.now()
        });
        if (this.conversationHistory.length > this.maxHistoryLength) {
            this.conversationHistory.shift();
        }
    }
}

class SuggestionEngine {
    constructor() {
        this.templates = [
            {
                pattern: /번호|숫자|\d+/,
                example: '3, 7, 15, 22, 35 번호 분석해줘',
                description: '특정 번호들의 출현 패턴 분석'
            },
            {
                pattern: /루카스|피보나치/,
                example: '루카스 수로 분석해줘',
                description: '특수 수열(루카스, 피보나치) 분석'
            },
            {
                pattern: /전|이전|지난|회차/,
                example: '전회차 +1 패턴 분석',
                description: '이전 당첨번호 기반 동적 분석'
            },
            {
                pattern: /미출현|안나온/,
                example: '미출현 5회 이상 번호 분석',
                description: '연속 미출현 번호 분석'
            }
        ];
    }

    suggest(input, limit = 3) {
        const scores = this.templates.map(t => ({
            ...t,
            score: this.calculateScore(input, t)
        }));

        return scores
            .sort((a, b) => b.score - a.score)
            .slice(0, limit)
            .filter(s => s.score > 0)
            .map(({ example, description, score }) => ({
                example,
                description,
                confidence: Math.round(score * 100)
            }));
    }

    calculateScore(input, template) {
        let score = 0;
        if (template.pattern.test(input)) score += 0.5;
        const inputWords = input.toLowerCase().split(/\s+/);
        const exampleWords = template.example.toLowerCase().split(/\s+/);
        const matchedWords = inputWords.filter(w =>
            exampleWords.some(ew => ew.includes(w) || w.includes(ew))
        );
        score += (matchedWords.length / Math.max(inputWords.length, 1)) * 0.3;
        return Math.min(1, score);
    }

    autocomplete(partialInput) {
        if (partialInput.length < 2) return [];
        const lowerInput = partialInput.toLowerCase();
        return this.templates
            .filter(t => t.example.toLowerCase().includes(lowerInput))
            .slice(0, 5)
            .map(t => ({
                suggestion: t.example,
                description: t.description
            }));
    }
}

// ===== 5. 통합 NLP 프로세서 =====
class NLPProcessor {
    constructor() {
        this.classifier = new IntentClassifier();
        this.contextParser = new ContextAwareParser(this.classifier);
        this.slotFiller = new SlotFiller();
        this.errorHandler = new NLPErrorHandler();
        this.suggestionEngine = new SuggestionEngine();
        this.debug = false;
    }

    // [핵심 변경] async 키워드 추가
    async process(rawInput) {
        const startTime = performance.now();
        const result = {
            success: false,
            input: rawInput,
            params: null,
            suggestions: [],
            warnings: [],
            errors: [],
            processingTime: 0,
            source: 'local_regex' // 출처 표시 (local_regex 또는 remote_ai)
        };

        try {
            const normalizedInput = normalizeKorean(rawInput);
            if (this.debug) console.log('[NLP] Normalized:', normalizedInput);

            // 1. 로컬 정규식(Regex)으로 먼저 시도 (속도 최적화)
            const parsed = this.contextParser.parse(normalizedInput);

            // 2. 로컬 파싱 성공 여부 판단
            let confidenceThreshold = 0.6;
            let isUnknown = (parsed.confidence < confidenceThreshold || parsed.intent === 'unknown');

            // [New] 로컬 파싱 실패 시 -> AI(제미나이)에게 물어보기 (Fallback)
            if (isUnknown) {
                if (this.debug) console.log('⚠️ 로컬 파싱 실패. AI에게 위임합니다...');
                try {
                    // AIProxy가 없다면 에러 처리
                    if (!window.AIProxy || !window.AIProxy.interpret) {
                        // AIProxy가 아직 로드되지 않았거나 없을 수 있음
                        console.warn("AIProxy not found or interpret not supported");
                    } else {
                        // 백엔드 호출
                        const aiResult = await window.AIProxy.interpret(rawInput);

                        if (aiResult && aiResult.intent && aiResult.intent !== 'unknown') {
                            // AI 응답을 로컬 파싱 결과처럼 덮어쓰기
                            parsed.intent = aiResult.intent;
                            parsed.params = aiResult.params || {};
                            parsed.confidence = 0.95; // AI 신뢰도 높음
                            result.source = 'remote_ai'; // 출처 변경
                            isUnknown = false; // 해결됨!

                            if (this.debug) console.log('✅ AI 파싱 성공:', aiResult);
                        }
                    }
                } catch (aiError) {
                    console.warn('[NLP] AI Fallback Failed:', aiError);
                    // AI도 실패하면 원래대로 실패 처리
                }
            }

            // 3. 여전히 모르면 제안(Suggestion) 모드로
            if (isUnknown) {
                result.suggestions = this.suggestionEngine.suggest(normalizedInput, 5);
                result.errors.push({
                    code: 'PARSE_FAILED',
                    message: '명령을 이해하지 못했습니다. (AI도 해석에 실패했습니다)'
                });
                return this.finalize(result, startTime);
            }

            // 4. 파라미터 검증 및 채우기 (기존 로직 수행)
            // AI가 준 params도 이 과정을 거치면서 유효성 검사를 받게 됨
            const filled = this.slotFiller.fill(parsed.intent, parsed.params);
            if (!filled.complete) {
                result.errors.push({
                    code: 'MISSING_SLOTS',
                    message: `다음 정보가 필요합니다: ${filled.missingSlots.map(s => s.description).join(', ')}`,
                    missingSlots: filled.missingSlots
                });
                return this.finalize(result, startTime);
            }

            const validation = this.errorHandler.validate(filled.data);
            if (!validation.valid) {
                result.errors = validation.errors;
                result.suggestions = this.suggestionEngine.suggest(normalizedInput);
                return this.finalize(result, startTime);
            }

            // 5. 최종 성공
            result.success = true;
            result.intent = parsed.intent;
            result.confidence = parsed.confidence;
            result.params = validation.params;
            result.warnings = [...(parsed.warnings || []), ...(filled.warnings || []), ...validation.warnings];
            if (validation.autoFixed) result.autoFixed = true;

            this.contextParser.updateHistory(normalizedInput, result);

        } catch (error) {
            console.error('[NLP] Error:', error);
            result.errors.push({
                code: 'PROCESSING_ERROR',
                message: error.message || '처리 중 오류가 발생했습니다.'
            });
            result.suggestions = this.suggestionEngine.suggest(rawInput, 5);
        }

        return this.finalize(result, startTime);
    }

    finalize(result, startTime) {
        result.processingTime = Math.round(performance.now() - startTime);
        return result;
    }

    autocomplete(partialInput) {
        return this.suggestionEngine.autocomplete(partialInput);
    }

    setDebug(enabled) {
        this.debug = enabled;
    }
}

const nlpProcessor = new NLPProcessor();

if (typeof window !== 'undefined') {
    window.NLPProcessor = NLPProcessor;
    window.nlpProcessor = nlpProcessor;
    window.normalizeKorean = normalizeKorean;
    window.LottoDictionary = LottoDictionary;
}
