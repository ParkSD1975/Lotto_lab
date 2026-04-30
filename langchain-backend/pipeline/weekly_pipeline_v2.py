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

# deep_analysis_v3.py 의 핵심 계산 함수들 임포트
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from routes.deep_analysis_v3 import (
    simulate_all_filters,
    get_model_filter_expectations,
    analyze_all_regressions,
    calc_stat_correction,
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
            logger.info("[Phase B] 딥러닝 분석 실행 중...")
            analysis = self._run_analysis(draws, target)

            # ── Phase C: weekly_* 테이블 저장 ────────────────────────────────
            logger.info("[Phase C] weekly_* 테이블 저장 중...")
            save_result = self._save_to_weekly_tables(target, analysis)

            elapsed = round((datetime.now() - start).total_seconds(), 2)
            logger.info(f"[WeeklyPipelineV2] 완료 ({elapsed}초)")

            return {
                "success":      True,
                "target_round": target,
                "elapsed":      elapsed,
                "verify":       verify_result,
                "save":         save_result,
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

        Returns dict with keys:
          prediction, contribs, xai, top5_result, excl_result,
          final_probs, range_analysis, regression_analysis, combinations,
          predictor_pipeline_outputs (Master Plan Stage 1-4-E 신설)
        """
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

        # ── 1. 앙상블 예측 (P4 Top5 + P5 Veto) ──────────────────────────────
        logger.info("  [B1] 앙상블 예측...")
        top5_result = self.ensemble.predict_top5(draws)
        excl_result = self.ensemble.predict_exclusion_with_veto(draws)
        prediction  = top5_result.get("full_probs") or {}
        contribs    = top5_result.get("contributions", {})
        xai         = top5_result.get("xai_contributions", {})
        evidence    = top5_result.get("evidence", {})

        # fallback: predict()에서 가져오기
        if not prediction:
            base = self.ensemble.predict(draws)
            prediction = base.get("probabilities", {})
            contribs   = base.get("model_contributions", {})
            xai        = base.get("xai_contributions", {})
            evidence   = base.get("evidence", {})

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
        logger.info("  [B3] 필터 범위 분석...")
        range_analysis_simple, _ = simulate_all_filters(corrected_probs, draws)
        range_analysis = {}
        for fk, fv in range_analysis_simple.items():
            from models.ensemble import LottoEnsemble as LE
            auto_task = LE.get_task_for_filter(fk)
            model_exp = get_model_filter_expectations(
                fk, draws, contribs, task=auto_task,
                ensemble=self.ensemble,
            )
            ens_entry = model_exp.get("__ensemble__", {})
            range_analysis[fk] = {
                "range":              fv,
                "primary_task":       auto_task,
                "ensemble_min":       ens_entry.get("min"),
                "ensemble_max":       ens_entry.get("max"),
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
        top_5   = [e["number"] for e in top5_result.get("top_numbers", [])][:5]
        excl_10 = [e["number"] for e in excl_result.get("exclusions", [])][:10]
        gen_probs = corrected_probs.copy()
        for n in excl_10:
            gen_probs[n] = 0
        pred_obj = {"probabilities": gen_probs, "model_contributions": contribs}
        combinations = CombinationGenerator.generate(
            pred_obj, filter_settings={}, n_combinations=10
        )

        # ── 6. 메타러너 상태 ─────────────────────────────────────────────────
        meta_status = self.ensemble.meta_learner_status()

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
            contributions = analysis.get("contributions", {})  # {model: {n: raw_prob}}
            gnn_contribs  = contributions.get("gnn", {})       # {n: raw_prob}

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
                # Stage 1-4-D-2-fix-6: 11 base 토폴로지 통일 (사용자 결정 #24)
                # 메인 1~45 binary classifier 11 base — nbeats 제외 (스칼라 시계열 분해 전용)
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
                    # 5 신규 base (Stage 1-4-D-2 학습 산출물)
                    "catboost_pct":    x.get("catboost", 0.0),
                    "tabnet_pct":      x.get("tabnet", 0.0),
                    "tft_pct":         x.get("tft", 0.0),
                    "mhn_pct":         x.get("mhn", 0.0),
                    "bayesian_nn_pct": x.get("bayesian_nn", 0.0),
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
        try:
            ra = analysis.get("range_analysis", {})
            rows = []
            for fk, fdata in ra.items():
                ens_ci = fdata.get("ensemble_ci")
                rows.append({
                    "target_round":       target_round,
                    "filter_key":         fk,
                    "filter_value":       json.dumps(fdata.get("range"), ensure_ascii=False),
                    "primary_task":       fdata.get("primary_task"),
                    "ensemble_min":       fdata.get("ensemble_min"),
                    "ensemble_max":       fdata.get("ensemble_max"),
                    "ensemble_ci":        ens_ci,
                    "model_expectations": {
                        k: v for k, v in (fdata.get("model_expectations") or {}).items()
                        if k != "__ensemble__"  # __ensemble__은 위에서 분리 저장
                    },
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

        return saved


# ── 스크립트 직접 실행 지원 ────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Weekly Pipeline V2")
    parser.add_argument("--round", type=int, default=None, help="예측 대상 회차 (기본: 최신+1)")
    args = parser.parse_args()

    pipeline = WeeklyPipelineV2()
    result = pipeline.run(target_round=args.round)
    print(json.dumps(result, ensure_ascii=False, indent=2))
