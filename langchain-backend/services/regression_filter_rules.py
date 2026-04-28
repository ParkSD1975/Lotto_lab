"""Tier 3 — 회귀(2~200) 결합 필터 + 자동 룰 트리거.

회귀-plan Tier 3 (3-A/3-B/3-C/3-D/3-E) 구현. NumberRecommender의 force_exclude
입력으로 흘러갈 자동 제외 후보를 생성한다.

서브모듈:
  3-A. 라인 x N 매트릭스        (compute_line_x_n_matrix, detect_consecutive_miss_lines)
  3-B. 끝수 x N 매트릭스        (compute_ending_x_n_matrix, detect_ending_pattern)
  3-C. 번호대 x N 군집 + 자동 필터 룰
                              (compute_decade_x_n_matrix, detect_decade_cluster_and_apply_filter)
  3-D. 4연번 자동 제외 룰      (apply_consecutive_4_rule, apply_recent_4_consecutive_rule)
  3-E. 데드 회귀 x 라인 이월률 자동 제외 룰
                              (detect_dead_carryover_lines)
  통합. apply_all_regression_rules()
"""

from __future__ import annotations

from typing import Any

import numpy as np

import config


# ────────────────── config 상수 (default fallback) ──────────────────


REGRESSION_DECADE_CLUSTER_THRESHOLD = getattr(
    config, "REGRESSION_DECADE_CLUSTER_THRESHOLD", 3
)
REGRESSION_LINE_MISS_THRESHOLD = getattr(config, "REGRESSION_LINE_MISS_THRESHOLD", 5)
REGRESSION_CONSECUTIVE_RULE_LOOKBACK = getattr(
    config, "REGRESSION_CONSECUTIVE_RULE_LOOKBACK", 4
)
REGRESSION_DEAD_CARRYOVER_THRESHOLD = getattr(
    config, "REGRESSION_DEAD_CARRYOVER_THRESHOLD", 2
)


# ────────────────── 공용 유틸 ──────────────────


def _draw_seven(draw: dict) -> list[int]:
    """draw dict 에서 정렬된 (당첨 6 + 보너스) 리스트 반환.

    keys: 'numbers' (list[int] len 6), 'bonus' (int).
    """
    nums = list(draw.get("numbers", []))
    bonus = draw.get("bonus")
    if bonus is not None:
        nums = nums + [int(bonus)]
    nums = [int(x) for x in nums]
    return sorted(nums)


def _draws_by_round(draws: list[dict]) -> dict[int, dict]:
    """round -> draw dict 매핑 (round 키로 빠르게 조회)."""
    out: dict[int, dict] = {}
    for d in draws:
        r = d.get("round")
        if r is None:
            continue
        out[int(r)] = d
    return out


def _decade_index(n: int) -> int:
    """1~9 -> 0, 10~19 -> 1, 20~29 -> 2, 30~39 -> 3, 40~45 -> 4."""
    if n <= 9:
        return 0
    if n <= 19:
        return 1
    if n <= 29:
        return 2
    if n <= 39:
        return 3
    return 4


def _safe_active_n(active_n_list: list[int]) -> list[int]:
    """오름차순 + 중복 제거 + 양수 필터."""
    return sorted({int(n) for n in active_n_list if int(n) > 0})


# ────────────────── 3-A. 라인 x N 매트릭스 ──────────────────


