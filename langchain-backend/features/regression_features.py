"""회귀(2~200) Tier 2 — 번호별 8 압축 변수 빌더.

각 번호 1~45별 회귀 분석을 8개 변수로 압축. 45 × 8 = 360 dim 매트릭스를
메인 ensemble.py 입력에 합류 가능하게 한다.

압축 변수 (각 번호 n에 대해):
  - regression_appearance_count: 199 N 중 등장 누적 (0~199)
  - regression_avg_gap: 등장한 N의 평균 (높을수록 장기 회귀 우세)
  - regression_max_consecutive: 어느 N에서 가장 길게 연속 활성
  - regression_top3_active_N: top 3 활성 N 인덱스 (정수 3개)
  - regression_low_N_density: N<=10 활성도
  - regression_mid_N_density: N=11~50 활성도
  - regression_high_N_density: N>=51 활성도
  - regression_sequence_dormancy: 가장 최근 회귀 활성 후 경과 회차
  - (옵션) regression_mhn_similarity: MHN top-K 유사도 (의존성 충족 시만)

회귀 N=k 정의:
  t회차 분석에서 (t-k)회차 풀(6번호+보너스) 멤버 중 1명 이상이 t회차에 출현.
  번호 n이 N=k에 활성이라는 것은: 어떤 t에 대해 n이 (t-k) 풀과 t 풀 양쪽에 들어있음.
"""

from __future__ import annotations

import numpy as np

import config


# 회귀 기본 파라미터
_REGRESSION_N_RANGE: tuple[int, int] = getattr(config, "REGRESSION_N_RANGE", (2, 200))
_LOW_N_MAX = 10
_MID_N_MAX = 50

# MHN 가용성 (옵션 — 의존성 미충족 시 mhn_similarity skip)
try:
    from models.mhn_model import LottoMHN, TORCH_AVAILABLE as _MHN_TORCH_OK

    _MHN_AVAILABLE = bool(_MHN_TORCH_OK)
except Exception:
    _MHN_AVAILABLE = False
    LottoMHN = None  # type: ignore


# ────────────────── 풀/유틸 ──────────────────


def _draw_seven(d: dict) -> set[int]:
    """단일 회차 풀 (6번호 + 보너스)."""
    nums: set[int] = set()
    for n in d.get("numbers", []):
        try:
            nums.add(int(n))
        except (TypeError, ValueError):
            continue
    bonus = d.get("bonus")
    if bonus is not None:
        try:
            nums.add(int(bonus))
        except (TypeError, ValueError):
            pass
    return nums


def _ordered(draws: list[dict]) -> list[dict]:
    """draws → 시간순 정렬."""
    return sorted(draws, key=lambda d: int(d.get("round", 0)))


# ────────────────── 휴면도 ──────────────────


def compute_dormancy_per_number(draws: list[dict]) -> dict[int, int]:
    """각 번호의 마지막 출현 후 경과 회차. 풀 = 6번호 + 보너스 기준.

    Returns: {n: dormancy} — n이 한 번도 등장 안하면 len(draws).
    """
    ordered = _ordered(draws)
    T = len(ordered)
    last_seen: dict[int, int] = {}
    for i, d in enumerate(ordered):
        for n in _draw_seven(d):
            last_seen[n] = i
    out: dict[int, int] = {}
    for n in range(1, 46):
        if n in last_seen:
            out[n] = T - 1 - last_seen[n]
        else:
            out[n] = T
    return out


# ────────────────── 회귀 활성/연속 측정 ──────────────────


def _build_n_activity_for_number(
    n: int,
    ordered: list[dict],
    n_range: tuple[int, int] = _REGRESSION_N_RANGE,
) -> dict[int, np.ndarray]:
    """번호 n의 N별 활성 시계열. {N: array shape (T,) bool}.

    각 t에 대해 n이 (t-N) 풀과 t 풀 양쪽에 있으면 1, 아니면 0.
    """
    T = len(ordered)
    n_min, n_max = int(n_range[0]), int(n_range[1])
    activities: dict[int, np.ndarray] = {}
    # 각 t의 풀 캐시
    pools: list[set[int]] = [_draw_seven(d) for d in ordered]
    presence = np.array([1 if n in p else 0 for p in pools], dtype=np.int8)

    for N in range(n_min, n_max + 1):
        if N >= T:
            break
        arr = np.zeros(T, dtype=np.int8)
        for t in range(N, T):
            if presence[t] == 1 and presence[t - N] == 1:
                arr[t] = 1
        if arr.any():
            activities[N] = arr
    return activities


