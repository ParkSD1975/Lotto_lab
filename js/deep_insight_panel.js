/**
 * deep_insight_panel.js  v2.0
 * 딥러닝 AI 인사이트 패널 — 전문가용 분석 UI
 *
 * 구조:
 *  [1] 모델별 예측 범위  — 게이지 없이 숫자만, 컴팩트 리스트
 *  [2] 앙상블 종합       — 7개 모델 평균 + 합의도
 *  [3] AI 분석 & 최종 제안 — 흐름분석 + 딥러닝 결과 기반 LLM 제안
 *
 * 사용법:
 *   DeepInsightPanel.render(containerId, filterKey, filterLabel)
 *   DeepInsightPanel.renderGroup(containerId, groupType)
 */
(function () {
    'use strict';

    const CACHE_KEY = 'dl_analysis_cache_v3';
    const CACHE_TTL = 60 * 60 * 1000;  // 1시간 — 같은 회차 내 값 고정
 
    let _lastContainerId = ''; // [추가] 새로고침 버튼 대응용
    
    const MODEL_META = {
        lstm:        { label: 'LSTM',        dot: '#3b82f6', tag: '시계열' },
        xgboost:     { label: 'XGBoost',     dot: '#22c55e', tag: '빈도통계' },
        cnn:         { label: 'CNN',          dot: '#f97316', tag: '공간분석' },
        transformer: { label: 'Transformer', dot: '#a855f7', tag: '주기패턴' },
        markov:      { label: 'Markov',      dot: '#ef4444', tag: '전이확률' },
        autoencoder: { label: 'AutoEncoder', dot: '#14b8a6', tag: '잠재특징' },
        gnn:         { label: 'GNN',          dot: '#6366f1', tag: '관계망' }
    };

    const MODEL_ORDER = ['lstm', 'xgboost', 'cnn', 'transformer', 'markov', 'autoencoder', 'gnn'];

    // ── 캐시 ─────────────────────────────────────────────────────────────────
    let _memCache = null;
    let _memCacheTime = 0;

    async function _getData(force = false) {
        const now = Date.now();
        // 메모리 캐시 우선 — 같은 회차면 force여도 재사용
        if (_memCache) {
            if (!force) return _memCache;
            // force=true라도 같은 회차 데이터면 유지 (백엔드 stochastic 방지)
            const fresh = await window.AIProxy.getDeepAnalysis();
            if (fresh && fresh.target_round === _memCache.target_round) return _memCache;
            if (fresh) { _memCache = fresh; _memCacheTime = now; }
            return _memCache;
        }
        // sessionStorage 확인
        if (!force) {
            try {
                const stored = sessionStorage.getItem(CACHE_KEY);
                if (stored) {
                    const p = JSON.parse(stored);
                    if ((now - p.ts) < CACHE_TTL) { _memCache = p.data; _memCacheTime = p.ts; return _memCache; }
                }
            } catch (e) {}
        }
        const data = await window.AIProxy.getDeepAnalysis();
        if (data) {
            _memCache = data; _memCacheTime = now;
            try { sessionStorage.setItem(CACHE_KEY, JSON.stringify({ data, ts: now })); } catch (e) {}
        }
        return data;
    }

    // ── 합의도 계산 ───────────────────────────────────────────────────────────
    function _computeAgreement(modelExp) {
        const vals = Object.values(modelExp);
        if (vals.length < 2) return 1;
        const mids = vals.map(e => (e.min + e.max) / 2);
        const mean = mids.reduce((a, b) => a + b, 0) / mids.length;
        const std = Math.sqrt(mids.reduce((acc, v) => acc + Math.pow(v - mean, 2), 0) / mids.length);
        return Math.max(0, Math.min(1, 1 - std / 3));
    }

    // ── 모델 아웃라이어 감지 ──────────────────────────────────────────────────
    function _findOutliers(modelExp) {
        const entries = MODEL_ORDER.map(k => ({ key: k, ...modelExp[k] })).filter(e => e.min !== undefined);
        if (entries.length < 3) return [];
        const mids = entries.map(e => (e.min + e.max) / 2);
        const mean = mids.reduce((a, b) => a + b, 0) / mids.length;
        const std = Math.sqrt(mids.reduce((acc, v) => acc + Math.pow(v - mean, 2), 0) / mids.length);
        return entries.filter((e, i) => Math.abs(mids[i] - mean) > std * 1.5).map(e => (MODEL_META[e.key] && MODEL_META[e.key].label) || e.key);
    }

    // ── 앙상블 min/max 및 합의도 계산 ───────────────────────────────────────────
    function _ensembleRange(modelExp) {
        const mins = Object.values(modelExp).map(e => e.min).filter(v => v !== undefined);
        const maxs = Object.values(modelExp).map(e => e.max).filter(v => v !== undefined);
        if (!mins.length) return { cMin: '-', cMax: '-', agreement: 0 };
        
        const cMin = Math.round(mins.reduce((a, b) => a + b, 0) / mins.length);
        const cMax = Math.round(maxs.reduce((a, b) => a + b, 0) / maxs.length);

        // 합의도 계산 (표준편차 기반)
        const mids = Object.values(modelExp).map(e => (e.min + e.max) / 2);
        const mean = mids.reduce((a, b) => a + b, 0) / mids.length;
        const variance = mids.reduce((acc, v) => acc + Math.pow(v - mean, 2), 0) / mids.length;
        const stdDev = Math.sqrt(variance);
        // 합의도 0~100 (표준편차가 작을수록 높음)
        const agreement = Math.max(0, Math.min(100, Math.round(100 - (stdDev * 5))));

        return { cMin, cMax, agreement };
    }

    // ── 통계 계산 (분석 범위 기반) ───────────────────────────────────────────
    function _calculateQuantitativeStats(filterKey, range) {
        // AppState 또는 전역 allDrawData 모두 체크 (폴백 강화)
        let rawData = (window.AppState && window.AppState.allDrawData) || window.allDrawData;
        if (!rawData || !rawData.length) return null;
        
        // 필터 키 매핑 (내부 속성명으로 변환)
        const keyMap = {
            'total_sum': 'sum',
            'sum': 'sum',
            'ac_value': 'ac',
            'ac': 'ac',
            'odd_even': 'odd_count',
            'high_low': 'high_count',
            'end_sum': 'end_sum',
            'missing_count': 'missing_count'
        };
        const dataKey = keyMap[filterKey] || filterKey;
        
        const data = rawData.slice(0, range);
        if (!data.length) return null;

        const values = data.map(d => d[dataKey]).filter(v => typeof v === 'number');
        if (!values.length) return null;

        const avg = values.reduce((a, b) => a + b, 0) / values.length;
        const min = Math.min(...values);
        const max = Math.max(...values);
        const stdDev = Math.sqrt(values.reduce((acc, v) => acc + Math.pow(v - avg, 2), 0) / values.length);

        // 추세 (최적 분석 범위 내의 상반기 vs 하반기 비교)
        const half = Math.floor(values.length / 2);
        const recentHalf = values.slice(0, half);
        const olderHalf = values.slice(half);
        if (recentHalf.length === 0 || olderHalf.length === 0) return { avg: avg.toFixed(1), min, max, stdDev: stdDev.toFixed(1), trend: '안정적', range };
        
        const recentAvg = recentHalf.reduce((a, b) => a + b, 0) / recentHalf.length;
        const olderAvg = olderHalf.reduce((a, b) => a + b, 0) / olderHalf.length;
        
        let trend = '안정적';
        const diff = recentAvg - olderAvg;
        const threshold = (max - min > 0) ? (max - min) * 0.1 : 1; 
        if (diff > threshold) trend = '상승세';
        else if (diff < -threshold) trend = '하락세';

        return { avg: avg.toFixed(1), min, max, stdDev: stdDev.toFixed(1), trend, range };
    }

    // ── LLM 비동기 분석 호출 ──────────────────────────────────────────────────
    async function _requestLLMAnalysis(aiBodyId, filterKey, filterLabel, modelExp, cMin, cMax, targetRound, strategy, analysisRange = 100) {
        const flowEl   = document.getElementById('dip-v3-content-flow');
        const patternEl = document.getElementById('dip-v3-content-pattern');
        const strategyEl = document.getElementById('dip-v3-content-strategy');

        if (!flowEl || !patternEl || !strategyEl) return;

        // 1. 통계 계산 및 UI 업데이트 (패턴 분석 섹션 상단에 즉시 표시)
        const stats = _calculateQuantitativeStats(filterKey, analysisRange);
        if (stats) {
            const statsHTML = `
                <div style="background:rgba(241, 245, 249, 0.5); border:1px solid #e2e8f0; border-radius:12px; padding:12px; margin-bottom:12px; display:flex; flex-wrap:wrap; gap:10px; align-items:center;">
                    <div style="font-size:0.75rem; color:#64748b; font-weight:700; width:100%; border-bottom:1px solid #f1f5f9; padding-bottom:4px; margin-bottom:4px">
                        ${analysisRange}회 분석 범위 통계 요약
                    </div>
                    <div style="flex:1; min-width:80px">
                        <div style="font-size:0.7rem; color:#94a3b8">평균</div>
                        <div style="font-size:0.9rem; font-weight:800; color:#1e293b">${stats.avg}</div>
                    </div>
                    <div style="flex:1; min-width:80px">
                        <div style="font-size:0.7rem; color:#94a3b8">범위(Min~Max)</div>
                        <div style="font-size:0.9rem; font-weight:800; color:#1e293b">${stats.min}~${stats.max}</div>
                    </div>
                    <div style="flex:1; min-width:80px">
                        <div style="font-size:0.7rem; color:#94a3b8">표준편차</div>
                        <div style="font-size:0.9rem; font-weight:800; color:#1e293b">±${stats.stdDev}</div>
                    </div>
                    <div style="flex:1; min-width:80px">
                        <div style="font-size:0.7rem; color:#94a3b8">최근 추세</div>
                        <div style="font-size:0.9rem; font-weight:800; color:${stats.trend==='상승세'?'#ef4444':(stats.trend==='하락세'?'#3b82f6':'#1e293b')}">${stats.trend}</div>
                    </div>
                </div>
            `;
            patternEl.innerHTML = statsHTML + `<div id="dip-pattern-llm-text" class="italic text-gray-400" style="font-size:0.85rem">데이터의 통계적 패턴을 심층 해석 중입니다...</div>`;
        }

        const modelSummary = MODEL_ORDER
            .filter(k => modelExp[k])
            .map(k => `${MODEL_META[k].label}: ${modelExp[k].min}~${modelExp[k].max}`)
            .join(', ');

        const prompt =
`# Role: 최고의 로또 통계 분석 전문가이자 데이터 과학자
# Target: ${targetRound || ''}회차 ${filterLabel} 심층 분석 보고서
# Data Context:
- 분석 범위: 최근 ${analysisRange}회차 전수 데이터 로드 완료
- 통계 분석 결과: 평균 ${stats?.avg || 'N/A'}, 범위 ${stats?.min || 'N/A'}~${stats?.max || 'N/A'}, 표준편차 ${stats?.stdDev || 'N/A'}, 추세 ${stats?.trend || 'N/A'}
- 7개 개별 모델 예측: ${modelSummary}
- AI 앙상블 종합 예측 범위: ${cMin}~${cMax}
- 현재 전략 가이드 (기본): ${(strategy.overall_strategy && strategy.overall_strategy.short_advice) || 'N/A'}

# 분석 요청 사항:
1. [흐름진단]: 최근 ${analysisRange}회차의 통계 지표와 현재 AI 모델들의 예측치를 교차 검증하여, 현재 ${filterLabel} 구간이 "과열(과출현)" 상태인지 "침체(미출현)" 상태인지 진단하고, 반등 가능성을 전문가답게 분석하세요.
2. [패턴분석]: 위에서 제공된 통계 지표(특히 표준편차와 최근 추세)를 기반으로, 이번 회차에서 발생할 확률이 가장 높은 '패턴의 변곡점'을 제시하세요. 사람이 직관적으로 놓치기 쉬운 숫자의 침묵 상태를 명확히 짚어주어야 합니다.
3. [필승공략]: 모든 AI 모델의 합의점(Ensemble)과 방금 계산된 통계적 추세를 융합하여, ${targetRound}회차에서 사용자가 반드시 적용해야 할 **최종 필터 범위**를 확정하고 확신 있는 가이드를 제공하세요.

# 주의사항:
- 강조할 수치나 키워드는 반드시 {{good:값}} (유리), {{info:값}} (관찰), {{warn:위험}} (주의) 태그로 감싸세요.
- 답변은 전문적이고 단호해야 하며, "발생 가능성이 매우 높습니다"와 같이 근거에 기반한 확신 있는 종결 어미를 사용하세요.`;

        try {
            const result = await window.AIProxy.invoke({
                prompt,
                analysisType: filterKey,
                targetRound: targetRound || 0,
                responseStyle: 'expert'
            });
            const text = _extractLLMText(result, filterKey);
            if (text) {
                const parts = _splitPremiumText(text);
                flowEl.innerHTML     = _cleanLLMText(parts.flow);
                
                // 패턴 분석 섹션은 통계 UI를 유지하면서 텍스트만 업데이트
                const patternTextEl = document.getElementById('dip-pattern-llm-text');
                if (patternTextEl) {
                    patternTextEl.innerHTML = _cleanLLMText(parts.pattern);
                    patternTextEl.classList.remove('italic', 'text-gray-400');
                    patternTextEl.style.color = '#475569';
                } else {
                    patternEl.innerHTML = _cleanLLMText(parts.pattern);
                }
                
                strategyEl.innerHTML = _cleanLLMText(parts.strategy);
                return;
            }
        } catch (e) { /* fallback */ }

        const advice = (strategy.overall_strategy && strategy.overall_strategy.short_advice) || '분석 데이터를 불러오고 있습니다.';
        flowEl.innerHTML = `현재 ${filterLabel} 패턴의 흐름을 분석하고 있습니다.`;
        const pTextFallback = document.getElementById('dip-pattern-llm-text');
        if (pTextFallback) pTextFallback.innerHTML = '과거 데이터와의 연관 패턴을 도출하는 중입니다.';
        strategyEl.innerHTML = _cleanLLMText(advice);
    }

    // 프리미엄 리포트용 텍스트 분할 유틸리티 (유연한 섹션 감지 및 내용 추출)
    function _splitPremiumText(text) {
        if (!text) return { flow: '', pattern: '', strategy: '' };

        const lines = text.split('\n');
        let flow = '', pattern = '', strategy = '';
        let current = '';

        lines.forEach(line => {
            let l = line.trim();
            if (!l) return;
            
            // 1. 섹션 전환 감지 (앞부분의 **, #, [ 등 특수문자 및 공백 유연하게 허용)
            let isHeader = false;
            if (l.match(/[#*\s]*[1]\.?\s*\[?(흐름|진단)\]?/i) || l.match(/^[#*\s]*흐름\s*진단/i)) { 
                current = 'flow'; 
                isHeader = true; 
            } 
            else if (l.match(/[#*\s]*[2]\.?\s*\[?(패턴|분석)\]?/i) || l.match(/^[#*\s]*패턴\s*분석/i)) { 
                current = 'pattern'; 
                isHeader = true; 
            } 
            else if (l.match(/[#*\s]*[3]\.?\s*\[?(전략|제언|공략|필승)\]?/i) || l.match(/^[#*\s]*(전략\s*제언|필승\s*공략)/i)) { 
                current = 'strategy'; 
                isHeader = true; 
            }
            
            if (isHeader) return; // 헤더 라인 자체는 본문에 포함하지 않음

            // 2. 내용 누적 (불필요한 마크다운/불렛 기호 정제)
            const cleanLine = l.replace(/^[#*\-\+\s]+/, '').trim();
            if (!cleanLine) return;

            if (current === 'flow') flow += cleanLine + ' ';
            else if (current === 'pattern') pattern += cleanLine + ' ';
            else if (current === 'strategy') strategy += cleanLine + ' ';
            else if (!current) flow += cleanLine + ' '; // 헤더 전 텍스트는 흐름진단에 포함
        });

        return {
            flow: flow.trim()     || 'AI 흐름 진단 분석을 진행하고 있습니다.',
            pattern: pattern.trim()   || 'AI 패턴 분석 결과 도출 중입니다.',
            strategy: strategy.trim() || 'AI 최종 전략 가이드를 수립하고 있습니다.'
        };
    }

    // AIProxy 응답에서 텍스트 추출 — 다양한 응답 구조 대응
    function _extractLLMText(result, filterKey) {
        if (!result) return null;
        const direct = result.response || result.content || result.answer || result.report || result.text;
        if (direct) return _cleanLLMText(direct, filterKey);
        // {trend, pattern, recommendation} 구조 (Python RAG 응답)
        const parts = [];
        if (result.trend)          parts.push(result.trend);
        if (result.pattern)        parts.push(result.pattern);
        if (result.recommendation) parts.push(result.recommendation);
        if (parts.length) return _cleanLLMText(parts.join('\n\n'), filterKey);
        return null;
    }

    // LLM 텍스트 정제 — 강조 태그 스타일링 및 범위 태그 지원
    function _cleanLLMText(text) {
        if (!text) return text;
        return text
            .replace(/\{\{good:([^}]+)\}\}/g, '<strong class="dip-v3-hl-good">$1</strong>')
            .replace(/\{\{warn:([^}]+)\}\}/g, '<strong class="dip-v3-hl-warn">$1</strong>')
            .replace(/\{\{info:([^}]+)\}\}/g, '<strong class="dip-v3-hl-info">$1</strong>')
            .replace(/\{\{range:([^}]+)\}\}/g, '<strong class="dip-v3-hl-range">$1</strong>') // [추가] 범위 강조 지원
            .replace(/\b0\.(\d{3,4})\b/g, (_, d) => {
                const pct = (parseFloat('0.' + d) * 100).toFixed(1);
                return `<span class="dip-v3-hl-info">${pct}%</span>`;
            });
    }

    function _fillFallbackAI(aiBody, strategy, filterLabel) {
        aiBody.innerHTML = '';
        const slot = document.getElementById('dip-ai-rec-slot');
        if (slot) slot.innerHTML = _llmRecHTML(strategy, filterLabel);
    }

    // LLM이 제안한 해당 필터의 권장값 — 텍스트 아래 한 줄 표시
    function _llmRecHTML(strategy, filterLabel) {
        const rec = (strategy.filter_recommendations || []).find(r =>
            r.filter === filterLabel ||
            (r.filter && r.filter.replace(/\s/g, '') === filterLabel.replace(/\s/g, ''))
        );
        if (!rec) return '';
        const val = rec.min !== undefined ? `${rec.min} ~ ${rec.max}` : (rec.pattern || '');
        if (!val) return '';
        return `<div class="dip-llm-rec">
            <span class="dip-llm-rec-label">LLM 권장</span>
            <span class="dip-llm-rec-val">${val}</span>
            ${rec.evidence ? `<span class="dip-llm-rec-ev">${rec.evidence}</span>` : ''}
        </div>`;
    }

    function _actionTagsHTML(strategy) {
        const actions = (strategy.overall_strategy && strategy.overall_strategy.key_actions ? strategy.overall_strategy.key_actions : []).slice(0, 3);
        if (!actions.length) return '';
        return `<div class="dip-actions">${actions.map(a => `<span class="dip-action-tag">✓ ${a}</span>`).join('')}</div>`;
    }

    // ── 헤더 갱신 ─────────────────────────────────────────────────────────────
    function _updateHeader(data) {
        // [제거] 회차 예측 정보 표시 제거 요청
        // const el = document.getElementById('dlTargetRound');
        // if (el && data?.target_round) el.textContent = `${data.target_round}회차 예측`;
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // HTML 빌더 — 단일 필터 (Category A)
    // ═══════════════════════════════════════════════════════════════════════════
    function _buildFilterHTML(filterKey, filterLabel, modelExp, strategy, currentRange) {
        const { cMin, cMax, agreement } = _ensembleRange(modelExp);
        const targetRound = _memCache?.target_round || '';

        return `
        <div class="dip-root">
            <!-- [Header] -->
            <header class="dip-v3-header">
                <div class="dip-v3-title-group">
                    <div>
                        <h2>AI 프리미엄 전략 리포트</h2>
                        <p>INTELLIGENT ANALYSIS — ${filterLabel}</p>
                    </div>
                </div>
            </header>

            <!-- [Ensemble Summary] - [추가] 앙상블 섹션 복구 -->
            <div class="dip-v3-ensemble-box">
                <div class="dip-v3-ens-main">
                    <div class="dip-v3-ens-info">
                        <span class="dip-v3-ens-label">앙상블 종합 예측 범위</span>
                        <div class="dip-v3-ens-value">
                            <span class="dip-v3-ens-range">${cMin} ~ ${cMax}</span>
                            <span class="dip-v3-ens-avg">평균 ${((cMin + cMax) / 2).toFixed(1)}</span>
                        </div>
                    </div>
                    <div class="dip-v3-ens-gauge">
                        <div class="dip-v3-gauge-label">모델 합의도</div>
                        <div class="dip-v3-gauge-track">
                            <div class="dip-v3-gauge-bar" style="width: ${agreement}%"></div>
                        </div>
                        <div class="dip-v3-gauge-text">${agreement}% 합의</div>
                    </div>
                </div>
            </div>

            <div style="padding: 1rem 2rem 2rem 2rem;">
                <!-- [Middle] Compact Model Grid -->
                <div class="dip-v3-model-grid">
                    ${MODEL_ORDER.map(key => {
                        const meta = MODEL_META[key];
                        const exp  = modelExp[key];
                        if (!exp) return '';
                        return `
                        <div class="dip-v3-model-card">
                            <span class="dip-v3-m-label">${meta.label}</span>
                            <span class="dip-v3-m-val">${exp.min}~${exp.max}</span>
                        </div>`;
                    }).join('')}
                </div>

                <!-- [Body] AI Analysis Slots -->
                <div class="dip-v3-body" style="display: block;">
                    <div class="dip-v3-col" style="margin-bottom: 2rem;">
                        <div class="dip-v3-col-header">
                            <span class="dip-v3-col-title">흐름 진단</span>
                        </div>
                        <div class="dip-v3-col-content" id="dip-v3-content-flow">
                            전체 모델 데이터와 최근 추세를 종합하여 흐름을 진단 중입니다...
                        </div>
                    </div>
                    <div class="dip-v3-col" style="border-top: 1px solid #f1f5f9; padding-top: 2rem; margin-bottom: 1rem;">
                        <div class="dip-v3-col-header">
                            <span class="dip-v3-col-title">패턴 분석</span>
                        </div>
                        <div class="dip-v3-col-content" id="dip-v3-content-pattern">
                            통계적 범위 내 특이 패턴 및 소외 구간을 분석 중입니다...
                        </div>
                    </div>
                </div>

                <!-- [Bottom] Winning Strategy -->
                <div class="dip-v3-strategy">
                    <div class="dip-v3-strat-header">
                        <span class="dip-v3-strat-title">${targetRound}회차 전략 제언</span>
                    </div>
                    <div class="dip-v3-strat-content" id="dip-v3-content-strategy">
                        최적의 분석 가이드를 생성하고 있습니다.
                    </div>
                </div>
            </div>
        </div>`;
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // HTML 빌더 — 그룹 (Category B)
    // ═══════════════════════════════════════════════════════════════════════════
    function _buildGroupHTML(groupType, analysis, strategy) {
        let bodyHTML = '';
        let groupLabel = '';
        let recFilter = '';
        let isSectioned = false;  // true when bodyHTML already contains <section> elements

        switch (groupType) {
            case 'custom_analysis': {
                groupLabel = '맞춤형 전략 분석';
                recFilter  = '맞춤분석';
                
                // 맞춤형 분석은 별도의 통계 그리드 대신, 
                // 현재 설정된 필터 조건과 번호들의 매칭률을 강조하는 UI
                const targets = analysis.target_numbers || [];
                
                bodyHTML = `
                    <section class="dip-section">
                        <div class="dip-section-label">필터 대상 번호 분석</div>
                        <div class="flex flex-wrap gap-2 p-4 bg-[#f8fafc] border border-slate-100 rounded-xl">
                            ${targets.length > 0 ? targets.map(num => {
                                const ballColor = (window.Utils && window.Utils.getBallColor) ? window.Utils.getBallColor(num) : '#64748b';
                                return `<div class="w-8 h-8 rounded-full flex items-center justify-center text-white font-bold text-sm shadow-sm" style="background-color: ${ballColor}">${num}</div>`;
                            }).join('') : '<span class="text-slate-400 text-xs">선택된 번호가 없습니다.</span>'}
                        </div>
                    </section>
                `;
                break;
            }
            case 'number_band': {
                groupLabel = '번호대별 분포';
                recFilter  = '번호대별';
                const bands = analysis.number_band_analysis || [];
                if (!bands.length) { bodyHTML = _noDataHTML(); break; }
                const max = Math.max(...bands.map(b => b.exp || 0)) || 1;
                bodyHTML = `<div class="dip-group-list">
                    ${bands.map((b, i) => `
                    <div class="dip-group-row">
                        <span class="dip-group-name">${b.label}</span>
                        <div class="dip-group-bar-wrap">
                            <div class="dip-group-bar" style="width:${(b.exp/max*100).toFixed(1)}%;background:${['#3b82f6','#22c55e','#f97316','#a855f7','#ef4444'][i%5]}"></div>
                        </div>
                        <span class="dip-group-val">기대 <strong>${b.exp}</strong>개</span>
                    </div>`).join('')}
                </div>`;
                break;
            }
            case 'magic_square': {
                groupLabel = '9궁 분석';
                recFilter  = '9궁분석';
                const squares = analysis.magic_square_analysis || [];
                if (!squares.length) { bodyHTML = _noDataHTML(); break; }
                const sorted = [...squares].sort((a, b) => (b.exp || 0) - (a.exp || 0));
                const max = (sorted[0] && sorted[0].exp) || 1;
                const COLORS = ['#3b82f6','#22c55e','#f97316','#a855f7','#ef4444','#14b8a6','#f59e0b','#ec4899','#6366f1'];
                bodyHTML = `<div class="dip-palace-grid">
                    ${squares.map((s, i) => {
                        const isTop = sorted.indexOf(s) < 2;
                        return `<div class="dip-palace-cell ${isTop ? 'dip-palace-top' : ''}" style="border-color:${COLORS[i]}20">
                            <div class="dip-palace-num" style="color:${COLORS[i]}">${s.label}</div>
                            <div class="dip-palace-exp" style="color:${COLORS[i]}">${s.exp}</div>
                            ${isTop ? `<div class="dip-palace-badge" style="background:${COLORS[i]}">TOP</div>` : ''}
                        </div>`;
                    }).join('')}
                </div>`;
                break;
            }
            case 'lotto_paper': {
                groupLabel = '로또용지 분석';
                recFilter  = '로또용지';
                const paper = analysis.lotto_paper_analysis;
                if (!paper) { bodyHTML = _noDataHTML(); break; }
                const rows = paper.rows || [], cols = paper.cols || [];
                const maxR = Math.max(...rows.map(r => r.exp || 0)) || 1;
                const maxC = Math.max(...cols.map(c => c.exp || 0)) || 1;
                bodyHTML = `<div class="dip-paper-grid">
                    <div>
                        <div class="dip-paper-subtitle">행 (가로)</div>
                        ${rows.map(r => `<div class="dip-group-row">
                            <span class="dip-group-name">${r.label}</span>
                            <div class="dip-group-bar-wrap">
                                <div class="dip-group-bar" style="width:${(r.exp/maxR*100).toFixed(1)}%;background:#3b82f6"></div>
                            </div>
                            <span class="dip-group-val"><strong>${r.exp}</strong>개</span>
                        </div>`).join('')}
                    </div>
                    <div>
                        <div class="dip-paper-subtitle">열 (세로)</div>
                        ${cols.map(c => `<div class="dip-group-row">
                            <span class="dip-group-name">${c.label}</span>
                            <div class="dip-group-bar-wrap">
                                <div class="dip-group-bar" style="width:${(c.exp/maxC*100).toFixed(1)}%;background:#22c55e"></div>
                            </div>
                            <span class="dip-group-val"><strong>${c.exp}</strong>개</span>
                        </div>`).join('')}
                    </div>
                </div>`;
                break;
            }
            case 'regression': {
                groupLabel = '회귀분석 종합';
                recFilter  = '';
                const REGRESSION_FILTERS = ['총합','끝수합','AC값','홀짝','저고','소수','합성수','연속','이월','이웃','핫콜드','미출현'];
                const recs = (strategy.filter_recommendations || [])
                    .filter(r => REGRESSION_FILTERS.some(name => r.filter?.includes(name.replace('비율',''))))
                    .slice(0, 10);
                
                // [수리] regression_analysis 데이터가 없을 경우 recs를 기반으로 기본 그리드 구성
                const regData = (analysis.regression_analysis && Array.isArray(analysis.regression_analysis)) 
                                ? analysis.regression_analysis 
                                : recs.map(r => ({ filter_name: r.filter, predicted: r.pattern || `${r.min}~${r.max}` }));

                bodyHTML = `
                    ${regData.length ? `
                    <div class="dip-group-list dip-regression-list">
                        ${regData.slice(0, 8).map(r => `
                        <div class="dip-reg-row">
                            <span class="dip-reg-name">${r.filter_name || r.name || r.label || '항목'}</span>
                            <span class="dip-reg-val">${r.predicted !== undefined ? r.predicted : (r.range || r.value || '-')}</span>
                        </div>`).join('')}
                    </div>` : '<div class="text-slate-400 text-xs text-center py-4">분석 데이터 생성 중입니다.</div>'}
                `;
                break;
            }
            case 'tail_digit': {
                groupLabel = '끝수 분포';
                recFilter  = '끝수 분석';
                
                const tailData = analysis.tail_analysis || [];
                if (!tailData || !tailData.length) {
                    bodyHTML = _noDataHTML();
                    break;
                }
                
                const _deriveRecommendedRange = (exp) => {
                    if (exp < 0.3) return "0 ~ 1";
                    if (exp >= 0.3 && exp < 1.2) return "0 ~ 2";
                    if (exp >= 1.2 && exp < 1.8) return "1 ~ 2";
                    if (exp >= 1.8 && exp < 2.3) return "1 ~ 3";
                    if (exp >= 2.3 && exp < 2.8) return "2 ~ 3";
                    return "1 ~ 4"; 
                };
                
                const tdModelRows = tailData.map((item, index) => {
                    const exp = typeof item.exp === 'number' ? item.exp : 0;
                    const recRange = _deriveRecommendedRange(exp);
                    
                    return `<div class="dip-model-row" style="flex-direction:column; align-items:stretch; padding:10px 12px; gap:8px;">
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <div style="display:flex;align-items:center;gap:6px;">
                                <span class="dip-dot" style="background:${exp >= 1.2 ? '#db2777' : '#0ea5e9'};width:8px;height:8px;"></span>
                                <span class="dip-model-name" style="font-size:14px;">${index}끝</span>
                            </div>
                            <span style="font-size:11px;color:#94a3b8;font-weight:600;">출현 확률: ${(exp*100).toFixed(0)}%</span>
                        </div>
                        <div style="background:${exp >= 1.2 ? '#fdf2f8' : '#f0f9ff'}; border:1px solid ${exp >= 1.2 ? '#fbcfe8' : '#e0f2fe'}; border-radius:8px; padding:6px; text-align:center;">
                            <span style="font-size:11px;color:${exp >= 1.2 ? '#be185d' : '#0369a1'};font-weight:700;margin-right:4px;">추천 필터범위</span>
                            <span style="font-size:14px;color:${exp >= 1.2 ? '#9d174d' : '#0284c7'};font-weight:900;letter-spacing:1px;font-family:monospace;">[ ${recRange} ]</span>
                        </div>
                    </div>`;
                }).join('');
                
                isSectioned = true;
                bodyHTML = `
                    <section class="dip-section" style="padding-bottom:10px;">
                        <div class="dip-section-label" style="display:flex; justify-content:space-between; align-items:center;">
                            <span>끝수 독립 출현 예측 (0~9끝)</span>
                            <span style="font-size:11px; color:#ef4444; font-weight:bold; background:#fee2e2; padding:2px 6px; border-radius:4px;">🔥 직접 입력(Actionable) 데이터</span>
                        </div>
                        <div class="dip-model-list" style="display:grid;grid-template-columns:repeat(2,1fr);gap:10px">${tdModelRows}</div>
                    </section>
                `;
                break;
            }
        }

        const rec = (strategy.filter_recommendations || []).find(r => r.filter === recFilter || (r.filter && r.filter.includes(recFilter)));
        const recBlock = rec ? `<div class="dip-rec-badge" style="margin-top:12px">
            <span class="dip-rec-label">권장</span>
            <span class="dip-rec-value">${rec.pattern || (rec.min !== undefined ? `${rec.min}~${rec.max}` : '')}</span>
            ${rec.evidence ? `<span class="dip-rec-evidence">${rec.evidence}</span>` : ''}
        </div>` : '';

        if (isSectioned) {
            // bodyHTML already contains <section> elements (e.g. tail_digit)
            return _wrapGroup(groupLabel, `${bodyHTML}${_aiSection(groupLabel)}`, '');
        }

        return _wrapGroup(groupLabel, `
            <section class="dip-section">
                <div class="dip-section-label">${groupLabel}</div>
                ${bodyHTML}
                ${recBlock}
            </section>
            ${_aiSection(groupLabel)}
        `, '');
    }

    function _wrapGroup(label, content, extra) {
        const targetRound = _memCache?.target_round || '';
        return `
        <div class="dip-root">
            <!-- [Header] -->
            <header class="dip-v3-header">
                <div class="dip-v3-title-group">
                    <div class="dip-v3-icon-main">
                        <span class="material-symbols-outlined" style="font-size:24px; color:white;">analytics</span>
                    </div>
                    <div>
                        <h2>AI 프리미엄 전략 리포트</h2>
                        <p>INTELLIGENT GROUP ANALYSIS — ${label}</p>
                    </div>
                </div>
                <!-- 그룹분석 새로고침은 현재 미지원하거나 별도 로직 필요 (필요시 추가) -->
            </header>

            <!-- [Stats/Content] -->
            <div style="padding: 2rem 2rem 1rem 2rem;">
                ${content}
            </div>

            ${extra}
        </div>`;
    }

    function _aiSection(sectionLabel) {
        const targetRound = _memCache?.target_round || '';
        return `
            <!-- [Ensemble Summary] - [추가] 앙상블 섹션 복구 -->
            <div class="dip-v3-ensemble-box" style="margin-top:0; border-top:none;">
                <div class="dip-v3-ens-main">
                    <div class="dip-v3-ens-info">
                        <span class="dip-v3-ens-label">종합 흐름 분석</span>
                        <div class="dip-v3-ens-value">
                            <span class="dip-v3-ens-range" style="font-size:1.1rem">데이터 정밀 진단 중</span>
                        </div>
                    </div>
                </div>
            </div>

            <!-- [Body] AI Analysis Slots -->
            <div class="dip-v3-body" style="padding: 1rem 2rem 1rem 2rem; display: block;">
                <div class="dip-v3-col" style="margin-bottom: 2rem;">
                    <div class="dip-v3-col-header">
                        <span class="dip-v3-col-title">흐름 진단</span>
                    </div>
                    <div class="dip-v3-col-content" id="dip-v3-group-flow">
                        종합 통계 데이터의 흐름을 분석 중입니다...
                    </div>
                </div>
                <div class="dip-v3-col" style="border-top: 1px solid #f1f5f9; padding-top: 2rem; margin-bottom: 1rem;">
                    <div class="dip-v3-col-header">
                        <span class="dip-v3-col-title">패턴 분석</span>
                    </div>
                    <div class="dip-v3-col-content" id="dip-v3-group-pattern">
                        과거 데이터와의 상관 관계 및 특이 패턴을 분석 중입니다...
                    </div>
                </div>
            </div>

            <!-- [Bottom] Winning Strategy -->
            <div class="dip-v3-strategy" style="margin: 0 2rem 2rem 2rem; border-radius: 1rem;">
                <div class="dip-v3-strat-header">
                    <span class="dip-v3-strat-title">${targetRound}회차 전략 제언</span>
                </div>
                <div class="dip-v3-strat-content" id="dip-v3-group-strategy">
                    가장 유력한 필터 값을 도출하고 있습니다.
                </div>
            </div>
        `;
    }

    // ── 그룹용 LLM 비동기 분석 호출 ───────────────────────────────────────────
    async function _requestGroupLLMAnalysis(aiBodyId, groupType, groupLabel, analysis, strategy, targetRound) {
        const flowEl   = document.getElementById('dip-v3-group-flow');
        const patternEl = document.getElementById('dip-v3-group-pattern');
        const strategyEl = document.getElementById('dip-v3-group-strategy');

        if (!flowEl || !patternEl || !strategyEl) return;

        let summaryText = '';
        switch (groupType) {
            case 'number_band': {
                const bands = analysis.number_band_analysis || [];
                summaryText = bands.map(b => `${b.label}: ${b.exp}개`).join(', ');
                break;
            }
            case 'magic_square': {
                const squares = analysis.magic_square_analysis || [];
                const sorted = [...squares].sort((a, b) => (b.exp || 0) - (a.exp || 0));
                summaryText = sorted.slice(0, 3).map(s => `${s.label}궁: ${s.exp}`).join(', ') +
                    ` (상위 3궁), 전체: ${squares.map(s => `${s.label}=${s.exp}`).join(',')}`;
                break;
            }
            case 'lotto_paper': {
                const paper = analysis.lotto_paper_analysis;
                if (paper) {
                    summaryText = `행: ${(paper.rows || []).map(r => `${r.label}=${r.exp}`).join(',')} / ` +
                        `열: ${(paper.cols || []).map(c => `${c.label}=${c.exp}`).join(',')}`;
                }
                break;
            }
            case 'regression': {
                const recs = (strategy.filter_recommendations || []).slice(0, 8);
                summaryText = recs.map(r => `${r.filter}: ${r.min !== undefined ? r.min + '~' + r.max : (r.pattern || '')}`).join(', ');
                break;
            }
            case 'custom_analysis': {
                const targets = analysis.target_numbers || [];
                summaryText = `분석 대상 번호: [${targets.join(', ')}], 설정 필터: ${(strategy.filter_recommendations || []).map(r => r.filter).join(', ')}`;
                break;
            }
            case 'tail_digit': {
                const tailData = analysis.tail_analysis || [];
                if (tailData.length) {
                    summaryText = tailData.map((d, i) => `${i}끝:${(d && d.exp ? d.exp.toFixed(2) : '0.00')}개`).join(', ');
                } else {
                    summaryText = "데이터 없음";
                }
                break;
            }
        }

        const prompt =
`# Role: 최고의 로또 통계 분석 전문가이자 데이터 과학자
# Target: ${targetRound || ''}회차 ${groupLabel} 그룹 리포트
# Analysis Summary: ${summaryText}

# 분석 요청 사항:
1. [흐름진단]: 위 요약된 ${groupLabel} 통계 데이터를 기반으로 최근 로또 당첨번호의 전체적인 흐름과 추세를 과학적으로 진단해주세요. (3~4문장)
2. [패턴분석]: 제공된 데이터를 통해 도출할 수 있는 특이 패턴이나 과거 유사 회차들과의 연계성, 그리고 사람이 직관적으로 보기 어려운 숨겨진 통계적 의미를 분석해주세요. (3~4문장)
3. [필승공략]: 이 분석 결과를 실제 번호 조합 시 ${targetRound}회차에서 어떻게 필터링 전략으로 활용해야 할지 구체적인 팁과 최종 의사결정 가이드를 제안해주세요. (2~3문장)

# 주의사항:
- 강조할 수치나 키워드는 반드시 {{good:값}} 또는 {{info:값}}, {{warn:위험}} 태그로 감싸주세요.
- 전문가답게 단정적이고 확신 있는 어조를 사용하고, 추상적인 설명을 배제하세요.`;

        try {
            const result = await window.AIProxy.invoke({
                prompt,
                analysisType: groupType,
                targetRound: targetRound || 0,
                responseStyle: 'expert'
            });
            const text = _extractLLMText(result, groupType);
            if (text) {
                const parts = _splitPremiumText(text);
                flowEl.innerHTML     = _cleanLLMText(parts.flow);
                patternEl.innerHTML  = _cleanLLMText(parts.pattern);
                strategyEl.innerHTML = _cleanLLMText(parts.strategy);
                return;
            }
        } catch (e) { /* fallback */ }

        flowEl.innerHTML = `현재 ${groupLabel} 흐름을 면밀히 분석하고 있습니다.`;
        patternEl.innerHTML = '패턴 일치 여부를 검증 중입니다.';
        strategyEl.innerHTML = '최적의 조합 전략을 수립하여 제공할 예정입니다.';
    }

    function _noDataHTML() {
        return '<p class="dip-empty">분석 데이터가 없습니다.</p>';
    }

    // ── CSS 주입 (한 번만) ────────────────────────────────────────────────────
    function _injectStyles() {
        if (document.getElementById('dip-styles')) return;
        const style = document.createElement('style');
        style.id = 'dip-styles';
        style.textContent = `
        /* ── DeepInsightPanel Premium V3 Styles ── */
        .dip-root {
            font-family: 'Pretendard', sans-serif;
            border-radius: 2rem;
            overflow: hidden;
            background: #ffffff;
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.05), 0 8px 10px -6px rgba(0, 0, 0, 0.05);
            margin-bottom: 2rem;
            border: 1px solid #f1f5f9;
            width: 100%; box-sizing: border-box;
        }

        /* [Header] Dark Premium */
        .dip-v3-header {
            background: #1e293b;
            padding: 1.25rem 2rem;
            display: flex;
            align-items: center;
            justify-content: space-between;
            color: white;
        }
        .dip-v3-title-group h2 { font-size: 1.1rem; font-weight: 800; margin: 0; letter-spacing: -0.02em; }
        .dip-v3-title-group p { font-size: 0.7rem; color: rgba(255,255,255,0.6); margin: 2px 0 0 0; font-weight: 600; text-transform: uppercase; }

        /* [Ensemble Summary Section] */
        .dip-v3-ensemble-box {
            padding: 1.5rem 2rem;
            background: #f8fafc;
            border-bottom: 1px solid #f1f5f9;
        }
        .dip-v3-ens-main {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 2rem;
        }
        .dip-v3-ens-info { flex: 1; }
        .dip-v3-ens-label { font-size: 0.75rem; color: #64748b; font-weight: 600; text-transform: uppercase; margin-bottom: 4px; display: block; }
        .dip-v3-ens-value { display: flex; align-items: baseline; gap: 12px; }
        .dip-v3-ens-range { font-size: 1.75rem; font-weight: 800; color: #1e293b; font-family: 'Pretendard', sans-serif; }
        .dip-v3-ens-avg { font-size: 0.9rem; color: #2563eb; font-weight: 700; background: #dbeafe; padding: 2px 8px; border-radius: 6px; }

        .dip-v3-ens-gauge { width: 220px; }
        .dip-v3-gauge-label { font-size: 0.65rem; color: #94a3b8; font-weight: 700; text-align: right; margin-bottom: 6px; }
        .dip-v3-gauge-track { height: 8px; background: #e2e8f0; border-radius: 4px; overflow: hidden; }
        .dip-v3-gauge-bar { height: 100%; background: linear-gradient(90deg, #3b82f6, #2563eb); transition: width 1s ease-out; }
        .dip-v3-gauge-text { font-size: 0.75rem; color: #475569; font-weight: 600; text-align: right; margin-top: 4px; }

        /* [Grid] Compact Models */
        .dip-v3-model-grid {
            display: grid;
            grid-template-columns: repeat(7, 1fr);
            gap: 12px;
            margin-bottom: 2rem;
        }
        .dip-v3-model-card {
            background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px;
            padding: 10px 8px; text-align: center; transition: all 0.2s;
        }
        .dip-v3-model-card:hover { border-color: #cbd5e1; transform: translateY(-2px); box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); }
        .dip-v3-m-label { font-size: 0.6rem; color: #94a3b8; font-weight: 700; text-transform: uppercase; display: block; margin-bottom: 4px; }
        .dip-v3-m-val { font-size: 0.8rem; font-weight: 800; color: #334155; font-family: monospace; }

        /* [Body] 1-Column Content */
        .dip-v3-body { display: block; margin-bottom: 2rem; }
        .dip-v3-col { width: 100%; }
        .dip-v3-col-header { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
        .dip-v3-col-title { font-size: 1rem; font-weight: 800; color: #1e293b; }
        .dip-v3-col-content { font-size: 0.9rem; color: #475569; line-height: 1.7; word-break: keep-all; }

        /* [Strategy] Bottom Box (Dark Strategy) */
        .dip-v3-strategy {
            background: #1e293b;
            padding: 1.5rem 2rem;
            border-radius: 1.25rem;
            color: rgba(255,255,255,0.9);
            margin-top: 1rem;
        }
        .dip-v3-strat-header { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
        .dip-v3-strat-title { font-size: 0.95rem; font-weight: 800; color: #38bdf8; }
        .dip-v3-strat-content { font-size: 0.9rem; line-height: 1.7; font-weight: 400; color: #e2e8f0; }

        /* Highlighting Tags */
        .dip-v3-hl-good { color: #2563eb; font-weight: 800; border-bottom: 2px solid #dbeafe; }
        .dip-v3-hl-warn { color: #e11d48; font-weight: 800; }
        .dip-v3-hl-info { color: #0891b2; font-weight: 800; }
        .dip-v3-hl-range { color: #7c3aed; font-weight: 800; background: #f5f3ff; padding: 2px 6px; border-radius: 4px; border: 1px solid #ede9fe; }

        /* [States] Loading / Empty */
        .dip-ai-loading {
            padding: 4rem 2rem; text-align: center; color: #94a3b8; font-size: 0.9rem;
            display: flex; flex-direction: column; align-items: center; gap: 1rem;
        }
        .dip-spin { animation: dip-spin 1s linear infinite; }
        @keyframes dip-spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        .dip-offline, .dip-error {
            padding: 3rem 2rem; text-align: center; background: #fff1f2; border-radius: 1.5rem; margin: 1.5rem;
        }
        .dip-offline p, .dip-error p { color: #9f1239; font-weight: 700; margin-bottom: 4px; }
        .dip-offline span, .dip-error span { color: #e11d48; font-size: 0.8rem; }
        `;
        document.head.appendChild(style);
    }

    // ── 상태 UI ───────────────────────────────────────────────────────────────
    function _showLoading(el) {
        el.innerHTML = `
            <div class="flex items-center justify-center gap-3 py-14 text-gray-400">
                <span class="material-symbols-outlined dip-spin text-2xl">progress_activity</span>
                <span class="text-sm font-medium">AI 딥러닝 분석 레포트 생성 중...</span>
            </div>`;
    }

    function _showOffline(el) {
        el.innerHTML = `
            <div class="dip-offline">
                <p>AI 서버 오프라인</p>
                <span>서버 기동 대기 중입니다. 잠시 후 새로고침 해주세요.</span>
            </div>`;
    }

    function _showError(el, msg) {
        el.innerHTML = `
            <div class="dip-error">
                <p>분석 오류</p>
                <span>${msg || '잠시 후 다시 시도해주세요'}</span>
            </div>`;
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // 공개 API
    // ═══════════════════════════════════════════════════════════════════════════
    window.DeepInsightPanel = {

        async render(containerId, filterKey, filterLabel, force = false) {
            const el = document.getElementById(containerId);
            if (!el) return;
            _lastContainerId = containerId; // ID 기억
            _injectStyles();
            _showLoading(el);

            try {
                const alive = await window.AIProxy.checkHealth(false, true);
                if (!alive) { _showOffline(el); return; }

                const data = await _getData(force);
                if (!data) { _showError(el, 'API 응답 없음'); return; }
                _updateHeader(data);

                const rangeAna   = (data && data.analysis && data.analysis.range_analysis) || {};
                const filterData = rangeAna[filterKey] || {};
                const modelExp   = filterData.model_expectations || {};
                const strategy   = (data && data.strategy) || {};
                const { cMin, cMax } = _ensembleRange(modelExp);

                // modelExp 비어있으면 캐시 무효화 후 1회 강제 재시도
                if (!Object.keys(modelExp).length) {
                    _memCache = null;
                    try { sessionStorage.removeItem(CACHE_KEY); } catch(e) {}
                    const fresh = await window.AIProxy.getDeepAnalysis();
                    if (fresh) {
                        _memCache = fresh;
                        try { sessionStorage.setItem(CACHE_KEY, JSON.stringify({ data: fresh, ts: Date.now() })); } catch(e) {}
                        const fd2 = (fresh && fresh.analysis && fresh.analysis.range_analysis ? fresh.analysis.range_analysis : {})[filterKey] || {};
                        const me2 = fd2.model_expectations || {};
                        if (Object.keys(me2).length) {
                            const st2 = (fresh && fresh.strategy) || {};
                            const { cMin: c2, cMax: x2 } = _ensembleRange(me2);
                            el.style.minHeight = '';
                            el.innerHTML = _buildFilterHTML(filterKey, filterLabel, me2, st2, fd2.range);
                            _requestLLMAnalysis('dip-ai-llm-body', filterKey, filterLabel, me2, c2, x2, fresh.target_round, st2, fd2.range);
                            return;
                        }
                    }
                    el.style.minHeight = '';
                    el.innerHTML = `<div class="dip-offline">
                        <p style="font-size:14px;color:#64748b;text-align:center;padding:32px 0">
                            <strong style="color:#334155">${filterLabel}</strong> 필터 데이터를 불러오지 못했습니다.<br>
                            <span style="font-size:12px;color:#94a3b8;margin-top:6px;display:block">잠시 후 다시 시도해주세요.</span>
                        </p>
                    </div>`;
                    return;
                }

                // 1단계: 모델 카드 + 앙상블 즉시 렌더
                el.style.minHeight = '';
                el.innerHTML = _buildFilterHTML(filterKey, filterLabel, modelExp, strategy, filterData.range);

                // 2단계: LLM 비동기 흐름분석 (병렬)
                _requestLLMAnalysis('dip-ai-llm-body', filterKey, filterLabel, modelExp, cMin, cMax, data.target_round, strategy, filterData.range);

            } catch (e) {
                console.error('[DeepInsightPanel]', e);
                _showError(el, e.message);
            }
        },

        refresh(containerId, filterKey, filterLabel) {
            this.render(containerId, filterKey, filterLabel, true);
        },

        async renderGroup(containerId, groupType, force = false, payload = null) {
            const el = document.getElementById(containerId);
            if (!el) return;
            _injectStyles();
            _showLoading(el);

            try {
                const alive = await window.AIProxy.checkHealth(false, true);
                if (!alive) { _showOffline(el); return; }

                const data = await _getData(force);
                if (!data) { _showError(el, 'API 응답 없음'); return; }
                _updateHeader(data);

                const GROUP_LABELS = {
                    number_band: '번호대별 분포',
                    magic_square: '9궁 분석',
                    lotto_paper: '로또용지 분석',
                    regression: '회귀분석 종합',
                    tail_digit: '끝수 분포',
                    custom_analysis: '맞춤형 분석'
                };
                const groupLabel = GROUP_LABELS[groupType] || groupType;

                // tail_digit needs range_analysis injected into analysis
                const analysis = { 
                    ...data.analysis, 
                    ...payload, // [추가] 외부 페이로드 주입 (예: custom_analysis의 타겟 번호)
                    range_analysis: (data.analysis && data.analysis.range_analysis) || {} 
                };
                el.style.minHeight = '';
                el.innerHTML = _buildGroupHTML(groupType, analysis, (data && data.strategy) || {});

                // 2-phase: LLM async analysis
                _requestGroupLLMAnalysis('dip-ai-llm-body', groupType, groupLabel, analysis, (data && data.strategy) || {}, data.target_round);

            } catch (e) {
                console.error('[DeepInsightPanel.renderGroup]', e);
                _showError(el, e.message);
            }
        },

        refreshGroup(containerId, groupType) {
            this.renderGroup(containerId, groupType, true);
        }
    };

    console.log('🧠 [DeepInsightPanel v2] 로드 완료');
})();
