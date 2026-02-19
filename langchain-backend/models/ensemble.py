"""Ensemble Model - Transformer + LSTM + CNN + XGBoost + Markov 5중 앙상블.

5개 모델의 예측을 가중 합산하여 최종 확률을 산출하고,
Monte Carlo 샘플링으로 최적 번호 조합을 생성한다.
"""

import os
import json
import numpy as np
import random
from datetime import datetime

import config
from .transformer_model import TransformerTrainer
from .lstm_model import LSTMTrainer
from .cnn_model import CNNTrainer
from .xgboost_model import LottoXGBoost
from .markov_model import MarkovLottoModel


class LottoEnsemble:
    """5개 모델의 예측을 결합하여 최종 확률 산출."""

    def __init__(self):
        self.transformer = TransformerTrainer()
        self.lstm = LSTMTrainer()
        self.cnn = CNNTrainer()
        self.xgb = LottoXGBoost()
        self.markov = MarkovLottoModel()

        # 가중치 (초기값)
        self.weights = config.ENSEMBLE_INITIAL_WEIGHTS.copy()
        self._load_weights()

    def train_all(self, draws: list):
        """5개 모델 순차 학습 (빠른 모델부터)."""
        print("=" * 60)
        print("[START] Starting 5-Model Ensemble Training...")
        print("=" * 60)

        results = {}
        total_models = 5

        # 1. Markov (가장 빠름 - 통계 기반)
        print(f"\n[1/{total_models}] Training Markov Model...")
        try:
            self.markov.train(draws)
            results["markov"] = {"success": True}
            print("  [OK] Markov training complete")
        except Exception as e:
            results["markov"] = {"success": False, "error": str(e)}
            print(f"  [FAIL] Markov training failed: {e}")

        # 2. XGBoost (빠름 - 트리 기반)
        print(f"\n[2/{total_models}] Training XGBoost Model...")
        try:
            xgb_result = self.xgb.train(draws)
            results["xgboost"] = xgb_result
            print("  [OK] XGBoost training complete")
        except Exception as e:
            results["xgboost"] = {"success": False, "error": str(e)}
            print(f"  [FAIL] XGBoost training failed: {e}")

        # 3. CNN (중간 속도 - 1D Conv)
        print(f"\n[3/{total_models}] Training 1D-CNN Model...")
        try:
            cnn_result = self.cnn.train(draws)
            results["cnn"] = cnn_result
            if cnn_result.get("success"):
                print(f"  [OK] CNN training complete (Epochs: {cnn_result['epochs_trained']}, "
                      f"Val Loss: {cnn_result['best_val_loss']:.6f})")
            else:
                print(f"  [WARN] CNN training failed: {cnn_result.get('error')}")
        except Exception as e:
            results["cnn"] = {"success": False, "error": str(e)}
            print(f"  [FAIL] CNN training failed: {e}")

        # 4. LSTM (느림 - BiLSTM + Attention)
        print(f"\n[4/{total_models}] Training LSTM Model...")
        try:
            lstm_result = self.lstm.train(draws)
            results["lstm"] = lstm_result
            if lstm_result.get("success"):
                print(f"  [OK] LSTM training complete (Epochs: {lstm_result['epochs_trained']}, "
                      f"Val Loss: {lstm_result['best_val_loss']:.6f})")
            else:
                print(f"  [WARN] LSTM training failed: {lstm_result.get('error')}")
        except Exception as e:
            results["lstm"] = {"success": False, "error": str(e)}
            print(f"  [FAIL] LSTM training failed: {e}")

        # 5. Transformer (가장 느림 - Self-Attention)
        print(f"\n[5/{total_models}] Training Transformer Model...")
        try:
            trans_result = self.transformer.train(draws)
            results["transformer"] = trans_result
            if trans_result.get("success"):
                print(f"  [OK] Transformer training complete (Epochs: {trans_result['epochs_trained']}, "
                      f"Val Loss: {trans_result['best_val_loss']:.6f})")
            else:
                print(f"  [WARN] Transformer training failed: {trans_result.get('error')}")
        except Exception as e:
            results["transformer"] = {"success": False, "error": str(e)}
            print(f"  [FAIL] Transformer training failed: {e}")

        # [Upgrade] Dynamic Weighting via Validation Loss (Stacking-Lite)
        # 검증 손실(Validation Loss)이 낮은 모델에게 더 높은 가중치를 부여
        print(f"\n[Stacking] Adjusting weights based on validation loss...")
        dl_losses = {}
        if results.get("cnn", {}).get("success"):
            dl_losses["cnn"] = results["cnn"]["best_val_loss"]
        if results.get("lstm", {}).get("success"):
            dl_losses["lstm"] = results["lstm"]["best_val_loss"]
        if results.get("transformer", {}).get("success"):
            dl_losses["transformer"] = results["transformer"]["best_val_loss"]

        if dl_losses:
            # Softmax-like weighting based on negative loss
            # Loss가 낮을수록 가중치가 커짐
            # 예: Loss [0.5, 0.4, 0.3] -> Exp(-Loss) -> Weights
            
            # 1. 역수 변환 (Loss가 0에 가까우면 너무 커지므로 exp(-loss) 사용)
            exp_inv_losses = {k: np.exp(-v * 5.0) for k, v in dl_losses.items()} # *5.0은 scaling factor (변별력 강화)
            total_exp = sum(exp_inv_losses.values())
            
            # 2. DL 모델 간의 상대적 중요도 재분배
            # 현재 DL 모델들의 총 가중치 합 계산
            current_dl_weight_sum = sum(self.weights.get(k, 0.2) for k in dl_losses.keys())
            
            if total_exp > 0:
                for name, val in exp_inv_losses.items():
                    # DL 그룹 내에서 비중 재설정
                    self.weights[name] = current_dl_weight_sum * (val / total_exp)
                    print(f"  -> Model {name}: Val Loss {dl_losses[name]:.4f} => Adjusted Weight {self.weights[name]:.4f}")

        # 가중치 저장
        self._save_weights()

        # 결과 요약
        success_count = sum(1 for r in results.values() if r.get("success", False))
        print("\n" + "=" * 60)
        print(f"[DONE] Ensemble Training Complete: {success_count}/{total_models} models succeeded")
        print("=" * 60)

        return {"success": success_count > 0, "model_results": results}

    def predict(self, draws: list, custom_rules: list = None) -> dict:
        """최종 5모델 앙상블 예측 실행."""
        # 각 모델 예측
        model_predictions = {}

        try:
            model_predictions["transformer"] = self.transformer.predict(draws)
        except Exception as e:
            print(f"  [WARN] Transformer predict failed: {e}")
            model_predictions["transformer"] = {n: config.RANDOM_BASELINE for n in range(1, 46)}

        try:
            model_predictions["lstm"] = self.lstm.predict(draws)
        except Exception as e:
            print(f"  [WARN] LSTM predict failed: {e}")
            model_predictions["lstm"] = {n: config.RANDOM_BASELINE for n in range(1, 46)}

        try:
            model_predictions["cnn"] = self.cnn.predict(draws)
        except Exception as e:
            print(f"  [WARN] CNN predict failed: {e}")
            model_predictions["cnn"] = {n: config.RANDOM_BASELINE for n in range(1, 46)}

        try:
            model_predictions["xgboost"] = self.xgb.predict(draws)
        except Exception as e:
            print(f"  [WARN] XGBoost predict failed: {e}")
            model_predictions["xgboost"] = {n: config.RANDOM_BASELINE for n in range(1, 46)}

        try:
            model_predictions["markov"] = self.markov.predict(draws)
        except Exception as e:
            print(f"  [WARN] Markov predict failed: {e}")
            model_predictions["markov"] = {n: config.RANDOM_BASELINE for n in range(1, 46)}

        # 5개 모델 가중 합산
        final_probs = {}
        for n in range(1, 46):
            score = 0.0
            for model_name, model_probs in model_predictions.items():
                weight = self.weights.get(model_name, 0.0)
                prob = model_probs.get(n, 0.0)
                score += prob * weight
            final_probs[n] = score

        # 랭킹 산출
        ranked = sorted(final_probs.items(), key=lambda x: x[1], reverse=True)
        top_10 = [n for n, p in ranked[:10]]
        bottom_10 = [n for n, p in ranked[-10:]]

        # XAI 데이터 준비 — 5개 모델 기여도
        contributions = model_predictions.copy()

        # XGBoost 중요 피처
        xgb_features = {}
        for n in top_10:
            xgb_features[n] = self.xgb.get_top_features(n)

        return {
            "probabilities": final_probs,
            "recommended": top_10,
            "excluded": bottom_10,
            "model_contributions": contributions,
            "xgb_feature_importance": xgb_features,
            "weights_used": self.weights,
        }

    def get_model_status(self) -> dict:
        """각 모델의 로드 상태를 반환한다 (/health 엔드포인트용)."""
        return {
            "transformer": self.transformer.model is not None
                           or os.path.exists(os.path.join(config.MODEL_DIR, "transformer_model.pt")),
            "lstm": self.lstm.model is not None
                    or os.path.exists(os.path.join(config.MODEL_DIR, "lstm_model.pt")),
            "cnn": self.cnn.model is not None
                   or os.path.exists(os.path.join(config.MODEL_DIR, "cnn_model.pt")),
            "xgboost": os.path.exists(os.path.join(config.MODEL_DIR, "xgboost_models.pkl")),
            "markov": os.path.exists(os.path.join(config.MODEL_DIR, "markov_matrices.json")),
        }

    def update_weights(self, actual_numbers: list, predictions: dict):
        """지난 예측 결과에 따라 가중치 동적 조정.

        각 모델의 예측 정확도를 측정하여 가중치를 업데이트한다.
        """
        if not actual_numbers or not predictions:
            return

        actual_set = set(actual_numbers)
        model_scores = {}

        for model_name, model_probs in predictions.get("model_contributions", {}).items():
            if not model_probs:
                continue

            # 각 모델이 추천한 상위 10개 번호 중 정답 비율
            sorted_nums = sorted(model_probs.items(), key=lambda x: x[1], reverse=True)
            top_10_nums = set(int(n) for n, _ in sorted_nums[:10])
            hit_count = len(top_10_nums & actual_set)
            model_scores[model_name] = hit_count / 6.0  # 6개 중 몇 개 맞았는지

        if not model_scores:
            return

        # 가중치 블렌딩 (기존 가중치 * blend + 새 점수 * (1-blend))
        blend = config.ENSEMBLE_BLEND_RATIO
        total_score = sum(model_scores.values())

        if total_score > 0:
            for model_name in self.weights:
                if model_name in model_scores:
                    new_weight = model_scores[model_name] / total_score
                    self.weights[model_name] = (
                        self.weights[model_name] * blend + new_weight * (1 - blend)
                    )

        # 최소 가중치 보장
        for model_name in self.weights:
            self.weights[model_name] = max(
                self.weights[model_name], config.ENSEMBLE_MIN_WEIGHT
            )

        # 정규화 (합 = 1.0)
        total = sum(self.weights.values())
        if total > 0:
            self.weights = {k: v / total for k, v in self.weights.items()}

        self._save_weights()

    def _save_weights(self):
        path = os.path.join(config.MODEL_DIR, "ensemble_weights.json")
        with open(path, "w") as f:
            json.dump(self.weights, f, indent=2)

    def _load_weights(self):
        path = os.path.join(config.MODEL_DIR, "ensemble_weights.json")
        if os.path.exists(path):
            with open(path, "r") as f:
                loaded = json.load(f)
            # 5개 모델 키가 모두 있는지 확인
            expected_keys = {"transformer", "lstm", "cnn", "xgboost", "markov"}
            if set(loaded.keys()) == expected_keys:
                self.weights = loaded
            else:
                # 이전 3모델 가중치 파일인 경우 새 초기값 사용
                print("  [WARN] Existing weight file is not 5-model format. Using initial weights.")
                self.weights = config.ENSEMBLE_INITIAL_WEIGHTS.copy()


