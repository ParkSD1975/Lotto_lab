"""Stage 3-C — NumberRecommender + Hard Filter 3계층.

단일 진실 공급원: docs/MASTER_PLAN.md (Stage 3, Hard Filter 3계층)

Hard Filter 3계층 우선순위 (사용자 결정 #21):
    1순위 (최우선): 사용자 전문가 메모 (forced_excludes / forced_includes)
    2순위: 자동 룰 1·2·3 (회귀 4연번 / 1회귀 4연번 / 데드 회귀x라인)
    3순위: 4 Pillar 점수 다중 조건

추천 5 + 제외 10 결정:
    select_recommendations(): 메모 forced_includes -> top15 후보 -> consensus.top10>=4
                              -> filter_compliance>=median+0.1 -> CI lower 정렬 -> top n_top
    select_exclusions():      메모 forced_excludes -> 자동 룰 force_exclude
                              -> 4 Pillar 다중 조건 통과 후보 -> top n_exc

XAI evidence (Stage 4 narrative 입력):
    build_xai_evidence(): 각 번호별 4 Pillar 분해 + 활성 시그널 + 자동 룰 트리거
"""
from __future__ import annotations

import os
from typing import Any

import numpy as np

try:
    import config  # type: ignore
    _RANDOM_SEED = int(getattr(config, "RANDOM_SEED", 42))
    _REC_TOP10_THR = int(getattr(config, "RECOMMEND_CONSENSUS_TOP10_THRESHOLD", 4))
    _EXC_BOT15_THR = int(getattr(config, "EXCLUDE_CONSENSUS_BOTTOM15_THRESHOLD", 4))
except Exception:
    _RANDOM_SEED = 42
    _REC_TOP10_THR = 4
    _EXC_BOT15_THR = 4

try:
    from models.number_scorer import NumberScorer  # type: ignore
except Exception:
    try:
        from number_scorer import NumberScorer  # type: ignore
    except Exception:
        NumberScorer = None  # type: ignore

try:
    from models.consensus_analyzer import ConsensusAnalyzer  # type: ignore
except Exception:
    try:
        from consensus_analyzer import ConsensusAnalyzer  # type: ignore
    except Exception:
        ConsensusAnalyzer = None  # type: ignore

try:
    from db.supabase_client import get_client as _get_supabase  # type: ignore
except Exception:
    _get_supabase = None  # type: ignore


# ──────────────────────────────────────────────────────────────────────
# 유틸
# ──────────────────────────────────────────────────────────────────────
def _safe_int_set(seq: Any) -> set[int]:
    """1~45 범위 정수만 추출한 set."""
    out: set[int] = set()
    if not isinstance(seq, (list, tuple, set, frozenset)):
        return out
    for v in seq:
        try:
            iv = int(v)
        except Exception:
            continue
        if 1 <= iv <= 45:
            out.add(iv)
    return out


def _coerce_filter_compliance(arr_or_dict: Any) -> np.ndarray:
    """filter_compliance를 (45,) np.ndarray로 정규화."""
    out = np.full(45, 0.5, dtype=np.float64)
    if arr_or_dict is None:
        return out
    if isinstance(arr_or_dict, np.ndarray):
        a = np.asarray(arr_or_dict, dtype=np.float64).ravel()
        if a.size == 45:
            return a
        return out
    if isinstance(arr_or_dict, dict):
        for n in range(1, 46):
            v = arr_or_dict.get(n, arr_or_dict.get(str(n), 0.5))
            try:
                f = float(v)
                if np.isfinite(f):
                    out[n - 1] = f
            except Exception:
                pass
        return out
    if isinstance(arr_or_dict, (list, tuple)) and len(arr_or_dict) == 45:
        try:
            return np.asarray(arr_or_dict, dtype=np.float64).ravel()
        except Exception:
            return out
    return out


def _ci_lower_estimate(score: float, sigma: float | None) -> float:
    """Bayesian sigma 가용 시 score - 1.96*sigma (95% CI lower), 없으면 score."""
    if sigma is None:
        return float(score)
    try:
        s = float(sigma)
        if not np.isfinite(s):
            return float(score)
        return float(score) - 1.96 * s
    except Exception:
        return float(score)


# ──────────────────────────────────────────────────────────────────────
# [P1 PATCH] 빈도 페널티 — favorite bias 해소
# 근거: Lotto_lab_Root_Cause_Diagnosis.md (Finding #2)
#       50회차 분석에서 18=60%, 14=50%, 43=50% 추천 → 자연 출현률 14% 대비 과대
# 패치 일자: 2026-05-11
# ──────────────────────────────────────────────────────────────────────
def _compute_frequency_penalty(
    n: int,
    draws_so_far: list[dict] | None,
    recent_window: int = 3,
    recent_penalty: float = 0.7,
    historical_threshold_high: float = 0.18,
    historical_penalty_high: float = 0.85,
    historical_threshold_mid: float = 0.16,
    historical_penalty_mid: float = 0.92,
    min_rounds_for_hist: int = 50,
) -> float:
    """빈도 페널티 곱셈 계수 반환 (1.0=무페널티, < 1.0=감점).

    Args:
        n: 평가할 번호 (1~45)
        draws_so_far: 회차 history (dict or list of int)
        recent_window: 최근 N회 회피 윈도우
        recent_penalty: 최근 N회 출현 시 곱셈 계수
        historical_threshold_high/mid: 자연 빈도 대비 high/mid 임계
        historical_penalty_high/mid: high/mid 페널티
        min_rounds_for_hist: historical 페널티 적용 최소 회차

    Returns:
        곱셈 계수 (예: 0.7 × 0.85 = 0.595)
    """
    if not draws_so_far:
        return 1.0

    coef = 1.0

    # 1) 직전 N회 출현 페널티
    recent_numbers: set[int] = set()
    for draw in draws_so_far[-recent_window:]:
        nums = draw.get("numbers") if isinstance(draw, dict) else draw
        if isinstance(nums, (list, tuple, set)):
            for x in nums:
                try:
                    recent_numbers.add(int(x))
                except (ValueError, TypeError):
                    continue
    if n in recent_numbers:
        coef *= recent_penalty

    # 2) Historical 빈도 페널티
    total_rounds = len(draws_so_far)
    if total_rounds >= min_rounds_for_hist:
        appear_count = 0
        for draw in draws_so_far:
            nums = draw.get("numbers") if isinstance(draw, dict) else draw
            if isinstance(nums, (list, tuple, set)):
                for x in nums:
                    try:
                        if int(x) == n:
                            appear_count += 1
                            break
                    except (ValueError, TypeError):
                        continue
        hist_freq = appear_count / total_rounds

        if hist_freq > historical_threshold_high:
            coef *= historical_penalty_high
        elif hist_freq > historical_threshold_mid:
            coef *= historical_penalty_mid

    return coef


