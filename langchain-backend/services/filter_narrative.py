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


_FILTER_PROMPT = """다음 필터 분석을 한국어 3문장으로만 답해주세요. 영어 단어 사용 금지 (모델명 XGBoost/CNN/Bayesian 등은 예외).

[입력]
필터: {filter_label}
AI 예측 범위: {ens_min} ~ {ens_max}
신뢰구간 80%: {ci_band}
사용자 설정: {user_range}
주도 모델: {primary_model} ({primary_weight}%)

[답변 예시 (이 형식대로 한국어로 작성)]
끝수합은 22 ~ 33 범위로 예측되며 XGBoost가 31% 비중으로 주도하고 있습니다. 80% 신뢰구간 21 ~ 32에 사용자 설정 21 ~ 32가 포함되어 정합성이 높게 나타납니다. 종합적으로 사용자 설정 범위가 AI 예측과 일치하므로 그대로 사용해도 무리가 없습니다.

[답변 (위 예시처럼 정확히 한국어 3문장)]
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

        # [Stage 1-4-D-2-fix-58] 주도 모델 추출 — DEPRECATED(lstm/transformer) 제외
        DEPRECATED = {"lstm", "transformer"}
        active_w = {k: v for k, v in (task_weights or {}).items() if k not in DEPRECATED}
        sorted_w = sorted(active_w.items(), key=lambda x: x[1], reverse=True)
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
    """LLM 응답 후처리 — 한국어 자연 문장만 추출.

    [fix-57] Gemma가 영어 prompt-echo로 시작하는 경우 강화 처리:
    - '번호 N번' 또는 '필터 X번/X 분석' 같은 한국어 시작점부터 채택
    - 한국어 80자 이상 paragraph만 통과
    """
    if not text:
        return ""
    text = text.strip()

    # [fix-63 v3] early return 제거 — 모든 정리 단계 일관 적용
    # extract_final_answer가 fast-path로 반환하면 토큰/메타 잔재가 제거 안 됨

    # 1) 마크다운/LaTeX 정리
    text = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", text)
    text = re.sub(r"\$\\?\w+\$|\$.*?\$", "", text)
    # 2) 영어 괄호 안 텍스트 제거
    text = re.sub(r"\(\s*[A-Za-z][\s\S]*?\)", "", text)
    # 3) [fix-58] '1:', '2:', '3:' 메타 라벨 제거
    text = re.sub(r"\d+\s*:\s*", " ", text)
    # 4) [fix-58] '[1, 3]', '[0, 2]' 같은 array 메타 제거
    text = re.sub(r"\[\s*\d+\s*,\s*\d+\s*\]", " ", text)
    # 5) [fix-58] '(35.0%)', '(30.0%)' 같은 percent 메타 제거 (앞뒤 한글 문장 보존)
    text = re.sub(r"\(\s*\d+\.?\d*\s*%\s*\)", " ", text)
    # 6) [fix-58] '80%:' 메타 라벨 제거
    text = re.sub(r"\d+%\s*:\s*", " ", text)
    # 7) DEPRECATED 모델 멘션 제거 (lstm, transformer 폐기)
    text = re.sub(r"\b(?:lstm|transformer|LSTM|Transformer)\b\s*", "", text)
    # 8) [fix-63 v2] 모델명 화이트리스트 보호 — 한글+숫자 토큰 (영어 정규식 안 잡음)
    _MODEL_NAMES = ["XGBoost", "CatBoost", "TabNet", "TFT", "Markov", "N-BEATS",
                    "MHN", "Bayesian", "CNN", "GNN", "AutoEncoder", "AE"]
    _placeholders = {}
    for i, m in enumerate(_MODEL_NAMES):
        # 한글+숫자 토큰 (영어 알파벳 미포함 → 영어 제거 정규식 안 매칭)
        token = f"모델{i:02d}이름"
        if m in text:
            text = text.replace(m, token)
            _placeholders[token] = m
    # 9) 영어 단어 시퀀스 5자 이상 연속 제거 (모델명은 한글 토큰으로 보호됨)
    text = re.sub(r"[A-Za-z][A-Za-z\s,;:'.\-/_~]{4,}", " ", text)
    # 10) [fix-63 v2] 모델명 토큰 복원
    for token, m in _placeholders.items():
        text = text.replace(token, m)
    # 9) 한국어 사이 단독 영어 단어 정리 (3자 이하 모델명은 보존: AE)
    # text = re.sub(r"\s[A-Za-z]{2,4}\s", " ", text)
    # 10) bullet/대시 정리
    text = re.sub(r"^\s*[\-*•]\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s+[*\-•]\s+", " ", text)
    # 11) 잔여 양 끝 영어/공백 정리
    text = text.strip(" .,:;-_~/")
    # 12) [fix-58/63 v4] 마침표 split + sentence 안 메타데이터 제거
    sentences = re.split(r"[.!?]\s*", text)
    ko_sentences = []
    _start_pattern = re.compile(r"^([가-힣]|XGBoost|CatBoost|TabNet|TFT|Markov|N-BEATS|MHN|Bayesian|CNN|GNN|AutoEncoder|AE\b)")
    # 진짜 sentence 시작점 패턴: 명사 + 조사 (한국어 자연 문장의 정형)
    _real_start = re.compile(r"[가-힣]+(?:은|는|이|가|에|을|를|로|와|과|도|만)")
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        s = re.sub(r'["“”]', "", s)
        s = re.sub(r"\s+", " ", s).strip()
        # [fix-63 v5] 앞부분 메타데이터 잘라냄 — 명사+조사 위치가 sentence 시작에서 6자 초과 멀때만
        rs_match = _real_start.search(s)
        if rs_match and rs_match.start() > 6:
            # 6자 이내면 'AC값은', 'XGBoost가' 같은 자연 시작 — 보존
            # 6자 초과 → '총합 116 ~ 165 80% ... 총합은' 같은 메타 + 자연 혼재 → 잘라냄
            s = s[rs_match.start():].strip()
        # 한국어/모델명 시작 + 한글 10+ → 자연 문장
        if _start_pattern.match(s) and len(re.findall(r"[가-힣]", s)) >= 10:
            ko_sentences.append(s + ".")
    if ko_sentences:
        text = " ".join(ko_sentences)
    else:
        ko_match = re.search(r"[가-힣].+", text, re.DOTALL)
        text = ko_match.group(0) if ko_match else ""
    # 13) [fix-58 추가] 'S1:', 'S2:', 'S3:' 라벨 제거
    text = re.sub(r"S\d+\s*:\s*", "", text)
    # 13-2) [fix-63 v3] 잔재 토큰 (`__03__`, `04__`, `00__`) 제거 — LLM이 echo한 placeholder 잔재
    text = re.sub(r"_+\d+_+|\d+_{2,}|_{2,}\d+", " ", text)
    text = re.sub(r"_{2,}", " ", text)
    # 14) 공백 정리
    text = re.sub(r"\s+", " ", text)
    # 15) 잔여 마침표 중복 제거
    text = re.sub(r"\s+\.\s+", ". ", text)
    text = re.sub(r"\.{2,}", ".", text)
    # 16) [fix-58/63] 반복 sentence dedup — 단순 마침표 split
    final_sents = re.split(r"\.\s+", text)
    seen = set()
    deduped = []
    for s in final_sents:
        s = s.strip()
        if not s:
            continue
        # 정규화 키 (공백/숫자/특수문자 제거 후 한글만, 첫 25자)
        key = re.sub(r"[^가-힣]", "", s)[:25]
        if key and key not in seen:
            seen.add(key)
            # sentence 끝에 마침표 보장
            if not s.endswith(("."  , "!", "?")):
                s = s + "."
            deduped.append(s)
    if deduped:
        text = " ".join(deduped)
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
