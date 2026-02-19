/**
 * Lotto AI - NLP 입력 UI 컴포넌트
 * NLPInputComponent.js
 * 
 * 사용법:
 * <div id="nlp-input-container"></div>
 * <script>
 *   window.initNLPInput('nlp-input-container', {
 *     onAnalysisCreate: (params) => { ... },
 *     placeholder: '분석 조건을 입력하세요...'
 *   });
 * </script>
 */

class NLPInputComponent {
    static instance = null;

    static init(containerId, options = {}) {
        this.instance = new NLPInputComponent(containerId, options);
        return this.instance;
    }

    static focus() {
        if (this.instance) this.instance.focus();
    }

    constructor(containerId, options = {}) {
        this.container = document.getElementById(containerId);
        if (!this.container) {
            console.error(`[NLPInput] Container not found: ${containerId}`);
            return;
        }

        this.options = {
            placeholder: options.placeholder || '분석 조건을 자연어로 입력하세요...',
            onAnalysisCreate: options.onAnalysisCreate || null,
            showExamples: options.showExamples !== false,
            autoFocus: options.autoFocus || false
        };

        this.currentResult = null;
        this.debounceTimer = null;

        this.render();
        this.bindEvents();

        if (this.options.autoFocus) {
            setTimeout(() => this.container.querySelector('#nlpInput')?.focus(), 100);
        }
    }

    render() {
        this.container.innerHTML = `
            <div class="nlp-input-wrapper relative">
                <!-- 메인 입력 영역 -->
                <div class="relative group">
                    <input type="text" 
                           id="nlpInput"
                           placeholder="${this.options.placeholder}"
                           class="w-full px-6 py-4 text-[15px] border border-gray-200 rounded-2xl
                                  focus:border-blue-400 focus:ring-4 focus:ring-blue-50/50
                                  hover:border-gray-300
                                  transition-all duration-300 outline-none
                                  placeholder:text-gray-300 placeholder:font-medium"
                           autocomplete="off"
                           spellcheck="false">
                    <button id="nlpSubmit" 
                            class="absolute right-5 top-1/2 -translate-y-1/2 
                                   text-blue-500 hover:text-blue-600
                                   active:scale-90
                                   transition-all duration-200 
                                   flex items-center justify-center
                                   disabled:opacity-30 disabled:cursor-not-allowed"
                            title="분석 실행">
                        <svg viewBox="0 0 24 24" class="w-6 h-6" fill="none" xmlns="http://www.w3.org/2000/svg">
                            <path d="M2.01 21L23 12L2.01 3L2 10L17 12L2 14L2.01 21Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                        </svg>
                    </button>
                </div>

                <!-- 자동 완성 드롭다운 -->
                <div id="autocompleteDropdown" 
                     class="hidden absolute top-full left-0 right-0 mt-2 
                            bg-white border border-gray-200 rounded-xl 
                            shadow-xl shadow-gray-200/50 z-50 overflow-hidden
                            max-h-80 overflow-y-auto">
                </div>

                <!-- 예시 버튼들 -->
                ${this.options.showExamples ? `
                <div id="exampleButtons" class="flex flex-wrap gap-2 mt-3">
                    <span class="text-xs text-gray-400 self-center mr-1">예시:</span>
                    <button class="example-btn px-3 py-1.5 text-xs bg-gray-100 hover:bg-blue-100 hover:text-blue-700 rounded-full transition-colors" data-example="3, 7, 15, 22, 35 번호 분석">번호 분석</button>
                    <button class="example-btn px-3 py-1.5 text-xs bg-gray-100 hover:bg-blue-100 hover:text-blue-700 rounded-full transition-colors" data-example="전회차 +1 패턴 분석">전회차 +1</button>
                    <button class="example-btn px-3 py-1.5 text-xs bg-gray-100 hover:bg-blue-100 hover:text-blue-700 rounded-full transition-colors" data-example="이월 번호 분석">이월 분석</button>
                    <button class="example-btn px-3 py-1.5 text-xs bg-gray-100 hover:bg-blue-100 hover:text-blue-700 rounded-full transition-colors" data-example="미출현 5회 이상 번호">미출현 번호</button>
                    <button class="example-btn px-3 py-1.5 text-xs bg-gray-100 hover:bg-blue-100 hover:text-blue-700 rounded-full transition-colors" data-example="1~15 범위 2개, 30~45 범위 2개 조합">그룹 조합</button>
                </div>
                ` : ''}

                <!-- 처리 결과/피드백 영역 -->
                <div id="nlpFeedback" class="mt-4 hidden">
                </div>

                <!-- 로딩 인디케이터 -->
                <div id="nlpLoading" class="hidden mt-4">
                    <div class="flex items-center justify-center gap-3 py-4">
                        <div class="w-5 h-5 border-2 border-blue-600 border-t-transparent rounded-full animate-spin"></div>
                        <span class="text-sm text-gray-500">분석 중...</span>
                    </div>
                </div>
            </div>

            <style>
                .nlp-input-wrapper input:focus::placeholder {
                    opacity: 0.5;
                }
                
                .autocomplete-item {
                    transition: all 0.15s ease;
                }
                
                .autocomplete-item:hover {
                    transform: translateX(4px);
                }
                
                .example-btn:active {
                    transform: scale(0.95);
                }
                
                @keyframes slideUp {
                    from {
                        opacity: 0;
                        transform: translateY(10px);
                    }
                    to {
                        opacity: 1;
                        transform: translateY(0);
                    }
                }
                
                .feedback-animate {
                    animation: slideUp 0.3s ease-out;
                }
            </style>
        `;
    }

