const fs = require('fs');
global.window = global;

// console.log를 일시 가로채서 simulator 내부 동작 추적
let simCode = fs.readFileSync('C:/Users/psdet/Documents/lottoanalysis/js/simulator_evaluator.js', 'utf-8');

// regref 처리 부분에 디버그 로그 주입
simCode = simCode.replace(
  "if (c.refType === 'all_main_bonus') {",
  "console.log('[regref·debug] refType=all_main_bonus N=', N, 'refDraw=', refDraw && (refDraw.round||refDraw.drawNo), 'numbers=', refDraw && refDraw.numbers, 'bonus=', refDraw && refDraw.bonus); if (c.refType === 'all_main_bonus') {"
);

// W1 결과 로그
simCode = simCode.replace(
  "wsEvalCache.set(c.sourceWsId, sourceVals);",
  "wsEvalCache.set(c.sourceWsId, sourceVals); console.log('[regref·debug] sourceVals from ws-', c.sourceWsId, '=', sourceVals);"
);

eval(simCode);

const draws = JSON.parse(fs.readFileSync('C:/Users/psdet/Documents/lottoanalysis/.tmp_draws.json', 'utf-8'));

const formula1223 = {
  version: 'v5-multi',
  combineOps: [{op: 'union', leftWsId: 'ws-1', rightWsId: 'ws-2'}],
  workspaces: [
    {
      id: 'ws-1', mode: 'auto',
      cards: [
        {type: 'round', offset: 0, digitMode: 'ones'},
        {type: 'date', offset: 0, datePart: 'day', drawDate: '2026-05-09'}
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

console.log('=== 1223 회차 평가 ===');
const r1223 = window.evalSimulatorFormulaForDraw(formula1223, draws, 1223, 45);
console.log('\n최종 결과:', r1223);

console.log('\n=== 비교: 1224 회차 (추첨 전) ===');
const formula1224 = JSON.parse(JSON.stringify(formula1223));
formula1224.workspaces[0].cards[1].drawDate = '2026-05-16';
const r1224 = window.evalSimulatorFormulaForDraw(formula1224, draws, 1224, 45);
console.log('\n최종 결과:', r1224);
