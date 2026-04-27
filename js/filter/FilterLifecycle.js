/**
 * ============================================================
 * FilterLifecycle.js
 * 필터 생명주기 이벤트 중앙 관리
 * ============================================================
 *
 * 4가지 이벤트:
 *  - LOGOUT        : 로그아웃 → 모든 필터 비활성 + 수동플래그 제거
 *  - LOGIN         : 로그인  → DB 마지막 저장값 반영 신호
 *  - NEW_ROUND     : 신규 회차 → 수동플래그 제거 + recent10 자동적용 신호
 *  - MANUAL_OVERRIDE: 사용자 수동 변경 → recent10 비활성 신호
 *
 * 사용법 (각 분석 페이지):
 *   window.addEventListener('filterLifecycle', (e) => {
 *     const { type, data } = e.detail;
 *     if (type === 'NEW_ROUND')      { ...최근10회차 자동적용... }
 *     if (type === 'MANUAL_OVERRIDE') { isRecentTenFilter = false; ... }
 *     if (type === 'LOGOUT')         { ...UI 초기화... }
 *   });
 *
 * FilterRuleEngine.setValue(key, val, { source:'manual' }) 호출 시
 * 자동으로 MANUAL_OVERRIDE가 발화됩니다.
 *
 * basket.js의 checkAndClearIfNewRound()가 새 회차 감지 시
 * FilterLifecycle.onNewRound(prev, next) 를 호출합니다.
 * ============================================================
 */

(function () {
    'use strict';

    const LIFECYCLE_EVENT = 'filterLifecycle';

    // ── 이벤트 발화 ────────────────────────────────────────────
    function emit(type, data) {
        window.dispatchEvent(new CustomEvent(LIFECYCLE_EVENT, {
            detail: { type, data: data || {}, timestamp: Date.now() }
        }));
        console.log(`[FilterLifecycle] ▶ ${type}`, data || '');
    }

    // ── localStorage: _isManual / _is_manual 플래그 전체 제거 ──
    function clearManualFlags() {
        const toRemove = [];
        for (let i = 0; i < localStorage.length; i++) {
            const k = localStorage.key(i);
            if (k && (k.endsWith('_isManual') || k.endsWith('_is_manual'))) {
                toRemove.push(k);
            }
        }
        toRemove.forEach(k => localStorage.removeItem(k));
        if (toRemove.length) {
            console.log(`[FilterLifecycle] 수동 플래그 ${toRemove.length}개 제거:`, toRemove);
        }
    }

    // ── LOGOUT ─────────────────────────────────────────────────
    // auth.js _resetAllFilterStorage() 호출 직후 연결됨
    function onLogout() {
        clearManualFlags();
        emit('LOGOUT');
    }

    // ── LOGIN ──────────────────────────────────────────────────
    // auth.js SIGNED_IN 이벤트 시 연결됨
    function onLogin(user) {
        emit('LOGIN', { userId: user ? user.id : null });
    }

    // ── NEW_ROUND ──────────────────────────────────────────────
    // basket.js checkAndClearIfNewRound() 에서 새 회차 감지 시 호출
    function onNewRound(prevRound, newRound) {
        clearManualFlags();
        emit('NEW_ROUND', { prevRound, newRound });
    }

    // ── MANUAL_OVERRIDE ────────────────────────────────────────
    // FilterRuleEngine.setValue(key, val, { source:'manual' }) 에서 자동 호출
    // 또는 페이지에서 직접 호출 가능
    function onManualOverride(filterKey) {
        emit('MANUAL_OVERRIDE', { key: filterKey });
    }

    // ── auth.js onAuthStateChange 후킹 ─────────────────────────
    // auth.js 가 이미 onAuthStateChange 를 등록하고 있으므로
    // FilterLifecycle 도 별도로 구독하여 이벤트를 발화한다.
    // (Supabase는 여러 리스너 동시 지원)
    function _hookAuthStateChange() {
        if (!window.supabaseClient) {
            setTimeout(_hookAuthStateChange, 200);
            return;
        }
        window.supabaseClient.auth.onAuthStateChange((event, session) => {
            if (event === 'SIGNED_OUT') {
                onLogout();
            } else if (event === 'SIGNED_IN') {
                onLogin(session && session.user);
            }
        });
        console.log('[FilterLifecycle] auth 후킹 완료');
    }
    _hookAuthStateChange();

    // ── 공개 API ───────────────────────────────────────────────
    window.FilterLifecycle = {
        /** 이벤트 직접 발화 (테스트·특수 케이스용) */
        emit,
        /** 로그아웃 훅 — auth.js에서 호출 */
        onLogout,
        /** 로그인 훅 — auth.js에서 호출 */
        onLogin,
        /** 신규 회차 훅 — basket.js에서 호출 */
        onNewRound,
        /** 수동 변경 훅 — FilterRuleEngine / 각 페이지에서 호출 */
        onManualOverride,
        /** 이벤트 이름 (addEventListener 에 직접 사용) */
        EVENT: LIFECYCLE_EVENT,
    };

    console.log('✅ FilterLifecycle.js 로드 완료');
})();
