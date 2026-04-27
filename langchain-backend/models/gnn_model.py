"""
LottoGNN – Graph Attention Network (순수 PyTorch, 외부 라이브러리 불필요)

아키텍처 (G-7 적용):
  Node: 45개 번호 (1~45)
  Edge: 동반출현 횟수 → Top-K=15 희소화 (G-7-C)
  Node feature: 10차원, freq/gap/hot 6개는 PowerTransformer 정규화 (G-7-D)
  GAT Layer 1: 10 → 64  (4-head)
  GAT Layer 2: 64 → 32  (2-head)
  Classifier:  32 → 32 → 1  (per-node 출현 로짓)
  Loss (G-7-A): SoftmaxRankingLoss + 0.3 × BCEWithLogitsLoss(pos_weight=6.5)
  Hyperparam (G-7-B): epochs=80, patience=15, LR=0.0008, dropout=0.25 — config.py
"""

import os
import json
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import config
# G-7-D: PowerTransformer 정규화 (옵셔널)
try:
    from sklearn.preprocessing import PowerTransformer
    _SKLEARN_OK = True
except ImportError:
    _SKLEARN_OK = False

# ── 하이퍼파라미터 (G-7-B: config.py에서 로드) ──────────────────────────────
NODE_FEAT_DIM = config.GNN_NODE_FEAT_DIM
HIDDEN_DIM    = config.GNN_HIDDEN_DIM
HEAD_DIM_2    = config.GNN_HEAD_DIM_2
N_HEADS_1     = config.GNN_HEADS[0]
N_HEADS_2     = config.GNN_HEADS[1]
DROPOUT       = config.GNN_DROPOUT
LEARNING_RATE = config.GNN_LR
WEIGHT_DECAY  = config.GNN_WEIGHT_DECAY
MAX_EPOCHS    = config.GNN_EPOCHS
PATIENCE      = config.GNN_PATIENCE
MIN_HIST      = config.GNN_MIN_HIST
TOPK          = config.GNN_TOPK
POS_WEIGHT    = config.GNN_POS_WEIGHT
BCE_AUX_WEIGHT = config.GNN_BCE_AUX_WEIGHT
FEATURE_NORMALIZE = config.GNN_FEATURE_NORMALIZE
FEATURE_NORMALIZE_IDX = config.GNN_FEATURE_NORMALIZE_INDICES


# ── 손실 함수: Softmax Ranking Loss ──────────────────────────────────────────
class SoftmaxRankingLoss(nn.Module):
    """
    45개 번호를 경쟁적으로 비교하는 랭킹 손실.

    BCEWithLogitsLoss 문제:
      - 각 번호를 독립 이진 분류 → 모든 로짓이 사전확률(≈-1.87)로 수렴 가능
      - 번호 간 상대적 차이를 학습할 동기 없음 → uniform 수렴

    SoftmaxRankingLoss 해결:
      - Softmax(logits[45]) → 45개 번호가 확률 합 1로 경쟁
      - 맞는 6개 번호의 log-prob을 최대화
      - 한 번호의 확률이 높아지면 다른 번호들이 낮아짐 → 반드시 차별화
    """
    def forward(self, logits: torch.Tensor, labels: torch.Tensor) -> torch.Tensor:
        log_probs = F.log_softmax(logits, dim=0)   # [45]
        pos_mask  = labels > 0                      # 6개 당첨 번호
        if pos_mask.sum() == 0:
            return torch.tensor(0.0, requires_grad=True)
        return -log_probs[pos_mask].mean()          # NLL for winning numbers


