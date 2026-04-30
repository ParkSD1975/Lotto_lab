"""
[Stage 1-4-D-2-fix-28] 번호별 XAI evidence 합성기

매주 1회 weekly_pipeline_v2 실행 시 45개 번호 각각에 대해 evidence reasons를
즉석 합성하여 weekly_number_xai.evidence_text 컬럼에 저장한다.

LLM 호출 없는 deterministic 합성 — 매주 1회 < 1초 소요.

프론트는 SELECT만으로 즉시 표시 (lazy fetch /api/explain/ 폐기).
"""

from typing import Optional


_MODEL_KO = {
    "xgboost": "XGBoost",
    "catboost": "CatBoost",
    "tabnet": "TabNet",
    "cnn": "CNN",
    "gnn": "GNN",
    "markov": "Markov",
    "autoencoder": "AE",
    "tft": "TFT",
    "nbeats": "N-BEATS",
    "mhn": "MHN",
    "bayesian_nn": "Bayesian",
}


def synthesize_evidence(
    num: int,
    total_prob: float,
    gap: Optional[int],
    freq: Optional[float],
    models_xai: dict,
    top5: list,
    exclude10: list,
    penalty: float = 1.0,
    boost: float = 1.0,
    is_memo_excluded: bool = False,
) -> Optional[str]:
    """
    번호별 evidence reasons 합성. '|'-separated string.

    Args:
        num:               번호 (1~45)
        total_prob:        앙상블 확률 % (0~100)
        gap:               미출현 횟수 (None 가능)
        freq:              출현 빈도 0~1
        models_xai:        {model_name: score_pct}  (예: {'xgboost': 89.9, ...})
        top5:              추천 5 번호 list
        exclude10:         제외 10 번호 list
        penalty:           과출현 패널티 (1.0=없음, ≤0.35=극심)
        boost:             주기 임박 부스트 (1.0=없음, ≥1.45=임박)
        is_memo_excluded:  사용자 메모 강제 제외

    Returns:
        '|'-separated reasons string. 없으면 None.
    """
    reasons = []

    # 1. 사용자 메모 강제 제외
    if is_memo_excluded:
        reasons.append("[경고] 사용자 메모 — 강제 제외 대상")

    # 2. 추천/제외 상태
    if num in top5:
        reasons.append(f"매우 유력 — 앙상블 추천 {total_prob:.2f}% 강신호")
    elif num in exclude10:
        reasons.append(f"[경고] 제외 후보 — 앙상블 {total_prob:.2f}% 약신호")

    # 3. 주도 모델 분석
    if models_xai:
        sorted_models = sorted(models_xai.items(), key=lambda x: x[1], reverse=True)
        top1_name, top1_score = sorted_models[0]
        top2_name, top2_score = (sorted_models[1] if len(sorted_models) > 1 else (None, 0))
        if top1_score >= 50:
            reasons.append(
                f"{_MODEL_KO.get(top1_name, top1_name)} {top1_score:.1f}% 압도적 주도 — 단독 강신호"
            )
        elif top1_score >= 20 and top2_score >= 10:
            reasons.append(
                f"{_MODEL_KO.get(top1_name, top1_name)} {top1_score:.1f}% + "
                f"{_MODEL_KO.get(top2_name, top2_name)} {top2_score:.1f}% 합의"
            )
        elif top1_score < 5:
            reasons.append("전 모델 약신호 — 모델 합의 부족")

    # 4. Gap 분석
    if gap is not None:
        try:
            gap_n = int(gap)
            if gap_n == 0:
                reasons.append("직전 회차 출현 — 단기 모멘텀 활성")
            elif gap_n <= 5:
                reasons.append(f"{gap_n}회 미출현 — 단기 반등 영역")
            elif gap_n <= 15:
                reasons.append(f"{gap_n}회 미출현 — 평균 주기 내 복귀 신호")
            elif gap_n <= 30:
                reasons.append(f"{gap_n}회 미출현 — 중장기 반등 적합")
            else:
                reasons.append(f"[경고] {gap_n}회 미출현 — 장기 데드콜드 우려")
        except (TypeError, ValueError):
            pass

    # 5. 빈도
    if freq is not None and freq > 0:
        freq_pct = freq * 100
        if freq >= 0.15:
            reasons.append(f"최근 빈도 {freq_pct:.1f}% 높음 — 활성 영역")
        elif freq < 0.05:
            reasons.append(f"[경고] 빈도 {freq_pct:.1f}% 부족 — 출현 약세")

    # 6. 과출현 패널티
    if penalty < 1.0:
        pen_pct = round((1 - penalty) * 100)
        if penalty <= 0.35:
            reasons.append(f"[경고] 극심 과출현 {pen_pct}% 차감 — 평균 회귀 압력")
        elif penalty <= 0.5:
            reasons.append(f"[경고] 강 과출현 {pen_pct}% 차감")
        else:
            reasons.append(f"과출현 {pen_pct}% 차감 — 보정 진행")

    # 7. 주기 임박 부스트
    if boost > 1.0:
        boost_pct = round((boost - 1) * 100)
        if boost >= 1.45:
            reasons.append(f"출현 임박 +{boost_pct}% — 주기 한계 초과")
        elif boost >= 1.25:
            reasons.append(f"주기 초과 +{boost_pct}% — 복귀 신호")
        else:
            reasons.append(f"주기 근접 +{boost_pct}% — 출현 적합")

    return " | ".join(reasons) if reasons else None


