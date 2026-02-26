"""2D-CNN 모델 - 로또 용지(7x7 그리드) 공간 패턴 및 주변수 분석 기반 번호 출현 확률 예측.
시간의 흐름(최근 N회차)을 채널(Channel)로 쌓고, 3x3 Conv2d 필터가 '주변수' 패턴을 추출합니다.
"""

import os
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset
import config
from .focal_loss import FocalLoss

# ── 1. 2D 전용 데이터셋 ──
class LottoGridSequenceDataset(Dataset):
    def __init__(self, draws: list, seq_len: int = config.CNN_SEQ_LEN):
        self.seq_len = seq_len
        self.X, self.y = self._build_sequences(draws)

    def _build_sequences(self, draws):
        sorted_draws = list(reversed(draws))
        sequences, labels = [], []
        for i in range(len(sorted_draws) - self.seq_len):
            seq_draws = sorted_draws[i : i + self.seq_len]
            target_draw = sorted_draws[i + self.seq_len]
            
            # (seq_len, 7, 7) 형태의 2D 그리드 생성
            grid_seq = np.zeros((self.seq_len, 7, 7), dtype=np.float32)
            for t, d in enumerate(seq_draws):
                for num in d.get("numbers", []):
                    if 1 <= num <= 45:
                        row, col = (num - 1) // 7, (num - 1) % 7
                        grid_seq[t, row, col] = 1.0
            sequences.append(grid_seq)
            
            label = np.zeros(45, dtype=np.float32)
            for num in target_draw.get("numbers", []):
                if 1 <= num <= 45:
                    label[num - 1] = 1.0
            labels.append(label)
        return np.array(sequences, dtype=np.float32), np.array(labels, dtype=np.float32)

    def __len__(self): return len(self.X)
    def __getitem__(self, idx): return torch.FloatTensor(self.X[idx]), torch.FloatTensor(self.y[idx])

# ── 2. 2D-CNN 모델 ──
class LottoCNN2D(nn.Module):
    def __init__(self, seq_len: int = config.CNN_SEQ_LEN, filters_1: int = config.CNN_FILTERS_1, filters_2: int = config.CNN_FILTERS_2, dropout: float = config.CNN_DROPOUT):
        super().__init__()
        # 3x3 커널로 상하좌우 주변수 탐색
        self.conv_block1 = nn.Sequential(
            nn.Conv2d(seq_len, filters_1, kernel_size=3, padding=1),
            nn.BatchNorm2d(filters_1),
            nn.ReLU()
        )
        self.conv_block2 = nn.Sequential(
            nn.Conv2d(filters_1, filters_2, kernel_size=3, padding=1),
            nn.BatchNorm2d(filters_2),
            nn.ReLU()
        )
        self.global_max_pool = nn.AdaptiveMaxPool2d(1)
        self.fc = nn.Sequential(
            nn.Linear(filters_2, filters_2 // 2),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(filters_2 // 2, 45)
        )

    def forward(self, x):
        x = self.conv_block1(x) # (batch, 64, 7, 7)
        x = self.conv_block2(x) # (batch, 128, 7, 7)
        x = self.global_max_pool(x) # (batch, 128, 1, 1)
        x = x.view(x.size(0), -1)
        return self.fc(x)

# ── 3. Trainer ──
class CNNTrainer:
    def __init__(self, device: str = "auto"):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu") if device == "auto" else torch.device(device)
        self.model = None

    def train(self, draws: list) -> dict:
        dataset = LottoGridSequenceDataset(draws, seq_len=config.CNN_SEQ_LEN)
        if len(dataset) < 100: return {"success": False, "error": "데이터 부족"}
        
        train_loader = DataLoader(dataset, batch_size=config.CNN_BATCH_SIZE, shuffle=True)
        self.model = LottoCNN2D().to(self.device)
        criterion = FocalLoss(gamma=config.LSTM_FOCAL_GAMMA, alpha=config.LSTM_FOCAL_ALPHA, pos_weight=torch.full([45], config.LSTM_POS_WEIGHT, device=self.device))
        optimizer = torch.optim.Adam(self.model.parameters(), lr=config.CNN_LR)

        best_loss = float("inf")
        self.model.train()
        for epoch in range(config.CNN_EPOCHS):
            epoch_loss = 0.0
            for X_batch, y_batch in train_loader:
                X_batch, y_batch = X_batch.to(self.device), y_batch.to(self.device)
                optimizer.zero_grad()
                loss = criterion(self.model(X_batch), y_batch)
                loss.backward()
                optimizer.step()
                epoch_loss += loss.item()
            if epoch_loss < best_loss:
                best_loss = epoch_loss
                self._save_model()
        
        self._load_model()
        return {"success": True, "epochs_trained": config.CNN_EPOCHS, "best_val_loss": best_loss}

    def predict(self, draws: list) -> dict:
        if self.model is None: self._load_model()
        if self.model is None: return {n: 0.0 for n in range(1, 46)}
        
        recent = list(reversed(draws[:config.CNN_SEQ_LEN]))
        grid_seq = np.zeros((config.CNN_SEQ_LEN, 7, 7), dtype=np.float32)
        for t, d in enumerate(recent):
            for num in d.get("numbers", []):
                if 1 <= num <= 45:
                    row, col = (num - 1) // 7, (num - 1) % 7
                    grid_seq[t, row, col] = 1.0

        x = torch.FloatTensor(np.array([grid_seq])).to(self.device)
        self.model.eval()
        with torch.no_grad():
            probs = torch.sigmoid(self.model(x)).cpu().numpy()[0]
        return {i + 1: float(probs[i]) for i in range(45)}

    def _save_model(self):
        if self.model: torch.save(self.model.state_dict(), os.path.join(config.MODEL_DIR, "cnn_model.pt"))
    def _load_model(self):
        path = os.path.join(config.MODEL_DIR, "cnn_model.pt")
        if os.path.exists(path):
            self.model = LottoCNN2D().to(self.device)
            self.model.load_state_dict(torch.load(path, map_location=self.device, weights_only=True))
