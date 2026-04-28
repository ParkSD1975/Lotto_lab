"""MissingGroupPredictor — 미출현그룹 광역 4 카테고리 동적 풀 분류기.

Stage 1 / Phase 1. unified-plan #5 결정에 따라 4 카테고리만 운용한다.
동적 N(미출현 회차 N)은 Stage 2 회귀에서 처리.

4 그룹 정의 (각 번호의 마지막 출현 후 경과 회차 = dormancy):
  - group_0: 0-5 회 미출현 (가장 핫)
  - group_1: 6-10 회 미출현
  - group_2: 11-15 회 미출현
  - group_3: 16+ 회 미출현 (가장 콜드)

각 회차에서 4 그룹 풀 크기 M_g 가 변동 (예: t회차 group_2=12, t+1=8).
각 카테고리 출현 카운트 0~6 을 7-class softmax 로 학습한다 (ICP 베이스 활용).

narrative 는 동적 M 을 반영한다: "group_0 pool 8 expected 3 (P=42.1%)".
"""

from __future__ import annotations

import os
import pickle
from typing import Optional

import numpy as np

import config
from predictors.independent_count_predictor import IndependentCountPredictor


# ASCII only print


GROUP_BOUNDARIES = (
    (0, 5),    # group_0
    (6, 10),   # group_1
    (11, 15),  # group_2
    (16, 10**9),  # group_3
)
GROUP_LABELS = ("group_0", "group_1", "group_2", "group_3")
N_GROUPS = 4


def _draw_numbers(d: dict) -> list[int]:
    """draw dict 에서 번호 6개를 안전하게 추출."""
    nums = d.get("numbers")
    if nums is None:
        nums = d.get("nums") or []
    return [int(n) for n in nums if 1 <= int(n) <= 45]


def _augment_class_coverage(
    X: np.ndarray, Y: np.ndarray, n_classes: int = 7
) -> tuple[np.ndarray, np.ndarray]:
    """ICP/XGBoost 학습 안전망 — 각 카테고리에서 누락된 클래스를 더미 샘플로 보충.

    XGBoost 는 num_class 와 실제 라벨 unique 가 일치해야 한다. 누락된 클래스가
    있으면 X 평균 행을 복사하고 라벨만 누락 클래스로 지정한 더미 샘플 1개씩 추가.
    """
    if X.shape[0] == 0:
        return X, Y
    n_cat = Y.shape[1]
    avg_row = X.mean(axis=0, keepdims=True)
    extra_X: list[np.ndarray] = []
    extra_Y: list[np.ndarray] = []
    for ci in range(n_cat):
        present = set(np.unique(Y[:, ci]).tolist())
        missing = [c for c in range(n_classes) if c not in present]
        for cls in missing:
            extra_X.append(avg_row.copy())
            row = Y[0:1].copy()
            row[0, ci] = cls
            extra_Y.append(row)
    if not extra_X:
        return X, Y
    X_aug = np.concatenate([X] + extra_X, axis=0)
    Y_aug = np.concatenate([Y] + extra_Y, axis=0)
    return X_aug, Y_aug


