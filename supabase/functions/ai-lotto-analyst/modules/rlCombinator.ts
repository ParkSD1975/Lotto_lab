// =====================================================
// Phase 4 — RL 조합 생성기 (메인 셰프)
// =====================================================
// Monte Carlo 시뮬레이션으로 최적 조합을 생성한다.
//
// 알고리즘:
//   1. 번호별 선택 확률 = softmax(numberScores)
//   2. 확률에 비례하여 6개 번호 비복원 샘플링
//   3. 보상 함수: R = Σ(번호점수) + α·궁합 + β·필터보너스
//      필터 미충족 → R = 0
//   4. 5,000~10,000회 시뮬레이션
//   5. 상위 보상 조합에서 다양성 보장하며 numGames개 선택
// =====================================================

import type { RLInput } from "../types.ts";
import { passesAllFilters, relaxFilters } from "./filters.ts";
import type { FilterConditions } from "./filters.ts";

// =====================================================
// 설정
// =====================================================

const DEFAULT_SIMULATIONS = 7000;
const ALPHA = 0.3;   // 궁합 점수 가중치
const BETA  = 0.2;   // 필터 보너스 가중치

// =====================================================
// 확률 기반 샘플링
// =====================================================

/**
 * 누적 확률 배열을 구성한다.
 * 번호 인덱스 → 누적 확률 (이진 탐색용)
 */
function buildCDF(probs: number[]): number[] {
  const cdf: number[] = [];
  let cum = 0;
  for (const p of probs) {
    cum += p;
    cdf.push(cum);
  }
  return cdf;
}

/**
 * CDF에서 이진 탐색으로 인덱스를 샘플링한다.
 */
