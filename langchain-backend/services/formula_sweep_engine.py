"""
formula_sweep_engine.py

Formula Variable Sweep — v5-multi 산식 평가 엔진.
JS simulator_evaluator.js의 evalSimulatorV5Multi를 정확히 포팅.

Stage 6-F-X: Formula Sweep Phase 3

절대 준수 원칙:
1. JS와 Python 평가 결과 100% 일치 — 단 한 개 변수값/회차에서도 차이 X
2. 추측 X — 모든 코드는 js/simulator_evaluator.js 인용 근거
3. 데이터 누수 0 — cutoff_round 이전 데이터만 사용
4. 결정론 — hashlib.md5 기반 (hash() 사용 금지)
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Optional, Callable

from models.sweep_schemas import (
    FormulaV5Multi,
    FormulaCard,
    FormulaWorkspace,
    FormulaTransform,
    VariablePath,
    SweepCriteria,
    SweepResult,
    SweepHitRecord,
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
)


class FormulaSweepEngine:
    """v5-multi 산식 평가 + 변수 sweep 엔진"""

    def __init__(
        self,
        formula: FormulaV5Multi,
        variable_paths: list[VariablePath],
        draws: list[dict],
        max_ball: int = 45,
    ):
        """
        Args:
            formula: v5-multi 산식 객체
            variable_paths: sweep 변수 경로 (ws_id + transform_idx)
            draws: 회차 데이터 (round DESC 정렬 필수)
            max_ball: 최대 번호 (기본 45)
        """
        self.formula = formula
        self.variable_paths = variable_paths
        self.draws = sorted(draws, key=lambda d: d.get("round", 0) or d.get("drawNo", 0), reverse=True)
        self.max_ball = max_ball

    def evaluate_at_round(self, var_value: int, target_idx: int) -> list[int]:
        """
        단일 회차에 산식 평가.

        Args:
            var_value: 변수 치환값
            target_idx: 대상 회차 인덱스 (sorted 배열)

        Returns:
            정규화된 추천 번호 배열 (1~max_ball, 중복 제거, 정렬)
        """
        # 변수 치환
        formula = self._substitute_variable(var_value)

        # evalSimulatorV5Multi 포팅
        return self._eval_v5_multi(formula, target_idx)

    def sweep(
        self,
        var_range: range,
        criteria: SweepCriteria,
        eval_rounds: Optional[list[int]] = None,
        progress_callback: Optional[Callable[[int, int, int], None]] = None,
    ) -> list[SweepResult]:
        """
        변수 범위 sweep.

        Args:
            var_range: 변수 범위 (e.g. range(2, 1001))
            criteria: 연속 hit 판정 기준
            eval_rounds: 평가 대상 회차 목록 (None=전체)
            progress_callback: 진행 콜백 (current, total, var_value)

        Returns:
            기준 충족 결과 목록 (longest_consecutive >= min_consecutive)
        """
        if eval_rounds is None:
            eval_rounds = [d.get("round", 0) or d.get("drawNo", 0) for d in self.draws]

        # round → idx 매핑
        round_to_idx = {
            d.get("round", 0) or d.get("drawNo", 0): idx for idx, d in enumerate(self.draws)
        }

        results = []
        total = len(var_range)

        for current, var_value in enumerate(var_range, 1):
            # 모든 회차 평가
            history = []
            for round_no in eval_rounds:
                if round_no not in round_to_idx:
                    continue

                target_idx = round_to_idx[round_no]

                # 다음 회차 (실제 당첨 번호)
                next_idx = target_idx - 1
                if next_idx < 0:
                    continue  # 최신 회차 → 다음 회차 없음

                next_draw = self.draws[next_idx]

                # 산식 평가
                try:
                    targets = self.evaluate_at_round(var_value, target_idx)
                except Exception as e:
                    # 평가 오류 → skip
                    continue

                # hit 판정
                hit_count, bonus_hit = self._eval_hit(
                    targets, next_draw, criteria.include_bonus
                )

                history.append(
                    SweepHitRecord(
                        round=round_no,
                        targets=targets,
                        hit_count=hit_count,
                        bonus_hit=bonus_hit,
                        next_numbers=next_draw.get("numbers", []),
                        next_bonus=next_draw.get("bonus"),
                    )
                )

            # 연속 hit 판정
            longest_consecutive = self._longest_consecutive(history)
            total_hits = sum(1 for h in history if h.hit_count > 0)
            avg_gap = self._compute_avg_gap(history)

            # 기준 충족 여부
            if longest_consecutive >= criteria.min_consecutive:
                if criteria.max_avg_gap is None or avg_gap <= criteria.max_avg_gap:
                    results.append(
                        SweepResult(
                            var_value=var_value,
                            longest_consecutive=longest_consecutive,
                            total_hits=total_hits,
                            avg_gap=avg_gap,
                            history=history,
                        )
                    )

            # 진행 콜백
            if progress_callback:
                progress_callback(current, total, var_value)

        return results

    # ─────────────────────────────────────────────────────────────────
    # 내부 메서드 (JS simulator_evaluator.js 포팅)
    # ─────────────────────────────────────────────────────────────────

    def _substitute_variable(self, var_value: int) -> FormulaV5Multi:
        """변수 치환 (deep copy + 변수 위치 value 교체)"""
        formula = self.formula.model_copy(deep=True)
        for path in self.variable_paths:
            ws = next((w for w in formula.workspaces if w.id == path.ws_id), None)
            if ws and path.transform_idx < len(ws.transforms):
                ws.transforms[path.transform_idx].value = var_value
        return formula

    def _eval_v5_multi(self, formula: FormulaV5Multi, target_idx: int) -> list[int]:
        """
        evalSimulatorV5Multi 포팅 (JS line 22~368).

        Args:
            formula: v5-multi 산식
            target_idx: 대상 회차 인덱스

        Returns:
            정규화된 번호 배열
        """
        target = self.draws[target_idx]

        # 회귀 참조 캐시 (사이클 방지)
        ws_eval_cache: dict[str, list[int]] = {}
        ws_evaluating: set[str] = set()

        # ── evalCard (JS line 33~131) ──
        def eval_card(c: FormulaCard) -> list[int]:
            if isinstance(c, FormulaCardTail):
                # JS line 34~39
                return [n for n in range(1, self.max_ball + 1) if n % 10 == c.tailNum]

            if isinstance(c, FormulaCardSaved):
                # JS line 42~44
                return list(c.targetNumbers)

            if isinstance(c, FormulaCardRegref):
                # JS line 47~97
                source_ws = next((w for w in formula.workspaces if w.id == c.sourceWsId), None)
                if not source_ws:
                    return []

                # 사이클 차단
                if c.sourceWsId in ws_evaluating:
                    return []

                ws_evaluating.add(c.sourceWsId)

                # 소스 워크스페이스 평가
                if c.sourceWsId in ws_eval_cache:
                    source_vals = ws_eval_cache[c.sourceWsId]
                else:
                    source_vals = eval_ws(source_ws)
                    ws_eval_cache[c.sourceWsId] = source_vals

                ws_evaluating.discard(c.sourceWsId)

                if not source_vals:
                    return []

                # N<1 차단 (fix-351)
                collected = []
                seen_offsets = set()
                for raw_n in source_vals:
                    n = int(raw_n)
                    if n < 1 or n in seen_offsets:
                        continue
                    seen_offsets.add(n)

                    ref_idx = target_idx + n
                    if ref_idx >= len(self.draws):
                        continue

                    ref_draw = self.draws[ref_idx]

                    if c.refType == "line":
                        collected.extend(ref_draw.get("numbers", []))
                    elif c.refType == "bonus":
                        bonus = ref_draw.get("bonus")
                        if bonus is not None:
                            collected.append(bonus)
                    elif c.refType == "pos":
                        sorted_nums = sorted(ref_draw.get("numbers", []))
                        if c.position and 1 <= c.position <= len(sorted_nums):
                            collected.append(sorted_nums[c.position - 1])
                    elif c.refType == "round":
                        v = ref_draw.get("drawNo") or ref_draw.get("round")
                        if v is not None:
                            # digitMode: thousands는 mod 없음
                            mod = {"ones": 10, "tens": 100, "hundreds": 1000}.get(c.digitMode)
                            if mod:
                                v = v % mod
                            collected.append(v)
                    elif c.refType == "all_main_bonus":
                        collected.extend(ref_draw.get("numbers", []))
                        bonus = ref_draw.get("bonus")
                        if bonus is not None:
                            collected.append(bonus)

                return collected

            # offset 기반 카드
            offset = getattr(c, "offset", 0)
            ref_idx = target_idx + offset
            ref_draw = self.draws[ref_idx] if 0 <= ref_idx < len(self.draws) else None

            # round/date는 fallback 지원
            if not ref_draw and not isinstance(c, (FormulaCardRound, FormulaCardDate)):
                return []

            if isinstance(c, FormulaCardLine):
                # JS line 104
                return list(ref_draw.get("numbers", []) if ref_draw else [])

            if isinstance(c, FormulaCardPos):
                # JS line 105~108
                if ref_draw:
                    sorted_nums = sorted(ref_draw.get("numbers", []))
                    if 1 <= c.position <= len(sorted_nums):
                        return [sorted_nums[c.position - 1]]
                return []

            if isinstance(c, FormulaCardBonus):
                # JS line 110
                bonus = ref_draw.get("bonus") if ref_draw else None
                return [bonus] if bonus is not None else []

            if isinstance(c, FormulaCardNum):
                # JS line 111
                return [c.num]

            if isinstance(c, FormulaCardRound):
                # JS line 112~118
                v = None
                if ref_draw:
                    v = ref_draw.get("drawNo") or ref_draw.get("round")
                elif target:
                    v = target.get("drawNo") or target.get("round")
                elif c.drawNo is not None:
                    v = c.drawNo

                if v is not None:
                    # digitMode: ones(%10), tens(%100), hundreds(%1000), thousands(전체)
                    # thousands는 mod 없음 (v 그대로)
                    mod = {"ones": 10, "tens": 100, "hundreds": 1000}.get(c.digitMode)
                    if mod:
                        v = v % mod
                    return [v]
                return []

            if isinstance(c, FormulaCardDate):
                # JS line 120~129
                date_str = None
                if ref_draw:
                    date_str = ref_draw.get("drawDate") or ref_draw.get("date")
                elif target:
                    date_str = target.get("drawDate") or target.get("date")
                elif c.drawDate:
                    date_str = c.drawDate

                if not date_str:
                    return []

                try:
                    dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    if c.datePart == "year":
                        return [dt.year]
                    elif c.datePart == "month":
                        return [dt.month]
                    else:  # day
                        return [dt.day]
                except Exception:
                    return []

            return []

        # ── evalWs (JS line 134~199) ──
        def eval_ws(ws: FormulaWorkspace) -> list[int]:
            # setOpOverride 지원
            if ws.setOpOverride and ws.setOpOverride.numbers:
                return list(ws.setOpOverride.numbers)

            # cards 시퀀스 순회 (op 토큰 지원)
            acc: Optional[list[int]] = None
            pending_op: Optional[str] = None

            for card in ws.cards:
                if isinstance(card, FormulaCardOp):
                    pending_op = card.value
                    continue

                chip_result = eval_card(card)

                if acc is None:
                    acc = chip_result
                elif pending_op:
                    acc = apply_op_broadcast(acc, chip_result, pending_op)
                    pending_op = None
                else:
                    # op 없이 chip 연속 → union
                    acc.extend(chip_result)

            all_values = acc or []

            # transforms 적용
            def apply_tx(v: int, tx: FormulaTransform) -> int:
                if tx.op == "+":
                    return v + tx.value
                elif tx.op == "-":
                    return v - tx.value
                elif tx.op == "*":
                    return v * tx.value
                elif tx.op == "/":
                    return 0 if tx.value == 0 else v // tx.value
                elif tx.op == "%":
                    return 0 if tx.value == 0 else v % tx.value
                return v

            if ws.mode == "scalar":
                # 합산 후 chain transforms (JS line 178~182)
                scalar = sum(all_values) if all_values else 0
                for tx in ws.transforms:
                    scalar = apply_tx(scalar, tx)
                working = [scalar]
            elif not ws.transforms:
                working = list(all_values)
            else:
                # 분기 union (JS line 186~188) — 각 transform을 모든 값에 독립 적용
                branches = []
                for tx in ws.transforms:
                    branch = [apply_tx(v, tx) for v in all_values]
                    branches.append(branch)
                working = []
                for branch in branches:
                    working.extend(branch)

            if ws.mode == "tail":
                # 끝수 expand
                tail_set = {(v % 10 + 10) % 10 for v in working}
                working = [n for n in range(1, self.max_ball + 1) if n % 10 in tail_set]

            return working

        # ── applyOpBroadcast (JS line 202~220) ──
        def apply_op_broadcast(a: list[int], b: list[int], op: str) -> list[int]:
            result = set()
            for x in a:
                for y in b:
                    if op == "+":
                        v = x + y
                    elif op == "-":
                        v = x - y
                    elif op == "*":
                        v = x * y
                    elif op in ("/", "%"):
                        v = 0 if y == 0 else x % y
                    else:
                        v = x

                    # mod 45 + 1 정규화 (음수 안전)
                    v = ((v - 1) % 45 + 45) % 45 + 1
                    if 1 <= v <= 45:
                        result.add(v)
            return sorted(result)

        # ── 모든 워크스페이스 평가 (JS line 223~238) ──
        all_ws_values = [eval_ws(ws) for ws in formula.workspaces]

        # hiddenInOutput=True 제외
        visible_idx = [
            i for i, ws in enumerate(formula.workspaces) if not ws.hiddenInOutput
        ]
        ws_values = [all_ws_values[i] for i in visible_idx]

        # combineOps 재계산
        combine_ops_adjusted = []
        for k in range(1, len(visible_idx)):
            idx = visible_idx[k] - 1
            if idx < len(formula.combineOps):
                combine_ops_adjusted.append(formula.combineOps[idx])
            else:
                combine_ops_adjusted.append(type("", (), {"op": "union"})())

        if not ws_values:
            return []

        # ── combine (JS line 247~292) ──
        def combine(left: list[int], right: list[int], op: str) -> list[int]:
            if op == "union" or not op:
                return list(left) + list(right)

            if op == "intersection":
                rs = set(right)
                return [v for v in left if v in rs]

            if op == "complement":
                # 1~max_ball 중 (left ∪ right)에 없는 번호
                all_nums = set(left) | set(right)
                return [n for n in range(1, self.max_ball + 1) if n not in all_nums]

            if op == "difference":
                rs = set(right)
                return [v for v in left if v not in rs]

            if op == "symdiff":
                ls, rs = set(left), set(right)
                return [v for v in left if v not in rs] + [v for v in right if v not in ls]

            # 산술 연산
            def do_op(x: int, y: int) -> int:
                if op == "+":
                    return x + y
                elif op == "-":
                    return x - y
                elif op == "*":
                    return x * y
                elif op == "/":
                    return 0 if y == 0 else x // y
                elif op == "%":
                    return 0 if y == 0 else x % y
                return x

            L, R = len(left), len(right)
            if L == 0 or R == 0:
                return []
            if L == 1 and R == 1:
                return [do_op(left[0], right[0])]
            if L == 1:
                return [do_op(left[0], v) for v in right]
            if R == 1:
                return [do_op(v, right[0]) for v in left]
            if L == R:
                return [do_op(left[i], right[i]) for i in range(L)]

            # cartesian
            return [do_op(a, b) for a in left for b in right]

        # 좌→우 누적 결합
        working = ws_values[0] if ws_values else []
        for i in range(1, len(ws_values)):
            op = combine_ops_adjusted[i - 1].op if i - 1 < len(combine_ops_adjusted) else "union"
            working = combine(working, ws_values[i], op)

        # ── 단항 complement 처리 (JS line 302~313) ──
        if len(visible_idx) == 1:
            has_hidden = any(ws.hiddenInOutput for ws in formula.workspaces)
            if has_hidden and any(c.op == "complement" for c in formula.combineOps if hasattr(c, "op")):
                present = set(working)
                working = [n for n in range(1, self.max_ball + 1) if n not in present]

        # ── 결합 후 변환 (JS line 318~329) ──
        for tx in formula.combinePostTransforms:
            working = [self._apply_post_tx(v, tx) for v in working]

        # ── 결합 후 끝수 expand (JS line 334~341) ──
        if formula.combinePostExpand:
            tail_set = {(v % 10 + 10) % 10 for v in working}
            working = [n for n in range(1, self.max_ball + 1) if n % 10 in tail_set]

        # ── 보정 (JS line 346~366) ──
        normalized = []
        for v in working:
            if v == 0:
                continue
            if v < 0:
                r = self.max_ball + (v % self.max_ball)
                if r == 0:
                    continue
                normalized.append(r)
            elif v > self.max_ball:
                r = ((v - 1) % self.max_ball) + 1
                normalized.append(r)
            else:
                normalized.append(v)

        # 중복 제거 + 정렬
        return sorted(set(normalized))

    def _apply_post_tx(self, v: int, tx: FormulaTransform) -> int:
        """결합 후 변환 적용 (JS line 319~327)"""
        if tx.op == "+":
            return v + tx.value
        elif tx.op == "-":
            return v - tx.value
        elif tx.op == "*":
            return v * tx.value
        elif tx.op == "/":
            return 0 if tx.value == 0 else v // tx.value
        elif tx.op == "%":
            return 0 if tx.value == 0 else ((v % tx.value + tx.value) % tx.value)
        return v

    def _eval_hit(
        self, targets: list[int], next_draw: dict, include_bonus: bool
    ) -> tuple[int, bool]:
        """hit 판정 (JS 기준 동일)"""
        next_nums = set(next_draw.get("numbers", []))
        bonus = next_draw.get("bonus")

        if include_bonus and bonus is not None:
            next_nums.add(bonus)

        hit_count = len(set(targets) & next_nums)
        bonus_hit = bonus in targets if bonus is not None else False

        return hit_count, bonus_hit

    def _longest_consecutive(self, history: list[SweepHitRecord]) -> int:
        """최장 N연속 hit"""
        max_streak, cur = 0, 0
        for h in history:
            if h.hit_count > 0:
                cur += 1
                max_streak = max(max_streak, cur)
            else:
                cur = 0
        return max_streak

    def _compute_avg_gap(self, history: list[SweepHitRecord]) -> float:
        """hit 간 평균 간격"""
        hit_indices = [i for i, h in enumerate(history) if h.hit_count > 0]
        if len(hit_indices) < 2:
            return float("inf")

        gaps = [hit_indices[i + 1] - hit_indices[i] for i in range(len(hit_indices) - 1)]
        return sum(gaps) / len(gaps)
