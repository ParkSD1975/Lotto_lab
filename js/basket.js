/**
 * ============================================================
 * basket.js - GNB 고정수 / 제외수 바스켓
 * ============================================================
 * - localStorage 저장 (key: lotto_basket)
 * - FilterService 연동 가능 (필터 페이지와 동일 데이터)
 * - 전역 window.Basket 으로 접근
 */

(function () {
    const STORAGE_KEY = 'lotto_basket';

    // ── 저장/로드 ──────────────────────────────────────────
    function load() {
        try {
            const data = JSON.parse(localStorage.getItem(STORAGE_KEY)) || { fixed: [], exclude: [] };
            if (!data.fixed) data.fixed = [];
            if (!data.exclude) data.exclude = [];
            return data;
        } catch { return { fixed: [], exclude: [] }; }
    }

    // ⚠ DB-first 정책 (2026-05-14): DB가 단일 출처. localStorage는 캐시.
    //   DB 저장 실패 시 사용자에게 명시적 알림 (silent fail 금지).
    async function save(data) {
        // 1) localStorage 즉시 캐시 (UI 반응성)
        localStorage.setItem(STORAGE_KEY, JSON.stringify(data));

        // 2) DB 저장 시도 (filterService 필수)
        if (!window.filterService?.initialized) {
            if (window.BasketUI?.showToast) {
                window.BasketUI.showToast('⚠ 로그인이 필요합니다. 바스켓이 DB에 저장되지 않았습니다.', 'warn');
            }
            console.warn('⚠ Basket: filterService 미초기화 — DB 저장 생략');
            window.dispatchEvent(new CustomEvent('basketChanged', { detail: load() }));
            return;
        }

        try {
            await window.filterService.saveSetting('fixed_numbers',    { numbers: data.fixed },   data.fixed.length > 0);
            await window.filterService.saveSetting('excluded_numbers', { numbers: data.exclude }, data.exclude.length > 0);
            console.log('💾 GNB Basket saved to Supabase');
        } catch (e) {
            console.error('❌ Basket Supabase Save Error:', e);
            if (window.BasketUI?.showToast) {
                window.BasketUI.showToast('❌ 바스켓 DB 저장 실패 — 새로고침 후 다시 시도해주세요', 'warn');
            }
        }
        window.dispatchEvent(new CustomEvent('basketChanged', { detail: load() }));
    }

    // ⚠ DB-first 정책 (2026-05-14): DB가 단일 출처. union 정책 폐기 — DB가 비어 있으면 localStorage도 비움.
    async function syncFromDB() {
        if (!window.filterService?.initialized) return;

        try {
            const fixedData   = await window.filterService.loadSetting('fixed_numbers');
            const excludeData = await window.filterService.loadSetting('excluded_numbers');

            const current = load();
            const dbFixed   = (fixedData   && Array.isArray(fixedData.settings?.numbers))   ? fixedData.settings.numbers   : [];
            const dbExclude = (excludeData && Array.isArray(excludeData.settings?.numbers)) ? excludeData.settings.numbers : [];

            const synced = {
                fixed:   [...dbFixed].sort((a, b) => a - b),
                exclude: [...dbExclude].sort((a, b) => a - b),
                current_round: current.current_round
            };

            localStorage.setItem(STORAGE_KEY, JSON.stringify(synced));
            renderPanel();
            console.log(`🔄 GNB Basket synced from DB (fixed=${synced.fixed.length}, exclude=${synced.exclude.length})`);
        } catch (e) {
            console.error('❌ Basket Sync Error:', e);
        }
    }

    // ── 공개 API ───────────────────────────────────────────
    window.Basket = {
        get() { return load(); },

        addFixed(num) {
            num = parseInt(num);
            if (isNaN(num) || num < 1 || num > 45) return { ok: false, msg: '1~45 범위의 번호를 입력하세요.' };
            const d = load();
            if (d.fixed.includes(num)) return { ok: false, msg: `${num}은 이미 고정수입니다.` };
            if (d.exclude.includes(num)) return { ok: false, msg: `${num}은 제외수입니다. 먼저 제외수에서 삭제하세요.` };
            if (d.fixed.length >= 6) return { ok: false, msg: '고정수는 최대 6개까지 가능합니다.' };
            d.fixed = [...d.fixed, num].sort((a, b) => a - b);
            save(d);
            return { ok: true };
        },

        addExclude(num) {
            num = parseInt(num);
            if (isNaN(num) || num < 1 || num > 45) return { ok: false, msg: '1~45 범위의 번호를 입력하세요.' };
            const d = load();
            if (d.exclude.includes(num)) return { ok: false, msg: `${num}은 이미 제외수입니다.` };
            if (d.fixed.includes(num)) return { ok: false, msg: `${num}은 고정수입니다. 먼저 고정수에서 삭제하세요.` };
            if (d.exclude.length >= 39) return { ok: false, msg: '제외수는 최대 39개까지 가능합니다.' };
            d.exclude = [...d.exclude, num].sort((a, b) => a - b);
            save(d);
            return { ok: true };
        },

        removeFixed(num) {
            const d = load();
            d.fixed = d.fixed.filter(n => n !== parseInt(num));
            save(d);
        },

        removeExclude(num) {
            const d = load();
            d.exclude = d.exclude.filter(n => n !== parseInt(num));
            save(d);
        },

        clear() {
            const d = load();
            save({ fixed: [], exclude: [], current_round: d.current_round });
        },

        clearFixed() {
            const d = load();
            d.fixed = [];
            save(d);
        },

        clearExclude() {
            const d = load();
            d.exclude = [];
            save(d);
        },

        async sync() {
            await syncFromDB();
        },

        async checkNewRound() {
            await checkAndClearIfNewRound();
        }
    };

    // ── 새 회차 감지 및 바스켓 초기화 ───────────────────────
    let isCheckingRound = false;
    let _wasCleared = false; // 새 회차로 인해 초기화됐는지 추적 (syncFromDB 생략용)
    async function checkAndClearIfNewRound() {
        if (isCheckingRound || !window.supabaseClient) return;
        isCheckingRound = true;
        _wasCleared = false;

        try {
            // 가장 최신 회차 번호만 1개 가져오기
            const { data, error } = await window.supabaseClient
                .from('lotto_draws')
                .select('round')
                .order('round', { ascending: false })
                .limit(1);

            if (error) throw error;
            if (!data || data.length === 0) return;

            const latestRound = data[0].round;
            const currentData = load();
            const savedRound = currentData.current_round;

            // 로컬에 이전 회차가 기록되어 있고, 최신 회차보다 작다면 (새 회차가 업데이트 되었다면)
            if (savedRound && savedRound < latestRound) {
                // [2026-05-14 정책 변경] 사용자 명시 지시: "회차 업데이트되면 리셋이야"
                // 기존 fix-80의 "exclude 보존" 정책 폐기 → fixed·exclude 모두 비움
                // 이유: 영구 제외수가 다음 회차 적중 기회를 차단하는 사고 방지
                console.log(`[Basket] 새 회차 감지 (${savedRound} → ${latestRound}). 고정수·제외수 모두 리셋.`);
                save({ fixed: [], exclude: [], current_round: latestRound });
                _wasCleared = true;

                if (window.FilterLifecycle?.onNewRound) {
                    window.FilterLifecycle.onNewRound(savedRound, latestRound);
                }
                if (window.BasketUI?.showToast) {
                    window.BasketUI.showToast('새 회차 업데이트 — 고정수·제외수가 초기화되었습니다.', 'info');
                }
            }
            // 기록된 회차가 없거나, 같거나 크다면 current_round localStorage만 갱신
            // [2026-05-15 critical fix] 이전: save(currentData) 호출 → 빈 {fixed:[], exclude:[]}를
            //   DB로 PUSH해서 사용자 등록 데이터를 무효화하는 결함. 새 창/다른 기기에서 페이지 열 때마다
            //   DB의 excluded_numbers 8개 등을 빈 배열로 덮어쓰는 사고 유발.
            // → localStorage current_round만 직접 갱신. syncFromDB가 DB에서 데이터 회수 담당.
            else if (!savedRound || savedRound !== latestRound) {
                const next = { ...currentData, current_round: latestRound };
                localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
            }
        } catch (e) {
            console.error('[Basket] 최신 회차 확인 실패:', e);
        } finally {
            isCheckingRound = false;
        }
    }

    // ── 볼 색상 헬퍼 ───────────────────────────────────────
    function ballColor(n) {
        if (n <= 10) return '#F7C948';
        if (n <= 20) return '#4a90d9';
        if (n <= 30) return '#E04A4A';
        if (n <= 40) return '#6B7280';
        return '#48B05A';
    }

    // ── 패널 렌더링 ────────────────────────────────────────
    function renderPanel() {
        const d = load();

        // 뱃지 업데이트 — 같은 위치이므로 우선순위: 고정수 > 제외수 > 숨김
        const fixedBadge = document.getElementById('basket-fixed-badge');
        const excludeBadge = document.getElementById('basket-exclude-badge');
        const total = d.fixed.length + d.exclude.length;

        if (fixedBadge && excludeBadge) {
            if (d.fixed.length > 0) {
                // 고정수 있으면 고정수 뱃지에 합계 표시
                fixedBadge.textContent = total;
                fixedBadge.style.display = 'flex';
                excludeBadge.style.display = 'none';
            } else if (d.exclude.length > 0) {
                // 제외수만 있으면 제외수 뱃지
                excludeBadge.textContent = d.exclude.length;
                excludeBadge.style.display = 'flex';
                fixedBadge.style.display = 'none';
            } else {
                fixedBadge.style.display = 'none';
                excludeBadge.style.display = 'none';
            }
        }

        // 패널 내용
        const fixedList = document.getElementById('basket-fixed-list');
        const excludeList = document.getElementById('basket-exclude-list');

        if (fixedList) {
            if (d.fixed.length === 0) {
                fixedList.innerHTML = '<span class="text-slate-400 text-xs">없음</span>';
            } else {
                fixedList.innerHTML = d.fixed.map(n => `
                    <button onclick="Basket.removeFixed(${n}); BasketUI.refresh();"
                        title="${n} 삭제"
                        class="basket-ball flex items-center justify-center w-8 h-8 rounded-full text-white text-xs font-bold shadow-sm hover:opacity-70 hover:scale-90 transition-all"
                        style="background:${ballColor(n)}">
                        ${n}
                    </button>`).join('');
            }
        }

        if (excludeList) {
            if (d.exclude.length === 0) {
                excludeList.innerHTML = '<span class="text-slate-400 text-xs">없음</span>';
            } else {
                excludeList.innerHTML = d.exclude.map(n => `
                    <button onclick="Basket.removeExclude(${n}); BasketUI.refresh();"
                        title="${n} 삭제"
                        class="basket-ball flex items-center justify-center w-7 h-7 rounded-full text-white text-[11px] font-bold shadow-sm hover:opacity-70 hover:scale-90 transition-all ring-2 ring-red-300"
                        style="background:${ballColor(n)}; opacity:0.7">
                        ${n}
                    </button>`).join('');
            }
        }
    }

    // ── 입력 처리 ──────────────────────────────────────────
    function handleInput(type, inputId) {
        const el = document.getElementById(inputId);
        if (!el) return;
        const val = el.value.trim();
        if (!val) return;

        // 여러 번호 한꺼번에 입력 지원 (예: "7 14 27" or "7,14,27")
        const nums = val.split(/[\s,]+/).map(n => parseInt(n)).filter(n => !isNaN(n));
        let lastMsg = '';
        nums.forEach(n => {
            const res = type === 'fixed' ? Basket.addFixed(n) : Basket.addExclude(n);
            if (!res.ok) lastMsg = res.msg;
        });

        if (lastMsg) {
            showToast(lastMsg, 'warn');
        }
        el.value = '';
        renderPanel();
    }

    // ── 토스트 ─────────────────────────────────────────────
    function showToast(msg, type = 'info') {
        const existing = document.getElementById('basket-toast');
        if (existing) existing.remove();
        const el = document.createElement('div');
        el.id = 'basket-toast';
        el.className = 'fixed bottom-6 left-1/2 -translate-x-1/2 z-[9999] px-5 py-3 rounded-xl text-sm font-semibold shadow-xl transition-all';
        el.style.background = type === 'warn' ? '#ef4444' : '#1d4ed8';
        el.style.color = '#fff';
        el.textContent = msg;
        document.body.appendChild(el);
        setTimeout(() => el.remove(), 2500);
    }

    // ── 패널 토글 ──────────────────────────────────────────
    let panelOpen = false;

    function togglePanel() {
        const panel = document.getElementById('basket-panel');
        if (!panel) return;
        panelOpen = !panelOpen;
        if (panelOpen) {
            panel.classList.remove('hidden', 'opacity-0', 'scale-95', 'pointer-events-none');
            panel.classList.add('opacity-100', 'scale-100');
            renderPanel();
            // 패널 외부 클릭 시 닫기
            setTimeout(() => {
                document.addEventListener('click', closePanelOutside, { once: true });
            }, 10);
        } else {
            panel.classList.add('opacity-0', 'scale-95', 'pointer-events-none');
            setTimeout(() => panel.classList.add('hidden'), 150);
        }
    }

    function closePanelOutside(e) {
        const panel = document.getElementById('basket-panel');
        const trigger = document.getElementById('basket-trigger');
        if (!panel || !trigger) return;
        if (!panel.contains(e.target) && !trigger.contains(e.target)) {
            panelOpen = false;
            panel.classList.add('opacity-0', 'scale-95', 'pointer-events-none');
            setTimeout(() => panel.classList.add('hidden'), 150);
        } else {
            // 패널 안 클릭이면 다시 리스너 등록
            document.addEventListener('click', closePanelOutside, { once: true });
        }
    }

    // ── 전역 UI 컨트롤러 ──────────────────────────────────
    window.BasketUI = {
        toggle: togglePanel,
        refresh: renderPanel,
        handleInput,
        showToast,
    };

    // ── basketChanged 이벤트 시 자동 갱신 ─────────────────
    window.addEventListener('basketChanged', renderPanel);

    // ── DOM 준비 후 초기 렌더링 ────────────────────────────
    document.addEventListener('DOMContentLoaded', async () => {
        renderPanel();

        // FilterService가 나중에 초기화될 수 있으므로 대기 후 동기화 및 새 회차 검사 시도
        setTimeout(async () => {
            // Wait for filterService initialization first
            if (!window.filterService?.initialized) {
                await new Promise(resolve => {
                    let retry = 0;
                    const timer = setInterval(() => {
                        if (window.filterService?.initialized || ++retry > 20) {
                            clearInterval(timer);
                            resolve();
                        }
                    }, 500);
                });
            }

            // 새 회차 체크를 먼저 실행 (신규 회차면 DB도 함께 초기화)
            await checkAndClearIfNewRound();

            // 새 회차로 초기화된 경우 DB sync 생략 (초기화 직후 복원 방지)
            if (!_wasCleared && window.filterService?.initialized) {
                await syncFromDB();
            }
        }, 1000);
    });

    // layout.js가 헤더를 동적 로드하므로 약간 지연 후 재시도
    setTimeout(renderPanel, 600);
})();
