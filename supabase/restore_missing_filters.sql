-- Lotto Lab: Missing Filter Definitions Restoration Script
-- This script inserts missing filter definitions into the filter_definitions table.
-- Use this in the Supabase SQL Editor if you are missing sections like "Prime Number" on the dashboard.

INSERT INTO filter_definitions (filter_key, filter_name, filter_type, ui_group, display_order, is_active, default_settings)
VALUES 
('prime_number_patterns', '소수 패턴', 'discrete_select', 'features', 70, true, '{"selectedCounts": [0,1,2,3,4,5,6], "excludedPrimes": []}'),
('square_number_patterns', '제곱수 패턴', 'discrete_select', 'features', 80, true, '{"selectedCounts": [0,1,2,3,4,5,6], "excludedNumbers": []}'),
('triangular_number_patterns', '삼각수 패턴', 'discrete_select', 'features', 90, true, '{"selectedCounts": [0,1,2,3,4,5,6], "excludedNumbers": []}'),
('twin_number_patterns', '쌍둥이수 패턴', 'discrete_select', 'features', 100, true, '{"activeCounts": [0,1,2,3,4], "selectedNumbers": []}'),
('neighbor_number_patterns', '이웃수 패턴', 'discrete_select', 'features', 110, true, '{"selectedCounts": [0,1,2,3,4,5,6], "excludedNumbers": []}')
ON CONFLICT (filter_key) 
DO UPDATE SET 
    filter_name = EXCLUDED.filter_name,
    filter_type = EXCLUDED.filter_type,
    ui_group = EXCLUDED.ui_group,
    display_order = EXCLUDED.display_order,
    is_active = EXCLUDED.is_active,
    default_settings = EXCLUDED.default_settings;

-- Ensure RLS is disabled or privileges are granted if still facing issues
-- ALTER TABLE filter_definitions DISABLE ROW LEVEL SECURITY;
-- GRANT ALL PRIVILEGES ON filter_definitions TO anon, authenticated, service_role;