# ── G-7-A: Combined Loss = SoftmaxRanking + 0.3 × BCE ───────────────────────
class CombinedGNNLoss(nn.Module):
    """G-7-A 결정: Softmax 단독은 정답 외 번호의 prob 미세 조정에 약함.
    BCE 보조로 logit 안정성 확보 + mode collapse 추가 방어.

    total = SoftmaxRankingLoss + bce_weight × BCEWithLogitsLoss(pos_weight=6.5)
    """
    def __init__(self, bce_weight: float = BCE_AUX_WEIGHT,
                 pos_weight: float = POS_WEIGHT, device: torch.device = None):
        super().__init__()
        self.softmax_rank = SoftmaxRankingLoss()
        pw = torch.full([45], pos_weight, device=device) if device is not None \
             else torch.full([45], pos_weight)
        self.bce = nn.BCEWithLogitsLoss(pos_weight=pw)
        self.bce_weight = bce_weight

    def forward(self, logits: torch.Tensor, labels: torch.Tensor) -> torch.Tensor:
        return self.softmax_rank(logits, labels) + self.bce_weight * self.bce(logits, labels)


# ── Graph Attention Layer ─────────────────────────────────────────────────────
class GraphAttentionLayer(nn.Module):
    """
    단일 Graph Attention Layer (Veličković et al., 2018)

    h   [N, in_dim]  → out [N, out_dim]
    adj [N, N]       대칭 정규화 인접 행렬 (비음수)
    """
    def __init__(self, in_dim: int, out_dim: int,
                 n_heads: int, dropout: float = 0.2):
        super().__init__()
        assert out_dim % n_heads == 0, "out_dim must be divisible by n_heads"
        self.n_heads  = n_heads
        self.head_dim = out_dim // n_heads
        self.out_dim  = out_dim

        # 공유 선형 변환
        self.W = nn.Linear(in_dim, out_dim, bias=False)

        # 헤드별 어텐션 벡터 a ∈ R^{2 × head_dim}
        self.a = nn.Parameter(torch.empty(n_heads, 2 * self.head_dim))
        nn.init.xavier_uniform_(self.a)

        self.dropout    = nn.Dropout(dropout)
        self.leaky_relu = nn.LeakyReLU(negative_slope=0.2)
        self.layer_norm = nn.LayerNorm(out_dim)

    def forward(self, h: torch.Tensor, adj: torch.Tensor,
                return_attention: bool = False):
        """
        Args:
            h: [N, in_dim] 노드 피처
            adj: [N, N] 정규화 인접 행렬
            return_attention: True면 (out, attention[heads, N, N]) 반환

        Returns:
            return_attention=False: out [N, out_dim]
            return_attention=True:  (out, attn_weights [n_heads, N, N])
        """
        N   = h.size(0)                          # 45
        Wh  = self.W(h)                          # [N, out_dim]
        Wh3 = Wh.view(N, self.n_heads, self.head_dim)  # [N, H, D]

        head_outs = []
        attn_per_head = [] if return_attention else None
        for k in range(self.n_heads):
            wh_k = Wh3[:, k, :]                            # [N, D]

            # e_ij = LeakyReLU( a_k · [Wh_i ‖ Wh_j] )
            src  = wh_k.unsqueeze(1).expand(N, N, self.head_dim)   # [N,N,D]
            dst  = wh_k.unsqueeze(0).expand(N, N, self.head_dim)   # [N,N,D]
            pair = torch.cat([src, dst], dim=-1)                    # [N,N,2D]
            e    = self.leaky_relu((pair * self.a[k]).sum(-1))      # [N,N]

            # 엣지 없는 위치 마스킹 (-∞)
            mask = (adj > 0).float()
            e    = e * mask + (1.0 - mask) * (-1e9)

            # 소프트맥스 + 엣지 강도 가중
            alpha = F.softmax(e, dim=1) * adj   # [N,N]
            if return_attention:
                attn_per_head.append(alpha.detach())   # 학습된 attention 보존
            alpha = self.dropout(alpha)

            head_outs.append(alpha @ wh_k)      # [N, D]

        out = torch.cat(head_outs, dim=-1)       # [N, out_dim]
        out = F.elu(out)
        out = self.layer_norm(out)

        if return_attention:
            attn = torch.stack(attn_per_head, dim=0)   # [n_heads, N, N]
            return out, attn
        return out


