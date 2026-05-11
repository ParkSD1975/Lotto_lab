/**
 * Lotto Lab Self-Discovery NLP Phase 2 - AutoNLPMatcher
 *
 * vocabulary.json 기반 자동 매칭 엔진
 * - 다단계 매칭: Exact → Substring → Fuzzy → Token-level
 * - 한글 특수 처리: 자모 분리, 숫자 한글, 조사 제거
 * - Intent 분류: filter_combination / regression_query / model_query / unknown
 * - Span tracking: 중복 매칭 방지
 *
 * @version 1.0.0
 * @date 2026-05-08
 */

class AutoNLPMatcher {
    constructor(vocabularyUrl = '/js/vocabulary.json') {
        this.vocabularyUrl = vocabularyUrl;
        this.vocabulary = null;
        this.aliasIndex = new Map(); // alias → vocab entry 역인덱스
        this.loaded = false;

        // 한글 숫자 매핑
        this.koreanNumbers = {
            '하나': 1, '둘': 2, '셋': 3, '넷': 4, '다섯': 5,
            '여섯': 6, '일곱': 7, '여덟': 8, '아홉': 9, '열': 10,
            '한': 1, '두': 2, '세': 3, '네': 4,
            '일': 1, '이': 2, '삼': 3, '사': 4, '오': 5,
            '육': 6, '칠': 7, '팔': 8, '구': 9, '십': 10,
            '영': 0, '공': 0
        };

        // 한글 조사 패턴
        this.koreanParticles = ['의', '를', '을', '가', '이', '에', '로', '으로', '와', '과', '도'];
    }

    /**
     * vocabulary.json 로드 + 역인덱스 구축
     */
    async load() {
        const cacheKey = 'autoNLP_vocabulary_cache';
        const cacheTTL = 5 * 60 * 1000; // 5분

        try {
            // localStorage 캐시 확인
            const cached = localStorage.getItem(cacheKey);
            if (cached) {
                const parsed = JSON.parse(cached);
                if (Date.now() - parsed.timestamp < cacheTTL) {
                    this.vocabulary = parsed.data;
                    this._buildIndex();
                    this.loaded = true;
                    return;
                }
            }
        } catch (e) {
            console.warn('[AutoNLP] localStorage cache read failed:', e);
        }

        // 네트워크 로드
        const url = `${this.vocabularyUrl}?v=${Date.now()}`;
        const response = await fetch(url);
        if (!response.ok) {
            throw new Error(`Failed to load vocabulary: ${response.status}`);
        }

        this.vocabulary = await response.json();
        this._buildIndex();
        this.loaded = true;

        // 캐시 저장
        try {
            localStorage.setItem(cacheKey, JSON.stringify({
                data: this.vocabulary,
                timestamp: Date.now()
            }));
        } catch (e) {
            console.warn('[AutoNLP] localStorage cache write failed:', e);
        }
    }

    /**
     * 역인덱스 구축: alias → { section, entry }
     */
    _buildIndex() {
        this.aliasIndex.clear();

        const sections = ['filters', 'models', 'operations', 'statistics', 'time_windows'];
        for (const section of sections) {
            const entries = this.vocabulary[section] || [];
            for (const entry of entries) {
                const aliases = entry.aliases || [];
                for (const alias of aliases) {
                    const normalized = this._normalizeText(alias);
                    if (!this.aliasIndex.has(normalized)) {
                        this.aliasIndex.set(normalized, []);
                    }
                    this.aliasIndex.get(normalized).push({ section, entry });
                }
            }
        }
    }

    /**
     * 텍스트 정규화 (소문자 + 공백 제거)
     */
    _normalizeText(text) {
        return text.toLowerCase().replace(/\s+/g, '');
    }

