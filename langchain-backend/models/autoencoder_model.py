"""Autoencoder 모델 - 당첨 패턴의 복원 오차(Reconstruction Error)를 계산하여 비정상 쏠림 현상(제외수)을 판별합니다."""

import os
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset
import config

class LottoAutoencoder(nn.Module):
    def __init__(self):
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Conv2d(1, 16, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2, padding=1),
            nn.Conv2d(16, 32, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2)
        )
        self.decoder = nn.Sequential(
            nn.ConvTranspose2d(32, 16, 2, stride=2), nn.ReLU(),
            nn.ConvTranspose2d(16, 1, 3, stride=2, padding=1, output_padding=0), nn.Sigmoid()
        )

    def forward(self, x): return self.decoder(self.encoder(x))

class AutoencoderTrainer:
    def __init__(self, device: str = "auto"):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu") if device == "auto" else torch.device(device)
        self.model = None

    def train(self, draws: list):
        # 최신 데이터를 제외한 평범한 과거 데이터로 정상 패턴 학습
        grids = []
        for draw in draws[10:]: 
            grid = np.zeros((1, 7, 7), dtype=np.float32)
            for num in draw.get("numbers", []):
                if 1 <= num <= 45: grid[0, (num-1)//7, (num-1)%7] = 1.0
            grids.append(grid)
            
        self.model = LottoAutoencoder().to(self.device)
        optimizer = torch.optim.Adam(self.model.parameters(), lr=0.001)
        criterion = nn.MSELoss()
        
        self.model.train()
        for _ in range(20):
            for batch in DataLoader(torch.FloatTensor(np.array(grids)), batch_size=32, shuffle=True):
                batch = batch.to(self.device)
                optimizer.zero_grad()
                loss = criterion(self.model(batch), batch)
                loss.backward()
                optimizer.step()
        
        path = os.path.join(config.MODEL_DIR, "autoencoder_model.pt")
        torch.save(self.model.state_dict(), path)
        return {"success": True}

    def predict_exclusions(self, draws: list, threshold: float = 0.6) -> dict:
        """최근 3회차 누적 패턴을 분석해 복원 오차가 임계치(threshold)를 넘는 번호를 추출"""
        path = os.path.join(config.MODEL_DIR, "autoencoder_model.pt")
        if not os.path.exists(path): return {}
        
        self.model = LottoAutoencoder().to(self.device)
        self.model.load_state_dict(torch.load(path, map_location=self.device, weights_only=True))
        self.model.eval()

        combined_grid = np.zeros((1, 1, 7, 7), dtype=np.float32)
        for draw in draws[:3]:
            for num in draw.get("numbers", []):
                if 1 <= num <= 45: combined_grid[0, 0, (num-1)//7, (num-1)%7] += 1.0
        if combined_grid.max() > 0: combined_grid /= combined_grid.max()

        x = torch.FloatTensor(combined_grid).to(self.device)
        with torch.no_grad():
            reconstructed = self.model(x)
        
        error_map = (x - reconstructed).cpu().numpy()[0, 0]
        exclusions = {}
        for num in range(1, 46):
            if error_map[(num-1)//7, (num-1)%7] > threshold:
                exclusions[num] = float(error_map[(num-1)//7, (num-1)%7])
        return exclusions
