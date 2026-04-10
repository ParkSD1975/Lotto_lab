/**
 * auth.js - Google OAuth 로그인/로그아웃
 * Supabase Auth 기반
 */

(function () {
    // supabaseClient가 아직 없으면 대기
    function waitForClient(cb) {
        if (window.supabaseClient) return cb();
        const t = setInterval(() => {
            if (window.supabaseClient) { clearInterval(t); cb(); }
        }, 50);
    }

    // ==========================================
    // 구글 로그인
    // ==========================================
    window.signInWithGoogle = async function () {
        const { error } = await window.supabaseClient.auth.signInWithOAuth({
            provider: 'google',
            options: {
                redirectTo: window.location.origin + '/' + window.location.pathname.split('/').pop()
            }
        });
        if (error) {
            console.error('구글 로그인 실패:', error.message);
            alert('로그인 중 오류가 발생했습니다: ' + error.message);
        }
    };

    // ==========================================
    // 로그아웃
    // ==========================================
    window.signOut = async function () {
        // [수정] 로그아웃 전에 현재 유저 ID를 백업 → 메뉴 순서 키 보존을 위해
        const currentUserId = window.filterService?.userId
            || (await window.supabaseClient.auth.getUser()).data?.user?.id
            || null;
        if (currentUserId) {
            // 마지막 로그인 유저 ID를 저장해두면, 재로그인 시 같은 키로 순서를 복원할 수 있음
            localStorage.setItem('_lastLoginUserId', currentUserId);
        }

        const { error } = await window.supabaseClient.auth.signOut();
        if (error) {
            console.error('로그아웃 실패:', error.message);
        } else {
            updateAuthUI(null);
            // FilterService 상태 초기화
            if (window.filterService) {
                window.filterService.initialized = false;
                window.filterService.userId = null;
                window.filterService.currentPresetId = null;
            }
            // 모든 필터값 초기화 (0-0, 미적용 상태)
            _resetAllFilterStorage();
        }
    };

    /**
     * 로그아웃 시 localStorage의 모든 필터값을 0-0, 비활성화 상태로 초기화
     */
    function _resetAllFilterStorage() {
        // [수정] 텔레그램 채팅 ID 백업 (로그아웃 시에도 유지하기 위함)
        const savedTgChatId = localStorage.getItem('telegram_chat_id');

        const disabledFilter = JSON.stringify({ enabled: false, _ts: Date.now() });
        const disabledCustom  = JSON.stringify({ min: 0, max: 0, enabled: false });

        // 기초 분석 필터 키 목록
        const foundationKeys = [
            'total_sum', 'last_digit_sum', 'ac_value', 'odd_even_pattern', 'high_low_pattern',
            'prime_number_patterns', 'composite_count', 'square_number_patterns',
            'triangular_number_patterns', 'twin_number_patterns', 'neighbor_number_patterns',
            'carryover_count', 'consecutive_count', 'multiple_3_count', 'number_range_patterns',
            'magic_square_pattern', 'lotto_paper_pattern', 'hot_cold_5', 'hot_cold_10',
            'hot_cold_15', 'hot_cold_20', 'missing_period', 'missing_custom_filter',
            'regression_analysis', 'tail_digit_patterns'
        ];
        foundationKeys.forEach(k => {
            localStorage.setItem(k, disabledFilter);
            localStorage.setItem(k + '_filter', disabledFilter);
        });

        // custom_filter_* 키들을 0-0, 비활성화로 초기화
        const keysToReset = [];
        for (let i = 0; i < localStorage.length; i++) {
            const k = localStorage.key(i);
            if (k && k.startsWith('custom_filter_')) keysToReset.push(k);
        }
        keysToReset.forEach(k => localStorage.setItem(k, disabledCustom));

        // [추가] 백업한 텔레그램 채팅 ID 복구
        if (savedTgChatId) {
            localStorage.setItem('telegram_chat_id', savedTgChatId);
        }

        // 필터 대시보드 리렌더링 (현재 페이지가 filter.html인 경우)
        if (window.FilterDashboard && window.FilterDashboard.init) {
            window.FilterDashboard.init().catch(() => {});
        }

        console.log('🔒 로그아웃: 전체 필터 초기화 완료');
    }

    // ==========================================
    // UI 업데이트 — #acct-login-area만 교체 (패널 구조 유지)
    // ==========================================
    function updateAuthUI(user) {
        // ① 트리거 버튼 아이콘 업데이트
        const trigger = document.getElementById('acct-trigger');
        if (trigger) {
            if (user) {
                const avatar = user.user_metadata?.avatar_url || '';
                const name   = user.user_metadata?.full_name || user.email || '사용자';
                trigger.innerHTML = avatar
                    ? `<img src="${avatar}" alt="${name}" class="w-8 h-8 rounded-full object-cover border-2 border-blue-300" title="${name}">`
                    : `<span class="material-symbols-outlined text-[24px] text-blue-500" title="${name}">account_circle</span>`;
            } else {
                trigger.innerHTML = `<span class="material-symbols-outlined text-[24px]">account_circle</span>`;
            }
        }

        // ② 패널 내부 로그인 영역만 교체
        const loginArea = document.getElementById('acct-login-area');
        if (!loginArea) return;

        if (user) {
            const avatar = user.user_metadata?.avatar_url || '';
            const name   = user.user_metadata?.full_name || user.email || '사용자';
            loginArea.innerHTML = `
                <div class="flex items-center gap-3 mb-2">
                    ${avatar ? `<img src="${avatar}" alt="${name}" class="w-9 h-9 rounded-full object-cover border-2 border-blue-200">` : `<span class="material-symbols-outlined text-blue-400 text-[32px]">account_circle</span>`}
                    <div class="min-w-0">
                        <p class="text-[12px] font-bold text-slate-800 truncate">${name}</p>
                        <p class="text-[11px] text-slate-400 truncate">${user.email}</p>
                    </div>
                </div>
                <button onclick="signOut()"
                    class="w-full flex items-center justify-center gap-1.5 px-3 py-1.5 text-[12px] font-semibold text-rose-500 bg-rose-50 hover:bg-rose-100 rounded-xl transition-all">
                    <span class="material-symbols-outlined text-[14px]">logout</span>로그아웃
                </button>`;
        } else {
            loginArea.innerHTML = `
                <button onclick="signInWithGoogle()"
                    class="w-full flex items-center justify-center gap-2 px-3 py-2 bg-white border border-slate-200 rounded-xl text-[12px] font-semibold text-slate-700 hover:border-blue-400 hover:text-blue-600 transition-all">
                    <svg width="16" height="16" viewBox="0 0 48 48"><path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.08 17.74 9.5 24 9.5z"/><path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/><path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/><path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.18 1.48-4.97 2.36-8.16 2.36-6.26 0-11.57-3.59-13.46-8.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/></svg>
                    Google 계정으로 로그인
                </button>`;
        }
    }

    // ==========================================
    // 초기화 (페이지 로드 시)
    // ==========================================
    waitForClient(async function () {
        // 현재 세션 확인
        const { data: { user } } = await window.supabaseClient.auth.getUser();
        updateAuthUI(user);

        // 로그인 상태가 있으면 FilterService 초기화
        if (user && window.initFilterService && !window.filterService?.initialized) {
            await window.initFilterService();
        }

        // 로그인 상태 변경 감지
        window.supabaseClient.auth.onAuthStateChange(async (event, session) => {
            const currentUser = session?.user || null;
            updateAuthUI(currentUser);

            if (event === 'SIGNED_IN' && currentUser) {
                console.log('✅ 로그인됨:', currentUser.email);
                // FilterService 초기화 (필터 DB 저장 활성화)
                if (window.initFilterService) {
                    await window.initFilterService();
                }
            } else if (event === 'SIGNED_OUT') {
                console.log('👋 로그아웃됨');
                _resetAllFilterStorage();
            }
        });

        // 헤더가 동적으로 로드된 경우 재실행
        document.addEventListener('gnbLoaded', async function () {
            const { data: { user: u } } = await window.supabaseClient.auth.getUser();
            updateAuthUI(u);
        });
    });

})();
