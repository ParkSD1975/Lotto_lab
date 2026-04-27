let currentAnalysis = null;
let allDrawData = [];
let referenceRound = 0; // 기준 회차 (0=최신)
let historyViewLimit = 200; // [수정] 딥러닝 백필 데이터(1211회~) 노출을 위해 기본 범위를 200회로 확대

const aiCache = new Map(); // [New] AI 예측 데이터 캐시

// [성능] sessionStorage에서 aiCache 복원 (페이지 재방문 시 재요청 방지)
(function _restoreAiCache() {
    try {
        const raw = sessionStorage.getItem('_aiCacheV1');
        if (raw) {
            const obj = JSON.parse(raw);
            Object.entries(obj).forEach(([k, v]) => aiCache.set(parseInt(k), v));
            console.log(`♻️ [aiCache] sessionStorage에서 ${aiCache.size}개 회차 복원`);
        }
    } catch (_) {}
})();

// [성능] aiCache → sessionStorage 저장 헬퍼
function _persistAiCache() {
    try {
        const obj = {};
        aiCache.forEach((v, k) => { obj[k] = v; });
        sessionStorage.setItem('_aiCacheV1', JSON.stringify(obj));
    } catch (_) {}
}

// [표준] 로또 번호대별 공 색상 — lotto_ball_colors.md 스펙 (그라데이션)
//   1-10: yellow / 11-20: blue / 21-30: red / 31-40: gray / 41-45: green
function getStandardBallGradient(num) {
    const n = parseInt(num);
    if (n <= 10) return 'linear-gradient(135deg,#f59e0b,#d97706)';
    if (n <= 20) return 'linear-gradient(135deg,#3b82f6,#2563eb)';
    if (n <= 30) return 'linear-gradient(135deg,#ef4444,#dc2626)';
    if (n <= 40) return 'linear-gradient(135deg,#6b7280,#4b5563)';
    return 'linear-gradient(135deg,#10b981,#059669)';
}
window.getStandardBallGradient = getStandardBallGradient;

// [성능] calculateStats 결과 캐시 → refreshAIAnalysis에서 중복 연산 방지
let _lastStats = null;
let _lastStatsId = null;

// [성능] AI 리포트 localStorage 캐시 헬퍼 (TTL: 72시간, 회차 변경 시 자동 무효화)
const AI_CACHE_TTL = 72 * 60 * 60 * 1000; // 72시간
function _getAICache(key) {
    try {
        const raw = localStorage.getItem('ai_rpt_' + key);
        if (!raw) return null;
        const { ts, html } = JSON.parse(raw);
        if (Date.now() - ts > AI_CACHE_TTL) { localStorage.removeItem('ai_rpt_' + key); return null; }
        return html;
    } catch (e) { return null; }
}
function _setAICache(key, html) {
    try { localStorage.setItem('ai_rpt_' + key, JSON.stringify({ ts: Date.now(), html })); } catch (e) { }
}

// [성능] lotto_draws sessionStorage 캐시 (동일 탭 내 분석 전환 시 재사용)
const DRAWS_SS_KEY = 'lotto_draws_ss_cache';
async function loadLottoDrawsCached() {
    try {
        const raw = sessionStorage.getItem(DRAWS_SS_KEY);
        if (raw) {
            const { ts, data } = JSON.parse(raw);
            if (Date.now() - ts < 5 * 60 * 1000) return data; // 5분 유효
        }
    } catch (e) { }
    const { data } = await window.supabaseClient.from('lotto_draws')
        .select('*').order('round', { ascending: false }).range(0, 5000);
    const result = data || [];
    try { sessionStorage.setItem(DRAWS_SS_KEY, JSON.stringify({ ts: Date.now(), data: result })); } catch (e) { }
    return result;
}

// Highlighting State
let highlightState = { col: null, val: null };
let rangeHighlightIndex = -1; // [New] 10회차 구간 하이라이트 시작 인덱스
let editingRound = null; // [New] 현재 편집 중인 회차

function toggleHighlight(col, val) {
    if (highlightState.col === col && highlightState.val === val) {
        highlightState = { col: null, val: null };
    } else {
        highlightState = { col, val };
    }
    updateAnalysisDisplay(true);
}

function toggleRangeHighlight(index) {
    // 이미 같은 인덱스면 해제, 아니면 설정
    rangeHighlightIndex = (rangeHighlightIndex === index) ? -1 : index;
    updateAnalysisDisplay(true); // [Mod] 하이라이트 토글 시 AI 재분석 방지
}

// [New] 히스토리 범위 변경 핸들러
window.onHistoryLimitChange = function (val) {
    historyViewLimit = parseInt(val);
    const label = document.getElementById('historyRangeVal');
    if (label) {
        label.textContent = (historyViewLimit >= 2000) ? '전체' : historyViewLimit;
    }
    updateAnalysisDisplay(true); // AI 분석 갱신 없이 UI만 리렌더링
};

// [SPA Navigation Support] global exposure
window.initAnalysis = initAnalysis;

/**
 * [New] 분석 항목의 성격(AI 여부, 제외수 여부 등)을 판단하는 통합 헬퍼
 */
function getAnalysisContext(analysis) {
    if (!analysis) return { type: 'static', isAiType: false, isExclusion: false };
    const type = analysis.type || 'static';
    const title = (analysis.title || '').toUpperCase();
    // [수정] "앙상블", "추천조합", "XGB" 등 누락된 키워드 추가
    const isAiModelTitle = !!title.match(/(LSTM|GNN|CNN|TRANSFORMER|MARKOV|AUTOENCODER|XGBOOST|XGB|ENSEMBLE|앙상블|추천조합|TF|ATC|AI|딥러닝|추천|제외)/i);
    const isExclusion = title.includes('제외') || title.includes('EXCLUDE') || type.includes('excluded');
    const aiSource = analysis.config?.aiSource;
    const isAiType = type.startsWith('ai_') || !!aiSource || isAiModelTitle;
    return { type, title, isAiModelTitle, isExclusion, isAiType, aiSource };
}

/**
 * [New] AI 캐시 데이터에서 분석 설정에 맞는 타겟 번호를 추출하는 통합 헬퍼
 * 이력 데이터 매핑과 차기 회차(Upcoming) 매핑 로직을 하나로 합쳐 코드 중복을 제거하고 정합성을 유지함.
 */
function extractTargetsFromAIData(aiData, context, analysis) {
    if (!aiData) return [];
    const { type, aiSource, isAiModelTitle, title } = context;
    const isTarget20 = title.includes('20');
    // [추가] 제목에서 숫자 추출 (예: 추천조합 10 -> count=10)
    const titleMatch = title.match(/(\d+)/);
    const titleCount = titleMatch ? parseInt(titleMatch[0]) : null;

    let targets = [];

    // [New] 추천조합N: combinations(AI 추천 10게임)에서 조합 범위별 번호 추출 (중복 제거)
    // 추천조합5 = 1~5번 조합, 추천조합10 = 6~10번 조합, 추천조합1-10 = 1~10번 조합
    if (title.includes('추천조합') && aiData.combinations?.length > 0) {
        const combos = aiData.combinations;
        let startRank, endRank;

        // 제목에서 범위 파싱: "1-10", "5", "10" 등
        const rangeMatch = title.match(/추천조합\s*(\d+)\s*[-~]\s*(\d+)/);
        const singleMatch = title.match(/추천조합\s*(\d+)/);

        if (rangeMatch) {
            // "추천조합1-10" → 1번~10번
            startRank = parseInt(rangeMatch[1]);
            endRank = parseInt(rangeMatch[2]);
        } else if (singleMatch) {
            const num = parseInt(singleMatch[1]);
            if (num <= 5) {
                // "추천조합5" → 1번~5번
                startRank = 1;
                endRank = num;
            } else {
                // "추천조합10" → 6번~10번
                startRank = 6;
                endRank = num;
            }
        } else {
            startRank = 1;
            endRank = combos.length;
        }

        const selected = combos.filter(c => c.rank >= startRank && c.rank <= endRank);
        const allNums = selected.flatMap(c => c.numbers || []);
        targets = [...new Set(allNums)].sort((a, b) => a - b);
        return targets.map(Number);
    }

    // [수정] 추천조합 등 개수가 명시된 항목은 matrix_data 기반 추출을 우선하거나 fixed 목록을 슬라이싱함
    if (aiSource === 'dl_recommended') {
        targets = (aiData.recommended_numbers?.length > 0 ? aiData.recommended_numbers :
            (aiData.recommended?.length > 0 ? aiData.recommended : (aiData.top_5 || [])));

        // 만약 가져온 갯수가 요청된 개수보다 적고 matrix_data가 있다면 폴백
        const count = parseInt(analysis.rules?.count || titleCount || targets.length);
        if (targets.length < count && aiData.matrix_data?.length > 0) {
            const sorted = [...aiData.matrix_data].sort((a, b) => (b.total || 0) - (a.total || 0));
            targets = sorted.slice(0, count).map(item => Number(item.num));
        } else if (targets.length > count) {
            targets = targets.slice(0, count);
        }
    } else if (aiSource === 'dl_excluded') {
        targets = (aiData.excluded_numbers?.length > 0 ? aiData.excluded_numbers :
            (aiData.excluded?.length > 0 ? aiData.excluded : (aiData.exclude_10 || [])));
    } else if (type === 'ai_ensemble_fixed') {
        targets = (aiData.top_5?.length > 0 ? aiData.top_5 : aiData.recommended || []).slice(0, 6);
    } else if (type === 'ai_ensemble_excluded') {
        targets = aiData.exclude_10 || aiData.excluded || [];
    } else if (type === 'ai_model_top' || type === 'ai_model_bottom' || isAiModelTitle) {
        let model = (analysis.rules?.model || 'ensemble').toLowerCase();
        if (isAiModelTitle && (!analysis.rules?.model || model === 'ensemble')) {
            const matched = title.match(/(LSTM|GNN|CNN|TRANSFORMER|MARKOV|AUTOENCODER|XGBOOST|XGB|TF|ATC|앙상블)/i);
            if (matched) {
                model = matched[0].toLowerCase();
                if (model === 'tf') model = 'transformer';
                if (model === 'atc') model = 'autoencoder';
                if (model === 'xgb') model = 'xgboost';
                if (model === '앙상블') model = 'ensemble';
            }
        }
        let count = parseInt(analysis.rules?.count || titleCount || (isTarget20 ? 20 : 10));
        const isTop = (type !== 'ai_model_bottom');
        const matrixData = aiData.matrix_data || [];
        if (matrixData.length > 0) {
            const sorted = [...matrixData].sort((a, b) => {
                let scoreA, scoreB;
                if (model === 'ensemble' || model === 'total' || model === '앙상블') {
                    scoreA = a.total || 0;
                    scoreB = b.total || 0;
                } else {
                    scoreA = (a.models && a.models[model]) ? (a.models[model].score || 0) : 0;
                    scoreB = (b.models && b.models[model]) ? (b.models[model].score || 0) : 0;
                }
                return isTop ? (scoreB - scoreA) : (scoreA - scoreB);
            });
            targets = sorted.slice(0, count).map(item => Number(item.num));
        }
    }
    return (targets || []).map(Number);
}

document.addEventListener('DOMContentLoaded', async () => {
    const params = new URLSearchParams(window.location.search);
    let analysisId = params.get('id');

    if (!analysisId) {
        // [수정] LNB 메뉴와 동일한 정렬: created_at ASC + 사용자 드래그 순서 우선 → 맨 위(피보나치수열 등) 항목으로 랜딩
        try {
            const userId = window.filterService?.userId
                || (await window.supabaseClient.auth.getUser()).data?.user?.id
                || localStorage.getItem('_lastLoginUserId')
                || null;

            let q = window.supabaseClient
                .from('ai_custom_analyses')
                .select('id')
                .is('target_round', null)
                .order('created_at', { ascending: true });
            if (userId) q = q.or(`user_id.eq.${userId},user_id.is.null`);
            else q = q.is('user_id', null);

            const { data: list } = await q;
            if (!list || list.length === 0) return;

            // LNB 드래그 순서 반영
            const storageKey = userId ? `lnbOrder_custom_${userId}` : 'lnbOrder_custom_guest';
            let ordered = list;
            try {
                const saved = JSON.parse(localStorage.getItem(storageKey) || 'null');
                if (saved && saved.length > 0) {
                    ordered = [...list].sort((a, b) => {
                        const ia = saved.indexOf(`custom_analysis.html?id=${a.id}`);
                        const ib = saved.indexOf(`custom_analysis.html?id=${b.id}`);
                        if (ia !== -1 && ib !== -1) return ia - ib;
                        if (ia !== -1) return -1;
                        if (ib !== -1) return 1;
                        return 0;
                    });
                }
            } catch (e) { /* noop */ }

            const firstId = ordered[0]?.id;
            if (firstId) return window.location.replace(`custom_analysis.html?id=${firstId}`);
        } catch (e) {
            console.warn('[Custom Landing] 맨 위 분석 조회 실패:', e);
        }
        return;
    }

    await initAnalysis(analysisId);
});

// Handle Browser Back/Forward buttons
window.addEventListener('popstate', (event) => {
    const params = new URLSearchParams(window.location.search);
    const id = params.get('id');
    if (id) window.initAnalysis(id);
});

