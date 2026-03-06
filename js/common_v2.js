// ==========================================
// Lotto AI Common Utilities v2.0
// Fixed: Duplicate Header Removed & Better Error Handling
// ==========================================

// 중복 로드 방지 가드
if (window._COMMON_V2_LOADED) {
    console.log('ℹ️ common_v2.js already loaded, skipping duplicate');
} else {
    window._COMMON_V2_LOADED = true;

    // ==========================================
    // 1. Supabase Client Initialization
    // ==========================================
    const SUPABASE_CONFIG = {
        URL: window.CONFIG ? window.CONFIG.SUPABASE.URL : '',
        KEY: window.CONFIG ? window.CONFIG.SUPABASE.KEY : ''
    };

    window.supabaseClient = null;

    if (typeof supabase !== 'undefined') {
        window.supabaseClient = supabase.createClient(SUPABASE_CONFIG.URL, SUPABASE_CONFIG.KEY);
        console.log('✅ Supabase Client initialized');
    } else {
        console.warn('⚠️ Supabase SDK not loaded');
    }

    // ==========================================
    // 2. Lotto Constants
    // ==========================================
    window.LOTTO_CONSTANTS = {
        COLORS: {
            P10: '#FBC400',
            P20: '#69C8F2',
            P30: '#FF7272',
            P40: '#AAAAAA',
            P45: '#B0D840'
        },
        MULTIPLES: {
            '3배수': [3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36, 39, 42, 45],
            '4배수': [4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44],
            '5배수': [5, 10, 15, 20, 25, 30, 35, 40, 45]
        },

        // [New] 표준 번호 그룹 정의 (백엔드와 동기화)
        GROUPS: {
            '소수': [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43],
            '제곱수': [1, 4, 9, 16, 25, 36],
            '삼각수': [1, 3, 6, 10, 15, 21, 28, 36, 45],
            '쌍수': [11, 22, 33, 44],
            '트윈': [11, 22, 33, 44],
            '동형수': [12, 21, 13, 31, 14, 41, 23, 32, 34, 43],
            '피보나치': [1, 2, 3, 5, 8, 13, 21, 34],
            '홀수': [1, 3, 5, 7, 9, 11, 13, 15, 17, 19, 21, 23, 25, 27, 29, 31, 33, 35, 37, 39, 41, 43, 45],
            '짝수': [2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30, 32, 34, 36, 38, 40, 42, 44]
        },

        // [New] 안전한 수식 계산기 (AI Custom Analysis용)
        // 'x' 변수를 사용하여 수식 계산 (예: "x + 1", "(x * 2) % 45")
        safeMathEval: function (expression, x) {
            try {
                // 허용된 문자만 정규식으로 필터링 (보안상 매우 중요)
                // 숫자, x, +, -, *, /, %, (, ), 공백 만 허용
                if (/[^0-9x\+\-\*\/\%\(\)\s\.]/.test(expression)) {
                    console.warn("Invalid characters in expression:", expression);
                    return x;
                }

                // 단순 replace 후 Function 생성자 사용 (샌드박스 환경이 없으므로 제한적 허용)
                // 실제 구현 시에는 math.js 같은 라이브러리를 쓰는 것이 좋음.
                // 여기서는 간단한 사칙연산만 지원한다고 가정.
                const fn = new Function('x', `return ${expression}`);
                return fn(x);
            } catch (e) {
                console.error("Math Eval Error:", e);
                return x;
            }
        },

        // [New] 로또 필터 적용
        applyLottoFilters: function (numbers, filters) {
            if (!filters || !Array.isArray(filters)) return numbers;

            return numbers.filter(n => {
                let pass = true;
                filters.forEach(f => {
                    if (f === 'odd' && n % 2 === 0) pass = false;
                    if (f === 'even' && n % 2 !== 0) pass = false;
                    if (f === 'prime' && ![2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43].includes(n)) pass = false;
                    if (f === 'exclude_multiples_of_3' && n % 3 === 0) pass = false;
                    if (f === 'multiple_of_3' && n % 3 !== 0) pass = false;
                    if (f === 'under_23' && n >= 23) pass = false;
                    if (f === 'over_23' && n <= 23) pass = false;
                });
                return pass;
            });
        },

        /**
         * 커스텀 분석 대상번호 계산 통합 함수
         * 최신 로직 (회차 끝수 등) 반영 및 시스템 전체 동기화용
         * @param {Object} custom - ai_custom_analyses 레코드 객체
         * @param {Array} allDraws - 정렬된 전체 회차 데이터 (최신순)
         * @param {Object} options - { isPrediction: boolean } (대시보드/필터링 등 예측 모드 여부)
         */
        calculateCustomTargets: function (custom, allDraws, options = {}) {
            if (!custom) return [];
            let type = custom.type || 'static';
            let targetNums = typeof custom.target_numbers === 'string' ? JSON.parse(custom.target_numbers) : (custom.target_numbers || []);
            let rules = typeof custom.rules === 'string' ? JSON.parse(custom.rules) : (custom.rules || {});

            // [Bugfix] config 컬럼이 없을 경우 rules.config에서 복구
            let config = custom.config;
            if (typeof config === 'string') config = JSON.parse(config);
            if (!config && rules.config) config = rules.config;
            if (!config) config = {};

            if (type === 'group' || type === 'regression_overlap') {
                const groups = config.groups || [];
                return [...new Set(groups.flatMap(g => g.numbers))].sort((a, b) => a - b).filter(n => n !== null);
            }

            if (type === 'dynamic') {
                if (!allDraws || allDraws.length === 0) return [];

                let formula = rules.formula || 'prev_plus_n';
                let val = (rules.value !== undefined && rules.value !== null && rules.value !== '') ? Number(rules.value) : 1;
                if (isNaN(val)) val = 1;
                const expression = rules.expression;
                const filters = rules.filters || [];
                const title = custom.title || '';

                // [Fix] Hotfix/Legacy 호환성 (제목 기반 보정 등)
                const simplifiedTitle = title.replace(/\s/g, '');
                if ((!rules.formula || rules.formula === 'carryover') && simplifiedTitle.includes('+1')) {
                    formula = 'prev_plus_n';
                    val = 1;
                }
                if (custom.id === '855cefc4-7b76-4f24-b6b8-2a965c89f30b') {
                    formula = 'prev_plus_n';
                    val = 1;
                }

                const step = parseInt(rules.regression_step || 1);
                const targetDraw = allDraws[step - 1]; // draws[0]이 최신 회차
                if (!targetDraw) return [];

                // [Fix] Metadata shift: 끝수나 날짜 분석은 '해당 회차' 자체의 속성을 보려는 경우가 많음.
                // 1회귀 번호 기반(이월수)은 draws[0](전회차)을 보지만, 
                // 1회귀 회차끝수는 대시보드에서 '이번에 올 회차'의 끝수를 의미하고 싶어함.
                // 따라서 metadata formula들은 isPrediction 모드 시 한 단계 앞의 데이터를 참조하거나 생성함.

                let baseDate = targetDraw.date;
                let baseRound = targetDraw.round;
                const isPrediction = options.isPrediction === true;

                // 1. 끝수 분석 (날짜 기준/회차 기준)
                if (formula === 'draw_date_end') {
                    if (isPrediction && step === 1) {
                        // 대시보드에서 1회귀 날짜끝수 = 다음 토요일
                        const d = new Date(baseDate);
                        d.setDate(d.getDate() + 7);
                        const digit = d.getDate() % 10;
                        let targets = [];
                        const start = (digit === 0) ? 10 : digit;
                        for (let n = start; n <= 45; n += 10) targets.push(n);
                        return targets;
                    }
                    if (!baseDate) return [];
                    const d = new Date(baseDate);
                    if (isNaN(d.getTime())) return [];
                    const digit = d.getDate() % 10;
                    let targets = [];
                    const start = (digit === 0) ? 10 : digit;
                    for (let n = start; n <= 45; n += 10) targets.push(n);
                    return targets;
                }

                if (formula === 'round_end_digit') {
                    // [Fix] value가 명시적으로 없으면 0으로 오프셋을 처리
                    let offset = (rules.value !== undefined && rules.value !== null && rules.value !== '') ? Number(rules.value) : 0;
                    if (isPrediction && step === 1) {
                        // 대시보드에서 1회귀 회차끝수 = 다음 회차 (1102 -> 1103) + 오프셋
                        const digit = (Number(baseRound) + 1 + offset) % 10;
                        let targets = [];
                        const start = (digit === 0) ? 10 : digit;
                        for (let n = start; n <= 45; n += 10) targets.push(n);
                        return targets;
                    }
                    if (!baseRound) return [];
                    const digit = (Number(baseRound) + offset) % 10;
                    let targets = [];
                    const start = (digit === 0) ? 10 : digit;
                    for (let n = start; n <= 45; n += 10) targets.push(n);
                    return targets;
                }

                // 2. 날짜 수학 분석
                if (formula === 'draw_date_math') {
                    let d;
                    if (isPrediction && step === 1) {
                        d = new Date(baseDate);
                        d.setDate(d.getDate() + 7);
                    } else {
                        if (!baseDate) return [];
                        d = new Date(baseDate);
                    }
                    if (isNaN(d.getTime())) return [];
                    const year = d.getFullYear(), month = d.getMonth() + 1, day = d.getDate();
                    const components = [Math.floor(year / 100), year % 100, month, day];
                    let results = new Set();
                    components.forEach(c => { if (c >= 1 && c <= 45) results.add(c); });
                    for (let i = 0; i < components.length; i++) {
                        for (let j = 0; j < components.length; j++) {
                            if (i === j) continue;
                            const a = components[i], b = components[j];
                            [a + b, Math.abs(a - b), a * b, Math.floor(a / b), Math.floor(b / a)].forEach(v => {
                                if (v >= 1 && v <= 45) results.add(v);
                            });
                        }
                    }
                    return Array.from(results).sort((a, b) => a - b);
                }

                // 3. 번호 기반 분석 (Carryover, Plus/Minus, Expression)
                const sourceNumbers = (targetDraw.numbers || []).map(Number);
                let calculatedTargets = [];

                if (formula === 'math_expression' && expression && this.safeMathEval) {
                    calculatedTargets = sourceNumbers.map(n => {
                        let nextNum = Math.round(Number(this.safeMathEval(expression, n)));
                        while (nextNum > 45) nextNum -= 45;
                        while (nextNum < 1) nextNum += 45;
                        return nextNum;
                    });
                } else if (formula === 'carryover') {
                    calculatedTargets = [...sourceNumbers];
                } else {
                    calculatedTargets = sourceNumbers.map(n => {
                        let nextNum = (formula === 'prev_plus_n') ? n + val : n - val;
                        while (nextNum > 45) nextNum -= 45;
                        while (nextNum < 1) nextNum += 45;
                        return nextNum;
                    });
                }

                // 4. 필터 적용
                if (filters && filters.length > 0 && this.applyLottoFilters) {
                    calculatedTargets = this.applyLottoFilters(calculatedTargets, filters);
                }

                return [...new Set(calculatedTargets)].sort((a, b) => a - b);
            }

            return targetNums;
        },

        getBallColor: function (num) {
            // 1~10: 노랑 (#fbc400)
            // 11~20: 파랑 (#69c8f2)
            // 21~30: 빨강 (#ff7272)
            // 31~40: 회색 (#aaaaaa)
            // 41~45: 초록 (#b0d840)
            const n = parseInt(num);
            if (n <= 10) return '#fbc400';
            if (n <= 20) return '#69c8f2';
            if (n <= 30) return '#ff7272';
            if (n <= 40) return '#aaaaaa';
            return '#b0d840';
        }
    };

    // ==========================================
    // 3. AI Analysis Utilities
    // ==========================================
    window.AIAnalysis = {

        extractFirstJsonObject: function (text) {
            if (!text) return null;
            const start = text.indexOf('{');
            if (start === -1) return null;

            let depth = 0;
            let inString = false;
            let escape = false;

            for (let i = start; i < text.length; i++) {
                const ch = text[i];

                if (inString) {
                    if (escape) {
                        escape = false;
                    } else if (ch === '\\') {
                        escape = true;
                    } else if (ch === '"') {
                        inString = false;
                    }
                    continue;
                }

                if (ch === '"') {
                    inString = true;
                    continue;
                }

                if (ch === '{') depth++;
                if (ch === '}') {
                    depth--;
                    if (depth === 0) return text.slice(start, i + 1);
                }
            }

            return null;
        },

        parseLooseTriple: function (text) {
            if (!text) return null;

            const getValue = function (key) {
                const re = new RegExp('"' + key + '"\\s*:\\s*"((?:[^"\\\\]|\\\\.)*)"');
                const match = text.match(re);
                if (!match) return null;
                return match[1]
                    .replace(/\\\\n/g, '\n')
                    .replace(/\\"/g, '"')
                    .replace(/\\\\/g, '\\');
            };

            const trend = getValue('trend');
            const pattern = getValue('pattern');
            const recommendation = getValue('recommendation');

            if (trend || pattern || recommendation) {
                return {
                    trend: trend || '',
                    pattern: pattern || '',
                    recommendation: recommendation || ''
                };
            }

            return null;
        },

        formatText: function (text, mode) {
            mode = mode || 'light';
            if (!text) return '분석 대기 중...';

            // 1. 기본 마크다운/줄바꿈 처리
            var result = text
                .replace(/\*\*(.*?)\*\*/g, '<strong class="font-bold text-gray-900">$1</strong>')
                .replace(/\n/g, '<br>');

            // 2. 태그 색상 정의
            const tagColors = {
                range: mode === 'light' ? 'text-pink-600' : 'text-pink-300',
                good: mode === 'light' ? 'text-blue-600' : 'text-blue-300',
                warn: mode === 'light' ? 'text-red-600' : 'text-red-300',
                pattern: mode === 'light' ? 'text-purple-600' : 'text-purple-300',
                recommendation: mode === 'light' ? 'text-indigo-600' : 'text-indigo-300',
                trend: mode === 'light' ? 'text-teal-600' : 'text-teal-300',
                highlight: mode === 'light' ? 'text-orange-600' : 'text-orange-300'
            };

            // 3. 다이나믹 태그 처리 {{key:value}} -> <span class="...">value</span>
            result = result.replace(/\{\{([a-zA-Z0-9_]+):(.*?)\}\}/g, function (match, key, value) {
                const colorClass = tagColors[key] || (mode === 'light' ? 'text-blue-600' : 'text-blue-300');
                return `<span class="${colorClass} font-bold">${value}</span>`;
            });

            // 4. 단일 태그 처리 {value} -> value (불필요한 강조 제거)
            result = result.replace(/\{([^{}]+)\}/g, '$1');

            // 5. 로또 번호 (1~45번) 자동 색상 배지 적용
            result = result.replace(/(?<!\d)([1-9]|[1-3][0-9]|4[0-5])번/g, function (match, numStr) {
                const num = parseInt(numStr, 10);
                let colorClass = "bg-emerald-500 border-emerald-600";
                if (num <= 10) colorClass = "bg-amber-400 border-amber-500";
                else if (num <= 20) colorClass = "bg-blue-500 border-blue-600";
                else if (num <= 30) colorClass = "bg-rose-500 border-rose-600";
                else if (num <= 40) colorClass = "bg-slate-500 border-slate-600";
                return `<span class="inline-flex items-center justify-center w-[22px] h-[22px] rounded-full text-[11px] font-black text-white shadow-sm border mx-[2px] ${colorClass}">${num}</span><span class="font-bold text-gray-700">번</span>`;
            });

            if (mode === 'dark') {
                result = result.replace(/text-gray-900/g, 'text-white');
            }

            return result;
        },

        getLoadingUI: function (targetRound, analysisType) {
            analysisType = analysisType || '로또';
            return `
            <div class="flex items-center justify-center py-16">
                <div class="text-center space-y-4">
                    <div class="relative inline-block">
                        <div class="w-12 h-12 border-3 border-blue-200 border-t-blue-600 rounded-full animate-spin"></div>
                        <div class="absolute inset-0 flex items-center justify-center">
                            <span class="material-symbols-outlined text-blue-600 text-sm">psychology</span>
                        </div>
                    </div>
                    <div class="space-y-1">
                        <p class="text-sm font-semibold text-gray-900">${targetRound}회차 ${analysisType} 분석 중</p>
                        <p class="text-xs text-gray-500">AI가 최신 데이터를 분석하고 있습니다</p>
                    </div>
                </div>
            </div>`;
        },

        getErrorUI: function (error, retryFn) {
            retryFn = retryFn || 'refreshAIAnalysis';
            // 에러 메시지 분석
            var errorMsg = typeof error === 'string' ? error : (error.message || '알 수 없는 오류');
            var isQuotaError = errorMsg.includes('Quota') || errorMsg.includes('overloaded') || errorMsg.includes('503');

            var userMessage = isQuotaError
                ? '사용자가 많아 AI가 잠시 바쁩니다.<br>잠시 후 다시 시도해주세요.'
                : '일시적인 오류가 발생했습니다.<br>다시 시도해주세요.';

            return `
            <div class="flex items-center justify-center py-12">
                <div class="text-center space-y-4 max-w-sm">
                    <div class="w-12 h-12 bg-red-50 rounded-full flex items-center justify-center mx-auto">
                        <span class="material-symbols-outlined text-red-600 text-2xl">error</span>
                    </div>
                    <div class="space-y-2">
                        <p class="text-sm font-semibold text-gray-900">분석 연결 실패</p>
                        <p class="text-xs text-gray-600 leading-relaxed">${userMessage}</p>
                        <p class="text-[10px] text-gray-400 mt-1">${errorMsg.substring(0, 50)}...</p>
                    </div>
                    <button 
                        onclick="${retryFn}()" 
                        class="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition-colors shadow-sm mt-2">
                        다시 시도
                    </button>
                </div>
            </div>`;
        },

        renderAnalysis: function (analysis, targetRound, subjectRound, renderType) {
            var self = this;
            var formatText = function (text) { return self.formatText(text, 'light'); };
            var formatTextDark = function (text) { return self.formatText(text, 'dark'); };

            // 🔹 [Modified] Minimal Rendering for Chat (No Card Wrapper)
            if (renderType === 'minimal') {
                const content = analysis.response || analysis.recommendation || JSON.stringify(analysis);
                let html = `<div class="text-base leading-relaxed text-gray-900 font-medium">${formatText(content)}</div>`;

                // Add filter recommendations if present
                if (analysis.filter_recommendations && analysis.filter_recommendations.length > 0) {
                    const iconMap = {
                        '총합': 'functions', '끝수합': 'pin', 'AC값': 'calculate',
                        '홀짝': 'contrast', '저고': 'swap_vert', '연속수': 'linear_scale',
                        '이월수': 'replay', '소수': 'looks_one', '합성수': 'looks_two',
                        '제곱수': 'crop_square', '삼각수': 'change_history', '쌍둥이수': 'group',
                        '핫콜드': 'local_fire_department', '범위': 'expand',
                        '최근 10회 출현': 'history', '장기 미출현': 'hourglass_empty',
                        '3의 배수': 'view_week', '이웃수': 'people_alt'
                    };
                    const filterHtml = analysis.filter_recommendations.map(function (r) {
                        const icon = iconMap[r.filter] || 'tune';
                        const valueText = r.pattern ? '패턴: ' + r.pattern : (r.min !== undefined && r.max !== undefined) ? r.min + ' ~ ' + r.max : r.max !== undefined ? '최대 ' + r.max : '-';
                        return `<div class="bg-blue-50/50 rounded-xl border border-blue-100 p-3 hover:border-blue-300 transition-colors">
                            <div class="flex items-center gap-2 mb-2"><span class="material-symbols-outlined text-blue-500 text-base">${icon}</span><h4 class="font-bold text-gray-800 text-xs">${r.filter}</h4></div>
                            <p class="text-blue-700 font-black text-sm mb-1.5">${valueText}</p>
                            <div class="bg-white p-2 rounded text-[11px] text-gray-600 leading-snug border border-blue-50/50">${r.evidence || '근거 데이터 없음'}</div></div>`;
                    }).join('');
                    html += `<div class="mt-4 pt-4 border-t border-gray-100"><h5 class="text-sm font-bold text-gray-800 mb-3 flex items-center gap-1.5"><span class="material-symbols-outlined text-blue-500 text-lg">tune</span>AI 필터 추천 구간</h5><div class="grid grid-cols-2 lg:grid-cols-4 gap-3">${filterHtml}</div></div>`;
                }
                return html;
            }

            // 🔹 [Modified] 단순 응답 모드 (response 필드가 있거나 trend 필드가 없는 경우)
            if (analysis.response || (!analysis.trend && analysis.recommendation)) {
                const content = analysis.response || analysis.recommendation;
                let html = `
                <div class="rounded-xl p-6 shadow-lg bg-gray-900 text-white animate-fade-in">
                    <div class="flex items-center gap-3 mb-4 border-b border-gray-700 pb-3">
                        <div class="p-1.5 bg-blue-600 rounded-lg">
                            <span class="material-symbols-outlined text-white text-lg">psychology</span>
                        </div>
                        <h5 class="text-lg font-bold text-white">AI 분석 결과</h5>
                    </div>
                    <div class="text-base leading-7 text-gray-100 font-medium">
                        ${formatTextDark(content)}
                    </div>`;

                // Add filter recommendations in Dark Mode format
                if (analysis.filter_recommendations && analysis.filter_recommendations.length > 0) {
                    const iconMap = {
                        '총합': 'functions', '끝수합': 'pin', 'AC값': 'calculate',
                        '홀짝': 'contrast', '저고': 'swap_vert', '연속수': 'linear_scale',
                        '이월수': 'replay', '소수': 'looks_one', '합성수': 'looks_two',
                        '제곱수': 'crop_square', '삼각수': 'change_history', '쌍둥이수': 'group',
                        '핫콜드': 'local_fire_department', '범위': 'expand',
                        '최근 10회 출현': 'history', '장기 미출현': 'hourglass_empty',
                        '3의 배수': 'view_week', '이웃수': 'people_alt'
                    };
                    const filterHtml = analysis.filter_recommendations.map(function (r) {
                        const icon = iconMap[r.filter] || 'tune';
                        const valueText = r.pattern ? '패턴: ' + r.pattern : (r.min !== undefined && r.max !== undefined) ? r.min + ' ~ ' + r.max : r.max !== undefined ? '최대 ' + r.max : '-';
                        return `<div class="bg-gray-800 rounded-xl border border-gray-700 p-3 hover:border-blue-500 transition-colors">
                            <div class="flex items-center gap-2 mb-2"><span class="material-symbols-outlined text-blue-400 text-base">${icon}</span><h4 class="font-bold text-gray-200 text-xs">${r.filter}</h4></div>
                            <p class="text-blue-300 font-black text-sm mb-1.5">${valueText}</p>
                            <div class="bg-gray-900 p-2 rounded text-[11px] text-gray-400 leading-snug border border-gray-800">${r.evidence || '근거 데이터 없음'}</div></div>`;
                    }).join('');
                    html += `<div class="mt-5 pt-5 border-t border-gray-700"><h5 class="text-sm font-bold text-gray-200 mb-3 flex items-center gap-1.5"><span class="material-symbols-outlined text-blue-400 text-lg">tune</span>AI 필터 추천 구간</h5><div class="grid grid-cols-2 lg:grid-cols-4 gap-3">${filterHtml}</div></div>`;
                }

                html += `</div>`;
                return html;
            }

            // 🔹 기존 3단 구성 리포트
            return `
            <div class="space-y-6 animate-fade-in">
                
                <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                    
                    <div class="space-y-3">
                        <div class="flex items-center gap-2">
                            <span class="material-symbols-outlined text-blue-600 text-2xl">trending_up</span>
                            <h5 class="text-base font-semibold text-gray-900">흐름 진단</h5>
                        </div>
                        <div class="text-base text-gray-900 leading-relaxed pl-8">
                            ${formatText(analysis.trend)}
                        </div>
                    </div>
                    
                    <div class="space-y-3">
                        <div class="flex items-center gap-2">
                            <span class="material-symbols-outlined text-purple-600 text-2xl">analytics</span>
                            <h5 class="text-base font-semibold text-gray-900">패턴 분석</h5>
                        </div>
                        <div class="text-base text-gray-900 leading-relaxed pl-8">
                            ${formatText(analysis.pattern)}
                        </div>
                    </div>
                    
                </div>

                <div class="mt-6 rounded-xl p-6 shadow-lg" style="background: linear-gradient(135deg, #1F2937 0%, #111827 100%);">
                    <div class="flex items-center gap-2 mb-4">
                        <span class="material-symbols-outlined text-white text-2xl">star</span>
                        <h5 class="text-base font-semibold text-white">${targetRound}회차 필승 공략</h5>
                    </div>
                    <div class="text-base text-gray-100 leading-relaxed pl-8">
                        ${formatTextDark(analysis.recommendation)}
                    </div>
                </div>
                
            </div>`;
        },

        generatePrompt: function (config) {
            var analysisType = config.analysisType || '';
            var subjectRound = config.subjectRound || 0;
            var targetRound = config.targetRound || 0;
            var customData = config.customData || config.contextData || '';
            var customRules = config.customRules || '';

            if (config.responseStyle === 'simple') {
                return `
# Role: 대한민국 로또 분석 권위자 (${analysisType} 전문)
# Task: ${subjectRound}회차 실측 데이터를 분석하여, 차기 **${targetRound}회차**를 예측하라.

${customData}

${customRules}

# [절대 금지 표현]
에너지, 기운, 파동, 운세, 소액 투자, 분산 투자, 고액 투자 지양, 투자 전략, 100% 보장은 없다, 참고용, 책임지지 않습니다, 재미로, 행운을 빕니다, 당첨을 기원, 감이 좋다, 직감, 필승, 대박

# [출력 규칙]
- 답변은 "흐름 진단", "패턴 분석" 등으로 나누지 말고, **단 하나의 통합된 줄글**로 작성하라.
- 사용자의 질문에 대한 핵심 답변을 서두에 배치하고, 근거를 뒤이어 설명하라.
- 반드시 제공된 데이터의 실제 수치를 인용하라. 제공되지 않은 데이터를 창작하지 마라.
- 답변은 자연스러운 한국어 문장으로만 작성하고, 영어 단어(trend, pattern, recommendation 등)는 쓰지 말며, 단어를 따옴표로 강조하지 마라.
- 오직 순수 JSON 포맷으로만 응답하라.

# [JSON 구조]
{
  "response": "분석 결과 및 추천 전략 (4-5문장의 자연스러운 줄글)"
}`;
            }

            // [New] Chat Style: Single response with Highlight Tags
            if (config.responseStyle === 'chat') {
                return `
# Role: 대한민국 로또 분석 권위자 (${analysisType} 전문)
# Task: ${subjectRound}회차 실측 데이터를 분석하여, 차기 **${targetRound}회차**를 예측하라.

${customData}

${customRules}

# [절대 금지 표현]
에너지, 기운, 파동, 운세, 소액 투자, 분산 투자, 고액 투자 지양, 투자 전략, 100% 보장은 없다, 참고용, 책임지지 않습니다, 재미로, 행운을 빕니다, 당첨을 기원, 감이 좋다, 직감, 필승, 대박

# [출력 규칙]
- 사용자의 질문에 대해 **단 하나의 통합된 줄글**로 자연스럽게 답변하라.
- 반드시 제공된 데이터의 실제 수치를 인용하라. 제공되지 않은 데이터를 창작하지 마라.
- 답변은 자연스러운 한국어 문장으로만 작성하고, 영어 단어(trend, pattern, recommendation 등)는 쓰지 말며, 단어를 따옴표로 강조하지 마라.
- 핵심 숫자는 반드시 태그로 감싸 시각적으로 강조하라:
  - {{good:숫자}} → 추천/긍정 (빨강)
  - {{warn:숫자}} → 제외/주의 (파랑)
  - {{range:텍스트}} → 주요 구간/텍스트 참조
- 오직 순수 JSON 포맷으로만 응답하라.

# [JSON 구조]
{
  "response": "분석 결과 및 답변 (태그 포함, 3-4문장)",
  "filter_recommendations": [
    {"filter": "총합", "min": 100, "max": 180, "evidence": "근거"},
    {"filter": "홀짝", "pattern": "3:3", "evidence": "근거"},
    {"filter": "AC값", "min": 7, "max": 10, "evidence": "근거"}
  ]
}`;
            }

            return `
# Role: 대한민국 로또 분석 권위자 (${analysisType} 전문)
# Task: ${subjectRound}회차 실측 데이터를 분석하여, 차기 **${targetRound}회차**를 예측하라.

${customData}

${customRules}

# [절대 금지 표현]
에너지, 기운, 파동, 운세, 소액 투자, 분산 투자, 고액 투자 지양, 투자 전략, 100% 보장은 없다, 참고용, 책임지지 않습니다, 재미로, 행운을 빕니다, 당첨을 기원, 감이 좋다, 직감, 필승, 대박

# [출력 규칙]
- 반드시 제공된 데이터의 실제 수치를 인용하며 분석하라. 제공되지 않은 데이터를 창작하지 마라.
- 핵심 내용은 다음 태그로 감싸라:
  - {{range:수치/구간}} → 분석 범위나 중요 수치
  - {{good:추천/긍정}} → 추천 사항이나 긍정적 신호
  - {{warn:경고/주의}} → 주의 사항이나 위험 신호
- 답변은 자연스러운 한국어 문장으로만 작성하고, 영어 단어(trend, pattern, recommendation 등)는 쓰지 말며, 단어를 따옴표로 강조하지 마라.
- 오직 순수 JSON 포맷으로만 응답하라.

# [JSON 구조]
{
  "trend": "현재 흐름 및 추세 진단 - 실측 데이터 인용 필수 (2-3문장)",
  "pattern": "통계 패턴 분석 - 수치 근거 기반 (2-3문장)",
  "recommendation": "${targetRound}회차 전략 - 구체적 수치와 근거 포함 (3-4문장)"
}`;
        },

        executeAnalysis: async function (config) {
            var containerId = config.containerId;
            var container = document.getElementById(containerId);
            if (!container) {
                console.error('❌ Container not found: ' + containerId);
                return;
            }

            // 로딩 UI 표시
            if (config.responseStyle === 'chat') {
                container.innerHTML = `
            <div class="flex items-center gap-3 p-2 text-gray-500">
                <div class="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
                <span class="text-xs">AI 분석 중...</span>
            </div>`;
            } else {
                container.innerHTML = this.getLoadingUI(config.targetRound, config.analysisType);
            }

            try {
                // 1. 프롬프트 생성 (기존 로직 유지)
                var prompt = this.generatePrompt(config);
                var analysisData;

                // 2. [핵심 변경] AIProxy가 존재하면(새 방식) 사용, 없으면 기존 방식 사용
                if (window.AIProxy) {
                    console.log("🚀 [Switch] 신규 AI 파이프라인(Python RAG)으로 요청");
                    // AIProxy.invoke는 처리된 결과 데이터를 바로 반환합니다.
                    analysisData = await window.AIProxy.invoke({
                        prompt: prompt,
                        analysisType: config.analysisType,
                        targetRound: config.targetRound,
                        subjectRound: config.subjectRound,
                        responseStyle: config.responseStyle,
                        topic: config.topic || ''
                    });
                } else {
                    console.log("📡 [Fallback] 기존 Edge Function으로 요청 (AIProxy 미감지)");
                    // 기존 30개 페이지는 이 코드를 타게 됩니다.
                    var response = await window.supabaseClient.functions.invoke('analyze-lotto', {
                        body: { context: prompt }
                    });
                    if (response.error) throw response.error;
                    analysisData = response.data;
                }

                // 3. 응답 데이터 정제 (문자열인 경우 JSON 파싱)
                var analysis = analysisData;
                if (typeof analysis === 'string') {
                    // 에러 메시지 체크
                    if (analysis.includes('Error') || analysis.includes('Overloaded') || analysis.includes('오류')) {
                        throw new Error(analysis);
                    }
                    try {
                        analysis = JSON.parse(analysis);
                    } catch (e) {
                        // JSON 파싱 실패 시 추출 시도
                        const extracted = this.extractFirstJsonObject(analysis);
                        if (extracted) {
                            try { analysis = JSON.parse(extracted); } catch (err) { }
                        }

                        // 그래도 실패하면 텍스트 그대로 표시 준비
                        if (typeof analysis === 'string') {
                            const triple = this.parseLooseTriple(analysis);
                            if (triple) analysis = triple;
                        }
                    }
                }

                // 4. 결과 렌더링 (기존 로직 유지)
                var renderType = config.renderType || (config.responseStyle === 'chat' ? 'minimal' : null);
                // [Mod] prose-sm -> prose-base (폰트 크기 증가)
                container.innerHTML = this.renderAnalysis(analysis, config.targetRound, config.subjectRound, renderType).replace('prose-sm', 'prose-base');

            } catch (error) {
                console.error('❌ AI 분석 실패:', error);
                container.innerHTML = this.getErrorUI(error, 'refreshAIAnalysis');
            }
        },

        // 🔹 [Modified] 프롬프트 라이브러리 팝업 오픈 (시인성 강화 및 위치 보정)
        openPromptLibraryModal: function (type, event) {
            const library = {
                'carryover': [
                    { title: '심층 추세 분석', prompt: '최근 100회차 이월수 발생 주기를 분석하여 다음 회차의 발생 확률을 백분율로 산출해줘.' },
                    { title: '멸(0개) 대비 전략', prompt: '이월수가 나오지 않는 회차의 직전 회차 특징을 분석하고, 이번 회차가 그에 해당하는지 판단해줘.' },
                    { title: '특정 번호 추적', prompt: '가장 오래 이월되지 않은 번호와 가장 자주 이월되는 번호를 비교 분석하여 추천 번호를 도출해줘.' }
                ],
                'ac_value': [
                    { title: '표준 편차 기반 예측', prompt: '최근 AC값의 표준 편차와 이동평균을 계산하고, 평균 회귀 법칙에 따라 다음 회차 AC값 예상 구간을 수치와 함께 제시해줘.' },
                    { title: '조합 필터 최적화', prompt: '과거 전체 AC값 분포 데이터를 기반으로, 적중률이 가장 높았던 필터 설정값(Min, Max 구간)을 추천하고 해당 구간의 출현 비율을 알려줘.' },
                    { title: '극단값(0/10) 발생 예측', prompt: 'AC값 0~3 또는 10과 같은 극단적인 수치가 직전에 어떤 패턴을 보였는지 분석하고, 이번 회차에 극단값이 나올 가능성을 수치로 진단해줘.' },
                    { title: '연속 동일값 패턴', prompt: '직전 회차와 동일한 AC값이 반복되는 비율은 얼마인가? 현재 연속 동일값 기록과 과거 최대 연속 동일값을 비교 분석해줘.' },
                    { title: 'AC값 추세 방향 진단', prompt: '최근 5회, 10회, 20회 이동평균을 비교하여 현재 AC값이 상승세인지 하락세인지 구체적 수치로 진단하고, 향후 방향을 예측해줘.' },
                    { title: '구간별(저/중/고) 비율 분석', prompt: 'AC값을 저(0~4), 중(5~8), 고(9~10) 3구간으로 나누어 최근 출현 비율을 계산하고, 다음 회차에 어느 구간이 유력한지 분석해줘.' },
                    { title: '연속 상승/하락 패턴', prompt: '최근 AC값의 연속 상승(또는 하락) 기록을 분석하고, 현재 추세가 반전될 타이밍인지 과거 데이터와 비교하여 판단해줘.' },
                    { title: 'AC값과 당첨번호 상관관계', prompt: 'AC값이 높은 회차(8~10)와 낮은 회차(0~5)에서 당첨번호의 특성(홀짝, 저고, 번호대 분포)이 어떻게 달라지는지 분석해줘.' },
                    { title: '최빈 AC값 주기 분석', prompt: '가장 자주 출현하는 AC값(최빈값)이 무엇이고, 이 값이 나오는 주기는 평균 몇 회차인지, 그리고 현재 몇 회차째 미출현인지 분석해줘.' },
                    { title: '이동평균 교차 시그널', prompt: '5회 이동평균과 10회 이동평균의 교차(골든크로스/데드크로스) 시점을 분석하고, 현재 신호가 무엇인지 판단해줘.' }
                ],
                'composite': [
                    { title: '합성수/소수 밸런스 점검', prompt: '최근 20회차 동안의 합성수와 소수의 출현 비율을 분석하여, 현재 밸런스가 한쪽으로 치우쳐 있는지 진단해줘. (이상적 비율 4:2 또는 3:3)' },
                    { title: '임계치(Threshold) 분석', prompt: '합성수가 5개 이상 또는 1개 이하로 극단적으로 적게 나온 회차의 특징을 분석하고 재발 가능성을 예측해줘.' },
                    { title: '특정 합성수 추적', prompt: '최근 가장 오랫동안 나오지 않은 합성수 목록을 뽑고, 통계적으로 출현 임계점에 도달한 번호를 추천해줘.' },
                    { title: '합성수구간 멸(Zero) 경고', prompt: '특정 합성수 구간(예: 4~20, 21~45)이 전멸할 가능성이 있는지, 과거 멸 구간 패턴을 기반으로 진단해줘.' },
                    { title: '연속 합성수 출현 패턴', prompt: '최근 합성수가 3연속 이상 이어진 패턴(4-6-8 등)이 있었는지 분석하고, 이번 회차에 연속 출현할 가능성을 알려줘.' },
                    { title: '소수 강세/약세 주기', prompt: '현재 시점이 소수가 강세를 보이는 주기인지, 아니면 합성수가 압도하는 주기인지 10회차 평균을 기준으로 판별해줘.' },
                    { title: '합성수 필출 구간 추천', prompt: '다음 회차에 반드시 포함시켜야 할 합성수 구간(단번대, 10번대 등)을 하나만 꼽는다면 어디일까?' },
                    { title: '이월 합성수 분석', prompt: '직전 회차의 합성수들 중, 통계적으로 이번 회차에 다시 이월될 확률이 가장 높은 번호는?' },
                    { title: '3배수 합성수 전략', prompt: '합성수 중에서도 3의 배수(6, 9, 12...)가 차지하는 비중을 분석하고, 이번 회차 추천 개수를 제시해줘.' },
                    { title: '고합성수(40번대) 집중', prompt: '40번대 합성수(40, 42, 44, 45)가 최근 어떻게 출현했는지 분석하고, 이번 회차 필출 여부를 예측해줘.' }
                ],
                'consecutive_number': [
                    { title: '연번 발생 주기 분석', prompt: '최근 연번(Neighbor)이 발생한 회차들 사이의 평균 간격을 계산하고, 이번 회차가 연번이 출현할 타이밍인지 분석해줘.' },
                    { title: '다중 연번 가능성', prompt: '과거 데이터에서 3연번 이상 혹은 연번이 2쌍 이상 발생했을 때의 전조 증상을 분석하고, 이번 회차에 적용해줘.' },
                    { title: '연번 미출현 지속성', prompt: '연번이 오랫동안 나오지 않을 때(0쌍 지속)의 최대 기록을 확인하고, 통계적으로 이번에 나올 확률을 계산해줘.' }
                ],
                'hot_cold': [
                    { title: '과열(Hot) 구간 진단', prompt: '최근 Hot 번호(3회 이상 출현)가 너무 과밀하게 몰려있는지 진단하고, 이번 회차에 몇 개 정도 유지될지 예측해줘.' },
                    { title: '콜드(Cold) 부활 타이밍', prompt: '10회 이상 미출현한 Cold 번호들 중, 최근 주변 번호 출현 패턴을 고려할 때 이번 회차에 당첨 가능성이 높은 번호는 무엇인가?' },
                    { title: '중립(Neutral) 전환 분석', prompt: '현재 중립 구간에 있는 번호들(1~2회 출현) 중 Hot으로 진입할 상승세(Rising) 번호와 Cold로 떨어질 하락세(Falling) 번호를 분류해줘.' }
                ],
                'lotto_paper': [
                    { title: '가로/세로 멸(Zero) 구간 예측', prompt: '최근 10회차의 가로/세로 라인 멸 현황을 분석하고, 이번 회차에 당첨번호가 하나도 안 나올 확률이 가장 높은 라인을 예측해줘.' },
                    { title: '집중(쏠림) 현상 분석', prompt: '특정 라인에 번호가 3개 이상 과도하게 몰리는 "쏠림 현상"의 다음 패턴을 분석하여, 반작용으로 약세가 예상되는 구간을 조언해줘.' },
                    { title: '4분면 & 대각선 패턴', prompt: '용지 전체를 4등분(TOP-LEFT, TOP-RIGHT 등)했을 때의 번호 분포 추세와 대각선 라인의 출현 가능성을 종합적으로 분석해줘.' }
                ],
                'low_high': [
                    { title: '저고 비율 균형 회귀', prompt: '최근 저고 비율이 한쪽으로 쏠렸는지 분석하고, 평균(3:3 또는 4:2)으로의 회귀 가능성을 예측해줘.' },
                    { title: '저번호(Low) 집중 분석', prompt: '1번부터 22번 사이의 번호가 최근 강세인지 약세인지 판단하고, 이번 회차의 출현 예상 개수를 제시해줘.' },
                    { title: '극단적 비율(6:0/0:6) 경고', prompt: '과거 데이터를 바탕으로 극단적인 비율(All Low 또는 All High)이 발생할 가능성이 있는 주기인지 분석해줘.' }
                ],
                'magic_square': [
                    { title: '9궁 패턴 균형 분석', prompt: '최근 5회차의 9궁 패턴 분포를 분석하고, 번호가 집중된 과열 구역과 나오지 않은 소외 구역의 균형이 어떻게 맞춰질지 예측해줘.' },
                    { title: '공멸(0개) 구간 예측', prompt: '9궁 회귀 법칙에 따라 다음 회차에 당첨번호가 하나도 나오지 않을 가능성이 높은 궁(멸 구간)을 2곳 이상 지목하고 이유를 설명해줘.' },
                    { title: '중심(5궁) 집중도 진단', prompt: '중앙에 위치한 5궁(22~26번 등)의 최근 출현 빈도를 분석하여, 이번 회차에 번호가 중앙으로 모일지 외곽으로 분산될지 판단해줘.' }
                ],
                'multiple': [
                    { title: '배수 추천 전략', prompt: '다음 회차에 3배수, 4배수, 5배수 중 어느 그룹에서 당첨번호가 많이 나올까요? 비율을 추천해 주세요.' },
                    { title: '배수 멸(Zero) 구간', prompt: '최근 흐름을 볼 때, 이번 회차에 하나도 안 나올(멸) 가능성이 높은 배수 그룹은 어디인가요?' },
                    { title: '공배수(3·4/3·5) 분석', prompt: '3배수이면서 4배수인 12, 24, 36이나 3배수이면서 5배수인 15, 30, 45가 나올 타이밍인가요?' }
                ],
                'missing_number': [
                    { title: '미출현 번호 추천', prompt: '현재 미출현 기간이 5회 이상인 번호들 중에서, 통계적으로 이번 회차에 나올 가능성이 가장 높은 번호 3개를 추천해줘.' },
                    { title: '장기 미출수 부활 예측', prompt: '10회 이상 장기 미출현 번호들의 최근 패턴을 분석하여, 이번에 "부활"할 가능성이 있는 번호가 있는지 진단해줘.' },
                    { title: '보합 구간(5~10회) 전략', prompt: '미출현 기간이 5~10회 사이인 "보합세" 번호들의 출현 빈도를 분석하고, 이 구간에서 몇 개 정도를 조합에 포함해야 할지 조언해줘.' }
                ],
                'neighbor_number': [
                    { title: '이웃수 출현 주기', prompt: '최근 10회차 동안 이웃수가 2개 이상 나온 주기를 분석해서 이번 회차에 다출할 가능성을 예측해줘.' },
                    { title: '멸(Zero) 가능성 진단', prompt: '이웃수가 연속으로 많이 나왔다면 이번엔 하나도 안 나올(멸) 타이밍일까? 확률적으로 분석해줘.' },
                    { title: '보너스볼 이웃수 전략', prompt: '지난주 보너스볼의 이웃수가 이번 주 당첨번호로 연결될 가능성과 과거 패턴을 설명해줘.' }
                ],
                'number_range': [
                    { title: '번호대 밸런스 분석', prompt: '최근 5회차 번호대별 분포 비율을 분석하고, 이번 회차에 가장 유력한 밸런스 패턴(예: 3:2:1)을 추천해줘.' },
                    { title: '멸(Zero) 구간 예측', prompt: '특정 번호대(단번대, 10번대 등)가 전멸할 가능성이 높은 구간을 통계적 근거와 함께 2곳 이상 지목해줘.' },
                    { title: '과열/침체 구간 진단', prompt: '현재 가장 과열된 번호대와 가장 오랫동안 침체된 번호대를 분석하여, 반전(Reverse) 포인트가 될 구간을 알려줘.' }
                ],
                'prime_number': [
                    { title: '소수 개수 추천', prompt: '다음 회차 소수 추천 개수(0~6개)는?' },
                    { title: '소수 vs 합성수', prompt: '최근 소수가 강세인가, 합성수가 강세인가?' },
                    { title: '소수 전멸 가능성', prompt: '이번에 소수가 전멸(0개)할 가능성은?' },
                    { title: '소수 다출 타이밍', prompt: '소수가 4개 이상 많이 나올(다출) 타이밍인가?' },
                    { title: '핵심 소수 추천', prompt: '가장 자주 나오는 소수 번호 3개만 추천해줘' },
                    { title: '합성수 전략', prompt: '합성수 위주로 조합을 짜는 게 유리할까?' },
                    { title: '이월 소수 여부', prompt: '지난 회차의 소수가 이번에도 나올까요? (이월)' },
                    { title: '소수 최소(1개 이하)', prompt: '소수가 1개 이하로 적게 나올 확률은?' },
                    { title: '보너스 소수 확률', prompt: '보너스 번호가 소수일 확률은?' },
                    { title: '단번대 소수 필출', prompt: '단번대(1~10)에 있는 소수(2,3,5,7) 중 하나가 나올까?' }
                ],
                'regression': [
                    { title: '회귀 패턴 종합 진단', prompt: '현재 선택된 회귀 주기(Step)의 최근 30주기 적중 패턴을 분석하여 다음 회차 출현 가능성을 진단해줘.' },
                    { title: '최적의 회귀 주기 추천', prompt: '과거 100회차 데이터를 기준으로 현재 가장 적중률이 높은 최적의 회귀 주기(Step) 3개를 추천해줘.' },
                    { title: '연속 미출현(Gap) 임계 분석', prompt: '현재의 연속 미출현(Gap) 상태가 과거 최대치와 비교했을 때 어느 정도 위험 수준인지 분석해줘.' },
                    { title: '장기 미출 주기 부활 패턴', prompt: '최근 50회차 동안 거의 나오지 않다가 갑자기 적중하기 시작한 회귀 주기가 있다면 무엇인지 찾아줘.' },
                    { title: '회귀 주기 간 결합 분석', prompt: '현재 주기와 상호보완적인 관계에 있는(한쪽이 안 나올 때 다른 쪽이 잘 나오는) 또 다른 주기를 추천해줘.' },
                    { title: '패턴 붕괴 및 전환 예측', prompt: '현재 잘 맞고 있는 이 주기가 언제쯤 정체기에 접어들지, 패턴 붕괴의 전조 증상이 있는지 분석해줘.' },
                    { title: '회귀 기반 예상수 도출', prompt: '현재 주기의 적중률과 번호 분포를 고려할 때, 이번 회차에 가장 강력하게 추천하는 예상 번호 6개를 뽑아줘.' },
                    { title: '주기별 효율 가성비 진단', prompt: '짧은 주기(2-10회귀)와 긴 주기(50-100회귀) 중 현재 어떤 타입이 더 안정적인 수익 모델인지 비교해줘.' },
                    { title: '특정 번호대 회귀 강세', prompt: '특정 번호대(예: 단번대, 40번대)가 유독 잘 마는 회귀 주기가 따로 있는지 분석해줘.' },
                    { title: '회귀 필터값 최적화 제안', prompt: '현재 주기의 데이터를 바탕으로 적중률 90% 이상을 유지할 수 있는 가장 보수적인 필터 범위(Min/Max)를 제안해줘.' }
                ],
                'odd_even': [
                    { title: '홀짝 밸런스 추천', prompt: '최근 10회차 홀짝 데이터 흐름을 분석하여, 다음 회차에 가장 유력한 홀짝 비율(예: 3:3, 4:2 등)을 추천해 주세요.' },
                    { title: '극단값(6:0/0:6) 경고', prompt: '역대 데이터를 보았을 때, 이번 회차에 홀수 또는 짝수만 나오는 극단적인 패턴(6:0, 0:6)이 나올 가능성이 있나요?' },
                    { title: '홀수/짝수 강세 분석', prompt: '최근 홀수와 짝수 중 어느 쪽이 추세적으로 강세인가요? 이번 회차에 강세를 보일 쪽을 예측하고 이유를 설명해 주세요.' }
                ],
                'stats_by_number': [
                    { title: 'Hot 번호 심층 분석', prompt: '최근 100회차 동안 출현 빈도가 압도적으로 높은 "Hot 번호" 5개를 선정하고, 이들의 최근 출현 주기와 이번 회차 재출현 가능성을 분석해줘.' },
                    { title: 'Cold 번호 부활 타이밍', prompt: '10회 이상 미출현 중인 "장기 미출현(Cold) 번호"들 중 통계적으로 임계점에 도달하여 이번에 부활할 가능성이 가장 높은 번호 3개를 추천해줘.' },
                    { title: '번호대 전멸(Zero) 예측', prompt: '현재 각 번호대별(단번대, 10번대 등) 흐름을 볼 때, 다음 회차에 당첨번호가 하나도 나오지 않을 가능성이 높은 "멸 구간"은 어디인가요?' },
                    { title: '이월수(Carryover) 추적', prompt: '직전 회차 당첨번호 중 이번 회차에 다시 나올 가능성이 높은 이월수 후보를 통계적 근거와 함께 제시해줘.' },
                    { title: '평균 회귀 밸런스 필터', prompt: '최근의 과출현 번호와 미출현 번호 간의 밸런스를 고려할 때, 이번 회차 조합에서 가져가야 할 가장 이상적인 Hot:Cold 비율을 제안해줘.' },
                    { title: '특정 번호대 강세 진단', prompt: '최근 10회차 동안 특정 번호대에 당첨번호가 쏠리는 현상이 있는지 분석하고, 이에 따른 반작용으로 이번에 강세가 예상되는 구간을 알려줘.' },
                    { title: '보너스볼 연결 패턴', prompt: '과거 데이터에서 보너스 번호가 다음 회차의 당첨번호로 연결되었던 사례를 분석하여, 이번 보너스볼 주변수의 출현 확률을 계산해줘.' },
                    { title: '쌍수/연번 빈도 점검', prompt: '현재 번호 통계상 쌍수(11, 22 등)나 연번(12-13 등)이 나올 확률이 높은 타이밍인지 분석하고 추천 번호를 포함해줘.' },
                    { title: '제외수 필터 추천', prompt: '최근 출현 패턴이 매우 불규칙하거나 통계적으로 출현 확률이 가장 낮은 번호 5개를 "제외 예상수"로 분류하고 근거를 설명해줘.' },
                    { title: 'AI 최종 조합 시나리오', prompt: '지금까지의 모든 번호 통계를 종합하여, 가장 확률이 높은 번호 10개를 선별하고 그 조합 비중 전략을 세워줘.' }
                ],
                'square_number': [
                    { title: '제곱수 추천 전략', prompt: '다음 회차 제곱수(1, 4, 9, 16, 25, 36) 중 나올 가능성이 높은 숫자를 추천해줘.' },
                    { title: '최근 추세 진단', prompt: '최근 10회차 동안 제곱수가 나온 빈도와 추세를 분석해서 상승세인지 하락세인지 알려줘.' },
                    { title: '과열 집중 구간', prompt: '최근 제곱수가 2개 이상 집중적으로 나온 구간이 있다면 분석해주고, 이번 회차에 반작용이 있을지 예측해줘.' },
                    { title: '미출현(Cold) 분석', prompt: '오랫동안 나오지 않은 제곱수(Cold)는 무엇이며, 부활할 가능성은 얼마나 될까?' },
                    { title: '전멸(0개) 가능성', prompt: '이번 회차에 제곱수가 하나도 나오지 않을(전멸) 가능성이 있는지 통계적으로 진단해줘.' }
                ],
                'tail_sum': [
                    { title: '끝수합 추세 분석', prompt: '최근 10회차 끝수합의 추세를 분석하고, 다음 회차의 등락 방향을 예측해줘.' },
                    { title: '평균 회귀 진단', prompt: '현재 끝수합이 평균(20~30)에서 얼마나 벗어났는지 분석하고 회귀 가능성을 진단해줘.' },
                    { title: '과열/침체 구간', prompt: '끝수합이 매우 높거나 낮은 구간이 지속되고 있는지 확인하고, 반작용 가능성을 알려줘.' },
                    { title: '구간별 패턴 분석', prompt: '최근 끝수합이 주로 어느 구간(10대, 20대, 30대 등)에 머물렀는지 분석하고 추천 구간을 제시해줘.' }
                ],
                'tail_digit': [
                    { title: '기본 분석: 끝수 추천', prompt: '다음 회차 끝수 추천해줘' },
                    { title: '기본 분석: 최근 패턴', prompt: '최근 10회 끝수 패턴 분석해줘' },
                    { title: '기본 분석: 이월 끝수', prompt: '이월된 끝수와 보너스 끝수 분석해줘' },
                    { title: '심화 분석: 미출현 끝수', prompt: '미출현 기간이 긴 끝수 알려줘' },
                    { title: '심화 분석: 평균 회귀', prompt: '끝수 합이 평균으로 회귀할 시점인가?' },
                    { title: '심화 분석: 연속 출현', prompt: '연속 출현 중인 끝수는?' },
                    { title: '전략: 제외 끝수', prompt: '이번 회차 제외하면 좋을 끝수는?' },
                    { title: '전략: 쏠림 현상', prompt: '끝수 쏠림 현상 분석해줘' },
                    { title: '전략: 안전 조합', prompt: '안전한 끝수 조합 추천해줘' }
                ],
                'total_sum': [
                    { title: '추세 분석: 합계 방향성', prompt: '최근 10회차 총합의 추세를 분석하고 다음 회차의 등락 방향을 예측해줘.' },
                    { title: '평균 회귀: 회귀 가능성', prompt: '현재 총합이 평균에서 얼마나 벗어났는지 분석하고, 평균으로의 회귀 시점을 진단해줘.' },
                    { title: '극값 진단: 과열/침체 구간', prompt: '최근 총합이 매우 높거나 낮은 구간이 지속되고 있는지 확인하고, 반작용 가능성을 분석해줘.' },
                    { title: '구간별 패턴: 분포 분석', prompt: '최근 총합이 주로 어느 구간(50대, 60대, 70대 등)에 머물렀는지 분석하고 추천 구간을 제시해줘.' },
                    { title: '필터 전략: Min-Max 설정', prompt: '현재까지의 총합 데이터를 기반으로 다음 회차에 출현할 가능성이 높은 합계 범위(Min, Max)를 추천해줘.' },
                    { title: '심화 분석: 번호대별 영향도', prompt: '단번대, 10번대, 20번대, 30번대, 40번대의 번호들이 총합에 미치는 영향도를 분석해줘.' },
                    { title: '통계: 표준편차 분석', prompt: '최근 100회차의 총합 데이터를 기반으로 표준편차를 계산하고, 이번 회차의 예상 범위를 제시해줘.' },
                    { title: '패턴: 연속 편차 추적', prompt: '총합이 평균 이상으로 나오는 구간과 평균 이하로 나오는 구간의 지속 주기를 분석해줘.' },
                    { title: '전략: 고위험 회피', prompt: '과거 데이터에서 가장 출현 확률이 낮았던 합계 구간이 무엇인지 찾아서 제외 가능한 범위를 추천해줘.' }
                ],
                'triangular_number': [
                    { title: '삼각수 개수 추천', prompt: '다음 회차 삼각수(1, 3, 6, 10, 15, 21, 28, 36, 45) 중 몇 개가 나올까요?' },
                    { title: '과열/침체 구간 진단', prompt: '최근 삼각수의 출현 빈도가 과열 상태인지 침체 상태인지 분석해줘.' },
                    { title: '필출 삼각수 추천', prompt: '이번 회차에 꼭 나올 것 같은 삼각수 번호 1~2개를 추천해줘.' },
                    { title: '삼각수 전멸 가능성', prompt: '이번 회차에 삼각수가 하나도 안 나올(멸) 가능성이 있나?' },
                    { title: '삼각수 vs 비삼각수', prompt: '삼각수와 비삼각수의 적절한 조합 비율을 추천해줘.' }
                ],
                'twin_number': [
                    { title: '동형수 개수 추천', prompt: '다음 회차 동형수(11, 22, 33, 44) 추천 개수는?' },
                    { title: '증가/감소 추세', prompt: '최근 동형수 출현이 증가하는 추세인가요?' },
                    { title: '전멸(0개) 가능성', prompt: '이번에 동형수가 전멸(0개)할 가능성은?' },
                    { title: '과열(2개↑) 체크', prompt: '동형수가 2개 이상 과열될 확률은?' },
                    { title: '동형수 제외 전략', prompt: '동형수(11, 22, 33, 44)를 모두 제외수로 가져가도 좋을까요?' },
                    { title: '11번 출현 가능성', prompt: '11번 출현 가능성은?' },
                    { title: '22번 출현 가능성', prompt: '22번 출현 가능성은?' },
                    { title: '33번 출현 가능성', prompt: '33번 출현 가능성은?' },
                    { title: '44번 출현 가능성', prompt: '44번 출현 가능성은?' },
                    { title: '역대 최다 출현 동형수', prompt: '역대 가장 많이 출현한 동형수 번호는 무엇인가요?' }
                ]
            };

            // 이전 모달 제거
            const existing = document.getElementById('promptLibModal');
            if (existing) existing.remove();
            const existingOverlay = document.getElementById('promptLibOverlay');
            if (existingOverlay) existingOverlay.remove();

            const currentLib = library[type] || [];
            const button = event ? event.currentTarget : null;
            let positionStyle = 'position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%); min-width: 450px;';

            // [Fix] 프롬프트 내의 따옴표가 HTML 속성을 깨뜨리지 않도록 이스케이프 처리
            const escapeHtml = (str) => str.replace(/'/g, "\\'").replace(/"/g, "&quot;");

            let html = `
            <div id="promptLibOverlay" class="fixed inset-0 z-[190]" onclick="const m=document.getElementById('promptLibModal'); if(m) m.remove(); this.remove();"></div>
            <div id="promptLibModal" class="z-[200] bg-white rounded-3xl shadow-[0_20px_60px_-15px_rgba(0,0,0,0.3)] w-full max-w-lg overflow-hidden animate-zoom-in border border-gray-200" 
                 style="${positionStyle}">
                <div class="px-7 py-5 border-b border-gray-100 flex items-center justify-between bg-gradient-to-r from-gray-50 to-white">
                    <div class="flex items-center gap-3">
                        <div class="p-2 bg-blue-100 rounded-xl">
                            <span class="material-symbols-outlined text-blue-600 text-xl font-bold">library_books</span>
                        </div>
                        <h3 class="text-lg font-extrabold text-gray-900 tracking-tight">전문가용 프롬프트 라이브러리</h3>
                    </div>
                    <button onclick="document.getElementById('promptLibModal').remove(); document.getElementById('promptLibOverlay').remove();" 
                            class="p-2 hover:bg-gray-100 rounded-xl text-gray-400 transition-all hover:text-gray-600">
                        <span class="material-symbols-outlined text-2xl">close</span>
                    </button>
                </div>
                <div class="p-6 space-y-4 max-h-[500px] overflow-y-auto custom-scrollbar bg-white">
                    <p class="text-sm font-medium text-gray-500 mb-2 px-1">원하는 분석 시나리오를 선택하면 AI 채팅창에 즉시 입력됩니다.</p>
                    ${currentLib.map(item => `
                        <button onclick="window.AIAnalysis.selectPrompt('${escapeHtml(item.prompt)}')" 
                                class="w-full text-left p-5 rounded-2xl border border-gray-100 hover:border-blue-500 hover:bg-blue-50/50 transition-all group relative overflow-hidden shadow-sm hover:shadow-md">
                            <div class="absolute left-0 top-0 w-1 h-full bg-blue-500 opacity-0 group-hover:opacity-100 transition-opacity"></div>
                            <h4 class="font-black text-blue-600 group-hover:text-blue-700 text-sm mb-2 flex items-center gap-2">
                                <span class="w-1.5 h-1.5 rounded-full bg-blue-600"></span>
                                ${item.title}
                            </h4>
                            <p class="text-sm text-gray-700 leading-relaxed font-medium group-hover:text-gray-900">${item.prompt}</p>
                        </button>
                    `).join('')}
                </div>
                <div class="px-7 py-4 bg-gray-50 border-t border-gray-100 text-center">
                    <p class="text-[11px] text-gray-400 font-bold uppercase tracking-widest">Lotto Expert Knowledge Base</p>
                </div>
            </div>
        `;
            document.body.insertAdjacentHTML('beforeend', html);


            const modal = document.getElementById('promptLibModal');
            if (button && modal) {
                const btnRect = button.getBoundingClientRect();

                // 1. 모달 표시 (먼저 보여야 함)
                modal.classList.remove('hidden');

                // [중요] 기존 중앙 정렬 클래스 제거 (혹시 남아있다면)
                modal.classList.remove('flex', 'items-center', 'justify-center');

                // 3. 모달 위치 지정 (우측 정렬)
                modal.style.position = 'fixed';
                modal.style.margin = '0';
                modal.style.transform = 'none'; // transform 제거

                // Y축: 버튼 바로 아래 (+8px 간격)
                modal.style.top = (btnRect.bottom + 8) + 'px';

                // X축: [핵심 변경] 왼쪽(left) 대신 오른쪽(right) 기준점 사용
                // 화면 전체 너비에서 버튼의 오른쪽 끝 위치를 빼면, 오른쪽 여백 값이 나옵니다.
                const rightSpace = window.innerWidth - btnRect.right;

                modal.style.left = 'auto'; // 왼쪽 기준 해제
                modal.style.right = rightSpace + 'px'; // 버튼의 오른쪽 끝과 모달의 오른쪽 끝을 일치시킴
            }
        },

        selectPrompt: function (prompt) {
            const input = document.getElementById('aiUserPrompt');
            const modalInput = document.getElementById('aiModalInput');
            if (input) input.value = prompt;
            if (modalInput) modalInput.value = prompt;

            const libModal = document.getElementById('promptLibModal');
            const libOverlay = document.getElementById('promptLibOverlay');
            if (libModal) libModal.remove();
            if (libOverlay) libOverlay.remove();

            // 프롬프트를 직접 전달하여 AI 분석 실행
            if (typeof window.submitCustomAIAnalysis === 'function') {
                window.submitCustomAIAnalysis(prompt);
            } else if (typeof submitCustomAIAnalysis === 'function') {
                submitCustomAIAnalysis(prompt);
            }
        },

        formatResponse: function (text) {
            return this.formatText(text);
        },

        analyzePattern: async function (analysisType, userPrompt, contextData) {
            try {
                const systemPrompt = `
Role: 로또 분석 전문가
Analysis Type: ${analysisType}
Task: 사용자의 질문에 대해 주어진 데이터를 바탕으로 명확하고 통찰력 있는 답변을 제공하세요.
Format: JSON
{
    "response": "답변 내용 (마크다운 지원)"
}
`;
                const fullContext = `${systemPrompt}\n\nUser Question: "${userPrompt}"\n\n${contextData}`;

                const response = await window.supabaseClient.functions.invoke('analyze-lotto', {
                    body: { context: fullContext }
                });

                if (response.error) throw response.error;
                return response.data;

            } catch (err) {
                console.error("Pattern Analysis Error:", err);
                throw err;
            }
        }
    };

    // ==========================================
    // 4. Legacy Utils (Compatibility)
    // ==========================================
    window.Utils = {
        getBallColor: function (num) {
            var n = parseInt(num);
            if (n <= 10) return window.LOTTO_CONSTANTS.COLORS.P10;
            if (n <= 20) return window.LOTTO_CONSTANTS.COLORS.P20;
            if (n <= 30) return window.LOTTO_CONSTANTS.COLORS.P30;
            if (n <= 40) return window.LOTTO_CONSTANTS.COLORS.P40;
            return window.LOTTO_CONSTANTS.COLORS.P45;
        },

        formatAIResponse: function (text, mode) {
            return window.AIAnalysis.formatText(text, mode);
        },

        saveFilter: function (pageKey, filterData) {
            try {
                localStorage.setItem(pageKey, JSON.stringify(filterData));
            } catch (e) {
                console.error('필터 저장 실패:', e);
            }
        },

        loadFilter: function (pageKey) {
            try {
                var saved = localStorage.getItem(pageKey);
                return saved ? JSON.parse(saved) : null;
            } catch (e) {
                console.error('필터 로드 실패:', e);
                return null;
            }
        },

        /**
         * 조합을 커스텀분석 필터로 검증
         * @param {number[]} combination - 검증할 6개 번호 조합
         * @returns {Promise<Object>} { valid: boolean, failedFilter?: string, matchCount?: number, expected?: string }
         */
        validateCustomFilters: async function (combination) {
            if (!window.supabaseClient) {
                return { valid: true, message: 'Supabase 미연결' };
            }

            try {
                // 활성화된 커스텀분석 필터 조회
                const _v2UserId = window.filterService?.userId
                    || (await window.supabaseClient.auth.getUser()).data?.user?.id;
                let _v2Query = window.supabaseClient
                    .from('ai_custom_analyses')
                    .select('id, title, target_numbers, type, rules, config, filter_config')
                    .not('filter_config', 'is', null);
                if (_v2UserId) _v2Query = _v2Query.eq('user_id', _v2UserId);
                const { data, error } = await _v2Query;

                if (error) throw error;

                // enabled가 true인 것만 필터링
                const activeFilters = (data || []).filter(item => item.filter_config?.enabled === true);

                if (activeFilters.length === 0) {
                    return { valid: true, message: '활성 필터 없음' };
                }

                // [New] 동적 필터 계산을 위한 최신 회차 데이터 조회 (필요한 경우에만)
                let allDraws = [];
                const hasDynamic = activeFilters.some(f => f.type === 'dynamic' || (f.rules && (f.rules.formula || f.rules.regression_step)));
                if (hasDynamic) {
                    const { data: draws } = await window.supabaseClient
                        .from('lotto_draws')
                        .select('*')
                        .order('round', { ascending: false })
                        .limit(250);
                    allDraws = draws || [];
                }

                // 각 필터 검증
                for (const filter of activeFilters) {
                    // [New] 통합 계산 함수 사용 (DB 저장값 대신 실시간 계산값 우선)
                    const targetNumbers = (filter.type === 'dynamic' || filter.type === 'group')
                        ? (window.LOTTO_CONSTANTS.calculateCustomTargets(filter, allDraws, { isPrediction: true }))
                        : (filter.target_numbers || []);

                    const matchCount = combination.filter(n => targetNumbers.includes(n)).length;
                    const { min = 0, max = 6 } = filter.filter_config || {};

                    if (matchCount < min || matchCount > max) {
                        return {
                            valid: false,
                            failedFilter: filter.title,
                            matchCount,
                            expected: `${min}~${max}개`,
                            message: `[${filter.title}] 필터 불통과: ${matchCount}개 포함 (필요: ${min}~${max}개)`
                        };
                    }
                }

                return { valid: true, passedCount: activeFilters.length };

            } catch (err) {
                console.error('커스텀 필터 검증 실패:', err);
                return { valid: true, error: err.message };
            }
        },

        /**
         * 활성화된 커스텀분석 필터 개수 조회
         */
        getActiveCustomFilterCount: async function () {
            if (!window.supabaseClient) return 0;

            try {
                const _cntUserId = window.filterService?.userId
                    || (await window.supabaseClient.auth.getUser()).data?.user?.id;
                let _cntQuery = window.supabaseClient
                    .from('ai_custom_analyses')
                    .select('id, filter_config')
                    .not('filter_config', 'is', null);
                if (_cntUserId) _cntQuery = _cntQuery.eq('user_id', _cntUserId);
                const { data } = await _cntQuery;

                return (data || []).filter(item => item.filter_config?.enabled === true).length;
            } catch (err) {
                console.error('활성 필터 개수 조회 실패:', err);
                return 0;
            }
        }
    };

    console.log('✅ Lotto AI Utilities v2.0 Loaded');

    // ==========================================
    // 7. AIProxy - LangChain 백엔드 자동 감지 + Fallback
    // ==========================================


    console.log('✅ AIProxy v4.0 Loaded');

    /**
     * 전역 전문가 메모 (Human-in-the-loop) 시스템
     */
    window.ExpertMemo = {
        init() {
            // body 끝에 모달창 HTML 자동 주입
            if (document.getElementById('expertMemoModal')) return;

            const modalHtml = `
                <div id="expertMemoModal" class="fixed inset-0 bg-slate-900/60 z-[10000] hidden flex flex-col items-center justify-center backdrop-blur-sm transition-opacity p-4">
                    <div class="bg-white rounded-2xl shadow-2xl max-w-lg w-full p-6 transform transition-all flex flex-col max-h-[90vh]">
                        <div class="flex justify-between items-center mb-4 shrink-0">
                            <h3 class="text-lg font-bold text-slate-800 flex items-center gap-2">
                                <span class="material-symbols-outlined text-indigo-600">sticky_note_2</span>
                                전문가 분석 메모
                            </h3>
                            <button onclick="window.ExpertMemo.close()" class="text-slate-400 hover:text-slate-600">
                                <span class="material-symbols-outlined">close</span>
                            </button>
                        </div>
                        
                        <div class="mb-4 shrink-0">
                            <label class="block text-xs font-bold text-slate-500 mb-1">적용할 타겟 회차 (분석회차)</label>
                            <input type="number" id="memoTargetRound" onchange="window.ExpertMemo.loadHistory()" class="w-full border border-slate-200 rounded-lg text-sm px-3 py-2 focus:ring-2 focus:ring-indigo-500 outline-none" placeholder="예: 1213">
                        </div>
                        
                        <div class="mb-4 flex-1 overflow-y-auto min-h-[150px] border border-slate-200 rounded-lg bg-slate-50 custom-scrollbar relative" id="memoHistoryContainer">
                            <div class="text-center text-sm text-slate-400 py-4 absolute inset-0 flex flex-col items-center justify-center">
                                로딩 중...
                            </div>
                        </div>

                        <div class="mb-5 shrink-0">
                            <label class="block text-xs font-bold text-slate-500 mb-1">분석 내용 (자연어로 자유롭게 입력)</label>
                            <textarea id="memoContent" rows="3" class="w-full border border-slate-200 rounded-lg text-sm px-3 py-2 focus:ring-2 focus:ring-indigo-500 outline-none resize-none custom-scrollbar" placeholder="예: 이번 주는 30번대가 강세일 것 같고..."></textarea>
                        </div>
                        
                        <div class="flex justify-end gap-2 shrink-0">
                            <button onclick="window.ExpertMemo.close()" class="px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg text-sm font-bold transition-colors">닫기</button>
                            <button id="btnSaveMemo" onclick="window.ExpertMemo.save()" class="px-4 py-2 bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-700 hover:to-purple-700 text-white rounded-lg text-sm font-bold shadow-md transition-all flex items-center justify-center">
                                메모 추가
                            </button>
                        </div>
                    </div>
                </div>
            `;
            document.body.insertAdjacentHTML('beforeend', modalHtml);
        },

        async open() {
            this.init(); // 모달이 없으면 생성
            const modal = document.getElementById('expertMemoModal');
            const roundInput = document.getElementById('memoTargetRound');

            // 타겟 회차 자동 세팅: DeepLearning.state.targetRound -> 최신회차+1 -> 빈값
            if (!roundInput.value) {
                if (window.DeepLearning && window.DeepLearning.state && window.DeepLearning.state.targetRound) {
                    roundInput.value = window.DeepLearning.state.targetRound;
                } else if (window.supabaseClient) {
                    try {
                        const { data } = await window.supabaseClient.from('lotto_draws').select('round').order('round', { ascending: false }).limit(1);
                        if (data && data.length > 0) {
                            roundInput.value = data[0].round + 1;
                        }
                    } catch (e) {
                        console.error("최신 회차 조회 실패:", e);
                    }
                }
            }

            if (modal) modal.classList.remove('hidden');

            this.loadHistory();
        },

        close() {
            const modal = document.getElementById('expertMemoModal');
            if (modal) modal.classList.add('hidden');
        },

        async loadHistory() {
            const roundInput = document.getElementById('memoTargetRound');
            const container = document.getElementById('memoHistoryContainer');

            if (!roundInput || !container || !roundInput.value) return;

            const targetRound = parseInt(roundInput.value);
            container.innerHTML = '<div class="absolute inset-0 flex flex-col items-center justify-center text-sm text-slate-400"><span class="material-symbols-outlined animate-spin align-middle mr-1 text-2xl mb-2 text-indigo-500">sync</span>이력을 불러오는 중...</div>';

            try {
                if (!window.supabaseClient) {
                    throw new Error("Supabase is not initialized.");
                }

                const { data, error } = await window.supabaseClient
                    .from('user_checkpoints')
                    .select('*')
                    .eq('round', targetRound)
                    .order('created_at', { ascending: true });

                if (error) throw error;

                if (!data || data.length === 0) {
                    container.innerHTML = `<div class="absolute inset-0 flex flex-col items-center justify-center text-sm text-slate-400 p-6 text-center"><span class="material-symbols-outlined text-4xl mb-3 opacity-30 text-slate-500">inbox</span>${targetRound}회차 전문가 통찰을<br>가장 먼저 기록해보세요.</div>`;
                    return;
                }

                let html = '<div class="space-y-3 p-4">';
                data.forEach((item, index) => {
                    const dateObj = new Date(item.created_at || new Date());
                    const dateStr = dateObj.getFullYear() + '-' +
                        String(dateObj.getMonth() + 1).padStart(2, '0') + '-' +
                        String(dateObj.getDate()).padStart(2, '0') + ' ' +
                        String(dateObj.getHours()).padStart(2, '0') + ':' +
                        String(dateObj.getMinutes()).padStart(2, '0');

                    const content = (item.memo || '').replace(/\\n/g, '<br>').replace(/\\r/g, '');

                    html += `
                        <div class="bg-white p-3.5 rounded-xl border border-slate-200 shadow-sm transition-all hover:shadow-md group/memo relative">
                            <div class="flex justify-between items-center mb-2.5">
                                <span class="inline-flex items-center gap-1.5 text-[11px] font-black text-indigo-700 bg-indigo-50 px-2 py-1 rounded-md tracking-tight">
                                    <span class="material-symbols-outlined text-[14px]">bookmark</span>
                                    #${index + 1}
                                </span>
                                <div class="flex items-center gap-2">
                                    <span class="text-[11px] text-slate-400 font-bold">${dateStr}</span>
                                    <button onclick="window.ExpertMemo.delete('${item.id}')" class="text-slate-300 hover:text-red-500 transition-colors opacity-0 group-hover/memo:opacity-100 p-0.5 rounded-md hover:bg-red-50" title="메모 삭제">
                                        <span class="material-symbols-outlined text-[16px]">close</span>
                                    </button>
                                </div>
                            </div>
                            <div class="text-[13px] text-slate-700 leading-normal font-medium whitespace-pre-wrap break-words">${content}</div>
                        </div>
                    `;
                });
                html += '</div>';
                container.innerHTML = html;

                // Scroll to bottom softly
                setTimeout(() => {
                    container.scrollTop = container.scrollHeight;
                }, 50);

            } catch (err) {
                console.error("이력 로드 실패:", err);
                container.innerHTML = `<div class="absolute inset-0 flex flex-col items-center justify-center text-sm text-red-500 p-6 text-center"><span class="material-symbols-outlined text-4xl mb-3 opacity-50">error</span>이력을 불러오지 못했습니다.<br><span class="text-xs text-red-400 mt-1">${err.message}</span></div>`;
            }
        },

        async delete(id) {
            if (!id || !confirm('이 메모를 삭제하시겠습니까?')) return;

            try {
                if (!window.supabaseClient) throw new Error("Supabase is not initialized.");

                const { error } = await window.supabaseClient
                    .from('user_checkpoints')
                    .delete()
                    .eq('id', id);

                if (error) throw error;

                // 삭제 성공 시 목록 갱신
                await this.loadHistory();

            } catch (err) {
                console.error("메모 삭제 실패:", err);
                alert("삭제에 실패했습니다: " + err.message);
            }
        },

        async save() {
            const round = document.getElementById('memoTargetRound').value;
            const memo = document.getElementById('memoContent').value;
            const btn = document.getElementById('btnSaveMemo');

            if (!round || !memo.trim()) {
                alert("회차와 메모 내용을 모두 입력해주세요.");
                return;
            }

            try {
                const originalText = btn.innerHTML;
                btn.innerHTML = '<span class="material-symbols-outlined animate-spin text-sm align-middle mr-1">sync</span>저장 중...';
                btn.disabled = true;

                if (!window.supabaseClient) {
                    throw new Error("Supabase is not initialized.");
                }

                // Supabase insert
                const { error } = await window.supabaseClient.from('user_checkpoints').insert([
                    { round: parseInt(round), memo: memo }
                ]);

                if (error) throw error;

                document.getElementById('memoContent').value = '';
                await this.loadHistory();

                const originalBg = btn.className;
                btn.className = "px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-sm font-bold shadow-md transition-all flex items-center justify-center";
                btn.innerHTML = '<span class="material-symbols-outlined text-sm align-middle mr-1 relative -top-[1px]">check_circle</span>저장 완료';

                setTimeout(() => {
                    btn.className = originalBg;
                    btn.innerHTML = '메모 추가';
                }, 2000);

            } catch (err) {
                console.error("메모 저장 실패:", err);
                alert("저장에 실패했습니다: " + err.message);
                btn.innerHTML = '메모 추가';
            } finally {
                btn.disabled = false;
            }
        }
    };

    // 페이지 로드 시 전역 모달 초기화 준비
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => window.ExpertMemo.init());
    } else {
        window.ExpertMemo.init();
    }

} // end of duplicate load guard
