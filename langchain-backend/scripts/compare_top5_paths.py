"""Phase 2 dry-run: predict_top5 vs NumberRecommender 결과 비교.

사용법:
    python -m scripts.compare_top5_paths --round 1223
    python -m scripts.compare_top5_paths --round 1223 --round 1224
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db.supabase_client import get_client
from models.ensemble import LottoEnsemble
from models.model_rank_extractor import ModelRankExtractor
from models.consensus_analyzer import ConsensusAnalyzer
from models.number_scorer import NumberScorer
from models.number_recommender import NumberRecommender

def _load_draws(supabase, target_round: int) -> list[dict]:
    res = supabase.table("lotto_draws") \
        .select("round, numbers, bonus") \
        .lt("round", target_round) \
        .order("round", desc=True) \
        .limit(200) \
        .execute()
    return [{"round": r["round"], "numbers": r["numbers"], "bonus": r.get("bonus")} for r in (res.data or [])]

def compare(target_round: int) -> dict:
    supabase = get_client()
    draws = _load_draws(supabase, target_round)

    ens = LottoEnsemble()  # 초기화 시 자동 load

    # 기존 경로
    old_result = ens.predict_top5(draws)
    old_top5 = [e["number"] for e in old_result.get("top_numbers", [])][:5]

    # 신규 경로
    result = ens.predict_with_task(draws, task="recommend_top")
    final_probs = result["probabilities"]
    contributions = result["model_contributions"]
    rankings = ModelRankExtractor().extract_rankings(contributions)
    consensus_metrics = ConsensusAnalyzer().compute_metrics(rankings)
    scorer = NumberScorer()
    scores = scorer.score_numbers(
        ensemble_probs=final_probs,
        filter_stats_result=None,
        predictor_pipeline_outputs=None,
        consensus_metrics=consensus_metrics,
        draws_so_far=draws[:20],
    )
    import numpy as np
    filter_compliance = np.full(45, 0.5)  # 간단 fallback
    recommender = NumberRecommender(scorer=scorer)
    recs = recommender.select_recommendations(
        scores=scores,
        consensus_metrics=consensus_metrics,
        filter_compliance=filter_compliance,
        expert_memo=None,
        n_top=5,
        bayesian_sigma=None,
        target_round=target_round,
        draws_so_far=draws,
    )
    new_top5 = [r["number"] for r in recs]

    diff_in = set(new_top5) - set(old_top5)
    diff_out = set(old_top5) - set(new_top5)

    return {
        "target_round": target_round,
        "old_top5": sorted(old_top5),
        "new_top5": sorted(new_top5),
        "diff_added": sorted(diff_in),
        "diff_removed": sorted(diff_out),
        "overlap": len(set(old_top5) & set(new_top5)),
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--round", type=int, action="append", required=True)
    args = parser.parse_args()
    for r in args.round:
        result = compare(r)
        print(json.dumps(result, indent=2, ensure_ascii=False))
