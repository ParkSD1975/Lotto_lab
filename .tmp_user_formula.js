const fs = require('fs');
global.window = global;
const simCode = fs.readFileSync('C:/Users/psdet/Documents/lottoanalysis/js/simulator_evaluator.js', 'utf-8');
eval(simCode);

const draws = JSON.parse(fs.readFileSync('C:/Users/psdet/Documents/lottoanalysis/.tmp_draws.json', 'utf-8'));

// 사용자 화면과 동일한 W1 단일 워크스페이스 (op 없는 union → scalar 자동 fallback?)
const formulaUnion = {
  version: 'v5-multi',
  combineOps: [],
  workspaces: [{
    id: 'ws-1', mode: 'auto',
    cards: [
      { type: 'round', offset: 0, drawNo: 1223 },                    // 1223
      { type: 'pos',  offset: 0, drawNo: 1223, position: 4 },         // 4라인=32
      { type: 'bonus', offset: 0, drawNo: 1223 }                      // 보너스=26
    ],
    transforms: [{ op: '+', value: 20 }, { op: '/', value: 46 }]
  }]
};

console.log('=== Test 1: union (auto, op 없음) + transforms +20 ÷46 ===');
const r1 = window.evalSimulatorFormulaForDraw(formulaUnion, draws, 1224, 45, { withLogs: true });
console.log('result:', r1.result, '| logs:', r1.logs);

// scalar 모드 강제
const formulaScalar = JSON.parse(JSON.stringify(formulaUnion));
formulaScalar.workspaces[0].mode = 'scalar';
console.log('\n=== Test 2: scalar (합산) + transforms +20 ÷46 ===');
const r2 = window.evalSimulatorFormulaForDraw(formulaScalar, draws, 1224, 45, { withLogs: true });
console.log('result:', r2.result, '| logs:', r2.logs);

// scalar + ÷46을 %46으로
const formulaScalarMod = JSON.parse(JSON.stringify(formulaScalar));
formulaScalarMod.workspaces[0].transforms = [{ op: '+', value: 20 }, { op: '%', value: 46 }];
console.log('\n=== Test 3: scalar + transforms +20 %46 ===');
const r3 = window.evalSimulatorFormulaForDraw(formulaScalarMod, draws, 1224, 45, { withLogs: true });
console.log('result:', r3.result, '| logs:', r3.logs);

// scalar + 변환 1개만 %46
const formulaScalarSingle = JSON.parse(JSON.stringify(formulaScalar));
formulaScalarSingle.workspaces[0].transforms = [{ op: '%', value: 46 }];
console.log('\n=== Test 4: scalar + 변환 1개 %46만 (1281%46) ===');
const r4 = window.evalSimulatorFormulaForDraw(formulaScalarSingle, draws, 1224, 45, { withLogs: true });
console.log('result:', r4.result, '| logs:', r4.logs);

// 카드 사이 + op 추가 (1223+32+26=1281을 op로 강제)
const formulaWithOp = {
  version: 'v5-multi', combineOps: [],
  workspaces: [{
    id: 'ws-1', mode: 'auto',
    cards: [
      { type: 'round', offset: 0, drawNo: 1223 },
      { type: 'op', value: '+' },
      { type: 'pos', offset: 0, drawNo: 1223, position: 4 },
      { type: 'op', value: '+' },
      { type: 'bonus', offset: 0, drawNo: 1223 }
    ],
    transforms: [{ op: '+', value: 20 }, { op: '%', value: 46 }]
  }]
};
console.log('\n=== Test 5: cards 사이 + op + transforms [+20, %46] ===');
const r5 = window.evalSimulatorFormulaForDraw(formulaWithOp, draws, 1224, 45, { withLogs: true });
console.log('result:', r5.result, '| logs:', r5.logs);
