"""Pillar 4 보조 모듈 — 11 base 모델 순위 추출 및 슬라이스 합의도 계산.

각 base 모델이 1~45 번호별 prob를 반환할 때, 이를 순위 벡터로 변환한 뒤
사용자 정의 슬라이스 (default 5분할) 단위로 합집합/공집합/카운트 매트릭스를
산출한다.

단일 진실 공급원: docs/MASTER_PLAN.md (Stage 3-A)
참고 archive: docs/_archive/2026-04-28/number-recommendation-plan.md (Pillar 4)
"""
from __future__ import annotations

from itertools import combinations
from typing import Iterable

import numpy as np

try:
    import config  # type: ignore
    _RANDOM_SEED = int(getattr(config, "RANDOM_SEED", 42))
except Exception:
    _RANDOM_SEED = 42


# ── 5분할 default 슬라이스 (1-indexed, inclusive) ─────────────────────────
DEFAULT_SLICES: list[tuple[int, int]] = [
    (1, 9),     # Slice 1: 1~9위 — 강 추천 합의
    (10, 19),   # Slice 2: 10~19위
    (20, 29),   # Slice 3: 20~29위
    (30, 39),   # Slice 4: 30~39위
    (40, 45),   # Slice 5: 40~45위 — 강 제외 합의
]


