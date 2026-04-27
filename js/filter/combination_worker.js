/**
 * js/filter/combination_worker.js
 * 814만 로또 조합 100% 전수조사 카운팅 및 전체 추출 워커 (샘플링 없음)
 * v2.0 — 모든 필터(50+개) 완전 구현
 */

'use strict';

// ──────────────────────────────────────────────────
// 1. 정적 LUT (Lookup Table) - 번호 속성 사전 계산
// ──────────────────────────────────────────────────
const PRIME_LUT = new Uint8Array(46); // 소수
const SQUARE_LUT = new Uint8Array(46); // 제곱수
const TRI_LUT = new Uint8Array(46); // 삼각수
const TWIN_LUT = new Uint8Array(46); // 쌍수(동형수: 11,22,33,44)
const COMPOS_LUT = new Uint8Array(46); // 합성수

[2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43].forEach(n => PRIME_LUT[n] = 1);
[1, 4, 9, 16, 25, 36].forEach(n => SQUARE_LUT[n] = 1);
[1, 3, 6, 10, 15, 21, 28, 36, 45].forEach(n => TRI_LUT[n] = 1);
[11, 22, 33, 44].forEach(n => TWIN_LUT[n] = 1);
[4, 6, 8, 9, 10, 12, 14, 15, 16, 18, 20, 21, 22, 24, 25, 26, 27, 28, 30, 32, 33, 34, 35, 36, 38, 39, 40, 42, 44, 45].forEach(n => COMPOS_LUT[n] = 1);

// 9궁 (마방진) - 5개씩 그룹
const PALACE_LUT = new Uint8Array(46); // 1~9궁 → 1~9 저장
for (let g = 0; g < 9; g++) {
    for (let i = 0; i < 5; i++) {
        const n = g * 5 + i + 1;
        if (n <= 45) PALACE_LUT[n] = g + 1;
    }
}

// 로또용지 가로(행) 및 세로(열) - 7개씩
// 가로: 가로1=[1..7], 가로2=[8..14], ..., 가로7=[43..45]
const GARO_LUT = new Uint8Array(46);  // 1~7 저장
const SERO_LUT = new Uint8Array(46);  // 1~7 저장
for (let n = 1; n <= 45; n++) {
    GARO_LUT[n] = Math.ceil(n / 7);       // 가로 행: 1~7
    SERO_LUT[n] = ((n - 1) % 7) + 1;     // 세로 열: 1~7
}

// 배수 LUT: 각 번호가 3/4/5/7/8의 배수인지
const M3_LUT = new Uint8Array(46);
const M4_LUT = new Uint8Array(46);
const M5_LUT = new Uint8Array(46);
const M7_LUT = new Uint8Array(46);
const M8_LUT = new Uint8Array(46);
const MUL7_SET = new Set([7, 14, 21, 28, 35, 42]);
const MUL8_SET = new Set([8, 16, 24, 32, 40]);
for (let n = 1; n <= 45; n++) {
    if (n % 3 === 0) M3_LUT[n] = 1;
    if (n % 4 === 0) M4_LUT[n] = 1;
    if (n % 5 === 0) M5_LUT[n] = 1;
    if (MUL7_SET.has(n)) M7_LUT[n] = 1;
    if (MUL8_SET.has(n)) M8_LUT[n] = 1;
}

// ──────────────────────────────────────────────────
// 2. 조합 저장소
// ──────────────────────────────────────────────────
let combinations = null;
const TOTAL_COMBINATIONS = 8145060;

function initCombinations() {
    if (combinations) return;
    combinations = new Uint8Array(TOTAL_COMBINATIONS * 6);
    let idx = 0;
    for (let a = 1; a <= 40; a++)
        for (let b = a + 1; b <= 41; b++)
            for (let c = b + 1; c <= 42; c++)
                for (let d = c + 1; d <= 43; d++)
                    for (let e = d + 1; e <= 44; e++)
                        for (let f = e + 1; f <= 45; f++) {
                            combinations[idx++] = a; combinations[idx++] = b;
                            combinations[idx++] = c; combinations[idx++] = d;
                            combinations[idx++] = e; combinations[idx++] = f;
                        }
    self.postMessage({ type: 'INIT_DONE', total: TOTAL_COMBINATIONS });
}

// ──────────────────────────────────────────────────
// 3. 필터 파라미터 파싱 (메인→워커 전달 후 1회 파싱)
// ──────────────────────────────────────────────────
function makeLUT(arr) {
    if (!arr || arr.length === 0) return null;
    const lut = new Uint8Array(46);
    for (let i = 0; i < arr.length; i++) { const v = arr[i]; if (v >= 1 && v <= 45) lut[v] = 1; }
    return lut;
}

function parseFilters(raw) {
    const F = {};

    // ── 기본 바스켓 ──
    F.fixedLUT = makeLUT(raw.fixed);
    F.fixedArr = raw.fixed || [];
    F.excludedLUT = makeLUT(raw.excluded);

    // ── 총합 ──
    if (raw.sumRange) {
        F.sumMin = raw.sumRange.min;
        F.sumMax = raw.sumRange.max;
        F.sumExcluded = raw.sumExcluded ? new Set(raw.sumExcluded) : null;
    }

    // ── 끝수합 ──
    if (raw.tailSumRange) {
        F.tailSumMin = raw.tailSumRange.min;
        F.tailSumMax = raw.tailSumRange.max;
        F.tailSumExcluded = raw.tailSumExcluded ? new Set(raw.tailSumExcluded) : null;
    }

    // ── AC값 ──
    if (raw.acRange) {
        F.acMin = raw.acRange.min;
        F.acMax = raw.acRange.max;
        F.acExcluded = raw.acExcluded ? new Set(raw.acExcluded) : null;
    }

    // ── 홀짝 패턴 ──
    if (raw.oddEvenPatterns && raw.oddEvenPatterns.length > 0) {
        F.oddEvenSet = new Set(raw.oddEvenPatterns);
        F.oddEvenExcluded = raw.oddEvenExcluded ? new Set(raw.oddEvenExcluded) : null;
    }

    // ── 고저 패턴 ──
    if (raw.highLowPatterns && raw.highLowPatterns.length > 0) {
        F.highLowSet = new Set(raw.highLowPatterns);
        F.highLowExcluded = raw.highLowExcluded ? new Set(raw.highLowExcluded) : null;
    }

    // ── 끝수 패턴 (0~9) ──
    if (raw.tailDigitRanges) {
        F.tailDigitRanges = raw.tailDigitRanges; // {0:{min,max}, 1:{min,max}, ...}
    }

    // ── 소수 ──
    if (raw.primeFilter) {
        F.primeCounts = raw.primeFilter.selectedCounts ? new Set(raw.primeFilter.selectedCounts) : null;
        F.primeExcludedLUT = makeLUT(raw.primeFilter.excludedPrimes);
    }

    // ── 제곱수 ──
    if (raw.squareFilter) {
        F.squareCounts = raw.squareFilter.selectedCounts ? new Set(raw.squareFilter.selectedCounts) : null;
        F.squareExcludedLUT = makeLUT(raw.squareFilter.excludedNumbers);
    }

    // ── 삼각수 ──
    if (raw.triangularFilter) {
        F.triCounts = raw.triangularFilter.selectedCounts ? new Set(raw.triangularFilter.selectedCounts) : null;
        F.triExcludedLUT = makeLUT(raw.triangularFilter.excludedNumbers);
    }

    // ── 쌍수(동형수) ──
    if (raw.twinFilter) {
        F.twinCounts = raw.twinFilter.activeCounts ? new Set(raw.twinFilter.activeCounts) : null;
        F.twinExcludedLUT = makeLUT(raw.twinFilter.selectedNumbers);
    }

    // ── 합성수 ──
    if (raw.compositeFilter) {
        // selectedCounts(분석페이지 저장) 또는 selectedValues(대시보드 기본값) 모두 수용
        const _compArr = raw.compositeFilter.selectedCounts || raw.compositeFilter.selectedValues;
        F.compositeCounts = (_compArr && _compArr.length > 0) ? new Set(_compArr) : null;
        F.compositeExcludedLUT = makeLUT(raw.compositeFilter.excludedComposites);
    }

    // ── 연번 ──
    if (raw.consecutiveFilter) {
        F.consecutiveCounts = raw.consecutiveFilter.selectedCounts ? new Set(raw.consecutiveFilter.selectedCounts) : null;
        F.runFilters = raw.consecutiveFilter.runFilters || {}; // {run3:{enabled,allowed}, run4:..., run5:..., run6:...}
    }

    // ── 번호대 (1_10, 11_20, 21_30, 31_40, 41_45) + 엔트로피 ──
    if (raw.numberRangeFilter) {
        F.numRanges = raw.numberRangeFilter.ranges || {};  // {1_10:{min,max}, ...}
        F.entropyRange = raw.numberRangeFilter.entropy || null; // {min, max}
    }

    // ── 9궁 (마방진) ──
    if (raw.magicSquareFilter) {
        F.palaceRanges = raw.magicSquareFilter.filters || {}; // {'1궁':{min,max}, ...}
    }

    // ── 로또용지 ──
    if (raw.lottoPaperFilter) {
        F.paperGroups = raw.lottoPaperFilter.groups || {}; // {가로1:{min,max}, ...세로7:...}
    }

    // ── 배수 패턴 ──
    if (raw.multipleFilter) {
        F.multipleRanges = raw.multipleFilter.filters || {}; // {'3배수':{min,max}, ...}
    }

    // ── 이월수 ──
    if (raw.carryoverFilter) {
        F.carryoverCounts = raw.carryoverFilter.selectedCounts ? new Set(raw.carryoverFilter.selectedCounts) : null;
        F.carryoverLUT = makeLUT(raw.carryoverFilter.carryoverNums);
        F.carryoverBonusCounts = raw.carryoverFilter.selectedBonusCounts ? new Set(raw.carryoverFilter.selectedBonusCounts) : null;
        F.carryoverBonusLUT = makeLUT(raw.carryoverFilter.carryoverBonusNums);
    }

    // ── 이웃수 ──
    if (raw.neighborFilter) {
        F.neighborCounts = raw.neighborFilter.selectedValues ? new Set(raw.neighborFilter.selectedValues) : null;
        F.neighborLUT = makeLUT(raw.neighborFilter.neighborNums);
    }

    // ── Hot/Cold (5/10/15/20) ──
    for (const period of [5, 10, 15, 20]) {
        const key = `hotCold${period}`;
        if (raw[key]) {
            const hc = raw[key];
            F[`hc${period}`] = {
                hotLUT: makeLUT(hc.hotNums),
                warmLUT: makeLUT(hc.warmNums),
                coldLUT: makeLUT(hc.coldNums),
                hotRange: hc.hotRange || [0, 6],
                warmRange: hc.warmRange || [0, 6],
                coldRange: hc.coldRange || [0, 6]
            };
        }
    }

    // ── 미출현 기간 ──
    if (raw.missingPeriodFilter) {
        F.missingPeriodGroups = raw.missingPeriodFilter; // [{nums:[], min, max}, ...]
        // makeLUT per group is too expensive; keep as arrays
    }

    // ── 미출현 커스텀 ──
    if (raw.missingCustomFilter && raw.missingCustomFilter.length > 0) {
        F.missingCustomGroups = raw.missingCustomFilter.map(g => ({
            lut: makeLUT(g.nums),
            min: g.min,
            max: g.max
        }));
    }

    // ── 커스텀 분석 필터 (ai_custom_analyses) ──
    if (raw.customAnalysisFilters && raw.customAnalysisFilters.length > 0) {
        F.customAnalysis = raw.customAnalysisFilters.map(cf => ({
            id: cf.id,
            lut: makeLUT(cf.targetNums),
            min: cf.min !== undefined ? cf.min : 0,
            max: cf.max !== undefined ? cf.max : 6,
            title: cf.title || '커스텀분석'   // 진단 시 필터명 표시용
        }));
    }

    // ── 회귀 분석 (steps 2~200) ──
    if (raw.regressionFilters && raw.regressionFilters.length > 0) {
        // regressionFilters = [{drawNums:[...], min, max}, ...]
        F.regressionFilters = raw.regressionFilters.map(rf => ({
            step: rf.step,
            lut: makeLUT(rf.drawNums),
            min: rf.min,
            max: rf.max
        }));
    }

    // ── 수동 필터 (manual_filters) ──
    if (raw.manualFilters && raw.manualFilters.length > 0) {
        F.manualFilters = raw.manualFilters.map(mf => ({
            id: mf.id,
            title: mf.title || '수동필터',
            lut: makeLUT(mf.selectedNums),
            min: mf.min !== undefined ? mf.min : 1,
            max: mf.max !== undefined ? mf.max : 6
        }));
    }

    return F;
}

