// =====================================================
// Phase 4 — RL 조합 생성기 테스트
// =====================================================

import { assertEquals, assertAlmostEquals } from "https://deno.land/std@0.168.0/testing/asserts.ts";
import {
  sampleCombination,
  calcReward,
  selectDiverse,
  runRL,
  runRLWithFallback,
} from "../modules/rlCombinator.ts";
import {
  calcSum,
  calcOddCount,
  calcACValue,
  calcConsecutivePairs,
  passesAllFilters,
} from "../modules/filters.ts";

// ─────────────────────────────────────────────────
// 헬퍼
// ─────────────────────────────────────────────────

const noCompatibility = (_a: number, _b: number) => 0;
const uniformScores: Record<number, number> = Object.fromEntries(
  Array.from({ length: 45 }, (_, i) => [i + 1, 1 / 45])
);

// ─────────────────────────────────────────────────
// sampleCombination 테스트
// ─────────────────────────────────────────────────

Deno.test("sampleCombination: 6개 번호를 반환한다", () => {
  const scores = Array(45).fill(1 / 45);
  const combo = sampleCombination(scores);
  assertEquals(combo.length, 6);
});

Deno.test("sampleCombination: 번호가 1~45 범위 내", () => {
  const scores = Array(45).fill(1 / 45);
  for (let trial = 0; trial < 20; trial++) {
    const combo = sampleCombination(scores);
    for (const n of combo) {
      assertEquals(n >= 1 && n <= 45, true, `번호 ${n}이 범위 초과`);
    }
  }
});

Deno.test("sampleCombination: 중복 없음", () => {
  const scores = Array(45).fill(1 / 45);
  for (let trial = 0; trial < 20; trial++) {
    const combo = sampleCombination(scores);
    const unique = new Set(combo);
    assertEquals(unique.size, 6, `중복 발생: ${combo}`);
  }
});

Deno.test("sampleCombination: 오름차순 정렬", () => {
  const scores = Array(45).fill(1 / 45);
  for (let trial = 0; trial < 20; trial++) {
    const combo = sampleCombination(scores);
    for (let i = 0; i < combo.length - 1; i++) {
      assertEquals(combo[i] < combo[i + 1], true);
    }
  }
});

Deno.test("sampleCombination: 높은 점수 번호가 더 자주 선택된다", () => {
  // 1~5번에 90% 확률 집중
  const scores = Array(45).fill(0.1 / 40);
  for (let i = 0; i < 5; i++) scores[i] = 0.9 / 5;

  let hotCount = 0;
  const TRIALS = 200;
  for (let t = 0; t < TRIALS; t++) {
    const combo = sampleCombination(scores);
    hotCount += combo.filter((n) => n <= 5).length;
  }
  // 200회 * 평균 기대값 ≈ 5.4개 → 최소 3개 이상 평균
  assertEquals(hotCount / TRIALS > 3, true);
});

// ─────────────────────────────────────────────────
// calcReward 테스트
// ─────────────────────────────────────────────────

Deno.test("calcReward: 필터 미충족 → 0 반환", () => {
  const numbers = [1, 2, 3, 4, 5, 6]; // 총합 21
  const r = calcReward(
    numbers,
    uniformScores,
    noCompatibility,
    { sumRange: [100, 200] } // 필터 불충족
  );
  assertEquals(r, 0);
});

Deno.test("calcReward: 필터 통과 → 양수 반환", () => {
  const numbers = [5, 12, 19, 27, 34, 42]; // 총합 139
  const r = calcReward(
    numbers,
    uniformScores,
    noCompatibility,
    { sumRange: [100, 180] }
  );
  assertEquals(r > 0, true);
});

Deno.test("calcReward: 필터 없음 → 항상 양수", () => {
  const numbers = [3, 11, 22, 31, 38, 44];
  const r = calcReward(numbers, uniformScores, noCompatibility, {});
  assertEquals(r > 0, true);
});

// ─────────────────────────────────────────────────
// runRL 통합 테스트
// ─────────────────────────────────────────────────

Deno.test("runRL: 요청한 게임 수만큼 반환한다 (필터 없음)", () => {
  const results = runRL(
    {
      numberScores: uniformScores,
      compatibility: noCompatibility,
      filters: {},
      numGames: 10,
    },
    3000
  );
  assertEquals(results.length, 10);
});

Deno.test("runRL: 각 조합은 6개 번호, 1~45, 중복 없음, 오름차순", () => {
  const results = runRL(
    { numberScores: uniformScores, compatibility: noCompatibility, filters: {}, numGames: 5 },
    2000
  );
  for (const r of results) {
    assertEquals(r.numbers.length, 6);
    const unique = new Set(r.numbers);
    assertEquals(unique.size, 6);
    for (const n of r.numbers) assertEquals(n >= 1 && n <= 45, true);
    for (let i = 0; i < r.numbers.length - 1; i++) {
      assertEquals(r.numbers[i] < r.numbers[i + 1], true);
    }
  }
});

Deno.test("runRL: 10게임 간 중복 조합 없음", () => {
  const results = runRL(
    { numberScores: uniformScores, compatibility: noCompatibility, filters: {}, numGames: 10 },
    5000
  );
  const keys = results.map((r) => r.numbers.join("-"));
  const unique = new Set(keys);
  assertEquals(unique.size, results.length);
});

Deno.test("runRL: 총합 필터 충족", () => {
  const results = runRL(
    {
      numberScores: uniformScores,
      compatibility: noCompatibility,
      filters: { sumRange: [100, 200] },
      numGames: 5,
    },
    5000
  );
  for (const r of results) {
    const s = calcSum(r.numbers);
    assertEquals(s >= 100 && s <= 200, true, `총합 ${s} 범위 초과`);
  }
});

Deno.test("runRL: rank 순서가 1부터 순서대로", () => {
  const results = runRL(
    { numberScores: uniformScores, compatibility: noCompatibility, filters: {}, numGames: 5 },
    2000
  );
  results.forEach((r, i) => assertEquals(r.rank, i + 1));
});

// ─────────────────────────────────────────────────
// selectDiverse 테스트
// ─────────────────────────────────────────────────

Deno.test("selectDiverse: 4개 이상 겹치는 조합을 배제한다", () => {
  const base = [1, 2, 3, 4, 5, 6];
  const similar = [1, 2, 3, 4, 5, 7];  // 5개 겹침 → 배제
  const different = [7, 8, 9, 10, 11, 12]; // 0개 겹침 → 포함

  const candidates = [
    { numbers: base, reward: 1.0 },
    { numbers: similar, reward: 0.9 },
    { numbers: different, reward: 0.8 },
  ];

  const selected = selectDiverse(candidates, 2);
  assertEquals(selected.length, 2);
  assertEquals(selected[0].numbers, base);
  assertEquals(selected[1].numbers, different);
});
