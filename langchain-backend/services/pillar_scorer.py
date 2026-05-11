"""
[P5 PATCH 옵션 A] 4-Pillar Consensus Scorer

CNS / ENS / FLT / STA 점수 계산 + recommendation_backtest_runs 저장.

근거: Lotto_lab_Root_Cause_Diagnosis.md (Finding #1)
       pillar_scores 50회 모두 동일 더미값, 4-Pillar 코드 미존재
       MASTER_PLAN.md 결정 #25

패치 일자: 2026-05-11

Pillar 정의:
  CNS — Consensus Strength: 1 / (1 + avg_std_rank/10)
  ENS — Ensemble Probability: top-10 avg_prob / natural_freq - 1, clip [0,1]
  FLT — Filter Compliance: passed_filters / total_verified_filters
  STA — Stability: prev 5 rounds top_5와 평균 overlap
"""
from __future__ import annotations

import logging
import statistics
from typing import Any

from db.supabase_client import get_client

logger = logging.getLogger("PillarScorer")


# 11-base 모델 _rank 컬럼 (LSTM/Transformer archive 처리됨)
MODEL_RANK_COLUMNS: list[str] = [
    "xgboost_rank", "catboost_rank", "tabnet_rank",
    "cnn_rank", "gnn_rank", "markov_rank",
    "autoencoder_rank", "tft_rank", "mhn_rank", "bayesian_nn_rank",
    # "nbeats_rank",   # C3 패치 후 추가
]


def compute_cns(rows: list[dict]) -> float:
    """CNS — Consensus Strength.

    11개 모델 간 rank의 표준편차 평균. 작을수록 합의 강함.
    정규화: 1 / (1 + avg_std/10) → [0, 1]
    """
    if not rows:
        return 0.0

    rank_stds = []
    for row in rows:
        ranks = []
        for col in MODEL_RANK_COLUMNS:
            v = row.get(col)
            if v is not None:
                try:
                    ranks.append(int(v))
                except (ValueError, TypeError):
                    continue
        if len(ranks) >= 2:
            rank_stds.append(statistics.stdev(ranks))

    if not rank_stds:
        return 0.0

    avg_std = statistics.mean(rank_stds)
    return round(1 / (1 + avg_std / 10), 4)


def compute_ens(rows: list[dict], top_n: int = 10) -> float:
    """ENS — Ensemble Probability.

    상위 N개 번호의 평균 probability. 자연 평균(0.022) 대비 lift.
    정규화: avg_prob / 0.022 - 1, clipped to [0, 1]
    """
    if not rows:
        return 0.0

    probs = []
    for row in rows:
        v = row.get("probability")
        if v is not None:
            try:
                probs.append(float(v))
            except (ValueError, TypeError):
                continue

    if not probs:
        return 0.0

    probs.sort(reverse=True)
    top_probs = probs[:top_n]
    avg_top = sum(top_probs) / len(top_probs)

    natural = 1 / 45
    lift = (avg_top / natural) - 1.0

    return round(max(0.0, min(1.0, lift)), 4)


def compute_flt(target_round: int, supabase) -> float:
    """FLT — Filter Compliance Rate."""
    try:
        response = supabase.table("weekly_filter_predictions") \
            .select("filter_key, in_range") \
            .eq("target_round", target_round) \
            .execute()

        rows = response.data or []
        if not rows:
            return 0.0

        verified_rows = [r for r in rows if r.get("in_range") is not None]
        if not verified_rows:
            # 미검증 회차 — 0.5 반환 (중립)
            return 0.5

        pass_count = sum(1 for r in verified_rows if r["in_range"] is True)
        return round(pass_count / len(verified_rows), 4)

    except Exception as e:
        logger.warning(f"  [PillarScorer.compute_flt] FAILED: {e}")
        return 0.0


def compute_sta(target_round: int, supabase, lookback: int = 5) -> float:
    """STA — Stability Over Time.

    직전 N회의 top_5와 현재 top_5의 평균 overlap.
    """
    try:
        cur_response = supabase.table("weekly_predictions") \
            .select("top_5") \
            .eq("target_round", target_round) \
            .execute()

        if not cur_response.data:
            return 0.0

        current_top5 = set(cur_response.data[0].get("top_5") or [])
        if not current_top5:
            return 0.0

        prev_response = supabase.table("weekly_predictions") \
            .select("target_round, top_5") \
            .lt("target_round", target_round) \
            .order("target_round", desc=True) \
            .limit(lookback) \
            .execute()

        prev_rounds = prev_response.data or []
        if not prev_rounds:
            return 0.0

        overlaps = []
        for prev in prev_rounds:
            prev_top5 = set(prev.get("top_5") or [])
            if prev_top5:
                overlap = len(current_top5 & prev_top5) / 5.0
                overlaps.append(overlap)

        if not overlaps:
            return 0.0

        return round(sum(overlaps) / len(overlaps), 4)

    except Exception as e:
        logger.warning(f"  [PillarScorer.compute_sta] FAILED: {e}")
        return 0.0


