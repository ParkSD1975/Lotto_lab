document.addEventListener("DOMContentLoaded", function () {
    // 1. SortableJS 라이브러리 로드 (기초분석 메뉴 순서 변경용)
    const script = document.createElement('script');
    script.src = "https://cdn.jsdelivr.net/npm/sortablejs@latest/Sortable.min.js";
    document.head.appendChild(script);

    // basket.js 로드 (GNB 고정수/제외수 바스켓)
    if (!window.Basket) {
        const basketScript = document.createElement('script');
        basketScript.src = 'js/basket.js';
        document.head.appendChild(basketScript);
    }

    // auth.js 로드 (구글 로그인)
    if (!window._AUTH_LOADED) {
        window._AUTH_LOADED = true;
        const authScript = document.createElement('script');
        authScript.src = 'js/auth.js';
        document.head.appendChild(authScript);
    }

    // ==========================================
    // 설정: 페이지별 컨텍스트 정의
    // ==========================================
    const path = window.location.pathname;
    const pageName = path.split("/").pop() || 'index.html';

    // 페이지별 설정 (어떤 GNB를 켜고, 어떤 사이드바를 쓸지)
    const PAGE_CONFIG = {
        // 대시보드 페이지: GNB 인덱스 0번
        'dashboard.html': {
            gnbIndex: 0,
            sidebarUrl: null,
            type: 'full'
        },
        // 당첨번호 페이지: GNB 인덱스 1번
        'winning-numbers.html': {
            gnbIndex: 1,
            sidebarUrl: 'components/sidebar.html',
            type: 'none'
        },
        // 커스텀 분석 관련 페이지
        'custom_analysis.html': {
            gnbIndex: 3,
            sidebarUrl: 'components/sidebar_custom.html',
            type: 'custom'
        },
        'custom_simulator.html': {
            gnbIndex: 3,
            sidebarUrl: null,
            type: 'full'
        },
        // 번호 생성 페이지
        'generator.html': {
            gnbIndex: 4,
            sidebarUrl: 'components/sidebar.html',
            type: 'none'
        },
        // 딥러닝 분석 페이지
        'ai_deep_learning.html': {
            gnbIndex: 4,
            sidebarUrl: 'components/sidebar.html',
            type: 'none'
        },
        'filter.html': {
            gnbIndex: 5,
            sidebarUrl: null, // 사이드바 제거
            type: 'full'      // 꽉 찬 화면 레이아웃
        },
        'combination_generator.html': {
            gnbIndex: 6,
            sidebarUrl: null,
            type: 'full'
        },
        // [추가] AI 조합 페이지
        'ai_combination.html': {
            gnbIndex: 7,
            sidebarUrl: null,
            type: 'full'
        },
        'output.html': {
            gnbIndex: 8,
            sidebarUrl: null,
            type: 'full'
        },
        'verification.html': {
            gnbIndex: 9,
            sidebarUrl: null,
            type: 'full'
        },
        // [fix-386] 분석 매트릭스 페이지 — 자체 컨트롤 + 모달 사용, LNB 없음
        'analysis_matrix.html': {
            gnbIndex: -1,        // GNB 활성 인덱스 없음 (헤더 매트릭스 아이콘은 nav 외부)
            sidebarUrl: null,
            type: 'full'
        },
        // 그 외 나머지는 모두 '기초 분석'으로 간주 (기본값)
        'default': {
            gnbIndex: 2,
            sidebarUrl: 'components/sidebar.html',
            type: 'basic'
        }
    };

    // 현재 페이지 설정 가져오기 (매칭되는게 없으면 default 사용)
    const config = PAGE_CONFIG[pageName] || PAGE_CONFIG['default'];

    // ✅ [핵심 수정] 캐시 방지용 타임스탬프 생성
    // (파일 주소 뒤에 이 값을 붙이면 브라우저가 매번 새 파일로 인식합니다)
    // 단, file:// 프로토콜에서는 쿼리스트링이 오류를 유발할 수 있으므로 제외
    const cacheBuster = (window.location.protocol === 'file:')
        ? ''
        : '?v=' + new Date().getTime();

    // ==========================================
    // 2. 헤더(GNB) 로드 및 활성화
    // ==========================================
    // 헤더에도 캐시 방지 적용
    fetch('components/header.html' + cacheBuster)
        .then(response => response.text())
        .then(data => {
            const container = document.getElementById('gnb-container');
            if (container) {
                container.innerHTML = data;
                // 헤더 컨테이너에 높이와 레이아웃 클래스 강제 주입
                container.classList.add('h-16', 'shrink-0', 'z-[100]', 'relative');
            }

            // [NEW] 전문가 메모 버튼 주입
            const loginBtnWrapper = container.querySelector('#loginBtn');
            if (loginBtnWrapper && !document.getElementById('expert-memo-trigger')) {
                const btnHtml = `
                    <button id="expert-memo-trigger" onclick="window.ExpertMemo.open()" class="flex items-center justify-center w-9 h-9 rounded-full text-slate-500 hover:text-blue-600 hover:bg-blue-50 transition-all group relative mr-1" title="전문가 분석 메모">
                        <span class="material-symbols-outlined text-[24px]">edit_note</span>
                        <span class="absolute top-1.5 right-1.5 w-2 h-2 bg-red-500 rounded-full border border-white"></span>
                    </button>
                `;
                loginBtnWrapper.insertAdjacentHTML('beforebegin', btnHtml);
            }

            // acct_panel.js 로드 (계정/텔레그램 패널 — innerHTML 주입 후 별도 실행)
            if (!window.AcctPanel) {
                const apScript = document.createElement('script');
                apScript.src = 'js/acct_panel.js';
                document.head.appendChild(apScript);
            } else {
                // 이미 로드된 경우 뱃지 갱신
                setTimeout(() => window.AcctPanel?.refresh(), 50);
            }

            // GNB 메뉴 처리 — [fix-285] 견고한 active 처리 + 재시도 로직
            const applyGnbActive = () => {
                const nav = container.querySelector('nav');
                if (!nav) return false;
                const currentFile = (window.location.pathname.split('/').pop() || 'index.html').toLowerCase();
                const links = nav.querySelectorAll('a.gnb-link');
                if (links.length === 0) return false;
                const activate = (link) => {
                    link.classList.add('active');
                    link.style.color = '#1d4ed8';
                    link.style.fontWeight = '600';
                    if (!link.querySelector('.gnb-underline')) {
                        const u = document.createElement('span');
                        u.className = 'gnb-underline';
                        u.style.cssText = 'position:absolute;left:14px;right:14px;bottom:0;height:2px;background:#1d4ed8;border-radius:1px';
                        link.appendChild(u);
                    }
                };
                // 기존 active 모두 클리어 (페이지 이동 시 잔재 방지)
                links.forEach(l => {
                    l.classList.remove('active');
                    l.style.color = '';
                    l.style.fontWeight = '';
                    l.querySelector('.gnb-underline')?.remove();
                });
                let activated = false;
                links.forEach(link => {
                    const href = (link.getAttribute('href') || '').split('?')[0].toLowerCase();
                    if (href === currentFile) { activate(link); activated = true; }
                });
                if (!activated && config.gnbIndex !== undefined && links[config.gnbIndex]) {
                    activate(links[config.gnbIndex]);
                }
                return true;
            };
            // 즉시 시도 + 100/300/600/1200ms 재시도 (innerHTML 비동기 페인트 보정)
            applyGnbActive();
            [100, 300, 600, 1200].forEach(ms => setTimeout(applyGnbActive, ms));

            // [NEW] 모달 HTML 주입 (없으면)
            if (!document.getElementById('createAnalysisModal')) {
                const modalHTML = `
<div id="createAnalysisModal" class="hidden fixed inset-0 z-[100] flex items-center justify-center p-4">
    <!-- Backdrop -->
    <div class="absolute inset-0 bg-slate-900/60 backdrop-blur-sm transition-opacity" onclick="closeCreateModal()"></div>

    <!-- Modal Content -->
    <div class="relative w-full max-w-2xl bg-white rounded-3xl shadow-2xl transform transition-all scale-100 opacity-100 overflow-hidden flex flex-col max-h-[90vh]">
        
        <!-- Header -->
        <div class="px-8 py-6 border-b border-gray-100 flex items-center justify-between bg-gradient-to-r from-gray-50 to-white">
            <div class="flex items-center gap-3">
                <div class="w-10 h-10 bg-blue-600 rounded-xl flex items-center justify-center text-white shadow-lg shadow-blue-200">
                    <span class="material-symbols-outlined text-xl">add_circle</span>
                </div>
                <div>
                    <h2 class="text-xl font-black text-gray-900 tracking-tight">새 분석 만들기</h2>
                    <p class="text-[11px] font-bold text-gray-400 uppercase tracking-widest mt-0.5">AI Analysis Generator</p>
                </div>
            </div>
            <button onclick="closeCreateModal()" class="w-10 h-10 flex items-center justify-center rounded-full hover:bg-gray-100 text-gray-400 transition-colors">
                <span class="material-symbols-outlined">close</span>
            </button>
        </div>

        <!-- Body -->
        <div class="p-8 overflow-y-auto custom-scrollbar space-y-6">
            
            <!-- Input Section -->
            <div id="inputSection" class="space-y-6 transition-all duration-300">
                <div class="space-y-2">
                    <label class="block text-sm font-bold text-gray-700">분석 제목 <span class="text-red-500">*</span></label>
                    <input type="text" id="newAnalysisTitle" 
                        class="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:border-blue-500 focus:ring-4 focus:ring-blue-50/50 transition-all font-bold text-gray-900 placeholder-gray-400"
                        placeholder="예: 최근 5주간 당첨번호 분석">
                </div>

                <div class="space-y-2">
                    <label class="block text-sm font-bold text-gray-700">
                        분석 요청 사항 (프롬프트) <span class="text-red-500">*</span>
                    </label>
                    <div class="relative">
                        <textarea id="newAnalysisPrompt" rows="4"
                            class="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:border-blue-500 focus:ring-4 focus:ring-blue-50/50 transition-all text-gray-700 placeholder-gray-400 resize-none"
                            placeholder="AI에게 분석하고 싶은 내용을 자연어로 설명해주세요.&#10;예: '지난주 당첨번호에서 +1씩 더한 번호들을 분석해줘'"></textarea>
                        <div class="absolute bottom-3 right-3">
                            <button onclick="document.getElementById('newAnalysisPrompt').value = ''" class="p-1 text-gray-300 hover:text-gray-500 rounded-lg hover:bg-gray-100 transition-colors">
                                <span class="material-symbols-outlined text-sm">backspace</span>
                            </button>
                        </div>
                    </div>
                </div>

                <!-- 💡 Tip Box -->
                <div class="bg-blue-50/50 border border-blue-100 rounded-xl p-4 flex gap-3">
                    <span class="material-symbols-outlined text-blue-500 shrink-0">lightbulb</span>
                    <div class="text-sm text-blue-800 space-y-1">
                        <p class="font-bold">AI 분석 팁</p>
                        <p class="text-blue-600/80 leading-relaxed">
                            "직전 회차 번호", "날짜 끝수", "이월수" 같은 키워드를 사용하면 AI가 더 정확한 규칙을 만들어줍니다.
                        </p>
                    </div>
                </div>
            </div>

            <!-- Preview Section (Hidden by default) -->
            <div id="previewSection" class="hidden space-y-5 animate-in fade-in slide-in-from-bottom-4 duration-500">
                <div class="flex items-center gap-2 mb-2">
                    <span class="h-px flex-1 bg-gray-100"></span>
                    <span class="text-xs font-bold text-gray-400 uppercase tracking-wider">Analysis Preview</span>
                    <span class="h-px flex-1 bg-gray-100"></span>
                </div>

                <div class="bg-white border-2 border-blue-50 rounded-2xl p-6 shadow-xl shadow-blue-50/50 relative overflow-hidden">
                    <div class="absolute top-0 right-0 p-4 opacity-5 pointer-events-none">
                        <span class="material-symbols-outlined text-8xl text-blue-900">neurology</span>
                    </div>

                    <div class="relative z-10 space-y-4">
                        <div class="flex items-center gap-3">
                            <span id="previewTypeBadge" class="px-3 py-1 rounded-lg text-xs font-black bg-blue-100 text-blue-700">TYPE</span>
                            <span class="text-xs font-bold text-gray-400 uppercase tracking-wider">AI Generated Configuration</span>
                        </div>

                        <p id="previewDesc" class="text-sm font-medium text-gray-600 bg-gray-50 p-3 rounded-lg border border-gray-100">
                            설명
                        </p>

                        <!-- Static Preview -->
                        <div id="previewStatic" class="hidden">
                            <label class="block text-xs font-bold text-gray-500 mb-2 uppercase">Target Numbers</label>
                            <div id="previewBalls" class="flex flex-wrap gap-2"></div>
                        </div>

                        <!-- Dynamic Preview -->
                        <div id="previewDynamic" class="hidden">
                             <label class="block text-xs font-bold text-gray-500 mb-2 uppercase">Dynamic Rule</label>
                             <div class="p-4 bg-blue-600 rounded-xl text-white shadow-lg shadow-blue-200">
                                <div class="flex items-center gap-3">
                                    <span class="material-symbols-outlined text-2xl">function</span>
                                    <p id="previewRuleText" class="font-bold text-lg">규칙 설명</p>
                                </div>
                             </div>
                        </div>
                    </div>
                </div>
            </div>

        </div>

        <!-- Footer -->
        <div class="px-8 py-5 bg-gray-50 border-t border-gray-100 flex items-center justify-end gap-3">
            <button onclick="closeCreateModal()" class="px-5 py-2.5 text-sm font-bold text-gray-500 hover:text-gray-700 hover:bg-gray-200 rounded-xl transition-colors">
                취소
            </button>
            
            <button id="btnAnalyze" onclick="analyzePrompt()" class="flex items-center gap-2 px-6 py-2.5 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-sm font-bold transition-all shadow-lg shadow-blue-200 hover:shadow-blue-300 transform active:scale-95">
                <span class="material-symbols-outlined text-lg">psychology</span>
                AI 분석 실행
            </button>

            <button id="btnSave" onclick="saveAnalysis()" class="hidden flex items-center gap-2 px-6 py-2.5 bg-green-600 hover:bg-green-700 text-white rounded-xl text-sm font-bold transition-all shadow-lg shadow-green-200 hover:shadow-green-300 transform active:scale-95">
                <span class="material-symbols-outlined text-lg">save</span>
                분석 저장하기
            </button>
        </div>
    </div>
</div>
                `;
                document.body.insertAdjacentHTML('beforeend', modalHTML);
            }

            // [NEW] 모달 스크립트 함수들을 전역에 등록 (fetch로 로드된 script가 실행되지 않으므로)
            initHeaderModalFunctions();

            // auth.js에 헤더 로드 완료 알림 (로그인 UI 업데이트)
            document.dispatchEvent(new Event('gnbLoaded'));
        })
        .catch(err => console.error('헤더 로드 실패:', err));

    // ==========================================
    // 3. 사이드바(LNB) 동적 로드
    // ==========================================
    if (config.sidebarUrl) {
        // ✅ [핵심 수정] 사이드바 URL 뒤에 캐시 방지 코드 추가
        loadSidebar(config.sidebarUrl + cacheBuster, config, pageName, script);
    }
});

