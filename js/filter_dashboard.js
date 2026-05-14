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
        manualFilters: [],
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

    _dashSelfSaving: false, // 자체 저장 StorageEvent 루프 방지

    async init() {
        console.log("🚀 Real Filter Dashboard Booting...");
        await this.loadDataFromDB();
        this.renderUI();
        // [Phase 4.4] AI 범위 캐시 비동기 로드 (렌더링 차단하지 않음)
        this.loadAIRangesCache();

        // [수정] 실시간 동기화: 다른 탭에서 필터 변경 시 즉시 반영
        window.addEventListener('storage', (e) => {
            if (!e.key) return;
            // [Fix] 대시보드 자체 저장으로 발생한 StorageEvent 무시 (re-render → 입력 포커스 유실 방지)
            if (this._dashSelfSaving) return;

            const watchedKeys = new Set([
                'total_sum', 'tail_sum', 'ac_value', 'odd_even_pattern', 'high_low_pattern',
                'prime_number_patterns', 'composite_count', 'square_number_patterns',
                'triangular_number_patterns', 'twin_number_patterns', 'neighbor_number_patterns',
                'carryover_count', 'consecutive_count', 'multiple_3_count',
                'multiple_4_count', 'multiple_5_count',
                'multiple_7_count', 'multiple_8_count', 'no_multiple_count',
                'number_range_patterns',
                'magic_square_pattern', 'lotto_paper_pattern', 'hot_cold_5', 'hot_cold_10',
                'hot_cold_15', 'hot_cold_20', 'missing_period', 'missing_custom_filter',
                'regression_analysis', 'lotto_basket', 'tail_digit_patterns',
                'combination_filter', 'combination_settings'
            ]);

            const isCustomFilter = e.key.startsWith('custom_filter_');
            const isAnalysisRefresh = e.key === 'custom_analysis_refresh';
            // [수정] layout.js 저장 키와 동기화: lnbOrder_custom_<userId> 또는 lnbOrder_custom_guest
            const isLnbOrderChange = e.key === 'lnbOrder_custom' || e.key.startsWith('lnbOrder_custom_');
            const isEndDigitFilter = /^end_digit_\d_count$/.test(e.key);

            const isWatched = watchedKeys.has(e.key) || e.key.endsWith('_filter') || isCustomFilter || isAnalysisRefresh || isLnbOrderChange || isEndDigitFilter;
            if (!isWatched) return;

            // [Phase 4] BroadcastChannel 중복 방지: 처리 시각 기록
            if (window._lottoBcHandled) window._lottoBcHandled.set(e.key, Date.now());

            console.log(`🔄 Storage Change Detected: ${e.key}. Refreshing Dashboard...`);

            if (isAnalysisRefresh) {
                this.loadDataFromDB().then(() => this.renderUI());
                return;
            }

            if (isLnbOrderChange) {
                // [수정] LNB 순서 변경 시: 정렬 → render → 카운트 재계산 (인디펜던트 카운트 + Combination Worker)
                this._reorderCustomFiltersByLnb();
                this.renderCustomFilters();
                this.updateNeonCounter();
                if (window.applyIndepCountBadges) window.applyIndepCountBadges();
                return;
            }

            if (isCustomFilter && e.newValue) {
                try {
                    const customId = e.key.replace('custom_filter_', '');
                    const newData = JSON.parse(e.newValue);
                    const custom = this.state.customFilters.find(c => c.id === customId);
                    if (custom) {
                        // Utils.saveFilter가 envelope {settings, enabled, _ts} 구조로 저장하므로 settings 추출
                        const fc = newData.settings !== undefined ? newData.settings : newData;
                        if (fc && typeof fc === 'object') {
                            // [Fix] envelope.enabled를 fc에 병합 → conf.enabled가 undefined인 경우에도 enabled 상태 보존
                            // (DB에 enabled 필드 없이 저장된 구 버전 filter_config 방어)
                            if (newData.settings !== undefined && newData.enabled !== undefined) {
                                fc.enabled = newData.enabled;
                            }
                            custom.filter_config = fc;
                        }
                        this.renderCustomFilters();
                        this.updateNeonCounter();
                        return;
                    }
                } catch (err) { }
            }

            if ((e.key === 'regression_analysis' || e.key === 'regression_patterns' || e.key === 'lotto_period_filters') && e.newValue) {
                try {
                    const newData = JSON.parse(e.newValue);
                    const msgRound = newData.targetRound || newData.target_round;
                    if (msgRound && msgRound !== this.state.targetRound) return;

                    this.state.regressionSettings = newData.settings || (newData.periodFilters ? newData.periodFilters : newData);
                    this.state.regressionEnabled = newData.enabled !== undefined ? newData.enabled : true;
                    this.renderUI();
                    return;
                } catch (err) { }
            }

            // [핵심] localStorage 변경값을 state에 즉시 병합 후 UI 갱신 (DB 레이스 컨디션 방지)
            if (e.newValue && e.key !== 'lotto_basket') {
                try {
                    const newData = JSON.parse(e.newValue);
                    // _filter 접미사 호환성 처리
                    const searchKey = e.key.endsWith('_filter') ? e.key.replace('_filter', '') : e.key;
                    const def = this.state.foundationFilters.find(d => d.filter_key === searchKey || d.filter_key === e.key);

                    if (def) {
                        // [수정] userSettings[def.id]가 없어도 즉시 생성 후 fast-sync
                        // (foundationFilters 로드됐으나 userSettings 미초기화 케이스 방어)
                        if (!this.state.userSettings[def.id]) {
                            try {
                                const defaultParsed = typeof def.default_settings === 'string'
                                    ? JSON.parse(def.default_settings || '{}')
                                    : (def.default_settings || {});
                                this.state.userSettings[def.id] = { enabled: false, settings: defaultParsed };
                            } catch (_) {
                                this.state.userSettings[def.id] = { enabled: false, settings: {} };
                            }
                        }
                        console.log(`💡 [Sync] Fast-syncing ${e.key} to dashboard state`);
                        if (newData.settings !== undefined) {
                            this.state.userSettings[def.id].settings = newData.settings;
                            this.state.userSettings[def.id].enabled = newData.enabled !== false;
                        } else {
                            const { enabled, _ts, ...settings } = newData;
                            if (enabled !== undefined) this.state.userSettings[def.id].enabled = enabled;
                            if (Object.keys(settings).length > 0) {
                                this.state.userSettings[def.id].settings = {
                                    ...this.state.userSettings[def.id].settings,
                                    ...settings
                                };
                            }
                        }
                        this.renderUI();
                        return; // 즉시 반영 성공 시 DB 재로드 스킵
                    }
                } catch (err) { }
            }

            // 폴백: DB에서 데이터 재로드 (디바운스 300ms - 멀티탭 동시 변경 레이스 컨디션 방지)
            if (this._storageReloadTimer) clearTimeout(this._storageReloadTimer);
            this._storageReloadTimer = setTimeout(() => {
                this.loadDataFromDB().then(() => this.renderUI());
            }, 300);
        });


        // [Phase 4] BroadcastChannel 초기화 - 크로스탭 필터 변경 수신
        // _lottoBcHandled: storage 이벤트와 BroadcastChannel 간 100ms 내 중복 처리 방지
        window._lottoBcHandled = new Map();
        if (typeof BroadcastChannel !== 'undefined') {
            try {
                window._lottoBc = new BroadcastChannel('lotto_filter_sync');
                window._lottoBc.onmessage = (e) => {
                    if (!e.data || e.data.type !== 'FILTER_CHANGED') return;
                    const { key, value } = e.data;
                    // storage 이벤트가 먼저 도착했으면 100ms 내 중복 무시
                    const lastHandled = window._lottoBcHandled.get(key) || 0;
                    if (Date.now() - lastHandled < 100) return;
                    window._lottoBcHandled.set(key, Date.now());
                    // storage 이벤트와 동일한 처리 로직 재사용 (dispatchEvent로 storage 핸들러 호출)
                    window.dispatchEvent(new StorageEvent('storage', {
                        key, newValue: value, storageArea: localStorage
                    }));
                };
                console.log('[FilterDashboard] BroadcastChannel 초기화 완료');
            } catch (_) { /* 미지원 환경 무시 */ }
        }

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

        // [동기화] regression.html에서 특정 step 링크로 진입 시 해당 행으로 스크롤
        const stepParam = params.get('step');
        if (stepParam && tab === 'regression') {
            setTimeout(() => {
                const stepEl = document.getElementById(`regression-row-${stepParam}`);
                if (stepEl) {
                    stepEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    stepEl.style.borderTop = '2px solid #22c55e';
                    stepEl.style.borderBottom = '2px solid #22c55e';
                    stepEl.style.borderLeft = '2px solid #22c55e';
                    stepEl.style.borderRight = '2px solid #22c55e';
                    stepEl.style.boxShadow = '0 0 12px rgba(34,197,94,0.35)';
                    setTimeout(() => {
                        stepEl.style.borderTop = '';
                        stepEl.style.borderBottom = '';
                        stepEl.style.borderLeft = '';
                        stepEl.style.borderRight = '';
                        stepEl.style.boxShadow = '';
                    }, 2000);
                }
            }, 800);
        }

        document.getElementById('btnRegAllOn')?.addEventListener('click', () => this.bulkToggleRegression(true));
        document.getElementById('btnRegAllOff')?.addEventListener('click', () => this.bulkToggleRegression(false));
        document.getElementById('btnRegBulkApply')?.addEventListener('click', () => this.bulkApplyRegressionRange());
    },

    // [추가] 필터 값 증감 도우미 함수 (Foundation 전용)
    changeFilterValue(defId, key, delta, min, max) {
        const input = document.getElementById(`input-${defId}-${key}`);
        if (!input) return;
        let val = parseInt(input.value) || 0;
        val += delta;
        if (val < min) val = min;
        if (val > max) val = max;
        input.value = val;

        // 논리적 오류 방지 (min > max 되지 않도록)
        const isMin = key === 'min';
        const otherId = isMin ? `input-${defId}-max` : `input-${defId}-min`;
        const otherEl = document.getElementById(otherId);
        if (otherEl) {
            let otherVal = parseInt(otherEl.value) || 0;
            if (isMin && val > otherVal) {
                otherEl.value = val;
                this.updateFilterValue(defId, 'max', val);
            } else if (!isMin && val < otherVal) {
                otherEl.value = val;
                this.updateFilterValue(defId, 'min', val);
            }
        }

        this.updateFilterValue(defId, key, val);
    },

    // [추가] 회귀분석 필터 값 증감 도우미 함수
    changeRegressionValue(idx, key, delta, min, max) {
        const input = document.getElementById(`reg-${idx}-${key}`);
        if (!input) return;
        let val = parseInt(input.value) || 0;
        val += delta;
        if (val < min) val = min;
        if (val > max) val = max;
        input.value = val;

        // 논리적 오류 방지
        const isMin = key === 'min';
        const otherId = isMin ? `reg-${idx}-max` : `reg-${idx}-min`;
        const otherEl = document.getElementById(otherId);
        if (otherEl) {
            let otherVal = parseInt(otherEl.value) || 0;
            if (isMin && val > otherVal) {
                otherEl.value = val;
                this.updateRegressionRange(idx, 'max', val);
            } else if (!isMin && val < otherVal) {
                otherEl.value = val;
                this.updateRegressionRange(idx, 'min', val);
            }
        }

        this.updateRegressionRange(idx, key, val);
    },

    async loadAIRangesCache() {
        // [Phase 4.4] AI 추천 범위를 state에 캐싱 (1회만 로드)
        if (this.state._aiRangesLoaded) return;
        this.state._aiRangesLoaded = true;
        try {
            if (window.filterService && window.filterService.loadAIRanges) {
                this.state.aiRanges = await window.filterService.loadAIRanges();
                if (this.state.aiRanges) {
                    console.log('[FilterDashboard] AI 범위 로드 완료:', this.state.aiRanges);
                }
            }
        } catch (e) {
            console.warn('[FilterDashboard] AI 범위 로드 실패:', e);
        }
    },

    renderUI() {
        this.state.totalActiveCount = 0;
        this.renderBasket();
        this.renderFoundationFilters();
        this.renderRegressionFilters();
        this.renderCustomFilters();
        this.updateNeonCounter();

        const totalCountEl = document.getElementById('totalActiveFilterCount');
        if (totalCountEl) {
            totalCountEl.textContent = this.state.totalActiveCount;
        }
        // 헤더 높이 변동 후 탭 sticky 위치 재보정
        if (window.fixTabTop) requestAnimationFrame(window.fixTabTop);
    },

    handleDeepLink(focusId) {
        // [수정] 렌더링 완료 시간을 고려하여 조금 더 긴 지연시간 부여 및 재시도 로직 추가
        const tryScroll = (retryCount = 0) => {
            const element = document.getElementById(`filter-${focusId}`) || document.getElementById(`filter-card-${focusId}`);
            if (element) {
                element.scrollIntoView({ behavior: 'smooth', block: 'center' });
                // [수정] 하이라이트 효과 강화 (시각적 피드백 명확화)
                element.style.outline = '4px solid #6366f1';
                element.style.boxShadow = '0 0 20px rgba(99, 102, 241, 0.4)';
                element.style.zIndex = '10';

                setTimeout(() => {
                    element.style.outline = '';
                    element.style.boxShadow = '';
                    element.style.zIndex = '';
                }, 3000);
            } else if (retryCount < 3) {
                // 아직 렌더링되지 않았을 경우 500ms 간격으로 최대 3번 더 시도
                setTimeout(() => tryScroll(retryCount + 1), 500);
            }
        };

        setTimeout(() => tryScroll(0), 500);
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

            const { data: draws } = await window.supabaseClient.from('lotto_draws').select('*').order('round', { ascending: false }).limit(500);
            this.state.allDraws = draws || [];
            this._regStatCache = null; // allDraws 갱신 시 GAP/STR 캐시 리셋

            if (this.state.allDraws.length > 0) {
                // [추가] 차기 회차 계산 (regression.html과 동일한 로직)
                this.state.targetRound = this.state.allDraws[0].round + 1;
                console.log(`[FilterDashboard] Current Target Round: ${this.state.targetRound}`);

                // 회차 변경 감지 (최근 10회차 자동 활성화용)
                const _savedLastRound = parseInt(localStorage.getItem('_fdb_lastKnownRound') || '0');
                const _currentRound = this.state.allDraws[0].round;
                this._newRoundDetected = _savedLastRound > 0 && _savedLastRound < _currentRound;
                if (_currentRound > _savedLastRound) {
                    localStorage.setItem('_fdb_lastKnownRound', _currentRound.toString());
                }

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



            const allSettings = await window.filterService.loadAllSettings(this.state.targetRound);
            console.log('[FilterDashboard] All Settings Loaded', allSettings);

            this.state.userSettings = {};
            this.state.regressionSettings = {};
            this.state.regressionEnabled = false;

            for (const def of this.state.foundationFilters) {
                const defaultParsed = typeof def.default_settings === 'string' ? JSON.parse(def.default_settings) : (def.default_settings || {});

                // localStorage 우선순위: filter_key_filter -> filter_key
                let rawLocalData = null;
                try {
                    // localStorage 우선순위: filter_key_filter -> filter_key
                    // [수정] missing_period의 경우 suffix가 없는 키가 우선임
                    let localKey = `${def.filter_key}_filter`;
                    if (def.filter_key === 'missing_period') localKey = 'missing_period';

                    const raw = localStorage.getItem(def.filter_key) || localStorage.getItem(localKey);
                    if (raw) rawLocalData = JSON.parse(raw);

                    // [tail_digit 호환] tail_digit.html이 사용하는 추가 키 체크
                    if (!rawLocalData && def.filter_key === 'tail_digit_patterns') {
                        const raw2 = localStorage.getItem('tail_digit_filter') || localStorage.getItem('lottoDigitFilters');
                        if (raw2) rawLocalData = JSON.parse(raw2);
                    }
                    // [composite 호환] 구버전 composite_number.html이 'composite_number_filter'로 저장했던 레거시 데이터 대응
                    if (!rawLocalData && def.filter_key === 'composite_count') {
                        const raw2 = localStorage.getItem('composite_number_filter');
                        if (raw2) rawLocalData = JSON.parse(raw2);
                    }
                } catch (e) { }

                // [수정] 데이터베이스(allSettings)에서 데이터 조회 시 매핑된 키도 함께 확인
                const standardKeyMapping = {
                    'ac_value': 'ac_value_filter',
                    'high_low_pattern': 'low_high_filter',
                    'odd_even_pattern': 'odd_even_filter',
                    'composite_count': 'composite_filter',
                    'prime_number_patterns': 'prime_filter',
                    'neighbor_count': 'neighbor_number_patterns'  // 구 키 하위 호환 로드
                };
                // 레거시 키 → localStorage 폴백 맵 (composite_number.html이 구버전에서 'composite_number_filter'로 저장했던 데이터 대응)
                const legacyLocalKeyMapping = {
                    'composite_count': 'composite_number_filter'
                };
                const altKey = standardKeyMapping[def.filter_key];
                const dbEntry = allSettings[def.filter_key] || (altKey ? allSettings[altKey] : null);

                if (dbEntry) {
                    // [fix-296] DB가 단일 진실 공급원 (Single Source of Truth)
                    // localStorage 우선 로직 제거 — DB가 항상 진실, localStorage는 단순 캐시
                    // (이전: lsTs > dbTs면 localStorage 사용 → DB 변경 무시되는 문제 발생)
                    {
                        // DB primary로 사용
                        this.state.userSettings[def.id] = {
                            enabled: dbEntry.enabled,
                            settings: dbEntry.settings || {}
                        };

                        // [핵심] DB-primary일 때 Local 캐시로 누락 데이터 보완
                        if (rawLocalData) {
                            // Utils.saveFilter 표준 구조 대응 (Unboxing)
                            const localSettings = (rawLocalData.settings !== undefined) ? rawLocalData.settings : rawLocalData;
                            // [수정] localStorage에 값이 있다면 (analysis 페이지에서 온 경우) 명시적으로 false가 아닌 한 적용(true)으로 간주
                            const localEnabled = (rawLocalData.enabled !== undefined) ? rawLocalData.enabled : true;

                            this.state.userSettings[def.id].enabled = this.state.userSettings[def.id].enabled || localEnabled;
                            const dbSettings = this.state.userSettings[def.id].settings;

                            // 1. 제외 값들 병합 (합계, AC값 등)
                            const isAc = def.filter_key.includes('ac_value');
                            const exKeyDB = isAc ? 'excludedAcValues' : 'excludedSums';
                            const exKeyLocal = localSettings.excludedAcValues || localSettings.excludedSums || localSettings.excluded || [];

                            if ((!dbSettings[exKeyDB] || dbSettings[exKeyDB].length === 0) && Array.isArray(exKeyLocal) && exKeyLocal.length > 0) {
                                console.log(`💡 [Merge] ${def.filter_key}: Local ${exKeyDB} recovered to DB state`);
                                dbSettings[exKeyDB] = exKeyLocal;
                            }

                            // 2. 범위값 병합: DB ranges 내부 → local 순으로 fallback
                            if (dbSettings.min === undefined) {
                                if (dbSettings.ranges?.min !== undefined) dbSettings.min = dbSettings.ranges.min;
                                else if (localSettings.min !== undefined) dbSettings.min = localSettings.min;
                                else if (localSettings.ranges?.min !== undefined) dbSettings.min = localSettings.ranges.min;
                            }
                            if (dbSettings.max === undefined) {
                                if (dbSettings.ranges?.max !== undefined) dbSettings.max = dbSettings.ranges.max;
                                else if (localSettings.max !== undefined) dbSettings.max = localSettings.max;
                                else if (localSettings.ranges?.max !== undefined) dbSettings.max = localSettings.ranges.max;
                            }

                            // 3. recent10FilterActive 플래그 병합
                            if (!dbSettings.recent10FilterActive && localSettings.recent10FilterActive) {
                                dbSettings.recent10FilterActive = localSettings.recent10FilterActive;
                            }

                            // 4. 복원된 자동 제외값 병합
                            const resKeyDB = isAc ? 'restoredAutoAcValues' : 'restoredAutoSums';
                            const resKeyLocal = localSettings.restoredAutoAcValues || localSettings.restoredAutoSums || [];
                            if ((!dbSettings[resKeyDB] || dbSettings[resKeyDB].length === 0) && resKeyLocal.length > 0) {
                                dbSettings[resKeyDB] = resKeyLocal;
                            }

                            // 5. 계수형 필터(소수, 합성수 등) 데이터 지능형 병합
                            const discreteKeys = ['prime_number_patterns', 'composite_count', 'odd_even_pattern', 'high_low_pattern'];
                            if (discreteKeys.includes(def.filter_key)) {
                                let targetArrName = 'selectedCounts';
                                if (def.filter_key === 'odd_even_pattern' || def.filter_key === 'high_low_pattern') {
                                    targetArrName = 'selectedRatios';
                                }
                                if ((!dbSettings[targetArrName] || dbSettings[targetArrName].length === 0) && localSettings[targetArrName]) {
                                    dbSettings[targetArrName] = localSettings[targetArrName];
                                }
                            }

                            // 6. [tail_digit 전용] filters 복구
                            if (def.filter_key === 'tail_digit_patterns' && localSettings.filters) {
                                dbSettings.filters = localSettings.filters;
                            }

                            // 7. [missing_custom_filter] filters 복구
                            if (def.filter_key === 'missing_custom_filter' && Array.isArray(localSettings.filters) && localSettings.filters.length > 0) {
                                if (!Array.isArray(dbSettings.filters) || dbSettings.filters.length === 0) {
                                    const lsTargetRound = localSettings.targetRound;
                                    const curExpected = this.state.allDraws.length > 0 ? this.state.allDraws[0].round + 1 : null;
                                    if (!lsTargetRound || !curExpected || lsTargetRound === curExpected) {
                                        dbSettings.filters = localSettings.filters;
                                        if (localSettings.counter) dbSettings.counter = localSettings.counter;
                                    }
                                }
                            }

                            // 8. [missing_period] ranges 복구
                            if (def.filter_key === 'missing_period' && localSettings.ranges) {
                                if (!dbSettings.ranges || Object.keys(dbSettings.ranges).length === 0) {
                                    dbSettings.ranges = localSettings.ranges;
                                }
                            }
                        }
                    }
                } else if (rawLocalData) {
                    const localSettings = rawLocalData.settings !== undefined ? rawLocalData.settings : rawLocalData;
                    const localEnabled = rawLocalData.enabled !== undefined ? rawLocalData.enabled : (rawLocalData.enabled !== false);
                    this.state.userSettings[def.id] = {
                        enabled: localEnabled,
                        settings: Object.keys(localSettings).length > 0 ? localSettings : defaultParsed
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

            // 신규 회차 감지 시 recent10FilterActive 자동 활성화
            if (this._newRoundDetected) {
                console.log('[FilterDashboard] 🎉 신규 회차! 모든 필터 recent10FilterActive 자동 활성화...');
                const recent10 = this.state.allDraws.slice(0, 10);
                const flagOnlyKeys = ['total_sum', 'tail_sum', 'ac_value', 'odd_even_pattern', 'high_low_pattern', 'prime_number_patterns', 'composite_count', 'missing_period'];
                for (const def of this.state.foundationFilters) {
                    const us = this.state.userSettings[def.id];
                    if (!us || def.filter_key === 'missing_custom_filter') continue;
                    us.settings.recent10FilterActive = true;
                    us.enabled = true; // 신규 회차 시 필터를 자동으로 활성화 (대시보드 "적용" 상태 표시)
                    if (!flagOnlyKeys.includes(def.filter_key) && def.filter_key !== 'tail_digit_patterns') {
                        this._calcAndApplyRecent10(def.filter_key, us, recent10);
                    } else if (def.filter_key === 'tail_digit_patterns') {
                        // tail_digit는 값 직접 계산
                        const counts = Array.from({ length: 10 }, () => []);
                        recent10.forEach(draw => {
                            const digitCounts = new Array(10).fill(0);
                            (draw.numbers || []).forEach(n => digitCounts[n % 10]++);
                            for (let i = 0; i < 10; i++) counts[i].push(digitCounts[i]);
                        });
                        if (!us.settings.filters) us.settings.filters = {};
                        for (let i = 0; i < 10; i++) {
                            us.settings.filters[i] = { min: Math.min(...counts[i]), max: Math.max(...counts[i]) };
                        }
                    }
                }
                this._newRoundDetected = false;
                // 비동기 배치 저장 (렌더링 차단 안 함)
                setTimeout(async () => {
                    for (const def of this.state.foundationFilters) {
                        const us = this.state.userSettings[def.id];
                        if (!us || def.filter_key === 'missing_custom_filter') continue;
                        if (window.Utils && window.Utils.saveFilter) {
                            await window.Utils.saveFilter(def.filter_key, us.settings, us.enabled, this.state.targetRound);
                        }
                    }
                    console.log('[FilterDashboard] ✅ recent10 배치 저장 완료');
                }, 200);
            }

            // ── missing_custom_filter: targetRound 업데이트 (그룹은 유지) ───────────
            // 커스텀 그룹(사용자 직접 생성)은 회차가 변경되어도 삭제하지 않음
            // 회차 불일치 감지 시 targetRound만 갱신하여 다음 로드에서 오탐 방지
            const mcDef = this.state.foundationFilters.find(d => d.filter_key === 'missing_custom_filter');
            if (mcDef && this.state.userSettings[mcDef.id] && this.state.allDraws.length > 0) {
                const mcSet = this.state.userSettings[mcDef.id];
                const savedRound = mcSet.settings?.targetRound;
                const latestDraw = this.state.allDraws[0].round;
                const expectedTargetRound = latestDraw + 1;

                // targetRound가 없거나 구 회차이면 갱신만 (filters는 절대 지우지 않음)
                if (!savedRound || savedRound !== expectedTargetRound) {
                    // [버그 수정] filters가 비어 있으면 저장 자체 skip (빈 상태로 1223 행 덮어쓰기 방지)
                    const hasGroups = Array.isArray(mcSet.settings?.filters) && mcSet.settings.filters.length > 0;
                    if (!hasGroups) {
                        console.log(`[Dashboard] missing_custom_filter 빈 그룹 — targetRound 갱신 skip (1223 행 보호)`);
                    } else {
                        console.log(`[Dashboard] missing_custom_filter targetRound 갱신: ${savedRound} → ${expectedTargetRound} (그룹 유지)`);
                        mcSet.settings.targetRound = expectedTargetRound;
                        if (window.filterService?.initialized) {
                            // [2026-05-14] targetRound 명시 — 회차별 행에 저장 (NULL 행으로 빠지지 않도록)
                            await window.filterService.saveSetting('missing_custom_filter', mcSet.settings, mcSet.enabled, expectedTargetRound);
                        }
                        // localStorage 동기화
                        try {
                            const lsRaw = localStorage.getItem('missing_custom_filter');
                            if (lsRaw) {
                                const lsParsed = JSON.parse(lsRaw);
                                if (lsParsed.settings) lsParsed.settings.targetRound = expectedTargetRound;
                                lsParsed.targetRound = expectedTargetRound;
                                localStorage.setItem('missing_custom_filter', JSON.stringify(lsParsed));
                            }
                        } catch (e) { }
                    }
                }
            }
            // ────────────────────────────────────────────────────────────────────────

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


            // [수정] 커스텀 분석 데이터 로드 (필터링 조건 완화 및 안정화)
            // [fix-264] created_at ASC 정렬 — lnbOrder에 없는 신규 필터가 자연스럽게 맨 끝으로
            //          (layout.js 사이드바도 ASC로 동일한 기준)
            let _customQuery = window.supabaseClient.from('ai_custom_analyses').select('*')
                .is('target_round', null) // [추가] 마스터 행만 조회 (회차별 스냅샷 제외)
                .or('is_archived.is.null,is_archived.eq.false')   // [fix-385] archived 제외
                .order('created_at', { ascending: true });
            const _customUserId = window.filterService?.userId;

            // [Fix] userId 유무와 관계없이 항상 공용(user_id IS NULL) 데이터 포함
            if (_customUserId) {
                _customQuery = _customQuery.or(`user_id.eq.${_customUserId},user_id.is.null`);
            } else {
                // userId 없을 때도 공용 데이터 명시적 로드
                _customQuery = _customQuery.is('user_id', null);
            }

            const { data: customs, error: customsError } = await _customQuery;
            if (customsError) console.error("Custom Analyses Load Error:", customsError);
            console.log(`[FilterDashboard] Custom filters loaded: ${(customs || []).length}개 (userId: ${_customUserId || 'none'})`);
            this.state.customFilters = customs || [];

            // [추가] AI 모델 및 커스텀 분석 대상 번호(history) 로드
            try {
                const { data: latestHistories } = await window.supabaseClient
                    .from('analysis_history')
                    .select('*')
                    .eq('target_round', this.state.targetRound);

                if (latestHistories && latestHistories.length > 0) {
                    this.state.customFilters.forEach(custom => {
                        const hist = latestHistories.find(h => h.analysis_id === custom.id);
                        if (hist && hist.target_numbers && hist.target_numbers.length > 0) {
                            // [수성] history_data가 있으면 memory 상에 임시 저장하여 렌더링 시 사용
                            custom.target_numbers = hist.target_numbers;
                        }
                    });
                }

                // [추가] AI 실시간 예측 데이터 로드 (AIProxy) - 최신 회차 데이터가 없으면 이전 회차 시도
                if (window.AIProxy && typeof window.AIProxy.getPredictions === 'function') {
                    const fetchWithFallback = async (round, attempts = 10) => {
                        const aiResult = await window.AIProxy.getPredictions(round);
                        if (aiResult) {
                            const data = (aiResult.success && aiResult.data) ? aiResult.data : aiResult;
                            const hasData = data.matrix_data || (data.analysis && data.analysis.matrix_data) || data.top_5;
                            if (hasData) return data;
                        }
                        if (attempts > 1 && round > 1) return await fetchWithFallback(round - 1, attempts - 1);
                        return null;
                    };

                    const finalAiData = await fetchWithFallback(this.state.targetRound);
                    if (finalAiData) {
                        this.state.aiUpcomingData = finalAiData;
                        console.log(`📡 [FilterDashboard] AI 예측 데이터 로드 완료 (${this.state.targetRound}회 또는 이전)`);
                    }
                }
            } catch (e) {
                console.warn("[FilterDashboard] AI/History data hydration failed:", e);
            }

            // [수정] 사이드바(layout.js)와 동일한 사용자 기반 스토리지 키 사용 (lnbOrder_custom_[userId])
            try {
                const _menuUserId = window.filterService?.userId
                    || (await window.supabaseClient.auth.getUser()).data?.user?.id
                    || localStorage.getItem('_lastLoginUserId')
                    || null;

                const storageKey = _menuUserId ? `lnbOrder_custom_${_menuUserId}` : 'lnbOrder_custom_guest';
                const _savedOrder = JSON.parse(localStorage.getItem(storageKey));

                if (_savedOrder && _savedOrder.length > 0) {
                    this.state.customFilters.sort((a, b) => {
                        const hA = `custom_analysis.html?id=${a.id}`;
                        const hB = `custom_analysis.html?id=${b.id}`;
                        const iA = _savedOrder.indexOf(hA);
                        const iB = _savedOrder.indexOf(hB);
                        if (iA !== -1 && iB !== -1) return iA - iB;
                        if (iA !== -1) return -1;
                        if (iB !== -1) return 1;
                        return 0;
                    });
                }
            } catch (e) { /* ignore */ }

            // ── 수동 필터 로드 (manual_filters 테이블) ──────────────
            try {
                const { data: manuals, error: manualsError } = await window.supabaseClient
                    .from('manual_filters')
                    .select('*')
                    .order('created_at', { ascending: false });
                if (manualsError) console.error('[FilterDashboard] manual_filters 로드 실패:', manualsError);
                this.state.manualFilters = manuals || [];
            } catch (e) { console.error('[FilterDashboard] manual_filters 예외:', e); }

            let loadedBasket = { fixed: [], exclude: [] };
            try { loadedBasket = JSON.parse(localStorage.getItem('lotto_basket')) || { fixed: [], exclude: [] }; } catch (e) { }
            this.state.basket = { fixed: loadedBasket.fixed || [], excluded: loadedBasket.exclude || [] };

        } catch (error) { console.error("DB Load Error:", error); }
    },

    renderBalls(numbers, excludedList = [], fixedList = [], ballPx = null) {
        if (!numbers || numbers.length === 0) return '<span class="text-xs text-slate-400 font-black italic">분석 결과 없음</span>';
        const finalFixed = fixedList.length > 0 ? fixedList : this.state.basket.fixed;
        const finalExcluded = excludedList.length > 0 ? excludedList : this.state.basket.excluded;

        const getBallStyle = (n) => {
            if (n <= 10) return { bg: '#f59e0b', border: '#d97706' };
            if (n <= 20) return { bg: '#3b82f6', border: '#2563eb' };
            if (n <= 30) return { bg: '#ef4444', border: '#dc2626' };
            if (n <= 40) return { bg: '#6b7280', border: '#4b5563' };
            return { bg: '#10b981', border: '#059669' };
        };

        const sizeStyle = ballPx
            ? `width:${ballPx}px !important; height:${ballPx}px !important; min-width:${ballPx}px !important; min-height:${ballPx}px !important; font-size:${Math.round(ballPx * 0.38)}px !important; margin:2px !important; flex-shrink:0 !important; border-radius:50% !important;`
            : '';
        const baseClass = ballPx
            ? `flex items-center justify-center rounded-full font-black shadow-sm border `
            : `w-8 h-8 flex items-center justify-center rounded-full text-[12px] font-black shadow-sm border transition-all `;

        return numbers.map(n => {
            const isEx = finalExcluded.includes(n);
            const isFi = finalFixed.includes(n);
            const s = getBallStyle(n);

            let ballClass = baseClass;
            let inlineStyle = sizeStyle;

            if (isFi) {
                ballClass += "ball-fixed text-white";
                inlineStyle += "background-color: #2563eb; border-color: #3b82f6; border-width: 2px; box-shadow: 0 0 8px rgba(37, 99, 235, 0.4);";
            } else if (isEx) {
                ballClass += "ball-excluded text-white/90";
                inlineStyle += `background-color: #94a3b8; border-color: #64748b; border-width: 1px; text-decoration: line-through; opacity: 0.6;`;
            } else {
                ballClass += "text-white";
                inlineStyle += `background-color: ${s.bg}; border-color: ${s.border};`;
            }
            return `<span class="${ballClass}" style="${inlineStyle}">${String(n).padStart(2, '0')}</span>`;
        }).join('');
    },

    getFilterLink(key) {
        const mapping = {
            'total_sum': 'total_sum.html', 'tail_sum': 'tail_sum.html', 'ac_value': 'ac_value.html',
            'prime_number_patterns': 'prime_number.html', 'composite_count': 'composite_number.html',
            'square_number_patterns': 'square_number.html', 'triangular_number_patterns': 'triangular_number.html',
            'twin_number_patterns': 'twin_number.html', 'neighbor_count': 'neighbor_number.html', 'neighbor_number_patterns': 'neighbor_number.html',
            'carryover_count': 'carryover.html', 'consecutive_count': 'consecutive_number.html',
            'odd_even_pattern': 'odd_even.html', 'high_low_pattern': 'low_high.html',
            'tail_digit_patterns': 'tail_digit.html',
            'hot_cold_5': 'hot_cold.html?period=5', 'hot_cold_10': 'hot_cold.html?period=10',
            'hot_cold_15': 'hot_cold.html?period=15', 'hot_cold_20': 'hot_cold.html?period=20',
            'missing_period': 'missing.html',
            'missing_custom_filter': 'missing.html',
            'long_term_miss': 'missing.html',
            // [fix-300] 9개 배수 키 모두 multiple.html의 row anchor로 직접 점프
            'multiple_3_count':   'multiple.html#filter-row-multiple_3_count',
            'multiple_4_count':   'multiple.html#filter-row-multiple_4_count',
            'multiple_5_count':   'multiple.html#filter-row-multiple_5_count',
            'multiple_7_count':   'multiple.html#filter-row-multiple_7_count',
            'multiple_8_count':   'multiple.html#filter-row-multiple_8_count',
            'multiple_3_4_count': 'multiple.html#filter-row-multiple_3_4_count',
            'multiple_3_5_count': 'multiple.html#filter-row-multiple_3_5_count',
            'multiple_4_5_count': 'multiple.html#filter-row-multiple_4_5_count',
            'no_multiple_count':  'multiple.html#filter-row-no_multiple_count',
            'number_range_patterns': 'number_range.html', 'lotto_paper_pattern': 'lotto_paper.html',
            'magic_square_pattern': 'magic_square.html'
        };
        return mapping[key] || `${key}.html`;
    },

    calculateCustomTargets(custom) {
        // [추가] AI 모델 타입에 대한 실시간/이력 대상 번호 매핑 (11 base 토폴로지)
        const title = (custom.title || '').toUpperCase();
        const isAiModelTitle = !!title.match(/(GNN|CNN|MARKOV|AUTOENCODER|XGBOOST|XGB|CATBOOST|TABNET|TFT|N-?BEATS|NBEATS|MHN|BAYESIAN|ENSEMBLE|앙상블|추천조합|TF|ATC|AE|AI|딥러닝|추천|제외)/i);
        const isAiType = (custom.type && custom.type.startsWith('ai_')) || isAiModelTitle;

        if (isAiType && this.state.aiUpcomingData) {
            const aiData = this.state.aiUpcomingData;
            const titleMatch = title.match(/(\d+)/);
            const titleCount = titleMatch ? parseInt(titleMatch[0]) : null;

            // 1. 앙상블 고정/제외 타입
            if (custom.type === 'ai_ensemble_fixed' || (isAiModelTitle && title.includes('추천') && !title.includes('제외'))) {
                return (aiData.top_5 || aiData.recommended || []).slice(0, 6).map(Number);
            } else if (custom.type === 'ai_ensemble_excluded' || (isAiModelTitle && title.includes('제외'))) {
                return (aiData.exclude_10 || aiData.excluded || []).map(Number);
            }
            // 2. 모델별 TOP/BOTTOM 타입 또는 타이틀 기반 모델 자동 인식
            else if (custom.type === 'ai_model_top' || custom.type === 'ai_model_bottom' || isAiModelTitle) {
                let model = (custom.rules?.model || 'ensemble').toLowerCase();

                // [추가] 타이틀 기반 모델 자동 인식 (TFT 20, XGB 20, CatBoost 10 등)
                if (isAiModelTitle && (!custom.rules?.model || model === 'ensemble')) {
                    const matched = title.match(/(GNN|CNN|MARKOV|AUTOENCODER|XGBOOST|XGB|CATBOOST|TABNET|TFT|N-?BEATS|NBEATS|MHN|BAYESIAN|TF|ATC|AE|앙상블)/i);
                    if (matched) {
                        model = matched[0].toLowerCase().replace('-', '');
                        if (model === 'tf') model = 'tft';
                        if (model === 'atc' || model === 'ae') model = 'autoencoder';
                        if (model === 'xgb') model = 'xgboost';
                        if (model === 'bayesian') model = 'bayesian_nn';
                        if (model === '앙상블') model = 'ensemble';
                    }
                }

                const isTarget20 = title.includes('20');
                const count = parseInt(custom.rules?.count || titleCount || (isTarget20 ? 20 : 10));
                const isTop = (custom.type !== 'ai_model_bottom');

                // [수정] AI 데이터 중첩 구조 지원 (matrix_data가 analysis 내부에 있는 경우 대응)
                const matrixData = aiData.matrix_data || (aiData.analysis && aiData.analysis.matrix_data) || [];

                if (matrixData.length > 0) {
                    const sorted = [...matrixData].sort((a, b) => {
                        let scoreA, scoreB;
                        if (model === 'ensemble' || model === 'total' || model === '앙상블') {
                            scoreA = a.total !== undefined ? a.total : 0;
                            scoreB = b.total !== undefined ? b.total : 0;
                        } else {
                            // [수정] 모델 점수 추출 유연성 강화 (객체 내 score 필드 또는 직접 값 대응)
                            const scoresA = a.models || a;
                            const scoresB = b.models || b;
                            scoreA = scoresA[model]?.score !== undefined ? scoresA[model].score : (scoresA[model] || 0);
                            scoreB = scoresB[model]?.score !== undefined ? scoresB[model].score : (scoresB[model] || 0);
                        }
                        return isTop ? (scoreB - scoreA) : (scoreA - scoreB);
                    });
                    return sorted.slice(0, count).map(item => Number(item.num));
                }
            }
        }

        // AI 타입이더라도 history에서 로드된 target_numbers가 있으면 우선 사용 (fallback)
        if (custom.target_numbers && custom.target_numbers.length > 0) {
            return custom.target_numbers.map(Number);
        }

        // 기존 공통 로직 실행 (static, dynamic, group 등)
        return window.LOTTO_CONSTANTS.calculateCustomTargets(custom, this.state.allDraws, { isPrediction: true });
    },

    buildFilterControl(def, userSet) {
        const key = def.filter_key;
        const vals = userSet.settings || {};
        let html = '';

        const targetNums = this.state.staticTargets[key] || this.state.dynamicTargets[key];
        const excludedNums = vals.excludedNumbers || vals.excludedPrimes || vals.excludedComposites || vals.excludedSquares || vals.excludedTriangulars || [];

        const SMALL_BALL = "w-6 h-6 flex items-center justify-center rounded-full text-[10px] font-black shadow-sm border transaction-all ";
        const NORMAL_BALL = "w-8 h-8 flex items-center justify-center rounded-full text-[12px] font-black shadow-sm border transaction-all ";
        const LARGE_BALL = "w-10 h-10 flex items-center justify-center rounded-full text-[14px] font-black shadow-sm border transaction-all ";

        let dynamicSizeClass = NORMAL_BALL;
        if (['neighbor_count', 'neighbor_number_patterns', 'carryover_count', 'prime_number_patterns', 'composite_count', 'triangular_number_patterns', 'square_number_patterns', 'twin_number_patterns'].includes(key)) {
            dynamicSizeClass = SMALL_BALL;
        } else if (['number_range_patterns', 'color_range_pattern', 'magic_square_pattern', 'lotto_paper_pattern', 'hot_cold_5', 'hot_cold_10', 'hot_cold_15', 'hot_cold_20', 'missing_period', 'missing_custom_filter', 'long_term_miss'].includes(key)) {
            dynamicSizeClass = LARGE_BALL;
        }

        // 이월수 필터는 대상번호 박스를 개별 섹션 내부에 그리므로 여기선 스킵
        if (targetNums && key !== 'carryover_count') {
            html += `
            <div class="mt-4 mb-4 p-3 bg-slate-50 border border-slate-100 rounded-xl">
                <div class="mb-2 flex justify-between items-center">
                    <span class="text-xs font-bold text-slate-500">대상번호</span>
                    <span class="text-[11px] font-black text-blue-600">${targetNums.length}개</span>
                </div>
                <div class="flex flex-wrap gap-1.5">
                    ${this.renderBalls(targetNums, excludedNums, [], dynamicSizeClass)}
                </div>
            </div>`;
        }

        const isRange = key.includes('sum') || key.includes('ac_value') || key.includes('neighbor');

        if (isRange) {
            const defaultSet = typeof def.default_settings === 'string' ? JSON.parse(def.default_settings) : (def.default_settings || {});
            const isCountFilter = key.includes('count') || key.includes('number_patterns') || key.includes('missing_period');
            // [수정] AC값(10), 끝수합(60) 등 필터 속성에 맞는 정확한 Max값 설정 (0-6 고정 오류 해결)
            const defaultMax = isCountFilter ? 6 :
                (key.includes('total_sum') ? 255 :
                    (key.includes('tail_sum') ? 60 :
                        (key.includes('ac_value') ? 10 : 45)));

            const min = vals.min !== undefined ? vals.min : (defaultSet.min !== undefined ? defaultSet.min : 0);
            const max = vals.max !== undefined ? vals.max : (defaultSet.max !== undefined ? defaultSet.max : defaultMax);

            // [수정] 탭별 메인 색상 적용 (기초분석: Blue)
            const ringColor = 'focus-within:ring-blue-500';
            const textColor = 'text-blue-600';

            // [Phase 4] AI 추천 범위 뱃지 (deep_analysis_history.range_analysis 기반)
            // ⚠ 4계층 동기화: 키 = filter_definitions.filter_key, 값 = loadAIRanges() 반환 키 (= 컬럼 prefix _min/_max)
            const AI_KEY_MAP = {
                'total_sum':                  ['total_sum_min',                  'total_sum_max'],
                'ac_value':                   ['ac_value_min',                   'ac_value_max'],
                'tail_sum':                   ['tail_sum_min',                   'tail_sum_max'],
                'odd_even_pattern':           ['odd_even_pattern_min',           'odd_even_pattern_max'],
                'high_low_pattern':           ['high_low_pattern_min',           'high_low_pattern_max'],
                'consecutive_count':          ['consecutive_count_min',          'consecutive_count_max'],
                'prime_number_patterns':      ['prime_number_patterns_min',      'prime_number_patterns_max'],
                'composite_count':            ['composite_count_min',            'composite_count_max'],
                'square_number_patterns':     ['square_number_patterns_min',     'square_number_patterns_max'],
                'triangular_number_patterns': ['triangular_number_patterns_min', 'triangular_number_patterns_max'],
                'twin_number_patterns':       ['twin_number_patterns_min',       'twin_number_patterns_max'],
                'multiple_3_count':           ['multiple_3_count_min',           'multiple_3_count_max'],
                'multiple_7_count':           ['multiple_7_count_min',           'multiple_7_count_max'],
                'multiple_8_count':           ['multiple_8_count_min',           'multiple_8_count_max'],
                'missing_period':             ['missing_period_min',             'missing_period_max'],
                'neighbor_number_patterns':   ['neighbor_number_patterns_min',   'neighbor_number_patterns_max'],
            };
            let aiRangeBadge = '';
            const aiCols = AI_KEY_MAP[key];
            const aiRanges = this.state.aiRanges;
            if (aiRanges && aiCols) {
                const aMin = aiRanges[aiCols[0]]; const aMax = aiRanges[aiCols[1]];
                if (aMin != null && aMax != null) {
                    aiRangeBadge = `<span class="text-[10px] font-black bg-indigo-50 text-indigo-600 px-2 py-0.5 rounded-full ring-1 ring-indigo-200 cursor-pointer hover:bg-indigo-100 transition"
                        title="AI 추천값 클릭 시 적용"
                        onclick="document.getElementById('input-${def.id}-min').value=${aMin}; document.getElementById('input-${def.id}-max').value=${aMax}; FilterDashboard.updateFilterValue('${def.id}','min',${aMin}); FilterDashboard.updateFilterValue('${def.id}','max',${aMax});">
                        AI ${aMin}~${aMax}
                    </span>`;
                }
            }

            // 총합/끝수합처럼 3자리 값을 갖는 필터는 input 너비 확장
            const _wideRangeKeys = new Set(['total_sum', 'tail_sum', 'missing_period']);
            const _inputWidthCls = _wideRangeKeys.has(key) ? 'w-20' : 'w-14';
            html += `
            <div class="flex items-center justify-end gap-3">
                ${aiRangeBadge}
                <div class="flex items-center gap-2">
                    <input type="number" id="input-${def.id}-min" min="0" max="${defaultMax}" value="${min}"
                        onchange="FilterDashboard.updateFilterValue('${def.id}', 'min', this.value)"
                        class="${_inputWidthCls} h-8 text-center text-sm font-bold text-gray-900 border-0 border-b-2 border-gray-200 focus:border-blue-500 focus:outline-none focus:ring-0 bg-transparent">
                    <span class="text-xs text-gray-400">~</span>
                    <input type="number" id="input-${def.id}-max" min="0" max="${defaultMax}" value="${max}"
                        onchange="FilterDashboard.updateFilterValue('${def.id}', 'max', this.value)"
                        class="${_inputWidthCls} h-8 text-center text-sm font-bold text-gray-900 border-0 border-b-2 border-gray-200 focus:border-blue-500 focus:outline-none focus:ring-0 bg-transparent">
                </div>
            </div>`;

            if (key === 'total_sum' || key === 'tail_sum' || key === 'ac_value') {
                const manualExcluded = key === 'ac_value' ? (vals.excludedAcValues || []) : (vals.excludedSums || vals.excluded || []);

                // 시스템 자동 제외
                let systemExcluded = [];
                const restoredAuto = vals.restoredAutoSums || vals.restoredAutoAcValues || [];

                if (vals.recent10FilterActive && this.state.allDraws && this.state.allDraws.length > 0) {
                    // recent10 활성: 실시간 계산
                    if (key === 'total_sum') {
                        systemExcluded = [...new Set(
                            this.state.allDraws.slice(0, 10).map(d => {
                                if (d.sum !== undefined && d.sum !== null) return d.sum;
                                if (d.numbers && Array.isArray(d.numbers)) return d.numbers.reduce((a, b) => a + b, 0);
                                return null;
                            }).filter(s => s !== null && !isNaN(s))
                        )].filter(s => !restoredAuto.includes(s)).sort((a, b) => a - b);
                    } else if (key === 'tail_sum') {
                        const latestDraw = this.state.allDraws[0];
                        let latestTailSum = null;
                        if (latestDraw) {
                            if (latestDraw.tail_sum !== undefined && latestDraw.tail_sum !== null) latestTailSum = latestDraw.tail_sum;
                            else if (latestDraw.numbers && Array.isArray(latestDraw.numbers)) latestTailSum = latestDraw.numbers.reduce((a, b) => a + (b % 10), 0);
                        }
                        if (latestTailSum !== null && !restoredAuto.includes(latestTailSum)) systemExcluded = [latestTailSum];
                    } else if (key === 'ac_value') {
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
                } else {
                    // recent10 비활성: 저장된 캐시로 폴백 (배지 영속 표시)
                    const cacheKey = key === 'ac_value' ? 'cachedAutoAcExcluded' : 'cachedAutoExcluded';
                    const cached = vals[cacheKey];
                    if (Array.isArray(cached) && cached.length > 0) {
                        systemExcluded = cached.filter(s => !restoredAuto.includes(s));
                    }
                }

                const hasManual = manualExcluded.length > 0;
                const hasSystem = systemExcluded.length > 0;

                if (hasManual || hasSystem) {
                    const label = key.includes('tail_sum') ? '끝수합' : key.includes('ac_value') ? 'AC값' : '합계';
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
                        const displayFn = key.includes('ac_value') ? (v => `AC${v}`) : (v => `${v}`);
                        html += systemExcluded.map(sum => `
                            <button onclick="FilterDashboard.restoreAutoExcludedSum('${def.id}', ${sum})"
                                class="inline-flex items-center gap-1 px-2.5 py-1 bg-blue-600 text-white rounded-full text-[10px] font-black shadow-md hover:bg-blue-700 transition-colors"
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
                '1_10': { label: '단번대', count: 10 },
                '11_20': { label: '십번대', count: 10 },
                '21_30': { label: '이십번대', count: 10 },
                '31_40': { label: '삼십번대', count: 10 },
                '41_45': { label: '사십번대', count: 5 }
            };

            // 최근 5회차 자동 제외 패턴 표시
            if (vals.autoExcludeRecent5 && Array.isArray(vals.excludedPatterns) && vals.excludedPatterns.length > 0) {
                html += `<div class="mb-2 pb-2 border-b border-slate-100">
                    <div class="flex items-center gap-2 mb-1">
                        <span class="text-[11px] font-bold text-rose-600">최근 5회차 자동 제외</span>
                        <span class="text-[10px] text-slate-400">동일 패턴 차단</span>
                    </div>
                    <div class="flex gap-1 flex-wrap">
                        ${vals.excludedPatterns.map(p => `<span class="px-1.5 py-0.5 rounded text-[10px] font-mono font-bold text-rose-500 bg-rose-50 line-through">${p}</span>`).join('')}
                    </div>
                </div>`;
            }

            html += `<div class="flex flex-col gap-y-3">`;

            Object.keys(rangeTypes).forEach(type => {
                const info = rangeTypes[type];
                const f = ranges[type] || { min: 0, max: 6 };

                let [startNum, endNum] = type.split('_').map(Number);
                let numbersHtml = '';
                for (let n = startNum; n <= endNum; n++) {
                    const isEx = this.state.basket.excluded.includes(n);
                    const isFi = this.state.basket.fixed.includes(n);
                    let ballClass = "ball flex-shrink-0 flex items-center justify-center rounded-full font-black text-white shadow-sm ";
                    let color = '#F97316';
                    if (n <= 10) { color = '#F97316'; }
                    else if (n <= 20) { color = '#38BDF8'; }
                    else if (n <= 30) { color = '#EF4444'; }
                    else if (n <= 40) { color = '#6B7280'; }
                    else { color = '#84CC16'; }
                    let inlineStyle = `width:30px !important;height:30px !important;font-size:11px !important;background-color:${color} !important;`;

                    if (isFi) {
                        ballClass += "ball-fixed";
                        inlineStyle = "width:30px !important;height:30px !important;font-size:11px !important;background-color:#2563eb !important;border:2px solid #3b82f6 !important;";
                    } else if (isEx) {
                        ballClass += "ball-excluded";
                        inlineStyle = "width:30px !important;height:30px !important;font-size:11px !important;background-color:#94a3b8 !important;border:1px solid #64748b !important;";
                    }

                    numbersHtml += `<span class="${ballClass}" style="${inlineStyle}">${String(n).padStart(2, '0')}</span>`;
                }

                html += `
                    <div class="flex items-center justify-between gap-3 py-2 border-b border-gray-100 last:border-b-0">
                        <div class="flex items-center gap-3 min-w-0 flex-1">
                            <span class="text-sm font-bold text-gray-800 w-24 flex-shrink-0">${info.label}</span>
                            <div class="flex flex-wrap gap-1">${numbersHtml}</div>
                        </div>
                        <div class="flex items-center gap-2 flex-shrink-0">
                            <input type="number" min="0" max="6" value="${f.min}"
                                onchange="FilterDashboard.updateNumberRangeFilter('${def.id}', '${type}', 'min', this.value)"
                                class="w-12 h-8 text-center text-sm font-bold text-gray-900 border-0 border-b-2 border-gray-200 focus:border-blue-500 focus:outline-none focus:ring-0 bg-transparent">
                            <span class="text-xs text-gray-400">~</span>
                            <input type="number" min="0" max="6" value="${f.max}"
                                onchange="FilterDashboard.updateNumberRangeFilter('${def.id}', '${type}', 'max', this.value)"
                                class="w-12 h-8 text-center text-sm font-bold text-gray-900 border-0 border-b-2 border-gray-200 focus:border-blue-500 focus:outline-none focus:ring-0 bg-transparent">
                        </div>
                    </div>`;
            });

            // Entropy
            const ent = ranges['entropy'] || { min: '0.00', max: '3.00' };
            html += `
                    <div class="flex items-center justify-between gap-3 py-2">
                        <div class="flex items-center gap-3 flex-1">
                            <span class="text-sm font-bold text-gray-800 w-24 flex-shrink-0">엔트로피</span>
                            <span class="text-xs text-gray-400">불확실성 지표</span>
                        </div>
                        <div class="flex items-center gap-2 flex-shrink-0">
                            <input type="text" value="${parseFloat(ent.min || 0).toFixed(2)}"
                                onchange="this.value=parseFloat(this.value||0).toFixed(2); FilterDashboard.updateNumberRangeFilter('${def.id}', 'entropy', 'min', this.value)"
                                class="w-14 h-8 text-center text-sm font-bold text-gray-900 border-0 border-b-2 border-gray-200 focus:border-blue-500 focus:outline-none focus:ring-0 bg-transparent">
                            <span class="text-xs text-gray-400">~</span>
                            <input type="text" value="${parseFloat(ent.max || 3).toFixed(2)}"
                                onchange="this.value=parseFloat(this.value||0).toFixed(2); FilterDashboard.updateNumberRangeFilter('${def.id}', 'entropy', 'max', this.value)"
                                class="w-14 h-8 text-center text-sm font-bold text-gray-900 border-0 border-b-2 border-gray-200 focus:border-blue-500 focus:outline-none focus:ring-0 bg-transparent">
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
                const bg = isActive ? 'bg-blue-600 text-white border-blue-600 shadow-sm' : 'bg-white text-slate-400 border-slate-200 hover:bg-slate-50';
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
                                class="inline-flex items-center gap-1 px-2.5 py-1 bg-blue-600 text-white rounded-full text-[10px] font-black shadow-md hover:bg-blue-700 transition-colors"
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
                const bg = isActive ? 'bg-blue-600 text-white border-blue-600 shadow-sm' : 'bg-white text-slate-400 border-slate-200 hover:bg-slate-50';
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
                                class="inline-flex items-center gap-1 px-2.5 py-1 bg-blue-600 text-white rounded-full text-[10px] font-black shadow-md hover:bg-blue-700 transition-colors"
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
            // 배수 패턴: 각 배수 타입은 개별 filter_key에 flat {min,max} 형식으로 저장됨
            // multiple.html 저장 구조: Utils.saveFilter('multiple_7_count', {min,max,...})
            const MULTIPLE_TYPE_KEYS = {
                '3배수': 'multiple_3_count', '4배수': 'multiple_4_count', '5배수': 'multiple_5_count',
                '7배수': 'multiple_7_count', '8배수': 'multiple_8_count',
                '3·4배수': 'multiple_3_4_count', '3·5배수': 'multiple_3_5_count',
                '4·5배수': 'multiple_4_5_count', '배수외': 'no_multiple_count'
            };
            const MULTIPLE_MAX = { '8배수': 5, '3·4배수': 3, '3·5배수': 3, '4·5배수': 2 };
            const filters = {};
            for (const [typeName, typeKey] of Object.entries(MULTIPLE_TYPE_KEYS)) {
                const typeDef = this.state.foundationFilters.find(f => f.filter_key === typeKey);
                const s = typeDef ? (this.state.userSettings[typeDef.id]?.settings || {}) : {};
                const defaultMax = MULTIPLE_MAX[typeName] ?? 6;
                // flat 형식 우선, 없으면 번들 폴백, 없으면 기본값
                if (s.min !== undefined && s.max !== undefined) {
                    filters[typeName] = { min: s.min, max: s.max };
                } else if (vals.filters?.[typeName]) {
                    filters[typeName] = vals.filters[typeName];
                } else {
                    filters[typeName] = { min: 0, max: defaultMax };
                }
            }
            const multipleDefinitions = {
                '3배수': [3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36, 39, 42, 45],
                '4배수': [4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44],
                '5배수': [5, 10, 15, 20, 25, 30, 35, 40, 45],
                '7배수': [7, 14, 21, 28, 35, 42],
                '8배수': [8, 16, 24, 32, 40],
                '3·4배수': [12, 24, 36],
                '3·5배수': [15, 30, 45],
                '4·5배수': [20, 40],
                '배수외': [1, 2, 11, 13, 17, 19, 22, 23, 26, 29, 31, 34, 37, 38, 41, 43]
            };
            // multiple.html과 동일한 색상
            const multipleColors = {
                '3배수': '#4F6AFF', '4배수': '#10B981', '5배수': '#EC4899',
                '7배수': '#F97316', '8배수': '#06B6D4',
                '3·4배수': '#8B5CF6', '3·5배수': '#F59E0B', '4·5배수': '#14B8A6',
                '배수외': '#6B7280'
            };

            html += `<div class="space-y-3 w-full">`;

            Object.keys(multipleDefinitions).forEach(type => {
                const f = filters[type] || { min: 0, max: 6 };
                const color = multipleColors[type];
                const numbersHtml = multipleDefinitions[type].map(n => {
                    const isEx = this.state.basket.excluded.includes(n);
                    const isFi = this.state.basket.fixed.includes(n);
                    let ballClass = "flex-shrink-0 flex items-center justify-center rounded-full font-black text-white shadow-sm ";
                    let style = `width:30px;height:30px;font-size:11px;background-color:${color};border:1px solid transparent;`;

                    if (isFi) {
                        ballClass += "ball-fixed";
                        style = "width:30px;height:30px;font-size:11px;background-color:#2563eb;border:2px solid #3b82f6;";
                    } else if (isEx) {
                        ballClass += "ball-excluded";
                        style = "width:30px;height:30px;font-size:11px;background-color:#94a3b8;border:1px solid #64748b;";
                    }

                    return `<span class="${ballClass}" style="${style}">${String(n).padStart(2, '0')}</span>`;
                }).join('');

                const gapClass = 'gap-1.5';

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
                        <div class="flex items-center gap-2 shrink-0 ml-4">
                            <input type="number" min="0" max="6" value="${f.min}"
                                oninput="FilterDashboard.updateMultipleFilter('${def.id}', '${type}', 'min', this.value)"
                                class="w-14 h-8 text-center text-sm font-bold text-gray-900 border-0 border-b-2 border-gray-200 focus:border-blue-500 focus:outline-none focus:ring-0 bg-transparent">
                            <span class="text-xs text-gray-400">~</span>
                            <input type="number" min="0" max="6" value="${f.max}"
                                oninput="FilterDashboard.updateMultipleFilter('${def.id}', '${type}', 'max', this.value)"
                                class="w-14 h-8 text-center text-sm font-bold text-gray-900 border-0 border-b-2 border-gray-200 focus:border-blue-500 focus:outline-none focus:ring-0 bg-transparent">
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
                    let ballClass = "ball flex-shrink-0 flex items-center justify-center rounded-full font-black text-white shadow-sm ";
                    let inlineStyle = `width:30px !important;height:30px !important;font-size:11px !important;background-color:${gungColors[type]} !important;`;

                    if (isFi) {
                        ballClass += "ball-fixed";
                        inlineStyle = "width:30px !important;height:30px !important;font-size:11px !important;background-color:#2563eb !important;border:2px solid #3b82f6 !important;";
                    } else if (isEx) {
                        ballClass += "ball-excluded";
                        inlineStyle = "width:30px !important;height:30px !important;font-size:11px !important;background-color:#94a3b8 !important;border:1px solid #64748b !important;";
                    }

                    return `<span class="${ballClass}" style="${inlineStyle}">${String(n).padStart(2, '0')}</span>`;
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
                        <div class="flex items-center gap-2 shrink-0 ml-2">
                            <input type="number" min="0" max="6" value="${f.min}"
                                oninput="FilterDashboard.updateMagicSquareFilter('${def.id}', '${type}', 'min', this.value)"
                                class="w-14 h-8 text-center text-sm font-bold text-gray-900 border-0 border-b-2 border-gray-200 focus:border-blue-500 focus:outline-none focus:ring-0 bg-transparent">
                            <span class="text-xs text-gray-400">~</span>
                            <input type="number" min="0" max="6" value="${f.max}"
                                oninput="FilterDashboard.updateMagicSquareFilter('${def.id}', '${type}', 'max', this.value)"
                                class="w-14 h-8 text-center text-sm font-bold text-gray-900 border-0 border-b-2 border-gray-200 focus:border-blue-500 focus:outline-none focus:ring-0 bg-transparent">
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
                    let ballClass = "ball flex-shrink-0 flex items-center justify-center rounded-full font-black text-white shadow-sm ";
                    const color = paperColors[type] || '#94a3b8';
                    let inlineStyle = `width:30px !important;height:30px !important;font-size:11px !important;background-color:${color} !important;`;
                    if (isFi) { ballClass += "ball-fixed"; inlineStyle = "width:30px !important;height:30px !important;font-size:11px !important;background-color:#2563eb !important;border:2px solid #3b82f6 !important;"; }
                    else if (isEx) { ballClass += "ball-excluded"; inlineStyle = "width:30px !important;height:30px !important;font-size:11px !important;background-color:#94a3b8 !important;border:1px solid #64748b !important;"; }
                    return `<span class="${ballClass}" style="${inlineStyle}">${String(n).padStart(2, '0')}</span>`;
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
                        <div class="flex items-center gap-2 shrink-0 ml-2">
                            <input type="number" min="0" max="6" value="${f.min}"
                                onchange="FilterDashboard.updateLottoPaperFilter('${def.id}', '${type}', 'min', this.value)"
                                class="w-14 h-8 text-center text-sm font-bold text-gray-900 border-0 border-b-2 border-gray-200 focus:border-blue-500 focus:outline-none focus:ring-0 bg-transparent">
                            <span class="text-xs text-gray-400">~</span>
                            <input type="number" min="0" max="6" value="${f.max}"
                                onchange="FilterDashboard.updateLottoPaperFilter('${def.id}', '${type}', 'max', this.value)"
                                class="w-14 h-8 text-center text-sm font-bold text-gray-900 border-0 border-b-2 border-gray-200 focus:border-blue-500 focus:outline-none focus:ring-0 bg-transparent">
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

            // 공 렌더 헬퍼 (번호대별 색상)
            const ballColor = n => {
                if (n <= 10) return '#F97316';
                if (n <= 20) return '#38BDF8';
                if (n <= 30) return '#EF4444';
                if (n <= 40) return '#6B7280';
                return '#84CC16';
            };
            const renderBallsList = (nums) => nums.map(n => {
                const isEx = this.state.basket.excluded.includes(n);
                const isFi = this.state.basket.fixed.includes(n);
                let ballClass = "ball flex-shrink-0 flex items-center justify-center rounded-full font-black text-white shadow-sm";
                let style = `width:30px !important;height:30px !important;font-size:11px !important;background-color:${ballColor(n)} !important;`;
                if (isFi) { ballClass += " ball-fixed"; style = 'width:30px !important;height:30px !important;font-size:11px !important;background-color:#2563eb !important;border:2px solid #3b82f6 !important;'; }
                else if (isEx) { ballClass += " ball-excluded"; style = 'width:30px !important;height:30px !important;font-size:11px !important;background-color:#94a3b8 !important;border:1px solid #64748b !important;'; }
                return `<span class="${ballClass}" style="${style}">${String(n).padStart(2, '0')}</span>`;
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
                            <div class="flex items-center gap-2 ">
                                <input type="number" min="0" max="6" value="${row.values[0]}"
                                    onchange="FilterDashboard.updateHotColdFilter('${def.id}', '${row.field}', 0, this.value)"
                                    class="w-14 h-8 text-center text-sm font-bold text-gray-900 border-0 border-b-2 border-gray-200 focus:border-blue-500 focus:outline-none focus:ring-0 bg-transparent">
                                <span class="text-xs text-gray-400">~</span>
                                <input type="number" min="0" max="6" value="${row.values[1]}"
                                    onchange="FilterDashboard.updateHotColdFilter('${def.id}', '${row.field}', 1, this.value)"
                                    class="w-14 h-8 text-center text-sm font-bold text-gray-900 border-0 border-b-2 border-gray-200 focus:border-blue-500 focus:outline-none focus:ring-0 bg-transparent">
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

            // 번호대별 색상
            const ballColor = n => {
                if (n <= 10) return '#F97316';
                if (n <= 20) return '#38BDF8';
                if (n <= 30) return '#EF4444';
                if (n <= 40) return '#6B7280';
                return '#84CC16';
            };
            const renderMissBalls = nums => nums.map(n => {
                const isEx = this.state.basket?.excluded?.includes(n);
                const isFi = this.state.basket?.fixed?.includes(n);
                let ballClass = "ball flex-shrink-0 flex items-center justify-center rounded-full font-black text-white shadow-sm";
                let style = `width:30px !important;height:30px !important;font-size:11px !important;background-color:${ballColor(n)} !important;`;
                if (isFi) { ballClass += " ball-fixed"; style = 'width:30px !important;height:30px !important;font-size:11px !important;background-color:#2563eb !important;border:2px solid #3b82f6 !important;'; }
                else if (isEx) { ballClass += " ball-excluded"; style = 'width:30px !important;height:30px !important;font-size:11px !important;background-color:#94a3b8 !important;border:1px solid #64748b !important;'; }
                return `<span class="${ballClass}" style="${style}">${String(n).padStart(2, '0')}</span>`;
            }).join('');

            const groupDefs = [
                { id: 1, label: '1-5\ud68c (\ucd5c\uadfc)', color: '#E64A19', bgColor: '#FFF3EF', minKey: 'r1Min', maxKey: 'r1Max' },
                { id: 2, label: '6-10\ud68c (\uc911\uac04)', color: '#4B5563', bgColor: '#F9FAFB', minKey: 'r2Min', maxKey: 'r2Max' },
                { id: 3, label: '11-15\ud68c (\uc7a5\uae30)', color: '#16A34A', bgColor: '#F0FDF4', minKey: 'r3Min', maxKey: 'r3Max' },
                { id: 4, label: '16+\ud68c (\uadf9\uc7a5\uae30)', color: '#1A6DFF', bgColor: '#EFF6FF', minKey: 'r4Min', maxKey: 'r4Max' }
            ];


            html += `<div class="flex flex-col gap-3">`;
            groupDefs.forEach(g => {
                const nums = groupNums[g.id] || [];
                // [fix-411] 그룹 사이즈로 max 클램프 + 안내 — 다음 회차 출현 가능 카운트는 그룹 사이즈를 못 넘음
                const cap = Math.min(6, nums.length);
                const rawMin = ranges[g.minKey] ?? 0;
                const rawMax = ranges[g.maxKey] ?? 6;
                const minVal = Math.min(rawMin, cap);
                const maxVal = Math.min(rawMax, cap);
                html += `
                    <div class="flex flex-col gap-2 p-3 rounded-xl border" style="background-color:${g.bgColor}; border-color:${g.color}33;">
                        <div class="flex items-center justify-between">
                            <span class="text-xs font-black shrink-0" style="color:${g.color}">${g.label} <span class="text-[11px] font-black opacity-60">(${nums.length}개)</span></span>
                            <div class="flex items-center gap-1">
                                <div class="flex items-center gap-2">
                                    <input type="number" min="0" max="${cap}" value="${minVal}"
                                        oninput="FilterDashboard.updateMissingPeriodFilter('${def.id}', '${g.minKey}', this.value, ${cap})"
                                        class="w-14 h-8 text-center text-sm font-bold text-gray-900 border-0 border-b-2 border-gray-200 focus:border-blue-500 focus:outline-none focus:ring-0 bg-transparent">
                                    <span class="text-xs text-gray-400">~</span>
                                    <input type="number" min="0" max="${cap}" value="${maxVal}"
                                        oninput="FilterDashboard.updateMissingPeriodFilter('${def.id}', '${g.maxKey}', this.value, ${cap})"
                                        class="w-14 h-8 text-center text-sm font-bold text-gray-900 border-0 border-b-2 border-gray-200 focus:border-blue-500 focus:outline-none focus:ring-0 bg-transparent">
                                </div>
                                <span class="text-[10px] text-gray-400 ml-2" title="다음 회차에 이 그룹에서 가능한 최대 카운트">max ${cap}</span>
                            </div>
                        </div>
                        <div class="flex flex-wrap gap-1 pt-1 border-t" style="border-color:${g.color}22;">
                            ${renderMissBalls(nums)}
                        </div>
                    </div>`;
            });
            html += `</div>`;



        } else if (key === 'missing_custom_filter') {
            const savedFilters = (vals.filters || []).filter(f => f.numbers && f.numbers.length > 0);
            if (savedFilters.length === 0) {
                html += `<div class="text-center py-3 text-slate-400 text-xs">
                    <span class="material-symbols-outlined text-2xl block mb-1">group_work</span>
                    미출현 커스텀 그룹이 없습니다.<br>
                    <a href="missing.html" class="text-blue-500 font-black hover:underline mt-1 inline-block">미출현 페이지에서 그룹 추가 →</a>
                </div>`;
            } else {
                // [수정] renderBalls() 기준 색상으로 통일
                const ballColor = n => n <= 10 ? '#F7C948' : n <= 20 ? '#4a90d9' : n <= 30 ? '#E04A4A' : n <= 40 ? '#6B7280' : '#48B05A';
                html += `<div class="flex flex-col gap-2.5">`;
                savedFilters.forEach(f => {
                    const isEnabled = f.enabled || false;
                    const nums = [...new Set(f.numbers || [])].sort((a, b) => a - b);
                    const mn = f.minCount ?? 0;
                    const mx = f.maxCount ?? 0;
                    html += `
                    <div class="flex flex-col gap-2 p-3 rounded-xl border ${isEnabled ? 'border-blue-300 bg-blue-50/30' : 'border-slate-200 bg-white opacity-60'}">
                        <div class="flex items-center justify-between gap-2">
                            <span class="text-xs font-black text-slate-700 flex-1 min-w-0 truncate">${f.name || '미출현그룹'}</span>
                                <div class="flex items-center gap-2 bg-white border border-slate-200 rounded-xl px-2 py-1 shadow-sm focus-within:ring-2 focus-within:ring-blue-500 shrink-0 ml-auto">
                                <input type="number" min="0" max="6" value="${mn}"
                                    oninput="FilterDashboard.updateMissingCustomMinMax('${def.id}', '${f.id}', 'min', this.value)"
                                    class="w-11 text-center text-[13px] font-black text-blue-600 bg-transparent border-none p-0 focus:ring-0">
                                <span class="text-slate-300 font-bold text-xs">~</span>
                                <input type="number" min="0" max="6" value="${mx}"
                                    oninput="FilterDashboard.updateMissingCustomMinMax('${def.id}', '${f.id}', 'max', this.value)"
                                    class="w-11 text-center text-[13px] font-black text-blue-600 bg-transparent border-none p-0 focus:ring-0">
                            </div>
                        </div>
                        <div class="flex flex-wrap gap-1 pt-1.5 border-t border-slate-100">
                            ${nums.map(n => {
                        const isEx = this.state.basket?.excluded?.includes(n);
                        const isFi = this.state.basket?.fixed?.includes(n);
                        let ballClass = "w-7 h-7 rounded-full flex items-center justify-center text-[11px] font-black text-white";
                        let style = `background-color:${ballColor(n)};`;
                        if (isFi) { ballClass += " ball-fixed"; style = "background-color:#2563eb; border-color:#3b82f6;"; }
                        else if (isEx) { ballClass += " ball-excluded"; style = "background-color:#94a3b8; border-color:#64748b;"; }
                        return `<span class="${ballClass}" style="${style}">${String(n).padStart(2, '0')}</span>`;
                    }).join('')}
                        </div>
                    </div>`;
                });
                html += `</div>`;
            } // end else (hasGroups)
        } else if (key === 'tail_digit_patterns') {
            // [2026-05-14 표준] tail_digit_patterns.settings.filters 단일 진실 사용
            // 이전: end_digit_0~9_count 10개 유령 키 참조 → DB 삭제 후 데이터 0건 → UI 빈 값 표시
            const digitFilters = {};
            const tdFilters = (vals && vals.filters) || {};
            for (let i = 0; i <= 9; i++) {
                const f = tdFilters[i] || tdFilters[String(i)];
                if (f && f.min !== undefined && f.max !== undefined) {
                    digitFilters[i] = { min: f.min, max: f.max };
                }
            }

            const getBallColorClass = n => {
                if (n <= 10) return 'ball-y';
                if (n <= 20) return 'ball-b';
                if (n <= 30) return 'ball-r';
                if (n <= 40) return 'ball-g';
                return 'ball-gr';
            };

            html += `<div class="space-y-0">`;

            // [fix-296] 끝수별 실제 가능 max (10/20/30/40 → 4개, 1/11/21/31/41 → 5개 등)
            const TAIL_REAL_MAX = { 0: 4, 1: 5, 2: 5, 3: 5, 4: 5, 5: 5, 6: 4, 7: 4, 8: 4, 9: 4 };

            for (let i = 0; i < 10; i++) {
                const realMax = TAIL_REAL_MAX[i];
                const f = digitFilters[i] || { min: 0, max: realMax };
                const digitDefId = digitFilters[i]?._defId;
                const tailTargets = [];
                for (let n = 1; n <= 45; n++) if (n % 10 === i) tailTargets.push(n);

                const ballHtml = tailTargets.map(n => {
                    const isEx = this.state.basket.excluded.includes(n);
                    const isFi = this.state.basket.fixed.includes(n);
                    let ballClass = "flex-shrink-0 flex items-center justify-center rounded-full font-black text-white shadow-sm ";
                    let style = `width:30px;height:30px;font-size:11px;border:1px solid transparent;`;

                    if (isFi) {
                        ballClass += "ball-fixed";
                        style = "width:30px;height:30px;font-size:11px;background-color:#2563eb;border:2px solid #3b82f6;";
                    } else if (isEx) {
                        ballClass += "ball-excluded";
                        style = "width:30px;height:30px;font-size:11px;background-color:#94a3b8;border:1px solid #64748b;";
                    } else {
                        ballClass += getBallColorClass(n);
                    }
                    return `<span class="${ballClass}" style="${style}">${String(n).padStart(2, '0')}</span>`;
                }).join('');

                html += `
                    <div class="flex items-center justify-between border-b border-slate-100 pb-3 last:border-0 w-full mb-2">
                        <div class="flex-1">
                            <div class="flex items-center gap-2 mb-1.5">
                                <span class="text-xs font-bold text-slate-700 w-16">${i}끝</span>
                            </div>
                            <div class="flex flex-wrap gap-1.5">
                                ${ballHtml}
                            </div>
                        </div>
                        <div class="flex items-center gap-2 shrink-0 ml-4">
                            <input type="number" min="0" max="${realMax}" value="${f.min}"
                                oninput="FilterDashboard.updateTailDigitFilter('${digitDefId || def.id}', ${i}, 'min', this.value)"
                                class="w-14 h-8 text-center text-sm font-bold text-gray-900 border-0 border-b-2 border-gray-200 focus:border-blue-500 focus:outline-none focus:ring-0 bg-transparent">
                            <span class="text-xs text-gray-400">~</span>
                            <input type="number" min="0" max="${realMax}" value="${f.max}"
                                oninput="FilterDashboard.updateTailDigitFilter('${digitDefId || def.id}', ${i}, 'max', this.value)"
                                class="w-14 h-8 text-center text-sm font-bold text-gray-900 border-0 border-b-2 border-gray-200 focus:border-blue-500 focus:outline-none focus:ring-0 bg-transparent">
                        </div>
                    </div>`;
            }

            html += `</div>`;
        } else if (key === 'consecutive_count') {
            const selectedCounts = vals.selectedCounts || [];
            const runFilters = vals.runFilters || { run3: false, run4: false, run5: false, run6: false };

            let btns = '';
            for (let i = 0; i <= 5; i++) {
                const isActive = selectedCounts.includes(i);
                const bg = isActive ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-slate-400 border-slate-200 hover:bg-slate-50';
                btns += `<button onclick="FilterDashboard.toggleDiscreteValue('${def.id}', 'selectedCounts', ${i})" class="flex-1 py-1.5 text-center rounded-lg border text-[10px] font-black transition-colors ${bg}">${i}</button>`;
            }

            html += `
                <div class="flex gap-1 mb-4">${btns}</div>
                <div class="flex flex-wrap items-center gap-10">
                    <label class="flex items-center gap-1.5 cursor-pointer hover:bg-slate-50 p-1 rounded transition-colors">
                        <input type="checkbox" ${runFilters.run3 ? 'checked' : ''} 
                            onchange="FilterDashboard.toggleRunFilter('${def.id}', 'run3', this.checked)"
                            class="w-3.5 h-3.5 text-blue-600 rounded border-gray-300 focus:ring-0">
                        <span class="text-[11px] font-bold text-slate-600">2연번(3수)</span>
                    </label>
                    <label class="flex items-center gap-1.5 cursor-pointer hover:bg-slate-50 p-1 rounded transition-colors">
                        <input type="checkbox" ${runFilters.run4 ? 'checked' : ''} 
                            onchange="FilterDashboard.toggleRunFilter('${def.id}', 'run4', this.checked)"
                            class="w-3.5 h-3.5 text-blue-600 rounded border-gray-300 focus:ring-0">
                        <span class="text-[11px] font-bold text-slate-600">3연번(4수)</span>
                    </label>
                    <label class="flex items-center gap-1.5 cursor-pointer hover:bg-slate-50 p-1 rounded transition-colors">
                        <input type="checkbox" ${runFilters.run5 ? 'checked' : ''} 
                            onchange="FilterDashboard.toggleRunFilter('${def.id}', 'run5', this.checked)"
                            class="w-3.5 h-3.5 text-blue-600 rounded border-gray-300 focus:ring-0">
                        <span class="text-[11px] font-bold text-slate-600">4연번(5수)</span>
                    </label>
                    <label class="flex items-center gap-1.5 cursor-pointer hover:bg-slate-50 p-1 rounded transition-colors">
                        <input type="checkbox" ${runFilters.run6 ? 'checked' : ''} 
                            onchange="FilterDashboard.toggleRunFilter('${def.id}', 'run6', this.checked)"
                            class="w-3.5 h-3.5 text-blue-600 rounded border-gray-300 focus:ring-0">
                        <span class="text-[11px] font-bold text-slate-600">5연번(6수)</span>
                    </label>
                </div>`;
        } else {
            // composite_count / prime_number_patterns은 항상 selectedCounts 사용 (분석페이지 저장 필드 통일)
            const activeArrName = (key === 'composite_count' || key === 'prime_number_patterns')
                ? 'selectedCounts'
                : (vals.activeCounts ? 'activeCounts' : (vals.selectedCounts ? 'selectedCounts' : 'selectedValues'));
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
                const bg = isActive ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-slate-400 border-slate-200 hover:bg-slate-50';
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
                            class="inline-flex items-center gap-1 px-2.5 py-1 bg-blue-600 text-white rounded-full text-[10px] font-black shadow-md hover:bg-blue-700 transition-colors"
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

        const targetKeys = ['total_sum', 'tail_sum', 'ac_value', 'odd_even_pattern', 'high_low_pattern', 'consecutive_count', 'neighbor_number_patterns', 'carryover_count', 'prime_number_patterns', 'composite_count', 'triangular_number_patterns', 'square_number_patterns', 'twin_number_patterns', 'tail_digit_patterns', 'multiple_3_count', 'number_range_patterns', 'magic_square_pattern', 'lotto_paper_pattern', 'hot_cold_5', 'hot_cold_10', 'hot_cold_15', 'hot_cold_20', 'missing_period', 'missing_custom_filter'];
        const orderedFilters = targetKeys.map(key => this.state.foundationFilters.find(def => def.filter_key === key)).filter(Boolean);

        orderedFilters.forEach(def => {
            const userSet = this.state.userSettings[def.id] || { enabled: false, settings: {} };

            const isMissingCustom = def.filter_key === 'missing_custom_filter';
            const hasGroups = isMissingCustom
                ? (userSet.settings?.filters || []).some(f => f.numbers && f.numbers.length > 0)
                : true;
            // missing_custom_filter는 그룹이 없어도 카드 표시 (편집 링크 노출)

            if (userSet.enabled && hasGroups) activeCount++;

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
            if (def.filter_key === 'missing_custom_filter') {
                const _mcGroups = (userSet.settings?.filters || []).filter(f => f.numbers && f.numbers.length > 0);
                if (_mcGroups.length === 1 && _mcGroups[0].name) {
                    displayName = _mcGroups[0].name; // 그룹 1개면 그 이름 사용
                } else if (_mcGroups.length > 1) {
                    displayName = `미출현 커스텀 (${_mcGroups.length}개)`;
                } else {
                    displayName = '미출현 커스텀';
                }
            }

            // [수정] 전문적이고 대조가 뚜렷한(Bolder) 카드 테마
            const isActive = userSet.enabled;
            const themeClass = isActive
                ? 'bg-white shadow-md ring-1 ring-slate-900/5 border-l-4 border-l-indigo-500 scale-[1.01]'
                : 'bg-slate-50/50 border border-slate-200/60 opacity-80 hover:opacity-100 hover:border-slate-300';
            const titleColor = isActive ? 'text-slate-900' : 'text-slate-500';
            const toggleColor = isActive ? 'peer-checked:bg-indigo-600' : 'peer-checked:bg-indigo-600';
            const editIconColor = isActive ? 'group-hover:text-indigo-600 text-slate-400' : 'group-hover:text-slate-600 text-slate-300';

            // [수정] 끝수부터 미출현 커스텀 필터까지 동일한 크기로 맞추기 위한 로직
            const complexKeys = ['number_range_patterns', 'magic_square_pattern', 'lotto_paper_pattern', 'hot_cold_5', 'hot_cold_10', 'hot_cold_15', 'hot_cold_20', 'missing_period', 'missing_custom_filter'];
            const isComplex = complexKeys.includes(def.filter_key);
            const ctrlContainerClass = isComplex ? 'h-[360px] overflow-y-auto custom-scrollbar pr-2' : '';

            html += `
            <div id="filter-${def.filter_key}" class="rounded-2xl p-6 transition-all duration-300 relative w-full flex flex-col ${themeClass}">
                <div class="flex items-center justify-between mb-3 border-b border-slate-100 pb-3">
                    <a href="${this.getFilterLink(def.filter_key)}" class="group flex items-center gap-2 cursor-pointer">
                        <h3 class="text-[17px] font-black tracking-tight ${titleColor} group-hover:underline decoration-indigo-300 underline-offset-4">${displayName}</h3>
                        <span class="material-symbols-outlined text-[16px] ${editIconColor} transition-colors">edit_square</span>
                    </a>
                    <div class="flex items-center gap-2">
                        <span id="indep-count-${def.filter_key}" class="hidden text-[11px] text-blue-500 ml-2 font-medium"></span>
                        ${def.filter_key !== 'missing_custom_filter' ? `<button onclick="FilterDashboard.toggleRecent10Filter('${def.id}')"
                            title="최근 10회차 필터 자동 설정 (클릭 시 토글)"
                            class="px-2 py-0.5 text-[9px] font-black rounded-md border transition-colors ${userSet.settings?.recent10FilterActive ? 'bg-blue-600 border-blue-600 text-white' : 'bg-white border-slate-200 text-slate-400 hover:border-blue-400 hover:text-blue-500'}">
                            최근10</button>` : ''}
                        <button onclick="FilterDashboard.loadDataFromDB().then(()=>FilterDashboard.renderUI())"
                            title="데이터 수동 동기화"
                            class="p-1 text-slate-300 hover:text-blue-500 transition-colors">
                            <span class="material-symbols-outlined text-[18px]">sync</span>
                        </button>
                        <label class="relative inline-flex items-center cursor-pointer">
                            <input type="checkbox" class="sr-only peer" ${userSet.enabled ? 'checked' : ''} onchange="FilterDashboard.toggleSetting('${def.id}', this.checked)">
                            <div class="w-10 h-5 bg-slate-200 rounded-full peer peer-checked:after:translate-x-full after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border after:rounded-full after:h-4 after:w-4 transition-all peer-checked:bg-blue-600"></div>
                        </label>
                    </div>
                </div>
                <!-- [수정] 스크롤 영역 적용 -->
                <div id="filter-ctrl-${def.filter_key}" class="flex-1 ${ctrlContainerClass}">${this.buildFilterControl(def, userSet)}</div>
            </div>`;
        });
        container.innerHTML = html;
        document.getElementById('foundationActiveCount').textContent = `${activeCount}개 적용중`;
        if (this.state.totalActiveCount !== undefined) this.state.totalActiveCount += activeCount;
        // 배지 복원: renderUI 재실행 시 hidden 초기화되므로 캐시된 값으로 복원
        if (window.applyIndepCountBadges) window.applyIndepCountBadges();
    },

    /**
     * 단일 필터 카드 컨트롤 영역만 업데이트 (성능 최적화)
     * toggleDiscreteValue / toggleRunFilter 등 내부 값 변경 시 사용
     */
    _renderOneCardCtrl(id) {
        const def = this.state.foundationFilters.find(d => d.id === id);
        if (!def) return this.renderFoundationFilters();
        const ctrlEl = document.getElementById(`filter-ctrl-${def.filter_key}`);
        if (!ctrlEl) return this.renderFoundationFilters();
        const userSet = this.state.userSettings[def.id] || { enabled: false, settings: {} };
        ctrlEl.innerHTML = this.buildFilterControl(def, userSet);
        // 최근10 배지 업데이트
        const badgeEl = ctrlEl.closest(`[id="filter-${def.filter_key}"]`)
            ?.querySelector(`button[onclick*="toggleRecent10Filter"]`);
        if (badgeEl) {
            const r10Active = userSet.settings?.recent10FilterActive;
            badgeEl.className = `px-2 py-0.5 text-[9px] font-black rounded-md border transition-colors ${r10Active
                ? 'bg-blue-600 border-blue-600 text-white'
                : 'bg-white border-slate-200 text-slate-400 hover:border-blue-400 hover:text-blue-500'}`;
        }
    },

    /**
     * 단일 필터 카드 전체(헤더+컨트롤) 업데이트 (toggleSetting 등 enabled 상태 변경 시)
     */
    _renderOneCard(id) {
        const def = this.state.foundationFilters.find(d => d.id === id);
        if (!def) return this.renderFoundationFilters();
        const cardEl = document.getElementById(`filter-${def.filter_key}`);
        if (!cardEl) return this.renderFoundationFilters();
        const userSet = this.state.userSettings[def.id] || { enabled: false, settings: {} };

        const isCarryover = def.filter_key === 'carryover_count';
        let displayName = def.filter_name.replace(' 패턴', '').replace('패턴', '').replace(' 개수', '').replace('개수', '').replace('(전체)', '').replace('(당번)', '').trim();
        const nameMap = {
            odd_even_pattern: '홀짝', tail_digit_patterns: '끝수', multiple_3_count: '배수',
            high_low_pattern: '저고', prime_number_patterns: '소수', composite_count: '합성수',
            twin_number_patterns: '동형수', square_number_patterns: '제곱수', triangular_number_patterns: '삼각수',
            magic_square_pattern: '9궁', lotto_paper_pattern: '로또용지', hot_cold_5: '핫/콜드 5회',
            hot_cold_10: '핫/콜드 10회', hot_cold_15: '핫/콜드 15회', hot_cold_20: '핫/콜드 20회', missing_period: '미출현 그룹'
        };
        if (nameMap[def.filter_key]) displayName = nameMap[def.filter_key];

        // [수정] 전문적이고 대조가 뚜렷한(Bolder) 카드 테마
        const isActive = userSet.enabled;
        const themeClass = isActive
            ? 'bg-white shadow-md ring-1 ring-slate-900/5 border-l-4 border-l-indigo-500 scale-[1.01]'
            : 'bg-slate-50/50 border border-slate-200/60 opacity-80 hover:opacity-100 hover:border-slate-300';
        const titleColor = isActive ? 'text-slate-900' : 'text-slate-500';
        const toggleColor = isActive ? 'peer-checked:bg-indigo-600' : 'peer-checked:bg-indigo-600';
        const editIconColor = isActive ? 'group-hover:text-indigo-600 text-slate-400' : 'group-hover:text-slate-600 text-slate-300';

        // [수정] 끝수부터 미출현 커스텀 필터까지 동일한 크기로 맞추기 위한 로직
        const complexKeys = ['tail_digit_patterns', 'multiple_3_count', 'number_range_patterns', 'magic_square_pattern', 'lotto_paper_pattern', 'hot_cold_5', 'hot_cold_10', 'hot_cold_15', 'hot_cold_20', 'missing_period', 'missing_custom_filter'];
        const isComplex = complexKeys.includes(def.filter_key);
        const ctrlContainerClass = isComplex ? 'h-[360px] overflow-y-auto custom-scrollbar pr-2' : '';

        const newHtml = `
            <div class="flex items-center justify-between mb-3 border-b border-slate-100 pb-3">
                <a href="${this.getFilterLink(def.filter_key)}" class="group flex items-center gap-2 cursor-pointer">
                    <h3 class="text-[17px] font-black tracking-tight ${titleColor} group-hover:underline decoration-indigo-300 underline-offset-4">${displayName}</h3>
                    <span class="material-symbols-outlined text-[16px] ${editIconColor} transition-colors">edit_square</span>
                </a>
                <div class="flex items-center gap-2">
                    <span id="indep-count-${def.filter_key}" class="hidden text-[11px] text-indigo-500 ml-2 font-black tracking-wide bg-indigo-50 px-2 py-0.5 rounded-md border border-indigo-100"></span>
                    ${def.filter_key !== 'missing_custom_filter' ? `<button onclick="FilterDashboard.toggleRecent10Filter('${def.id}')"
                        title="최근 10회차 필터 자동 설정 (클릭 시 토글)"
                        class="px-2 py-0.5 text-[9px] font-black rounded-md border transition-colors ${userSet.settings?.recent10FilterActive ? 'bg-blue-600 border-blue-600 text-white' : 'bg-white border-slate-200 text-slate-400 hover:border-blue-400 hover:text-blue-500'}">
                        최근10</button>` : ''}
                    <button onclick="FilterDashboard.loadDataFromDB().then(()=>FilterDashboard.renderUI())"
                        title="데이터 수동 동기화"
                        class="p-1 text-slate-300 hover:text-blue-500 transition-colors">
                        <span class="material-symbols-outlined text-[18px]">sync</span>
                    </button>
                    <label class="relative inline-flex items-center cursor-pointer">
                        <input type="checkbox" class="sr-only peer" ${userSet.enabled ? 'checked' : ''} onchange="FilterDashboard.toggleSetting('${def.id}', this.checked)">
                        <div class="w-10 h-5 bg-slate-200 rounded-full peer peer-checked:after:translate-x-full after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border after:rounded-full after:h-4 after:w-4 transition-all ${toggleColor}"></div>
                    </label>
                </div>
            </div>
            <!-- [수정] 스크롤 영역 적용 -->
            <div id="filter-ctrl-${def.filter_key}" class="flex-1 ${ctrlContainerClass}">${this.buildFilterControl(def, userSet)}</div>`;

        // 카드 border 클래스 등 통합 업데이트
        cardEl.className = `rounded-2xl p-6 transition-all duration-300 relative w-full flex flex-col ${themeClass}`;
        cardEl.innerHTML = newHtml;

        // 활성 카드 수 업데이트
        const activeCountEl = document.getElementById('foundationActiveCount');
        if (activeCountEl) {
            const activeCount = this.state.foundationFilters.filter(d => {
                const us = this.state.userSettings[d.id];
                return us && us.enabled;
            }).length;
            activeCountEl.textContent = `${activeCount}개 적용중`;
        }
        if (window.applyIndepCountBadges) window.applyIndepCountBadges();
    },

    // 🔥 핵심 변경점: 회귀 분석 렌더링 (입력창 추가 및 텍스트 수정)
    renderRegressionFilters() {
        const container = document.getElementById('regressionFilterGrid');
        if (!container) return;
        let html = '';
        let activeCount = 0;

        // ── GAP / STR / 특이사항 사전 계산 (캐시) ──
        const draws = this.state.allDraws || [];
        const drawsLen = draws.length;
        // allDraws[idx]?.numbers 빠른 접근용 (idx 기반 회귀 주기 계산)
        const _nums = (idx) => (idx >= 0 && idx < drawsLen) ? draws[idx].numbers : null;

        // 캐시 무효화: allDraws 길이가 바뀌었을 때만 재계산
        if (!this._regStatCache || this._regStatCache.len !== drawsLen) {
            const cache = {};
            for (let s = 2; s <= 200; s++) {
                // ── GAP: 최근 주기부터 연속 미출 카운트 ──
                let gap = 0;
                for (let k = 0; k < 30; k++) {
                    const cA = _nums(s - 1 + k * s); // (base - s) → (base - 2s) → ...
                    const cB = _nums(2 * s - 1 + k * s);
                    if (!cA || !cB) break;
                    if (cB.some(n => cA.includes(n))) break; // 출현 → gap 끝
                    gap++;
                }

                // ── STR: 최근 주기부터 연속 출현 카운트 ──
                let str = 0;
                for (let k = 0; k < 30; k++) {
                    const cA = _nums(s - 1 + k * s);
                    const cB = _nums(2 * s - 1 + k * s);
                    if (!cA || !cB) break;
                    if (cB.some(n => cA.includes(n))) str++;
                    else break;
                }

                // ── 특이사항: 대상번호 중 3회 이상 연속 출현 번호 ──
                const targetNums = _nums(s - 1) || [];
                const notable = [];
                for (const n of targetNums) {
                    const d2 = _nums(2 * s - 1);
                    if (!d2 || !d2.includes(n)) continue;
                    let consec = 2;
                    const d3 = _nums(3 * s - 1);
                    if (d3 && d3.includes(n)) {
                        consec = 3;
                        const d4 = _nums(4 * s - 1);
                        if (d4 && d4.includes(n)) {
                            consec = 4;
                            const d5 = _nums(5 * s - 1);
                            if (d5 && d5.includes(n)) consec = 5;
                        }
                    }
                    if (consec >= 3) notable.push({ num: n, count: consec });
                }

                cache[s] = { gap, str, notable };
            }
            this._regStatCache = { len: drawsLen, data: cache };
        }
        const regStats = this._regStatCache.data;

        for (let i = 2; i <= 200; i++) {
            const masterOn = this.state.regressionEnabled !== false;
            const rData = this.state.regressionSettings[i] || { enabled: false, min: 0, max: 3 };
            const isActuallyEnabled = masterOn && rData.enabled;
            if (isActuallyEnabled) activeCount++;

            const targetNums = draws[i - 1] ? draws[i - 1].numbers : [];
            const st = regStats[i] || { gap: 0, str: 0, notable: [] };

            // ── GAP/STR 합칙 열 (GAP 우선, 없으면 STR) ──
            let gapStrHtml = '';
            if (st.gap > 0) {
                const gCls = st.gap >= 4
                    ? 'text-rose-600 bg-rose-50 ring-1 ring-rose-200'
                    : 'text-amber-600 bg-amber-50 ring-1 ring-amber-200';
                gapStrHtml = `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-black ${gCls}">GAP ${st.gap}미출</span>`;
            } else if (st.str > 0) {
                const sCls = st.str >= 5
                    ? 'text-emerald-700 bg-emerald-100 ring-1 ring-emerald-300'
                    : 'text-emerald-600 bg-emerald-50 ring-1 ring-emerald-200';
                gapStrHtml = `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-black ${sCls}">STR ${st.str}연속</span>`;
            }

            // ── 특이사항 열 ──
            let notableHtml = '';
            if (st.notable.length > 0) {
                const parts = st.notable
                    .sort((a, b) => b.count - a.count)
                    .map(x => `<b>${x.num}번</b> ${x.count}회`)
                    .join(' · ');
                notableHtml = `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-black text-violet-600 bg-violet-50 ring-1 ring-violet-200"><span class="opacity-70">특이</span> ${parts}</span>`;
            }

            html += `
            <div id="regression-row-${i}" class="hover:bg-slate-50 ${isActuallyEnabled ? 'bg-emerald-50/30' : 'opacity-60 grayscale'}"
                 style="display:grid; grid-template-columns:120px 280px 120px 160px 1fr auto; align-items:center; column-gap:24px; padding:10px 16px; border-bottom:1px solid #f1f5f9;">
                <!-- ① 토글 + N회귀 -->
                <div style="display:flex; align-items:center; gap:8px;">
                    <label style="position:relative; display:inline-flex; align-items:center; cursor:pointer;">
                        <input type="checkbox" class="sr-only peer" ${isActuallyEnabled ? 'checked' : ''} onchange="FilterDashboard.toggleRegression(${i})">
                        <div class="w-10 h-5 bg-slate-200 rounded-full peer peer-checked:after:translate-x-full after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 transition-all peer-checked:bg-emerald-500"></div>
                    </label>
                    <a href="regression.html?step=${i}" class="text-sm font-black text-slate-800 hover:text-emerald-600" style="white-space:nowrap;">${i}회귀</a>
                </div>
                <!-- ② 대상번호 (280px 고정, 한 줄) -->
                <div style="display:flex; align-items:center; gap:2px; flex-wrap:nowrap;">
                    ${this.renderBalls(targetNums, [], [], 30)}
                </div>
                <!-- ③ GAP/STR (120px 고정) -->
                <div style="display:flex; justify-content:center;">${gapStrHtml}</div>
                <!-- ④ 특이사항 (160px 고정) -->
                <div style="display:flex; flex-wrap:wrap; gap:4px;">${notableHtml}</div>
                <!-- ⑤ AI 배지 (1fr 빈 공간) -->
                <div style="display:flex; align-items:center; gap:4px; flex-wrap:wrap;">
                    ${(() => {
                        const ar = this.state.aiRanges;
                        if (!ar) return '';
                        const badges = [];
                        const odd = [ar.odd_even_pattern_min, ar.odd_even_pattern_max];
                        if (odd[0] != null && odd[1] != null)
                            badges.push(`<span class="text-[10px] font-black bg-indigo-50 text-indigo-500 px-1.5 py-0.5 rounded-full ring-1 ring-indigo-200" style="white-space:nowrap;" title="AI 추천 홀수 범위">홀 ${odd[0]}~${odd[1]}</span>`);
                        const sum = [ar.total_sum_min, ar.total_sum_max];
                        if (sum[0] != null && sum[1] != null)
                            badges.push(`<span class="text-[10px] font-black bg-blue-50 text-blue-500 px-1.5 py-0.5 rounded-full ring-1 ring-blue-200" style="white-space:nowrap;" title="AI 추천 합계 범위">합 ${sum[0]}~${sum[1]}</span>`);
                        const ac = [ar.ac_value_min, ar.ac_value_max];
                        if (ac[0] != null && ac[1] != null)
                            badges.push(`<span class="text-[10px] font-black bg-violet-50 text-violet-500 px-1.5 py-0.5 rounded-full ring-1 ring-violet-200" style="white-space:nowrap;" title="AI 추천 AC값 범위">AC ${ac[0]}~${ac[1]}</span>`);
                        if (ar._round)
                            badges.push(`<span class="text-[10px] text-slate-400" style="white-space:nowrap;">${ar._round}회 기준</span>`);
                        return badges.join('');
                    })()}
                </div>
                <!-- ⑥ 조합카운팅 + min~max (우측 고정) -->
                <div style="display:flex; align-items:center; gap:8px;">
                    <span id="indep-count-regression_${i}" class="hidden text-[10px] font-black text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded-full" style="white-space:nowrap;"></span>
                    <div class="flex items-center gap-2 ">
                        <input type="number" id="reg-${i}-min" min="0" max="6" value="${Math.max(0, Math.min(6, rData.min))}"
                            oninput="FilterDashboard.updateRegressionRange(${i}, 'min', this.value)"
                            class="w-14 h-8 text-center text-sm font-bold text-gray-900 border-0 border-b-2 border-gray-200 focus:border-emerald-500 focus:outline-none focus:ring-0 bg-transparent">
                        <span class="text-xs text-gray-400">~</span>
                        <input type="number" id="reg-${i}-max" min="0" max="6" value="${Math.max(0, Math.min(6, rData.max))}"
                            oninput="FilterDashboard.updateRegressionRange(${i}, 'max', this.value)"
                            class="w-14 h-8 text-center text-sm font-bold text-gray-900 border-0 border-b-2 border-gray-200 focus:border-emerald-500 focus:outline-none focus:ring-0 bg-transparent">
                    </div>
                </div>
            </div>`;
        }
        container.innerHTML = html;
        document.getElementById('regressionActiveCount').textContent = `${activeCount}개 적용중`;
        if (this.state.totalActiveCount !== undefined) this.state.totalActiveCount += activeCount;
        if (window.applyIndepCountBadges) window.applyIndepCountBadges();
    },

    /**
     * [신규] LNB 순서 기준으로 state.customFilters 자체를 재정렬한다.
     * - storage 이벤트(LNB 드래그) 수신 시 호출 → renderCustomFilters() 이전에 state 자체 정렬 보장
     * - 필터 값 계산(updateNeonCounter / Combination Worker)도 같은 순서로 수행됨
     */
    _reorderCustomFiltersByLnb() {
        if (!this.state.customFilters || this.state.customFilters.length === 0) return;
        try {
            // layout.js와 동일한 user-specific 키 사용 (window._customMenuStorageKey 우선, fallback은 직접 계산)
            let storageKey = window._customMenuStorageKey;
            if (!storageKey) {
                const uid = window.filterService?.userId || localStorage.getItem('_lastLoginUserId') || null;
                storageKey = uid ? `lnbOrder_custom_${uid}` : 'lnbOrder_custom_guest';
            }
            const savedOrder = JSON.parse(localStorage.getItem(storageKey));
            if (!savedOrder || savedOrder.length === 0) return;
            this.state.customFilters.sort((a, b) => {
                const hA = `custom_analysis.html?id=${a.id}`;
                const hB = `custom_analysis.html?id=${b.id}`;
                const iA = savedOrder.indexOf(hA);
                const iB = savedOrder.indexOf(hB);
                if (iA !== -1 && iB !== -1) return iA - iB;
                if (iA !== -1) return -1;
                if (iB !== -1) return 1;
                return 0;
            });
        } catch (e) { /* ignore */ }
    },

    renderCustomFilters() {
        const container = document.getElementById('customFilterGrid');
        if (!container) return;
        let html = '';
        let activeCount = 0;

        // [수정] LNB 순서 기준 정렬 — layout.js와 동일한 lnbOrder_custom_<userId> 키 사용
        // (이전엔 lnbOrder_custom 단일 키로 잘못 매칭되어 절대 정렬되지 않던 버그 수정)
        let orderedFilters = [...this.state.customFilters];
        try {
            let storageKey = window._customMenuStorageKey;
            if (!storageKey) {
                const uid = window.filterService?.userId || localStorage.getItem('_lastLoginUserId') || null;
                storageKey = uid ? `lnbOrder_custom_${uid}` : 'lnbOrder_custom_guest';
            }
            const savedOrder = JSON.parse(localStorage.getItem(storageKey));
            if (savedOrder && savedOrder.length > 0) {
                orderedFilters.sort((a, b) => {
                    const hrefA = `custom_analysis.html?id=${a.id}`;
                    const hrefB = `custom_analysis.html?id=${b.id}`;
                    const idxA = savedOrder.indexOf(hrefA);
                    const idxB = savedOrder.indexOf(hrefB);
                    if (idxA !== -1 && idxB !== -1) return idxA - idxB;
                    if (idxA !== -1) return -1;
                    if (idxB !== -1) return 1;
                    return 0;
                });
            }
        } catch (e) { /* ignore */ }

        orderedFilters.forEach(custom => {
            try {
                let config = {};
                if (typeof custom.filter_config === 'string') {
                    try { config = JSON.parse(custom.filter_config || '{}'); } catch (e) { config = {}; }
                } else {
                    config = custom.filter_config || {};
                }

                let targetNums = [];
                try {
                    targetNums = this.calculateCustomTargets(custom);
                } catch (e) {
                    console.warn(`[Dashboard] Target calculation failed for: ${custom.title}`, e);
                }

                // 번호가 있어야 실제 "적용" 상태로 인정 (빈 필터는 enabled여도 미적용 처리)
                const isEffectivelyActive = config.enabled && targetNums.length > 0;
                if (isEffectivelyActive) activeCount++;

                let targetHtml = targetNums.length > 0
                    ? `<div class="mb-2 flex justify-between items-center"><span class="text-xs font-bold text-slate-500">대상번호</span><span class="text-[11px] font-black text-pink-600">${targetNums.length}개</span></div><div class="flex flex-wrap gap-1">${this.renderBalls(targetNums)}</div>`
                    : `<div class="text-[11px] font-bold text-slate-400 flex items-center justify-center py-2 bg-slate-100 rounded">타겟 생성 중/없음</div>`;

                html += `
                <div id="filter-card-${custom.id}" class="bg-white rounded-2xl border ${isEffectivelyActive ? 'border-pink-500 shadow-md ring-1 ring-pink-100' : 'border-slate-200 opacity-70'} p-5 transition-all">
                    <div class="flex items-start justify-between mb-3 gap-3">
                        <div class="flex items-center gap-2 flex-wrap min-w-0 flex-1">
                            <span class="px-2 py-0.5 rounded text-[10px] font-black bg-slate-100 text-slate-500 uppercase flex-shrink-0">${custom.type || '분석'}</span>
                            <!-- [fix-287] truncate w-48 제거 → 제목 전체 표시 (긴 제목은 wrap) -->
                            <a href="custom_analysis.html?id=${custom.id}" id="filter-title-link-${custom.id}" class="text-base font-black text-slate-800 break-keep leading-tight">${custom.title || '제목 없음'}</a>
                            <!-- [fix-291] 제목 인라인 편집 버튼 -->
                            <button onclick="event.preventDefault();event.stopPropagation();FilterDashboard.editCustomTitle('${custom.id}')"
                                title="제목 편집"
                                class="text-slate-400 hover:text-pink-600 transition-colors flex-shrink-0 -ml-1">
                                <span class="material-symbols-outlined" style="font-size:14px;line-height:1">edit</span>
                            </button>
                        </div>
                        <label class="relative inline-flex items-center cursor-pointer flex-shrink-0">
                            <input type="checkbox" class="sr-only peer" ${config.enabled ? 'checked' : ''} onchange="FilterDashboard.toggleCustom('${custom.id}', this.checked)">
                            <div class="w-10 h-5 bg-slate-200 rounded-full peer peer-checked:after:translate-x-full after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 transition-all peer-checked:bg-pink-600"></div>
                        </label>
                    </div>
                    <div class="p-3 bg-slate-50 border border-slate-100 rounded-xl mb-3">${targetHtml}</div>
                    <div class="flex items-center justify-end">
                        <span id="indep-count-custom_${custom.id}" class="hidden text-[10px] font-black text-pink-600 bg-pink-50 px-2 py-0.5 rounded-full whitespace-nowrap flex-shrink-0 mr-3"></span>
                        <div class="flex items-center gap-2 ">
                            <!-- [수정] 0~6 범위 제한 추가 및 회귀분석 스타일로 통일 -->
                            <input type="number" min="0" max="6" value="${config.values?.length > 0 ? Math.min(...config.values) : (config.min ?? 0)}"
                                oninput="FilterDashboard.updateCustomMinMax('${custom.id}', 'min', this.value)"
                                class="w-14 h-8 text-center text-sm font-bold text-gray-900 border-0 border-b-2 border-gray-200 focus:border-pink-500 focus:outline-none focus:ring-0 bg-transparent">
                            <span class="text-xs text-gray-400">~</span>
                            <input type="number" min="0" max="6" value="${config.values?.length > 0 ? Math.max(...config.values) : (config.max ?? 3)}"
                                oninput="FilterDashboard.updateCustomMinMax('${custom.id}', 'max', this.value)"
                                class="w-14 h-8 text-center text-sm font-bold text-gray-900 border-0 border-b-2 border-gray-200 focus:border-pink-500 focus:outline-none focus:ring-0 bg-transparent">
                        </div>
                    </div>
                </div>`;
            } catch (err) {
                console.error(`[Dashboard] Critical error rendering custom filter card:`, err, custom);
            }
        });
        container.innerHTML = html;
        if (document.getElementById('customActiveCount')) document.getElementById('customActiveCount').textContent = `${activeCount}개 적용중`;
        if (this.state.totalActiveCount !== undefined) this.state.totalActiveCount += activeCount;
        if (window.applyIndepCountBadges) window.applyIndepCountBadges();
    },

    /**
     * 대시보드 전용 저장 헬퍼 — 2026-05-14 양방향 동기화 fix v2
     *
     * 핵심 변경:
     *   - 이전: Utils.saveFilter(NULL 행, storage event) + saveSetting(회차별 행, DB-only)
     *           → 분석 페이지가 회차별 행 우선 로드하므로 storage event가 NULL 데이터로 발화돼 단방향 깨짐
     *   - v2 추가: 분석 페이지의 자동 재세팅(checkAndResetOnNewDraw 등)이 대시보드 변경을
     *             덮어쓰는 문제 fix — 모든 분석 페이지의 isManual 플래그 변형을 한번에 표시.
     */
    async _saveDashboardFilter(defKey, settings, enabled) {
        this._dashSelfSaving = true;
        try {
            const tr = this.state.targetRound;
            // 회차별 행 + localStorage + storage event 발화 (분석 페이지가 즉시 수신)
            if (window.Utils && window.Utils.saveFilter) {
                await window.Utils.saveFilter(defKey, settings, enabled, tr);
            } else if (window.filterService?.initialized) {
                await window.filterService.saveSetting(defKey, settings, enabled, tr);
            }
            // NULL 행 폴백 보존 (DB만)
            if (tr && window.filterService?.initialized) {
                try {
                    await window.filterService.saveSetting(defKey, settings, enabled, null);
                } catch (e) { /* 무시 */ }
            }
            // 분석 페이지 자동 재세팅 방지: 표준 키 → 페이지 isManual 키 매핑
            this._markPagesManual(defKey);
        } finally {
            this._dashSelfSaving = false;
        }
    },

    /**
     * 표준 filter_key에 매핑되는 각 분석 페이지의 isManual localStorage 플래그를 'true'로 설정.
     * checkAndResetOnNewDraw / autoApply*OnLoad 등 자동 재세팅 로직이 대시보드 변경을 덮어쓰는 사고 방지.
     */
    _markPagesManual(filter_key) {
        const MANUAL_KEY_MAP = {
            'ac_value':                  ['ac_value_is_manual'],
            'total_sum':                 ['total_sum_filter_isManual'],
            'tail_sum':                  ['tail_sum_filter_isManual'],
            'tail_digit_patterns':       ['tail_digit_filter_isManual'],
            'carryover_count':           ['carryover_filter_isManual'],
            'composite_count':           ['composite_number_is_manual'],
            'consecutive_count':         ['consecutive_number_is_manual', 'consecutive_filter_isManual'],
            'hot_cold_5':                ['hot_cold_filter_isManual'],
            'hot_cold_10':               ['hot_cold_filter_isManual'],
            'hot_cold_15':               ['hot_cold_filter_isManual'],
            'hot_cold_20':               ['hot_cold_filter_isManual'],
            'high_low_pattern':          ['low_high_is_manual'],
            'magic_square_pattern':      ['magic_square_filter_isManual'],
            'missing_period':            ['missing_period_is_manual'],
            'missing_custom_filter':     ['missing_period_is_manual'],
            'multiple_3_count':          ['multiple_period_is_manual'],
            'multiple_4_count':          ['multiple_period_is_manual'],
            'multiple_5_count':          ['multiple_period_is_manual'],
            'multiple_7_count':          ['multiple_period_is_manual'],
            'multiple_8_count':          ['multiple_period_is_manual'],
            'multiple_3_4_count':        ['multiple_period_is_manual'],
            'multiple_3_5_count':        ['multiple_period_is_manual'],
            'multiple_4_5_count':        ['multiple_period_is_manual'],
            'no_multiple_count':         ['multiple_period_is_manual'],
            'neighbor_number_patterns':  ['neighbor_number_period_is_manual'],
            'number_range_patterns':     ['number_range_period_is_manual'],
            'odd_even_pattern':          ['odd_even_is_manual'],
            'prime_number_patterns':     ['prime_number_patterns_isManual'],
            'regression_analysis':       ['regression_analysis_isManual'],
            'square_number_patterns':    ['square_number_patterns_isManual'],
            'twin_number_patterns':      ['twin_number_patterns_isManual'],
            'lotto_paper_pattern':       ['lotto_paper_filter_isManual'],
        };
        const keys = MANUAL_KEY_MAP[filter_key] || [];
        for (const k of keys) {
            try { localStorage.setItem(k, 'true'); } catch (_) { /* 무시 */ }
        }
    },

    async toggleSetting(id, isEnabled) {
        if (this.state.userSettings[id]) {
            this.state.userSettings[id].enabled = isEnabled;

            // [성능] 해당 카드 전체만 업데이트 (enabled 상태 변경 → border/header 색상 포함)
            this._renderOneCard(id);
            this.updateNeonCounter();

            const def = this.state.foundationFilters.find(d => d.id === id);
            if (def) {
                const settings = this.state.userSettings[id].settings || {};
                await this._saveDashboardFilter(def.filter_key, settings, isEnabled);
            }
        }
    },

    // 미출현 커스텀 그룹별 min/max 인라인 수정
    async updateMissingCustomMinMax(defId, groupId, type, rawVal) {
        const userSet = this.state.userSettings[defId];
        if (!userSet) return;
        const filters = userSet.settings.filters || [];
        const group = filters.find(f => String(f.id) === String(groupId));
        if (!group) return;

        const v = Math.max(0, Math.min(6, parseInt(rawVal) || 0));
        if (type === 'min') group.minCount = v;
        else group.maxCount = v;

        // 디바운스 저장 (400ms) — input 포커스 유지를 위해 renderFoundationFilters 호출 안 함
        if (this._mcSaveTimer) clearTimeout(this._mcSaveTimer);
        this._mcSaveTimer = setTimeout(async () => {
            const def = this.state.foundationFilters.find(d => d.id === defId);
            if (def) {
                await this._saveDashboardFilter(def.filter_key, userSet.settings, userSet.enabled);
            }
            this.updateNeonCounter();
        }, 400);
    },

    async updateFilterValue(id, type, value) {
        if (this.state.userSettings[id]) {
            // [수정] 합계 필터 등을 제외한 갯수 필터의 0~6 제한 적용 여부 결정
            const def = this.state.foundationFilters.find(d => d.id === id);
            const isCountFilter = def && (def.filter_key.includes('count') || def.filter_key.includes('number_patterns') || def.filter_key.includes('missing_period'));
            let val = parseInt(value);
            if (isCountFilter) val = Math.max(0, Math.min(6, val || 0));

            if (isNaN(val)) return;
            this.state.userSettings[id].settings[type] = val;

            // 최근10 활성 상태에서 수동 변경 → 즉시 비활성화 + UI 갱신
            if (this.state.userSettings[id].settings.recent10FilterActive) {
                this.state.userSettings[id].settings.recent10FilterActive = false;
                this.renderFoundationFilters(); // 버튼 · 인디고 배지 즉시 비활성화
            }

            if (this._saveTimer) clearTimeout(this._saveTimer);
            this._saveTimer = setTimeout(async () => {
                const def = this.state.foundationFilters.find(d => d.id === id);
                if (def) {
                    await this._saveDashboardFilter(def.filter_key, this.state.userSettings[id].settings, this.state.userSettings[id].enabled);
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
            this.state.userSettings[id].settings.recent10FilterActive = false; // 수동 변경 시 최근 10회차 버튼 비활성화

            // [성능] 해당 카드 컨트롤만 즉시 업데이트 (전체 재빌드 불필요)
            this._renderOneCardCtrl(id);
            this.updateNeonCounter();

            const def = this.state.foundationFilters.find(d => d.id === id);
            if (def) {
                await this._saveDashboardFilter(def.filter_key, this.state.userSettings[id].settings, this.state.userSettings[id].enabled);
            }
        }
    },

    async toggleRunFilter(id, runKey, isChecked) {
        if (this.state.userSettings[id]) {
            if (!this.state.userSettings[id].settings.runFilters) {
                this.state.userSettings[id].settings.runFilters = { run3: false, run4: false, run5: false, run6: false };
            }
            this.state.userSettings[id].settings.runFilters[runKey] = isChecked;
            // 수동 변경 시 최근 10회차 버튼 비활성화
            this.state.userSettings[id].settings.recent10FilterActive = false;

            // [성능] 해당 카드 컨트롤만 즉시 업데이트
            this._renderOneCardCtrl(id);
            this.updateNeonCounter();

            const def = this.state.foundationFilters.find(d => d.id === id);
            if (def) {
                // [2026-05-14] _saveDashboardFilter 사용 — targetRound + isManual 일괄 처리
                await this._saveDashboardFilter(def.filter_key, this.state.userSettings[id].settings, this.state.userSettings[id].enabled);
            }
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
            // [수정] 0~6 범위 제한
            userSet.settings.ranges[typeName][boundType] = Math.max(0, Math.min(6, parseInt(value) || 0));
        }

        userSet.settings.recent10FilterActive = false;

        const def = this.state.foundationFilters.find(f => f.id === id);
        if (def) {
            // [fix-318] _saveDashboardFilter — IS NULL + targetRound row 양쪽 저장 (분석페이지↔대시보드 sync)
            await this._saveDashboardFilter(def.filter_key, userSet.settings, userSet.enabled);
        }
        this.renderFoundationFilters();
        this.updateNeonCounter();
    },

    async updateMultipleFilter(id, typeName, boundType, value) {
        // 모든 배수 타입은 각자의 filter_key에 flat {min,max} 형식으로 저장 (multiple.html 호환)
        const MULTIPLE_TYPE_KEYS = {
            '3배수': 'multiple_3_count', '4배수': 'multiple_4_count', '5배수': 'multiple_5_count',
            '7배수': 'multiple_7_count', '8배수': 'multiple_8_count',
            '3·4배수': 'multiple_3_4_count', '3·5배수': 'multiple_3_5_count',
            '4·5배수': 'multiple_4_5_count', '배수외': 'no_multiple_count'
        };
        const MULTIPLE_MAX = { '8배수': 5, '3·4배수': 3, '3·5배수': 3, '4·5배수': 2 };
        const maxVal = MULTIPLE_MAX[typeName] ?? 6;

        const targetKey = MULTIPLE_TYPE_KEYS[typeName];
        if (!targetKey) return;
        const targetDef = this.state.foundationFilters.find(f => f.filter_key === targetKey);
        if (!targetDef) return;

        if (!this.state.userSettings[targetDef.id]) {
            this.state.userSettings[targetDef.id] = { enabled: false, settings: {} };
        }
        const targetUserSet = this.state.userSettings[targetDef.id];
        // flat 형식 저장
        targetUserSet.settings[boundType] = Math.max(0, Math.min(maxVal, parseInt(value) || 0));
        const newMin = targetUserSet.settings.min ?? 0;
        const newMax = targetUserSet.settings.max ?? maxVal;
        targetUserSet.settings.selectedValues = Array.from({ length: Math.max(0, newMax - newMin + 1) }, (_, i) => newMin + i);
        targetUserSet.settings.recent10FilterActive = false;

        // ON/OFF 공유: 배수 카드 전체 enabled는 multiple_3_count 기준, 개별 key는 항상 enabled=true
        await this._saveDashboardFilter(targetKey, targetUserSet.settings, true);
        this.renderFoundationFilters();
        this.updateNeonCounter();
    },

    async updateMagicSquareFilter(id, typeName, boundType, value) {
        const userSet = this.state.userSettings[id];
        if (!userSet) return;
        if (!userSet.settings.filters) userSet.settings.filters = {};
        if (!userSet.settings.filters[typeName]) userSet.settings.filters[typeName] = { min: 0, max: 5 };

        // [수정] 0~6 범위 제한
        userSet.settings.filters[typeName][boundType] = Math.max(0, Math.min(6, parseInt(value) || 0));
        userSet.settings.targetRound = this.state.allDraws && this.state.allDraws.length > 0 ? this.state.allDraws[0].round : null;
        userSet.settings.recent10FilterActive = false;

        // 디바운스 저장 (500ms) — 포커스 유지를 위해 renderFoundationFilters 호출 안 함
        if (this._msqSaveTimer) clearTimeout(this._msqSaveTimer);
        this._msqSaveTimer = setTimeout(async () => {
            const def = this.state.foundationFilters.find(f => f.id === id);
            if (def) {
                // IS NULL + round-specific 행 모두 저장 → 분석페이지 로드 시 반영
                await this._saveDashboardFilter(def.filter_key, userSet.settings, userSet.enabled);
            }
            this.updateNeonCounter();
        }, 500);
    },

    async updateLottoPaperFilter(id, typeName, boundType, value) {
        const userSet = this.state.userSettings[id];
        if (!userSet) return;
        if (!userSet.settings.groups) userSet.settings.groups = {};
        if (!userSet.settings.groups[typeName]) userSet.settings.groups[typeName] = { min: 0, max: 6 };

        // [수정] 0~6 범위 제한
        userSet.settings.groups[typeName][boundType] = Math.max(0, Math.min(6, parseInt(value) || 0));
        userSet.settings.targetRound = this.state.allDraws && this.state.allDraws.length > 0 ? this.state.allDraws[0].round : null;
        userSet.settings.recent10FilterActive = false; // 수동 변경 시 최근 10회차 버튼 비활성화

        const def = this.state.foundationFilters.find(f => f.id === id);
        if (def) {
            // [fix-318] _saveDashboardFilter — IS NULL + targetRound row 양쪽 저장 (분석페이지↔대시보드 sync)
            await this._saveDashboardFilter(def.filter_key, userSet.settings, userSet.enabled);
        }
        this.renderFoundationFilters();
        this.updateNeonCounter();
    },

    /**
     * [2026-05-14 수정] 끝수 필터 → tail_digit_patterns 통합 키로 저장
     * (end_digit_0~9_count 10개 유령 키는 DB에서 삭제됨 — Phase A·C)
     * settings 구조: { filters: { "0":{min,max}, ..., "9":{min,max} }, recent10FilterActive }
     */
    async updateTailDigitFilter(id, digit, type, value) {
        const TAIL_REAL_MAX = { 0: 4, 1: 5, 2: 5, 3: 5, 4: 5, 5: 5, 6: 4, 7: 4, 8: 4, 9: 4 };
        const realMax = TAIL_REAL_MAX[digit] ?? 6;

        const def = this.state.foundationFilters.find(f => f.filter_key === 'tail_digit_patterns');
        if (!def) {
            console.warn('[updateTailDigitFilter] tail_digit_patterns 정의를 찾을 수 없음');
            return;
        }

        if (!this.state.userSettings[def.id]) {
            this.state.userSettings[def.id] = { enabled: true, settings: { filters: {} } };
        }
        const us = this.state.userSettings[def.id];
        us.settings = us.settings || {};
        us.settings.filters = us.settings.filters || {};
        if (!us.settings.filters[digit]) us.settings.filters[digit] = { min: 0, max: realMax };

        const v = Math.max(0, Math.min(realMax, parseInt(value) || 0));
        us.settings.filters[digit][type] = v;
        us.settings.recent10FilterActive = false;

        await this._saveDashboardFilter(def.filter_key, us.settings, us.enabled);
        this.renderFoundationFilters();
        this.updateNeonCounter();
    },

    async updateHotColdFilter(id, field, index, value) {
        const userSet = this.state.userSettings[id];
        if (!userSet) return;

        // [수정] 0~6 범위 제한
        const v = Math.max(0, Math.min(6, parseInt(value) || 0));

        // 배열 포맷 업데이트 (대시보드 저장형)
        if (!userSet.settings[field]) userSet.settings[field] = [0, 6];
        userSet.settings[field][index] = v;

        // periodFilter flat 포맷도 함께 저장 (hot_cold.html 호환성)
        const hr = userSet.settings.hotRange || [0, 6];
        const wr = userSet.settings.warmRange || [0, 6];
        const cr = userSet.settings.coldRange || [0, 6];
        userSet.settings.periodFilter = {
            hotMin: hr[0], hotMax: hr[1],
            neutralMin: wr[0], neutralMax: wr[1],
            coldMin: cr[0], coldMax: cr[1]
        };

        // 수동 변경 시 최근 10회차 버튼 비활성화
        userSet.settings.recent10FilterActive = false;

        const def = this.state.foundationFilters.find(f => f.id === id);
        if (def) {
            // [fix-318] _saveDashboardFilter — IS NULL + targetRound row 양쪽 저장 (분석페이지↔대시보드 sync)
            await this._saveDashboardFilter(def.filter_key, userSet.settings, userSet.enabled);
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
        if (def) {
            // [수정] 최근 10회차를 켤 때만 필터를 자동으로 켜줌 (해제할 때는 기존 상태 유지)
            if (isActivating) userSet.enabled = true;

            // [2026-05-14] _saveDashboardFilter 사용 — targetRound + isManual 일괄 처리
            // (이전: Utils.saveFilter 직접 호출 + targetRound 누락 → null 저장)
            await this._saveDashboardFilter(def.filter_key, userSet.settings, userSet.enabled);
        }
        this.renderFoundationFilters();
        this.updateNeonCounter();
    },

    // ── 범용 최근 10회차 필터 토글 ────────────────────────────────────────────────
    async toggleRecent10Filter(defId) {
        const userSet = this.state.userSettings[defId];
        if (!userSet) return;

        const def = this.state.foundationFilters.find(f => f.id === defId);
        if (!def) return;

        const key = def.filter_key;

        // tail_digit는 기존 전용 함수 위임
        if (key === 'tail_digit_patterns') {
            return this.toggleRecent10TailDigits(defId);
        }

        const isActivating = !userSet.settings.recent10FilterActive;
        userSet.settings.recent10FilterActive = isActivating;

        // flag-only 필터: buildFilterControl의 표시 로직이 자동 제외 처리
        const flagOnlyKeys = ['total_sum', 'tail_sum', 'ac_value',
            'odd_even_pattern', 'high_low_pattern',
            'prime_number_patterns', 'composite_count', 'missing_period'];

        if (isActivating && this.state.allDraws && this.state.allDraws.length >= 10) {
            const recent10 = this.state.allDraws.slice(0, 10);
            if (!flagOnlyKeys.includes(key)) {
                this._calcAndApplyRecent10(key, userSet, recent10);
            }
        }

        // [성능] 해당 카드만 즉시 업데이트
        this._renderOneCard(defId); // [수정] _renderOneCardCtrl 대신 _renderOneCard를 호출하여 헤더 토글 상태까지 갱신
        this.updateNeonCounter();

        // [fix-321] _saveDashboardFilter — IS NULL + targetRound row 양쪽 저장 (다른 update 함수와 동일 패턴)
        // 이전: Utils.saveFilter (4th arg targetRound) 또는 filterService.saveSetting 단독 호출 → specific row만
        if (isActivating) userSet.enabled = true;
        await this._saveDashboardFilter(key, userSet.settings, userSet.enabled);
    },

    // 최근 10회차 기반 필터 값 계산 (flag-only 제외 모든 타입)
    _calcAndApplyRecent10(key, userSet, recent10) {
        const vals = userSet.settings;

        // ── 연속수 ──────────────────────────────────────────────────────────────
        if (key === 'consecutive_count') {
            const counts = recent10.map(d => {
                const nums = [...(d.numbers || [])].sort((a, b) => a - b);
                let cnt = 0;
                for (let i = 0; i < nums.length - 1; i++) if (nums[i + 1] - nums[i] === 1) cnt++;
                return cnt;
            });
            vals.selectedCounts = [...new Set(counts)].sort((a, b) => a - b);
            return;
        }

        // ── 동형수 ──────────────────────────────────────────────────────────────
        if (key === 'twin_number_patterns') {
            const counts = recent10.map(d => {
                const digitFreq = {};
                (d.numbers || []).forEach(n => { const dig = n % 10; digitFreq[dig] = (digitFreq[dig] || 0) + 1; });
                return Object.values(digitFreq).filter(c => c >= 2).length;
            });
            vals.selectedCounts = [...new Set(counts)].sort((a, b) => a - b);
            return;
        }

        // ── 제곱수 / 삼각수 ─────────────────────────────────────────────────────
        if (key === 'square_number_patterns' || key === 'triangular_number_patterns') {
            const targetSet = new Set(this.state.staticTargets[key] || []);
            const counts = recent10.map(d => (d.numbers || []).filter(n => targetSet.has(n)).length);
            vals.selectedCounts = [...new Set(counts)].sort((a, b) => a - b);
            return;
        }

        // ── 이월수 ──────────────────────────────────────────────────────────────
        if (key === 'carryover_count') {
            const counts = [];
            for (let i = 0; i < Math.min(recent10.length - 1, 9); i++) {
                const curSet = new Set(recent10[i].numbers || []);
                counts.push((recent10[i + 1].numbers || []).filter(n => curSet.has(n)).length);
            }
            vals.selectedCounts = [...new Set(counts)].sort((a, b) => a - b);
            return;
        }

        // ── 배수 ────────────────────────────────────────────────────────────────
        if (key === 'multiple_3_count') {
            // 각 배수 타입을 개별 filter_key에 flat {min,max} 형식으로 저장 (multiple.html 호환)
            const MULTI_DEFS = {
                '3배수': { nums: [3,6,9,12,15,18,21,24,27,30,33,36,39,42,45], key: 'multiple_3_count' },
                '4배수': { nums: [4,8,12,16,20,24,28,32,36,40,44],            key: 'multiple_4_count' },
                '5배수': { nums: [5,10,15,20,25,30,35,40,45],                 key: 'multiple_5_count' },
                '7배수': { nums: [7,14,21,28,35,42],                          key: 'multiple_7_count' },
                '8배수': { nums: [8,16,24,32,40],                             key: 'multiple_8_count' },
            };
            if (!vals.filters) vals.filters = {};
            Object.entries(MULTI_DEFS).forEach(([typeName, { nums, key: typeKey }]) => {
                const mSet = new Set(nums);
                const counts = recent10.map(d => (d.numbers || []).filter(n => mSet.has(n)).length);
                const minC = Math.min(...counts), maxC = Math.max(...counts);
                // vals.filters에도 기록 (번들 폴백용)
                vals.filters[typeName] = { min: minC, max: maxC };
                // 각 개별 key의 userSettings를 flat 형식으로 업데이트
                const typeDef = this.state.foundationFilters.find(f => f.filter_key === typeKey);
                if (!typeDef) return;
                if (!this.state.userSettings[typeDef.id]) this.state.userSettings[typeDef.id] = { enabled: false, settings: {} };
                const typeUserSet = this.state.userSettings[typeDef.id];
                typeUserSet.settings.min = minC;
                typeUserSet.settings.max = maxC;
                typeUserSet.settings.selectedValues = Array.from({ length: maxC - minC + 1 }, (_, i) => minC + i);
                // multiple_3_count는 caller(toggleRecent10Filter)가 저장, 나머지는 fire-and-forget
                if (typeKey !== 'multiple_3_count') {
                    this._saveDashboardFilter(typeKey, typeUserSet.settings, true);
                }
            });
            return;
        }

        // ── 번호 구간 ───────────────────────────────────────────────────────────
        if (key === 'number_range_patterns') {
            const rangeDefs = { '1_10': [1, 10], '11_20': [11, 20], '21_30': [21, 30], '31_40': [31, 40], '41_45': [41, 45] };
            if (!vals.ranges) vals.ranges = {};
            Object.entries(rangeDefs).forEach(([rKey, [lo, hi]]) => {
                const counts = recent10.map(d => (d.numbers || []).filter(n => n >= lo && n <= hi).length);
                vals.ranges[rKey] = { min: Math.min(...counts), max: Math.max(...counts) };
            });
            return;
        }

        // ── 9궁 ─────────────────────────────────────────────────────────────────
        if (key === 'magic_square_pattern') {
            const gungDefs = {
                '1궁': [1, 2, 3, 4, 5], '2궁': [6, 7, 8, 9, 10], '3궁': [11, 12, 13, 14, 15],
                '4궁': [16, 17, 18, 19, 20], '5궁': [21, 22, 23, 24, 25], '6궁': [26, 27, 28, 29, 30],
                '7궁': [31, 32, 33, 34, 35], '8궁': [36, 37, 38, 39, 40], '9궁': [41, 42, 43, 44, 45]
            };
            if (!vals.filters) vals.filters = {};
            Object.entries(gungDefs).forEach(([gName, gNums]) => {
                const gSet = new Set(gNums);
                const counts = recent10.map(d => (d.numbers || []).filter(n => gSet.has(n)).length);
                vals.filters[gName] = { min: Math.min(...counts), max: Math.max(...counts) };
            });
            return;
        }

        // ── 로또용지 ────────────────────────────────────────────────────────────
        if (key === 'lotto_paper_pattern') {
            const paperDefs = {
                '가로1': [1, 2, 3, 4, 5, 6, 7], '가로2': [8, 9, 10, 11, 12, 13, 14],
                '가로3': [15, 16, 17, 18, 19, 20, 21], '가로4': [22, 23, 24, 25, 26, 27, 28],
                '가로5': [29, 30, 31, 32, 33, 34, 35], '가로6': [36, 37, 38, 39, 40, 41, 42],
                '가로7': [43, 44, 45],
                '세로1': [1, 8, 15, 22, 29, 36, 43], '세로2': [2, 9, 16, 23, 30, 37, 44],
                '세로3': [3, 10, 17, 24, 31, 38, 45], '세로4': [4, 11, 18, 25, 32, 39],
                '세로5': [5, 12, 19, 26, 33, 40], '세로6': [6, 13, 20, 27, 34, 41],
                '세로7': [7, 14, 21, 28, 35, 42]
            };
            if (!vals.groups) vals.groups = {};
            Object.entries(paperDefs).forEach(([gName, gNums]) => {
                const gSet = new Set(gNums);
                const counts = recent10.map(d => (d.numbers || []).filter(n => gSet.has(n)).length);
                vals.groups[gName] = { min: Math.min(...counts), max: Math.max(...counts) };
            });
            return;
        }

        // ── 핫/콜드 ─────────────────────────────────────────────────────────────
        if (key.startsWith('hot_cold_')) {
            const period = parseInt(key.split('_')[2]);
            const CRITERIA = {
                5:  { hot: 2, neutralMin: 1 },
                10: { hot: 3, neutralMin: 1 },
                15: { hot: 4, neutralMin: 2 },
                20: { hot: 5, neutralMin: 2 }
            };
            const crit = CRITERIA[period] || CRITERIA[10];
            const refDraws = this.state.allDraws.slice(0, period);
            const countMap = {};
            for (let n = 1; n <= 45; n++) countMap[n] = 0;
            refDraws.forEach(d => (d.numbers || []).forEach(n => { if (n >= 1 && n <= 45) countMap[n]++; }));
            const hotSet  = new Set(Object.keys(countMap).map(Number).filter(n => countMap[n] >= crit.hot));
            const warmSet = new Set(Object.keys(countMap).map(Number).filter(n => countMap[n] >= crit.neutralMin && countMap[n] < crit.hot));
            const coldSet = new Set(Object.keys(countMap).map(Number).filter(n => countMap[n] < crit.neutralMin));
            const hotCounts  = recent10.map(d => (d.numbers || []).filter(n => hotSet.has(n)).length);
            const warmCounts = recent10.map(d => (d.numbers || []).filter(n => warmSet.has(n)).length);
            const coldCounts = recent10.map(d => (d.numbers || []).filter(n => coldSet.has(n)).length);
            // hotRange 기준으로 min/max 설정
            vals.min = Math.min(...hotCounts);
            vals.max = Math.max(...hotCounts);
            return;
        }

        // ── 이웃수 ──────────────────────────────────────────────────────────────
        if (key === 'neighbor_number_patterns') {
            const neighborSet = new Set(this.state.dynamicTargets['neighbor_number_patterns'] || []);
            if (neighborSet.size > 0) {
                const counts = recent10.map(d => (d.numbers || []).filter(n => neighborSet.has(n)).length);
                vals.min = Math.min(...counts);
                vals.max = Math.max(...counts);
            }
            return;
        }
    },
    // ── 범용 최근 10회차 필터 토글 (끝)) ─────────────────────────────────────────

    async updateMissingPeriodFilter(id, rangeKey, value, cap) {
        const userSet = this.state.userSettings[id];
        if (!userSet) return;
        if (!userSet.settings.ranges) userSet.settings.ranges = {};
        // [fix-411] 그룹 사이즈 cap으로 클램프 (cap 미지정 시 기존 0~6 제한)
        const upper = (typeof cap === 'number' && cap >= 0 && cap <= 6) ? cap : 6;
        userSet.settings.ranges[rangeKey] = Math.max(0, Math.min(upper, parseInt(value) || 0));
        // 수동 변경 시 최근 10회차 버튼 비활성화
        userSet.settings.recent10FilterActive = false;

        const def = this.state.foundationFilters.find(f => f.id === id);
        if (def) {
            // [Fix] _saveDashboardFilter 사용: IS NULL + 특정 회차 행 모두 저장 (대시보드↔분석페이지 동기화)
            await this._saveDashboardFilter(def.filter_key, userSet.settings, userSet.enabled);
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

        if (window.Utils && window.Utils.saveFilter) {
            await window.Utils.saveFilter('regression_analysis', this.state.regressionSettings, true, this.state.targetRound);
        } else if (window.filterService?.initialized) {
            await window.filterService.saveSetting('regression_analysis', this.state.regressionSettings, true, this.state.targetRound);
        }
        this.renderRegressionFilters();
        this.updateNeonCounter();
    },

    // 🔥 추가: 회귀분석 Min/Max 입력 시 즉시 DB 저장
    async updateRegressionRange(step, type, value) {
        if (!this.state.regressionSettings[step]) this.state.regressionSettings[step] = { enabled: false, min: 0, max: 2 };
        // [수정] 0~6 범위 제한
        const v = Math.max(0, Math.min(6, parseInt(value) || 0));
        this.state.regressionSettings[step][type] = v;

        if (this._regSaveTimer) clearTimeout(this._regSaveTimer);
        this._regSaveTimer = setTimeout(async () => {
            const isOn = this.state.regressionEnabled !== false;
            // [수정] Utils.saveFilter를 사용하여 실시간 동기화(storage 이벤트) 트리거
            if (window.Utils && window.Utils.saveFilter) {
                await window.Utils.saveFilter('regression_analysis', this.state.regressionSettings, isOn, this.state.targetRound);
            } else if (window.filterService?.initialized) {
                await window.filterService.saveSetting('regression_analysis', this.state.regressionSettings, isOn, this.state.targetRound);
            }
            this.updateNeonCounter();
        }, 500);
    },

    /**
     * [fix-291] 커스텀 필터 제목 인라인 편집
     * 카드의 제목 영역을 input으로 교체 → Enter/blur 저장 → Escape 취소
     * [fix-292] AI 자동 감지 키워드 보존 가드 (레거시 호환)
     */
    async editCustomTitle(id) {
        const link = document.getElementById(`filter-title-link-${id}`);
        if (!link || link.dataset.editing === '1') return;
        link.dataset.editing = '1';
        const custom = this.state.customFilters.find(c => c.id === id);
        if (!custom) return;
        const oldTitle = custom.title || '';
        // [fix-292] AI 자동 감지 키워드 (레거시 호환 — calculateCustomTargets isAiModelTitle 정규식과 동일)
        const AI_KEYWORDS_RE = /(GNN|CNN|MARKOV|AUTOENCODER|XGBOOST|XGB|CATBOOST|TABNET|TFT|N-?BEATS|NBEATS|MHN|BAYESIAN|ENSEMBLE|앙상블|추천조합|TF|ATC|AE|AI|딥러닝|추천|제외)/i;
        const oldHasAiKeyword = AI_KEYWORDS_RE.test(oldTitle);
        const oldHref = link.getAttribute('href');
        const oldClass = link.className;

        const input = document.createElement('input');
        input.type = 'text';
        input.value = oldTitle;
        input.className = 'text-base font-black text-slate-800 bg-pink-50 border-b-2 border-pink-500 focus:outline-none focus:bg-white px-1.5 py-0.5 rounded-t';
        input.style.minWidth = '180px';
        input.style.width = Math.max(180, oldTitle.length * 14) + 'px';
        link.replaceWith(input);
        input.focus();
        input.select();

        let resolved = false;
        const restore = (newTitle) => {
            if (resolved) return;
            resolved = true;
            const a = document.createElement('a');
            a.href = oldHref;
            a.id = `filter-title-link-${id}`;
            a.className = oldClass;
            a.textContent = newTitle;
            input.replaceWith(a);
        };
        const save = async () => {
            const val = input.value.trim();
            if (!val || val === oldTitle) { restore(oldTitle); return; }
            // [fix-292] AI 키워드 보존 가드 — 원래 AI 키워드가 있던 필터인데 새 제목에 AI 키워드가 없으면 사용자에게 경고
            if (oldHasAiKeyword && !AI_KEYWORDS_RE.test(val)) {
                const proceed = confirm(
                    `⚠ 이 필터는 AI 자동 감지 키워드(GNN/CNN/AI/딥러닝/추천/제외 등)가 포함된 제목이었습니다.\n` +
                    `새 제목 "${val}"에는 키워드가 없어 AI 실시간 데이터 자동 매칭이 풀릴 수 있습니다.\n` +
                    `(저장된 정적 target_numbers는 그대로 유지됨)\n\n` +
                    `계속 변경하시겠습니까?`
                );
                if (!proceed) { restore(oldTitle); return; }
            }
            try {
                if (window.supabaseClient) {
                    const { error } = await window.supabaseClient
                        .from('ai_custom_analyses').update({ title: val, updated_at: new Date().toISOString() }).eq('id', id);
                    if (error) throw error;
                }
                custom.title = val;
                restore(val);
                // 다른 페이지/탭 갱신 알림
                localStorage.setItem('custom_analysis_refresh', Date.now());
            } catch (e) {
                console.error('[editCustomTitle] 저장 실패', e);
                alert('제목 변경 실패: ' + (e.message || '알 수 없는 오류'));
                restore(oldTitle);
            }
        };
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); save(); }
            else if (e.key === 'Escape') { e.preventDefault(); restore(oldTitle); }
        });
        input.addEventListener('blur', save);
    },

    async toggleCustom(id, isEnabled) {
        const custom = this.state.customFilters.find(c => c.id === id);
        if (custom) {
            let conf = typeof custom.filter_config === 'string' ? JSON.parse(custom.filter_config) : custom.filter_config;
            conf.enabled = isEnabled;
            // [추가] 저장 시 target_round 포함 (검증 페이지용)
            if (this.state.targetRound) conf.target_round = this.state.targetRound;
            custom.filter_config = conf;
            if (window.supabaseClient) {
                await window.supabaseClient.from('ai_custom_analyses').update({ filter_config: conf, updated_at: new Date().toISOString() }).eq('id', id);
            }
            // [수정] FilterService의 구조상 custom_filter_*는 정의되지 않은 필터이므로 Utils.saveFilter 호출 시 콘솔 에러 발생.
            // 다른 탭과의 동기화를 위해 localStorage와 이벤트만 별도로 발생시킴.
            localStorage.setItem(`custom_filter_${id}`, JSON.stringify({ settings: conf, enabled: conf.enabled, target_round: this.state.targetRound }));
            window.dispatchEvent(new Event('storage'));

            this.renderCustomFilters();
            this.updateNeonCounter();
        }
    },

    // [New] 커스텀 분석 Min/Max 변경 핸들러
    async updateCustomMinMax(id, type, value) {
        const custom = this.state.customFilters.find(c => c.id === id);
        if (!custom) return;

        let conf = typeof custom.filter_config === 'string' ? JSON.parse(custom.filter_config) : custom.filter_config;
        // [수정] 0~6 범위 제한
        conf[type] = Math.max(0, Math.min(6, parseInt(value) || 0));
        // [Fix] min/max 직접 변경 시 values 배열 초기화 → min-max 모드로 통일
        // values가 남아있으면 custom_analysis.html에서 버튼 표시가 values 우선 → min/max 변경이 무시됨
        delete conf.values;
        // [추가] 저장 시 target_round 포함 (검증 페이지용)
        if (this.state.targetRound) conf.target_round = this.state.targetRound;
        custom.filter_config = conf;

        // DB Update
        if (window.supabaseClient) {
            await window.supabaseClient.from('ai_custom_analyses').update({ filter_config: conf }).eq('id', id);
        }

        // localStorage 저장 (실시간 동기화용)
        // [수정] custom_filter_*는 자체 DB 테이블(ai_custom_analyses)을 사용하므로 
        // FilterService 쪽 에러(정의 없음)를 피하기 위해 스토리지 이벤트만 수동 발생
        this._dashSelfSaving = true;
        try {
            localStorage.setItem(`custom_filter_${id}`, JSON.stringify({ settings: conf, enabled: conf.enabled, target_round: this.state.targetRound }));
            window.dispatchEvent(new Event('storage'));
        } finally {
            this._dashSelfSaving = false;
        }

        this.renderCustomFilters();
        this.updateNeonCounter();
    },

    async bulkToggleRegression(isOn) {
        this.state.regressionEnabled = isOn;
        for (let i = 2; i <= 200; i++) {
            if (!this.state.regressionSettings[i]) this.state.regressionSettings[i] = { enabled: isOn, min: 0, max: 2 };
            else this.state.regressionSettings[i].enabled = isOn;
        }
        if (window.Utils && window.Utils.saveFilter) {
            await window.Utils.saveFilter('regression_analysis', this.state.regressionSettings, isOn, this.state.targetRound);
        } else if (window.filterService?.initialized) {
            await window.filterService.saveSetting('regression_analysis', this.state.regressionSettings, isOn, this.state.targetRound);
        }
        this.renderRegressionFilters();
        this.updateNeonCounter();
    },

    /**
     * 일괄 필터 적용 — 입력한 min/max를 활성화된 회귀 단계 모두에 적용 (또는 전 단계).
     * @returns void
     */
    async bulkApplyRegressionRange() {
        const minInput = document.getElementById('regBulkMin');
        const maxInput = document.getElementById('regBulkMax');
        if (!minInput || !maxInput) return;

        // 빈 입력은 placeholder 기본값 사용 (min=0, max=2)
        const minRaw = (minInput.value || '').toString().trim();
        const maxRaw = (maxInput.value || '').toString().trim();
        const min = minRaw === '' ? 0 : parseInt(minRaw, 10);
        const max = maxRaw === '' ? 2 : parseInt(maxRaw, 10);

        if (isNaN(min) || isNaN(max) || min < 0 || min > 6 || max < 0 || max > 6) {
            alert('min/max에 0~6 사이 숫자를 입력하세요.');
            return;
        }
        if (min > max) {
            alert('min은 max보다 작거나 같아야 합니다.');
            return;
        }

        // 활성화된 회귀가 있으면 활성 단계에만, 아니면 전 단계(2~200)에 적용
        const enabledSteps = [];
        for (let i = 2; i <= 200; i++) {
            if (this.state.regressionSettings[i]?.enabled) enabledSteps.push(i);
        }
        const targetSteps = enabledSteps.length > 0 ? enabledSteps : Array.from({length: 199}, (_, i) => i + 2);

        const confirmMsg = enabledSteps.length > 0
            ? `활성화된 ${enabledSteps.length}개 회귀 단계에 일괄 적용 (${min}~${max}) 하시겠습니까?`
            : `전체 199개 회귀 단계에 일괄 적용 (${min}~${max}) 하시겠습니까?\n(현재 활성화된 단계가 없으므로 전 단계에 적용됩니다)`;
        if (!confirm(confirmMsg)) return;

        for (const step of targetSteps) {
            if (!this.state.regressionSettings[step]) {
                this.state.regressionSettings[step] = { enabled: true, min, max };
            } else {
                this.state.regressionSettings[step].min = min;
                this.state.regressionSettings[step].max = max;
                if (enabledSteps.length === 0) this.state.regressionSettings[step].enabled = true;
            }
        }
        if (enabledSteps.length === 0) this.state.regressionEnabled = true;

        // 저장
        if (window.Utils && window.Utils.saveFilter) {
            await window.Utils.saveFilter('regression_analysis', this.state.regressionSettings, this.state.regressionEnabled, this.state.targetRound);
        } else if (window.filterService?.initialized) {
            await window.filterService.saveSetting('regression_analysis', this.state.regressionSettings, this.state.regressionEnabled, this.state.targetRound);
        }

        this.renderRegressionFilters();
        this.updateNeonCounter();
        console.log(`✅ 회귀 일괄 적용: ${targetSteps.length}개 단계에 ${min}~${max} 적용`);
    },

    async removeExcludedSum(id, sumValue) {
        if (!this.state.userSettings[id]) return;
        const record = this.state.userSettings[id];
        const def = this.state.foundationFilters.find(d => d.id === id);
        const key = def ? def.filter_key : null;

        let targetArray = null;
        let arrayName = null;

        if (key.includes('ac_value')) {
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

            // [수정] 수동 조작 시 최근 10회차 모드 비활성화
            record.settings.recent10FilterActive = false;

            if (key) {
                // [수정] window.Utils.saveFilter 사용 (DB + localStorage 동시 저장 및 실시간 동기화)
                if (window.Utils && window.Utils.saveFilter) {
                    await window.Utils.saveFilter(key, record.settings, record.enabled);
                } else if (window.filterService?.initialized) {
                    await window.filterService.saveSetting(key, record.settings, record.enabled);
                    const settingsWithEnabled = { ...record.settings, enabled: record.enabled };
                    localStorage.setItem(key, JSON.stringify(settingsWithEnabled));
                }
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
        if (key.includes('ac_value')) arrayName = 'restoredAutoAcValues';
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

            // [수정] 수동 조작 시 최근 10회차 모드 비활성화
            record.settings.recent10FilterActive = false;

            if (key) {
                // [수정] window.Utils.saveFilter 사용 (DB + localStorage 동시 저장 및 실시간 동기화)
                if (window.Utils && window.Utils.saveFilter) {
                    await window.Utils.saveFilter(key, record.settings, record.enabled);
                } else if (window.filterService?.initialized) {
                    await window.filterService.saveSetting(key, record.settings, record.enabled);
                    const settingsWithEnabled = { ...record.settings, enabled: record.enabled };
                    localStorage.setItem(key, JSON.stringify(settingsWithEnabled));
                    localStorage.setItem(key + '_filter', JSON.stringify(settingsWithEnabled));
                }
            }
            this.renderFoundationFilters();
            this.updateNeonCounter();
        }
    },

    updateNeonCounter() {
        // 1) 즉시 "계산 중..." 표시
        const obj = document.getElementById('neonCounter');
        if (obj) {
            obj.innerHTML = '<span class="opacity-40 text-2xl">계산 중...</span>';
            obj.classList.add('opacity-50', 'animate-pulse');
        }
        // 2) 워커 전수조사 즉시 트리거 (DOM 이벤트 없이도 항상 정확한 값 갱신)
        if (typeof window.triggerFilterCount === 'function') {
            window.triggerFilterCount();
        }
    },

    _updateNeonCounterLegacy() {
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
    },

    // [중복 제거] updateMissingCustomMinMax는 line 1835의 버전(디바운스 포함)만 사용

    async updateGungFilter(defId, gungType, type, value) {
        const userSet = this.state.userSettings[defId];
        if (!userSet) return;
        if (!userSet.settings.filters) userSet.settings.filters = {};
        if (!userSet.settings.filters[gungType]) userSet.settings.filters[gungType] = { min: 0, max: 6 };

        const val = parseInt(value);
        if (isNaN(val)) return;
        userSet.settings.filters[gungType][type] = val;

        // [수정] 수동 조작 시 최근 10회차 모드 비활성화
        userSet.settings.recent10FilterActive = false;

        if (this._saveTimer) clearTimeout(this._saveTimer);
        this._saveTimer = setTimeout(async () => {
            const def = this.state.foundationFilters.find(d => d.id === defId);
            if (def) {
                // IS NULL + round-specific 행 모두 저장 → 분석페이지 로드 시 대시보드 변경값 반영
                await this._saveDashboardFilter(def.filter_key, userSet.settings, userSet.enabled !== false);
            }
        }, 500);
    },

    // [New] 🔥 전체 필터 설정 초기화 (DB + LocalStorage)
    async resetDashboard() {
        if (!confirm('모든 필터 설정을 초기화하시겠습니까?\n(분석 페이지의 설정도 모두 삭제됩니다)')) return;

        const btn = document.getElementById('btnGlobalReset');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<span class="animate-spin material-symbols-outlined">sync</span>';
        }

        try {
            // 1. Supabase DB 초기화 (현재 프리셋 내의 모든 설정 삭제)
            if (window.filterService?.initialized) {
                const { error } = await window.supabaseClient
                    .from('filter_settings')
                    .delete()
                    .eq('preset_id', window.filterService.currentPresetId);

                if (error) throw error;
            }

            // 2. LocalStorage 관련 모든 키 삭제
            const keysToRemove = [
                'total_sum', 'tail_sum', 'ac_value', 'odd_even_pattern', 'high_low_pattern',
                'prime_number_patterns', 'composite_count', 'square_number_patterns',
                'triangular_number_patterns', 'twin_number_patterns', 'neighbor_number_patterns',
                'carryover_count', 'consecutive_count', 'multiple_3_count',
                'multiple_7_count', 'multiple_8_count', 'number_range_patterns',
                'magic_square_pattern', 'lotto_paper_pattern', 'hot_cold_5', 'hot_cold_10',
                'hot_cold_15', 'hot_cold_20', 'missing_period', 'missing_custom_filter',
                'regression_analysis', 'lotto_basket', 'tail_digit_patterns'
            ];
            keysToRemove.forEach(k => {
                localStorage.removeItem(k);
                localStorage.removeItem(k + '_filter');
            });

            // 3. 상태 초기화
            this.state.userSettings = {};
            this.state.regressionSettings = {};
            this.state.regressionEnabled = false;
            this.state.basket = { fixed: [], excluded: [] };

            // 4. 리로드
            alert('초기화가 완료되었습니다.');
            window.location.reload();
        } catch (e) {
            console.error('[Dashboard] Reset Error:', e);
            alert('초기화 중 오류가 발생했습니다: ' + e.message);
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<span class="material-symbols-outlined">history</span>';
            }
        }
    }
};
