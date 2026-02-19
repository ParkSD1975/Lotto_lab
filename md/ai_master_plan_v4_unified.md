# 🧠 Lotto AI Master Plan v4.0 — 통합 설계서

**작성일**: 2026-02-07
**기반 문서**: ai_master_plan_v3_supplement.md + DB 현황 분석 + LangChain/RAG 신규 설계
**목적**: 딥러닝 예측 시스템 + LangChain/RAG 지능형 분석의 완전한 통합 아키텍처

---

## 📋 문서 구조

| 장 | 내용 | 상태 |
|----|------|------|
| 1장 | 전체 아키텍처 (Layer Map) | v3 보강 |
| 2장 | 딥러닝 모델 상세 설계 (LSTM + XGBoost + 마르코프) | **신규** |
| 3장 | 앙상블 엔진 + 동적 가중치 | **신규** |
| 4장 | 피처 엔지니어링 완전판 | v3 보강 |
| 5장 | LangChain/RAG 통합 레이어 | **신규** |
| 6장 | 데이터베이스 스키마 완전판 | v3 보강 |
| 7장 | 데이터 파이프라인 (7단계) | v3 보강 |
| 8장 | 프론트엔드 통합 (AIContextManager + 챗봇 + 위젯) | **신규** |
| 9장 | 성능 모니터링 + 설명 가능한 AI | **신규** |
| 10장 | 개발 로드맵 | 재수립 |

---

## 1장. 전체 아키텍처

### 1.1 시스템 레이어 맵

```
╔═════════════════════════════════════════════════════════════════════════════╗
║                         USER INTERFACE (Browser)                           ║
╠═════════════════════════════════════════════════════════════════════════════╣
║                                                                            ║
║  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌─────────────────┐   ║
║  │ 32개 분석    │ │ AI Dashboard │ │ Custom       │ │ 조합 생성기    │   ║
║  │ HTML 페이지  │ │  .html       │ │ Analysis     │ │ (Generation)    │   ║
║  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘ └────────┬────────┘   ║
║         └────────────────┴────────┬───────┴──────────────────┘            ║
║                                   ▼                                        ║
║  ┌────────────────────────────────────────────────────────────────────┐    ║
║  │                   FRONTEND SERVICE LAYER                           │    ║
║  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────┐ │    ║
║  │  │AIContext     │ │FilterService │ │ChatbotWidget │ │AIProxy   │ │    ║
║  │  │Manager.js   │ │.js           │ │.js           │ │.js       │ │    ║
║  │  └──────────────┘ └──────────────┘ └──────────────┘ └──────────┘ │    ║
║  └────────────────────────┬───────────────────────────────────────────┘    ║
╠════════════════════════════╪════════════════════════════════════════════════╣
║                            │ REST API + WebSocket                          ║
║                            ▼                                               ║
║  ┌─────────────────────────────────────────────────────────────────────┐   ║
║  │                    SUPABASE LAYER (PostgreSQL + Edge Functions)      │   ║
║  │                                                                      │   ║
║  │  Edge Functions:                   Database (10+ Tables):            │   ║
║  │  ┌──────────────┐                 ┌──────────────────────┐          │   ║
║  │  │analyze-lotto │                 │ lotto_draws          │          │   ║
║  │  │(Gemini LLM)  │                 │ ai_predictions       │          │   ║
║  │  ├──────────────┤                 │ stats_summary        │          │   ║
║  │  │generate-     │                 │ ai_custom_analyses   │          │   ║
║  │  │prediction    │                 │ analysis_history     │          │   ║
║  │  │(새 AI 예측)  │                 │ filter_definitions   │          │   ║
║  │  ├──────────────┤                 │ filter_settings      │          │   ║
║  │  │evaluate-     │                 │ user_filter_presets   │          │   ║
║  │  │rules         │                 │ number_round_stats   │          │   ║
║  │  └──────────────┘                 │ regression_details   │          │   ║
║  │                                    │ model_performance_log│          │   ║
║  │                                    └──────────────────────┘          │   ║
║  └─────────────────────────────────────────────────────────────────────┘   ║
╠═══════════════════════════════════════════════════════════════════════════╣
║                                                                            ║
║  ┌─────────────────────────────────────────────────────────────────────┐   ║
║  │              PYTHON AI LAYER (FastAPI + LangChain)                   │   ║
║  │                                                                      │   ║
║  │  ┌─────────────────┐ ┌─────────────────┐ ┌──────────────────────┐  │   ║
║  │  │  Deep Learning  │ │  LangChain/RAG  │ │  Report Generator   │  │   ║
║  │  │  Engine         │ │  Engine          │ │                      │  │   ║
║  │  │                 │ │                  │ │  • 주간 보고서       │  │   ║
║  │  │  • LSTM Model   │ │  • ChromaDB      │ │  • 모델 성능 리포트 │  │   ║
║  │  │  • XGBoost      │ │  • RAG Retriever │ │  • 트렌드 분석      │  │   ║
║  │  │  • Markov Chain │ │  • Chat Chain    │ │                      │  │   ║
║  │  │  • Ensemble     │ │  • Analysis Chain│ │                      │  │   ║
║  │  └────────┬────────┘ └────────┬─────────┘ └──────────┬───────────┘  │   ║
║  │           │                   │                       │              │   ║
║  │           └───────────────────┴───────────────────────┘              │   ║
║  │                        ↕ Supabase Python Client                      │   ║
║  └─────────────────────────────────────────────────────────────────────┘   ║
║                                                                            ║
╚═════════════════════════════════════════════════════════════════════════════╝
```

### 1.2 역할 분담

| 레이어 | 역할 | 기술 |
|--------|------|------|
| **Supabase Edge Function** | 경량 LLM 호출 (Gemini), 실시간 분석 | Deno/TypeScript |
| **Python AI Layer** | 딥러닝 학습/예측, LangChain/RAG, 보고서 | FastAPI + PyTorch + LangChain |
| **Frontend** | UI 렌더링, 상태 관리, 사용자 인터랙션 | Vanilla JS + Tailwind |

### 1.3 핵심 데이터 흐름

```
[매주 토요일 추첨]
    │
    ▼
① lotto_draws INSERT (update_lotto.py)
    │
    ▼
② Python AI Layer: 딥러닝 예측 실행
    │  ├── LSTM → 시계열 확률
    │  ├── XGBoost → 피처 기반 확률
    │  ├── Markov → 전이 확률
    │  └── Ensemble → 최종 확률 (45개 번호)
    │
    ▼
③ ai_predictions INSERT (4가지 타입: exclusion/recommendation/filter/combination)
④ stats_summary UPDATE (45개 번호 × 통계)
⑤ 커스텀 룰 평가 → ai_custom_analyses.ai_evaluation UPDATE
    │
    ▼
⑥ RAG 벡터 인덱스 증분 업데이트 (ChromaDB)
    │
    ▼
⑦ LangChain → 주간 보고서 자동 생성
⑧ 이전 회차 예측 검증 → model_performance_log INSERT
    │
    ▼
⑨ 프론트엔드 실시간 갱신 (AIContextManager)
```

---

## 2장. 딥러닝 모델 상세 설계

### 2.1 Model A: LSTM (가중치 0.35)

#### 2.1.1 목적
시계열 순서 정보를 학습하여 "다음 회차에 각 번호가 출현할 확률"을 예측한다.
LSTM은 최근 N회차의 **출현 패턴 순서**를 기억하여 "연속 출현", "주기적 부활" 등의 시간적 패턴을 포착한다.

#### 2.1.2 입력 데이터 구조

```python
# 입력 형태: (batch_size, seq_len, feature_dim)
# seq_len = 30 (최근 30회차를 시퀀스로)
# feature_dim = 45 + 12 = 57

# 각 회차별 피처 벡터 (57차원):
features_per_round = {
    # 45차원: 각 번호의 출현 여부 (0 or 1)
    "number_occurrence": [0, 0, 1, 0, ..., 1, 0],  # 45개

    # 12차원: 해당 회차의 패턴 피처
    "total_sum_normalized": 0.62,         # 총합 / 255 (정규화)
    "odd_ratio": 0.67,                    # 홀수 비율 (4/6)
    "low_ratio": 0.50,                    # 저번호 비율 (3/6)
    "ac_value_normalized": 0.80,          # AC값 / 10
    "consecutive_pairs": 0.17,            # 연번 쌍 수 / 6
    "tail_sum_normalized": 0.51,          # 끝수합 / 45
    "prime_ratio": 0.33,                  # 소수 비율 (2/6)
    "carryover_count": 0.17,              # 이월수 / 6
    "sum_trend_5": 0.3,                   # 최근 5회 총합 변화율
    "gap_entropy": 0.72,                  # 번호별 Gap 엔트로피
    "hot_ratio": 0.45,                    # 최근 10회 내 2회+ 출현 비율
    "cold_ratio": 0.22,                   # 10회+ 미출현 비율
}
```