def compute_max_consecutive_for_number(
    n: int,
    draws: list[dict],
    n_range: tuple[int, int] = _REGRESSION_N_RANGE,
) -> dict[int, int]:
    """각 N에 대해 번호 n의 max consecutive 활성 길이.

    Tier 3-D 자동 룰 룰 1 입력 (4연번 자동 제외 트리거).
    """
    ordered = _ordered(draws)
    activities = _build_n_activity_for_number(n, ordered, n_range)
    out: dict[int, int] = {}
    for N, arr in activities.items():
        max_run = 0
        cur = 0
        for v in arr:
            if v:
                cur += 1
                if cur > max_run:
                    max_run = cur
            else:
                cur = 0
        out[N] = int(max_run)
    return out


# ────────────────── 단일 번호 압축 변수 ──────────────────


def build_regression_compression_for_number(
    n: int,
    draws: list[dict],
    gnn_data: dict | None = None,
    n_range: tuple[int, int] = _REGRESSION_N_RANGE,
) -> dict[str, float]:
    """번호 n의 8 압축 변수.

    Args:
      n: 번호 (1~45)
      draws: 회차 list (시간순/최신순 모두 허용)
      gnn_data: 옵션. mhn_similarity 산출용 패턴 메모리 (key="mhn_patterns").
      n_range: 회귀 N 범위 (default (2, 200))

    Returns:
      dict with 8 (or 9 with mhn) 변수.
    """
    ordered = _ordered(draws)
    T = len(ordered)
    if T < 2:
        return _zero_compression()

    n_min, n_max = int(n_range[0]), int(n_range[1])
    activities = _build_n_activity_for_number(n, ordered, n_range)

    # 등장 N 목록 (1회 이상 활성한 N)
    active_n_list: list[int] = sorted(activities.keys())
    appearance_count = len(active_n_list)

    if appearance_count == 0:
        out = _zero_compression()
        # 기본 sequence_dormancy은 T (한 번도 회귀 활성 안 됨)
        out["regression_sequence_dormancy"] = float(T)
        return out

    # avg gap = 등장한 N의 평균
    avg_gap = float(np.mean(active_n_list))

    # max consecutive = 어느 N에서 가장 길게 연속 활성
    max_consecutive = 0
    for N, arr in activities.items():
        cur = 0
        for v in arr:
            if v:
                cur += 1
                if cur > max_consecutive:
                    max_consecutive = cur
            else:
                cur = 0

    # top3 active N — 활성 빈도(arr.sum()) 내림차순 top 3 N 인덱스
    by_freq: list[tuple[int, int]] = []
    for N in active_n_list:
        by_freq.append((N, int(activities[N].sum())))
    by_freq.sort(key=lambda x: (-x[1], x[0]))
    top3 = [N for N, _ in by_freq[:3]]
    while len(top3) < 3:
        top3.append(0)

    # density: N 범위별 등장 비율 (활성 N 개수 / 해당 범위 N 개수)
    low_total = max(_LOW_N_MAX - n_min + 1, 1) if n_min <= _LOW_N_MAX else 1
    mid_total = max(min(_MID_N_MAX, n_max) - max(_LOW_N_MAX + 1, n_min) + 1, 1)
    high_total = max(n_max - max(_MID_N_MAX + 1, n_min) + 1, 1)

    low_count = sum(1 for N in active_n_list if N <= _LOW_N_MAX)
    mid_count = sum(1 for N in active_n_list if _LOW_N_MAX < N <= _MID_N_MAX)
    high_count = sum(1 for N in active_n_list if N > _MID_N_MAX)

    low_density = low_count / low_total
    mid_density = mid_count / mid_total
    high_density = high_count / high_total

    # sequence_dormancy = 가장 최근 회귀 활성(어느 N이든 1) 후 경과 회차
    last_active_t = -1
    for N, arr in activities.items():
        idx = np.where(arr > 0)[0]
        if len(idx) > 0 and int(idx[-1]) > last_active_t:
            last_active_t = int(idx[-1])
    sequence_dormancy = float(T - 1 - last_active_t) if last_active_t >= 0 else float(T)

    out: dict[str, float] = {
        "regression_appearance_count": float(appearance_count),
        "regression_avg_gap": float(avg_gap),
        "regression_max_consecutive": float(max_consecutive),
        "regression_top3_active_N_0": float(top3[0]),
        "regression_top3_active_N_1": float(top3[1]),
        "regression_top3_active_N_2": float(top3[2]),
        "regression_low_N_density": float(low_density),
        "regression_mid_N_density": float(mid_density),
        "regression_high_N_density": float(high_density),
        "regression_sequence_dormancy": float(sequence_dormancy),
    }

    # MHN 유사도 (옵션)
    if gnn_data is not None and "mhn_patterns" in gnn_data and _MHN_AVAILABLE:
        try:
            sim = _compute_mhn_similarity(
                ordered=ordered,
                target_number=n,
                mhn_patterns=gnn_data["mhn_patterns"],
                top_k=int(gnn_data.get("mhn_top_k", 5)),
            )
            out["regression_mhn_similarity"] = float(sim)
        except Exception:
            out["regression_mhn_similarity"] = 0.0

    return out


