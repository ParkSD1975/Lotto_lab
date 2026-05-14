/**
 * ============================================
 * FilterService.js
 * 로또 AI 필터 시스템 - DB 연동 핵심 모듈
 * ============================================
 * 
 * 기능:
 * - 필터 정의 로드 (캐싱)
 * - 사용자 프리셋 관리
 * - 필터 설정 저장/로드 (Supabase DB)
 * - localStorage → DB 마이그레이션
 * - AI 분석용 데이터 포맷팅
 */

class FilterService {
    constructor(supabaseClient) {
        this.supabase = supabaseClient;
        this.currentPresetId = null;
        this.userId = null;

        // 캐시
        this.definitionsCache = null;
        this.definitionsCacheTime = null;
        this.CACHE_TTL = 5 * 60 * 1000; // 5분

        // 초기화 상태
        this.initialized = false;
    }

    // ==========================================
    // 초기화
    // ==========================================

    /**
     * 서비스 초기화 (페이지 로드 시 호출)
     */
    async initialize() {
        if (this.initialized) return true;

        try {
            // 1. 사용자 확인 (없으면 익명 로그인 자동 처리)
            let { data: { user } } = await this.supabase.auth.getUser();
            const isNewAnonUser = !user;
            if (!user) {
                console.log('🔐 FilterService: 익명 로그인 시도...');
                const { data: anonData, error: anonErr } = await this.supabase.auth.signInAnonymously();
                if (anonErr || !(anonData && anonData.user)) {
                    console.warn('⚠️ FilterService: 익명 로그인 실패', anonErr && anonErr.message);
                    // [Fix] 익명 로그인 불가 시 (localhost 등) → 저장된 preset_id로 읽기 전용 초기화
                    // filter_definitions(category=system)과 filter_settings(anon role 허용)은 인증 없이 읽기 가능
                    const savedPresetId = localStorage.getItem('_lotto_preset_id');
                    if (savedPresetId) {
                        this.currentPresetId = savedPresetId;
                        this.initialized = true;
                        console.log('✅ FilterService: 로컬 preset_id로 읽기 전용 모드 초기화', savedPresetId);
                        return true;
                    }
                    console.warn('⚠️ FilterService: preset_id 없음, localStorage 모드로 폴백');
                    return false;
                }
                user = anonData.user;
                console.log('✅ FilterService: 익명 로그인 성공 (새 세션)');
            }
            this.userId = user.id;

            // [Fix] 세션 만료 후 새 익명 유저 생성 시: localStorage에 저장된 preset_id로 기존 데이터 먼저 복구 시도
            if (isNewAnonUser) {
                const savedPresetId = localStorage.getItem('_lotto_preset_id');
                if (savedPresetId) {
                    console.log('🔄 FilterService: 세션 복구 시도 - 기존 preset_id:', savedPresetId);
                    const { error: updateErr } = await this.supabase
                        .from('user_filter_presets')
                        .update({ user_id: this.userId })
                        .eq('id', savedPresetId);
                    if (!updateErr) {
                        this.currentPresetId = savedPresetId;
                        console.log('✅ FilterService: 기존 필터 설정 복구 완료 (세션 재연결)');
                    } else {
                        console.warn('⚠️ FilterService: preset 복구 실패, 새 preset 생성', updateErr.message);
                    }
                }
            }

            // 2. 기본 프리셋 확보 (복구 실패 또는 최초 실행 시)
            if (!this.currentPresetId) {
                await this.ensureDefaultPreset();
            }

            // preset_id localStorage에 저장 (다음 세션 복구용)
            if (this.currentPresetId) {
                localStorage.setItem('_lotto_preset_id', this.currentPresetId);
            }

            // 3. localStorage 마이그레이션 (최초 1회)
            await this.migrateFromLocalStorage();

            this.initialized = true;
            console.log('✅ FilterService 초기화 완료');
            return true;

        } catch (error) {
            console.error('❌ FilterService 초기화 실패:', error);
            return false;
        }
    }

    // ==========================================
    // 필터 정의 (filter_definitions)
    // ==========================================

