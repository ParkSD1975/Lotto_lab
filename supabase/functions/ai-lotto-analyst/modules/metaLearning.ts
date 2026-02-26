// =====================================================
// Phase 2 — Meta-Learning 엔진 (팀 매니저)
// =====================================================
// 기존 고정 가중치 { lstm: 0.2, xgboost: 0.2, ... }를
// 최근 모델 성적 기반 동적 가중치로 교체한다.
//
// 알고리즘:
//   1. model_predictions 테이블에서 최근 WINDOW_SIZE 회차 성적 조회
//   2. 지수 가중 이동평균 (최근 회차에 DECAY_FACTOR 배 가중)
//   3. Softmax 정규화 → 합계 = 1.0
//   4. 최소 가중치 하한선 MIN_WEIGHT 적용
// =====================================================

import type { ModelName, ModelWeights, ModelPerformanceSummary } from "../types.ts";
import { MODEL_NAMES } from "../types.ts";
import { getAllModelPerformances, calcAverageHitRate, applyWindow } from "./modelPerformance.ts";

// =====================================================
// 설정 (Task 2.4: 외부화된 파라미터)
// =====================================================

export interface MetaLearningConfig {
  /** 성적 참고 회차 수 (기본 10) */
  windowSize: number;
  /** 최소 가중치 하한선 — 모든 모델이 최소 이 비율은 유지 (기본 0.05) */
  minWeight: number;
  /** 지수 감쇠율 — 최근 회차에 부여하는 추가 가중치 배율 (기본 2.0) */
  decayFactor: number;
}

export const DEFAULT_META_CONFIG: MetaLearningConfig = {
  windowSize: 10,
  minWeight: 0.05,
  decayFactor: 2.0,
};

/** 기본 균등 가중치 (데이터 없을 때 폴백) */
export const DEFAULT_WEIGHTS: ModelWeights = {
  lstm:         0.2,
  xgboost:      0.2,
  cnn:          0.2,
  transformer:  0.2,
  markov:       0.1,
  autoencoder:  0.1,
};

// =====================================================
// 순수 계산 함수 (테스트 가능)
// =====================================================

/**
 * 지수 가중 이동평균(EWMA)으로 hit_count 배열을 점수화한다.
 * 배열의 앞쪽이 최신 회차이며, 인덱스가 클수록 오래된 데이터.
 *
 * score = Σ hitCounts[i] * (decayFactor ^ -i)
 * 단, 정규화는 softmax에서 처리하므로 여기서는 원시 합산만.
 */
export function calcEWMAScore(hitCounts: number[], decayFactor: number): number {
  if (hitCounts.length === 0) return 0;
  let score = 0;
  for (let i = 0; i < hitCounts.length; i++) {
    score += hitCounts[i] * Math.pow(decayFactor, -i);
  }
  return score;
}

/**
 * 점수 배열에 Softmax를 적용하여 합이 1.0인 확률 분포로 변환한다.
 * 수치 안정성을 위해 최댓값을 빼는 표준 구현 사용.
 */
export function softmax(scores: number[]): number[] {
  if (scores.length === 0) return [];
  const max = Math.max(...scores);
  const exps = scores.map((s) => Math.exp(s - max));
  const sum = exps.reduce((a, b) => a + b, 0);
  return exps.map((e) => e / sum);
}

/**
 * 최소 가중치 하한선을 적용한다.
 * minWeight 미만인 모델의 가중치를 minWeight로 올리고,
 * 초과분은 나머지 모델에서 비례 차감하여 합이 1.0이 되게 한다.
 *
 * 반복 최대 10회 (극단적 케이스 방지)
 */
export function applyMinWeight(weights: number[], minWeight: number): number[] {
  const n = weights.length;
  let result = [...weights];

  for (let iter = 0; iter < 10; iter++) {
    const below = result.map((w) => w < minWeight);
    const anyBelow = below.some(Boolean);
    if (!anyBelow) break;

    // 하한선 미달 모델에 minWeight 할당
    const fixedTotal = below.filter(Boolean).length * minWeight;
    const freeTotal = 1.0 - fixedTotal;
    const freeSum = result
      .filter((_, i) => !below[i])
      .reduce((a, b) => a + b, 0);

    result = result.map((w, i) => {
      if (below[i]) return minWeight;
      if (freeSum === 0) return freeTotal / result.filter((_, j) => !below[j]).length;
      return (w / freeSum) * freeTotal;
    });
  }

  return result;
}

/**
 * ModelPerformanceSummary 배열로부터 동적 가중치를 계산한다.
 * (DB 없이 순수 로직 테스트 가능)
 *
 * @param performances - 모델별 성적 요약 (MODEL_NAMES 순서와 일치해야 함)
 * @param config - MetaLearning 설정
 * @returns ModelWeights (합 = 1.0, 각 값 >= minWeight)
 */
export function calcDynamicWeights(
  performances: ModelPerformanceSummary[],
  config: MetaLearningConfig = DEFAULT_META_CONFIG
): ModelWeights {
  // 데이터가 전혀 없으면 기본 가중치 반환
  const hasData = performances.some((p) => p.recentHitCounts.length > 0);
  if (!hasData) return { ...DEFAULT_WEIGHTS };

  // 각 모델의 EWMA 점수 계산
  const scores = performances.map((p) => {
    const windowed = applyWindow(p.recentHitCounts, config.windowSize);
    return calcEWMAScore(windowed, config.decayFactor);
  });

  // Softmax → 합 = 1.0
  const softmaxed = softmax(scores);

  // 최소 가중치 하한선 적용
  const floored = applyMinWeight(softmaxed, config.minWeight);

  // 합이 정확히 1.0이 되도록 마지막 정규화 (부동소수점 오차 제거)
  const total = floored.reduce((a, b) => a + b, 0);
  const normalized = floored.map((w) => w / total);

  // ModelWeights 객체로 변환 (MODEL_NAMES 순서 기준)
  const result: Partial<ModelWeights> = {};
  MODEL_NAMES.forEach((name, i) => {
    result[name] = normalized[i] ?? config.minWeight;
  });

  return result as ModelWeights;
}

// =====================================================
// DB 연동 함수
// =====================================================

/**
 * Supabase에서 전체 모델 성적을 조회하여 동적 가중치를 산출한다.
 * Edge Function에서 호출.
 *
 * @param supabaseClient - Supabase 클라이언트
 * @param config - MetaLearning 설정 (생략 시 기본값)
 * @returns ModelWeights + 근거 설명 문자열
 */
export async function computeMetaWeights(
  supabaseClient: any,
  config: MetaLearningConfig = DEFAULT_META_CONFIG
): Promise<{ weights: ModelWeights; reason: string }> {
  try {
    const performances = await getAllModelPerformances(
      supabaseClient,
      MODEL_NAMES,
      config.windowSize
    );

    const weights = calcDynamicWeights(performances, config);

    // 근거 문자열 생성
    const topModel = MODEL_NAMES.reduce((best, name) =>
      weights[name] > weights[best] ? name : best
    );
    const hasData = performances.some((p) => p.recentHitCounts.length > 0);
    const reason = hasData
      ? `최근 ${config.windowSize}회차 기준: ${topModel.toUpperCase()} 모델 가중치 최고 (${(weights[topModel] * 100).toFixed(1)}%)`
      : `성적 데이터 없음 — 기본 균등 가중치 사용`;

    return { weights, reason };
  } catch (err) {
    console.error("[metaLearning] computeMetaWeights error:", err);
    return {
      weights: { ...DEFAULT_WEIGHTS },
      reason: "Meta-Learning 오류 — 기본 가중치 폴백",
    };
  }
}