// ──────────────────────────────────────────────────
// 4. 핵심 필터 검사 함수
// ──────────────────────────────────────────────────
function checkFilters(a, b, c, d, e, f, F) {

    // ── 바스켓: 고정수 ──
    if (F.fixedArr && F.fixedArr.length > 0) {
        const fa = F.fixedArr;
        for (let i = 0; i < fa.length; i++) {
            const n = fa[i];
            if (a !== n && b !== n && c !== n && d !== n && e !== n && f !== n) return false;
        }
    }

    // ── 바스켓: 제외수 ──
    if (F.excludedLUT) {
        const lut = F.excludedLUT;
        if (lut[a] || lut[b] || lut[c] || lut[d] || lut[e] || lut[f]) return false;
    }

    // ── 총합 ──
    const sum = a + b + c + d + e + f;
    if (F.sumMin !== undefined) {
        if (sum < F.sumMin || sum > F.sumMax) return false;
        if (F.sumExcluded && F.sumExcluded.has(sum)) return false;
    }

    // ── 끝수합 ──
    if (F.tailSumMin !== undefined) {
        const ts = (a % 10) + (b % 10) + (c % 10) + (d % 10) + (e % 10) + (f % 10);
        if (ts < F.tailSumMin || ts > F.tailSumMax) return false;
        if (F.tailSumExcluded && F.tailSumExcluded.has(ts)) return false;
    }

    // ── AC값 ──
    if (F.acMin !== undefined) {
        // AC = 서로 다른 번호 간격의 수 - 5
        const nums = [a, b, c, d, e, f];
        const gaps = new Set();
        for (let i = 0; i < 6; i++)
            for (let j = i + 1; j < 6; j++)
                gaps.add(Math.abs(nums[i] - nums[j]));
        const acVal = gaps.size - 5;
        if (acVal < F.acMin || acVal > F.acMax) return false;
        if (F.acExcluded && F.acExcluded.has(acVal)) return false;
    }

    // ── 홀짝 패턴 ──
    if (F.oddEvenSet) {
        const odd = (a % 2) + (b % 2) + (c % 2) + (d % 2) + (e % 2) + (f % 2);
        const ratio = `${odd}:${6 - odd}`;
        if (!F.oddEvenSet.has(ratio)) return false;
        if (F.oddEvenExcluded && F.oddEvenExcluded.has(ratio)) return false;
    }

    // ── 고저 패턴 (1~22=저, 23~45=고) ──
    if (F.highLowSet) {
        let low = 0;
        if (a <= 22) low++; if (b <= 22) low++; if (c <= 22) low++;
        if (d <= 22) low++; if (e <= 22) low++; if (f <= 22) low++;
        const ratio = `${low}:${6 - low}`;
        if (!F.highLowSet.has(ratio)) return false;
        if (F.highLowExcluded && F.highLowExcluded.has(ratio)) return false;
    }

    // ── 연번 ──
    if (F.consecutiveCounts !== undefined || F.runFilters) {
        // 정렬된 입력(a<b<c<d<e<f) 기준으로 연속 런 계산
        const arr6 = [a, b, c, d, e, f];
        let maxRun = 1, curRun = 1;
        let run3 = false, run4 = false, run5 = false, run6 = false;

        for (let i = 1; i < 6; i++) {
            if (arr6[i] === arr6[i - 1] + 1) {
                curRun++;
                if (curRun === 3) run3 = true;
                if (curRun === 4) run4 = true;
                if (curRun === 5) run5 = true;
                if (curRun === 6) run6 = true;
                if (curRun > maxRun) maxRun = curRun;
            } else {
                curRun = 1;
            }
        }
        if (F.consecutiveCounts && !F.consecutiveCounts.has(maxRun < 2 ? 0 : maxRun - 1)) return false;
        if (F.runFilters) {
            const rf = F.runFilters;
            if (rf.run3 && rf.run3.enabled !== undefined) { if (rf.run3.enabled && !run3) return false; }
            if (rf.run4 && rf.run4.enabled !== undefined) { if (rf.run4.enabled && !run4) return false; }
            if (rf.run5 && rf.run5.enabled !== undefined) { if (rf.run5.enabled && !run5) return false; }
            if (rf.run6 && rf.run6.enabled !== undefined) { if (rf.run6.enabled && !run6) return false; }
        }
    }

    // ── 이웃수 ──
    if (F.neighborCounts && F.neighborLUT) {
        const lut = F.neighborLUT;
        const cnt = (lut[a] || 0) + (lut[b] || 0) + (lut[c] || 0) + (lut[d] || 0) + (lut[e] || 0) + (lut[f] || 0);
        if (!F.neighborCounts.has(cnt)) return false;
    }

    // ── 이월수 ──
    if (F.carryoverCounts !== undefined || F.carryoverBonusCounts !== undefined) {
        if (F.carryoverCounts && F.carryoverLUT) {
            const lut = F.carryoverLUT;
            const cnt = (lut[a] || 0) + (lut[b] || 0) + (lut[c] || 0) + (lut[d] || 0) + (lut[e] || 0) + (lut[f] || 0);
            if (!F.carryoverCounts.has(cnt)) return false;
        }
        if (F.carryoverBonusCounts && F.carryoverBonusLUT) {
            const lut = F.carryoverBonusLUT;
            const cnt = (lut[a] || 0) + (lut[b] || 0) + (lut[c] || 0) + (lut[d] || 0) + (lut[e] || 0) + (lut[f] || 0);
            if (!F.carryoverBonusCounts.has(cnt)) return false;
        }
    }

    // ── 소수 ──
    if (F.primeCounts || F.primeExcludedLUT) {
        const el = F.primeExcludedLUT;
        if (el && (el[a] || el[b] || el[c] || el[d] || el[e] || el[f])) return false;
        if (F.primeCounts) {
            let cnt = PRIME_LUT[a] + PRIME_LUT[b] + PRIME_LUT[c] + PRIME_LUT[d] + PRIME_LUT[e] + PRIME_LUT[f];
            if (el) {
                if (el[a] && PRIME_LUT[a]) cnt--;
                if (el[b] && PRIME_LUT[b]) cnt--;
                if (el[c] && PRIME_LUT[c]) cnt--;
                if (el[d] && PRIME_LUT[d]) cnt--;
                if (el[e] && PRIME_LUT[e]) cnt--;
                if (el[f] && PRIME_LUT[f]) cnt--;
            }
            if (!F.primeCounts.has(cnt)) return false;
        }
    }

    // ── 합성수 ──
    if (F.compositeCounts || F.compositeExcludedLUT) {
        const el = F.compositeExcludedLUT;
        if (el && (el[a] || el[b] || el[c] || el[d] || el[e] || el[f])) return false;
        if (F.compositeCounts) {
            let cnt = COMPOS_LUT[a] + COMPOS_LUT[b] + COMPOS_LUT[c] + COMPOS_LUT[d] + COMPOS_LUT[e] + COMPOS_LUT[f];
            if (el) {
                if (el[a] && COMPOS_LUT[a]) cnt--;
                if (el[b] && COMPOS_LUT[b]) cnt--;
                if (el[c] && COMPOS_LUT[c]) cnt--;
                if (el[d] && COMPOS_LUT[d]) cnt--;
                if (el[e] && COMPOS_LUT[e]) cnt--;
                if (el[f] && COMPOS_LUT[f]) cnt--;
            }
            if (!F.compositeCounts.has(cnt)) return false;
        }
    }

    // ── 삼각수 ──
    if (F.triCounts || F.triExcludedLUT) {
        const el = F.triExcludedLUT;
        if (el && (el[a] || el[b] || el[c] || el[d] || el[e] || el[f])) return false;
        if (F.triCounts) {
            let cnt = TRI_LUT[a] + TRI_LUT[b] + TRI_LUT[c] + TRI_LUT[d] + TRI_LUT[e] + TRI_LUT[f];
            if (el) {
                if (el[a] && TRI_LUT[a]) cnt--;
                if (el[b] && TRI_LUT[b]) cnt--;
                if (el[c] && TRI_LUT[c]) cnt--;
                if (el[d] && TRI_LUT[d]) cnt--;
                if (el[e] && TRI_LUT[e]) cnt--;
                if (el[f] && TRI_LUT[f]) cnt--;
            }
            if (!F.triCounts.has(cnt)) return false;
        }
    }

    // ── 제곱수 ──
    if (F.squareCounts || F.squareExcludedLUT) {
        const el = F.squareExcludedLUT;
        if (el && (el[a] || el[b] || el[c] || el[d] || el[e] || el[f])) return false;
        if (F.squareCounts) {
            let cnt = SQUARE_LUT[a] + SQUARE_LUT[b] + SQUARE_LUT[c] + SQUARE_LUT[d] + SQUARE_LUT[e] + SQUARE_LUT[f];
            if (el) {
                if (el[a] && SQUARE_LUT[a]) cnt--;
                if (el[b] && SQUARE_LUT[b]) cnt--;
                if (el[c] && SQUARE_LUT[c]) cnt--;
                if (el[d] && SQUARE_LUT[d]) cnt--;
                if (el[e] && SQUARE_LUT[e]) cnt--;
                if (el[f] && SQUARE_LUT[f]) cnt--;
            }
            if (!F.squareCounts.has(cnt)) return false;
        }
    }

    // ── 동형수(쌍수: 11,22,33,44) ──
    if (F.twinCounts || F.twinExcludedLUT) {
        const el = F.twinExcludedLUT;
        if (el && (el[a] || el[b] || el[c] || el[d] || el[e] || el[f])) return false;
        if (F.twinCounts) {
            let cnt = TWIN_LUT[a] + TWIN_LUT[b] + TWIN_LUT[c] + TWIN_LUT[d] + TWIN_LUT[e] + TWIN_LUT[f];
            if (el) {
                if (el[a] && TWIN_LUT[a]) cnt--;
                if (el[b] && TWIN_LUT[b]) cnt--;
                if (el[c] && TWIN_LUT[c]) cnt--;
                if (el[d] && TWIN_LUT[d]) cnt--;
                if (el[e] && TWIN_LUT[e]) cnt--;
                if (el[f] && TWIN_LUT[f]) cnt--;
            }
            if (!F.twinCounts.has(cnt)) return false;
        }
    }

    // ── 끝수 패턴 (0~9 끝자리 개수 범위) ──
    if (F.tailDigitRanges) {
        const td = new Uint8Array(10);
        td[a % 10]++; td[b % 10]++; td[c % 10]++; td[d % 10]++; td[e % 10]++; td[f % 10]++;
        const ranges = F.tailDigitRanges;
        for (const digit in ranges) {
            const r = ranges[digit];
            if (r.min === undefined && r.max === undefined) continue;
            const cnt = td[parseInt(digit)];
            if (r.min !== undefined && cnt < r.min) return false;
            if (r.max !== undefined && cnt > r.max) return false;
        }
    }

    // ── 배수 패턴 ──
    if (F.multipleRanges) {
        const mr = F.multipleRanges;
        const m3a = M3_LUT[a], m3b = M3_LUT[b], m3c = M3_LUT[c], m3d = M3_LUT[d], m3e = M3_LUT[e], m3f = M3_LUT[f];
        const m4a = M4_LUT[a], m4b = M4_LUT[b], m4c = M4_LUT[c], m4d = M4_LUT[d], m4e = M4_LUT[e], m4f = M4_LUT[f];
        const m5a = M5_LUT[a], m5b = M5_LUT[b], m5c = M5_LUT[c], m5d = M5_LUT[d], m5e = M5_LUT[e], m5f = M5_LUT[f];
        const m7a = M7_LUT[a], m7b = M7_LUT[b], m7c = M7_LUT[c], m7d = M7_LUT[d], m7e = M7_LUT[e], m7f = M7_LUT[f];
        const m8a = M8_LUT[a], m8b = M8_LUT[b], m8c = M8_LUT[c], m8d = M8_LUT[d], m8e = M8_LUT[e], m8f = M8_LUT[f];
        const cnt3 = m3a + m3b + m3c + m3d + m3e + m3f;
        const cnt4 = m4a + m4b + m4c + m4d + m4e + m4f;
        const cnt5 = m5a + m5b + m5c + m5d + m5e + m5f;
        const cnt7 = m7a + m7b + m7c + m7d + m7e + m7f;
        const cnt8 = m8a + m8b + m8c + m8d + m8e + m8f;
        const r3 = mr['3배수']; if (r3 && r3.min !== undefined) { if (cnt3 < r3.min || cnt3 > r3.max) return false; }
        const r4 = mr['4배수']; if (r4 && r4.min !== undefined) { if (cnt4 < r4.min || cnt4 > r4.max) return false; }
        const r5 = mr['5배수']; if (r5 && r5.min !== undefined) { if (cnt5 < r5.min || cnt5 > r5.max) return false; }
        const r7 = mr['7배수']; if (r7 && r7.min !== undefined) { if (cnt7 < r7.min || cnt7 > r7.max) return false; }
        const r8 = mr['8배수']; if (r8 && r8.min !== undefined) { if (cnt8 < r8.min || cnt8 > r8.max) return false; }
        const cnt34 = (m3a && m4a ? 1 : 0) + (m3b && m4b ? 1 : 0) + (m3c && m4c ? 1 : 0) + (m3d && m4d ? 1 : 0) + (m3e && m4e ? 1 : 0) + (m3f && m4f ? 1 : 0);
        const r34 = mr['3·4배수']; if (r34 && r34.min !== undefined) { if (cnt34 < r34.min || cnt34 > r34.max) return false; }
        const cnt35 = (m3a && m5a ? 1 : 0) + (m3b && m5b ? 1 : 0) + (m3c && m5c ? 1 : 0) + (m3d && m5d ? 1 : 0) + (m3e && m5e ? 1 : 0) + (m3f && m5f ? 1 : 0);
        const r35 = mr['3·5배수']; if (r35 && r35.min !== undefined) { if (cnt35 < r35.min || cnt35 > r35.max) return false; }
        const cnt45 = (m4a && m5a ? 1 : 0) + (m4b && m5b ? 1 : 0) + (m4c && m5c ? 1 : 0) + (m4d && m5d ? 1 : 0) + (m4e && m5e ? 1 : 0) + (m4f && m5f ? 1 : 0);
        const r45b = mr['4·5배수']; if (r45b && r45b.min !== undefined) { if (cnt45 < r45b.min || cnt45 > r45b.max) return false; }
        const cntOther = (!m3a && !m4a && !m5a && !m7a && !m8a ? 1 : 0) + (!m3b && !m4b && !m5b && !m7b && !m8b ? 1 : 0) +
            (!m3c && !m4c && !m5c && !m7c && !m8c ? 1 : 0) + (!m3d && !m4d && !m5d && !m7d && !m8d ? 1 : 0) +
            (!m3e && !m4e && !m5e && !m7e && !m8e ? 1 : 0) + (!m3f && !m4f && !m5f && !m7f && !m8f ? 1 : 0);
        const rOther = mr['배수외']; if (rOther && rOther.min !== undefined) { if (cntOther < rOther.min || cntOther > rOther.max) return false; }
    }

    // ── 번호대 (1_10 / 11_20 / 21_30 / 31_40 / 41_45) ──
    if (F.numRanges) {
        const ranges = F.numRanges;
        let c1 = 0, c2 = 0, c3 = 0, c4 = 0, c5 = 0;
        const cnt = (n) => { if (n <= 10) c1++; else if (n <= 20) c2++; else if (n <= 30) c3++; else if (n <= 40) c4++; else c5++; };
        cnt(a); cnt(b); cnt(c); cnt(d); cnt(e); cnt(f);
        const r10 = ranges['1_10'];  if (r10 && r10.min !== undefined) { if (c1 < r10.min || c1 > r10.max) return false; }
        const r20 = ranges['11_20']; if (r20 && r20.min !== undefined) { if (c2 < r20.min || c2 > r20.max) return false; }
        const r30 = ranges['21_30']; if (r30 && r30.min !== undefined) { if (c3 < r30.min || c3 > r30.max) return false; }
        const r40 = ranges['31_40']; if (r40 && r40.min !== undefined) { if (c4 < r40.min || c4 > r40.max) return false; }
        const r45 = ranges['41_45']; if (r45 && r45.min !== undefined) { if (c5 < r45.min || c5 > r45.max) return false; }
    }

    // ── 엔트로피 ──
    if (F.entropyRange) {
        const eMin = parseFloat(F.entropyRange.min);
        const eMax = parseFloat(F.entropyRange.max);
        if (!isNaN(eMin) || !isNaN(eMax)) {
            let c1 = 0, c2 = 0, c3 = 0, c4 = 0, c5 = 0;
            const cnt = (n) => { if (n <= 10) c1++; else if (n <= 20) c2++; else if (n <= 30) c3++; else if (n <= 40) c4++; else c5++; };
            cnt(a); cnt(b); cnt(c); cnt(d); cnt(e); cnt(f);
            const bins = [c1, c2, c3, c4, c5];
            let ent = 0;
            for (let i = 0; i < 5; i++) { if (bins[i] > 0) { const p = bins[i] / 6; ent -= p * Math.log2(p); } }
            ent = Math.round(ent * 100) / 100;
            if (!isNaN(eMin) && ent < eMin) return false;
            if (!isNaN(eMax) && ent > eMax) return false;
        }
    }

    // ── 9궁 (마방진) ──
    if (F.palaceRanges) {
        const pr = F.palaceRanges;
        const pc = new Uint8Array(10);
        pc[PALACE_LUT[a]]++; pc[PALACE_LUT[b]]++; pc[PALACE_LUT[c]]++;
        pc[PALACE_LUT[d]]++; pc[PALACE_LUT[e]]++; pc[PALACE_LUT[f]]++;
        for (let g = 1; g <= 9; g++) {
            const r = pr[`${g}궁`]; if (!r) continue;
            if (r.min !== undefined && pc[g] < r.min) return false;
            if (r.max !== undefined && pc[g] > r.max) return false;
        }
    }

    // ── 로또용지 (가로/세로) ──
    if (F.paperGroups) {
        const pg = F.paperGroups;
        const gc = new Uint8Array(8);
        gc[GARO_LUT[a]]++; gc[GARO_LUT[b]]++; gc[GARO_LUT[c]]++;
        gc[GARO_LUT[d]]++; gc[GARO_LUT[e]]++; gc[GARO_LUT[f]]++;
        for (let row = 1; row <= 7; row++) {
            const r = pg[`가로${row}`]; if (!r) continue;
            if (r.min !== undefined && gc[row] < r.min) return false;
            if (r.max !== undefined && gc[row] > r.max) return false;
        }
        const sc = new Uint8Array(8);
        sc[SERO_LUT[a]]++; sc[SERO_LUT[b]]++; sc[SERO_LUT[c]]++;
        sc[SERO_LUT[d]]++; sc[SERO_LUT[e]]++; sc[SERO_LUT[f]]++;
        for (let col = 1; col <= 7; col++) {
            const r = pg[`세로${col}`]; if (!r) continue;
            if (r.min !== undefined && sc[col] < r.min) return false;
            if (r.max !== undefined && sc[col] > r.max) return false;
        }
    }

    // ── Hot/Cold 5/10/15/20 ──
    for (const period of [5, 10, 15, 20]) {
        const hc = F[`hc${period}`];
        if (!hc) continue;

        const lh = hc.hotLUT, lw = hc.warmLUT, lc = hc.coldLUT;

        const hotCnt = lh ? (lh[a] || 0) + (lh[b] || 0) + (lh[c] || 0) + (lh[d] || 0) + (lh[e] || 0) + (lh[f] || 0) : 0;
        const warmCnt = lw ? (lw[a] || 0) + (lw[b] || 0) + (lw[c] || 0) + (lw[d] || 0) + (lw[e] || 0) + (lw[f] || 0) : 0;
        const coldCnt = lc ? (lc[a] || 0) + (lc[b] || 0) + (lc[c] || 0) + (lc[d] || 0) + (lc[e] || 0) + (lc[f] || 0) : 0;

        const hr = hc.hotRange;
        if (hotCnt < hr[0] || hotCnt > hr[1]) return false;
        const wr = hc.warmRange;
        if (warmCnt < wr[0] || warmCnt > wr[1]) return false;
        const cr = hc.coldRange;
        if (coldCnt < cr[0] || coldCnt > cr[1]) return false;
    }

    // ── 미출현 기간 그룹 ──
    if (F.missingPeriodGroups) {
        const groups = F.missingPeriodGroups;
        for (let gi = 0; gi < groups.length; gi++) {
            const g = groups[gi];
            if (!g.nums || g.nums.length === 0) continue;
            const nums = g.nums;
            let cnt = 0;
            for (let ni = 0; ni < nums.length; ni++) {
                const n = nums[ni];
                if (n === a || n === b || n === c || n === d || n === e || n === f) cnt++;
            }
            if (g.min !== undefined && cnt < g.min) return false;
            if (g.max !== undefined && cnt > g.max) return false;
        }
    }

    // ── 미출현 커스텀 그룹 ──
    if (F.missingCustomGroups) {
        const groups = F.missingCustomGroups;
        for (let gi = 0; gi < groups.length; gi++) {
            const g = groups[gi];
            if (!g.lut) continue;
            const lut = g.lut;
            const cnt = (lut[a] || 0) + (lut[b] || 0) + (lut[c] || 0) + (lut[d] || 0) + (lut[e] || 0) + (lut[f] || 0);
            if (cnt < g.min || cnt > g.max) return false;
        }
    }

    // ── 회귀 분석 ──
    if (F.regressionFilters) {
        const rf = F.regressionFilters;
        for (let ri = 0; ri < rf.length; ri++) {
            const r = rf[ri];
            if (!r.lut) continue;
            const lut = r.lut;
            const cnt = (lut[a] || 0) + (lut[b] || 0) + (lut[c] || 0) + (lut[d] || 0) + (lut[e] || 0) + (lut[f] || 0);
            if (cnt < r.min || cnt > r.max) return false;
        }
    }

    // ── 커스텀 분석 필터 (ai_custom_analyses) ──
    if (F.customAnalysis) {
        const ca = F.customAnalysis;
        for (let ci = 0; ci < ca.length; ci++) {
            const cf = ca[ci];
            if (!cf.lut) continue;
            const lut = cf.lut;
            const cnt = (lut[a] || 0) + (lut[b] || 0) + (lut[c] || 0) + (lut[d] || 0) + (lut[e] || 0) + (lut[f] || 0);
            if (cnt < cf.min || cnt > cf.max) return false;
        }
    }

    // ── 수동 필터 (manual_filters) ──
    if (F.manualFilters) {
        const mf = F.manualFilters;
        for (let mi = 0; mi < mf.length; mi++) {
            const m = mf[mi];
            if (!m.lut) continue;
            const lut = m.lut;
            const cnt = (lut[a] || 0) + (lut[b] || 0) + (lut[c] || 0) + (lut[d] || 0) + (lut[e] || 0) + (lut[f] || 0);
            if (cnt < m.min || cnt > m.max) return false;
        }
    }

    return true;
}

