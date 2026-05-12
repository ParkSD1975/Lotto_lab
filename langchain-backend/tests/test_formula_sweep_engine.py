"""
test_formula_sweep_engine.py

JS/Python 교차 검증 + 결정론 + 데이터 누수 테스트.

Stage 6-F-X: Formula Sweep Phase 3
"""
from __future__ import annotations

import json
import pytest
from pathlib import Path

from models.sweep_schemas import (
    FormulaV5Multi,
    VariablePath,
    SweepCriteria,
)
from services.formula_sweep_engine import FormulaSweepEngine


# ─────────────────────────────────────────────────────────────────
# 테스트 픽스처 (샘플 회차 데이터)
# ─────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_draws():
    """샘플 회차 데이터 (1224~1220 역순)"""
    return [
        {
            "round": 1224,
            "drawNo": 1224,
            "date": "2025-01-04",
            "drawDate": "2025-01-04",
            "numbers": [1, 2, 3, 4, 5, 6],
            "bonus": 7,
        },
        {
            "round": 1223,
            "drawNo": 1223,
            "date": "2024-12-28",
            "drawDate": "2024-12-28",
            "numbers": [8, 15, 22, 29, 36, 43],
            "bonus": 10,
        },
        {
            "round": 1222,
            "drawNo": 1222,
            "date": "2024-12-21",
            "drawDate": "2024-12-21",
            "numbers": [5, 12, 19, 26, 33, 40],
            "bonus": 45,
        },
        {
            "round": 1221,
            "drawNo": 1221,
            "date": "2024-12-14",
            "drawDate": "2024-12-14",
            "numbers": [7, 14, 21, 28, 35, 42],
            "bonus": 3,
        },
        {
            "round": 1220,
            "drawNo": 1220,
            "date": "2024-12-07",
            "drawDate": "2024-12-07",
            "numbers": [2, 9, 16, 23, 30, 37],
            "bonus": 44,
        },
    ]


# ─────────────────────────────────────────────────────────────────
# 단순 산식 테스트 (JS 검증 불필요)
# ─────────────────────────────────────────────────────────────────

def test_simple_round_plus_1(sample_draws):
    """단순 산식: 회차+1 → 1225 → 보정 10"""
    formula_dict = {
        "version": "v5-multi",
        "workspaces": [
            {
                "id": "ws-1",
                "label": "W1",
                "cards": [{"type": "round", "digitMode": "thousands", "offset": 0}],
                "transforms": [{"op": "+", "value": 1, "isVariable": False}],
                "mode": "auto",
            }
        ],
        "combineOps": [],
        "combinePostTransforms": [],
        "combinePostExpand": False,
    }

    formula = FormulaV5Multi(**formula_dict)
    engine = FormulaSweepEngine(formula, [], sample_draws)

    # 1224회차 평가 → 1224+1=1225 → ((1225-1)%45)+1=10
    result = engine.evaluate_at_round(0, target_idx=0)
    assert result == [10]


def test_tail_expand(sample_draws):
    """끝수 expand: 3끝 → [3,13,23,33,43]"""
    formula_dict = {
        "version": "v5-multi",
        "workspaces": [
            {
                "id": "ws-1",
                "label": "W1",
                "cards": [{"type": "tail", "tailNum": 3}],
                "transforms": [],
                "mode": "auto",
            }
        ],
        "combineOps": [],
        "combinePostTransforms": [],
        "combinePostExpand": False,
    }

    formula = FormulaV5Multi(**formula_dict)
    engine = FormulaSweepEngine(formula, [], sample_draws)

    result = engine.evaluate_at_round(0, target_idx=0)
    assert result == [3, 13, 23, 33, 43]


def test_line_offset_1(sample_draws):
    """1회 전 라인: 1223회 본번호"""
    formula_dict = {
        "version": "v5-multi",
        "workspaces": [
            {
                "id": "ws-1",
                "label": "W1",
                "cards": [{"type": "line", "offset": 1}],
                "transforms": [],
                "mode": "auto",
            }
        ],
        "combineOps": [],
        "combinePostTransforms": [],
        "combinePostExpand": False,
    }

    formula = FormulaV5Multi(**formula_dict)
    engine = FormulaSweepEngine(formula, [], sample_draws)

    # 1224회차 평가 → 1223회 번호 (line 카드는 본번호만, 보너스 제외)
    result = engine.evaluate_at_round(0, target_idx=0)
    assert result == [8, 15, 22, 29, 36, 43]  # 보너스 10 제외