async function initAnalysis(analysisId) {
    try {
        // [New] 분석 이동 시 하이라이트 상태 리셋
        highlightState = { col: null, val: null };
        rangeHighlightIndex = -1;
        editingRound = null;

        // 1. 데이터 로드 (분석 설정 + 전체 회차) - lotto_draws는 SS캐시 우선
        const [analysisRes, cachedDraws] = await Promise.all([
            window.supabaseClient.from('ai_custom_analyses').select('*').eq('id', analysisId).single(),
            loadLottoDrawsCached() // [성능] sessionStorage 캐시 적용 (5분 유효)
        ]);

        if (analysisRes.error || !analysisRes.data) throw new Error("분석 로드 실패");
        currentAnalysis = analysisRes.data;
        allDrawData = cachedDraws;

        // [자동보정] 회차 업데이트 후 첫 방문 시 전체 필터 일괄 재설정 (1회만 실행)
        // [핵심] await로 동기 실행 → 초기 렌더 전에 현재 분석의 min/max가 최근 10회차 값으로 반영되도록 보장
        if (!_hasRunAutoCalibrate) {
            _hasRunAutoCalibrate = true;
            try { await batchCalibrateAllFilters(); }
            catch (e) { console.warn('[AutoCalibrate] 실패:', e); }
            // 보정 후 최신 filter_config 재조회 (다른 탭/서비스 변경분 반영)
            try {
                const { data: refreshed } = await window.supabaseClient
                    .from('ai_custom_analyses')
                    .select('filter_config')
                    .eq('id', analysisId).single();
                if (refreshed?.filter_config) currentAnalysis.filter_config = refreshed.filter_config;
            } catch (e) { /* noop */ }
        }

        // 데이터 보정 (안전 장치)
        if (!currentAnalysis.target_numbers) currentAnalysis.target_numbers = [];
        if (!currentAnalysis.filter_config) currentAnalysis.filter_config = { min: 1, max: 3, enabled: false };

        // [New] Dynamic Hydration: config 컬럼이 없을 경우 rules.config에서 복구
        if (!currentAnalysis.config && currentAnalysis.rules?.config) {
            currentAnalysis.config = currentAnalysis.rules.config;
            console.log('[initAnalysis] Hydrated config from rules.config');
        }

        // [New] Group Number Fallback: 그룹 분석인데 번호가 비어있는 경우 자동 복구
        if (currentAnalysis.type === 'group' && currentAnalysis.config?.groups) {
            currentAnalysis.config.groups.forEach(group => {
                if (!group.numbers || group.numbers.length === 0) {
                    const standardKey = Object.keys(window.LOTTO_CONSTANTS?.GROUPS || {}).find(k => group.name.includes(k));
                    if (standardKey) {
                        group.numbers = window.LOTTO_CONSTANTS.GROUPS[standardKey];
                        console.log(`[initAnalysis] Restored missing numbers for group: ${group.name}`);
                    }
                }
            });
        }

        // 2. 히스토리 로드 (분석별 상세 회차 데이터)
        const historyRes = await window.supabaseClient.from('analysis_history').select('*').eq('analysis_id', analysisId);
        currentAnalysis.history_data = historyRes.data || [];

        // [수정] 수동(직접입력)의 경우 다음 회차 이력이 존재하면 UI의 target_numbers에 즉시 연동 (상단볼/대시보드/그리드 노출)
        if (currentAnalysis.type === 'manual' || currentAnalysis.type === 'direct') {
            const nextRound = (allDrawData[0]?.round || 0) + 1;
            const hist = currentAnalysis.history_data.find(h => h.target_round === nextRound);
            if (hist && hist.target_numbers && hist.target_numbers.length > 0) {
                // [수정] 정렬(sort) 제거하여 모델별 중요도 순서 유지
                currentAnalysis.target_numbers = [...hist.target_numbers];
                if (!currentAnalysis.filter_config) currentAnalysis.filter_config = {};
                currentAnalysis.filter_config.target_round = nextRound;
                console.log(`[DL Sync] ${nextRound}회차 데이터 UI 연동 완료`);
            }
        }

        // 3. 초기 렌더링 (로드 시에는 AI 자동 분석 방지)
        renderBaseInfo();
        await updateAnalysisDisplay();

        // 4. 유형별 전용 컨트롤 로드
        renderTypeSpecificControls();

        // 5. [New] AI 프리미엄 전략 리포트 — 커스텀 분석의 target_numbers에 대해 각 모델 예측값 동적 계산
        renderCustomAnalysisInsight('dlInsightContainer', currentAnalysis)
            .catch(e => console.warn('[CustomInsight] 실패:', e));

    } catch (err) {
        console.error("초기화 중 오류:", err);
        document.getElementById('analysisTitle').textContent = "로드 실패";
    }
}

/**
 * [New] 특정 범위의 회차들에 대해 AI 예측 데이터를 가져와 캐싱합니다.
 */
async function ensureAIHistoryLoaded(rounds) {
    const toFetch = rounds.filter(r => !aiCache.has(r));
    if (toFetch.length === 0) return;

    console.log(`📡 [AI History] ${toFetch.length}개 회차 로딩 중...`);

    // ── 1단계: Supabase 일괄 조회 (1 HTTP 요청) ─────────────────────────
    const dbFoundRounds = new Set();
    try {
        const { data: dbHistory } = await window.supabaseClient
            .from('deep_analysis_history')
            .select('target_round, recommended_numbers, excluded_numbers, analysis_data')
            .in('target_round', toFetch);

        if (dbHistory) {
            dbHistory.forEach(item => {
                const round = item.target_round;
                const analysisData = (typeof item.analysis_data === 'string')
                    ? JSON.parse(item.analysis_data)
                    : item.analysis_data || {};
                const nestedAnalysis = analysisData.analysis || {};
                const matrixData = nestedAnalysis.matrix_data || analysisData.matrix_data || [];

                aiCache.set(round, {
                    ...analysisData,
                    matrix_data: matrixData,
                    recommended_numbers: item.recommended_numbers || [],
                    excluded_numbers: item.excluded_numbers || [],
                    top_5: analysisData.top_5 || analysisData.recommended || item.recommended_numbers || [],
                    exclude_10: analysisData.exclude_10 || analysisData.excluded || item.excluded_numbers || []
                });
                dbFoundRounds.add(round);
            });
        }
    } catch (dbErr) {
        console.warn("⚠️ [AI History] DB 로드 실패:", dbErr);
    }

    // ── 2단계: DB에 없거나, DB에 있어도 matrix_data가 비어있는 회차는 Python API 재호출 ──
    // matrix_data 없으면 모델별(LSTM/XGB/CNN 등) 점수 계산 불가 → 빈 데이터로 캐시된 회차도 재시도
    const noMatrixRounds = [...dbFoundRounds].filter(r => {
        const cached = aiCache.get(r);
        return cached && (!cached.matrix_data || cached.matrix_data.length === 0);
    });
    const needApi = [
        ...toFetch.filter(r => !dbFoundRounds.has(r)),
        ...noMatrixRounds
    ];

    if (needApi.length > 0) {
        console.log(`📡 [AI History] Python API 필요 회차: ${needApi.length}개`);

        // 동시 요청 수 제한 (최대 5개) — Python 서버 과부하 방지
        const CONCURRENCY = 5;
        for (let i = 0; i < needApi.length; i += CONCURRENCY) {
            const batch = needApi.slice(i, i + CONCURRENCY);
            await Promise.all(batch.map(async (round) => {
                try {
                    const data = await window.AIProxy.getPredictions(round);
                    if (data) {
                        const aiResult = (data.success && data.data) ? data.data : data;
                        const existing = aiCache.get(round) || {};
                        const merged = { ...existing, ...aiResult };
                        // matrix_data 위치 정규화 (analysis.matrix_data → 최상위로)
                        if (!merged.matrix_data || merged.matrix_data.length === 0) {
                            merged.matrix_data = aiResult.analysis?.matrix_data || aiResult.matrix_data || [];
                        }
                        aiCache.set(round, merged);
                        // matrix_data 확보 성공 시 DB 갱신 — analysis_data 전체 교체 금지!
                        // analysis_data JSONB 내 matrix_data 키만 패치: 기존 strategy/summary/combinations 보존
                        if (merged.matrix_data?.length > 0 && window.supabaseClient) {
                            // 1) 현재 DB의 analysis_data를 먼저 읽어서
                            window.supabaseClient
                                .from('deep_analysis_history')
                                .select('analysis_data')
                                .eq('target_round', round)
                                .maybeSingle()
                                .then(({ data: row, error: selErr }) => {
                                    if (selErr || !row) return;
                                    // 2) 기존 JSONB에 matrix_data만 병합
                                    let existing_ad = row.analysis_data;
                                    if (typeof existing_ad === 'string') {
                                        try { existing_ad = JSON.parse(existing_ad); } catch { existing_ad = {}; }
                                    }
                                    if (typeof existing_ad !== 'object' || existing_ad === null) existing_ad = {};

                                    // analysis.matrix_data 경로로 저장 (기존 analysis 키 보존)
                                    const patched = {
                                        ...existing_ad,
                                        analysis: {
                                            ...(existing_ad.analysis || {}),
                                            matrix_data: merged.matrix_data
                                        }
                                    };
                                    // 최상위 top_5/exclude_10도 없으면 채워줌 (하위호환)
                                    if (!patched.top_5 && merged.top_5?.length) patched.top_5 = merged.top_5;
                                    if (!patched.exclude_10 && merged.exclude_10?.length) patched.exclude_10 = merged.exclude_10;

                                    // 3) 패치된 전체 구조로 저장
                                    window.supabaseClient
                                        .from('deep_analysis_history')
                                        .update({ analysis_data: patched })
                                        .eq('target_round', round)
                                        .then(({ error }) => {
                                            if (error) console.warn(`[AI] ${round}회차 matrix_data DB 저장 실패:`, error);
                                            else console.log(`✅ [AI] ${round}회차 matrix_data 패치 완료 (strategy 보존)`);
                                        });
                                });
                        }
                    } else if (!aiCache.has(round)) {
                        aiCache.set(round, null);
                    }
                } catch (e) {
                    console.error(`${round}회차 AI 데이터 로드 실패:`, e);
                    if (!aiCache.has(round)) aiCache.set(round, null);
                }
            }));
        }
    }

    // ── 3단계: sessionStorage에 캐시 저장 (다음 방문 시 재요청 방지) ─────
    _persistAiCache();

    console.log(`✅ [AI History] 로드 완료 — DB: ${dbFoundRounds.size}개, API: ${needApi.length}개`);
}