# ──────────────────────────────────────────────────────────────────────
# Stage 6-D — Diversity injection (Plackett-Luce sampling)
# ──────────────────────────────────────────────────────────────────────
def _round_seeded_rng(target_round: int | None, salt: str = "rec") -> np.random.Generator:
    """target_round + salt 기반 결정론적 RNG.

    Stage 6-F-3 fix: Python의 hash()는 PYTHONHASHSEED 기본 random이라
    프로세스마다 다른 seed 발생 → hashlib.md5로 fully deterministic seeding.

    같은 (round, salt)는 어느 프로세스든 같은 seed → 재현 가능.
    다른 round는 다른 seed → 회차별 다양성.
    target_round가 None이면 fixed seed (기존 동작 유지).
    """
    if target_round is None:
        return np.random.default_rng(_RANDOM_SEED)
    import hashlib
    seed_str = f"{salt}:{int(target_round)}:{_RANDOM_SEED}"
    h = hashlib.md5(seed_str.encode("utf-8")).digest()
    seed = int.from_bytes(h[:4], "big")
    return np.random.default_rng(seed)


def _plackett_luce_diverse_pick(
    scored_items: list[tuple[int, float]],
    n_pick: int,
    target_round: int | None = None,
    temperature: float = 0.04,
    salt: str = "rec",
    adjacency: np.ndarray | list | None = None,
    gnn_penalty_strength: float = 0.5,
) -> list[int]:
    """Plackett-Luce 샘플링 + (옵션) GNN co-occurrence pairwise diversity penalty.

    스코어 차이가 작으면 (mode collapse) softmax 분포가 평탄해져 다양 선택 유도.
    adjacency 주입 시 각 pick마다 이미 뽑힌 번호와의 동반출현 빈도가 높은 후보에 페널티 →
    조합 다양성 강화 (Stage 6-F-3).

    Args:
        scored_items         : [(number, score), ...] — 점수 내림차순 정렬 가정 (큰 게 좋음)
        n_pick               : 뽑을 개수
        target_round         : 회차별 시드 (None이면 fixed)
        temperature          : softmax 온도. 작을수록 greedy. 0.06 권장.
        salt                 : RNG salt ("rec" / "exc")
        adjacency            : 45×45 GNN co-occurrence 매트릭스 (선택). None이면 기존 PL.
        gnn_penalty_strength : 페널티 강도. 0.0=GNN 무시, 1.0=score range 만큼 차감.

    Returns:
        선택된 number 리스트 (n_pick개, 중복 없음)
    """
    if not scored_items or n_pick <= 0:
        return []

    items = list(scored_items)
    rng = _round_seeded_rng(target_round, salt=salt)
    picked: list[int] = []

    T = max(float(temperature), 1e-6)

    # adjacency normalize (max-norm to [0, 1])
    adj_norm = None
    if adjacency is not None:
        try:
            adj_arr = np.asarray(adjacency, dtype=np.float64)
            if adj_arr.shape == (45, 45):
                amax = float(adj_arr.max())
                if amax > 1e-9:
                    adj_norm = adj_arr / amax
        except Exception:
            adj_norm = None

    while items and len(picked) < n_pick:
        nums = np.array([n for n, _ in items], dtype=np.int64)
        scores = np.array([s for _, s in items], dtype=np.float64)

        # GNN pairwise penalty (Stage 6-F-3)
        if adj_norm is not None and picked:
            penalty = np.zeros(len(items), dtype=np.float64)
            for n_picked in picked:
                idx_picked = n_picked - 1
                for i, n_cand in enumerate(nums):
                    penalty[i] += adj_norm[idx_picked, n_cand - 1]
            penalty /= max(len(picked), 1)
            score_range = float(scores.max() - scores.min()) or 1e-6
            scores = scores - gnn_penalty_strength * score_range * penalty

        # softmax with temperature
        z = (scores - scores.max()) / T
        p = np.exp(z)
        p_sum = p.sum()
        if not np.isfinite(p_sum) or p_sum <= 0:
            p = np.ones_like(p) / len(p)
        else:
            p = p / p_sum

        idx = int(rng.choice(len(items), p=p))
        picked.append(int(nums[idx]))
        items.pop(idx)

    return picked


def _plackett_luce_diverse_pick_asc(
    scored_items: list[tuple[int, float]],
    n_pick: int,
    target_round: int | None = None,
    temperature: float = 0.04,
    salt: str = "exc",
    adjacency: np.ndarray | list | None = None,
    gnn_penalty_strength: float = 0.0,
) -> list[int]:
    """제외용: 점수 작은 게 좋음. 부호 반전 후 _plackett_luce_diverse_pick 호출.

    제외 측면에서는 GNN diversity가 역효과 (10개 제외가 비슷해야 좋음 — 약한 번호 그룹).
    기본 gnn_penalty_strength=0.0으로 GNN penalty 비활성화.
    """
    flipped = [(n, -s) for n, s in scored_items]
    return _plackett_luce_diverse_pick(
        flipped, n_pick, target_round, temperature, salt,
        adjacency=adjacency, gnn_penalty_strength=gnn_penalty_strength,
    )