    bindEvents() {
        const input = this.container.querySelector('#nlpInput');
        const submitBtn = this.container.querySelector('#nlpSubmit');
        const dropdown = this.container.querySelector('#autocompleteDropdown');

        // 입력 시 자동 완성 (디바운스)
        input.addEventListener('input', (e) => {
            clearTimeout(this.debounceTimer);
            this.debounceTimer = setTimeout(() => {
                this.handleAutocomplete(e.target.value);
            }, 150);
        });

        // 키보드 이벤트
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.isComposing) {
                e.preventDefault();
                this.processInput(input.value);
            }
            if (e.key === 'Escape') {
                this.hideAutocomplete();
            }
            if (e.key === 'ArrowDown' && !dropdown.classList.contains('hidden')) {
                e.preventDefault();
                this.navigateAutocomplete(1);
            }
            if (e.key === 'ArrowUp' && !dropdown.classList.contains('hidden')) {
                e.preventDefault();
                this.navigateAutocomplete(-1);
            }
        });

        // 제출 버튼
        submitBtn.addEventListener('click', () => this.processInput(input.value));

        // 예시 버튼
        this.container.querySelectorAll('.example-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                input.value = btn.dataset.example;
                input.focus();
                this.processInput(btn.dataset.example);
            });
        });

        // 외부 클릭 시 드롭다운 닫기
        document.addEventListener('click', (e) => {
            if (!this.container.contains(e.target)) {
                this.hideAutocomplete();
            }
        });
    }

    handleAutocomplete(value) {
        if (value.length < 2) {
            this.hideAutocomplete();
            return;
        }

        if (!window.nlpProcessor) {
            console.warn('[NLPInput] nlpProcessor not found');
            return;
        }

        const suggestions = window.nlpProcessor.autocomplete(value);
        this.showAutocomplete(suggestions);
    }

    showAutocomplete(suggestions) {
        const dropdown = this.container.querySelector('#autocompleteDropdown');

        if (!suggestions || suggestions.length === 0) {
            this.hideAutocomplete();
            return;
        }

        dropdown.innerHTML = suggestions.map((s, i) => `
            <div class="autocomplete-item px-4 py-3 cursor-pointer border-b border-gray-50 last:border-0
                        hover:bg-gradient-to-r hover:from-blue-50 hover:to-transparent
                        ${i === 0 ? 'bg-blue-50/50' : ''}"
                 data-index="${i}"
                 data-value="${this.escapeHtml(s.suggestion)}">
                <div class="font-medium text-gray-900 text-sm">${this.highlightMatch(s.suggestion)}</div>
                <div class="text-xs text-gray-500 mt-0.5">${s.description}</div>
            </div>
        `).join('');

        dropdown.classList.remove('hidden');

        // 클릭 이벤트
        dropdown.querySelectorAll('.autocomplete-item').forEach(item => {
            item.addEventListener('click', () => {
                const input = this.container.querySelector('#nlpInput');
                input.value = item.dataset.value;
                this.hideAutocomplete();
                input.focus();
            });
        });
    }

    highlightMatch(text) {
        const input = this.container.querySelector('#nlpInput')?.value || '';
        if (!input) return text;

        const regex = new RegExp(`(${this.escapeRegex(input)})`, 'gi');
        return text.replace(regex, '<mark class="bg-yellow-200 px-0.5 rounded">$1</mark>');
    }

    hideAutocomplete() {
        this.container.querySelector('#autocompleteDropdown').classList.add('hidden');
    }

    navigateAutocomplete(direction) {
        const dropdown = this.container.querySelector('#autocompleteDropdown');
        const items = dropdown.querySelectorAll('.autocomplete-item');
        if (items.length === 0) return;

        const currentIndex = Array.from(items).findIndex(item => item.classList.contains('bg-blue-50/50'));
        let newIndex = currentIndex + direction;

        if (newIndex < 0) newIndex = items.length - 1;
        if (newIndex >= items.length) newIndex = 0;

        items.forEach((item, i) => {
            item.classList.toggle('bg-blue-50/50', i === newIndex);
        });

        items[newIndex].scrollIntoView({ block: 'nearest' });
    }

    async processInput(value) {
        if (!value.trim()) return;

        const feedbackEl = this.container.querySelector('#nlpFeedback');
        const loadingEl = this.container.querySelector('#nlpLoading');

        // 로딩 표시
        this.hideAutocomplete();
        feedbackEl.classList.add('hidden');
        loadingEl.classList.remove('hidden');

        // 약간의 딜레이로 UX 개선
        await new Promise(r => setTimeout(r, 200));

        if (!window.nlpProcessor) {
            this.displayError('NLP 엔진을 로드할 수 없습니다.');
            loadingEl.classList.add('hidden');
            return;
        }

        const result = window.nlpProcessor.process(value);
        this.currentResult = result;

        loadingEl.classList.add('hidden');
        this.displayFeedback(result);
    }

    displayFeedback(result) {
        const feedbackEl = this.container.querySelector('#nlpFeedback');
        feedbackEl.classList.remove('hidden');
        feedbackEl.classList.add('feedback-animate');

        if (result.success) {
            feedbackEl.innerHTML = `
                <div class="bg-gradient-to-r from-green-50 to-emerald-50 border border-green-200 rounded-2xl p-5">
                    <div class="flex items-start gap-3">
                        <div class="w-10 h-10 bg-green-500 rounded-xl flex items-center justify-center flex-shrink-0">
                            <svg xmlns="http://www.w3.org/2000/svg" class="w-6 h-6 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
                            </svg>
                        </div>
                        <div class="flex-1">
                            <div class="font-bold text-green-900 mb-1">분석 조건이 인식되었습니다</div>
                            <div class="text-sm text-green-700 space-y-1">
                                <div><span class="font-medium">유형:</span> ${this.getTypeLabel(result.intent)}</div>
                                <div><span class="font-medium">신뢰도:</span> ${Math.round(result.confidence * 100)}%</div>
                                ${this.renderParams(result.params)}
                            </div>
                            ${result.warnings.length > 0 ? `
                                <div class="mt-3 p-2 bg-yellow-100 rounded-lg text-yellow-800 text-sm">
                                    ⚠️ ${result.warnings.map(w => w.message).join(' | ')}
                                </div>
                            ` : ''}
                        </div>
                    </div>
                    <div class="flex gap-3 mt-4 pt-4 border-t border-green-200">
                        <button id="createAnalysisBtn"
                                class="flex-1 px-4 py-2.5 bg-green-600 hover:bg-green-700 text-white rounded-xl font-bold transition-colors shadow-lg shadow-green-600/30">
                            이 조건으로 분석 생성
                        </button>
                        <button id="modifyConditionBtn"
                                class="px-4 py-2.5 bg-white border border-green-300 text-green-700 rounded-xl font-medium hover:bg-green-50 transition-colors">
                            수정
                        </button>
                    </div>
                </div>
            `;

            // 버튼 이벤트 바인딩
            feedbackEl.querySelector('#createAnalysisBtn').addEventListener('click', () => {
                this.createAnalysis(result.params, result.intent);
            });
            feedbackEl.querySelector('#modifyConditionBtn').addEventListener('click', () => {
                this.container.querySelector('#nlpInput').focus();
            });
        }
        else {
            feedbackEl.innerHTML = `
                <div class="bg-gradient-to-r from-red-50 to-orange-50 border border-red-200 rounded-2xl p-5">
                    <div class="flex items-start gap-3">
                        <div class="w-10 h-10 bg-red-500 rounded-xl flex items-center justify-center flex-shrink-0">
                            <svg xmlns="http://www.w3.org/2000/svg" class="w-6 h-6 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                            </svg>
                        </div>
                        <div class="flex-1">
                            <div class="font-bold text-red-900 mb-1">${result.errors[0]?.message || '명령을 이해하지 못했습니다'}</div>
                            <div class="text-sm text-red-700">아래 예시를 참고하여 다시 입력해주세요.</div>
                        </div>
                    </div>
                    
                    ${result.suggestions.length > 0 ? `
                        <div class="mt-4 pt-4 border-t border-red-200">
                            <div class="text-sm font-medium text-gray-700 mb-3">💡 이런 명령은 어떠세요?</div>
                            <div class="space-y-2">
                                ${result.suggestions.map(s => `
                                    <div class="suggestion-item bg-white rounded-xl p-3 border border-gray-200 cursor-pointer hover:border-blue-300 hover:shadow-md transition-all group"
                                         data-example="${this.escapeHtml(s.example)}">
                                        <div class="text-blue-600 font-medium group-hover:text-blue-700">${s.example}</div>
                                        <div class="text-xs text-gray-500 mt-1">${s.description}</div>
                                    </div>
                                `).join('')}
                            </div>
                        </div>
                    ` : ''}
                </div>
            `;

            // 제안 클릭 이벤트
            feedbackEl.querySelectorAll('.suggestion-item').forEach(item => {
                item.addEventListener('click', () => {
                    const input = this.container.querySelector('#nlpInput');
                    input.value = item.dataset.example;
                    input.focus();
                    this.processInput(item.dataset.example);
                });
            });
        }
    }

    displayError(message) {
        const feedbackEl = this.container.querySelector('#nlpFeedback');
        feedbackEl.classList.remove('hidden');
        feedbackEl.innerHTML = `
            <div class="bg-red-50 border border-red-200 rounded-xl p-4 text-red-800">
                <strong>오류:</strong> ${message}
            </div>
        `;
    }

    renderParams(params) {
        const parts = [];

        if (params.target_numbers?.length > 0) {
            parts.push(`<div><span class="font-medium">번호:</span> ${params.target_numbers.join(', ')}</div>`);
        }

        if (params.rules) {
            const formula = params.rules.formula;
            const value = params.rules.value;
            let formulaText = '';

            switch (formula) {
                case 'prev_plus_n': formulaText = `전회차 +${value}`; break;
                case 'prev_minus_n': formulaText = `전회차 -${value}`; break;
                case 'carryover': formulaText = '이월 (전회차 동일)'; break;
                case 'draw_date_end': formulaText = '추첨일 끝수'; break;
                case 'math_expression': formulaText = `수식: ${params.rules.expression}`; break;
                default: formulaText = formula;
            }

            parts.push(`<div><span class="font-medium">수식:</span> ${formulaText}</div>`);
        }

        if (params.config?.groups?.length > 0) {
            const groupTexts = params.config.groups.map(g => {
                if (g.type === 'hot') return '고온수';
                if (g.type === 'cold') return '저온수';
                return `${g.name} (${g.numbers.length}개)`;
            });
            parts.push(`<div><span class="font-medium">그룹:</span> ${groupTexts.join(', ')}</div>`);
        }

        return parts.join('');
    }

    getTypeLabel(intent) {
        const labels = {
            'static_numbers': '고정 번호 분석',
            'dynamic_formula': '동적 수식 분석',
            'group_condition': '그룹 조건 분석',
            'statistical': '통계 기반 분석',
            'filter_condition': '필터 조건'
        };
        return labels[intent] || intent;
    }

    createAnalysis(params, intent) {
        // 콜백이 있으면 호출
        if (this.options.onAnalysisCreate) {
            this.options.onAnalysisCreate(params, intent);
        } else {
            // 기본 동작: 콘솔 출력 또는 전역 함수 호출
            console.log('[NLPInput] Analysis params:', params);

            if (typeof window.createAnalysis === 'function') {
                window.createAnalysis(params);
            }
        }
    }

    // 유틸리티 메서드
    escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    escapeRegex(str) {
        return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }

    // Public API
    getValue() {
        return this.container.querySelector('#nlpInput')?.value || '';
    }

    setValue(value) {
        const input = this.container.querySelector('#nlpInput');
        if (input) input.value = value;
    }

    clear() {
        this.setValue('');
        this.container.querySelector('#nlpFeedback')?.classList.add('hidden');
        this.currentResult = null;
    }

    focus() {
        this.container.querySelector('#nlpInput')?.focus();
    }
}

