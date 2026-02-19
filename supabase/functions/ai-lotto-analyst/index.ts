// @ts-ignore
import { serve } from "https://deno.land/std@0.168.0/http/server.ts"

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
