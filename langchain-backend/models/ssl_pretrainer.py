"""G-8: Self-Supervised Pretraining for shared neural backbone.

Stage 0 핵심 인프라. 1100회차 데이터로 마스킹+대조학습 backbone 사전학습.
이후 Stage 1~2의 모든 신경망 (TFT/N-BEATS/MHN/Bayesian NN/CNN/TabNet/AE)이
이 backbone으로 가중치 초기화.

Loss:
    total = masked_modeling_loss + contrastive_loss
    - masked_modeling_loss: 15% mask 후 reconstruction
    - contrastive_loss: 인접 회차 (within ±5) 양성, 먼 회차 (>50) 음성

출력: config.SSL_BACKBONE_PATH (.pt)
"""

from __future__ import annotations

import os
from typing import Optional

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, Dataset

import config


# ────────────────── Backbone 모델 ──────────────────


class SharedBackbone(nn.Module):
    """11 base 신경망이 공유하는 Transformer encoder.

    TFT 흡수 정책상 LSTM/Transformer 폐기 후 본 backbone이 시계열 백본 역할.
    출력은 (batch, seq, hidden_dim) — 각 모델이 자신의 head로 후속 처리.
    """

    def __init__(
        self,
        input_dim: int = 65,
        hidden_dim: int = 128,
        num_layers: int = 4,
        nhead: int = 4,
        dropout: float = 0.1,
    ):
        super().__init__()
        self.input_proj = nn.Linear(input_dim, hidden_dim)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=hidden_dim,
            nhead=nhead,
            dim_feedforward=hidden_dim * 2,
            dropout=dropout,
            batch_first=True,
            activation="gelu",
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)
        self.recon_head = nn.Linear(hidden_dim, input_dim)
        self.proj_head = nn.Linear(hidden_dim, hidden_dim)  # contrastive projection

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """x: (batch, seq, input_dim) → (encoded, projected)."""
        h = self.input_proj(x)
        h = self.encoder(h)
        return h, self.proj_head(h.mean(dim=1))


# ────────────────── Dataset ──────────────────


class RoundsSequenceDataset(Dataset):
    """1100회차 → 슬라이딩 윈도우 시퀀스 + 인접/먼 회차 페어."""

    def __init__(self, features: np.ndarray, seq_len: int = 30, near_window: int = 5, far_window: int = 50):
        # features: (num_rounds, input_dim)
        self.features = features
        self.seq_len = seq_len
        self.near_window = near_window
        self.far_window = far_window
        self.num_rounds = features.shape[0]

    def __len__(self) -> int:
        return max(0, self.num_rounds - self.seq_len)

    def __getitem__(self, idx: int) -> dict:
        seq = self.features[idx : idx + self.seq_len]
        near_start = max(0, idx - self.near_window)
        near_end = min(self.num_rounds - self.seq_len, idx + self.near_window)
        near_idx = np.random.randint(near_start, near_end + 1)
        near_seq = self.features[near_idx : near_idx + self.seq_len]

        far_choices = list(range(0, max(0, idx - self.far_window))) + list(
            range(min(self.num_rounds - self.seq_len, idx + self.far_window), self.num_rounds - self.seq_len)
        )
        far_idx = np.random.choice(far_choices) if far_choices else (idx + self.far_window) % (self.num_rounds - self.seq_len)
        far_seq = self.features[far_idx : far_idx + self.seq_len]

        return {
            "anchor": torch.from_numpy(seq).float(),
            "near": torch.from_numpy(near_seq).float(),
            "far": torch.from_numpy(far_seq).float(),
        }


# ────────────────── Pretrainer ──────────────────


