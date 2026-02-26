// =====================================================
// Phase 5 — Anomaly Detection 엔진 (위생 검열관)
// =====================================================
// RL이 생성한 조합 중 통계적으로 비현실적인 조합을 탐지·차단.
//
// 탐지 규칙:
//   1. 연번 탐지:   3개 이상 연속번호        → severity: medium
//   2. 등차수열:    동일 공차 4개 이상        → severity: high
//   3. 극단 분포:   번호 간격 편차 극단        → severity: medium
//   4. 번호대 편중: 특정 10단위에 4개 이상    → severity: low
//   5. 총합 극단:   총합 < 60 또는 > 220     → severity: high
// =====================================================

import type { AnomalyResult } from "../types.ts";

// =====================================================
// 설정 (Task 5.4: 외부화된 임계값)
// =====================================================

export interface AnomalyConfig {
  /** 연속번호 최대 허용 개수 (이 값 이상이면 이상) */
  maxConsecutive: number;
  /** 등차수열 최소 개수 (이 값 이상이면 이상) */
  minArithmetic: number;
  /** 간격 표준편차 이상 임계값 (이 값 초과이면 이상) */
  maxGapStdDev: number;
  /** 특정 10단위 편중 임계값 */
  maxDecadeCount: number;
  /** 총합 하한 */
  sumMin: number;
  /** 총합 상한 */
  sumMax: number;
}

export const DEFAULT_ANOMALY_CONFIG: AnomalyConfig = {
  maxConsecutive:  3,   // 3개 이상 연속번호 → 이상
  minArithmetic:   4,   // 공차 동일 4개+ → 이상
  maxGapStdDev:   12,  // 간격 표준편차 12 초과 → 이상
  maxDecadeCount:  4,   // 특정 10단위에 4개+ → 이상
  sumMin:         60,
  sumMax:        220,
};

// =====================================================
// 개별 탐지 규칙
// =====================================================

/**
 * 규칙 1: 연번 탐지
 * 정렬된 번호에서 N개 이상 연속이면 이상.
 * ex) [1,2,3,4,5,6] → 6연번
 */
export function detectConsecutive(
  sorted: number[],
  maxConsecutive: number
): { detected: boolean; maxRun: number } {
  let maxRun = 1;
  let run = 1;
  for (let i = 1; i < sorted.length; i++) {
    if (sorted[i] - sorted[i - 1] === 1) {
      run++;
      if (run > maxRun) maxRun = run;
    } else {
      run = 1;
    }
  }
  return { detected: maxRun >= maxConsecutive, maxRun };
}

/**
 * 규칙 2: 등차수열 탐지
 * 동일한 공차를 가진 번호가 minArithmetic개 이상이면 이상.
 * ex) [5,10,15,20,25,30] → 공차 5, 6개
 */
export function detectArithmetic(
  sorted: number[],
  minArithmetic: number
): { detected: boolean; maxCount: number; commonDiff?: number } {
  const diffs = sorted.slice(1).map((n, i) => n - sorted[i]);

  // 각 공차별 최장 연속 구간 탐색
  const diffSet = new Set(diffs);
  let maxCount = 0;
  let commonDiff: number | undefined;

  for (const d of diffSet) {
    let count = 1;
    for (const diff of diffs) {
      if (diff === d) count++;
      else count = 1;
      if (count > maxCount) {
        maxCount = count;
        commonDiff = d;
      }
    }
  }

  return { detected: maxCount >= minArithmetic, maxCount, commonDiff };
}

/**
 * 규칙 3: 극단 분포 탐지
 * 번호 간격(diff)의 표준편차가 임계값 초과이면 이상.
 * ex) [1,2,3,43,44,45] → 간격이 1,1,40,1,1 로 극단적
 */
export function detectExtremeDistribution(
  sorted: number[],
  maxGapStdDev: number
): { detected: boolean; stdDev: number } {
  const gaps = sorted.slice(1).map((n, i) => n - sorted[i]);
  const mean = gaps.reduce((a, b) => a + b, 0) / gaps.length;
  const variance = gaps.reduce((a, b) => a + Math.pow(b - mean, 2), 0) / gaps.length;
  const stdDev = Math.sqrt(variance);
  return { detected: stdDev > maxGapStdDev, stdDev };
}

/**
 * 규칙 4: 번호대 편중 탐지
 * 10단위 구간(1-9, 10-19, 20-29, 30-39, 40-45)에
 * maxDecadeCount개 이상 몰려있으면 이상.
 */