def compute_line_x_n_matrix(
    draws: list[dict], active_n_list: list[int]
) -> dict[str, Any]:
    """라인(7) x 활성 N 매트릭스.

    각 셀 (k, j): 학습 데이터 전체에서, t회차 라인 k+1 위치의 번호가
    t+N(j) 회차 (당첨6+보너스)에 출현한 비율.

    returns:
      matrix:  np.ndarray shape (7, len(active_n))
      active_n: list[int]
      total_pairs_per_n: list[int]
    """
    actives = _safe_active_n(active_n_list)
    n_cols = len(actives)
    mat = np.zeros((7, n_cols), dtype=np.float64)
    total_pairs = [0] * n_cols

    if not draws or n_cols == 0:
        return {
            "matrix": mat,
            "active_n": actives,
            "total_pairs_per_n": total_pairs,
        }

    by_round = _draws_by_round(draws)
    rounds = sorted(by_round.keys())

    for j, N in enumerate(actives):
        carry_per_line = [0] * 7
        total = 0
        for t_round in rounds:
            t_plus = t_round + N
            if t_plus not in by_round:
                continue
            t_seven = _draw_seven(by_round[t_round])
            t_plus_set = set(_draw_seven(by_round[t_plus]))
            if len(t_seven) < 7:
                continue
            for k in range(7):
                if t_seven[k] in t_plus_set:
                    carry_per_line[k] += 1
            total += 1
        total_pairs[j] = total
        if total > 0:
            for k in range(7):
                mat[k, j] = carry_per_line[k] / total

    return {
        "matrix": mat,
        "active_n": actives,
        "total_pairs_per_n": total_pairs,
    }


def detect_consecutive_miss_lines(
    matrix_dict: dict[str, Any], threshold: int = REGRESSION_LINE_MISS_THRESHOLD
) -> list[dict[str, Any]]:
    """이월률이 0 또는 매우 낮은 (N, 라인) 조합 감지.

    threshold 는 "활성 N 중 carryover 0 인 N의 개수" 임계.
    한 라인에서 dead 한 N 개수 >= threshold 이면 미출 라인 후보.
    """
    mat: np.ndarray = matrix_dict["matrix"]
    actives: list[int] = matrix_dict["active_n"]
    out: list[dict[str, Any]] = []

    if mat.size == 0:
        return out

    for k in range(mat.shape[0]):
        zero_ns = [actives[j] for j in range(mat.shape[1]) if mat[k, j] <= 0.0]
        if len(zero_ns) >= threshold:
            out.append(
                {
                    "line": k + 1,
                    "consecutive_miss": len(zero_ns),
                    "dead_n_list": zero_ns,
                    "narrative": (
                        f"line {k + 1} dead in {len(zero_ns)} regression N "
                        f"({zero_ns[:5]}...)"
                    ),
                }
            )
    return out


# ────────────────── 3-B. 끝수 x N 매트릭스 ──────────────────


def compute_ending_x_n_matrix(
    draws: list[dict], active_n_list: list[int]
) -> dict[str, Any]:
    """끝수(0~9) x 활성 N 매트릭스.

    셀 (k, j): t회차 풀(7개)에서 끝수 k 인 번호가 적어도 하나 있을 때,
    t+N(j) 회차에 끝수 k 가 다시 출현한 비율.
    """
    actives = _safe_active_n(active_n_list)
    n_cols = len(actives)
    mat = np.zeros((10, n_cols), dtype=np.float64)
    total_pairs = [0] * n_cols

    if not draws or n_cols == 0:
        return {
            "matrix": mat,
            "active_n": actives,
            "total_pairs_per_n": total_pairs,
        }

    by_round = _draws_by_round(draws)
    rounds = sorted(by_round.keys())

    for j, N in enumerate(actives):
        carry_per_end = [0] * 10
        total_per_end = [0] * 10
        for t_round in rounds:
            t_plus = t_round + N
            if t_plus not in by_round:
                continue
            t_endings = {x % 10 for x in _draw_seven(by_round[t_round])}
            tp_endings = {x % 10 for x in _draw_seven(by_round[t_plus])}
            for e in t_endings:
                total_per_end[e] += 1
                if e in tp_endings:
                    carry_per_end[e] += 1
        total_pairs[j] = sum(total_per_end)
        for e in range(10):
            if total_per_end[e] > 0:
                mat[e, j] = carry_per_end[e] / total_per_end[e]

    return {
        "matrix": mat,
        "active_n": actives,
        "total_pairs_per_n": total_pairs,
    }


