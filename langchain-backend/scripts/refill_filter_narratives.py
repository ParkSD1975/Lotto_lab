"""
[Stage 1-4-D-2-fix-58] DB의 filter narratives를 LLM 재호출.
fix-57의 새 prompt (1-shot 한국어 예시) 적용.
"""
import os
import sys
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.supabase_client import get_client
from services.filter_narrative import _generate_one, _clean_response


async def refill(target_round: int = 1222):
    client = get_client()
    res = client.table("weekly_filter_predictions") \
        .select("filter_key, ensemble_min, ensemble_max, ensemble_ci, filter_value, primary_task, model_expectations") \
        .eq("target_round", target_round) \
        .execute()
    rows = res.data or []
    print(f"[fix-58] {target_round} 회차 {len(rows)} 필터 재호출")

    try:
        from models.ensemble import TASK_WEIGHTS
    except Exception:
        TASK_WEIGHTS = {}

    sem = asyncio.Semaphore(2)

    async def _one(row):
        async with sem:
            fk = row["filter_key"]
            ci = row.get("ensemble_ci") or {}
            ci_band = ci.get("band") if isinstance(ci, dict) else None
            user_range = row.get("filter_value") or "미설정"
            task = row.get("primary_task", "filter_count_attr")
            tw = TASK_WEIGHTS.get(task, {})
            if not tw:
                me = row.get("model_expectations") or {}
                tw = {k: v.get("weight", 0) for k, v in me.items()
                      if isinstance(v, dict) and k != "__ensemble__"}
            for attempt in range(2):
                try:
                    text = await _generate_one(
                        filter_key=fk,
                        ens_min=row.get("ensemble_min"),
                        ens_max=row.get("ensemble_max"),
                        ci_band=ci_band,
                        user_range=user_range,
                        model_expectations=row.get("model_expectations") or {},
                        task_weights=tw,
                    )
                    if text:
                        import re
                        ko = len(re.findall(r"[가-힣]", text))
                        if ko >= 30:
                            client.table("weekly_filter_predictions") \
                                .update({"evidence_text": text}) \
                                .eq("target_round", target_round) \
                                .eq("filter_key", fk) \
                                .execute()
                            print(f"  [{fk:15s}] OK ({len(text)}자, 시도{attempt+1}): {text[:90]}")
                            return
                        print(f"  [{fk:15s}] 시도{attempt+1} 한국어 부족({ko}자) 재시도")
                except Exception as e:
                    print(f"  [{fk:15s}] 시도{attempt+1} 오류: {e}")
            print(f"  [{fk:15s}] FAIL")

    await asyncio.gather(*[_one(r) for r in rows])
    print("\n[fix-58] 재호출 완료")


if __name__ == "__main__":
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 1222
    asyncio.run(refill(target))
