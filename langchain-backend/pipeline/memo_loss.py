"""Stage 3-B-2: 메모 정합성 보조 손실 (Memo Consistency Loss).

메커니즘 2 — 학습 시 메인 BCE/CE 손실에 추가되는 보조항.
사용자 메모의 forced_includes 번호가 실제 출현(label=1)했는데 모델이 낮게
예측하면 패널티, forced_excludes 번호가 미출현(label=0)인데 모델이 높게 예측
하면 패널티를 부여하여 메모 신호와 일관된 방향으로 학습되도록 유도한다.

torch import-guard: PyTorch 미설치 환경에서도 모듈 import는 통과 (함수 호출
시점에 런타임 에러).
"""

from __future__ import annotations

from typing import Any

try:
    import torch
    from torch import Tensor
    _HAS_TORCH = True
except Exception:  # pragma: no cover
    torch = None  # type: ignore[assignment]
    Tensor = Any  # type: ignore[assignment,misc]
    _HAS_TORCH = False


def _require_torch() -> None:
    if not _HAS_TORCH:
        raise RuntimeError(
            "memo_loss requires PyTorch but torch is not installed in this env."
        )


def memo_consistency_loss(
    predictions: "Tensor",
    labels: "Tensor",
    memo: dict | None,
    memo_confidence: float = 1.0,
    weight: float = 0.1,
) -> "Tensor":
    """메모 정합성 보조 손실.

    predictions: shape (45,) 또는 (B, 45). 확률 (sigmoid 후) 가정.
    labels:      shape (45,) 또는 (B, 45). binary 0/1.
    memo:        dict with forced_includes / forced_excludes (None 가능).
    memo_confidence: 0~1 신뢰도. 결과 손실에 곱해진다.
    weight: 번호별 패널티 강도 (기본 0.1).
    """
    _require_torch()

    if predictions.dim() == 1:
        preds = predictions.unsqueeze(0)
        lbls = labels.unsqueeze(0)
        squeezed = True
    else:
        preds = predictions
        lbls = labels
        squeezed = False

    device = preds.device
    dtype = preds.dtype
    loss = torch.zeros((), device=device, dtype=dtype)

    if not memo:
        return loss

    forced_includes = [int(n) for n in (memo.get("forced_includes") or []) if 1 <= int(n) <= 45]
    forced_excludes = [int(n) for n in (memo.get("forced_excludes") or []) if 1 <= int(n) <= 45]

    # forced_includes: label==1인 위치에서 prob ↑ 유도 (낮으면 penalty)
    for n in forced_includes:
        idx = n - 1
        # label==1인 sample만 적용
        mask = lbls[:, idx] > 0.5
        if mask.any():
            loss = loss - weight * preds[:, idx][mask].mean()

    # forced_excludes: label==0인 위치에서 prob ↓ 유도 (높으면 penalty)
    for n in forced_excludes:
        idx = n - 1
        mask = lbls[:, idx] < 0.5
        if mask.any():
            loss = loss + weight * preds[:, idx][mask].mean()

    final = float(memo_confidence) * loss

    if squeezed:
        return final
    return final


def total_loss_with_memo(
    predictions: "Tensor",
    labels: "Tensor",
    memo: dict | None,
    memo_confidence: float,
    main_criterion,
    weight: float = 0.1,
) -> "Tensor":
    """main_criterion(preds, labels) + memo_consistency_loss 합산.

    main_criterion이 logits을 요구하는 경우(예: BCEWithLogitsLoss)에는 caller가
    적절히 logits을 넘기고, memo_loss용으로는 sigmoid 확률을 따로 만든 뒤 본
    함수의 predictions에 sigmoid 결과를 넘기도록 한다 (caller 책임).
    """
    _require_torch()
    main_loss = main_criterion(predictions, labels)
    aux = memo_consistency_loss(
        predictions=predictions,
        labels=labels,
        memo=memo,
        memo_confidence=memo_confidence,
        weight=weight,
    )
    return main_loss + aux


# ----------------------------------------------------------------------- smoke
def main() -> None:
    """ASCII smoke."""
    print("[smoke] memo_loss")
    if not _HAS_TORCH:
        print("  torch not available in this env; skipping runtime checks.")
        print("[smoke] OK (import-guard only)")
        return

    import config

    torch.manual_seed(getattr(config, "RANDOM_SEED", 42))

    # 가짜 prediction (sigmoid 결과 가정)
    preds = torch.full((1, 45), 0.5)
    # forced_includes [3, 11] -> 모델이 낮게 (0.1) 예측, label=1
    preds[0, 3 - 1] = 0.1
    preds[0, 11 - 1] = 0.1
    # forced_excludes [42] -> 모델이 높게 (0.9) 예측, label=0
    preds[0, 42 - 1] = 0.9

    labels = torch.zeros((1, 45))
    labels[0, 3 - 1] = 1.0
    labels[0, 11 - 1] = 1.0
    # 42는 0 유지 (미출현)

    memo = {"forced_includes": [3, 11], "forced_excludes": [42]}

    aux_with_lowprob = memo_consistency_loss(
        preds, labels, memo, memo_confidence=1.0, weight=0.1
    )
    print(f"  aux loss (low include prob, high exclude prob) = {float(aux_with_lowprob):.4f}")

    # 정합 케이스: includes 출현 시 prob 높이고, excludes prob 낮추면 loss 감소
    preds_good = preds.clone()
    preds_good[0, 3 - 1] = 0.95
    preds_good[0, 11 - 1] = 0.95
    preds_good[0, 42 - 1] = 0.05
    aux_good = memo_consistency_loss(
        preds_good, labels, memo, memo_confidence=1.0, weight=0.1
    )
    print(f"  aux loss (good prediction) = {float(aux_good):.4f}")
    print(f"  good < bad (expect True): {float(aux_good) < float(aux_with_lowprob)}")
    print(f"  includes-hit -> negative loss (good < 0): {float(aux_good) < 0.0}")

    # null memo
    null_aux = memo_consistency_loss(preds, labels, None, memo_confidence=1.0)
    print(f"  null memo loss == 0: {float(null_aux) == 0.0}")

    # total_loss_with_memo
    bce = torch.nn.BCELoss()
    total = total_loss_with_memo(preds_good, labels, memo, 0.8, bce, weight=0.1)
    print(f"  total_loss_with_memo = {float(total):.4f}")

    print("[smoke] OK")


if __name__ == "__main__":
    main()
