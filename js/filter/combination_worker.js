/**
 * js/filter/combination_worker.js
 * 814만 로또 조합 100% 전수조사 카운팅 및 전체 추출 워커 (샘플링 없음)
 */

let combinations = null;
const TOTAL_COMBINATIONS = 8145060;

function initCombinations() {
    if (combinations) return;
    combinations = new Uint8Array(TOTAL_COMBINATIONS * 6);
    let idx = 0;
    for (let a = 1; a <= 40; a++) {
        for (let b = a + 1; b <= 41; b++) {
            for (let c = b + 1; c <= 42; c++) {
                for (let d = c + 1; d <= 43; d++) {
                    for (let e = d + 1; e <= 44; e++) {
                        for (let f = e + 1; f <= 45; f++) {
                            combinations[idx++] = a;
                            combinations[idx++] = b;
                            combinations[idx++] = c;
                            combinations[idx++] = d;
                            combinations[idx++] = e;
                            combinations[idx++] = f;
                        }
                    }
                }
            }
        }
    }
    self.postMessage({ type: 'INIT_DONE', total: TOTAL_COMBINATIONS });
}

function checkFilters(temp, filters) {
    if (filters.fixed && filters.fixed.length > 0) {
        for (let i = 0; i < filters.fixed.length; i++) {
            let found = false;
            for (let j = 0; j < 6; j++) if (temp[j] === filters.fixed[i]) { found = true; break; }
            if (!found) return false;
        }
    }
    if (filters.excluded && filters.excluded.length > 0) {
        for (let i = 0; i < filters.excluded.length; i++) {
            for (let j = 0; j < 6; j++) if (temp[j] === filters.excluded[i]) return false;
        }
    }
    if (filters.sumRange) {
        const sum = temp[0] + temp[1] + temp[2] + temp[3] + temp[4] + temp[5];
        if (sum < filters.sumRange.min || sum > filters.sumRange.max) return false;
    }
    if (filters.oddEven && filters.oddEven.length > 0) {
        let oddCount = 0;
        for (let j = 0; j < 6; j++) if (temp[j] % 2 !== 0) oddCount++;
        const ratioStr = `${oddCount}:${6 - oddCount}`;
        if (!filters.oddEven.includes(ratioStr)) return false;
    }
    if (filters.lowHigh && filters.lowHigh.length > 0) {
        let lowCount = 0;
        for (let j = 0; j < 6; j++) if (temp[j] <= 22) lowCount++;
        const ratioStr = `${lowCount}:${6 - lowCount}`;
        if (!filters.lowHigh.includes(ratioStr)) return false;
    }
    return true;
}

// 1. 100% 전수조사 카운팅
function countCombinations(filters) {
    if (!combinations) return 0;
    let validCount = 0;
    let temp = new Array(6);

    for (let i = 0; i < TOTAL_COMBINATIONS; i++) {
        const offset = i * 6;
        temp[0] = combinations[offset];     temp[1] = combinations[offset + 1];
        temp[2] = combinations[offset + 2]; temp[3] = combinations[offset + 3];
        temp[4] = combinations[offset + 4]; temp[5] = combinations[offset + 5];

        if (checkFilters(temp, filters)) validCount++;
    }
    return validCount;
}

// 2. 살아남은 조합 100% 전체 추출 (샘플링 절대 안함)
function generateCombinations(filters) {
    if (!combinations) return { combos: [], total: 0 };

    let validCount = 0;
    let results = [];
    let temp = new Array(6);

    // 브라우저 메모리 터짐 방지용 안전장치 (최대 5만 개까지만 배열에 담음)
    const MAX_RETURN_LIMIT = 50000;

    for (let i = 0; i < TOTAL_COMBINATIONS; i++) {
        const offset = i * 6;
        temp[0] = combinations[offset];     temp[1] = combinations[offset + 1];
        temp[2] = combinations[offset + 2]; temp[3] = combinations[offset + 3];
        temp[4] = combinations[offset + 4]; temp[5] = combinations[offset + 5];

        if (checkFilters(temp, filters)) {
            validCount++;
            // 무작위 확률(샘플링) 없이 통과된 순서대로 정직하게 다 담습니다.
            if (results.length < MAX_RETURN_LIMIT) {
                results.push([...temp]);
            }
        }
    }
    return { combos: results, total: validCount };
}

self.onmessage = function(e) {
    const data = e.data;
    if (data.type === 'INIT') {
        initCombinations();
    } else if (data.type === 'COUNT') {
        self.postMessage({ type: 'COUNT_RESULT', count: countCombinations(data.filters) });
    } else if (data.type === 'GENERATE') {
        const result = generateCombinations(data.filters);
        self.postMessage({ type: 'GENERATE_RESULT', combos: result.combos, totalValid: result.total });
    }
};
