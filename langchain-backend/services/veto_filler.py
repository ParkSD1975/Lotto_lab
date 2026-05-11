"""
[P4 PATCH] Veto Filler

weekly_number_xai.veto 컬럼 자동 채움.

근거: Lotto_lab_Root_Cause_Diagnosis.md (Finding #5)
       weekly_number_xai.veto 50회 모두 빈 값 → 추천수 5 safe 기반 선정 불가
패치 일자: 2026-05-11

원리:
    11개 모델(_rank 컬럼)에서 각 번호의 순위를 보고,
    rank >= 36 (하위 10) 모델이 일정 개수 이상이면 'exclude' 처리.

값 의미:
    'safe'                 — 어떤 모델도 하위 추천 안 함 (추천 후보)
    'exclude:m1,m2,...'    — 3개 이상 모델이 하위 추천 (강한 제외)
    'neutral:m1,...'       — 1~2개 모델만 하위 추천 (모호)
    NULL                   — 미평가 (legacy 또는 오류)
"""
from __future__ import annotations

import logging
from typing import Any

from db.supabase_client import get_client

logger = logging.getLogger("VetoFiller")


# 11-base 모델의 _rank 컬럼 명세 (LSTM/Transformer는 stage-0에서 archive 처리됨)
MODEL_RANK_COLUMNS: list[tuple[str, str]] = [
    ("xgboost",     "xgboost_rank"),
    ("catboost",    "catboost_rank"),
    ("tabnet",      "tabnet_rank"),
    ("cnn",         "cnn_rank"),
    ("gnn",         "gnn_rank"),
    ("markov",      "markov_rank"),
    ("autoencoder", "autoencoder_rank"),
    ("tft",         "tft_rank"),
    ("mhn",         "mhn_rank"),
    ("bayesian_nn", "bayesian_nn_rank"),
    ("nbeats",      "nbeats_rank"),   # [2026-05-12 결정 B] DB nbeats_rank 컬럼 추가 후 활성
]

# 임계 파라미터
VETO_RANK_THRESHOLD: int = 36     # rank >= 36 = 하위 10개
VETO_MODEL_COUNT_HIGH: int = 3     # 이 이상 모델이 하위 추천 → exclude
VETO_MODEL_COUNT_MID: int = 1      # 이 이상 → neutral


def compute_veto_value(rank_dict: dict[str, int]) -> str:
    """단일 번호의 모델 rank 사전을 받아 veto 값 결정.

    Args:
        rank_dict: {'xgboost': 5, 'catboost': 38, ...}

    Returns:
        'safe' | 'exclude:m1,m2,...' | 'neutral:m1,...'
    """
    veto_models: list[str] = []
    for model_name, rank in rank_dict.items():
        if rank is None:
            continue
        try:
            r = int(rank)
        except (ValueError, TypeError):
            continue
        if r >= VETO_RANK_THRESHOLD:
            veto_models.append(model_name)

    if len(veto_models) >= VETO_MODEL_COUNT_HIGH:
        return "exclude:" + ",".join(sorted(veto_models))
    elif len(veto_models) == 0:
        return "safe"
    else:
        return "neutral:" + ",".join(sorted(veto_models))


