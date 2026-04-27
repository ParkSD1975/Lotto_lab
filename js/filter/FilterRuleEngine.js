/**
 * ============================================================
 * FilterRuleEngine.js
 * 필터 단일 진입점 API
 * ============================================================
 *
 * 역할:
 *  - 모든 필터 읽기/쓰기의 단일 통로 (Utils.saveFilter/loadFilter 래핑)
 *  - source:'manual' 저장 시 FilterLifecycle.onManualOverride 자동 발화
 *  - 크로스탭 StorageEvent 수신 시 'change' 이벤트 발화
 *  - FilterLifecycle 이벤트를 FilterEngine.on('lifecycle:*') 으로 재발화
 *  - 조합 저장용 snapshot / restore
 *
 * 사용법 (분석 페이지 어댑터):
 *
 *   // 1. 필터 값 읽기 (동기)
 *   const val = FilterEngine.getValue('prime_number_patterns');
 *
 *   // 2. 필터 저장 (시스템 자동)
 *   await FilterEngine.setValue('prime_number_patterns', settings, { enabled: true, source:'system' });
 *
 *   // 3. 사용자 수동 저장 (recent10 비활성 자동 처리)
 *   await FilterEngine.setValue('prime_number_patterns', settings, { source:'manual' });
 *
 *   // 4. UI 동기화 리스너
 *   FilterEngine.on('change', ({ key, settings, enabled, source }) => { ... });
 *
 *   // 5. 생명주기 이벤트
 *   FilterEngine.on('lifecycle:NEW_ROUND',      ({ prevRound, newRound }) => { ... });
 *   FilterEngine.on('lifecycle:MANUAL_OVERRIDE', ({ key }) => { ... });
 *   FilterEngine.on('lifecycle:LOGOUT',         () => { ... });
 *   FilterEngine.on('lifecycle:LOGIN',          ({ userId }) => { ... });
 *
 *   // 6. 수동 플래그만 세울 때 (저장 없이 recent10 비활성만)
 *   FilterEngine.markManual('prime_number_patterns');
 *
 * ============================================================
 */

