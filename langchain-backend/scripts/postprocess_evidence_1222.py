"""
[Stage 1-4-D-2-fix-32] DB의 evidence_text를 LLM 재호출 없이 후처리.

기존 1222회차 45개 evidence_text는 Gemma reasoning process(영어 draft)까지
모두 포함되어 있음. extract_final_answer() 적용하여 한국어 최종 답변만 남김.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.supabase_client import get_client
from services.evidence_builder import extract_final_answer


def main(target_round: int = 1222):
    client = get_client()
    res = client.table("weekly_number_xai") \
        .select("number, evidence_text") \
        .eq("target_round", target_round) \
        .execute()

    rows = res.data or []
    print(f"[fix-32] {target_round}회차: {len(rows)}행 발견")

    updated = 0
    for row in rows:
        n = row["number"]
        raw = row.get("evidence_text") or ""
        if not raw:
            continue
        cleaned = extract_final_answer(raw)
        # 한국어 문장 50자 이상이어야 valid (영어 prompt-echo 제외)
        import re
        ko_count = len(re.findall(r'[가-힣]', cleaned or ""))
        final_value = cleaned if ko_count >= 50 else None
        if final_value == raw:
            continue
        client.table("weekly_number_xai") \
            .update({"evidence_text": final_value}) \
            .eq("target_round", target_round) \
            .eq("number", n) \
            .execute()
        updated += 1
        if final_value:
            print(f"  [{n:2d}] raw {len(raw)}자 -> cleaned {len(final_value)}자: {final_value[:80]}...")
        else:
            print(f"  [{n:2d}] raw {len(raw)}자 -> NULL (한국어 답변 미생성, frontend 합성 fallback)")

    print(f"\n[fix-32] update 완료: {updated}/{len(rows)}행")


if __name__ == "__main__":
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 1222
    main(target)
