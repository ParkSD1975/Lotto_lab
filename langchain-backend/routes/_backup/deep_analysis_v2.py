"""딥러닝 심층 분석 v2 API 라우트.

v1 대비 변경점:
  - 18+ 필터별 통계/추천/근거(evidence) 추가
  - LLM 프롬프트에 필터 통계 포함 (더 정밀한 전략)
  - 회차별 이력 저장/조회 (Supabase deep_analysis_history)
  - 3-tab 프론트엔드 지원 (Dashboard / Deep Analysis / Recommendations)
"""

import json
import time
import traceback
from datetime import datetime, timezone

import numpy as np
from fastapi import APIRouter, Request
from starlette.responses import Response
from db.supabase_client import fetch_all_draws, get_client

router = APIRouter(prefix="/api/deep-analysis/v2", tags=["deep-analysis-v2"])


# ── numpy-safe JSON 인코더 ──
class NumpyEncoder(json.JSONEncoder):
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
    body = json.dumps(data, cls=NumpyEncoder, ensure_ascii=False)
    return Response(content=body, status_code=status_code, media_type="application/json")


# ═══════════════════════════════════════════
# 1. 통합 분석 실행
# ═══════════════════════════════════════════
@router.post("/run")
async def run_deep_analysis_v2(request: Request):
    """v2 통합 딥러닝 심층 분석.

    1) 앙상블 모델로 45개 번호 확률 예측
    2) 18+ 필터별 통계/추천/근거 계산
    3) Monte Carlo 샘플링으로 최적 조합 생성
    4) LLM에게 필터 통계 포함 전략 분석 요청
    """
    start_time = time.time()

    try:
        body = await request.json()
        target_round_input = body.get("target_round")
        n_combinations = body.get("n_combinations", 10)

        draws = fetch_all_draws()
        if not draws:
            return _json_response({"success": False, "error": "로또 데이터를 불러올 수 없습니다"})

        target_round = target_round_input or (draws[0]["round"] + 1)

        # ── Step 1: 앙상블 예측 ──
        from models.ensemble import LottoEnsemble, CombinationGenerator

        ensemble = LottoEnsemble()
        prediction = ensemble.predict(draws)

        # ── Step 2: 필터별 통계 계산 ──
        from services.filter_stats import FilterStatsComputer

        computer = FilterStatsComputer(draws, recent_n=50)
        filter_stats = computer.compute_all()

        # ── Step 3: 조합 생성 ──
        filter_settings = {
            "sum_range": {"min": 100, "max": 180},
            "odd_count": {"min": 2, "max": 4},
            "low_count": {"min": 2, "max": 4},
            "ac_value": {"min": 7, "max": 10},
            "consecutive": {"max": 2},
        }
        combinations = CombinationGenerator.generate(
            prediction,
            filter_settings=filter_settings,
            n_combinations=n_combinations,
        )

        # ── Step 4: 통계 요약 ──
        probs = prediction["probabilities"]
        sorted_nums = sorted(probs.items(), key=lambda x: x[1], reverse=True)

        number_probs = {str(n): round(float(p), 4) for n, p in probs.items()}
        recommended = [int(n) for n, _ in sorted_nums[:10]]
        excluded = [int(n) for n, _ in sorted_nums[-10:]]
        top_6 = [int(n) for n, _ in sorted_nums[:6]]

        weights = prediction["weights_used"]

        model_top10 = {}
        for model_name, model_probs in prediction["model_contributions"].items():
            s = sorted(model_probs.items(), key=lambda x: x[1], reverse=True)
            model_top10[model_name] = [
                {"number": int(n), "prob": round(float(p), 4)} for n, p in s[:10]
            ]

        xgb_features = {}
        for n, feats in prediction.get("xgb_feature_importance", {}).items():
            xgb_features[str(n)] = feats

        markov_reasons = {}
        for n, reason in prediction.get("markov_reasoning", {}).items():
            if n in recommended[:10]:
                markov_reasons[str(n)] = reason

        # 최근 5회차 요약 (LLM 프롬프트용)
        recent_5 = draws[:5]
        recent_summary = []
        for d in recent_5:
            nums = d.get("numbers", [])
            recent_summary.append({
                "round": d["round"],
                "numbers": nums,
                "sum": sum(nums) if nums else 0,
                "odd": sum(1 for n in nums if n % 2 == 1) if nums else 0,
                "low": sum(1 for n in nums if n <= 22) if nums else 0,
            })

        # ── Step 5: LLM 전략 분석 (필터 통계 포함) ──
        llm_strategy = await _ask_llm_strategy_v2(
            target_round, recommended, excluded, top_6,
            weights, recent_summary, combinations, filter_stats
        )

        elapsed = round(time.time() - start_time, 2)

        result = {
            "success": True,
            "version": "v2",
            "target_round": target_round,
            "elapsed_seconds": elapsed,
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
            "filter_stats": filter_stats,
            "combinations": [
                {"rank": c["rank"], "numbers": c["numbers"], "score": float(c["score"])}
                for c in combinations
            ],
            "strategy": llm_strategy,
            "recent_summary": recent_summary,
        }

        # ── Step 6: 이력 저장 (비동기, 실패해도 무시) ──
        try:
            _save_history(target_round, result)
        except Exception as e:
            print(f"이력 저장 실패 (무시): {e}")

        return _json_response(result)

    except Exception as e:
        traceback.print_exc()
        return _json_response({"success": False, "error": str(e)}, status_code=200)


