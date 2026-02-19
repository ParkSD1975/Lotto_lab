import sys
import os
import time

# 부모 디렉토리를 경로에 추가하여 모듈 임포트 가능하게 설정
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.supabase_client import fetch_all_draws
from models.ensemble import LottoEnsemble
import config

def main():
    start_time = time.time()
    print("[Phase 3] Initial model training system starting...")
    print("   5-Model Ensemble: Transformer + LSTM + CNN + XGBoost + Markov")

    # 1. 데이터 로드
    print("\n[Step 1] Fetching all lotto data from Supabase...")
    try:
        draws = fetch_all_draws()
        print(f"   [OK] Loaded {len(draws)} rounds successfully.")

        if len(draws) < 100:
            print("   [WARN] Too few data points. Training quality may be low.")

    except Exception as e:
        print(f"   [FAIL] Data load failed: {e}")
        return

    # 2. 모델 학습 시작
    print("\n[Step 2] Starting 5-model deep learning ensemble training...")
    print("   (Markov -> XGBoost -> CNN -> LSTM -> Transformer)")
    ensemble = LottoEnsemble()

    try:
        # 전체 학습 실행
        results = ensemble.train_all(draws)

        if results.get("success"):
            elapsed = time.time() - start_time
            print(f"\n[COMPLETE] All model training finished! (Elapsed: {elapsed:.2f}s)")
            print(f"[SAVE] Model files saved to: {os.path.abspath(config.MODEL_DIR)}")
            print("   - transformer_model.pt  (Self-Attention)")
            print("   - lstm_model.pt         (BiLSTM+Attention)")
            print("   - cnn_model.pt          (1D-CNN)")
            print("   - xgboost_models.pkl    (XGBoost)")
            print("   - markov_matrices.json  (Markov)")
            print("   - ensemble_weights.json (5-model weights)")

            # 모델별 결과 요약
            model_results = results.get("model_results", {})
            print("\n[SUMMARY] Per-model training results:")
            for name, res in model_results.items():
                status = "[OK]" if res.get("success") else "[FAIL]"
                detail = ""
                if res.get("epochs_trained"):
                    detail = f" (Epochs: {res['epochs_trained']}, Val Loss: {res.get('best_val_loss', 'N/A'):.6f})"
                elif res.get("error"):
                    detail = f" ({res['error']})"
                print(f"   {status} {name}{detail}")
        else:
            print(f"\n[FAIL] Training failed: {results.get('error')}")

    except Exception as e:
        print(f"\n[FATAL] Critical error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
