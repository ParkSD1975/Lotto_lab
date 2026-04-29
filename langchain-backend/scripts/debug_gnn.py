"""GNN mode collapse 디버그 스크립트 (Stage 1-4-D-2-fix-9).

용도:
  1) 현재 저장된 gnn_model.pt를 로드해 predict 분포 출력 (학습 안 하고 측정)
  2) 학습 데이터 변환(features/adjacency) 분포 점검
  3) (옵션) raw logits / sigmoid prob 분포 출력
ASCII print only (cp949 호환).
"""

from __future__ import annotations

import os
import sys
import json
import numpy as np

# 프로젝트 루트 경로
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from db.supabase_client import fetch_all_draws
from models.gnn_model import GNNTrainer, LottoGNNModel
import torch


def describe_array(name: str, arr: np.ndarray) -> None:
    arr = np.asarray(arr, dtype=np.float64)
    if arr.size == 0:
        print(f"  [{name}] EMPTY")
        return
    print(
        f"  [{name}] shape={arr.shape}  "
        f"min={arr.min():.4f}  max={arr.max():.4f}  "
        f"mean={arr.mean():.4f}  std={arr.std():.4f}"
    )


def main() -> int:
    print("=" * 72)
    print("[GNN debug] start")
    print("=" * 72)

    # 1. draws 로드
    draws = fetch_all_draws()
    print(f"[Step1] fetch_all_draws -> {len(draws)} rows")
    if not draws:
        print("  ERROR: no draws fetched")
        return 1

    # 데이터 sanity
    sample = draws[0]
    print(f"  sample keys: {list(sample.keys())}")
    nums_field = sample.get("numbers", None)
    print(f"  sample.numbers = {nums_field} (type={type(nums_field).__name__})")

    # 'numbers' 가 list가 아닐 경우 변환
    fixed_draws = []
    for d in draws:
        nums = d.get("numbers", None)
        if isinstance(nums, str):
            try:
                nums = json.loads(nums)
            except Exception:
                nums = []
        if not isinstance(nums, list):
            # num1..num6 fallback
            cols = [d.get(f"num{i}") for i in range(1, 7)]
            nums = [int(c) for c in cols if c is not None]
        fixed_draws.append({
            "round": int(d.get("round", 0) or 0),
            "numbers": [int(n) for n in nums if n is not None],
            "bonus": d.get("bonus", 0),
        })

    valid = [d for d in fixed_draws if len(d["numbers"]) == 6]
    print(f"  valid 6-number draws: {len(valid)}/{len(fixed_draws)}")
    if not valid:
        print("  ERROR: no valid draws after normalization")
        return 1

    # 2. 현재 저장된 모델 predict 분포
    print()
    print("[Step2] predict using EXISTING saved gnn_model.pt")
    trainer = GNNTrainer()
    res = trainer.predict(valid)
    probs = np.array([res.get(n, 0.0) for n in range(1, 46)], dtype=np.float64)
    describe_array("existing.probs", probs)
    nz = (probs > 0.001).sum()
    print(f"  nonzero(>0.001) = {nz}/45")
    print(f"  prob_top5 = {sorted(res.items(), key=lambda x: -x[1])[:5]}")

    # 3. raw logits / sigmoid 점검
    print()
    print("[Step3] raw logits inspection")
    model_path = os.path.join(trainer.save_dir, "gnn_model.pt")
    if not os.path.exists(model_path):
        print("  no gnn_model.pt -> skip")
    else:
        # predict 내부 동작 흉내
        if trainer.model is None:
            trainer.model = LottoGNNModel().to(trainer.device)
        trainer.model.load_state_dict(
            torch.load(model_path, map_location=trainer.device, weights_only=True)
        )
        trainer.model.eval()

        draws_sorted = sorted(valid, key=lambda x: x["round"])
        recent = draws_sorted[-100:]
        adj_norm = trainer._normalize_adjacency(trainer._adj_counts)
        raw_feats = trainer._build_features_raw(recent)
        feats = trainer._apply_feature_transform(raw_feats)

        x = torch.FloatTensor(feats).to(trainer.device)
        adj = torch.FloatTensor(adj_norm).to(trainer.device)
        with torch.no_grad():
            logits = trainer.model(x, adj).cpu().numpy()
            sig = 1.0 / (1.0 + np.exp(-logits))
        describe_array("raw_logits", logits)
        describe_array("sigmoid(logits)", sig)

        # 정규화 전후 차이
        norm = sig / sig.sum() if sig.sum() > 0 else sig
        describe_array("normalized_probs", norm)

    # 4. adjacency / feature 분포 점검
    print()
    print("[Step4] adjacency / feature inspection")
    adj_counts = trainer._adj_counts
    describe_array("adj_counts", adj_counts)
    adj_norm = trainer._normalize_adjacency(adj_counts)
    describe_array("adj_norm", adj_norm)
    print(f"  adj_norm row_sum mean={adj_norm.sum(axis=1).mean():.4f}")

    raw_feats = trainer._build_features_raw(valid[-100:])
    describe_array("raw_feats", raw_feats)
    if trainer._feature_transformer is not None:
        feats = trainer._apply_feature_transform(raw_feats)
        describe_array("transformed_feats", feats)
    else:
        print("  feature_transformer = None")

    # 5. parameter norm
    print()
    print("[Step5] model parameter inspection")
    if os.path.exists(model_path):
        if trainer.model is None:
            trainer.model = LottoGNNModel().to(trainer.device)
        trainer.model.load_state_dict(
            torch.load(model_path, map_location=trainer.device, weights_only=True)
        )
        for name, p in trainer.model.named_parameters():
            arr = p.detach().cpu().numpy()
            print(f"  {name:40s}  shape={list(arr.shape)}  "
                  f"abs_mean={np.abs(arr).mean():.4f}  std={arr.std():.4f}")

    print("=" * 72)
    print("[GNN debug] done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