def detect_ending_pattern(
    matrix_dict: dict[str, Any], high_threshold: float = 0.6
) -> list[dict[str, Any]]:
    """이월률이 high_threshold 이상인 (끝수, N) 강세 패턴 감지."""
    mat: np.ndarray = matrix_dict["matrix"]
    actives: list[int] = matrix_dict["active_n"]
    out: list[dict[str, Any]] = []
    if mat.size == 0:
        return out
    for e in range(mat.shape[0]):
        for j in range(mat.shape[1]):
            if mat[e, j] >= high_threshold:
                out.append(
                    {
                        "ending": e,
                        "regression_N": actives[j],
                        "next_appearance_prob": float(mat[e, j]),
                        "narrative": (
                            f"ending {e} (N={actives[j]}) carryover "
                            f"{mat[e, j]:.2f} >= {high_threshold:.2f}"
                        ),
                    }
                )
    return out


# ────────────────── 3-C. 번호대 x N + 자동 필터 룰 ──────────────────


def compute_decade_x_n_matrix(
    draws: list[dict], active_n_list: list[int], target_round: int | None = None
) -> dict[str, Any]:
    """번호대(5) x 활성 N 매트릭스.

    셀 (d, j): 회차 (target_round - N(j)) 에서 번호대 d 에 속한 풀 멤버 개수.
    target_round 미지정 시 draws 의 max round + 1 을 사용.
    """
    actives = _safe_active_n(active_n_list)
    n_cols = len(actives)
    mat = np.zeros((5, n_cols), dtype=np.int32)
    cluster_members: dict[tuple[int, int], list[int]] = {}

    if not draws or n_cols == 0:
        return {
            "matrix": mat,
            "active_n": actives,
            "cluster_members": cluster_members,
            "target_round": target_round,
        }

    by_round = _draws_by_round(draws)
    if target_round is None:
        target_round = max(by_round.keys()) + 1
    target_round = int(target_round)

    for j, N in enumerate(actives):
        ref = target_round - N
        if ref not in by_round:
            continue
        seven = _draw_seven(by_round[ref])
        for n in seven:
            d = _decade_index(n)
            mat[d, j] += 1
            cluster_members.setdefault((d, N), []).append(n)

    return {
        "matrix": mat,
        "active_n": actives,
        "cluster_members": cluster_members,
        "target_round": target_round,
    }


def detect_decade_cluster_and_apply_filter(
    matrix_dict: dict[str, Any],
    threshold: int = REGRESSION_DECADE_CLUSTER_THRESHOLD,
) -> list[dict[str, Any]]:
    """동일 번호대 >= threshold 군집 발견 시 다른 번호대 0~1 필터 자동 트리거.

    사용자 항목 E 핵심.
    """
    mat: np.ndarray = matrix_dict["matrix"]
    actives: list[int] = matrix_dict["active_n"]
    members_lookup = matrix_dict.get("cluster_members", {})
    out: list[dict[str, Any]] = []

    if mat.size == 0:
        return out

    for d in range(mat.shape[0]):
        for j in range(mat.shape[1]):
            cnt = int(mat[d, j])
            if cnt >= threshold:
                N = actives[j]
                members = sorted(set(members_lookup.get((d, N), [])))
                applied = {f"decade_{k}_max_count": 1 for k in range(5) if k != d}
                out.append(
                    {
                        "trigger": (
                            f"decade {d} cluster {cnt} members at N={N}"
                        ),
                        "decade": d,
                        "regression_N": N,
                        "cluster_members": members,
                        "cluster_count": cnt,
                        "applied_filter": applied,
                        "evidence": [
                            f"decade={d}",
                            f"N={N}",
                            f"members={members}",
                        ],
                        "narrative": (
                            f"decade {d} cluster {cnt} (N={N}, members={members}) "
                            f"-> other decades max 1"
                        ),
                    }
                )
    return out


