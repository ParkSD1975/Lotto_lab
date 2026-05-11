"""
1222회 step 2~200 전체 backfill
"""
from __future__ import annotations
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from models.ensemble import LottoEnsemble
from db.supabase_client import get_client
import time

BATCH_SIZE = 30  # 30 step씩 커밋

def main():
    print("=" * 80)
    print("1222회 회귀 분석 전체 backfill (step 2~200)")
    print("=" * 80)

    # ── 1. 데이터 로드 ──
    print("\n[1] lotto_draws 로드")
    supabase = get_client()
    response = supabase.table("lotto_draws").select("*").order("round", desc=True).execute()
    all_draws = response.data
    all_draws.sort(key=lambda x: x["round"], reverse=True)
    print(f"총 {len(all_draws)}회 데이터 로드")

    history_1222 = [d for d in all_draws if d["round"] < 1222]
    history_1222.sort(key=lambda x: x["round"], reverse=True)
    print(f"1222회 이전 데이터: {len(history_1222)}회")

    # ── 2. Ensemble 초기화 ──
    print("\n[2] LottoEnsemble 초기화")
    ensemble = LottoEnsemble()
    print("11 base 모델 인스턴스 생성 완료")

    # ── 3. 기존 1222회 데이터 삭제 ──
    print("\n[3] 기존 1222회 데이터 삭제")
    try:
        supabase.table("weekly_regression_analysis").delete().eq("target_round", 1222).execute()
        print("기존 1222회 데이터 삭제 완료")
    except Exception as e:
        print(f"삭제 실패 (무시): {e}")

    # ── 4. 배치 처리 ──
    print("\n[4] 배치 UPSERT 시작 (step 2~200)")
    total_rows = 0
    current_step = 2

    while current_step <= 200:
        batch_end = min(current_step + BATCH_SIZE - 1, 200)
        print(f"\n  [Batch] step {current_step}~{batch_end} 생성 중...")

        batch_rows = []
        for step in range(current_step, batch_end + 1):
            try:
                reg_result = ensemble.predict_regression(history_1222, step=step)
                model_exp = reg_result.get("model_exp", {})
                target_numbers = reg_result.get("target_numbers", [])

                batch_rows.append({
                    "target_round": 1222,
                    "step": step,
                    "window_type": None,
                    "predicted_numbers": target_numbers,
                    "model_exp": model_exp,
                    "primary_method": None,
                    "confidence": 0.0,
                })
                print(f"    step {step} ✓")
            except Exception as e:
                print(f"    step {step} ✗ 실패: {e}")
                continue

        # UPSERT
        if batch_rows:
            print(f"  [DB] {len(batch_rows)}행 INSERT 중...")
            try:
                supabase.table("weekly_regression_analysis").insert(batch_rows).execute()
                print(f"  [DB] {len(batch_rows)}행 INSERT 완료 ✓")
                total_rows += len(batch_rows)
            except Exception as e:
                print(f"  [DB] INSERT 실패: {e}")

        current_step = batch_end + 1
        time.sleep(0.3)  # 과부하 방지

    print(f"\n1222회 총 {total_rows}행 적재 완료")

    # ── 5. 검증 ──
    print("\n" + "=" * 80)
    print("1222회 DB 검증")
    print("=" * 80)

    result = supabase.table("weekly_regression_analysis") \
        .select("step,model_exp") \
        .eq("target_round", 1222) \
        .order("step") \
        .execute()

    rows = result.data
    print(f"총 {len(rows)}행 적재됨")

    expected_models = [
        "xgboost", "cnn", "gnn", "markov", "autoencoder",
        "catboost", "tabnet", "tft", "mhn", "bayesian_nn", "nbeats"
    ]

    for m in expected_models:
        steps = [r["step"] for r in rows if r.get("model_exp", {}) and r.get("model_exp", {}).get(m) is not None]
        coverage = len(steps)
        if coverage == 199:  # step 2~200 전체
            print(f"  {m:<15}: {coverage}/199 ✓")
        else:
            step_range = f"{min(steps)}-{max(steps)}" if steps else "none"
            print(f"  {m:<15}: {coverage}/199 (range: {step_range})")

    print("\n" + "=" * 80)
    print("1222회 backfill 완료")
    print("=" * 80)

if __name__ == "__main__":
    main()