#### 2.1.3 네트워크 구조

```python
import torch
import torch.nn as nn

class LottoLSTM(nn.Module):
    """
    로또 번호 출현 확률 예측 LSTM

    Input: (batch, seq_len=30, features=57)
    Output: (batch, 45) — 각 번호의 출현 확률
    """
    def __init__(self, input_dim=57, hidden_dim=128, num_layers=2, dropout=0.3):
        super().__init__()

        # Bidirectional LSTM: 과거→미래 + 미래→과거 양방향 패턴 학습
        self.lstm = nn.LSTM(
            input_size=input_dim,
            hidden_size=hidden_dim,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout,
            bidirectional=True
        )

        # Attention 메커니즘: 어떤 회차가 예측에 중요한지 가중치
        self.attention = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.Tanh(),
            nn.Linear(hidden_dim, 1)
        )

        # 출력 레이어
        self.fc = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, 45),
            nn.Sigmoid()  # 각 번호별 0~1 확률
        )

    def forward(self, x):
        # x: (batch, 30, 57)
        lstm_out, _ = self.lstm(x)  # (batch, 30, 256)

        # Attention weights
        attn_weights = self.attention(lstm_out)  # (batch, 30, 1)
        attn_weights = torch.softmax(attn_weights, dim=1)

        # Weighted sum
        context = torch.sum(lstm_out * attn_weights, dim=1)  # (batch, 256)

        # Predict
        output = self.fc(context)  # (batch, 45)
        return output, attn_weights.squeeze(-1)  # attention도 반환 (설명용)
```

#### 2.1.4 학습 설정

```python
class LSTMTrainingConfig:
    # 데이터
    SEQ_LEN = 30                    # 최근 30회차를 시퀀스로
    MIN_TRAIN_ROUNDS = 500          # 최소 학습 데이터 (500회차 이상)
    VALIDATION_SPLIT = 0.15         # 최근 15%를 검증셋으로

    # 모델
    HIDDEN_DIM = 128
    NUM_LAYERS = 2
    DROPOUT = 0.3

    # 학습
    EPOCHS = 100
    BATCH_SIZE = 32
    LEARNING_RATE = 0.001
    WEIGHT_DECAY = 1e-5             # L2 정규화
    SCHEDULER = "CosineAnnealing"   # 학습률 스케줄러
    EARLY_STOPPING_PATIENCE = 15    # 15 에폭 개선 없으면 중단

    # 손실 함수
    LOSS = "BCELoss"                # Binary Cross Entropy (다중 레이블)
    POS_WEIGHT = 6.5                # 양성(출현) 가중치 (45개 중 6개만 양성이므로)

    # 랜덤 기준선
    RANDOM_BASELINE = 6 / 45        # 0.1333... (무작위 시 각 번호 출현 확률)
```

#### 2.1.5 Attention 시각화 (설명 가능한 AI)
```
LSTM Attention Weights 예시:
회차   Weight   의미
1198   0.15    ████████████████  ← 이 회차가 예측에 가장 큰 영향
1199   0.08    ████████
1200   0.12    ████████████      ← 직전 회차도 중요
1201   0.04    ████
...
→ "AI가 1198회차와 1200회차 패턴을 특히 중시하여 예측했습니다"
```

---

### 2.2 Model B: XGBoost (가중치 0.40)

#### 2.2.1 목적
풍부한 통계 피처를 기반으로 **각 번호의 출현 확률**을 이진 분류한다.
LSTM이 놓치는 비시계열적 특징(소수 여부, 끝수, 배수 관계 등)을 포착한다.

#### 2.2.2 학습 구조

```python
from xgboost import XGBClassifier
import numpy as np

class LottoXGBoost:
    """
    45개 번호에 대해 각각 독립적인 이진 분류 모델을 학습한다.
    (Multi-Label: 번호별로 "출현(1)/미출현(0)" 예측)
    """
    def __init__(self):
        self.models = {}      # {번호: XGBClassifier}
        self.importances = {} # {번호: feature_importance}

    def build_features_for_number(self, num, draws, round_idx):
        """
        특정 번호(num)에 대해 특정 시점(round_idx)까지의 피처를 생성한다.
        round_idx 시점에서 과거 데이터만 사용 (미래 정보 누출 방지).
        """
        history = draws[round_idx + 1:]  # round_idx 이전 데이터만

        # ── 번호 자체 피처 (15개) ──
        total_freq = sum(1 for d in history if num in d['numbers']) / len(history)
        recent_10_freq = sum(1 for d in history[:10] if num in d['numbers']) / 10
        recent_50_freq = sum(1 for d in history[:50] if num in d['numbers']) / min(50, len(history))

        current_gap = 0
        for d in history:
            if num in d['numbers']:
                break
            current_gap += 1

        gaps = []
        last_seen = -1
        for i, d in enumerate(history):
            if num in d['numbers']:
                if last_seen >= 0:
                    gaps.append(i - last_seen)
                last_seen = i

        avg_gap = np.mean(gaps) if gaps else len(history)
        max_gap = max(gaps) if gaps else len(history)
        std_gap = np.std(gaps) if len(gaps) > 1 else 0
        gap_percentile = current_gap / max_gap if max_gap > 0 else 0

        # 모멘텀: 최근 20회에서의 출현 가속도
        recent_20 = [1 if num in d['numbers'] else 0 for d in history[:20]]
        first_half = sum(recent_20[:10])
        second_half = sum(recent_20[10:])
        momentum = (first_half - second_half) / 10  # 양수 = 최근 상승세

        # 트렌드: 최근 50회 출현 간격의 기울기
        appear_indices = [i for i, d in enumerate(history[:50]) if num in d['numbers']]
        if len(appear_indices) >= 2:
            trend_slope = np.polyfit(range(len(appear_indices)), appear_indices, 1)[0]
        else:
            trend_slope = 0

        is_prime = 1 if num in {2,3,5,7,11,13,17,19,23,29,31,37,41,43} else 0
        is_odd = num % 2
        decade = (num - 1) // 10  # 0~4
        tail_digit = num % 10
        is_low = 1 if num <= 22 else 0

        # ── 패턴 피처 (12개) ──
        last_draw = history[0] if history else {'numbers': []}
        last_nums = sorted(last_draw.get('numbers', []))
        last_sum = sum(last_nums) if last_nums else 0
        last_odd = sum(1 for n in last_nums if n % 2 == 1)
        last_low = sum(1 for n in last_nums if n <= 22)
        last_ac = self._calc_ac(last_nums)
        last_consec = sum(1 for i in range(len(last_nums)-1) if last_nums[i+1]-last_nums[i]==1)
        last_tail_sum = sum(n % 10 for n in last_nums)

        # 최근 10회 평균들
        recent_sums = [sum(d['numbers']) for d in history[:10]]
        avg_sum = np.mean(recent_sums) if recent_sums else 130
        sum_std = np.std(recent_sums) if recent_sums else 0

        # 이월수 (직전 회차와 겹치는 번호)
        if len(history) >= 2:
            carryover = len(set(history[0]['numbers']) & set(history[1]['numbers']))
        else:
            carryover = 0

        # ── 동반 출현 피처 (5개) ──
        # 이 번호와 가장 자주 같이 나오는 번호와의 관계
        co_occur = {}
        for d in history[:200]:
            if num in d['numbers']:
                for other in d['numbers']:
                    if other != num:
                        co_occur[other] = co_occur.get(other, 0) + 1

        if co_occur:
            top_partner = max(co_occur.values())
            avg_partner = np.mean(list(co_occur.values()))
            partner_diversity = len(co_occur) / 44  # 얼마나 다양한 번호와 출현하는가
        else:
            top_partner = 0
            avg_partner = 0
            partner_diversity = 0

        # 같은 끝수 번호들의 최근 활성도
        same_tail_nums = [n for n in range(1, 46) if n % 10 == tail_digit and n != num]
        same_tail_recent = sum(
            1 for d in history[:10] for n in d['numbers'] if n in same_tail_nums
        ) / max(len(same_tail_nums) * 10, 1)

        # 같은 번호대의 최근 활성도
        same_decade_nums = [n for n in range(1, 46) if (n-1)//10 == decade and n != num]
        same_decade_recent = sum(
            1 for d in history[:10] for n in d['numbers'] if n in same_decade_nums
        ) / max(len(same_decade_nums) * 10, 1)

        return [
            # 번호 자체 (15개)
            total_freq, recent_10_freq, recent_50_freq,
            current_gap, avg_gap, max_gap, std_gap, gap_percentile,
            momentum, trend_slope,
            is_prime, is_odd, decade, tail_digit, is_low,
            # 패턴 (12개)
            last_sum / 255, last_odd / 6, last_low / 6,
            last_ac / 10, last_consec / 5, last_tail_sum / 45,
            avg_sum / 255, sum_std / 50, carryover / 6,
            recent_10_freq - total_freq,  # 최근 활성도 차이
            gap_percentile - 0.5,          # 평균 Gap 대비 현재 위치
            momentum,
            # 동반 출현 (5개)
            top_partner / max(len(history[:200]), 1),
            avg_partner / max(len(history[:200]), 1),
            partner_diversity,
            same_tail_recent,
            same_decade_recent,
        ]

    def _calc_ac(self, nums):
        if len(nums) < 2:
            return 0
        diffs = set()
        for i in range(len(nums)):
            for j in range(i+1, len(nums)):
                diffs.add(abs(nums[i] - nums[j]))
        return len(diffs) - (len(nums) - 1)

    def train(self, draws):
        """
        전체 데이터로 45개 모델을 학습한다.
        draws: round 내림차순 (최신 → 과거)
        """
        for num in range(1, 46):
            X, y = [], []

            # 시계열 분할: 가장 최근 100회는 제외 (검증용)
            for i in range(100, len(draws) - 30):
                features = self.build_features_for_number(num, draws, i)
                label = 1 if num in draws[i]['numbers'] else 0
                X.append(features)
                y.append(label)

            X = np.array(X)
            y = np.array(y)

            # 클래스 불균형 처리 (6/45 ≈ 13% 양성)
            scale_pos_weight = (len(y) - sum(y)) / max(sum(y), 1)

            model = XGBClassifier(
                n_estimators=200,
                max_depth=6,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                scale_pos_weight=scale_pos_weight,
                objective='binary:logistic',
                eval_metric='logloss',
                use_label_encoder=False,
                reg_alpha=0.1,       # L1 정규화
                reg_lambda=1.0,      # L2 정규화
                min_child_weight=5,  # 과적합 방지
            )

            model.fit(X, y)
            self.models[num] = model
            self.importances[num] = model.feature_importances_

            print(f"  번호 {num:2d} 학습 완료 | 양성 비율: {sum(y)/len(y):.3f}")

    def predict(self, draws):
        """현재 시점에서 다음 회차 예측"""
        probs = {}
        for num in range(1, 46):
            features = self.build_features_for_number(num, draws, 0)
            prob = self.models[num].predict_proba([features])[0][1]
            probs[num] = float(prob)
        return probs

    def get_top_features(self, num, top_k=5):
        """특정 번호 예측에 가장 중요한 피처 반환 (XAI)"""
        feature_names = [
            'total_freq', 'recent_10_freq', 'recent_50_freq',
            'current_gap', 'avg_gap', 'max_gap', 'std_gap', 'gap_percentile',
            'momentum', 'trend_slope',
            'is_prime', 'is_odd', 'decade', 'tail_digit', 'is_low',
            'last_sum', 'last_odd', 'last_low',
            'last_ac', 'last_consec', 'last_tail_sum',
            'avg_sum', 'sum_std', 'carryover',
            'freq_diff', 'gap_position', 'momentum_dup',
            'top_partner', 'avg_partner', 'partner_diversity',
            'same_tail_active', 'same_decade_active',
        ]
        importance = self.importances.get(num, [])
        if len(importance) == 0:
            return []
        ranked = sorted(zip(feature_names, importance), key=lambda x: x[1], reverse=True)
        return ranked[:top_k]
```

