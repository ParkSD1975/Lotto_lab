// ════════════════════════════════════════════════════════════════════
// [fix-363] 분석 매트릭스 — 다중 분석 비교 + 집합 연산 + 메트릭 통계
// ════════════════════════════════════════════════════════════════════

(function () {
    'use strict';

    // ── 상태 ─────────────────────────────────────────────────────
    const state = {
        draws: [],           // 회차 DESC
        targetRound: 0,
        catalog: [],         // 분석 카탈로그 [ {id, label, type, group, getTargets} ]
        rows: [],            // 선택된 분석 [ {id, label, type, targets, metrics} ]
        ops: { union: true, intersection: true, difference: true, symdiff: true, complement: true },
        modalTab: 'all',
        modalSearch: ''
    };

    // ── 유틸 ─────────────────────────────────────────────────────
    const $ = (id) => document.getElementById(id);
    const ballBg = (n) => {
        if (n <= 10) return 'linear-gradient(135deg,#FBBF24,#F59E0B)';
        if (n <= 20) return 'linear-gradient(135deg,#60A5FA,#2563EB)';
        if (n <= 30) return 'linear-gradient(135deg,#F87171,#DC2626)';
        if (n <= 40) return 'linear-gradient(135deg,#9CA3AF,#4B5563)';
        return 'linear-gradient(135deg,#34D399,#059669)';
    };
    const isPrime = (n) => {
        if (n < 2) return false;
        for (let i = 2; i * i <= n; i++) if (n % i === 0) return false;
        return true;
    };
    const range = (start, end) => Array.from({ length: end - start + 1 }, (_, i) => start + i);

    // ── 정적 분석 카탈로그 ───────────────────────────────────────
    const STATIC_CATALOG = [
        { id: 'prime', label: '소수', group: 'static', getTargets: () => range(1, 45).filter(isPrime) },
        { id: 'composite', label: '합성수', group: 'static', getTargets: () => range(2, 45).filter(n => !isPrime(n)) },
        { id: 'twin', label: '쌍둥이수 (11·22·33·44)', group: 'static', getTargets: () => [11, 22, 33, 44] },
        { id: 'square', label: '제곱수', group: 'static', getTargets: () => [1, 4, 9, 16, 25, 36] },
        { id: 'triangular', label: '삼각수', group: 'static', getTargets: () => [1, 3, 6, 10, 15, 21, 28, 36, 45] },
        { id: 'fibonacci', label: '피보나치수', group: 'static', getTargets: () => [1, 2, 3, 5, 8, 13, 21, 34] },
        { id: 'lucas', label: '루카스수', group: 'static', getTargets: () => [1, 3, 4, 7, 11, 18, 29] },
        { id: 'catalan', label: '카탈란수', group: 'static', getTargets: () => [1, 2, 5, 14, 42] },
        { id: 'harshad', label: '하샤드수', group: 'static', getTargets: () => [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 18, 20, 21, 24, 27, 30, 36, 40, 42, 45] },
        { id: 'mul3', label: '3의 배수', group: 'static', getTargets: () => range(3, 45).filter(n => n % 3 === 0) },
        { id: 'mul4', label: '4의 배수', group: 'static', getTargets: () => range(4, 45).filter(n => n % 4 === 0) },
        { id: 'mul5', label: '5의 배수', group: 'static', getTargets: () => range(5, 45).filter(n => n % 5 === 0) },
        { id: 'mul7', label: '7의 배수', group: 'static', getTargets: () => range(7, 45).filter(n => n % 7 === 0) },
        { id: 'mul8', label: '8의 배수', group: 'static', getTargets: () => range(8, 45).filter(n => n % 8 === 0) },
        { id: 'odd', label: '홀수', group: 'static', getTargets: () => range(1, 45).filter(n => n % 2 === 1) },
        { id: 'even', label: '짝수', group: 'static', getTargets: () => range(2, 45).filter(n => n % 2 === 0) },
        { id: 'low', label: '저번호 (1~22)', group: 'static', getTargets: () => range(1, 22) },
        { id: 'high', label: '고번호 (23~45)', group: 'static', getTargets: () => range(23, 45) },
        // 끝수 0~9
        ...range(0, 9).map(d => ({
            id: `tail${d}`, label: `끝수 ${d}`, group: 'static',
            getTargets: () => range(1, 45).filter(n => n % 10 === d)
        })),
        // 번호대
        { id: 'decade1', label: '1번대 (1~9)', group: 'static', getTargets: () => range(1, 9) },
        { id: 'decade10', label: '10번대 (10~19)', group: 'static', getTargets: () => range(10, 19) },
        { id: 'decade20', label: '20번대 (20~29)', group: 'static', getTargets: () => range(20, 29) },
        { id: 'decade30', label: '30번대 (30~39)', group: 'static', getTargets: () => range(30, 39) },
        { id: 'decade40', label: '40번대 (40~45)', group: 'static', getTargets: () => range(40, 45) }
    ];

    // ── 동적 분석 카탈로그 ───────────────────────────────────────
    // [fix-373] getTargets(drawIdx=-1)
    //   drawIdx=-1: "다음 회차"(미추첨) 시점 = 직전 = state.draws[0]
    //   drawIdx=N:  state.draws[N] 회차 시점 = 직전 = state.draws[N+1]
    //   매트릭스 표에서 각 회차 평가 시 회차별 fresh 재계산
    const _draws = () => state.draws || [];
    const _baseIdx = (drawIdx) => (drawIdx == null || drawIdx < 0) ? 0 : drawIdx + 1;
    // _baseIdx = 그 회차의 "직전 회차" 인덱스
    const DYNAMIC_CATALOG = [
        {
            id: 'hot10', label: '핫넘버 (최근 10회)', group: 'dynamic',
            getTargets: (drawIdx) => topNNumbers(_draws().slice(_baseIdx(drawIdx), _baseIdx(drawIdx) + 10), 10)
        },
        {
            id: 'cold10', label: '콜드넘버 (최근 10회)', group: 'dynamic',
            getTargets: (drawIdx) => bottomNNumbers(_draws().slice(_baseIdx(drawIdx), _baseIdx(drawIdx) + 10), 10)
        },
        {
            id: 'hot20', label: '핫넘버 (최근 20회)', group: 'dynamic',
            getTargets: (drawIdx) => topNNumbers(_draws().slice(_baseIdx(drawIdx), _baseIdx(drawIdx) + 20), 12)
        },
        {
            id: 'cold20', label: '콜드넘버 (최근 20회)', group: 'dynamic',
            getTargets: (drawIdx) => bottomNNumbers(_draws().slice(_baseIdx(drawIdx), _baseIdx(drawIdx) + 20), 12)
        },
        {
            id: 'missing10', label: '미출현 (10회 이상)', group: 'dynamic',
            getTargets: (drawIdx) => {
                const seen = new Set();
                _draws().slice(_baseIdx(drawIdx), _baseIdx(drawIdx) + 10).forEach(d => (d.numbers || []).forEach(n => seen.add(n)));
                return range(1, 45).filter(n => !seen.has(n));
            }
        },
        {
            id: 'missing20', label: '미출현 (20회 이상)', group: 'dynamic',
            getTargets: (drawIdx) => {
                const seen = new Set();
                _draws().slice(_baseIdx(drawIdx), _baseIdx(drawIdx) + 20).forEach(d => (d.numbers || []).forEach(n => seen.add(n)));
                return range(1, 45).filter(n => !seen.has(n));
            }
        },
        {
            id: 'carryover', label: '이월수 후보 (직전 회차)', group: 'dynamic',
            getTargets: (drawIdx) => {
                const d = _draws()[_baseIdx(drawIdx)];
                return d ? [...(d.numbers || [])].sort((a, b) => a - b) : [];
            }
        },
        {
            id: 'carryoverBonus', label: '이월수 + 보너스 (직전 회차)', group: 'dynamic',
            getTargets: (drawIdx) => {
                const d = _draws()[_baseIdx(drawIdx)]; if (!d) return [];
                const s = new Set([...(d.numbers || []), d.bonus].filter(Boolean));
                return [...s].sort((a, b) => a - b);
            }
        },
        {
            id: 'neighbor', label: '이웃수 후보 (직전 회차 ±1)', group: 'dynamic',
            getTargets: (drawIdx) => {
                const d = _draws()[_baseIdx(drawIdx)]; if (!d) return [];
                const set = new Set();
                (d.numbers || []).forEach(n => { if (n > 1) set.add(n - 1); if (n < 45) set.add(n + 1); });
                (d.numbers || []).forEach(n => set.delete(n));
                return [...set].sort((a, b) => a - b);
            }
        },
        {
            id: 'neighborBonus', label: '보너스 이웃수 후보', group: 'dynamic',
            getTargets: (drawIdx) => {
                const d = _draws()[_baseIdx(drawIdx)]; if (!d || !d.bonus) return [];
                const set = new Set();
                if (d.bonus > 1) set.add(d.bonus - 1);
                if (d.bonus < 45) set.add(d.bonus + 1);
                return [...set];
            }
        },
        {
            id: 'lastBonus', label: '직전 회차 보너스', group: 'dynamic',
            getTargets: (drawIdx) => {
                const d = _draws()[_baseIdx(drawIdx)];
                return d?.bonus ? [d.bonus] : [];
            }
        }
    ];

    // ── [fix-367] 회귀 카탈로그 (1~30회귀) — [fix-373] 회차별 재계산 ──
    //   N회귀 = "그 회차 기준 N회 전 회차" — drawIdx 기반
    const REGRESSION_CATALOG = [];
    for (let n = 1; n <= 30; n++) {
        REGRESSION_CATALOG.push({
            id: `regression${n}`,
            label: `${n}회귀`,
            group: 'regression',
            getTargets: (drawIdx) => {
                // drawIdx=-1 → 다음 회차에서 N회귀 = state.draws[N-1]
                // drawIdx=I  → state.draws[I] 회차에서 N회귀 = state.draws[I+N]
                const baseI = (drawIdx == null || drawIdx < 0) ? -1 : drawIdx;
                const d = _draws()[baseI + n];
                return d ? [...(d.numbers || [])].sort((a, b) => a - b) : [];
            }
        });
        REGRESSION_CATALOG.push({
            id: `regression${n}b`,
            label: `${n}회귀 + 보너스`,
            group: 'regression',
            getTargets: (drawIdx) => {
                const baseI = (drawIdx == null || drawIdx < 0) ? -1 : drawIdx;
                const d = _draws()[baseI + n];
                if (!d) return [];
                const set = new Set([...(d.numbers || []), d.bonus].filter(Boolean));
                return [...set].sort((a, b) => a - b);
            }
        });
    }

    function topNNumbers(draws, n) {
        const cnt = Array(46).fill(0);
        draws.forEach(d => (d.numbers || []).forEach(x => cnt[x]++));
        return cnt.map((c, i) => ({ n: i, c })).filter(x => x.n >= 1).sort((a, b) => b.c - a.c || a.n - b.n).slice(0, n).map(x => x.n).sort((a, b) => a - b);
    }
    function bottomNNumbers(draws, n) {
        const cnt = Array(46).fill(0);
        draws.forEach(d => (d.numbers || []).forEach(x => cnt[x]++));
        return cnt.map((c, i) => ({ n: i, c })).filter(x => x.n >= 1).sort((a, b) => a.c - b.c || a.n - b.n).slice(0, n).map(x => x.n).sort((a, b) => a - b);
    }

    // ── 커스텀 분석 fetch ────────────────────────────────────────
    async function fetchCustomAnalyses() {
        if (!window.supabaseClient) return [];
        try {
            const { data, error } = await window.supabaseClient
                .from('ai_custom_analyses')
                .select('id, title, type, target_numbers, rules, target_round, created_at, updated_at')
                .is('target_round', null)        // master 행만
                .or('is_archived.is.null,is_archived.eq.false')   // [fix-385] archived 제외
                .order('created_at', { ascending: true })
                .limit(200);
            if (error) throw error;
            const _norm = (s) => String(s || '').replace(/\s/g, '').replace(/분석$/, '').toLowerCase();
            const seen = new Map();
            (data || []).forEach(item => {
                const key = JSON.stringify((item.target_numbers || []).slice().sort((a, b) => a - b)) +
                            '|' + (item.type || '') + '|' + (item.rules?.formula || '') +
                            '|' + (item.rules?.formula_text || '') + '|' + _norm(item.title);
                if (!seen.has(key)) seen.set(key, item);
            });
            const deduped = [...seen.values()];
            // LNB 순서 적용
            try {
                const _uid = (await window.supabaseClient.auth.getUser())?.data?.user?.id || null;
                const _key = _uid ? `lnbOrder_custom_${_uid}` : 'lnbOrder_custom_guest';
                const _saved = JSON.parse(localStorage.getItem(_key) || 'null');
                if (_saved && _saved.length > 0) {
                    deduped.sort((a, b) => {
                        const iA = _saved.indexOf(`custom_analysis.html?id=${a.id}`);
                        const iB = _saved.indexOf(`custom_analysis.html?id=${b.id}`);
                        if (iA !== -1 && iB !== -1) return iA - iB;
                        if (iA !== -1) return -1;
                        if (iB !== -1) return 1;
                        return 0;
                    });
                }
            } catch (_) { }
            // [fix-379] 커스텀 분석 회차별 재계산 — simulator_custom은 매 회차 시뮬 재실행
            return deduped.map(item => ({
                id: `custom-${item.id}`,
                label: item.title || '커스텀',
                group: 'custom',
                customId: item.id,
                _stored: item,
                getTargets: (drawIdx) => {
                    const isSimulator = item.rules?.formula === 'simulator_custom';
                    const formulaSteps = item.rules?.formula_steps;
                    const draws = state.draws;
                    if (isSimulator && formulaSteps && typeof window.evalSimulatorFormulaForDraw === 'function' && draws.length > 0) {
                        // drawIdx=-1 → 다음 회차 시뮬 (simNow)
                        // drawIdx=N → draws[N] 회차의 round 시점
                        const targetRound = (drawIdx == null || drawIdx < 0)
                            ? (draws[0].round + 1)
                            : (draws[drawIdx]?.round || 0);
                        if (!targetRound) return [];
                        try {
                            const result = window.evalSimulatorFormulaForDraw(formulaSteps, draws, targetRound, 45) || [];
                            return result.filter(n => Number.isInteger(n) && n >= 1 && n <= 45);
                        } catch (e) {
                            console.warn(`[matrix·custom·fix-379] 시뮬 재계산 실패 "${item.title}" round=${targetRound}`, e);
                        }
                    }
                    // fallback (정적 커스텀): stored target_numbers
                    return (item.target_numbers || []).filter(n => Number.isInteger(n) && n >= 1 && n <= 45);
                }
            }));
        } catch (e) {
            console.warn('[matrix] 커스텀 분석 fetch 실패', e);
            return [];
        }
    }

    // ── 메트릭 계산 ──────────────────────────────────────────────
    // [fix-382] 회차별 fresh 매칭 — cat 인자 받아 각 회차 시점 대상번호로 적중 계산
    //   - lastDrawHit: 직전 회차 시점 대상번호 ∩ 그 회차 추첨번호
    //   - avg3/5/10/52: 각 회차마다 fresh 시뮬/계산 후 평균
    //   - size: 다음 회차 시점(drawIdx=-1) 대상번호 갯수
    function computeMetrics(targets, cat = null) {
        const draws = state.draws;
        // cat이 있으면 회차별 fresh 재계산, 없으면 (호환) targets 단일값 매칭
        const hitAt = cat
            ? (drawIdx) => {
                const t = cat.getTargets(drawIdx) || [];
                const set = new Set(t);
                return (draws[drawIdx]?.numbers || []).filter(n => set.has(n)).length;
            }
            : (drawIdx) => {
                const set = new Set(targets);
                return (draws[drawIdx]?.numbers || []).filter(n => set.has(n)).length;
            };
        const avg = (n) => {
            const arr = [];
            for (let i = 0; i < n && i < draws.length; i++) arr.push(hitAt(i));
            return arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : 0;
        };
        return {
            size: targets.length,    // 다음 회차 시점 대상수 (drawIdx=-1, addRow에서 전달된 targets)
            avg10: avg(10),
            avg5: avg(5),
            avg3: avg(3),
            avg52: avg(52),
            lastDrawHit: hitAt(0)    // 1223회 시점 대상번호 ∩ 1223회 추첨번호
        };
    }

    // ── 집합 연산 ────────────────────────────────────────────────
    function setUnion(arrays) {
        const s = new Set();
        arrays.forEach(arr => arr.forEach(n => s.add(n)));
        return [...s].sort((a, b) => a - b);
    }
    function setIntersection(arrays) {
        if (arrays.length === 0) return [];
        return arrays[0].filter(n => arrays.every(arr => arr.includes(n))).sort((a, b) => a - b);
    }
    function setComplement(targetUnion) {
        const s = new Set(targetUnion);
        return range(1, 45).filter(n => !s.has(n));
    }
    function setSymDiff(arrays) {
        // 정확히 1번만 등장한 번호 (홀수 포함)
        const cnt = {};
        arrays.forEach(arr => arr.forEach(n => { cnt[n] = (cnt[n] || 0) + 1; }));
        return Object.keys(cnt).filter(n => cnt[n] === 1).map(Number).sort((a, b) => a - b);
    }
    // 차집합 (b 방식): 각 row마다 "다른 분석 합집합 빼기"
    function setDifferenceForEach(rows) {
        return rows.map((row, idx) => {
            const others = rows.filter((_, i) => i !== idx);
            const othersUnion = setUnion(others.map(r => r.targets));
            const othersSet = new Set(othersUnion);
            const diff = row.targets.filter(n => !othersSet.has(n));
            return { name: `${row.label} − 나머지`, targets: diff, opType: 'difference', sourceLabel: row.label, sourceIdx: idx };
        });
    }

    // ── 렌더 ─────────────────────────────────────────────────────
    function renderEmptyState() {
        $('emptyState').style.display = state.rows.length === 0 ? 'block' : 'none';
    }

    // [fix-407] 바스켓 헬퍼 — GNB 고정수/제외수 동기화
    function getBasket() {
        try {
            if (window.Basket && typeof window.Basket.get === 'function') {
                const b = window.Basket.get();
                return {
                    fixed: new Set((b.fixed || []).map(Number)),
                    exclude: new Set((b.exclude || []).map(Number))
                };
            }
            const raw = JSON.parse(localStorage.getItem('lotto_basket') || '{}');
            return {
                fixed: new Set((raw.fixed || []).map(Number)),
                exclude: new Set((raw.exclude || []).map(Number))
            };
        } catch {
            return { fixed: new Set(), exclude: new Set() };
        }
    }

    function basketClass(n, basket) {
        if (basket.fixed.has(n)) return ' basket-fixed';
        if (basket.exclude.has(n)) return ' basket-exclude';
        return '';
    }

    function basketTitle(n, basket) {
        if (basket.fixed.has(n)) return ` · 고정수`;
        if (basket.exclude.has(n)) return ` · 제외수`;
        return '';
    }

    function renderNumGrid(targets) {
        const set = new Set(targets);
        const basket = getBasket();
        // [fix-364] 1~45 한 줄 표시 (가로 스크롤 wrapper)
        // [fix-407] 고정수/제외수 바스켓 하이라이트 클래스 추가
        return `<div class="num-grid-wrap"><div class="num-grid">${range(1, 45).map(n => {
            const bk = basketClass(n, basket);
            const bkTitle = basketTitle(n, basket);
            if (set.has(n)) return `<div class="num-cell active${bk}" style="background:${ballBg(n)}" title="${n}번 (대상)${bkTitle}">${n}</div>`;
            return `<div class="num-cell inactive${bk}" title="${n}번 (비대상)${bkTitle}">${n}</div>`;
        }).join('')}</div></div>`;
    }

    // [fix-370/382] 인라인 메트릭 6개 (제목 옆) — BOLD 제거, 회차별 fresh 결과
    function renderInlineMetrics(m, lastRound) {
        const fmt = (v) => v.toFixed(2).replace(/\.?0+$/, '') || '0';
        const sep = '<span class="text-gray-300 mx-2">·</span>';
        return `<div class="flex items-center flex-wrap text-[12px] text-gray-500" style="font-feature-settings:'tnum';letter-spacing:-0.01em">
            <span><span class="text-[10px] uppercase tracking-wider text-gray-400 mr-1">대상수</span><span class="text-slate-700">${m.size}</span><span class="text-[10px] text-gray-400 ml-0.5">개</span></span>${sep}
            <span><span class="text-[10px] uppercase tracking-wider text-gray-400 mr-1">${lastRound}회 적중</span><span class="${m.lastDrawHit > 0 ? 'text-emerald-600' : 'text-slate-400'}">${m.lastDrawHit}</span><span class="text-[10px] text-gray-400 ml-0.5">개</span></span>${sep}
            <span><span class="text-[10px] uppercase tracking-wider text-gray-400 mr-1">3회</span><span class="text-slate-700">${fmt(m.avg3)}</span></span>${sep}
            <span><span class="text-[10px] uppercase tracking-wider text-gray-400 mr-1">5회</span><span class="text-slate-700">${fmt(m.avg5)}</span></span>${sep}
            <span><span class="text-[10px] uppercase tracking-wider text-gray-400 mr-1">10회</span><span class="text-slate-700">${fmt(m.avg10)}</span></span>${sep}
            <span><span class="text-[10px] uppercase tracking-wider text-gray-400 mr-1">1년</span><span class="text-blue-700">${fmt(m.avg52)}</span></span>
        </div>`;
    }
    // [fix-370] A/B/C/... 라벨 (Excel 스타일)
    function rowLabel(idx) {
        if (idx < 26) return String.fromCharCode(65 + idx);
        const high = Math.floor(idx / 26) - 1;
        return String.fromCharCode(65 + high) + String.fromCharCode(65 + (idx % 26));
    }
    function rowLabelChip(idx) {
        return `<span class="flex-shrink-0 inline-flex items-center justify-center w-8 h-8 rounded-lg text-base font-black bg-blue-50 text-blue-700">${rowLabel(idx)}</span>`;
    }

    function typeBadge(type) {
        const map = {
            static: { label: '정적', bg: '#EEF2FF', color: '#4F46E5' },
            dynamic: { label: '동적', bg: '#ECFDF5', color: '#059669' },
            regression: { label: '회귀', bg: '#FCE7F3', color: '#BE185D' },
            custom: { label: '커스텀', bg: '#FEF3C7', color: '#D97706' }
        };
        const t = map[type] || map.static;
        return `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-black uppercase tracking-wider" style="background:${t.bg};color:${t.color}">${t.label}</span>`;
    }

    function renderRows() {
        const lastRound = state.draws[0]?.round || '—';
        // [fix-370] 라벨 A/B/C + 제목 + 인라인 메트릭 6개
        $('analysisRows').innerHTML = state.rows.map((row, idx) => `
            <div class="row-card">
                <div class="flex items-start gap-3 mb-4">
                    ${rowLabelChip(idx)}
                    <div class="flex-1 min-w-0">
                        <div class="flex items-baseline gap-3 flex-wrap mb-2">
                            ${typeBadge(row.group)}
                            <span class="text-base font-black text-slate-800 row-title">${escape(row.label)}</span>
                        </div>
                        ${renderInlineMetrics(row.metrics, lastRound)}
                    </div>
                    <button onclick="window._matrix.removeRow(${idx})" class="flex-shrink-0 flex items-center gap-1 text-xs text-rose-500 hover:text-rose-700 font-bold transition-colors mt-2">
                        <span class="material-symbols-outlined text-[16px]">close</span>
                    </button>
                </div>
                <div>${renderNumGrid(row.targets)}</div>
            </div>
        `).join('');
    }

    function renderOperations() {
        const container = $('operationRows');
        if (state.rows.length < 2) {
            container.innerHTML = '';
            return;
        }
        const lastRound = state.draws[0]?.round || '—';
        const targets = state.rows.map(r => r.targets);
        const opRows = [];

        if (state.ops.union) {
            const t = setUnion(targets);
            opRows.push({ name: `${state.rows.length}개 분석 합집합 (∪)`, targets: t, metrics: computeMetrics(t), opType: 'union', desc: '모든 대상 번호의 합집합' });
        }
        if (state.ops.intersection) {
            const t = setIntersection(targets);
            opRows.push({ name: `${state.rows.length}개 분석 교집합 (∩)`, targets: t, metrics: computeMetrics(t), opType: 'intersection', desc: '모든 분석에 공통된 번호' });
        }
        if (state.ops.symdiff) {
            const t = setSymDiff(targets);
            opRows.push({ name: `대칭차 (△)`, targets: t, metrics: computeMetrics(t), opType: 'symdiff', desc: '정확히 1개 분석에만 속한 번호' });
        }
        if (state.ops.complement) {
            const t = setComplement(setUnion(targets));
            opRows.push({ name: `미포함 (∁)`, targets: t, metrics: computeMetrics(t), opType: 'complement', desc: '어디에도 속하지 않은 번호' });
        }
        if (state.ops.difference) {
            const diffs = setDifferenceForEach(state.rows);
            // [fix-381] 라벨 'A 고유값' / 'B 고유값' 표시 (sourceIdx 활용)
            diffs.forEach(d => {
                const srcLabel = rowLabel(d.sourceIdx);
                opRows.push({
                    name: `${srcLabel} 고유값`,
                    targets: d.targets,
                    metrics: computeMetrics(d.targets),
                    opType: 'difference',
                    desc: `${d.sourceLabel}에만 있고 다른 분석엔 없음`
                });
            });
        }

        const opLabel = (op) => ({
            union: '∪', intersection: '∩', difference: '−', symdiff: '△', complement: '∁'
        }[op] || '?');

        container.innerHTML = opRows.length === 0 ? '' :
            `<div class="pt-4 mt-2 border-t border-gray-200">
                <div class="flex items-baseline gap-3 mb-4">
                    <span class="text-[11px] uppercase tracking-wider text-gray-400 font-bold">집합 연산 결과</span>
                    <span class="text-xs text-gray-400">${opRows.length}개</span>
                </div>
                <div class="space-y-4">
                    ${opRows.map(r => `
                        <div class="row-card op op-${r.opType}">
                            <div class="flex items-start gap-3 mb-4">
                                <span class="flex-shrink-0 inline-flex items-center justify-center w-8 h-8 rounded-lg text-base font-black" style="background:${opColor(r.opType)};color:#fff">${opLabel(r.opType)}</span>
                                <div class="flex-1 min-w-0">
                                    <div class="flex items-baseline gap-3 flex-wrap mb-2">
                                        <span class="text-base font-black text-slate-800 row-title">${escape(r.name)}</span>
                                        <span class="text-[11px] text-gray-400">${escape(r.desc)}</span>
                                    </div>
                                    ${renderInlineMetrics(r.metrics, lastRound)}
                                </div>
                            </div>
                            <div>${renderNumGrid(r.targets)}</div>
                        </div>
                    `).join('')}
                </div>
            </div>`;
    }
    function opColor(t) { return { union: '#A78BFA', intersection: '#10B981', difference: '#F97316', symdiff: '#EC4899', complement: '#94A3B8' }[t] || '#94A3B8'; }
    function escape(s) { return String(s || '').replace(/[<>&"]/g, c => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' }[c])); }

    function renderAll() {
        renderEmptyState();
        renderRows();
        renderOperations();
        renderComparisonTable();
    }

    // ── [fix-366] 회차 × 분석 매트릭스 — 역대 회차별 적중 통계 ────
    state.matrixRange = 50;   // 기본 50회

    function buildColumns() {
        // [fix-370] 컬럼 = 분석 row(라벨 A/B/C) + 활성 집합 연산 row
        // [fix-373] cat 참조 보관 → 매트릭스 표에서 회차별 fresh targets 계산
        const cols = state.rows.map((r, idx) => ({
            kind: 'analysis', label: r.label, shortLabel: rowLabel(idx),
            type: r.group, targets: r.targets, cat: r.cat
        }));
        if (state.rows.length < 2) return cols;
        const ts = state.rows.map(r => r.targets);
        // [fix-373] 고유 라벨 → A고유 / B고유 (분석 라벨 단축)
        if (state.ops.union) cols.push({ kind: 'op', opType: 'union', label: '합집합', shortLabel: '∪', targets: setUnion(ts) });
        if (state.ops.intersection) cols.push({ kind: 'op', opType: 'intersection', label: '교집합', shortLabel: '∩', targets: setIntersection(ts) });
        if (state.ops.symdiff) cols.push({ kind: 'op', opType: 'symdiff', label: '대칭차', shortLabel: '△', targets: setSymDiff(ts) });
        if (state.ops.complement) cols.push({ kind: 'op', opType: 'complement', label: '미포함', shortLabel: '∁', targets: setComplement(setUnion(ts)) });
        if (state.ops.difference) {
            setDifferenceForEach(state.rows).forEach((d, di) => {
                const sourceIdx = state.rows.findIndex(r => r.label === d.sourceLabel);
                const srcLabel = sourceIdx >= 0 ? rowLabel(sourceIdx) : '?';
                cols.push({
                    kind: 'op', opType: 'difference',
                    label: `${srcLabel} 고유`,
                    shortLabel: `${srcLabel}고유`,
                    sourceIdx, targets: d.targets
                });
            });
        }
        return cols;
    }

    // [fix-373] 헤더 색상 보더 제거, 라벨만 표시
    function colHeaderLabel(col) {
        if (col.kind === 'analysis') {
            return `<span class="text-[16px] font-black" style="color:#fff" title="${escape(col.label)}">${col.shortLabel}</span>`;
        }
        const map = {
            union: '∪', intersection: '∩', difference: col.shortLabel || '−',
            symdiff: '△', complement: '∁'
        };
        return `<span class="text-[14px] font-black" style="color:#fff" title="${escape(col.label)}">${map[col.opType] || col.shortLabel}</span>`;
    }

    function hitClass(hit, size) {
        // [fix-374] 단순화: 0 / 일반 / 최대 3단계만
        if (hit === 0) return 'hit-0';
        if (size > 0 && hit === Math.min(6, size)) return 'hit-max';
        return 'hit-mid';
    }

    function ballChip(n, dim = false) {
        const bg = dim ? '#fff' : ballBg(n);
        const color = dim ? '#94A3B8' : '#fff';
        // [fix-407] 바스켓 하이라이트 — 고정수=초록 링 / 제외수=빨강 링 (border 대체)
        const basket = getBasket();
        let extraClass = '';
        let border = dim ? 'border:1px solid #E2E8F0;' : 'box-shadow:0 1px 2px rgba(0,0,0,0.12);';
        let titleSuffix = '';
        if (basket.fixed.has(n)) {
            extraClass = ' ball-chip-basket-fixed';
            border = '';
            titleSuffix = ' · 고정수';
        } else if (basket.exclude.has(n)) {
            extraClass = ' ball-chip-basket-exclude';
            border = '';
            titleSuffix = ' · 제외수';
        }
        return `<span class="inline-flex items-center justify-center font-black${extraClass}" title="${n}번${titleSuffix}" style="width:24px;height:24px;border-radius:50%;font-size:10px;background:${bg};color:${color};${border}">${n}</span>`;
    }

    function renderComparisonTable() {
        const wrap = $('comparisonTableWrap');
        if (!wrap) return;
        if (state.rows.length === 0) {
            wrap.style.display = 'none';
            return;
        }
        wrap.style.display = 'block';

        const cols = buildColumns();
        const rangeN = state.matrixRange;
        const data = state.draws.slice(0, rangeN);

        // [fix-373] 회차별 fresh 재계산: 각 회차에서 해당 회차 시점 기준 분석 대상 다시 산출
        //   - 정적: drawIdx 무관 동일
        //   - 동적/회귀: drawIdx 기반 직전 데이터 사용
        //   - 집합 연산: 매 회차 분석 col targets 재계산 후 연산
        const computeRowCols = (drawIdx) => {
            // 분석 cols
            const analysisCols = state.rows.map((r, idx) => {
                const t = r.cat ? (r.cat.getTargets(drawIdx) || []) : r.targets;
                return { kind: 'analysis', label: r.label, shortLabel: rowLabel(idx), type: r.group, targets: t };
            });
            if (state.rows.length < 2) return analysisCols;
            const ts = analysisCols.map(c => c.targets);
            const result = [...analysisCols];
            if (state.ops.union) result.push({ kind: 'op', opType: 'union', shortLabel: '∪', targets: setUnion(ts) });
            if (state.ops.intersection) result.push({ kind: 'op', opType: 'intersection', shortLabel: '∩', targets: setIntersection(ts) });
            if (state.ops.symdiff) result.push({ kind: 'op', opType: 'symdiff', shortLabel: '△', targets: setSymDiff(ts) });
            if (state.ops.complement) result.push({ kind: 'op', opType: 'complement', shortLabel: '∁', targets: setComplement(setUnion(ts)) });
            if (state.ops.difference) {
                state.rows.forEach((_, srcI) => {
                    const others = analysisCols.filter((_, j) => j !== srcI).map(c => c.targets);
                    const othersUnion = setUnion(others);
                    const oset = new Set(othersUnion);
                    const diff = analysisCols[srcI].targets.filter(n => !oset.has(n));
                    result.push({ kind: 'op', opType: 'difference', shortLabel: `${rowLabel(srcI)}고유`, targets: diff });
                });
            }
            return result;
        };

        // 각 회차별 cols 계산 + 적중수 매트릭스
        // [fix-380] drawIdx = i (data[i] = state.draws[i]). 이전 i+1은 한 회차 밀림 버그.
        //   카탈로그 정의: drawIdx=N → state.draws[N] 회차 시점 평가
        //   회귀 1회 = draws[drawIdx + 1] (직전), 시뮬 = draws[drawIdx].round (그 회차)
        const drawCols = data.map((d, i) => computeRowCols(i));
        const colCount = cols.length;
        const hitMatrix = data.map((d, i) => {
            const winSet = new Set(d.numbers || []);
            return drawCols[i].map(col => col.targets.filter(n => winSet.has(n)).length);
        });
        const targetSizeMatrix = drawCols.map(rowCols => rowCols.map(c => c.targets.length));

        // 컬럼별 통계 (평균/최대/최소)
        const colStats = cols.map((_, ci) => {
            const arr = hitMatrix.map(r => r[ci]);
            const sum = arr.reduce((a, b) => a + b, 0);
            const avg = arr.length ? sum / arr.length : 0;
            const max = arr.length ? Math.max(...arr) : 0;
            const min = arr.length ? Math.min(...arr) : 0;
            return { sum, avg, max, min };
        });
        // 대상수도 회차마다 다를 수 있으니 평균
        const targetSizeAvg = cols.map((_, ci) => {
            const sizes = targetSizeMatrix.map(r => r[ci]);
            return sizes.length ? (sizes.reduce((a, b) => a + b, 0) / sizes.length) : 0;
        });

        // [fix-378] thead 5행 — 좌측 sticky 컬럼에 행 라벨 명확히 (회차/갯수/평균/최대/최소)
        //   당첨번호 컬럼은 rowspan=5 (한 번만 표시)
        //   매트릭스 표와 통계가 한 표 안에서 컬럼 정렬됨
        const head = $('matrixTableHead');
        const thRowLabel = 'font-weight:400;font-size:10px;color:#94A3B8;text-align:center;padding:6px 10px';
        const thStat = 'font-weight:400;font-size:11px;color:#CBD5E1;text-align:center;padding:6px 10px';
        head.innerHTML = `
            <tr>
                <th class="matrix-cell-th matrix-cell-round-th text-center" style="min-width:80px;font-weight:400;color:#fff;padding:10px">회차</th>
                <th class="matrix-cell-th matrix-cell-balls-th text-center" rowspan="5" style="min-width:240px;font-weight:400;color:#fff;padding:10px">당첨번호</th>
                ${cols.map(col => `<th class="matrix-cell-th text-center" style="font-weight:400;color:#fff;padding:10px">${colHeaderLabel(col)}</th>`).join('')}
            </tr>
            <tr>
                <th class="matrix-cell-round-th" style="${thRowLabel};position:sticky;left:0;background:#0f172a;z-index:25">갯수</th>
                ${cols.map((col, ci) => {
                    const isVar = (state.rows[ci]?.group === 'dynamic') || (state.rows[ci]?.group === 'regression') || col.kind === 'op';
                    return `<th style="${thStat}">${isVar ? '~' : ''}${targetSizeAvg[ci].toFixed(0)}</th>`;
                }).join('')}
            </tr>
            <tr>
                <th class="matrix-cell-round-th" style="${thRowLabel};position:sticky;left:0;background:#0f172a;z-index:25">평균</th>
                ${colStats.map(s => `<th style="${thStat}">${s.avg.toFixed(2)}</th>`).join('')}
            </tr>
            <tr>
                <th class="matrix-cell-round-th" style="${thRowLabel};position:sticky;left:0;background:#0f172a;z-index:25">최대</th>
                ${colStats.map(s => `<th style="${thStat}">${s.max}</th>`).join('')}
            </tr>
            <tr>
                <th class="matrix-cell-round-th" style="${thRowLabel};position:sticky;left:0;background:#0f172a;z-index:25">최소</th>
                ${colStats.map(s => `<th style="${thStat}">${s.min}</th>`).join('')}
            </tr>
        `;

        // [fix-377] 바디 — 적중수 + 회차별 대상수 (작게, 그 회차 시점 기준)
        const tbody = $('matrixTableBody');
        const rows = data.map((d, i) => {
            const cellsHtml = cols.map((col, ci) => {
                const hit = hitMatrix[i][ci];
                const size = targetSizeMatrix[i][ci];
                return `<td class="matrix-cell">
                    <span class="${hitClass(hit, size)}">${hit}</span>
                    <span class="text-gray-300" style="font-size:9px;margin-left:3px">/${size}</span>
                </td>`;
            }).join('');
            const ballsHtml = (d.numbers || []).map(n => ballChip(n)).join('');
            const bonusHtml = d.bonus ? `<span class="text-gray-300 mx-1 text-xs">+</span>${ballChip(d.bonus)}` : '';
            return `<tr class="hover:bg-slate-50/60 transition-colors">
                <td class="matrix-cell matrix-cell-round">${d.round}회</td>
                <td class="matrix-cell-balls" style="text-align:center"><div class="flex items-center gap-1 flex-nowrap" style="justify-content:center">${ballsHtml}${bonusHtml}</div></td>
                ${cellsHtml}
            </tr>`;
        }).join('');

        tbody.innerHTML = rows;

        // 상단 요약 (BOLD 제거, 단일 톤)
        const summary = $('matrixSummary');
        if (summary) {
            const totalHits = colStats.reduce((s, c) => s + c.sum, 0);
            const cellCount = colCount * data.length;
            summary.innerHTML = `<span class="text-slate-700">${data.length}회차</span> × <span class="text-slate-700">${colCount}개 분석/연산</span> · 평균 적중 <span class="text-blue-700">${(totalHits / Math.max(1, cellCount)).toFixed(2)}</span>개 · <span class="text-slate-500">회차별 fresh 재계산</span>`;
        }
    }

    // ── 행 조작 ──────────────────────────────────────────────────
    function addRow(catalogItem) {
        if (state.rows.some(r => r.id === catalogItem.id)) {
            console.warn('[matrix] 이미 추가된 분석:', catalogItem.id);
            return;
        }
        // [fix-383] 커스텀 분석은 stored target_numbers 사용 (사용자 simulator UI와 일치)
        //   매트릭스 표는 cat.getTargets(drawIdx) fresh 재계산으로 회차별 정확성 유지
        let targets;
        if (catalogItem.group === 'custom' && catalogItem._stored?.target_numbers?.length > 0) {
            targets = catalogItem._stored.target_numbers.filter(n => Number.isInteger(n) && n >= 1 && n <= 45);
        } else {
            targets = catalogItem.getTargets(-1) || [];
        }
        state.rows.push({
            id: catalogItem.id,
            label: catalogItem.label,
            group: catalogItem.group,
            cat: catalogItem,
            targets,
            metrics: computeMetrics(targets, catalogItem)   // ★ cat 전달 → 회차별 fresh 매칭
        });
        renderAll();
    }
    function removeRow(idx) {
        state.rows.splice(idx, 1);
        renderAll();
    }
    function clearAll() {
        if (state.rows.length === 0) return;
        if (!confirm('모든 분석을 비울까요?')) return;
        state.rows = [];
        renderAll();
    }

    // ── 모달 ─────────────────────────────────────────────────────
    // [fix-387] 모달 열 때마다 커스텀 카탈로그 fresh 갱신
    //   - 다른 페이지에서 분석 숨김/삭제/이름 변경된 경우 즉시 반영
    async function openAnalysisModal() {
        state.modalSearch = '';
        state.modalTab = 'all';
        $('analysisSearch').value = '';
        document.querySelectorAll('#analysisModal .tab-btn').forEach(b => {
            b.classList.toggle('active', b.dataset.tab === 'all');
        });
        // 카탈로그 fresh — 커스텀만 다시 fetch (정적/동적/회귀는 회차 데이터 기반이라 그대로)
        try {
            const customs = await fetchCustomAnalyses();
            state.catalog = [...STATIC_CATALOG, ...DYNAMIC_CATALOG, ...REGRESSION_CATALOG, ...customs];

            // 이미 추가된 row 중 카탈로그에서 사라진(숨김/삭제) 분석은 row에서 제거
            const validIds = new Set(state.catalog.map(c => c.id));
            const beforeLen = state.rows.length;
            state.rows = state.rows.filter(r => validIds.has(r.id));
            if (state.rows.length !== beforeLen) {
                console.log(`[fix-387] row 정리 — ${beforeLen - state.rows.length}개 제거 (숨김/삭제된 분석)`);
                renderAll();
            }
            // 이름 변경 반영 — 동일 id의 row label 갱신
            state.rows.forEach(r => {
                const fresh = state.catalog.find(c => c.id === r.id);
                if (fresh && fresh.label !== r.label) {
                    console.log(`[fix-387] 이름 변경 반영: "${r.label}" → "${fresh.label}"`);
                    r.label = fresh.label;
                    r.cat = fresh;
                }
            });
            renderRows();
            renderOperations();
        } catch (e) {
            console.warn('[matrix·fix-387] 카탈로그 갱신 실패', e);
        }
        renderModalList();
        $('analysisModal').classList.add('open');
        setTimeout(() => $('analysisSearch').focus(), 50);
    }
    function closeAnalysisModal() { $('analysisModal').classList.remove('open'); }
    window.closeAnalysisModal = closeAnalysisModal;

    function renderModalList() {
        const selectedIds = new Set(state.rows.map(r => r.id));
        const search = state.modalSearch.toLowerCase();
        const filtered = state.catalog.filter(item => {
            if (state.modalTab !== 'all' && item.group !== state.modalTab) return false;
            if (search && !item.label.toLowerCase().includes(search)) return false;
            return true;
        });
        // [fix-367] 그룹 4개 — 정적 / 동적 / 회귀 / 커스텀
        const groupName = { static: '정적 분석', dynamic: '동적 분석', regression: '회귀 분석', custom: '커스텀 분석' };
        const groupOrder = ['static', 'dynamic', 'regression', 'custom'];
        const grouped = { static: [], dynamic: [], regression: [], custom: [] };
        filtered.forEach(item => { if (grouped[item.group]) grouped[item.group].push(item); });
        const list = $('analysisModalList');
        if (filtered.length === 0) {
            list.innerHTML = '<div class="text-center py-8 text-sm text-gray-400">검색 결과 없음</div>';
            return;
        }
        list.innerHTML = groupOrder.filter(g => grouped[g].length > 0).map(g => `
            <div class="mb-3">
                <div class="text-[10px] uppercase tracking-wider text-gray-400 font-bold px-3 mb-1.5">${groupName[g]} · ${grouped[g].length}</div>
                ${grouped[g].map(item => {
                    // [fix-383] 커스텀 = stored 사용, 그 외 = drawIdx=-1 fresh
                    let targets;
                    if (item.group === 'custom' && item._stored?.target_numbers?.length > 0) {
                        targets = item._stored.target_numbers.filter(n => Number.isInteger(n) && n >= 1 && n <= 45);
                    } else {
                        targets = item.getTargets(-1) || [];
                    }
                    const disabled = selectedIds.has(item.id);
                    return `<div class="analysis-pick ${disabled ? 'disabled' : ''}" data-id="${item.id}">
                        <div class="flex items-center justify-between gap-3">
                            <div class="flex-1 min-w-0">
                                <div class="text-sm text-slate-800 truncate">${escape(item.label)}</div>
                                <div class="text-[11px] text-gray-500 mt-0.5">${targets.length}개 번호 · ${disabled ? '이미 추가됨' : `예: ${targets.slice(0, 5).join(', ')}${targets.length > 5 ? '…' : ''}`}</div>
                            </div>
                            ${typeBadge(item.group)}
                        </div>
                    </div>`;
                }).join('')}
            </div>
        `).join('');
        list.querySelectorAll('.analysis-pick:not(.disabled)').forEach(el => {
            el.addEventListener('click', () => {
                const id = el.dataset.id;
                const item = state.catalog.find(x => x.id === id);
                if (item) { addRow(item); closeAnalysisModal(); }
            });
        });
    }

    // ── 저장/불러오기 (localStorage) ─────────────────────────────
    const SAVE_KEY = 'analysis_matrix_saved';

    function getSavedList() {
        try { return JSON.parse(localStorage.getItem(SAVE_KEY) || '[]'); } catch (_) { return []; }
    }
    function setSavedList(list) {
        localStorage.setItem(SAVE_KEY, JSON.stringify(list));
    }
    function openSaveModal() {
        $('loadModalTitle').textContent = '매트릭스 저장';
        $('loadModalDesc').textContent = '현재 매트릭스 구성을 저장합니다';
        $('saveModalForm').classList.remove('hidden');
        $('saveNameInput').value = '';
        renderSavedList(false);
        $('loadModal').classList.add('open');
        setTimeout(() => $('saveNameInput').focus(), 50);
    }
    function openLoadModal() {
        $('loadModalTitle').textContent = '매트릭스 불러오기';
        $('loadModalDesc').textContent = '저장된 매트릭스를 선택하세요';
        $('saveModalForm').classList.add('hidden');
        renderSavedList(true);
        $('loadModal').classList.add('open');
    }
    function closeLoadModal() { $('loadModal').classList.remove('open'); }
    window.closeLoadModal = closeLoadModal;

    function renderSavedList(loadMode) {
        const list = getSavedList();
        const el = $('loadModalList');
        if (list.length === 0) {
            el.innerHTML = '<div class="text-center py-8 text-sm text-gray-400">저장된 매트릭스 없음</div>';
            return;
        }
        el.innerHTML = list.map((item, i) => `
            <div class="analysis-pick ${loadMode ? '' : 'cursor-default hover:bg-transparent hover:border-transparent'}" data-idx="${i}">
                <div class="flex items-center justify-between gap-3">
                    <div class="flex-1 min-w-0">
                        <div class="text-sm font-bold text-slate-800 truncate">${escape(item.name)}</div>
                        <div class="text-[11px] text-gray-500 mt-0.5">분석 ${item.rows.length}개 · ${new Date(item.createdAt).toLocaleString('ko-KR', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</div>
                    </div>
                    <button class="btn-delete w-7 h-7 rounded-lg text-rose-400 hover:bg-rose-50 hover:text-rose-600 flex items-center justify-center" data-idx="${i}">
                        <span class="material-symbols-outlined text-[16px]">delete</span>
                    </button>
                </div>
            </div>`).join('');
        el.querySelectorAll('.btn-delete').forEach(b => b.addEventListener('click', (e) => {
            e.stopPropagation();
            const idx = parseInt(b.dataset.idx);
            const list = getSavedList();
            list.splice(idx, 1);
            setSavedList(list);
            renderSavedList(loadMode);
        }));
        if (loadMode) {
            el.querySelectorAll('.analysis-pick').forEach(el2 => el2.addEventListener('click', () => {
                const idx = parseInt(el2.dataset.idx);
                loadSaved(idx);
                closeLoadModal();
            }));
        }
    }

    function saveCurrent(name) {
        if (!name) { alert('이름을 입력하세요'); return; }
        if (state.rows.length === 0) { alert('저장할 분석이 없습니다'); return; }
        const list = getSavedList();
        list.unshift({
            name,
            rows: state.rows.map(r => ({ id: r.id, label: r.label, group: r.group })),
            ops: { ...state.ops },
            createdAt: new Date().toISOString()
        });
        setSavedList(list);
        closeLoadModal();
        alert(`"${name}" 저장 완료`);
    }
    function loadSaved(idx) {
        const list = getSavedList();
        const item = list[idx];
        if (!item) return;
        state.rows = [];
        item.rows.forEach(r => {
            const cat = state.catalog.find(c => c.id === r.id);
            if (cat) addRow(cat);
            else console.warn('[matrix] 카탈로그 미스 — 무시:', r.id, r.label);
        });
        if (item.ops) {
            state.ops = { ...state.ops, ...item.ops };
            document.querySelectorAll('.op-toggle').forEach(b => {
                b.classList.toggle('active', !!state.ops[b.dataset.op]);
            });
        }
        renderAll();
    }

    // ── 초기화 ───────────────────────────────────────────────────
    async function init() {
        const sb = window.supabaseClient;
        if (!sb) { console.error('[matrix] Supabase 클라이언트 없음'); return; }

        // 회차 데이터 로드 (최근 1년 + a)
        const { data: drawsData, error: drawsErr } = await sb
            .from('lotto_draws')
            .select('round, date, numbers, bonus')
            .order('round', { ascending: false })
            .limit(500);
        if (drawsErr) { console.error('[matrix] draws 로드 실패', drawsErr); return; }
        state.draws = (drawsData || []).map(d => ({
            round: d.round,
            date: d.date,
            numbers: (d.numbers || []).slice().sort((a, b) => a - b),
            bonus: d.bonus
        }));
        state.targetRound = (state.draws[0]?.round || 0) + 1;
        $('targetRoundDisplay').textContent = state.targetRound;

        // 카탈로그 빌드 — [fix-367] 회귀 그룹 추가
        const customs = await fetchCustomAnalyses();
        state.catalog = [...STATIC_CATALOG, ...DYNAMIC_CATALOG, ...REGRESSION_CATALOG, ...customs];
        console.log(`[matrix] 카탈로그 ${state.catalog.length}개 (정적 ${STATIC_CATALOG.length} + 동적 ${DYNAMIC_CATALOG.length} + 회귀 ${REGRESSION_CATALOG.length} + 커스텀 ${customs.length})`);

        // 이벤트 바인딩
        $('btnAddAnalysis').addEventListener('click', openAnalysisModal);
        $('btnSave').addEventListener('click', openSaveModal);
        $('btnLoad').addEventListener('click', openLoadModal);
        $('btnClear').addEventListener('click', clearAll);
        $('analysisSearch').addEventListener('input', (e) => {
            state.modalSearch = e.target.value;
            renderModalList();
        });
        document.querySelectorAll('#analysisModal .tab-btn').forEach(b => b.addEventListener('click', () => {
            state.modalTab = b.dataset.tab;
            document.querySelectorAll('#analysisModal .tab-btn').forEach(x => x.classList.toggle('active', x === b));
            renderModalList();
        }));
        document.querySelectorAll('.op-toggle').forEach(b => b.addEventListener('click', () => {
            const op = b.dataset.op;
            state.ops[op] = !state.ops[op];
            b.classList.toggle('active', state.ops[op]);
            renderOperations();
            renderComparisonTable();   // [fix-366] 매트릭스 리스트도 즉시 갱신
        }));
        // [fix-366] 회차 범위 버튼
        document.querySelectorAll('.range-btn').forEach(b => b.addEventListener('click', () => {
            state.matrixRange = parseInt(b.dataset.range);
            document.querySelectorAll('.range-btn').forEach(x => x.classList.toggle('active', x === b));
            renderComparisonTable();
        }));
        $('confirmSaveBtn').addEventListener('click', () => {
            saveCurrent($('saveNameInput').value.trim());
        });
        $('saveNameInput').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') saveCurrent($('saveNameInput').value.trim());
        });

        // [fix-407] 바스켓(고정수/제외수) 변경 시 즉시 재렌더 — GNB Basket 패널 등에서 변경
        window.addEventListener('basketChanged', () => {
            console.log('[matrix] basketChanged → re-render');
            renderAll();
        });
        // storage 이벤트 — 다른 탭에서 변경된 경우 동기화
        window.addEventListener('storage', (e) => {
            if (e.key === 'lotto_basket') renderAll();
        });

        renderAll();
    }

    // 외부 노출
    window._matrix = {
        addRow, removeRow, state
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
