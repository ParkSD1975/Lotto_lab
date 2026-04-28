"""Stage 3-B-2: 전문가 메모 -> 입력 Feature (Soft Signal 90D).

메커니즘 1 — 사용자 메모를 딥러닝 입력 feature로 변환한다.

shape (90,) 구성:
    forced_excludes_45  (45D): 강제 제외 번호 binary
    forced_includes_45  (45D): 강제 포함 번호 binary
    (총 90D)

추가 시그널 (apply_to_main_model_features 단계):
    memo_hit_rate_recent_50 (10D): 시계열 적중률 trend
    memo_domain_confidence  (1D)
    memo_active_flag        (1D)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

import config

if TYPE_CHECKING:
    from services.expert_memo_history import ExpertMemoHistoryTracker


FEATURE_DIM = 90
EXTRA_SIGNAL_DIM = 12  # 10 trend + 1 confidence + 1 active_flag


class ExpertMemoFeatureExtractor:
    """메모 -> Soft Signal feature 변환기."""

    def __init__(self, history_tracker: "ExpertMemoHistoryTracker | None" = None) -> None:
        self.history_tracker = history_tracker
        self._rng = np.random.default_rng(getattr(config, "RANDOM_SEED", 42))

    # ------------------------------------------------------------------ core
    def extract_features(
        self,
        memo: dict | None,
        recent_50_history: list[dict] | None = None,
    ) -> np.ndarray:
        """메모 -> shape (90,) feature 배열을 반환.

        memo가 None이면 zero vector. memo가 있는 경우 forced_includes /
        forced_excludes 두 binary block (각 45D)을 채운다.
        """
        feat = np.zeros(FEATURE_DIM, dtype=np.float32)
        if not memo:
            return feat

        forced_excludes = memo.get("forced_excludes") or []
        forced_includes = memo.get("forced_includes") or []

        # block 1: forced_excludes_45 [0..45)
        for n in forced_excludes:
            if isinstance(n, (int, np.integer)) and 1 <= int(n) <= 45:
                feat[int(n) - 1] = 1.0

        # block 2: forced_includes_45 [45..90)
        for n in forced_includes:
            if isinstance(n, (int, np.integer)) and 1 <= int(n) <= 45:
                feat[45 + int(n) - 1] = 1.0

        return feat

    # ------------------------------------------------------------------ extra
    def extract_extra_signals(
        self,
        memo: dict | None,
        recent_50_history: list[dict] | None = None,
        target_round: int | None = None,
    ) -> np.ndarray:
        """confidence/trend 등 보조 시그널 (12D)을 반환.

        forced 45+45 block과 함께 main_features에 합류 가능.
        """
        sig = np.zeros(EXTRA_SIGNAL_DIM, dtype=np.float32)
        if not memo:
            return sig

        # active_flag (1D, idx 0)
        sig[0] = 1.0

        # confidence (1D, idx 1)
        confidence = 0.5
        if self.history_tracker is not None:
            try:
                if target_round is not None:
                    confidence = float(self.history_tracker.get_confidence(target_round))
                else:
                    confidence = float(self.history_tracker.get_confidence(0))
            except Exception:
                confidence = 0.5
        sig[1] = float(np.clip(confidence, 0.0, 1.0))

        # trend (10D, idx 2..12) — 최근 50회차를 10 bin 평균
        history = recent_50_history
        if history is None and self.history_tracker is not None:
            try:
                history = self.history_tracker.get_recent_history(window=50)
            except Exception:
                history = None

        if history:
            rates = np.array(
                [float(h.get("hit_rate", 0.0) or 0.0) for h in history],
                dtype=np.float32,
            )
            if rates.size > 0:
                # 50개 -> 10 bin 평균 (모자랄 때는 zero pad)
                padded = np.zeros(50, dtype=np.float32)
                padded[: min(50, rates.size)] = rates[: min(50, rates.size)]
                trend = padded.reshape(10, 5).mean(axis=1)
                sig[2:12] = trend.astype(np.float32)

        return sig

    # ------------------------------------------------------------------ merge
    def apply_to_main_model_features(
        self,
        main_features: np.ndarray,
        memo: dict | None,
        history_tracker: "ExpertMemoHistoryTracker | None" = None,
        recent_50_history: list[dict] | None = None,
        target_round: int | None = None,
    ) -> np.ndarray:
        """메인 모델 입력에 메모 feature(90D)+ extra(12D) = 102D 합류.

        main_features: shape (..., D) — 마지막 축에 102D를 concat한다.
        """
        if history_tracker is not None and self.history_tracker is None:
            self.history_tracker = history_tracker

        memo_feat = self.extract_features(memo, recent_50_history=recent_50_history)
        extra = self.extract_extra_signals(
            memo,
            recent_50_history=recent_50_history,
            target_round=target_round,
        )
        merged_tail = np.concatenate([memo_feat, extra], axis=0).astype(np.float32)

        if main_features.ndim == 1:
            return np.concatenate([main_features.astype(np.float32), merged_tail], axis=0)

        # broadcast tail across batch / sequence dims
        tail_shape = list(main_features.shape[:-1]) + [merged_tail.shape[0]]
        tail = np.broadcast_to(merged_tail, tail_shape).astype(np.float32)
        return np.concatenate([main_features.astype(np.float32), tail], axis=-1)


# ----------------------------------------------------------------------- smoke
def main() -> None:
    """ASCII smoke."""
    print("[smoke] ExpertMemoFeatureExtractor")

    fake_memo = {
        "memo_id": "test-001",
        "target_round": 2122,
        "forced_excludes": [42],
        "forced_includes": [3, 11],
        "forced_filter_constraints": {},
        "memo_text": "smoke memo",
        "priority": 1,
        "created_by": "tester",
    }

    extractor = ExpertMemoFeatureExtractor(history_tracker=None)
    feat = extractor.extract_features(fake_memo)
    print(f"  feature shape: {feat.shape}")
    print(f"  exclude block sum (expect 1): {feat[:45].sum()}")
    print(f"  include block sum (expect 2): {feat[45:].sum()}")
    print(f"  feat[42-1]==1.0 (exclude #42): {feat[42 - 1] == 1.0}")
    print(f"  feat[45+3-1]==1.0 (include #3): {feat[45 + 3 - 1] == 1.0}")
    print(f"  feat[45+11-1]==1.0 (include #11): {feat[45 + 11 - 1] == 1.0}")

    null_feat = extractor.extract_features(None)
    print(f"  null memo all-zero: {bool(np.all(null_feat == 0.0))}")

    extra = extractor.extract_extra_signals(fake_memo)
    print(f"  extra shape: {extra.shape}")
    print(f"  active_flag (expect 1.0): {extra[0]}")

    main_x = np.zeros((4, 30, 65), dtype=np.float32)
    merged = extractor.apply_to_main_model_features(main_x, fake_memo)
    print(f"  merged shape: {merged.shape} (expect (4, 30, 167))")

    print("[smoke] OK")


if __name__ == "__main__":
    main()