function calculateStats(analysis, draws) {
    if (!analysis || !draws.length) return null;

    const ctx = getAnalysisContext(analysis);
    const { type, isAiType, isExclusion, title: titleStr } = ctx;
    const globalTargets = analysis.target_numbers || [];

    // [New] 회귀 중첩수 기반 동적 그룹 생성 (Regression Overlap)
    if (type === 'regression_overlap' && analysis.config) {
        const { startStep, endStep } = analysis.config;
        // 초기화: 1~45번의 빈도수 카운팅
        const counts = new Array(46).fill(0);

        // 지정된 회귀 범위 내의 모든 과거 번호 스캔
        // draws[0] = 최신 회차. 
        // n회귀 = draws[n] (n번째 전의 데이터)
        for (let s = startStep; s <= endStep; s++) {
            if (draws[s] && draws[s].numbers) {
                draws[s].numbers.forEach(n => {
                    const num = Number(n);
                    if (num >= 1 && num <= 45) counts[num]++;
                });
            }
        }

        // 빈도별 그룹 자동 정의
        const ranges = [
            { label: '30회 이상 (초고빈도)', min: 30, max: 999, color: '#EF4444' }, // Red
            { label: '25~29회 (고빈도)', min: 25, max: 29, color: '#F97316' },   // Orange
            { label: '20~24회 (중상)', min: 20, max: 24, color: '#FACC15' },     // Yellow
            { label: '15~19회 (중간)', min: 15, max: 19, color: '#22C55E' },     // Green
            { label: '10~14회 (중하)', min: 10, max: 14, color: '#3B82F6' },     // Blue
            { label: '5~9회 (저빈도)', min: 5, max: 9, color: '#8B5CF6' },       // Purple
            { label: '5회 미만 (희귀)', min: 0, max: 4, color: '#94A3B8' }      // Gray
        ];

        analysis.config.groups = ranges.map(r => ({
            name: r.label,
            color: r.color,
            numbers: counts.map((c, i) => (c >= r.min && c <= r.max ? i : null)).filter(n => n !== null),
            condition: { min: 1, max: 6 }
        })).filter(g => g.numbers.length > 0);

        // 타입을 그룹 분석으로 변경하여 이후 로직이 정상 작동하게 함
        analysis.type = 'group';
        analysis.title = analysis.title || `${startStep}~${endStep}회귀 중첩 분석`;
    }

    // [New] 다음 회차(Upcoming)를 위한 데이터 추가 준비
    const latestActualDraw = draws[0];
    const nextRound = latestActualDraw.round + 1;

    const ascDraws = [...draws].reverse();

    // [New] 동적 규칙 처리 (Dynamic Rules)
    const isDynamic = type === 'dynamic';
    const rules = analysis.rules || {};

    // 헬퍼: 동적 타겟 계산 함수
    // 날짜 기반 분석을 위해 baseDate 인자 추가, 회차 끝수 분석을 위해 baseRound 추가
    const calculateDynamicTargets = (baseNumbers, baseDate, baseRound) => {
        // [Refactor] 공통 타겟 계산 함수 사용 (회차 끝수 로직 등 통합 관리)
        const tempCustom = {
            ...analysis,
            rules: { ...analysis.rules, regression_step: 1 } // 이미 결정된 base 데이터를 쓰므로 step=1 고정
        };
        const tempDraws = [{ numbers: baseNumbers, date: baseDate, round: baseRound }];
        return window.LOTTO_CONSTANTS.calculateCustomTargets(tempCustom, tempDraws);
    };

    let currentGap = 0;
    let currentStraight = 0;
    let maxGap = 0;
    let maxStraight = 0;
    let maxHits = 0;
    let totalHitCount = 0;
    let hitRounds = 0;

    // [수정] history_data가 있으면 무조건 전체 이력 표시 (aiSource 여부, type 여부 무관)
    // DB에 저장된 GNN/CNN 등 AI 모델들은 type='manual'로 저장되어 있으므로
    // createdAt 필터를 적용하면 과거 데이터가 통째로 막혀버림
    const hasHistoryData = (analysis.history_data || []).length > 0;
    const createdAt = analysis.created_at ? new Date(analysis.created_at) : null;

    // [수정] filteredAscDraws를 기본값(전체 ascDraws)으로 먼저 선언 → 조건과 무관하게 항상 정의됨
    let filteredAscDraws = ascDraws;
    if (!hasHistoryData && !isAiType && createdAt && (type === 'manual' || type === 'direct')) {
        filteredAscDraws = ascDraws.filter(draw => {
            const drawDate = new Date(draw.date);
            return drawDate >= createdAt;
        });
    }

    const history = filteredAscDraws.map((draw, idx) => {
        let targets = [];

        // [유형별 타겟 결정]
        if (type === 'manual' || type === 'direct' || isAiType) {
            const hist = (analysis.history_data || []).find(h => h.target_round === draw.round);
            // [수정] 수파베이스에 저장된 이력 데이터를 최우선으로 사용
            targets = (hist?.target_numbers || []).map(Number);

            // AI 타입: aiCache에서 모델별 점수 기반 대상번호 추출
            if (targets.length === 0 && isAiType) {
                const aiData = aiCache.get(draw.round);
                if (aiData) {
                    targets = extractTargetsFromAIData(aiData, ctx, analysis);
                }
                // matrix_data 없으면 globalTargets로 대체하지 않음 → 빈 배열 유지 (테이블에 "−" 표시)
            }

            // [Fallback] AI 타입이 아닌 경우(manual/direct)만 전역 타겟 사용
            if (targets.length === 0 && !isAiType && globalTargets.length > 0) {
                targets = globalTargets.map(Number);
            }
        } else if (type === 'static') {
            targets = (globalTargets || []).map(Number);
        } else if (isDynamic) {
            if (rules.formula === 'draw_date_end' || rules.formula === 'draw_date_math') {
                targets = (calculateDynamicTargets(null, draw.date, draw.round) || []).map(Number);
            } else if (rules.formula === 'round_end_digit') {
                targets = (calculateDynamicTargets(null, null, draw.round) || []).map(Number);
            } else {
                // [New] 회귀 분석(Regression) 지원: regression_step 만큼 뒤의 회차를 참조
                const step = parseInt(rules.regression_step || 1);
                const currentRoundIdx = draws.findIndex(d => d.round === draw.round);
                const targetDraw = (currentRoundIdx + step < draws.length) ? draws[currentRoundIdx + step] : null;

                if (targetDraw) {
                    targets = (calculateDynamicTargets(targetDraw.numbers) || []).map(Number);
                }
            }
        } else if (type === 'group') {
            const groups = analysis.config?.groups || [];
            // [수정] 그룹 분석에서도 정렬(sort)을 제거하여 설정된 순서를 그대로 따름
            targets = [...new Set(groups.flatMap(g => (g.numbers || []).map(Number)))];
        }
        // 기존 AI 처리 블록 중복 제거 (위로 이동됨)


        const drawNums = (draw.numbers || []).map(Number);
        const matched = drawNums.filter(n => targets.includes(n));
        const hitCount = matched.length;

        // [Standardized] 적중 여부 판단
        // 기본 hit 여부: 제외수인 경우 0개 적중이 성공, 추천수인 경우 1개 이상 적중이 성공
        let isHit = isExclusion ? (hitCount === 0) : (hitCount > 0);

        // [New] 'group' 유형일 경우 위 조건과 그룹별 조건을 병합
        if (type === 'group') {
            const groups = analysis.config?.groups || [];
            const condition = analysis.config?.combineLogic || 'AND';
            const groupHits = groups.map(g => {
                const gNums = (g.numbers || []).map(Number);
                const count = drawNums.filter(n => gNums.includes(n)).length;

                // [Fix] 필터 켜짐/꺼짐 여부와 상관없이, 수열 분석에서 0개는 무조건 미출현(Miss)
                // AI나 설정이 min:0으로 잡혀있어도 1로 강제 보정
                let min = (g.condition?.min !== undefined) ? g.condition.min : 1;
                let max = (g.condition?.max !== undefined) ? g.condition.max : 6;
                if (min === 0) min = 1;

                return (count >= min && count <= max);
            });
            const groupResult = condition === 'AND' ? groupHits.every(v => v) : groupHits.some(v => v);

            // [Decoupled Logic]
            // 전역 필터(fConfig) 연결 여부 판단
            // 사용자가 "필터 적용"을 켰다면 필터 조건도 만족해야 함.
            // 단, 0개 적중은 이미 min=1 보정으로 인해 groupResult에서 걸러짐.
            if (fConfig.enabled) {
                if (fConfig.values && fConfig.values.length > 0) {
                    isHit = groupResult && fConfig.values.includes(hitCount);
                } else {
                    isHit = groupResult && (hitCount >= fConfig.min && hitCount <= fConfig.max);
                }
            } else {
                // 필터를 껐다면: 그룹 조건만 따짐
                isHit = groupResult;
            }
        }

        if (isHit) {
            currentStraight++;
            currentGap = 0;
            hitRounds++;
        } else {
            currentGap++;
            currentStraight = 0;
        }

        maxGap = Math.max(maxGap, currentGap);
        maxStraight = Math.max(maxStraight, currentStraight);
        maxHits = Math.max(maxHits, hitCount);
        totalHitCount += hitCount;

        return {
            round: draw.round,
            winNumbers: draw.numbers,
            targets: targets,
            matched: matched,
            hitCount: hitCount,
            gap: currentGap,
            straight: currentStraight,
            isHit: isHit
        };
    });

    // ---------------------------------------------------------
    // [CRITICAL] 다음 회차(Upcoming Round) 가상 로우 추가
    // ---------------------------------------------------------
    let nextTargets = [];
    if (type === 'manual' || type === 'direct') {
        // [추가] manual 타입이더라도 aiSource가 설정되어 있다면 차기 회차용 AI 캐시 데이터 우선 적용
        const aiSource = analysis.config?.aiSource;
        const aiData = aiCache.get(nextRound);
        if (aiSource && aiData) {
            if (aiSource === 'dl_recommended') {
                // [수정] 5개 요약(top_5)보다 전체 목록(recommended_numbers)을 우선하도록 순서 교정
                nextTargets = (aiData.recommended_numbers || aiData.recommended || aiData.top_5 || []).map(Number);
            } else if (aiSource === 'dl_excluded') {
                nextTargets = (aiData.excluded_numbers || aiData.excluded || aiData.exclude_10 || []).map(Number);
            }
        }

        // 데이터가 없거나 aiSource가 없는 경우에만 전역 고정 타겟 사용
        if (nextTargets.length === 0) {
            nextTargets = [...globalTargets];
        }
    } else if (type === 'static') {
        nextTargets = globalTargets;
    } else if (isDynamic) {
        if (latestActualDraw) {
            if (rules.formula === 'draw_date_end' || rules.formula === 'draw_date_math') {
                // [New] 다음 추첨일 예측 (가장 최근 당첨일 + 7일)
                // date가 YYYY-MM-DD 또는 ISO 형식이면 파싱 가능
                const lastDate = new Date(latestActualDraw.date);
                if (!isNaN(lastDate.getTime())) {
                    const nextDate = new Date(lastDate);
                    nextDate.setDate(lastDate.getDate() + 7); // +1주일
                    nextTargets = calculateDynamicTargets(null, nextDate.toISOString(), nextRound);
                }
            } else if (rules.formula === 'round_end_digit') {
                nextTargets = calculateDynamicTargets(null, null, nextRound);
            } else {
                // [New] 회귀 기반 다음 회차 타겟 산출
                const step = parseInt(rules.regression_step || 1);
                // 다음 회차(nextRound) 기준 step만큼 전 회차는 draws[step-1] 임
                const targetDraw = (step - 1 < draws.length) ? draws[step - 1] : null;
                if (targetDraw) {
                    nextTargets = calculateDynamicTargets(targetDraw.numbers);
                }
            }
        }
    } else if (type === 'group') {
        const groups = analysis.config?.groups || [];
        // [수정] 정렬 제거
        nextTargets = [...new Set(groups.flatMap(g => g.numbers))];
    } else if (isAiType) {
        // [New] 다음 회차 AI 예측 데이터 로드 (통합 헬퍼 사용으로 1220회차 이슈 해결)
        const aiData = aiCache.get(nextRound);
        if (aiData) {
            nextTargets = extractTargetsFromAIData(aiData, ctx, analysis);
        }
    }

    const nextRow = {
        round: nextRound,
        winNumbers: [0, 0, 0, 0, 0, 0, 0], // 미추첨
        targets: nextTargets,
        matched: [],
        hitCount: 0,
        gap: currentGap, // 현재 연속 미출현 유지
        straight: 0,
        isUpcoming: true
    };

    // 최신 순 정렬 (DESC): 다음 회차가 맨 위, 그 다음 최근 당첨 회차들
    const sortedHistory = [...history].reverse();

    // 타입별 노출 범위 결정:
    // - direct(직접입력형): 분석 생성 시점 이후 회차만 표시
    // - AI 모델 타입(딥러닝 제외수, 추천수, 모델별, 추천조합 등): 1212회차 이후만
    // - 그 외(정적, 그룹 등): 전체 회차 노출
    let filteredHistory;
    if (type === 'direct') {
        const createdAt = analysis.created_at ? new Date(analysis.created_at) : null;
        if (createdAt) {
            // draws(desc)에서 생성 시점 이후 회차의 최소(첫 번째) 회차 번호 산출
            const afterCreation = draws.filter(d => new Date(d.date) >= createdAt);
            const firstRound = afterCreation.length > 0 ? afterCreation[afterCreation.length - 1].round : 0;
            filteredHistory = firstRound > 0 ? sortedHistory.filter(r => r.round >= firstRound) : sortedHistory;
        } else {
            filteredHistory = sortedHistory;
        }
    } else if (isAiType) {
        // AI 모델 타입: 1212회차 이후만 (백필 데이터 범위)
        filteredHistory = sortedHistory.filter(r => r.round >= 1212);
    } else {
        filteredHistory = sortedHistory;
    }
    const combinedRows = [nextRow, ...filteredHistory];

    // [수정] 차기 회차 타겟을 메모리(헤더 Ball)에만 동기화 — DB 쓰기 side effect 제거
    // calculateStats()는 순수 계산 함수여야 하므로 DB 갱신은 명시적 저장 액션(saveManual 등)에서만 수행
    if (nextTargets && nextTargets.length > 0) {
        currentAnalysis.target_numbers = [...nextTargets];
        renderBaseInfo();
    }

    // AI 타입은 슬라이더(historyViewLimit) 없이 전체 로드; 일반 타입은 전체 회차 노출
    const finalRows = combinedRows;

    return {
        rows: finalRows,
        currentGap: history[history.length - 1]?.gap || 0,
        currentStraight: history[history.length - 1]?.straight || 0,
        maxGap, maxStraight, maxHits,
        hitRate: (hitRounds > 0 && history.length > 0 ? (hitRounds / history.length) * 100 : 0),
        avgHits: (history.length > 0 ? totalHitCount / history.length : 0)
    };
}

// [Mod] skipAI 파라미터 추가 - 리스트 클릭 시 자동 분석 방지
async function updateAnalysisDisplay(skipAI = false) {
    const ctx = getAnalysisContext(currentAnalysis);
    const { type, isAiType } = ctx;

    // [New] AI 분석 유형일 경우 과거 데이터 로딩
    if (isAiType || type.startsWith('ai_')) {
        const latestRound = allDrawData[0]?.round || 0;
        const eligible = allDrawData.filter(d => d.round >= 1212).map(d => d.round);

        // [성능] 1단계: 최근 20회차만 먼저 로드 → 화면 즉시 표시
        const firstBatch = eligible.slice(0, 20);
        firstBatch.push(latestRound + 1); // 차기 회차 포함
        await ensureAIHistoryLoaded(firstBatch);

        // [성능] 2단계: 나머지 회차는 화면 렌더링 후 백그라운드 로드
        const remaining = eligible.slice(20);
        if (remaining.length > 0) {
            setTimeout(() => ensureAIHistoryLoaded(remaining).then(() => {
                // 백그라운드 로드 완료 후 테이블만 조용히 갱신
                const stats = calculateStats(currentAnalysis, allDrawData);
                if (stats) renderHistoryTable(stats);
            }), 0);
        }
    }

    const stats = calculateStats(currentAnalysis, allDrawData);
    if (!stats) return;

    // [성능] stats 결과 캐시 → refreshAIAnalysis에서 중복 연산 방지
    _lastStats = stats;
    _lastStatsId = currentAnalysis?.id;

    renderDashboard(stats);
    renderHeaderBalls(stats);
    renderFilterUI();
    renderHistoryTable(stats);

    // [New] AI 분석 리포트 자동 갱신 (skipAI가 false일 때만 실행)
    if (!skipAI && window.refreshAIAnalysis) window.refreshAIAnalysis();
}

// Zone A: 헤더 정보
function renderBaseInfo() {
    document.getElementById('analysisTitle').textContent = currentAnalysis.title || '커스텀 분석';
    document.getElementById('analysisDesc').textContent = currentAnalysis.description || currentAnalysis.original_prompt || '';
}

function renderHeaderBalls(stats) {
    const container = document.getElementById('targetBallContainer');
    const filterContainer = document.getElementById('targetBallContainerFilter');

    if (!container && !filterContainer) return;

    // [Mod] calculateStats에서 계산된 최신 회차(Next Round)의 타겟 번호를 가져와서 표시
    // stats가 없으면 기존 로직(static) fallback
    let targets = [];
    if (stats && stats.rows && stats.rows.length > 0) {
        // stats.rows[0]은 Next Round (Upcoming)
        targets = stats.rows[0].targets || [];
    } else {
        targets = (currentAnalysis.target_numbers || []);
    }

    const html = (!targets || targets.length === 0) ?
        '<span class="text-sm text-gray-400">선택된 번호가 없습니다.</span>' :
        targets.map(num => {
            const bg = getStandardBallGradient(num);
            return `<div class="w-8 h-8 rounded-full flex items-center justify-center text-white font-medium text-[13px]" style="background:${bg}; box-shadow:0 2px 4px rgba(0,0,0,0.12)">${num}</div>`;
        }).join('');

    if (container) container.innerHTML = html;
    if (filterContainer) filterContainer.innerHTML = html;
}

