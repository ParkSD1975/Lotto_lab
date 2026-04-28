"""스칼라 지표 공통 feature 빌더.

sum_predictor / ac_predictor / endings_predictor 등 스칼라 회귀 지표가
공유하는 lag/rolling/zscore/diff/consecutive/volatility/trend feature 빌더.

기존 4 plan의 결정:
- kind-hugging-matsumoto.md 지표 1 (총합) Part C: 13개 공통 feature
- 지표 3 (AC값) 1-3 Part A: AC 고유 2개 추가 (ac_to_sum_ratio, ac_to_consecutive_count)
- features/scalar_features.py 일반화 (sum/ac/endings_sum 공통 호출)

정규화는 별도 (validation/normalization.py 호출). 본 모듈은 raw feature 산출만.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


# ────────────────── 데이터 클래스 ──────────────────


@dataclass
class ScalarFeatureConfig:
    """스칼라 feature 빌더 설정."""

    lag_lengths: tuple[int, ...] = (1, 2, 3, 5)
    rolling_windows: tuple[int, ...] = (5, 10, 20)
    zscore_windows: tuple[int, ...] = (5, 20)  # short, long
    diff_lengths: tuple[int, ...] = (1, 2)
    trend_window: int = 5
    trend_categories: int = 5  # one-hot 5개 (steeply_up, mild_up, flat, mild_down, steeply_down)


DEFAULT_CFG = ScalarFeatureConfig()


# ────────────────── 빌더 ──────────────────


def build_lag_features(history: np.ndarray, lag_lengths: tuple[int, ...] = DEFAULT_CFG.lag_lengths) -> dict:
    """직전 N회차 값. shape (T,) → {'lag_1': v1, ...}."""
    out = {}
    for lag in lag_lengths:
        out[f"lag_{lag}"] = float(history[-lag]) if len(history) >= lag else 0.0
    return out


def build_rolling_stats(history: np.ndarray, windows: tuple[int, ...] = DEFAULT_CFG.rolling_windows) -> dict:
    """rolling mean/std/min/max. window별."""
    out = {}
    for w in windows:
        if len(history) >= w:
            chunk = history[-w:]
            out[f"rolling_mean_{w}"] = float(chunk.mean())
            out[f"rolling_std_{w}"] = float(chunk.std())
            if w == 10:
                out[f"rolling_min_{w}"] = float(chunk.min())
                out[f"rolling_max_{w}"] = float(chunk.max())
        else:
            out[f"rolling_mean_{w}"] = float(history.mean()) if len(history) > 0 else 0.0
            out[f"rolling_std_{w}"] = 0.0
            if w == 10:
                out[f"rolling_min_{w}"] = float(history.min()) if len(history) > 0 else 0.0
                out[f"rolling_max_{w}"] = float(history.max()) if len(history) > 0 else 0.0
    return out


def build_zscore(history: np.ndarray, windows: tuple[int, ...] = DEFAULT_CFG.zscore_windows) -> dict:
    """zscore_short, zscore_long. 직전값을 윈도우 평균±편차에 비교."""
    out = {}
    if len(history) == 0:
        return {"zscore_short": 0.0, "zscore_long": 0.0}
    last = float(history[-1])
    for w, label in zip(windows, ("short", "long")):
        if len(history) >= w:
            chunk = history[-w:]
            mean = float(chunk.mean())
            std = float(chunk.std())
            out[f"zscore_{label}"] = (last - mean) / max(std, 1e-6)
        else:
            out[f"zscore_{label}"] = 0.0
    return out


def build_diff(history: np.ndarray, diff_lengths: tuple[int, ...] = DEFAULT_CFG.diff_lengths) -> dict:
    """diff_1, diff_2. 직전 회차 대비 차이."""
    out = {}
    for d in diff_lengths:
        if len(history) > d:
            out[f"diff_{d}"] = float(history[-1] - history[-1 - d])
        else:
            out[f"diff_{d}"] = 0.0
    return out


def build_consecutive_runs(history: np.ndarray) -> dict:
    """연속 상승/하락 횟수.

    consecutive_up: 가장 최근 다이렉션이 상승일 때 그 길이. 하락이면 0.
    consecutive_down: 반대.
    """
    if len(history) < 2:
        return {"consecutive_up": 0, "consecutive_down": 0}
    diffs = np.diff(history)
    up, down = 0, 0
    for d in reversed(diffs):
        if d > 0:
            if down > 0:
                break
            up += 1
        elif d < 0:
            if up > 0:
                break
            down += 1
        else:
            break
    return {"consecutive_up": int(up), "consecutive_down": int(down)}


def build_volatility_ratio(history: np.ndarray) -> dict:
    """단기 변동성 / 장기 변동성. 1 초과면 변동성 증가 국면."""
    if len(history) < 20:
        return {"volatility_ratio": 1.0}
    short_std = float(history[-5:].std())
    long_std = float(history[-20:].std())
    return {"volatility_ratio": short_std / max(long_std, 1e-6)}


def build_trend_pattern(history: np.ndarray, window: int = DEFAULT_CFG.trend_window) -> dict:
    """직전 window 회차의 추세 패턴을 5 카테고리 one-hot.

    카테고리: steeply_up / mild_up / flat / mild_down / steeply_down
    임계값: |slope| 기준 (history std 단위)
    """
    if len(history) < window:
        return {f"trend_pattern_{i}": 0 for i in range(5)} | {"trend_pattern_2": 1}  # flat default

    chunk = history[-window:]
    x = np.arange(window)
    slope, _ = np.polyfit(x, chunk, 1)
    norm_slope = slope / max(history[-20:].std() if len(history) >= 20 else chunk.std(), 1e-6)

    out = {f"trend_pattern_{i}": 0 for i in range(5)}
    if norm_slope > 0.5:
        out["trend_pattern_0"] = 1  # steeply_up
    elif norm_slope > 0.1:
        out["trend_pattern_1"] = 1  # mild_up
    elif norm_slope > -0.1:
        out["trend_pattern_2"] = 1  # flat
    elif norm_slope > -0.5:
        out["trend_pattern_3"] = 1  # mild_down
    else:
        out["trend_pattern_4"] = 1  # steeply_down
    return out


# ────────────────── 통합 빌더 ──────────────────


def build_scalar_features(
    history: np.ndarray,
    cfg: ScalarFeatureConfig = DEFAULT_CFG,
) -> dict:
    """스칼라 시계열 → 통합 feature dict (~22 feature).

    Args:
        history: shape (T,) 스칼라 시계열 (sum/ac/endings_sum 등)
        cfg: 빌더 설정

    Returns:
        dict: {feature_name: value}
    """
    history = np.asarray(history, dtype=np.float64)
    out = {}
    out.update(build_lag_features(history, cfg.lag_lengths))
    out.update(build_rolling_stats(history, cfg.rolling_windows))
    out.update(build_zscore(history, cfg.zscore_windows))
    out.update(build_diff(history, cfg.diff_lengths))
    out.update(build_consecutive_runs(history))
    out.update(build_volatility_ratio(history))
    out.update(build_trend_pattern(history, cfg.trend_window))
    return out


def build_scalar_feature_matrix(
    history: np.ndarray,
    cfg: ScalarFeatureConfig = DEFAULT_CFG,
    min_history: int = 20,
) -> tuple[np.ndarray, list[str]]:
    """walk-forward로 매 회차에서 그 시점까지의 history만 사용한 feature matrix 생성.

    학습용. min_history 미만은 skip.

    Returns:
        X: shape (N - min_history, num_features)
        feature_names: list[str]
    """
    history = np.asarray(history, dtype=np.float64)
    rows, names = [], None
    for i in range(min_history, len(history) + 1):
        sub = history[:i]
        feats = build_scalar_features(sub, cfg)
        if names is None:
            names = list(feats.keys())
        rows.append([feats[k] for k in names])
    return np.array(rows, dtype=np.float64), (names or [])


# ────────────────── AC 고유 cross-feature ──────────────────


def build_ac_cross_features(
    sum_history: np.ndarray,
    ac_history: np.ndarray,
    consecutive_history: np.ndarray | None = None,
) -> dict:
    """AC predictor 전용: sum/연번과의 비.

    kind-hugging-matsumoto.md 지표 3 1-3 Part A 지정 feature.
    """
    out = {}
    if len(ac_history) > 0 and len(sum_history) > 0:
        last_sum = float(sum_history[-1])
        last_ac = float(ac_history[-1])
        out["ac_to_sum_ratio_lag_1"] = last_ac / max(last_sum, 1e-6)
    else:
        out["ac_to_sum_ratio_lag_1"] = 0.0

    if consecutive_history is not None and len(consecutive_history) > 0 and len(ac_history) > 0:
        out["ac_to_consecutive_count_lag_1"] = float(ac_history[-1]) / max(float(consecutive_history[-1]) + 1.0, 1e-6)
    else:
        out["ac_to_consecutive_count_lag_1"] = 0.0
    return out


# ────────────────── CLI smoke ──────────────────


def main():
    """python -m features.scalar_features --smoke."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()

    if args.smoke:
        rng = np.random.default_rng(42)
        sums = rng.normal(138, 30, size=100)
        feats = build_scalar_features(sums)
        print(f"[scalar_features] smoke - {len(feats)} features generated")
        for k, v in feats.items():
            print(f"  {k:30s} = {v:.4f}" if isinstance(v, float) else f"  {k:30s} = {v}")

        X, names = build_scalar_feature_matrix(sums, min_history=20)
        print(f"\n[scalar_features] matrix shape: {X.shape}, num names: {len(names)}")


if __name__ == "__main__":
    main()
