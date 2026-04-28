"""Tier 4 — 회귀 메타 분석.

회귀-plan Tier 4 구현. N 별 자주 보이는 패턴 빈도 측정 + (선택) MHN retrieval.

빈도 측정 패턴:
  - "N회귀 후 sum 변화 패턴"
  - "N회귀 후 끝수 분포 변화 패턴"
  - "N회귀 후 번호대 군집 발생률"
  - "N회귀 후 라인 변화 패턴"

frequency >= REGRESSION_META_FREQUENCY_MIN, support >= REGRESSION_META_SUPPORT_MIN
인 패턴만 보존.

MHN 미설치 시 retrieve_similar_rounds 는 graceful skip.
출력 cache: saved_models/regression_meta_patterns.json
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from typing import Any

import numpy as np

import config


# ────────────────── config 상수 ──────────────────


REGRESSION_META_FREQUENCY_MIN = getattr(config, "REGRESSION_META_FREQUENCY_MIN", 0.20)
REGRESSION_META_SUPPORT_MIN = getattr(config, "REGRESSION_META_SUPPORT_MIN", 10)


# ────────────────── MHN graceful import ──────────────────


try:
    from models.mhn_model import LottoMHN, TORCH_AVAILABLE as _MHN_TORCH_OK

    MHN_AVAILABLE = bool(_MHN_TORCH_OK)
except ImportError:
    MHN_AVAILABLE = False
    LottoMHN = None  # type: ignore


# ────────────────── 공용 유틸 ──────────────────


def _draw_seven(draw: dict) -> list[int]:
    nums = list(draw.get("numbers", []))
    bonus = draw.get("bonus")
    if bonus is not None:
        nums = nums + [int(bonus)]
    return sorted(int(x) for x in nums)


def _decade_index(n: int) -> int:
    if n <= 9:
        return 0
    if n <= 19:
        return 1
    if n <= 29:
        return 2
    if n <= 39:
        return 3
    return 4


def _sum_change_bucket(delta: float) -> str:
    """sum 변화량 버킷 분류."""
    if delta < -20:
        return "sum_drop_big"
    if delta < -5:
        return "sum_drop_small"
    if delta <= 5:
        return "sum_flat"
    if delta <= 20:
        return "sum_rise_small"
    return "sum_rise_big"


def _ending_dominant(seven: list[int]) -> str:
    """7개 번호의 끝수 분포에서 우세 끝수 (>=2개)."""
    cnt: dict[int, int] = defaultdict(int)
    for n in seven:
        cnt[n % 10] += 1
    items = sorted(cnt.items(), key=lambda x: (-x[1], x[0]))
    if items and items[0][1] >= 2:
        return f"ending_dominant_{items[0][0]}"
    return "ending_no_dominant"


def _decade_cluster_label(seven: list[int], threshold: int = 3) -> str:
    """동일 번호대 >= threshold 군집이 있으면 라벨, 없으면 NA."""
    cnt = [0] * 5
    for n in seven:
        cnt[_decade_index(n)] += 1
    for d in range(5):
        if cnt[d] >= threshold:
            return f"decade_{d}_cluster_{cnt[d]}"
    return "decade_no_cluster"


def _line_shift_label(prev_seven: list[int], curr_seven: list[int]) -> str:
    """라인별 평균 차이 부호 패턴."""
    if len(prev_seven) < 7 or len(curr_seven) < 7:
        return "line_shift_na"
    diffs = [curr_seven[k] - prev_seven[k] for k in range(7)]
    pos = sum(1 for d in diffs if d > 0)
    neg = sum(1 for d in diffs if d < 0)
    if pos >= 5:
        return "line_shift_up"
    if neg >= 5:
        return "line_shift_down"
    return "line_shift_mixed"


# ────────────────── 분석 클래스 ──────────────────


class RegressionMetaAnalyzer:
    """회귀 N 별 자주 보이는 패턴 자동 발견.

    walk-forward 방식으로 학습 데이터 t -> t+N 페어 통계 측정.
    """

    def __init__(
        self,
        frequency_min: float = REGRESSION_META_FREQUENCY_MIN,
        support_min: int = REGRESSION_META_SUPPORT_MIN,
        n_range: tuple[int, int] = (2, 30),
        random_seed: int | None = None,
    ) -> None:
        self.frequency_min = float(frequency_min)
        self.support_min = int(support_min)
        self.n_range = (int(n_range[0]), int(n_range[1]))
        self.random_seed = (
            random_seed if random_seed is not None else config.RANDOM_SEED
        )

        # 결과 보존
        self.frequent_patterns_by_N: dict[str, list[dict[str, Any]]] = {}
        self.similar_past_rounds: list[dict[str, Any]] = []

        # MHN backend (가용 시)
        self._mhn: Any = None
        self._mhn_round_index: list[int] = []

    # ---------- 패턴 분석 ----------

    def analyze_patterns(self, draws: list[dict]) -> dict[str, Any]:
        """학습 데이터 walk-forward 패턴 빈도 측정."""
        if not draws:
            self.frequent_patterns_by_N = {}
            return self._compose_output()

        by_round: dict[int, dict] = {}
        for d in draws:
            r = d.get("round")
            if r is None:
                continue
            by_round[int(r)] = d
        rounds_sorted = sorted(by_round.keys())

        self.frequent_patterns_by_N = {}
        n_lo, n_hi = self.n_range

        for N in range(n_lo, n_hi + 1):
            counter: dict[str, int] = defaultdict(int)
            total = 0
            for t_round in rounds_sorted:
                t_plus = t_round + N
                if t_plus not in by_round:
                    continue
                t_seven = _draw_seven(by_round[t_round])
                tp_seven = _draw_seven(by_round[t_plus])
                if len(t_seven) < 7 or len(tp_seven) < 7:
                    continue

                # patterns
                d_sum = sum(tp_seven) - sum(t_seven)
                counter[_sum_change_bucket(d_sum)] += 1
                counter[_ending_dominant(tp_seven)] += 1
                counter[_decade_cluster_label(tp_seven, threshold=3)] += 1
                counter[_line_shift_label(t_seven, tp_seven)] += 1
                total += 1

            if total < self.support_min:
                continue

            kept: list[dict[str, Any]] = []
            for pat, cnt in counter.items():
                freq = cnt / max(total, 1)
                if freq >= self.frequency_min and cnt >= self.support_min:
                    kept.append(
                        {
                            "pattern": pat,
                            "frequency": float(freq),
                            "support": int(cnt),
                            "total_pairs": int(total),
                        }
                    )
            kept.sort(key=lambda x: -x["frequency"])
            if kept:
                self.frequent_patterns_by_N[f"N={N}"] = kept

        return self._compose_output()

    # ---------- MHN retrieval ----------

    def fit_mhn(
        self,
        feature_matrix: np.ndarray,
        round_index: list[int],
        num_heads: int = 4,
        beta: float = 1.0,
    ) -> bool:
        """MHN 패턴 메모리 저장 (retrieve_similar_rounds 준비).

        feature_matrix: (M, D)  학습 회차 feature
        round_index:    (M,)    round 번호 매핑
        returns: 성공 여부 (MHN 미설치 시 False)
        """
        if not MHN_AVAILABLE or LottoMHN is None:
            self._mhn = None
            self._mhn_round_index = []
            return False
        arr = np.asarray(feature_matrix, dtype=np.float32)
        if arr.ndim != 2 or arr.shape[0] != len(round_index):
            raise ValueError(
                f"feature_matrix shape {arr.shape} mismatch round_index "
                f"len {len(round_index)}"
            )
        try:
            self._mhn = LottoMHN(
                input_dim=int(arr.shape[1]),
                num_heads=num_heads,
                beta=beta,
                task_type="none",
                random_seed=self.random_seed,
            )
            self._mhn.store_patterns(arr)
            self._mhn_round_index = [int(r) for r in round_index]
            return True
        except Exception as exc:
            print(f"[regression_meta_analyzer] MHN fit failed: {exc}")
            self._mhn = None
            self._mhn_round_index = []
            return False

    def retrieve_similar_rounds(
        self, query_features: np.ndarray, top_k: int = 5
    ) -> dict[str, Any]:
        """현재 회차 feature 와 가장 유사한 과거 회차 top_k 검색.

        MHN 미설치/미학습 시 빈 결과 graceful 반환.
        """
        if self._mhn is None or not self._mhn_round_index:
            return {
                "available": False,
                "top_k_rounds": [],
                "similarities": [],
                "retrieved_patterns": [],
            }
        q = np.asarray(query_features, dtype=np.float32)
        if q.ndim == 1:
            q = q.reshape(1, -1)
        try:
            res = self._mhn.retrieve(q, top_k=top_k)
        except Exception as exc:
            print(f"[regression_meta_analyzer] MHN retrieve failed: {exc}")
            return {
                "available": False,
                "top_k_rounds": [],
                "similarities": [],
                "retrieved_patterns": [],
            }
        idx = res["top_k_indices"][0].tolist()
        sims = res["similarities"][0].tolist()
        rounds = [
            self._mhn_round_index[i]
            for i in idx
            if 0 <= i < len(self._mhn_round_index)
        ]
        retrieved = [
            {
                "round": rounds[k] if k < len(rounds) else None,
                "similarity": float(sims[k]),
                "key_pattern": "mhn_retrieval",
            }
            for k in range(len(rounds))
        ]
        self.similar_past_rounds = retrieved
        return {
            "available": True,
            "top_k_rounds": rounds,
            "similarities": [float(s) for s in sims],
            "retrieved_patterns": retrieved,
        }

    # ---------- 출력 합성 ----------

    def _compose_output(self) -> dict[str, Any]:
        return {
            "frequent_patterns_by_N": self.frequent_patterns_by_N,
            "similar_past_rounds": self.similar_past_rounds,
            "config": {
                "frequency_min": self.frequency_min,
                "support_min": self.support_min,
                "n_range": list(self.n_range),
            },
        }

    # ---------- 직렬화 ----------

    def save_to_json(self, path: str | None = None) -> str:
        """결과를 JSON 직렬화. path 미지정 시 saved_models/regression_meta_patterns.json."""
        if path is None:
            path = os.path.join(
                getattr(config, "MODEL_DIR", "saved_models"),
                "regression_meta_patterns.json",
            )
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        payload = self._compose_output()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return path

    def load_from_json(self, path: str | None = None) -> dict[str, Any]:
        if path is None:
            path = os.path.join(
                getattr(config, "MODEL_DIR", "saved_models"),
                "regression_meta_patterns.json",
            )
        if not os.path.exists(path):
            raise FileNotFoundError(f"meta pattern file not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.frequent_patterns_by_N = data.get("frequent_patterns_by_N", {})
        self.similar_past_rounds = data.get("similar_past_rounds", [])
        cfg = data.get("config", {})
        self.frequency_min = float(cfg.get("frequency_min", self.frequency_min))
        self.support_min = int(cfg.get("support_min", self.support_min))
        nr = cfg.get("n_range")
        if isinstance(nr, list) and len(nr) == 2:
            self.n_range = (int(nr[0]), int(nr[1]))
        return data


# ────────────────── smoke ──────────────────


def _make_fake_draws(n_rounds: int = 200, seed: int | None = None) -> list[dict]:
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
    print("[regression_meta_analyzer] smoke start")
    print(f"[regression_meta_analyzer] MHN available: {MHN_AVAILABLE}")
    draws = _make_fake_draws(200)

    # 약한 임계 (random data 상에서 패턴이 우연히 frequency_min 넘기 어려움)
    analyzer = RegressionMetaAnalyzer(
        frequency_min=0.15,
        support_min=10,
        n_range=(2, 12),
    )
    out = analyzer.analyze_patterns(draws)
    n_buckets = len(out["frequent_patterns_by_N"])
    print(
        f"[meta] N buckets with surviving patterns={n_buckets} "
        f"(out of {analyzer.n_range[1] - analyzer.n_range[0] + 1})"
    )
    if n_buckets:
        first_key = next(iter(out["frequent_patterns_by_N"].keys()))
        print(
            f"[meta] sample {first_key}: "
            f"{out['frequent_patterns_by_N'][first_key][:3]}"
        )

    # MHN retrieval (가용 시 가짜 feature 학습)
    rng = np.random.default_rng(config.RANDOM_SEED)
    fake_feat = rng.standard_normal((150, 21)).astype(np.float32)
    fake_rounds = list(range(1, 151))
    fit_ok = analyzer.fit_mhn(fake_feat, fake_rounds, num_heads=2)
    print(f"[mhn] fit_ok={fit_ok}")
    query = rng.standard_normal((1, 21)).astype(np.float32)
    sim = analyzer.retrieve_similar_rounds(query, top_k=5)
    print(
        f"[mhn] retrieve available={sim['available']} top_k_rounds={sim['top_k_rounds']}"
    )

    # save / load round-trip
    tmp_path = os.path.join(
        getattr(config, "MODEL_DIR", "saved_models"),
        "_smoke_regression_meta.json",
    )
    saved = analyzer.save_to_json(tmp_path)
    print(f"[io] saved={saved}, exists={os.path.exists(saved)}")
    a2 = RegressionMetaAnalyzer()
    a2.load_from_json(saved)
    print(
        f"[io] reloaded N buckets={len(a2.frequent_patterns_by_N)}"
    )
    try:
        os.remove(saved)
    except OSError:
        pass

    print("[regression_meta_analyzer] smoke OK")
    return 0


def main() -> int:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--smoke", action="store_true")
    args = p.parse_args()
    if args.smoke:
        return _smoke()
    print("[regression_meta_analyzer] use --smoke to run smoke test")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
