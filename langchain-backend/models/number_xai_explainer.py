"""NumberXAIExplainer — 다층 XAI 출력 통합. NumberRecommender 직후 호출.

Master Plan Stage 4-A. 추천 5 + 제외 10 각 번호별 Layer 1/2/3 XAI 산출.
Layer 1 (narrative)은 Stage 4-B Gemma 4 합성. Layer 2 (Pillar 게이지) + Layer 3
(11 base XAI)은 본 모듈에서 직접 산출.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from services.xai_aggregator import XAIAggregator


class NumberXAIExplainer:
    """11 base XAI + 4 Pillar 분해 + 21지표 통과도 통합."""

    def __init__(
        self,
        aggregator: Optional[XAIAggregator] = None,
        scorer=None,
        recommender=None,
    ):
        self.aggregator = aggregator or XAIAggregator()
        self.scorer = scorer
        self.recommender = recommender

    # ────── 단일 번호 explain ──────

    def explain_number(
        self,
        number: int,
        type: str,
        recommendation_or_exclusion: dict,
        scorer_metrics: Optional[dict] = None,
        consensus_metrics: Optional[dict] = None,
        model_outputs: Optional[dict] = None,
        predictor_pipeline_outputs: Optional[dict] = None,
        filter_compliance: Optional[np.ndarray] = None,
        x_features: Optional[np.ndarray] = None,
        scalar_series: Optional[np.ndarray] = None,
    ) -> dict:
        """단일 번호 3 layer XAI."""
        rec_or_exc = recommendation_or_exclusion or {}

        # Layer 3: 11 base XAI
        layer_3 = self.aggregator.aggregate_per_number(
            number=number,
            x=x_features,
            scalar_series=scalar_series,
        )

        # Layer 2: 4 Pillar 게이지 (0~1 정규화)
        pillar_breakdown = self.aggregator.aggregate_pillar_breakdown(
            number=number,
            scorer_metrics=scorer_metrics,
            recommender_evidence=rec_or_exc,
            consensus_metrics=consensus_metrics,
            filter_compliance=filter_compliance,
        )
        layer_2 = self._pillar_gauges(pillar_breakdown)

        # Layer 1: narrative seed (Stage 4-B Gemma 4 입력)
        layer_1 = self._narrative_seed(
            number=number,
            type=type,
            rec_or_exc=rec_or_exc,
            pillar_breakdown=pillar_breakdown,
            layer_3=layer_3,
        )

        # Auto rule + memo signals
        auto_rule_triggers = []
        if type == "exclude":
            reason = rec_or_exc.get("exclude_reason", "")
            if reason and reason != "memo" and reason != "pillar_score_low":
                auto_rule_triggers.append({"reason": reason, "force_exclude": True})

        memo_signals = {
            "forced_inc": bool(rec_or_exc.get("memo_forced", False)) and type == "recommend",
            "forced_exc": rec_or_exc.get("exclude_reason") == "memo",
            "confidence": (rec_or_exc.get("memo_confidence")
                           if "memo_confidence" in rec_or_exc else None),
        }

        return {
            "number": int(number),
            "type": type,
            "layer_1_narrative": layer_1,
            "layer_2_pillar_gauges": layer_2,
            "layer_3_contributions": layer_3,
            "pillar_breakdown": pillar_breakdown,
            "auto_rule_triggers": auto_rule_triggers,
            "memo_signals": memo_signals,
        }

    # ────── 추천/제외 통합 explain ──────

    def explain_all(
        self,
        recommendations: list[dict],
        exclusions: list[dict],
        scorer_metrics: Optional[dict] = None,
        consensus_metrics: Optional[dict] = None,
        model_outputs: Optional[dict] = None,
        predictor_pipeline_outputs: Optional[dict] = None,
        filter_compliance: Optional[np.ndarray] = None,
        x_features: Optional[np.ndarray] = None,
        scalar_series: Optional[np.ndarray] = None,
    ) -> dict:
        """추천 5 + 제외 10 통합 explain + global summary."""
        rec_explained = []
        for r in (recommendations or []):
            try:
                rec_explained.append(
                    self.explain_number(
                        number=int(r["number"]),
                        type="recommend",
                        recommendation_or_exclusion=r,
                        scorer_metrics=scorer_metrics,
                        consensus_metrics=consensus_metrics,
                        model_outputs=model_outputs,
                        predictor_pipeline_outputs=predictor_pipeline_outputs,
                        filter_compliance=filter_compliance,
                        x_features=x_features,
                        scalar_series=scalar_series,
                    )
                )
            except Exception as e:
                rec_explained.append({"number": r.get("number"), "error": str(e)})

        exc_explained = []
        for e in (exclusions or []):
            try:
                exc_explained.append(
                    self.explain_number(
                        number=int(e["number"]),
                        type="exclude",
                        recommendation_or_exclusion=e,
                        scorer_metrics=scorer_metrics,
                        consensus_metrics=consensus_metrics,
                        model_outputs=model_outputs,
                        predictor_pipeline_outputs=predictor_pipeline_outputs,
                        filter_compliance=filter_compliance,
                        x_features=x_features,
                        scalar_series=scalar_series,
                    )
                )
            except Exception as exc_err:
                exc_explained.append({"number": e.get("number"), "error": str(exc_err)})

        return {
            "recommendations": rec_explained,
            "exclusions": exc_explained,
            "global_summary": self._global_summary(rec_explained, exc_explained),
        }

    # ────── Layer 2: Pillar 게이지 (0~1 정규화) ──────

    def _pillar_gauges(self, pillar_breakdown: dict) -> dict:
        ens = pillar_breakdown.get("pillar_1_ensemble_prob", {}).get("value")
        flt = pillar_breakdown.get("pillar_2_filter_compliance", {}).get("value")
        # Pillar 3은 직접 정규화 어려움 (혼합 시그널) — 임시 0.5 (Stage 1-5 검증 후 정밀화)
        sta = 0.5
        cns_obj = pillar_breakdown.get("pillar_4_consensus", {})
        cns_score = cns_obj.get("consensus_score", 0)
        # consensus_score 범위 약 -50 ~ 5 → 0~1 sigmoid
        cns = float(1.0 / (1.0 + np.exp(-cns_score / 10.0))) if cns_score else 0.5

        return {
            "ENS": float(ens) if ens is not None else 0.5,
            "FLT": float(flt) if flt is not None else 0.5,
            "STA": float(sta),
            "CNS": float(cns),
            "consensus_strength_visual": cns_obj.get("agreement_strength", "보통"),
        }

    # ────── Layer 1: narrative seed (Gemma 4 입력) ──────

    def _narrative_seed(
        self,
        number: int,
        type: str,
        rec_or_exc: dict,
        pillar_breakdown: dict,
        layer_3: dict,
    ) -> dict:
        """Stage 4-B Gemma 4가 받을 evidence dict — 시그널/근거/결론 합성용."""
        cns = pillar_breakdown.get("pillar_4_consensus", {})
        flt = pillar_breakdown.get("pillar_2_filter_compliance", {})
        sta = pillar_breakdown.get("pillar_3_individual_state", {})

        # 시그널: 가장 강한 단일 신호 (top10_count 또는 ensemble rank)
        strongest_signal = None
        if cns.get("top10_count", 0) >= 5:
            strongest_signal = f"7 모델 중 {cns['top10_count']}개가 상위 10위 합의"
        elif cns.get("bottom15_count", 0) >= 5:
            strongest_signal = f"7 모델 중 {cns['bottom15_count']}개가 하위 15위 합의"
        else:
            ens_rank = rec_or_exc.get("score") or rec_or_exc.get("rank")
            if ens_rank:
                strongest_signal = f"앙상블 점수 {ens_rank:.3f} 수준"

        # 근거: filter_compliance 통과 + 활성 신호
        passed_filters = flt.get("passed_filters", [])
        failed_filters = flt.get("failed_filters", [])
        rationale_parts = []
        if passed_filters:
            rationale_parts.append(f"필터 {len(passed_filters)}개 통과")
        if sta.get("hotcold"):
            rationale_parts.append(f"핫콜드 {sta['hotcold']}")
        if sta.get("dormancy"):
            rationale_parts.append(f"미출 {sta['dormancy']}회")
        if sta.get("regression_top3_N"):
            rationale_parts.append(f"활성 회귀 N={sta['regression_top3_N']}")

        # 결론: 추천/제외 + 이유
        if type == "recommend":
            conclusion = f"다음 회차 출현 가능성 높음 (Pillar 합의 {cns.get('agreement_strength', '')})"
        else:
            reason = rec_or_exc.get("exclude_reason", "")
            conclusion = f"미출현 가능성 높음 ({reason})"

        return {
            "signal_seed": strongest_signal or "일반 신호",
            "rationale_seed": ", ".join(rationale_parts) if rationale_parts else "추가 신호 없음",
            "conclusion_seed": conclusion,
            "evidence_full": {
                "pillar_1": pillar_breakdown.get("pillar_1_ensemble_prob"),
                "pillar_2": flt,
                "pillar_3": sta,
                "pillar_4": cns,
                "auto_rule_reason": rec_or_exc.get("exclude_reason"),
                "memo_active": rec_or_exc.get("memo_forced", False),
            },
        }

    # ────── global summary ──────

    def _global_summary(self, rec_explained: list[dict], exc_explained: list[dict]) -> dict:
        # 평균 ensemble_prob
        ens_top5 = []
        cns_top5 = []
        flt_dist = {"high": 0, "mid": 0, "low": 0}

        for r in rec_explained:
            if "error" in r:
                continue
            l2 = r.get("layer_2_pillar_gauges", {})
            ens_top5.append(l2.get("ENS", 0.5))
            cns_top5.append(l2.get("CNS", 0.5))
            f = l2.get("FLT", 0.5)
            if f > 0.7:
                flt_dist["high"] += 1
            elif f > 0.4:
                flt_dist["mid"] += 1
            else:
                flt_dist["low"] += 1

        return {
            "average_ensemble_prob_top5": float(np.mean(ens_top5)) if ens_top5 else 0.0,
            "average_consensus_strength_top5": float(np.mean(cns_top5)) if cns_top5 else 0.0,
            "filter_compliance_distribution": flt_dist,
            "n_recommendations_explained": len(rec_explained),
            "n_exclusions_explained": len(exc_explained),
        }


# ────── smoke ──────


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()

    if args.smoke:
        recommendations = [
            {"number": 23, "score": 0.62, "memo_forced": False,
             "passed_filters": ["sum", "endings"], "failed_filters": [],
             "hotcold": "Warm", "dormancy": 12,
             "regression_top3_active_N": [2, 8, 22]},
            {"number": 31, "score": 0.58, "memo_forced": True,
             "passed_filters": ["high_low"], "failed_filters": ["odd_even"]},
        ]
        exclusions = [
            {"number": 42, "score": 0.05, "exclude_reason": "memo", "force_exclude": True},
            {"number": 22, "score": 0.08, "exclude_reason": "regression_consecutive_N12",
             "force_exclude": True},
            {"number": 13, "score": 0.10, "exclude_reason": "pillar_score_low",
             "force_exclude": False},
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
            13: {"top10_count": 2, "bottom15_count": 4, "mean_rank": 28.3,
                 "std_rank": 6.2, "consensus_score": -33.5},
        }

        explainer = NumberXAIExplainer()
        out = explainer.explain_all(
            recommendations=recommendations,
            exclusions=exclusions,
            consensus_metrics=consensus_metrics,
            filter_compliance=np.random.default_rng(42).random(45),
        )

        print(f"[xai_explainer] explained recs: {len(out['recommendations'])}, "
              f"excs: {len(out['exclusions'])}")
        for r in out["recommendations"]:
            n = r["number"]
            l2 = r["layer_2_pillar_gauges"]
            l1 = r["layer_1_narrative"]
            print(f"  REC n={n}: ENS={l2['ENS']:.2f} FLT={l2['FLT']:.2f} "
                  f"CNS={l2['CNS']:.2f} ({l2['consensus_strength_visual']})")
            print(f"    signal: {l1['signal_seed']}")
            print(f"    rationale: {l1['rationale_seed']}")
            print(f"    conclusion: {l1['conclusion_seed']}")
            print(f"    memo_forced: {r['memo_signals']['forced_inc']}")

        for e in out["exclusions"]:
            n = e["number"]
            triggers = e["auto_rule_triggers"]
            print(f"  EXC n={n}: triggers={triggers}, "
                  f"memo_forced_exc={e['memo_signals']['forced_exc']}")

        gs = out["global_summary"]
        print(f"\n[global summary]")
        print(f"  avg_ENS_top5: {gs['average_ensemble_prob_top5']:.3f}")
        print(f"  avg_CNS_top5: {gs['average_consensus_strength_top5']:.3f}")
        print(f"  flt_dist: {gs['filter_compliance_distribution']}")


if __name__ == "__main__":
    main()
