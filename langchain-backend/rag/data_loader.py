"""lotto_draws DB 데이터를 LangChain Document로 변환하는 모듈."""

from langchain_core.documents import Document

PRIMES = {2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43}
SQUARES = {1, 4, 9, 16, 25, 36}
TRIANGULARS = {1, 3, 6, 10, 15, 21, 28, 36, 45}


def _compute_stats(numbers: list[int]) -> dict:
    """6개 번호에서 각종 통계를 계산한다."""
    nums = sorted(numbers)
    total_sum = sum(nums)
    odd_count = sum(1 for n in nums if n % 2 == 1)
    even_count = 6 - odd_count
    low_count = sum(1 for n in nums if n <= 22)
    high_count = 6 - low_count
    prime_count = sum(1 for n in nums if n in PRIMES)
    composite_count = sum(1 for n in nums if n > 1 and n not in PRIMES)
    square_count = sum(1 for n in nums if n in SQUARES)
    triangular_count = sum(1 for n in nums if n in TRIANGULARS)

    # AC값 계산
    diffs = set()
    for i in range(len(nums)):
        for j in range(i + 1, len(nums)):
            diffs.add(abs(nums[i] - nums[j]))
    ac_value = len(diffs) - 5  # 6개 번호의 AC값 = 차이값 개수 - (n-1)

    # 연번 쌍 수
    consecutive_pairs = sum(1 for i in range(len(nums) - 1) if nums[i + 1] - nums[i] == 1)

    # 끝수합
    tail_sum = sum(n % 10 for n in nums)

    # 번호대별 분포
    ranges = {"단번대": 0, "10번대": 0, "20번대": 0, "30번대": 0, "40번대": 0}
    for n in nums:
        if n <= 9:
            ranges["단번대"] += 1
        elif n <= 19:
            ranges["10번대"] += 1
        elif n <= 29:
            ranges["20번대"] += 1
        elif n <= 39:
            ranges["30번대"] += 1
        else:
            ranges["40번대"] += 1

    return {
        "total_sum": total_sum,
        "odd_count": odd_count,
        "even_count": even_count,
        "low_count": low_count,
        "high_count": high_count,
        "prime_count": prime_count,
        "composite_count": composite_count,
        "square_count": square_count,
        "triangular_count": triangular_count,
        "ac_value": ac_value,
        "consecutive_pairs": consecutive_pairs,
        "tail_sum": tail_sum,
        "ranges": ranges,
    }


def draw_to_document(draw: dict) -> Document:
    """단일 lotto_draws 레코드를 LangChain Document로 변환한다."""
    numbers = draw.get("numbers", [])
    if isinstance(numbers, str):
        numbers = [int(x) for x in numbers.strip("{}[]").split(",")]

    bonus = draw.get("bonus", 0)
    round_num = draw.get("round", 0)
    date = draw.get("date", "")

    stats = _compute_stats(numbers)
    nums_str = ",".join(str(n) for n in sorted(numbers))
    range_dist = " ".join(f"{k}{v}개" for k, v in stats["ranges"].items() if v > 0)

    primes_in = [n for n in numbers if n in PRIMES]
    primes_str = ",".join(str(n) for n in sorted(primes_in)) if primes_in else "없음"

    content = (
        f"{round_num}회차 로또 ({date}): "
        f"당첨번호 {nums_str} 보너스 {bonus}. "
        f"총합 {stats['total_sum']}. "
        f"홀짝비 {stats['odd_count']}:{stats['even_count']}. "
        f"저고비 {stats['low_count']}:{stats['high_count']}. "
        f"AC값 {stats['ac_value']}. "
        f"소수 {stats['prime_count']}개({primes_str}). "
        f"합성수 {stats['composite_count']}개. "
        f"제곱수 {stats['square_count']}개. "
        f"삼각수 {stats['triangular_count']}개. "
        f"연번 {stats['consecutive_pairs']}쌍. "
        f"끝수합 {stats['tail_sum']}. "
        f"번호대 {range_dist}."
    )

    metadata = {
        "round": round_num,
        "date": date,
        "numbers": ",".join(str(n) for n in sorted(numbers)),
        "bonus": bonus,
        "total_sum": stats["total_sum"],
        "odd_count": stats["odd_count"],
        "even_count": stats["even_count"],
        "low_count": stats["low_count"],
        "high_count": stats["high_count"],
        "ac_value": stats["ac_value"],
        "prime_count": stats["prime_count"],
        "consecutive_pairs": stats["consecutive_pairs"],
        "tail_sum": stats["tail_sum"],
        "source": "lotto_draws",
    }

    return Document(page_content=content, metadata=metadata)