function sampleFromCDF(cdf: number[], rand: number): number {
  let lo = 0, hi = cdf.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (cdf[mid] < rand) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/**
 * 번호별 점수 배열에서 6개 번호를 비복원 샘플링한다.
 * @param scores - 인덱스 0~44가 번호 1~45에 대응
 * @returns 정렬된 6개 번호 배열
 */
export function sampleCombination(scores: number[]): number[] {
  // 남은 번호 확률 재계산 (비복원)
  const remaining = [...scores];
  const selected: number[] = [];

  for (let pick = 0; pick < 6; pick++) {
    // -1(제외된 번호) 무시하고 양수만 합산
    const total = remaining.reduce((a, b) => a + Math.max(b, 0), 0);
    if (total <= 0) {
      // 확률 합이 0이면 균등 샘플링
      const available = remaining
        .map((v, i) => (v > 0 ? i : -1))
        .filter((i) => i >= 0);
      const idx = available[Math.floor(Math.random() * available.length)];
      selected.push(idx + 1);
      remaining[idx] = -1; // 제외
      continue;
    }

    const rand = Math.random() * total;
    const cdf = buildCDF(remaining.map((v) => Math.max(v, 0)));
    const idx = sampleFromCDF(cdf, rand);
    selected.push(idx + 1);
    remaining[idx] = -1; // 선택된 번호 제외
  }

  return selected.sort((a, b) => a - b);
}

// =====================================================
// 보상 함수
// =====================================================

/**
 * 조합의 보상(R)을 계산한다.
 * 필터 미충족 → 0
 */
export function calcReward(
  numbers: number[],
  numberScores: Record<number, number>,
  compatibility: (a: number, b: number) => number,
  filters: FilterConditions
): number {
  if (!passesAllFilters(numbers, filters)) return 0;

  // Σ 번호 점수
  const scoreSum = numbers.reduce((acc, n) => acc + (numberScores[n] ?? 0), 0);

  // 평균 궁합 점수 (C(6,2)=15쌍 평균)
  let compatTotal = 0;
  let compatCount = 0;
  for (let i = 0; i < numbers.length; i++) {
    for (let j = i + 1; j < numbers.length; j++) {
      compatTotal += compatibility(numbers[i], numbers[j]);
      compatCount++;
    }
  }
  const avgCompat = compatCount > 0 ? compatTotal / compatCount : 0;

  return scoreSum + ALPHA * avgCompat + BETA;
}

// =====================================================
// 다양성 보장 선택
// =====================================================

/** 두 조합의 번호 겹침 수 */
function overlapCount(a: number[], b: number[]): number {
  const setB = new Set(b);
  return a.filter((n) => setB.has(n)).length;
}

/**
 * 상위 후보에서 다양성을 보장하며 numGames개를 선택한다.
 * 이미 선택된 조합과 4개 이상 겹치면 제외.
 */
export function selectDiverse(
  candidates: { numbers: number[]; reward: number }[],
  numGames: number
): { numbers: number[]; reward: number }[] {
  const selected: { numbers: number[]; reward: number }[] = [];

  for (const candidate of candidates) {
    if (selected.length >= numGames) break;
    const tooSimilar = selected.some(
      (s) => overlapCount(s.numbers, candidate.numbers) >= 4
    );
    if (!tooSimilar) {
      selected.push(candidate);
    }
  }

  // 다양성 조건 때문에 부족하면 조건 완화하여 채움
  if (selected.length < numGames) {
    for (const candidate of candidates) {
      if (selected.length >= numGames) break;
      if (!selected.includes(candidate)) {
        selected.push(candidate);
      }
    }
  }

  return selected;
}

// =====================================================
// 메인: RL 조합 생성
// =====================================================

export interface RLResult {
  rank: number;
  numbers: number[];
  score: number;
}

/**
 * Monte Carlo 시뮬레이션으로 최적 조합을 생성한다.
 *
 * @param input - RL 입력 (numberScores, compatibility, filters, numGames)
 * @param simulations - 시뮬레이션 횟수 (기본 7,000)
 * @returns RLResult 배열 (rank 순)
 */
export function runRL(input: RLInput, simulations = DEFAULT_SIMULATIONS): RLResult[] {
  const { numberScores, compatibility, filters, numGames } = input;

  // 번호 1~45를 인덱스 0~44로 매핑한 점수 배열
  const scoreArr: number[] = Array.from({ length: 45 }, (_, i) =>
    Math.max(numberScores[i + 1] ?? 0, 0)
  );

  const candidates: { numbers: number[]; reward: number }[] = [];

  // 수렴 감지용
  let bestReward = 0;
  let noImprovementCount = 0;

  for (let sim = 0; sim < simulations; sim++) {
    const combo = sampleCombination(scoreArr);
    const reward = calcReward(combo, numberScores, compatibility, filters);

    if (reward > 0) {
      candidates.push({ numbers: combo, reward });
    }

    // 조기 종료: 최소 1000회 이후 200회 연속 개선 없으면 종료 (Task 4.5)
    if (sim >= 1000) {
      if (reward > bestReward) {
        bestReward = reward;
        noImprovementCount = 0;
      } else {
        noImprovementCount++;
        if (noImprovementCount >= 500 && candidates.length >= numGames * 3) break;
      }
    }
  }

  // 보상 내림차순 정렬
  candidates.sort((a, b) => b.reward - a.reward);

  // 다양성 보장 선택
  const diverse = selectDiverse(candidates, numGames);

  return diverse.map((c, i) => ({
    rank: i + 1,
    numbers: c.numbers,
    score: Math.round(c.reward * 100) / 100,
  }));
}

// =====================================================
// 폴백 포함 안전 실행 (최대 3단계 필터 완화)
// =====================================================

/**
 * RL을 실행하되, 필터가 너무 엄격하면 단계적으로 완화하며 재시도한다.
 * 최대 3회 재시도 후에도 부족하면 Gemini 조합을 그대로 사용 (폴백).
 */
export function runRLWithFallback(
  input: RLInput,
  simulations = DEFAULT_SIMULATIONS
): RLResult[] {
  for (let step = 0; step <= 3; step++) {
    const relaxedFilters = step === 0
      ? input.filters
      : relaxFilters(input.filters, step);

    const results = runRL({ ...input, filters: relaxedFilters }, simulations);

    if (results.length >= input.numGames) {
      return results.slice(0, input.numGames);
    }
  }

  // 완전 실패: 필터 없이 한 번 더 시도
  const fallbackResults = runRL({ ...input, filters: {} }, simulations);
  return fallbackResults.slice(0, input.numGames);
}
