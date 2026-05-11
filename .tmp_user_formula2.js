const fs = require('fs');
global.window = global;
const simCode = fs.readFileSync('C:/Users/psdet/Documents/lottoanalysis/js/simulator_evaluator.js', 'utf-8');
eval(simCode);
const draws = JSON.parse(fs.readFileSync('C:/Users/psdet/Documents/lottoanalysis/.tmp_draws.json', 'utf-8'));

// offset=1 (현재-1 = 1223회)
const baseW1 = (transforms) => ({
  version: 'v5-multi', combineOps: [],
  workspaces: [{
    id: 'ws-1', mode: 'auto',
    cards: [
      { type: 'round', offset: 1, drawNo: 1223 },
      { type: 'pos',  offset: 1, drawNo: 1223, position: 4 },
      { type: 'bonus', offset: 1, drawNo: 1223 }
    ],
    transforms
  }]
});

console.log('=== A. transforms [+20, ÷46] (사용자 화면 그대로) ===');
const rA = window.evalSimulatorFormulaForDraw(baseW1([{ op: '+', value: 20 }, { op: '/', value: 46 }]), draws, 1224, 45, { withLogs: true });
console.log('result:', rA.result, '| logs:', rA.logs);

console.log('\n=== B. scalar 모드 + [+20, ÷46] ===');
const fB = baseW1([{ op: '+', value: 20 }, { op: '/', value: 46 }]);
fB.workspaces[0].mode = 'scalar';
const rB = window.evalSimulatorFormulaForDraw(fB, draws, 1224, 45, { withLogs: true });
console.log('result:', rB.result, '| logs:', rB.logs);

console.log('\n=== C. scalar + [+20, %46] (사용자 의도 = 13) ===');
const fC = baseW1([{ op: '+', value: 20 }, { op: '%', value: 46 }]);
fC.workspaces[0].mode = 'scalar';
const rC = window.evalSimulatorFormulaForDraw(fC, draws, 1224, 45, { withLogs: true });
console.log('result:', rC.result, '| logs:', rC.logs);

console.log('\n=== D. union + [+20, %46] ===');
const rD = window.evalSimulatorFormulaForDraw(baseW1([{ op: '+', value: 20 }, { op: '%', value: 46 }]), draws, 1224, 45, { withLogs: true });
console.log('result:', rD.result, '| logs:', rD.logs);

console.log('\n=== E. union + [%46] 단일 (1281을 분기 union 후 mod) ===');
const rE = window.evalSimulatorFormulaForDraw(baseW1([{ op: '%', value: 46 }]), draws, 1224, 45, { withLogs: true });
console.log('result:', rE.result, '| logs:', rE.logs);
