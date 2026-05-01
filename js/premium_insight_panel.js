/**
 * Premium Insight Panel — 커스텀 분석과 동일한 "AI 프리미엄 전략 리포트" 디자인
 * 표준 피처(AC값/총합/끝수합/이월/미출/쌍수/삼각 등)용
 *
 * 사용:
 *   PremiumInsightPanel.render('dlInsightContainer', 'ac', 'AC값')
 *
 * 데이터 소스 우선순위:
 *   0) /api/v4/filters/0                 — V4 주간 파이프라인 (즉시 응답, P8 CI 포함)
 *   1) AIProxy.getMenuAnalysis(filterKey) — DB 저장분 (model_expectations, ensemble_range)
 *   2) AIProxy.getDeepAnalysis()         — 실시간 분석 (analysis.range_analysis[filterKey])
 */
(function () {
    'use strict';

    // 딥러닝 payload 세션 캐시 (탭 전환·재렌더 때 네트워크 재요청 방지)
    let _payloadCache = null;
    let _payloadInflight = null;
    const _CACHE_TTL = 10 * 60 * 1000; // 10분
    const _SS_KEY = 'pi_payload_cache_v3'; // [fix-68] fix-61 새 가중치 / fix-67 DEPRECATED 제외 강제 갱신
    // 페이지 로드 시 sessionStorage에서 즉시 복원 (네비게이션 간 캐시 유지)
    try {
        const raw = sessionStorage.getItem(_SS_KEY);
        if (raw) {
            const parsed = JSON.parse(raw);
            if (parsed && parsed.data && (Date.now() - parsed.ts) < _CACHE_TTL) _payloadCache = parsed;
        }
    } catch (_) {}

    function _payloadSync() {
        return (_payloadCache && (Date.now() - _payloadCache.ts) < _CACHE_TTL) ? _payloadCache.data : null;
    }

    // V4 필터 데이터 → payload 호환 형식 변환
    async function _getPayloadV4() {
        try {
            const baseUrl = (window.LANGCHAIN_CONFIG && window.LANGCHAIN_CONFIG.URL) || 'http://127.0.0.1:8000';
            const res = await fetch(`${baseUrl}/api/v4/filters/0`, { signal: AbortSignal.timeout(5000) });
            if (!res.ok) return null;
            const json = await res.json();
            if (!json.success || !json.filters) return null;
            // filters map → analysis.range_analysis 형식으로 변환
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

    async function _getPayload() {
        const cached = _payloadSync();
        if (cached) return cached;
        if (_payloadInflight) return _payloadInflight;
        _payloadInflight = (async () => {
            try {
                // 0. V4 주간 파이프라인 필터 데이터 우선 (즉시 응답)
                const v4Data = await _getPayloadV4();
                if (v4Data) {
                    console.log(`⚡ [PremiumInsightPanel] V4 필터 데이터 로드! (제${v4Data.target_round}회차)`);
                    _payloadCache = { data: v4Data, ts: Date.now() };
                    try { sessionStorage.setItem(_SS_KEY, JSON.stringify(_payloadCache)); } catch (_) {}
                    _payloadInflight = null;
                    return v4Data;
                }
                // 1. 실시간 v3 분석 폴백
                const deep = await window.AIProxy.getDeepAnalysis();
                const data = (deep && deep.data) ? deep.data : deep;

                // [수정] 데이터 유효성 검증 강화: 성공 응답이고 분석 데이터가 있을 때만 캐시
                if (data && data.success !== false && data.analysis) {
                    _payloadCache = { data, ts: Date.now() };
                    try { sessionStorage.setItem(_SS_KEY, JSON.stringify(_payloadCache)); } catch (_) {}
                    _payloadInflight = null;
                    return data;
                } else {
                    console.warn('[PremiumInsightPanel] Invalid payload received:', data);
                    _payloadInflight = null;
                    return data; // 에러 핸들링은 호출측(_resolvePayload)에서 처리
                }
            } catch (err) {
                console.error('[PremiumInsightPanel] Payload fetch error:', err);
                _payloadInflight = null;
                return null;
            }
        })();
        return _payloadInflight;
    }

    /**
     * 리졸버(resolver) 시스템
     * ─ 각 필터 키가 deep-analysis payload에서 어떻게 model_expectations를 꺼낼지 정의
     * ─ 특수 메뉴(끝자리 digit0~9, 기타 tail_analysis/position_analysis 등)가 추가될 때
     *   여기에 등록만 하면 자동으로 동일 디자인·로직으로 리포트됨
     *
     * 각 resolver: (payload, filterKey) => { modelExp, targetRound } | null
     */
    const _defaultResolver = (payload, filterKey) => {
        const ra = payload?.analysis?.range_analysis || {};
        const fd = ra[filterKey] || ra[`${filterKey}_value`] || ra[filterKey.replace('_value', '')] || {};
        // 빈 객체({})도 null로 처리하여 후속 폴백이 동작하게 함
        const me = fd.model_expectations;
        const modelExp = (me && typeof me === 'object' && Object.keys(me).length > 0) ? me : null;
        return { modelExp, targetRound: payload?.target_round || '' };
    };

    // mul7/mul8 resolver — range_analysis에서 직접 읽고, 없으면 구성 배수 통계로 합성
    const _mul7Resolver = (payload) => {
        const ra = payload?.analysis?.range_analysis || {};
        const fd = ra['mul7'];
        if (fd?.model_expectations && Object.keys(fd.model_expectations).length > 0) {
            return { modelExp: fd.model_expectations, targetRound: payload?.target_round || '' };
        }
        // 폴백: mul3/mul5 데이터에서 7배수 특성(저빈도) 합성
        const MODEL_KEYS = ['xgboost', 'catboost', 'tabnet', 'cnn', 'gnn', 'markov', 'autoencoder', 'tft', 'nbeats', 'mhn', 'bayesian_nn'];
        const mul3 = ra['mul3'], mul5 = ra['mul5'];
        const modelExp = {};
        MODEL_KEYS.forEach(m => {
            const r3 = mul3?.model_expectations?.[m];
            const r5 = mul5?.model_expectations?.[m];
            // 7배수는 1~2개가 일반적 (45개 중 6개, 확률 ~0.8개 기대)
            const base = r3 && r5 ? Math.round((r3.min + r5.min) / 4) : 0;
            modelExp[m] = { min: Math.max(0, base), max: Math.min(6, base + 2), reasoning: '7배수 합성(mul3/mul5 참조)' };
        });
        return { modelExp, targetRound: payload?.target_round || '' };
    };

    const _mul8Resolver = (payload) => {
        const ra = payload?.analysis?.range_analysis || {};
        const fd = ra['mul8'];
        if (fd?.model_expectations && Object.keys(fd.model_expectations).length > 0) {
            return { modelExp: fd.model_expectations, targetRound: payload?.target_round || '' };
        }
        // 폴백: mul4 데이터에서 8배수 특성 합성 (8배수 ⊂ 짝수, 45개 중 5개)
        const MODEL_KEYS = ['xgboost', 'catboost', 'tabnet', 'cnn', 'gnn', 'markov', 'autoencoder', 'tft', 'nbeats', 'mhn', 'bayesian_nn'];
        const mul4 = ra['mul4'];
        const modelExp = {};
        MODEL_KEYS.forEach(m => {
            const r4 = mul4?.model_expectations?.[m];
            // 8배수는 0~1개가 일반적
            const base = r4 ? Math.round(r4.min / 2) : 0;
            modelExp[m] = { min: Math.max(0, base), max: Math.min(5, base + 1), reasoning: '8배수 합성(mul4 참조)' };
        });
        return { modelExp, targetRound: payload?.target_round || '' };
    };

    // 교집합 배수(mul34/mul35/mul45) resolver
    // range_analysis에 직접 키가 없거나 model_expectations가 비었을 때
    // 구성 필터(mul3+mul4, mul3+mul5, mul4+mul5)의 범위 교집합으로 합성
    const _INTERSECTION_MAP = {
        'mul34': ['mul3', 'mul4'],
        'mul35': ['mul3', 'mul5'],
        'mul45': ['mul4', 'mul5'],
    };
    const _multipleIntersectionResolver = (payload, filterKey) => {
        const ra = payload?.analysis?.range_analysis || {};

        // (a) 직접 키가 있고 model_expectations가 유효하면 그대로 사용
        const direct = ra[filterKey];
        if (direct?.model_expectations && Object.keys(direct.model_expectations).length > 0) {
            return { modelExp: direct.model_expectations, targetRound: payload?.target_round || '' };
        }

        // (b) 구성 필터의 범위로 합성 — 교집합 배수이므로 각 구성 필터보다 좁은 범위
        const parts = _INTERSECTION_MAP[filterKey] || [];
        if (!parts.length) return null;

        // 7개 모델 × 구성 필터 범위를 교집합(min의 최솟값, max의 최솟값)으로 합성
        const MODEL_KEYS = ['xgboost', 'catboost', 'tabnet', 'cnn', 'gnn', 'markov', 'autoencoder', 'tft', 'nbeats', 'mhn', 'bayesian_nn'];
        const modelExp = {};
        MODEL_KEYS.forEach(m => {
            const ranges = parts.map(pk => {
                const fd = ra[pk];
                const me = fd?.model_expectations?.[m];
                return me && typeof me.min === 'number' ? me : null;
            }).filter(Boolean);

            if (!ranges.length) {
                // 구성 데이터 없으면 교집합 배수 특성상 0~1 기본값
                modelExp[m] = { min: 0, max: 1, reasoning: '교집합 배수 기본값' };
            } else {
                // 교집합: 각 구성 필터 최솟값들의 min, 최댓값들의 min (교집합이라 더 좁음)
                const lo = Math.min(...ranges.map(r => r.min));
                const hi = Math.min(...ranges.map(r => r.max));
                modelExp[m] = { min: lo, max: Math.max(lo, hi), reasoning: '교집합 합성' };
            }
        });

        // 최소 1개 이상 모델 데이터가 있으면 반환
        return Object.keys(modelExp).length > 0
            ? { modelExp, targetRound: payload?.target_round || '' }
            : null;
    };

    // 확률(기댓값) → min/max 범위 정규화 (끝자리·포지션 등 카운트형 메뉴)
    function _probToRange(prob) {
        if (prob < 0.3) return { min: 0, max: 1 };
        if (prob >= 1.8) return { min: 1, max: 3 };
        if (prob >= 1.2) return { min: 1, max: 2 };
        return { min: 0, max: 2 };
    }

    const _digitResolver = (payload, filterKey) => {
        const ta = payload?.analysis?.tail_analysis;
        if (!Array.isArray(ta)) return null;
        const idx = parseInt(String(filterKey).replace('digit', ''), 10);
        const raw = ta[idx];
        if (!raw || !raw.model_exp) return null;
        const modelExp = {};
        Object.entries(raw.model_exp).forEach(([m, p]) => { modelExp[m] = _probToRange(p); });
        return { modelExp, targetRound: payload?.target_round || '' };
    };

    // 비율형(홀짝/고저) 리졸버 — backend ratio_analysis 우선, 없으면 range_analysis로 합성
    const _ratioResolver = (payload, filterKey) => {
        const map = { 'odd': 'odd_even', 'high': 'high_low' };
        const metric = map[filterKey];
        if (!metric) return null;

        // (a) 백엔드가 ratio_analysis 제공하는 경우
        const ra = payload?.analysis?.ratio_analysis?.[metric];
        if (ra && ra.model_expectations) {
            const modelExp = {};
            Object.entries(ra.model_expectations).forEach(([k, v]) => {
                const tops = Array.isArray(v.top) ? v.top : [];
                const vals = tops.map(s => parseInt(String(s).split(':')[0], 10)).filter(n => !isNaN(n));
                if (vals.length) {
                    modelExp[k] = { min: Math.min(...vals), max: Math.max(...vals), reasoning: 'ratio top-K' };
                } else {
                    const entries = Object.entries(v.probs || {}).sort((a, b) => b[1] - a[1]);
                    if (entries[0]) {
                        const n = parseInt(String(entries[0][0]).split(':')[0], 10);
                        if (!isNaN(n)) modelExp[k] = { min: n, max: n, reasoning: 'ratio top-1' };
                    }
                }
            });
            return { modelExp, targetRound: payload?.target_round || '', ratioData: ra };
        }

        // (b) 폴백: range_analysis[key]의 {min,max}를 비율로 합성
        const rng = payload?.analysis?.range_analysis?.[filterKey];
        if (!rng || !rng.model_expectations) return null;
        const key = k => `${k}:${6 - k}`;
        const modelExp = rng.model_expectations;
        // 각 모델의 [min,max] 구간 내 카운트를 균등 분포로 보고 비율 분포 산출
        const modelRatioExp = {};
        Object.entries(modelExp).forEach(([m, r]) => {
            if (typeof r.min !== 'number') return;
            const probs = {}; for (let k = 0; k <= 6; k++) probs[key(k)] = 0;
            const span = Math.max(1, r.max - r.min + 1);
            for (let k = r.min; k <= r.max; k++) probs[key(k)] = 1 / span;
            const top = [];
            for (let k = r.min; k <= r.max; k++) top.push(key(k));
            modelRatioExp[m] = { probs, top };
        });
        // 앙상블: 모델별 분포 평균
        const ensembleProbs = {}; for (let k = 0; k <= 6; k++) ensembleProbs[key(k)] = 0;
        const mlist = Object.values(modelRatioExp);
        if (mlist.length) {
            mlist.forEach(v => Object.entries(v.probs).forEach(([kk, pp]) => { ensembleProbs[kk] += pp; }));
            Object.keys(ensembleProbs).forEach(kk => { ensembleProbs[kk] = +(ensembleProbs[kk] / mlist.length).toFixed(4); });
        }
        const recommended = [...new Set(Object.entries(ensembleProbs).sort((a, b) => b[1] - a[1]).filter(([, v]) => v > 0).slice(0, 3).map(([k]) => k))];
        // 합의도: min/max 스프레드로 근사
        const mins = Object.values(modelExp).map(r => r.min).filter(n => typeof n === 'number');
        const maxs = Object.values(modelExp).map(r => r.max).filter(n => typeof n === 'number');
        const spread = mins.length ? (Math.max(...maxs) - Math.min(...mins)) : 6;
        const agreement = Math.max(0, 1 - spread / 6);

        const synthRatio = {
            empirical_distribution: {},
            model_expectations: modelRatioExp,
            ensemble: { probs: ensembleProbs, recommended, agreement: +agreement.toFixed(2) }
        };
        return { modelExp, targetRound: payload?.target_round || '', ratioData: synthRatio };
    };

    const _arrayResolver = (payload, filterKey) => {
        const p = payload?.analysis;
        if (!p) return null;
        
        let target = null;
        if (p.lotto_paper_analysis) {
            target = [...(p.lotto_paper_analysis.rows || []), ...(p.lotto_paper_analysis.cols || [])].find(x => String(x.label).trim() === String(filterKey).trim());
        }
        if (!target && Array.isArray(p.magic_square_analysis)) {
            target = p.magic_square_analysis.find(x => String(x.label).trim() === String(filterKey).trim());
        }
        if (!target && Array.isArray(p.number_band_analysis)) {
            target = p.number_band_analysis.find(x => {
                const l = String(x.label).trim();
                const fk = String(filterKey).trim();
                return l === fk || l.includes(fk) || fk.includes(l);
            });
        }

        if (!target || !target.model_exp) return null;

        const modelExp = {};
        Object.entries(target.model_exp).forEach(([m, val]) => {
            modelExp[m] = { min: Math.floor(val), max: Math.ceil(val) };
        });

        const modelRatioExp = {};
        Object.entries(modelExp).forEach(([m, r]) => {
            if (typeof r.min !== 'number') return;
            const probs = {}; for (let k = 0; k <= 6; k++) probs[`${k}개`] = 0; // [수정] 레이블에 '개' 접미사 추가
            const span = Math.max(1, r.max - r.min + 1);
            for (let k = r.min; k <= r.max; k++) probs[`${k}개`] = 1 / span;
            const top = [];
            for (let k = r.min; k <= r.max; k++) top.push(`${k}개`);
            modelRatioExp[m] = { probs, top };
        });

        const ensembleProbs = {}; for (let k = 0; k <= 6; k++) ensembleProbs[`${k}개`] = 0;
        const mlist = Object.values(modelRatioExp);
        if (mlist.length) {
            mlist.forEach(v => Object.entries(v.probs).forEach(([kk, pp]) => { ensembleProbs[kk] += pp; }));
            Object.keys(ensembleProbs).forEach(kk => { ensembleProbs[kk] = +(ensembleProbs[kk] / mlist.length).toFixed(4); });
        }
        const recommended = [...new Set(Object.entries(ensembleProbs).sort((a, b) => b[1] - a[1]).filter(([, v]) => v > 0).slice(0, 3).map(([k]) => k))];
        const mins = Object.values(modelExp).map(r => r.min).filter(n => typeof n === 'number');
        const maxs = Object.values(modelExp).map(r => r.max).filter(n => typeof n === 'number');
        const spread = mins.length ? (Math.max(...maxs) - Math.min(...mins)) : 6;
        const agreement = Math.max(0, 1 - spread / 6);

        const synthRatio = {
            empirical_distribution: {},
            model_expectations: modelRatioExp,
            ensemble: { probs: ensembleProbs, recommended, agreement: +agreement.toFixed(2) }
        };

        return { modelExp, targetRound: payload?.target_round || '', ratioData: synthRatio };
    };

    // 번호대 resolver — number_band_analysis 배열에서 해당 번호대 항목 탐색
    // model_exp 값은 float 기댓값(0~6) → {min, max} 범위로 변환
    const _BAND_LABEL_MAP = {
        '단번대': '01~10',
        '10번대': '11~20',
        '20번대': '21~30',
        '30번대': '31~40',
        '40번대': '41~45',
    };
    // float 기댓값 → {min, max} 범위 (number_band model_exp 전용)
    function _bandExpToRange(val) {
        const f = parseFloat(val) || 0;
        const lo = Math.floor(f);
        const hi = Math.ceil(f);
        return { min: lo, max: Math.max(hi, lo) };
    }

    const _numberBandResolver = (payload, filterKey) => {
        const p = payload?.analysis;
        if (!p) return null;

        // number_band_analysis 배열에서 해당 레이블 탐색
        // 백엔드 레이블 형식: "01~10", "11~20", "21~30", "31~40", "41~45"
        if (Array.isArray(p.number_band_analysis)) {
            const targetLabel = _BAND_LABEL_MAP[filterKey];
            const target = p.number_band_analysis.find(x => {
                const l = String(x.label).trim();
                // 정확 매칭 우선, 그 다음 포함 관계 매칭
                return l === targetLabel ||
                       (targetLabel && l.includes(targetLabel)) ||
                       l === filterKey;
            });
            if (target && target.model_exp && Object.keys(target.model_exp).length > 0) {
                const modelExp = {};
                Object.entries(target.model_exp).forEach(([m, val]) => {
                    // val이 이미 {min,max}면 그대로, float이면 변환
                    if (typeof val === 'object' && val !== null && 'min' in val) {
                        modelExp[m] = val;
                    } else {
                        modelExp[m] = _bandExpToRange(val);
                    }
                });
                return { modelExp, targetRound: payload?.target_round || '' };
            }
        }

        // 폴백: range_analysis['number_band'] (전체 번호대 분석)
        const ra = p.range_analysis || {};
        const nb = ra['number_band'] || ra['numberband'];
        if (nb && nb.model_expectations) {
            return { modelExp: nb.model_expectations, targetRound: payload?.target_round || '' };
        }

        return null;
    };

    // 회귀 스텝별 resolver — regression_step_{N} 키에 대응
    // payload.analysis.regression_analysis 배열 + matrix_data 모델 스코어로 per-model 예측값 합성
    const _regressionStepResolver = (payload, filterKey) => {
        const step = parseInt(String(filterKey).replace('regression_step_', ''), 10);
        if (isNaN(step) || step < 2 || step > 200) return null;

        const ra = payload?.analysis?.regression_analysis;
        const matrix = payload?.analysis?.matrix_data;
        if (!Array.isArray(ra)) return null;

        const item = ra.find(r => r.id === step);
        if (!item) return null;

        const targetSet = new Set((item.targets || []).map(Number));
        const targetRound = payload?.target_round || '';
        const MODEL_KEYS = ['xgboost', 'catboost', 'tabnet', 'cnn', 'gnn', 'markov', 'autoencoder', 'tft', 'nbeats', 'mhn', 'bayesian_nn'];
        const modelExp = {};

        if (Array.isArray(matrix) && matrix.length > 0) {
            // 각 모델 top-6 예측 번호 vs 회귀 대상번호 교집합 → {min, max}
            MODEL_KEYS.forEach(m => {
                const sorted = [...matrix]
                    .filter(x => x.models?.[m]?.score != null)
                    .sort((a, b) => (b.models[m].score || 0) - (a.models[m].score || 0));
                const top6 = sorted.slice(0, 6).map(x => Number(x.num));
                const hit = top6.filter(n => targetSet.has(n)).length;
                const maxPossible = Math.min(targetSet.size, 6);
                modelExp[m] = {
                    min: Math.max(0, hit - 1),
                    max: Math.min(maxPossible, hit + 1),
                };
            });
        } else {
            // matrix 없으면 hit_dist 분위수로 합성 (모델별 소폭 변이)
            const dist = item.hit_dist || {};
            const total = Object.values(dist).reduce((a, b) => a + b, 0) || 1;
            let cumul = 0, p10 = 0, p90 = 3;
            for (let k = 0; k <= 6; k++) {
                const prev = cumul;
                cumul += (dist[k] || 0) / total;
                if (prev < 0.1 && cumul >= 0.1) p10 = k;
                if (prev < 0.9 && cumul >= 0.9) { p90 = k; break; }
            }
            MODEL_KEYS.forEach((m, i) => {
                const d = (i % 3) - 1; // -1, 0, 1 cycle
                modelExp[m] = {
                    min: Math.max(0, p10 + (i < 4 ? 0 : d)),
                    max: Math.min(6, p90 + d),
                };
            });
        }

        return { modelExp, targetRound };
    };

    const RESOLVERS = [
        { match: k => /^digit\d$/.test(k), resolve: _digitResolver },
        { match: k => k === 'odd' || k === 'high', resolve: _ratioResolver },
        { match: k => ['단번대','10번대','20번대','30번대','40번대'].includes(k), resolve: _numberBandResolver },
        { match: k => ['mul34','mul35','mul45'].includes(k), resolve: _multipleIntersectionResolver },
        { match: k => k === 'mul7', resolve: _mul7Resolver },
        { match: k => k === 'mul8', resolve: _mul8Resolver },
        { match: k => /가로\d|세로\d|\d+궁|번대/.test(k), resolve: _arrayResolver },
        { match: k => String(k).startsWith('regression_step_'), resolve: _regressionStepResolver },
        { match: () => true, resolve: _defaultResolver }
    ];

    function _resolvePayload(payload, filterKey) {
        if (!payload) {
            console.error('[PremiumInsightPanel] Payload is empty.');
            return null;
        }

        for (const r of RESOLVERS) {
            if (r.match(filterKey)) {
                const out = r.resolve(payload, filterKey);
                // modelExp가 없더라도 객체 자체는 반환하여 상위에서 처리 유도
                if (out) {
                    if (!out.modelExp || Object.keys(out.modelExp).length === 0) {
                        console.warn(`[PremiumInsightPanel] modelExp is empty for key: "${filterKey}"`, payload);
                    }
                    return out;
                }
            }
        }
        console.warn(`[PremiumInsightPanel] No resolver matched for key: "${filterKey}"`, payload);
        return null;
    }

    // 11 base 토폴로지 (사용자 결정 #24) — lstm/transformer 폐기, TFT 흡수
    // [Stage 1-4-D-2-fix-10] 메인 1~45 영역에서 N-BEATS 제외 (스칼라 분해 전용)
    const MODEL_ORDER = [
        { key: 'xgboost',     label: 'XGBOOST' },
        { key: 'catboost',    label: 'CATBOOST' },
        { key: 'tabnet',      label: 'TABNET' },
        { key: 'cnn',         label: 'CNN' },
        { key: 'gnn',         label: 'GNN' },
        { key: 'markov',      label: 'MARKOV' },
        { key: 'autoencoder', label: 'AE' },
        { key: 'tft',         label: 'TFT' },
        { key: 'mhn',         label: 'MHN' },
        { key: 'bayesian_nn', label: 'BAYESIAN' }
    ];

    // 백워드 호환: 폐기 모델 키 (API 응답에 와도 graceful skip)
    const DEPRECATED_MODEL_KEYS = new Set(['lstm', 'transformer']);
    // 메인 1~45 영역에서 제외할 모델 (스칼라 분해 전용 — 별도 영역에서만 노출)
    const MAIN_EXCLUDED_MODEL_KEYS = new Set(['nbeats']);

    // 탭 HTML (헤더 우측에 삽입) — sky-blue 언더바 활성 표시
    function _tabsHTML(tabs, containerId) {
        if (!tabs || !Array.isArray(tabs.items) || !tabs.items.length) return '';
        const activeKey = String(tabs.activeKey ?? tabs.items[0].key);
        const btns = tabs.items.map(it => {
            const k = String(it.key);
            const active = k === activeKey;
            const style = active
                ? 'color:#38bdf8; font-weight:900; border-bottom:3px solid #38bdf8;'
                : 'color:#94a3b8; font-weight:600; border-bottom:3px solid transparent;';
            return `<button type="button" data-pi-tab="${k}" style="background:transparent; padding:6px 10px; font-size:0.78rem; letter-spacing:-0.3px; cursor:pointer; transition:all 0.15s; ${style}">${it.label}</button>`;
        }).join('');
        return `<div data-pi-tabs="${containerId}" style="display:flex; gap:2px; flex-wrap:wrap; align-items:center;">${btns}</div>`;
    }

    function _wireTabs(containerId, tabs) {
        if (!tabs || typeof tabs.onSelect !== 'function') return;
        const root = document.getElementById(containerId);
        if (!root) return;
        const holder = root.querySelector(`[data-pi-tabs="${containerId}"]`);
        if (!holder) return;
        holder.querySelectorAll('[data-pi-tab]').forEach(btn => {
            btn.addEventListener('click', () => {
                const k = btn.getAttribute('data-pi-tab');
                try { tabs.onSelect(k); } catch (e) { console.error('[PremiumInsightPanel] onSelect error', e); }
            });
        });
    }

    function _skeleton(label, tabs, containerId) {
        const shimmer = `<span style="display:inline-block; background:linear-gradient(90deg,#e2e8f0 0%,#f1f5f9 50%,#e2e8f0 100%); background-size:200% 100%; animation:piShimmer 1.4s ease-in-out infinite; border-radius:6px; color:transparent;">····</span>`;
        const cards = MODEL_ORDER.map(m => `
            <div style="background:white; border:1px solid #e2e8f0; border-radius:12px; padding:14px 10px; text-align:center;">
                <div style="font-size:0.7rem; color:#64748b; font-weight:800; letter-spacing:0.5px; margin-bottom:6px;">${m.label}</div>
                <div style="font-size:1.1rem; color:#1e293b; font-weight:500; letter-spacing:-0.3px;">${shimmer}</div>
            </div>`).join('');

        return `
        <style>@keyframes piSpin{to{transform:rotate(360deg)}}@keyframes piShimmer{0%{background-position:200% 0}100%{background-position:-200% 0}}</style>
        <div style="background:white; border-radius:24px; border:1px solid #e2e8f0; overflow:hidden; box-shadow:0 4px 16px rgba(15,23,42,0.04);">
            <div style="background:#0f172a; padding:1.25rem 2rem; display:flex; align-items:center; gap:14px;">
                <div style="width:40px; height:40px; background:#1e293b; border-radius:12px; display:flex; align-items:center; justify-content:center;">
                    <span class="material-symbols-outlined" style="font-size:22px; color:#38bdf8;">insights</span>
                </div>
                <div style="flex:1;">
                    <div style="font-size:1.05rem; font-weight:900; color:white; letter-spacing:-0.3px;">AI 프리미엄 전략 리포트</div>
                    <div style="font-size:0.68rem; color:#94a3b8; font-weight:700; letter-spacing:2px; text-transform:uppercase; margin-top:2px;">INTELLIGENT ANALYSIS — ${label || ''}</div>
                </div>
                ${_tabsHTML(tabs, containerId)}
                <div style="display:inline-flex; align-items:center; gap:8px; color:#94a3b8; font-size:0.72rem; font-weight:700;">
                    <div style="width:14px; height:14px; border:2px solid #38bdf8; border-top-color:transparent; border-radius:50%; animation:piSpin 1s linear infinite;"></div>
                    <span>값 로딩 중</span>
                </div>
            </div>

            <div style="background:#f8fafc; border-bottom:1px solid #f1f5f9; padding:1.5rem 2rem;">
                <div style="display:flex; align-items:center; justify-content:space-between; gap:2rem; flex-wrap:wrap;">
                    <div>
                        <span style="font-size:0.7rem; color:#64748b; font-weight:800; letter-spacing:1px; text-transform:uppercase; margin-bottom:6px; display:block;">AI 종합 예측 범위</span>
                        <div style="display:flex; align-items:baseline; gap:12px;">
                            <span style="font-size:2.2rem; font-weight:900; color:#2563eb; letter-spacing:-1px;">${shimmer}</span>
                        </div>
                    </div>
                    <div style="width:240px; background:white; padding:12px; border-radius:16px; border:1px solid #e2e8f0;">
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                            <span style="font-size:0.68rem; color:#64748b; font-weight:800;">모델 합의도</span>
                            <span style="font-size:0.85rem; color:#1e293b; font-weight:900;">${shimmer}</span>
                        </div>
                        <div style="height:10px; background:#f1f5f9; border-radius:5px; overflow:hidden;"></div>
                        <div style="font-size:0.62rem; color:#94a3b8; font-weight:700; text-align:right; margin-top:6px;">10개 메인 딥러닝 모델 교차 검증</div>
                    </div>
                </div>
            </div>

            <div style="display:grid; grid-template-columns:repeat(5, 1fr); gap:10px; padding:1.25rem 2rem; background:#f8fafc;">
                ${cards}
            </div>

            <div style="padding:1.75rem 2rem;">
                <div style="margin-bottom:1.5rem;">
                    <div style="display:flex; align-items:center; gap:8px; margin-bottom:10px;">
                        <span style="width:4px; height:16px; background:#2563eb; border-radius:2px;"></span>
                        <span style="font-size:0.95rem; font-weight:900; color:#0f172a; letter-spacing:-0.3px;">흐름 진단</span>
                    </div>
                    <div style="font-size:0.92rem; line-height:1.8; color:#334155;">${shimmer} ${shimmer} ${shimmer}</div>
                </div>
                <div style="border-top:1px solid #f1f5f9; padding-top:1.5rem;">
                    <div style="display:flex; align-items:center; gap:8px; margin-bottom:10px;">
                        <span style="width:4px; height:16px; background:#8b5cf6; border-radius:2px;"></span>
                        <span style="font-size:0.95rem; font-weight:900; color:#0f172a; letter-spacing:-0.3px;">패턴 분석</span>
                    </div>
                    <div style="font-size:0.92rem; line-height:1.8; color:#334155;">${shimmer} ${shimmer} ${shimmer}</div>
                </div>
            </div>

            <div style="background:#0f172a; padding:1.75rem 2rem; color:white;">
                <div style="display:flex; align-items:center; gap:10px; margin-bottom:12px;">
                    <span class="material-symbols-outlined" style="font-size:20px; color:#38bdf8;">verified</span>
                    <span style="font-size:1rem; font-weight:900; color:#38bdf8; letter-spacing:-0.3px;">필승 공략</span>
                </div>
                <div style="font-size:0.93rem; line-height:1.85; color:rgba(255,255,255,0.6);">${shimmer} ${shimmer} ${shimmer}</div>
            </div>
        </div>`;
    }

    function _error(label, msg) {
        return `<div style="background:#fef2f2; border:1px solid #fecaca; border-radius:16px; padding:2rem; text-align:center; color:#991b1b; font-size:0.9rem; font-weight:700;">
            ${label} 데이터를 불러오지 못했습니다.
            ${msg ? `<div style="font-size:0.78rem; color:#7f1d1d; font-weight:500; margin-top:8px;">${msg}</div>` : ''}
        </div>`;
    }

    function _ensembleOf(modelExp) {
        const mins = [], maxs = [];
        Object.entries(modelExp || {}).forEach(([k, r]) => {
            if (k === '__ensemble__') return;  // 앙상블 자체는 평균 계산에서 제외
            // [Stage 1-4-D-2-fix-67] DEPRECATED(lstm/transformer) 제외 — 합집합/교집합/합의도 왜곡 방지
            if (DEPRECATED_MODEL_KEYS.has(k)) return;
            // weight 0 (해당 task 미사용) 모델 제외 — 합의도 왜곡 방지
            if (r && typeof r.weight === 'number' && r.weight === 0) return;
            if (r && typeof r.min === 'number' && typeof r.max === 'number') {
                mins.push(r.min); maxs.push(r.max);
            }
        });
        if (!mins.length) return { cMin: 0, cMax: 0, agreement: 0, unionMin: 0, unionMax: 0, interMin: 0, interMax: 0, ci: null };
        // P8: __ensemble__ 키가 있으면 백엔드 가중 앙상블 우선 사용
        const ensEntry = (modelExp || {})['__ensemble__'];
        const cMin = ensEntry?.min ?? Math.round(mins.reduce((a, b) => a + b, 0) / mins.length);
        const cMax = ensEntry?.max ?? Math.round(maxs.reduce((a, b) => a + b, 0) / maxs.length);
        const ci   = ensEntry?.ci ?? null;   // P8 Bootstrap CI
        const unionMin = Math.min(...mins);
        const unionMax = Math.max(...maxs);
        const interMin = Math.max(...mins);
        const interMax = Math.min(...maxs);
        const spread = unionMax - unionMin;
        const center = (cMin + cMax) / 2 || 1;
        const relSpread = spread / center;
        const agreement = Math.max(0, Math.min(100, Math.round(100 - relSpread * 120)));
        return { cMin, cMax, agreement, unionMin, unionMax, interMin, interMax, spread, ci };
    }

    // 최근 실제값 시계열 → 흐름·패턴 통계
    function _flowStats(values) {
        if (!Array.isArray(values) || values.length < 3) return null;
        const n = values.length;
        const mean = values.reduce((a, b) => a + b, 0) / n;
        const variance = values.reduce((a, b) => a + (b - mean) ** 2, 0) / n;
        const std = Math.sqrt(variance);
        const last = values[0];                       // 최신이 맨 앞이라고 가정
        const half = Math.floor(n / 2);
        const recent = values.slice(0, half);
        const older = values.slice(half);
        const recentAvg = recent.reduce((a, b) => a + b, 0) / recent.length;
        const olderAvg = older.reduce((a, b) => a + b, 0) / older.length;
        const trendDiff = recentAvg - olderAvg;
        const trendPct = (trendDiff / (olderAvg || 1)) * 100;
        let trend = '횡보';
        if (trendPct > 5) trend = '상승';
        else if (trendPct < -5) trend = '하락';
        const volatility = std / (mean || 1);
        return { mean, std, last, recentAvg, olderAvg, trend, trendPct, volatility, min: Math.min(...values), max: Math.max(...values) };
    }

    // 모델별 최근 적중률: 각 회차의 실제값이 해당 모델의 [min,max]에 들어갔는지 카운트
    function _modelHitRates(modelExp, recentValues) {
        if (!recentValues || !recentValues.length) return null;
        const rates = {};
        Object.entries(modelExp).forEach(([k, r]) => {
            // [Stage 1-4-D-2-fix-67] DEPRECATED + weight 0 제외 — 적중률 통계 왜곡 방지
            if (DEPRECATED_MODEL_KEYS.has(k)) return;
            if (k === '__ensemble__') return;
            if (r && typeof r.weight === 'number' && r.weight === 0) return;
            if (!r || typeof r.min !== 'number') return;
            const hits = recentValues.filter(v => v >= r.min && v <= r.max).length;
            rates[k] = { hits, total: recentValues.length, rate: hits / recentValues.length };
        });
        return rates;
    }

    function _buildHTML(filterLabel, targetRound, modelExp, ensemble, recentValues, tabs, containerId, ratioData, filterKey) {
        const ratioChips = (() => {
            if (!ratioData || !ratioData.ensemble) return '';
            const rec = ratioData.ensemble.recommended || [];
            const probs = ratioData.ensemble.probs || {};
            const agr = Math.round((ratioData.ensemble.agreement || 0) * 100);
            if (!rec.length) return '';
            const chips = rec.map((r, i) => {
                const p = probs[r] != null ? `${Math.round(probs[r] * 100)}%` : '';
                const bg = i === 0 ? '#2563eb' : i === 1 ? '#38bdf8' : '#64748b';
                return `<span style="display:inline-flex; align-items:center; gap:6px; background:${bg}; color:white; padding:6px 12px; border-radius:999px; font-size:0.85rem; font-weight:900; letter-spacing:-0.3px;">
                    <span>${r}</span>
                    ${p ? `<span style="font-size:0.7rem; opacity:0.85; font-weight:700;">${p}</span>` : ''}
                </span>`;
            }).join(' ');
            return `
            <div style="padding:1.25rem 2rem; background:#f0f9ff; border-top:1px solid #e0f2fe; border-bottom:1px solid #e0f2fe;">
                <div style="display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:12px;">
                    <div>
                        <span style="font-size:0.7rem; color:#0369a1; font-weight:800; letter-spacing:1px; text-transform:uppercase; display:block; margin-bottom:6px;">앙상블 권장 비율</span>
                        <div style="display:flex; gap:8px; flex-wrap:wrap;">${chips}</div>
                    </div>
                    <div style="font-size:0.72rem; color:#0369a1; font-weight:800;">합의도 ${agr}%</div>
                </div>
            </div>`;
        })();

        const flow = _flowStats(recentValues);
        const hitRates = _modelHitRates(modelExp, recentValues);

        // [Stage 1-4-D-2-fix-67] 카드 표시 — weight 0 / DEPRECATED 모델 제외
        const cards = MODEL_ORDER
            .filter(m => {
                const r = modelExp[m.key];
                if (!r) return false;
                if (DEPRECATED_MODEL_KEYS.has(m.key)) return false;
                // weight 0 → 해당 task에서 미사용 → 제외
                if (typeof r.weight === 'number' && r.weight === 0) return false;
                return true;
            })
            .map(m => {
                const r = modelExp[m.key];
                let val = r ? `${r.min}~${r.max}` : '-';
                if (ratioData && ratioData.model_expectations?.[m.key]) {
                    const rt = ratioData.model_expectations[m.key];
                    if (Array.isArray(rt.top) && rt.top[0] && String(rt.top[0]).includes(':')) val = rt.top[0];
                }
                return `
                <div style="background:white; border:1px solid #e2e8f0; border-radius:10px; padding:10px 4px; text-align:center; min-width:0;">
                    <div style="font-size:0.6rem; color:#64748b; font-weight:800; letter-spacing:0.3px; margin-bottom:4px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${m.label}</div>
                    <div style="font-size:0.95rem; color:#1e293b; font-weight:500; letter-spacing:-0.3px; white-space:nowrap;">${val}</div>
                </div>`;
            }).join('');

        // [Stage 1-4-D-2-fix-68] entries에서 DEPRECATED + weight 0 + __ensemble__ 제외
        // (lstm 0~0이 'tightest'로 선택되어 잘못된 텍스트 생성하던 문제)
        const entries = Object.entries(modelExp).filter(([k, r]) => {
            if (k === '__ensemble__') return false;
            if (DEPRECATED_MODEL_KEYS.has(k)) return false;
            if (r && typeof r.weight === 'number' && r.weight === 0) return false;
            if (!r || typeof r.min !== 'number' || typeof r.max !== 'number') return false;
            return true;
        });
        const labelOf = k => (MODEL_ORDER.find(m => m.key === k)?.label || k || '-');
        const maxModel = entries.slice().sort((a, b) => ((b[1]?.max || 0) - (a[1]?.max || 0)))[0];
        const minModel = entries.slice().sort((a, b) => ((a[1]?.min ?? 1e9) - (b[1]?.min ?? 1e9)))[0];
        // 가장 좁은 범위(고신뢰) 모델
        const tightest = entries.slice().sort((a, b) =>
            ((a[1]?.max - a[1]?.min) || 0) - ((b[1]?.max - b[1]?.min) || 0))[0];

        // --- 흐름 진단 ---
        let flowText;
        if (flow) {
            const trendColor = flow.trend === '상승' ? '#ea580c' : flow.trend === '하락' ? '#0284c7' : '#64748b';
            const volLabel = flow.volatility < 0.08 ? '낮음(안정)' : flow.volatility < 0.18 ? '보통' : '높음(불안정)';
            const lastPos = flow.last >= ensemble.cMin && flow.last <= ensemble.cMax ? '앙상블 범위 내부'
                : flow.last < ensemble.cMin ? `앙상블 하한 미만(${ensemble.cMin - flow.last} 격차)`
                : `앙상블 상한 초과(${flow.last - ensemble.cMax} 격차)`;
            flowText = `최근 ${recentValues.length}회차 평균 <strong>${flow.mean.toFixed(1)}</strong>, 표준편차 <strong>${flow.std.toFixed(1)}</strong>, 변동성 <strong>${volLabel}</strong>. 전반부 평균 ${flow.olderAvg.toFixed(1)} → 후반부 ${flow.recentAvg.toFixed(1)}로 <strong style="color:${trendColor}">${flow.trend}세(${flow.trendPct >= 0 ? '+' : ''}${flow.trendPct.toFixed(1)}%)</strong>. 직전 회차 값 <strong>${flow.last}</strong>는 ${lastPos}.`;
        } else {
            flowText = `최근 회차 실측 데이터가 부족해 모델 합의도 기반으로 진단합니다. 앙상블 범위 <strong>${ensemble.cMin}~${ensemble.cMax}</strong>, 합의도 <strong>${ensemble.agreement}%</strong>(${ensemble.agreement >= 70 ? '수렴' : '발산'}).`;
        }

        // --- 패턴 분석 ---
        let patternText;
        if (hitRates) {
            const ranked = Object.entries(hitRates).sort((a, b) => b[1].rate - a[1].rate);
            const best = ranked[0];
            const worst = ranked[ranked.length - 1];
            const top3 = ranked.slice(0, 3).map(([k, v]) => `${labelOf(k)} ${Math.round(v.rate * 100)}%`).join(', ');
            patternText = `최근 ${recentValues.length}회차 기준 모델별 적중률 상위: <strong>${top3}</strong>. 최고 <strong style="color:#16a34a">${labelOf(best[0])}(${best[1].hits}/${best[1].total})</strong>, 최저 <strong style="color:#ea580c">${labelOf(worst[0])}(${worst[1].hits}/${worst[1].total})</strong>. 가장 좁은 예측폭은 <strong>${labelOf(tightest?.[0])}</strong>(${tightest?.[1]?.min}~${tightest?.[1]?.max}).`;
        } else {
            patternText = `최고 낙관 <strong>${labelOf(maxModel?.[0])}</strong>(~${maxModel?.[1]?.max}), 최저 비관 <strong>${labelOf(minModel?.[0])}</strong>(~${minModel?.[1]?.min}), 최협소 예측폭 <strong>${labelOf(tightest?.[0])}</strong>(${tightest?.[1]?.min}~${tightest?.[1]?.max}).`;
        }

        // --- 필승 공략: 상황 분기 ---
        let stratMin = ensemble.cMin, stratMax = ensemble.cMax, stratReason = '앙상블 평균', stratTag = '앙상블';
        if (hitRates) {
            const ranked = Object.entries(hitRates).sort((a, b) => b[1].rate - a[1].rate);
            const top = ranked[0];
            // 최근 적중률 60% 이상이고 2위와 10%p 이상 격차 → 해당 모델 단독 채택
            if (top && top[1].rate >= 0.6 && (ranked[1] ? top[1].rate - ranked[1][1].rate >= 0.1 : true)) {
                const r = modelExp[top[0]];
                stratMin = r.min; stratMax = r.max;
                stratReason = `최근 ${top[1].total}회차 중 ${top[1].hits}회 적중한 <strong>${labelOf(top[0])}</strong> 모델 단독 채택 (적중률 ${Math.round(top[1].rate * 100)}%)`;
                stratTag = labelOf(top[0]);
            } else if (ensemble.agreement < 60 && flow && flow.volatility >= 0.18) {
                stratMin = ensemble.unionMin; stratMax = ensemble.unionMax;
                stratReason = `모델 합의도 낮음(${ensemble.agreement}%) + 최근 변동성 높음 → <strong>합집합 구간</strong>으로 안전망 확대`;
                stratTag = '합집합';
            } else if (ensemble.agreement < 60 && ensemble.interMin <= ensemble.interMax) {
                stratMin = ensemble.interMin; stratMax = ensemble.interMax;
                stratReason = `모델 간 견해 분산(${ensemble.agreement}%) → <strong>교집합 구간</strong>으로 공통 합의 구간만 채택`;
                stratTag = '교집합';
            } else if (flow && flow.trend === '상승') {
                const r = modelExp[maxModel[0]];
                stratMin = Math.round((ensemble.cMin + r.min) / 2); stratMax = r.max;
                stratReason = `최근 상승세(+${flow.trendPct.toFixed(1)}%) → 낙관 모델 <strong>${labelOf(maxModel[0])}</strong> 가중`;
                stratTag = `상승·${labelOf(maxModel[0])}`;
            } else if (flow && flow.trend === '하락') {
                const r = modelExp[minModel[0]];
                stratMin = r.min; stratMax = Math.round((ensemble.cMax + r.max) / 2);
                stratReason = `최근 하락세(${flow.trendPct.toFixed(1)}%) → 비관 모델 <strong>${labelOf(minModel[0])}</strong> 가중`;
                stratTag = `하락·${labelOf(minModel[0])}`;
            } else if (ensemble.agreement >= 75) {
                stratReason = `모델 합의도 높음(${ensemble.agreement}%) → <strong>앙상블 평균 범위</strong> 그대로 채택`;
                stratTag = '앙상블 수렴';
            }
        } else if (ensemble.agreement < 60 && ensemble.interMin <= ensemble.interMax) {
            stratMin = ensemble.interMin; stratMax = ensemble.interMax;
            stratReason = `모델 견해 분산(${ensemble.agreement}%) → 교집합 구간 채택`;
            stratTag = '교집합';
        }

        let strategyText = `<strong style="color:#38bdf8">[${stratTag}]</strong> ${stratReason}. <br>→ <strong style="color:#fff">${filterLabel}</strong> 조합 필터 <strong style="color:#38bdf8">Min=${stratMin}, Max=${stratMax}</strong> 적용 권장.`;

        // --- 비율형(홀짝/고저) 전용 문구 오버라이드 ---
        if (ratioData && ratioData.ensemble && String(ratioData.ensemble.recommended?.[0] || '').includes(':')) {
            const ratioKey = k => `${k}:${6 - k}`;
            const rec = ratioData.ensemble.recommended || [];
            const probs = ratioData.ensemble.probs || {};
            const agr = Math.round((ratioData.ensemble.agreement || 0) * 100);
            // 흐름: 최근 비율 분포
            if (Array.isArray(recentValues) && recentValues.length) {
                const bucket = {};
                for (let k = 0; k <= 6; k++) bucket[ratioKey(k)] = 0;
                recentValues.forEach(v => { const kk = ratioKey(v); if (bucket[kk] !== undefined) bucket[kk]++; });
                const entriesR = Object.entries(bucket).sort((a, b) => b[1] - a[1]).filter(([, c]) => c > 0).slice(0, 4);
                const distLine = entriesR.map(([k, c]) => `<strong>${k}</strong> ${c}회(${Math.round(c / recentValues.length * 100)}%)`).join(', ');
                flowText = `최근 ${recentValues.length}회차 <strong>${filterLabel}</strong> 분포: ${distLine}. 최빈 비율 <strong style="color:#2563eb">${entriesR[0][0]}</strong> 기준 흐름 형성.`;
            } else {
                flowText = `최근 실측 데이터 부족. 앙상블 권장 비율 <strong style="color:#2563eb">${rec[0] || '-'}</strong> 기반으로 진단.`;
            }
            // 패턴: 모델별 Top 비율 선호도
            const modelTops = Object.entries(ratioData.model_expectations || {})
                .map(([m, v]) => `${labelOf(m)}: ${(v.top || []).slice(0, 2).join('/') || '-'}`)
                .join(' · ');
            patternText = `7개 모델별 선호 비율 — ${modelTops}. 모델 합의도 <strong>${agr}%</strong> (${agr >= 70 ? '<strong style="color:#16a34a">수렴</strong>' : '<strong style="color:#ea580c">발산</strong>'}).`;
            // 공략: 앙상블 권장 비율 상위 3
            const topChips = rec.slice(0, 3).map(r => {
                const p = probs[r] != null ? `${Math.round(probs[r] * 100)}%` : '';
                return `<strong style="color:#38bdf8">${r}</strong>${p ? `(${p})` : ''}`;
            }).join(', ');
            let ratioTag = '앙상블 권장';
            if (agr >= 75) ratioTag = '합의 수렴';
            else if (agr < 50) ratioTag = '견해 분산';
            strategyText = `<strong style="color:#38bdf8">[${ratioTag}]</strong> 합의도 ${agr}% 하에서 AI 앙상블이 권장하는 비율은 ${topChips}.<br>→ <strong style="color:#fff">${filterLabel}</strong> 조합 필터에서 위 비율만 허용(나머지 제외)하는 전략 권장.`;
        }

        return `
        <div style="background:white; border-radius:24px; border:1px solid #e2e8f0; overflow:hidden; box-shadow:0 4px 16px rgba(15,23,42,0.04);">
            <div style="background:#0f172a; padding:1rem 1.5rem; display:flex; align-items:center; gap:12px; flex-wrap:wrap;">
                <div style="width:36px; height:36px; flex-shrink:0; background:#1e293b; border-radius:10px; display:flex; align-items:center; justify-content:center;">
                    <span class="material-symbols-outlined" style="font-size:20px; color:#38bdf8;">insights</span>
                </div>
                <div style="flex:1; min-width:0;">
                    <div style="font-size:0.95rem; font-weight:900; color:white; letter-spacing:-0.3px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">AI 프리미엄 전략 리포트</div>
                    <div style="font-size:0.62rem; color:#94a3b8; font-weight:700; letter-spacing:1.5px; text-transform:uppercase; margin-top:1px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">INTELLIGENT ANALYSIS — ${filterLabel}</div>
                </div>
                ${filterKey ? `
                <a href="ai_deep_learning.html?focus=${filterKey}#filter-card-${filterKey}"
                   style="display:inline-flex; align-items:center; gap:6px; padding:6px 12px; background:#1e293b; border:1px solid #334155; border-radius:8px; color:#38bdf8; font-size:0.72rem; font-weight:700; text-decoration:none; transition:all 0.15s; white-space:nowrap;"
                   onmouseover="this.style.background='#334155'; this.style.borderColor='#38bdf8';"
                   onmouseout="this.style.background='#1e293b'; this.style.borderColor='#334155';"
                   title="딥러닝 분석 페이지의 ${filterLabel} 섹션으로 이동">
                    <span class="material-symbols-outlined" style="font-size:14px;">network_intelligence</span>
                    딥러닝 상세
                    <span class="material-symbols-outlined" style="font-size:12px;">arrow_forward</span>
                </a>` : ''}
                ${_tabsHTML(tabs, containerId)}
            </div>

            <div style="background:#f8fafc; border-bottom:1px solid #f1f5f9; padding:1.25rem 1.5rem;">
                <div style="display:grid; grid-template-columns:1fr auto; gap:1rem; align-items:center;">
                    <div>
                        <span style="font-size:0.65rem; color:#64748b; font-weight:800; letter-spacing:1px; text-transform:uppercase; margin-bottom:4px; display:block;">AI 종합 예측 범위</span>
                        <div style="display:flex; align-items:baseline; gap:8px; flex-wrap:wrap;">
                            <span style="font-size:1.9rem; font-weight:900; color:#2563eb; letter-spacing:-1px;">
                                ${ratioData && ratioData.ensemble?.recommended && String(ratioData.ensemble.recommended[0]).includes(':') ? ratioData.ensemble.recommended.join(', ') : `${ensemble.cMin} ~ ${ensemble.cMax}`}
                            </span>
                            ${!(ratioData && ratioData.ensemble) ? `
                            <span style="font-size:0.8rem; color:#2563eb; font-weight:800; background:#dbeafe; padding:3px 8px; border-radius:8px; border:1px solid #bfdbfe;">평균 ${((ensemble.cMin + ensemble.cMax) / 2).toFixed(1)}</span>
                            ` : ''}
                        </div>
                        ${ensemble.ci ? `
                        <!-- P8: Bootstrap CI 밴드 -->
                        <div style="margin-top:8px; display:flex; align-items:center; gap:6px;">
                            <span style="font-size:0.62rem; color:#7c3aed; font-weight:800; background:#ede9fe; padding:2px 6px; border-radius:4px; border:1px solid #ddd6fe;">${ensemble.ci.level} CI</span>
                            <span style="font-size:0.75rem; color:#7c3aed; font-weight:700;">${ensemble.ci.band}</span>
                            <span style="font-size:0.6rem; color:#94a3b8;">부트스트랩 ${ensemble.ci.n_boot}회</span>
                        </div>
                        <div style="margin-top:4px; position:relative; height:6px; background:#e9d5ff; border-radius:3px; overflow:hidden; max-width:200px;">
                            ${(() => {
                                const lo = ensemble.ci.lo_p10, hi = ensemble.ci.hi_p90;
                                const span = hi - lo || 1;
                                const coreLo = Math.max(0, Math.round((ensemble.cMin - lo) / span * 100));
                                const coreW  = Math.min(100, Math.round((ensemble.cMax - ensemble.cMin) / span * 100));
                                return `<div style="position:absolute; left:${coreLo}%; width:${coreW}%; height:100%; background:linear-gradient(90deg,#7c3aed,#5b21b6); border-radius:3px;"></div>`;
                            })()}
                        </div>` : ''}
                    </div>
                    <div style="min-width:160px; max-width:220px; background:white; padding:10px 12px; border-radius:14px; border:1px solid #e2e8f0;">
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                            <span style="font-size:0.65rem; color:#64748b; font-weight:800;">모델 합의도</span>
                            <span style="font-size:0.82rem; color:#1e293b; font-weight:900;">
                                ${ratioData && ratioData.ensemble ? Math.round((ratioData.ensemble.agreement || 0) * 100) : ensemble.agreement}%
                            </span>
                        </div>
                        <div style="height:8px; background:#f1f5f9; border-radius:5px; overflow:hidden;">
                            <div style="width:${ratioData && ratioData.ensemble ? Math.round((ratioData.ensemble.agreement || 0) * 100) : ensemble.agreement}%; height:100%; background:linear-gradient(90deg,#38bdf8,#2563eb);"></div>
                        </div>
                        <div style="font-size:0.6rem; color:#94a3b8; font-weight:700; text-align:right; margin-top:4px;">10개 메인 딥러닝 모델</div>
                    </div>
                </div>
            </div>


            <div style="display:grid; grid-template-columns:repeat(5, minmax(0,1fr)); gap:6px; padding:1rem 1.5rem; background:#f8fafc;">
                ${cards}
            </div>

            <div style="padding:1.25rem 1.5rem;">
                <div style="margin-bottom:1.25rem;">
                    <div style="display:flex; align-items:center; gap:8px; margin-bottom:8px;">
                        <span style="width:4px; height:15px; flex-shrink:0; background:#2563eb; border-radius:2px;"></span>
                        <span style="font-size:0.9rem; font-weight:900; color:#0f172a; letter-spacing:-0.3px;">흐름 진단</span>
                    </div>
                    <div style="font-size:0.87rem; line-height:1.8; color:#334155; word-break:keep-all;">${flowText}</div>
                </div>
                <div style="border-top:1px solid #f1f5f9; padding-top:1.25rem;">
                    <div style="display:flex; align-items:center; gap:8px; margin-bottom:8px;">
                        <span style="width:4px; height:15px; flex-shrink:0; background:#8b5cf6; border-radius:2px;"></span>
                        <span style="font-size:0.9rem; font-weight:900; color:#0f172a; letter-spacing:-0.3px;">패턴 분석</span>
                    </div>
                    <div style="font-size:0.87rem; line-height:1.8; color:#334155; word-break:keep-all;">${patternText}</div>
                </div>
            </div>

            <div style="background:#0f172a; padding:1.25rem 1.5rem; color:white;">
                <div style="display:flex; align-items:center; gap:8px; margin-bottom:10px;">
                    <span class="material-symbols-outlined" style="font-size:18px; color:#38bdf8; flex-shrink:0;">verified</span>
                    <span style="font-size:0.9rem; font-weight:900; color:#38bdf8; letter-spacing:-0.3px;">${targetRound || ''}회차 필승 공략</span>
                </div>
                <div style="font-size:0.87rem; line-height:1.85; color:rgba(255,255,255,0.9); font-weight:400; word-break:keep-all;">${strategyText}</div>
            </div>
        </div>`;
    }

    async function render(containerId, filterKey, filterLabel, opts) {
        const recentValues = (opts && Array.isArray(opts.recentValues)) ? opts.recentValues : null;
        const skipMenuFetch = !!(opts && opts.skipMenuFetch);
        const tabs = (opts && opts.tabs) ? opts.tabs : null;
        const el = document.getElementById(containerId);
        if (!el) return;
        // 캐시가 있으면 스켈레톤 건너뛰고 즉시 렌더 (탭 전환 체감속도 개선)
        const warmPayload = _payloadSync();
        if (warmPayload && skipMenuFetch) {
            const resolved = _resolvePayload(warmPayload, filterKey);
            if (resolved && resolved.modelExp && Object.keys(resolved.modelExp).length > 0) {
                const ensemble = _ensembleOf(resolved.modelExp);
                el.innerHTML = _buildHTML(filterLabel, resolved.targetRound || '', resolved.modelExp, ensemble, recentValues, tabs, containerId, resolved.ratioData || null, filterKey);
                _wireTabs(containerId, tabs);
                return;
            }
        }
        el.innerHTML = _skeleton(filterLabel, tabs, containerId);
        _wireTabs(containerId, tabs);

        if (!window.AIProxy) {
            el.innerHTML = _error(filterLabel, 'AIProxy 모듈을 찾을 수 없습니다.');
            return;
        }

        try {
            let modelExp = null, targetRound = '', ratioData = null;

            // 1) 메뉴 DB 저장분 우선 (skipMenuFetch 시 건너뜀)
            try {
                const row = skipMenuFetch ? null : await window.AIProxy.getMenuAnalysis(filterKey);
                if (row && row.model_expectations && Object.keys(row.model_expectations).length > 0) {
                    modelExp = row.model_expectations;
                    targetRound = row.target_round || '';
                }
            } catch (_) { /* noop */ }

            // 2) 실시간 딥러닝 분석 폴백 (리졸버 시스템 + 세션 캐시)
            if (!modelExp) {
                const payload = await _getPayload();
                const resolved = _resolvePayload(payload, filterKey);
                if (resolved) {
                    modelExp = resolved.modelExp;
                    targetRound = resolved.targetRound || targetRound;
                    if (resolved.ratioData) ratioData = resolved.ratioData;
                }
            }

            if (!modelExp || Object.keys(modelExp).length === 0) {
                el.innerHTML = _error(filterLabel, '잠시 후 다시 시도해주세요.');
                return;
            }

            const ensemble = _ensembleOf(modelExp);
            el.innerHTML = _buildHTML(filterLabel, targetRound, modelExp, ensemble, recentValues, tabs, containerId, ratioData, filterKey);
            _wireTabs(containerId, tabs);
        } catch (e) {
            console.error('[PremiumInsightPanel]', e);
            el.innerHTML = _error(filterLabel, e.message);
        }
    }

    window.PremiumInsightPanel = {
        render,
        refresh: render
    };

    console.log('🌟 [PremiumInsightPanel] 로드 완료');
})();
