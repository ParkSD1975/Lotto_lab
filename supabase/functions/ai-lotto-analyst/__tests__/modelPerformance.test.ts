// =====================================================
// Phase 1 — 모델 성적 추적 테스트 (순수 로직만)
// DB 연결 없이 순수 함수만 테스트
// =====================================================

import { assertEquals, assertAlmostEquals } from "https://deno.land/std@0.168.0/testing/asserts.ts";
import {
  calcHitCount,
  calcAverageHitRate,
  applyWindow,
} from "../modules/modelPerformance.ts";

// ─────────────────────────────────────────────────
// calcHitCount 테스트
// ─────────────────────────────────────────────────

Deno.test("calcHitCount: 예측 vs 실제 비교 → 정확한 적중 수", () => {
  const predicted = [3, 11, 17, 22, 35, 41, 5, 8, 19, 30];
  const actual    = [3, 11, 17, 22, 35, 41]; // 6개 모두 맞음

  assertEquals(calcHitCount(predicted, actual), 6);
});

Deno.test("calcHitCount: 부분 적중", () => {
  const predicted = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
  const actual    = [3, 7, 20, 25, 33, 40];

  assertEquals(calcHitCount(predicted, actual), 2); // 3, 7만 맞음
});

Deno.test("calcHitCount: 전혀 맞지 않음 → 0", () => {
  const predicted = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
  const actual    = [11, 22, 33, 34, 35, 45];

  assertEquals(calcHitCount(predicted, actual), 0);
});

Deno.test("calcHitCount: 빈 배열 → 0", () => {
  assertEquals(calcHitCount([], [1, 2, 3, 4, 5, 6]), 0);
  assertEquals(calcHitCount([1, 2, 3], []), 0);
});

// ─────────────────────────────────────────────────
// calcAverageHitRate 테스트
// ─────────────────────────────────────────────────

Deno.test("calcAverageHitRate: 빈 배열 → 0", () => {
  assertEquals(calcAverageHitRate([]), 0);
});

Deno.test("calcAverageHitRate: 모두 6 적중 → 1.0", () => {
  assertAlmostEquals(calcAverageHitRate([6, 6, 6, 6, 6]), 1.0, 0.0001);
});

Deno.test("calcAverageHitRate: 모두 0 적중 → 0.0", () => {
  assertAlmostEquals(calcAverageHitRate([0, 0, 0, 0, 0]), 0.0, 0.0001);
});

Deno.test("calcAverageHitRate: 평균 3 적중 → 0.5", () => {
  // 4회차: [3, 3, 3, 3] → 합 12, 평균 3, /6 = 0.5
  assertAlmostEquals(calcAverageHitRate([3, 3, 3, 3]), 0.5, 0.0001);
});

Deno.test("calcAverageHitRate: 혼합 값", () => {
  // [6, 0, 3] → 합 9, /3 회차 /6 번호 = 9/18 = 0.5
  assertAlmostEquals(calcAverageHitRate([6, 0, 3]), 0.5, 0.0001);
});

// ─────────────────────────────────────────────────
// applyWindow 테스트
// ─────────────────────────────────────────────────

Deno.test("applyWindow: 최근 N개만 반환한다 (최신순 배열 기준)", () => {
  const hitCounts = [4, 3, 2, 5, 1, 0, 3, 2, 4, 6, 1, 2]; // 12회차

  const window10 = applyWindow(hitCounts, 10);
  assertEquals(window10.length, 10);
  assertEquals(window10[0], 4); // 가장 최신

  const window3 = applyWindow(hitCounts, 3);
  assertEquals(window3, [4, 3, 2]);
});

Deno.test("applyWindow: 배열보다 큰 windowSize → 전체 반환", () => {
  const arr = [1, 2, 3];
  assertEquals(applyWindow(arr, 10), [1, 2, 3]);
});

Deno.test("applyWindow: 빈 배열 → 빈 배열", () => {
  assertEquals(applyWindow([], 5), []);
});