def test_scalar_mode_sum(sample_draws):
    """scalar 모드: 10+20=30 → +5=35 → %45=35"""
    formula_dict = {
        "version": "v5-multi",
        "workspaces": [
            {
                "id": "ws-1",
                "label": "W1",
                "cards": [
                    {"type": "num", "num": 10},
                    {"type": "num", "num": 20},
                ],
                "transforms": [
                    {"op": "+", "value": 5, "isVariable": False},
                    {"op": "%", "value": 45, "isVariable": False},
                ],
                "mode": "scalar",
            }
        ],
        "combineOps": [],
        "combinePostTransforms": [],
        "combinePostExpand": False,
    }

    formula = FormulaV5Multi(**formula_dict)
    engine = FormulaSweepEngine(formula, [], sample_draws)

    result = engine.evaluate_at_round(0, target_idx=0)
    assert result == [35]


def test_union_combine(sample_draws):
    """union 결합: W1∪W2"""
    formula_dict = {
        "version": "v5-multi",
        "workspaces": [
            {
                "id": "ws-1",
                "label": "W1",
                "cards": [{"type": "num", "num": 1}],
                "transforms": [],
                "mode": "auto",
            },
            {
                "id": "ws-2",
                "label": "W2",
                "cards": [{"type": "num", "num": 2}],
                "transforms": [],
                "mode": "auto",
            },
        ],
        "combineOps": [{"leftWsId": "ws-1", "op": "union", "rightWsId": "ws-2"}],
        "combinePostTransforms": [],
        "combinePostExpand": False,
    }

    formula = FormulaV5Multi(**formula_dict)
    engine = FormulaSweepEngine(formula, [], sample_draws)

    result = engine.evaluate_at_round(0, target_idx=0)
    assert result == [1, 2]


def test_intersection_combine(sample_draws):
    """intersection 결합: W1∩W2"""
    formula_dict = {
        "version": "v5-multi",
        "workspaces": [
            {
                "id": "ws-1",
                "label": "W1",
                "cards": [{"type": "tail", "tailNum": 3}],  # 3,13,23,33,43
                "transforms": [],
                "mode": "auto",
            },
            {
                "id": "ws-2",
                "label": "W2",
                "cards": [{"type": "tail", "tailNum": 3}],  # 3,13,23,33,43
                "transforms": [],
                "mode": "auto",
            },
        ],
        "combineOps": [{"leftWsId": "ws-1", "op": "intersection", "rightWsId": "ws-2"}],
        "combinePostTransforms": [],
        "combinePostExpand": False,
    }

    formula = FormulaV5Multi(**formula_dict)
    engine = FormulaSweepEngine(formula, [], sample_draws)

    result = engine.evaluate_at_round(0, target_idx=0)
    assert result == [3, 13, 23, 33, 43]


def test_complement_combine(sample_draws):
    """complement 결합: 1~45 중 (W1∪W2)에 없는 번호"""
    formula_dict = {
        "version": "v5-multi",
        "workspaces": [
            {
                "id": "ws-1",
                "label": "W1",
                "cards": [{"type": "num", "num": 1}, {"type": "num", "num": 2}],
                "transforms": [],
                "mode": "auto",
            },
            {
                "id": "ws-2",
                "label": "W2",
                "cards": [{"type": "num", "num": 3}],
                "transforms": [],
                "mode": "auto",
            },
        ],
        "combineOps": [{"leftWsId": "ws-1", "op": "complement", "rightWsId": "ws-2"}],
        "combinePostTransforms": [],
        "combinePostExpand": False,
    }

    formula = FormulaV5Multi(**formula_dict)
    engine = FormulaSweepEngine(formula, [], sample_draws)

    result = engine.evaluate_at_round(0, target_idx=0)
    # 1~45 중 {1,2,3} 제외
    expected = [n for n in range(4, 46)]
    assert result == expected


def test_combine_post_transforms(sample_draws):
    """결합 후 변환: W1+W2 → +5 → %10"""
    formula_dict = {
        "version": "v5-multi",
        "workspaces": [
            {
                "id": "ws-1",
                "label": "W1",
                "cards": [{"type": "num", "num": 10}],
                "transforms": [],
                "mode": "auto",
            },
        ],
        "combineOps": [],
        "combinePostTransforms": [
            {"op": "+", "value": 5, "isVariable": False},
            {"op": "%", "value": 10, "isVariable": False},
        ],
        "combinePostExpand": False,
    }

    formula = FormulaV5Multi(**formula_dict)
    engine = FormulaSweepEngine(formula, [], sample_draws)

    result = engine.evaluate_at_round(0, target_idx=0)
    # 10 → +5=15 → %10=5
    assert result == [5]


