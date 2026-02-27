import os
import json
import numpy as np
import torch
import config

class GNNTrainer:
    def __init__(self):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.save_dir = config.MODEL_DIR
        os.makedirs(self.save_dir, exist_ok=True)
        # 45x45 크기의 동반 출현(Edge) 가중치 행렬
        self.adjacency_matrix = np.zeros((45, 45))

    def train(self, draws: list, fine_tune: bool = True):
        print("  [GNN] 동반 출현(짝꿍) 그래프 네트워크 학습 시작...")
        
        # 파인튜닝(증분 학습) 모드일 경우 기존 그래프 뇌를 불러옴
        if fine_tune:
            path = os.path.join(self.save_dir, "gnn_adjacency.json")
            if os.path.exists(path):
                with open(path, "r") as f:
                    self.adjacency_matrix = np.array(json.load(f))
                print("  [GNN] 기존 그래프 네트워크(.json)를 성공적으로 불러왔습니다.")
            
        # 최신 회차 데이터만 걸러서 그래프 선(Edge)을 더 굵게 만듦
        # (단순화를 위해 전체를 훑지만, 실제 가중치는 누적됨)
        draws_asc = sorted(draws, key=lambda x: x['round'])
        
        for draw in draws_asc:
            nums = draw.get("numbers", [])
            for i in range(len(nums)):
                for j in range(i + 1, len(nums)):
                    n1, n2 = nums[i] - 1, nums[j] - 1
                    if 0 <= n1 < 45 and 0 <= n2 < 45:
                        self.adjacency_matrix[n1][n2] += 1
                        self.adjacency_matrix[n2][n1] += 1 # 양방향 연결

        # 모델 저장
        with open(os.path.join(self.save_dir, "gnn_adjacency.json"), "w") as f:
            json.dump(self.adjacency_matrix.tolist(), f)

    def predict(self, draws: list) -> dict:
        if len(draws) == 0:
            return {n: 1/45 for n in range(1, 46)}
            
        # 최근 3주간 나온 번호들을 '활성화된 노드(Node)'로 간주
        recent_draws = sorted(draws, key=lambda x: x['round'])[-3:]
        active_nodes = set()
        for draw in recent_draws:
            active_nodes.update(draw.get("numbers", []))
            
        gnn_scores = np.zeros(45)
        
        # 활성화된 노드들과 선(Edge)이 가장 굵게 연결된(많이 동반 출현한) 번호들 추천
        for node in active_nodes:
            if 1 <= node <= 45:
                gnn_scores += self.adjacency_matrix[node - 1]
                
        # 자기 자신(이미 나온 번호)은 점수 약간 페널티 (이월수 방지)
        for node in active_nodes:
            if 1 <= node <= 45:
                gnn_scores[node - 1] *= 0.5 
                
        # 점수 정규화
        total_score = np.sum(gnn_scores)
        if total_score > 0:
            gnn_scores = gnn_scores / total_score
        else:
            gnn_scores = np.ones(45) / 45
            
        return {n: float(gnn_scores[n - 1]) for n in range(1, 46)}
