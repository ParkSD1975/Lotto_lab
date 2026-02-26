// =====================================================
// Phase 3 — GNN 궁합 분석 테스트
// =====================================================

import { assertEquals, assertAlmostEquals } from "https://deno.land/std@0.168.0/testing/asserts.ts";
import {
  buildGNNContext,
  computeNeighborScores,
  getCompatibility,
  getCombinationCompatibility,
  getAverageCompatibility,
  applyGNNCorrection,
  getTopCompatiblePairs,
} from "../modules/gnn.ts";
import { buildCoOccurrenceMatrix } from "../modules/cooccurrence.ts";
import type { LottoDraw } from "../types.ts";

// ─────────────────────────────────────────────────
// 샘플 데이터
// ─────────────────────────────────────────────────

// 1-2, 3-4, 10-11 쌍이 자주 등장하도록 설계
const SAMPLE_DRAWS: LottoDraw[] = [
  { round: 1,  numbers: [1,  2,  3,  4, 20, 21] },
  { round: 2,  numbers: [1,  2,  5,  6, 22, 23] },
  { round: 3,  numbers: [1,  2, 10, 11, 24, 25] },
  { round: 4,  numbers: [3,  4, 10, 11, 26, 27] },
  { round: 5,  numbers: [3,  4, 12, 13, 28, 29] },
  { round: 6,  numbers: [1,  2,  7,  8, 30, 31] },
  { round: 7,  numbers: [3,  4,  9, 14, 32, 33] },
  { round: 8,  numbers: [1,  2, 15, 16, 34, 35] },
  { round: 9,  numbers: [3,  4, 17, 18, 36, 37] },
  { round: 10, numbers: [1,  2, 19, 40, 41, 42] },
];

// ─────────────────────────────────────────────────
// computeNeighborScores 테스트
// ─────────────────────────────────────────────────

Deno.test("computeNeighborScores: 빈 행렬 → 모든 점수가 0", () => {
  const ctx = buildGNNContext(new Map());
  for (let n = 1; n <= 45; n++) {
    assertEquals(ctx.neighborScores.get(n), 0);
  }
});

Deno.test("computeNeighborScores: 자주 등장하는 번호가 높은 이웃 점수를 가진다", () => {
  const matrix = buildCoOccurrenceMatrix(SAMPLE_DRAWS);
  const ctx = buildGNNContext(matrix);

  // 1번과 2번은 거의 모든 회차에 등장 → 높은 이웃 점수
  const score1 = ctx.neighborScores.get(1) ?? 0;
  const score45 = ctx.neighborScores.get(45) ?? 0; // 45번은 등장 없음
  assertEquals(score1 > score45, true);
});

// ─────────────────────────────────────────────────
// getCompatibility 테스트
// ─────────────────────────────────────────────────

Deno.test("getCompatibility: 자주 같이 나온 쌍 → 높은 궁합 점수", () => {
  const matrix = buildCoOccurrenceMatrix(SAMPLE_DRAWS);
  const ctx = buildGNNContext(matrix);

  // 1-2 쌍 (5회 등장) vs 1-45 쌍 (0회 등장)
  const highCompat = getCompatibility(ctx, 1, 2);
  const lowCompat  = getCompatibility(ctx, 1, 45);
  assertEquals(highCompat > lowCompat, true);
});

Deno.test("getCompatibility: 같이 나온 적 없는 쌍 → 낮은 점수", () => {
  const matrix = buildCoOccurrenceMatrix(SAMPLE_DRAWS);
  const ctx = buildGNNContext(matrix);

  // 1번과 45번은 같이 나온 적 없음
  const score = getCompatibility(ctx, 1, 45);
  // neighborScore 기여분만 있을 수 있으므로 0 이상, 낮아야 함
  assertEquals(score >= 0, true);
  assertEquals(score < 0.3, true);
});

Deno.test("getCompatibility: 점수가 0~1 범위 내", () => {
  const matrix = buildCoOccurrenceMatrix(SAMPLE_DRAWS);
  const ctx = buildGNNContext(matrix);

  for (let a = 1; a <= 10; a++) {
    for (let b = a + 1; b <= 10; b++) {
      const score = getCompatibility(ctx, a, b);
      assertEquals(score >= 0 && score <= 1, true, `${a}-${b}: ${score} 범위 초과`);
    }
  }
});

