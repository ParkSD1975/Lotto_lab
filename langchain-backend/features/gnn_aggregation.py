"""기존 GNN 출력(45 logits) → 21지표 집계식 재사용.

새 GNN 학습 없이 기존 graph attention 결과를 그대로 다양한 지표로 변환.
kind-hugging-matsumoto.md "기존 GNN 출력 집계 활용" 섹션의 매핑 그대로 구현.

지표별 집계식:
| 지표 | 식 |
|---|---|
| 총합 | Σ(n × softmax(logit_n)) × 6 / Σ(top6 softmax) |
| 끝수합 | Σ((n%10) × prob_n) |
| 끝수 분포 10D | digit_k = Σ(prob_n where n%10==k) |
| 고개수 | Σ(prob_n where n>22) |
| 홀개수 | Σ(prob_n where n%2==1) |
| 번호대 5D | 1-9 / 10대 / 20대 / 30대 / 40대 |
| 9궁 9D | 9 분할 |
| 로또용지 14D | 가로 7 + 세로 7 |
| 소수/합성수 | 소수 집합 prob 합 |
| 배수 6D | 3·4·5·7·8 + 외 |
"""

from __future__ import annotations

import numpy as np

import config


# ────────────────── 풀 정의 ──────────────────


def softmax(logits: np.ndarray) -> np.ndarray:
    """softmax with numerical stability."""
    z = logits - logits.max()
    exp = np.exp(z)
    return exp / exp.sum()


def normalize_to_probs(arr: np.ndarray) -> np.ndarray:
    """이미 prob일 수도 있고 logit일 수도 있는 입력을 prob로 정규화."""
    arr = np.asarray(arr, dtype=np.float64).flatten()
    if arr.shape[0] != 45:
        raise ValueError(f"GNN 출력은 (45,)여야 함. 받은 shape: {arr.shape}")
    if (arr >= 0).all() and abs(arr.sum() - 1.0) < 1e-3:
        return arr
    return softmax(arr)


# ────────────────── 집계식 ──────────────────


def aggregate_sum(probs45: np.ndarray) -> float:
    """expected_sum = E[n] x 6.

    plan의 top6_sum 분모 표기는 typo로 판단 (균등 분포 검증 시 138 정상 산출).
    분자 단독으로 6번호 sum의 기댓값.
    """
    p = normalize_to_probs(probs45)
    nums = np.arange(1, 46, dtype=np.float64)
    return float((nums * p).sum() * 6)


def aggregate_sum_top6_weighted(probs45: np.ndarray) -> float:
    """대안 추정: top6 번호의 prob-weighted 평균 x 6. SHAP/diagnostic용."""
    p = normalize_to_probs(probs45)
    nums = np.arange(1, 46, dtype=np.float64)
    top6_idx = np.argsort(-p)[:6]
    top6_p = p[top6_idx]
    top6_p_sum = top6_p.sum()
    if top6_p_sum < 1e-9:
        return 0.0
    return float((nums[top6_idx] * top6_p / top6_p_sum).sum() * 6)


def aggregate_endings_sum(probs45: np.ndarray) -> float:
    """6번호 끝수합의 기댓값. E[n%10] x 6."""
    p = normalize_to_probs(probs45)
    nums = np.arange(1, 46)
    return float(np.sum((nums % 10) * p) * 6)


def aggregate_endings_distribution(probs45: np.ndarray) -> np.ndarray:
    """digit_k = Σ(prob_n where n%10==k). returns shape (10,)."""
    p = normalize_to_probs(probs45)
    out = np.zeros(10)
    for n_idx in range(45):
        n = n_idx + 1
        out[n % 10] += p[n_idx]
    return out


def aggregate_high_count(probs45: np.ndarray) -> float:
    """expected = Σ(prob_n where n>22) × 6."""
    p = normalize_to_probs(probs45)
    return float(p[22:].sum() * 6)


def aggregate_odd_count(probs45: np.ndarray) -> float:
    p = normalize_to_probs(probs45)
    odd_indices = [i for i in range(45) if (i + 1) % 2 == 1]
    return float(p[odd_indices].sum() * 6)


def aggregate_decade_distribution(probs45: np.ndarray) -> np.ndarray:
    """5 카테고리: [1-9, 10-19, 20-29, 30-39, 40-45]."""
    p = normalize_to_probs(probs45)
    boundaries = [(1, 9), (10, 19), (20, 29), (30, 39), (40, 45)]
    out = np.zeros(5)
    for k, (lo, hi) in enumerate(boundaries):
        out[k] = p[lo - 1 : hi].sum() * 6
    return out


def aggregate_gung_distribution(probs45: np.ndarray) -> np.ndarray:
    """9궁 9 분할.

    표준 9궁:
      G0 1-5, G1 6-10, G2 11-15, G3 16-20, G4 21-25,
      G5 26-30, G6 31-35, G7 36-40, G8 41-45
    """
    p = normalize_to_probs(probs45)
    boundaries = [(1, 5), (6, 10), (11, 15), (16, 20), (21, 25),
                  (26, 30), (31, 35), (36, 40), (41, 45)]
    out = np.zeros(9)
    for k, (lo, hi) in enumerate(boundaries):
        out[k] = p[lo - 1 : hi].sum() * 6
    return out


