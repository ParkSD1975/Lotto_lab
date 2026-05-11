# -*- coding: utf-8 -*-
"""NBeats 모델 학습 스크립트.

마스터 플랜 Stage 1 #9: sum/AC/끝수합 같은 스칼라 지표 시계열 학습.
1차 단순화: sum 시계열만 학습.
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np

# langchain-backend 패키지 import
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import config
from db.supabase_client import fetch_all_draws
from models.nbeats_model import LottoNBeats


def extract_sum_series(draws: list[dict]) -> np.ndarray:
    """전체 회차 데이터에서 sum 시계열 추출.

    Args:
        draws: supabase lotto_draws 테이블 데이터 (round desc 정렬)

    Returns:
        (T,) ndarray - 오름차순 회차 sum 시계열
    """
    # round 오름차순 정렬
    sorted_draws = sorted(draws, key=lambda d: int(d.get("round", 0)))

    sums = []
    for draw in sorted_draws:
        numbers = draw.get("numbers", [])
        if numbers:
            sums.append(float(sum(numbers)))
        else:
            # 결측 시 직전 값으로 채움 (또는 평균)
            if sums:
                sums.append(sums[-1])
            else:
                sums.append(120.0)  # 로또 평균 합 기준값

    return np.array(sums, dtype=np.float32)


def train_nbeats_sum(
    epochs: int = 30,
    seq_length: int = 50,
    val_ratio: float = 0.1,
    save_path: str | None = None,
) -> dict:
    """Sum 시계열 NBeats 학습.

    Args:
        epochs: 학습 epoch
        seq_length: NBeats encoder length
        val_ratio: 검증 split 비율
        save_path: 저장 경로 (None이면 saved_models/nbeats_sum.pt)

    Returns:
        학습 정보 dict
    """
    print(f"[train_nbeats] start - epochs={epochs}, seq_length={seq_length}")

    # 1. 데이터 로드
    draws = fetch_all_draws()
    print(f"[train_nbeats] fetch_all_draws: {len(draws)} rounds")

    if len(draws) < seq_length + 10:
        raise ValueError(f"Insufficient data: {len(draws)} rounds < seq_length({seq_length})+10")

    # 2. sum 시계열 추출
    sum_series = extract_sum_series(draws)
    print(f"[train_nbeats] sum series: {sum_series.shape}, min={sum_series.min():.1f}, max={sum_series.max():.1f}")

    # 3. train/val split
    n_val = max(1, int(len(sum_series) * val_ratio))
    train_series = sum_series[:-n_val]
    val_series = sum_series[-n_val:]
    print(f"[train_nbeats] split: train={len(train_series)}, val={len(val_series)}")

    # 4. 모델 학습
    model = LottoNBeats(
        seq_length=seq_length,
        prediction_length=1,
        num_blocks=(3, 3),
        expansion_coefficient_lengths=(3, 5),
        widths=(32, 512),
        learning_rate=1e-3,
        random_seed=config.RANDOM_SEED,
    )

    info = model.train(
        train_series,
        val_series=val_series,
        max_epochs=epochs,
        batch_size=64,
    )

    print(f"[train_nbeats] training complete: {info}")

    # 5. 검증 예측
    try:
        pred_next = model.predict(sum_series, steps=1)
        print(f"[train_nbeats] next round sum prediction: {pred_next[0]:.1f}")
    except Exception as e:
        print(f"[train_nbeats] prediction failed: {e}")

    # 6. 분해 검증
    try:
        dec = model.decompose(sum_series)
        print(
            f"[train_nbeats] decompose: "
            f"trend={dec['trend'].shape}, "
            f"seasonality={dec['seasonality'].shape}, "
            f"residual={dec['residual'].shape}"
        )
    except Exception as e:
        print(f"[train_nbeats] decompose failed: {e}")

    # 7. 저장
    if save_path is None:
        save_path = os.path.join(config.MODEL_DIR, "nbeats_sum.pt")

    model.save(save_path)
    print(f"[train_nbeats] saved: {save_path}")

    return {
        "success": True,
        "epochs": epochs,
        "train_size": len(train_series),
        "val_size": len(val_series),
        "save_path": save_path,
    }


def main():
    parser = argparse.ArgumentParser(description="NBeats sum time-series training")
    parser.add_argument("--epochs", type=int, default=30, help="Number of training epochs")
    parser.add_argument("--seq-length", type=int, default=50, help="Encoder sequence length")
    parser.add_argument("--val-ratio", type=float, default=0.1, help="Validation split ratio")
    parser.add_argument("--save-path", type=str, default=None, help="Save path")

    args = parser.parse_args()

    result = train_nbeats_sum(
        epochs=args.epochs,
        seq_length=args.seq_length,
        val_ratio=args.val_ratio,
        save_path=args.save_path,
    )

    if result["success"]:
        print(f"\n[train_nbeats] SUCCESS: {result['save_path']}")
        return 0
    else:
        print("\n[train_nbeats] FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
