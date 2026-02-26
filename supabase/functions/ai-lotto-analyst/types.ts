// =====================================================
// 고급 AI 파이프라인 — 공통 타입 정의
// Phase 1: 데이터 기반 모듈 타입
// =====================================================

/** 로또 회차 원본 데이터 */
export interface LottoDraw {
  round: number;
  numbers: number[]; // 1~45, 6개
  date?: string;
}

// =====================================================
// Phase 1: 동반출현 행렬 타입
// =====================================================

/**
 * 동반출현 행렬
 * 키: "a-b" 형태 (a < b, 예: "3-17")
 * 값: 정규화된 동반출현 점수 (0~1)
 */
export type CoOccurrenceMatrix = Map<string, number>;

/** 정규화 전 원시 동반출현 횟수 */
export type RawCoOccurrenceMatrix = Map<string, number>;

// =====================================================
// Phase 1: 모델 성적 추적 타입
// =====================================================

/** Supabase model_predictions 테이블 레코드 */
export interface ModelPredictionRecord {
  id?: number;
  round_number: number;
  model_name: ModelName;
  predicted_top10: number[];
  actual_numbers?: number[];
  hit_count?: number;
  created_at?: string;
}

/** 지원 모델 이름 */
export type ModelName =
  | "lstm"
  | "xgboost"
  | "cnn"
  | "transformer"
  | "markov"
  | "autoencoder";

export const MODEL_NAMES: ModelName[] = [
  "lstm",
  "xgboost",
  "cnn",
  "transformer",
  "markov",
  "autoencoder",
];

/** 모델별 최근 성적 요약 */
export interface ModelPerformanceSummary {
  modelName: ModelName;
  recentHitCounts: number[]; // 최근 N회차 hit_count 배열 (최신순)
  averageHitRate: number;    // 평균 적중률 (0~1, hit_count / 6)
  windowSize: number;        // 사용된 회차 수
}

// =====================================================
// Phase 2~6 예약 타입 (추후 구현)
// =====================================================

/** Meta-Learning 가중치 출력 */
export interface ModelWeights {
  lstm: number;
  xgboost: number;
  cnn: number;
  transformer: number;
  markov: number;
  autoencoder: number;
}

/** RL 입력 인터페이스 */
export interface RLInput {
  numberScores: Record<number, number>;
  compatibility: (a: number, b: number) => number;
  filters: {
    sumRange?: [number, number];
    oddEvenRatio?: string;
    acRange?: [number, number];
    consecutiveMax?: number;
  };
  numGames: number;
}

/** Anomaly Detection 결과 */
export interface AnomalyResult {
  isAnomaly: boolean;
  reasons: string[];
  severity: "low" | "medium" | "high";
}

/** 신규 pipeline 필드 (Edge Function 응답에 추가) */
export interface PipelineInfo {
  modelWeights: ModelWeights;
  weightReasons: string;
  topCompatiblePairs: [number, number, number][]; // [numA, numB, score]
  anomalyResults: { combo: number[]; passed: boolean; reason?: string }[];
  aiReport: string;
}