def aggregate_lotto_paper(probs45: np.ndarray) -> np.ndarray:
    """로또용지 14 (가로 7 × 세로 7 미존재 — 5×9에서 가로 5, 세로 9 + 1).

    실제 로또용지: 1~45를 5행 × 9열 그리드.
      row k = numbers (k*9 + 1) ~ (k*9 + 9), k=0..4 (row 4: 37~45)
      col k = numbers (k+1, k+10, k+19, k+28, k+37), k=0..8

    가로 5 + 세로 9 + 종합 = 14? plan은 가로 7 + 세로 7 = 14.
    실제 한국 로또 용지 그리드는 5×9 + 1(45 단독). 본 구현은 5+9=14 근사 (행/열 분포).
    """
    p = normalize_to_probs(probs45)
    rows = np.zeros(5)
    cols = np.zeros(9)
    for n in range(1, 46):
        idx = n - 1
        # 0-indexed: row = (n-1) // 9, col = (n-1) % 9
        rows[idx // 9] += p[idx]
        cols[idx % 9] += p[idx]
    return np.concatenate([rows * 6, cols * 6])  # shape (14,)


def aggregate_prime_count(probs45: np.ndarray) -> float:
    p = normalize_to_probs(probs45)
    prime_indices = [n - 1 for n in config.PRIMES]
    return float(p[prime_indices].sum() * 6)


def aggregate_composite_count(probs45: np.ndarray) -> float:
    """1과 소수를 제외한 4~45 중 합성수."""
    p = normalize_to_probs(probs45)
    primes = config.PRIMES
    composite_indices = [n - 1 for n in range(2, 46) if n not in primes and n != 1]
    return float(p[composite_indices].sum() * 6)


def aggregate_one_count(probs45: np.ndarray) -> float:
    """unified-plan #15: 1은 별도 카테고리."""
    p = normalize_to_probs(probs45)
    return float(p[0] * 6)


def aggregate_multiple_distribution(probs45: np.ndarray) -> dict:
    """배수 6D: 3·4·5·7·8배수 + 배수외."""
    p = normalize_to_probs(probs45)
    out = {}
    counted = set()
    for k in (3, 4, 5, 7, 8):
        indices = [n - 1 for n in range(k, 46, k)]
        out[f"multiple_{k}"] = float(p[indices].sum() * 6)
        counted.update(n + 1 for n in indices)
    other_indices = [n - 1 for n in range(1, 46) if n not in counted]
    out["multiple_other"] = float(p[other_indices].sum() * 6)
    return out


def aggregate_square_count(probs45: np.ndarray) -> float:
    p = normalize_to_probs(probs45)
    indices = [n - 1 for n in config.SQUARES]
    return float(p[indices].sum() * 6)


def aggregate_triangular_count(probs45: np.ndarray) -> float:
    p = normalize_to_probs(probs45)
    indices = [n - 1 for n in config.TRIANGULARS]
    return float(p[indices].sum() * 6)


def aggregate_twin_count(probs45: np.ndarray) -> float:
    """동형수 (11배수: 11, 22, 33, 44)."""
    p = normalize_to_probs(probs45)
    indices = [11 - 1, 22 - 1, 33 - 1, 44 - 1]
    return float(p[indices].sum() * 6)


# ────────────────── 통합 ──────────────────


def aggregate_all(probs45: np.ndarray) -> dict:
    """45 prob → 21지표 모든 집계식 한 번에. predictor 입력 evidence로 사용."""
    return {
        "expected_sum": aggregate_sum(probs45),
        "expected_endings_sum": aggregate_endings_sum(probs45),
        "endings_distribution": aggregate_endings_distribution(probs45).tolist(),
        "expected_high_count": aggregate_high_count(probs45),
        "expected_odd_count": aggregate_odd_count(probs45),
        "decade_distribution": aggregate_decade_distribution(probs45).tolist(),
        "gung_distribution": aggregate_gung_distribution(probs45).tolist(),
        "lotto_paper_distribution": aggregate_lotto_paper(probs45).tolist(),
        "expected_prime_count": aggregate_prime_count(probs45),
        "expected_composite_count": aggregate_composite_count(probs45),
        "expected_one_count": aggregate_one_count(probs45),
        "multiple_distribution": aggregate_multiple_distribution(probs45),
        "expected_square_count": aggregate_square_count(probs45),
        "expected_triangular_count": aggregate_triangular_count(probs45),
        "expected_twin_count": aggregate_twin_count(probs45),
    }


def main():
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--smoke", action="store_true")
    args = p.parse_args()

    if args.smoke:
        rng = np.random.default_rng(42)
        probs = rng.dirichlet(np.ones(45))
        agg = aggregate_all(probs)
        print(f"[gnn_aggregation] smoke - {len(agg)} aggregated metrics")
        for k, v in agg.items():
            if isinstance(v, list):
                print(f"  {k:30s} = list len={len(v)}, sum={sum(v):.4f}")
            elif isinstance(v, dict):
                print(f"  {k:30s} = dict {list(v.keys())}, total={sum(v.values()):.4f}")
            else:
                print(f"  {k:30s} = {v:.4f}")


if __name__ == "__main__":
    main()
