/**
 * AIProxy.js
 * Python(LangChain) 서버 우선 통신 및 V3 심층 분석 호출
 */
(function () {
    const BASE_URLS = [
        (window.LANGCHAIN_CONFIG && window.LANGCHAIN_CONFIG.URL) || 'https://lotto-api-server.onrender.com'
    ];
    let CURRENT_BASE_URL = BASE_URLS[0];

    window.AIProxy = {
        async checkHealth(force = false) {
            try {
                const controller = new AbortController();
                // Render cold start accommodation
                const timeoutId = setTimeout(() => controller.abort(), 15000);
                const res = await fetch(`${CURRENT_BASE_URL}/health`, { method: 'GET', signal: controller.signal });
                clearTimeout(timeoutId);
                return res.ok;
            } catch (e) {
                return false;
            }
        },

        // ★ [핵심] V3 백엔드(메모 적용) 호출 함수
        async getDeepAnalysis(roundNum) {
            try {
                const query = roundNum ? `?round_num=${roundNum}` : '';
                const url = `${CURRENT_BASE_URL}/api/deep-analysis/v3/analysis${query}`;
                console.log(`📡 [AIProxy] V3 딥러닝 심층 분석 요청: ${url}`);

                const res = await fetch(url, {
                    method: 'GET',
                    headers: { 'Content-Type': 'application/json' }
                });

                if (!res.ok) throw new Error("분석 데이터를 가져올 수 없습니다.");
                return await res.json();
            } catch (e) {
                console.error("딥러닝 분석 API 호출 실패:", e);
                return null;
            }
        },

        async explainNumber(number, userQuery) {
            try {
                const res = await fetch(`${CURRENT_BASE_URL}/api/explain`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ number, user_query: userQuery })
                });
                return await res.json();
            } catch (e) {
                return { error: "설명을 가져올 수 없습니다." };
            }
        },

        async interpret(query) {
            try {
                const res = await fetch(`${CURRENT_BASE_URL}/api/interpret/`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ query: query })
                });
                return res.ok ? await res.json() : null;
            } catch (e) {
                return null;
            }
        }
    };
})();
