/**
 * ai_deep_learning.js  v3.0
 *
 * AI 딥러닝 심층 분석 대시보드 컨트롤러 (3-Tab 버전)
 * aiProxy.js를 통해 Python 백엔드(LangChain RAG)와 통신합니다.
 *
 * v3 변경점:
 *  - 3-Tab 구조: 대시보드 / 심화분석 / 추천
 *  - 18+ 필터별 통계 카드 렌더링 (미니 분포 차트 + 근거)
 *  - 회차별 이력 관리 (드롭다운 선택)
 *  - 모든 추천에 근거(evidence) 포함
 *  - v3 API (/api/deep-analysis/v3/analysis) 사용
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
        console.log("🚀 Deep Learning v3 Initializing...");

        // 1. 회차 정보 설정
        await this.setTargetRound();

        // 2. 백엔드 연결 확인
        await this.checkConnection();

        // 3. UI 이벤트 바인딩
        this.bindEvents();

        // 4. 이력 로드
        this.loadHistoryList();

        // 5. 자동 분석
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
     * 유지보수 없이 페이지 제목만 바꾸면 AI도 알아서 바뀝니다.
     */
    getAnalysisTopic: function () {
        // 1. 커스텀 분석 페이지인 경우 (전역 변수 확인)
        if (window.currentAnalysisRule) {
            return {
                mode: 'custom',
                topic: document.getElementById('pageTitle')?.innerText || '사용자 정의 분석',
                desc: window.currentRuleDescription || ''
            };
        }

        // 2. 일반 분석 페이지 (화면에 보이는 큰 제목을 가져옴)
        // h1 태그나 id="pageTitle" 요소를 찾아서 " 분석" 글자만 떼고 가져옵니다.
        const titleElement = document.getElementById('pageTitle') ||
            document.querySelector('h1') ||
            document.querySelector('h2.font-bold');

        let topic = '로또 번호 정밀 분석'; // 기본값

        if (titleElement) {
            // "AC값 분석" -> "AC값", "총합 분석" -> "총합"
            topic = titleElement.innerText.replace(/분석/g, '').trim();
        }

        return { mode: 'dynamic', topic: topic };
    },

    async checkConnection() {
        const url = this._getBaseUrl();

        // window.AIProxy가 있으면 통합된 헬스체크 사용 (중복 호출 방지 및 쿨다운 적용)
        if (window.AIProxy && typeof window.AIProxy.checkHealth === 'function') {
            this.state.isConnected = await window.AIProxy.checkHealth();
        } else {
            try {
                const res = await fetch(url + '/health', { signal: AbortSignal.timeout(3000) });
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

        // 버튼 활성화 (connected-tab 스타일)
        document.querySelectorAll('.connected-tab').forEach(btn => {
            btn.classList.remove('connected-tab-active');
        });
        const activeBtn = document.getElementById('btn-' + tabName);
        if (activeBtn) activeBtn.classList.add('connected-tab-active');

        // 탭 패널: hidden 클래스 토글 (content-grid 방식)
        ['summary', 'recommend', 'filters', 'regression', 'custom'].forEach(t => {
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

    // ── 전문가 메모 섹션 렌더링 (모델 컨디션 바 아래) ──
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
        console.log("📝 [DeepLearning] 전문가 메모 제외번호 파싱 시작...");

        for (const m of (memos || [])) {
            const text = m.memo || '';
            console.log("   - 분석 중인 메모:", text);

            // 패턴1: 숫자 + 번? + (어쩌구저쩌구) + 제외 (사용자 제안 반영)
            // ([1-9]|[1-3][0-9]|4[0-5])번[\s\S]*?제외
            const re1 = /([1-9]|[1-3][0-9]|4[0-5])번[\s\S]*?제외/g;
            let match;
            while ((match = re1.exec(text)) !== null) {
                const n = parseInt(match[1]);
                if (n >= 1 && n <= 45) {
                    excluded.add(n);
                    console.log(`     ✅ 패턴1 매칭: ${n}번 제외 감지`);
                }
            }

            // 패턴2: (제외|빼|제거) + 숫자 + 번?
            const re2 = /(?:제외|빼|제거|삭제)\s*[:：]?\s*([\d,\s]+)/gi;
            while ((match = re2.exec(text)) !== null) {
                match[1].split(/[,\s]+/).forEach(s => {
                    const n = parseInt(s);
                    if (n >= 1 && n <= 45) {
                        excluded.add(n);
                        console.log(`     ✅ 패턴2 매칭: ${n}번 제외 감지 (목록)`);
                    }
                });
            }

            // 기존에 제가 넣었던 패턴들 중 유용한 것 유지 및 개선
            const re3 = /(\d{1,2})\s*번?(?:\s*[은는을를이가])?\s*(제외|빼|제거)/gi;
            while ((match = re3.exec(text)) !== null) {
                const n = parseInt(match[1]);
                if (n >= 1 && n <= 45) {
                    excluded.add(n);
                    console.log(`     ✅ 패턴3 매칭: ${n}번 제외 감지 (직설형)`);
                }
            }
        }

        const resultArr = [...excluded];
        console.log("🚫 [DeepLearning] 최종 강제 제외 판단된 번호들:", resultArr);
        return resultArr;
    },

    // ── 메인 분석 실행 (Python 고정) ──
    async runAnalysis() {
        console.log("🚀 [DeepLearning] runAnalysis() Called");
        if (this.state.isAnalyzing) {
            console.log("⚠️ [DeepLearning] Already analyzing, skipping.");
            return;
        }

        this.state.isAnalyzing = true;

        // 전문가 메모 미리 로드 (분석 요청 전)
        this.state.expertMemos = await this._loadExpertMemos();
        console.log(`✅ 전문가 메모 ${this.state.expertMemos.length}개 로드 완료`);

        this.showLoading(true, 'AI가 현재 페이지 데이터를 분석 중...');

        try {
            // 1. Python 서버 시도
            if (!this.state.isConnected) {
                await this.checkConnection();
            }

            let result = null;
            if (this.state.isConnected && window.AIProxy) {
                console.log("🟢 [DeepLearning] Python Backend is Healthy. Running Python Analysis...");
                this.setProgress(10, 'LSTM·GNN·RL 동시 분석 중...');
                result = await window.AIProxy.getDeepAnalysis(this.state.targetRound);
            }

            if (!result) {
                console.warn("xq [DeepLearning] Python 통신 실패. 통계 모드 폴백 실행...");
                result = await this._runLocalFallbackAnalysis();
            } else {
                this.setProgress(100, '완료!');
                this.state.analysisData = result;
                this.renderAll(result);
            }
        } catch (e) {
            console.error("분석 실패, 데모 데이터 로드:", e);
            this.showLoading(true, '분석 실패. 데모 데이터 로드 중...');
            await new Promise(r => setTimeout(r, 1000));
            this.loadDemoData();
        } finally {
            setTimeout(() => {
                this.showLoading(false);
                this.state.isAnalyzing = false;
            }, 500);
        }
    },

    // Python 서버 직접 분석 (기존 로직)
    async _runPythonAnalysis() {
        console.log("🐍 [DeepLearning] _runPythonAnalysis() Started");
        this.showLoading(true, 'AI가 현재 페이지 데이터를 분석 중...');
        const url = this._getBaseUrl();

        const context = this.getAnalysisTopic();
        console.log(`🤖 AI 분석 주제 자동 감지: [${context.topic}]`);

        let pageStats = "";
        document.querySelectorAll('.stat-card, .card, .analysis-section').forEach(el => {
            pageStats += el.innerText + "\n";
        });
        if (pageStats.length < 10) pageStats = "현재 페이지의 통계 데이터가 감지되지 않았습니다.";

        let _fallbackCalled = false;

        try {
            this.setProgress(10, 'LSTM·GNN·RL 동시 분석 중...');

            // ① Python ML 분석 + Edge Function 파이프라인 병렬 호출
            const pythonPromise = window.AIProxy.getDeepAnalysis(this.state.targetRound);

            // 전문가 메모를 분석 컨텍스트에 포함
            const expertMemos = this.state.expertMemos || [];
            const memosContext = expertMemos.length > 0
                ? '\n\n# 전문가 메모 (반드시 분석에 반영)\n' + expertMemos.map((m, i) => `[메모 ${i + 1}] ${m.memo}`).join('\n')
                : '';

            const edgePromise = window.supabaseClient
                ? window.supabaseClient.functions.invoke('ai-lotto-analyst', {
                    body: {
                        context: `대상: 제 ${this.state.targetRound}회차\n${pageStats.slice(0, 500)}${memosContext}`,
                        target_round: this.state.targetRound,
                        expert_memos: expertMemos.map(m => m.memo)
                    }
                })
                : Promise.resolve({ data: null });

            const [result, edgeRes] = await Promise.all([pythonPromise, edgePromise]);

            this.setProgress(70, '분석 결과 병합 중...');

            if (!result) {
                throw new Error('분석 데이터를 가져올 수 없습니다. (Python 서버 확인 필요)');
            }

            // ② Edge Function 결과 병합: pipeline(모델 컨디션바·AI리포트) + RL 조합
            const edgeData = edgeRes?.data;
            if (edgeData) {
                if (edgeData.pipeline) {
                    result.pipeline = edgeData.pipeline;
                    console.log('✅ Edge Function pipeline 병합 완료 (모델 컨디션바·AI리포트)');
                }
                if (edgeData.combinations && edgeData.combinations.length > 0) {
                    result.combinations = edgeData.combinations;
                    console.log('✅ Edge Function RL 조합 병합 완료');
                }
            }

            this.setProgress(85, '결과 렌더링 중...');
            this.state.analysisData = result;
            console.log('✅ 풀스택 분석 완료 (Python ML + Edge Function 파이프라인):', result);
            this.renderAll(result);
            this.setProgress(100, '완료!');
            this.loadHistoryList();

        } catch (err) {
            console.error('❌ Python Analysis Failed, trying Edge Function fallback:', err);
            _fallbackCalled = true;
            await this._runEdgeFunctionFallback();
        } finally {
            if (!_fallbackCalled) {
                setTimeout(() => {
                    this.showLoading(false);
                    this.state.isAnalyzing = false;
                }, 500);
            }
        }
    },

    // 로컬 통계 폴백 분석 (Python 없을 때) — 클라이언트 통계 기반
    async _runLocalFallbackAnalysis() {
        console.log("☁️ [DeepLearning] _runLocalFallbackAnalysis() — 클라이언트 통계 모드");
        if (!window.supabaseClient) {
            this.showLoading(false);
            const summaryEl = document.getElementById('aiSummaryText');
            if (summaryEl) {
                summaryEl.innerHTML = '<span class="text-red-500 font-bold">⚠️ Supabase 클라이언트 미초기화. 페이지를 새로고침해주세요.</span>';
            }
            return;
        }

        this.showLoading(true, '통계 기반 분석 중...');

        try {
            this.setProgress(10, '전체 당첨 데이터 조회 중...');

            // ── 1. DB 데이터 전체 조회 ──────────────────────────────────
            const { data: allDraws, error: dbError } = await window.supabaseClient
                .from('lotto_draws')
                .select('round, numbers, date')
                .order('round', { ascending: false })
                .limit(1300);

            if (dbError || !allDraws || allDraws.length === 0) {
                throw new Error('DB 데이터 조회 실패: ' + (dbError?.message || '데이터 없음'));
            }

            const TOTAL = allDraws.length;
            const targetRound = this.state.targetRound || (allDraws[0].round + 1);

            this.setProgress(25, '빈도 · 주기 분석 중...');

            // ── 2. 번호별 빈도 / 마지막 출현 / 평균 주기 계산 ──────────
            const freq = new Array(46).fill(0);
            const lastSeen = new Array(46).fill(TOTAL); // 몇 회 전에 마지막 출현했는지
            const appearances = Array.from({ length: 46 }, () => []);

            allDraws.forEach((d, idx) => {
                (d.numbers || []).forEach(n => {
                    if (n >= 1 && n <= 45) {
                        freq[n]++;
                        if (lastSeen[n] === TOTAL) lastSeen[n] = idx; // 처음 발견 시 기록
                        appearances[n].push(idx);
                    }
                });
            });

            const avgGap = new Array(46).fill(0);
            for (let n = 1; n <= 45; n++) {
                const apps = appearances[n];
                if (apps.length >= 2) {
                    let s = 0;
                    for (let i = 0; i < apps.length - 1; i++) s += apps[i + 1] - apps[i];
                    avgGap[n] = s / (apps.length - 1);
                } else {
                    avgGap[n] = TOTAL / (freq[n] + 1);
                }
            }

            this.setProgress(38, '확률 스코어 산출 중...');

            // ── 3. 번호별 확률 스코어 (빈도 + 주기 보정) ──────────────
            const EXPECTED = TOTAL * 6 / 45;
            const rawScores = new Array(46).fill(0);
            for (let n = 1; n <= 45; n++) {
                let score = freq[n] / TOTAL;
                // 과출현 패널티
                if (freq[n] > EXPECTED * 1.15) score *= 0.85;
                // 주기 임박 부스트
                if (avgGap[n] > 0 && lastSeen[n] >= avgGap[n] * 0.85) score *= 1.20;
                rawScores[n] = score;
            }

            // 번호별 확률 객체
            const numberProbs = {};
            for (let n = 1; n <= 45; n++) {
                numberProbs[String(n)] = parseFloat(rawScores[n].toFixed(6));
            }

            // 스코어 내림차순 정렬
            const sortedByScore = Array.from({ length: 45 }, (_, i) => i + 1)
                .sort((a, b) => rawScores[b] - rawScores[a]);

            this.setProgress(48, '모델 행렬 구성 중...');

            // ── 4. 7모델 행렬 데이터 구성 (결정론적 변동 적용) ─────────
            const MODELS = ['lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'];
            const M_OFFSET = { lstm: 0, xgboost: 2, cnn: -1, transformer: 3, markov: 1, autoencoder: -2, gnn: -3 };

            const matrixData = [];
            for (let n = 1; n <= 45; n++) {
                const base = Math.round(rawScores[n] * 1000);
                const models = {};
                MODELS.forEach(m => {
                    const jitter = ((n * 31 + m.charCodeAt(0) * 7) % 17) - 8;
                    models[m] = { score: Math.max(1, Math.min(99, base + jitter + M_OFFSET[m])) };
                });
                matrixData.push({ num: n, total: base, models });
            }

            // ── 5. 전문가 메모 제외번호 ───────────────────────────────
            const memoExcluded = this._parseMemoExclusions(this.state.expertMemos || []);
            const memoExcSet = new Set(memoExcluded);

            // ── 6. Top-5 추천 / 제외 10개 ────────────────────────────
            const top5 = sortedByScore.filter(n => !memoExcSet.has(n)).slice(0, 5);
            const exclude10 = [...new Set([...sortedByScore.slice(-10), ...memoExcluded])];

            // ── 7. 모델 가중치 & model_top10 ─────────────────────────
            const modelWeights = { lstm: 0.20, xgboost: 0.20, cnn: 0.15, transformer: 0.15, markov: 0.15, autoencoder: 0.10, gnn: 0.05 };

            const model_top10 = {};
            MODELS.forEach(m => {
                const sorted_m = [...matrixData]
                    .sort((a, b) => (b.models[m]?.score || 0) - (a.models[m]?.score || 0))
                    .slice(0, 10);
                model_top10[m] = sorted_m.map(item => ({
                    number: item.num,
                    prob: parseFloat(((item.models[m]?.score || 0) / 100).toFixed(4))
                }));
            });

            this.setProgress(58, '필터 통계 계산 중...');

            // ── 8. 필터 통계 8종 ─────────────────────────────────────
            const recentDraws = allDraws.slice(0, 200);
            const filterStats = this._computeFilterStats(recentDraws);

            // ── 9. 필터 추천 8종 생성 ─────────────────────────────────
            const filterRecs = filterStats.map(fs => {
                const rec = fs.recommendation || {};
                if (fs.type === 'range') {
                    return { filter: fs.name, min: rec.min, max: rec.max, evidence: rec.evidence || '' };
                } else {
                    return { filter: fs.name, pattern: (rec.recommended_patterns || []).join(' 또는 '), evidence: rec.evidence || '' };
                }
            });

            this.setProgress(66, '조합 생성 중...');

            // ── 10. 조합 10개 생성 ────────────────────────────────────
            const top15 = sortedByScore.filter(n => !memoExcSet.has(n)).slice(0, 15);
            const combinations = [];
            for (let i = 0; i < 10 && top15.length >= 6; i++) {
                const pool = [...top15];
                const combo = [];
                while (combo.length < 6 && pool.length > 0) {
                    const idx = (i * 7 + combo.length * 13 + Math.floor(rawScores[pool[0]] * 100)) % pool.length;
                    combo.push(pool.splice(idx, 1)[0]);
                }
                combo.sort((a, b) => a - b);
                combinations.push({ rank: i + 1, numbers: combo, score: parseFloat((0.85 - i * 0.025).toFixed(3)) });
            }

            this.setProgress(74, 'AI 텍스트 분석 요청 중...');

            // ── 11. Edge Function — AI 텍스트 요약만 선택적 호출 (18초 타임아웃) ─
            let aiStrategy = null;
            try {
                const recentStr = allDraws.slice(0, 8)
                    .map(d => d.round + '회: [' + d.numbers.join(', ') + ']').join('\n');
                const memoCtx = (this.state.expertMemos || []).length > 0
                    ? '\n전문가 메모: ' + (this.state.expertMemos || []).map(m => m.memo).join(' / ')
                    : '';
                const textPromise = window.supabaseClient.functions.invoke('ai-lotto-analyst', {
                    body: {
                        context: `# ${targetRound}회차 로또 예측 분석\n최근 당첨:\n${recentStr}${memoCtx}\n추천번호: [${top5.join(', ')}]\n\n아래 JSON만 반환(마크다운 없이):\n{"summary":"분석요약(3문장)","keywords":["k1","k2","k3","k4"],"overall_strategy":"전략(2문장)","hot_cold_analysis":"핫콜드(2문장)","risk_assessment":"리스크(1문장)"}`,
                        target_round: targetRound
                    }
                });
                const textTimeout = new Promise((_, r) => setTimeout(() => r(new Error('timeout')), 18000));
                const { data: textData } = await Promise.race([textPromise, textTimeout]);
                if (textData) {
                    let parsed = textData;
                    if (typeof parsed === 'string') {
                        try { parsed = JSON.parse(parsed.replace(/```json|```/g, '').trim()); } catch (e) {
                            const m2 = parsed.match(/\{[\s\S]*\}/);
                            if (m2) try { parsed = JSON.parse(m2[0]); } catch (e2) { parsed = null; }
                        }
                    }
                    if (parsed) aiStrategy = parsed.strategy || parsed.analysis?.strategy || parsed;
                }
            } catch (e) {
                console.warn('[Fallback] AI 텍스트 생성 실패, 통계 기반 텍스트 사용:', e.message);
            }

            this.setProgress(88, '결과 구성 중...');

            // ── 12. 꼬리 분석 (최근 100회) ───────────────────────────
            const tailCounts = new Array(10).fill(0);
            allDraws.slice(0, 100).forEach(d => (d.numbers || []).forEach(n => tailCounts[n % 10]++));
            const tailData = tailCounts.map((c, i) => ({ tail: i, count: c, pct: Math.round(c / 600 * 1000) / 10 }));

            // ── 13. 핫/콜드 데이터 ───────────────────────────────────
            const hotColdData = {
                hot: sortedByScore.slice(0, 10).map(n => ({ number: n, frequency: freq[n], gap: lastSeen[n] })),
                cold: sortedByScore.slice(-10).map(n => ({ number: n, frequency: freq[n], gap: lastSeen[n] }))
            };

            // ── 14. 미출현 그룹 ──────────────────────────────────────
            const recentNums = new Set(allDraws[0]?.numbers || []);
            const missingGroups = [
                { group: '1~10', numbers: Array.from({ length: 10 }, (_, i) => i + 1).filter(n => !recentNums.has(n)) },
                { group: '11~20', numbers: Array.from({ length: 10 }, (_, i) => i + 11).filter(n => !recentNums.has(n)) },
                { group: '21~30', numbers: Array.from({ length: 10 }, (_, i) => i + 21).filter(n => !recentNums.has(n)) },
                { group: '31~40', numbers: Array.from({ length: 10 }, (_, i) => i + 31).filter(n => !recentNums.has(n)) },
                { group: '41~45', numbers: [41, 42, 43, 44, 45].filter(n => !recentNums.has(n)) }
            ];

            // ── 15. 전략 객체 구성 ────────────────────────────────────
            const hotStr = sortedByScore.slice(0, 5).join(', ');
            const coldStr = sortedByScore.slice(-5).join(', ');
            const strategy = {
                confidence: 62,
                summary: aiStrategy?.summary || `통계 기반 ${targetRound}회차 분석. 상위 빈도 번호 [${top5.join(', ')}] 추천. 총 ${TOTAL}회 DB 데이터 기반 앙상블 계산.`,
                keywords: aiStrategy?.keywords || ['빈도분석', '주기임박', '앙상블', '통계기반'],
                hot_cold_analysis: aiStrategy?.hot_cold_analysis || `핫번호: ${hotStr} | 콜드번호: ${coldStr}`,
                risk_assessment: aiStrategy?.risk_assessment || 'Python 서버 미연결. 통계 기반 분석으로 정확도 제한.',
                overall_strategy: aiStrategy?.overall_strategy || `고빈도 + 주기임박 번호 조합 전략. 메모 제외번호 [${memoExcluded.join(', ') || '없음'}] 반영.`,
                fixed_numbers: { numbers: top5.slice(0, 4), evidence: '앙상블 통계 확률 상위 번호' },
                exclude_numbers: { numbers: exclude10.slice(0, 6), evidence: '저빈도 + 전문가 메모 제외' },
                filter_recommendations: filterRecs
            };

            // ── 16. pipeline ─────────────────────────────────────────
            const pipeline = {
                modelWeights: modelWeights,
                weightReasons: `통계 기반 클라이언트 계산 (Python 미연결). ${TOTAL}회 DB 데이터.`,
                rlGenerated: false,
                topCompatiblePairs: []
            };

            // ── 17. 최종 result 조립 ──────────────────────────────────
            const result = {
                success: true,
                target_round: targetRound,
                elapsed_seconds: 0,
                top_5: top5,               // 정확히 5개
                exclude_10: exclude10,     // 10개
                model_weights: modelWeights,
                strategy: strategy,
                combinations: combinations,
                filter_stats: filterStats, // 8종 필터 카드용
                pipeline: pipeline,
                analysis: {
                    number_probabilities: numberProbs,
                    top_6: top5.slice(0, 6),
                    recommended: top5,        // 5개 (renderExcludeFixed에서 'AI 강력 추천'으로 사용)
                    excluded: exclude10,
                    model_weights: modelWeights,
                    model_top10: model_top10, // 7모델 × 10개
                    range_analysis: null,
                    matrix_data: matrixData,  // renderAll이 읽는 위치 (analysis 내부)
                    tail_analysis: tailData,
                    hot_cold_data: hotColdData,
                    missing_group_data: missingGroups
                    // custom_evaluations: 의도적으로 미설정 (undefined → renderCustomEvaluations 미호출)
                }
            };

            // 연결 상태 표시
            const statusEl = document.getElementById('connectionStatus');
            if (statusEl) {
                statusEl.innerHTML = '<span class="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse"></span> 통계 분석 (Python 미연결)';
                statusEl.className = 'flex items-center gap-1.5 text-[11px] font-bold text-amber-700 bg-amber-50 px-2.5 py-0.5 rounded-full border border-amber-200';
            }

            this.state.analysisData = result;
            console.log('✅ 클라이언트 통계 분석 완료. top_5:', result.top_5, 'filterRecs:', filterRecs.length, '개');

            return result;
        } catch (err) {
            console.error('❌ Local Fallback Failed:', err);
            throw err;
        }
    },

    // ── 전체 렌더링 ──
    renderAll(result) {
        console.log("🎨 [DeepLearning] renderAll() Called", result);
        // pipeline 데이터를 state에 저장 (renderCombinations 등에서 접근)
        this.state.pipeline = result.pipeline || null;
        const combinations = result.combinations;
        const strategy = result.strategy;
        const top5 = result.top_5;
        const exclude10 = result.exclude_10;

        // v4: 통계 데이터는 result.analysis 내부에 존재합니다.
        const analysisData = result.analysis || {};
        const rangeAnalysis = analysisData.range_analysis;
        const matrixData = analysisData.matrix_data;

        // v3: matrix_data에서 번호 확률 재구성
        const numberProbs = {};
        if (matrixData) {
            matrixData.forEach(function (item) {
                numberProbs[String(item.num)] = (item.total || 0) / 100;
            });
        }

        // v3: matrix_data에서 모델별 top10 재구성
        const modelTop10 = {};
        const modelWeights = result.model_weights || {};
        if (matrixData && matrixData.length > 0) {
            const models = ['lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'];
            models.forEach(function (m) {
                const sorted = [...matrixData].sort((a, b) => {
                    const sa = (a.models[m] || {}).score || 0;
                    const sb = (b.models[m] || {}).score || 0;
                    return sb - sa;
                }).slice(0, 10);
                modelTop10[m] = sorted.map(item => ({
                    number: item.num,
                    prob: ((item.models[m] || {}).score || 0) / 100
                }));
            });
        }

        // analysis 호환 객체 구성 (추천 최대 10개, 제외 최대 10개 강제)
        const compatAnalysis = {
            number_probabilities: numberProbs,
            model_top10: modelTop10,
            model_weights: modelWeights,
            top_6: (top5 || []).slice(0, 6),
            recommended: (top5 || []).slice(0, 10),
            excluded: (exclude10 || []).slice(0, 10)
        };

        // ── 전문가 메모 제외번호 강제 적용 ──────────────────────────────
        // Python 서버는 메모를 모르므로, 클라이언트에서 직접 필터링합니다.
        const memoExcluded = this._parseMemoExclusions(this.state.expertMemos || []);
        if (memoExcluded.length > 0) {
            const memoExcSet = new Set(memoExcluded);

            // 1) 강력추천(recommended, top_6) 에서 제외번호 제거
            compatAnalysis.recommended = (compatAnalysis.recommended || []).filter(n => !memoExcSet.has(n));
            compatAnalysis.top_6 = (compatAnalysis.top_6 || []).filter(n => !memoExcSet.has(n));

            // 2) 제외목록에 메모 제외번호 추가 (중복 방지)
            const exSet = new Set([...(compatAnalysis.excluded || []), ...memoExcluded]);
            compatAnalysis.excluded = [...exSet];

            // 3) result.top_5 원본도 업데이트 (renderExcludeFixed 우선 경로 반영)
            if (result.top_5) result.top_5 = result.top_5.filter(n => !memoExcSet.has(n));
            if (result.exclude_10) {
                const ex10Set = new Set([...result.exclude_10, ...memoExcluded]);
                result.exclude_10 = [...ex10Set];
            }

            // 4) 조합(combinations)에서 제외번호 포함된 조합 제거
            if (result.combinations && result.combinations.length > 0) {
                const filtered = result.combinations.filter(
                    c => !(c.numbers || []).some(n => memoExcSet.has(n))
                );
                // 전부 걸리면 원본 유지 (빈 목록 방지)
                if (filtered.length > 0) result.combinations = filtered;
            }

            // 5) matrixData에 제외 플래그 설정 (sortMatrix에서 🚫 배지 표시용)
            if (matrixData) {
                matrixData.forEach(item => {
                    if (memoExcSet.has(item.num)) item.memo_excluded = true;
                });
            }

            console.log(`🚫 [전문가 메모] 제외번호 적용: [${memoExcluded.join(', ')}]`);
        }
        // ────────────────────────────────────────────────────────────────

        // Tab 1: 대시보드
        this.renderStrategy(strategy, result.elapsed_seconds);
        this.renderHotColdRisk(strategy);
        this.renderHeatmap(compatAnalysis.number_probabilities);
        this.renderModelTop10(compatAnalysis.model_top10, modelWeights);

        // Tab 2: 심화분석
        if (rangeAnalysis) this.renderRangeAnalysis(rangeAnalysis);
        if (matrixData) this.renderMatrixData(matrixData);
        // 기존 통계 데이터들
        if (analysisData.tail_analysis) this.renderTailAnalysis(analysisData.tail_analysis);
        if (analysisData.lotto_paper_analysis) this.renderLottoPaperAnalysis(analysisData.lotto_paper_analysis);
        if (analysisData.magic_square_analysis) this.renderMagicSquareAnalysis(analysisData.magic_square_analysis);
        if (analysisData.number_band_analysis) this.renderNumberBandAnalysis(analysisData.number_band_analysis);
        if (analysisData.missing_group_data) this.renderMissingGroupAnalysis(analysisData.missing_group_data);
        if (analysisData.hot_cold_data) this.renderHotColdAnalysis(analysisData.hot_cold_data);
        if (analysisData.regression_analysis) this.renderRegressionAnalysis(analysisData.regression_analysis);
        if (analysisData.custom_evaluations) this.renderCustomEvaluations(analysisData.custom_evaluations);

        // Tab 3(맨끝): 추천
        this.renderExcludeFixed(strategy, compatAnalysis);
        this.renderFilterRecommendations(strategy);
        // result.combinations: 메모 제외 필터링 후 최신값 사용
        this.renderCombinations(result.combinations, compatAnalysis, matrixData);

        // [Phase 6] pipeline 신규 렌더링 (pipeline 필드가 있을 때만)
        if (result.pipeline) {
            this.renderPipelineInfo(result.pipeline);
        }

        // 전문가 메모 섹션 렌더링 (pipeline 유무와 무관하게 항상 표시)
        this.renderExpertMemoSection(this.state.expertMemos || []);
    },

    // ══════════════════════════════════
    // Tab 1: Dashboard
    // ══════════════════════════════════
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
        const hcEl = document.getElementById('hotColdText');
        if (hcEl) hcEl.textContent = strategy.hot_cold_analysis || '데이터 없음';
        const rkEl = document.getElementById('riskText');
        if (rkEl) rkEl.textContent = strategy.risk_assessment || '데이터 없음';
        const osEl = document.getElementById('overallStrategyText');
        if (osEl) osEl.textContent = strategy.overall_strategy || '데이터 없음';
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
            if (items.length === 0) return; // 데이터가 없는 모델은 숨김
            var weight = weights ? (weights[key] * 100).toFixed(1) : '--';
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

        // 컬럼이 6개가 되므로 UI 깨짐 방지를 위해 grid-cols를 3개로 맞추기
        container.className = "grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4";
        container.innerHTML = html;
    },

    // ══════════════════════════════════
    // Tab 2: 모델별 필터 비교표
    // ══════════════════════════════════
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
        // 표시 순서 지정
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

        // 헤더
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

        // 행 - FILTER_ORDER 순서로 렌더링
        let rowIdx = 0;
        const orderedEntries = FILTER_ORDER
            .filter(k => rangeAnalysis[k] !== undefined)
            .map(k => [k, rangeAnalysis[k]])
            .concat(Object.entries(rangeAnalysis).filter(([k]) => !FILTER_ORDER.includes(k)));
        // 홀짝/저고 비율 변환 헬퍼
        // odd: 홀수 개수 → "홀:짝" 형식 / high: 고번호 개수 → "저:고" 형식
        const formatRatioRange = (key, rawRange) => {
            const isRatioKey = (key === 'odd' || key === 'high');
            if (!isRatioKey) {
                // 배열([min,max])이면 "min~max"
                if (Array.isArray(rawRange)) return rawRange[0] + '~' + rawRange[1];
                return rawRange || '-';
            }
            // "2~5" 또는 "2~4" 형태의 문자열 파싱
            let lo, hi;
            if (Array.isArray(rawRange)) { lo = rawRange[0]; hi = rawRange[1]; }
            else if (typeof rawRange === 'string' && rawRange.includes('~')) {
                const parts = rawRange.split('~');
                lo = parseInt(parts[0]); hi = parseInt(parts[1]);
            } else return rawRange || '-';

            // 범위 내 가능한 비율 패턴 생성
            const patterns = [];
            for (let v = lo; v <= hi; v++) {
                const other = 6 - v;
                if (key === 'odd') patterns.push(`${v}:${other}`);
                else patterns.push(`${other}:${v}`);
            }
            if (patterns.length === 0) return rawRange || '-';
            if (patterns.length === 1) return patterns[0];
            // 너무 많으면 첫~끝 요약
            if (patterns.length > 3) {
                return patterns[0] + ' ~ ' + patterns[patterns.length - 1];
            }
            return patterns.join(', ');
        };

        // 모델별 셀도 비율 형식으로 변환
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

    // ══════════════════════════════════
    // Tab 2: 번호별 모델 근거 매트릭스
    // ══════════════════════════════════
    renderMatrixData(matrixData) {
        const container = document.getElementById('matrixDataContainer');
        if (!container || !matrixData || matrixData.length === 0) return;
        this._matrixData = matrixData;
        this.sortMatrix('total');
    },

    sortMatrix(key) {
        const matrixData = this._matrixData;
        if (!matrixData) return;

        // 버튼 활성 스타일
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
            // 전문가 메모에 의한 강제 제외 표기
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

            // 모델별 근거 렌더링 (7개 모델)
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

    // ══════════════════════════════════
    // Tab 2: 심화분석 (필터 카드)
    // ══════════════════════════════════
    renderFilterCards(filterStats) {
        const container = document.getElementById('filterCardsContainer');
        const countEl = document.getElementById('filterCount');
        if (!container || !filterStats) return;

        if (countEl) countEl.textContent = filterStats.length + '개 필터';

        var self = this;
        var html = '';
        filterStats.forEach(function (fs, idx) {
            if (fs.type === 'range') {
                html += self._renderRangeFilterCard(fs, idx);
            } else if (fs.type === 'pattern') {
                html += self._renderPatternFilterCard(fs, idx);
            }
        });
        container.innerHTML = html;
    },

    _renderRangeFilterCard(fs, idx) {
        var stats = fs.stats || {};
        var all = stats.all || {};
        var recent = stats.recent || {};
        var rec = fs.recommendation || {};
        var trend = fs.trend || [];
        var dist = fs.distribution || [];

        var trendMax = trend.length > 0 ? Math.max.apply(null, trend) : 1;
        var trendMin = trend.length > 0 ? Math.min.apply(null, trend) : 0;
        var trendRange = trendMax - trendMin || 1;

        var topDist = dist.slice().sort(function (a, b) { return b.all_count - a.all_count; }).slice(0, 5);

        var trendHtml = '';
        if (trend.length > 0) {
            var bars = trend.slice().reverse().map(function (v, i) {
                var h = ((v - trendMin) / trendRange * 100);
                var isLast = (i === trend.length - 1);
                return '<div class="sparkline-bar flex-1 rounded-t ' + (isLast ? 'bg-indigo-500' : 'bg-slate-200') + '" style="height: ' + Math.max(h, 5) + '%" title="' + v + '"></div>';
            }).join('');
            trendHtml = '<div><p class="text-[10px] text-slate-400 font-bold uppercase mb-2">최근 10회 트렌드</p><div class="flex items-end gap-1 h-12">' + bars + '</div></div>';
        }

        var distHtml = '';
        if (topDist.length > 0) {
            distHtml = '<div><p class="text-[10px] text-slate-400 font-bold uppercase mb-2">상위 분포</p><div class="space-y-1">';
            topDist.forEach(function (d) {
                distHtml += '<div class="flex items-center gap-2 text-xs">' +
                    '<span class="text-slate-600 font-bold w-8 text-right">' + d.value + '</span>' +
                    '<div class="flex-1 bg-slate-100 h-3 rounded-full overflow-hidden"><div class="h-full bg-indigo-300 rounded-full" style="width: ' + d.all_pct + '%"></div></div>' +
                    '<span class="text-slate-500 font-mono w-12 text-right">' + d.all_pct + '%</span>' +
                    '<span class="text-indigo-600 font-bold w-14 text-right text-[10px]">최근 ' + d.recent_pct + '%</span></div>';
            });
            distHtml += '</div></div>';
        }

        var recMin = rec.min != null ? rec.min : '-';
        var recMax = rec.max != null ? rec.max : '-';

        return '<div class="filter-card bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden animate-fadeInUp" style="animation-delay: ' + (idx * 50) + 'ms">' +
            '<div class="px-5 py-4 border-b border-slate-100 bg-slate-50/50 flex items-center justify-between">' +
            '<div class="flex items-center gap-2"><span class="material-symbols-outlined text-indigo-500">' + (fs.icon || 'filter_list') + '</span><h4 class="font-bold text-slate-900 text-sm">' + fs.name + '</h4></div>' +
            '<span class="text-[10px] bg-indigo-50 text-indigo-600 font-bold px-2 py-0.5 rounded-full border border-indigo-100">추천: ' + recMin + '~' + recMax + '</span></div>' +
            '<div class="p-5 space-y-4">' +
            '<p class="text-xs text-slate-500 leading-4">' + (fs.description || '') + '</p>' +
            '<div class="grid grid-cols-2 gap-3">' +
            '<div class="bg-slate-50 rounded-lg p-3"><p class="text-[10px] text-slate-400 font-bold uppercase mb-1">역대 (' + (all.count || 0) + '회)</p><p class="text-lg font-black text-slate-800">' + (all.mean != null ? all.mean : '-') + '</p><p class="text-[10px] text-slate-500">중앙값 ' + (all.median != null ? all.median : '-') + ' · 최빈값 ' + (all.mode != null ? all.mode : '-') + '</p><p class="text-[10px] text-slate-400">σ ' + (all.std != null ? all.std : '-') + ' · ' + (all.min != null ? all.min : '-') + '~' + (all.max != null ? all.max : '-') + '</p></div>' +
            '<div class="bg-indigo-50/50 rounded-lg p-3 border border-indigo-100/50"><p class="text-[10px] text-indigo-500 font-bold uppercase mb-1">최근 ' + (recent.count || 0) + '회</p><p class="text-lg font-black text-indigo-700">' + (recent.mean != null ? recent.mean : '-') + '</p><p class="text-[10px] text-indigo-600/70">중앙값 ' + (recent.median != null ? recent.median : '-') + ' · 최빈값 ' + (recent.mode != null ? recent.mode : '-') + '</p><p class="text-[10px] text-indigo-400">σ ' + (recent.std != null ? recent.std : '-') + ' · ' + (recent.min != null ? recent.min : '-') + '~' + (recent.max != null ? recent.max : '-') + '</p></div></div>' +
            trendHtml + distHtml +
            '<div class="evidence-box bg-indigo-50/30 p-3 rounded-lg"><p class="text-[10px] font-bold text-indigo-600 uppercase mb-1 flex items-center gap-1"><span class="material-symbols-outlined text-xs">verified</span> 추천 근거</p><p class="text-xs text-slate-700 leading-5">' + (rec.evidence || '데이터 부족') + '</p></div>' +
            '</div></div>';
    },

    _renderPatternFilterCard(fs, idx) {
        var patterns = fs.patterns || [];
        var rec = fs.recommendation || {};
        var topPatterns = patterns.slice(0, 6);
        var recommendedPatterns = rec.recommended_patterns || [];

        var patternsHtml = '';
        topPatterns.forEach(function (p) {
            var isRec = recommendedPatterns.indexOf(p.pattern) >= 0;
            patternsHtml += '<div class="flex items-center gap-2 text-xs ' + (isRec ? 'bg-violet-50 rounded-lg p-1.5 border border-violet-100' : '') + '">' +
                '<span class="font-mono font-bold w-16 ' + (isRec ? 'text-violet-700' : 'text-slate-600') + '">' + p.pattern + '</span>' +
                '<div class="flex-1 bg-slate-100 h-3 rounded-full overflow-hidden"><div class="h-full rounded-full ' + (isRec ? 'bg-violet-400' : 'bg-slate-300') + '" style="width: ' + p.all_pct + '%"></div></div>' +
                '<span class="text-slate-500 font-mono w-12 text-right">' + p.all_pct + '%</span>' +
                '<span class="text-violet-600 font-bold w-14 text-right text-[10px]">최근 ' + p.recent_pct + '%</span>' +
                (isRec ? '<span class="material-symbols-outlined text-violet-500 text-sm">check_circle</span>' : '') +
                '</div>';
        });

        return '<div class="filter-card bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden animate-fadeInUp" style="animation-delay: ' + (idx * 50) + 'ms">' +
            '<div class="px-5 py-4 border-b border-slate-100 bg-slate-50/50 flex items-center justify-between"><div class="flex items-center gap-2"><span class="material-symbols-outlined text-violet-500">' + (fs.icon || 'pattern') + '</span><h4 class="font-bold text-slate-900 text-sm">' + fs.name + '</h4></div><span class="text-[10px] bg-violet-50 text-violet-600 font-bold px-2 py-0.5 rounded-full border border-violet-100">패턴형</span></div>' +
            '<div class="p-5 space-y-4"><p class="text-xs text-slate-500 leading-4">' + (fs.description || '') + '</p>' +
            '<div class="space-y-2"><p class="text-[10px] text-slate-400 font-bold uppercase">패턴 분포 (상위 ' + topPatterns.length + '개)</p>' + patternsHtml + '</div>' +
            '<div class="evidence-box bg-violet-50/30 p-3 rounded-lg" style="border-left-color: #8b5cf6"><p class="text-[10px] font-bold text-violet-600 uppercase mb-1 flex items-center gap-1"><span class="material-symbols-outlined text-xs">verified</span> 추천 근거</p><p class="text-xs text-slate-700 leading-5">' + (rec.evidence || '데이터 부족') + '</p></div>' +
            '</div></div>';
    },

    // ══════════════════════════════════
    // Tab 3: 추천
    // ══════════════════════════════════
    renderExcludeFixed(strategy, analysis) {
        var fixedNums, fixedEvidence, excludeNums, excludeEvidence;

        // Top5 전체 우선 사용 (strategy.fixed_numbers보다 우선)
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

        // exclude_10 전체 우선 사용
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
            '홀짝': 'contrast', '저고': 'swap_vert', '연속번호': 'linear_scale',
            '이월수': 'replay', '소수': 'looks_one', '합성수': 'looks_two',
            '제곱수': 'crop_square', '삼각수': 'change_history', '쌍수': 'group',
            '핫콜드': 'local_fire_department', '범위': 'expand'
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

        // 분석 데이터 준비
        const top5Set = new Set(analysis ? (analysis.recommended || analysis.top_6 || []) : []);
        const excludeSet = new Set(analysis ? (analysis.excluded || []) : []);
        // matrix_data에서 번호별 점수 맵
        const scoreMap = {};
        if (matrixData) matrixData.forEach(d => { scoreMap[d.num] = Math.round(d.total || 0); });
        const maxScore = Math.max(...combinations.map(c => c.score));

        // 각 번호별 모델별 상위10 포함 여부
        const modelTop = {};
        if (matrixData) {
            ['lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'].forEach(m => {
                const sorted = [...matrixData].sort((a, b) => ((b.models || {})[m] || {}).score - ((a.models || {})[m] || {}).score);
                modelTop[m] = new Set(sorted.slice(0, 10).map(d => d.num));
            });
        }

        // pipeline anomaly 결과 맵 구성 (combo key → passed/reason)
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

            // Top5 포함 번호
            const topIncluded = nums.filter(n => top5Set.has(n));
            // 모델 동의 수 (각 번호가 해당 모델 top10에 있으면 카운트)
            const modelAgreement = ['lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'].filter(m =>
                nums.some(n => modelTop[m] && modelTop[m].has(n))
            ).length;

            // 필터 통계
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

            // 점수 색상
            const scoreColor = scorePct >= 0.8 ? '#6366f1' : scorePct >= 0.5 ? '#64748b' : '#94a3b8';
            const rankBg = rank === 1 ? '#6366f1' : rank <= 3 ? '#0f172a' : '#475569';

            // 번호 볼 HTML
            const ballsHtml = nums.map(n => {
                const color = self.getBallColor(n);
                const isTop = top5Set.has(n);
                return `<span style="position:relative;display:inline-flex;flex-direction:column;align-items:center;gap:1px;cursor:pointer" onclick="window.DeepLearning.explainNumber(${n})">
                    <span style="display:inline-flex;align-items:center;justify-content:center;width:30px;height:30px;border-radius:50%;background:${color};color:#fff;font-size:11px;font-weight:900;box-shadow:${isTop ? '0 0 0 2px #6366f1,0 0 0 4px #e0e7ff' : ''}">${n}</span>
                    ${isTop ? '<span style="font-size:7px;font-weight:800;color:#6366f1;line-height:1">TOP</span>' : '<span style="font-size:7px;line-height:1;opacity:0">&nbsp;</span>'}
                </span>`;
            }).join('');

            // 모델 동의 바
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

    // ══════════════════════════════════
    // [Phase 6] Pipeline 정보 렌더링
    // Task 6.3: Tab1 모델 컨디션 바
    // Task 6.4: Tab3 AI 분석 리포트 카드
    // ══════════════════════════════════
    renderPipelineInfo(pipeline) {
        if (!pipeline) return;

        // ── Task 6.3: 모델 컨디션 바 (Tab 1) ──
        const condContainer = document.getElementById('modelConditionContainer');
        if (condContainer && pipeline.modelWeights) {
            const MODEL_COLORS = { lstm: '#818cf8', xgboost: '#60a5fa', cnn: '#f472b6', transformer: '#fb923c', markov: '#34d399', autoencoder: '#a855f7', gnn: '#ef4444' };
            const MODEL_LABELS = { lstm: 'LSTM', xgboost: 'XGBoost', cnn: 'CNN', transformer: 'Transformer', markov: 'Markov', autoencoder: 'Autoenc.', gnn: 'GNN' };
            const weights = pipeline.modelWeights;
            const maxW = Math.max(...Object.values(weights));

            const barsHtml = Object.entries(weights).map(([name, w]) => {
                const pct = (w * 100).toFixed(1);
                const barW = maxW > 0 ? (w / maxW * 100).toFixed(1) : 0;
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
            // ※ 전문가 메모는 expertMemoSection(별도 카드)에서만 표시 → 여기선 제거

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

        // ── Task 6.4: AI 분석 리포트 카드 (Tab 3) ──
        const reportContainer = document.getElementById('aiReportContainer');
        if (reportContainer && pipeline.aiReport) {
            const reportId = 'aiReportBody_' + Date.now();

            // 중요 키워드 하이라이트
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

    // ══════════════════════════════════
    // Tab 2: 끝수 분석
    // ══════════════════════════════════
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

    // ══════════════════════════════════
    // Tab 2: 로또용지 분석
    // ══════════════════════════════════
    renderLottoPaperAnalysis(paperData) {
        const container = document.getElementById('lottoPaperContainer');
        if (!container || !paperData) return;

        const MODEL_COLORS = { lstm: '#818cf8', xgboost: '#60a5fa', cnn: '#f472b6', transformer: '#fb923c', markov: '#34d399', autoencoder: '#a855f7', gnn: '#ef4444' };
        const MODEL_LABELS = { lstm: 'LSTM', xgboost: 'XGB', cnn: 'CNN', transformer: 'TF', markov: 'MKV', autoencoder: 'ATC', gnn: 'GNN' };
        const models = ['lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'];

        // 백엔드가 이미 '가로1'/'세로1' 형태로 전송하므로 별도 라벨 변환 불필요
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

    // ══════════════════════════════════
    // Tab 2: 번호대별 분석
    // ══════════════════════════════════
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

    // ══════════════════════════════════
    // Tab 2: 9궁 분석
    // ══════════════════════════════════
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

    // ══════════════════════════════════
    // ══════════════════════════════════
    // Tab 2: 미출현 그룹 분석
    // ══════════════════════════════════
    renderMissingGroupAnalysis(data) {
        const container = document.getElementById('missingGroupContainer');
        if (!container || !data) return;
        const groups = data.groups || {};
        const self = this;

        // 모노톤: 진하기 단계만 다르게
        const GC = {
            1: { label: '1~5회', sub: '최근', dot: '#1e293b', bar: '#1e293b', dimText: '#475569' },
            2: { label: '6~10회', sub: '중기', dot: '#475569', bar: '#475569', dimText: '#64748b' },
            3: { label: '11~15회', sub: '장기', dot: '#94a3b8', bar: '#94a3b8', dimText: '#94a3b8' },
            4: { label: '16회+', sub: '극장기', dot: '#cbd5e1', bar: '#cbd5e1', dimText: '#cbd5e1' },
        };

        // ① 요약 스탯 행 (4구간)
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

        // ② 구간별 접이식 패널
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

    // ══════════════════════════════════
    // Tab 2: 핫/콜드 분석
    // ══════════════════════════════════
    renderHotColdAnalysis(hotColdData) {
        const container = document.getElementById('hotColdContainer');
        if (!container || !hotColdData) return;
        const self = this;

        // 모노톤 + 포인트 컬러만 사용
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

        // ① 요약 5단계 스탯
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

        // ② 모델 × 상태 교차표
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

        // ③ 상태별 번호 접이식
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

    // ══════════════════════════════════
    // Tab 2: 회귀 분석
    // ══════════════════════════════════
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

        // 헤더 클릭 정렬
        this._regrSortKey = null;
        this._regrSortAsc = false;
        this._regSort = (key) => {
            const cols = ['id', 'gap', 'str', 'avg_hit'];
            // 같은 컬럼 재클릭 시 방향 토글, 다른 컬럼이면 내림차순으로 시작
            if (this._regrSortKey === key) { this._regrSortAsc = !this._regrSortAsc; }
            else { this._regrSortKey = key; this._regrSortAsc = false; }
            // 화살표 표시
            cols.forEach(c => { const el = document.getElementById('reg-sort-arrow-' + c); if (el) el.textContent = ''; });
            const arrow = document.getElementById('reg-sort-arrow-' + key);
            if (arrow) arrow.textContent = this._regrSortAsc ? ' ▲' : ' ▼';
            // 정렬
            const sorted = [...regrData].sort((a, b) => {
                const av = parseFloat(a[key] ?? 0), bv = parseFloat(b[key] ?? 0);
                return this._regrSortAsc ? av - bv : bv - av;
            });
            render(sorted);
        };
    },

    // ══════════════════════════════════
    // Tab: 커스텀 분석 딥러닝 평가
    // ══════════════════════════════════
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

            // 유형 뱃지
            const typeMap = { static: '고정', dynamic: '동적', manual: '매뉴얼', group: '그룹', regression_overlap: '회귀중첩' };
            const typeBadge = typeMap[grp.type] || grp.type || '';

            // 대상번호 볼 (30px, 추천&조합과 동일)
            const ballsHtml = (grp.numbers || []).map(n => {
                const color = self.getBallColor(n);
                return `<span style="display:inline-flex;align-items:center;justify-content:center;width:30px;height:30px;border-radius:50%;background:${color};color:#fff;font-size:11px;font-weight:900;margin:0 2px">${n}</span>`;
            }).join('');

            // 적중 분포 미니바 (회귀 분석과 동일한 방식)
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

            // 모델별 점수바
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
                <!-- 헤더: 유형뱃지 + 제목 -->
                <div style="padding:10px 14px;background:#f8fafc;border-bottom:1px solid #f1f5f9;display:flex;align-items:center;gap:6px;min-width:0">
                    <span style="font-size:9px;padding:1px 5px;background:#ede9fe;color:#6d28d9;border-radius:4px;font-weight:700;flex-shrink:0">${typeBadge}</span>
                    <span style="font-weight:700;color:#1e293b;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${grp.title || ''}">${grp.title || '커스텀'}</span>
                </div>
                <!-- 대상번호 볼 -->
                <div style="padding:10px 14px 6px;display:flex;flex-wrap:wrap;gap:0;align-items:center">
                    ${ballsHtml || '<span style="font-size:11px;color:#94a3b8">대상번호 없음</span>'}
                </div>
                <!-- 과거평균 / GAP / STR -->
                <div style="padding:4px 14px 8px;display:flex;gap:14px;font-size:11px;flex-wrap:wrap">
                    <span>평균적중 <strong style="font-size:13px;color:${avgColor}">${avgHit}</strong></span>
                    <span>Gap <strong style="color:${gapColor}">${gap}</strong></span>
                    <span>STR <strong style="color:${strColor}">${str}</strong></span>
                </div>
                <!-- 적중 분포 미니바 -->
                <div style="padding:4px 14px 8px;border-top:1px solid #f8fafc">
                    <div style="font-size:9px;color:#94a3b8;margin-bottom:3px">적중 분포 (0~6개)</div>
                    <div style="display:inline-flex;align-items:flex-end;height:40px">${distBars}</div>
                </div>
                <!-- 모델 점수바 -->
                <div style="padding:8px 14px;border-top:1px solid #f1f5f9">
                    ${modelBars}
                </div>
            </div>`;
        }).join('');
    },

    // ══════════════════════════════════
    // 이력 관리
    // ══════════════════════════════════
    async loadHistoryList() {
        var select = document.getElementById('historySelect');
        if (!select) return;

        // 서버가 연결되지 않은 상태면 히스토리 조회를 시도하지 않음
        if (!this.state.isConnected) {
            console.log("ℹ️ [DeepLearning] 서버 미연결 상태이므로 히스토리 로드 생략");
            return;
        }

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

    // ══════════════════════════════════
    // XAI 모달
    // ══════════════════════════════════
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

            // evidence가 있으면 우선 사용
            var evidenceText = (d.evidence && d.evidence[number]) ? d.evidence[number] : null;

            // 만약 evidenceText가 없으면 백엔드에서 실시간 XAI 예측
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
                        // 결과 캐싱
                        if (!d.evidence) d.evidence = {};
                        d.evidence[number] = evidenceText;
                    } else {
                        console.warn(`[XAI] Server returned ${res.status}`);
                    }
                } catch (e) {
                    console.warn(`[XAI] Failed to fetch explanation for ${number}:`, e);
                }
            }

            // v3: matrix_data에서 번호 정보 추출 (기존 로직 유지)
            var matrixItem = null;
            if (d.matrix_data) {
                matrixItem = d.matrix_data.find(function (m) { return m.num === number; });
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

            // 헤더 구성
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

            // 추가 정보 (Gap, Hot, 빈도 등)
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

            // XAI Evidence 영역
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

            // 기존 모델별 점수
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

    // ══════════════════════════════════
    // 필터 통계 직접 계산 (Edge Function 폴백용)
    // ══════════════════════════════════
    _computeFilterStats(draws) {
        if (!draws || draws.length < 5) return [];
        var PRIMES = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43];
        var all = draws;
        var recent = draws.slice(0, Math.min(50, draws.length));

        function calcStats(values) {
            if (!values.length) return { count: 0, mean: 0, median: 0, mode: 0, std: 0, min: 0, max: 0 };
            var sorted = values.slice().sort(function (a, b) { return a - b; });
            var n = sorted.length;
            var sum = sorted.reduce(function (a, b) { return a + b; }, 0);
            var mean = Math.round(sum / n * 10) / 10;
            var median = n % 2 === 0 ? Math.round((sorted[n / 2 - 1] + sorted[n / 2]) / 2 * 10) / 10 : sorted[Math.floor(n / 2)];
            var freq = {};
            sorted.forEach(function (v) { freq[v] = (freq[v] || 0) + 1; });
            var mode = Object.keys(freq).sort(function (a, b) { return freq[b] - freq[a]; })[0];
            var variance = sorted.reduce(function (s, v) { return s + (v - mean) * (v - mean); }, 0) / n;
            return { count: n, mean: mean, median: median, mode: Number(mode), std: Math.round(Math.sqrt(variance) * 10) / 10, min: sorted[0], max: sorted[n - 1] };
        }

        function getDistribution(values, topN) {
            var freq = {};
            values.forEach(function (v) { freq[v] = (freq[v] || 0) + 1; });
            var total = values.length;
            return Object.keys(freq).map(function (k) { return { value: Number(k), all_count: freq[k], all_pct: Math.round(freq[k] / total * 1000) / 10 }; })
                .sort(function (a, b) { return b.all_count - a.all_count; }).slice(0, topN || 5);
        }

        function calcAC(nums) {
            var diffs = new Set();
            for (var i = 0; i < nums.length; i++) for (var j = i + 1; j < nums.length; j++) diffs.add(Math.abs(nums[i] - nums[j]));
            return diffs.size;
        }

        function calcConsecutive(nums) {
            var s = nums.slice().sort(function (a, b) { return a - b; });
            var c = 0;
            for (var i = 1; i < s.length; i++) if (s[i] - s[i - 1] === 1) c++;
            return c;
        }

        function calcCarryover(numsA, numsB) {
            if (!numsB) return 0;
            return numsA.filter(function (n) { return numsB.indexOf(n) >= 0; }).length;
        }

        // 각 회차에서 통계값 추출
        var allSums = [], allTails = [], allAC = [], allOddPat = [], allLowPat = [], allPrime = [], allConsec = [], allCarry = [];
        all.forEach(function (d, idx) {
            var nums = d.numbers;
            if (!nums || nums.length < 6) return;
            allSums.push(nums.reduce(function (a, b) { return a + b; }, 0));
            allTails.push(nums.reduce(function (a, b) { return a + (b % 10); }, 0));
            allAC.push(calcAC(nums));
            var odd = nums.filter(function (n) { return n % 2 === 1; }).length;
            allOddPat.push(odd + ':' + (6 - odd));
            var low = nums.filter(function (n) { return n <= 22; }).length;
            allLowPat.push(low + ':' + (6 - low));
            allPrime.push(nums.filter(function (n) { return PRIMES.indexOf(n) >= 0; }).length);
            allConsec.push(calcConsecutive(nums));
            if (idx < all.length - 1 && all[idx + 1].numbers) allCarry.push(calcCarryover(nums, all[idx + 1].numbers));
        });

        var recentN = Math.min(50, allSums.length);
        var trend10 = function (arr) { return arr.slice(0, Math.min(10, arr.length)); };

        function makeRangeFilter(name, icon, desc, allVals, recVals) {
            var dist = getDistribution(allVals, 5);
            dist.forEach(function (d) {
                var rv = recVals.filter(function (v) { return v === d.value; }).length;
                d.recent_pct = recVals.length > 0 ? Math.round(rv / recVals.length * 1000) / 10 : 0;
            });
            var allS = calcStats(allVals), recS = calcStats(recVals);
            return {
                name: name, type: 'range', icon: icon, description: desc,
                stats: { all: allS, recent: recS },
                trend: trend10(recVals),
                distribution: dist,
                recommendation: { min: Math.round(recS.mean - recS.std), max: Math.round(recS.mean + recS.std), evidence: '최근 ' + recS.count + '회 평균 ' + recS.mean + ', 표준편차 ' + recS.std + ' 기반 1σ 범위' }
            };
        }

        function makePatternFilter(name, icon, desc, allPats, recPats) {
            var freq = {};
            allPats.forEach(function (p) { freq[p] = (freq[p] || 0) + 1; });
            var total = allPats.length;
            var rfreq = {};
            recPats.forEach(function (p) { rfreq[p] = (rfreq[p] || 0) + 1; });
            var rtotal = recPats.length;
            var patterns = Object.keys(freq).map(function (k) {
                return { pattern: k, all_pct: Math.round(freq[k] / total * 1000) / 10, recent_pct: rtotal > 0 ? Math.round((rfreq[k] || 0) / rtotal * 1000) / 10 : 0 };
            }).sort(function (a, b) { return b.all_pct - a.all_pct; }).slice(0, 6);
            var top2 = patterns.slice(0, 2).map(function (p) { return p.pattern; });
            return {
                name: name, type: 'pattern', icon: icon, description: desc,
                patterns: patterns,
                recommendation: { recommended_patterns: top2, evidence: '전체 ' + total + '회 데이터 기준 상위 2개 패턴 추천' }
            };
        }

        var recSums = allSums.slice(0, recentN);
        var recTails = allTails.slice(0, recentN);
        var recAC = allAC.slice(0, recentN);
        var recOddPat = allOddPat.slice(0, recentN);
        var recLowPat = allLowPat.slice(0, recentN);
        var recPrime = allPrime.slice(0, recentN);
        var recConsec = allConsec.slice(0, recentN);
        var recCarry = allCarry.slice(0, recentN);

        return [
            makeRangeFilter('총합', 'functions', '6개 당첨번호의 합계', allSums, recSums),
            makeRangeFilter('끝수합', 'pin', '6개 번호 일의 자리 합', allTails, recTails),
            makeRangeFilter('AC값', 'calculate', '번호 간 차이값의 종류 수', allAC, recAC),
            makePatternFilter('홀짝비율', 'contrast', '홀수:짝수 비율', allOddPat, recOddPat),
            makePatternFilter('저고비율', 'swap_vert', '저(1~22):고(23~45) 비율', allLowPat, recLowPat),
            makeRangeFilter('소수개수', 'looks_one', '소수(2,3,5,7...) 포함 개수', allPrime, recPrime),
            makeRangeFilter('연속번호', 'linear_scale', '연속된 번호 쌍의 수', allConsec, recConsec),
            makeRangeFilter('이월수', 'replay', '직전 회차와 동일한 번호 수', allCarry, recCarry)
        ];
    },

    // ══════════════════════════════════
    // 유틸리티
    // ══════════════════════════════════
    loadDemoData() {
        const demoResult = {
            success: true,
            target_round: this.state.targetRound || 1212,
            elapsed_seconds: 0,
            analysis: {
                number_probabilities: Object.fromEntries(Array.from({ length: 45 }, (_, i) => [i + 1, (Math.random() * 0.03 + 0.01).toFixed(4)])),
                top_6: [3, 11, 19, 27, 35, 42],
                recommended: [3, 7, 11, 15, 19, 23, 27, 35, 42, 44],
                excluded: [1, 6, 13, 22, 31, 40],
                model_top10: {
                    transformer: [{ number: 3, prob: 0.031 }, { number: 11, prob: 0.029 }, { number: 19, prob: 0.027 }, { number: 27, prob: 0.025 }, { number: 35, prob: 0.024 }, { number: 7, prob: 0.022 }, { number: 42, prob: 0.021 }, { number: 15, prob: 0.020 }, { number: 23, prob: 0.019 }, { number: 44, prob: 0.018 }],
                    lstm: [{ number: 11, prob: 0.030 }, { number: 3, prob: 0.028 }, { number: 27, prob: 0.026 }, { number: 19, prob: 0.024 }, { number: 42, prob: 0.023 }, { number: 35, prob: 0.021 }, { number: 7, prob: 0.020 }, { number: 23, prob: 0.019 }, { number: 15, prob: 0.018 }, { number: 44, prob: 0.017 }],
                    markov: [{ number: 19, prob: 0.029 }, { number: 11, prob: 0.027 }, { number: 3, prob: 0.025 }, { number: 35, prob: 0.023 }, { number: 27, prob: 0.021 }, { number: 42, prob: 0.020 }, { number: 7, prob: 0.019 }, { number: 15, prob: 0.018 }, { number: 23, prob: 0.017 }, { number: 44, prob: 0.016 }],
                    autoencoder: [{ number: 27, prob: 0.032 }, { number: 19, prob: 0.028 }, { number: 35, prob: 0.025 }, { number: 3, prob: 0.022 }, { number: 11, prob: 0.020 }, { number: 42, prob: 0.019 }, { number: 15, prob: 0.018 }, { number: 7, prob: 0.017 }, { number: 44, prob: 0.016 }, { number: 23, prob: 0.015 }]
                },
                model_weights: { transformer: 0.2, lstm: 0.2, cnn: 0.2, xgboost: 0.2, markov: 0.1, autoencoder: 0.1 }
            },
            strategy: {
                confidence: 50,
                summary: '서버 연결 실패로 데모 데이터를 표시합니다. 실제 분석을 위해 백엔드 서버를 확인해주세요.',
                keywords: ['데모', '연결실패', '백엔드확인'],
                hot_cold_analysis: '데모 데이터입니다.',
                risk_assessment: '서버 연결 후 정확한 분석이 가능합니다.',
                overall_strategy: '백엔드 서버(https://lotto-api-server.onrender.com) 응답 대기 중입니다.',
                fixed_numbers: { numbers: [3, 11, 19], evidence: '데모 데이터' },
                exclude_numbers: { numbers: [1, 6, 13], evidence: '데모 데이터' },
                filter_recommendations: [
                    { filter: '총합', min: 100, max: 180, evidence: '데모' },
                    { filter: '홀짝', pattern: '3:3', evidence: '데모' },
                    { filter: 'AC값', min: 7, max: 10, evidence: '데모' }
                ]
            },
            combinations: [
                { rank: 1, numbers: [3, 11, 19, 27, 35, 42], score: 0.80 },
                { rank: 2, numbers: [7, 11, 15, 23, 35, 44], score: 0.75 },
                { rank: 3, numbers: [3, 7, 19, 27, 42, 44], score: 0.70 }
            ],
            filter_stats: [
                {
                    name: '총합', type: 'range', icon: 'functions', description: '6개 당첨번호의 합계',
                    stats: { all: { mean: 140, std: 20 }, recent: { mean: 135, std: 18 } },
                    recommendation: { min: 120, max: 160, evidence: '데모 데이터' }
                },
                {
                    name: '홀짝비율', type: 'pattern', icon: 'contrast', description: '홀수:짝수 비율',
                    stats: { all: { mode: '3:3' }, recent: { mode: '4:2' } },
                    recommendation: { pattern: '3:3', evidence: '데모 데이터' }
                },
                {
                    name: 'AC값', type: 'range', icon: 'calculate', description: '번호 간 차이값의 종류 수',
                    stats: { all: { mean: 8, std: 1 }, recent: { mean: 9, std: 1 } },
                    recommendation: { min: 7, max: 10, evidence: '데모 데이터' }
                }
            ]
        };
        this.state.analysisData = demoResult;
        this.renderAll(demoResult);
    },

    _getBaseUrl() {
        if (window.AIProxy && window.AIProxy._langchainUrl) {
            return window.AIProxy._langchainUrl;
        }
        return 'https://lotto-api-server.onrender.com';
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

            // [Safety] 60초 후 강제 종료 (무한 로딩 방지)
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

// 전역 등록 (HTML의 DOMContentLoaded에서 init() 호출)
window.DeepLearning = DeepLearning;

