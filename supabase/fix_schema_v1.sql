-- ============================================
-- AI 커스텀 분석 & 히스토리 테이블 고도화 SQL
-- ============================================

-- 1. ai_custom_analyses 테이블 컬럼 확장
ALTER TABLE ai_custom_analyses 
ADD COLUMN IF NOT EXISTS title VARCHAR(100),
ADD COLUMN IF NOT EXISTS type VARCHAR(50) DEFAULT 'static',
ADD COLUMN IF NOT EXISTS target_numbers INTEGER[] DEFAULT '{}',
ADD COLUMN IF NOT EXISTS filter_config JSONB DEFAULT '{"min": 1, "max": 3, "enabled": false}';

-- 기존 name 데이터를 title로 이관 (데이터 보존용)
UPDATE ai_custom_analyses SET title = name WHERE title IS NULL;

-- 2. analysis_history 테이블 컬럼 확장 (커스텀 분석용)
ALTER TABLE analysis_history 
ADD COLUMN IF NOT EXISTS analysis_id UUID REFERENCES ai_custom_analyses(id) ON DELETE CASCADE,
ADD COLUMN IF NOT EXISTS target_numbers INTEGER[] DEFAULT '{}';

-- 3. upsert를 위한 유니크 제약 조건 추가 (분석ID + 회차 조합)
-- 주의: 이미 중복된 (analysis_id, target_round) 데이터가 있다면 제약 조건 생성에 실패할 수 있습니다.
DO $$ 
BEGIN 
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'analysis_history_analysis_id_target_round_key') THEN
        ALTER TABLE analysis_history ADD CONSTRAINT analysis_history_analysis_id_target_round_key UNIQUE (analysis_id, target_round);
    END IF;
END $$;

-- 4. RLS 정책 확인 (테스트를 위해 잠시 비활성화 권장하거나 정책 추가 필요)
-- ALTER TABLE analysis_history DISABLE ROW LEVEL SECURITY;
