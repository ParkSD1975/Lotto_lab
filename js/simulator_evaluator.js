/**
 * simulator_evaluator.js
 *
 * 시뮬레이터 수식(simulator_custom)의 회차별 재실행 평가 함수.
 * filter.html, custom_analysis.html, dashboard.html 등 시뮬레이터 분석 표시/필터링이 필요한
 * 모든 페이지에서 공통 사용. window.evalSimulatorFormulaForDraw 전역 노출.
 *
 * 두 형식 지원:
 *   - v4 토큰 배열 (구버전): [{ type: 'main', round: 1, position: 1, ... }, op, ...]
 *   - v5-multi 객체 (현재): { workspaces: [...], combineOps: [...], pattern, version: 'v5-multi' }
 *
 * 반환: 보정 후 정수 번호 배열 (set, dedup, 1~maxBall 범위)
 */

(function () {
    'use strict';

    // ============================================================
    // [v5-multi] 다중 워크스페이스 + 분기 변환 + 결합 op
    //   customSimulator.js의 _evaluateWorkspace + _combineArrays + evaluateAt 로직 포팅
    // ============================================================
    function evalSimulatorV5Multi(steps, sorted, targetIdx, maxBall, options) {
        options = options || {};
        const target = sorted[targetIdx];
        if (!target) return [];

        // [fix-267] 회귀 참조(regref) 카드 — 다른 워크스페이스의 산출값 N을 회귀 offset으로 사용
        // 사이클 방지용 evaluating set + 메모이제이션 캐시
        const wsEvalCache = new Map();   // wsId → result array (한 회차 평가 내 1회만)
        const wsEvaluating = new Set();  // 현재 평가 중인 wsId (사이클 검출)

        // 단일 카드 산출값 추출
        const evalCard = (c) => {
            if (c.type === 'tail') {
                const out = [];
                for (let n = 1; n <= maxBall; n++) {
                    if (n % 10 === c.tailNum) out.push(n);
                }
                return out;
            }
            // [fix-290] 저장된 필터 카드 — 드롭 시점의 target_numbers 스냅샷 그대로 반환
            if (c.type === 'saved') {
                return [...(c.targetNumbers || [])];
            }
            // [fix-267] regref: 다른 워크스페이스의 산출값을 회귀 offset N으로 dereferencing
            // 예) W1 = [회차십(1223)+0] = 23 → regref(W1, 'line') → sorted[targetIdx+23] = 1200회 전라인
            if (c.type === 'regref') {
                const sourceWs = (steps.workspaces || []).find(w => w.id === c.sourceWsId);
                if (!sourceWs) return [];
                if (wsEvaluating.has(c.sourceWsId)) {
                    if (options.withLogs) console.warn('[regref] cycle detected:', c.sourceWsId);
                    return []; // 사이클 차단
                }
                wsEvaluating.add(c.sourceWsId);
                let sourceVals;
                if (wsEvalCache.has(c.sourceWsId)) {
                    sourceVals = wsEvalCache.get(c.sourceWsId);
                } else {
                    sourceVals = evalWs(sourceWs);
                    wsEvalCache.set(c.sourceWsId, sourceVals);
                }
                wsEvaluating.delete(c.sourceWsId);
                if (!sourceVals || sourceVals.length === 0) return [];

                // [fix-268] sourceVals 의 모든 N에 대해 dereferencing → union
                // 예) W1=[23,24,22,123] (분기 변환 결과) → 4개 회차의 라인을 모두 가져옴
                // [fix-351] N=0 가드: target 회차 자체를 가져오면 추첨 후 자기 추첨번호가 시뮬에 합쳐져
                //   "허위 적중" 발생. 회귀는 1회 이상만 유의미하므로 N<1은 차단.
                const collected = [];
                const seenOffsets = new Set();   // 중복 offset 가드
                for (const rawN of sourceVals) {
                    const N = parseInt(rawN);
                    if (!Number.isFinite(N) || N < 1) continue;   // [fix-351] N<1 차단
                    if (seenOffsets.has(N)) continue;
                    seenOffsets.add(N);
                    const refDraw = sorted[targetIdx + N];
                    if (!refDraw) continue;
                    if (c.refType === 'line') {
                        for (const n of (refDraw.numbers || [])) collected.push(n);
                    } else if (c.refType === 'bonus') {
                        if (refDraw.bonus != null) collected.push(refDraw.bonus);
                    } else if (c.refType === 'pos') {
                        const sortedNums = [...(refDraw.numbers || [])].sort((a, b) => a - b);
                        const v = sortedNums[(c.position || 1) - 1];
                        if (v != null) collected.push(v);
                    } else if (c.refType === 'round') {
                        let v = refDraw.drawNo || refDraw.round;
                        const dm = c.digitMode || 'thousands';
                        const mod = dm === 'ones' ? 10 : dm === 'tens' ? 100 : dm === 'hundreds' ? 1000 : null;
                        if (v != null && mod != null) v = v % mod;
                        if (v != null) collected.push(v);
                    } else if (c.refType === 'all_main_bonus') {
                        for (const n of (refDraw.numbers || [])) collected.push(n);
                        if (refDraw.bonus != null) collected.push(refDraw.bonus);
                    }
                }
                return collected;
            }
            const refDraw = sorted[targetIdx + (c.offset || 0)];
            const drawNoFallback = c.drawNo;
            const drawDateFallback = c.drawDate;
            // round/date 카드는 refDraw 없어도 fallback 사용
            if (!refDraw && c.type !== 'round' && c.type !== 'date') return [];
            if (c.type === 'line') return [...((refDraw && refDraw.numbers) || [])];
            if (c.type === 'pos') {
                const sortedNums = [...((refDraw && refDraw.numbers) || [])].sort((a, b) => a - b);
                const v = sortedNums[(c.position || 1) - 1];
                return v != null ? [v] : [];
            }
            if (c.type === 'bonus') return (refDraw && refDraw.bonus != null) ? [refDraw.bonus] : [];
            if (c.type === 'num') return c.num != null ? [c.num] : [];
            if (c.type === 'round') {
                let v = (refDraw && (refDraw.drawNo || refDraw.round)) ?? (target && (target.drawNo || target.round)) ?? drawNoFallback;
                // digitMode: ones(%10) / tens(%100) / hundreds(%1000) / thousands(전체)
                const dm = c.digitMode || 'thousands';
                const mod = dm === 'ones' ? 10 : dm === 'tens' ? 100 : dm === 'hundreds' ? 1000 : null;
                if (v != null && mod != null) v = v % mod;
                return v != null ? [v] : [];
            }
            if (c.type === 'date') {
                const dateStr = (refDraw && (refDraw.drawDate || refDraw.date)) ?? (target && (target.drawDate || target.date)) ?? drawDateFallback;
                if (!dateStr) return [];
                const dt = new Date(dateStr);
                if (isNaN(dt.getTime())) return [];
                const part = c.datePart || 'day';
                if (part === 'year') return [dt.getFullYear()];
                if (part === 'month') return [dt.getMonth() + 1];
                return [dt.getDate()];
            }
            return [];
        };

        // Stage 6-5-1: 워크스페이스 평가 (op 토큰 기반 inline 연산 지원)
        const evalWs = (ws) => {
            // 집합 연산 override가 적용된 경우 — 고정 번호 배열을 즉시 반환
            if (ws.setOpOverride && Array.isArray(ws.setOpOverride.numbers) && ws.setOpOverride.numbers.length > 0) {
                return [...ws.setOpOverride.numbers];
            }

            // cards 시퀀스 순회 — op 토큰 만나면 좌→우 누적 연산
            let acc = null;
            let pendingOp = null;
            for (const c of ws.cards || []) {
                if (c.type === 'op') {
                    pendingOp = c.value;
                    continue;
                }
                // chip 평가
                const chipResult = evalCard(c);
                if (acc === null) {
                    acc = chipResult;
                } else if (pendingOp) {
                    acc = applyOpBroadcast(acc, chipResult, pendingOp);
                    pendingOp = null;
                } else {
                    // op 없이 chip 연속 → 기존 동작 (union) 호환
                    acc.push(...chipResult);
                }
            }
            // 마지막 op 토큰이 남아있으면 무시 (chip 없이 끝남)

            let allValues = acc || [];

            // [fix-369] scalar 모드는 transforms 적용 *전*에 합산 후 chain 적용 (분기 union 아님)
            //   사용자 의도 패턴: 카드값 합산 → 단일값에 +20 → mod 46 같은 순차 산술
            //   기본 모드(union/auto)는 기존 분기 union 유지
            const applyTx = (v, tx) => {
                switch (tx.op) {
                    case '+': return v + tx.value;
                    case '-': return v - tx.value;
                    case '*': return v * tx.value;
                    case '/': return tx.value === 0 ? 0 : Math.floor(v / tx.value);
                    case '%': return tx.value === 0 ? 0 : (v % tx.value);
                }
                return v;
            };
            let working;
            if (ws.mode === 'scalar') {
                // 합산 후 chain transforms
                let scalar = allValues.length ? allValues.reduce((s, v) => s + v, 0) : 0;
                for (const tx of (ws.transforms || [])) scalar = applyTx(scalar, tx);
                working = [scalar];
            } else if (!ws.transforms || ws.transforms.length === 0) {
                working = [...allValues];
            } else {
                // 분기 union (union/auto/default)
                const branches = ws.transforms.map(tx => allValues.map(v => applyTx(v, tx)));
                working = branches.flat();
            }
            if (ws.mode === 'tail') {
                const tailSet = new Set(working.map(v => ((v % 10) + 10) % 10));
                const expanded = [];
                for (let n = 1; n <= maxBall; n++) {
                    if (tailSet.has(n % 10)) expanded.push(n);
                }
                working = expanded;
            }
            return working;
        };

        // Stage 6-5-1: 각 원소별 broadcast 연산 + mod 45 + 1 정규화
        const applyOpBroadcast = (a, b, op) => {
            const result = new Set();
            for (const x of a) {
                for (const y of b) {
                    let v;
                    switch (op) {
                        case '+': v = x + y; break;
                        case '-': v = x - y; break;
                        case '*': v = x * y; break;
                        case '/': v = (y !== 0) ? x % y : 0; break;  // 나머지
                        case '%': v = (y !== 0) ? x % y : 0; break;
                    }
                    // mod 45 + 1 정규화 (음수 안전)
                    v = ((v - 1) % 45 + 45) % 45 + 1;
                    if (v >= 1 && v <= 45) result.add(v);
                }
            }
            return [...result].sort((a, b) => a - b);
        };

        // [fix-267] 모든 워크스페이스 평가 (regref 의존성 위해 hidden 포함)
        const _allWsValues = (steps.workspaces || []).map(evalWs);
        // hiddenInOutput=true 인 워크스페이스는 최종 결합에서 제외 (regref 소스 전용)
        const _wsList = steps.workspaces || [];
        const visibleIdx = _wsList
            .map((w, i) => ({ w, i }))
            .filter(({ w }) => !w.hiddenInOutput)
            .map(({ i }) => i);
        const wsValues = visibleIdx.map(i => _allWsValues[i]);
        // 가시 워크스페이스에 맞춰 combineOps 재계산: ws[visibleIdx[k-1]]→ws[visibleIdx[k]] 사이의 op
        const _origCombineOps = steps.combineOps || [];
        const combineOpsAdjusted = [];
        for (let k = 1; k < visibleIdx.length; k++) {
            // 두 visible 사이에 있는 첫 op (visibleIdx[k]-1 위치) 사용
            combineOpsAdjusted.push(_origCombineOps[visibleIdx[k] - 1] || { op: 'union' });
        }
        if (wsValues.length === 0) return [];

        // combineOps 좌→우 누적 (broadcast 모드 + 집합 연산)
        // - union (∪): 합집합
        // - intersection (∩): 교집합 (양쪽 모두 포함)
        // - complement (∁): 미포함 = 1~maxBall 중 (W1∪W2)에 없는 모든 번호
        // - difference (\): 차집합 (왼쪽에만 — 오른쪽 미포함)
        // - symdiff (△): 대칭차 (한쪽에만)
        // - 산술 (+, -, *, /, %): broadcast / element-wise / cartesian
        const combine = (left, right, op) => {
            if (op === 'union' || !op) return [...left, ...right];
            if (op === 'intersection') {
                const rs = new Set(right);
                return left.filter(v => rs.has(v));
            }
            if (op === 'complement') {
                // 1~maxBall 중 (left ∪ right)에 없는 번호 = 미포함
                const all = new Set([...left, ...right]);
                const out = [];
                for (let n = 1; n <= maxBall; n++) {
                    if (!all.has(n)) out.push(n);
                }
                return out;
            }
            if (op === 'difference') {
                const rs = new Set(right);
                return left.filter(v => !rs.has(v));
            }
            if (op === 'symdiff') {
                const ls = new Set(left), rs = new Set(right);
                const out = [];
                for (const v of left) if (!rs.has(v)) out.push(v);
                for (const v of right) if (!ls.has(v)) out.push(v);
                return out;
            }
            const doOp = (x, y) => {
                switch (op) {
                    case '+': return x + y;
                    case '-': return x - y;
                    case '*': return x * y;
                    case '/': return y === 0 ? 0 : Math.floor(x / y);
                    case '%': return y === 0 ? 0 : (x % y);
                }
                return x;
            };
            const L = left.length, R = right.length;
            if (L === 0 || R === 0) return [];
            if (L === 1 && R === 1) return [doOp(left[0], right[0])];
            if (L === 1) return right.map(v => doOp(left[0], v));
            if (R === 1) return left.map(v => doOp(v, right[0]));
            if (L === R) return left.map((v, i) => doOp(v, right[i]));
            const out = [];
            for (const a of left) for (const b of right) out.push(doOp(a, b));
            return out;
        };
        let working = wsValues[0] || [];
        for (let i = 1; i < wsValues.length; i++) {
            const op = combineOpsAdjusted[i - 1]?.op || 'union';
            working = combine(working, wsValues[i], op);
        }

        // [fix-286] visible 워크스페이스가 1개뿐이고 hidden(regref 전용)이 있으며
        // 사용자가 ∁ 미포함을 선택했다면 단항으로 적용 → 1~maxBall 중 working에 없는 번호
        // (W1 hidden + W2 visible + ∁ 합쳐서 "regref 가져온 번호의 보집합" 시나리오)
        if (visibleIdx.length === 1) {
            const hasHiddenWs = (steps.workspaces || []).some(w => w.hiddenInOutput);
            if (hasHiddenWs) {
                const hasComplement = (_origCombineOps || []).some(o => o && o.op === 'complement');
                if (hasComplement) {
                    const present = new Set(working);
                    const complemented = [];
                    for (let n = 1; n <= maxBall; n++) if (!present.has(n)) complemented.push(n);
                    working = complemented;
                }
            }
        }

        // ── 결합 후 변환 (Post-combine transforms) ──────────────────
        // 모든 워크스페이스가 결합된 다음에 적용 (e.g. W1+W2=38 → %10=8)
        const postTx = steps.combinePostTransforms || [];
        for (const tx of postTx) {
            working = working.map(v => {
                switch (tx.op) {
                    case '+': return v + tx.value;
                    case '-': return v - tx.value;
                    case '*': return v * tx.value;
                    case '/': return tx.value === 0 ? 0 : Math.floor(v / tx.value);
                    case '%': return tx.value === 0 ? 0 : ((v % tx.value + tx.value) % tx.value);
                }
                return v;
            });
        }

        // ── 결합 후 끝수 expand ──────────────────────────────────────
        // combinePostExpand=true → 결합값의 끝자리 → 그 끝자리의 모든 번호
        // e.g. [38] → 8끝 → {8,18,28,38}
        if (steps.combinePostExpand) {
            const tailSet = new Set(working.map(v => ((v % 10) + 10) % 10));
            const expanded = [];
            for (let n = 1; n <= maxBall; n++) {
                if (tailSet.has(n % 10)) expanded.push(n);
            }
            working = expanded;
        }

        // 보정 (0→제거, 음수→역산, 초과→순환) + logs 옵션
        const normalized = [];
        const logs = [];
        for (const v of working) {
            if (v === 0) {
                if (options.withLogs) logs.push('0');
                continue;
            }
            if (v < 0) {
                const r = maxBall + (v % maxBall);
                if (r === 0) {
                    if (options.withLogs) logs.push(`${v}→0`);
                    continue;
                }
                if (options.withLogs) logs.push(`${v}→${r}`);
                normalized.push(r);
            } else if (v > maxBall) {
                const r = ((v - 1) % maxBall) + 1;
                if (options.withLogs) logs.push(`${v}→${r}`);
                normalized.push(r);
            } else {
                normalized.push(v);
            }
        }
        const result = [...new Set(normalized)].sort((a, b) => a - b);
        return options.withLogs ? { result, logs } : result;
    }

    // ============================================================
    // 메인 진입점 — v4 배열 + v5-multi 객체 둘 다 처리
    //
    // @param {object|array} steps - v5-multi 객체 또는 v4 토큰 배열
    // @param {array} draws - 회차 데이터
    // @param {number} targetRound - 산출 대상 회차 번호
    // @param {number} maxBall - 최대 번호 (기본 45)
    // @param {object} options - { withLogs: boolean } — logs 배열 반환 여부
    // @returns {array|object} - withLogs=false(기본): number[], withLogs=true: { result: number[], logs: string[] }
    // ============================================================
    function evalSimulatorFormulaForDraw(steps, draws, targetRound, maxBall, options) {
        if (maxBall === undefined) maxBall = 45;
        options = options || {};
        if (!steps) return [];
        if (!Array.isArray(draws) || draws.length === 0) return [];

        // round DESC 정렬 + targetIdx 검색
        const sorted = [...draws].sort((a, b) => (b.round || b.drawNo) - (a.round || a.drawNo));
        let targetIdx = sorted.findIndex(d => (d.round || d.drawNo) === targetRound);

        // simNow(미추첨 다음 회차) 처리: targetRound가 draws에 없을 때 가상 target 추가
        // sorted[-1] 위치에 가상 simNow를 두고 targetIdx=-1 사용 (offset 0 + draws[-1] = undefined → fallback)
        // 단, sorted에 없을 때만 (이미 있으면 그 인덱스 사용)
        if (targetIdx < 0) {
            const latest = sorted[0];
            if (latest && targetRound === ((latest.round || latest.drawNo || 0) + 1)) {
                // simNow 가상 처리: 가상 target 객체를 sorted 앞에 prepend → targetIdx=0
                const nextDate = (latest.date || latest.drawDate)
                    ? (() => { const d = new Date(latest.date || latest.drawDate); d.setDate(d.getDate() + 7); return d.toISOString(); })()
                    : null;
                sorted.unshift({
                    round: targetRound,
                    drawNo: targetRound,
                    date: nextDate,
                    drawDate: nextDate,
                    numbers: [],
                    bonus: null,
                    _pending: true
                });
                targetIdx = 0;
            } else {
                return [];
            }
        }

        // ─── v5-multi 형식 분기 (workspaces + combineOps + transforms 분기 union) ───
        if (!Array.isArray(steps) && steps.workspaces) {
            return evalSimulatorV5Multi(steps, sorted, targetIdx, maxBall, options);
        }
        if (!Array.isArray(steps) || steps.length === 0) return options.withLogs ? { result: [], logs: [] } : [];

        // ─── v4 토큰 배열 ───
        const evalToken = (tok) => {
            const single = (v) => ({ values: [v], isSet: false });
            const setOf = (vs) => ({ values: vs, isSet: true });
            if (tok.type === 'const') return single(tok.value);
            if (tok.type === 'main') {
                const d = sorted[targetIdx + tok.round];
                if (!d) return single(0);
                const nums = d.numbers || [];
                const v = nums[tok.position - 1] || 0;
                return single(tok.tail ? (v % 10) : v);
            }
            if (tok.type === 'all_main') {
                const d = sorted[targetIdx + tok.round];
                if (!d) return setOf([]);
                const vs = (d.numbers || []).map(v => tok.tail ? (v % 10) : v);
                return setOf(vs);
            }
            if (tok.type === 'all_main_bonus') {
                const d = sorted[targetIdx + tok.round];
                if (!d) return setOf([]);
                const list = [...(d.numbers || [])];
                if (d.bonus) list.push(d.bonus);
                return setOf(list.map(v => tok.tail ? (v % 10) : v));
            }
            if (tok.type === 'bonus') {
                const d = sorted[targetIdx + tok.round];
                if (!d || !d.bonus) return single(0);
                return single(tok.tail ? (d.bonus % 10) : d.bonus);
            }
            if (tok.type === 'draw') {
                const d = sorted[targetIdx];
                if (!d) return single(0);
                const no = d.round || d.drawNo || 0;
                if (tok.attr === 'raw') return single(no);
                if (tok.attr === 'digitSum') return single(String(no).split('').reduce((s, c) => s + (parseInt(c) || 0), 0));
                if (tok.attr === 'tail') return single(no % 10);
            }
            if (tok.type === 'date') {
                const d = sorted[targetIdx + tok.round];
                if (!d || !d.date) return single(0);
                const dt = new Date(d.date);
                let v = 0;
                if (tok.attr === 'year') v = dt.getFullYear();
                else if (tok.attr === 'month') v = dt.getMonth() + 1;
                else if (tok.attr === 'day') v = dt.getDate();
                else if (tok.attr === 'weekday') v = dt.getDay();
                return single(tok.tail ? (v % 10) : v);
            }
            return single(0);
        };
        const applyOp = (a, op, b) => {
            const doOp = (x, y) => {
                switch (op) {
                    case '+': return x + y;
                    case '-': return x - y;
                    case '*': return x * y;
                    case '/': return y === 0 ? 0 : Math.floor(x / y);
                    case '%': return y === 0 ? 0 : (x % y);
                }
                return x;
            };
            if (a.isSet && !b.isSet) return { values: a.values.map(v => doOp(v, b.values[0] || 0)), isSet: true };
            if (!a.isSet && b.isSet) return { values: b.values.map(v => doOp(a.values[0] || 0, v)), isSet: true };
            if (a.isSet && b.isSet) return { values: [...a.values, ...b.values], isSet: true };
            return { values: [doOp(a.values[0] || 0, b.values[0] || 0)], isSet: false };
        };

        if (steps[0].type === 'op') return [];
        let acc = evalToken(steps[0]);
        for (let i = 1; i < steps.length; i += 2) {
            const op = steps[i];
            const next = steps[i + 1];
            if (!op || op.type !== 'op' || !next) break;
            acc = applyOp(acc, op.value, evalToken(next));
        }

        const normalized = [];
        const logs = [];
        for (const v of acc.values) {
            if (v === 0) {
                if (options.withLogs) logs.push('0');
                continue;
            }
            if (v < 0) {
                const r = maxBall + (v % maxBall);
                if (r === 0) {
                    if (options.withLogs) logs.push(`${v}→0`);
                    continue;
                }
                if (options.withLogs) logs.push(`${v}→${r}`);
                normalized.push(r);
            } else if (v > maxBall) {
                const r = ((v - 1) % maxBall) + 1;
                if (options.withLogs) logs.push(`${v}→${r}`);
                normalized.push(r);
            } else {
                normalized.push(v);
            }
        }
        const result = [...new Set(normalized)].sort((a, b) => a - b);
        return options.withLogs ? { result, logs } : result;
    }

    // 전역 노출
    window.evalSimulatorFormulaForDraw = evalSimulatorFormulaForDraw;
    window.evalSimulatorV5Multi = evalSimulatorV5Multi;
})();
