"""1222회 weekly_number_xai XGBoost/CNN/GNN 재계산 + Supabase UPSERT.

문제:
    1222회 weekly_number_xai에서 xgboost_pct/cnn_pct 모두 0, gnn_pct 모두 2.22 (균일값)
    → 모델별 rank도 모두 45 (미계산)

해결:
    1. ensemble.predict() 재실행 → model_contributions 추출
    2. raw probabilities를 XAI Z-score로 변환 (앙상블과 동일 로직)
    3. weekly_number_xai 45행 UPDATE

사용:
    cd langchain-backend
    python scripts/backfill_1222_xai.py
"""

from __future__ import annotations

import sys
import os

# langchain-backend 루트를 sys.path에 추가
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

import numpy as np
from db.supabase_client import get_client, fetch_all_draws
from models.ensemble import LottoEnsemble


def compute_xai_from_raw(model_contributions: dict) -> dict:
    """raw probabilities를 XAI Z-score (%) 로 변환.

    앙상블의 compute_xai_contributions()와 동일 로직.

    Args:
        model_contributions: {model_name: {number: raw_prob}, ...}

    Returns:
        {number: {model_name: xai_pct}, ...}
    """
    xai_contributions = {}
    for num in range(1, 46):
        xai_contributions[num] = {}

    for model_name, num_to_prob in model_contributions.items():
        if not isinstance(num_to_prob, dict):
            continue
        # raw probs 추출
        probs = [float(num_to_prob.get(n, num_to_prob.get(str(n), 0.0))) for n in range(1, 46)]
        arr = np.array(probs, dtype=np.float64)
        if arr.sum() == 0:
            # 균등 fallback
            arr = np.ones(45, dtype=np.float64) / 45.0

        # Z-score
        mean = arr.mean()
        std = arr.std()
        if std < 1e-9:
            std = 1e-9
        z_scores = (arr - mean) / std

        # 양수만 (음수는 0으로 클램핑)
        z_scores = np.maximum(z_scores, 0.0)
        z_sum = z_scores.sum()
        if z_sum > 0:
            z_scores = z_scores / z_sum * 100.0  # 비율로 변환 (%)
        else:
            z_scores = np.ones(45, dtype=np.float64) / 45.0 * 100.0

        for n in range(1, 46):
            xai_contributions[n][model_name] = round(float(z_scores[n - 1]), 2)

    return xai_contributions


def main():
    print("[backfill_1222_xai] 시작")
    target_round = 1222

    # 1. 데이터 로드
    draws = fetch_all_draws()
    if not draws:
        print("  [ERR] 이력 데이터 없음")
        return
    latest_round = draws[0]["round"]
    if target_round > latest_round:
        print(f"  [ERR] target_round {target_round} > latest {latest_round}")
        return

    # 1222회 이전 데이터로 필터링
    history_1222 = [d for d in draws if d["round"] < target_round]
    print(f"  [1] 1222회 이전 이력: {len(history_1222)}회차")

    # 2. ensemble 예측 (history_1222는 이미 1222 이전만 포함)
    print(f"  [2] ensemble.predict() 실행 (1222 이전 이력 사용)...")
    ensemble = LottoEnsemble()
    pred = ensemble.predict(history_1222)
    contributions = pred.get("model_contributions", {})
    if not contributions:
        print("  [ERR] model_contributions 없음")
        return

    # 3. XAI Z-score 계산
    print(f"  [3] XAI Z-score 계산 (11 base)...")
    xai_contrib = compute_xai_from_raw(contributions)

    # 4. raw probabilities 기반 순위 계산
    print(f"  [4] 모델별 raw prob 순위 계산...")
    _rank_models = [
        'xgboost', 'catboost', 'tabnet', 'cnn', 'gnn',
        'markov', 'autoencoder', 'tft', 'mhn', 'bayesian_nn',
    ]
    model_ranks = {}
    for _m in _rank_models:
        _probs = contributions.get(_m, {})
        if _probs:
            _sorted = sorted(range(1, 46),
                             key=lambda n, p=_probs: float(p.get(n, p.get(str(n), 0.0))),
                             reverse=True)
            model_ranks[_m] = {num: (rank + 1) for rank, num in enumerate(_sorted)}
        else:
            # fallback: XAI pct로 근사
            _xai_scores = {n: float(xai_contrib.get(n, {}).get(_m, 0.0)) for n in range(1, 46)}
            _xai_sorted = sorted(range(1, 46), key=lambda n, s=_xai_scores: s[n], reverse=True)
            model_ranks[_m] = {num: (rank + 1) for rank, num in enumerate(_xai_sorted)}

    # 5. Supabase UPDATE (45행)
    print(f"  [5] Supabase weekly_number_xai UPDATE (1222회, 45행)...")
    client = get_client()
    for n in range(1, 46):
        x = xai_contrib.get(n, {})
        update_row = {
            "xgboost_pct": x.get("xgboost", 0.0),
            "catboost_pct": x.get("catboost", 0.0),
            "tabnet_pct": x.get("tabnet", 0.0),
            "cnn_pct": x.get("cnn", 0.0),
            "gnn_pct": x.get("gnn", 0.0),
            "markov_pct": x.get("markov", 0.0),
            "autoencoder_pct": x.get("autoencoder", 0.0),
            "tft_pct": x.get("tft", 0.0),
            "mhn_pct": x.get("mhn", 0.0),
            "bayesian_nn_pct": x.get("bayesian_nn", 0.0),
            # rank
            "xgboost_rank": model_ranks.get('xgboost', {}).get(n, 45),
            "catboost_rank": model_ranks.get('catboost', {}).get(n, 45),
            "tabnet_rank": model_ranks.get('tabnet', {}).get(n, 45),
            "cnn_rank": model_ranks.get('cnn', {}).get(n, 45),
            "gnn_rank": model_ranks.get('gnn', {}).get(n, 45),
            "markov_rank": model_ranks.get('markov', {}).get(n, 45),
            "autoencoder_rank": model_ranks.get('autoencoder', {}).get(n, 45),
            "tft_rank": model_ranks.get('tft', {}).get(n, 45),
            "mhn_rank": model_ranks.get('mhn', {}).get(n, 45),
            "bayesian_nn_rank": model_ranks.get('bayesian_nn', {}).get(n, 45),
        }
        client.table("weekly_number_xai") \
            .update(update_row) \
            .eq("target_round", target_round) \
            .eq("number", n) \
            .execute()

    print(f"  [6] 완료: 1222회 XGBoost/CNN/GNN XAI + rank 정상화")
    print(f"      예시 - 번호 1: xgb={xai_contrib[1].get('xgboost', 0):.2f}%, "
          f"cnn={xai_contrib[1].get('cnn', 0):.2f}%, gnn={xai_contrib[1].get('gnn', 0):.2f}%")


if __name__ == "__main__":
    main()
