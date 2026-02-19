"""LSTM 모델 - 시계열 번호 출현 확률 예측.

Input: (batch, seq_len=30, features=65)
Output: (batch, 45) - 각 번호의 출현 확률
"""

import os
import math  # [New] for cyclical features
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader

import config
from .focal_loss import FocalLoss  # [New]

# ──────────────────────────────────────────────
#  Dataset
# ──────────────────────────────────────────────
class LottoSequenceDataset(Dataset):
    """로또 시퀀스 데이터셋.

    draws: round 내림차순 (최신→과거).
    각 샘플은 seq_len 회차의 피처 벡터 → 다음 회차 번호 레이블.
    """

    def __init__(self, draws: list, seq_len: int = 30):
        self.seq_len = seq_len
        self.X, self.y = self._build_sequences(draws)

    def _build_sequences(self, draws):
        """시퀀스-레이블 쌍을 생성한다."""
        # draws를 시간순 정렬 (과거→최신)
        sorted_draws = list(reversed(draws))
        sequences = []
        labels = []

        for i in range(len(sorted_draws) - self.seq_len):
            seq_draws = sorted_draws[i : i + self.seq_len]
            target_draw = sorted_draws[i + self.seq_len]

            # 피처 벡터 생성
            seq_features = []
            for d in seq_draws:
                feat = self._draw_to_features(d)
                seq_features.append(feat)

            # 레이블: 타겟 회차 번호 출현 여부 (45차원 binary)
            label = np.zeros(45, dtype=np.float32)
            for n in target_draw.get("numbers", []):
                if 1 <= n <= 45:
                    label[n - 1] = 1.0

            sequences.append(np.array(seq_features, dtype=np.float32))
            labels.append(label)

        return (
            np.array(sequences, dtype=np.float32),
            np.array(labels, dtype=np.float32),
        )

    def _draw_to_features(self, draw):
        """한 회차 데이터를 65차원 피처 벡터로 변환한다."""
        numbers = sorted(draw.get("numbers", []))
        round_num = draw.get("round", 0)

        # 45차원: 번호 출현 여부
        occurrence = np.zeros(45, dtype=np.float32)
        for n in numbers:
            if 1 <= n <= 45:
                occurrence[n - 1] = 1.0

        # 기존 12차원 패턴 피처
        total_sum = sum(numbers) if numbers else 0
        odd_count = sum(1 for n in numbers if n % 2 == 1)
        low_count = sum(1 for n in numbers if n <= 22)
        prime_count = sum(1 for n in numbers if n in config.PRIMES)
        tail_sum = sum(n % 10 for n in numbers)

        # AC값
        ac_value = 0
        if len(numbers) >= 2:
            diffs = set()
            for i in range(len(numbers)):
                for j in range(i + 1, len(numbers)):
                    diffs.add(abs(numbers[i] - numbers[j]))
            ac_value = len(diffs) - (len(numbers) - 1)

        # 연번 쌍 수
        consec_pairs = sum(
            1
            for i in range(len(numbers) - 1)
            if numbers[i + 1] - numbers[i] == 1
        )

        pattern_features = np.array(
            [
                total_sum / 255.0,
                odd_count / 6.0,
                low_count / 6.0,
                ac_value / 10.0,
                consec_pairs / 6.0,
                tail_sum / 45.0,
                prime_count / 6.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
            ],
            dtype=np.float32,
        )

        # [New] 8차원 주파수/주기성 피처 (Cyclical Features)
        # 회차 정보를 주파수 도메인으로 매핑하여 주기적 패턴 학습 유도
        cyclical_features = np.array([
            math.sin(2 * math.pi * round_num / 5.0),
            math.cos(2 * math.pi * round_num / 5.0),
            math.sin(2 * math.pi * round_num / 10.0),
            math.cos(2 * math.pi * round_num / 10.0),
            math.sin(2 * math.pi * round_num / 20.0),
            math.cos(2 * math.pi * round_num / 20.0),
            math.sin(2 * math.pi * round_num / 52.0), # 약 1년 주기
            math.cos(2 * math.pi * round_num / 52.0),
        ], dtype=np.float32)

        return np.concatenate([occurrence, pattern_features, cyclical_features])

    def __len__(self):
        return len(self.X)

    def __getitem__(self, idx):
        return torch.FloatTensor(self.X[idx]), torch.FloatTensor(self.y[idx])


# ──────────────────────────────────────────────
#  Model
# ──────────────────────────────────────────────
class LottoLSTM(nn.Module):
    """Bidirectional LSTM with Attention.

    Input: (batch, seq_len=30, features=65)
    Output: (batch, 45) - Logits (no sigmoid)
    """

    def __init__(
        self,
        input_dim: int = config.LSTM_INPUT_DIM,
        hidden_dim: int = config.LSTM_HIDDEN_DIM,
        num_layers: int = config.LSTM_NUM_LAYERS,
        dropout: float = config.LSTM_DROPOUT,
    ):
        super().__init__()

        self.lstm = nn.LSTM(
            input_size=input_dim,
            hidden_size=hidden_dim,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0,
            bidirectional=True,
        )

        # Attention 메커니즘
        self.attention = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.Tanh(),
            nn.Linear(hidden_dim, 1),
        )

        # 출력 레이어
        self.fc = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, 45),
        )

    def forward(self, x):
        """
        Returns:
            output: (batch, 45) - Logits
            attn_weights: (batch, seq_len)
        """
        lstm_out, _ = self.lstm(x)  # (batch, seq_len, hidden*2)

        # Attention
        attn_scores = self.attention(lstm_out)  # (batch, seq_len, 1)
        attn_weights = torch.softmax(attn_scores, dim=1)

        # Weighted sum
        context = torch.sum(lstm_out * attn_weights, dim=1)  # (batch, hidden*2)

        # Predict
        output = self.fc(context)  # (batch, 45)

        return output, attn_weights.squeeze(-1)


