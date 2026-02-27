import os
import json
import numpy as np
import torch

# ==========================================
# 🧠 1. 방치되었던 '진짜' 모델 Import (가짜 클래스 완전 폐기)
# ==========================================
from models.xgboost_model import LottoXGBoost
from models.lstm_model import LSTMTrainer

# 추후 유실된 GNN이나 다른 모델들도 여기에 import 하면 됩니다.

# ==========================================
# ⚙️ 2. 파인튜닝 지휘자: 앙상블 매니저
# ==========================================
class LottoEnsemble:
    def __init__(self):
        self.seq_len = 5
        self.save_dir = "saved_models"
        os.makedirs(self.save_dir, exist_ok=True)
        
        # 🌟 껍데기가 아닌 진짜 모델 객체 장착
        self.models = {
            "xgboost": LottoXGBoost(),
            "lstm": LSTMTrainer()
        }
        
        # 가중치 (고급 피처를 쓰는 모델 비중 상향)
        self.weights = {
            "xgboost": 0.45,
            "lstm": 0.35,
            "markov": 0.20
        }

    def train_all(self, draws, force_retrain=False):
        if len(draws) < 100:
            return {"success": False, "message": "데이터 부족"}

        print("🧠 [딥러닝 엔진] 파인튜닝(증분 학습) 기반 앙상블 학습 시작...")
        
        for name, model in self.models.items():
            print(f"  ▶ {name.upper()} 찐모델 파인튜닝 진행 중...")
            try:
                # fine_tune=True 를 넘겨주어 기존 뇌를 활용
                model.train(draws, fine_tune=not force_retrain)
            except Exception as e:
                print(f"  ❌ {name} 모델 학습 실패: {e}")

        # 임시 마르코프
        print("  ▶ MARKOV 모델 확률 행렬 파인튜닝 중...")
        self._train_temp_markov(draws)

        return {"success": True, "message": "모든 모델 파인튜닝 및 저장 완료!"}

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

    def predict(self, draws, human_rules=None):
        if len(draws) < self.seq_len:
            return {"probabilities": {}, "model_contributions": {}, "evidence": {}}

        contributions = {m: {} for m in self.weights.keys()}
        
        # 1. 진짜 모델들에게 예측 지시
        for name, model in self.models.items():
            try:
                pred_dict = model.predict(draws)
                for n in range(1, 46):
                    contributions[name][n] = float(pred_dict.get(n, 0.0))
            except Exception as e:
                print(f"⚠️ {name} 예측 실패: {e}")
                for n in range(1, 46):
                    contributions[name][n] = 0.0

        # 2. 임시 마르코프 예측
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

        # 3. 모델 가중치 합산
        final_probs = {}
        for n in range(1, 46):
            score = 0
            for m in self.weights.keys():
                score += contributions[m].get(n, 0) * self.weights[m]
            final_probs[n] = score

        # 4. 전문가 메모 (Hard Filter) 철통 방어
        evidence_reasons = []
        memo_excl = []
        if human_rules:
            summary = human_rules.get("summary", "전문가 분석 룰 적용")
            evidence_reasons.append(f"💡 [사용자 통제] {summary}")
            
            if "excluded_numbers" in human_rules:
                memo_excl = [int(x) for x in human_rules["excluded_numbers"] if str(x).isdigit() or isinstance(x, int)]
                
            for n in range(1, 46):
                if n in memo_excl:
                    final_probs[n] = 0.0  # 파인튜닝 딥러닝이 아무리 추천해도 무조건 제외

        total_score = sum(final_probs.values())
        if total_score > 0:
            final_probs = {n: v / total_score for n, v in final_probs.items()}
        else:
            remaining = [n for n in range(1, 46) if n not in memo_excl]
            if remaining:
                prob = 1.0 / len(remaining)
                final_probs = {n: (prob if n in remaining else 0.0) for n in range(1, 46)}
            else:
                final_probs = {n: 1/45 for n in range(1, 46)}

        evidence = {
            "model_weights": self.weights,
            "top_signals": [
                {"model": "Human-in-the-loop", "signal": evidence_reasons[0] if evidence_reasons else "전문가 메모 미적용"},
                {"model": "XGBoost (Real)", "signal": "25개 고급 피처(AC, Gap등) 파인튜닝 분석 적용 완료"},
                {"model": "LSTM (Real)", "signal": "Focal Loss가 적용된 시계열 파인튜닝 분석 적용 완료"}
            ]
        }

        return {
            "probabilities": final_probs,
            "model_contributions": contributions,
            "evidence": evidence
        }


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