---

### 2.3 Model C: 마르코프 체인 (가중치 0.25)

#### 2.3.1 목적
번호 출현의 **전이 확률**을 계산한다. "이전 상태에서 다음 상태로의 전환 확률"을 기반으로 예측.

#### 2.3.2 상태 정의

```python
class MarkovLottoModel:
    """
    2차 마르코프 체인: 현재 Gap 상태 → 다음 회차 출현 확률

    각 번호에 대해 독립적인 마르코프 체인을 구성한다.
    상태: "현재 연속 미출현 횟수" (Gap)
    전이: Gap N → 출현(0) 또는 Gap N+1
    """

    def __init__(self):
        self.transition_matrices = {}  # {번호: {gap: {0: prob, 1: prob}}}

    def train(self, draws):
        """전이 확률 행렬을 구성한다."""
        for num in range(1, 46):
            transitions = {}  # {current_gap: {appeared: count, not_appeared: count}}

            current_gap = 0
            for i in range(len(draws) - 1, 0, -1):  # 과거→현재 순서
                appeared = 1 if num in draws[i-1]['numbers'] else 0

                if current_gap not in transitions:
                    transitions[current_gap] = {0: 0, 1: 0}
                transitions[current_gap][appeared] += 1

                if appeared:
                    current_gap = 0
                else:
                    current_gap += 1

            # 확률로 변환
            matrix = {}
            for gap, counts in transitions.items():
                total = counts[0] + counts[1]
                if total > 0:
                    matrix[gap] = {
                        'appear_prob': counts[1] / total,       # 이 Gap에서 출현할 확률
                        'continue_prob': counts[0] / total,     # 계속 미출현 확률
                        'sample_count': total                    # 통계적 신뢰도용
                    }

            self.transition_matrices[num] = matrix

    def predict(self, draws):
        """현재 각 번호의 Gap 상태에서 출현 확률을 계산한다."""
        probs = {}

        for num in range(1, 46):
            # 현재 Gap 계산
            current_gap = 0
            for d in draws:
                if num in d['numbers']:
                    break
                current_gap += 1

            matrix = self.transition_matrices.get(num, {})

            if current_gap in matrix:
                entry = matrix[current_gap]
                prob = entry['appear_prob']
                confidence = min(entry['sample_count'] / 20, 1.0)  # 샘플 20개 이상이면 신뢰
            else:
                # 관측되지 않은 Gap → 베이지안 사전확률 사용
                # Gap이 매우 크면 출현 확률 높게 (평균 회귀)
                avg_gap = self._calc_avg_gap(num, draws)
                prob = min(0.5 + (current_gap / avg_gap - 1) * 0.15, 0.95) if avg_gap > 0 else 0.133
                confidence = 0.3  # 낮은 신뢰도

            probs[num] = {
                'probability': float(prob),
                'current_gap': current_gap,
                'confidence': float(confidence),
                'reasoning': self._generate_reasoning(num, current_gap, prob, matrix)
            }

        return probs

    def _calc_avg_gap(self, num, draws):
        gaps = []
        last_seen = -1
        for i, d in enumerate(draws):
            if num in d['numbers']:
                if last_seen >= 0:
                    gaps.append(i - last_seen)
                last_seen = i
        return np.mean(gaps) if gaps else 7.5  # 기본값: 45/6

    def _generate_reasoning(self, num, current_gap, prob, matrix):
        """자연어 추론 생성 (LangChain에서 활용)"""
        if current_gap == 0:
            return f"번호 {num}은 직전 회차에 출현했으며, 연속 출현 확률은 {prob:.1%}입니다."

        avg_entry = matrix.get(current_gap, {})
        sample = avg_entry.get('sample_count', 0) if avg_entry else 0

        if prob > 0.3:
            return (f"번호 {num}은 {current_gap}회 연속 미출현 중이며, "
                    f"과거 동일 상황에서 출현 확률은 {prob:.1%}입니다 "
                    f"(근거 데이터: {sample}회).")
        else:
            return (f"번호 {num}은 {current_gap}회 미출현 중이지만, "
                    f"아직 평균 미출현 주기에 도달하지 않았습니다 (출현 확률: {prob:.1%}).")
```

---

## 3장. 앙상블 엔진 + 동적 가중치

### 3.1 앙상블 레이어

