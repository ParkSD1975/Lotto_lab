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
    let lastExactCount = -1; // -1: 아직 계산 안됨, 0+: 워커 전수조사 결과
    let indepCountTimer = null;   // debounce 타이머: 마지막 COUNT_RESULT 후 INDEP_COUNT 예약
    let isIndepCounting = false;  // INDEP_COUNT 진행 중 여부
    let pendingIndepCount = false; // INDEP_COUNT 완료 후 재실행 필요 여부
    // [fix-319] worker hang 방지 — 일정 시간 응답 없으면 isCounting 강제 reset 후 pending 재실행
    let _countTimeoutId = null;
    const COUNT_HANG_TIMEOUT_MS = 12000; // 12초 후에도 COUNT_RESULT 없으면 hang으로 간주

    // filter_dashboard.js의 updateNeonCounter()에서 직접 워커 트리거 가능하도록 전역 노출
    window.triggerFilterCount = function () {
        if (isWorkerReady && !isGenerating) triggerCount();
    };

    // 수동필터 뱃지 갱신 등 외부에서 CUMUL_BADGES 재실행 요청
    window.triggerIndepCount = function () {
        if (isWorkerReady && !isGenerating) scheduleIndepCount();
    };

    // [fix-319] 디버그 진단 — 사용자 환경에서 콘솔로 worker 상태 확인
    window._counterDebug = function () {
        return {
            isWorkerReady, isCounting, isGenerating,
            lastExactCount, hasPending: !!pendingFilters,
            displayCount: document.getElementById('neonCounter')?.textContent?.trim()
        };
    };
    // [fix-319] 강제 reset (긴급 stuck 해소)
    window._counterForceReset = function () {
        const wasStuck = isCounting;
        isCounting = false;
        if (_countTimeoutId) { clearTimeout(_countTimeoutId); _countTimeoutId = null; }
        const pending = pendingFilters;
        pendingFilters = null;
        if (pending) sendToWorker(pending);
        else if (isWorkerReady) triggerCount();
        return { wasStuck, retriggered: true };
    };

    // ──────────────────────────────────────────────────
    // Foundation 필터 배지 키 목록 (로딩 상태 표시용)
    // ──────────────────────────────────────────────────
    const BADGE_FILTER_KEYS = [
        'total_sum', 'tail_sum', 'ac_value', 'odd_even_pattern', 'high_low_pattern',
        // 끝수: 개별 키
        'end_digit_0_count','end_digit_1_count','end_digit_2_count','end_digit_3_count',
        'end_digit_4_count','end_digit_5_count','end_digit_6_count','end_digit_7_count',
        'end_digit_8_count','end_digit_9_count',
        'prime_number_patterns', 'square_number_patterns',
        'triangular_number_patterns', 'twin_number_patterns', 'composite_count',
        'consecutive_count', 'number_range_patterns', 'magic_square_pattern',
        'lotto_paper_pattern',
        // 배수: 개별 키
        'multiple_3_count', 'multiple_4_count', 'multiple_5_count',
        'multiple_7_count', 'multiple_8_count',
        'multiple_3_4_count', 'multiple_3_5_count', 'multiple_4_5_count', 'no_multiple_count',
        'carryover_count',
        'neighbor_number_patterns', 'hot_cold_5', 'hot_cold_10', 'hot_cold_15', 'hot_cold_20',
        'missing_period', 'missing_custom_filter'
    ];

    // 배지 업데이트: 각 필터 카드에 누적 카운트 표시
    // [fix-266] 워커 결과 없는 Foundation 배지(비활성 필터)는 8,145,060개(전체 통과) 표시
    //           → 사용자에게 21개 Foundation 카드 모두 일관된 카운트 노출
    //           BADGE_FILTER_KEYS 전체를 순회하도록 변경 → renderUI() 후에도 fallback 동작
    const TOTAL_LOTTO_COMBINATIONS = 8145060;
    function updateFilterCountBadges(badges) {
        window._lastCumulBadges = badges;
        // 1) 워커 결과가 있는 키: 정확한 누적 카운트 + 활성 스타일
        for (const [filterKey, survivors] of Object.entries(badges)) {
            const el = document.getElementById(`indep-count-${filterKey}`);
            if (el) {
                el.textContent = survivors.toLocaleString() + '개';
                el.classList.remove('hidden', 'indep-loading', 'indep-inactive');
            }
        }
        // 2) 결과 없는 BADGE_FILTER_KEYS Foundation 배지: 8,145,060개(전체 통과) + 회색 톤
        BADGE_FILTER_KEYS.forEach(function(filterKey) {
            if (badges[filterKey] !== undefined) return; // 이미 1)에서 처리됨
            const el = document.getElementById('indep-count-' + filterKey);
            if (el) {
                el.textContent = TOTAL_LOTTO_COMBINATIONS.toLocaleString() + '개';
                el.classList.remove('hidden', 'indep-loading');
                el.classList.add('indep-inactive');
            }
        });
    }

    // 전역 노출: renderUI 재실행 후 배지 복원용
    window.applyIndepCountBadges = function() {
        if (window._lastCumulBadges) {
            updateFilterCountBadges(window._lastCumulBadges);
        } else if (isIndepCounting) {
            showLoadingBadges(); // 계산 중이면 로딩 상태 복원
        }
    };

    // 모든 foundation 및 수동필터 배지에 로딩 상태 표시
    function showLoadingBadges() {
        // 고정 필터들
        BADGE_FILTER_KEYS.forEach(function(filterKey) {
            const el = document.getElementById('indep-count-' + filterKey);
            if (el) {
                el.textContent = '···';
                el.classList.remove('hidden');
                el.classList.add('indep-loading');
            }
        });
        
        // [추가] 수동필터 배지들 (동적 ID)
        document.querySelectorAll("[id^='indep-count-manual_']").forEach(function(el) {
            el.textContent = '···';
            el.classList.remove('hidden');
            el.classList.add('indep-loading');
        });
    }

    // CUMUL_BADGES 실제 전송 (누적 카운팅)
    // 누적 카운팅: enabled 필터만 (COUNT와 동일한 필터셋)
    // [fix-266] 비활성 Foundation 필터 배지는 DOM 레벨에서 "8,145,060개"(전체 통과)로 표시
    //           → 워커 누적 체인엔 영향 없음 + 사용자에게 21개 Foundation 카드 카운트 노출
    function sendIndepCount() {
        indepCountTimer = null;
        if (!worker || !isWorkerReady || isGenerating) return;
        isIndepCounting = true;
        showLoadingBadges(); // 즉시 로딩 상태 표시
        const filters = gatherActiveFilters(false);
        worker.postMessage({ type: 'CUMUL_BADGES', filters });
    }

    // INDEP_COUNT 예약 (debounce 1초)
    // COUNT_RESULT가 올 때마다 타이머 리셋 → 마지막 COUNT 안정화 후 실행
    // isIndepCounting 중이면 pendingIndepCount 플래그만 설정 (중복 실행 방지)
    function scheduleIndepCount() {
        if (isIndepCounting) {
            pendingIndepCount = true; // 현재 계산 완료 후 재실행
            return;
        }
        if (indepCountTimer) clearTimeout(indepCountTimer);
        indepCountTimer = setTimeout(sendIndepCount, 1000);
    }

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
        worker = new Worker('js/filter/combination_worker.js?v=' + Date.now());
        worker.postMessage({ type: 'INIT' });

        worker.onmessage = function (e) {
            const data = e.data;
            if (data.type === 'INIT_DONE') {
                isWorkerReady = true;
                // allDraws 로드 완료된 경우에만 즉시 트리거
                // 미로드 시 renderUI 훅이 loadDataFromDB 완료 후 자동 트리거함
                if (window.FilterDashboard?.state?.allDraws?.length > 0) {
                    triggerCount();
                }
            } else if (data.type === 'STEPCNT_RESULT') {
                printStepCount(data.result);
            } else if (data.type === 'DIAGNOSE_RESULT') {
                showDiagnoseResult(data.result);
            } else if (data.type === 'COUNT_RESULT') {
                isCounting = false;
                if (_countTimeoutId) { clearTimeout(_countTimeoutId); _countTimeoutId = null; }  // [fix-319] hang timer 해제
                lastExactCount = data.count; // 전수조사 정확한 값 저장
                updateCounterUI(data.count);
                if (pendingFilters) {
                    const filters = pendingFilters;
                    pendingFilters = null;
                    sendToWorker(filters);
                }
                // COUNT_RESULT마다 INDEP_COUNT 예약 (debounce 2초)
                // pendingFilters 여부와 무관하게 마지막 COUNT 완료 후 자동 실행
                scheduleIndepCount();
            } else if (data.type === 'CUMUL_BADGES_RESULT') {
                isIndepCounting = false;
                updateFilterCountBadges(data.badges);
                // 계산 중 필터가 변경된 경우 재실행
                if (pendingIndepCount) {
                    pendingIndepCount = false;
                    scheduleIndepCount();
                }
            } else if (data.type === 'GENERATE_RESULT') {
                isGenerating = false;

                const combos = data.combos.map((arr, idx) => ({
                    rank: idx + 1,
                    numbers: arr,
                    score: 1.0,
                    type: 'filter_exact_match'
                }));

                // 대상 회차 찾기 (allDraws[0]이 최신 회차이므로 + 1)
                const sysState = window.FilterDashboard?.state;
                const latestRoundObj = sysState?.allDraws?.[0];
                const tr = latestRoundObj ? latestRoundObj.round + 1 : null;

                // [추가/수정] 필터 스냅샷 캡처 (UI 복원용)
                const state = window.FilterDashboard?.state || {};
                // foundationFilters: UUID→filter_key 맵 복원에 필요 (combination_generator.html에 FilterDashboard 없음)
                const _ff = (state.foundationFilters || []).map(d => ({ id: d.id, filter_key: d.filter_key }));
                const filter_snapshot = {
                    userSettings: state.userSettings || {},
                    basket: state.basket || { fixed: [], excluded: [] },
                    customFilters: state.customFilters || [],
                    regressionSettings: state.regressionSettings || {},
                    manualFilters: state.manualFilters || [],
                    foundationFilters: _ff   // UUID→filter_key 변환 테이블
                };

                localStorage.setItem('generated_filter_combos', JSON.stringify({
                    timestamp: new Date().getTime(),
                    total_pool: data.totalValid,
                    combinations: combos,
                    target_round: tr,
                    filter_snapshot: filter_snapshot
                }));

                const btn = document.getElementById('btnGenerateCombos');
                if (btn) btn.innerHTML = '<span class="material-symbols-outlined" style="font-size:16px;">check_circle</span>조합 생성 완료!';

                window.location.href = 'combination_generator.html';
            }
        };
    }

    // ──────────────────────────────────────────────────
    // 필터 수집 (메인 함수)
    // ──────────────────────────────────────────────────
    // ignoreEnabled=true: 토글 OFF 필터도 포함 (배지 계산용)
    function gatherActiveFilters(ignoreEnabled = false) {
        const filters = {};

        // FilterDashboard 없으면 빈 필터 반환 (워커는 통과만 함)
        if (!window.FilterDashboard || !window.FilterDashboard.state) {
            return filters;
        }

        const S = window.FilterDashboard.state;

        /**
         * 특정 filter_key가 enabled인지 확인 후 settings 반환
         * ignoreEnabled=true 시 enabled 체크 생략 (배지 독립 카운팅용)
         * disabled이거나 없으면 null 반환
         */
        function getSetting(filterKey) {
            const def = (S.foundationFilters || []).find(d => d.filter_key === filterKey);
            if (!def) return null;
            const us = S.userSettings[def.id];
            if (!us) return null;
            if (!ignoreEnabled && !us.enabled) return null;
            return us.settings || {};
        }

        // ── 바스켓: 고정수 / 제외수 ──────────────────────
        filters.fixed = (S.basket && S.basket.fixed) ? [...S.basket.fixed] : [];
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
        const tailSumSet = getSetting('tail_sum');
        if (tailSumSet) {
            filters.tailSumRange = {
                min: tailSumSet.min !== undefined ? tailSumSet.min : 0,
                max: tailSumSet.max !== undefined ? tailSumSet.max : 45
            };
            // [수정] 키 이름 불일치 수정: "excluded" OR "excludedSums" 둘 다 지원
            const excl = [...(tailSumSet.excludedSums || tailSumSet.excluded || [])];
            // recent10FilterActive가 켜져 있을 때만 최근 끝수합 자동 제외
            if (tailSumSet.recent10FilterActive && S.allDraws && S.allDraws.length > 0) {
                const restAuto = tailSumSet.restoredAutoSums || [];
                const latestDraw = S.allDraws[0];
                let latestTailSum = latestDraw ? latestDraw.tail_sum : null;
                if ((latestTailSum === undefined || latestTailSum === null) && latestDraw && latestDraw.numbers) {
                    latestTailSum = latestDraw.numbers.reduce((a, b) => a + (b % 10), 0);
                }
                // restAuto(복원된 값)에 없는 경우에만 제외 목록에 추가
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
            const selected = oddEvenSet.selectedRatios || [];
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
            const selected = highLowSet.selectedRatios || [];
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

        // ── 끝수 패턴 (end_digit_0_count ~ end_digit_9_count 개별 키) ──────
        {
            const tailDigitRanges = {};
            for (let _d = 0; _d <= 9; _d++) {
                const _ds = getSetting(`end_digit_${_d}_count`);
                if (!_ds) continue;
                if (_ds.min !== undefined && _ds.max !== undefined) {
                    tailDigitRanges[_d] = { min: _ds.min, max: _ds.max };
                } else if (_ds.selectedValues && _ds.selectedValues.length > 0) {
                    // discrete_select 전용 설정: selectedValues → min/max 변환
                    tailDigitRanges[_d] = {
                        min: Math.min(..._ds.selectedValues),
                        max: Math.max(..._ds.selectedValues)
                    };
                }
            }
            if (Object.keys(tailDigitRanges).length > 0) {
                filters.tailDigitRanges = tailDigitRanges;
            }
        }

        // ── 소수 ──────────────────────────────────────────
        const primeSet = getSetting('prime_number_patterns');
        if (primeSet) {
            filters.primeFilter = {
                selectedCounts: primeSet.selectedCounts || [],
                excludedPrimes: primeSet.excludedPrimes || []
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
                activeCounts: twinSet.activeCounts || twinSet.selectedCounts || [],
                selectedNumbers: twinSet.selectedNumbers || twinSet.excludedTwins || []
            };
        }

        // ── 합성수 ────────────────────────────────────────
        const compositeSet = getSetting('composite_count');
        if (compositeSet) {
            filters.compositeFilter = {
                selectedValues: compositeSet.selectedCounts || compositeSet.selectedValues || [],
                excludedComposites: compositeSet.excludedComposites || []
            };
        }

        // ── 연번 ──────────────────────────────────────────
        const consecSet = getSetting('consecutive_count');
        if (consecSet) {
            filters.consecutiveFilter = {
                selectedCounts: consecSet.selectedCounts || [],
                runFilters: consecSet.runFilters || {}
            };
        }

        // ── 번호대 + 엔트로피 ────────────────────────────
        const numRangeSet = getSetting('number_range_patterns');
        if (numRangeSet && numRangeSet.ranges) {
            const { entropy, ...rangeParts } = numRangeSet.ranges;
            filters.numberRangeFilter = {
                ranges: rangeParts,
                entropy: entropy || null,
                excludedPatterns: numRangeSet.autoExcludeRecent5 ? (numRangeSet.excludedPatterns || []) : []
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

        // ── 배수 패턴 (multiple_3_count 등 개별 키) ─────────────────────────
        {
            const _multipleKeyMap = [
                ['3배수',  'multiple_3_count'],
                ['4배수',  'multiple_4_count'],
                ['5배수',  'multiple_5_count'],
                ['7배수',  'multiple_7_count'],
                ['8배수',  'multiple_8_count'],
                ['3·4배수','multiple_3_4_count'],
                ['3·5배수','multiple_3_5_count'],
                ['4·5배수','multiple_4_5_count'],
                ['배수외', 'no_multiple_count']
            ];
            const _multipleRanges = {};
            for (const [type, key] of _multipleKeyMap) {
                const _ms = getSetting(key);
                if (!_ms) continue;
                if (_ms.min !== undefined && _ms.max !== undefined) {
                    _multipleRanges[type] = { min: _ms.min, max: _ms.max };
                } else if (_ms.selectedValues && _ms.selectedValues.length > 0) {
                    // discrete_select 전용 설정: selectedValues → min/max 변환
                    _multipleRanges[type] = {
                        min: Math.min(..._ms.selectedValues),
                        max: Math.max(..._ms.selectedValues)
                    };
                }
            }
            if (Object.keys(_multipleRanges).length > 0) {
                filters.multipleFilter = { filters: _multipleRanges };
            }
        }

        // ── 이월수 ────────────────────────────────────────
        const carryoverSet = getSetting('carryover_count');

        if (carryoverSet) {
            const prevNums = (S.dynamicTargets && S.dynamicTargets['carryover_count']) || [];
            const prevBonusNums = (S.dynamicTargets && S.dynamicTargets['carryover_bonus_count']) || [];
            filters.carryoverFilter = {
                // 이월수(보너스 제외): carryover_count 필터 설정
                selectedCounts: (carryoverSet && carryoverSet.selectedCounts) || [],
                carryoverNums: prevNums,
                // 이월수(보너스 포함): carryover_count의 selectedBonusIncludedCounts 사용
                selectedBonusCounts: (carryoverSet && carryoverSet.selectedBonusIncludedCounts) || [],
                carryoverBonusNums: prevBonusNums
            };
        }

        // ── 이웃수 ────────────────────────────────────────
        const neighborSet = getSetting('neighbor_number_patterns');
        if (neighborSet) {
            const neighborNums = (S.dynamicTargets && S.dynamicTargets['neighbor_number_patterns']) || [];
            // [수정] selectedValues/selectedCounts가 없고 min/max 형식인 경우 범위 배열로 변환
            let selectedValues = neighborSet.selectedValues || neighborSet.selectedCounts || null;
            if ((!selectedValues || selectedValues.length === 0) && neighborSet.max !== undefined) {
                const minV = neighborSet.min !== undefined ? Math.max(0, parseInt(neighborSet.min)) : 0;
                const maxV = Math.min(6, parseInt(neighborSet.max));
                selectedValues = [];
                for (let i = minV; i <= maxV; i++) selectedValues.push(i);
            }
            filters.neighborFilter = {
                selectedValues: (selectedValues && selectedValues.length > 0) ? selectedValues : null,
                neighborNums
            };
        }

        // ── Hot/Cold 5 / 10 / 15 / 20 ───────────────────
        const CRITERIA = {
            5: { hot: 2, neutralMin: 1, neutralMax: 1 },
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
                    hotRange: [parseInt(pf.hotMin ?? 0), parseInt(pf.hotMax ?? 6)],
                    warmRange: [parseInt(pf.neutralMin ?? 0), parseInt(pf.neutralMax ?? 6)],
                    coldRange: [parseInt(pf.coldMin ?? 0), parseInt(pf.coldMax ?? 6)]
                };
            }

            filters[`hotCold${period}`] = {
                hotNums,
                warmNums,
                coldNums,
                hotRange: Array.isArray(effVals.hotRange) ? effVals.hotRange : [0, 6],
                warmRange: Array.isArray(effVals.warmRange) ? effVals.warmRange : [0, 6],
                coldRange: Array.isArray(effVals.coldRange) ? effVals.coldRange : [0, 6]
            };
        }

        // ── 미출현 기간 ────────────────────────────────────
        const missingPeriodSet = getSetting('missing_period');
        if (missingPeriodSet && S.allDraws && S.allDraws.length > 0) {
            const ranges = missingPeriodSet.ranges || {};
            // [수정] 그룹 정의 (r1~r4): missing.html의 고정 통계 범위와 일치시킴
            const GROUP_DEFS = [
                { key: 'r1', minM: 1, maxM: 5 },
                { key: 'r2', minM: 6, maxM: 10 },
                { key: 'r3', minM: 11, maxM: 15 },
                { key: 'r4', minM: 16, maxM: 999 }
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

                // [수정] r1Min/Max 등은 해당 기간 그룹에 포함된 '번호 개수'의 최소/최대값임
                const minCount = ranges[`${gd.key}Min`] !== undefined ? parseInt(ranges[`${gd.key}Min`]) : 0;
                const maxCount = ranges[`${gd.key}Max`] !== undefined ? parseInt(ranges[`${gd.key}Max`]) : 6;
                // [버그수정] 그룹 실제 크기 < 설정 min → 달성 불가 → 실제 크기로 cap (영구 count=0 방지)
                const effectiveMin = Math.min(minCount, nums.length);
                if (effectiveMin < minCount) {
                    console.warn(`[미출현기간] ${gd.key} 그룹 실제 크기(${nums.length}) < 설정 min(${minCount}). min을 ${effectiveMin}로 자동 보정.`);
                }
                mpGroups.push({ nums, min: effectiveMin, max: maxCount });
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
                    min: g.minCount !== undefined ? g.minCount : 0,
                    max: g.maxCount !== undefined ? g.maxCount : 6
                }))
                .filter(g => g.nums.length > 0);
            if (mcGroups.length > 0) filters.missingCustomFilter = mcGroups;
        }

        // ── 커스텀 분석 필터 (ai_custom_analyses) ────────
        if (S.customFilters && S.customFilters.length > 0 && window.LOTTO_CONSTANTS && window.LOTTO_CONSTANTS.calculateCustomTargets) {
            const cfArr = [];
            S.customFilters.forEach(cf => {
                // filter_config.enabled 우선, 없으면 cf.enabled (최상위) 확인
                const fc = (typeof cf.filter_config === 'string'
                    ? JSON.parse(cf.filter_config || '{}')
                    : (cf.filter_config || {}));
                const isEnabled = fc.enabled !== undefined ? fc.enabled : (cf.enabled === true);
                if (!isEnabled) return;

                try {
                    const targetNums = window.LOTTO_CONSTANTS.calculateCustomTargets(cf, S.allDraws, { isPrediction: true });
                    if (!targetNums || targetNums.length === 0) return;

                    // min/max 우선순위:
                    //   1) rules.minCount / rules.maxCount
                    //   2) cf.min_count / cf.max_count
                    //   3) filter_config.min / filter_config.max  ← 신규 (manual/직접입력형)
                    //   4) 기본값 0 / 6
                    let rules = {};
                    try { rules = typeof cf.rules === 'string' ? JSON.parse(cf.rules || '{}') : (cf.rules || {}); } catch (_) { }
                    const minCount = rules.minCount !== undefined ? rules.minCount
                        : (cf.min_count !== undefined ? cf.min_count
                            : (fc.min !== undefined ? fc.min : 0));
                    const maxCount = rules.maxCount !== undefined ? rules.maxCount
                        : (cf.max_count !== undefined ? cf.max_count
                            : (fc.max !== undefined ? fc.max : 6));

                    cfArr.push({
                        id: cf.id,
                        title: cf.title,
                        targetNums: targetNums.filter(n => n >= 1 && n <= 45),
                        min: parseInt(minCount),
                        max: parseInt(maxCount)
                    });
                } catch (err) {
                    console.warn(`[filterCounter] 커스텀 필터 오류: ${cf.title}`, err);
                }
            });
            if (cfArr.length > 0) filters.customAnalysisFilters = cfArr;
        }

        // ── 회귀 분석 (steps 2~200) ───────────────────────
        if (S.regressionEnabled !== false && S.regressionSettings && S.allDraws && S.allDraws.length > 0) {
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
                    min: parseInt(rs.min !== undefined ? rs.min : 0),
                    max: parseInt(rs.max !== undefined ? rs.max : 6)
                });
            }
            if (regArr.length > 0) filters.regressionFilters = regArr;
        }

        // ── 수동 필터 (manual_filters 테이블) ─────────────────
        if (S.manualFilters && S.manualFilters.length > 0) {
            const mfArr = S.manualFilters
                .filter(mf => mf.enabled !== false)
                .map(mf => ({
                    id: mf.id,
                    title: mf.title || '수동필터',
                    selectedNums: (mf.selected_numbers || []).map(Number),
                    min: mf.min_match !== undefined ? mf.min_match : 1,
                    max: mf.max_match !== undefined ? mf.max_match : 6
                }));
            if (mfArr.length > 0) filters.manualFilters = mfArr;
        }

        return filters;
    }

    // ──────────────────────────────────────────────────
    // 워커에 전송
    // ──────────────────────────────────────────────────
    function sendToWorker(filters) {
        if (!isWorkerReady || isGenerating) return;
        if (isCounting) {
            pendingFilters = filters;
            return;
        }

        isCounting = true;
        const counterEl = document.getElementById('neonCounter');
        if (counterEl) counterEl.classList.add('opacity-50', 'animate-pulse');
        worker.postMessage({ type: 'COUNT', filters });

        // [fix-319] worker hang 방지 — COUNT_HANG_TIMEOUT_MS 후에도 응답 없으면 강제 reset
        if (_countTimeoutId) clearTimeout(_countTimeoutId);
        _countTimeoutId = setTimeout(() => {
            if (isCounting) {
                console.warn(`[counter] worker hang detected (${COUNT_HANG_TIMEOUT_MS}ms timeout) — force reset + retrigger`);
                isCounting = false;
                if (counterEl) counterEl.classList.remove('opacity-50', 'animate-pulse');
                if (pendingFilters) {
                    const f = pendingFilters; pendingFilters = null;
                    sendToWorker(f);
                } else {
                    sendToWorker(gatherActiveFilters());
                }
            }
        }, COUNT_HANG_TIMEOUT_MS);
    }

    function triggerCount() {
        sendToWorker(gatherActiveFilters());
    }

    // ──────────────────────────────────────────────────
    // 진단 결과 표시
    // ──────────────────────────────────────────────────
    // ──────────────────────────────────────────────────
    // 진단 결과 표시 (프리미엄 UI + 페이지 순서 정렬)
    // ──────────────────────────────────────────────────
    function showDiagnoseResult(result) {
        if (!result) { alert('진단 실패: 조합 데이터가 없습니다.'); return; }

        const { pass, total, failMap } = result;

        // [추가] 페이지에 표시된 필터 순서 정의 (checkFilters / buildStages 순서와 일치)
        // 주의: a.name.includes(p) 매칭 사용 → 실제 failMap 키에 포함되는 문자열이어야 함
        // ※ 구체적인 이름(예: '끝수합')이 포괄적인 이름(예: '끝수')보다 먼저 위치해야 findIndex가 올바름
        const PAGE_ORDER = [
            '바스켓 고정수', '바스켓 제외수',
            '총합', '총합 제외값',
            '끝수합', '끝수합 제외값',
            'AC값', 'AC값 제외',
            '홀짝 패턴', '홀짝 제외',
            '고저 패턴', '고저 제외',
            '연번',
            '이웃수',
            '이월수',
            '소수', '합성수', '삼각수', '제곱수', '동형수',
            '끝수',
            '배수',
            '번호대', '엔트로피', '9궁', '로또용지',
            '핫콜드', '미출현기간', '미출현커스텀',
            '회귀분석', '커스텀분석', '수동필터'
        ];

        // failMap(배열)을 페이지 순서에 맞춰 정렬
        const sortedFail = [...failMap].sort((a, b) => {
            const idxA = PAGE_ORDER.findIndex(p => a.name.includes(p));
            const idxB = PAGE_ORDER.findIndex(p => b.name.includes(p));
            const finalA = idxA === -1 ? 999 : idxA;
            const finalB = idxB === -1 ? 999 : idxB;
            return finalA - finalB; // 그룹 순서대로만 정렬 (워커에서 온 순서 유지)
        });

        // 탈락 조합이 0개인 항목도 모두 보여주기로 결정 (사용자 요청)
        const displayItems = sortedFail;

        let html = `
<div id="diagnoseResultOverlay" class="fade-in" style="position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(2, 6, 23, 0.85);backdrop-filter:blur(10px);z-index:99999;display:flex;align-items:center;justify-content:center;font-family:'Pretendard', sans-serif;">
  <div style="background:linear-gradient(145deg, #1e293b, #0f172a);border:1px solid rgba(255,255,255,0.1);border-radius:24px;padding:32px;max-width:650px;width:95%;max-height:85vh;overflow-y:auto;color:#fff;box-shadow:0 25px 50px -12px rgba(0,0,0,0.5);">
    
    <!-- Header -->
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;">
      <div style="display:flex;items-center;gap:12px;">
        <span class="material-symbols-outlined text-rose-500" style="font-size:28px;">analytics</span>
        <h2 style="margin:0;font-size:22px;font-weight:900;letter-spacing:-0.5px;background:linear-gradient(to right, #fff, #94a3b8);-webkit-background-clip:text;-webkit-text-transparent:true;">필터 정밀 진단 리포트</h2>
      </div>
      <button onclick="document.getElementById('diagnoseResultOverlay').remove()" 
        class="hover:bg-slate-800 transition-colors w-10 h-10 flex items-center justify-center rounded-full border border-slate-700">
        <span class="material-symbols-outlined" style="font-size:20px;color:#94a3b8;">close</span>
      </button>
    </div>

    <!-- Summary Box -->
    <div style="background:rgba(30, 41, 59, 0.5);border:1px solid rgba(255,255,255,0.05);border-radius:20px;padding:24px;margin-bottom:24px;display:flex;align-items:center;justify-content:around;gap:20px;">
      <div style="flex:1;text-align:center;">
        <div style="font-size:12px;color:#64748b;font-weight:700;text-transform:uppercase;margin-bottom:8px;">최종 생존 조합</div>
        <div style="font-size:36px;font-weight:900;color:${pass === 0 ? '#f43f5e' : '#10b981'};text-shadow:0 0 20px ${pass === 0 ? 'rgba(244,63,94,0.3)' : 'rgba(16,185,129,0.3)'};">${pass.toLocaleString()}<span style="font-size:16px;margin-left:2px;">개</span></div>
        <div style="font-size:12px;color:#475569;margin-top:4px;">전체 ${total.toLocaleString()}개 대비 ${(pass / total * 100).toFixed(4)}%</div>
      </div>
      <div style="width:1px;height:40px;background:rgba(255,255,255,0.1);"></div>
      <div style="flex:1;text-align:center;">
        <div style="font-size:12px;color:#64748b;font-weight:700;text-transform:uppercase;margin-bottom:8px;">필터 엄격도</div>
        <div style="font-size:24px;font-weight:900;color:#94a3b8;">${pass === 0 ? '매우 높음' : (pass < 1000 ? '높음' : '적절')}</div>
      </div>
    </div>

    <!-- Detail List -->
    <div style="margin-bottom:12px;display:flex;justify-content:space-between;align-items:center;">
        <span style="font-size:14px;color:#94a3b8;font-weight:700;">📊 필터별 탈락 분석 <span style="font-size:11px;font-weight:normal;color:#475569;">(페이지 순서순 정렬)</span></span>
        <span style="font-size:11px;color:#475569;">총 ${displayItems.length}개 항목 표시</span>
    </div>

    <div style="display:flex;flex-direction:column;gap:10px;">`;

        const totalFails = total - pass;
        displayItems.forEach((item, idx) => {
            const pctOfTotal = (item.count / total * 100).toFixed(1);
            const pctOfFail = totalFails > 0 ? (item.count / totalFails * 100).toFixed(1) : 0;

            // 프리미엄 바 컬러: 상단 3개는 로즈, 나머지는 블루/인디고
            const color = idx < 3 ? '#f43f5e' : '#6366f1';
            const bgOpacity = idx < 3 ? '0.1' : '0.05';

            html += `
      <div style="background:rgba(30, 41, 59, 0.3);border:1px solid rgba(255,255,255,0.03);border-radius:14px;padding:14px 18px;transition:all 0.2s hover:transform:translateX(4px);">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
          <div style="display:flex;align-items:center;gap:10px;">
            <span style="color:#475569;font-weight:900;font-size:11px;min-width:20px;">${String(idx + 1).padStart(2, '0')}</span>
            <span style="color:#f1f5f9;font-weight:700;font-size:14px;">${item.name}</span>
          </div>
          <div style="text-align:right;">
            <div style="font-size:14px;font-weight:900;color:${color};">${item.count.toLocaleString()}<span style="font-size:10px;margin-left:2px;font-weight:normal;color:#64748b;">개 탈락</span></div>
            <div style="font-size:10px;color:#475569;">비중: ${pctOfTotal}%</div>
          </div>
        </div>
        <div style="background:rgba(255,255,255,0.05);border-radius:100px;height:6px;overflow:hidden;position:relative;">
          <div style="background:linear-gradient(to right, ${color}, ${color}dd);height:100%;width:${pctOfTotal}%;border-radius:100px;box-shadow:0 0 10px ${color}44;"></div>
        </div>
      </div>`;
        });

        if (displayItems.length === 0) {
            html += `<div style="text-align:center;padding:40px;color:#475569;">활성화된 필터 중 탈락시킨 조합이 없습니다.</div>`;
        }

        html += `
    </div>

    <!-- Recommendation -->
    <div style="margin-top:28px;padding:18px;background:${pass === 0 ? 'rgba(244,63,94,0.05)' : 'rgba(16,185,129,0.05)'};border:1px solid ${pass === 0 ? 'rgba(244,63,94,0.1)' : 'rgba(16,185,129,0.1)'};border-radius:18px;">
      <div style="display:flex;gap:12px;">
        <span class="material-symbols-outlined" style="color:${pass === 0 ? '#fb7185' : '#4ade80'};">${pass === 0 ? 'warning' : 'info'}</span>
        <div style="font-size:13px;line-height:1.6;color:#94a3b8;">
          <strong style="color:${pass === 0 ? '#fda4af' : '#86efac'};display:block;margin-bottom:4px;">${pass === 0 ? '분석 제안' : '분석 최적화'}</strong>
          ${pass === 0 ? '현재 필터 조건이 너무 까다로워 통과하는 조합이 없습니다. 상위 탈락 필터인 <b>' + (displayItems[0]?.name || '필터') + '</b> 등을 완화해 보세요.' : pass.toLocaleString() + '개의 조합이 준비되었습니다. 이 조합들로 필터 최적화가 완료되었습니다.'}
        </div>
      </div>
    </div>

  </div>
</div>`;

        const overlay = document.createElement('div');
        overlay.id = 'diagnoseResultOverlayWrapper';
        overlay.innerHTML = html;
        document.body.appendChild(overlay);

        // 간단한 페이드인 효과
        setTimeout(() => {
            const target = document.getElementById('diagnoseResultOverlay');
            if (target) target.style.opacity = '1';
        }, 10);
    }

    // ──────────────────────────────────────────────────
    // 단계별 카운팅 결과 — 페이지 모달 + 한 줄씩 순서대로 표시
    // ──────────────────────────────────────────────────
    function printStepCount(result) {
        if (!result) { alert('단계별 분석 실패: 조합 데이터가 없습니다.'); return; }

        const { steps, total, pass } = result;
        const INTERVAL = 80; // ms — 한 줄씩 추가되는 간격

        // ── 모달 오버레이 생성 ─────────────────────────
        const overlay = document.createElement('div');
        overlay.id = 'stepCountOverlay';
        overlay.style.cssText = [
            'position:fixed', 'inset:0', 'background:rgba(0,0,0,0.75)',
            'z-index:99999', 'display:flex', 'align-items:center', 'justify-content:center',
            'font-family:ui-monospace,SFMono-Regular,Menlo,monospace'
        ].join(';');

        overlay.innerHTML = `
<div id="stepCountBox" style="background:#0f172a;border-radius:18px;padding:28px 32px;
  width:min(860px,95vw);max-height:88vh;display:flex;flex-direction:column;
  box-shadow:0 30px 80px rgba(0,0,0,0.6);border:1px solid #1e293b;">

  <!-- 헤더 -->
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:18px;flex-shrink:0;">
    <div>
      <div style="font-size:17px;font-weight:900;color:#c4b5fd;letter-spacing:-0.3px;">
        🔢 필터 단계별 조합 카운팅
      </div>
      <div style="font-size:12px;color:#475569;margin-top:3px;">
        전체 <span style="color:#94a3b8;font-weight:700;">${total.toLocaleString()}</span>개 →
        필터 적용 순서대로 탈락 현황
      </div>
    </div>
    <button onclick="document.getElementById('stepCountOverlay').remove()"
      style="background:#1e293b;border:none;color:#94a3b8;border-radius:10px;
             padding:8px 16px;cursor:pointer;font-size:13px;font-weight:700;
             transition:background 0.2s;" onmouseover="this.style.background='#334155'"
      onmouseout="this.style.background='#1e293b'">✕ 닫기</button>
  </div>

  <!-- 시작 행 -->
  <div style="background:#1e293b;border-radius:10px;padding:10px 14px;
    display:flex;justify-content:space-between;align-items:center;
    margin-bottom:6px;flex-shrink:0;">
    <span style="color:#64748b;font-size:12px;font-weight:700;">시작</span>
    <span style="color:#64748b;font-size:13px;">
      남은 조합 <span style="color:#94a3b8;font-weight:900;font-size:15px;">
        ${total.toLocaleString()}
      </span> 개
    </span>
  </div>

  <!-- 단계 목록 (스크롤) -->
  <div id="stepCountList" style="overflow-y:auto;flex:1;display:flex;
    flex-direction:column;gap:4px;padding-right:4px;min-height:0;"></div>

  <!-- 푸터 (처음엔 숨김) -->
  <div id="stepCountFooter" style="display:none;margin-top:12px;flex-shrink:0;"></div>
</div>`;

        document.body.appendChild(overlay);

        const list = document.getElementById('stepCountList');
        const footer = document.getElementById('stepCountFooter');

        // ── 활성 필터 없음 ───────────────────────────
        if (steps.length === 0) {
            list.innerHTML = `<div style="color:#475569;font-size:13px;padding:16px;text-align:center;">
              활성화된 필터가 없습니다. 전체 ${total.toLocaleString()}개 통과.
            </div>`;
            return;
        }

        // ── 각 단계를 INTERVAL ms 간격으로 하나씩 추가 ─
        steps.forEach((s, i) => {
            setTimeout(() => {
                const eliminated = s.eliminated;
                const pct = (eliminated / total * 100).toFixed(2);
                const survivorsPct = (s.survivors / total * 100).toFixed(1);
                const barW = Math.max(1, Math.round(s.survivors / total * 100));

                // 색상 결정
                let nameColor, countColor, bg, borderColor;
                if (s.survivors === 0) {
                    bg = '#450a0a'; nameColor = '#fca5a5'; countColor = '#f87171'; borderColor = '#7f1d1d';
                } else if (eliminated === 0) {
                    bg = '#0f172a'; nameColor = '#374151'; countColor = '#4b5563'; borderColor = '#1e293b';
                } else if (eliminated > total * 0.15) {
                    bg = '#1c1008'; nameColor = '#fdba74'; countColor = '#fb923c'; borderColor = '#431407';
                } else if (eliminated > total * 0.05) {
                    bg = '#1a1205'; nameColor = '#fde68a'; countColor = '#fbbf24'; borderColor = '#422006';
                } else {
                    bg = '#0f172a'; nameColor = '#94a3b8'; countColor = '#cbd5e1'; borderColor = '#1e293b';
                }

                const row = document.createElement('div');
                row.style.cssText = `background:${bg};border:1px solid ${borderColor};
                  border-radius:8px;padding:8px 12px;animation:fadeInRow 0.2s ease;`;

                row.innerHTML = `
  <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;">
    <span style="color:${nameColor};font-size:11px;font-weight:700;white-space:nowrap;min-width:0;flex-shrink:0;">
      <span style="color:#4b5563;">[${i + 1}]</span> ${s.name}
    </span>
    <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;justify-content:flex-end;">
      <span style="color:${countColor};font-size:13px;font-weight:900;white-space:nowrap;">
        ${s.survivors === 0 ? '0' : s.survivors.toLocaleString()} 개
      </span>
      ${eliminated > 0 ? `<span style="color:#64748b;font-size:11px;white-space:nowrap;">
        탈락 <span style="color:${countColor};">-${eliminated.toLocaleString()}</span>
        (${pct}%)
      </span>` : `<span style="color:#374151;font-size:11px;">탈락 없음</span>`}
    </div>
  </div>
  ${eliminated > 0 ? `
  <div style="margin-top:5px;background:#1e293b;border-radius:3px;height:3px;overflow:hidden;">
    <div style="background:${countColor};height:100%;width:${barW}%;opacity:0.6;transition:width 0.3s;"></div>
  </div>` : ''}`;

                list.appendChild(row);
                // 자동 스크롤 (항상 최신 항목이 보이도록)
                list.scrollTop = list.scrollHeight;

                // ── 마지막 단계 → 푸터 표시 ───────────
                if (i === steps.length - 1) {
                    setTimeout(() => {
                        footer.style.display = 'block';
                        footer.innerHTML = pass === 0
                            ? `<div style="background:#450a0a;border:1px solid #7f1d1d;border-radius:10px;
                                padding:14px 18px;color:#fca5a5;font-size:14px;font-weight:900;text-align:center;">
                                ⚠️ 최종 통과 조합: 0개 — 필터를 일부 완화해 주세요
                              </div>`
                            : `<div style="background:#052e16;border:1px solid #14532d;border-radius:10px;
                                padding:14px 18px;color:#86efac;font-size:14px;font-weight:900;text-align:center;">
                                ✅ 최종 통과 조합: ${pass.toLocaleString()}개
                                <span style="font-size:12px;color:#4ade80;font-weight:500;">
                                  (전체의 ${(pass / total * 100).toFixed(4)}%)
                                </span>
                              </div>`;
                    }, INTERVAL);
                }
            }, (i + 1) * INTERVAL);
        });
    }

    // ──────────────────────────────────────────────────
    // 단계별 카운팅 실행 (외부 호출용)
    // ──────────────────────────────────────────────────
    window.stepCountCombinations = function () {
        if (!isWorkerReady) { alert('조합 엔진이 준비 중입니다. 잠시 후 다시 시도해주세요.'); return; }
        const btn = document.getElementById('btnStepCount');
        if (btn) btn.innerHTML = '<span class="material-symbols-outlined animate-spin" style="font-size:16px;">sync</span>계산 중...';
        worker.postMessage({ type: 'STEPCNT', filters: gatherActiveFilters() });
        // 버튼 원복 (최대 40초 후)
        setTimeout(() => {
            if (btn) btn.innerHTML = '<span class="material-symbols-outlined" style="font-size:16px;">filter_list</span>단계별 분석';
        }, 40000);
    };

    // ──────────────────────────────────────────────────
    // 진단 실행 (외부 호출용)
    // ──────────────────────────────────────────────────
    window.diagnoseCombinations = function () {
        if (!isWorkerReady) { alert('조합 엔진이 준비 중입니다. 잠시 후 다시 시도해주세요.'); return; }
        const btn = document.getElementById('btnDiagnose');
        if (btn) btn.innerHTML = '<span class="material-symbols-outlined animate-spin" style="font-size:16px;">sync</span>진단 중...';
        worker.postMessage({ type: 'DIAGNOSE', filters: gatherActiveFilters() });
        setTimeout(() => { if (btn) btn.innerHTML = '<span class="material-symbols-outlined" style="font-size:16px;">bug_report</span>필터 진단'; }, 15000);
    };

    // ──────────────────────────────────────────────────
    // 조합 생성 버튼
    // ──────────────────────────────────────────────────
    window.generateFinalCombinations = function () {
        if (!isWorkerReady) {
            alert('조합 엔진이 준비 중입니다. 잠시만 기다려주세요.');
            return;
        }

        // DOM 값 대신 워커 전수조사 결과 사용
        if (lastExactCount === -1) {
            alert('조합 수 계산이 진행 중입니다. 잠시 후 다시 시도해주세요.');
            return;
        }

        const currentCount = lastExactCount;

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
        if (btn) btn.innerHTML = '<span class="material-symbols-outlined animate-spin" style="font-size:16px;">sync</span>추출 중...';

        worker.postMessage({ type: 'GENERATE', filters: gatherActiveFilters() });
    };

    // ──────────────────────────────────────────────────
    // 이벤트 리스너 & 초기화
    // ──────────────────────────────────────────────────

    // [추가] FilterDashboard.renderUI 훅을 걸고, 이미 걸려있으면 건너뜀
    function hookRenderUI() {
        const fd = window.FilterDashboard;
        if (!fd || !fd.renderUI || fd.__countHooked__) return;
        const orig = fd.renderUI.bind(fd);
        fd.renderUI = function () {
            orig();
            if (isWorkerReady) setTimeout(triggerCount, 300);
        };
        fd.__countHooked__ = true;
    }

    document.addEventListener('DOMContentLoaded', () => {
        initWorker();

        // 필터 변경 시 자동 리카운팅
        document.body.addEventListener('change', (e) => {
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') triggerCount();
        });
        document.body.addEventListener('click', (e) => {
            if (e.target.closest('button:not(#btnGenerateCombos)')) setTimeout(triggerCount, 100);
        });

        // 최초 훅 연결
        hookRenderUI();
    });

    // [추가] storage 변경 감지: FilterDashboard가 재초기화될 때마다 훅을 다시 연결하고 카운팅
    window.addEventListener('storage', (e) => {
        // FilterDashboard가 감지하는 키에 변경이 생겼을 때
        setTimeout(() => {
            // 재초기화 후 새로 생성된 renderUI에 훅 재연결
            const fd = window.FilterDashboard;
            if (fd) fd.__countHooked__ = false; // 강제 초기화 후 재훅
            hookRenderUI();
            if (isWorkerReady) setTimeout(triggerCount, 500);
        }, 800); // FilterDashboard 재초기화 완료 대기
    });

    // [추가] FilterDashboard 늦게 초기화되는 경우 대비: 주기적으로 훅 재연결 시도 (최대 10초)
    let hookRetryCount = 0;
    const hookRetryInterval = setInterval(() => {
        hookRenderUI();
        hookRetryCount++;
        if (hookRetryCount >= 20) clearInterval(hookRetryInterval); // 10초 후 중단
    }, 500);

    // FilterDashboard가 늦게 로드되는 경우를 위한 추가 훅
    window.addEventListener('load', () => {
        hookRenderUI();
        if (isWorkerReady) setTimeout(triggerCount, 500);
    });

})();
