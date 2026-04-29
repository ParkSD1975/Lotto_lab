"""GNN 재학습 + 재진단 스크립트 (Stage 1-4-D-2-fix-9).

순서:
  1) draws 로드 (numbers list 정규화)
  2) GNNTrainer.train(draws, fine_tune=False)  # force_retrain.flag 또는 fine_tune=False
  3) predict 분포 측정 (max/mean/std/nonzero/top5)
  4) GAT W weight norm 출력
ASCII print only.
"""

from __future__ import annotations

import os
import sys
import json
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from db.supabase_client import fetch_all_draws
from models.gnn_model import GNNTrainer
import torch


def main() -> int:
    print("=" * 72)
    print("[GNN retrain] start")
    print("=" * 72)

    # 1. draws 로드
    raw_draws = fetch_all_draws()
    fixed = []
    for d in raw_draws:
        nums = d.get("numbers", None)
        if isinstance(nums, str):
            try:
                nums = json.loads(nums)
            except Exception:
                nums = []
        if not isinstance(nums, list):
            nums = []
        fixed.append({
            "round": int(d.get("round", 0) or 0),
            "numbers": [int(n) for n in nums if n is not None],
            "bonus": d.get("bonus", 0),
        })
    valid = [d for d in fixed if len(d["numbers"]) == 6]
    print(f"[1] valid draws: {len(valid)}")

    # 2. force_retrain (fine_tune=False)
    trainer = GNNTrainer()
    trainer.train(valid, fine_tune=False)

    # 3. predict
    res = trainer.predict(valid)
    probs = np.array([res.get(n, 0.0) for n in range(1, 46)], dtype=np.float64)
    print()
    print("[3] predict result")
    print(f"  mean={probs.mean():.4f}  max={probs.max():.4f}  "
          f"std={probs.std():.4f}  min={probs.min():.4f}")
    print(f"  nonzero(>0.001) = {(probs > 0.001).sum()}/45")
    top5 = sorted(res.items(), key=lambda x: -x[1])[:5]
    bot5 = sorted(res.items(), key=lambda x: x[1])[:5]
    print(f"  top5: {[(n, round(p, 4)) for n, p in top5]}")
    print(f"  bot5: {[(n, round(p, 4)) for n, p in bot5]}")
    print(f"  spread (max-min): {probs.max() - probs.min():.4f}")

    # 4. GAT weight norm
    print()
    print("[4] GAT weight norm (post-train)")
    if trainer.model is not None:
        for name, p in trainer.model.named_parameters():
            arr = p.detach().cpu().numpy()
            print(f"  {name:42s}  abs_mean={np.abs(arr).mean():.4f}  std={arr.std():.4f}")

    # 검증 기준
    print()
    print("[VERDICT]")
    pass_max = probs.max() > 0.05
    pass_spread = (probs.max() - probs.min()) > 0.02
    pass_std = probs.std() > 0.005
    print(f"  max_prob > 0.05    : {pass_max}  ({probs.max():.4f})")
    print(f"  spread > 0.02      : {pass_spread}  ({probs.max() - probs.min():.4f})")
    print(f"  std    > 0.005     : {pass_std}  ({probs.std():.4f})")
    print(f"  OVERALL: {'PASS' if (pass_max and pass_spread and pass_std) else 'FAIL'}")

    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
