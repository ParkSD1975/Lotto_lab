"""
LottoGNN – Graph Attention Network (순수 PyTorch, 외부 라이브러리 불필요)

아키텍처:
  Node: 45개 번호 (1~45)
  Edge: 동반출현 횟수로 가중치 부여 (symmetric)
  Node feature: 10차원 (출현빈도 3개 윈도우, GAP 3개, 핫스트릭, 홀짝, 고저, 정규화 번호값)
  GAT Layer 1: 10 → 64  (4-head)
  GAT Layer 2: 64 → 32  (2-head)
  Classifier:  32 → 32 → 1  (per-node 출현 로짓)
  Loss: BCEWithLogitsLoss (pos_weight=6.5, 6양성/39음성 보정)
"""

import os
import json
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import config

# ── 하이퍼파라미터 ────────────────────────────────────────────────────────────
NODE_FEAT_DIM = 10
HIDDEN_DIM    = 64
N_HEADS_1     = 4
N_HEADS_2     = 2
DROPOUT       = 0.3
LEARNING_RATE = 1e-3
MAX_EPOCHS    = 200
PATIENCE      = 25
MIN_HIST      = 50      # 학습 샘플 생성을 위한 최소 이력 회차
POS_WEIGHT    = 6.5     # 6개 양성 / 39개 음성 불균형 보정


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

    def forward(self, h: torch.Tensor, adj: torch.Tensor) -> torch.Tensor:
        N   = h.size(0)                          # 45
        Wh  = self.W(h)                          # [N, out_dim]
        Wh3 = Wh.view(N, self.n_heads, self.head_dim)  # [N, H, D]

        head_outs = []
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
            alpha = self.dropout(alpha)

            head_outs.append(alpha @ wh_k)      # [N, D]

        out = torch.cat(head_outs, dim=-1)       # [N, out_dim]
        out = F.elu(out)
        out = self.layer_norm(out)
        return out


# ── GNN 모델 ──────────────────────────────────────────────────────────────────
class LottoGNNModel(nn.Module):
    """2-layer Graph Attention Network + per-node 분류기"""

    def __init__(self):
        super().__init__()
        self.gat1 = GraphAttentionLayer(
            NODE_FEAT_DIM, HIDDEN_DIM,    N_HEADS_1, DROPOUT
        )
        self.gat2 = GraphAttentionLayer(
            HIDDEN_DIM,   HIDDEN_DIM // 2, N_HEADS_2, DROPOUT * 0.7
        )
        self.classifier = nn.Sequential(
            nn.Linear(HIDDEN_DIM // 2, 32),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(32, 1),
        )

    def forward(self, x: torch.Tensor, adj: torch.Tensor) -> torch.Tensor:
        """
        x   : [45, NODE_FEAT_DIM]
        adj : [45, 45]  (정규화 인접 행렬)
        반환 : [45]  per-node 로짓 (sigmoid 적용 전)
        """
        h = self.gat1(x, adj)                     # [45, HIDDEN_DIM]
        h = self.gat2(h, adj)                     # [45, HIDDEN_DIM//2]
        return self.classifier(h).squeeze(-1)     # [45]


# ── GNNTrainer ────────────────────────────────────────────────────────────────
class GNNTrainer:
    def __init__(self):
        self.device   = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.save_dir = config.MODEL_DIR
        os.makedirs(self.save_dir, exist_ok=True)
        self.model       = LottoGNNModel().to(self.device)
        self._adj_counts = np.zeros((45, 45), dtype=np.float32)
        self._load_adjacency_counts()

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

    # ── 그래프 / 피처 구성 ───────────────────────────────────────────────────
    @staticmethod
    def _normalize_adjacency(adj_counts: np.ndarray, top_k: int = 10) -> np.ndarray:
        """
        원시 동반출현 카운트 행렬 → Top-K 희소 대칭 정규화 인접 행렬

        [Over-smoothing 방지]
        로또 그래프는 1200+회차로 인해 45개 노드가 거의 완전 연결(dense).
        Dense graph에서 2-layer GAT를 통과하면 모든 노드 표현이 평균화되어
        균일 예측(uniform)으로 수렴한다 → top_k 이웃만 남겨 희소화.

        top_k=10: 각 번호는 동반출현 횟수 상위 10개 번호하고만 연결.
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
    def _build_features(draws: list) -> np.ndarray:
        """
        히스토리 draws → 노드 피처 행렬 [45, NODE_FEAT_DIM]

        피처 구성 (인덱스 0~9):
          0  freq_10   : 최근 10회차 출현율
          1  freq_20   : 최근 20회차 출현율
          2  freq_50   : 최근 50회차 출현율
          3  cur_gap   : 현재 GAP (정규화, 0~1)
          4  avg_gap   : 평균 GAP (정규화)
          5  gap_dev   : (현재-평균)/평균 편차 (클립 -1~1)
          6  hot_streak: 연속 출현 길이 (정규화)
          7  odd        : 홀수=1, 짝수=0
          8  low        : 1~22=1, 23~45=0
          9  pos_norm   : (번호-1)/44
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

        feat_list  = []
        label_list = []
        for i in range(MIN_HIST, len(draws_sorted)):
            hist  = draws_sorted[:i]
            feats = self._build_features(hist)
            label = np.zeros(45, dtype=np.float32)
            for num in draws_sorted[i].get("numbers", []):
                if 1 <= num <= 45:
                    label[num - 1] = 1.0
            feat_list.append(feats)
            label_list.append(label)

        if not feat_list:
            print("  [GNN] 학습 데이터 부족 (이력 < 50 회차)")
            return

        n_samples = len(feat_list)
        print(f"  [GNN] 학습 샘플 수: {n_samples}")

        # GPU/CPU 텐서 사전 변환
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

        # ── 옵티마이저 & 손실 ──────────────────────────────────────────────
        pos_weight = torch.tensor([POS_WEIGHT], device=self.device)
        criterion  = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
        optimizer  = optim.Adam(
            self.model.parameters(), lr=LEARNING_RATE, weight_decay=1e-4
        )
        scheduler  = optim.lr_scheduler.ReduceLROnPlateau(
            optimizer, mode="min", patience=10, factor=0.5, min_lr=1e-5
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
        feats    = self._build_features(recent)

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

        Returns:
            {
              "node_probs"        : {1~45: float}     — 번호별 노드 확률
              "consecutive_probs" : {n: float, ...}   — P(n, n+1 동반) ≈ geo-mean conditional
              "top_pairs"         : [(i,j,prob), ...]  — 상위 20 동반쌍 (확률 내림차순)
              "attention_weights" : [[45×45 float]]   — GAT layer-1 어텐션 (proxy)
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
            "edge_density":       edge_density,
        }