    /**
     * 모든 활성 필터 정의 로드 (캐싱)
     */
    async loadDefinitions(forceRefresh = false) {
        // 캐시 유효한 경우 바로 반환
        if (!forceRefresh && this.definitionsCache &&
            Date.now() - this.definitionsCacheTime < this.CACHE_TTL) {
            return this.definitionsCache;
        }

        const { data, error } = await this.supabase
            .from('filter_definitions')
            .select('*')
            .eq('is_active', true)
            .order('display_order');

        if (error) {
            console.error('❌ 필터 정의 로드 실패:', error);
            return this.definitionsCache || [];
        }

        this.definitionsCache = data;
        this.definitionsCacheTime = Date.now();

        return data;
    }

    /**
     * filter_key로 정의 조회
     */
    async getDefinitionByKey(filterKey) {
        const definitions = await this.loadDefinitions();
        return definitions.find(d => d.filter_key === filterKey) || null;
    }

    /**
     * ui_group별로 필터 그룹핑
     */
    async getDefinitionsByGroup() {
        const definitions = await this.loadDefinitions();
        const groups = {};

        definitions.forEach(def => {
            const group = def.ui_group || 'general';
            if (!groups[group]) groups[group] = [];
            groups[group].push(def);
        });

        return groups;
    }

    // ==========================================
    // 프리셋 (user_filter_presets)
    // ==========================================

    /**
     * 기본 프리셋 확보 (없으면 생성)
     */
    async ensureDefaultPreset() {
        if (!this.userId) return null;

        // 기존 기본 프리셋 조회
        const { data: existing } = await this.supabase
            .from('user_filter_presets')
            .select('id')
            .eq('user_id', this.userId)
            .eq('is_default', true)
            .maybeSingle();

        if (existing) {
            this.currentPresetId = existing.id;
            return this.currentPresetId;
        }

        // 없으면 생성
        const { data: newPreset, error } = await this.supabase
            .from('user_filter_presets')
            .insert({
                user_id: this.userId,
                preset_name: '기본 전략',
                is_default: true
            })
            .select('id')
            .single();

        if (error) {
            console.error('❌ 기본 프리셋 생성 실패:', error);
            return null;
        }

        this.currentPresetId = newPreset.id;
        return this.currentPresetId;
    }

    /**
     * 사용자 프리셋 목록 조회
     */
    async getPresets() {
        if (!this.userId) return [];

        const { data, error } = await this.supabase
            .from('user_filter_presets')
            .select('*')
            .eq('user_id', this.userId)
            .order('created_at', { ascending: false });

        return data || [];
    }

    /**
     * 새 프리셋 생성
     */
    async createPreset(name, description = '', tags = []) {
        if (!this.userId) return null;

        const { data, error } = await this.supabase
            .from('user_filter_presets')
            .insert({
                user_id: this.userId,
                preset_name: name,
                description,
                tags,
                is_default: false
            })
            .select()
            .single();

        if (error) {
            console.error('❌ 프리셋 생성 실패:', error);
            return null;
        }

        return data;
    }

    /**
     * 현재 프리셋 변경
     */
    setCurrentPreset(presetId) {
        this.currentPresetId = presetId;
    }

    // ==========================================
    // 필터 설정 (filter_settings)
    // ==========================================