    /**
     * 메인 매칭 메서드
     * @param {string} text - 입력 텍스트
     * @param {object} options - { maxFuzzyDistance: 2, minFuzzyScore: 0.6 }
     * @returns {object} - 매칭 결과
     */
    match(text, options = {}) {
        if (!this.loaded) {
            throw new Error('AutoNLPMatcher not loaded. Call load() first.');
        }

        const opts = {
            maxFuzzyDistance: options.maxFuzzyDistance || 2,
            minFuzzyScore: options.minFuzzyScore || 0.6,
            ...options
        };

        // 텍스트 전처리 (토큰화 먼저, 그 후 조사 제거)
        const tokens = this._tokenize(text); // 원본 텍스트로 토큰화 (확장 포함)
        const cleanedText = this._removeParticles(text); // 매칭용 정규화된 텍스트

        // 섹션별 매칭 저장
        const matches = {
            filters: [],
            models: [],
            operations: [],
            statistics: [],
            time_windows: [],
            numbers: this._extractNumbers(cleanedText),
            raw_tokens: tokens,
            spans: [] // [start, end] 중복 방지
        };

        // 각 섹션 매칭
        matches.filters = this._matchSection(cleanedText, tokens, 'filters', opts);
        matches.models = this._matchSection(cleanedText, tokens, 'models', opts);
        matches.operations = this._matchSection(cleanedText, tokens, 'operations', opts);
        matches.statistics = this._matchSection(cleanedText, tokens, 'statistics', opts);
        matches.time_windows = this._matchSection(cleanedText, tokens, 'time_windows', opts);

        // Intent 분류
        const intentResult = this._classifyIntent(matches, cleanedText);
        matches.intent = intentResult.intent;
        matches.confidence = intentResult.confidence;

        // spans 제거 (내부 사용)
        delete matches.spans;

        return matches;
    }

    /**
     * 섹션별 매칭
     */
    _matchSection(text, tokens, section, opts) {
        const results = [];
        const entries = this.vocabulary[section] || [];

        // 텍스트에서 숫자 추출 (배수 필터 컨텍스트용)
        const numbersInText = this._extractNumbers(text).map(n => n.value);

        for (const entry of entries) {
            const aliases = entry.aliases || [];
            for (const alias of aliases) {
                const matchResult = this._matchAlias(text, tokens, alias, entry, section, opts);
                if (matchResult) {
                    // 배수 필터 특수 처리: 텍스트에 명시된 숫자와 일치하지 않으면 점수 하락
                    if (section === 'filters' && this._isMultipleFilter(entry.key)) {
                        const filterNumber = this._extractFilterNumber(entry.key);
                        if (filterNumber && numbersInText.length > 0) {
                            if (!numbersInText.includes(filterNumber)) {
                                matchResult.score *= 0.3; // 대폭 감점
                                matchResult.penalized = true;
                            }
                        }
                    }

                    results.push(matchResult);
                }
            }
        }

        // 중복 제거 (같은 key는 최고 점수만)
        const unique = new Map();
        for (const r of results) {
            const existing = unique.get(r.key);
            if (!existing || r.score > existing.score) {
                unique.set(r.key, r);
            }
        }

        // 점수 임계값 필터링 (상위 매칭만)
        const sorted = Array.from(unique.values()).sort((a, b) => b.score - a.score);

        // score >= 0.7인 항목만 (penalized 제거)
        return sorted.filter(r => r.score >= 0.7 && !r.penalized);
    }

    /**
     * 배수 필터 여부 확인
     */
    _isMultipleFilter(key) {
        return /^(mul|multiple)/.test(key) || key.includes('multiple');
    }

    /**
     * 필터 key에서 숫자 추출 (mul7 → 7, multiple_3_count → 3)
     */
    _extractFilterNumber(key) {
        const match = key.match(/\d+/);
        return match ? parseInt(match[0]) : null;
    }

