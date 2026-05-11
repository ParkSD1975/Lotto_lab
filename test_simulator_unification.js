/**
 * 시뮬레이터 수식 평가 통일 검증 스크립트
 * 사용자 제보 분석 "전회차(회차연월일+1라인)" 수식 평가 일관성 검증
 *
 * 수식 구조:
 *   W1: [회차값, 년, 월, 일] (offset=1 → 전회차)
 *   W2: [1라인] (offset=1 → 전회차 본번호 중 1번째)
 *   결합: W1 + W2 (broadcast 모드 — element-wise 4×1 → 4개 결과)
 *   보정: 0 제거, 음수 역산, 초과 순환 ((v-1)%45)+1
 *
 * 검증 케이스:
 * 1. 1222회 산출 (offset=1 → 1221회 참조)
 *    - 1221회 = 2026-04-25, 본번호 [6,13,18,28,30,36]
 *    - W1 = [1221, 2026, 4, 25]
 *    - W2 = [6] (1라인 = 6)
 *    - W1 + W2 = [1227, 2032, 10, 31] (element-wise)
 *    - 보정:
 *      1227 → ((1227-1)%45)+1 = (1226%45)+1 = 11+1 = 12
 *      2032 → ((2032-1)%45)+1 = (2031%45)+1 = 6+1 = 7
 *      10 → 10
 *      31 → 31
 *    - 결과 = [7, 10, 12, 31] (정렬)
 *
 * 2. 1221회 산출 (offset=1 → 1220회 참조)
 *    - 1220회 = 2026-04-18, 본번호 [2,7,11,15,24,33]
 *    - W1 = [1220, 2026, 4, 18]
 *    - W2 = [2] (1라인 = 2)
 *    - W1 + W2 = [1222, 2028, 6, 20]
 *    - 보정:
 *      1222 → ((1222-1)%45)+1 = (1221%45)+1 = 6+1 = 7
 *      2028 → ((2028-1)%45)+1 = (2027%45)+1 = 2+1 = 3
 *      6 → 6
 *      20 → 20
 *    - 결과 = [3, 6, 7, 20] (정렬)
 */

// simulator_evaluator.js 로드 (Node.js 환경용 window mock)
const fs = require('fs');
const path = require('path');
global.window = global;
const evalCode = fs.readFileSync(path.join(__dirname, 'js', 'simulator_evaluator.js'), 'utf8');
eval(evalCode);

// 테스트 draws 데이터 (DESC 정렬 — 최신 회차부터)
const testDraws = [
    { drawNo: 1222, drawDate: '2026-05-02', numbers: [1,5,9,14,22,40], bonus: 35 },
    { drawNo: 1221, drawDate: '2026-04-25', numbers: [6,13,18,28,30,36], bonus: 42 },
    { drawNo: 1220, drawDate: '2026-04-18', numbers: [2,7,11,15,24,33], bonus: 19 },
    { drawNo: 1219, drawDate: '2026-04-11', numbers: [3,8,12,16,25,34], bonus: 20 },
];

// 수식 정의 (v5-multi 형식)
const formulaSteps = {
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
    version: 'v5-multi',
};

// 검증 케이스 1: 1222회 산출
console.log('=== 검증 케이스 1: 1222회 산출 ===');
const result1222 = window.evalSimulatorFormulaForDraw(formulaSteps, testDraws, 1222, 45, { withLogs: true });
console.log('결과:', result1222);
console.log('예상:', { result: [7, 10, 12, 31], logs: ['1227→12', '2032→7'] });
console.log('일치:', JSON.stringify(result1222.result) === JSON.stringify([7, 10, 12, 31]) ? '✅' : '❌');

// 검증 케이스 2: 1221회 산출
console.log('\n=== 검증 케이스 2: 1221회 산출 ===');
const result1221 = window.evalSimulatorFormulaForDraw(formulaSteps, testDraws, 1221, 45, { withLogs: true });
console.log('결과:', result1221);
console.log('예상:', { result: [3, 6, 7, 20], logs: ['1222→7', '2028→3'] });
console.log('일치:', JSON.stringify(result1221.result) === JSON.stringify([3, 6, 7, 20]) ? '✅' : '❌');

// withLogs 없이 호출 (레거시 호환성 검증)
console.log('\n=== 레거시 호환성: withLogs 없이 호출 ===');
const legacy1222 = window.evalSimulatorFormulaForDraw(formulaSteps, testDraws, 1222, 45);
console.log('결과:', legacy1222);
console.log('예상:', [7, 10, 12, 31]);
console.log('일치:', JSON.stringify(legacy1222) === JSON.stringify([7, 10, 12, 31]) ? '✅' : '❌');
