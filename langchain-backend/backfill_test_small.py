"""
1223회 step 33~42 소규모 테스트 (10 step)
"""
from __future__ import annotations
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from models.ensemble import LottoEnsemble
from db.supabase_client import get_client

def test_small():
    print("=" * 80)
    print("1223회 step 33~42 테스트 (10 step)")
    print("=" * 80)

    supabase = get_client()
    response = supabase.table("lotto_draws").select("*").order("round", desc=True).execute()
    all_draws = response.data
    all_draws.sort(key=lambda x: x["round"], reverse=True)
    print(f"총 {len(all_draws)}회 데이터 로드")

    history_1223 = [d for d in all_draws if d["round"] < 1223]
    history_1223.sort(key=lambda x: x["round"], reverse=True)
    print(f"1223회 이전 데이터: {len(history_1223)}회")

    ensemble = LottoEnsemble()
    print("Ensemble 초기화 완료")

    # Step 33~42 테스트
    for step in range(33, 43):
        print(f"\n[Step {step}]")
        try:
            result = ensemble.predict_regression(history_1223, step=step)
            model_exp = result.get("model_exp", {})
            print(f"  model_exp keys: {list(model_exp.keys())}")

            # 11 base 확인
            expected = ["xgboost", "cnn", "gnn", "markov", "autoencoder",
                       "catboost", "tabnet", "tft", "mhn", "bayesian_nn", "nbeats"]
            missing = [m for m in expected if m not in model_exp]
            if missing:
                print(f"  ✗ 누락: {missing}")
            else:
                print(f"  ✓ 11 base 전체 존재")
        except Exception as e:
            print(f"  ✗ 실패: {e}")
            import traceback
            traceback.print_exc()

    print("\n테스트 완료")

if __name__ == "__main__":
    test_small()