// Zone B: 대시보드
function renderDashboard(stats) {
    document.getElementById('currGap').textContent = stats.currentGap;
    document.getElementById('currStraight').textContent = stats.currentStraight;
    document.getElementById('maxGap').textContent = stats.maxGap;
    document.getElementById('maxStraight').textContent = stats.maxStraight;
    document.getElementById('maxHitCount').textContent = stats.maxHits;
    document.getElementById('totalHitRate').textContent = `${stats.hitRate.toFixed(1)}%`;
    document.getElementById('avgHitCount').textContent = stats.avgHits.toFixed(2);

    // [New] 출현 임박 지수 (Imminence Index) 산출
    // 1. Gap Score (80%): 현재 미출현이 역대 최대치에 얼마나 근접했는가
    const gapScore = stats.maxGap > 0 ? (stats.currentGap / stats.maxGap) * 80 : 0;
    // 2. Frequency Bonus (20%): 패턴 자체가 얼마나 자주 나오는가 (평균 2.0개를 만점으로 계산)
    const freqBonus = Math.min(20, (stats.avgHits * 10));

    const imminenceIndex = Math.min(100, Math.round(gapScore + freqBonus));

    const riskScoreEl = document.getElementById('riskScore');
    const riskBarEl = document.getElementById('riskBar');

    if (riskScoreEl) riskScoreEl.textContent = `${imminenceIndex}%`;
    if (riskBarEl) {
        riskBarEl.style.width = `${imminenceIndex}%`;
        // 상태에 따른 색상 변경
        riskBarEl.classList.remove('bg-green-500', 'bg-orange-500', 'bg-red-500');
        if (imminenceIndex >= 80) riskBarEl.classList.add('bg-red-500');
        else if (imminenceIndex >= 50) riskBarEl.classList.add('bg-orange-500');
        else riskBarEl.classList.add('bg-green-500');
    }
}

// Zone C: 수동/수식/그룹 컨트롤
function renderTypeSpecificControls() {
    const area = document.getElementById('manualControlSection');
    if (!area) return;

    const type = currentAnalysis.type || 'static';

    if (type === 'manual' || type === 'direct') {
        area.classList.remove('hidden');
        renderManualGrid(area);
    } else if (type === 'group') {
        area.classList.remove('hidden');
        renderGroupSummary(area);
    } else {
        area.classList.add('hidden');
    }
}

function renderGroupSummary(container) {
    const groups = currentAnalysis.config?.groups || [];
    if (!groups.length) {
        container.innerHTML = `<div class="bg-white p-6 rounded-xl border border-gray-200 text-center text-gray-400">정의된 그룹이 없습니다.</div>`;
        return;
    }

    const groupHtml = groups.map(g => `
        <div class="p-3 bg-gray-50 rounded-lg border border-gray-100">
            <div class="flex items-center gap-2 mb-2">
                <span class="w-3 h-3 rounded-full" style="background-color: ${g.color || '#3B82F6'}"></span>
                <span class="font-bold text-gray-700">${g.name}</span>
                <span class="text-xs text-gray-400">${g.condition?.min}~${g.condition?.max}개 조건</span>
            </div>
            <div class="flex flex-wrap gap-1">
                ${g.numbers.slice(0, 10).map(n => `<span class="text-[10px] text-gray-500">${n}</span>`).join('')}
                ${g.numbers.length > 10 ? '<span class="text-[10px] text-gray-300">...</span>' : ''}
            </div>
        </div>
    `).join('');

    container.innerHTML = `
        <div class="bg-white p-6 rounded-xl border border-gray-200 shadow-sm">
            <h3 class="text-base font-bold text-gray-900 flex items-center gap-2 mb-4">
                <span class="material-symbols-outlined text-purple-600">group_work</span>
                그룹 분석 구성
            </h3>
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                ${groupHtml}
            </div>
        </div>
    `;
}

function renderManualGrid(container) {
    const latestRound = allDrawData[0]?.round || 0;
    const targetRound = latestRound + 1;
    const targets = (currentAnalysis.target_numbers || []).sort((a, b) => a - b);

    // [Optimize] 컨테이너가 이미 그려져 있다면 헤더 텍스트만 갱신
    let grid = document.getElementById('numberGrid');
    if (!grid) {
        container.innerHTML = `
            <div class="bg-white p-6 rounded-[2rem] border border-slate-200 shadow-xl shadow-slate-200/50 space-y-6">
                <div class="flex flex-col md:flex-row md:items-center justify-between gap-4">
                    <div class="flex items-center gap-4">
                        <div class="w-10 h-10 bg-indigo-50 rounded-2xl flex items-center justify-center text-indigo-600 shadow-inner">
                            <span class="material-symbols-outlined text-xl font-bold">touch_app</span>
                        </div>
                        <div>
                            <h3 class="text-lg font-black text-slate-900" id="manualTargetTitle">${targetRound}회차 번호 선택</h3>
                            <p class="text-[10px] font-bold text-slate-400 uppercase tracking-widest mt-0.5">다음 회차 번호 선택</p>
                        </div>
                    </div>
                    <div class="flex gap-1">
                        <button onclick="window.clearManual()" class="w-9 h-9 flex items-center justify-center text-slate-400 hover:text-slate-600 rounded-lg transition-all" title="전체 해제">
                            <span class="material-symbols-outlined text-xl">backspace</span>
                        </button>
                        <button onclick="window.saveManual()" class="w-9 h-9 flex items-center justify-center text-slate-400 hover:text-slate-600 rounded-lg transition-all" title="저장">
                            <span class="material-symbols-outlined text-xl">save</span>
                        </button>
                    </div>
                </div>
                <div class="overflow-x-auto custom-scrollbar pb-2">
                    <!-- [수정] 2줄 -> 3줄 레이아웃으로 변경 (높이 확보) -->
                    <div id="numberGrid" class="grid grid-rows-3 grid-flow-col gap-1.5 min-w-max h-[140px] items-center"></div>
                </div>
            </div>
        `;
        grid = document.getElementById('numberGrid');
    } else {
        const titleEl = document.getElementById('manualTargetTitle');
        if (titleEl) titleEl.innerText = `${targetRound}회차 번호 선택`;
    }

    if (!grid) return;

    // [Optimize] 버튼이 이미 생성되어 있다면 상태만 갱신
    if (grid.children.length === 0) {
        for (let i = 1; i <= 45; i++) {
            const btn = document.createElement('button');
            btn.id = `manual-btn-${i}`;
            // 이벤트 리스너를 한 번만 등록
            btn.onclick = (e) => {
                e.preventDefault(); // 화면 움직임 방지 보강
                const idx = currentAnalysis.target_numbers.indexOf(i);
                if (idx >= 0) currentAnalysis.target_numbers.splice(idx, 1);
                else currentAnalysis.target_numbers.push(i);

                // 전역 상태 업데이트 및 디스플레이 갱신 (리스트 등)
                updateAnalysisDisplay(true); // AI 분석은 스킵

                // 버튼 스타일만 즉시 업데이트 (전체 리렌더링 방지)
                updateManualGridUI();
                renderHeaderBalls(); // 상단 볼 영역은 별도로 갱신
            };
            grid.appendChild(btn);
        }
    }

    updateManualGridUI();
}

/**
 * [New] 직접 입력형 그리드의 버튼 스타일만 부분적으로 업데이트하여 성능 개선 및 떨림 방지
 */
function updateManualGridUI() {
    const targets = (currentAnalysis.target_numbers || []).map(Number);
    for (let i = 1; i <= 45; i++) {
        const btn = document.getElementById(`manual-btn-${i}`);
        if (!btn) continue;

        const active = targets.includes(i);
        const bg = getStandardBallGradient(i);

        btn.className = `w-[34px] h-[34px] rounded-full flex items-center justify-center text-[11px] font-bold border transition-all ${active ? 'text-white border-transparent scale-105 shadow-md' : 'bg-white border-slate-100 text-slate-300 hover:border-indigo-100 hover:text-indigo-400'
            }`;
        btn.style.background = active ? bg : 'white';
        btn.style.boxShadow = active ? '0 2px 4px rgba(0,0,0,0.12)' : '';
        btn.innerText = i;
    }
}

// Zone E: 필터
function renderFilterUI() {
    const config = currentAnalysis.filter_config || { min: 1, max: 3, enabled: false };
    document.getElementById('customFilterMin').value = config.min;
    document.getElementById('customFilterMax').value = config.max;

    // [추가] 필터 토글 상태 반영
    const filterToggle = document.getElementById('filterToggle');
    if (filterToggle) {
        filterToggle.checked = (config.enabled === true);
    }
}

// [New] 필터 범위 직접 업데이트 함수 (Pill 디자인 대응)
window.updateCustomRange = async function (type, val) {
    if (!currentAnalysis) return;
    const value = parseInt(val) || 0;

    if (type === 'min') currentAnalysis.filter_config.min = value;
    else if (type === 'max') currentAnalysis.filter_config.max = value;

    // values 배열 초기화 (min-max 모드로 전환)
    delete currentAnalysis.filter_config.values;

    await saveFilterConfig();
    updateAnalysisDisplay(true); // UI만 갱신
};

// [Global Function] 필터 토글 저장 함수 (HTML onchange에서 호출됨)
window.saveCustomFilter = async function () {
    const toggle = document.getElementById('filterToggle');
    if (!toggle || !currentAnalysis) return;

    currentAnalysis.filter_config.enabled = toggle.checked;

    // DB Update
    await saveFilterConfig();
}

