// =====================================================
// Phase 4 — 필터 엔진
// =====================================================
// RL 조합 생성 시 조합이 조건을 충족하는지 검사한다.
// 기존 프론트의 _computeFilterStats() 필터 조건과 동일한 기준.
// =====================================================

export interface FilterConditions {
  sumRange?: [number, number];       // 총합 범위 [min, max]
  oddEvenRatio?: string;             // "3:3", "4:2", "2:4" 등 (쉼표로 복수 허용)
  acRange?: [number, number];        // AC값 범위 [min, max]
  consecutiveMax?: number;           // 연속번호 최대 허용 쌍 수
  lowHighRatio?: string;             // 저번호(1-22):고번호(23-45) 비율
  tailSumRange?: [number, number];   // 끝수합 범위 [min, max]
}

// =====================================================
// 개별 통계 계산
// =====================================================

/** 6개 번호 총합 */
export function calcSum(numbers: number[]): number {
  return numbers.reduce((a, b) => a + b, 0);
}

/** 홀수 개수 */
export function calcOddCount(numbers: number[]): number {
  return numbers.filter((n) => n % 2 !== 0).length;
}

/** AC값 (Arithmetic Complexity) */
export function calcACValue(numbers: number[]): number {
  const sorted = [...numbers].sort((a, b) => a - b);
  const diffs = new Set<number>();
  for (let i = 0; i < sorted.length; i++) {
    for (let j = i + 1; j < sorted.length; j++) {
      diffs.add(sorted[j] - sorted[i]);
    }
  }
  return diffs.size - (sorted.length - 1);
}

/** 연속번호 쌍 수 (예: [1,2,3] → 2쌍) */
export function calcConsecutivePairs(numbers: number[]): number {
  const sorted = [...numbers].sort((a, b) => a - b);
  let pairs = 0;
  for (let i = 0; i < sorted.length - 1; i++) {
    if (sorted[i + 1] - sorted[i] === 1) pairs++;
  }
  return pairs;
}

/** 저번호(1~22) 개수 */
export function calcLowCount(numbers: number[]): number {
  return numbers.filter((n) => n <= 22).length;
}

/** 끝수(1의 자리) 합 */
export function calcTailSum(numbers: number[]): number {
  return numbers.reduce((a, b) => a + (b % 10), 0);
}

// =====================================================
// 개별 필터 검사
// =====================================================

/** 총합 필터 */
export function checkSumRange(numbers: number[], range: [number, number]): boolean {
  const s = calcSum(numbers);
  return s >= range[0] && s <= range[1];
}

/**
 * 홀짝 비율 필터
 * oddEvenRatio: "3:3" 또는 "3:3,4:2" (복수 허용)
 */
export function checkOddEvenRatio(numbers: number[], ratio: string): boolean {
  const odd = calcOddCount(numbers);
  const even = numbers.length - odd;
  return ratio.split(",").some((r) => {
    const [o, e] = r.trim().split(":").map(Number);
    return odd === o && even === e;
  });
}

/** AC값 필터 */
export function checkACRange(numbers: number[], range: [number, number]): boolean {
  const ac = calcACValue(numbers);
  return ac >= range[0] && ac <= range[1];
}

/** 연속번호 최대 쌍 수 필터 */
export function checkConsecutiveMax(numbers: number[], max: number): boolean {
  return calcConsecutivePairs(numbers) <= max;
}

/** 저고 비율 필터 */
export function checkLowHighRatio(numbers: number[], ratio: string): boolean {
  const low = calcLowCount(numbers);
  const high = numbers.length - low;
  return ratio.split(",").some((r) => {
    const [l, h] = r.trim().split(":").map(Number);
    return low === l && high === h;
  });
}

/** 끝수합 범위 필터 */
export function checkTailSumRange(numbers: number[], range: [number, number]): boolean {
  const ts = calcTailSum(numbers);
  return ts >= range[0] && ts <= range[1];
}

// =====================================================
// 통합 필터 검사
// =====================================================

/**
 * 조합이 모든 필터 조건을 충족하는지 검사한다.
 * 하나라도 실패하면 false.
 */
export function passesAllFilters(
  numbers: number[],
  conditions: FilterConditions
): boolean {
  if (conditions.sumRange && !checkSumRange(numbers, conditions.sumRange)) return false;
  if (conditions.oddEvenRatio && !checkOddEvenRatio(numbers, conditions.oddEvenRatio)) return false;
  if (conditions.acRange && !checkACRange(numbers, conditions.acRange)) return false;
  if (conditions.consecutiveMax !== undefined && !checkConsecutiveMax(numbers, conditions.consecutiveMax)) return false;
  if (conditions.lowHighRatio && !checkLowHighRatio(numbers, conditions.lowHighRatio)) return false;
  if (conditions.tailSumRange && !checkTailSumRange(numbers, conditions.tailSumRange)) return false;
  return true;
}

// =====================================================
// 필터 완화 (재시도 시 단계적으로 완화)
// =====================================================

/**
 * 필터 조건을 한 단계 완화한다.
 * 순서: sumRange 확장 → oddEvenRatio 제거 → acRange 확장 → 나머지 제거
 */
export function relaxFilters(conditions: FilterConditions, step: number): FilterConditions {
  const relaxed = { ...conditions };
  if (step === 1 && relaxed.sumRange) {
    // 총합 범위 ±20 확장
    relaxed.sumRange = [
      Math.max(21,   relaxed.sumRange[0] - 20),
      Math.min(255, relaxed.sumRange[1] + 20),
    ];
  } else if (step === 2) {
    delete relaxed.oddEvenRatio;
    delete relaxed.lowHighRatio;
  } else if (step >= 3) {
    // 총합만 유지, 나머지 전부 제거
    const sumRange = relaxed.sumRange;
    return sumRange ? { sumRange } : {};
  }
  return relaxed;
}
