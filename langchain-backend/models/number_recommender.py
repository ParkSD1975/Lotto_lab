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
# NumberRecommender
# ──────────────────────────────────────────────────────────────────────
class NumberRecommender:
    """Hard Filter 3계층 + 추천 5 + 제외 10 결정."""

    def __init__(
        self,
        scorer: "NumberScorer | None" = None,
        consensus_analyzer: "ConsensusAnalyzer | None" = None,
    ):
        """외부 주입 받거나 lazy 초기화.

        Args:
            scorer            : NumberScorer (4 Pillar Ridge 통합)
            consensus_analyzer: ConsensusAnalyzer (Pillar 4)
        """
        self._seed: int = _RANDOM_SEED
        self.scorer = scorer
        self.consensus_analyzer = consensus_analyzer

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
    ) -> list[dict]:
        """추천 5 선출 (Hard Filter 3계층).

        흐름:
        1. 사용자 메모 forced_includes 우선 (최대 n_top까지 강제 포함)
        2. final_score 정렬 -> 상위 15 후보
        3. consensus_metrics.top10_count >= REC_TOP10_THR 통과
        4. filter_compliance >= median + 0.1 통과
        5. CI lower bound 정렬 -> top n_top
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

        # 5) CI lower bound 정렬 (Bayesian sigma 가용 시)
        def _ci_key(n: int) -> float:
            sc = float(scores.get(n, 0.0))
            sig = None
            if isinstance(bayesian_sigma, dict):
                sig = bayesian_sigma.get(n, bayesian_sigma.get(str(n)))
            return -_ci_lower_estimate(sc, sig)  # 내림차순 정렬 위해 음수

        f_pass.sort(key=_ci_key)

        # 부족 시 c_pass -> candidates 순으로 보충
        need = n_top - len(result)
        picked = list(f_pass[:need])
        if len(picked) < need:
            for n in c_pass:
                if n in picked:
                    continue
                picked.append(n)
                if len(picked) >= need:
                    break
        if len(picked) < need:
            for n in candidates:
                if n in picked:
                    continue
                picked.append(n)
                if len(picked) >= need:
                    break

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

        # 4) GNN veto 보강 (가용 시)
        gnn_set = gnn_strong_set or set()
        if gnn_set:
            # f_pass에 우선 GNN strong 포함된 번호를 앞으로
            f_pass.sort(key=lambda n: (n not in gnn_set, scores.get(n, 0.0)))

        # 5) 보완 우선순위: f_pass -> c_pass -> low_candidates
        need = n_exc - len(result)
        for n in f_pass:
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

        if len(result) < n_exc:
            for n in c_pass:
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

        if len(result) < n_exc:
            for n in low_candidates:
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
        n_top: int = 5,
        n_exc: int = 10,
        draws_so_far: list[dict] | None = None,
        bayesian_sigma: dict[int, float] | None = None,
        gnn_strong_set: set[int] | None = None,
        filter_compliance_override: np.ndarray | dict | None = None,
    ) -> dict:
        """추천 5 + 제외 10 + Hard Filter 3계층 통합 진입점.

        흐름:
        1. ConsensusAnalyzer로 Pillar 4 메트릭 산출
        2. NumberScorer로 4 Pillar 점수 (final_score) 산출
        3. filter_compliance 추출 (filter_stats_result 또는 override)
        4. regression_rules_output 추출 (predictor_pipeline_outputs.regression.tier3_rules)
        5. select_recommendations + select_exclusions
        """
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

        # 5) 추천 + 제외
        recommendations = self.select_recommendations(
            scores=scores,
            consensus_metrics=consensus_metrics,
            filter_compliance=comp,
            expert_memo=expert_memo,
            n_top=n_top,
            bayesian_sigma=bayesian_sigma,
        )
        exclusions = self.select_exclusions(
            scores=scores,
            consensus_metrics=consensus_metrics,
            filter_compliance=comp,
            regression_rules_output=regr_rules,
            expert_memo=expert_memo,
            n_exc=n_exc,
            gnn_strong_set=gnn_strong_set,
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
