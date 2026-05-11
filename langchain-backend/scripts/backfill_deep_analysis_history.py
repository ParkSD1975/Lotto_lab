"""1222·1223회 deep_analysis_history matrix_data backfill.

문제:
    deep_analysis_history의 1222·1223회 analysis_data에 matrix_data 누락
    → ai_deep_learning.html 매트릭스 섹션 렌더링 실패

해결:
    1. weekly_number_xai에서 각 회차 45행 조회
    2. matrix_data = [{num, models: {model: {score, rank}}}, ...] 재구성
    3. deep_analysis_history.analysis_data UPDATE

사용:
    cd langchain-backend
    python scripts/backfill_deep_analysis_history.py
"""

from __future__ import annotations

import sys
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

import json
from db.supabase_client import get_client


def backfill_matrix_data(target_round: int) -> bool:
    """단일 회차 matrix_data backfill.

    Args:
        target_round: 대상 회차 (예: 1222)

    Returns:
        성공 여부
    """
    print(f"  [backfill] {target_round}회차 matrix_data 재구성...")
    client = get_client()

    # 1. weekly_number_xai 45행 조회
    xai_res = client.table("weekly_number_xai") \
        .select("*").eq("target_round", target_round).execute()
    xai_rows = xai_res.data or []
    if len(xai_rows) != 45:
        print(f"    [WARN] weekly_number_xai {len(xai_rows)}행 (기대 45행) — skip")
        return False

    # 2. matrix_data 빌드
    matrix_data = []
    for row in xai_rows:
        num = row.get("number")
        models_dict = {}
        # 11 base (10 active + deprecated)
        for model_name in ["xgboost", "catboost", "tabnet", "cnn", "gnn",
                           "markov", "autoencoder", "tft", "mhn", "bayesian_nn",
                           "lstm", "transformer"]:
            pct_key = f"{model_name}_pct"
            rank_key = f"{model_name}_rank"
            models_dict[model_name] = {
                "score": float(row.get(pct_key, 0.0)),
                "rank": int(row.get(rank_key, 45)),
            }
        matrix_data.append({"num": num, "models": models_dict})

    # 3. 기존 deep_analysis_history row 조회
    hist_res = client.table("deep_analysis_history") \
        .select("*").eq("target_round", target_round).execute()
    if not hist_res.data:
        print(f"    [WARN] deep_analysis_history {target_round}회 없음 — 신규 생성")
        # 신규 생성 (weekly_predictions에서 top_5/exclude_10 조회)
        pred_res = client.table("weekly_predictions") \
            .select("top_5, exclude_10").eq("target_round", target_round).execute()
        top_5 = pred_res.data[0].get("top_5", []) if pred_res.data else []
        exclude_10 = pred_res.data[0].get("exclude_10", []) if pred_res.data else []

        analysis_data_obj = {
            "success": True,
            "target_round": target_round,
            "top_5": top_5,
            "exclude_10": exclude_10,
            "analysis": {"matrix_data": matrix_data},
            "combinations": [],
        }
        new_row = {
            "target_round": target_round,
            "confidence": 75,
            "summary": f"{target_round}회차 딥러닝 앙상블 분석 (matrix_data backfill)",
            "analysis_data": analysis_data_obj,
            "recommended_numbers": top_5,
            "excluded_numbers": exclude_10,
            "combinations": json.dumps([], ensure_ascii=False),
            "number_rankings": json.dumps({}, ensure_ascii=False),
            "model_rankings": json.dumps({}, ensure_ascii=False),
            "applied_filters": json.dumps({}, ensure_ascii=False),
            "model_analysis": json.dumps({}, ensure_ascii=False),
        }
        client.table("deep_analysis_history").insert(new_row).execute()
        print(f"    [OK] 신규 생성: {target_round}회 (matrix_data {len(matrix_data)}행)")
        return True

    # 4. 기존 row UPDATE (analysis_data 병합)
    existing = hist_res.data[0]
    analysis_data_raw = existing.get("analysis_data")
    if isinstance(analysis_data_raw, str):
        try:
            analysis_data_obj = json.loads(analysis_data_raw)
        except Exception:
            analysis_data_obj = {}
    else:
        analysis_data_obj = analysis_data_raw or {}

    # analysis.matrix_data 덮어쓰기
    if "analysis" not in analysis_data_obj:
        analysis_data_obj["analysis"] = {}
    analysis_data_obj["analysis"]["matrix_data"] = matrix_data

    # UPDATE
    client.table("deep_analysis_history") \
        .update({"analysis_data": analysis_data_obj}) \
        .eq("target_round", target_round).execute()
    print(f"    [OK] UPDATE: {target_round}회 (matrix_data {len(matrix_data)}행)")
    return True


def main():
    print("[backfill_deep_analysis_history] 시작")
    target_rounds = [1222, 1223]

    success_count = 0
    for tr in target_rounds:
        if backfill_matrix_data(tr):
            success_count += 1

    print(f"[backfill_deep_analysis_history] 완료: {success_count}/{len(target_rounds)} 회차")


if __name__ == "__main__":
    main()
