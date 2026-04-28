"""카운트형 카테고리 지표 공통 feature 빌더.

categorical_count_predictor (고저·홀짝·이월수·이웃수·연번)와 21 IndependentCountPredictor가 공유.

기존 4 plan 결정:
- kind-hugging-matsumoto.md 지표 4·5/6/7/8: 공통 + target_type별 분기
- target_type: "low_high" | "odd_even" | "carryover" | "neighbor" | "consecutive"
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np


@dataclass
class CategoricalFeatureConfig:
    lag_lengths: tuple[int, ...] = (1, 2, 3, 5)
    rolling_windows: tuple[int, ...] = (5, 10, 20)
    n_classes: int = 7  # 0~6 default. consecutive는 0~5라 6 사용


DEFAULT_CFG = CategoricalFeatureConfig()


# ────────────────── 기본 빌더 ──────────────────


def build_count_lag(history: np.ndarray, lag_lengths: tuple[int, ...] = DEFAULT_CFG.lag_lengths) -> dict:
    out = {}
    for lag in lag_lengths:
        out[f"count_lag_{lag}"] = float(history[-lag]) if len(history) >= lag else 0.0
    return out


def build_count_rolling(history: np.ndarray, windows: tuple[int, ...] = DEFAULT_CFG.rolling_windows) -> dict:
    out = {}
    for w in windows:
        if len(history) >= w:
            chunk = history[-w:]
            out[f"count_rolling_mean_{w}"] = float(chunk.mean())
            out[f"count_rolling_std_{w}"] = float(chunk.std())
        else:
            out[f"count_rolling_mean_{w}"] = float(history.mean()) if len(history) > 0 else 0.0
            out[f"count_rolling_std_{w}"] = 0.0
    return out


def build_balance_score(history: np.ndarray, mid_value: int = 3) -> dict:
    """직전값 기준 균형 깨짐 정도. 고저·홀짝에서 의미 있음."""
    if len(history) == 0:
        return {"balance_score": 0.0, "consecutive_imbalance_count": 0}
    last = float(history[-1])
    balance = abs(last - mid_value)

    # 직전 회차들이 연속으로 mid_value에서 벗어났는지
    consec = 0
    for v in reversed(history):
        if abs(v - mid_value) >= 1.0:
            consec += 1
        else:
            break
    return {"balance_score": balance, "consecutive_imbalance_count": int(consec)}


def build_class_dormancy(history: np.ndarray, n_classes: int = 7) -> dict:
    """각 클래스의 마지막 출현 후 경과 회차."""
    out = {f"class_dormancy_{c}": float(len(history)) for c in range(n_classes)}
    for offset, val in enumerate(reversed(history)):
        c = int(val)
        if 0 <= c < n_classes and out[f"class_dormancy_{c}"] >= len(history):
            out[f"class_dormancy_{c}"] = float(offset)
    return out


# ────────────────── target_type별 빌더 ──────────────────


def build_carryover_extras(
    prev_round_numbers: list[int] | None,
    gnn_probs: np.ndarray | None = None,
    hot_streak: dict[int, int] | None = None,
    dormancy: dict[int, int] | None = None,
) -> dict:
    """이월수 전용 추가 feature."""
    if prev_round_numbers is None:
        return {
            "previous_round_avg_hot_streak": 0.0,
            "previous_round_avg_dormancy": 0.0,
            "previous_round_in_top10_count": 0,
        }

    hs = hot_streak or {}
    dm = dormancy or {}
    avg_hs = float(np.mean([hs.get(n, 0) for n in prev_round_numbers])) if prev_round_numbers else 0.0
    avg_dm = float(np.mean([dm.get(n, 0) for n in prev_round_numbers])) if prev_round_numbers else 0.0

    in_top10 = 0
    if gnn_probs is not None:
        top10 = set(int(i + 1) for i in np.argsort(-gnn_probs)[:10])
        in_top10 = sum(1 for n in prev_round_numbers if n in top10)

    return {
        "previous_round_avg_hot_streak": avg_hs,
        "previous_round_avg_dormancy": avg_dm,
        "previous_round_in_top10_count": int(in_top10),
    }


def build_neighbor_extras(prev_round_numbers: list[int] | None) -> dict:
    """이웃수 전용 추가 feature."""
    if not prev_round_numbers:
        return {"neighbor_pool_size": 0, "prev_round_dense_overlap": 0.0}

    pool: set[int] = set()
    for p in prev_round_numbers:
        pool.update({p - 1, p, p + 1})
    pool &= set(range(1, 46))

    # 이웃 풀 압축률: ±1 인접 군집이 풀을 줄이는 정도
    naive_pool = 3 * len(prev_round_numbers)
    actual = len(pool)
    overlap_ratio = 1.0 - actual / max(naive_pool, 1)

    return {
        "neighbor_pool_size": int(actual),
        "prev_round_dense_overlap": float(overlap_ratio),
    }


def build_consecutive_extras(
    prev_round_numbers: list[int] | None,
    gnn_top10: list[int] | None = None,
    gnn_edge_probs: dict[tuple[int, int], float] | None = None,
) -> dict:
    """연번 전용 추가 feature (가장 강한 시그널: GNN edge_prob)."""
    out = {
        "gnn_top10_pair_count": 0,
        "gnn_total_edge_prob_sum": 0.0,
        "previous_round_max_run_length": 0,
    }

    if gnn_top10:
        sorted_top = sorted(gnn_top10)
        out["gnn_top10_pair_count"] = sum(
            1 for i in range(len(sorted_top) - 1) if sorted_top[i + 1] - sorted_top[i] == 1
        )

    if gnn_edge_probs:
        out["gnn_total_edge_prob_sum"] = float(
            sum(p for (a, b), p in gnn_edge_probs.items() if abs(a - b) == 1)
        )

    if prev_round_numbers:
        s = sorted(prev_round_numbers)
        max_run, cur = 1, 1
        for i in range(1, len(s)):
            if s[i] - s[i - 1] == 1:
                cur += 1
                max_run = max(max_run, cur)
            else:
                cur = 1
        out["previous_round_max_run_length"] = int(max_run)
    return out


# ────────────────── 통합 빌더 ──────────────────


def build_categorical_features(
    history: np.ndarray,
    target_type: str,
    cfg: CategoricalFeatureConfig = DEFAULT_CFG,
    prev_round_numbers: list[int] | None = None,
    gnn_probs: np.ndarray | None = None,
    gnn_top10: list[int] | None = None,
    gnn_edge_probs: dict[tuple[int, int], float] | None = None,
    hot_streak: dict[int, int] | None = None,
    dormancy: dict[int, int] | None = None,
) -> dict:
    """카운트형 시계열 + 컨텍스트 → feature dict.

    Args:
        history: shape (T,) 카운트 시계열 (각 회차 카운트)
        target_type: 'low_high' | 'odd_even' | 'carryover' | 'neighbor' | 'consecutive'
        cfg: 빌더 설정
        prev_round_numbers: 직전 회차 6 또는 7번호 (carryover/neighbor/consecutive 입력)
        gnn_probs: shape (45,) GNN 출력 확률 (carryover 입력)
        gnn_top10: GNN top10 번호 (consecutive 입력)
        gnn_edge_probs: {(a,b): p} GNN edge_prob (consecutive 입력)
        hot_streak: {n: streak_length} (carryover 입력)
        dormancy: {n: dormancy} (carryover 입력)

    Returns:
        dict: {feature_name: value}
    """
    history = np.asarray(history, dtype=np.float64)
    n_classes = 6 if target_type == "consecutive" else 7

    out = {}
    out.update(build_count_lag(history, cfg.lag_lengths))
    out.update(build_count_rolling(history, cfg.rolling_windows))
    out.update(build_class_dormancy(history, n_classes=n_classes))

    if target_type in ("low_high", "odd_even"):
        out.update(build_balance_score(history, mid_value=3))
    elif target_type == "carryover":
        out.update(build_carryover_extras(prev_round_numbers, gnn_probs, hot_streak, dormancy))
    elif target_type == "neighbor":
        out.update(build_neighbor_extras(prev_round_numbers))
    elif target_type == "consecutive":
        out.update(build_consecutive_extras(prev_round_numbers, gnn_top10, gnn_edge_probs))

    return out


def main():
    """smoke."""
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--type", default="low_high")
    a = p.parse_args()

    if a.smoke:
        rng = np.random.default_rng(42)
        history = rng.integers(0, 7, size=50).astype(np.float64)
        feats = build_categorical_features(
            history,
            target_type=a.type,
            prev_round_numbers=[3, 11, 18, 22, 33, 44],
            gnn_probs=rng.dirichlet(np.ones(45)),
        )
        print(f"[categorical_features] smoke ({a.type}) - {len(feats)} features")
        for k, v in feats.items():
            print(f"  {k:35s} = {v:.4f}" if isinstance(v, float) else f"  {k:35s} = {v}")


if __name__ == "__main__":
    main()
