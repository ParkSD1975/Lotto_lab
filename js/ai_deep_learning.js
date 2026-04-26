/**
 * ai_deep_learning.js  v3.5 (Design Synchronization)
 *
 * AI 딥러닝 심층 분석 대시보드 컨트롤러 (3-Tab 버전)
 * aiProxy.js를 통해 Python 백엔드(LangChain RAG)와 통신합니다.
 */

const DeepLearning = {
    // ── 상태 변수 ──
    state: {
        isConnected: false,
        isAnalyzing: false,
        targetRound: 0,
        analysisData: null,
        regressionSort: { field: 'id', asc: true }
    },

    // ── 초기화 ──
    async init() {
        const startTime = Date.now();
        console.log("🚀 Deep Learning v3.5 Initializing...");

        // 1. 회차 정보 먼저 확정 (V4 조회에 필요)
        await this.setTargetRound();

        // 2. UI 이벤트 바인딩
        this.bindEvents();
        this._updateWeeklyStatusUI();

        // 3. V4 분석 즉시 시작 (백엔드 웜업과 무관)
        this.runAnalysis();

        console.log(`⏱️ [DeepLearning] 초기 렌더 시작 (${Date.now() - startTime}ms)`);

        // 4. 3초 후 V4 성공 여부 확인:
        //    - V4 성공 → 백엔드 웜업 완전 생략 (503 스팸 없음)
        //    - V4 실패 → 백엔드 단일 health check (웜업 아님)
        setTimeout(async () => {
            if (this.state.analysisData && this.state.analysisData._source === 'v4_weekly') {
                // V4 로드 성공 → 백엔드 연결 불필요, 웜업 생략
                console.log('⚡ [DeepLearning] V4 데이터 로드 완료 → 백엔드 웜업 생략');
                return;
            }
            // V4 실패한 경우에만 백엔드 연결 시도
            console.log('🔄 [DeepLearning] V4 데이터 없음 → 백엔드 연결 시도...');
            await this.checkConnection(true);
            if (this.state.isConnected) {
                window.AIProxy && window.AIProxy.startKeepAlive && window.AIProxy.startKeepAlive();
                this.loadHistoryList();
            }
        }, 3000);
    },

    async setTargetRound() {
        try {
            const { data } = await window.supabaseClient
                .from('lotto_draws')
                .select('round')
                .order('round', { ascending: false })
                .limit(1)
                .single();

            if (data) {
                this.state.targetRound = data.round + 1;
            } else {
                this.state.targetRound = 1200;
            }
        } catch (e) {
            console.error("회차 정보 로드 실패:", e);
            this.state.targetRound = 1200;
        }

        const el = document.getElementById('targetRoundDisplay');
        if (el) el.innerText = this.state.targetRound;
    },

    getAnalysisTopic: function () {
        if (window.currentAnalysisRule) {
            return {
                mode: 'custom',
                topic: document.getElementById('pageTitle')?.innerText || '사용자 정의 분석',
                desc: window.currentRuleDescription || ''
            };
        }
        const titleElement = document.getElementById('pageTitle') ||
            document.querySelector('h1') ||
            document.querySelector('h2.font-bold');

        let topic = '로또 번호 정밀 분석';
        if (titleElement) {
            topic = titleElement.innerText.replace(/분석/g, '').trim();
        }
        return { mode: 'dynamic', topic: topic };
    },

    async checkConnection(isStartup = false) {
        if (window.AIProxy && typeof window.AIProxy.warmup === 'function') {
            if (isStartup) {
                // 초기 로드: 웜업 모드 (최대 250초 대기, 진행 상황 UI 업데이트)
                this.updateConnectionStatusUI('warming');
                const ok = await window.AIProxy.warmup((elapsed) => {
                    this.updateConnectionStatusUI('warming', elapsed);
                });
                this.state.isConnected = ok;
                if (ok) window.AIProxy.startKeepAlive(); // 연결 성공 시 keep-alive 시작
            } else {
                this.state.isConnected = await window.AIProxy.checkHealth(true);
            }
        } else {
            try {
                const timeout = isStartup ? 3000 : 5000;
                const res = await fetch(this._getBaseUrl() + '/health', { signal: AbortSignal.timeout(timeout) });
                this.state.isConnected = res.ok;
            } catch (e) {
                this.state.isConnected = false;
            }
        }
        this.updateConnectionStatusUI();
    },

    // [신규] 연결 상태 UI 업데이트 함수
    updateConnectionStatusUI(state, elapsed) {
        const el = document.getElementById('connectionStatus');
        if (!el) return;

        if (state === 'warming') {
            const sec = elapsed ? ` ${elapsed}초` : '';
            el.innerHTML = `<span class="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse"></span> 서버 기동 중${sec} <span class="font-normal opacity-70">(최대 1분)</span>`;
            el.className = 'flex items-center gap-1.5 text-[11px] font-bold text-amber-600 bg-amber-50 px-2.5 py-0.5 rounded-full border border-amber-200';
        } else if (state === 'v4_ready') {
            // V4 Supabase 직접 로드 성공 — 백엔드 없이도 정상 동작
            el.innerHTML = '<span class="w-1.5 h-1.5 rounded-full bg-blue-500"></span> ⚡ 주간 파이프라인 (V4)';
            el.className = 'flex items-center gap-1.5 text-[11px] font-bold text-blue-600 bg-blue-50 px-2.5 py-0.5 rounded-full border border-blue-200';
        } else if (this.state.isConnected) {
            el.innerHTML = '<span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span> 연결됨';
            el.className = 'flex items-center gap-1.5 text-[11px] font-bold text-emerald-600 bg-emerald-50 px-2.5 py-0.5 rounded-full border border-emerald-200';
        } else {
            // V4 데이터가 이미 로드됐으면 "연결 끊김" 대신 조용한 안내
            if (this.state.analysisData && this.state.analysisData._source === 'v4_weekly') {
                el.innerHTML = '<span class="w-1.5 h-1.5 rounded-full bg-blue-400"></span> ⚡ V4 데이터 <span class="font-normal opacity-60">(AI서버 대기중)</span>';
                el.className = 'flex items-center gap-1.5 text-[11px] font-bold text-blue-500 bg-blue-50 px-2.5 py-0.5 rounded-full border border-blue-200';
            } else {
                el.innerHTML = '<span class="w-1.5 h-1.5 rounded-full bg-rose-500"></span> 연결 끊김 <button onclick="DeepLearning.retryConnection()" class="ml-1 underline text-rose-600 hover:text-rose-800 cursor-pointer bg-transparent border-0 p-0 text-[11px] font-bold">재시도</button>';
                el.className = 'flex items-center gap-1.5 text-[11px] font-bold text-rose-500 bg-rose-50 px-2.5 py-0.5 rounded-full border border-rose-200';
            }
        }
    },

    async retryConnection() {
        console.log('🔄 [DeepLearning] 재연결 시도...');
        await this.checkConnection(true);
        if (this.state.isConnected) {
            this.loadHistoryList();
            this.runAnalysis();
        }
    },

    bindEvents() {
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') this.closeXaiModal();
        });
    },

    switchTab(tabName) {
        this.state.currentTab = tabName;
        document.querySelectorAll('.connected-tab').forEach(btn => {
            btn.classList.remove('connected-tab-active');
        });
        const activeBtn = document.getElementById('btn-' + tabName);
        if (activeBtn) activeBtn.classList.add('connected-tab-active');

        ['status', 'summary', 'recommend', 'filters', 'regression', 'custom'].forEach(t => {
            const panel = document.getElementById('tab-' + t);
            if (!panel) return;
            if (t === tabName) {
                panel.classList.remove('hidden');
            } else {
                panel.classList.add('hidden');
            }
        });
    },

    async _loadExpertMemos() {
        try {
            if (!window.supabaseClient) return [];
            const { data, error } = await window.supabaseClient
                .from('user_checkpoints')
                .select('*')
                .eq('round', this.state.targetRound)
                .order('created_at', { ascending: true });
            if (error) throw error;
            return data || [];
        } catch (e) {
            console.warn('[DeepLearning] 전문가 메모 로드 실패:', e);
            return [];
        }
    },

    renderExpertMemoSection(memos) {
        const section = document.getElementById('expertMemoSection');
        const list = document.getElementById('expertMemoList');
        const countBadge = document.getElementById('expertMemoCount');
        if (!section || !list) return;

        if (!memos || memos.length === 0) {
            section.style.display = 'none';
            return;
        }

        if (countBadge) countBadge.textContent = memos.length + '개';

        list.innerHTML = memos.map(function (m, i) {
            const dateObj = new Date(m.created_at || new Date());
            const dateStr = dateObj.getFullYear() + '.' +
                String(dateObj.getMonth() + 1).padStart(2, '0') + '.' +
                String(dateObj.getDate()).padStart(2, '0');
            const content = (m.memo || '').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
            return `<div style="background:#F9FAFB;border:1px solid #E5E7EB;border-left:3px solid #4F46E5;border-radius:0 12px 12px 0;padding:14px 16px">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
                    <span style="font-size:11px;font-weight:700;color:#4F46E5;text-transform:uppercase;letter-spacing:0.05em">Expert Note #${i + 1}</span>
                    <span style="font-size:11px;color:#9CA3AF;font-weight:500">${dateStr}</span>
                </div>
                <div style="font-size:13px;color:#374151;line-height:1.6">${content}</div>
            </div>`;
        }).join('');

        section.style.display = 'block';
    },

    _parseMemoExclusions(memos) {
        const excluded = new Set();
        for (const m of (memos || [])) {
            const text = m.memo || '';
            const re1 = /([1-9]|[1-3][0-9]|4[0-5])\s*번(?:은|는|이|가|도)?\s*[^0-9]{0,8}?(?:제외|빼|제거|삭제)/g;
            let match;
            while ((match = re1.exec(text)) !== null) {
                const n = parseInt(match[1]);
                if (n >= 1 && n <= 45) excluded.add(n);
            }
            const re2 = /(?:제외|빼|제거|삭제)\s*[:：]?\s*([\d,\s]+)/gi;
            while ((match = re2.exec(text)) !== null) {
                match[1].split(/[,\s]+/).forEach(s => {
                    const n = parseInt(s);
                    if (n >= 1 && n <= 45) excluded.add(n);
                });
            }
            const re3 = /(\d{1,2})\s*번?(?:\s*[은는을를이가도])?\s*(제외|빼|제거)/gi;
            while ((match = re3.exec(text)) !== null) {
                const n = parseInt(match[1]);
                if (n >= 1 && n <= 45) excluded.add(n);
            }
        }
        return [...excluded];
    },

    async runAnalysis(forceReload = false) {
        console.log("🚀 [DeepLearning] runAnalysis() Called");
        if (this.state.isAnalyzing) return;
        this.state.isAnalyzing = true;

        this.state.expertMemos = await this._loadExpertMemos();

        if (forceReload) {
            try {
                const cacheKey = `ai_analysis_cache_${this.state.targetRound}`;
                localStorage.removeItem(cacheKey);
            } catch (e) { }
        }

        this.showLoading(true, 'AI 심층 분석 데이터 조회 중...');

        try {
            // 0. V4 주간 파이프라인 데이터 우선 시도 (isConnected 무관 — Supabase 직접 조회)
            if (!forceReload) {
                this.showLoading(true, '⚡ 주간 파이프라인 데이터 조회 중...');
                const v4Data = await this._fetchAnalysisFromV4(this.state.targetRound);
                if (v4Data) {
                    console.log(`⚡ [DeepLearning] V4 주간 파이프라인 로드 성공! 제${v4Data.target_round}회차 top_5=${JSON.stringify(v4Data.top_5)}`);
                    this.setProgress(100, '완료!');
                    this.state.analysisData = v4Data;
                    this.renderAll(v4Data);
                    this._showV4Badge(v4Data);
                    this.updateConnectionStatusUI('v4_ready');  // ← 연결 끊김 대신 V4 배지
                    this._prefetchXAIInBackground();
                    this._updateWeeklyStatusUI();
                    this.state.isAnalyzing = false;
                    this.showLoading(false);
                    return;
                }
                console.log('[DeepLearning] V4 데이터 없음 → 기존 경로로 전환');
            }

            // 1. 현재 회차 exact match DB 조회
            let dbData = null;
            if (!forceReload) {
                dbData = await this._fetchAnalysisFromDB(this.state.targetRound);
            }

            // 2. exact match 없으면 최신 저장 데이터 확인 (다른 회차일 수 있음)
            let staleData = null;
            if (!dbData && !forceReload) {
                const latest = await this._fetchLatestAnalysisFromDB();
                if (latest) {
                    const latestRound = latest.target_round || 0;
                    if (latestRound === this.state.targetRound) {
                        dbData = latest; // 같은 회차 — 정상 사용
                    } else {
                        staleData = latest; // 이전 회차 — 임시 표시용
                        console.log(`📦 [DeepLearning] 이전 회차(${latestRound}) 데이터 발견 — 현재 회차(${this.state.targetRound}) 신규 분석 진행`);
                    }
                }
            }

            if (dbData) {
                console.log("📦 [DeepLearning] DB에서 분석 결과 로드 성공!");
                this.setProgress(100, '완료!');
                this.state.analysisData = dbData;
                this.renderAll(dbData);
                this._prefetchXAIInBackground();
                this._updateWeeklyStatusUI();
                this.state.isAnalyzing = false;
                this.showLoading(false);
                return;
            }

            // 2-b. 이전 회차 데이터 있고 주간 제한 도달한 경우 → 이전 데이터 표시 + 경고 배너
            if (staleData && !this._canRunAnalysis()) {
                const staleRound = staleData.target_round || '?';
                this.setProgress(100, '완료 (이전 회차)');
                this.state.analysisData = staleData;
                this.renderAll(staleData);
                this._prefetchXAIInBackground();
                this._updateWeeklyStatusUI();
                this.state.isAnalyzing = false;
                this.showLoading(false);
                const summaryEl = document.getElementById('aiSummaryText');
                if (summaryEl) {
                    const banner = document.createElement('div');
                    banner.id = 'stale-round-banner';
                    banner.className = 'flex items-center gap-3 bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 mb-4 text-amber-700 text-sm font-bold';
                    banner.innerHTML = `<span class="text-lg">⚠️</span><span>제${staleRound}회차 분석 결과입니다. <strong>제${this.state.targetRound}회차</strong> 신규 분석이 필요합니다.</span><button onclick="DeepLearning.runAnalysis(true)" class="ml-auto px-3 py-1 bg-amber-500 hover:bg-amber-600 text-white rounded-lg text-xs font-bold whitespace-nowrap transition-colors">새 분석 실행</button>`;
                    summaryEl.parentElement?.insertBefore(banner, summaryEl);
                }
                return;
            }
            // 2-c. 이전 회차 데이터 있지만 신규 분석 가능 → 계속 진행 (staleData는 무시하고 새 분석 실행)

            // 3. DB에 데이터 없음 → 주간 제한 체크 후 Python 실행 (forceReload면 제한 무시)
            if (!forceReload && !this._canRunAnalysis()) {
                this.showLoading(false);
                const nextSat = this._getNextSaturdayKST();
                const summaryEl = document.getElementById('aiSummaryText');
                if (summaryEl) {
                    summaryEl.innerHTML = `<span class="text-amber-600 font-bold">⏳ 이번 주 분석이 완료되었습니다. 다음 분석은 토요일 추첨 후 가능합니다. (다음: ${nextSat})</span>`;
                }
                this.state.isAnalyzing = false;
                return;
            }

            if (!this.state.isConnected) await this.checkConnection();

            if (this.state.isConnected && window.AIProxy) {
                console.log("🟢 [DeepLearning] Python 서버 실시간 분석 요청...");
                this.setProgress(30, '7중 앙상블 모델 연산 중...');
                const result = await window.AIProxy.getDeepAnalysis(this.state.targetRound);

                if (result && result.success) {
                    this.setProgress(100, '완료!');
                    this.state.analysisData = result;
                    this.renderAll(result);
                    this._prefetchXAIInBackground();
                    this._markAnalysisRun();
                    this._updateWeeklyStatusUI();
                    this.showLoading(false);

                    // 분석 완료 즉시 DB에 자동 저장
                    if (window.supabaseClient) {
                        try {
                            const { error: saveErr } = await window.supabaseClient
                                .from('deep_analysis_history')
                                .upsert({
                                    target_round: parseInt(result.target_round || this.state.targetRound),
                                    analysis_data: result,
                                    recommended_numbers: result.top_5 || result.recommended || [],
                                    combinations: result.combinations || [],
                                    created_at: new Date().toISOString()
                                }, { onConflict: 'target_round' });

                            if (saveErr) {
                                console.warn("💾 [AI 분석] 자동 저장 실패:", saveErr);
                            } else {
                                console.log("💾 [AI 분석] DB에 성공적으로 자동 저장되었습니다.");
                                const histSel = document.getElementById('historySelect');
                                if (!histSel || histSel.options.length <= 1) this.loadHistoryList();
                            }
                        } catch (e) {
                            console.error("💾 [AI 분석] DB 저장 도중 오류:", e);
                        }
                    }
                } else {
                    throw new Error("Python 분석 실패 (응답 없음)");
                }
            } else {
                console.warn("⚠️ [DeepLearning] 서버 미연결 & DB 데이터 없음.");
                this.showLoading(false);
                const summaryEl = document.getElementById('aiSummaryText');
                if (summaryEl) {
                    summaryEl.innerHTML = '<span class="text-rose-500 font-bold">⚠️ 분석 데이터가 없습니다. (백엔드 서버 실행 필요)</span>';
                }
                document.getElementById('connectionStatus').innerHTML =
                    '<span class="flex items-center gap-1.5 text-[11px] font-bold text-rose-500 bg-rose-50 px-2.5 py-0.5 rounded-full border border-rose-200"><span class="w-1.5 h-1.5 rounded-full bg-rose-500"></span> 연결 끊김</span>';
            }

        } catch (e) {
            console.error("분석 실패:", e);
            this.showLoading(false);
            const summaryEl = document.getElementById('aiSummaryText');
            if (summaryEl) {
                summaryEl.innerHTML = `<span class="text-rose-500 font-bold">⚠️ 분석 중 오류 발생: ${e.message}</span>`;
            }
        } finally {
            this.state.isAnalyzing = false;
        }
    },

    // ── V4 주간 파이프라인 데이터 조회 (Supabase 직접 읽기 — 백엔드 무관) ──
    async _fetchAnalysisFromV4(round) {
        if (!window.supabaseClient) return null;
        try {
            const targetRound = round || this.state.targetRound;

            // 1. weekly_predictions 조회
            let predsQuery = window.supabaseClient
                .from('weekly_predictions')
                .select('*')
                .order('created_at', { ascending: false })
                .limit(1);
            if (targetRound) predsQuery = predsQuery.eq('target_round', targetRound);

            const { data: predRows, error: predErr } = await predsQuery;
            if (predErr || !predRows || predRows.length === 0) {
                console.log('[V4] weekly_predictions 데이터 없음 (round=' + targetRound + ')');
                return null;
            }
            const pred = predRows[0];

            // 2. 나머지 데이터 병렬 조회
            const [xaiResult, combResult, featResult, drawsResult, filterResult, regressionResult] = await Promise.allSettled([
                // weekly_number_xai (번호별 모델 기여도)
                window.supabaseClient
                    .from('weekly_number_xai')
                    .select('*')
                    .eq('target_round', pred.target_round),
                // weekly_combinations
                window.supabaseClient
                    .from('weekly_combinations')
                    .select('*')
                    .eq('target_round', pred.target_round)
                    .order('combo_rank', { ascending: true }),
                // number_features_by_round (gap, hot_cold, 회귀, 궁, 용지 위치)
                window.supabaseClient
                    .from('number_features_by_round')
                    .select('number, missing_count, hot_cold, last_appearance_round, regression_2, regression_3, regression_5, regression_10, regression_15, regression_20, regression_30, regression_50, regression_100, regression_200, gung, paper_row, paper_col')
                    .eq('round', pred.target_round - 1),
                // 최근 20회차 당첨번호 (freq 계산용)
                window.supabaseClient
                    .from('lotto_draws')
                    .select('round, numbers')
                    .order('round', { ascending: false })
                    .limit(20),
                // weekly_filter_predictions (필터 분석탭용)
                window.supabaseClient
                    .from('weekly_filter_predictions')
                    .select('filter_key, ensemble_min, ensemble_max, ensemble_ci, model_expectations, filter_value')
                    .eq('target_round', pred.target_round),
                // weekly_regression_analysis (회귀분석탭용, 최근 50단계만)
                window.supabaseClient
                    .from('weekly_regression_analysis')
                    .select('step, predicted_numbers, model_exp, confidence')
                    .eq('target_round', pred.target_round)
                    .lte('step', 50)
                    .order('step', { ascending: true })
            ]);

            // xai map
            const xaiMap = {};
            if (xaiResult.status === 'fulfilled' && xaiResult.value.data) {
                xaiResult.value.data.forEach(r => { xaiMap[r.number] = r; });
            }
            // features map
            const featMap = {};
            if (featResult.status === 'fulfilled' && featResult.value.data) {
                featResult.value.data.forEach(r => { featMap[r.number] = r; });
            }
            // 빈도 계산 (최근 20회차 등장 횟수)
            const freqMap = {};
            if (drawsResult.status === 'fulfilled' && drawsResult.value.data) {
                const recentDraws = drawsResult.value.data;
                for (let n = 1; n <= 45; n++) {
                    freqMap[n] = recentDraws.filter(d => (d.numbers || []).includes(n)).length;
                }
            }
            // combinations
            const combinations = (combResult.status === 'fulfilled' && combResult.value.data) ? combResult.value.data : [];

            // 필터 분석 데이터 (range_analysis 포맷으로 변환)
            const filterRows = (filterResult.status === 'fulfilled' && filterResult.value.data) ? filterResult.value.data : [];
            const rangeAnalysis = {};
            filterRows.forEach(row => {
                let parsedRange = row.filter_value;
                try { parsedRange = JSON.parse(row.filter_value); } catch(e) {}
                rangeAnalysis[row.filter_key] = {
                    range: parsedRange,
                    ensemble_min: row.ensemble_min,
                    ensemble_max: row.ensemble_max,
                    ensemble_ci: row.ensemble_ci,
                    model_expectations: row.model_expectations || {}
                };
            });

            // 회귀분석 데이터 (regression_analysis 포맷으로 변환)
            const regRows = (regressionResult.status === 'fulfilled' && regressionResult.value.data) ? regressionResult.value.data : [];
            const regressionAnalysis = regRows.map(row => {
                const me = row.model_exp || {};
                const targets = me._targets || row.predicted_numbers || [];
                const modelExpClean = {};
                ['lstm','xgboost','cnn','transformer','markov','autoencoder','gnn'].forEach(m => {
                    if (me[m] != null) modelExpClean[m] = me[m];
                });
                const ensExp = modelExpClean.lstm != null
                    ? parseFloat(((modelExpClean.lstm || 0) * 0.4 + (modelExpClean.transformer || 0) * 0.3 + (modelExpClean.xgboost || 0) * 0.2 + (modelExpClean.markov || 0) * 0.1).toFixed(3))
                    : null;
                return {
                    id:           row.step,
                    targets:      targets,
                    gap:          me._gap || 0,
                    str:          me._str || 0,
                    avg_hit:      me._avg_hit || row.confidence || 0,
                    model_exp:    modelExpClean,
                    ensemble_exp: ensExp,
                    notable:      me._notable || []
                };
            });

            const preds = {
                target_round: pred.target_round,
                top_5: pred.top_5 || [],
                exclude_10: pred.exclude_10 || [],
                model_weights: pred.model_weights || {},
                meta_active: pred.meta_active,
                meta_alpha: pred.meta_alpha,
                pipeline_version: pred.pipeline_version,
                created_at: pred.created_at,
                combinations
            };

            console.log(`[V4] Supabase 직접 조회 성공 — 제${pred.target_round}회차 (xai:${Object.keys(xaiMap).length}개, feat:${Object.keys(featMap).length}개, filters:${filterRows.length}개, reg:${regRows.length}개)`);
            return this._adaptV4ToV3Format(preds, xaiMap, featMap, freqMap, rangeAnalysis, regressionAnalysis);
        } catch (e) {
            console.log('[V4] Supabase 직접 조회 실패 (무시):', e.message);
            return null;
        }
    },

    // ── V4 데이터 → renderAll() 호환 V3 포맷 변환 ──
    // xaiMap:  { [num]: { xgboost_pct, lstm_pct, ..., probability } }  (0~100 % 단위)
    // featMap: { [num]: { missing_count, hot_cold, appearance_count_20, regression_*, gung, ... } }
    // rangeAnalysis: { filter_key: { range, ensemble_min, ensemble_max, model_expectations } }
    // regressionAnalysis: [ { id, targets, gap, str, avg_hit, model_exp, ensemble_exp, notable } ]
    _adaptV4ToV3Format(preds, xaiMap, featMap = {}, freqMap = {}, rangeAnalysis = {}, regressionAnalysis = []) {
        const top5      = preds.top_5 || [];
        const exclude10 = preds.exclude_10 || [];
        const mw        = preds.model_weights || {};

        // ── GNN 균일 감지: 모든 번호의 gnn_pct 값이 동일하면 균일 예측 ──
        // 파이프라인이 GNN 균일 시 1/45=2.22%를 저장 → sum 기반 감지 불가 (2.22×45=99.9 > 0.5)
        // 분산(max-min) 기반으로 변경: 값이 모두 동일하면 균일 예측 판정
        const _gnnValues = Object.values(xaiMap).map(x => x.gnn_pct || 0);
        const _gnnMin = _gnnValues.length ? Math.min(..._gnnValues) : 0;
        const _gnnMax = _gnnValues.length ? Math.max(..._gnnValues) : 0;
        const _gnnUniform = (_gnnMax - _gnnMin) < 0.01; // 모든 값이 동일 → 균일 예측
        const GNN_UNIFORM_PCT = 1 / 45 * 100; // ≈ 2.22% (hot_cold 표시용)
        // hot_cold/matrix 표시용: 균일이면 2.22% (기저확률, 시각적 표시 목적)
        const _gnnPct = (x) => _gnnUniform ? GNN_UNIFORM_PCT : (x.gnn_pct || 0);

        // ── 1. matrix_data (45개 번호) ──
        // score = 모델의 이 번호에 대한 기여도 % (0-100 범위, xai 컬럼 그대로)
        // total = 앙상블 확률 × 100 (%)
        const matrixData = [];
        for (let n = 1; n <= 45; n++) {
            const x = xaiMap[n] || {};
            const f = featMap[n] || {};
            const prob = x.probability || 0;
            const gapVal = f.missing_count !== undefined ? f.missing_count : null;
            const freqCount = freqMap[n] !== undefined ? freqMap[n] : null;
            // freq는 0~1 비율로 저장 (sortMatrix가 *100 해서 표시)
            const freqFrac = freqCount !== null ? parseFloat((freqCount / 20).toFixed(4)) : null;
            const numInfo  = { gap: gapVal, hot_cold: f.hot_cold };
            matrixData.push({
                num:  n,
                total: parseFloat((prob * 100).toFixed(2)),
                gap:  gapVal,
                freq: freqFrac,
                hot_cold: f.hot_cold || null,
                models: {
                    xgboost:     { score: parseFloat((x.xgboost_pct     || 0).toFixed(2)), reason: DeepLearning._modelReason('xgboost',     x.xgboost_pct     || 0, numInfo) },
                    lstm:        { score: parseFloat((x.lstm_pct        || 0).toFixed(2)), reason: DeepLearning._modelReason('lstm',        x.lstm_pct        || 0, numInfo) },
                    cnn:         { score: parseFloat((x.cnn_pct         || 0).toFixed(2)), reason: DeepLearning._modelReason('cnn',         x.cnn_pct         || 0, numInfo) },
                    transformer: { score: parseFloat((x.transformer_pct || 0).toFixed(2)), reason: DeepLearning._modelReason('transformer', x.transformer_pct || 0, numInfo) },
                    gnn:         { score: parseFloat(_gnnPct(x).toFixed(2)),                reason: DeepLearning._modelReason('gnn',         _gnnPct(x),              numInfo) },
                    markov:      { score: parseFloat((x.markov_pct      || 0).toFixed(2)), reason: DeepLearning._modelReason('markov',      x.markov_pct      || 0, numInfo) },
                    autoencoder: { score: parseFloat((x.autoencoder_pct || 0).toFixed(2)), reason: DeepLearning._modelReason('autoencoder', x.autoencoder_pct || 0, numInfo) }
                }
            });
        }

        // ── 2. hot_cold_data (renderHotColdAnalysis 호환 — 상태별 num_details 구조) ──
        // top15: 확률 기준 상위 15개 번호
        const _top15Set = new Set(
            Array.from({ length: 45 }, (_, i) => i + 1)
                .sort((a, b) => (xaiMap[b]?.probability || 0) - (xaiMap[a]?.probability || 0))
                .slice(0, 15)
        );
        // 각 번호를 gap 기준으로 5단계 분류
        const hot_cold_data = {};
        for (let n = 1; n <= 45; n++) {
            const x = xaiMap[n] || {};
            const f = featMap[n] || {};
            const g = f.missing_count != null ? f.missing_count : 99;
            const ensProb = parseFloat(((x.probability || 0) * 100).toFixed(2));
            const detail = {
                num:           n,
                ensemble_prob: ensProb,
                is_top15:      _top15Set.has(n),
                models: {
                    lstm:        { prob: x.lstm_pct        || 0 },
                    xgboost:     { prob: x.xgboost_pct     || 0 },
                    cnn:         { prob: x.cnn_pct          || 0 },
                    transformer: { prob: x.transformer_pct  || 0 },
                    markov:      { prob: x.markov_pct       || 0 },
                    autoencoder: { prob: x.autoencoder_pct  || 0 },
                    gnn:         { prob: _gnnPct(x) }
                }
            };
            const status = g <= 2 ? 'hot' : g <= 7 ? 'active' : g <= 15 ? 'cooling' : g <= 25 ? 'cold' : 'deadcold';
            if (!hot_cold_data[status]) hot_cold_data[status] = { num_details: [] };
            hot_cold_data[status].num_details.push(detail);
        }

        // ── 3. regression_analysis (number_features 회귀 컬럼 활용) ──
        const REG_WINDOWS = [2, 3, 5, 10, 15, 20, 30, 50, 100, 200];
        const regression_analysis = [];
        for (let n = 1; n <= 45; n++) {
            const f = featMap[n] || {};
            if (!Object.keys(f).length) continue;
            const gap  = f.missing_count || 0;
            const hot  = f.hot_cold || 'neutral';
            // 50회 기준 기대치 대비 이상도
            const reg50    = f.regression_50 || 0;
            const expected = parseFloat((50 * 6 / 45).toFixed(3)); // ≈ 6.667
            const anomaly  = expected > 0 ? parseFloat((Math.abs(reg50 - expected) / expected).toFixed(3)) : 0;
            const avgHit   = f.appearance_count_20 ? parseFloat((f.appearance_count_20 / 20 * 6).toFixed(2)) : 0;
            const x = xaiMap[n] || {};
            regression_analysis.push({
                id:            n,
                target_number: n,
                gap,
                str:           hot,
                avg_hit:       avgHit,
                anomaly,
                // 각 회귀 윈도우별 실제 출현 횟수
                regression_windows: REG_WINDOWS.reduce((acc, w) => {
                    acc[`reg_${w}`] = f[`regression_${w}`] || 0;
                    return acc;
                }, {}),
                models: {
                    xgboost:     { score: x.xgboost_pct     || 0 },
                    lstm:        { score: x.lstm_pct         || 0 },
                    cnn:         { score: x.cnn_pct          || 0 },
                    transformer: { score: x.transformer_pct  || 0 },
                    markov:      { score: x.markov_pct       || 0 },
                    autoencoder: { score: x.autoencoder_pct  || 0 },
                    gnn:         { score: x.gnn_pct          || 0 }
                }
            });
        }

        // ── 공통 헬퍼: 번호 그룹에서 model_exp(기대수) 계산 ──
        const _MODEL_KEYS = ['lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'];
        const _calcModelExp = (nums) => {
            const me = {};
            _MODEL_KEYS.forEach(m => {
                const pctSum = nums.reduce((s, n) => {
                    const x = xaiMap[n] || {};
                    const pct = (m === 'gnn') ? _gnnPct(x) : (x[m + '_pct'] || 0);
                    return s + pct;
                }, 0);
                me[m] = parseFloat((pctSum / 100 * 6).toFixed(2));
            });
            return me;
        };
        const _calcExp = (nums) =>
            parseFloat((nums.reduce((s, n) => s + (xaiMap[n]?.probability || 0), 0) * 6).toFixed(2));

        // ── 4. magic_square_analysis (9궁) ──
        const gungGroups = {};
        for (let n = 1; n <= 45; n++) {
            const g = (featMap[n] && featMap[n].gung) ? featMap[n].gung : Math.ceil(n / 5);
            if (!gungGroups[g]) gungGroups[g] = { section: g, numbers: [], prob_sum: 0 };
            gungGroups[g].numbers.push(n);
            gungGroups[g].prob_sum += (xaiMap[n]?.probability || 0);
        }
        const magic_square_analysis = Object.values(gungGroups)
            .sort((a, b) => a.section - b.section)
            .map(g => ({
                ...g,
                label:     g.section + '궁',
                exp:       _calcExp(g.numbers),
                model_exp: _calcModelExp(g.numbers),
                gap: 0, str: ''
            }));

        // ── 5. lotto_paper_analysis (로또용지 행/열) ──
        const paperRowMap = {};
        for (let n = 1; n <= 45; n++) {
            const f   = featMap[n] || {};
            const row = f.paper_row || Math.ceil(n / 7);
            if (!paperRowMap[row]) paperRowMap[row] = { row, numbers: [], prob_sum: 0 };
            paperRowMap[row].numbers.push(n);
            paperRowMap[row].prob_sum += (xaiMap[n]?.probability || 0);
        }
        const lotto_paper_analysis = {
            rows: Object.values(paperRowMap)
                .sort((a, b) => a.row - b.row)
                .map(r => ({
                    ...r,
                    label:     r.row + '행',
                    exp:       _calcExp(r.numbers),
                    model_exp: _calcModelExp(r.numbers),
                    gap: 0, str: ''
                }))
        };

        // ── 6. number_band_analysis (번호대 1~10 / 11~20 / ...) ──
        const BANDS = [
            { range: '1~10',  min: 1,  max: 10 },
            { range: '11~20', min: 11, max: 20 },
            { range: '21~30', min: 21, max: 30 },
            { range: '31~40', min: 31, max: 40 },
            { range: '41~45', min: 41, max: 45 }
        ];
        const number_band_analysis = BANDS.map(b => {
            const nums = Array.from({ length: b.max - b.min + 1 }, (_, i) => b.min + i);
            return {
                range:         b.range,
                label:         b.range,
                numbers:       nums,
                probabilities: nums.map(n => parseFloat(((xaiMap[n]?.probability || 0) * 100).toFixed(2))),
                exp:           _calcExp(nums),
                model_exp:     _calcModelExp(nums),
                gap: 0, str: ''
            };
        });

        // ── 7. tail_analysis (끝수 0~9) ──
        const tailGroups = {};
        for (let t = 0; t <= 9; t++) tailGroups[t] = [];
        for (let n = 1; n <= 45; n++) tailGroups[n % 10].push(n);
        const tail_analysis = Object.entries(tailGroups).map(([tail, nums]) => {
            const t = parseInt(tail);
            return {
                tail:      t,
                tail_digit: t,
                exp:       _calcExp(nums),
                model_exp: _calcModelExp(nums),
                counts: {
                    xgboost:     parseFloat(nums.reduce((s, n) => s + (xaiMap[n]?.xgboost_pct     || 0), 0).toFixed(1)),
                    lstm:        parseFloat(nums.reduce((s, n) => s + (xaiMap[n]?.lstm_pct        || 0), 0).toFixed(1)),
                    cnn:         parseFloat(nums.reduce((s, n) => s + (xaiMap[n]?.cnn_pct         || 0), 0).toFixed(1)),
                    transformer: parseFloat(nums.reduce((s, n) => s + (xaiMap[n]?.transformer_pct || 0), 0).toFixed(1)),
                    markov:      parseFloat(nums.reduce((s, n) => s + (xaiMap[n]?.markov_pct      || 0), 0).toFixed(1)),
                    autoencoder: parseFloat(nums.reduce((s, n) => s + (xaiMap[n]?.autoencoder_pct || 0), 0).toFixed(1)),
                    gnn:         parseFloat(nums.reduce((s, n) => s + _gnnPct(xaiMap[n] || {}),  0).toFixed(1))
                },
                gap: 0,
                str: ''
            };
        });

        // ── 8. missing_group_data (미출현 그룹) ──
        const MISSING_GROUPS = [
            { label: 'Gap 0~5 (최근 출현)',  minGap: 0,  maxGap: 5,   color: '#10B981' },
            { label: 'Gap 6~15 (중기)',       minGap: 6,  maxGap: 15,  color: '#3B82F6' },
            { label: 'Gap 16~25 (장기)',      minGap: 16, maxGap: 25,  color: '#8B5CF6' },
            { label: 'Gap 26~40 (초장기)',    minGap: 26, maxGap: 40,  color: '#F97316' },
            { label: 'Gap 41+ (극장기)',      minGap: 41, maxGap: 999, color: '#EF4444' }
        ];
        const missing_group_data = MISSING_GROUPS.map(mg => {
            const nums = [];
            for (let n = 1; n <= 45; n++) {
                const f = featMap[n] || {};
                const g = f.missing_count != null ? f.missing_count : 0;
                if (g >= mg.minGap && g <= mg.maxGap) {
                    const x = xaiMap[n] || {};
                    nums.push({
                        num:           n,
                        gap:           g,
                        is_top15:      _top15Set.has(n),
                        ensemble_prob: parseFloat(((x.probability || 0) * 100).toFixed(2))
                    });
                }
            }
            if (!nums.length) return null;
            const totalProb = nums.reduce((s, d) => s + d.ensemble_prob, 0);
            const avg_prob  = parseFloat((totalProb / nums.length).toFixed(2));
            const model_exp = {};
            ['lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'].forEach(m => {
                const sumPct = nums.reduce((s, d) => {
                    const x = xaiMap[d.num] || {};
                    return s + ((m === 'gnn') ? _gnnPct(x) : (x[m + '_pct'] || 0));
                }, 0);
                model_exp[m] = parseFloat((sumPct / 100 * 6).toFixed(2));
            });
            return {
                label:    mg.label,
                color:    mg.color,
                count:    nums.length,
                avg_prob,
                numbers:  nums.sort((a, b) => b.ensemble_prob - a.ensemble_prob),
                model_exp
            };
        }).filter(Boolean);

        // ── strategy ──
        const hotNums  = (hot_cold_data.hot?.num_details || []).map(d => d.num);
        const coldNums = [...(hot_cold_data.cold?.num_details || []), ...(hot_cold_data.deadcold?.num_details || [])].map(d => d.num);

        // ── 앙상블 합의도(confidence): top-5 번호에 대해 각 모델이 실제로 양수 기여하는 비율 ──
        // 가짜 85/78 대신 xaiMap 실데이터 기반 계산
        const _CONF_MODELS = ['xgboost', 'lstm', 'cnn', 'transformer', 'markov'];
        const _top5Nums = top5.slice(0, 5);
        let _agreeCount = 0;
        _top5Nums.forEach(n => {
            const x = xaiMap[n] || {};
            _CONF_MODELS.forEach(m => { if ((x[m + '_pct'] || 0) > 0) _agreeCount++; });
        });
        const _maxAgree = _top5Nums.length * _CONF_MODELS.length;
        // 합의도: 40(최저)~95(최고) — 모델 기여가 전혀 없으면 40%, 전부 동의하면 95%
        const _agreement = _maxAgree > 0 ? _agreeCount / _maxAgree : 0;
        const confidence = Math.round(40 + _agreement * 55);

        // ── keywords: 회차·모델·메타·버전 ──
        const MODEL_ABBR_KW = { xgboost: 'XGBoost', lstm: 'LSTM', cnn: 'CNN', transformer: 'TF', markov: 'Markov', autoencoder: 'ATC', gnn: 'GNN' };
        const activeModelNames = Object.entries(mw)
            .filter(([, w]) => w > 0.03)
            .sort((a, b) => b[1] - a[1])
            .map(([m]) => MODEL_ABBR_KW[m] || m);
        // pipeline_version 이 "v2" 처럼 이미 v로 시작하면 v를 추가하지 않음
        const _ver = preds.pipeline_version
            ? (String(preds.pipeline_version).startsWith('v')
                ? String(preds.pipeline_version)
                : `v${preds.pipeline_version}`)
            : null;
        const keywords = [
            `${preds.target_round}회차`,
            activeModelNames.length > 0 ? activeModelNames.slice(0, 3).join('+') : '앙상블',
            preds.meta_active ? `메타α=${(preds.meta_alpha || 0).toFixed(2)}` : null,
            _ver
        ].filter(Boolean);

        // ── overall_strategy: 핵심 공략 — 실제 번호 기반 전략 조언 ──
        const _topModels = Object.entries(mw).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([m]) => MODEL_ABBR_KW[m] || m);
        // 추천 번호의 gap 분포로 전략 문구 생성
        const _top5Gaps = _top5Nums.map(n => (featMap[n]?.missing_count ?? 99));
        const _avgGap   = _top5Gaps.reduce((s, g) => s + g, 0) / (_top5Gaps.length || 1);
        const _gapText  = _avgGap <= 5  ? '최근 출현 번호 중심 (단기 모멘텀)'
                        : _avgGap <= 15 ? '중기 미출현 번호 중심 (반등 기대)'
                        :                 '장기 미출현 번호 중심 (역발상 전략)';
        const _top5str  = `추천 ${_top5Nums.join('·')}`;
        const overall_strategy = `${_top5str}. ${_gapText}. 주도 모델: ${_topModels.join('·')}.`;

        // ── hot_cold_analysis: || 50 기본값 제거, 실데이터만 ──
        const _hotCount  = hotNums.length;
        const _coldCount = coldNums.length;
        const hot_cold_analysis = (_hotCount > 0 || _coldCount > 0)
            ? {
                hot_ratio:  Math.round(_hotCount  / 45 * 100),
                cold_ratio: Math.round(_coldCount / 45 * 100),
                trend_text: `Hot(최근출현) ${_hotCount}개 · Cold(장기미출현) ${_coldCount}개 / 전체 45개`
              }
            : null;  // null이면 렌더러가 "데이터 없음" 표시

        // ── risk_assessment: XAI 기반 단순 위험도 ──
        // top-5 번호 중 1개 이상이 veto(hard filter)면 위험, confidence로 판단
        const _vetoCount = _top5Nums.filter(n => (xaiMap[n]?.veto)).length;
        const risk_assessment = {
            risk_score: Math.max(0, Math.min(100, Math.round((1 - _agreement) * 80 + _vetoCount * 15))),
            risk_level: _agreement > 0.7 ? '낮음' : _agreement > 0.4 ? '보통' : '높음',
            warning_text: _vetoCount > 0
                ? `추천 번호 중 ${_vetoCount}개가 하드필터 경고 대상입니다.`
                : `모델 합의도 ${Math.round(_agreement * 100)}% — ${_agreement > 0.7 ? '앙상블 일치도 양호' : _agreement > 0.4 ? '모델 간 의견 분산' : '모델 간 큰 이견, 주의 필요'}.`
        };

        const strategy = {
            summary:          `제${preds.target_round}회차 주간 앙상블 분석 완료. 추천 번호: ${_top5Nums.join(', ')}`,
            confidence,
            keywords,
            hot_cold_analysis,
            overall_strategy,
            risk_assessment
        };

        // ── XAI 실기여도: top-5 번호의 모델별 평균 기여도 (weekly_number_xai 실데이터) ──
        // 이게 "모델 컨디션" 차트에 표시될 진짜 값
        const _XAI_MODEL_KEYS = ['xgboost', 'lstm', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'];
        const _top5ForXai = top5.slice(0, 5).filter(n => xaiMap[n] && Object.keys(xaiMap[n]).length > 0);
        const xaiTop5Weights = {};
        _XAI_MODEL_KEYS.forEach(m => {
            const sum = _top5ForXai.reduce((s, n) => s + (xaiMap[n][m + '_pct'] || 0), 0);
            xaiTop5Weights[m] = _top5ForXai.length > 0
                ? parseFloat((sum / _top5ForXai.length).toFixed(2))
                : 0;
        });
        // GNN 균일 예측이면 XAI 기여도 0으로 강제 (2.22%는 기저확률이지 기여도가 아님)
        if (_gnnUniform) xaiTop5Weights.gnn = 0;

        // ── combinations ──
        const combinations = (preds.combinations || []).map(c => ({
            numbers:    c.numbers || [],
            total_sum:  c.total_sum,
            odd_count:  c.odd_count,
            high_count: c.high_count,
            combo_rank: c.combo_rank
        }));

        return {
            success:          true,
            target_round:     preds.target_round,
            top_5:            top5,
            exclude_10:       exclude10,
            combinations,
            strategy,
            model_weights:    mw,
            xai_top5_weights: xaiTop5Weights, // XAI 실기여도 (모델 컨디션 차트용)
            gnn_uniform:      _gnnUniform,    // GNN 균일 예측 여부 (차트 레이블용)
            meta_active:      preds.meta_active,
            meta_alpha:       preds.meta_alpha,
            pipeline_version: preds.pipeline_version,
            created_at:       preds.created_at,
            elapsed_seconds:  0,
            _source:          'v4_weekly',
            analysis: {
                matrix_data:          matrixData,
                hot_cold_data,
                regression_analysis:  regressionAnalysis.length > 0 ? regressionAnalysis : regression_analysis,
                magic_square_analysis,
                lotto_paper_analysis,
                number_band_analysis,
                tail_analysis,
                range_analysis:       rangeAnalysis,
                missing_group_data:   missing_group_data
            },
            evidence: {
                model_weights: mw
            },
            recommendations: preds.recommendations || []
        };
    },

    // ── 모델별 번호 분석 이유 생성 ──
    _modelReason(modelName, score, numInfo = {}) {
        const gap = numInfo.gap !== null && numInfo.gap !== undefined ? numInfo.gap : '?';
        const hc  = numInfo.hot_cold || 'neutral';
        const hcLabel = hc === 'hot' ? '🔥 핫' : hc === 'cold' ? '🧊 콜드' : '🌡️ 중립';

        const tiers = (h, m, l, z) => score >= 40 ? h : score >= 15 ? m : score > 0 ? l : z;

        const reasons = {
            xgboost: tiers(
                `특성 기반 강력 추천 — ${gap < 4 ? '연속 출현 패턴' : gap > 15 ? '장기 미출현 반등 신호' : `gap ${gap}회차`}`,
                `특성 기반 중간 신호 — ${hcLabel} (gap ${gap})`,
                `특성 기반 신호 미미 — gap ${gap}`,
                '특성 신호 없음'
            ),
            lstm: tiers(
                `시계열 강신호 — ${hcLabel}, 최근 출현 주기 패턴 감지`,
                `시계열 보조 신호 — ${hcLabel} (gap ${gap})`,
                `시계열 패턴 약함 — gap ${gap}`,
                '시계열 패턴 미감지'
            ),
            cnn: tiers(
                '공간 패턴 강신호 — 로또용지 위치 집중 활성화',
                '공간 패턴 보조 신호 — 특정 행/열 패턴 감지',
                '공간 패턴 약신호',
                '공간 패턴 미감지 (학습 보완 필요)'
            ),
            transformer: tiers(
                '글로벌 어텐션 강신호 — 장거리 출현 의존성 포착',
                '글로벌 패턴 보조 신호 — 중거리 상관관계',
                '어텐션 신호 약함',
                '글로벌 패턴 미감지'
            ),
            markov: tiers(
                `전이확률 높음 — 직전 당첨번호와 강한 연결 (gap ${gap})`,
                `전이확률 중간 — 이전 회차 연관 존재`,
                '전이확률 낮음',
                '전이 연결 없음 — 직전 회차와 무관'
            ),
            autoencoder: tiers(
                '정상 패턴 감지 — 복원오차 최소, 이상 없음',
                '비교적 정상 패턴',
                '패턴 희소',
                '이상 패턴 없음 (페널티 미적용)'
            ),
            gnn: tiers(
                `그래프 공동출현 강신호 — 클러스터 핵심 번호`,
                '공동출현 보조 신호 — 일부 번호와 연관',
                '공동출현 신호 약함',
                '공동출현 그래프 신호 없음'
            )
        };
        return reasons[modelName] || (score > 0 ? `기여도 ${score}%` : '신호 없음');
    },

    async _fetchAnalysisFromDB(round) {
        if (!window.supabaseClient) return null;
        try {
            const { data, error } = await window.supabaseClient
                .from('deep_analysis_history')
                .select('analysis_data, target_round, created_at')
                .eq('target_round', round)
                .order('created_at', { ascending: false })
                .limit(1)
                .maybeSingle();

            if (data && data.analysis_data) {
                return typeof data.analysis_data === 'string'
                    ? JSON.parse(data.analysis_data)
                    : data.analysis_data;
            }
            return null;
        } catch (e) {
            return null;
        }
    },

    async _fetchLatestAnalysisFromDB() {
        if (!window.supabaseClient) return null;
        try {
            const { data, error } = await window.supabaseClient
                .from('deep_analysis_history')
                .select('analysis_data, target_round, created_at')
                .order('created_at', { ascending: false })
                .limit(1)
                .maybeSingle();

            if (data && data.analysis_data) {
                return typeof data.analysis_data === 'string'
                    ? JSON.parse(data.analysis_data)
                    : data.analysis_data;
            }
            return null;
        } catch (e) {
            return null;
        }
    },

    _getLastSaturdayKST() {
        const now = new Date();
        // KST = UTC+9
        const kstOffset = 9 * 60 * 60 * 1000;
        const kstNow = new Date(now.getTime() + kstOffset);
        const day = kstNow.getUTCDay(); // 0=Sun, 6=Sat
        const daysBack = day === 6 ? 0 : (day + 1); // 토요일이면 오늘, 아니면 지난 토요일
        const lastSat = new Date(kstNow.getTime() - daysBack * 24 * 60 * 60 * 1000);
        // 토요일 21:05 KST (추첨 완료 기준)
        lastSat.setUTCHours(12, 5, 0, 0); // 21:05 KST = 12:05 UTC
        return lastSat;
    },

    _getNextSaturdayKST() {
        const kstOffset = 9 * 60 * 60 * 1000;
        const kstNow = new Date(Date.now() + kstOffset);
        const day = kstNow.getUTCDay();
        const daysUntilSat = day === 6 ? 7 : (6 - day);
        const nextSat = new Date(kstNow.getTime() + daysUntilSat * 24 * 60 * 60 * 1000);
        const mm = String(nextSat.getUTCMonth() + 1).padStart(2, '0');
        const dd = String(nextSat.getUTCDate()).padStart(2, '0');
        return `${nextSat.getUTCFullYear()}.${mm}.${dd} 21:05`;
    },

    _canRunAnalysis() {
        try {
            const lastRun = parseInt(localStorage.getItem('dl_analysis_last_run_ts') || '0');
            if (!lastRun) return true;
            const lastSaturday = this._getLastSaturdayKST();
            // 마지막 실행이 지난 토요일 추첨 이후면 이번 주 이미 실행됨
            return lastRun < lastSaturday.getTime();
        } catch (e) {
            return true;
        }
    },

    _markAnalysisRun() {
        try {
            localStorage.setItem('dl_analysis_last_run_ts', String(Date.now()));
        } catch (e) { }
    },

    _updateWeeklyStatusUI() {
        const el = document.getElementById('weeklyAnalysisStatus');
        if (!el) return;
        try {
            const lastRun = parseInt(localStorage.getItem('dl_analysis_last_run_ts') || '0');
            const canRun = this._canRunAnalysis();
            if (lastRun) {
                const d = new Date(lastRun + 9 * 60 * 60 * 1000);
                const dateStr = `${d.getUTCFullYear()}.${String(d.getUTCMonth()+1).padStart(2,'0')}.${String(d.getUTCDate()).padStart(2,'0')}`;
                if (canRun) {
                    el.innerHTML = `<span class="text-[11px] text-emerald-600 font-medium">마지막 분석: ${dateStr} • <span class="text-blue-600">새 분석 가능</span></span>`;
                } else {
                    const next = this._getNextSaturdayKST();
                    el.innerHTML = `<span class="text-[11px] text-slate-500">마지막 분석: ${dateStr} • 다음 분석: ${next}</span>`;
                }
            } else {
                el.innerHTML = `<span class="text-[11px] text-slate-400">분석 이력 없음 • <span class="text-blue-600">첫 분석 가능</span></span>`;
            }
        } catch (e) { }
    },

    // ── V4 주간 파이프라인 배지 표시 ──
    _showV4Badge(v4Data) {
        try {
            // 기존 배지 제거
            document.querySelectorAll('.v4-pipeline-badge').forEach(el => el.remove());

            const round = v4Data?.target_round || this.state.targetRound;
            const badge = document.createElement('div');
            badge.className = 'v4-pipeline-badge flex items-center gap-2 bg-gradient-to-r from-blue-50 to-indigo-50 border border-blue-200 rounded-xl px-4 py-2 mb-4 text-sm font-semibold text-blue-700 shadow-sm';
            badge.innerHTML = `
                <span class="text-base">⚡</span>
                <span>주간 파이프라인 데이터 (V4) — 제<strong>${round}</strong>회차</span>
                <span class="ml-auto text-xs text-blue-400 font-normal">즉시 응답 모드</span>
            `;

            // 삽입 위치: aiSummaryText 상단 또는 첫 번째 섹션 위
            const anchor = document.getElementById('aiSummaryText')
                || document.querySelector('.analysis-section')
                || document.querySelector('main');
            if (anchor && anchor.parentElement) {
                anchor.parentElement.insertBefore(badge, anchor);
            }
        } catch (e) { /* 배지 표시 실패는 무시 */ }
    },

    async _runLocalFallbackAnalysis() {
        console.warn("🚫 [DeepLearning] 로컬 폴백 비활성화.");
        return null;
    },

    // ── 전체 렌더링 ──
    renderAll(result) {
        console.log("🎨 [DeepLearning] renderAll() Called", result);
        // 이전 회차 경고 배너 제거 (새 분석 결과 렌더 시)
        const oldBanner = document.getElementById('stale-round-banner');
        if (oldBanner) oldBanner.remove();
        this.state.pipeline = result.pipeline || null;
        const combinations = result.combinations;
        const strategy = result.strategy;
        const top5 = result.top_5;
        const exclude10 = result.exclude_10;

        const analysisData = result.analysis || {};
        const rangeAnalysis = analysisData.range_analysis || result.range_analysis || {};
        const matrixData = analysisData.matrix_data || result.matrix_data || [];

        const modelWeights = (result.evidence && result.evidence.model_weights) ? result.evidence.model_weights : (result.model_weights || {});

        if (matrixData && matrixData.length > 0) {
            let maxTotal = 0;
            const maxScores = { lstm: 0, xgboost: 0, cnn: 0, transformer: 0, markov: 0, autoencoder: 0, gnn: 0 };
            matrixData.forEach(item => {
                if (item.total > maxTotal) maxTotal = item.total;
                ['lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'].forEach(m => {
                    if (item.models && item.models[m] && item.models[m].score > maxScores[m]) {
                        maxScores[m] = item.models[m].score;
                    }
                });
            });
            if (maxTotal > 105) {
                matrixData.forEach(item => {
                    item.raw_total = item.total;
                    item.total = maxTotal > 0 ? parseFloat(((item.total / maxTotal) * 100).toFixed(2)) : 0;
                    ['lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'].forEach(m => {
                        if (item.models && item.models[m] && item.models[m].score) {
                            item.models[m].score = maxScores[m] > 0 ? parseFloat(((item.models[m].score / maxScores[m]) * 100).toFixed(2)) : 0;
                        }
                    });
                });
            }
        }

        const numberProbs = {};
        if (matrixData) {
            matrixData.forEach(function (item) {
                numberProbs[String(item.num)] = (item.total || 0) / 100;
            });
        }

        const modelTop10 = {};
        if (matrixData && matrixData.length > 0) {
            const models = ['lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'];
            models.forEach(function (m) {
                const sorted = [...matrixData].sort((a, b) => {
                    const sa = ((a.models || {})[m] || {}).score || 0;
                    const sb = ((b.models || {})[m] || {}).score || 0;
                    if (sb !== sa) return sb - sa;
                    return a.num - b.num;
                }).slice(0, 10);
                modelTop10[m] = sorted.map(item => ({
                    number: item.num,
                    prob: (((item.models || {})[m] || {}).score || 0) / 100
                }));
            });
        }

        const compatAnalysis = {
            number_probabilities: numberProbs,
            model_top10: modelTop10,
            model_weights: modelWeights,
            top_6: (top5 || []).slice(0, 6),
            recommended: (top5 || []).slice(0, 10),
            excluded: (exclude10 || []).slice(0, 10)
        };

        const memoExcluded = this._parseMemoExclusions(this.state.expertMemos || []);
        if (memoExcluded.length > 0) {
            const memoExcSet = new Set(memoExcluded);
            compatAnalysis.recommended = (compatAnalysis.recommended || []).filter(n => !memoExcSet.has(n));
            compatAnalysis.top_6 = (compatAnalysis.top_6 || []).filter(n => !memoExcSet.has(n));
            const exSet = new Set([...(compatAnalysis.excluded || []), ...memoExcluded]);
            compatAnalysis.excluded = [...exSet];
            if (result.top_5) result.top_5 = result.top_5.filter(n => !memoExcSet.has(n));
            if (result.exclude_10) {
                const ex10Set = new Set([...result.exclude_10, ...memoExcluded]);
                result.exclude_10 = [...ex10Set];
            }
            if (result.combinations && result.combinations.length > 0) {
                const filtered = result.combinations.filter(
                    c => !(c.numbers || []).some(n => memoExcSet.has(n))
                );
                if (filtered.length > 0) result.combinations = filtered;
            }
            if (matrixData) {
                matrixData.forEach(item => {
                    if (memoExcSet.has(item.num)) item.memo_excluded = true;
                });
            }
        }

        this.renderStrategy(strategy, result.elapsed_seconds);
        this.renderHotColdRisk(strategy);
        this.renderHeatmap(compatAnalysis.number_probabilities);
        this.renderModelTop10(compatAnalysis.model_top10, modelWeights);

        if (matrixData && matrixData.length) this.renderModelRanking(matrixData);
        if (rangeAnalysis) this.renderRangeAnalysis(rangeAnalysis);
        if (matrixData) this.renderMatrixData(matrixData);
        if (analysisData.tail_analysis) this.renderTailAnalysis(analysisData.tail_analysis);
        if (analysisData.lotto_paper_analysis) this.renderLottoPaperAnalysis(analysisData.lotto_paper_analysis);
        if (analysisData.magic_square_analysis) this.renderMagicSquareAnalysis(analysisData.magic_square_analysis);
        if (analysisData.number_band_analysis) this.renderNumberBandAnalysis(analysisData.number_band_analysis);

        // ── hot_cold num_details → 모델별 확률 캐시 (구형 DB 보강 공통 소스) ──
        this._buildNumModelProbs(analysisData.hot_cold_data);

        // 미출현 그룹: model_exp 없으면 hot_cold 확률로 보강 후 렌더링
        if (analysisData.missing_group_data) {
            this._enrichMissingGroupData(analysisData.missing_group_data);
            this.renderMissingGroupAnalysis(analysisData.missing_group_data);
        }
        if (analysisData.hot_cold_data) this.renderHotColdAnalysis(analysisData.hot_cold_data).catch(e => console.error('[hot_cold]', e));
        if (analysisData.regression_analysis) {
            this.renderRegressionAnalysis(analysisData.regression_analysis);
            // 비동기 보강: notable + model_exp (draws 로드 후)
            this._loadAndEnrichRegression(analysisData.regression_analysis).then(enriched => {
                this.renderRegressionAnalysis(enriched);
            });
        }
        if (analysisData.custom_evaluations) {
            this._enrichCustomEvaluations(analysisData.custom_evaluations);
            this.renderCustomEvaluations(analysisData.custom_evaluations);
        }

        this.renderExcludeFixed(strategy, compatAnalysis);
        this.renderCombinations(result.combinations, compatAnalysis, matrixData);

        var effectivePipeline = result.pipeline;
        if (!effectivePipeline) {
            // xai_top5_weights 우선 (실데이터) — 없으면 model_weights fallback
            const hasXai = result.xai_top5_weights && Object.values(result.xai_top5_weights).some(v => v > 0);
            effectivePipeline = {
                modelWeights:  hasXai ? result.xai_top5_weights : (result.evidence?.model_weights || null),
                isXaiMode:     hasXai,
                gnnUniform:    !!result.gnn_uniform,
                top5Numbers:   result.top_5 || [],
                weightReasons: result.evidence?.task_key
                    ? `Task: ${result.evidence.task_key} | Meta: ${result.meta_active ? '활성' : '비활성'}`
                    : '',
                rlGenerated: true
            };
        }
        if (effectivePipeline) {
            this.renderPipelineInfo(effectivePipeline);
        }
        this.renderExpertMemoSection(this.state.expertMemos || []);
    },

    getBallColorClass(n) {
        n = parseInt(n);
        if (n <= 10) return 'ball-yellow';
        if (n <= 20) return 'ball-blue';
        if (n <= 30) return 'ball-red';
        if (n <= 40) return 'ball-gray';
        return 'ball-green';
    },

    getBallColor(n) {
        n = parseInt(n);
        if (n <= 10) return '#F7C948';
        if (n <= 20) return '#4a90d9';
        if (n <= 30) return '#E04A4A';
        if (n <= 40) return '#6B7280';
        return '#48B05A';
    },

    renderStrategy(strategy, elapsed) {
        if (!strategy) return;
        const conf = strategy.confidence || 0;
        this.animateValue('confidenceScore', 0, conf, 1500);
        const bar = document.getElementById('confidenceBar');
        if (bar) setTimeout(function () { bar.style.width = conf + '%'; }, 100);
        const summaryEl = document.getElementById('aiSummaryText');
        if (summaryEl) summaryEl.textContent = strategy.summary || '분석 결과가 없습니다.';
        const tagEl = document.getElementById('keywordTags');
        if (tagEl && strategy.keywords) {
            tagEl.innerHTML = strategy.keywords.map(function (k) {
                return '<span class="px-3 py-1 bg-white text-blue-700 text-xs font-bold rounded-lg border border-blue-100 shadow-sm">' + k + '</span>';
            }).join('');
        }
        const elapsedEl = document.getElementById('elapsedTime');
        if (elapsedEl && elapsed) {
            elapsedEl.textContent = '분석 소요: ' + elapsed + '초';
        }
    },

    renderHotColdRisk(strategy) {
        if (!strategy) return;
        const hcUI = document.getElementById('hotColdUI');
        if (hcUI) {
            const hc = strategy.hot_cold_analysis;
            if (hc && typeof hc === 'object') {
                const hotR  = hc.hot_ratio  ?? 0;   // || 50 기본값 제거 — 가짜 데이터 방지
                const coldR = hc.cold_ratio ?? 0;
                // hot+cold+나머지 세 영역 시각화 (합이 100%를 넘을 수 있으므로 별도 바)
                hcUI.innerHTML = `
                    <div class="flex items-center justify-between text-xs font-bold text-gray-500 mb-1">
                        <span class="text-rose-500">Hot(최근출현) ${hotR}%</span>
                        <span class="text-blue-500">Cold(장기미출현) ${coldR}%</span>
                    </div>
                    <div class="w-full h-2 bg-gray-100 rounded-full overflow-hidden mb-1">
                        <div class="h-full bg-rose-400 rounded-full" style="width:${Math.min(hotR,100)}%"></div>
                    </div>
                    <div class="w-full h-2 bg-gray-100 rounded-full overflow-hidden">
                        <div class="h-full bg-blue-400 rounded-full" style="width:${Math.min(coldR,100)}%"></div>
                    </div>
                    <p class="text-xs font-medium text-gray-600 mt-2 leading-snug">${hc.trend_text || ''}</p>
                `;
            } else if (typeof hc === 'string' && hc) {
                hcUI.innerHTML = '<p class="text-sm font-medium text-gray-700 leading-snug">' + hc + '</p>';
            } else {
                hcUI.innerHTML = '<p class="text-sm text-gray-400">데이터 없음</p>';
            }
        }
        const riskUI = document.getElementById('riskUI');
        if (riskUI) {
            const rs = strategy.risk_assessment;
            if (rs && typeof rs === 'object') {
                const score = rs.risk_score || 0;
                let color = score >= 70 ? 'text-red-500' : score >= 40 ? 'text-amber-500' : 'text-emerald-500';
                let bgColor = score >= 70 ? 'bg-red-50' : score >= 40 ? 'bg-amber-50' : 'bg-emerald-50';
                riskUI.innerHTML = `
                    <div class="flex items-end gap-2 mb-2">
                        <span class="text-3xl font-black ${color} leading-none tracking-tight">${score}</span>
                        <span class="text-xs font-bold px-2 py-1 rounded ${bgColor} ${color} mb-1">${rs.risk_level || ''}</span>
                    </div>
                    <p class="text-xs font-medium text-gray-700 mt-2 leading-snug break-keep">${rs.warning_text || ''}</p>
                `;
            } else if (typeof rs === 'string' && rs) {
                riskUI.innerHTML = '<p class="text-sm font-medium text-gray-700 leading-snug">' + rs + '</p>';
            } else {
                riskUI.innerHTML = '<p class="text-sm text-gray-400">데이터 없음</p>';
            }
        }
        const strategyUI = document.getElementById('overallStrategyUI');
        if (strategyUI) {
            const os = strategy.overall_strategy;
            if (os && typeof os === 'object') {
                let actionsHtml = (os.key_actions || []).map(action =>
                    '<span class="inline-block px-2 py-1 bg-green-50 border border-green-100 text-green-700 text-xs font-bold rounded mb-1 mr-1">' + action + '</span>'
                ).join('');
                strategyUI.innerHTML = '<div class="flex flex-wrap mb-2">' + actionsHtml + '</div>' +
                    '<p class="text-xs font-medium text-gray-700 mt-1 leading-snug break-keep">' + (os.short_advice || '') + '</p>';
            } else if (typeof os === 'string' && os) {
                strategyUI.innerHTML = '<p class="text-sm font-medium text-gray-700 leading-snug">' + os + '</p>';
            } else {
                strategyUI.innerHTML = '<p class="text-sm text-gray-400">데이터 없음</p>';
            }
        }
    },

    renderHeatmap(numberProbs) {
        const container = document.getElementById('heatmapContainer');
        if (!container || !numberProbs) return;
        const values = Object.values(numberProbs).map(Number);
        const minP = Math.min.apply(null, values);
        const maxP = Math.max.apply(null, values);
        const range = maxP - minP || 1;
        let html = '';
        for (let n = 1; n <= 45; n++) {
            const p = Number(numberProbs[String(n)] || 0);
            const norm = (p - minP) / range;
            const pct = (p * 100).toFixed(2);
            const bgColor = this.getHeatmapColor(norm);
            const textColor = norm > 0.6 ? 'white' : 'rgba(0,0,0,0.8)';
            html += '<div class="heatmap-cell rounded-xl flex flex-col items-center justify-center p-2 aspect-square relative transition-transform hover:scale-105 shadow-sm" ' +
                'style="background-color: ' + bgColor + '; color: ' + textColor + '" ' +
                'onclick="window.DeepLearning.explainNumber(' + n + ')" ' +
                'title="' + n + '번: ' + pct + '%">' +
                '<span class="text-lg font-black">' + n + '</span>' +
                '<span class="text-[10px] font-bold opacity-80">' + pct + '%</span>' +
                '</div>';
        }
        container.innerHTML = html;
    },

    getHeatmapColor(norm) {
        if (norm < 0.25) return 'rgba(229, 231, 235, ' + (0.6 + norm * 1.6) + ')';
        else if (norm < 0.5) {
            var t = (norm - 0.25) / 0.25;
            return 'rgb(' + 253 + ', ' + Math.round(224 + t * 10) + ', ' + Math.round(71 + (1 - t) * 100) + ')';
        } else if (norm < 0.75) {
            var t2 = (norm - 0.5) / 0.25;
            return 'rgb(' + 251 + ', ' + Math.round(191 - t2 * 80) + ', 36)';
        } else {
            return 'rgb(239, 68, 68)';
        }
    },

    renderModelTop10(modelTop10, weights) {
        const container = document.getElementById('modelDetailContainer');
        if (!container || !modelTop10) return;
        const modelConfig = {
            lstm: { label: 'LSTM (시계열)', icon: 'timeline', gradient: 'from-blue-500 to-blue-600', barColor: '#818cf8' },
            xgboost: { label: 'XGBoost (패턴)', icon: 'account_tree', gradient: 'from-blue-500 to-blue-600', barColor: '#60a5fa' },
            cnn: { label: 'CNN (공간)', icon: 'grid_view', gradient: 'from-pink-500 to-pink-600', barColor: '#f472b6' },
            transformer: { label: 'Transformer (맥락)', icon: 'psychology', gradient: 'from-orange-500 to-orange-600', barColor: '#fb923c' },
            markov: { label: 'Markov (통계)', icon: 'analytics', gradient: 'from-emerald-500 to-emerald-600', barColor: '#34d399' },
            autoencoder: { label: 'Autoencoder (압축)', icon: 'compress', gradient: 'from-purple-500 to-purple-600', barColor: '#a855f7' },
            gnn: { label: 'GNN (관계망)', icon: 'hub', gradient: 'from-red-500 to-red-600', barColor: '#ef4444' }
        };
        var self = this;
        var html = '';
        Object.keys(modelConfig).forEach(function (key) {
            var cfg = modelConfig[key];
            var items = modelTop10[key] || [];
            if (items.length === 0) return;
            var w_val = (weights && weights[key] !== undefined) ? weights[key] : 0;
            var weight = (w_val * 100).toFixed(1);
            var maxProb = items.length > 0 ? Math.max.apply(null, items.map(function (i) { return i.prob; })) : 1;
            html += '<div class="bg-white rounded-2xl border border-gray-100 overflow-hidden shadow-sm hover:shadow-md transition-shadow">' +
                '<div class="px-5 py-4 bg-white border-b border-gray-100 flex justify-between items-center">' +
                '<div class="flex items-center gap-2">' +
                '<div class="p-1.5 rounded-lg bg-gray-50 text-gray-600"><span class="material-symbols-outlined text-sm">' + cfg.icon + '</span></div>' +
                '<span class="font-bold text-gray-800 text-sm">' + cfg.label + '</span>' +
                '</div>' +
                '<span class="text-xs font-bold bg-gray-50 text-gray-600 px-2 py-1 rounded-lg">' + weight + '%</span>' +
                '</div>' +
                '<div class="p-5 space-y-3">';
            items.forEach(function (item) {
                var barWidth = maxProb > 0 ? (item.prob / maxProb * 100).toFixed(1) : 0;
                var colorClass = self.getBallColorClass(item.number);
                html += '<div class="flex items-center gap-3 group cursor-pointer" onclick="window.DeepLearning.explainNumber(' + item.number + ')">' +
                    '<span class="ball-common ' + colorClass + ' w-8 h-8 text-xs shadow-none group-hover:scale-110 transition-transform flex-shrink-0">' + item.number + '</span>' +
                    '<div class="flex-1 h-2.5 bg-gray-100 rounded-full overflow-hidden">' +
                    '<div class="prob-bar-fill h-full rounded-full" style="width: ' + barWidth + '%; background-color: ' + cfg.barColor + '"></div>' +
                    '</div>' +
                    '<span class="text-xs font-bold text-gray-500 w-12 text-right">' + (item.prob * 100).toFixed(1) + '%</span>' +
                    '</div>';
            });
            html += '</div></div>';
        });
        container.className = "grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6";
        container.innerHTML = html;
    },

    renderRangeAnalysis(rangeAnalysis) {
        const container = document.getElementById('rangeAnalysisContainer');
        if (!container || !rangeAnalysis) return;

        // 출처 뱃지: filter.html 연동 안내
        const sourceEl = document.getElementById('rangeAnalysisSource');
        if (sourceEl) {
            const round = this.state.targetRound;
            sourceEl.innerHTML = `<span class="text-[11px] text-slate-400">앙상블 기반 • ${round}회차 예측 •
                <a href="filter.html" class="text-indigo-500 font-bold hover:underline">filter.html</a>에서 AI 추천값 클릭으로 적용</span>`;
        }
        const FILTER_LABELS = {
            sum: '총합', tail_sum: '끝수합', ac: 'AC값',
            odd: '홀짝', high: '저고', prime: '소수',
            composite: '합성수', consecutive: '연번', square: '제곱수',
            triangular: '삼각수', twin: '동형수', mul3: '3배수',
            mul4: '4배수', mul5: '5배수', mul7: '7배수', mul8: '8배수',
            non_multiple: '배수외',
            neighbor: '이웃수', carryover: '이월수'
        };
        // 명시적 제외 목록 (hot10·missing은 동적 지표로 범위 의미 없음)
        const FILTER_EXCLUDE = new Set(['hot10', 'missing']);
        const FILTER_ORDER = [
            'sum', 'tail_sum', 'ac',
            'odd', 'high', 'consecutive', 'twin',
            'prime', 'composite', 'square', 'triangular',
            'mul3', 'mul4', 'mul5', 'mul7', 'mul8', 'non_multiple',
            'neighbor', 'carryover'
        ];
        // 백엔드 key → localStorage key 매핑 (현재 설정값 읽기용)
        const FILTER_TO_LS = {
            sum: 'total_sum', tail_sum: 'last_digit_sum', ac: 'ac_value',
            odd: 'odd_even_pattern', high: 'high_low_pattern',
            prime: 'prime_number_patterns', composite: 'composite_count',
            consecutive: 'consecutive_count', square: 'square_number_patterns',
            triangular: 'triangular_number_patterns', twin: 'twin_number_patterns',
            mul3: 'multiple_3_count', mul4: 'multiple_4_count', mul5: 'multiple_5_count',
            mul7: 'multiple_7_count', mul8: 'multiple_8_count',
            non_multiple: 'no_multiple_count',
            hot10: 'hot_cold_10', missing: 'missing_period',
            neighbor: 'neighbor_number_patterns', carryover: 'carryover_count'
        };
        const FILTER_MAX = { mul8: 5, non_multiple: 6 };
        // localStorage에서 현재 활성 필터 min~max 읽기
        const _getCurrentSetting = (key) => {
            const lsKey = FILTER_TO_LS[key];
            if (!lsKey) return null;
            try {
                const raw = localStorage.getItem(lsKey);
                if (!raw) return null;
                const p = JSON.parse(raw);
                const enabled = p.enabled !== undefined ? p.enabled : true;
                if (!enabled) return null;
                const s = p.settings !== undefined ? p.settings : p;
                if (s.min !== undefined && s.max !== undefined) return `${s.min}~${s.max}`;
                if (s.selectedCounts && s.selectedCounts.length > 0) {
                    const mn = s.selectedCounts[0], mx = s.selectedCounts[s.selectedCounts.length - 1];
                    return mn === mx ? `${mn}` : `${mn}~${mx}`;
                }
            } catch(e) {}
            return null;
        };
        const MODEL_CONFIG = {
            lstm: { label: 'LSTM', color: '#818cf8', bg: '#eef2ff' },
            xgboost: { label: 'XGBoost', color: '#60a5fa', bg: '#eff6ff' },
            cnn: { label: 'CNN', color: '#f472b6', bg: '#fdf2f8' },
            transformer: { label: 'Transformer', color: '#fb923c', bg: '#fff7ed' },
            markov: { label: 'Markov', color: '#34d399', bg: '#f0fdf4' },
            autoencoder: { label: 'Auto', color: '#a855f7', bg: '#faf5ff' },
            gnn: { label: 'GNN', color: '#ef4444', bg: '#fef2f2' }
        };
        const models = ['lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'];
        let html = '<div class="overflow-x-auto rounded-2xl border border-gray-100 shadow-sm bg-white">';
        html += '<table class="w-full text-xs">';
        html += '<thead><tr>';
        html += '<th class="px-5 py-4 text-left font-bold text-gray-700">지표</th>';
        html += '<th class="px-4 py-4 text-center font-bold text-emerald-600 bg-emerald-50/50">현재<br>설정</th>';
        html += '<th class="px-4 py-4 text-center font-bold text-blue-600 bg-blue-50/50">앙상블<br>범위</th>';
        models.forEach(m => {
            const cfg = MODEL_CONFIG[m];
            html += `<th class="px-4 py-4 text-center font-bold text-gray-500">${cfg.label}<br><span class="text-gray-400 font-normal text-[10px]">예상범위</span></th>`;
        });
        html += '</tr></thead><tbody>';
        let rowIdx = 0;
        const orderedEntries = FILTER_ORDER
            .filter(k => rangeAnalysis[k] !== undefined)
            .map(k => [k, rangeAnalysis[k]])
            .concat(Object.entries(rangeAnalysis).filter(([k]) => !FILTER_ORDER.includes(k) && !FILTER_EXCLUDE.has(k)));

        const formatRatioRange = (key, rawRange) => {
            const isRatioKey = (key === 'odd' || key === 'high');
            if (!isRatioKey) {
                if (Array.isArray(rawRange)) return rawRange[0] + '~' + rawRange[1];
                return rawRange || '-';
            }
            let lo, hi;
            if (Array.isArray(rawRange)) { lo = rawRange[0]; hi = rawRange[1]; }
            else if (typeof rawRange === 'string' && rawRange.includes('~')) {
                const parts = rawRange.split('~');
                lo = parseInt(parts[0]); hi = parseInt(parts[1]);
            } else return rawRange || '-';
            const patterns = [];
            for (let v = lo; v <= hi; v++) {
                const other = 6 - v;
                if (key === 'odd') patterns.push(`${v}:${other}`);
                else patterns.push(`${other}:${v}`);
            }
            if (patterns.length === 0) return rawRange || '-';
            if (patterns.length === 1) return patterns[0];
            if (patterns.length > 3) return patterns[0] + ' ~ ' + patterns[patterns.length - 1];
            return patterns.join(', ');
        };
        const formatModelRatio = (key, exp) => {
            if (!exp) return '-';
            const min = exp.min != null ? exp.min : null;
            const max = exp.max != null ? exp.max : null;
            if (min === null || max === null) return '-';
            const isRatioKey = (key === 'odd' || key === 'high');
            if (!isRatioKey) return `${min}~${max}`;
            const patterns = [];
            for (let v = min; v <= max; v++) {
                const other = 6 - v;
                if (key === 'odd') patterns.push(`${v}:${other}`);
                else patterns.push(`${other}:${v}`);
            }
            if (patterns.length === 0) return `${min}~${max}`;
            if (patterns.length === 1) return patterns[0];
            if (patterns.length > 3) return patterns[0] + '~' + patterns[patterns.length - 1];
            return patterns.join(', ');
        };
        for (const [key, val] of orderedEntries) {
            const label = FILTER_LABELS[key] || key;
            const rawRange = val.range;
            const ensembleRange = formatRatioRange(key, rawRange);
            const modelExp = val.model_expectations || {};
            const currentSetting = _getCurrentSetting(key);
            rowIdx++;
            html += `<tr class="border-b border-gray-50 last:border-0 hover:bg-gray-50 transition-colors">`;
            html += `<td class="px-5 py-3 font-bold text-gray-700">${label}</td>`;
            // 현재 설정 컬럼: 설정됨=초록, 없음=회색 대시
            if (currentSetting) {
                html += `<td class="px-4 py-3 text-center font-mono font-bold text-emerald-600 bg-emerald-50/30">${currentSetting}</td>`;
            } else {
                html += `<td class="px-4 py-3 text-center text-gray-300 bg-emerald-50/10">-</td>`;
            }
            html += `<td class="px-4 py-3 text-center font-mono font-bold text-blue-600 bg-blue-50/30">${ensembleRange}</td>`;
            models.forEach(m => {
                const cfg = MODEL_CONFIG[m];
                const exp = modelExp[m];
                const cellText = formatModelRatio(key, exp);
                const title = exp ? (exp.reasoning || '') : '';
                const cellHtml = cellText === '-'
                    ? '<span class="text-gray-300">-</span>'
                    : `<span class="font-mono font-semibold text-gray-600">${cellText}</span>`;
                html += `<td class="px-4 py-3 text-center" title="${title}">${cellHtml}</td>`;
            });
            html += '</tr>';
        }
        html += '</tbody></table></div>';
        container.innerHTML = html;
    },

    renderMatrixData(matrixData) {
        const container = document.getElementById('matrixDataContainer');
        if (!container || !matrixData || matrixData.length === 0) return;
        this._matrixData = matrixData;
        this.sortMatrix('total');
    },

    sortMatrix(key) {
        const matrixData = this._matrixData;
        if (!matrixData) return;
        const colors = { total: '#1F2937', lstm: '#818cf8', xgboost: '#60a5fa', cnn: '#f472b6', transformer: '#fb923c', markov: '#34d399', autoencoder: '#a855f7', gnn: '#ef4444' };
        ['total', 'lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'].forEach(k => {
            const btn = document.getElementById('sort-btn-' + k);
            if (!btn) return;
            if (k === key) { btn.style.background = colors[k]; btn.style.color = '#fff'; btn.style.borderColor = colors[k]; }
            else { btn.style.background = '#fff'; btn.style.color = k === 'total' ? '#374151' : colors[k]; btn.style.borderColor = '#E5E7EB'; }
        });
        const MODEL_CONFIG = {
            lstm: { label: 'LSTM', color: '#818cf8' },
            xgboost: { label: 'XGBoost', color: '#60a5fa' },
            cnn: { label: 'CNN', color: '#f472b6' },
            transformer: { label: 'Transformer', color: '#fb923c' },
            markov: { label: 'Markov', color: '#34d399' },
            autoencoder: { label: 'Autoencoder', color: '#a855f7' },
            gnn: { label: 'GNN', color: '#ef4444' }
        };
        const models = ['lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'];
        const self = this;
        const container = document.getElementById('matrixDataContainer');
        const sorted = [...matrixData].sort((a, b) => {
            if (key === 'total') return (b.total || 0) - (a.total || 0);
            const sa = ((a.models || {})[key] || {}).score || 0;
            const sb = ((b.models || {})[key] || {}).score || 0;
            return sb - sa;
        });
        let html = '<div class="space-y-4">';
        sorted.forEach(item => {
            const num = item.num;
            const total = Math.round(item.total || 0);
            const rawTotal = Math.round(item.raw_total || item.total || 0);
            const gap = item.gap || 0;
            const freq = item.freq ? (item.freq * 100).toFixed(1) : '-';
            const colorClass = self.getBallColorClass(num);
            const scoreColor = total >= 70 ? '#EF4444' : total >= 50 ? '#F59E0B' : '#9CA3AF';
            const overRatio = item.over_ratio != null ? item.over_ratio : null;
            const penalty = item.penalty != null ? item.penalty : 1.0;
            const gapRatio = item.gap_ratio != null ? item.gap_ratio : null;
            const boost = item.boost != null ? item.boost : 1.0;
            const personalAvgGap = item.personal_avg_gap;
            const isExcluded = item.memo_excluded === true;
            let corrBadges = '';
            if (isExcluded) {
                corrBadges += `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-gray-800 text-white">🚫 제외</span> `;
            }
            if (!isExcluded && penalty < 1.0) {
                const penLabel = penalty <= 0.35 ? '⚠️ 극심과출현' : penalty <= 0.5 ? '🔴 강과출현' : '🟠 과출현';
                corrBadges += `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-red-50 text-red-600 border border-red-100">${penLabel}</span> `;
            }
            if (!isExcluded && boost > 1.0) {
                const boostLabel = boost >= 1.45 ? '⚡ 출현임박' : boost >= 1.25 ? '🔔 주기초과' : '📈 주기근접';
                corrBadges += `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-50 text-emerald-700 border border-emerald-100">${boostLabel}</span>`;
            }
            html += `<div class="${isExcluded ? 'bg-gray-50 opacity-50' : 'bg-white'} rounded-2xl border ${isExcluded ? 'border-gray-200' : 'border-gray-200'} overflow-hidden shadow-sm hover:shadow-md transition-all">`;
            html += `<div class="flex items-center gap-5 px-6 py-4 bg-white border-b border-gray-50">`;
            html += `<span class="ball-common ${colorClass} w-10 h-10 text-base shadow-lg cursor-pointer hover:scale-110 transition-transform flex-shrink-0 ${isExcluded ? 'grayscale' : ''}" onclick="window.DeepLearning.explainNumber(${num})">${num}</span>`;
            html += `<div class="flex-1 flex flex-wrap items-center gap-x-5 gap-y-1 text-sm text-gray-500">`;
            html += `<span>Gap <strong class="text-gray-900">${gap}</strong></span>`;
            html += `<span>빈도 <strong class="text-gray-900">${freq}%</strong></span>`;
            if (rawTotal !== total) html += `<span class="text-gray-400 text-xs">원점수 <s class="text-gray-300">${rawTotal}</s>→<strong class="text-gray-500">${total}</strong></span>`;
            if (corrBadges) html += corrBadges;
            html += `</div>`;
            html += `<span class="font-black text-2xl tracking-tight" style="color:${isExcluded ? '#9CA3AF' : scoreColor}">${total}</span>`;
            html += `</div>`;
            html += `<div class="grid grid-cols-1 divide-y divide-gray-50 px-6 py-2 ${isExcluded ? 'grayscale opacity-70' : ''}">`;
            models.forEach(m => {
                const cfg = MODEL_CONFIG[m];
                const mData = (item.models || {})[m] || {};
                const score = mData.score != null ? mData.score : '-';
                const reason = mData.reason || mData.reasoning || '-';
                const isActive = key === m;
                html += `<div class="flex items-center gap-4 py-2.5 text-xs">`;
                html += `<span class="font-bold w-24 flex-shrink-0${isActive ? ' text-blue-600' : ' text-gray-500'}">${cfg.label}</span>`;
                html += `<div class="flex-1 bg-gray-100 h-2 rounded-full overflow-hidden"><div class="h-full rounded-full" style="width:${Math.min(score === '-' ? 0 : score, 100)}%;background:${cfg.color}"></div></div>`;
                html += `<span class="font-bold w-8 text-right text-gray-700">${score}</span>`;
                html += `<span class="text-gray-400 flex-1 truncate ml-3" title="${reason}">${reason}</span>`;
                html += `</div>`;
            });
            html += `</div></div>`;
        });
        html += '</div>';
        container.innerHTML = html;
    },

    renderExcludeFixed(strategy, analysis) {
        var fixedNums, fixedEvidence, excludeNums, excludeEvidence;
        if (analysis.recommended && analysis.recommended.length > 0) {
            fixedNums = analysis.recommended;
            fixedEvidence = '앙상블 7개 모델 상위 추천';
        } else if (strategy && strategy.fixed_numbers && strategy.fixed_numbers.numbers) {
            fixedNums = strategy.fixed_numbers.numbers;
            fixedEvidence = strategy.fixed_numbers.evidence;
        } else {
            fixedNums = analysis.top_7 || [];
            fixedEvidence = '앙상블 모델 상위 확률 기반';
        }
        this.renderBalls('fixedNumbers', fixedNums);
        this._showEvidence('fixedEvidence', fixedEvidence);
        if (analysis.excluded && analysis.excluded.length > 0) {
            excludeNums = analysis.excluded;
            excludeEvidence = '앙상블 7개 모델 하위 제외';
        } else if (strategy && strategy.exclude_numbers && strategy.exclude_numbers.numbers) {
            excludeNums = strategy.exclude_numbers.numbers;
            excludeEvidence = strategy.exclude_numbers.evidence;
        } else {
            excludeNums = [];
            excludeEvidence = '앙상블 모델 하위 확률 기반';
        }
        this.renderBalls('excludeNumbers', excludeNums);
        this._showEvidence('excludeEvidence', excludeEvidence);
    },

    _showEvidence(id, text) {
        var el = document.getElementById(id);
        if (!el) return;
        if (text) {
            el.textContent = '📋 ' + text;
            el.classList.remove('hidden');
        } else {
            el.classList.add('hidden');
        }
    },


    renderCombinations(combinations, analysis, matrixData) {
        const container = document.getElementById('combos');
        if (!container || !combinations || combinations.length === 0) return;
        const self = this;
        const top5Set = new Set(analysis ? (analysis.recommended || analysis.top_6 || []) : []);
        const excludeSet = new Set(analysis ? (analysis.excluded || []) : []);
        const scoreMap = {};
        if (matrixData) matrixData.forEach(d => { scoreMap[d.num] = Math.round(d.total || 0); });
        const maxScore = Math.max(...combinations.map(c => c.score || 0)) || 1;
        const modelTop = {};
        if (matrixData) {
            ['lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'].forEach(m => {
                const sorted = [...matrixData].sort((a, b) => ((b.models || {})[m] || {}).score - ((a.models || {})[m] || {}).score);
                modelTop[m] = new Set(sorted.slice(0, 10).map(d => d.num));
            });
        }
        const anomalyMap = {};
        const pipeline = this.state.pipeline || {};
        if (pipeline.anomalyResults) {
            pipeline.anomalyResults.forEach(function (r) {
                anomalyMap[r.combo.join('-')] = r;
            });
        }
        container.innerHTML = combinations.map((combo, idx) => {
            const nums = combo.numbers || [];
            const rank = combo.rank || idx + 1;
            const score = combo.score || 0;
            const scorePct = maxScore > 0 ? score / maxScore : 0;
            const anomaly = anomalyMap[nums.join('-')];
            const isVerified = pipeline.rlGenerated && (!anomaly || anomaly.passed !== false);
            const topIncluded = nums.filter(n => top5Set.has(n));
            const modelAgreement = ['lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'].filter(m =>
                nums.some(n => modelTop[m] && modelTop[m].has(n))
            ).length;
            const sum = nums.reduce((a, b) => a + b, 0);
            const odd = nums.filter(n => n % 2 !== 0).length;
            const high = nums.filter(n => n >= 24).length;
            const ac = (() => {
                const diffs = new Set();
                for (let i = 0; i < nums.length; i++)
                    for (let j = i + 1; j < nums.length; j++)
                        diffs.add(Math.abs(nums[i] - nums[j]));
                return diffs.size - (nums.length - 1);
            })();
            // 순위별 좌측 액센트 색상
            const accentColor = rank === 1 ? '#6366F1' : rank <= 3 ? '#8B5CF6' : rank <= 6 ? '#3B82F6' : '#E5E7EB';
            const rankTextCls = rank === 1 ? 'text-indigo-600' : rank <= 3 ? 'text-violet-500' : rank <= 6 ? 'text-blue-400' : 'text-gray-200';

            const ballsHtml = nums.map(n => {
                const colorClass = self.getBallColorClass(n);
                const isTop = top5Set.has(n);
                return `<span style="position:relative;display:inline-flex;flex-direction:column;align-items:center;cursor:pointer" onclick="window.DeepLearning.explainNumber(${n})">
                    <span class="ball-common ${colorClass} w-9 h-9 text-sm ${isTop ? 'ring-2 ring-amber-400 ring-offset-1' : ''}">${n}</span>
                    ${isTop ? '<span style="position:absolute;top:-3px;right:-3px;width:7px;height:7px;background:#FBBF24;border-radius:50%;border:1.5px solid white;"></span>' : ''}
                </span>`;
            }).join('');

            const MODEL_LIST = ['lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'];
            const MODEL_COLORS = { lstm: '#818cf8', xgboost: '#60a5fa', cnn: '#f472b6', transformer: '#fb923c', markov: '#34d399', autoencoder: '#a855f7', gnn: '#ef4444' };
            const MODEL_SHORT  = { lstm: 'L', xgboost: 'X', cnn: 'C', transformer: 'T', markov: 'M', autoencoder: 'A', gnn: 'G' };
            const modelBar = MODEL_LIST.map(m => {
                const agree = nums.some(n => modelTop[m] && modelTop[m].has(n));
                return `<div style="width:4px;height:22px;border-radius:3px;background:${agree ? MODEL_COLORS[m] : '#F3F4F6'};" title="${MODEL_SHORT[m]}"></div>`;
            }).join('');

            // 배경: 1위는 아주 연한 인디고, 나머지 흰색
            const cardBg = rank === 1 ? 'background:linear-gradient(135deg,#F5F3FF 0%,#EEF2FF 100%)' : 'background:#FFFFFF';

            return `<div class="group relative border rounded-2xl overflow-hidden hover:shadow-lg transition-all duration-200" style="${cardBg};border-color:${rank === 1 ? '#C7D2FE' : '#F3F4F6'}">
                <div class="absolute left-0 top-0 bottom-0 w-1 transition-all duration-200" style="background:${accentColor}"></div>
                <div class="flex items-center gap-4 px-5 py-4">
                    <!-- 순위 -->
                    <span class="text-[28px] font-black w-10 text-center font-mono leading-none ${rankTextCls}">${String(rank).padStart(2, '0')}</span>

                    <!-- 볼 -->
                    <div class="flex gap-1.5">${ballsHtml}</div>

                    <!-- 우측 정보 -->
                    <div class="ml-auto flex items-center gap-5">
                        <!-- 모델 동의 바 -->
                        <div class="flex gap-0.5 items-end h-6">${modelBar}</div>

                        <!-- 점수 -->
                        <div class="text-right min-w-[52px]">
                            <div class="text-[9px] text-gray-400 font-medium uppercase tracking-wider">Score</div>
                            <div class="text-[18px] font-black leading-tight ${scorePct >= 0.8 ? 'text-indigo-600' : 'text-gray-600'}">${(score * 100).toFixed(0)}</div>
                        </div>
                    </div>
                </div>

                <!-- 스탯 바 -->
                <div class="flex items-center gap-3 px-5 pb-3 text-[10px] text-gray-400">
                    ${topIncluded.length > 0 ? `<span class="font-bold text-amber-500">★ Top${topIncluded.length}</span>` : ''}
                    <span>합 <b class="text-gray-600">${sum}</b></span>
                    <span>홀짝 <b class="text-gray-600">${odd}:${6 - odd}</b></span>
                    <span>AC <b class="text-gray-600">${ac}</b></span>
                    <span>저고 <b class="text-gray-600">${6 - high}:${high}</b></span>
                    ${isVerified ? '<span class="ml-auto text-emerald-500 font-bold flex items-center gap-0.5"><span class="material-symbols-outlined text-[12px]">verified</span>AI검증</span>' : ''}
                </div>
            </div>`;
        }).join('');
    },

    renderModelRanking(matrixData) {
        const container = document.getElementById('modelRankingContainer');
        if (!container || !matrixData || !matrixData.length) return;

        const MODEL_ORDER  = ['lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'];
        const MODEL_LABELS = { lstm: 'LSTM', xgboost: 'XGB', cnn: 'CNN', transformer: 'TF', markov: 'MKV', autoencoder: 'ATC', gnn: 'GNN' };
        const MODEL_COLORS = { lstm: '#6366F1', xgboost: '#3B82F6', cnn: '#EC4899', transformer: '#F97316', markov: '#10B981', autoencoder: '#8B5CF6', gnn: '#EF4444' };

        const self = this;

        // 번호 → 볼 HTML
        const _ball = (n) => {
            const cls = self.getBallColorClass(n);
            return `<span class="ball-common ${cls} inline-flex items-center justify-center flex-shrink-0" style="width:28px;height:28px;font-size:11px;font-weight:800">${n}</span>`;
        };

        // 앙상블: total 기준 내림차순
        const ensRanked = [...matrixData]
            .sort((a, b) => (b.total || 0) - (a.total || 0))
            .map(d => d.num);

        // 모델별: models[m].score 기준 내림차순
        const modelRanked = {};
        MODEL_ORDER.forEach(m => {
            modelRanked[m] = [...matrixData]
                .sort((a, b) => {
                    const sa = ((a.models || {})[m] || {}).score || 0;
                    const sb = ((b.models || {})[m] || {}).score || 0;
                    return sb - sa;
                })
                .map(d => d.num);
        });

        // 모델 목록 (앙상블 + 7개)
        const cols = [
            { label: '앙상블', color: '#1E293B', nums: ensRanked },
            ...MODEL_ORDER.map(m => ({ label: MODEL_LABELS[m], color: MODEL_COLORS[m], nums: modelRanked[m] }))
        ];

        // 헤더: 순위(고정) | 앙상블 | LSTM | XGB | CNN | TF | MKV | ATC | GNN
        const theadHtml = `<thead>
            <tr class="border-b-2 border-gray-200 bg-gray-50/80 sticky top-0">
                <th class="py-2 text-center text-[11px] font-bold text-gray-400 whitespace-nowrap" style="width:40px">순위</th>
                ${cols.map(c => `<th class="py-2 text-center text-[12px] font-black whitespace-nowrap" style="color:${c.color}">${c.label}</th>`).join('')}
            </tr>
        </thead>`;

        // 행: 1위~45위, 각 셀은 해당 순위의 번호
        const tbodyHtml = Array.from({ length: 45 }, (_, i) => {
            const rank = i + 1;
            const rankCls = rank <= 6 ? 'font-black text-indigo-600' : rank <= 15 ? 'font-bold text-gray-600' : 'font-medium text-gray-300';
            return `<tr class="border-b border-gray-100 last:border-0 hover:bg-indigo-50/20 transition-colors">
                <td class="py-1.5 text-center text-[12px] ${rankCls}">${rank}</td>
                ${cols.map(c => `<td class="py-1.5 text-center">${_ball(c.nums[i])}</td>`).join('')}
            </tr>`;
        }).join('');

        container.innerHTML = `
            <div class="card col-span-1 lg:col-span-2">
                <div class="card-header">
                    <span class="material-symbols-outlined icon text-indigo-500">format_list_numbered</span>
                    <h3>모델별 번호 순위 (1위 → 45위)</h3>
                    <span class="ml-auto text-[10px] bg-indigo-50 text-indigo-500 font-bold px-2 py-0.5 rounded-full whitespace-nowrap">열 = 모델, 행 = 순위</span>
                </div>
                <div class="card-body p-0">
                    <table class="w-full text-xs" style="border-collapse:collapse;table-layout:fixed">
                        ${theadHtml}
                        <tbody>${tbodyHtml}</tbody>
                    </table>
                </div>
            </div>`;
        container.style.display = 'block';
    },

    renderPipelineInfo(pipeline) {
        if (!pipeline) return;
        const condContainer = document.getElementById('modelConditionContainer');
        if (condContainer && pipeline.modelWeights) {
            const MODEL_COLORS = { lstm: '#818cf8', xgboost: '#60a5fa', cnn: '#f472b6', transformer: '#fb923c', markov: '#34d399', autoencoder: '#a855f7', gnn: '#ef4444' };
            const MODEL_LABELS = { lstm: 'LSTM', xgboost: 'XGBoost', cnn: 'CNN', transformer: 'Transformer', markov: 'Markov', autoencoder: 'Autoenc.', gnn: 'GNN' };
            const rawWeights = pipeline.modelWeights;
            const isXai = !!pipeline.isXaiMode;

            // XAI 모드: 각 모델 기여도 % 그대로 사용 (이미 0~100% 범위)
            // 가중치 모드: 합계로 정규화
            let displayValues;
            if (isXai) {
                // XAI 기여도는 번호당 합 ≈ 100% → 평균도 ≈ 100% → 그대로 사용
                displayValues = Object.keys(MODEL_LABELS).map(k => rawWeights[k] || 0);
            } else {
                const rawSum = Object.keys(MODEL_LABELS).reduce((s, k) => s + (rawWeights[k] || 0), 0);
                displayValues = Object.keys(MODEL_LABELS).map(k => rawSum > 0 ? (rawWeights[k] || 0) / rawSum * 100 : 0);
            }
            const maxVal = Math.max(...displayValues, 0.001);

            const barsHtml = Object.keys(MODEL_LABELS).map((name, i) => {
                const val   = displayValues[i];
                const pct   = val.toFixed(1);
                const barW  = (val / maxVal * 100).toFixed(1);
                const color = MODEL_COLORS[name] || '#9CA3AF';
                const isZero = val < 0.05;
                // GNN 균일예측: 기여도 0이지만 이유를 명시
                const isGnnUniform = isXai && pipeline.gnnUniform && name === 'gnn';
                const valLabel = isGnnUniform
                    ? `<span style="font-size:10px;color:#9CA3AF;font-weight:600">균일예측</span>`
                    : `<span style="width:44px;color:${isZero ? '#D1D5DB' : color};font-weight:800;text-align:right;flex-shrink:0">${pct}%</span>`;
                return `<div style="display:flex;align-items:center;gap:10px;font-size:12px">
                    <span style="width:80px;color:#4B5563;font-weight:700;text-align:right;flex-shrink:0">${MODEL_LABELS[name]}</span>
                    <div style="flex:1;height:10px;background:#F3F4F6;border-radius:99px;overflow:hidden">
                        <div style="width:${barW}%;height:100%;background:${(isZero || isGnnUniform) ? '#E5E7EB' : color};border-radius:99px;transition:width 0.8s ease"></div>
                    </div>
                    ${valLabel}
                </div>`;
            }).join('');

            // 제목·부제: XAI 모드이면 실데이터임을 명확히
            const top5Html = isXai && pipeline.top5Numbers?.length
                ? `<div style="margin-top:12px;padding-top:10px;border-top:1px solid #F3F4F6;font-size:11px;color:#9CA3AF">
                    추천 번호 기준 ·
                    ${pipeline.top5Numbers.slice(0,5).map(n => `<b style="color:#6366f1">${n}</b>`).join(' · ')}
                  </div>`
                : '';
            const taskBadge = pipeline.weightReasons
                ? `<div style="margin-top:10px;font-size:10px;color:#9CA3AF">${pipeline.weightReasons}</div>`
                : '';

            condContainer.innerHTML = `
                <div class="card">
                    <div class="card-header">
                        <span class="material-symbols-outlined icon" style="color:${isXai?'#6366f1':'#94a3b8'}">${isXai ? 'analytics' : 'neurology'}</span>
                        <h3>${isXai ? '모델별 XAI 기여도' : '모델 컨디션'}</h3>
                        <span class="ml-auto text-[10px] font-medium whitespace-nowrap px-2 py-1 rounded-lg"
                              style="background:${isXai?'#EEF2FF':'#F9FAFB'};color:${isXai?'#6366f1':'#9CA3AF'}">
                            ${isXai ? '추천번호 평균 XAI' : '가중치 자동 조정'}
                        </span>
                    </div>
                    <div class="card-body">
                        <div style="display:flex;flex-direction:column;gap:10px">${barsHtml}</div>
                        ${top5Html}${taskBadge}
                    </div>
                </div>`;
            condContainer.style.display = 'block';
        }
        const reportContainer = document.getElementById('aiReportContainer');
        if (reportContainer && pipeline.aiReport) {
            const reportId = 'aiReportBody_' + Date.now();
            const highlighted = pipeline.aiReport
                .replace(/(\d+(?:\.\d+)?%)/g, '<b style="color:#4F46E5">$1</b>')
                .replace(/(LSTM|XGBoost|CNN|Transformer|Markov|Autoencoder)/gi, '<b style="color:#0EA5E9">$1</b>')
                .replace(/(몬테카를로|강화학습|RL|GNN|Meta-Learning)/gi, '<b style="color:#8B5CF6">$1</b>')
                .replace(/(\d+(?:,\d+)*회)/g, '<b style="color:#F59E0B">$1</b>')
                .replace(/(\d{1,2}-\d{1,2})/g, '<b style="color:#10B981">$1</b>')
                .replace(/(높은|최고|우수)/g, '<b style="color:#10B981">$1</b>')
                .replace(/(낮은|부족|없어|미실행)/g, '<b style="color:#EF4444">$1</b>');
            reportContainer.innerHTML = `
                <div style="background:linear-gradient(135deg,#F8FAFC,#F1F5F9);border:1px solid #E2E8F0;border-radius:20px;overflow:hidden;margin-top:24px">
                    <div style="padding:16px 20px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #E2E8F0;cursor:pointer"
                         onclick="(function(){var b=document.getElementById('${reportId}');var arr=document.getElementById('${reportId}_arr');var open=b.style.display!=='none';b.style.display=open?'none':'block';arr.textContent=open?'펼치기 ▼':'접기 ▲'})()">
                        <span style="font-size:13px;font-weight:800;color:#1E293B;display:flex;align-items:center;gap:8px">
                            <span style="width:8px;height:8px;border-radius:50%;background:#4F46E5;display:inline-block;box-shadow:0 0 8px rgba(79, 70, 229, 0.4)"></span>
                            AI 종합 분석 리포트
                        </span>
                        <span id="${reportId}_arr" style="font-size:11px;color:#64748B;font-weight:600">접기 ▲</span>
                    </div>
                    <div id="${reportId}" style="display:block;padding:20px;font-size:13px;line-height:1.8;color:#334155">${highlighted}</div>
                </div>`;
            reportContainer.style.display = 'block';
        }
    },

    renderTailAnalysis(tailData) {
        const tbody = document.getElementById('tail-body');
        if (!tbody || !tailData) return;

        // deep_insight_panel.js와 동일한 확률→범위 변환 로직
        const _probToRange = (prob) => {
            if (prob < 0.3) return { min: 0, max: 1 };
            if (prob >= 1.8) return { min: 1, max: 3 };
            if (prob >= 1.2) return { min: 1, max: 2 };
            return { min: 0, max: 2 };
        };
        const MODEL_ORDER = ['lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'];
        const MODEL_ABBR = { lstm: 'LSTM', xgboost: 'XGB', cnn: 'CNN', transformer: 'TF', markov: 'MKV', autoencoder: 'ATC', gnn: 'GNN' };
        const MODEL_COLORS = {
            lstm: '#6366F1', xgboost: '#3B82F6', cnn: '#EC4899',
            transformer: '#F97316', markov: '#10B981', autoencoder: '#8B5CF6', gnn: '#EF4444'
        };

        tbody.innerHTML = tailData.map(item => {
            const exp = typeof item.exp === 'number' ? item.exp : 0;
            const str = item.str != null ? item.str : '-';

            // 앙상블 범위: model_exp에서 min/max 집계
            const modelRanges = {};
            if (item.model_exp) {
                MODEL_ORDER.forEach(m => {
                    const p = parseFloat(item.model_exp[m]) || 0;
                    modelRanges[m] = _probToRange(p);
                });
            }
            const allRanges = Object.values(modelRanges);
            const rMin = allRanges.length ? Math.min(...allRanges.map(r => r.min)) : _probToRange(exp).min;
            const rMax = allRanges.length ? Math.max(...allRanges.map(r => r.max)) : _probToRange(exp).max;

            const isHot = exp >= 1.2;
            const rangeColor = isHot ? '#0F766E' : exp < 0.3 ? '#9CA3AF' : '#374151';

            const ensembleCell = `
                <div class="flex flex-col items-center gap-0.5">
                    <span style="font-family:monospace;font-size:13px;font-weight:800;color:${rangeColor}">${rMin}~${rMax}개</span>
                    <span style="font-size:9px;color:#94A3B8">평균 ${exp.toFixed(1)}개</span>
                </div>`;

            const modelCells = MODEL_ORDER.map(m => {
                const r = modelRanges[m] || _probToRange(exp);
                const rangeLabel = r.min === r.max ? `${r.min}` : `${r.min}~${r.max}`;
                const color = MODEL_COLORS[m];
                return `<td class="px-2 py-3 text-center">
                    <span style="font-family:monospace;font-size:10px;font-weight:700;color:${color}">${rangeLabel}</span>
                </td>`;
            }).join('');

            return `<tr class="hover:bg-gray-50 border-b border-gray-100 last:border-0 transition-colors${isHot ? ' bg-emerald-50/40' : ''}">
                <td class="px-4 py-3 font-black text-center text-gray-800 text-base">${item.tail}끝</td>
                <td class="px-2 py-3 text-center">${ensembleCell}</td>
                ${modelCells}
                <td class="px-4 py-3 text-center font-mono text-xs text-gray-500">${item.gap ?? '-'}</td>
                <td class="px-4 py-3 text-center font-mono text-xs text-gray-500">${str}</td>
            </tr>`;
        }).join('');
    },

    renderLottoPaperAnalysis(paperData) {
        const container = document.getElementById('lottoPaperContainer');
        if (!container || !paperData) return;

        const _probToRange = (prob) => {
            if (prob < 0.3) return { min: 0, max: 1 };
            if (prob >= 1.8) return { min: 1, max: 3 };
            if (prob >= 1.2) return { min: 1, max: 2 };
            return { min: 0, max: 2 };
        };
        const MODEL_ORDER = ['lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'];
        const MODEL_ABBR = { lstm: 'LSTM', xgboost: 'XGB', cnn: 'CNN', transformer: 'TF', markov: 'MKV', autoencoder: 'ATC', gnn: 'GNN' };
        const MODEL_COLORS = {
            lstm: '#6366F1', xgboost: '#3B82F6', cnn: '#EC4899',
            transformer: '#F97316', markov: '#10B981', autoencoder: '#8B5CF6', gnn: '#EF4444'
        };

        const _modelHeader = () => MODEL_ORDER.map(m =>
            `<th class="px-2 py-3 text-center font-semibold" style="color:${MODEL_COLORS[m]}">${MODEL_ABBR[m]}</th>`
        ).join('');

        const _modelCells = (item) => {
            const exp = typeof item.exp === 'number' ? item.exp : 0;
            return MODEL_ORDER.map(m => {
                const p = item.model_exp ? (parseFloat(item.model_exp[m]) || 0) : exp;
                const r = _probToRange(p);
                const label = r.min === r.max ? `${r.min}` : `${r.min}~${r.max}`;
                return `<td class="px-2 py-3 text-center"><span style="font-family:monospace;font-size:10px;font-weight:700;color:${MODEL_COLORS[m]}">${label}</span></td>`;
            }).join('');
        };

        const buildTable = (title, items) => {
            let html = `<div class="mb-8">`;
            html += `<div class="flex items-center gap-2 mb-4 px-1"><span class="w-1 h-4 bg-gray-800 rounded-full"></span><span class="text-sm font-bold text-gray-800 uppercase tracking-wide">${title}</span></div>`;
            html += '<div class="overflow-x-auto rounded-2xl border border-gray-200 shadow-sm bg-white">';
            html += '<table class="w-full text-xs">';
            html += '<thead><tr class="bg-gray-50/50 border-b border-gray-200">';
            html += '<th class="px-4 py-3 text-left font-bold text-gray-700">구분</th>';
            html += '<th class="px-4 py-3 text-center font-bold text-blue-600">AI 종합</th>';
            html += _modelHeader();
            html += '<th class="px-4 py-3 text-center font-bold text-gray-600">Gap</th>';
            html += '<th class="px-4 py-3 text-center font-bold text-gray-600">STR</th>';
            html += '</tr></thead><tbody>';

            items.forEach(item => {
                const exp = typeof item.exp === 'number' ? item.exp : 0;
                const modelRanges = MODEL_ORDER.map(m => _probToRange(item.model_exp ? (parseFloat(item.model_exp[m]) || 0) : exp));
                const rMin = Math.min(...modelRanges.map(r => r.min));
                const rMax = Math.max(...modelRanges.map(r => r.max));
                const isHot = exp >= 1.2;
                const rangeColor = isHot ? '#0F766E' : exp < 0.3 ? '#9CA3AF' : '#374151';

                const ensembleCell = `<div class="flex flex-col items-center gap-0.5">
                    <span style="font-family:monospace;font-size:12px;font-weight:800;color:${rangeColor}">${rMin}~${rMax}개</span>
                    <span style="font-size:9px;color:#94A3B8">평균 ${exp.toFixed(1)}개</span>
                </div>`;

                html += `<tr class="border-b border-gray-100 last:border-0 hover:bg-gray-50 transition-colors${isHot ? ' bg-emerald-50/30' : ''}">`;
                html += `<td class="px-4 py-3 font-bold text-gray-700 text-sm">${item.label}</td>`;
                html += `<td class="px-4 py-3 text-center">${ensembleCell}</td>`;
                html += _modelCells(item);
                html += `<td class="px-4 py-3 text-center font-mono text-gray-500">${item.gap != null ? item.gap : '-'}</td>`;
                html += `<td class="px-4 py-3 text-center font-mono text-gray-500">${item.str != null ? item.str : '-'}</td>`;
                html += '</tr>';
            });
            html += '</tbody></table></div></div>';
            return html;
        };

        let html = '';
        if (paperData.rows) html += buildTable('가로 라인 분포', paperData.rows);
        if (paperData.cols) html += buildTable('세로 라인 분포', paperData.cols);
        container.innerHTML = html || '<p class="text-sm text-gray-400 text-center py-4">데이터 없음</p>';
    },

    renderNumberBandAnalysis(bandData) {
        const container = document.getElementById('numberBandContainer');
        if (!container || !bandData || !bandData.length) return;

        const _probToRange = (prob) => {
            if (prob < 0.3) return { min: 0, max: 1 };
            if (prob >= 1.8) return { min: 1, max: 3 };
            if (prob >= 1.2) return { min: 1, max: 2 };
            return { min: 0, max: 2 };
        };
        const BAND_LABEL_MAP = {
            '01~10': '단번대', '1~10': '단번대',
            '11~20': '10번대', '21~30': '20번대',
            '31~40': '30번대', '41~45': '40번대'
        };
        const MODEL_ORDER = ['lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'];
        const MODEL_ABBR = { lstm: 'LSTM', xgboost: 'XGB', cnn: 'CNN', transformer: 'TF', markov: 'MKV', autoencoder: 'ATC', gnn: 'GNN' };
        const MODEL_COLORS = {
            lstm: '#6366F1', xgboost: '#3B82F6', cnn: '#EC4899',
            transformer: '#F97316', markov: '#10B981', autoencoder: '#8B5CF6', gnn: '#EF4444'
        };

        let html = '<div class="overflow-x-auto rounded-2xl border border-gray-200 shadow-sm bg-white">';
        html += '<table class="w-full text-xs">';
        html += '<thead><tr class="bg-gray-50/50 border-b border-gray-200">';
        html += '<th class="px-4 py-3 text-left font-bold text-gray-700">번호대</th>';
        html += '<th class="px-4 py-3 text-center font-bold text-blue-600">AI 종합</th>';
        MODEL_ORDER.forEach(m => {
            html += `<th class="px-2 py-3 text-center font-semibold" style="color:${MODEL_COLORS[m]}">${MODEL_ABBR[m]}</th>`;
        });
        html += '<th class="px-4 py-3 text-center font-bold text-gray-600">Gap</th>';
        html += '<th class="px-4 py-3 text-center font-bold text-gray-600">STR</th>';
        html += '</tr></thead><tbody>';

        bandData.forEach(item => {
            const exp = typeof item.exp === 'number' ? item.exp : 0;
            const displayLabel = BAND_LABEL_MAP[item.label] || item.label;
            const modelRanges = MODEL_ORDER.map(m => _probToRange(item.model_exp ? (parseFloat(item.model_exp[m]) || 0) : exp));
            const rMin = Math.min(...modelRanges.map(r => r.min));
            const rMax = Math.max(...modelRanges.map(r => r.max));
            const isHot = exp >= 1.2;
            const rangeColor = isHot ? '#0F766E' : exp < 0.3 ? '#9CA3AF' : '#374151';

            const ensembleCell = `<div class="flex flex-col items-center gap-0.5">
                <span style="font-family:monospace;font-size:12px;font-weight:800;color:${rangeColor}">${rMin}~${rMax}개</span>
                <span style="font-size:9px;color:#94A3B8">평균 ${exp.toFixed(1)}개</span>
            </div>`;

            const modelCells = MODEL_ORDER.map((m, i) => {
                const r = modelRanges[i];
                const lbl = r.min === r.max ? `${r.min}` : `${r.min}~${r.max}`;
                return `<td class="px-2 py-3 text-center"><span style="font-family:monospace;font-size:10px;font-weight:700;color:${MODEL_COLORS[m]}">${lbl}</span></td>`;
            }).join('');

            html += `<tr class="border-b border-gray-100 last:border-0 hover:bg-gray-50 transition-colors${isHot ? ' bg-emerald-50/30' : ''}">`;
            html += `<td class="px-4 py-3 font-bold text-gray-700 text-sm">${displayLabel}</td>`;
            html += `<td class="px-4 py-3 text-center">${ensembleCell}</td>`;
            html += modelCells;
            html += `<td class="px-4 py-3 text-center font-mono text-gray-500">${item.gap != null ? item.gap : '-'}</td>`;
            html += `<td class="px-4 py-3 text-center font-mono text-gray-500">${item.str != null ? item.str : '-'}</td>`;
            html += '</tr>';
        });
        html += '</tbody></table></div>';
        container.innerHTML = html;
    },

    renderMagicSquareAnalysis(squareData) {
        const container = document.getElementById('magicSquareContainer');
        if (!container || !squareData || !squareData.length) return;

        const _probToRange = (prob) => {
            if (prob < 0.3) return { min: 0, max: 1 };
            if (prob >= 1.8) return { min: 1, max: 3 };
            if (prob >= 1.2) return { min: 1, max: 2 };
            return { min: 0, max: 2 };
        };
        const MODEL_ORDER = ['lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'];
        const MODEL_ABBR = { lstm: 'LSTM', xgboost: 'XGB', cnn: 'CNN', transformer: 'TF', markov: 'MKV', autoencoder: 'ATC', gnn: 'GNN' };
        const MODEL_COLORS = {
            lstm: '#6366F1', xgboost: '#3B82F6', cnn: '#EC4899',
            transformer: '#F97316', markov: '#10B981', autoencoder: '#8B5CF6', gnn: '#EF4444'
        };

        let html = '<div class="overflow-x-auto rounded-2xl border border-gray-200 shadow-sm bg-white">';
        html += '<table class="w-full text-xs">';
        html += '<thead><tr class="bg-gray-50/50 border-b border-gray-200">';
        html += '<th class="px-4 py-3 text-left font-bold text-gray-700">궁</th>';
        html += '<th class="px-4 py-3 text-center font-bold text-blue-600">AI 종합</th>';
        MODEL_ORDER.forEach(m => {
            html += `<th class="px-2 py-3 text-center font-semibold" style="color:${MODEL_COLORS[m]}">${MODEL_ABBR[m]}</th>`;
        });
        html += '<th class="px-4 py-3 text-center font-bold text-gray-600">Gap</th>';
        html += '<th class="px-4 py-3 text-center font-bold text-gray-600">STR</th>';
        html += '</tr></thead><tbody>';

        squareData.forEach(item => {
            const exp = typeof item.exp === 'number' ? item.exp : 0;
            const modelRanges = MODEL_ORDER.map(m => _probToRange(item.model_exp ? (parseFloat(item.model_exp[m]) || 0) : exp));
            const rMin = Math.min(...modelRanges.map(r => r.min));
            const rMax = Math.max(...modelRanges.map(r => r.max));
            const isHot = exp >= 1.2;
            const rangeColor = isHot ? '#0F766E' : exp < 0.3 ? '#9CA3AF' : '#374151';

            const ensembleCell = `<div class="flex flex-col items-center gap-0.5">
                <span style="font-family:monospace;font-size:12px;font-weight:800;color:${rangeColor}">${rMin}~${rMax}개</span>
                <span style="font-size:9px;color:#94A3B8">평균 ${exp.toFixed(1)}개</span>
            </div>`;

            const modelCells = MODEL_ORDER.map((m, i) => {
                const r = modelRanges[i];
                const label = r.min === r.max ? `${r.min}` : `${r.min}~${r.max}`;
                return `<td class="px-2 py-3 text-center"><span style="font-family:monospace;font-size:10px;font-weight:700;color:${MODEL_COLORS[m]}">${label}</span></td>`;
            }).join('');

            html += `<tr class="border-b border-gray-100 last:border-0 hover:bg-gray-50 transition-colors${isHot ? ' bg-emerald-50/30' : ''}">`;
            html += `<td class="px-4 py-3 font-bold text-gray-700 text-sm">${item.label}</td>`;
            html += `<td class="px-4 py-3 text-center">${ensembleCell}</td>`;
            html += modelCells;
            html += `<td class="px-4 py-3 text-center font-mono text-gray-500">${item.gap != null ? item.gap : '-'}</td>`;
            html += `<td class="px-4 py-3 text-center font-mono text-gray-500">${item.str != null ? item.str : '-'}</td>`;
            html += '</tr>';
        });
        html += '</tbody></table></div>';
        container.innerHTML = html;
    },

    renderMissingGroupAnalysis(groupData) {
        const container = document.getElementById('missingGroupContainer');
        if (!container || !groupData) return;

        const rawGroups = groupData.groups || groupData;
        const groupArray = Array.isArray(rawGroups) ? rawGroups : Object.values(rawGroups);
        if (!groupArray.length) return;

        const MODEL_ORDER = ['lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'];
        const MODEL_ABBR = { lstm: 'LSTM', xgboost: 'XGB', cnn: 'CNN', transformer: 'TF', markov: 'MKV', autoencoder: 'ATC', gnn: 'GNN' };
        const MODEL_COLORS = {
            lstm: '#6366F1', xgboost: '#3B82F6', cnn: '#EC4899',
            transformer: '#F97316', markov: '#10B981', autoencoder: '#8B5CF6', gnn: '#EF4444'
        };
        const _expToRange = (exp) => {
            if (exp < 0.5) return { min: 0, max: 1 };
            if (exp >= 2.0) return { min: 1, max: 3 };
            if (exp >= 1.2) return { min: 1, max: 2 };
            return { min: 0, max: 2 };
        };

        let html = '<div class="overflow-x-auto rounded-2xl border border-gray-200 shadow-sm bg-white">';
        html += '<table class="w-full text-xs">';
        html += '<thead><tr class="bg-gray-50/50 border-b border-gray-200">';
        html += '<th class="px-4 py-3 text-left font-bold text-gray-700">미출현 구간</th>';
        html += '<th class="px-4 py-3 text-center font-bold text-blue-600">AI 종합</th>';
        MODEL_ORDER.forEach(m => {
            html += `<th class="px-2 py-3 text-center font-semibold" style="color:${MODEL_COLORS[m]}">${MODEL_ABBR[m]}</th>`;
        });
        html += '<th class="px-4 py-3 text-center font-bold text-gray-600">번호수</th>';
        html += '<th class="px-4 py-3 text-left font-bold text-gray-600">추천 번호 (상위15)</th>';
        html += '</tr></thead><tbody>';

        groupArray.forEach(g => {
            const expected = (g.count || 0) * (g.avg_prob || 0) / 100 * 6;
            const r = _expToRange(expected);
            const isHot = expected >= 1.2;
            const rangeColor = isHot ? '#0F766E' : expected < 0.5 ? '#9CA3AF' : '#374151';

            const ensembleCell = `<div class="flex flex-col items-center gap-0.5">
                <span style="font-family:monospace;font-size:12px;font-weight:800;color:${rangeColor}">${r.min}~${r.max}개</span>
                <span style="font-size:9px;color:#94A3B8">평균 ${expected.toFixed(1)}개</span>
            </div>`;

            // 모델별 — model_exp 있으면 범위값, 없으면 '-'
            const modelCells = MODEL_ORDER.map(m => {
                const color = MODEL_COLORS[m];
                if (!g.model_exp || g.model_exp[m] == null) {
                    return `<td class="px-2 py-3 text-center"><span style="color:#D1D5DB;font-size:10px">-</span></td>`;
                }
                const mExp = parseFloat(g.model_exp[m]);
                const mr = _expToRange(mExp);
                const lbl = mr.min === mr.max ? `${mr.min}` : `${mr.min}~${mr.max}`;
                return `<td class="px-2 py-3 text-center"><span style="font-family:monospace;font-size:10px;font-weight:700;color:${color}">${lbl}</span></td>`;
            }).join('');

            const top15Nums = (g.numbers || []).filter(n => n.is_top15).map(n => n.num).slice(0, 10);
            const ballsHtml = top15Nums.map(n =>
                `<span class="inline-flex items-center justify-center w-6 h-6 rounded-full text-[10px] font-bold text-white mx-0.5" style="background:${g.color || '#6366f1'}">${n}</span>`
            ).join('') || '<span class="text-gray-400">-</span>';

            html += `<tr class="border-b border-gray-100 last:border-0 hover:bg-gray-50 transition-colors${isHot ? ' bg-emerald-50/30' : ''}">`;
            html += `<td class="px-4 py-3 font-bold text-sm" style="color:${g.color || '#374151'}">${g.label || '-'}</td>`;
            html += `<td class="px-4 py-3 text-center">${ensembleCell}</td>`;
            html += modelCells;
            html += `<td class="px-4 py-3 text-center font-mono text-gray-500">${g.count || 0}</td>`;
            html += `<td class="px-4 py-3">${ballsHtml}</td>`;
            html += '</tr>';
        });
        html += '</tbody></table></div>';
        container.innerHTML = html;
    },

    async renderHotColdAnalysis(hotColdData) {
        const container = document.getElementById('hotColdContainer');
        if (!container || !hotColdData) return;

        const MODEL_ORDER = ['lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'];
        const MODEL_ABBR = { lstm: 'LSTM', xgboost: 'XGB', cnn: 'CNN', transformer: 'TF', markov: 'MKV', autoencoder: 'ATC', gnn: 'GNN' };
        const MODEL_COLORS = {
            lstm: '#6366F1', xgboost: '#3B82F6', cnn: '#EC4899',
            transformer: '#F97316', markov: '#10B981', autoencoder: '#8B5CF6', gnn: '#EF4444'
        };
        const STATUS_ORDER = ['hot', 'active', 'cooling', 'cold', 'deadcold'];
        const STATUS_META = {
            hot:      { label: '🔥 핫',    sub: 'Gap 0~2',   color: '#EF4444' },
            active:   { label: '✅ 활성',   sub: 'Gap 3~7',   color: '#F97316' },
            cooling:  { label: '🌡️ 쿨링',  sub: 'Gap 8~15',  color: '#3B82F6' },
            cold:     { label: '❄️ 콜드',   sub: 'Gap 16~25', color: '#6366F1' },
            deadcold: { label: '🧊 극콜드', sub: 'Gap 26+',   color: '#94A3B8' },
        };
        const PERIOD_OPTIONS = [5, 10, 15, 20];
        // hot_cold.html과 동일한 출현 횟수 기준 분류
        const HC_CRITERIA = {
            5:  { hot: 2, coldMax: 0, hotLabel: '2~5회',  neutralLabel: '1회',   coldLabel: '0회' },
            10: { hot: 3, coldMax: 0, hotLabel: '3~10회', neutralLabel: '1~2회', coldLabel: '0회' },
            15: { hot: 4, coldMax: 1, hotLabel: '4~15회', neutralLabel: '2~3회', coldLabel: '0~1회' },
            20: { hot: 5, coldMax: 1, hotLabel: '5~20회', neutralLabel: '2~4회', coldLabel: '0~1회' },
        };

        const _expToRange = (exp) => {
            if (exp < 0.5) return { min: 0, max: 1 };
            if (exp >= 2.0) return { min: 1, max: 3 };
            if (exp >= 1.2) return { min: 1, max: 2 };
            return { min: 0, max: 2 };
        };

        // 전체 num_details 수집
        const allNums = [];
        STATUS_ORDER.forEach(s => {
            const d = hotColdData[s];
            if (d && Array.isArray(d.num_details)) allNums.push(...d.num_details);
        });

        // 최근 당첨 결과 로드 (출현 횟수 계산용)
        if (!this._drawsCache) {
            const { data } = await window.supabaseClient
                .from('lotto_draws')
                .select('round, numbers')
                .order('round', { ascending: false })
                .limit(20);
            this._drawsCache = data || [];
        }
        const recentDraws = this._drawsCache;

        const _buildPeriodTable = (n) => {
            const crit = HC_CRITERIA[n];
            // 최근 N회 출현 횟수 계산 (hot_cold.html과 동일 로직)
            const periodDraws = recentDraws.slice(0, n);
            const countMap = {};
            for (let num = 1; num <= 45; num++) {
                let cnt = 0;
                periodDraws.forEach(draw => { if ((draw.numbers || []).includes(num)) cnt++; });
                countMap[num] = cnt;
            }
            // 출현 횟수 기준 분류
            const hot     = allNums.filter(d => countMap[d.num] >= crit.hot);
            const neutral = allNums.filter(d => countMap[d.num] > crit.coldMax && countMap[d.num] < crit.hot);
            const cold    = allNums.filter(d => countMap[d.num] <= crit.coldMax);
            const hotRange     = `당첨횟수: ${crit.hotLabel}`;
            const neutralRange = `당첨횟수: ${crit.neutralLabel}`;
            const coldRange    = `당첨횟수: ${crit.coldLabel}`;

            const _rowHtml = (icon, label, rangeLabel, color, bgClass, nums) => {
                if (!nums.length) return `<tr class="border-b border-gray-100"><td class="px-4 py-3 font-bold text-sm" style="color:${color}">${icon} ${label}</td><td colspan="${MODEL_ORDER.length + 3}" class="px-4 py-3 text-center text-gray-400 text-xs">해당 번호 없음</td></tr>`;

                const ensExp = nums.reduce((s, d) => s + (d.ensemble_prob || 0) / 100, 0) * 6;
                const r = _expToRange(ensExp);
                const rangeColor = ensExp >= 1.2 ? '#0F766E' : ensExp < 0.5 ? '#9CA3AF' : '#374151';

                const ensCell = `<div class="flex flex-col items-center gap-0.5">
                    <span style="font-family:monospace;font-size:12px;font-weight:800;color:${rangeColor}">${r.min}~${r.max}개</span>
                    <span style="font-size:9px;color:#94A3B8">평균 ${ensExp.toFixed(1)}개</span>
                </div>`;

                const modelCells = MODEL_ORDER.map(m => {
                    const mExp = nums.reduce((s, d) => {
                        const p = (d.models && d.models[m]) ? (d.models[m].prob || 0) : 0;
                        return s + p / 100;
                    }, 0) * 6;
                    const mr = _expToRange(mExp);
                    const lbl = mr.min === mr.max ? `${mr.min}` : `${mr.min}~${mr.max}`;
                    return `<td class="px-2 py-3 text-center"><span style="font-family:monospace;font-size:10px;font-weight:700;color:${MODEL_COLORS[m]}">${lbl}</span></td>`;
                }).join('');

                const topBalls = nums.filter(d => d.is_top15).sort((a, b) => (b.ensemble_prob||0)-(a.ensemble_prob||0)).slice(0, 8);
                const ballsHtml = topBalls.map(d =>
                    `<span class="inline-flex items-center justify-center w-6 h-6 rounded-full text-[10px] font-bold text-white mx-0.5" style="background:${color}">${d.num}</span>`
                ).join('') || '<span class="text-gray-400 text-xs">-</span>';

                return `<tr class="border-b border-gray-100 last:border-0 hover:bg-gray-50 transition-colors${bgClass ? ' ' + bgClass : ''}">
                    <td class="px-4 py-3 text-sm">
                        <div class="font-bold" style="color:${color}">${icon} ${label}</div>
                        <div style="font-size:10px;color:#94A3B8">${rangeLabel} · 대상수: ${nums.length}개</div>
                    </td>
                    <td class="px-4 py-3 text-center">${ensCell}</td>
                    ${modelCells}
                    <td class="px-4 py-3 text-center font-mono text-gray-500">${nums.length}</td>
                    <td class="px-4 py-3">${ballsHtml}</td>
                </tr>`;
            };

            let t = '<div class="overflow-x-auto rounded-2xl border border-gray-200 shadow-sm bg-white">';
            t += '<table class="w-full text-xs">';
            t += '<thead><tr class="bg-gray-50/50 border-b border-gray-200">';
            t += '<th class="px-4 py-3 text-left font-bold text-gray-700">구분</th>';
            t += '<th class="px-4 py-3 text-center font-bold text-blue-600">AI 종합</th>';
            MODEL_ORDER.forEach(m => { t += `<th class="px-2 py-3 text-center font-semibold" style="color:${MODEL_COLORS[m]}">${MODEL_ABBR[m]}</th>`; });
            t += '<th class="px-4 py-3 text-center font-bold text-gray-600">번호수</th>';
            t += '<th class="px-4 py-3 text-left font-bold text-gray-600">추천 번호 (상위15)</th>';
            t += '</tr></thead><tbody>';
            t += _rowHtml('🔥', '핫', hotRange,     '#EF4444', 'bg-red-50/20',    hot);
            t += _rowHtml('🌡️', '중립', neutralRange, '#F97316', 'bg-orange-50/20', neutral);
            t += _rowHtml('❄️', '콜드', coldRange,    '#6366F1', '',               cold);
            t += '</tbody></table></div>';
            return t;
        };

        // 기준 회차 탭 + 상태 기반 테이블 (num_details 없을 때 fallback)
        const useNumDetails = allNums.length > 0;
        const uid = `hc_${Date.now()}`;

        let html = '';

        // 기준 회차 선택 탭
        html += `<div class="flex gap-1.5 mb-3 flex-wrap" id="${uid}_tabs">`;
        PERIOD_OPTIONS.forEach((n, i) => {
            const active = i === 0 ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200';
            html += `<button onclick="window._hcSelectPeriod('${uid}',${n})" id="${uid}_tab_${n}"
                class="px-3 py-1 rounded-full text-xs font-bold transition-colors ${active}">${n}회차 기준</button>`;
        });
        html += '</div>';

        // 콘텐츠 영역
        if (useNumDetails) {
            PERIOD_OPTIONS.forEach((n, i) => {
                html += `<div id="${uid}_content_${n}" style="display:${i===0?'block':'none'}">${_buildPeriodTable(n)}</div>`;
            });
        } else {
            // num_details 없는 구형 데이터: status 기반 fallback
            html += '<div class="overflow-x-auto rounded-2xl border border-gray-200 shadow-sm bg-white">';
            html += '<table class="w-full text-xs"><thead><tr class="bg-gray-50/50 border-b border-gray-200">';
            html += '<th class="px-4 py-3 text-left font-bold text-gray-700">온도</th>';
            html += '<th class="px-4 py-3 text-center font-bold text-blue-600">AI 종합</th>';
            MODEL_ORDER.forEach(m => { html += `<th class="px-2 py-3 text-center font-semibold" style="color:${MODEL_COLORS[m]}">${MODEL_ABBR[m]}</th>`; });
            html += '<th class="px-4 py-3 text-center font-bold text-gray-600">번호수</th>';
            html += '<th class="px-4 py-3 text-center font-bold text-gray-600">평균Gap</th>';
            html += '</tr></thead><tbody>';
            STATUS_ORDER.forEach(status => {
                const d = hotColdData[status];
                if (!d) return;
                const meta = STATUS_META[status];
                const expected = (d.count || 0) * (d.avg_prob || 0) * 6;
                const r = _expToRange(expected);
                const rangeColor = expected >= 1.2 ? '#0F766E' : expected < 0.5 ? '#9CA3AF' : '#374151';
                const ensCell = `<div class="flex flex-col items-center gap-0.5">
                    <span style="font-family:monospace;font-size:12px;font-weight:800;color:${rangeColor}">${r.min}~${r.max}개</span>
                    <span style="font-size:9px;color:#94A3B8">평균 ${expected.toFixed(1)}개</span>
                </div>`;
                const modelCells = MODEL_ORDER.map(m => {
                    const sig = ((d.model_scores || {})[m] || {}).signal || 'neutral';
                    const lbl = sig === 'positive' ? '1~2' : sig === 'negative' ? '0~1' : '0~2';
                    return `<td class="px-2 py-3 text-center"><span style="font-family:monospace;font-size:10px;font-weight:700;color:${MODEL_COLORS[m]}">${lbl}</span></td>`;
                }).join('');
                html += `<tr class="border-b border-gray-100 last:border-0 hover:bg-gray-50 transition-colors">
                    <td class="px-4 py-3 text-sm"><div class="font-bold" style="color:${meta.color}">${meta.label}</div><div style="font-size:10px;color:#94A3B8">${meta.sub}</div></td>
                    <td class="px-4 py-3 text-center">${ensCell}</td>${modelCells}
                    <td class="px-4 py-3 text-center font-mono text-gray-500">${d.count||0}</td>
                    <td class="px-4 py-3 text-center font-mono text-gray-500">${d.avg_gap!=null?d.avg_gap.toFixed(1):'-'}</td>
                </tr>`;
            });
            html += '</tbody></table></div>';
        }

        container.innerHTML = html;

        // 탭 전환 함수 (전역 등록)
        window._hcSelectPeriod = (uid, n) => {
            PERIOD_OPTIONS.forEach(p => {
                const tab = document.getElementById(`${uid}_tab_${p}`);
                const content = document.getElementById(`${uid}_content_${p}`);
                if (!tab || !content) return;
                if (p === n) {
                    tab.className = tab.className.replace('bg-gray-100 text-gray-600 hover:bg-gray-200', 'bg-blue-600 text-white');
                    content.style.display = 'block';
                } else {
                    tab.className = tab.className.replace('bg-blue-600 text-white', 'bg-gray-100 text-gray-600 hover:bg-gray-200');
                    content.style.display = 'none';
                }
            });
        };
    },

    renderRegressionAnalysis(data) {
        const tbody = document.getElementById('reg-body');
        if (!tbody || !data) return;

        // 원본 데이터 저장 (enriched 데이터 우선 저장)
        const isEnriched = data.some(d => d.model_exp || d.notable);
        if (!this._regressionData || isEnriched) this._regressionData = data;

        let displayData = [...data];
        const sort = this.state.regressionSort;

        // 정렬 화살표 초기화
        ['id', 'gap', 'avg_hit'].forEach(f => {
            const arrow = document.getElementById('reg-sort-arrow-' + f);
            if (arrow) arrow.textContent = '';
        });
        const currentArrow = document.getElementById('reg-sort-arrow-' + sort.field);
        if (currentArrow) currentArrow.textContent = sort.asc ? '▲' : '▼';

        // 데이터 정렬
        displayData.sort((a, b) => {
            let v1 = a[sort.field];
            let v2 = b[sort.field];
            if (sort.field === 'id') {
                v1 = parseInt(v1);
                v2 = parseInt(v2);
            }
            if (v1 < v2) return sort.asc ? -1 : 1;
            if (v1 > v2) return sort.asc ? 1 : -1;
            return 0;
        });

        const MODEL_COLORS = { lstm: '#818cf8', xgboost: '#60a5fa', cnn: '#f472b6', transformer: '#fb923c', markov: '#34d399', autoencoder: '#a855f7', gnn: '#ef4444' };
        const MODEL_LABELS = { lstm: 'LSTM', xgboost: 'XGB', cnn: 'CNN', transformer: 'TF', markov: 'MKV', autoencoder: 'ATC', gnn: 'GNN' };
        const MODEL_ORDER = ['lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'];

        tbody.innerHTML = displayData.map(item => {
            const targetsHtml = (item.targets || []).map(n => {
                const colorClass = this.getBallColorClass(n);
                return `<span class="ball-common ${colorClass} w-7 h-7 text-xs">${n}</span>`;
            }).join('');

            // GAP/STR 뱃지 (필터페이지 동일 스타일)
            const gapStrHtml = (() => {
                if (item.gap > 0) {
                    const gCls = item.gap >= 4
                        ? 'text-rose-600 bg-rose-50 ring-1 ring-rose-200'
                        : 'text-amber-600 bg-amber-50 ring-1 ring-amber-200';
                    return `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-black ${gCls}" style="white-space:nowrap">GAP ${item.gap}미출</span>`;
                } else if (item.str > 0) {
                    const sCls = item.str >= 5
                        ? 'text-emerald-700 bg-emerald-100 ring-1 ring-emerald-300'
                        : 'text-emerald-600 bg-emerald-50 ring-1 ring-emerald-200';
                    return `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-black ${sCls}" style="white-space:nowrap">STR ${item.str}연속</span>`;
                }
                return '<span class="text-gray-300 text-xs">-</span>';
            })();

            // 특이사항 뱃지
            const notableHtml = (() => {
                const notable = item.notable || [];
                if (!notable.length) return '<span class="text-gray-300 text-xs">-</span>';
                const parts = [...notable].sort((a, b) => b.count - a.count)
                    .map(x => `<b>${x.num}번</b> ${x.count}회`).join(' · ');
                return `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-black text-violet-600 bg-violet-50 ring-1 ring-violet-200"><span class="opacity-70">특이</span> ${parts}</span>`;
            })();

            // 공통 _expToRange
            const _expToRange = (exp) => {
                if (exp < 0.5) return { min: 0, max: 1 };
                if (exp >= 2.0) return { min: 1, max: 3 };
                if (exp >= 1.2) return { min: 1, max: 2 };
                return { min: 0, max: 2 };
            };

            // AI 종합 셀
            const ensExp = item.ensemble_exp;
            const ensCell = (() => {
                if (ensExp == null) return `<td class="px-3 py-3 text-center"><span style="color:#D1D5DB;font-size:10px">-</span></td>`;
                const r = _expToRange(ensExp);
                const rangeColor = ensExp >= 1.2 ? '#0F766E' : ensExp < 0.5 ? '#9CA3AF' : '#374151';
                return `<td class="px-3 py-3 text-center">
                    <div class="flex flex-col items-center gap-0.5">
                        <span style="font-family:monospace;font-size:12px;font-weight:800;color:${rangeColor}">${r.min}~${r.max}개</span>
                        <span style="font-size:9px;color:#94A3B8">기대 ${ensExp.toFixed(1)}개</span>
                    </div>
                </td>`;
            })();

            // 모델별 기대값 컬럼
            const modelCells = MODEL_ORDER.map(m => {
                const mExp = (item.model_exp && item.model_exp[m] != null) ? parseFloat(item.model_exp[m]) : null;
                const color = MODEL_COLORS[m];
                if (mExp === null) return `<td class="px-2 py-3 text-center"><span style="color:#D1D5DB;font-size:10px">-</span></td>`;
                const mr = _expToRange(mExp);
                const lbl = mr.min === mr.max ? `${mr.min}` : `${mr.min}~${mr.max}`;
                return `<td class="px-2 py-3 text-center"><span style="font-family:monospace;font-size:11px;font-weight:800;color:${color}">${lbl}</span></td>`;
            }).join('');

            return `<tr class="hover:bg-gray-50 transition-colors">
                <td class="px-3 py-3 font-bold text-gray-800">${item.id}회귀</td>
                <td class="px-3 py-3"><div class="flex gap-1 justify-center">${targetsHtml}</div></td>
                <td class="px-3 py-3 text-center">${gapStrHtml}</td>
                <td class="px-3 py-3 text-center">${notableHtml}</td>
                <td class="px-3 py-3 font-mono text-center text-gray-500">${item.avg_hit != null ? item.avg_hit.toFixed(2) : '-'}</td>
                ${ensCell}
                ${modelCells}
            </tr>`;
        }).join('');
    },

    // ── hot_cold num_details에서 번호별 모델 확률 + 앙상블 확률 캐시 구축 ──
    _buildNumModelProbs(hotColdData) {
        this._numModelProbs   = {};
        this._modelTotals     = {};
        this._numEnsembleProbs = {};   // {num: ensembleProb(%)}
        this._ensembleTotal   = 0;
        if (!hotColdData) return;
        ['hot', 'active', 'cooling', 'cold', 'deadcold'].forEach(s => {
            const d = hotColdData[s];
            if (!d || !Array.isArray(d.num_details)) return;
            d.num_details.forEach(nd => {
                this._numModelProbs[nd.num] = {};
                Object.entries(nd.models || {}).forEach(([m, mv]) => {
                    const p = mv.prob || 0;
                    this._numModelProbs[nd.num][m] = p;
                    this._modelTotals[m] = (this._modelTotals[m] || 0) + p;
                });
                // 앙상블 확률 (ensemble_prob = final_prob * 100)
                const ep = nd.ensemble_prob || 0;
                this._numEnsembleProbs[nd.num] = ep;
                this._ensembleTotal += ep;
            });
        });
    },

    // ── 번호 목록 → 모델별 기대값 계산 ──
    _computeModelExpFromNumProbs(nums) {
        const MODELS = ['lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'];
        const exp = {};
        MODELS.forEach(m => {
            const total = this._modelTotals[m] || 1;
            const groupSum = nums.reduce((s, n) => s + ((this._numModelProbs[n] || {})[m] || 0), 0);
            exp[m] = parseFloat((groupSum / total * 6).toFixed(3));
        });
        return exp;
    },

    // ── 번호 목록 → 앙상블 기대값 계산 ──
    _computeEnsembleExp(nums) {
        const total = this._ensembleTotal || 100;
        const sum = nums.reduce((s, n) => s + (this._numEnsembleProbs[n] || 0), 0);
        return parseFloat((sum / total * 6).toFixed(3));
    },

    // ── 미출현 그룹 model_exp 보강 ──
    _enrichMissingGroupData(groupData) {
        if (!this._numModelProbs || !Object.keys(this._numModelProbs).length) return;
        const rawGroups = groupData.groups || groupData;
        const groups = Array.isArray(rawGroups) ? rawGroups : Object.values(rawGroups);
        groups.forEach(g => {
            if (!g.model_exp || !Object.keys(g.model_exp).length) {
                const nums = (g.numbers || []).map(x => x.num);
                if (nums.length) g.model_exp = this._computeModelExpFromNumProbs(nums);
            }
        });
    },

    // ── 커스텀 분석 model_exp + ensemble_exp 보강 ──
    _enrichCustomEvaluations(customData) {
        if (!this._numModelProbs || !Object.keys(this._numModelProbs).length) return;
        (customData || []).forEach(grp => {
            const nums = grp.targets || [];
            if (!nums.length) return;
            if (!grp.model_exp || !Object.keys(grp.model_exp).length)
                grp.model_exp = this._computeModelExpFromNumProbs(nums);
            if (grp.ensemble_exp == null)
                grp.ensemble_exp = this._computeEnsembleExp(nums);
        });
    },

    // ── 회귀분석 데이터 보강 (notable + model_exp fallback) ──
    async _loadAndEnrichRegression(regressionData) {
        try {
            // draws 캐시 로드 (1회만)
            if (!this._drawsCache) {
                const { data } = await window.supabaseClient
                    .from('lotto_draws')
                    .select('round, numbers')
                    .order('round', { ascending: false })
                    .limit(500);
                this._drawsCache = data || [];
            }
            const draws = this._drawsCache;

            return regressionData.map(item => {
                const w = item.id;
                const targetNums = item.targets || [];

                // ── notable: 저장 데이터에 없으면 프론트에서 직접 계산 ──
                let notable = item.notable;
                if (!notable) {
                    notable = [];
                    for (const n of targetNums) {
                        let consec = 1;
                        for (let k = 2; k <= 5; k++) {
                            const idx = k * w - 1;
                            if (idx < draws.length && (draws[idx].numbers || []).includes(n)) {
                                consec++;
                            } else break;
                        }
                        if (consec >= 3) notable.push({ num: n, count: consec });
                    }
                }

                // ── model_exp: 3단계 fallback ──
                // 1) 저장된 model_exp  2) model_scores 변환  3) hot_cold num_details 확률
                let model_exp = (item.model_exp && Object.keys(item.model_exp).length) ? item.model_exp : null;
                if (!model_exp && item.model_scores && Object.keys(item.model_scores).length) {
                    const tLen = targetNums.length || 6;
                    model_exp = {};
                    Object.entries(item.model_scores).forEach(([m, v]) => {
                        model_exp[m] = parseFloat(((v.score || 0) / 100 * tLen).toFixed(3));
                    });
                }
                if (!model_exp && this._numModelProbs && Object.keys(this._numModelProbs).length) {
                    model_exp = this._computeModelExpFromNumProbs(targetNums);
                }

                // ── ensemble_exp: hot_cold 앙상블 확률 기반 ──
                const ensemble_exp = (item.ensemble_exp != null)
                    ? item.ensemble_exp
                    : (this._numEnsembleProbs ? this._computeEnsembleExp(targetNums) : null);

                return { ...item, notable, model_exp, ensemble_exp };
            });
        } catch (e) {
            console.warn('[DeepLearning] 회귀분석 보강 실패:', e);
            return regressionData;
        }
    },

    _regSort(field) {
        if (this.state.regressionSort.field === field) {
            this.state.regressionSort.asc = !this.state.regressionSort.asc;
        } else {
            this.state.regressionSort.field = field;
            this.state.regressionSort.asc = true;
        }

        const data = this.state.analysisData
            ? (this.state.analysisData.analysis?.regression_analysis || this.state.analysisData.regression_analysis)
            : this._regressionData;
        if (data) {
            this.renderRegressionAnalysis(data);
        }
    },

    renderCustomEvaluations(customData) {
        const container = document.getElementById('custom-container');
        if (!container || !customData) return;
        const self = this;
        const MODEL_COLORS = { lstm: '#818cf8', xgboost: '#60a5fa', cnn: '#f472b6', transformer: '#fb923c', markov: '#34d399', autoencoder: '#a855f7', gnn: '#ef4444' };
        const MODEL_LABELS = { lstm: 'LSTM', xgboost: 'XGB', cnn: 'CNN', transformer: 'TF', markov: 'MKV', autoencoder: 'ATC', gnn: 'GNN' };
        const MODEL_ORDER = ['lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'];

        if (!customData || customData.length === 0) {
            container.innerHTML = '<p class="text-sm text-slate-400 py-8 text-center">커스텀 분석 데이터가 없습니다.</p>';
            return;
        }

        const TYPE_MAP  = { static: '고정', dynamic: '동적', manual: '매뉴얼', group: '그룹', regression_overlap: '회귀중첩' };
        const TYPE_COLOR = { static: '#6366F1', dynamic: '#10B981', manual: '#F97316', group: '#3B82F6', regression_overlap: '#EC4899' };

        const _expToRange = (exp) => {
            if (exp < 0.5)  return { min: 0, max: 1 };
            if (exp >= 2.0) return { min: 1, max: 3 };
            if (exp >= 1.2) return { min: 1, max: 2 };
            return { min: 0, max: 2 };
        };

        // 테이블 헤더
        let html = '<div class="rounded-2xl border border-gray-200 shadow-sm bg-white overflow-x-auto">';
        html += '<table class="w-full text-xs">';
        html += '<thead><tr class="bg-gray-50/50 border-b border-gray-200">';
        html += '<th class="px-4 py-3 text-left font-bold text-gray-700" style="min-width:140px">분석명</th>';
        html += '<th class="px-4 py-3 text-left font-bold text-gray-700" style="min-width:220px">대상번호</th>';
        html += '<th class="px-3 py-3 text-center font-bold text-gray-700" style="white-space:nowrap;min-width:90px">GAP/STR</th>';
        html += '<th class="px-3 py-3 text-center font-bold text-gray-500" style="white-space:nowrap;min-width:60px">과거평균</th>';
        html += '<th class="px-3 py-3 text-center font-bold text-blue-600" style="white-space:nowrap;min-width:80px">AI 종합</th>';
        MODEL_ORDER.forEach(m => {
            html += `<th class="px-2 py-3 text-center font-semibold" style="color:${MODEL_COLORS[m]};white-space:nowrap;min-width:40px">${MODEL_LABELS[m]}</th>`;
        });
        html += '</tr></thead><tbody>';

        customData.forEach(grp => {
            const gap    = grp.gap ?? 0;
            const str    = grp.str ?? 0;
            const avgHit = grp.avg_hit != null ? parseFloat(grp.avg_hit).toFixed(2) : '-';

            const typeLbl   = TYPE_MAP[grp.type]  || grp.type || '';
            const typeColor = TYPE_COLOR[grp.type] || '#6366F1';

            // GAP/STR 배지
            const gapStrHtml = (() => {
                if (gap > 0) {
                    const gCls = gap >= 4
                        ? 'text-rose-600 bg-rose-50 ring-1 ring-rose-200'
                        : 'text-amber-600 bg-amber-50 ring-1 ring-amber-200';
                    return `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-black ${gCls}" style="white-space:nowrap">GAP ${gap}미출</span>`;
                } else if (str > 0) {
                    const sCls = str >= 5
                        ? 'text-emerald-700 bg-emerald-100 ring-1 ring-emerald-300'
                        : 'text-emerald-600 bg-emerald-50 ring-1 ring-emerald-200';
                    return `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-black ${sCls}" style="white-space:nowrap">STR ${str}연속</span>`;
                }
                return '<span class="text-gray-300 text-[10px]">-</span>';
            })();

            // 대상번호 공 (회귀분석과 동일 크기 w-7 h-7)
            const ballsHtml = (grp.targets || []).map(n => {
                const colorClass = self.getBallColorClass(n);
                return `<span class="ball-common ${colorClass} w-7 h-7 text-xs mx-0.5">${n}</span>`;
            }).join('') || '<span class="text-gray-400">-</span>';

            // AI 종합 셀
            const ensExp = grp.ensemble_exp != null ? parseFloat(grp.ensemble_exp) : null;
            const ensCell = (() => {
                if (ensExp === null) return `<td class="px-3 py-3 text-center"><span style="color:#D1D5DB;font-size:10px">-</span></td>`;
                const r = _expToRange(ensExp);
                const rangeColor = ensExp >= 1.2 ? '#0F766E' : ensExp < 0.5 ? '#9CA3AF' : '#374151';
                return `<td class="px-3 py-3 text-center">
                    <div class="flex flex-col items-center gap-0.5">
                        <span style="font-family:monospace;font-size:12px;font-weight:800;color:${rangeColor}">${r.min}~${r.max}개</span>
                        <span style="font-size:9px;color:#94A3B8">기대 ${ensExp.toFixed(1)}개</span>
                    </div>
                </td>`;
            })();

            // 모델별 컬럼 (model_exp 우선, 없으면 model_scores 변환)
            const modelCells = MODEL_ORDER.map(m => {
                const color = MODEL_COLORS[m];
                let mExp = null;
                if (grp.model_exp && grp.model_exp[m] != null) {
                    mExp = parseFloat(grp.model_exp[m]);
                } else if (grp.model_scores && grp.model_scores[m] != null) {
                    const score = grp.model_scores[m].score || 0;
                    mExp = score / 100 * (grp.targets?.length || 6);
                }
                if (mExp === null) return `<td class="px-2 py-3 text-center"><span style="color:#D1D5DB">-</span></td>`;
                const mr  = _expToRange(mExp);
                const lbl = mr.min === mr.max ? `${mr.min}` : `${mr.min}~${mr.max}`;
                return `<td class="px-2 py-3 text-center"><span style="font-family:monospace;font-size:11px;font-weight:800;color:${color}">${lbl}</span></td>`;
            }).join('');

            html += `<tr class="border-b border-gray-100 last:border-0 hover:bg-gray-50 transition-colors">`;
            html += `<td class="px-4 py-3">
                <div class="flex flex-col gap-1">
                    <span class="inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-bold self-start" style="background:${typeColor}18;color:${typeColor}">${typeLbl}</span>
                    <span class="font-bold text-gray-800 text-xs leading-tight">${grp.title || '커스텀'}</span>
                </div>
            </td>`;
            html += `<td class="px-4 py-3"><div class="flex flex-wrap items-center">${ballsHtml}</div></td>`;
            html += `<td class="px-3 py-3 text-center">${gapStrHtml}</td>`;
            html += `<td class="px-3 py-3 text-center font-mono text-gray-500" style="white-space:nowrap">${avgHit}</td>`;
            html += ensCell;
            html += modelCells;
            html += `</tr>`;
        });

        html += '</tbody></table></div>';
        container.innerHTML = html;
    },

    async loadHistoryList() {
        const select = document.getElementById('historySelect');
        if (!select) return;

        // init()의 checkConnection(true)에서 이미 처리됨 - 중복 호출 금지
        if (!this.state.isConnected) return;

        const url = this._getBaseUrl();
        try {
            var res = await fetch(url + '/api/deep-analysis/v3/history', {
                signal: AbortSignal.timeout(15000)
            });
            if (!res.ok) return;
            var data = await res.json();
            if (!data.success) return;

            select.style.display = 'inline-block';
            while (select.options.length > 1) select.remove(1);

            (data.history || []).forEach(function (h) {
                var opt = document.createElement('option');
                opt.value = h.id;
                var date = new Date(h.created_at).toLocaleString('ko-KR', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
                opt.textContent = h.target_round + '회 (' + date + ') - ' + h.confidence + '%';
                select.appendChild(opt);
            });

            select.onchange = (e) => {
                if (e.target.value) {
                    this.loadHistory(e.target.value);
                }
            };

        } catch (e) {
            console.warn('이력 목록 로드 실패:', e);
        }
    },

    async loadHistory(historyId) {
        if (!historyId) return;
        var url = this._getBaseUrl();
        try {
            this.showLoading(true, '이력 데이터 로드 중...');
            var res = await fetch(url + '/api/deep-analysis/v3/history/' + historyId, {
                signal: AbortSignal.timeout(10000)
            });
            if (!res.ok) throw new Error('이력 조회 실패');
            var data = await res.json();
            if (!data.success) throw new Error(data.error);
            // [수정] analysis_data가 이미 객체이면 그대로 사용, 문자열이면 파싱
            var rawData = data.data.analysis_data;
            var analysisData = (typeof rawData === 'string') ? JSON.parse(rawData) : rawData;
            this.state.analysisData = analysisData;
            var roundEl = document.getElementById('targetRoundDisplay');
            if (roundEl) roundEl.textContent = analysisData.target_round;
            this.renderAll(analysisData);
            this._prefetchXAIInBackground();
        } catch (e) {
            console.error('이력 로드 실패:', e);
            alert('이력 로드 실패: ' + e.message);
        } finally {
            setTimeout(function () { DeepLearning.showLoading(false); }, 300);
        }
    },

    async _prefetchXAIInBackground() {
        // 백엔드 미연결 시 /api/explain/ 스팸 방지
        if (!this.state.isConnected) return;

        var d = this.state.analysisData;
        if (!d) return;
        if (!d.evidence) d.evidence = {};

        // 우선순위: top_5 + exclude_10 (클릭 가능성 높음)
        var priority = [...new Set([...(d.top_5 || []), ...(d.exclude_10 || [])])];

        // 나머지: matrix_data 번호 (total 점수 순)
        var _mtxSource = (d.analysis && d.analysis.matrix_data) ? d.analysis.matrix_data : (d.matrix_data || []);
        var matrixNums = [..._mtxSource].sort((a, b) => (b.total || 0) - (a.total || 0)).map(m => m.num);
        var remaining = matrixNums.filter(n => !priority.includes(n));
        var queue = [...priority, ...remaining];

        const url = this._getBaseUrl();
        const target_round = d.target_round;
        const CONCURRENCY = 3;

        const fetchOne = async (number) => {
            if (d.evidence[number]) return; // 이미 캐시됨
            try {
                const reqBody = { number, user_query: "이 번호에 대한 심층 분석을 해줘" };
                if (target_round) reqBody.target_round = target_round;
                const res = await fetch(url + '/api/explain/', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(reqBody),
                    signal: AbortSignal.timeout(15000)
                });
                if (res.ok) {
                    const xaiData = await res.json();
                    if (xaiData.explanation) {
                        d.evidence[number] = xaiData.explanation;
                        console.log(`[XAI Prefetch] ${number}번 캐시 완료`);
                    }
                    // 서버 응답 성공 → 연결 상태 업데이트 (콜드스타트 후 복구)
                    if (!this.state.isConnected) {
                        this.state.isConnected = true;
                        this.updateConnectionStatusUI();
                        this.loadHistoryList();
                    }
                }
            } catch (e) {
                // 백그라운드 프리페치 실패 무시
            }
        };

        // 1.5초 후 시작 (UI 렌더링과 경쟁 방지)
        await new Promise(r => setTimeout(r, 1500));

        // CONCURRENCY개씩 병렬 처리
        for (let i = 0; i < queue.length; i += CONCURRENCY) {
            // 분석 데이터가 교체된 경우 중단
            if (this.state.analysisData !== d) break;
            const batch = queue.slice(i, i + CONCURRENCY);
            await Promise.all(batch.map(fetchOne));
        }
    },

    async explainNumber(number) {
        var modal = document.getElementById('xaiModal');
        var content = document.getElementById('xaiContent');
        var title = document.getElementById('xaiTitle');
        if (!modal || !content) return;
        modal.classList.remove('hidden');
        if (title) title.textContent = number + '번 XAI 심층 분석';
        content.innerHTML = '<div class="text-center text-slate-400 py-8"><div class="w-10 h-10 border-3 border-blue-200 border-t-blue-600 rounded-full animate-spin mx-auto mb-3"></div><p>' + number + '번 분석 중...</p></div>';
        var localInfo = '';
        if (this.state.analysisData) {
            var d = this.state.analysisData;
            var evidenceText = (d.evidence && d.evidence[number]) ? d.evidence[number] : null;
            if (!evidenceText) {
                try {
                    const url = this._getBaseUrl();
                    const reqBody = { number: number, user_query: "이 번호에 대한 심층 분석을 해줘" };
                    if (d.target_round) reqBody.target_round = d.target_round;
                    const res = await fetch(url + '/api/explain/', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(reqBody),
                        signal: AbortSignal.timeout(30000)
                    });
                    if (res.ok) {
                        const xaiData = await res.json();
                        evidenceText = xaiData.explanation;
                        if (!d.evidence) d.evidence = {};
                        d.evidence[number] = evidenceText;
                    }
                } catch (e) {
                    console.warn(`[XAI] Failed to fetch explanation for ${number}:`, e);
                }
            }
            var matrixItem = null;
            var _mtxSource = (d.analysis && d.analysis.matrix_data) ? d.analysis.matrix_data : (d.matrix_data || []);
            if (_mtxSource.length) {
                matrixItem = _mtxSource.find(function (m) { return m.num === number; });
            }
            var prob = matrixItem ? (matrixItem.total || 0) / 100 : null;
            var isRecommended = (d.top_5 || []).indexOf(number) >= 0;
            if (!isRecommended && d.recommended) isRecommended = d.recommended.indexOf(number) >= 0;
            var isExcluded = (d.exclude_10 || []).indexOf(number) >= 0;
            if (!isExcluded && d.excluded) isExcluded = d.excluded.indexOf(number) >= 0;
            var statusClass = isRecommended ? 'bg-emerald-50 text-emerald-600 border border-emerald-200'
                : isExcluded ? 'bg-rose-50 text-rose-600 border border-rose-200'
                    : 'bg-slate-50 text-slate-500 border border-slate-200';
            var statusText = isRecommended ? '강력추천' : isExcluded ? '제외예상' : '일반';

            const colorClass = this.getBallColorClass(number);
            localInfo = '<div class="space-y-5 mb-6">' +
                '<div class="flex items-center gap-4 p-4 bg-gray-50 rounded-2xl border border-gray-100">' +
                '<span class="ball-common ' + colorClass + ' w-14 h-14 text-xl shadow-lg ring-4 ring-white">' + number + '</span>' +
                '<div class="flex-1">' +
                '<div class="flex items-center justify-between mb-1">' +
                '<p class="font-black text-gray-900 text-lg">번호 ' + number + ' 분석결과</p>' +
                '<span class="px-3 py-1 rounded-full text-xs font-bold ' + statusClass + '">' + statusText + '</span>' +
                '</div>' +
                '<p class="text-sm text-gray-500">앙상블 예측 확률: <span class="font-black text-blue-600 text-base">' + (prob !== null ? (prob * 100).toFixed(2) : '--') + '%</span></p>' +
                '</div></div>';

            if (matrixItem) {
                var corrInfo = '';
                if (matrixItem.penalty != null && matrixItem.penalty < 1.0) {
                    corrInfo += ' <span class="text-rose-500 font-bold ml-1">⚠️과출현제어(' + Math.round((1 - matrixItem.penalty) * 100) + '%)</span>';
                }
                if (matrixItem.boost != null && matrixItem.boost > 1.0) {
                    corrInfo += ' <span class="text-emerald-600 font-bold ml-1">⚡주기임박</span>';
                }
                localInfo += '<div class="flex items-center gap-4 text-xs text-slate-500 bg-slate-50 px-4 py-2 rounded-lg border border-slate-100">' +
                    '<span>Gap: <strong class="text-slate-700">' + matrixItem.gap + '</strong></span>' +
                    '<span class="w-px h-3 bg-slate-300"></span>' +
                    '<span>빈도: <strong class="text-slate-700">' + (matrixItem.freq * 100).toFixed(1) + '%</strong></span>' +
                    corrInfo +
                    '</div></div>';
            } else {
                localInfo += '</div>';
            }
            if (evidenceText) {
                const reasons = evidenceText.split(" | ");
                let reasonsHtml = '<ul class="space-y-2">';
                reasons.forEach(reason => {
                    const isWarning = reason.includes("[경고]") || reason.includes("제외") || reason.includes("부족") || reason.includes("높음");
                    const isPositive = reason.includes("추천") || reason.includes("유력") || reason.includes("매우") || reason.includes("적합");
                    let boxClass = "bg-white border-slate-100 text-slate-600";
                    let icon = "check_circle";
                    let iconClass = "text-slate-400";
                    if (isWarning) {
                        boxClass = "bg-rose-50/50 border-rose-100 text-rose-700";
                        icon = "warning";
                        iconClass = "text-rose-500";
                    } else if (isPositive) {
                        boxClass = "bg-blue-50/50 border-blue-100 text-blue-700";
                        icon = "auto_awesome";
                        iconClass = "text-blue-500";
                    }
                    reasonsHtml += `
                        <li class="flex items-start gap-3 p-3 rounded-xl border ${boxClass}">
                            <span class="material-symbols-outlined ${iconClass} text-lg mt-0.5 flex-shrink-0">${icon}</span>
                            <span class="text-sm leading-relaxed font-medium">${reason}</span>
                        </li>
                    `;
                });
                reasonsHtml += '</ul>';
                localInfo += `
                    <div class="mb-5">
                        <h4 class="font-bold text-slate-800 text-sm mb-3 flex items-center gap-2">
                            <span class="material-symbols-outlined text-blue-600">psychology</span> AI 심층 분석 리포트
                        </h4>
                        ${reasonsHtml}
                    </div>
                `;
            }
            if (matrixItem && matrixItem.models) {
                var MODEL_COLORS = { lstm: '#818cf8', xgboost: '#60a5fa', cnn: '#f472b6', transformer: '#fb923c', markov: '#34d399', autoencoder: '#a855f7', gnn: '#ef4444' };
                var MODEL_LABELS = { lstm: 'LSTM (시계열)', xgboost: 'XGBoost (패턴)', cnn: 'CNN (공간)', transformer: 'Transformer (맥락)', markov: 'Markov (전이)', autoencoder: 'Autoencoder (압축)', gnn: 'GNN (관계망)' };
                var modelHtml = '';
                ['lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'].forEach(mKey => {
                    var mVal = matrixItem.models[mKey] || {};
                    var score = mVal.score || 0;
                    var color = MODEL_COLORS[mKey] || '#94a3b8';
                    var label = MODEL_LABELS[mKey] || mKey;
                    modelHtml += `<div class="flex items-center gap-3 mb-2"><span class="text-[10px] font-bold w-28 text-slate-500 flex-shrink-0">${label}</span><div class="flex-1 bg-slate-100 h-1.5 rounded-full overflow-hidden"><div class="h-full rounded-full" style="width:${score}%;background:${color}"></div></div><span class="text-[10px] font-bold w-8 text-right text-slate-600">${score}</span></div>`;
                });
                localInfo += `<div class="bg-slate-50 rounded-xl p-4 border border-slate-100 mt-4"><h5 class="font-bold text-slate-600 text-xs mb-3">7개 모델별 기여도</h5>${modelHtml}</div>`;
            }
        }
        content.innerHTML = localInfo || '<div class="text-center text-slate-400 py-8"><p>분석 데이터를 먼저 실행해주세요.</p></div>';
    },

    closeXaiModal() {
        var modal = document.getElementById('xaiModal');
        if (modal) modal.classList.add('hidden');
    },

    _getBaseUrl() {
        return window.AI_SERVER_URL || 'https://parksungdeok-lotto-ai-backend.hf.space';
    },

    renderBalls(id, nums) {
        var el = document.getElementById(id);
        if (!el) return;
        if (!nums || nums.length === 0) {
            el.innerHTML = '<span class="text-slate-400 text-xs">추천 없음</span>';
            return;
        }
        var self = this;
        el.className = 'flex flex-wrap gap-2';
        el.innerHTML = nums.map(function (n) {
            var color = self.getBallColor(n);
            return '<span class="w-7 h-7 rounded-full flex items-center justify-center text-[11px] font-black text-white shadow cursor-pointer hover:scale-110 transition-transform" style="background-color: ' + color + '" onclick="window.DeepLearning.explainNumber(' + n + ')" title="' + n + '번 클릭 시 XAI 분석">' + n + '</span>';
        }).join('');
    },

    showLoading(show, text) {
        var overlay = document.getElementById('loadingOverlay');
        if (!overlay) return;
        if (show) {
            overlay.classList.remove('hidden');
            overlay.classList.add('flex');
            if (text) {
                var pt = document.getElementById('progressText');
                if (pt) pt.textContent = text;
            }
            if (this._loadingTimeout) clearTimeout(this._loadingTimeout);
            this._loadingTimeout = setTimeout(() => {
                if (!overlay.classList.contains('hidden')) {
                    console.warn("⚠️ [DeepLearning] Loading timed out (60s). Force hiding overlay.");
                    this.showLoading(false);
                    const summaryEl = document.getElementById('aiSummaryText');
                    if (summaryEl) {
                        summaryEl.innerHTML = '<span class="text-red-500 font-bold">⚠️ 분석 시간이 초과되었습니다. 잠시 후 다시 시도해주세요.</span>';
                    }
                }
            }, 60000);
        } else {
            overlay.classList.add('hidden');
            overlay.classList.remove('flex');
            if (this._loadingTimeout) {
                clearTimeout(this._loadingTimeout);
                this._loadingTimeout = null;
            }
        }
    },

    setProgress(pct, text) {
        var bar = document.getElementById('progressBar');
        var pt = document.getElementById('progressText');
        if (bar) bar.style.width = pct + '%';
        if (pt && text) pt.textContent = text;
    },

    animateValue(id, start, end, duration) {
        var obj = document.getElementById(id);
        if (!obj) return;
        var startTimestamp = null;
        var step = function (timestamp) {
            if (!startTimestamp) startTimestamp = timestamp;
            var progress = Math.min((timestamp - startTimestamp) / duration, 1);
            obj.innerHTML = Math.floor(progress * (end - start) + start);
            if (progress < 1) {
                window.requestAnimationFrame(step);
            }
        };
        window.requestAnimationFrame(step);
    }
};

window.DeepLearning = DeepLearning;
