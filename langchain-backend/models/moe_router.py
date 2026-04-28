"""M-1 진화: Mixture of Experts 라우팅.

기존 Autoencoder 게이트(이상/정상 2 분기)를 4 expert로 확장:
  - normal: 평범한 회차 (AE 재구성오차 ≤ percentile 95)
  - anomaly: 이상 회차 (AE 재구성오차 > percentile 95)
  - regression: 활성 회귀 N이 풍부 (16~30 active N)
  - memo: 사용자 메모 신뢰도 ≥ 0.7 (충분 누적 후 활성)

Gating network: 회차 feature → 4 expert probability (softmax)
출력: 각 expert에게 위임할 가중치 (top-2 또는 전체 가중평균)

학습: walk-forward 라벨 = 각 expert가 해당 회차 hit 기여도 → CE
"""

from __future__ import annotations

import os
from typing import Optional

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

import config


class MoEGatingNetwork(nn.Module):
    """4 expert softmax gate."""

    def __init__(self, feature_dim: int, hidden_dim: int = 64, num_experts: Optional[int] = None):
        super().__init__()
        self.num_experts = num_experts or config.MOE_NUM_EXPERTS
        self.gate = nn.Sequential(
            nn.Linear(feature_dim, hidden_dim),
            nn.GELU(),
            nn.Dropout(0.1),
            nn.Linear(hidden_dim, self.num_experts),
        )

    def forward(self, feature: torch.Tensor) -> torch.Tensor:
        """feature: (batch, feature_dim) → softmax (batch, num_experts)."""
        logits = self.gate(feature)
        return F.softmax(logits, dim=-1)


class MoERouter:
    """4 expert 라우터.

    각 회차마다:
      1. context feature 추출 (AE 재구성오차, 활성 N count, 메모 신뢰도, 기타 통계)
      2. gate → expert weight
      3. expert별 prediction을 weighted sum
    """

    EXPERT_NAMES = ("normal", "anomaly", "regression", "memo")

    def __init__(self, feature_dim: int = 16, device: Optional[str] = None):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.gate = MoEGatingNetwork(feature_dim=feature_dim).to(self.device)
        assert tuple(config.MOE_EXPERT_NAMES) == self.EXPERT_NAMES, (
            "config.MOE_EXPERT_NAMES 변경 시 본 클래스 EXPERT_NAMES 도 동기화"
        )

    def extract_context_feature(self, ctx: dict) -> torch.Tensor:
        """회차 컨텍스트 → gate 입력 feature.

        Args:
            ctx: {
                "ae_recon_error": float,
                "ae_recon_percentile": float (0~100),
                "active_regression_n_count": int,
                "memo_domain_confidence": float (0~1),
                "rolling_volatility": float,
                "consecutive_anomalies": int,
                ...
            }
        """
        # MoE feature 16개: 추후 학습 데이터로 fine-tune
        feats = [
            ctx.get("ae_recon_error", 0.0),
            ctx.get("ae_recon_percentile", 50.0) / 100.0,
            float(ctx.get("active_regression_n_count", 0)) / 30.0,
            ctx.get("memo_domain_confidence", 0.0),
            ctx.get("rolling_volatility", 0.0),
            float(ctx.get("consecutive_anomalies", 0)) / 10.0,
            ctx.get("hot_streak_avg", 0.0),
            ctx.get("dormancy_avg", 0.0),
            ctx.get("sum_zscore_long", 0.0),
            ctx.get("ac_zscore_long", 0.0),
            ctx.get("memo_hit_rate_recent_50", 0.0),
            ctx.get("regression_max_consecutive_global", 0.0) / 10.0,
            ctx.get("filter_compliance_avg", 0.5),
            ctx.get("consensus_strength_avg", 0.5),
            ctx.get("days_since_last_anomaly", 0.0) / 100.0,
            ctx.get("input_dim_norm", 0.5),
        ]
        return torch.tensor(feats, dtype=torch.float32, device=self.device).unsqueeze(0)

    def route(self, ctx: dict) -> dict:
        """회차 컨텍스트 → expert별 가중치."""
        self.gate.eval()
        with torch.no_grad():
            feat = self.extract_context_feature(ctx)
            probs = self.gate(feat).squeeze(0).cpu().numpy()
        return {name: float(p) for name, p in zip(self.EXPERT_NAMES, probs)}

    def route_batch(self, ctx_batch: list[dict]) -> list[dict]:
        return [self.route(c) for c in ctx_batch]

    def combine_expert_outputs(self, expert_outputs: dict, weights: dict) -> np.ndarray:
        """expert별 prediction (1~45 prob) → weighted sum.

        Args:
            expert_outputs: {expert_name: np.ndarray shape (45,)}
            weights: {expert_name: float}
        """
        out = np.zeros(45)
        total_w = 0.0
        for name, w in weights.items():
            if name in expert_outputs:
                out += w * np.asarray(expert_outputs[name])
                total_w += w
        if total_w > 0:
            out /= total_w
        return out

    def train_gate(
        self,
        ctx_history: list[dict],
        expert_hit_history: list[dict],
        epochs: int = 30,
        lr: float = 1e-3,
    ) -> dict:
        """walk-forward로 gate 학습.

        Args:
            ctx_history: [{...}, ...] 회차별 컨텍스트
            expert_hit_history: [{name: hit_count}, ...] 각 expert가 hit 기여한 정도
                hit_count는 0~6 정수 또는 normalized 0~1
        """
        self.gate.train()
        optimizer = torch.optim.AdamW(self.gate.parameters(), lr=lr, weight_decay=1e-5)
        history = {"loss": []}

        for ep in range(epochs):
            ep_loss, n = 0.0, 0
            for ctx, hits in zip(ctx_history, expert_hit_history):
                feat = self.extract_context_feature(ctx)
                pred = self.gate(feat)  # (1, num_experts)
                target_hits = torch.tensor(
                    [hits.get(name, 0.0) for name in self.EXPERT_NAMES],
                    dtype=torch.float32, device=self.device,
                ).unsqueeze(0)
                target_norm = target_hits / (target_hits.sum() + 1e-8)
                loss = F.kl_div(pred.log(), target_norm, reduction="batchmean")
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
                ep_loss += loss.item()
                n += 1
            avg = ep_loss / max(1, n)
            history["loss"].append(avg)
            print(f"  [MoE] epoch {ep + 1}/{epochs}  KL={avg:.4f}")

        return history

    def save(self, path: Optional[str] = None) -> str:
        path = path or config.MOE_GATING_PATH
        os.makedirs(os.path.dirname(path), exist_ok=True)
        torch.save(self.gate.state_dict(), path)
        return path

    def load(self, path: Optional[str] = None) -> None:
        path = path or config.MOE_GATING_PATH
        if os.path.exists(path):
            self.gate.load_state_dict(torch.load(path, map_location=self.device))
