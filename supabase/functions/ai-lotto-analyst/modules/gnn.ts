// =====================================================
// Phase 3 — GNN 궁합 분석 엔진 (관계 코치)
// =====================================================
// Phase 1의 동반출현 행렬을 인접 행렬로 활용하여
// 번호 간 궁합 점수를 계산하는 경량 GNN 구현.
//
// 알고리즘:
//   1. Phase 1 동반출현 행렬 → 인접 행렬 (edge weight)
//   2. 1회 메시지 패싱: 각 번호의 "이웃 평균 점수" 계산
//   3. 번호 쌍 궁합:
//      compatibility(a, b) = cooccurrence[a][b] + neighborScore[a] * neighborScore[b]
//   4. 조합 전체 궁합: C(6,2)=15쌍의 평균 궁합
// =====================================================

import type { CoOccurrenceMatrix } from "../types.ts";
import { getPairScore } from "./cooccurrence.ts";

// 로또 번호 범위
const MIN_NUM = 1;
const MAX_NUM = 45;

// =====================================================
// 메시지 패싱 — 이웃 평균 점수 계산
// =====================================================

/**
 * 동반출현 행렬로부터 각 번호의 "이웃 평균 점수"를 계산한다.
 * (1회 메시지 패싱)
 *
 * neighborScore[n] = 다른 모든 번호와의 동반출현 점수 평균
 * 즉, 번호 n이 전체적으로 얼마나 "어울리는" 번호인지.
 */
export function computeNeighborScores(matrix: CoOccurrenceMatrix): Map<number, number> {
  const neighborScores = new Map<number, number>();

  for (let n = MIN_NUM; n <= MAX_NUM; n++) {
    let total = 0;
    let count = 0;
    for (let m = MIN_NUM; m <= MAX_NUM; m++) {
      if (m === n) continue;
      const score = getPairScore(matrix, n, m);
      if (score > 0) {
        total += score;
        count++;
      }
    }
    neighborScores.set(n, count > 0 ? total / count : 0);
  }

  return neighborScores;
}

// =====================================================
// GNN 컨텍스트 — 행렬 + 이웃 점수를 묶어 재사용
// =====================================================

export interface GNNContext {
  matrix: CoOccurrenceMatrix;
  neighborScores: Map<number, number>;
}

/**
 * 동반출현 행렬로부터 GNN 컨텍스트를 생성한다.
 * 동일 회차에서 반복 호출 시 캐싱하여 재계산을 방지.
 * (Task 3.4: 행렬 캐싱)
 */
export function buildGNNContext(matrix: CoOccurrenceMatrix): GNNContext {
  return {
    matrix,
    neighborScores: computeNeighborScores(matrix),
  };
}

// =====================================================
// 번호 쌍 궁합 점수
// =====================================================

/**
 * 두 번호의 궁합 점수를 반환한다. (0~1)
 *
 * compatibility(a, b) = cooccurrence[a][b] + neighborScore[a] * neighborScore[b]
 * → 동반출현 점수 + 양쪽 모두 "어울리는" 번호일수록 보너스
 * → 최대값으로 클램핑하여 0~1 유지
 */
export function getCompatibility(ctx: GNNContext, a: number, b: number): number {
  const coScore = getPairScore(ctx.matrix, a, b);
  const nA = ctx.neighborScores.get(a) ?? 0;
  const nB = ctx.neighborScores.get(b) ?? 0;
  const raw = coScore + nA * nB;
  // 이론적 최대: 1.0 (coScore) + 1.0*1.0 (neighbor) = 2.0 → 0.5로 나눠 0~1 정규화
  return Math.min(raw / 2.0, 1.0);
}

// =====================================================
// 조합 전체 궁합 점수
// =====================================================

/**
 * 6개 번호 조합의 전체 궁합 점수를 반환한다. (0~1)
 *
 * C(6,2)=15쌍의 궁합 점수 평균
 *
 * @param ctx - GNN 컨텍스트
 * @param numbers - 번호 배열 (6개)
 * @returns 평균 궁합 점수 (0~1), 번호가 2개 미만이면 0
 */