def _zero_compression() -> dict[str, float]:
    """등장 0 회 fallback."""
    return {
        "regression_appearance_count": 0.0,
        "regression_avg_gap": 0.0,
        "regression_max_consecutive": 0.0,
        "regression_top3_active_N_0": 0.0,
        "regression_top3_active_N_1": 0.0,
        "regression_top3_active_N_2": 0.0,
        "regression_low_N_density": 0.0,
        "regression_mid_N_density": 0.0,
        "regression_high_N_density": 0.0,
        "regression_sequence_dormancy": 0.0,
    }


# ────────────────── MHN 유사도 (옵션) ──────────────────


def _compute_mhn_similarity(
    ordered: list[dict],
    target_number: int,
    mhn_patterns: np.ndarray,
    top_k: int = 5,
) -> float:
    """번호 target_number 회귀 패턴 query에 대해 MHN top-K 평균 유사도.

    mhn_patterns: shape (M, D) 사전 저장된 회차 패턴.
    """
    if not _MHN_AVAILABLE or LottoMHN is None:
        return 0.0
    arr = np.asarray(mhn_patterns, dtype=np.float32)
    if arr.ndim != 2 or arr.shape[0] == 0:
        return 0.0

    D = arr.shape[1]
    # query: target_number의 활성 시계열 압축 → D dim에 맞춰 정렬
    activities = _build_n_activity_for_number(target_number, ordered)
    if not activities:
        return 0.0
    flat: list[float] = []
    for N in sorted(activities.keys()):
        flat.append(float(activities[N].sum()))
    q = np.asarray(flat, dtype=np.float32)
    if q.shape[0] < D:
        q = np.concatenate([q, np.zeros(D - q.shape[0], dtype=np.float32)])
    elif q.shape[0] > D:
        q = q[:D]

    try:
        mhn = LottoMHN(input_dim=D)
        mhn.store_patterns(arr)
        out = mhn.retrieve(q.reshape(1, -1), top_k=top_k)
        sims = np.asarray(out["similarities"], dtype=np.float32).flatten()
        return float(sims.mean())
    except Exception:
        return 0.0


# ────────────────── 매트릭스 빌더 ──────────────────


_FEATURE_KEYS_BASE: tuple[str, ...] = (
    "regression_appearance_count",
    "regression_avg_gap",
    "regression_max_consecutive",
    "regression_top3_active_N_0",  # 3 entries collapsed to single dim representation
    "regression_low_N_density",
    "regression_mid_N_density",
    "regression_high_N_density",
    "regression_sequence_dormancy",
)
# top3는 3개 정수 — 압축 8 변수 표기상 single 셀에 0번째만 넣어도 8 dim 유지.
# 별도 매트릭스 사용 시 top3 3개 모두 보존하려면 build_regression_features_matrix_full 사용.


def build_regression_features_matrix(
    draws: list[dict],
    n_range: tuple[int, int] = _REGRESSION_N_RANGE,
    gnn_data: dict | None = None,
) -> np.ndarray:
    """45 × 8 매트릭스. 각 번호의 8 압축 변수.

    top3_active_N은 첫 번째(top1)만 압축 변수에 합류. 전체 3개 보존이 필요하면
    build_regression_features_matrix_full() 사용.

    Returns: shape (45, 8) float32.
    """
    rows: list[list[float]] = []
    for n in range(1, 46):
        comp = build_regression_compression_for_number(n, draws, gnn_data, n_range)
        rows.append([float(comp.get(k, 0.0)) for k in _FEATURE_KEYS_BASE])
    return np.asarray(rows, dtype=np.float32)


def build_regression_features_matrix_full(
    draws: list[dict],
    n_range: tuple[int, int] = _REGRESSION_N_RANGE,
    gnn_data: dict | None = None,
) -> tuple[np.ndarray, list[str]]:
    """45 × 10 매트릭스 (top3 3개 모두 + density 3개 + 나머지). full feature 보존.

    Returns: (matrix shape (45, 10), feature_names list).
    """
    full_keys = (
        "regression_appearance_count",
        "regression_avg_gap",
        "regression_max_consecutive",
        "regression_top3_active_N_0",
        "regression_top3_active_N_1",
        "regression_top3_active_N_2",
        "regression_low_N_density",
        "regression_mid_N_density",
        "regression_high_N_density",
        "regression_sequence_dormancy",
    )
    rows: list[list[float]] = []
    for n in range(1, 46):
        comp = build_regression_compression_for_number(n, draws, gnn_data, n_range)
        rows.append([float(comp.get(k, 0.0)) for k in full_keys])
    return np.asarray(rows, dtype=np.float32), list(full_keys)