# ────────────────── 3-D. 4연번 자동 제외 룰 ──────────────────


def apply_consecutive_4_rule(
    regression_features: np.ndarray,
    active_n_list: list[int],
    threshold: int = REGRESSION_CONSECUTIVE_RULE_LOOKBACK,
) -> list[dict[str, Any]]:
    """회귀 N 별 max_consecutive >= threshold 인 번호 자동 제외 후보.

    Args:
        regression_features: shape (45, n_active, k_features) 또는
                             (45, n_active) 인 max_consecutive 매트릭스.
                             k_features 형태이면 마지막 축 0 슬롯을 max_consecutive 로 가정.
        active_n_list: 활성 N 리스트
        threshold: 4연번 임계
    """
    arr = np.asarray(regression_features)
    actives = _safe_active_n(active_n_list)

    if arr.ndim == 3:
        max_consec = arr[:, :, 0]
    elif arr.ndim == 2:
        max_consec = arr
    else:
        raise ValueError(
            f"regression_features must be 2D or 3D, got ndim={arr.ndim}"
        )

    if max_consec.shape[0] != 45:
        raise ValueError(
            f"regression_features axis 0 must be 45, got {max_consec.shape[0]}"
        )

    out: list[dict[str, Any]] = []
    n_active = min(max_consec.shape[1], len(actives))
    for n_idx in range(45):
        n = n_idx + 1
        for j in range(n_active):
            mc = int(max_consec[n_idx, j])
            if mc >= threshold:
                N = actives[j]
                out.append(
                    {
                        "number": n,
                        "reason": f"regression_consecutive_N{N}",
                        "max_consecutive": mc,
                        "regression_N": N,
                        "narrative": (
                            f"number {n}: N={N} regression {mc}-consecutive "
                            f"-> next round absence likely"
                        ),
                    }
                )
                break
    return out


def apply_recent_4_consecutive_rule(
    draws: list[dict], lookback: int = REGRESSION_CONSECUTIVE_RULE_LOOKBACK
) -> list[dict[str, Any]]:
    """직전 lookback 회차 연속 출현 (1회귀에서 4연번) 자동 제외.

    draws 는 round 오름/내림 어느 쪽이든 동작 (정렬 후 최신 lookback 사용).
    'numbers' + 'bonus' 합집합으로 출현 판정.
    """
    if not draws or lookback <= 0:
        return []

    by_round = _draws_by_round(draws)
    rounds_desc = sorted(by_round.keys(), reverse=True)
    if len(rounds_desc) < lookback:
        return []

    recent = rounds_desc[:lookback]
    out: list[dict[str, Any]] = []
    for n in range(1, 46):
        all_in = True
        for r in recent:
            seven = set(_draw_seven(by_round[r]))
            if n not in seven:
                all_in = False
                break
        if all_in:
            out.append(
                {
                    "number": n,
                    "reason": "recent_4_consecutive",
                    "lookback": lookback,
                    "rounds": recent,
                    "narrative": (
                        f"number {n}: recent {lookback} rounds consecutive "
                        f"appearance -> mean reversion signal"
                    ),
                }
            )
    return out


# ────────────────── 3-E. 데드 회귀 x 라인 이월률 자동 제외 ──────────────────


