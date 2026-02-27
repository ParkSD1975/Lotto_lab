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
        }
    };

    // ==========================================
    // UI 업데이트
    // ==========================================
    function updateAuthUI(user) {
        const loginBtn = document.getElementById('loginBtn');
        if (!loginBtn) return;

        if (user) {
            const avatar = user.user_metadata?.avatar_url || '';
            const name = user.user_metadata?.full_name || user.email || '사용자';

            loginBtn.innerHTML = `
                <div class="relative group">
                    <button class="flex items-center gap-1.5 rounded-full focus:outline-none" title="${name}">
                        ${avatar
                    ? `<img src="${avatar}" alt="${name}" class="w-8 h-8 rounded-full object-cover border-2 border-indigo-300">`
                    : `<span class="material-symbols-outlined text-[24px] text-indigo-500">account_circle</span>`
                }
                    </button>
                    <!-- 드롭다운 -->
                    <div class="hidden group-hover:block absolute right-0 top-full pt-1.5 w-52 z-[9999] origin-top-right">
                        <div class="bg-white rounded-xl border border-slate-100 shadow-xl py-1">
                            <div class="px-4 py-2.5 border-b border-slate-100">
                                <p class="text-[12px] font-bold text-slate-800 truncate">${name}</p>
                                <p class="text-[11px] text-slate-400 truncate">${user.email}</p>
                            </div>
                            <button onclick="signOut()"
                                class="w-full text-left flex items-center gap-2 px-4 py-2.5 text-[13px] text-slate-600 hover:bg-slate-50 hover:text-rose-500 transition-colors">
                                <span class="material-symbols-outlined text-[16px]">logout</span>
                                로그아웃
                            </button>
                        </div>
                    </div>
                </div>
            `;
        } else {
            loginBtn.innerHTML = `
                <button onclick="signInWithGoogle()"
                    title="구글로 로그인"
                    class="flex items-center justify-center w-9 h-9 rounded-full text-slate-400 hover:text-[#4c1d95] transition-colors">
                    <span class="material-symbols-outlined text-[24px]">account_circle</span>
                </button>
            `;
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
            }
        });

        // 헤더가 동적으로 로드된 경우 재실행
        document.addEventListener('gnbLoaded', async function () {
            const { data: { user: u } } = await window.supabaseClient.auth.getUser();
            updateAuthUI(u);
        });
    });

})();