// ──────────────────────────────────────────────────
// 5. 진단 함수 — 어느 필터에서 탈락하는지 단계별 집계
// ──────────────────────────────────────────────────
function checkFiltersGetStage(a, b, c, d, e, f, F) {
    // 각 필터를 단계별로 체크하고 첫 번째 탈락 필터명을 반환
    // 통과하면 null 반환

    if (F.fixedArr && F.fixedArr.length > 0) {
        for (let i = 0; i < F.fixedArr.length; i++) {
            const n = F.fixedArr[i];
            if (a !== n && b !== n && c !== n && d !== n && e !== n && f !== n) return '바스켓 고정수';
        }
    }
    if (F.excludedLUT) {
        const lut = F.excludedLUT;
        if (lut[a] || lut[b] || lut[c] || lut[d] || lut[e] || lut[f]) return '바스켓 제외수';
    }

    const sum = a + b + c + d + e + f;
    if (F.sumMin !== undefined) {
        if (sum < F.sumMin || sum > F.sumMax) return '총합';
        if (F.sumExcluded && F.sumExcluded.has(sum)) return '총합 제외값';
    }
    if (F.tailSumMin !== undefined) {
        const ts = (a % 10) + (b % 10) + (c % 10) + (d % 10) + (e % 10) + (f % 10);
        if (ts < F.tailSumMin || ts > F.tailSumMax) return '끝수합';
        if (F.tailSumExcluded && F.tailSumExcluded.has(ts)) return '끝수합 제외값';
    }
    if (F.acMin !== undefined) {
        const nums = [a, b, c, d, e, f];
        const gaps = new Set();
        for (let i = 0; i < 6; i++) for (let j = i + 1; j < 6; j++) gaps.add(Math.abs(nums[i] - nums[j]));
        const acVal = gaps.size - 5;
        if (acVal < F.acMin || acVal > F.acMax) return 'AC값';
        if (F.acExcluded && F.acExcluded.has(acVal)) return 'AC값 제외';
    }
    if (F.oddEvenSet) {
        const odd = (a % 2) + (b % 2) + (c % 2) + (d % 2) + (e % 2) + (f % 2);
        const r = `${odd}:${6 - odd}`;
        if (!F.oddEvenSet.has(r)) return '홀짝 패턴';
        if (F.oddEvenExcluded && F.oddEvenExcluded.has(r)) return '홀짝 제외';
    }
    if (F.highLowSet) {
        let low = 0;
        if (a <= 22) low++; if (b <= 22) low++; if (c <= 22) low++;
        if (d <= 22) low++; if (e <= 22) low++; if (f <= 22) low++;
        const r = `${low}:${6 - low}`;
        if (!F.highLowSet.has(r)) return '고저 패턴';
        if (F.highLowExcluded && F.highLowExcluded.has(r)) return '고저 제외';
    }
    if (F.tailDigitRanges) {
        const td = new Uint8Array(10);
        td[a % 10]++; td[b % 10]++; td[c % 10]++; td[d % 10]++; td[e % 10]++; td[f % 10]++;
        for (const digit in F.tailDigitRanges) {
            const r = F.tailDigitRanges[digit];
            const cnt = td[parseInt(digit)];
            if (r.min !== undefined && cnt < r.min) return `끝수(${digit})`;
            if (r.max !== undefined && cnt > r.max) return `끝수(${digit})`;
        }
    }
    if (F.primeCounts || F.primeExcludedLUT) {
        const el = F.primeExcludedLUT;
        if (el && (el[a] || el[b] || el[c] || el[d] || el[e] || el[f])) return '소수 제외번호';
        if (F.primeCounts) {
            let cnt = PRIME_LUT[a] + PRIME_LUT[b] + PRIME_LUT[c] + PRIME_LUT[d] + PRIME_LUT[e] + PRIME_LUT[f];
            if (el) { if (el[a] && PRIME_LUT[a]) cnt--; if (el[b] && PRIME_LUT[b]) cnt--; if (el[c] && PRIME_LUT[c]) cnt--; if (el[d] && PRIME_LUT[d]) cnt--; if (el[e] && PRIME_LUT[e]) cnt--; if (el[f] && PRIME_LUT[f]) cnt--; }
            if (!F.primeCounts.has(cnt)) return '소수 개수';
        }
    }
    if (F.squareCounts || F.squareExcludedLUT) {
        const el = F.squareExcludedLUT;
        if (el && (el[a] || el[b] || el[c] || el[d] || el[e] || el[f])) return '제곱수 제외번호';
        if (F.squareCounts) {
            let cnt = SQUARE_LUT[a] + SQUARE_LUT[b] + SQUARE_LUT[c] + SQUARE_LUT[d] + SQUARE_LUT[e] + SQUARE_LUT[f];
            if (!F.squareCounts.has(cnt)) return '제곱수 개수';
        }
    }
    if (F.triCounts || F.triExcludedLUT) {
        const el = F.triExcludedLUT;
        if (el && (el[a] || el[b] || el[c] || el[d] || el[e] || el[f])) return '삼각수 제외번호';
        if (F.triCounts) {
            let cnt = TRI_LUT[a] + TRI_LUT[b] + TRI_LUT[c] + TRI_LUT[d] + TRI_LUT[e] + TRI_LUT[f];
            if (!F.triCounts.has(cnt)) return '삼각수 개수';
        }
    }
    if (F.twinCounts || F.twinExcludedLUT) {
        const el = F.twinExcludedLUT;
        if (el && (el[a] || el[b] || el[c] || el[d] || el[e] || el[f])) return '쌍수 제외번호';
        if (F.twinCounts) {
            let cnt = TWIN_LUT[a] + TWIN_LUT[b] + TWIN_LUT[c] + TWIN_LUT[d] + TWIN_LUT[e] + TWIN_LUT[f];
            if (!F.twinCounts.has(cnt)) return '쌍수 개수';
        }
    }
    if (F.compositeCounts || F.compositeExcludedLUT) {
        const el = F.compositeExcludedLUT;
        if (el && (el[a] || el[b] || el[c] || el[d] || el[e] || el[f])) return '합성수 제외번호';
        if (F.compositeCounts) {
            let cnt = COMPOS_LUT[a] + COMPOS_LUT[b] + COMPOS_LUT[c] + COMPOS_LUT[d] + COMPOS_LUT[e] + COMPOS_LUT[f];
            if (!F.compositeCounts.has(cnt)) return '합성수 개수';
        }
    }
    if (F.consecutiveCounts !== undefined || F.runFilters) {
        const arr6 = [a, b, c, d, e, f];
        let maxRun = 1, curRun = 1;
        let run3 = false, run4 = false, run5 = false, run6 = false;
        for (let i = 1; i < 6; i++) {
            if (arr6[i] === arr6[i - 1] + 1) { curRun++; if (curRun >= 3) run3 = true; if (curRun >= 4) run4 = true; if (curRun >= 5) run5 = true; if (curRun === 6) run6 = true; if (curRun > maxRun) maxRun = curRun; } else curRun = 1;
        }
        if (F.consecutiveCounts && !F.consecutiveCounts.has(maxRun < 2 ? 0 : maxRun - 1)) return '연번 개수';
        if (F.runFilters) {
            const rf = F.runFilters;
            if (rf.run3 && rf.run3.enabled && !run3) return '연번(3연속)';
            if (rf.run4 && rf.run4.enabled && !run4) return '연번(4연속)';
            if (rf.run5 && rf.run5.enabled && !run5) return '연번(5연속)';
            if (rf.run6 && rf.run6.enabled && !run6) return '연번(6연속)';
        }
    }
    if (F.numRanges) {
        let c1 = 0, c2 = 0, c3 = 0, c4 = 0, c5 = 0;
        const cnt = (n) => { if (n <= 10) c1++; else if (n <= 20) c2++; else if (n <= 30) c3++; else if (n <= 40) c4++; else c5++; };
        cnt(a); cnt(b); cnt(c); cnt(d); cnt(e); cnt(f);
        const r10 = F.numRanges['1_10']; if (r10 && r10.min !== undefined && (c1 < r10.min || c1 > r10.max)) return '번호대 1~10';
        const r20 = F.numRanges['11_20']; if (r20 && r20.min !== undefined && (c2 < r20.min || c2 > r20.max)) return '번호대 11~20';
        const r30 = F.numRanges['21_30']; if (r30 && r30.min !== undefined && (c3 < r30.min || c3 > r30.max)) return '번호대 21~30';
        const r40 = F.numRanges['31_40']; if (r40 && r40.min !== undefined && (c4 < r40.min || c4 > r40.max)) return '번호대 31~40';
        const r45 = F.numRanges['41_45']; if (r45 && r45.min !== undefined && (c5 < r45.min || c5 > r45.max)) return '번호대 41~45';
    }
    if (F.entropyRange) {
        const eMin = parseFloat(F.entropyRange.min);
        const eMax = parseFloat(F.entropyRange.max);
        if (!isNaN(eMin) || !isNaN(eMax)) {
            let c1 = 0, c2 = 0, c3 = 0, c4 = 0, c5 = 0;
            const cnt = (n) => {
                if (n <= 10) c1++;
                else if (n <= 20) c2++;
                else if (n <= 30) c3++;
                else if (n <= 40) c4++;
                else c5++;
            };
            cnt(a); cnt(b); cnt(c); cnt(d); cnt(e); cnt(f);

            const ranges = [c1, c2, c3, c4, c5];
            let ent = 0;
            for (let i = 0; i < 5; i++) {
                if (ranges[i] > 0) {
                    const p = ranges[i] / 6;
                    ent -= p * Math.log2(p);
                }
            }
            ent = Math.round(ent * 100) / 100;

            if (!isNaN(eMin) && ent < eMin) return '엔트로피_최소';
            if (!isNaN(eMax) && ent > eMax) return '엔트로피_최대';
        }
    }
    if (F.palaceRanges) {
        const pc = new Uint8Array(10);
        pc[PALACE_LUT[a]]++; pc[PALACE_LUT[b]]++; pc[PALACE_LUT[c]]++; pc[PALACE_LUT[d]]++; pc[PALACE_LUT[e]]++; pc[PALACE_LUT[f]]++;
        for (let g = 1; g <= 9; g++) { const r = F.palaceRanges[`${g}궁`]; if (!r) continue; if (r.min !== undefined && pc[g] < r.min) return `9궁(${g}궁)`; if (r.max !== undefined && pc[g] > r.max) return `9궁(${g}궁)`; }
    }
    if (F.paperGroups) {
        const gc = new Uint8Array(8);
        gc[GARO_LUT[a]]++; gc[GARO_LUT[b]]++; gc[GARO_LUT[c]]++; gc[GARO_LUT[d]]++; gc[GARO_LUT[e]]++; gc[GARO_LUT[f]]++;
        for (let r = 1; r <= 7; r++) { const f2 = F.paperGroups[`가로${r}`]; if (!f2) continue; if (f2.min !== undefined && gc[r] < f2.min) return `로또용지(가로${r})`; if (f2.max !== undefined && gc[r] > f2.max) return `로또용지(가로${r})`; }
        const sc = new Uint8Array(8);
        sc[SERO_LUT[a]]++; sc[SERO_LUT[b]]++; sc[SERO_LUT[c]]++; sc[SERO_LUT[d]]++; sc[SERO_LUT[e]]++; sc[SERO_LUT[f]]++;
        for (let col = 1; col <= 7; col++) { const f2 = F.paperGroups[`세로${col}`]; if (!f2) continue; if (f2.min !== undefined && sc[col] < f2.min) return `로또용지(세로${col})`; if (f2.max !== undefined && sc[col] > f2.max) return `로또용지(세로${col})`; }
    }
    if (F.multipleRanges) {
        const mr = F.multipleRanges;
        const m3a = M3_LUT[a], m3b = M3_LUT[b], m3c = M3_LUT[c], m3d = M3_LUT[d], m3e = M3_LUT[e], m3f = M3_LUT[f];
        const m4a = M4_LUT[a], m4b = M4_LUT[b], m4c = M4_LUT[c], m4d = M4_LUT[d], m4e = M4_LUT[e], m4f = M4_LUT[f];
        const m5a = M5_LUT[a], m5b = M5_LUT[b], m5c = M5_LUT[c], m5d = M5_LUT[d], m5e = M5_LUT[e], m5f = M5_LUT[f];
        const m7a = M7_LUT[a], m7b = M7_LUT[b], m7c = M7_LUT[c], m7d = M7_LUT[d], m7e = M7_LUT[e], m7f = M7_LUT[f];
        const m8a = M8_LUT[a], m8b = M8_LUT[b], m8c = M8_LUT[c], m8d = M8_LUT[d], m8e = M8_LUT[e], m8f = M8_LUT[f];
        const cnt3 = m3a + m3b + m3c + m3d + m3e + m3f; const r3 = mr['3배수']; if (r3 && r3.min !== undefined && (cnt3 < r3.min || cnt3 > r3.max)) return '3배수';
        const cnt4 = m4a + m4b + m4c + m4d + m4e + m4f; const r4 = mr['4배수']; if (r4 && r4.min !== undefined && (cnt4 < r4.min || cnt4 > r4.max)) return '4배수';
        const cnt5 = m5a + m5b + m5c + m5d + m5e + m5f; const r5 = mr['5배수']; if (r5 && r5.min !== undefined && (cnt5 < r5.min || cnt5 > r5.max)) return '5배수';
        const cnt7 = m7a + m7b + m7c + m7d + m7e + m7f; const r7 = mr['7배수']; if (r7 && r7.min !== undefined && (cnt7 < r7.min || cnt7 > r7.max)) return '7배수';
        const cnt8 = m8a + m8b + m8c + m8d + m8e + m8f; const r8 = mr['8배수']; if (r8 && r8.min !== undefined && (cnt8 < r8.min || cnt8 > r8.max)) return '8배수';
        const cnt34 = (m3a && m4a ? 1 : 0) + (m3b && m4b ? 1 : 0) + (m3c && m4c ? 1 : 0) + (m3d && m4d ? 1 : 0) + (m3e && m4e ? 1 : 0) + (m3f && m4f ? 1 : 0); const r34 = mr['3·4배수']; if (r34 && r34.min !== undefined && (cnt34 < r34.min || cnt34 > r34.max)) return '3·4배수';
        const cnt35 = (m3a && m5a ? 1 : 0) + (m3b && m5b ? 1 : 0) + (m3c && m5c ? 1 : 0) + (m3d && m5d ? 1 : 0) + (m3e && m5e ? 1 : 0) + (m3f && m5f ? 1 : 0); const r35 = mr['3·5배수']; if (r35 && r35.min !== undefined && (cnt35 < r35.min || cnt35 > r35.max)) return '3·5배수';
        const cnt45 = (m4a && m5a ? 1 : 0) + (m4b && m5b ? 1 : 0) + (m4c && m5c ? 1 : 0) + (m4d && m5d ? 1 : 0) + (m4e && m5e ? 1 : 0) + (m4f && m5f ? 1 : 0); const r45b = mr['4·5배수']; if (r45b && r45b.min !== undefined && (cnt45 < r45b.min || cnt45 > r45b.max)) return '4·5배수';
        const cntO = (!m3a && !m4a && !m5a && !m7a && !m8a ? 1 : 0) + (!m3b && !m4b && !m5b && !m7b && !m8b ? 1 : 0) + (!m3c && !m4c && !m5c && !m7c && !m8c ? 1 : 0) + (!m3d && !m4d && !m5d && !m7d && !m8d ? 1 : 0) + (!m3e && !m4e && !m5e && !m7e && !m8e ? 1 : 0) + (!m3f && !m4f && !m5f && !m7f && !m8f ? 1 : 0); const rO = mr['배수외']; if (rO && rO.min !== undefined && (cntO < rO.min || cntO > rO.max)) return '배수외';
    }
    if (F.carryoverCounts && F.carryoverLUT) {
        const lut = F.carryoverLUT; const cnt = (lut[a] || 0) + (lut[b] || 0) + (lut[c] || 0) + (lut[d] || 0) + (lut[e] || 0) + (lut[f] || 0);
        if (!F.carryoverCounts.has(cnt)) return '이월수';
    }
    if (F.carryoverBonusCounts && F.carryoverBonusLUT) {
        const lut = F.carryoverBonusLUT; const cnt = (lut[a] || 0) + (lut[b] || 0) + (lut[c] || 0) + (lut[d] || 0) + (lut[e] || 0) + (lut[f] || 0);
        if (!F.carryoverBonusCounts.has(cnt)) return '이월수(보너스포함)';
    }
    if (F.neighborCounts && F.neighborLUT) {
        const lut = F.neighborLUT; const cnt = (lut[a] || 0) + (lut[b] || 0) + (lut[c] || 0) + (lut[d] || 0) + (lut[e] || 0) + (lut[f] || 0);
        if (!F.neighborCounts.has(cnt)) return '이웃수';
    }
    for (const period of [5, 10, 15, 20]) {
        const hc = F[`hc${period}`]; if (!hc) continue;
        const lh = hc.hotLUT, lw = hc.warmLUT, lc = hc.coldLUT;
        const hCnt = lh ? (lh[a] || 0) + (lh[b] || 0) + (lh[c] || 0) + (lh[d] || 0) + (lh[e] || 0) + (lh[f] || 0) : 0;
        const wCnt = lw ? (lw[a] || 0) + (lw[b] || 0) + (lw[c] || 0) + (lw[d] || 0) + (lw[e] || 0) + (lw[f] || 0) : 0;
        const cCnt = lc ? (lc[a] || 0) + (lc[b] || 0) + (lc[c] || 0) + (lc[d] || 0) + (lc[e] || 0) + (lc[f] || 0) : 0;
        const hr = hc.hotRange, wr = hc.warmRange, cr = hc.coldRange;
        if (hCnt < hr[0] || hCnt > hr[1]) return `핫콜드${period}(핫)`;
        if (wCnt < wr[0] || wCnt > wr[1]) return `핫콜드${period}(중립)`;
        if (cCnt < cr[0] || cCnt > cr[1]) return `핫콜드${period}(콜드)`;
    }
    if (F.missingPeriodGroups) {
        for (let gi = 0; gi < F.missingPeriodGroups.length; gi++) {
            const g = F.missingPeriodGroups[gi]; if (!g.nums || g.nums.length === 0) continue;
            const nums = g.nums; let cnt = 0;
            for (let ni = 0; ni < nums.length; ni++) { const n = nums[ni]; if (n === a || n === b || n === c || n === d || n === e || n === f) cnt++; }
            if (g.min !== undefined && cnt < g.min) return `미출현기간(그룹${gi + 1})`;
            if (g.max !== undefined && cnt > g.max) return `미출현기간(그룹${gi + 1})`;
        }
    }
    if (F.missingCustomGroups) {
        for (let gi = 0; gi < F.missingCustomGroups.length; gi++) {
            const g = F.missingCustomGroups[gi]; if (!g.lut) continue;
            const cnt = (g.lut[a] || 0) + (g.lut[b] || 0) + (g.lut[c] || 0) + (g.lut[d] || 0) + (g.lut[e] || 0) + (g.lut[f] || 0);
            if (cnt < g.min || cnt > g.max) return `미출현커스텀(${gi + 1})`;
        }
    }
    if (F.regressionFilters) {
        for (let ri = 0; ri < F.regressionFilters.length; ri++) {
            const r = F.regressionFilters[ri]; if (!r.lut) continue;
            const cnt = (r.lut[a] || 0) + (r.lut[b] || 0) + (r.lut[c] || 0) + (r.lut[d] || 0) + (r.lut[e] || 0) + (r.lut[f] || 0);
            if (cnt < r.min || cnt > r.max) return `회귀분석(step${r.step})`;
        }
    }
    if (F.customAnalysis) {
        for (let ci = 0; ci < F.customAnalysis.length; ci++) {
            const cf = F.customAnalysis[ci]; if (!cf.lut) continue;
            const cnt = (cf.lut[a] || 0) + (cf.lut[b] || 0) + (cf.lut[c] || 0) + (cf.lut[d] || 0) + (cf.lut[e] || 0) + (cf.lut[f] || 0);
            if (cnt < cf.min || cnt > cf.max) return `커스텀분석:${cf.title || ci}`;
        }
    }
    if (F.manualFilters) {
        for (let mi = 0; mi < F.manualFilters.length; mi++) {
            const m = F.manualFilters[mi]; if (!m.lut) continue;
            const cnt = (m.lut[a] || 0) + (m.lut[b] || 0) + (m.lut[c] || 0) + (m.lut[d] || 0) + (m.lut[e] || 0) + (m.lut[f] || 0);
            if (cnt < m.min || cnt > m.max) return `수동필터:${m.title || mi}`;
        }
    }
    return null; // 모든 필터 통과
}