    /**
     * 단일 alias 매칭
     */
    _matchAlias(text, tokens, alias, entry, section, opts) {
        const normalized = this._normalizeText(alias);
        const normalizedText = this._normalizeText(text);

        // 최소 길이 제한 (1~2글자 alias는 정확 매칭만)
        const minLengthForSubstring = 3;

        // 1. Exact match (전체 텍스트)
        if (normalizedText === normalized) {
            return this._createMatch(entry, alias, 1.0, [0, text.length], section);
        }

        // 2. Token-level exact match (우선순위 높임)
        for (let i = 0; i < tokens.length; i++) {
            const token = tokens[i];
            const normToken = this._normalizeText(token);
            if (normToken === normalized) {
                const span = this._findTokenSpan(text, token, i);
                return this._createMatch(entry, alias, 0.95, span, section);
            }
        }

        // 2-1. Multi-token match (연속된 토큰 결합, "7의 배수" 같은 케이스)
        for (let i = 0; i < tokens.length - 1; i++) {
            for (let j = i + 1; j <= Math.min(i + 3, tokens.length); j++) {
                const combined = tokens.slice(i, j).join('');
                const normCombined = this._normalizeText(combined);
                if (normCombined === normalized) {
                    return this._createMatch(entry, alias, 0.93, [0, 0], section);
                }
            }
        }

        // 3. Substring match (길이 제한 + 단어 경계 검사)
        if (normalized.length >= minLengthForSubstring) {
            const index = normalizedText.indexOf(normalized);
            if (index !== -1) {
                // 단어 경계 확인 (앞뒤가 공백이거나 문자열 시작/끝)
                const before = index === 0 || /\s/.test(normalizedText[index - 1]);
                const after = (index + normalized.length >= normalizedText.length) ||
                              /\s/.test(normalizedText[index + normalized.length]);

                if (before || after) {
                    return this._createMatch(entry, alias, 0.85, [index, index + normalized.length], section);
                }
            }
        }

        // 4. Fuzzy match (길이 비율 제한)
        const fuzzyResults = [];
        for (const token of tokens) {
            const normToken = this._normalizeText(token);

            // 길이 차이가 너무 크면 스킵
            const lengthRatio = Math.min(normToken.length, normalized.length) /
                               Math.max(normToken.length, normalized.length);
            if (lengthRatio < 0.5) continue;

            const distance = this._levenshteinDistance(normToken, normalized);
            if (distance <= opts.maxFuzzyDistance) {
                const score = 1 - (distance / Math.max(token.length, alias.length));
                if (score >= opts.minFuzzyScore) {
                    const span = this._findTokenSpan(text, token, tokens.indexOf(token));
                    fuzzyResults.push({ score: score * 0.7, span }); // fuzzy는 0.7 가중
                }
            }
        }

        // 5. 한글 자모 유사도 (한글 토큰에만, 길이 비율 제한)
        for (const token of tokens) {
            if (this._isKorean(token) && this._isKorean(alias)) {
                const lengthRatio = Math.min(token.length, alias.length) /
                                   Math.max(token.length, alias.length);
                if (lengthRatio < 0.5) continue;

                const similarity = this._hangulSimilarity(token, alias);
                if (similarity >= 0.8) {
                    const span = this._findTokenSpan(text, token, tokens.indexOf(token));
                    fuzzyResults.push({ score: similarity * 0.65, span });
                }
            }
        }

        if (fuzzyResults.length > 0) {
            const best = fuzzyResults.sort((a, b) => b.score - a.score)[0];
            return this._createMatch(entry, alias, best.score, best.span, section);
        }

        return null;
    }

    /**
     * Match 객체 생성
     */
    _createMatch(entry, matchedAlias, score, span, section) {
        return {
            key: entry.key,
            name_kr: entry.name_kr || entry.key,
            name_en: entry.name_en || '',
            score: Math.round(score * 100) / 100,
            matched_alias: matchedAlias,
            span,
            category: entry.category || section,
            description: entry.description || ''
        };
    }

    /**
     * 토큰의 원본 span 찾기
     */
    _findTokenSpan(text, token, tokenIndex) {
        const normalized = this._normalizeText(text);
        const normalizedToken = this._normalizeText(token);
        let count = 0;
        let startIdx = 0;

        while (count <= tokenIndex) {
            const idx = normalized.indexOf(normalizedToken, startIdx);
            if (idx === -1) break;
            if (count === tokenIndex) {
                return [idx, idx + normalizedToken.length];
            }
            startIdx = idx + 1;
            count++;
        }

        return [0, 0];
    }

    /**
     * 조사 제거
     */
    _removeParticles(text) {
        let cleaned = text;
        for (const particle of this.koreanParticles) {
            // "7배수의" → "7배수"
            const pattern = new RegExp(`([^\\s])${particle}([\\s,.]|$)`, 'g');
            cleaned = cleaned.replace(pattern, '$1$2');
        }
        return cleaned;
    }