```python
class LottoEnsemble:
    """
    3개 모델의 예측을 가중 평균하여 최종 확률을 산출한다.
    가중치는 최근 성능에 따라 동적으로 조정된다.
    """

    def __init__(self):
        self.lstm = LottoLSTM()
        self.xgboost = LottoXGBoost()
        self.markov = MarkovLottoModel()

        # 초기 가중치 (마스터플랜 v3 기준)
        self.weights = {
            'lstm': 0.35,
            'xgboost': 0.40,
            'markov': 0.25
        }

        # 성능 이력
        self.performance_history = []

    def predict(self, draws, custom_rules=None):
        """앙상블 예측 실행"""
        # 1. 각 모델별 예측
        lstm_probs = self.lstm.predict(draws)        # {num: prob}
        xgb_probs = self.xgboost.predict(draws)     # {num: prob}
        markov_result = self.markov.predict(draws)   # {num: {probability, reasoning, ...}}
        markov_probs = {n: r['probability'] for n, r in markov_result.items()}

        # 2. 가중 앙상블
        final_probs = {}
        for num in range(1, 46):
            ensemble_prob = (
                self.weights['lstm'] * lstm_probs.get(num, 0) +
                self.weights['xgboost'] * xgb_probs.get(num, 0) +
                self.weights['markov'] * markov_probs.get(num, 0)
            )
            final_probs[num] = ensemble_prob

        # 3. 커스텀 룰 가중치 조정
        if custom_rules:
            final_probs = self._apply_custom_rule_adjustment(final_probs, custom_rules)

        # 4. 결과 분류
        sorted_nums = sorted(final_probs.items(), key=lambda x: x[1], reverse=True)

        return {
            'probabilities': final_probs,
            'recommended': [n for n, _ in sorted_nums[:10]],      # Top 10 추천수
            'excluded': [n for n, _ in sorted_nums[-10:]],         # Bottom 10 제외수
            'top_6': [n for n, _ in sorted_nums[:6]],              # 최고 확률 6개
            'model_contributions': {
                'lstm': lstm_probs,
                'xgboost': xgb_probs,
                'markov': markov_probs,
            },
            'markov_reasoning': {n: r['reasoning'] for n, r in markov_result.items()},
            'xgb_feature_importance': {
                n: self.xgboost.get_top_features(n, 3)
                for n in [n for n, _ in sorted_nums[:10]]  # 추천수 Top 10에 대해서만
            },
            'weights_used': dict(self.weights),
        }

    def _apply_custom_rule_adjustment(self, probs, custom_rules):
        """사용자 커스텀 룰 중 'Hot' 상태인 것의 가중치를 부여한다."""
        adjusted = dict(probs)

        for rule in custom_rules:
            eval_data = rule.get('ai_evaluation', {})
            if not eval_data.get('is_hot', False):
                continue
            if not eval_data.get('recommended_for_next', False):
                continue

            # 이 룰이 추천하는 번호들에 가중치 부여
            target_nums = rule.get('target_numbers', [])
            contribution = eval_data.get('contribution_to_ai', 0.1)

            for num in target_nums:
                if num in adjusted:
                    adjusted[num] *= (1 + contribution)

        return adjusted

    def update_weights(self, actual_numbers, predictions):
        """
        동적 가중치 조정: 최근 20회 성능에 따라 가중치를 재조정한다.
        actual_numbers: 실제 당첨 번호 리스트
        predictions: 이전에 생성한 predict() 결과
        """
        actual_set = set(actual_numbers)

        # 각 모델별 적중률 계산
        for model_name in ['lstm', 'xgboost', 'markov']:
            model_probs = predictions['model_contributions'][model_name]
            sorted_nums = sorted(model_probs.items(), key=lambda x: x[1], reverse=True)
            top_10 = set(n for n, _ in sorted_nums[:10])
            hits = len(top_10 & actual_set)

            self.performance_history.append({
                'model': model_name,
                'hits': hits,
                'max_possible': len(actual_set),
            })

        # 최근 20회 성능으로 가중치 재계산
        recent = self.performance_history[-60:]  # 20회 × 3모델

        model_scores = {'lstm': 0, 'xgboost': 0, 'markov': 0}
        model_counts = {'lstm': 0, 'xgboost': 0, 'markov': 0}

        for entry in recent:
            model_scores[entry['model']] += entry['hits']
            model_counts[entry['model']] += 1

        avg_scores = {}
        for m in model_scores:
            avg_scores[m] = model_scores[m] / max(model_counts[m], 1)

        total_score = sum(avg_scores.values())
        if total_score > 0:
            # Softmax-like 정규화 (극단적 변동 방지)
            for m in self.weights:
                raw_weight = avg_scores[m] / total_score
                # 이전 가중치와 블렌딩 (급격한 변화 방지: 70% 기존 + 30% 새 가중치)
                self.weights[m] = 0.7 * self.weights[m] + 0.3 * raw_weight

            # 최소 가중치 보장 (한 모델이 완전히 무시되지 않도록)
            MIN_WEIGHT = 0.10
            for m in self.weights:
                self.weights[m] = max(self.weights[m], MIN_WEIGHT)

            # 정규화 (합이 1이 되도록)
            total = sum(self.weights.values())
            for m in self.weights:
                self.weights[m] /= total
```

### 3.2 조합 생성기

```python
class CombinationGenerator:
    """앙상블 확률 + 필터 조건으로 최종 6개 번호 조합을 생성한다."""

    def generate(self, ensemble_result, filter_settings, n_combinations=5):
        """
        Monte Carlo 샘플링으로 필터를 통과하는 최적 조합을 생성한다.
        """
        probs = ensemble_result['probabilities']
        combinations = []
        attempts = 0
        max_attempts = 100000

        while len(combinations) < n_combinations and attempts < max_attempts:
            # 확률 기반 가중 랜덤 샘플링
            numbers = list(range(1, 46))
            weights = [probs.get(n, 0.02) for n in numbers]

            # 6개 번호 비복원 추출
            selected = self._weighted_sample(numbers, weights, 6)
            selected.sort()

            # 필터 통과 확인
            if self._passes_filters(selected, filter_settings):
                score = sum(probs[n] for n in selected)
                combinations.append({
                    'numbers': selected,
                    'score': round(score, 4),
                })

            attempts += 1

        # 점수 순 정렬
        combinations.sort(key=lambda x: x['score'], reverse=True)

        for i, combo in enumerate(combinations):
            combo['rank'] = i + 1

        return combinations[:n_combinations]

    def _weighted_sample(self, population, weights, k):
        """가중치 기반 비복원 추출"""
        import random
        result = []
        pop = list(population)
        w = list(weights)

        for _ in range(k):
            total = sum(w)
            r = random.uniform(0, total)
            cumulative = 0
            for i, weight in enumerate(w):
                cumulative += weight
                if cumulative >= r:
                    result.append(pop[i])
                    pop.pop(i)
                    w.pop(i)
                    break

        return result

    def _passes_filters(self, numbers, filters):
        """필터 조건 통과 여부"""
        if not filters:
            return True

        total_sum = sum(numbers)
        odd_count = sum(1 for n in numbers if n % 2 == 1)
        low_count = sum(1 for n in numbers if n <= 22)
        primes = {2,3,5,7,11,13,17,19,23,29,31,37,41,43}
        prime_count = sum(1 for n in numbers if n in primes)
        consec = sum(1 for i in range(len(numbers)-1) if numbers[i+1]-numbers[i]==1)

        # AC값
        diffs = set()
        for i in range(len(numbers)):
            for j in range(i+1, len(numbers)):
                diffs.add(abs(numbers[i]-numbers[j]))
        ac = len(diffs) - 5

        checks = {
            'sum_range': filters.get('sum_range') and (
                filters['sum_range']['min'] <= total_sum <= filters['sum_range']['max']
            ),
            'odd_count': filters.get('odd_count') and (
                filters['odd_count']['min'] <= odd_count <= filters['odd_count']['max']
            ),
            'low_count': filters.get('low_count') and (
                filters['low_count']['min'] <= low_count <= filters['low_count']['max']
            ),
            'ac_value': filters.get('ac_value') and (
                filters['ac_value']['min'] <= ac <= filters['ac_value']['max']
            ),
            'consecutive': filters.get('consecutive') and (
                consec <= filters['consecutive']['max']
            ),
        }

        # 설정된 필터만 검사 (None이면 통과)
        for key, result in checks.items():
            if result is not None and not result:
                return False

        return True
```

---

## 4장. 피처 엔지니어링 완전판

### 4.1 피처 카테고리 총정리

| 카테고리 | 피처 수 | 대상 모델 | 설명 |
|----------|---------|----------|------|
| 번호별 기본 통계 | 15 × 45 | XGBoost | 빈도, Gap, 트렌드, 속성 |
| 패턴 피처 | 12 | XGBoost, LSTM | 총합, 홀짝, AC값, 연번, 이월 |
| 동반 출현 | 5 × 45 | XGBoost | 번호 간 상관관계 |
| 시계열 시퀀스 | 30 × 57 | LSTM | 최근 30회 전체 상태 |
| Gap 전이 확률 | 1 × 45 | Markov | 현재 Gap→출현 확률 |
| 날짜 피처 | 6 | XGBoost | 요일, 월, 월초/말 |
| 커스텀 룰 피처 | N × 4 | Ensemble | 룰별 적중률, Hot 여부, 가중치 |

