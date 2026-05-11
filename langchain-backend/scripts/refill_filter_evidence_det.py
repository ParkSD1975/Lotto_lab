# -*- coding: utf-8 -*-
"""[fix-evidence-det] 결정론적 evidence_text 재생성 스크립트.

LLM 없이 synthesize_filter_evidence()로 weekly_filter_predictions.evidence_text를
모든 회차(또는 특정 회차)에 대해 재생성한다.

사용:
    python langchain-backend/scripts/refill_filter_evidence_det.py [--round 1223]
    python langchain-backend/scripts/refill_filter_evidence_det.py --all
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.supabase_client import get_client
from services.filter_narrative import synthesize_filter_evidence, _extract_task_weights


def refill(target_round: int | None = None, all_rounds: bool = False) -> None:
    client = get_client()

    # 대상 회차 결정
    query = client.table("weekly_filter_predictions").select(
        "id, target_round, filter_key, ensemble_min, ensemble_max, "
        "ensemble_ci, filter_value, primary_task, model_expectations"
    )
    if not all_rounds:
        if target_round is None:
            # 최신 회차 자동 결정
            res = client.table("weekly_filter_predictions") \
                .select("target_round") \
                .order("target_round", desc=True) \
                .limit(1) \
                .execute()
            if not res.data:
                print("[ERROR] weekly_filter_predictions 데이터 없음")
                return
            target_round = res.data[0]["target_round"]
            print(f"[refill] 최신 회차 자동 선택: {target_round}")
        query = query.eq("target_round", target_round)

    res = query.execute()
    rows = res.data or []
    print(f"[refill] 대상 {len(rows)}개 필터 행 재생성 시작...")

    updated = 0
    skipped = 0
    for row in rows:
        fk = row["filter_key"]
        rnd = row["target_round"]
        try:
            tw = _extract_task_weights(row)
            user_range_str = str(row.get("filter_value") or "미설정")
            text = synthesize_filter_evidence(
                filter_key=fk,
                ens_min=row.get("ensemble_min"),
                ens_max=row.get("ensemble_max"),
                ensemble_ci=row.get("ensemble_ci"),
                user_range_str=user_range_str,
                task_weights=tw,
            )
            if text and len(text) >= 20:
                client.table("weekly_filter_predictions") \
                    .update({"evidence_text": text}) \
                    .eq("id", row["id"]) \
                    .execute()
                print(f"  [{rnd}] [{fk:20s}] OK ({len(text)}자): {text[:80]}...")
                updated += 1
            else:
                print(f"  [{rnd}] [{fk:20s}] SKIP (텍스트 너무 짧음)")
                skipped += 1
        except Exception as e:
            print(f"  [{rnd}] [{fk:20s}] ERROR: {e}")
            skipped += 1

    print(f"\n[refill] 완료: 업데이트 {updated}개, 스킵 {skipped}개")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--round", type=int, default=None, help="대상 회차 (생략 시 최신)")
    parser.add_argument("--all", action="store_true", help="전체 회차 재생성")
    args = parser.parse_args()
    refill(target_round=args.round, all_rounds=args.all)