/**
 * 기초분석 사이드바 전용 초기화 함수
 * (메뉴 순서 저장, 하이라이트, 드래그앤드롭)
 */
function initBasicSidebar(container, pageName, sortableScript) {
    const navList = container.querySelector('nav');
    if (!navList) return;

    // (1) 순서 재배치 (LocalStorage)
    // 주의: 메뉴가 추가되었을 때, 기존 저장된 순서 때문에 새 메뉴가 맨 뒤로 밀리거나 안 보일 수도 있음
    // 이를 방지하기 위해 저장된 목록에 없는 새 메뉴는 자동으로 끝에 추가되도록 로직 보완
    const savedOrder = JSON.parse(localStorage.getItem('lnbOrder'));

    // 현재 HTML에 있는 모든 메뉴 아이템 맵핑
    const items = Array.from(navList.children);
    const itemsMap = {};
    items.forEach(item => {
        const href = item.getAttribute('href');
        if (href) itemsMap[href] = item;
    });

    // 저장된 순서대로 배치하되, HTML에는 있지만 저장내역엔 없는(새로 추가된) 메뉴도 처리해야 함
    if (savedOrder && savedOrder.length > 0) {
        // 1. 저장된 순서대로 배치
        savedOrder.forEach(href => {
            if (itemsMap[href]) {
                navList.appendChild(itemsMap[href]);
                delete itemsMap[href]; // 배치된 것은 맵에서 제거
            }
        });

        // 2. 저장내역엔 없지만 HTML엔 남아있는(새로 추가된) 메뉴들을 뒤에 붙임
        // (이게 없으면 로컬스토리지 때문에 새 메뉴가 안 보일 수 있음!)
        Object.values(itemsMap).forEach(item => {
            navList.appendChild(item);
        });
    }

    // (2) 현재 페이지 하이라이트 (초록색)
    const links = navList.querySelectorAll('a.nav-link');
    links.forEach(link => {
        if (link.getAttribute('href') === pageName) {
            link.classList.remove('text-gray-600', 'hover:bg-gray-50', 'hover:text-gray-900');
            link.classList.add('font-semibold', 'bg-blue-50', 'text-blue-700', 'border-l-4', 'border-blue-500');
            const icon = link.querySelector('.material-symbols-outlined');
            if (icon) icon.classList.add('filled', 'text-blue-700');
        }
    });

    // (3) 드래그앤드롭 초기화
    const setupSortable = () => {
        if (window.Sortable) {
            new Sortable(navList, {
                animation: 150,
                ghostClass: 'bg-gray-100',
                onEnd: function () {
                    const newOrder = Array.from(navList.children)
                        .map(item => item.getAttribute('href'))
                        .filter(href => href !== null);
                    localStorage.setItem('lnbOrder', JSON.stringify(newOrder));
                }
            });
        }
    };

    if (window.Sortable) {
        setupSortable();
    } else if (sortableScript) {
        sortableScript.onload = setupSortable;
    }
}

