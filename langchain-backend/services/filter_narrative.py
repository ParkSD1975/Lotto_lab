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
    # [fix-77] prime_hot/prime_cold — 최근 3회차 등장/미등장 소수 세분화
    "prime_hot": "소수(핫·최근 3회 등장)", "prime_cold": "소수(콜드·최근 3회 미등장)",
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


_FILTER_PROMPT = """You are a Korean lottery analyst. Write exactly 3 natural Korean sentences analyzing the filter below. Output only the 3 sentences in Korean — no preamble, no English explanation, no bullet points, no labels.

Filter data:
- Filter name: {filter_label}
- Predicted range: {ens_min} to {ens_max}
- 80% confidence interval: {ci_band}
- User setting: {user_range}
- Dominant model: {primary_model} (weight {primary_weight}%)

Output exactly 3 Korean sentences in this order:
First sentence: The predicted range of {filter_label} and {primary_model} with {primary_weight} percent weight (always include the percent sign).
Second sentence: Compare the 80 percent confidence interval with the user setting.
Third sentence: A conclusion starting with "종합적으로".

Constraints:
- Korean only. Allowed English tokens: model names XGBoost/CatBoost/TabNet/CNN/GNN/Markov/AE/TFT/N-BEATS/MHN/Bayesian.
- Every number must carry a unit (%, 점, 개, 회). Never end a clause like "Markov가 25." without a unit.
- Do not mention any other filter name except "{filter_label}".
- Do not echo these instructions back. Output only S1 + S2 + S3, separated by spaces.

Example tone (do not copy values, only style):
"{filter_label}은 X ~ Y 범위로 예측되며 XGBoost가 30.0% 비중으로 주도하고 있습니다. 80% 신뢰구간 X ~ Y에 사용자 설정 A ~ B가 포함되어 정합성이 높게 나타납니다. 종합적으로 사용자 설정 범위가 AI 예측과 일치하므로 그대로 사용해도 무리가 없습니다."

Output (3 Korean sentences only):
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
        return _clean_response(response, current_filter_key=filter_key)
    except Exception as e:
        logger.warning(f"  filter_narrative {filter_key} 실패: {e}")
        return None


def _clean_response(text: str, current_filter_key: Optional[str] = None) -> str:
    """LLM 응답 후처리 — 한국어 자연 문장만 추출.

    [fix-57] Gemma가 영어 prompt-echo로 시작하는 경우 강화 처리:
    - '번호 N번' 또는 '필터 X번/X 분석' 같은 한국어 시작점부터 채택
    - 한국어 80자 이상 paragraph만 통과

    [fix-73] cross-contamination 차단:
    - current_filter_key가 주어지면 다른 필터의 한국어 라벨이 등장하는 sentence 폐기
    - "X가 25." 처럼 숫자 뒤 단위 없이 마침표 찍힌 어절 잘림 감지 → 해당 sentence 폐기
    - "종합적으로/결론적으로" 시작 sentence는 첫 1개만 채택
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
        # [fix-78] _real_start 트리밍 비활성화
        # 기존(fix-63 v5)은 'X: AI 종합 ...' 같은 메타 라벨을 자르려 했으나,
        # 'AI 예측 범위 0개에서 1개에 비해 ...' 같은 자연 한국어 prefix까지 잘라
        # '개에 비해 ...' fragment를 만들어버림.
        # 메타 라벨/prompt-echo는 _PROMPT_ECHO_PATTERNS에서 별도 처리.
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
    # [fix-73] 다른 필터 라벨 (current_filter_key 외) 수집
    _other_labels = []
    if current_filter_key:
        for fk, label in _FILTER_LABELS.items():
            if fk == current_filter_key:
                continue
            # 짧은 라벨(2자 이하)은 우연 매치 위험 → 4자 이상만 사용
            if len(label) >= 4:
                _other_labels.append(label)
            else:
                # '연번', '소수', '동형수' 등 짧은 라벨은 단어 경계 강화
                _other_labels.append(label)
    # 결론 sentence 카운터 (종합적으로/결론적으로 시작)
    conclusion_count = 0
    # 어절 잘림 패턴: 모델명+조사 뒤 숫자+마침표로 끝나는 단편 (단위 누락)
    _MODEL_NAMES_ALL = ["XGBoost", "CatBoost", "TabNet", "TFT", "Markov", "N-BEATS",
                        "MHN", "Bayesian", "CNN", "GNN", "AutoEncoder", "AE"]
    _model_alt = "|".join(re.escape(m) for m in _MODEL_NAMES_ALL)
    # [fix-76/78] 강화: 모델명 + (이|가|모델이)? + 숫자(.소수)? + 옵션 마침표 + sentence 끝
    # (마침표 포함하여 매치 — sentence가 "...XGBoost가 18." 처럼 마침표 직전에 끝나도 검출)
    _truncated_pat = re.compile(rf"(?:{_model_alt})(?:이|가|\s*모델이)?\s*\d+(?:\.\d+)?\s*\.?\s*$")
    # [fix-76 추가] prompt-echo 검출 패턴
    _PROMPT_ECHO_PATTERNS = [
        # 메타 라벨/규칙 echo
        re.compile(r"^종합적으로\s*or\s*결론적으로"),
        re.compile(r"^결론적으로\s*or"),
        re.compile(r"모든\s*숫자\s*뒤에\s*반드시"),
        re.compile(r"뒤에\s*반드시\s*단위"),
        re.compile(r"필터에\s*대해서만\s*작성"),
        re.compile(r"이름을\s*절대\s*언급"),
        re.compile(r"영어\s*단어\s*사용\s*금지"),
        re.compile(r"결론\s*문장은\s*정확히"),
        re.compile(r"\[형식|\[입력|\[답변|\[엄격"),
        re.compile(r"^(만\s*예외|예외\)|예외\s*\))"),
        re.compile(r"종합적으로\s*\d+\s*종합적으로"),
        re.compile(r"^S\d+\s*\("),  # "S1 (Korean):" 같은 영어 형식 라벨
        re.compile(r"(?i)\b(first|second|third)\s+sentence\b"),  # prompt 영어 라벨 echo
        re.compile(r"(?i)\boutput\s+(?:exactly|only)\b"),  # "Output exactly 3 Korean sentences"
    ]
    # [fix-76] placeholder echo 패턴 ("필터명은(는)", "모델이(가)") — 자연 조사로 변환
    _placeholder_josa_pat = re.compile(r"([가-힣A-Za-z0-9]+)은\(는\)")
    _placeholder_josa_pat2 = re.compile(r"([가-힣A-Za-z0-9]+)이\(가\)")
    # [fix-78] 의존명사 시작 fragment 검출
    # 자연스러운 sentence는 명사+조사("연번은", "총합이", "예측은")로 시작
    # 의존명사("개", "점", "회", "호")로 시작하면 앞 어절 손실된 fragment → 폐기
    _dep_noun_start_pat = re.compile(r"^(개|점|회|호)(에|와|과|로|을|를|이|가|는|도|만)\b")
    for s in final_sents:
        s = s.strip()
        if not s:
            continue
        # [fix-76 a] placeholder 조사 정리 — "필터명은(는)" → "필터명은", "모델이(가)" → "모델이"
        s = _placeholder_josa_pat.sub(r"\1은", s)
        s = _placeholder_josa_pat2.sub(r"\1이", s)
        # [fix-76 b] prompt-echo sentence 폐기
        if any(p.search(s) for p in _PROMPT_ECHO_PATTERNS):
            continue
        # [fix-78] 의존명사("개"/"점"/"회"/"호") + 조사로 시작하는 fragment 폐기
        if _dep_noun_start_pat.match(s):
            continue
        # [fix-73 a] 다른 필터 라벨 침투 검출 → sentence 폐기
        if _other_labels:
            hit_other = False
            for label in _other_labels:
                # current label과 substring 충돌 방지: current_label이 label을 포함하면 skip
                cur_label = _FILTER_LABELS.get(current_filter_key or "", "")
                if cur_label and label in cur_label:
                    continue
                if label in s:
                    hit_other = True
                    break
            if hit_other:
                continue
        # [fix-73 b / fix-76 강화] 어절 잘림 검출 — "Markov가 25." 단위 누락 → 폐기
        if _truncated_pat.search(s):
            continue
        # [fix-73 c] 결론 문장은 첫 1개만
        is_conclusion = bool(re.match(r"^(종합적으로|결론적으로)", s))
        if is_conclusion:
            if conclusion_count >= 1:
                continue
            conclusion_count += 1
        # [fix-76] 너무 짧은 단편(한글 8자 미만)은 폐기 — 의미 없는 토막 차단
        ko_chars = len(re.findall(r"[가-힣]", s))
        if ko_chars < 8:
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
