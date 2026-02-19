"""증분 벡터 업데이트 스크립트."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.vector_store import get_document_count
from rag.embedder import update_incremental

if __name__ == "__main__":
    current = get_document_count()
    print(f"현재 벡터 문서 수: {current}")

    # 현재 문서 수를 대략적인 마지막 회차로 사용
    count = update_incremental(current)
    if count > 0:
        print(f"{count}개 회차 증분 업데이트 완료")
    else:
        print("새 데이터 없음 - 최신 상태")
