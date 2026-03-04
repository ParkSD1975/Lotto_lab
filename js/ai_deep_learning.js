/**
 * ai_deep_learning.js  v3.2
 *
 * AI 딥러닝 심층 분석 대시보드 컨트롤러 (3-Tab 버전)
 * aiProxy.js를 통해 Python 백엔드(LangChain RAG)와 통신합니다.
 *
 * v3.2 변경점:
 *  - 로컬 폴백(가짜 분석) 제거 & DB 데이터 우선 조회 (Supabase)
 *  - 3-Tab 구조: 대시보드 / 심화분석 / 추천
 *  - 18+ 필터별 통계 카드 렌더링 (미니 분포 차트 + 근거)
 *  - 회차별 이력 관리 (드롭다운 선택)
 *  - 모든 추천에 근거(evidence) 포함
 */

const DeepLearning = {
    // ── 상태 변수 ──
    state: {
        isConnected: false,
        isAnalyzing: false,
        targetRound: 0,
        currentTab: 'dashboard',
        analysisData: null
    },

    // ── 초기화 ──
    async init() {
        const startTime = Date.now();
        console.log("🚀 Deep Learning v3.2 Initializing...");

        // 1. 핵심 정보 병렬 로드 (회차 정보, 연결 확인, 이력 리스트)
        await Promise.all([
            this.setTargetRound(),
            this.checkConnection(true),
            this.loadHistoryList()
        ]);

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

    /**
     * [신규 추가] 현재 페이지의 제목을 읽어 분석 주제(Topic)를 자동으로 추출합니다.
     */
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
        const url = window.AI_SERVER_URL || 'https://lotto-api-server.onrender.com';
        if (window.AIProxy && typeof window.AIProxy.checkHealth === 'function') {
            this.state.isConnected = await window.AIProxy.checkHealth(!isStartup);
        } else {
            try {
                const timeout = isStartup ? 3000 : 5000;
                const res = await fetch(url + '/health', { signal: AbortSignal.timeout(timeout) });
                this.state.isConnected = res.ok;
            } catch (e) {
                this.state.isConnected = false;
            }
        }
    },

    bindEvents() {
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') this.closeXaiModal();
        });
    },

    // ── 탭 전환 ──
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

    // ── 전문가 메모 DB 로드 ──
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
            return `<div style="background:#f8fafc;border:1px solid #eef2f6;border-left:3px solid #6366f1;border-radius:0 8px 8px 0;padding:12px 14px">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
                    <span style="font-size:10px;font-weight:700;color:#6366f1;text-transform:uppercase;letter-spacing:0.02em">Expert Note #${i + 1}</span>
                    <span style="font-size:10px;color:#94a3b8;font-weight:500">${dateStr}</span>
                </div>
                <div style="font-size:12.5px;color:#334155;line-height:1.7">${content}</div>
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

    // ── 메인 분석 실행 (v3.2: DB 조회 우선) ──
    async runAnalysis(forceReload = false) {
        console.log("🚀 [DeepLearning] runAnalysis() Called");
        if (this.state.isAnalyzing) return;
        this.state.isAnalyzing = true;

        this.state.expertMemos = await this._loadExpertMemos();

        // 캐시 강제 삭제 (새 로직 반영을 위해)
        try {
            const cacheKey = `ai_analysis_cache_${this.state.targetRound}`;
            localStorage.removeItem(cacheKey);
        } catch (e) {}

        this.showLoading(true, 'AI 심층 분석 데이터 조회 중...');

        try {
            // [1] DB 조회 우선
            const dbData = await this._fetchAnalysisFromDB(this.state.targetRound);
            if (dbData) {
                console.log("📦 [DeepLearning] DB에서 분석 결과 로드 성공!");
                this.setProgress(100, '완료!');
                this.state.analysisData = dbData;
                this.renderAll(dbData);
                this.state.isAnalyzing = false;
                this.showLoading(false);
                return;
            }

            // [2] DB 없으면 Python 서버 요청
            if (!this.state.isConnected) await this.checkConnection();

            if (this.state.isConnected && window.AIProxy) {
                console.log("🟢 [DeepLearning] Python 서버 실시간 분석 요청...");
                this.setProgress(30, '7중 앙상블 모델 연산 중...');
                const result = await window.AIProxy.getDeepAnalysis(this.state.targetRound);

                if (result && result.success) {
                    this.setProgress(100, '완료!');
                    this.state.analysisData = result;
                    this.renderAll(result);
                } else {
                    throw new Error("Python 분석 실패 (응답 없음)");
                }
            } else {
                // [3] 서버 미연결 & DB 없음 -> 안내 메시지
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

    // [신규] DB에서 분석 결과 조회
    async _fetchAnalysisFromDB(round) {
        if (!window.supabaseClient) return null;
        try {
            const { data, error } = await window.supabaseClient
                .from('deep_analysis_history')
                .select('analysis_data')
                .eq('target_round', round)
                .order('created_at', { ascending: false })
                .limit(1)
                .single();
            
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

    // 로컬 통계 폴백 분석 (비활성화)
    async _runLocalFallbackAnalysis() {
        console.warn("🚫 [DeepLearning] 로컬 폴백(가짜 분석) 비활성화됨.");
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

        // [수정 1] 구버전(v2)과 신버전(v3) 백엔드 응답 모두 완벽하게 호환되도록 수정
        const analysisData = result.analysis || {};
        const rangeAnalysis = analysisData.range_analysis || result.range_analysis || {};
        const matrixData = analysisData.matrix_data || result.matrix_data || [];

        // [수정 2] 모델 가중치(weights) 위치를 v3 버전에 맞게 수정하여 점수 누락 방지
        const modelWeights = (result.evidence && result.evidence.model_weights) ? result.evidence.model_weights : (result.model_weights || {});

        // 점수 정규화
        if (matrixData && matrixData.length > 0) {
            let maxTotal = 0;
            const maxScores = { lstm: 0, xgboost: 0, cnn: 0, transformer: 0, markov: 0, autoencoder: 0, gnn: 0 };
            matrixData.forEach(item => {
                if (item.total > maxTotal) maxTotal = item.total;
                ['lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'].forEach(m => {
                    // [수정 3] item.models가 비어있을 경우 발생하는 에러 방지
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
                    // [수정 4] a.models가 undefined일 때 발생하는 치명적인 렌더링 중단 에러 완벽 차단
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
                return '<span class="px-2.5 py-1 bg-indigo-50 text-indigo-700 text-[11px] font-bold rounded-md border border-indigo-100 hover:bg-indigo-100 transition-colors">' + k + '</span>';
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
                    <div class="flex items-center justify-between text-[11px] font-bold text-slate-500 mb-1">
                        <span class="text-rose-500">Hot ${hotR}%</span>
                        <span class="text-blue-500">Cold ${coldR}%</span>
                    </div>
                    <div class="w-full h-2 bg-blue-100 rounded-full overflow-hidden flex">
                        <div class="h-full bg-rose-400" style="width: ${hotR}%"></div>
                        <div class="h-full bg-blue-400" style="width: ${coldR}%"></div>
                    </div>
                    <p class="text-xs font-semibold text-slate-700 mt-2 leading-snug">${hc.trend_text || ''}</p>
                `;
            } else if (typeof hc === 'string' && hc) {
                hcUI.innerHTML = '<p class="text-sm font-semibold text-slate-700 leading-snug">' + hc + '</p>';
            } else {
                hcUI.innerHTML = '<p class="text-sm text-slate-400">데이터 없음</p>';
            }
        }
        const riskUI = document.getElementById('riskUI');
        if (riskUI) {
            const rs = strategy.risk_assessment;
            if (rs && typeof rs === 'object') {
                const score = rs.risk_score || 0;
                let color = score >= 70 ? 'text-red-500' : score >= 40 ? 'text-amber-500' : 'text-emerald-500';
                let bgColor = score >= 70 ? 'bg-red-100' : score >= 40 ? 'bg-amber-100' : 'bg-emerald-100';
                riskUI.innerHTML = `
                    <div class="flex items-end gap-2 mb-1">
                        <span class="text-2xl font-black ${color} leading-none">${score}</span>
                        <span class="text-xs font-bold px-2 py-0.5 rounded ${bgColor} ${color} mb-0.5">${rs.risk_level || ''}</span>
                    </div>
                    <p class="text-xs font-semibold text-slate-700 mt-2 leading-snug break-keep">${rs.warning_text || ''}</p>
                `;
            } else if (typeof rs === 'string' && rs) {
                riskUI.innerHTML = '<p class="text-sm font-semibold text-slate-700 leading-snug">' + rs + '</p>';
            } else {
                riskUI.innerHTML = '<p class="text-sm text-slate-400">데이터 없음</p>';
            }
        }
        const strategyUI = document.getElementById('overallStrategyUI');
        if (strategyUI) {
            const os = strategy.overall_strategy;
            if (os && typeof os === 'object') {
                let actionsHtml = (os.key_actions || []).map(action =>
                    '<span class="inline-block px-2 py-1 bg-green-50 border border-green-200 text-green-700 text-[11px] font-bold rounded mb-1 mr-1">' + action + '</span>'
                ).join('');
                strategyUI.innerHTML = '<div class="flex flex-wrap mb-1">' + actionsHtml + '</div>' +
                    '<p class="text-xs font-semibold text-slate-700 mt-1 leading-snug break-keep">' + (os.short_advice || '') + '</p>';
            } else if (typeof os === 'string' && os) {
                strategyUI.innerHTML = '<p class="text-sm font-semibold text-slate-700 leading-snug">' + os + '</p>';
            } else {
                strategyUI.innerHTML = '<p class="text-sm text-slate-400">데이터 없음</p>';
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
            html += '<div class="heatmap-cell rounded-lg flex flex-col items-center justify-center p-2 aspect-square relative" ' +
                'style="background-color: ' + bgColor + '; color: ' + textColor + '" ' +
                'onclick="window.DeepLearning.explainNumber(' + n + ')" ' +
                'title="' + n + '번: ' + pct + '%">' +
                '<span class="text-base font-black">' + n + '</span>' +
                '<span class="text-[9px] font-bold opacity-80">' + pct + '%</span>' +
                '</div>';
        }
        container.innerHTML = html;
    },

    getHeatmapColor(norm) {
        if (norm < 0.25) return 'rgba(219, 234, 254, ' + (0.6 + norm * 1.6) + ')';
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
            html += '<div class="bg-slate-50 rounded-xl border border-slate-100 overflow-hidden animate-fadeInUp">' +
                '<div class="px-4 py-3 bg-gradient-to-r ' + cfg.gradient + ' text-white flex justify-between items-center">' +
                '<div class="flex items-center gap-2">' +
                '<span class="material-symbols-outlined text-sm">' + cfg.icon + '</span>' +
                '<span class="font-bold text-sm">' + cfg.label + '</span>' +
                '</div>' +
                '<span class="text-xs font-bold bg-white/20 px-2 py-0.5 rounded-full">' + weight + '%</span>' +
                '</div>' +
                '<div class="p-4 space-y-2">';
            items.forEach(function (item) {
                var barWidth = maxProb > 0 ? (item.prob / maxProb * 100).toFixed(1) : 0;
                var ballColor = self.getBallColor(item.number);
                html += '<div class="flex items-center gap-2 group cursor-pointer" onclick="window.DeepLearning.explainNumber(' + item.number + ')">' +
                    '<span class="w-7 h-7 rounded-full flex items-center justify-center text-xs font-black text-white shadow-sm flex-shrink-0" style="background-color: ' + ballColor + '">' + item.number + '</span>' +
                    '<div class="flex-1 h-5 bg-slate-100 rounded-full overflow-hidden">' +
                    '<div class="prob-bar-fill h-full rounded-full" style="width: ' + barWidth + '%; background-color: ' + cfg.barColor + '"></div>' +
                    '</div>' +
                    '<span class="text-[11px] font-bold text-slate-500 w-14 text-right">' + (item.prob * 100).toFixed(2) + '%</span>' +
                    '</div>';
            });
            html += '</div></div>';
        });
        container.className = "grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4";
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
        let html = '<div class="overflow-x-auto rounded-xl border border-slate-200 shadow-sm">';
        html += '<table class="w-full text-xs">';
        html += '<thead><tr class="bg-slate-800 text-white">';
        html += '<th class="px-4 py-3 text-left font-bold">지표</th>';
        html += '<th class="px-3 py-3 text-center font-bold text-slate-300">앙상블<br>범위</th>';
        models.forEach(m => {
            const cfg = MODEL_CONFIG[m];
            html += `<th class="px-3 py-3 text-center font-bold" style="color:${cfg.color}">${cfg.label}<br><span class="text-slate-400 font-normal text-[10px]">예상범위</span></th>`;
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
            const rowBg = rowIdx % 2 === 0 ? 'bg-white' : 'bg-slate-50/50';
            rowIdx++;
            html += `<tr class="${rowBg} hover:bg-indigo-50/30 transition-colors border-b border-slate-100">`;
            html += `<td class="px-4 py-2.5 font-bold text-slate-700">${label}</td>`;
            html += `<td class="px-3 py-2.5 text-center font-mono font-bold text-indigo-600 bg-indigo-50/50">${ensembleRange}</td>`;
            models.forEach(m => {
                const cfg = MODEL_CONFIG[m];
                const exp = modelExp[m];
                const cellText = formatModelRatio(key, exp);
                const title = exp ? (exp.reasoning || '') : '';
                const cellHtml = cellText === '-'
                    ? '-'
                    : `<span style="color:${cfg.color}" class="font-mono font-bold">${cellText}</span>`;
                html += `<td class="px-3 py-2.5 text-center" style="background:${cfg.bg}" title="${title}">${cellHtml}</td>`;
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
        const colors = { total: '#6366f1', lstm: '#818cf8', xgboost: '#60a5fa', cnn: '#f472b6', transformer: '#fb923c', markov: '#34d399', autoencoder: '#a855f7', gnn: '#ef4444' };
        ['total', 'lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'].forEach(k => {
            const btn = document.getElementById('sort-btn-' + k);
            if (!btn) return;
            if (k === key) { btn.style.background = colors[k]; btn.style.color = '#fff'; btn.style.borderColor = colors[k]; }
            else { btn.style.background = '#fff'; btn.style.color = colors[k]; btn.style.borderColor = '#e2e8f0'; }
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
        let html = '<div class="space-y-2">';
        sorted.forEach(item => {
            const num = item.num;
            const total = Math.round(item.total || 0);
            const rawTotal = Math.round(item.raw_total || item.total || 0);
            const gap = item.gap || 0;
            const freq = item.freq ? (item.freq * 100).toFixed(1) : '-';
            const ballColor = self.getBallColor(num);
            const scoreColor = total >= 70 ? '#ef4444' : total >= 50 ? '#f59e0b' : '#94a3b8';
            const overRatio = item.over_ratio != null ? item.over_ratio : null;
            const penalty = item.penalty != null ? item.penalty : 1.0;
            const gapRatio = item.gap_ratio != null ? item.gap_ratio : null;
            const boost = item.boost != null ? item.boost : 1.0;
            const personalAvgGap = item.personal_avg_gap;
            const isExcluded = item.memo_excluded === true;
            let corrBadges = '';
            if (isExcluded) {
                corrBadges += `<span class="px-1.5 py-0.5 rounded text-[10px] font-bold bg-slate-800 text-white" title="전문가 메모에 의해 강제 제외됨">🚫 전문가 룰 제외</span> `;
            }
            if (!isExcluded && penalty < 1.0) {
                const penLabel = penalty <= 0.35 ? '⚠️ 극심과출현' : penalty <= 0.5 ? '🔴 강과출현' : '🟠 과출현';
                corrBadges += `<span class="px-1.5 py-0.5 rounded text-[10px] font-bold bg-red-100 text-red-600" title="과출현비율 ${overRatio}배 → 점수 ${Math.round((1 - penalty) * 100)}% 하향">${penLabel} ×${overRatio}</span> `;
            }
            if (!isExcluded && boost > 1.0) {
                const boostLabel = boost >= 1.45 ? '⚡ 출현임박' : boost >= 1.25 ? '🔔 주기초과' : '📈 주기근접';
                corrBadges += `<span class="px-1.5 py-0.5 rounded text-[10px] font-bold bg-emerald-100 text-emerald-700" title="Gap비율 ${gapRatio}배 (평균Gap: ${personalAvgGap}회) → 점수 ${Math.round((boost - 1) * 100)}% 상향">${boostLabel} ×${gapRatio}</span>`;
            }
            html += `<div class="${isExcluded ? 'bg-slate-50 opacity-60' : 'bg-white'} rounded-xl border ${isExcluded ? 'border-slate-300' : 'border-slate-200'} overflow-hidden shadow-sm">`;
            html += `<div class="flex items-center gap-3 px-4 py-2.5 bg-slate-50 border-b border-slate-100">`;
            html += `<span class="w-8 h-8 rounded-full flex items-center justify-center text-xs font-black text-white flex-shrink-0 cursor-pointer hover:ring-2 hover:ring-slate-300 transition-all ${isExcluded ? 'grayscale filter' : ''}" style="background:${ballColor}" onclick="window.DeepLearning.explainNumber(${num})">${num}</span>`;
            html += `<div class="flex-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">`;
            html += `<span>Gap <strong class="text-slate-700">${gap}회</strong></span>`;
            html += `<span>빈도 <strong class="text-slate-700">${freq}%</strong></span>`;
            if (rawTotal !== total) html += `<span class="text-slate-400">원점수 <s class="text-slate-400">${rawTotal}</s>→<strong class="text-slate-600">${total}</strong></span>`;
            if (corrBadges) html += corrBadges;
            html += `</div>`;
            html += `<span class="font-black text-sm" style="color:${isExcluded ? '#94a3b8' : scoreColor}">${total}점</span>`;
            html += `</div>`;
            html += `<div class="grid grid-cols-1 divide-y divide-slate-50 px-4 py-2 ${isExcluded ? 'grayscale filter opacity-70' : ''}">`;
            models.forEach(m => {
                const cfg = MODEL_CONFIG[m];
                const mData = (item.models || {})[m] || {};
                const score = mData.score != null ? mData.score : '-';
                const reason = mData.reason || mData.reasoning || '-';
                const isActive = key === m;
                html += `<div class="flex items-center gap-2 py-1.5 text-xs">`;
                html += `<span class="font-bold w-20 flex-shrink-0${isActive ? ' underline' : ''}" style="color:${cfg.color}">${cfg.label}</span>`;
                html += `<div class="flex-1 bg-slate-100 h-1.5 rounded-full overflow-hidden"><div class="h-full rounded-full" style="width:${Math.min(score === '-' ? 0 : score, 100)}%;background:${cfg.color}"></div></div>`;
                html += `<span class="font-bold w-8 text-right" style="color:${cfg.color}">${score}</span>`;
                html += `<span class="text-slate-500 flex-1 truncate ml-2" title="${reason}">${reason}</span>`;
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
            container.innerHTML = '<div class="col-span-3 text-center text-slate-300 text-sm py-8">필터 추천 데이터가 없습니다.</div>';
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
            return '<div class="bg-slate-50 rounded-xl border border-slate-100 p-4 hover:border-indigo-200 transition-colors">' +
                '<div class="flex items-center gap-2 mb-2"><span class="material-symbols-outlined text-indigo-500 text-lg">' + icon + '</span><h4 class="font-bold text-slate-800 text-sm">' + r.filter + '</h4></div>' +
                '<p class="text-indigo-700 font-black text-lg mb-2">' + valueText + '</p>' +
                '<div class="evidence-box bg-white p-2.5 rounded text-xs text-slate-600 leading-5">' + (r.evidence || '근거 데이터 없음') + '</div></div>';
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
            const scoreColor = scorePct >= 0.8 ? '#6366f1' : scorePct >= 0.5 ? '#64748b' : '#94a3b8';
            const rankBg = rank === 1 ? '#6366f1' : rank <= 3 ? '#0f172a' : '#475569';
            const ballsHtml = nums.map(n => {
                const color = self.getBallColor(n);
                const isTop = top5Set.has(n);
                return `<span style="position:relative;display:inline-flex;flex-direction:column;align-items:center;gap:1px;cursor:pointer" onclick="window.DeepLearning.explainNumber(${n})">
                    <span style="display:inline-flex;align-items:center;justify-content:center;width:30px;height:30px;border-radius:50%;background:${color};color:#fff;font-size:11px;font-weight:900;box-shadow:${isTop ? '0 0 0 2px #6366f1,0 0 0 4px #e0e7ff' : ''}">${n}</span>
                    ${isTop ? '<span style="font-size:7px;font-weight:800;color:#6366f1;line-height:1">TOP</span>' : '<span style="font-size:7px;line-height:1;opacity:0">&nbsp;</span>'}
                </span>`;
            }).join('');
            const modelBar = ['lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'].map(m => {
                const colors = { lstm: '#818cf8', xgboost: '#60a5fa', cnn: '#f472b6', transformer: '#fb923c', markov: '#34d399', autoencoder: '#a855f7', gnn: '#ef4444' };
                const labels = { lstm: 'L', xgboost: 'X', cnn: 'C', transformer: 'T', markov: 'M', autoencoder: 'A', gnn: 'G' };
                const agree = nums.some(n => modelTop[m] && modelTop[m].has(n));
                return `<span style="display:inline-flex;align-items:center;justify-content:center;width:16px;height:16px;border-radius:3px;font-size:9px;font-weight:900;background:${agree ? colors[m] : '#f1f5f9'};color:${agree ? '#fff' : '#cbd5e1'}">${labels[m]}</span>`;
            }).join('');
            return `<div style="background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:12px 16px;display:flex;align-items:center;gap:12px;flex-wrap:wrap">
                <span style="min-width:28px;height:28px;border-radius:50%;background:${rankBg};color:#fff;font-size:11px;font-weight:900;display:flex;align-items:center;justify-content:center;flex-shrink:0">#${rank}</span>
                <div style="display:flex;gap:6px;align-items:flex-end;flex-wrap:nowrap">${ballsHtml}</div>
                <div style="margin-left:auto;display:flex;flex-direction:column;align-items:flex-end;gap:4px;flex-shrink:0">
                    <div style="display:flex;gap:3px">${modelBar}</div>
                    <div style="display:flex;gap:8px;font-size:10px;color:#64748b;white-space:nowrap">
                        <span>합<b style="color:#1e293b;margin-left:2px">${sum}</b></span>
                        <span>홀<b style="color:#1e293b;margin-left:2px">${odd}</b></span>
                        <span>고<b style="color:#1e293b;margin-left:2px">${high}</b></span>
                        <span>AC<b style="color:#1e293b;margin-left:2px">${ac}</b></span>
                        <span style="color:${topIncluded.length >= 2 ? '#6366f1' : '#94a3b8'};font-weight:700">Top${topIncluded.length}</span>
                        <span style="color:${scoreColor};font-weight:700">${(score * 100).toFixed(1)}점</span>
                        ${isVerified ? '<span style="background:#dcfce7;color:#16a34a;font-size:9px;font-weight:800;padding:1px 5px;border-radius:4px;border:1px solid #bbf7d0">✓AI검증</span>' : (pipeline.rlGenerated ? '<span style="background:#fef9c3;color:#ca8a04;font-size:9px;font-weight:800;padding:1px 5px;border-radius:4px;border:1px solid #fef08a">⚠주의</span>' : '')}
                    </div>
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
            const weights = pipeline.modelWeights;
            const weightValues = Object.values(weights).map(v => v || 0);
            const maxW = weightValues.length > 0 ? Math.max(...weightValues) : 0;
            const barsHtml = Object.entries(weights).map(([name, w]) => {
                const w_val = w || 0;
                const pct = (w_val * 100).toFixed(1);
                const barW = maxW > 0 ? (w_val / maxW * 100).toFixed(1) : 0;
                const color = MODEL_COLORS[name] || '#94a3b8';
                return `<div style="display:flex;align-items:center;gap:8px;font-size:11px">
                    <span style="width:64px;color:#475569;font-weight:700;text-align:right">${MODEL_LABELS[name] || name}</span>
                    <div style="flex:1;height:14px;background:#f1f5f9;border-radius:7px;overflow:hidden">
                        <div style="width:${barW}%;height:100%;background:${color};border-radius:7px;transition:width 0.6s ease"></div>
                    </div>
                    <span style="width:36px;color:${color};font-weight:800;text-align:right">${pct}%</span>
                </div>`;
            }).join('');
            const reason = pipeline.weightReasons || '';
            condContainer.innerHTML = `
                <div class="card">
                    <div class="card-header">
                        <span class="material-symbols-outlined icon">neurology</span>
                        <h3>모델 컨디션 (Meta-Learning)</h3>
                        <span class="ml-auto text-[10px] text-slate-400 font-medium whitespace-nowrap">가중치 자동 조정</span>
                    </div>
                    <div class="card-body">
                        <div style="display:flex;flex-direction:column;gap:8px">${barsHtml}</div>
                        ${reason ? `<div style="margin-top:12px;font-size:11px;color:#64748b;border-top:1px solid #f1f5f9;padding-top:10px;line-height:1.5">${reason}</div>` : ''}
                    </div>
                </div>`;
            condContainer.style.display = 'block';
        }
        const reportContainer = document.getElementById('aiReportContainer');
        if (reportContainer && pipeline.aiReport) {
            const reportId = 'aiReportBody_' + Date.now();
            const highlighted = pipeline.aiReport
                .replace(/(\d+(?:\.\d+)?%)/g, '<b style="color:#6366f1">$1</b>')
                .replace(/(LSTM|XGBoost|CNN|Transformer|Markov|Autoencoder)/gi, '<b style="color:#0ea5e9">$1</b>')
                .replace(/(몬테카를로|강화학습|RL|GNN|Meta-Learning)/gi, '<b style="color:#8b5cf6">$1</b>')
                .replace(/(\d+(?:,\d+)*회)/g, '<b style="color:#f59e0b">$1</b>')
                .replace(/(\d{1,2}-\d{1,2})/g, '<b style="color:#10b981">$1</b>')
                .replace(/(높은|최고|우수)/g, '<b style="color:#16a34a">$1</b>')
                .replace(/(낮은|부족|없어|미실행)/g, '<b style="color:#ef4444">$1</b>');
            reportContainer.innerHTML = `
                <div style="background:linear-gradient(135deg,#f8faff,#f0f4ff);border:1px solid #c7d2fe;border-radius:12px;overflow:hidden;margin-top:16px">
                    <div style="padding:12px 16px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #e0e7ff;cursor:pointer"
                         onclick="(function(){var b=document.getElementById('${reportId}');var arr=document.getElementById('${reportId}_arr');var open=b.style.display!=='none';b.style.display=open?'none':'block';arr.textContent=open?'펼치기 ▼':'접기 ▲'})()">
                        <span style="font-size:12px;font-weight:800;color:#4338ca;display:flex;align-items:center;gap:6px">
                            <span style="width:8px;height:8px;border-radius:50%;background:#6366f1;display:inline-block;box-shadow:0 0 6px #6366f188"></span>
                            AI 종합 분석 리포트
                        </span>
                        <span id="${reportId}_arr" style="font-size:10px;color:#6366f1;font-weight:600">접기 ▲</span>
                    </div>
                    <div id="${reportId}" style="display:block;padding:14px 16px;font-size:12.5px;line-height:1.9;color:#334155">${highlighted}</div>
                </div>`;
            reportContainer.style.display = 'block';
        }
    },

    renderTailAnalysis(tailData) {
        const tbody = document.getElementById('tail-body');
        if (!tbody || !tailData) return;
        const MODEL_COLORS = { lstm: '#818cf8', xgboost: '#60a5fa', cnn: '#f472b6', transformer: '#fb923c', markov: '#34d399', autoencoder: '#a855f7', gnn: '#ef4444' };
        const models = ['lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'];
        tbody.innerHTML = tailData.map(item => {
            const exp = typeof item.exp === 'number' ? item.exp.toFixed(2) : item.exp;
            const str = item.str != null ? item.str : '-';
            const modelCells = models.map(m => {
                const mExp = item.model_exp && item.model_exp[m] != null
                    ? parseFloat(item.model_exp[m]).toFixed(2)
                    : '-';
                return `<td class="px-2 py-2.5 text-center font-mono text-xs" style="color:${MODEL_COLORS[m]}">${mExp}</td>`;
            }).join('');
            return `<tr class="hover:bg-slate-50 border-b border-slate-100">
                <td class="px-4 py-2.5 font-bold text-center">${item.tail}</td>
                <td class="px-4 py-2.5 text-center font-mono font-bold text-indigo-600">${exp}</td>
                ${modelCells}
                <td class="px-4 py-2.5 text-center font-mono">${item.gap}</td>
                <td class="px-4 py-2.5 text-center font-mono">${str}</td>
            </tr>`;
        }).join('');
    },

    renderLottoPaperAnalysis(paperData) {
        const container = document.getElementById('lottoPaperContainer');
        if (!container || !paperData) return;
        const MODEL_COLORS = { lstm: '#818cf8', xgboost: '#60a5fa', cnn: '#f472b6', transformer: '#fb923c', markov: '#34d399', autoencoder: '#a855f7', gnn: '#ef4444' };
        const MODEL_LABELS = { lstm: 'LSTM', xgboost: 'XGB', cnn: 'CNN', transformer: 'TF', markov: 'MKV', autoencoder: 'ATC', gnn: 'GNN' };
        const models = ['lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'];
        const buildTable = (title, items) => {
            let html = `<div class="mb-5">`;
            html += `<div class="text-xs font-bold text-slate-600 mb-2 px-1">${title}</div>`;
            html += '<div class="overflow-x-auto rounded-xl border border-slate-200 shadow-sm">';
            html += '<table class="w-full text-xs">';
            html += '<thead><tr class="bg-black text-white">';
            html += '<th class="px-4 py-2.5 text-left font-bold text-white">구분</th>';
            html += '<th class="px-3 py-2.5 text-center font-bold text-indigo-300">앙상블</th>';
            models.forEach(m => {
                html += `<th class="px-2 py-2.5 text-center font-bold" style="color:${MODEL_COLORS[m]}">${MODEL_LABELS[m]}</th>`;
            });
            html += '<th class="px-3 py-2.5 text-center font-bold text-white">Gap</th>';
            html += '<th class="px-3 py-2.5 text-center font-bold text-white">STR</th>';
            html += '</tr></thead><tbody>';
            items.forEach((item, idx) => {
                const rowBg = idx % 2 === 0 ? 'bg-white' : 'bg-slate-50/50';
                const exp = typeof item.exp === 'number' ? item.exp.toFixed(2) : '-';
                const modelCells = models.map(m => {
                    const mVal = item.model_exp && item.model_exp[m] != null ? parseFloat(item.model_exp[m]).toFixed(2) : '-';
                    return `<td class="px-2 py-2 text-center font-mono" style="color:${MODEL_COLORS[m]}">${mVal}</td>`;
                }).join('');
                html += `<tr class="${rowBg} hover:bg-indigo-50/20 border-b border-slate-100">`;
                html += `<td class="px-4 py-2 font-bold text-slate-700">${item.label}</td>`;
                html += `<td class="px-3 py-2 text-center font-mono font-bold text-indigo-600">${exp}</td>`;
                html += modelCells;
                html += `<td class="px-3 py-2 text-center font-mono">${item.gap != null ? item.gap : '-'}</td>`;
                html += `<td class="px-3 py-2 text-center font-mono">${item.str != null ? item.str : '-'}</td>`;
                html += '</tr>';
            });
            html += '</tbody></table></div></div>';
            return html;
        };
        let html = '';
        if (paperData.rows) html += buildTable('가로 라인 분포 (가로1~가로7)', paperData.rows);
        if (paperData.cols) html += buildTable('세로 라인 분포 (세로1~세로7)', paperData.cols);
        container.innerHTML = html || '<p class="text-sm text-slate-400 text-center py-4">데이터 없음</p>';
    },

    renderNumberBandAnalysis(bandData) {
        const container = document.getElementById('numberBandContainer');
        if (!container || !bandData || !bandData.length) return;
        const MODEL_COLORS = { lstm: '#818cf8', xgboost: '#60a5fa', cnn: '#f472b6', transformer: '#fb923c', markov: '#34d399', autoencoder: '#a855f7', gnn: '#ef4444' };
        const MODEL_LABELS = { lstm: 'LSTM', xgboost: 'XGB', cnn: 'CNN', transformer: 'TF', markov: 'MKV', autoencoder: 'ATC', gnn: 'GNN' };
        const models = ['lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'];
        let html = '<div class="overflow-x-auto rounded-xl border border-slate-200 shadow-sm">';
        html += '<table class="w-full text-xs">';
        html += '<thead><tr class="bg-slate-800 text-white">';
        html += '<th class="px-4 py-3 text-left font-bold">번호대</th>';
        html += '<th class="px-3 py-3 text-center font-bold text-slate-300">앙상블</th>';
        models.forEach(m => {
            html += `<th class="px-2 py-3 text-center font-bold" style="color:${MODEL_COLORS[m]}">${MODEL_LABELS[m]}</th>`;
        });
        html += '<th class="px-3 py-3 text-center font-bold text-slate-300">Gap</th>';
        html += '<th class="px-3 py-3 text-center font-bold text-slate-300">STR</th>';
        html += '</tr></thead><tbody>';
        bandData.forEach((item, idx) => {
            const rowBg = idx % 2 === 0 ? 'bg-white' : 'bg-slate-50/50';
            const exp = typeof item.exp === 'number' ? item.exp.toFixed(2) : '-';
            const modelCells = models.map(m => {
                const mVal = item.model_exp && item.model_exp[m] != null ? parseFloat(item.model_exp[m]).toFixed(2) : '-';
                return `<td class="px-2 py-2.5 text-center font-mono" style="color:${MODEL_COLORS[m]}">${mVal}</td>`;
            }).join('');
            html += `<tr class="${rowBg} hover:bg-indigo-50/30 transition-colors border-b border-slate-100">`;
            html += `<td class="px-4 py-2.5 font-bold text-slate-700">${item.label}</td>`;
            html += `<td class="px-3 py-2.5 text-center font-mono font-bold text-indigo-600">${exp}</td>`;
            html += modelCells;
            html += `<td class="px-3 py-2.5 text-center font-mono">${item.gap != null ? item.gap : '-'}</td>`;
            html += `<td class="px-3 py-2.5 text-center font-mono">${item.str != null ? item.str : '-'}</td>`;
            html += '</tr>';
        });
        html += '</tbody></table></div>';
        container.innerHTML = html;
    },

    renderMagicSquareAnalysis(squareData) {
        const container = document.getElementById('magicSquareContainer');
        if (!container || !squareData || !squareData.length) return;
        const MODEL_COLORS = { lstm: '#818cf8', xgboost: '#60a5fa', cnn: '#f472b6', transformer: '#fb923c', markov: '#34d399', autoencoder: '#a855f7', gnn: '#ef4444' };
        const MODEL_LABELS = { lstm: 'LSTM', xgboost: 'XGB', cnn: 'CNN', transformer: 'TF', markov: 'MKV', autoencoder: 'ATC', gnn: 'GNN' };
        const models = ['lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'];
        let html = '<div class="overflow-x-auto rounded-xl border border-slate-200 shadow-sm">';
        html += '<table class="w-full text-xs">';
        html += '<thead><tr class="bg-slate-800 text-white">';
        html += '<th class="px-4 py-3 text-left font-bold">궁</th>';
        html += '<th class="px-3 py-3 text-center font-bold text-slate-300">앙상블</th>';
        models.forEach(m => {
            html += `<th class="px-2 py-3 text-center font-bold" style="color:${MODEL_COLORS[m]}">${MODEL_LABELS[m]}</th>`;
        });
        html += '<th class="px-3 py-3 text-center font-bold text-slate-300">Gap</th>';
        html += '<th class="px-3 py-3 text-center font-bold text-slate-300">STR</th>';
        html += '</tr></thead><tbody>';
        squareData.forEach((item, idx) => {
            const rowBg = idx % 2 === 0 ? 'bg-white' : 'bg-slate-50/50';
            const exp = typeof item.exp === 'number' ? item.exp.toFixed(2) : '-';
            const modelCells = models.map(m => {
                const mVal = item.model_exp && item.model_exp[m] != null ? parseFloat(item.model_exp[m]).toFixed(2) : '-';
                return `<td class="px-2 py-2.5 text-center font-mono" style="color:${MODEL_COLORS[m]}">${mVal}</td>`;
            }).join('');
            html += `<tr class="${rowBg} hover:bg-indigo-50/30 transition-colors border-b border-slate-100">`;
            html += `<td class="px-4 py-2.5 font-bold text-slate-700">${item.label}</td>`;
            html += `<td class="px-3 py-2.5 text-center font-mono font-bold text-indigo-600">${exp}</td>`;
            html += modelCells;
            html += `<td class="px-3 py-2.5 text-center font-mono">${item.gap != null ? item.gap : '-'}</td>`;
            html += `<td class="px-3 py-2.5 text-center font-mono">${item.str != null ? item.str : '-'}</td>`;
            html += '</tr>';
        });
        html += '</tbody></table></div>';
        container.innerHTML = html;
    },

    renderMissingGroupAnalysis(data) {
        const container = document.getElementById('missingGroupContainer');
        if (!container || !data) return;
        const groups = data.groups || {};
        const self = this;
        const GC = {
            1: { label: '1~5회', sub: '최근', dot: '#1e293b', bar: '#1e293b', dimText: '#475569' },
            2: { label: '6~10회', sub: '중기', dot: '#475569', bar: '#475569', dimText: '#64748b' },
            3: { label: '11~15회', sub: '장기', dot: '#94a3b8', bar: '#94a3b8', dimText: '#94a3b8' },
            4: { label: '16회+', sub: '극장기', dot: '#cbd5e1', bar: '#cbd5e1', dimText: '#cbd5e1' },
        };
        const total = Object.values(groups).reduce((s, d) => s + (d.count || 0), 0) || 1;
        let html = '<div class="grid grid-cols-4 gap-px bg-slate-200 rounded-xl overflow-hidden mb-5 border border-slate-200">';
        for (let g = 1; g <= 4; g++) {
            const d = groups[g] || {}; const c = GC[g];
            const pct = ((d.count || 0) / total * 100).toFixed(0);
            html += `<div class="bg-white px-3 py-3 text-center">
                <div style="font-size:11px;font-weight:600;color:#1e293b;white-space:nowrap">${c.label}</div>
                <div style="font-size:10px;color:#94a3b8;margin-bottom:4px;white-space:nowrap">${c.sub}</div>
                <div style="font-size:22px;font-weight:900;color:${c.dot};line-height:1">${d.count || 0}</div>
                <div style="font-size:10px;color:#94a3b8;margin-top:2px;white-space:nowrap">${pct}% · T15 ${d.top_count || 0}</div>
            </div>`;
        }
        html += '</div>';
        html += '<div class="divide-y divide-slate-100 border border-slate-200 rounded-xl overflow-hidden">';
        for (let g = 1; g <= 4; g++) {
            const d = groups[g] || {}; const c = GC[g];
            const nums = d.numbers || [];
            if (!nums.length) continue;
            const sid = 'mg-' + g;
            const maxProb = Math.max(...nums.map(n => n.prob), 0.01);
            html += `<div>
                <button onclick="document.getElementById('${sid}').classList.toggle('hidden')"
                    class="w-full flex items-center gap-3 px-4 py-3 bg-white hover:bg-slate-50 transition text-left">
                    <span style="width:8px;height:8px;border-radius:50%;background:${c.dot};flex-shrink:0;display:inline-block"></span>
                    <span style="font-weight:700;font-size:13px;color:#1e293b;flex:1;white-space:nowrap">${c.label} <span style="font-weight:400;font-size:11px;color:#94a3b8">${c.sub}</span></span>
                    <span style="font-size:11px;color:#94a3b8;white-space:nowrap">${nums.length}개 · 평균 ${(d.avg_prob || 0).toFixed(2)}%</span>
                    <span class="material-symbols-outlined" style="font-size:16px;color:#cbd5e1">expand_more</span>
                </button>
                <div id="${sid}" class="hidden bg-slate-50/50 px-4 pb-3 pt-2">
                    <div style="display:grid;gap:6px;grid-template-columns:repeat(auto-fill,minmax(190px,1fr))">`;
            nums.forEach(item => {
                const ballColor = self.getBallColor(item.num);
                const bw = maxProb > 0 ? (item.prob / maxProb * 100).toFixed(1) : 0;
                const topBadge = item.is_top15
                    ? `<span style="font-size:9px;background:#f1f5f9;color:#475569;font-weight:700;padding:1px 4px;border-radius:3px;white-space:nowrap;flex-shrink:0">TOP</span>`
                    : `<span style="width:28px;flex-shrink:0;display:inline-block"></span>`;
                html += `<div style="display:flex;align-items:center;gap:6px;background:#fff;border-radius:8px;padding:6px 8px;cursor:pointer;border:1px solid #f1f5f9" onclick="window.DeepLearning.explainNumber(${item.num})">
                    <span style="width:26px;height:26px;border-radius:50%;background:${ballColor};display:inline-flex;align-items:center;justify-content:center;color:#fff;font-size:10px;font-weight:900;flex-shrink:0">${item.num}</span>
                    ${topBadge}
                    <span style="font-size:10px;color:#94a3b8;white-space:nowrap;flex-shrink:0">미출 <b style="color:${c.dot}">${item.missing_count}</b>회</span>
                    <div style="flex:1;height:3px;border-radius:9999px;background:#f1f5f9;min-width:30px;overflow:hidden">
                        <div style="width:${bw}%;height:100%;background:${c.bar};border-radius:9999px"></div>
                    </div>
                    <span style="font-size:11px;font-weight:700;color:#475569;white-space:nowrap;flex-shrink:0">${item.prob}%</span>
                </div>`;
            });
            html += '</div></div></div>';
        }
        html += '</div>';
        container.innerHTML = html;
    },

    renderHotColdAnalysis(hotColdData) {
        const container = document.getElementById('hotColdContainer');
        if (!container || !hotColdData) return;
        const self = this;
        const SC = {
            hot: { label: 'Hot', sub: 'Gap ≤ 2', dot: '#0f172a', accent: '#0f172a' },
            active: { label: 'Active', sub: 'Gap 3~7', dot: '#334155', accent: '#334155' },
            cooling: { label: 'Cooling', sub: 'Gap 8~15', dot: '#64748b', accent: '#64748b' },
            cold: { label: 'Cold', sub: 'Gap 16~25', dot: '#94a3b8', accent: '#94a3b8' },
            deadcold: { label: 'Dead', sub: 'Gap > 25', dot: '#cbd5e1', accent: '#cbd5e1' },
        };
        const MC = {
            lstm: '#818cf8', xgboost: '#60a5fa', cnn: '#f472b6', transformer: '#fb923c', markov: '#34d399', autoencoder: '#a855f7', gnn: '#ef4444'
        };
        const ML = { lstm: 'LSTM', xgboost: 'XGB', cnn: 'CNN', transformer: 'TF', markov: 'MKV', autoencoder: 'ATC', gnn: 'GNN' };
        const models = ['lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'];
        const statusOrder = ['hot', 'active', 'cooling', 'cold', 'deadcold'];
        const sigBadge = (sig) => {
            if (sig === 'positive') return '<span style="color:#10b981;font-weight:700;font-size:10px;white-space:nowrap">▲선호</span>';
            if (sig === 'negative') return '<span style="color:#ef4444;font-weight:700;font-size:10px;white-space:nowrap">▼기피</span>';
            return '<span style="color:#cbd5e1;font-size:10px;white-space:nowrap">—</span>';
        };
        let html = '<div class="grid grid-cols-5 gap-px bg-slate-200 rounded-xl overflow-hidden mb-5 border border-slate-200">';
        statusOrder.forEach(st => {
            const d = hotColdData[st] || {}; const c = SC[st];
            html += `<div class="bg-white px-2 py-3 text-center">
                <div style="font-size:11px;font-weight:700;color:${c.dot};white-space:nowrap">${c.label}</div>
                <div style="font-size:9px;color:#94a3b8;margin-bottom:4px;white-space:nowrap">${c.sub}</div>
                <div style="font-size:22px;font-weight:900;color:${c.dot};line-height:1">${d.count || 0}</div>
                <div style="font-size:9px;color:#94a3b8;margin-top:2px;white-space:nowrap">Gap ${d.avg_gap != null ? d.avg_gap : '-'}</div>
                <div style="font-size:9px;color:#94a3b8;white-space:nowrap">T15·${d.top_count || 0}</div>
            </div>`;
        });
        html += '</div>';
        html += '<div class="rounded-xl overflow-hidden border border-slate-200 mb-5"><div class="overflow-x-auto">';
        html += '<table class="w-full text-xs border-collapse">';
        html += '<thead><tr style="background:#0f172a">';
        html += '<th style="padding:8px 12px;text-align:left;font-weight:700;color:#fff;white-space:nowrap;font-size:11px">모델</th>';
        statusOrder.forEach(st => {
            const c = SC[st];
            html += `<th style="padding:8px;text-align:center;font-weight:700;color:${c.dot === '#0f172a' ? '#fff' : c.dot === '#334155' ? '#e2e8f0' : c.dot === '#64748b' ? '#94a3b8' : '#cbd5e1'};white-space:nowrap;font-size:11px">${c.label}<br><span style="font-size:9px;color:#475569;font-weight:400">${c.sub}</span></th>`;
        });
        html += '</tr></thead><tbody>';
        models.forEach((m, idx) => {
            const bg = idx % 2 === 0 ? '#fff' : '#f8fafc';
            html += `<tr style="background:${bg};border-bottom:1px solid #f1f5f9">`;
            html += `<td style="padding:8px 12px;font-weight:700;color:${MC[m]};white-space:nowrap">${ML[m]}</td>`;
            statusOrder.forEach(st => {
                const d = hotColdData[st] || {};
                const ms = (d.model_scores || {})[m] || {};
                const ar = ms.avg_rank != null ? ms.avg_rank : '-';
                const tc = ms.top_count != null ? ms.top_count : '-';
                html += `<td style="padding:6px 8px;text-align:center;background:${bg}">
                    ${sigBadge(ms.signal || 'neutral')}
                    <div style="font-size:9px;color:#94a3b8;white-space:nowrap">순위 <b style="color:#475569">${ar}</b></div>
                    <div style="font-size:9px;color:#94a3b8;white-space:nowrap">T15 <b style="color:#475569">${tc}</b></div>
                </td>`;
            });
            html += '</tr>';
        });
        html += '</tbody></table></div></div>';
        html += '<div class="divide-y divide-slate-100 border border-slate-200 rounded-xl overflow-hidden">';
        statusOrder.forEach(st => {
            const d = hotColdData[st] || {}; const c = SC[st];
            const details = d.num_details || [];
            if (!details.length) return;
            const sid = 'hc-' + st;
            html += `<div>
                <button onclick="document.getElementById('${sid}').classList.toggle('hidden')"
                    class="w-full flex items-center gap-3 px-4 py-3 bg-white hover:bg-slate-50 transition text-left">
                    <span style="width:8px;height:8px;border-radius:50%;background:${c.dot};flex-shrink:0;display:inline-block"></span>
                    <span style="font-weight:700;font-size:13px;color:#1e293b;flex:1;white-space:nowrap">${c.label} <span style="font-weight:400;font-size:11px;color:#94a3b8">${c.sub}</span></span>
                    <span style="font-size:11px;color:#94a3b8;white-space:nowrap">${details.length}개</span>
                    <span class="material-symbols-outlined" style="font-size:16px;color:#cbd5e1">expand_more</span>
                </button>
                <div id="${sid}" class="hidden overflow-x-auto">
                    <table class="w-full text-xs" style="border-top:1px solid #f1f5f9">
                        <thead style="background:#f8fafc">
                            <tr>
                                <th style="padding:7px 12px;text-align:center;font-weight:600;color:#64748b;white-space:nowrap">번호</th>
                                <th style="padding:7px 8px;text-align:center;font-weight:600;color:#64748b;white-space:nowrap">Gap</th>
                                <th style="padding:7px 8px;text-align:center;font-weight:600;color:#6366f1;white-space:nowrap">앙상블%</th>
                                <th style="padding:7px 6px;text-align:center;font-weight:600;color:#818cf8;white-space:nowrap">LSTM</th>
                                <th style="padding:7px 6px;text-align:center;font-weight:600;color:#60a5fa;white-space:nowrap">XGB</th>
                                <th style="padding:7px 6px;text-align:center;font-weight:600;color:#f472b6;white-space:nowrap">CNN</th>
                                <th style="padding:7px 6px;text-align:center;font-weight:600;color:#fb923c;white-space:nowrap">TF</th>
                                <th style="padding:7px 6px;text-align:center;font-weight:600;color:#34d399;white-space:nowrap">MKV</th>
                                <th style="padding:7px 6px;text-align:center;font-weight:600;color:#a855f7;white-space:nowrap">ATC</th>
                            </tr>
                        </thead>
                        <tbody>`;
            details.forEach((nd, i) => {
                const ballColor = self.getBallColor(nd.num);
                const bg = i % 2 === 0 ? '#fff' : '#f8fafc';
                const topBadge = nd.is_top15
                    ? `<span style="font-size:9px;background:#f1f5f9;color:#475569;font-weight:700;padding:1px 4px;border-radius:3px;white-space:nowrap;vertical-align:middle">TOP</span>`
                    : `<span style="display:inline-block;width:26px"></span>`;
                let modelCells = '';
                models.forEach(m => {
                    const md = (nd.models || {})[m] || {};
                    const rank = md.rank != null ? md.rank : '-';
                    const prob = md.prob != null ? md.prob : '-';
                    modelCells += `<td style="padding:6px;text-align:center;background:${bg}">
                        <span style="font-weight:700;color:${MC[m]};white-space:nowrap">${rank}위</span>
                        <div style="font-size:9px;color:#94a3b8;white-space:nowrap">${prob}%</div>
                    </td>`;
                });
                html += `<tr style="border-bottom:1px solid #f1f5f9">
                    <td style="padding:7px 12px;text-align:center;background:${bg};white-space:nowrap">
                        <span style="width:24px;height:24px;border-radius:50%;background:${ballColor};display:inline-flex;align-items:center;justify-content:center;color:#fff;font-size:10px;font-weight:900;cursor:pointer;vertical-align:middle" onclick="window.DeepLearning.explainNumber(${nd.num})">${nd.num}</span>
                        ${topBadge}
                    </td>
                    <td style="padding:7px 8px;text-align:center;font-weight:700;color:#1e293b;background:${bg};white-space:nowrap">${nd.gap}</td>
                    <td style="padding:7px 8px;text-align:center;font-weight:700;color:#6366f1;background:${bg};white-space:nowrap">${nd.ensemble_prob}%</td>
                    ${modelCells}
                </tr>`;
            });
            html += `</tbody></table></div></div>`;
        });
        html += '</div>';
        container.innerHTML = html;
    },

    renderRegressionAnalysis(regrData) {
        const tbody = document.getElementById('reg-body');
        if (!tbody || !regrData) return;
        const self = this;
        this._regrData = regrData;
        this._regrRender = render;
        function render(data) {
            const countEl = document.getElementById('reg-filter-count');
            if (countEl) countEl.textContent = `${data.length} / ${regrData.length}`;
            tbody.innerHTML = data.map((item, i) => {
                const bg = i % 2 === 0 ? '#fff' : '#f8fafc';
                const ballsHtml = (item.targets || []).map(n => {
                    const color = self.getBallColor(n);
                    return `<span style="display:inline-flex;align-items:center;justify-content:center;width:30px;height:30px;border-radius:50%;background:${color};color:#fff;font-size:11px;font-weight:900;margin:0 2px">${n}</span>`;
                }).join('');
                const avg = parseFloat(item.avg_hit ?? 0).toFixed(1);
                const avgColor = parseFloat(avg) >= 2 ? '#6366f1' : parseFloat(avg) >= 1 ? '#475569' : '#94a3b8';
                const dist = item.hit_dist || {};
                const total = Object.values(dist).reduce((a, b) => a + b, 0) || 1;
                const distBars = [0, 1, 2, 3, 4, 5, 6].map(k => {
                    const cnt = dist[k] || 0;
                    const pct = Math.round(cnt / total * 100);
                    const barColor = k === 0 ? '#e2e8f0' : k <= 2 ? '#94a3b8' : k <= 4 ? '#6366f1' : '#4f46e5';
                    return `<span style="display:inline-flex;flex-direction:column;align-items:center;gap:1px;margin:0 2px">
                        <span style="font-size:9px;font-weight:700;color:${k === 0 ? '#94a3b8' : '#1e293b'}">${pct}%</span>
                        <span style="display:block;width:14px;height:${Math.max(2, Math.round(pct * 0.3))}px;background:${barColor};border-radius:2px"></span>
                        <span style="font-size:8px;color:#94a3b8">${k}</span>
                    </span>`;
                }).join('');
                const step = item.id;
                return `<tr style="background:${bg};border-bottom:1px solid #f1f5f9;cursor:pointer" title="${step}회귀 기초분석 보기" onclick="window.open('regression.html?step=${step}','_blank')">
                    <td style="padding:6px 12px;text-align:center;font-weight:700;color:#6366f1;white-space:nowrap;background:${bg};text-decoration:underline">${step}회귀</td>
                    <td style="padding:6px 8px;text-align:center;background:${bg}">${ballsHtml}</td>
                    <td style="padding:6px 8px;text-align:center;font-weight:700;color:#475569;white-space:nowrap;background:${bg}">${item.gap}</td>
                    <td style="padding:6px 8px;text-align:center;font-weight:700;color:#475569;white-space:nowrap;background:${bg}">${item.str ?? 0}</td>
                    <td style="padding:6px 8px;text-align:center;font-weight:700;white-space:nowrap;background:${bg};color:${avgColor}">${avg}</td>
                    <td style="padding:6px 8px;text-align:center;background:${bg}">
                        <div style="display:inline-flex;align-items:flex-end;height:42px">${distBars}</div>
                    </td>
                </tr>`;
            }).join('');
        }
        render(regrData);
        this._regrSortKey = null;
        this._regrSortAsc = false;
        this._regSort = (key) => {
            const cols = ['id', 'gap', 'str', 'avg_hit'];
            if (this._regrSortKey === key) { this._regrSortAsc = !this._regrSortAsc; }
            else { this._regrSortKey = key; this._regrSortAsc = false; }
            cols.forEach(c => { const el = document.getElementById('reg-sort-arrow-' + c); if (el) el.textContent = ''; });
            const arrow = document.getElementById('reg-sort-arrow-' + key);
            if (arrow) arrow.textContent = this._regrSortAsc ? ' ▲' : ' ▼';
            const sorted = [...regrData].sort((a, b) => {
                const av = parseFloat(a[key] ?? 0), bv = parseFloat(b[key] ?? 0);
                return this._regrSortAsc ? av - bv : bv - av;
            });
            render(sorted);
        };
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
            const gapColor = (typeof gap === 'number' && gap >= 5) ? '#ef4444' : '#64748b';
            const strColor = (typeof str === 'number' && str >= 2) ? '#6366f1' : '#64748b';
            const avgColor = parseFloat(avgHit) >= 2 ? '#6366f1' : parseFloat(avgHit) >= 1 ? '#475569' : '#94a3b8';
            const typeMap = { static: '고정', dynamic: '동적', manual: '매뉴얼', group: '그룹', regression_overlap: '회귀중첩' };
            const typeBadge = typeMap[grp.type] || grp.type || '';
            const ballsHtml = (grp.targets || []).map(n => {
                const color = self.getBallColor(n);
                return `<span style="display:inline-flex;align-items:center;justify-content:center;width:30px;height:30px;border-radius:50%;background:${color};color:#fff;font-size:11px;font-weight:900;margin:0 2px">${n}</span>`;
            }).join('');
            const distBars = [0, 1, 2, 3, 4, 5, 6].map(k => {
                const cnt = dist[k] || 0;
                const pct = Math.round(cnt / distTotal * 100);
                const barColor = k === 0 ? '#e2e8f0' : k <= 2 ? '#94a3b8' : k <= 4 ? '#6366f1' : '#4f46e5';
                return `<span style="display:inline-flex;flex-direction:column;align-items:center;gap:1px;margin:0 2px">
                    <span style="font-size:9px;font-weight:700;color:${k === 0 ? '#94a3b8' : '#1e293b'}">${pct}%</span>
                    <span style="display:block;width:14px;height:${Math.max(2, Math.round(pct * 0.3))}px;background:${barColor};border-radius:2px"></span>
                    <span style="font-size:8px;color:#94a3b8">${k}</span>
                </span>`;
            }).join('');
            const modelBars = MODEL_ORDER.map(m => {
                const v = (grp.model_scores || {})[m];
                const s = v ? Math.round(v.score || 0) : 0;
                const color = MODEL_COLORS[m];
                return `<div style="display:flex;align-items:center;gap:6px;font-size:10px;margin-bottom:3px">
                    <span style="width:28px;font-weight:800;color:${color};flex-shrink:0">${MODEL_LABELS[m]}</span>
                    <div style="flex:1;height:5px;background:#f1f5f9;border-radius:3px;overflow:hidden">
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
        var select = document.getElementById('historySelect');
        if (!select || !this.state.isConnected) return;
        var url = this._getBaseUrl();
        try {
            var res = await fetch(url + '/api/deep-analysis/v3/history', {
                signal: AbortSignal.timeout(5000)
            });
            if (!res.ok) return;
            var data = await res.json();
            if (!data.success) return;
            while (select.options.length > 1) select.remove(1);
            (data.history || []).forEach(function (h) {
                var opt = document.createElement('option');
                opt.value = h.id;
                var date = new Date(h.created_at).toLocaleString('ko-KR', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
                opt.textContent = h.target_round + '회 (' + date + ') - ' + h.confidence + '%';
                select.appendChild(opt);
            });
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
        } catch (e) {
            console.error('이력 로드 실패:', e);
            alert('이력 로드 실패: ' + e.message);
        } finally {
            setTimeout(function () { DeepLearning.showLoading(false); }, 300);
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
                    const url = window.AI_SERVER_URL || 'https://lotto-api-server.onrender.com';
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
            localInfo = '<div class="space-y-4 mb-4">' +
                '<div class="flex items-center gap-3">' +
                '<span class="w-14 h-14 rounded-full flex items-center justify-center text-xl font-black text-white shadow-xl ring-4 ring-white" style="background-color: ' + this.getBallColor(number) + '">' + number + '</span>' +
                '<div class="flex-1">' +
                '<div class="flex items-center justify-between mb-1">' +
                '<p class="font-bold text-slate-900 text-lg">번호 ' + number + ' 분석결과</p>' +
                '<span class="px-3 py-1 rounded-full text-xs font-bold ' + statusClass + '">' + statusText + '</span>' +
                '</div>' +
                '<p class="text-sm text-slate-500">앙상블 예측 확률: <span class="font-black text-indigo-600 text-base">' + (prob !== null ? (prob * 100).toFixed(2) : '--') + '%</span></p>' +
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
        return window.AI_SERVER_URL || 'https://lotto-api-server.onrender.com';
    },

    getBallColor(n) {
        n = parseInt(n);
        if (n <= 10) return '#fbc400';
        if (n <= 20) return '#69c8f2';
        if (n <= 30) return '#ff7272';
        if (n <= 40) return '#aaaaaa';
        return '#b0d840';
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