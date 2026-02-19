-- =====================================================
-- Lotto AI v3.0 Integrated Schema
-- =====================================================
-- 목표: 딥러닝 예측, 전체 통계, 커스텀 분석 성과를 통합 관리
-- 작성일: 2026-02-01

-- 1. AI 예측 결과 테이블 (Deep Learning Engine Output)
CREATE TABLE IF NOT EXISTS ai_predictions (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    round INTEGER NOT NULL, -- 회차
    
    -- 예측 데이터
    probabilities JSONB NOT NULL, -- { "1": 0.85, "2": 0.12, ... }
    recommended_numbers INTEGER[] DEFAULT '{}', -- 상위 10수
    excluded_numbers INTEGER[] DEFAULT '{}', -- 하위 10수
    
    -- 필터 추천 (AI가 시뮬레이션한 최적 조건)
    suggested_filters JSONB DEFAULT '{}', 
    -- 예: { "sum_range": [120, 150], "odd_even": [3, 3] }

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(round)
);

-- 2. 전체 통계 요약 (Stats Summary for All Rounds)
-- 기존 analysis_history와 달리, '전체 회차' 기준의 누적 통계를 저장
CREATE TABLE IF NOT EXISTS stats_summary (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    category VARCHAR(50) NOT NULL, -- 'odd_even', 'sum', 'ac', 'edge_sums'
    period INTEGER DEFAULT 0, -- 0 = 전체 회차 (기본값)
    
    -- 통계 데이터 (JSONB로 유연하게 저장)
    stats_data JSONB NOT NULL,
    -- 예: { "average": 134, "hot_numbers": [...], "cold_numbers": [...] }
    
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(category, period)
);

-- 3. 커스텀 분석 성과 추적 (Integration with User Rules)
-- 사용자가 만든 커스텀 분석이 최근 얼마나 적중했는지 추적하여 AI가 '추천'할 수 있게 함
CREATE TABLE IF NOT EXISTS custom_analysis_performance (
    analysis_id UUID REFERENCES ai_custom_analyses(id) ON DELETE CASCADE,
    
    -- 성과 지표
    recent_accuracy FLOAT DEFAULT 0, -- 최근 5회 적중률
    current_streak INTEGER DEFAULT 0, -- 연속 적중 횟수
    last_hit_round INTEGER, -- 마지막 적중 회차
    
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (analysis_id)
);

-- 4. RLS (Row Level Security) 설정 - 개인 프로젝트이므로 끄기
ALTER TABLE ai_predictions DISABLE ROW LEVEL SECURITY;
ALTER TABLE stats_summary DISABLE ROW LEVEL SECURITY;
ALTER TABLE custom_analysis_performance DISABLE ROW LEVEL SECURITY;

-- 5. 인덱스 (성능 최적화)
CREATE INDEX IF NOT EXISTS idx_ai_predictions_round ON ai_predictions(round);
CREATE INDEX IF NOT EXISTS idx_custom_perf_accuracy ON custom_analysis_performance(recent_accuracy DESC);

SELECT 'Lotto AI v3.0 DB Schema Created!' as status;
