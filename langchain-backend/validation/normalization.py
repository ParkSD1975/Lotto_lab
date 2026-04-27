"""G-3: 변수 그룹별 차등 정규화 래퍼.

본 문서 G-3 결정에 따라 feature를 그룹별로 다른 scaler에 매핑한다:

- StandardScaler   : lag, rolling_mean, diff, zscore (정규분포 가까운 연속값)
- PowerTransformer : rolling_std, volatility (long-tail 분포)
- log1p+Standard   : count, dormancy (0 이상 정수 long-tail)
- raw              : binary, one-hot, 이미 정규화된 0~1
- minmax           : 정수 범위 (0~6 등)

핵심 원칙:
- fit은 train fold에만 (data leakage 방지)
- walk-forward 매 fold마다 재fit
- transform 시 unknown feature 그룹은 raw 그대로
"""

from __future__ import annotations

import numpy as np
from sklearn.preprocessing import StandardScaler, PowerTransformer, MinMaxScaler


# ── 그룹 정의 (predictor가 feature → 그룹 매핑을 명시) ──
GROUP_STANDARD = "standard"        # StandardScaler
GROUP_POWER = "power"              # PowerTransformer (Yeo-Johnson)
GROUP_LOG1P = "log1p"              # log1p + StandardScaler
GROUP_MINMAX = "minmax"            # MinMaxScaler [0, 1]
GROUP_RAW = "raw"                  # 변환 없음

VALID_GROUPS = {GROUP_STANDARD, GROUP_POWER, GROUP_LOG1P, GROUP_MINMAX, GROUP_RAW}


class GroupedNormalizer:
    """Feature 이름 → 그룹 매핑을 받아 fit/transform한다.

    Example:
        >>> spec = {
        ...     "sum_lag_1": "standard",
        ...     "rolling_std_5": "power",
        ...     "dormancy": "log1p",
        ...     "is_anomaly": "raw",
        ... }
        >>> norm = GroupedNormalizer(spec)
        >>> norm.fit(train_df)
        >>> X_train = norm.transform(train_df)
        >>> X_val = norm.transform(val_df)   # train의 scaler 재사용
    """

    def __init__(self, feature_groups: dict[str, str]):
        for name, group in feature_groups.items():
            if group not in VALID_GROUPS:
                raise ValueError(f"Unknown group '{group}' for '{name}'. Valid: {VALID_GROUPS}")
        self.feature_groups = feature_groups
        self._scalers: dict[str, object] = {}
        self._fitted = False

    def fit(self, X: np.ndarray | "pandas.DataFrame", feature_names: list[str] | None = None):
        """train fold에만 fit.

        X: shape (n_samples, n_features) 또는 DataFrame.
        feature_names: ndarray 입력 시 컬럼 이름 list.
        """
        names, arr = self._unwrap(X, feature_names)

        # 그룹별로 컬럼 모아 fit
        groups: dict[str, list[int]] = {g: [] for g in VALID_GROUPS}
        for i, name in enumerate(names):
            group = self.feature_groups.get(name, GROUP_RAW)
            groups[group].append(i)

        if groups[GROUP_STANDARD]:
            sc = StandardScaler()
            sc.fit(arr[:, groups[GROUP_STANDARD]])
            self._scalers[GROUP_STANDARD] = (sc, groups[GROUP_STANDARD])

        if groups[GROUP_POWER]:
            pt = PowerTransformer(method="yeo-johnson", standardize=True)
            pt.fit(arr[:, groups[GROUP_POWER]])
            self._scalers[GROUP_POWER] = (pt, groups[GROUP_POWER])

        if groups[GROUP_LOG1P]:
            sub = np.log1p(np.clip(arr[:, groups[GROUP_LOG1P]], a_min=0, a_max=None))
            sc = StandardScaler()
            sc.fit(sub)
            self._scalers[GROUP_LOG1P] = (sc, groups[GROUP_LOG1P])

        if groups[GROUP_MINMAX]:
            mm = MinMaxScaler()
            mm.fit(arr[:, groups[GROUP_MINMAX]])
            self._scalers[GROUP_MINMAX] = (mm, groups[GROUP_MINMAX])

        # raw는 fit 불필요
        self._raw_indices = groups[GROUP_RAW]
        self._fitted = True
        self._feature_names = names
        return self

    def transform(self, X, feature_names: list[str] | None = None) -> np.ndarray:
        if not self._fitted:
            raise RuntimeError("fit() must be called before transform()")
        _, arr = self._unwrap(X, feature_names)
        out = arr.copy().astype(np.float32)

        if GROUP_STANDARD in self._scalers:
            sc, idx = self._scalers[GROUP_STANDARD]
            out[:, idx] = sc.transform(arr[:, idx])

        if GROUP_POWER in self._scalers:
            pt, idx = self._scalers[GROUP_POWER]
            out[:, idx] = pt.transform(arr[:, idx])

        if GROUP_LOG1P in self._scalers:
            sc, idx = self._scalers[GROUP_LOG1P]
            sub = np.log1p(np.clip(arr[:, idx], a_min=0, a_max=None))
            out[:, idx] = sc.transform(sub)

        if GROUP_MINMAX in self._scalers:
            mm, idx = self._scalers[GROUP_MINMAX]
            out[:, idx] = mm.transform(arr[:, idx])

        return out

    def fit_transform(self, X, feature_names: list[str] | None = None) -> np.ndarray:
        return self.fit(X, feature_names).transform(X, feature_names)

    @staticmethod
    def _unwrap(X, feature_names):
        try:
            import pandas as pd
            if isinstance(X, pd.DataFrame):
                return list(X.columns), X.to_numpy()
        except ImportError:
            pass
        if feature_names is None:
            raise ValueError("feature_names required for ndarray input")
        return feature_names, np.asarray(X)
