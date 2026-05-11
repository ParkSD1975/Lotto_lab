/**
 * customSimulator.js의 evaluateAt이 simulator_evaluator.js로 정확히 위임하는지 검증
 * (브라우저 환경 시뮬레이션 — customSimulator.js 전역 상태 사용)
 */

const fs = require('fs');
const path = require('path');

// window mock
global.window = global;
global.document = {
    getElementById: () => null,
    createElement: () => ({ style: {}, addEventListener: () => {}, appendChild: () => {} }),
    addEventListener: () => {},
};
global.Chart = class Chart {};

// simulator_evaluator.js 로드
const evalCode = fs.readFileSync(path.join(__dirname, 'js', 'simulator_evaluator.js'), 'utf8');
eval(evalCode);

// customSimulator.js 부분 로드 (evaluateAt, _evaluateWorkspace, _combineArrays만 필요)
// 전체 로드는 DOM 의존성 때문에 불가능하므로 핵심 함수만 추출
// 실제로는 evaluateAt이 simulator_evaluator.js를 호출하므로 그 동작만 검증

// CustomSim mock 객체 생성
const CustomSim = {
    draws: [
        { drawNo: 1222, drawDate: '2026-05-02', numbers: [1,5,9,14,22,40], bonus: 35, maxBall: 45 },
        { drawNo: 1221, drawDate: '2026-04-25', numbers: [6,13,18,28,30,36], bonus: 42, maxBall: 45 },
        { drawNo: 1220, drawDate: '2026-04-18', numbers: [2,7,11,15,24,33], bonus: 19, maxBall: 45 },
    ],
    workspaces: [
        {
            cards: [
                { type: 'round', offset: 1 },
                { type: 'date', offset: 1, datePart: 'year' },
                { type: 'date', offset: 1, datePart: 'month' },
                { type: 'date', offset: 1, datePart: 'day' },
            ],
            transforms: [],
            mode: 'array',
        },
        {
            cards: [
                { type: 'pos', offset: 1, position: 1 },
            ],
            transforms: [],
            mode: 'array',
        },
    ],
    combineOps: [{ op: '+' }],
    pattern: 'none',
    currentDB: 'korea',

    // evaluateAt 구현 (customSimulator.js의 위임 버전)
    evaluateAt: function(targetIdx) {
        if (!this.draws?.length || this.workspaces.length === 0) {
            return { rawValues: [], normalizedSet: [], logs: [], valid: false };
        }
        if (typeof window.evalSimulatorFormulaForDraw !== 'function') {
            console.error('[customSimulator] simulator_evaluator.js not loaded — cannot evaluate');
            return { rawValues: [], normalizedSet: [], logs: [], valid: false };
        }

        const draws = this.draws;
        let targetRound;
        if (targetIdx === -1 && this.currentDB === 'korea') {
            const latest = draws[0];
            targetRound = ((latest?.drawNo || latest?.round) || 0) + 1;
        } else {
            const target = draws[targetIdx];
            if (!target) return { rawValues: [], normalizedSet: [], logs: [], valid: false };
            targetRound = target.drawNo || target.round;
        }
        if (!targetRound) return { rawValues: [], normalizedSet: [], logs: [], valid: false };

        const formulaSteps = {
            workspaces: this.workspaces,
            combineOps: this.combineOps,
            pattern: this.pattern || 'none',
            version: 'v5-multi',
        };
        const maxBall = draws[0]?.maxBall || 45;

        const evalResult = window.evalSimulatorFormulaForDraw(
            formulaSteps,
            draws,
            targetRound,
            maxBall,
            { withLogs: true }
        );

        if (Array.isArray(evalResult)) {
            return { rawValues: evalResult, normalizedSet: evalResult, logs: [], valid: true };
        } else {
            return {
                rawValues: evalResult.result || [],
                normalizedSet: evalResult.result || [],
                logs: evalResult.logs || [],
                valid: true,
            };
        }
    }
};

// 검증 케이스 1: targetIdx=0 (1222회)
console.log('=== customSimulator.js evaluateAt(0) — 1222회 산출 ===');
const result1 = CustomSim.evaluateAt(0);
console.log('결과:', result1);
console.log('예상:', { rawValues: [7, 10, 12, 31], normalizedSet: [7, 10, 12, 31], logs: ['1227→12', '2032→7'], valid: true });
console.log('일치:', JSON.stringify(result1.normalizedSet) === JSON.stringify([7, 10, 12, 31]) ? '✅' : '❌');

// 검증 케이스 2: targetIdx=1 (1221회)
console.log('\n=== customSimulator.js evaluateAt(1) — 1221회 산출 ===');
const result2 = CustomSim.evaluateAt(1);
console.log('결과:', result2);
console.log('예상:', { rawValues: [3, 6, 7, 20], normalizedSet: [3, 6, 7, 20], logs: ['1222→7', '2028→3'], valid: true });
console.log('일치:', JSON.stringify(result2.normalizedSet) === JSON.stringify([3, 6, 7, 20]) ? '✅' : '❌');

// 검증 케이스 3: targetIdx=-1 (simNow — 1223회)
console.log('\n=== customSimulator.js evaluateAt(-1) — simNow 1223회 산출 ===');
const result3 = CustomSim.evaluateAt(-1);
console.log('결과:', result3);
// 1223회 simNow → offset=1 → 1222회 참조
// W1 = [1222, 2026, 5, 2], W2 = [1] (1222회 1라인 = 1)
// [1223, 2027, 6, 3]
// 1223→8, 2027→2, 6→6, 3→3 → [2, 3, 6, 8]
console.log('예상:', { normalizedSet: [2, 3, 6, 8], valid: true });
console.log('일치:', JSON.stringify(result3.normalizedSet) === JSON.stringify([2, 3, 6, 8]) ? '✅' : '❌');