    /**
     * 토큰화 (띄어쓰기 + 특수문자 분리)
     */
    _tokenize(text) {
        // "7과 8의 배수" → ["7의 배수", "8의 배수", "7", "8", "배수", ...]
        // 복합 패턴 확장
        let expanded = text;

        // "N과 M의 X" → "N의 X", "M의 X" 추가
        const pattern = /(\d+)과\s*(\d+)의\s*(\S+)/g;
        const matches = [...text.matchAll(pattern)];
        for (const match of matches) {
            const [, n1, n2, suffix] = match;
            expanded += ` ${n1}의 ${suffix} ${n2}의 ${suffix}`;
        }

        // 한글 숫자 버전도 처리 ("칠과 팔의 배수")
        const koreanPattern = /(일|이|삼|사|오|육|칠|팔|구|십|하나|둘|셋|넷|다섯|여섯|일곱|여덟|아홉|열)과\s*(일|이|삼|사|오|육|칠|팔|구|십|하나|둘|셋|넷|다섯|여섯|일곱|여덟|아홉|열)의\s*(\S+)/g;
        const koreanMatches = [...text.matchAll(koreanPattern)];
        for (const match of koreanMatches) {
            const [, n1, n2, suffix] = match;
            expanded += ` ${n1}의 ${suffix} ${n2}의 ${suffix}`;
        }

        // 숫자+단위 보존 (예: "7배수", "50회")
        return expanded
            .replace(/([,;.])/g, ' $1 ')
            .split(/\s+/)
            .filter(t => t.length > 0);
    }

    /**
     * 숫자 추출 (아라비아 + 한글)
     */
    _extractNumbers(text) {
        const numbers = [];

        // 아라비아 숫자
        const arabicPattern = /\d+/g;
        let match;
        while ((match = arabicPattern.exec(text)) !== null) {
            numbers.push({
                value: parseInt(match[0]),
                span: [match.index, match.index + match[0].length],
                type: 'arabic'
            });
        }

        // 한글 숫자 ("칠배수", "셋배수")
        for (const [korean, value] of Object.entries(this.koreanNumbers)) {
            const index = text.indexOf(korean);
            if (index !== -1) {
                numbers.push({
                    value,
                    span: [index, index + korean.length],
                    type: 'korean'
                });
            }
        }

        return numbers;
    }

    /**
     * Intent 분류
     */
    _classifyIntent(matches, text) {
        const filterCount = matches.filters.length;
        const modelCount = matches.models.length;
        const opCount = matches.operations.length;
        const statCount = matches.statistics.length;
        const timeCount = matches.time_windows.length;

        // 회귀 쿼리 (패턴 개선)
        const hasRegression = /회귀|regression|\d+회차|회차.*분석/.test(text);

        // 규칙 기반 분류 (우선순위 순)

        // 1. 필터 조합 (2개 이상 필터 + 연산자)
        if (filterCount >= 2 && opCount >= 1) {
            return { intent: 'filter_combination', confidence: 0.95 };
        }

        // 2. 회귀 분석
        if (hasRegression) {
            return { intent: 'regression_query', confidence: 0.9 };
        }

        // 3. 모델 쿼리 (모델 있고, 필터가 없거나 적음)
        if (modelCount >= 1 && filterCount <= 2) {
            // "추천", "예측" 키워드 있으면 신뢰도 높임
            const hasRecommend = /추천|예측|번호|선택/.test(text);
            return {
                intent: 'model_query',
                confidence: hasRecommend ? 0.9 : 0.75
            };
        }

        // 4. 통계 쿼리 (통계 + 시간창 또는 필터)
        if (statCount > 0 && (timeCount > 0 || filterCount > 0 || modelCount > 0)) {
            return { intent: 'statistics_query', confidence: 0.8 };
        }

        // 5. 필터 쿼리 (단일 필터)
        if (filterCount === 1 && opCount === 0 && modelCount === 0) {
            return { intent: 'filter_query', confidence: 0.7 };
        }

        // 6. 시간 범위 쿼리
        if (timeCount > 0 && filterCount === 0 && modelCount === 0) {
            return { intent: 'time_range_query', confidence: 0.7 };
        }

        // 7. Unknown (매칭된 항목이 너무 적음)
        const totalMatches = filterCount + modelCount + opCount + statCount + timeCount;
        if (totalMatches === 0) {
            return { intent: 'unknown', confidence: 0.0 };
        }

        return { intent: 'mixed_query', confidence: 0.5 };
    }