class ModelRankExtractor:
    """11 base 모델 순위 추출 + 슬라이스 + 합집합/공집합 매트릭스 산출기."""

    def __init__(self, default_slices: list[tuple[int, int]] | None = None):
        """기본 슬라이스를 설정한다 (사용자 정의 가능).

        Args:
            default_slices: [(a, b), ...] 1-indexed inclusive. None이면 5분할 default.
        """
        self.default_slices: list[tuple[int, int]] = (
            default_slices if default_slices is not None else list(DEFAULT_SLICES)
        )
        # 재현성: numpy 동률 처리 등에 영향 없도록 시드만 보관
        self._seed = _RANDOM_SEED

    # ------------------------------------------------------------------
    # 1. ranking 추출
    # ------------------------------------------------------------------
    def extract_rankings(
        self,
        model_outputs: dict[str, dict[int, float] | None],
    ) -> dict[str, list[int]]:
        """모델별 1~45 prob → 순위 벡터 (rank=1이 prob 최고).

        Args:
            model_outputs: {model_name: {n: prob for n in 1..45}} — 일부 None 허용

        Returns:
            {model_name: [number_at_rank_1, ..., number_at_rank_45]}
            None / 빈 dict 모델은 결과에서 skip.

        Notes:
            동률 처리: 같은 prob이면 번호가 작은 쪽이 우선 (안정 정렬).
        """
        rankings: dict[str, list[int]] = {}
        for name, probs in model_outputs.items():
            if probs is None:
                continue
            if not isinstance(probs, dict) or len(probs) == 0:
                continue

            # 1~45 범위로 정규화 (없는 키는 0 prob)
            normalized: dict[int, float] = {}
            for n in range(1, 46):
                v = probs.get(n, None)
                if v is None:
                    v = probs.get(str(n), 0.0)
                try:
                    normalized[n] = float(v) if v is not None else 0.0
                except (TypeError, ValueError):
                    normalized[n] = 0.0

            # prob 내림차순 + 동률 시 번호 오름차순
            ordered = sorted(
                range(1, 46),
                key=lambda x: (-normalized[x], x),
            )
            rankings[name] = ordered

        return rankings

    # ------------------------------------------------------------------
    # 2. 슬라이스 분할
    # ------------------------------------------------------------------
    def slice_by_ranges(
        self,
        rankings: dict[str, list[int]],
        ranges: list[tuple[int, int]] | None = None,
    ) -> dict[str, dict[str, list[int]]]:
        """모델별 ranking을 사용자 슬라이스로 자른다.

        Args:
            rankings: extract_rankings() 결과
            ranges: [(a, b), ...] 1-indexed inclusive. None이면 default 사용

        Returns:
            {model_name: {"rank_{a}-{b}": [numbers in that slice]}}
        """
        slices = ranges if ranges is not None else self.default_slices
        valid_slices = self._validate_slices(slices)

        result: dict[str, dict[str, list[int]]] = {}
        for name, rank_vec in rankings.items():
            sliced: dict[str, list[int]] = {}
            for a, b in valid_slices:
                key = f"rank_{a}-{b}"
                # 1-indexed inclusive → 0-indexed slice [a-1:b]
                lo = max(0, a - 1)
                hi = min(len(rank_vec), b)
                sliced[key] = list(rank_vec[lo:hi])
            result[name] = sliced
        return result

    # ------------------------------------------------------------------
    # 3. 단일 슬라이스 합의도
    # ------------------------------------------------------------------
    def consensus_within_slice(
        self,
        rankings: dict[str, list[int]],
        slice_range: tuple[int, int],
    ) -> dict:
        """단일 슬라이스(a, b) 내 모델 간 합의도.

        Args:
            rankings: extract_rankings() 결과
            slice_range: (a, b) 1-indexed inclusive

        Returns:
            {
              "slice_range":        (a, b),
              "intersection":       sorted list — 모든 모델이 슬라이스에 둔 번호
              "union":              sorted list — 어느 한 모델이라도 둔 번호
              "per_number_count":   {n: count of models having n in slice}
              "pairwise_overlap":   {(model_a, model_b): count}
              "consensus_strength": float (intersection / union 비율)
              "n_models":           int — 입력 활성 모델 수
            }
        """
        a, b = self._validate_slices([slice_range])[0]
        active = {m: r for m, r in rankings.items() if r}
        n_models = len(active)

        if n_models == 0:
            return {
                "slice_range": (a, b),
                "intersection": [],
                "union": [],
                "per_number_count": {},
                "pairwise_overlap": {},
                "consensus_strength": 0.0,
                "n_models": 0,
            }

        # 모델별 슬라이스 set
        per_model_set: dict[str, set[int]] = {}
        for name, rank_vec in active.items():
            lo = max(0, a - 1)
            hi = min(len(rank_vec), b)
            per_model_set[name] = set(rank_vec[lo:hi])

        # intersection / union
        sets = list(per_model_set.values())
        intersection: set[int] = set.intersection(*sets) if sets else set()
        union: set[int] = set.union(*sets) if sets else set()

        # per_number_count
        per_number_count: dict[int, int] = {}
        for n in sorted(union):
            per_number_count[n] = sum(1 for s in sets if n in s)

        # pairwise_overlap (모델 쌍별 겹치는 번호 수)
        pairwise_overlap: dict[tuple[str, str], int] = {}
        names_sorted = sorted(per_model_set.keys())
        for ma, mb in combinations(names_sorted, 2):
            pairwise_overlap[(ma, mb)] = len(per_model_set[ma] & per_model_set[mb])

        consensus_strength = (
            len(intersection) / len(union) if len(union) > 0 else 0.0
        )

        return {
            "slice_range": (a, b),
            "intersection": sorted(intersection),
            "union": sorted(union),
            "per_number_count": per_number_count,
            "pairwise_overlap": pairwise_overlap,
            "consensus_strength": float(consensus_strength),
            "n_models": n_models,
        }

    # ------------------------------------------------------------------
    # 4. 다중 슬라이스 통합
    # ------------------------------------------------------------------
    def consensus_across_slices(
        self,
        rankings: dict[str, list[int]],
        slices: list[tuple[int, int]] | None = None,
    ) -> dict:
        """모든 슬라이스에 대해 consensus_within_slice를 실행하여 통합.

        Args:
            rankings: extract_rankings() 결과
            slices: 사용자 정의 슬라이스. None이면 default 5분할

        Returns:
            {
              "slices": [(a,b), ...],
              "n_models": int,
              "model_names": list,
              "by_slice": {
                 "slice_{idx}_rank_{a}-{b}": consensus_within_slice(...) dict
              },
              "summary": {
                 "avg_consensus_strength": float,
                 "max_intersection_slice": str,
                 "min_intersection_slice": str,
              }
            }
        """
        slc_list = slices if slices is not None else self.default_slices
        slc_list = self._validate_slices(slc_list)

        active = {m: r for m, r in rankings.items() if r}
        model_names = sorted(active.keys())

        by_slice: dict[str, dict] = {}
        strengths: list[float] = []
        intersection_sizes: list[tuple[str, int]] = []

        for idx, (a, b) in enumerate(slc_list, start=1):
            res = self.consensus_within_slice(active, (a, b))
            key = f"slice_{idx}_rank_{a}-{b}"
            by_slice[key] = res
            strengths.append(res["consensus_strength"])
            intersection_sizes.append((key, len(res["intersection"])))

        avg_strength = float(np.mean(strengths)) if strengths else 0.0
        max_slice = max(intersection_sizes, key=lambda kv: kv[1])[0] if intersection_sizes else ""
        min_slice = min(intersection_sizes, key=lambda kv: kv[1])[0] if intersection_sizes else ""

        return {
            "slices": slc_list,
            "n_models": len(model_names),
            "model_names": model_names,
            "by_slice": by_slice,
            "summary": {
                "avg_consensus_strength": avg_strength,
                "max_intersection_slice": max_slice,
                "min_intersection_slice": min_slice,
            },
        }

    # ------------------------------------------------------------------
    # 헬퍼
    # ------------------------------------------------------------------
    @staticmethod
    def _validate_slices(slices: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
        """슬라이스 범위 검증 — 1<=a<=b<=45 강제."""
        out: list[tuple[int, int]] = []
        for s in slices:
            if not (isinstance(s, (tuple, list)) and len(s) == 2):
                raise ValueError(f"slice must be (a, b) tuple, got {s}")
            a, b = int(s[0]), int(s[1])
            if not (1 <= a <= b <= 45):
                raise ValueError(f"slice out of [1,45] range: ({a},{b})")
            out.append((a, b))
        return out


# ──────────────────────────────────────────────────────────────────────
# Smoke main
# ──────────────────────────────────────────────────────────────────────
def main() -> None:
    """smoke: 11 base 가짜 prob → ranking → 5분할 슬라이스 합의도."""
    rng = np.random.default_rng(_RANDOM_SEED)

    base_models = [
        "xgboost", "catboost", "tabnet",
        "cnn", "gnn", "markov",
        "autoencoder", "tft", "nbeats",
        "mhn", "bayesian_nn",
    ]

    # 일부 모델은 None (미설치 라이브러리 시나리오)
    fake_outputs: dict[str, dict[int, float] | None] = {}
    for name in base_models:
        if name in {"tabnet", "mhn"}:  # 2개 미설치 가정
            fake_outputs[name] = None
            continue
        # 1~45 prob: dirichlet으로 합 1.0 분포 생성
        probs = rng.dirichlet(np.ones(45) * 0.6)
        # 일부 번호에 강한 신호 부여 (모델 간 일부 합의 유도)
        # 모든 모델이 3, 17, 23, 38은 상위에 두도록 가산
        boost_targets = [3, 17, 23, 38]
        for t in boost_targets:
            probs[t - 1] += 0.05
        probs = probs / probs.sum()
        fake_outputs[name] = {n: float(probs[n - 1]) for n in range(1, 46)}

    extractor = ModelRankExtractor()

    print("[ModelRankExtractor] smoke start")
    print(f"  active base models: {sum(1 for v in fake_outputs.values() if v)}/{len(base_models)}")
    print(f"  default slices    : {extractor.default_slices}")

    # 1. extract_rankings
    rankings = extractor.extract_rankings(fake_outputs)
    print(f"\n  [1] extract_rankings: {len(rankings)} models")
    for name in list(rankings.keys())[:3]:
        head = rankings[name][:5]
        print(f"      {name:12s} top5 = {head}")

    # 2. slice_by_ranges
    sliced = extractor.slice_by_ranges(rankings)
    sample_name = next(iter(sliced))
    print(f"\n  [2] slice_by_ranges (sample={sample_name}):")
    for k, v in sliced[sample_name].items():
        print(f"      {k}: {v}")

    # 3. consensus_within_slice (top 1-9)
    cw = extractor.consensus_within_slice(rankings, (1, 9))
    print(f"\n  [3] consensus_within_slice rank 1-9:")
    print(f"      intersection ({len(cw['intersection'])}): {cw['intersection']}")
    print(f"      union        ({len(cw['union'])}): {cw['union']}")
    print(f"      consensus_strength: {cw['consensus_strength']:.3f}")
    print(f"      pairwise_overlap pairs: {len(cw['pairwise_overlap'])}")

    # 4. consensus_across_slices
    ca = extractor.consensus_across_slices(rankings)
    print(f"\n  [4] consensus_across_slices: {len(ca['by_slice'])} slices")
    for key, res in ca["by_slice"].items():
        print(
            f"      {key}: |inter|={len(res['intersection'])} "
            f"|union|={len(res['union'])} strength={res['consensus_strength']:.3f}"
        )
    print(f"\n  summary: avg_strength={ca['summary']['avg_consensus_strength']:.3f}")
    print(f"           max_slice={ca['summary']['max_intersection_slice']}")
    print(f"           min_slice={ca['summary']['min_intersection_slice']}")

    # 검증: 모든 모델 ranking 길이 45
    assert all(len(v) == 45 for v in rankings.values()), "ranking length must be 45"
    # 검증: 부스트 타겟이 top-9 슬라이스 intersection에 포함될 가능성 높음
    assert isinstance(cw["intersection"], list)
    print("\n[ModelRankExtractor] smoke OK")


if __name__ == "__main__":
    main()
