-- =====================================================
-- Phase 1 Migration: model_predictions 테이블 생성
-- 날짜: 2026-02-26
-- 목적: 각 모델의 회차별 예측 기록 및 적중률 추적
-- =====================================================

CREATE TABLE IF NOT EXISTS model_predictions (
    id           SERIAL PRIMARY KEY,
    round_number INT  NOT NULL,
    model_name   TEXT NOT NULL,

    -- 해당 회차에서 모델이 예측한 상위 10개 번호
    predicted_top10 INT[] NOT NULL,

    -- 실제 당첨번호 (회차 확정 후 업데이트)
    actual_numbers  INT[] DEFAULT NULL,

    -- predicted_top10 중 actual_numbers에 포함된 번호 수 (0~6)
    hit_count INT DEFAULT 0,

    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- 같은 회차·모델 조합은 1건만 유지
    UNIQUE(round_number, model_name)
);

-- 인덱스: 모델별 성적 조회 최적화
CREATE INDEX IF NOT EXISTS idx_model_predictions_model_round
    ON model_predictions (model_name, round_number DESC);

-- 인덱스: 미확정 회차 일괄 업데이트용
CREATE INDEX IF NOT EXISTS idx_model_predictions_unresolved
    ON model_predictions (round_number)
    WHERE actual_numbers IS NULL;

-- RLS 비활성화 (개인 프로젝트)
ALTER TABLE model_predictions DISABLE ROW LEVEL SECURITY;

-- =====================================================
-- 롤백 스크립트 (필요 시 수동 실행)
-- DROP TABLE IF EXISTS model_predictions;
-- =====================================================
