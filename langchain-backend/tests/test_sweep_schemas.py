"""
test_sweep_schemas.py

Pydantic 스키마 JSON 직렬화/역직렬화 round-trip 검증.
사용자 이미지의 W1∪W2 산식 구조 테스트.

Stage 6-F-X: Formula Sweep Phase 2
"""
from __future__ import annotations

import json
import pytest

from models.sweep_schemas import (
    FormulaV5Multi,
    FormulaWorkspace,
    FormulaCardRound,
    FormulaCardDate,
    FormulaCardLine,
    FormulaCardRegref,
    FormulaTransform,
    FormulaCombineOp,
)


def test_round_trip_w1_union_w2():
    """사용자 이미지 산식: W1∪W2 round-trip 불변성 검증"""
    # 원본 구조 (사용자 이미지 기반)
    formula_dict = {
        "version": "v5-multi",
        "workspaces": [
            {
                "id": "ws-1",
                "label": "W1",
                "cards": [
                    {"type": "round", "digitMode": "thousands", "offset": 0},
                    {"type": "date", "datePart": "day", "offset": 0},
                    {"type": "date", "datePart": "month", "offset": 0},
                    {"type": "line", "offset": 1},  # 1회 전 라인
                ],
                "transforms": [
                    {"op": "+", "value": 1, "isVariable": False},
                    {"op": "+", "value": 2, "isVariable": False},
                    {"op": "+", "value": 2, "isVariable": False},
                    {"op": "*", "value": 2, "isVariable": False},
                ],
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
                        "refType": "all_main_bonus",
                    },
                ],
                "transforms": [
                    {"op": "+", "value": 79, "isVariable": True},  # 변수 위치
                    {"op": "%", "value": 46, "isVariable": False},
                ],
                "mode": "auto",
                "hiddenInOutput": False,
            },
        ],
        "combineOps": [
            {"leftWsId": "ws-1", "op": "union", "rightWsId": "ws-2"},
        ],
        "combinePostTransforms": [],
        "combinePostExpand": True,  # 끝수 expand
    }

    # 1. JSON → Pydantic
    formula = FormulaV5Multi(**formula_dict)

    # 2. Pydantic → JSON
    serialized = formula.model_dump(mode="json")

    # 3. JSON → Pydantic (재생성)
    formula2 = FormulaV5Multi(**serialized)

    # 4. 불변성 검증
    assert formula.model_dump() == formula2.model_dump()
    assert len(formula.workspaces) == 2
    assert formula.workspaces[0].id == "ws-1"
    assert formula.workspaces[1].id == "ws-2"
    assert len(formula.workspaces[0].cards) == 4
    assert len(formula.workspaces[0].transforms) == 4
    assert len(formula.workspaces[1].cards) == 1
    assert len(formula.workspaces[1].transforms) == 2
    assert formula.workspaces[1].transforms[0].isVariable is True
    assert len(formula.combineOps) == 1
    assert formula.combineOps[0].op == "union"
    assert formula.combinePostExpand is True


def test_all_card_types_roundtrip():
    """모든 카드 타입 직렬화 검증"""
    formula_dict = {
        "version": "v5-multi",
        "workspaces": [
            {
                "id": "ws-all",
                "label": "All Cards",
                "cards": [
                    {"type": "tail", "tailNum": 3},
                    {"type": "saved", "targetNumbers": [1, 2, 3]},
                    {"type": "regref", "sourceWsId": "ws-1", "refType": "line"},
                    {"type": "line", "offset": 1},
                    {"type": "pos", "position": 3, "offset": 0},
                    {"type": "bonus", "offset": 1},
                    {"type": "round", "digitMode": "tens", "offset": 2},
                    {"type": "date", "datePart": "month", "offset": 1},
                    {"type": "num", "num": 42},
                ],
                "transforms": [],
                "mode": "auto",
            },
        ],
        "combineOps": [],
        "combinePostTransforms": [],
        "combinePostExpand": False,
    }

    formula = FormulaV5Multi(**formula_dict)
    serialized = formula.model_dump(mode="json")
    formula2 = FormulaV5Multi(**serialized)

    assert formula.model_dump() == formula2.model_dump()
    assert len(formula.workspaces[0].cards) == 9


def test_variable_path_with_transforms():
    """변수 치환 경로 검증"""
    formula_dict = {
        "version": "v5-multi",
        "workspaces": [
            {
                "id": "ws-var",
                "label": "W1",
                "cards": [{"type": "round", "digitMode": "thousands", "offset": 0}],
                "transforms": [
                    {"op": "+", "value": 10, "isVariable": True},  # idx=0
                    {"op": "*", "value": 2, "isVariable": False},  # idx=1
                    {"op": "%", "value": 45, "isVariable": False},  # idx=2
                ],
                "mode": "auto",
            },
        ],
        "combineOps": [],
        "combinePostTransforms": [],
        "combinePostExpand": False,
    }

    formula = FormulaV5Multi(**formula_dict)

    # 변수 위치 추출 (isVariable=True인 transforms)
    variable_transforms = [
        (ws.id, idx, tx)
        for ws in formula.workspaces
        for idx, tx in enumerate(ws.transforms)
        if tx.isVariable
    ]

    assert len(variable_transforms) == 1
    assert variable_transforms[0][0] == "ws-var"
    assert variable_transforms[0][1] == 0  # transform index
    assert variable_transforms[0][2].op == "+"
    assert variable_transforms[0][2].value == 10