### 4.2 number_round_stats + regression_details 활용

기존 DB에 이미 계산된 데이터를 피처로 활용한다:

```python
def load_precomputed_features(supabase_client, round_num):
    """DB에 이미 계산된 통계를 피처로 로드한다."""

    # number_round_stats: 번호별 회차 통계
    nrs = supabase_client.table('number_round_stats') \
        .select('*').eq('round', round_num).execute()

    # regression_details: 회귀분석 결과
    rd = supabase_client.table('regression_details') \
        .select('*').eq('target_round', round_num).execute()

    return {
        'number_stats': {row['number']: row for row in (nrs.data or [])},
        'regression': {row['regression_distance']: row for row in (rd.data or [])},
    }
```

---

## 5장. LangChain/RAG 통합 레이어

### 5.1 역할 정의: 딥러닝 vs LangChain

```
┌──────────────────────────────────────────────────────────────────────┐
│                        역할 분담 매트릭스                           │
├──────────────────────┬──────────────────┬────────────────────────────┤
│       영역           │   딥러닝 엔진    │    LangChain/RAG           │
├──────────────────────┼──────────────────┼────────────────────────────┤
│ 번호 확률 예측       │ ✅ 핵심 담당     │ ❌                        │
│ 제외수/추천수 산출   │ ✅ 핵심 담당     │ ❌                        │
│ 필터 가이드 생성     │ ✅ 핵심 담당     │ ❌                        │
│ 조합 생성           │ ✅ 핵심 담당     │ ❌                        │
├──────────────────────┼──────────────────┼────────────────────────────┤
│ "왜 이 번호를 추천?" │ 피처 중요도 제공 │ ✅ 자연어 설명 생성        │
│ "과거 유사 패턴은?"  │ ❌              │ ✅ RAG 벡터 검색           │
│ Q&A 대화            │ ❌              │ ✅ 대화형 체인             │
│ 주간 종합 보고서     │ 예측 데이터 제공 │ ✅ 보고서 구성/작성        │
│ 실시간 분석 해석     │ ❌              │ ✅ Gemini LLM 호출        │
│ 커스텀 룰 해석       │ ❌              │ ✅ NLP → 필터 변환        │
│ 트렌드 자연어 설명   │ 통계 데이터 제공 │ ✅ 서술형 해석 생성        │
└──────────────────────┴──────────────────┴────────────────────────────┘
```

### 5.2 RAG 벡터화 범위 (확장판)

기존 설계에서 lotto_draws만 벡터화했던 것을 **전체 DB 데이터**로 확장한다:

| 데이터 소스 | 문서 수 | 벡터화 내용 | 활용 |
|------------|---------|------------|------|
| **lotto_draws** | ~1200 | 각 회차별 번호 + 18개 통계 지표 | "1200회차와 비슷한 패턴은?" |
| **ai_predictions** | ~1200 × 4 | 예측 결과 + reasoning + 검증 결과 | "AI가 맞춘 회차의 공통점은?" |
| **ai_custom_analyses** | ~수십 | 룰 설명 + 적중률 + 평가 이력 | "적중률 높은 분석 전략은?" |
| **stats_summary** | ~1200 | 회차별 종합 통계 | "총합 150 이상일 때 패턴은?" |
| **number_round_stats** | ~1200 × 45 | 번호별 상세 통계 | "3번이 자주 나오는 조건은?" |
| **regression_details** | ~수천 | 회귀 주기별 적중 데이터 | "5회귀가 잘 맞는 시기는?" |
| **model_performance_log** | ~수백 | 모델별 성능 기록 | "어떤 모델이 최근 잘 맞아?" |

### 5.3 RAG 문서 스키마 (확장판)

```python
def prediction_to_document(prediction, draw):
    """ai_predictions + 실제 결과를 RAG 문서로 변환한다."""

    hit_count = prediction.get('hit_count', 0)
    predicted = prediction.get('predicted_numbers', [])
    actual = draw.get('numbers', [])
    hits = set(predicted) & set(actual)

    content = (
        f"{prediction['target_round']}회차 AI 예측 ({prediction['prediction_type']}): "
        f"예측 번호 {','.join(str(n) for n in sorted(predicted))}. "
        f"실제 번호 {','.join(str(n) for n in sorted(actual))}. "
        f"적중 {hit_count}개 ({','.join(str(n) for n in sorted(hits)) if hits else '없음'}). "
        f"모델 버전 {prediction.get('model_version', 'unknown')}. "
        f"신뢰도 {prediction.get('confidence_score', 0):.2%}."
    )

    reasoning = prediction.get('analysis_detail', {}).get('reasoning', '')
    if reasoning:
        content += f" 추론: {reasoning}"

    return Document(
        page_content=content,
        metadata={
            'round': prediction['target_round'],
            'type': prediction['prediction_type'],
            'hit_count': hit_count,
            'confidence': prediction.get('confidence_score', 0),
            'model_version': prediction.get('model_version', ''),
            'source': 'ai_predictions',
        }
    )
```

### 5.4 LangChain 체인 구조

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      LangChain Chain Architecture                        │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ① AnalysisChain (각 분석 페이지용)                                     │
│     Input: 페이지 통계 데이터 + 사용자 프롬프트                          │
│     Process:                                                             │
│       [1] ai_predictions에서 최신 딥러닝 예측 로드                       │
│       [2] RAG로 유사 과거 패턴 10개 검색                                 │
│       [3] XGBoost feature importance 로드                                │
│       [4] Markov reasoning 로드                                          │
│       [5] Gemini LLM에 모든 컨텍스트 전달 → 자연어 분석 생성            │
│     Output: {trend, pattern, recommendation} (기존과 동일 형식)          │
│                                                                          │
│  ② ChatChain (Q&A 챗봇용)                                               │
│     Input: 사용자 질문 + 현재 페이지 컨텍스트                            │
│     Process:                                                             │
│       [1] RAG 검색 (lotto_draws + ai_predictions + stats_summary)        │
│       [2] 세션 메모리에서 이전 대화 로드                                 │
│       [3] Gemini LLM에 RAG 결과 + 대화 기록 + 질문 전달                 │
│     Output: {answer, sources: [{round, content}]}                        │
│                                                                          │
│  ③ ReportChain (주간 보고서용)                                           │
│     Input: target_round                                                  │
│     Process:                                                             │
│       [1] ai_predictions에서 최신 예측 4가지 타입 로드                   │
│       [2] model_performance_log에서 최근 20회 성능 로드                  │
│       [3] stats_summary에서 45개 번호 통계 로드                          │
│       [4] 커스텀 룰 중 Hot 상태인 것 로드                               │
│       [5] RAG로 유사 패턴 15개 검색                                     │
│       [6] 앙상블 가중치 + feature importance + Markov reasoning 통합     │
│       [7] Gemini LLM에 전체 데이터 전달 → 종합 보고서 생성              │
│     Output: {title, summary, sections[], recommended[], excluded[]}      │
│                                                                          │
│  ④ ExplainChain (설명 가능한 AI용) **신규**                              │
│     Input: "왜 번호 7을 추천했어?"                                       │
│     Process:                                                             │
│       [1] ai_predictions에서 번호 7의 확률 로드                          │
│       [2] XGBoost feature importance에서 번호 7의 Top 5 피처             │
│       [3] LSTM attention weights에서 번호 7에 영향 준 회차               │
│       [4] Markov에서 번호 7의 Gap→출현확률 reasoning                    │
│       [5] Gemini LLM에 3개 모델의 근거 통합 → 자연어 설명               │
│     Output: {explanation, model_contributions, evidence_rounds[]}         │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 5.5 AnalysisChain 구현 (v2: 딥러닝 통합)

