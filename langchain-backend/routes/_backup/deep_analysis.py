"""딥러닝 심층 분석 통합 API 라우트.

프론트엔드 ai_deep_learning.html 대시보드에서 사용.
앙상블 예측 + 조합 생성 + LLM 전략 분석을 한 번에 수행한다.
"""

import json
import traceback

import numpy as np
from fastapi import APIRouter, Request
from starlette.responses import Response
from db.supabase_client import fetch_all_draws

router = APIRouter(prefix="/api/deep-analysis", tags=["deep-analysis"])


class NumpyEncoder(json.JSONEncoder):
    """numpy 타입을 Python native 타입으로 변환하는 JSON 인코더."""

    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.bool_):
            return bool(obj)
        return super().default(obj)


def _json_response(data: dict, status_code: int = 200) -> Response:
    """numpy 안전한 JSON 응답을 생성한다."""
    body = json.dumps(data, cls=NumpyEncoder, ensure_ascii=False)
    return Response(
        content=body,
        status_code=status_code,
        media_type="application/json",
    )


@router.post("/run")
async def run_deep_analysis(request: Request):
    """통합 딥러닝 심층 분석 실행.

    1) 앙상블 모델로 45개 번호 확률 예측
    2) Monte Carlo 샘플링으로 최적 조합 생성
    3) LLM에게 전략 분석 요청
    """
    try:
        body = await request.json()
        target_round_input = body.get("target_round")
        n_combinations = body.get("n_combinations", 10)

        draws = fetch_all_draws()
        if not draws:
            return _json_response({"error": "로또 데이터를 불러올 수 없습니다"})

        target_round = target_round_input or (draws[0]["round"] + 1)

        # ── Step 1: 앙상블 예측 ──
        from models.ensemble import LottoEnsemble, CombinationGenerator

        ensemble = LottoEnsemble()
        prediction = ensemble.predict(draws)

        # ── Step 2: 조합 생성 ──
        generator = CombinationGenerator()
        filter_settings = {
            "sum_range": {"min": 100, "max": 180},
            "odd_count": {"min": 2, "max": 4},
            "low_count": {"min": 2, "max": 4},
            "ac_value": {"min": 7, "max": 10},
            "consecutive": {"max": 2},
        }
        combinations = generator.generate(
            prediction,
            filter_settings=filter_settings,
            n_combinations=n_combinations,
        )

        # ── Step 3: 통계 요약 계산 ──
        probs = prediction["probabilities"]
        sorted_nums = sorted(probs.items(), key=lambda x: x[1], reverse=True)

        # 번호별 확률 (1~45)
        number_probs = {str(n): round(float(p), 4) for n, p in probs.items()}

        # 상위/하위 번호
        recommended = [int(n) for n, _ in sorted_nums[:10]]
        excluded = [int(n) for n, _ in sorted_nums[-10:]]
        top_6 = [int(n) for n, _ in sorted_nums[:6]]

        # 모델별 기여도 (가중치)
        weights = prediction["weights_used"]

        # 모델별 Top10
        model_top10 = {}
        for model_name, model_probs in prediction["model_contributions"].items():
            s = sorted(model_probs.items(), key=lambda x: x[1], reverse=True)
            model_top10[model_name] = [
                {"number": int(n), "prob": round(float(p), 4)} for n, p in s[:10]
            ]

        # XGBoost 피처 중요도 (상위 번호)
        xgb_features = {}
        for n, feats in prediction.get("xgb_feature_importance", {}).items():
            xgb_features[str(n)] = feats

        # Markov 추론 근거
        markov_reasons = {}
        for n, reason in prediction.get("markov_reasoning", {}).items():
            if n in recommended[:10]:
                markov_reasons[str(n)] = reason

        # 최근 10회차 요약
        recent_10 = draws[:10]
        recent_summary = []
        for d in recent_10:
            nums = d.get("numbers", [])
            recent_summary.append({
                "round": d["round"],
                "numbers": nums,
                "sum": sum(nums) if nums else 0,
                "odd": sum(1 for n in nums if n % 2 == 1) if nums else 0,
                "low": sum(1 for n in nums if n <= 22) if nums else 0,
            })

        # ── Step 4: LLM 전략 분석 ──
        llm_strategy = await _ask_llm_strategy(
            target_round, recommended, excluded, top_6,
            weights, recent_summary, combinations
        )

        result = {
            "success": True,
            "target_round": target_round,
            "analysis": {
                "number_probabilities": number_probs,
                "recommended": recommended,
                "excluded": excluded,
                "top_6": top_6,
                "model_weights": {k: round(float(v), 4) for k, v in weights.items()},
                "model_top10": model_top10,
                "xgb_feature_importance": xgb_features,
                "markov_reasoning": markov_reasons,
            },
            "combinations": [
                {"rank": c["rank"], "numbers": c["numbers"], "score": float(c["score"])}
                for c in combinations
            ],
            "strategy": llm_strategy,
            "recent_summary": recent_summary,
        }
        return _json_response(result)

    except Exception as e:
        traceback.print_exc()
        return _json_response({"success": False, "error": str(e)}, status_code=200)


