"""Ensemble Model - 5중 앙상블 합산 및 Autoencoder 기반 이상 탐지 거부권(Veto) 적용. XAI 근거 텍스트를 함께 생성합니다."""

import os
import json
import numpy as np
import random
import config

from .transformer_model import TransformerTrainer
from .lstm_model import LSTMTrainer
from .cnn_model import CNNTrainer
from .xgboost_model import LottoXGBoost
from .markov_model import MarkovLottoModel
from .autoencoder_model import AutoencoderTrainer  # [추가]

class LottoEnsemble:
    def __init__(self):
        self.transformer = TransformerTrainer()
        self.lstm = LSTMTrainer()
        self.cnn = CNNTrainer()
        self.xgb = LottoXGBoost()
        self.markov = MarkovLottoModel()
        self.autoencoder = AutoencoderTrainer() # [추가]
        self.weights = config.ENSEMBLE_INITIAL_WEIGHTS.copy()
        self._load_weights()

    def train_all(self, draws: list):
        print("=" * 60 + "\n[START] Deep Analysis Ensemble Training...\n" + "=" * 60)
        results = {}
        
        try: self.markov.train(draws); results["markov"] = {"success": True}
        except Exception as e: results["markov"] = {"success": False, "error": str(e)}
        
        try: results["xgboost"] = self.xgb.train(draws)
        except Exception as e: results["xgboost"] = {"success": False, "error": str(e)}
        
        try: results["cnn"] = self.cnn.train(draws)
        except Exception as e: results["cnn"] = {"success": False, "error": str(e)}
        
        try: results["lstm"] = self.lstm.train(draws)
        except Exception as e: results["lstm"] = {"success": False, "error": str(e)}
        
        try: results["transformer"] = self.transformer.train(draws)
        except Exception as e: results["transformer"] = {"success": False, "error": str(e)}

        try: results["autoencoder"] = self.autoencoder.train(draws)
        except Exception as e: results["autoencoder"] = {"success": False, "error": str(e)}

        return {"success": True, "model_results": results}

    def predict(self, draws: list, custom_rules: list = None) -> dict:
        model_predictions = {
            "transformer": self.transformer.predict(draws),
            "lstm": self.lstm.predict(draws),
            "cnn": self.cnn.predict(draws),
            "xgboost": self.xgb.predict(draws),
            "markov": self.markov.predict(draws)
        }
        
        # [핵심] Autoencoder 이상 패턴 제외수 추출 (거부권)
        ae_exclusions = self.autoencoder.predict_exclusions(draws, threshold=0.6)

        final_probs = {}
        evidence_dict = {}

        for n in range(1, 46):
            score = 0.0
            reasons = []
            
            # 1. 기본 가중 합산
            for m_name, probs in model_predictions.items():
                prob = probs.get(n, 0.0)
                score += prob * self.weights.get(m_name, 0.0)
                if prob > 0.7: reasons.append(f"{m_name.upper()} 모델에서 높은 출현 확률({prob*100:.1f}%) 감지")
                
            # 2. 룰 기반 거부권 (Autoencoder Veto)
            if n in ae_exclusions:
                error_val = ae_exclusions[n]
                score *= 0.1 # 확률을 10%로 강제 삭감 (강력한 페널티)
                reasons.append(f"[경고] Autoencoder 복원 오차 {error_val:.2f} 감지. 비정상적 과열 패턴으로 강제 페널티 부여됨.")
            
            # 3. XGBoost 피처 근거 추가 (Top 10에만 디테일 부여)
            top_features = self.xgb.get_top_features(n)
            if top_features:
                f_name = top_features[0][0]
                reasons.append(f"통계 지표 '{f_name}' 수치 변화가 긍정적 시그널로 작용.")

            final_probs[n] = score
            evidence_dict[n] = " | ".join(reasons) if reasons else "평범한 확률 분포를 보임."

        ranked = sorted(final_probs.items(), key=lambda x: x[1], reverse=True)
        top_10 = [n for n, p in ranked[:10]]
        bottom_10 = [n for n, p in ranked[-10:]]

        return {
            "probabilities": final_probs,
            "recommended": top_10,
            "excluded": bottom_10,
            "model_contributions": model_predictions,
            "evidence": evidence_dict, # XAI 모달용 텍스트 근거 데이터 추가
            "weights_used": self.weights,
        }
        
    def get_model_status(self) -> dict: return {}
    def update_weights(self, actual_numbers: list, predictions: dict): pass
    def _save_weights(self): pass
    def _load_weights(self): pass

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