function diagnoseFilters(rawFilters) {
    if (!combinations) return null;
    const F = parseFilters(rawFilters);
    const failMap = {};
    let pass = 0;

    // [추가] 모든 활성화된 필터명을 failMap에 0으로 미리 등록
    if (F.fixedArr && F.fixedArr.length > 0) failMap['바스켓 고정수'] = 0;
    if (F.excludedLUT) failMap['바스켓 제외수'] = 0;
    if (F.sumMin !== undefined) { failMap['총합'] = 0; if (F.sumExcluded) failMap['총합 제외값'] = 0; }
    if (F.tailSumMin !== undefined) { failMap['끝수합'] = 0; if (F.tailSumExcluded) failMap['끝수합 제외값'] = 0; }
    if (F.acMin !== undefined) { failMap['AC값'] = 0; if (F.acExcluded) failMap['AC값 제외'] = 0; }
    if (F.oddEvenSet) { failMap['홀짝 패턴'] = 0; if (F.oddEvenExcluded) failMap['홀짝 제외'] = 0; }
    if (F.highLowSet) { failMap['고저 패턴'] = 0; if (F.highLowExcluded) failMap['고저 제외'] = 0; }

    // 번호 속성 (소수, 제곱수 등)
    if (F.primeCounts || F.primeExcludedLUT) { if (F.primeExcludedLUT) failMap['소수 제외번호'] = 0; if (F.primeCounts) failMap['소수 개수'] = 0; }
    if (F.squareCounts || F.squareExcludedLUT) { if (F.squareExcludedLUT) failMap['제곱수 제외번호'] = 0; if (F.squareCounts) failMap['제곱수 개수'] = 0; }
    if (F.triCounts || F.triExcludedLUT) { if (F.triExcludedLUT) failMap['삼각수 제외번호'] = 0; if (F.triCounts) failMap['삼각수 개수'] = 0; }
    if (F.twinCounts || F.twinExcludedLUT) { if (F.twinExcludedLUT) failMap['쌍수 제외번호'] = 0; if (F.twinCounts) failMap['쌍수 개수'] = 0; }
    if (F.compositeCounts || F.compositeExcludedLUT) { if (F.compositeExcludedLUT) failMap['합성수 제외번호'] = 0; if (F.compositeCounts) failMap['합성수 개수'] = 0; }

    if (F.consecutiveCounts !== undefined) failMap['연번 개수'] = 0;
    if (F.runFilters) {
        const rf = F.runFilters;
        if (rf.run3 && rf.run3.enabled !== false) failMap['연번(3연속)'] = 0; // enabled check logic
        if (rf.run4 && rf.run4.enabled !== false) failMap['연번(4연속)'] = 0;
        if (rf.run5 && rf.run5.enabled !== false) failMap['연번(5연속)'] = 0;
        if (rf.run6 && rf.run6.enabled !== false) failMap['연번(6연속)'] = 0;
    }
    if (F.numRanges) {
        for (const k in F.numRanges) {
            if (k === '1_10') failMap['번호대 1~10'] = 0;
            if (k === '11_20') failMap['번호대 11~20'] = 0;
            if (k === '21_30') failMap['번호대 21~30'] = 0;
            if (k === '31_40') failMap['번호대 31~40'] = 0;
            if (k === '41_45') failMap['번호대 41~45'] = 0;
        }
    }
    if (F.entropyRange) failMap['엔트로피'] = 0;
    if (F.palaceRanges) { for (let g = 1; g <= 9; g++) if (F.palaceRanges[`${g}궁`]) failMap[`9궁(${g}궁)`] = 0; }
    if (F.paperGroups) {
        for (let r = 1; r <= 7; r++) if (F.paperGroups[`가로${r}`]) failMap[`로또용지(가로${r})`] = 0;
        for (let c = 1; c <= 7; c++) if (F.paperGroups[`세로${c}`]) failMap[`로또용지(세로${c})`] = 0;
    }
    if (F.multipleRanges) {
        if (F.multipleRanges['3배수']) failMap['3배수'] = 0;
        if (F.multipleRanges['4배수']) failMap['4배수'] = 0;
        if (F.multipleRanges['5배수']) failMap['5배수'] = 0;
        if (F.multipleRanges['7배수']) failMap['7배수'] = 0;
        if (F.multipleRanges['8배수']) failMap['8배수'] = 0;
        if (F.multipleRanges['3·4배수']) failMap['3·4배수'] = 0;
        if (F.multipleRanges['3·5배수']) failMap['3·5배수'] = 0;
        if (F.multipleRanges['4·5배수']) failMap['4·5배수'] = 0;
        if (F.multipleRanges['배수외']) failMap['배수외'] = 0;
    }

    if (F.carryoverCounts) failMap['이월수'] = 0;
    if (F.carryoverBonusCounts) failMap['이월수(보너스포함)'] = 0;
    if (F.neighborCounts) failMap['이웃수'] = 0;

    for (const period of [5, 10, 15, 20]) {
        if (F[`hc${period}`]) {
            failMap[`핫콜드${period}(핫)`] = 0;
            failMap[`핫콜드${period}(중립)`] = 0;
            failMap[`핫콜드${period}(콜드)`] = 0;
        }
    }
    if (F.missingPeriodGroups) { for (let gi = 0; gi < F.missingPeriodGroups.length; gi++) failMap[`미출현기간(그룹${gi + 1})`] = 0; }
    if (F.missingCustomGroups) { for (let gi = 0; gi < F.missingCustomGroups.length; gi++) failMap[`미출현커스텀(${gi + 1})`] = 0; }

    if (F.customAnalysis) {
        for (let ci = 0; ci < F.customAnalysis.length; ci++) {
            failMap[`커스텀분석:${F.customAnalysis[ci].title || ci}`] = 0;
        }
    }
    if (F.regressionFilters) {
        for (let ri = 0; ri < F.regressionFilters.length; ri++) {
            failMap[`회귀분석(step${F.regressionFilters[ri].step})`] = 0;
        }
    }
    if (F.manualFilters) {
        for (let mi = 0; mi < F.manualFilters.length; mi++) {
            failMap[`수동필터:${F.manualFilters[mi].title || mi}`] = 0;
        }
    }

    for (let i = 0; i < TOTAL_COMBINATIONS; i++) {
        const o = i * 6;
        const stage = checkFiltersGetStage(
            combinations[o], combinations[o + 1], combinations[o + 2],
            combinations[o + 3], combinations[o + 4], combinations[o + 5], F
        );
        if (stage === null) { pass++; }
        else { failMap[stage] = (failMap[stage] || 0) + 1; }
    }

    // 정렬하지 않고 그대로 맵 객체 형태로 반환 (메인 스레드에서 정렬 처리)
    const failList = Object.entries(failMap).map(([name, count]) => ({ name, count }));

    return { pass, total: TOTAL_COMBINATIONS, failMap: failList };
}

