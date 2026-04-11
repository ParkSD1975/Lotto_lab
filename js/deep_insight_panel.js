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
        return entries.filter((e, i) => Math.abs(mids[i] - mean) > std * 1.5).map(e => MODEL_META[e.key]?.label || e.key);
    }

    // ── 앙상블 min/max 계산 ───────────────────────────────────────────────────
    function _ensembleRange(modelExp) {
        const mins = Object.values(modelExp).map(e => e.min).filter(v => v !== undefined);
        const maxs = Object.values(modelExp).map(e => e.max).filter(v => v !== undefined);
        if (!mins.length) return { cMin: '-', cMax: '-' };
        return {
            cMin: Math.round(mins.reduce((a, b) => a + b, 0) / mins.length),
            cMax: Math.round(maxs.reduce((a, b) => a + b, 0) / maxs.length)
        };
    }

    // ── LLM 비동기 분석 호출 ──────────────────────────────────────────────────
    async function _requestLLMAnalysis(aiBodyId, filterKey, filterLabel, modelExp, cMin, cMax, targetRound, strategy) {
        const aiBody = document.getElementById(aiBodyId);
        if (!aiBody) return;

        aiBody.innerHTML = `<div class="dip-ai-loading">
            <span class="material-symbols-outlined dip-spin" style="font-size:15px;color:#475569">progress_activity</span>
            <span>흐름분석 중...</span>
        </div>`;

        const modelSummary = MODEL_ORDER
            .filter(k => modelExp[k])
            .map(k => `${MODEL_META[k].label}: ${modelExp[k].min}~${modelExp[k].max}`)
            .join(', ');

        // [추가] 필터 유형에 따른 단위 안내 (총합/끝수합은 단위 없음, 나머지는 '개')
        const _UNIT_LESS = ['sum', 'tail_sum'];  // 단위 없이 숫자만
        const unitHint = _UNIT_LESS.includes(filterKey)
            ? `(단위: 숫자 값 그대로 — 절대 '개', '번' 등 단위 붙이지 말 것)`
            : `(단위: 개수 기준)`;

        const prompt =
`[${targetRound || ''}회차 ${filterLabel} 딥러닝 분석 결과]
모델별 예측: ${modelSummary}
앙상블 평균: ${cMin}~${cMax}
${unitHint}

위 딥러닝 결과를 바탕으로 3~4문장으로 답변해주세요:
1. 모델 합의 수준 및 이탈 모델이 있다면 평가
2. 이 범위를 권장하는 핵심 근거
3. 최종 적용 권장 범위와 주의사항
※ 숫자 강조 시 {{good:값}} 또는 {{warn:값}} 형식으로 표시하세요.`;

        try {
            const result = await window.AIProxy.invoke({
                prompt,
                analysisType: filterKey,
                targetRound: targetRound || 0,
                responseStyle: 'expert'
            });
            const text = _extractLLMText(result, filterKey);
            if (text) {
                  const recHTML = _llmRecHTML(strategy, filterLabel);
                  const contentHTML = text.replace(/\n/g, '<br>');
                  
                  if (recHTML) {
                      aiBody.innerHTML = `
                          <div class="dip-ai-unified-box">
                              ${recHTML}
                              <div class="dip-ai-unified-text">${contentHTML}</div>
                          </div>
                      `;
                  } else {
                      aiBody.innerHTML = `<div class="dip-ai-unified-box"><div class="dip-ai-unified-text">${contentHTML}</div></div>`;
                  }
                  return;
              }
        } catch (e) { /* fallback */ }

        _fillFallbackAI(aiBody, strategy, filterLabel);
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

    // LLM 텍스트 정제 — 소수 확률 → %, 태그 치환
    // [수정] filterKey를 받아 단위 동적 결정
    const _UNIT_LESS_KEYS = ['sum', 'tail_sum'];
    function _cleanLLMText(text, filterKey) {
        if (!text) return text;
        const isUnitLess = _UNIT_LESS_KEYS.includes(filterKey);
        return text
            // [수정] {{range:2~3}} → 단위 없는 필터는 숫자만, 나머지는 '개' 붙임
            .replace(/\{\{range:([^}]+)\}\}/g, (_, r) => {
                const display = isUnitLess ? r : `${r}개`;
                return `<strong style="color:#db2777">${display}</strong>`;
            })
            // [추가] {{good:값}} → 초록색 강조 (총합 등 숫자형은 단위 없음)
            .replace(/\{\{good:([^}]+)\}\}/g, (_, v) => {
                return `<strong style="color:#22c55e">${v}</strong>`;
            })
            // [추가] {{warn:값}} → 노란색 경고 강조
            .replace(/\{\{warn:([^}]+)\}\}/g, (_, v) => {
                return `<strong style="color:#ec4899">${v}</strong>`;
            })
            // 앙상블 확률 소수 → % (0.XXXX 형태)
            .replace(/\b0\.(\d{3,4})\b/g, (_, d) => {
                const pct = (parseFloat('0.' + d) * 100).toFixed(1);
                return `<span style="color:#93c5fd">${pct}%</span>`;
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
            r.filter?.replace(/\s/g, '') === filterLabel.replace(/\s/g, '')
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
        const actions = (strategy.overall_strategy?.key_actions || []).slice(0, 3);
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
    function _buildFilterHTML(filterKey, filterLabel, modelExp, strategy, overallRange) {
        const agreement     = _computeAgreement(modelExp);
        const agreePct      = Math.round(agreement * 100);
        const outliers      = _findOutliers(modelExp);
        const { cMin, cMax } = _ensembleRange(modelExp);

        // LLM 필터 권장 추출
        const filterRec = (strategy.filter_recommendations || []).find(r =>
            r.filter && (
                r.filter === filterLabel ||
                r.filter.replace(/\s/g, '') === filterLabel.replace(/\s/g, '') ||
                r.filter.includes(filterKey.replace('_', ''))
            )
        );

        // 모델 행 HTML
        const modelRows = MODEL_ORDER.map(key => {
            const meta = MODEL_META[key];
            const exp  = modelExp[key];
            if (!exp) return '';
            const lo = exp.min, hi = exp.max;
            return `
            <div class="dip-model-row">
                <span class="dip-dot" style="background:${meta.dot}"></span>
                <span class="dip-model-name">${meta.label}</span>
                <span class="dip-model-tag">${meta.tag}</span>
                <span class="dip-range" style="color:${meta.dot}">${lo}<span class="dip-range-sep"> ~ </span>${hi}</span>
            </div>`;
        }).join('');

        // 합의도 색상 — 항상 빨간색
        const agreeColor = '#ef4444';
        const agreeLabel = agreePct >= 75 ? '높음' : agreePct >= 50 ? '보통' : '낮음';

        const outlierNote = outliers.length
            ? `<p class="dip-note">⚠ 이탈 모델: <strong>${outliers.join(', ')}</strong> — 범위 설정 시 참고</p>`
            : `<p class="dip-note">✓ 7개 모델이 유사한 범위를 예측합니다</p>`;

        return `
        <div class="dip-root">
            <!-- [제거] 내부 제목 제거 -->

            <!-- Section 1: 모델별 예측 -->
            <section class="dip-section">
                <div class="dip-model-list">${modelRows}</div>
            </section>

            <!-- Section 2: 앙상블 종합 -->
            <section class="dip-section dip-ensemble-section">
                <div class="dip-ensemble-row">
                    <div class="dip-ensemble-left">
                        <span class="dip-ensemble-title">앙상블 종합</span>
                        <span class="dip-ensemble-sub">7개 모델 평균</span>
                    </div>
                    <div class="dip-ensemble-right">
                        <span class="dip-ensemble-range">${cMin}<span class="dip-range-sep"> ~ </span>${cMax}</span>
                        ${overallRange ? `<span class="dip-sim-badge">${Array.isArray(overallRange) ? overallRange[0]+'~'+overallRange[1] : overallRange} 시뮬레이션</span>` : ''}
                    </div>
                </div>
                <div class="dip-agree-row">
                    <span class="dip-agree-label">모델 합의도</span>
                    <div class="dip-agree-bar-wrap">
                        <div class="dip-agree-bar" style="width:${agreePct}%;background:${agreeColor}"></div>
                    </div>
                    <span class="dip-agree-pct" style="color:${agreeColor}">${agreePct}% · ${agreeLabel}</span>
                </div>
            </section>

            <!-- Section 3: AI 분석 & 최종 제안 -->
            <section class="dip-ai-section">
                <div class="dip-ai-header">
                    <span class="dip-ai-icon">✦</span>
                    <span class="dip-ai-label">AI 흐름분석 &amp; 최종 제안</span>
                    <span class="dip-ai-filter-tag">${filterLabel}</span>
                </div>
                <div class="dip-ai-body">
                  ${outlierNote}
                  <div id="dip-ai-llm-body" style="min-height: 160px; width: 100%; box-sizing: border-box;">
                      <div class="dip-ai-loading">
                          <span class="material-symbols-outlined dip-spin" style="font-size:15px;color:#94a3b8">progress_activity</span>
                          <span>흐름분석 중...</span>
                      </div>
                  </div>
                </div>
            </section>
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
                const max = sorted[0]?.exp || 1;
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
                const regData = analysis.regression_analysis;
                bodyHTML = `
                    ${regData && Array.isArray(regData) && regData.length ? `
                    <div class="dip-group-list dip-regression-list">
                        ${regData.slice(0, 6).map(r => `
                        <div class="dip-reg-row">
                            <span class="dip-reg-name">${r.filter_name || r.name || r.label || '항목'}</span>
                            <span class="dip-reg-val">${r.predicted !== undefined ? r.predicted : (r.range || r.value || '-')}</span>
                        </div>`).join('')}
                    </div>` : ''}
                    ${recs.length ? `<div class="dip-rec-grid">
                        ${recs.map(r => `<div class="dip-rec-item">
                            <span class="dip-rec-item-label">${r.filter}</span>
                            <span class="dip-rec-item-val">${r.min !== undefined ? `${r.min}~${r.max}` : (r.pattern || '-')}</span>
                        </div>`).join('')}
                    </div>` : ''}`;
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

        const rec = (strategy.filter_recommendations || []).find(r => r.filter === recFilter || r.filter?.includes(recFilter));
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
        return `<div class="dip-root">${content}${extra}</div>`;
    }

    function _aiSection(sectionLabel) {
        return `
        <section class="dip-ai-section">
            <div class="dip-ai-header">
                <span class="dip-ai-icon">✦</span>
                <span class="dip-ai-label">AI 흐름분석 &amp; 최종 제안</span>
                <span class="dip-ai-filter-tag">${sectionLabel}</span>
            </div>
            <div class="dip-ai-body">
                <div id="dip-ai-llm-body" style="min-height: 160px; width: 100%; box-sizing: border-box;">
                    <div class="dip-ai-loading">
                    <span class="material-symbols-outlined dip-spin" style="font-size:15px;color:#475569">progress_activity</span>
                    <span>흐름분석 중...</span>
                </div>
            </div>
        </section>`;
    }

    // ── 그룹용 LLM 비동기 분석 호출 ───────────────────────────────────────────
    async function _requestGroupLLMAnalysis(aiBodyId, groupType, groupLabel, analysis, strategy, targetRound) {
        const aiBody = document.getElementById(aiBodyId);
        if (!aiBody) return;

        aiBody.innerHTML = `<div class="dip-ai-loading">
            <span class="material-symbols-outlined dip-spin" style="font-size:15px;color:#475569">progress_activity</span>
            <span>흐름분석 중...</span>
        </div>`;

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
            case 'tail_digit': {
                const tailData = analysis.tail_analysis || [];
                if (tailData.length) {
                    summaryText = tailData.map((d, i) => `${i}끝:${d.exp?.toFixed(2)}개`).join(', ');
                } else {
                    summaryText = "데이터 없음";
                }
                break;
            }
        }

        const prompt =
`[${targetRound || ''}회차 ${groupLabel} 딥러닝 분석 결과]
분석 데이터: ${summaryText}

위 딥러닝 결과를 바탕으로 3~4문장으로 답변해주세요:
1. 현재 패턴의 특이사항 및 경향 분석
2. 이 분포가 의미하는 핵심 전략적 시사점
3. 다음 회차 적용 시 주의사항과 권장 접근법`;

        try {
            const result = await window.AIProxy.invoke({
                prompt,
                analysisType: groupType,
                targetRound: targetRound || 0,
                responseStyle: 'expert'
            });
            const text = _extractLLMText(result);
              if (text) {
                  aiBody.innerHTML = `<div class="dip-ai-unified-box"><div class="dip-ai-unified-text">${text.replace(/\n/g, '<br>')}</div></div>`;
                  return;
              }
        } catch (e) { /* fallback */ }

        const advice = strategy.overall_strategy?.short_advice || '';
          const recHTML = _llmRecHTML(strategy, filterLabel);
          if (advice) {
              aiBody.innerHTML = `
                  <div class="dip-ai-unified-box">
                      ${recHTML}
                      <div class="dip-ai-unified-text">${advice}</div>
                  </div>
              `;
          } else {
              aiBody.innerHTML = '<p class="dip-note">분석 데이터를 불러오는 중입니다.</p>';
          }
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
        .dip-root {
            width: 100%; box-sizing: border-box;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji";
            color: #24292f; line-height: 1.5; font-size: 14px;
        }

        /* ── Section Dividers ── */
        .dip-section { padding: 16px 0; border-bottom: 1px solid #d0d7de; }
        .dip-section:last-child { border-bottom: none; }
        .dip-section-label {
            font-size: 15px; font-weight: 600; color: #24292f; margin-bottom: 20px;
            padding-bottom: 8px; border-bottom: 1px solid #d0d7de; display: inline-block;
        }

        /* ── Model Boxes (1 row, 7 columns) ── */
        /* 점선 제거: border-bottom: none */
        .dip-model-list { display: grid; grid-template-columns: repeat(7, 1fr); gap: 10px; padding-bottom: 24px; border-bottom: none; }
        .dip-model-row {
            display: flex; flex-direction: column; align-items: flex-start; gap: 4px;
            padding: 8px 12px; background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 6px;
        }
        .dip-model-name { font-size: 13px; font-weight: 700; color: #24292f; }
        .dip-range {
            font-family: ui-monospace, SFMono-Regular, SF Mono, Menlo, Consolas, Liberation Mono, monospace;
            font-size: 14px; font-weight: 600; color: #24292f; font-variant-numeric: tabular-nums;
        }
        .dip-range-sep { font-weight: 400; color: #57606a; margin: 0 4px; }
        .dip-dot, .dip-model-tag { display: none; }

        /* ── Ensemble ── */
        .dip-ensemble-section { padding-top: 24px !important; border-bottom: none; }
        .dip-ensemble-row { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 12px; }
        .dip-ensemble-left { display: flex; align-items: baseline; gap: 8px; }
        .dip-ensemble-title { font-size: 16px; font-weight: 600; color: #24292f; }
        .dip-ensemble-sub { font-size: 13px; color: #57606a; }
        .dip-ensemble-right { }
        .dip-ensemble-range { 
            font-family: ui-monospace, SFMono-Regular, SF Mono, Menlo, Consolas, Liberation Mono, monospace;
            font-size: 26px; font-weight: 700; color: #0969da; 
            background: transparent; padding: 0; border: none; border-bottom: 2px solid #0969da;
            font-variant-numeric: tabular-nums;
        }
        .dip-sim-badge { display: none; }
        
        .dip-agree-row { display: flex; align-items: center; gap: 12px; margin-top: 16px; font-size: 13px; }
        .dip-agree-label { font-weight: 600; color: #57606a; min-width: 70px; }
        .dip-agree-bar-wrap { flex: 1; height: 8px; background: #ebecf0; overflow: hidden; border-radius: 4px; }
        .dip-agree-bar { height: 100%; background: #2da44e; transition: width 1s ease; border-radius: 4px; }
        .dip-agree-pct { font-family: ui-monospace, SFMono-Regular, SF Mono, Menlo, Consolas, Liberation Mono, monospace; font-weight: 600; color: #24292f; width: 85px; text-align: right; white-space: nowrap; }

        /* ── AI Insight Section ── */
        .dip-ai-section {
            padding: 24px 0 16px 0; margin-top: 24px; border-top: 1px solid #d0d7de; position: relative;
        }
        .dip-ai-header { display: flex; align-items: center; gap: 8px; margin-bottom: 20px; }
        .dip-ai-icon { font-size: 18px; }
        .dip-ai-label { font-size: 16px; font-weight: 600; color: #24292f; }
        .dip-ai-filter-tag { font-family: ui-monospace, SFMono-Regular, SF Mono, Menlo, Consolas, Liberation Mono, monospace; font-size: 12px; font-weight: 500; color: #57606a; margin-left: auto; background: #f6f8fa; border: 1px solid #d0d7de; padding: 2px 6px; border-radius: 6px; }
        .dip-ai-body { display: flex; flex-direction: column; gap: 16px; } /* gap 확대 */

        /* Meta Row (Callouts) - 테두리선 완전히 제거 */
        .dip-meta-row { display: flex; flex-direction: column; gap: 10px; border: none; overflow: visible; }

        /* 이탈모델: 깊이있고 고급스러운 플라밍고 레드 배경 */
        .dip-note {
            display: flex; align-items: baseline; justify-content: flex-start; gap: 8px;
            background: #fff1f2; border: none; border-radius: 8px; padding: 14px 18px; margin: 0;
            font-size: 13px; color: #9f1239; font-weight: 500;
        }
        .dip-note strong { font-weight: 700; color: #9f1239; }

        /* LLM 권장: 깊이있고 고급스러운 스카이 블루 배경 */
        .dip-llm-rec {
            display: flex; align-items: baseline; justify-content: flex-start; gap: 8px;
            background: #f0f9ff; border: none; border-radius: 8px; padding: 14px 18px; margin: 0;
        }
        .dip-llm-rec-label { font-size: 13px; font-weight: 700; color: #0369a1; min-width: 70px; display: flex; align-items: center; gap: 6px; }
        .dip-llm-rec-label::before { content: '💡'; font-size: 12px; }
        .dip-llm-rec-val { font-family: ui-monospace, SFMono-Regular, SF Mono, Menlo, Consolas, Liberation Mono, monospace; font-size: 16px; font-weight: 700; color: #0369a1; font-variant-numeric: tabular-nums; }
        .dip-llm-rec-ev { font-size: 12px; color: #475569; font-weight: 400; margin-left: auto; }

        
        /* 일체화된 LLM 분석 박스 */
        .dip-ai-unified-box {
            background: #f0f9ff; border-radius: 8px; overflow: hidden;
            border: none; width: 100%; box-sizing: border-box;
        }
        .dip-ai-unified-box .dip-llm-rec {
            background: transparent; border-bottom: 1px dashed #bae6fd; border-radius: 0;
            padding: 16px 20px;
        }
        .dip-ai-unified-text {
            padding: 16px 20px; font-size: 14px; line-height: 1.6; color: #334155;
        }

        /* Quote text block */
        .dip-advice {
            font-size: 14px; font-weight: 400; color: #24292f; line-height: 1.6;
            margin: 12px 0 0 0; padding: 4px 0 4px 16px;
            border-left: 4px solid #d0d7de; background: transparent;
        }

        /* ── Group views ── */
        .dip-group-list { margin-top: 12px; display: flex; flex-direction: column; gap: 8px; }
        .dip-group-row { display: flex; align-items: center; gap: 12px; }
        .dip-group-name { font-size: 13px; font-weight: 600; color: #24292f; width: 65px; flex-shrink: 0; }
        .dip-group-bar-wrap { flex: 1; height: 8px; background: #ebecf0; overflow: hidden; border-radius: 4px; }
        .dip-group-bar { height: 100%; background: #0969da; transition: width 0.8s ease; border-radius: 4px;}
        .dip-group-val { font-family: ui-monospace, SFMono-Regular, SF Mono, Menlo, Consolas, Liberation Mono, monospace; font-size: 12px; font-weight: 600; color: #24292f; width: 60px; text-align: right; flex-shrink: 0; }

        /* ── Palace grid ── */
        .dip-palace-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
        .dip-palace-cell { background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 6px; padding: 20px 12px; text-align: center; position: relative; }
        .dip-palace-top { background: transparent; border-color: #0969da; border-width: 2px; }
        .dip-palace-num { font-size: 13px; color: #57606a; margin-bottom: 4px; font-weight: 600; }
        .dip-palace-exp { font-family: ui-monospace, SFMono-Regular, SF Mono, Menlo, Consolas, Liberation Mono, monospace; font-size: 20px; font-weight: 600; color: #24292f; }
        .dip-palace-badge { display: none; }

        /* ── Paper grid ── */
        .dip-paper-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 40px; }
        .dip-paper-subtitle { font-size: 13px; font-weight: 600; color: #24292f; border-bottom: 1px solid #d0d7de; padding-bottom: 8px; margin-bottom: 16px; display: block; }

        /* ── Regression ── */
        .dip-regression-list { margin-bottom: 24px; display: flex; flex-direction: column; }
        .dip-reg-row {
            display: flex; align-items: center; justify-content: space-between;
            padding: 10px 12px; border-bottom: 1px solid #d0d7de;
        }
        .dip-reg-name { font-size: 13px; font-weight: 600; color: #24292f; }
        .dip-reg-val { font-family: ui-monospace, SFMono-Regular, SF Mono, Menlo, Consolas, Liberation Mono, monospace; font-size: 14px; font-weight: 600; color: #0969da; }
        
        .dip-rec-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; border-top: 1px solid #d0d7de; padding-top: 16px; }
        .dip-rec-item { display: flex; flex-direction: column; gap: 4px; padding: 12px; background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 6px; }
        .dip-rec-item-label { font-size: 12px; font-weight: 600; color: #57606a; }
        .dip-rec-item-val { font-family: ui-monospace, SFMono-Regular, SF Mono, Menlo, Consolas, Liberation Mono, monospace; font-size: 14px; font-weight: 600; color: #24292f; }

        /* ── Badge / Rec Block ── */
        .dip-rec-badge {
            display: inline-flex; align-items: baseline; gap: 10px;
            padding: 10px 16px; border: none; background: transparent; border-radius: 0; margin-top: 8px; width: 100%; padding: 0;
        }
        .dip-rec-label { font-size: 12px; font-weight: 600; color: #0969da; border: 1px solid #0969da; padding: 2px 6px; border-radius: 4px; }
        .dip-rec-value { font-family: ui-monospace, SFMono-Regular, SF Mono, Menlo, Consolas, Liberation Mono, monospace; font-size: 15px; font-weight: 600; color: #0969da; }
        .dip-rec-evidence { font-size: 12px; color: #57606a; margin-left: auto; }

        
        .dip-ai-loading {
            display: flex; align-items: center; justify-content: center; gap: 8px;
            padding: 32px 0; background: transparent; border: none; border-radius: 6px;
            color: #57606a; font-size: 14px; font-weight: 500; min-height: 50px; width: 100%; box-sizing: border-box;
            background-color: #f8fafc;
        }

        /* ── States / Skeleton ── */
        .dip-skel { background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 6px; animation: dip-pulse 1.5s infinite; }
        @keyframes dip-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
        #dip-ai-llm-body { min-height: 0; }
        
        .dip-loading, .dip-offline, .dip-error, .dip-empty {
            text-align: center; padding: 48px 0; color: #57606a; font-size: 14px; font-weight: 500; background: transparent; border-top: 1px solid #d0d7de; margin-top: 24px;
        }
        .dip-spin { animation: dip-spin 1s linear infinite; }
        .dip-spin { animation: dip-spin 1s linear infinite; }
        .dip-spin { animation: dip-spin 1s linear infinite; }
        .dip-spin { animation: dip-spin 1s linear infinite; }
        .dip-spin { animation: dip-spin 1s linear infinite; }
        .dip-offline-icon, .dip-error-icon { display: none; }
        .dip-offline p, .dip-error p { color: #111827; font-weight: 500; font-size: 15px; margin-bottom: 8px; }
        `;
        document.head.appendChild(style);
    }

    // ── 상태 UI ───────────────────────────────────────────────────────────────
    function _showLoading(el) {
        el.style.minHeight = '';
        el.innerHTML = `<div style="padding:4px 0">
            <!-- 제목 스켈레톤 -->
            <div class="dip-skel" style="width:140px;height:22px;margin-bottom:18px"></div>
            <!-- 모델 카드 7열 스켈레톤 -->
            <div style="display:grid;grid-template-columns:repeat(7,1fr);gap:7px;margin-bottom:16px">
                ${Array(7).fill('<div class="dip-skel" style="height:72px;border-radius:12px"></div>').join('')}
            </div>
            <!-- 앙상블 스켈레톤 -->
            <div class="dip-skel" style="height:72px;border-radius:12px;margin-bottom:14px"></div>
            <!-- AI 섹션 스켈레톤 -->
            <div class="dip-skel" style="height:120px;border-radius:12px;background:#1e293b;opacity:0.4"></div>
        </div>`;
    }

    function _showOffline(el) {
        el.style.minHeight = '';
        el.innerHTML = `<div class="dip-offline">
            <span class="dip-offline-icon">🔌</span>
            <p style="font-weight:700;color:#64748b">AI 서버 오프라인</p>
            <p style="color:#94a3b8;font-size:12px">AI 딥러닝 서버 기동 대기 중입니다. 잠시 후 새로고침 해주세요.</p>
        </div>`;
    }

    function _showError(el, msg) {
        el.style.minHeight = '';
        el.innerHTML = `<div class="dip-error">
            <span class="dip-error-icon">⚠️</span>
            <p style="font-weight:700;color:#92400e">분석 오류</p>
            <p style="color:#94a3b8;font-size:12px">${msg || '잠시 후 다시 시도해주세요'}</p>
        </div>`;
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // 공개 API
    // ═══════════════════════════════════════════════════════════════════════════
    window.DeepInsightPanel = {

        async render(containerId, filterKey, filterLabel, force = false) {
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

                const rangeAna   = data?.analysis?.range_analysis || {};
                const filterData = rangeAna[filterKey] || {};
                const modelExp   = filterData.model_expectations || {};
                const strategy   = data?.strategy || {};
                const { cMin, cMax } = _ensembleRange(modelExp);

                // modelExp 비어있으면 캐시 무효화 후 1회 강제 재시도
                if (!Object.keys(modelExp).length) {
                    _memCache = null;
                    try { sessionStorage.removeItem(CACHE_KEY); } catch(e) {}
                    const fresh = await window.AIProxy.getDeepAnalysis();
                    if (fresh) {
                        _memCache = fresh;
                        try { sessionStorage.setItem(CACHE_KEY, JSON.stringify({ data: fresh, ts: Date.now() })); } catch(e) {}
                        const fd2 = (fresh?.analysis?.range_analysis || {})[filterKey] || {};
                        const me2 = fd2.model_expectations || {};
                        if (Object.keys(me2).length) {
                            const st2 = fresh?.strategy || {};
                            const { cMin: c2, cMax: x2 } = _ensembleRange(me2);
                            el.style.minHeight = '';
                            el.innerHTML = _buildFilterHTML(filterKey, filterLabel, me2, st2, fd2.range);
                            _requestLLMAnalysis('dip-ai-llm-body', filterKey, filterLabel, me2, c2, x2, fresh.target_round, st2);
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
                _requestLLMAnalysis('dip-ai-llm-body', filterKey, filterLabel, modelExp, cMin, cMax, data.target_round, strategy);

            } catch (e) {
                console.error('[DeepInsightPanel]', e);
                _showError(el, e.message);
            }
        },

        refresh(containerId, filterKey, filterLabel) {
            this.render(containerId, filterKey, filterLabel, true);
        },

        async renderGroup(containerId, groupType, force = false) {
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
                    tail_digit: '끝수 분포'
                };
                const groupLabel = GROUP_LABELS[groupType] || groupType;

                // tail_digit needs range_analysis injected into analysis
                const analysis = { ...data.analysis, range_analysis: data.analysis?.range_analysis || {} };
                el.style.minHeight = '';
                el.innerHTML = _buildGroupHTML(groupType, analysis, data?.strategy || {});

                // 2-phase: LLM async analysis
                _requestGroupLLMAnalysis('dip-ai-llm-body', groupType, groupLabel, analysis, data?.strategy || {}, data.target_round);

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