// ==========================================
// 4. 사이드바 로드 함수 (수정됨)
// ==========================================
function loadSidebar(url, config, pageName, sortableScript) {
    const container = document.getElementById('lnb-container');
    if (!container) return;

    // 로드 전 투명화 (로딩 중 깜빡임 방지)
    container.style.opacity = '0';
    container.style.transition = 'opacity 0.2s ease';

    fetch(url)
        .then(response => response.text())
        .then(async html => { // async 키워드 추가
            // 사이드바 상단에 넉넉한 여백(24px) 추가
            container.classList.add('pt-6');
            container.innerHTML = html;

            // 로드 완료 이벤트 발송
            document.dispatchEvent(new Event('sidebarLoaded'));

            // [기초분석]일 경우에만 드래그앤드롭(Sortable) 및 현재 메뉴 하이라이트 적용
            if (config.type === 'basic') {
                initBasicSidebar(container, pageName, sortableScript);
            }

            highlightCurrentPage();

            // HTML 주입 완료 즉시 fade-in (async 작업 전에 실행하여 LNB가 숨긴 채 유지되는 현상 방지)
            container.style.opacity = '1';
            requestAnimationFrame(() => { container.style.opacity = '1'; });

            // [NEW] 커스텀 분석 메뉴 동적 로딩 (커스텀 타입일 때만) — fade-in 후 비동기 실행
            if (config.type === 'custom') {
                renderCustomMenuItems().then((storageKey) => {
                    // 커스텀 사이드바도 드래그앤드롭 지원
                    const navContainer = document.getElementById('customAnalysisNav');
                    if (navContainer && storageKey) {
                        initSortable(navContainer, storageKey);
                    }
                }).catch(err => console.warn('커스텀 메뉴 로드 실패:', err));
            }
        })
        .catch(err => console.error('사이드바 로드 실패:', err));
}

