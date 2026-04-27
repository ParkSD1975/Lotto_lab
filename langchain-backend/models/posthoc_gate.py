"""T-1 결정 A: 메인 1~45 모델은 INPUT_DIM 동결, Phase 출력은 후처리 게이트로만 결합.

본 모듈은 ensemble.predict() 후단에서 호출되어 메인 모델의 prob[1..45]를
21지표 predictor 출력으로 *보정*한다. 메인 모델은 Phase 출력에 의존하지 않으므로
INPUT_DIM 폭증 위험 해소 (이전 검토 3-1).

설계 원칙:
- 게이트는 *부드러운* 보정 — 곱셈식·log 가산식. 갑작스러운 0 강제는 hard filter에 양보.
- 게이트 미가용 시(predictor 출력 없음·캐시 미스) raw probs 그대로 반환.
- 모든 게이트 적용 후 합=1 정규화.

호출 패턴:
    >>> gate = PosthocGate()
    >>> gate.add_gate("decade_5", DecadeGate(predictor_outputs))
    >>> adjusted = gate.apply(main_probs)  # {1~45: float}
"""

from __future__ import annotations

from typing import Callable, Iterable

import numpy as np


class PosthocGate:
    """메인 ensemble probs[1..45] → Phase 보정 prob.

    - register: 게이트 함수 등록. signature: fn(probs45) -> probs45 (numpy array)
    - apply: 등록된 게이트 순차 적용 + 합=1 정규화
    """

    def __init__(self):
        self._gates: list[tuple[str, Callable[[np.ndarray], np.ndarray]]] = []

    def register(self, name: str, gate_fn: Callable[[np.ndarray], np.ndarray]) -> None:
        """게이트 등록.

        Args:
            name: 식별자 (디버그/log)
            gate_fn: probs45 (shape (45,)) → probs45. 합 정규화는 자동 처리됨.
        """
        if not callable(gate_fn):
            raise TypeError(f"gate_fn for '{name}' must be callable")
        self._gates.append((name, gate_fn))

    def clear(self) -> None:
        self._gates.clear()

    @property
    def registered(self) -> list[str]:
        return [name for name, _ in self._gates]

    def apply(self, probs: dict | np.ndarray) -> dict[int, float]:
        """게이트 순차 적용. probs는 {1~45: float} 또는 shape (45,) ndarray.

        Returns:
            {1~45: float} — 합=1 정규화된 보정 prob
        """
        arr = self._unwrap(probs)
        for name, fn in self._gates:
            try:
                out = np.asarray(fn(arr), dtype=np.float64)
                if out.shape != (45,):
                    # 게이트 출력 invalid → 무시
                    continue
                arr = out
            except Exception as e:
                # 게이트 실패는 raw 보존. 운영 안정성 우선.
                print(f"  [PosthocGate] '{name}' 실패 (skip): {e}")
                continue

        # 안전: 음수 클립, 합 정규화
        arr = np.clip(arr, 0.0, None)
        total = arr.sum()
        if total > 0:
            arr = arr / total
        else:
            arr = np.full(45, 1.0 / 45.0)

        return {n: float(arr[n - 1]) for n in range(1, 46)}

    @staticmethod
    def _unwrap(probs) -> np.ndarray:
        if isinstance(probs, dict):
            return np.array([float(probs.get(n, 1.0 / 45.0)) for n in range(1, 46)],
                            dtype=np.float64)
        a = np.asarray(probs, dtype=np.float64).ravel()
        if a.shape != (45,):
            raise ValueError(f"probs must have 45 elements, got {a.shape}")
        return a


# ── 게이트 빌더 — predictor 출력 → gate_fn 변환 ──────────────────────────────


def build_decade_gate(decade_dist: list, strength: float = 1.0) -> Callable:
    """번호대 5분포(예측) 기반 게이트 빌더.

    Args:
        decade_dist: shape (5,) — [단번대, 10대, 20대, 30대, 40대] expected count (합 ≈ 6)
        strength: 게이트 강도 (0=비활성, 1=완전 적용). 메인 prob × multiplier.

    Returns:
        gate_fn(probs45) → probs45
    """
    decade_dist = np.asarray(decade_dist, dtype=np.float64)
    if decade_dist.shape != (5,):
        raise ValueError(f"decade_dist must have 5 elements, got {decade_dist.shape}")
    # 각 번호대의 raw 풀 크기
    sizes = np.array([9, 10, 10, 10, 6], dtype=np.float64)
    # 정규화: expected/size = 단위 풀 멤버 출현률
    rates = np.where(sizes > 0, decade_dist / sizes, 0.0)

    # 번호 → 번호대 매핑
    def _decade_idx(n: int) -> int:
        if n <= 9: return 0
        elif n <= 19: return 1
        elif n <= 29: return 2
        elif n <= 39: return 3
        else: return 4

    # 게이트 multiplier — rates 평균 대비 비율
    mean_rate = rates.mean() if rates.mean() > 0 else 1.0
    multiplier = np.zeros(45, dtype=np.float64)
    for num in range(1, 46):
        m = rates[_decade_idx(num)] / mean_rate if mean_rate > 0 else 1.0
        # strength=1이면 m, strength=0이면 1 (게이트 미적용)
        multiplier[num - 1] = (1.0 - strength) + strength * m

    def gate_fn(probs45: np.ndarray) -> np.ndarray:
        return probs45 * multiplier

    return gate_fn


def build_excluded_set_gate(excluded: Iterable[int]) -> Callable:
    """사용자 메모/hard filter 등 강제 제외 번호 → 0.

    Args:
        excluded: 제외할 1~45 정수 집합.

    Returns:
        gate_fn(probs45) → probs45 (제외 번호는 0)
    """
    mask = np.ones(45, dtype=np.float64)
    for n in excluded:
        if 1 <= int(n) <= 45:
            mask[int(n) - 1] = 0.0

    def gate_fn(probs45: np.ndarray) -> np.ndarray:
        return probs45 * mask

    return gate_fn