    /**
     * 단일 필터 설정 저장
     */
    async saveSetting(filterKey, settings, enabled = false, targetRound = null) {
        if (!this.currentPresetId) {
            await this.ensureDefaultPreset();
        }
        if (!this.currentPresetId) return null;

        // filter_key 또는 filter_id로 definition 조회
        let definition;

        // 첫 시도: filter_key로 조회
        definition = await this.getDefinitionByKey(filterKey);

        // 두 번째 시도: ID로 조회 (FilterDashboard에서 ID를 전달하는 경우)
        if (!definition) {
            const definitions = await this.loadDefinitions();
            definition = definitions.find(d => d.id === filterKey);
        }

        if (!definition) {
            console.error(`❌ 필터 정의를 찾을 수 없음: ${filterKey}`);
            console.log('🔍 사용 가능한 필터들:', (await this.loadDefinitions()).map(d => ({ id: d.id, key: d.filter_key, name: d.filter_name })));
            return null;
        }

        // 필터_key로 통일 (이후 DB 쿼리는 filter_definition_id 사용)
        const actualFilterKey = definition.filter_key;

        // 기존 레코드 확인 후 insert/update 분기
        let query = this.supabase
            .from('filter_settings')
            .select('id')
            .eq('preset_id', this.currentPresetId)
            .eq('filter_definition_id', definition.id);

        if (targetRound) {
            query = query.eq('target_round', targetRound);
        } else {
            query = query.is('target_round', null);
        }

        const { data: existing } = await query.maybeSingle();

        let data, error;
        if (existing) {
            // UPDATE
            ({ data, error } = await this.supabase
                .from('filter_settings')
                .update({ settings, enabled, updated_at: new Date().toISOString() })
                .eq('id', existing.id)
                .select()
                .single());
        } else {
            // INSERT
            ({ data, error } = await this.supabase
                .from('filter_settings')
                .insert({
                    preset_id: this.currentPresetId,
                    filter_definition_id: definition.id,
                    settings,
                    enabled,
                    target_round: targetRound
                })
                .select()
                .single());
        }

        if (error) {
            if (error.message && error.message.includes('Failed to fetch')) {
                // 오프라인 상태 (인터넷 끊김) - 로컬스토리지 백업이 동작하므로 콘솔 에러 생략
            } else {
                console.error(`❌ 필터 설정 저장 실패 (${filterKey}):`, error);
            }
            return null;
        }

        console.log(`✅ 필터 저장: ${filterKey}`, { enabled, settings });

        // [핵심] localStorage도 동기화 — Utils.loadFilter fresh-path와 filter_dashboard.js 양쪽이
        // 동일한 값을 보도록 보장. targetRound가 있는 경우(회차별 설정)는 전역 localStorage를 덮지 않음.
        if (!targetRound) {
            try {
                const envelope = { settings, enabled, _ts: Date.now() };
                localStorage.setItem(actualFilterKey, JSON.stringify(envelope));
            } catch (_) { /* localStorage 쓰기 실패 무시 */ }
        }

        return data;
    }

    /**
     * 단일 필터 설정 로드
     */
    async loadSetting(filterKey, targetRound = null) {
        if (!this.currentPresetId) {
            await this.ensureDefaultPreset();
        }
        if (!this.currentPresetId) return null;

        const definition = await this.getDefinitionByKey(filterKey);
        if (!definition) return null;

        // [수정] 우선순위 로직: 특정 회차(targetRound) 먼저 조회 후 없으면 NULL(기본값) 조회
        let query = this.supabase
            .from('filter_settings')
            .select('*')
            .eq('preset_id', this.currentPresetId)
            .eq('filter_definition_id', definition.id);

        if (targetRound) {
            // 특정 회차와 NULL을 모두 가져오되, 회차 우선순위 부여를 위해 or 조건 사용
            query = query.or(`target_round.eq.${targetRound},target_round.is.null`);
            const { data, error } = await query;

            if (error) {
                console.error(`❌ 필터 설정 로드 실패 (${filterKey}):`, error);
                return null;
            }

            if (!data || data.length === 0) return null;

            // targetRound가 일치하는 것이 있으면 그것을 반환, 없으면 NULL인 것을 반환
            const specificMatch = data.find(item => item.target_round === targetRound);
            return specificMatch || data.find(item => item.target_round === null);
        } else {
            // targetRound가 없으면 NULL인 것만 조회
            query = query.is('target_round', null);
            const { data, error } = await query.maybeSingle();

            if (error) {
                console.error(`❌ 필터 설정 로드 실패 (${filterKey}):`, error);
                return null;
            }
            return data;
        }
    }