```python
async def run_analysis_v2(
    context: str,
    analysis_type: str,
    target_round: int,
    subject_round: int,
    response_style: str = "default",
) -> dict:
    """
    v2: 딥러닝 예측 결과 + RAG + Gemini를 통합한 분석
    """

    # 1. 딥러닝 예측 결과 로드
    predictions = supabase.table('ai_predictions') \
        .select('*').eq('target_round', target_round).execute()

    prediction_context = ""
    for pred in (predictions.data or []):
        ptype = pred['prediction_type']
        nums = pred.get('predicted_numbers', [])
        conf = pred.get('confidence_score', 0)
        prediction_context += (
            f"[딥러닝 {ptype}] "
            f"번호: {nums}, 신뢰도: {conf:.1%}\n"
        )
        if pred.get('analysis_detail', {}).get('reasoning'):
            prediction_context += f"  근거: {pred['analysis_detail']['reasoning']}\n"

    # 2. XGBoost feature importance (추천수 Top 10에 대해)
    recommended_pred = next(
        (p for p in (predictions.data or []) if p['prediction_type'] == 'recommendation'),
        None
    )
    feature_context = ""
    if recommended_pred:
        for num in recommended_pred.get('predicted_numbers', [])[:5]:
            detail = recommended_pred.get('analysis_detail', {})
            features = detail.get('feature_importance', {}).get(str(num), [])
            if features:
                feature_context += f"  번호 {num} 주요 근거: {', '.join(f[0] for f in features[:3])}\n"

    # 3. 마르코프 추론
    markov_pred = next(
        (p for p in (predictions.data or []) if p.get('analysis_detail', {}).get('markov_reasoning')),
        None
    )
    markov_context = ""
    if markov_pred:
        reasonings = markov_pred['analysis_detail'].get('markov_reasoning', {})
        # 추천수에 대한 마르코프 추론만
        for num in recommended_pred.get('predicted_numbers', [])[:5] if recommended_pred else []:
            if str(num) in reasonings:
                markov_context += f"  {reasonings[str(num)]}\n"

    # 4. RAG 유사 패턴 검색
    rag_context = retrieve_as_text(
        f"{analysis_type} 분석 {target_round}회차", analysis_type, k=10
    )

    # 5. 통합 프롬프트
    prompt = f"""
# Role: 대한민국 로또 분석 권위자 ({analysis_type} 전문)
# Task: {subject_round}회차 데이터를 분석하여 {target_round}회차를 예측하라.

## 현재 분석 데이터 (프론트엔드에서 전달)
{context}

## 딥러닝 앙상블 예측 결과
{prediction_context}

## XGBoost 피처 중요도 (추천 근거)
{feature_context}

## 마르코프 전이 확률 분석
{markov_context}

## RAG 과거 유사 패턴
{rag_context}

## 분석 규칙
- 딥러닝 예측 결과를 근거로 활용하되, 맹신하지 말고 통계 데이터와 교차 검증하라.
- 추천/제외 번호를 언급할 때는 반드시 근거(피처 중요도, 마르코프 확률, 유사 패턴)를 함께 제시하라.
- 태그: {{{{good:추천}}}}, {{{{warn:주의}}}}, {{{{range:구간}}}}
- 오직 순수 JSON 포맷으로만 응답하라.

# [JSON 구조]
{{
  "trend": "현재 흐름 및 추세 진단 (딥러닝+통계 근거 포함, 2-3문장)",
  "pattern": "패턴 분석 (마르코프 전이확률+XGBoost 피처 근거 포함, 2-3문장)",
  "recommendation": "{target_round}회차 필승 공략 (구체적 추천/제외 번호 + 근거, 3-4문장)"
}}
"""

    result = await llm.ainvoke(prompt)
    return parse_json_response(result.content, response_style)
```

---

## 6장. 데이터베이스 스키마 완전판

### 6.1 신규 테이블

#### model_performance_log (모델 성능 추적)

```sql
CREATE TABLE model_performance_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    round INTEGER NOT NULL,
    model_name VARCHAR(50) NOT NULL,       -- 'lstm', 'xgboost', 'markov', 'ensemble'
    prediction_type VARCHAR(50) NOT NULL,  -- 'exclusion', 'recommendation', 'filter', 'combination'

    -- 예측 vs 실제
    predicted_numbers INTEGER[],
    actual_numbers INTEGER[],
    hit_count INTEGER DEFAULT 0,

    -- 상세 메트릭
    precision_at_6 DECIMAL(5,4),           -- Top 6 중 적중률
    precision_at_10 DECIMAL(5,4),          -- Top 10 중 적중률

    -- 가중치 정보
    weight_at_prediction DECIMAL(5,4),     -- 예측 시점의 모델 가중치

    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(round, model_name, prediction_type)
);

CREATE INDEX idx_perf_round ON model_performance_log(round DESC);
CREATE INDEX idx_perf_model ON model_performance_log(model_name);
```

### 6.2 기존 테이블 확장

#### ai_custom_analyses 확장 (v3 supplement 반영)

```sql
ALTER TABLE ai_custom_analyses ADD COLUMN IF NOT EXISTS
    ai_evaluation JSONB DEFAULT '{}';

ALTER TABLE ai_custom_analyses ADD COLUMN IF NOT EXISTS
    evaluation_history JSONB DEFAULT '[]';

ALTER TABLE ai_custom_analyses ADD COLUMN IF NOT EXISTS
    is_ai_enabled BOOLEAN DEFAULT TRUE;
```

#### ai_predictions 확장 (마스터플랜 v3 반영 + 모델별 기여도 추가)

```sql
-- 기존 ai_predictions에 모델별 기여도 필드 추가
ALTER TABLE ai_predictions ADD COLUMN IF NOT EXISTS
    model_contributions JSONB DEFAULT '{}';
    /*
    {
        "lstm": { "prob": 0.82, "attention_rounds": [1198, 1200] },
        "xgboost": { "prob": 0.78, "top_features": ["current_gap", "momentum"] },
        "markov": { "prob": 0.65, "current_gap": 12, "reasoning": "..." }
    }
    */

ALTER TABLE ai_predictions ADD COLUMN IF NOT EXISTS
    ensemble_weights JSONB DEFAULT '{}';
    /* { "lstm": 0.35, "xgboost": 0.40, "markov": 0.25 } */
```

### 6.3 전체 테이블 맵

```
┌─────────────────────────────────────────────────────────────────┐
│                    DATABASE TABLE MAP                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  [데이터 소스]                                                   │
│  ┌─────────────┐                                                │
│  │lotto_draws  │ ← update_lotto.py (매주 자동)                  │
│  │1200+ rows   │                                                │
│  └──────┬──────┘                                                │
│         │                                                        │
│  [통계 레이어]                                                   │
│  ┌──────┴──────┐ ┌─────────────────┐ ┌─────────────────────┐   │
│  │stats_summary│ │number_round_stats│ │regression_details   │   │
│  │회차별 종합  │ │번호×회차 통계    │ │회귀분석 상세        │   │
│  └──────┬──────┘ └────────┬────────┘ └──────────┬──────────┘   │
│         │                 │                       │              │
│  [AI 예측 레이어]                                                │
│  ┌──────┴──────────────────┴───────────────────────┴──────┐     │
│  │ai_predictions                                          │     │
│  │• exclusion (제외수 10개)                                │     │
│  │• recommendation (추천수 10개)                           │     │
│  │• filter (필터 가이드)                                   │     │
│  │• combination (최종 조합 5세트)                          │     │
│  │+ model_contributions (모델별 기여도)                    │     │
│  │+ ensemble_weights (사용된 가중치)                       │     │
│  └──────┬─────────────────────────────────────────────────┘     │
│         │                                                        │
│  [성능 추적]                                                     │
│  ┌──────┴──────────────┐                                        │
│  │model_performance_log│ ← 매주 자동 검증                       │
│  │• 모델별 적중률      │                                        │
│  │• 동적 가중치 근거   │                                        │
│  └─────────────────────┘                                        │
│                                                                  │
│  [사용자 레이어]                                                 │
│  ┌──────────────────┐ ┌──────────────────┐ ┌─────────────────┐ │
│  │ai_custom_analyses│ │filter_definitions│ │filter_settings  │ │
│  │+ ai_evaluation   │ │22개 필터 타입    │ │사용자 설정      │ │
│  │+ is_ai_enabled   │ └──────────────────┘ └─────────────────┘ │
│  └──────┬───────────┘                                           │
│         │                                                        │
│  ┌──────┴──────────┐ ┌──────────────────┐                      │
│  │analysis_history │ │user_filter_presets│                      │
│  │분석 실행 기록   │ │프리셋 저장       │                      │
│  └─────────────────┘ └──────────────────┘                      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 7장. 데이터 파이프라인 (7단계)

### 7.1 전체 파이프라인 (v3의 6단계 → v4의 7단계)

```
┌──────────────────────────────────────────────────────────────────┐
│              WEEKLY DATA PIPELINE (매주 토요일 21:30~)            │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│  Stage 1: Data Ingestion (update_lotto.py)                       │
│  ├── 동행복권/Daum 크롤링                                        │
│  ├── lotto_draws INSERT                                          │
│  └── 소요: ~5초                                                  │
│         │                                                        │
│         ▼                                                        │
│  Stage 2: Previous Prediction Verification **신규**              │
│  ├── 직전 회차 ai_predictions의 hit_count 업데이트               │
│  ├── model_performance_log INSERT (모델별)                       │
│  ├── 앙상블 가중치 동적 조정                                     │
│  └── 소요: ~3초                                                  │
│         │                                                        │
│         ▼                                                        │
│  Stage 3: Stats Update                                           │
│  ├── stats_summary UPSERT (45개 번호 통계 갱신)                  │
│  ├── number_round_stats UPSERT (새 회차 데이터)                  │
│  └── 소요: ~10초                                                 │
│         │                                                        │
│         ▼                                                        │
│  Stage 4: Deep Learning Prediction                               │
│  ├── 피처 생성 (45 × 32 피처)                                    │
│  ├── LSTM 추론 (~2초)                                            │
│  ├── XGBoost 추론 (~1초)                                         │
│  ├── Markov 추론 (~0.5초)                                        │
│  ├── 앙상블 통합                                                 │
│  ├── 조합 생성 (Monte Carlo)                                     │
│  ├── ai_predictions INSERT (4가지 타입)                          │
│  └── 소요: ~30초                                                 │
│         │                                                        │
│         ▼                                                        │
│  Stage 5: Custom Rule Evaluation                                 │
│  ├── is_ai_enabled=true인 커스텀 룰 로드                         │
│  ├── 각 룰의 적중률 재계산                                       │
│  ├── ai_evaluation 업데이트 (is_hot, contribution_to_ai)         │
│  └── 소요: ~5초                                                  │
│         │                                                        │
│         ▼                                                        │
│  Stage 6: RAG Vector Update **신규**                             │
│  ├── 새 회차 lotto_draws → 벡터화                                │
│  ├── 새 ai_predictions → 벡터화                                  │
│  ├── 변경된 ai_custom_analyses → 벡터 재생성                     │
│  ├── ChromaDB 증분 업데이트                                      │
│  └── 소요: ~15초                                                 │
│         │                                                        │
│         ▼                                                        │
│  Stage 7: Report Generation + Notification **확장**              │
│  ├── LangChain ReportChain 실행                                  │
│  ├── 주간 보고서 JSON 생성 + DB 저장                             │
│  └── 소요: ~20초                                                 │
│                                                                   │
│  전체 소요: ~90초                                                 │
└──────────────────────────────────────────────────────────────────┘
```

### 7.2 파이프라인 오케스트레이터

```python
# langchain-backend/pipeline/weekly_pipeline.py

