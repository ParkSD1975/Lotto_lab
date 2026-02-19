-- ============================================
-- AI 커스텀 분석 & 히스토리 테이블 최종 해결 SQL (v4)
-- 로그인 없이도 저장이 가능하도록 모든 제약을 해제합니다.
-- ============================================

-- 1. 보안 정책(RLS) 완전히 비활성화
ALTER TABLE ai_custom_analyses DISABLE ROW LEVEL SECURITY;
ALTER TABLE analysis_history DISABLE ROW LEVEL SECURITY;

-- 2. 필수 값 제약 해제 (user_id가 없어도 저장되도록)
ALTER TABLE analysis_history ALTER COLUMN user_id DROP NOT NULL;

-- 3. 테이블 권한 부여 (혹시 모를 401 에러 방지)
GRANT ALL ON TABLE ai_custom_analyses TO anon, authenticated;
GRANT ALL ON TABLE analysis_history TO anon, authenticated;

-- 4. ai_custom_analyses 테이블 컬럼 보완
ALTER TABLE ai_custom_analyses ADD COLUMN IF NOT EXISTS title VARCHAR(100);
ALTER TABLE ai_custom_analyses ADD COLUMN IF NOT EXISTS type VARCHAR(50) DEFAULT 'static';
ALTER TABLE ai_custom_analyses ADD COLUMN IF NOT EXISTS target_numbers INTEGER[] DEFAULT '{}';
ALTER TABLE ai_custom_analyses ADD COLUMN IF NOT EXISTS filter_config JSONB DEFAULT '{"min": 1, "max": 3, "enabled": false}';

-- 5. analysis_history 테이블 컬럼 보완
ALTER TABLE analysis_history ADD COLUMN IF NOT EXISTS analysis_id UUID REFERENCES ai_custom_analyses(id) ON DELETE CASCADE;
ALTER TABLE analysis_history ADD COLUMN IF NOT EXISTS target_numbers INTEGER[] DEFAULT '{}';

-- 6. 유니크 제약 조건 (중복 저장 방지)
DO $$ 
BEGIN 
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'analysis_history_analysis_id_target_round_key') THEN
        ALTER TABLE analysis_history ADD CONSTRAINT analysis_history_analysis_id_target_round_key UNIQUE (analysis_id, target_round);
    END IF;
END $$;

-- 최종 확인
SELECT '모바일/웹 모든 환경에서 로그인 없이도 저장 가능하게 설정되었습니다!' as status;
