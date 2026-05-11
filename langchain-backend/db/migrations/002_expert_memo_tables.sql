-- ============================================================
-- Stage 3-5: Expert Memo 학습 시그널 테이블
-- expert_memos + expert_memo_history
-- ============================================================

-- expert_memos: 사용자 전문가 메모 저장
CREATE TABLE IF NOT EXISTS expert_memos (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id           UUID,                                   -- nullable (공용 메모 가능)
  target_round      INTEGER       NOT NULL,                 -- 메모 적용 회차 (1223 등)
  memo_text         TEXT,                                   -- 사용자 자연어 메모
  forced_includes   INTEGER[]     DEFAULT '{}',             -- 강제 추천 번호
  forced_excludes   INTEGER[]     DEFAULT '{}',             -- 강제 제외 번호
  domain_tags       TEXT[]        DEFAULT '{}',             -- 자동 태깅 (예: ["회귀", "끝수", "고저"])
  confidence        NUMERIC(3,2)  DEFAULT 0.50,             -- 0~1, 사용자 신뢰도 입력
  created_at        TIMESTAMPTZ   DEFAULT NOW(),
  updated_at        TIMESTAMPTZ   DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_expert_memos_target_round
  ON expert_memos(target_round DESC);

CREATE INDEX IF NOT EXISTS idx_expert_memos_user_id
  ON expert_memos(user_id);

-- expert_memo_history: 메모 적중률 추적
CREATE TABLE IF NOT EXISTS expert_memo_history (
  id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  memo_id                   UUID          REFERENCES expert_memos(id) ON DELETE CASCADE,
  target_round              INTEGER       NOT NULL,                 -- 평가 회차
  actual_numbers            INTEGER[]     DEFAULT '{}',             -- 실제 당첨번호
  forced_includes_hit       INTEGER       DEFAULT 0,                -- forced_includes 중 적중 카운트
  forced_excludes_correct   INTEGER       DEFAULT 0,                -- forced_excludes 중 미당첨 카운트
  memo_score                NUMERIC(4,3)  DEFAULT 0.000,            -- 회차별 메모 적중률
  memo_hit_rate_window      NUMERIC(4,3)  DEFAULT 0.000,            -- 누적 50회 평균 적중률
  memo_domain_confidence    NUMERIC(4,3)  DEFAULT 0.500,            -- sigmoid 신뢰도 (0~1)
  created_at                TIMESTAMPTZ   DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_expert_memo_history_memo_id
  ON expert_memo_history(memo_id);

CREATE INDEX IF NOT EXISTS idx_expert_memo_history_target_round
  ON expert_memo_history(target_round DESC);

-- RLS: anon read + anon write (프론트엔드 메모 작성 허용)
ALTER TABLE expert_memos ENABLE ROW LEVEL SECURITY;
ALTER TABLE expert_memo_history ENABLE ROW LEVEL SECURITY;

CREATE POLICY "expert_memos_read"
  ON expert_memos FOR SELECT
  USING (true);

CREATE POLICY "expert_memos_write"
  ON expert_memos FOR ALL
  USING (true);

CREATE POLICY "expert_memo_history_read"
  ON expert_memo_history FOR SELECT
  USING (true);

CREATE POLICY "expert_memo_history_write"
  ON expert_memo_history FOR ALL
  USING (true);