// ──────────────────────────────────────────────────
// 5-B. 단계별 카운팅 — 각 필터를 하나씩 순서대로 적용해
//       단계마다 남은 조합 수 / 탈락 수를 집계 (단일 패스)
// ──────────────────────────────────────────────────
function buildStages(F) {
    const stages = [];

    // ── 바스켓 ──────────────────────────────────────
    if (F.fixedArr && F.fixedArr.length > 0) {
        const fa = F.fixedArr;
        stages.push({
            name: '바스켓 고정수', key: 'basket', fn(a, b, c, d, e, f) {
                for (let i = 0; i < fa.length; i++) {
                    const n = fa[i];
                    if (a !== n && b !== n && c !== n && d !== n && e !== n && f !== n) return false;
                }
                return true;
            }
        });
    }
    if (F.excludedLUT) {
        const lut = F.excludedLUT;
        stages.push({
            name: '바스켓 제외수', key: 'basket', fn(a, b, c, d, e, f) {
                return !(lut[a] || lut[b] || lut[c] || lut[d] || lut[e] || lut[f]);
            }
        });
    }

    // ── 총합 ────────────────────────────────────────
    if (F.sumMin !== undefined) {
        stages.push({
            name: '총합', key: 'total_sum', fn(a, b, c, d, e, f) {
                const s = a + b + c + d + e + f;
                if (s < F.sumMin || s > F.sumMax) return false;
                if (F.sumExcluded && F.sumExcluded.has(s)) return false;
                return true;
            }
        });
    }

    // ── 끝수합 ──────────────────────────────────────
    if (F.tailSumMin !== undefined) {
        stages.push({
            name: '끝수합', key: 'last_digit_sum', fn(a, b, c, d, e, f) {
                const ts = (a % 10) + (b % 10) + (c % 10) + (d % 10) + (e % 10) + (f % 10);
                if (ts < F.tailSumMin || ts > F.tailSumMax) return false;
                if (F.tailSumExcluded && F.tailSumExcluded.has(ts)) return false;
                return true;
            }
        });
    }

    // ── AC값 ────────────────────────────────────────
    if (F.acMin !== undefined) {
        stages.push({
            name: 'AC값', key: 'ac_value', fn(a, b, c, d, e, f) {
                const nums = [a, b, c, d, e, f];
                const gaps = new Set();
                for (let i = 0; i < 6; i++) for (let j = i + 1; j < 6; j++) gaps.add(Math.abs(nums[i] - nums[j]));
                const ac = gaps.size - 5;
                if (ac < F.acMin || ac > F.acMax) return false;
                if (F.acExcluded && F.acExcluded.has(ac)) return false;
                return true;
            }
        });
    }

    // ── 홀짝 패턴 ───────────────────────────────────
    if (F.oddEvenSet) {
        const oes = F.oddEvenSet, oex = F.oddEvenExcluded;
        stages.push({
            name: '홀짝 패턴', key: 'odd_even_pattern', fn(a, b, c, d, e, f) {
                const odd = (a % 2) + (b % 2) + (c % 2) + (d % 2) + (e % 2) + (f % 2);
                const r = `${odd}:${6 - odd}`;
                if (!oes.has(r)) return false;
                if (oex && oex.has(r)) return false;
                return true;
            }
        });
    }

    // ── 고저 패턴 ───────────────────────────────────
    if (F.highLowSet) {
        const hls = F.highLowSet, hlx = F.highLowExcluded;
        stages.push({
            name: '고저 패턴', key: 'high_low_pattern', fn(a, b, c, d, e, f) {
                let low = 0;
                if (a <= 22) low++; if (b <= 22) low++; if (c <= 22) low++;
                if (d <= 22) low++; if (e <= 22) low++; if (f <= 22) low++;
                const r = `${low}:${6 - low}`;
                if (!hls.has(r)) return false;
                if (hlx && hlx.has(r)) return false;
                return true;
            }
        });
    }

    // ── 연번 ────────────────────────────────────────
    if (F.consecutiveCounts !== undefined || F.runFilters) {
        const cons = F.consecutiveCounts, rf = F.runFilters;
        stages.push({
            name: '연번', key: 'consecutive_count', fn(a, b, c, d, e, f) {
                const arr6 = [a, b, c, d, e, f];
                let maxRun = 1, cur = 1, run3 = false, run4 = false, run5 = false, run6 = false;
                for (let i = 1; i < 6; i++) {
                    if (arr6[i] === arr6[i - 1] + 1) {
                        cur++;
                        if (cur === 3) run3 = true;
                        if (cur === 4) run4 = true;
                        if (cur === 5) run5 = true;
                        if (cur === 6) run6 = true;
                        if (cur > maxRun) maxRun = cur;
                    } else { cur = 1; }
                }
                if (cons && !cons.has(maxRun < 2 ? 0 : maxRun - 1)) return false;
                if (rf) {
                    if (rf.run3 && rf.run3.enabled && !run3) return false;
                    if (rf.run4 && rf.run4.enabled && !run4) return false;
                    if (rf.run5 && rf.run5.enabled && !run5) return false;
                    if (rf.run6 && rf.run6.enabled && !run6) return false;
                }
                return true;
            }
        });
    }

    // ── 이웃수 ──────────────────────────────────────
    if (F.neighborCounts && F.neighborLUT) {
        const lut = F.neighborLUT, nc = F.neighborCounts;
        stages.push({
            name: '이웃수', key: 'neighbor_number_patterns', fn(a, b, c, d, e, f) {
                const cnt = (lut[a] || 0) + (lut[b] || 0) + (lut[c] || 0) + (lut[d] || 0) + (lut[e] || 0) + (lut[f] || 0);
                return nc.has(cnt);
            }
        });
    }

    // ── 이월수 ──────────────────────────────────────
    if (F.carryoverCounts && F.carryoverLUT) {
        const lut = F.carryoverLUT, cc = F.carryoverCounts;
        stages.push({
            name: '이월수', key: 'carryover_count', fn(a, b, c, d, e, f) {
                const cnt = (lut[a] || 0) + (lut[b] || 0) + (lut[c] || 0) + (lut[d] || 0) + (lut[e] || 0) + (lut[f] || 0);
                return cc.has(cnt);
            }
        });
    }
    if (F.carryoverBonusCounts && F.carryoverBonusLUT) {
        const lut = F.carryoverBonusLUT, cc = F.carryoverBonusCounts;
        stages.push({
            name: '이월수(보너스포함)', key: 'carryover_count', fn(a, b, c, d, e, f) {
                const cnt = (lut[a] || 0) + (lut[b] || 0) + (lut[c] || 0) + (lut[d] || 0) + (lut[e] || 0) + (lut[f] || 0);
                return cc.has(cnt);
            }
        });
    }

    // ── 소수 ────────────────────────────────────────
    if (F.primeCounts || F.primeExcludedLUT) {
        const el = F.primeExcludedLUT, pc = F.primeCounts;
        stages.push({
            name: '소수', key: 'prime_number_patterns', fn(a, b, c, d, e, f) {
                if (el && (el[a] || el[b] || el[c] || el[d] || el[e] || el[f])) return false;
                if (pc) {
                    let cnt = PRIME_LUT[a] + PRIME_LUT[b] + PRIME_LUT[c] + PRIME_LUT[d] + PRIME_LUT[e] + PRIME_LUT[f];
                    if (el) { if (el[a] && PRIME_LUT[a]) cnt--; if (el[b] && PRIME_LUT[b]) cnt--; if (el[c] && PRIME_LUT[c]) cnt--; if (el[d] && PRIME_LUT[d]) cnt--; if (el[e] && PRIME_LUT[e]) cnt--; if (el[f] && PRIME_LUT[f]) cnt--; }
                    if (!pc.has(cnt)) return false;
                }
                return true;
            }
        });
    }

    // ── 합성수 ──────────────────────────────────────
    if (F.compositeCounts || F.compositeExcludedLUT) {
        const el = F.compositeExcludedLUT, cc = F.compositeCounts;
        stages.push({
            name: '합성수', key: 'composite_count', fn(a, b, c, d, e, f) {
                if (el && (el[a] || el[b] || el[c] || el[d] || el[e] || el[f])) return false;
                if (cc) {
                    let cnt = COMPOS_LUT[a] + COMPOS_LUT[b] + COMPOS_LUT[c] + COMPOS_LUT[d] + COMPOS_LUT[e] + COMPOS_LUT[f];
                    if (!cc.has(cnt)) return false;
                }
                return true;
            }
        });
    }

    // ── 삼각수 ──────────────────────────────────────
    if (F.triCounts || F.triExcludedLUT) {
        const el = F.triExcludedLUT, tc = F.triCounts;
        stages.push({
            name: '삼각수', key: 'triangular_number_patterns', fn(a, b, c, d, e, f) {
                if (el && (el[a] || el[b] || el[c] || el[d] || el[e] || el[f])) return false;
                if (tc) {
                    let cnt = TRI_LUT[a] + TRI_LUT[b] + TRI_LUT[c] + TRI_LUT[d] + TRI_LUT[e] + TRI_LUT[f];
                    if (!tc.has(cnt)) return false;
                }
                return true;
            }
        });
    }

    // ── 제곱수 ──────────────────────────────────────
    if (F.squareCounts || F.squareExcludedLUT) {
        const el = F.squareExcludedLUT, sc = F.squareCounts;
        stages.push({
            name: '제곱수', key: 'square_number_patterns', fn(a, b, c, d, e, f) {
                if (el && (el[a] || el[b] || el[c] || el[d] || el[e] || el[f])) return false;
                if (sc) {
                    let cnt = SQUARE_LUT[a] + SQUARE_LUT[b] + SQUARE_LUT[c] + SQUARE_LUT[d] + SQUARE_LUT[e] + SQUARE_LUT[f];
                    if (!sc.has(cnt)) return false;
                }
                return true;
            }
        });
    }

    // ── 동형수(쌍수) ────────────────────────────────
    if (F.twinCounts || F.twinExcludedLUT) {
        const el = F.twinExcludedLUT, twc = F.twinCounts;
        stages.push({
            name: '쌍수(동형수)', key: 'twin_number_patterns', fn(a, b, c, d, e, f) {
                if (el && (el[a] || el[b] || el[c] || el[d] || el[e] || el[f])) return false;
                if (twc) {
                    let cnt = TWIN_LUT[a] + TWIN_LUT[b] + TWIN_LUT[c] + TWIN_LUT[d] + TWIN_LUT[e] + TWIN_LUT[f];
                    if (!twc.has(cnt)) return false;
                }
                return true;
            }
        });
    }

    // ── 끝수 패턴 ───────────────────────────────────
    if (F.tailDigitRanges) {
        const tdr = F.tailDigitRanges;
        stages.push({
            name: '끝수 패턴', key: 'tail_digit_patterns', fn(a, b, c, d, e, f) {
                const td = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0];
                td[a % 10]++; td[b % 10]++; td[c % 10]++; td[d % 10]++; td[e % 10]++; td[f % 10]++;
                for (const digit in tdr) {
                    const r = tdr[digit], cnt = td[parseInt(digit)];
                    if (r.min !== undefined && cnt < r.min) return false;
                    if (r.max !== undefined && cnt > r.max) return false;
                }
                return true;
            }
        });
    }

    // ── 배수 패턴 ───────────────────────────────────
    if (F.multipleRanges) {
        const mr = F.multipleRanges;
        stages.push({
            name: '배수 패턴', key: 'multiple_3_count', fn(a, b, c, d, e, f) {
                const m3a = M3_LUT[a], m3b = M3_LUT[b], m3c = M3_LUT[c], m3d = M3_LUT[d], m3e = M3_LUT[e], m3f = M3_LUT[f];
                const m4a = M4_LUT[a], m4b = M4_LUT[b], m4c = M4_LUT[c], m4d = M4_LUT[d], m4e = M4_LUT[e], m4f = M4_LUT[f];
                const m5a = M5_LUT[a], m5b = M5_LUT[b], m5c = M5_LUT[c], m5d = M5_LUT[d], m5e = M5_LUT[e], m5f = M5_LUT[f];
                const m7a = M7_LUT[a], m7b = M7_LUT[b], m7c = M7_LUT[c], m7d = M7_LUT[d], m7e = M7_LUT[e], m7f = M7_LUT[f];
                const m8a = M8_LUT[a], m8b = M8_LUT[b], m8c = M8_LUT[c], m8d = M8_LUT[d], m8e = M8_LUT[e], m8f = M8_LUT[f];
                const m3 = m3a + m3b + m3c + m3d + m3e + m3f;
                const m4 = m4a + m4b + m4c + m4d + m4e + m4f;
                const m5 = m5a + m5b + m5c + m5d + m5e + m5f;
                const m7 = m7a + m7b + m7c + m7d + m7e + m7f;
                const m8 = m8a + m8b + m8c + m8d + m8e + m8f;
                const r3 = mr['3배수']; if (r3 && r3.min !== undefined && (m3 < r3.min || m3 > r3.max)) return false;
                const r4 = mr['4배수']; if (r4 && r4.min !== undefined && (m4 < r4.min || m4 > r4.max)) return false;
                const r5 = mr['5배수']; if (r5 && r5.min !== undefined && (m5 < r5.min || m5 > r5.max)) return false;
                const r7 = mr['7배수']; if (r7 && r7.min !== undefined && (m7 < r7.min || m7 > r7.max)) return false;
                const r8 = mr['8배수']; if (r8 && r8.min !== undefined && (m8 < r8.min || m8 > r8.max)) return false;
                const cnt34 = (m3a && m4a ? 1 : 0) + (m3b && m4b ? 1 : 0) + (m3c && m4c ? 1 : 0) + (m3d && m4d ? 1 : 0) + (m3e && m4e ? 1 : 0) + (m3f && m4f ? 1 : 0);
                const r34 = mr['3·4배수']; if (r34 && r34.min !== undefined && (cnt34 < r34.min || cnt34 > r34.max)) return false;
                const cnt35 = (m3a && m5a ? 1 : 0) + (m3b && m5b ? 1 : 0) + (m3c && m5c ? 1 : 0) + (m3d && m5d ? 1 : 0) + (m3e && m5e ? 1 : 0) + (m3f && m5f ? 1 : 0);
                const r35 = mr['3·5배수']; if (r35 && r35.min !== undefined && (cnt35 < r35.min || cnt35 > r35.max)) return false;
                const cnt45 = (m4a && m5a ? 1 : 0) + (m4b && m5b ? 1 : 0) + (m4c && m5c ? 1 : 0) + (m4d && m5d ? 1 : 0) + (m4e && m5e ? 1 : 0) + (m4f && m5f ? 1 : 0);
                const r45b = mr['4·5배수']; if (r45b && r45b.min !== undefined && (cnt45 < r45b.min || cnt45 > r45b.max)) return false;
                const cntO = (!m3a && !m4a && !m5a && !m7a && !m8a ? 1 : 0) + (!m3b && !m4b && !m5b && !m7b && !m8b ? 1 : 0) +
                    (!m3c && !m4c && !m5c && !m7c && !m8c ? 1 : 0) + (!m3d && !m4d && !m5d && !m7d && !m8d ? 1 : 0) +
                    (!m3e && !m4e && !m5e && !m7e && !m8e ? 1 : 0) + (!m3f && !m4f && !m5f && !m7f && !m8f ? 1 : 0);
                const rO = mr['배수외']; if (rO && rO.min !== undefined && (cntO < rO.min || cntO > rO.max)) return false;
                return true;
            }
        });
    }

    // ── 번호대 ──────────────────────────────────────
    if (F.numRanges) {
        const ranges = F.numRanges;
        stages.push({
            name: '번호대', key: 'number_range_patterns', fn(a, b, c, d, e, f) {
                let c1 = 0, c2 = 0, c3 = 0, c4 = 0, c5 = 0;
                const cnt = n => { if (n <= 10) c1++; else if (n <= 20) c2++; else if (n <= 30) c3++; else if (n <= 40) c4++; else c5++; };
                cnt(a); cnt(b); cnt(c); cnt(d); cnt(e); cnt(f);
                const r10 = ranges['1_10'], r20 = ranges['11_20'], r30 = ranges['21_30'], r40 = ranges['31_40'], r45 = ranges['41_45'];
                if (r10 && r10.min !== undefined && (c1 < r10.min || c1 > r10.max)) return false;
                if (r20 && r20.min !== undefined && (c2 < r20.min || c2 > r20.max)) return false;
                if (r30 && r30.min !== undefined && (c3 < r30.min || c3 > r30.max)) return false;
                if (r40 && r40.min !== undefined && (c4 < r40.min || c4 > r40.max)) return false;
                if (r45 && r45.min !== undefined && (c5 < r45.min || c5 > r45.max)) return false;
                return true;
            }
        });
    }

    // ── 엔트로피 ────────────────────────────────────
    if (F.entropyRange) {
        const eMin = parseFloat(F.entropyRange.min), eMax = parseFloat(F.entropyRange.max);
        stages.push({
            name: '엔트로피', key: 'entropy', fn(a, b, c, d, e, f) {
                let c1 = 0, c2 = 0, c3 = 0, c4 = 0, c5 = 0;
                if (a <= 10) c1++; else if (a <= 20) c2++; else if (a <= 30) c3++; else if (a <= 40) c4++; else c5++;
                if (b <= 10) c1++; else if (b <= 20) c2++; else if (b <= 30) c3++; else if (b <= 40) c4++; else c5++;
                if (c <= 10) c1++; else if (c <= 20) c2++; else if (c <= 30) c3++; else if (c <= 40) c4++; else c5++;
                if (d <= 10) c1++; else if (d <= 20) c2++; else if (d <= 30) c3++; else if (d <= 40) c4++; else c5++;
                if (e <= 10) c1++; else if (e <= 20) c2++; else if (e <= 30) c3++; else if (e <= 40) c4++; else c5++;
                if (f <= 10) c1++; else if (f <= 20) c2++; else if (f <= 30) c3++; else if (f <= 40) c4++; else c5++;
                const bins = [c1, c2, c3, c4, c5];
                let ent = 0;
                for (let i = 0; i < 5; i++) { if (bins[i] > 0) { const p = bins[i] / 6; ent -= p * Math.log2(p); } }
                if (!isNaN(eMin) && ent < eMin) return false;
                if (!isNaN(eMax) && ent > eMax) return false;
                return true;
            }
        });
    }

    // ── 9궁 ─────────────────────────────────────────
    if (F.palaceRanges) {
        const pr = F.palaceRanges;
        stages.push({
            name: '9궁(마방진)', key: 'magic_square_pattern', fn(a, b, c, d, e, f) {
                const pc = new Uint8Array(10);
                pc[PALACE_LUT[a]]++; pc[PALACE_LUT[b]]++; pc[PALACE_LUT[c]]++;
                pc[PALACE_LUT[d]]++; pc[PALACE_LUT[e]]++; pc[PALACE_LUT[f]]++;
                for (let g = 1; g <= 9; g++) {
                    const r = pr[`${g}궁`]; if (!r) continue;
                    if (r.min !== undefined && pc[g] < r.min) return false;
                    if (r.max !== undefined && pc[g] > r.max) return false;
                }
                return true;
            }
        });
    }

    // ── 로또용지 ────────────────────────────────────
    if (F.paperGroups) {
        const pg = F.paperGroups;
        stages.push({
            name: '로또용지', key: 'lotto_paper_pattern', fn(a, b, c, d, e, f) {
                const gc = new Uint8Array(8), sc = new Uint8Array(8);
                gc[GARO_LUT[a]]++; gc[GARO_LUT[b]]++; gc[GARO_LUT[c]]++; gc[GARO_LUT[d]]++; gc[GARO_LUT[e]]++; gc[GARO_LUT[f]]++;
                sc[SERO_LUT[a]]++; sc[SERO_LUT[b]]++; sc[SERO_LUT[c]]++; sc[SERO_LUT[d]]++; sc[SERO_LUT[e]]++; sc[SERO_LUT[f]]++;
                for (let row = 1; row <= 7; row++) { const r = pg[`가로${row}`]; if (!r) continue; if (r.min !== undefined && gc[row] < r.min) return false; if (r.max !== undefined && gc[row] > r.max) return false; }
                for (let col = 1; col <= 7; col++) { const r = pg[`세로${col}`]; if (!r) continue; if (r.min !== undefined && sc[col] < r.min) return false; if (r.max !== undefined && sc[col] > r.max) return false; }
                return true;
            }
        });
    }

    // ── Hot/Cold ─────────────────────────────────────
    for (const period of [5, 10, 15, 20]) {
        const hc = F[`hc${period}`];
        if (!hc) continue;
        const lh = hc.hotLUT, lw = hc.warmLUT, lc = hc.coldLUT;
        const hr = hc.hotRange, wr = hc.warmRange, cr = hc.coldRange;
        stages.push({
            name: `핫콜드(${period}회)`, key: `hot_cold_${period}`, fn(a, b, c, d, e, f) {
                const hCnt = lh ? (lh[a] || 0) + (lh[b] || 0) + (lh[c] || 0) + (lh[d] || 0) + (lh[e] || 0) + (lh[f] || 0) : 0;
                const wCnt = lw ? (lw[a] || 0) + (lw[b] || 0) + (lw[c] || 0) + (lw[d] || 0) + (lw[e] || 0) + (lw[f] || 0) : 0;
                const cCnt = lc ? (lc[a] || 0) + (lc[b] || 0) + (lc[c] || 0) + (lc[d] || 0) + (lc[e] || 0) + (lc[f] || 0) : 0;
                if (hCnt < hr[0] || hCnt > hr[1]) return false;
                if (wCnt < wr[0] || wCnt > wr[1]) return false;
                if (cCnt < cr[0] || cCnt > cr[1]) return false;
                return true;
            }
        });
    }

    // ── 미출현 기간 ──────────────────────────────────
    if (F.missingPeriodGroups) {
        const mpg = F.missingPeriodGroups;
        stages.push({
            name: '미출현 기간', key: 'missing_period', fn(a, b, c, d, e, f) {
                for (let gi = 0; gi < mpg.length; gi++) {
                    const g = mpg[gi]; if (!g.nums || g.nums.length === 0) continue;
                    const nums = g.nums; let cnt = 0;
                    for (let ni = 0; ni < nums.length; ni++) { const n = nums[ni]; if (n === a || n === b || n === c || n === d || n === e || n === f) cnt++; }
                    if (g.min !== undefined && cnt < g.min) return false;
                    if (g.max !== undefined && cnt > g.max) return false;
                }
                return true;
            }
        });
    }

    // ── 미출현 커스텀 ────────────────────────────────
    if (F.missingCustomGroups) {
        const mcg = F.missingCustomGroups;
        stages.push({
            name: '미출현 커스텀', key: 'missing_custom_filter', fn(a, b, c, d, e, f) {
                for (let gi = 0; gi < mcg.length; gi++) {
                    const g = mcg[gi]; if (!g.lut) continue;
                    const cnt = (g.lut[a] || 0) + (g.lut[b] || 0) + (g.lut[c] || 0) + (g.lut[d] || 0) + (g.lut[e] || 0) + (g.lut[f] || 0);
                    if (cnt < g.min || cnt > g.max) return false;
                }
                return true;
            }
        });
    }

    // ── 회귀 분석 필터 (각각 개별 단계) ─────────────
    if (F.regressionFilters) {
        F.regressionFilters.forEach(rf => {
            if (!rf.lut) return;
            const lut = rf.lut, mn = rf.min, mx = rf.max, step = rf.step;
            stages.push({
                name: `회귀분석(step${step})`, key: `regression_${step}`, fn(a, b, c, d, e, f) {
                    const cnt = (lut[a] || 0) + (lut[b] || 0) + (lut[c] || 0) + (lut[d] || 0) + (lut[e] || 0) + (lut[f] || 0);
                    return cnt >= mn && cnt <= mx;
                }
            });
        });
    }

    // ── 커스텀 분석 필터 (각각 개별 단계) ────────────
    if (F.customAnalysis) {
        F.customAnalysis.forEach(cf => {
            if (!cf.lut) return;
            const lut = cf.lut, mn = cf.min, mx = cf.max, name = cf.title || '커스텀', cfId = cf.id;
            stages.push({
                name: `커스텀:${name}`, key: `custom_${cfId}`, fn(a, b, c, d, e, f) {
                    const cnt = (lut[a] || 0) + (lut[b] || 0) + (lut[c] || 0) + (lut[d] || 0) + (lut[e] || 0) + (lut[f] || 0);
                    return cnt >= mn && cnt <= mx;
                }
            });
        });
    }

    // ── 수동 필터 (각각 개별 단계) ───────────────────
    if (F.manualFilters) {
        F.manualFilters.forEach(mf => {
            const lut = mf.lut, mn = mf.min, mx = mf.max, name = mf.title || '수동필터', mfId = mf.id;
            stages.push({
                name: `수동:${name}`, key: `manual_${mfId}`, fn(a, b, c, d, e, f) {
                    if (!lut) return mn <= 0; // 번호 미선택 시: min이 0이면 통과
                    const cnt = (lut[a] || 0) + (lut[b] || 0) + (lut[c] || 0) + (lut[d] || 0) + (lut[e] || 0) + (lut[f] || 0);
                    return cnt >= mn && cnt <= mx;
                }
            });
        });
    }

    return stages;
}

