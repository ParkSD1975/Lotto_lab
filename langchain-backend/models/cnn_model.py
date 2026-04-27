"""2D-CNN 모델 - 로또 용지(7x7 그리드) 공간 패턴 및 주변수 분석 기반 번호 출현 확률 예측.
시간의 흐름(최근 N회차)을 채널(Channel)로 쌓고, 3x3 Conv2d 필터가 '주변수' 패턴을 추출합니다.
"""

import os
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset
import config
# G-1: FocalLoss 폐기. BCEWithLogitsLoss + pos_weight 단일 보정으로 변경.

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

    def train(self, draws: list, fine_tune: bool = True) -> dict:
        # G-6: 재현성 seed 적용
        from validation.seed_utils import set_global_seed
        set_global_seed()

        dataset = LottoGridSequenceDataset(draws, seq_len=config.CNN_SEQ_LEN)
        if len(dataset) < 100: return {"success": False, "error": "데이터 부족"}
        
        train_loader = DataLoader(dataset, batch_size=config.CNN_BATCH_SIZE, shuffle=True)
        self.model = LottoCNN2D().to(self.device)

        if fine_tune:
            path = os.path.join(config.MODEL_DIR, "cnn_model.pt")
            if os.path.exists(path):
                try:
                    self.model.load_state_dict(torch.load(path, map_location=self.device, weights_only=True))
                    print("  [CNN] 기존 뇌(.pt) 가중치를 성공적으로 불러와 파인튜닝을 시작합니다.")
                except Exception as e:
                    print(f"  [CNN] 구 버전 가중치 호환 불가, 초기 상태에서 학습합니다: {e}")
            else:
                print("  [CNN] 기존 뇌가 없어 초기 상태에서 학습합니다.")

        # G-1: BCEWithLogitsLoss + pos_weight 단일 보정 (Focal Loss 폐기)
        criterion = nn.BCEWithLogitsLoss(pos_weight=torch.full([45], config.LSTM_POS_WEIGHT, device=self.device))
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
        if self.model is None: return {n: 1.0/45.0 + float(np.random.rand() * 0.0001) for n in range(1, 46)}
        
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

    # ── P6: 공간형 필터 전용 분석 ────────────────────────────────────────────
    def predict_spatial_pool(self, draws: list) -> dict:
        """
        CNN 공간 특화 메서드 — 공간형 필터(행/열/번호대/9궁)에 최적화.

        Returns:
            {
              "number_probs"  : {1~45: float}   — 번호별 확률
              "row_probs"     : {0~6: float}    — 7×7 그리드 행별 확률 합
              "col_probs"     : {0~6: float}    — 7×7 그리드 열별 확률 합
              "zone_probs"    : {"1-9":f, "10-19":f, "20-29":f,
                                 "30-39":f, "40-45":f}
              "ninezone_probs": {0~8: float}    — 9궁(3×3 블록) 구역별 확률
              "feature_map"   : [[7×7 float]]   — conv 활성화 맵 (정규화)
              "spatial_leader": str             — 활성화 가장 강한 번호대/행/열
            }
        """
        number_probs = self.predict(draws)  # {1~45: float}

        # ── 1. 그리드 입력 구성 ────────────────────────────────────────────
        recent = list(reversed(draws[:config.CNN_SEQ_LEN]))
        grid_seq = np.zeros((config.CNN_SEQ_LEN, 7, 7), dtype=np.float32)
        for t, d in enumerate(recent):
            for num in d.get("numbers", []):
                if 1 <= num <= 45:
                    r, c = (num - 1) // 7, (num - 1) % 7
                    grid_seq[t, r, c] = 1.0

        # ── 2. conv 특징맵 추출 ────────────────────────────────────────────
        feature_map_raw = None
        if self.model is not None:
            if self.model is None:
                self._load_model()
            self.model.eval()
            x = torch.FloatTensor(np.array([grid_seq])).to(self.device)
            with torch.no_grad():
                h1 = self.model.conv_block1(x)   # (1, F1, 7, 7)
                h2 = self.model.conv_block2(h1)  # (1, F2, 7, 7)
                # 채널 평균 → 공간 활성화 맵
                act = h2.mean(dim=1).squeeze(0)  # (7, 7)
                act_min, act_max = act.min(), act.max()
                if act_max > act_min:
                    act = (act - act_min) / (act_max - act_min)
                feature_map_raw = act.cpu().numpy()   # (7, 7)

        # ── 3. 번호 확률 기반 공간 집계 ──────────────────────────────────
        row_probs  = {}
        col_probs  = {}
        for r in range(7):
            row_nums = [r * 7 + c + 1 for c in range(7) if r * 7 + c + 1 <= 45]
            row_probs[r] = round(sum(number_probs.get(n, 0.0) for n in row_nums), 6)
        for c in range(7):
            col_nums = [r * 7 + c + 1 for r in range(7) if r * 7 + c + 1 <= 45]
            col_probs[c] = round(sum(number_probs.get(n, 0.0) for n in col_nums), 6)

        # 번호대 (10단위)
        zone_ranges = {
            "1-9":   range(1, 10),
            "10-19": range(10, 20),
            "20-29": range(20, 30),
            "30-39": range(30, 40),
            "40-45": range(40, 46),
        }
        zone_probs = {
            z: round(sum(number_probs.get(n, 0.0) for n in rng), 6)
            for z, rng in zone_ranges.items()
        }

        # 9궁 구역 (7×7 그리드를 3×3 블록으로 분할)
        # 블록 경계: 행 0-2/3-4/5-6, 열 0-2/3-4/5-6
        BLOCK_BOUNDS = [(0, 2), (3, 4), (5, 6)]
        ninezone_probs = {}
        for bi, (r0, r1) in enumerate(BLOCK_BOUNDS):
            for bj, (c0, c1) in enumerate(BLOCK_BOUNDS):
                zone_idx = bi * 3 + bj
                zone_nums = []
                for r in range(r0, r1 + 1):
                    for c in range(c0, c1 + 1):
                        n = r * 7 + c + 1
                        if 1 <= n <= 45:
                            zone_nums.append(n)
                ninezone_probs[zone_idx] = round(
                    sum(number_probs.get(n, 0.0) for n in zone_nums), 6
                )

        # ── 4. 특징맵 가중 보정 ───────────────────────────────────────────
        # feature_map이 있으면 행/열 활성화 평균값으로 row/col_probs를 살짝 보정 (10%)
        if feature_map_raw is not None:
            fm = feature_map_raw
            row_act = fm.mean(axis=1)   # (7,)
            col_act = fm.mean(axis=0)   # (7,)
            row_act_n = row_act / (row_act.sum() + 1e-9)
            col_act_n = col_act / (col_act.sum() + 1e-9)
            for r in range(7):
                row_probs[r] = round(row_probs[r] * 0.9 + row_act_n[r] * 0.1, 6)
            for c in range(7):
                col_probs[c] = round(col_probs[c] * 0.9 + col_act_n[c] * 0.1, 6)

        # 가장 활성화된 공간 영역 식별
        best_zone = max(zone_probs, key=zone_probs.get)
        best_row  = max(row_probs,  key=row_probs.get)
        spatial_leader = f"번호대 {best_zone} (row {best_row}행)"

        return {
            "number_probs":   number_probs,
            "row_probs":      row_probs,
            "col_probs":      col_probs,
            "zone_probs":     zone_probs,
            "ninezone_probs": ninezone_probs,
            "feature_map":    feature_map_raw.tolist() if feature_map_raw is not None else None,
            "spatial_leader": spatial_leader,
        }

    def _save_model(self):
        if self.model: torch.save(self.model.state_dict(), os.path.join(config.MODEL_DIR, "cnn_model.pt"))
    def _load_model(self):
        path = os.path.join(config.MODEL_DIR, "cnn_model.pt")
        if os.path.exists(path):
            try:
                self.model = LottoCNN2D().to(self.device)
                self.model.load_state_dict(torch.load(path, map_location=self.device, weights_only=True))
            except Exception as e:
                print(f"⚠️ [CNN] 구 버전 가중치 호환 불가 → 삭제 후 재학습 필요: {e}")
                self.model = None
                # 호환 불가 체크포인트 삭제 → 다음 학습 시 새 아키텍처로 저장
                try:
                    os.remove(path)
                    print(f"🗑️ [CNN] 구 버전 체크포인트 삭제 완료: {path}")
                except Exception:
                    pass