class SSLPretrainer:
    """마스킹 + 대조학습 결합 사전학습기."""

    def __init__(
        self,
        input_dim: int = 65,
        hidden_dim: int = 128,
        num_layers: int = 4,
        device: Optional[str] = None,
    ):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.backbone = SharedBackbone(
            input_dim=input_dim, hidden_dim=hidden_dim, num_layers=num_layers
        ).to(self.device)
        self.mask_ratio = config.SSL_MASK_RATIO
        self.temp = config.SSL_CONTRASTIVE_TEMP

    def _mask_inputs(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """랜덤 마스킹. (batch, seq, dim) → (masked_x, mask)."""
        mask = torch.rand(x.shape[:2], device=x.device) < self.mask_ratio
        masked = x.clone()
        masked[mask] = 0.0
        return masked, mask

    def _step(self, batch: dict) -> dict:
        anchor = batch["anchor"].to(self.device)
        near = batch["near"].to(self.device)
        far = batch["far"].to(self.device)

        # Masked modeling on anchor
        masked, mask = self._mask_inputs(anchor)
        encoded, proj_anchor = self.backbone(masked)
        recon = self.backbone.recon_head(encoded)
        recon_loss = F.mse_loss(recon[mask], anchor[mask]) if mask.any() else torch.tensor(0.0, device=self.device)

        # Contrastive: anchor near positive, far negative
        _, proj_near = self.backbone(near)
        _, proj_far = self.backbone(far)
        a = F.normalize(proj_anchor, dim=-1)
        p = F.normalize(proj_near, dim=-1)
        n = F.normalize(proj_far, dim=-1)
        pos_sim = (a * p).sum(dim=-1) / self.temp
        neg_sim = (a * n).sum(dim=-1) / self.temp
        contrastive_loss = -F.logsigmoid(pos_sim - neg_sim).mean()

        return {
            "recon_loss": recon_loss,
            "contrastive_loss": contrastive_loss,
            "total": recon_loss + contrastive_loss,
        }

    def train(self, features: np.ndarray, epochs: Optional[int] = None, batch_size: int = 32, lr: float = 1e-4) -> dict:
        epochs = epochs or config.SSL_PRETRAIN_EPOCHS
        dataset = RoundsSequenceDataset(features)
        loader = DataLoader(dataset, batch_size=batch_size, shuffle=True, num_workers=0)

        optimizer = torch.optim.AdamW(self.backbone.parameters(), lr=lr, weight_decay=1e-5)
        history = {"recon": [], "contrastive": [], "total": []}

        self.backbone.train()
        for ep in range(epochs):
            ep_recon, ep_cont, ep_total, n = 0.0, 0.0, 0.0, 0
            for batch in loader:
                losses = self._step(batch)
                optimizer.zero_grad()
                losses["total"].backward()
                torch.nn.utils.clip_grad_norm_(self.backbone.parameters(), 1.0)
                optimizer.step()

                ep_recon += losses["recon_loss"].item()
                ep_cont += losses["contrastive_loss"].item()
                ep_total += losses["total"].item()
                n += 1

            avg_recon = ep_recon / max(1, n)
            avg_cont = ep_cont / max(1, n)
            avg_total = ep_total / max(1, n)
            history["recon"].append(avg_recon)
            history["contrastive"].append(avg_cont)
            history["total"].append(avg_total)
            print(f"  [SSL] epoch {ep + 1}/{epochs}  recon={avg_recon:.4f}  contrastive={avg_cont:.4f}  total={avg_total:.4f}")

        return history

    def save_backbone(self, path: Optional[str] = None) -> str:
        path = path or config.SSL_BACKBONE_PATH
        os.makedirs(os.path.dirname(path), exist_ok=True)
        torch.save(self.backbone.state_dict(), path)
        return path

    def load_backbone(self, path: Optional[str] = None) -> None:
        path = path or config.SSL_BACKBONE_PATH
        self.backbone.load_state_dict(torch.load(path, map_location=self.device))


# ────────────────── CLI ──────────────────


def main():
    """python -m langchain-backend.models.ssl_pretrainer --epochs 50.

    Stage 0 검증 게이트: SSL pretrain 1 epoch 완주 확인.
    """
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs", type=int, default=config.SSL_PRETRAIN_EPOCHS)
    parser.add_argument("--smoke", action="store_true", help="1 epoch 검증")
    args = parser.parse_args()

    # TODO Stage 0-8: 실 데이터 로드 — db.repository에서 회차 feature 추출
    # 임시 smoke test: 1100×65 랜덤 데이터로 1 epoch 학습 가능 검증
    if args.smoke:
        print("[SSL] smoke test - random 1100x65 data, 1 epoch")
        rng = np.random.default_rng(config.RANDOM_SEED)
        features = rng.standard_normal((1100, 65)).astype(np.float32)
        trainer = SSLPretrainer()
        history = trainer.train(features, epochs=1, batch_size=16)
        path = trainer.save_backbone()
        print(f"[SSL] smoke done. backbone saved: {path}")
        return

    raise NotImplementedError(
        "real-data training: deferred to Stage 0-8 (db.repository integration). use --smoke for now."
    )


if __name__ == "__main__":
    main()
