"""U-1: validation 패키지 단위 테스트.

대상:
- seed_utils.set_global_seed (G-6)
- normalization.GroupedNormalizer (G-3)
- timeseries_cv.time_series_splits (G-4)
- baselines.baseline_* + report_improvement (G-5)
"""

import sys
from pathlib import Path

import numpy as np
import pytest

# langchain-backend을 sys.path에 추가 (config import 위해)
BACKEND = Path(__file__).parent.parent.parent / "langchain-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from validation.seed_utils import set_global_seed, seed_worker
from validation.normalization import (
    GroupedNormalizer,
    GROUP_STANDARD,
    GROUP_POWER,
    GROUP_LOG1P,
    GROUP_MINMAX,
    GROUP_RAW,
)
from validation.timeseries_cv import time_series_splits, holdout_split
from validation.baselines import (
    baseline_rolling_mean,
    baseline_uniform,
    baseline_frequency,
    mae,
    cross_entropy,
    kl_divergence,
    report_improvement,
)


# ────────────────── G-6: seed_utils ──────────────────

class TestSeedUtils:
    def test_set_global_seed_default(self):
        seed = set_global_seed()
        assert seed == 42  # config.RANDOM_SEED

    def test_set_global_seed_explicit(self):
        seed = set_global_seed(123)
        assert seed == 123

    def test_seed_reproducibility(self):
        set_global_seed()
        a = np.random.rand(10)
        set_global_seed()
        b = np.random.rand(10)
        np.testing.assert_array_equal(a, b)

    def test_seed_worker_determinism(self):
        seed_worker(0)
        a = np.random.rand(5)
        seed_worker(0)
        b = np.random.rand(5)
        np.testing.assert_array_equal(a, b)


# ────────────────── G-3: normalization ──────────────────

class TestGroupedNormalizer:
    def test_invalid_group_raises(self):
        with pytest.raises(ValueError):
            GroupedNormalizer({"x": "unknown_group"})

    def test_standard_scaling(self):
        spec = {"a": GROUP_STANDARD, "b": GROUP_STANDARD}
        norm = GroupedNormalizer(spec)
        X = np.array([[1.0, 10.0], [2.0, 20.0], [3.0, 30.0], [4.0, 40.0]])
        out = norm.fit_transform(X, ["a", "b"])
        # StandardScaler: mean=0, std=1
        np.testing.assert_allclose(out.mean(axis=0), [0.0, 0.0], atol=1e-6)
        np.testing.assert_allclose(out.std(axis=0), [1.0, 1.0], atol=1e-6)

    def test_log1p_scaling(self):
        spec = {"x": GROUP_LOG1P}
        norm = GroupedNormalizer(spec)
        X = np.array([[0.0], [1.0], [10.0], [100.0]])
        out = norm.fit_transform(X, ["x"])
        # log1p 적용 후 StandardScaler — 0 입력은 log(1)=0
        assert out.shape == (4, 1)
        # 단조 증가 보존
        assert out[0, 0] < out[1, 0] < out[2, 0] < out[3, 0]

    def test_raw_passthrough(self):
        spec = {"flag": GROUP_RAW}
        norm = GroupedNormalizer(spec)
        X = np.array([[1.0], [0.0], [1.0]])
        out = norm.fit_transform(X, ["flag"])
        np.testing.assert_array_equal(out, X.astype(np.float32))

    def test_minmax_scaling(self):
        spec = {"x": GROUP_MINMAX}
        norm = GroupedNormalizer(spec)
        X = np.array([[0.0], [50.0], [100.0]])
        out = norm.fit_transform(X, ["x"])
        np.testing.assert_allclose(out.flatten(), [0.0, 0.5, 1.0], atol=1e-6)

    def test_fit_transform_consistency(self):
        """fit→transform vs fit_transform 동일성."""
        spec = {"a": GROUP_STANDARD}
        X = np.array([[1.0], [2.0], [3.0]])
        n1 = GroupedNormalizer(spec)
        out1 = n1.fit_transform(X, ["a"])
        n2 = GroupedNormalizer(spec)
        n2.fit(X, ["a"])
        out2 = n2.transform(X, ["a"])
        np.testing.assert_allclose(out1, out2)

    def test_no_fit_transform_raises(self):
        norm = GroupedNormalizer({"a": GROUP_STANDARD})
        with pytest.raises(RuntimeError):
            norm.transform(np.array([[1.0]]), ["a"])


