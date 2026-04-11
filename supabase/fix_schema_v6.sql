-- ============================================
-- fix_schema_v6.sql
-- 누락된 filter_definitions 항목 추가
-- - missing_period (미출현 그룹 구간 필터)
-- - missing_custom_filter (미출현 커스텀 그룹 필터)
-- - number_range_patterns (번호 구간 필터)
-- ============================================

INSERT INTO filter_definitions (filter_key, filter_name, filter_type, ui_group, display_order, is_active, default_settings)
VALUES
(
  'missing_period',
  '미출현 그룹',
  'multi_range',
  'pattern',
  145,
  true,
  '{"enabled": false, "ranges": {"r1Min": 0, "r1Max": 6, "r2Min": 0, "r2Max": 6, "r3Min": 0, "r3Max": 6, "r4Min": 0, "r4Max": 6}}'
),
(
  'missing_custom_filter',
  '미출현 커스텀',
  'custom_groups',
  'pattern',
  146,
  true,
  '{"enabled": false, "filters": [], "counter": 1}'
),
(
  'number_range_patterns',
  '번호 구간 패턴',
  'multi_range',
  'pattern',
  150,
  true,
  '{"enabled": false, "ranges": {"1_10": {"min": 0, "max": 6}, "11_20": {"min": 0, "max": 6}, "21_30": {"min": 0, "max": 6}, "31_40": {"min": 0, "max": 6}, "41_45": {"min": 0, "max": 6}, "entropy": {"min": "0.00", "max": "3.00"}}}'
)
ON CONFLICT (filter_key)
DO UPDATE SET
  filter_name = EXCLUDED.filter_name,
  filter_type = EXCLUDED.filter_type,
  ui_group = EXCLUDED.ui_group,
  display_order = EXCLUDED.display_order,
  is_active = EXCLUDED.is_active,
  default_settings = EXCLUDED.default_settings;

-- 확인
SELECT filter_key, filter_name, is_active, display_order
FROM filter_definitions
WHERE filter_key IN ('missing_period', 'missing_custom_filter', 'number_range_patterns')
ORDER BY display_order;
