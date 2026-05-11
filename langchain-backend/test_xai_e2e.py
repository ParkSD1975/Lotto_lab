"""Stage 4-B XAI + Narrative e2e 검증 — 1222회 추천/제외 분석.

Master Plan Stage 4-1~4-3 검증:
  - NumberXAIExplainer: 11 base XAI + 4 Pillar 통합
  - XAIAggregator: 번호별 XAI 집계
  - NumberNarrative: 3섹션 narrative (fallback 모드)
  - PageNarrative: 페이지 narrative
"""

import sys
import traceback
from models.ensemble import LottoEnsemble
from db.supabase_client import fetch_all_draws
from models.number_xai_explainer import NumberXAIExplainer
from services.xai_aggregator import XAIAggregator
from services.number_narrative import generate_batch as generate_number_narratives
from services.page_narrative import generate_page_narrative


def main():
    target_round = 1222
    print(f"\n{'='*70}")
    print(f"Stage 4-B XAI + Narrative e2e - {target_round} round")
    print(f"{'='*70}\n")

    # 1. 데이터 로드
    print("[1/5] 과거 회차 로드...")
    try:
        all_draws = fetch_all_draws()
        history_draws = [d for d in all_draws if d["round"] < target_round]
        print(f"  → {len(history_draws)}회차 로드 완료")
    except Exception as e:
        print(f"  ✗ DB 연결 실패: {e}")
        return

    # 2. 앙상블 예측 (추천 5 + 제외 10)
    print("\n[2/5] 앙상블 예측 (추천 5 + 제외 10)...")
    try:
        ensemble = LottoEnsemble()

        # 추천 5
        top5_result = ensemble.predict_top5(
            history_draws, n_top=5, n_bootstrap=50, consensus_k=4
        )
        recommendations = top5_result.get("top_numbers", [])[:5]

        # 제외 10
        excl_result = ensemble.predict_exclusion_with_veto(
            history_draws, n_exclude=10
        )
        exclusions = excl_result.get("exclusions", [])[:10]

        print(f"  → 추천: {[r['number'] for r in recommendations]}")
        print(f"  → 제외: {[e['number'] for e in exclusions]}")
    except Exception as e:
        print(f"  ✗ 예측 실패: {e}")
        traceback.print_exc()
        return

    # 3. XAI 통합 (NumberXAIExplainer)
    print("\n[3/5] XAI 통합 (NumberXAIExplainer)...")
    try:
        xai_explainer = NumberXAIExplainer()
        xai_out = xai_explainer.explain_all(
            recommendations=recommendations,
            exclusions=exclusions,
            consensus_metrics=top5_result.get("consensus_metrics", {}),
        )

        print(f"  → 추천 XAI: {len(xai_out['recommendations'])}개")
        print(f"  → 제외 XAI: {len(xai_out['exclusions'])}개")

        # 첫 번째 추천 번호 Layer 2 Pillar 게이지 확인
        if xai_out['recommendations']:
            first = xai_out['recommendations'][0]
            l2 = first.get('layer_2_pillar_gauges', {})
            print(f"  → 추천 1번(n={first['number']}): ENS={l2.get('ENS', 0):.2f}, "
                  f"FLT={l2.get('FLT', 0):.2f}, CNS={l2.get('CNS', 0):.2f}")
    except Exception as e:
        print(f"  ✗ XAI 통합 실패: {e}")
        traceback.print_exc()
        xai_out = {"recommendations": [], "exclusions": []}

    # 4. Narrative 생성 (NumberNarrative fallback)
    print("\n[4/5] Narrative 생성 (NumberNarrative fallback)...")
    try:
        narratives = generate_number_narratives(
            xai_out['recommendations'] + xai_out['exclusions'],
            fallback=True
        )

        print(f"  → Narrative 생성 완료: {len(narratives)}개")

        # 첫 번째 추천 narrative 출력
        if narratives:
            for narr in narratives[:1]:  # 추천 1개만
                if narr.get('type') == 'recommend':
                    n = narr['narrative']
                    print(f"\n  [추천 번호 {narr['number']} narrative]")
                    print(f"    시그널: {n['signal']}")
                    print(f"    근거: {n['rationale']}")
                    print(f"    결론: {n['conclusion']}")
                    break
    except Exception as e:
        print(f"  ✗ Narrative 생성 실패: {e}")
        traceback.print_exc()
        narratives = []

    # 5. PageNarrative 생성
    print("\n[5/5] PageNarrative 생성 (총합 지표)...")
    try:
        page_evidence = {
            "indicator_name": "총합",
            "recent_stats": {
                "rolling_mean_10": 138.5,
                "rolling_std_10": 28.3,
                "trend_pattern": "mild_up",
                "volatility_ratio": 1.2,
            },
            "ml_prediction": {"q10": 110.0, "q50": 138.0, "q90": 168.0},
            "consensus": "중",
        }
        page_narr = generate_page_narrative(page_evidence, fallback=True)

        pn = page_narr.get('narrative', {})
        print(f"  → 흐름: {pn.get('flow', '')}")
        print(f"  → 추세: {pn.get('trend', '')}")
        print(f"  → 추천: {pn.get('recommendation', '')}")
    except Exception as e:
        print(f"  ✗ PageNarrative 실패: {e}")
        traceback.print_exc()

    # 요약
    print(f"\n{'='*70}")
    print(f"검증 완료")
    print(f"{'='*70}")
    print(f"추천 {len(recommendations)}개, 제외 {len(exclusions)}개")
    print(f"XAI 통합: {len(xai_out.get('recommendations', []))} + {len(xai_out.get('exclusions', []))}개")
    print(f"Narrative: {len(narratives)}개")
    print(f"Global summary avg_ENS: {xai_out.get('global_summary', {}).get('average_ensemble_prob_top5', 0):.3f}")
    print()


if __name__ == "__main__":
    main()
