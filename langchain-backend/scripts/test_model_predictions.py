# -*- coding: utf-8 -*-
"""model_predictions 저장 기능 단위 테스트.

Supabase RLS 정책 확인용.
"""

from __future__ import annotations

from models.ensemble import LottoEnsemble
from db.supabase_client import fetch_all_draws, get_client

# 1. 예측 생성
draws = fetch_all_draws()
historical = [d for d in draws if int(d.get("round", 0)) < 1222]

ensemble = LottoEnsemble()
result = ensemble.predict_top5(
    draws=historical,
    n_top=5,
    round_number=1222,
    save_predictions=False,
)

contributions = result.get("contributions", {})
print(f"Model contributions: {len(contributions)}")

# 2. save_model_predictions 직접 호출
save_result = ensemble.save_model_predictions(1222, contributions)

print(f"\nSave result: {save_result}")

if save_result.get("success"):
    print(f"SUCCESS: {save_result['saved_count']} models saved")
    print(f"Models: {', '.join(save_result['models'])}")

    # 3. 검증
    client = get_client()
    verify = client.table("model_predictions").select("*").eq("round_number", 1222).execute()
    print(f"\nVerification: {len(verify.data)} records in DB")

    for record in verify.data[:3]:
        print(f"  - {record['model_name']}: {record['predicted_top10'][:5]}...")
else:
    print(f"FAILED: {save_result.get('error', 'unknown')}")
    print("\nLikely RLS policy issue - user needs to disable RLS or add policy for model_predictions table")