class WeeklyPipeline:
    """매주 토요일 추첨 후 실행되는 전체 파이프라인"""

    async def run(self):
        start = time.time()
        results = {}

        try:
            # Stage 1
            results['ingestion'] = await self.stage_1_ingest()
            new_round = results['ingestion']['round']

            # Stage 2
            results['verification'] = await self.stage_2_verify(new_round - 1)

            # Stage 3
            results['stats'] = await self.stage_3_update_stats(new_round)

            # Stage 4
            results['prediction'] = await self.stage_4_predict(new_round + 1)

            # Stage 5
            results['rules'] = await self.stage_5_evaluate_rules(new_round)

            # Stage 6
            results['vectors'] = await self.stage_6_update_vectors(new_round)

            # Stage 7
            results['report'] = await self.stage_7_generate_report(new_round + 1)

            elapsed = time.time() - start
            print(f"파이프라인 완료: {elapsed:.1f}초")
            return {'success': True, 'results': results, 'elapsed': elapsed}

        except Exception as e:
            elapsed = time.time() - start
            print(f"파이프라인 실패: {e} ({elapsed:.1f}초)")
            return {'success': False, 'error': str(e), 'partial_results': results}
```

---

## 8장. 프론트엔드 통합

### 8.1 AIProxy 확장 (딥러닝 결과 라우팅 포함)

```javascript
window.AIProxy = {
    backend: 'auto',  // 'auto' | 'langchain' | 'edge'
    langchainUrl: 'http://localhost:8000',

    async invoke(config) {
        // LangChain 서버가 실행 중이면 LangChain으로
        // 아니면 기존 Edge Function으로 fallback
        if (this.backend === 'auto') {
            try {
                const health = await fetch(this.langchainUrl + '/health',
                    { signal: AbortSignal.timeout(2000) });
                if (health.ok) return this._invokeLangChain(config);
            } catch(e) { /* fallback */ }
        }
        if (this.backend === 'langchain') return this._invokeLangChain(config);
        return this._invokeEdge(config);
    },

    // 딥러닝 예측 결과 직접 조회 (AIContextManager에서 사용)
    async getPredictions(targetRound) {
        const res = await fetch(this.langchainUrl + '/api/predictions/' + targetRound);
        return res.json();
    },

    // 모델 성능 조회
    async getModelPerformance(limit = 20) {
        const res = await fetch(this.langchainUrl + '/api/performance?limit=' + limit);
        return res.json();
    },

    // 설명 요청: "왜 이 번호를 추천했어?"
    async explain(number, targetRound) {
        const res = await fetch(this.langchainUrl + '/api/explain', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ number, target_round: targetRound })
        });
        return res.json();
    },
};
```

### 8.2 AIContextManager 확장 (딥러닝 데이터 통합)

마스터플랜 v3의 AIContextManager에 딥러닝 예측 데이터를 추가한다.
(v3 원본의 fetchPredictions, fetchStats, fetchCustomRules에 더해)

```javascript
// 추가되는 메서드:

async fetchModelPerformance() {
    // model_performance_log에서 최근 성능 로드
    const { data, error } = await window.supabaseClient
        .from('model_performance_log')
        .select('*')
        .order('round', { ascending: false })
        .limit(60);  // 최근 20회 × 3모델

    if (error) throw error;

    // 모델별 그룹화
    const byModel = {};
    for (const entry of (data || [])) {
        if (!byModel[entry.model_name]) byModel[entry.model_name] = [];
        byModel[entry.model_name].push(entry);
    }

    return {
        raw: data,
        byModel,
        currentWeights: this._calculateCurrentWeights(byModel),
    };
}

// 페이지 컨텍스트에 딥러닝 데이터 추가
getContextForPage(pageType) {
    const { predictions, stats, customRules } = this.state;

    // 기존 v3 로직 + 딥러닝 보강
    const baseContext = this._getBaseContext(pageType, stats, predictions);

    // 딥러닝 예측에서 해당 페이지 관련 정보 추출
    const recommendation = predictions?.recommendations;
    const exclusion = predictions?.exclusions;

    return {
        ...baseContext,
        aiPrediction: {
            recommended: recommendation?.predicted_numbers || [],
            excluded: exclusion?.predicted_numbers || [],
            confidence: recommendation?.confidence_score || 0,
            modelContributions: recommendation?.model_contributions || {},
        },
    };
}
```

---

## 9장. 성능 모니터링 + 설명 가능한 AI

### 9.1 모델 성능 대시보드 데이터

```python
# /api/performance 엔드포인트

async def get_performance_dashboard():
    """모델 성능 대시보드용 데이터를 반환한다."""

    client = get_client()

    # 최근 50회 성능
    perf = client.table('model_performance_log') \
        .select('*').order('round', desc=True).limit(200).execute()

    data = perf.data or []

    # 모델별 평균 적중률
    model_stats = {}
    for entry in data:
        name = entry['model_name']
        if name not in model_stats:
            model_stats[name] = {'hits': [], 'rounds': set()}
        model_stats[name]['hits'].append(entry['hit_count'])
        model_stats[name]['rounds'].add(entry['round'])

    summary = {}
    for name, stats in model_stats.items():
        hits = stats['hits']
        summary[name] = {
            'avg_hits': round(sum(hits) / len(hits), 2) if hits else 0,
            'max_hits': max(hits) if hits else 0,
            'total_rounds': len(stats['rounds']),
            'hit_distribution': {
                i: hits.count(i) for i in range(max(hits) + 1)
            } if hits else {},
        }

    # 랜덤 기준선과 비교
    random_baseline = {
        'avg_hits': round(6 * 10 / 45, 2),  # Top 10 추천 중 기대 적중: 1.33
        'description': '무작위 10개 선택 시 기대 적중 수'
    }

    return {
        'model_stats': summary,
        'random_baseline': random_baseline,
        'current_weights': get_current_weights(),
        'trend': get_performance_trend(data),
    }
```

### 9.2 ExplainChain: "왜 이 번호를 추천했어?"

```python
# /api/explain 엔드포인트

