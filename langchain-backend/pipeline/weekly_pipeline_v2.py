"""
weekly_pipeline_v2.py — Single Source of Truth 파이프라인

주 1회 (새 회차 업데이트 직후) 실행:
  1. 딥러닝 전체 분석 (앙상블 + P4 Top5 + P5 GNN Veto + P7 Meta + P8 CI)
  2. 결과를 6개 weekly_* 테이블에 저장
  3. 이전 회차 검증 (weekly_* + 기존 테이블 모두)

페이지들은 /api/v4/... 엔드포인트를 통해 이 테이블을 읽어 즉시 응답.
→ XAI 느림 문제 해결: 매번 딥러닝 재실행 없이 DB 조회만.
"""

import logging
import json
import traceback
from datetime import datetime, timezone

from db.supabase_client import get_client, fetch_all_draws
from models.ensemble import LottoEnsemble, CombinationGenerator, TASK_WEIGHTS as ENSEMBLE_TASK_WEIGHTS
from pipeline.sla_monitor import SLAMonitor, sync_sla_to_latency_log

# deep_analysis_v3.py 의 핵심 계산 함수들 임포트
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from routes.deep_analysis_v3 import (
    simulate_all_filters,
    get_model_filter_expectations,
    analyze_all_regressions,
    calc_stat_correction,
    # High-1: 4섹션 분석 함수 추가
    analyze_tail_detailed,
    analyze_number_band,
    analyze_magic_square,
    analyze_lotto_paper,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("WeeklyPipelineV2")


class WeeklyPipelineV2:
    """
    주간 딥러닝 파이프라인 v2 — weekly_* 6개 테이블에 결과 저장.

    사용:
        pipeline = WeeklyPipelineV2()
        result = pipeline.run(target_round=1234)
    """

    def __init__(self):
        self.supabase = get_client()
        self.ensemble = LottoEnsemble()

        # Master Plan Stage 1-4-E: predictor_pipeline 통합 (Phase 1~4 22 predictor)
        # 학습 산출물은 메모리 + saved_models/predictor_pipeline 캐시
        try:
            from predictors.predictor_pipeline import PredictorPipeline
            self.predictor_pipeline = PredictorPipeline(feature_dim=24)
        except Exception as e:
            logger.warning(f"  [WeeklyPipelineV2] predictor_pipeline init fail (skip): {e}")
            self.predictor_pipeline = None

        # [P3 PATCH] EMA 평활화 — 회차 간 가중치 변동 흡수
        # 근거: Lotto_lab_Root_Cause_Diagnosis.md (Finding #3)
        #       model_weights가 회차 간 거의 동일 (1222 == 1223) → 추론 시 갱신 안 됨
        # 패치 일자: 2026-05-11
        self._prev_weights: dict | None = None
        self._ema_alpha: float = 0.85  # 0.85 = 기존 85% + 신규 15% 반영

    # ──────────────────────────────────────────────────────────────────────────
    # 진입점
    # ──────────────────────────────────────────────────────────────────────────
    def run(self, target_round: int = None) -> dict:
        """파이프라인 실행."""
        logger.info("[WeeklyPipelineV2] 파이프라인 시작")
        start = datetime.now()

        try:
            draws = fetch_all_draws()
            if not draws:
                return {"success": False, "error": "이력 데이터 없음"}

            latest_round = draws[0]["round"]
            target = target_round or (latest_round + 1)
            logger.info(f"  target_round={target}, history={len(draws)}회차")

            # ── Phase A: 이전 회차 검증 ──────────────────────────────────────
            logger.info("[Phase A] 이전 회차 검증 시작...")
            verify_result = self._verify_previous(latest_round, draws)

            # ── Phase B: 딥러닝 전체 분석 ────────────────────────────────────
            # [데이터 누수 방지] target_round 이전 회차만 사용 (reviewer 권장)
            # 정상 운영(target = latest+1)은 영향 없음. backtest target 지정 시 누수 차단.
            draws = [d for d in draws if d.get("round") is not None and d["round"] < target]
            logger.info(f"  analysis draws (cutoff): {len(draws)}회차 (round < {target})")
            logger.info("[Phase B] 딥러닝 분석 실행 중...")
            analysis = self._run_analysis(draws, target)

            # ── Phase C: weekly_* 테이블 저장 ────────────────────────────────
            logger.info("[Phase C] weekly_* 테이블 저장 중...")
            save_result = self._save_to_weekly_tables(target, analysis)

            elapsed = round((datetime.now() - start).total_seconds(), 2)
            logger.info(f"[WeeklyPipelineV2] 완료 ({elapsed}초)")

            # ── Phase D: SLA Monitor → model_latency_log 동기화 ─────────────────
            logger.info("[Phase D] SLA Monitor 동기화 중...")
            try:
                sync_result = sync_sla_to_latency_log(
                    supabase_client=self.supabase,
                    recent_n=100,
                )
                logger.info(f"  [D] model_latency_log 동기화: {sync_result}")
            except Exception as e:
                logger.warning(f"  [D] SLA 동기화 실패 (무시): {e}")
                sync_result = {"success": False, "error": str(e)}

            return {
                "success":      True,
                "target_round": target,
                "elapsed":      elapsed,
                "verify":       verify_result,
                "save":         save_result,
                "sla_sync":     sync_result,
            }

        except Exception as e:
            traceback.print_exc()
            logger.error(f"[WeeklyPipelineV2] 오류: {e}")
            return {"success": False, "error": str(e)}

    # ──────────────────────────────────────────────────────────────────────────
    # Phase A: 이전 회차 검증
    # ──────────────────────────────────────────────────────────────────────────
    def _verify_previous(self, actual_round: int, draws: list) -> dict:
        """weekly_predictions / weekly_recommendations 채점 + 기존 테이블 업데이트."""
        try:
            draw_res = self.supabase.table("lotto_draws") \
                .select("numbers").eq("round", actual_round).execute()
            if not draw_res.data:
                logger.warning("  실제 당첨 정보 없음 → 검증 스킵")
                return {"skipped": True}

            actual = set(int(x) for x in draw_res.data[0]["numbers"])
            now_ts = datetime.now(timezone.utc).isoformat()

            # 1. weekly_predictions 채점
            wp_res = self.supabase.table("weekly_predictions") \
                .select("id, top_5, exclude_10") \
                .eq("target_round", actual_round).execute()
            for row in (wp_res.data or []):
                top5_hit  = len(actual & set(row.get("top_5") or []))
                excl_hit  = len(actual & set(row.get("exclude_10") or []))
                self.supabase.table("weekly_predictions").update({
                    "top5_hit_count":  top5_hit,
                    "excl_hit_count":  excl_hit,
                    "verified_at":     now_ts,
                    "actual_numbers":  sorted(actual),
                }).eq("id", row["id"]).execute()

            # 2. weekly_recommendations 채점
            wr_res = self.supabase.table("weekly_recommendations") \
                .select("id, number") \
                .eq("target_round", actual_round).execute()
            for row in (wr_res.data or []):
                hit = int(row.get("number") or 0) in actual
                self.supabase.table("weekly_recommendations").update({
                    "hit": hit, "verified_at": now_ts,
                }).eq("id", row["id"]).execute()

            # 3. weekly_filter_predictions 범위 검증
            actual_sum = sum(actual)
            wfp_res = self.supabase.table("weekly_filter_predictions") \
                .select("id, filter_key, ensemble_min, ensemble_max") \
                .eq("target_round", actual_round).execute()
            for row in (wfp_res.data or []):
                if row["filter_key"] == "sum":
                    in_range = (
                        row.get("ensemble_min") is not None
                        and row["ensemble_min"] <= actual_sum <= row["ensemble_max"]
                    )
                    self.supabase.table("weekly_filter_predictions").update({
                        "actual_value": actual_sum,
                        "in_range":     in_range,
                        "verified_at":  now_ts,
                    }).eq("id", row["id"]).execute()

            # 4. 기존 model_performance_log 업데이트 (하위 호환)
            perf_res = self.supabase.table("model_performance_log") \
                .select("id, predicted_numbers").eq("round", actual_round).execute()
            for row in (perf_res.data or []):
                hit = len(actual & set(row.get("predicted_numbers") or []))
                self.supabase.table("model_performance_log").update({
                    "actual_numbers": sorted(actual), "hit_count": hit,
                }).eq("id", row["id"]).execute()

            logger.info(f"  검증 완료 (actual={sorted(actual)})")
            return {"verified": True, "actual": sorted(actual)}

        except Exception as e:
            logger.warning(f"  검증 실패 (무시): {e}")
            return {"verified": False, "error": str(e)}

    # ──────────────────────────────────────────────────────────────────────────
    # Phase B: 딥러닝 전체 분석
    # ──────────────────────────────────────────────────────────────────────────
    def _run_analysis(self, draws: list, target_round: int) -> dict:
        """
        전체 분석 실행.

        [P3 PATCH] 추론 직전 ensemble 가중치 재계산 추가 (Finding #3).

        Returns dict with keys:
          prediction, contribs, xai, top5_result, excl_result,
          final_probs, range_analysis, regression_analysis, combinations,
          predictor_pipeline_outputs (Master Plan Stage 1-4-E 신설)
        """
        # ── [P3 PATCH] 추론 시점 ensemble 가중치 재계산 (EMA 평활화) ───────────
        # 근거: 회차별 model_performance_log 기반 동적 가중치 적용
        # EMA: 0.85 × 기존 + 0.15 × 신규 (큰 변동 흡수)
        # 패치 일자: 2026-05-11
        logger.info(f"  [P3] ensemble 가중치 재계산 (target_round={target_round})...")
        try:
            if hasattr(self.ensemble, "_update_meta_weights"):
                # _update_meta_weights(draws) — draws 인자 필수, self.weights에 저장 (반환 None)
                # P3 fix-1: 원본 P 문서가 인자 없는 호출로 가정했으나 실제 시그니처는 draws 받음
                ret = self.ensemble._update_meta_weights(draws)
                new_weights = ret if isinstance(ret, dict) else None
                if new_weights is None:
                    # 속성에서 직접 추출
                    new_weights = (
                        getattr(self.ensemble, "current_weights", None)
                        or getattr(self.ensemble, "weights", None)
                        or getattr(self.ensemble, "meta_weights", None)
                        or {}
                    )
                # EMA 평활화 적용 (2회차 이후)
                if self._prev_weights is not None and new_weights:
                    smoothed = {}
                    all_keys = set(self._prev_weights.keys()) | set(new_weights.keys())
                    for k in all_keys:
                        prev_v = float(self._prev_weights.get(k, 0.0) or 0.0)
                        new_v  = float(new_weights.get(k, 0.0) or 0.0)
                        smoothed[k] = self._ema_alpha * prev_v + (1 - self._ema_alpha) * new_v
                    total = sum(smoothed.values()) or 1.0
                    smoothed = {k: v / total for k, v in smoothed.items()}
                    # ensemble 속성 갱신 (다양한 이름 호환)
                    for attr in ("current_weights", "weights", "meta_weights"):
                        if hasattr(self.ensemble, attr):
                            setattr(self.ensemble, attr, smoothed)
                            break
                    self._prev_weights = smoothed
                    top3 = dict(sorted(smoothed.items(), key=lambda kv: -kv[1])[:3])
                    logger.info(f"  [P3] EMA weights top3: {top3}")
                else:
                    # 첫 회차 — EMA 미적용
                    self._prev_weights = new_weights or {}
                    top3 = dict(sorted((new_weights or {}).items(), key=lambda kv: -kv[1])[:3])
                    logger.info(f"  [P3] 초기 weights top3: {top3}")
            else:
                logger.warning("  [P3] ensemble._update_meta_weights() 없음 — 스킵")
        except Exception as e:
            logger.warning(f"  [P3] 가중치 갱신 실패 (기존 가중치 유지): {e}")
        # ── /P3 PATCH ──────────────────────────────────────────────────────────

        # ── B0. predictor_pipeline 학습/추론 (Master Plan Stage 1-4-E) ──────
        # Phase 1~4 22 predictor — filter_stats ml_recommendation 입력 제공
        predictor_pipeline_outputs = None
        if self.predictor_pipeline is not None:
            logger.info("  [B0] predictor_pipeline (Phase 1~4) 학습/추론...")
            try:
                if not self.predictor_pipeline._is_trained:
                    self.predictor_pipeline.train(draws, min_history=50)
                predictor_pipeline_outputs = self.predictor_pipeline.predict_all(draws)
            except Exception as e:
                logger.warning(f"  predictor_pipeline 실패 (fallback): {e}")
                predictor_pipeline_outputs = None

        # ── [B1] NumberRecommender 경로 (마스터 플랜 Stage 3-C) ─────────────
        logger.info("  [B1] NumberRecommender 경로...")

        # B1-A: contributions 추출
        result = self.ensemble.predict_with_task(draws, task="recommend_top")
        final_probs = result["probabilities"]
        contribs = result["model_contributions"]
        xai = result.get("xai_contributions", {})
        evidence = result.get("evidence", {})
        prediction = final_probs

        # B1-B: rankings (model별 1~45 순위)
        from models.model_rank_extractor import ModelRankExtractor
        extractor = ModelRankExtractor()
        rankings = extractor.extract_rankings(contribs)

        # B1-C: consensus_metrics
        from models.consensus_analyzer import ConsensusAnalyzer
        analyzer = ConsensusAnalyzer()
        consensus_metrics = analyzer.compute_metrics(rankings)

        # B1-D: bayesian_sigma (Stage 6-G까지 None fallback)
        bayesian_sigma = None

        # B1-E: 4 Pillar 점수
        from models.number_scorer import NumberScorer
        scorer = NumberScorer()
        scores = scorer.score_numbers(
            ensemble_probs=final_probs,
            filter_stats_result=predictor_pipeline_outputs,
            predictor_pipeline_outputs=predictor_pipeline_outputs,
            consensus_metrics=consensus_metrics,
            draws_so_far=draws[:20],
            bayesian_sigma=bayesian_sigma,
        )

        # B1-F: filter_compliance
        filter_compliance = self._compute_filter_compliance(
            predictor_pipeline_outputs, draws
        )

        # B1-G: expert_memo
        expert_memo = self._load_expert_memo(target_round)

        # B1-H: NumberRecommender 호출 (CRITICAL: draws_so_far + target_round 반드시 전달)
        from models.number_recommender import NumberRecommender
        recommender = NumberRecommender(scorer=scorer)
        recs = recommender.select_recommendations(
            scores=scores,
            consensus_metrics=consensus_metrics,
            filter_compliance=filter_compliance,
            expert_memo=expert_memo,
            n_top=5,
            bayesian_sigma=bayesian_sigma,
            target_round=target_round,    # Stage 6-D Plackett-Luce
            draws_so_far=draws,           # [P1] 빈도 페널티 활성화 — 절대 누락 금지
        )
        top_5 = [entry["number"] for entry in recs]

        # B1-I: 제외 10 (기존 유지)
        excl_result = self.ensemble.predict_exclusion_with_veto(draws)
        excl_10 = [e["number"] for e in excl_result.get("exclusions", [])][:10]

        final_probs = prediction

        # ── 2. stat_corrections 계산 ─────────────────────────────────────────
        logger.info("  [B2] 통계 보정값 계산...")
        try:
            stat_corrections = calc_stat_correction(draws, final_probs)
        except Exception:
            stat_corrections = {}

        # 보정 확률
        corrected_probs = {}
        for n in range(1, 46):
            sc = stat_corrections.get(n, {})
            adj = sc.get("adj_factor", 1.0)
            corrected_probs[n] = final_probs.get(n, 1/45) * adj
        total_c = sum(corrected_probs.values()) or 1
        corrected_probs = {n: v/total_c for n, v in corrected_probs.items()}

        # ── 3. 필터 범위 분석 (P1/P2/P8 포함) ──────────────────────────────
        # [Stage 1-4-D-2-fix-100] 단일 앙상블 산출 통합
        # 사용자 결정: simulate_all_filters MC 범위 폐기 → 가중평균 __ensemble__ 단일 산출 통일
        logger.info("  [B3] 필터 범위 분석...")
        # simulate_all_filters는 필터 키 목록 추출용으로만 사용 (값은 폐기)
        range_analysis_simple, _ = simulate_all_filters(corrected_probs, draws)
        range_analysis = {}
        for fk in range_analysis_simple.keys():
            from models.ensemble import LottoEnsemble as LE
            auto_task = LE.get_task_for_filter(fk)
            model_exp = get_model_filter_expectations(
                fk, draws, contribs, task=auto_task,
                ensemble=self.ensemble,
            )
            ens_entry = model_exp.get("__ensemble__", {})
            ens_min = ens_entry.get("min")
            ens_max = ens_entry.get("max")
            range_analysis[fk] = {
                "range":              [ens_min, ens_max],  # 가중평균 = 단일 앙상블
                "primary_task":       auto_task,
                "ensemble_min":       ens_min,
                "ensemble_max":       ens_max,
                "ensemble_ci":        ens_entry.get("ci"),
                "model_expectations": model_exp,
            }

        # ── 4. 회귀분석 (P3) ─────────────────────────────────────────────────
        logger.info("  [B4] 회귀분석...")
        try:
            regression_analysis = analyze_all_regressions(
                draws, final_probs,
                model_contributions=contribs,
                ensemble=self.ensemble,
            )
        except Exception as e:
            logger.warning(f"  회귀분석 실패: {e}")
            regression_analysis = {}

        # ── 5. 조합 생성 (10게임) ────────────────────────────────────────────
        logger.info("  [B5] 조합 생성...")
        # top_5, excl_10은 이미 B1-H/I에서 산출됨 (Hot/Cold 균형은 NumberRecommender 내부로 이전)
        gen_probs = corrected_probs.copy()
        for n in excl_10:
            gen_probs[n] = 0
        pred_obj = {"probabilities": gen_probs, "model_contributions": contribs}

        # [번호대 자동 제외] 최근 5회차의 번호대 분포 패턴 → CombinationGenerator로 전달
        # draws는 round DESC 정렬이라 처음 5개가 최근 5회차
        recent5_patterns = []
        for d in draws[:5]:
            cnts = [0, 0, 0, 0, 0]
            for n in d.get("numbers", []):
                if   n <=  10: cnts[0] += 1
                elif n <=  20: cnts[1] += 1
                elif n <=  30: cnts[2] += 1
                elif n <=  40: cnts[3] += 1
                else:          cnts[4] += 1
            recent5_patterns.append("-".join(str(x) for x in cnts))

        # context_data 빌드 (19개 조건 필터용)
        def _build_combo_context_weekly():
            """weekly_pipeline용 context_data 빌드"""
            # missing_11plus
            missing_11plus = [n for n in range(1, 46) if stat_corrections.get(n, {}).get("current_gap", 0) >= 11]

            # hot/cold 분류 (위에서 이미 계산한 freq_count 재사용)
            hot_nums = [n for n in range(1, 46) if freq_count.get(n, 0) >= 5]
            cold_nums = [n for n in range(1, 46) if freq_count.get(n, 0) < 3]

            # 이월수
            carryover = draws[0].get("numbers", []) if draws else []

            # 최근 10회 끝수 분포
            tail_dist_10 = [0] * 10
            for d in draws[:10]:
                for n in d.get("numbers", []):
                    tail_dist_10[n % 10] += 1

            # 4회 이상 미출인 끝수
            tail_missing_4plus = [t for t in range(10) if tail_dist_10[t] <= 2]

            # 최근 10회 번호대 분포
            band_dist_10 = [0] * 5
            for d in draws[:10]:
                for n in d.get("numbers", []):
                    if n <= 10: band_dist_10[0] += 1
                    elif n <= 20: band_dist_10[1] += 1
                    elif n <= 30: band_dist_10[2] += 1
                    elif n <= 40: band_dist_10[3] += 1
                    else: band_dist_10[4] += 1

            # 2회 이상 미출인 번호대
            band_missing_2plus = [idx for idx in range(5) if band_dist_10[idx] <= 5]

            # 앙상블 총합 범위
            sum_range = range_analysis.get("sum", {}).get("range", [100, 220])
            if isinstance(sum_range, list) and len(sum_range) == 2:
                sum_dict = {"min": sum_range[0], "max": sum_range[1]}
            else:
                sum_dict = {"min": 100, "max": 220}

            # 끝수합 범위
            tail_sum_range = range_analysis.get("tail_sum", {}).get("range", [15, 35])
            if isinstance(tail_sum_range, list) and len(tail_sum_range) == 2:
                tail_sum_dict = {"min": tail_sum_range[0], "max": tail_sum_range[1]}
            else:
                tail_sum_dict = {"min": 15, "max": 35}

            return {
                "top_5": top_5,
                "exclude_10": excl_10,
                "missing_11plus": missing_11plus,
                "hot_numbers": hot_nums,
                "cold_numbers": cold_nums,
                "carryover_numbers": carryover,
                "recent_10_tail_dist": tail_dist_10,
                "tail_missing_4plus": tail_missing_4plus,
                "recent_10_band_dist": band_dist_10,
                "band_missing_2plus": band_missing_2plus,
                "ensemble_sum_range": sum_dict,
                "ensemble_tail_sum_range": tail_sum_dict
            }

        combo_context = _build_combo_context_weekly()
        combinations = CombinationGenerator.generate(
            pred_obj,
            filter_settings={"excluded_range_patterns": recent5_patterns},
            n_combinations=6,
            context_data=combo_context
        )

        # ── 6. 메타러너 상태 ─────────────────────────────────────────────────
        meta_status = self.ensemble.meta_learner_status()

        # ── B1-J: top5_result 호환 구조 조립 (weekly_recommendations 저장용) ───
        # NumberRecommender.select_recommendations() 결과 → predict_top5 형식 변환
        top5_result = {
            "top_numbers": recs,  # list[dict] with number, score, consensus, etc.
            "full_probs": final_probs,
            "contributions": contribs,
            "xai_contributions": xai,
            "evidence": evidence,
            "method": "number_recommender",
        }

        return {
            "final_probs":        final_probs,
            "corrected_probs":    corrected_probs,
            "contribs":           contribs,
            "xai":                xai,
            "evidence":           evidence,
            "top5_result":        top5_result,
            "excl_result":        excl_result,
            "top_5":              top_5,
            "excl_10":            excl_10,
            "range_analysis":     range_analysis,
            "regression_analysis": regression_analysis,
            "combinations":       combinations,
            "meta_status":        meta_status,
            # Master Plan Stage 1-4-E 신설 — Phase 1~4 22 predictor 출력
            "predictor_pipeline_outputs": predictor_pipeline_outputs,
            # [Phase 1 옵션 B] NumberRecommender 산출물
            "recs":               recs,
            "scores":             scores,
            "consensus_metrics":  consensus_metrics,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Phase C: weekly_* 테이블 저장
    # ──────────────────────────────────────────────────────────────────────────
    def _save_to_weekly_tables(self, target_round: int, analysis: dict) -> dict:
        saved = {}

        # ── C1. weekly_predictions ──────────────────────────────────────────
        try:
            evidence = analysis.get("evidence", {})
            row = {
                "target_round":    target_round,
                "top_5":           analysis.get("top_5", []),
                "exclude_10":      analysis.get("excl_10", []),
                # task_weights = 실제 예측에 사용된 블렌딩 가중치 (0.7×task + 0.3×meta)
                # model_weights = 메타러너 기본 가중치 (초기값에 가까워 표시 부적합)
                # → task_weights 우선 저장, 없으면 model_weights fallback
                "model_weights":   evidence.get("task_weights") or evidence.get("model_weights", {}),
                "meta_active":     evidence.get("meta_active", False),
                "meta_alpha":      evidence.get("meta_alpha", 0.0),
                "pipeline_version": "v2",
            }
            self.supabase.table("weekly_predictions").upsert(
                row, on_conflict="target_round"
            ).execute()
            saved["weekly_predictions"] = "OK"
            logger.info(f"  [C1] weekly_predictions 저장: top_5={row['top_5']}")
        except Exception as e:
            saved["weekly_predictions"] = f"ERR: {e}"
            logger.error(f"  [C1] weekly_predictions 실패: {e}")

        # ── C2. weekly_number_xai ────────────────────────────────────────────
        try:
            xai = analysis.get("xai", {})
            final_probs  = analysis.get("final_probs", {})
            contributions = analysis.get("contribs", {})  # {model: {n: raw_prob}} — key는 "contribs"
            gnn_contribs  = contributions.get("gnn", {})       # {n: raw_prob}

            # ── 모델별 raw 확률 기반 1-45 순위 계산 ────────────────────────────
            # XAI Z-score는 평균 이하 번호를 0으로 클램핑 → 동점 발생 → 번호 오름차순 fallback
            # raw 확률로 직접 정렬하면 45개 번호 각각에 진짜 순위 부여 가능
            _rank_models = [
                'xgboost', 'catboost', 'tabnet', 'cnn', 'gnn',
                'markov', 'autoencoder', 'tft', 'mhn', 'bayesian_nn',
            ]
            model_ranks: dict = {}
            for _m in _rank_models:
                _probs = contributions.get(_m, {})
                if _probs:
                    _sorted = sorted(range(1, 46),
                                     key=lambda n, p=_probs: float(p.get(n, 0.0)),
                                     reverse=True)
                    model_ranks[_m] = {num: (rank + 1) for rank, num in enumerate(_sorted)}
                else:
                    # Fallback: raw 확률 없으면 XAI Z-score(pct)로 순위 근사
                    # (Markov처럼 contributions가 별도 경로로 채워지지 않는 모델 대응)
                    _xai_scores = {
                        n: float((xai.get(n) or xai.get(str(n)) or {}).get(_m, 0.0))
                        for n in range(1, 46)
                    }
                    _xai_sorted = sorted(range(1, 46),
                                         key=lambda n, s=_xai_scores: s[n],
                                         reverse=True)
                    model_ranks[_m] = {num: (rank + 1) for rank, num in enumerate(_xai_sorted)}

            # GNN이 균등 예측(uniform)이면 XAI excess = 0 → raw 확률로 대체
            gnn_xai_total = sum(
                (xai.get(n) or xai.get(str(n)) or {}).get("gnn", 0.0)
                for n in range(1, 46)
            )
            gnn_is_uniform = gnn_xai_total < 0.5  # 전체 합 0.5% 미만 → uniform 판정

            # [Stage 1-4-D-2-fix-30] evidence_text 일괄 생성 — LLM(Gemma) 자연 문장
            # 모달이 보여주던 /api/explain/ 응답과 동일. 매주 1회 45 호출 (1~2분).
            try:
                import asyncio
                from services.evidence_builder import build_all_evidence_llm
                logger.info(f"  [C2] LLM evidence 생성 시작 (45회 호출)...")
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        # nested loop (드물지만 안전 처리) — 새 thread로 실행
                        import threading
                        evidence_map_holder = {}
                        def _runner():
                            evidence_map_holder["v"] = asyncio.run(
                                build_all_evidence_llm(target_round=target_round)
                            )
                        t = threading.Thread(target=_runner)
                        t.start()
                        t.join()
                        evidence_map = evidence_map_holder.get("v", {})
                    else:
                        evidence_map = asyncio.run(
                            build_all_evidence_llm(target_round=target_round)
                        )
                except RuntimeError:
                    evidence_map = asyncio.run(
                        build_all_evidence_llm(target_round=target_round)
                    )
                logger.info(
                    f"  [C2] LLM evidence 생성 완료: "
                    f"{sum(1 for v in evidence_map.values() if v)}/45개"
                )
            except Exception as ev_e:
                evidence_map = {}
                logger.warning(f"  [C2] evidence 생성 실패 (무시): {ev_e}")

            rows = []
            for n in range(1, 46):
                x = xai.get(n) or xai.get(str(n)) or {}
                if gnn_is_uniform:
                    # raw GNN 확률 × 100 (%) 저장 — 균등이면 ≈ 2.22
                    raw_gnn = gnn_contribs.get(n, gnn_contribs.get(str(n), 1 / 45))
                    gnn_pct = round(float(raw_gnn) * 100, 2)
                else:
                    gnn_pct = x.get("gnn", 0.0)
                # Stage 1-4-D-2-fix-6: 11 base 토폴로지 통일 (사용자 결정 #24 → #24-B 갱신)
                # [2026-05-12 사용자 결정 B] nbeats binary classifier 활성화 — 11 base *모두* per-number
                # LSTM / Transformer는 폐기되었으나 schema 백워드 호환 위해 0 저장
                rows.append({
                    "target_round":    target_round,
                    "number":          n,
                    # 7 base (legacy 컬럼 보존)
                    "xgboost_pct":     x.get("xgboost", 0.0),
                    "cnn_pct":         x.get("cnn", 0.0),
                    "gnn_pct":         gnn_pct,
                    "markov_pct":      x.get("markov", 0.0),
                    "autoencoder_pct": x.get("autoencoder", 0.0),
                    # deprecated (사용자 결정 #24, weight 0 — 호환 위해 0.0 저장)
                    "lstm_pct":        0.0,
                    "transformer_pct": 0.0,
                    # 6 신규 base (Stage 1-4-D-2 + 2026-05-12 nbeats 옵션 B)
                    "catboost_pct":    x.get("catboost", 0.0),
                    "tabnet_pct":      x.get("tabnet", 0.0),
                    "tft_pct":         x.get("tft", 0.0),
                    "mhn_pct":         x.get("mhn", 0.0),
                    "bayesian_nn_pct": x.get("bayesian_nn", 0.0),
                    "nbeats_pct":      x.get("nbeats", 0.0),  # [B] 11번째 base 활성화
                    # 모델별 raw 확률 기반 순위 (1=최고, 45=최저) — XAI 클램핑 우회
                    "xgboost_rank":     model_ranks.get('xgboost',     {}).get(n, 45),
                    "catboost_rank":    model_ranks.get('catboost',    {}).get(n, 45),
                    "tabnet_rank":      model_ranks.get('tabnet',      {}).get(n, 45),
                    "cnn_rank":         model_ranks.get('cnn',         {}).get(n, 45),
                    "gnn_rank":         model_ranks.get('gnn',         {}).get(n, 45),
                    "markov_rank":      model_ranks.get('markov',      {}).get(n, 45),
                    "autoencoder_rank": model_ranks.get('autoencoder', {}).get(n, 45),
                    "tft_rank":         model_ranks.get('tft',         {}).get(n, 45),
                    "mhn_rank":         model_ranks.get('mhn',         {}).get(n, 45),
                    "bayesian_nn_rank": model_ranks.get('bayesian_nn', {}).get(n, 45),
                    "nbeats_rank":      model_ranks.get('nbeats',      {}).get(n, 45),  # [B] 신규
                    # 메타
                    "top_model":       x.get("top_model"),
                    "veto":            x.get("veto"),
                    "probability":     float(final_probs.get(n, 0)),
                    # [Stage 1-4-D-2-fix-28] 번호별 XAI evidence (lazy fetch 폐기, 사전 저장)
                    "evidence_text":   evidence_map.get(n),
                })
            # 기존 행 삭제 후 일괄 insert (upsert conflict 방지)
            self.supabase.table("weekly_number_xai") \
                .delete().eq("target_round", target_round).execute()
            self.supabase.table("weekly_number_xai").insert(rows).execute()
            saved["weekly_number_xai"] = f"OK ({len(rows)}rows)"
            logger.info(f"  [C2] weekly_number_xai 저장: {len(rows)}행")
        except Exception as e:
            saved["weekly_number_xai"] = f"ERR: {e}"
            logger.error(f"  [C2] weekly_number_xai 실패: {e}")

        # ── C3. weekly_filter_predictions ────────────────────────────────────
        # [Stage 1-4-D-2-fix-54-B/C] filter_value 형식 통일 [min, max] array + ±1 패딩
        # [Stage 1-4-D-2-fix-55] LLM 자연어 분석 evidence_text 생성
        try:
            ra = analysis.get("range_analysis", {})

            # [fix-55] 26개 필터 LLM evidence 일괄 생성
            try:
                import asyncio
                from services.filter_narrative import build_all_filter_narratives
                logger.info(f"  [C3] LLM filter_narrative 생성 시작 ({len(ra)} 필터)...")
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        import threading
                        holder = {}
                        def _run():
                            holder["v"] = asyncio.run(
                                build_all_filter_narratives(ra, self.ensemble)
                            )
                        t = threading.Thread(target=_run); t.start(); t.join()
                        filter_narratives = holder.get("v", {})
                    else:
                        filter_narratives = asyncio.run(
                            build_all_filter_narratives(ra, self.ensemble)
                        )
                except RuntimeError:
                    filter_narratives = asyncio.run(
                        build_all_filter_narratives(ra, self.ensemble)
                    )
                logger.info(
                    f"  [C3] LLM filter_narrative 완료: "
                    f"{sum(1 for v in filter_narratives.values() if v)}/{len(ra)} 필터"
                )
            except Exception as ev_e:
                filter_narratives = {}
                logger.warning(f"  [C3] filter_narrative 생성 실패 (무시): {ev_e}")

            rows = []

            # filter별 물리적 클램프 (C와 동일)
            FILTER_CLAMP = {
                "sum": (21, 255), "tail_sum": (0, 54), "ac": (0, 10),
                "odd": (0, 6), "high": (0, 6), "prime": (0, 6), "composite": (0, 6),
                "consecutive": (0, 5), "square": (0, 6), "triangular": (0, 6), "twin": (0, 6),
                "mul3": (0, 6), "mul4": (0, 6), "mul5": (0, 6), "mul7": (0, 6), "mul8": (0, 5),
                "mul34": (0, 3), "mul35": (0, 3), "mul45": (0, 2),
                "non_multiple": (0, 6), "hot10": (0, 6), "neutral10": (0, 6),
                "cold10": (0, 6), "missing": (0, 6), "neighbor": (0, 6), "carryover": (0, 6),
            }

            for fk, fdata in ra.items():
                ens_ci = fdata.get("ensemble_ci")
                ens_min = fdata.get("ensemble_min")
                ens_max = fdata.get("ensemble_max")

                # [fix-54-C] AI 추천 범위가 너무 좁으면 ±1 패딩
                if ens_min is not None and ens_max is not None:
                    rng = ens_max - ens_min
                    # 좁은 기준: range ≤ 1 (즉 0~1, 1~2 같은 매우 협소)
                    # → ±1 확장
                    if rng <= 1:
                        ens_min = ens_min - 1
                        ens_max = ens_max + 1
                    clamp = FILTER_CLAMP.get(fk)
                    if clamp:
                        ens_min = max(clamp[0], ens_min)
                        ens_max = min(clamp[1], ens_max)

                # [Stage 1-4-D-2-fix-100] filter_value = [ensemble_min, ensemble_max] 단일 산출 통일
                # 가중평균 __ensemble__ 결과를 filter_value에도 저장 (MC simulate 결과 폐기)
                normalized_range = [ens_min if ens_min is not None else 0,
                                     ens_max if ens_max is not None else 6]

                rows.append({
                    "target_round":       target_round,
                    "filter_key":         fk,
                    "filter_value":       json.dumps(normalized_range, ensure_ascii=False),
                    "primary_task":       fdata.get("primary_task"),
                    "ensemble_min":       ens_min,
                    "ensemble_max":       ens_max,
                    "ensemble_ci":        ens_ci,
                    "model_expectations": {
                        k: v for k, v in (fdata.get("model_expectations") or {}).items()
                        if k != "__ensemble__"  # __ensemble__은 위에서 분리 저장
                    },
                    # [fix-55] LLM 자연어 분석 (필터별 evidence)
                    "evidence_text":      filter_narratives.get(fk),
                })
            self.supabase.table("weekly_filter_predictions") \
                .delete().eq("target_round", target_round).execute()
            if rows:
                self.supabase.table("weekly_filter_predictions").insert(rows).execute()
            saved["weekly_filter_predictions"] = f"OK ({len(rows)}rows)"
            logger.info(f"  [C3] weekly_filter_predictions 저장: {len(rows)}행")
        except Exception as e:
            saved["weekly_filter_predictions"] = f"ERR: {e}"
            logger.error(f"  [C3] weekly_filter_predictions 실패: {e}")

        # ── C4. weekly_regression_analysis ───────────────────────────────────
        try:
            reg = analysis.get("regression_analysis", {})
            rows = []
            # analyze_all_regressions()는 list 반환 (각 항목에 id=실제 step 포함)
            if isinstance(reg, list):
                reg_items = reg
            elif isinstance(reg, dict):
                reg_items = list(reg.values())
            else:
                reg_items = []

            for sdata in reg_items:
                if not isinstance(sdata, dict):
                    continue
                # 실제 회귀 윈도우: sdata["id"] 우선, 없으면 sdata["step"]
                step_int = int(sdata.get("id") or sdata.get("step") or 0)
                # model_exp에 표시용 메타 정보 포함 (스키마 변경 없이)
                me = dict(sdata.get("model_exp") or {})
                me["_targets"] = sdata.get("targets") or []
                me["_gap"]     = sdata.get("gap", 0)
                me["_str"]     = sdata.get("str", 0)
                me["_avg_hit"] = round(float(sdata.get("avg_hit") or 0), 3)
                me["_notable"] = sdata.get("notable") or []
                rows.append({
                    "target_round":      target_round,
                    "step":              step_int,
                    "window_type":       sdata.get("window_type") or sdata.get("type"),
                    "predicted_numbers": sdata.get("targets") or sdata.get("predicted_numbers") or [],
                    "model_exp":         me,
                    "primary_method":    sdata.get("primary_method"),
                    "confidence":        round(float(sdata.get("avg_hit") or sdata.get("confidence") or 0), 3),
                })
            self.supabase.table("weekly_regression_analysis") \
                .delete().eq("target_round", target_round).execute()
            if rows:
                self.supabase.table("weekly_regression_analysis").insert(rows).execute()
            saved["weekly_regression_analysis"] = f"OK ({len(rows)}rows)"
            logger.info(f"  [C4] weekly_regression_analysis 저장: {len(rows)}행")
        except Exception as e:
            saved["weekly_regression_analysis"] = f"ERR: {e}"
            logger.error(f"  [C4] weekly_regression_analysis 실패: {e}")

        # ── C5. weekly_recommendations (P4 상세) ─────────────────────────────
        try:
            top5_detail = analysis["top5_result"].get("top_numbers", [])
            rows = []
            for i, entry in enumerate(top5_detail[:5], start=1):
                rows.append({
                    "target_round":   target_round,
                    "rank":           i,
                    "number":         entry.get("number"),
                    "ci_lower":       entry.get("ci_lower"),
                    "ci_upper":       entry.get("ci_upper"),
                    "consensus_count": entry.get("consensus_count"),
                    "confidence_level": entry.get("confidence_level"),
                    "probability":    entry.get("probability"),
                })
            self.supabase.table("weekly_recommendations") \
                .delete().eq("target_round", target_round).execute()
            if rows:
                self.supabase.table("weekly_recommendations").insert(rows).execute()
            saved["weekly_recommendations"] = f"OK ({len(rows)}rows)"
            logger.info(f"  [C5] weekly_recommendations 저장: {len(rows)}행")
        except Exception as e:
            saved["weekly_recommendations"] = f"ERR: {e}"
            logger.error(f"  [C5] weekly_recommendations 실패: {e}")

        # ── C6. weekly_combinations ───────────────────────────────────────────
        try:
            combos = analysis.get("combinations", [])
            rows = []
            for i, combo in enumerate(combos[:10], start=1):
                nums = sorted(combo) if isinstance(combo, list) else sorted(combo.get("numbers", []))
                rows.append({
                    "target_round": target_round,
                    "combo_rank":   i,
                    "numbers":      nums,
                    "total_sum":    sum(nums),
                    "odd_count":    sum(1 for n in nums if n % 2 == 1),
                    "high_count":   sum(1 for n in nums if n >= 23),
                })
            self.supabase.table("weekly_combinations") \
                .delete().eq("target_round", target_round).execute()
            if rows:
                self.supabase.table("weekly_combinations").insert(rows).execute()
            saved["weekly_combinations"] = f"OK ({len(rows)}rows)"
            logger.info(f"  [C6] weekly_combinations 저장: {len(rows)}행")
        except Exception as e:
            saved["weekly_combinations"] = f"ERR: {e}"
            logger.error(f"  [C6] weekly_combinations 실패: {e}")

        # ── C7. deep_analysis_history (frontend ai_deep_learning.html 호환) ────
        # matrix_data + 4섹션 + regression_analysis를 저장
        try:
            # weekly_number_xai에서 방금 저장한 45행 조회
            xai_res = self.supabase.table("weekly_number_xai") \
                .select("*").eq("target_round", target_round).execute()
            xai_rows = xai_res.data or []

            # matrix_data 빌드: [{num, models: {model_name: {score, rank}}}, ...]
            matrix_data = []
            for row in xai_rows:
                num = row.get("number")
                models_dict = {}
                # 11 base (10 active + nbeats 제외) — deprecated는 0으로 채워짐
                for model_name in ["xgboost", "catboost", "tabnet", "cnn", "gnn",
                                   "markov", "autoencoder", "tft", "mhn", "bayesian_nn",
                                   "lstm", "transformer"]:
                    pct_key = f"{model_name}_pct"
                    rank_key = f"{model_name}_rank"
                    models_dict[model_name] = {
                        "score": float(row.get(pct_key, 0.0)),
                        "rank": int(row.get(rank_key, 45)),
                    }
                matrix_data.append({"num": num, "models": models_dict})

            # High-1: 4섹션 분석 계산 (deep_analysis_v3 함수 재사용)
            final_probs = analysis.get("final_probs", {})
            contribs = analysis.get("contribs", {})
            history_draws = fetch_all_draws()

            logger.info("  [C7] 4섹션 분석 계산 중...")
            tail_analysis = analyze_tail_detailed(final_probs, history_draws, model_contributions=contribs)
            number_band_analysis = analyze_number_band(final_probs, history_draws, model_contributions=contribs)
            magic_square_analysis = analyze_magic_square(final_probs, history_draws, model_contributions=contribs)
            lotto_paper_analysis = analyze_lotto_paper(final_probs, history_draws, model_contributions=contribs)

            # regression_analysis는 Phase B에서 이미 계산됨
            regression_analysis = analysis.get("regression_analysis", {})

            # analysis_data 구조 (ai_deep_learning.js가 기대하는 형식 + 4섹션 추가)
            analysis_data_obj = {
                "success": True,
                "target_round": target_round,
                "top_5": analysis.get("top_5", []),
                "exclude_10": analysis.get("excl_10", []),
                "analysis": {
                    "matrix_data": matrix_data,
                    # High-1: 4섹션 추가
                    "tail_analysis": tail_analysis,
                    "number_band_analysis": number_band_analysis,
                    "magic_square_analysis": magic_square_analysis,
                    "lotto_paper_analysis": lotto_paper_analysis,
                    # regression_analysis도 추가 (이미 frontend는 weekly_regression_analysis에서 직접 fetch)
                    "regression_analysis": regression_analysis,
                },
                "combinations": analysis.get("combinations", [])[:10],
            }

            # deep_analysis_history upsert
            history_row = {
                "target_round": target_round,
                "confidence": 75,  # 기본 신뢰도 (LLM 전략 없이 앙상블 단독)
                "summary": f"{target_round}회차 딥러닝 앙상블 분석 (11 base + 4 Pillar)",
                "analysis_data": analysis_data_obj,
                "recommended_numbers": analysis.get("top_5", []),
                "excluded_numbers": analysis.get("excl_10", []),
                # [fix] JSONB 컬럼은 Python dict/list 직접 전달 (json.dumps 시 string 타입으로 이중 인코딩됨)
                "combinations": analysis.get("combinations", [])[:10],
                "number_rankings": {},  # 옵션
                "model_rankings": {},   # 옵션
                "applied_filters": {},
                "model_analysis": {},
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self.supabase.table("deep_analysis_history") \
                .upsert(history_row, on_conflict="target_round").execute()
            saved["deep_analysis_history"] = "OK"
            logger.info(f"  [C7] deep_analysis_history 저장: matrix_data={len(matrix_data)}행, "
                       f"4섹션(tail={len(tail_analysis)}, band={len(number_band_analysis)}, "
                       f"magic={len(magic_square_analysis)}, paper={len(lotto_paper_analysis['rows'])+len(lotto_paper_analysis['cols'])}), "
                       f"regression={len(regression_analysis)}행")
        except Exception as e:
            saved["deep_analysis_history"] = f"ERR: {e}"
            logger.error(f"  [C7] deep_analysis_history 실패: {e}")

        # ── [P4 PATCH] C8. weekly_number_xai.veto 채움 ────────────────────────
        # weekly_number_xai 저장 직후 _rank 컬럼 기반으로 veto 컬럼 채움
        # 근거: Lotto_lab_Root_Cause_Diagnosis.md (Finding #5)
        try:
            from services.veto_filler import fill_veto_for_round
            veto_result = fill_veto_for_round(target_round)
            if veto_result["success"]:
                d = veto_result["distribution"]
                saved["weekly_number_xai_veto"] = (
                    f"OK ({veto_result['updated']}rows, "
                    f"safe={d.get('safe', 0)}, "
                    f"exclude={d.get('exclude', 0)}, "
                    f"neutral={d.get('neutral', 0)})"
                )
                logger.info(f"  [C8/P4] veto 채움: {d}")
            else:
                saved["weekly_number_xai_veto"] = f"WARN: {veto_result.get('error')}"
        except Exception as e:
            saved["weekly_number_xai_veto"] = f"ERR: {e}"
            logger.error(f"  [C8/P4] veto 채움 실패: {e}")
        # ── /P4 PATCH ──────────────────────────────────────────────────────────

        # ── [P5 PATCH 옵션 A] C9. recommendation_backtest_runs.pillar_scores ──
        # 4-Pillar Consensus Score (CNS/ENS/FLT/STA) 계산 + 저장
        # 근거: Lotto_lab_Root_Cause_Diagnosis.md (Finding #1)
        try:
            from services.pillar_scorer import save_pillar_scores
            pillar_result = save_pillar_scores(target_round)
            if pillar_result["success"]:
                s = pillar_result["scores"]
                saved["pillar_scores"] = (
                    f"OK (updated={pillar_result['updated']}, "
                    f"CNS={s.get('CNS', 0):.3f}, "
                    f"ENS={s.get('ENS', 0):.3f}, "
                    f"FLT={s.get('FLT', 0):.3f}, "
                    f"STA={s.get('STA', 0):.3f})"
                )
                logger.info(f"  [C9/P5] pillar_scores: {s}")
            else:
                saved["pillar_scores"] = f"WARN: {pillar_result.get('error')}"
        except Exception as e:
            saved["pillar_scores"] = f"ERR: {e}"
            logger.error(f"  [C9/P5] pillar_scores 실패: {e}")
        # ── /P5 PATCH ──────────────────────────────────────────────────────────

        return saved

    # ──────────────────────────────────────────────────────────────────────────
    # [Phase 1 옵션 B] NumberRecommender 경로 헬퍼 메서드
    # ──────────────────────────────────────────────────────────────────────────
    def _load_expert_memo(self, target_round: int) -> dict | None:
        """expert_memos 테이블에서 forced_includes/excludes 로드 (graceful fallback)."""
        try:
            from db.supabase_client import get_client
            supabase = get_client()
            res = supabase.table("expert_memos") \
                .select("forced_includes, forced_excludes") \
                .eq("target_round", target_round) \
                .order("created_at", desc=True) \
                .limit(1) \
                .execute()
            if res.data:
                row = res.data[0]
                return {
                    "forced_includes": row.get("forced_includes") or [],
                    "forced_excludes": row.get("forced_excludes") or [],
                }
        except Exception as e:
            logger.warning(f"  [B1-G] expert_memos 로드 실패 (None fallback): {e}")
        return None

    def _compute_filter_compliance(
        self,
        predictor_pipeline_outputs: dict | None,
        draws: list,
    ) -> "np.ndarray":
        """21지표 통과도 (45,) ndarray. NumberScorer._compute_pillar_2 위임."""
        import numpy as np
        try:
            from models.number_scorer import NumberScorer
            scorer = NumberScorer()
            p2 = scorer._compute_pillar_2(predictor_pipeline_outputs, draws[:20] if draws else None)
            if isinstance(p2, np.ndarray) and p2.shape == (45,):
                return p2
        except Exception as e:
            logger.warning(f"  [B1-F] filter_compliance 산출 실패 (균등 fallback): {e}")
        # fallback: 균등 0.5
        return np.full(45, 0.5, dtype=np.float64)


# ── 스크립트 직접 실행 지원 ────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Weekly Pipeline V2")
    parser.add_argument("--round", type=int, default=None, help="예측 대상 회차 (기본: 최신+1)")
    args = parser.parse_args()

    pipeline = WeeklyPipelineV2()
    result = pipeline.run(target_round=args.round)
    print(json.dumps(result, ensure_ascii=False, indent=2))
