"""
sweep_schemas.py

Formula Variable Sweep — v5-multi 산식 직렬화 스키마.
JS customSimulator 워크스페이스 구조와 100% 호환.

Stage 6-F-X: Formula Sweep Phase 2
"""
from __future__ import annotations

from typing import Literal, Optional, Union
from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────
# 카드 타입 (simulator_evaluator.js line 33~131 참조)
# ─────────────────────────────────────────────────────────────────

class FormulaCardTail(BaseModel):
    """끝수 카드 (0~9)"""
    type: Literal["tail"] = "tail"
    tailNum: int = Field(ge=0, le=9)


class FormulaCardSaved(BaseModel):
    """저장된 필터 카드 (드롭 시점 스냅샷)"""
    type: Literal["saved"] = "saved"
    targetNumbers: list[int] = Field(default_factory=list)


class FormulaCardRegref(BaseModel):
    """회귀 참조 카드 (다른 ws의 산출값 N을 offset으로 dereferencing)"""
    type: Literal["regref"] = "regref"
    sourceWsId: str
    refType: Literal["line", "bonus", "pos", "round", "all_main_bonus"]
    position: Optional[int] = None  # refType="pos"일 때만
    digitMode: Optional[Literal["ones", "tens", "hundreds", "thousands"]] = None  # refType="round"일 때만


class FormulaCardLine(BaseModel):
    """1라인/2라인 카드 (offset 기준 회차의 본번호 전체)"""
    type: Literal["line"] = "line"
    offset: int = 0  # 0=현재, 1=직전, 2=2회 전, ...


class FormulaCardPos(BaseModel):
    """번호 위치 카드 (정렬 후 index)"""
    type: Literal["pos"] = "pos"
    position: int = Field(ge=1, le=6)
    offset: int = 0


class FormulaCardBonus(BaseModel):
    """보너스 번호 카드"""
    type: Literal["bonus"] = "bonus"
    offset: int = 0


class FormulaCardRound(BaseModel):
    """회차 번호 카드"""
    type: Literal["round"] = "round"
    digitMode: Literal["ones", "tens", "hundreds", "thousands"] = "thousands"
    offset: int = 0
    # fallback (회차 데이터 없을 때)
    drawNo: Optional[int] = None


class FormulaCardDate(BaseModel):
    """일자 카드"""
    type: Literal["date"] = "date"
    datePart: Literal["year", "month", "day"] = "day"
    offset: int = 0
    # fallback (회차 데이터 없을 때)
    drawDate: Optional[str] = None


class FormulaCardNum(BaseModel):
    """상수 카드"""
    type: Literal["num"] = "num"
    num: int


class FormulaCardOp(BaseModel):
    """산술 연산 토큰 (workspace cards 사이에 삽입)"""
    type: Literal["op"] = "op"
    value: Literal["+", "-", "*", "/", "%"]


FormulaCard = Union[
    FormulaCardTail,
    FormulaCardSaved,
    FormulaCardRegref,
    FormulaCardLine,
    FormulaCardPos,
    FormulaCardBonus,
    FormulaCardRound,
    FormulaCardDate,
    FormulaCardNum,
    FormulaCardOp,
]


# ─────────────────────────────────────────────────────────────────
# 변환 (transforms)
# ─────────────────────────────────────────────────────────────────

class FormulaTransform(BaseModel):
    """워크스페이스 변환 토큰 (+, -, *, /, %, tail)"""
    op: Literal["+", "-", "*", "/", "%", "tail"]
    value: int
    isVariable: bool = False  # sweep 변수 위치 마킹


# ─────────────────────────────────────────────────────────────────
# 집합 연산 override (시뮬레이터 UI 고정 번호 직접 입력 모드)
# ─────────────────────────────────────────────────────────────────

class FormulaSetOpOverride(BaseModel):
    """워크스페이스 산출값 무시하고 고정 번호 배열 사용"""
    numbers: list[int]


# ─────────────────────────────────────────────────────────────────
# 워크스페이스
# ─────────────────────────────────────────────────────────────────

class FormulaWorkspace(BaseModel):
    """단일 워크스페이스 (카드 시퀀스 + 변환 분기)"""
    id: str
    label: str
    cards: list[FormulaCard] = Field(default_factory=list)
    transforms: list[FormulaTransform] = Field(default_factory=list)
    mode: Literal["auto", "scalar", "tail"] = "auto"
    # auto: 분기 union (기본)
    # scalar: 카드 합산 후 chain transforms (순차 산술)
    # tail: 변환 후 끝수 expand
    hiddenInOutput: bool = False  # regref 소스 전용 (최종 결합 제외)
    setOpOverride: Optional[FormulaSetOpOverride] = None


# ─────────────────────────────────────────────────────────────────
# 결합 연산 (워크스페이스 간)
# ─────────────────────────────────────────────────────────────────

class FormulaCombineOp(BaseModel):
    """워크스페이스 간 결합 연산 (좌→우 누적)"""
    leftWsId: str
    op: Literal["union", "intersection", "complement", "difference", "symdiff", "+", "-", "*", "/", "%"]
    rightWsId: str


# ─────────────────────────────────────────────────────────────────
# v5-multi 최상위 객체
# ─────────────────────────────────────────────────────────────────

class FormulaV5Multi(BaseModel):
    """v5-multi 산식 — 다중 워크스페이스 + 결합 + 후처리"""
    workspaces: list[FormulaWorkspace]
    combineOps: list[FormulaCombineOp] = Field(default_factory=list)
    combinePostTransforms: list[FormulaTransform] = Field(default_factory=list)  # 결합 후 변환
    combinePostExpand: bool = False  # 결합값 끝수 → 1~45 expand
    version: Literal["v5-multi"] = "v5-multi"


# ─────────────────────────────────────────────────────────────────
# Sweep 변수 경로 (워크스페이스 → 변환 인덱스)
# ─────────────────────────────────────────────────────────────────

class VariablePath(BaseModel):
    """변수 치환 경로 (ws_id + transform_idx)"""
    ws_id: str
    transform_idx: int
    field: Literal["value"] = "value"


# ─────────────────────────────────────────────────────────────────
# Sweep 기준
# ─────────────────────────────────────────────────────────────────

class SweepCriteria(BaseModel):
    """연속 hit 판정 기준"""
    min_consecutive: int = 3  # 최소 N연속 hit
    include_bonus: bool = False  # 보너스 번호 포함 여부
    max_avg_gap: Optional[float] = None  # 평균 gap 상한 (None=무제한)


# ─────────────────────────────────────────────────────────────────
# Sweep 결과
# ─────────────────────────────────────────────────────────────────

class SweepHitRecord(BaseModel):
    """단일 회차 평가 결과"""
    round: int
    targets: list[int]  # 산출된 추천 번호
    hit_count: int
    bonus_hit: bool
    next_numbers: list[int]  # 실제 당첨 번호 (검증용)
    next_bonus: Optional[int]


class SweepResult(BaseModel):
    """단일 변수값 sweep 결과"""
    var_value: int
    longest_consecutive: int  # 최장 N연속 hit
    total_hits: int  # 총 hit 회차 수
    avg_gap: float  # hit 간 평균 간격
    history: list[SweepHitRecord]  # 회차별 상세
