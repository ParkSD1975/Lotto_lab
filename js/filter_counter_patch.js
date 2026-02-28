/**
 * filter_counter_patch.js
 * 100% 전수조사 카운팅 + 전체 조합 생성 컨트롤러
 */

(function() {
    let worker = null;
    let isWorkerReady = false;
    let isCounting = false;
    let isGenerating = false;
    let pendingFilters = null;

    function animateValue(obj, start, end, duration) {
        let startTimestamp = null;
        const step = (timestamp) => {
            if (!startTimestamp) startTimestamp = timestamp;
            const progress = Math.min((timestamp - startTimestamp) / duration, 1);
            obj.innerHTML = Math.floor(progress * (end - start) + start).toLocaleString() + '개';
            if (progress < 1) window.requestAnimationFrame(step);
        };
        window.requestAnimationFrame(step);
    }

    function updateCounterUI(count) {
        const counterEl = document.getElementById('neonCounter');
        if (counterEl) {
            const currentVal = parseInt(counterEl.innerText.replace(/[^0-9]/g, '')) || 8145060;
            animateValue(counterEl, currentVal, count, 400);
            counterEl.classList.remove('opacity-50', 'animate-pulse');
        }
    }

    function initWorker() {
        if (!window.Worker) return;
        worker = new Worker('js/filter/combination_worker.js');
        worker.postMessage({ type: 'INIT' });

        worker.onmessage = function(e) {
            const data = e.data;
            if (data.type === 'INIT_DONE') {
                isWorkerReady = true;
                triggerCount();
            } else if (data.type === 'COUNT_RESULT') {
                isCounting = false;
                updateCounterUI(data.count);
                if (pendingFilters) {
                    const filters = pendingFilters;
                    pendingFilters = null;
                    sendToWorker(filters);
                }
            } else if (data.type === 'GENERATE_RESULT') {
                isGenerating = false;

                // 샘플링 없이 필터를 통과한 모든 조합을 그대로 가져옴
                const combos = data.combos.map((arr, idx) => ({
                    rank: idx + 1,
                    numbers: arr,
                    score: 1.0,
                    type: 'filter_exact_match'
                }));

                localStorage.setItem('generated_filter_combos', JSON.stringify({
                    timestamp: new Date().getTime(),
                    total_pool: data.totalValid,
                    combinations: combos
                }));

                const btn = document.getElementById('btnGenerateCombos');
                if (btn) btn.innerHTML = '<span class="material-symbols-outlined text-[18px]">play_arrow</span>조합 생성 완료!';

                window.location.href = 'combination_generator.html';
            }
        };
    }

    function gatherActiveFilters() {
        const filters = { fixed: [], excluded: [], sumRange: null, oddEven: [], lowHigh: [] };

        if (window.FilterDashboard && window.FilterDashboard.state) {
            filters.excluded = window.FilterDashboard.state.excludedNumbers || [];
            filters.fixed = window.FilterDashboard.state.fixedNumbers || [];
        }

        const sumToggle = document.getElementById('toggle-total_sum');
        if (sumToggle && sumToggle.checked) {
            filters.sumRange = {
                min: parseInt(document.getElementById('sum_min')?.value) || 21,
                max: parseInt(document.getElementById('sum_max')?.value) || 255
            };
        }

        const oddToggle = document.getElementById('toggle-odd_even');
        if (oddToggle && oddToggle.checked) {
            document.querySelectorAll('input[type="checkbox"][id^="odd_"]:checked').forEach(cb => {
                const parts = cb.id.split('_');
                if (parts.length === 3) filters.oddEven.push(`${parts[1]}:${parts[2]}`);
            });
        }

        const lowToggle = document.getElementById('toggle-low_high');
        if (lowToggle && lowToggle.checked) {
            document.querySelectorAll('input[type="checkbox"][id^="low_"]:checked').forEach(cb => {
                const parts = cb.id.split('_');
                if (parts.length === 3) filters.lowHigh.push(`${parts[1]}:${parts[2]}`);
            });
        }
        return filters;
    }

    function sendToWorker(filters) {
        if (!isWorkerReady || isGenerating) return;
        if (isCounting) { pendingFilters = filters; return; }

        isCounting = true;
        const counterEl = document.getElementById('neonCounter');
        if (counterEl) counterEl.classList.add('opacity-50', 'animate-pulse');
        worker.postMessage({ type: 'COUNT', filters: filters });
    }

    function triggerCount() { sendToWorker(gatherActiveFilters()); }

    // ★ 조합 생성 버튼 클릭 시 실행
    window.generateFinalCombinations = function() {
        if (!isWorkerReady) {
            alert('조합 엔진이 준비 중입니다. 잠시만 기다려주세요.');
            return;
        }

        const counterEl = document.getElementById('neonCounter');
        const currentCount = parseInt(counterEl?.innerText.replace(/[^0-9]/g, '')) || 0;

        if (currentCount === 0) {
            alert('선택하신 필터 조건에 맞는 조합이 0개입니다. 필터를 조금 완화해주세요.');
            return;
        }

        // 남은 조합이 너무 많을 경우 정밀 필터링 유도
        if (currentCount > 50000) {
            const proceed = confirm(
                `현재 ${currentCount.toLocaleString()}개의 조합이 통과되었습니다.\n` +
                `웹 브라우저 보호를 위해 앞의 5만 개까지만 생성됩니다.\n\n` +
                `필터를 더 켜서 조합 수를 정밀하게 줄이는 것을 권장합니다.\n` +
                `그래도 생성하시겠습니까?`
            );
            if (!proceed) return;
        }

        isGenerating = true;
        const btn = document.getElementById('btnGenerateCombos');
        if (btn) btn.innerHTML = '<span class="material-symbols-outlined animate-spin text-[18px]">sync</span>추출 중...';

        worker.postMessage({ type: 'GENERATE', filters: gatherActiveFilters() });
    };

    document.addEventListener('DOMContentLoaded', () => {
        initWorker();
        document.body.addEventListener('change', (e) => {
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') triggerCount();
        });
        document.body.addEventListener('click', (e) => {
            if (e.target.closest('button:not(#btnGenerateCombos)')) setTimeout(triggerCount, 50);
        });
    });
})();