def detect_dead_carryover_lines(
    target_round: int,
    draws: list[dict],
    active_n_list: list[int],
    dead_threshold: int = REGRESSION_DEAD_CARRYOVER_THRESHOLD,
) -> list[dict[str, Any]]:
    """데드 회귀 x 라인 이월률 자동 제외.

    절차:
    1. 각 번호 n: target_round - N 회차 풀에 n 이 있다면 라인 k 식별.
    2. 학습 데이터 전체에서 (N, k) 이월률 계산. 이월률 0 -> dead_count += 1.
    3. dead_count >= dead_threshold -> auto_exclude.
    """
    actives = _safe_active_n(active_n_list)
    if not draws or not actives:
        return []

    by_round = _draws_by_round(draws)
    rounds_sorted = sorted(by_round.keys())
    if not rounds_sorted:
        return []

    target_round = int(target_round)

    # (N, k) -> carryover_rate cache
    cache_rate: dict[tuple[int, int], float] = {}

    def _carryover_rate(N: int, k: int) -> float:
        key = (N, k)
        if key in cache_rate:
            return cache_rate[key]
        carry, total = 0, 0
        for t_round in rounds_sorted:
            t_plus = t_round + N
            if t_plus not in by_round:
                continue
            t_seven = _draw_seven(by_round[t_round])
            if len(t_seven) < 7 or k - 1 >= len(t_seven):
                continue
            t_line_num = t_seven[k - 1]
            tp_set = set(_draw_seven(by_round[t_plus]))
            if t_line_num in tp_set:
                carry += 1
            total += 1
        rate = (carry / total) if total > 0 else -1.0
        cache_rate[key] = rate
        return rate

    out: list[dict[str, Any]] = []
    for n in range(1, 46):
        dead_count = 0
        details: list[str] = []
        for N in actives:
            ref = target_round - N
            if ref not in by_round:
                continue
            ref_seven = _draw_seven(by_round[ref])
            if n not in ref_seven:
                continue
            line_k = ref_seven.index(n) + 1  # 1..7
            rate = _carryover_rate(N, line_k)
            if rate == 0.0:
                dead_count += 1
                details.append(f"(N={N}, k={line_k}, ref_round={ref})")
        if dead_count >= dead_threshold:
            out.append(
                {
                    "number": n,
                    "reason": "dead_carryover_lines",
                    "count": dead_count,
                    "details": details,
                    "narrative": (
                        f"number {n}: dead in {dead_count} regression-line "
                        f"pairs {details} -> auto exclude"
                    ),
                }
            )
    return out


# ────────────────── 통합 ──────────────────


def apply_all_regression_rules(
    target_round: int,
    draws: list[dict],
    active_n_list: list[int],
    regression_features: np.ndarray | None = None,
) -> dict[str, Any]:
    """3-D + 3-E 통합 + 3-C 군집 트리거 결과 통합.

    returns:
      force_exclude: set[int]   NumberRecommender 입력
      rule1_consecutive_n: list (회귀 N 4연번)
      rule1_recent: list        (1회귀 4연번)
      rule2_dead_lines: list    (데드 라인)
      decade_clusters: list     (3-C 군집 + 자동 필터)
      auto_applied_filters: dict (3-C 필터 통합)
    """
    actives = _safe_active_n(active_n_list)

    # 3-D 룰 1: 회귀 N 4연번 (regression_features 가용 시)
    rule1_consec = []
    if regression_features is not None:
        rule1_consec = apply_consecutive_4_rule(regression_features, actives)

    # 3-D 룰 2: 직전 4회차 연속
    rule1_recent = apply_recent_4_consecutive_rule(draws)

    # 3-E 룰 3: 데드 라인
    rule2_dead = detect_dead_carryover_lines(target_round, draws, actives)

    # 3-C 군집 + 자동 필터
    dec_dict = compute_decade_x_n_matrix(draws, actives, target_round=target_round)
    decade_clusters = detect_decade_cluster_and_apply_filter(dec_dict)

    auto_applied: dict[str, int] = {}
    for cl in decade_clusters:
        for k, v in cl.get("applied_filter", {}).items():
            # 가장 강한(작은 값) 필터 채택
            if k not in auto_applied or v < auto_applied[k]:
                auto_applied[k] = v

    force_exclude: set[int] = set()
    for r in rule1_consec:
        force_exclude.add(int(r["number"]))
    for r in rule1_recent:
        force_exclude.add(int(r["number"]))
    for r in rule2_dead:
        force_exclude.add(int(r["number"]))

    return {
        "force_exclude": force_exclude,
        "rule1_consecutive_n": rule1_consec,
        "rule1_recent": rule1_recent,
        "rule2_dead_lines": rule2_dead,
        "decade_clusters": decade_clusters,
        "auto_applied_filters": auto_applied,
    }


