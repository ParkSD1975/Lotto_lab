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
            container.innerHTML = data;

            // 헤더 컨테이너에 높이와 레이아웃 클래스 강제 주입
            container.classList.add('h-16', 'shrink-0', 'z-50', 'relative');

            // GNB 메뉴 처리
            const nav = container.querySelector('nav');
            if (nav && nav.children[config.gnbIndex]) {
                const activeLink = nav.children[config.gnbIndex];
                activeLink.classList.add('active');
            }

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
                <div class="w-10 h-10 bg-indigo-600 rounded-xl flex items-center justify-center text-white shadow-lg shadow-indigo-200">
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
                        class="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:border-indigo-500 focus:ring-4 focus:ring-indigo-50/50 transition-all font-bold text-gray-900 placeholder-gray-400"
                        placeholder="예: 최근 5주간 당첨번호 분석">
                </div>

                <div class="space-y-2">
                    <label class="block text-sm font-bold text-gray-700">
                        분석 요청 사항 (프롬프트) <span class="text-red-500">*</span>
                    </label>
                    <div class="relative">
                        <textarea id="newAnalysisPrompt" rows="4"
                            class="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:border-indigo-500 focus:ring-4 focus:ring-indigo-50/50 transition-all text-gray-700 placeholder-gray-400 resize-none"
                            placeholder="AI에게 분석하고 싶은 내용을 자연어로 설명해주세요.&#10;예: '지난주 당첨번호에서 +1씩 더한 번호들을 분석해줘'"></textarea>
                        <div class="absolute bottom-3 right-3">
                            <button onclick="document.getElementById('newAnalysisPrompt').value = ''" class="p-1 text-gray-300 hover:text-gray-500 rounded-lg hover:bg-gray-100 transition-colors">
                                <span class="material-symbols-outlined text-sm">backspace</span>
                            </button>
                        </div>
                    </div>
                </div>

                <!-- 💡 Tip Box -->
                <div class="bg-indigo-50/50 border border-indigo-100 rounded-xl p-4 flex gap-3">
                    <span class="material-symbols-outlined text-indigo-500 shrink-0">lightbulb</span>
                    <div class="text-sm text-indigo-800 space-y-1">
                        <p class="font-bold">AI 분석 팁</p>
                        <p class="text-indigo-600/80 leading-relaxed">
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

                <div class="bg-white border-2 border-indigo-50 rounded-2xl p-6 shadow-xl shadow-indigo-50/50 relative overflow-hidden">
                    <div class="absolute top-0 right-0 p-4 opacity-5 pointer-events-none">
                        <span class="material-symbols-outlined text-8xl text-indigo-900">neurology</span>
                    </div>

                    <div class="relative z-10 space-y-4">
                        <div class="flex items-center gap-3">
                            <span id="previewTypeBadge" class="px-3 py-1 rounded-lg text-xs font-black bg-indigo-100 text-indigo-700">TYPE</span>
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
                             <div class="p-4 bg-indigo-600 rounded-xl text-white shadow-lg shadow-indigo-200">
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
            
            <button id="btnAnalyze" onclick="analyzePrompt()" class="flex items-center gap-2 px-6 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl text-sm font-bold transition-all shadow-lg shadow-indigo-200 hover:shadow-indigo-300 transform active:scale-95">
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

            // [NEW] 커스텀 분석 메뉴 동적 로딩 (커스텀 타입일 때만)
            if (config.type === 'custom') {
                await renderCustomMenuItems();
                // 커스텀 사이드바도 드래그앤드롭 지원
                const navContainer = document.getElementById('customAnalysisNav');
                if (navContainer) {
                    initSortable(navContainer, 'lnbOrder_custom');
                }
            }

            highlightCurrentPage();
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
async function renderCustomMenuItems() {
    const navContainer = document.getElementById('customAnalysisNav'); // sidebar_custom.html 내의 nav 태그 찾기
    if (!navContainer || !window.supabaseClient) return;

    try {
        // 1. DB에서 커스텀 분석 목록 가져오기
        const { data: analyses, error } = await window.supabaseClient
            .from('ai_custom_analyses')
            .select('id, title, type, filter_config')
            .order('created_at', { ascending: true }); // 생성 순으로 표시

        if (error) throw error;

        // [NEW] 순서 동기화 (LocalStorage 기반)
        const savedOrder = JSON.parse(localStorage.getItem('lnbOrder_custom'));
        if (savedOrder && savedOrder.length > 0) {
            analyses.sort((a, b) => {
                const hrefA = `custom_analysis.html?id=${a.id}`;
                const hrefB = `custom_analysis.html?id=${b.id}`;
                const idxA = savedOrder.indexOf(hrefA);
                const idxB = savedOrder.indexOf(hrefB);

                // 둘 다 순서에 있으면 해당 순서대로
                if (idxA !== -1 && idxB !== -1) return idxA - idxB;
                // 새로운 메뉴(순서에 없는 것)는 뒤로 보냄
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
            analyses.forEach(item => {
                const params = new URLSearchParams(window.location.search);
                const currentId = params.get('id');
                const isActive = currentId === item.id;
                const isFilterEnabled = item.filter_config?.enabled === true;

                // 해당 유형의 아이콘 가져오기 (없으면 기본 아이콘)
                const iconName = iconMap[item.type] || 'auto_awesome';

                const link = document.createElement('a');
                link.href = `custom_analysis.html?id=${item.id}`;

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
                navContainer.appendChild(link);
            });
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

    // 1단계: 프롬프트 분석 (Real AI by Edge Function)
    window.analyzePrompt = async function () {
        const title = document.getElementById('newAnalysisTitle')?.value.trim();
        const prompt = document.getElementById('newAnalysisPrompt')?.value.trim();

        if (!title || !prompt) {
            alert("분석 이름과 내용을 모두 입력해주세요.");
            return;
        }

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
    "formula": "prev_plus_n" | "prev_minus_n" | "carryover" | "draw_date_end" | "math_expression",
    "value": 0,
    "expression": "...",
    
    // For "ai_model_top" or "ai_model_bottom" type:
    "model": "lstm" | "xgboost" | "cnn" | "transformer" | "markov" | "ensemble",
    "count": 10
  }
}

# Logic Guide
1. If the user asks for specific fixed numbers (e.g., "Analyze 1, 5, 10"), set type to "static" and fill "target_numbers".
2. If the user asks for a rule relative to previous rounds (e.g., "+ 2", "- 1", "Carryover"), set type to "dynamic" and appropriate formula.
3. [IMPORTANT] If the request mentions AI, Deep Learning, Recommendation, Fixed, or Excluded (e.g., "AI 고정수", "제외수 분석"), set type to "ai_ensemble_fixed" or "ai_ensemble_excluded".
4. [IMPORTANT] If the request mentions a specific model or ranking (e.g., "LSTM 상위 10개", "XGB 하위 5개"), set type to "ai_model_top" or "ai_model_bottom", and specify "model" and "count" in "rules".

# Response
Return ONLY the JSON. No markdown.
`;

            // Edge Function 호출
            const { data, error } = await window.supabaseClient.functions.invoke('analyze-lotto', {
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
            else if (formula === 'math_expression') ruleText = `규칙: 수식 ( ${data.rules?.expression || 'x'} )`;

            if (ruleTextEl) ruleTextEl.textContent = ruleText;

        } else if (data.type.startsWith('ai_')) {
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
                    if (n <= 10) return '#fbc400';
                    if (n <= 20) return '#69c8f2';
                    if (n <= 30) return '#ff7272';
                    if (n <= 40) return '#aaaaaa';
                    return '#b0d840';
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
            const { data, error } = await window.supabaseClient
                .from('ai_custom_analyses')
                .insert([{
                    title: tempAnalysisData.title,
                    prompt: tempAnalysisData.prompt,
                    description: tempAnalysisData.description,
                    type: tempAnalysisData.type,
                    // [FIX] dynamic 타입일 경우 target_numbers가 null일 수 있으므로 빈 배열 처리
                    target_numbers: tempAnalysisData.target_numbers || [],
                    rules: tempAnalysisData.rules,
                    filter_config: { min: 1, max: 3, enabled: false }
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
