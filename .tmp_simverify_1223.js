const fs = require('fs');
global.window = global;
const simCode = fs.readFileSync('C:/Users/psdet/Documents/lottoanalysis/js/simulator_evaluator.js', 'utf-8');
eval(simCode);

const draws = JSON.parse(fs.readFileSync('C:/Users/psdet/Documents/lottoanalysis/.tmp_draws.json', 'utf-8'));

// 1223 회차 시점 수식 — 동일 구조이지만 drawDate=2026-05-09로 변경 (1223 추첨일)
const formula1223 = {
  version: 'v5-multi',
  combineOps: [{op: 'union', leftWsId: 'ws-1', rightWsId: 'ws-2'}],
  workspaces: [
    {
      id: 'ws-1', mode: 'auto',
      cards: [
        {type: 'round', offset: 0, digitMode: 'ones'},                          // 1223 ones=3
        {type: 'date', offset: 0, datePart: 'day', drawDate: '2026-05-09'}      // 9
      ],
      transforms: [{op: '/', value: 8}]
    },
    {
      id: 'ws-2', mode: 'auto',
      cards: [{type: 'regref', refType: 'all_main_bonus', sourceWsId: 'ws-1'}],
      transforms: []
    }
  ]
};

console.log('=== 1223 회차 (이미 추첨됨, 추첨번호 [16,18,20,32,33,39] 보너스 26) ===');
const r1223 = window.evalSimulatorFormulaForDraw(formula1223, draws, 1223, 45, {withLogs: true});
console.log('1223 시뮬 결과:', Array.isArray(r1223) ? r1223 : r1223.result);

const w1Only = {version: 'v5-multi', combineOps: [], workspaces: [formula1223.workspaces[0]]};
const w1res = window.evalSimulatorFormulaForDraw(w1Only, draws, 1223, 45, {withLogs: true});
console.log('  W1만:', w1res.result, 'logs:', w1res.logs);

console.log('\n--- 사용자 화면에 표시된 13개 번호 ---');
const userScreen = [4, 11, 16, 17, 18, 20, 22, 26, 32, 33, 34, 39, 41];
const actual = [16, 18, 20, 32, 33, 39];
const bonus = 26;
console.log('화면:', userScreen);
console.log('1223 실제 추첨:', actual, 'bonus:', bonus);
const simResult = Array.isArray(r1223) ? r1223 : r1223.result;
console.log('\n시뮬 결과 vs 화면:');
console.log('  시뮬에만 있음:', simResult.filter(n => !userScreen.includes(n)));
console.log('  화면에만 있음:', userScreen.filter(n => !simResult.includes(n)));
console.log('  공통:', simResult.filter(n => userScreen.includes(n)));

console.log('\n--- 시뮬 결과 vs 실제 추첨번호 ---');
console.log('  시뮬 적중수(main):', simResult.filter(n => actual.includes(n)).length);
console.log('  시뮬에 보너스 포함:', simResult.includes(bonus));
