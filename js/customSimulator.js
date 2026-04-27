/**
 * 커스텀 연산 시뮬레이터 & 대시보드 (customSimulator.js)
 */

const CustomSim = {
    draws: [],
    lotteries: [],
    currentLottery: null,
    results: [],

    init: async () => {
        console.log('[CustomSim] Initializing...');
        CustomSim.showLoading(true);

        try {
            // GNB 로드
            if (window.Layout && window.Layout.loadGNB) {
                await window.Layout.loadGNB();
            }

            // 로또 목록 로드 (동행 + 해외)
            await CustomSim.loadLotteries();

            // 대시보드 로드
            await CustomSim.loadDashboard();

            // 이벤트 바인딩
            document.getElementById('windowSlider').addEventListener('input', (e) => {
                document.getElementById('windowDisplay').innerText = e.target.value;
            });

        } catch (e) {
            console.error('[CustomSim] Init Error:', e);
        } finally {
            CustomSim.showLoading(false);
        }
    },

    loadLotteries: async () => {
        const { data, error } = await window.supabaseClient
            .from('lotteries')
            .select('*')
            .order('country', { ascending: true })
            .order('name', { ascending: true });

        if (error) {
            console.error('[CustomSim] Load Lotteries Error:', error);
            return;
        }

        const group = document.getElementById('globalLottoGroup');
        group.innerHTML = '';
        
        data.forEach(l => {
            if (l.id === 'korea') return; // Korea is already in static option
            const opt = document.createElement('option');
            opt.value = l.id;
            opt.innerText = `[${l.country}] ${l.name}`;
            group.appendChild(opt);
        });
        
        CustomSim.lotteries = data;
    },

    switchTab: (tabId) => {
        document.getElementById('tab-simulator').classList.toggle('hidden', tabId !== 'simulator');
        document.getElementById('tab-dashboard').classList.toggle('hidden', tabId !== 'dashboard');
        
        document.getElementById('btn-simulator').classList.toggle('connected-tab-active', tabId === 'simulator');
        document.getElementById('btn-dashboard').classList.toggle('connected-tab-active', tabId === 'dashboard');
    },

    run: async () => {
        const lotteryId = document.getElementById('dbSelect').value;
        const formulaStr = document.getElementById('formulaInput').value.trim();
        const N = parseInt(document.getElementById('windowSlider').value);

        if (!formulaStr) {
            alert('수식을 입력해 주세요.');
            return;
        }

        CustomSim.showLoading(true);
        try {
            let draws = [];
            const maxBall = CustomSim.getMaxBall(lotteryId);

            if (lotteryId === 'korea') {
                // 1-1. 대한민국 데이터 (lotto_draws)
                const { data, error } = await window.supabaseClient
                    .from('lotto_draws')
                    .select('*')
                    .order('round', { ascending: true });

                if (error) throw error;
                draws = data.map(d => ({
                    drawNo: d.round,
                    drawDate: d.date,
                    numbers: d.numbers.sort((a,b)=>a-b),
                    bonus: d.bonus,
                    maxBall: 45
                }));
            } else {
                // 1-2. 해외 데이터 (draws)
                const { data, error } = await window.supabaseClient
                    .from('draws')
                    .eq('lottery_id', lotteryId)
                    .order('draw_no', { ascending: true });

                if (error) throw error;
                draws = data.map(d => ({
                    drawNo: d.draw_no,
                    drawDate: d.draw_date,
                    numbers: [d.n1, d.n2, d.n3, d.n4, d.n5, d.n6].filter(n => n != null).sort((a,b)=>a-b),
                    bonus: d.b1,
                    maxBall: maxBall
                }));
            }

            if (!draws || draws.length < N + 2) {
                alert('시뮬레이션을 위한 데이터가 부족합니다. (최소 N+2회차 필요)');
                return;
            }

            // 3. 시뮬레이션 실행
            CustomSim.results = CustomSim.calculate(draws, formulaStr, N);

            // 4. UI 렌더링
            CustomSim.renderResults();
            document.getElementById('resultCard').classList.remove('hidden');

        } catch (e) {
            console.error('[CustomSim] Run Error:', e);
            alert('시뮬레이션 중 오류가 발생했습니다: ' + e.message);
        } finally {
            CustomSim.showLoading(false);
        }
    },

    /**
     * 핵심 연산 로직
     */
    calculate: (draws, formulaStr, N) => {
        const results = [];
        let totalHitRate = 0;

        // 수식 파싱 (순차 연산을 위해 토큰화)
        // 정규식: N-x[y], drawNo.digitSum, 숫자, 연산자(+, -, *, /, %)
        const tokens = CustomSim.tokenize(formulaStr);

        // 시뮬레이션 루프 (i번째 회차에 대해 예측 시도)
        for (let i = N + 1; i < draws.length; i++) {
            const current = draws[i];
            
            // 윈도우 합집합 (T-1 ~ T-N)
            const windowSet = new Set();
            for (let k = 1; k <= N; k++) {
                draws[i - k].numbers.forEach(n => windowSet.add(n));
            }

            // 수식 적용 (현재 회차 i에 대한 예측값 도출)
            const predictedValue = CustomSim.evaluateSequential(tokens, draws, i);
            const normalized = CustomSim.normalize(predictedValue, current.maxBall);

            // Hit 판정
            const actualSet = new Set(current.numbers);
            const isHit = normalized && actualSet.has(normalized);
            const hitCount = isHit ? 1 : 0; // 이 엔진은 수식 하나당 번호 1개를 생성한다고 가정 (기획서 예시 기준)
            
            results.push({
                drawNo: current.drawNo,
                windowList: Array.from(windowSet).sort((a,b)=>a-b),
                actualNumbers: current.numbers,
                predicted: normalized,
                isHit: isHit
            });

            if (isHit) totalHitRate += 100; // 수식 1개 적중시 100% (필터 성격에 따라 조정 가능)
        }

        const avg = results.length > 0 ? (totalHitRate / results.length).toFixed(1) : 0;
        document.getElementById('avgHitRate').innerText = `${avg}%`;

        return results.reverse(); // 최신 회차가 위로 오게
    },

    tokenize: (str) => {
        // 간단한 토큰화: 공백 제거 후 연산자와 피연산자 분리
        // 지원: N-x[y], drawNo.digitSum, 숫자
        const regex = /(N-\d+\[\d+\]|drawNo\.digitSum|\d+|[\+\-\*\/\%])/g;
        return str.replace(/\s+/g, '').match(regex) || [];
    },

    evaluateSequential: (tokens, draws, currentIndex) => {
        if (tokens.length === 0) return 0;

        let result = CustomSim.getOperandValue(tokens[0], draws, currentIndex);

        for (let i = 1; i < tokens.length; i += 2) {
            const operator = tokens[i];
            const nextOperand = tokens[i + 1];
            if (!nextOperand) break;

            const nextValue = CustomSim.getOperandValue(nextOperand, draws, currentIndex);

            switch (operator) {
                case '+': result += nextValue; break;
                case '-': result -= nextValue; break;
                case '*': result *= nextValue; break;
                case '/': result = Math.floor(result / nextValue); break;
                case '%': result = result % nextValue; break;
            }
        }
        return result;
    },

    getOperandValue: (token, draws, currentIndex) => {
        // 1. 숫자 리터럴
        if (/^\d+$/.test(token)) return parseInt(token);

        // 2. N-x[y] 형식 (예: N-1[1] -> i-1회차의 1번째 번호)
        const nMatch = token.match(/N-(\d+)\[(\d+)\]/);
        if (nMatch) {
            const lookback = parseInt(nMatch[1]);
            const ballIdx = parseInt(nMatch[2]) - 1; // 1-based to 0-based
            const targetDraw = draws[currentIndex - lookback];
            return targetDraw ? targetDraw.numbers[ballIdx] || 0 : 0;
        }

        // 3. drawNo.digitSum (현재 타겟 회차 번호의 자릿수 합)
        if (token === 'drawNo.digitSum') {
            const drawNo = draws[currentIndex].drawNo.toString();
            return drawNo.split('').reduce((sum, d) => sum + parseInt(d), 0);
        }

        return 0;
    },

    normalize: (val, maxBall) => {
        if (val === 0) return null;

        // 음수 처리 (역산)
        if (val < 0) {
            val = maxBall + (val % maxBall);
            if (val === 0) return null;
        }

        // 초과 처리 (순환)
        if (val > maxBall) {
            val = ((val - 1) % maxBall) + 1;
        }

        return val;
    },

    getMaxBall: (id) => {
        if (id === 'korea') return 45;
        const lottery = CustomSim.lotteries.find(l => l.id === id);
        if (lottery && lottery.max_number) return lottery.max_number;
        return 45; // Default
    },

    renderResults: () => {
        const tbody = document.getElementById('resultBody');
        tbody.innerHTML = '';

        CustomSim.results.forEach(res => {
            const tr = document.createElement('tr');
            
            // 대상 번호 합집합 렌더링
            const windowHtml = res.windowList.map(n => `<span class="ball-common ${CustomSim.getBallColor(n)}">${n}</span>`).join('');
            
            // 실제 당첨 번호 렌더링
            const actualHtml = res.actualNumbers.map(n => {
                const isMatch = n === res.predicted;
                const highlight = isMatch ? 'ring-4 ring-indigo-500 ring-offset-2' : '';
                return `<span class="ball-common ${CustomSim.getBallColor(n)} ${highlight}">${n}</span>`;
            }).join('');

            const hitCls = res.isHit ? 'hit-high' : 'hit-low';
            const hitIcon = res.isHit ? '★' : '-';

            tr.innerHTML = `
                <td class="px-4 py-4 font-bold text-gray-700">${res.drawNo}</td>
                <td class="px-4 py-4"><div class="flex flex-wrap gap-1">${windowHtml}</div></td>
                <td class="px-4 py-4"><div class="flex flex-wrap gap-1">${actualHtml}</div></td>
                <td class="px-4 py-4 text-center font-black ${hitCls}">${hitIcon}</td>
                <td class="px-4 py-4 text-center"><span class="badge-indigo">${res.isHit ? '100%' : '0%'}</span></td>
            `;
            tbody.appendChild(tr);
        });
    },

    getBallColor: (n) => {
        if (n <= 10) return 'ball-y';
        if (n <= 20) return 'ball-b';
        if (n <= 30) return 'ball-r';
        if (n <= 40) return 'ball-g';
        return 'ball-gr';
    },

    saveFilter: async () => {
        const name = prompt('필터 이름을 입력하세요:');
        if (!name) return;

        const lotteryId = document.getElementById('dbSelect').value;
        const formulaStr = document.getElementById('formulaInput').value.trim();
        const N = parseInt(document.getElementById('windowSlider').value);

        const { error } = await window.supabaseClient
            .from('custom_simulations')
            .insert({
                filter_name: name,
                db_id: lotteryId,
                formula: { str: formulaStr },
                window_n: N,
                last_hit_count: CustomSim.results[0]?.isHit ? 1 : 0,
                last_evaluated_draw: CustomSim.results[0]?.drawNo,
                notes: ''
            });

        if (error) {
            alert('저장 실패: ' + error.message);
        } else {
            alert('성공적으로 저장되었습니다.');
            CustomSim.loadDashboard();
        }
    },

    loadDashboard: async () => {
        const { data, error } = await window.supabaseClient
            .from('custom_simulations')
            .select('*')
            .order('created_at', { ascending: false });

        if (error) return;

        const grid = document.getElementById('dashboardGrid');
        const empty = document.getElementById('emptyDashboard');

        if (!data || data.length === 0) {
            grid.innerHTML = '';
            grid.appendChild(empty);
            return;
        }

        empty.classList.add('hidden');
        grid.innerHTML = data.map(f => {
            const lottery = CustomSim.lotteries.find(l => l.id === f.db_id);
            const displayName = f.db_id === 'korea' ? '대한민국' : (lottery ? `[${lottery.country}] ${lottery.name}` : f.db_id.substring(0,8));
            
            return `
            <div class="card p-6 hover:shadow-lg transition-all border border-gray-100">
                <div class="flex justify-between items-start mb-4">
                    <span class="badge-indigo">${displayName} [N=${f.window_n}]</span>
                    <button onclick="CustomSim.deleteFilter('${f.id}')" class="text-gray-300 hover:text-red-500 transition-colors">
                        <span class="material-symbols-outlined text-sm">delete</span>
                    </button>
                </div>
                <h4 class="font-black text-gray-900 mb-2">${f.filter_name}</h4>
                <div class="bg-gray-50 rounded-lg p-3 mb-4 font-mono text-[11px] text-gray-600 break-all border border-gray-100">
                    ${f.formula.str}
                </div>
                <div class="flex justify-between items-end border-t border-gray-50 pt-4">
                    <div class="text-[10px] text-gray-400 font-bold uppercase">최근 회차 성적</div>
                    <div class="text-sm font-black ${f.last_hit_count > 0 ? 'text-emerald-500' : 'text-gray-300'}">
                        ${f.last_hit_count > 0 ? 'HIT ★' : 'MISS'}
                    </div>
                </div>
            </div>
            `;
        }).join('');
    },

    deleteFilter: async (id) => {
        if (!confirm('정말 삭제하시겠습니까?')) return;
        const { error } = await window.supabaseClient.from('custom_simulations').delete().eq('id', id);
        if (!error) CustomSim.loadDashboard();
    },

    showLoading: (show) => {
        document.getElementById('loadingOverlay').classList.toggle('hidden', !show);
    },

    showGuide: () => {
        alert("수식 가이드:\n- N-1[1]: 이전 회차의 1번째 번호\n- N-2[3]: 2회전 전의 3번째 번호\n- drawNo.digitSum: 현재 회차 번호의 자릿수 합 (예: 1177 -> 1+1+7+7=16)\n- 사칙연산(+, -, *, /) 및 나머지(%) 연산 지원\n- 연산은 입력된 순서대로(좌->우) 진행됩니다.");
    }
};

window.CustomSim = CustomSim;