# ────────────────── smoke ──────────────────


def _make_fake_draws(n_rounds: int = 200, seed: int | None = None) -> list[dict]:
    """가짜 200 회차 (numbers 6 + bonus 1)."""
    if seed is None:
        seed = config.RANDOM_SEED
    rng = np.random.default_rng(seed)
    out = []
    for r in range(1, n_rounds + 1):
        seven = rng.choice(np.arange(1, 46), size=7, replace=False)
        out.append(
            {
                "round": int(r),
                "numbers": [int(x) for x in seven[:6]],
                "bonus": int(seven[6]),
            }
        )
    return out


def _smoke() -> int:
    print("[regression_filter_rules] smoke start")
    rng = np.random.default_rng(config.RANDOM_SEED)
    draws = _make_fake_draws(200)
    active_n = [2, 3, 5, 8, 12, 22, 30]

    # 3-A
    line_dict = compute_line_x_n_matrix(draws, active_n)
    print(
        f"[3-A] line_x_N matrix shape={line_dict['matrix'].shape}, "
        f"active_n={line_dict['active_n']}"
    )
    miss_lines = detect_consecutive_miss_lines(line_dict, threshold=4)
    print(f"[3-A] consecutive_miss_lines count={len(miss_lines)}")

    # 3-B
    end_dict = compute_ending_x_n_matrix(draws, active_n)
    print(f"[3-B] ending_x_N matrix shape={end_dict['matrix'].shape}")
    end_pat = detect_ending_pattern(end_dict, high_threshold=0.5)
    print(f"[3-B] ending pattern count={len(end_pat)}")

    # 3-C
    target_round = 201
    dec_dict = compute_decade_x_n_matrix(
        draws, active_n, target_round=target_round
    )
    print(
        f"[3-C] decade_x_N matrix shape={dec_dict['matrix'].shape}, "
        f"target_round={dec_dict['target_round']}"
    )
    clusters = detect_decade_cluster_and_apply_filter(dec_dict, threshold=3)
    print(f"[3-C] decade clusters triggered={len(clusters)}")
    if clusters:
        c0 = clusters[0]
        print(
            f"  cluster sample: decade={c0['decade']} N={c0['regression_N']} "
            f"count={c0['cluster_count']} members={c0['cluster_members']}"
        )

    # 3-D rule1 (가짜 features: shape (45, n_active))
    fake_max_consec = rng.integers(0, 6, size=(45, len(active_n)))
    rule1_n = apply_consecutive_4_rule(fake_max_consec, active_n, threshold=4)
    print(f"[3-D] rule1 (regression N 4-consec) auto exclude count={len(rule1_n)}")

    # 3-D rule2
    rule1_recent = apply_recent_4_consecutive_rule(draws, lookback=4)
    print(f"[3-D] rule2 (recent 4-consec) auto exclude count={len(rule1_recent)}")

    # 3-E
    dead_lines = detect_dead_carryover_lines(
        target_round, draws, active_n, dead_threshold=2
    )
    print(f"[3-E] dead carryover auto exclude count={len(dead_lines)}")

    # integrated
    summary = apply_all_regression_rules(
        target_round, draws, active_n, regression_features=fake_max_consec
    )
    print(
        f"[ALL] force_exclude size={len(summary['force_exclude'])} "
        f"sample={sorted(summary['force_exclude'])[:10]}"
    )
    print(
        f"[ALL] auto_applied_filters keys={list(summary['auto_applied_filters'].keys())}"
    )
    print("[regression_filter_rules] smoke OK")
    return 0


def main() -> int:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--smoke", action="store_true")
    args = p.parse_args()
    if args.smoke:
        return _smoke()
    print("[regression_filter_rules] use --smoke to run smoke test")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
