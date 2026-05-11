"""
11-base 토폴로지 전 모델 학습 스크립트.

각 모델의 학습 상황을 train_log.txt에 실시간 기록.
"""
import sys
import os
import time
import traceback
from datetime import datetime

# Windows cp949 인코딩 회피 — UTF-8 강제
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "train_progress.log")


def log(msg: str):
    """파일과 stdout에 동시 출력."""
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()


# 로그 초기화
with open(LOG_PATH, "w", encoding="utf-8") as f:
    f.write(f"=== 학습 시작 {datetime.now().isoformat()} ===\n")


log("[1/5] 환경 로드 시작")

try:
    from db.supabase_client import fetch_all_draws
    from models.ensemble import LottoEnsemble
    import config
    log("    [OK] ensemble + supabase 모듈 import 완료")
except Exception as e:
    log(f"    [FAIL] import 실패: {e}")
    traceback.print_exc()
    sys.exit(1)

log("[2/5] Supabase에서 draws 데이터 fetching")
try:
    draws = fetch_all_draws()
    if not draws:
        log("    [FAIL] draws 데이터 없음 — 종료")
        sys.exit(1)
    latest_round = max(d['round'] for d in draws)
    log(f"    [OK] 총 {len(draws)}회차 로드, 최신 {latest_round}회")
except Exception as e:
    log(f"    [FAIL] Supabase fetch 실패: {e}")
    traceback.print_exc()
    sys.exit(1)

log("[3/5] LottoEnsemble 초기화 (11 모델 + 기존 LSTM/Transformer)")
try:
    ensemble = LottoEnsemble()
    log(f"    [OK] ensemble 인스턴스 생성")
    log(f"    등록된 모델 ({len(ensemble.models)}): {list(ensemble.models.keys())}")
except Exception as e:
    log(f"    [FAIL] ensemble 초기화 실패: {e}")
    traceback.print_exc()
    sys.exit(1)

log("[4/5] 전 모델 학습 시작 (force_retrain=True, 시간 오래 걸림)")
log("=" * 70)

# 각 모델 개별 학습 - ensemble.train_all 대신 직접 호출하여 진행 상황 추적
model_results = {}
model_names = list(ensemble.models.keys())

for idx, name in enumerate(model_names, 1):
    model = ensemble.models[name]
    model_start = time.time()
    log(f"  [{idx}/{len(model_names)}] {name.upper()} 학습 시작...")
    try:
        if name == "autoencoder":
            result = model.train(draws)
        elif name in ("catboost", "tabnet", "tft", "mhn", "bayesian_nn"):
            # 신규 5 모델: force_retrain=True 강제 (dummy 가중치 제거)
            result = model.train(draws, fine_tune=False)
        else:
            # 기존 7 모델 force_retrain=True
            result = model.train(draws, fine_tune=False)
        elapsed = time.time() - model_start
        ok = result.get("success", True) if isinstance(result, dict) else True
        log(f"    {'[OK]' if ok else '[FAIL]'} {name} 완료 ({elapsed:.1f}s)")
        if isinstance(result, dict):
            for k, v in result.items():
                if k != "success":
                    log(f"        {k}: {str(v)[:100]}")
        model_results[name] = {"success": ok, "elapsed": elapsed, "result": result}
    except Exception as e:
        elapsed = time.time() - model_start
        log(f"    [FAIL] {name} 실패 ({elapsed:.1f}s): {type(e).__name__}: {str(e)[:200]}")
        model_results[name] = {"success": False, "elapsed": elapsed, "error": str(e)}

    # 메모리 정리
    try:
        import torch, gc
        if hasattr(model, 'model'):
            del model.model
            model.model = None
        torch.cuda.empty_cache()
        gc.collect()
    except Exception:
        pass

log("=" * 70)
log("[5/5] 전 모델 학습 완료 — 결과 요약")
ok_count = sum(1 for r in model_results.values() if r.get("success"))
fail_count = len(model_results) - ok_count
log(f"  성공: {ok_count}개 / 실패: {fail_count}개")
for name, res in model_results.items():
    status = "[OK]" if res.get("success") else "[FAIL]"
    log(f"  {status} {name}: {res.get('elapsed', 0):.1f}s")

log("학습 완료. saved_models/ 디렉토리에 가중치 저장됨.")
log("=== 종료 ===")
