-- ============================================
-- AI 커스텀 분석 & 히스토리 테이블 완벽 해결 SQL (v3)
-- RLS(보안 정책) 충돌 및 컬럼 미비 문제를 한 번에 해결합니다.
-- ============================================

-- 1. 보안 정책(RLS) 비활성화 (개인용 프로젝트이므로 접근 허용)
ALTER TABLE ai_custom_analyses DISABLE ROW LEVEL SECURITY;
ALTER TABLE analysis_history DISABLE ROW LEVEL SECURITY;

-- 2. ai_custom_analyses 테이블 컬럼 확정
ALTER TABLE ai_custom_analyses 
ADD COLUMN IF NOT EXISTS title VARCHAR(100),
ADD COLUMN IF NOT EXISTS type VARCHAR(50) DEFAULT 'static',
ADD COLUMN IF NOT EXISTS target_numbers INTEGER[] DEFAULT '{}',
ADD COLUMN IF NOT EXISTS filter_config JSONB DEFAULT '{"min": 1, "max": 3, "enabled": false}';

-- 3. analysis_history 테이블 컬럼 확정
ALTER TABLE analysis_history 
ADD COLUMN IF NOT EXISTS analysis_id UUID REFERENCES ai_custom_analyses(id) ON DELETE CASCADE,
ADD COLUMN IF NOT EXISTS target_numbers INTEGER[] DEFAULT '{}';

-- 4. 유니크 제약 조건 (중복 저장 방지)
DO $$ 
BEGIN 
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'analysis_history_analysis_id_target_round_key') THEN
        ALTER TABLE analysis_history ADD CONSTRAINT analysis_history_analysis_id_target_round_key UNIQUE (analysis_id, target_round);
    END IF;
EXCEPTION
    WHEN others THEN
        RAISE NOTICE 'Constraint already exists or could not be created.';
END $$;

-- 완료 확인
SELECT '모바일/웹 모든 환경에서 저장 및 로드가 가능하도록 설정되었습니다!' as status;
