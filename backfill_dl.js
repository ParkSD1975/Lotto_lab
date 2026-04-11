const fs = require('fs');
const { createClient } = require('@supabase/supabase-js');

// `eval` config.js to get URL and KEY
const configStr = fs.readFileSync('js/config.js', 'utf8');
const script = 'const window = {}; \n' + configStr + '\nmodule.exports = CONFIG;';
const tmpFile = './temp_config.js';
fs.writeFileSync(tmpFile, script);
const CONFIG = require(tmpFile);
fs.unlinkSync(tmpFile);

const sb = createClient(CONFIG.SUPABASE.URL, CONFIG.SUPABASE.KEY);

async function main() {
    console.log("Fetching deep learning data from round 1211...");
    const { data: dlRows, error: dlErr } = await sb.from('deep_analysis_history')
        .select('*')
        .gte('target_round', 1211)
        .order('target_round', { ascending: true });

    if (dlErr) throw dlErr;
    console.log(`Found ${dlRows.length} DL history rows.`);

    const MODELS = [
        { id: 'ensemble', title: '앙상블 20' },
        { id: 'lstm', title: 'LSTM 20' },
        { id: 'xgboost', title: 'XGB 20' },
        { id: 'cnn', title: 'CNN 20' },
        { id: 'transformer', title: 'TF 20' },
        { id: 'markov', title: 'MARKOV 20' },
        { id: 'autoencoder', title: 'ATC 20' },
        { id: 'gnn', title: 'GNN 20' }
    ];

    for (const [idx, m] of MODELS.entries()) {
        console.log(`Processing Model: ${m.title}`);

        // 1. Create or Find Master Row
        const { data: existMs, error: emErr } = await sb.from('ai_custom_analyses')
            .select('id')
            .eq('title', m.title)
            .is('target_round', null)
            .limit(1);

        let masterId = null;
        if (existMs && existMs.length > 0) {
            masterId = existMs[0].id;
            console.log(`> Found Master Row: ${masterId}`);
        } else {
            console.log(`> Creating Master Row for ${m.title}`);
            const { data: newMs, error: nmErr } = await sb.from('ai_custom_analyses')
                .insert({
                    title: m.title,
                    type: 'manual',
                    description: `딥러닝 ${m.title} 분석 결과 - 상위 20수 직접 입력형 연결`,
                    prompt: 'System DL Automation',
                    target_numbers: [],
                    filter_config: { min: 1, max: 6, enabled: true },
                    rules: { category: '딥러닝 탑20' }
                }).select();
            if (nmErr) { console.error("Master Insert Error:", nmErr); continue; }
            masterId = newMs[0].id;
        }

        // 2. Fetch all target_round items from DL History and Create Snapshots
        for (const dl of dlRows) {
            const tr = parseInt(dl.target_round);
            if (!tr) continue;

            const ad = typeof dl.analysis_data === 'string' ? JSON.parse(dl.analysis_data) : (dl.analysis_data || {});
            const matrixData = ad.analysis?.matrix_data || [];
            
            let top20 = [];
            if (matrixData.length > 0) {
                let topn = matrixData.map(item => {
                    let score = 0;
                    if (m.id === 'ensemble') {
                        // total score based
                        score = item.total || 0;
                    } else {
                        score = (item.models && item.models[m.id]) ? 
                                ((typeof item.models[m.id] === 'object') ? item.models[m.id].score : Number(item.models[m.id])) : -999;
                    }
                    return { num: Number(item.num), score: score };
                }).filter(x => x.num >= 1 && x.num <= 45);

                topn.sort((a,b) => b.score - a.score);
                // [수정] 번호순 재정렬 제거 → 1순위~20순위 순서 그대로 저장
                top20 = topn.slice(0, 20).map(x => x.num);
            }

            if (top20.length === 0 && m.id === 'ensemble') {
                // ensemble fallback은 recommended_numbers 순서 유지 (번호순 정렬 제거)
                top20 = (dl.recommended_numbers || []).slice(0, 20).map(Number);
            }

            if (top20.length > 0) {
                // [수정] 기존 데이터를 먼저 삭제 후 재삽입 → 순위 순서가 반드시 적용되도록 강제
                await sb.from('analysis_history')
                    .delete()
                    .eq('analysis_id', masterId)
                    .eq('target_round', tr);

                const historyRecord = {
                    analysis_id: masterId,
                    target_round: tr,
                    target_numbers: top20,
                    analysis_type: 'custom'
                };
                const { error: ssErr } = await sb.from('analysis_history').insert(historyRecord);
                
                if (ssErr) {
                    console.error(`Insert error for ${m.title} @ ${tr}:`, ssErr);
                }
            }
        }
        console.log(`> Saved snapshots for ${m.title}.`);
    }
    console.log("ALL DONE.");
}
main().catch(console.error);
