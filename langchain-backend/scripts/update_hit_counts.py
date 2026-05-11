# -*- coding: utf-8 -*-
"""model_predictions 테이블의 hit_count 업데이트 스크립트.

backfill_model_predictions는 predicted_top10만 저장하고,
실제 당첨번호와 비교한 hit_count는 별도 업데이트가 필요.
"""

from __future__ import annotations

import argparse
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.supabase_client import fetch_all_draws, get_client


def update_hit_counts(start_round: int, end_round: int) -> dict:
    """model_predictions 테이블의 hit_count 업데이트.

    Args:
        start_round: 시작 회차
        end_round: 종료 회차

    Returns:
        {"success": bool, "updated_count": int}
    """
    print(f"[update_hit_counts] Updating rounds {start_round}~{end_round}")

    # 1. 실제 당첨번호 로드
    draws = fetch_all_draws()
    if not draws:
        return {"success": False, "error": "No draws data"}

    actual_numbers_map = {}
    for d in draws:
        round_num = int(d.get("round", 0))
        if start_round <= round_num <= end_round:
            actual_numbers_map[round_num] = d.get("numbers", [])

    print(f"[update_hit_counts] Loaded {len(actual_numbers_map)} rounds actual numbers")

    # 2. model_predictions 레코드 가져오기
    try:
        client = get_client()
        result = (
            client.table("model_predictions")
            .select("id, round_number, model_name, predicted_top10")
            .gte("round_number", start_round)
            .lte("round_number", end_round)
            .execute()
        )

        records = result.data or []
        print(f"[update_hit_counts] Fetched {len(records)} model_predictions records")

    except Exception as e:
        return {"success": False, "error": f"fetch failed: {e}"}

    # 3. hit_count 계산 및 업데이트
    updated_count = 0
    errors = []

    for rec in records:
        rec_id = rec["id"]
        round_num = rec["round_number"]
        model_name = rec["model_name"]
        predicted_top10 = rec.get("predicted_top10", [])

        if round_num not in actual_numbers_map:
            print(f"  [skip] round {round_num}: no actual numbers")
            continue

        actual_nums = actual_numbers_map[round_num]
        hit_count = len(set(predicted_top10) & set(actual_nums))

        # update
        try:
            client.table("model_predictions").update(
                {
                    "actual_numbers": actual_nums,
                    "hit_count": hit_count,
                }
            ).eq("id", rec_id).execute()

            updated_count += 1

            if updated_count <= 10 or updated_count % 100 == 0:
                print(f"  [{model_name}] round {round_num}: hit={hit_count}/10")

        except Exception as e:
            error_msg = f"round {round_num} {model_name}: {e}"
            errors.append(error_msg)
            print(f"  [ERROR] {error_msg}")

    return {
        "success": True,
        "updated_count": updated_count,
        "errors": errors,
    }


def main():
    parser = argparse.ArgumentParser(description="Update hit_count in model_predictions")
    parser.add_argument(
        "--start",
        type=int,
        required=True,
        help="시작 회차",
    )
    parser.add_argument(
        "--end",
        type=int,
        required=True,
        help="종료 회차",
    )

    args = parser.parse_args()

    result = update_hit_counts(start_round=args.start, end_round=args.end)

    if result["success"]:
        print(f"\n[SUCCESS] Updated {result['updated_count']} records")
        if result.get("errors"):
            print(f"  Errors: {len(result['errors'])}")
            for err in result["errors"][:5]:
                print(f"    - {err}")
        return 0
    else:
        print(f"\n[FAILED] {result.get('error', 'unknown')}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
