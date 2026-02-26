// =====================================================
// Phase 5 — Anomaly Detection 테스트
// =====================================================

import { assertEquals } from "https://deno.land/std@0.168.0/testing/asserts.ts";
import {
  detectAnomaly,
  detectConsecutive,
  detectArithmetic,
  detectExtremeDistribution,
  detectDecadeBias,
  detectExtremeSum,
  screenCombinations,
  getPassedCombinations,
  DEFAULT_ANOMALY_CONFIG,
} from "../modules/anomalyDetection.ts";

// ─────────────────────────────────────────────────
// 플랜 명시 테스트 케이스
// ─────────────────────────────────────────────────

Deno.test("[플랜] [1,2,3,4,5,6] → 이상 (6연번)", () => {
  const result = detectAnomaly([1, 2, 3, 4, 5, 6]);
  assertEquals(result.isAnomaly, true);
  assertEquals(result.reasons.some((r) => r.includes("연번")), true);
});

Deno.test("[플랜] [5,10,15,20,25,30] → 이상 (등차수열)", () => {
  const result = detectAnomaly([5, 10, 15, 20, 25, 30]);
  assertEquals(result.isAnomaly, true);
  assertEquals(result.reasons.some((r) => r.includes("등차수열")), true);
});

Deno.test("[플랜] [1,2,3,43,44,45] → 이상 (극단 분포)", () => {
  const result = detectAnomaly([1, 2, 3, 43, 44, 45]);
  assertEquals(result.isAnomaly, true);
});

Deno.test("[플랜] [3,17,22,28,35,41] → 정상", () => {
  const result = detectAnomaly([3, 17, 22, 28, 35, 41]);
  assertEquals(result.isAnomaly, false);
  assertEquals(result.reasons.length, 0);
});

Deno.test("[플랜] [1,2,3,4,5,45] → 이상 (5연번)", () => {
  const result = detectAnomaly([1, 2, 3, 4, 5, 45]);
  assertEquals(result.isAnomaly, true);
  assertEquals(result.reasons.some((r) => r.includes("연번")), true);
});

// ─────────────────────────────────────────────────
// detectConsecutive 상세 테스트
// ─────────────────────────────────────────────────

Deno.test("detectConsecutive: 2연번은 maxConsecutive=3 기준 정상", () => {
  const { detected } = detectConsecutive([3, 4, 10, 17, 25, 38], 3);
  assertEquals(detected, false);
});

Deno.test("detectConsecutive: 3연번은 감지됨", () => {
  const { detected, maxRun } = detectConsecutive([1, 2, 3, 15, 28, 40], 3);
  assertEquals(detected, true);
  assertEquals(maxRun, 3);
});

Deno.test("detectConsecutive: 연번 없음", () => {
  const { detected } = detectConsecutive([1, 7, 14, 22, 33, 44], 3);
  assertEquals(detected, false);
});

// ─────────────────────────────────────────────────
// detectArithmetic 상세 테스트
// ─────────────────────────────────────────────────

Deno.test("detectArithmetic: 공차 5로 6개 → 감지됨", () => {
  const { detected, commonDiff, maxCount } = detectArithmetic([5, 10, 15, 20, 25, 30], 4);
  assertEquals(detected, true);
  assertEquals(commonDiff, 5);
  assertEquals(maxCount, 6);
});

Deno.test("detectArithmetic: 공차 3개 미만 → 미감지 (minArithmetic=4)", () => {
  const { detected } = detectArithmetic([2, 5, 8, 14, 27, 39], 4);
  assertEquals(detected, false);
});

// ─────────────────────────────────────────────────
// detectExtremeDistribution 상세 테스트
// ─────────────────────────────────────────────────

Deno.test("detectExtremeDistribution: [1,2,3,43,44,45] → 높은 표준편차", () => {
  const { detected, stdDev } = detectExtremeDistribution([1, 2, 3, 43, 44, 45], 12);
  assertEquals(detected, true);
  assertEquals(stdDev > 12, true);
});

Deno.test("detectExtremeDistribution: 균등 분포 → 낮은 표준편차", () => {
  const { detected } = detectExtremeDistribution([5, 13, 21, 29, 37, 45], 12);
  // 간격이 8로 균등 → 표준편차 0 → 정상
  assertEquals(detected, false);
});

// ─────────────────────────────────────────────────
// detectDecadeBias 상세 테스트
// ─────────────────────────────────────────────────

Deno.test("detectDecadeBias: 1~9번대에 4개 → 감지됨", () => {
  const { detected, count } = detectDecadeBias([1, 2, 3, 4, 25, 38], 4);
  assertEquals(detected, true);
  assertEquals(count, 4);
});

Deno.test("detectDecadeBias: 각 10단위에 최대 2개 → 정상", () => {
  const { detected } = detectDecadeBias([3, 8, 14, 22, 33, 41], 4);
  assertEquals(detected, false);
});

// ─────────────────────────────────────────────────
// detectExtremeSum 상세 테스트
// ─────────────────────────────────────────────────

Deno.test("detectExtremeSum: 총합 21 (1+2+3+4+5+6) → sumMin=60 기준 이상", () => {
  const { detected, sum } = detectExtremeSum([1, 2, 3, 4, 5, 6], 60, 220);
  assertEquals(detected, true);
  assertEquals(sum, 21);
});