# ────────────────── CLI smoke ──────────────────


def _generate_fake_draws(n_rounds: int, seed: int = config.RANDOM_SEED) -> list[dict]:
    rng = np.random.default_rng(seed)
    pool = np.arange(1, 46)
    draws: list[dict] = []
    for r in range(n_rounds):
        nums = sorted(rng.choice(pool, size=6, replace=False).tolist())
        bonus_pool = [int(n) for n in pool if n not in nums]
        bonus = int(rng.choice(bonus_pool))
        draws.append({"round": 1000 + r, "numbers": nums, "bonus": bonus})
    return draws


def main() -> None:
    """python -m features.regression_features --smoke."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--rounds", type=int, default=200)
    args = parser.parse_args()

    if not args.smoke:
        parser.print_help()
        return

    print("[regression_features] smoke start")
    draws = _generate_fake_draws(args.rounds)
    print(f"  fake draws: {len(draws)}")

    # 단일 번호 압축 변수
    print("  single-number compression (n=1)...")
    comp = build_regression_compression_for_number(1, draws)
    for k, v in comp.items():
        print(f"    {k:35s} = {v:.4f}")

    # 정합성: appearance_count >= top3 nonzero count
    nonzero_top3 = sum(1 for k in ("regression_top3_active_N_0", "regression_top3_active_N_1", "regression_top3_active_N_2")
                       if comp.get(k, 0.0) > 0)
    assert comp["regression_appearance_count"] >= nonzero_top3, (
        f"appearance_count {comp['regression_appearance_count']} < top3 nonzero {nonzero_top3}"
    )
    print(f"    appearance >= nonzero top3 OK ({comp['regression_appearance_count']:.0f} >= {nonzero_top3})")

    # avg_gap < n_max (회귀 범위 내)
    n_min, n_max = _REGRESSION_N_RANGE
    if comp["regression_appearance_count"] > 0:
        assert n_min <= comp["regression_avg_gap"] <= n_max, (
            f"avg_gap {comp['regression_avg_gap']} out of [{n_min}, {n_max}]"
        )
        print(f"    avg_gap within range [{n_min}, {n_max}] OK")

    # max_consecutive 정합성: 별도 함수와 일치
    mc_dict = compute_max_consecutive_for_number(1, draws)
    if mc_dict:
        max_mc = max(mc_dict.values())
        assert int(comp["regression_max_consecutive"]) == int(max_mc), (
            f"compression max_consecutive {comp['regression_max_consecutive']} != "
            f"compute_max_consecutive max {max_mc}"
        )
        print(f"    max_consecutive matches compute_max_consecutive_for_number ({max_mc})")

    # 매트릭스
    print("  matrix build (45 x 8)...")
    mat = build_regression_features_matrix(draws)
    print(f"    matrix shape: {mat.shape}, dtype: {mat.dtype}")
    assert mat.shape == (45, 8), f"matrix shape mismatch: {mat.shape}"
    print(f"    matrix mean: {mat.mean():.4f}, max: {mat.max():.4f}")

    # full matrix (45 x 10)
    full_mat, full_keys = build_regression_features_matrix_full(draws)
    print(f"    full matrix shape: {full_mat.shape}, n_keys: {len(full_keys)}")
    assert full_mat.shape == (45, 10), f"full matrix shape mismatch: {full_mat.shape}"

    # dormancy
    print("  dormancy per number...")
    dorm = compute_dormancy_per_number(draws)
    print(f"    n=1 dormancy: {dorm[1]}, n=45 dormancy: {dorm[45]}")
    assert all(0 <= v <= len(draws) for v in dorm.values()), "dormancy out of range"
    print("    dormancy range OK")

    # MHN 유사도 (옵션)
    if _MHN_AVAILABLE:
        print("  MHN similarity (optional)...")
        rng = np.random.default_rng(config.RANDOM_SEED)
        fake_patterns = rng.standard_normal((50, 16)).astype(np.float32)
        comp_mhn = build_regression_compression_for_number(
            1, draws, gnn_data={"mhn_patterns": fake_patterns, "mhn_top_k": 5}
        )
        if "regression_mhn_similarity" in comp_mhn:
            print(f"    mhn_similarity: {comp_mhn['regression_mhn_similarity']:.4f}")
        else:
            print("    mhn_similarity skipped")
    else:
        print("  MHN not available, mhn_similarity skipped (expected)")

    print("  smoke OK")


if __name__ == "__main__":
    main()
