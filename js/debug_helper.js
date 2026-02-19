
let supabase = null;
let allDraws = [];
let drawsMap = new Map();
let isRunning = false;
let startTime = null;
let stats = { processed: 0, inserted: 0 };

// 로그 함수
function log(message, type = 'info') {
    const container = document.getElementById('logContainer');
    const entry = document.createElement('div');
    entry.className = `log-entry ${type}`;
    entry.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
    container.appendChild(entry);
    container.scrollTop = container.scrollHeight;
}

// 진행률 업데이트
function updateProgress(current, total, text) {
    const pct = Math.round((current / total) * 100);
    document.getElementById('progressFill').style.width = pct + '%';
    document.getElementById('progressText').textContent = text || `${current}/${total} (${pct}%)`;
}

// 통계 업데이트
function updateStats() {
    const elapsed = (Date.now() - startTime) / 1000;
    document.getElementById('statProcessed').textContent = stats.processed;
    document.getElementById('statInserted').textContent = stats.inserted.toLocaleString();
    document.getElementById('statTime').textContent = elapsed.toFixed(1) + 's';
    document.getElementById('statSpeed').textContent = Math.round(stats.inserted / elapsed);
}

// 연결 테스트
async function testConnection() {
    const url = document.getElementById('supabaseUrl').value.trim();
    const key = document.getElementById('supabaseKey').value.trim();

    if (!url || !key) {
        log('URL과 Key를 입력해주세요.', 'error');
        return;
    }

    try {
        supabase = window.supabase.createClient(url, key);
        const { data, error } = await supabase.from('lotto_draws').select('round').order('round', { ascending: false }).limit(1);

        if (error) throw error;

        const maxRound = data[0]?.round || 0;
        log(`✅ 연결 성공! 최신 회차: ${maxRound}`, 'success');

        // 전체 데이터 로드
        log('📥 전체 추첨 데이터 로드 중...', 'info');
        const { data: draws, error: drawsError } = await supabase
            .from('lotto_draws')
            .select('*')
            .order('round', { ascending: true });

        if (drawsError) throw drawsError;

        allDraws = draws;
        drawsMap = new Map(draws.map(d => [d.round, d]));
        log(`✅ ${draws.length}개 회차 데이터 로드 완료`, 'success');

        // 종료 회차 자동 설정
        if (!document.getElementById('endRound').value) {
            document.getElementById('endRound').value = maxRound;
        }

    } catch (err) {
        log(`❌ 연결 실패: ${err.message}`, 'error');
    }
}

// 번호별 통계 생성
async function generateNumberStats() {
    if (!supabase || allDraws.length === 0) {
        log('먼저 연결 테스트를 실행해주세요.', 'error');
        return;
    }

    if (isRunning) return;
    isRunning = true;

    const startRound = parseInt(document.getElementById('startRound').value) || 1;
    const endRound = parseInt(document.getElementById('endRound').value) || Math.max(...allDraws.map(d => d.round));

    document.getElementById('progressContainer').style.display = 'block';
    document.getElementById('statsGrid').style.display = 'grid';
    document.getElementById('btnNumberStats').disabled = true;

    startTime = Date.now();
    stats = { processed: 0, inserted: 0 };

    log(`🚀 번호별 통계 생성 시작 (${startRound} ~ ${endRound}회차)`, 'info');

    try {
        const targetDraws = allDraws.filter(d => d.round >= startRound && d.round <= endRound);
        const totalRounds = targetDraws.length;

        // 배치 단위로 처리
        const BATCH_SIZE = 10; // 10개 회차씩 처리

        for (let i = 0; i < targetDraws.length; i += BATCH_SIZE) {
            const batch = targetDraws.slice(i, i + BATCH_SIZE);
            const rows = [];

            for (const draw of batch) {
                const round = draw.round;
                const winningNumbers = new Set(draw.numbers);

                for (let num = 1; num <= 45; num++) {
                    // Gap 계산
                    let gap = 0;
                    for (let r = round - 1; r >= 1; r--) {
                        const pastDraw = drawsMap.get(r);
                        if (!pastDraw) continue;
                        if (pastDraw.numbers.includes(num)) break;
                        gap++;
                    }

                    // 빈도 계산 (해당 회차 이전 기준)
                    const freq5 = countFrequency(num, round, 5);
                    const freq10 = countFrequency(num, round, 10);
                    const freq15 = countFrequency(num, round, 15);
                    const freq20 = countFrequency(num, round, 20);

                    // Hot/Cold 분류
                    let hotCold = 'warm';
                    if (freq10 >= 3) hotCold = 'hot';
                    else if (freq10 === 0) hotCold = 'cold';

                    // 회귀 일치 횟수
                    let regressionHitCount = 0;
                    for (let dist = 2; dist <= 200; dist++) {
                        const pastDraw = drawsMap.get(round - dist);
                        if (pastDraw && pastDraw.numbers.includes(num)) {
                            regressionHitCount++;
                        }
                    }

                    rows.push({
                        round,
                        number: num,
                        gap,
                        freq_5: freq5,
                        freq_10: freq10,
                        freq_15: freq15,
                        freq_20: freq20,
                        hot_cold: hotCold,
                        regression_hit_count: regressionHitCount,
                        is_winner: winningNumbers.has(num)
                    });
                }
            }

            // Supabase에 upsert
            const { error } = await supabase
                .from('number_round_stats')
                .upsert(rows, { onConflict: 'round,number' });

            if (error) {
                log(`❌ 삽입 오류: ${error.message}`, 'error');
                continue;
            }

            stats.processed += batch.length;
            stats.inserted += rows.length;

            updateProgress(stats.processed, totalRounds,
                `${stats.processed}/${totalRounds} 회차 처리 (${Math.round(stats.processed / totalRounds * 100)}%)`);
            updateStats();

            // UI 업데이트를 위한 짧은 대기
            await new Promise(r => setTimeout(r, 10));
        }

        log(`✅ 번호별 통계 생성 완료! ${stats.inserted.toLocaleString()}행 삽입`, 'success');

    } catch (err) {
        log(`❌ 오류 발생: ${err.message}`, 'error');
    } finally {
        isRunning = false;
        document.getElementById('btnNumberStats').disabled = false;
    }
}