function stepCountFilters(rawFilters) {
    if (!combinations) return null;
    const F = parseFilters(rawFilters);
    const stages = buildStages(F);
    const N = stages.length;
    if (N === 0) return { steps: [], total: TOTAL_COMBINATIONS, pass: TOTAL_COMBINATIONS };

    // 각 stage별 탈락 수 (failAt[i] = stage i에서 탈락한 조합 수, failAt[N] = 전부 통과)
    const failAt = new Int32Array(N + 1);

    for (let i = 0; i < TOTAL_COMBINATIONS; i++) {
        const o = i * 6;
        const a = combinations[o], b = combinations[o + 1], c = combinations[o + 2];
        const d = combinations[o + 3], e = combinations[o + 4], f = combinations[o + 5];
        let fi = 0;
        for (; fi < N; fi++) {
            if (!stages[fi].fn(a, b, c, d, e, f)) break;
        }
        failAt[fi]++;
    }

    // 누적 통과 수 계산
    const steps = [];
    let survivors = TOTAL_COMBINATIONS;
    for (let i = 0; i < N; i++) {
        const elim = failAt[i];
        survivors -= elim;
        steps.push({
            name: stages[i].name,
            key: stages[i].key,
            survivors,
            eliminated: elim,
            cumElim: TOTAL_COMBINATIONS - survivors
        });
    }

    return { steps, total: TOTAL_COMBINATIONS, pass: survivors };
}

