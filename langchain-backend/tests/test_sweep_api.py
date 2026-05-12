"""
test_sweep_api.py

Formula Variable Sweep API 통합 테스트 (Phase 4).

Stage 6-F-X: Formula Sweep Phase 4
"""
from __future__ import annotations

import pytest
import time
from fastapi.testclient import TestClient

# main.py 임포트 (FastAPI app)
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from main import app

client = TestClient(app)


def test_sweep_run_endpoint():
    """Sweep 실행 엔드포인트 기본 동작 검증"""

    # 단순 산식: 회차+VAR
    payload = {
        "formula": {
            "version": "v5-multi",
            "workspaces": [
                {
                    "id": "ws-1",
                    "label": "W1",
                    "cards": [
                        {"type": "round", "digitMode": "thousands", "offset": 0}
                    ],
                    "transforms": [
                        {"op": "+", "value": 0, "isVariable": True}
                    ],
                    "mode": "auto",
                }
            ],
            "combineOps": [],
            "combinePostTransforms": [],
            "combinePostExpand": False,
        },
        "variable_paths": [
            {"ws_id": "ws-1", "transform_idx": 0, "field": "value"}
        ],
        "variable_range": {"min": 2, "max": 5, "step": 1},
        "criteria": {
            "min_consecutive": 2,
            "include_bonus": False,
            "min_avg_gap": None,
        },
        "eval_rounds": None,
    }

    response = client.post("/api/sweep/run", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "job_id" in data
    assert data["status"] == "queued"

    job_id = data["job_id"]

    # 상태 조회
    status_response = client.get(f"/api/sweep/{job_id}/status")
    assert status_response.status_code == 200
    status_data = status_response.json()
    assert status_data["status"] in ["queued", "running", "complete", "failed"]


def test_sweep_invalid_range():
    """variable_range 검증 (min >= max 시 400)"""

    payload = {
        "formula": {
            "version": "v5-multi",
            "workspaces": [
                {
                    "id": "ws-1",
                    "label": "W1",
                    "cards": [{"type": "num", "num": 1}],
                    "transforms": [],
                    "mode": "auto",
                }
            ],
            "combineOps": [],
            "combinePostTransforms": [],
            "combinePostExpand": False,
        },
        "variable_paths": [],
        "variable_range": {"min": 100, "max": 50, "step": 1},  # min >= max
        "criteria": {"min_consecutive": 1, "include_bonus": False},
    }

    response = client.post("/api/sweep/run", json=payload)
    assert response.status_code == 400


def test_sweep_results_endpoint():
    """결과 조회 엔드포인트 (job_id 없을 시 404)"""

    fake_job_id = "00000000-0000-0000-0000-000000000000"
    response = client.get(f"/api/sweep/{fake_job_id}/results")
    assert response.status_code == 404


def test_sweep_history_endpoint():
    """과거 통계 엔드포인트 (job_id 없을 시 404)"""

    fake_job_id = "00000000-0000-0000-0000-000000000000"
    response = client.get(f"/api/sweep/{fake_job_id}/results/10/history")
    assert response.status_code == 404


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