# ──────────────────────────────────────────────
#  Trainer
# ──────────────────────────────────────────────
class LSTMTrainer:
    """LSTM 학습 관리자."""

    def __init__(self, device: str = "auto"):
        if device == "auto":
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        else:
            self.device = torch.device(device)

        self.model = None
        self.best_loss = float("inf")

    def train(self, draws: list) -> dict:
        """전체 학습 실행."""
        # 데이터셋 생성
        dataset = LottoSequenceDataset(draws, seq_len=config.LSTM_SEQ_LEN)

        if len(dataset) < 100:
            return {"success": False, "error": "학습 데이터 부족 (최소 100 시퀀스 필요)"}

        # 학습/검증 분할
        val_size = max(int(len(dataset) * 0.15), 20)
        train_size = len(dataset) - val_size

        train_dataset = torch.utils.data.Subset(dataset, range(train_size))
        val_dataset = torch.utils.data.Subset(dataset, range(train_size, len(dataset)))

        train_loader = DataLoader(
            train_dataset, batch_size=config.LSTM_BATCH_SIZE, shuffle=True
        )
        val_loader = DataLoader(
            val_dataset, batch_size=config.LSTM_BATCH_SIZE, shuffle=False
        )

        # 모델 초기화
        self.model = LottoLSTM().to(self.device)

        # [Upgrade] Focal Loss 적용
        criterion = FocalLoss(
            gamma=config.LSTM_FOCAL_GAMMA,
            alpha=config.LSTM_FOCAL_ALPHA,
            pos_weight=torch.full([45], config.LSTM_POS_WEIGHT, device=self.device)
        )

        optimizer = torch.optim.Adam(
            self.model.parameters(),
            lr=config.LSTM_LR,
            weight_decay=config.LSTM_WEIGHT_DECAY,
        )

        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
            optimizer, T_max=config.LSTM_EPOCHS
        )

        # 학습 루프
        best_val_loss = float("inf")
        patience_counter = 0
        history = {"train_loss": [], "val_loss": []}

        for epoch in range(config.LSTM_EPOCHS):
            # Train
            self.model.train()
            train_loss = 0.0
            for X_batch, y_batch in train_loader:
                X_batch = X_batch.to(self.device)
                y_batch = y_batch.to(self.device)

                optimizer.zero_grad()
                output, _ = self.model(X_batch)
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
                    output, _ = self.model(X_batch)
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

            if patience_counter >= config.LSTM_EARLY_STOP_PATIENCE:
                print(f"  Early stopping at epoch {epoch + 1}")
                break

            if (epoch + 1) % 10 == 0:
                print(
                    f"  Epoch {epoch + 1:3d} | "
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
        """현재 시점에서 다음 회차 각 번호 확률 예측."""
        if self.model is None:
            self._load_model()

        if self.model is None:
            return {n: config.RANDOM_BASELINE for n in range(1, 46)}

        self.model.eval()

        # 최근 seq_len개 회차로 입력 생성
        recent = draws[: config.LSTM_SEQ_LEN]
        if len(recent) < config.LSTM_SEQ_LEN:
            while len(recent) < config.LSTM_SEQ_LEN:
                recent.append({"numbers": []})

        sorted_recent = list(reversed(recent))

        ds = LottoSequenceDataset.__new__(LottoSequenceDataset)
        ds.seq_len = config.LSTM_SEQ_LEN
        features = []
        for d in sorted_recent:
            features.append(ds._draw_to_features(d))

        x = torch.FloatTensor(np.array([features])).to(self.device)

        with torch.no_grad():
            logits, attn_weights = self.model(x)
            probs = torch.sigmoid(logits)  # [Fix] Logits -> Probabilities

        probs_np = probs.cpu().numpy()[0]
        
        result = {}
        for i in range(45):
            result[i + 1] = float(probs_np[i])

        return result

    def get_attention_weights(self, draws: list) -> dict:
        """Attention 가중치를 반환한다 (XAI용)."""
        if self.model is None:
            self._load_model()
        if self.model is None:
            return {}

        self.model.eval()
        recent = draws[: config.LSTM_SEQ_LEN]
        if len(recent) < config.LSTM_SEQ_LEN:
            while len(recent) < config.LSTM_SEQ_LEN:
                recent.append({"numbers": []})

        sorted_recent = list(reversed(recent))
        ds = LottoSequenceDataset.__new__(LottoSequenceDataset)
        ds.seq_len = config.LSTM_SEQ_LEN
        features = []
        for d in sorted_recent:
            features.append(ds._draw_to_features(d))

        x = torch.FloatTensor(np.array([features])).to(self.device)

        with torch.no_grad():
            _, attn_weights = self.model(x)

        attn_np = attn_weights.cpu().numpy()[0]

        result = {}
        for i, d in enumerate(sorted_recent):
            round_num = d.get("round", i)
            result[round_num] = float(attn_np[i])

        return result

    def _save_model(self):
        """모델 저장."""
        path = os.path.join(config.MODEL_DIR, "lstm_model.pt")
        if self.model:
            torch.save(self.model.state_dict(), path)

    def _load_model(self):
        """저장된 모델 로드."""
        path = os.path.join(config.MODEL_DIR, "lstm_model.pt")
        if os.path.exists(path):
            self.model = LottoLSTM().to(self.device)
            self.model.load_state_dict(
                torch.load(path, map_location=self.device, weights_only=True)
            )
            self.model.eval()