async def explain_number(number: int, target_round: int) -> dict:
    """특정 번호의 추천/제외 이유를 자연어로 설명한다."""

    # 1. ai_predictions에서 해당 번호 관련 데이터 로드
    preds = supabase.table('ai_predictions') \
        .select('*').eq('target_round', target_round).execute()

    contributions = {}
    for pred in (preds.data or []):
        mc = pred.get('model_contributions', {})
        if str(number) in str(mc):
            contributions[pred['prediction_type']] = mc

    # 2. 각 모델의 근거 수집
    evidence = {
        'xgboost_features': [],  # Top 5 피처
        'lstm_attention': [],     # 영향 받은 회차
        'markov_reasoning': '',   # 전이 확률 설명
        'ensemble_prob': 0,       # 최종 확률
    }

    # ... (각 모델에서 근거 추출)

    # 3. LangChain으로 자연어 설명 생성
    prompt = f"""
다음 데이터를 바탕으로 "로또 번호 {number}이(가)
{target_round}회차에 {'추천' if evidence['ensemble_prob'] > 0.15 else '제외'}된 이유"를
사용자가 이해할 수 있도록 자연스러운 한국어로 설명하세요.

XGBoost 주요 근거: {evidence['xgboost_features']}
LSTM 참조 회차: {evidence['lstm_attention']}
마르코프 분석: {evidence['markov_reasoning']}
최종 확률: {evidence['ensemble_prob']:.1%}
"""

    result = await llm.ainvoke(prompt)

    return {
        'number': number,
        'explanation': result.content,
        'model_contributions': evidence,
        'confidence': evidence['ensemble_prob'],
    }
```

---

## 10장. 개발 로드맵

### Phase 0: DB 마이그레이션 (2일)
- [ ] model_performance_log 테이블 생성
- [ ] ai_custom_analyses 확장 (ai_evaluation, is_ai_enabled)
- [ ] ai_predictions 확장 (model_contributions, ensemble_weights)
- [ ] stats_summary 스키마를 v4 형태로 확장
- [ ] 기존 데이터 백업

### Phase 1: 딥러닝 모델 구현 (1.5주)
- [ ] LSTM 모델 구현 + 학습
- [ ] XGBoost 모델 구현 + 학습
- [ ] 마르코프 체인 구현 + 학습
- [ ] 앙상블 레이어 + 동적 가중치
- [ ] 조합 생성기
- [ ] 모델 평가 (랜덤 기준선 대비)
- **마일스톤**: ai_predictions에 실제 예측 데이터 저장

### Phase 2: 데이터 파이프라인 (1주)
- [ ] 7단계 파이프라인 오케스트레이터
- [ ] 자동 검증 (Stage 2)
- [ ] 커스텀 룰 평가 (Stage 5)
- [ ] 스케줄러 설정
- **마일스톤**: 매주 자동 예측 생성 + 자동 검증

### Phase 3: LangChain/RAG 통합 (1주)
- [ ] FastAPI 서버 세팅
- [ ] 전체 DB 데이터 벡터화 (ChromaDB)
- [ ] AnalysisChain v2 (딥러닝 결과 통합)
- [ ] ChatChain (Q&A 챗봇 with RAG)
- [ ] ExplainChain (설명 가능한 AI)
- [ ] ReportChain (주간 보고서)
- **마일스톤**: /api/analyze가 딥러닝+RAG 통합 분석 반환

### Phase 4: 프론트엔드 통합 (1주)
- [ ] AIProxy.js 생성
- [ ] ChatbotWidget.js 생성
- [ ] AIContextManager 구현 (딥러닝 데이터 포함)
- [ ] AIInsightWidget 구현
- [ ] 32개 HTML 페이지 수정 (script 태그 + AIProxy 전환)
- [ ] common_v2.js 수정
- **마일스톤**: 모든 페이지에서 딥러닝+RAG 기반 분석 동작

### Phase 5: 안정화 + 모니터링 (0.5주)
- [ ] 모델 성능 대시보드
- [ ] E2E 테스트
- [ ] 에러 핸들링 + Fallback
- [ ] 성능 최적화
- **마일스톤**: 프로덕션 배포 준비 완료

### 전체 기간: 약 5주

---

## 부록 A: 디렉토리 구조 (최종)

```
로또개발/
├── js/                              # 프론트엔드
│   ├── common_v2.js                 # (수정) AIProxy 전환
│   ├── config.js                    # (수정) LANGCHAIN 설정 추가
│   ├── aiProxy.js                   # (신규) AI 호출 라우터
│   ├── ChatbotWidget.js             # (신규) RAG Q&A 챗봇
│   ├── ai/
│   │   ├── AIContextManager.js      # (신규) 중앙 상태 관리
│   │   ├── AIInsightWidget.js       # (신규) 페이지별 인사이트 위젯
│   │   └── AIFallbackStrategy.js    # (신규) Fallback 로직
│   ├── filter/
│   │   └── FilterService.js         # (기존) 유지
│   ├── NLPProcessor.js              # (기존) 유지
│   └── ...
│
├── langchain-backend/               # (신규) Python AI 서버
│   ├── main.py                      # FastAPI 진입점
│   ├── config.py
│   ├── models/                      # 딥러닝 모델
│   │   ├── lstm_model.py
│   │   ├── xgboost_model.py
│   │   ├── markov_model.py
│   │   ├── ensemble.py
│   │   └── combination_generator.py
│   ├── chains/                      # LangChain 체인
│   │   ├── analysis_chain.py
│   │   ├── chat_chain.py
│   │   ├── report_chain.py
│   │   └── explain_chain.py
│   ├── rag/                         # RAG 파이프라인
│   │   ├── data_loader.py
│   │   ├── embedder.py
│   │   └── retriever.py
│   ├── pipeline/                    # 데이터 파이프라인
│   │   ├── weekly_pipeline.py
│   │   └── scheduler.py
│   ├── routes/                      # API 엔드포인트
│   │   ├── analysis.py
│   │   ├── chat.py
│   │   ├── report.py
│   │   ├── explain.py
│   │   ├── predictions.py
│   │   ├── performance.py
│   │   └── vectors.py
│   ├── db/
│   │   ├── supabase_client.py
│   │   └── vector_store.py
│   ├── memory/
│   │   └── session_store.py
│   └── scripts/
│       ├── build_vectors.py
│       ├── train_models.py
│       └── run_pipeline.py
│
├── supabase/                        # DB 스키마
│   ├── schema_v4_unified.sql        # (신규) 통합 스키마
│   └── ...
│
├── 32개 HTML 분석 페이지             # (수정) script 태그 + AIProxy
├── components/                      # (수정) sidebar에 챗봇 링크
├── lotto-auto-update/               # (수정) 파이프라인 트리거 추가
└── md/
    └── ai_master_plan_v4_unified.md # 이 문서
```

---

## 부록 B: 랜덤 기준선 (Random Baseline)

모델 성능을 평가할 때 반드시 랜덤 기준선과 비교해야 한다:

| 메트릭 | 랜덤 기준선 | 목표 |
|--------|-----------|------|
| Top 10 추천 중 적중 | 1.33개 (6×10/45) | **≥2.0개** |
| Top 6 추천 중 적중 | 0.80개 (6×6/45) | **≥1.2개** |
| 제외수 10개 중 당첨번호 없는 비율 | 73.3% | **≥85%** |
| 필터 통과 비율 | 조건 의존 | **≥75%** |

모델이 랜덤 기준선보다 **유의미하게** 좋지 않다면, 과적합이거나 무의미한 학습이므로 재설계가 필요하다.

---

## ✅ v3 대비 v4 변경 요약

| 항목 | v3 | v4 |
|------|----|----|
| LSTM | 한 줄 언급 | **완전한 구현 설계** (Attention, 학습 설정) |
| 마르코프 | 한 줄 언급 | **완전한 구현 설계** (전이 행렬, 베이지안) |
| 앙상블 가중치 | 고정(0.35/0.40/0.25) | **동적 조정** (최근 성능 기반) |
| LangChain/RAG | 없음 | **전체 통합 설계** (4개 체인, 7개 데이터 소스) |
| 벡터화 범위 | 없음 | **lotto_draws + ai_predictions + stats 등 7가지** |
| 설명 가능한 AI | 없음 | **ExplainChain + Feature Importance + Attention** |
| 성능 모니터링 | 없음 | **model_performance_log + 대시보드** |
| 랜덤 기준선 | 없음 | **필수 비교 대상으로 명시** |
| 파이프라인 | 6단계 | **7단계** (검증 + RAG 업데이트 추가) |
| 동반 출현 분석 | 없음 | **Co-occurrence 피처 추가** |
| Cold Start | 없음 | **즉시 백테스팅 전략** |
