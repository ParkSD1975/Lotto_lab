"""Stage 3-B-2: 전문가 메모 적중률 추적 + 신뢰도 동적 갱신.

메커니즘 3 — 메모의 forced_includes / forced_excludes가 실제 회차에 얼마나
들어맞았는지를 누적 기록하여, 시간이 지남에 따라 메모 신뢰도를 자동 조정한다.

Supabase 테이블 expert_memo_history 가용 시 영속 적재. 미가용 시
프로세스 메모리 dict로 fallback (테스트/오프라인 환경).
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

try:
    from db.supabase_client import get_client as _supabase_get_client
except Exception:  # pragma: no cover - 임포트 실패 환경 대비
    _supabase_get_client = None


HISTORY_TABLE = "expert_memo_history"
DEFAULT_WINDOW = 50


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    z = math.exp(x)
    return z / (1.0 + z)


class ExpertMemoHistoryTracker:
    """메모 적중률 누적 + 신뢰도 산출."""

    def __init__(self, supabase_client: Any | None = None) -> None:
        # 외부에서 client 주입 가능. 미주입 시 lazy 시도, 실패 시 fallback dict.
        self._client = supabase_client
        self._memory: list[dict] = []      # round 오름차순 누적
        self._confidence_by_round: dict[int, float] = {}

    # ------------------------------------------------------------------ utils
    def _ensure_client(self) -> Any | None:
        if self._client is not None:
            return self._client
        if _supabase_get_client is None:
            return None
        try:
            self._client = _supabase_get_client()
        except Exception:
            self._client = None
        return self._client

    @staticmethod
    def _hit_rate(forced_includes: list[int], winning: list[int]) -> float:
        if not forced_includes:
            return 0.0
        hit = len(set(int(n) for n in forced_includes) & set(int(n) for n in winning))
        return float(hit) / float(max(len(forced_includes), 1))

    @staticmethod
    def _exclude_success_rate(forced_excludes: list[int], winning: list[int]) -> float:
        if not forced_excludes:
            return 0.0
        miss = len(set(int(n) for n in forced_excludes) - set(int(n) for n in winning))
        return float(miss) / float(max(len(forced_excludes), 1))

    # ------------------------------------------------------------------ core
    def update(
        self,
        target_round: int,
        memo: dict,
        actual_winning_numbers: list[int],
    ) -> dict:
        """단일 회차 적중률 갱신 + 신뢰도 재계산."""
        forced_includes = list(memo.get("forced_includes") or [])
        forced_excludes = list(memo.get("forced_excludes") or [])

        forced_inc_hit = len(set(forced_includes) & set(actual_winning_numbers))
        forced_exc_hit = len(set(forced_excludes) - set(actual_winning_numbers))
        hit_rate = self._hit_rate(forced_includes, actual_winning_numbers)
        exclude_success = self._exclude_success_rate(forced_excludes, actual_winning_numbers)

        # 누적 (window 50 기준 평균)
        record = {
            "target_round": int(target_round),
            "memo_id": memo.get("memo_id"),
            "forced_inc_hit": int(forced_inc_hit),
            "forced_exc_hit": int(forced_exc_hit),
            "hit_rate": float(hit_rate),
            "exclude_success_rate": float(exclude_success),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._memory.append(record)
        self._memory = sorted(self._memory, key=lambda r: r.get("target_round", 0))

        # 최근 50 평균 + sigmoid 신뢰도
        recent = self._memory[-DEFAULT_WINDOW:]
        mean_hit = (
            sum(r["hit_rate"] for r in recent) / len(recent) if recent else 0.0
        )
        confidence = float(_sigmoid((mean_hit - 0.5) * 5.0))
        record["memo_hit_rate_window"] = float(mean_hit)
        record["memo_domain_confidence"] = confidence

        self._confidence_by_round[int(target_round)] = confidence

        # Supabase 적재 시도 (graceful)
        try:
            self.save_to_supabase(record)
        except Exception:
            pass

        return record

    # ------------------------------------------------------------------ query
    def get_confidence(self, target_round: int) -> float:
        """target_round 기준 누적 신뢰도. 미기록 시 가장 가까운 과거 신뢰도."""
        if int(target_round) in self._confidence_by_round:
            return float(self._confidence_by_round[int(target_round)])

        if not self._confidence_by_round:
            return 0.5  # neutral prior

        past = [r for r in self._confidence_by_round if r <= int(target_round)]
        if past:
            return float(self._confidence_by_round[max(past)])
        # target이 모든 기록보다 이전 → neutral
        return 0.5

    def get_recent_history(self, window: int = DEFAULT_WINDOW) -> list[dict]:
        """최근 window 회차 적중률 기록 (round 오름차순)."""
        if window <= 0:
            return []
        return list(self._memory[-int(window):])

    # ------------------------------------------------------------------ persist
    def save_to_supabase(self, record: dict) -> bool:
        """단일 record 적재. 가용 클라이언트가 없거나 오류면 False."""
        client = self._ensure_client()
        if client is None:
            return False
        try:
            payload = dict(record)
            # supabase는 timestamp 문자열 OK
            client.table(HISTORY_TABLE).insert(payload).execute()
            return True
        except Exception:
            return False

    def load_from_supabase(self, memo_id: str | None = None, limit: int = 200) -> int:
        """Supabase에서 누적 기록 로드 (가용 시). 반환: 로드 행 수."""
        client = self._ensure_client()
        if client is None:
            return 0
        try:
            q = client.table(HISTORY_TABLE).select("*")
            if memo_id is not None:
                q = q.eq("memo_id", memo_id)
            res = q.order("target_round", desc=False).limit(int(limit)).execute()
            data = res.data or []
            self._memory = list(data)
            self._confidence_by_round = {
                int(r["target_round"]): float(r.get("memo_domain_confidence", 0.5))
                for r in data
                if "target_round" in r
            }
            return len(data)
        except Exception:
            return 0


# ----------------------------------------------------------------------- smoke
def main() -> None:
    """ASCII smoke."""
    print("[smoke] ExpertMemoHistoryTracker")

    tracker = ExpertMemoHistoryTracker(supabase_client=None)

    fake_memo = {
        "memo_id": "memo-001",
        "forced_includes": [3, 11, 27],
        "forced_excludes": [42, 45],
    }

    # 회차 1: 27만 적중 (1/3), 제외 둘다 미출현 (2/2)
    rec1 = tracker.update(2120, fake_memo, [27, 5, 8, 19, 22, 33])
    print(f"  round 2120 hit_rate (expect 1/3): {rec1['hit_rate']:.4f}")
    print(f"  round 2120 exclude_success (expect 1.0): {rec1['exclude_success_rate']:.4f}")
    print(f"  round 2120 confidence: {rec1['memo_domain_confidence']:.4f}")

    # 회차 2: 3, 11 적중 (2/3)
    rec2 = tracker.update(2121, fake_memo, [3, 11, 7, 19, 22, 33])
    print(f"  round 2121 hit_rate (expect 2/3): {rec2['hit_rate']:.4f}")
    print(f"  round 2121 confidence (expect > round 1 conf): {rec2['memo_domain_confidence']:.4f}")
    print(f"  conf-rising check: {rec2['memo_domain_confidence'] >= rec1['memo_domain_confidence']}")

    print(f"  get_confidence(2121): {tracker.get_confidence(2121):.4f}")
    print(f"  get_confidence(9999) -> closest past: {tracker.get_confidence(9999):.4f}")
    print(f"  recent history len: {len(tracker.get_recent_history(window=50))}")

    print("[smoke] OK")


if __name__ == "__main__":
    main()
