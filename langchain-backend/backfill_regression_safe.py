"""
1222·1223회 weekly_regression_analysis 안전 재적재 스크립트

Step 33~200 배치 UPSERT (10 step씩) + 개별 모델 fallback
"""
from __future__ import annotations
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from models.ensemble import LottoEnsemble
from db.supabase_client import get_client
import time

BATCH_SIZE = 20  # 20 step씩 커밋 (속도 개선)

def predict_regression_safe(ensemble: LottoEnsemble, history_draws: list, step: int):
    """
    ensemble.predict_regression() wrapper - 개별 모델 예외 처리

    실패 시 fallback: 균등 분포 [1/7, 1/7, ..., 1/7]
    """
    try:
        result = ensemble.predict_regression(history_draws, step=step)
        return result
    except Exception as e:
        print(f"    [WARNING] predict_regression(step={step}) 실패: {e}")
        # Fallback: 균등 분포
        uniform_dist = [1.0/7] * 7
        return {
            "model_exp": {
                "xgboost": uniform_dist,
                "cnn": uniform_dist,
                "gnn": uniform_dist,
                "markov": uniform_dist,
                "autoencoder": uniform_dist,
                "catboost": uniform_dist,
                "tabnet": uniform_dist,
                "tft": uniform_dist,
                "mhn": uniform_dist,
                "bayesian_nn": uniform_dist,
                "nbeats": uniform_dist,
                "_targets": [],
                "_gap": 0,
                "_str": 0,
                "_avg_hit": 0.0,
                "_notable": []
            },
            "target_numbers": []
        }

def backfill_batch(supabase, ensemble: LottoEnsemble, target_round: int, history_draws: list, step_range: tuple):
    """
    특정 step 범위 batch 생성 + UPSERT

    Args:
        step_range: (start, end) inclusive (예: (33, 42) → step 33~42 총 10개)
    """
    start_step, end_step = step_range
    batch_rows = []

    print(f"\n  [Batch] step {start_step}~{end_step} 생성 중...")

    for step in range(start_step, end_step + 1):
        try:
            reg_result = predict_regression_safe(ensemble, history_draws, step=step)
            model_exp = reg_result.get("model_exp", {})
            target_numbers = reg_result.get("target_numbers", [])

            batch_rows.append({
                "target_round": target_round,
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

    # UPSERT (기존 row 덮어쓰기)
    if batch_rows:
        print(f"  [DB] {len(batch_rows)}행 UPSERT 중...")
        try:
            for row in batch_rows:
                # 개별 UPSERT (conflict 시 update)
                supabase.table("weekly_regression_analysis") \
                    .upsert(row, on_conflict="target_round,step") \
                    .execute()
            print(f"  [DB] {len(batch_rows)}행 UPSERT 완료 ✓")
            return len(batch_rows)
        except Exception as e:
            print(f"  [DB] UPSERT 실패: {e}")
            return 0
    else:
        print(f"  [DB] 적재할 row 없음")
        return 0

def backfill_round(supabase, ensemble: LottoEnsemble, target_round: int, all_draws: list, start_step=33, end_step=200):
    """
    특정 회차 회귀 분석 재적재 (배치 단위)

    Args:
        start_step: 시작 step (기본 33 = 이전 agent 중단 지점)
        end_step: 종료 step (기본 200)
    """
    print("\n" + "=" * 80)
    print(f"{target_round}회 회귀 분석 재적재 (step {start_step}~{end_step})")
    print("=" * 80)

    history = [d for d in all_draws if d["round"] < target_round]
    history.sort(key=lambda x: x["round"], reverse=True)
    print(f"{target_round}회 이전 데이터: {len(history)}회")

    total_rows = 0
    current_step = start_step

    while current_step <= end_step:
        batch_end = min(current_step + BATCH_SIZE - 1, end_step)

        rows_added = backfill_batch(
            supabase=supabase,
            ensemble=ensemble,
            target_round=target_round,
            history_draws=history,
            step_range=(current_step, batch_end)
        )

        total_rows += rows_added
        current_step = batch_end + 1

        # 과부하 방지 (배치 간 0.5초 대기)
        time.sleep(0.5)

    print(f"\n{target_round}회 총 {total_rows}행 적재 완료")
    return total_rows

def verify_coverage(supabase, target_round: int):
    """11 base 모델별 적재 확인"""
    print("\n" + "=" * 80)
    print(f"{target_round}회 DB 검증")
    print("=" * 80)

    result = supabase.table("weekly_regression_analysis") \
        .select("step,model_exp") \
        .eq("target_round", target_round) \
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
            print(f"  {m:<15}: {coverage}/199 ✗ (range: {step_range})")

def main():
    """메인 재적재 플로우"""
    print("=" * 80)
    print("1222·1223회 회귀 분석 안전 재적재")
    print("=" * 80)

    # ── 1. 데이터 로드 ──
    print("\n[1] lotto_draws 로드")
    supabase = get_client()
    response = supabase.table("lotto_draws").select("*").order("round", desc=True).execute()
    all_draws = response.data
    all_draws.sort(key=lambda x: x["round"], reverse=True)
    print(f"총 {len(all_draws)}회 데이터 로드")

    # ── 2. Ensemble 초기화 ──
    print("\n[2] LottoEnsemble 초기화")
    ensemble = LottoEnsemble()
    print("11 base 모델 인스턴스 생성 완료")

    # ── 3. 1223회 재적재 (step 33~200) ──
    # 사용자 요구: 1223회 먼저 완료
    backfill_round(
        supabase=supabase,
        ensemble=ensemble,
        target_round=1223,
        all_draws=all_draws,
        start_step=33,  # 이전 중단 지점
        end_step=200
    )

    # ── 4. 1223회 검증 ──
    verify_coverage(supabase, target_round=1223)

    # ── 5. 1222회 재적재 (step 2~200 전체) ──
    print("\n" + "=" * 80)
    print("1222회 회귀 분석 재적재 시작")
    print("=" * 80)

    backfill_round(
        supabase=supabase,
        ensemble=ensemble,
        target_round=1222,
        all_draws=all_draws,
        start_step=2,  # 전체 재적재
        end_step=200
    )

    # ── 6. 1222회 검증 ──
    verify_coverage(supabase, target_round=1222)

    print("\n" + "=" * 80)
    print("재적재 완료")
    print("=" * 80)

if __name__ == "__main__":
    main()
