"""Stage 6 통합 검증 — 전체 파이프라인 200회차 walk-forward.

Master Plan Stage 6. predictor_pipeline + ensemble + scorer + recommender +
xai_explainer + narrative 전체 chain 200회차 검증.

검증 항목:
  - 22 predictor 학습 + 추론 정상
  - 4 Pillar 점수 + Hard Filter 3계층 동작
  - 추천 5 평균 hit / 제외 10 평균 hit (목표: 2~3 / 0~1)
  - SLA 내 학습/추론 시간 (config.SLA_*)
  - Stage 0~4 모든 검증 게이트 통과
"""

from __future__ import annotations

import json
import os
import time
from typing import Optional

import numpy as np

import config


# ────── 가짜 데이터 (smoke) ──────


def _make_synthetic_draws(n_rounds: int = 220, seed: Optional[int] = None) -> list[dict]:
    """smoke용 합성 회차 데이터."""
    rng = np.random.default_rng(seed if seed is not None else config.RANDOM_SEED)
    draws = []
    for r in range(n_rounds, 0, -1):
        nums = sorted(rng.choice(45, size=6, replace=False) + 1)
        bonus = int(rng.integers(1, 46))
        while bonus in nums:
            bonus = int(rng.integers(1, 46))
        draws.append({"round": int(r), "numbers": [int(n) for n in nums], "bonus": int(bonus)})
    return draws


# ────── 통합 테스트 ──────


