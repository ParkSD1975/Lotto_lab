/**
 * filter_dashboard.js
 * 100% 리얼 데이터 연동 (대상수 계산, 분석 페이지 UI 거울 반영)
 * 수정: 회귀분석 직접 입력창 적용, 텍스트 다이어트, DB 키값 오류(regression_patterns) 수정
 */

window.FilterDashboard = {
    state: {
        totalCombos: 8145060,
        currentCombos: 8145060,
        allDraws: [],
        foundationFilters: [],
        userSettings: {},
        regressionSettings: {},
        customFilters: [],
        basket: { fixed: [], excluded: [] },

        // 고정 속성수 사전
        staticTargets: {
            prime_number_patterns: [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43],
            composite_count: [4, 6, 8, 9, 10, 12, 14, 15, 16, 18, 20, 21, 22, 24, 25, 26, 27, 28, 30, 32, 33, 34, 35, 36, 38, 39, 40, 42, 44, 45],
            square_number_patterns: [1, 4, 9, 16, 25, 36],
            triangular_number_patterns: [1, 3, 6, 10, 15, 21, 28, 36, 45],
            twin_number_patterns: [11, 22, 33, 44]
        },
        dynamicTargets: {}
    },

    async init() {
        console.log("🚀 Real Filter Dashboard Booting...");
        await this.loadDataFromDB();
        this.renderUI();

        // [추가] 실시간 동기화: 다른 탭(total_sum.html 등)에서 저장 시 즉시 반영
        window.addEventListener('storage', (e) => {
            if (e.key && (e.key === 'total_sum' || e.key.endsWith('_filter') || e.key === 'regression_analysis' || e.key === 'lotto_basket' || e.key === 'prime_number_patterns' || e.key === 'composite_count' || e.key === 'twin_number_patterns' || e.key === 'square_number_patterns' || e.key === 'triangular_number_patterns')) {
                console.log(`🔄 Storage Change Detected: ${e.key}. Refreshing Dashboard...`);
                this.loadDataFromDB().then(() => this.renderUI());
            }
        });

        // [추가] GNB 바스켓 실시간 동기화 (같은 탭 내 이벤트 감지)
        window.addEventListener('basketChanged', (e) => {
            console.log('🧺 Basket Changed Event Detected. Updating UI...');
            this.state.basket = {
                fixed: e.detail.fixed || [],
                excluded: e.detail.exclude || []
            };
            this.renderUI();
        });

        // 탭 전환 및 딥링크 지원
        const params = new URLSearchParams(window.location.search);
        let tab = params.get('tab');
        const focusId = params.get('id') || params.get('focus');

        if (tab) {
            if (tab.includes('custom')) tab = 'custom';
            if (tab.includes('regression')) tab = 'regression';
            if (tab.includes('foundation') || tab.includes('basic')) tab = 'foundation';
            this.switchTab(tab);
        } else {
            this.switchTab('foundation');
        }

        if (focusId) {
            this.handleDeepLink(focusId);
        }

        document.getElementById('btnRegAllOn')?.addEventListener('click', () => this.bulkToggleRegression(true));
        document.getElementById('btnRegAllOff')?.addEventListener('click', () => this.bulkToggleRegression(false));
    },

    renderUI() {
        this.renderBasket();
        this.renderFoundationFilters();
        this.renderRegressionFilters();
        this.renderCustomFilters();
        this.updateNeonCounter();
    },

    handleDeepLink(focusId) {
        setTimeout(() => {
            const element = document.getElementById(`filter-${focusId}`) || document.getElementById(`filter-card-${focusId}`);
            if (element) {
                element.scrollIntoView({ behavior: 'smooth', block: 'center' });
                element.classList.add('transition-all', 'duration-500', 'ring-4', 'ring-indigo-500');
                setTimeout(() => {
                    element.classList.remove('ring-4', 'ring-indigo-500');
                }, 2000);
            }
        }, 300);
    },

    switchTab(tabId) {
        document.querySelectorAll('.tab-btn').forEach(btn => {
            if (btn.dataset.tab === tabId) btn.classList.add('active');
            else btn.classList.remove('active');
        });

        document.querySelectorAll('.tab-content').forEach(content => {
            if (content.id === `tab-${tabId}`) content.classList.remove('hidden');
            else content.classList.add('hidden');
        });
    },

    async loadDataFromDB() {
        if (!window.supabaseClient) return;

        try {
            if (!window.filterService) {
                window.filterService = new FilterService(window.supabaseClient);
            }
            await window.filterService.initialize();

            const { data: draws } = await window.supabaseClient.from('lotto_draws').select('*').order('round', { ascending: false }).limit(250);
            this.state.allDraws = draws || [];

            if (this.state.allDraws.length > 0) {
                const prevNum = (this.state.allDraws[0].numbers || []).slice(0, 6);
                const prevBonus = this.state.allDraws[0].bonus || this.state.allDraws[0].bonus_number || this.state.allDraws[0].bonusNo;

                this.state.dynamicTargets['carryover_count'] = [...prevNum].sort((a, b) => a - b);
                this.state.dynamicTargets['carryover_bonus_count'] = [...prevNum, prevBonus].filter(n => n !== null && n !== undefined).sort((a, b) => a - b);

                let neighbors = new Set();
                prevNum.forEach(n => { if (n > 1) neighbors.add(n - 1); if (n < 45) neighbors.add(n + 1); });
                prevNum.forEach(n => neighbors.delete(n));
                this.state.dynamicTargets['neighbor_number_patterns'] = Array.from(neighbors).sort((a, b) => a - b);
            }

            const defs = await window.filterService.loadDefinitions(true);
            this.state.foundationFilters = defs || [];
            const loadedKeys = this.state.foundationFilters.map(d => d.filter_key);
            console.log('[FilterDashboard] Loaded filter_keys:', loadedKeys);

            // Explicit check for required keys
            ['missing_period', 'missing_custom_filter'].forEach(k => {
                if (!loadedKeys.includes(k)) {
                    console.warn(`[FilterDashboard] CRITICAL: Key "${k}" is MISSING from DB!`);
                }
            });



            const allSettings = await window.filterService.loadAllSettings();
            console.log('[FilterDashboard] All Settings Loaded', allSettings);

            this.state.userSettings = {};
            this.state.regressionSettings = {};
            this.state.regressionEnabled = false;

            for (const def of this.state.foundationFilters) {
                const defaultParsed = typeof def.default_settings === 'string' ? JSON.parse(def.default_settings) : (def.default_settings || {});

                // localStorage 우선순위: filter_key_filter -> filter_key
                let rawLocalData = null;
                try {
                    const localKey = `${def.filter_key}_filter`;
                    // [핵심 수정] direct key(total_sum)를 _filter 접미사보다 우선함
                    const raw = localStorage.getItem(def.filter_key) || localStorage.getItem(localKey);
                    if (raw) rawLocalData = JSON.parse(raw);

                    // [tail_digit 호환] tail_digit.html이 사용하는 추가 키 체크
                    if (!rawLocalData && def.filter_key === 'tail_digit_patterns') {
                        const raw2 = localStorage.getItem('tail_digit_filter') || localStorage.getItem('lottoDigitFilters');
                        if (raw2) rawLocalData = JSON.parse(raw2);
                    }
                } catch (e) { }

                if (allSettings[def.filter_key]) {
                    this.state.userSettings[def.id] = {
                        enabled: allSettings[def.filter_key].enabled,
                        settings: allSettings[def.filter_key].settings || {}
                    };

                    // [핵심] DB 데이터와 Local 캐시 지능적 병합 (로그인 시 배지 누락 방지)
                    const dbSettings = this.state.userSettings[def.id].settings;
                    if (rawLocalData) {
                        // 1. 제외 합계 병합: DB에 없거나 비어있는데 Local에 있으면 복구
                        const hasExInDB = dbSettings.excludedSums && dbSettings.excludedSums.length > 0;
                        const hasExInLocal = rawLocalData.excludedSums && rawLocalData.excludedSums.length > 0;

                        if (!hasExInDB && hasExInLocal) {
                            console.log(`💡 [Merge] ${def.filter_key}: Local excludedSums recovered to DB state`);
                            dbSettings.excludedSums = rawLocalData.excludedSums;
                        }

                        // 2. 범위값 병합: DB에 없고 local에만 있는 경우 보호
                        if (dbSettings.min === undefined && rawLocalData.min !== undefined) dbSettings.min = rawLocalData.min;
                        if (dbSettings.max === undefined && rawLocalData.max !== undefined) dbSettings.max = rawLocalData.max;

                        // 3. [수정] recent10FilterActive 플래그 병합 (배지 표시 핵심)
                        // DB에 없거나 false인데 local에 true면 local 값 우선 적용
                        if (!dbSettings.recent10FilterActive && rawLocalData.recent10FilterActive) {
                            dbSettings.recent10FilterActive = rawLocalData.recent10FilterActive;
                        }

                        // 4. [추가] 계수형 필터(소수, 합성수 등) 데이터 지능형 병합
                        const discreteKeys = ['prime_number_patterns', 'composite_count', 'odd_even_pattern', 'high_low_pattern'];
                        if (discreteKeys.includes(def.filter_key)) {
                            const targetArrName = (def.filter_key === 'prime_number_patterns' || def.filter_key === 'composite_count') ? 'selectedCounts' : 'activeCounts';

                            // DB에 선택값이 없는데 Local에 있으면 복구
                            if ((!dbSettings[targetArrName] || dbSettings[targetArrName].length === 0) && rawLocalData[targetArrName]) {
                                dbSettings[targetArrName] = rawLocalData[targetArrName];
                            }

                            // 특수 필드 병합
                            if (def.filter_key === 'composite_count' && !dbSettings.excludedComposites && rawLocalData.excludedComposites) {
                                dbSettings.excludedComposites = rawLocalData.excludedComposites;
                            }
                        }

                        // 5. 홀짝 패턴 전용 데이터 병합
                        if (def.filter_key === 'odd_even_pattern') {
                            if (!dbSettings.excludedOddEvens && rawLocalData.excludedOddEvens) dbSettings.excludedOddEvens = rawLocalData.excludedOddEvens;
                            if (!dbSettings.restoredAutoOddEvens && rawLocalData.restoredAutoOddEvens) dbSettings.restoredAutoOddEvens = rawLocalData.restoredAutoOddEvens;
                            if (!dbSettings.selectedRatios && rawLocalData.selectedRatios) dbSettings.selectedRatios = rawLocalData.selectedRatios;
                        }

                        // 6. [tail_digit 전용] filters 복구 - localStorage를 항상 우선 적용
                        // (updateTailDigitFilter에서 localStorage를 항상 최신으로 유지하기 때문)
                        if (def.filter_key === 'tail_digit_patterns' && rawLocalData && rawLocalData.filters) {
                            console.log('💡 [Merge] tail_digit_patterns: Applying localStorage filters');
                            dbSettings.filters = rawLocalData.filters;
                        }
                    }
                } else if (rawLocalData) {
                    const { enabled, ...actualSettings } = rawLocalData;
                    this.state.userSettings[def.id] = {
                        enabled: enabled || false,
                        settings: Object.keys(actualSettings).length > 0 ? actualSettings : defaultParsed
                    };
                } else {
                    this.state.userSettings[def.id] = { enabled: false, settings: defaultParsed };
                }

                // [정리] 레거시 키 삭제 (필요 시) - total_sum_filter 등
                if (localStorage.getItem(`${def.filter_key}_filter`) && localStorage.getItem(def.filter_key)) {
                    // console.log(`🧹 Cleaning up legacy key: ${def.filter_key}_filter`);
                    // localStorage.removeItem(`${def.filter_key}_filter`); 
                }
            }

            // [수정] 회귀 분석 키값 통일 (regression_analysis 우선, regression_patterns 호환)
            if (allSettings['regression_analysis']) {
                this.state.regressionSettings = allSettings['regression_analysis'].settings || {};
                this.state.regressionEnabled = allSettings['regression_analysis'].enabled;
            } else {
                // localStorage fallback
                try {
                    const raw = localStorage.getItem('regression_analysis') || localStorage.getItem('regression_patterns');
                    if (raw) {
                        const localReg = JSON.parse(raw);
                        this.state.regressionEnabled = localReg.master_enabled !== undefined ? localReg.master_enabled : (localReg.enabled || false);
                        this.state.regressionSettings = localReg.settings || localReg;
                    }
                } catch (e) { }
            }


            const { data: customs } = await window.supabaseClient.from('ai_custom_analyses').select('*');
            this.state.customFilters = customs || [];

            let loadedBasket = { fixed: [], exclude: [] };
            try { loadedBasket = JSON.parse(localStorage.getItem('lotto_basket')) || { fixed: [], exclude: [] }; } catch (e) { }
            this.state.basket = { fixed: loadedBasket.fixed || [], excluded: loadedBasket.exclude || [] };

        } catch (error) { console.error("DB Load Error:", error); }
    },

    renderBalls(numbers, excludedList = [], fixedList = []) {
        if (!numbers || numbers.length === 0) return '<span class="text-xs text-slate-400">대상수 없음</span>';
        const finalFixed = fixedList.length > 0 ? fixedList : this.state.basket.fixed;
        const finalExcluded = excludedList.length > 0 ? excludedList : this.state.basket.excluded;

        return numbers.map(n => {
            const isEx = finalExcluded.includes(n);
            const isFi = finalFixed.includes(n);
            let ballClass = "w-7 h-7 flex items-center justify-center rounded-full text-[11px] font-black text-white shadow-sm border ";

            if (isFi) ballClass += "bg-blue-600 border-blue-400 ball-fixed";
            else if (isEx) ballClass += "bg-slate-400 border-slate-500 ball-excluded";
            else {
                if (n <= 10) ballClass += "bg-amber-400 border-amber-500";
                else if (n <= 20) ballClass += "bg-blue-500 border-blue-600";
                else if (n <= 30) ballClass += "bg-rose-500 border-rose-600";
                else if (n <= 40) ballClass += "bg-slate-500 border-slate-600";
                else ballClass += "bg-emerald-500 border-emerald-600";
            }
            return `<span class="${ballClass}">${String(n).padStart(2, '0')}</span>`;
        }).join('');
    },

    getFilterLink(key) {
        const mapping = {
            'total_sum': 'total_sum.html', 'last_digit_sum': 'tail_sum.html', 'ac_value': 'ac_value.html',
            'prime_number_patterns': 'prime_number.html', 'composite_count': 'composite_number.html',
            'square_number_patterns': 'square_number.html', 'triangular_number_patterns': 'triangular_number.html',
            'twin_number_patterns': 'twin_number.html', 'neighbor_number_patterns': 'neighbor_number.html',
            'carryover_count': 'carryover.html', 'consecutive_count': 'consecutive_number.html',
            'odd_even_pattern': 'odd_even.html', 'high_low_pattern': 'low_high.html',
            'tail_digit_patterns': 'tail_digit.html',
            'hot_cold_5': 'hot_cold.html', 'hot_cold_10': 'hot_cold.html',
            'hot_cold_15': 'hot_cold.html', 'hot_cold_20': 'hot_cold.html',
            'missing_period': 'missing.html',
            'missing_custom_filter': 'missing.html',
            'long_term_miss': 'missing.html',
            'multiple_3_count': 'multiple.html',
            'number_range_patterns': 'number_range.html', 'lotto_paper_pattern': 'lotto_paper.html',
            'magic_square_pattern': 'magic_square.html'
        };
        return mapping[key] || `${key}.html`;
    },

    calculateCustomTargets(custom) {
        return window.LOTTO_CONSTANTS.calculateCustomTargets(custom, this.state.allDraws, { isPrediction: true });
    },

    buildFilterControl(def, userSet) {
        const key = def.filter_key;
        const vals = userSet.settings || {};
        let html = '';

        const targetNums = this.state.staticTargets[key] || this.state.dynamicTargets[key];
        const excludedNums = vals.excludedNumbers || vals.excludedPrimes || vals.excludedComposites || vals.excludedSquares || vals.excludedTriangulars || [];

        // 이월수 필터는 대상번호 박스를 개별 섹션 내부에 그리므로 여기선 스킵
        if (targetNums && key !== 'carryover_count') {
            html += `
            <div class="mt-4 mb-4 p-3 bg-slate-50 border border-slate-100 rounded-xl">
                <div class="mb-2 flex justify-between items-center">
                    <span class="text-xs font-bold text-slate-500">대상번호</span>
                    <span class="text-[11px] font-black text-indigo-600">${targetNums.length}개</span>
                </div>
                <div class="flex flex-wrap gap-1.5">
                    ${this.renderBalls(targetNums, excludedNums)}
                </div>
            </div>`;
        }

        const isRange = key.includes('sum') || key === 'ac_value' || key.includes('neighbor');

        if (isRange) {
            const defaultSet = typeof def.default_settings === 'string' ? JSON.parse(def.default_settings) : (def.default_settings || {});
            const min = vals.min !== undefined ? vals.min : (defaultSet.min !== undefined ? defaultSet.min : 0);
            const max = vals.max !== undefined ? vals.max : (defaultSet.max !== undefined ? defaultSet.max : (key.includes('total_sum') ? 255 : 45));

            html += `
            <div class="flex items-center gap-3">
                <div class="flex-1 bg-white border border-slate-200 rounded-lg flex items-center px-3 py-2 shadow-sm focus-within:ring-2 focus-within:ring-indigo-500">
                    <span class="text-xs font-black text-slate-400 uppercase w-8">Min</span>
                    <input type="number" value="${min}" 
                        onchange="FilterDashboard.updateFilterValue('${def.id}', 'min', this.value)"
                        class="w-full text-right font-black text-slate-700 bg-transparent border-none p-0 focus:ring-0">
                </div>
                <span class="text-slate-300 font-bold">~</span>
                <div class="flex-1 bg-white border border-slate-200 rounded-lg flex items-center px-3 py-2 shadow-sm focus-within:ring-2 focus-within:ring-indigo-500">
                    <span class="text-xs font-black text-slate-400 uppercase w-8">Max</span>
                    <input type="number" value="${max}" 
                        onchange="FilterDashboard.updateFilterValue('${def.id}', 'max', this.value)"
                        class="w-full text-right font-black text-slate-700 bg-transparent border-none p-0 focus:ring-0">
                </div>
            </div>`;

            if (key === 'total_sum' || key === 'last_digit_sum' || key === 'ac_value') {
                const manualExcluded = key === 'ac_value' ? (vals.excludedAcValues || []) : (vals.excludedSums || vals.excluded || []);

                // 시스템 자동 제외
                let systemExcluded = [];
                if (vals.recent10FilterActive && this.state.allDraws && this.state.allDraws.length > 0) {
                    const restoredAuto = vals.restoredAutoSums || vals.restoredAutoAcValues || [];

                    if (key === 'total_sum') {
                        systemExcluded = [...new Set(
                            this.state.allDraws.slice(0, 10).map(d => {
                                if (d.sum !== undefined && d.sum !== null) return d.sum;
                                if (d.numbers && Array.isArray(d.numbers)) return d.numbers.reduce((a, b) => a + b, 0);
                                return null;
                            }).filter(s => s !== null && !isNaN(s))
                        )].filter(s => !restoredAuto.includes(s)).sort((a, b) => a - b);
                    } else if (key === 'last_digit_sum') {
                        // 끝수합: 직전 1회차 끝수합만
                        const latestDraw = this.state.allDraws[0];
                        let latestTailSum = null;
                        if (latestDraw) {
                            if (latestDraw.tail_sum !== undefined && latestDraw.tail_sum !== null) latestTailSum = latestDraw.tail_sum;
                            else if (latestDraw.numbers && Array.isArray(latestDraw.numbers)) latestTailSum = latestDraw.numbers.reduce((a, b) => a + (b % 10), 0);
                        }
                        if (latestTailSum !== null && !restoredAuto.includes(latestTailSum)) systemExcluded = [latestTailSum];
                    } else if (key === 'ac_value') {
                        // AC값: 최근 10회에서 6회 초과 AC값 자동 제외
                        const acCount = {};
                        this.state.allDraws.slice(0, 10).forEach(d => {
                            let ac = null;
                            if (d.ac_value !== undefined && d.ac_value !== null) ac = d.ac_value;
                            else if (d.acValue !== undefined && d.acValue !== null) ac = d.acValue;
                            if (ac !== null) acCount[ac] = (acCount[ac] || 0) + 1;
                        });
                        systemExcluded = Object.entries(acCount)
                            .filter(([ac, cnt]) => cnt > 6 && !restoredAuto.includes(parseInt(ac)))
                            .map(([ac]) => parseInt(ac))
                            .sort((a, b) => a - b);
                    }
                }

                const hasManual = manualExcluded.length > 0;
                const hasSystem = systemExcluded.length > 0;

                if (hasManual || hasSystem) {
                    const label = key === 'last_digit_sum' ? '끝수합' : key === 'ac_value' ? 'AC값' : '합계';
                    html += `<div class="mt-4 pt-3 border-t border-slate-100 italic text-[10px] text-slate-400 font-bold mb-1">제외된 ${label}:</div>`;
                    html += `<div class="flex flex-wrap gap-1.5">`;

                    // 수동 제외 (Red)
                    if (hasManual) {
                        html += manualExcluded.slice().sort((a, b) => a - b).map(sum => `
                            <button onclick="FilterDashboard.removeExcludedSum('${def.id}', ${sum})"
                                class="inline-flex items-center gap-1 px-2.5 py-1 bg-red-600 text-white rounded-full text-[10px] font-black shadow-md hover:bg-red-700 transition-colors"
                                title="클릭 시 복원" style="background-color: #dc2626 !important; color: #ffffff !important;">
                                ${sum} <span style="font-size:11px;">✕</span>
                            </button>
                        `).join('');
                    }

                    // 자동 제외 (Indigo)
                    if (hasSystem) {
                        const displayFn = key === 'ac_value' ? (v => `AC${v}`) : (v => `${v}`);
                        html += systemExcluded.map(sum => `
                            <button onclick="FilterDashboard.restoreAutoExcludedSum('${def.id}', ${sum})"
                                class="inline-flex items-center gap-1 px-2.5 py-1 bg-indigo-600 text-white rounded-full text-[10px] font-black shadow-md hover:bg-indigo-700 transition-colors"
                                title="클릭 시 자동 제외 취소" style="background-color: #4f46e5 !important; color: #ffffff !important;">
                                ${displayFn(sum)} <span style="font-size:11px;">✕</span>
                            </button>
                        `).join('');
                    }

                    html += `</div>`;
                    html += `<div class="mt-1 text-[10px] text-slate-400 font-medium">🧩 수동: ${manualExcluded.length}개, 자동: ${systemExcluded.length}개</div>`;
                }
            }
        } else if (key === 'number_range_patterns') {
            const ranges = vals.ranges || {};
            const rangeTypes = {
                '1_10': { label: '1~10 (단번대)', count: 10 },
                '11_20': { label: '11~20 (십번대)', count: 10 },
                '21_30': { label: '21~30 (이십번대)', count: 10 },
                '31_40': { label: '31~40 (삼십번대)', count: 10 },
                '41_45': { label: '41~45 (사십번대)', count: 5 }
            };

            html += `<div class="flex flex-col gap-y-3">`;

            Object.keys(rangeTypes).forEach(type => {
                const info = rangeTypes[type];
                const f = ranges[type] || { min: 0, max: 6 };

                let [startNum, endNum] = type.split('_').map(Number);
                let numbersHtml = '';
                for (let n = startNum; n <= endNum; n++) {
                    const isEx = this.state.basket.excluded.includes(n);
                    const isFi = this.state.basket.fixed.includes(n);
                    let ballClass = "w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-black text-white shadow-sm border ";
                    // Colors based on lotto ball ranges
                    let color = '#fbcfe8'; let border = '#f9a8d4'; // default pinkish
                    if (n <= 10) { color = '#fbbf24'; border = '#f59e0b'; } // yellow
                    else if (n <= 20) { color = '#60a5fa'; border = '#3b82f6'; } // blue
                    else if (n <= 30) { color = '#f87171'; border = '#ef4444'; } // red
                    else if (n <= 40) { color = '#9ca3af'; border = '#6b7280'; } // gray
                    else { color = '#34d399'; border = '#10b981'; } // green
                    let style = `background-color: ${color}; border-color: ${border};`;

                    if (isFi) {
                        ballClass += "ball-fixed";
                        style = "background-color: #2563eb; border-color: #3b82f6;";
                    } else if (isEx) {
                        ballClass += "ball-excluded";
                        style = "background-color: #94a3b8; border-color: #64748b;";
                    }

                    numbersHtml += `<span class="${ballClass}" style="${style}">${String(n).padStart(2, '0')}</span>`;
                }

                html += `
                    <div class="flex flex-col p-3 bg-slate-50 border border-slate-100 rounded-xl gap-2">
                        <div class="flex items-center justify-between">
                            <div class="flex items-center gap-1.5 ml-1">
                                <span class="text-xs font-bold text-slate-700">${info.label}</span>
                                <span class="text-[11px] font-black text-slate-400">(${info.count}개)</span>
                            </div>
                            <div class="flex items-center gap-1.5 shrink-0">
                                <span class="text-[10px] text-slate-400 font-bold uppercase">Min</span>
                                <input type="number" value="${f.min}" 
                                    onchange="FilterDashboard.updateNumberRangeFilter('${def.id}', '${type}', 'min', this.value)"
                                    class="w-10 h-7 text-center text-[11px] font-black text-slate-700 bg-white border border-slate-200 rounded focus:ring-1 focus:ring-indigo-500 p-0">
                                <span class="text-slate-300 font-bold">~</span>
                                <span class="text-[10px] text-slate-400 font-bold uppercase">Max</span>
                                <input type="number" value="${f.max}" 
                                    onchange="FilterDashboard.updateNumberRangeFilter('${def.id}', '${type}', 'max', this.value)"
                                    class="w-10 h-7 text-center text-[11px] font-black text-slate-700 bg-white border border-slate-200 rounded focus:ring-1 focus:ring-indigo-500 p-0">
                            </div>
                        </div>
                        <div class="flex flex-wrap gap-1 mt-1 pl-1">
                            ${numbersHtml}
                        </div>
                    </div>`;
            });

            // Entropy
            const ent = ranges['entropy'] || { min: '0.00', max: '3.00' };
            html += `
                    <div class="flex items-center justify-between p-2 bg-slate-50 border border-slate-100 rounded-xl mt-1">
                        <span class="text-[11px] font-black text-indigo-600 ml-1">엔트로피 (불확실성)</span>
                        <div class="flex items-center gap-1.5 shrink-0">
                            <span class="text-[10px] text-slate-400 font-bold uppercase">Min</span>
                            <input type="text" value="${parseFloat(ent.min || 0).toFixed(2)}" 
                                onchange="this.value=parseFloat(this.value||0).toFixed(2); FilterDashboard.updateNumberRangeFilter('${def.id}', 'entropy', 'min', this.value)"
                                class="w-12 h-7 text-center text-[11px] font-black text-slate-700 bg-white border border-slate-200 rounded focus:ring-1 focus:ring-indigo-500 p-0">
                            <span class="text-slate-300 font-bold">~</span>
                            <span class="text-[10px] text-slate-400 font-bold uppercase">Max</span>
                            <input type="text" value="${parseFloat(ent.max || 3).toFixed(2)}" 
                                onchange="this.value=parseFloat(this.value||0).toFixed(2); FilterDashboard.updateNumberRangeFilter('${def.id}', 'entropy', 'max', this.value)"
                                class="w-12 h-7 text-center text-[11px] font-black text-slate-700 bg-white border border-slate-200 rounded focus:ring-1 focus:ring-indigo-500 p-0">
                        </div>
                    </div>`;

            html += `</div>`;
        } else if (key === 'odd_even_pattern') {
            // 홀짝 패턴: 특별한 7개 버튼 UI + 제외 배지
            const ratios = ['6:0', '5:1', '4:2', '3:3', '2:4', '1:5', '0:6'];
            const selected = vals.selectedRatios || [];
            const manualExcluded = vals.excludedOddEvens || [];
            const restoredAuto = vals.restoredAutoOddEvens || [];

            // 자동 제외 계산
            let systemExcluded = [];
            if (vals.recent10FilterActive && this.state.allDraws && this.state.allDraws.length >= 10) {
                const recent10 = this.state.allDraws.slice(0, 10);
                const counts = {};
                recent10.forEach(d => {
                    let ratio = null;
                    if (d.odd_even_ratio) ratio = d.odd_even_ratio;
                    else if (d.numbers) {
                        let odd = d.numbers.filter(n => n % 2 !== 0).length;
                        ratio = `${odd}:${6 - odd}`;
                    }
                    if (ratio) counts[ratio] = (counts[ratio] || 0) + 1;
                });
                systemExcluded = Object.entries(counts)
                    .filter(([r, cnt]) => cnt > 6 && !restoredAuto.includes(r))
                    .map(([r]) => r)
                    .sort();
            }

            let btns = '';
            ratios.forEach(r => {
                const isActive = selected.includes(r);
                const bg = isActive ? 'bg-indigo-600 text-white border-indigo-600 shadow-sm' : 'bg-white text-slate-400 border-slate-200 hover:bg-slate-50';
                btns += `<button onclick="FilterDashboard.toggleDiscreteValue('${def.id}', 'selectedRatios', '${r}')" 
                                class="w-9 h-9 flex items-center justify-center rounded-full border text-[9px] font-black transition-all ${bg}">${r}</button>`;
            });

            html += `
                <div class="text-xs font-bold text-slate-500 mb-2 mt-1">홀짝 비중 선택</div>
                <div class="flex justify-start items-center gap-1.5">${btns}</div>`;

            if (manualExcluded.length > 0 || systemExcluded.length > 0) {
                html += `<div class="mt-4 pt-3 border-t border-slate-100 italic text-[10px] text-slate-400 font-bold mb-1">제외된 홀짝 비율:</div>`;
                html += `<div class="flex flex-wrap gap-1.5">`;

                if (manualExcluded.length > 0) {
                    html += manualExcluded.sort().map(r => `
                            <button onclick="FilterDashboard.removeExcludedSum('${def.id}', '${r}')"
                                class="inline-flex items-center gap-1 px-2.5 py-1 bg-red-600 text-white rounded-full text-[10px] font-black shadow-md hover:bg-red-700 transition-colors"
                                title="클릭 시 복원">
                                ${r} <span style="font-size:11px;">✕</span>
                            </button>
                        `).join('');
                }

                if (systemExcluded.length > 0) {
                    html += systemExcluded.map(r => `
                            <button onclick="FilterDashboard.restoreAutoExcludedSum('${def.id}', '${r}')"
                                class="inline-flex items-center gap-1 px-2.5 py-1 bg-indigo-600 text-white rounded-full text-[10px] font-black shadow-md hover:bg-indigo-700 transition-colors"
                                title="클릭 시 자동 제외 취소">
                                ${r} <span style="font-size:11px;">✕</span>
                            </button>
                        `).join('');
                }
                html += `</div>`;
            }
        } else if (key === 'high_low_pattern') {
            const ratios = ['6:0', '5:1', '4:2', '3:3', '2:4', '1:5', '0:6'];
            const selected = vals.selectedRatios || [];
            const manualExcluded = vals.excludedHighLows || [];
            const restoredAuto = vals.restoredAutoHighLows || [];

            // 자동 제외 계산
            let systemExcluded = [];
            if (vals.recent10FilterActive && this.state.allDraws && this.state.allDraws.length >= 10) {
                const recent10 = this.state.allDraws.slice(0, 10);
                const counts = {};
                recent10.forEach(d => {
                    let ratio = null;
                    if (d.high_low_ratio) ratio = d.high_low_ratio;
                    else if (d.numbers) {
                        let low = d.numbers.filter(n => n <= 22).length;
                        ratio = `${low}:${6 - low}`;
                    }
                    if (ratio) counts[ratio] = (counts[ratio] || 0) + 1;
                });
                systemExcluded = Object.entries(counts)
                    .filter(([r, cnt]) => cnt > 6 && !restoredAuto.includes(r))
                    .map(([r]) => r)
                    .sort();
            }

            let btns = '';
            ratios.forEach(r => {
                const isActive = selected.includes(r);
                const bg = isActive ? 'bg-indigo-600 text-white border-indigo-600 shadow-sm' : 'bg-white text-slate-400 border-slate-200 hover:bg-slate-50';
                btns += `<button onclick="FilterDashboard.toggleDiscreteValue('${def.id}', 'selectedRatios', '${r}')" 
                                class="w-9 h-9 flex items-center justify-center rounded-full border text-[9px] font-black transition-all ${bg}">${r}</button>`;
            });

            html += `
                <div class="text-xs font-bold text-slate-500 mb-2 mt-1">저고 비중 선택</div>
                <div class="flex justify-start items-center gap-1.5">${btns}</div>`;

            if (manualExcluded.length > 0 || systemExcluded.length > 0) {
                html += `<div class="mt-4 pt-3 border-t border-slate-100 italic text-[10px] text-slate-400 font-bold mb-1">제외된 저고 비율:</div>`;
                html += `<div class="flex flex-wrap gap-1.5">`;

                if (manualExcluded.length > 0) {
                    html += manualExcluded.sort().map(r => `
                            <button onclick="FilterDashboard.removeExcludedSum('${def.id}', '${r}')"
                                class="inline-flex items-center gap-1 px-2.5 py-1 bg-red-600 text-white rounded-full text-[10px] font-black shadow-md hover:bg-red-700 transition-colors"
                                title="클릭 시 복원">
                                ${r} <span style="font-size:11px;">✕</span>
                            </button>
                        `).join('');
                }

                if (systemExcluded.length > 0) {
                    html += systemExcluded.map(r => `
                            <button onclick="FilterDashboard.restoreAutoExcludedSum('${def.id}', '${r}')"
                                class="inline-flex items-center gap-1 px-2.5 py-1 bg-indigo-600 text-white rounded-full text-[10px] font-black shadow-md hover:bg-indigo-700 transition-colors"
                                title="클릭 시 자동 제외 취소">
                                ${r} <span style="font-size:11px;">✕</span>
                            </button>
                        `).join('');
                }
                html += `</div>`;
            }
        } else if (key === 'carryover_count') {
            const selectedCounts = vals.selectedCounts || [];
            const selectedBonusCounts = vals.selectedBonusIncludedCounts || [];
            const targetBasic = this.state.dynamicTargets['carryover_count'] || [];
            const targetBonus = this.state.dynamicTargets['carryover_bonus_count'] || [];

            const getBtnHtml = (activeArr, value, fieldName) => {
                const isActive = activeArr.includes(value);
                const bg = isActive ? 'bg-blue-600 text-white border-blue-600 shadow-md' : 'bg-white text-slate-400 border-slate-200 hover:bg-blue-50';
                return `<button onclick="FilterDashboard.toggleDiscreteValue('${def.id}', '${fieldName}', ${value})" class="w-8 h-8 flex items-center justify-center rounded-lg border text-[11px] font-black transition-colors ${bg}">${value}</button>`;
            };

            let basicBtns = Array.from({ length: 7 }, (_, i) => getBtnHtml(selectedCounts, i, 'selectedCounts')).join('');
            let bonusBtns = Array.from({ length: 7 }, (_, i) => getBtnHtml(selectedBonusCounts, i, 'selectedBonusIncludedCounts')).join('');

            html += `
                <div class="mt-2 grid grid-cols-2 gap-4">
                    <div class="space-y-4 pr-4 border-r border-slate-100">
                        <div class="p-3 bg-slate-50/50 rounded-xl border border-slate-100 min-h-[110px]">
                            <div class="flex items-center justify-between mb-2">
                                <div class="text-xs font-bold text-blue-600">기본 이월수</div>
                                <span class="text-[11px] font-black text-blue-600">${targetBasic.length}개</span>
                            </div>
                            <div class="flex flex-wrap gap-1">${this.renderBalls(targetBasic)}</div>
                        </div>
                        <div class="space-y-2 px-1">
                            <div class="text-[10px] font-bold text-slate-400 uppercase tracking-tighter">포함 개수 설정</div>
                            <div class="flex flex-wrap gap-1">${basicBtns}</div>
                        </div>
                    </div>
                    <div class="space-y-4">
                        <div class="p-3 bg-slate-50/50 rounded-xl border border-slate-100 min-h-[110px]">
                            <div class="flex items-center justify-between mb-2">
                                <div class="text-xs font-bold text-blue-600">보너스 포함</div>
                                <span class="text-[11px] font-black text-blue-600">${targetBonus.length}개</span>
                            </div>
                            <div class="flex flex-wrap gap-1">${this.renderBalls(targetBonus)}</div>
                        </div>
                        <div class="space-y-2 px-1">
                            <div class="text-[10px] font-bold text-slate-400 uppercase tracking-tighter">포함 개수 설정</div>
                            <div class="flex flex-wrap gap-1">${bonusBtns}</div>
                        </div>
                    </div>
                </div>`;
        } else if (key === 'multiple_3_count') {
            // 배수 패턴: 조합 필터 상세 UI
            const filters = vals.filters || {};
            const multipleDefinitions = {
                '3배수': [3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36, 39, 42, 45],
                '4배수': [4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44],
                '5배수': [5, 10, 15, 20, 25, 30, 35, 40, 45],
                '3·4배수': [12, 24, 36],
                '3·5배수': [15, 30, 45],
                '4·5배수': [20, 40],
                '배수외': [1, 2, 7, 11, 13, 14, 17, 19, 22, 23, 26, 29, 31, 34, 37, 38, 41, 43]
            };
            const multipleColors = {
                '3배수': '#3B82F6', '4배수': '#10B981', '5배수': '#EC4899',
                '3·4배수': '#8B5CF6', '3·5배수': '#F59E0B', '4·5배수': '#14B8A6',
                '배수외': '#6B7280'
            };

            html += `<div class="space-y-4 w-full">`;

            Object.keys(multipleDefinitions).forEach(type => {
                const f = filters[type] || { min: 0, max: 6 };
                const numbersHtml = multipleDefinitions[type].map(n => {
                    const isEx = this.state.basket.excluded.includes(n);
                    const isFi = this.state.basket.fixed.includes(n);
                    let ballClass = "w-7 h-7 rounded-full flex items-center justify-center text-[11px] font-black text-white shadow-sm border ";
                    let style = `background-color: ${multipleColors[type]}; border-color: transparent;`;

                    if (isFi) {
                        ballClass += "ball-fixed";
                        style = "background-color: #2563eb; border-color: #3b82f6;";
                    } else if (isEx) {
                        ballClass += "ball-excluded";
                        style = "background-color: #94a3b8; border-color: #64748b;";
                    }

                    return `<span class="${ballClass}" style="${style}">${String(n).padStart(2, '0')}</span>`;
                }).join('');

                const gapClass = type === '배수외' ? 'gap-1' : 'gap-1.5';

                html += `
                    <div class="flex items-center justify-between border-b border-slate-100 pb-3 last:border-0 w-full mb-2">
                        <div class="flex-1">
                            <div class="flex items-center gap-2 mb-1.5">
                                <span class="text-xs font-bold text-slate-700 w-16">${type}</span>
                                <span class="text-[11px] font-black text-slate-400">(${multipleDefinitions[type].length}개)</span>
                            </div>
                            <div class="flex flex-wrap ${gapClass}">
                                ${numbersHtml}
                            </div>
                        </div>
                        <div class="flex items-center gap-1.5 ml-4 shrink-0">
                            <span class="text-[10px] text-slate-400 font-bold uppercase">Min</span>
                            <input type="number" value="${f.min}" 
                                onchange="FilterDashboard.updateMultipleFilter('${def.id}', '${type}', 'min', this.value)"
                                class="w-12 h-8 text-center text-xs font-black text-slate-700 bg-white border border-slate-200 rounded-lg focus:ring-1 focus:ring-indigo-500 p-0">
                            <span class="text-slate-300 font-bold">~</span>
                            <span class="text-[10px] text-slate-400 font-bold uppercase">Max</span>
                            <input type="number" value="${f.max}" 
                                onchange="FilterDashboard.updateMultipleFilter('${def.id}', '${type}', 'max', this.value)"
                                class="w-12 h-8 text-center text-xs font-black text-slate-700 bg-white border border-slate-200 rounded-lg focus:ring-1 focus:ring-indigo-500 p-0">
                        </div>
                    </div>`;
            });

            html += `</div>`;
            return html;
        } else if (key === 'magic_square_pattern') {
            const filters = vals.filters || {};
            const gungDefinitions = {
                '1궁': [1, 2, 3, 4, 5],
                '2궁': [6, 7, 8, 9, 10],
                '3궁': [11, 12, 13, 14, 15],
                '4궁': [16, 17, 18, 19, 20],
                '5궁': [21, 22, 23, 24, 25],
                '6궁': [26, 27, 28, 29, 30],
                '7궁': [31, 32, 33, 34, 35],
                '8궁': [36, 37, 38, 39, 40],
                '9궁': [41, 42, 43, 44, 45]
            };
            const gungColors = {
                '1궁': '#EF4444', '2궁': '#F97316', '3궁': '#F59E0B',
                '4궁': '#84CC16', '5궁': '#10B981', '6궁': '#06B6D4',
                '7궁': '#3B82F6', '8궁': '#8B5CF6', '9궁': '#EC4899'
            };

            html += `<div class="grid grid-cols-1 xl:grid-cols-2 gap-3 w-full">`;

            Object.keys(gungDefinitions).forEach(type => {
                const f = filters[type] || { min: 0, max: 5 };
                const numbersHtml = gungDefinitions[type].map(n => {
                    const isEx = this.state.basket.excluded.includes(n);
                    const isFi = this.state.basket.fixed.includes(n);
                    let ballClass = "w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-black text-white shadow-sm border ";
                    let style = `background-color: ${gungColors[type]}; border-color: transparent;`;

                    if (isFi) {
                        ballClass += "ball-fixed";
                        style = "background-color: #2563eb; border-color: #3b82f6;";
                    } else if (isEx) {
                        ballClass += "ball-excluded";
                        style = "background-color: #94a3b8; border-color: #64748b;";
                    }

                    return `<span class="${ballClass}" style="${style}">${String(n).padStart(2, '0')}</span>`;
                }).join('');

                html += `
                    <div class="flex items-center justify-between p-2.5 bg-slate-50 border border-slate-100 rounded-xl">
                        <div class="flex-1">
                            <div class="flex items-center gap-2 mb-1">
                                <span class="font-bold text-slate-700 text-xs w-8">${type}</span>
                            </div>
                            <div class="flex flex-wrap gap-1">
                                ${numbersHtml}
                            </div>
                        </div>
                        <div class="flex items-center gap-1.5 ml-2 shrink-0">
                            <span class="text-[10px] text-slate-400 font-bold uppercase">Min</span>
                            <input type="number" value="${f.min}" 
                                onchange="FilterDashboard.updateMagicSquareFilter('${def.id}', '${type}', 'min', this.value)"
                                class="w-10 h-8 text-center text-xs font-black text-slate-700 bg-white border border-slate-200 rounded-lg focus:ring-1 focus:ring-indigo-500 p-0 shadow-sm">
                            <span class="text-slate-300 font-bold text-xs">~</span>
                            <span class="text-[10px] text-slate-400 font-bold uppercase">Max</span>
                            <input type="number" value="${f.max}" 
                                onchange="FilterDashboard.updateMagicSquareFilter('${def.id}', '${type}', 'max', this.value)"
                                class="w-10 h-8 text-center text-xs font-black text-slate-700 bg-white border border-slate-200 rounded-lg focus:ring-1 focus:ring-indigo-500 p-0 shadow-sm">
                        </div>
                    </div>`;
            });

            html += `</div>`;
        } else if (key === 'lotto_paper_pattern') {
            const groups = vals.groups || {};
            const garoDefinitions = {
                '\uac00\ub85c1': [1, 2, 3, 4, 5, 6, 7], '\uac00\ub85c2': [8, 9, 10, 11, 12, 13, 14], '\uac00\ub85c3': [15, 16, 17, 18, 19, 20, 21],
                '\uac00\ub85c4': [22, 23, 24, 25, 26, 27, 28], '\uac00\ub85c5': [29, 30, 31, 32, 33, 34, 35], '\uac00\ub85c6': [36, 37, 38, 39, 40, 41, 42],
                '\uac00\ub85c7': [43, 44, 45]
            };
            const seroDefinitions = {
                '\uc138\ub85c1': [1, 8, 15, 22, 29, 36, 43], '\uc138\ub85c2': [2, 9, 16, 23, 30, 37, 44], '\uc138\ub85c3': [3, 10, 17, 24, 31, 38, 45],
                '\uc138\ub85c4': [4, 11, 18, 25, 32, 39], '\uc138\ub85c5': [5, 12, 19, 26, 33, 40], '\uc138\ub85c6': [6, 13, 20, 27, 34, 41],
                '\uc138\ub85c7': [7, 14, 21, 28, 35, 42]
            };
            const paperColors = {
                '\uac00\ub85c1': '#E11D48', '\uac00\ub85c2': '#E11D48', '\uac00\ub85c3': '#BE123C', '\uac00\ub85c4': '#BE123C',
                '\uac00\ub85c5': '#9F1239', '\uac00\ub85c6': '#9F1239', '\uac00\ub85c7': '#881337',
                '\uc138\ub85c1': '#2563EB', '\uc138\ub85c2': '#2563EB', '\uc138\ub85c3': '#1D4ED8', '\uc138\ub85c4': '#1D4ED8',
                '\uc138\ub85c5': '#1E40AF', '\uc138\ub85c6': '#1E40AF', '\uc138\ub85c7': '#1E3A8A'
            };

            const buildRow = (type, nums) => {
                const f = groups[type] || { min: 0, max: 6 };
                const numbersHtml = nums.map(n => {
                    const isEx = this.state.basket.excluded.includes(n);
                    const isFi = this.state.basket.fixed.includes(n);
                    let ballClass = "w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-black text-white shadow-sm border ";
                    const color = paperColors[type] || '#94a3b8';
                    let style = `background-color: ${color}; border-color: transparent;`;
                    if (isFi) { ballClass += "ball-fixed"; style = "background-color: #2563eb; border-color: #3b82f6;"; }
                    else if (isEx) { ballClass += "ball-excluded"; style = "background-color: #94a3b8; border-color: #64748b;"; }
                    return `<span class="${ballClass}" style="${style}">${String(n).padStart(2, '0')}</span>`;
                }).join('');
                return `
                    <div class="flex items-center justify-between p-2.5 bg-slate-50 border border-slate-100 rounded-xl">
                        <div class="flex-1">
                            <div class="flex items-center gap-2 mb-1">
                                <span class="font-bold text-slate-700 text-xs w-10">${type}</span>
                            </div>
                            <div class="flex flex-wrap gap-1">
                                ${numbersHtml}
                            </div>
                        </div>
                        <div class="flex items-center gap-1.5 ml-2 shrink-0">
                            <span class="text-[10px] text-slate-400 font-bold uppercase">Min</span>
                            <input type="number" value="${f.min}"
                                onchange="FilterDashboard.updateLottoPaperFilter('${def.id}', '${type}', 'min', this.value)"
                                class="w-10 h-8 text-center text-xs font-black text-slate-700 bg-white border border-slate-200 rounded-lg focus:ring-1 focus:ring-indigo-500 p-0 shadow-sm">
                            <span class="text-slate-300 font-bold text-xs">~</span>
                            <span class="text-[10px] text-slate-400 font-bold uppercase">Max</span>
                            <input type="number" value="${f.max}"
                                onchange="FilterDashboard.updateLottoPaperFilter('${def.id}', '${type}', 'max', this.value)"
                                class="w-10 h-8 text-center text-xs font-black text-slate-700 bg-white border border-slate-200 rounded-lg focus:ring-1 focus:ring-indigo-500 p-0 shadow-sm">
                        </div>
                    </div>`;
            };

            html += `<div class="grid grid-cols-2 gap-x-4 gap-y-3 w-full">`;
            html += `<div class="flex flex-col gap-3">`;
            Object.entries(garoDefinitions).forEach(([type, nums]) => { html += buildRow(type, nums); });
            html += `</div>`;
            html += `<div class="flex flex-col gap-3">`;
            Object.entries(seroDefinitions).forEach(([type, nums]) => { html += buildRow(type, nums); });
            html += `</div>`;
            html += `</div>`;

        } else if (key === 'hot_cold_5' || key === 'hot_cold_10' || key === 'hot_cold_15' || key === 'hot_cold_20') {
            const period = parseInt(key.split('_').pop());

            // 설정 정규화: hot_cold.html이 저장하는 flat 포맷(periodFilter.hotMin/Max)과
            // filter_dashboard가 저장하는 배열 포맷(hotRange) 양스 대응
            let effVals = vals;
            if (vals.periodFilter) {
                // hot_cold.html이 저장한 구조: periodFilter 내에 flat 텍스트
                const pf = vals.periodFilter;
                effVals = {
                    hotRange: [parseInt(pf.hotMin ?? 0), parseInt(pf.hotMax ?? 6)],
                    warmRange: [parseInt(pf.neutralMin ?? 0), parseInt(pf.neutralMax ?? 6)],
                    coldRange: [parseInt(pf.coldMin ?? 0), parseInt(pf.coldMax ?? 6)]
                };
            }
            const hotRange = effVals.hotRange || [0, 6];
            const warmRange = effVals.warmRange || [0, 6];
            const coldRange = effVals.coldRange || [0, 6];

            // CRITERIA (hot_cold.html과 동일)
            const CRITERIA = {
                5: { hot: 2, neutralMin: 1, neutralMax: 1 },
                10: { hot: 3, neutralMin: 1, neutralMax: 2 },
                15: { hot: 4, neutralMin: 2, neutralMax: 3 },
                20: { hot: 5, neutralMin: 2, neutralMax: 4 }
            };
            const crit = CRITERIA[period] || CRITERIA[10];

            // 최근 N회차 번호 출현 횟수 계산
            const recentDraws = this.state.allDraws.slice(0, period);
            const countMap = {};
            for (let n = 1; n <= 45; n++) countMap[n] = 0;
            recentDraws.forEach(d => { (d.numbers || []).forEach(n => { if (n >= 1 && n <= 45) countMap[n]++; }); });

            const hotNums = [], warmNums = [], coldNums = [];
            for (let n = 1; n <= 45; n++) {
                const c = countMap[n];
                if (c >= crit.hot) hotNums.push(n);
                else if (c >= crit.neutralMin) warmNums.push(n);
                else coldNums.push(n);
            }

            // 공 렌더 헬퍼
            const ballColor = n => {
                if (n <= 10) return '#fbbf24';
                if (n <= 20) return '#60a5fa';
                if (n <= 30) return '#f87171';
                if (n <= 40) return '#9ca3af';
                return '#34d399';
            };
            const renderBallsList = (nums, borderColor) => nums.map(n => {
                const isEx = this.state.basket.excluded.includes(n);
                const isFi = this.state.basket.fixed.includes(n);
                let style = `background-color:${ballColor(n)}; border:1px solid transparent;`;
                if (isFi) style = 'background-color:#2563eb; border:1px solid #3b82f6;';
                else if (isEx) style = 'background-color:#94a3b8; border:1px solid #64748b;';
                return `<span class="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-black text-white shadow-sm" style="${style}">${String(n).padStart(2, '0')}</span>`;
            }).join('');

            const rows = [
                { label: '🔴 Hot (과열)', color: '#DC2626', bgColor: '#FEF2F2', field: 'hotRange', values: hotRange, nums: hotNums },
                { label: '⚪ Neutral (중립)', color: '#6B7280', bgColor: '#F9FAFB', field: 'warmRange', values: warmRange, nums: warmNums },
                { label: '🔵 Cold (냉각)', color: '#2563EB', bgColor: '#EFF6FF', field: 'coldRange', values: coldRange, nums: coldNums }
            ];

            html += `<div class="flex flex-col gap-3">`;
            rows.forEach(row => {
                html += `
                    <div class="flex flex-col gap-2 p-3 rounded-xl border" style="background-color:${row.bgColor}; border-color: ${row.color}33;">
                        <div class="flex items-center justify-between">
                            <span class="text-xs font-black shrink-0" style="color:${row.color}">${row.label} <span class="text-[11px] font-black opacity-60">(${row.nums.length}개)</span></span>
                            <div class="flex items-center gap-1.5 shrink-0">
                                <span class="text-[10px] text-slate-400 font-bold uppercase">Min</span>
                                <input type="number" min="0" max="6" value="${row.values[0]}"
                                    onchange="FilterDashboard.updateHotColdFilter('${def.id}', '${row.field}', 0, this.value)"
                                    class="w-10 h-7 text-center text-xs font-black text-slate-700 bg-white border border-slate-200 rounded-lg focus:ring-1 focus:ring-indigo-500 p-0 shadow-sm">
                                <span class="text-slate-300 font-bold">~</span>
                                <span class="text-[10px] text-slate-400 font-bold uppercase">Max</span>
                                <input type="number" min="0" max="6" value="${row.values[1]}"
                                    onchange="FilterDashboard.updateHotColdFilter('${def.id}', '${row.field}', 1, this.value)"
                                    class="w-10 h-7 text-center text-xs font-black text-slate-700 bg-white border border-slate-200 rounded-lg focus:ring-1 focus:ring-indigo-500 p-0 shadow-sm">
                            </div>
                        </div>
                        <div class="flex flex-wrap gap-1 pt-1 border-t" style="border-color:${row.color}22;">
                            ${renderBallsList(row.nums)}
                        </div>
                    </div>`;
            });
            html += `</div>`;


        } else if (key === 'missing_period') {
            const ranges = vals.ranges || {};

            // 각 번호의 현재 미출현 회차 계산 (allDraws = 최신회차 순)
            const draws = this.state.allDraws || [];
            const missCount = {};
            for (let n = 1; n <= 45; n++) missCount[n] = 0;
            if (draws.length > 0) {
                // 최신회차부터 역으로 추적: 각 번호가 처음 등장하는 시점까지 카운트
                const found = new Set();
                for (let i = 0; i < draws.length && found.size < 45; i++) {
                    (draws[i].numbers || []).forEach(n => {
                        if (!found.has(n)) {
                            missCount[n] = i; // i회 전 마지막 등장 → 미출현 i회
                            found.add(n);
                        }
                    });
                }
            }

            // 그룹 분류
            const groupNums = { 1: [], 2: [], 3: [], 4: [] };
            for (let n = 1; n <= 45; n++) {
                const c = missCount[n];
                if (c <= 5) groupNums[1].push(n);
                else if (c <= 10) groupNums[2].push(n);
                else if (c <= 15) groupNums[3].push(n);
                else groupNums[4].push(n);
            }

            const ballColor = n => {
                if (n <= 10) return '#fbbf24';
                if (n <= 20) return '#60a5fa';
                if (n <= 30) return '#f87171';
                if (n <= 40) return '#9ca3af';
                return '#34d399';
            };
            const renderMissBalls = nums => nums.map(n => {
                const isEx = this.state.basket?.excluded?.includes(n);
                const isFi = this.state.basket?.fixed?.includes(n);
                let style = `background-color:${ballColor(n)}; border:1px solid transparent;`;
                if (isFi) style = 'background-color:#2563eb; border:1px solid #3b82f6;';
                else if (isEx) style = 'background-color:#94a3b8; border:1px solid #64748b;';
                return `<span class="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-black text-white shadow-sm" style="${style}">${String(n).padStart(2, '0')}</span>`;
            }).join('');

            const groupDefs = [
                { id: 1, label: '1-5\ud68c (\ucd5c\uadfc)', color: '#E64A19', bgColor: '#FFF3EF', minKey: 'r1Min', maxKey: 'r1Max' },
                { id: 2, label: '6-10\ud68c (\uc911\uac04)', color: '#4B5563', bgColor: '#F9FAFB', minKey: 'r2Min', maxKey: 'r2Max' },
                { id: 3, label: '11-15\ud68c (\uc7a5\uae30)', color: '#16A34A', bgColor: '#F0FDF4', minKey: 'r3Min', maxKey: 'r3Max' },
                { id: 4, label: '16+\ud68c (\uadf9\uc7a5\uae30)', color: '#1A6DFF', bgColor: '#EFF6FF', minKey: 'r4Min', maxKey: 'r4Max' }
            ];


            html += `<div class="flex flex-col gap-3">`;
            groupDefs.forEach(g => {
                const minVal = ranges[g.minKey] ?? 0;
                const maxVal = ranges[g.maxKey] ?? 6;
                const nums = groupNums[g.id] || [];
                html += `
                    <div class="flex flex-col gap-2 p-3 rounded-xl border" style="background-color:${g.bgColor}; border-color:${g.color}33;">
                        <div class="flex items-center justify-between">
                            <span class="text-xs font-black shrink-0" style="color:${g.color}">${g.label} <span class="text-[11px] font-black opacity-60">(${nums.length}개)</span></span>
                            <div class="flex items-center gap-1.5 shrink-0">
                                <span class="text-[10px] text-slate-400 font-bold uppercase">Min</span>
                                <input type="number" min="0" max="6" value="${minVal}"
                                    onchange="FilterDashboard.updateMissingPeriodFilter('${def.id}', '${g.minKey}', this.value)"
                                    class="w-10 h-7 text-center text-xs font-black text-slate-700 bg-white border border-slate-200 rounded-lg focus:ring-1 focus:ring-indigo-500 p-0 shadow-sm">
                                <span class="text-slate-300 font-bold">~</span>
                                <span class="text-[10px] text-slate-400 font-bold uppercase">Max</span>
                                <input type="number" min="0" max="6" value="${maxVal}"
                                    onchange="FilterDashboard.updateMissingPeriodFilter('${def.id}', '${g.maxKey}', this.value)"
                                    class="w-10 h-7 text-center text-xs font-black text-slate-700 bg-white border border-slate-200 rounded-lg focus:ring-1 focus:ring-indigo-500 p-0 shadow-sm">
                            </div>
                        </div>
                        <div class="flex flex-wrap gap-1 pt-1 border-t" style="border-color:${g.color}22;">
                            ${renderMissBalls(nums)}
                        </div>
                    </div>`;
            });
            html += `</div>`;



        } else if (key === 'missing_custom_filter') {
            const savedFilters = vals.filters || [];

            if (savedFilters.length === 0) {
                html += `
                    <div class="flex flex-col items-center justify-center py-6 text-center gap-2">
                        <span class="material-symbols-outlined text-3xl text-slate-300">tune</span>
                        <p class="text-xs text-slate-400 font-bold">저장된 커스텀 필터가 없습니다.</p>
                        <a href="missing.html" class="mt-1 text-xs font-black text-indigo-600 hover:underline">미출현 페이지에서 추가하기 →</a>
                    </div>`;
            } else {
                const ballColor = n => {
                    if (n <= 10) return '#fbbf24';
                    if (n <= 20) return '#60a5fa';
                    if (n <= 30) return '#f87171';
                    if (n <= 40) return '#9ca3af';
                    return '#34d399';
                };
                html += `<div class="flex flex-col gap-3">`;
                savedFilters.forEach(f => {
                    const isEnabled = f.enabled || false;
                    const nums = [...new Set(f.numbers || [])].sort((a, b) => a - b);
                    html += `
                        <div class="flex flex-col gap-2 p-3 rounded-xl border ${isEnabled ? 'border-indigo-300 bg-indigo-50/30' : 'border-slate-200 bg-white opacity-70'}">
                            <div class="flex items-center justify-between">
                                <span class="text-xs font-black text-slate-700">${f.name || '미출현그룹'} <span class="text-[11px] font-black text-slate-400">(${nums.length}개 / ${f.minCount ?? 0}~${f.maxCount ?? 6}개)</span></span>
                                <span class="text-[10px] font-black px-2 py-0.5 rounded-full ${isEnabled ? 'bg-indigo-600 text-white' : 'bg-slate-200 text-slate-500'}">${isEnabled ? 'ON' : 'OFF'}</span>
                            </div>
                            <div class="flex flex-wrap gap-1 pt-1 border-t border-slate-100">
                                ${nums.map(n => `<span class="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-black text-white shadow-sm" style="background-color:${ballColor(n)}">${String(n).padStart(2, '0')}</span>`).join('')}
                            </div>
                        </div>`;
                });
                html += `</div>
                <div class="mt-2 text-center">
                    <a href="missing.html" class="text-xs font-black text-indigo-600 hover:underline">미출현 페이지에서 편집 →</a>
                </div>`;
            }

        } else if (key === 'tail_digit_patterns') {


            const digitFilters = vals.filters || {};

            html += `
                <div class="flex items-center justify-between mb-4">
                    <div class="text-xs font-bold text-slate-500 uppercase tracking-tighter">0~9끝 개수 (Min ~ Max)</div>
                </div>
                <div class="grid grid-cols-2 gap-x-6 gap-y-3">`;

            for (let i = 0; i < 10; i++) {
                const f = digitFilters[i] || { min: 0, max: 6 };
                // 해당 끝수 대상수 추출
                const tailTargets = [];
                for (let n = 1; n <= 45; n++) if (n % 10 === i) tailTargets.push(n);

                // 컴팩트한 공 렌더링 (w-6 h-6)
                const ballHtml = tailTargets.map(n => {
                    const isEx = this.state.basket.excluded.includes(n);
                    const isFi = this.state.basket.fixed.includes(n);
                    let ballClass = "w-6 h-6 flex-shrink-0 flex items-center justify-center rounded-full text-[10px] font-black text-white shadow-sm border ";

                    if (isFi) ballClass += "bg-blue-600 border-blue-400 ball-fixed";
                    else if (isEx) ballClass += "bg-slate-400 border-slate-500 ball-excluded";
                    else {
                        if (n <= 10) ballClass += "bg-amber-400 border-amber-500";
                        else if (n <= 20) ballClass += "bg-blue-500 border-blue-600";
                        else if (n <= 30) ballClass += "bg-rose-500 border-rose-600";
                        else if (n <= 40) ballClass += "bg-slate-500 border-slate-600";
                        else ballClass += "bg-emerald-500 border-emerald-600";
                    }
                    return `<span class="${ballClass}">${String(n).padStart(2, '0')}</span>`;
                }).join('');

                html += `
                    <div class="flex flex-col p-2 bg-slate-50 border border-slate-100 rounded-xl">
                        <div class="flex items-center justify-between gap-2 overflow-hidden">
                            <div class="flex items-center gap-1.5 flex-1 min-w-0">
                                <span class="w-7 h-7 flex-shrink-0 flex items-center justify-center rounded-full bg-slate-600 text-white text-[9px] font-black">${i}끝</span>
                                <span class="text-[11px] font-black text-indigo-600 flex-shrink-0">(${tailTargets.length}개)</span>
                                <div class="flex items-center gap-0.5 ml-4 overflow-x-auto no-scrollbar py-1">
                                    ${ballHtml}
                                </div>
                            </div>
                            <div class="flex items-center gap-1.5 shrink-0 px-1">
                                <div class="flex items-center gap-1">
                                    <span class="text-[10px] text-slate-400 font-bold lowercase">min</span>
                                    <input type="number" value="${f.min}" 
                                        onchange="FilterDashboard.updateTailDigitFilter('${def.id}', ${i}, 'min', this.value)"
                                        class="w-9 h-7 text-center text-[10px] font-black text-slate-700 bg-white border border-slate-200 rounded focus:ring-1 focus:ring-indigo-500 p-0">
                                </div>
                                <span class="text-slate-300 font-bold text-[10px]">∼</span>
                                <div class="flex items-center gap-1">
                                    <span class="text-[10px] text-slate-400 font-bold lowercase">max</span>
                                    <input type="number" value="${f.max}" 
                                        onchange="FilterDashboard.updateTailDigitFilter('${def.id}', ${i}, 'max', this.value)"
                                        class="w-9 h-7 text-center text-[10px] font-black text-slate-700 bg-white border border-slate-200 rounded focus:ring-1 focus:ring-indigo-500 p-0">
                                </div>
                            </div>
                        </div>
                    </div>`;
            }
            html += '</div>';
        } else if (key === 'consecutive_count') {
            const selectedCounts = vals.selectedCounts || [];
            const runFilters = vals.runFilters || { run3: false, run4: false, run5: false, run6: false };

            let btns = '';
            for (let i = 0; i <= 5; i++) {
                const isActive = selectedCounts.includes(i);
                const bg = isActive ? 'bg-indigo-600 text-white border-indigo-600' : 'bg-white text-slate-400 border-slate-200 hover:bg-slate-50';
                btns += `<button onclick="FilterDashboard.toggleDiscreteValue('${def.id}', 'selectedCounts', ${i})" class="flex-1 py-1.5 text-center rounded-lg border text-[10px] font-black transition-colors ${bg}">${i}</button>`;
            }

            html += `
                <div class="flex gap-1 mb-4">${btns}</div>
                <div class="flex flex-wrap items-center gap-10">
                    <label class="flex items-center gap-1.5 cursor-pointer hover:bg-slate-50 p-1 rounded transition-colors">
                        <input type="checkbox" ${runFilters.run3 ? 'checked' : ''} 
                            onchange="FilterDashboard.toggleRunFilter('${def.id}', 'run3', this.checked)"
                            class="w-3.5 h-3.5 text-indigo-600 rounded border-gray-300 focus:ring-0">
                        <span class="text-[11px] font-bold text-slate-600">2연번(3수)</span>
                    </label>
                    <label class="flex items-center gap-1.5 cursor-pointer hover:bg-slate-50 p-1 rounded transition-colors">
                        <input type="checkbox" ${runFilters.run4 ? 'checked' : ''} 
                            onchange="FilterDashboard.toggleRunFilter('${def.id}', 'run4', this.checked)"
                            class="w-3.5 h-3.5 text-indigo-600 rounded border-gray-300 focus:ring-0">
                        <span class="text-[11px] font-bold text-slate-600">3연번(4수)</span>
                    </label>
                    <label class="flex items-center gap-1.5 cursor-pointer hover:bg-slate-50 p-1 rounded transition-colors">
                        <input type="checkbox" ${runFilters.run5 ? 'checked' : ''} 
                            onchange="FilterDashboard.toggleRunFilter('${def.id}', 'run5', this.checked)"
                            class="w-3.5 h-3.5 text-indigo-600 rounded border-gray-300 focus:ring-0">
                        <span class="text-[11px] font-bold text-slate-600">4연번(5수)</span>
                    </label>
                    <label class="flex items-center gap-1.5 cursor-pointer hover:bg-slate-50 p-1 rounded transition-colors">
                        <input type="checkbox" ${runFilters.run6 ? 'checked' : ''} 
                            onchange="FilterDashboard.toggleRunFilter('${def.id}', 'run6', this.checked)"
                            class="w-3.5 h-3.5 text-indigo-600 rounded border-gray-300 focus:ring-0">
                        <span class="text-[11px] font-bold text-slate-600">5연번(6수)</span>
                    </label>
                </div>`;
        } else {
            const activeArrName = vals.activeCounts ? 'activeCounts' : (vals.selectedCounts ? 'selectedCounts' : 'selectedValues');
            const activeArr = vals[activeArrName] || [];
            const maxBtn = (key === 'twin_number_patterns') ? 4 : 6;

            let systemExcluded = [];

            if (key === 'prime_number_patterns' && vals.recent10FilterActive && this.state.allDraws.length >= 10) {
                const restoredAuto = vals.restoredAutoPrimes || [];
                const primeSet = new Set(this.state.staticTargets.prime_number_patterns);
                const counts = this.state.allDraws.slice(0, 10).map(d => {
                    return d.numbers.filter(n => primeSet.has(n)).length;
                });
                systemExcluded = [...new Set(counts)].filter(c => !restoredAuto.includes(c)).sort((a, b) => a - b);
            }

            if (key === 'composite_count' && vals.recent10FilterActive && this.state.allDraws.length >= 10) {
                const restoredAuto = vals.restoredAutoComposites || [];
                const compositeSet = new Set(this.state.staticTargets.composite_count);
                const counts = this.state.allDraws.slice(0, 10).map(d => {
                    return (d.numbers || []).filter(n => compositeSet.has(n)).length;
                });
                systemExcluded = [...new Set(counts)].filter(c => !restoredAuto.includes(c)).sort((a, b) => a - b);
            }

            let btns = '';
            for (let i = 0; i <= maxBtn; i++) {
                const isActive = activeArr.includes(i);
                const bg = isActive ? 'bg-indigo-600 text-white border-indigo-600' : 'bg-white text-slate-400 border-slate-200 hover:bg-slate-50';
                btns += `<button onclick="FilterDashboard.toggleDiscreteValue('${def.id}', '${activeArrName}', ${i})" class="flex-1 py-2 text-center rounded-lg border text-xs font-black transition-colors ${bg}">${i}</button>`;
            }
            html += `
                <div class="text-xs font-bold text-slate-500 mb-2 mt-1">포함될 당첨번호 개수 설정</div>
                <div class="flex gap-1.5">${btns}</div>`;

            if (systemExcluded.length > 0) {
                const labelSub = key === 'prime_number_patterns' ? '소수' : '합성수';
                html += `<div class="mt-4 pt-3 border-t border-slate-100 italic text-[10px] text-slate-400 font-bold mb-1">최근 10회차 자동 제외 ${labelSub} 개수:</div>`;
                html += `<div class="flex flex-wrap gap-1.5">`;
                html += systemExcluded.map(c => `
                        <button onclick="FilterDashboard.restoreAutoExcludedSum('${def.id}', ${c})"
                            class="inline-flex items-center gap-1 px-2.5 py-1 bg-indigo-600 text-white rounded-full text-[10px] font-black shadow-md hover:bg-indigo-700 transition-colors"
                            title="클릭 시 자동 제외 취소">
                            ${c}개 <span style="font-size:11px;">✕</span>
                        </button>
                    `).join('');
                html += `</div>`;
            }
        }
        return html;
    },

    renderBasket() {
        if (!document.getElementById('topFixedBalls')) return;
        document.getElementById('topFixedBalls').innerHTML = this.renderBalls(this.state.basket.fixed) || '<span class="text-xs text-gray-400">없음</span>';
        document.getElementById('topExcludeBalls').innerHTML = this.renderBalls(this.state.basket.excluded, this.state.basket.excluded) || '<span class="text-xs text-gray-400">없음</span>';
    },

    renderFoundationFilters() {
        const container = document.getElementById('foundationFilterGrid');
        if (!container) return;
        let html = '';
        let activeCount = 0;

        const targetKeys = ['total_sum', 'last_digit_sum', 'tail_digit_patterns', 'ac_value', 'odd_even_pattern', 'high_low_pattern', 'prime_number_patterns', 'composite_count', 'square_number_patterns', 'triangular_number_patterns', 'twin_number_patterns', 'neighbor_number_patterns', 'carryover_count', 'consecutive_count', 'multiple_3_count', 'number_range_patterns', 'magic_square_pattern', 'lotto_paper_pattern', 'hot_cold_5', 'hot_cold_10', 'hot_cold_15', 'hot_cold_20', 'missing_period', 'missing_custom_filter'];
        const orderedFilters = targetKeys.map(key => this.state.foundationFilters.find(def => def.filter_key === key)).filter(Boolean);

        orderedFilters.forEach(def => {
            const userSet = this.state.userSettings[def.id] || { enabled: false, settings: {} };
            if (userSet.enabled) activeCount++;

            const isCarryover = def.filter_key === 'carryover_count';
            let displayName = def.filter_name.replace(' 패턴', '').replace('패턴', '').replace(' 개수', '').replace('개수', '').replace('(전체)', '').replace('(당번)', '').trim();
            if (def.filter_key === 'odd_even_pattern') displayName = '홀짝';
            if (def.filter_key === 'tail_digit_patterns') displayName = '끝수';
            if (def.filter_key === 'multiple_3_count') displayName = '배수';
            if (def.filter_key === 'high_low_pattern') displayName = '저고';
            if (def.filter_key === 'prime_number_patterns') displayName = '소수';
            if (def.filter_key === 'composite_count') displayName = '합성수';
            if (def.filter_key === 'twin_number_patterns') displayName = '동형수';
            if (def.filter_key === 'square_number_patterns') displayName = '제곱수';
            if (def.filter_key === 'triangular_number_patterns') displayName = '삼각수';
            if (def.filter_key === 'magic_square_pattern') displayName = '9궁';
            if (def.filter_key === 'lotto_paper_pattern') displayName = '로또용지';
            if (def.filter_key === 'hot_cold_5') displayName = '핫/콜드 5회';
            if (def.filter_key === 'hot_cold_10') displayName = '핫/콜드 10회';
            if (def.filter_key === 'hot_cold_15') displayName = '핫/콜드 15회';
            if (def.filter_key === 'hot_cold_20') displayName = '핫/콜드 20회';
            if (def.filter_key === 'missing_period') displayName = '미출현 그룹';
            if (def.filter_key === 'missing_custom_filter') displayName = '미출현 커스텀';

            const themeClass = isCarryover ? 'border-blue-500 ring-blue-100 shadow-md ring-1' : 'border-indigo-500 shadow-md ring-1 ring-indigo-100';
            const titleColor = isCarryover ? 'text-blue-700' : 'text-indigo-700';
            const toggleColor = isCarryover ? 'peer-checked:bg-blue-600' : 'peer-checked:bg-indigo-600';
            const editIconColor = isCarryover ? 'group-hover:text-blue-500' : 'group-hover:text-indigo-500';

            html += `
            <div id="filter-${def.filter_key}" class="bg-white rounded-2xl border ${userSet.enabled ? themeClass : 'border-slate-200 opacity-70'} p-6 transition-all relative w-full">
                <div class="flex items-center justify-between mb-2">
                    <a href="${this.getFilterLink(def.filter_key)}" class="group flex items-center gap-1.5 cursor-pointer">
                        <h3 class="text-lg font-black ${userSet.enabled ? titleColor : 'text-slate-800'} group-hover:underline decoration-indigo-400 underline-offset-4">${displayName}</h3>
                        <span class="material-symbols-outlined text-[16px] text-slate-400 ${editIconColor}">edit_square</span>
                    </a>
                    <div class="flex items-center gap-2">
                        <button onclick="FilterDashboard.loadDataFromDB().then(()=>FilterDashboard.renderUI())" 
                            title="데이터 수동 동기화"
                            class="p-1 text-slate-300 hover:text-indigo-500 transition-colors">
                            <span class="material-symbols-outlined text-[18px]">sync</span>
                        </button>
                        <label class="relative inline-flex items-center cursor-pointer">
                            <input type="checkbox" class="sr-only peer" ${userSet.enabled ? 'checked' : ''} onchange="FilterDashboard.toggleSetting('${def.id}', this.checked)">
                            <div class="w-10 h-5 bg-slate-200 rounded-full peer peer-checked:after:translate-x-full after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border after:rounded-full after:h-4 after:w-4 transition-all ${toggleColor}"></div>
                        </label>
                    </div>
                </div>
                ${this.buildFilterControl(def, userSet)}
            </div>`;
        });
        container.innerHTML = html;
        document.getElementById('foundationActiveCount').textContent = `${activeCount}개 적용중`;
    },

    // 🔥 핵심 변경점: 회귀 분석 렌더링 (입력창 추가 및 텍스트 수정)
    renderRegressionFilters() {
        const container = document.getElementById('regressionFilterGrid');
        if (!container) return;
        let html = '';
        let activeCount = 0;

        for (let i = 2; i <= 200; i++) {
            const masterOn = this.state.regressionEnabled !== false;
            const rData = this.state.regressionSettings[i] || { enabled: false, min: 0, max: 2 };
            const isActuallyEnabled = masterOn && rData.enabled;
            if (isActuallyEnabled) activeCount++;

            const targetNums = this.state.allDraws[i - 1] ? this.state.allDraws[i - 1].numbers : [];

            html += `
            <div class="px-6 py-4 grid grid-cols-1 md:grid-cols-3 items-center gap-4 hover:bg-slate-50 border-b border-slate-100 ${isActuallyEnabled ? 'bg-emerald-50/30' : 'opacity-60 grayscale'}">
                <div class="flex items-center gap-6 justify-start">
                    <label class="relative inline-flex items-center cursor-pointer scale-110">
                        <input type="checkbox" class="sr-only peer" ${isActuallyEnabled ? 'checked' : ''} onchange="FilterDashboard.toggleRegression(${i})">
                        <div class="w-10 h-5 bg-slate-200 rounded-full peer peer-checked:after:translate-x-full after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 transition-all peer-checked:bg-emerald-500"></div>
                    </label>
                    <a href="regression.html?step=${i}" class="text-sm font-black text-slate-800 whitespace-nowrap hover:text-emerald-600">${i}회귀</a>
                </div>
                <!-- 번호 중앙 정렬 처리 -->
                <div class="flex items-center justify-center gap-1">
                    ${this.renderBalls(targetNums)}
                </div>
                <div class="flex items-center justify-end">
                    <div class="flex items-center gap-2 bg-white border border-slate-200 rounded-xl px-3 py-1.5 shadow-sm focus-within:ring-2 focus-within:ring-emerald-500">
                        <input type="number" value="${rData.min}" 
                            onchange="FilterDashboard.updateRegressionRange(${i}, 'min', this.value)"
                            class="w-12 text-center font-black text-emerald-600 bg-transparent border-none p-0 focus:ring-0 text-base">
                        <span class="text-slate-300 font-bold">~</span>
                        <input type="number" value="${rData.max}" 
                            onchange="FilterDashboard.updateRegressionRange(${i}, 'max', this.value)"
                            class="w-12 text-center font-black text-emerald-600 bg-transparent border-none p-0 focus:ring-0 text-base">
                    </div>
                </div>
            </div>`;
        }
        container.innerHTML = html;
        document.getElementById('regressionActiveCount').textContent = `${activeCount}개 적용중`;
    },

    renderCustomFilters() {
        const container = document.getElementById('customFilterGrid');
        if (!container) return;
        let html = '';
        let activeCount = 0;

        this.state.customFilters.forEach(custom => {
            let config = typeof custom.filter_config === 'string' ? JSON.parse(custom.filter_config) : (custom.filter_config || {});
            let targetNums = this.calculateCustomTargets(custom);
            if (config.enabled) activeCount++;

            let targetHtml = targetNums.length > 0
                ? `<div class="mb-2 flex justify-between items-center"><span class="text-xs font-bold text-slate-500">대상번호</span><span class="text-[11px] font-black text-pink-600">${targetNums.length}개</span></div><div class="flex flex-wrap gap-1">${this.renderBalls(targetNums)}</div>`
                : `<div class="text-[11px] font-bold text-slate-400 flex items-center justify-center py-2 bg-slate-100 rounded">타겟 생성 중/없음</div>`;

            html += `
            <div id="filter-card-${custom.id}" class="bg-white rounded-2xl border ${config.enabled ? 'border-pink-500 shadow-md ring-1 ring-pink-100' : 'border-slate-200 opacity-70'} p-5 transition-all">
                <div class="flex items-center justify-between mb-3">
                    <div class="flex items-center gap-2">
                        <span class="px-2 py-0.5 rounded text-[10px] font-black bg-slate-100 text-slate-500 uppercase">${custom.type}</span>
                        <a href="custom_analysis.html?id=${custom.id}" class="text-base font-black text-slate-800 truncate w-48">${custom.title}</a>
                    </div>
                    <label class="relative inline-flex items-center cursor-pointer">
                        <input type="checkbox" class="sr-only peer" ${config.enabled ? 'checked' : ''} onchange="FilterDashboard.toggleCustom('${custom.id}', this.checked)">
                        <div class="w-10 h-5 bg-slate-200 rounded-full peer peer-checked:after:translate-x-full after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 transition-all peer-checked:bg-pink-600"></div>
                    </label>
                </div>
                <div class="p-3 bg-slate-50 border border-slate-100 rounded-xl mb-3">${targetHtml}</div>
                <div class="flex items-center gap-3">
                    <div class="flex-1 bg-white border border-slate-200 rounded-lg flex items-center px-3 py-2 shadow-sm">
                        <span class="text-xs font-black text-slate-400 uppercase w-8">Min</span>
                        <input type="number" value="${config.min || 0}" class="w-full text-right font-black text-slate-700 bg-transparent border-none p-0 focus:ring-0">
                    </div>
                    <span class="text-slate-300 font-bold">~</span>
                    <div class="flex-1 bg-white border border-slate-200 rounded-lg flex items-center px-3 py-2 shadow-sm">
                        <span class="text-xs font-black text-slate-400 uppercase w-8">Max</span>
                        <input type="number" value="${config.max || 6}" class="w-full text-right font-black text-slate-700 bg-transparent border-none p-0 focus:ring-0">
                    </div>
                </div>
            </div>`;
        });
        container.innerHTML = html;
        if (document.getElementById('customActiveCount')) document.getElementById('customActiveCount').textContent = `${activeCount}개 적용중`;
    },

    async toggleSetting(id, isEnabled) {
        if (this.state.userSettings[id]) {
            this.state.userSettings[id].enabled = isEnabled;
            if (window.filterService?.initialized) {
                const def = this.state.foundationFilters.find(d => d.id === id);
                if (def) await window.filterService.saveSetting(def.filter_key, this.state.userSettings[id].settings, isEnabled);
            }
        }
        this.renderFoundationFilters();
        this.updateNeonCounter();
    },

    async updateFilterValue(id, type, value) {
        if (this.state.userSettings[id]) {
            const val = parseInt(value);
            if (isNaN(val)) return;
            this.state.userSettings[id].settings[type] = val;

            if (this._saveTimer) clearTimeout(this._saveTimer);
            this._saveTimer = setTimeout(async () => {
                if (window.filterService?.initialized) {
                    const def = this.state.foundationFilters.find(d => d.id === id);
                    if (def) await window.filterService.saveSetting(def.filter_key, this.state.userSettings[id].settings, this.state.userSettings[id].enabled);
                }
                this.updateNeonCounter();
            }, 500);
        }
    },

    async toggleDiscreteValue(id, arrayName, value) {
        if (this.state.userSettings[id]) {
            let arr = this.state.userSettings[id].settings[arrayName] || [];
            if (arr.includes(value)) {
                arr = arr.filter(v => v !== value);
            } else {
                arr.push(value);
                arr.sort((a, b) => a - b);
            }
            this.state.userSettings[id].settings[arrayName] = arr;

            if (window.filterService?.initialized) {
                const def = this.state.foundationFilters.find(d => d.id === id);
                if (def) await window.filterService.saveSetting(def.filter_key, this.state.userSettings[id].settings, this.state.userSettings[id].enabled);
            }
            this.renderFoundationFilters();
            this.updateNeonCounter();
        }
    },

    async toggleRunFilter(id, runKey, isChecked) {
        if (this.state.userSettings[id]) {
            if (!this.state.userSettings[id].settings.runFilters) {
                this.state.userSettings[id].settings.runFilters = { run3: false, run4: false, run5: false, run6: false };
            }
            this.state.userSettings[id].settings.runFilters[runKey] = isChecked;

            if (window.filterService?.initialized) {
                const def = this.state.foundationFilters.find(d => d.id === id);
                if (def) await window.filterService.saveSetting(def.filter_key, this.state.userSettings[id].settings, this.state.userSettings[id].enabled);
            }
            this.renderFoundationFilters();
            this.updateNeonCounter();
        }
    },

    async updateNumberRangeFilter(id, typeName, boundType, value) {
        const userSet = this.state.userSettings[id];
        if (!userSet) return;
        if (!userSet.settings.ranges) userSet.settings.ranges = {};
        if (!userSet.settings.ranges[typeName]) userSet.settings.ranges[typeName] = { min: (typeName === 'entropy' ? '0.00' : 0), max: (typeName === 'entropy' ? '3.00' : 6) };

        if (typeName === 'entropy') {
            userSet.settings.ranges[typeName][boundType] = parseFloat(value).toFixed(2);
        } else {
            userSet.settings.ranges[typeName][boundType] = parseInt(value);
        }

        userSet.settings.recent10FilterActive = false;

        const def = this.state.foundationFilters.find(f => f.id === id);
        if (def && window.filterService?.initialized) {
            await window.filterService.saveSetting(def.filter_key, userSet.settings, userSet.enabled);
        }
        this.renderFoundationFilters();
        this.updateNeonCounter();
    },

    async updateMultipleFilter(id, typeName, boundType, value) {
        const userSet = this.state.userSettings[id];
        if (!userSet) return;
        if (!userSet.settings.filters) userSet.settings.filters = {};
        if (!userSet.settings.filters[typeName]) userSet.settings.filters[typeName] = { min: 0, max: 6 };

        userSet.settings.filters[typeName][boundType] = parseInt(value);
        userSet.settings.recent10FilterActive = false;

        const def = this.state.foundationFilters.find(f => f.id === id);
        if (def && window.filterService?.initialized) {
            await window.filterService.saveSetting(def.filter_key, userSet.settings, userSet.enabled);
        }
        this.renderFoundationFilters();
        this.updateNeonCounter();
    },

    async updateMagicSquareFilter(id, typeName, boundType, value) {
        const userSet = this.state.userSettings[id];
        if (!userSet) return;
        if (!userSet.settings.filters) userSet.settings.filters = {};
        if (!userSet.settings.filters[typeName]) userSet.settings.filters[typeName] = { min: 0, max: 5 };

        userSet.settings.filters[typeName][boundType] = parseInt(value);
        userSet.settings.targetRound = this.state.allDraws && this.state.allDraws.length > 0 ? this.state.allDraws[0].round : null;

        const def = this.state.foundationFilters.find(f => f.id === id);
        if (def && window.filterService?.initialized) {
            await window.filterService.saveSetting(def.filter_key, userSet.settings, userSet.enabled);
        }
        this.renderFoundationFilters();
        this.updateNeonCounter();
    },

    async updateLottoPaperFilter(id, typeName, boundType, value) {
        const userSet = this.state.userSettings[id];
        if (!userSet) return;
        if (!userSet.settings.groups) userSet.settings.groups = {};
        if (!userSet.settings.groups[typeName]) userSet.settings.groups[typeName] = { min: 0, max: 6 };

        userSet.settings.groups[typeName][boundType] = parseInt(value);
        userSet.settings.targetRound = this.state.allDraws && this.state.allDraws.length > 0 ? this.state.allDraws[0].round : null;

        const def = this.state.foundationFilters.find(f => f.id === id);
        if (def && window.filterService?.initialized) {
            await window.filterService.saveSetting(def.filter_key, userSet.settings, userSet.enabled);
        }
        this.renderFoundationFilters();
        this.updateNeonCounter();
    },

    async updateTailDigitFilter(id, digit, type, value) {
        const userSet = this.state.userSettings[id];
        if (!userSet) return;
        if (!userSet.settings.filters) userSet.settings.filters = {};
        if (!userSet.settings.filters[digit]) userSet.settings.filters[digit] = { min: 0, max: 6 };

        userSet.settings.filters[digit][type] = parseInt(value);
        userSet.settings.recent10FilterActive = false;

        // ✅ localStorage 즉시 백업 (DB 저장 실패/지연 시에도 새로고침 후 복구)
        try {
            localStorage.setItem('tail_digit_patterns', JSON.stringify(userSet.settings));
        } catch (e) { }

        const def = this.state.foundationFilters.find(f => f.id === id);
        if (def && window.filterService?.initialized) {
            await window.filterService.saveSetting(def.filter_key, userSet.settings, userSet.enabled);
        }
        this.renderFoundationFilters();
        this.updateNeonCounter();
    },

    async updateHotColdFilter(id, field, index, value) {
        const userSet = this.state.userSettings[id];
        if (!userSet) return;

        // \ubc30\uc5f4 \ud3ec\ub9f7 \uc5c5\ub370\uc774\ud2b8 (\ub300\uc2dc\ubcf4\ub4dc \uc800\uc7a5\ud615)\n        if (!userSet.settings[field]) userSet.settings[field] = [0, 6];
        userSet.settings[field][index] = parseInt(value);

        // periodFilter flat \ud3ec\ub9f7\ub3c4 \ud568\uaed8 \uc800\uc7a5 (hot_cold.html \ud638\ud658\uc131)\n        const hr = userSet.settings.hotRange  || [0, 6];
        const wr = userSet.settings.warmRange || [0, 6];
        const cr = userSet.settings.coldRange || [0, 6];
        userSet.settings.periodFilter = {
            hotMin: hr[0], hotMax: hr[1],
            neutralMin: wr[0], neutralMax: wr[1],
            coldMin: cr[0], coldMax: cr[1]
        };

        const def = this.state.foundationFilters.find(f => f.id === id);
        if (def && window.filterService?.initialized) {
            await window.filterService.saveSetting(def.filter_key, userSet.settings, userSet.enabled);
        }
        this.renderFoundationFilters();
        this.updateNeonCounter();
    },


    async toggleRecent10TailDigits(id) {
        const userSet = this.state.userSettings[id];
        if (!userSet) return;

        const isActivating = !userSet.settings.recent10FilterActive;
        userSet.settings.recent10FilterActive = isActivating;

        if (isActivating && this.state.allDraws && this.state.allDraws.length >= 10) {
            const recent10 = this.state.allDraws.slice(0, 10);
            const counts = Array.from({ length: 10 }, () => []);
            recent10.forEach(draw => {
                const digitCounts = new Array(10).fill(0);
                (draw.numbers || []).forEach(n => digitCounts[n % 10]++);
                for (let i = 0; i < 10; i++) counts[i].push(digitCounts[i]);
            });

            if (!userSet.settings.filters) userSet.settings.filters = {};
            for (let i = 0; i < 10; i++) {
                userSet.settings.filters[i] = {
                    min: Math.min(...counts[i]),
                    max: Math.max(...counts[i])
                };
            }
        } else if (!isActivating) {
            if (userSet.settings.filters) {
                for (let i = 0; i < 10; i++) {
                    userSet.settings.filters[i] = { min: 0, max: 6 };
                }
            }
        }

        const def = this.state.foundationFilters.find(f => f.id === id);
        if (def && window.filterService?.initialized) {
            await window.filterService.saveSetting(def.filter_key, userSet.settings, userSet.enabled);
        }
        this.renderFoundationFilters();
        this.updateNeonCounter();
    },

    async updateMissingPeriodFilter(id, rangeKey, value) {
        const userSet = this.state.userSettings[id];
        if (!userSet) return;
        if (!userSet.settings.ranges) userSet.settings.ranges = {};
        userSet.settings.ranges[rangeKey] = parseInt(value);

        const def = this.state.foundationFilters.find(f => f.id === id);
        if (def && window.filterService?.initialized) {
            await window.filterService.saveSetting(def.filter_key, userSet.settings, userSet.enabled);
        }
        this.renderFoundationFilters();
        this.updateNeonCounter();
    },

    // 🔥 DB 키값 수정됨 ('regression_patterns')
    async toggleRegression(step) {
        if (!this.state.regressionSettings[step]) this.state.regressionSettings[step] = { enabled: false, min: 0, max: 2 };
        const current = this.state.regressionSettings[step].enabled;
        this.state.regressionSettings[step].enabled = !current;
        this.state.regressionEnabled = true;

        if (window.filterService?.initialized) {
            await window.filterService.saveSetting('regression_analysis', this.state.regressionSettings, true);
        }
        this.renderRegressionFilters();
        this.updateNeonCounter();
    },

    // 🔥 추가: 회귀분석 Min/Max 입력 시 즉시 DB 저장
    async updateRegressionRange(step, type, value) {
        if (!this.state.regressionSettings[step]) this.state.regressionSettings[step] = { enabled: false, min: 0, max: 2 };
        this.state.regressionSettings[step][type] = parseInt(value);

        if (this._regSaveTimer) clearTimeout(this._regSaveTimer);
        this._regSaveTimer = setTimeout(async () => {
            if (window.filterService?.initialized) {
                // 회귀분석 덩어리 전체를 저장
                await window.filterService.saveSetting('regression_analysis', this.state.regressionSettings, this.state.regressionEnabled !== false);
            }
            this.updateNeonCounter();
        }, 500);
    },

    async toggleCustom(id, isEnabled) {
        const custom = this.state.customFilters.find(c => c.id === id);
        if (custom) {
            let conf = typeof custom.filter_config === 'string' ? JSON.parse(custom.filter_config) : custom.filter_config;
            conf.enabled = isEnabled;
            custom.filter_config = conf;
            if (window.supabaseClient) {
                await window.supabaseClient.from('ai_custom_analyses').update({ filter_config: conf, updated_at: new Date().toISOString() }).eq('id', id);
            }
            this.renderCustomFilters();
            this.updateNeonCounter();
        }
    },

    async bulkToggleRegression(isOn) {
        this.state.regressionEnabled = isOn;
        for (let i = 2; i <= 200; i++) {
            if (!this.state.regressionSettings[i]) this.state.regressionSettings[i] = { enabled: isOn, min: 0, max: 2 };
            else this.state.regressionSettings[i].enabled = isOn;
        }
        if (window.filterService?.initialized) {
            await window.filterService.saveSetting('regression_analysis', this.state.regressionSettings, isOn);
        }
        this.renderRegressionFilters();
        this.updateNeonCounter();
    },

    async removeExcludedSum(id, sumValue) {
        if (!this.state.userSettings[id]) return;
        const record = this.state.userSettings[id];
        const def = this.state.foundationFilters.find(d => d.id === id);
        const key = def ? def.filter_key : null;

        let targetArray = null;
        let arrayName = null;

        if (key === 'ac_value') {
            arrayName = 'excludedAcValues';
            targetArray = record.settings.excludedAcValues;
        } else if (key === 'odd_even_pattern') {
            arrayName = 'excludedOddEvens';
            targetArray = record.settings.excludedOddEvens;
        } else if (key === 'high_low_pattern') {
            arrayName = 'excludedHighLows';
            targetArray = record.settings.excludedHighLows;
        } else if (key === 'prime_number_patterns') {
            arrayName = 'restoredAutoPrimes'; // Discrete type usually uses restore logic
            targetArray = record.settings.restoredAutoPrimes;
        } else if (key === 'composite_count') {
            arrayName = 'restoredAutoComposites';
            targetArray = record.settings.restoredAutoComposites;
        } else {
            arrayName = 'excludedSums';
            targetArray = record.settings.excludedSums;
        }

        if (record.settings && targetArray && targetArray.includes(sumValue)) {
            record.settings[arrayName] = targetArray.filter(val => val !== sumValue);

            // selectedRatios 복원 (홀짝/저고 공통)
            if (key === 'odd_even_pattern' || key === 'high_low_pattern') {
                if (!record.settings.selectedRatios) record.settings.selectedRatios = [];
                if (!record.settings.selectedRatios.includes(sumValue)) {
                    record.settings.selectedRatios.push(sumValue);
                }
            }

            if (window.filterService?.initialized && key) {
                await window.filterService.saveSetting(key, record.settings, record.enabled);
                // localStorage 동기화
                const settingsWithEnabled = { ...record.settings, enabled: record.enabled };
                localStorage.setItem(key, JSON.stringify(settingsWithEnabled));
            }
            this.renderFoundationFilters();
            this.updateNeonCounter();
        }
    },

    // 자동 제외 복원 (X 클릭 → 해당 합계를 자동 제외에서 제거)
    async restoreAutoExcludedSum(id, sumValue) {
        if (!this.state.userSettings[id]) return;
        const record = this.state.userSettings[id];
        if (!record.settings) record.settings = {};

        const def = this.state.foundationFilters.find(d => d.id === id);
        const key = def ? def.filter_key : null;

        let arrayName = 'restoredAutoSums';
        if (key === 'ac_value') arrayName = 'restoredAutoAcValues';
        else if (key === 'odd_even_pattern') arrayName = 'restoredAutoOddEvens';
        else if (key === 'high_low_pattern') arrayName = 'restoredAutoHighLows';
        else if (key === 'prime_number_patterns') arrayName = 'restoredAutoPrimes';
        else if (key === 'composite_count') arrayName = 'restoredAutoComposites';
        if (!record.settings[arrayName]) record.settings[arrayName] = [];

        if (!record.settings[arrayName].includes(sumValue)) {
            record.settings[arrayName].push(sumValue);

            // selectedRatios 복원 (홀짝/저고 공통)
            if (key === 'odd_even_pattern' || key === 'high_low_pattern') {
                if (!record.settings.selectedRatios) record.settings.selectedRatios = [];
                if (!record.settings.selectedRatios.includes(sumValue)) {
                    record.settings.selectedRatios.push(sumValue);
                }
            }

            if (window.filterService?.initialized && key) {
                await window.filterService.saveSetting(key, record.settings, record.enabled);
                // localStorage 동기화
                const settingsWithEnabled = { ...record.settings, enabled: record.enabled };
                localStorage.setItem(key, JSON.stringify(settingsWithEnabled));
                localStorage.setItem(key + '_filter', JSON.stringify(settingsWithEnabled));
            }
            this.renderFoundationFilters();
            this.updateNeonCounter();
        }
    },

    updateNeonCounter() {
        try {
            // 1. 상태값 Null 방어
            const state = this.state || {};
            const basket = state.basket || { fixed: [], excluded: [] };
            const f = Array.isArray(basket.fixed) ? basket.fixed.length : 0;
            const e = Array.isArray(basket.excluded) ? basket.excluded.length : 0;

            let combos = 8145060;

            if (f > 6 || f + e > 45) {
                combos = 0;
            } else if (f > 0 || e > 0) {
                const nCr = (n, r) => {
                    if (r < 0 || r > n) return 0;
                    if (r === 0 || r === n) return 1;
                    if (r > n / 2) r = n - r;
                    let res = 1;
                    for (let i = 1; i <= r; i++) {
                        res = res * (n - i + 1) / i;
                    }
                    return res;
                };
                combos = nCr(45 - e - f, 6 - f);
            }

            // 2. 기초 분석 필터 
            let combinedProb = 1.0;
            const userSettings = state.userSettings || {};
            const foundationFilters = state.foundationFilters || [];

            Object.entries(userSettings).forEach(([id, s]) => {
                if (s && s.enabled) {
                    const def = foundationFilters.find(f => f.id === id);
                    const key = def ? def.filter_key : null;

                    if (key && window.FilterStatsData && typeof window.FilterStatsData.calculateProbability === 'function') {
                        let prob = window.FilterStatsData.calculateProbability(key, s.settings || s);
                        if (prob <= 0) prob = 0.0001;
                        combinedProb *= prob;
                    } else {
                        combinedProb *= 0.95;
                    }
                }
            });

            combos *= combinedProb;

            // 3. 회귀 필터
            const regSettings = state.regressionSettings || {};
            let regActive = Object.values(regSettings).filter(s => s && s.enabled).length;
            if (regActive > 0) {
                const regProb = Math.max(0.15, Math.pow(0.99, regActive));
                combos *= regProb;
            }

            // 4. 커스텀 필터 (JSON 파싱 에러 완벽 차단)
            const customFilters = state.customFilters || [];
            let customActive = customFilters.filter(c => {
                if (!c || !c.filter_config) return false;
                try {
                    // 빈 문자열이거나 유효하지 않은 JSON일 때의 크래시 방지
                    let conf = typeof c.filter_config === 'string'
                        ? JSON.parse(c.filter_config || "{}")
                        : c.filter_config;
                    return conf.enabled === true;
                } catch (e) {
                    return false;
                }
            }).length;

            if (customActive > 0) {
                combos *= Math.pow(0.95, customActive);
            }

            const target = Math.max(0, Math.floor(combos));

            // 5. 네온 카운터 애니메이션
            const obj = document.getElementById('neonCounter');
            if (!obj) return;

            const startVal = state.currentCombos || 8145060;
            if (startVal === target) {
                obj.innerHTML = target.toLocaleString();
                return;
            }

            let startTimestamp = null;
            const step = (timestamp) => {
                if (!startTimestamp) startTimestamp = timestamp;
                const progress = Math.min((timestamp - startTimestamp) / 500, 1);

                const easeOut = progress * (2 - progress);
                const currentVal = Math.floor(startVal + (target - startVal) * easeOut);

                obj.innerHTML = currentVal.toLocaleString();

                if (progress < 1) {
                    window.requestAnimationFrame(step);
                } else {
                    obj.innerHTML = target.toLocaleString();
                    state.currentCombos = target;
                }
            };
            window.requestAnimationFrame(step);

        } catch (error) {
            console.error("🚨 [Counter Error] 카운팅 로직 중 치명적 에러 발생:", error);
        }
    }
};