/**
 * 드래그앤드롭(Sortable) 공통 초기화 함수
 */
function initSortable(el, storageKey) {
    const setup = () => {
        if (window.Sortable && el) {
            new Sortable(el, {
                animation: 150,
                ghostClass: 'bg-gray-100',
                onEnd: function () {
                    const newOrder = Array.from(el.children)
                        .map(item => item.getAttribute('href'))
                        .filter(href => href !== null);
                    localStorage.setItem(storageKey, JSON.stringify(newOrder));
                }
            });
        }
    };

    if (window.Sortable) setup();
    else {
        // 아직 로드 전이라면 체크 (layout.js 상단에서 script 추가하므로 보통은 로드됨)
        const check = setInterval(() => {
            if (window.Sortable) {
                setup();
                clearInterval(check);
            }
        }, 100);
        setTimeout(() => clearInterval(check), 3000); // 3초 후 포기
    }
}

// ==========================================
// 5. 현재 페이지 하이라이트 함수
// ==========================================
function highlightCurrentPage() {
    const path = window.location.pathname;
    const pageName = path.split("/").pop() || 'index.html';
    const params = new URLSearchParams(window.location.search);
    const currentId = params.get('id');

    const links = document.querySelectorAll('#lnb-container a.nav-link');
    links.forEach(link => {
        const href = link.getAttribute('href');
        // 일반 페이지 매칭 또는 id 파라미터 매칭
        const isMatch = href === pageName ||
            (currentId && href && href.includes(`id=${currentId}`));

        if (isMatch) {
            link.classList.remove('text-gray-600', 'hover:bg-gray-50', 'hover:text-gray-900');
            link.classList.add('bg-blue-50', 'text-blue-700', 'border-r-2', 'border-blue-500');
        }
    });
}

// ==========================================
// 6. [NEW] 커스텀 메뉴 렌더링 함수
// ==========================================
// [fix-384/385] LNB 다중 선택 스타일 + 숨긴 분석 푸터 (1회 주입)
(function injectLnbSelectionStyle() {
    if (document.getElementById('lnb-multi-select-style')) return;
    const style = document.createElement('style');
    style.id = 'lnb-multi-select-style';
    style.textContent = `
        .nav-link.lnb-selected { background: #DBEAFE !important; color: #1E40AF !important; box-shadow: inset 3px 0 0 0 #3B82F6; }
        .lnb-selection-bar { animation: lnbSelectFadeIn 0.15s ease; }
        @keyframes lnbSelectFadeIn { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: none; } }
        .lnb-archived-footer { margin-top: 16px; padding: 8px 12px; border-top: 1px solid #F1F5F9; }
        .lnb-archived-footer button { font-size: 11px; color: #94A3B8; cursor: pointer; background: transparent; border: 0; padding: 4px 0; }
        .lnb-archived-footer button:hover { color: #475569; }
        .lnb-archived-list { padding: 4px 0; }
        .lnb-archived-item { display: flex; align-items: center; justify-content: space-between; padding: 6px 8px; font-size: 12px; color: #94A3B8; border-radius: 6px; }
        .lnb-archived-item:hover { background: #F8FAFC; color: #475569; }
        .lnb-archived-item .label { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .lnb-archived-item button { font-size: 10px; color: #2563EB; padding: 2px 6px; }
        .lnb-archived-item button:hover { color: #1E40AF; background: #EFF6FF; border-radius: 4px; }
    `;
    document.head.appendChild(style);
})();

// [fix-385] LNB 푸터 — 숨긴 분석 토글 + 재활성화
async function renderArchivedFooter(navContainer) {
    if (!navContainer) return;
    let footer = navContainer.parentNode.querySelector('.lnb-archived-footer');
    if (footer) footer.remove();

    // archived 갯수 조회
    const { count } = await window.supabaseClient
        .from('ai_custom_analyses')
        .select('id', { count: 'exact', head: true })
        .is('target_round', null)
        .eq('is_archived', true);

    if (!count || count === 0) return;   // archived 없으면 푸터 표시 X

    footer = document.createElement('div');
    footer.className = 'lnb-archived-footer';
    footer.innerHTML = `<button data-toggle="archived" class="flex items-center gap-1.5">
        <span class="material-symbols-outlined" style="font-size:14px">visibility_off</span>
        숨긴 분석 (${count})
    </button>
    <div class="lnb-archived-list" style="display:none"></div>`;
    navContainer.parentNode.appendChild(footer);

    const toggle = footer.querySelector('[data-toggle="archived"]');
    const list = footer.querySelector('.lnb-archived-list');
    toggle.onclick = async () => {
        if (list.style.display === 'none') {
            // 펼침 + 데이터 로드
            const { data, error } = await window.supabaseClient
                .from('ai_custom_analyses')
                .select('id, title')
                .is('target_round', null)
                .eq('is_archived', true)
                .order('updated_at', { ascending: false });
            if (error) { alert('숨긴 분석 로드 실패'); return; }
            list.innerHTML = (data || []).map(item => `
                <div class="lnb-archived-item" data-id="${item.id}">
                    <span class="label" title="${item.title || ''}">${item.title || '(제목 없음)'}</span>
                    <button data-act="restore">↶ 복원</button>
                </div>
            `).join('');
            list.querySelectorAll('[data-act="restore"]').forEach(b => b.onclick = async (e) => {
                e.stopPropagation();
                const id = b.closest('.lnb-archived-item').dataset.id;
                const { error: e2 } = await window.supabaseClient
                    .from('ai_custom_analyses')
                    .update({ is_archived: false })
                    .eq('id', id);
                if (e2) { alert('복원 실패'); return; }
                // LNB 새로고침
                renderCustomMenuItems();
            });
            list.style.display = 'block';
        } else {
            list.style.display = 'none';
        }
    };
}

