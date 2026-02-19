-- ============================================
-- AI 커스텀 분석 테이블 생성 SQL
-- Supabase SQL Editor에서 실행하세요
-- ============================================

-- 1. 테이블 생성
CREATE TABLE IF NOT EXISTS ai_custom_analyses (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  
  -- 분석 정보
  name VARCHAR(100) NOT NULL,
  original_prompt TEXT NOT NULL,           -- 원본 자연어 입력
  
  -- AI 해석 결과
  interpreted_filters JSONB NOT NULL DEFAULT '[]',  -- 구조화된 필터 조건
  explanation TEXT,                         -- AI 해석 설명
  confidence DECIMAL(3,2) DEFAULT 0.85,     -- 신뢰도 (0~1)
  
  -- 필터 설정
  filter_enabled BOOLEAN DEFAULT false,     -- 필터 적용 여부
  
  -- 메타 데이터
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. 인덱스 생성
CREATE INDEX IF NOT EXISTS idx_ai_analyses_created 
ON ai_custom_analyses(created_at DESC);

-- 3. RLS (Row Level Security) 비활성화 (개인용)
ALTER TABLE ai_custom_analyses DISABLE ROW LEVEL SECURITY;

-- 4. updated_at 자동 업데이트 트리거
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_ai_custom_analyses_updated_at
  BEFORE UPDATE ON ai_custom_analyses
  FOR EACH ROW
  EXECUTE FUNCTION update_updated_at_column();

-- 5. 테스트 데이터 삽입 (선택사항)
-- INSERT INTO ai_custom_analyses (name, original_prompt, interpreted_filters, explanation, confidence)
-- VALUES (
--   '테스트 분석',
--   '홀수 3개 이상, 총합 150 이상',
--   '[{"type": "odd_count", "operator": ">=", "value": 3}, {"type": "sum_range", "min": 150, "max": 255}]',
--   '홀수 3개 이상, 총합 150 이상으로 해석했습니다.',
--   0.92
-- );

-- 완료 메시지
SELECT 'ai_custom_analyses 테이블 생성 완료!' as message;
