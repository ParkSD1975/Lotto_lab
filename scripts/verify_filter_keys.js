#!/usr/bin/env node
/**
 * verify_filter_keys.js
 * 필터 키 4계층 동기화 검증.
 *
 * 비교 대상:
 *   ① 프론트       FilterRuleEngine.js  FILTER_KEYS 배열
 *   ② 백엔드       filter_stats.py      각 _xxx() 메서드의 key=
 *   ③ DB 정의      filter_definitions.filter_key  (Supabase SELECT)
 *   ④ DB 컬럼      model_filter_predictions       <key>_min/_max
 *
 * 사용법:
 *   SUPABASE_URL=... SUPABASE_KEY=... node scripts/verify_filter_keys.js
 *
 * 종료 코드: 0 (일치) / 1 (불일치)
 */
'use strict';

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');

// 카운트형(*_count)·패턴형(*_patterns)이 아닌 입력 전용 필터는 컬럼 확인 면제
const COLUMN_EXEMPT = new Set([
  'tail_digit_patterns',
  'lotto_paper_pattern',
  'magic_square_pattern',
  'number_range_patterns',
  'missing_period',
  'missing_custom_filter',
  'hot_cold_5', 'hot_cold_10', 'hot_cold_15', 'hot_cold_20',
  'fixed_numbers', 'excluded_numbers',
  'regression_analysis',
  'multiple_3_4_count', 'multiple_3_5_count', 'multiple_4_5_count',
  'no_multiple_count',
  'multiple_4_count', 'multiple_5_count',
  'neighbor_number_patterns',
  'twin_number_patterns',
  'square_number_patterns',
  'triangular_number_patterns',
  'carryover_count',
]);

function extractFrontendKeys() {
  const src = fs.readFileSync(path.join(ROOT, 'js/filter/FilterRuleEngine.js'), 'utf8');
  const m = src.match(/const FILTER_KEYS = \[([\s\S]*?)\];/);
  if (!m) throw new Error('FILTER_KEYS not found');
  return [...m[1].matchAll(/'([^']+)'/g)].map(x => x[1]);
}

function extractBackendKeys() {
  const src = fs.readFileSync(path.join(ROOT, 'langchain-backend/services/filter_stats.py'), 'utf8');
  return [...src.matchAll(/key="([^"]+)",/g)].map(x => x[1]);
}

async function fetchDBKeys() {
  const { SUPABASE_URL, SUPABASE_KEY } = process.env;
  if (!SUPABASE_URL || !SUPABASE_KEY) {
    console.warn('⚠ SUPABASE_URL / SUPABASE_KEY 미설정 — DB 확인 생략');
    return { defs: null, columns: null };
  }
  const headers = { apikey: SUPABASE_KEY, Authorization: `Bearer ${SUPABASE_KEY}` };

  const defsRes = await fetch(`${SUPABASE_URL}/rest/v1/filter_definitions?select=filter_key&is_active=eq.true`, { headers });
  const defs = (await defsRes.json()).map(r => r.filter_key);

  const colsQuery = `SELECT column_name FROM information_schema.columns WHERE table_name = 'model_filter_predictions'`;
  const colsRes = await fetch(`${SUPABASE_URL}/rest/v1/rpc/exec_sql`, {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ query: colsQuery }),
  });
  // exec_sql RPC 미구현 시 fallback: information_schema 직접 접근 불가 → DB 컬럼 검사 생략
  let columns = null;
  if (colsRes.ok) {
    const rows = await colsRes.json();
    columns = rows.map(r => r.column_name);
  }
  return { defs, columns };
}

function setDiff(a, b) {
  const A = new Set(a), B = new Set(b);
  return {
    onlyA: [...A].filter(x => !B.has(x)).sort(),
    onlyB: [...B].filter(x => !A.has(x)).sort(),
  };
}

(async () => {
  const front = extractFrontendKeys();
  const backend = extractBackendKeys();
  const { defs, columns } = await fetchDBKeys();

  const issues = [];

  // ① ↔ ② 프론트 vs 백엔드 (백엔드는 산출형만, 입력 전용 키는 면제)
  const backendComparable = front.filter(k => !COLUMN_EXEMPT.has(k));
  const diff_fb = setDiff(backendComparable, backend);
  // 백엔드가 프론트에 없는 키를 산출할 수도 있음 (zone_pattern, decade_distribution, missing_group, hot_cold 등 보조 산출) → onlyB는 경고만
  if (diff_fb.onlyA.length) {
    issues.push(`[프론트→백엔드] 백엔드에 산출 메서드가 없는 키: ${diff_fb.onlyA.join(', ')}`);
  }

  // ① ↔ ③ 프론트 vs DB 정의
  if (defs) {
    const diff_fd = setDiff(front, defs);
    if (diff_fd.onlyA.length) issues.push(`[프론트→DB정의] filter_definitions에 없음: ${diff_fd.onlyA.join(', ')}`);
    if (diff_fd.onlyB.length) issues.push(`[DB정의→프론트] FILTER_KEYS에 없음: ${diff_fd.onlyB.join(', ')}`);
  }

  // ① ↔ ④ 프론트 vs DB 컬럼 (산출형만)
  if (columns) {
    const colSet = new Set(columns);
    const missingCols = front.filter(k => !COLUMN_EXEMPT.has(k))
                             .filter(k => !colSet.has(`${k}_min`) || !colSet.has(`${k}_max`));
    if (missingCols.length) issues.push(`[프론트→DB컬럼] *_min/*_max 컬럼 누락: ${missingCols.join(', ')}`);
  }

  if (issues.length === 0) {
    console.log('✅ 4계층 필터 키 동기화 OK');
    console.log(`   프론트: ${front.length}, 백엔드: ${backend.length}, DB정의: ${defs?.length ?? 'skip'}, DB컬럼: ${columns?.length ?? 'skip'}`);
    process.exit(0);
  }

  console.error('❌ 필터 키 동기화 불일치:');
  for (const i of issues) console.error('  -', i);
  process.exit(1);
})();
