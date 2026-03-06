let currentAnalysis = null;
let allDrawData = [];
let referenceRound = 0; // 기준 회차 (0=최신)
let historyViewLimit = 100; // [New] 히스토리 조회 제한 (기본 100)

const aiCache = new Map(); // [New] AI 예측 데이터 캐시

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
 * [New] 필터 바로가기: filter.html의 해당 커스텀 필터로 이동
 */
window.goToFilterPage = function () {
    if (!currentAnalysis?.id) return;
    const tab = 'custom';
    window.location.href = `filter.html?tab=${tab}&id=${currentAnalysis.id}`;
};

document.addEventListener('DOMContentLoaded', async () => {
    const params = new URLSearchParams(window.location.search);
    let analysisId = params.get('id');

    if (!analysisId) {
        // Redirect to the most recent analysis if no ID provided
        const { data } = await window.supabaseClient.from('ai_custom_analyses').select('id').order('created_at', { ascending: false }).limit(1).single();
        if (data?.id) return window.location.replace(`custom_analysis.html?id=${data.id}`);
        // No analysis found at all
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

        // 1. 데이터 로드 (분석 설정 + 전체 회차)
        const [analysisRes, drawsRes] = await Promise.all([
            window.supabaseClient.from('ai_custom_analyses').select('*').eq('id', analysisId).single(),
            window.supabaseClient.from('lotto_draws')
                .select('*')
                .order('round', { ascending: false })
                .range(0, 5000) // 👈 전체 데이터 로딩 (필수)
        ]);

        if (analysisRes.error || !analysisRes.data) throw new Error("분석 로드 실패");
        currentAnalysis = analysisRes.data;
        allDrawData = drawsRes.data || [];

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

        // 3. 초기 렌더링 (로드 시에는 AI 자동 분석 방지)
        renderBaseInfo();
        await updateAnalysisDisplay();

        // 4. 유형별 전용 컨트롤 로드
        renderTypeSpecificControls();

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

    console.log(`📡 [AI History] ${toFetch.length}개 회차의 AI 데이터 로딩 중... (Rounds: ${toFetch.join(', ')})`);

    // API 부하 방지 및 속도 향상을 위해 Promise.all로 병렬 처리
    await Promise.all(toFetch.map(async (round) => {
        try {
            const data = await window.AIProxy.getPredictions(round);
            if (data) {
                // [FIX] 만약 데이터가 { success: true, data: { ... } } 형태로 래핑되어 있다면 언래핑
                const aiResult = (data.success && data.data) ? data.data : data;
                aiCache.set(round, aiResult);
                console.log(`✅ [AI History] ${round}회차 로드 완료:`, aiResult);
            } else {
                console.warn(`⚠️ [AI History] ${round}회차 데이터 없음`);
                aiCache.set(round, null); // 중복 요청 방지를 위해 null이라도 캐시
            }
        } catch (e) {
            console.error(`${round}회차 AI 데이터 로드 실패:`, e);
        }
    }));
}

function calculateStats(analysis, draws) {
    if (!analysis || !draws.length) return null;

    const type = analysis.type || 'static';
    const title = analysis.title || '';
    const globalTargets = analysis.target_numbers || [];

    // AI 관련 타입 여부 확인
    const isAiType = type.startsWith('ai_');

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

    // [New] 분석 생성일(created_at) 기준 필터링 로직 추가
    // 사용자의 요청에 따라 '분석 페이지 생성 후 부터' 계산하도록 함.
    const createdAt = analysis.created_at ? new Date(analysis.created_at) : null;
    let filteredAscDraws = ascDraws;

    if (createdAt && (type === 'manual' || type === 'direct')) {
        // 생성일보다 늦게 추첨된 회차(date 기반) 혹은 생성 시점의 최신 회차를 찾아 필터링
        // allDrawData는 DESC(최신순)이므로 ascDraws(과거순)에서 찾음
        filteredAscDraws = ascDraws.filter(draw => {
            const drawDate = new Date(draw.date);
            // 추첨일이 생성일 이후이거나, 추첨일 정보가 없으면 생성 시점 최신 회차 판단 로직 필요
            // 여기서는 안전하게 '추첨일 >= 생성일' 기준으로 필터링 (시간 정보 포함)
            return drawDate >= createdAt;
        });

        // 만약 필터링 결과가 너무 적다면(방금 생성한 경우), 
        // 최소한 생성 시점의 최신 회차 1개는 포함하거나 혹은 빈 상태로 둠.
        // 현재 로직은 생성 이후 실적만 수집함.
    }

    const history = filteredAscDraws.map((draw, idx) => {
        let targets = [];

        // [유형별 타겟 결정]
        if (type === 'manual' || type === 'direct') {
            const hist = (analysis.history_data || []).find(h => h.target_round === draw.round);
            targets = (hist?.target_numbers || []).map(Number);
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
            // [Fix] 그룹 숫자가 문자열로 저장되어 있을 수 있으므로 숫자로 변환하여 타겟 추출
            targets = [...new Set(groups.flatMap(g => (g.numbers || []).map(Number)))].sort((a, b) => a - b);
        } else if (isAiType) {
            // [New] AI 분석 유형 처리
            const aiData = aiCache.get(draw.round);
            if (aiData) {
                if (type === 'ai_ensemble_fixed') {
                    targets = (aiData.top_5 || aiData.recommended || []).slice(0, 6).map(Number);
                } else if (type === 'ai_ensemble_excluded') {
                    targets = (aiData.exclude_10 || aiData.excluded || []).map(Number);
                } else if (type === 'ai_model_top' || type === 'ai_model_bottom') {
                    const model = (analysis.rules?.model || 'ensemble').toLowerCase();
                    const count = parseInt(analysis.rules?.count || 10);
                    const isTop = (type === 'ai_model_top');

                    const matrixData = aiData.matrix_data || [];
                    if (matrixData.length > 0) {
                        const sorted = [...matrixData].sort((a, b) => {
                            let scoreA, scoreB;
                            if (model === 'ensemble' || model === 'total') {
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
            }
        }

        const drawNums = (draw.numbers || []).map(Number);
        const matched = drawNums.filter(n => targets.includes(n));
        const hitCount = matched.length;

        // [Standardized] 적중 여부 판단
        // matched와 hitCount는 위에서 이미 선언됨

        // 기본 hit 여부: 1개 이상이면 Hit (필터 미적용 시 기본값)
        let isHit = hitCount > 0;

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
        // [FIXED] Next round ALWAYS uses the current targets being actively edited,
        // no historical carry-over dependency for the upcoming predictions to allow live UI updates.
        nextTargets = [...globalTargets].sort((a, b) => a - b);
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
        nextTargets = [...new Set(groups.flatMap(g => g.numbers))].sort((a, b) => a - b);
    } else if (isAiType) {
        // [New] 다음 회차 AI 예측 데이터 로드 (캐싱된게 있으면 사용, 없으면 빈 배열)
        const aiData = aiCache.get(nextRound);
        if (aiData) {
            if (type === 'ai_ensemble_fixed') {
                nextTargets = (aiData.top_5 || aiData.recommended || []).slice(0, 6);
            } else if (type === 'ai_ensemble_excluded') {
                nextTargets = aiData.exclude_10 || aiData.excluded || [];
            } else if (type === 'ai_model_top' || type === 'ai_model_bottom') {
                const model = (analysis.rules?.model || 'ensemble').toLowerCase();
                const count = parseInt(analysis.rules?.count || 10);
                const isTop = (type === 'ai_model_top');
                const matrixData = aiData.matrix_data || [];
                if (matrixData.length > 0) {
                    const sorted = [...matrixData].sort((a, b) => {
                        let scoreA, scoreB;
                        if (model === 'ensemble' || model === 'total') {
                            scoreA = a.total || 0;
                            scoreB = b.total || 0;
                        } else {
                            scoreA = (a.models && a.models[model]) ? (a.models[model].score || 0) : 0;
                            scoreB = (b.models && b.models[model]) ? (b.models[model].score || 0) : 0;
                        }
                        return isTop ? (scoreB - scoreA) : (scoreA - scoreB);
                    });
                    nextTargets = sorted.slice(0, count).map(item => item.num);
                }
            }
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
    const sortedHistory = [...history].reverse(); // history가 ASC이므로 뒤집어서 DESC로 만듦
    const combinedRows = [nextRow, ...sortedHistory];

    return {
        rows: combinedRows.slice(0, historyViewLimit), // [Mod] 동적 제한 적용
        currentGap: history[history.length - 1]?.gap || 0,
        currentStraight: history[history.length - 1]?.straight || 0,
        maxGap, maxStraight, maxHits,
        hitRate: (hitRounds / history.length) * 100,
        avgHits: totalHitCount / history.length
    };
}

// [Mod] skipAI 파라미터 추가 - 리스트 클릭 시 자동 분석 방지
async function updateAnalysisDisplay(skipAI = false) {
    const type = currentAnalysis?.type || 'static';

    // [New] AI 분석 유형일 경우 과거 데이터 로딩
    if (type.startsWith('ai_')) {
        // AI 분석은 과거 데이터가 많을수록 로딩이 매우 느려지므로 초기 로딩은 20회차로 제한
        const aiHistoryLimit = 20;
        const roundsToLoad = allDrawData.slice(0, Math.min(historyViewLimit, aiHistoryLimit)).map(d => d.round);
        const latestRound = allDrawData[0]?.round || 0;
        roundsToLoad.push(latestRound + 1); // 다음 회차 포함

        await ensureAIHistoryLoaded(roundsToLoad);
    }

    const stats = calculateStats(currentAnalysis, allDrawData);
    if (!stats) return;

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
        targets = (currentAnalysis.target_numbers || []).sort((a, b) => a - b);
    }

    const html = targets.length === 0 ?
        '<span class="text-sm text-gray-400">선택된 번호가 없습니다.</span>' :
        targets.map(num => {
            const color = window.Utils?.getBallColor(num) || '#6B7280';
            return `<div class="w-8 h-8 rounded-full flex items-center justify-center text-white font-bold text-sm shadow-sm" style="background-color: ${color}">${num}</div>`;
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
                    <div id="numberGrid" class="grid grid-rows-2 grid-flow-col gap-1.5 min-w-max"></div>
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
        const color = window.Utils?.getBallColor(i) || '#64748b';

        // 클래스 및 스타일만 조절
        btn.className = `w-9 h-9 rounded-full flex items-center justify-center text-xs font-bold border transition-all ${active ? 'text-white border-transparent scale-105 shadow-md' : 'bg-white border-slate-100 text-slate-300 hover:border-indigo-100 hover:text-indigo-400'
            }`;
        btn.style.backgroundColor = active ? color : 'white';
        btn.innerText = i;
    }
}

// Zone E: 필터
function renderFilterUI() {
    const config = currentAnalysis.filter_config || { min: 1, max: 3, enabled: false };
    const stats = calculateStats(currentAnalysis, allDrawData);

    // [Auto-Calibration Logic]
    // 최초 로드 시(혹은 설정이 없을 때), 최근 10회차 실적을 기반으로 필터 범위를 자동 제안하되,
    // 사용자가 '직접' 끈 경우(enabled=false)에는 강제로 켜지 않도록 주의해야 함.
    // 하지만 "Fibonacci" 같은 분석은 기본적으로 켜져있길 원할 수도 있음.
    // 여기서는 "DB에 저장된 config"가 우선이며, 만약 config가 초기값(min:1, max:3, enabled:false)일 때만 자동 보정을 수행합니다.

    // Check if it's default config
    const isDefaultConfig = (config.min === 1 && config.max === 3 && config.enabled === false);

    if (isDefaultConfig && stats && stats.rows.length > 0) {
        const last10 = stats.rows.slice(0, 10);
        const hits = last10.map(r => r.hitCount);
        const minHit = Math.min(...hits);
        const maxHit = Math.max(...hits);

        // 자동 보정 적용 (범위만 업데이트하고, 활성화는 끄기 상태 유지 - 사용자가 켤 때 적용되도록)
        // config.min = minHit;
        // config.max = maxHit;
        // NOTE: 사용자가 혼란스러워할 수 있으므로, 자동 보정은 "제안"만 하고 값은 건드리지 않거나,
        // 아니면 값을 바꾸되 enabled는 false로 둠.

        // 사용자 요청: "파보나치 수열 분석은 기본이 적용..." -> 즉, 유의미한 패턴이 있으면 켜주고 싶음.
        // 하지만 "다시 끄고 새로고침하면 다시 적용" 되는 문제는 DB 저장이 안되어서 발생함.
        // 따라서 DB 저장을 확실히 하고, 여기선 UI 렌더링에 집중.
    }

    const rangeDisplay = document.getElementById('filterRangeDisplay');
    if (rangeDisplay) {
        let label = '';
        if (config.values && config.values.length > 0) {
            label = config.values.join(', ') + '개';
        } else {
            label = `${config.min} ~ ${config.max}개`;
        }

        if (stats && stats.rows.length > 0) {
            const last10 = stats.rows.slice(1, 11); // Next Round 제외한 최근 10회
            const hits = last10.map(r => r.hitCount);
            const minHit = Math.min(...hits);
            const maxHit = Math.max(...hits);

            rangeDisplay.innerHTML = `${label} <span class="text-[10px] text-gray-400 ml-2">(최근 10회 실적: ${minHit}~${maxHit})</span>`;
        } else {
            rangeDisplay.innerHTML = label;
        }
    }

    const toggle = document.getElementById('filterToggle');
    if (toggle) {
        toggle.checked = config.enabled;
        // 이벤트 핸들러가 HTML에 inline으로 박혀있으므로 (onchange="saveCustomFilter()")
        // 여기서 별도 addEventListener는 안 해도 됨. 단 함수가 전역에 있어야 함.
    }

    const btnContainer = document.getElementById('filterBtnContainer');
    if (btnContainer) {
        btnContainer.innerHTML = '';
        const limit = 6;
        for (let i = 0; i <= limit; i++) {
            // active 여부 결정 (values 배열 기준 또는 min~max 범위 기준)
            let active = false;
            if (config.values && config.values.length > 0) {
                active = config.values.includes(i);
            } else {
                active = (i >= config.min && i <= config.max);
            }

            const btn = document.createElement('button');
            btn.className = `px-3 py-1.5 rounded-lg text-sm font-medium border transition-all ${active ? 'bg-blue-600 text-white border-blue-600 shadow-sm' : 'bg-white text-gray-600 border-gray-200 hover:border-blue-300'}`;
            btn.innerText = `${i}개`;
            btn.onclick = async () => {
                // [Fix] 복수 선택(Toggle) 로직으로 변경
                if (!config.values || config.values.length === 0) {
                    // 기존 min~max 기반이면 values로 변환
                    config.values = [];
                    for (let j = config.min; j <= config.max; j++) config.values.push(j);
                }

                const existingIdx = config.values.indexOf(i);
                if (existingIdx >= 0) {
                    // 해제 시도: 단, 최소 1개는 선택되어야 하므로 체크
                    if (config.values.length > 1) {
                        config.values.splice(existingIdx, 1);
                    }
                } else {
                    // 추가
                    config.values.push(i);
                }
                config.values.sort((a, b) => a - b);

                // 하위 호환성을 위해 min, max도 업데이트
                config.min = Math.min(...config.values);
                config.max = Math.max(...config.values);

                await saveFilterConfig();
                renderFilterUI();
                // [New] 필터가 변경되었으므로 대시보드 및 테이블 즉시 갱신
                updateAnalysisDisplay(true); // AI 분석은 스킵
            };
            btnContainer.appendChild(btn);
        }
    }
}

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

    // UI 업데이트 (낙관적)
    // renderFilterUI(); // 저장 후 리렌더링 하되, DB 요청은 비동기로

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

// Zone F: 히스토리 테이블
function renderHistoryTable(stats) {
    const headerGrid = document.getElementById('historyHeader');
    const tbody = document.getElementById('historyTableBody');
    if (!tbody || !headerGrid) {
        console.error("Table elements not found:", { headerGrid, tbody });
        return;
    }

    const type = currentAnalysis.type || 'static';
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
    const maxTargetLen = Math.max(...stats.rows.map(r => r.targets.length), 0);

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

        // [New] 직접 입력형일 경우 텍스트 인풋 제공 (편집 모드 지원)
        const isManualEntry = (type === 'manual' || type === 'direct');

        // [Refinement] 직접입력형 전용 (정렬 + 글로벌 사이즈 적용)
        const alignClass = `${alignClassBase} ${globalGapClass}`;

        const targetVisualManual = `<div class="flex flex-nowrap items-center ${alignClass}" style="max-width: 100%; overflow-x: auto;">${row.targets.map(n => {
            const isMatched = row.matched.includes(n);
            const textClass = isMatched ? 'text-red-500 font-bold' : 'text-slate-400';
            return `<span class="${textClass} ${globalSizeClass} transition-all whitespace-nowrap shrink-0">${n}</span>`;
        }).join('')}</div>`;

        // [Refinement] 기본형 (정렬 + 글로벌 사이즈 적용)
        const alignClassDefault = `${alignClassBase} items-center ${globalBallGap}`;

        const targetVisualDefault = `<div class="flex flex-nowrap ${alignClassDefault}" style="max-width: 100%; overflow-x: auto;">${row.targets.map(n => {
            const isMatched = row.matched.includes(n);
            const color = window.Utils?.getBallColor(n) || '#64748b';

            // 미당첨 시 스타일
            const ballClass = isMatched
                ? 'text-white shadow-md'
                : 'text-slate-700 border border-slate-400 bg-white font-bold';

            const ballStyle = isMatched ? `background: ${color};` : '';

            return `<span class="${globalBallSize} rounded-full flex items-center justify-center font-bold transition-all shrink-0 ${ballClass}" style="${ballStyle}">${n}</span>`;
        }).join('')}</div>`;

        let targetContent = '';
        if (isManualEntry) {
            if (editingRound === row.round) {
                // 편집 모드: 인풋박스 노출 (코드 유지)
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
                // 보기 모드: 클릭 시 편집 전환
                targetContent = `
                    <div class="cursor-edit group/edit relative w-full h-full min-h-[50px] flex items-center justify-center rounded-xl hover:bg-slate-100/50 transition-colors" 
                         onclick="event.stopPropagation(); window.enterEditMode(${row.round})">
                        ${targetVisualManual}
                        <div class="absolute inset-0 flex items-center justify-center opacity-0 group-hover/edit:opacity-100 transition-opacity pointer-events-none">
                            <span class="bg-indigo-600 text-white text-[10px] px-2 py-1 rounded-full shadow-lg font-bold">클릭하여 수정</span>
                        </div>
                    </div>
                `;
            }
        } else {
            // 다른 유형(고정형 등)은 원래 디자인 유지
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
            const bg = window.Utils?.getBallColor(num) || '#64748b';
            const orbStyle = `background: ${bg}; color: white; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);`;
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
            analysis_type: 'custom'
        }, {
            onConflict: 'analysis_id,target_round' // 중복 발생 시 해당 키를 기준으로 업데이트
        });
        // onConflict 옵션 제거하여 기본 프라이머리 키/유니크 인덱스 활용 (PostgREST 기본동작)

        if (error) throw error;

        // 로컬 데이터 갱신
        const idx = currentAnalysis.history_data.findIndex(h => h.target_round === round);
        if (idx >= 0) currentAnalysis.history_data[idx].target_numbers = sortedNums;
        else currentAnalysis.history_data.push({ target_round: round, target_numbers: sortedNums, analysis_id: currentAnalysis.id });

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

// [Refactored] AI 분석 리포트 갱신 - 실제 데이터 기반 분석
window.refreshAIAnalysis = async function () {
    const section = document.getElementById('aiAnalysisSection');
    const content = document.getElementById('aiAnalysisContent');
    if (!section || !content) return;

    section.classList.remove('hidden');
    content.innerHTML = `
        <div class="flex flex-col items-center justify-center gap-4 py-8 min-h-[250px] bg-slate-50/50 rounded-2xl border border-dashed border-indigo-200">
            <div class="w-8 h-8 border-4 border-indigo-500 border-t-transparent rounded-full animate-spin"></div>
            <div class="text-center">
                <span class="block text-indigo-600 font-bold text-sm tracking-wide animate-pulse mb-1.5">AI 분석 에이전트가 데이터를 검토하고 있습니다...</span>
                <span class="block text-slate-400 text-[11px]">최초 실행 시 분석 서버 준비(Cold Start)로 인해 약 45초 가량 소요될 수 있습니다.</span>
            </div>
        </div>
    `;

    try {
        const stats = calculateStats(currentAnalysis, allDrawData);
        if (!stats || !stats.rows) throw new Error("통계 데이터 없음");

        // ── 1. 다음 회차 타겟 번호 추출 ──
        const nextRow = stats.rows[0]; // isUpcoming = true
        const targetNumbers = nextRow?.targets || [];

        // ── 2. 최근 20회차 실제 당첨번호 ──
        const recent20 = allDrawData.slice(0, 20).map(d =>
            `${d.round}회: [${(d.numbers || []).join(',')}]`
        ).join('\n');

        // ── 3. 히스토리 테이블에서 최근 30회차 적중 데이터 추출 ──
        const historyRows = stats.rows.filter(r => !r.isUpcoming).slice(0, 30);
        const hitHistory = historyRows.map(r =>
            `${r.round}회: 타겟[${r.targets.join(',')}] → 당첨[${r.winNumbers.join(',')}] → 적중${r.hitCount}개(${r.matched.join(',') || '없음'}) GAP=${r.gap} STR=${r.straight}`
        ).join('\n');

        // ── 4. 적중 패턴 통계 요약 ──
        const hitCounts = historyRows.map(r => r.hitCount);
        const hitDistribution = {};
        hitCounts.forEach(c => { hitDistribution[c] = (hitDistribution[c] || 0) + 1; });
        const hitDistText = Object.entries(hitDistribution)
            .sort((a, b) => Number(b[0]) - Number(a[0]))
            .map(([k, v]) => `${k}개적중: ${v}회(${((v / historyRows.length) * 100).toFixed(1)}%)`)
            .join(', ');

        // ── 5. GAP 패턴 분석 (연속 미출현 구간) ──
        let gapStreaks = [];
        let currentStreakStart = null;
        historyRows.forEach((r, i) => {
            if (r.gap > 0 && !r.isHit) {
                if (currentStreakStart === null) currentStreakStart = r.round;
            } else {
                if (currentStreakStart !== null) {
                    gapStreaks.push({ from: currentStreakStart, to: historyRows[i - 1]?.round, length: r.gap });
                    currentStreakStart = null;
                }
            }
        });
        const gapText = gapStreaks.length > 0
            ? gapStreaks.slice(0, 5).map(g => `${g.from}~${g.to}회(${g.length}회연속미출현)`).join(', ')
            : '최근 30회 내 장기 미출현 구간 없음';

        // ── 6. 분석 유형별 컨텍스트 ──
        let typeContext = "";
        if (currentAnalysis.type === 'group') {
            const groups = currentAnalysis.config?.groups || [];
            typeContext = groups.map(g => `그룹[${g.name}]: 번호${g.numbers.slice(0, 10).join(',')}${g.numbers.length > 10 ? '...' : ''} (조건: ${g.condition?.min}~${g.condition?.max}개)`).join('\n');
        } else if (currentAnalysis.type === 'dynamic') {
            const rules = currentAnalysis.rules || {};
            const step = rules.regression_step || 1;
            const formulaMap = {
                prev_plus_n: `${step}전회차+N`,
                carryover: `${step}전회차이월`,
                draw_date_end: '추첨일끝수',
                round_end_digit: rules.value ? `회차끝수(오프셋:${rules.value})` : '회차끝수',
                draw_date_math: '날짜사칙연산',
                math_expression: `수식(${rules.expression})`
            };
            typeContext = `동적분석 규칙: ${formulaMap[rules.formula] || rules.formula} (회귀간격: ${step})`;
        } else if (currentAnalysis.type === 'static') {
            typeContext = `고정번호 분석: [${targetNumbers.join(', ')}]`;
        }

        // ── 7. 최종 프롬프트 조립 (데이터 중심) ──
        const prompt = `[분석 대상]
제목: ${currentAnalysis.title || '커스텀 분석'}
유형: ${currentAnalysis.type}
${typeContext}
다음회차 타겟번호: [${targetNumbers.join(', ')}] (총 ${targetNumbers.length}개)

[핵심 통계]
- 현재 미출현(Gap): ${stats.currentGap}회 연속
- 현재 연속출현(Straight): ${stats.currentStraight}회
- 역대 최장 미출현: ${stats.maxGap}회
- 역대 최장 연속출현: ${stats.maxStraight}회
- 한 회차 최다 적중: ${stats.maxHits}개
- 전체 적중률: ${stats.hitRate.toFixed(1)}% (${historyRows.length}회 중 ${historyRows.filter(r => r.isHit).length}회 적중)
- 평균 적중 개수: ${stats.avgHits.toFixed(2)}개

[적중 분포]
${hitDistText}

[GAP 패턴]
${gapText}

[최근 30회차 상세 히스토리]
${hitHistory}

[최근 20회 실제 당첨번호]
${recent20}
`;

        let response;
        if (window.AIProxy) {
            try {
                response = await window.AIProxy.invoke({
                    prompt: prompt,
                    analysisType: 'custom',
                    topic: '커스텀 분석',
                    targetRound: (allDrawData[0]?.round || 0) + 1,
                    subjectRound: allDrawData[0]?.round || 0,
                    responseStyle: 'json',
                    historyData: historyRows.slice(0, 20).map(r => ({
                        round: r.round, targets: r.targets, matched: r.matched,
                        hitCount: r.hitCount, gap: r.gap, straight: r.straight
                    }))
                });
            } catch (proxyErr) {
                console.warn('AIProxy failed, falling back to Edge Function:', proxyErr);
                const result = await window.supabaseClient.functions.invoke('analyze-lotto', { body: { context: prompt } });
                if (result.error) throw result.error;
                const data = result.data;
                response = typeof data === 'string' ? JSON.parse(data) : data;
            }
        } else {
            const result = await window.supabaseClient.functions.invoke('analyze-lotto', { body: { context: prompt } });
            if (result.error) throw result.error;
            const data = result.data;
            response = typeof data === 'string' ? JSON.parse(data) : data;
        }

        if (response) {
            content.innerHTML = `
                <div class="animate-in fade-in slide-in-from-top-1 duration-500">
                    <p class="mb-6 text-slate-700 leading-relaxed text-lg font-medium">${formatAIResponse(response.trend || "데이터 분석 완료")}</p>
                    <div class="flex flex-col gap-6 text-base">
                        <div class="p-5 bg-indigo-50 rounded-2xl border border-indigo-100 shadow-sm">
                            <span class="font-black text-indigo-700 block mb-2 text-lg">✨ AI 패턴 통찰</span>
                            <div class="leading-relaxed text-slate-700">
                                ${formatAIResponse(response.pattern || "-")}
                            </div>
                        </div>
                        <div class="p-5 bg-emerald-50 rounded-2xl border border-emerald-100 shadow-sm">
                            <span class="font-black text-emerald-700 block mb-2 text-lg">🚀 데이터 기반 추천 전략</span>
                            <div class="leading-relaxed text-slate-700">
                                ${formatAIResponse(response.recommendation || "-")}
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }
    } catch (err) {
        console.error("AI 분석 실패:", err);
        content.innerHTML = `
            <div class="p-4 bg-red-50 rounded-xl border border-red-100">
                <p class="text-red-600 font-bold text-sm mb-1">AI 분석 연결 실패</p>
                <p class="text-red-400 text-xs">${err.message || '알 수 없는 오류'}</p>
            </div>`;
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
            const color = window.Utils?.getBallColor(n) || '#64748b';
            return `<span class="w-8 h-8 rounded-full flex items-center justify-center text-[10px] font-bold ${isHit ? 'text-white shadow-sm' : 'bg-white border border-slate-200 text-slate-400'}" style="${isHit ? `background: ${color}` : ''}">${n}</span>`;
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
