"""U-1: G-7 GNN 재설계 검증.

대상:
- LottoGNNModel forward (logits + attention)
- CombinedGNNLoss = SoftmaxRankingLoss + 0.3 × BCE
- GNNTrainer feature transform 헬퍼
- Top-K 희소화 K=15
- config 외부화 (gnn_model.py 내부 하드코딩 제거)
"""

import sys
from pathlib import Path

import numpy as np
import pytest
import torch

BACKEND = Path(__file__).parent.parent.parent / "langchain-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import config
from models.gnn_model import (
    LottoGNNModel,
    CombinedGNNLoss,
    SoftmaxRankingLoss,
    GraphAttentionLayer,
    GNNTrainer,
    NODE_FEAT_DIM,
    HIDDEN_DIM,
    HEAD_DIM_2,
    N_HEADS_1,
    N_HEADS_2,
    TOPK,
    BCE_AUX_WEIGHT,
)


# ────────────────── G-7-B: config 외부화 ──────────────────

class TestConfigExternalization:
    """G-7-B: 모든 GNN 하이퍼파라미터가 config.py에 있는지."""

    def test_topk_from_config(self):
        assert TOPK == config.GNN_TOPK == 15  # G-7-C: 10 → 15

    def test_epochs_from_config(self):
        assert config.GNN_EPOCHS == 80  # G-7-B: 300 → 80

    def test_patience_from_config(self):
        assert config.GNN_PATIENCE == 15  # G-7-B: 30 → 15

    def test_lr_from_config(self):
        assert config.GNN_LR == 0.0008  # G-7-B

    def test_dropout_from_config(self):
        assert config.GNN_DROPOUT == 0.25  # G-7-B: 0.3 → 0.25

    def test_heads_from_config(self):
        assert config.GNN_HEADS == [4, 2]
        assert N_HEADS_1 == 4
        assert N_HEADS_2 == 2

    def test_dimensions_from_config(self):
        assert NODE_FEAT_DIM == 10
        assert HIDDEN_DIM == 64
        assert HEAD_DIM_2 == 32

    def test_bce_aux_weight(self):
        assert BCE_AUX_WEIGHT == 0.3  # G-7-A


# ────────────────── G-7-A: CombinedGNNLoss ──────────────────

class TestCombinedGNNLoss:
    """G-7-A: SoftmaxRankingLoss + 0.3 × BCE 결합."""

    def test_combined_loss_basic(self):
        loss_fn = CombinedGNNLoss(bce_weight=0.3, pos_weight=6.5)
        logits = torch.randn(45)
        labels = torch.zeros(45)
        labels[[0, 5, 10, 20, 30, 40]] = 1.0
        loss = loss_fn(logits, labels)
        assert loss.item() > 0
        assert torch.isfinite(loss)

    def test_combined_loss_breaks_into_components(self):
        """CombinedLoss = SoftmaxRanking + 0.3 × BCE 산술 동치 확인."""
        torch.manual_seed(42)
        logits = torch.randn(45)
        labels = torch.zeros(45)
        labels[[0, 5, 10, 20, 30, 40]] = 1.0

        # 통합 loss
        combined = CombinedGNNLoss(bce_weight=0.3, pos_weight=6.5)
        total = combined(logits, labels).item()

        # 개별 컴포넌트 합
        rank_loss = SoftmaxRankingLoss()(logits, labels).item()
        bce = torch.nn.BCEWithLogitsLoss(pos_weight=torch.full([45], 6.5))
        bce_val = bce(logits, labels).item()
        manual = rank_loss + 0.3 * bce_val

        assert total == pytest.approx(manual, rel=1e-5)

    def test_softmax_ranking_zero_for_no_positive(self):
        """정답 0개일 때 0 반환."""
        loss = SoftmaxRankingLoss()
        out = loss(torch.randn(45), torch.zeros(45))
        assert out.item() == 0.0

    def test_combined_loss_all_zero_labels(self):
        """정답 0개여도 BCE 부분이 살아있으므로 > 0."""
        loss_fn = CombinedGNNLoss(bce_weight=0.3, pos_weight=6.5)
        logits = torch.randn(45)
        labels = torch.zeros(45)
        loss = loss_fn(logits, labels)
        # SoftmaxRanking은 0이지만 BCE는 > 0
        assert loss.item() > 0


# ────────────────── G-7-E: Forward + Attention 출력 ──────────────────

