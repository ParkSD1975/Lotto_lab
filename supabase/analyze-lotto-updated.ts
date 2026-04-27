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

        const apiUrl = `https://generativelanguage.googleapis.com/v1/models/gemma-4-31b-it:generateContent?key=${aiApiKey}`;

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
        // 기존 분석 모드 (analyze)
        // ========================================
        const context = body.context || "데이터가 없습니다.";

        const systemPrompt = `
      당신은 로또 분석 전문가입니다. 주어진 데이터를 분석하여 JSON 형식으로만 응답하세요.
      
      [응답 형식]
      반드시 아래 JSON 구조를 지켜야 하며, 마크다운이나 추가 설명 없이 순수 JSON만 출력하세요.
      {
        "trend": "지표 흐름 진단 내용 (핵심 숫자는 {{range:숫자}}, 추천은 {{good:내용}}, 경고는 {{warn:내용}} 태그 사용)",
        "pattern": "패턴 및 에너지 분석 내용 (태그 사용)",
        "recommendation": "공략 시나리오 내용 (태그 사용)"
      }
    `;

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
