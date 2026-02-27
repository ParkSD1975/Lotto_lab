"""Transformer 모델 - Self-Attention 기반 번호 출현 확률 예측.

Input: (batch, seq_len=30, features=57)
Output: (batch, 45) - 각 번호의 출현 확률

Positional Encoding으로 시퀀스 순서 정보를 주입하고,
Multi-Head Self-Attention으로 회차 간 장기 의존성을 포착한다.
"""

import os
import math
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader

import config
from .lstm_model import LottoSequenceDataset
from .focal_loss import FocalLoss  # [New]


# ──────────────────────────────────────────────
#  Positional Encoding
# ──────────────────────────────────────────────
class PositionalEncoding(nn.Module):
    """사인/코사인 기반 위치 인코딩.

    시퀀스 내 각 회차의 순서 정보를 임베딩에 더해준다.
    """

    def __init__(self, d_model: int, max_len: int = 200, dropout: float = 0.1):
        super().__init__()
        self.dropout = nn.Dropout(p=dropout)

        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(
            torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model)
        )

        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        pe = pe.unsqueeze(0)  # (1, max_len, d_model)

        self.register_buffer("pe", pe)

    def forward(self, x):
        """
        Args:
            x: (batch, seq_len, d_model)
        Returns:
            (batch, seq_len, d_model) with positional encoding added
        """
        x = x + self.pe[:, : x.size(1), :]
        return self.dropout(x)