async function renderCustomMenuItems() {
    const navContainer = document.getElementById('customAnalysisNav');
    if (!navContainer) return null;

    try {
        // [수정] filterService 우선 → auth.getUser() 비동기 타이밍 이슈 해결
        // 로그아웃 직후 auth 상태가 비확정일 때, filterService가 이미 확정된 userId를 가지고 있으면 우선 사용
        // _lastLoginUserId: 로그아웃 전에 auth.js에서 백업해둔 유저 ID (3번째 fallback)
        const _menuUserId = window.filterService?.userId
            || (await window.supabaseClient.auth.getUser()).data?.user?.id
            || localStorage.getItem('_lastLoginUserId')
            || null;

        // [수정] 사용자별로 저장 키 분리 (로그아웃 시 순서가 섞이는 문제 방지)
        const storageKey = _menuUserId ? `lnbOrder_custom_${_menuUserId}` : 'lnbOrder_custom_guest';
        // 현재 로그인한 사용자의 키를 window에 노출 → 드래그앤드롭 저장 시에도 같은 키 사용되도록 보장
        window._customMenuStorageKey = storageKey;

        // [수정] 내 분석 + 공용(user_id가 null) 분석 모두 가져오기
        // [fix-385] is_archived = false 만 표시 (숨김 처리된 분석 제외)
        let _menuQuery = window.supabaseClient
            .from('ai_custom_analyses')
            .select('id, title, type, filter_config, user_id, is_archived')
            .is('target_round', null)
            .or('is_archived.is.null,is_archived.eq.false')
            .order('created_at', { ascending: true });

        if (_menuUserId) {
            _menuQuery = _menuQuery.or(`user_id.eq.${_menuUserId},user_id.is.null`);
        } else {
            _menuQuery = _menuQuery.is('user_id', null);
        }

        const { data: analyses, error } = await _menuQuery;

        if (error) throw error;

        // [NEW] 순서 동기화 (사용자 전용 LocalStorage 기반)
        const savedOrder = JSON.parse(localStorage.getItem(storageKey));
        if (savedOrder && savedOrder.length > 0) {
            analyses.sort((a, b) => {
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

        // 2. 기존 로딩 메시지 제거
        navContainer.innerHTML = '';

        // 아이콘 매핑 객체
        const iconMap = {
            'static': 'grid_view',
            'dynamic': 'trending_up',
            'group': 'group_work',
            'manual': 'edit_square',
            'direct': 'edit_square',
            'comparison': 'compare_arrows',
            'compare': 'compare_arrows'
        };

        // 3. 메뉴 아이템 생성 및 추가
        if (analyses && analyses.length > 0) {
            // [fix-384] 다중 선택 상태 + 선택 바
            const selectedSet = new Set();
            let selectionBar = navContainer.parentNode.querySelector('.lnb-selection-bar');
            if (selectionBar) selectionBar.remove();
            selectionBar = document.createElement('div');
            selectionBar.className = 'lnb-selection-bar sticky top-0 z-10 px-3 py-2 bg-blue-50 border-b border-blue-100 flex items-center justify-between';
            selectionBar.style.display = 'none';
            navContainer.parentNode.insertBefore(selectionBar, navContainer);

            const updateSelectionBar = () => {
                if (selectedSet.size === 0) {
                    selectionBar.style.display = 'none';
                    return;
                }
                selectionBar.style.display = 'flex';
                // [fix-385] 숨김(권장) + 삭제(영구) 두 버튼 분리
                selectionBar.innerHTML = `
                    <span class="text-[11px] text-blue-700">${selectedSet.size}개 선택</span>
                    <div class="flex gap-3 items-center">
                        <button class="text-[11px] text-slate-500 hover:text-slate-700" data-act="clear">해제</button>
                        <button class="text-[11px] text-amber-600 hover:text-amber-700 flex items-center gap-1" data-act="archive" title="숨김 — 메뉴/필터/조합에서 숨김 (DB 보존, 재활성화 가능)">
                            <span class="material-symbols-outlined" style="font-size:14px">visibility_off</span>숨김
                        </button>
                        <button class="text-[11px] text-rose-600 hover:text-rose-700 flex items-center gap-1" data-act="delete" title="영구 삭제 — DB에서 완전 제거">
                            <span class="material-symbols-outlined" style="font-size:14px">delete</span>삭제
                        </button>
                    </div>
                `;
                selectionBar.querySelector('[data-act="clear"]').onclick = () => {
                    selectedSet.clear();
                    navContainer.querySelectorAll('.lnb-selected').forEach(el => el.classList.remove('lnb-selected'));
                    updateSelectionBar();
                };
                // [fix-385] 숨김 (UPDATE is_archived=true)
                selectionBar.querySelector('[data-act="archive"]').onclick = async () => {
                    const cnt = selectedSet.size;
                    if (!confirm(`선택한 ${cnt}개 분석을 숨길까요?\n(메뉴/필터/조합에서 안 보이지만 DB에는 보존됩니다. 추후 재활성화 가능)`)) return;
                    const ids = [...selectedSet];
                    try {
                        const { error } = await window.supabaseClient
                            .from('ai_custom_analyses')
                            .update({ is_archived: true })
                            .in('id', ids);
                        if (error) throw error;
                        ids.forEach(id => {
                            const el = navContainer.querySelector(`[data-analysis-id="${id}"]`);
                            if (el) el.remove();
                        });
                        selectedSet.clear();
                        updateSelectionBar();
                        const params = new URLSearchParams(window.location.search);
                        const curId = params.get('id');
                        if (curId && ids.includes(curId)) {
                            alert(`${cnt}개 분석 숨김 처리됨. 현재 페이지도 숨김 대상입니다.`);
                            window.location.href = 'index.html';
                        } else {
                            console.log(`[fix-385] ${cnt}개 분석 숨김 처리`);
                        }
                    } catch (e) {
                        alert('숨김 처리 실패: ' + e.message);
                    }
                };
                // 영구 삭제 (DELETE)
                selectionBar.querySelector('[data-act="delete"]').onclick = async () => {
                    const cnt = selectedSet.size;
                    if (!confirm(`선택한 ${cnt}개 분석을 영구 삭제할까요?\n(되돌릴 수 없습니다. 모든 페이지에서 사라집니다)`)) return;
                    const ids = [...selectedSet];
                    try {
                        const { error } = await window.supabaseClient
                            .from('ai_custom_analyses')
                            .delete()
                            .in('id', ids);
                        if (error) throw error;
                        ids.forEach(id => {
                            const el = navContainer.querySelector(`[data-analysis-id="${id}"]`);
                            if (el) el.remove();
                        });
                        selectedSet.clear();
                        updateSelectionBar();
                        const params = new URLSearchParams(window.location.search);
                        const curId = params.get('id');
                        if (curId && ids.includes(curId)) {
                            alert(`${cnt}개 분석 삭제됨. 현재 페이지 분석도 삭제되었습니다.`);
                            window.location.href = 'index.html';
                        } else {
                            console.log(`[fix-385] ${cnt}개 분석 영구 삭제`);
                        }
                    } catch (e) {
                        alert('삭제 실패: ' + e.message);
                    }
                };
            };

            analyses.forEach(item => {
                const params = new URLSearchParams(window.location.search);
                const currentId = params.get('id');
                const isActive = currentId === item.id;
                const isFilterEnabled = item.filter_config?.enabled === true;

                // 해당 유형의 아이콘 가져오기 (없으면 기본 아이콘)
                const iconName = iconMap[item.type] || 'auto_awesome';

                const link = document.createElement('a');
                link.href = `custom_analysis.html?id=${item.id}`;
                link.dataset.analysisId = item.id;   // [fix-384] 삭제 시 DOM 매칭

                if (isActive) {
                    link.className = 'nav-link flex items-center justify-between px-3 py-2 text-sm font-semibold bg-blue-50 text-blue-700 border-l-4 border-blue-500 rounded-lg transition-colors';
                } else {
                    link.className = 'nav-link flex items-center justify-between px-3 py-2 text-sm text-gray-600 hover:bg-gray-50 hover:text-gray-900 rounded-lg transition-colors';
                }

                // 필터 상태 배지
                const filterBadge = isFilterEnabled
                    ? '<span class="text-[10px] font-bold px-1.5 py-0.5 rounded bg-green-100 text-green-700">ON</span>'
                    : '';

                link.innerHTML = `
                    <span class="flex items-center gap-2 truncate">
                        <span class="material-symbols-outlined text-lg">${iconName}</span>
                        <span class="truncate">${item.title}</span>
                    </span>
                    ${filterBadge}
                `;

                // [fix-384] Ctrl/Cmd + 클릭 = 다중 선택 (navigation 차단)
                link.addEventListener('click', (e) => {
                    if (e.ctrlKey || e.metaKey) {
                        e.preventDefault();
                        if (selectedSet.has(item.id)) {
                            selectedSet.delete(item.id);
                            link.classList.remove('lnb-selected');
                        } else {
                            selectedSet.add(item.id);
                            link.classList.add('lnb-selected');
                        }
                        updateSelectionBar();
                    }
                    // 일반 클릭은 그대로 navigation
                });

                navContainer.appendChild(link);
            });
            // [fix-385] LNB 하단 — 숨긴 분석 보기 토글
            renderArchivedFooter(navContainer);
        } else {
            // 분석이 없을 때 빈 상태 표시
            navContainer.innerHTML = `
                <div class="text-center py-6 text-gray-400">
                    <span class="material-symbols-outlined text-3xl mb-2 block">auto_awesome</span>
                    <p class="text-xs mb-2">아직 분석이 없습니다</p>
                    <p class="text-xs text-gray-300">상단의 [새분석] 버튼을<br>눌러 만들어보세요!</p>
                </div>
            `;
        }

        return storageKey;
    } catch (err) {
        console.error('커스텀 메뉴 로딩 실패:', err);
        navContainer.innerHTML = `
            <div class="text-center py-6 text-red-400">
                <span class="material-symbols-outlined text-2xl mb-2 block">error</span>
                <p class="text-xs">메뉴 로딩 실패</p>
            </div>
        `;
    }
}

// ==========================================
// 7. [NEW] 헤더 모달 함수 초기화 - Static/Dynamic 지원
// ==========================================
let tempAnalysisData = null;  // 미리보기 데이터 임시 저장

function initHeaderModalFunctions() {
    // 모달 열기
    window.openCreateModal = function () {
        const modal = document.getElementById('createAnalysisModal');
        if (!modal) {
            console.warn('모달을 찾을 수 없습니다.');
            return;
        }
        modal.classList.remove('hidden');

        // 초기화
        const titleInput = document.getElementById('newAnalysisTitle');
        const promptInput = document.getElementById('newAnalysisPrompt');
        const inputSection = document.getElementById('inputSection');
        const previewSection = document.getElementById('previewSection');
        const btnAnalyze = document.getElementById('btnAnalyze');
        const btnSave = document.getElementById('btnSave');

        if (titleInput) titleInput.value = '';
        if (promptInput) promptInput.value = '';
        if (inputSection) inputSection.classList.remove('opacity-50', 'pointer-events-none');
        if (previewSection) previewSection.classList.add('hidden');
        if (btnAnalyze) btnAnalyze.classList.remove('hidden');
        if (btnSave) btnSave.classList.add('hidden');
        tempAnalysisData = null;

        const transformDiv = modal.querySelector('.transform');
        if (transformDiv) {
            setTimeout(() => {
                transformDiv.classList.add('scale-100');
                transformDiv.classList.remove('scale-95', 'opacity-0');
            }, 10);
        }
        if (titleInput) titleInput.focus();
    };

    // [Fix] GlobalModal 정의 (header.html 호환용)
    window.GlobalModal = {
        openNewAnalysis: window.openCreateModal
    };

    // 모달 닫기
    window.closeCreateModal = function () {
        const modal = document.getElementById('createAnalysisModal');
        if (!modal) return;
        modal.classList.add('hidden');
    };

    // [Stage 1-4-D-2-fix-106] 필터 합집합/교집합 패턴 사전 계산기
    // — "7배수 8배수 합집합", "소수 합성수 교집합" 같은 패턴을 AI 거치지 않고 직접 계산
    function _computeFilterCombination(prompt) {
        const text = prompt.replace(/\s+/g, '');
        // 1) X배수 / Y배수 / Z배수 ... 추출 (3, 4, 5, 7, 8 지원)
        const multipleRe = /(\d+)배수/g;
        const mults = [];
        let m;
        while ((m = multipleRe.exec(text)) !== null) {
            const v = parseInt(m[1]);
            if (v >= 2 && v <= 9) mults.push(v);
        }
        // 2) 합집합/교집합/차집합 키워드
        const op = /합집합|union/i.test(text) ? 'union'
                 : /교집합|intersection/i.test(text) ? 'intersection'
                 : null;
        if (mults.length < 2 || !op) return null;

        // 3) 1~45 중 각 배수의 set 빌드
        const sets = mults.map(m => {
            const s = new Set();
            for (let n = m; n <= 45; n += m) s.add(n);
            return s;
        });

        // 4) op 적용
        let result;
        if (op === 'union') {
            result = new Set();
            sets.forEach(s => s.forEach(n => result.add(n)));
        } else {
            result = new Set([...sets[0]].filter(n => sets.every(s => s.has(n))));
        }

        const sorted = [...result].sort((a, b) => a - b);
        const opLabel = op === 'union' ? '합집합' : '교집합';
        return {
            type: 'static',
            target_numbers: sorted,
            description: `${mults.join('배수, ')}배수 ${opLabel} (총 ${sorted.length}개 번호)`,
            _matched_pattern: true
        };
    }

    // [Stage 1-4-D-2-fix-203] AutoNLP 기반 직접 계산 (Phase 3)
    // — AutoNLPMatcher가 매칭한 필터/연산자로 AI 우회 처리
    function _computeFromAutoNLP(prompt, nlpResult, title) {
        try {
            const { filters, operations, confidence } = nlpResult;

            // 필터가 2개 미만이면 합집합/교집합 불가
            if (!filters || filters.length < 2) return null;

            // 연산자 확인
            const operation = operations && operations.length > 0 ? operations[0] : null;
            if (!operation || !['union', 'intersection'].includes(operation.canonical)) {
                return null;
            }

            // 배수 필터만 지원 (mul3~mul9)
            const mulFilters = filters.filter(f => f.canonical.startsWith('mul'));
            if (mulFilters.length < 2) return null;

            // 배수 값 추출
            const mults = mulFilters.map(f => {
                const match = f.canonical.match(/mul(\d+)/);
                return match ? parseInt(match[1]) : null;
            }).filter(v => v !== null && v >= 2 && v <= 9);

            if (mults.length < 2) return null;

            // set 빌드
            const sets = mults.map(m => {
                const s = new Set();
                for (let n = m; n <= 45; n += m) s.add(n);
                return s;
            });

            // 연산 적용
            let result;
            if (operation.canonical === 'union') {
                result = new Set();
                sets.forEach(s => s.forEach(n => result.add(n)));
            } else {
                result = new Set([...sets[0]].filter(n => sets.every(s => s.has(n))));
            }

            const sorted = [...result].sort((a, b) => a - b);
            const opLabel = operation.canonical === 'union' ? '합집합' : '교집합';
            const filterLabels = mulFilters.map(f => f.matched_text || f.canonical).join(', ');

            return {
                type: 'static',
                target_numbers: sorted,
                description: `${filterLabels} ${opLabel} (총 ${sorted.length}개 번호)`,
                rules: {
                    source: 'auto_nlp',
                    filters: mulFilters.map(f => f.canonical),
                    operation: operation.canonical,
                    confidence: confidence
                },
                _matched_auto_nlp: true
            };
        } catch (e) {
            console.warn('[_computeFromAutoNLP] Error:', e);
            return null;
        }
    }

    // 1단계: 프롬프트 분석 (Real AI by Edge Function)
    window.analyzePrompt = async function () {
        const title = document.getElementById('newAnalysisTitle')?.value.trim();
        const prompt = document.getElementById('newAnalysisPrompt')?.value.trim();

        if (!title || !prompt) {
            alert("분석 이름과 내용을 모두 입력해주세요.");
            return;
        }

        // ── 단계 1: AutoNLP 매칭 (Phase 3 fix-203) ──────────────────────
        let nlpResult = null;
        try {
            if (window.autoNLP && window.autoNLP.loaded) {
                nlpResult = window.autoNLP.match(prompt);
                console.log('[analyzePrompt fix-203] AutoNLP intent:', nlpResult.intent, 'conf:', nlpResult.confidence);
            }
        } catch (e) {
            console.warn('[analyzePrompt fix-203] AutoNLP error:', e);
        }

        // ── 단계 2: filter_combination 의도 + 신뢰도 ≥ 0.8 → AI 우회 직접 계산 ──
        if (nlpResult && nlpResult.intent === 'filter_combination' && nlpResult.confidence >= 0.8) {
            const directResult = _computeFromAutoNLP(prompt, nlpResult, title);
            if (directResult) {
                const result = {
                    title: title,
                    prompt: prompt,
                    ...directResult
                };
                console.log('[analyzePrompt fix-203] AutoNLP 직접 계산:', result);
                tempAnalysisData = result;
                showPreview(result);
                return;
            }
        }

        // ── 단계 3: 기존 정규식 fallback (역호환) ──────────────────────
        const directResult = _computeFilterCombination(prompt);
        if (directResult) {
            const result = {
                title: title,
                prompt: prompt,
                ...directResult
            };
            console.log('[analyzePrompt fix-106] regex fallback:', result);
            tempAnalysisData = result;
            showPreview(result);
            return;
        }

        // ── 단계 4: AI 호출 (기존 그대로) ──────────────────────────────
        // 로딩 UI
        const btnAnalyze = document.getElementById('btnAnalyze');
        if (!btnAnalyze) return;
        const originalText = btnAnalyze.innerHTML;
        btnAnalyze.innerHTML = `<span class="material-symbols-outlined animate-spin">progress_activity</span> AI 분석 중...`;
        btnAnalyze.disabled = true;

        try {
            // 시스템 프롬프트: AI에게 역할과 출력 형식을 부여
            const systemContext = `
# Role
You are the 'Configuration Generator' for a Lotto Analysis System.
Your goal is to parse the user's natural language request and convert it into a structured JSON configuration object.

# User Input
Title: ${title}
Request: "${prompt}"

# Output Format (JSON Only)
You must return a valid JSON object matching this schema:
{
  "title": "${title}",
  "description": "...",
  "type": "static" | "dynamic" | "manual" | "ai_ensemble_fixed" | "ai_ensemble_excluded" | "ai_model_top" | "ai_model_bottom",
  "target_numbers": [], // Only for "static" or "manual"
    "rules": {
    // For "dynamic" type:
    "formula": "prev_plus_n" | "prev_minus_n" | "carryover" | "draw_date_end" | "round_end_digit" | "math_expression",
    "value": 0,
    "expression": "...",
    
    // For "ai_model_top" or "ai_model_bottom" type:
    "model": "xgboost" | "catboost" | "tabnet" | "cnn" | "gnn" | "markov" | "autoencoder" | "tft" | "nbeats" | "mhn" | "bayesian_nn" | "ensemble",
    "count": 10
  }
}

# Logic Guide
1. If the user asks for specific fixed numbers (e.g., "Analyze 1, 5, 10"), set type to "static" and fill "target_numbers".
2. If the user asks for a rule relative to previous rounds (e.g., "+ 2", "- 1", "Carryover"), set type to "dynamic" and appropriate formula.
3. [IMPORTANT] If the user asks for a specific round offset end digit (e.g., "회차 - 1 끝수", "전회차 끝수"), set forumla to "round_end_digit" and "value" to the offset (e.g., -1).
4. [IMPORTANT] If the request mentions AI, Deep Learning, Recommendation, Fixed, or Excluded (e.g., "AI 고정수", "제외수 분석"), set type to "ai_ensemble_fixed" or "ai_ensemble_excluded".
5. [IMPORTANT] If the request mentions a specific model or ranking (e.g., "TFT 상위 10개", "XGB 하위 5개", "CatBoost 상위 7개"), set type to "ai_model_top" or "ai_model_bottom", and specify "model" and "count" in "rules".

# Response
Return ONLY the JSON. No markdown.
`;

            // Edge Function 호출
            const { data, error } = await window.supabaseClient.functions.invoke('ai-lotto-analyst', {
                body: { context: systemContext }
            });

            if (error) throw error;

            let result = data;

            // 문자열로 온 경우 파싱 시도
            if (typeof result === 'string') {
                try {
                    const cleanJson = result.replace(/```json/g, '').replace(/```/g, '').trim();
                    result = JSON.parse(cleanJson);
                } catch (e) {
                    console.error("JSON Parsing Error:", e);
                    throw new Error("AI 응답을 해석할 수 없습니다.");
                }
            }

            console.log("AI Analysis Result:", result);

            // [FIX] 원본 프롬프트 보존 (DB 저장을 위해 필수)
            result.prompt = prompt;

            tempAnalysisData = result;
            showPreview(result);

        } catch (err) {
            console.error(err);
            alert("AI 분석 중 오류가 발생했습니다: " + (err.message || err));
        } finally {
            btnAnalyze.innerHTML = originalText;
            btnAnalyze.disabled = false;
        }
    };

    // 미리보기 UI 업데이트
    function showPreview(data) {
        const previewSection = document.getElementById('previewSection');
        const btnAnalyze = document.getElementById('btnAnalyze');
        const btnSave = document.getElementById('btnSave');

        if (previewSection) previewSection.classList.remove('hidden');
        if (btnAnalyze) btnAnalyze.classList.add('hidden');
        if (btnSave) btnSave.classList.remove('hidden');

        const previewDesc = document.getElementById('previewDesc');
        if (previewDesc) previewDesc.textContent = data.description;

        const badge = document.getElementById('previewTypeBadge');
        const staticArea = document.getElementById('previewStatic');
        const dynamicArea = document.getElementById('previewDynamic');
        const ruleTextEl = document.getElementById('previewRuleText');

        if (data.type === 'dynamic') {
            if (badge) {
                badge.textContent = "변동 규칙 (Dynamic)";
                badge.className = "px-2 py-0.5 rounded text-xs font-bold bg-blue-100 text-blue-700";
            }
            if (staticArea) staticArea.classList.add('hidden');
            if (dynamicArea) dynamicArea.classList.remove('hidden');

            let ruleText = "알 수 없는 규칙";
            const formula = data.rules?.formula;
            const val = data.rules?.value || 0;

            if (formula === 'prev_plus_n') ruleText = `규칙: 직전 회차 번호 + ${val}`;
            else if (formula === 'prev_minus_n') ruleText = `규칙: 직전 회차 번호 - ${val}`;
            else if (formula === 'carryover') ruleText = "규칙: 이월수 (직전 회차 그대로)";
            else if (formula === 'draw_date_end') ruleText = "규칙: 당첨일(추첨일) 일자 기준 끝수 분석";
            else if (formula === 'round_end_digit') ruleText = val ? `규칙: 회차 끝수 분석 (오프셋: ${val})` : "규칙: 회차 끝수 분석";
            else if (formula === 'math_expression') ruleText = `규칙: 수식 ( ${data.rules?.expression || 'x'} )`;

            if (ruleTextEl) ruleTextEl.textContent = ruleText;

        } else if (data.type && data.type.startsWith('ai_')) {
            if (badge) {
                badge.textContent = "AI 딥러닝 분석";
                badge.className = "px-2 py-0.5 rounded text-xs font-bold bg-purple-100 text-purple-700";
            }
            if (staticArea) staticArea.classList.add('hidden');
            if (dynamicArea) dynamicArea.classList.remove('hidden');

            let aiRuleText = "AI 앙상블 분석";
            if (data.type === 'ai_ensemble_fixed') aiRuleText = "AI 강력 추천 고정수 분석";
            else if (data.type === 'ai_ensemble_excluded') aiRuleText = "AI 확률 기반 제외수 분석";
            else if (data.type === 'ai_model_top') aiRuleText = `전술 모델(${data.rules?.model || 'Ensemble'}) 상위 ${data.rules?.count || 10}개 분석`;
            else if (data.type === 'ai_model_bottom') aiRuleText = `전술 모델(${data.rules?.model || 'Ensemble'}) 하위 ${data.rules?.count || 10}개 분석`;

            if (ruleTextEl) ruleTextEl.textContent = aiRuleText;

        } else {
            if (badge) {
                badge.textContent = data.type === 'manual' ? "수동 선택 (Manual)" : "고정 번호 (Static)";
                badge.className = "px-2 py-0.5 rounded text-xs font-bold bg-green-100 text-green-700";
            }
            if (dynamicArea) dynamicArea.classList.add('hidden');
            if (staticArea) staticArea.classList.remove('hidden');

            const ballContainer = document.getElementById('previewBalls');
            if (ballContainer) {
                ballContainer.innerHTML = '';
                const getBallColor = (n) => {
                    if (n <= 10) return '#F7C948';
                    if (n <= 20) return '#4a90d9';
                    if (n <= 30) return '#E04A4A';
                    if (n <= 40) return '#6B7280';
                    return '#48B05A';
                };

                (data.target_numbers || []).forEach(num => {
                    const ball = document.createElement('span');
                    ball.className = "inline-flex items-center justify-center w-6 h-6 rounded-full text-[10px] font-bold text-white shadow-sm";
                    ball.style.backgroundColor = window.Utils ? window.Utils.getBallColor(num) : getBallColor(num);
                    ball.textContent = num;
                    ballContainer.appendChild(ball);
                });
            }
        }
    }

    // 2단계: 최종 저장 (DB Insert)
    window.saveAnalysis = async function () {
        if (!tempAnalysisData) return;

        const btnSave = document.getElementById('btnSave');
        if (!btnSave) return;
        const originalText = btnSave.innerHTML;
        btnSave.innerHTML = `<span class="material-symbols-outlined animate-spin">progress_activity</span> 저장 중...`;
        btnSave.disabled = true;

        try {
            const userTitle = document.getElementById('newAnalysisTitle')?.value.trim();
            const _saveUserId = window.filterService?.userId
                || (await window.supabaseClient.auth.getUser()).data?.user?.id;
            const { data, error } = await window.supabaseClient
                .from('ai_custom_analyses')
                .insert([{
                    title: tempAnalysisData.title || userTitle || '새 분석',
                    prompt: tempAnalysisData.prompt,
                    description: tempAnalysisData.description,
                    type: tempAnalysisData.type,
                    // [FIX] dynamic 타입일 경우 target_numbers가 null일 수 있으므로 빈 배열 처리
                    target_numbers: tempAnalysisData.target_numbers || [],
                    rules: tempAnalysisData.rules,
                    filter_config: { min: 1, max: 3, enabled: false },
                    user_id: _saveUserId || null
                }])
                .select()
                .single();

            if (error) throw error;

            alert("분석이 생성되었습니다!");
            window.location.href = `custom_analysis.html?id=${data.id}`;

        } catch (err) {
            console.error(err);
            alert("저장 실패: " + err.message);
            btnSave.innerHTML = originalText;
            btnSave.disabled = false;
        }
    };
}
