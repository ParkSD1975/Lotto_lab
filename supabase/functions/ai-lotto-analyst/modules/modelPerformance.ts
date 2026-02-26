// =====================================================
// Phase 1 — 모델 성적 추적 모듈
// =====================================================
// model_predictions 테이블을 통해 각 모델의 예측 기록과
// 실제 당첨번호 대비 적중률을 추적한다.
// =====================================================

import type {
  ModelPredictionRecord,
  ModelPerformanceSummary,
  ModelName,
  MODEL_NAMES,
} from "../types.ts";

// =====================================================
// 예측 기록 저장
// =====================================================

/**
 * 현재 회차의 각 모델 예측 top10을 model_predictions 테이블에 저장한다.
 * Edge Function 분석 실행 시 호출.
 *
 * @param supabaseClient - Supabase 클라이언트 (any로 받아 Deno 환경 호환)
 * @param roundNumber - 현재 분석 회차
 * @param predictions - { 모델명: 예측 top10 번호 배열 }
 */
export async function savePredictions(
  supabaseClient: any,
  roundNumber: number,
  predictions: Record<ModelName, number[]>
): Promise<void> {
  const records: Omit<ModelPredictionRecord, "id" | "created_at">[] = [];

  for (const [modelName, top10] of Object.entries(predictions)) {
    records.push({
      round_number: roundNumber,
      model_name: modelName as ModelName,
      predicted_top10: top10.slice(0, 10),
    });
  }

  const { error } = await supabaseClient
    .from("model_predictions")
    .upsert(records, { onConflict: "round_number,model_name" });

  if (error) {
    console.error("[modelPerformance] savePredictions error:", error.message);
  }
}

// =====================================================
// 적중 횟수 갱신
// =====================================================

/**
 * 실제 당첨번호가 확정되면 해당 회차 예측들의 hit_count를 갱신한다.
 * 당첨번호 동기화 시 호출.
 *
 * @param supabaseClient - Supabase 클라이언트
 * @param roundNumber - 확정된 회차
 * @param actualNumbers - 실제 당첨번호 6개
 */
export async function updateHitCounts(
  supabaseClient: any,
  roundNumber: number,
  actualNumbers: number[]
): Promise<void> {
  const { data, error } = await supabaseClient
    .from("model_predictions")
    .select("id, predicted_top10")
    .eq("round_number", roundNumber)
    .is("actual_numbers", null);

  if (error || !data) {
    console.error("[modelPerformance] updateHitCounts fetch error:", error?.message);
    return;
  }

  const actualSet = new Set(actualNumbers);

  for (const row of data) {
    const hitCount = (row.predicted_top10 as number[]).filter((n) =>
      actualSet.has(n)
    ).length;

    await supabaseClient
      .from("model_predictions")
      .update({ actual_numbers: actualNumbers, hit_count: hitCount })
      .eq("id", row.id);
  }
}

// =====================================================
// 성적 조회
// =====================================================

/**
 * 특정 모델의 최근 N회차 성적을 조회한다.
 *
 * @param supabaseClient - Supabase 클라이언트
 * @param modelName - 조회할 모델 이름
 * @param windowSize - 최근 N회차 (기본 10)
 * @returns 모델 성적 요약
 */
export async function getModelPerformance(
  supabaseClient: any,
  modelName: ModelName,
  windowSize = 10
): Promise<ModelPerformanceSummary> {
  const { data, error } = await supabaseClient
    .from("model_predictions")
    .select("hit_count")
    .eq("model_name", modelName)
    .not("actual_numbers", "is", null)
    .order("round_number", { ascending: false })
    .limit(windowSize);

  if (error || !data || data.length === 0) {
    return {
      modelName,
      recentHitCounts: [],
      averageHitRate: 0,
      windowSize: 0,
    };
  }

  const recentHitCounts: number[] = data.map((r: any) => r.hit_count ?? 0);
  const averageHitRate =
    recentHitCounts.reduce((sum, h) => sum + h, 0) / (recentHitCounts.length * 6);

  return {
    modelName,
    recentHitCounts,
    averageHitRate,
    windowSize: recentHitCounts.length,
  };
}

/**
 * 전체 모델의 최근 성적을 일괄 조회한다.
 */
export async function getAllModelPerformances(
  supabaseClient: any,
  modelNames: readonly ModelName[],
  windowSize = 10
): Promise<ModelPerformanceSummary[]> {
  return Promise.all(
    modelNames.map((name) => getModelPerformance(supabaseClient, name, windowSize))
  );
}

// =====================================================
// 순수 계산 유틸 (테스트 가능)
// =====================================================

/**
 * 예측 배열과 실제 번호 배열을 비교하여 적중 번호 수를 반환한다.
 * (DB 없이 순수 로직 테스트용)
 */
export function calcHitCount(predicted: number[], actual: number[]): number {
  const actualSet = new Set(actual);
  return predicted.filter((n) => actualSet.has(n)).length;
}

/**
 * 최근 hit_count 배열에서 평균 적중률을 계산한다.
 * hit_count는 6개 번호 중 맞힌 개수이므로 /6으로 정규화.
 */
export function calcAverageHitRate(hitCounts: number[]): number {
  if (hitCounts.length === 0) return 0;
  const total = hitCounts.reduce((sum, h) => sum + h, 0);
  return total / (hitCounts.length * 6);
}

/**
 * 슬라이딩 윈도우: 배열에서 최근 N개만 추출한다.
 */
export function applyWindow<T>(arr: T[], windowSize: number): T[] {
  return arr.slice(0, windowSize);
}
