/**
 * filter_counter_patch.js
 * 100% 전수조사 카운팅 + 전체 조합 생성 컨트롤러
 * v2.0 — FilterDashboard.state의 모든 필터(50+개) 완전 수집
 */

(function () {
    'use strict';

    let worker = null;
    let isWorkerReady = false;
    let isCounting = false;
    let isGenerating = false;
    let pendingFilters = null;

    // ──────────────────────────────────────────────────
    // UI 헬퍼
    // ──────────────────────────────────────────────────
    function animateValue(obj, start, end, duration) {
        let startTimestamp = null;
        const step = (timestamp) => {
            if (!startTimestamp) startTimestamp = timestamp;
            const progress = Math.min((timestamp - startTimestamp) / duration, 1);
            obj.innerHTML = Math.floor(progress * (end - start) + start).toLocaleString() + '개';
            if (progress < 1) window.requestAnimationFrame(step);
        };
        window.requestAnimationFrame(step);
    }

    function updateCounterUI(count) {
        const counterEl = document.getElementById('neonCounter');
        if (counterEl) {
            const currentVal = parseInt(counterEl.innerText.replace(/[^0-9]/g, '')) || 8145060;
            animateValue(counterEl, currentVal, count, 400);
            counterEl.classList.remove('opacity-50', 'animate-pulse');
        }
    }

    // ──────────────────────────────────────────────────
    // 워커 초기화
    // ──────────────────────────────────────────────────
    function initWorker() {
        if (!window.Worker) return;
        worker = new Worker('js/filter/combination_worker.js');
        worker.postMessage({ type: 'INIT' });

        worker.onmessage = function (e) {
            const data = e.data;
            if (data.type === 'INIT_DONE') {
                isWorkerReady = true;
                triggerCount();
            } else if (data.type === 'COUNT_RESULT') {
                isCounting = false;
                updateCounterUI(data.count);
                if (pendingFilters) {
                    const filters = pendingFilters;
                    pendingFilters = null;
                    sendToWorker(filters);
                }
            } else if (data.type === 'GENERATE_RESULT') {
                isGenerating = false;

                const combos = data.combos.map((arr, idx) => ({
                    rank: idx + 1,
                    numbers: arr,
                    score: 1.0,
                    type: 'filter_exact_match'
                }));

                localStorage.setItem('generated_filter_combos', JSON.stringify({
                    timestamp: new Date().getTime(),
                    total_pool: data.totalValid,
                    combinations: combos
                }));

                const btn = document.getElementById('btnGenerateCombos');
                if (btn) btn.innerHTML = '<span class="material-symbols-outlined text-[18px]">play_arrow</span>조합 생성 완료!';

                window.location.href = 'combination_generator.html';
            }
        };
    }

    // ──────────────────────────────────────────────────
    // 필터 수집 (메인 함수)
    // ──────────────────────────────────────────────────
    function gatherActiveFilters() {
        const filters = {};

        // FilterDashboard 없으면 빈 필터 반환 (워커는 통과만 함)
        if (!window.FilterDashboard || !window.FilterDashboard.state) {
            return filters;
        }

        const S = window.FilterDashboard.state;

        /**
         * 특정 filter_key가 enabled인지 확인 후 settings 반환
         * disabled이거나 없으면 null 반환
         */
        function getSetting(filterKey) {
            const def = (S.foundationFilters || []).find(d => d.filter_key === filterKey);
            if (!def) return null;
            const us = S.userSettings[def.id];
            if (!us || !us.enabled) return null;
            return us.settings || {};
        }

        // ── 바스켓: 고정수 / 제외수 ──────────────────────
        filters.fixed    = (S.basket && S.basket.fixed)    ? [...S.basket.fixed]    : [];
        filters.excluded = (S.basket && S.basket.excluded) ? [...S.basket.excluded] : [];

        // ── 총합 ─────────────────────────────────────────
        const totalSumSet = getSetting('total_sum');
        if (totalSumSet) {
            filters.sumRange = {
                min: totalSumSet.min !== undefined ? totalSumSet.min : 21,
                max: totalSumSet.max !== undefined ? totalSumSet.max : 255
            };
            // 수동 제외합
            const excl = [...(totalSumSet.excludedSums || [])];
            // 시스템 자동 제외합 (최근 10회차)
            if (totalSumSet.recent10FilterActive && S.allDraws && S.allDraws.length > 0) {
                const restAuto = totalSumSet.restoredAutoSums || [];
                S.allDraws.slice(0, 10).forEach(d => {
                    let s = d.sum;
                    if (s === undefined || s === null) {
                        if (d.numbers && Array.isArray(d.numbers)) s = d.numbers.reduce((a, b) => a + b, 0);
                    }
                    if (s !== null && s !== undefined && !restAuto.includes(s)) excl.push(s);
                });
            }
            filters.sumExcluded = [...new Set(excl)];
        }

        // ── 끝수합 ───────────────────────────────────────
        const tailSumSet = getSetting('last_digit_sum');
        if (tailSumSet) {
            filters.tailSumRange = {
                min: tailSumSet.min !== undefined ? tailSumSet.min : 0,
                max: tailSumSet.max !== undefined ? tailSumSet.max : 45
            };
            const excl = [...(tailSumSet.excludedSums || [])];
            if (tailSumSet.recent10FilterActive && S.allDraws && S.allDraws.length > 0) {
                const restAuto = tailSumSet.restoredAutoSums || [];
                const latestDraw = S.allDraws[0];
                let latestTailSum = latestDraw ? latestDraw.tail_sum : null;
                if ((latestTailSum === undefined || latestTailSum === null) && latestDraw && latestDraw.numbers) {
                    latestTailSum = latestDraw.numbers.reduce((a, b) => a + (b % 10), 0);
                }
                if (latestTailSum !== null && latestTailSum !== undefined && !restAuto.includes(latestTailSum)) {
                    excl.push(latestTailSum);
                }
            }
            filters.tailSumExcluded = [...new Set(excl)];
        }

        // ── AC값 ─────────────────────────────────────────
        const acSet = getSetting('ac_value');
        if (acSet) {
            filters.acRange = {
                min: acSet.min !== undefined ? acSet.min : 0,
                max: acSet.max !== undefined ? acSet.max : 9
            };
            const excl = [...(acSet.excludedAcValues || [])];
            if (acSet.recent10FilterActive && S.allDraws && S.allDraws.length > 0) {
                const restAuto = acSet.restoredAutoAcValues || [];
                const acCount = {};
                S.allDraws.slice(0, 10).forEach(d => {
                    const ac = d.ac_value !== undefined && d.ac_value !== null ? d.ac_value
                        : (d.acValue !== undefined && d.acValue !== null ? d.acValue : null);
                    if (ac !== null) acCount[ac] = (acCount[ac] || 0) + 1;
                });
                Object.entries(acCount).forEach(([ac, cnt]) => {
                    const acNum = parseInt(ac);
                    if (cnt > 6 && !restAuto.includes(acNum)) excl.push(acNum);
                });
            }
            filters.acExcluded = [...new Set(excl)];
        }

        // ── 홀짝 패턴 ────────────────────────────────────
        const oddEvenSet = getSetting('odd_even_pattern');
        if (oddEvenSet) {
            const selected  = oddEvenSet.selectedRatios || [];
            const manualExcl = oddEvenSet.excludedOddEvens || [];
            let sysExcl = [];
            if (oddEvenSet.recent10FilterActive && S.allDraws && S.allDraws.length >= 10) {
                const restAuto = oddEvenSet.restoredAutoOddEvens || [];
                const counts = {};
                S.allDraws.slice(0, 10).forEach(d => {
                    let ratio = d.odd_even_ratio;
                    if (!ratio && d.numbers) {
                        const odd = d.numbers.filter(n => n % 2 !== 0).length;
                        ratio = `${odd}:${6 - odd}`;
                    }
                    if (ratio) counts[ratio] = (counts[ratio] || 0) + 1;
                });
                sysExcl = Object.entries(counts)
                    .filter(([r, cnt]) => cnt > 6 && !restAuto.includes(r))
                    .map(([r]) => r);
            }
            if (selected.length > 0) {
                filters.oddEvenPatterns = selected;
                filters.oddEvenExcluded = [...new Set([...manualExcl, ...sysExcl])];
            }
        }

        // ── 고저 패턴 ─────────────────────────────────────
        const highLowSet = getSetting('high_low_pattern');
        if (highLowSet) {
            const selected   = highLowSet.selectedRatios || [];
            const manualExcl = highLowSet.excludedHighLows || [];
            let sysExcl = [];
            if (highLowSet.recent10FilterActive && S.allDraws && S.allDraws.length >= 10) {
                const restAuto = highLowSet.restoredAutoHighLows || [];
                const counts = {};
                S.allDraws.slice(0, 10).forEach(d => {
                    let ratio = d.high_low_ratio;
                    if (!ratio && d.numbers) {
                        const low = d.numbers.filter(n => n <= 22).length;
                        ratio = `${low}:${6 - low}`;
                    }
                    if (ratio) counts[ratio] = (counts[ratio] || 0) + 1;
                });
                sysExcl = Object.entries(counts)
                    .filter(([r, cnt]) => cnt > 6 && !restAuto.includes(r))
                    .map(([r]) => r);
            }
            if (selected.length > 0) {
                filters.highLowPatterns = selected;
                filters.highLowExcluded = [...new Set([...manualExcl, ...sysExcl])];
            }
        }

        // ── 끝수 패턴 ─────────────────────────────────────
        const tailDigitSet = getSetting('tail_digit_patterns');
        if (tailDigitSet && tailDigitSet.filters) {
            filters.tailDigitRanges = tailDigitSet.filters; // {'0':{min,max}, '1':{min,max}, ...}
        }

        // ── 소수 ──────────────────────────────────────────
        const primeSet = getSetting('prime_number_patterns');
        if (primeSet) {
            filters.primeFilter = {
                selectedCounts: primeSet.selectedCounts || [],
                excludedPrimes:  primeSet.excludedPrimes  || []
            };
        }

        // ── 제곱수 ────────────────────────────────────────
        const squareSet = getSetting('square_number_patterns');
        if (squareSet) {
            filters.squareFilter = {
                selectedCounts: squareSet.selectedCounts || squareSet.activeCounts || [],
                excludedNumbers: squareSet.excludedNumbers || squareSet.excludedSquares || []
            };
        }

        // ── 삼각수 ────────────────────────────────────────
        const triSet = getSetting('triangular_number_patterns');
        if (triSet) {
            filters.triangularFilter = {
                selectedCounts: triSet.selectedCounts || triSet.activeCounts || [],
                excludedNumbers: triSet.excludedNumbers || triSet.excludedTriangulars || []
            };
        }

        // ── 쌍수(동형수) ──────────────────────────────────
        const twinSet = getSetting('twin_number_patterns');
        if (twinSet) {
            filters.twinFilter = {
                activeCounts:    twinSet.activeCounts    || twinSet.selectedCounts || [],
                selectedNumbers: twinSet.selectedNumbers || twinSet.excludedTwins  || []
            };
        }

        // ── 합성수 ────────────────────────────────────────
        const compositeSet = getSetting('composite_count');
        if (compositeSet) {
            filters.compositeFilter = {
                selectedValues:    compositeSet.selectedCounts  || compositeSet.selectedValues || [],
                excludedComposites: compositeSet.excludedComposites || []
            };
        }

        // ── 연번 ──────────────────────────────────────────
        const consecSet = getSetting('consecutive_count');
        if (consecSet) {
            filters.consecutiveFilter = {
                selectedCounts: consecSet.selectedCounts || [],
                runFilters:     consecSet.runFilters     || {}
            };
        }

        // ── 번호대 + 엔트로피 ────────────────────────────
        const numRangeSet = getSetting('number_range_patterns');
        if (numRangeSet && numRangeSet.ranges) {
            const { entropy, ...rangeParts } = numRangeSet.ranges;
            filters.numberRangeFilter = {
                ranges:  rangeParts,
                entropy: entropy || null
            };
        }

        // ── 9궁 (마방진) ──────────────────────────────────
        const magicSet = getSetting('magic_square_pattern');
        if (magicSet && magicSet.filters) {
            filters.magicSquareFilter = { filters: magicSet.filters };
        }

        // ── 로또용지 ──────────────────────────────────────
        const paperSet = getSetting('lotto_paper_pattern');
        if (paperSet && paperSet.groups) {
            filters.lottoPaperFilter = { groups: paperSet.groups };
        }

        // ── 배수 패턴 ─────────────────────────────────────
        const multipleSet = getSetting('multiple_3_count');
        if (multipleSet && multipleSet.filters) {
            filters.multipleFilter = { filters: multipleSet.filters };
        }

        // ── 이월수 ────────────────────────────────────────
        const carryoverSet = getSetting('carryover_count');
        if (carryoverSet) {
            const prevNums      = (S.dynamicTargets && S.dynamicTargets['carryover_count'])       || [];
            const prevBonusNums = (S.dynamicTargets && S.dynamicTargets['carryover_bonus_count']) || [];
            filters.carryoverFilter = {
                selectedCounts:     carryoverSet.selectedCounts              || [],
                carryoverNums:      prevNums,
                selectedBonusCounts: carryoverSet.selectedBonusIncludedCounts || [],
                carryoverBonusNums: prevBonusNums
            };
        }

        // ── 이웃수 ────────────────────────────────────────
        const neighborSet = getSetting('neighbor_number_patterns');
        if (neighborSet) {
            const neighborNums = (S.dynamicTargets && S.dynamicTargets['neighbor_number_patterns']) || [];
            filters.neighborFilter = {
                selectedValues: neighborSet.selectedValues || neighborSet.selectedCounts || [],
                neighborNums
            };
        }

        // ── Hot/Cold 5 / 10 / 15 / 20 ───────────────────
        const CRITERIA = {
            5:  { hot: 2, neutralMin: 1, neutralMax: 1 },
            10: { hot: 3, neutralMin: 1, neutralMax: 2 },
            15: { hot: 4, neutralMin: 2, neutralMax: 3 },
            20: { hot: 5, neutralMin: 2, neutralMax: 4 }
        };
        for (const period of [5, 10, 15, 20]) {
            const hcSet = getSetting(`hot_cold_${period}`);
            if (!hcSet) continue;

            const crit = CRITERIA[period];
            const recentDraws = (S.allDraws || []).slice(0, period);
            const cntMap = {};
            for (let n = 1; n <= 45; n++) cntMap[n] = 0;
            recentDraws.forEach(d => { (d.numbers || []).forEach(n => { if (n >= 1 && n <= 45) cntMap[n]++; }); });

            const hotNums = [], warmNums = [], coldNums = [];
            for (let n = 1; n <= 45; n++) {
                const c = cntMap[n];
                if (c >= crit.hot) hotNums.push(n);
                else if (c >= crit.neutralMin) warmNums.push(n);
                else coldNums.push(n);
            }

            // 설정 정규화: periodFilter(flat) 또는 hotRange(배열) 형식 모두 지원
            let effVals = hcSet;
            if (hcSet.periodFilter) {
                const pf = hcSet.periodFilter;
                effVals = {
                    hotRange:  [parseInt(pf.hotMin     ?? 0), parseInt(pf.hotMax     ?? 6)],
                    warmRange: [parseInt(pf.neutralMin  ?? 0), parseInt(pf.neutralMax ?? 6)],
                    coldRange: [parseInt(pf.coldMin    ?? 0), parseInt(pf.coldMax    ?? 6)]
                };
            }

            filters[`hotCold${period}`] = {
                hotNums,
                warmNums,
                coldNums,
                hotRange:  Array.isArray(effVals.hotRange)  ? effVals.hotRange  : [0, 6],
                warmRange: Array.isArray(effVals.warmRange) ? effVals.warmRange : [0, 6],
                coldRange: Array.isArray(effVals.coldRange) ? effVals.coldRange : [0, 6]
            };
        }

        // ── 미출현 기간 ────────────────────────────────────
        const missingPeriodSet = getSetting('missing_period');
        if (missingPeriodSet && S.allDraws && S.allDraws.length > 0) {
            const ranges = missingPeriodSet.ranges || {};
            // 그룹 정의 (r1~r4): missing_period.html과 동일 범위 기준
            const GROUP_DEFS = [
                { key: 'r1', minM: parseInt(ranges.r1Min ?? 1),   maxM: parseInt(ranges.r1Max ?? 10),  settingMinKey: 'r1Min', settingMaxKey: 'r1Max' },
                { key: 'r2', minM: parseInt(ranges.r2Min ?? 11),  maxM: parseInt(ranges.r2Max ?? 20),  settingMinKey: 'r2Min', settingMaxKey: 'r2Max' },
                { key: 'r3', minM: parseInt(ranges.r3Min ?? 21),  maxM: parseInt(ranges.r3Max ?? 50),  settingMinKey: 'r3Min', settingMaxKey: 'r3Max' },
                { key: 'r4', minM: parseInt(ranges.r4Min ?? 51),  maxM: parseInt(ranges.r4Max ?? 999), settingMinKey: 'r4Min', settingMaxKey: 'r4Max' }
            ];

            // 각 번호의 현재 미출현 횟수 계산
            const missCnt = new Array(46).fill(0);
            for (let n = 1; n <= 45; n++) {
                let miss = 0;
                for (let di = 0; di < S.allDraws.length; di++) {
                    if ((S.allDraws[di].numbers || []).indexOf(n) !== -1) break;
                    miss++;
                }
                missCnt[n] = miss;
            }

            // 그룹별로 해당 번호 묶어서 필터 생성
            const mpGroups = [];
            GROUP_DEFS.forEach(gd => {
                const nums = [];
                for (let n = 1; n <= 45; n++) {
                    if (missCnt[n] >= gd.minM && missCnt[n] <= gd.maxM) nums.push(n);
                }
                if (nums.length === 0) return;
                const minCount = ranges[`${gd.key}CountMin`] !== undefined ? parseInt(ranges[`${gd.key}CountMin`]) : 0;
                const maxCount = ranges[`${gd.key}CountMax`] !== undefined ? parseInt(ranges[`${gd.key}CountMax`]) : 6;
                mpGroups.push({ nums, min: minCount, max: maxCount });
            });
            if (mpGroups.length > 0) filters.missingPeriodFilter = mpGroups;
        }

        // ── 미출현 커스텀 ──────────────────────────────────
        const missingCustomSet = getSetting('missing_custom_filter');
        if (missingCustomSet && missingCustomSet.filters && missingCustomSet.filters.length > 0) {
            const mcGroups = missingCustomSet.filters
                .filter(g => g.enabled)
                .map(g => ({
                    nums: g.numbers || [],
                    min:  g.minCount !== undefined ? g.minCount : 0,
                    max:  g.maxCount !== undefined ? g.maxCount : 6
                }))
                .filter(g => g.nums.length > 0);
            if (mcGroups.length > 0) filters.missingCustomFilter = mcGroups;
        }

        // ── 커스텀 분석 필터 (ai_custom_analyses) ────────
        if (S.customFilters && S.customFilters.length > 0 && window.LOTTO_CONSTANTS && window.LOTTO_CONSTANTS.calculateCustomTargets) {
            const cfArr = [];
            S.customFilters.forEach(cf => {
                if (!cf.enabled) return;
                try {
                    const targetNums = window.LOTTO_CONSTANTS.calculateCustomTargets(cf, S.allDraws, { isPrediction: true });
                    if (!targetNums || targetNums.length === 0) return;

                    // min/max: rules 우선 → cf 직접 필드 → 0/6 기본값
                    let rules = {};
                    try { rules = typeof cf.rules === 'string' ? JSON.parse(cf.rules || '{}') : (cf.rules || {}); } catch (_) {}
                    const minCount = rules.minCount !== undefined ? rules.minCount
                        : (cf.min_count !== undefined ? cf.min_count : 0);
                    const maxCount = rules.maxCount !== undefined ? rules.maxCount
                        : (cf.max_count !== undefined ? cf.max_count : 6);

                    cfArr.push({
                        id:         cf.id,
                        title:      cf.title,
                        targetNums: targetNums.filter(n => n >= 1 && n <= 45),
                        min:        parseInt(minCount),
                        max:        parseInt(maxCount)
                    });
                } catch (err) {
                    console.warn(`[filterCounter] 커스텀 필터 오류: ${cf.title}`, err);
                }
            });
            if (cfArr.length > 0) filters.customAnalysisFilters = cfArr;
        }

        // ── 회귀 분석 (steps 2~200) ───────────────────────
        if (S.regressionEnabled && S.regressionSettings && S.allDraws && S.allDraws.length > 0) {
            const regArr = [];
            const regSettings = S.regressionSettings;

            for (let step = 2; step <= 200; step++) {
                const rs = regSettings[step] || regSettings[String(step)];
                if (!rs || !rs.enabled) continue;

                const draw = S.allDraws[step - 1]; // draws[0]=최신회차, draws[step-1]=step번째 이전 회차
                if (!draw) continue;

                regArr.push({
                    step,
                    drawNums: (draw.numbers || []).map(Number),
                    min:      parseInt(rs.min !== undefined ? rs.min : 0),
                    max:      parseInt(rs.max !== undefined ? rs.max : 6)
                });
            }
            if (regArr.length > 0) filters.regressionFilters = regArr;
        }

        return filters;
    }

    // ──────────────────────────────────────────────────
    // 워커에 전송
    // ──────────────────────────────────────────────────
    function sendToWorker(filters) {
        if (!isWorkerReady || isGenerating) return;
        if (isCounting) { pendingFilters = filters; return; }

        isCounting = true;
        const counterEl = document.getElementById('neonCounter');
        if (counterEl) counterEl.classList.add('opacity-50', 'animate-pulse');
        worker.postMessage({ type: 'COUNT', filters });
    }

    function triggerCount() {
        sendToWorker(gatherActiveFilters());
    }

    // ──────────────────────────────────────────────────
    // 조합 생성 버튼
    // ──────────────────────────────────────────────────
    window.generateFinalCombinations = function () {
        if (!isWorkerReady) {
            alert('조합 엔진이 준비 중입니다. 잠시만 기다려주세요.');
            return;
        }

        const counterEl = document.getElementById('neonCounter');
        const currentCount = parseInt(counterEl?.innerText.replace(/[^0-9]/g, '')) || 0;

        if (currentCount === 0) {
            alert('선택하신 필터 조건에 맞는 조합이 0개입니다. 필터를 조금 완화해주세요.');
            return;
        }

        if (currentCount > 50000) {
            const proceed = confirm(
                `현재 ${currentCount.toLocaleString()}개의 조합이 통과되었습니다.\n` +
                `웹 브라우저 보호를 위해 앞의 5만 개까지만 생성됩니다.\n\n` +
                `필터를 더 켜서 조합 수를 정밀하게 줄이는 것을 권장합니다.\n` +
                `그래도 생성하시겠습니까?`
            );
            if (!proceed) return;
        }

        isGenerating = true;
        const btn = document.getElementById('btnGenerateCombos');
        if (btn) btn.innerHTML = '<span class="material-symbols-outlined animate-spin text-[18px]">sync</span>추출 중...';

        worker.postMessage({ type: 'GENERATE', filters: gatherActiveFilters() });
    };

    // ──────────────────────────────────────────────────
    // 이벤트 리스너 & 초기화
    // ──────────────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', () => {
        initWorker();

        // 필터 변경 시 자동 리카운팅
        document.body.addEventListener('change', (e) => {
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') triggerCount();
        });
        document.body.addEventListener('click', (e) => {
            if (e.target.closest('button:not(#btnGenerateCombos)')) setTimeout(triggerCount, 50);
        });

        // FilterDashboard가 DB 로드 완료 후 렌더링할 때 다시 카운트
        const origRenderUI = window.FilterDashboard && window.FilterDashboard.renderUI;
        if (window.FilterDashboard && origRenderUI) {
            window.FilterDashboard.renderUI = function () {
                origRenderUI.call(window.FilterDashboard);
                // 렌더 직후 최신 state로 카운트 재요청
                if (isWorkerReady) triggerCount();
            };
        }
    });

    // FilterDashboard가 늦게 로드되는 경우를 위한 추가 훅
    window.addEventListener('load', () => {
        if (isWorkerReady) setTimeout(triggerCount, 300);
    });

})();
