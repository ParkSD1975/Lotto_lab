"""Stage 3-D — 50회차 walk-forward RecommendationBacktest.

단일 진실 공급원: docs/MASTER_PLAN.md (Stage 3, 50회차 백테스트).
사용자 결정 #7: 50회차 백테스트 + 메타러너 동적 가중치 갱신.

흐름:
    run(draws):
        for t in last_window_rounds:
            history = draws[t+1:]                # t 회차 시점까지의 history
            actual  = draws[t]["numbers"]        # 정답
            scores, recs, excs = recommend(history)
            hit_rec = |recs ∩ actual|
            hit_exc = |excs ∩ actual|

    compute_pillar_contributions(per_round_details):
        Pillar별 hit 기여도 (SHAP-style attribution)

    update_pillar_weights(scorer, backtest_result):
        scorer.update_weights_from_backtest()로 위임

    safety_check(backtest_result):
        평균 hit 임계 미달 시 경고 + 임계값 강화 권고

성능 목표:
    추천 5 평균 hit ≥ 2~3, 제외 10 평균 hit ≤ 0~1
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Any

import numpy as np

# 직접 실행 (python validation/recommendation_backtest.py) 시
# langchain-backend 루트를 sys.path에 추가하여 models.* import 가능 보장.
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

try:
    import config  # type: ignore
    _RANDOM_SEED = int(getattr(config, "RANDOM_SEED", 42))
    _BACKTEST_WIN = int(getattr(config, "RECOMMENDATION_BACKTEST_WINDOW", 50))
except Exception:
    _RANDOM_SEED = 42
    _BACKTEST_WIN = 50

try:
    from models.number_scorer import NumberScorer  # type: ignore
except Exception:
    try:
        from number_scorer import NumberScorer  # type: ignore
    except Exception:
        NumberScorer = None  # type: ignore

try:
    from models.number_recommender import NumberRecommender  # type: ignore
except Exception:
    try:
        from number_recommender import NumberRecommender  # type: ignore
    except Exception:
        NumberRecommender = None  # type: ignore

try:
    from models.consensus_analyzer import ConsensusAnalyzer  # type: ignore
except Exception:
    try:
        from consensus_analyzer import ConsensusAnalyzer  # type: ignore
    except Exception:
        ConsensusAnalyzer = None  # type: ignore


# 안전 장치 임계값
_SAFETY_REC_HIT_MIN = 1.5   # 추천 5 평균 hit 하한
_SAFETY_EXC_HIT_MAX = 2.0   # 제외 10 평균 hit 상한
_SAFETY_BOT15_BUMP = 1      # 제외 임계값 강화 권고 폭 (4 -> 5)


# ──────────────────────────────────────────────────────────────────────
# 유틸
# ──────────────────────────────────────────────────────────────────────
def _safe_int_list(seq: Any) -> list[int]:
    """1~45 범위 정수만 추출한 list."""
    out: list[int] = []
    if not isinstance(seq, (list, tuple, set, frozenset)):
        return out
    for v in seq:
        try:
            iv = int(v)
        except Exception:
            continue
        if 1 <= iv <= 45:
            out.append(iv)
    return out


def _hit_count(picks: list[int], actual: list[int]) -> int:
    """추천/제외 번호 vs 실제 출현 번호 교집합 크기."""
    return len(set(picks) & set(actual))


# ──────────────────────────────────────────────────────────────────────
# RecommendationBacktest
# ──────────────────────────────────────────────────────────────────────
class RecommendationBacktest:
    """50회차 walk-forward 백테스트 + Pillar 가중치 동적 갱신."""

    def __init__(
        self,
        scorer: "NumberScorer | None" = None,
        recommender: "NumberRecommender | None" = None,
        window: int = 50,
    ):
        """외부 주입 또는 lazy 초기화.

        Args:
            scorer     : NumberScorer (4 Pillar Ridge)
            recommender: NumberRecommender (Hard Filter 3계층)
            window     : 백테스트 회차 수 (default 50)
        """
        self._seed: int = _RANDOM_SEED
        self.window: int = int(window) if window > 0 else _BACKTEST_WIN

        self.scorer = scorer
        self.recommender = recommender

        if self.scorer is None and NumberScorer is not None:
            try:
                self.scorer = NumberScorer()
            except Exception as e:
                print(f"[RecommendationBacktest] NumberScorer init skip: {e}")
                self.scorer = None

        if self.recommender is None and NumberRecommender is not None:
            try:
                self.recommender = NumberRecommender(scorer=self.scorer)
            except Exception as e:
                print(f"[RecommendationBacktest] NumberRecommender init skip: {e}")
                self.recommender = None

    # ------------------------------------------------------------------
    # walk-forward 백테스트
    # ------------------------------------------------------------------
    def run(
        self,
        draws: list[dict],
        ensemble: Any = None,
        predictor_pipeline: Any = None,
        retrain_every: int = 0,
        expert_memo: dict | None = None,
        n_top: int = 5,
        n_exc: int = 10,
    ) -> dict:
        """walk-forward 50회차 백테스트.

        Args:
            draws             : 전체 회차 list[dict] (최신순, draws[0]가 가장 최근)
            ensemble          : LottoEnsemble 인스턴스 (Pillar 1)
            predictor_pipeline: PredictorPipeline (Pillar 2/3)
            retrain_every     : 0이면 한 번 학습 후 추론만, N>0이면 N회차마다 재학습
            expert_memo       : 사용자 메모 (forced_includes/excludes)
            n_top             : 추천 수 (default 5)
            n_exc             : 제외 수 (default 10)

        Returns:
            {
              n_rounds_evaluated, rec_hits_per_round, exc_hits_per_round,
              avg_rec_hit, avg_exc_hit, pillar_contributions,
              exclude_reason_distribution, memo_hit_summary, per_round_details
            }
        """
        if not isinstance(draws, list) or len(draws) < self.window + 1:
            return {
                "n_rounds_evaluated": 0,
                "rec_hits_per_round": [],
                "exc_hits_per_round": [],
                "avg_rec_hit": 0.0,
                "avg_exc_hit": 0.0,
                "pillar_contributions": {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0},
                "exclude_reason_distribution": {},
                "memo_hit_summary": None,
                "per_round_details": [],
                "error": f"insufficient draws ({len(draws) if isinstance(draws, list) else 0} < window+1)",
            }

        rec_hits: list[int] = []
        exc_hits: list[int] = []
        per_round: list[dict] = []
        reason_dist: dict[str, int] = {}

        memo_inc_hits = 0
        memo_exc_hits = 0
        memo_inc_total = 0
        memo_exc_total = 0
        memo_inc_set = set(_safe_int_list(expert_memo.get("forced_includes"))) if isinstance(expert_memo, dict) else set()
        memo_exc_set = set(_safe_int_list(expert_memo.get("forced_excludes"))) if isinstance(expert_memo, dict) else set()

        # walk-forward: t는 draws[0]부터 window-1까지 (가장 최근 window 회차 평가)
        for t in range(self.window):
            actual = _safe_int_list(draws[t].get("numbers", []))
            if len(actual) != 6:
                # 회차 데이터 결손 — skip
                continue

            history = draws[t + 1:]  # t 시점 이전 history
            if not history:
                continue

            # retrain_every>0 시 N회차마다 scorer 재학습 (스텁: smoke 환경에서 비활성)
            if retrain_every > 0 and (t % retrain_every == 0) and self.scorer is not None:
                # 실제 운영에선 history로 4 Pillar 산출 + train_meta 호출.
                # 본 구현은 외부 학습 파이프라인을 권장 (시간 비용).
                pass

            # Pillar 4 입력: 11 base rankings 산출 (ensemble 가용 시)
            rankings = self._build_rankings(ensemble, history)

            # Pillar 1 입력: ensemble.predict 결과
            ens_probs = self._extract_ensemble_probs(ensemble, history)

            # Pillar 2/3 입력: predictor_pipeline.predict_all
            pp_outputs = self._extract_predictor_outputs(predictor_pipeline, history)

            # filter_stats_result는 pp_outputs에서 추출 시도
            filter_stats = self._extract_filter_stats(pp_outputs)

            # recommend
            rec_out = self._recommend_one(
                final_probs=ens_probs,
                filter_stats_result=filter_stats,
                predictor_pipeline_outputs=pp_outputs,
                rankings=rankings,
                expert_memo=expert_memo,
                draws_so_far=history,
                n_top=n_top,
                n_exc=n_exc,
            )

            recs = [int(r["number"]) for r in rec_out.get("recommendations", [])]
            excs = [int(e["number"]) for e in rec_out.get("exclusions", [])]
            h_rec = _hit_count(recs, actual)
            h_exc = _hit_count(excs, actual)
            rec_hits.append(h_rec)
            exc_hits.append(h_exc)

            # exclude_reason 분포
            for e in rec_out.get("exclusions", []):
                rkey = str(e.get("exclude_reason", "unknown"))
                reason_dist[rkey] = reason_dist.get(rkey, 0) + 1

            # 메모 hit 추적
            if memo_inc_set:
                memo_inc_total += 1
                if memo_inc_set & set(actual):
                    memo_inc_hits += 1
            if memo_exc_set:
                memo_exc_total += 1
                if not (memo_exc_set & set(actual)):
                    memo_exc_hits += 1  # 제외가 출현 안 했으면 적중

            # per_round_details: Pillar 매트릭스 + actual + recs/excs (기여도 계산용)
            pillars_mat = self._compute_pillars_matrix(
                ens_probs=ens_probs,
                filter_stats=filter_stats,
                pp_outputs=pp_outputs,
                rankings=rankings,
                history=history,
            )
            per_round.append({
                "round_index": int(t),
                "round": int(draws[t].get("round", -1)) if isinstance(draws[t].get("round"), int) else -1,
                "actual": actual,
                "recommendations": recs,
                "exclusions": excs,
                "rec_hit": int(h_rec),
                "exc_hit": int(h_exc),
                "pillars": pillars_mat,  # (45, 4) ndarray
                "scores_top5": [
                    (int(r["number"]), float(r.get("score", 0.0)))
                    for r in rec_out.get("recommendations", [])
                ],
            })

        n_eval = len(rec_hits)
        avg_rec = float(np.mean(rec_hits)) if rec_hits else 0.0
        avg_exc = float(np.mean(exc_hits)) if exc_hits else 0.0

        pillar_contrib = self.compute_pillar_contributions(per_round)

        memo_summary: dict | None = None
        if memo_inc_total > 0 or memo_exc_total > 0:
            memo_summary = {
                "forced_includes": sorted(memo_inc_set),
                "forced_excludes": sorted(memo_exc_set),
                "inc_rounds_with_hit": int(memo_inc_hits),
                "inc_rounds_total": int(memo_inc_total),
                "inc_hit_rate": float(memo_inc_hits / memo_inc_total) if memo_inc_total > 0 else 0.0,
                "exc_rounds_avoided": int(memo_exc_hits),
                "exc_rounds_total": int(memo_exc_total),
                "exc_avoid_rate": float(memo_exc_hits / memo_exc_total) if memo_exc_total > 0 else 0.0,
            }

        return {
            "n_rounds_evaluated": int(n_eval),
            "rec_hits_per_round": list(rec_hits),
            "exc_hits_per_round": list(exc_hits),
            "avg_rec_hit": float(avg_rec),
            "avg_exc_hit": float(avg_exc),
            "pillar_contributions": pillar_contrib,
            "exclude_reason_distribution": dict(reason_dist),
            "memo_hit_summary": memo_summary,
            "per_round_details": per_round,
        }

    # ------------------------------------------------------------------
    # 보조: rankings/probs 추출
    # ------------------------------------------------------------------
    @staticmethod
    def _build_rankings(ensemble: Any, history: list[dict]) -> dict[str, list[int]]:
        """11 base rankings 추출. ensemble 미가용 시 빈 dict."""
        if ensemble is None:
            return {}
        try:
            pred = ensemble.predict(history)
            contribs = pred.get("model_contributions") if isinstance(pred, dict) else None
            if not isinstance(contribs, dict):
                return {}
            rankings: dict[str, list[int]] = {}
            for name, num_to_p in contribs.items():
                if not isinstance(num_to_p, dict):
                    continue
                pairs = [(n, float(num_to_p.get(n, num_to_p.get(str(n), 0.0)))) for n in range(1, 46)]
                pairs.sort(key=lambda kv: kv[1], reverse=True)
                rankings[str(name)] = [int(n) for n, _ in pairs]
            return rankings
        except Exception as e:
            print(f"[RecommendationBacktest] _build_rankings skip: {e}")
            return {}

    @staticmethod
    def _extract_ensemble_probs(ensemble: Any, history: list[dict]) -> dict[int, float]:
        """ensemble.predict 결과의 probabilities 추출. None 시 uniform fallback."""
        if ensemble is None:
            return {n: 1.0 / 45.0 for n in range(1, 46)}
        try:
            pred = ensemble.predict(history)
            probs = pred.get("probabilities") if isinstance(pred, dict) else None
            if isinstance(probs, dict) and probs:
                out: dict[int, float] = {}
                for n in range(1, 46):
                    v = probs.get(n, probs.get(str(n), 0.0))
                    try:
                        out[n] = float(v)
                    except Exception:
                        out[n] = 0.0
                s = sum(out.values())
                if s > 0:
                    return {n: v / s for n, v in out.items()}
                return {n: 1.0 / 45.0 for n in range(1, 46)}
        except Exception as e:
            print(f"[RecommendationBacktest] _extract_ensemble_probs skip: {e}")
        return {n: 1.0 / 45.0 for n in range(1, 46)}

    @staticmethod
    def _extract_predictor_outputs(predictor_pipeline: Any, history: list[dict]) -> dict:
        """predictor_pipeline.predict_all() 호출."""
        if predictor_pipeline is None:
            return {}
        try:
            return predictor_pipeline.predict_all(history) or {}
        except Exception as e:
            print(f"[RecommendationBacktest] _extract_predictor_outputs skip: {e}")
            return {}

    @staticmethod
    def _extract_filter_stats(pp_outputs: dict) -> list[dict]:
        """predictor_pipeline 출력에서 filter_stats list 추출."""
        if not isinstance(pp_outputs, dict):
            return []
        # 다양한 출처 시도
        for key in ("filter_stats", "phase2_filter_stats", "phase2"):
            v = pp_outputs.get(key)
            if isinstance(v, list):
                return [d for d in v if isinstance(d, dict)]
            if isinstance(v, dict):
                items = list(v.values())
                if items and all(isinstance(x, dict) for x in items):
                    return items
        return []

    # ------------------------------------------------------------------
    # recommend 단일 호출
    # ------------------------------------------------------------------
    def _recommend_one(
        self,
        final_probs: dict[int, float],
        filter_stats_result: list[dict],
        predictor_pipeline_outputs: dict,
        rankings: dict[str, list[int]],
        expert_memo: dict | None,
        draws_so_far: list[dict],
        n_top: int,
        n_exc: int,
    ) -> dict:
        """recommender.recommend() 호출. 미가용 시 score 기반 fallback."""
        if self.recommender is not None:
            try:
                return self.recommender.recommend(
                    final_probs=final_probs,
                    filter_stats_result=filter_stats_result,
                    predictor_pipeline_outputs=predictor_pipeline_outputs,
                    rankings=rankings,
                    expert_memo=expert_memo,
                    n_top=n_top,
                    n_exc=n_exc,
                    draws_so_far=draws_so_far,
                )
            except Exception as e:
                print(f"[RecommendationBacktest] recommend fail, fallback: {e}")

        # fallback: probs 정렬만 사용
        items = sorted(final_probs.items(), key=lambda kv: kv[1], reverse=True)
        recs = [{"number": int(n), "score": float(p)} for n, p in items[:n_top]]
        excs = [
            {"number": int(n), "score": float(p), "exclude_reason": "fallback_low_prob",
             "force_exclude": False}
            for n, p in items[-n_exc:]
        ]
        return {"recommendations": recs, "exclusions": excs,
                "hard_filter_summary": {}, "metadata": {}}

    # ------------------------------------------------------------------
    # Pillar 매트릭스 (per_round_details 저장용)
    # ------------------------------------------------------------------
    def _compute_pillars_matrix(
        self,
        ens_probs: dict[int, float],
        filter_stats: list[dict],
        pp_outputs: dict,
        rankings: dict[str, list[int]],
        history: list[dict],
    ) -> np.ndarray:
        """4 Pillar (45, 4) 매트릭스 계산. scorer 미가용 시 zeros."""
        if self.scorer is None:
            return np.zeros((45, 4), dtype=np.float64)

        # Pillar 4 metrics
        consensus_metrics: dict[int, dict] = {}
        if self.recommender is not None and self.recommender.consensus_analyzer is not None and rankings:
            try:
                consensus_metrics = self.recommender.consensus_analyzer.compute_metrics(rankings)
            except Exception:
                consensus_metrics = {}

        try:
            mat = self.scorer.compute_4pillars(
                ensemble_probs=ens_probs,
                filter_stats_result=filter_stats,
                predictor_pipeline_outputs=pp_outputs,
                consensus_metrics=consensus_metrics,
                draws_so_far=history,
            )
            return np.asarray(mat, dtype=np.float64)
        except Exception as e:
            print(f"[RecommendationBacktest] _compute_pillars_matrix skip: {e}")
            return np.zeros((45, 4), dtype=np.float64)

    # ------------------------------------------------------------------
    # Pillar 기여도 측정 (SHAP-style attribution)
    # ------------------------------------------------------------------
    def compute_pillar_contributions(
        self,
        per_round_details: list[dict],
    ) -> dict[int, float]:
        """각 Pillar의 hit 기여도 (actual 번호의 Pillar 평균 - 전체 Pillar 평균).

        값이 양수일수록 해당 Pillar가 actual 번호를 잘 가리킴 (기여 ↑).
        값이 음수면 Pillar가 actual을 회피 — 가중치 ↓ 후보.

        Returns:
            {1: contrib_1, 2: contrib_2, 3: contrib_3, 4: contrib_4}
        """
        if not isinstance(per_round_details, list) or not per_round_details:
            return {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0}

        contrib_sum = np.zeros(4, dtype=np.float64)
        n_used = 0
        for r in per_round_details:
            pillars = r.get("pillars") if isinstance(r, dict) else None
            actual = r.get("actual") if isinstance(r, dict) else None
            if pillars is None or actual is None:
                continue
            try:
                arr = np.asarray(pillars, dtype=np.float64)
            except Exception:
                continue
            if arr.shape != (45, 4):
                continue
            idx = [int(a) - 1 for a in actual if isinstance(a, int) and 1 <= a <= 45]
            if not idx:
                continue
            hit_mean = arr[idx].mean(axis=0)
            all_mean = arr.mean(axis=0)
            contrib_sum += (hit_mean - all_mean)
            n_used += 1

        if n_used == 0:
            return {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0}

        avg = contrib_sum / float(n_used)
        return {
            1: float(avg[0]),
            2: float(avg[1]),
            3: float(avg[2]),
            4: float(avg[3]),
        }

    # ------------------------------------------------------------------
    # Pillar 가중치 자동 갱신
    # ------------------------------------------------------------------
    def update_pillar_weights(
        self,
        scorer: "NumberScorer",
        backtest_result: dict,
    ) -> dict:
        """hit 기여 큰 Pillar -> 가중치 ↑, 작거나 음의 기여 -> ↓.

        scorer.update_weights_from_backtest()로 위임.

        Args:
            scorer         : NumberScorer (pillar_weights 갱신 대상)
            backtest_result: run() 결과

        Returns:
            {success, n_rounds_used, hit_contrib, new_pillar_weights}
        """
        if scorer is None or not hasattr(scorer, "update_weights_from_backtest"):
            return {"success": False, "error": "scorer unavailable or missing update_weights_from_backtest"}

        per_round = backtest_result.get("per_round_details") if isinstance(backtest_result, dict) else None
        if not isinstance(per_round, list) or not per_round:
            return {"success": False, "error": "no per_round_details in backtest_result"}

        rounds_payload = []
        for r in per_round:
            if not isinstance(r, dict):
                continue
            pillars = r.get("pillars")
            actual = r.get("actual")
            if pillars is None or actual is None:
                continue
            rounds_payload.append({"pillars": pillars, "actual": actual})

        if not rounds_payload:
            return {"success": False, "error": "no valid rounds"}

        return scorer.update_weights_from_backtest({
            "rounds": rounds_payload,
            "window": self.window,
        })

    # ------------------------------------------------------------------
    # 안전 장치
    # ------------------------------------------------------------------
    def safety_check(self, backtest_result: dict) -> dict:
        """평균 hit 임계 미달 시 경고 + 임계값 강화 권고.

        규칙:
            avg_rec_hit <= 1.5: 경고 + Pillar 가중치 큰 변화 권고
            avg_exc_hit >= 2.0: 임계값 강화 권고 (consensus.bottom15 4 -> 5)

        Returns:
            {warnings: [str], adjustments: {...}, safe: bool}
        """
        warnings: list[str] = []
        adjustments: dict[str, Any] = {}

        if not isinstance(backtest_result, dict):
            return {"warnings": ["invalid backtest_result"], "adjustments": {}, "safe": False}

        avg_rec = float(backtest_result.get("avg_rec_hit", 0.0))
        avg_exc = float(backtest_result.get("avg_exc_hit", 0.0))
        n_eval = int(backtest_result.get("n_rounds_evaluated", 0))

        if n_eval <= 0:
            return {"warnings": ["no rounds evaluated"], "adjustments": {}, "safe": False}

        if avg_rec <= _SAFETY_REC_HIT_MIN:
            warnings.append(
                f"avg_rec_hit {avg_rec:.3f} <= {_SAFETY_REC_HIT_MIN} "
                f"(rec window={n_eval}) - recommend large pillar weight update"
            )
            adjustments["pillar_weights_blend"] = "increase_new_weight_share"

        if avg_exc >= _SAFETY_EXC_HIT_MAX:
            new_thr = 4 + _SAFETY_BOT15_BUMP
            warnings.append(
                f"avg_exc_hit {avg_exc:.3f} >= {_SAFETY_EXC_HIT_MAX} "
                f"(exc window={n_eval}) - recommend tighten exc threshold to bottom15 >= {new_thr}"
            )
            adjustments["exc_bot15_threshold"] = int(new_thr)

        # Pillar 기여도 음수 다수 시 추가 경고
        contribs = backtest_result.get("pillar_contributions") or {}
        if isinstance(contribs, dict):
            neg_pillars = [p for p, v in contribs.items() if isinstance(v, (int, float)) and v < 0]
            if len(neg_pillars) >= 2:
                warnings.append(
                    f"pillars with negative contribution: {sorted(neg_pillars)} "
                    f"- consider down-weighting"
                )
                adjustments["negative_contrib_pillars"] = sorted(neg_pillars)

        safe = (len(warnings) == 0)
        return {"warnings": warnings, "adjustments": adjustments, "safe": bool(safe)}

    # ------------------------------------------------------------------
    # 결과 보고서 (ASCII)
    # ------------------------------------------------------------------
    def report(self, backtest_result: dict) -> str:
        """ASCII 형식 텍스트 보고서."""
        if not isinstance(backtest_result, dict):
            return "[RecommendationBacktest] invalid result"

        n_eval = int(backtest_result.get("n_rounds_evaluated", 0))
        avg_rec = float(backtest_result.get("avg_rec_hit", 0.0))
        avg_exc = float(backtest_result.get("avg_exc_hit", 0.0))
        contribs = backtest_result.get("pillar_contributions") or {}
        reason_dist = backtest_result.get("exclude_reason_distribution") or {}
        memo_summary = backtest_result.get("memo_hit_summary")

        lines: list[str] = []
        bar = "=" * 60
        lines.append(bar)
        lines.append("RecommendationBacktest Report")
        lines.append(bar)
        lines.append(f"  rounds evaluated   : {n_eval}")
        lines.append(f"  avg recommend hit  : {avg_rec:.4f} (target >= 2.0)")
        lines.append(f"  avg exclusion hit  : {avg_exc:.4f} (target <= 1.0)")

        lines.append("-" * 60)
        lines.append("  pillar contributions (hit_mean - all_mean):")
        for pid in (1, 2, 3, 4):
            v = float(contribs.get(pid, 0.0))
            sign = "+" if v >= 0 else ""
            lines.append(f"    pillar_{pid}: {sign}{v:.4f}")

        lines.append("-" * 60)
        lines.append("  exclude_reason distribution:")
        if reason_dist:
            for k, v in sorted(reason_dist.items(), key=lambda kv: -int(kv[1])):
                lines.append(f"    {str(k):<28s} : {int(v)}")
        else:
            lines.append("    (none)")

        if memo_summary is not None:
            lines.append("-" * 60)
            lines.append("  memo hit summary:")
            lines.append(f"    forced_includes  : {memo_summary.get('forced_includes')}")
            lines.append(f"    inc_hit_rate     : {float(memo_summary.get('inc_hit_rate', 0.0)):.4f}")
            lines.append(f"    forced_excludes  : {memo_summary.get('forced_excludes')}")
            lines.append(f"    exc_avoid_rate   : {float(memo_summary.get('exc_avoid_rate', 0.0)):.4f}")

        # safety check 출력
        sc = self.safety_check(backtest_result)
        lines.append("-" * 60)
        lines.append(f"  safety_check.safe : {sc.get('safe')}")
        if sc.get("warnings"):
            lines.append("  warnings:")
            for w in sc["warnings"]:
                lines.append(f"    - {w}")
        adj = sc.get("adjustments") or {}
        if adj:
            lines.append("  adjustments:")
            for k, v in adj.items():
                lines.append(f"    {k} : {v}")

        lines.append(bar)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Supabase 적재 (recommendation_backtest_runs 테이블)
    # ------------------------------------------------------------------
    def save_backtest_to_db(
        self,
        backtest_result: dict,
        supabase_client: Any = None,
    ) -> dict:
        """50회차 백테스트 결과를 recommendation_backtest_runs 테이블에 INSERT.

        Args:
            backtest_result: run() 결과
            supabase_client: Supabase 클라이언트 (None이면 get_client 호출)

        Returns:
            {success: bool, rows_inserted: int, error: str?}

        Supabase 테이블 스키마 (실제):
            run_id (uuid, not null) — 각 백테스트 실행 ID
            target_round (int, not null)
            recommendations (int[], not null) — 추천 번호 배열
            exclusions (int[], not null) — 제외 번호 배열
            actual_numbers (int[])
            hit_count (int, default 0) — recommendations 중 실제 적중 개수
            exclusion_correct_count (int, default 0) — exclusions 중 실제 미출 개수
            pillar_scores (jsonb) — 4 Pillar 점수
            pillar_shap (jsonb) — SHAP 기여도
            wall_time_ms (float)
            memory_mb (float)
            forced_includes/excludes (int[])
            notes (text)
            created_at (timestamptz)
        """
        if supabase_client is None:
            try:
                from db.supabase_client import get_client
                supabase_client = get_client()
            except Exception as e:
                return {"success": False, "rows_inserted": 0, "error": f"supabase unavailable: {e}"}

        if not isinstance(backtest_result, dict):
            return {"success": False, "rows_inserted": 0, "error": "invalid backtest_result"}

        per_round = backtest_result.get("per_round_details") or []
        if not isinstance(per_round, list) or not per_round:
            return {"success": False, "rows_inserted": 0, "error": "no per_round_details"}

        pillar_contrib = backtest_result.get("pillar_contributions") or {}

        # 단일 run_id (이번 백테스트 실행 전체에 공통)
        import uuid
        run_id = str(uuid.uuid4())

        rows = []
        for r in per_round:
            if not isinstance(r, dict):
                continue
            target_round = r.get("round")
            if not isinstance(target_round, int) or target_round <= 0:
                continue

            recs = r.get("recommendations", [])
            excs = r.get("exclusions", [])
            actual = r.get("actual", [])
            rec_hit = int(r.get("rec_hit", 0))
            exc_hit = int(r.get("exc_hit", 0))

            # pillar_shap: 4 Pillar SHAP 기여도
            pillar_shap_val = {
                "ENS": round(float(pillar_contrib.get(1, 0.0)), 4),
                "FLT": round(float(pillar_contrib.get(2, 0.0)), 4),
                "STA": round(float(pillar_contrib.get(3, 0.0)), 4),
                "CNS": round(float(pillar_contrib.get(4, 0.0)), 4),
            }

            # pillar_scores: 실제 Pillar 매트릭스에서 추출 (옵션)
            # 여기선 스텁으로 None 처리 (추후 pillars 매트릭스 활용)
            pillar_scores_val = None

            row = {
                "run_id": run_id,
                "target_round": target_round,
                "recommendations": recs,
                "exclusions": excs,
                "actual_numbers": actual if actual else None,
                "hit_count": rec_hit,
                "exclusion_correct_count": len(excs) - exc_hit,  # 제외가 정답 회피 개수
                "pillar_scores": pillar_scores_val,
                "pillar_shap": pillar_shap_val,
            }
            rows.append(row)

        if not rows:
            return {"success": False, "rows_inserted": 0, "error": "no valid rounds to insert"}

        try:
            # 일괄 INSERT (기존 데이터 삭제 안 함 — run_id가 매번 새로 생성되므로 중복 없음)
            supabase_client.table("recommendation_backtest_runs").insert(rows).execute()
            return {"success": True, "rows_inserted": len(rows), "run_id": run_id}
        except Exception as e:
            return {"success": False, "rows_inserted": 0, "error": str(e)}


# ──────────────────────────────────────────────────────────────────────
# Smoke main
# ──────────────────────────────────────────────────────────────────────
def _build_fake_draws(n_rounds: int, seed: int) -> list[dict]:
    """가짜 회차 list[dict] 생성 (최신순)."""
    rng = np.random.default_rng(seed)
    draws: list[dict] = []
    base_round = 1100
    for i in range(n_rounds):
        nums = sorted(rng.choice(np.arange(1, 46), size=6, replace=False).tolist())
        draws.append({
            "round": int(base_round - i),
            "numbers": [int(n) for n in nums],
        })
    return draws


class _FakeEnsemble:
    """smoke용 가짜 ensemble — 11 base contributions + probabilities 반환."""

    def __init__(self, seed: int = 42):
        self._rng = np.random.default_rng(seed)
        self._base_models = [
            "xgboost", "catboost", "tabnet",
            "cnn", "gnn", "markov",
            "autoencoder", "tft", "nbeats",
            "mhn", "bayesian_nn",
        ]

    def predict(self, draws: list[dict]) -> dict:
        contribs: dict[str, dict[int, float]] = {}
        for name in self._base_models:
            p = self._rng.dirichlet(np.ones(45) * 0.6)
            contribs[name] = {n: float(p[n - 1]) for n in range(1, 46)}
        # 통합 probs (균등 평균)
        probs = {n: 0.0 for n in range(1, 46)}
        for name, d in contribs.items():
            for n, v in d.items():
                probs[n] += v
        s = sum(probs.values())
        if s > 0:
            probs = {n: v / s for n, v in probs.items()}
        return {"probabilities": probs, "model_contributions": contribs, "evidence": {}}


class _FakePredictorPipeline:
    """smoke용 가짜 predictor — phase1/regression 출력."""

    def __init__(self, seed: int = 42):
        self._rng = np.random.default_rng(seed + 1)

    def predict_all(self, draws: list[dict]) -> dict:
        # 최근 30회차 빈도 기반 hot/cold
        recent = draws[:30] if isinstance(draws, list) else []
        freq = np.zeros(45, dtype=np.int64)
        for d in recent:
            for n in d.get("numbers", []) or []:
                if isinstance(n, int) and 1 <= n <= 45:
                    freq[n - 1] += 1
        order = np.argsort(-freq) + 1
        hot_pool = [int(n) for n in order[:8]]
        cold_pool = [int(n) for n in order[-8:]]
        missing = [int(n) for n in range(1, 46) if freq[n - 1] == 0]

        # filter_stats 가짜 (NumberScorer Pillar 2 입력)
        filter_stats = [
            {"key": "total_sum",  "ml_recommendation": {"min": 100, "median": 132, "max": 165}},
            {"key": "tail_sum",   "ml_recommendation": {"min": 15, "median": 20, "max": 28}},
            {"key": "ac_value",   "ml_recommendation": {"min": 5, "median": 8, "max": 10}},
            {"key": "odd_even",   "ml_recommendation": {"top_class": 3}},
            {"key": "low_high",   "ml_recommendation": {"top_class": 3}},
            {"key": "hot_cold",
             "ml_recommendation": {"per_category": {"hot_pool": hot_pool, "cold_pool": cold_pool}}},
            {"key": "carryover",  "ml_recommendation": {}},
            {"key": "neighbor_count", "ml_recommendation": {}},
            {"key": "missing_group",
             "ml_recommendation": {"per_category": {"missing_pool": missing}}},
        ]

        return {
            "phase1": {
                "hotcold": {"per_category": {"hot_pool": hot_pool, "cold_pool": cold_pool}},
                "missing_group": {"per_category": {"missing_pool": missing}},
            },
            "regression": {
                "tier1": {"active_N_set": hot_pool[:4]},
                "tier3_rules": {
                    "force_exclude": set(cold_pool[:2]),
                    "rule1_consecutive_n": [],
                    "rule1_recent": [],
                    "rule2_dead_lines": [
                        {"number": int(cold_pool[0]), "reason": "dead_carryover_lines"}
                    ],
                },
            },
            "filter_stats": filter_stats,
        }


def main() -> None:
    """smoke: 가짜 200회차 + scorer + recommender -> 50회차 백테스트 검증."""
    print("[RecommendationBacktest] smoke start")

    if NumberScorer is None or NumberRecommender is None:
        print("  WARN: NumberScorer or NumberRecommender unavailable")

    # 1. 가짜 데이터
    fake_draws = _build_fake_draws(n_rounds=200, seed=_RANDOM_SEED)
    print(f"  [1] fake_draws: {len(fake_draws)} rounds, latest round={fake_draws[0]['round']}")

    # 2. scorer + recommender
    scorer = NumberScorer() if NumberScorer is not None else None
    recommender = NumberRecommender(scorer=scorer) if NumberRecommender is not None else None

    # 3. fake ensemble + predictor pipeline
    fake_ens = _FakeEnsemble(seed=_RANDOM_SEED)
    fake_pp = _FakePredictorPipeline(seed=_RANDOM_SEED)

    # 4. 백테스트 실행
    bt = RecommendationBacktest(scorer=scorer, recommender=recommender, window=50)
    result = bt.run(
        draws=fake_draws,
        ensemble=fake_ens,
        predictor_pipeline=fake_pp,
        retrain_every=0,
        expert_memo=None,
    )

    print(f"\n  [2] n_rounds_evaluated = {result['n_rounds_evaluated']}")
    print(f"      avg_rec_hit        = {result['avg_rec_hit']:.4f}")
    print(f"      avg_exc_hit        = {result['avg_exc_hit']:.4f}")

    print(f"\n  [3] pillar_contributions:")
    for pid, v in result["pillar_contributions"].items():
        print(f"      pillar_{pid}: {v:+.4f}")

    print(f"\n  [4] exclude_reason_distribution:")
    for k, v in sorted(
        result["exclude_reason_distribution"].items(), key=lambda kv: -int(kv[1])
    ):
        print(f"      {k:<32s} : {v}")

    # 5. safety_check
    sc = bt.safety_check(result)
    print(f"\n  [5] safety_check.safe = {sc['safe']}")
    for w in sc.get("warnings", []) or []:
        print(f"      WARN: {w}")
    if sc.get("adjustments"):
        print(f"      adjustments: {sc['adjustments']}")

    # 6. update_pillar_weights
    if scorer is not None:
        upd = bt.update_pillar_weights(scorer, result)
        print(f"\n  [6] update_pillar_weights:")
        print(f"      success      : {upd.get('success')}")
        if upd.get("success"):
            print(f"      n_rounds_used: {upd.get('n_rounds_used')}")
            print(f"      hit_contrib  : {[round(c, 4) for c in upd.get('hit_contrib', [])]}")
            print(f"      new_weights  : {[round(w, 4) for w in upd.get('new_pillar_weights', [])]}")

    # 7. ASCII report
    print(f"\n  [7] report():\n")
    print(bt.report(result))

    # 8. 검증
    assert result["n_rounds_evaluated"] > 0, "must evaluate at least one round"
    assert result["n_rounds_evaluated"] <= 50, "cannot exceed window"
    assert len(result["rec_hits_per_round"]) == result["n_rounds_evaluated"]
    assert len(result["exc_hits_per_round"]) == result["n_rounds_evaluated"]
    assert isinstance(result["pillar_contributions"], dict)
    assert set(result["pillar_contributions"].keys()) == {1, 2, 3, 4}
    assert isinstance(sc, dict) and "safe" in sc and "warnings" in sc
    print("\n[RecommendationBacktest] smoke OK")


if __name__ == "__main__":
    main()
