"""U-1: M-1 MetaLearner 재구축 검증.

대상:
- MetaLearner.fit_alpha (bounded optimization)
- MetaLearner._save_alpha / _load_alpha
- LottoEnsemble.load_task_weights / save_task_weights (M-1-F)
- LottoEnsemble.compute_anomaly_flag (M-1-E)
- config.TASK_PREDICTOR_MAP 정합 (M-1-A)

LottoEnsemble 자체는 7 모델 인스턴스화 시 saved_models 디렉터리를 건드림.
테스트는 *생성 없이 메서드만* 호출 가능한 부분과 tmp_path로 격리한 부분 분리.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pytest

BACKEND = Path(__file__).parent.parent.parent / "langchain-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import config


# ────────────────── M-1-A: TASK_PREDICTOR_MAP ──────────────────

class TestTaskPredictorMap:
    def test_keys_match_existing_task_weights(self):
        """TASK_PREDICTOR_MAP의 키 == ensemble.TASK_WEIGHTS의 키 (8 task)."""
        from models.ensemble import TASK_WEIGHTS
        assert set(config.TASK_PREDICTOR_MAP.keys()) == set(TASK_WEIGHTS.keys())

    def test_recommend_top_uses_main_45(self):
        assert config.TASK_PREDICTOR_MAP["recommend_top"] == ["main_45"]

    def test_filter_range_predictors(self):
        assert "sum" in config.TASK_PREDICTOR_MAP["filter_range"]
        assert "ac" in config.TASK_PREDICTOR_MAP["filter_range"]
        assert "endings_sum" in config.TASK_PREDICTOR_MAP["filter_range"]

    def test_meta_alpha_default(self):
        assert config.META_ALPHA_DEFAULT == 0.30

    def test_ae_gate_percentile(self):
        assert config.AE_GATE_PERCENTILE == 95


# ────────────────── M-1-C: fit_alpha bounded optimization ──────────────────

class TestFitAlpha:
    def test_alpha_default_loaded(self, tmp_path):
        from models.meta_learner import MetaLearner
        m = MetaLearner(save_dir=str(tmp_path))
        assert m.alpha == config.META_ALPHA_DEFAULT

    def test_fit_alpha_skips_when_too_few_samples(self, tmp_path):
        """검증 데이터가 META_ALPHA_MIN_VAL_SAMPLES 미만이면 미학습."""
        from models.meta_learner import MetaLearner
        m = MetaLearner(save_dir=str(tmp_path))
        ens = np.random.rand(10)
        meta = np.random.rand(10)
        labels = np.random.rand(10)
        result = m.fit_alpha(ens, meta, labels)
        assert result["fitted"] is False
        assert m.alpha == config.META_ALPHA_DEFAULT  # 변경 없음

    def test_fit_alpha_meta_perfect(self, tmp_path):
        """meta_pred=label, ensemble_pred=noise → α=1.0 수렴."""
        from models.meta_learner import MetaLearner
        m = MetaLearner(save_dir=str(tmp_path))
        rng = np.random.RandomState(42)
        labels = rng.randint(0, 2, 100).astype(np.float64)
        meta = labels.copy()  # 완벽
        ens = rng.rand(100)   # noise
        result = m.fit_alpha(ens, meta, labels)
        assert result["fitted"] is True
        assert result["n_samples"] == 100
        assert m.alpha > 0.9  # 메타가 압도적으로 좋음

    def test_fit_alpha_ensemble_perfect(self, tmp_path):
        """ensemble_pred=label, meta_pred=noise → α=0 수렴."""
        from models.meta_learner import MetaLearner
        m = MetaLearner(save_dir=str(tmp_path))
        rng = np.random.RandomState(42)
        labels = rng.randint(0, 2, 100).astype(np.float64)
        ens = labels.copy()   # 완벽
        meta = rng.rand(100)  # noise
        result = m.fit_alpha(ens, meta, labels)
        assert result["fitted"] is True
        assert m.alpha < 0.1  # ensemble이 압도적으로 좋음

    def test_fit_alpha_within_bounds(self, tmp_path):
        """alpha는 항상 [0, 1] 범위 내."""
        from models.meta_learner import MetaLearner
        m = MetaLearner(save_dir=str(tmp_path))
        rng = np.random.RandomState(0)
        # 다양한 시나리오 8회
        for _ in range(8):
            ens = rng.rand(100)
            meta = rng.rand(100)
            labels = rng.randint(0, 2, 100).astype(np.float64)
            r = m.fit_alpha(ens, meta, labels)
            if r["fitted"]:
                assert 0.0 <= m.alpha <= 1.0

    def test_fit_alpha_persists(self, tmp_path):
        """alpha를 학습하면 meta_alpha.json에 저장."""
        from models.meta_learner import MetaLearner
        m = MetaLearner(save_dir=str(tmp_path))
        rng = np.random.RandomState(42)
        labels = rng.randint(0, 2, 100).astype(np.float64)
        m.fit_alpha(labels.copy(), rng.rand(100), labels)

        # 새 인스턴스가 같은 alpha 로드
        m2 = MetaLearner(save_dir=str(tmp_path))
        assert m2.alpha == m.alpha

    def test_fit_alpha_length_mismatch(self, tmp_path):
        from models.meta_learner import MetaLearner
        m = MetaLearner(save_dir=str(tmp_path))
        with pytest.raises(ValueError):
            m.fit_alpha(np.zeros(10), np.zeros(20), np.zeros(10))


# ────────────────── M-1-F: Task 가중치 외부화 ──────────────────

class TestTaskWeightsExternalization:
    @pytest.fixture
    def isolated_ensemble(self, tmp_path, monkeypatch):
        """LottoEnsemble을 tmp_path 격리 환경에서 생성."""
        # 모델 인스턴스화 부담 회피 — 메서드만 호출하도록 minimal 구조
        from models import ensemble as ens_module

        class StubEnsemble:
            save_dir = str(tmp_path)
            _task_weights_path = ens_module.LottoEnsemble._task_weights_path
            load_task_weights = ens_module.LottoEnsemble.load_task_weights
            save_task_weights = ens_module.LottoEnsemble.save_task_weights

        return StubEnsemble()

    def test_default_when_no_file(self, isolated_ensemble):
        """task_weights.json 없으면 default TASK_WEIGHTS 사용."""
        from models.ensemble import TASK_WEIGHTS
        out = isolated_ensemble.load_task_weights()
        for task in TASK_WEIGHTS:
            assert task in out
            for m, v in TASK_WEIGHTS[task].items():
                assert out[task][m] == v

    def test_external_overrides_default(self, isolated_ensemble, tmp_path):
        """외부 파일 값이 우선."""
        path = tmp_path / "task_weights.json"
        path.write_text(json.dumps({
            "recommend_top": {"xgboost": 0.99}
        }))
        out = isolated_ensemble.load_task_weights()
        assert out["recommend_top"]["xgboost"] == 0.99
        # 다른 모델은 default 유지
        from models.ensemble import TASK_WEIGHTS
        assert out["recommend_top"]["lstm"] == TASK_WEIGHTS["recommend_top"]["lstm"]

    def test_save_round_trip(self, isolated_ensemble, tmp_path):
        from models.ensemble import TASK_WEIGHTS
        weights = {task: w.copy() for task, w in TASK_WEIGHTS.items()}
        weights["recommend_top"]["xgboost"] = 0.42
        isolated_ensemble.save_task_weights(weights)

        out = isolated_ensemble.load_task_weights()
        assert out["recommend_top"]["xgboost"] == 0.42

    def test_invalid_external_falls_back(self, isolated_ensemble, tmp_path):
        """음수·문자열 등 invalid 값은 무시하고 default 사용."""
        path = tmp_path / "task_weights.json"
        path.write_text(json.dumps({
            "recommend_top": {"xgboost": -1.0, "lstm": "invalid"}
        }))
        out = isolated_ensemble.load_task_weights()
        from models.ensemble import TASK_WEIGHTS
        # invalid 값들은 default 유지
        assert out["recommend_top"]["xgboost"] == TASK_WEIGHTS["recommend_top"]["xgboost"]
        assert out["recommend_top"]["lstm"] == TASK_WEIGHTS["recommend_top"]["lstm"]


# ────────────────── M-1-E: compute_anomaly_flag ──────────────────

class TestAnomalyFlag:
    """LottoEnsemble.compute_anomaly_flag — AE 미학습 환경에서도 안전 fallback."""

    @pytest.fixture
    def stub(self, tmp_path):
        """compute_anomaly_flag만 테스트할 수 있는 minimal stub."""
        from models import ensemble as ens_module

        class FakeAE:
            def predict_exclusions(self, draws, threshold=0.0):
                # 각 번호별 오차 dict (단순화)
                if not draws:
                    return {}
                # draws[0] number 기반 가짜 오차
                avg_num = sum(draws[0].get("numbers", [])) / max(len(draws[0].get("numbers", [])), 1)
                return {n: float(avg_num / 100.0) for n in range(1, 46)}

        class StubEnsemble:
            save_dir = str(tmp_path)
            models = {"autoencoder": FakeAE()}
            _ae_threshold_path = ens_module.LottoEnsemble._ae_threshold_path
            _load_ae_threshold = ens_module.LottoEnsemble._load_ae_threshold
            compute_anomaly_flag = ens_module.LottoEnsemble.compute_anomaly_flag
            calibrate_anomaly_threshold = ens_module.LottoEnsemble.calibrate_anomaly_threshold

        return StubEnsemble()

    def test_no_draws_unavailable(self, stub):
        out = stub.compute_anomaly_flag([])
        assert out["available"] is False
        assert out["is_anomaly"] is False

    def test_normal_draws_under_threshold(self, stub):
        draws = [{"round": i, "numbers": [1, 2, 3, 4, 5, 6]} for i in range(5)]
        out = stub.compute_anomaly_flag(draws, threshold=0.5)
        assert out["available"] is True
        # 평균 번호 = (1+2+3+4+5+6)/6 = 3.5, /100 = 0.035 < 0.5
        assert out["is_anomaly"] is False
        assert out["recon_error"] == pytest.approx(0.035, abs=1e-4)

    def test_anomaly_above_threshold(self, stub):
        draws = [{"round": i, "numbers": [40, 41, 42, 43, 44, 45]} for i in range(5)]
        out = stub.compute_anomaly_flag(draws, threshold=0.3)
        # 평균 번호 = 42.5, /100 = 0.425 > 0.3
        assert out["is_anomaly"] is True

    def test_calibrate_threshold_persists(self, stub, tmp_path):
        rng = np.random.RandomState(42)
        draws = [{"round": i, "numbers": list(rng.choice(range(1, 46), 6, replace=False))}
                 for i in range(20)]
        result = stub.calibrate_anomaly_threshold(draws, percentile=95)
        assert result["fitted"] is True
        # 파일 저장 확인
        path = tmp_path / "ae_anomaly_threshold.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["threshold"] == result["threshold"]
        # 95p 이므로 mean보다 큼
        assert result["threshold"] >= result["mean"]
