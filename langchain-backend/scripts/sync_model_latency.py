"""model_latency_log 테이블 동기화 (sla_history → Supabase).

문제:
    model_latency_log 테이블이 비어있음 (0행)
    → ai_deep_learning.html 모델 추론시간 섹션 렌더링 실패

해결:
    1. sla_monitor.py의 sync_sla_to_latency_log() 호출
    2. sla_history.parquet/jsonl에서 11 base 모델 추론시간 추출
    3. model_latency_log 테이블에 INSERT

사용:
    cd langchain-backend
    python scripts/sync_model_latency.py
"""

from __future__ import annotations

import sys
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from db.supabase_client import get_client
from pipeline.sla_monitor import sync_sla_to_latency_log


def main():
    print("[sync_model_latency] 시작")

    # 1. Supabase 클라이언트
    client = get_client()

    # 2. sync_sla_to_latency_log 호출 (11 base)
    print(f"  [1] sync_sla_to_latency_log (11 base, recent_n=100) 실행...")
    model_names = [
        "xgboost", "catboost", "tabnet", "cnn", "gnn",
        "markov", "autoencoder", "tft", "mhn", "bayesian_nn", "nbeats"
    ]
    result = sync_sla_to_latency_log(
        supabase_client=client,
        recent_n=100,
        model_names=model_names,
    )

    if result.get("success"):
        print(f"  [OK] 적재 완료:")
        print(f"      rows_inserted  = {result['rows_inserted']}")
        print(f"      models_synced  = {result['models_synced']}")
    else:
        print(f"  [ERR] 동기화 실패: {result.get('error')}")

    # 3. 검증: model_latency_log 테이블 조회 (실제 컬럼명: model_name, elapsed_ms)
    print(f"\n  [2] model_latency_log 검증 조회...")
    verify_res = client.table("model_latency_log").select("model_name, elapsed_ms, operation").order("created_at", desc=True).execute()
    if verify_res.data:
        print(f"      확인: {len(verify_res.data)}행 적재됨 (최근 5개):")
        for row in verify_res.data[:5]:
            print(f"        - {row['model_name']} ({row['operation']}): {row['elapsed_ms']}ms")
    else:
        print(f"      [WARN] model_latency_log 여전히 비어있음")


if __name__ == "__main__":
    main()
