"""임베딩 파이프라인: DB 데이터 -> 벡터 인덱스 빌드."""

from db.supabase_client import fetch_all_draws, fetch_draws_after
from db.vector_store import add_documents, get_document_count
from rag.data_loader import draws_to_documents


def build_full_index() -> int:
    """전체 lotto_draws를 벡터화한다 (초기 빌드)."""
    print("전체 데이터 로딩 중...")
    draws = fetch_all_draws()
    print(f"  {len(draws)}개 회차 로딩 완료")

    docs = draws_to_documents(draws)
    print(f"  {len(docs)}개 문서 변환 완료")

    # 배치 처리 (API rate limit 방지)
    batch_size = 50
    for i in range(0, len(docs), batch_size):
        batch = docs[i : i + batch_size]
        add_documents(batch)
        print(f"  [{i + len(batch)}/{len(docs)}] 벡터화 완료")

    total = get_document_count()
    print(f"벡터 인덱스 빌드 완료: 총 {total}개 문서")
    return total


def update_incremental(after_round: int) -> int:
    """특정 회차 이후 데이터만 증분 벡터화한다."""
    draws = fetch_draws_after(after_round)
    if not draws:
        print("새로운 데이터 없음")
        return 0

    docs = draws_to_documents(draws)
    add_documents(docs)
    print(f"{len(docs)}개 회차 증분 벡터화 완료")
    return len(docs)