// ──────────────────────────────────────────────────
// 5. 독립 카운팅 — 각 필터를 단독으로 적용했을 때 통과 수
// ──────────────────────────────────────────────────
function countIndependent(rawFilters) {
    if (!combinations) return {};
    const F = parseFilters(rawFilters);
    const counts = {};

    // 활성 필터별 카운터 초기화
    if (rawFilters.sumRange) counts.sumRange = 0;
    if (rawFilters.tailSumRange) counts.tailSumRange = 0;
    if (rawFilters.acRange) counts.acRange = 0;
    if (rawFilters.oddEvenPatterns && rawFilters.oddEvenPatterns.length > 0) counts.oddEvenPatterns = 0;
    if (rawFilters.highLowPatterns && rawFilters.highLowPatterns.length > 0) counts.highLowPatterns = 0;
    if (rawFilters.tailDigitRanges) counts.tailDigitRanges = 0;
    if (rawFilters.primeFilter) counts.primeFilter = 0;
    if (rawFilters.squareFilter) counts.squareFilter = 0;
    if (rawFilters.triangularFilter) counts.triangularFilter = 0;
    if (rawFilters.twinFilter) counts.twinFilter = 0;
    if (rawFilters.compositeFilter) counts.compositeFilter = 0;
    if (rawFilters.consecutiveFilter) counts.consecutiveFilter = 0;
    if (rawFilters.numberRangeFilter) counts.numberRangeFilter = 0;
    if (rawFilters.magicSquareFilter) counts.magicSquareFilter = 0;
    if (rawFilters.lottoPaperFilter) counts.lottoPaperFilter = 0;
    if (rawFilters.multipleFilter) counts.multipleFilter = 0;
    if (rawFilters.carryoverFilter) counts.carryoverFilter = 0;
    if (rawFilters.neighborFilter) counts.neighborFilter = 0;
    for (const period of [5, 10, 15, 20]) {
        if (rawFilters[`hotCold${period}`]) counts[`hotCold${period}`] = 0;
    }
    if (rawFilters.missingPeriodFilter) counts.missingPeriodFilter = 0;
    if (rawFilters.missingCustomFilter && rawFilters.missingCustomFilter.length > 0) counts.missingCustomFilter = 0;

    // 회귀: step별 LUT 사전 파싱
    const regrParsed = (rawFilters.regressionFilters || []).map(r => ({
        key: `regression_${r.step}`,
        lut: makeLUT(r.drawNums),
        min: r.min,
        max: r.max
    }));
    regrParsed.forEach(r => { counts[r.key] = 0; });

    // 커스텀 분석: id별 LUT 사전 파싱
    const customParsed = (rawFilters.customAnalysisFilters || []).map(c => ({
        key: `custom_${c.id}`,
        lut: makeLUT(c.targetNums),
        min: c.min,
        max: c.max
    }));
    customParsed.forEach(c => { counts[c.key] = 0; });

    // 수동 필터: id별 LUT 사전 파싱
    const manualParsed = (rawFilters.manualFilters || []).map(m => ({
        key: `manual_${m.id}`,
        lut: makeLUT(m.selectedNums),
        min: m.min !== undefined ? m.min : 1,
        max: m.max !== undefined ? m.max : 6
    }));
    manualParsed.forEach(m => { counts[m.key] = 0; });

    for (let i = 0; i < TOTAL_COMBINATIONS; i++) {
        const o = i * 6;
        const a = combinations[o], b = combinations[o+1], c = combinations[o+2];
        const d = combinations[o+3], e = combinations[o+4], f = combinations[o+5];

        // 총합
        if (counts.sumRange !== undefined) {
            const sum = a + b + c + d + e + f;
            if (sum >= F.sumMin && sum <= F.sumMax && (!F.sumExcluded || !F.sumExcluded.has(sum))) counts.sumRange++;
        }

        // 끝수합
        if (counts.tailSumRange !== undefined) {
            const ts = (a%10)+(b%10)+(c%10)+(d%10)+(e%10)+(f%10);
            if (ts >= F.tailSumMin && ts <= F.tailSumMax && (!F.tailSumExcluded || !F.tailSumExcluded.has(ts))) counts.tailSumRange++;
        }

        // AC값
        if (counts.acRange !== undefined) {
            const gaps = new Set();
            gaps.add(Math.abs(a-b)); gaps.add(Math.abs(a-c)); gaps.add(Math.abs(a-d)); gaps.add(Math.abs(a-e)); gaps.add(Math.abs(a-f));
            gaps.add(Math.abs(b-c)); gaps.add(Math.abs(b-d)); gaps.add(Math.abs(b-e)); gaps.add(Math.abs(b-f));
            gaps.add(Math.abs(c-d)); gaps.add(Math.abs(c-e)); gaps.add(Math.abs(c-f));
            gaps.add(Math.abs(d-e)); gaps.add(Math.abs(d-f));
            gaps.add(Math.abs(e-f));
            const acVal = gaps.size - 5;
            if (acVal >= F.acMin && acVal <= F.acMax && (!F.acExcluded || !F.acExcluded.has(acVal))) counts.acRange++;
        }

        // 홀짝
        if (counts.oddEvenPatterns !== undefined) {
            const odd = (a%2)+(b%2)+(c%2)+(d%2)+(e%2)+(f%2);
            const ratio = `${odd}:${6-odd}`;
            if (F.oddEvenSet.has(ratio) && (!F.oddEvenExcluded || !F.oddEvenExcluded.has(ratio))) counts.oddEvenPatterns++;
        }

        // 고저
        if (counts.highLowPatterns !== undefined) {
            let low = 0;
            if (a<=22) low++; if (b<=22) low++; if (c<=22) low++;
            if (d<=22) low++; if (e<=22) low++; if (f<=22) low++;
            const ratio = `${low}:${6-low}`;
            if (F.highLowSet.has(ratio) && (!F.highLowExcluded || !F.highLowExcluded.has(ratio))) counts.highLowPatterns++;
        }

        // 끝수 패턴
        if (counts.tailDigitRanges !== undefined) {
            const td = new Uint8Array(10);
            td[a%10]++; td[b%10]++; td[c%10]++; td[d%10]++; td[e%10]++; td[f%10]++;
            let pass = true;
            const ranges = F.tailDigitRanges;
            for (const digit in ranges) {
                const r = ranges[digit];
                if (r.min === undefined && r.max === undefined) continue;
                const cnt = td[parseInt(digit)];
                if ((r.min !== undefined && cnt < r.min) || (r.max !== undefined && cnt > r.max)) { pass = false; break; }
            }
            if (pass) counts.tailDigitRanges++;
        }

        // 소수
        if (counts.primeFilter !== undefined) {
            const el = F.primeExcludedLUT;
            if (!el || (!el[a]&&!el[b]&&!el[c]&&!el[d]&&!el[e]&&!el[f])) {
                if (F.primeCounts) {
                    let cnt = PRIME_LUT[a]+PRIME_LUT[b]+PRIME_LUT[c]+PRIME_LUT[d]+PRIME_LUT[e]+PRIME_LUT[f];
                    if (el) { if(el[a]&&PRIME_LUT[a])cnt--; if(el[b]&&PRIME_LUT[b])cnt--; if(el[c]&&PRIME_LUT[c])cnt--; if(el[d]&&PRIME_LUT[d])cnt--; if(el[e]&&PRIME_LUT[e])cnt--; if(el[f]&&PRIME_LUT[f])cnt--; }
                    if (F.primeCounts.has(cnt)) counts.primeFilter++;
                } else { counts.primeFilter++; }
            }
        }

        // 제곱수
        if (counts.squareFilter !== undefined) {
            const el = F.squareExcludedLUT;
            if (!el || (!el[a]&&!el[b]&&!el[c]&&!el[d]&&!el[e]&&!el[f])) {
                if (F.squareCounts) {
                    let cnt = SQUARE_LUT[a]+SQUARE_LUT[b]+SQUARE_LUT[c]+SQUARE_LUT[d]+SQUARE_LUT[e]+SQUARE_LUT[f];
                    if (el) { if(el[a]&&SQUARE_LUT[a])cnt--; if(el[b]&&SQUARE_LUT[b])cnt--; if(el[c]&&SQUARE_LUT[c])cnt--; if(el[d]&&SQUARE_LUT[d])cnt--; if(el[e]&&SQUARE_LUT[e])cnt--; if(el[f]&&SQUARE_LUT[f])cnt--; }
                    if (F.squareCounts.has(cnt)) counts.squareFilter++;
                } else { counts.squareFilter++; }
            }
        }

        // 삼각수
        if (counts.triangularFilter !== undefined) {
            const el = F.triExcludedLUT;
            if (!el || (!el[a]&&!el[b]&&!el[c]&&!el[d]&&!el[e]&&!el[f])) {
                if (F.triCounts) {
                    let cnt = TRI_LUT[a]+TRI_LUT[b]+TRI_LUT[c]+TRI_LUT[d]+TRI_LUT[e]+TRI_LUT[f];
                    if (el) { if(el[a]&&TRI_LUT[a])cnt--; if(el[b]&&TRI_LUT[b])cnt--; if(el[c]&&TRI_LUT[c])cnt--; if(el[d]&&TRI_LUT[d])cnt--; if(el[e]&&TRI_LUT[e])cnt--; if(el[f]&&TRI_LUT[f])cnt--; }
                    if (F.triCounts.has(cnt)) counts.triangularFilter++;
                } else { counts.triangularFilter++; }
            }
        }

        // 쌍수
        if (counts.twinFilter !== undefined) {
            const el = F.twinExcludedLUT;
            if (!el || (!el[a]&&!el[b]&&!el[c]&&!el[d]&&!el[e]&&!el[f])) {
                if (F.twinCounts) {
                    let cnt = TWIN_LUT[a]+TWIN_LUT[b]+TWIN_LUT[c]+TWIN_LUT[d]+TWIN_LUT[e]+TWIN_LUT[f];
                    if (el) { if(el[a]&&TWIN_LUT[a])cnt--; if(el[b]&&TWIN_LUT[b])cnt--; if(el[c]&&TWIN_LUT[c])cnt--; if(el[d]&&TWIN_LUT[d])cnt--; if(el[e]&&TWIN_LUT[e])cnt--; if(el[f]&&TWIN_LUT[f])cnt--; }
                    if (F.twinCounts.has(cnt)) counts.twinFilter++;
                } else { counts.twinFilter++; }
            }
        }

        // 합성수
        if (counts.compositeFilter !== undefined) {
            const el = F.compositeExcludedLUT;
            if (!el || (!el[a]&&!el[b]&&!el[c]&&!el[d]&&!el[e]&&!el[f])) {
                if (F.compositeCounts) {
                    let cnt = COMPOS_LUT[a]+COMPOS_LUT[b]+COMPOS_LUT[c]+COMPOS_LUT[d]+COMPOS_LUT[e]+COMPOS_LUT[f];
                    if (el) { if(el[a]&&COMPOS_LUT[a])cnt--; if(el[b]&&COMPOS_LUT[b])cnt--; if(el[c]&&COMPOS_LUT[c])cnt--; if(el[d]&&COMPOS_LUT[d])cnt--; if(el[e]&&COMPOS_LUT[e])cnt--; if(el[f]&&COMPOS_LUT[f])cnt--; }
                    if (F.compositeCounts.has(cnt)) counts.compositeFilter++;
                } else { counts.compositeFilter++; }
            }
        }

        // 연번
        if (counts.consecutiveFilter !== undefined) {
            const arr6 = [a, b, c, d, e, f];
            let maxRun = 1, curRun = 1;
            let run3 = false, run4 = false, run5 = false, run6 = false;
            for (let ii = 1; ii < 6; ii++) {
                if (arr6[ii] === arr6[ii-1]+1) {
                    curRun++;
                    if (curRun === 3) run3 = true;
                    if (curRun === 4) run4 = true;
                    if (curRun === 5) run5 = true;
                    if (curRun === 6) run6 = true;
                    if (curRun > maxRun) maxRun = curRun;
                } else { curRun = 1; }
            }
            let pass = true;
            if (F.consecutiveCounts && !F.consecutiveCounts.has(maxRun < 2 ? 0 : maxRun - 1)) pass = false;
            if (pass && F.runFilters) {
                const rf = F.runFilters;
                if (rf.run3 && rf.run3.enabled !== undefined && rf.run3.enabled && !run3) pass = false;
                if (pass && rf.run4 && rf.run4.enabled !== undefined && rf.run4.enabled && !run4) pass = false;
                if (pass && rf.run5 && rf.run5.enabled !== undefined && rf.run5.enabled && !run5) pass = false;
                if (pass && rf.run6 && rf.run6.enabled !== undefined && rf.run6.enabled && !run6) pass = false;
            }
            if (pass) counts.consecutiveFilter++;
        }

        // 번호대 + 엔트로피
        if (counts.numberRangeFilter !== undefined) {
            let c1=0, c2=0, c3=0, c4=0, c5=0;
            const cntN = (n) => { if(n<=10)c1++; else if(n<=20)c2++; else if(n<=30)c3++; else if(n<=40)c4++; else c5++; };
            cntN(a); cntN(b); cntN(c); cntN(d); cntN(e); cntN(f);
            let pass = true;
            const ranges = F.numRanges;
            if (ranges) {
                const r10=ranges['1_10']; if (r10&&r10.min!==undefined&&(c1<r10.min||c1>r10.max)) pass=false;
                if (pass) { const r20=ranges['11_20']; if (r20&&r20.min!==undefined&&(c2<r20.min||c2>r20.max)) pass=false; }
                if (pass) { const r30=ranges['21_30']; if (r30&&r30.min!==undefined&&(c3<r30.min||c3>r30.max)) pass=false; }
                if (pass) { const r40=ranges['31_40']; if (r40&&r40.min!==undefined&&(c4<r40.min||c4>r40.max)) pass=false; }
                if (pass) { const r45=ranges['41_45']; if (r45&&r45.min!==undefined&&(c5<r45.min||c5>r45.max)) pass=false; }
            }
            if (pass && F.entropyRange) {
                const eMin=parseFloat(F.entropyRange.min), eMax=parseFloat(F.entropyRange.max);
                if (!isNaN(eMin)||!isNaN(eMax)) {
                    let ent = 0;
                    [c1,c2,c3,c4,c5].forEach(x => { if(x>0){const p=x/6; ent-=p*Math.log2(p);} });
                    ent = Math.round(ent*100)/100;
                    if (!isNaN(eMin)&&ent<eMin) pass=false;
                    if (!isNaN(eMax)&&ent>eMax) pass=false;
                }
            }
            if (pass) counts.numberRangeFilter++;
        }

        // 9궁
        if (counts.magicSquareFilter !== undefined) {
            const pc = new Uint8Array(10);
            pc[PALACE_LUT[a]]++; pc[PALACE_LUT[b]]++; pc[PALACE_LUT[c]]++;
            pc[PALACE_LUT[d]]++; pc[PALACE_LUT[e]]++; pc[PALACE_LUT[f]]++;
            let pass = true;
            const pr = F.palaceRanges;
            for (let g = 1; g <= 9; g++) {
                const r = pr[`${g}궁`];
                if (!r) continue;
                if ((r.min!==undefined&&pc[g]<r.min)||(r.max!==undefined&&pc[g]>r.max)) { pass=false; break; }
            }
            if (pass) counts.magicSquareFilter++;
        }

        // 로또용지
        if (counts.lottoPaperFilter !== undefined) {
            const gc = new Uint8Array(8), sc = new Uint8Array(8);
            gc[GARO_LUT[a]]++; gc[GARO_LUT[b]]++; gc[GARO_LUT[c]]++;
            gc[GARO_LUT[d]]++; gc[GARO_LUT[e]]++; gc[GARO_LUT[f]]++;
            sc[SERO_LUT[a]]++; sc[SERO_LUT[b]]++; sc[SERO_LUT[c]]++;
            sc[SERO_LUT[d]]++; sc[SERO_LUT[e]]++; sc[SERO_LUT[f]]++;
            let pass = true;
            const pg = F.paperGroups;
            for (let row=1; row<=7&&pass; row++) { const r=pg[`가로${row}`]; if(r&&((r.min!==undefined&&gc[row]<r.min)||(r.max!==undefined&&gc[row]>r.max))) pass=false; }
            for (let col=1; col<=7&&pass; col++) { const r=pg[`세로${col}`]; if(r&&((r.min!==undefined&&sc[col]<r.min)||(r.max!==undefined&&sc[col]>r.max))) pass=false; }
            if (pass) counts.lottoPaperFilter++;
        }

        // 배수
        if (counts.multipleFilter !== undefined) {
            const m3a=M3_LUT[a],m3b=M3_LUT[b],m3c=M3_LUT[c],m3d=M3_LUT[d],m3e=M3_LUT[e],m3f=M3_LUT[f];
            const m4a=M4_LUT[a],m4b=M4_LUT[b],m4c=M4_LUT[c],m4d=M4_LUT[d],m4e=M4_LUT[e],m4f=M4_LUT[f];
            const m5a=M5_LUT[a],m5b=M5_LUT[b],m5c=M5_LUT[c],m5d=M5_LUT[d],m5e=M5_LUT[e],m5f=M5_LUT[f];
            const m7a=M7_LUT[a],m7b=M7_LUT[b],m7c=M7_LUT[c],m7d=M7_LUT[d],m7e=M7_LUT[e],m7f=M7_LUT[f];
            const m8a=M8_LUT[a],m8b=M8_LUT[b],m8c=M8_LUT[c],m8d=M8_LUT[d],m8e=M8_LUT[e],m8f=M8_LUT[f];
            const cnt3=m3a+m3b+m3c+m3d+m3e+m3f, cnt4=m4a+m4b+m4c+m4d+m4e+m4f, cnt5=m5a+m5b+m5c+m5d+m5e+m5f;
            const cnt7=m7a+m7b+m7c+m7d+m7e+m7f, cnt8=m8a+m8b+m8c+m8d+m8e+m8f;
            const mr=F.multipleRanges;
            let pass=true;
            const r3=mr['3배수']; if(r3&&r3.min!==undefined&&(cnt3<r3.min||cnt3>r3.max)) pass=false;
            if(pass){const r4=mr['4배수']; if(r4&&r4.min!==undefined&&(cnt4<r4.min||cnt4>r4.max)) pass=false;}
            if(pass){const r5=mr['5배수']; if(r5&&r5.min!==undefined&&(cnt5<r5.min||cnt5>r5.max)) pass=false;}
            if(pass){const r7=mr['7배수']; if(r7&&r7.min!==undefined&&(cnt7<r7.min||cnt7>r7.max)) pass=false;}
            if(pass){const r8=mr['8배수']; if(r8&&r8.min!==undefined&&(cnt8<r8.min||cnt8>r8.max)) pass=false;}
            if(pass){const cnt34=(m3a&&m4a?1:0)+(m3b&&m4b?1:0)+(m3c&&m4c?1:0)+(m3d&&m4d?1:0)+(m3e&&m4e?1:0)+(m3f&&m4f?1:0); const r34=mr['3·4배수']; if(r34&&r34.min!==undefined&&(cnt34<r34.min||cnt34>r34.max)) pass=false;}
            if(pass){const cnt35=(m3a&&m5a?1:0)+(m3b&&m5b?1:0)+(m3c&&m5c?1:0)+(m3d&&m5d?1:0)+(m3e&&m5e?1:0)+(m3f&&m5f?1:0); const r35=mr['3·5배수']; if(r35&&r35.min!==undefined&&(cnt35<r35.min||cnt35>r35.max)) pass=false;}
            if(pass){const cnt45=(m4a&&m5a?1:0)+(m4b&&m5b?1:0)+(m4c&&m5c?1:0)+(m4d&&m5d?1:0)+(m4e&&m5e?1:0)+(m4f&&m5f?1:0); const r45b=mr['4·5배수']; if(r45b&&r45b.min!==undefined&&(cnt45<r45b.min||cnt45>r45b.max)) pass=false;}
            if(pass){const cntO=(!m3a&&!m4a&&!m5a&&!m7a&&!m8a?1:0)+(!m3b&&!m4b&&!m5b&&!m7b&&!m8b?1:0)+(!m3c&&!m4c&&!m5c&&!m7c&&!m8c?1:0)+(!m3d&&!m4d&&!m5d&&!m7d&&!m8d?1:0)+(!m3e&&!m4e&&!m5e&&!m7e&&!m8e?1:0)+(!m3f&&!m4f&&!m5f&&!m7f&&!m8f?1:0); const rO=mr['배수외']; if(rO&&rO.min!==undefined&&(cntO<rO.min||cntO>rO.max)) pass=false;}
            if(pass) counts.multipleFilter++;
        }

        // 이월수
        if (counts.carryoverFilter !== undefined) {
            let pass = true;
            if (F.carryoverCounts && F.carryoverLUT) {
                const lut=F.carryoverLUT;
                const cnt=(lut[a]||0)+(lut[b]||0)+(lut[c]||0)+(lut[d]||0)+(lut[e]||0)+(lut[f]||0);
                if (!F.carryoverCounts.has(cnt)) pass=false;
            }
            if (pass && F.carryoverBonusCounts && F.carryoverBonusLUT) {
                const lut=F.carryoverBonusLUT;
                const cnt=(lut[a]||0)+(lut[b]||0)+(lut[c]||0)+(lut[d]||0)+(lut[e]||0)+(lut[f]||0);
                if (!F.carryoverBonusCounts.has(cnt)) pass=false;
            }
            if (pass) counts.carryoverFilter++;
        }

        // 이웃수
        if (counts.neighborFilter !== undefined && F.neighborCounts && F.neighborLUT) {
            const lut=F.neighborLUT;
            const cnt=(lut[a]||0)+(lut[b]||0)+(lut[c]||0)+(lut[d]||0)+(lut[e]||0)+(lut[f]||0);
            if (F.neighborCounts.has(cnt)) counts.neighborFilter++;
        }

        // Hot/Cold
        for (const period of [5, 10, 15, 20]) {
            const key = `hotCold${period}`;
            if (counts[key] !== undefined) {
                const hc = F[`hc${period}`];
                if (hc) {
                    const lh=hc.hotLUT, lw=hc.warmLUT, lc=hc.coldLUT;
                    const hotCnt=lh?(lh[a]||0)+(lh[b]||0)+(lh[c]||0)+(lh[d]||0)+(lh[e]||0)+(lh[f]||0):0;
                    const warmCnt=lw?(lw[a]||0)+(lw[b]||0)+(lw[c]||0)+(lw[d]||0)+(lw[e]||0)+(lw[f]||0):0;
                    const coldCnt=lc?(lc[a]||0)+(lc[b]||0)+(lc[c]||0)+(lc[d]||0)+(lc[e]||0)+(lc[f]||0):0;
                    const hr=hc.hotRange, wr=hc.warmRange, cr=hc.coldRange;
                    if (hotCnt>=hr[0]&&hotCnt<=hr[1]&&warmCnt>=wr[0]&&warmCnt<=wr[1]&&coldCnt>=cr[0]&&coldCnt<=cr[1]) counts[key]++;
                }
            }
        }

        // 미출현 기간
        if (counts.missingPeriodFilter !== undefined && F.missingPeriodGroups) {
            const groups=F.missingPeriodGroups;
            let pass=true;
            for (let gi=0; gi<groups.length&&pass; gi++) {
                const g=groups[gi];
                if (!g.nums||g.nums.length===0) continue;
                const nums=g.nums;
                let cnt=0;
                for (let ni=0; ni<nums.length; ni++) { const n=nums[ni]; if(n===a||n===b||n===c||n===d||n===e||n===f) cnt++; }
                if ((g.min!==undefined&&cnt<g.min)||(g.max!==undefined&&cnt>g.max)) pass=false;
            }
            if (pass) counts.missingPeriodFilter++;
        }

        // 미출현 커스텀
        if (counts.missingCustomFilter !== undefined && F.missingCustomGroups) {
            const groups=F.missingCustomGroups;
            let pass=true;
            for (let gi=0; gi<groups.length&&pass; gi++) {
                const g=groups[gi];
                if (!g.lut) continue;
                const lut=g.lut;
                const cnt=(lut[a]||0)+(lut[b]||0)+(lut[c]||0)+(lut[d]||0)+(lut[e]||0)+(lut[f]||0);
                if (cnt<g.min||cnt>g.max) pass=false;
            }
            if (pass) counts.missingCustomFilter++;
        }

        // 회귀
        for (let ri=0; ri<regrParsed.length; ri++) {
            const r=regrParsed[ri];
            if (!r.lut) continue;
            const lut=r.lut;
            const cnt=(lut[a]||0)+(lut[b]||0)+(lut[c]||0)+(lut[d]||0)+(lut[e]||0)+(lut[f]||0);
            if (cnt>=r.min&&cnt<=r.max) counts[r.key]++;
        }

        // 커스텀 분석
        for (let ci=0; ci<customParsed.length; ci++) {
            const cp=customParsed[ci];
            if (!cp.lut) continue;
            const lut=cp.lut;
            const cnt=(lut[a]||0)+(lut[b]||0)+(lut[c]||0)+(lut[d]||0)+(lut[e]||0)+(lut[f]||0);
            if (cnt>=cp.min&&cnt<=cp.max) counts[cp.key]++;
        }

        // 수동 필터
        for (let mi=0; mi<manualParsed.length; mi++) {
            const mp=manualParsed[mi];
            if (!mp.lut) continue;
            const lut=mp.lut;
            const cnt=(lut[a]||0)+(lut[b]||0)+(lut[c]||0)+(lut[d]||0)+(lut[e]||0)+(lut[f]||0);
            if (cnt>=mp.min&&cnt<=mp.max) counts[mp.key]++;
        }
    }

    return counts;
}

