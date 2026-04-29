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

    // 11 base 토폴로지 (Master Plan 사용자 결정 #24) — lstm/transformer 폐기, TFT 흡수
    const MODEL_META = {
        xgboost:     { label: 'XGBoost',  dot: '#3B82F6', tag: '트리' },
        catboost:    { label: 'CatBoost', dot: '#14B8A6', tag: '카테고리' },
        tabnet:      { label: 'TabNet',   dot: '#A855F7', tag: 'attention' },
        cnn:         { label: 'CNN',      dot: '#EC4899', tag: '그리드' },
        gnn:         { label: 'GNN',      dot: '#EF4444', tag: '그래프' },
        markov:      { label: 'Markov',   dot: '#10B981', tag: '전이' },
        autoencoder: { label: 'AE',       dot: '#8B5CF6', tag: '이상치' },
        tft:         { label: 'TFT',      dot: '#F97316', tag: '시계열' },
        nbeats:      { label: 'N-BEATS',  dot: '#06B6D4', tag: '분해' },
        mhn:         { label: 'MHN',      dot: '#84CC16', tag: '메모리' },
        bayesian_nn: { label: 'Bayesian', dot: '#F59E0B', tag: '불확실성' }
    };

    const MODEL_ORDER = [
        'xgboost', 'catboost', 'tabnet',
        'cnn', 'gnn',
        'markov', 'autoencoder',
        'tft', 'nbeats',
        'mhn', 'bayesian_nn'
    ];

    // 백워드 호환: 폐기 모델 키 (API 응답에 와도 graceful skip)
    const DEPRECATED_MODEL_KEYS = new Set(['lstm', 'transformer']);

    // ── 캐시 ─────────────────────────────────────────────────────────────────
    let _memCache = null;
    let _memCacheTime = 0;

    // V4 필터 데이터 → 호환 payload 변환
    async function _getDataV4() {
        try {
            const baseUrl = (window.LANGCHAIN_CONFIG && window.LANGCHAIN_CONFIG.URL) || 'http://127.0.0.1:8000';
            const res = await fetch(`${baseUrl}/api/v4/filters/0`, { signal: AbortSignal.timeout(5000) });
            if (!res.ok) return null;
            const json = await res.json();
            if (!json.success || !json.filters) return null;
            const rangeAnalysis = {};
            for (const [key, fdata] of Object.entries(json.filters)) {
                if (fdata.model_expectations && Object.keys(fdata.model_expectations).length > 0) {
                    rangeAnalysis[key] = {
                        model_expectations: fdata.model_expectations,
                        ensemble_min: fdata.ensemble_min,
                        ensemble_max: fdata.ensemble_max,
                        ci: fdata.ci,
                        filter_value: fdata.filter_value,
                        primary_task: fdata.primary_task
                    };
                }
            }
            if (Object.keys(rangeAnalysis).length === 0) return null;
            return {
                success: true,
                target_round: json.target_round,
                _source: 'v4_weekly',
                analysis: { range_analysis: rangeAnalysis }
            };
        } catch (e) {
            return null;
        }
    }

    async function _getData(force = false) {
        const now = Date.now();
        // 메모리 캐시 우선 — 같은 회차면 force여도 재사용
        if (_memCache) {
            if (!force) return _memCache;
            // V4 우선 재시도
            const v4 = await _getDataV4();
            if (v4) { _memCache = v4; _memCacheTime = now; return _memCache; }
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
            } catch (e) { }
        }
        // 0. V4 주간 파이프라인 우선 시도 (즉시 응답)
        const v4Data = await _getDataV4();
        if (v4Data) {
            console.log(`⚡ [DeepInsightPanel] V4 필터 데이터 로드! (제${v4Data.target_round}회차)`);
            _memCache = v4Data; _memCacheTime = now;
            try { sessionStorage.setItem(CACHE_KEY, JSON.stringify({ data: v4Data, ts: now })); } catch (e) { }
            return v4Data;
        }
        // 1. 실시간 v3 폴백
        const data = await window.AIProxy.getDeepAnalysis();
        if (data) {
            _memCache = data; _memCacheTime = now;
            try { sessionStorage.setItem(CACHE_KEY, JSON.stringify({ data, ts: now })); } catch (e) { }
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

    // ── 앙상블 min/max 및 합의도 계산 ─────────────────────────────���─────────────
    function _ensembleRange(modelExp) {
        const mins = Object.values(modelExp).map(e => e.min).filter(v => v !== undefined);
        const maxs = Object.values(modelExp).map(e => e.max).filter(v => v !== undefined);
        if (!mins.length) return { cMin: '-', cMax: '-', agreement: 0 };

        // P8: __ensemble__ 키가 있으면 백엔드 가중 앙상블 값 우선 사용
        const ensEntry = modelExp['__ensemble__'];
        const cMin = ensEntry?.min ?? Math.round(mins.reduce((a, b) => a + b, 0) / mins.length);
        const cMax = ensEntry?.max ?? Math.round(maxs.reduce((a, b) => a + b, 0) / maxs.length);

        // P8: Bootstrap CI (sum/tail_sum/ac/filter_range 에만 존재)
        const ci = ensEntry?.ci || null;  // {lo_p10, lo_p90, hi_p10, hi_p90, band, level}

        // 합의도 계산 (표준편차 기반) — __ensemble__ 제외한 모델들만 사용
        const validForMids = Object.entries(modelExp)
            .filter(([k, e]) => k !== '__ensemble__' && e.min !== undefined && e.max !== undefined)
            .map(([, e]) => e);
        const mids = validForMids.map(e => (e.min + e.max) / 2);
        if (!mids.length) return { cMin, cMax, agreement: 0, recommendations: [], ci };

        const mean = mids.reduce((a, b) => a + b, 0) / mids.length;
        const variance = mids.reduce((acc, v) => acc + Math.pow(v - mean, 2), 0) / mids.length;
        const stdDev = Math.sqrt(variance);
        // 합의도 0~100 (표준편차가 작을수록 높음)
        const agreement = Math.max(0, Math.min(100, Math.round(100 - (stdDev * 5))));

        // [추가] 추천 모델 추출 (outlier 기반)
        const recommendations = _findOutliers(modelExp);

        return { cMin, cMax, agreement, recommendations, ci };
    }

    // ── 통계 계산 (분석 범위 기반) ───────────────────────────────────────────
    function _calculateQuantitativeStats(filterKey, range) {
        // AppState 또는 전역 allDrawData 모두 체크 (폴백 강화)
        let rawData = (window.AppState && window.AppState.allDrawData) || window.allDrawData;
        if (!rawData || !rawData.length) return null;

        // 필터 키 매핑 (내부 속성명으로 변환)
        const keyMap = {
            'sum': 'sum',
            'total_sum': 'sum',
            'tail_sum': 'sum',
            'ac': 'ac_value',
            'ac_value': 'ac_value',
            'odd': 'odd_count',
            'odd_even': 'odd_count',
            'high': 'high_count',
            'high_low': 'high_count',
            'low_high': 'high_count',
            'prime': 'prime_count',
            'prime_number': 'prime_count',
            'twin': 'twin_count',
            'twin_number': 'twin_count',
            'triangular': 'triangular_count',
            'triangular_number': 'triangular_count',
            'missing': 'missing_count',
            'missing_count': 'missing_count',
            'end_sum': 'end_sum',
            'tail_sum': 'end_sum',
            'number_band': 'entropy',
            'number_range': 'entropy',
            'consecutive': 'consecutive_count',
            'neighbor': 'neighbor_count',
            'carryover': 'carryover_count',
            'ac': 'ac_value',
            'ac_value': 'ac_value'
        };
        const dataKey = keyMap[filterKey] || filterKey;

        // [수정] range가 배열([min,max])이거나 유효하지 않은 숫자면 currentRange 또는 100으로 폴백
        const safeRange = (typeof range === 'number' && range > 0)
            ? range
            : ((window.AppState && window.AppState.currentRange) || window.currentRange || 100);

        const data = rawData.slice(0, safeRange);
        if (!data.length) return null;

        const values = data.map(d => {
            // [추가] 필드(sum)가 없는데 끝수합(tail_sum) 분석인 경우 numbers 배열로 즉석 계산
            if (d[dataKey] === undefined && (filterKey === 'tail_sum' || filterKey === 'sum') && d.numbers) {
                return d.numbers.reduce((a, b) => a + (b % 10), 0);
            }
            return d[dataKey];
        }).filter(v => typeof v === 'number');

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

    // ── 끝수 통계 계산 헬퍼 ──────────────────────────────────────────────────
    function _computeDigitStats(digit, rawData, analysisRange) {
        // [수정] analysisRange가 배열([0,4]) 또는 undefined일 경우 100 고정
        const rangeNum = (typeof analysisRange === 'number' && analysisRange > 10) ? analysisRange : 100;
        const data = (rawData || []).slice(0, rangeNum);
        if (!data.length) return null;

        // 회차별 해당 끝수 출현 개수 배열 (index 0 = 최신 회차)
        const counts = data.map(draw => draw.numbers.filter(n => n % 10 === digit).length);

        const totalAppear = counts.reduce((a, b) => a + b, 0);
        const avgPerDraw = (totalAppear / data.length).toFixed(2);
        const drawsWithDigit = counts.filter(c => c > 0).length;
        const presenceRate = ((drawsWithDigit / data.length) * 100).toFixed(1);

        // 현재 연속 미출 / 연속 출현 계산
        let currentAbsent = 0, currentPresent = 0;
        for (const c of counts) {
            if (c === 0) { if (currentPresent === 0) currentAbsent++; else break; }
            else { if (currentAbsent === 0) currentPresent++; else break; }
        }

        // 역대 최대 연속 미출 / 연속 출현
        let maxAbsent = 0, maxPresent = 0, tmpA = 0, tmpP = 0;
        for (const c of counts) {
            if (c === 0) { tmpA++; maxAbsent = Math.max(maxAbsent, tmpA); tmpP = 0; }
            else { tmpP++; maxPresent = Math.max(maxPresent, tmpP); tmpA = 0; }
        }

        // 최근 10회 출현율
        const r10 = counts.slice(0, 10);
        const r10Avg = (r10.reduce((a, b) => a + b, 0) / r10.length).toFixed(2);
        const r10Rate = ((r10.filter(c => c > 0).length / r10.length) * 100).toFixed(0);

        // 출현 분포: 0개 / 1개 / 2개 / 3개+
        const dist = { 0: 0, 1: 0, 2: 0, '3+': 0 };
        counts.forEach(c => { if (c === 0) dist[0]++; else if (c === 1) dist[1]++; else if (c === 2) dist[2]++; else dist['3+']++; });

        const statusText = currentAbsent > 0
            ? `현재 {{warn:${currentAbsent}회 연속 미출현}} (역대 최대 미출: ${maxAbsent}회)`
            : `현재 {{good:${currentPresent}회 연속 출현 중}} (역대 최대 연속출: ${maxPresent}회)`;

        return {
            digit, range: data.length,
            totalAppear, avgPerDraw, drawsWithDigit, presenceRate,
            currentAbsent, currentPresent, maxAbsent, maxPresent,
            r10Avg, r10Rate, dist, statusText
        };
    }

    // ── LLM 비동기 분석 호출 ──────────────────────────────────────────────────
    async function _requestLLMAnalysis(aiBodyId, filterKey, filterLabel, modelExp, cMin, cMax, targetRound, strategy, analysisRange = 100, allDrawData = null) {
        const flowEl = document.getElementById('dip-v3-content-flow');
        const patternEl = document.getElementById('dip-v3-content-pattern');
        const strategyEl = document.getElementById('dip-v3-content-strategy');

        if (!flowEl || !patternEl || !strategyEl) return;

        // ═══════════════════════════════════════════════════════════════════
        // [끝수 전용 분석] digit0 ~ digit9 필터 감지 → 맞춤 통계 기반 프롬프트
        // ═══════════════════════════════════════════════════════════════════
        const digitMatch = filterKey && filterKey.match(/^digit(\d)$/);
        if (digitMatch) {
            const digit = parseInt(digitMatch[1]);
            // [수정] 직접 전달받은 allDrawData를 우선 사용, 없으면 전역 변수 폴백
            const rawData = allDrawData || (window.AppState && window.AppState.allDrawData) || window.allDrawData || [];
            const ds = _computeDigitStats(digit, rawData, analysisRange);

            if (ds) {
                // 통계 카드 즉시 노출
                patternEl.innerHTML = `
                    <div style="background:rgba(241,245,249,0.5);border:1px solid #e2e8f0;border-radius:12px;padding:12px;margin-bottom:12px;display:flex;flex-wrap:wrap;gap:10px;">
                        <div style="font-size:0.75rem;color:#64748b;font-weight:700;width:100%;border-bottom:1px solid #f1f5f9;padding-bottom:4px;margin-bottom:4px">
                            최근 ${ds.range}회 ${digit}끝수 통계
                        </div>
                        <div style="flex:1;min-width:80px"><div style="font-size:0.7rem;color:#94a3b8">출현율</div><div style="font-size:0.9rem;font-weight:800;color:#1e293b">${ds.presenceRate}%</div></div>
                        <div style="flex:1;min-width:80px"><div style="font-size:0.7rem;color:#94a3b8">회당 평균</div><div style="font-size:0.9rem;font-weight:800;color:#1e293b">${ds.avgPerDraw}개</div></div>
                        <div style="flex:1;min-width:80px"><div style="font-size:0.7rem;color:#94a3b8">최근 10회 평균</div><div style="font-size:0.9rem;font-weight:800;color:#1e293b">${ds.r10Avg}개 (${ds.r10Rate}%)</div></div>
                        <div style="flex:1;min-width:80px"><div style="font-size:0.7rem;color:#94a3b8">최대 연속 미출</div><div style="font-size:0.9rem;font-weight:800;color:#ef4444">${ds.maxAbsent}회</div></div>
                        <div style="flex:1;min-width:80px"><div style="font-size:0.7rem;color:#94a3b8">현재 상태</div><div style="font-size:0.9rem;font-weight:800;color:${ds.currentAbsent > 0 ? '#ef4444' : '#22c55e'}">${ds.currentAbsent > 0 ? ds.currentAbsent + '회 미출' : ds.currentPresent + '회 연속출'}</div></div>
                        <div style="flex:1;min-width:120px"><div style="font-size:0.7rem;color:#94a3b8">분포(0/1/2/3+개)</div><div style="font-size:0.9rem;font-weight:800;color:#1e293b">${ds.dist[0]}/${ds.dist[1]}/${ds.dist[2]}/${ds.dist['3+']}회</div></div>
                    </div>
                    <div id="dip-pattern-llm-text" style="font-size:0.85rem;color:#94a3b8;font-style:italic;">${digit}끝수 패턴 심층 분석 중...</div>`;

                // 끝수 전용 프롬프트 빌드
                const prompt = `# Role: 대한민국 최고의 로또 끝수(끝자리) 전문 통계 분석가
# Target: ${targetRound || ''}회차 ${digit}끝수 전용 심층 분석
# 분석 범위: 최근 ${ds.range}회차 실측 데이터

# ${digit}끝수 핵심 통계:
- 출현율: ${ds.range}회 중 ${ds.drawsWithDigit}회 출현 (${ds.presenceRate}%)
- 회당 평균 출현: ${ds.avgPerDraw}개
- 현재 상태: ${ds.currentAbsent > 0 ? `${ds.currentAbsent}회 연속 미출현` : `${ds.currentPresent}회 연속 출현 중`}
- 최대 연속 미출 기록: ${ds.maxAbsent}회 / 최대 연속 출현 기록: ${ds.maxPresent}회
- 최근 10회 평균: ${ds.r10Avg}개 (출현율 ${ds.r10Rate}%)
- 출현 분포: 0개=${ds.dist[0]}회, 1개=${ds.dist[1]}회, 2개=${ds.dist[2]}회, 3개이상=${ds.dist['3+']}회
- AI 딥러닝 앙상블 예측 범위: ${cMin}~${cMax}개

# 분석 요청 (반드시 아래 3단계 구조로 답변하라):
1. [흐름진단]: ${digit}끝수의 현재 상태(미출 ${ds.currentAbsent}회 또는 연속 ${ds.currentPresent}회)를 역대 최대 기록(최대 미출 ${ds.maxAbsent}회)과 비교하여 현재 흐름이 과열인지 침체인지 진단하라. 반등 가능성도 평가할 것.
2. [패턴분석]: 출현 분포(0/1/2/3+개 빈도), 최근 10회 평균(${ds.r10Avg})과 전체 평균(${ds.avgPerDraw})의 차이, 그리고 현재 미출/연속 상태가 통계적으로 어느 위치에 있는지 분석하라. ${targetRound}회차에 ${digit}끝이 출현할 확률과 예상 개수를 수치 근거로 제시하라.
3. [필승공략]: 위 분석을 종합하여 ${targetRound}회차 조합 시 ${digit}끝수를 몇 개 포함해야 하는지 구체적 범위(예: 최소 1개 ~ 최대 2개)를 확신 있게 제언하라.

# 출력 규칙:
- {{good:값}} = 유리/긍정, {{info:값}} = 중립/관찰, {{warn:값}} = 주의/위험
- 전문가 어조, 구체적 수치 근거 필수, 인사말 생략`;

                const digitCurrentAbsent = ds.currentAbsent; // closure 보정

                try {
                    const result = await window.AIProxy.invoke({
                        prompt,
                        analysisType: `digit_${digit}`,
                        targetRound: targetRound || 0,
                        responseStyle: 'expert'
                    });

                    // 구조화 응답 처리 (끝수용: trend/pattern/recommendation)
                    if (result && (result.trend || result.pattern || result.recommendation)) {
                        flowEl.innerHTML = _cleanLLMText(result.trend || '');
                        const ptEl = document.getElementById('dip-pattern-llm-text');
                        if (ptEl) {
                            ptEl.innerHTML = _cleanLLMText(result.pattern || '');
                            ptEl.style.color = '#475569';
                            ptEl.style.fontStyle = 'normal';
                        } else {
                            patternEl.innerHTML = _cleanLLMText(result.pattern || '');
                        }
                        strategyEl.innerHTML = _cleanLLMText(result.recommendation || '');
                        return;
                    }
                    // 텍스트 파싱 폴백
                    const text = _extractLLMText(result, filterKey);
                    if (text) {
                        const parts = _splitPremiumText(text);
                        flowEl.innerHTML = _cleanLLMText(parts.flow);
                        const ptEl = document.getElementById('dip-pattern-llm-text');
                        if (ptEl) { ptEl.innerHTML = _cleanLLMText(parts.pattern); ptEl.style.color = '#475569'; ptEl.style.fontStyle = 'normal'; }
                        else patternEl.innerHTML = _cleanLLMText(parts.pattern);
                        strategyEl.innerHTML = _cleanLLMText(parts.strategy);
                        return;
                    }
                } catch (e) { /* fallback */ }

                // AI 실패 시 통계 기반 기본 메시지 표시
                const absOrPres = ds.currentAbsent > 0
                    ? `현재 ${ds.currentAbsent}회 연속 미출현 중입니다 (역대 최대 미출: ${ds.maxAbsent}회).`
                    : `현재 ${ds.currentPresent}회 연속 출현 중입니다.`;
                flowEl.innerHTML = `최근 ${ds.range}회 분석 시 ${digit}끝 출현율은 ${ds.presenceRate}% (평균 ${ds.avgPerDraw}개)입니다. ${absOrPres}`;
                const ptElFb = document.getElementById('dip-pattern-llm-text');
                const patternFb = `최근 10회 평균 ${ds.r10Avg}개 / 전체 평균 ${ds.avgPerDraw}개. 분포: 0개=${ds.dist[0]}회, 1개=${ds.dist[1]}회, 2개=${ds.dist[2]}회.`;
                if (ptElFb) { ptElFb.innerHTML = patternFb; ptElFb.style.color = '#475569'; ptElFb.style.fontStyle = 'normal'; }
                strategyEl.innerHTML = `AI 앙상블 예측: ${cMin}~${cMax}개 구간 권장.`;
            }
            return; // digit 처리 완료 후 반드시 종료
        }

        // ═══════════════════════════════════════════════════════════════════
        // [일반 필터 분석] — 기존 로직 유지
        // ═══════════════════════════════════════════════════════════════════

        // [수정] analysisRange가 배열([min,max])이면 회차 범위(숫자)로 정규화
        // 예: [113, 163] → "113,163회차" 오출력 방지
        const safeAnalysisRange = (typeof analysisRange === 'number' && analysisRange > 0)
            ? analysisRange
            : ((window.AppState && window.AppState.currentRange) || window.currentRange || 100);

        // [수정] 통계 요약 박스는 이미 상단 헤더 영역에 표시되므로 패턴 분석 칸에는 중복 제거
        // 통계는 프롬프트용으로만 계산
        const stats = _calculateQuantitativeStats(filterKey, safeAnalysisRange);

        // 패턴 분석 칸은 로딩 플레이스홀더만 (기울기 없음)
        patternEl.innerHTML = `<div id="dip-pattern-llm-text" style="font-size:0.95rem; color:#94a3b8;">데이터의 통계적 패턴을 심층 해석 중입니다...</div>`;


        const modelSummary = MODEL_ORDER
            .filter(k => modelExp[k])
            .map(k => `${MODEL_META[k].label}: ${modelExp[k].min}~${modelExp[k].max}`)
            .join(', ');

        const prompt =
            `# Role: 대한민국 최고의 로또 통계 분석 전문가 (${filterLabel} 전문)
# Target: ${targetRound || ''}회차 ${filterLabel} 심층 분석 보고서
# Data Context:
- 분석 범위: 최근 ${safeAnalysisRange}회차 전수 데이터 기반
- 통계 분석: 평균 ${stats?.avg || 'N/A'}, 범위 ${stats?.min || 'N/A'}~${stats?.max || 'N/A'}, 표준편차 ${stats?.stdDev || 'N/A'}, 추세 ${stats?.trend || 'N/A'}
- 7개 개별 모델 예측: ${modelSummary}
- AI 앙상블 종합 예측 범위: ${cMin}~${cMax}
- 현재 전략 가이드 (기본): ${(strategy.overall_strategy && strategy.overall_strategy.short_advice) || 'N/A'}

# 분석 요청 사항 (반드시 아래 3단계 구조로 답변하라):
1. [흐름진단]: 통계 지표와 AI 예측치를 교차 검증하여 현재 ${filterLabel}의 흐름을 정밀 진단하라. 과열 또는 침체 여부와 반등 가능성을 전문가답게 분석할 것.
2. [패턴분석]: 통계 지표(표준편차, 추세)를 기반으로 이번 회차의 '패턴 변곡점'을 제시하라. 사람이 놓치기 쉬운 숨겨진 통계적 의미를 명확히 짚어줄 것.
3. [필승공략]: AI 앙상블 결과와 통계적 추세를 융합하여 ${targetRound}회차 최종 필터 범위와 확신 있는 베팅 가이드를 제언하라.

# 출력 규칙:
- 강조할 수치나 키워드는 반드시 {{good:값}}, {{info:값}}, {{warn:위험}} 태그로 감싸라.
- 전문가답게 확신 있는 어조를 사용하고, 구체적인 수치 기반의 인사이트를 제공하라.`;

        try {
            const result = await window.AIProxy.invoke({
                prompt,
                analysisType: filterKey,
                targetRound: targetRound || 0,
                responseStyle: 'expert'
            });

            // [수정] 구조화된 응답 {trend, pattern, recommendation} 우선 직접 주입
            if (result && (result.trend || result.pattern || result.recommendation)) {
                flowEl.innerHTML = _cleanLLMText(result.trend || '');
                const patternTextEl = document.getElementById('dip-pattern-llm-text');
                const patternContent = _cleanLLMText(result.pattern || '');
                if (patternTextEl) {
                    patternTextEl.innerHTML = patternContent;
                    patternTextEl.classList.remove('italic', 'text-gray-400');
                    patternTextEl.style.color = '#475569';
                    patternTextEl.style.fontStyle = 'normal'; // [수정] inline italic 초기화
                } else {
                    patternEl.innerHTML = patternContent;
                }
                strategyEl.innerHTML = _cleanLLMText(result.recommendation || '');
                return;
            }

            // [폴백] 단일 텍스트 응답인 경우 파싱
            const text = _extractLLMText(result, filterKey);
            if (text) {
                const parts = _splitPremiumText(text);
                flowEl.innerHTML = _cleanLLMText(parts.flow);
                const patternTextEl = document.getElementById('dip-pattern-llm-text');
                if (patternTextEl) {
                    patternTextEl.innerHTML = _cleanLLMText(parts.pattern);
                    patternTextEl.classList.remove('italic', 'text-gray-400');
                    patternTextEl.style.color = '#475569';
                    patternTextEl.style.fontStyle = 'normal'; // [수정] inline italic 초기화
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

    // 프리미엄 리포트용 텍스트 분할 유틸리티 (강화된 파싱 로직)
    function _splitPremiumText(text) {
        if (!text) return { flow: '', pattern: '', strategy: '' };

        // 1. 섹션 헤더 검색용 정규식 (유연한 매칭 지원)
        const flowRegex = /(?:[#*\s]*[1]\.?\s*\[?(?:흐름|진단|Flow)\]?|^[#*\s]*흐름\s*진단)[:\-\s]*/i;
        const patternRegex = /(?:[#*\s]*[2]\.?\s*\[?(?:패턴|분석|Pattern)\]?|^[#*\s]*패턴\s*분석)[:\-\s]*/i;
        const strategyRegex = /(?:[#*\s]*[3]\.?\s*\[?(?:전략|제언|공략|필승|Strategy)\]?|^[#*\s]*(?:전략\s*제언|필승\s*공략))[:\-\s]*/i;

        const lines = text.split('\n');
        let flow = '', pattern = '', strategy = '';
        let current = '';

        lines.forEach(line => {
            const l = line.trim();
            if (!l) return;

            // 섹션 감지 및 헤더 이후 텍스트 추출 시도
            if (flowRegex.test(l)) {
                current = 'flow';
                const content = l.replace(flowRegex, '').trim();
                if (content) flow += content + ' ';
                return;
            }
            if (patternRegex.test(l)) {
                current = 'pattern';
                const content = l.replace(patternRegex, '').trim();
                if (content) pattern += content + ' ';
                return;
            }
            if (strategyRegex.test(l)) {
                current = 'strategy';
                const content = l.replace(strategyRegex, '').trim();
                if (content) strategy += content + ' ';
                return;
            }

            // 현재 활성화된 섹션에 내용 누적 (특수문자 제거 후)
            const cleanLine = l.replace(/^[#*\-\+\s]+/, '').trim();
            if (!cleanLine) return;

            if (current === 'flow') flow += cleanLine + ' ';
            else if (current === 'pattern') pattern += cleanLine + ' ';
            else if (current === 'strategy') strategy += cleanLine + ' ';
            else if (!current) flow += cleanLine + ' '; // 헤더 전 텍스트는 흐름진단으로 간주
        });

        // 결과 반환 (누락 시 기본 메시지)
        return {
            flow: flow.trim() || '최근 데이터 흐름을 정밀 분석하고 있습니다.',
            pattern: pattern.trim() || 'AI 기술적 패턴 분석 결과를 생성 중입니다.',
            strategy: strategy.trim() || '최종 필승 공략 및 전략을 수립하고 있습니다.'
        };
    }

    // AIProxy 응답에서 텍스트 추출 — 다양한 응답 구조 대응
    function _extractLLMText(result, filterKey) {
        if (!result) return null;
        const direct = result.response || result.content || result.answer || result.report || result.text;
        if (direct) return _cleanLLMText(direct, filterKey);
        // {trend, pattern, recommendation} 구조 (Python RAG 응답)
        const parts = [];
        if (result.trend) parts.push(result.trend);
        if (result.pattern) parts.push(result.pattern);
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
        const { cMin, cMax, agreement, recommendations } = _ensembleRange(modelExp);
        const targetRound = _memCache?.target_round || '';
        
        // 홀수/짝수 개수(0-6), 저번호/고번호 개수(0-6)는 범주형으로 취급
        const isCategorical = ['odd_even', 'low_high', 'odd', 'even', 'low', 'high', 'high_low'].includes(filterKey);
        const isDigit = filterKey.startsWith('digit');

        // 비율 패턴 변환기 (홀짝/저고 전용)
        const formatPattern = (val) => {
            if (val === undefined || val === null || isNaN(parseInt(val))) return val || '-';
            const v = parseInt(val);
            if (['odd', 'even', 'odd_even'].includes(filterKey)) return `${v}:${6 - v}`;
            if (['low', 'high', 'low_high', 'high_low'].includes(filterKey)) return `${v}:${6 - v}`;
            return v;
        };

        let rangeDisplay = '';
        if (isCategorical) {
            // 범주형인 경우 (비율 형태 출력)
            if (recommendations && recommendations.length > 0) {
                rangeDisplay = recommendations.map(r => formatPattern(r)).join(', ');
            } else if (cMin !== Infinity && cMax !== -Infinity) {
                rangeDisplay = (cMin === cMax) ? formatPattern(cMin) : `${formatPattern(cMin)} ~ ${formatPattern(cMax)}`;
            } else {
                rangeDisplay = '분석 데이터 없음';
            }
        } else {
            // 수치형인 경우 (끝수 등)
            if (recommendations && recommendations.length > 0) {
                rangeDisplay = recommendations.join(', ');
            } else if (cMin !== Infinity && cMax !== -Infinity) {
                rangeDisplay = (cMin === cMax) ? cMin : `${cMin} ~ ${cMax}`;
            } else {
                rangeDisplay = '분석 데이터 없음';
            }
        }

        return `
        <div class="dip-root">
            <!-- [Header] Dark Premium -->
            <header class="dip-v3-header" style="background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);">
                <div class="dip-v3-title-group" style="flex: 1;">
                    <div style="display:flex; align-items:center; gap:12px;">
                        <div style="background:rgba(255,255,255,0.1); padding:8px; border-radius:10px; display:flex; align-items:center; justify-content:center;">
                            <span class="material-symbols-outlined" style="font-size:24px; color:#38bdf8;">psychology</span>
                        </div>
                        <div>
                            <h2 style="color:white; margin:0; font-size:1.1rem; font-weight:800;">AI 프리미엄 전략 리포트</h2>
                            <p style="color:rgba(255,255,255,0.5); margin:2px 0 0 0; font-size:0.75rem; font-weight:600; text-transform:uppercase; letter-spacing:0.05em;">INTELLIGENT ANALYSIS — ${filterLabel}</p>
                        </div>
                    </div>
                </div>

                <!-- [Digit Selection Buttons in Header] -->
                ${isDigit ? `
                <div style="display:flex; gap:12px; align-items: center; margin-left: 20px;">
                    ${[0, 1, 2, 3, 4, 5, 6, 7, 8, 9].map(i => {
                        const isActive = filterKey === 'digit' + i;
                        return `
                        <button onclick="if(window.changeGraphType) window.changeGraphType('${i}끝')" 
                                style="
                                    background: transparent;
                                    color: ${isActive ? '#ffffff' : 'rgba(255,255,255,0.4)'};
                                    border: none;
                                    padding: 8px 4px;
                                    font-size: 0.9rem;
                                    font-weight: ${isActive ? '900' : '600'};
                                    cursor: pointer;
                                    transition: all 0.2s;
                                    border-bottom: 3px solid ${isActive ? '#38bdf8' : 'transparent'};
                                    display: flex;
                                    align-items: center;
                                    justify-content: center;
                                    min-width: 40px;
                                "
                                onmouseover="if(!${isActive}) { this.style.color='#ffffff'; this.style.borderBottom='3px solid rgba(56, 189, 248, 0.3)'; }"
                                onmouseout="if(!${isActive}) { this.style.color='rgba(255,255,255,0.4)'; this.style.borderBottom='3px solid transparent'; }"
                        >${i}끝</button>`;
                    }).join('')}
                </div>
                ` : ''}
            </header>

            <!-- [Ensemble Summary] -->
            <div class="dip-v3-ensemble-box" style="background:#f8fafc; border-bottom:1px solid #f1f5f9; padding:1.5rem 2rem;">
                <div class="dip-v3-ens-main" style="display:flex; align-items:center; justify-content:space-between; gap:2rem;">
                    <div class="dip-v3-ens-info">
                        <span class="dip-v3-ens-label" style="font-size:0.75rem; color:#64748b; font-weight:700; text-transform:uppercase; margin-bottom:6px; display:block;">앙상블 종합 예측 범위</span>
                        <div class="dip-v3-ens-value" style="display:flex; align-items:baseline; gap:12px;">
                            <span class="dip-v3-ens-range" style="font-size:2.2rem; font-weight:900; color:#0f172a; letter-spacing:-1px;">${cMin} ~ ${cMax}</span>
                            <span class="dip-v3-ens-avg" style="font-size:0.95rem; color:#2563eb; font-weight:800; background:#dbeafe; padding:4px 10px; border-radius:8px; border:1px solid #bfdbfe;">평균 ${((cMin + cMax) / 2).toFixed(1)}</span>
                        </div>
                        ${ci ? `
                        <!-- P8: Bootstrap CI 밴드 -->
                        <div style="margin-top:10px;">
                            <div style="display:flex; align-items:center; gap:8px; margin-bottom:4px;">
                                <span style="font-size:0.68rem; color:#64748b; font-weight:700; text-transform:uppercase; letter-spacing:0.04em;">${ci.level} 신뢰구간</span>
                                <span style="font-size:0.68rem; color:#7c3aed; font-weight:800; background:#ede9fe; padding:2px 7px; border-radius:5px; border:1px solid #ddd6fe;">${ci.band}</span>
                                <span style="font-size:0.62rem; color:#94a3b8; font-weight:500;">부트스트랩 ${ci.n_boot}회</span>
                            </div>
                            <!-- CI 시각 바 -->
                            ${(() => {
                                if (typeof cMin !== 'number' || typeof cMax !== 'number') return '';
                                const lo = ci.lo_p10, hi = ci.hi_p90;
                                const span = hi - lo || 1;
                                const coreLo = Math.max(0, Math.round((cMin - lo) / span * 100));
                                const coreW  = Math.min(100, Math.round((cMax - cMin) / span * 100));
                                return `
                                <div style="position:relative; height:8px; background:#e9d5ff; border-radius:4px; overflow:hidden;">
                                    <div style="position:absolute; left:${coreLo}%; width:${coreW}%; height:100%; background:linear-gradient(90deg,#7c3aed,#5b21b6); border-radius:4px;"></div>
                                </div>
                                <div style="display:flex; justify-content:space-between; margin-top:2px;">
                                    <span style="font-size:0.6rem; color:#7c3aed; font-weight:700;">${lo}</span>
                                    <span style="font-size:0.6rem; color:#7c3aed; font-weight:700;">${hi}</span>
                                </div>`;
                            })()}
                        </div>` : ''}
                    </div>
                    <div class="dip-v3-ens-gauge" style="width:240px; background:white; padding:12px; border-radius:16px; border:1px solid #e2e8f0; box-shadow:0 1px 2px rgba(0,0,0,0.05);">
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                            <span style="font-size:0.7rem; color:#64748b; font-weight:700;">모델 합의도</span>
                            <span style="font-size:0.8rem; color:#1e293b; font-weight:800;">${agreement}%</span>
                        </div>
                        <div class="dip-v3-gauge-track" style="height:10px; background:#f1f5f9; border-radius:5px; overflow:hidden;">
                            <div class="dip-v3-gauge-bar" style="width: ${agreement}%; height:100%; background:linear-gradient(90deg, #3b82f6, #2563eb); border-radius:5px; transition:width 1s ease-out;"></div>
                        </div>
                        <div style="font-size:0.65rem; color:#94a3b8; font-weight:600; text-align:right; margin-top:6px;">7개 딥러닝 모델 교차 검증 완료</div>
                    </div>
                </div>
            </div>

            <div style="padding: 1rem 2rem 2rem 2rem;">
                <!-- [Middle] Compact Model Grid -->
                <div class="dip-v3-model-grid">
                    ${MODEL_ORDER.map(key => {
            const meta = MODEL_META[key];
            const exp = modelExp[key];
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
                            전체 모델 데이터와 최근 추세를 종합하여 흐름을 정밀 진단하고 있습니다.
                        </div>
                    </div>
                    <div class="dip-v3-col" style="border-top: 1px solid #f1f5f9; padding-top: 2rem; margin-bottom: 1rem;">
                        <div class="dip-v3-col-header">
                            <span class="dip-v3-col-title">패턴 분석</span>
                        </div>
                        <div class="dip-v3-col-content" id="dip-v3-content-pattern">
                            통계적 범위 내 특이 패턴 및 소외 구간에 대한 기술적 분석을 진행 중입니다.
                        </div>
                    </div>
                </div>

                <!-- [Bottom] Winning Strategy -->
                <div class="dip-v3-strategy" style="background:#0f172a; padding:1.75rem 2rem; border-radius:24px; color:white; margin-top:1.5rem; box-shadow:0 20px 25px -5px rgba(0,0,0,0.1), 0 10px 10px -5px rgba(0,0,0,0.04); border:1px solid rgba(255,255,255,0.05);">
                    <div class="dip-v3-strat-header" style="display:flex; align-items:center; gap:10px; margin-bottom:12px;">
                        <span class="material-symbols-outlined" style="font-size:20px; color:#38bdf8;">verified</span>
                        <span class="dip-v3-strat-title" style="font-size:1rem; font-weight:800; color:#38bdf8; letter-spacing:-0.5px;">${targetRound}회차 필승 공략</span>
                    </div>
                    <div class="dip-v3-strat-content" id="dip-v3-content-strategy" style="font-size:0.95rem; line-height:1.8; color:rgba(255,255,255,0.9); font-weight:400; word-break:keep-all;">
                        분석 결과를 토대로 최적의 필터링 전략과 조합 가이드를 도출하고 있습니다.
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
                recFilter = '맞춤분석';

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
                recFilter = '번호대별';
                const bands = analysis.number_band_analysis || [];
                if (!bands.length) { bodyHTML = _noDataHTML(); break; }
                const max = Math.max(...bands.map(b => b.exp || 0)) || 1;
                bodyHTML = `<div class="dip-group-list">
                    ${bands.map((b, i) => `
                    <div class="dip-group-row">
                        <span class="dip-group-name">${b.label}</span>
                        <div class="dip-group-bar-wrap">
                            <div class="dip-group-bar" style="width:${(b.exp / max * 100).toFixed(1)}%;background:${['#3b82f6', '#22c55e', '#f97316', '#a855f7', '#ef4444'][i % 5]}"></div>
                        </div>
                        <span class="dip-group-val">기대 <strong>${b.exp}</strong>개</span>
                    </div>`).join('')}
                </div>`;
                break;
            }
            case 'magic_square': {
                groupLabel = '9궁 분석';
                recFilter = '9궁분석';
                const squares = analysis.magic_square_analysis || [];
                if (!squares.length) { bodyHTML = _noDataHTML(); break; }
                const sorted = [...squares].sort((a, b) => (b.exp || 0) - (a.exp || 0));
                const max = (sorted[0] && sorted[0].exp) || 1;
                const COLORS = ['#3b82f6', '#22c55e', '#f97316', '#a855f7', '#ef4444', '#14b8a6', '#f59e0b', '#ec4899', '#6366f1'];
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
                recFilter = '로또용지';
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
                                <div class="dip-group-bar" style="width:${(r.exp / maxR * 100).toFixed(1)}%;background:#3b82f6"></div>
                            </div>
                            <span class="dip-group-val"><strong>${r.exp}</strong>개</span>
                        </div>`).join('')}
                    </div>
                    <div>
                        <div class="dip-paper-subtitle">열 (세로)</div>
                        ${cols.map(c => `<div class="dip-group-row">
                            <span class="dip-group-name">${c.label}</span>
                            <div class="dip-group-bar-wrap">
                                <div class="dip-group-bar" style="width:${(c.exp / maxC * 100).toFixed(1)}%;background:#22c55e"></div>
                            </div>
                            <span class="dip-group-val"><strong>${c.exp}</strong>개</span>
                        </div>`).join('')}
                    </div>
                </div>`;
                break;
            }
            case 'regression': {
                groupLabel = '회귀분석 종합';
                recFilter = '';
                const REGRESSION_FILTERS = ['총합', '끝수합', 'AC값', '홀짝', '저고', '소수', '합성수', '연속', '이월', '이웃', '핫콜드', '미출현'];
                const recs = (strategy.filter_recommendations || [])
                    .filter(r => REGRESSION_FILTERS.some(name => r.filter?.includes(name.replace('비율', ''))))
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
                recFilter = '끝수 분석';

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
                            <span style="font-size:11px;color:#94a3b8;font-weight:600;">출현 확률: ${(exp * 100).toFixed(0)}%</span>
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
                        종합 통계 데이터의 흐름을 분석하고 있습니다. 잠시만 기다려주세요.
                    </div>
                </div>
                <div class="dip-v3-col" style="border-top: 1px solid #f1f5f9; padding-top: 2rem; margin-bottom: 1rem;">
                    <div class="dip-v3-col-header">
                        <span class="dip-v3-col-title">패턴 분석</span>
                    </div>
                    <div class="dip-v3-col-content" id="dip-v3-group-pattern">
                        과거 데이터와 현재 흐름의 기술적 패턴을 정밀 검증 중입니다.
                    </div>
                </div>
            </div>

            <!-- [Bottom] Winning Strategy -->
            <div class="dip-v3-strategy" style="margin: 0 2rem 2rem 2rem; border-radius: 1rem;">
                <div class="dip-v3-strat-header">
                    <span class="dip-v3-strat-title">${targetRound}회차 필승 공략</span>
                </div>
                <div class="dip-v3-strat-content" id="dip-v3-group-strategy">
                    최적의 필터링 전략과 핵심 공략 지점을 도출하고 있습니다.
                </div>
            </div>
        `;
    }

    // ── 그룹용 LLM 비동기 분석 호출 ───────────────────────────────────────────
    async function _requestGroupLLMAnalysis(aiBodyId, groupType, groupLabel, analysis, strategy, targetRound) {
        const flowEl = document.getElementById('dip-v3-group-flow');
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
            `# Role: 대한민국 최고의 로또 통계 분석 전문가 (${groupLabel} 전문)
# Target: ${targetRound || ''}회차 ${groupLabel} 프리미엄 전략 리포트
# Analysis Summary: ${summaryText}

# 분석 요청 사항 (반드시 아래 3단계 구조로 답변하라):
1. [흐름진단]: 위 요약된 통계 데이터를 바탕으로 최근 ${groupLabel}의 전반적인 흐름과 추세를 전문가적 관점에서 진단하라. 현재 구간이 과열인지 침체인지 명확히 짚어줄 것. (3~4문장)
2. [패턴분석]: 제공된 데이터에서 도출되는 핵심 패턴, 특이 사항, 그리고 과거 유사 패턴과의 상관관계를 분석하라. 단순히 숫자를 나열하지 말고 '왜' 이런 패턴이 중요한지 설명할 것. (3~4문장)
3. [필승공략]: 분석 결과를 토대로 ${targetRound}회차에서 사용자가 반드시 적용해야 할 핵심 전략과 필터링 가이드를 구체적으로 제언하라. 확신 있는 어조를 사용할 것. (2~3문장)

# 출력 규칙:
- 강조할 수치나 키워드는 반드시 {{good:값}} (유리), {{info:값}} (관찰), {{warn:위험}} (주의) 태그로 감싸라.
- 답변은 전문적이고 논리적이어야 하며, 사용자에게 실질적인 도움을 주는 인사이트를 포함하라.
- 불필요한 미사여구나 인사말은 생략하고 분석 내용에 집중하라.`;

        try {
            const result = await window.AIProxy.invoke({
                prompt,
                analysisType: groupType,
                targetRound: targetRound || 0,
                responseStyle: 'expert'
            });

            // [수정] 구조화된 응답 {trend, pattern, recommendation} 우선 직접 주입
            if (result && (result.trend || result.pattern || result.recommendation)) {
                flowEl.innerHTML = _cleanLLMText(result.trend || '');
                patternEl.innerHTML = _cleanLLMText(result.pattern || '');
                strategyEl.innerHTML = _cleanLLMText(result.recommendation || '');
                return;
            }

            // [폴백] 단일 텍스트 응답인 경우 파싱
            const text = _extractLLMText(result, groupType);
            if (text) {
                const parts = _splitPremiumText(text);
                flowEl.innerHTML = _cleanLLMText(parts.flow);
                patternEl.innerHTML = _cleanLLMText(parts.pattern);
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
            font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, system-ui, Roboto, sans-serif;
            border-radius: 1.5rem;
            overflow: hidden;
            background: #ffffff;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 10px 15px -3px rgba(0, 0, 0, 0.1);
            margin-bottom: 2rem;
            border: 1px solid #f1f5f9;
            width: 100%; box-sizing: border-box;
            display: flex;
            flex-direction: column;
            transition: all 0.3s ease;
        }

        /* [Header] Dark Premium */
        .dip-v3-header {
            padding: 1.5rem 2rem;
            display: flex;
            align-items: center;
            justify-content: space-between;
            color: white;
        }
        .dip-v3-title-group h2 { font-size: 1.25rem; font-weight: 800; margin: 0; letter-spacing: -0.025em; }
        .dip-v3-title-group p { font-size: 0.8rem; color: rgba(255,255,255,0.6); margin-top: 2px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; }

        /* [Ensemble Summary Section] */
        .dip-v3-ensemble-box {
            padding: 1.75rem 2rem;
            background: #f8fafc;
            border-bottom: 1px solid #f1f5f9;
        }
        .dip-v3-ens-main {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 2rem;
        }

        /* [Grid] Compact Models */
        .dip-v3-model-grid {
            display: grid;
            grid-template-columns: repeat(7, 1fr);
            gap: 10px;
            margin-bottom: 2.5rem;
        }
        .dip-v3-model-card {
            background: #ffffff; 
            border: 1px solid #e2e8f0; 
            border-radius: 1rem;
            padding: 12px 8px; 
            text-align: center; 
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
            cursor: default;
        }
        .dip-v3-model-card:hover { 
            border-color: #3b82f6; 
            transform: translateY(-4px); 
            box-shadow: 0 10px 15px -3px rgba(59, 130, 246, 0.1); 
        }
        .dip-v3-m-label { font-size: 0.65rem; color: #94a3b8; font-weight: 800; text-transform: uppercase; display: block; margin-bottom: 6px; letter-spacing: 0.025em; }
        .dip-v3-m-val { font-size: 0.95rem; font-weight: 900; color: #1e293b; font-family: 'JetBrains Mono', monospace; }

        /* [Body] 1-Column Content */
        .dip-v3-body { display: block; margin-bottom: 2rem; }
        .dip-v3-col { width: 100%; }
        .dip-v3-col-header { display: flex; align-items: center; gap: 8px; margin-bottom: 14px; padding-bottom: 10px; border-bottom: 2px solid #f1f5f9; }
        .dip-v3-col-title { font-size: 1.1rem; font-weight: 900; color: #0f172a; display: flex; align-items: center; gap: 8px; }
        .dip-v3-col-title::before { content: ''; width: 4px; height: 16px; background: #3b82f6; border-radius: 2px; }
        .dip-v3-col-content { font-size: 0.95rem; color: #475569; line-height: 1.8; word-break: keep-all; text-align: justify; }

        /* Highlighting Tags — 텍스트 색상만 (배경/박스/테두리 일절 없음) */
        .dip-v3-hl-good  { color: #2563eb; font-weight: 800; }
        .dip-v3-hl-warn  { color: #dc2626; font-weight: 800; }
        .dip-v3-hl-info  { color: #0284c7; font-weight: 800; }
        .dip-v3-hl-range { color: #8b5cf6; font-weight: 800; }

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

    function _showOffline(el, retryFn, attempt = 1) {
        // [수정] 자동 재시도 카운트다운 + 즉시 재시도 버튼 포함
        const retryId = 'dip-retry-btn-' + Date.now();
        const countId = 'dip-countdown-' + Date.now();
        const maxAttempts = 5;
        const waitSecs = Math.min(30 + (attempt - 1) * 10, 60); // 30→40→50→60초

        el.innerHTML = `
            <div style="background:#fff8f8;border:1px solid #fee2e2;border-radius:20px;padding:32px 24px;text-align:center;font-family:inherit;">
                <div style="width:52px;height:52px;border-radius:50%;background:#fee2e2;display:flex;align-items:center;justify-content:center;margin:0 auto 16px;">
                    <span class="material-symbols-outlined" style="font-size:28px;color:#ef4444;">cloud_off</span>
                </div>
                <p style="font-size:1rem;font-weight:800;color:#dc2626;margin-bottom:6px;">AI 서버 기동 중...</p>
                <p style="font-size:0.8rem;color:#94a3b8;margin-bottom:20px;">
                    HuggingFace 서버가 절전 모드에서 깨어나는 중입니다.<br>
                    잠시 후 자동으로 다시 연결합니다.
                    ${attempt > 1 ? `<br><span style="color:#f59e0b;font-weight:700;">(${attempt}/${maxAttempts}번째 시도 중)</span>` : ''}
                </p>
                <div style="display:flex;align-items:center;justify-content:center;gap:12px;flex-wrap:wrap;">
                    <button id="${retryId}"
                        style="background:linear-gradient(135deg,#3b82f6,#2563eb);color:white;border:none;border-radius:12px;padding:10px 24px;font-size:0.85rem;font-weight:700;cursor:pointer;display:flex;align-items:center;gap:6px;"
                        onclick="this.disabled=true;this.textContent='연결 중...';">
                        <span class="material-symbols-outlined" style="font-size:16px;">refresh</span>
                        지금 재시도
                    </button>
                    <span style="font-size:0.8rem;color:#94a3b8;">
                        <span id="${countId}" style="font-weight:800;color:#3b82f6;">${waitSecs}</span>초 후 자동 재시도
                    </span>
                </div>
            </div>`;

        if (!retryFn) return; // 재시도 함수가 없으면 타이머 안 걸음

        // 카운트다운 타이머
        let remaining = waitSecs;
        const timer = setInterval(() => {
            remaining--;
            const countEl = document.getElementById(countId);
            if (countEl) countEl.textContent = remaining;
            if (remaining <= 0) {
                clearInterval(timer);
                if (el.isConnected) retryFn(attempt + 1);
            }
        }, 1000);

        // 즉시 재시도 버튼 이벤트
        const btn = document.getElementById(retryId);
        if (btn) {
            btn.addEventListener('click', () => {
                clearInterval(timer);
                if (el.isConnected) retryFn(attempt + 1);
            });
        }
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

        async render(containerId, filterKey, filterLabel, force = false, allDrawData = null) {
            const el = document.getElementById(containerId);
            if (!el) return;
            _lastContainerId = containerId; // ID 기억
            _injectStyles();
            _showLoading(el);

            try {
                // [방어적] AIProxy 로드 실패 시에도 대시보드 중단 방지
                const alive = window.AIProxy ? await window.AIProxy.checkHealth(false, true) : false;
                if (!alive) { _showOffline(el, (att) => this.render(containerId, filterKey, filterLabel, true, allDrawData), 1); return; }

                const data = await _getData(force);
                if (!data) { _showError(el, 'API 응답 없음'); return; }
                _updateHeader(data);

                const ra = (data && data.analysis && data.analysis.range_analysis) || {};
                let filterData = ra[filterKey] || {};

                // [개선] 끝수(digitX) 데이터 매핑 및 확률->범위 정규화
                if (filterKey.startsWith('digit') && data.analysis && data.analysis.tail_analysis) {
                    const dIdx = filterKey.replace('digit', '');
                    const raw = data.analysis.tail_analysis[dIdx] || data.analysis.tail_analysis[parseInt(dIdx)] || {};

                    // 확률(model_exp)을 UI 카드용 범위(model_expectations)로 변환
                    const normModelExp = {};
                    if (raw.model_exp) {
                        Object.entries(raw.model_exp).forEach(([m, prob]) => {
                            // 단순 확률을 0~1/2/3 범위로 매핑 (기존 추천 로직과 일치)
                            let min = 0, max = 2;
                            if (prob < 0.3) { min = 0; max = 1; }
                            else if (prob >= 1.2) { min = 1; max = 2; }
                            else if (prob >= 1.8) { min = 1; max = 3; }
                            normModelExp[m] = { min, max, reasoning: 'Deep Ensemble Probability' };
                        });
                    }
                    filterData = { ...raw, model_expectations: normModelExp, range: [0, 4] };
                }

                const modelExp = filterData.model_expectations || {};
                const strategy = (data && data.strategy) || {};
                const { cMin, cMax } = _ensembleRange(modelExp);

                // modelExp 비어있으면 캐시 무효화 후 1회 강제 재시도
                if (!Object.keys(modelExp).length) {
                    _memCache = null;
                    try { sessionStorage.removeItem(CACHE_KEY); } catch (e) { }
                    const fresh = await window.AIProxy.getDeepAnalysis();
                    if (fresh) {
                        _memCache = fresh;
                        try { sessionStorage.setItem(CACHE_KEY, JSON.stringify({ data: fresh, ts: Date.now() })); } catch (e) { }

                        let fd2 = (fresh.analysis?.range_analysis ? fresh.analysis.range_analysis[filterKey] : {}) || {};
                        if (filterKey.startsWith('digit') && fresh.analysis?.tail_analysis) {
                            const raw2 = fresh.analysis.tail_analysis[filterKey.replace('digit', '')] || {};
                            const mexp2 = {};
                            if (raw2.model_exp) {
                                Object.entries(raw2.model_exp).forEach(([m, p]) => {
                                    let mi = 0, ma = 2;
                                    if (p < 0.3) { mi = 0; ma = 1; }
                                    else if (p >= 1.2) { mi = 1; ma = 2; }
                                    mexp2[m] = { min: mi, max: ma };
                                });
                            }
                            fd2 = { ...raw2, model_expectations: mexp2 };
                        }

                        const me2 = fd2.model_expectations || {};
                        if (Object.keys(me2).length) {
                            const st2 = (fresh && fresh.strategy) || {};
                            const { cMin: c2, cMax: x2 } = _ensembleRange(me2);
                            el.style.minHeight = '';
                            el.innerHTML = _buildFilterHTML(filterKey, filterLabel, me2, st2, fd2.range);
                            _requestLLMAnalysis('dip-ai-llm-body', filterKey, filterLabel, me2, c2, x2, fresh.target_round, st2, fd2.range, allDrawData);
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
                _requestLLMAnalysis('dip-ai-llm-body', filterKey, filterLabel, modelExp, cMin, cMax, data.target_round, strategy, filterData.range, allDrawData);

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
                if (!alive) { _showOffline(el, (att) => this.renderGroup(containerId, groupType, true, payload), att); return; }

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
        },

        // ─────────────────────────────────────────────────────────────────────
        // renderFromDB: menu_analysis_history DB에서 메뉴별 분석을 가져와 렌더링
        //   containerId  : 대상 DOM ID
        //   menuType     : 'sum' | 'ac' | 'odd' | ... | 'regression' | 'custom_{uuid}'
        //   filterLabel  : 화면 표시용 한국어 라벨
        //   force        : true면 캐시 무시하고 재조회
        // ─────────────────────────────────────────────────────────────────────
        async renderFromDB(containerId, menuType, filterLabel, force = false) {
            const el = document.getElementById(containerId);
            if (!el) return;
            _lastContainerId = containerId;
            _injectStyles();
            _showLoading(el);

            try {
                // [방어적] AIProxy 로드 실패 시에도 대시보드 중단 방지
                const alive = window.AIProxy ? await window.AIProxy.checkHealth(false, true) : false;
                if (!alive) { _showOffline(el, (att) => this.renderFromDB(containerId, menuType, filterLabel, true), 1); return; }

                // 1단계: DB에서 메뉴별 분석 조회
                const dbRow = await window.AIProxy.getMenuAnalysis(menuType);

                if (dbRow && dbRow.model_expectations && Object.keys(dbRow.model_expectations).length > 0) {
                    // DB 데이터 정상 — 모델 카드 즉시 렌더
                    const modelExp = dbRow.model_expectations || {};
                    const ensRange = dbRow.ensemble_range || {};
                    const targetRound = dbRow.target_round;

                    // range 값 구성 (sum/tail_sum은 숫자 배열, 나머지는 "min~max" 문자열)
                    const isNumericFilter = ['sum', 'tail_sum'].includes(menuType);
                    const rangeForUI = isNumericFilter
                        ? [ensRange.min, ensRange.max]
                        : `${ensRange.min}~${ensRange.max}`;

                    // 기존 _buildFilterHTML / _ensembleRange 재활용
                    const { cMin, cMax } = _ensembleRange(modelExp);
                    const strategy = {};  // DB row엔 strategy 없으므로 빈값
                    el.style.minHeight = '';
                    el.innerHTML = _buildFilterHTML(menuType, filterLabel, modelExp, strategy, rangeForUI);

                    // 2단계: LLM 분석
                    if (dbRow.llm_analysis && (dbRow.llm_analysis.trend || dbRow.llm_analysis.pattern)) {
                        // DB에 LLM 분석이 이미 저장되어 있으면 즉시 표시
                        _injectLLMFromDB('dip-ai-llm-body', dbRow.llm_analysis, filterLabel, targetRound);
                    } else {
                        // DB에 없으면 LLM 서버에 요청 (기존 로직)
                        _requestLLMAnalysis('dip-ai-llm-body', menuType, filterLabel, modelExp, cMin, cMax, targetRound, strategy, rangeForUI);
                    }
                } else {
                    // DB에 데이터 없음 → 전체 딥러닝 분석 폴백
                    console.warn(`[DeepInsightPanel] DB에 ${menuType} 데이터 없음 — 전체 분석으로 폴백`);
                    await this.render(containerId, menuType, filterLabel, force);
                }

            } catch (e) {
                console.error('[DeepInsightPanel.renderFromDB]', e);
                _showError(el, e.message);
            }
        },

        refreshFromDB(containerId, menuType, filterLabel) {
            this.renderFromDB(containerId, menuType, filterLabel, true);
        }
    };

    // ─────────────────────────────────────────────────────────────────────────
    // LLM 분석 DB 결과 직접 주입 (llm_analysis가 이미 저장된 경우)
    // ─────────────────────────────────────────────────────────────────────────
    function _injectLLMFromDB(bodyId, llmData, filterLabel, targetRound) {
        const body = document.getElementById(bodyId);
        if (!body) return;

        const trend = llmData.trend || '';
        const pattern = llmData.pattern || '';
        const recommendation = llmData.recommendation || '';

        if (!trend && !pattern && !recommendation) return;

        const sectionHTML = (icon, title, color, content) => `
            <div style="margin-bottom:20px">
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
                    <span class="material-symbols-outlined" style="font-size:16px;color:${color}">${icon}</span>
                    <span style="font-size:13px;font-weight:700;color:#1e293b">${title}</span>
                </div>
                <div id="dip-v3-content-${title === '흐름 진단' ? 'flow' : title === '패턴 분석' ? 'pattern' : 'strategy'}"
                     style="font-size:13px;color:#475569;line-height:1.7;padding:12px 14px;background:#f8fafc;border-radius:8px;border-left:3px solid ${color}">
                    ${content.replace(/\n/g, '<br>')}
                </div>
            </div>`;

        body.innerHTML = `
            <div style="margin-top:4px">
                ${sectionHTML('trending_up', '흐름 진단', '#3b82f6', trend)}
                ${sectionHTML('grid_view', '패턴 분석', '#a855f7', pattern)}
                ${sectionHTML('auto_awesome', '필승 공략', '#22c55e', recommendation)}
                <div style="margin-top:12px;padding-top:10px;border-top:1px solid #e2e8f0;display:flex;align-items:center;gap:6px">
                    <span class="material-symbols-outlined" style="font-size:14px;color:#94a3b8">database</span>
                    <span style="font-size:11px;color:#94a3b8">${targetRound}회차 저장된 분석</span>
                </div>
            </div>`;
    }

    console.log('🧠 [DeepInsightPanel v2] 로드 완료');
})();