export function detectDecadeBias(
  numbers: number[],
  maxDecadeCount: number
): { detected: boolean; decade?: number; count?: number } {
  const buckets: Record<number, number> = {};
  for (const n of numbers) {
    const decade = Math.floor((n - 1) / 10);
    buckets[decade] = (buckets[decade] ?? 0) + 1;
  }
  for (const [decade, count] of Object.entries(buckets)) {
    if (count >= maxDecadeCount) {
      return { detected: true, decade: parseInt(decade) * 10 + 1, count };
    }
  }
  return { detected: false };
}

/**
 * 규칙 5: 총합 극단 탐지
 */
export function detectExtremeSum(
  numbers: number[],
  sumMin: number,
  sumMax: number
): { detected: boolean; sum: number } {
  const sum = numbers.reduce((a, b) => a + b, 0);
  return { detected: sum < sumMin || sum > sumMax, sum };
}

// =====================================================
// 통합 탐지
// =====================================================

/**
 * 조합의 이상 여부를 종합 판정한다.
 *
 * @param numbers - 검사할 번호 배열 (정렬 여부 무관)
 * @param config  - 탐지 임계값 설정
 * @returns AnomalyResult
 */
export function detectAnomaly(
  numbers: number[],
  config: AnomalyConfig = DEFAULT_ANOMALY_CONFIG
): AnomalyResult {
  const sorted = [...numbers].sort((a, b) => a - b);
  const reasons: string[] = [];
  let highestSeverity: "low" | "medium" | "high" = "low";

  // 규칙 5: 총합 극단 (high)
  const sumCheck = detectExtremeSum(sorted, config.sumMin, config.sumMax);
  if (sumCheck.detected) {
    reasons.push(`총합 극단: ${sumCheck.sum} (정상 범위 ${config.sumMin}~${config.sumMax})`);
    highestSeverity = "high";
  }

  // 규칙 2: 등차수열 (high)
  const arithCheck = detectArithmetic(sorted, config.minArithmetic);
  if (arithCheck.detected) {
    reasons.push(`등차수열: 공차 ${arithCheck.commonDiff}로 ${arithCheck.maxCount}개 연속`);
    highestSeverity = "high";
  }

  // 규칙 1: 연번 (medium)
  const consCheck = detectConsecutive(sorted, config.maxConsecutive);
  if (consCheck.detected) {
    reasons.push(`${consCheck.maxRun}연번 감지`);
    if (highestSeverity === "low") highestSeverity = "medium";
  }

  // 규칙 3: 극단 분포 (medium)
  const distCheck = detectExtremeDistribution(sorted, config.maxGapStdDev);
  if (distCheck.detected) {
    reasons.push(`극단 분포: 간격 표준편차 ${distCheck.stdDev.toFixed(1)}`);
    if (highestSeverity === "low") highestSeverity = "medium";
  }

  // 규칙 4: 번호대 편중 (low)
  const decadeCheck = detectDecadeBias(sorted, config.maxDecadeCount);
  if (decadeCheck.detected) {
    reasons.push(`번호대 편중: ${decadeCheck.decade}번대에 ${decadeCheck.count}개`);
    // severity는 low 유지
  }

  return {
    isAnomaly: reasons.length > 0,
    reasons,
    severity: reasons.length > 0 ? highestSeverity : "low",
  };
}

// =====================================================
// RL 파이프라인 게이트 (Task 5.3)
// =====================================================

export interface ScreenedResult {
  numbers: number[];
  rank: number;
  score: number;
  passed: boolean;
  reason?: string;
}

/**
 * RL 결과 목록에 이상 탐지 게이트를 적용한다.
 *
 * - 통과한 조합: passed=true
 * - 실패한 조합: passed=false + reason
 * - 부족분은 호출자가 RL 재실행으로 채워야 함 (최대 3회 재시도)
 */
export function screenCombinations(
  combos: { rank: number; numbers: number[]; score: number }[],
  config: AnomalyConfig = DEFAULT_ANOMALY_CONFIG
): ScreenedResult[] {
  return combos.map((c) => {
    const result = detectAnomaly(c.numbers, config);
    return {
      ...c,
      passed: !result.isAnomaly,
      reason: result.isAnomaly ? result.reasons.join(" / ") : undefined,
    };
  });
}

/**
 * 통과한 조합만 추출하여 rank를 재부여한다.
 */
export function getPassedCombinations(
  screened: ScreenedResult[]
): { rank: number; numbers: number[]; score: number }[] {
  return screened
    .filter((s) => s.passed)
    .map((s, i) => ({ rank: i + 1, numbers: s.numbers, score: s.score }));
}
