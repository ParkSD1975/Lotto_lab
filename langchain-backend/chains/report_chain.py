"""주간 보고서 생성 체인 v2 - 딥러닝 예측 + 모델 성능 통합.

v1 대비 변경사항:
- ai_predictions에서 딥러닝 예측 4가지 타입 로드
- model_performance_log에서 최근 모델 성능 로드
- 커스텀 룰 Hot 상태 반영
- 앙상블 가중치 + feature importance + Markov reasoning 통합
"""

import json
from langchain_google_genai import ChatGoogleGenerativeAI

from config import GOOGLE_API_KEY, LLM_MODEL
from db.supabase_client import get_client, fetch_recent_draws
from rag.retriever import retrieve_as_text
from rag.data_loader import _compute_stats


def get_llm() -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=LLM_MODEL,
        google_api_key=GOOGLE_API_KEY,
        temperature=0.7,
    )


async def generate_report(target_round: int = None) -> dict:
    """주간 종합 분석 보고서를 생성한다 (v2: 딥러닝 통합)."""
    llm = get_llm()
    client = get_client()

    # ── 최근 10회차 데이터 ──
    draws = fetch_recent_draws(10)
    if not draws:
        return {"error": "데이터 없음"}

    if target_round is None:
        target_round = draws[0].get("round", 0) + 1

    draws_summary = []
    for d in draws:
        numbers = d.get("numbers", [])
        if isinstance(numbers, str):
            numbers = [int(x) for x in numbers.strip("{}[]").split(",")]
        stats = _compute_stats(numbers)
        draws_summary.append(
            f"{d['round']}회: {','.join(str(n) for n in sorted(numbers))} "
            f"| 총합 {stats['total_sum']} | 홀짝 {stats['odd_count']}:{stats['even_count']} "
            f"| AC {stats['ac_value']} | 소수 {stats['prime_count']}개 "
            f"| 연번 {stats['consecutive_pairs']}쌍 | 끝수합 {stats['tail_sum']}"
        )
    draws_text = "\n".join(draws_summary)

    # ── 딥러닝 예측 결과 로드 ──
    prediction_text = ""
    try:
        predictions = (
            client.table("ai_predictions")
            .select("*")
            .eq("target_round", target_round)
            .execute()
        )

        for pred in predictions.data or []:
            ptype = pred["prediction_type"]
            nums = pred.get("predicted_numbers", [])
            conf = pred.get("confidence_score", 0)
            prediction_text += f"[{ptype}] 번호: {nums}, 신뢰도: {conf:.1%}\n"

            detail = pred.get("analysis_detail", {})
            if isinstance(detail, dict):
                weights = detail.get("weights")
                if weights:
                    prediction_text += f"  앙상블 가중치: {weights}\n"
    except Exception as e:
        prediction_text = f"(딥러닝 예측 로드 실패: {e})\n"

    # ── 모델 성능 이력 로드 ──
    performance_text = ""
    try:
        perf = (
            client.table("model_performance_log")
            .select("model_name, hit_count, prediction_type, round")
            .order("round", desc=True)
            .limit(60)
            .execute()
        )

        if perf.data:
            from collections import defaultdict

            model_hits = defaultdict(list)
            for entry in perf.data:
                m = entry["model_name"]
                model_hits[m].append(entry["hit_count"])

            for m, hits in model_hits.items():
                avg = sum(hits) / len(hits) if hits else 0
                performance_text += f"  {m}: 최근 {len(hits)}회 평균 적중 {avg:.1f}개\n"
    except Exception:
        pass

    # ── 커스텀 룰 Hot 상태 ──
    hot_rules_text = ""
    try:
        rules = (
            client.table("ai_custom_analyses")
            .select("name, ai_evaluation")
            .eq("is_ai_enabled", True)
            .execute()
        )

        for rule in rules.data or []:
            eval_data = rule.get("ai_evaluation", {})
            if isinstance(eval_data, dict) and eval_data.get("is_hot"):
                hr = eval_data.get("hit_rate", 0)
                hot_rules_text += f"  [HOT] {rule['name']}: hit rate {hr:.1%}\n"
    except Exception:
        pass

    # ── RAG 참조 ──
    rag_context = retrieve_as_text(f"주간 종합 분석 {target_round}회차", k=15)

    # ── 프롬프트 ──
    prompt = f"""
# Role: 로또 주간 분석 리포터 (AI 딥러닝 데이터 통합)
# Task: 제{target_round}회차 주간 종합 분석 보고서를 작성하라.

## 최근 10회차 데이터
{draws_text}

## 딥러닝 앙상블 예측 결과 ({target_round}회차 대상)
{prediction_text if prediction_text else "(아직 예측이 실행되지 않았습니다)"}

## AI 모델 최근 성능
{performance_text if performance_text else "(성능 데이터 없음)"}

## 적중 중인 커스텀 룰 (Hot)
{hot_rules_text if hot_rules_text else "(없음)"}

## 과거 유사 패턴 (RAG)
{rag_context}

## 보고서 작성 규칙
- 딥러닝 예측 결과가 있으면 반드시 보고서에 통합하여 분석하라
- 각 모델(LSTM, XGBoost, Markov)의 기여도를 언급하라
- 핵심 숫자는 {{{{good:숫자}}}}, {{{{warn:숫자}}}}, {{{{range:구간}}}} 태그로 강조
- 오직 순수 JSON 포맷으로만 응답하라

## JSON 구조
{{
    "report_title": "제{target_round}회 주간 로또 AI 분석 보고서",
    "summary": "전체 요약: 딥러닝 예측 + 통계 분석 통합 (3-4문장)",
    "sections": [
        {{ "title": "총합 분석", "content": "최근 총합 추세와 AI 예측 구간" }},
        {{ "title": "홀짝/저고 밸런스", "content": "홀짝비와 저고비 분석 + AI 필터 가이드" }},
        {{ "title": "핫/콜드 번호", "content": "AI 추천수와 통계적 핫번호 교차 분석" }},
        {{ "title": "소수/합성수 동향", "content": "소수 출현 추세 + 마르코프 확률" }},
        {{ "title": "연번/이월수 패턴", "content": "연번과 이월 가능성 + AI 모델 견해" }},
        {{ "title": "AI 딥러닝 종합 전략", "content": "앙상블 모델 추천 번호 + 조합 전략" }}
    ],
    "ai_prediction_summary": {{
        "recommended": [1,2,3,4,5],
        "excluded": [6,7,8,9,10],
        "model_weights": {{ "lstm": 0.35, "xgboost": 0.40, "markov": 0.25 }}
    }},
    "recommended_numbers": [1,2,3,4,5,6],
    "excluded_numbers": [7,8,9,10,11]
}}
"""

    result = await llm.ainvoke(prompt)
    return _parse_json_response(result.content)


def _parse_json_response(text: str) -> dict:
    """LLM 응답에서 JSON을 파싱한다."""
    try:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
        return {"error": "보고서 생성 실패", "raw": text}