// 내부 저장 함수
async function saveFilterConfig() {
    if (!currentAnalysis) return;

    // [추가] 수동 설정 플래그 및 현재 회차 정보 기록 (회차 업데이트 시 자동 보정 트리거용)
    const latestRound = (allDrawData && allDrawData.length > 0) ? allDrawData[0].round : 0;
    currentAnalysis.filter_config.is_manual = true;
    currentAnalysis.filter_config.last_calibrated_round = latestRound;

    try {
        const { error } = await window.supabaseClient.from('ai_custom_analyses')
            .update({ filter_config: currentAnalysis.filter_config })
            .eq('id', currentAnalysis.id);

        if (error) throw error;


        // [수정] localStorage에도 동시 저장하여 대시보드 및 타 탭과 동기화
        if (window.Utils && window.Utils.saveFilter) {
            window.Utils.saveFilter(`custom_filter_${currentAnalysis.id}`, currentAnalysis.filter_config);
        } else {
            const storageKey = `custom_filter_${currentAnalysis.id}`;
            localStorage.setItem(storageKey, JSON.stringify(currentAnalysis.filter_config));
        }

        // [New] 사이드바 'ON' 뱃지 갱신을 위해 메뉴 다시 그리기
        if (window.renderCustomMenuItems) {
            await window.renderCustomMenuItems();
        }

        // 성공 시 토스트는 너무 자주 뜨면 귀찮으므로 생략하거나 짧게
        // showToast("필터 설정 저장됨");

    } catch (err) {
        console.error("필터 저장 실패:", err);
        alert("설정 저장에 실패했습니다.");
        // 실패 시 롤백 UI 처리 필요하나 복잡성 때문에 생략
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// [자동보정] 매주 회차 업데이트 시 전체 커스텀 분석 필터 min/max 자동 재설정
// filter_config.last_calibrated_round < 최신 회차인 분석만 업데이트
// ─────────────────────────────────────────────────────────────────────────────
let _hasRunAutoCalibrate = false; // 탭 세션 내 1회만 실행

async function batchCalibrateAllFilters() {
    if (!allDrawData || allDrawData.length === 0) return;
    const latestRound = allDrawData[0].round;

    try {
        // 전체 커스텀 분석 목록 로드
        let query = window.supabaseClient.from('ai_custom_analyses').select('*');
        const userId = window.filterService?.userId;
        if (userId) query = query.or(`user_id.eq.${userId},user_id.is.null`);

        const { data: allAnalyses, error } = await query;
        if (error || !allAnalyses || allAnalyses.length === 0) return;

        // 보정이 필요한 분석만 선별:
        // 1) last_calibrated_round < latestRound (새 회차 업데이트)
        // 2) min=0 AND max=0 (이전 보정이 잘못된 경우 강제 재보정)
        const toUpdate = allAnalyses.filter(a => {
            try {
                const fc = typeof a.filter_config === 'string'
                    ? JSON.parse(a.filter_config)
                    : (a.filter_config || {});
                const needsRound = (fc.last_calibrated_round || 0) < latestRound;
                const isBroken = (fc.min === 0 && fc.max === 0);
                return needsRound || isBroken;
            } catch (e) { return true; }
        });

        if (toUpdate.length === 0) {
            console.log(`[AutoCalibrate] 전체 분석 최신 상태 (회차: ${latestRound})`);
            return;
        }

        console.log(`[AutoCalibrate] ${toUpdate.length}개 분석 필터 자동 보정 시작 (기준 회차: ${latestRound}회)`);

        // [사전 준비] AI 타입 분석의 calculateStats에 필요한 aiCache 확보 (최근 20회차만)
        const recentRounds = allDrawData.filter(d => d.round >= 1212).slice(0, 20).map(d => d.round);
        recentRounds.push(latestRound + 1);
        await ensureAIHistoryLoaded(recentRounds);

        for (const analysis of toUpdate) {
            try {
                const fc = typeof analysis.filter_config === 'string'
                    ? JSON.parse(analysis.filter_config)
                    : (analysis.filter_config || { min: 1, max: 3, enabled: false });

                // [수정] AI/수동 타입 분석은 history_data와 config가 필요
                if (!analysis.history_data) {
                    const { data: histData } = await window.supabaseClient
                        .from('analysis_history')
                        .select('*')
                        .eq('analysis_id', analysis.id);
                    analysis.history_data = histData || [];
                }
                // config 하이드레이션 (rules.config → config)
                if (!analysis.config && analysis.rules?.config) {
                    analysis.config = analysis.rules.config;
                }

                // calculateStats로 최근 10회차 적중 분포 계산
                const tempStats = calculateStats(analysis, allDrawData);
                if (!tempStats || !tempStats.rows || tempStats.rows.length < 3) continue;

                // Upcoming(다음 회차) 제외한 최근 10회차 hit count
                const last10 = tempStats.rows.filter(r => !r.isUpcoming).slice(0, 10);
                if (last10.length < 3) continue;

                const hits = last10.map(r => r.hitCount);
                const minHit = Math.min(...hits);
                const maxHit = Math.max(...hits);

                // 새 filter_config: min/max 보정 + last_calibrated_round 기록
                const newFc = { ...fc, min: minHit, max: maxHit, last_calibrated_round: latestRound };
                delete newFc.values; // values 초기화 (min-max 범위 모드로 리셋)

                // DB 저장
                const { error: updateErr } = await window.supabaseClient
                    .from('ai_custom_analyses')
                    .update({ filter_config: newFc, updated_at: new Date().toISOString() })
                    .eq('id', analysis.id);

                if (updateErr) { console.warn(`[AutoCalibrate] ${analysis.id} 저장 실패:`, updateErr.message); continue; }

                // 현재 열린 분석이면 메모리·UI·대시보드·히스토리 전체 재렌더
                if (currentAnalysis && currentAnalysis.id === analysis.id) {
                    currentAnalysis.filter_config = newFc;
                    renderFilterUI();
                    if (window.Utils && window.Utils.saveFilter) {
                        window.Utils.saveFilter(`custom_filter_${analysis.id}`, newFc);
                    }
                    // [핵심] 리스트/대시보드까지 새 min/max로 재계산되도록 전체 갱신
                    if (typeof updateAnalysisDisplay === 'function') {
                        try { await updateAnalysisDisplay(true); } catch (e) { /* noop */ }
                    }
                }

                console.log(`[AutoCalibrate] ✅ ${analysis.title || analysis.id}: min=${minHit}, max=${maxHit}`);
            } catch (e) {
                console.warn(`[AutoCalibrate] ${analysis.id} 처리 실패:`, e.message);
            }
        }

        console.log(`[AutoCalibrate] 완료 — ${toUpdate.length}개 분석 필터 재설정 (${latestRound}회차 기준)`);

    } catch (e) {
        console.error('[AutoCalibrate] 일괄 보정 오류:', e);
    }
}

// Zone F: 히스토리 테이블
function renderHistoryTable(stats) {
    const headerGrid = document.getElementById('historyHeader');
    const tbody = document.getElementById('historyTableBody');
    if (!tbody || !headerGrid) {
        console.error("Table elements not found:", { headerGrid, tbody });
        return;
    }

    const ctx = getAnalysisContext(currentAnalysis);
    const { type, isAiType } = ctx;
    const isStatic = (type === 'static');

    // [New] 고정형(Static)일 경우 통계 보기 버튼 표시
    const statsBtnContainer = document.getElementById('statsBtnContainer');
    if (statsBtnContainer) {
        if (isStatic) statsBtnContainer.classList.remove('hidden');
        else statsBtnContainer.classList.add('hidden');
    }

    // [Mod] 날짜 기반 분석 감지 (formula가 'draw_date_end' 이면 날짜 컬럼 표시)
    // 혹은 사용자가 명시적으로 날짜 보기를 원할 수도 있음(추후 옵션). 여기선 rule 기반 자동 감지.
    const isDateBased = (currentAnalysis.rules?.formula === 'draw_date_end');

    // [표준화] 헤더 재구성 (Table Headers) - [Mod] 텍스트 크기 확대 (text-base)
    let headerHtml = `
        <tr class="text-base font-black uppercase tracking-wider text-white">
            <th class="py-4 px-4 text-center w-20 sticky left-0 bg-slate-900 z-40">회차</th>
    `;

    if (isDateBased) {
        headerHtml += `<th class="py-4 px-4 text-center w-28 whitespace-nowrap">추첨일</th>`;
    }

    headerHtml += `
            <th class="py-4 px-4 text-center w-[300px]">당첨번호</th>
            <th class="py-4 px-4 text-center">분석 대상 (Target)</th>
            <th class="py-4 px-2 text-center w-24">HIT</th>
            <th class="py-4 px-2 text-center w-24">GAP</th>
            <th class="py-4 px-2 text-center w-24">STR</th>
        </tr>
    `;

    headerGrid.innerHTML = headerHtml;
    // Remove grid classes from header row since it's now a thead
    headerGrid.className = "sticky top-0 bg-slate-900 text-white font-semibold border-b border-[#334155] z-30";


    // [Refinement] 정교한 HIT/GAP/STR 색상 정의
    const statColors = {
        hit: { bg: 'bg-blue-600', text: 'text-white' }, // Blue
        gapHit: { bg: 'bg-blue-600', text: 'text-white' }, // 당 (Blue)
        gapMiss: { bg: 'bg-red-500', text: 'text-white' }, // 미 (Red)
        str: { bg: 'bg-slate-800', text: 'text-white' }
    };

    // [UI Standardization] 전체 로우 중 '최대 타겟 개수'를 기준으로 통일된 사이즈 적용
    // [Fix] stats.rows가 비어있을 경우 0으로 처리 (Math.max 오류 방지)
    const maxTargetLen = stats.rows.length > 0 ? Math.max(...stats.rows.map(r => r.targets.length)) : 0;

    // [Refinement] 타겟 번호 개수가 모든 회차에서 동일한지 여부 판단 (Fixed Count)
    // - 개수 동일(Fixed Count): 중앙 정렬 (justify-center) - 번호가 달라도 개수가 같으면 중앙
    // - 개수 다름(Variable Count): 좌측 정렬 (justify-start)
    let isFixedCount = false;
    if (stats.rows.length > 0) {
        const firstLen = stats.rows[0].targets.length;
        isFixedCount = stats.rows.every(r => r.targets.length === firstLen);
    }

    // [Mod] 당첨번호 크기(w-9 h-9)와 동일하게 최대 크기 제한
    let globalSizeClass = 'text-base';
    let globalGapClass = 'gap-2';

    // 기본값: w-9 (36px) - 당첨번호와 동일한 크기 (폰트도 text-sm으로 맞춤)
    // 중요: 테두리가 있으므로 내부 공간이 조금 좁아 보일 수 있음 -> w-9 유지하되 폰트는 sm
    let globalBallSize = 'min-w-[2.25rem] w-9 h-9 text-sm';
    let globalBallGap = 'gap-2';

    // 단계별 축소 로직 (최대 개수 기준)
    // [Refinement] 고정형(Fixed)일 경우, 개수가 적당하면(15개 이하) 무조건 당첨번호 사이즈 유지
    if (isFixedCount && maxTargetLen <= 15) {
        globalBallSize = 'min-w-[2.25rem] w-9 h-9 text-sm';
        globalBallGap = 'gap-2';
    } else {
        // 단, 너무 많으면 어쩔 수 없이 줄여야 함
        if (maxTargetLen > 25) {
            // 25개 초과
            globalSizeClass = 'text-[10px]';
            globalGapClass = 'gap-0.5';
            globalBallSize = 'w-5 h-5 text-[10px]';
            globalBallGap = 'gap-0.5';
        } else if (maxTargetLen > 20) {
            // 21~25개
            globalSizeClass = 'text-xs';
            globalGapClass = 'gap-1';
            globalBallSize = 'w-6 h-6 text-xs';
            globalBallGap = 'gap-1';
        } else if (maxTargetLen > 15) {
            // 16~20개: w-7 (28px)
            globalSizeClass = 'text-sm';
            globalGapClass = 'gap-1';
            globalBallSize = 'min-w-[1.75rem] w-7 h-7 text-xs';
            globalBallGap = 'gap-1';
        } else {
            // 15개 이하 (가변형이라도 공간 충분하면 w-9)
            globalSizeClass = 'text-base';
            globalGapClass = 'gap-1.5';
            globalBallSize = 'min-w-[2.25rem] w-9 h-9 text-sm'; // [Force] w-9 유지
            globalBallGap = 'gap-1.5';
        }
    }

    // 정렬 클래스 결정
    const alignClassBase = isFixedCount ? 'justify-center' : 'justify-start';

    // 2. 바디 렌더링
    tbody.innerHTML = stats.rows.map((row, index) => {
        const isInRange = (rangeHighlightIndex !== -1 && index >= rangeHighlightIndex && index < rangeHighlightIndex + 10);

        // [New] 직접 입력형 또는 AI 분석 유형일 경우 텍스트/모델 순위 보존 렌더링
        const isRankType = (type === 'manual' || type === 'direct' || type.startsWith('ai_'));

        // [수정] 딥러닝/수동입력 타입(isRankType)은 항상 좌측 정렬, 그 외는 기존 로직
        const alignClass = isRankType
            ? `justify-start ${globalGapClass}`
            : `${alignClassBase} ${globalGapClass}`;

        const targetVisualManual = `<div class="flex flex-nowrap items-center ${alignClass} pl-2" style="max-width: 100%; overflow-x: auto;">${row.targets.map(n => {
            const isMatched = row.matched.includes(n);
            const textClass = isMatched ? 'text-red-500 font-bold' : 'text-slate-400';
            return `<span class="${textClass} ${globalSizeClass} transition-all whitespace-nowrap shrink-0">${n}</span>`;
        }).join('')}</div>`;

        // [Refinement] 기본형 (정렬 + 글로벌 사이즈 적용)
        const alignClassDefault = `${alignClassBase} items-center ${globalBallGap}`;

        const targetVisualDefault = `<div class="flex flex-nowrap ${alignClassDefault}" style="max-width: 100%; overflow-x: auto;">${row.targets.map(n => {
            const isMatched = row.matched.includes(n);
            const bg = getStandardBallGradient(n);
            const ballClass = isMatched
                ? 'text-white'
                : 'text-slate-700 border border-slate-400 bg-white font-bold';
            const ballStyle = isMatched ? `background: ${bg}; box-shadow:0 2px 4px rgba(0,0,0,0.12);` : '';
            return `<span class="${globalBallSize} rounded-full flex items-center justify-center font-bold transition-all shrink-0 ${ballClass}" style="${ballStyle}">${n}</span>`;
        }).join('')}</div>`;

        // [수정] AI 타입 전용: CSS Grid repeat(20, 1fr) — 열 너비에 꽉 차도록 20개씩 자동 분배
        // 볼 크기가 열 너비를 20등분한 크기로 자동 계산되어 항상 딱 맞게 표시됨
        const targetVisualAI = row.targets.length === 0
            ? `<div class="flex items-center justify-center w-full">
                   <span class="text-[11px] text-slate-300 italic px-2">모델 점수 데이터 없음</span>
               </div>`
            : `<div style="display:grid; grid-template-columns:repeat(20, 1fr); gap:2px; width:100%; padding:2px 6px; box-sizing:border-box;">${row.targets.map(n => {
                const isMatched = row.matched.includes(n);
                const bg = getStandardBallGradient(n);
                const baseStyle = `aspect-ratio:1/1; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:700; font-size:9px; min-width:0;`;
                const colorStyle = isMatched
                    ? `background:${bg}; color:#fff; box-shadow:0 1px 3px rgba(0,0,0,0.15);`
                    : `background:#fff; color:#64748b; border:1px solid #cbd5e1;`;
                return `<span style="${baseStyle}${colorStyle}">${n}</span>`;
            }).join('')}</div>`;

        let targetContent = '';
        if (isRankType) {
            const isManualEntry = (type === 'manual' || type === 'direct') && !isAiType;

            if (isAiType) {
                // ── AI 분석 타입 (딥러닝 제외수/추천수/추천조합, 앙상블, LSTM, XGB 등):
                // 원형 공(circle) 스타일 — 미적중: 테두리 원, 적중: 그라데이션 채움
                targetContent = targetVisualAI;

            } else if (isManualEntry && editingRound === row.round) {
                // ── 편집 모드 (manual/direct 전용): 인풋박스 ──
                targetContent = `
                    <div class="flex flex-col items-center gap-2 w-full px-4" onclick="event.stopPropagation()">
                        <input type="text"
                               id="edit-input-${row.round}"
                               value="${row.targets.join(', ')}"
                               placeholder="번호 입력 (예: 1 2 3)"
                               onkeydown="if(event.key==='Enter') window.saveHistoryTarget(${row.round}, this.value)"
                               onblur="window.saveHistoryTarget(${row.round}, this.value, true)"
                               class="w-full text-center text-xs py-1.5 border-2 border-indigo-400 rounded-lg focus:ring-2 focus:ring-indigo-300 transition-all bg-white shadow-lg font-medium outline-none">
                        <p class="text-[9px] text-indigo-500 font-bold animate-pulse">엔터를 치면 저장됩니다</p>
                    </div>
                `;
                setTimeout(() => {
                    const el = document.getElementById(`edit-input-${row.round}`);
                    if (el) { el.focus(); el.select(); }
                }, 10);

            } else {
                // ── 보기 모드 (manual/direct): 클릭-투-에디트 텍스트 ──
                targetContent = `
                    <div class="cursor-pointer group/edit relative w-full h-full min-h-[50px] flex items-center justify-start pl-2 rounded-xl transition-colors ${isManualEntry ? 'hover:bg-slate-100/50' : ''}"
                         ${isManualEntry ? `onclick="event.stopPropagation(); window.enterEditMode(${row.round})"` : ''}>
                        ${targetVisualManual}
                        ${isManualEntry ? `
                        <div class="absolute inset-0 flex items-center justify-center opacity-0 group-hover/edit:opacity-100 transition-opacity pointer-events-none">
                            <span class="bg-indigo-600 text-white text-[10px] px-2 py-1 rounded-full shadow-lg font-bold">클릭하여 수정</span>
                        </div>` : ''}
                    </div>
                `;
            }
        } else {
            // 고정형(static), 그룹형, 동적(dynamic) 등: 원래 원형 공 스타일 유지
            targetContent = targetVisualDefault;
        }

        // [New] Draw Date 표시
        // row.winNumbers가 있는 데이터 소스(draw)에서 date를 가져와야 하는데, 
        // calculateStats에서 history 매핑 시 draw 객체 전체를 참조하지 않고 필요한 것만 뽑았다면 
        // 여기서 date를 찾기 위해 다시 allDrawData를 참조해야 할 수 있음.
        // * 효율성을 위해 calculateStats에서 date도 리턴하도록 위에서 수정하지 않았으므로 여기서 allDrawData 조회.
        // 단, stats.rows를 만들 때 이미 combinedRows에 필요한 정보를 다 넣는 것이 좋음.
        // 현재 코드 구조상 calculateStats를 수정하는 것이 정석이나, 
        // replace_file_content 범위 제한으로 인해 여기서 간이로 찾음.
        const drawData = allDrawData.find(d => d.round === row.round);
        const drawDate = drawData?.date || (row.isUpcoming ? '예정' : '-');

        // 날짜 컬럼 HTML
        const dateColumnHtml = isDateBased ? `
            <div class="text-xs font-semibold text-slate-500 text-center">${drawDate}</div>
        ` : '';

        // [Refinement] 하이라이트 스타일 가이드 적용 (보라색 테마)
        let rowClass = 'transition-none';
        let cellBaseClass = 'py-4 px-4 text-center border-l-4 border-transparent'; // Shaking Fix

        if (isInRange) {
            rowClass = 'bg-[#F3E8FF]'; // 옅은 보라색 배경
            cellBaseClass = 'py-4 px-4 text-center border-l-4 border-[#7C3AED]'; // 딥퍼플 왼쪽 선
        }

        return `
            <tr class="${rowClass} cursor-pointer group" onclick="toggleRangeHighlight(${index})">
                <td class="${cellBaseClass} text-sm font-bold text-gray-900 w-20 sticky left-0 bg-inherit z-10 whitespace-nowrap">${row.round}회</td>
                ${isDateBased ? `<td class="py-4 px-4 text-xs font-semibold text-slate-500 text-center">${drawDate}</td>` : ''}
                <td class="py-4 px-4 text-center">
                    <div class="flex gap-2 justify-center w-[300px] mx-auto">
                        ${row.winNumbers.every(n => n === 0) ? '<span class="text-slate-300 text-xs italic">추첨 대기 중...</span>' : row.winNumbers.map((num, i) => {
            const bg = getStandardBallGradient(num);
            const orbStyle = `background: ${bg}; color: white; box-shadow: 0 2px 4px rgba(0,0,0,0.12);`;
            return `
                                ${i === 6 ? '<span class="text-slate-300 self-center font-bold px-1">+</span>' : ''}
                                <div class="w-9 h-9 rounded-full flex items-center justify-center text-sm font-medium transition-transform hover:scale-110" style="${orbStyle}">${num}</div>
                            `;
        }).join('')}
                    </div>
                </td>
                <td class="py-4 px-4 text-center text-sm font-medium">${targetContent || '<span class="text-slate-200">-</span>'}</td>
                <td class="py-4 px-2">
                    <div class="flex justify-center">
                        ${row.isUpcoming ? '<span class="text-slate-300">-</span>' : `
                        <div class="text-sm font-medium ${row.hitCount > 0 ? 'text-blue-600 font-black' : 'text-slate-600'}">
                            ${row.hitCount}
                        </div>
                        `}
                    </div>
                </td>
                <td class="py-4 px-2">
                    <div class="flex justify-center">
                        ${row.isUpcoming ? '<span class="text-slate-300">-</span>' : `
                        ${row.gap === 0 ? `
                            <div class="flex items-center justify-center w-8 h-8 rounded-full bg-blue-600 text-white text-[10px] font-black shadow-sm">당</div>
                        ` : `
                            <div class="text-sm font-medium text-slate-600">${row.gap}</div>
                        `}
                        `}
                    </div>
                </td>
                <td class="py-4 px-2">
                    <div class="flex justify-center">
                        ${row.isUpcoming ? '<span class="text-slate-300">-</span>' : `
                        ${row.straight > 0 ? `
                            <div class="text-sm font-medium text-slate-600">${row.straight}</div>
                        ` : `
                            <div class="flex items-center justify-center w-8 h-8 rounded-full bg-red-500 text-white text-[10px] font-black shadow-sm">미</div>
                        `}
                        `}
                    </div>
                </td>
            </tr>
        `;
    }).join('');

    initResizableColumns();
}

/**
 * [New] 테이블 컬럼 너비 조절 기능
 */
function initResizableColumns() {
    const header = document.getElementById('historyHeader');
    if (!header) return;

    const resizers = header.querySelectorAll('.resizer');
    let startX, startWidth, colIdx;

    const onMouseMove = (e) => {
        const deltaX = e.clientX - startX;
        const newWidth = Math.max(50, startWidth + deltaX);
        document.documentElement.style.setProperty(`--col-${colIdx}-w`, `${newWidth}px`);
    };

    const onMouseUp = () => {
        document.body.classList.remove('resizing');
        document.removeEventListener('mousemove', onMouseMove);
        document.removeEventListener('mouseup', onMouseUp);
    };

    resizers.forEach(resizer => {
        resizer.onmousedown = (e) => {
            e.preventDefault();
            startX = e.clientX;
            colIdx = resizer.getAttribute('data-col');
            const colElement = resizer.parentElement;
            startWidth = colElement.offsetWidth;

            document.body.classList.add('resizing');
            document.addEventListener('mousemove', onMouseMove);
            document.addEventListener('mouseup', onMouseUp);
        };
    });
}

// [New] 통계 모달 관련 함수
let statsRange = 100;
let statsGapMap = null; // Gap 데이터를 캐싱하여 렌더링 성능 최적화

window.openStatsModal = function () {
    const modal = document.getElementById('statsModal');
    if (!modal) return;

    // 슬라이더 최대값 설정
    const slider = document.getElementById('statsRangeSlider');
    if (slider) slider.max = allDrawData.length || 1200;

    // 분석 범위 내의 모든 데이터를 기반으로 Gap(미출현) 계산 (가장 오래된 데이터부터 순방향)
    const targets = (currentAnalysis.target_numbers || []).sort((a, b) => a - b);
    statsGapMap = new Map();
    const currentGaps = {};
    targets.forEach(t => currentGaps[t] = 0);

    // 가장 과거 회차부터 현재 회차까지 순회하며 누적 Gap 계산
    for (let i = allDrawData.length - 1; i >= 0; i--) {
        const draw = allDrawData[i];
        const drawNums = (draw.numbers || []).map(Number);
        const roundGaps = {};
        targets.forEach(t => {
            const numT = Number(t);
            if (drawNums.includes(numT)) {
                currentGaps[t] = 0; // 출현 시 초기화
            } else {
                currentGaps[t]++; // 미출현 시 누적
            }
            roundGaps[t] = currentGaps[t];
        });
        statsGapMap.set(draw.round, roundGaps);
    }

    modal.classList.remove('hidden');
    renderStatsTable();
};

window.closeStatsModal = function () {
    const modal = document.getElementById('statsModal');
    if (modal) modal.classList.add('hidden');
};

window.updateStatsRange = function (val) {
    statsRange = parseInt(val);
    const display = document.getElementById('statsRangeText');
    if (display) display.innerText = `최근 ${statsRange}회 분석`;
    renderStatsTable();
};

function renderStatsTable() {
    const headerRow = document.getElementById('statsTableHeader');
    const tbody = document.getElementById('statsTableBody');
    if (!headerRow || !tbody || !statsGapMap) return;

    const targets = (currentAnalysis.target_numbers || []).sort((a, b) => a - b);
    const targetNums = targets.map(Number);
    const data = allDrawData.slice(0, statsRange);

    // 1. 헤더 렌더링
    let headerHtml = `
        <th class="sticky left-0 z-30 bg-white border-r border-slate-100 px-4 py-4 text-xs font-black text-gray-700 uppercase tracking-widest min-w-[100px] text-center">회차</th>
        <th class="px-4 py-4 text-xs font-black text-gray-700 uppercase tracking-widest min-w-[80px] border-r border-slate-100 text-center">HIT</th>
    `;
    targets.forEach(num => {
        // [Mod] 번호대별 색상 제거 -> 다크그레이(text-gray-700) 처리
        headerHtml += `<th class="px-3 py-4 text-xs font-black text-gray-700 uppercase tracking-widest min-w-[60px] text-center">${num}</th>`;
    });
    headerRow.innerHTML = headerHtml;

    // 2. 바디 렌더링
    tbody.innerHTML = data.map((draw, index) => {
        const drawNums = (draw.numbers || []).map(Number);
        const matchedCount = drawNums.filter(n => targetNums.includes(n)).length;
        const roundGaps = statsGapMap.get(draw.round) || {};

        // [New] 연속 당첨 여부 확인 (현재 회차 당첨 AND 직전 회차 당첨)
        let isConsecutive = false;
        if (matchedCount > 0) {
            // allDrawData는 내림차순 정렬되어 있으므로, index + 1이 직전 회차 데이터임
            const prevDraw = allDrawData[index + 1];
            if (prevDraw) {
                const prevDrawNums = (prevDraw.numbers || []).map(Number);
                const prevMatched = prevDrawNums.filter(n => targetNums.includes(n)).length;
                if (prevMatched > 0) isConsecutive = true;
            }
        }

        const hitColorClass = matchedCount === 0 ? 'text-gray-300' : (isConsecutive ? 'text-red-600' : 'text-blue-600');

        let cellsHtml = `
            <td class="sticky left-0 z-10 bg-white border-r border-slate-50 px-4 py-3 text-sm font-black text-gray-800 border-b border-slate-50 text-center">${draw.round}회</td>
            <td class="px-4 py-3 text-center border-r border-slate-50 border-b border-slate-50">
                <span class="text-sm font-black ${hitColorClass}">
                    ${matchedCount}
                </span>
            </td>
        `;

        targets.forEach(num => {
            const isHit = drawNums.includes(Number(num));
            // [Mod] 당첨(isHit)일 때만 파란색 원형, 나머지는 회색 숫자
            const gapValue = roundGaps[num] || 0;

            // 당첨: 파란색 배경 + 흰글씨 + '당'
            // 미당첨: 투명 배경 + 진한 회색 글씨 + Gap 숫자
            const cellContent = isHit
                ? `<span class="w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-black bg-blue-600 text-white shadow-md scale-110">당</span>`
                : `<span class="text-xs font-bold text-gray-500">${gapValue}</span>`;

            cellsHtml += `
                <td class="px-3 py-3 text-center border-b border-slate-50">
                    <div class="flex items-center justify-center">
                        ${cellContent}
                    </div>
                </td>
            `;
        });

        return `<tr>${cellsHtml}</tr>`;
    }).join('');
}

// 저장 로직
window.saveManual = async function () {
    const { error } = await window.supabaseClient.from('ai_custom_analyses').update({ target_numbers: currentAnalysis.target_numbers }).eq('id', currentAnalysis.id);
    if (error) return alert("저장 실패");

    // [New] 매뉴얼 모드 - 특정 회차 히스토리에도 저장
    const latestRound = allDrawData[0]?.round || 0;
    const targetRound = latestRound + 1;
    await window.supabaseClient.from('analysis_history').upsert({
        analysis_id: currentAnalysis.id,
        target_round: targetRound,
        target_numbers: currentAnalysis.target_numbers
    }, { onConflict: 'analysis_id, target_round' });

    showToast(`${targetRound}회차 설정이 저장되었습니다.`);
    // [추가] 대시보드 갱신 알림
    localStorage.setItem('custom_analysis_refresh', Date.now());
    updateAnalysisDisplay();
};

window.clearManual = () => {
    currentAnalysis.target_numbers = [];
    updateAnalysisDisplay();
    renderTypeSpecificControls();
};

async function saveFilterConfig() {
    await window.supabaseClient.from('ai_custom_analyses').update({ filter_config: currentAnalysis.filter_config }).eq('id', currentAnalysis.id);
    showToast("필터가 적용되었습니다.");
}

// [New] 히스토리 편집 모드 진입
window.enterEditMode = function (round) {
    editingRound = round;
    renderHistoryTable(calculateStats(currentAnalysis, allDrawData));
};

// [New] 히스토리 개별 타겟 저장
window.saveHistoryTarget = async function (round, value, isBlur = false) {
    if (!currentAnalysis) return;

    // "1, 2, 3" -> [1, 2, 3]
    const nums = value.split(/[\s,]+/).map(n => parseInt(n.trim())).filter(n => !isNaN(n) && n >= 1 && n <= 45);
    const sortedNums = [...new Set(nums)].sort((a, b) => a - b);

    // blur 시 값이 변경되지 않았다면 그냥 종료
    if (isBlur) {
        const existing = (currentAnalysis.history_data || []).find(h => h.target_round === round);
        const existingNums = (existing?.target_numbers || []).join(',');
        if (existingNums === sortedNums.join(',')) {
            editingRound = null;
            updateAnalysisDisplay();
            return;
        }
    }

    try {
        // userId 확보 시도 (여러 경로)
        let userId = window.filterService?.userId;
        if (!userId) {
            const { data: { user } } = await window.supabaseClient.auth.getUser();
            userId = user?.id;
        }

        const { error } = await window.supabaseClient.from('analysis_history').upsert({
            user_id: userId,
            analysis_id: currentAnalysis.id,
            target_round: round,
            target_numbers: sortedNums,
            analysis_type: 'manual' // [수정] 수동 편집 표시 → autoSync에서 보호됨
        }, {
            onConflict: 'analysis_id,target_round' // 중복 발생 시 해당 키를 기준으로 업데이트
        });
        // onConflict 옵션 제거하여 기본 프라이머리 키/유니크 인덱스 활용 (PostgREST 기본동작)

        if (error) throw error;

        // 로컬 데이터 갱신 (analysis_type: 'manual' 표시로 autoSync 보호)
        const idx = currentAnalysis.history_data.findIndex(h => h.target_round === round);
        if (idx >= 0) {
            currentAnalysis.history_data[idx].target_numbers = sortedNums;
            currentAnalysis.history_data[idx].analysis_type = 'manual';
        } else {
            currentAnalysis.history_data.push({ target_round: round, target_numbers: sortedNums, analysis_id: currentAnalysis.id, analysis_type: 'manual' });
        }

        showToast(`${round}회차 데이터가 저장되었습니다.`);
    } catch (err) {
        console.error("히스토리 저장 실패 상세:", err);
        const msg = err.message || '데이터 구조 오류';
        const detail = err.details ? ` (${err.details})` : '';
        showToast(`저장 실패: ${msg}${detail}`);
    } finally {
        editingRound = null;
        updateAnalysisDisplay(); // 전체 다시 계산 및 리스트 갱신
    }
};

function showToast(msg) {
    // 기존 토스트 제거
    const old = document.getElementById('toast-unique');
    if (old) old.remove();

    const toast = document.createElement('div');
    toast.id = 'toast-unique';
    toast.className = 'fixed bottom-12 left-1/2 -translate-x-1/2 bg-gray-800/90 backdrop-blur-sm text-white px-6 py-3 rounded-2xl shadow-2xl z-[500] animate-fade-in-up text-sm font-bold';
    toast.innerText = msg;
    document.body.appendChild(toast);
    setTimeout(() => { if (toast.parentElement) toast.remove(); }, 2500);
}

// 편집, 삭제 (UI 연동용)
window.editTitle = async () => {
    const val = prompt("새 제목:", currentAnalysis.title);
    if (val) {
        await window.supabaseClient.from('ai_custom_analyses').update({ title: val }).eq('id', currentAnalysis.id);
        currentAnalysis.title = val;
        // [추가] 대시보드 갱신 알림
        localStorage.setItem('custom_analysis_refresh', Date.now());
        renderBaseInfo();
        updateAnalysisDisplay(); // [Fix] 제목 변경 즉시 분석 갱신
    }
};

window.deleteAnalysis = async () => {
    if (confirm("삭제할까요?")) {
        await window.supabaseClient.from('ai_custom_analyses').delete().eq('id', currentAnalysis.id);
        // [추가] 삭제 알림 sentinel 설정
        localStorage.setItem('custom_analysis_refresh', Date.now());
        window.location.href = 'custom_analysis.html';
    }
};

// [New] 모드 전환 기능 (애니메이션 지원)
window.switchMode = function (mode) {
    const numView = document.getElementById('mode-number-analysis');
    const scanView = document.getElementById('mode-regression-scan');

    // 모든 컨테이너에서 active 제거
    numView?.classList.remove('active');
    scanView?.classList.remove('active');

    // 0.3초 후 display 조절 및 active 추가 (부드러운 전환)
    setTimeout(() => {
        if (mode === 'regression') {
            numView?.classList.add('hidden');
            scanView?.classList.remove('hidden');
            setTimeout(() => scanView?.classList.add('active'), 50);
            showAIFeedback("회귀 전수조사 모드로 전환했습니다. 분석을 시작합니다.");
        } else {
            scanView?.classList.add('hidden');
            numView?.classList.remove('hidden');
            setTimeout(() => numView?.classList.add('active'), 50);
            showAIFeedback("번호 분석 대시보드로 복귀했습니다.");
        }
    }, 100);
};

// [New] AI 피드백 메시지 표시
function showAIFeedback(message) {
    const container = document.getElementById('aiStatusContainer');
    const msgEl = document.getElementById('aiStatusMessage');
    const timeEl = document.getElementById('aiStatusTime');

    if (!container || !msgEl) return;

    msgEl.innerText = message;
    timeEl.innerText = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });

    container.classList.remove('hidden');
    container.classList.add('block');

    // 5초 후 페이드 아웃 (옵션)
    // setTimeout(() => container.classList.add('opacity-0'), 4000);
}

// [Refactored] AI 분석 리포트 갱신 → 커스텀 분석 전용 동적 리포트로 통합
window.refreshAIAnalysis = async function () {
    if (typeof renderCustomAnalysisInsight === 'function') {
        await renderCustomAnalysisInsight('dlInsightContainer', currentAnalysis);
    }
}

// [New] 회귀 전수조사 로직
async function runRegressionScan(limit = 200) {
    switchMode('regression');
    const tbody = document.getElementById('regression-scan-results');
    if (!tbody) return;

    tbody.innerHTML = `
        <tr>
            <td colspan="4" class="px-6 py-20 text-center">
                <div class="flex flex-col items-center gap-3">
                    <div class="w-12 h-12 border-4 border-indigo-100 border-t-indigo-600 rounded-full animate-spin"></div>
                    <p class="text-indigo-600 font-bold">1회귀 ~ ${limit}회귀 전수조사 진행 중...</p>
                    <p class="text-xs text-gray-400">직전 회차에 적중한 패턴을 찾고 있습니다.</p>
                </div>
            </td>
        </tr>
    `;

    if (!allDrawData || allDrawData.length < limit + 1) {
        tbody.innerHTML = '<tr><td colspan="4" class="px-6 py-10 text-center text-red-500">데이터가 부족합니다.</td></tr>';
        return;
    }

    const latestDraw = allDrawData[0];
    const prevDraw = allDrawData[1];
    const latestNumbers = latestDraw.numbers.map(Number);
    const results = [];

    // 2회귀부터 limit회귀까지 스캔
    for (let step = 2; step <= limit; step++) {
        // 직전 회차(1번 인덱스)에서 step만큼 뒤의 회차(1 + step - 1 = step) 번호가 타겟
        if (allDrawData.length <= step) continue;

        const targetDraw = allDrawData[step]; // 전회차(index 1) 기준 -step 회차
        const targetNumbers = targetDraw.numbers.map(Number);
        const matched = latestNumbers.filter(n => targetNumbers.includes(n));

        if (matched.length > 0) {
            results.push({
                step,
                targetNumbers,
                matched,
                hitCount: matched.length
            });
        }
    }

    results.sort((a, b) => b.hitCount - a.hitCount);

    if (results.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="px-6 py-10 text-center text-gray-500 font-medium">적중한 회귀 패턴이 없습니다.</td></tr>';
        return;
    }

    tbody.innerHTML = results.map(res => {
        const numbersHtml = res.targetNumbers.map(n => {
            const isHit = res.matched.includes(n);
            const bg = getStandardBallGradient(n);
            return `<span class="w-8 h-8 rounded-full flex items-center justify-center text-[10px] font-bold ${isHit ? 'text-white' : 'bg-white border border-slate-200 text-slate-400'}" style="${isHit ? `background:${bg}; box-shadow:0 2px 4px rgba(0,0,0,0.12)` : ''}">${n}</span>`;
        }).join('');

        return `
            <tr class="hover:bg-indigo-50/30 transition-colors group">
                <td class="px-6 py-4 whitespace-nowrap">
                    <div class="flex items-center gap-2">
                        <span class="w-8 h-8 bg-indigo-100 text-indigo-700 rounded-lg flex items-center justify-center text-sm font-black">${res.step}</span>
                        <span class="text-sm font-bold text-gray-900">회귀</span>
                    </div>
                </td>
                <td class="px-6 py-4">
                    <div class="flex gap-1 justify-center">${numbersHtml}</div>
                </td>
                <td class="px-6 py-4 text-center">
                    <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-black ${res.hitCount >= 2 ? 'bg-red-100 text-red-700' : 'bg-blue-100 text-blue-700'}">
                        ${res.hitCount}개 적중
                    </span>
                </td>
                <td class="px-6 py-4 text-right">
                    <button onclick="createRegressionAnalysis(${res.step})" class="text-indigo-600 hover:text-indigo-900 text-xs font-black flex items-center gap-1 ml-auto group-hover:translate-x-1 transition-transform">
                        연구소 등록 <span class="material-symbols-outlined text-sm">arrow_forward</span>
                    </button>
                </td>
            </tr>
        `;
    }).join('');
}

// [New] 특정 회귀를 커스텀 분석으로 등록
window.createRegressionAnalysis = async function (step) {
    const params = {
        type: 'dynamic',
        title: `${step}회귀 전수조사 분석`,
        description: `직전 회차 적중(${step}회귀) 기반 자동 분석`,
        prompt: `${step}회귀 자동 생성`,
        rules: {
            formula: 'carryover', // 타겟 회차의 번호를 변환 없이 그대로 사용
            regression_step: step
        },
        target_numbers: allDrawData[step] ? allDrawData[step].numbers.map(Number) : []
    };

    // createAnalysis는 customAnalysis.js 어딘가에 정의되어 있을 것 (handleNLPResult에서 호출함)
    if (window.createAnalysis) {
        window.createAnalysis(params);
    } else {
        alert(`${step}회귀 분석 생성을 시도합니다. (createAnalysis 함수를 찾을 수 없음)`);
    }
};

// [New] NLP 결과 처리 함수
async function handleNLPResult(params, intent) {
    // 0. 모드 전환 의도 (Switch View)
    if (intent === 'switch_view') {
        switchMode(params.target);
        window.nlpComponent?.clear();
        return;
    }

    // 1. 회귀 스캔 의도 (Regression Scan)
    if (intent === 'regression_scan') {
        runRegressionScan(params.limit || 200);
        window.nlpComponent?.clear();
        return;
    }

    // 2. 수정 의도인 경우 (Modification)
    if (intent === 'modification' && currentAnalysis) {
        if (!confirm('현재 보고 계신 분석 설정을 수정하시겠습니까?\n(취소 시 새 분석으로 생성됩니다)')) {
            window.createAnalysis(params);
            return;
        }

        try {
            const { data, error } = await window.supabaseClient
                .from('ai_custom_analyses')
                .update({
                    target_numbers: params.target_numbers || [],
                    rules: params.rules || {},
                    config: params.config || {},
                    filter_config: params.filter_config || currentAnalysis.filter_config
                })
                .eq('id', currentAnalysis.id)
                .select()
                .single();

            if (error) throw error;

            currentAnalysis = data;
            updateAnalysisDisplay();
            renderTypeSpecificControls();
            alert('분석 조건이 수정되었습니다.');
            window.nlpComponent?.clear();
            switchMode('number'); // 수정 시 숫자 분석 모드로 강제 전환

        } catch (err) {
            console.error('수정 실패:', err);
            alert('수정 중 오류가 발생했습니다.');
        }
        return;
    }

    // 3. 그 외 (새 분석 생성)
    if (window.createAnalysis) {
        // [Fix] DB 저장 오류 방지: prompt가 없으면 제목이나 기본값으로 채움
        if (!params.prompt) {
            params.prompt = params.title || "사용자 지정 조건 분석";
        }

        window.createAnalysis(params);
        switchMode('number');
    }
}

// [New] AI 응답 텍스트 포맷터
function formatAIResponse(text) {
    if (!text) return '';
    return text
        .replace(/{{range:(.*?)}}/g, '<span class="font-bold text-indigo-600 bg-indigo-50 px-1 rounded">$1</span>')
        .replace(/{{warn:(.*?)}}/g, '<span class="font-bold text-red-600 bg-red-50 px-1 rounded">$1</span>')
        .replace(/{{good:(.*?)}}/g, '<span class="font-bold text-emerald-600 bg-emerald-50 px-1 rounded">$1</span>')
        .replace(/\*\*(.*?)\*\*/g, '<strong class="font-black text-gray-900">$1</strong>')
        .replace(/\n/g, '<br>');
}
// [New] 실시간 동기화: 다른 탭(대시보드 등)에서 필터 변경 시 즉시 반영
window.addEventListener('storage', (e) => {
    if (!e.key || !currentAnalysis) return;

    // 현재 보고 있는 분석의 필터가 변경되었는지 확인
    if (e.key === `custom_filter_${currentAnalysis.id}`) {
        try {
            const newData = JSON.parse(e.newValue);
            if (newData) {
                console.log(`🔄 [Sync] 외부 변경 감지: ${e.key}`);
                currentAnalysis.filter_config = newData;
                renderFilterUI();
                updateAnalysisDisplay(true); // UI만 즉시 갱신
            }
        } catch (err) {
            console.error("데이터 동기화 파싱 오류:", err);
        }
    }
});

// ═══════════════════════════════════════════════════════════════════════════
// [New] 커스텀 분석용 AI 프리미엄 전략 리포트 (동적 · 분석별 고유)
//   - target_numbers 대해 각 모델(LSTM/XGB/CNN/TF/Markov/ATC/GNN)의
//     다음 회차 "예상 적중 개수 범위"를 matrix_data.models[*].score 기반으로 계산
//   - 최근 10회차 실제 적중으로 Min/Max 범위 보정
// ═══════════════════════════════════════════════════════════════════════════
const CUSTOM_INSIGHT_MODELS = [
    { key: 'lstm',        label: 'LSTM' },
    { key: 'xgboost',     label: 'XGBOOST' },
    { key: 'cnn',         label: 'CNN' },
    { key: 'transformer', label: 'TRANSFORMER' },
    { key: 'markov',      label: 'MARKOV' },
    { key: 'autoencoder', label: 'AUTOENCODER' },
    { key: 'gnn',         label: 'GNN' }
];

function _ciModelRange(matrixData, modelKey, targets) {
    // 모델 score 기준 내림차순 정렬 → target_numbers 가 상위 K에 몇 개 들어있는지
    if (!matrixData || !matrixData.length || !targets.length) return null;
    const tSet = new Set(targets.map(Number));
    const sorted = [...matrixData]
        .map(m => ({
            num: Number(m.num),
            score: (modelKey === 'ensemble' || modelKey === 'total')
                ? (m.total || 0)
                : ((m.models && m.models[modelKey]) ? (m.models[modelKey].score || 0) : 0)
        }))
        .sort((a, b) => b.score - a.score);

    // 다음 회차 추첨 번호 6개를 모델이 상위 6으로 예측한다고 가정
    const top6 = sorted.slice(0, 6).map(x => x.num);
    const expectedHit = top6.filter(n => tSet.has(n)).length;

    // target 들의 평균 랭크로 신뢰도 산정 (랭크 상위일수록 기대 적중↑)
    const rankMap = new Map(sorted.map((x, i) => [x.num, i + 1]));
    const ranks = targets.map(n => rankMap.get(Number(n))).filter(Boolean);
    const avgRank = ranks.length ? (ranks.reduce((a, b) => a + b, 0) / ranks.length) : 45;

    // Min/Max: expectedHit 중심 ±1 (0~6 클램핑). 평균 랭크가 좋을수록(낮을수록) Max+1
    let min = Math.max(0, expectedHit - 1);
    let max = Math.min(6, expectedHit + 1);
    if (avgRank <= 15) max = Math.min(6, max + 1);
    if (avgRank >= 35) min = Math.max(0, min - 1);

    return { min, max, expectedHit, avgRank: Math.round(avgRank) };
}

function _ciEnsembleFromModels(modelRanges) {
    const mins = [], maxs = [];
    Object.values(modelRanges).forEach(r => { if (r) { mins.push(r.min); maxs.push(r.max); } });
    if (!mins.length) return { cMin: 0, cMax: 0, agreement: 0 };
    const cMin = Math.round(mins.reduce((a, b) => a + b, 0) / mins.length);
    const cMax = Math.round(maxs.reduce((a, b) => a + b, 0) / maxs.length);
    // 합의도: 모델 간 min/max 분산이 작을수록 높음
    const spread = (Math.max(...maxs) - Math.min(...mins));
    const agreement = Math.max(0, Math.min(100, 100 - spread * 15));
    return { cMin, cMax, agreement: Math.round(agreement) };
}

function _ciRecentHitStats(analysis, allDrawData) {
    try {
        const stats = calculateStats(analysis, allDrawData);
        if (!stats || !stats.rows) return null;
        const rows = stats.rows.filter(r => !r.isUpcoming).slice(0, 10);
        if (!rows.length) return null;
        const hits = rows.map(r => r.hitCount || 0);
        const avg = (hits.reduce((a, b) => a + b, 0) / hits.length);
        return { avg: avg.toFixed(1), min: Math.min(...hits), max: Math.max(...hits), n: rows.length, recentHits: hits };
    } catch (e) { return null; }
}

function _ciBuildHTML(analysis, targetRound, modelRanges, ensemble, recentStats) {
    const title = analysis.title || '커스텀 분석';
    const cardsHTML = CUSTOM_INSIGHT_MODELS.map(m => {
        const r = modelRanges[m.key];
        const val = r ? `${r.min}~${r.max}` : '-';
        return `
        <div style="background:white; border:1px solid #e2e8f0; border-radius:12px; padding:14px 10px; text-align:center; transition:all .2s;">
            <div style="font-size:0.7rem; color:#64748b; font-weight:800; letter-spacing:0.5px; margin-bottom:6px;">${m.label}</div>
            <div style="font-size:1.1rem; color:#1e293b; font-weight:500; letter-spacing:-0.3px;">${val}</div>
        </div>`;
    }).join('');

    const avgRecent = recentStats ? recentStats.avg : '-';
    const recentMin = recentStats ? recentStats.min : '-';
    const recentMax = recentStats ? recentStats.max : '-';

    // 흐름 진단
    const flowText = recentStats
        ? `최근 ${recentStats.n}회차 "${title}" 대상 평균 적중은 <strong style="color:#2563eb">${avgRecent}개</strong>이며, 현재 AI 앙상블 예측 범위 <strong style="color:#2563eb">${ensemble.cMin}~${ensemble.cMax}개</strong>로 나타나 최근 실측(${recentMin}~${recentMax})과 ${Math.abs(parseFloat(avgRecent) - (ensemble.cMin + ensemble.cMax)/2) < 1 ? '<strong style="color:#16a34a">정합</strong>' : '<strong style="color:#ea580c">편차</strong>'} 흐름을 보입니다.`
        : 'AI 모델 예측과 최근 적중 데이터를 종합하여 흐름을 진단 중입니다.';

    // 패턴 분석
    const maxModel = Object.entries(modelRanges).sort((a, b) => ((b[1]?.max || 0) - (a[1]?.max || 0)))[0];
    const minModel = Object.entries(modelRanges).sort((a, b) => ((a[1]?.min || 9) - (b[1]?.min || 9)))[0];
    const maxLabel = maxModel ? (CUSTOM_INSIGHT_MODELS.find(m => m.key === maxModel[0])?.label || maxModel[0]) : '-';
    const minLabel = minModel ? (CUSTOM_INSIGHT_MODELS.find(m => m.key === minModel[0])?.label || minModel[0]) : '-';
    const patternText = `모델 합의도 <strong style="color:#2563eb">${ensemble.agreement}%</strong>. 최고 낙관 모델은 <strong>${maxLabel}</strong>(최대 ${maxModel?.[1]?.max ?? '-'}개), 최저 비관 모델은 <strong>${minLabel}</strong>(최소 ${minModel?.[1]?.min ?? '-'}개)로 나타나 ${ensemble.agreement >= 70 ? '모델 간 견해가 <strong style="color:#16a34a">수렴</strong>' : '모델 간 견해가 <strong style="color:#ea580c">발산</strong>'}하고 있습니다.`;

    // 필승 공략
    const strategyText = `${targetRound}회차 "${title}" 공략: AI 앙상블 예측 <strong style="color:#38bdf8">${ensemble.cMin}~${ensemble.cMax}개</strong>를 기준으로 <strong style="color:#38bdf8">Min=${ensemble.cMin}, Max=${ensemble.cMax}</strong>의 조합 필터 적용을 권장합니다. 최근 10회 평균 ${avgRecent}개를 고려하여 ${recentMax}개 이상의 초과 적중 조합은 제외 전략을 병행하십시오.`;

    return `
    <div style="background:white; border-radius:24px; border:1px solid #e2e8f0; overflow:hidden; box-shadow:0 4px 16px rgba(15,23,42,0.04);">
        <!-- Header -->
        <div style="background:#0f172a; padding:1.25rem 2rem; display:flex; align-items:center; gap:14px;">
            <div style="width:40px; height:40px; background:#1e293b; border-radius:12px; display:flex; align-items:center; justify-content:center;">
                <span class="material-symbols-outlined" style="font-size:22px; color:#38bdf8;">insights</span>
            </div>
            <div>
                <div style="font-size:1.05rem; font-weight:900; color:white; letter-spacing:-0.3px;">AI 프리미엄 전략 리포트</div>
                <div style="font-size:0.68rem; color:#94a3b8; font-weight:700; letter-spacing:2px; text-transform:uppercase; margin-top:2px;">INTELLIGENT ANALYSIS — ${title}</div>
            </div>
        </div>

        <!-- Ensemble Summary -->
        <div style="background:#f8fafc; border-bottom:1px solid #f1f5f9; padding:1.5rem 2rem;">
            <div style="display:flex; align-items:center; justify-content:space-between; gap:2rem; flex-wrap:wrap;">
                <div>
                    <span style="font-size:0.7rem; color:#64748b; font-weight:800; letter-spacing:1px; text-transform:uppercase; margin-bottom:6px; display:block;">AI 종합 예상 적중 범위</span>
                    <div style="display:flex; align-items:baseline; gap:12px;">
                        <span style="font-size:2.2rem; font-weight:900; color:#2563eb; letter-spacing:-1px;">${ensemble.cMin} ~ ${ensemble.cMax}</span>
                        <span style="font-size:0.85rem; color:#2563eb; font-weight:800; background:#dbeafe; padding:4px 10px; border-radius:8px; border:1px solid #bfdbfe;">평균 ${((ensemble.cMin + ensemble.cMax) / 2).toFixed(1)}개</span>
                    </div>
                </div>
                <div style="width:240px; background:white; padding:12px; border-radius:16px; border:1px solid #e2e8f0;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                        <span style="font-size:0.68rem; color:#64748b; font-weight:800;">모델 합의도</span>
                        <span style="font-size:0.85rem; color:#1e293b; font-weight:900;">${ensemble.agreement}%</span>
                    </div>
                    <div style="height:10px; background:#f1f5f9; border-radius:5px; overflow:hidden;">
                        <div style="width:${ensemble.agreement}%; height:100%; background:linear-gradient(90deg,#38bdf8,#2563eb);"></div>
                    </div>
                    <div style="font-size:0.62rem; color:#94a3b8; font-weight:700; text-align:right; margin-top:6px;">7개 딥러닝 모델 교차 검증</div>
                </div>
            </div>
        </div>

        <!-- Model Cards -->
        <div style="display:grid; grid-template-columns:repeat(7, 1fr); gap:10px; padding:1.25rem 2rem; background:#f8fafc;">
            ${cardsHTML}
        </div>

        <!-- Body -->
        <div style="padding:1.75rem 2rem;">
            <div style="margin-bottom:1.5rem;">
                <div style="display:flex; align-items:center; gap:8px; margin-bottom:10px;">
                    <span style="width:4px; height:16px; background:#2563eb; border-radius:2px;"></span>
                    <span style="font-size:0.95rem; font-weight:900; color:#0f172a; letter-spacing:-0.3px;">흐름 진단</span>
                </div>
                <div style="font-size:0.92rem; line-height:1.8; color:#334155; word-break:keep-all;">${flowText}</div>
            </div>
            <div style="border-top:1px solid #f1f5f9; padding-top:1.5rem;">
                <div style="display:flex; align-items:center; gap:8px; margin-bottom:10px;">
                    <span style="width:4px; height:16px; background:#8b5cf6; border-radius:2px;"></span>
                    <span style="font-size:0.95rem; font-weight:900; color:#0f172a; letter-spacing:-0.3px;">패턴 분석</span>
                </div>
                <div style="font-size:0.92rem; line-height:1.8; color:#334155; word-break:keep-all;">${patternText}</div>
            </div>
        </div>

        <!-- Winning Strategy -->
        <div style="background:#0f172a; padding:1.75rem 2rem; color:white;">
            <div style="display:flex; align-items:center; gap:10px; margin-bottom:12px;">
                <span class="material-symbols-outlined" style="font-size:20px; color:#38bdf8;">verified</span>
                <span style="font-size:1rem; font-weight:900; color:#38bdf8; letter-spacing:-0.3px;">${targetRound}회차 필승 공략</span>
            </div>
            <div style="font-size:0.93rem; line-height:1.85; color:rgba(255,255,255,0.9); font-weight:400; word-break:keep-all;">${strategyText}</div>
        </div>
    </div>`;
}

function _ciSkeleton() {
    return `<div style="background:white; border-radius:24px; border:1px solid #e2e8f0; padding:3rem; text-align:center; color:#94a3b8;">
        <div style="display:inline-flex; align-items:center; gap:12px;">
            <div style="width:18px; height:18px; border:3px solid #2563eb; border-top-color:transparent; border-radius:50%; animation:ciSpin 1s linear infinite;"></div>
            <span style="font-size:0.9rem; font-weight:700; color:#475569;">AI 프리미엄 전략 리포트 생성 중...</span>
        </div>
        <style>@keyframes ciSpin{to{transform:rotate(360deg)}}</style>
    </div>`;
}

async function renderCustomAnalysisInsight(containerId, analysis) {
    const el = document.getElementById(containerId);
    if (!el) return;

    // [중요] 예전 디자인(DeepInsightPanel 등)이 남아있지 않도록 먼저 완전 초기화
    el.innerHTML = _ciSkeleton();

    if (!analysis || !allDrawData || !allDrawData.length) {
        el.innerHTML = '';
        return;
    }

    const targets = (analysis.target_numbers || []).map(Number).filter(n => n >= 1 && n <= 45);
    if (targets.length === 0) {
        el.innerHTML = `<div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:16px; padding:2rem; text-align:center; color:#64748b; font-size:0.9rem;">대상 번호가 없어 AI 프리미엄 전략 리포트를 생성할 수 없습니다.</div>`;
        return;
    }

    const latestRound = allDrawData[0].round;
    const targetRound = latestRound + 1;

    // matrix_data 로드 (이미 ensureAIHistoryLoaded 에서 캐시됨)
    try {
        if (typeof ensureAIHistoryLoaded === 'function') {
            await ensureAIHistoryLoaded([targetRound]);
        }
    } catch (e) { /* noop */ }

    const aiData = (typeof aiCache !== 'undefined' && aiCache.get) ? aiCache.get(targetRound) : null;
    const matrixData = aiData?.matrix_data || [];

    if (!matrixData.length) {
        el.innerHTML = `<div style="background:#fef2f2; border:1px solid #fecaca; border-radius:16px; padding:2rem; text-align:center; color:#991b1b; font-size:0.9rem; font-weight:700;">
            ${targetRound}회차 딥러닝 예측 데이터(matrix_data)가 아직 준비되지 않았습니다.
            <div style="font-size:0.8rem; color:#7f1d1d; font-weight:500; margin-top:8px;">회차 업데이트 후 자동 생성됩니다.</div>
        </div>`;
        return;
    }

    // 모델별 예측 범위 계산
    const modelRanges = {};
    CUSTOM_INSIGHT_MODELS.forEach(m => {
        modelRanges[m.key] = _ciModelRange(matrixData, m.key, targets);
    });
    const ensemble = _ciEnsembleFromModels(modelRanges);
    const recentStats = _ciRecentHitStats(analysis, allDrawData);

    el.innerHTML = _ciBuildHTML(analysis, targetRound, modelRanges, ensemble, recentStats);
}

window.renderCustomAnalysisInsight = renderCustomAnalysisInsight;


// [추가] 커스텀 분석 페이지에서 조합 필터 페이지의 해당 항목으로 이동하는 함수
window.goToFilterPage = function () {
    if (!currentAnalysis || !currentAnalysis.id) {
        window.location.href = 'filter.html?tab=custom';
        return;
    }
    // 딥링크 파라미터 (id)를 포함하여 이동 → filter_dashboard.js의 handleDeepLink에서 하이라이트 처리됨
    window.location.href = `filter.html?tab=custom&id=${currentAnalysis.id}`;
};
