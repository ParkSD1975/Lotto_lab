import logging
import asyncio
from datetime import datetime
import json

import config
from db.supabase_client import get_client, fetch_all_draws
from models.ensemble import LottoEnsemble, CombinationGenerator
from rag.data_loader import draws_to_documents, predictions_to_documents
# from rag.embedder import LottoEmbedder # Fixed: Use db.vector_store directly
from db.vector_store import add_documents
# from chains.report_chain import create_report_chain # Fixed: Use generate_report
from chains.report_chain import generate_report

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("WeeklyPipeline")

class WeeklyPipeline:
    """매주 토요일 실행되는 로또 분석/학습/예측 자동화 파이프라인."""

    def __init__(self):
        self.supabase = get_client()
        self.ensemble = LottoEnsemble()
        # self.embedder = LottoEmbedder() # Fixed: Not needed
        self.combinator = CombinationGenerator()

    async def run(self, new_round: int = None):
        """파이프라인 실행 진입점."""
        logger.info(f"[Start] Weekly pipeline starting (Target Round: {new_round})")
        
        try:
            # 1. 데이터 확인
            draws = fetch_all_draws()
            latest_db_round = draws[0]['round'] if draws else 0
            
            if new_round and latest_db_round < new_round:
                logger.warning(f"[WARN] DB latest round({latest_db_round}) < requested round({new_round}). Data update needed first.")
                # 실제 운영 시에는 여기서 크롤러(update_lotto.py)를 트리거할 수 있음
            
            target_round = latest_db_round + 1
            logger.info(f"[Target] Predicting round {target_round}")

            # 2. 이전 회차 예측 검증 (채점)
            await self._verify_previous_predictions(latest_db_round)

            # 3. 모델 재학습 및 예측 (핵심)
            predictions = await self._run_deep_learning_prediction(draws, target_round)

            # 4. RAG 벡터 DB 업데이트
            await self._update_vector_db(draws, predictions)

            # 5. 주간 분석 보고서 생성
            await self._generate_weekly_report(target_round, predictions)

            logger.info("[Complete] Weekly pipeline all tasks finished")
            return {"status": "success", "target_round": target_round}

        except Exception as e:
            logger.error(f"[Error] Pipeline failed: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    async def _verify_previous_predictions(self, actual_round: int):
        """[Phase 1.3 / 2.3 / 4.5] 지난 회차 예측 채점 + 제외수 / 필터 범위 검증."""
        logger.info(f"[Stage 2] Verifying predictions for round {actual_round}...")

        # 1. 실제 당첨 번호 조회
        draw_res = self.supabase.table("lotto_draws").select("numbers").eq("round", actual_round).execute()
        if not draw_res.data:
            logger.warning("   실제 당첨 정보를 찾을 수 없어 검증을 건너뜁니다.")
            return

        actual_numbers = set(draw_res.data[0]['numbers'])
        actual_sum     = sum(actual_numbers)
        actual_odd     = sum(1 for n in actual_numbers if n % 2 == 1)

        # 2. model_performance_log hit_count 업데이트 (Phase 1.3)
        perf_res = self.supabase.table("model_performance_log") \
            .select("*").eq("round", actual_round).execute()
        for row in (perf_res.data or []):
            predicted = set(row.get("predicted_numbers") or [])
            hit = len(actual_numbers & predicted)
            self.supabase.table("model_performance_log") \
                .update({"actual_numbers": list(actual_numbers), "hit_count": hit}) \
                .eq("id", row["id"]).execute()
        logger.info(f"   [1.3] model_performance_log 업데이트: {len(perf_res.data or [])}건")

        # 3. deep_analysis_history 제외수 검증 (Phase 2.3)
        hist_res = self.supabase.table("deep_analysis_history") \
            .select("id, excluded_numbers, analysis_data") \
            .eq("target_round", actual_round).execute()
        for row in (hist_res.data or []):
            excluded = set(row.get("excluded_numbers") or [])
            exclude_hit = len(actual_numbers & excluded)
            exclude_acc = round((len(excluded) - exclude_hit) / max(len(excluded), 1), 3)
            # analysis_data JSON 병합 업데이트
            try:
                import json
                ad = json.loads(row.get("analysis_data") or "{}")
                if isinstance(ad, dict):
                    ad["exclude_hit_count"] = exclude_hit
                    ad["exclude_accuracy"]  = exclude_acc
                    self.supabase.table("deep_analysis_history") \
                        .update({
                            "actual_numbers": list(actual_numbers),
                            "analysis_data":  json.dumps(ad, ensure_ascii=False)
                        }) \
                        .eq("id", row["id"]).execute()
            except Exception as e2:
                logger.warning(f"   [2.3] 제외수 검증 업데이트 실패: {e2}")
        logger.info(f"   [2.3] 제외수 정확도 업데이트 완료")

        # 4. model_filter_predictions 범위 검증 (Phase 4.5)
        mfp_res = self.supabase.table("model_filter_predictions") \
            .select("id, total_sum_min, total_sum_max, odd_even_pattern_min, odd_even_pattern_max, ac_value_min, ac_value_max") \
            .eq("round_number", actual_round).execute()

        from datetime import datetime, timezone
        now_ts = datetime.now(timezone.utc).isoformat()
        for row in (mfp_res.data or []):
            in_sum = (row["total_sum_min"] is not None and row["total_sum_min"] <= actual_sum <= row["total_sum_max"])  \
                     if row.get("total_sum_min") is not None else None
            in_odd = (row["odd_even_pattern_min"] is not None and row["odd_even_pattern_min"] <= actual_odd <= row["odd_even_pattern_max"]) \
                     if row.get("odd_even_pattern_min") is not None else None
            self.supabase.table("model_filter_predictions") \
                .update({
                    "actual_total_sum":           actual_sum,
                    "actual_odd_even_pattern":    actual_odd,
                    "in_range_total_sum":         in_sum,
                    "in_range_odd_even_pattern":  in_odd,
                    "verified_at":                now_ts,
                }) \
                .eq("id", row["id"]).execute()
        logger.info(f"   [4.5] 필터 범위 검증 완료: {len(mfp_res.data or [])}건")

        # 5. 기존 ai_predictions 업데이트 (하위 호환)
        preds = self.supabase.table("ai_predictions").select("*").eq("target_round", actual_round).execute()
        for pred in (preds.data or []):
            predicted_nums = set(pred['predicted_numbers'])
            hit_count = len(actual_numbers & predicted_nums)
            self.supabase.table("ai_predictions").update({"hit_count": hit_count}).eq("id", pred['id']).execute()
        logger.info(f"   {len(preds.data or [])}건의 지난 예측 검증 완료.")

        # 6. ai_custom_analyses 회차별 성과 기록 (evaluation_history 누적)
        await self._verify_custom_analyses(actual_round, actual_numbers)

    async def _verify_custom_analyses(self, actual_round: int, actual_numbers: set):
        """[신규] ai_custom_analyses 각 분석의 회차별 성과를 evaluation_history에 누적 기록.

        대상번호 중 실제 당첨번호와 겹친 번호(hit), 전체 대상수 대비 적중률을 기록한다.
        dynamic 타입은 target_round 기준 대상번호를 재계산하여 평가한다.
        """
        from datetime import timezone as _tz
        now_ts = datetime.now(_tz.utc).isoformat()

        try:
            # 이전 회차 당첨번호 (dynamic 수식 계산용)
            prev_draw_res = self.supabase.table("lotto_draws") \
                .select("numbers") \
                .eq("round", actual_round - 1) \
                .maybeSingle().execute()
            prev_numbers = prev_draw_res.data["numbers"] if prev_draw_res.data else []

            res = self.supabase.table("ai_custom_analyses") \
                .select("id, type, target_numbers, rules, filter_config") \
                .eq("is_ai_enabled", True).execute()
            analyses = res.data or []
            updated = 0

            for a in analyses:
                try:
                    target_nums = self._resolve_target_numbers(a, actual_round, actual_numbers, prev_numbers)
                    if not target_nums:
                        continue

                    target_set = set(target_nums)
                    hit_nums  = sorted(actual_numbers & target_set)
                    hit_count = len(hit_nums)
                    total     = len(target_set)
                    accuracy  = round(hit_count / total, 4) if total > 0 else 0.0

                    # filter_config min/max 기준 pass/fail 판정
                    fc = a.get("filter_config") or {}
                    if isinstance(fc, str):
                        try: fc = json.loads(fc)
                        except: fc = {}
                    fc_min = fc.get("min", 0)
                    fc_max = fc.get("max", 99)
                    passed = fc_min <= hit_count <= fc_max

                    entry = {
                        "round":      actual_round,
                        "hit_count":  hit_count,
                        "hit_numbers": hit_nums,
                        "total":      total,
                        "accuracy":   accuracy,
                        "passed":     passed,
                        "evaluated_at": now_ts,
                    }

                    # evaluation_history 배열에 최신 항목 append (최대 50회 보관)
                    hist_res = self.supabase.table("ai_custom_analyses") \
                        .select("evaluation_history") \
                        .eq("id", a["id"]).maybeSingle().execute()
                    existing_hist = (hist_res.data or {}).get("evaluation_history") or []
                    if isinstance(existing_hist, str):
                        try: existing_hist = json.loads(existing_hist)
                        except: existing_hist = []
                    existing_hist.append(entry)
                    existing_hist = existing_hist[-50:]  # 최근 50회만 보관

                    # ai_evaluation: 최근 10회 요약 통계
                    recent = existing_hist[-10:]
                    avg_hit = round(sum(e["hit_count"] for e in recent) / len(recent), 2) if recent else 0
                    avg_acc = round(sum(e["accuracy"] for e in recent) / len(recent), 4) if recent else 0
                    pass_rate = round(sum(1 for e in recent if e.get("passed")) / len(recent), 4) if recent else 0
                    ai_eval = {
                        "last_round":  actual_round,
                        "avg_hit_10":  avg_hit,
                        "avg_acc_10":  avg_acc,
                        "pass_rate_10": pass_rate,
                        "total_evals": len(existing_hist),
                        "updated_at":  now_ts,
                    }

                    self.supabase.table("ai_custom_analyses").update({
                        "evaluation_history": existing_hist,
                        "ai_evaluation":      ai_eval,
                        "target_round":       actual_round,
                        "target_numbers":     sorted(target_set),
                        "updated_at":         now_ts,
                    }).eq("id", a["id"]).execute()
                    updated += 1

                except Exception as e_inner:
                    logger.warning(f"   [custom eval] {a.get('id','')} 평가 실패: {e_inner}")

            logger.info(f"   [6] ai_custom_analyses 성과 기록 완료: {updated}/{len(analyses)}건")

        except Exception as e:
            logger.warning(f"   [6] ai_custom_analyses 성과 기록 전체 실패: {e}")

    def _resolve_target_numbers(self, analysis: dict, actual_round: int,
                                 actual_numbers: set, prev_numbers: list) -> list:
        """분석 타입별로 해당 회차의 대상번호를 계산한다.

        - static : target_numbers 그대로
        - dynamic: rules 수식으로 prev_numbers 기반 계산
        - ai_custom: target_numbers 그대로 (딥러닝 추천 결과)
        """
        a_type  = analysis.get("type", "static")
        rules   = analysis.get("rules") or {}
        if isinstance(rules, str):
            try: rules = json.loads(rules)
            except: rules = {}

        # ── static / ai_custom ──────────────────────────────
        if a_type in ("static", "ai_custom"):
            raw = analysis.get("target_numbers") or []
            if isinstance(raw, str):
                try: raw = json.loads(raw)
                except: raw = []
            return [int(n) for n in raw if 1 <= int(n) <= 45]

        # ── dynamic ─────────────────────────────────────────
        if a_type == "dynamic" and prev_numbers:
            formula = rules.get("formula", "prev_plus_n")
            value   = int(rules.get("value", 0))
            result  = []
            for n in prev_numbers:
                if formula == "prev_plus_n":
                    v = n + value
                elif formula == "prev_minus_n":
                    v = n - value
                elif formula == "prev_multiply_n":
                    v = n * value
                else:
                    v = n + value
                if 1 <= v <= 45:
                    result.append(v)
            return result

        return []

    async def _run_deep_learning_prediction(self, draws, target_round):
        """앙상블 모델 예측 실행 및 DB 저장."""
        logger.info(f"[Stage 3] Deep learning ensemble prediction (Target: {target_round})...")
        
        # 1. 예측 실행
        result = self.ensemble.predict(draws)
        
        # 2. 조합 생성 (Combination)
        combinations = self.combinator.generate(result, count=5)
        
        # 3. DB 저장 데이터 준비
        db_entries = []
        
        # (A) 추천수 (Top 15)
        db_entries.append({
            "target_round": target_round,
            "prediction_type": "recommendation",
            "predicted_numbers": result['recommended'], # Top 10
            "confidence_score": max(result['probabilities'].values()),
            "model_version": "v2.0-ensemble",
            "model_contributions": result['model_contributions'],
            "ensemble_weights": result['weights_used'],
            "analysis_detail": {"xgb_features": result['xgb_feature_importance']}
        })
        
        # (B) 제외수 (Bottom 10)
        db_entries.append({
            "target_round": target_round,
            "prediction_type": "exclusion",
            "predicted_numbers": result['excluded'],
            "confidence_score": 0.95, # 제외 확신도
            "model_version": "v2.0-ensemble"
        })
        
        # (C) 최종 조합 5게임
        for i, comb in enumerate(combinations):
            db_entries.append({
                "target_round": target_round,
                "prediction_type": "combination",
                "predicted_numbers": comb,
                "confidence_score": 0.85, # 조합 기대도
                "model_version": "v2.0-monte-carlo",
                "analysis_detail": {"rank": i + 1}
            })

        # 4. 일괄 Insert
        for entry in db_entries:
            self.supabase.table("ai_predictions").insert(entry).execute()
            
        logger.info(f"   예측 결과 {len(db_entries)}건 DB 저장 완료.")
        return db_entries

    async def _update_vector_db(self, draws, predictions):
        """RAG 검색을 위한 벡터 DB 최신화."""
        logger.info("[Stage 4] RAG vector DB update...")
        
        # 1. 최신 회차(Draw) 벡터화 (마지막 1건만)
        if draws:
            latest_draw = [draws[0]] # draws는 이미 최신순 정렬되어 있다고 가정
            docs = draws_to_documents(latest_draw)
            if docs:
                # Fixed: Call sync function directly
                add_documents(docs)
                logger.info(f"   최신 회차({latest_draw[0]['round']}) 문서 추가.")

        # 2. 이번주 예측(Predictions) 벡터화
        # 예측 결과는 딕셔너리 형태이므로 변환 필요
        pred_docs = predictions_to_documents(predictions)
        if pred_docs:
            # Fixed: Call sync function directly
            add_documents(pred_docs)
            logger.info(f"   AI 예측 문서 {len(pred_docs)}건 추가.")

    async def _generate_weekly_report(self, target_round, predictions):
        """LangChain을 이용해 종합 분석 보고서 생성."""
        logger.info("[Stage 5] Generating weekly report...")
        
        # 간단한 요약 데이터 구성
        rec_nums = next((p['predicted_numbers'] for p in predictions if p['prediction_type'] == 'recommendation'), [])
        exc_nums = next((p['predicted_numbers'] for p in predictions if p['prediction_type'] == 'exclusion'), [])
        
        report_context = {
            "round": target_round,
            "recommendations": rec_nums,
            "exclusions": exc_nums,
            "trend": "딥러닝 모델 분석 완료. 상승세 패턴 감지." # 실제로는 통계 분석 결과 삽입
        }
        
        # 실제로는 report_chain을 호출하여 생성된 텍스트를 DB나 파일로 저장
        # 여기서는 로그로만 출력
        logger.info(f"   [Report Preview] {target_round}회차: 추천 {rec_nums}, 제외 {exc_nums}")
        
        # TODO: reports 테이블에 저장하거나 알림 발송