# ── GNN 모델 ──────────────────────────────────────────────────────────────────
class LottoGNNModel(nn.Module):
    """2-layer Graph Attention Network + per-node 분류기 (G-7 적용)"""

    def __init__(self):
        super().__init__()
        self.gat1 = GraphAttentionLayer(
            NODE_FEAT_DIM, HIDDEN_DIM,  N_HEADS_1, DROPOUT
        )
        self.gat2 = GraphAttentionLayer(
            HIDDEN_DIM,    HEAD_DIM_2,  N_HEADS_2, DROPOUT * 0.7
        )
        self.classifier = nn.Sequential(
            nn.Linear(HEAD_DIM_2, 32),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(32, 1),
        )

    def forward(self, x: torch.Tensor, adj: torch.Tensor,
                return_attention: bool = False):
        """
        Args:
            x: [45, NODE_FEAT_DIM]
            adj: [45, 45] 정규화 인접 행렬
            return_attention: G-7-E — True면 (logits, layer1_attn) 반환

        Returns:
            return_attention=False: [45] per-node logits
            return_attention=True:  (logits [45], layer1_attn [n_heads_1, 45, 45])
        """
        if return_attention:
            h, attn1 = self.gat1(x, adj, return_attention=True)
            h = self.gat2(h, adj)
            logits = self.classifier(h).squeeze(-1)
            return logits, attn1
        h = self.gat1(x, adj)
        h = self.gat2(h, adj)
        return self.classifier(h).squeeze(-1)


