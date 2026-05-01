"""[fix-76 검증] DB의 evidence_text를 UTF-8로 출력해 실제 LLM 응답 확인."""
import os
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.supabase_client import get_client

client = get_client()
res = client.table("weekly_filter_predictions") \
    .select("filter_key, evidence_text") \
    .eq("target_round", 1222) \
    .execute()

for row in (res.data or []):
    fk = row["filter_key"]
    et = row.get("evidence_text") or ""
    print(f"\n[{fk}]")
    print(et)
