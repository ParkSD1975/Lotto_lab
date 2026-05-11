"""
1222·1223회 weekly_regression_analysis 재적재 스크립트
수정된 ensemble.py (11 base 전체 포함)로 회귀 분석 재생성 → DB UPSERT
"""
from __future__ import annotations
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from models.ensemble import LottoEnsemble
from db.supabase_client import get_client

def analyze_regressions_for_round(target_round: int, history_draws: list, ensemble: LottoEnsemble):
    """특정 회차의 회귀 분석 (step 2~200) 생성"""
    results = []
    total_draws = len(history_draws)

    for w in range(2, 201):
        if total_draws < w + 20:
            break  # 검증을 위한 최소 표본 확보

        try:
            # predict_regression() 호출
            reg_result = ensemble.predict_regression(history_draws, step=w)
            model_exp = reg_result.get("model_exp", {})
            target_numbers = reg_result.get("target_numbers", [])

            # 메타 정보 추가 (스키마 변경 없이)
            me = dict(model_exp)
            me["_targets"] = target_numbers
            me["_gap"] = 0  # 간소화 (필요 시 계산)
            me["_str"] = 0
            me["_avg_hit"] = 0.0
            me["_notable"] = []

            results.append({
                "target_round": target_round,
                "step": w,
                "window_type": None,
                "predicted_numbers": target_numbers,
                "model_exp": me,
                "primary_method": None,
                "confidence": 0.0,
            })
        except Exception as e:
            print(f"  [step={w}] 실패: {e}")
            continue

    return results

def backfill_regression():
    """1222·1223회 회귀 분석 재적재"""
    print("=" * 80)
    print("1. Supabase에서 lotto_draws 로드")
    print("=" * 80)

    supabase = get_client()
    response = supabase.table("lotto_draws").select("*").order("round", desc=True).execute()
    all_draws = response.data
    all_draws.sort(key=lambda x: x["round"], reverse=True)

    print(f"총 {len(all_draws)}회 데이터 로드")

    print("\n" + "=" * 80)
    print("2. LottoEnsemble 초기화")
    print("=" * 80)

    ensemble = LottoEnsemble()
    print("11 base 모델 인스턴스 생성 완료")

    # ── 1222회 재적재 ──
    print("\n" + "=" * 80)
    print("3-1. 1222회 회귀 분석 재생성")
    print("=" * 80)

    history_1222 = [d for d in all_draws if d["round"] < 1222]
    history_1222.sort(key=lambda x: x["round"], reverse=True)

    print(f"1222회 이전 데이터: {len(history_1222)}회")
    results_1222 = analyze_regressions_for_round(1222, history_1222, ensemble)
    print(f"1222회 회귀 분석 {len(results_1222)}개 생성")

    # DB 저장
    try:
        supabase.table("weekly_regression_analysis").delete().eq("target_round", 1222).execute()
        if results_1222:
            # batch insert (199 row)
            supabase.table("weekly_regression_analysis").insert(results_1222).execute()
            print(f"1222회 {len(results_1222)}행 DB 저장 완료 ✓")
    except Exception as e:
        print(f"1222회 DB 저장 실패: {e}")

    # ── 1223회 재적재 ──
    print("\n" + "=" * 80)
    print("3-2. 1223회 회귀 분석 재생성")
    print("=" * 80)

    history_1223 = [d for d in all_draws if d["round"] < 1223]
    history_1223.sort(key=lambda x: x["round"], reverse=True)

    print(f"1223회 이전 데이터: {len(history_1223)}회")
    results_1223 = analyze_regressions_for_round(1223, history_1223, ensemble)
    print(f"1223회 회귀 분석 {len(results_1223)}개 생성")

    # DB 저장
    try:
        supabase.table("weekly_regression_analysis").delete().eq("target_round", 1223).execute()
        if results_1223:
            supabase.table("weekly_regression_analysis").insert(results_1223).execute()
            print(f"1223회 {len(results_1223)}행 DB 저장 완료 ✓")
    except Exception as e:
        print(f"1223회 DB 저장 실패: {e}")

    # ── 검증 ──
    print("\n" + "=" * 80)
    print("4. DB 검증")
    print("=" * 80)

    for target_round in [1222, 1223]:
        result = supabase.table("weekly_regression_analysis") \
            .select("*") \
            .eq("target_round", target_round) \
            .execute()
        rows = result.data

        print(f"\n{target_round}회 weekly_regression_analysis: {len(rows)}행")

        # 11 base 모델별 적재 확인
        expected_models = [
            "xgboost", "cnn", "gnn", "markov", "autoencoder",
            "catboost", "tabnet", "tft", "mhn", "bayesian_nn", "nbeats"
        ]

        for m in expected_models:
            count = sum(1 for r in rows if r.get("model_exp", {}).get(m) is not None)
            if count == len(rows):
                print(f"  {m:<15}: {count}/{len(rows)} ✓")
            else:
                print(f"  {m:<15}: {count}/{len(rows)} ✗ (누락: {len(rows) - count})")

    print("\n" + "=" * 80)
    print("재적재 완료")
    print("=" * 80)

if __name__ == "__main__":
    backfill_regression()
