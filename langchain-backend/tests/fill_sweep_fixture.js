/**
 * Sweep Fixture Filler — Node 자동화
 *
 * `js/simulator_evaluator.js` (브라우저 IIFE)를 Node에서 실행하여
 * `tests/fixtures/sweep_js_baseline.json`의 placeholder를 실제 JS 결과로 채움.
 *
 * 사용:
 *   node langchain-backend/tests/fill_sweep_fixture.js
 *   → 콘솔에 결과 출력 + fixture 자동 업데이트
 *
 * 근거: JS와 Python 엔진 교차 검증의 source of truth.
 *       fill_fixture_from_js.html을 Node 자동화로 옮김.
 */
'use strict';

const fs = require('fs');
const path = require('path');

// IIFE의 window 전역 객체 흉내 — simulator_evaluator.js가 window.evalSimulatorFormulaForDraw 노출
global.window = global;

// simulator_evaluator.js 로드 (IIFE 즉시 실행 → window.evalSimulatorFormulaForDraw 등록)
const SIMULATOR_EVAL_PATH = path.join(__dirname, '..', '..', 'js', 'simulator_evaluator.js');
require(SIMULATOR_EVAL_PATH);

const evalFn = global.evalSimulatorFormulaForDraw || global.window.evalSimulatorFormulaForDraw;
if (typeof evalFn !== 'function') {
    console.error('FATAL: window.evalSimulatorFormulaForDraw not found. Check simulator_evaluator.js IIFE export.');
    process.exit(1);
}

// fill_fixture_from_js.html과 동일한 SAMPLE_DRAWS
const SAMPLE_DRAWS = [
    {round: 1224, drawNo: 1224, date: "2025-01-04", drawDate: "2025-01-04",
     numbers: [1, 2, 3, 4, 5, 6], bonus: 7},
    {round: 1223, drawNo: 1223, date: "2024-12-28", drawDate: "2024-12-28",
     numbers: [8, 15, 22, 29, 36, 43], bonus: 10},
    {round: 1222, drawNo: 1222, date: "2024-12-21", drawDate: "2024-12-21",
     numbers: [5, 12, 19, 26, 33, 40], bonus: 45},
    {round: 1221, drawNo: 1221, date: "2024-12-14", drawDate: "2024-12-14",
     numbers: [7, 14, 21, 28, 35, 42], bonus: 3},
    {round: 1220, drawNo: 1220, date: "2024-12-07", drawDate: "2024-12-07",
     numbers: [2, 9, 16, 23, 30, 37], bonus: 44},
];

// fixture 로드
const FIXTURE_PATH = path.join(__dirname, 'fixtures', 'sweep_js_baseline.json');
const fixture = JSON.parse(fs.readFileSync(FIXTURE_PATH, 'utf8'));

console.log('[Fixture Filler] Running JS evaluator for placeholder cases...\n');

const updates = [];
for (const tc of fixture.test_cases) {
    const expected = tc.expected_result;
    const needsFill = (typeof expected === 'string') &&
                       (expected === 'PLACEHOLDER_TO_BE_FILLED_BY_JS' ||
                        expected === 'DEPENDS_ON_1223_NUMBERS');
    if (!needsFill) continue;

    try {
        const result = evalFn(tc.formula, SAMPLE_DRAWS, tc.round, 45);
        const arr = Array.isArray(result) ? result : [];
        console.log(`[${tc.name}]`);
        console.log(`  round=${tc.round} var_value=${tc.var_value}`);
        console.log(`  result: ${JSON.stringify(arr)}`);
        console.log('');

        tc.expected_result = arr;
        updates.push(tc.name);
    } catch (e) {
        console.error(`[${tc.name}] ERROR:`, e.message);
    }
}

// fixture 저장 (변경 있을 때만)
if (updates.length > 0) {
    fs.writeFileSync(FIXTURE_PATH, JSON.stringify(fixture, null, 2) + '\n', 'utf8');
    console.log(`[Fixture Filler] Updated ${updates.length} case(s): ${updates.join(', ')}`);
    console.log(`[Fixture Filler] Saved: ${FIXTURE_PATH}`);
} else {
    console.log('[Fixture Filler] No placeholders found. Nothing to update.');
}
