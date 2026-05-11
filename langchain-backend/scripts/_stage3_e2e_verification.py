"""Stage 3 E2E 검증 — target_round 1222 전체 파이프라인.

1. ensemble.predict_top5() → contributions 추출
2. NumberScorer.score_all() → 1~45 final_score
3. ModelRankExtractor.extract() → rankings + consensus_count
4. ConsensusAnalyzer.analyze() → Pillar 4
5. NumberRecommender.select_recommendations() → 추천 5
6. NumberRecommender.select_exclusions() → 제외 10
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np

from db.supabase_client import fetch_all_draws
from models.ensemble import LottoEnsemble
from models.number_scorer import NumberScorer
from models.model_rank_extractor import ModelRankExtractor
from models.consensus_analyzer import ConsensusAnalyzer
from models.number_recommender import NumberRecommender
from predictors.predictor_pipeline import PredictorPipeline


def main():
    print("[Stage 3 E2E] 시작 - target_round=1222\n")

    # 데이터 로드
    draws = fetch_all_draws()
    if not draws:
        print("[E2E] draws 데이터 없음")
        return

    # target_round 1222 찾기
    target_idx = None
    for i, d in enumerate(draws):
        if d.get("round") == 1222:
            target_idx = i
            break

    if target_idx is None:
        print("[E2E] round 1222 찾지 못함")
        return

    # 1222 이전 회차만 사용 (누수 방지)
    draws_before = draws[target_idx + 1 :]
    print(f"  draws before 1222: {len(draws_before)}")

    # 1. Ensemble contributions
    print("\n[1] Ensemble.predict_top5()")
    ens = LottoEnsemble()
    result = ens.predict_top5(
        draws=draws_before,
        n_top=5,
        n_bootstrap=30,
        save_predictions=False,
    )
    model_contributions = result.get("contributions", {})  # 모델별 contributions (올바른 키)
    full_probs = result.get("full_probs", {})
    print(f"    model_contributions: {len(model_contributions)} models")
    print(f"    full_probs: {len(full_probs)} numbers")

    # 2. ModelRankExtractor → rankings
    print("\n[2] ModelRankExtractor.extract_rankings()")
    extractor = ModelRankExtractor()
    rankings = extractor.extract_rankings(model_contributions)
    print(f"    rankings: {len(rankings)} models")
    sample_model = list(rankings.keys())[0] if rankings else None
    if sample_model:
        print(f"    {sample_model} top5: {rankings[sample_model][:5]}")

    # 3. ConsensusAnalyzer → Pillar 4
    print("\n[3] ConsensusAnalyzer.compute_metrics()")
    analyzer = ConsensusAnalyzer()
    consensus_metrics = analyzer.compute_metrics(rankings)
    print(f"    consensus_metrics: {len(consensus_metrics)} numbers")
    # 상위 3개 번호 출력
    sorted_by_score = sorted(
        consensus_metrics.items(), key=lambda kv: kv[1].get("consensus_score", -999), reverse=True
    )
    print(f"    top3 consensus:")
    for n, m in sorted_by_score[:3]:
        print(
            f"      n={n:2d}: score={m['consensus_score']:.2f}, "
            f"mean_rank={m['mean_rank']:.2f}, top10={m['top10_count']}"
        )

    # 4. PredictorPipeline → Phase 출력 (Pillar 2/3 실데이터)
    print("\n[4] PredictorPipeline.predict_all()")
    pipeline = PredictorPipeline(feature_dim=24)

    # Phase 1 predictor 추론 (학습된 가중치 로드)
    # Phase 1 Registry는 자동으로 default predictor 등록 + 학습된 가중치 로드
    try:
        # Phase1Registry.load_all()로 학습된 가중치 로드
        phase1_dir = os.path.join(os.path.dirname(__file__), "..", "saved_models", "phase1")
        pipeline.phase1.load_all(phase1_dir)

        phase1_raw = pipeline.phase1.predict_all(draws_before)
        phase_outputs = {"phase1": phase1_raw}
        print(f"    phase1 predictors: {len(phase1_raw)} predictors")
    except Exception as e:
        print(f"    phase1 predict_all fail: {e}, fallback to empty")
        phase_outputs = {"phase1": {}}

    # Regression predictor 추론 (Tier 1 active_N_set)
    try:
        if pipeline.regression is None:
            from predictors.regression_predictor import DynamicIndependentCountPredictor
            pipeline.regression = DynamicIndependentCountPredictor(feature_dim=24)
            # 학습된 가중치 로드 시도
            regression_path = os.path.join(os.path.dirname(__file__), "..", "saved_models", "regression_predictor.pkl")
            if os.path.exists(regression_path):
                pipeline.regression.load(regression_path)
                print(f"    regression loaded from {regression_path}")
            else:
                print(f"    regression model not found, using untrained fallback")

        regression_output = pipeline.regression.predict(
            draws_so_far=draws_before,
            target_round=1222,
        )
        phase_outputs["regression"] = regression_output
        active_set = regression_output.get("tier1", {}).get("active_N_set", [])
        print(f"    regression active_N_set: {len(active_set)} numbers")
    except Exception as e:
        print(f"    regression predict fail: {e}, fallback to empty")
        phase_outputs["regression"] = {"tier1": {"active_N_set": []}, "tier3_rules": {}}

    # 5. NumberScorer → 4 Pillar + final_score
    print("\n[5] NumberScorer.score_numbers()")
    scorer = NumberScorer()

    # Pillar 2/3 차별화 강화를 위한 임시 가중치 (Ridge 미학습 시 fallback)
    # P1(ensemble) 25% → 15%, P2(filter) 25% → 35%, P3(state) 25% → 35%, P4(consensus) 25% → 15%
    if not scorer._ridge_fitted:
        import numpy as np
        scorer.pillar_weights = np.array([0.15, 0.35, 0.35, 0.15], dtype=np.float64)
        print(f"    임시 Pillar 가중치 설정: {scorer.pillar_weights}")

    final_scores = scorer.score_numbers(
        ensemble_probs=full_probs,
        filter_stats_result=phase_outputs,  # Phase 출력 전달 (Pillar 2 입력)
        predictor_pipeline_outputs=phase_outputs,  # Pillar 3 입력
        consensus_metrics=consensus_metrics,
        draws_so_far=draws_before[:20],
    )

    print(f"    final_scores: {len(final_scores)} numbers")
    sorted_scores = sorted(final_scores.items(), key=lambda kv: kv[1], reverse=True)
    print(f"    top5 final_score:")
    for n, s in sorted_scores[:5]:
        print(f"      n={n:2d}: final={s:.4f}")

    # Pillar 2/3 차별화 검증 (분산 측정)
    mat_4p = scorer.compute_4pillars(
        ensemble_probs=full_probs,
        filter_stats_result=phase_outputs,
        predictor_pipeline_outputs=phase_outputs,
        consensus_metrics=consensus_metrics,
        draws_so_far=draws_before[:20],
    )
    p2_std = float(mat_4p[:, 1].std())
    p3_std = float(mat_4p[:, 2].std())
    print(f"    Pillar 2 (filter_compliance) std = {p2_std:.4f}")
    print(f"    Pillar 3 (individual_state) std = {p3_std:.4f}")

    # 6. NumberRecommender → 추천 5 + 제외 10
    print("\n[6] NumberRecommender.select_recommendations()")
    recommender = NumberRecommender(scorer=scorer)

    # filter_compliance (더미)
    filter_comp = np.full(45, 0.5, dtype=np.float64)

    recs = recommender.select_recommendations(
        scores=final_scores,
        consensus_metrics=consensus_metrics,
        filter_compliance=filter_comp,
        expert_memo=None,
        n_top=5,
        bayesian_sigma=None,
    )

    print(f"    recommendations: {len(recs)} items")
    print(f"    top 5:")
    for item in recs[:5]:
        print(
            f"      n={item['number']:2d}, score={item['score']:.4f}, "
            f"top10={item.get('consensus_top10_count', 0)}"
        )

    print("\n[7] NumberRecommender.select_exclusions()")
    excs = recommender.select_exclusions(
        scores=final_scores,
        consensus_metrics=consensus_metrics,
        filter_compliance=filter_comp,
        regression_rules_output=None,
        expert_memo=None,
        n_exc=10,
        gnn_strong_set=None,
    )

    print(f"    exclusions: {len(excs)} items")
    print(f"    top 3:")
    for item in excs[:3]:
        print(
            f"      n={item['number']:2d}, score={item['score']:.4f}, "
            f"force={item.get('force_exclude', False)}"
        )

    # 실제 정답 (1222 회차)
    actual = draws[target_idx].get("numbers", [])
    print(f"\n[8] 실제 당첨 번호 (1222): {sorted(actual)}")
    rec_nums = [item["number"] for item in recs]
    hit_count = len(set(rec_nums) & set(actual))
    print(f"    추천 5 hit: {hit_count}/5 (목표: 2~3/5)")
    print(f"    추천 번호: {sorted(rec_nums)}")
    print(f"    hit 번호: {sorted(set(rec_nums) & set(actual))}")

    # Pillar 2/3 실데이터 활용 전후 비교 요약
    print(f"\n[9] Pillar 2/3 차별화 요약:")
    print(f"    P2 std = {p2_std:.4f} (더미 0.5 대비 차별화 정도)")
    print(f"    P3 std = {p3_std:.4f}")
    print(f"    추천 번호 분산: {sorted(rec_nums)} (이전 [1,2,3,4,5] 단순 ranking 탈피)")

    print("\n[Stage 3 E2E] 완료")


if __name__ == "__main__":
    main()
