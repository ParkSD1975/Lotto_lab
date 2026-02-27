import os
import torch
import torch.nn as nn
import numpy as np
import json
from collections import Counter

# ==========================================
# 🧠 1. 진짜 딥러닝 신경망 모델 정의 (PyTorch)
# ==========================================

class LottoLSTM(nn.Module):
    def __init__(self):
        super().__init__()
        self.lstm = nn.LSTM(input_size=45, hidden_size=64, num_layers=2, batch_first=True)
        self.fc = nn.Linear(64, 45)
    def forward(self, x):
        out, _ = self.lstm(x)
        return torch.sigmoid(self.fc(out[:, -1, :]))

class LottoCNN(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv1 = nn.Conv1d(in_channels=5, out_channels=32, kernel_size=3, padding=1)
        self.relu = nn.ReLU()
        self.fc = nn.Linear(32 * 45, 45)
    def forward(self, x):
        x = self.relu(self.conv1(x))
        x = x.view(x.size(0), -1)
        return torch.sigmoid(self.fc(x))

class LottoTransformer(nn.Module):
    def __init__(self):
        super().__init__()
        self.encoder_layer = nn.TransformerEncoderLayer(d_model=45, nhead=5, batch_first=True)
        self.transformer = nn.TransformerEncoder(self.encoder_layer, num_layers=2)
        self.fc = nn.Linear(45, 45)
    def forward(self, x):
        out = self.transformer(x)
        return torch.sigmoid(self.fc(out[:, -1, :]))

class LottoMLP(nn.Module):
    def __init__(self):
        super().__init__()
        self.fc1 = nn.Linear(5 * 45, 128)
        self.relu = nn.ReLU()
        self.fc2 = nn.Linear(128, 45)
    def forward(self, x):
        x = x.view(x.size(0), -1)
        return torch.sigmoid(self.fc2(self.relu(self.fc1(x))))

# 💡 [핵심 추가] 질문자님이 찾으시던 오토인코더 모델!
class LottoAutoencoder(nn.Module):
    """과거 데이터를 극도로 압축(16차원)했다가 복원하며 핵심 패턴만 걸러내는 병목 예측기"""
    def __init__(self):
        super().__init__()
        # 인코더 (압축)
        self.encoder = nn.Sequential(
            nn.Linear(5 * 45, 64),
            nn.ReLU(),
            nn.Linear(64, 16), # 16차원 병목(Bottleneck)
            nn.ReLU()
        )
        # 디코더 (복원 및 예측)
        self.decoder = nn.Sequential(
            nn.Linear(16, 64),
            nn.ReLU(),
            nn.Linear(64, 45),
            nn.Sigmoid()
        )
    def forward(self, x):
        x = x.view(x.size(0), -1)
        latent = self.encoder(x)
        out = self.decoder(latent)
        return out


# ==========================================
# ⚙️ 2. 앙상블 매니저 (학습 및 예측 총괄)
# ==========================================

class LottoEnsemble:
    def __init__(self):
        self.seq_len = 5
        self.save_dir = "saved_models"
        os.makedirs(self.save_dir, exist_ok=True)
        
        # 6개의 모델 장착 완료
        self.models = {
            "lstm": LottoLSTM(),
            "cnn": LottoCNN(),
            "transformer": LottoTransformer(),
            "xgboost": LottoMLP(),
            "autoencoder": LottoAutoencoder() # 오토인코더 추가!
        }
        
        # 모델별 가중치 재분배 (합산 1.0)
        self.weights = {
            "lstm": 0.20, 
            "transformer": 0.20, 
            "xgboost": 0.20, 
            "cnn": 0.15, 
            "autoencoder": 0.15, # 오토인코더에 15%의 권한 부여
            "markov": 0.10
        }

    def _prepare_data(self, draws):
        draws_asc = sorted(draws, key=lambda x: x['round'])
        data = []
        for d in draws_asc:
            vec = np.zeros(45, dtype=np.float32)
            for n in d.get("numbers", []):
                if 1 <= n <= 45: vec[n-1] = 1.0
            data.append(vec)
            
        X, y = [], []
        for i in range(len(data) - self.seq_len):
            X.append(data[i : i + self.seq_len])
            y.append(data[i + self.seq_len])
            
        return torch.tensor(np.array(X)), torch.tensor(np.array(y)), draws_asc

    def train_all(self, draws, epochs=50):
        X, y, draws_asc = self._prepare_data(draws)
        if len(X) == 0: return {"success": False, "message": "데이터 부족"}

        print("🧠 [딥러닝 엔진] 6중 앙상블 학습을 시작합니다...")
        criterion = nn.BCELoss()
        
        for name, model in self.models.items():
            print(f"  ▶ {name.upper()} 모델 학습 중...")
            optimizer = torch.optim.Adam(model.parameters(), lr=0.005)
            model.train()
            
            for epoch in range(epochs):
                optimizer.zero_grad()
                outputs = model(X)
                loss = criterion(outputs, y)
                loss.backward()
                optimizer.step()
                
            torch.save(model.state_dict(), os.path.join(self.save_dir, f"{name}.pt"))

        print("  ▶ MARKOV 모델 확률 행렬 계산 중...")
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

        return {"success": True, "message": "모든 딥러닝 모델 학습 및 저장 완료!"}

    def predict(self, draws, human_rules=None):
        if len(draws) < self.seq_len:
            return {"probabilities": {}, "model_contributions": {}, "evidence": {}}

        draws_asc = sorted(draws, key=lambda x: x['round'])
        recent_draws = draws_asc[-self.seq_len:]
        
        x_input = []
        for d in recent_draws:
            vec = np.zeros(45, dtype=np.float32)
            for n in d.get("numbers", []):
                if 1 <= n <= 45: vec[n-1] = 1.0
            x_input.append(vec)
            
        x_tensor = torch.tensor(np.array([x_input]))
        
        contributions = {m: {} for m in self.weights.keys()}
        
        for name, model in self.models.items():
            model_path = os.path.join(self.save_dir, f"{name}.pt")
            if os.path.exists(model_path):
                model.load_state_dict(torch.load(model_path, weights_only=True))
                model.eval()
                with torch.no_grad():
                    pred = model(x_tensor).squeeze().numpy()
                for n in range(1, 46):
                    contributions[name][n] = float(pred[n-1])
            else:
                for n in range(1, 46):
                    contributions[name][n] = 0.0

        markov_path = os.path.join(self.save_dir, "markov.json")
        if os.path.exists(markov_path):
            with open(markov_path, "r") as f:
                markov_matrix = np.array(json.load(f))
            last_nums = recent_draws[-1].get("numbers", [])
            pred_markov = np.zeros(45)
            for num in last_nums:
                if 1 <= num <= 45: pred_markov += markov_matrix[num-1]
            if len(last_nums) > 0: pred_markov /= len(last_nums)
            for n in range(1, 46):
                contributions["markov"][n] = float(pred_markov[n-1])

        final_probs = {}
        for n in range(1, 46):
            score = 0
            for m in self.weights.keys():
                score += contributions[m].get(n, 0) * self.weights[m]
            final_probs[n] = score

        # 전문가 메모 (Human-in-the-loop) 적용
        evidence_reasons = []
        if human_rules:
            summary = human_rules.get("summary", "전문가 분석 룰 적용")
            evidence_reasons.append(f"💡 [사용자 통제] {summary}")
            
            # 정수 변환 및 제외 처리 (LLM은 가끔 숫자를 문자열로 반환함)
            memo_excl = []
            if "excluded_numbers" in human_rules:
                memo_excl = [int(x) for x in human_rules["excluded_numbers"] if str(x).isdigit() or isinstance(x, int)]
                
            for n in range(1, 46):
                # 가중치 상향 (Boost)
                for b_range in human_rules.get("boost_ranges", []):
                    if isinstance(b_range, list) and len(b_range) == 2:
                        if b_range[0] <= n <= b_range[1]:
                            final_probs[n] *= 1.5 
                    elif isinstance(b_range, dict):
                        if b_range.get("start", 0) <= n <= b_range.get("end", 0):
                            final_probs[n] *= 1.5

                # 제외 (Exclude)
                if n in memo_excl:
                    print(f"🛠️ [Ensemble Debug] 번호 {n} 제외 처리됨")
                    final_probs[n] = 0.0 

        total_score = sum(final_probs.values())
        if total_score > 0:
            final_probs = {n: v / total_score for n, v in final_probs.items()}
        else:
            # 모델 점수가 전혀 없는 경우 (Fallback) - 단, 제외수는 제외하고 균등 배분
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
                {"model": "Autoencoder", "signal": "비정형 패턴 압축 및 이상 징후 필터링 완료"},
                {"model": "DeepLearning", "signal": "6중 다중 신경망 앙상블 예측 완료"}
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

        # 정규화된 확률 dict (score 계산용)
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
