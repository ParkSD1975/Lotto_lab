-- ──────────────────────────────────────────────────────────────────────
-- P5. recommendation_backtest_runs.pillar_scores 임시 정리
-- ──────────────────────────────────────────────────────────────────────
-- 목적: 50회 모두 동일한 더미값을 NULL로 초기화하여
--       UI에 거짓 정보가 표시되는 것을 방지
--
-- 근거: Lotto_lab_Root_Cause_Diagnosis.md Finding #1
--      4-Pillar 코드가 저장소에 존재하지 않음 (검색 0건)
--      현재 데이터는 backfill SQL로 일괄 INSERT된 더미값
--
-- 패치 일자: 2026-05-11
-- 옵션: B (임시 정리). 옵션 A (실제 구현)는 services/pillar_scorer.py 작성 필요
-- ──────────────────────────────────────────────────────────────────────

-- 1) 적용 전 상태 확인
SELECT
  COUNT(*) AS total_rows,
  COUNT(DISTINCT pillar_scores::text) AS distinct_values,
  pillar_scores AS sample_value
FROM recommendation_backtest_runs
GROUP BY pillar_scores
ORDER BY COUNT(*) DESC
LIMIT 3;

-- 기대: 1개 row, distinct_values=1, sample_value=({"CNS":-0.0133,"ENS":0.0343,"FLT":0,"STA":0.0015})


-- 2) 트랜잭션 시작
BEGIN;

-- 3) 백업 view (롤백 안전망)
CREATE OR REPLACE VIEW _bk_pillar_scores_20260511 AS
  SELECT id, target_round, pillar_scores, pillar_shap
  FROM recommendation_backtest_runs
  WHERE pillar_scores IS NOT NULL OR pillar_shap IS NOT NULL;

-- 4) NULL 초기화
UPDATE recommendation_backtest_runs
SET
  pillar_scores = NULL,
  pillar_shap = NULL
WHERE pillar_scores IS NOT NULL
   OR pillar_shap IS NOT NULL;

-- 5) 적용 후 확인
SELECT
  COUNT(*) AS total_rows,
  COUNT(*) FILTER (WHERE pillar_scores IS NULL) AS null_count,
  COUNT(*) FILTER (WHERE pillar_scores IS NOT NULL) AS non_null_count
FROM recommendation_backtest_runs;

-- 기대: null_count = total_rows, non_null_count = 0

-- 6) 문제 없으면 COMMIT
COMMIT;


-- ──────────────────────────────────────────────────────────────────────
-- 롤백 (필요 시)
-- ──────────────────────────────────────────────────────────────────────
-- UPDATE recommendation_backtest_runs r
-- SET
--   pillar_scores = bk.pillar_scores,
--   pillar_shap = bk.pillar_shap
-- FROM _bk_pillar_scores_20260511 bk
-- WHERE r.id = bk.id;
--
-- DROP VIEW _bk_pillar_scores_20260511;


-- ──────────────────────────────────────────────────────────────────────
-- 7) (선택) 컬럼 자체 임시 archive — 옵션 B+
-- ──────────────────────────────────────────────────────────────────────
-- UI 코드에서 컬럼 참조 중인 경우 NULL 처리만으로 충분.
-- 코드에서 완전히 사용 안 하고 향후 옵션 A 구현 예정이라면 컬럼 보존.
-- 단, 미래에 다시 backfill 더미값 INSERT되는 것 방지하려면 trigger 추가:

CREATE OR REPLACE FUNCTION prevent_dummy_pillar_scores()
RETURNS TRIGGER AS $$
BEGIN
  -- 알려진 더미값 INSERT 차단
  IF NEW.pillar_scores::text = '{"CNS": -0.0133, "ENS": 0.0343, "FLT": 0, "STA": 0.0015}' THEN
    RAISE EXCEPTION 'Dummy pillar_scores INSERT blocked. Implement services/pillar_scorer.py first.';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- (선택) 트리거 활성화:
-- CREATE TRIGGER trg_prevent_dummy_pillar_scores
-- BEFORE INSERT OR UPDATE ON recommendation_backtest_runs
-- FOR EACH ROW EXECUTE FUNCTION prevent_dummy_pillar_scores();