def fill_veto_for_round(target_round: int) -> dict[str, Any]:
    """특정 회차의 weekly_number_xai 모든 행에 veto 컬럼 채움.

    Args:
        target_round: 대상 회차

    Returns:
        {success, updated, distribution, error}
    """
    try:
        supabase = get_client()

        rank_columns = [col for (_, col) in MODEL_RANK_COLUMNS]
        select_cols = "id, number, " + ", ".join(rank_columns)

        response = supabase.table("weekly_number_xai") \
            .select(select_cols) \
            .eq("target_round", target_round) \
            .execute()

        rows = response.data or []
        if not rows:
            logger.warning(f"  [VetoFiller] No rows for target_round={target_round}")
            return {
                "success": False,
                "updated": 0,
                "distribution": {},
                "error": "no rows",
            }

        distribution = {"safe": 0, "exclude": 0, "neutral": 0}
        updates = []

        for row in rows:
            rank_dict = {
                model_name: row.get(col_name)
                for (model_name, col_name) in MODEL_RANK_COLUMNS
            }
            veto = compute_veto_value(rank_dict)

            if veto == "safe":
                distribution["safe"] += 1
            elif veto.startswith("exclude:"):
                distribution["exclude"] += 1
            else:
                distribution["neutral"] += 1

            updates.append({"id": row["id"], "veto": veto})

        update_count = 0
        for upd in updates:
            try:
                supabase.table("weekly_number_xai") \
                    .update({"veto": upd["veto"]}) \
                    .eq("id", upd["id"]) \
                    .execute()
                update_count += 1
            except Exception as e:
                logger.warning(f"  [VetoFiller] update fail for id={upd['id']}: {e}")

        logger.info(
            f"  [VetoFiller] target_round={target_round} "
            f"updated={update_count}/{len(rows)} dist={distribution}"
        )

        return {
            "success": True,
            "updated": update_count,
            "distribution": distribution,
            "error": None,
        }

    except Exception as e:
        logger.error(f"  [VetoFiller] FAILED for target_round={target_round}: {e}")
        return {
            "success": False,
            "updated": 0,
            "distribution": {},
            "error": str(e),
        }


def get_safe_numbers(target_round: int, limit: int = 5) -> list[int]:
    """Veto='safe'인 번호 중 probability 상위 N개 반환.

    추천수 5 선정에 활용:
        - 어떤 모델도 거부 안 한 번호만
        - 그 중 종합 확률 가장 높은 N개
    """
    try:
        supabase = get_client()
        response = supabase.table("weekly_number_xai") \
            .select("number, probability") \
            .eq("target_round", target_round) \
            .eq("veto", "safe") \
            .order("probability", desc=True) \
            .limit(limit) \
            .execute()

        return [int(r["number"]) for r in (response.data or [])]
    except Exception as e:
        logger.error(f"  [VetoFiller.get_safe_numbers] FAILED: {e}")
        return []


def backfill_all_rounds(start_round: int | None = None,
                        end_round: int | None = None) -> dict[str, Any]:
    """과거 회차 일괄 veto 채움 (history backfill)."""
    try:
        supabase = get_client()

        query = supabase.table("weekly_number_xai") \
            .select("target_round", count="exact")
        if start_round is not None:
            query = query.gte("target_round", start_round)
        if end_round is not None:
            query = query.lte("target_round", end_round)

        response = query.execute()
        all_rounds = sorted(set(r["target_round"] for r in (response.data or [])))

        total = len(all_rounds)
        success = 0
        failed = 0

        logger.info(f"  [VetoFiller.backfill] {total} rounds to process...")
        for i, rnd in enumerate(all_rounds, 1):
            result = fill_veto_for_round(rnd)
            if result["success"]:
                success += 1
            else:
                failed += 1

            if i % 10 == 0:
                logger.info(f"  [VetoFiller.backfill] {i}/{total} done")

        return {
            "total_rounds": total,
            "success": success,
            "failed": failed,
        }

    except Exception as e:
        logger.error(f"  [VetoFiller.backfill] FAILED: {e}")
        return {"total_rounds": 0, "success": 0, "failed": 0, "error": str(e)}


# ── 스크립트 직접 실행 지원 ────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Veto Filler — fill weekly_number_xai.veto")
    parser.add_argument("--round", type=int, default=None, help="단일 회차 처리")
    parser.add_argument("--backfill", action="store_true", help="전체 회차 backfill")
    parser.add_argument("--start", type=int, default=None, help="backfill 시작 회차")
    parser.add_argument("--end", type=int, default=None, help="backfill 종료 회차")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    if args.backfill:
        result = backfill_all_rounds(args.start, args.end)
        print(f"Backfill: {result}")
    elif args.round:
        result = fill_veto_for_round(args.round)
        print(f"Round {args.round}: {result}")
    else:
        print("Usage:")
        print("  python -m services.veto_filler --round 1224")
        print("  python -m services.veto_filler --backfill")
        print("  python -m services.veto_filler --backfill --start 1173 --end 1222")
