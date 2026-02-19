-- ============================================
-- AI 커스텀 분석 & 히스토리 테이블 고도화 SQL (v2)
-- 'name' 컬럼이 없는 경우를 위해 보완된 버전입니다.
-- ============================================

-- 1. ai_custom_analyses 테이블 컬럼 확장
ALTER TABLE ai_custom_analyses 
ADD COLUMN IF NOT EXISTS title VARCHAR(100),
ADD COLUMN IF NOT EXISTS type VARCHAR(50) DEFAULT 'static',
ADD COLUMN IF NOT EXISTS target_numbers INTEGER[] DEFAULT '{}',
ADD COLUMN IF NOT EXISTS filter_config JSONB DEFAULT '{"min": 1, "max": 3, "enabled": false}';

-- 2. analysis_history 테이블 컬럼 확장 (커스텀 분석용)
ALTER TABLE analysis_history 
ADD COLUMN IF NOT EXISTS analysis_id UUID REFERENCES ai_custom_analyses(id) ON DELETE CASCADE,
ADD COLUMN IF NOT EXISTS target_numbers INTEGER[] DEFAULT '{}';

-- 3. upsert를 위한 유니크 제약 조건 추가 (분석ID + 회차 조합)
-- 기존에 (analysis_id, target_round) 유니크 제약이 없다면 새로 추가합니다.
DO $$ 
BEGIN 
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'analysis_history_analysis_id_target_round_key') THEN
        ALTER TABLE analysis_history ADD CONSTRAINT analysis_history_analysis_id_target_round_key UNIQUE (analysis_id, target_round);
    END IF;
EXCEPTION
    WHEN others THEN
        RAISE NOTICE 'Constraint already exists or could not be created.';
END $$;
