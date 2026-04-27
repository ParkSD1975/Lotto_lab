"""U-1: T-1 (TrainingOrchestrator + posthoc_gate) + S-1 (SLAMonitor) 검증."""

import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pytest

BACKEND = Path(__file__).parent.parent.parent / "langchain-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


# ────────────────── T-1: posthoc_gate ──────────────────


class TestPosthocGate:
    def test_no_gates_returns_normalized_input(self):
        from models.posthoc_gate import PosthocGate
        g = PosthocGate()
        probs = {n: 1.0 / 45.0 for n in range(1, 46)}
        out = g.apply(probs)
        assert sum(out.values()) == pytest.approx(1.0, abs=1e-6)

    def test_gate_modifies_probs(self):
        from models.posthoc_gate import PosthocGate
        g = PosthocGate()
        # 1번 prob 2배 게이트
        def boost_one(arr):
            arr = arr.copy()
            arr[0] *= 2
            return arr
        g.register("boost_one", boost_one)
        probs = {n: 1.0 / 45.0 for n in range(1, 46)}
        out = g.apply(probs)
        # 1번이 다른 번호보다 높음
        assert out[1] > out[2]
        # 합 정규화
        assert sum(out.values()) == pytest.approx(1.0, abs=1e-6)

    def test_gate_failure_skipped(self):
        """게이트 raise 시 raw 보존."""
        from models.posthoc_gate import PosthocGate
        g = PosthocGate()
        def bad(arr):
            raise RuntimeError("intentional")
        g.register("bad", bad)
        probs = {n: 1.0 / 45.0 for n in range(1, 46)}
        out = g.apply(probs)
        assert sum(out.values()) == pytest.approx(1.0, abs=1e-6)

    def test_excluded_set_gate(self):
        from models.posthoc_gate import PosthocGate, build_excluded_set_gate
        g = PosthocGate()
        g.register("exclude", build_excluded_set_gate({3, 14}))
        probs = {n: 1.0 / 45.0 for n in range(1, 46)}
        out = g.apply(probs)
        assert out[3] == 0.0
        assert out[14] == 0.0
        # 다른 번호는 0이 아니고 합=1
        assert out[1] > 0
        assert sum(out.values()) == pytest.approx(1.0, abs=1e-6)

    def test_decade_gate_shifts_distribution(self):
        from models.posthoc_gate import PosthocGate, build_decade_gate
        g = PosthocGate()
        # 10대(10~19)에 5개 몰림 예측 → 10대 prob 부스트
        decade_dist = [0.5, 5.0, 0.2, 0.2, 0.1]
        g.register("decade", build_decade_gate(decade_dist, strength=1.0))
        probs = {n: 1.0 / 45.0 for n in range(1, 46)}
        out = g.apply(probs)
        # 10대 평균 prob > 다른 번호대 평균
        decade_2 = np.mean([out[n] for n in range(10, 20)])
        decade_1 = np.mean([out[n] for n in range(1, 10)])
        assert decade_2 > decade_1

    def test_invalid_decade_dist(self):
        from models.posthoc_gate import build_decade_gate
        with pytest.raises(ValueError):
            build_decade_gate([1, 2, 3])  # 5개 아님

    def test_unwrap_invalid_shape(self):
        from models.posthoc_gate import PosthocGate
        g = PosthocGate()
        with pytest.raises(ValueError):
            g.apply(np.zeros(10))


# ────────────────── T-1: TrainingOrchestrator ──────────────────