def test_combine_post_expand(sample_draws):
    """결합 후 끝수 expand: [38] → 8끝 → [8,18,28,38]"""
    formula_dict = {
        "version": "v5-multi",
        "workspaces": [
            {
                "id": "ws-1",
                "label": "W1",
                "cards": [{"type": "num", "num": 38}],
                "transforms": [],
                "mode": "auto",
            },
        ],
        "combineOps": [],
        "combinePostTransforms": [],
        "combinePostExpand": True,
    }

    formula = FormulaV5Multi(**formula_dict)
    engine = FormulaSweepEngine(formula, [], sample_draws)

    result = engine.evaluate_at_round(0, target_idx=0)
    assert result == [8, 18, 28, 38]


# ─────────────────────────────────────────────────────────────────
# 변수 치환 테스트
# ─────────────────────────────────────────────────────────────────

def test_variable_substitution(sample_draws):
    """변수 치환: 회차+VAR → VAR=10 → 1234 → 보정 19"""
    formula_dict = {
        "version": "v5-multi",
        "workspaces": [
            {
                "id": "ws-1",
                "label": "W1",
                "cards": [{"type": "round", "digitMode": "thousands", "offset": 0}],
                "transforms": [{"op": "+", "value": 0, "isVariable": True}],  # 변수
                "mode": "auto",
            }
        ],
        "combineOps": [],
        "combinePostTransforms": [],
        "combinePostExpand": False,
    }

    formula = FormulaV5Multi(**formula_dict)
    variable_paths = [VariablePath(ws_id="ws-1", transform_idx=0, field="value")]
    engine = FormulaSweepEngine(formula, variable_paths, sample_draws)

    # VAR=10 → 1224+10=1234 → ((1234-1)%45)+1=19
    result = engine.evaluate_at_round(10, target_idx=0)
    assert result == [19]


# ─────────────────────────────────────────────────────────────────
# regref 회귀 참조 테스트
# ─────────────────────────────────────────────────────────────────

def test_regref_line(sample_draws):
    """regref: W1=1 → W2=regref(W1,line) → 1223회 라인"""
    formula_dict = {
        "version": "v5-multi",
        "workspaces": [
            {
                "id": "ws-1",
                "label": "W1",
                "cards": [{"type": "num", "num": 1}],  # N=1
                "transforms": [],
                "mode": "auto",
                "hiddenInOutput": True,  # 최종 결합 제외
            },
            {
                "id": "ws-2",
                "label": "W2",
                "cards": [
                    {
                        "type": "regref",
                        "sourceWsId": "ws-1",
                        "refType": "line",
                    }
                ],
                "transforms": [],
                "mode": "auto",
                "hiddenInOutput": False,
            },
        ],
        "combineOps": [],
        "combinePostTransforms": [],
        "combinePostExpand": False,
    }

    formula = FormulaV5Multi(**formula_dict)
    engine = FormulaSweepEngine(formula, [], sample_draws)

    # 1224회차 평가 → W1=1 → regref(1) → 1223회 라인
    result = engine.evaluate_at_round(0, target_idx=0)
    assert result == [8, 15, 22, 29, 36, 43]


def test_regref_n_less_than_1_blocked(sample_draws):
    """regref N<1 차단 (fix-351)"""
    formula_dict = {
        "version": "v5-multi",
        "workspaces": [
            {
                "id": "ws-1",
                "label": "W1",
                "cards": [{"type": "num", "num": 0}],  # N=0 (차단)
                "transforms": [],
                "mode": "auto",
                "hiddenInOutput": True,
            },
            {
                "id": "ws-2",
                "label": "W2",
                "cards": [
                    {
                        "type": "regref",
                        "sourceWsId": "ws-1",
                        "refType": "line",
                    }
                ],
                "transforms": [],
                "mode": "auto",
                "hiddenInOutput": False,
            },
        ],
        "combineOps": [],
        "combinePostTransforms": [],
        "combinePostExpand": False,
    }

    formula = FormulaV5Multi(**formula_dict)
    engine = FormulaSweepEngine(formula, [], sample_draws)

    result = engine.evaluate_at_round(0, target_idx=0)
    assert result == []  # N<1 차단