    /**
     * 현재 프리셋의 모든 필터 설정 로드
     */
    async loadAllSettings(targetRound = null) {
        if (!this.currentPresetId) {
            await this.ensureDefaultPreset();
        }
        if (!this.currentPresetId) return {};

        let query = this.supabase
            .from('filter_settings')
            .select(`
                *,
                filter_definitions (
                    filter_key,
                    filter_name,
                    filter_type,
                    default_settings
                )
            `)
            .eq('preset_id', this.currentPresetId);

        if (targetRound) {
            query = query.or(`target_round.eq.${targetRound},target_round.is.null`);
        }

        const { data, error } = await query;

        if (error) {
            console.error('❌ 전체 필터 설정 로드 실패:', error);
            return {};
        }

        // filter_key를 키로 하는 객체로 변환
        const result = {};

        // [수정] 정렬: null인 항목을 먼저 처리하고, 특정 회차(targetRound)인 항목을 나중에 처리하여 덮어쓰기 (우선순위 부여)
        const sortedData = [...(data || [])].sort((a, b) => {
            if (a.target_round === null && b.target_round !== null) return -1;
            if (a.target_round !== null && b.target_round === null) return 1;
            return 0;
        });

        sortedData.forEach(item => {
            if (item.filter_definitions) {
                result[item.filter_definitions.filter_key] = {
                    settings: item.settings,
                    enabled: item.enabled,
                    target_round: item.target_round,
                    updated_at: item.updated_at
                };
            }
        });

        return result;
    }

    /**
     * 활성화된 필터만 조회
     */
    async getActiveFilters(targetRound = null) {
        const allSettings = await this.loadAllSettings(targetRound);
        const active = {};

        Object.entries(allSettings).forEach(([key, value]) => {
            if (value.enabled) {
                active[key] = value;
            }
        });

        return active;
    }

    // ==========================================
    // localStorage 마이그레이션
    // ==========================================

    /**
     * localStorage → DB 마이그레이션 (최초 1회)
     */
    async migrateFromLocalStorage() {
        const migrationKey = `lotto_filter_migrated_${this.userId}`;

        // 이미 마이그레이션 완료된 경우 스킵
        if (localStorage.getItem(migrationKey)) {
            return { migrated: 0, skipped: true };
        }

        // localStorage 키 → DB filter_key 매핑 (전체 22개)
        const keyMapping = {
            'ac_filter': 'ac_value',
            'total_sum_filter': 'total_sum',
            'tail_sum_filter': 'tail_sum',
            'last_digit_sum': 'tail_sum',
            'tail_digit_filter': 'tail_digit_patterns',  // 끝수 통합 패턴 키로 마이그레이션
            'carryover_filter': 'carryover_count',
            'odd_even_filter': 'odd_even_pattern',
            'low_high_filter': 'high_low_pattern',
            'prime_filter': 'prime_number_patterns',
            'composite_filter': 'composite_count',
            'square_filter': 'square_number_patterns',
            'twin_filter': 'twin_number_patterns',
            'consecutive_filter': 'consecutive_count',
            'hot_cold_filter': 'hot_cold_10',
            'missing_filter': 'long_term_miss',
            'missing_period': 'long_term_miss', // [추가] 분석 페이지 키 추가
            'missGroupFilters': 'missing_custom_filter', // [추가] 커스텀 미출현 그룹 마이그레이션
            'multiple_filter': 'multiple_3_count',  // 배수는 별도 처리 필요
            'neighbor_filter': 'neighbor_number_patterns',
            'number_range_filter': 'number_range_patterns', // Changed from zone_3_pattern
            'stats_by_number_filter': null,  // 통계용, 필터 아님
            // 새로 추가된 필터
            'lotto_paper_filter': 'lotto_paper_pattern',
            'gung_filter': 'magic_square_pattern',
            'triangular_filter': 'triangular_number_patterns',
            'regression_patterns': 'regression_analysis'
        };

        let migratedCount = 0;

        for (const [oldKey, newKey] of Object.entries(keyMapping)) {
            if (!newKey) continue;  // null이면 스킵

            const stored = localStorage.getItem(oldKey);
            if (!stored) continue;

            try {
                const data = JSON.parse(stored);

                // enabled와 나머지 settings 분리
                const { enabled, ...settings } = data;

                await this.saveSetting(newKey, settings, enabled || false);
                migratedCount++;

            } catch (e) {
                console.warn(`⚠️ 마이그레이션 실패 (${oldKey}):`, e);
            }
        }

        // 마이그레이션 완료 플래그
        if (migratedCount > 0) {
            localStorage.setItem(migrationKey, new Date().toISOString());
            console.log(`✅ ${migratedCount}개 필터 마이그레이션 완료`);
        }

        // ── tail_digit_patterns 전용 보정 마이그레이션 (1회) ──────────────
        // 기존 사용자가 이미 마이그레이션 완료했더라도 tail_digit_filter 데이터를
        // 올바른 키(tail_digit_patterns)로 저장하지 못한 경우를 보정합니다.
        const tailFixKey = `lotto_tail_digit_fixed_${this.userId}`;
        if (!localStorage.getItem(tailFixKey)) {
            const tailOldData = localStorage.getItem('tail_digit_filter');
            if (tailOldData) {
                try {
                    const parsed = JSON.parse(tailOldData);
                    // tail_digit_patterns DB에 아직 데이터가 없으면 저장
                    const existing = await this.loadSetting('tail_digit_patterns');
                    if (!existing) {
                        const { enabled, ...settings } = parsed;
                        await this.saveSetting('tail_digit_patterns', settings, enabled || false);
                        console.log('✅ tail_digit_filter → tail_digit_patterns 보정 마이그레이션 완료');
                    }
                } catch (e) {
                    console.warn('⚠️ tail_digit 보정 마이그레이션 실패:', e);
                }
            }
            localStorage.setItem(tailFixKey, new Date().toISOString());
        }

        return { migrated: migratedCount, skipped: false };
    }

