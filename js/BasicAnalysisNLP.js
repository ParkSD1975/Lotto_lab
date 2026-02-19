/**
 * BasicAnalysisNLP.js
 * 기초분석 페이지 공통 NLP 컴포넌트
 * 
 * - NLPInputComponent UI 주입
 * - 공통 Intent 처리 (네비게이션 등)
 * - 페이지별 Intent 위임 (하이라이트, 필터)
 */

class BasicAnalysisNLP {
    constructor(targetSelector, options = {}) {
        this.targetSelector = targetSelector;
        this.options = {
            onHighlight: options.onHighlight || null, // (params) => {}
            onFilter: options.onFilter || null,       // (params) => {}
            onNavigate: options.onNavigate || null,   // (round) => {}
            ...options
        };

        this.init();
    }

    init() {
        const target = document.querySelector(this.targetSelector);
        if (!target) {
            console.warn(`[BasicAnalysisNLP] Target selector "${this.targetSelector}" not found.`);
            return;
        }

        // 1. NLP UI 컨테이너 생성 및 주입
        const containerId = 'basic-nlp-container';
        let container = document.getElementById(containerId);

        if (!container) {
            container = document.createElement('div');
            container.id = containerId;
            target.innerHTML = ''; // 기존 내용(예: 구형 AI 채팅) 제거
            target.appendChild(container); // 타겟 안에 삽입
        }

        // 2. NLPInputComponent 초기화
        if (window.initNLPInput) {
            this.nlpComponent = window.initNLPInput(containerId, {
                placeholder: '분석 조건을 말해보세요...',
                onAnalysisCreate: this.handleCommand.bind(this),
                showExamples: this.options.showExamples === true, // Default to false unless explicitly true
                autoFocus: false
            });
        } else {
            console.error('[BasicAnalysisNLP] NLPInputComponent not loaded.');
            container.innerHTML = '<div class="text-red-500">NLP 컴포넌트 로드 실패</div>';
        }
    }

    /**
     * NLP 명령 처리 핸들러
     * @param {Object} params 추출된 파라미터
     * @param {string} intent 의도
     */
    handleCommand(params, intent) {
        console.log(`[BasicNLP] Command: ${intent}`, params);

        switch (intent) {
            case 'navigate':
                this.handleNavigation(params);
                break;
            case 'highlight_property':
                if (this.options.onHighlight) {
                    this.options.onHighlight(params);
                    this.showFeedback('하이라이트가 적용되었습니다.');
                }
                break;
            case 'filter_data':
                if (this.options.onFilter) {
                    this.options.onFilter(params);
                    this.showFeedback('필터가 적용되었습니다.');
                }
                break;
            // Analysis Creation Intents (Redirect to Custom Analysis)
            case 'static_numbers':
            case 'dynamic_formula':
            case 'group_condition':
            case 'statistical':
                this.showFeedback('커스텀 분석 페이지로 이동합니다...');
                if (typeof window.createAnalysis === 'function') {
                    window.createAnalysis(params);
                } else {
                    console.error('[BasicNLP] createAnalysis function not found.');
                    alert('분석 생성 기능을 사용할 수 없습니다.');
                }
                break;
            case 'explain_view':
                alert('곧 제공될 기능입니다: 화면 설명');
                break;
            default:
                // 알 수 없는 명령은 페이지별 커스텀 핸들러로 전달 시도
                if (this.options.onCustomCommand) {
                    this.options.onCustomCommand(intent, params);
                } else {
                    console.warn(`[BasicNLP] Unhandled intent: ${intent}`);
                }
        }
    }

    handleNavigation(params) {
        let targetRound = params.targetRound;

        // 'latest'인 경우 최신 회차 찾기 (UI 의존성 있음)
        if (targetRound === 'latest') {
            // TODO: 페이지에서 최신 회차 정보를 가져오는 방법 표준화 필요
            // 여기서는 단순히 최상단으로 스크롤
            const tableContainer = document.querySelector('.table-scroll') || document.querySelector('.overflow-y-auto');
            if (tableContainer) tableContainer.scrollTop = 0;
            return;
        }

        if (this.options.onNavigate) {
            this.options.onNavigate(targetRound);
            this.showFeedback(`${targetRound}회차로 이동했습니다.`);
            return;
        }

        // 기본 네비게이션: row-{round} 아이디를 가진 요소로 스크롤
        const rowId = `row-${targetRound}`;
        const row = document.getElementById(rowId);
        if (row) {
            row.scrollIntoView({ behavior: 'smooth', block: 'center' });
            // 일시적 강조 효과
            row.classList.add('bg-yellow-100');
            setTimeout(() => row.classList.remove('bg-yellow-100'), 2000);
            this.showFeedback(`${targetRound}회차로 이동했습니다.`);
        } else {
            console.warn(`[BasicNLP] target round row not found: ${rowId}`);
            // 리스트에 없을 수도 있으므로 페이지 리로드나 데이터 로드 요청이 필요할 수 있음
            // (여기서는 간단히 알림만)
            alert(`${targetRound}회차 데이터가 현재 목록에 없습니다.`);
        }
    }

    showFeedback(message) {
        // NLPInputComponent에 피드백 표시 기능이 있다면 호출
        // 현재는 없으므로 Toast나 간단한 DOM 조작 사용 가능
        // TODO: NLPInputComponent에 showTemporaryMessage 기능 추가 제안 필요
        console.log('[BasicNLP] Feedback:', message);
    }
}

// 전역 노출
window.BasicAnalysisNLP = BasicAnalysisNLP;