def draws_to_documents(draws: list[dict]) -> list[Document]:
    """여러 lotto_draws 레코드를 Document 리스트로 변환한다."""
    docs = []
    for draw in draws:
        try:
            docs.append(draw_to_document(draw))
        except Exception as e:
            print(f"[WARN] {draw.get('round', '?')}회차 변환 실패: {e}")
    return docs


# ──────────────────────────────────────────────
# v4 추가: ai_predictions → RAG 문서 변환
# ──────────────────────────────────────────────

def prediction_to_document(prediction: dict, actual_draw: dict = None) -> Document:
    """ai_predictions 레코드를 RAG Document로 변환한다.

    Args:
        prediction: ai_predictions 테이블의 한 행
        actual_draw: 해당 회차의 실제 당첨 결과 (검증용, optional)
    """
    target_round = prediction.get("target_round", 0)
    ptype = prediction.get("prediction_type", "unknown")
    predicted = prediction.get("predicted_numbers", [])
    confidence = prediction.get("confidence_score", 0)
    model_version = prediction.get("model_version", "unknown")
    hit_count = prediction.get("hit_count")

    # 1. 기본 예측 정보
    content = (
        f"{target_round}회차 AI 예측 ({ptype}): "
        f"추천 번호 {','.join(str(n) for n in sorted(predicted))}. "
        f"모델 버전 {model_version}. 신뢰도 {confidence:.1%}."
    )

    # 2. 실제 결과와 비교 (검증 정보)
    if actual_draw:
        actual = actual_draw.get("numbers", [])
        # 실제 적중 개수 계산 (DB에 없으면 직접 계산)
        if hit_count is None:
            hit_count = len(set(predicted) & set(actual))
            
        hits = sorted(set(predicted) & set(actual))
        content += (
            f" 실제 당첨번호 {','.join(str(n) for n in sorted(actual))}."
            f" 결과: {hit_count}개 적중"
            f" ({','.join(str(n) for n in hits) if hits else '없음'})."
        )

    # 3. 추론 근거 (Reasoning)
    detail = prediction.get("analysis_detail", {})
    if isinstance(detail, dict):
        reasoning = detail.get("reasoning", "")
        if reasoning:
            content += f" 추론 근거: {reasoning}"

    metadata = {
        "round": target_round,
        "type": ptype,
        "hit_count": hit_count if hit_count is not None else -1,
        "confidence": confidence,
        "model_version": model_version,
        "source": "ai_predictions",
    }

    return Document(page_content=content, metadata=metadata)


def predictions_to_documents(
    predictions: list[dict], draws_map: dict = None
) -> list[Document]:
    """여러 ai_predictions 레코드를 Document 리스트로 변환한다.

    Args:
        predictions: ai_predictions 레코드 리스트
        draws_map: {round: draw_data} 매핑 (검증용, optional)
    """
    docs = []
    for pred in predictions:
        try:
            actual = None
            if draws_map:
                actual = draws_map.get(pred.get("target_round"))
            docs.append(prediction_to_document(pred, actual))
        except Exception as e:
            print(f"[WARN] 예측 데이터 변환 실패 (Round {pred.get('target_round')}): {e}")
    return docs
