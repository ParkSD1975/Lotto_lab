# -*- coding: utf-8 -*-
"""weekly_number_xai 에 model_rank 컬럼 backfill.

weekly_number_xai 테이블에 xgboost_rank ~ bayesian_nn_rank 컬럼이 추가된 뒤
기존 row를 raw 확률 기반 순위로 채운다.

사용:
    python langchain-backend/scripts/backfill_model_ranks.py [--round 1223]
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.supabase_client import fetch_all_draws, get_client
from models.ensemble import LottoEnsemble

RANK_MODELS = [
    "xgboost", "catboost", "tabnet", "cnn", "gnn",
    "markov", "autoencoder", "tft", "mhn", "bayesian_nn",
]


def compute_model_ranks(contributions: dict) -> dict:
    """raw 확률로 1-45 순위 계산.

    Args:
        contributions: {model_name: {num: raw_prob}}

    Returns:
        {model_name: {num: rank}}  rank 1=최고, 45=최저
    """
    model_ranks: dict = {}
    for m in RANK_MODELS:
        m_probs = contributions.get(m, {})
        if m_probs:
            sorted_nums = sorted(
                range(1, 46),
                key=lambda n, p=m_probs: float(p.get(n, 0.0)),
                reverse=True,
            )
            model_ranks[m] = {num: (rank + 1) for rank, num in enumerate(sorted_nums)}
        else:
            model_ranks[m] = {n: 45 for n in range(1, 46)}
    return model_ranks


def backfill_ranks(target_round: int | None = None) -> None:
    print("[backfill_model_ranks] 시작...")

    draws = fetch_all_draws()
    if not draws:
        print("[ERROR] draws 로드 실패")
        return

    # 최신 회차 결정 (key: 'round' or 'draw_no' 모두 지원)
    _rkey = "draw_no" if draws and "draw_no" in draws[0] else "round"
    if target_round is None:
        target_round = max(d[_rkey] for d in draws) + 1
    print(f"[backfill_model_ranks] 대상 회차: {target_round} (key={_rkey})")

    # 학습 데이터 (cutoff=1100 이하)
    train_draws = [d for d in draws if d[_rkey] <= 1100]
    if not train_draws:
        train_draws = draws  # fallback

    # 앙상블 초기화 (학습된 saved_models 자동 로드)
    ensemble = LottoEnsemble()

    # predict_top5 로 raw contributions 추출 (full_probs + contributions 포함)
    top5 = ensemble.predict_top5(draws)
    contributions = top5.get("contributions", {})

    if not contributions:
        # fallback: predict()
        pred = ensemble.predict(draws)
        contributions = pred.get("model_contributions", {})

    if not contributions:
        print("[ERROR] contributions 비어있음 — 모델 로드 확인 필요")
        return

    # 순위 계산
    model_ranks = compute_model_ranks(contributions)
    print(f"[backfill_model_ranks] 순위 계산 완료: {list(model_ranks.keys())}")

    # Supabase UPDATE
    client = get_client()
    updated = 0
    for n in range(1, 46):
        rank_update = {
            f"{m}_rank": model_ranks.get(m, {}).get(n, 45)
            for m in RANK_MODELS
        }
        client.table("weekly_number_xai") \
            .update(rank_update) \
            .eq("target_round", target_round) \
            .eq("number", n) \
            .execute()
        updated += 1

    print(f"[backfill_model_ranks] 완료: {updated}개 번호 업데이트 (회차 {target_round})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--round", type=int, default=None,
                        help="대상 회차 번호 (생략 시 최신+1)")
    args = parser.parse_args()
    backfill_ranks(target_round=args.round)
