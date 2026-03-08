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
            // 1. 사용자 확인
            const { data: { user } } = await this.supabase.auth.getUser();
            if (!user) {
                console.warn('⚠️ FilterService: 로그인 필요');
                return false;
            }
            this.userId = user.id;

            // 2. 기본 프리셋 확보
            await this.ensureDefaultPreset();

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

        let query = this.supabase
            .from('filter_settings')
            .select('*')
            .eq('preset_id', this.currentPresetId)
            .eq('filter_definition_id', definition.id);

        if (targetRound) {
            query = query.eq('target_round', targetRound);
        } else {
            query = query.is('target_round', null);
        }

        const { data, error } = await query.maybeSingle();

        if (error) {
            console.error(`❌ 필터 설정 로드 실패 (${filterKey}):`, error);
            return null;
        }

        return data;
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
        data?.forEach(item => {
            if (item.filter_definitions) {
                result[item.filter_definitions.filter_key] = {
                    settings: item.settings,
                    enabled: item.enabled,
                    target_round: item.target_round
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
            'tail_sum_filter': 'last_digit_sum',
            'tail_digit_filter': 'tail_digit_patterns',  // 끝수 통합 패턴 키로 마이그레이션
            'carryover_filter': 'carryover_count',
            'odd_even_filter': 'odd_even_pattern',
            'low_high_filter': 'high_low_pattern',
            'prime_filter': 'prime_count',
            'composite_filter': 'composite_count',
            'square_filter': 'square_count',
            'twin_filter': 'twin_count',
            'consecutive_filter': 'consecutive_count',
            'hot_cold_filter': 'hot_cold_10',
            'missing_filter': 'long_term_miss',
            'missing_period': 'long_term_miss', // [추가] 분석 페이지 키 추가
            'missGroupFilters': 'missing_custom_filter', // [추가] 커스텀 미출현 그룹 마이그레이션
            'multiple_filter': 'multiple_3_count',  // 배수는 별도 처리 필요
            'neighbor_filter': 'neighbor_count',
            'number_range_filter': 'number_range_patterns', // Changed from zone_3_pattern
            'stats_by_number_filter': null,  // 통계용, 필터 아님
            // 새로 추가된 필터
            'lotto_paper_filter': 'lotto_paper_pattern',
            'gung_filter': 'magic_square_pattern',
            'triangular_filter': 'triangular_count',
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
                if (settings.selectedValues?.length > 0) {
                    return `- ${name}: ${settings.selectedValues.join(', ')} 선택`;
                } else if (settings.min !== undefined && settings.max !== undefined) {
                    return `- ${name}: ${settings.min}~${settings.max} 범위`;
                }
                return `- ${name}: 설정됨`;

            case 'range':
                if (settings.useDiscreteSelection && settings.selectedValues?.length > 0) {
                    return `- ${name}: ${settings.selectedValues.join(', ')} 선택 (불연속)`;
                }
                return `- ${name}: ${settings.min}~${settings.max} 범위`;

            case 'pattern_select':
                if (settings.selectedPatterns?.length > 0) {
                    return `- ${name}: ${settings.selectedPatterns.join(', ')} 패턴`;
                }
                return `- ${name}: 패턴 설정됨`;

            case 'number_selector':
                if (settings.numbers?.length > 0) {
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
                filter_name: def?.filter_name || key,
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
                preset_name: preset?.preset_name,
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
            .not('filter_config', 'is', null);
        if (this.userId) query = query.eq('user_id', this.userId);
        const { data, error } = await query;

        if (error) {
            console.error('❌ 커스텀분석 필터 조회 실패:', error);
            return [];
        }

        // enabled가 true인 것만 필터링
        return (data || []).filter(item => item.filter_config?.enabled === true);
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

    if (window.filterService?.initialized) {
        return window.filterService;
    }

    if (_isFilterServiceInitializing) {
        // 이미 다른 곳에서 초기화 중이면 대기
        return new Promise(resolve => {
            const checkT = setInterval(() => {
                if (window.filterService?.initialized) {
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
    const originalSaveFilter = window.Utils.saveFilter;
    const originalLoadFilter = window.Utils.loadFilter;

    window.Utils.saveFilter = async function (pageKey, filterData, enabledArg) {
        // [수정] 3개 인자 호출 방식 지원: (key, data, enabled) 또는 (key, {enabled, ...data})
        // missing.html, neighbor_number.html 등은 3번째 인자로 enabled를 별도로 전달함
        let settings = filterData || {};
        let enabled;
        if (enabledArg !== undefined) {
            // 3개 인자 방식: saveFilter('missing_period', data, true)
            enabled = enabledArg;
        } else {
            // 2개 인자 방식: saveFilter('missing_period', { enabled, ...settings })
            const { enabled: _e, ...rest } = filterData || {};
            enabled = _e;
            settings = rest;
        }

        // DB 저장 시도
        if (window.filterService?.initialized) {
            await window.filterService.saveSetting(pageKey, settings, enabled !== false);
        }
        // [핵심] localStorage에도 항상 기록 → 다른 탭의 storage 이벤트 트리거
        try {
            localStorage.setItem(pageKey, JSON.stringify({ ...settings, enabled, _ts: Date.now() }));
        } catch (e) {
            // localStorage 용량 초과 등 예외는 무시
        }
    };

    window.Utils.loadFilter = async function (pageKey) {
        // DB에서 로드 시도
        if (window.filterService?.initialized) {
            const data = await window.filterService.loadSetting(pageKey);
            if (data) {
                return {
                    ...data.settings,
                    enabled: data.enabled
                };
            }
        }
        // fallback: localStorage
        return originalLoadFilter(pageKey);
    };
}

// 모듈 내보내기
window.FilterService = FilterService;
window.initFilterService = initFilterService;

console.log('✅ FilterService.js 로드 완료');