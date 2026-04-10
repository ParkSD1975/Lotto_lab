/**
 * AIProxy.js
 * Python(LangChain) 서버 우선 통신, V3 심층 분석 및 기초 분석 폴백 처리
 */
(function () {
    const BASE_URLS = [
        (window.LANGCHAIN_CONFIG && window.LANGCHAIN_CONFIG.URL) || 'http://127.0.0.1:8000'
    ];
    let CURRENT_BASE_URL = BASE_URLS[0];
    const TIMEOUT = (window.LANGCHAIN_CONFIG && window.LANGCHAIN_CONFIG.TIMEOUT) || 60000;

    window.AIProxy = {
        _isServerDown: false,
        _lastCheckTime: 0,
        _keepAliveTimer: null,

        /**
         * 콜드스타트 웜업: 10초 간격으로 최대 12회 폴링 (총 최대 120초)
         * 단일 긴 fetch 대신 짧은 요청 반복으로 안정성 확보
         * @param {function} onProgress - 경과초 전달 (UI 업데이트용)
         */
        async warmup(onProgress) {
            const POLL_TIMEOUT = 10000;  // 회당 10초
            const MAX_ATTEMPTS = 12;     // 최대 12회 (120초)
            console.log('🔥 [AIProxy] 서버 웜업 시작 (최대 120초, 10초 간격 폴링)...');

            let elapsed = 0;
            let success = false;

            for (const url of BASE_URLS) {
                for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
                    try {
                        const controller = new AbortController();
                        const timeoutId = setTimeout(() => controller.abort(), POLL_TIMEOUT);
                        const res = await fetch(`${url}/health`, { method: 'GET', signal: controller.signal });
                        clearTimeout(timeoutId);
                        if (res.ok) {
                            CURRENT_BASE_URL = url;
                            this._isServerDown = false;
                            this._lastCheckTime = Date.now();
                            success = true;
                            console.log(`✅ [AIProxy] 서버 웜업 완료 (${elapsed}초 경과, ${attempt}회 시도)`);
                            break;
                        }
                    } catch (e) {
                        elapsed += Math.round(POLL_TIMEOUT / 1000);
                        if (onProgress) onProgress(elapsed);
                        console.log(`🔄 [AIProxy] 웜업 재시도 ${attempt}/${MAX_ATTEMPTS} (${elapsed}초 경과)`);
                    }
                    if (success) break;
                }
                if (success) break;
            }

            if (!success) {
                this._isServerDown = true;
                this._lastCheckTime = Date.now();
                console.warn('⚠️ [AIProxy] 웜업 실패: 서버 응답 없음');
            }
            return success;
        },

        /**
         * Keep-alive: 주기적 ping으로 Railway 슬립 방지
         * @param {number} intervalMs - 기본 10분
         */
        startKeepAlive(intervalMs = 10 * 60 * 1000) {
            this.stopKeepAlive();
            this._keepAliveTimer = setInterval(async () => {
                try {
                    const controller = new AbortController();
                    const timeoutId = setTimeout(() => controller.abort(), 10000);
                    await fetch(`${CURRENT_BASE_URL}/health`, { method: 'GET', signal: controller.signal });
                    clearTimeout(timeoutId);
                    this._lastCheckTime = Date.now();
                    this._isServerDown = false;
                    console.log('💓 [AIProxy] Keep-alive ping 성공');
                } catch (e) {
                    console.warn('⚠️ [AIProxy] Keep-alive ping 실패');
                }
            }, intervalMs);
            console.log(`💓 [AIProxy] Keep-alive 시작 (${intervalMs / 60000}분 간격)`);
        },

        stopKeepAlive() {
            if (this._keepAliveTimer) {
                clearInterval(this._keepAliveTimer);
                this._keepAliveTimer = null;
            }
        },

        async checkHealth(force = false, isStartup = false) {
            const now = Date.now();

            // 캐시된 결과가 있고 강제 실행이 아니면 즉시 반환
            if (!force && this._isServerDown && (now - this._lastCheckTime < 30000)) return false;
            if (!force && !this._isServerDown && (now - this._lastCheckTime < 60000)) return true;

            // 초기 로딩 시에는 5초, 이후에는 기본 30~60초 타임아웃 적용
            const checkTimeout = isStartup ? 5000 : TIMEOUT;

            for (const url of BASE_URLS) {
                try {
                    const controller = new AbortController();
                    const timeoutId = setTimeout(() => controller.abort(), checkTimeout);

                    const res = await fetch(`${url}/health`, { method: 'GET', signal: controller.signal });
                    clearTimeout(timeoutId);

                    if (res.ok) {
                        CURRENT_BASE_URL = url;
                        this._isServerDown = false;
                        this._lastCheckTime = now;
                        return true;
                    }
                } catch (e) {
                    // console.warn(`⚠️ Connection Failed: ${url}`);
                }
            }

            this._isServerDown = true;
            this._lastCheckTime = now;
            return false;
        },

        // ★ [핵심] V3 딥러닝 백엔드(메모 적용) 호출 함수
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

        /**
         * 메인 분석 실행 (Python 우선 → Supabase 폴백) (기초 분석 페이지용)
         */
        async invoke(config) {
            try {
                // [성능] invoke 경로에서는 5초 타임아웃으로 health check → 서버 다운 시 빠른 폴백
                const isAlive = await this.checkHealth(false, true);
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

            return await this.invokeEdgeFunction(config);
        },

        /**
         * Supabase Edge Function 폴백 (타임아웃 포함)
         */
        async invokeEdgeFunction(config) {
            if (!window.supabaseClient) {
                throw new Error("Supabase 클라이언트가 초기화되지 않았습니다.");
            }

            console.log("📡 [AIProxy] Supabase Edge Function(ai-lotto-analyst)으로 폴백 요청...");

            const edgePromise = window.supabaseClient.functions.invoke('ai-lotto-analyst', {
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
            if (typeof data === 'string') {
                try { data = JSON.parse(data); } catch (e) { /* 그대로 사용 */ }
            }

            console.log("✅ [AIProxy] Edge Function 폴백 분석 완료:", data);
            return data;
        },

        /**
         * 특정 회차 예측 데이터 조회
         */
        async getPredictions(round) {
            try {
                const res = await fetch(`${CURRENT_BASE_URL}/api/predictions/${round}`);
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
         * 자연어 명령 해석 요청
         */
        async interpret(query) {
            try {
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
