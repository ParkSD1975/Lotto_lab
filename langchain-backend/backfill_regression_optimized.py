"""
최적화된 회귀 분석 재적재 (1223회만 우선)
- step별 개별 UPSERT로 빠른 진행
- 진행 상황 실시간 출력
"""
from __future__ import annotations
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from models.ensemble import LottoEnsemble
from db.supabase_client import get_client

def backfill_optimized():
    """1223회 회귀 분석 재적재 (step 2~200)"""
    print("=" * 80)
    print("1223회 weekly_regression_analysis 전체 재적재 (step 2~200)")
    print("=" * 80)

    supabase = get_client()
    response = supabase.table("lotto_draws").select("*").order("round", desc=True).execute()
    all_draws = response.data

    history_1223 = [d for d in all_draws if d["round"] < 1223]
    history_1223.sort(key=lambda x: x["round"], reverse=True)

    print(f"1223회 이전 데이터: {len(history_1223)}회")

    ensemble = LottoEnsemble()
    print("LottoEnsemble 초기화 완료\n")

    success_count = 0
    fail_count = 0

    for w in range(2, 201):
        try:
            reg_result = ensemble.predict_regression(history_1223, step=w)
            model_exp = reg_result.get("model_exp", {})
            target_numbers = reg_result.get("target_numbers", [])

            if not model_exp:
                print(f"[step={w:3d}] model_exp 비어있음 - 스킵")
                fail_count += 1
                continue

            # 메타 정보 추가
            me = dict(model_exp)
            me["_targets"] = target_numbers
            me["_gap"] = 0
            me["_str"] = 0
            me["_avg_hit"] = 0.0
            me["_notable"] = []

            row = {
                "target_round": 1223,
                "step": w,
                "window_type": None,
                "predicted_numbers": target_numbers,
                "model_exp": me,
                "primary_method": None,
                "confidence": 0.0,
            }

            # DB UPSERT (개별 step 삭제 후 insert)
            supabase.table("weekly_regression_analysis") \
                .delete().eq("target_round", 1223).eq("step", w).execute()
            supabase.table("weekly_regression_analysis").insert([row]).execute()

            success_count += 1

            # 10 step마다 진행 상황 출력
            if w % 10 == 0:
                print(f"[step={w:3d}] ✓ (진행: {success_count}/199)")

        except Exception as e:
            print(f"[step={w:3d}] 실패: {e}")
            fail_count += 1
            continue

    print("\n" + "=" * 80)
    print(f"재적재 완료: 성공 {success_count}, 실패 {fail_count}")
    print("=" * 80)

    # 최종 검증
    result = supabase.table("weekly_regression_analysis") \
        .select("*") \
        .eq("target_round", 1223) \
        .execute()

    rows = result.data
    print(f"\n1223회 총 저장 행: {len(rows)}")

    # 11 base 모델별 적재 확인
    models = [
        "xgboost", "cnn", "gnn", "markov", "autoencoder",
        "catboost", "tabnet", "tft", "mhn", "bayesian_nn", "nbeats"
    ]

    print("\n모델별 적재 확인:")
    print("-" * 80)
    for m in models:
        count = sum(1 for r in rows if r.get("model_exp", {}).get(m) is not None)
        status = "✓" if count == len(rows) else f"✗ (누락: {len(rows) - count})"
        print(f"  {m:<15}: {count}/{len(rows)} {status}")

if __name__ == "__main__":
    backfill_optimized()