# ────────────────── G-4: timeseries_cv ──────────────────

class TestTimeSeriesSplits:
    def test_split_count(self):
        splits = list(time_series_splits(n_samples=1100, n_splits=5, holdout_size=100))
        assert 1 <= len(splits) <= 5

    def test_train_always_before_val(self):
        """walk-forward 핵심 invariant: train end ≤ val start."""
        for train, val in time_series_splits(n_samples=1100, n_splits=5):
            assert max(train) < min(val), f"train.max={max(train)} >= val.min={min(val)}"

    def test_train_expanding(self):
        """expanding window: train 크기가 fold마다 증가."""
        splits = list(time_series_splits(n_samples=1100, n_splits=5))
        train_sizes = [len(t) for t, _ in splits]
        for i in range(1, len(train_sizes)):
            assert train_sizes[i] > train_sizes[i - 1], "train should expand"

    def test_too_small_raises(self):
        with pytest.raises(ValueError):
            list(time_series_splits(n_samples=50, n_splits=5))

    def test_holdout_split_basic(self):
        train, val = holdout_split(n_samples=1100, holdout_size=100)
        assert len(train) == 1000
        assert len(val) == 100
        assert max(train) < min(val)


# ────────────────── G-5: baselines ──────────────────

class TestBaselines:
    def test_rolling_mean_window(self):
        values = np.array([10.0, 20.0, 30.0, 40.0, 50.0])
        out = baseline_rolling_mean(values, window=2)
        assert len(out) == 5
        # i=2: window=2, [v0, v1].mean() = 15
        assert out[2] == pytest.approx(15.0)
        assert out[3] == pytest.approx(25.0)

    def test_uniform(self):
        u = baseline_uniform(45)
        assert len(u) == 45
        np.testing.assert_allclose(u.sum(), 1.0)
        np.testing.assert_allclose(u, 1 / 45)

    def test_frequency_normalization(self):
        labels = np.array([0, 0, 1, 2, 2, 2])
        f = baseline_frequency(labels, n_classes=3)
        assert len(f) == 3
        np.testing.assert_allclose(f.sum(), 1.0, atol=1e-6)
        # class 2 가장 빈번
        assert np.argmax(f) == 2

    def test_mae(self):
        y_true = np.array([1.0, 2.0, 3.0])
        y_pred = np.array([1.5, 2.5, 3.5])
        assert mae(y_true, y_pred) == pytest.approx(0.5)

    def test_cross_entropy(self):
        # 정답 클래스에 prob=1 → CE=0
        probs = np.array([[0.99, 0.005, 0.005], [0.01, 0.98, 0.01]])
        labels = np.array([0, 1])
        ce = cross_entropy(probs, labels)
        assert ce >= 0
        assert ce < 0.05  # 거의 정확한 예측

    def test_kl_divergence_zero(self):
        """동일 분포는 KL=0."""
        p = np.array([0.5, 0.5])
        q = np.array([0.5, 0.5])
        assert kl_divergence(p, q) == pytest.approx(0.0, abs=1e-9)

    def test_report_improvement_lower_is_better(self):
        """MAE 처럼 낮을수록 좋은 메트릭."""
        rep = report_improvement(model_metric=0.3, baseline_metric=0.5,
                                  metric_name="MAE", higher_is_better=False)
        assert rep["is_improved"] is True
        assert rep["delta"] == pytest.approx(0.2)
        assert rep["relative_improvement"] == pytest.approx(0.4)

    def test_report_improvement_higher_is_better(self):
        """AUC 처럼 높을수록 좋은 메트릭."""
        rep = report_improvement(model_metric=0.7, baseline_metric=0.6,
                                  metric_name="AUC", higher_is_better=True)
        assert rep["is_improved"] is True
        assert rep["delta"] == pytest.approx(0.1)

    def test_report_improvement_not_improved(self):
        rep = report_improvement(model_metric=0.6, baseline_metric=0.5,
                                  metric_name="MAE", higher_is_better=False)
        assert rep["is_improved"] is False
        assert rep["delta"] < 0
