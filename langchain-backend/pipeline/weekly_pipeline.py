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
        """지난주 예측 결과 채점 및 모델 성능 기록."""
        logger.info(f"[Stage 2] Verifying predictions for round {actual_round}...")
        
        # 1. 실제 당첨 번호 조회
        response = self.supabase.table("lotto_draws").select("numbers").eq("round", actual_round).execute()
        if not response.data:
            logger.warning("   실제 당첨 정보를 찾을 수 없어 검증을 건너뜁니다.")
            return

        actual_numbers = set(response.data[0]['numbers'])
        
        # 2. 해당 회차에 대한 AI 예측 조회
        preds = self.supabase.table("ai_predictions").select("*").eq("target_round", actual_round).execute()
        
        for pred in preds.data:
            predicted_nums = set(pred['predicted_numbers'])
            hit_count = len(actual_numbers & predicted_nums)
            
            # 예측 결과(hit_count) 업데이트
            self.supabase.table("ai_predictions").update({"hit_count": hit_count}).eq("id", pred['id']).execute()
            
            # 모델 성능 로그 기록 (model_performance_log)
            # (상세 구현은 생략, 필요 시 추가)
            
        logger.info(f"   {len(preds.data)}건의 지난 예측 검증 완료.")

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
