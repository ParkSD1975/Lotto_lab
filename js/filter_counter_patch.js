/**
 * filter_counter_patch.js
 * 
 * filter_dashboard.js의 updateNeonCounter() 함수를
 * 백엔드 정확 계산 버전으로 교체하는 패치입니다.
 * 
 * filter_dashboard.js 보다 나중에 로드하면 자동으로 덮어씁니다.
 * 
 * 사용법 (filter.html 하단):
 *   <script src="js/filter_dashboard.js?v=5"></script>
 *   <script src="js/filter_counter_patch.js"></script>  ← 추가
 */

(function () {

    // ── 설정: Render 배포 후 실제 URL로 교체 ──────────────────────
    const API_BASE = 'https://lotto-filter-api-psd.fly.dev';
    // ────────────────────────────────────────────────────────────────

    let _lastRequestId = 0;

    /**
     * FilterDashboard 상태에서 API 요청 body를 조립합니다.
     */
    function buildRequestBody(state) {
        const basket = state.basket || { fixed: [], excluded: [] };
        const userSettings = state.userSettings || {};
        const foundationFilters = state.foundationFilters || [];
        const regressionSettings = state.regressionSettings || {};
        const regressionEnabled = state.regressionEnabled !== false;
        const allDraws = state.allDraws || [];

        const body = {
            fixed: basket.fixed || [],
            excluded: basket.excluded || [],

            // 기초 필터들
            total_sum_enabled: false,
            last_digit_sum_enabled: false,
            ac_value_enabled: false,
            odd_even_enabled: false, odd_even_counts: [],
            high_low_enabled: false, high_low_counts: [],
            prime_enabled: false, prime_counts: [],
            composite_enabled: false, composite_counts: [],
            square_enabled: false, square_counts: [],
            triangular_enabled: false, triangular_counts: [],
            twin_enabled: false, twin_counts: [],
            consecutive_enabled: false, consecutive_counts: [],
            tail_digit_enabled: false, tail_digit_filters: {},
            band_enabled: false, band_filters: {},
            palace_enabled: false, palace_filters: {},
            paper_enabled: false, paper_filters: {},
            missing_period_enabled: false, missing_groups: [],
            missing_custom_enabled: false, missing_custom_groups: [],

            regression_filters: []
        };

        // ── 기초 필터 매핑 ──────────────────────────────────────────
        Object.entries(userSettings).forEach(([id, s]) => {
            if (!s || !s.enabled) return;
            const def = foundationFilters.find(f => f.id === id);
            if (!def) return;
            const key = def.filter_key;
            const vals = s.settings || {};

            switch (key) {
                case 'total_sum':
                    body.total_sum_enabled = true;
                    body.total_sum_min = vals.min !== undefined ? parseInt(vals.min) : 21;
                    body.total_sum_max = vals.max !== undefined ? parseInt(vals.max) : 255;
                    body.total_sum_excluded = vals.excludedSums || vals.excluded || [];
                    break;

                case 'last_digit_sum':
                    body.last_digit_sum_enabled = true;
                    body.last_digit_sum_min = vals.min !== undefined ? parseInt(vals.min) : 2;
                    body.last_digit_sum_max = vals.max !== undefined ? parseInt(vals.max) : 52;
                    body.last_digit_sum_excluded = vals.excludedSums || vals.excluded || [];
                    break;

                case 'ac_value':
                    body.ac_value_enabled = true;
                    body.ac_value_min = vals.min !== undefined ? parseInt(vals.min) : 0;
                    body.ac_value_max = vals.max !== undefined ? parseInt(vals.max) : 10;
                    body.ac_value_excluded = vals.excludedAcValues || [];
                    break;

                case 'odd_even_pattern':
                    body.odd_even_enabled = true;
                    body.odd_even_counts = vals.activeCounts || [];
                    break;

                case 'high_low_pattern':
                    body.high_low_enabled = true;
                    body.high_low_counts = vals.activeCounts || [];
                    break;

                case 'prime_number_patterns':
                    body.prime_enabled = true;
                    body.prime_counts = vals.selectedCounts || vals.activeCounts || [];
                    break;

                case 'composite_count':
                    body.composite_enabled = true;
                    body.composite_counts = vals.selectedCounts || vals.activeCounts || [];
                    break;

                case 'square_number_patterns':
                    body.square_enabled = true;
                    body.square_counts = vals.activeCounts || vals.selectedCounts || [];
                    break;

                case 'triangular_number_patterns':
                    body.triangular_enabled = true;
                    body.triangular_counts = vals.activeCounts || vals.selectedCounts || [];
                    break;

                case 'twin_number_patterns':
                    body.twin_enabled = true;
                    body.twin_counts = vals.activeCounts || vals.selectedCounts || [];
                    break;

                case 'consecutive_count':
                    body.consecutive_enabled = true;
                    body.consecutive_counts = vals.selectedCounts || [];
                    break;

                case 'tail_digit_patterns':
                    body.tail_digit_enabled = true;
                    body.tail_digit_filters = vals.filters || {};
                    break;

                case 'number_range_patterns':
                    body.band_enabled = true;
                    body.band_filters = vals.ranges || {};  // number_range.html은 'ranges' 키로 저장
                    break;

                case 'missing_period': {
                    // allDraws(최근 250회차)로 각 번호의 현재 연속 미출현 횟수 계산
                    if (!allDraws || allDraws.length === 0) break;

                    // missCount[i]: missing.html 기준 값 (1=최신 회차 출현, N=N-1번 연속 미출현)
                    const missCount = {};
                    const appeared = new Set();
                    for (let i = 1; i <= 45; i++) missCount[i] = allDraws.length + 1;

                    for (let idx = 0; idx < allDraws.length; idx++) {
                        const drawNums = new Set(allDraws[idx].numbers || []);
                        for (let i = 1; i <= 45; i++) {
                            if (!appeared.has(i) && drawNums.has(i)) {
                                missCount[i] = idx + 1; // idx=0(최신)→missCount=1
                                appeared.add(i);
                            }
                        }
                        if (appeared.size === 45) break;
                    }

                    // 그룹 분류 (getMissRange와 동일)
                    const g1 = [], g2 = [], g3 = [], g4 = [];
                    for (let i = 1; i <= 45; i++) {
                        const m = missCount[i];
                        if (m <= 5) g1.push(i);
                        else if (m <= 10) g2.push(i);
                        else if (m <= 15) g3.push(i);
                        else g4.push(i);
                    }

                    const ranges = vals.ranges || {};
                    body.missing_period_enabled = true;
                    body.missing_groups = [
                        { numbers: g1, min: parseInt(ranges.r1Min ?? 0), max: parseInt(ranges.r1Max ?? 6) },
                        { numbers: g2, min: parseInt(ranges.r2Min ?? 0), max: parseInt(ranges.r2Max ?? 6) },
                        { numbers: g3, min: parseInt(ranges.r3Min ?? 0), max: parseInt(ranges.r3Max ?? 6) },
                        { numbers: g4, min: parseInt(ranges.r4Min ?? 0), max: parseInt(ranges.r4Max ?? 6) },
                    ].filter(g => g.numbers.length > 0);
                    break;
                }

                case 'missing_custom_filter': {
                    // 사용자가 정의한 미출현 커스텀 그룹 필터
                    const customFilters = vals.filters || [];
                    const activeGroups = customFilters.filter(
                        f => f.enabled && f.numbers && f.numbers.length > 0
                    );
                    if (activeGroups.length === 0) break;

                    body.missing_custom_enabled = true;
                    body.missing_custom_groups = activeGroups.map(f => ({
                        numbers: f.numbers,
                        min: parseInt(f.minCount ?? 0),
                        max: parseInt(f.maxCount ?? 6)
                    }));
                    break;
                }

                case 'magic_square_pattern':
                    body.palace_enabled = true;
                    body.palace_filters = vals.filters || {};
                    break;

                case 'lotto_paper_pattern':
                    body.paper_enabled = true;
                    body.paper_filters = vals.groups || {};
                    break;
            }
        });

        // ── 회귀 필터 매핑 ──────────────────────────────────────────
        if (regressionEnabled) {
            Object.entries(regressionSettings).forEach(([stepStr, rData]) => {
                if (!rData || !rData.enabled) return;
                const step = parseInt(stepStr);
                const drawData = allDraws[step - 1];
                if (!drawData) return;
                const nums = drawData.numbers || [];
                if (nums.length === 0) return;
                body.regression_filters.push({
                    numbers: nums,
                    min: rData.min !== undefined ? parseInt(rData.min) : 0,
                    max: rData.max !== undefined ? parseInt(rData.max) : 2
                });
            });
        }

        return body;
    }

    /**
     * 카운터 UI 업데이트 (애니메이션 포함)
     */
    function animateCounter(targetVal) {
        const obj = document.getElementById('neonCounter');
        if (!obj) return;

        const startVal = parseInt(obj.innerText.replace(/,/g, '')) || 8145060;
        if (startVal === targetVal) {
            obj.innerText = targetVal.toLocaleString();
            return;
        }

        let startTimestamp = null;
        const step = (timestamp) => {
            if (!startTimestamp) startTimestamp = timestamp;
            const progress = Math.min((timestamp - startTimestamp) / 500, 1);
            const easeOut = progress * (2 - progress);
            const current = Math.floor(startVal + (targetVal - startVal) * easeOut);
            obj.innerText = current.toLocaleString();
            if (progress < 1) window.requestAnimationFrame(step);
            else obj.innerText = targetVal.toLocaleString();
        };
        window.requestAnimationFrame(step);
    }

    /**
     * 메인 함수: 필터 변경 즉시 API 호출
     * (여러 번 연속 호출 시 가장 마지막 응답만 반영)
     */
    /**
     * 현재 body에서 활성 필터 목록을 요약 문자열로 반환
     */
    function summarizeActiveFilters(body) {
        const list = [];
        if (body.fixed?.length)              list.push(`고정수(${body.fixed.length}개):[${body.fixed}]`);
        if (body.excluded?.length)           list.push(`제외수(${body.excluded.length}개):[${body.excluded}]`);
        if (body.total_sum_enabled)          list.push(`총합:${body.total_sum_min}~${body.total_sum_max}`);
        if (body.last_digit_sum_enabled)     list.push(`끝수합:${body.last_digit_sum_min}~${body.last_digit_sum_max}`);
        if (body.ac_value_enabled)           list.push(`AC:${body.ac_value_min}~${body.ac_value_max}`);
        if (body.odd_even_enabled)           list.push(`홀짝:[${body.odd_even_counts}]`);
        if (body.high_low_enabled)           list.push(`고저:[${body.high_low_counts}]`);
        if (body.prime_enabled)              list.push(`소수:[${body.prime_counts}]`);
        if (body.composite_enabled)          list.push(`합성수:[${body.composite_counts}]`);
        if (body.square_enabled)             list.push(`제곱수:[${body.square_counts}]`);
        if (body.triangular_enabled)         list.push(`삼각수:[${body.triangular_counts}]`);
        if (body.twin_enabled)               list.push(`쌍수:[${body.twin_counts}]`);
        if (body.consecutive_enabled)        list.push(`연속번호:[${body.consecutive_counts}]`);
        if (body.tail_digit_enabled)         list.push(`끝수패턴(${Object.keys(body.tail_digit_filters||{}).length}자리)`);
        if (body.band_enabled)               list.push(`번호대(${Object.keys(body.band_filters||{}).length}구간)`);
        if (body.palace_enabled)             list.push(`9궁(${Object.keys(body.palace_filters||{}).length}궁)`);
        if (body.paper_enabled)              list.push(`용지패턴(${Object.keys(body.paper_filters||{}).length}라인)`);
        if (body.missing_period_enabled)     list.push(`미출현(${body.missing_groups?.length}그룹)`);
        if (body.missing_custom_enabled)     list.push(`미출현커스텀(${body.missing_custom_groups?.length}그룹)`);
        if (body.regression_filters?.length) list.push(`회귀분석(${body.regression_filters.length}단계)`);
        return list.length ? list.join(' │ ') : '활성 필터 없음';
    }

    async function updateNeonCounter() {
        const requestId = ++_lastRequestId;

        // 로딩 표시
        const obj = document.getElementById('neonCounter');
        if (obj) obj.style.opacity = '0.5';

        try {
            const state = window.FilterDashboard?.state;
            if (!state) return;

            const body = buildRequestBody(state);

            // ── 디버그 로그 ──────────────────────────────────────────
            console.group('[FilterCounter] 조합수 계산 요청');
            console.log('활성 필터:', summarizeActiveFilters(body));
            console.log('전체 body:', JSON.stringify(body, null, 2));
            console.groupEnd();
            // ────────────────────────────────────────────────────────

            const res = await fetch(`${API_BASE}/api/count`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });

            // 더 최신 요청이 이미 발생했으면 이 응답은 무시
            if (requestId !== _lastRequestId) return;

            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();

            // ── 조합수가 매우 적으면 explain API로 원인 추적 ──────────
            if (data.count <= 1000) {
                console.warn(`⚠️ [FilterCounter] 조합수 ${data.count.toLocaleString()}개 → 원인 분석 중...`);
                fetch(`${API_BASE}/api/count/explain`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                }).then(r => r.json()).then(exp => {
                    console.group('🔍 [FilterCounter] 필터별 조합수 단계 분석');
                    (exp.steps || []).forEach(s => {
                        const removed = s.before - s.after;
                        const pct = s.before > 0 ? ((removed / s.before) * 100).toFixed(1) : '0.0';
                        const flag = removed > 0 ? '  ←' : '';
                        console.log(`${s.filter.padEnd(24)} ${s.after.toLocaleString().padStart(12)} 남음  (${removed.toLocaleString()} 제거, ${pct}%)${flag}`);
                    });
                    console.groupEnd();
                }).catch(() => {});
            }
            // ────────────────────────────────────────────────────────

            if (obj) obj.style.opacity = '1';
            animateCounter(data.count);

        } catch (err) {
            console.error('[FilterCounter] API 오류:', err);
            if (obj) obj.style.opacity = '1';
            // 실패 시 기존 근사 계산으로 폴백
            if (window.FilterDashboard?._fallbackCounter) {
                window.FilterDashboard._fallbackCounter();
            }
        }
    }

    // ── FilterDashboard에 패치 적용 ────────────────────────────────
    function applyPatch() {
        if (!window.FilterDashboard) {
            setTimeout(applyPatch, 200);
            return;
        }
        // 기존 함수를 fallback으로 보존
        window.FilterDashboard._fallbackCounter = window.FilterDashboard.updateNeonCounter.bind(window.FilterDashboard);
        // 새 함수로 교체
        window.FilterDashboard.updateNeonCounter = updateNeonCounter;
        console.log('✅ [FilterCounter] 백엔드 정확 계산 모드로 교체 완료');
    }

    applyPatch();

})();