class MissingGroupPredictor:
    """미출현그룹 광역 4 카테고리 동적 풀 predictor.

    AE 는 동적 풀 변동(쏠림) 감지에 강하다. 기본 active_models 에 ae 포함.
    """

    def __init__(
        self,
        feature_dim: int = 16,
        active_models: tuple[str, ...] = (
            "xgboost", "catboost", "tabnet", "markov", "ae", "tft",
        ),
        seq_window: int = 30,
    ):
        self.feature_dim = feature_dim
        self.active_models = active_models
        self.seq_window = seq_window

        # ICP 에는 ae 가 base 로 없다. ae 는 본 predictor 가 별도 학습/주입한다.
        icp_models = tuple(m for m in active_models if m != "ae")
        if not icp_models:
            icp_models = ("xgboost", "markov")

        self.icp = IndependentCountPredictor(
            indicator_name="missing_group_4",
            n_categories=N_GROUPS,
            category_labels=list(GROUP_LABELS),
            n_classes=7,
            feature_dim=feature_dim,
            active_models=icp_models,
            category_pool_sizes=[1] * N_GROUPS,
        )

        # ae 보조 (선택)
        self._ae_trainer = None
        self._is_trained = False

    # ────── dormancy / 그룹 할당 ──────

    def compute_dormancy(self, draws: list[dict]) -> dict[int, int]:
        """각 번호 1~45 의 마지막 출현 이후 경과 회차.

        draws 는 최신순 (index 0 = 가장 최근) 으로 정렬된 리스트.
        한 번도 안 나온 번호는 len(draws) + 1 로 처리.
        """
        last_seen = {n: None for n in range(1, 46)}
        for t, d in enumerate(draws):
            for n in _draw_numbers(d):
                if last_seen[n] is None:
                    last_seen[n] = t

        dormancy: dict[int, int] = {}
        big = len(draws) + 1
        for n in range(1, 46):
            dormancy[n] = last_seen[n] if last_seen[n] is not None else big
        return dormancy

    def assign_groups(self, dormancy: dict[int, int]) -> dict[int, list[int]]:
        """{group_idx: [numbers]} 동적 풀."""
        pools: dict[int, list[int]] = {i: [] for i in range(N_GROUPS)}
        for num, dorm in dormancy.items():
            for gi, (lo, hi) in enumerate(GROUP_BOUNDARIES):
                if lo <= dorm <= hi:
                    pools[gi].append(num)
                    break
        return pools

    # ────── feature ──────

    def build_features(self, draws_so_far: list[dict]) -> np.ndarray:
        """현재 회차 시점의 단일 feature 행 (D,).

        구성 (총 16 요소):
          - 4 그룹 풀 크기
          - 4 그룹 dormancy 평균
          - 4 그룹 dormancy 표준편차
          - 최근 5 / 10 / 15 / 20 회차 평균 미출현 갯수 (전체)
        """
        if not draws_so_far:
            return np.zeros(self.feature_dim, dtype=np.float32)

        dorm = self.compute_dormancy(draws_so_far)
        pools = self.assign_groups(dorm)

        feat: list[float] = []
        for gi in range(N_GROUPS):
            members = pools[gi]
            feat.append(float(len(members)))
        for gi in range(N_GROUPS):
            members = pools[gi]
            feat.append(float(np.mean([dorm[n] for n in members])) if members else 0.0)
        for gi in range(N_GROUPS):
            members = pools[gi]
            feat.append(float(np.std([dorm[n] for n in members])) if members else 0.0)

        for w in (5, 10, 15, 20):
            sub = draws_so_far[:w]
            seen = set()
            for d in sub:
                seen.update(_draw_numbers(d))
            miss = 45 - len(seen)
            feat.append(float(miss))

        arr = np.array(feat, dtype=np.float32)
        if arr.size < self.feature_dim:
            arr = np.pad(arr, (0, self.feature_dim - arr.size))
        elif arr.size > self.feature_dim:
            arr = arr[: self.feature_dim]
        return arr

    # ────── 학습 데이터 시퀀스화 ──────

    def _build_training_set(self, draws: list[dict]) -> tuple[np.ndarray, np.ndarray, list[list[int]]]:
        """과거 시점 t 마다 X = features(t), Y = 다음 회차 4 그룹 출현 카운트.

        draws 는 최신순. 학습은 오래된 회차 → 최신 순으로 정합.
        """
        N = len(draws)
        if N < 5:
            return (
                np.zeros((0, self.feature_dim), dtype=np.float32),
                np.zeros((0, N_GROUPS), dtype=np.int64),
                [],
            )

        X_rows: list[np.ndarray] = []
        Y_rows: list[list[int]] = []
        pool_sizes_rows: list[list[int]] = []

        # t 회차 시점 = draws[t:] (즉 t 회차 이후 과거만 보유). 다음 회차 = draws[t-1].
        # 따라서 t 가 큰 값 → 작은 값으로 진행하며 (t-1) 는 0 까지.
        for t in range(N - 1, 0, -1):
            history = draws[t:]
            if len(history) < 1:
                continue
            x = self.build_features(history)
            dorm = self.compute_dormancy(history)
            pools = self.assign_groups(dorm)

            target_nums = set(_draw_numbers(draws[t - 1]))
            counts = []
            sizes = []
            for gi in range(N_GROUPS):
                members = set(pools[gi])
                cnt = len(members & target_nums)
                if cnt > 6:
                    cnt = 6
                counts.append(cnt)
                sizes.append(len(members))

            X_rows.append(x)
            Y_rows.append(counts)
            pool_sizes_rows.append(sizes)

        X = np.stack(X_rows, axis=0).astype(np.float32) if X_rows else np.zeros((0, self.feature_dim), dtype=np.float32)
        Y = np.array(Y_rows, dtype=np.int64) if Y_rows else np.zeros((0, N_GROUPS), dtype=np.int64)
        return X, Y, pool_sizes_rows

    # ────── 학습 ──────

    def train(self, draws: list[dict]) -> dict:
        """draws (최신순) 로 ICP 학습."""
        X, Y, pool_sizes_rows = self._build_training_set(draws)
        if X.shape[0] < 5:
            print("[MissingGroup] not enough samples for training")
            return {"success": False, "reason": "insufficient_data"}

        # 평균 풀 크기 → ICP 의 초기 pool_size 로 사용 (predict 시 동적 갱신)
        avg_pools = np.mean(np.array(pool_sizes_rows, dtype=np.float32), axis=0).astype(int).tolist()
        for gi, head in enumerate(self.icp.heads):
            head.pool_size = max(1, int(avg_pools[gi]))
        self.icp.category_pool_sizes = [h.pool_size for h in self.icp.heads]

        # 80/20 split (시계열 — 최근 20% 가 학습 데이터 입장에선 마지막)
        cut = max(1, int(X.shape[0] * 0.8))
        X_tr, Y_tr = _augment_class_coverage(X[:cut], Y[:cut], n_classes=7)
        X_val, Y_val = X[cut:], Y[cut:]
        if X_val.shape[0] > 0:
            X_val, Y_val = _augment_class_coverage(X_val, Y_val, n_classes=7)
        history = self.icp.train(X_tr, Y_tr, X_val=X_val if X_val.shape[0] > 0 else None,
                                 Y_val=Y_val if X_val.shape[0] > 0 else None)

        # ae 보조 학습 (선택)
        if "ae" in self.active_models:
            self._train_ae(draws)

        self._is_trained = True
        return {"success": True, "samples": int(X.shape[0]), "icp_history": history}

    def _train_ae(self, draws: list[dict]) -> None:
        """AE 보조 학습 — 그룹 풀 사이즈 변동 패턴 감지용."""
        try:
            from models.autoencoder_model import AutoencoderTrainer
            self._ae_trainer = AutoencoderTrainer()
            self._ae_trainer.train(draws)
        except Exception as e:
            print(f"[MissingGroup] AE train skipped: {e}")
            self._ae_trainer = None

    # ────── 추론 ──────

    def predict(self, draws_so_far: list[dict]) -> dict:
        """현재 회차 시점 4 그룹 분포 (동적 M 반영)."""
        if not draws_so_far:
            return {"per_group": {}, "narrative": "no draws"}

        # 동적 풀 갱신
        dorm = self.compute_dormancy(draws_so_far)
        pools = self.assign_groups(dorm)
        dynamic_sizes = [len(pools[gi]) for gi in range(N_GROUPS)]
        for gi, head in enumerate(self.icp.heads):
            head.pool_size = max(1, dynamic_sizes[gi])
        self.icp.category_pool_sizes = list(dynamic_sizes)

        x = self.build_features(draws_so_far)
        X = np.expand_dims(x, axis=0)
        out = self.icp.predict(X)

        per_group = {}
        for gi, label in enumerate(GROUP_LABELS):
            payload = out.per_category.get(label, {})
            members = pools[gi]
            payload = dict(payload)
            payload["members"] = members
            payload["dynamic_pool_size"] = dynamic_sizes[gi]
            top_class = payload.get("top_class", 0)
            top_prob = payload.get("top_class_prob", 0.0)
            M = dynamic_sizes[gi]
            payload["narrative"] = (
                f"{label} pool {M} expected {top_class} out of {M} "
                f"(P={top_prob * 100:.1f}%)"
            )
            per_group[label] = payload

        return {
            "indicator": "missing_group_4",
            "per_group": per_group,
            "dynamic_pool_sizes": dynamic_sizes,
        }

    # ────── persistence ──────

    def save(self, path: str) -> str:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        icp_path = path + ".icp.pkl"
        self.icp.save(icp_path)
        meta = {
            "feature_dim": self.feature_dim,
            "active_models": list(self.active_models),
            "seq_window": self.seq_window,
            "is_trained": self._is_trained,
            "icp_path": icp_path,
        }
        with open(path, "wb") as f:
            pickle.dump(meta, f)
        return path

    def load(self, path: str) -> None:
        with open(path, "rb") as f:
            meta = pickle.load(f)
        self.feature_dim = meta["feature_dim"]
        self.active_models = tuple(meta["active_models"])
        self.seq_window = meta["seq_window"]
        self._is_trained = meta["is_trained"]
        self.icp.load(meta["icp_path"])


