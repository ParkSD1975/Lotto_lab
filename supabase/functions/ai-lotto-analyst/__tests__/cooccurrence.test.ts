// =====================================================
// Phase 1 — 동반출현 행렬 테스트
// Deno 테스트 러너 사용: deno test
// =====================================================

import { assertEquals, assertAlmostEquals } from "https://deno.land/std@0.168.0/testing/asserts.ts";
import {
  buildCoOccurrenceMatrix,
  buildRawCoOccurrence,
  normalizeCoOccurrence,
  makePairKey,
  getPairScore,
  isSymmetric,
} from "../modules/cooccurrence.ts";
import type { LottoDraw } from "../types.ts";

// ─────────────────────────────────────────────────
// 샘플 데이터
// ─────────────────────────────────────────────────

const SAMPLE_DRAWS: LottoDraw[] = [
  { round: 1, numbers: [1, 2, 3, 4, 5, 6] },
  { round: 2, numbers: [1, 2, 7, 8, 9, 10] },
  { round: 3, numbers: [3, 4, 11, 12, 13, 14] },
];

// ─────────────────────────────────────────────────
// makePairKey 테스트
// ─────────────────────────────────────────────────

Deno.test("makePairKey: 항상 작은 번호가 앞에 온다", () => {
  assertEquals(makePairKey(17, 3), "3-17");
  assertEquals(makePairKey(3, 17), "3-17");
  assertEquals(makePairKey(1, 45), "1-45");
  assertEquals(makePairKey(45, 1), "1-45");
});

// ─────────────────────────────────────────────────
// buildRawCoOccurrence 테스트
// ─────────────────────────────────────────────────

Deno.test("buildRawCoOccurrence: 정확한 동반출현 횟수를 계산한다", () => {
  const raw = buildRawCoOccurrence(SAMPLE_DRAWS);

  // 1-2 쌍: 회차 1, 2에서 등장 → 2회
  assertEquals(raw.get("1-2"), 2);

  // 3-4 쌍: 회차 1, 3에서 등장 → 2회
  assertEquals(raw.get("3-4"), 2);

  // 1-7 쌍: 회차 2에서만 → 1회
  assertEquals(raw.get("1-7"), 1);

  // 1-3 쌍: 회차 1에서만 → 1회
  assertEquals(raw.get("1-3"), 1);

  // 존재하지 않는 쌍 (5번과 11번은 같은 회차에 없음)
  assertEquals(raw.get("5-11"), undefined);
});

Deno.test("buildRawCoOccurrence: 각 회차에서 C(6,2)=15쌍이 생성된다", () => {
  const singleDraw: LottoDraw[] = [{ round: 1, numbers: [1, 2, 3, 4, 5, 6] }];
  const raw = buildRawCoOccurrence(singleDraw);
  assertEquals(raw.size, 15); // C(6,2) = 15
});

Deno.test("buildRawCoOccurrence: 빈 배열 → 빈 Map", () => {
  const raw = buildRawCoOccurrence([]);
  assertEquals(raw.size, 0);
});

// ─────────────────────────────────────────────────
// normalizeCoOccurrence 테스트
// ─────────────────────────────────────────────────

Deno.test("normalizeCoOccurrence: 정규화 점수가 0~1 범위이다", () => {
  const raw = buildRawCoOccurrence(SAMPLE_DRAWS);
  const normalized = normalizeCoOccurrence(raw);

  for (const score of normalized.values()) {
    assertEquals(score >= 0 && score <= 1, true, `점수 ${score}가 0~1 범위를 벗어남`);
  }
});

Deno.test("normalizeCoOccurrence: 최대 빈도 쌍의 점수가 1.0이다", () => {
  const raw = buildRawCoOccurrence(SAMPLE_DRAWS);
  const normalized = normalizeCoOccurrence(raw);

  let maxScore = 0;
  for (const score of normalized.values()) {
    if (score > maxScore) maxScore = score;
  }
  assertAlmostEquals(maxScore, 1.0, 0.0001);
});

Deno.test("normalizeCoOccurrence: 빈 Map → 빈 Map 반환", () => {
  const result = normalizeCoOccurrence(new Map());
  assertEquals(result.size, 0);
});

// ─────────────────────────────────────────────────
// buildCoOccurrenceMatrix 통합 테스트
// ─────────────────────────────────────────────────

Deno.test("buildCoOccurrenceMatrix: 빈 데이터 → 빈 행렬", () => {
  const matrix = buildCoOccurrenceMatrix([]);
  assertEquals(matrix.size, 0);
});

Deno.test("buildCoOccurrenceMatrix: 대칭 행렬 구조를 유지한다 (키가 항상 a < b)", () => {
  const matrix = buildCoOccurrenceMatrix(SAMPLE_DRAWS);
  assertEquals(isSymmetric(matrix), true);
});

Deno.test("buildCoOccurrenceMatrix: 자주 같이 나온 쌍이 높은 점수를 가진다", () => {
  const matrix = buildCoOccurrenceMatrix(SAMPLE_DRAWS);

  // 1-2 쌍 (2회) > 1-7 쌍 (1회)
  const score12 = getPairScore(matrix, 1, 2);
  const score17 = getPairScore(matrix, 1, 7);
  assertEquals(score12 > score17, true);
});

Deno.test("buildCoOccurrenceMatrix: getPairScore는 순서에 무관하게 같은 값을 반환한다", () => {
  const matrix = buildCoOccurrenceMatrix(SAMPLE_DRAWS);
  assertAlmostEquals(getPairScore(matrix, 3, 17), getPairScore(matrix, 17, 3), 0.0001);
});

Deno.test("buildCoOccurrenceMatrix: 한 번도 같이 나오지 않은 쌍은 0을 반환한다", () => {
  const matrix = buildCoOccurrenceMatrix(SAMPLE_DRAWS);
  assertEquals(getPairScore(matrix, 5, 11), 0);
});
