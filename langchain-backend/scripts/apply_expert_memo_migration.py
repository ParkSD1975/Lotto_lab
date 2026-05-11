"""Supabase expert_memo 테이블 마이그레이션 적용.

Supabase Python client는 raw SQL DDL 실행을 직접 지원하지 않으므로,
이 스크립트는 SQL 내용을 출력하여 사용자가 Supabase SQL Editor에서 수동 실행하도록 안내합니다.

또는 테스트를 위해 간단히 테이블 존재 여부만 확인하고,
e2e 테스트에서 graceful fallback을 통해 진행합니다.
"""
from __future__ import annotations

import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from db.supabase_client import get_client


def main() -> None:
    """테이블 존재 여부 확인 및 마이그레이션 안내."""
    print("[apply_expert_memo_migration] start")

    client = get_client()

    # expert_memos 테이블 존재 확인
    print("\n[1] Check expert_memos table")
    try:
        res = client.table("expert_memos").select("id").limit(1).execute()
        print(f"    expert_memos table exists: {res is not None}")
    except Exception as e:
        print(f"    expert_memos table NOT found: {e}")
        print("\n    [ACTION REQUIRED]")
        print("    1. Open Supabase SQL Editor (https://supabase.com/dashboard)")
        print("    2. Copy content from: db/migrations/002_expert_memo_tables.sql")
        print("    3. Run the SQL to create tables")
        print("\n    Alternative: Use Supabase CLI:")
        print("      supabase db push --file db/migrations/002_expert_memo_tables.sql")
        return

    # expert_memo_history 테이블 존재 확인
    print("\n[2] Check expert_memo_history table")
    try:
        res = client.table("expert_memo_history").select("id").limit(1).execute()
        print(f"    expert_memo_history table exists: {res is not None}")
    except Exception as e:
        print(f"    expert_memo_history table NOT found: {e}")
        print("    [ACTION REQUIRED] (same as above)")
        return

    print("\n[apply_expert_memo_migration] Tables verified OK")
    print("You can now run: python scripts/_test_expert_memo.py")


if __name__ == "__main__":
    main()
