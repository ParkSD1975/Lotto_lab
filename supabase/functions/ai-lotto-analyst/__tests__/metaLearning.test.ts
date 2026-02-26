// =====================================================
// Phase 2 — Meta-Learning 테스트
// =====================================================

import { assertEquals, assertAlmostEquals } from "https://deno.land/std@0.168.0/testing/asserts.ts";
import {
  calcEWMAScore,
  softmax,
  applyMinWeight,
  calcDynamicWeights,
  DEFAULT_WEIGHTS,
  DEFAULT_META_CONFIG,
} from "../modules/metaLearning.ts";
import type { ModelPerformanceSummary } from "../types.ts";
import { MODEL_NAMES } from "../types.ts";

// ─────────────────────────────────────────────────
// 헬퍼: 테스트용 ModelPerformanceSummary 생성
// ─────────────────────────────────────────────────

function makePerf(
  name: (typeof MODEL_NAMES)[number],
  hitCounts: number[]
): ModelPerformanceSummary {
  return {
    modelName: name,
    recentHitCounts: hitCounts,
    averageHitRate: hitCounts.length
      ? hitCounts.reduce((a, b) => a + b, 0) / (hitCounts.length * 6)
      : 0,
    windowSize: hitCounts.length,
  };
}

// ─────────────────────────────────────────────────
// calcEWMAScore 테스트
// ─────────────────────────────────────────────────

Deno.test("calcEWMAScore: 빈 배열 → 0", () => {
  assertEquals(calcEWMAScore([], 2.0), 0);
});

Deno.test("calcEWMAScore: 최신 회차(인덱스 0)에 가중치가 가장 크다", () => {
  // [4, 0, 0] vs [0, 0, 4]: 최신 4점이 더 높아야 함
  const recent = calcEWMAScore([4, 0, 0], 2.0);
  const old    = calcEWMAScore([0, 0, 4], 2.0);
  assertEquals(recent > old, true);
});

// ─────────────────────────────────────────────────
// softmax 테스트
// ─────────────────────────────────────────────────

Deno.test("softmax: 합이 1.0이다", () => {
  const result = softmax([1.0, 2.0, 3.0, 0.5, 0.5, 1.5]);
  const total = result.reduce((a, b) => a + b, 0);
  assertAlmostEquals(total, 1.0, 0.0001);
});

Deno.test("softmax: 모든 값이 동일하면 균등 분포", () => {
  const result = softmax([1, 1, 1, 1, 1, 1]);
  for (const v of result) {
    assertAlmostEquals(v, 1 / 6, 0.0001);
  }
});

Deno.test("softmax: 빈 배열 → 빈 배열", () => {
  assertEquals(softmax([]), []);
});

// ─────────────────────────────────────────────────
// applyMinWeight 테스트
// ─────────────────────────────────────────────────

Deno.test("applyMinWeight: 하한선 미달 값이 minWeight로 올라간다", () => {
  // [0.8, 0.1, 0.1, 0.0, 0.0, 0.0] 에서 0.05 하한선 적용
  const result = applyMinWeight([0.8, 0.1, 0.1, 0.0, 0.0, 0.0], 0.05);
  for (const w of result) {
    assertEquals(w >= 0.05 - 0.0001, true, `${w} < 0.05`);
  }
});

Deno.test("applyMinWeight: 적용 후 합이 1.0이다", () => {
  const result = applyMinWeight([0.5, 0.3, 0.1, 0.05, 0.04, 0.01], 0.05);
  const total = result.reduce((a, b) => a + b, 0);
  assertAlmostEquals(total, 1.0, 0.001);
});

Deno.test("applyMinWeight: 이미 모두 하한선 이상이면 변화 없다", () => {
  const input = [0.2, 0.2, 0.2, 0.15, 0.15, 0.1];
  const result = applyMinWeight(input, 0.05);
  for (let i = 0; i < input.length; i++) {
    assertAlmostEquals(result[i], input[i], 0.0001);
  }
});

// ─────────────────────────────────────────────────
// calcDynamicWeights 테스트
// ─────────────────────────────────────────────────

Deno.test("calcDynamicWeights: 성적 동일 → 가중치 합 = 1.0", () => {
  const perfs = MODEL_NAMES.map((name) => makePerf(name, [3, 3, 3, 3, 3]));
  const weights = calcDynamicWeights(perfs);
  const total = Object.values(weights).reduce((a, b) => a + b, 0);
  assertAlmostEquals(total, 1.0, 0.001);
});

Deno.test("calcDynamicWeights: 성적 동일 → 균등 가중치 (~16.7%)", () => {
  const perfs = MODEL_NAMES.map((name) => makePerf(name, [3, 3, 3, 3, 3]));
  const weights = calcDynamicWeights(perfs);
  for (const w of Object.values(weights)) {
    assertAlmostEquals(w, 1 / 6, 0.01);
  }
});

Deno.test("calcDynamicWeights: 한 모델만 적중 → 해당 모델 가중치 최대", () => {
  const perfs = MODEL_NAMES.map((name) =>
    makePerf(name, name === "xgboost" ? [6, 6, 6, 6, 6] : [0, 0, 0, 0, 0])
  );
  const weights = calcDynamicWeights(perfs);

  const xgboostWeight = weights["xgboost"];
  for (const [name, w] of Object.entries(weights)) {
    if (name !== "xgboost") {
      assertEquals(xgboostWeight >= w, true, `xgboost(${xgboostWeight}) should be >= ${name}(${w})`);
    }
  }
});

Deno.test("calcDynamicWeights: 가중치 합이 1.0이다", () => {
  const perfs = MODEL_NAMES.map((name, i) =>
    makePerf(name, Array(5).fill(i))
  );
  const weights = calcDynamicWeights(perfs);
  const total = Object.values(weights).reduce((a, b) => a + b, 0);
  assertAlmostEquals(total, 1.0, 0.001);
});

Deno.test("calcDynamicWeights: 모든 가중치가 minWeight(5%) 이상이다", () => {
  const perfs = MODEL_NAMES.map((name) =>
    makePerf(name, name === "lstm" ? [6, 6, 6, 6, 6] : [0, 0, 0, 0, 0])
  );
  const weights = calcDynamicWeights(perfs, DEFAULT_META_CONFIG);
  for (const [name, w] of Object.entries(weights)) {
    assertEquals(
      w >= DEFAULT_META_CONFIG.minWeight - 0.0001,
      true,
      `${name}(${w}) < minWeight(${DEFAULT_META_CONFIG.minWeight})`
    );
  }
});

Deno.test("calcDynamicWeights: 데이터 없음 → 기본 가중치 반환", () => {
  const perfs = MODEL_NAMES.map((name) => makePerf(name, []));
  const weights = calcDynamicWeights(perfs);

  for (const name of MODEL_NAMES) {
    assertAlmostEquals(weights[name], DEFAULT_WEIGHTS[name], 0.0001);
  }
});