class CombinationGenerator:
    """확률 기반 번호 조합 생성기."""

    @staticmethod
    def generate(
        ensemble_result: dict,
        filter_settings: dict = None,
        n_combinations: int = 5,
    ) -> list:
        """Monte Carlo 방식으로 조합 생성.

        Args:
            ensemble_result: LottoEnsemble.predict() 결과
            filter_settings: 필터 조건 (sum_range, odd_count 등)
            n_combinations: 생성할 조합 수

        Returns:
            list of {"rank": int, "numbers": list, "score": float}
        """
        probs = ensemble_result["probabilities"]
        numbers = list(probs.keys())
        weights = list(probs.values())

        # 가중치를 양수로 보정
        min_w = min(weights)
        if min_w < 0:
            weights = [w - min_w + 0.0001 for w in weights]

        total_w = sum(weights)
        norm_weights = [w / total_w for w in weights]

        combinations = []
        max_attempts = n_combinations * 100  # 필터 적용 시 더 많은 시도 필요
        attempts = 0

        while len(combinations) < n_combinations and attempts < max_attempts:
            attempts += 1

            # 중복 없이 6개 추출
            comb = np.random.choice(
                numbers, size=6, replace=False, p=norm_weights
            )
            comb_sorted = sorted(int(n) for n in comb)

            # 필터 적용
            if filter_settings and not CombinationGenerator._passes_filter(
                comb_sorted, filter_settings
            ):
                continue

            # 중복 조합 방지
            if comb_sorted in [c["numbers"] for c in combinations]:
                continue

            # 조합 점수 계산 (구성 번호의 평균 확률)
            score = sum(probs.get(n, 0) for n in comb_sorted) / 6.0

            combinations.append({
                "rank": len(combinations) + 1,
                "numbers": comb_sorted,
                "score": score,
            })

        # 점수 기준 내림차순 정렬 후 순위 재할당
        combinations.sort(key=lambda x: x["score"], reverse=True)
        for i, c in enumerate(combinations):
            c["rank"] = i + 1

        return combinations

    @staticmethod
    def _passes_filter(numbers: list, settings: dict) -> bool:
        """조합이 필터 조건을 통과하는지 검사."""
        # 총합 필터
        if "sum_range" in settings:
            s = sum(numbers)
            sr = settings["sum_range"]
            if s < sr.get("min", 0) or s > sr.get("max", 270):
                return False

        # 홀수 개수 필터
        if "odd_count" in settings:
            odd = sum(1 for n in numbers if n % 2 == 1)
            oc = settings["odd_count"]
            if odd < oc.get("min", 0) or odd > oc.get("max", 6):
                return False

        # 저번호 (1~22) 개수 필터
        if "low_count" in settings:
            low = sum(1 for n in numbers if n <= 22)
            lc = settings["low_count"]
            if low < lc.get("min", 0) or low > lc.get("max", 6):
                return False

        # AC값 필터
        if "ac_value" in settings:
            diffs = set()
            for i in range(len(numbers)):
                for j in range(i + 1, len(numbers)):
                    diffs.add(abs(numbers[i] - numbers[j]))
            ac = len(diffs) - (len(numbers) - 1)
            ac_s = settings["ac_value"]
            if ac < ac_s.get("min", 0) or ac > ac_s.get("max", 10):
                return False

        # 연번 필터
        if "consecutive" in settings:
            consec = sum(
                1 for i in range(len(numbers) - 1)
                if numbers[i + 1] - numbers[i] == 1
            )
            if consec > settings["consecutive"].get("max", 6):
                return False

        return True
