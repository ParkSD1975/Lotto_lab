"""
[Stage 1-4-D-2-fix-55] 필터별 LLM 자연어 분석 생성기.

매주 1회 weekly_pipeline_v2 실행 시 26개 필터 각각에 대해
- AI 추천 범위 (ensemble_min/max)
- 신뢰구간 (P8 Bootstrap CI 80%)
- 모델 구성 (어떤 모델이 주도, 가중치)
- 사용자 설정과의 비교
를 LLM(Gemma)로 자연 문장 3~4문장 생성하여 weekly_filter_predictions.evidence_text에 저장.

프론트는 SELECT만으로 즉시 표시.
"""

from __future__ import annotations
import asyncio
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# 필터 한국어 라벨
_FILTER_LABELS = {
    "sum": "총합", "tail_sum": "끝수합", "ac": "AC값",
    "odd": "홀짝(홀수 개수)", "high": "저고(고 영역 개수)",
    "prime": "소수", "composite": "합성수",
    "consecutive": "연번", "square": "제곱수", "triangular": "삼각수", "twin": "동형수",
    "mul3": "3배수", "mul4": "4배수", "mul5": "5배수", "mul7": "7배수", "mul8": "8배수",
    "mul34": "3·4배수 교집합", "mul35": "3·5배수 교집합", "mul45": "4·5배수 교집합",
    "non_multiple": "배수외", "neighbor": "이웃수", "carryover": "이월수",
    "hot10": "최근10 핫", "neutral10": "최근10 중립", "cold10": "최근10 콜드",
    "missing": "장기 미출현",
}

# 모델 한국어 표기 (영어 그대로 사용 정책)
_MODEL_KO = {
    "xgboost": "XGBoost", "catboost": "CatBoost", "tabnet": "TabNet",
    "cnn": "CNN", "gnn": "GNN", "markov": "Markov", "autoencoder": "AE",
    "tft": "TFT", "nbeats": "N-BEATS", "mhn": "MHN", "bayesian_nn": "Bayesian",
}


_FILTER_PROMPT = """
당신은 로또 AI 필터 분석가입니다. 필터 '{filter_label}({filter_key})'에 대한 분석을 한국어로만 작성해주세요.

[AI 분석 데이터]
- AI 예측 범위: {ens_min} ~ {ens_max} (6번호 기준 카운트 또는 합계)
- 80% 신뢰구간: {ci_band}
- 사용자 설정 범위: {user_range}
- 주도 모델: {primary_model} (가중치 {primary_weight}%)
- 상위 기여 모델: {top_models}

[엄격한 작성 규칙]
- 한국어 자연 문장으로만 작성. 영어 번역 금지.
- 모델명은 영어 그대로 사용 ({primary_model} 등). 한글 음역 금지.
- LSTM, Transformer 언급 금지 (폐기됨).
- "Sentence", "Conclusion", "Draft" 같은 메타 라벨 금지.
- 마크다운 강조(**, *), bullet 금지.
- 정확히 3문장으로 작성. 그 외 텍스트 일체 추가 금지.
- 첫 문장: 추천 범위 + 주도 모델 명시.
- 두 번째 문장: 신뢰구간 / 사용자 설정과 비교.
- 세 번째 문장: 종합 결론 (사용자 설정 적합 여부 또는 권장 조정).
- 답변만 출력. 사고과정/번역/마크다운 출력 금지.

[답변 시작]
"""