class TestTrainingOrchestrator:
    def test_init_creates_stage_dirs(self, tmp_path):
        from pipeline.training_orchestrator import TrainingOrchestrator
        orch = TrainingOrchestrator(save_dir=str(tmp_path / "cache"))
        for stage_id in range(7):
            assert (tmp_path / "cache" / f"stage{stage_id}").exists()

    def test_register_and_list(self, tmp_path):
        from pipeline.training_orchestrator import (
            TrainingOrchestrator, PredictorEntry, STAGE_PHASE1,
        )
        orch = TrainingOrchestrator(save_dir=str(tmp_path / "cache"))
        entry = PredictorEntry(
            predictor_id="digit_10",
            stage=STAGE_PHASE1,
            train_fn=lambda draws: {"success": True},
            cache_key="digit_10",
        )
        orch.register(entry)
        out = orch.list_stage(STAGE_PHASE1)
        assert len(out) == 1
        assert out[0].predictor_id == "digit_10"

    def test_register_duplicate_raises(self, tmp_path):
        from pipeline.training_orchestrator import (
            TrainingOrchestrator, PredictorEntry, STAGE_PHASE1,
        )
        orch = TrainingOrchestrator(save_dir=str(tmp_path / "cache"))
        e = PredictorEntry("x", STAGE_PHASE1, lambda d: {}, "x")
        orch.register(e)
        with pytest.raises(ValueError):
            orch.register(e)

    def test_run_stage_marker_created(self, tmp_path):
        """train_fn 성공 시 .done marker 파일 생성."""
        from pipeline.training_orchestrator import (
            TrainingOrchestrator, PredictorEntry, STAGE_PHASE1,
        )
        orch = TrainingOrchestrator(save_dir=str(tmp_path / "cache"))
        orch.register(PredictorEntry(
            predictor_id="p1",
            stage=STAGE_PHASE1,
            train_fn=lambda draws: {"success": True},
            cache_key="p1",
        ))
        out = orch.run_stage(STAGE_PHASE1, draws=[])
        assert out["n_predictors"] == 1
        assert out["results"][0]["success"] is True
        assert os.path.exists(orch.cache_marker_path(STAGE_PHASE1, "p1"))

    def test_run_stage_with_failure(self, tmp_path):
        """train_fn raise 시 success=False, marker 미생성."""
        from pipeline.training_orchestrator import (
            TrainingOrchestrator, PredictorEntry, STAGE_PHASE1,
        )
        orch = TrainingOrchestrator(save_dir=str(tmp_path / "cache"))
        def bad(draws):
            raise RuntimeError("nope")
        orch.register(PredictorEntry(
            predictor_id="p_bad", stage=STAGE_PHASE1,
            train_fn=bad, cache_key="p_bad",
        ))
        out = orch.run_stage(STAGE_PHASE1, draws=[])
        assert out["results"][0]["success"] is False
        assert not os.path.exists(orch.cache_marker_path(STAGE_PHASE1, "p_bad"))

    def test_validate_dag_ok_when_marker_exists(self, tmp_path):
        from pipeline.training_orchestrator import (
            TrainingOrchestrator, PredictorEntry, STAGE_PHASE1, STAGE_GLOBAL,
        )
        orch = TrainingOrchestrator(save_dir=str(tmp_path / "cache"))
        orch.register(PredictorEntry("p1", STAGE_PHASE1,
                                      lambda d: {"success": True}, "p1"))
        orch.run_stage(STAGE_PHASE1, draws=[])
        check = orch.validate_dag(up_to_stage=STAGE_PHASE1)
        assert check["ok"]
        assert check["found"] == 1
        assert check["missing"] == []

    def test_validate_dag_missing_when_no_marker(self, tmp_path):
        from pipeline.training_orchestrator import (
            TrainingOrchestrator, PredictorEntry, STAGE_PHASE1,
        )
        orch = TrainingOrchestrator(save_dir=str(tmp_path / "cache"))
        orch.register(PredictorEntry("p1", STAGE_PHASE1,
                                      lambda d: {"success": True}, "p1"))
        # run_stage 안 함 → marker 없음
        check = orch.validate_dag(up_to_stage=STAGE_PHASE1)
        assert not check["ok"]
        assert check["missing"] == [(STAGE_PHASE1, "p1")]

    def test_disabled_predictor_skipped(self, tmp_path):
        from pipeline.training_orchestrator import (
            TrainingOrchestrator, PredictorEntry, STAGE_PHASE1,
        )
        orch = TrainingOrchestrator(save_dir=str(tmp_path / "cache"))
        orch.register(PredictorEntry(
            "p_disabled", STAGE_PHASE1, lambda d: {"success": True}, "p_disabled",
            enabled=False,
        ))
        out = orch.run_stage(STAGE_PHASE1, draws=[])
        assert out["n_predictors"] == 0
        check = orch.validate_dag(up_to_stage=STAGE_PHASE1)
        assert check["total_required"] == 0  # disabled는 검증 대상 아님