# ═══════════════════════════════════════════
# 2. 이력 조회
# ═══════════════════════════════════════════
@router.get("/history")
async def get_history(request: Request):
    """저장된 분석 이력 목록 조회."""
    try:
        client = get_client()
        result = (
            client.table("deep_analysis_history")
            .select("id, target_round, created_at, confidence, summary")
            .order("created_at", desc=True)
            .limit(30)
            .execute()
        )
        return _json_response({"success": True, "history": result.data or []})
    except Exception as e:
        # 테이블이 없을 수 있음 - 빈 목록 반환
        print(f"이력 조회 실패: {e}")
        return _json_response({"success": True, "history": []})


@router.get("/history/{history_id}")
async def get_history_detail(history_id: int):
    """특정 이력의 상세 데이터 조회."""
    try:
        client = get_client()
        result = (
            client.table("deep_analysis_history")
            .select("*")
            .eq("id", history_id)
            .single()
            .execute()
        )
        if result.data:
            return _json_response({"success": True, "data": result.data})
        return _json_response({"success": False, "error": "이력을 찾을 수 없습니다"})
    except Exception as e:
        return _json_response({"success": False, "error": str(e)})


# ═══════════════════════════════════════════
# 이력 저장
# ═══════════════════════════════════════════
def _save_history(target_round: int, result: dict):
    """분석 결과를 Supabase deep_analysis_history 테이블에 저장."""
    try:
        client = get_client()
        strategy = result.get("strategy", {})

        row = {
            "target_round": target_round,
            "confidence": strategy.get("confidence", 0),
            "summary": (strategy.get("summary", ""))[:500],
            "analysis_data": json.dumps(result, cls=NumpyEncoder, ensure_ascii=False),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        client.table("deep_analysis_history").insert(row).execute()
    except Exception as e:
        print(f"이력 저장 DB 오류: {e}")


# ═══════════════════════════════════════════
# LLM 전략 분석 v2 (필터 통계 포함)
# ═══════════════════════════════════════════
async def _ask_llm_strategy_v2(
    target_round, recommended, excluded, top_6,
    weights, recent_summary, combinations, filter_stats
):
    """LLM에게 필터 통계를 포함한 전략 분석을 요청한다."""
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

        # 필터 통계 요약 생성
        filter_summary = _build_filter_summary(filter_stats)

        prompt = f"""당신은 로또 데이터 분석 전문가 AI입니다.
{target_round}회차 예측을 위한 심층 전략을 수립하세요.

[5중 앙상블 딥러닝 분석 결과]
- 모델 가중치: Transformer {float(weights.get('transformer',0)):.1%}, LSTM {float(weights.get('lstm',0)):.1%}, CNN {float(weights.get('cnn',0)):.1%}, XGBoost {float(weights.get('xgboost',0)):.1%}, Markov {float(weights.get('markov',0)):.1%}
- 추천 상위 10개: {recommended}
- 제외 하위 10개: {excluded}
- Top 6 예측: {top_6}

[최근 5회 당첨 결과]
{recent_text}

[AI 생성 조합 (Top 5)]
{combo_text}

[필터별 통계 분석 결과]
{filter_summary}

위 데이터를 바탕으로 반드시 아래 JSON 형식으로만 응답하세요. 마크다운 없이 순수 JSON만 반환하세요.
모든 추천에는 반드시 구체적인 근거(evidence)를 포함하세요.

{{
  "confidence": 72,
  "summary": "최근 동향과 모델 분석을 종합한 5~8문장의 심층 전략 요약. 필터 통계 근거를 반드시 포함하세요.",
  "keywords": ["#키워드1", "#키워드2", "#키워드3", "#키워드4", "#키워드5"],
  "fixed_numbers": {{
    "numbers": [가장 유력한 고정수 2~4개],
    "evidence": "이 번호를 고정수로 추천하는 구체적 근거"
  }},
  "exclude_numbers": {{
    "numbers": [강력 제외수 3~5개],
    "evidence": "이 번호를 제외하는 구체적 근거"
  }},
  "filter_recommendations": [
    {{"filter": "총합", "min": 100, "max": 180, "evidence": "근거"}},
    {{"filter": "끝수합", "min": 15, "max": 35, "evidence": "근거"}},
    {{"filter": "AC값", "min": 7, "max": 10, "evidence": "근거"}},
    {{"filter": "홀짝", "pattern": "3:3", "evidence": "근거"}},
    {{"filter": "저고", "pattern": "3:3", "evidence": "근거"}},
    {{"filter": "연속번호", "max": 1, "evidence": "근거"}},
    {{"filter": "이월수", "min": 0, "max": 2, "evidence": "근거"}},
    {{"filter": "소수", "min": 1, "max": 3, "evidence": "근거"}}
  ],
  "hot_cold_analysis": "핫넘버/콜드넘버 동향 분석 3~4문장 (구체적인 번호와 출현 빈도 포함)",
  "risk_assessment": "예측 리스크 수준 및 근거 2~3문장",
  "overall_strategy": "이번 회차의 전반적인 전략 2~3문장"
}}"""

        result = await llm.ainvoke(prompt)
        content = result.content

        import re
        json_match = re.search(r"\{[\s\S]*\}", content)
        if json_match:
            parsed = json.loads(json_match.group(0))
            # 구조 호환성 보장
            if "fixed_numbers" in parsed and isinstance(parsed["fixed_numbers"], dict):
                pass  # v2 구조 (numbers + evidence)
            elif "fixed_numbers" in parsed and isinstance(parsed["fixed_numbers"], list):
                parsed["fixed_numbers"] = {
                    "numbers": parsed["fixed_numbers"],
                    "evidence": "LLM 분석 기반 추천"
                }
            if "exclude_numbers" in parsed and isinstance(parsed["exclude_numbers"], dict):
                pass
            elif "exclude_numbers" in parsed and isinstance(parsed["exclude_numbers"], list):
                parsed["exclude_numbers"] = {
                    "numbers": parsed["exclude_numbers"],
                    "evidence": "LLM 분석 기반 제외"
                }
            return parsed
        else:
            return _fallback_strategy(content, top_6, excluded)

    except Exception as e:
        print(f"LLM 전략 분석 실패: {e}")
        return _fallback_strategy(str(e), top_6, excluded)


def _build_filter_summary(filter_stats: list) -> str:
    """필터 통계를 LLM 프롬프트용 요약 문자열로 변환."""
    lines = []
    for fs in filter_stats:
        name = fs.get("name", fs.get("key", ""))
        if fs.get("type") == "range":
            stats = fs.get("stats", {})
            rec = fs.get("recommendation", {})
            all_s = stats.get("all", {})
            rec_s = stats.get("recent", {})
            lines.append(
                f"- {name}: 역대평균={all_s.get('mean', '-')}, "
                f"최근50회평균={rec_s.get('mean', '-')}, "
                f"추천범위={rec.get('min', '-')}~{rec.get('max', '-')}"
            )
        elif fs.get("type") == "pattern":
            patterns = fs.get("patterns", [])[:3]
            pat_text = ", ".join(f"{p['pattern']}({p['all_pct']}%)" for p in patterns)
            lines.append(f"- {name}: 상위패턴={pat_text}")

    return "\n".join(lines)


def _fallback_strategy(error_msg: str, top_6: list, excluded: list) -> dict:
    """LLM 실패 시 폴백 전략."""
    return {
        "confidence": 50,
        "summary": f"LLM 분석 실패 ({str(error_msg)[:100]}). 모델 결과와 통계 기반으로 표시합니다.",
        "keywords": ["#모델분석전용", "#통계기반"],
        "fixed_numbers": {
            "numbers": top_6[:3],
            "evidence": "앙상블 모델 상위 확률 기반 (LLM 미사용)"
        },
        "exclude_numbers": {
            "numbers": excluded[:5],
            "evidence": "앙상블 모델 하위 확률 기반 (LLM 미사용)"
        },
        "filter_recommendations": [
            {"filter": "총합", "min": 100, "max": 180, "evidence": "통계적 1표준편차 범위"},
            {"filter": "AC값", "min": 7, "max": 10, "evidence": "역대 평균 기반"},
        ],
        "hot_cold_analysis": "LLM 미사용 - 통계 데이터를 참조해주세요.",
        "risk_assessment": "모델 단독 분석으로 리스크 평가 불가.",
        "overall_strategy": "모델 예측과 필터 통계를 직접 비교하여 판단해주세요.",
    }