# ──────────────────────────────────────────────────────────────────────
# MemoLoader (Supabase 자동 조회)
# ──────────────────────────────────────────────────────────────────────
class MemoLoader:
    """Supabase expert_memos 테이블에서 target_round용 메모 자동 조회."""

    def __init__(self, supabase_client: Any | None = None):
        self._client = supabase_client

    def _ensure_client(self) -> Any | None:
        if self._client is not None:
            return self._client
        if _get_supabase is None:
            return None
        try:
            self._client = _get_supabase()
        except Exception:
            self._client = None
        return self._client

    def load_memos_for_round(self, target_round: int) -> dict | None:
        """target_round용 메모 조회 (최신 1개).

        Returns:
            dict with forced_includes/forced_excludes/confidence or None
        """
        client = self._ensure_client()
        if client is None:
            return None
        try:
            res = (
                client.table("expert_memos")
                .select("*")
                .eq("target_round", int(target_round))
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if res.data:
                row = res.data[0]
                return {
                    "memo_id": row.get("id"),
                    "forced_includes": row.get("forced_includes") or [],
                    "forced_excludes": row.get("forced_excludes") or [],
                    "confidence": float(row.get("confidence") or 0.5),
                    "memo_text": row.get("memo_text"),
                    "domain_tags": row.get("domain_tags") or [],
                }
        except Exception as e:
            print(f"[MemoLoader] Supabase query fail: {e}")
        return None


# ──────────────────────────────────────────────────────────────────────
# NumberRecommender
# ──────────────────────────────────────────────────────────────────────
class NumberRecommender:
    """Hard Filter 3계층 + 추천 5 + 제외 10 결정."""

    def __init__(
        self,
        scorer: "NumberScorer | None" = None,
        consensus_analyzer: "ConsensusAnalyzer | None" = None,
        memo_loader: "MemoLoader | None" = None,
    ):
        """외부 주입 받거나 lazy 초기화.

        Args:
            scorer            : NumberScorer (4 Pillar Ridge 통합)
            consensus_analyzer: ConsensusAnalyzer (Pillar 4)
            memo_loader       : MemoLoader (Supabase 메모 자동 조회)
        """
        self._seed: int = _RANDOM_SEED
        self.scorer = scorer
        self.consensus_analyzer = consensus_analyzer
        self.memo_loader = memo_loader or MemoLoader()

        if self.scorer is None and NumberScorer is not None:
            try:
                self.scorer = NumberScorer()
            except Exception as e:
                print(f"[NumberRecommender] NumberScorer init skip: {e}")
                self.scorer = None

        if self.consensus_analyzer is None and ConsensusAnalyzer is not None:
            try:
                self.consensus_analyzer = ConsensusAnalyzer()
            except Exception as e:
                print(f"[NumberRecommender] ConsensusAnalyzer init skip: {e}")
                self.consensus_analyzer = None

        # Stage 6-F-3: GNN adjacency lazy load (45×45 co-occurrence)
        self._gnn_adjacency: np.ndarray | None = None

    def _load_gnn_adjacency(self) -> np.ndarray | None:
        """saved_models/gnn_adjacency.json 1회 로드 (캐시)."""
        if self._gnn_adjacency is not None:
            return self._gnn_adjacency
        try:
            import json
            path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "saved_models", "gnn_adjacency.json",
            )
            if not os.path.exists(path):
                return None
            with open(path, "r", encoding="utf-8") as f:
                arr = json.load(f)
            adj = np.asarray(arr, dtype=np.float64)
            if adj.shape == (45, 45):
                self._gnn_adjacency = adj
                return adj
        except Exception as e:
            print(f"[NumberRecommender] gnn_adjacency load skip: {e}")
        return None

    # ------------------------------------------------------------------
    # 추천 5 결정
    # ------------------------------------------------------------------
    def select_recommendations(
        self,
        scores: dict[int, float],
        consensus_metrics: dict[int, dict],
        filter_compliance: np.ndarray,
        expert_memo: dict | None = None,
        n_top: int = 5,
        bayesian_sigma: dict[int, float] | None = None,
        target_round: int | None = None,
        diversity_temperature: float = 0.06,
        gnn_diversity_strength: float = 0.5,
        draws_so_far: list[dict] | None = None,  # [P1 PATCH]
    ) -> list[dict]:
        """추천 5 선출 (Hard Filter 3계층 + [P1] 빈도 페널티 + [6-D] Plackett-Luce).

        흐름:
        1. 사용자 메모 forced_includes 우선 (최대 n_top까지 강제 포함)
        2. [P1 PATCH] 빈도 페널티 적용 (favorite bias 해소, memo_forced 면제)
        3. final_score 정렬 -> 상위 15 후보
        4. consensus_metrics.top10_count >= REC_TOP10_THR 통과
        5. filter_compliance >= median + 0.1 통과
        6. (Stage 6-D) Plackett-Luce diversity 샘플링 -> top n_top
            - 회차 시드(target_round) 기반 결정론적 RNG
            - softmax(score / T) 분포에서 비복원 추출
            - mode collapse 완화 (회차마다 동일 번호 반복 방지)

        Args:
            target_round         : 회차 시드 (None이면 fixed seed로 기존 동작)
            diversity_temperature: softmax 온도. 0.06 권장 (Stage 6-F sweep 최적값,
                                  hit_top5=0.818 random+23%). T<0.04 너무 greedy, T>0.12 너무 평탄.
            draws_so_far         : [P1 PATCH] 빈도 페널티용 회차 history (None이면 페널티 비활성)
        """
        comp = _coerce_filter_compliance(filter_compliance)
        median_comp = float(np.median(comp))
        thr_comp = median_comp + 0.1

        # 메모 forced_includes
        memo_forced: set[int] = set()
        memo_excludes: set[int] = set()
        if isinstance(expert_memo, dict):
            memo_forced = _safe_int_set(expert_memo.get("forced_includes"))
            memo_excludes = _safe_int_set(expert_memo.get("forced_excludes"))

        # 강제 포함은 forced_excludes와 충돌 시 forced_excludes 우선 (사용자 모순 방어)
        memo_forced = memo_forced - memo_excludes

        # ── [P1 PATCH] 빈도 페널티 적용 ────────────────────────────────
        # favorite bias 해소: 직전 3회 출현 + historical 과빈출 감점
        # memo_forced는 페널티 면제 (사용자 의도 존중)
        if draws_so_far:
            _adjusted_scores: dict[int, float] = {}
            for _n in range(1, 46):
                _base = float(scores.get(_n, 0.0))
                if _n in memo_forced:
                    _adjusted_scores[_n] = _base
                else:
                    _coef = _compute_frequency_penalty(_n, draws_so_far)
                    _adjusted_scores[_n] = _base * _coef
            scores = _adjusted_scores
        # ── /P1 PATCH ─────────────────────────────────────────────────

        # 1) memo forced_includes 우선 슬롯 채우기
        result: list[dict] = []
        used: set[int] = set()
        for n in sorted(memo_forced):
            if len(result) >= n_top:
                break
            entry = self._build_rec_entry(
                n=n,
                scores=scores,
                consensus_metrics=consensus_metrics,
                comp=comp,
                bayesian_sigma=bayesian_sigma,
                memo_forced=True,
            )
            result.append(entry)
            used.add(n)

        if len(result) >= n_top:
            return result[:n_top]

        # 2) final_score 상위 15 후보 (memo_excludes 제외)
        scored_items = [
            (n, float(scores.get(n, 0.0)))
            for n in range(1, 46)
            if n not in used and n not in memo_excludes
        ]
        scored_items.sort(key=lambda kv: kv[1], reverse=True)
        candidates = [n for n, _ in scored_items[:15]]

        # 3) consensus.top10_count >= threshold 통과
        c_pass: list[int] = []
        for n in candidates:
            m = consensus_metrics.get(n) or {}
            top10 = int(m.get("top10_count", 0) or 0)
            if top10 >= _REC_TOP10_THR:
                c_pass.append(n)

        # 4) filter_compliance >= median + 0.1 통과
        f_pass = [n for n in c_pass if comp[n - 1] >= thr_comp]

        # 5) (Stage 6-D/F-3) Plackett-Luce + GNN co-occurrence diversity
        # CI lower bound를 score로 사용 (Bayesian sigma 가용 시 보수적)
        def _ci_score(n: int) -> float:
            sc = float(scores.get(n, 0.0))
            sig = None
            if isinstance(bayesian_sigma, dict):
                sig = bayesian_sigma.get(n, bayesian_sigma.get(str(n)))
            return _ci_lower_estimate(sc, sig)

        need = n_top - len(result)

        # F-3: GNN adjacency lazy load (조합 다양성 보너스)
        gnn_adj = self._load_gnn_adjacency() if gnn_diversity_strength > 0.0 else None

        # f_pass에서 우선 샘플링
        f_scored = [(n, _ci_score(n)) for n in f_pass]
        f_scored.sort(key=lambda kv: kv[1], reverse=True)
        picked = _plackett_luce_diverse_pick(
            f_scored, need, target_round=target_round,
            temperature=diversity_temperature, salt="rec",
            adjacency=gnn_adj, gnn_penalty_strength=gnn_diversity_strength,
        )

        # 부족 시 c_pass에서 추가 샘플링 (이미 picked는 제외)
        if len(picked) < need:
            remain_c = [n for n in c_pass if n not in picked]
            c_scored = [(n, _ci_score(n)) for n in remain_c]
            c_scored.sort(key=lambda kv: kv[1], reverse=True)
            extra = _plackett_luce_diverse_pick(
                c_scored, need - len(picked), target_round=target_round,
                temperature=diversity_temperature, salt="rec_c",
                adjacency=gnn_adj, gnn_penalty_strength=gnn_diversity_strength,
            )
            picked.extend(extra)

        # 그래도 부족 시 candidates 전체에서 보충
        if len(picked) < need:
            remain_all = [n for n in candidates if n not in picked]
            a_scored = [(n, _ci_score(n)) for n in remain_all]
            a_scored.sort(key=lambda kv: kv[1], reverse=True)
            extra = _plackett_luce_diverse_pick(
                a_scored, need - len(picked), target_round=target_round,
                temperature=diversity_temperature, salt="rec_a",
                adjacency=gnn_adj, gnn_penalty_strength=gnn_diversity_strength,
            )
            picked.extend(extra)

        for n in picked[:need]:
            entry = self._build_rec_entry(
                n=n,
                scores=scores,
                consensus_metrics=consensus_metrics,
                comp=comp,
                bayesian_sigma=bayesian_sigma,
                memo_forced=False,
            )
            result.append(entry)

        # ── fix-48 흡수: Hot/Cold 균형 ────────────────────────────────────
        try:
            picked_numbers = [r["number"] for r in result]
            # candidates는 위 단계의 후보 풀 (top 15)
            balanced_numbers = self._apply_hotcold_balance(
                picked=picked_numbers,
                candidates=candidates,
                draws_so_far=draws_so_far,
                scores=scores,
            )
            if balanced_numbers != picked_numbers:
                # 균형 변경 발생 → result 재조립
                result = [self._build_rec_entry(
                    n=n,
                    scores=scores,
                    consensus_metrics=consensus_metrics,
                    comp=comp,
                    bayesian_sigma=bayesian_sigma,
                    memo_forced=(n in memo_forced),
                ) for n in balanced_numbers]
        except Exception as e:
            print(f"[NumberRecommender] hotcold_balance 실패 (무시): {e}")

        return result[:n_top]

    @staticmethod
    def _build_rec_entry(
        n: int,
        scores: dict[int, float],
        consensus_metrics: dict[int, dict],
        comp: np.ndarray,
        bayesian_sigma: dict[int, float] | None,
        memo_forced: bool,
    ) -> dict:
        """추천 1 entry 조립."""
        sc = float(scores.get(n, 0.0))
        m = consensus_metrics.get(n) or {}
        top10 = int(m.get("top10_count", 0) or 0)
        sig = None
        if isinstance(bayesian_sigma, dict):
            sig = bayesian_sigma.get(n, bayesian_sigma.get(str(n)))
        ci_lo = _ci_lower_estimate(sc, sig)

        # narrative_seed: 핵심 시그널 한 줄
        seed = (
            f"score={sc:.3f}, top10_count={top10}, "
            f"filter_compliance={comp[n - 1]:.3f}"
        )
        if memo_forced:
            seed = "memo_forced_include; " + seed

        return {
            "number": int(n),
            "score": float(sc),
            "consensus_top10_count": int(top10),
            "filter_compliance": float(comp[n - 1]),
            "ci_lower": float(ci_lo),
            "narrative_seed": seed,
            "memo_forced": bool(memo_forced),
        }

    def _apply_hotcold_balance(
        self,
        picked: list[int],
        candidates: list[int],
        draws_so_far: list[dict] | None,
        scores: dict[int, float],
        hot_min: int = 2,
        cold_max: int = 2,
        freq_window: int = 20,
    ) -> list[int]:
        """Hot/Cold 균형 강제 (fix-48 흡수 — weekly_pipeline_v2 line 353-420에서 이전).

        룰:
          - Hot 최소 2 (최근 freq_window회에 5번 이상 출현)
          - Cold 최대 2 (최근 freq_window회에 3번 미만 출현)

        Args:
            picked: NumberRecommender가 선출한 top_5
            candidates: 보충 후보 풀 (top 15)
            draws_so_far: 회차 history (round DESC)
            scores: {n: score}
            hot_min/cold_max: 균형 임계
            freq_window: 빈도 산출 윈도우

        Returns:
            균형 조정된 picked (len 동일)
        """
        if not draws_so_far or not picked:
            return picked

        recent = draws_so_far[:freq_window] if len(draws_so_far) >= freq_window else draws_so_far
        freq_count = {n: 0 for n in range(1, 46)}
        for d in recent:
            nums = d.get("numbers") if isinstance(d, dict) else d
            if isinstance(nums, (list, tuple, set)):
                for x in nums:
                    try:
                        xi = int(x)
                        if 1 <= xi <= 45:
                            freq_count[xi] += 1
                    except (ValueError, TypeError):
                        continue

        def _cls(n: int) -> str:
            fc = freq_count.get(n, 0)
            if fc >= 5: return "hot"
            if fc >= 3: return "neutral"
            return "cold"

        balanced = list(picked)
        cur_hot = sum(1 for n in balanced if _cls(n) == "hot")
        cur_cold = sum(1 for n in balanced if _cls(n) == "cold")

        pool = [n for n in candidates if n not in balanced]

        # Hot 부족 → Hot 후보로 cold 교체 (가장 score 낮은 cold부터)
        if cur_hot < hot_min:
            hot_pool = [n for n in pool if _cls(n) == "hot"]
            cold_in = [n for n in balanced if _cls(n) == "cold"]
            cold_in.sort(key=lambda n: scores.get(n, 0))
            for new_n in hot_pool:
                if cur_hot >= hot_min or not cold_in:
                    break
                old_n = cold_in.pop(0)
                idx = balanced.index(old_n)
                balanced[idx] = new_n
                cur_hot += 1
                cur_cold -= 1

        # Cold 초과 → Non-cold로 교체
        if cur_cold > cold_max:
            non_cold = [n for n in pool if _cls(n) != "cold" and n not in balanced]
            cold_in = [n for n in balanced if _cls(n) == "cold"]
            cold_in.sort(key=lambda n: scores.get(n, 0))
            while cur_cold > cold_max and non_cold and cold_in:
                new_n = non_cold.pop(0)
                old_n = cold_in.pop(0)
                idx = balanced.index(old_n)
                balanced[idx] = new_n
                cur_cold -= 1

        return balanced

    # ------------------------------------------------------------------
    # 제외 10 결정
    # ------------------------------------------------------------------
    def select_exclusions(
        self,
        scores: dict[int, float],
        consensus_metrics: dict[int, dict],
        filter_compliance: np.ndarray,
        regression_rules_output: dict | None = None,
        expert_memo: dict | None = None,
        n_exc: int = 10,
        gnn_strong_set: set[int] | None = None,
        target_round: int | None = None,
        diversity_temperature: float = 0.06,
    ) -> list[dict]:
        """제외 10 선출 (Hard Filter 3계층).

        흐름:
        1. 사용자 메모 forced_excludes 강제 (최우선)
        2. 자동 룰 1·2·3 force_exclude 추가
        3. 4 Pillar 다중 조건 통과 후보
           - final_score 하위 -> 하위 15
           - consensus.bottom15_count >= EXC_BOT15_THR
           - filter_compliance < median - 0.1
        4. GNN co-occurrence veto 보강 (가용 시)
        5. 통합: 메모 + 자동 룰 + Pillar 보완 -> top n_exc
        """
        comp = _coerce_filter_compliance(filter_compliance)
        median_comp = float(np.median(comp))
        thr_low = median_comp - 0.1

        # 메모
        memo_excludes: set[int] = set()
        memo_forced_includes: set[int] = set()
        if isinstance(expert_memo, dict):
            memo_excludes = _safe_int_set(expert_memo.get("forced_excludes"))
            memo_forced_includes = _safe_int_set(expert_memo.get("forced_includes"))

        # 자동 룰 force_exclude + 사유 매핑
        auto_force: set[int] = set()
        reason_lookup: dict[int, str] = {}
        if isinstance(regression_rules_output, dict):
            fset = regression_rules_output.get("force_exclude")
            if isinstance(fset, (set, list, tuple)):
                auto_force |= _safe_int_set(fset)

            # 룰별 reason
            for r in regression_rules_output.get("rule1_consecutive_n", []) or []:
                if isinstance(r, dict):
                    n = r.get("number")
                    if isinstance(n, int) and 1 <= n <= 45:
                        reason_lookup.setdefault(
                            n, str(r.get("reason", "regression_consecutive"))
                        )
            for r in regression_rules_output.get("rule1_recent", []) or []:
                if isinstance(r, dict):
                    n = r.get("number")
                    if isinstance(n, int) and 1 <= n <= 45:
                        reason_lookup.setdefault(n, "recent_4_consecutive")
            for r in regression_rules_output.get("rule2_dead_lines", []) or []:
                if isinstance(r, dict):
                    n = r.get("number")
                    if isinstance(n, int) and 1 <= n <= 45:
                        reason_lookup.setdefault(n, "dead_carryover_lines")

        # forced_includes는 절대 제외하지 않음 (1순위 메모)
        memo_excludes = memo_excludes - memo_forced_includes
        auto_force = auto_force - memo_forced_includes

        # 1) 메모 강제 제외 (최우선)
        result: list[dict] = []
        picked: set[int] = set()
        for n in sorted(memo_excludes):
            if len(result) >= n_exc:
                break
            entry = self._build_exc_entry(
                n=n,
                scores=scores,
                consensus_metrics=consensus_metrics,
                comp=comp,
                exclude_reason="memo",
                force_exclude=True,
            )
            result.append(entry)
            picked.add(n)

        # 2) 자동 룰 force_exclude
        for n in sorted(auto_force - picked):
            if len(result) >= n_exc:
                break
            reason = reason_lookup.get(n, "regression_auto_rule")
            entry = self._build_exc_entry(
                n=n,
                scores=scores,
                consensus_metrics=consensus_metrics,
                comp=comp,
                exclude_reason=reason,
                force_exclude=True,
            )
            result.append(entry)
            picked.add(n)

        if len(result) >= n_exc:
            return result[:n_exc]

        # 3) 4 Pillar 다중 조건 후보
        scored_items = [
            (n, float(scores.get(n, 0.0)))
            for n in range(1, 46)
            if n not in picked and n not in memo_forced_includes
        ]
        scored_items.sort(key=lambda kv: kv[1])  # 오름차순 (낮은 점수)
        low_candidates = [n for n, _ in scored_items[:15]]

        c_pass: list[int] = []
        for n in low_candidates:
            m = consensus_metrics.get(n) or {}
            bot15 = int(m.get("bottom15_count", 0) or 0)
            if bot15 >= _EXC_BOT15_THR:
                c_pass.append(n)

        f_pass = [n for n in c_pass if comp[n - 1] < thr_low]

        # 4) (Stage 6-D) GNN veto + Plackett-Luce diversity (점수 작은 게 좋음)
        gnn_set = gnn_strong_set or set()

        def _exc_score(n: int) -> float:
            """제외 점수: low score + GNN strong 보너스. 작을수록 강한 제외."""
            base = float(scores.get(n, 0.0))
            # GNN strong이면 -0.05 보너스 (더 작아짐 = 더 강한 제외)
            if n in gnn_set:
                base -= 0.05
            return base

        need = n_exc - len(result)

        # 5) f_pass에서 PL 샘플링 (작을수록 좋음 → ASC variant)
        f_scored = [(n, _exc_score(n)) for n in f_pass if n not in picked]
        f_scored.sort(key=lambda kv: kv[1])  # 오름차순
        f_picked = _plackett_luce_diverse_pick_asc(
            f_scored, need, target_round=target_round,
            temperature=diversity_temperature, salt="exc",
        )
        for n in f_picked:
            if len(result) >= n_exc:
                break
            if n in picked:
                continue
            entry = self._build_exc_entry(
                n=n,
                scores=scores,
                consensus_metrics=consensus_metrics,
                comp=comp,
                exclude_reason="pillar_score_low",
                force_exclude=False,
            )
            result.append(entry)
            picked.add(n)

        # 6) 부족 시 c_pass에서 PL 샘플링
        if len(result) < n_exc:
            remain_c = [n for n in c_pass if n not in picked]
            c_scored = [(n, _exc_score(n)) for n in remain_c]
            c_scored.sort(key=lambda kv: kv[1])
            c_picked = _plackett_luce_diverse_pick_asc(
                c_scored, n_exc - len(result),
                target_round=target_round,
                temperature=diversity_temperature, salt="exc_c",
            )
            for n in c_picked:
                if len(result) >= n_exc:
                    break
                if n in picked:
                    continue
                entry = self._build_exc_entry(
                    n=n,
                    scores=scores,
                    consensus_metrics=consensus_metrics,
                    comp=comp,
                    exclude_reason="pillar_score_low",
                    force_exclude=False,
                )
                result.append(entry)
                picked.add(n)

        # 7) 그래도 부족 시 low_candidates 전체에서 PL 샘플링
        if len(result) < n_exc:
            remain_l = [n for n in low_candidates if n not in picked]
            l_scored = [(n, _exc_score(n)) for n in remain_l]
            l_scored.sort(key=lambda kv: kv[1])
            l_picked = _plackett_luce_diverse_pick_asc(
                l_scored, n_exc - len(result),
                target_round=target_round,
                temperature=diversity_temperature, salt="exc_l",
            )
            for n in l_picked:
                if len(result) >= n_exc:
                    break
                if n in picked:
                    continue
                entry = self._build_exc_entry(
                    n=n,
                    scores=scores,
                    consensus_metrics=consensus_metrics,
                    comp=comp,
                    exclude_reason="pillar_score_low",
                    force_exclude=False,
                )
                result.append(entry)
                picked.add(n)

        return result[:n_exc]

    @staticmethod
    def _build_exc_entry(
        n: int,
        scores: dict[int, float],
        consensus_metrics: dict[int, dict],
        comp: np.ndarray,
        exclude_reason: str,
        force_exclude: bool,
    ) -> dict:
        """제외 1 entry 조립."""
        sc = float(scores.get(n, 0.0))
        m = consensus_metrics.get(n) or {}
        bot15 = int(m.get("bottom15_count", 0) or 0)

        seed = (
            f"reason={exclude_reason}, score={sc:.3f}, "
            f"bottom15_count={bot15}, filter_compliance={comp[n - 1]:.3f}"
        )
        if force_exclude:
            seed = "force_exclude; " + seed

        return {
            "number": int(n),
            "score": float(sc),
            "exclude_reason": str(exclude_reason),
            "force_exclude": bool(force_exclude),
            "consensus_bottom15_count": int(bot15),
            "filter_compliance": float(comp[n - 1]),
            "narrative_seed": seed,
        }

    # ------------------------------------------------------------------
    # 통합 진입점
    # ------------------------------------------------------------------
    def recommend(
        self,
        final_probs: dict[int, float],
        filter_stats_result: dict | list,
        predictor_pipeline_outputs: dict,
        rankings: dict[str, list[int]],
        expert_memo: dict | None = None,
        target_round: int | None = None,
        n_top: int = 5,
        n_exc: int = 10,
        draws_so_far: list[dict] | None = None,
        bayesian_sigma: dict[int, float] | None = None,
        gnn_strong_set: set[int] | None = None,
        filter_compliance_override: np.ndarray | dict | None = None,
        auto_load_memo: bool = True,
    ) -> dict:
        """추천 5 + 제외 10 + Hard Filter 3계층 통합 진입점.

        흐름:
        0. (신규) target_round 지정 시 Supabase에서 메모 자동 로드
        1. ConsensusAnalyzer로 Pillar 4 메트릭 산출
        2. NumberScorer로 4 Pillar 점수 (final_score) 산출
        3. filter_compliance 추출 (filter_stats_result 또는 override)
        4. regression_rules_output 추출 (predictor_pipeline_outputs.regression.tier3_rules)
        5. select_recommendations + select_exclusions

        Args:
            target_round      : 예측 대상 회차 (메모 자동 로드용)
            auto_load_memo    : True면 target_round로 메모 자동 조회 (expert_memo 우선)
        """
        # 0) 메모 자동 로드 (expert_memo 미지정 + target_round 가용 시)
        if expert_memo is None and target_round is not None and auto_load_memo:
            try:
                loaded = self.memo_loader.load_memos_for_round(target_round)
                if loaded:
                    expert_memo = loaded
                    print(f"[NumberRecommender] Auto-loaded memo for round {target_round}")
            except Exception as e:
                print(f"[NumberRecommender] Memo auto-load fail: {e}")
        # 1) Pillar 4
        if self.consensus_analyzer is not None and rankings:
            consensus_metrics = self.consensus_analyzer.compute_metrics(rankings)
        else:
            consensus_metrics = {
                n: {
                    "mean_rank": 0.0,
                    "std_rank": 0.0,
                    "top10_count": 0,
                    "bottom15_count": 0,
                    "consensus_score": 0.0,
                    "n_models": 0,
                }
                for n in range(1, 46)
            }

        # 2) 4 Pillar -> final_score
        if self.scorer is not None:
            try:
                scores = self.scorer.score_numbers(
                    ensemble_probs=final_probs,
                    filter_stats_result=filter_stats_result,
                    predictor_pipeline_outputs=predictor_pipeline_outputs,
                    consensus_metrics=consensus_metrics,
                    draws_so_far=draws_so_far,
                    bayesian_sigma=bayesian_sigma,
                )
            except Exception as e:
                print(f"[NumberRecommender] scorer.score_numbers fail: {e}")
                scores = {n: float(final_probs.get(n, 0.0)) for n in range(1, 46)}
        else:
            scores = {n: float(final_probs.get(n, 0.0)) for n in range(1, 46)}

        # 3) filter_compliance
        if filter_compliance_override is not None:
            comp = _coerce_filter_compliance(filter_compliance_override)
        else:
            comp = self._extract_filter_compliance(filter_stats_result)

        # 4) regression_rules_output
        regr_rules = None
        if isinstance(predictor_pipeline_outputs, dict):
            regr = predictor_pipeline_outputs.get("regression") or {}
            if isinstance(regr, dict):
                # tier3_rules가 직접 force_exclude를 가질 수도 있고,
                # apply_all_regression_rules() 출력 형태를 가질 수도 있다.
                t3 = regr.get("tier3_rules") or regr.get("rules") or regr
                if isinstance(t3, dict):
                    regr_rules = t3

        # 5) 추천 + 제외 (Stage 6-D: target_round 전파 + [P1] draws_so_far)
        recommendations = self.select_recommendations(
            scores=scores,
            consensus_metrics=consensus_metrics,
            filter_compliance=comp,
            expert_memo=expert_memo,
            n_top=n_top,
            bayesian_sigma=bayesian_sigma,
            target_round=target_round,
            draws_so_far=draws_so_far,  # [P1 PATCH]
        )
        exclusions = self.select_exclusions(
            scores=scores,
            consensus_metrics=consensus_metrics,
            filter_compliance=comp,
            regression_rules_output=regr_rules,
            expert_memo=expert_memo,
            n_exc=n_exc,
            gnn_strong_set=gnn_strong_set,
            target_round=target_round,
        )

        # Hard Filter 3계층 요약
        memo_inc = sorted(
            _safe_int_set(expert_memo.get("forced_includes")) if isinstance(expert_memo, dict) else set()
        )
        memo_exc = sorted(
            _safe_int_set(expert_memo.get("forced_excludes")) if isinstance(expert_memo, dict) else set()
        )
        auto_exc = sorted(
            _safe_int_set(regr_rules.get("force_exclude")) if isinstance(regr_rules, dict) else set()
        )
        pillar_exc = sorted(
            {e["number"] for e in exclusions if not e.get("force_exclude")}
        )

        # Pillar 가중치
        pw_used: dict[str, float] = {}
        if self.scorer is not None:
            try:
                names = ["pillar_1_ensemble", "pillar_2_filter",
                         "pillar_3_individual", "pillar_4_consensus"]
                for i, name in enumerate(names):
                    pw_used[name] = float(self.scorer.pillar_weights[i])
            except Exception:
                pw_used = {}

        return {
            "recommendations": recommendations,
            "exclusions": exclusions,
            "hard_filter_summary": {
                "memo_forced_includes": memo_inc,
                "memo_forced_excludes": memo_exc,
                "auto_rules_excludes": auto_exc,
                "pillar_score_excludes": pillar_exc,
            },
            "pillar_weights_used": pw_used,
            "metadata": {
                "n_recommendations": len(recommendations),
                "n_exclusions": len(exclusions),
                "memo_active": bool(memo_inc or memo_exc),
                "rec_top10_threshold": _REC_TOP10_THR,
                "exc_bot15_threshold": _EXC_BOT15_THR,
            },
        }

    # ------------------------------------------------------------------
    # filter_compliance 추출 헬퍼
    # ------------------------------------------------------------------
    def _extract_filter_compliance(
        self, filter_stats_result: dict | list | None
    ) -> np.ndarray:
        """filter_stats.compute_all() 출력에서 (45,) 통과도 추출.

        FilterStatsComputer 내부 통과도 정의가 다양하므로,
        여기서는 NumberScorer._compute_pillar_2를 재활용하여 일관 산출.
        """
        if self.scorer is not None:
            try:
                comp = self.scorer._compute_pillar_2(filter_stats_result, [])  # noqa: SLF001
                return np.asarray(comp, dtype=np.float64).ravel()
            except Exception as e:
                print(f"[NumberRecommender] _compute_pillar_2 fail: {e}")

        # fallback: 0.5 uniform
        return np.full(45, 0.5, dtype=np.float64)

    # ------------------------------------------------------------------
    # XAI evidence (Stage 4 narrative 입력)
    # ------------------------------------------------------------------
    def build_xai_evidence(
        self,
        item: dict,
        scores: dict[int, float],
        consensus_metrics: dict[int, dict],
        filter_compliance: np.ndarray,
        regression_rules_output: dict | None = None,
        expert_memo: dict | None = None,
        kind: str = "recommend",
    ) -> dict:
        """단일 추천/제외 entry에 대한 4 Pillar 분해 + 활성 시그널.

        Args:
            item                   : recommendation 또는 exclusion entry
            scores                 : final_score
            consensus_metrics      : ConsensusAnalyzer 결과
            filter_compliance      : (45,) np.ndarray
            regression_rules_output: apply_all_regression_rules() 출력
            expert_memo            : 사용자 메모
            kind                   : "recommend" | "exclude"
        """
        n = int(item.get("number", 0))
        comp = _coerce_filter_compliance(filter_compliance)
        m = consensus_metrics.get(n) or {}

        # 메모 시그널
        memo_inc = _safe_int_set(expert_memo.get("forced_includes")) if isinstance(expert_memo, dict) else set()
        memo_exc = _safe_int_set(expert_memo.get("forced_excludes")) if isinstance(expert_memo, dict) else set()

        # 자동 룰 트리거 매핑
        rule_triggers: list[str] = []
        if isinstance(regression_rules_output, dict):
            for r in regression_rules_output.get("rule1_consecutive_n", []) or []:
                if isinstance(r, dict) and int(r.get("number", -1)) == n:
                    rule_triggers.append(str(r.get("reason", "regression_consecutive")))
            for r in regression_rules_output.get("rule1_recent", []) or []:
                if isinstance(r, dict) and int(r.get("number", -1)) == n:
                    rule_triggers.append("recent_4_consecutive")
            for r in regression_rules_output.get("rule2_dead_lines", []) or []:
                if isinstance(r, dict) and int(r.get("number", -1)) == n:
                    rule_triggers.append("dead_carryover_lines")

        return {
            "number": n,
            "kind": str(kind),
            "score": float(scores.get(n, 0.0)),
            "pillar_4_consensus": {
                "mean_rank": float(m.get("mean_rank", 0.0)),
                "std_rank": float(m.get("std_rank", 0.0)),
                "top10_count": int(m.get("top10_count", 0) or 0),
                "bottom15_count": int(m.get("bottom15_count", 0) or 0),
                "consensus_score": float(m.get("consensus_score", 0.0)),
            },
            "pillar_2_filter_compliance": float(comp[n - 1]),
            "memo_signal": {
                "forced_include": (n in memo_inc),
                "forced_exclude": (n in memo_exc),
            },
            "auto_rule_triggers": rule_triggers,
            "narrative_seed": str(item.get("narrative_seed", "")),
        }