// 빈도 계산 헬퍼
function countFrequency(num, round, range) {
    let count = 0;
    for (let r = round - 1; r >= round - range && r >= 1; r--) {
        const draw = drawsMap.get(r);
        if (draw && draw.numbers.includes(num)) count++;
    }
    return count;
}

// 회귀 분석 데이터 생성
async function generateRegressionData() {
    if (!supabase || allDraws.length === 0) {
        log('먼저 연결 테스트를 실행해주세요.', 'error');
        return;
    }

    if (isRunning) return;
    isRunning = true;

    const startRound = parseInt(document.getElementById('startRound').value) || 1;
    const endRound = parseInt(document.getElementById('endRound').value) || Math.max(...allDraws.map(d => d.round));

    document.getElementById('progressContainer').style.display = 'block';
    document.getElementById('statsGrid').style.display = 'grid';
    document.getElementById('btnRegression').disabled = true;

    startTime = Date.now();
    stats = { processed: 0, inserted: 0 };

    log(`🚀 회귀 분석 데이터 생성 시작 (${startRound} ~ ${endRound}회차)`, 'info');

    try {
        const targetDraws = allDraws.filter(d => d.round >= startRound && d.round <= endRound);
        const totalRounds = targetDraws.length;

        // 5개 회차씩 배치 처리 (메모리 및 네트워크 부하 관리)
        const BATCH_SIZE = 5;

        for (let i = 0; i < totalRounds; i += BATCH_SIZE) {
            const batch = targetDraws.slice(i, i + BATCH_SIZE);
            let batchRows = [];

            for (const draw of batch) {
                const round = draw.round;
                const currentNumbers = new Set(draw.numbers);

                // 1~300 회귀 분석 (기존 200에서 확장)
                for (let dist = 1; dist <= 300; dist++) {
                    const sourceRound = round - dist;
                    if (sourceRound < 1) break;

                    const sourceDraw = drawsMap.get(sourceRound);
                    if (!sourceDraw) continue;

                    const matching = sourceDraw.numbers.filter(n => currentNumbers.has(n));

                    batchRows.push({
                        target_round: round,
                        regression_distance: dist,
                        source_round: sourceRound,
                        source_numbers: sourceDraw.numbers,
                        matching_numbers: matching,
                        match_count: matching.length
                    });
                }
            }

            if (batchRows.length > 0) {
                const { error } = await supabase
                    .from('regression_details')
                    .upsert(batchRows, { onConflict: 'target_round,regression_distance' });

                if (error) throw error;
                stats.inserted += batchRows.length;
            }

            stats.processed += batch.length;

            if (stats.processed % 20 === 0 || stats.processed >= totalRounds) {
                updateProgress(Math.min(stats.processed, totalRounds), totalRounds);
                updateStats();
                await new Promise(r => setTimeout(r, 0));
            }
        }

        log(`✅ 회귀 분석 데이터 생성 완료! ${stats.inserted.toLocaleString()}행 삽입`, 'success');

    } catch (err) {
        console.error("Error generating regression data:", err);
        log(`❌ 오류 발생: ${err.message}`, 'error');
    } finally {
        isRunning = false;
        document.getElementById('btnRegression').disabled = false;
    }
}
