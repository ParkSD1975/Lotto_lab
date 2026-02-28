/**
 * filter_counter_patch.js
 *
 * filter_dashboard.js의 updateNeonCounter()를
 * 백엔드 정확 계산 버전으로 교체합니다.
 *
 * ─── 주요 기능 ───────────────────────────────────────────────────
 * 1. 50ms 디바운스 + AbortController(이전 요청 자동 취소) + 즉시 "계산 중..." 피드백
 * 2. /api/count → 정확한 조합수
 * 3. 조합수 ≤ 50,000 → /api/combinations 자동 호출 → 물리 조합 로드
 * 4. 물리 조합 로드 후 바스켓(고정/제외) 변경은 클라이언트 즉시 카운팅
 * 5. 무거운 필터 변경 시 자동 물리 조합 재로드
 * ────────────────────────────────────────────────────────────────
 */

(function () {

    const API_BASE        = 'https://lotto-filter-api-psd.fly.dev';
    const DEBOUNCE_MS     = 50;     // 마지막 변경 후 API 호출 대기 시간 (실시간성)
    const PHYSICAL_LIMIT  = 50000;  // 이 수 이하면 물리 조합 자동 로드
    const EXPLAIN_LIMIT   = 1000;   // 이 수 이하면 단계 분석 자동 실행

    // ── 내부 상태 ─────────────────────────────────────────────────
    let _debounceTimer    = null;
    let _lastRequestId    = 0;
    let _abortController  = null;   // 진행 중인 fetch 취소용

    // 물리 조합 캐시: { body(JSON key), combinations([[n1..n6],...]) }
    let _physicalCache    = null;

    // ── UI 헬퍼 ──────────────────────────────────────────────────
    function getCounter()  { return document.getElementById('neonCounter'); }
    function getStatusEl() { return document.getElementById('physicalComboStatus'); }

    /** 카운터 아래 상태 배지를 표시/갱신합니다. */
    function setStatus(html, color) {
        let el = getStatusEl();
        if (!el) {
            // 최초 1회만 DOM 생성
            const counter = getCounter();
            if (!counter) return;
            el = document.createElement('div');
            el.id = 'physicalComboStatus';
            el.style.cssText = [
                'font-size:11px', 'font-weight:600', 'text-align:center',
                'margin-top:4px', 'letter-spacing:-0.01em',
                'transition:color 0.3s'
            ].join(';');
            counter.parentNode.insertBefore(el, counter.nextSibling);
        }
        el.innerHTML  = html;
        el.style.color = color || '#64748b';
    }

    /** 숫자를 애니메이션으로 카운터에 표시합니다. */
    function animateCounter(targetVal) {
        const obj = getCounter();
        if (!obj) return;
        const startVal = parseInt((obj.innerText || '').replace(/,/g, '')) || 8145060;
        if (startVal === targetVal) { obj.innerText = targetVal.toLocaleString(); return; }

        let startTs = null;
        const step = (ts) => {
            if (!startTs) startTs = ts;
            const p   = Math.min((ts - startTs) / 400, 1);
            const ease = p * (2 - p);
            obj.innerText = Math.floor(startVal + (targetVal - startVal) * ease).toLocaleString();
            if (p < 1) requestAnimationFrame(step);
            else obj.innerText = targetVal.toLocaleString();
        };
        requestAnimationFrame(step);
    }

    // ── 필터 body 조립 ────────────────────────────────────────────
    function buildRequestBody(state) {
        const basket           = state.basket           || { fixed: [], excluded: [] };
        const userSettings     = state.userSettings     || {};
        const foundationFilters= state.foundationFilters|| [];
        const regressionSettings = state.regressionSettings || {};
        const regressionEnabled  = state.regressionEnabled !== false;
        const allDraws           = state.allDraws || [];

        const body = {
            fixed: basket.fixed || [], excluded: basket.excluded || [],
            total_sum_enabled: false, last_digit_sum_enabled: false,
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

        Object.entries(userSettings).forEach(([id, s]) => {
            if (!s || !s.enabled) return;
            const def = foundationFilters.find(f => f.id === id);
            if (!def) return;
            const key  = def.filter_key;
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
                    body.band_filters = vals.ranges || {};
                    break;
                case 'missing_period': {
                    if (!allDraws || allDraws.length === 0) break;
                    const missCount = {};
                    const appeared = new Set();
                    for (let i = 1; i <= 45; i++) missCount[i] = allDraws.length + 1;
                    for (let idx = 0; idx < allDraws.length; idx++) {
                        const drawNums = new Set(allDraws[idx].numbers || []);
                        for (let i = 1; i <= 45; i++) {
                            if (!appeared.has(i) && drawNums.has(i)) {
                                missCount[i] = idx + 1;
                                appeared.add(i);
                            }
                        }
                        if (appeared.size === 45) break;
                    }
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
                    const customFilters = vals.filters || [];
                    const activeGroups  = customFilters.filter(f => f.enabled && f.numbers?.length > 0);
                    if (!activeGroups.length) break;
                    body.missing_custom_enabled = true;
                    body.missing_custom_groups  = activeGroups.map(f => ({
                        numbers: f.numbers,
                        min: parseInt(f.minCount ?? 0),
                        max: parseInt(f.maxCount ?? 6)
                    }));
                    break;
                }
                case 'magic_square_pattern':
                    body.palace_enabled  = true;
                    body.palace_filters  = vals.filters || {};
                    break;
                case 'lotto_paper_pattern':
                    body.paper_enabled  = true;
                    body.paper_filters  = vals.groups || {};
                    break;
            }
        });

        // 회귀 필터
        if (regressionEnabled) {
            Object.entries(regressionSettings).forEach(([stepStr, rData]) => {
                if (!rData || !rData.enabled) return;
                const drawData = allDraws[parseInt(stepStr) - 1];
                if (!drawData) return;
                const nums = drawData.numbers || [];
                if (!nums.length) return;
                body.regression_filters.push({
                    numbers: nums,
                    min: rData.min !== undefined ? parseInt(rData.min) : 0,
                    max: rData.max !== undefined ? parseInt(rData.max) : 2
                });
            });
        }

        return body;
    }

    // ── 바스켓(고정/제외)만 바뀐 경우 물리 조합에서 즉시 카운팅 ────
    /**
     * _physicalCache 내 조합에서 고정/제외 조건으로 필터링한 개수를 반환.
     * 물리 캐시가 없거나 무거운 필터가 바뀐 경우 null 반환.
     */
    function clientSideCount(body) {
        if (!_physicalCache) return null;

        // 무거운 필터 키(바스켓 제외)가 캐시와 동일한지 확인
        const heavyKey = _heavyFilterKey(body);
        if (_physicalCache.heavyKey !== heavyKey) return null;

        // 물리 조합에 바스켓 필터 적용
        const fixSet = new Set(body.fixed   || []);
        const excSet = new Set(body.excluded || []);

        let count = 0;
        for (const combo of _physicalCache.combinations) {
            let ok = true;
            for (const n of combo) {
                if (excSet.has(n)) { ok = false; break; }
            }
            if (!ok) continue;
            for (const n of fixSet) {
                if (!combo.includes(n)) { ok = false; break; }
            }
            if (ok) count++;
        }
        return count;
    }

    /** 바스켓(fixed/excluded)을 제외한 나머지 필터 키 문자열 생성 (캐시 무효화용) */
    function _heavyFilterKey(body) {
        const b = Object.assign({}, body);
        delete b.fixed;
        delete b.excluded;
        return JSON.stringify(b);
    }

    // ── 물리 조합 자동 로드 ────────────────────────────────────────
    async function loadPhysicalCombos(body, countFromAPI) {
        const heavyKey = _heavyFilterKey(body);

        // 이미 같은 무거운 필터로 로드됐으면 스킵
        if (_physicalCache && _physicalCache.heavyKey === heavyKey) return;

        setStatus('⏳ 조합 목록 로드 중...', '#f59e0b');
        try {
            // ★ 핵심: 바스켓(fixed/excluded)을 제거하고 요청
            //   → 캐시에는 무거운 필터만 통과한 전체 조합을 저장
            //   → clientSideCount에서 바스켓 클라이언트 적용
            //   (바스켓 포함 로드 시: fixed=[7]→[8] 변경 시 캐시에 8 포함 조합이
            //    없어서 count=0 오표시되는 버그 방지)
            const bodyNoBasket = Object.assign({}, body, { fixed: [], excluded: [] });

            const res = await fetch(`${API_BASE}/api/combinations`, {
                method : 'POST',
                headers: { 'Content-Type': 'application/json' },
                body   : JSON.stringify(bodyNoBasket)
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();

            if (data.too_many) {
                // 무거운 필터만으로도 50,000개 초과 → 물리 캐시 사용 불가
                // 바스켓 변경 시 API 호출로 처리
                _physicalCache = null;
                setStatus(
                    `📊 조합 풀 ${data.count.toLocaleString()}개 — 바스켓 변경 시 자동 재계산`,
                    '#94a3b8'
                );
                return;
            }

            _physicalCache = { heavyKey, combinations: data.combinations };

            // window에도 노출 (AI 딥러닝 페이지 등 외부 참조용)
            if (window.FilterDashboard) {
                window.FilterDashboard._physicalCombos = data.combinations;
                window.FilterDashboard._physicalCount  = data.count;
            }

            // 현재 바스켓 기준 실제 카운트 표시
            const withBasket = clientSideCount(body) ?? data.count;
            setStatus(
                `✅ ${data.count.toLocaleString()}개 조합 풀 확보 — 현재 ${withBasket.toLocaleString()}개 (바스켓 즉시 반영)`,
                '#22c55e'
            );
            console.info(`✅ [FilterCounter] 물리 조합 ${data.count.toLocaleString()}개 로드 완료 (바스켓 적용 후 ${withBasket.toLocaleString()}개)`);
        } catch (err) {
            _physicalCache = null;
            setStatus('❌ 조합 로드 실패', '#ef4444');
            console.error('[FilterCounter] 물리 조합 로드 오류:', err);
        }
    }

    // ── 단계별 필터 분석 결과를 화면에 표시 ────────────────────────
    function showExplainPanel(steps, finalCount) {
        // 기존 패널 제거
        document.getElementById('filterExplainPanel')?.remove();

        const statusEl = getStatusEl();
        if (!statusEl) return;

        // 실제로 조합수를 줄인 단계만 표시 (시작 제외)
        const active = (steps || []).filter((s, i) => i > 0 && s.before !== s.after);
        if (!active.length) return;

        // 가장 많이 제거한 필터 찾기
        const maxRemoved = Math.max(...active.map(s => s.before - s.after));

        const panel = document.createElement('div');
        panel.id = 'filterExplainPanel';
        panel.style.cssText = [
            'margin-top:8px', 'border-radius:10px', 'overflow:hidden',
            'border:1px solid #fee2e2', 'background:#fff',
            'box-shadow:0 2px 8px rgba(239,68,68,0.10)',
            'font-size:11px'
        ].join(';');

        // 헤더
        const header = document.createElement('div');
        header.style.cssText = 'background:#fef2f2;padding:6px 12px;display:flex;justify-content:space-between;align-items:center';
        header.innerHTML = `
            <span style="font-weight:700;color:#b91c1c">🔍 필터 과다 제거 분석</span>
            <span style="color:#94a3b8;font-size:10px">최종 ${finalCount.toLocaleString()}개</span>`;

        // 행
        const rows = document.createElement('div');
        rows.style.cssText = 'padding:4px 0';

        active.forEach(s => {
            const removed = s.before - s.after;
            const pct     = s.before > 0 ? ((removed / s.before) * 100).toFixed(1) : '0.0';
            const isBig   = removed === maxRemoved;
            const row     = document.createElement('div');
            row.style.cssText = [
                'display:flex', 'align-items:center', 'justify-content:space-between',
                'padding:4px 12px',
                isBig ? 'background:#fef2f2' : ''
            ].join(';');

            // 막대 너비 (최대 제거 필터 기준 비율)
            const barPct = maxRemoved > 0 ? (removed / maxRemoved * 100).toFixed(0) : 0;

            row.innerHTML = `
                <span style="flex:0 0 auto;max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
                             color:${isBig ? '#b91c1c' : '#475569'};font-weight:${isBig ? '700' : '500'}">
                    ${isBig ? '⚠️ ' : ''}${s.filter}
                </span>
                <div style="flex:1;margin:0 8px;height:4px;background:#f1f5f9;border-radius:2px;overflow:hidden">
                    <div style="width:${barPct}%;height:100%;background:${isBig ? '#ef4444' : '#94a3b8'};border-radius:2px;transition:width 0.4s"></div>
                </div>
                <span style="flex:0 0 auto;text-align:right;color:${isBig ? '#b91c1c' : '#64748b'};font-weight:${isBig ? '700' : '400'}">
                    -${removed.toLocaleString()} (${pct}%)
                </span>`;
            rows.appendChild(row);
        });

        panel.appendChild(header);
        panel.appendChild(rows);
        statusEl.parentNode.insertBefore(panel, statusEl.nextSibling);
    }

    /** 숨기기 */
    function hideExplainPanel() {
        document.getElementById('filterExplainPanel')?.remove();
    }

    // ── 단계별 필터 분석 (count 너무 적을 때) ───────────────────────
    async function runExplain(body, showUI = false) {
        try {
            const res = await fetch(`${API_BASE}/api/count/explain`, {
                method : 'POST',
                headers: { 'Content-Type': 'application/json' },
                body   : JSON.stringify(body)
            });
            if (!res.ok) return;
            const exp = await res.json();

            // 콘솔 출력
            console.group('🔍 [FilterCounter] 필터별 조합수 단계 분석');
            (exp.steps || []).forEach(s => {
                const removed = s.before - s.after;
                const pct     = s.before > 0 ? ((removed / s.before) * 100).toFixed(1) : '0.0';
                const flag    = removed > 0 ? '  ←' : '';
                console.log(
                    `${s.filter.padEnd(24)} ${s.after.toLocaleString().padStart(12)} 남음` +
                    `  (${removed.toLocaleString()} 제거, ${pct}%)${flag}`
                );
            });
            console.groupEnd();

            // UI 패널 표시 (count ≤ 100이면 항상, 명시 요청이면 항상)
            if (showUI) showExplainPanel(exp.steps, exp.final_count ?? 0);

        } catch (_) {}
    }

    // ── 활성 필터 요약 (디버그 로그용) ───────────────────────────────
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

    // ── 서버 초기화 대기 자동 재시도 ─────────────────────────────────
    const MAX_RETRIES   = 10;   // 최대 재시도 횟수
    let _initRetryTimer = null;
    let _retryCount     = 0;    // 현재 재시도 누적 횟수

    function _scheduleRetry(delaySec) {
        _retryCount++;
        if (_retryCount > MAX_RETRIES) {
            // 최대 재시도 초과 → 폴백으로 복구
            console.warn(`[FilterCounter] 서버 연결 실패 (${MAX_RETRIES}회 재시도 초과) — 추정치 표시 모드`);
            const obj = getCounter();
            if (obj) { obj.style.opacity = '1'; }
            setStatus('⚠️ 서버 연결 실패 — 추정치 표시 중', '#f59e0b');
            // 기존 확률 기반 fallback 카운터 실행
            if (window.FilterDashboard?._fallbackCounter) {
                try { window.FilterDashboard._fallbackCounter(); } catch (_) {}
            }
            return;
        }
        clearTimeout(_initRetryTimer);
        _initRetryTimer = setTimeout(() => {
            console.log(`[FilterCounter] 서버 초기화 완료 대기 → 재시도 (${_retryCount}/${MAX_RETRIES})`);
            if (window.FilterDashboard?.updateNeonCounter) {
                window.FilterDashboard.updateNeonCounter();
            }
        }, delaySec * 1000);
    }

    // ── 핵심: 실제 API 카운트 요청 ───────────────────────────────────
    async function _doFetch(body, requestId, signal) {
        try {
            const res = await fetch(`${API_BASE}/api/count`, {
                method : 'POST',
                headers: { 'Content-Type': 'application/json' },
                body   : JSON.stringify(body),
                signal : signal    // AbortController signal (취소 지원)
            });

            if (requestId !== _lastRequestId) return;   // 더 최신 요청이 있으면 무시
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();

            // ── 서버 초기화 중 응답 처리 ─────────────────────────────
            if (data.error && data.error.includes('Initializing')) {
                const obj = getCounter();
                if (obj) { obj.style.opacity = '0.4'; }
                setStatus('⏳ 서버 준비 중... 잠시 후 자동 업데이트됩니다', '#f59e0b');
                _scheduleRetry(4);   // 4초 후 재시도 (초기화에 ~30초 소요)
                return;
            }
            // ─────────────────────────────────────────────────────────
            clearTimeout(_initRetryTimer);   // 정상 응답 시 재시도 취소
            _retryCount = 0;                 // 재시도 카운터 리셋

            const obj = getCounter();
            if (obj) obj.style.opacity = '1';
            animateCounter(data.count);

            // 조합수에 따른 분기 처리
            if (data.count === 0) {
                // ── 0개: 원인 분석 패널 자동 표시 ────────────────────
                _physicalCache = null;
                if (window.FilterDashboard) window.FilterDashboard._physicalCombos = null;
                setStatus('⛔ 조합 없음 — 아래 분석을 참고해 필터를 완화해주세요', '#ef4444');
                runExplain(body, true);   // UI 패널 표시

            } else if (data.count <= EXPLAIN_LIMIT) {
                // ── 1~1000개: 경고 + 분석 패널 표시 ──────────────────
                setStatus(`⚠️ ${data.count.toLocaleString()}개 — 필터가 너무 좁습니다`, '#f59e0b');
                runExplain(body, true);   // UI 패널 표시
                loadPhysicalCombos(body, data.count);

            } else if (data.count <= PHYSICAL_LIMIT) {
                // ── 1001~50000개: 물리 조합 자동 로드 ────────────────
                hideExplainPanel();
                loadPhysicalCombos(body, data.count);

            } else {
                // ── 50000개 초과: 안내만 ──────────────────────────────
                hideExplainPanel();
                _physicalCache = null;
                if (window.FilterDashboard) window.FilterDashboard._physicalCombos = null;
                setStatus(
                    `${data.count.toLocaleString()}개 — 필터를 좁히면 조합 목록을 확보합니다`,
                    '#94a3b8'
                );
            }

        } catch (err) {
            if (err.name === 'AbortError') return;   // 이전 요청 취소 — 정상, 무시

            // ★ CORS/네트워크 오류 → _fallbackCounter() 절대 호출 금지
            //   이유: fallback은 확률 계산으로 0을 반환할 수 있음
            //   대신: 상태 표시 + 자동 재시도
            console.warn('[FilterCounter] 서버 연결 실패 (CORS/네트워크):', err.message);
            const obj = getCounter();
            if (obj) obj.style.opacity = '0.6';
            setStatus('🔄 서버 연결 중... 자동 재시도합니다', '#f59e0b');
            _scheduleRetry(3);
        }
    }

    // ── updateNeonCounter (패치 버전) ─────────────────────────────
    function updateNeonCounter() {
        // 물리 캐시에서 즉시 클라이언트 카운팅 (바스켓만 변경된 경우)
        const state = window.FilterDashboard?.state;
        if (state) {
            const body   = buildRequestBody(state);
            const quick  = clientSideCount(body);
            if (quick !== null) {
                // 즉시 결과 반영 — API 불필요
                animateCounter(quick);
                setStatus(
                    `✅ ${_physicalCache.combinations.length.toLocaleString()}개 조합 풀 (바스켓 반영 즉시)`,
                    '#22c55e'
                );
                return;
            }
        }

        // 무거운 필터 변경 → 이전 요청 즉시 취소 + 50ms 디바운스 후 새 요청
        clearTimeout(_debounceTimer);
        if (_abortController) {
            _abortController.abort();   // 진행 중인 fetch 즉시 취소
            _abortController = null;
        }

        // 즉시 로딩 피드백
        const obj = getCounter();
        if (obj) {
            obj.style.opacity = '0.4';
            obj.title         = '계산 중...';
        }

        _debounceTimer = setTimeout(async () => {
            const state2 = window.FilterDashboard?.state;
            if (!state2) return;
            const body2     = buildRequestBody(state2);
            const requestId = ++_lastRequestId;

            // 새 AbortController 생성 (이 요청 전용)
            _abortController = new AbortController();

            // 디버그 로그
            console.group('[FilterCounter] API 조합수 요청');
            console.log('활성 필터:', summarizeActiveFilters(body2));
            console.groupEnd();

            await _doFetch(body2, requestId, _abortController.signal);
            _abortController = null;   // 요청 완료 후 정리
        }, DEBOUNCE_MS);
    }

    // ── 서버 상태 사전 체크 (페이지 로드 시) ────────────────────────
    async function checkServerReady() {
        try {
            const res  = await fetch(`${API_BASE}/api/health`);
            const data = await res.json();
            if (data.status !== 'ready') {
                // 서버가 아직 준비 중 → 상태 표시 + 자동 재시도
                const obj = getCounter();
                if (obj) obj.style.opacity = '0.4';
                setStatus('⏳ 서버 초기화 중 (약 30초)... 자동 업데이트됩니다', '#f59e0b');
                _scheduleRetry(5);
                return false;
            }
        } catch (_) {
            // health 체크 실패 → count API 시도 시 error 필드로 처리
        }
        return true;
    }

    // ── FilterDashboard에 패치 적용 ───────────────────────────────
    function applyPatch() {
        if (!window.FilterDashboard) { setTimeout(applyPatch, 200); return; }
        window.FilterDashboard._fallbackCounter = window.FilterDashboard.updateNeonCounter.bind(window.FilterDashboard);
        window.FilterDashboard.updateNeonCounter = updateNeonCounter;
        console.log('✅ [FilterCounter] 백엔드 정확 계산 + 물리 조합 모드 활성화');

        // 페이지 로드 직후 서버 상태 미리 확인
        checkServerReady().then(ready => {
            if (ready) window.FilterDashboard.updateNeonCounter();
        });
    }

    applyPatch();

})();