async def _generate_one(
    filter_key: str,
    ens_min,
    ens_max,
    ci_band,
    user_range,
    model_expectations: dict,
    task_weights: dict,
) -> Optional[str]:
    """단일 필터에 대해 LLM 호출하여 자연 문장 생성."""
    try:
        from langchain_core.prompts import PromptTemplate
        from langchain_google_genai import ChatGoogleGenerativeAI
        from langchain_core.output_parsers import StrOutputParser
        import config

        # 주도 모델 추출 (task_weights 가장 큰 모델, 또는 model_expectations에서)
        sorted_w = sorted(task_weights.items(), key=lambda x: x[1], reverse=True)
        primary = sorted_w[0][0] if sorted_w else "xgboost"
        primary_w = sorted_w[0][1] * 100 if sorted_w else 0
        top3 = ", ".join(
            f"{_MODEL_KO.get(m, m)} {w*100:.1f}%"
            for m, w in sorted_w[:3]
        )

        llm_kwargs = {"model": config.LLM_MODEL, "temperature": 0.4}
        if config.GOOGLE_API_KEY:
            llm_kwargs["google_api_key"] = config.GOOGLE_API_KEY
        llm = ChatGoogleGenerativeAI(**llm_kwargs)
        prompt = PromptTemplate(
            template=_FILTER_PROMPT,
            input_variables=[
                "filter_label", "filter_key", "ens_min", "ens_max",
                "ci_band", "user_range", "primary_model", "primary_weight", "top_models"
            ],
        )
        chain = prompt | llm | StrOutputParser()
        response = await chain.ainvoke({
            "filter_label":   _FILTER_LABELS.get(filter_key, filter_key),
            "filter_key":     filter_key,
            "ens_min":        ens_min,
            "ens_max":        ens_max,
            "ci_band":        ci_band or "미생성",
            "user_range":     user_range,
            "primary_model":  _MODEL_KO.get(primary, primary),
            "primary_weight": f"{primary_w:.1f}",
            "top_models":     top3,
        })
        return _clean_response(response)
    except Exception as e:
        logger.warning(f"  filter_narrative {filter_key} 실패: {e}")
        return None


def _clean_response(text: str) -> str:
    """LLM 응답 후처리 — 한국어 자연 문장만 추출."""
    if not text:
        return ""
    text = text.strip()
    # 마크다운 강조
    text = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", text)
    # LaTeX
    text = re.sub(r"\$\\?\w+\$|\$.*?\$", "", text)
    # 영어 prompt-echo 괄호
    text = re.sub(r"\(\s*[A-Z][\s\S]*?\)", "", text)
    # 한국어 사이 끼어든 영어 sentence
    text = re.sub(r"(?:^|\s)[A-Za-z][A-Za-z\s,;:'.\-]{30,}\.\s*", " ", text)
    # Sentence/Conclusion 메타
    text = re.sub(r"(?:Sentence|Conclusion|Draft|Final|Reasoning)[^:]*?:\s*", "", text, flags=re.IGNORECASE)
    # bullet
    text = re.sub(r"^\s*[\-*•]\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s+[*\-•]\s+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


async def build_all_filter_narratives(range_analysis: dict, ensemble) -> dict:
    """
    26개 필터 evidence_text 일괄 생성.

    Args:
        range_analysis: weekly_pipeline_v2의 range_analysis dict
        ensemble: LottoEnsemble instance (task_weights 추출용)

    Returns:
        {filter_key: evidence_text or None}
    """
    if not range_analysis:
        return {}

    try:
        from models.ensemble import TASK_WEIGHTS
    except Exception:
        TASK_WEIGHTS = {}

    sem = asyncio.Semaphore(2)
    results = {}

    async def _one(fk: str, fdata: dict):
        async with sem:
            try:
                ens_min = fdata.get("ensemble_min")
                ens_max = fdata.get("ensemble_max")
                ci = fdata.get("ensemble_ci") or {}
                ci_band = ci.get("band") if isinstance(ci, dict) else None
                # raw filter_value
                rng = fdata.get("range")
                if isinstance(rng, str):
                    user_range = rng
                elif isinstance(rng, (list, tuple)) and len(rng) == 2:
                    user_range = f"{rng[0]} ~ {rng[1]}"
                else:
                    user_range = "미설정"
                # task_weights
                task = fdata.get("primary_task", "filter_count_attr")
                tw = TASK_WEIGHTS.get(task, {})
                if not tw:
                    # fallback: model_expectations 에서 weight 추출
                    me = fdata.get("model_expectations") or {}
                    tw = {k: v.get("weight", 0) for k, v in me.items()
                          if isinstance(v, dict) and k != "__ensemble__"}

                text = await _generate_one(
                    filter_key=fk,
                    ens_min=ens_min, ens_max=ens_max,
                    ci_band=ci_band, user_range=user_range,
                    model_expectations=fdata.get("model_expectations") or {},
                    task_weights=tw,
                )
                ko_count = len(re.findall(r"[가-힣]", text or ""))
                if ko_count >= 30:
                    results[fk] = text
                    logger.info(f"  [filter_narrative] {fk} OK ({len(text)}자)")
                else:
                    logger.warning(f"  [filter_narrative] {fk} 한국어 부족({ko_count}자), skip")
            except Exception as e:
                logger.warning(f"  [filter_narrative] {fk} 오류: {e}")

    await asyncio.gather(*[_one(fk, fdata) for fk, fdata in range_analysis.items()])
    return results
