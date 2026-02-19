-- deep_analysis_history 테이블 생성
-- AI 딥러닝 심층 분석 v2의 회차별 이력을 저장한다.
-- Supabase Dashboard > SQL Editor에서 실행하세요.

CREATE TABLE IF NOT EXISTS deep_analysis_history (
    id BIGSERIAL PRIMARY KEY,
    target_round INTEGER NOT NULL,
    confidence INTEGER DEFAULT 0,
    summary TEXT DEFAULT '',
    analysis_data JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_dah_target_round ON deep_analysis_history (target_round);
CREATE INDEX IF NOT EXISTS idx_dah_created_at ON deep_analysis_history (created_at DESC);

-- RLS 비활성화 (프로젝트 내부 사용)
ALTER TABLE deep_analysis_history ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow all for deep_analysis_history"
    ON deep_analysis_history FOR ALL
    USING (true)
    WITH CHECK (true);

-- 자동 정리: 30건 초과 시 가장 오래된 것 삭제 (선택사항)
-- 수동 정리가 필요한 경우:
-- DELETE FROM deep_analysis_history WHERE id NOT IN (
--     SELECT id FROM deep_analysis_history ORDER BY created_at DESC LIMIT 30
-- );
