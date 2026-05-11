"""recommendation_backtest_runs 테이블 50회차 walk-forward 적재.

문제:
    recommendation_backtest_runs 테이블이 비어있음 (0행)
    → verification.html 백테스트 섹션 렌더링 실패

해결:
    1. RecommendationBacktest.run() 실행 (50회차 walk-forward)
    2. save_backtest_to_db() 호출하여 Supabase INSERT

사용:
    cd langchain-backend
    python scripts/populate_backtest_runs.py
"""

from __future__ import annotations

import sys
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from db.supabase_client import get_client, fetch_all_draws
from validation.recommendation_backtest import RecommendationBacktest
from models.number_scorer import NumberScorer
from models.number_recommender import NumberRecommender
from models.ensemble import LottoEnsemble


def main():
    print("[populate_backtest_runs] 시작")

    # 1. 데이터 로드
    draws = fetch_all_draws()
    if not draws or len(draws) < 51:
        print(f"  [ERR] 이력 데이터 부족: {len(draws)}회차 (최소 51회차 필요)")
        return

    print(f"  [1] 이력 데이터: {len(draws)}회차")

    # 2. 객체 생성
    print(f"  [2] NumberScorer + NumberRecommender + Ensemble 생성...")
    scorer = NumberScorer()
    recommender = NumberRecommender(scorer=scorer)
    ensemble = LottoEnsemble()

    # 3. 백테스트 실행 (50회차)
    print(f"  [3] RecommendationBacktest.run (window=50) 실행...")
    bt = RecommendationBacktest(scorer=scorer, recommender=recommender, window=50)
    result = bt.run(
        draws=draws,
        ensemble=ensemble,
        predictor_pipeline=None,  # PredictorPipeline은 옵션
        retrain_every=0,
        expert_memo=None,
        n_top=5,
        n_exc=10,
    )

    if result.get("n_rounds_evaluated") == 0:
        print(f"  [ERR] 백테스트 실행 실패: {result.get('error')}")
        return

    print(f"  [4] 백테스트 완료:")
    print(f"      n_rounds_evaluated = {result['n_rounds_evaluated']}")
    print(f"      avg_rec_hit        = {result['avg_rec_hit']:.4f}")
    print(f"      avg_exc_hit        = {result['avg_exc_hit']:.4f}")

    # 4. Supabase 적재
    print(f"  [5] Supabase recommendation_backtest_runs 적재...")
    client = get_client()
    save_result = bt.save_backtest_to_db(result, supabase_client=client)

    if save_result.get("success"):
        print(f"  [OK] 적재 완료: {save_result['rows_inserted']}행")
    else:
        print(f"  [ERR] 적재 실패: {save_result.get('error')}")

    # 5. 안전 체크
    sc = bt.safety_check(result)
    if not sc.get("safe"):
        print(f"\n  [WARN] safety_check 경고:")
        for w in sc.get("warnings", []):
            print(f"    - {w}")


if __name__ == "__main__":
    main()
