global.window = global;
require('/c/Users/psdet/Documents/lottoanalysis/js/simulator_evaluator.js');

const fs = require('fs');
const draws = JSON.parse(fs.readFileSync('/c/Users/psdet/Documents/lottoanalysis/.tmp_draws.json', 'utf-8'));

const formula = {
  version: 'v5-multi',
  combineOps: [{op: 'union', leftWsId: 'ws-1', rightWsId: 'ws-2'}],
  workspaces: [
    {
      id: 'ws-1', mode: 'auto',
      cards: [
        {type: 'round', offset: 0, digitMode: 'ones'},
        {type: 'date', offset: 0, datePart: 'day', drawDate: '2026-05-16'}
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

const targetRound = 1224;
console.log('Target:', targetRound, '/ Latest:', draws[0].round, draws[0].date);

try {
  const result = window.evalSimulatorFormulaForDraw(formula, draws, targetRound, 45, {withLogs: true});
  console.log('\n=== W1 ∪ W2 (full) ===');
  console.log('Numbers:', Array.isArray(result) ? result : result.result);
  if (result.logs) console.log('Logs:', result.logs);
} catch (e) {
  console.error('FULL ERROR:', e.message);
}

console.log('\n=== W1 only ===');
const w1Only = {version: 'v5-multi', combineOps: [], workspaces: [formula.workspaces[0]]};
try {
  const w1res = window.evalSimulatorFormulaForDraw(w1Only, draws, targetRound, 45, {withLogs: true});
  console.log('W1 numbers:', Array.isArray(w1res) ? w1res : w1res.result);
  if (w1res.logs) console.log('W1 logs:', w1res.logs);
} catch (e) {
  console.error('W1 ERROR:', e.message);
}
