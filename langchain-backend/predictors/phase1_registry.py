"""Phase 1 predictor 통합 registry — 16개 (이월수 변형 포함 17) 인스턴스 관리.

Master Plan Stage 1-2-C. 각 predictor가 동일 인터페이스 (train/predict/save/load)를
가져 일괄 학습·추론 가능하게 한다.

지표 매핑 (Phase 1):
  - 끝수0~9 (10 카테고리) — ICP 직접
  - 번호대 5 — ICP 직접
  - 9궁 9 — ICP 직접
  - 배수 6 (3·4·5·7·8 + 외) — ICP 직접
  - 고저/홀짝/이월수×2/이웃수/연번 — categorical_count_predictor (target_type 분기)
  - 소수/합성수/1/삼각수/제곱수/동형수 — special_number_predictor
  - 미출현그룹 광역 4 — missing_group_predictor (동적 풀)
  - 핫콜드 12 — hotcold_predictor (동적 풀)
  - 로또용지 14 — lotto_paper_predictor (CNN 그리드)

Phase 2/3/4 (endings/ac/sum)는 별도 registry.
"""

from __future__ import annotations

import os
from typing import Optional

import numpy as np

import config
from predictors.independent_count_predictor import IndependentCountPredictor


# ────────────────── 풀 사이즈 헬퍼 ──────────────────


def digit_pool_sizes() -> list[int]:
    """끝수 0~9 풀 사이즈. 0끝(10,20,30,40)=4, 1끝~9끝 분포."""
    pools = [0] * 10
    for n in range(1, 46):
        pools[n % 10] += 1
    return pools  # [4,5,5,5,5,5,5,5,5,4] (확인: 1-9는 1~9 끝 5개씩, 10-45 추가 5개씩, 0끝은 10/20/30/40 4개)


def decade_pool_sizes() -> list[int]:
    """번호대 5: 1-9 / 10-19 / 20-29 / 30-39 / 40-45."""
    return [9, 10, 10, 10, 6]


def gung_pool_sizes() -> list[int]:
    """9궁 9 분할. 1-5 / 6-10 / 11-15 / ... / 41-45."""
    return [5] * 8 + [5]  # 1-5 / 6-10 / 11-15 / 16-20 / 21-25 / 26-30 / 31-35 / 36-40 / 41-45


def multiple_pool_sizes() -> list[int]:
    """배수 6: 3·4·5·7·8 + 외. counted set 중복은 첫 매칭에 귀속."""
    counted = set()
    pools = []
    for k in (3, 4, 5, 7, 8):
        members = {n for n in range(k, 46, k)}
        new = members - counted
        pools.append(len(new))
        counted |= members
    pools.append(len(set(range(1, 46)) - counted))  # 배수 외
    return pools


# ────────────────── ICP 직접 factory ──────────────────


def make_digit_predictor(feature_dim: int = 0, active_models: Optional[tuple] = None) -> IndependentCountPredictor:
    """끝수 0~9 분포 predictor."""
    return IndependentCountPredictor(
        indicator_name="digit_distribution",
        n_categories=10,
        category_labels=[f"digit_{i}" for i in range(10)],
        n_classes=7,
        feature_dim=feature_dim,
        active_models=active_models,
        category_pool_sizes=digit_pool_sizes(),
    )


def make_decade_predictor(feature_dim: int = 0, active_models: Optional[tuple] = None) -> IndependentCountPredictor:
    """번호대 5 분포 predictor."""
    return IndependentCountPredictor(
        indicator_name="decade_distribution",
        n_categories=5,
        category_labels=["1-9", "10-19", "20-29", "30-39", "40-45"],
        n_classes=7,
        feature_dim=feature_dim,
        active_models=active_models,
        category_pool_sizes=decade_pool_sizes(),
    )


def make_gung_predictor(feature_dim: int = 0, active_models: Optional[tuple] = None) -> IndependentCountPredictor:
    """9궁 9 분할 predictor."""
    return IndependentCountPredictor(
        indicator_name="gung_distribution",
        n_categories=9,
        category_labels=[f"gung_{i}" for i in range(9)],
        n_classes=7,
        feature_dim=feature_dim,
        active_models=active_models,
        category_pool_sizes=gung_pool_sizes(),
    )


def make_multiple_predictor(feature_dim: int = 0, active_models: Optional[tuple] = None) -> IndependentCountPredictor:
    """배수 6 (3·4·5·7·8 + 외)."""
    return IndependentCountPredictor(
        indicator_name="multiple_distribution",
        n_categories=6,
        category_labels=["m3", "m4", "m5", "m7", "m8", "other"],
        n_classes=7,
        feature_dim=feature_dim,
        active_models=active_models,
        category_pool_sizes=multiple_pool_sizes(),
    )


# ────────────────── 특수 predictor lazy import ──────────────────


def _try_import_categorical():
    try:
        from predictors.categorical_count_predictor import CategoricalCountPredictor
        return CategoricalCountPredictor
    except ImportError:
        return None