// ──────────────────────────────────────────────────
// 6. 카운팅 / 생성
// ──────────────────────────────────────────────────
function countCombinations(rawFilters) {
    if (!combinations) return 0;
    const F = parseFilters(rawFilters);
    let validCount = 0;

    for (let i = 0; i < TOTAL_COMBINATIONS; i++) {
        const o = i * 6;
        if (checkFilters(
            combinations[o], combinations[o + 1], combinations[o + 2],
            combinations[o + 3], combinations[o + 4], combinations[o + 5], F
        )) validCount++;
    }
    return validCount;
}

function generateCombinations(rawFilters) {
    if (!combinations) return { combos: [], total: 0 };
    const F = parseFilters(rawFilters);
    const MAX_RETURN = 50000;
    let validCount = 0;
    const results = [];

    for (let i = 0; i < TOTAL_COMBINATIONS; i++) {
        const o = i * 6;
        const a = combinations[o], b = combinations[o + 1], c = combinations[o + 2];
        const d = combinations[o + 3], e = combinations[o + 4], f = combinations[o + 5];
        if (checkFilters(a, b, c, d, e, f, F)) {
            validCount++;
            if (results.length < MAX_RETURN) results.push([a, b, c, d, e, f]);
        }
    }
    return { combos: results, total: validCount };
}

// ──────────────────────────────────────────────────
// 6. 메시지 핸들러
// ──────────────────────────────────────────────────
self.onmessage = function (e) {
    const data = e.data;
    if (data.type === 'INIT') {
        initCombinations();
    } else if (data.type === 'COUNT') {
        const count = countCombinations(data.filters);
        self.postMessage({ type: 'COUNT_RESULT', count });
    } else if (data.type === 'GENERATE') {
        const result = generateCombinations(data.filters);
        self.postMessage({ type: 'GENERATE_RESULT', combos: result.combos, totalValid: result.total });
    } else if (data.type === 'DIAGNOSE') {
        const result = diagnoseFilters(data.filters);
        self.postMessage({ type: 'DIAGNOSE_RESULT', result });
    } else if (data.type === 'STEPCNT') {
        const result = stepCountFilters(data.filters);
        self.postMessage({ type: 'STEPCNT_RESULT', result });
    } else if (data.type === 'INDEP_COUNT') {
        const counts = countIndependent(data.filters);
        self.postMessage({ type: 'INDEP_COUNT_RESULT', counts });
    } else if (data.type === 'CUMUL_BADGES') {
        const result = stepCountFilters(data.filters);
        if (!result) { self.postMessage({ type: 'CUMUL_BADGES_RESULT', badges: {} }); return; }
        const badges = {};
        for (const step of result.steps) {
            if (step.key && step.key !== 'basket' && step.key !== 'entropy') {
                badges[step.key] = step.survivors;
            }
        }
        self.postMessage({ type: 'CUMUL_BADGES_RESULT', badges });
    }
};
