import os
import json
import numpy as np
import torch
import gc

# ==========================================
# 🧠 1. 5대+2대 진짜 모델 완벽 Import
# ==========================================
from models.xgboost_model import LottoXGBoost
from models.lstm_model import LSTMTrainer
from models.cnn_model import CNNTrainer
from models.transformer_model import TransformerTrainer
from models.autoencoder_model import AutoencoderTrainer
from models.gnn_model import GNNTrainer
from models.meta_learner import MetaLearner   # P7: Stacking 메타러너


# ============================================================
# Phase 0.3 → 완료: GNN 실제 Graph Attention Network로 재구현됨 (2025-04)
# gnn_model.py: 2-layer GAT + per-node classifier, BCEWithLogitsLoss 학습
# DISABLED_MODELS: 현재 비활성화 모델 없음 (모두 실제 딥러닝 구현 완료)
# ============================================================
DISABLED_MODELS: set = {"lstm", "transformer"}  # Stage 1-4-D-2 (사용자 결정 #24): LSTM/Transformer 폐기 (TFT 흡수)

# ============================================================
# Phase 0.4 — Task-Specific 가중치 매트릭스 (8종으로 확장)
#
# A. recommend_top  : 번호 추천(precision 최우선) — XGBoost·LSTM 시계열/이진분류 강점
# B. exclude        : 제외수(recall/특이도 최우선) — Autoencoder 비정상패턴 강점
# C. filter_range   : 범위형 필터(sum/tail_sum/ac) — Transformer·Markov 분포/전이 강점
# D. filter_count_attr     : 속성 개수형 필터(odd/high/prime 등) — Transformer 강점
# E. filter_count_temporal : 시간형 필터(hot10/cold10/missing 등) — LSTM·Markov 강점
# F. filter_count_relation : 관계형 필터(consecutive/neighbor/carryover) — GNN 강점
# G. filter_spatial : 공간형 필터(번호대/로또용지/9궁) — CNN 강점
# H. regression     : 회귀분석(predict_regression() fallback용) — LSTM·Markov 강점
#
# DISABLED_MODELS는 모든 태스크에서 자동으로 0 유지됨.
# 하위 호환 aliases: TASK_ALIASES 참조 (recommend→recommend_top, filter→filter_count_attr)
# 합계는 정규화로 항상 1.0이 되도록 predict_with_task()에서 처리.
# ============================================================
TASK_WEIGHTS = {
    # ── A. 번호 추천 (precision 최우선) ─────────────────────────────────
    "recommend_top": {
        "xgboost":     0.30,
        "lstm":        0.20,
        "cnn":         0.08,
        "transformer": 0.15,
        "gnn":         0.15,
        "markov":      0.10,
        "autoencoder": 0.02,
    },
    # ── B. 제외수 (recall/특이도 최우선) ────────────────────────────────
    "exclude": {
        "xgboost":     0.15,
        "lstm":        0.05,
        "cnn":         0.05,
        "transformer": 0.00,
        "gnn":         0.20,
        "markov":      0.15,
        "autoencoder": 0.40,
    },
    # ── C. 범위형 필터: sum / tail_sum / ac ──────────────────────────────
    "filter_range": {
        "xgboost":     0.15,
        "lstm":        0.15,
        "cnn":         0.05,
        "transformer": 0.25,
        "gnn":         0.10,
        "markov":      0.30,
        "autoencoder": 0.00,
    },
    # ── D. 개수형 속성 필터: odd/high/prime/composite/배수/특수유형/커스텀
    "filter_count_attr": {
        "xgboost":     0.20,
        "lstm":        0.10,
        "cnn":         0.10,
        "transformer": 0.30,
        "gnn":         0.10,
        "markov":      0.15,
        "autoencoder": 0.05,
    },
    # ── E. 시간형 필터: hot10/cold10/neutral10/missing ───────────────────
    "filter_count_temporal": {
        "xgboost":     0.20,
        "lstm":        0.30,
        "cnn":         0.05,
        "transformer": 0.10,
        "gnn":         0.10,
        "markov":      0.25,
        "autoencoder": 0.00,
    },
    # ── F. 관계형 필터: consecutive/neighbor/carryover ───────────────────
    "filter_count_relation": {
        "xgboost":     0.10,
        "lstm":        0.20,
        "cnn":         0.15,
        "transformer": 0.05,
        "gnn":         0.35,
        "markov":      0.15,
        "autoencoder": 0.00,
    },
    # ── G. 공간형 필터: 번호대/로또용지/9궁 ─────────────────────────────
    "filter_spatial": {
        "xgboost":     0.10,
        "lstm":        0.10,
        "cnn":         0.40,
        "transformer": 0.15,
        "gnn":         0.20,
        "markov":      0.05,
        "autoencoder": 0.00,
    },
    # ── H. 회귀분석 (predict_regression() 별도 경로 우선, fallback용) ────
    "regression": {
        "xgboost":     0.20,
        "lstm":        0.35,
        "cnn":         0.00,
        "transformer": 0.15,
        "gnn":         0.00,
        "markov":      0.30,
        "autoencoder": 0.00,
    },
}

# 하위 호환 aliases (기존 3종 task명 → 새 task명)
# "exclude"는 이름 동일하므로 alias 불필요
TASK_ALIASES: dict = {
    "recommend": "recommend_top",
    "filter":    "filter_count_attr",
}

# filter_key → sub-task 자동 매핑 상수
FILTER_KEY_TO_TASK: dict = {
    # 범위형
    "sum": "filter_range", "tail_sum": "filter_range", "ac": "filter_range",
    # 속성 개수형
    "odd": "filter_count_attr", "high": "filter_count_attr",
    "prime": "filter_count_attr", "composite": "filter_count_attr",
    "square": "filter_count_attr", "triangular": "filter_count_attr",
    "twin": "filter_count_attr",
    "mul3": "filter_count_attr", "mul4": "filter_count_attr",
    "mul5": "filter_count_attr", "mul7": "filter_count_attr",
    "mul8": "filter_count_attr",
    "mul34": "filter_count_attr", "mul35": "filter_count_attr",
    "mul45": "filter_count_attr", "non_multiple": "filter_count_attr",
    # digit0~9
    **{f"digit{i}": "filter_count_attr" for i in range(10)},
    # 시간형
    "hot10": "filter_count_temporal", "neutral10": "filter_count_temporal",
    "cold10": "filter_count_temporal", "missing": "filter_count_temporal",
    # 관계형
    "consecutive": "filter_count_relation",
    "neighbor": "filter_count_relation",
    "carryover": "filter_count_relation",
    # 공간형 — 번호대
    "단번대": "filter_spatial", "10번대": "filter_spatial",
    "20번대": "filter_spatial", "30번대": "filter_spatial",
    "40번대": "filter_spatial",
    # 공간형 — 용지/궁
    **{f"가로{i}": "filter_spatial" for i in range(1, 4)},
    **{f"세로{i}": "filter_spatial" for i in range(1, 4)},
    **{f"{i}궁":   "filter_spatial" for i in range(1, 10)},
    # 회귀
    **{f"regression_step_{i}": "regression" for i in range(2, 201)},
}