export function getCombinationCompatibility(ctx: GNNContext, numbers: number[]): number {
  if (numbers.length < 2) return 0;

  let total = 0;
  let count = 0;

  for (let i = 0; i < numbers.length; i++) {
    for (let j = i + 1; j < numbers.length; j++) {
      total += getCompatibility(ctx, numbers[i], numbers[j]);
      count++;
    }
  }

  return count > 0 ? total / count : 0;
}

// =====================================================
// 번호별 평균 궁합 (상위 번호 필터링용)
// =====================================================

/**
 * 특정 번호가 후보 번호들과 갖는 평균 궁합 점수를 반환한다.
 * RL 조합 생성 시 번호 점수 보정에 활용.
 *
 * @param ctx - GNN 컨텍스트
 * @param num - 대상 번호
 * @param candidates - 비교 대상 번호 배열 (생략 시 1~45 전체)
 */
export function getAverageCompatibility(
  ctx: GNNContext,
  num: number,
  candidates?: number[]
): number {
  const targets = candidates ?? Array.from({ length: MAX_NUM }, (_, i) => i + 1);
  let total = 0;
  let count = 0;

  for (const other of targets) {
    if (other === num) continue;
    total += getCompatibility(ctx, num, other);
    count++;
  }

  return count > 0 ? total / count : 0;
}

// =====================================================
// GNN 보정: number_probabilities에 궁합 점수 반영
// =====================================================

/**
 * Gemini의 number_probabilities에 GNN 궁합 보정을 적용한다.
 *
 * finalScore[n] = geminiScore[n] * (1 + avgCompatibility[n] * GNN_WEIGHT)
 *
 * @param ctx - GNN 컨텍스트
 * @param numberProbs - Gemini 반환 번호별 확률 { "1": 0.022, ... }
 * @param gnnWeight - GNN 보정 강도 (기본 0.2, 플랜 명세)
 * @returns 보정된 번호별 점수 (합이 1이 되도록 재정규화)
 */
export function applyGNNCorrection(
  ctx: GNNContext,
  numberProbs: Record<string, number>,
  gnnWeight = 0.2
): Record<string, number> {
  const entries = Object.entries(numberProbs);
  if (entries.length === 0) return numberProbs;

  const corrected: Record<string, number> = {};
  const allNums = entries.map(([k]) => parseInt(k));

  for (const [key, geminiScore] of entries) {
    const num = parseInt(key);
    const avgCompat = getAverageCompatibility(ctx, num, allNums);
    corrected[key] = geminiScore * (1 + avgCompat * gnnWeight);
  }

  // 합이 1.0이 되도록 재정규화
  const total = Object.values(corrected).reduce((a, b) => a + b, 0);
  if (total > 0) {
    for (const key of Object.keys(corrected)) {
      corrected[key] /= total;
    }
  }

  return corrected;
}

// =====================================================
// 상위 궁합 쌍 추출 (pipeline.topCompatiblePairs용)
// =====================================================

/**
 * 전체 번호 중 궁합 점수가 높은 상위 N쌍을 반환한다.
 * Phase 6 pipeline.topCompatiblePairs 필드에 사용.
 *
 * @returns [numA, numB, score][] 형태의 배열 (score 내림차순)
 */
export function getTopCompatiblePairs(
  ctx: GNNContext,
  topN = 10
): [number, number, number][] {
  const pairs: [number, number, number][] = [];

  for (let a = MIN_NUM; a <= MAX_NUM; a++) {
    for (let b = a + 1; b <= MAX_NUM; b++) {
      const score = getCompatibility(ctx, a, b);
      if (score > 0) {
        pairs.push([a, b, score]);
      }
    }
  }

  pairs.sort((x, y) => y[2] - x[2]);
  return pairs.slice(0, topN);
}