# ──────────────────────────────────────────────
#  Model
# ──────────────────────────────────────────────
class LottoTransformer(nn.Module):
    """Transformer Encoder 기반 로또 번호 예측 모델.

    Input: (batch, seq_len=30, features=57)
    Output: (batch, 45) - 각 번호 출현 확률
    """

    def __init__(
        self,
        input_dim: int = config.TRANSFORMER_INPUT_DIM,
        d_model: int = config.TRANSFORMER_D_MODEL,
        nhead: int = config.TRANSFORMER_NHEAD,
        num_layers: int = config.TRANSFORMER_NUM_LAYERS,
        dim_feedforward: int = config.TRANSFORMER_DIM_FF,
        dropout: float = config.TRANSFORMER_DROPOUT,
    ):
        super().__init__()

        self.d_model = d_model

        # 입력 임베딩: 57차원 → d_model(128)차원
        self.input_projection = nn.Linear(input_dim, d_model)

        # 위치 인코딩
        self.pos_encoder = PositionalEncoding(d_model, dropout=dropout)

        # Transformer Encoder
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=nhead,
            dim_feedforward=dim_feedforward,
            dropout=dropout,
            batch_first=True,
            activation="gelu",
        )
        self.transformer_encoder = nn.TransformerEncoder(
            encoder_layer, num_layers=num_layers
        )

        # Layer Normalization
        self.layer_norm = nn.LayerNorm(d_model)

        # 출력 레이어
        self.fc = nn.Sequential(
            nn.Linear(d_model, d_model // 2),  # 128 → 64
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(d_model // 2, 45),
        )

        # Attention 저장용 훅
        self._attention_weights = None

    def forward(self, x):
        """
        Args:
            x: (batch, seq_len, input_dim=57)
        Returns:
            output: (batch, 45) - 각 번호 출현 확률
        """
        # 입력 임베딩
        x = self.input_projection(x)  # (batch, seq_len, d_model)
        x = x * math.sqrt(self.d_model)  # 스케일링

        # 위치 인코딩 추가
        x = self.pos_encoder(x)  # (batch, seq_len, d_model)

        # Transformer Encoder 통과
        encoded = self.transformer_encoder(x)  # (batch, seq_len, d_model)

        # Layer Norm
        encoded = self.layer_norm(encoded)

        # 마지막 시점(최신 회차)의 출력 사용
        last_output = encoded[:, -1, :]  # (batch, d_model)

        # 번호별 확률 예측
        output = self.fc(last_output)  # (batch, 45)

        return output

    def get_attention_maps(self, x):
        """Attention 가중치를 추출한다 (XAI용).

        Args:
            x: (batch, seq_len, input_dim=57)
        Returns:
            attention_maps: list of (batch, nhead, seq_len, seq_len) per layer
        """
        attention_maps = []

        # 입력 임베딩
        h = self.input_projection(x) * math.sqrt(self.d_model)
        h = self.pos_encoder(h)

        # 각 레이어를 수동으로 통과하며 attention weight 수집
        for layer in self.transformer_encoder.layers:
            # self_attn은 MultiheadAttention 모듈
            h_normed = layer.norm1(h)
            attn_output, attn_weights = layer.self_attn(
                h_normed, h_normed, h_normed, need_weights=True
            )
            h = h + layer.dropout1(attn_output)

            # Feed-forward
            h_normed2 = layer.norm2(h)
            ff_output = layer.linear2(
                layer.dropout(layer.activation(layer.linear1(h_normed2)))
            )
            h = h + layer.dropout2(ff_output)

            attention_maps.append(attn_weights.detach())

        return attention_maps


# ──────────────────────────────────────────────
#  Trainer
# ──────────────────────────────────────────────
class TransformerTrainer:
    """Transformer 학습 관리자.

    LSTMTrainer와 동일한 인터페이스를 제공한다.
    """

    def __init__(self, device: str = "auto"):
        if device == "auto":
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        else:
            self.device = torch.device(device)

        self.model = None
        self.best_loss = float("inf")

    def train(self, draws: list, fine_tune: bool = True) -> dict:
        """전체 학습 실행.

        Args:
            draws: round 내림차순 (최신→과거)

        Returns:
            학습 결과 dict
        """
        # 데이터셋 생성 (LSTM과 동일한 LottoSequenceDataset 재활용)
        dataset = LottoSequenceDataset(draws, seq_len=config.TRANSFORMER_SEQ_LEN)

        if len(dataset) < 100:
            return {"success": False, "error": "학습 데이터 부족 (최소 100 시퀀스 필요)"}

        # 학습/검증 분할 (최근 15%를 검증셋)
        val_size = max(int(len(dataset) * 0.15), 20)
        train_size = len(dataset) - val_size

        train_dataset = torch.utils.data.Subset(dataset, range(train_size))
        val_dataset = torch.utils.data.Subset(dataset, range(train_size, len(dataset)))

        train_loader = DataLoader(
            train_dataset, batch_size=config.TRANSFORMER_BATCH_SIZE, shuffle=True
        )
        val_loader = DataLoader(
            val_dataset, batch_size=config.TRANSFORMER_BATCH_SIZE, shuffle=False
        )

        # 모델 초기화
        self.model = LottoTransformer().to(self.device)
        
        if fine_tune:
            path = os.path.join(config.MODEL_DIR, "transformer_model.pt")
            if os.path.exists(path):
                self.model.load_state_dict(torch.load(path, map_location=self.device, weights_only=True))
                print("  [Transformer] 기존 뇌(.pt) 가중치를 성공적으로 불러와 파인튜닝을 시작합니다.")
            else:
                print("  [Transformer] 기존 뇌가 없어 초기 상태에서 학습합니다.")

        # [Upgrade] Focal Loss 적용
        criterion = FocalLoss(
            gamma=config.LSTM_FOCAL_GAMMA,
            alpha=config.LSTM_FOCAL_ALPHA,
            pos_weight=torch.full([45], config.LSTM_POS_WEIGHT, device=self.device)
        )

        optimizer = torch.optim.AdamW(
            self.model.parameters(),
            lr=config.TRANSFORMER_LR,
            weight_decay=config.TRANSFORMER_WEIGHT_DECAY,
        )

        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
            optimizer, T_max=config.TRANSFORMER_EPOCHS
        )

        # 학습 루프
        best_val_loss = float("inf")
        patience_counter = 0
        history = {"train_loss": [], "val_loss": []}

        for epoch in range(config.TRANSFORMER_EPOCHS):
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

            if patience_counter >= config.TRANSFORMER_EARLY_STOP_PATIENCE:
                print(f"  [Transformer] Early stopping at epoch {epoch + 1}")
                break

            if (epoch + 1) % 10 == 0:
                print(
                    f"  [Transformer] Epoch {epoch + 1:3d} | "
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
        recent = draws[: config.TRANSFORMER_SEQ_LEN]
        if len(recent) < config.TRANSFORMER_SEQ_LEN:
            while len(recent) < config.TRANSFORMER_SEQ_LEN:
                recent.append({"numbers": []})

        # 시간순 정렬 (과거→최신)
        sorted_recent = list(reversed(recent))

        ds = LottoSequenceDataset.__new__(LottoSequenceDataset)
        ds.seq_len = config.TRANSFORMER_SEQ_LEN
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

    def get_attention_weights(self, draws: list) -> dict:
        """Attention 가중치를 반환한다 (XAI용).

        각 레이어의 마지막 시점에 대한 attention 분포를 반환.
        """
        if self.model is None:
            self._load_model()
        if self.model is None:
            return {}

        self.model.eval()

        recent = draws[: config.TRANSFORMER_SEQ_LEN]
        if len(recent) < config.TRANSFORMER_SEQ_LEN:
            while len(recent) < config.TRANSFORMER_SEQ_LEN:
                recent.append({"numbers": []})

        sorted_recent = list(reversed(recent))
        ds = LottoSequenceDataset.__new__(LottoSequenceDataset)
        ds.seq_len = config.TRANSFORMER_SEQ_LEN
        features = []
        for d in sorted_recent:
            features.append(ds._draw_to_features(d))

        x = torch.FloatTensor(np.array([features])).to(self.device)

        with torch.no_grad():
            attn_maps = self.model.get_attention_maps(x)

        # 마지막 레이어, 모든 헤드 평균, 마지막 시점의 attention 분포
        last_layer_attn = attn_maps[-1]  # (1, nhead, seq_len, seq_len)
        avg_attn = last_layer_attn.mean(dim=1)  # (1, seq_len, seq_len)
        last_step_attn = avg_attn[0, -1, :]  # (seq_len,) — 마지막 시점이 각 과거에 주목한 정도

        attn_np = last_step_attn.cpu().numpy()

        result = {}
        for i, d in enumerate(sorted_recent):
            round_num = d.get("round", i)
            result[round_num] = float(attn_np[i])

        return result

    def _save_model(self):
        """모델 저장."""
        path = os.path.join(config.MODEL_DIR, "transformer_model.pt")
        if self.model:
            torch.save(self.model.state_dict(), path)

    def _load_model(self):
        """저장된 모델 로드."""
        path = os.path.join(config.MODEL_DIR, "transformer_model.pt")
        if os.path.exists(path):
            self.model = LottoTransformer().to(self.device)
            self.model.load_state_dict(
                torch.load(path, map_location=self.device, weights_only=True)
            )
            self.model.eval()

    def get_xai_reasoning(self, draws: list) -> str:
        """가장 집중(Attention)한 과거 회차를 찾아 분석 근거 텍스트를 생성합니다."""
        attn_weights = self.get_attention_weights(draws)
        if not attn_weights:
            return ""

        # 어텐션 점수 내림차순 정렬
        sorted_attn = sorted(attn_weights.items(), key=lambda x: x[1], reverse=True)
        
        # 현재 분석 기준이 되는 최신 회차 번호
        current_round = draws[0].get("round", 0) if draws else 0
        
        # 자기 자신(최신 회차)을 제외하고, 가장 강하게 참조한 과거 회차 찾기
        for rnd, weight in sorted_attn:
            if rnd != current_round:
                weeks_ago = current_round - rnd
                # 어텐션이 5% 이상 집중되었을 때만 유의미한 근거로 출력
                if weight > 0.05:
                    return f"거시적 시계열 맥락 상 {weeks_ago}주 전({rnd}회차)의 패턴 전개와 매우 유사한 흐름(집중도 {weight*100:.1f}%)을 감지했습니다."
                break
        return ""
