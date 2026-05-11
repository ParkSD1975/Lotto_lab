# -*- coding: utf-8 -*-
"""model_predictions 테이블 backfill 스크립트.

최신 회차 1222에 대해 ensemble.predict_top5를 호출하고,
각 모델의 top10을 model_predictions 테이블에 저장.
"""

from __future__ import annotations

import argparse
import os
import sys

# langchain-backend 패키지 import
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.supabase_client import fetch_all_draws, get_client
from models.ensemble import LottoEnsemble


def backfill_latest_round(n_rounds: int = 1, start_round: int | None = None) -> dict:
    """N회차에 대해 model_predictions backfill (walk-forward).

    Args:
        n_rounds: backfill할 회차 수
        start_round: 시작 회차 번호 (None이면 최신부터). hold-out 검증용 — 학습 cutoff 이전 회차로 backfill

    Returns:
        {"success": bool, "rounds_processed": list, "total_saved": int}
    """
    if start_round is not None:
        print(f"[backfill] start - {n_rounds} rounds from round {start_round} (hold-out mode)")
    else:
        print(f"[backfill] start - latest {n_rounds} rounds backfill")

    # 1. 데이터 로드
    draws = fetch_all_draws()
    if not draws:
        return {
            "success": False,
            "error": "No draws data",
            "rounds_processed": [],
            "total_saved": 0,
        }

    print(f"[backfill] fetch_all_draws: {len(draws)} rounds")

    # round desc 정렬 가정 → start_round 지정 시 그 회차부터 N개 (회차 desc로)
    if start_round is not None:
        target_draws = [d for d in draws if int(d.get("round", 0)) <= start_round][:n_rounds]
    else:
        target_draws = draws[:n_rounds]
    rounds_processed = []
    total_saved = 0

    # 2. Ensemble 초기화 (자동 로드)
    try:
        ensemble = LottoEnsemble()
        print("[backfill] LottoEnsemble initialized")
    except Exception as e:
        return {
            "success": False,
            "error": f"ensemble init failed: {e}",
            "rounds_processed": [],
            "total_saved": 0,
        }

    # 3. 각 회차별로 predict_top5 호출 + DB 저장
    for target_draw in target_draws:
        round_num = int(target_draw.get("round", 0))
        if round_num == 0:
            continue

        print(f"\n[backfill] processing round {round_num}...")

        # 해당 회차보다 이전 데이터만 사용 (walk-forward)
        historical = [d for d in draws if int(d.get("round", 0)) < round_num]

        if len(historical) < 10:
            print(f"[backfill] round {round_num}: insufficient data ({len(historical)} rounds) - skip")
            continue

        try:
            # predict_top5 with save_predictions=True
            result = ensemble.predict_top5(
                draws=historical,
                n_top=5,
                round_number=round_num,
                save_predictions=True,
            )

            save_info = result.get("model_predictions_saved", {})
            if save_info.get("success"):
                saved_count = save_info.get("saved_count", 0)
                models = save_info.get("models", [])
                print(
                    f"[backfill] round {round_num}: {saved_count} models saved - "
                    f"{', '.join(models)}"
                )
                rounds_processed.append(round_num)
                total_saved += saved_count
            else:
                error = save_info.get("error", "unknown")
                print(f"[backfill] round {round_num}: save failed - {error}")

        except Exception as e:
            print(f"[backfill] round {round_num}: exception - {type(e).__name__}: {e}")
            continue

    return {
        "success": len(rounds_processed) > 0,
        "rounds_processed": rounds_processed,
        "total_saved": total_saved,
        "n_rounds": n_rounds,
    }


def verify_saved_predictions(round_number: int) -> dict:
    """저장된 model_predictions 검증.

    Args:
        round_number: 검증할 회차 번호

    Returns:
        {"count": int, "models": list, "records": list}
    """
    try:
        client = get_client()
        result = (
            client.table("model_predictions")
            .select("*")
            .eq("round_number", round_number)
            .execute()
        )

        records = result.data or []
        models = [r["model_name"] for r in records]

        return {
            "count": len(records),
            "models": models,
            "records": records,
        }
    except Exception as e:
        return {
            "count": 0,
            "models": [],
            "error": str(e),
        }


def main():
    parser = argparse.ArgumentParser(description="model_predictions backfill")
    parser.add_argument(
        "--rounds",
        type=int,
        default=1,
        help="backfill할 회차 수 (기본 1)",
    )
    parser.add_argument(
        "--start-round",
        type=int,
        default=None,
        help="시작 회차 (이 회차부터 desc로 N개). 미지정 시 최신부터. hold-out 검증용",
    )
    parser.add_argument(
        "--verify",
        type=int,
        default=None,
        help="특정 회차 검증 (backfill 대신)",
    )

    args = parser.parse_args()

    if args.verify is not None:
        # 검증 모드
        print(f"\n[verify] round {args.verify} model_predictions verification")
        verify_result = verify_saved_predictions(args.verify)

        if "error" in verify_result:
            print(f"[verify] error: {verify_result['error']}")
            return 1

        count = verify_result["count"]
        models = verify_result["models"]

        print(f"[verify] saved records: {count}")
        print(f"[verify] models: {', '.join(models)}")

        for record in verify_result["records"][:3]:  # 처음 3개만 출력
            print(
                f"  - {record['model_name']}: "
                f"top10={record['predicted_top10'][:5]}..."
            )

        return 0

    # Backfill 모드
    result = backfill_latest_round(n_rounds=args.rounds, start_round=args.start_round)

    if result["success"]:
        print(
            f"\n[backfill] SUCCESS: "
            f"{len(result['rounds_processed'])} rounds processed, "
            f"{result['total_saved']} records saved"
        )
        print(f"[backfill] processed rounds: {result['rounds_processed']}")
        return 0
    else:
        print(f"\n[backfill] FAILED: {result.get('error', 'unknown')}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