# ── GNNTrainer ────────────────────────────────────────────────────────────────
class GNNTrainer:
    def __init__(self):
        self.device   = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.save_dir = config.MODEL_DIR
        os.makedirs(self.save_dir, exist_ok=True)
        self.model       = LottoGNNModel().to(self.device)
        self._adj_counts = np.zeros((45, 45), dtype=np.float32)
        self._feature_transformer = None  # G-7-D: PowerTransformer (학습 시 fit)
        self._load_adjacency_counts()
        self._load_feature_transformer()

    # ── 영속성 헬퍼 ──────────────────────────────────────────────────────────
    def _load_adjacency_counts(self):
        path = os.path.join(self.save_dir, "gnn_adjacency.json")
        if not os.path.exists(path):
            return
        with open(path, "r") as f:
            arr = np.array(json.load(f), dtype=np.float32)
        # 하위 호환: 구버전은 정규화 값(max≤1)으로 저장됨 → 스케일 복원
        if arr.max() <= 1.0 and arr.max() > 0:
            arr = (arr * 1000).round()
        self._adj_counts = arr
        print("  [GNN] adjacency counts 불러옴")

    def _save_adjacency_counts(self):
        path = os.path.join(self.save_dir, "gnn_adjacency.json")
        with open(path, "w") as f:
            json.dump(self._adj_counts.tolist(), f)

    # ── G-7-D: PowerTransformer 영속성 ───────────────────────────────────
    def _save_feature_transformer(self):
        if self._feature_transformer is None:
            return
        import pickle
        path = os.path.join(self.save_dir, "gnn_feature_transformer.pkl")
        with open(path, "wb") as f:
            pickle.dump(self._feature_transformer, f)

    def _load_feature_transformer(self):
        path = os.path.join(self.save_dir, "gnn_feature_transformer.pkl")
        if not os.path.exists(path) or not _SKLEARN_OK:
            return
        try:
            import pickle
            with open(path, "rb") as f:
                self._feature_transformer = pickle.load(f)
        except Exception as e:
            print(f"  [GNN] feature transformer 로드 실패 (raw feature 사용): {e}")
            self._feature_transformer = None

    def _apply_feature_transform(self, raw_feats: np.ndarray) -> np.ndarray:
        """G-7-D: raw feature → 정규화된 feature.

        FEATURE_NORMALIZE_IDX 컬럼만 PowerTransformer 적용, 나머지는 raw.
        transformer가 fit되지 않았으면 raw 그대로 반환.
        """
        if not FEATURE_NORMALIZE or self._feature_transformer is None:
            return raw_feats
        out = raw_feats.copy()
        out[:, FEATURE_NORMALIZE_IDX] = self._feature_transformer.transform(
            raw_feats[:, FEATURE_NORMALIZE_IDX]
        )
        return out.astype(np.float32)

    # ── 그래프 / 피처 구성 ───────────────────────────────────────────────────
    @staticmethod
    def _normalize_adjacency(adj_counts: np.ndarray, top_k: int = TOPK) -> np.ndarray:
        """
        원시 동반출현 카운트 행렬 → Top-K 희소 대칭 정규화 인접 행렬

        [Over-smoothing 방지]
        로또 그래프는 1200+회차로 인해 45개 노드가 거의 완전 연결(dense).
        Dense graph에서 2-layer GAT를 통과하면 모든 노드 표현이 평균화되어
        균일 예측(uniform)으로 수렴한다 → top_k 이웃만 남겨 희소화.

        G-7-C: top_k=15 (기존 10) — 1,100회차 dense graph에서 정보 손실 방지.
        검증: validation/timeseries_cv 5-fold에서 K∈{10,15,20,25} grid search.
        """
        adj = adj_counts.copy().astype(np.float32)
        N   = adj.shape[0]

        # ── Top-K 희소화: 각 행(노드)에서 동반출현 상위 top_k만 유지 ──
        sparse = np.zeros((N, N), dtype=np.float32)
        for i in range(N):
            row    = adj[i].copy()
            row[i] = 0.0  # 자기 자신 제외
            if row.max() > 0:
                # top_k번째로 큰 값을 기준으로 threshold 설정
                kk = min(top_k, int((row > 0).sum()))
                if kk > 0:
                    threshold = np.partition(row, -kk)[-kk]
                    sparse[i] = np.where(row >= threshold, row, 0.0)

        # 대칭 보장: 어느 한쪽이라도 strong edge면 연결 (union)
        adj = np.maximum(sparse, sparse.T)

        # 자기루프: 해당 행 최대값 + 1 (본인 노드 중요도)
        self_loop = adj.max(axis=1) + 1.0
        np.fill_diagonal(adj, self_loop)

        # 대칭 정규화 D^{-1/2} A D^{-1/2}
        deg          = adj.sum(axis=1)
        deg_inv_sqrt = np.where(deg > 0, 1.0 / np.sqrt(deg), 0.0)
        D            = np.diag(deg_inv_sqrt)
        return (D @ adj @ D).astype(np.float32)

    @staticmethod
    def _build_features_raw(draws: list) -> np.ndarray:
        """
        히스토리 draws → 노드 피처 행렬 [45, NODE_FEAT_DIM] (원시값, 미정규화)

        피처 구성 (인덱스 0~9):
          0  freq_10   : 최근 10회차 출현율   (G-7-D PowerTransformer)
          1  freq_20   : 최근 20회차 출현율   (G-7-D PowerTransformer)
          2  freq_50   : 최근 50회차 출현율   (G-7-D PowerTransformer)
          3  cur_gap_n : 현재 GAP/50 클립    (G-7-D PowerTransformer)
          4  avg_gap_n : 평균 GAP/15 클립    (G-7-D PowerTransformer)
          5  gap_dev   : (현재-평균)/평균 편차 (raw — 이미 -1~1)
          6  hot_streak: 연속 출현 길이/5 클립 (G-7-D PowerTransformer)
          7  odd        : 홀수=1, 짝수=0      (raw)
          8  low        : 1~22=1, 23~45=0   (raw)
          9  pos_norm   : (번호-1)/44       (raw)

        G-7-D: 인덱스 0~4, 6은 long-tail 분포 → train fold에서 PowerTransformer fit.
                인덱스 5, 7, 8, 9는 raw 그대로.
        """
        N        = len(draws)
        features = np.zeros((45, NODE_FEAT_DIM), dtype=np.float32)

        for idx in range(45):
            num         = idx + 1
            appearances = [i for i, d in enumerate(draws)
                           if num in d.get("numbers", [])]

            # ── 출현 빈도 ──
            w10 = max(min(10, N), 1)
            w20 = max(min(20, N), 1)
            w50 = max(min(50, N), 1)
            freq_10 = sum(1 for d in draws[-10:] if num in d.get("numbers", [])) / w10
            freq_20 = sum(1 for d in draws[-20:] if num in d.get("numbers", [])) / w20
            freq_50 = sum(1 for d in draws[-50:] if num in d.get("numbers", [])) / w50

            # ── GAP 피처 ──
            if appearances:
                cur_gap = float((N - 1) - appearances[-1])
                gaps    = [appearances[k+1] - appearances[k]
                           for k in range(len(appearances) - 1)]
                avg_gap = float(np.mean(gaps)) if gaps else 7.5
                gap_dev = float(np.clip(
                    (cur_gap - avg_gap) / (avg_gap + 1e-6), -3.0, 3.0
                )) / 3.0
            else:
                cur_gap = float(N)
                avg_gap = 7.5
                gap_dev = 1.0
            cur_gap_n = min(cur_gap / 50.0, 1.0)
            avg_gap_n = min(avg_gap / 15.0, 1.0)

            # ── 핫스트릭 (최근 연속 출현) ──
            hot = 0
            for d in reversed(draws):
                if num in d.get("numbers", []):
                    hot += 1
                else:
                    break
            hot_n = min(hot / 5.0, 1.0)

            # ── 정적 피처 ──
            odd      = 1.0 if num % 2 == 1 else 0.0
            low_rng  = 1.0 if num <= 22    else 0.0
            pos_norm = (num - 1) / 44.0

            features[idx] = [
                freq_10, freq_20, freq_50,
                cur_gap_n, avg_gap_n, gap_dev,
                hot_n, odd, low_rng, pos_norm,
            ]

        return features

    @staticmethod
    def _build_adj_counts_from_draws(draws: list) -> np.ndarray:
        """draws 목록 → 45×45 원시 동반출현 카운트 행렬"""
        adj = np.zeros((45, 45), dtype=np.float32)
        for draw in draws:
            nums = [n - 1 for n in draw.get("numbers", []) if 1 <= n <= 45]
            for i in range(len(nums)):
                for j in range(i + 1, len(nums)):
                    adj[nums[i]][nums[j]] += 1
                    adj[nums[j]][nums[i]] += 1
        return adj

    # ── 학습 ─────────────────────────────────────────────────────────────────
    def train(self, draws: list, fine_tune: bool = True):
        # G-6: 재현성 seed 적용
        from validation.seed_utils import set_global_seed
        set_global_seed()

        print("  [GNN] Graph Attention Network 학습 시작...")
        draws_sorted = sorted(draws, key=lambda x: x["round"])

        # 인접 행렬 업데이트 및 저장
        new_counts = self._build_adj_counts_from_draws(draws_sorted)
        if fine_tune:
            new_counts += self._adj_counts   # 기존 카운트에 누적
        self._adj_counts = new_counts
        self._save_adjacency_counts()

        # ── 학습 샘플 생성 ──────────────────────────────────────────────────
        # 각 회차 i에 대해: 이전 i회 이력으로 피처 계산, i번째 회차 번호를 정답으로 사용
        # 공유 인접 행렬(전체 이력)을 사용하여 속도 최적화
        adj_norm   = self._normalize_adjacency(self._adj_counts)
        adj_tensor = torch.FloatTensor(adj_norm).to(self.device)

        # ── 1단계: raw feature 수집 (정규화 fit 위해) ─────────────────────
        raw_feat_list = []
        label_list    = []
        for i in range(MIN_HIST, len(draws_sorted)):
            hist  = draws_sorted[:i]
            raw   = self._build_features_raw(hist)
            label = np.zeros(45, dtype=np.float32)
            for num in draws_sorted[i].get("numbers", []):
                if 1 <= num <= 45:
                    label[num - 1] = 1.0
            raw_feat_list.append(raw)
            label_list.append(label)

        if not raw_feat_list:
            print("  [GNN] 학습 데이터 부족 (이력 < 50 회차)")
            return

        n_samples = len(raw_feat_list)
        print(f"  [GNN] 학습 샘플 수: {n_samples}")

        # ── G-7-D: PowerTransformer fit (모든 train 샘플의 long-tail 컬럼만) ─
        if FEATURE_NORMALIZE and _SKLEARN_OK:
            stacked = np.vstack([f[:, FEATURE_NORMALIZE_IDX] for f in raw_feat_list])
            self._feature_transformer = PowerTransformer(
                method="yeo-johnson", standardize=True
            )
            self._feature_transformer.fit(stacked)
            self._save_feature_transformer()
            print(f"  [GNN] PowerTransformer fit 완료 ({stacked.shape[0]} rows × "
                  f"{len(FEATURE_NORMALIZE_IDX)} cols)")
        elif FEATURE_NORMALIZE and not _SKLEARN_OK:
            print("  [GNN] sklearn 미설치 → raw feature 사용")

        # ── 2단계: 정규화 적용 후 텐서 변환 ───────────────────────────────
        feat_list = [self._apply_feature_transform(f) for f in raw_feat_list]
        feat_tensors  = [torch.FloatTensor(f).to(self.device) for f in feat_list]
        label_tensors = [torch.FloatTensor(l).to(self.device) for l in label_list]

        # ── 파인튜닝: 기존 가중치 로드 ────────────────────────────────────
        # [v2] Top-K sparse 그래프 구조 변경으로 기존 Dense-학습 가중치는 무효
        #      → force_retrain 플래그 파일이 있으면 기존 모델 삭제 후 처음부터 학습
        model_path  = os.path.join(self.save_dir, "gnn_model.pt")
        retrain_flag = os.path.join(self.save_dir, "gnn_force_retrain.flag")
        if os.path.exists(retrain_flag):
            if os.path.exists(model_path):
                os.remove(model_path)
                print("  [GNN] force_retrain 플래그 감지 → 기존 모델 삭제, 처음부터 학습")
            os.remove(retrain_flag)
            fine_tune = False  # 처음부터 학습

        if fine_tune and os.path.exists(model_path):
            try:
                self.model.load_state_dict(
                    torch.load(model_path, map_location=self.device,
                               weights_only=True)
                )
                print("  [GNN] 기존 모델 가중치 불러옴 (파인튜닝)")
            except Exception as e:
                print(f"  [GNN] 기존 가중치 로드 실패 (처음부터 학습): {e}")

        # ── 옵티마이저 & 손실 (G-7-A) ─────────────────────────────────────
        # SoftmaxRankingLoss + 0.3 × BCEWithLogitsLoss(pos_weight=6.5)
        # — Softmax 단독 → BCE 보조로 logit 안정화, mode collapse 추가 방어
        criterion = CombinedGNNLoss(
            bce_weight=BCE_AUX_WEIGHT, pos_weight=POS_WEIGHT, device=self.device
        )
        optimizer = optim.Adam(
            self.model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY
        )
        scheduler = optim.lr_scheduler.ReduceLROnPlateau(
            optimizer, mode="min", patience=8, factor=0.5, min_lr=1e-5
        )

        best_loss    = float("inf")
        patience_cnt = 0
        best_state   = None
        indices      = list(range(n_samples))

        # ── 학습 루프 ─────────────────────────────────────────────────────
        self.model.train()
        for epoch in range(MAX_EPOCHS):
            np.random.shuffle(indices)
            epoch_loss = 0.0

            for idx in indices:
                optimizer.zero_grad()
                logits = self.model(feat_tensors[idx], adj_tensor)
                loss   = criterion(logits, label_tensors[idx])
                loss.backward()
                nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=1.0)
                optimizer.step()
                epoch_loss += loss.item()

            avg_loss = epoch_loss / n_samples
            scheduler.step(avg_loss)

            if avg_loss < best_loss - 1e-5:
                best_loss    = avg_loss
                patience_cnt = 0
                best_state   = {k: v.clone()
                                for k, v in self.model.state_dict().items()}
            else:
                patience_cnt += 1

            if (epoch + 1) % 25 == 0:
                lr_now = optimizer.param_groups[0]["lr"]
                print(
                    f"  [GNN] Epoch {epoch+1:3d}/{MAX_EPOCHS}  "
                    f"loss={avg_loss:.4f}  lr={lr_now:.1e}  "
                    f"patience={patience_cnt}/{PATIENCE}"
                )

            if patience_cnt >= PATIENCE:
                print(f"  [GNN] Early stopping at epoch {epoch + 1}")
                break

        # 최적 가중치 복원 & 저장
        if best_state is not None:
            self.model.load_state_dict(best_state)
        torch.save(self.model.state_dict(), model_path)
        print(f"  [GNN] 학습 완료 → best_loss={best_loss:.4f}  "
              f"저장: {model_path}")

    # ── 예측 ─────────────────────────────────────────────────────────────────
    def predict(self, draws: list) -> dict:
        model_path = os.path.join(self.save_dir, "gnn_model.pt")

        # 모델 파일 또는 이력 부족 시 균등 확률 반환
        if not os.path.exists(model_path) or len(draws) < 5:
            return {n: 1.0 / 45.0 for n in range(1, 46)}

        # 모델 로드
        try:
            self.model.load_state_dict(
                torch.load(model_path, map_location=self.device,
                           weights_only=True)
            )
        except Exception:
            return {n: 1.0 / 45.0 for n in range(1, 46)}

        self.model.eval()

        draws_sorted = sorted(draws, key=lambda x: x["round"])
        recent       = draws_sorted[-100:]   # 최근 100회차로 피처 계산

        adj_norm = self._normalize_adjacency(self._adj_counts)
        raw_feats = self._build_features_raw(recent)
        feats     = self._apply_feature_transform(raw_feats)   # G-7-D

        x   = torch.FloatTensor(feats).to(self.device)
        adj = torch.FloatTensor(adj_norm).to(self.device)

        with torch.no_grad():
            logits = self.model(x, adj)                        # [45]
            probs  = torch.sigmoid(logits).cpu().numpy()       # [45]

        # 합이 1이 되도록 정규화
        total = probs.sum()
        if total > 0:
            probs = probs / total
        else:
            probs = np.ones(45) / 45.0

        return {n: float(probs[n - 1]) for n in range(1, 46)}

    # ── P6: 관계형 필터 전용 분석 ────────────────────────────────────────────
    def predict_edge_prob(self, draws: list) -> dict:
        """
        GNN 관계 특화 메서드 — 연속/인접 번호 공동출현 확률(관계형 필터) 전용.

        Returns (G-7-E 적용):
            {
              "node_probs"        : {1~45: float}     — 번호별 노드 확률
              "consecutive_probs" : {n: float, ...}   — P(n, n+1 동반) ≈ geo-mean conditional
              "top_pairs"         : [(i,j,prob), ...]  — 상위 20 동반쌍 (확률 내림차순)
              "attention_weights" : [[45×45 float]]   — 인접 행렬 log proxy (구조 정보)
              "gat_layer1_attn"   : [[heads, 45, 45]] — G-7-E: GAT layer-1 학습된 attention
                                                          (모델 미로드 시 None)
              "edge_density"      : float             — 실제화 엣지 밀도
            }
        """
        node_probs = self.predict(draws)          # {1~45: float}

        # ── 1. 조건부 동반 출현 확률 계산 ────────────────────────────────
        # P(j 출현 | i 출현) ≈ adj_counts[i,j] / row_sum[i]
        counts = self._adj_counts.copy()          # (45, 45)
        row_sum = counts.sum(axis=1)              # (45,)
        with np.errstate(divide="ignore", invalid="ignore"):
            cond_adj = np.where(
                row_sum[:, None] > 0,
                counts / row_sum[:, None],
                0.0,
            ).astype(np.float32)                  # P(j|i)

        # 엣지 확률 = 두 노드 조건부 확률의 기하평균 × 노드 확률 평균
        # edge_prob(i,j) = sqrt(P(j|i)·P(i|j)) × (p_i + p_j)/2
        edge_probs_full = np.sqrt(
            cond_adj * cond_adj.T + 1e-12
        )  # (45,45) symmetric geo-mean conditional

        # ── 2. 연속 번호쌍 (n, n+1) ──────────────────────────────────────
        consecutive_probs = {}
        for n in range(1, 45):                    # 1-44 → (n, n+1)
            i, j = n - 1, n                       # 0-indexed
            geo = float(edge_probs_full[i, j])
            p_avg = (node_probs.get(n, 0.0) + node_probs.get(n + 1, 0.0)) / 2.0
            consecutive_probs[n] = round(geo * p_avg * 10.0, 6)  # ×10 scale

        # ── 3. 상위 20 동반쌍 ────────────────────────────────────────────
        pair_list = []
        for i in range(45):
            for j in range(i + 1, 45):
                geo = float(edge_probs_full[i, j])
                p_avg = (node_probs.get(i + 1, 0.0) + node_probs.get(j + 1, 0.0)) / 2.0
                pair_list.append((i + 1, j + 1, round(geo * p_avg * 10.0, 6)))
        pair_list.sort(key=lambda x: x[2], reverse=True)
        top_pairs = pair_list[:20]

        # ── 4. 어텐션 가중치 (정규화 인접 행렬을 proxy로 사용) ─────────────
        adj_norm = self._normalize_adjacency(counts)
        # 값이 너무 작으므로 log 스케일로 변환해서 보기 편하게
        attn_proxy = np.log1p(adj_norm * 100).tolist()  # (45,45)

        # ── G-7-E: GAT layer-1 학습된 attention 추출 ─────────────────────
        gat_layer1_attn = None
        model_path = os.path.join(self.save_dir, "gnn_model.pt")
        if os.path.exists(model_path) and len(draws) >= 5:
            try:
                # 최근 100회로 피처 빌드
                draws_sorted = sorted(draws, key=lambda x: x["round"])
                recent       = draws_sorted[-100:]
                raw_feats    = self._build_features_raw(recent)
                feats        = self._apply_feature_transform(raw_feats)
                x   = torch.FloatTensor(feats).to(self.device)
                adj_t = torch.FloatTensor(adj_norm).to(self.device)
                self.model.eval()
                with torch.no_grad():
                    _, attn = self.model(x, adj_t, return_attention=True)
                # attn shape: [n_heads_1, 45, 45]
                gat_layer1_attn = attn.cpu().numpy().tolist()
            except Exception as e:
                # smoke test 환경 등에서는 None
                gat_layer1_attn = None

        # ── 5. 엣지 밀도 계산 ────────────────────────────────────────────
        threshold = float(np.percentile(counts[counts > 0], 75)) if counts.max() > 0 else 1.0
        strong_edges = int((counts > threshold).sum()) // 2   # symmetric → /2
        max_edges    = 45 * 44 // 2
        edge_density = round(strong_edges / max_edges, 4)

        return {
            "node_probs":         node_probs,
            "consecutive_probs":  consecutive_probs,
            "top_pairs":          top_pairs,
            "attention_weights":  attn_proxy,
            "gat_layer1_attn":    gat_layer1_attn,
            "edge_density":       edge_density,
        }
