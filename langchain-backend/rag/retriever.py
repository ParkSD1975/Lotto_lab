"""최신성 가중치를 적용하는 커스텀 검색기."""

from db.vector_store import get_vector_store


def retrieve(query: str, analysis_type: str | None = None, k: int = 10) -> list:
    """시맨틱 검색 + 최신성 가중치로 관련 문서를 검색한다."""
    store = get_vector_store()
    raw_results = store.similarity_search_with_score(query, k=k * 2)

    if not raw_results:
        return []

    max_round = max(
        (doc.metadata.get("round", 0) for doc, _ in raw_results), default=0
    )

    scored = []
    for doc, score in raw_results:
        round_num = doc.metadata.get("round", 0)
        recency = 1.0 + 0.5 * max(0, 1 - (max_round - round_num) / 100)
        final_score = score * recency
        scored.append((doc, final_score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:k]


def retrieve_as_text(query: str, analysis_type: str | None = None, k: int = 10) -> str:
    """검색 결과를 텍스트 컨텍스트로 반환한다."""
    results = retrieve(query, analysis_type, k)
    if not results:
        return "(관련 과거 데이터 없음)"
    return "\n".join(doc.page_content for doc, _ in results)