    /**
     * Levenshtein Distance (편집 거리)
     */
    _levenshteinDistance(a, b) {
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

    /**
     * 한글 여부 확인
     */
    _isKorean(text) {
        return /[ㄱ-ㅎ|ㅏ-ㅣ|가-힣]/.test(text);
    }

    /**
     * 한글 자모 분리 유사도
     */
    _hangulSimilarity(a, b) {
        const jamo1 = this._decomposeHangul(a);
        const jamo2 = this._decomposeHangul(b);

        const maxLen = Math.max(jamo1.length, jamo2.length);
        if (maxLen === 0) return 0;

        let matches = 0;
        for (let i = 0; i < Math.min(jamo1.length, jamo2.length); i++) {
            if (jamo1[i] === jamo2[i]) matches++;
        }

        return matches / maxLen;
    }

    /**
     * 한글 자모 분리
     * 예: "엑" → ['ㅇ', 'ㅔ', 'ㄱ']
     */
    _decomposeHangul(text) {
        const cho = ['ㄱ', 'ㄲ', 'ㄴ', 'ㄷ', 'ㄸ', 'ㄹ', 'ㅁ', 'ㅂ', 'ㅃ', 'ㅅ', 'ㅆ', 'ㅇ', 'ㅈ', 'ㅉ', 'ㅊ', 'ㅋ', 'ㅌ', 'ㅍ', 'ㅎ'];
        const jung = ['ㅏ', 'ㅐ', 'ㅑ', 'ㅒ', 'ㅓ', 'ㅔ', 'ㅕ', 'ㅖ', 'ㅗ', 'ㅘ', 'ㅙ', 'ㅚ', 'ㅛ', 'ㅜ', 'ㅝ', 'ㅞ', 'ㅟ', 'ㅠ', 'ㅡ', 'ㅢ', 'ㅣ'];
        const jong = ['', 'ㄱ', 'ㄲ', 'ㄳ', 'ㄴ', 'ㄵ', 'ㄶ', 'ㄷ', 'ㄹ', 'ㄺ', 'ㄻ', 'ㄼ', 'ㄽ', 'ㄾ', 'ㄿ', 'ㅀ', 'ㅁ', 'ㅂ', 'ㅄ', 'ㅅ', 'ㅆ', 'ㅇ', 'ㅈ', 'ㅊ', 'ㅋ', 'ㅌ', 'ㅍ', 'ㅎ'];

        const result = [];

        for (let i = 0; i < text.length; i++) {
            const code = text.charCodeAt(i);

            // 완성형 한글 범위 (가 = 0xAC00, 힣 = 0xD7A3)
            if (code >= 0xAC00 && code <= 0xD7A3) {
                const base = code - 0xAC00;
                const choIdx = Math.floor(base / 588);
                const jungIdx = Math.floor((base % 588) / 28);
                const jongIdx = base % 28;

                result.push(cho[choIdx]);
                result.push(jung[jungIdx]);
                if (jong[jongIdx]) result.push(jong[jongIdx]);
            } else {
                // 한글 외 문자는 그대로
                result.push(text[i]);
            }
        }

        return result;
    }

    /**
     * 통계 정보
     */
    stats() {
        if (!this.loaded) return null;

        return {
            version: this.vocabulary.version,
            generated_at: this.vocabulary.generated_at,
            filters: this.vocabulary.filters.length,
            models: this.vocabulary.models.length,
            operations: this.vocabulary.operations.length,
            statistics: this.vocabulary.statistics.length,
            time_windows: this.vocabulary.time_windows.length,
            total_aliases: this.aliasIndex.size
        };
    }
}

// Singleton + window 노출
if (typeof window !== 'undefined') {
    window.AutoNLPMatcher = AutoNLPMatcher;
    window.autoNLP = null; // auto_nlp_loader.js에서 초기화
}

// Node.js export (테스트용)
if (typeof module !== 'undefined' && module.exports) {
    module.exports = AutoNLPMatcher;
}