def extract_final_answer(text: str) -> str:
    """
    [Stage 1-4-D-2-fix-32] LLM 응답에서 thinking/reasoning 제거 후
    한국어 최종 답변만 추출.

    Gemma 모델은 reasoning process(영어 draft)을 노출하는 경향이 있어
    "Final Polish (Korean):" 또는 마지막 한국어 단락을 우선 추출.
    """
    if not text:
        return ""
    import re
    text = text.strip()

    # 패턴 1: "Final Polish (Korean):" 또는 "Final (Korean):" 이후
    m = re.search(
        r'(?:Final Polish|Final|Final Answer|최종)[^:]*?\(?(?:Korean|한국어)?\)?:?\s*\n+\s*(번호\s*\d+[^\n]*[가-힣].+?)(?:\n\n|\*\s|$)',
        text, re.DOTALL
    )
    if m:
        return _clean_md(m.group(1))

    # 패턴 2: "Draft 2 ... Korean" 또는 마지막 *...:* 블록의 한국어
    m = re.search(
        r'(?:Draft 2|Refin\w+)[^:]*?:?\s*\n+\s*(?:[\-*]\s*)?(번호\s*\d+[^\n]*[가-힣].+?)(?:\n\n|\*\s|$)',
        text, re.DOTALL
    )
    if m:
        return _clean_md(m.group(1))

    # 패턴 3: 한국어 최소 80자 이상의 마지막 paragraph
    paragraphs = re.split(r'\n\s*\n', text)
    for p in reversed(paragraphs):
        p = p.strip()
        # 마크다운 메타 라인 제외
        if p.startswith(('*', '-', '#', '`')):
            continue
        ko_count = len(re.findall(r'[가-힣]', p))
        if ko_count >= 80:
            return _clean_md(p)

    # 패턴 4: "번호 NN번" 으로 시작하는 첫 paragraph
    m = re.search(r'(번호\s*\d+번[^\n]+(?:\n[^\*\n][^\n]+)*)', text)
    if m:
        return _clean_md(m.group(1))

    # 패턴 5: 영어 prompt-echo만 있는 케이스 — 한국어 답변 못 찾음 → 빈 문자열 반환
    # (frontend가 합성 fallback 사용하도록)
    return ""


def _clean_md(text: str) -> str:
    """마크다운 강조(**, *)와 LaTeX 제거."""
    import re
    text = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', text)
    text = re.sub(r'\$\\?\w+\$|\$.*?\$', '', text)
    text = re.sub(r'\\rightarrow', '→', text)
    text = re.sub(r'\\\w+', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


async def build_all_evidence_llm(target_round: int, draws_data=None) -> dict:
    """
    [Stage 1-4-D-2-fix-30] LLM(Gemma) 기반 evidence 생성 — 모달과 동일 응답.

    chains.explain_chain.explain_number()를 45회 호출하여 자연 문장 응답을
    weekly_number_xai.evidence_text에 저장할 수 있는 형태로 반환.

    매주 1회 weekly_pipeline_v2 실행 시 호출되며, 45 × 1~2초 = 1~2분 소요.

    Returns:
        {n: 자연 문장 (LLM 응답) or None}
    """
    import asyncio
    import logging
    logger = logging.getLogger(__name__)
    try:
        from chains.explain_chain import explain_number
    except Exception as e:
        logger.warning(f"explain_chain import 실패: {e}")
        return {}

    result = {}
    # 동시 호출 3개 제한 (LLM rate limit 보호)
    sem = asyncio.Semaphore(3)

    async def _one(n: int):
        async with sem:
            try:
                text = await explain_number(
                    number=n,
                    user_query="이 번호에 대한 심층 분석을 해줘",
                    target_round=target_round,
                    draws_data=draws_data,
                )
                if text and not text.startswith("죄송"):
                    # [fix-32] reasoning process 제거, 한국어 최종 답변만 추출
                    result[n] = extract_final_answer(text)
            except Exception as e:
                logger.warning(f"  evidence LLM {n}번 실패: {e}")

    await asyncio.gather(*[_one(n) for n in range(1, 46)])
    return result


def build_all_evidence(
    target_round: int,
    xai: dict,
    final_probs: dict,
    feature_map: dict,
    top5: list,
    exclude10: list,
) -> dict:
    """
    45개 번호 evidence 일괄 생성. weekly_pipeline_v2.py 호출용 헬퍼.

    Args:
        target_round:   대상 회차
        xai:            {n: {model_name: pct, ...}}  (weekly_number_xai 와 동일 형식)
        final_probs:    {n: probability 0~1}
        feature_map:    {n: {missing_count, freq, penalty, boost, ...}}
        top5:           추천 5 번호
        exclude10:      제외 10 번호

    Returns:
        {n: evidence_text or None}
    """
    result = {}
    for n in range(1, 46):
        x = xai.get(n) or xai.get(str(n)) or {}
        models_xai = {
            k: float(x.get(k, 0))
            for k in ("xgboost", "catboost", "tabnet", "cnn", "gnn",
                     "markov", "autoencoder", "tft", "mhn", "bayesian_nn")
        }
        f = feature_map.get(n) or feature_map.get(str(n)) or {}
        gap = f.get("missing_count")
        freq = f.get("freq") or f.get("frequency")
        if freq is None and "freq_count" in f:
            freq = float(f["freq_count"]) / 20.0  # 최근 20회 기준
        penalty = float(f.get("penalty", 1.0))
        boost = float(f.get("boost", 1.0))
        prob = float(final_probs.get(n, 0)) * 100  # %

        result[n] = synthesize_evidence(
            num=n,
            total_prob=prob,
            gap=gap,
            freq=freq,
            models_xai=models_xai,
            top5=top5,
            exclude10=exclude10,
            penalty=penalty,
            boost=boost,
            is_memo_excluded=False,  # weekly_pipeline 단계에서는 메모 미반영
        )
    return result
