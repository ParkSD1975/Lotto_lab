"""
빠른 검증: 1223회 step 2~10만 재적재
"""
from __future__ import annotations
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from models.ensemble import LottoEnsemble
from db.supabase_client import get_client

def quick_test():
    """1223회 step 2~10만 빠르게 재적재"""
    print("=" * 80)
    print("빠른 검증: 1223회 step 2~10만")
    print("=" * 80)

    supabase = get_client()
    response = supabase.table("lotto_draws").select("*").order("round", desc=True).execute()
    all_draws = response.data

    history_1223 = [d for d in all_draws if d["round"] < 1223]
    history_1223.sort(key=lambda x: x["round"], reverse=True)

    print(f"1223회 이전 데이터: {len(history_1223)}회")

    ensemble = LottoEnsemble()
    print("LottoEnsemble 초기화 완료")

    results = []
    for w in range(2, 11):
        try:
            reg_result = ensemble.predict_regression(history_1223, step=w)
            model_exp = reg_result.get("model_exp", {})
            target_numbers = reg_result.get("target_numbers", [])

            me = dict(model_exp)
            me["_targets"] = target_numbers
            me["_gap"] = 0
            me["_str"] = 0
            me["_avg_hit"] = 0.0
            me["_notable"] = []

            results.append({
                "target_round": 1223,
                "step": w,
                "window_type": None,
                "predicted_numbers": target_numbers,
                "model_exp": me,
                "primary_method": None,
                "confidence": 0.0,
            })

            # 모델별 값 출력
            print(f"\nstep={w} model_exp:")
            for m in ["xgboost", "cnn", "gnn", "markov", "autoencoder",
                      "catboost", "tabnet", "tft", "mhn", "bayesian_nn", "nbeats"]:
                val = model_exp.get(m)
                if val is None:
                    print(f"  {m:<15}: None ✗")
                else:
                    print(f"  {m:<15}: {val}")

        except Exception as e:
            print(f"  [step={w}] 실패: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n생성된 결과: {len(results)}개")

    # DB 저장 (step 2~10만 삭제 후 재적재)
    # 주의: 기존 step 11~200은 유지
    try:
        for r in results:
            # 개별 UPSERT (step별 삭제 후 insert)
            supabase.table("weekly_regression_analysis") \
                .delete().eq("target_round", 1223).eq("step", r["step"]).execute()
            supabase.table("weekly_regression_analysis").insert([r]).execute()

        print(f"\n1223회 step 2~10 DB 저장 완료 ✓")
    except Exception as e:
        print(f"DB 저장 실패: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    quick_test()
