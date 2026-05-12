-- =============================================================================
-- 003_formula_sweep_tables.sql
--
-- Formula Variable Sweep — DB 스키마
--
-- 적용 상태: Applied 2026-05-13 via mcp__supabase__apply_migration
--             migration name: add_formula_sweep_tables
--
-- 사용처:
--   - services/formula_sweep_engine.py (SweepResult 출력)
--   - routes/sweep.py (REST API)
--   - js/customSimulator.js (UI 결과 대시보드)
--
-- 마스터 플랜 정합: Stage 5 UI 기능 (모델/학습/pipeline 영향 0)
-- 결정론 정책: hashlib.md5 (Stage 6-F-3)
-- =============================================================================

-- 1. formula_sweep_jobs — sweep 작업 큐
CREATE TABLE IF NOT EXISTS formula_sweep_jobs (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         text,
    formula         jsonb NOT NULL,
    variable_paths  jsonb NOT NULL,
    variable_range  jsonb NOT NULL,
    criteria        jsonb NOT NULL DEFAULT '{}',
    eval_rounds     int,
    status          text NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued','running','complete','failed','cancelled')),
    progress        jsonb DEFAULT '{}',
    error_message   text,
    created_at      timestamptz DEFAULT now(),
    started_at      timestamptz,
    completed_at    timestamptz
);

COMMENT ON TABLE formula_sweep_jobs IS
  'Formula Variable Sweep 작업 큐. v5-multi 산식 + 변수 sweep range.';
COMMENT ON COLUMN formula_sweep_jobs.formula IS
  'v5-multi 워크스페이스 직렬화 { workspaces, combineOps, combinePostTransforms, ... }';
COMMENT ON COLUMN formula_sweep_jobs.variable_paths IS
  '[{ ws_id, transform_idx, field: "value" }, ...] — 변수 위치 명세';
COMMENT ON COLUMN formula_sweep_jobs.variable_range IS
  '{ min: 2, max: 1000, step: 1 }';
COMMENT ON COLUMN formula_sweep_jobs.criteria IS
  '{ min_consecutive: 3, include_bonus: true, min_avg_gap: 10 }';
COMMENT ON COLUMN formula_sweep_jobs.progress IS
  '{ current: N, total: M, eta_seconds: S }';

CREATE INDEX IF NOT EXISTS idx_sweep_jobs_user_status ON formula_sweep_jobs(user_id, status);
CREATE INDEX IF NOT EXISTS idx_sweep_jobs_created ON formula_sweep_jobs(created_at DESC);


-- 2. formula_sweep_results — 변수값별 평가 결과
CREATE TABLE IF NOT EXISTS formula_sweep_results (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id          uuid NOT NULL REFERENCES formula_sweep_jobs(id) ON DELETE CASCADE,
    variable_value  int NOT NULL,
    target_numbers  int[] NOT NULL,
    max_consecutive int NOT NULL,
    avg_gap_rounds  numeric(6,2),
    hit_count       int NOT NULL DEFAULT 0,
    total_evaluated int NOT NULL DEFAULT 0,
    history         jsonb,
    computed_at     timestamptz DEFAULT now(),

    CONSTRAINT unique_job_var UNIQUE (job_id, variable_value)
);

COMMENT ON TABLE formula_sweep_results IS
  '단일 변수값에 대한 평가 결과 (회차별 hit history + 연속/평균간격 지표).';
COMMENT ON COLUMN formula_sweep_results.target_numbers IS
  '최신 회차에서 산식이 산출한 대상수 (1~45)';
COMMENT ON COLUMN formula_sweep_results.history IS
  '[{ round, hit_count, bonus_hit, target_at_round: [...] }, ...]';

CREATE INDEX IF NOT EXISTS idx_sweep_results_job_consec ON formula_sweep_results(job_id, max_consecutive DESC);
CREATE INDEX IF NOT EXISTS idx_sweep_results_job_var ON formula_sweep_results(job_id, variable_value);


-- 3. RLS (Row Level Security) — anon SELECT 허용 (대시보드 조회용)
ALTER TABLE formula_sweep_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE formula_sweep_results ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "anon_select_sweep_jobs" ON formula_sweep_jobs;
CREATE POLICY "anon_select_sweep_jobs" ON formula_sweep_jobs
  FOR SELECT TO anon USING (true);

DROP POLICY IF EXISTS "anon_select_sweep_results" ON formula_sweep_results;
CREATE POLICY "anon_select_sweep_results" ON formula_sweep_results
  FOR SELECT TO anon USING (true);

-- service_role 전체 권한은 기본값 (RLS bypass)