    // ==========================================
    // AI 분석용 데이터 포맷팅
    // ==========================================

    /**
     * 활성화된 필터를 AI 프롬프트용 텍스트로 변환
     */
    async formatFiltersForAI(targetRound = null) {
        const activeFilters = await this.getActiveFilters(targetRound);
        const definitions = await this.loadDefinitions();

        if (Object.keys(activeFilters).length === 0) {
            return '현재 적용된 필터가 없습니다.';
        }

        const lines = [];

        for (const [filterKey, filterData] of Object.entries(activeFilters)) {
            const def = definitions.find(d => d.filter_key === filterKey);
            if (!def) continue;

            const formatted = this._formatSingleFilterForAI(def, filterData.settings);
            lines.push(formatted);
        }

        return `[현재 적용된 필터 전략]\n${lines.join('\n')}`;
    }

    _formatSingleFilterForAI(definition, settings) {
        const name = definition.filter_name;
        const type = definition.filter_type;

        switch (type) {
            case 'discrete_select':
                if (settings.selectedValues && settings.selectedValues.length > 0) {
                    return `- ${name}: ${settings.selectedValues.join(', ')} 선택`;
                } else if (settings.min !== undefined && settings.max !== undefined) {
                    return `- ${name}: ${settings.min}~${settings.max} 범위`;
                }
                return `- ${name}: 설정됨`;

            case 'range':
                if (settings.useDiscreteSelection && settings.selectedValues && settings.selectedValues.length > 0) {
                    return `- ${name}: ${settings.selectedValues.join(', ')} 선택 (불연속)`;
                }
                return `- ${name}: ${settings.min}~${settings.max} 범위`;

            case 'pattern_select':
                if (settings.selectedPatterns && settings.selectedPatterns.length > 0) {
                    return `- ${name}: ${settings.selectedPatterns.join(', ')} 패턴`;
                }
                return `- ${name}: 패턴 설정됨`;

            case 'number_selector':
                if (settings.numbers && settings.numbers.length > 0) {
                    return `- ${name}: ${settings.numbers.join(', ')}`;
                }
                return `- ${name}: 미설정`;

            default:
                return `- ${name}: ${JSON.stringify(settings)}`;
        }
    }

    // ==========================================
    // 분석 이력 (analysis_history)
    // ==========================================

