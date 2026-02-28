/**
 * AIProxy.js
 * Python(LangChain) 서버 우선, 실패 시 Supabase Edge Function 자동 폴백
 * * 역할:
 * 1. Python 백엔드 헬스 체크
 * 2. 분석 요청 (RAG + 딥러닝) 전송
 * 3. Python 실패 시 Supabase Edge Function 폴백
 * 4. 예측 데이터 및 설명 요청 전송
 */

(function () {
    // 설정 가져오기 (config.js가 로드되지 않았을 경우를 대비한 기본값)
    // [Mod] 기본값을 배열로 관리하여 순차 시도 (localhost -> 127.0.0.1)
    const BASE_URLS = [
        (window.LANGCHAIN_CONFIG && window.LANGCHAIN_CONFIG.URL) || 'https://lotto-api-server.onrender.com'
    ];
    let CURRENT_BASE_URL = BASE_URLS[0];
    const TIMEOUT = (window.LANGCHAIN_CONFIG && window.LANGCHAIN_CONFIG.TIMEOUT) || 30000;

    window.AIProxy = {
        /**
         * 메인 분석 실행 (Python 우선 → Supabase 폴백)
         */
        async invoke(config) {
            // 1. Python RAG 서버 시도
            try {
                const isAlive = await this.checkHealth();
                if (isAlive) {
                    console.log("🚀 [AIProxy] Python RAG 서버로 분석 요청 전송...", config);
                    const controller = new AbortController();
                    const timeoutId = setTimeout(() => controller.abort(), TIMEOUT);
                    const response = await fetch(`${CURRENT_BASE_URL}/api/analyze`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            prompt: config.prompt,
                            analysis_type: config.analysisType || 'general',
                            target_round: config.targetRound || 0,
                            subject_round: config.subjectRound || 0,
                            response_style: config.responseStyle || 'default',
                            history_data: config.historyData,
                            topic: config.topic || ''
                        }),
                        signal: controller.signal
                    });
                    clearTimeout(timeoutId);

                    if (response.ok) {
                        const data = await response.json();
                        console.log("✅ [AIProxy] Python RAG 분석 완료:", data);
                        return data;
                    }
                    console.warn("⚠️ [AIProxy] Python 서버 응답 오류, Edge Function 폴백 시도...");
                } else {
                    console.warn("⚠️ [AIProxy] Python 서버 미응답, Edge Function 폴백 시도...");
                }
            } catch (pythonErr) {
                console.warn("⚠️ [AIProxy] Python 요청 실패, Edge Function 폴백 시도...", pythonErr.message);
            }

            // 2. Supabase Edge Function 폴백
            return await this.invokeEdgeFunction(config);
        },

        /**
         * Supabase Edge Function 폴백 (타임아웃 포함)
         */
        async invokeEdgeFunction(config) {
            if (!window.supabaseClient) {
                throw new Error("Supabase 클라이언트가 초기화되지 않았습니다.");
            }

            console.log("📡 [AIProxy] Supabase Edge Function(analyze-lotto)으로 폴백 요청...");

            // 타임아웃 래퍼 (TIMEOUT 설정값 사용, 기본 30초)
            const edgePromise = window.supabaseClient.functions.invoke('analyze-lotto', {
                body: { context: config.prompt }
            });

            const timeoutPromise = new Promise((_, reject) =>
                setTimeout(() => reject(new Error("Edge Function 타임아웃 (" + TIMEOUT + "ms)")), TIMEOUT)
            );

            const response = await Promise.race([edgePromise, timeoutPromise]);

            if (response.error) {
                throw new Error("Edge Function 오류: " + (response.error.message || response.error));
            }

            let data = response.data;

            // 문자열 응답이면 JSON 파싱 시도
            if (typeof data === 'string') {
                try { data = JSON.parse(data); } catch (e) { /* 그대로 사용 */ }
            }

            console.log("✅ [AIProxy] Edge Function 폴백 분석 완료:", data);
            return data;
        },

        /**
         * 서버 헬스 체크 (중복 요청 및 콘솔 스팸 방지 로직 추가)
         */
        _isServerDown: false,
        _lastCheckTime: 0,

        async checkHealth(force = false) {
            const now = Date.now();
            if (!force && this._isServerDown && (now - this._lastCheckTime < 30000)) return false;

            for (const url of BASE_URLS) {
                try {
                    const controller = new AbortController();
                    const timeoutId = setTimeout(() => controller.abort(), 5000);

                    const res = await fetch(`${url}/health`, { method: 'GET', signal: controller.signal });
                    clearTimeout(timeoutId);

                    if (res.ok) {
                        CURRENT_BASE_URL = url; // 성공한 URL을 현재 URL로 확정
                        this._isServerDown = false;
                        this._lastCheckTime = now;
                        console.log(`✅ Python Server Connected: ${CURRENT_BASE_URL}`);
                        return true;
                    }
                } catch (e) {
                    console.warn(`⚠️ Connection Failed: ${url}`);
                }
            }

            console.warn("❌ All Python Server Connection Attempts Failed.");
            this._isServerDown = true;
            this._lastCheckTime = now;
            return false;
        },

        /**
         * 특정 회차 딥러닝 예측 데이터 조회
         */
        async getPredictions(round) {
            try {
                const res = await fetch(`${BASE_URL}/api/predictions/${round}`);
                if (!res.ok) return null;
                return await res.json();
            } catch (e) {
                console.error("예측 데이터 조회 실패:", e);
                return null;
            }
        },

        /**
         * 번호 추천 근거 설명 (XAI)
         */
        async explainNumber(number, userQuery) {
            try {
                const res = await fetch(`${CURRENT_BASE_URL}/api/explain`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ number, user_query: userQuery })
                });
                return await res.json();
            } catch (e) {
                console.error("설명 요청 실패:", e);
                return { error: "설명을 가져올 수 없습니다." };
            }
        },

        /**
         * [New] 자연어 명령 해석 요청 (NLP Fallback)
         */
        async interpret(query) {
            try {
                // 1. 서버 생존 확인 (생략 가능하나 안전을 위해)
                const isAlive = await this.checkHealth();
                if (!isAlive) return null;

                const response = await fetch(`${CURRENT_BASE_URL}/api/interpret/`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ query: query })
                });

                if (!response.ok) return null;
                return await response.json();
            } catch (e) {
                console.warn("AI Interpretation failed:", e);
                return null;
            }
        }
    };

    console.log("🔧 [AIProxy] 모듈이 로드되었습니다. (Target: " + CURRENT_BASE_URL + ")");
})();