(function () {
    'use strict';

    // ── 모든 기초 필터 표준 키 목록 ────────────────────────────
    const FILTER_KEYS = [
        'prime_number_patterns',
        'composite_count',
        'hot_cold_5',
        'hot_cold_10',
        'hot_cold_15',
        'hot_cold_20',
        'ac_value',
        'total_sum',
        'last_digit_sum',
        'tail_digit_patterns',
        'odd_even_pattern',
        'high_low_pattern',
        'consecutive_count',
        'multiple_3_count',
        'multiple_7_count',
        'multiple_8_count',
        'missing_period',
        'missing_custom_filter',
        'number_range_patterns',
        'magic_square_pattern',
        'lotto_paper_pattern',
        'neighbor_number_patterns',
        'square_number_patterns',
        'twin_number_patterns',
        'triangular_number_patterns',
        'regression_analysis',
        'carryover_count',
    ];

    // ── 내부 상태 ────────────────────────────────────────────
    let _saving = false;                    // StorageEvent 자기 참조 방지 락
    const _listeners = {};                  // { eventType: [fn, ...] }

    // ── 이벤트 리스너 ────────────────────────────────────────
    function on(event, handler) {
        if (!_listeners[event]) _listeners[event] = [];
        _listeners[event].push(handler);
    }

    function off(event, handler) {
        if (!_listeners[event]) return;
        _listeners[event] = _listeners[event].filter(h => h !== handler);
    }

    function _emit(event, data) {
        (_listeners[event] || []).forEach(fn => {
            try { fn(data); }
            catch (e) { console.error(`[FilterRuleEngine] listener error (${event}):`, e); }
        });
    }

    // ── getValue ─────────────────────────────────────────────
    // localStorage에서 즉시 동기 읽기
    // envelope 구조 { settings, enabled } 또는 raw 모두 처리
    function getValue(key) {
        try {
            const raw = localStorage.getItem(key);
            if (!raw) return null;
            const parsed = JSON.parse(raw);
            if (parsed && parsed.settings !== undefined) {
                return { ...parsed.settings, enabled: parsed.enabled };
            }
            return parsed;
        } catch {
            return null;
        }
    }

    // ── setValue ─────────────────────────────────────────────
    // Utils.saveFilter 래핑 + lifecycle 연동
    // options:
    //   source   : 'manual' | 'system'  (기본: 'system')
    //   enabled  : boolean              (기본: true)
    //   targetRound: number | null      (기본: null)
    async function setValue(key, settings, options) {
        const source      = (options && options.source)      || 'system';
        const enabled     = (options && options.enabled !== undefined) ? options.enabled : true;
        const targetRound = (options && options.targetRound) || null;

        _saving = true;
        try {
            // Utils.saveFilter: localStorage 저장 + DB 저장 + BroadcastChannel
            if (window.Utils && typeof window.Utils.saveFilter === 'function') {
                await window.Utils.saveFilter(key, settings, enabled, targetRound);
            } else {
                // fallback: Utils 미로드 시 localStorage 직접 저장
                const envelope = { settings, enabled, targetRound, _ts: Date.now() };
                localStorage.setItem(key, JSON.stringify(envelope));
            }

            // 'change' 이벤트 발화
            _emit('change', { key, settings, enabled, source });

            // 수동 변경 → MANUAL_OVERRIDE lifecycle 발화
            if (source === 'manual') {
                markManual(key);
            }
        } finally {
            // 다음 tick에 락 해제 (StorageEvent 가 동기 이벤트이므로 즉시 해제하면 누락될 수 있음)
            setTimeout(() => { _saving = false; }, 0);
        }
    }

    // ── markManual ────────────────────────────────────────────
    // 저장 없이 수동 플래그·lifecycle 만 발화
    // (버튼 클릭 → deactivateRecent10 → 이후 setValue 별도 호출 패턴에서 사용)
    function markManual(key) {
        if (window.FilterLifecycle) {
            window.FilterLifecycle.onManualOverride(key);
        } else {
            // FilterLifecycle 미로드 시 직접 발화
            window.dispatchEvent(new CustomEvent('filterLifecycle', {
                detail: { type: 'MANUAL_OVERRIDE', data: { key }, timestamp: Date.now() }
            }));
        }
        _emit('manual', { key });
    }

    // ── snapshot ─────────────────────────────────────────────
    // 현재 모든 필터 + 바스켓 상태를 객체로 반환 (조합 저장용)
    function snapshot() {
        const filters = {};
        FILTER_KEYS.forEach(key => {
            try {
                const raw = localStorage.getItem(key);
                if (!raw) return;
                const parsed = JSON.parse(raw);
                filters[key] = {
                    settings: parsed.settings !== undefined ? parsed.settings : parsed,
                    enabled:  parsed.enabled  !== undefined ? parsed.enabled  : false,
                    _ts:      parsed._ts      || 0,
                };
            } catch {}
        });

        const basket = (window.Basket && typeof window.Basket.get === 'function')
            ? window.Basket.get()
            : { fixed: [], exclude: [] };

        return {
            filters,
            basket: {
                fixed:    basket.fixed   || [],
                excluded: basket.exclude || [],
            },
            savedAt: new Date().toISOString(),
        };
    }

    // ── restore ──────────────────────────────────────────────
    // 스냅샷 전체 복원 (조합 불러오기용)
    async function restore(snap) {
        if (!snap || !snap.filters) {
            console.warn('[FilterRuleEngine] restore: 유효하지 않은 스냅샷');
            return;
        }

        // 필터 복원 (시스템 저장 = recent10 비활성화 안 함)
        for (const [key, data] of Object.entries(snap.filters)) {
            await setValue(key, data.settings, {
                enabled:     data.enabled,
                source:      'system',
                targetRound: null,
            });
        }

        // 바스켓 복원
        if (snap.basket && window.Basket) {
            window.Basket.clear();
            (snap.basket.fixed    || []).forEach(n => window.Basket.addFixed(n));
            (snap.basket.excluded || []).forEach(n => window.Basket.addExclude(n));
        }

        _emit('restored', { snapshot: snap });
        console.log('[FilterRuleEngine] ✅ 스냅샷 복원 완료');
    }

    // ── StorageEvent (크로스탭 sync) ─────────────────────────
    // 다른 탭에서 저장한 필터 변경을 감지 → 'change:sync' 이벤트 발화
    window.addEventListener('storage', function (e) {
        if (_saving) return;                              // 자기 자신이 발화한 이벤트 무시
        if (!e.key || !FILTER_KEYS.includes(e.key)) return;
        if (!e.newValue) return;

        try {
            const parsed = JSON.parse(e.newValue);
            const settings = parsed.settings !== undefined ? parsed.settings : parsed;
            _emit('change', {
                key:      e.key,
                settings,
                enabled:  parsed.enabled,
                source:   'sync',    // 다른 탭에서 온 변경임을 표시
            });
        } catch {}
    });

    // ── BroadcastChannel (크로스탭 sync, 동일 origin 다탭) ───
    if (window._lottoBc) {
        window._lottoBc.addEventListener('message', function (e) {
            if (_saving) return;
            if (!e.data || e.data.type !== 'FILTER_CHANGED') return;
            const { key, value } = e.data;
            if (!FILTER_KEYS.includes(key) || !value) return;
            try {
                const parsed = JSON.parse(value);
                const settings = parsed.settings !== undefined ? parsed.settings : parsed;
                _emit('change', { key, settings, enabled: parsed.enabled, source: 'sync' });
            } catch {}
        });
    }

    // ── FilterLifecycle 이벤트 → FilterEngine.on('lifecycle:*') 재발화 ──
    window.addEventListener('filterLifecycle', function (e) {
        const { type, data } = e.detail;
        _emit('lifecycle:' + type, data);  // e.g. 'lifecycle:NEW_ROUND'
        _emit('lifecycle', { type, data }); // 전체 구독용
    });

    // ── 공개 API ─────────────────────────────────────────────
    window.FilterEngine = {
        /** 동기 읽기 */
        getValue,
        /** 저장 (source:'manual'|'system') */
        setValue,
        /** 저장 없이 수동 플래그·lifecycle만 발화 */
        markManual,
        /** 이벤트 구독 */
        on,
        /** 이벤트 구독 해제 */
        off,
        /** 전체 필터 + 바스켓 스냅샷 */
        snapshot,
        /** 스냅샷 복원 */
        restore,
        /** 표준 필터 키 목록 */
        KEYS: FILTER_KEYS,
    };

    console.log('✅ FilterRuleEngine.js 로드 완료');
})();