Deno.test("getCompatibility: 순서에 무관하게 같은 점수", () => {
  const matrix = buildCoOccurrenceMatrix(SAMPLE_DRAWS);
  const ctx = buildGNNContext(matrix);

  assertAlmostEquals(getCompatibility(ctx, 3, 17), getCompatibility(ctx, 17, 3), 0.0001);
  assertAlmostEquals(getCompatibility(ctx, 1, 2), getCompatibility(ctx, 2, 1), 0.0001);
});

// ─────────────────────────────────────────────────
// getCombinationCompatibility 테스트
// ─────────────────────────────────────────────────

Deno.test("getCombinationCompatibility: 6개 번호 조합의 종합 궁합 산출", () => {
  const matrix = buildCoOccurrenceMatrix(SAMPLE_DRAWS);
  const ctx = buildGNNContext(matrix);

  const score = getCombinationCompatibility(ctx, [1, 2, 3, 4, 10, 11]);
  assertEquals(score >= 0 && score <= 1, true);
});

Deno.test("getCombinationCompatibility: 궁합 좋은 번호들이 더 높은 조합 점수", () => {
  const matrix = buildCoOccurrenceMatrix(SAMPLE_DRAWS);
  const ctx = buildGNNContext(matrix);

  // 1-2-3-4-10-11: 모두 자주 함께 등장한 번호들
  const goodCombo = getCombinationCompatibility(ctx, [1, 2, 3, 4, 10, 11]);
  // 40-41-42-43-44-45: 거의 등장한 적 없는 번호들
  const coldCombo = getCombinationCompatibility(ctx, [40, 41, 42, 43, 44, 45]);
  assertEquals(goodCombo >= coldCombo, true);
});

Deno.test("getCombinationCompatibility: 번호가 1개 이하면 0 반환", () => {
  const ctx = buildGNNContext(new Map());
  assertEquals(getCombinationCompatibility(ctx, []), 0);
  assertEquals(getCombinationCompatibility(ctx, [5]), 0);
});

// ─────────────────────────────────────────────────
// applyGNNCorrection 테스트
// ─────────────────────────────────────────────────

Deno.test("applyGNNCorrection: 보정 후 합이 1.0 (재정규화 확인)", () => {
  const matrix = buildCoOccurrenceMatrix(SAMPLE_DRAWS);
  const ctx = buildGNNContext(matrix);

  const probs: Record<string, number> = {};
  for (let n = 1; n <= 45; n++) probs[String(n)] = 1 / 45;

  const corrected = applyGNNCorrection(ctx, probs);
  const total = Object.values(corrected).reduce((a, b) => a + b, 0);
  assertAlmostEquals(total, 1.0, 0.001);
});

Deno.test("applyGNNCorrection: 자주 나온 번호가 보정 후 더 높은 점수", () => {
  const matrix = buildCoOccurrenceMatrix(SAMPLE_DRAWS);
  const ctx = buildGNNContext(matrix);

  // 초기값 동일
  const probs: Record<string, number> = {};
  for (let n = 1; n <= 45; n++) probs[String(n)] = 1 / 45;

  const corrected = applyGNNCorrection(ctx, probs);
  // 1번(자주 등장) vs 44번(거의 없음)
  assertEquals((corrected["1"] ?? 0) >= (corrected["44"] ?? 0), true);
});

Deno.test("applyGNNCorrection: 빈 probs → 빈 객체 반환", () => {
  const ctx = buildGNNContext(new Map());
  assertEquals(Object.keys(applyGNNCorrection(ctx, {})).length, 0);
});

// ─────────────────────────────────────────────────
// getTopCompatiblePairs 테스트
// ─────────────────────────────────────────────────

Deno.test("getTopCompatiblePairs: 지정한 N개를 내림차순으로 반환한다", () => {
  const matrix = buildCoOccurrenceMatrix(SAMPLE_DRAWS);
  const ctx = buildGNNContext(matrix);

  const top5 = getTopCompatiblePairs(ctx, 5);
  assertEquals(top5.length, 5);

  // 내림차순 정렬 검증
  for (let i = 0; i < top5.length - 1; i++) {
    assertEquals(top5[i][2] >= top5[i + 1][2], true);
  }
});