    /**
     * 분석 이력 저장 (스냅샷 포함)
     */
    async saveAnalysisHistory(targetRound, analysisType, resultSummary = null, notes = null) {
        if (!this.userId || !this.currentPresetId) return null;

        // 현재 활성 필터 스냅샷 생성
        const activeFilters = await this.getActiveFilters(targetRound);
        const definitions = await this.loadDefinitions();

        const filterSnapshot = Object.entries(activeFilters).map(([key, data]) => {
            const def = definitions.find(d => d.filter_key === key);
            return {
                filter_key: key,
                filter_name: (def && def.filter_name) || key,
                settings: data.settings,
                enabled: data.enabled
            };
        });

        // 프리셋 이름 조회
        const { data: preset } = await this.supabase
            .from('user_filter_presets')
            .select('preset_name')
            .eq('id', this.currentPresetId)
            .single();

        const { data, error } = await this.supabase
            .from('analysis_history')
            .insert({
                user_id: this.userId,
                target_round: targetRound,
                analysis_type: analysisType,
                preset_id: this.currentPresetId,
                preset_name: preset && preset.preset_name,
                filter_snapshot: filterSnapshot,
                result_summary: resultSummary,
                notes
            })
            .select()
            .single();

        if (error) {
            console.error('❌ 분석 이력 저장 실패:', error);
            return null;
        }

        return data;
    }

    /**
     * 분석 이력 조회
     */
    async getAnalysisHistory(targetRound = null, limit = 20) {
        if (!this.userId) return [];

        let query = this.supabase
            .from('analysis_history')
            .select('*')
            .eq('user_id', this.userId)
            .order('created_at', { ascending: false })
            .limit(limit);

        if (targetRound) {
            query = query.eq('target_round', targetRound);
        }

        const { data, error } = await query;

        if (error) {
            console.error('❌ 분석 이력 조회 실패:', error);
            return [];
        }

        return data || [];
    }

    /**
     * 과거 분석 설정 복원
     */
    async restoreFromHistory(historyId) {
        const { data: history, error } = await this.supabase
            .from('analysis_history')
            .select('filter_snapshot')
            .eq('id', historyId)
            .single();

        if (error || !history) {
            console.error('❌ 이력 조회 실패:', error);
            return false;
        }

        // 스냅샷의 각 필터 설정 복원
        for (const item of history.filter_snapshot) {
            await this.saveSetting(
                item.filter_key,
                item.settings,
                item.enabled
            );
        }

        console.log('✅ 분석 설정 복원 완료');
        return true;
    }

    // ==========================================
    // 커스텀분석 필터 (ai_custom_analyses)
    // ==========================================

    /**
     * 활성화된 커스텀분석 필터 조회
     */
    async getCustomAnalysisFilters() {
        let query = this.supabase
            .from('ai_custom_analyses')
            .select('id, title, target_numbers, filter_config')
            .not('filter_config', 'is', null)
            .is('target_round', null); // [추가] 마스터 행만 조회 (회차별 스냅샷 제외)
        if (this.userId) query = query.eq('user_id', this.userId);
        const { data, error } = await query;

        if (error) {
            console.error('❌ 커스텀분석 필터 조회 실패:', error);
            return [];
        }

        // enabled가 true인 것만 필터링
        return (data || []).filter(item => item.filter_config && item.filter_config.enabled === true);
    }

    /**
     * 조합을 커스텀분석 필터로 검증
     * @param {number[]} combination - 검증할 6개 번호 조합
     * @param {Array} customFilters - 커스텀분석 필터 배열 (미리 조회된 것)
     * @returns {Object} { valid: boolean, failedFilter?: string, matchCount?: number, expected?: string }
     */
    validateCombinationWithCustomFilters(combination, customFilters) {
        if (!customFilters || customFilters.length === 0) {
            return { valid: true };
        }

        for (const filter of customFilters) {
            const targetNumbers = filter.target_numbers || [];
            const matchCount = combination.filter(n => targetNumbers.includes(n)).length;
            const { min = 0, max = 6 } = filter.filter_config || {};

            if (matchCount < min || matchCount > max) {
                return {
                    valid: false,
                    failedFilter: filter.title,
                    matchCount,
                    expected: `${min}~${max}개`
                };
            }
        }

        return { valid: true };
    }