# ────────────────── S-1: SLAMonitor ──────────────────


class TestSLAMonitor:
    @pytest.fixture(autouse=True)
    def isolate_history(self, tmp_path, monkeypatch):
        """sla_history 파일을 tmp_path로 격리."""
        import config
        monkeypatch.setattr(config, "MODEL_DIR", str(tmp_path))
        # SLA_HISTORY_FILE 그대로 유지 (path는 MODEL_DIR로 결정)

    def test_basic_measurement(self):
        from pipeline.sla_monitor import SLAMonitor
        with SLAMonitor("infer_test", log_to_history=False) as m:
            time.sleep(0.05)
        assert m.wall_time >= 0.04
        assert m.status == "ok"
        # mem_peak_mb는 psutil 없으면 0, 있으면 > 0
        assert m.mem_peak_mb >= 0

    def test_exception_status(self):
        from pipeline.sla_monitor import SLAMonitor
        try:
            with SLAMonitor("infer_test", log_to_history=False) as m:
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        assert m.status == "error"

    def test_violation_check_train_tag(self):
        """tag가 *_train이면 학습 한도 비교."""
        from pipeline.sla_monitor import check_violation
        # wall_time 100000s = 약 27h > 24h limit
        v = check_violation("phase1_digit_train", wall_time=100000, mem_peak_gb=10)
        assert v["wall_violation"] is True
        # mem 10GB는 학습 한도 14GB 이내
        assert v["mem_violation"] is False

    def test_violation_check_infer_tag(self):
        from pipeline.sla_monitor import check_violation
        # 추론 100s > 30s
        v = check_violation("infer_main", wall_time=100, mem_peak_gb=5)
        assert v["wall_violation"] is True
        # mem 5GB는 추론 한도 12GB 이내
        assert v["mem_violation"] is False

    def test_log_sla_writes_history(self, tmp_path):
        from pipeline.sla_monitor import log_sla, read_sla_history
        log_sla(tag="test_tag", wall_time=1.5, mem_peak_mb=512.0)
        rows = read_sla_history()
        assert len(rows) >= 1
        # 가장 최근 entry
        last = rows[-1]
        assert last["tag"] == "test_tag"
        assert last["wall_time"] == 1.5

    def test_monitor_logs_to_history(self, tmp_path):
        from pipeline.sla_monitor import SLAMonitor, read_sla_history
        with SLAMonitor("infer_test_log", log_to_history=True):
            time.sleep(0.01)
        rows = read_sla_history()
        # 최소 1개 entry 존재 + 가장 최근이 우리 tag
        assert any(r.get("tag") == "infer_test_log" for r in rows)

    def test_get_sla_limits(self):
        from pipeline.sla_monitor import get_sla_limits
        limits = get_sla_limits()
        assert limits["train_wall_time_max"] == 86400
        assert limits["infer_wall_time_max"] == 30
        assert limits["infer_mem_max_gb"] == 12
        assert limits["train_mem_max_gb"] == 14
        assert limits["api_timeout"] == 120

    def test_read_sla_history_with_limit(self):
        from pipeline.sla_monitor import log_sla, read_sla_history
        for i in range(5):
            log_sla(tag=f"limit_test_{i}", wall_time=float(i), mem_peak_mb=10.0)
        rows = read_sla_history(limit=3)
        assert len(rows) == 3
        assert rows[-1]["tag"] == "limit_test_4"
