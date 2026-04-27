"""G-4: TimeSeriesSplit walk-forward CV.

본 문서 G-4 결정:
- n_splits=5 walk-forward expanding window
- 마지막 100~200회차는 hold-out 고정
- 매 fold에서 normalization·bucket_calibration·alpha 모두 *train fold에만* fit

배경:
- 1,100회차 시계열 → 일반 random K-fold는 미래 정보 누설 (data leakage) 위험
- walk-forward는 train ⊏ val의 시간 순서를 항상 보장
"""

from __future__ import annotations

from typing import Iterator


def time_series_splits(
    n_samples: int,
    n_splits: int = 5,
    holdout_size: int = 100,
    min_train_size: int | None = None,
) -> Iterator[tuple[range, range]]:
    """walk-forward expanding window splits.

    Args:
        n_samples: 전체 시계열 길이.
        n_splits: fold 개수 (기본 5).
        holdout_size: 마지막 회차 hold-out 길이 (기본 100).
        min_train_size: 첫 fold 최소 학습 크기. None이면 (n_samples - holdout) * 0.4.

    Yields:
        (train_indices, val_indices) 튜플. range 객체로 메모리 효율.

    예시 (n_samples=1100, n_splits=5, holdout=100, min_train=400):
        Fold 1: train [0:400),    val [400:600)
        Fold 2: train [0:600),    val [600:800)
        Fold 3: train [0:800),    val [800:900)
        Fold 4: train [0:900),    val [900:1000)
        Fold 5: train [0:1000),   val [1000:1100)   ← hold-out 포함
    """
    if n_samples < holdout_size + 100:
        raise ValueError(
            f"n_samples ({n_samples}) too small. Need at least {holdout_size + 100}."
        )

    available = n_samples - holdout_size  # hold-out 제외 학습 가용 영역
    if min_train_size is None:
        min_train_size = int(available * 0.4)

    # val window를 균등 분할
    val_total = n_samples - min_train_size
    val_per_fold = max(val_total // n_splits, 50)  # fold당 최소 50회

    train_end = min_train_size
    for i in range(n_splits):
        if i == n_splits - 1:
            # 마지막 fold는 hold-out 포함
            val_start = train_end
            val_end = n_samples
        else:
            val_start = train_end
            val_end = min(train_end + val_per_fold, n_samples - holdout_size)

        if val_end <= val_start:
            break

        yield range(0, train_end), range(val_start, val_end)
        train_end = val_end


def holdout_split(
    n_samples: int, holdout_size: int = 100
) -> tuple[range, range]:
    """train + 마지막 hold-out 단일 분할.

    weekly_pipeline_v2 추론 시점에 사용 — CV 없이 hold-out만 평가.
    """
    if n_samples < holdout_size + 100:
        raise ValueError(f"n_samples ({n_samples}) too small")
    train_end = n_samples - holdout_size
    return range(0, train_end), range(train_end, n_samples)