    /**
     * 단일 조합 검증 (필터 조회 포함)
     */
    async validateCombination(combination) {
        const customFilters = await this.getCustomAnalysisFilters();
        return this.validateCombinationWithCustomFilters(combination, customFilters);
    }

    /**
     * 커스텀분석 필터 요약 텍스트 생성 (AI용)
     */
    async formatCustomFiltersForAI() {
        const filters = await this.getCustomAnalysisFilters();

        if (filters.length === 0) {
            return '현재 적용된 커스텀분석 필터가 없습니다.';
        }

        const lines = filters.map(f => {
            const { min, max } = f.filter_config;
            const numbersPreview = f.target_numbers.slice(0, 5).join(', ');
            const more = f.target_numbers.length > 5 ? ` 외 ${f.target_numbers.length - 5}개` : '';
            return `- ${f.title}: [${numbersPreview}${more}] → ${min}~${max}개 포함 필터`;
        });

        return `[커스텀분석 필터 (${filters.length}개 활성)]\n${lines.join('\n')}`;
    }

    // ==========================================
    // [Phase 4] AI 필터 범위 로드 (Single Source of Truth)
    // ==========================================

    /**
     * deep_analysis_history.analysis_data.range_analysis 에서 AI 추천 필터 범위 조회.
     * 별도 테이블 없음 — 기존 JSONB 컬럼 재활용.
     * @param {number|null} roundNumber - 특정 회차 지정 (null = 최신)
     * @returns {object|null} { total_sum_min, total_sum_max, ac_value_min, ac_value_max, ... , _round, _source } 또는 null
     */
    async loadAIRanges(roundNumber = null) {
        // 5분 캐시 (동일 회차 재조회 방지)
        const cacheKey = `_aiRanges_${roundNumber || 'latest'}`;
        const cached = this[cacheKey];
        if (cached && (Date.now() - cached._ts < 5 * 60 * 1000)) return cached;

        try {
            let query = this.supabase
                .from('deep_analysis_history')
                .select('target_round, analysis_data')
                .order('target_round', { ascending: false })
                .limit(1);

            if (roundNumber) query = query.eq('target_round', roundNumber);

            const { data, error } = await query.maybeSingle();
            if (error || !data) {
                console.warn('[FilterService] deep_analysis_history 데이터 없음');
                return null;
            }

            const analysis = typeof data.analysis_data === 'string'
                ? JSON.parse(data.analysis_data)
                : data.analysis_data;

            const ra = analysis?.range_analysis || analysis?.analysis?.range_analysis;
            if (!ra) {
                console.warn('[FilterService] range_analysis 필드 없음');
                return null;
            }

            // range_analysis 키 → [min, max] 파싱 헬퍼
            const parseRange = (val) => {
                if (!val) return [null, null];
                if (Array.isArray(val)) return [Number(val[0]), Number(val[1])];
                if (typeof val === 'string' && val.includes('~')) {
                    const p = val.split('~');
                    return [Number(p[0]), Number(p[1])];
                }
                return [null, null];
            };
            const r = (key) => parseRange(ra[key]?.range);

            // filter_dashboard.js AI_KEY_MAP 호환 평탄화
            const [sumMin, sumMax]         = r('sum');
            const [acMin, acMax]           = r('ac');
            const [tailMin, tailMax]       = r('tail_sum');
            const [oddMin, oddMax]         = r('odd');
            const [highMin, highMax]       = r('high');
            const [consMin, consMax]       = r('consecutive');
            const [primeMin, primeMax]     = r('prime');
            const [compMin, compMax]       = r('composite');
            const [squareMin, squareMax]   = r('square');
            const [triMin, triMax]         = r('triangular');
            const [twinMin, twinMax]       = r('twin');
            const [mul3Min, mul3Max]       = r('mul3');
            const [mul7Min, mul7Max]       = r('mul7');
            const [mul8Min, mul8Max]       = r('mul8');
            const [misMin, misMax]         = r('missing');
            const [nbMin, nbMax]           = r('neighbor');

            const result = {
                // 표준 키 _min/_max (filter_definitions.filter_key prefix 일치)
                total_sum_min: sumMin,                       total_sum_max: sumMax,
                ac_value_min: acMin,                         ac_value_max: acMax,
                tail_sum_min: tailMin,                       tail_sum_max: tailMax,
                odd_even_pattern_min: oddMin,                odd_even_pattern_max: oddMax,
                high_low_pattern_min: highMin,               high_low_pattern_max: highMax,
                consecutive_count_min: consMin,              consecutive_count_max: consMax,
                prime_number_patterns_min: primeMin,         prime_number_patterns_max: primeMax,
                composite_count_min: compMin,                composite_count_max: compMax,
                square_number_patterns_min: squareMin,       square_number_patterns_max: squareMax,
                triangular_number_patterns_min: triMin,      triangular_number_patterns_max: triMax,
                twin_number_patterns_min: twinMin,           twin_number_patterns_max: twinMax,
                multiple_3_count_min: mul3Min,               multiple_3_count_max: mul3Max,
                multiple_7_count_min: mul7Min,               multiple_7_count_max: mul7Max,
                multiple_8_count_min: mul8Min,               multiple_8_count_max: mul8Max,
                missing_period_min: misMin,                  missing_period_max: misMax,
                neighbor_number_patterns_min: nbMin,         neighbor_number_patterns_max: nbMax,
                // 메타데이터
                _round: data.target_round,
                _source: 'ensemble',
                _ts: Date.now()
            };

            this[cacheKey] = result;
            console.log(`[FilterService] AI 범위 로드 완료 (${data.target_round}회차, 앙상블 기반)`);
            return result;
        } catch (e) {
            console.warn('[FilterService] loadAIRanges 실패:', e);
            return null;
        }
    }