class TestGNNModelForward:
    """LottoGNNModel forward — return_attention 옵션 검증."""

    @pytest.fixture
    def adj(self):
        torch.manual_seed(42)
        a = torch.eye(45) * 0.5 + torch.rand(45, 45) * 0.1
        return (a + a.t()) / 2

    @pytest.fixture
    def x(self):
        torch.manual_seed(42)
        return torch.randn(45, NODE_FEAT_DIM)

    def test_forward_shape(self, x, adj):
        m = LottoGNNModel()
        out = m(x, adj)
        assert out.shape == (45,)

    def test_forward_with_attention(self, x, adj):
        """G-7-E: return_attention=True → (logits, attn) 반환."""
        m = LottoGNNModel()
        logits, attn = m(x, adj, return_attention=True)
        assert logits.shape == (45,)
        assert attn.shape == (N_HEADS_1, 45, 45)

    def test_attention_is_detached(self, x, adj):
        """attention은 학습 그래프에서 분리되어야 (외부 노출용)."""
        m = LottoGNNModel()
        _, attn = m(x, adj, return_attention=True)
        assert not attn.requires_grad


# ────────────────── G-7-D: Feature Transform 헬퍼 ──────────────────

class TestFeatureTransform:
    """GNNTrainer의 PowerTransformer 적용 헬퍼."""

    def test_apply_without_fit_returns_raw(self, tmp_path, monkeypatch):
        """transformer가 없으면 raw 그대로 반환 (학습 전)."""
        monkeypatch.setattr(config, "MODEL_DIR", str(tmp_path))
        trainer = GNNTrainer()
        trainer._feature_transformer = None
        raw = np.random.rand(45, NODE_FEAT_DIM).astype(np.float32)
        out = trainer._apply_feature_transform(raw)
        np.testing.assert_array_equal(out, raw)

    def test_apply_with_fitted_transformer(self, tmp_path, monkeypatch):
        """fit된 transformer가 있으면 정규화 컬럼만 변환."""
        monkeypatch.setattr(config, "MODEL_DIR", str(tmp_path))
        trainer = GNNTrainer()
        from sklearn.preprocessing import PowerTransformer
        pt = PowerTransformer(method="yeo-johnson", standardize=True)
        # 100 row × 6 col (FEATURE_NORMALIZE_INDICES=[0,1,2,3,4,6])
        rng = np.random.RandomState(42)
        train = rng.exponential(scale=0.1, size=(100, 6)).astype(np.float32)
        pt.fit(train)
        trainer._feature_transformer = pt

        raw = rng.exponential(scale=0.1, size=(45, NODE_FEAT_DIM)).astype(np.float32)
        original_idx5 = raw[:, 5].copy()  # gap_dev (raw 그대로 보존돼야)

        out = trainer._apply_feature_transform(raw)

        assert out.shape == raw.shape
        # idx 5는 변환 안 됨
        np.testing.assert_array_equal(out[:, 5], original_idx5)
        # idx 0~4, 6은 transform됨 (값 다름)
        for i in [0, 1, 2, 3, 4, 6]:
            assert not np.allclose(out[:, i], raw[:, i]), f"col {i} not transformed"


# ────────────────── G-7-C: Top-K 희소화 ──────────────────

class TestTopKSparsification:
    def test_topk_default_15(self):
        """기본 K=15 (GNN_TOPK)."""
        rng = np.random.RandomState(42)
        counts = (rng.rand(45, 45) * 100).astype(np.float32)
        counts = (counts + counts.T) / 2  # symmetric
        np.fill_diagonal(counts, 0)

        # Top-K=15로 희소화
        adj_norm = GNNTrainer._normalize_adjacency(counts, top_k=15)

        # 자기 루프 제외, 각 행의 비영 엣지 ≤ 30 (15 + 대칭 union)
        # 현실적으로 정확히 15는 아니나 매우 dense한 경우 30 이내
        for i in range(45):
            row_nonzero = (adj_norm[i] > 0).sum() - 1  # 대각 제외
            assert row_nonzero <= 30, f"row {i}: {row_nonzero} non-zero"

    def test_topk_smaller_means_more_sparse(self):
        """K가 작을수록 희소."""
        rng = np.random.RandomState(42)
        counts = (rng.rand(45, 45) * 100).astype(np.float32)
        counts = (counts + counts.T) / 2
        np.fill_diagonal(counts, 0)

        adj_5 = GNNTrainer._normalize_adjacency(counts, top_k=5)
        adj_20 = GNNTrainer._normalize_adjacency(counts, top_k=20)

        # K=5는 K=20보다 비영 엣지 적음
        nz_5 = (adj_5 > 0).sum()
        nz_20 = (adj_20 > 0).sum()
        assert nz_5 < nz_20

    def test_normalize_adjacency_symmetric(self):
        """대칭 정규화 후에도 symmetric 보장."""
        rng = np.random.RandomState(42)
        counts = (rng.rand(45, 45) * 50).astype(np.float32)
        counts = (counts + counts.T) / 2
        np.fill_diagonal(counts, 0)
        adj_norm = GNNTrainer._normalize_adjacency(counts, top_k=15)
        np.testing.assert_allclose(adj_norm, adj_norm.T, atol=1e-5)