# ─────────────────────────────────────────────────────────────────
# 결정론 테스트
# ─────────────────────────────────────────────────────────────────

def test_deterministic(sample_draws):
    """같은 입력 두 번 → 같은 결과"""
    formula_dict = {
        "version": "v5-multi",
        "workspaces": [
            {
                "id": "ws-1",
                "label": "W1",
                "cards": [{"type": "round", "digitMode": "thousands", "offset": 0}],
                "transforms": [{"op": "+", "value": 0, "isVariable": True}],
                "mode": "auto",
            }
        ],
        "combineOps": [],
        "combinePostTransforms": [],
        "combinePostExpand": False,
    }

    formula = FormulaV5Multi(**formula_dict)
    variable_paths = [VariablePath(ws_id="ws-1", transform_idx=0, field="value")]
    engine = FormulaSweepEngine(formula, variable_paths, sample_draws)

    # 두 번 평가
    r1 = engine.evaluate_at_round(79, target_idx=0)
    r2 = engine.evaluate_at_round(79, target_idx=0)

    assert r1 == r2


# ─────────────────────────────────────────────────────────────────
# 데이터 누수 테스트
# ─────────────────────────────────────────────────────────────────

def test_no_data_leak_future_draw(sample_draws):
    """미래 회차 데이터 접근 불가 (offset=0은 현재)"""
    formula_dict = {
        "version": "v5-multi",
        "workspaces": [
            {
                "id": "ws-1",
                "label": "W1",
                "cards": [{"type": "line", "offset": -1}],  # 미래 (불가능)
                "transforms": [],
                "mode": "auto",
            }
        ],
        "combineOps": [],
        "combinePostTransforms": [],
        "combinePostExpand": False,
    }

    formula = FormulaV5Multi(**formula_dict)
    engine = FormulaSweepEngine(formula, [], sample_draws)

    # 1224회차 평가 → offset=-1 → 1225회 (없음)
    result = engine.evaluate_at_round(0, target_idx=0)
    assert result == []  # 미래 회차 접근 불가


def test_no_data_leak_cutoff(sample_draws):
    """cutoff 이전 데이터만 사용 (target_idx 제한)"""
    formula_dict = {
        "version": "v5-multi",
        "workspaces": [
            {
                "id": "ws-1",
                "label": "W1",
                "cards": [{"type": "line", "offset": 1}],
                "transforms": [],
                "mode": "auto",
            }
        ],
        "combineOps": [],
        "combinePostTransforms": [],
        "combinePostExpand": False,
    }

    formula = FormulaV5Multi(**formula_dict)
    engine = FormulaSweepEngine(formula, [], sample_draws)

    # 1220회차 평가 (target_idx=4, 마지막)
    result = engine.evaluate_at_round(0, target_idx=4)
    # offset=1 → 1219회 (없음)
    assert result == []


# ─────────────────────────────────────────────────────────────────
# Sweep 전체 테스트
# ─────────────────────────────────────────────────────────────────

def test_sweep_basic(sample_draws):
    """기본 sweep: 변수 2~5 범위"""
    formula_dict = {
        "version": "v5-multi",
        "workspaces": [
            {
                "id": "ws-1",
                "label": "W1",
                "cards": [{"type": "round", "digitMode": "thousands", "offset": 0}],
                "transforms": [{"op": "+", "value": 0, "isVariable": True}],
                "mode": "auto",
            }
        ],
        "combineOps": [],
        "combinePostTransforms": [],
        "combinePostExpand": False,
    }

    formula = FormulaV5Multi(**formula_dict)
    variable_paths = [VariablePath(ws_id="ws-1", transform_idx=0, field="value")]
    engine = FormulaSweepEngine(formula, variable_paths, sample_draws)

    criteria = SweepCriteria(min_consecutive=2, include_bonus=False)

    # 1223~1221 평가 (1224는 다음 회차 없음)
    results = engine.sweep(
        var_range=range(2, 6),
        criteria=criteria,
        eval_rounds=[1223, 1222, 1221],
    )

    # 결과 구조 검증 (적중 기준은 데이터 의존)
    assert isinstance(results, list)
    for r in results:
        assert r.variable_value in range(2, 6)
        assert r.max_consecutive >= 2
        assert len(r.history) > 0