    /**
     * AI 추천 범위 뱃지 HTML 생성 헬퍼.
     * @param {number} min
     * @param {number} max
     * @returns {string} HTML 뱃지
     */
    static aiRangeBadge(min, max) {
        if (min == null || max == null) return '';
        return `<span class="inline-flex items-center gap-0.5 px-2 py-0.5 rounded-full text-[10px] font-black bg-indigo-50 text-indigo-600 ring-1 ring-indigo-200 cursor-pointer ai-range-badge" data-min="${min}" data-max="${max}" title="클릭하면 AI 추천값 적용">AI ${min}~${max}</span>`;
    }
}

// ==========================================
// 전역 인스턴스 및 Utils 확장
// ==========================================

// 전역 FilterService 인스턴스
window.filterService = null;

let _isFilterServiceInitializing = false;

/**
 * FilterService 초기화 (페이지 로드 시 호출)
 */
async function initFilterService() {
    if (!window.supabaseClient) {
        console.warn('⚠️ Supabase 클라이언트가 없습니다');
        return null;
    }

    if (window.filterService && window.filterService.initialized) {
        return window.filterService;
    }

    if (_isFilterServiceInitializing) {
        // 이미 다른 곳에서 초기화 중이면 대기
        return new Promise(resolve => {
            const checkT = setInterval(() => {
                if (window.filterService && window.filterService.initialized) {
                    clearInterval(checkT);
                    resolve(window.filterService);
                }
            }, 100);
        });
    }

    _isFilterServiceInitializing = true;
    try {
        if (!window.filterService) {
            window.filterService = new FilterService(window.supabaseClient);
        }
        await window.filterService.initialize();
    } finally {
        _isFilterServiceInitializing = false;
    }

    return window.filterService;
}

/**
 * Utils.saveFilter 확장 (DB 우선, fallback으로 localStorage)
 */
if (window.Utils) {
    // Utils.saveFilter/loadFilter overrides removed. Managed in common_v2.js.
}

// 모듈 내보내기
window.FilterService = FilterService;
window.initFilterService = initFilterService;

console.log('✅ FilterService.js 로드 완료');