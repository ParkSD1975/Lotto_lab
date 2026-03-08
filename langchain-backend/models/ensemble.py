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

class LottoEnsemble:
    def __init__(self):
        self.seq_len = 5
        self.save_dir = "saved_models"
        os.makedirs(self.save_dir, exist_ok=True)
        
        # 메타 러닝 가중치 영구 저장 파일
        self.weights_file = os.path.join(self.save_dir, "ensemble_weights.json")
        
        # 🌟 딥러닝/머신러닝 진짜 모델 객체화
        self.models = {
            "xgboost": LottoXGBoost(),
            "lstm": LSTMTrainer(),
            "cnn": CNNTrainer(),
            "transformer": TransformerTrainer(),
            "autoencoder": AutoencoderTrainer(),
            "gnn": GNNTrainer()
        }
        
        # 기본 뼈대 가중치 (초기값) - 합계 1.0
        self.default_weights = {
            "xgboost": 0.25,       # 0.30 → 0.25 (autoencoder 편입으로 조정)
            "lstm": 0.20,
            "cnn": 0.10,
            "transformer": 0.15,
            "gnn": 0.15,
            "markov": 0.10,
            "autoencoder": 0.05    # 0.0 → 0.05 (복원 오차 기반 예측 기여도 반영)
        }
        
        # ★ 시스템 시작 시 진화된 가중치가 있다면 불러오기
        self.weights = self._load_meta_weights()

    def _load_meta_weights(self):
        """저장된 메타 가중치(학습된 비중)를 불러옵니다."""
        base_weights = self.default_weights.copy()
        if os.path.exists(self.weights_file):
            try:
                with open(self.weights_file, "r") as f:
                    w = json.load(f)
                    # 기존 가중치에 새로운 모델이 추가된 경우 대응 (e.g. autoencoder)
                    for k, v in w.items():
                        if k in base_weights:
                            # 이전 버전에서 0으로 저장된 경우 기본값 사용 (autoencoder 0→0.05 마이그레이션)
                            base_weights[k] = v if v > 0 else base_weights[k]
                    print(f"🧠 [Meta-Learning] 진화된 동적 가중치 로드 완료: {base_weights}")
                    return base_weights
            except Exception:
                pass
        return base_weights

    def _update_meta_weights(self, draws):
        """[핵심] 최신 당첨 번호로 모델별 모의고사를 실시하여 메타 가중치를 스스로 재조정합니다."""
        print("🧠 [Meta-Learning] 최신 당첨 번호로 모델별 모의고사를 실시합니다...")
        try:
            draws_asc = sorted(draws, key=lambda x: x['round'])
            latest_draw = draws_asc[-1]       # 최신 정답 데이터
            history = draws_asc[:-1]          # 모의고사용 과거 데이터
            actual_numbers = set(latest_draw["numbers"])

            # 🛠️ [교정 완료] 리셋하지 않고 현재까지 진화한 가중치(self.weights)를 기준으로 보너스 누적
            scores = {k: v for k, v in self.weights.items()}

            for name, model in self.models.items():
                try:
                    # 각 모델별로 최신 회차 예측 시뮬레이션
                    preds = model.predict(history)
                    top_10 = sorted(preds, key=preds.get, reverse=True)[:10]
                    
                    # 실제 당첨 번호와 비교하여 적중 개수 파악
                    hits = len(set(top_10) & actual_numbers)
                    
                    # 적중 1개당 누적 가중치에 5%(0.05)의 보너스 비중 부여
                    bonus = hits * 0.05
                    scores[name] += bonus
                    print(f"    - [{name.upper()}] 모의고사 적중: {hits}개 (가중치 보상 +{bonus:.2f})")
                except Exception as e:
                    print(f"    - [{name.upper()}] 평가 보류 (사전 학습 부족): {e}")
                finally:
                    # [학습 단계] 메모리 즉시 반환 (OOM 방지)
                    if hasattr(model, 'model'):
                        del model.model
                        model.model = None
                    if name == "xgboost" and hasattr(model, 'models'):
                        del model.models
                        model.models = {}
                    torch.cuda.empty_cache()
                    gc.collect()

            # 마르코프 연쇄에는 소폭의 고정 보너스 유지
            scores["markov"] += 0.02 

            # 부여된 보너스 합산 후 다시 100%(1.0) 비율로 정규화
            total = sum(scores.values())
            new_weights = {k: round(v / total, 3) for k, v in scores.items()}
            
            self.weights = new_weights
            # 진화된 가중치 영구 저장
            with open(self.weights_file, "w") as f:
                json.dump(self.weights, f)
            print(f"✅ [Meta-Learning] 새로운 메타 가중치 확정 및 저장 완료!")

        except Exception as e:
            print(f"⚠️ [Meta-Learning] 가중치 조정 중 오류 발생 (기존값 유지): {e}")

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

        evidence = {
            "model_weights": self.weights,
            "top_signals": [
                {"model": "Human-in-the-loop", "signal": evidence_reasons[0] if evidence_reasons else "전문가 메모 미적용"},
                {"model": "Ensemble", "signal": "메타 러닝을 통한 동적 가중치 앙상블 적용 완료"}
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
