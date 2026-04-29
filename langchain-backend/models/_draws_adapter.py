"""draws -> (X, y) 변환 공용 헬퍼.

Stage 1-4-D-2-fix-4: 5 신규 base wrapper(catboost/tabnet/tft/mhn/bayesian_nn)의
ensemble.train_all 호환 어댑터에서 공통으로 사용.

LSTM의 LottoSequenceDataset._draw_to_features 와 동일한 65-dim feature 산식을
재사용해 base간 feature 일관성을 유지한다.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

import config


def _draw_to_features_65(draw: dict) -> np.ndarray:
    """한 회차 dict -> 65-dim feature vector.

    LSTM `LottoSequenceDataset._draw_to_features` 와 동일 산식
    (45 occurrence + 12 pattern + 8 cyclical = 65).
    """
    numbers = sorted(draw.get("numbers", []) or [])
    round_num = int(draw.get("round", 0) or 0)

    occurrence = np.zeros(45, dtype=np.float32)
    for n in numbers:
        if 1 <= n <= 45:
            occurrence[n - 1] = 1.0

    total_sum = sum(numbers) if numbers else 0
    odd_count = sum(1 for n in numbers if n % 2 == 1)
    low_count = sum(1 for n in numbers if n <= 22)
    primes = getattr(config, "PRIMES", set())
    prime_count = sum(1 for n in numbers if n in primes)
    tail_sum = sum(n % 10 for n in numbers)

    ac_value = 0
    if len(numbers) >= 2:
        diffs = set()
        for i in range(len(numbers)):
            for j in range(i + 1, len(numbers)):
                diffs.add(abs(numbers[i] - numbers[j]))
        ac_value = len(diffs) - (len(numbers) - 1)

    consec_pairs = sum(
        1
        for i in range(len(numbers) - 1)
        if numbers[i + 1] - numbers[i] == 1
    )

    pattern = np.array(
        [
            total_sum / 255.0,
            odd_count / 6.0,
            low_count / 6.0,
            ac_value / 10.0,
            consec_pairs / 6.0,
            tail_sum / 45.0,
            prime_count / 6.0,
            0.0, 0.0, 0.0, 0.0, 0.0,
        ],
        dtype=np.float32,
    )

    cyclical = np.array(
        [
            math.sin(2 * math.pi * round_num / 5.0),
            math.cos(2 * math.pi * round_num / 5.0),
            math.sin(2 * math.pi * round_num / 10.0),
            math.cos(2 * math.pi * round_num / 10.0),
            math.sin(2 * math.pi * round_num / 20.0),
            math.cos(2 * math.pi * round_num / 20.0),
            math.sin(2 * math.pi * round_num / 52.0),
            math.cos(2 * math.pi * round_num / 52.0),
        ],
        dtype=np.float32,
    )

    return np.concatenate([occurrence, pattern, cyclical])


def _aggregate_window_to_features(window: list[dict], target_dim: int) -> np.ndarray:
    """window(seq_len개 회차) -> target_dim feature.

    seq_len회차 평균 feature(65) 를 만든 뒤 target_dim 으로 truncate/pad.
    target_dim==65 이면 그대로 평균 반환.
    """
    if not window:
        return np.zeros(target_dim, dtype=np.float32)

    feats = np.stack([_draw_to_features_65(d) for d in window], axis=0)  # (T, 65)
    mean_feat = feats.mean(axis=0).astype(np.float32)

    if target_dim == mean_feat.shape[0]:
        return mean_feat
    if target_dim < mean_feat.shape[0]:
        return mean_feat[:target_dim]
    out = np.zeros(target_dim, dtype=np.float32)
    out[: mean_feat.shape[0]] = mean_feat
    return out


def draws_to_xy(
    draws: list[dict],
    seq_len: int = 30,
    input_dim: int = 65,
) -> tuple[np.ndarray, np.ndarray]:
    """draws -> (X, y) for binary_45 학습.

    Args:
        draws: [{round, numbers, bonus}, ...] (최신순 가정 — LSTM 관례).
        seq_len: 직전 N회차 통계 윈도.
        input_dim: 출력 feature 차원 (65 권장 — LSTM/CNN 호환).

    Returns:
        X: (T - seq_len, input_dim) float32
        y: (T - seq_len, 45) float32 multi-hot
    """
    if not draws or len(draws) <= seq_len:
        return (
            np.zeros((0, input_dim), dtype=np.float32),
            np.zeros((0, 45), dtype=np.float32),
        )

    chronological = list(reversed(draws))  # 과거 -> 최신

    X_rows: list[np.ndarray] = []
    y_rows: list[np.ndarray] = []

    for i in range(seq_len, len(chronological)):
        window = chronological[i - seq_len : i]
        feat = _aggregate_window_to_features(window, target_dim=input_dim)
        if feat.shape[0] != input_dim:
            continue
        X_rows.append(feat)

        y_vec = np.zeros(45, dtype=np.float32)
        for n in chronological[i].get("numbers", []) or []:
            if 1 <= int(n) <= 45:
                y_vec[int(n) - 1] = 1.0
        y_rows.append(y_vec)

    if not X_rows:
        return (
            np.zeros((0, input_dim), dtype=np.float32),
            np.zeros((0, 45), dtype=np.float32),
        )

    X = np.stack(X_rows, axis=0).astype(np.float32)
    y = np.stack(y_rows, axis=0).astype(np.float32)
    return X, y


def draws_to_tft_dataframe(
    draws: list[dict],
    seq_len: int = 30,
    input_dim: int = 65,
) -> Any:
    """draws -> pandas DataFrame for TFT TimeSeriesDataSet.

    Schema:
      - time_idx: int (회차 순번)
      - group_id: str (단일 group "0")
      - target: float (현재 회차 sum 정규화 — 부수 metric, sigmoid binary_45는
        head fine-tune 용으로 별도 라벨 사용)
      - feat_0..feat_(input_dim-1): float
      - label_1..label_45: 0/1 (45 multi-hot 확장)

    pandas 미설치 시 None 반환.
    """
    try:
        import pandas as pd
    except ImportError:
        return None

    if not draws:
        return pd.DataFrame()

    chronological = list(reversed(draws))
    rows = []
    for t, d in enumerate(chronological):
        feat = _draw_to_features_65(d)
        if input_dim != 65:
            if input_dim < 65:
                feat = feat[:input_dim]
            else:
                pad = np.zeros(input_dim, dtype=np.float32)
                pad[:65] = feat
                feat = pad
        nums = d.get("numbers", []) or []
        target = float(sum(int(n) for n in nums if 1 <= int(n) <= 45)) / 255.0
        row = {
            "time_idx": int(t),
            "group_id": "0",
            "target": target,
        }
        for i, v in enumerate(feat):
            row[f"feat_{i}"] = float(v)
        for i in range(1, 46):
            row[f"label_{i}"] = 1.0 if i in {int(n) for n in nums} else 0.0
        rows.append(row)

    return pd.DataFrame(rows)