# ──────────────────────────────────────────────────────────────────────
# Smoke main
# ──────────────────────────────────────────────────────────────────────
def main() -> None:
    """smoke: 가짜 입력 -> recommend() -> 5/10 정상 + Hard Filter 3계층 동작 검증."""
    print("[NumberRecommender] smoke start")

    rng = np.random.default_rng(_RANDOM_SEED)

    # 1. 가짜 final_probs (Dirichlet)
    probs_arr = rng.dirichlet(np.ones(45) * 0.6)
    fake_final_probs = {n: float(probs_arr[n - 1]) for n in range(1, 46)}

    # 2. 가짜 11 base rankings — boost {3, 11, 17, 23} sink {22, 33, 42, 44}
    base_models = [
        "xgboost", "catboost", "tabnet",
        "cnn", "gnn", "markov",
        "autoencoder", "tft", "nbeats",
        "mhn", "bayesian_nn",
    ]
    boost = {3, 11, 17, 23}
    sink = {22, 33, 42, 44}
    fake_rankings: dict[str, list[int]] = {}
    for name in base_models:
        p = rng.dirichlet(np.ones(45) * 0.6)
        for t in boost:
            p[t - 1] += 0.10
        for t in sink:
            p[t - 1] *= 0.05
        p = p / p.sum()
        order = sorted(range(1, 46), key=lambda x: -p[x - 1])
        fake_rankings[name] = order

    # 3. 가짜 filter_stats (NumberScorer Pillar 2 입력 형태)
    fake_filter = [
        {"key": "total_sum",  "ml_recommendation": {"min": 100, "median": 132, "max": 165}},
        {"key": "tail_sum",   "ml_recommendation": {"min": 15, "median": 20, "max": 28}},
        {"key": "ac_value",   "ml_recommendation": {"min": 5, "median": 8, "max": 10}},
        {"key": "odd_even",   "ml_recommendation": {"top_class": 3}},
        {"key": "low_high",   "ml_recommendation": {"top_class": 3}},
        {"key": "hot_cold",
         "ml_recommendation": {"per_category": {"hot_pool": [3, 11, 17, 23], "cold_pool": [22, 33, 42, 44]}}},
        {"key": "carryover",  "ml_recommendation": {}},
        {"key": "neighbor_count", "ml_recommendation": {}},
    ]

    # 4. 가짜 predictor outputs (Pillar 3 + regression)
    fake_predictor = {
        "phase1": {
            "hotcold": {"per_category": {"hot_pool": [3, 11, 17, 23, 38],
                                          "cold_pool": [22, 33, 42, 44]}},
            "missing_group": {"per_category": {"missing_pool": [40, 41]}},
        },
        "regression": {
            "tier1": {"active_N_set": [2, 3, 8, 22]},
            "tier3_rules": {
                # apply_all_regression_rules() 출력 형태
                "force_exclude": {22, 33},   # 자동 룰 강제 제외
                "rule1_consecutive_n": [
                    {"number": 22, "reason": "regression_consecutive_N12",
                     "max_consecutive": 5, "regression_N": 12, "narrative": "smoke"},
                ],
                "rule1_recent": [],
                "rule2_dead_lines": [
                    {"number": 33, "reason": "dead_carryover_lines",
                     "count": 2, "details": [], "narrative": "smoke"},
                ],
                "decade_clusters": [],
                "auto_applied_filters": {},
            },
        },
    }

    fake_draws = [{"round": 1100, "numbers": [5, 12, 19, 28, 33, 41]}]

    # 5. expert memo: forced_includes [3, 11], forced_excludes [42]
    fake_memo = {
        "forced_includes": [3, 11],
        "forced_excludes": [42],
    }

    # 6. NumberRecommender 인스턴스
    if NumberScorer is None:
        print("  WARN: NumberScorer unavailable, fallback path")
    if ConsensusAnalyzer is None:
        print("  WARN: ConsensusAnalyzer unavailable, fallback path")

    # 가짜 NumberScorer (fitted) - 학습 데이터 없이도 fallback 가중합 동작
    scorer = NumberScorer() if NumberScorer is not None else None
    consensus = ConsensusAnalyzer() if ConsensusAnalyzer is not None else None

    rec = NumberRecommender(scorer=scorer, consensus_analyzer=consensus)

    # 7. recommend() 호출
    result = rec.recommend(
        final_probs=fake_final_probs,
        filter_stats_result=fake_filter,
        predictor_pipeline_outputs=fake_predictor,
        rankings=fake_rankings,
        expert_memo=fake_memo,
        draws_so_far=fake_draws,
        n_top=5,
        n_exc=10,
    )

    print(f"\n  [1] recommendations ({len(result['recommendations'])}):")
    for r in result["recommendations"]:
        print(
            f"      n={r['number']:2d} score={r['score']:7.4f} "
            f"top10={r['consensus_top10_count']} "
            f"comp={r['filter_compliance']:.3f} "
            f"ci_lo={r['ci_lower']:7.4f} "
            f"memo_forced={r['memo_forced']}"
        )

    print(f"\n  [2] exclusions ({len(result['exclusions'])}):")
    for e in result["exclusions"]:
        print(
            f"      n={e['number']:2d} score={e['score']:7.4f} "
            f"reason={e['exclude_reason']:<28s} "
            f"force={e['force_exclude']} "
            f"bot15={e['consensus_bottom15_count']}"
        )

    summary = result["hard_filter_summary"]
    print(f"\n  [3] hard_filter_summary:")
    print(f"      memo_forced_includes : {summary['memo_forced_includes']}")
    print(f"      memo_forced_excludes : {summary['memo_forced_excludes']}")
    print(f"      auto_rules_excludes  : {summary['auto_rules_excludes']}")
    print(f"      pillar_score_excludes: {summary['pillar_score_excludes']}")

    print(f"\n  [4] pillar_weights_used: {result['pillar_weights_used']}")
    print(f"  [5] metadata           : {result['metadata']}")

    # 8. 검증
    rec_nums = {r["number"] for r in result["recommendations"]}
    exc_nums = {e["number"] for e in result["exclusions"]}

    # 메모 forced_includes 우선순위 1
    assert 3 in rec_nums, f"memo forced_include 3 must be recommended, got {rec_nums}"
    assert 11 in rec_nums, f"memo forced_include 11 must be recommended, got {rec_nums}"
    print("\n  [v1] memo forced_includes [3, 11] recommended OK")

    # 메모 forced_excludes 우선순위 1
    assert 42 in exc_nums, f"memo forced_exclude 42 must be in exclusions, got {exc_nums}"
    memo_exc_entry = [e for e in result["exclusions"] if e["number"] == 42][0]
    assert memo_exc_entry["exclude_reason"] == "memo", (
        f"reason must be 'memo', got {memo_exc_entry['exclude_reason']}"
    )
    assert memo_exc_entry["force_exclude"] is True
    print("  [v2] memo forced_excludes [42] excluded with reason='memo' OK")

    # 자동 룰 우선순위 2
    assert 22 in exc_nums, f"auto rule force_exclude 22 must be in exclusions, got {exc_nums}"
    assert 33 in exc_nums, f"auto rule force_exclude 33 must be in exclusions, got {exc_nums}"
    e22 = [e for e in result["exclusions"] if e["number"] == 22][0]
    e33 = [e for e in result["exclusions"] if e["number"] == 33][0]
    assert e22["force_exclude"] is True
    assert e33["force_exclude"] is True
    assert e22["exclude_reason"] != "memo", "22 reason must NOT be memo"
    assert e33["exclude_reason"] != "memo", "33 reason must NOT be memo"
    print(f"  [v3] auto rule force_exclude [22, 33] OK")
    print(f"        reason(22)={e22['exclude_reason']}, reason(33)={e33['exclude_reason']}")

    # 4 Pillar 다중 조건 통과 - non-force 제외수가 일부 존재 (10개 채움 보장)
    assert len(result["exclusions"]) == 10, f"need 10 exclusions, got {len(result['exclusions'])}"
    assert len(result["recommendations"]) == 5, f"need 5 recs, got {len(result['recommendations'])}"
    print("  [v4] 5 recs + 10 excs filled OK")

    # forced_includes는 절대 제외되지 않음
    assert 3 not in exc_nums and 11 not in exc_nums, (
        f"forced_includes must never be excluded, got exc={exc_nums}"
    )
    print("  [v5] forced_includes [3, 11] NOT in exclusions OK")

    # exclude_reason 분포
    reason_dist: dict[str, int] = {}
    for e in result["exclusions"]:
        reason_dist[e["exclude_reason"]] = reason_dist.get(e["exclude_reason"], 0) + 1
    print(f"\n  [v6] exclude_reason distribution: {reason_dist}")

    # metadata 정합성
    assert result["metadata"]["n_recommendations"] == 5
    assert result["metadata"]["n_exclusions"] == 10
    assert result["metadata"]["memo_active"] is True
    print("  [v7] metadata consistent OK")

    # 9. None fallback (메모 미존재, 자동 룰 미존재)
    print("\n  [9] None fallback test (no memo, no auto rules):")
    result2 = rec.recommend(
        final_probs=fake_final_probs,
        filter_stats_result=fake_filter,
        predictor_pipeline_outputs={"phase1": fake_predictor["phase1"]},  # regression 없음
        rankings=fake_rankings,
        expert_memo=None,
        draws_so_far=fake_draws,
    )
    assert len(result2["recommendations"]) == 5
    assert len(result2["exclusions"]) == 10
    assert result2["metadata"]["memo_active"] is False
    rec_nums2 = {r["number"] for r in result2["recommendations"]}
    print(f"      fallback recs   : {sorted(rec_nums2)}")
    excs2 = {e["number"] for e in result2["exclusions"]}
    print(f"      fallback excs   : {sorted(excs2)}")
    # 4 Pillar 만으로 5/10 채움 검증
    for e in result2["exclusions"]:
        assert e["force_exclude"] is False, "no force_exclude when no memo/rules"
    print("      all force_exclude=False OK (Pillar-only fallback)")

    # 10. XAI evidence
    if result["recommendations"]:
        ev = rec.build_xai_evidence(
            item=result["recommendations"][0],
            scores={n: float(rng.normal(0, 1)) for n in range(1, 46)},
            consensus_metrics=(
                consensus.compute_metrics(fake_rankings)
                if consensus is not None else
                {n: {} for n in range(1, 46)}
            ),
            filter_compliance=np.full(45, 0.5),
            regression_rules_output=fake_predictor["regression"]["tier3_rules"],
            expert_memo=fake_memo,
            kind="recommend",
        )
        print(f"\n  [10] xai_evidence sample: number={ev['number']} keys={list(ev.keys())}")
        assert "pillar_4_consensus" in ev
        assert "pillar_2_filter_compliance" in ev
        assert "memo_signal" in ev
        assert "auto_rule_triggers" in ev

    print("\n[NumberRecommender] smoke OK")


if __name__ == "__main__":
    main()