# ────────────────── CLI smoke ──────────────────


def _make_fake_draws(n: int = 100, seed: int = 42) -> list[dict]:
    """가짜 회차 (최신순)."""
    rng = np.random.default_rng(seed)
    draws = []
    for i in range(n):
        nums = sorted(rng.choice(np.arange(1, 46), size=6, replace=False).tolist())
        draws.append({"round": n - i, "numbers": nums})
    return draws


def main():
    """python -m predictors.missing_group_predictor --smoke."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()

    if not args.smoke:
        return

    draws = _make_fake_draws(100, seed=config.RANDOM_SEED)
    pred = MissingGroupPredictor(
        feature_dim=16,
        active_models=("xgboost", "markov"),  # smoke: 의존성 적게
    )

    print("[MissingGroup] training (smoke)...")
    res = pred.train(draws)
    print(f"  result: success={res.get('success')} samples={res.get('samples')}")

    print("\n[MissingGroup] predict (smoke)...")
    out = pred.predict(draws[:50])
    print(f"  dynamic_pool_sizes: {out['dynamic_pool_sizes']}")
    for label, payload in out["per_group"].items():
        print(f"  {label}: M={payload['dynamic_pool_size']} top={payload.get('top_class')} P={payload.get('top_class_prob', 0):.3f}")
        print(f"    narrative: {payload['narrative']}")


if __name__ == "__main__":
    main()