def test_combine_ops_all_types():
    """모든 결합 연산 타입 직렬화 검증"""
    formula_dict = {
        "version": "v5-multi",
        "workspaces": [
            {"id": "ws-1", "label": "W1", "cards": [], "transforms": [], "mode": "auto"},
            {"id": "ws-2", "label": "W2", "cards": [], "transforms": [], "mode": "auto"},
            {"id": "ws-3", "label": "W3", "cards": [], "transforms": [], "mode": "auto"},
            {"id": "ws-4", "label": "W4", "cards": [], "transforms": [], "mode": "auto"},
            {"id": "ws-5", "label": "W5", "cards": [], "transforms": [], "mode": "auto"},
            {"id": "ws-6", "label": "W6", "cards": [], "transforms": [], "mode": "auto"},
        ],
        "combineOps": [
            {"leftWsId": "ws-1", "op": "union", "rightWsId": "ws-2"},
            {"leftWsId": "ws-2", "op": "intersection", "rightWsId": "ws-3"},
            {"leftWsId": "ws-3", "op": "complement", "rightWsId": "ws-4"},
            {"leftWsId": "ws-4", "op": "difference", "rightWsId": "ws-5"},
            {"leftWsId": "ws-5", "op": "symdiff", "rightWsId": "ws-6"},
        ],
        "combinePostTransforms": [],
        "combinePostExpand": False,
    }

    formula = FormulaV5Multi(**formula_dict)
    serialized = formula.model_dump(mode="json")
    formula2 = FormulaV5Multi(**serialized)

    assert formula.model_dump() == formula2.model_dump()
    assert len(formula.combineOps) == 5
    ops = [c.op for c in formula.combineOps]
    assert ops == ["union", "intersection", "complement", "difference", "symdiff"]


def test_combine_post_transforms():
    """결합 후 변환 직렬화 검증"""
    formula_dict = {
        "version": "v5-multi",
        "workspaces": [
            {"id": "ws-1", "label": "W1", "cards": [], "transforms": [], "mode": "auto"},
        ],
        "combineOps": [],
        "combinePostTransforms": [
            {"op": "+", "value": 5, "isVariable": False},
            {"op": "%", "value": 10, "isVariable": False},
        ],
        "combinePostExpand": True,
    }

    formula = FormulaV5Multi(**formula_dict)
    serialized = formula.model_dump(mode="json")
    formula2 = FormulaV5Multi(**serialized)

    assert formula.model_dump() == formula2.model_dump()
    assert len(formula.combinePostTransforms) == 2
    assert formula.combinePostExpand is True


def test_scalar_mode_workspace():
    """scalar 모드 워크스페이스 검증"""
    formula_dict = {
        "version": "v5-multi",
        "workspaces": [
            {
                "id": "ws-scalar",
                "label": "Scalar",
                "cards": [
                    {"type": "num", "num": 10},
                    {"type": "num", "num": 20},
                ],
                "transforms": [
                    {"op": "+", "value": 5, "isVariable": False},
                    {"op": "%", "value": 45, "isVariable": False},
                ],
                "mode": "scalar",  # 합산 후 chain
            },
        ],
        "combineOps": [],
        "combinePostTransforms": [],
        "combinePostExpand": False,
    }

    formula = FormulaV5Multi(**formula_dict)
    assert formula.workspaces[0].mode == "scalar"


def test_hidden_workspace_for_regref():
    """regref 소스 전용 hidden 워크스페이스 검증"""
    formula_dict = {
        "version": "v5-multi",
        "workspaces": [
            {
                "id": "ws-hidden",
                "label": "Hidden Source",
                "cards": [{"type": "round", "digitMode": "thousands", "offset": 0}],
                "transforms": [],
                "mode": "auto",
                "hiddenInOutput": True,  # 최종 결합 제외
            },
            {
                "id": "ws-visible",
                "label": "Visible",
                "cards": [
                    {
                        "type": "regref",
                        "sourceWsId": "ws-hidden",
                        "refType": "line",
                    },
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
    assert formula.workspaces[0].hiddenInOutput is True
    assert formula.workspaces[1].hiddenInOutput is False


def test_json_string_roundtrip():
    """JSON 문자열 왕복 변환 검증"""
    formula_dict = {
        "version": "v5-multi",
        "workspaces": [
            {
                "id": "ws-1",
                "label": "W1",
                "cards": [{"type": "round", "digitMode": "thousands", "offset": 0}],
                "transforms": [{"op": "+", "value": 1, "isVariable": False}],
                "mode": "auto",
            },
        ],
        "combineOps": [],
        "combinePostTransforms": [],
        "combinePostExpand": False,
    }

    # 1. dict → JSON string
    json_str = json.dumps(formula_dict)

    # 2. JSON string → Pydantic
    formula = FormulaV5Multi(**json.loads(json_str))

    # 3. Pydantic → JSON string
    json_str2 = formula.model_dump_json()

    # 4. JSON string → dict
    dict2 = json.loads(json_str2)

    # 5. 불변성
    formula2 = FormulaV5Multi(**dict2)
    assert formula.model_dump() == formula2.model_dump()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
