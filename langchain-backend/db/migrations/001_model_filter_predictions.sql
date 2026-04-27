-- ============================================================
-- Phase 4.1: model_filter_predictions 테이블 생성
-- 딥러닝 모델의 필터 범위 예측값을 회차별로 저장
-- ============================================================

CREATE TABLE IF NOT EXISTS model_filter_predictions (
  id                BIGSERIAL PRIMARY KEY,
  round_number      INTEGER       NOT NULL,          -- 예측 대상 회차
  created_at        TIMESTAMPTZ   DEFAULT NOW(),

  -- 필터 범위 예측값 (앙상블 시뮬레이션 결과)
  sum_min           INTEGER,
  sum_max           INTEGER,
  ac_value_min      INTEGER,
  ac_value_max      INTEGER,
  odd_count_min     INTEGER,
  odd_count_max     INTEGER,
  high_count_min    INTEGER,                         -- 23번 이상 개수
  high_count_max    INTEGER,
  consecutive_max   INTEGER,                         -- 최대 연속번호 수
  tail_sum_min      INTEGER,
  tail_sum_max      INTEGER,
  prime_min         INTEGER,
  prime_max         INTEGER,
  composite_min     INTEGER,
  composite_max     INTEGER,

  -- 전체 range_analysis JSON (모델별 min/max 포함)
  full_range_data   JSONB,                           -- range_analysis 전체 저장

  -- 출처 정보
  source_model      VARCHAR(50)   NOT NULL,          -- 'ensemble', 'llm_corrected', 모델명
  confidence        NUMERIC(4,3)  DEFAULT 0.500,     -- 0.000 ~ 1.000

  -- 검증 결과 (추첨 후 업데이트)
  actual_sum        INTEGER,
  actual_ac_value   INTEGER,
  actual_odd_count  INTEGER,
  in_range_sum      BOOLEAN,
  in_range_ac       BOOLEAN,
  in_range_odd      BOOLEAN,
  verified_at       TIMESTAMPTZ,

  UNIQUE(round_number, source_model)
);

CREATE INDEX IF NOT EXISTS idx_mfp_round
  ON model_filter_predictions(round_number DESC);

CREATE INDEX IF NOT EXISTS idx_mfp_source
  ON model_filter_predictions(source_model);

-- RLS: 인증 없이 읽기 가능 (filter.html 프론트에서 직접 조회)
ALTER TABLE model_filter_predictions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "model_filter_predictions_read"
  ON model_filter_predictions FOR SELECT
  USING (true);

CREATE POLICY "model_filter_predictions_write"
  ON model_filter_predictions FOR ALL
  USING (true);