def _try_import_special():
    try:
        from predictors.special_number_predictor import SpecialNumberPredictor
        return SpecialNumberPredictor
    except ImportError:
        return None


def _try_import_missing():
    try:
        from predictors.missing_group_predictor import MissingGroupPredictor
        return MissingGroupPredictor
    except ImportError:
        return None


def _try_import_hotcold():
    try:
        from predictors.hotcold_predictor import HotColdPredictor
        return HotColdPredictor
    except ImportError:
        return None


def _try_import_lotto_paper():
    try:
        from predictors.lotto_paper_predictor import LottoPaperPredictor
        return LottoPaperPredictor
    except ImportError:
        return None


# ────────────────── Registry ──────────────────


class Phase1Registry:
    """Phase 1 predictor 16~17 인스턴스 통합 관리."""

    CATEGORICAL_TYPES = (
        "low_high", "odd_even",
        "carryover_exact", "carryover_with_bonus",  # 이월수 변형 2개
        "neighbor", "consecutive",
    )
    SPECIAL_TYPES = ("prime", "composite", "one", "triangular", "square", "twin")

    def __init__(self, feature_dim: int = 24):
        self.feature_dim = feature_dim
        self.predictors: dict = {}
        self._train_status: dict[str, str] = {}

    def register_default(self) -> None:
        """전체 17 인스턴스 등록 (가용한 클래스만, 미작성된 건 skip)."""
        # ICP 직접 (4)
        self.predictors["digit_distribution"] = make_digit_predictor(self.feature_dim)
        self.predictors["decade_distribution"] = make_decade_predictor(self.feature_dim)
        self.predictors["gung_distribution"] = make_gung_predictor(self.feature_dim)
        self.predictors["multiple_distribution"] = make_multiple_predictor(self.feature_dim)

        # categorical_count_predictor 5 변형 (이월수 2 변형 포함 6)
        Cat = _try_import_categorical()
        if Cat is not None:
            for tt in self.CATEGORICAL_TYPES:
                try:
                    self.predictors[f"categorical_{tt}"] = Cat(target_type=tt, feature_dim=self.feature_dim)
                except Exception as e:
                    print(f"  [Phase1Registry] categorical_{tt} init fail: {e}")
        else:
            print("  [Phase1Registry] categorical_count_predictor not yet available (skip)")

        # special_number_predictor 6
        Sp = _try_import_special()
        if Sp is not None:
            for tt in self.SPECIAL_TYPES:
                try:
                    self.predictors[f"special_{tt}"] = Sp(target_type=tt, feature_dim=self.feature_dim)
                except Exception as e:
                    print(f"  [Phase1Registry] special_{tt} init fail: {e}")
        else:
            print("  [Phase1Registry] special_number_predictor not yet available (skip)")

        # missing_group / hotcold / lotto_paper
        for name, factory in (
            ("missing_group", _try_import_missing),
            ("hotcold", _try_import_hotcold),
            ("lotto_paper", _try_import_lotto_paper),
        ):
            cls = factory()
            if cls is not None:
                try:
                    self.predictors[name] = cls(feature_dim=self.feature_dim)
                except Exception as e:
                    print(f"  [Phase1Registry] {name} init fail: {e}")
            else:
                print(f"  [Phase1Registry] {name}_predictor not yet available (skip)")

    def list_registered(self) -> list[str]:
        return list(self.predictors.keys())

    # ────── 학습 ──────

    def train_all(self, draws: list[dict], min_history: int = 50) -> dict:
        """모든 predictor를 draws로 일괄 학습."""
        results = {}
        for name, p in self.predictors.items():
            try:
                if hasattr(p, "train") and callable(p.train):
                    # ICP 직접 인스턴스는 (X, Y) 인자 — 별도 처리 필요
                    if isinstance(p, IndependentCountPredictor):
                        X, Y = self._build_xy_for_icp(p, draws, min_history)
                        if X is None or len(X) < 10:
                            self._train_status[name] = "skip_insufficient_data"
                            continue
                        history = p.train(X, Y)
                    else:
                        history = p.train(draws)
                    results[name] = history
                    self._train_status[name] = "trained"
            except Exception as e:
                print(f"  [Phase1Registry] {name} train fail: {e}")
                self._train_status[name] = f"fail: {type(e).__name__}"
        return results

    def _build_xy_for_icp(
        self,
        predictor: IndependentCountPredictor,
        draws: list[dict],
        min_history: int = 50,
    ) -> tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """ICP 직접 인스턴스용 X, Y 빌드.

        X: (T - min_history, feature_dim) — features.scalar_features 사용
        Y: (T - min_history, n_categories) — predictor 별 카운트 시계열
        """
        from features.scalar_features import build_scalar_feature_matrix

        if len(draws) < min_history + 1:
            return None, None

        # draws는 최신순 가정 — 시간순 reverse
        chronological = list(reversed(draws))

        # 카운트 시계열 산출
        counts_over_time = []
        for d in chronological:
            counts = self._count_categories_for_draw(predictor.indicator_name, d)
            if counts is not None:
                counts_over_time.append(counts)

        if len(counts_over_time) < min_history + 1:
            return None, None

        Y = np.array(counts_over_time, dtype=np.int64)  # (T, n_categories)

        # 보조 시계열: 총합 (X feature 빌드용 placeholder)
        sum_history = np.array([sum(d["numbers"]) for d in chronological], dtype=np.float64)
        X_full, _ = build_scalar_feature_matrix(sum_history, min_history=min_history)

        # X와 Y 길이 정렬
        Y_aligned = Y[min_history:min_history + len(X_full)]
        X_aligned = X_full[: len(Y_aligned)]

        return X_aligned, Y_aligned

    def _count_categories_for_draw(self, indicator_name: str, draw: dict) -> Optional[list[int]]:
        """draw 6번호로부터 indicator별 카테고리 카운트 산출."""
        nums = draw["numbers"]

        if indicator_name == "digit_distribution":
            counts = [0] * 10
            for n in nums:
                counts[n % 10] += 1
            return counts

        if indicator_name == "decade_distribution":
            counts = [0] * 5
            for n in nums:
                if 1 <= n <= 9:
                    counts[0] += 1
                elif 10 <= n <= 19:
                    counts[1] += 1
                elif 20 <= n <= 29:
                    counts[2] += 1
                elif 30 <= n <= 39:
                    counts[3] += 1
                elif 40 <= n <= 45:
                    counts[4] += 1
            return counts

        if indicator_name == "gung_distribution":
            counts = [0] * 9
            for n in nums:
                idx = (n - 1) // 5
                if 0 <= idx < 9:
                    counts[idx] += 1
            return counts

        if indicator_name == "multiple_distribution":
            counts = [0] * 6
            assigned = set()
            for k_idx, k in enumerate((3, 4, 5, 7, 8)):
                for n in nums:
                    if n in assigned:
                        continue
                    if n % k == 0:
                        counts[k_idx] += 1
                        assigned.add(n)
            counts[5] = len(set(nums) - assigned)
            return counts

        return None

    # ────── 추론 ──────

    def predict_all(self, draws_so_far: list[dict]) -> dict:
        """모든 predictor의 현재 회차 추정 출력."""
        out = {}
        for name, p in self.predictors.items():
            try:
                if isinstance(p, IndependentCountPredictor):
                    X, _ = self._build_xy_for_icp(p, draws_so_far, min_history=20)
                    if X is None:
                        out[name] = {"error": "insufficient_data"}
                        continue
                    pred = p.predict(X)
                    out[name] = {
                        "indicator": pred.indicator_name,
                        "per_category": pred.per_category,
                    }
                else:
                    out[name] = p.predict(draws_so_far)
            except Exception as e:
                out[name] = {"error": f"{type(e).__name__}: {e}"}
        return out

    # ────── persistence ──────

    def save_all(self, save_dir: Optional[str] = None) -> dict:
        save_dir = save_dir or os.path.join(config.MODEL_DIR, "phase1")
        os.makedirs(save_dir, exist_ok=True)
        paths = {}
        for name, p in self.predictors.items():
            if hasattr(p, "save"):
                try:
                    path = os.path.join(save_dir, f"{name}.pkl")
                    p.save(path)
                    paths[name] = path
                except Exception as e:
                    print(f"  [Phase1Registry] {name} save fail: {e}")
        return paths

    def load_all(self, save_dir: Optional[str] = None) -> dict:
        save_dir = save_dir or os.path.join(config.MODEL_DIR, "phase1")
        loaded = {}
        for name, p in self.predictors.items():
            path = os.path.join(save_dir, f"{name}.pkl")
            if os.path.exists(path) and hasattr(p, "load"):
                try:
                    p.load(path)
                    loaded[name] = path
                except Exception as e:
                    print(f"  [Phase1Registry] {name} load fail: {e}")
        return loaded

    def status_report(self) -> dict:
        return {
            "registered": self.list_registered(),
            "train_status": dict(self._train_status),
            "feature_dim": self.feature_dim,
        }


# ────────────────── CLI smoke ──────────────────


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()

    if args.smoke:
        rng = np.random.default_rng(config.RANDOM_SEED)
        # 가짜 100 회차 draws (최신순)
        draws = []
        for r in range(100, 0, -1):
            nums = sorted(rng.choice(45, size=6, replace=False) + 1)
            bonus = int(rng.integers(1, 46))
            while bonus in nums:
                bonus = int(rng.integers(1, 46))
            draws.append({"round": r, "numbers": list(nums), "bonus": bonus})

        registry = Phase1Registry(feature_dim=24)
        registry.register_default()

        print(f"\n[Phase1Registry] registered: {len(registry.list_registered())}")
        for name in registry.list_registered():
            print(f"  - {name}")

        print("\n[Phase1Registry] training (smoke)...")
        registry.train_all(draws, min_history=30)
        print("\n[Phase1Registry] train status:")
        for name, status in registry._train_status.items():
            print(f"  {name:35s} = {status}")


if __name__ == "__main__":
    main()