// 글로벌 초기화 함수
window.initNLPInput = function (containerId, options) {
    return new NLPInputComponent(containerId, options);
};

// 글로벌 분석 생성 함수 (customAnalysis.js와 연동)
window.createAnalysis = window.createAnalysis || async function (params) {
    console.log('[NLPInput] Creating analysis with params:', params);

    // Supabase 저장 로직 (기존 시스템과 연동)
    if (!window.supabaseClient) {
        alert('데이터베이스 연결이 필요합니다.');
        return;
    }

    try {
        // 분석 제목 생성
        let title = '';
        switch (params.type) {
            case 'static':
                title = `번호 분석: ${params.target_numbers?.slice(0, 3).join(', ')}...`;
                break;
            case 'dynamic':
                title = `동적 분석: ${params.rules?.formula}`;
                break;
            case 'group':
                title = `그룹 분석: ${params.config?.groups?.length || 0}개 그룹`;
                // [New] 그룹 번호 자동 채움 (번호가 비어있을 경우 상구 상수로 보정)
                if (params.config?.groups) {
                    params.config.groups.forEach(group => {
                        if (!group.numbers || group.numbers.length === 0) {
                            const standardKey = Object.keys(window.LOTTO_CONSTANTS?.GROUPS || {}).find(k => group.name.includes(k));
                            if (standardKey) {
                                group.numbers = window.LOTTO_CONSTANTS.GROUPS[standardKey];
                                console.log(`[createAnalysis] Auto-populated group numbers for: ${group.name}`);
                            }
                        }
                    });
                }
                break;
            default:
                title = '새 분석';
        }

        // DB 스키마에 config 컬럼이 없으므로 rules에 통합 저장
        const mergedRules = {
            ...(params.rules || {}),
            ...(params.config ? { config: params.config } : {})
        };

        const { data, error } = await window.supabaseClient
            .from('ai_custom_analyses')
            .insert({
                title: title,
                type: params.type,
                target_numbers: params.target_numbers || [],
                rules: mergedRules,
                filter_config: params.filter_config || { min: 1, max: 3, enabled: false },
                description: ''
            })
            .select()
            .single();

        if (error) throw error;

        // [MOD] return data for GlobalModal to handle redirection optionally, or default to current behavior
        console.log('[NLPInput] Analysis created:', data);
        return data;

    } catch (err) {
        console.error('[NLPInput] Failed to create analysis:', err);
        alert('분석 생성에 실패했습니다: ' + err.message);
        return null;
    }
};


