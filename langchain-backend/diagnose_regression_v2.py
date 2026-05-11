"""
weekly_regression_analysis 누락 모델 진단 v2 (수정된 ensemble.py 사용)
1223회 step=2 직접 호출 → model_exp 키 확인
"""
from __future__ import annotations
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import json
from models.ensemble import LottoEnsemble
from db.supabase_client import get_client

def diagnose_regression_v2():
    """수정된 ensemble.py로 1223회 step=2 predict_regression() 호출"""
    print("=" * 80)
    print("1. Supabase에서 1222회차 이전 draws 로드")
    print("=" * 80)

    supabase = get_client()
    response = supabase.table("lotto_draws").select("*").order("round", desc=True).execute()
    all_draws = response.data

    # 1222회차 이전 데이터만 (cutoff_round=1222)
    history_draws = [d for d in all_draws if d["round"] < 1223]
    history_draws.sort(key=lambda x: x["round"], reverse=True)

    print(f"총 {len(history_draws)}회 데이터 로드 (1222회까지)")
    if len(history_draws) < 50:
        print("데이터 부족. 종료.")
        return

    print("\n" + "=" * 80)
    print("2. LottoEnsemble 초기화 (학습 스킵 - saved_models 사용)")
    print("=" * 80)

    ensemble = LottoEnsemble()
    # 학습 스킵 - 기존 saved_models만 로드
    print("11 base 모델 인스턴스 생성 완료 (학습 스킵)")

    print("\n" + "=" * 80)
    print("3. predict_regression(step=2) 호출")
    print("=" * 80)

    try:
        result = ensemble.predict_regression(history_draws, step=2)
        model_exp = result.get("model_exp", {})

        print(f"\nmodel_exp 키 개수: {len(model_exp)}")
        print("\n모델별 값:")
        print("-" * 80)

        # 11 base 모델 순서
        expected_models = [
            "xgboost", "cnn", "gnn", "markov", "autoencoder",
            "catboost", "tabnet", "tft", "mhn", "bayesian_nn", "nbeats"
        ]

        missing = []
        for m in expected_models:
            val = model_exp.get(m)
            if val is None:
                print(f"  {m:<15}: None (누락) ✗")
                missing.append(m)
            elif val == 0:
                print(f"  {m:<15}: 0 (fallback 의심)")
            else:
                print(f"  {m:<15}: {val}")

        print("-" * 80)
        if missing:
            print(f"\n누락된 모델: {', '.join(missing)}")
        else:
            print("\n모든 모델 적재 확인됨.")

        # 기타 반환값 확인
        print("\nensemble_exp:", result.get("ensemble_exp"))
        print("step_weights:", result.get("step_weights"))
        print("target_numbers:", result.get("target_numbers"))

    except Exception as e:
        print(f"predict_regression 호출 실패: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    diagnose_regression_v2()
