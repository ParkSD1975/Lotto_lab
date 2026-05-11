"""Stage 4-B XAI Simple Test - 모델 로딩 없이 검증."""

import numpy as np
from models.number_xai_explainer import NumberXAIExplainer
from services.xai_aggregator import XAIAggregator
from services.number_narrative import generate_narrative
from services.page_narrative import generate_page_narrative


def main():
    print("="*70)
    print("Stage 4-B XAI Simple Test (no model loading)")
    print("="*70)

    # 1. XAI Aggregator smoke
    print("\n[1/4] XAIAggregator smoke...")
    agg = XAIAggregator()
    xai_out = agg.aggregate_per_number(
        number=23,
        x=np.zeros((1, 65), dtype=np.float32),
    )
    print(f"  OK - aggregated {len(xai_out)} model outputs")

    pillar = agg.aggregate_pillar_breakdown(
        number=23,
        consensus_metrics={
            23: {"top10_count": 7, "bottom15_count": 0, "mean_rank": 5.2,
                 "std_rank": 2.8, "consensus_score": -3.6}
        },
    )
    print(f"  OK - pillar breakdown has {len(pillar)} pillars")

    # 2. NumberXAIExplainer smoke
    print("\n[2/4] NumberXAIExplainer smoke...")
    explainer = NumberXAIExplainer()
    recommendations = [
        {"number": 23, "score": 0.62, "memo_forced": False},
        {"number": 31, "score": 0.58, "memo_forced": True},
    ]
    exclusions = [
        {"number": 42, "score": 0.05, "exclude_reason": "memo", "force_exclude": True},
        {"number": 22, "score": 0.08, "exclude_reason": "regression_consecutive_N12"},
    ]
    consensus_metrics = {
        23: {"top10_count": 7, "bottom15_count": 0, "mean_rank": 5.2,
             "std_rank": 2.8, "consensus_score": -3.6},
        31: {"top10_count": 6, "bottom15_count": 0, "mean_rank": 6.1,
             "std_rank": 3.2, "consensus_score": -4.2},
        42: {"top10_count": 0, "bottom15_count": 7, "mean_rank": 38.5,
             "std_rank": 4.1, "consensus_score": -42.5},
        22: {"top10_count": 1, "bottom15_count": 5, "mean_rank": 32.1,
             "std_rank": 5.5, "consensus_score": -36.8},
    }

    out = explainer.explain_all(
        recommendations=recommendations,
        exclusions=exclusions,
        consensus_metrics=consensus_metrics,
        filter_compliance=np.random.default_rng(42).random(45),
    )

    print(f"  OK - explained {len(out['recommendations'])} recs, {len(out['exclusions'])} excs")

    # 3. NumberNarrative smoke
    print("\n[3/4] NumberNarrative (fallback)...")
    ev_rec = {
        "number": 23,
        "type": "recommend",
        "pillar_1": {"value": 0.62},
        "pillar_2": {"passed_filters": ["sum", "endings"]},
        "pillar_3": {"hotcold": "Warm", "dormancy": 12},
        "pillar_4": {"top10_count": 7, "agreement_strength": "strong"},
        "auto_rule_reason": None,
        "memo_forced_inc": False,
        "memo_forced_exc": False,
    }
    narr = generate_narrative(ev_rec, fallback=True)
    print(f"  OK - narrative signal: {narr['narrative']['signal'][:50]}...")

    # 4. PageNarrative smoke
    print("\n[4/4] PageNarrative (fallback)...")
    page_ev = {
        "indicator_name": "sum",
        "recent_stats": {"rolling_mean_10": 138.5, "rolling_std_10": 28.3},
        "ml_prediction": {"q10": 110.0, "q50": 138.0, "q90": 168.0},
        "consensus": "medium",
    }
    page_narr = generate_page_narrative(page_ev, fallback=True)
    print(f"  OK - page narrative flow: {page_narr['narrative']['flow'][:50]}...")

    print("\n" + "="*70)
    print("All tests passed")
    print("="*70)


if __name__ == "__main__":
    main()
