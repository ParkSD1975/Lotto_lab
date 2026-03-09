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

        // 1. 핵심 정보 병렬 로드 (checkConnection 먼저 완료해야 loadHistoryList가 isConnected를 정확히 읽음)
        await Promise.all([
            this.setTargetRound(),
            this.checkConnection(true)
        ]);
        this.loadHistoryList(); // checkConnection 완료 후 비동기 실행 (중복 /health 요청 방지)

        // 2. UI 이벤트 바인딩
        this.bindEvents();

        console.log(`⏱️ [DeepLearning] 초기 데이터 로드 완료 (${Date.now() - startTime}ms)`);

        // 3. 분석 실행
        this.runAnalysis();
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
                const url = window.AI_SERVER_URL || 'https://lottolab-production-31e3.up.railway.app';
                const timeout = isStartup ? 3000 : 5000;
                const res = await fetch(url + '/health', { signal: AbortSignal.timeout(timeout) });
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
            const sec = elapsed ? ` (${elapsed}초...)` : '';
            el.innerHTML = `<span class="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse"></span> 서버 웜업 중${sec}`;
            el.className = 'flex items-center gap-1.5 text-[11px] font-bold text-amber-600 bg-amber-50 px-2.5 py-0.5 rounded-full border border-amber-200';
        } else if (this.state.isConnected) {
            el.innerHTML = '<span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span> 연결됨';
            el.className = 'flex items-center gap-1.5 text-[11px] font-bold text-emerald-600 bg-emerald-50 px-2.5 py-0.5 rounded-full border border-emerald-200';
        } else {
            el.innerHTML = '<span class="w-1.5 h-1.5 rounded-full bg-rose-500"></span> 연결 끊김';
            el.className = 'flex items-center gap-1.5 text-[11px] font-bold text-rose-500 bg-rose-50 px-2.5 py-0.5 rounded-full border border-rose-200';
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
            let dbData = null;
            if (!forceReload) {
                dbData = await this._fetchAnalysisFromDB(this.state.targetRound);
            }
            if (dbData) {
                console.log("📦 [DeepLearning] DB에서 분석 결과 로드 성공!");
                this.setProgress(100, '완료!');
                this.state.analysisData = dbData;
                this.renderAll(dbData);
                this._prefetchXAIInBackground();
                this.state.isAnalyzing = false;
                this.showLoading(false);
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
                    this.showLoading(false);
                    // 서버 웜업 후 이력 목록 재시도 (초기 콜드스타트로 실패했을 수 있음)
                    const histSel = document.getElementById('historySelect');
                    if (!histSel || histSel.options.length <= 1) this.loadHistoryList();
                } else {
                    throw new Error("Python 분석 실패 (응답 없음)");
                }
            } else {
                console.warn("xq [DeepLearning] 서버 미연결 & DB 데이터 없음.");
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

    async _fetchAnalysisFromDB(round) {
        if (!window.supabaseClient) return null;
        try {
            const { data, error } = await window.supabaseClient
                .from('deep_analysis_history')
                .select('analysis_data')
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

    async _runLocalFallbackAnalysis() {
        console.warn("🚫 [DeepLearning] 로컬 폴백 비활성화.");
        return null;
    },

    // ── 전체 렌더링 ──
    renderAll(result) {
        console.log("🎨 [DeepLearning] renderAll() Called", result);
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

        if (rangeAnalysis) this.renderRangeAnalysis(rangeAnalysis);
        if (matrixData) this.renderMatrixData(matrixData);
        if (analysisData.tail_analysis) this.renderTailAnalysis(analysisData.tail_analysis);
        if (analysisData.lotto_paper_analysis) this.renderLottoPaperAnalysis(analysisData.lotto_paper_analysis);
        if (analysisData.magic_square_analysis) this.renderMagicSquareAnalysis(analysisData.magic_square_analysis);
        if (analysisData.number_band_analysis) this.renderNumberBandAnalysis(analysisData.number_band_analysis);
        if (analysisData.missing_group_data) this.renderMissingGroupAnalysis(analysisData.missing_group_data);
        if (analysisData.hot_cold_data) this.renderHotColdAnalysis(analysisData.hot_cold_data);
        if (analysisData.regression_analysis) this.renderRegressionAnalysis(analysisData.regression_analysis);
        if (analysisData.custom_evaluations) this.renderCustomEvaluations(analysisData.custom_evaluations);

        this.renderExcludeFixed(strategy, compatAnalysis);
        this.renderFilterRecommendations(strategy);
        this.renderCombinations(result.combinations, compatAnalysis, matrixData);

        var effectivePipeline = result.pipeline;
        if (!effectivePipeline && result.evidence && result.evidence.model_weights) {
            effectivePipeline = {
                modelWeights: result.evidence.model_weights,
                weightReasons: '딥러닝 앙상블 분석 완료',
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
        if (n <= 10) return '#fbc400';
        if (n <= 20) return '#69c8f2';
        if (n <= 30) return '#ff7272';
        if (n <= 40) return '#aaaaaa';
        return '#b0d840';
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
                return '<span class="px-3 py-1 bg-white text-indigo-700 text-xs font-bold rounded-lg border border-indigo-100 shadow-sm">' + k + '</span>';
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
                const hotR = hc.hot_ratio || 50;
                const coldR = hc.cold_ratio || 50;
                hcUI.innerHTML = `
                    <div class="flex items-center justify-between text-xs font-bold text-gray-500 mb-2">
                        <span class="text-rose-500">Hot ${hotR}%</span>
                        <span class="text-blue-500">Cold ${coldR}%</span>
                    </div>
                    <div class="w-full h-2.5 bg-gray-100 rounded-full overflow-hidden flex">
                        <div class="h-full bg-rose-400" style="width: ${hotR}%"></div>
                        <div class="h-full bg-blue-400" style="width: ${coldR}%"></div>
                    </div>
                    <p class="text-xs font-medium text-gray-700 mt-3 leading-snug">${hc.trend_text || ''}</p>
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
            lstm: { label: 'LSTM (시계열)', icon: 'timeline', gradient: 'from-indigo-500 to-indigo-600', barColor: '#818cf8' },
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
        const FILTER_LABELS = {
            sum: '총합', tail_sum: '끝수합', ac: 'AC값',
            odd: '홀짝비율', high: '저고비율', prime: '소수',
            composite: '합성수', consecutive: '연번', square: '제곱수',
            triangular: '삼각수', twin: '동형수', mul3: '3의배수',
            mul4: '4의배수', mul5: '5의배수', non_multiple: '배수외'
        };
        const FILTER_ORDER = [
            'sum', 'tail_sum', 'ac',
            'odd', 'high', 'consecutive', 'twin',
            'prime', 'composite', 'square', 'triangular',
            'mul3', 'mul4', 'mul5', 'non_multiple'
        ];
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
        html += '<th class="px-4 py-4 text-center font-bold text-indigo-600 bg-indigo-50/50">앙상블<br>범위</th>';
        models.forEach(m => {
            const cfg = MODEL_CONFIG[m];
            html += `<th class="px-4 py-4 text-center font-bold text-gray-500">${cfg.label}<br><span class="text-gray-400 font-normal text-[10px]">예상범위</span></th>`;
        });
        html += '</tr></thead><tbody>';
        let rowIdx = 0;
        const orderedEntries = FILTER_ORDER
            .filter(k => rangeAnalysis[k] !== undefined)
            .map(k => [k, rangeAnalysis[k]])
            .concat(Object.entries(rangeAnalysis).filter(([k]) => !FILTER_ORDER.includes(k)));

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
            rowIdx++;
            html += `<tr class="border-b border-gray-50 last:border-0 hover:bg-gray-50 transition-colors">`;
            html += `<td class="px-5 py-3 font-bold text-gray-700">${label}</td>`;
            html += `<td class="px-4 py-3 text-center font-mono font-bold text-indigo-600 bg-indigo-50/30">${ensembleRange}</td>`;
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
                html += `<span class="font-bold w-24 flex-shrink-0${isActive ? ' text-indigo-600' : ' text-gray-500'}">${cfg.label}</span>`;
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

    renderFilterRecommendations(strategy) {
        var container = document.getElementById('filterRecommendations');
        if (!container) return;
        var recs = (strategy && strategy.filter_recommendations) ? strategy.filter_recommendations : [];
        if (recs.length === 0) {
            container.innerHTML = '<div class="col-span-3 text-center text-gray-400 text-sm py-12">필터 추천 데이터가 없습니다.</div>';
            return;
        }
        var iconMap = {
            '총합': 'functions', '끝수합': 'pin', 'AC값': 'calculate',
            '홀짝': 'contrast', '홀짝비율': 'contrast', '저고': 'swap_vert', '저고비율': 'swap_vert',
            '연속수': 'linear_scale', '연속번호': 'linear_scale',
            '이월수': 'replay', '소수': 'looks_one', '소수개수': 'looks_one',
            '합성수': 'looks_two', '제곱수': 'crop_square', '삼각수': 'change_history', '쌍둥이수': 'group',
            '핫콜드': 'local_fire_department', '범위': 'expand',
            '최근 10회 출현': 'history', '장기 미출현': 'hourglass_empty',
            '3의 배수': 'view_week', '4의 배수': 'view_week', '5의 배수': 'view_week', '비배수': 'block', '이웃수': 'people_alt'
        };
        container.innerHTML = recs.map(function (r) {
            var icon = iconMap[r.filter] || 'tune';
            var valueText = r.pattern
                ? '패턴: ' + r.pattern
                : (r.min !== undefined && r.max !== undefined)
                    ? r.min + ' ~ ' + r.max
                    : r.max !== undefined ? '최대 ' + r.max : '-';
            return '<div class="bg-white rounded-2xl border border-gray-100 p-5 shadow-sm hover:shadow-md transition-shadow">' +
                '<div class="flex items-center gap-3 mb-3"><div class="p-1.5 bg-indigo-50 rounded-lg text-indigo-600"><span class="material-symbols-outlined text-lg">' + icon + '</span></div><h4 class="font-bold text-gray-800 text-sm">' + r.filter + '</h4></div>' +
                '<p class="text-gray-900 font-black text-xl mb-3 tracking-tight">' + valueText + '</p>' +
                '<div class="bg-gray-50 p-3 rounded-xl text-xs text-gray-600 leading-relaxed border border-gray-100">' + (r.evidence || '근거 데이터 없음') + '</div></div>';
        }).join('');
    },

    renderCombinations(combinations, analysis, matrixData) {
        const container = document.getElementById('combos');
        if (!container || !combinations || combinations.length === 0) return;
        const self = this;
        const top5Set = new Set(analysis ? (analysis.recommended || analysis.top_6 || []) : []);
        const excludeSet = new Set(analysis ? (analysis.excluded || []) : []);
        const scoreMap = {};
        if (matrixData) matrixData.forEach(d => { scoreMap[d.num] = Math.round(d.total || 0); });
        const maxScore = Math.max(...combinations.map(c => c.score));
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
            const scoreColor = scorePct >= 0.8 ? '#4F46E5' : scorePct >= 0.5 ? '#6B7280' : '#9CA3AF';
            const rankBg = rank === 1 ? '#4F46E5' : rank <= 3 ? '#1F2937' : '#4B5563';
            const ballsHtml = nums.map(n => {
                const colorClass = self.getBallColorClass(n);
                const isTop = top5Set.has(n);
                // [디자인 수정] Top5 표시는 금색 테두리와 상단 점(Dot)으로 심플하게 변경
                return `<span style="position:relative;display:inline-flex;flex-direction:column;align-items:center;cursor:pointer" onclick="window.DeepLearning.explainNumber(${n})">
                    <span class="ball-common ${colorClass} w-9 h-9 text-sm ${isTop ? 'ring-2 ring-amber-400 ring-offset-2' : ''}">${n}</span>
                    ${isTop ? '<span style="position:absolute;top:-4px;right:-4px;width:8px;height:8px;background:#FBBF24;border-radius:50%;border:2px solid white;"></span>' : ''}
                </span>`;
            }).join('');

            const modelBar = ['lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'].map(m => {
                const colors = { lstm: '#818cf8', xgboost: '#60a5fa', cnn: '#f472b6', transformer: '#fb923c', markov: '#34d399', autoencoder: '#a855f7', gnn: '#ef4444' };
                const labels = { lstm: 'L', xgboost: 'X', cnn: 'C', transformer: 'T', markov: 'M', autoencoder: 'A', gnn: 'G' };
                const agree = nums.some(n => modelTop[m] && modelTop[m].has(n));
                // 모델 바도 더 얇고 심플하게
                return `<div style="width:4px;height:24px;border-radius:2px;background:${agree ? colors[m] : '#F3F4F6'};" title="${labels[m]}"></div>`;
            }).join('');

            // [디자인 수정] 순위는 큰 숫자로, 전체 레이아웃 간소화
            return `<div class="group relative bg-white border border-gray-100 rounded-2xl p-5 hover:border-indigo-200 hover:shadow-lg transition-all duration-300">
                <div class="absolute left-0 top-0 bottom-0 w-1 bg-transparent group-hover:bg-indigo-500 rounded-l-2xl transition-colors"></div>
                <div class="flex items-center gap-6">
                    <span class="text-2xl font-black text-gray-200 group-hover:text-indigo-500 w-10 text-center transition-colors font-mono">${String(rank).padStart(2, '0')}</span>

                    <div class="flex gap-2">${ballsHtml}</div>

                    <div class="ml-auto flex items-center gap-6">
                        <div class="flex gap-1 items-center" title="모델 동의">${modelBar}</div>

                        <div class="text-right">
                            <div class="text-xs text-gray-400 font-medium mb-0.5">예측점수</div>
                            <div class="text-lg font-black ${scorePct >= 0.8 ? 'text-indigo-600' : 'text-gray-700'}">${(score * 100).toFixed(0)}<span class="text-xs font-normal text-gray-400 ml-0.5">점</span></div>
                        </div>
                    </div>
                </div>

                <!-- 하단 상세 스탯 (마우스 오버 시 또는 항상 표시) -->
                <div class="mt-4 pt-3 border-t border-gray-50 flex items-center gap-4 text-xs text-gray-400 font-mono">
                    <span class="${topIncluded.length >= 2 ? 'text-indigo-600 font-bold' : ''}">Top5: ${topIncluded.length}개</span>
                    <span>합: ${sum}</span>
                    <span>홀짝: ${odd}:${6 - odd}</span>
                    <span>AC: ${ac}</span>
                    ${isVerified ? '<span class="ml-auto text-emerald-600 font-bold flex items-center gap-1"><span class="material-symbols-outlined text-[14px]">check_circle</span>AI검증</span>' : ''}
                </div>
            </div>`;
        }).join('');
    },

    renderPipelineInfo(pipeline) {
        if (!pipeline) return;
        const condContainer = document.getElementById('modelConditionContainer');
        if (condContainer && pipeline.modelWeights) {
            const MODEL_COLORS = { lstm: '#818cf8', xgboost: '#60a5fa', cnn: '#f472b6', transformer: '#fb923c', markov: '#34d399', autoencoder: '#a855f7', gnn: '#ef4444' };
            const MODEL_LABELS = { lstm: 'LSTM', xgboost: 'XGBoost', cnn: 'CNN', transformer: 'Transformer', markov: 'Markov', autoencoder: 'Autoenc.', gnn: 'GNN' };
            // 구버전 DB 캐시에 누락된 모델 키를 기본값으로 보완 (예: autoencoder:0.0 → 0.045)
            const DEFAULT_WEIGHTS = { lstm: 0.213, xgboost: 0.182, cnn: 0.212, transformer: 0.212, markov: 0.091, autoencoder: 0.045, gnn: 0.045 };
            const rawWeights = pipeline.modelWeights;
            const weights = {};
            Object.keys(MODEL_LABELS).forEach(name => {
                const v = rawWeights[name];
                weights[name] = (v != null && v > 0) ? v : DEFAULT_WEIGHTS[name] || 0;
            });
            const weightValues = Object.values(weights).map(v => v || 0);

            const maxW = weightValues.length > 0 ? Math.max(...weightValues) : 0;
            const barsHtml = Object.entries(weights).map(([name, w_val]) => {
                const pct = (w_val * 100).toFixed(1);
                const barW = maxW > 0 ? (w_val / maxW * 100).toFixed(1) : 0;
                const color = MODEL_COLORS[name] || '#9CA3AF';
                // 구버전 캐시에서 기본값으로 보완된 경우 텍스트 색상을 흐리게
                const isDefault = (rawWeights[name] == null || rawWeights[name] === 0);
                return `<div style="display:flex;align-items:center;gap:10px;font-size:12px">
                    <span style="width:70px;color:#4B5563;font-weight:700;text-align:right">${MODEL_LABELS[name] || name}</span>
                    <div style="flex:1;height:10px;background:#F3F4F6;border-radius:99px;overflow:hidden">
                        <div style="width:${barW}%;height:100%;background:${isDefault ? color + '80' : color};border-radius:99px;transition:width 0.6s ease"></div>
                    </div>
                    <span style="width:40px;color:${isDefault ? '#9CA3AF' : color};font-weight:800;text-align:right">${isDefault ? '~' : ''}${pct}%</span>
                </div>`;
            }).join('');
            const reason = pipeline.weightReasons || '';
            condContainer.innerHTML = `
                <div class="card">
                    <div class="card-header">
                        <span class="material-symbols-outlined icon">neurology</span>
                        <h3>모델 컨디션 (Meta-Learning)</h3>
                        <span class="ml-auto text-[10px] text-gray-400 font-medium whitespace-nowrap bg-gray-50 px-2 py-1 rounded-lg">가중치 자동 조정</span>
                    </div>
                    <div class="card-body">
                        <div style="display:flex;flex-direction:column;gap:10px">${barsHtml}</div>
                        ${reason ? `<div style="margin-top:16px;font-size:12px;color:#6B7280;border-top:1px solid #F3F4F6;padding-top:12px;line-height:1.6">${reason}</div>` : ''}
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

        // 딥러닝 모델별 고유 색상 (차분한 톤)
        const MODEL_COLORS = {
            lstm: '#6366F1', xgboost: '#3B82F6', cnn: '#EC4899',
            transformer: '#F97316', markov: '#10B981', autoencoder: '#8B5CF6', gnn: '#EF4444'
        };
        const models = ['lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'];

        tbody.innerHTML = tailData.map(item => {
            const exp = typeof item.exp === 'number' ? item.exp : 0;
            const str = item.str != null ? item.str : '-';

            // 1. 앙상블 (메인 지표) - 딥 틸(Deep Teal) 테마 적용
            let barColor = '#CCFBF1'; // 기본: 연한 민트
            let width = '10%';

            if (exp >= 2.0) { width = '100%'; barColor = '#134E4A'; } // Hot
            else if (exp >= 1.5) { width = '85%'; barColor = '#0F766E'; }
            else if (exp >= 1.0) { width = '60%'; barColor = '#14B8A6'; }
            else if (exp >= 0.5) { width = '30%'; barColor = '#5EEAD4'; }

            const expCell = `
                <div class="flex flex-col items-center justify-center h-full px-2" title="예상 개수: ${exp.toFixed(2)}">
                    <div class="w-full h-1.5 bg-teal-50 rounded-full overflow-hidden">
                        <div style="width:${width};height:100%;background-color:${barColor};border-radius:99px;"></div>
                    </div>
                </div>
            `;

            // 2. 모델별 미니 바 (숫자 제거, 투명도 조절)
            const modelCells = models.map(m => {
                const val = item.model_exp && item.model_exp[m] != null ? parseFloat(item.model_exp[m]) : 0;
                let opacity = 0.15;
                let height = '4px';

                if (val >= 1.5) { opacity = 1.0; height = '14px'; } // 강함
                else if (val >= 1.0) { opacity = 0.7; height = '10px'; } // 중간
                else if (val >= 0.5) { opacity = 0.4; height = '6px'; } // 약함

                return `<td class="px-1 py-3 text-center align-bottom" title="${m.toUpperCase()}: ${val.toFixed(2)}">
                    <div style="display:flex;align-items:flex-end;justify-content:center;height:16px;">
                        <div style="width:12px;height:${height};background-color:${MODEL_COLORS[m]};opacity:${opacity};border-radius:2px;"></div>
                    </div>
                </td>`;
            }).join('');

            return `<tr class="hover:bg-gray-50 border-b border-gray-100 last:border-0 transition-colors">
                <td class="px-4 py-3 font-bold text-center text-gray-700 text-sm">${item.tail}</td>
                <td class="px-2 py-3 text-center w-24">${expCell}</td>
                ${modelCells}
                <td class="px-4 py-3 text-center font-mono text-xs text-gray-500">${item.gap}</td>
                <td class="px-4 py-3 text-center font-mono text-xs text-gray-500">${str}</td>
            </tr>`;
        }).join('');
    },

    renderLottoPaperAnalysis(paperData) {
        const container = document.getElementById('lottoPaperContainer');
        if (!container || !paperData) return;
        const MODEL_COLORS = {
            lstm: '#6366F1', xgboost: '#3B82F6', cnn: '#EC4899',
            transformer: '#F97316', markov: '#10B981', autoencoder: '#8B5CF6', gnn: '#EF4444'
        };
        const models = ['lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'];
        const MODEL_ABBR = { lstm: 'L', xgboost: 'X', cnn: 'C', transformer: 'T', markov: 'M', autoencoder: 'A', gnn: 'G' };

        const buildTable = (title, items) => {
            let html = `<div class="mb-8">`;
            html += `<div class="flex items-center gap-2 mb-4 px-1"><span class="w-1 h-4 bg-gray-800 rounded-full"></span><span class="text-sm font-bold text-gray-800 uppercase tracking-wide">${title}</span></div>`;
            html += '<div class="overflow-x-auto rounded-2xl border border-gray-200 shadow-sm bg-white">';
            html += '<table class="w-full text-xs">';
            html += '<thead><tr class="bg-gray-50/50 border-b border-gray-200">';
            html += '<th class="px-4 py-3 text-left font-bold text-gray-700">구분</th>';
            html += '<th class="px-4 py-3 text-center font-bold text-indigo-600">앙상블</th>';
            models.forEach(m => {
                html += `<th class="px-2 py-3 text-center font-semibold text-gray-500" title="${m.toUpperCase()}">${MODEL_ABBR[m]}</th>`;
            });
            html += '<th class="px-4 py-3 text-center font-bold text-gray-600">Gap</th>';
            html += '<th class="px-4 py-3 text-center font-bold text-gray-600">STR</th>';
            html += '</tr></thead><tbody>';

            items.forEach((item, idx) => {
                const exp = typeof item.exp === 'number' ? item.exp : 0;

                let barColor = '#CCFBF1';
                let width = '10%';
                if (exp >= 2.0) { width = '100%'; barColor = '#134E4A'; }
                else if (exp >= 1.5) { width = '85%'; barColor = '#0F766E'; }
                else if (exp >= 1.0) { width = '60%'; barColor = '#14B8A6'; }
                else if (exp >= 0.5) { width = '30%'; barColor = '#5EEAD4'; }

                const expCell = `
                    <div class="flex flex-col items-center justify-center h-full px-2" title="예상 개수: ${exp.toFixed(2)}">
                        <div class="w-full h-1.5 bg-teal-50 rounded-full overflow-hidden">
                            <div style="width:${width};height:100%;background-color:${barColor};border-radius:99px;"></div>
                        </div>
                    </div>
                `;

                const modelCells = models.map(m => {
                    const val = item.model_exp && item.model_exp[m] != null ? parseFloat(item.model_exp[m]) : 0;
                    let opacity = 0.15;
                    let height = '4px';
                    if (val >= 1.5) { opacity = 1.0; height = '14px'; }
                    else if (val >= 1.0) { opacity = 0.7; height = '10px'; }
                    else if (val >= 0.5) { opacity = 0.4; height = '6px'; }

                    return `<td class="px-2 py-3 text-center align-bottom" title="${m.toUpperCase()}: ${val.toFixed(2)}">
                        <div style="display:flex;align-items:flex-end;justify-content:center;height:16px;">
                            <div style="width:12px;height:${height};background-color:${MODEL_COLORS[m]};opacity:${opacity};border-radius:2px;"></div>
                        </div>
                    </td>`;
                }).join('');

                html += `<tr class="border-b border-gray-100 last:border-0 hover:bg-gray-50 transition-colors">`;
                html += `<td class="px-4 py-3 font-bold text-gray-700 text-sm">${item.label}</td>`;
                html += `<td class="px-4 py-3 text-center">${expCell}</td>`;
                html += modelCells;
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
        const MODEL_COLORS = {
            lstm: '#6366F1', xgboost: '#3B82F6', cnn: '#EC4899',
            transformer: '#F97316', markov: '#10B981', autoencoder: '#8B5CF6', gnn: '#EF4444'
        };
        const models = ['lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'];
        const MODEL_ABBR = { lstm: 'L', xgboost: 'X', cnn: 'C', transformer: 'T', markov: 'M', autoencoder: 'A', gnn: 'G' };

        let html = '<div class="overflow-x-auto rounded-2xl border border-gray-200 shadow-sm bg-white">';
        html += '<table class="w-full text-xs">';
        html += '<thead><tr class="bg-gray-50/50 border-b border-gray-200">';
        html += '<th class="px-4 py-3 text-left font-bold text-gray-700">번호대</th>';
        html += '<th class="px-4 py-3 text-center font-bold text-indigo-600">앙상블</th>';
        models.forEach(m => {
            html += `<th class="px-2 py-3 text-center font-semibold text-gray-500" title="${m.toUpperCase()}">${MODEL_ABBR[m]}</th>`;
        });
        html += '<th class="px-4 py-3 text-center font-bold text-gray-600">Gap</th>';
        html += '<th class="px-4 py-3 text-center font-bold text-gray-600">STR</th>';
        html += '</tr></thead><tbody>';

        bandData.forEach((item, idx) => {
            const exp = typeof item.exp === 'number' ? item.exp : 0;

            let barColor = '#CCFBF1';
            let width = '10%';
            if (exp >= 2.0) { width = '100%'; barColor = '#134E4A'; }
            else if (exp >= 1.5) { width = '85%'; barColor = '#0F766E'; }
            else if (exp >= 1.0) { width = '60%'; barColor = '#14B8A6'; }
            else if (exp >= 0.5) { width = '30%'; barColor = '#5EEAD4'; }

            const expCell = `
                <div class="flex flex-col items-center justify-center h-full px-2" title="예상 개수: ${exp.toFixed(2)}">
                    <div class="w-full h-1.5 bg-teal-50 rounded-full overflow-hidden">
                        <div style="width:${width};height:100%;background-color:${barColor};border-radius:99px;"></div>
                    </div>
                </div>
            `;

            const modelCells = models.map(m => {
                const val = item.model_exp && item.model_exp[m] != null ? parseFloat(item.model_exp[m]) : 0;
                let opacity = 0.15;
                let height = '4px';
                if (val >= 1.5) { opacity = 1.0; height = '14px'; }
                else if (val >= 1.0) { opacity = 0.7; height = '10px'; }
                else if (val >= 0.5) { opacity = 0.4; height = '6px'; }

                return `<td class="px-2 py-3 text-center align-bottom" title="${m.toUpperCase()}: ${val.toFixed(2)}">
                    <div style="display:flex;align-items:flex-end;justify-content:center;height:16px;">
                        <div style="width:12px;height:${height};background-color:${MODEL_COLORS[m]};opacity:${opacity};border-radius:2px;"></div>
                    </div>
                </td>`;
            }).join('');

            html += `<tr class="border-b border-gray-100 last:border-0 hover:bg-gray-50 transition-colors">`;
            html += `<td class="px-4 py-3 font-bold text-gray-700 text-sm">${item.label}</td>`;
            html += `<td class="px-4 py-3 text-center">${expCell}</td>`;
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
        const MODEL_COLORS = {
            lstm: '#6366F1', xgboost: '#3B82F6', cnn: '#EC4899',
            transformer: '#F97316', markov: '#10B981', autoencoder: '#8B5CF6', gnn: '#EF4444'
        };
        const models = ['lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'];
        const MODEL_ABBR = { lstm: 'L', xgboost: 'X', cnn: 'C', transformer: 'T', markov: 'M', autoencoder: 'A', gnn: 'G' };

        let html = '<div class="overflow-x-auto rounded-2xl border border-gray-200 shadow-sm bg-white">';
        html += '<table class="w-full text-xs">';
        html += '<thead><tr class="bg-gray-50/50 border-b border-gray-200">';
        html += '<th class="px-4 py-3 text-left font-bold text-gray-700">궁</th>';
        html += '<th class="px-4 py-3 text-center font-bold text-indigo-600">앙상블</th>';
        models.forEach(m => {
            html += `<th class="px-2 py-3 text-center font-semibold text-gray-500" title="${m.toUpperCase()}">${MODEL_ABBR[m]}</th>`;
        });
        html += '<th class="px-4 py-3 text-center font-bold text-gray-600">Gap</th>';
        html += '<th class="px-4 py-3 text-center font-bold text-gray-600">STR</th>';
        html += '</tr></thead><tbody>';

        squareData.forEach((item, idx) => {
            const exp = typeof item.exp === 'number' ? item.exp : 0;

            let barColor = '#CCFBF1';
            let width = '10%';
            if (exp >= 2.0) { width = '100%'; barColor = '#134E4A'; }
            else if (exp >= 1.5) { width = '85%'; barColor = '#0F766E'; }
            else if (exp >= 1.0) { width = '60%'; barColor = '#14B8A6'; }
            else if (exp >= 0.5) { width = '30%'; barColor = '#5EEAD4'; }

            const expCell = `
                <div class="flex flex-col items-center justify-center h-full px-2" title="예상 개수: ${exp.toFixed(2)}">
                    <div class="w-full h-1.5 bg-teal-50 rounded-full overflow-hidden">
                        <div style="width:${width};height:100%;background-color:${barColor};border-radius:99px;"></div>
                    </div>
                </div>
            `;

            const modelCells = models.map(m => {
                const val = item.model_exp && item.model_exp[m] != null ? parseFloat(item.model_exp[m]) : 0;
                let opacity = 0.15;
                let height = '4px';
                if (val >= 1.5) { opacity = 1.0; height = '14px'; }
                else if (val >= 1.0) { opacity = 0.7; height = '10px'; }
                else if (val >= 0.5) { opacity = 0.4; height = '6px'; }

                return `<td class="px-2 py-3 text-center align-bottom" title="${m.toUpperCase()}: ${val.toFixed(2)}">
                    <div style="display:flex;align-items:flex-end;justify-content:center;height:16px;">
                        <div style="width:12px;height:${height};background-color:${MODEL_COLORS[m]};opacity:${opacity};border-radius:2px;"></div>
                    </div>
                </td>`;
            }).join('');

            html += `<tr class="border-b border-gray-100 last:border-0 hover:bg-gray-50 transition-colors">`;
            html += `<td class="px-4 py-3 font-bold text-gray-700 text-sm">${item.label}</td>`;
            html += `<td class="px-4 py-3 text-center">${expCell}</td>`;
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

        // 백엔드가 {groups: {1:{...}, 2:{...}, ...}} 형태로 반환
        const rawGroups = groupData.groups || groupData;
        const groupArray = Array.isArray(rawGroups) ? rawGroups : Object.values(rawGroups);
        if (!groupArray.length) return;

        let html = '<div class="overflow-x-auto rounded-2xl border border-gray-200 shadow-sm bg-white">';
        html += '<table class="w-full text-xs">';
        html += '<thead><tr class="bg-gray-50/50 border-b border-gray-200">';
        html += '<th class="px-4 py-3 text-left font-bold text-gray-700">구분</th>';
        html += '<th class="px-4 py-3 text-center font-bold text-indigo-600">앙상블 확률</th>';
        html += '<th class="px-4 py-3 text-center font-bold text-gray-600">번호수</th>';
        html += '<th class="px-4 py-3 text-center font-bold text-gray-600">Top15</th>';
        html += '<th class="px-4 py-3 text-center font-bold text-gray-600">평균확률</th>';
        html += '<th class="px-4 py-3 text-left font-bold text-gray-600">주요 번호</th>';
        html += '</tr></thead><tbody>';

        groupArray.forEach(g => {
            const avgProb = g.avg_prob || 0;
            let barColor = '#CCFBF1', width = '10%';
            if (avgProb >= 4.0) { width = '100%'; barColor = '#134E4A'; }
            else if (avgProb >= 3.0) { width = '75%'; barColor = '#0F766E'; }
            else if (avgProb >= 2.0) { width = '50%'; barColor = '#14B8A6'; }
            else if (avgProb >= 1.0) { width = '25%'; barColor = '#5EEAD4'; }

            const expCell = `
                <div class="flex flex-col items-center justify-center h-full px-2" title="평균확률: ${avgProb.toFixed(2)}%">
                    <div class="w-full h-1.5 bg-teal-50 rounded-full overflow-hidden">
                        <div style="width:${width};height:100%;background-color:${barColor};border-radius:99px;"></div>
                    </div>
                </div>
            `;

            const top15Nums = (g.numbers || []).filter(n => n.is_top15).map(n => n.num).slice(0, 8);
            const ballsHtml = top15Nums.map(n =>
                `<span class="inline-flex items-center justify-center w-6 h-6 rounded-full text-[10px] font-bold text-white mx-0.5" style="background:${g.color || '#6366f1'}">${n}</span>`
            ).join('') || '<span class="text-gray-400">-</span>';

            html += `<tr class="border-b border-gray-100 last:border-0 hover:bg-gray-50 transition-colors">`;
            html += `<td class="px-4 py-3 font-bold text-gray-700 text-sm">${g.label || '-'}</td>`;
            html += `<td class="px-4 py-3 text-center">${expCell}</td>`;
            html += `<td class="px-4 py-3 text-center font-mono text-gray-500">${g.count || 0}</td>`;
            html += `<td class="px-4 py-3 text-center font-mono text-gray-500">${g.top_count || 0}</td>`;
            html += `<td class="px-4 py-3 text-center font-mono text-gray-500">${avgProb.toFixed(2)}%</td>`;
            html += `<td class="px-4 py-3">${ballsHtml}</td>`;
            html += '</tr>';
        });
        html += '</tbody></table></div>';
        container.innerHTML = html;
    },

    renderHotColdAnalysis(hotColdData) {
        const container = document.getElementById('hotColdContainer');
        if (!container || !hotColdData) return;
        const MODEL_COLORS = {
            lstm: '#6366F1', xgboost: '#3B82F6', cnn: '#EC4899',
            transformer: '#F97316', markov: '#10B981', autoencoder: '#8B5CF6', gnn: '#EF4444'
        };
        const models = ['lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'];
        const MODEL_ABBR = { lstm: 'L', xgboost: 'X', cnn: 'C', transformer: 'T', markov: 'M', autoencoder: 'A', gnn: 'G' };
        const STATUS_ORDER = ['hot', 'active', 'cooling', 'cold', 'deadcold'];
        const STATUS_LABELS = { hot: '🔥 핫', active: '✅ 활성', cooling: '🌡️ 쿨링', cold: '❄️ 콜드', deadcold: '🧊 극콜드' };

        let html = '<div class="overflow-x-auto rounded-2xl border border-gray-200 shadow-sm bg-white">';
        html += '<table class="w-full text-xs">';
        html += '<thead><tr class="bg-gray-50/50 border-b border-gray-200">';
        html += '<th class="px-4 py-3 text-left font-bold text-gray-700">온도</th>';
        html += '<th class="px-4 py-3 text-center font-bold text-indigo-600">앙상블 확률</th>';
        models.forEach(m => {
            html += `<th class="px-2 py-3 text-center font-semibold text-gray-500" title="${m.toUpperCase()}">${MODEL_ABBR[m]}</th>`;
        });
        html += '<th class="px-4 py-3 text-center font-bold text-gray-600">번호수</th>';
        html += '<th class="px-4 py-3 text-center font-bold text-gray-600">Top15</th>';
        html += '<th class="px-4 py-3 text-center font-bold text-gray-600">평균Gap</th>';
        html += '</tr></thead><tbody>';

        STATUS_ORDER.forEach(status => {
            const d = hotColdData[status];
            if (!d) return;
            const avgProb = (d.avg_prob || 0) * 100;
            let barColor = '#CCFBF1', width = '10%';
            if (avgProb >= 4.0) { width = '100%'; barColor = '#134E4A'; }
            else if (avgProb >= 3.0) { width = '75%'; barColor = '#0F766E'; }
            else if (avgProb >= 2.0) { width = '50%'; barColor = '#14B8A6'; }
            else if (avgProb >= 1.0) { width = '25%'; barColor = '#5EEAD4'; }

            const expCell = `
                <div class="flex flex-col items-center justify-center h-full px-2" title="평균확률: ${avgProb.toFixed(2)}%">
                    <div class="w-full h-1.5 bg-teal-50 rounded-full overflow-hidden">
                        <div style="width:${width};height:100%;background-color:${barColor};border-radius:99px;"></div>
                    </div>
                </div>
            `;

            const modelCells = models.map(m => {
                const ms = (d.model_scores || {})[m] || {};
                const signal = ms.signal || 'neutral';
                let opacity = 0.15, height = '4px';
                if (signal === 'positive') { opacity = 1.0; height = '14px'; }
                else if (signal === 'neutral') { opacity = 0.5; height = '8px'; }
                return `<td class="px-2 py-3 text-center align-bottom" title="${m.toUpperCase()}: ${signal}">
                    <div style="display:flex;align-items:flex-end;justify-content:center;height:16px;">
                        <div style="width:12px;height:${height};background-color:${MODEL_COLORS[m]};opacity:${opacity};border-radius:2px;"></div>
                    </div>
                </td>`;
            }).join('');

            html += `<tr class="border-b border-gray-100 last:border-0 hover:bg-gray-50 transition-colors">`;
            html += `<td class="px-4 py-3 font-bold text-gray-700 text-sm">${STATUS_LABELS[status] || status}</td>`;
            html += `<td class="px-4 py-3 text-center">${expCell}</td>`;
            html += modelCells;
            html += `<td class="px-4 py-3 text-center font-mono text-gray-500">${d.count || 0}</td>`;
            html += `<td class="px-4 py-3 text-center font-mono text-gray-500">${d.top_count || 0}</td>`;
            html += `<td class="px-4 py-3 text-center font-mono text-gray-500">${d.avg_gap != null ? d.avg_gap.toFixed(1) : '-'}</td>`;
            html += '</tr>';
        });
        html += '</tbody></table></div>';
        container.innerHTML = html;
    },

    renderRegressionAnalysis(data) {
        const tbody = document.getElementById('reg-body');
        if (!tbody || !data) return;

        // 원본 데이터 저장 (정렬을 위해)
        if (!this._regressionData) this._regressionData = data;

        let displayData = [...data];
        const sort = this.state.regressionSort;

        // 정렬 화살표 초기화
        ['id', 'gap', 'str', 'avg_hit'].forEach(f => {
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

        tbody.innerHTML = displayData.map(item => {
            const targetsHtml = (item.targets || []).map(n => {
                const colorClass = this.getBallColorClass(n);
                return `<span class="ball-common ${colorClass} w-7 h-7 text-xs">${n}</span>`;
            }).join('');

            // 적중 분포 막대 (0~6)
            const hits = item.hit_dist || {};
            const distTotal = Math.max(1, Object.values(hits).reduce((a, b) => a + b, 0));
            const distributionHtml = Array.from({ length: 7 }).map((_, i) => {
                const count = hits[i] || 0;
                const pct = Math.round(count / distTotal * 100);
                const barColor = i === 0 ? '#E5E7EB' : i <= 2 ? '#9CA3AF' : i <= 4 ? '#6366f1' : '#4f46e5';
                return `<span style="display:inline-flex;flex-direction:column;align-items:center;gap:1px;margin:0 1px">
                    <span style="font-size:8px;font-weight:700;color:${i === 0 ? '#9CA3AF' : '#1F2937'}">${pct}%</span>
                    <span style="display:block;width:12px;height:${Math.max(2, Math.round(pct * 0.25))}px;background:${barColor};border-radius:2px"></span>
                    <span style="font-size:7px;color:#9CA3AF">${i}</span>
                </span>`;
            }).join('');

            return `<tr class="hover:bg-gray-50 transition-colors">
                <td class="px-3 py-3 font-bold text-gray-800">${item.id}회귀</td>
                <td class="px-3 py-3"><div class="flex gap-1 justify-center">${targetsHtml}</div></td>
                <td class="px-3 py-3 font-mono text-gray-600">${item.gap}</td>
                <td class="px-3 py-3 font-mono text-gray-600">${item.str != null ? item.str : '-'}</td>
                <td class="px-3 py-3 font-mono text-gray-500">${item.avg_hit != null ? item.avg_hit.toFixed(2) : '-'}</td>
                <td class="px-3 py-3"><div class="flex items-center justify-center">${distributionHtml}</div></td>
            </tr>`;
        }).join('');
    },

    _regSort(field) {
        if (this.state.regressionSort.field === field) {
            this.state.regressionSort.asc = !this.state.regressionSort.asc;
        } else {
            this.state.regressionSort.field = field;
            this.state.regressionSort.asc = true;
        }

        const data = this.state.analysisData ? this.state.analysisData.regression_analysis : this._regressionData;
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
            container.innerHTML = '<p class="text-sm text-slate-400 col-span-full py-8 text-center">커스텀 분석 데이터가 없습니다.</p>';
            return;
        }
        container.innerHTML = customData.map(grp => {
            const avgHit = grp.avg_hit != null ? parseFloat(grp.avg_hit).toFixed(1) : '-';
            const gap = grp.gap ?? '-';
            const str = grp.str ?? '-';
            const dist = grp.hit_dist || {};
            const distTotal = Object.values(dist).reduce((a, b) => a + b, 0) || 1;
            const gapColor = (typeof gap === 'number' && gap >= 5) ? '#EF4444' : '#64748b';
            const strColor = (typeof str === 'number' && str >= 2) ? '#6366f1' : '#64748b';
            const avgColor = parseFloat(avgHit) >= 2 ? '#6366f1' : parseFloat(avgHit) >= 1 ? '#475569' : '#9CA3AF';
            const typeMap = { static: '고정', dynamic: '동적', manual: '매뉴얼', group: '그룹', regression_overlap: '회귀중첩' };
            const typeBadge = typeMap[grp.type] || grp.type || '';
            const ballsHtml = (grp.targets || []).map(n => {
                const colorClass = self.getBallColorClass(n);
                return `<span class="ball-common ${colorClass} w-7 h-7 text-xs mx-0.5">${n}</span>`;
            }).join('');
            const distBars = [0, 1, 2, 3, 4, 5, 6].map(k => {
                const cnt = dist[k] || 0;
                const pct = Math.round(cnt / distTotal * 100);
                const barColor = k === 0 ? '#E5E7EB' : k <= 2 ? '#9CA3AF' : k <= 4 ? '#6366f1' : '#4f46e5';
                return `<span style="display:inline-flex;flex-direction:column;align-items:center;gap:1px;margin:0 2px">
                    <span style="font-size:9px;font-weight:700;color:${k === 0 ? '#9CA3AF' : '#1F2937'}">${pct}%</span>
                    <span style="display:block;width:14px;height:${Math.max(2, Math.round(pct * 0.3))}px;background:${barColor};border-radius:2px"></span>
                    <span style="font-size:8px;color:#9CA3AF">${k}</span>
                </span>`;
            }).join('');
            const modelBars = MODEL_ORDER.map(m => {
                const v = (grp.model_scores || {})[m];
                const s = v ? Math.round(v.score || 0) : 0;
                const color = MODEL_COLORS[m];
                return `<div style="display:flex;align-items:center;gap:6px;font-size:10px;margin-bottom:3px">
                    <span style="width:28px;font-weight:800;color:${color};flex-shrink:0">${MODEL_LABELS[m]}</span>
                    <div style="flex:1;height:5px;background:#F3F4F6;border-radius:3px;overflow:hidden">
                        <div style="height:100%;width:${s}%;background:${color};border-radius:3px;transition:width 0.6s ease"></div>
                    </div>
                    <span style="width:24px;text-align:right;font-weight:700;color:${color}">${s}</span>
                </div>`;
            }).join('');
            return `<div style="background:#fff;border:1px solid #e2e8f0;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.06)">
                <div style="padding:10px 14px;background:#f8fafc;border-bottom:1px solid #f1f5f9;display:flex;align-items:center;gap:6px;min-width:0">
                    <span style="font-size:9px;padding:1px 5px;background:#ede9fe;color:#6d28d9;border-radius:4px;font-weight:700;flex-shrink:0">${typeBadge}</span>
                    <span style="font-weight:700;color:#1e293b;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${grp.title || ''}">${grp.title || '커스텀'}</span>
                </div>
                <div style="padding:10px 14px 6px;display:flex;flex-wrap:wrap;gap:0;align-items:center">
                    ${ballsHtml || '<span style="font-size:11px;color:#94a3b8">대상번호 없음</span>'}
                </div>
                <div style="padding:4px 14px 8px;display:flex;gap:14px;font-size:11px;flex-wrap:wrap">
                    <span>평균적중 <strong style="font-size:13px;color:${avgColor}">${avgHit}</strong></span>
                    <span>Gap <strong style="color:${gapColor}">${gap}</strong></span>
                    <span>STR <strong style="color:${strColor}">${str}</strong></span>
                </div>
                <div style="padding:4px 14px 8px;border-top:1px solid #f8fafc">
                    <div style="font-size:9px;color:#94a3b8;margin-bottom:3px">적중 분포 (0~6개)</div>
                    <div style="display:inline-flex;align-items:flex-end;height:40px">${distBars}</div>
                </div>
                <div style="padding:8px 14px;border-top:1px solid #f1f5f9">
                    ${modelBars}
                </div>
            </div>`;
        }).join('');
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
            var analysisData = JSON.parse(data.data.analysis_data);
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

        const url = window.AI_SERVER_URL || 'https://lottolab-production-31e3.up.railway.app';
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
        content.innerHTML = '<div class="text-center text-slate-400 py-8"><div class="w-10 h-10 border-3 border-indigo-200 border-t-indigo-600 rounded-full animate-spin mx-auto mb-3"></div><p>' + number + '번 분석 중...</p></div>';
        var localInfo = '';
        if (this.state.analysisData) {
            var d = this.state.analysisData;
            var evidenceText = (d.evidence && d.evidence[number]) ? d.evidence[number] : null;
            if (!evidenceText) {
                try {
                    const url = window.AI_SERVER_URL || 'https://lottolab-production-31e3.up.railway.app';
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
                '<p class="text-sm text-gray-500">앙상블 예측 확률: <span class="font-black text-indigo-600 text-base">' + (prob !== null ? (prob * 100).toFixed(2) : '--') + '%</span></p>' +
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
                        boxClass = "bg-indigo-50/50 border-indigo-100 text-indigo-700";
                        icon = "auto_awesome";
                        iconClass = "text-indigo-500";
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
                            <span class="material-symbols-outlined text-indigo-600">psychology</span> AI 심층 분석 리포트
                        </h4>
                        ${reasonsHtml}
                    </div>
                `;
            }
            if (matrixItem && matrixItem.models) {
                var MODEL_COLORS = { lstm: '#818cf8', xgboost: '#60a5fa', cnn: '#f472b6', transformer: '#fb923c', markov: '#34d399', autoencoder: '#a855f7' };
                var MODEL_LABELS = { lstm: 'LSTM (시계열)', xgboost: 'XGBoost (패턴)', cnn: 'CNN (공간)', transformer: 'Transformer (맥락)', markov: 'Markov (전이)', autoencoder: 'Autoencoder (압축)' };
                var modelHtml = '';
                ['lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder'].forEach(mKey => {
                    var mVal = matrixItem.models[mKey] || {};
                    var score = mVal.score || 0;
                    var color = MODEL_COLORS[mKey] || '#94a3b8';
                    var label = MODEL_LABELS[mKey] || mKey;
                    modelHtml += `<div class="flex items-center gap-3 mb-2"><span class="text-[10px] font-bold w-28 text-slate-500 flex-shrink-0">${label}</span><div class="flex-1 bg-slate-100 h-1.5 rounded-full overflow-hidden"><div class="h-full rounded-full" style="width:${score}%;background:${color}"></div></div><span class="text-[10px] font-bold w-8 text-right text-slate-600">${score}</span></div>`;
                });
                localInfo += `<div class="bg-slate-50 rounded-xl p-4 border border-slate-100 mt-4"><h5 class="font-bold text-slate-600 text-xs mb-3">6개 모델별 기여도</h5>${modelHtml}</div>`;
            }
        }
        content.innerHTML = localInfo || '<div class="text-center text-slate-400 py-8"><p>분석 데이터를 먼저 실행해주세요.</p></div>';
    },

    closeXaiModal() {
        var modal = document.getElementById('xaiModal');
        if (modal) modal.classList.add('hidden');
    },

    _getBaseUrl() {
        return window.AI_SERVER_URL || 'https://lottolab-production-31e3.up.railway.app';
    },

    renderBalls(id, nums) {
        var el = document.getElementById(id);
        if (!el) return;
        if (!nums || nums.length === 0) {
            el.innerHTML = '<span class="text-slate-400 text-xs">추천 없음</span>';
            return;
        }
        var self = this;
        el.className = (el.className || '') + ' flex flex-wrap gap-2';
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