class IntegrationTest:
    """Stage 6 통합 검증 진입점."""

    def __init__(self, window: int = 200):
        self.window = window
        self.results: dict = {}
        self.timings: dict = {}

    def run_all(self, draws: list[dict]) -> dict:
        """전체 통합 테스트. 각 단계별 타임 측정."""
        print(f"[IntegrationTest] start (window={self.window}, n_draws={len(draws)})")
        t0 = time.time()

        # Stage 1~2: predictor_pipeline 학습 + 추론
        self._test_predictor_pipeline(draws)

        # Stage 3-A: ModelRankExtractor + ConsensusAnalyzer
        rankings = self._test_model_rank_extractor()

        # Stage 3-A: ConsensusAnalyzer
        consensus_metrics = self._test_consensus_analyzer(rankings)

        # Stage 3-B: NumberScorer
        scores = self._test_number_scorer(consensus_metrics)

        # Stage 3-C: NumberRecommender
        rec_result = self._test_number_recommender(
            scores=scores,
            consensus_metrics=consensus_metrics,
            rankings=rankings,
        )

        # Stage 4: NumberXAIExplainer
        xai_out = self._test_xai_explainer(
            rec_result=rec_result,
            consensus_metrics=consensus_metrics,
        )

        # Stage 4-B: narrative
        self._test_narrative(xai_out)

        # Stage 6: RecommendationBacktest window=200
        self._test_backtest(draws)

        self.results["wall_time_total"] = time.time() - t0
        self.results["timings"] = self.timings
        self.results["stages_passed"] = self._summarize_stages()

        return self.results

    # ────── Stage별 테스트 ──────

    def _test_predictor_pipeline(self, draws: list[dict]) -> None:
        from predictors.predictor_pipeline import PredictorPipeline

        t0 = time.time()
        try:
            pipeline = PredictorPipeline(feature_dim=24)
            train_results = pipeline.train(draws[: self.window], min_history=50)
            predict_results = pipeline.predict_all(draws[: self.window // 2])

            self.pipeline = pipeline
            self.predict_results = predict_results
            self.results["stage_1_2"] = {
                "status": "ok",
                "phase1_n_predictors": len(pipeline.phase1.predictors),
                "phase2_trained": pipeline.endings is not None,
                "phase3_trained": pipeline.ac is not None,
                "phase4_trained": pipeline.sum_pred is not None,
                "regression_trained": pipeline.regression is not None,
                "regression_meta_trained": pipeline.regression_meta is not None,
            }
        except Exception as e:
            self.results["stage_1_2"] = {"status": "fail", "error": str(e)}
        self.timings["stage_1_2_predictor_pipeline"] = time.time() - t0

    def _test_model_rank_extractor(self) -> dict:
        from models.model_rank_extractor import ModelRankExtractor

        t0 = time.time()
        try:
            # 가짜 11 base prob (실제 ensemble 출력 자리)
            rng = np.random.default_rng(config.RANDOM_SEED)
            model_outputs = {}
            for name in ("xgboost", "catboost", "tabnet", "cnn", "gnn",
                         "markov", "autoencoder", "tft", "nbeats", "mhn", "bayesian_nn"):
                probs = rng.dirichlet(np.ones(45))
                model_outputs[name] = {n + 1: float(probs[n]) for n in range(45)}

            extractor = ModelRankExtractor()
            rankings = extractor.extract_rankings(model_outputs)
            slices = extractor.slice_by_ranges(rankings)
            consensus = extractor.consensus_within_slice(rankings, (1, 9))

            self.results["stage_3_A_rank"] = {
                "status": "ok",
                "n_models": len(rankings),
                "n_slices": len(next(iter(slices.values()))),
                "rank_1_9_intersection_size": len(consensus.get("intersection", [])),
                "rank_1_9_strength": consensus.get("consensus_strength"),
            }
            return rankings
        except Exception as e:
            self.results["stage_3_A_rank"] = {"status": "fail", "error": str(e)}
            return {}
        finally:
            self.timings["stage_3_A_rank"] = time.time() - t0

    def _test_consensus_analyzer(self, rankings: dict) -> dict:
        from models.consensus_analyzer import ConsensusAnalyzer

        t0 = time.time()
        try:
            analyzer = ConsensusAnalyzer()
            metrics = analyzer.compute_metrics(rankings)
            scores = analyzer.compute_consensus_score(metrics)
            features = analyzer.to_pillar4_features(metrics)

            top10_distribution = [m.get("top10_count", 0) for m in metrics.values()]
            self.results["stage_3_A_consensus"] = {
                "status": "ok",
                "n_numbers": len(metrics),
                "features_shape": list(features.shape),
                "max_top10_count": max(top10_distribution) if top10_distribution else 0,
                "mean_consensus_score": float(np.mean(list(scores.values()))) if scores else 0.0,
            }
            return metrics
        except Exception as e:
            self.results["stage_3_A_consensus"] = {"status": "fail", "error": str(e)}
            return {}
        finally:
            self.timings["stage_3_A_consensus"] = time.time() - t0

    def _test_number_scorer(self, consensus_metrics: dict) -> dict:
        from models.number_scorer import NumberScorer

        t0 = time.time()
        try:
            scorer = NumberScorer()
            # 가짜 ensemble probs
            ensemble_probs = {n: 1 / 45 for n in range(1, 46)}
            scores = scorer.score_numbers(
                ensemble_probs=ensemble_probs,
                filter_stats_result=None,
                predictor_pipeline_outputs=None,
                consensus_metrics=consensus_metrics,
                draws_so_far=[],
            )
            self.scorer = scorer
            self.results["stage_3_B_scorer"] = {
                "status": "ok",
                "n_scored": len(scores),
                "score_range": [float(min(scores.values())), float(max(scores.values()))],
            }
            return scores
        except Exception as e:
            self.results["stage_3_B_scorer"] = {"status": "fail", "error": str(e)}
            return {}
        finally:
            self.timings["stage_3_B_scorer"] = time.time() - t0

    def _test_number_recommender(
        self, scores: dict, consensus_metrics: dict, rankings: dict
    ) -> dict:
        from models.number_recommender import NumberRecommender

        t0 = time.time()
        try:
            recommender = NumberRecommender(scorer=self.scorer)
            ensemble_probs = {n: 1 / 45 for n in range(1, 46)}
            result = recommender.recommend(
                final_probs=ensemble_probs,
                filter_stats_result={},
                predictor_pipeline_outputs={},
                rankings=rankings,
                expert_memo={"forced_includes": [3], "forced_excludes": [42]},
            )
            self.recommender = recommender
            self.results["stage_3_C_recommender"] = {
                "status": "ok",
                "n_recommendations": len(result.get("recommendations", [])),
                "n_exclusions": len(result.get("exclusions", [])),
                "memo_active": result.get("metadata", {}).get("memo_active"),
                "exclude_reason_distribution": _count_reasons(result.get("exclusions", [])),
            }
            return result
        except Exception as e:
            self.results["stage_3_C_recommender"] = {"status": "fail", "error": str(e)}
            return {}
        finally:
            self.timings["stage_3_C_recommender"] = time.time() - t0

    def _test_xai_explainer(
        self, rec_result: dict, consensus_metrics: dict
    ) -> dict:
        from models.number_xai_explainer import NumberXAIExplainer

        t0 = time.time()
        try:
            explainer = NumberXAIExplainer()
            xai_out = explainer.explain_all(
                recommendations=rec_result.get("recommendations", []),
                exclusions=rec_result.get("exclusions", []),
                consensus_metrics=consensus_metrics,
                filter_compliance=np.random.default_rng(42).random(45),
            )
            self.results["stage_4_A_xai"] = {
                "status": "ok",
                "n_recs_explained": len(xai_out.get("recommendations", [])),
                "n_excs_explained": len(xai_out.get("exclusions", [])),
                "global_summary": xai_out.get("global_summary"),
            }
            return xai_out
        except Exception as e:
            self.results["stage_4_A_xai"] = {"status": "fail", "error": str(e)}
            return {}
        finally:
            self.timings["stage_4_A_xai"] = time.time() - t0

    def _test_narrative(self, xai_out: dict) -> None:
        from services.number_narrative import generate_batch as gen_number_batch
        from services.page_narrative import generate_page_narrative

        t0 = time.time()
        try:
            number_narratives = gen_number_batch(
                xai_out.get("recommendations", []) + xai_out.get("exclusions", []),
                fallback=True,
            )
            page_narrative = generate_page_narrative(
                {
                    "indicator_name": "총합",
                    "recent_stats": {"rolling_mean_10": 138.5, "rolling_std_10": 28.3},
                    "ml_prediction": {"q10": 110.0, "q50": 138.0, "q90": 168.0},
                    "consensus": "강",
                },
                fallback=True,
            )
            self.results["stage_4_B_narrative"] = {
                "status": "ok",
                "n_number_narratives": len(number_narratives),
                "page_narrative_keys": list(page_narrative.get("narrative", {}).keys()),
            }
        except Exception as e:
            self.results["stage_4_B_narrative"] = {"status": "fail", "error": str(e)}
        self.timings["stage_4_B_narrative"] = time.time() - t0

    def _test_backtest(self, draws: list[dict]) -> None:
        from validation.recommendation_backtest import RecommendationBacktest

        t0 = time.time()
        try:
            backtest = RecommendationBacktest(
                scorer=getattr(self, "scorer", None),
                recommender=getattr(self, "recommender", None),
                window=self.window,
            )
            bt_result = backtest.run(draws, retrain_every=0)
            self.results["stage_6_backtest"] = {
                "status": "ok",
                "n_rounds_evaluated": bt_result.get("n_rounds_evaluated"),
                "avg_rec_hit": bt_result.get("avg_rec_hit"),
                "avg_exc_hit": bt_result.get("avg_exc_hit"),
                "pillar_contributions": bt_result.get("pillar_contributions"),
                "exclude_reason_distribution": bt_result.get("exclude_reason_distribution"),
                "safety_check": backtest.safety_check(bt_result),
            }
        except Exception as e:
            self.results["stage_6_backtest"] = {"status": "fail", "error": str(e)}
        self.timings["stage_6_backtest"] = time.time() - t0

    def _summarize_stages(self) -> dict:
        passed = []
        failed = []
        for k, v in self.results.items():
            if not isinstance(v, dict):
                continue
            if v.get("status") == "ok":
                passed.append(k)
            elif v.get("status") == "fail":
                failed.append({"stage": k, "error": v.get("error")})
        return {
            "passed": passed,
            "failed": failed,
            "total": len(passed) + len(failed),
            "pass_rate": len(passed) / max(1, len(passed) + len(failed)),
        }

    # ────── 보고서 ──────

    def report(self) -> str:
        lines = []
        sep = "=" * 70
        lines.append(sep)
        lines.append("Stage 6 INTEGRATION TEST REPORT")
        lines.append(sep)
        lines.append(f"  window: {self.window}")
        lines.append(f"  total wall time: {self.results.get('wall_time_total', 0):.2f}s")

        stages = self.results.get("stages_passed", {})
        lines.append(f"\n  stages passed: {len(stages.get('passed', []))} / {stages.get('total', 0)}")
        lines.append(f"  pass rate: {stages.get('pass_rate', 0)*100:.1f}%")

        lines.append("\n  TIMINGS:")
        for k, v in self.timings.items():
            lines.append(f"    {k:40s} = {v:.2f}s")

        # 핵심 메트릭
        bt = self.results.get("stage_6_backtest", {})
        if bt.get("status") == "ok":
            lines.append("\n  STAGE 6 BACKTEST:")
            lines.append(f"    avg_rec_hit (target 2~3): {bt.get('avg_rec_hit', 0):.4f}")
            lines.append(f"    avg_exc_hit (target 0~1): {bt.get('avg_exc_hit', 0):.4f}")
            sc = bt.get("safety_check", {})
            lines.append(f"    safety_check: safe={sc.get('safe')}, warnings={len(sc.get('warnings', []))}")

        # 실패 stage
        if stages.get("failed"):
            lines.append("\n  FAILED STAGES:")
            for f in stages["failed"]:
                lines.append(f"    - {f['stage']}: {f['error']}")

        # SLA 체크
        infer_total = sum(
            v for k, v in self.timings.items()
            if "predictor_pipeline" in k or "scorer" in k or "recommender" in k
        )
        lines.append(f"\n  SLA CHECK:")
        lines.append(f"    inference time: {infer_total:.2f}s (limit {config.SLA_INFER_WALL_TIME_MAX}s)")
        lines.append(f"    sla_pass: {infer_total <= config.SLA_INFER_WALL_TIME_MAX}")

        lines.append(sep)
        return "\n".join(lines)


def _count_reasons(exclusions: list) -> dict:
    counts = {}
    for e in exclusions or []:
        r = e.get("exclude_reason", "unknown")
        counts[r] = counts.get(r, 0) + 1
    return counts


def main():
    """smoke: 220 회차 합성 데이터로 전체 통합 테스트."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--window", type=int, default=200)
    parser.add_argument("--n_rounds", type=int, default=220)
    parser.add_argument("--save_json", type=str, default=None)
    args = parser.parse_args()

    if args.smoke:
        draws = _make_synthetic_draws(n_rounds=args.n_rounds)
        test = IntegrationTest(window=args.window)
        test.run_all(draws)
        print(test.report())

        if args.save_json:
            with open(args.save_json, "w", encoding="utf-8") as f:
                json.dump(test.results, f, ensure_ascii=False, indent=2, default=str)
            print(f"\n[saved] {args.save_json}")


if __name__ == "__main__":
    main()