def compute_pillar_scores(target_round: int) -> dict[str, float]:
    """4-Pillar 점수 통합 계산.

    Returns:
        {'CNS': float, 'ENS': float, 'FLT': float, 'STA': float}
    """
    try:
        supabase = get_client()

        select_cols = "number, probability, " + ", ".join(MODEL_RANK_COLUMNS)
        xai_response = supabase.table("weekly_number_xai") \
            .select(select_cols) \
            .eq("target_round", target_round) \
            .execute()

        xai_rows = xai_response.data or []

        cns = compute_cns(xai_rows)
        ens = compute_ens(xai_rows)
        flt = compute_flt(target_round, supabase)
        sta = compute_sta(target_round, supabase)

        scores = {
            "CNS": cns,
            "ENS": ens,
            "FLT": flt,
            "STA": sta,
        }

        logger.info(
            f"  [PillarScorer] target_round={target_round} "
            f"CNS={cns:.4f} ENS={ens:.4f} FLT={flt:.4f} STA={sta:.4f}"
        )

        return scores

    except Exception as e:
        logger.error(f"  [PillarScorer.compute_pillar_scores] FAILED: {e}")
        return {"CNS": 0.0, "ENS": 0.0, "FLT": 0.0, "STA": 0.0}


def save_pillar_scores(target_round: int) -> dict[str, Any]:
    """4-Pillar 점수 계산 후 recommendation_backtest_runs에 저장."""
    try:
        supabase = get_client()
        scores = compute_pillar_scores(target_round)

        response = supabase.table("recommendation_backtest_runs") \
            .update({"pillar_scores": scores}) \
            .eq("target_round", target_round) \
            .execute()

        updated = len(response.data or [])

        return {
            "success": True,
            "scores": scores,
            "updated": updated,
            "error": None,
        }

    except Exception as e:
        logger.error(f"  [PillarScorer.save_pillar_scores] FAILED: {e}")
        return {
            "success": False,
            "scores": {},
            "updated": 0,
            "error": str(e),
        }


def composite_pillar_score(scores: dict) -> float:
    """4-Pillar 가중 종합 (CNS 0.3 + ENS 0.3 + FLT 0.2 + STA 0.2)."""
    return (
        0.3 * float(scores.get("CNS", 0.0))
        + 0.3 * float(scores.get("ENS", 0.0))
        + 0.2 * float(scores.get("FLT", 0.0))
        + 0.2 * float(scores.get("STA", 0.0))
    )


def backfill_all_rounds(start_round: int | None = None,
                        end_round: int | None = None) -> dict[str, Any]:
    """과거 회차 일괄 pillar_scores 계산 + 저장."""
    try:
        supabase = get_client()

        query = supabase.table("recommendation_backtest_runs") \
            .select("target_round")
        if start_round is not None:
            query = query.gte("target_round", start_round)
        if end_round is not None:
            query = query.lte("target_round", end_round)

        response = query.execute()
        all_rounds = sorted(set(r["target_round"] for r in (response.data or [])))

        total = len(all_rounds)
        success = 0
        failed = 0

        logger.info(f"  [PillarScorer.backfill] {total} rounds to process...")
        for i, rnd in enumerate(all_rounds, 1):
            result = save_pillar_scores(rnd)
            if result["success"]:
                success += 1
            else:
                failed += 1

            if i % 10 == 0:
                logger.info(f"  [PillarScorer.backfill] {i}/{total} done")

        return {
            "total_rounds": total,
            "success": success,
            "failed": failed,
        }

    except Exception as e:
        logger.error(f"  [PillarScorer.backfill] FAILED: {e}")
        return {"total_rounds": 0, "success": 0, "failed": 0, "error": str(e)}


# ── 스크립트 직접 실행 ────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Pillar Scorer — compute and save CNS/ENS/FLT/STA")
    parser.add_argument("--round", type=int, default=None, help="단일 회차 처리")
    parser.add_argument("--backfill", action="store_true", help="전체 backfill")
    parser.add_argument("--start", type=int, default=None)
    parser.add_argument("--end", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true", help="DB 저장 없이 계산만")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    if args.backfill:
        result = backfill_all_rounds(args.start, args.end)
        print(f"Backfill: {result}")
    elif args.round:
        if args.dry_run:
            scores = compute_pillar_scores(args.round)
            print(f"Round {args.round} pillar_scores (DRY RUN):")
            print(json.dumps(scores, indent=2))
        else:
            result = save_pillar_scores(args.round)
            print(f"Round {args.round}: {result}")
    else:
        print("Usage:")
        print("  python -m services.pillar_scorer --round 1224")
        print("  python -m services.pillar_scorer --round 1224 --dry-run")
        print("  python -m services.pillar_scorer --backfill --start 1173 --end 1222")
