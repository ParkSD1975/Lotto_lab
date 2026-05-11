"""
weekly_regression_analysis 누락 모델 진단 스크립트
1223회 step=2 직접 호출 → model_exp 키 확인
"""
from __future__ import annotations
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import json
from models.ensemble import LottoEnsemble
from db.supabase_client import get_client

def diagnose_regression():
    """1223회 step=2 predict_regression() 직접 호출"""
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
    print("2. LottoEnsemble 초기화 + 학습")
    print("=" * 80)

    ensemble = LottoEnsemble()
    try:
        ensemble.train_all(history_draws, force_retrain=False)
        print("11 base 모델 학습 완료")
    except Exception as e:
        print(f"학습 실패: {e}")
        import traceback
        traceback.print_exc()
        return

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

    print("\n" + "=" * 80)
    print("4. 개별 모델 predict() 직접 호출 테스트")
    print("=" * 80)

    # 누락 의심 모델 직접 테스트
    test_models = ["catboost", "tabnet", "cnn", "gnn", "tft", "nbeats", "mhn", "bayesian_nn"]
    for m_name in test_models:
        try:
            model = ensemble.models.get(m_name)
            if model is None:
                print(f"  {m_name:<15}: 모델 인스턴스 없음 ✗")
                continue

            preds = model.predict(history_draws)
            if not preds:
                print(f"  {m_name:<15}: 빈 dict 반환 ✗")
            elif len(preds) < 45:
                print(f"  {m_name:<15}: {len(preds)}개 번호만 반환 (45개 미만) ✗")
            else:
                sample_val = preds.get(1, 0)
                print(f"  {m_name:<15}: OK ({len(preds)} keys, num=1 prob={sample_val:.4f})")
        except Exception as e:
            print(f"  {m_name:<15}: 예외 발생 - {e} ✗")

if __name__ == "__main__":
    diagnose_regression()
