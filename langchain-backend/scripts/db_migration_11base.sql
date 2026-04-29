-- ============================================================================
-- Master Plan Stage 1-4-D-2-fix-6: 11 base 토폴로지 schema 확장
-- 사용자 결정 #24 — 11 base 전 모델 학습 + weekly_* 통일 + 프론트 노출
--
-- 11 base:
--   xgboost / catboost / tabnet                   (트리·attention)
--   cnn / gnn                                     (공간·관계)
--   markov / autoencoder                          (전이·이상치)
--   tft / mhn / bayesian_nn                       (시계열·메모리·불확실성)
--   nbeats                                        (스칼라 시계열 분해 — 메인 1~45 영역 제외)
--
-- DEPRECATED:
--   lstm / transformer  → tft 흡수 (weight 0, 컬럼은 백워드 호환 위해 보존)
--
-- 실행 방법:
--   Supabase Dashboard → SQL Editor → 본 파일 전체 복사/붙여넣기 → Run
--   (IF NOT EXISTS 안전 처리되어 있어 여러번 실행해도 부작용 없음)
-- ============================================================================

BEGIN;

-- ----------------------------------------------------------------------------
-- 1. weekly_number_xai — 신규 5 base 컬럼 추가 (메인 1~45 binary classifier)
-- ----------------------------------------------------------------------------
ALTER TABLE weekly_number_xai
  ADD COLUMN IF NOT EXISTS catboost_pct    NUMERIC DEFAULT 0,
  ADD COLUMN IF NOT EXISTS tabnet_pct      NUMERIC DEFAULT 0,
  ADD COLUMN IF NOT EXISTS tft_pct         NUMERIC DEFAULT 0,
  ADD COLUMN IF NOT EXISTS mhn_pct         NUMERIC DEFAULT 0,
  ADD COLUMN IF NOT EXISTS bayesian_nn_pct NUMERIC DEFAULT 0;

-- nbeats는 스칼라 시계열 분해 전용 — 메인 1~45 영역에는 채우지 않음.
-- 컬럼 자체는 추가 (future-proof) 하되 weekly_pipeline_v2는 null 저장.
ALTER TABLE weekly_number_xai
  ADD COLUMN IF NOT EXISTS nbeats_pct      NUMERIC DEFAULT NULL;

-- 폐기 모델 컬럼은 보존 (백워드 호환). 사용자 결정 #24로 weight 0이지만 schema는 유지.
COMMENT ON COLUMN weekly_number_xai.lstm_pct
  IS 'DEPRECATED — Stage 1-4-D-2 사용자 결정 #24, TFT 흡수. weight 0.0 저장.';
COMMENT ON COLUMN weekly_number_xai.transformer_pct
  IS 'DEPRECATED — Stage 1-4-D-2 사용자 결정 #24, TFT 흡수. weight 0.0 저장.';

COMMENT ON COLUMN weekly_number_xai.catboost_pct
  IS 'Stage 1-4-D-2 신규 base — Gradient Boosted Trees (CatBoost).';
COMMENT ON COLUMN weekly_number_xai.tabnet_pct
  IS 'Stage 1-4-D-2 신규 base — Sequential Attention (TabNet).';
COMMENT ON COLUMN weekly_number_xai.tft_pct
  IS 'Stage 1-4-D-2 신규 base — Temporal Fusion Transformer (LSTM/Transformer 흡수).';
COMMENT ON COLUMN weekly_number_xai.mhn_pct
  IS 'Stage 1-4-D-2 신규 base — Modern Hopfield Network (패턴 매칭 메모리).';
COMMENT ON COLUMN weekly_number_xai.bayesian_nn_pct
  IS 'Stage 1-4-D-2 신규 base — Bayesian NN (불확실성 분포).';
COMMENT ON COLUMN weekly_number_xai.nbeats_pct
  IS 'Stage 1-4-D-2 보조 base — N-BEATS (스칼라 시계열 분해 전용, 메인 1~45 영역에서는 NULL).';

-- ----------------------------------------------------------------------------
-- 2. weekly_predictions — 모델 활성 플래그 (있다면)
--    정확한 schema 미확인 → IF NOT EXISTS 안전 처리.
--    실제 사용 여부는 weekly_pipeline_v2.py 가 판단. 컬럼만 미리 준비.
-- ----------------------------------------------------------------------------
ALTER TABLE weekly_predictions
  ADD COLUMN IF NOT EXISTS catboost_active    BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS tabnet_active      BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS tft_active         BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS mhn_active         BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS bayesian_nn_active BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS nbeats_active      BOOLEAN DEFAULT FALSE;

-- ----------------------------------------------------------------------------
-- 3. 검증 쿼리 (확장 후 모든 11 base 컬럼 존재 여부 확인)
-- ----------------------------------------------------------------------------
SELECT
  column_name,
  data_type,
  column_default
FROM information_schema.columns
WHERE table_name = 'weekly_number_xai'
  AND column_name IN (
    'xgboost_pct', 'lstm_pct', 'cnn_pct', 'transformer_pct',
    'gnn_pct', 'markov_pct', 'autoencoder_pct',
    'catboost_pct', 'tabnet_pct', 'tft_pct',
    'mhn_pct', 'bayesian_nn_pct', 'nbeats_pct'
  )
ORDER BY column_name;

COMMIT;

-- 결과: 13 행 반환 시 정상 (legacy 7 + 신규 5 + nbeats 1 = 13).
-- 만약 일부 컬럼만 보이면 ALTER 가 실패한 것 — 권한/테이블 이름 확인.