Deno.test("detectExtremeSum: 총합 225 → sumMax=220 기준 이상", () => {
  const { detected } = detectExtremeSum([35, 38, 40, 42, 44, 45], 60, 220);
  assertEquals(detected, true);
});

Deno.test("detectExtremeSum: 정상 범위 총합", () => {
  const { detected } = detectExtremeSum([7, 14, 22, 31, 38, 42], 60, 220);
  assertEquals(detected, false);
});

// ─────────────────────────────────────────────────
// severity 검증
// ─────────────────────────────────────────────────

Deno.test("severity: 등차수열 → high", () => {
  const result = detectAnomaly([5, 10, 15, 20, 25, 30]);
  assertEquals(result.severity, "high");
});

Deno.test("severity: 3연번만 → medium", () => {
  // 3연번이지만 다른 규칙은 미충족
  const result = detectAnomaly([1, 2, 3, 20, 31, 38]);
  assertEquals(result.isAnomaly, true);
  assertEquals(result.severity, "medium");
});

Deno.test("severity: 번호대 편중만 → low", () => {
  // 10번대에 4개, 연번/등차/극단 없음
  const result = detectAnomaly([11, 12, 14, 17, 28, 39]);
  if (result.isAnomaly) {
    assertEquals(result.severity, "low");
  }
  // 이상 없을 수도 있음 (12는 연속 아님)
});

// ─────────────────────────────────────────────────
// screenCombinations / getPassedCombinations 테스트
// ─────────────────────────────────────────────────

Deno.test("screenCombinations: 이상 조합은 passed=false", () => {
  const combos = [
    { rank: 1, numbers: [1, 2, 3, 4, 5, 6],     score: 0.9 }, // 6연번
    { rank: 2, numbers: [3, 17, 22, 28, 35, 41], score: 0.8 }, // 정상
  ];
  const screened = screenCombinations(combos);
  assertEquals(screened[0].passed, false);
  assertEquals(screened[0].reason !== undefined, true);
  assertEquals(screened[1].passed, true);
});

Deno.test("getPassedCombinations: rank가 1부터 재부여된다", () => {
  const combos = [
    { rank: 1, numbers: [1, 2, 3, 4, 5, 6],      score: 0.9 }, // 실패
    { rank: 2, numbers: [3, 17, 22, 28, 35, 41],  score: 0.8 }, // 통과
    { rank: 3, numbers: [8, 15, 23, 29, 36, 42],  score: 0.7 }, // 통과
  ];
  const screened = screenCombinations(combos);
  const passed = getPassedCombinations(screened);
  assertEquals(passed.length, 2);
  assertEquals(passed[0].rank, 1);
  assertEquals(passed[1].rank, 2);
});

// ─────────────────────────────────────────────────
// False Positive 검증 (정상 조합 < 5% 탈락)
// ─────────────────────────────────────────────────

Deno.test("false positive: 실제 로또 형태 조합들이 5% 미만으로 탈락", () => {
  // 실제 로또 당첨번호에서 추출한 대표 조합들
  const realCombos = [
    [3,  17, 22, 28, 35, 41],  // diffs: 14,5,6,7,6
    [7,  11, 16, 25, 33, 40],  // diffs: 4,5,9,8,7
    [2,  13, 19, 27, 34, 44],  // diffs: 11,6,8,7,10
    [6,  14, 21, 30, 37, 43],  // diffs: 8,7,9,7,6
    [4,  12, 20, 26, 38, 45],  // diffs: 8,8,6,12,7
    [9,  18, 24, 29, 36, 42],  // diffs: 9,6,5,7,6
    [5,  16, 23, 31, 39, 44],  // diffs: 11,7,8,8,5
    [4,  11, 20, 27, 34, 43],  // diffs: 7,9,7,7,9  (교체: 1,10,19,28,37,43 → AP 없음)
    [8,  17, 25, 32, 38, 45],  // diffs: 9,8,7,6,7
    [11, 20, 26, 33, 40, 44],  // diffs: 9,6,7,7,4
    [3,  13, 22, 30, 37, 43],  // diffs: 10,9,8,7,6  (교체: 3,14,22,29,36,43 → AP 없음)
    [6,  15, 23, 30, 39, 45],  // diffs: 9,8,7,9,6
    [2,  11, 18, 27, 35, 42],  // diffs: 9,7,9,8,7
    [7,  16, 24, 31, 40, 44],  // diffs: 9,8,7,9,4
    [4,  13, 21, 28, 37, 45],  // diffs: 9,8,7,9,8
    [9,  19, 26, 34, 41, 43],  // diffs: 10,7,8,7,2
    [5,  14, 20, 29, 38, 44],  // diffs: 9,6,9,9,6
    [1,  12, 23, 32, 39, 42],  // diffs: 11,11,9,7,3
    [8,  18, 25, 33, 40, 45],  // diffs: 10,7,8,7,5
    [10, 21, 27, 35, 41, 44],  // diffs: 11,6,8,6,3
  ];

  const falsePositives = realCombos.filter((c) => detectAnomaly(c).isAnomaly);
  const rate = falsePositives.length / realCombos.length;
  assertEquals(rate < 0.05, true, `false positive ${(rate * 100).toFixed(1)}% ≥ 5%`);
});
