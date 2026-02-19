"""1D-CNN 모델 - 연속 회차 패턴의 지역적 특징 추출 기반 번호 예측.

Input: (batch, seq_len=30, features=57) → transpose → (batch, 57, 30)
Output: (batch, 45) - 각 번호의 출현 확률

Conv1d 필터로 인접 회차 묶음(kernel=3)의 국소 패턴을 탐지하고,
Global Max Pooling으로 가장 강한 신호를 추출하여 번호 확률을 예측한다.
"""

import os
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader

import config
from .lstm_model import LottoSequenceDataset
from .focal_loss import FocalLoss  # [New]


# ──────────────────────────────────────────────
#  Model
# ──────────────────────────────────────────────
class LottoCNN(nn.Module):
    """1D Convolutional Neural Network 로또 번호 예측 모델.

    Input: (batch, seq_len=30, features=57)
    Output: (batch, 45) - 각 번호 출현 확률
    """

    def __init__(
        self,
        input_dim: int = config.CNN_INPUT_DIM,
        seq_len: int = config.CNN_SEQ_LEN,
        filters_1: int = config.CNN_FILTERS_1,
        filters_2: int = config.CNN_FILTERS_2,
        kernel_size: int = config.CNN_KERNEL_SIZE,
        dropout: float = config.CNN_DROPOUT,
    ):
        super().__init__()

        # Conv1d 레이어 (채널: input_dim → filters_1 → filters_2)
        # padding='same' 효과: padding = (kernel_size - 1) // 2
        pad = (kernel_size - 1) // 2

        self.conv_block1 = nn.Sequential(
            nn.Conv1d(input_dim, filters_1, kernel_size=kernel_size, padding=pad),
            nn.BatchNorm1d(filters_1),
            nn.ReLU(),
        )

        self.conv_block2 = nn.Sequential(
            nn.Conv1d(filters_1, filters_2, kernel_size=kernel_size, padding=pad),
            nn.BatchNorm1d(filters_2),
            nn.ReLU(),
        )

        # Global Max Pooling → (batch, filters_2)
        self.global_max_pool = nn.AdaptiveMaxPool1d(1)

        # 출력 레이어 (Sigmoid 제거)
        self.fc = nn.Sequential(
            nn.Linear(filters_2, filters_2 // 2),  # 128 → 64
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(filters_2 // 2, 45),
        )

    def forward(self, x):
        """
        Args:
            x: (batch, seq_len=30, features=57)
        Returns:
            output: (batch, 45) - 각 번호 출현 확률
        """
        # Conv1d는 (batch, channels, length) 형식이 필요
        # (batch, seq_len, features) → (batch, features, seq_len)
        x = x.transpose(1, 2)  # (batch, 57, 30)

        # Convolutional blocks
        x = self.conv_block1(x)  # (batch, 64, 30)
        x = self.conv_block2(x)  # (batch, 128, 30)

        # Global Max Pooling: 가장 강한 패턴 신호 추출
        x = self.global_max_pool(x)  # (batch, 128, 1)
        x = x.squeeze(-1)  # (batch, 128)

        # 번호별 확률 예측
        output = self.fc(x)  # (batch, 45)

        return output

    def get_feature_maps(self, x):
        """Conv 레이어의 Feature Map을 반환한다 (XAI용).

        Args:
            x: (batch, seq_len=30, features=57)
        Returns:
            dict with conv1 and conv2 feature maps
        """
        x = x.transpose(1, 2)

        conv1_out = self.conv_block1(x)  # (batch, 64, 30)
        conv2_out = self.conv_block2(conv1_out)  # (batch, 128, 30)

        return {
            "conv1": conv1_out.detach(),
            "conv2": conv2_out.detach(),
        }


# ──────────────────────────────────────────────
#  Trainer
# ──────────────────────────────────────────────
class CNNTrainer:
    """CNN 학습 관리자.

    LSTMTrainer와 동일한 인터페이스를 제공한다.
    """

    def __init__(self, device: str = "auto"):
        if device == "auto":
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        else:
            self.device = torch.device(device)

        self.model = None
        self.best_loss = float("inf")

    def train(self, draws: list) -> dict:
        """전체 학습 실행.

        Args:
            draws: round 내림차순 (최신→과거)

        Returns:
            학습 결과 dict
        """
        # 데이터셋 생성 (LSTM과 동일한 LottoSequenceDataset 재활용)
        dataset = LottoSequenceDataset(draws, seq_len=config.CNN_SEQ_LEN)

        if len(dataset) < 100:
            return {"success": False, "error": "학습 데이터 부족 (최소 100 시퀀스 필요)"}

        # 학습/검증 분할 (최근 15%를 검증셋)
        val_size = max(int(len(dataset) * 0.15), 20)
        train_size = len(dataset) - val_size

        train_dataset = torch.utils.data.Subset(dataset, range(train_size))
        val_dataset = torch.utils.data.Subset(dataset, range(train_size, len(dataset)))

        train_loader = DataLoader(
            train_dataset, batch_size=config.CNN_BATCH_SIZE, shuffle=True
        )
        val_loader = DataLoader(
            val_dataset, batch_size=config.CNN_BATCH_SIZE, shuffle=False
        )

        # 모델 초기화
        self.model = LottoCNN().to(self.device)

        # [Upgrade] Focal Loss 적용
        criterion = FocalLoss(
            gamma=config.LSTM_FOCAL_GAMMA,
            alpha=config.LSTM_FOCAL_ALPHA,
            pos_weight=torch.full([45], config.LSTM_POS_WEIGHT, device=self.device)
        )

        optimizer = torch.optim.Adam(
            self.model.parameters(),
            lr=config.CNN_LR,
            weight_decay=config.CNN_WEIGHT_DECAY,
        )

        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
            optimizer, T_max=config.CNN_EPOCHS
        )

        # 학습 루프
        best_val_loss = float("inf")
        patience_counter = 0
        history = {"train_loss": [], "val_loss": []}

        for epoch in range(config.CNN_EPOCHS):
            # Train
            self.model.train()
            train_loss = 0.0
            for X_batch, y_batch in train_loader:
                X_batch = X_batch.to(self.device)
                y_batch = y_batch.to(self.device)

                optimizer.zero_grad()
                output = self.model(X_batch)
                loss = criterion(output, y_batch)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=1.0)
                optimizer.step()
                train_loss += loss.item()

            train_loss /= len(train_loader)

            # Validate
            self.model.eval()
            val_loss = 0.0
            with torch.no_grad():
                for X_batch, y_batch in val_loader:
                    X_batch = X_batch.to(self.device)
                    y_batch = y_batch.to(self.device)
                    output = self.model(X_batch)
                    loss = criterion(output, y_batch)
                    val_loss += loss.item()

            val_loss /= len(val_loader)
            scheduler.step()

            history["train_loss"].append(train_loss)
            history["val_loss"].append(val_loss)

            # Early stopping
            if val_loss < best_val_loss:
                best_val_loss = val_loss
                patience_counter = 0
                self._save_model()
            else:
                patience_counter += 1

            if patience_counter >= config.CNN_EARLY_STOP_PATIENCE:
                print(f"  [CNN] Early stopping at epoch {epoch + 1}")
                break

            if (epoch + 1) % 10 == 0:
                print(
                    f"  [CNN] Epoch {epoch + 1:3d} | "
                    f"Train Loss: {train_loss:.6f} | "
                    f"Val Loss: {val_loss:.6f} | "
                    f"LR: {scheduler.get_last_lr()[0]:.6f}"
                )

        # 최적 모델 로드
        self._load_model()

        return {
            "success": True,
            "epochs_trained": len(history["train_loss"]),
            "best_val_loss": best_val_loss,
            "final_train_loss": history["train_loss"][-1],
        }

    def predict(self, draws: list) -> dict:
        """현재 시점에서 다음 회차 각 번호 확률 예측.

        Args:
            draws: round 내림차순 (최신→과거), 최소 seq_len개 필요

        Returns:
            {번호(1~45): 확률(float)}
        """
        if self.model is None:
            self._load_model()

        if self.model is None:
            return {n: config.RANDOM_BASELINE for n in range(1, 46)}

        self.model.eval()

        # 최근 seq_len개 회차로 입력 생성
        recent = draws[: config.CNN_SEQ_LEN]
        if len(recent) < config.CNN_SEQ_LEN:
            while len(recent) < config.CNN_SEQ_LEN:
                recent.append({"numbers": []})

        # 시간순 정렬 (과거→최신)
        sorted_recent = list(reversed(recent))

        ds = LottoSequenceDataset.__new__(LottoSequenceDataset)
        ds.seq_len = config.CNN_SEQ_LEN
        features = []
        for d in sorted_recent:
            features.append(ds._draw_to_features(d))

        x = torch.FloatTensor(np.array([features])).to(self.device)

        with torch.no_grad():
            logits = self.model(x)
            probs = torch.sigmoid(logits)  # [Fix] Logits -> Probabilities

        probs_np = probs.cpu().numpy()[0]

        result = {}
        for i in range(45):
            result[i + 1] = float(probs_np[i])

        return result

    def _save_model(self):
        """모델 저장."""
        path = os.path.join(config.MODEL_DIR, "cnn_model.pt")
        if self.model:
            torch.save(self.model.state_dict(), path)

    def _load_model(self):
        """저장된 모델 로드."""
        path = os.path.join(config.MODEL_DIR, "cnn_model.pt")
        if os.path.exists(path):
            self.model = LottoCNN().to(self.device)
            self.model.load_state_dict(
                torch.load(path, map_location=self.device, weights_only=True)
            )
            self.model.eval()
