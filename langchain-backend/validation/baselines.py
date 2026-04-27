"""G-5: 베이스라인 비교 모델.

본 문서 G-5 결정:
- 신규 모델은 항상 아래 베이스라인을 *학습 시점에 비교*해야 함:
  - rolling_mean (window=20) — 스칼라 지표용
  - uniform 1/45 — 메인 1~45 모델용
  - freq (학습 fold 빈도분포) — 카테고리 카운트 predictor용
- 매 epoch 베이스라인 대비 개선율 출력
- 학습 종료 시 개선율 미달이면 학습 로그에 ERROR 기록 (롤백 신호)
"""

from __future__ import annotations

import numpy as np


def baseline_rolling_mean(values: np.ndarray, window: int = 20) -> np.ndarray:
    """단순 rolling mean baseline. 스칼라 지표(sum/AC/끝수합)에 사용.

    Args:
        values: shape (n,) 시계열 값
        window: rolling window 크기

    Returns:
        shape (n,) — values[i] 예측값 = values[max(0,i-window):i].mean()
        (i=0은 NaN 회피 위해 첫 값 그대로)
    """
    n = len(values)
    out = np.zeros(n, dtype=np.float32)
    for i in range(n):
        if i == 0:
            out[i] = values[0]
        else:
            start = max(0, i - window)
            out[i] = values[start:i].mean()
    return out


def baseline_uniform(n_classes: int = 45) -> np.ndarray:
    """균등 분포 baseline. 메인 1~45 모델용.

    Returns:
        shape (n_classes,) — 모든 클래스 1/n_classes
    """
    return np.full(n_classes, 1.0 / n_classes, dtype=np.float32)


def baseline_frequency(labels: np.ndarray, n_classes: int) -> np.ndarray:
    """학습 fold 빈도분포 baseline. 카테고리 카운트 predictor용.

    Args:
        labels: shape (n_samples,) 정수 클래스 레이블 (0~n_classes-1)
        n_classes: 클래스 개수

    Returns:
        shape (n_classes,) — train fold 빈도분포 (합=1)
    """
    counts = np.bincount(labels, minlength=n_classes).astype(np.float32)
    counts = np.maximum(counts, 0.5)  # Laplace smoothing
    return counts / counts.sum()


# ── 메트릭 ──

def mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(np.abs(y_true - y_pred)))


def cross_entropy(probs_pred: np.ndarray, labels: np.ndarray, eps: float = 1e-9) -> float:
    """카테고리 분류 CE. probs_pred: (n_samples, n_classes), labels: (n_samples,) int."""
    n = len(labels)
    return float(-np.mean(np.log(np.clip(probs_pred[np.arange(n), labels], eps, 1.0))))


def kl_divergence(p: np.ndarray, q: np.ndarray, eps: float = 1e-9) -> float:
    """KL(p || q). 분포 비교용."""
    p = np.clip(p, eps, 1.0)
    q = np.clip(q, eps, 1.0)
    return float(np.sum(p * np.log(p / q)))


# ── 개선율 보고 ──

def report_improvement(
    model_metric: float,
    baseline_metric: float,
    metric_name: str = "MAE",
    higher_is_better: bool = False,
) -> dict:
    """모델이 베이스라인 대비 얼마나 개선됐는지 dict로 반환.

    Args:
        model_metric: 모델 점수
        baseline_metric: 베이스라인 점수
        metric_name: 출력용 이름
        higher_is_better: AUC/Accuracy=True, MAE/CE=False

    Returns:
        {
          "metric": str,
          "model": float, "baseline": float,
          "delta": float,                 # baseline - model (낮을수록 좋은 metric 기준)
          "relative_improvement": float,  # 비율 (소수점)
          "is_improved": bool,
        }
    """
    if higher_is_better:
        delta = model_metric - baseline_metric
        rel = delta / max(abs(baseline_metric), 1e-9)
    else:
        delta = baseline_metric - model_metric
        rel = delta / max(abs(baseline_metric), 1e-9)

    return {
        "metric": metric_name,
        "model": float(model_metric),
        "baseline": float(baseline_metric),
        "delta": float(delta),
        "relative_improvement": float(rel),
        "is_improved": delta > 0,
    }
