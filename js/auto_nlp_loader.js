/**
 * Lotto Lab Self-Discovery NLP Phase 2 - Auto NLP Loader
 *
 * 전 페이지 공통: window.autoNLP 초기화
 * - AutoNLPMatcher.js 로드 후 자동 초기화
 * - 'autoNLPReady' 커스텀 이벤트 발생
 *
 * @version 1.0.0
 * @date 2026-05-08
 */

(async () => {
    // 중복 로드 방지
    if (window.autoNLP) {
        console.log('[AutoNLP] Already loaded');
        return;
    }

    // AutoNLPMatcher 클래스 확인
    if (!window.AutoNLPMatcher) {
        console.error('[AutoNLP] AutoNLPMatcher class not found. Please include AutoNLPMatcher.js before this script.');
        return;
    }

    // 인스턴스 생성 + 로드
    window.autoNLP = new window.AutoNLPMatcher();

    try {
        const startTime = performance.now();
        await window.autoNLP.load();
        const loadTime = Math.round(performance.now() - startTime);

        const stats = window.autoNLP.stats();
        console.log('[AutoNLP] Loaded successfully:', {
            loadTime: `${loadTime}ms`,
            version: stats.version,
            filters: stats.filters,
            models: stats.models,
            operations: stats.operations,
            statistics: stats.statistics,
            time_windows: stats.time_windows,
            total_aliases: stats.total_aliases
        });

        // 커스텀 이벤트 발생
        window.dispatchEvent(new CustomEvent('autoNLPReady', {
            detail: { stats, loadTime }
        }));

    } catch (error) {
        console.error('[AutoNLP] Load failed:', error);
        window.autoNLP = null; // graceful fallback
    }
})();
