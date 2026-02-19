-- ============================================
-- Lotto AI v4 DB 마이그레이션
-- Supabase SQL Editor에서 실행하세요.
-- ============================================

-- 1. 신규 테이블: model_performance_log (모델 성능 추적)
CREATE TABLE IF NOT EXISTS model_performance_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    round INTEGER NOT NULL,
    model_name VARCHAR(50) NOT NULL,
    prediction_type VARCHAR(50) NOT NULL,
    predicted_numbers INTEGER[],
    actual_numbers INTEGER[],
    hit_count INTEGER DEFAULT 0,
    precision_at_6 DECIMAL(5,4),
    precision_at_10 DECIMAL(5,4),
    weight_at_prediction DECIMAL(5,4),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(round, model_name, prediction_type)
);

CREATE INDEX IF NOT EXISTS idx_perf_round ON model_performance_log(round DESC);
CREATE INDEX IF NOT EXISTS idx_perf_model ON model_performance_log(model_name);

-- 2. ai_custom_analyses 확장
ALTER TABLE ai_custom_analyses ADD COLUMN IF NOT EXISTS
    ai_evaluation JSONB DEFAULT '{}';

ALTER TABLE ai_custom_analyses ADD COLUMN IF NOT EXISTS
    evaluation_history JSONB DEFAULT '[]';

ALTER TABLE ai_custom_analyses ADD COLUMN IF NOT EXISTS
    is_ai_enabled BOOLEAN DEFAULT TRUE;

-- 3. ai_predictions 확장
ALTER TABLE ai_predictions ADD COLUMN IF NOT EXISTS
    model_contributions JSONB DEFAULT '{}';

ALTER TABLE ai_predictions ADD COLUMN IF NOT EXISTS
    ensemble_weights JSONB DEFAULT '{}';

-- 확인
SELECT 'Migration complete' AS status;
