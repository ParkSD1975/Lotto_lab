// =====================================================
// Phase 1 — 동반출현 행렬 계산 모듈
// =====================================================
// 입력: 로또 회차 배열 (round, numbers[])
// 출력: 정규화된 동반출현 점수 Map (키: "a-b", 값: 0~1)
// =====================================================

import type { LottoDraw, CoOccurrenceMatrix, RawCoOccurrenceMatrix } from "../types.ts";

/**
 * 두 번호로 정규화된 키를 생성한다.
 * 항상 작은 번호가 앞에 오도록 정렬 (예: 17, 3 → "3-17")
 */
export function makePairKey(a: number, b: number): string {
  return a < b ? `${a}-${b}` : `${b}-${a}`;
}

/**
 * 로또 회차 배열에서 번호 쌍의 동반출현 횟수를 집계한다.
 * 각 회차의 6개 번호에서 C(6,2)=15쌍을 추출하여 카운트.
 */
export function buildRawCoOccurrence(draws: LottoDraw[]): RawCoOccurrenceMatrix {
  const raw: RawCoOccurrenceMatrix = new Map();

  for (const draw of draws) {
    const nums = draw.numbers;
    for (let i = 0; i < nums.length; i++) {
      for (let j = i + 1; j < nums.length; j++) {
        const key = makePairKey(nums[i], nums[j]);
        raw.set(key, (raw.get(key) ?? 0) + 1);
      }
    }
  }

  return raw;
}

/**
 * 원시 횟수 행렬을 최대 빈도 기준으로 0~1 정규화한다.
 * 빈 행렬이면 빈 Map을 반환한다.
 */
export function normalizeCoOccurrence(raw: RawCoOccurrenceMatrix): CoOccurrenceMatrix {
  if (raw.size === 0) return new Map();

  let maxCount = 0;
  for (const count of raw.values()) {
    if (count > maxCount) maxCount = count;
  }

  const normalized: CoOccurrenceMatrix = new Map();
  for (const [key, count] of raw.entries()) {
    normalized.set(key, count / maxCount);
  }

  return normalized;
}

/**
 * 로또 회차 배열로부터 정규화된 동반출현 행렬을 한 번에 계산한다.
 *
 * @param draws - 로또 회차 배열
 * @returns 정규화된 동반출현 점수 Map (키: "a-b", 값: 0~1)
 *
 * @example
 * const matrix = buildCoOccurrenceMatrix(draws);
 * const score = matrix.get("3-17") ?? 0; // 3번과 17번의 동반출현 점수
 */
export function buildCoOccurrenceMatrix(draws: LottoDraw[]): CoOccurrenceMatrix {
  if (draws.length === 0) return new Map();
  const raw = buildRawCoOccurrence(draws);
  return normalizeCoOccurrence(raw);
}

/**
 * 두 번호의 동반출현 점수를 조회한다.
 * 데이터 없으면 0 반환.
 */
export function getPairScore(
  matrix: CoOccurrenceMatrix,
  a: number,
  b: number
): number {
  return matrix.get(makePairKey(a, b)) ?? 0;
}

/**
 * 45×45 대칭 행렬인지 검증한다. (테스트 유틸)
 * 모든 (a,b) 쌍에 대해 matrix["a-b"] === matrix["b-a"]가 성립해야 한다.
 * Map 키가 항상 작은 번호 기준으로 정규화되어 있으므로 키 개수로 검증.
 */
export function isSymmetric(matrix: CoOccurrenceMatrix): boolean {
  for (const key of matrix.keys()) {
    const [a, b] = key.split("-").map(Number);
    if (a >= b) return false; // 키가 항상 a < b 형식이어야 함
  }
  return true;
}