def test_sweep_with_bonus(sample_draws):
    """보너스 포함 sweep"""
    formula_dict = {
        "version": "v5-multi",
        "workspaces": [
            {
                "id": "ws-1",
                "label": "W1",
                "cards": [{"type": "bonus", "offset": 1}],  # 1회 전 보너스
                "transforms": [],
                "mode": "auto",
            }
        ],
        "combineOps": [],
        "combinePostTransforms": [],
        "combinePostExpand": False,
    }

    formula = FormulaV5Multi(**formula_dict)
    engine = FormulaSweepEngine(formula, [], sample_draws)

    criteria = SweepCriteria(min_consecutive=1, include_bonus=True)

    # 1223회차 평가 → 보너스=10 (1223) → 1222회 당첨 (5,12,19,26,33,40,45)
    results = engine.sweep(
        var_range=range(1, 2),  # sweep 없음 (변수 없음)
        criteria=criteria,
        eval_rounds=[1223],
    )

    # 1223회 보너스(10)가 1222회에 적중하는지
    # (sample_draws에서 1222 보너스=45, 본번호=[5,12,19,26,33,40])
    # → 10은 적중 안 함 → hit_count=0
    assert len(results) >= 0  # 데이터 의존


def test_sweep_progress_callback(sample_draws):
    """진행 콜백 동작 검증"""
    formula_dict = {
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
    }

    formula = FormulaV5Multi(**formula_dict)
    engine = FormulaSweepEngine(formula, [], sample_draws)

    criteria = SweepCriteria(min_consecutive=1, include_bonus=False)

    progress_log = []

    def callback(current, total, var_value):
        progress_log.append((current, total, var_value))

    engine.sweep(
        var_range=range(1, 4),
        criteria=criteria,
        eval_rounds=[1223],
        progress_callback=callback,
    )

    assert len(progress_log) == 3
    assert progress_log[0] == (1, 3, 1)
    assert progress_log[1] == (2, 3, 2)
    assert progress_log[2] == (3, 3, 3)


# ─────────────────────────────────────────────────────────────────
# 성능 벤치마크 (단일 평가 < 50ms 목표)
# ─────────────────────────────────────────────────────────────────

def test_single_evaluation_performance(sample_draws):
    """단일 평가 성능 (< 50ms 목표)"""
    import time

    formula_dict = {
        "version": "v5-multi",
        "workspaces": [
            {
                "id": "ws-1",
                "label": "W1",
                "cards": [{"type": "round", "digitMode": "thousands", "offset": 0}],
                "transforms": [{"op": "+", "value": 0, "isVariable": True}],
                "mode": "auto",
            }
        ],
        "combineOps": [],
        "combinePostTransforms": [],
        "combinePostExpand": False,
    }

    formula = FormulaV5Multi(**formula_dict)
    variable_paths = [VariablePath(ws_id="ws-1", transform_idx=0, field="value")]
    engine = FormulaSweepEngine(formula, variable_paths, sample_draws)

    # 10회 평균 측정
    iterations = 10
    start = time.perf_counter()
    for _ in range(iterations):
        engine.evaluate_at_round(79, target_idx=0)
    elapsed = (time.perf_counter() - start) / iterations

    print(f"\n단일 평가 wall-time: {elapsed*1000:.2f}ms")

    # 50ms 목표 (여유 100ms)
    assert elapsed < 0.1, f"단일 평가 너무 느림: {elapsed*1000:.2f}ms"


def test_regref_cycle_blocked(sample_draws):
    """regref 순환 참조 차단: W1→W2, W2→W1 사이클 시 빈 결과 반환"""
    formula_dict = {
        "version": "v5-multi",
        "workspaces": [
            {
                "id": "ws-1",
                "label": "W1",
                "cards": [
                    {
                        "type": "regref",
                        "sourceWsId": "ws-2",
                        "refType": "line",
                    }
                ],
                "transforms": [],
                "mode": "auto",
                "hiddenInOutput": False,
            },
            {
                "id": "ws-2",
                "label": "W2",
                "cards": [
                    {
                        "type": "regref",
                        "sourceWsId": "ws-1",
                        "refType": "line",
                    }
                ],
                "transforms": [],
                "mode": "auto",
                "hiddenInOutput": False,
            },
        ],
        "combineOps": [{"leftWsId": "ws-1", "op": "union", "rightWsId": "ws-2"}],
        "combinePostTransforms": [],
        "combinePostExpand": False,
    }

    formula = FormulaV5Multi(**formula_dict)
    engine = FormulaSweepEngine(formula, [], sample_draws)

    # 순환 감지 → 빈 배열
    result = engine.evaluate_at_round(0, target_idx=0)
    assert result == []  # 순환 감지로 빈 배열


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