class LottoEnsemble:
    def __init__(self):
        self.seq_len = 5
        self.save_dir = "saved_models"
        os.makedirs(self.save_dir, exist_ok=True)

        # 메타 러닝 가중치 영구 저장 파일
        self.weights_file = os.path.join(self.save_dir, "ensemble_weights.json")

        # 🌟 딥러닝/머신러닝 진짜 모델 객체화 (기존 7 base)
        self.models = {
            "xgboost": LottoXGBoost(),
            "lstm": LSTMTrainer(),
            "cnn": CNNTrainer(),
            "transformer": TransformerTrainer(),
            "autoencoder": AutoencoderTrainer(),
            "gnn": GNNTrainer()
        }

        # ── Master Plan Stage 1-4-D-2: 5 신규 base lazy init ──
        # 사용자 결정 #24 — 11 base 토폴로지 (LSTM/Transformer는 TFT 흡수, 추후 archive).
        # 라이브러리 미설치 시 graceful skip. 학습 가중치는 D-3 학습 후 활성.
        self._init_new_base_models()

        # 기본 뼈대 가중치 (초기값) - 합계 1.0
        # Stage 1-4-D-2 (사용자 결정 #24): LSTM/Transformer 폐기 (TFT 흡수)
        # 5 신규 base 추가 (default 0, D-3 학습 후 활성)
        # Phase 0.3 완료: GNN 실제 GAT
        self.default_weights = {
            "xgboost":     0.30,
            "lstm":        0.0,    # 사용자 결정 #24 폐기 (TFT 흡수)
            "cnn":         0.15,
            "transformer": 0.0,    # 사용자 결정 #24 폐기 (TFT 흡수)
            "gnn":         0.20,
            "markov":      0.10,
            "autoencoder": 0.05,
            # Stage 1-4-D-2 신규 (D-3 학습 후 활성)
            "catboost":    0.0,
            "tabnet":      0.0,
            "tft":         0.20,   # LSTM/Transformer 흡수 (D-3 학습 후 활성)
            "mhn":         0.0,
            "bayesian_nn": 0.0,
        }
        # 폐기 모델 명시 — 프론트 노출 X
        self.deprecated_models = {"lstm", "transformer"}

        # ★ 시스템 시작 시 진화된 가중치가 있다면 불러오기
        self.weights = self._load_meta_weights()

        # P7: Stacking 메타러너 (100+ 회차 로그 누적 후 자동 활성화)
        # M-1-C: meta_alpha는 meta_learner.alpha (학습 가능 파라미터, fit_alpha 갱신)
        self.meta_learner  = MetaLearner(self.save_dir)
        self._meta_loaded  = False  # 최초 predict 때 한 번만 로드 시도

        # ── Master Plan Stage 1-4-D-1: predictor_pipeline 통합 ──
        # 사용자 결정 #23: T-1 결정 A 폐기. INPUT_DIM 동결 해제 (config.INPUT_DIM_FROZEN=False).
        # 메인 모델 학습 인터페이스 변경은 D-2 (별도 PR — 11 base 신규 학습 8~12h 소요).
        # 본 D-1은 추론 시점 evidence 합류만 — saved_models 재학습 X.
        self.predictor_pipeline = None  # lazy init (predict 호출 시점에 생성)
        self._predictor_pipeline_loaded = False

    @property
    def meta_alpha(self) -> float:
        """M-1-C: alpha를 meta_learner의 learnable property로 위임."""
        return self.meta_learner.alpha

    def _load_meta_weights(self):
        """저장된 메타 가중치(학습된 비중)를 불러옵니다."""
        base_weights = self.default_weights.copy()
        if os.path.exists(self.weights_file):
            try:
                with open(self.weights_file, "r") as f:
                    w = json.load(f)
                    for k, v in w.items():
                        if k in base_weights:
                            # DISABLED_MODELS는 파일 값 무시하고 항상 0 유지
                            if k in DISABLED_MODELS:
                                base_weights[k] = 0.0
                            else:
                                # 이전 버전에서 0으로 저장된 경우 기본값 사용 (마이그레이션 대응)
                                base_weights[k] = v if v > 0 else base_weights[k]
                    print(f"🧠 [Meta-Learning] 진화된 동적 가중치 로드 완료: {base_weights}")
            except Exception:
                pass

        # Phase 0.3: DISABLED_MODELS 강제 0 적용 (파일에 없던 모델 포함)
        for m in DISABLED_MODELS:
            if m in base_weights:
                base_weights[m] = 0.0

        # 합계가 1.0이 아닌 경우 정규화 (마이그레이션/rounding drift 방지)
        # DISABLED_MODELS(0)는 정규화에서 자연스럽게 0 유지됨
        total = sum(base_weights.values())
        if total > 0 and abs(total - 1.0) > 0.001:
            # DISABLED_MODELS 제외하고 정규화
            enabled = {k: v for k, v in base_weights.items() if k not in DISABLED_MODELS}
            enabled_total = sum(enabled.values())
            if enabled_total > 0:
                for k in enabled:
                    base_weights[k] = round(enabled[k] / enabled_total, 4)
            print(f"⚠️ [Meta-Learning] 가중치 합계({total:.4f}) 비정상 → 정규화 완료 (비활성화 모델 제외)")

        # 파일에 누락된 모델 키가 있을 경우 최신 키로 갱신 저장
        try:
            with open(self.weights_file, "w") as f:
                json.dump(base_weights, f, indent=2)
        except Exception:
            pass

        return base_weights

    # ── M-1-F: Task 가중치 매트릭스 외부화 ─────────────────────────────────
    def _task_weights_path(self) -> str:
        try:
            import config
            return os.path.join(self.save_dir,
                                getattr(config, "TASK_WEIGHTS_FILE", "task_weights.json"))
        except Exception:
            return os.path.join(self.save_dir, "task_weights.json")

    def load_task_weights(self) -> dict:
        """M-1-F: saved_models/task_weights.json 로드.

        파일 없거나 부분 누락 시 본 모듈의 TASK_WEIGHTS 하드코딩 default로 보완.
        return: 8 task × 7 model 매트릭스 (최종 사용용)
        """
        try:
            import config
            external = getattr(config, "TASK_WEIGHTS_EXTERNAL", True)
        except Exception:
            external = True

        # default를 deep copy
        merged = {task: weights.copy() for task, weights in TASK_WEIGHTS.items()}

        if not external:
            return merged

        path = self._task_weights_path()
        if not os.path.exists(path):
            return merged

        try:
            with open(path, "r", encoding="utf-8") as f:
                ext_data = json.load(f)
            for task, weights in ext_data.items():
                if task not in merged:
                    continue
                if not isinstance(weights, dict):
                    continue
                for m, v in weights.items():
                    if m in merged[task] and isinstance(v, (int, float)) and v >= 0:
                        merged[task][m] = float(v)
        except Exception as e:
            print(f"  [Ensemble] task_weights.json 로드 실패 (default 사용): {e}")

        return merged

    def save_task_weights(self, task_weights: dict) -> None:
        """M-1-F: 학습된 task 가중치 매트릭스를 외부 파일에 영속화."""
        path = self._task_weights_path()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(task_weights, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"  [Ensemble] task_weights.json 저장 실패: {e}")

    # ── M-1-E: AE 게이트 boolean 플래그 broadcast ──────────────────────────
    def _ae_threshold_path(self) -> str:
        return os.path.join(self.save_dir, "ae_anomaly_threshold.json")

    def calibrate_anomaly_threshold(self, train_fold_draws: list, percentile: int = None) -> dict:
        """M-1-E: 학습 fold AE 재구성오차 분포의 percentile로 임계값 산출.

        Args:
            train_fold_draws: 학습 fold draws (각 회차마다 AE 평가)
            percentile: 기본 95 (config.AE_GATE_PERCENTILE)

        Returns:
            {threshold, n_samples, percentile, mean, std}
        """
        if percentile is None:
            try:
                import config as _cfg
                percentile = getattr(_cfg, "AE_GATE_PERCENTILE", 95)
            except Exception:
                percentile = 95

        ae = self.models.get("autoencoder")
        if ae is None or len(train_fold_draws) < 5:
            return {"threshold": 0.5, "n_samples": 0, "percentile": percentile,
                    "fitted": False, "reason": "AE 미초기화 또는 fold 부족"}

        recon_errors = []
        for i in range(3, len(train_fold_draws)):
            window = train_fold_draws[i - 3 : i]
            try:
                excl = ae.predict_exclusions(window, threshold=0.0)  # threshold=0 → 모든 번호 오차
                if isinstance(excl, dict) and excl:
                    recon_errors.append(float(np.mean(list(excl.values()))))
            except Exception:
                continue

        if not recon_errors:
            return {"threshold": 0.5, "n_samples": 0, "percentile": percentile,
                    "fitted": False, "reason": "AE predict 실패"}

        arr = np.array(recon_errors, dtype=np.float64)
        threshold = float(np.percentile(arr, percentile))
        try:
            with open(self._ae_threshold_path(), "w") as f:
                json.dump({
                    "threshold": threshold,
                    "percentile": percentile,
                    "n_samples": len(arr),
                    "mean": float(arr.mean()),
                    "std": float(arr.std()),
                }, f, indent=2)
        except Exception:
            pass

        return {"threshold": threshold, "n_samples": len(arr),
                "percentile": percentile, "fitted": True,
                "mean": float(arr.mean()), "std": float(arr.std())}

    def _load_ae_threshold(self) -> float:
        """저장된 AE 임계값 로드 — 없으면 static fallback 0.5."""
        path = self._ae_threshold_path()
        if not os.path.exists(path):
            return 0.5
        try:
            with open(path, "r") as f:
                data = json.load(f)
            return float(data.get("threshold", 0.5))
        except Exception:
            return 0.5

    def compute_anomaly_flag(self, draws: list, threshold: float = None) -> dict:
        """M-1-E: 회차별 AE 재구성오차 → boolean "이상 회차" 플래그.

        17 predictor가 자기 출력에 직접 AE 페널티를 적용하지 않고,
        본 메서드의 boolean 결과를 broadcast 받아 *복잡 모델 가중치 dampening*에 사용.

        Args:
            draws: round 내림차순 draws (최근 3개 회차로 평가)
            threshold: 명시적 임계값 — None이면 saved_models/ae_anomaly_threshold.json

        Returns:
            {
              "is_anomaly":   bool,
              "recon_error":  float,
              "threshold":    float,
              "available":    bool,    # AE 모델/임계값 사용 가능 여부
            }
        """
        if threshold is None:
            threshold = self._load_ae_threshold()

        ae = self.models.get("autoencoder")
        if ae is None or len(draws) < 3:
            return {"is_anomaly": False, "recon_error": 0.0,
                    "threshold": threshold, "available": False}

        try:
            excl = ae.predict_exclusions(draws[:3], threshold=0.0)
            if not isinstance(excl, dict) or not excl:
                return {"is_anomaly": False, "recon_error": 0.0,
                        "threshold": threshold, "available": False}
            recon_error = float(np.mean(list(excl.values())))
        except Exception:
            return {"is_anomaly": False, "recon_error": 0.0,
                    "threshold": threshold, "available": False}

        return {
            "is_anomaly":  bool(recon_error > threshold),
            "recon_error": recon_error,
            "threshold":   threshold,
            "available":   True,
        }

    def _load_db_hit_counts(self, recent_n: int = 20) -> dict:
        """[Phase 1.1] Supabase model_performance_log에서 최근 N회차 모델별 적중률 조회.
        반환: {model_name: avg_hit_count} — 없으면 {} 반환"""
        try:
            from db.supabase_client import get_client
            client = get_client()
            result = (
                client.table("model_performance_log")
                .select("model_name, hit_count, round")
                .order("round", desc=True)
                .limit(recent_n * 7)   # 최대 7개 모델 × N회차
                .execute()
            )
            rows = result.data or []
            if not rows:
                return {}

            from collections import defaultdict
            hits_by_model = defaultdict(list)
            for row in rows:
                mn = row.get("model_name", "")
                hc = row.get("hit_count")
                if mn and hc is not None:
                    hits_by_model[mn].append(int(hc))

            avg_hits = {}
            for model_name, hits in hits_by_model.items():
                recent_hits = hits[:recent_n]  # 최신 N회차만
                avg_hits[model_name] = sum(recent_hits) / len(recent_hits) if recent_hits else 0.0

            print(f"🧠 [DB Weights] 최근 {recent_n}회차 모델별 평균 적중수: {avg_hits}")
            return avg_hits
        except Exception as e:
            print(f"⚠️ [DB Weights] DB 적중률 조회 실패 (파일 기반 유지): {e}")
            return {}

    def _update_meta_weights(self, draws):
        """[Phase 1.1 강화] DB 적중률 + 모의고사를 결합하여 동적 가중치 재조정."""
        print("🧠 [Meta-Learning] 최신 당첨 번호로 모델별 모의고사를 실시합니다...")
        try:
            draws_asc = sorted(draws, key=lambda x: x['round'])
            latest_draw = draws_asc[-1]
            history = draws_asc[:-1]
            actual_numbers = set(latest_draw["numbers"])

            # ① DB에서 최근 20회차 모델별 평균 적중수 조회
            db_avg_hits = self._load_db_hit_counts(recent_n=20)

            # ② 현재 가중치를 시작점으로 사용
            scores = {k: v for k, v in self.weights.items()}

            # ③ DB 적중률 반영 (파일 기반 보너스보다 DB 우선)
            if db_avg_hits:
                total_avg = sum(db_avg_hits.values()) or 1.0
                for name in scores:
                    avg_hit = db_avg_hits.get(name, 0.0)
                    # 평균 적중률 기반 가중치 비율로 점수 보정
                    db_weight = avg_hit / total_avg if total_avg > 0 else 0.0
                    # 기존 파일 기반 가중치와 DB 기반 가중치를 50:50 블렌딩
                    scores[name] = 0.5 * scores[name] + 0.5 * db_weight
                    # 최솟값 5% 보장
                    scores[name] = max(scores[name], 0.05)
                print(f"🧠 [Meta-Learning] DB 적중률 블렌딩 완료")
            else:
                # DB 없으면 기존 모의고사 방식으로만 진행
                for name, model in self.models.items():
                    try:
                        preds = model.predict(history)
                        top_10 = sorted(preds, key=preds.get, reverse=True)[:10]
                        hits = len(set(top_10) & actual_numbers)
                        bonus = hits * 0.05
                        scores[name] += bonus
                        print(f"    - [{name.upper()}] 모의고사 적중: {hits}개 (보상 +{bonus:.2f})")
                    except Exception as e:
                        print(f"    - [{name.upper()}] 평가 보류: {e}")
                    finally:
                        if hasattr(model, 'model'):
                            del model.model
                            model.model = None
                        if name == "xgboost" and hasattr(model, 'models'):
                            del model.models
                            model.models = {}
                        torch.cuda.empty_cache()
                        gc.collect()

            # 마르코프 연쇄 고정 소폭 보너스 유지
            scores["markov"] = max(scores.get("markov", 0.05), 0.05) + 0.02

            # Phase 0.3: DISABLED_MODELS 가중치 강제 0
            for m in DISABLED_MODELS:
                if m in scores:
                    scores[m] = 0.0

            # 정규화 (비활성화 모델 제외)
            enabled_scores = {k: v for k, v in scores.items() if k not in DISABLED_MODELS}
            total = sum(enabled_scores.values()) or 1.0
            new_weights = {}
            for k in scores:
                if k in DISABLED_MODELS:
                    new_weights[k] = 0.0
                else:
                    new_weights[k] = round(scores[k] / total, 3)

            self.weights = new_weights
            with open(self.weights_file, "w") as f:
                json.dump(self.weights, f)
            print(f"✅ [Meta-Learning] 새로운 메타 가중치: {new_weights}")

        except Exception as e:
            print(f"⚠️ [Meta-Learning] 가중치 조정 오류 (기존값 유지): {e}")

    def train_all(self, draws, force_retrain=False):
        if len(draws) < 100:
            return {"success": False, "message": "데이터 부족"}

        print("🧠 [딥러닝 엔진] 7중 앙상블 파인튜닝(증분 학습) 시작...")
        
        # ★ 새로운 데이터를 뇌에 각인시키기 전에, 방금 들어온 최신 데이터로 모의고사(평가) 먼저 실시!
        if not force_retrain:
            self._update_meta_weights(draws)
        
        # 1. 5대 모델 파인튜닝
        for name, model in self.models.items():
            print(f"  ▶ {name.upper()} 진짜 모델 파인튜닝 진행 중...")
            try:
                if name == "autoencoder":
                    model.train(draws)
                else:
                    model.train(draws, fine_tune=not force_retrain)
            except Exception as e:
                print(f"  ❌ {name} 모델 파인튜닝 실패: {e}")
            finally:
                if hasattr(model, 'model'):
                    del model.model
                    model.model = None
                if name == "xgboost" and hasattr(model, 'models'):
                    del model.models
                    model.models = {}
                torch.cuda.empty_cache()
                gc.collect()

        # 2. 마르코프 전이 행렬 파인튜닝
        print("  ▶ MARKOV 모델 확률 행렬 업데이트 중...")
        self._train_temp_markov(draws)

        return {"success": True, "message": "모든 모델 파인튜닝 및 메타 러닝 완료!"}

    def _train_temp_markov(self, draws):
        draws_asc = sorted(draws, key=lambda x: x['round'])
        markov_matrix = np.zeros((45, 45))
        for i in range(len(draws_asc) - 1):
            curr_nums = draws_asc[i]["numbers"]
            next_nums = draws_asc[i+1]["numbers"]
            for c in curr_nums:
                for n in next_nums:
                    if 1 <= c <= 45 and 1 <= n <= 45:
                        markov_matrix[c-1][n-1] += 1
                        
        row_sums = markov_matrix.sum(axis=1)
        for i in range(45):
            if row_sums[i] > 0: markov_matrix[i] /= row_sums[i]
                
        with open(os.path.join(self.save_dir, "markov.json"), "w") as f:
            json.dump(markov_matrix.tolist(), f)

    def _init_new_base_models(self):
        """Master Plan Stage 1-4-D-2: 5 신규 base 메인 1~45 binary classifier 등록.

        5 신규 base:
          - catboost / tabnet: 트리·attention (input_dim 인자 없음/필요 분기)
          - tft: 시계열 통합 (LSTM/Transformer 흡수, input_dim 필요)
          - mhn: 패턴 매칭 메모리 (input_dim 필요)
          - bayesian_nn: 불확실성 분포 (input_dim 필요)

        라이브러리 미설치 또는 인스턴스화 실패 시 graceful skip.
        실 학습은 Stage 1-4-D-3 (사용자 환경 8~12h).
        """
        try:
            input_dim = config.MAIN_MODEL_INPUT_DIM or config.LSTM_INPUT_DIM
        except (AttributeError, NameError):
            input_dim = 65

        new_base_specs = [
            # (key, module_path, class_name, needs_input_dim)
            ("catboost",    "models.catboost_model",    "LottoCatBoost",   False),
            ("tabnet",      "models.tabnet_model",      "LottoTabNet",     True),
            ("tft",         "models.tft_model",         "LottoTFT",        True),
            ("mhn",         "models.mhn_model",         "LottoMHN",        True),
            ("bayesian_nn", "models.bayesian_nn_model", "LottoBayesianNN", True),
        ]

        for key, mod_path, cls_name, needs_dim in new_base_specs:
            try:
                mod = __import__(mod_path, fromlist=[cls_name])
                cls = getattr(mod, cls_name, None)
                if cls is None:
                    print(f"[Stage 1-4-D-2] {key} skip (class not found)")
                    continue
                # task_type="binary_45" - main 1~45 sigmoid multi-hot
                kwargs = {"task_type": "binary_45", "num_classes": 45}
                if needs_dim:
                    kwargs["input_dim"] = input_dim
                self.models[key] = cls(**kwargs)
                print(f"[Stage 1-4-D-2] {key} registered (input_dim={input_dim if needs_dim else 'n/a'})")
            except ImportError as e:
                # CatBoost / TabNet / PyTorch-Forecasting / HFLayers / torch missing
                print(f"[Stage 1-4-D-2] {key} skip (library not available): {e}")
            except (TypeError, ValueError) as e:
                # signature mismatch - surface real message for debug
                print(f"[Stage 1-4-D-2] {key} init fail (signature): {type(e).__name__}: {e}")
            except Exception as e:
                print(f"[Stage 1-4-D-2] {key} init fail (graceful): {type(e).__name__}: {e}")

    def _get_predictor_pipeline(self):
        """Master Plan Stage 1-4-D-1: predictor_pipeline lazy init.

        실패 시 None 반환 (graceful fallback — 기존 7 base 추론 그대로).
        """
        if self._predictor_pipeline_loaded:
            return self.predictor_pipeline
        self._predictor_pipeline_loaded = True
        try:
            from predictors.predictor_pipeline import PredictorPipeline
            self.predictor_pipeline = PredictorPipeline(feature_dim=24)
            return self.predictor_pipeline
        except Exception as e:
            print(f"⚠️ [Stage 1-4-D] predictor_pipeline init fail (graceful): {e}")
            self.predictor_pipeline = None
            return None

    def predict(self, draws, human_rules=None):
        if len(draws) < self.seq_len:
            return {"probabilities": {}, "model_contributions": {}, "evidence": {}}

        contributions = {m: {} for m in self.weights.keys()}

        # 1. 딥러닝/머신러닝 예측
        for name, model in self.models.items():
            try:
                pred_dict = model.predict(draws)
                for n in range(1, 46):
                    # 키 타입 불일치 방지: 정수/문자열 모두 시도
                    val = pred_dict.get(n, None)
                    if val is None:
                        val = pred_dict.get(str(n), 0.0)
                    contributions[name][n] = float(val)
            except Exception as e:
                print(f"⚠️ {name} 예측 실패: {e}")
                for n in range(1, 46):
                    contributions[name][n] = 0.0
            # 🛠️ [교정 완료] 실시간 분석(predict)에서는 모델을 메모리에서 지우지 않고 유지하여 0.1초 반응성 확보

        # 2. 마르코프 연쇄 예측
        markov_path = os.path.join(self.save_dir, "markov.json")
        if os.path.exists(markov_path):
            with open(markov_path, "r") as f:
                markov_matrix = np.array(json.load(f))
            recent_draws = sorted(draws, key=lambda x: x['round'])
            last_nums = recent_draws[-1].get("numbers", [])
            pred_markov = np.zeros(45)
            for num in last_nums:
                if 1 <= num <= 45: pred_markov += markov_matrix[num-1]
            if len(last_nums) > 0: pred_markov /= len(last_nums)
            for n in range(1, 46):
                contributions["markov"][n] = float(pred_markov[n-1])

        # 3. ★ 진화된 메타 가중치를 적용하여 1차 합산!
        final_probs = {}
        for n in range(1, 46):
            score = sum(contributions[m].get(n, 0) * self.weights.get(m, 0) for m in self.weights.keys())
            final_probs[n] = score

        # 4. Autoencoder 비정상 패턴(쏠림/이상치) 페널티 부여
        try:
            ae_exclusions = self.models["autoencoder"].predict_exclusions(draws)
        except Exception:
            ae_exclusions = {}
        # 🛠️ [교정 완료] 실시간 분석 시 Autoencoder도 메모리에 유지

        for n in range(1, 46):
            ae_excl_val = float(ae_exclusions.get(n, 0))
            if n in ae_exclusions:
                final_probs[n] *= (1.0 - ae_excl_val)

        # 5. 전문가 메모 (Hard Filter) 철통 방어
        evidence_reasons = []
        memo_excl = []
        if human_rules:
            summary = human_rules.get("summary", "전문가 분석 룰 적용")
            evidence_reasons.append(f"💡 [사용자 통제] {summary}")
            
            if "excluded_numbers" in human_rules:
                memo_excl = [int(x) for x in human_rules["excluded_numbers"] if str(x).isdigit() or isinstance(x, int)]
                
            for n in range(1, 46):
                if n in memo_excl:
                    final_probs[n] = 0.0

        # 6. 최종 확률 100% 맞추기 (정규화)
        total_score = sum(final_probs.values())
        if total_score > 0:
            final_probs = {n: v / total_score for n, v in final_probs.items()}
        else:
            final_probs = {n: 1/45 for n in range(1, 46)}

        # 6-P7. 메타러너 블렌딩 (모델이 준비된 경우만)
        meta_active = False
        meta_importance = {}
        if not self._meta_loaded:
            self.meta_learner._load()
            self._meta_loaded = True

        if self.meta_learner.meta_model is not None and self.meta_alpha > 0:
            try:
                meta_probs = self.meta_learner.predict(contributions)
                if meta_probs:
                    # (1 - alpha) × ensemble + alpha × meta
                    alpha = self.meta_alpha
                    blended = {
                        n: (1.0 - alpha) * final_probs.get(n, 0.0)
                           + alpha * meta_probs.get(n, 0.0)
                        for n in range(1, 46)
                    }
                    # 재정규화
                    total_b = sum(blended.values())
                    if total_b > 0:
                        final_probs = {n: v / total_b for n, v in blended.items()}
                    meta_active = True
                    meta_importance = self.meta_learner.get_feature_importance()
            except Exception as _em:
                print(f"[MetaLearner] 블렌딩 실패 (무시): {_em}")

        _meta_signal = (
            f"P7 메타러너 활성 (alpha={self.meta_alpha:.2f}, "
            f"top={max(meta_importance, key=meta_importance.get, default='?')})"
            if meta_active and meta_importance else
            "P7 메타러너 대기 중 (로그 누적 필요)"
        )
        # ── Master Plan Stage 1-4-D-1: predictor_pipeline evidence 합류 ──
        # Phase 1~4 22 predictor + 회귀 4 Tier 출력 — 4 Pillar Pillar 2/3 입력 제공.
        # final_probs는 변경 X (메인 7 base 결과 그대로). evidence로만 노출.
        # 학습된 predictor_pipeline 가용 시 추론, 미가용 시 graceful skip.
        predictor_outputs = None
        pp = self._get_predictor_pipeline()
        if pp is not None and pp._is_trained:
            try:
                predictor_outputs = pp.predict_all(draws)
            except Exception as _pe:
                print(f"⚠️ [Stage 1-4-D] predictor_pipeline.predict_all fail (graceful): {_pe}")
                predictor_outputs = None

        evidence = {
            "model_weights": self.weights,
            "meta_active":   meta_active,
            "meta_alpha":    self.meta_alpha if meta_active else 0.0,
            "meta_importance": meta_importance,
            "top_signals": [
                {"model": "Human-in-the-loop",
                 "signal": evidence_reasons[0] if evidence_reasons else "전문가 메모 미적용"},
                {"model": "Ensemble",
                 "signal": "메타 러닝을 통한 동적 가중치 앙상블 적용 완료"},
                {"model": "MetaLearner", "signal": _meta_signal},
            ],
            # Stage 1-4-D-1 신규: 22 predictor + 회귀 4 Tier evidence
            "predictor_pipeline_outputs": predictor_outputs,
            "predictor_pipeline_active": predictor_outputs is not None,
        }

        return {
            "probabilities": final_probs,
            "model_contributions": contributions,
            "xai_contributions": self.compute_xai_contributions(
                contributions, self.weights, memo_excl
            ),
            "evidence": evidence,
            # Stage 1-4-D-1 신규: 4 Pillar/NumberRecommender 입력으로 직접 전달 가능
            "predictor_pipeline_outputs": predictor_outputs,
        }

    def compute_xai_contributions(
        self,
        contributions: dict,
        task_weights: dict,
        memo_excl: list = None,
    ) -> dict:
        """XAI 기여도 계산 — baseline(1/45) 초과분 기반.

        각 모델의 raw_prob 중 균등확률(1/45)을 초과하는 신호만 추출하여
        task_weight를 곱한 뒤 번호별로 퍼센트 기여도를 계산한다.

        Args:
            contributions: predict()가 수집한 {model: {num: prob}} 딕셔너리.
            task_weights:  사용된 가중치 딕셔너리 {model: weight}.
            memo_excl:     hard filter로 제외된 번호 목록 (해당 번호는 veto 처리).

        Returns:
            {
              17: {
                "lstm": 60.6,
                "xgboost": 29.1,
                "transformer": 6.3,
                "markov": 2.8,
                "gnn": 1.2,
                "cnn": 0.0,
                "autoencoder": 0.0,
                "top_model": "lstm",
                "veto": None
              },
              ...  # 1~45 전체
            }
        """
        baseline = 1.0 / 45.0
        memo_excl_set = set(memo_excl) if memo_excl else set()
        model_names = list(task_weights.keys())

        result: dict = {}

        for n in range(1, 46):
            # hard filter 번호: 모든 기여도 0, veto 처리
            if n in memo_excl_set:
                entry = {m: 0.0 for m in model_names}
                entry["top_model"] = "veto"
                entry["veto"] = "hard_filter"
                result[n] = entry
                continue

            # 각 모델별 excess 점수 계산
            scores: dict = {}
            for m in model_names:
                raw_prob = contributions.get(m, {}).get(n, 0.0)
                excess = max(0.0, raw_prob - baseline)
                scores[m] = excess * task_weights.get(m, 0.0)

            total_score = sum(scores.values())

            entry: dict = {}
            if total_score > 0:
                # 정상 케이스: excess 신호 합산이 0보다 큰 경우
                for m in model_names:
                    entry[m] = round(scores[m] / total_score * 100.0, 1)
            else:
                # 모든 모델이 baseline 이하인 번호: 가중치 비율로만 기여도 계산
                weight_total = sum(task_weights.get(m, 0.0) for m in model_names)
                for m in model_names:
                    w = task_weights.get(m, 0.0)
                    entry[m] = round((w / weight_total * 100.0) if weight_total > 0 else 0.0, 1)

            # top_model: 기여도가 가장 높은 모델
            top_model = max(model_names, key=lambda m: entry.get(m, 0.0))
            entry["top_model"] = top_model
            entry["veto"] = None
            result[n] = entry

        return result

    def predict_with_task(self, draws: list, task: str = "recommend",
                          human_rules=None) -> dict:
        """Phase 0.4 — task별 최적 가중치를 적용한 앙상블 예측.

        Args:
            task: 8종 task 중 하나 또는 하위 호환 alias.
                  - recommend_top (alias: recommend) : 번호 추천 (Top 20/5)
                  - filter_count_attr (alias: filter) : 속성 개수형 필터
                  - filter_range   : 범위형 필터
                  - filter_count_temporal : 시간형 필터
                  - filter_count_relation : 관계형 필터
                  - filter_spatial : 공간형 필터
                  - exclude        : 제외수 10개 선출
                  - regression     : 회귀분석 fallback
        Returns:
            predict()와 동일한 구조 + task_weights / task_key / task_resolved 필드 추가
        """
        # 1. TASK_ALIASES 처리 (하위 호환)
        task_key_original = task
        task_resolved = TASK_ALIASES.get(task, task)

        if task_resolved not in TASK_WEIGHTS:
            return self.predict(draws, human_rules=human_rules)

        # 2. task별 기본 가중치 가져오기
        task_w = TASK_WEIGHTS[task_resolved].copy()

        # 3. 동적 가중치(DB 성과 기반)와 블렌딩: task_base 70% + dynamic 30%
        dynamic_w = self.weights  # _load_meta_weights()로 로드된 현재 가중치
        blended = {}
        for m in task_w:
            if m in DISABLED_MODELS:
                blended[m] = 0.0
            else:
                blended[m] = 0.70 * task_w.get(m, 0) + 0.30 * dynamic_w.get(m, 0)

        # 4. 정규화 (DISABLED 제외)
        total = sum(v for k, v in blended.items() if k not in DISABLED_MODELS)
        if total > 0:
            blended = {k: (0.0 if k in DISABLED_MODELS else round(v / total, 4))
                       for k, v in blended.items()}

        # 5. 임시로 가중치 교체하여 predict() 실행
        original_weights = self.weights
        self.weights = blended
        result = self.predict(draws, human_rules=human_rules)
        self.weights = original_weights  # 원복

        # 6. 사용된 task 정보 evidence에 추가 (원본 key + resolved 모두 기록)
        result["evidence"]["task_key"] = task_key_original
        result["evidence"]["task_resolved"] = task_resolved
        result["evidence"]["task_weights"] = blended
        return result

    def predict_regression(self, draws: list, step: int) -> dict:
        """P3: regression_step_N 전용 예측 경로.

        N회 전 당첨번호 각각이 '다음 회차에 재출현할 확률'의 기대값을 모델별로 계산.
        ensemble.predict()와 완전히 분리된 경로 — CNN/GNN/Autoencoder 제외.

        단기(step 2~10):  LSTM 주도 (0.40) + Markov (0.30)
        중기(step 11~50): Markov 주도 (0.35) + Transformer (0.30)
        장기(step 51~200): Markov 주도 (0.40) + Transformer (0.30), LSTM 약화

        Returns:
            {
                "model_exp": {          # 모델별 N회전 번호 재출현 기대값
                    "lstm": 1.24,
                    "xgboost": 1.56,
                    "transformer": 1.31,
                    "markov": 1.18,
                },
                "ensemble_exp": 1.35,  # 가중 앙상블 기대값
                "step_weights": {...},  # 사용된 가중치
                "target_numbers": [...], # N회 전 당첨번호
            }
        """
        if len(draws) < step + 1:
            return {"model_exp": {}, "ensemble_exp": 0.0, "step_weights": {}, "target_numbers": []}

        draws_sorted = sorted(draws, key=lambda x: x["round"])

        # N회 전 당첨번호
        if step < len(draws_sorted):
            target_draw = draws_sorted[-(step + 1)]
        else:
            return {"model_exp": {}, "ensemble_exp": 0.0, "step_weights": {}, "target_numbers": []}
        target_numbers = target_draw.get("numbers", [])

        # step 구간별 가중치 (CNN/GNN/Autoencoder = 0)
        if step <= 10:
            step_weights = {"lstm": 0.40, "xgboost": 0.15, "cnn": 0.00,
                            "transformer": 0.15, "gnn": 0.00, "markov": 0.30, "autoencoder": 0.00}
        elif step <= 50:
            step_weights = {"lstm": 0.20, "xgboost": 0.15, "cnn": 0.00,
                            "transformer": 0.30, "gnn": 0.00, "markov": 0.35, "autoencoder": 0.00}
        else:
            step_weights = {"lstm": 0.10, "xgboost": 0.15, "cnn": 0.00,
                            "transformer": 0.30, "gnn": 0.00, "markov": 0.40, "autoencoder": 0.05}

        # 히스토리: N회 전 이전 데이터만 사용 (데이터 누수 방지)
        history = draws_sorted[:-(step)]

        # 각 모델의 next-draw 확률 → target_numbers 재출현 기대값
        model_exp = {}
        active_models = [m for m, w in step_weights.items() if w > 0]

        # Markov는 predict() 경로와 동일하게 markov.json 에서 읽음
        markov_preds = None
        markov_path = os.path.join(self.save_dir, "markov.json")
        if "markov" in active_models and os.path.exists(markov_path):
            try:
                with open(markov_path, "r") as f:
                    markov_matrix = np.array(json.load(f))
                last_nums = history[-1].get("numbers", []) if history else []
                pred_markov = np.zeros(45)
                for num in last_nums:
                    if 1 <= num <= 45:
                        pred_markov += markov_matrix[num - 1]
                total_m = pred_markov.sum()
                if total_m > 0:
                    pred_markov /= total_m
                else:
                    pred_markov = np.ones(45) / 45.0
                markov_preds = {n: float(pred_markov[n - 1]) for n in range(1, 46)}
            except Exception as e:
                pass  # fallback to uniform below

        for name in active_models:
            try:
                if name == "markov":
                    preds = markov_preds or {n: 1/45 for n in range(1, 46)}
                else:
                    model = self.models[name]
                    preds = model.predict(history)
                # model_exp = Σ P(number i ∈ next draw) for i in target_numbers
                exp_val = sum(float(preds.get(n, 1/45)) for n in target_numbers if 1 <= n <= 45)
                model_exp[name] = round(exp_val, 4)
            except Exception as e:
                model_exp[name] = round(len(target_numbers) / 45 * 6, 4)  # 기대값 fallback

        # 가중 앙상블 기대값
        total_w = sum(step_weights.get(m, 0) for m in model_exp)
        if total_w > 0:
            ensemble_exp = sum(model_exp[m] * step_weights.get(m, 0) for m in model_exp) / total_w
        else:
            ensemble_exp = sum(model_exp.values()) / len(model_exp) if model_exp else 0.0

        return {
            "model_exp":      model_exp,
            "ensemble_exp":   round(ensemble_exp, 4),
            "step_weights":   {k: v for k, v in step_weights.items() if v > 0},
            "target_numbers": target_numbers,
        }

    def predict_top5(
        self,
        draws: list,
        n_top: int = 5,
        n_bootstrap: int = 50,
        consensus_k: int = 4,
        human_rules=None,
    ) -> dict:
        """P4: Consensus + Bootstrap CI Gating으로 Top N 선출.

        Args:
            draws        : 회차 데이터 리스트
            n_top        : 선출할 번호 수 (기본 5)
            n_bootstrap  : 부트스트랩 반복 횟수 (기본 50)
            consensus_k  : 동의 모델 최소 수 (기본 4/7)
            human_rules  : 전문가 룰 (hard filter)

        Returns dict:
            top_numbers  : list of dicts — 선출된 번호들
            fallback_used: bool — consensus 통과 < n_top 시 True
            method       : str — "consensus+ci_bootstrap"
            full_probs   : dict — 전체 45개 확률
            xai_contributions: dict — P0 XAI 기여도
        """
        # Step 1 — 기본 예측
        result = self.predict_with_task(draws, task="recommend_top", human_rules=human_rules)
        final_probs   = result["probabilities"]           # {n: prob}
        contributions = result["model_contributions"]     # {model: {n: prob}}
        task_weights  = result["evidence"]["task_weights"] # {model: weight}
        xai           = result.get("xai_contributions", {})

        # Step 2 — Bootstrap CI (가중치 지터링, 모델 재호출 없음)
        bootstrap_all = []  # 50개의 {n: normalized_prob} 딕셔너리
        np.random.seed(42)  # 재현성
        for _ in range(n_bootstrap):
            # 각 가중치에 가우시안 노이즈 추가
            jitter = {
                m: max(0.0, w + np.random.normal(0, 0.05))
                for m, w in task_weights.items()
            }
            total = sum(jitter.values()) or 1.0
            jitter = {m: v / total for m, v in jitter.items()}

            boot = {}
            for n in range(1, 46):
                p = sum(
                    contributions.get(m, {}).get(n, 0) * jitter.get(m, 0)
                    for m in jitter
                )
                boot[n] = p

            # 정규화
            total_p = sum(boot.values()) or 1.0
            boot = {n: v / total_p for n, v in boot.items()}
            bootstrap_all.append(boot)

        # CI: 2.5th ~ 97.5th 백분위수
        ci = {}
        lo_idx = max(0, int(n_bootstrap * 0.025))
        hi_idx = min(n_bootstrap - 1, int(n_bootstrap * 0.975))
        for n in range(1, 46):
            vals = sorted(b[n] for b in bootstrap_all)
            ci[n] = {"lower": vals[lo_idx], "upper": vals[hi_idx]}

        # Step 3 — Consensus count
        consensus_count = {n: 0 for n in range(1, 46)}
        for m, m_probs in contributions.items():
            if not m_probs:
                continue
            model_top10 = sorted(m_probs, key=lambda x: m_probs[x], reverse=True)[:10]
            for n in model_top10:
                if isinstance(n, int) and 1 <= n <= 45:
                    consensus_count[n] += 1

        # Step 4 — Gate & Select
        # 전체 확률 기준 Top 10 후보
        candidates = sorted(range(1, 46), key=lambda n: final_probs.get(n, 0), reverse=True)[:10]

        # consensus gate 통과
        gated = [n for n in candidates if consensus_count[n] >= consensus_k]
        # CI lower bound 기준 정렬
        gated.sort(key=lambda n: ci[n]["lower"], reverse=True)

        selected = gated[:n_top]
        fallback_used = len(selected) < n_top

        if fallback_used:
            remaining = [n for n in candidates if n not in selected]
            remaining.sort(key=lambda n: ci[n]["lower"], reverse=True)
            selected.extend(remaining[: n_top - len(selected)])

        # Step 5 — 결과 조립
        rank_map = {
            n: i + 1
            for i, n in enumerate(sorted(range(1, 46), key=lambda x: final_probs.get(x, 0), reverse=True))
        }

        top_numbers = []
        for n in selected:
            cc  = consensus_count[n]
            cil = ci[n]["lower"]
            ciu = ci[n]["upper"]

            if cc >= 5 and cil > 0.018:
                conf_level = "high"
            elif cc >= 4:
                conf_level = "medium"
            else:
                conf_level = "low"

            top_numbers.append({
                "number":          n,
                "prob":            round(final_probs.get(n, 0), 6),
                "rank":            rank_map[n],
                "ci_lower":        round(cil, 6),
                "ci_upper":        round(ciu, 6),
                "consensus_count": cc,
                "confidence_level":conf_level,
                "low_confidence":  conf_level == "low",
            })

        return {
            "top_numbers":         top_numbers,
            "fallback_used":       fallback_used,
            "method":              "consensus+ci_bootstrap",
            "n_bootstrap":         n_bootstrap,
            "consensus_threshold": consensus_k,
            "full_probs":          final_probs,
            "xai_contributions":   xai,
            "evidence":            result["evidence"],
            "contributions":       contributions,  # model_contributions for filter/regression analysis
        }

    def predict_exclusion_with_veto(
        self,
        draws: list,
        n_exclude: int = 10,
        gnn_veto_percentile: float = 80.0,
        human_rules=None,
    ) -> dict:
        """P5: 제외수 10개 선출 with GNN veto rule.

        GNN이 강한 동반출현 신호를 보내는 번호(상위 20%)는 제외 후보에서 제거.
        동반출현이 활발한 번호는 출현 가능성이 높으므로 제외 리스트에 넣는 것이 위험.

        Args:
            draws               : 회차 데이터 리스트
            n_exclude           : 선출할 제외수 수 (기본 10)
            gnn_veto_percentile : GNN 상위 몇 % 이상을 veto 대상으로 볼지 (기본 80 → 상위 20%)
            human_rules         : 전문가 룰 (hard filter)

        Returns dict:
            exclusions   : list of dicts (number, prob, rank, gnn_veto)
            vetoed_count : int — veto로 제외된 번호 수
            method       : "inverse_score+gnn_veto"
        """
        # 1. exclude task 예측
        result = self.predict_with_task(draws, task="exclude", human_rules=human_rules)
        final_probs_excl = result["probabilities"]
        contributions    = result["model_contributions"]

        # 2. GNN co-occurrence 강도 (raw GNN 확률)
        gnn_probs = contributions.get("gnn", {})
        if gnn_probs:
            gnn_values = [float(v) for v in gnn_probs.values() if v is not None]
            threshold_val = float(np.percentile(gnn_values, gnn_veto_percentile)) if gnn_values else 0.0
            gnn_strong = {n for n, p in gnn_probs.items()
                          if isinstance(n, int) and float(p) >= threshold_val}
        else:
            gnn_strong = set()

        # 3. 제외수 후보: 확률 오름차순 (낮을수록 제외 1순위)
        sorted_excl = sorted(range(1, 46), key=lambda n: final_probs_excl.get(n, 0))

        # 4. veto 적용
        selected = []
        vetoed_pool = []
        for n in sorted_excl:
            if n in gnn_strong:
                vetoed_pool.append(n)   # veto — 일단 보류
            else:
                selected.append(n)
            if len(selected) >= n_exclude:
                break

        # 5. 부족하면 vetoed_pool에서 채움 (low_confidence 플래그)
        if len(selected) < n_exclude:
            selected.extend(vetoed_pool[: n_exclude - len(selected)])

        # 6. 결과 조립
        exclusions = []
        for i, n in enumerate(selected[:n_exclude]):
            exclusions.append({
                "number":   n,
                "prob":     round(final_probs_excl.get(n, 0), 6),
                "rank":     i + 1,
                "gnn_veto": n in gnn_strong,   # True = GNN이 동반출현 강하다고 봄
            })

        return {
            "exclusions":          exclusions,
            "vetoed_count":        sum(1 for e in exclusions if e["gnn_veto"]),
            "method":              "inverse_score+gnn_veto",
            "gnn_veto_percentile": gnn_veto_percentile,
            "gnn_strong_count":    len(gnn_strong),
            "base_probs":          final_probs_excl,
            "evidence":            result["evidence"],
        }

    # ── P7: 메타러너 부트스트랩 + 학습 + 상태조회 ───────────────────────────
    def bootstrap_meta_log(
        self,
        draws:      list,
        stride:     int = 10,
        max_rounds: int = 300,
        warmup:     int = 50,
    ) -> dict:
        """
        역대 이력(draws)으로 메타러너 학습 데이터를 생성한다.

        stride 회차마다 Rolling inference → meta_log.jsonl 에 기록.
        이미 충분한 로그가 있으면 추가 생성 없이 현황만 반환.

        Returns:
            {added, skipped, total_log_rounds, already_sufficient}
        """
        status = self.meta_learner.status()
        if status["ready"]:
            print(f"  [MetaLearner] 이미 충분한 로그 ({status['log_rounds']}회차) — 부트스트랩 건너뜀")
            return {
                "added":             0,
                "skipped":           0,
                "total_log_rounds":  status["log_rounds"],
                "already_sufficient": True,
            }

        result = self.meta_learner.bootstrap_meta_log(
            draws      = draws,
            ensemble_obj = self,
            stride     = stride,
            max_rounds = max_rounds,
            warmup     = warmup,
        )
        result["already_sufficient"] = False
        return result

    def train_meta_learner(self, draws: list = None, force_bootstrap: bool = False) -> dict:
        """
        메타러너 학습 파이프라인.

        1. 로그 데이터 부족 시 bootstrap_meta_log() 자동 실행 (draws 전달 필요)
        2. LightGBM 또는 LogisticRegression 학습
        3. 학습된 모델 저장

        Returns:
            {success, n_rounds, method, feature_importance, ...}
        """
        status = self.meta_learner.status()

        # 부트스트랩 필요 여부 확인
        if not status["ready"] or force_bootstrap:
            if draws is not None:
                print(f"  [MetaLearner] 로그 부족 ({status['log_rounds']}/{status['min_required']}) → 부트스트랩 실행")
                boot_result = self.bootstrap_meta_log(draws)
                print(f"  [MetaLearner] 부트스트랩: {boot_result['added']}개 추가")
            else:
                return {
                    "success": False,
                    "error":   f"로그 부족 ({status['log_rounds']}/{status['min_required']}) — draws 전달 필요",
                    "log_rounds": status["log_rounds"],
                }

        # 학습 실행
        train_result = self.meta_learner.train()
        if train_result.get("success"):
            self._meta_loaded = True  # 다음 predict에서 재로드 불필요
            print(
                f"  [MetaLearner] 학습 완료: {train_result['n_rounds']}회차 "
                f"/ {train_result['method']}"
            )
            imp = train_result.get("feature_importance", {})
            if imp:
                sorted_imp = sorted(imp.items(), key=lambda x: x[1], reverse=True)
                print(f"  [MetaLearner] 모델 중요도: {sorted_imp}")
        return train_result

    def meta_learner_status(self) -> dict:
        """메타러너 현황 및 feature_importance 조회"""
        status = self.meta_learner.status()
        if self.meta_learner.meta_model is not None:
            status["feature_importance"] = self.meta_learner.get_feature_importance()
        status["meta_alpha"] = self.meta_alpha
        return status

    @staticmethod
    def get_task_for_filter(filter_key: str) -> str:
        """filter_key → sub-task명 반환. 매핑 없으면 'filter_count_attr' 기본값."""
        return FILTER_KEY_TO_TASK.get(filter_key, "filter_count_attr")


class CombinationGenerator:
    @staticmethod
    def generate(prediction: dict, filter_settings: dict, n_combinations: int = 10) -> list:
        probs = prediction.get("probabilities", {})
        if not probs: return []
        nums, p_vals = list(probs.keys()), list(probs.values())
        
        total_p = sum(p_vals)
        p_vals = [p / total_p for p in p_vals] if total_p > 0 else [1/45]*45
        
        prob_norm = {n: p for n, p in zip(nums, p_vals)}

        results = []
        attempts = 0
        min_sum = filter_settings.get("sum_range", {}).get("min", 21)
        max_sum = filter_settings.get("sum_range", {}).get("max", 255)

        while len(results) < n_combinations and attempts < 10000:
            attempts += 1
            combo = sorted(np.random.choice(nums, 6, replace=False, p=p_vals).tolist())
            combo = [int(x) for x in combo]
            if min_sum <= sum(combo) <= max_sum:
                score = round(sum(prob_norm.get(n, 0) for n in combo), 4)
                results.append({
                    "rank": len(results) + 1,
                    "numbers": combo,
                    "score": score,
                    "type": "ai_recommended"
                })
        return results