async def _ask_llm_strategy(
    target_round, recommended, excluded, top_6,
    weights, recent_summary, combinations
):
    """LLM에게 전략 분석을 요청한다."""
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        from config import GOOGLE_API_KEY, LLM_MODEL

        llm = ChatGoogleGenerativeAI(
            model=LLM_MODEL,
            google_api_key=GOOGLE_API_KEY,
            temperature=0.4,
        )

        recent_text = "\n".join(
            f"  {r['round']}회: {r['numbers']} (합계:{r['sum']}, 홀:{r['odd']}, 저:{r['low']})"
            for r in recent_summary[:5]
        )

        combo_text = "\n".join(
            f"  #{c['rank']}: {c['numbers']} (점수:{c['score']:.4f})"
            for c in combinations[:5]
        )

        prompt = f"""당신은 로또 데이터 분석 전문가 AI입니다.
{target_round}회차 예측을 위한 심층 분석 전략을 수립하세요.

[5중 앙상블 딥러닝 분석 결과]
- 모델 가중치: Transformer {float(weights.get('transformer',0)):.1%}, LSTM {float(weights.get('lstm',0)):.1%}, CNN {float(weights.get('cnn',0)):.1%}, XGBoost {float(weights.get('xgboost',0)):.1%}, Markov {float(weights.get('markov',0)):.1%}
- 추천 상위 10개: {recommended}
- 제외 하위 10개: {excluded}
- Top 6 예측: {top_6}

[최근 5회 당첨 결과]
{recent_text}

[AI 생성 조합 (Top 5)]
{combo_text}

위 데이터를 바탕으로 반드시 아래 JSON 형식으로만 응답하세요. 마크다운 없이 순수 JSON만 반환하세요.

{{
  "confidence": 72,
  "summary": "최근 동향과 모델 분석을 종합한 3~5문장 전략 요약",
  "keywords": ["#키워드1", "#키워드2", "#키워드3", "#키워드4", "#키워드5"],
  "fixed_numbers": [가장 유력한 고정수 2~4개],
  "exclude_numbers": [강력 제외수 3~5개],
  "filters": ["필터조건1", "필터조건2", "필터조건3"],
  "hot_cold_analysis": "핫넘버/콜드넘버 동향 분석 2문장",
  "risk_assessment": "예측 리스크 수준 및 근거 1문장"
}}"""

        result = await llm.ainvoke(prompt)
        content = result.content

        # JSON 추출
        import re
        json_match = re.search(r"\{[\s\S]*\}", content)
        if json_match:
            return json.loads(json_match.group(0))
        else:
            return {
                "confidence": 50,
                "summary": content[:300],
                "keywords": [],
                "fixed_numbers": top_6[:3],
                "exclude_numbers": excluded[:5],
                "filters": [],
                "hot_cold_analysis": "",
                "risk_assessment": "",
            }

    except Exception as e:
        print(f"LLM 전략 분석 실패: {e}")
        return {
            "confidence": 50,
            "summary": f"LLM 분석 실패 ({str(e)[:100]}). 모델 결과만 표시합니다.",
            "keywords": ["#모델분석전용"],
            "fixed_numbers": top_6[:3],
            "exclude_numbers": excluded[:5],
            "filters": ["합계 100~180 권장", "홀짝 3:3 또는 4:2 권장"],
            "hot_cold_analysis": "LLM 미사용",
            "risk_assessment": "모델 단독 분석",
        }
