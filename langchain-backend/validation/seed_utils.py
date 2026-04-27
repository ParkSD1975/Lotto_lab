"""G-6: 재현성을 위한 글로벌 random seed 적용.

학습 시작 시점에 set_global_seed()를 1회 호출하면 numpy / random / torch (CPU·CUDA) /
PyTorch DataLoader worker까지 모두 동일 seed로 초기화된다.
"""

import os
import random
import numpy as np

import config


def set_global_seed(seed: int | None = None) -> int:
    """모든 라이브러리의 random seed를 통일한다.

    Args:
        seed: None이면 config.RANDOM_SEED 사용.

    Returns:
        실제 적용된 seed 값.
    """
    if seed is None:
        seed = config.RANDOM_SEED

    random.seed(seed)
    np.random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)

    try:
        import torch

        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
        # 결정성: 약간의 성능 손실 감수
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
    except ImportError:
        pass

    return seed


def seed_worker(worker_id: int) -> None:
    """PyTorch DataLoader worker_init_fn 용 헬퍼.

    DataLoader(num_workers > 0)에서 각 worker의 seed를 deterministic하게 설정.
    """
    worker_seed = config.RANDOM_SEED + worker_id
    np.random.seed(worker_seed)
    random.seed(worker_seed)
