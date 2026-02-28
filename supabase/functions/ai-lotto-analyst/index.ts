// @ts-ignore
import { serve } from "https://deno.land/std@0.168.0/http/server.ts"
// @ts-ignore
import { createClient } from "https://esm.sh/@supabase/supabase-js@2"
import { computeMetaWeights } from "./modules/metaLearning.ts"
import { buildCoOccurrenceMatrix } from "./modules/cooccurrence.ts"
import { buildGNNContext, applyGNNCorrection, getTopCompatiblePairs, getCompatibility } from "./modules/gnn.ts"
import { runRLWithFallback } from "./modules/rlCombinator.ts"
import { screenCombinations, getPassedCombinations } from "./modules/anomalyDetection.ts"
import type { LottoDraw } from "./types.ts"

// ✅ CORS 헤더
const corsHeaders = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type, x-supabase-client-platform',
}

serve(async (req: Request) => {
    // 1. CORS Preflight (OPTIONS) 요청 처리
    if (req.method === 'OPTIONS') {
        return new Response('ok', { headers: corsHeaders })
    }

    try {
        const body = await req.json().catch(() => ({}));

        // ✅ [신규] type 분기 처리
        const requestType = body.type || 'analyze';

        // @ts-ignore: Deno global is available in Edge Runtime
        const aiApiKey = Deno.env.get("GEMINI_API_KEY");
        if (!aiApiKey) throw new Error('API Key가 설정되지 않았습니다.');

        // Supabase 클라이언트 (Meta-Learning DB 조회용)
        // @ts-ignore
        const supabaseUrl = Deno.env.get("SUPABASE_URL") ?? "";
        // @ts-ignore
        const supabaseKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
        const supabaseClient = createClient(supabaseUrl, supabaseKey);

        const apiUrl = `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=${aiApiKey}`;

        // ========================================
        // ✅ [신규] 커스텀 분석 해석 모드
        // ========================================
        if (requestType === 'custom_interpret') {
            const userPrompt = body.prompt || "";

            const systemPrompt = `당신은 로또 분석 조건 해석 전문가입니다.
사용자의 자연어 입력을 구조화된 JSON 필터 조건으로 변환하세요.

## 사용 가능한 필터 타입
- odd_count: 홀수 개수 (operator: ==, >=, <=, value: 숫자)
- even_count: 짝수 개수 (operator: ==, >=, <=, value: 숫자)
- sum_range: 총합 범위 (min: 숫자, max: 숫자) - 최소 21, 최대 255
- ac_value: AC값 (operator: ==, >=, <=, value: 0~10)
- consecutive: 연번 개수 (operator: ==, >=, <=, value: 숫자)
- low_count: 저번호(1-22) 개수 (operator: ==, >=, <=, value: 숫자)
- high_count: 고번호(23-45) 개수 (operator: ==, >=, <=, value: 숫자)
- prime_count: 소수 개수 (operator: ==, >=, <=, value: 숫자)
- carryover: 이월수 개수 (operator: ==, >=, <=, value: 숫자)
- tail_sum: 끝수합 범위 (min: 숫자, max: 숫자)
- dynamic_formula: 동적 수식 분석 (formula: prev_plus_n, prev_minus_n, carryover, draw_date_end, round_end_digit, value: 숫자)
  * draw_date_end: 추첨일(당첨일) 일자 끝수 기준 (예: 25일 -> 5끝수)
  * round_end_digit: 회차 번호 끝수 기준 (예: 1103회 -> 3끝수)

## 응답 형식 (순수 JSON만, 마크다운 없이)
{
  "filters": [
    { "type": "필터타입", "operator": "연산자", "value": 값 },
    { "type": "sum_range", "min": 최소값, "max": 최대값 }
  ],
  "explanation": "사용자 입력을 이렇게 해석했습니다 (한국어)",
  "confidence": 0.0~1.0 사이 신뢰도
}

## 예시
입력: "홀수 3개 이상, 총합 150 이상"
출력: {
  "filters": [
    { "type": "odd_count", "operator": ">=", "value": 3 },
    { "type": "sum_range", "min": 150, "max": 255 }
  ],
  "explanation": "홀수 3개 이상, 총합 150~255 범위로 설정했습니다.",
  "confidence": 0.95
}`;

            const response = await fetch(apiUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    contents: [{
                        parts: [{
                            text: `${systemPrompt}\n\n[사용자 입력]\n${userPrompt}`
                        }]
                    }]
                })
            });

            const aiData = await response.json();

            if (aiData.error) {
                // @ts-ignore
                throw new Error(`Google AI Error: ${aiData.error.message}`);
            }

            let rawText = aiData?.candidates?.[0]?.content?.parts?.[0]?.text || "";
            rawText = rawText.replace(/```json/g, "").replace(/```/g, "").trim();

            let parsedData;
            try {
                parsedData = JSON.parse(rawText);
            } catch (e) {
                parsedData = {
                    filters: [],
                    explanation: "입력을 해석하지 못했습니다. 다시 시도해주세요.",
                    confidence: 0
                };
            }

            return new Response(JSON.stringify(parsedData), {
                headers: { ...corsHeaders, "Content-Type": "application/json" },
                status: 200
            });
        }

        // ========================================
        // 기존 분석 모드 (analyze) - 데이터 기반 정밀 분석
        // ========================================
        const context = body.context || "데이터가 없습니다.";
        const targetRound: number | null = body.target_round ? Number(body.target_round) : null;

        const systemPrompt = `당신은 감정과 조언이 제거된 '로또 번호 통계 분석 엔진'입니다.
사용자가 제공한 [분석 데이터]를 정밀하게 읽고, 오직 해당 데이터에 포함된 숫자와 통계만을 근거로 답변하세요.

[절대 금지 사항]
- "소액으로", "분산 투자", "고액 투자는 지양", "무리한 투자", "책임", "재미로", "유연한 접근", "시나리오" 등 투자/배팅 조언 문구를 절대 사용하지 마시오.
- "에너지 분석", "에너지가 응축", "에너지 분출" 등 비과학적 표현을 사용하지 마시오.
- "고려해볼 만합니다", "가능성이 있습니다" 등 모호한 서술 금지. 반드시 데이터 수치로 종결하시오.
- "적중률이 100%가 아니므로" 등 당연한 면책 문구를 쓰지 마시오.
- 제공된 데이터에 없는 내용을 지어내지 마시오. 데이터에 없으면 "해당 데이터 없음"으로 표기하시오.

[작성 가이드]
1. trend: 제공된 [핵심 통계]와 [적중 분포]를 직접 인용하며, 현재 GAP/STR 상태와 역대 기록 대비 위치를 수치로 서술.
2. pattern: [최근 30회차 상세 히스토리]에서 실제 적중 패턴을 추출. 연속적중/연속미출현 구간, 특정 번호의 적중 빈도 등 구체적 수치만 명시. 태그 필수: {{good:번호}}, {{warn:번호}}, {{range:구간}}
3. recommendation: [최근 20회 실제 당첨번호]와 [타겟번호]를 교차 분석하여, 어떤 번호가 자주 겹치는지, 최근 추세에서 타겟 번호 중 유력한 번호와 제외 번호를 수치 근거와 함께 제시. 번호 조합이 가능하면 조합 리스트로 출력.

[출력 형식] 순수 JSON만 출력. 마크다운 코드블록 금지.
{
  "trend": "수치 기반 현재 상태 진단 ({{range:}}, {{good:}}, {{warn:}} 태그 사용)",
  "pattern": "히스토리 데이터에서 추출한 구체적 패턴 (태그 사용)",
  "recommendation": "데이터 근거 기반 번호 전략 (태그 사용)"
}`;

        const response = await fetch(apiUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                contents: [{
                    parts: [{
                        text: `${systemPrompt}\n\n[분석 데이터]\n${context}`
                    }]
                }]
            })
        });

        const aiData = await response.json();

        if (aiData.error) {
            // @ts-ignore
            throw new Error(`Google AI Error: ${aiData.error.message}`);
        }

        let rawText = aiData?.candidates?.[0]?.content?.parts?.[0]?.text || "";
        rawText = rawText.replace(/```json/g, "").replace(/```/g, "").trim();

        let parsedData;
        try {
            parsedData = JSON.parse(rawText);
        } catch (e) {
            console.error("JSON Parse Error:", e);
            parsedData = {
                trend: rawText || "분석 결과를 불러오지 못했습니다.",
                pattern: "형식 변환 오류가 발생했습니다.",
                recommendation: "다시 시도해 주세요."
            };
        }

        // ========================================
        // [Phase 3] GNN 궁합 보정
        // Gemini의 number_probabilities에 동반출현 궁합 보정 적용
        // ========================================
        let gnnCtx = null;
        try {
            // lotto_draws 조회 (동반출현 행렬 계산용)
            const { data: drawsForGNN } = await supabaseClient
                .from('lotto_draws')
                .select('round, numbers')
                .order('round', { ascending: false })
                .limit(1300);

            if (drawsForGNN && drawsForGNN.length > 0) {
                const lottoDraws: LottoDraw[] = drawsForGNN.map((d: any) => ({
                    round: d.round,
                    numbers: d.numbers,
                }));
                const coMatrix = buildCoOccurrenceMatrix(lottoDraws);
                gnnCtx = buildGNNContext(coMatrix);

                // number_probabilities에 GNN 보정 적용
                if (parsedData?.analysis?.number_probabilities) {
                    parsedData.analysis.number_probabilities = applyGNNCorrection(
                        gnnCtx,
                        parsedData.analysis.number_probabilities
                    );
                }

                // pipeline에 상위 궁합 쌍 추가
                const topPairs = getTopCompatiblePairs(gnnCtx, 10);
                parsedData.pipeline = {
                    ...(parsedData.pipeline || {}),
                    topCompatiblePairs: topPairs,
                };
            }
        } catch (gnnErr) {
            console.error("[Phase3] GNN 보정 실패, 원본 확률 유지:", gnnErr);
        }

        // ========================================
        // [Phase 2] Meta-Learning 동적 가중치 주입
        // Gemini가 반환한 analysis.model_weights를
        // 실제 성적 기반 동적 가중치로 덮어씀
        // ========================================
        try {
            const { weights, reason } = await computeMetaWeights(supabaseClient);

            // analysis 필드가 있을 때만 model_weights 교체 (기존 응답 구조 보호)
            if (parsedData && typeof parsedData === 'object' && parsedData.analysis) {
                parsedData.analysis.model_weights = weights;
            }

            // pipeline 필드 추가 (Phase 6에서 프론트가 활용)
            parsedData.pipeline = {
                ...(parsedData.pipeline || {}),
                modelWeights: weights,
                weightReasons: reason,
            };
        } catch (metaErr) {
            console.error("[Phase2] Meta-Learning 실패, 기존 가중치 유지:", metaErr);
        }

        // ========================================
        // [Phase 3.5] 전문가 메모 파싱 & 저장
        // user_checkpoints 테이블에서 해당 회차 메모를 읽어
        // Gemini로 구조화된 규칙(excluded/boost/fixed)으로 변환
        // ========================================
        let memoRules: {
            summary?: string;
            excluded_numbers?: number[];
            boost_ranges?: Array<{ start: number; end: number }>;
            fixed_numbers?: number[];
        } | null = null;
        let rawMemoText: string | null = null;

        if (targetRound) {
            try {
                const { data: memoRows } = await supabaseClient
                    .from('user_checkpoints')
                    .select('memo')
                    .eq('round', targetRound)
                    .order('created_at', { ascending: true });

                if (memoRows && memoRows.length > 0) {
                    const memoTexts = memoRows.map((r: any) => r.memo).filter(Boolean);
                    rawMemoText = memoTexts.join('\n\n');

                    const memoCount = memoTexts.length;
                    console.log(`[Phase3.5] 전문가 메모 ${memoCount}개 감지 및 병합 완료`);

                    const memoParsedPrompt = `당신은 로또 전문가의 분석 메모(들)를 구조화된 JSON 규칙으로 변환하는 전문가입니다.
여러 개의 메모가 입력될 수 있으니, 모든 메모의 내용을 종합하여 하나의 구조화된 규칙으로 변환하세요.
아래 메모를 분석하여 다음 JSON 형식으로만 응답하세요. 마크다운 없이 순수 JSON만 반환하세요.

{
  "summary": "모든 메모를 종합한 요약 (한 문장)",
  "excluded_numbers": [제외할 번호 리스트 (없으면 빈 배열)],
  "boost_ranges": [{"start": 시작번호, "end": 끝번호} (확률을 높일 구간, 없으면 빈 배열)],
  "fixed_numbers": [고정 추천 번호 리스트 (없으면 빈 배열)]
}

[메모 리스트]
${rawMemoText}`;

                    const memoResponse = await fetch(apiUrl, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ contents: [{ parts: [{ text: memoParsedPrompt }] }] })
                    });
                    const memoAiData = await memoResponse.json();
                    let memoJsonText = memoAiData?.candidates?.[0]?.content?.parts?.[0]?.text || "";
                    memoJsonText = memoJsonText.replace(/```json/g, "").replace(/```/g, "").trim();

                    try {
                        memoRules = JSON.parse(memoJsonText);
                        console.log("[Phase3.5] 전문가 메모 파싱 성공:", memoRules?.summary);
                    } catch (e) {
                        console.error("[Phase3.5] 메모 JSON 파싱 실패:", e);
                    }

                    // pipeline에 메모 정보 추가
                    parsedData.pipeline = {
                        ...(parsedData.pipeline || {}),
                        expertMemo: rawMemoText,
                        expertMemoRules: memoRules,
                    };
                }
            } catch (memoErr) {
                console.error("[Phase3.5] 전문가 메모 조회/적용 실패:", memoErr);
            }
        }

        // ========================================
        // [Phase 4] RL 조합 생성
        // GNN 보정된 번호 점수 + 궁합 + 필터로
        // 최적 조합 10게임을 시뮬레이션하여
        // Gemini 조합을 덮어씀
        // ========================================
        try {
            // number_probabilities 없으면 역대 출현 빈도로 대체
            if (!parsedData?.analysis?.number_probabilities) {
                const { data: drawsForFreq } = await supabaseClient
                    .from('lotto_draws')
                    .select('numbers')
                    .order('round', { ascending: false })
                    .limit(1300);

                if (drawsForFreq && drawsForFreq.length > 0) {
                    const freq: Record<number, number> = {};
                    for (let i = 1; i <= 45; i++) freq[i] = 0;
                    drawsForFreq.forEach((d: any) => {
                        (d.numbers || []).forEach((n: number) => { freq[n] = (freq[n] || 0) + 1; });
                    });
                    const total = drawsForFreq.length * 6;
                    const freqProbs: Record<string, number> = {};
                    for (let i = 1; i <= 45; i++) {
                        freqProbs[String(i)] = (freq[i] || 0) / total;
                    }
                    if (!parsedData.analysis) parsedData.analysis = {};
                    parsedData.analysis.number_probabilities = freqProbs;
                }
            }

            const numberProbs = parsedData?.analysis?.number_probabilities;
            if (numberProbs && gnnCtx) {
                // 번호별 점수 (1~45)
                const numberScores: Record<number, number> = {};
                for (const [k, v] of Object.entries(numberProbs)) {
                    numberScores[parseInt(k)] = Number(v);
                }

                // ▶ 전문가 메모 규칙 적용
                if (memoRules) {
                    // 1. 제외 번호: 확률 0으로
                    (memoRules.excluded_numbers || []).forEach((n: number) => {
                        if (numberScores[n] !== undefined) numberScores[n] = 0;
                    });
                    // 2. 부스트 범위: 1.5배
                    (memoRules.boost_ranges || []).forEach((range: { start: number; end: number }) => {
                        for (let n = range.start; n <= range.end; n++) {
                            if (numberScores[n] !== undefined) numberScores[n] *= 1.5;
                        }
                    });
                    // 3. 고정 번호: 최대값의 2배 (강제 우선)
                    const maxScore = Math.max(...Object.values(numberScores).filter(v => v > 0));
                    (memoRules.fixed_numbers || []).forEach((n: number) => {
                        if (numberScores[n] !== undefined) numberScores[n] = maxScore * 2;
                    });
                    console.log("[Phase3.5] 전문가 메모 규칙 numberScores 적용 완료");
                }

                // 필터: Gemini 전략 권장값에서 추출 (없으면 기본 범위)
                const filterRecs = parsedData?.strategy?.filter_recommendations ?? [];
                const sumRec = filterRecs.find((f: any) => f.filter === '총합');
                const acRec = filterRecs.find((f: any) => f.filter === 'AC값');

                const rlFilters = {
                    sumRange: sumRec ? [sumRec.min ?? 100, sumRec.max ?? 200] as [number, number] : [80, 220] as [number, number],
                    acRange: acRec ? [acRec.min ?? 6, acRec.max ?? 10] as [number, number] : undefined,
                    consecutiveMax: 2,
                };

                const ctx = gnnCtx;
                const rlResults = runRLWithFallback({
                    numberScores,
                    compatibility: (a: number, b: number) => getCompatibility(ctx, a, b),
                    filters: rlFilters,
                    numGames: 10,
                });

                if (rlResults.length > 0) {
                    // ========================================
                    // [Phase 5] Anomaly Detection 게이트
                    // 이상 조합 폐기 → 부족분 재생성 (최대 2회)
                    // ========================================
                    let finalCombos = rlResults;
                    for (let retry = 0; retry < 2; retry++) {
                        const screened = screenCombinations(finalCombos);
                        const passed = getPassedCombinations(screened);
                        if (passed.length >= 10) {
                            finalCombos = passed;
                            break;
                        }
                        // 부족분 재생성
                        const extra = runRLWithFallback({
                            numberScores,
                            compatibility: (a: number, b: number) => getCompatibility(ctx, a, b),
                            filters: rlFilters,
                            numGames: 10 - passed.length,
                        });
                        finalCombos = [
                            ...passed,
                            ...extra.map((r, i) => ({ ...r, rank: passed.length + i + 1 })),
                        ];
                    }

                    // 최종 통과 조합 저장
                    const anomalyScreened = screenCombinations(finalCombos);
                    parsedData.combinations = getPassedCombinations(anomalyScreened);
                    parsedData.pipeline = {
                        ...(parsedData.pipeline || {}),
                        rlGenerated: true,
                        anomalyResults: anomalyScreened.map((s) => ({
                            combo: s.numbers,
                            passed: s.passed,
                            reason: s.reason,
                        })),
                    };
                }
            }
        } catch (rlErr) {
            console.error("[Phase4] RL 생성 실패, Gemini 조합 유지:", rlErr);
        }

        // ========================================
        // [Phase 6] LLM 자연어 리포트 생성 (RL 완료 후)
        // ========================================
        try {
            const pipelineSnapshot = parsedData.pipeline || {};
            const mw = pipelineSnapshot.modelWeights || {};
            const topModel = Object.entries(mw).sort((a: any, b: any) => b[1] - a[1])[0];
            const topPairs = (pipelineSnapshot.topCompatiblePairs || []).slice(0, 3)
                .map((p: any) => `${p[0]}-${p[1]}(${(p[2] * 100).toFixed(0)}%)`)
                .join(', ');

            const reportPrompt = `당신은 로또 AI 분석 결과를 한국어로 요약하는 리포터입니다.
아래 파이프라인 데이터를 바탕으로 2~3문단의 자연어 분석 리포트를 작성하세요.
투자/배팅 조언이나 면책 문구 없이 데이터 중심으로 서술하세요.
순수 텍스트만 반환하고, JSON이나 마크다운 없이 작성하세요.

[파이프라인 데이터]
- 최고 성능 모델: ${topModel ? topModel[0].toUpperCase() + ' (' + (Number(topModel[1]) * 100).toFixed(1) + '%)' : '균등'}
- 가중치 산출 근거: ${pipelineSnapshot.weightReasons || '데이터 없음'}
- 상위 궁합 쌍: ${topPairs || '데이터 없음'}
- RL 생성 여부: ${pipelineSnapshot.rlGenerated ? '예 (7,000회 Monte Carlo 시뮬레이션 완료)' : '아니오'}
- 생성 조합 수: ${(parsedData.combinations || []).length}게임
- 전략 요약: ${parsedData?.strategy?.summary || '없음'}
- 전문가 메모: ${rawMemoText ? `"${rawMemoText}" → ${memoRules?.summary || '규칙 적용됨'}` : '없음 (메모 미등록)'}`;

            const reportResponse = await fetch(apiUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ contents: [{ parts: [{ text: reportPrompt }] }] })
            });
            const reportData = await reportResponse.json();
            const aiReport = reportData?.candidates?.[0]?.content?.parts?.[0]?.text?.trim() || '';

            if (aiReport) {
                parsedData.pipeline = { ...(parsedData.pipeline || {}), aiReport };
            }
        } catch (reportErr) {
            console.error("[Phase6] LLM 리포트 생성 실패:", reportErr);
        }

        return new Response(JSON.stringify(parsedData), {
            headers: { ...corsHeaders, "Content-Type": "application/json" },
            status: 200
        });

    } catch (error: any) {
        return new Response(JSON.stringify({
            trend: "서버 오류 발생",
            pattern: error.message || "알 수 없는 오류",
            recommendation: "잠시 후 다시 시도해주세요."
        }), {
            headers: { ...corsHeaders, "Content-Type": "application/json" },
            status: 200
        });
    }
})
