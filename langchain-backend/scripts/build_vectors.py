"""초기 벡터 인덱스 전체 빌드 스크립트."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rag.embedder import build_full_index

if __name__ == "__main__":
    print("=" * 50)
    print("로또 벡터 인덱스 빌드 시작")
    print("=" * 50)
    total = build_full_index()
    print(f"\n완료! 총 {total}개 문서가 벡터화되었습니다.")
