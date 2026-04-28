# Lotto_lab 통합 플랜 (UNIFIED) — 처음부터 모든 시스템 통합 설계

## 0. Context

### 프로젝트
**Lotto_lab** (https://github.com/ParkSD1975/Lotto_lab) — 한국 로또 분석 보조 도구. Python FastAPI(`langchain-backend/`) + HTML/JS + Tailwind + LangChain·Gemma 4 LLM. 약 1100여 회차 Supabase 데이터.

### 본 plan의 위치
이 파일은 **모든 시스템을 처음부터 통합한 단일 마스터 플랜**. 기존 5개 plan 파일(`kind-hugging-matsumoto.md`, `회귀-plan.md`, `number-recommendation-plan.md`, `frontend-design-plan.md`, `lotto_lab-master-plan.md`, `advanced-models-plan.md`)은 보존되되 본 plan이 **단일 진실 공급원**.

### 사용자 핵심 결정 사항 (전체 누적)

| # | 결정 | 시점 |
|---|---|---|
| 1 | 21지표 IndependentCountPredictor 강화 패턴 + Category GNN | 2026-04-27 |
| 2 | "M중 N" 정규화 출력 형식 (모든 카테고리 지표) | 2026-04-27 |
| 3 | 이월수만 보너스 변형 2개, 이웃수는 단일 | 2026-04-27 |
| 4 | 회귀 Tier 3-C 자동 룰 트리거 | 2026-04-28 |
| 5 | 미출현그룹 광역 4만, 동적 N은 회귀로 | 2026-04-28 |
| 6 | 핫콜드 12 카테고리 (4 윈도우 × 3 그룹) | 2026-04-28 |
| 7 | 4 Pillar 추천/제외 + 메타러너 학습 | 2026-04-28 |
| 8 | Narrative 두 형식: 흐름·추세·추천 (페이지) / 시그널·근거·결론 (번호) | 2026-04-28 |
| 9 | 5분할 슬라이스 + 사용자 정의 | 2026-04-28 |
| 10 | 데스크탑 우선 + 모바일 대응 | 2026-04-28 |
| 11 | ECharts 도입 (5 시각화) | 2026-04-28 |
| 12 | **8 신규 모델/기법 모두 병렬 동시 도입** | 2026-04-28 |
| 13 | **TFT가 LSTM/Transformer 흡수** | 2026-04-28 |
| 14 | **NumberXAIExplainer 컴포넌트 신설** (옵션 B) | 2026-04-28 |
| 15 | **1 제외** — 소수·합성수에서 분리, 분석 대상 아님 | 2026-04-28 |
| 16 | **CombinationScorer 신설** — 4 Pillar + 11 base + 21지표 통합 조합 추천 | 2026-04-28 |
| 17 | **프론트 4 페이지** — 분석 지표별 AI 프리미엄 / 딥러닝 / AI 조합 / 검증 | 2026-04-28 |
| 18 | **커스텀 분석 동적 분석 통합** — 22개 분석 지표 페이지 모두 `dlInsightContainer` 자동 렌더링 | 2026-04-28 |
| 19 | **AI 제외수 자동 룰 2개** — 회귀 N 4연번 / 1회귀 4연번(직전 4회 연속 출현) → 강제 제외 | 2026-04-28 |
| 20 | **AI 제외수 자동 룰 3 추가** — 데드 회귀×라인 이월률 ≥ 2개 회귀 → 강제 제외 (라인=정렬 위치 1~6+보너스 7) | 2026-04-28 |
| 21 | **전문가 메모 통합** — Hard Filter 1순위 (사용자 메모) + 자동 룰 2순위 + 4 Pillar 3순위 | 2026-04-28 |
| 22 | **전문가 메모 → 딥러닝 학습 반영** — 90D feature 입력 + Memo Consistency Loss + 메모 적중률 동적 조정 + MoE 메모 expert | 2026-04-28 |

---

## 1. 모델 토폴로지 — 11 base + 2 기법

### 11 base 모델

| # | 모델 | 분류 | 강점 | 통합 위치 |
|---|---|---|---|---|
| 1 | **XGBoost** | 트리 | 정형 회귀/분류 | 모든 predictor 메인 |
| 2 | **CatBoost** | 트리 | 카테고리 자동 처리 | XGB와 병렬 |
| 3 | **TabNet** | 신경망(attention) | 자동 feature selection | 8번째 base |
| 4 | **CNN** | 신경망(2D) | 7×7 그리드 패턴 | 로또용지 입력 |
| 5 | **GNN(GAT)** | 그래프 신경망 | 동반출현 | 45번호 그래프 |
| 6 | **Markov** | 통계 | bucket 전이, mode collapse 면역 | bucket 카테고리 |
| 7 | **Autoencoder** | 신경망 | 이상치 감지 | 게이팅 |
| 8 | **TFT** | 신경망(통합) | 시계열+정형+카테고리 | LSTM/Transformer 흡수 |
| 9 | **N-BEATS** | 신경망(시계열) | trend/seasonality 분해 | 스칼라 지표 시계열 |
| 10 | **MHN** | 신경망(메모리) | 패턴 매칭 | 회귀 메타 + Pillar 3 |
| 11 | **Bayesian NN** | 신경망(VI) | 불확실성 정량화 | Pillar 1 보강 |

### 2 기법 (모델 아닌 인프라)

- **Self-Supervised Pretraining** (G-8) — 1100회차 마스킹+대조학습 → 모든 신경망 backbone 사전학습
- **MoE (Mixture of Experts)** — 메타러너 라우팅 (AE 게이트 진화)

### 폐기

- ❌ LSTM (TFT 흡수)
- ❌ Transformer (TFT 흡수)

### 모델 다양성 매트릭스

| 입력 형태 | 처리 모델 |
|---|---|
| 정형 (트리) | XGBoost, CatBoost |
| 정형 (attention) | TabNet |
| 시계열+정형+카테고리 통합 | TFT |
| 시계열 분해 | N-BEATS |
| 7×7 그리드 | CNN |
| 그래프 (45번호) | GNN |
| bucket 전이 | Markov |
| 이상치 | AE |
| 패턴 매칭 메모리 | MHN |
| 불확실성 분포 | Bayesian NN |

→ 입력·메커니즘 **완전히 다른 11개 모델**로 앙상블 다양성 극대화.

---

## 2. Phase 0 — 글로벌 인프라

### G 시리즈 (글로벌 결함 수정)

| # | 항목 | 내용 |
|---|---|---|
| G-1 | Focal Loss 미스튜닝 | BCEWithLogitsLoss + pos_weight=6.5 단일 |
| G-2 | Bidirectional LSTM 축소 | TFT 흡수로 자동 해결 |
| G-3 | 명시적 정규화 | StandardScaler/PowerTransformer/log1p 변수별 차등 |
| G-4 | TimeSeriesSplit walk-forward | n_splits=5, 마지막 200회차 hold-out |
| G-5 | 베이스라인 비교 | rolling_mean / 균등 / 빈도분포 |
| G-6 | Random Seed | RANDOM_SEED=42 전역 |
| G-7 | GNN 설정 외부화 | TOPK=15, BCE_AUX_WEIGHT=0.3 |
| **G-8** | **Self-Supervised Pretraining** | 마스킹+대조학습, 모든 신경망 backbone 초기화 |

### M/T/S/U 시리즈

- **M-1** MetaLearner 재구축 + **MoE 라우팅 통합**
- **T-1** Training Orchestrator (DAG **7단계** — 0단계 Self-Supervised 추가)
- **S-1** SLA Monitor (wall-time/메모리)
- **U-1~U-4** 단위 테스트 / 통일 하이퍼파라미터 / Markov calibration / Gemma 4 LRU 캐시

### T-1 DAG 7단계 (Self-Supervised 단계 추가)

```
0. Self-Supervised Pretraining (G-8) ← 신규 0단계
1. Markov 학습
2. XGBoost + CatBoost (트리)
3. CNN
4. TFT (신규, LSTM/TF 통합)
5. TabNet + N-BEATS + MHN + Bayesian NN (신규 4)
6. AutoEncoder
7. Meta Learner + MoE 라우팅
```

---

## 3. Phase 1 — 11 base 모델 정의

각 모델별 입출력 + 학습 방식. 자세한 하이퍼파라미터는 `config.py` 참조.

### 3-1. XGBoost (기존 유지)
- 입력: 정형 feature (지표별 차등)
- 출력: multi:softprob (카운트) 또는 binary:logistic (1~45)
- objective: 카테고리 카운트 = multi:softprob, 1~45 = binary:logistic
- pos_weight=6.5 (G-1)

### 3-2. CatBoost (신규)
- 입력: XGBoost와 동일 정형 + 카테고리 raw 입력
- 출력: 동일 형식 (XGB 병렬)
- 특징: target encoding 내장, ordered boosting (작은 데이터셋 친화)

### 3-3. TabNet (신규)
- 입력: 정형 feature
- 출력: 1~45 binary (sigmoid) + Sparsemax attention mask
- attention mask → NumberXAIExplainer 입력

### 3-4. CNN (기존 유지)
- 입력: (batch, seq=30, 7, 7) — 로또용지 그리드 시계열
- 출력: (batch, 45) sigmoid
- Self-Supervised pretrained backbone 초기화

### 3-5. GNN(GAT) (기존 유지)
- 노드: 1~45 번호
- 엣지: 동반출현 (Top-K=15, 사용자 정정)
- 출력: 45 logits + edge_prob (회귀 활용)
- 손실: SoftmaxRankingLoss

### 3-6. Markov (기존 유지)
- 7-state 전이행렬 (각 카테고리)
- bucket 카테고리화 (Markov calibration U-3)
- 출력: 다음 회차 카테고리 분포

### 3-7. Autoencoder (기존 유지)
- 입력: 회차 feature (65 dim)
- 출력: 재구성 + 잠재 4dim
- 게이팅 역할 → MoE로 진화

### 3-8. TFT (신규, LSTM/Transformer 흡수)
- 입력 통합:
  - 정형 입력: 21지표 + 회귀 압축 변수
  - 시계열 입력: 직전 30회차 시퀀스
  - 카테고리 입력: 끝수·번호대 임베딩
- 출력:
  - 다음 회차 예측 (binary 1~45 + 카테고리 분포)
  - **Variable selection weights** → NumberXAIExplainer 입력
- 구조: d_model=64, attention_head=4, num_layers=2 (1100회차 적응)

### 3-9. N-BEATS (신규)
- 입력: 직전 50회차 스칼라 시계열 (sum, endings_sum, ac, ...)
- 출력:
  - 다음 회차 예측
  - **trend + seasonality + residual** 분해 → narrative 직접 입력
- 적용 지표: 총합, 끝수합, AC, (선택적으로 다른 스칼라)

### 3-10. MHN (Modern Hopfield Networks, 신규)
- 메모리: 학습 데이터 1100회차 + 21지표 + 6번호 패턴
- 입력: 현재 회차 query
- 출력:
  - top-K 유사 과거 회차 (similarity score)
  - retrieval된 과거 패턴 → narrative 입력
- 적용:
  - 회귀 4 Tier의 Tier 4 메타 분석
  - 4 Pillar의 Pillar 3 (individual_state) 보강

### 3-11. Bayesian NN (신규)
- 입력: 정형 feature
- 출력:
  - ensemble_prob 분포 [q10, q50, q90] 대신 점추정
  - 가중치 자체 분포 (VI 또는 MC Dropout)
  - **분산 σ** → NumberXAIExplainer + Pillar 1 입력
- 적용: 4 Pillar Pillar 1 보강 (점추정 → 분포 추정)

---

## 3.5 모델 적용 매트릭스 (정확 표 3개) ★사용자 핵심 요구

★ 메인 / ✓ 보조 / · 미사용

### 표 1: 분석 지표 × 11 base 모델 (21지표 + 커스텀분석 + 회귀)

| 분석 지표 | XGB | Cat | TabNet | CNN | GNN | Markov | AE | TFT | N-BEATS | MHN | Bayesian | 비고 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **총합** (스칼라) | ★ | ✓ | ✓ | · | ✓ | ✓ | ✓ | ★ | ★ | · | ✓ | sum 카르텟 메인 |
| **끝수합** (스칼라+10D) | ★ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ★ | ★ | · | ✓ | scalar+distribution head |
| **AC값** (스칼라) | ★ | ✓ | ✓ | · | · | ★ | · | ★ | ✓ | · | ✓ | Markov 11-state 자연 |
| **고저** (7-pair) | ★ | ★ | ✓ | · | ✓ | ★ | · | ★ | · | · | ✓ | 7-pair 조인트 |
| **홀짝** (7-pair) | ★ | ★ | ✓ | · | ✓ | ★ | · | ★ | · | · | ✓ | 동일 |
| **이월수** (정확/보너스 ×2) | ★ | ★ | · | · | ★ | ★ | · | ✓ | · | · | · | GNN 집계 직접 |
| **이웃수** | ★ | ★ | · | · | ★ | ★ | · | ✓ | · | · | · | 이월수 템플릿 |
| **연번** | ★ | ★ | · | · | ★ | ★ | · | ✓ | · | · | · | GNN edge_prob 집계 |
| **끝수 0~9** (10D) | ★ | ★ | ★ | · | ★ | ★ | ✓ | ★ | · | · | ✓ | IndependentCountPredictor 대표 |
| **번호대** (5) | ★ | ★ | ★ | · | ★ | ★ | · | ★ | · | · | ✓ | sum 카르텟 |
| **9궁** (9) | ★ | ★ | ★ | · | ★ | ★ | · | ★ | · | · | ✓ | sum 카르텟 |
| **로또용지** (14) | ★ | ★ | ★ | ★ | ★ | ★ | · | ★ | · | · | ✓ | CNN 그리드 활용 |
| **배수** (6: 3·4·5·7·8 + 배수외) | ★ | ★ | ✓ | · | ★ | ★ | · | ✓ | · | · | · | 매핑 매트릭스 일관성 |
| **소수** (단일, 14개) | ★ | ✓ | · | · | ✓ | ★ | · | ✓ | · | · | · | **1 제외 (사용자 정정)** |
| **합성수** (단일, 30개) | ★ | ✓ | · | · | ✓ | ★ | · | ✓ | · | · | · | **1 제외**, 비율은 후처리 보조 |
| **삼각수** (단일, 9개) | ★ | ✓ | · | · | ✓ | ★ | · | ✓ | · | · | · | 단순 7-class |
| **제곱수** (단일, 6개) | ★ | ✓ | · | · | ✓ | ★ | · | ✓ | · | · | · | 단순 |
| **동형수** (단일, 4개) | ★ | ✓ | · | · | ✓ | ★ | · | ✓ | · | · | · | 11배수 동치 |
| **미출현그룹** (광역 4, 동적) | ★ | ★ | ✓ | · | ★ | ★ | ✓ | ★ | · | · | · | 시간 화살표 그래프 |
| **핫콜드** (12 = 4×3, 동적) | ★ | ★ | ✓ | · | ★ | ★ | ✓ | ★ | · | · | · | 4 윈도우 × 3 그룹 |
| **회귀 Tier 1** (가변 N 16~30) | ★ | ★ | ✓ | · | ★ | ★ | ✓ | ★ | · | · | ✓ | DynamicIndependentCountPredictor |
| **회귀 Tier 4 메타 분석** | · | · | · | · | · | · | · | · | · | ★ | · | MHN 패턴 매칭 전담 |
| **커스텀 분석 (사용자 그룹)** | ★ | ★ | ✓ | · | ✓ | ★ | ✓ | ★ | ✓ | ✓ | ✓ | 동적 분석, 사용자 정의 번호 그룹 |

### 표 2: 번호 분석 × 11 base 모델 (4 Pillar + XAI + Recommender)

| 컴포넌트 | XGB | Cat | TabNet | CNN | GNN | Markov | AE | TFT | N-BEATS | MHN | Bayesian | 역할 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **Pillar 1 ensemble_prob** | ★ | ★ | ★ | ★ | ★ | ★ | ★ | ★ | ✓ | · | ★ | 11 base 가중평균 + Bayesian 분포 |
| **Pillar 2 filter_compliance** | · | · | · | · | · | · | · | · | · | · | · | 21지표 출력 후처리 (모델 X) |
| **Pillar 3 individual_state** | · | · | · | · | ✓ | ✓ | ✓ | · | · | ★ | · | 핫콜드+미출현+회귀+MHN 매칭 |
| **Pillar 4 model_consensus** | ★ | ★ | ★ | ★ | ★ | ★ | ★ | ★ | ★ | ★ | ★ | 11 base 순위 통계 (mean/std/top-N) |
| **MetaLearner Ridge + MoE** | ✓ | ✓ | · | · | · | · | ✓ | · | · | · | ✓ | 4 Pillar 가중치 학습 + 라우팅 |
| **NumberRecommender** | (Pillar 점수 입력 다중 조건 통과) — 직접 모델 호출 X | | | | | | | | | | | 추천 5 + 제외 10 결정 |
| **NumberXAIExplainer** | ★ | ★ | ★ | ★ | ★ | ★ | ★ | ★ | ★ | ★ | ★ | **11 base 모두 XAI 입력** (옵션 B) |
| **NumberNarrativeGenerator** | (Gemma 4 LLM 외부 호출) | | | | | | | | | | | 시그널/근거/결론 3섹션 |

### 표 3: AI 조합기 × 11 base 모델 (CombinationScorer ★사용자 정정 추가)

| CombinationScorer 입력 | XGB | Cat | TabNet | CNN | GNN | Markov | AE | TFT | N-BEATS | MHN | Bayesian | 역할 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **번호별 앙상블 prob (11 base)** | ★ | ★ | ★ | ★ | ★ | ★ | ★ | ★ | · | · | ★ | 6번호 평균 점수 (Pillar 1 활용) |
| **4 Pillar 추천/제외** | (Pillar 결과 활용) | | | | | | | | | | | 고정수 보너스 / 제외수 페널티 |
| **21지표 필터 통과도** | (filter_compliance 활용) | | | | | | | | | | | 조합의 sum/끝수합/AC/홀짝/저고/소수/제곱수/삼각수/연속수 통과 점수 |
| **조합 다양성 보너스** | · | · | · | · | ★ | · | ✓ | · | · | · | · | GNN edge_prob (인접쌍 개수) + AE 이상도 |
| **조합 narrative** | (Gemma 4 LLM) | | | | | | | | | | | 흐름/추세/추천 3섹션 (조합 단위) |

**최종 점수 공식**:
```python
score(combo) = number_score (6번호 11 base 평균)
             + fixed_bonus (4 Pillar 추천 5 매칭)
             - exclude_penalty (4 Pillar 제외 10 매칭)
             + filter_compliance_score (21지표 통과)
             + diversity_bonus (GNN/AE 다양성)
```

---

## 3.6 1 제외 정정 (사용자 결정, 2026-04-28)

소수와 합성수에서 **숫자 1은 분석 대상 아님**:
- 소수: 14개 (2,3,5,7,11,13,17,19,23,29,31,37,41,43)
- 합성수: 30개 (4,6,8,9,...,44,45)
- 1: 분석 제외 (어느 카테고리에도 안 들어감, 매핑 매트릭스에서도 제외)

**비율 분석은 후처리 보조** (모델 X):
- prime_to_composite_ratio = predicted_prime_expected / predicted_composite_expected
- prime_ratio = expected / 6
- 두 단일 모델 출력에서 후처리 계산

**sum 추정 카르텟 갱신**: `expected_sum_from_prime_composite = 19.43×prime + 25.40×composite` (1 제외)

---

## 4. Phase 2 — 21개 분석 지표 IndependentCountPredictor

### 강화 패턴 (11 base 통합)

```python
class IndependentCountPredictor:
    """
    11 base 모델 통합 카테고리별 독립 7-class 카운트 분류기.
    
    Shared Backbone (모든 활성 모델 공유):
      ├─ XGBoost (per-category 헤드 N개)
      ├─ CatBoost (per-category 헤드 N개) — 신규
      ├─ TabNet (Sparsemax attention 헤드) — 신규
      ├─ Markov 7-state × N
      ├─ 기존 GNN 집계 (45-노드 → N개 카테고리)
      ├─ TFT (시계열+정형+카테고리 통합) — LSTM/TF 흡수
      ├─ N-BEATS (스칼라 지표만, 분해 head) — 신규
      ├─ Bayesian NN (분포 추정 헤드) — 신규
      ├─ Category Interaction Module:
      │    ├─ Category GNN (N 노드, 엣지=동시출현 상관)
      │    ├─ 카테고리 임베딩 학습
      │    └─ 임베딩을 per-category 헤드 입력에 주입
      └─ Pretrained backbone (Self-Supervised G-8 적용)
    
    Per-category Heads (N개):
      └─ Softmax 7-class P(count=0..6)
    
    출력 (각 카테고리별):
      {
        "absolute_dist": [P(0), ..., P(6)],
        "expected_count": E,
        "current_pool_size": M,
        "expected_ratio": E/M,
        "ratio_dist_top": [...],
        "narrative": "{name} 풀 {M}개 중 {N}개 출현 가능성 {P}%",
        # 11 base 모델 출력 분해 (XAI 입력)
        "model_contributions": {
          "xgboost": ..., "catboost": ..., "tabnet": ...,
          "tft": ..., "nbeats": ..., "bayesian_nn_std": ...,
        }
      }
    
    그룹간 강도 출력:
      ├─ inter_category_correlation_matrix [N×N]
      ├─ category_dependency_graph
      └─ joint_distribution_top_patterns
```

### 21지표 매핑 (요약)

| 지표 | N | Phase | 11 base 적용 |
|---|---|---|---|
| 총합 | 1 (스칼라 회귀) | 4 | XGB Quantile + CatBoost + TabNet + TFT + N-BEATS + Markov(6-bucket) + AE + GNN 집계 + Bayesian (8 모델) |
| 끝수합 (스칼라) | 1 | 2 | 총합과 동일 8 모델 + 분포 head (CNN 추가) |
| 끝수 분포 10D | 10 | 1 | IndependentCountPredictor 10 헤드 |
| AC값 | 1 (스칼라) | 3 | XGB + TFT + Markov 11-state + N-BEATS + Bayesian |
| 고저 (7-pair) | 7 | 1 | IndependentCountPredictor 7 헤드 |
| 홀짝 (7-pair) | 7 | 1 | 동일 |
| 이월수 정확/보너스 (×2) | 7 | 1 | XGB + CatBoost + Markov + GNN 집계 |
| 연번 | 6 | 1 | 위 + GNN edge_prob |
| 이웃수 | 7 | 1 | 이월수 템플릿 |
| 번호대 | 5 | 1 | 표준 |
| 9궁 | 9 | 1 | 표준 + Category GNN |
| 로또용지 | 14 | 1 | + CNN 그리드 출력 활용 |
| 배수 (3·4·5·7·8 + 배수외) | 6 | 1 | 매핑 매트릭스 일관성 |
| 소수+합성수+1 | 3 | 1 | 비율 분석 + sum 카르텟 |
| 삼각수 | 1 | 1 | 단일 카테고리 |
| 제곱수 | 1 | 1 | 단일 |
| 동형수 | 1 | 1 | 단일 |
| 미출현그룹 (광역 4) | 4 | 1 | 동적 멤버십 + 시간 화살표 그래프 |
| 핫콜드 (12) | 12 | 1 | 4 윈도우 × 3 그룹, 모두 동적 풀 크기 |
| 회귀 (2~200) | 가변 | 1 | **별도 Phase 3 (4 Tier)** |

### sum 추정 카르텟 (Phase 4 총합 매트릭스 핵심)

```python
expected_sum_from_decades = 5×d0 + 14.5×d1 + 24.5×d2 + 34.5×d3 + 42.5×d4
expected_sum_from_gungs = 3×g0 + 8×g1 + ... + 43×g8
expected_sum_from_horizontal = 4×h0 + 11×h1 + ... + 44×h6
expected_sum_from_prime_composite = 19.43×prime + 25.40×composite + 1.0×one
```

XGBoost가 4개 추정 자동 가중. **N-BEATS 분해 결과** 추가로 trend·seasonality·residual 입력.

### Cross-feedback Phase 위계 (순환 방지)

```
Phase 1 (독립): 끝수0~9, 고저, 홀짝, 이월수×2, 이웃수, 연번
                번호대, 9궁, 로또용지, 배수, 소수합성수+1
                삼각수, 제곱수, 동형수
                미출현그룹(광역4), 핫콜드(12), 회귀 Tier 1
   ↓ predicted dist + expected
Phase 2: 끝수합 (← 끝수 분포 + large_endings_ratio)
   ↓
Phase 3: AC값 (← Phase 1+2 다수)
   ↓
Phase 4: 총합 (← sum 카르텟 + 모든 약 시그널 + N-BEATS 분해)
```

---

## 5. Phase 3 — 회귀(2~200) 4 Tier

### Tier 1: DynamicIndependentCountPredictor

가변 카테고리 분류기. 매 회차 활성 N (16~30개) 동적.

**11 base 통합**:
- TFT 메인 (시계열+정형+카테고리 통합)
- XGBoost·CatBoost·TabNet 헤드
- Markov per-N 전이행렬
- GNN 집계 per-N 풀
- Bayesian NN으로 sparse N(<50 sample) 불확실성 정량화

### Tier 2: 번호별 회귀 압축 (8 변수 × 45)

기존 압축 + **MHN 추가**:
- regression_appearance_count, avg_gap, max_consecutive 등 8 변수
- **MHN retrieval**: 각 번호의 과거 비슷한 회귀 패턴 top-K → 9번째 변수

### Tier 3: 결합 필터 자동 룰 (사용자 항목 D, E, F + 4연번 룰)

- Tier 3-A: 라인×N 매트릭스
- Tier 3-B: 끝수×N
- **Tier 3-C: 번호대×N + 자동 룰 트리거** (사용자 항목 E):
  ```python
  if cluster_count >= 3:
      filter_mask = {"decade_other_max": 1}  # 다른 번호대 0~1개
  ```
- **Tier 3-D: 4연번 자동 제외 룰** (★사용자 정정, 2026-04-28):
  ```python
  # 룰 1: 회귀 N (2~200)에서 4연번 이상 → 자동 제외 후보
  for N in active_regression_N:
      for n in 1..45:
          if regression_data[n][N].max_consecutive >= 4:
              auto_exclude.add(n, reason=f'regression_consecutive_N{N}')
  
  # 룰 2: 1회귀에서 4연번 (직전 4회차 연속 출현) → 자동 제외
  for n in 1..45:
      if consecutive_recent_appearance(n, lookback=4) >= 4:
          auto_exclude.add(n, reason='recent_4_consecutive')
  ```
  → NumberRecommender 제외 결정에 force_exclude 우선 적용

- **Tier 3-E: 데드 회귀×라인 이월률 자동 제외 룰** (★사용자 정정, 2026-04-28):

  **라인 정의** (옵션 A 확정): 정렬된 당첨번호+보너스 위치 (1라인=1처, 6라인=6처, 7라인=보너스볼)

  **사용자 명세 예시** (현재 = 2121회차):
  - 2회귀 = 2119회차 [1,2,3,4,5,6,7] → 3라인 번호 = 3, (2회귀, 3라인) 이월률 0이면 3번 데드 카운트+1
  - 100회귀 = 2021회차 [2,3,4,5,6,7,8] → 2라인 번호 = 3, (100회귀, 2라인) 이월률 0이면 3번 데드 카운트+1
  - 3번 데드 카운트 = 2 ≥ 2 → **자동 제외**

  **알고리즘**:
  ```python
  def detect_dead_carryover_lines(target_round, history, active_N_list):
      """
      각 번호 X에 대해:
      1. 각 활성 N회귀의 N회 전 회차에서 X가 있었던 라인 k 식별
      2. 학습 데이터 전체에서 (N, k) 조합 이월률 계산
         = t회차 라인 k 번호가 t+N회차에 출현하는 비율
      3. 이월률 = 0 → X 데드 카운트 +1
      4. 데드 카운트 ≥ 2 → X 자동 제외
      """
      auto_exclude = []
      
      for n in 1..45:
          dead_count = 0
          dead_details = []
          
          for N in active_N_list:
              target_N_round = target_round - N
              target_N_data = history[target_N_round]
              sorted_seven = sorted(target_N_data.numbers + [target_N_data.bonus])
              
              if n not in sorted_seven:
                  continue
              line_k = sorted_seven.index(n) + 1  # 1~7
              
              # (N, k) 이월률 학습 데이터 전체 계산
              carryover, total = 0, 0
              for t in range(1, len(history) - N):
                  t_seven = sorted(history[t].numbers + [history[t].bonus])
                  t_line_k_num = t_seven[line_k - 1]
                  t_plus_N_nums = set(history[t+N].numbers + [history[t+N].bonus])
                  if t_line_k_num in t_plus_N_nums:
                      carryover += 1
                  total += 1
              
              if total > 0 and carryover == 0:
                  dead_count += 1
                  dead_details.append(f'(N={N}, k={line_k}, X={n})')
          
          if dead_count >= 2:
              auto_exclude.append({
                  'number': n,
                  'reason': 'dead_carryover_lines',
                  'count': dead_count,
                  'details': dead_details
              })
      
      return auto_exclude
  ```

  **narrative 예시**:
  > "3번: 2회귀(2119회차) 3라인 + 100회귀(2021회차) 2라인에서 학습 데이터 이월률 0 → 2개 회귀 데드 패턴 → 출현 가능성 낮음 → 제외"

### Tier 4: 메타 분석 (Gemma 4 입력)

기존 통계 빈도 분석 + **MHN retrieval 추가**:
- 학습 데이터에서 패턴 P 빈도 (frequency≥0.20, support≥10)
- **MHN으로 현재 회차와 가장 유사한 과거 N회차 검색** → "이 회차는 [123, 456, 789]회차와 유사도 0.85+" 출력
- Gemma 4가 두 정보 통합해 narrative 합성

---

## 6. Phase 4 — 4 Pillar 추천/제외 엔진

### 4 Pillar 점수 시스템 (11 base 통합)

```
[7→11 base logits]
   ↓ ModelRankExtractor (모델별 순위 + 5분할 슬라이스)
   ↓
[NumberScorer 4 Pillar]
   ├─ Pillar 1 ensemble_prob:
   │    11 base 가중평균 + Bayesian NN 분포
   │    [q10, q50, q90] + 분산 σ
   ├─ Pillar 2 filter_compliance:
   │    21지표 필터 통과도 (가중 합산)
   ├─ Pillar 3 individual_state:
   │    핫콜드 + 미출현 + 회귀 Tier 2 (압축 8변수)
   │    + MHN retrieval (과거 비슷한 번호 패턴)
   └─ Pillar 4 model_consensus:
        11 base 순위 mean/std/top10_count/bottom15_count
        4 메트릭 통합 consensus_score
   ↓
[Ridge MetaLearner — 4 Pillar 가중치 학습]
   ↓ MoE 라우팅 (이상/정상 회차 구분)
   ↓
[NumberRecommender]
- 추천 5: 점수↑ + consensus.top10_count ≥ 4 + filter_compliance ≥ 평균+0.1
- 제외 10: 점수↓ + consensus.bottom15_count ≥ 4 + filter_compliance < 평균-0.1
   ↓
[NumberXAIExplainer] (Phase 5 신규)
   ↓
[NumberNarrativeGenerator — Gemma 4]
번호당 시그널/근거/결론 3섹션
```

### 모델별 자유 슬라이스 (5분할 default)

```python
DEFAULT_SLICES = [(1,9), (10,19), (20,29), (30,39), (40,45)]
```

`ModelRankExtractor`는 **11 base** 각각의 1~45 ranking 추출 + 슬라이스별 합집합/공집합 + pairwise [11×11] 매트릭스.

### Hard Filter 우선순위 (사용자 메모 + 자동 룰)

**NumberRecommender 제외/추천 결정 시 Hard Filter 3계층 우선순위**:

| 순위 | 종류 | 출처 | 동작 |
|---|---|---|---|
| **1 (최우선)** | **사용자 전문가 메모** | 사용자 직접 입력 (UI) | `prob = 0.0` 또는 강제 추천 |
| **2** | **자동 룰 1·2·3** | 시스템 자동 (4연번/데드 라인) | force_exclude 추가 |
| **3** | **4 Pillar 점수** | NumberScorer 결과 | 다중 조건 통과 시 후보 |

→ 사용자 메모가 항상 1순위. 시스템 자동 룰을 덮어쓸 수 있음.

### 자동 제외 룰 3개 (★사용자 정정 추가, 2026-04-28)

| 룰 | 조건 | 근거 |
|---|---|---|
| **룰 1: 회귀 4연번** | 어느 회귀 N(2~200)에서든 특정번호가 활성 **4연번 이상** | 회귀 패턴 한계 도달 → 다음 회차 미출현 가능성 ↑ |
| **룰 2: 1회귀 4연번** | **1회귀**(직전 출현)에서 4연번 이상 = **직전 4회차 연속 출현** | 핫스트릭 한계 → 평균회귀 시그널 |
| **룰 3: 데드 회귀×라인 이월률 ≥ 2** | 번호 X가 2개 이상 회귀의 라인 위치에서 **이월률 0**(학습 데이터 전체) | (N, 라인 k) 조합이 한 번도 이월 안 된 패턴 2개 이상 → 강한 미출현 시그널 |

### 사용자 전문가 메모 (Hard Filter 1순위)

기존 `ensemble.py::predict()` 의 `[3차 통제] 전문가 메모 (hard filter)` 단계 강화.

**데이터 구조** (Supabase `expert_memos` 테이블 신규):
```python
class ExpertMemo:
    memo_id: UUID
    target_round: int           # 2122
    forced_excludes: List[int]   # [42, 13, 27] — 강제 제외
    forced_includes: List[int]   # [23, 31]    — 강제 추천 (rec 5에 항상 포함)
    forced_filter_constraints: dict  # 사용자 직접 21지표 범위 강제
    memo_text: str               # 자유 메모
    priority: int = 1            # 항상 최우선
    created_by: user_id
    created_at: timestamp
```

**처리 단계** (ensemble.predict 갱신):
```python
def predict(draws, target_round):
    # 1차 결합 + 2차 AE 페널티 (기존)
    final_probs = ensemble_weighted_average()
    final_probs *= ae_anomaly_penalty()
    
    # 3차 통제 — Hard Filter 3계층 (★사용자 정정 갱신)
    # 우선순위 1: 사용자 메모
    expert_memo = load_expert_memo(target_round)
    if expert_memo:
        for n in expert_memo.forced_excludes:
            final_probs[n] = 0.0  # 강제 제외
        # 강제 추천은 NumberRecommender에서 top 5에 항상 포함
    
    # 우선순위 2: 자동 룰 (룰 1·2·3)
    auto_excluded = (apply_consecutive_4_rule() 
                     + apply_recent_4_consecutive_rule() 
                     + detect_dead_carryover_lines())
    for memo_excluded_n in auto_excluded:
        if memo_excluded_n.number not in expert_memo.forced_includes:
            # 사용자 메모로 강제 추천된 게 아니면 자동 제외 적용
            final_probs[memo_excluded_n.number] = 0.0
    
    # 4·5차 (기존)
    final_probs = normalize(final_probs)
    final_probs = meta_learner_stacking(final_probs)
    
    return final_probs
```

**UI 노출** (AI 프리미엄 영역 C 위):
```
┌─ 🎯 전문가 메모 (사용자 Hard Filter) ────────────┐
│ 강제 제외: [42] [13] [27] [+ 추가]                │
│ 강제 추천: [23] [31] [+ 추가]                     │
│ 메모 내용: [자유 입력 텍스트박스]                  │
│ [저장 → 즉시 추천/제외 갱신]                      │
│                                                   │
│ 사용자 메모 영향: 자동 룰 23번 제외 권고 → 메모로 │
│   덮어씌워 추천에 포함됨 ✓                        │
└───────────────────────────────────────────────────┘
```

**검증 페이지 추적**:
- 각 회차의 사용자 메모 영향 표시
- "사용자 메모 적중률": 강제 추천 hit / 강제 제외 hit 별도 추적
- 자동 룰 vs 사용자 메모 충돌 회수 통계

### 사용자 메모 → 딥러닝 학습 반영 (★사용자 정정 추가, 2026-04-28)

전문가 메모를 **단순 hard filter**가 아니라 **딥러닝 학습 시그널**로 반영. 메모 패턴 자체가 도메인 지식으로 모델에 학습됨.

**4 메커니즘**:

#### 메커니즘 1: 메모를 입력 Feature (Soft Signal)

```python
class ExpertMemoFeatureExtractor:
    """
    매 회차 메모 → 학습 feature 90~100차원
    
    출력:
    - forced_excludes_45 (binary 45D)
    - forced_includes_45 (binary 45D)
    - memo_hit_rate_recent_50 (시계열 10D)
    - memo_domain_confidence (스칼라, 0~1)
    """
```

→ 모든 11 base 모델 입력 차원에 90~100 추가.

#### 메커니즘 2: Loss 보조항 (Memo Consistency Loss)

```python
def total_loss_with_memo(predictions, labels, memo, memo_confidence):
    main_loss = BCEWithLogitsLoss(predictions, labels)
    
    memo_loss = 0.0
    for n in memo.forced_includes:
        if labels[n] == 1:
            memo_loss -= 0.1 * predictions[n]   # 출현 → prob ↑ 유도
    for n in memo.forced_excludes:
        if labels[n] == 0:
            memo_loss += 0.1 * predictions[n]   # 미출현 → prob ↓ 유도
    
    # 메모 신뢰도 기반 동적 가중 (적중률 ↑ → 메모 영향 ↑)
    return main_loss + memo_confidence * memo_loss
```

#### 메커니즘 3: 메모 적중률 추적 + 신뢰도 동적 조정

```python
class ExpertMemoHistoryTracker:
    """
    매 회차 메모 적중 결과 누적 → memo_domain_confidence 동적 갱신
    
    - memo_hit_rate = mean(recent 50 회차 forced_inc_hit / 5)
    - memo_domain_confidence = sigmoid((memo_hit_rate - 0.5) * 5)
    """
    
    def update(self, target_round, memo, actual_winning_numbers):
        forced_inc_hit = len(set(memo.forced_includes) & set(actual_winning_numbers))
        forced_exc_hit = len(set(memo.forced_excludes) - set(actual_winning_numbers))
        # ... 신뢰도 계산
        return memo_domain_confidence
```

#### 메커니즘 4: MoE 라우팅에 메모 expert

```python
# MoE Expert 4 (메모 활성 회차 전용)
if memo_domain_confidence > 0.7:
    expert_4_weight = memo_domain_confidence  # 메모 영향 강화 expert
else:
    expert_4_weight = 0.0  # 다른 expert로 라우팅
```

**통합 흐름**:
```
사용자 메모 입력 (UI)
   ↓ Supabase expert_memos 저장
ExpertMemoFeatureExtractor (90D feature)
   ↓
모든 11 base 모델 입력 + 90D
   ↓ 학습 시:
TotalLoss = MainLoss + memo_confidence × MemoConsistencyLoss
   ↓ 추론 시:
final_probs = ensemble_with_memo_input()
   ↓ 후처리:
Hard Filter (사용자 메모 1순위 + 자동 룰 2순위)
   ↓
NumberRecommender → 추천 5 + 제외 10
   ↓ 결과 검증 후:
ExpertMemoHistoryTracker.update() → memo_domain_confidence 갱신
```

→ 메모 자체가 **시간 따라 자동 학습되는 도메인 지식**.

**신규 파일** (메모 학습 시스템):
- `langchain-backend/models/expert_memo_extractor.py` — 메모 → feature 변환
- `langchain-backend/services/expert_memo_history.py` — 적중률 추적 + 신뢰도 갱신
- `langchain-backend/pipeline/memo_loss.py` — 메모 일치 보조 손실

**신규 Supabase 테이블 2개**:
- `expert_memos` — 회차별 메모 입력 (memo_id, target_round, forced_*, memo_text)
- `expert_memo_history` — 회차별 적중 결과 + 신뢰도 누적

**통합 로직**:
```python
def select_exclusions_with_consecutive_rules(scores, regression_data, n_exc=10):
    # 자동 룰 1: 회귀 N에서 4연번 이상
    rule_1 = [n for n in 1..45 if any(
        regression_data[n][N].max_consecutive >= 4
        for N in active_regression_N
    )]
    
    # 자동 룰 2: 1회귀에서 4연번 이상 (직전 4회차 연속 출현)
    rule_2 = [n for n in 1..45 
              if get_consecutive_appearance(n, regression_N=1) >= 4]
    
    # 자동 제외 (force_exclude) — 우선
    auto_excluded = list(set(rule_1 + rule_2))
    
    # 기존 4 Pillar 다중 조건 통과 후보
    pillar_excluded = select_pillar_exclusion_candidates(scores)
    
    # 통합: 자동 룰이 우선 (강제), Pillar이 부족분 채움
    return merge_with_priority(auto_excluded, pillar_excluded, n=10)
```

**검증 출력 (각 제외 번호별)**:
- `exclusion_reason`: "regression_consecutive_N{k}" 또는 "recent_4_consecutive" 또는 "pillar_score_low"
- `force_exclude`: True/False (자동 룰 적용 여부)
- narrative에 자동 룰 사유 명시:
  - "42번: 12회귀에서 4연번 활성 → 회귀 패턴 한계 → 다음 회차 미출현 가능성 높음"
  - "23번: 직전 4회차 연속 출현 → 핫스트릭 한계 → 평균회귀 시그널"

### 50회차 백테스트 + Pillar 가중치 자동 조정

```python
class RecommendationBacktest:
    """
    walk-forward 50회차 시뮬레이션
    각 Pillar별 hit 기여도 측정 (SHAP-style attribution)
    Pillar 가중치 자동 갱신 → saved_models/pillar_meta_weights.json
    
    안전장치:
    - 추천 hit ≤1.5 시 경고 + Pillar 가중치 큰 변화
    - 제외 hit ≥2 시 임계값 강화
    """
```

### CombinationScorer — AI 조합기 (★사용자 정정 추가, 2026-04-28)

`ai_combination.html`에 이미 구현된 시스템을 4 Pillar + 11 base + 21지표로 강화.

**위치**: 4 Pillar 추천/제외 직후 호출. 사용자 필터 통과 조합 풀에 점수 부여.

**입력**:
- 사용자 필터 통과 조합 풀 (`localStorage.generated_filter_combos`)
- 11 base 모델 출력 (1~45 prob)
- 4 Pillar 추천 5 + 제외 10
- 21지표 필터 예측 (sum 범위·끝수합·AC·홀짝·저고·소수·제곱수·삼각수·연속수)

**점수 공식**:
```python
def score_combination(combo, ai_data, filter_predictions):
    nums = combo.numbers  # 6 numbers
    
    # (A) 번호별 11 base 앙상블 점수 (Pillar 1 활용)
    number_score = mean(normalize(scoreMap[n]) for n in nums)  # 0~100
    
    # (B) 4 Pillar 추천 5와 매칭
    fixed_bonus = sum(15 for n in nums if n in pillar_recommend_5)
    
    # (C) 4 Pillar 제외 10와 매칭
    exclude_penalty = sum(20 for n in nums if n in pillar_exclude_10)
    
    # (D) 21지표 필터 통과도
    filter_score = 0
    if in_range(sum(nums), filter_predictions['총합']):       filter_score += 10
    if in_range(tail_sum(nums), filter_predictions['끝수합']): filter_score += 8
    if in_range(ac_value(nums), filter_predictions['AC값']):  filter_score += 8
    if in_range(prime_count(nums), filter_predictions['소수']): filter_score += 6
    if in_range(square_count(nums), filter_predictions['제곱수']): filter_score += 4
    if in_range(triangular_count(nums), filter_predictions['삼각수']): filter_score += 4
    if in_range(consecutive(nums), filter_predictions['연속수']): filter_score += 5
    if pattern_match(odd_count(nums), filter_predictions['홀짝']): filter_score += 8
    if pattern_match(high_count(nums), filter_predictions['저고']): filter_score += 8
    
    # (E) 조합 다양성 보너스 (GNN edge_prob + AE 이상도)
    diversity_bonus = gnn_edge_prob_sum(nums) - ae_anomaly(nums) * 5
    
    return number_score + fixed_bonus - exclude_penalty + filter_score + diversity_bonus
```

**출력**:
- 정렬된 조합 리스트 + 각 조합 점수
- 상위 5/10/15/20 사용자 선택 (UI 토글)
- 조합별 narrative (Gemma 4 — 흐름/추세/추천)

**기존 ai_combination.html 갱신 사항**:
- 현재 점수 공식: number_score + fixed_bonus - exclude_penalty + filter_score
- 갱신: + diversity_bonus (GNN+AE) + Bayesian σ 신뢰도 표시

**신규 파일**: `langchain-backend/models/combination_scorer.py`

---

## 7. Phase 5 — NumberXAIExplainer 컴포넌트 (신규, 사용자 결정 옵션 B)

### 위치 및 목적

각 추천/제외 번호에 대해 **다층 XAI 출력**. NumberRecommender 직후 호출, NumberNarrativeGenerator(Gemma) 입력.

### 11 base 모델별 XAI 입력

| 모델 | XAI 출력 |
|---|---|
| XGBoost | TreeSHAP feature 기여도 |
| CatBoost | TreeSHAP feature 기여도 |
| TabNet | Sparsemax attention mask (feature selection) |
| CNN | Grad-CAM (그리드 위치별 기여) |
| GNN(GAT) | Attention weights (어느 인접 번호 영향) |
| Markov | 전이행렬 직접 노출 |
| AE | 재구성 오차 |
| TFT | Variable selection weights (어느 변수 중요) |
| N-BEATS | trend/seasonality/residual 분해 |
| MHN | top-K 유사 과거 회차 + similarity |
| Bayesian NN | 분산 σ (불확실성) |

### 통합 처리

```python
class NumberXAIExplainer:
    """
    11 base XAI + 4 Pillar 분해 + 21지표 필터 통과도 통합 → Gemma 4 narrative.
    
    Layer 1 (자연어 narrative — Gemma 4 합성):
      시그널 / 근거 / 결론 3섹션
    
    Layer 2 (4 Pillar 미니바 + 모델 합의도):
      ENS / FLT / STA / CNS 4개 게이지
      11 base 모델 합의도 시각화
    
    Layer 3 (기여 변수 시각화):
      - SHAP top-5 feature
      - TabNet attention mask (활성 feature 표시)
      - TFT variable selection top-5
      - N-BEATS 분해 그래프
      - MHN top-3 유사 회차
      - Bayesian NN 분산 σ 게이지
    """
```

### 신규 파일

- `langchain-backend/models/number_xai_explainer.py` — 통합 XAI 시스템
- `langchain-backend/services/xai_aggregator.py` — 11 base XAI 통합기
- `langchain-backend/prompts/xai_narrative_prompt.txt` — Gemma 4 시스템 프롬프트

### 외부 라이브러리

- **SHAP** (TreeSHAP for XGBoost/CatBoost)
- **Captum** (PyTorch — Integrated Gradients, DeepLIFT)
- **TabNet 자체 출력** (attention mask)
- **PyTorch Forecasting** (TFT VSN 출력)

---

## 8. Phase 6 — 프론트엔드 4 페이지 (★사용자 정정: 4 페이지)

### 페이지 매핑

| # | 페이지명 | 파일 | 역할 |
|---|---|---|---|
| 1 | **분석 지표별 AI 프리미엄 인사이트** | `total_sum.html`, `tail_sum.html`, `ac_value.html`, `low_high.html`, `odd_even.html`, `carryover.html`, `consecutive_number.html`, `neighbor_number.html`, `tail_digit.html`, `number_range.html`, `magic_square.html`, `lotto_paper.html`, `multiple.html`, `prime_number.html`, `composite_number.html`, `square_number.html`, `triangular_number.html`, `twin_number.html`, `hot_cold.html`, `missing.html`, `regression.html`, `custom_analysis.html` (총 22개 분석 지표 페이지) | 각 페이지의 `<div id="dlInsightContainer">` — DeepInsightPanel v3.0 |
| 2 | **딥러닝 분석 페이지** | `ai_deep_learning.html` (6 탭) | 전체 분석 대시보드 — 21지표·회귀·모델 디테일 |
| 3 | **AI 조합** | `ai_combination.html` | 필터 통과 조합 + AI 점수 + 상위 N 선택 |
| 4 | **검증** | `verification.html` (7 탭) | 회차별 hit 검증·필터 통과·4 Pillar 추적 |

### 공통 디자인 시스템

- 디자인 토큰 (`--c-primary`, `--c-primary-ai`, `--c-ok`, `--c-fail`)
- 7→**11 모델 색상 토큰** 확장:
  ```
  XGB #3B82F6 / CatBoost #14B8A6 / TabNet #A855F7 / CNN #EC4899
  GNN #EF4444 / Markov #10B981 / AE #8B5CF6 / TFT #F97316
  N-BEATS #06B6D4 / MHN #84CC16 / Bayesian #F59E0B
  ```
- **ECharts 도입** (5 시각화: heatmap×2, 신뢰구간, 시계열, sparkline)
- 신규 컴포넌트 9개 + **NumberXAIExplainerCard 신규 추가**

### 4 페이지 구조 (★사용자 결정: 4 페이지 명세)

#### 페이지 1: 분석 지표별 AI 프리미엄 인사이트 (22개 페이지 공통 컴포넌트)

**범위**: 22개 분석 지표 페이지 각각에 들어가는 `<div id="dlInsightContainer">` (DeepInsightPanel v3.0)

**구현 핵심**: `js/deep_insight_panel_v3.js` 컴포넌트가 페이지 컨텍스트(현재 분석 지표)를 자동 감지해 **그 지표 전용 모델·feature·narrative**를 표시.

**4 영역 (모든 22개 페이지 공통 구조, 데이터만 변동)**:
- **A**: 다크 프리미엄 헤더 + 신뢰도 게이지 (Pillar 4 평균 합의도)
- **B**: **페이지 컨텍스트 모델 카드** — 그 지표에 적용된 11 base 중 활성 모델만 표시 (★표 1 참조)
- **C**: 4 Pillar 추천 5 + 제외 10 + **NumberXAIExplainerCard 펼침**
- **D**: Gemma 4 종합 narrative (흐름/추세/추천)

**페이지별 활성 모델 매핑** (★표 1 참조):
- 총합 페이지 → XGB(★) + TFT(★) + N-BEATS(★) + Markov(✓) + AE(✓) + GNN(✓) + Cat(✓) + TabNet(✓) + Bayesian(✓) (9 모델)
- 끝수합 페이지 → 위 + CNN(✓) (10 모델, scalar+distribution head)
- AC값 페이지 → XGB + Markov(★) + TFT + N-BEATS + Cat + Bayesian (6 모델)
- 고저/홀짝 페이지 → XGB + Cat + Markov + TFT + GNN (5 모델)
- 끝수0~9 페이지 → XGB + Cat + TabNet + Markov + GNN + TFT + Bayesian (7 모델, IndependentCountPredictor 대표)
- 번호대/9궁/로또용지 페이지 → 위 + (로또용지는 +CNN)
- 배수 페이지 → 매핑 매트릭스 활용
- 소수/합성수/제곱수/삼각수/동형수 페이지 → XGB + Cat + Markov + GNN + TFT (5 모델, 단일)
- 미출현그룹 페이지 → XGB + Cat + TabNet + GNN + Markov + AE + TFT (7 모델, 동적)
- 핫콜드 페이지 → 동일 7 모델 (12 카테고리)
- 회귀 페이지 → DynamicIndependentCountPredictor + MHN(Tier 4) (8 모델)
- **커스텀 분석 페이지** (`custom_analysis.html`) → **모든 11 base + MHN 매칭 + 동적 통계 + 회귀 전수조사**

**구현 방법**:

```javascript
// js/deep_insight_panel_v3.js
class DeepInsightPanelV3 {
  init(pageContext) {
    // pageContext = {indicator: 'total_sum', target_round: 1234, ...}
    
    // 1. 페이지별 활성 모델 결정 (표 1 매핑)
    const activeModels = this.getActiveModelsForIndicator(pageContext.indicator);
    
    // 2. API 호출 (Supabase deep_analysis_history 또는 aiProxy)
    const data = await this.fetchAnalysisData(pageContext);
    
    // 3. 4 영역 렌더링
    this.renderHeaderA(data);          // 다크 헤더 + 신뢰도
    this.renderContextModelsB(activeModels, data);  // 활성 모델 카드
    this.renderPillarCardsC(data);     // 4 Pillar + XAI
    this.renderGemmaNarrativeD(data);  // 흐름/추세/추천
  }
  
  getActiveModelsForIndicator(indicator) {
    // 표 1 매트릭스 기반 매핑
    return INDICATOR_MODEL_MATRIX[indicator] || [];
  }
}
```

**HTML 구조** (모든 22개 페이지 동일):
```html
<!-- 분석 지표 페이지 어디든 이 컨테이너만 있으면 자동 렌더링 -->
<div id="dlInsightContainer" 
     data-indicator="total_sum"  <!-- 페이지 컨텍스트 -->
     class="mb-6">
</div>
<script src="js/deep_insight_panel_v3.js"></script>
<script>DeepInsightPanelV3.init({indicator: 'total_sum'});</script>
```

**데이터 소스**:
- 백엔드 API: `routes/deep_analysis_v3.py::get_indicator_analysis(indicator)`
- Supabase 캐시: `deep_analysis_history` 테이블
- LRU 캐시 (U-4): Gemma 4 narrative 결과

**커스텀 분석 페이지 특수 처리** (`custom_analysis.html`):
- 위 4 영역 + **추가 영역 E**: 동적 통계 대시보드 (3카드: 현재상태/역대기록/출현확률)
- **추가 영역 F**: 분석 데이터 히스토리 테이블 (가변 컬럼, 최대 1200px height)
- **추가 영역 G**: 회귀 전수조사 모드 토글 (`#mode-regression-scan` 모드 전환)
- **추가 영역 H**: 통계 상세 모달 (`#statsModal` — 번호대별 상세 통계)

#### 페이지 2: 딥러닝 페이지 6 탭 (`ai_deep_learning.html`)

- **#tab-status**: 11모델 컨디션 + RankSliceSelector + ConsensusMatrix [11×11] heatmap
- **#tab-summary**: 4 Pillar 추천/제외 + Pillar 분해 + **NumberXAIExplainerCard**
- **#tab-filters**: 21개 IndicatorCard (영역 1: 11모델 필터값 + 영역 2: 앙상블 + ECharts 신뢰구간 + 영역 3: 흐름/추세/추천 + N-BEATS 분해)
- **#tab-regression**: 4 Tier (Tier 1 sparkline / Tier 2 압축 변수 + MHN retrieval / Tier 3 heatmap + 자동 룰 / Tier 4 메타 + MHN 유사 회차)
- **#tab-custom**: 기존 유지
- **#tab-recommend**: 4 Pillar 기반 조합 6개 + 21지표 통과율 + 조합 narrative

#### 페이지 3: AI 조합 (`ai_combination.html`) ★사용자 정정 추가

**역할**: 사용자 필터 통과 조합 풀 (`localStorage.generated_filter_combos`)에 AI 점수 부여 → 상위 N 선택 → Supabase 저장.

**현재 구현**: 점수 = 번호별 앙상블 + 고정수 보너스 + 제외수 페널티 + 21지표 필터 통과
**갱신 후**: + 4 Pillar 결과 + 11 base ensemble + GNN 다양성 보너스 + Bayesian σ 신뢰도 + Gemma 조합 narrative

**페이지 구조 (현재 유지 + 강화)**:

```
[헤더 — sticky]
  타이틀 "AI 딥러닝 추천 조합"
  AI분석중 배지 (보라)
  뒤로 가기 버튼

[컨트롤 바 — sticky top:64px]
  상위 선택 토글: [5개] [10개] [15개] [20개]  ← 사용자 N 선택
  전체/해제 버튼
  선택 뜨지 + 저장 버튼

[요약 정보 — 3 카드 그리드]
  카드 1: 분석 대상 회차 + 신뢰도 (Bayesian σ 표시)
  카드 2: 필터 통과 풀 크기
  카드 3: AI 추천/고정수 (4 Pillar 추천 5 표시)

[조합 리스트]
  헤더: "AI 점수 상위 조합" + 개수 + 풀 크기
  각 조합 row:
    - 순위 (01~)
    - 6 번호 볼 (4 Pillar 추천 매칭 시 halo + dot 표시)
    - AI점수 게이지 (0~100%)
    - 합·홀짝 통계
    - F+ 필터 통과 점수
    - ★ 고정수 매칭 개수
    - 선택 토글 (radio)
    - **신규: 클릭 시 펼침 → 조합 narrative (흐름/추세/추천)**
```

**구현 핵심** (기존 `AIC` 모듈 갱신):

```javascript
// js/ai_combination.js (기존 인라인 → 외부 파일로 분리 + 갱신)
const AIC = (() => {
  // 기존: scoreAndSort()에서 점수 공식
  function scoreAndSort() {
    // ... 기존 (A) 번호별 앙상블 + (B) 고정/제외 + (C) 필터 통과
    
    // 신규 추가:
    // (D) 4 Pillar 매칭 (number-recommendation-plan 결과 활용)
    const pillarFixed = pillarData.recommend_5 || [];
    const pillarExclude = pillarData.exclude_10 || [];
    
    // (E) GNN 다양성 보너스 (인접쌍 + 분포 다양성)
    const diversityBonus = computeDiversityBonus(nums);  // GNN edge_prob 활용
    
    // (F) Bayesian σ 신뢰도
    const confidence = 1 - bayesianStd[combo];  // 분산 작을수록 신뢰도 ↑
    
    return {
      ...combo,
      aiScore: numScore + fixedBonus - exclPenalty + filterScore + diversityBonus,
      confidence,  // 새 필드
      narrative: gemmaResult,  // 새 필드 (흐름/추세/추천)
    };
  }
  
  // 신규: 조합 narrative 펼침
  function showCombinationNarrative(idx) {
    const combo = displayed[idx];
    // Gemma 4 narrative 표시 (흐름/추세/추천)
  }
})();
```

**API 변경**:
- 기존: `deep_analysis_history` 단일 테이블 조회
- 신규: + 4 Pillar 결과 (`pillar_meta_weights.json` 활용) + Gemma narrative API

**저장 페이로드 갱신** (`saved_combination_groups`):
```python
{
  ..., # 기존
  'pillar_data': {recommend_5, exclude_10, pillar_weights},  # 신규
  'gemma_narrative': '흐름:..., 추세:..., 추천:...',  # 신규
  'confidence_avg': 0.78,  # 신규
}
```

#### 페이지 4: 검증 페이지 7 탭 (`verification.html`)

딥러닝분석필터 탭 서브탭 6개:
- 추천수 검증 (★★★ 적중 + Pillar 분해 + **XAI 펼침**)
- 제외수 검증
- 기초필터 검증 (21지표 통과 매트릭스)
- 회귀필터 검증 (Tier 1·3 적중 + 자동 룰 적중)
- 모델별 검증 (11모델 정확도 비교)
- 종합 narrative (Gemma 4 회차별 흐름/추세/추천)

### Narrative 형식 (사용자 결정 — 둘 다 유지)

| 형식 | 단위 | 위치 |
|---|---|---|
| 흐름/추세/추천 | 페이지 지표 | AI 프리미엄 영역 D / 딥러닝 #tab-filters / 검증 종합 |
| 시그널/근거/결론 | 번호 | AI 프리미엄 영역 C 펼침 / 딥러닝 #tab-summary / 검증 추천수·제외수 |

`<NarrativeSection mode="flow">` / `<NarrativeSection mode="rationale">` 분기.

---

## 9. Cross-feedback 통합 흐름 (전체 시스템)

```
Phase 0: Self-Supervised Pretraining (G-8)
        ↓ pretrained_backbone.pt
Phase 1 백엔드 독립 예측기 (Phase 1 위계)
  ├─ 끝수0~9, 고저, 홀짝, 이월수×2, 이웃수, 연번
  ├─ 번호대, 9궁, 로또용지, 배수, 소수합성수+1
  ├─ 삼각수, 제곱수, 동형수
  ├─ 미출현그룹(광역4), 핫콜드(12)
  └─ 회귀 Tier 1 (가변 N) — TFT 통합
        ↓ predicted dist[7] + expected + "M중 N" narrative
Phase 2: 끝수합 (← 끝수 분포 + large_endings_ratio)
        ↓
Phase 3: AC값 (← Phase 1+2 다수)
        ↓
Phase 4: 총합 (← sum 카르텟 + N-BEATS 분해 + 모든 약 시그널)
        ↓
[NumberScorer 4 Pillar]
  ├─ Pillar 1: ensemble_prob (11 base + Bayesian NN 분산)
  ├─ Pillar 2: filter_compliance (Phase 1~4 21지표)
  ├─ Pillar 3: individual_state (핫콜드+미출현+회귀 Tier 2 + MHN 매칭)
  └─ Pillar 4: model_consensus (11 base ranking 통계)
        ↓
[MetaLearner Ridge + MoE 라우팅]
        ↓
[NumberRecommender] → 추천 5 + 제외 10
        ↓
[NumberXAIExplainer] (신규)
  L1 narrative + L2 4 Pillar 미니바 + L3 11 base XAI
        ↓
[NumberNarrativeGenerator Gemma 4]
  시그널/근거/결론 3섹션
        ↓
프론트엔드 3 페이지
  ├─ AI 프리미엄 (영역 C+D + XAI 카드)
  ├─ 딥러닝 (#tab-summary 4 Pillar + #tab-filters 21지표 + Tier 4 + XAI)
  └─ 검증 (추천수/제외수 hit + XAI + 종합 narrative)
```

---

## 10. 신규/수정 파일 정리

### 신규 모델·인프라 파일 (총 16개)

**신규 모델 (7개)**:
1. `langchain-backend/models/tft_model.py` (LSTM/TF 흡수)
2. `langchain-backend/models/catboost_model.py`
3. `langchain-backend/models/tabnet_model.py`
4. `langchain-backend/models/nbeats_model.py`
5. `langchain-backend/models/mhn_model.py`
6. `langchain-backend/models/bayesian_model.py`
7. `langchain-backend/models/moe_router.py`

**신규 XAI (1개, Phase 5)**:
8. `langchain-backend/models/number_xai_explainer.py`

**기존 plan 신규 모델 (6개)**:
9. `langchain-backend/models/sum_predictor.py`
10. `langchain-backend/models/endings_predictor.py`
11. `langchain-backend/models/ac_predictor.py`
12. `langchain-backend/models/categorical_count_predictor.py`
13. `langchain-backend/models/independent_count_predictor.py`
14. `langchain-backend/models/regression_predictor.py`

**기존 plan 신규 4 Pillar (5개)**:
15. `langchain-backend/models/number_scorer.py`
16. `langchain-backend/models/model_rank_extractor.py`
17. `langchain-backend/models/consensus_analyzer.py`
18. `langchain-backend/models/number_recommender.py`
19. `langchain-backend/services/number_narrative.py`

**인프라 (5개)**:
20. `langchain-backend/pretraining/self_supervised.py`
21. `langchain-backend/services/xai_aggregator.py`
22. `langchain-backend/services/regression_filter_rules.py`
23. `langchain-backend/services/regression_meta_analyzer.py`
24. `langchain-backend/validation/recommendation_backtest.py`

**Feature 빌더 (3개)**:
25. `langchain-backend/features/scalar_features.py`
26. `langchain-backend/features/categorical_features.py`
27. `langchain-backend/features/regression_features.py`

**Validation (2개, U 시리즈 일부)**:
28. `langchain-backend/validation/timeseries_cv.py` ✅ (이미 있음)
29. `langchain-backend/validation/baselines.py` ✅ (이미 있음)

**프롬프트 (2개)**:
30. `langchain-backend/prompts/xai_narrative_prompt.txt`
31. `langchain-backend/prompts/number_narrative_3section.txt`

### 수정 파일 (총 9개)

32. `models/ensemble.py` — 11 base + MoE 통합
33. `models/meta_learner.py` — MoE 라우팅 통합
34. `pipeline/training_orchestrator.py` — DAG 7단계 (G-8 추가)
35. `pipeline/weekly_pipeline_v2.py` — 모든 신규 컴포넌트 호출
36. `services/filter_stats.py` — 신규 메서드 (`_endings_distribution`, `_decade_distribution`, `_gung_distribution`, `_paper_distribution`, `_missing_group_distribution`, `_regression_distribution`, `_multiple_4`, `_multiple_5`) + "M중 N" 형식 통일
37. `routes/deep_analysis_v3.py` — 신규 모델 라우팅
38. `config.py` — 모든 신규 하이퍼파라미터
39. `lstm_model.py`, `transformer_model.py` — deprecated 표시 (TFT 흡수)

### 프론트엔드 (총 11개 신규/수정)

**신규 컴포넌트 (`js/components/`)**:
40. `narrative_section.js` (mode prop)
41. `model_badge.js` (11 모델 색상)
42. `mn_format.js`
43. `rank_slice_selector.js`
44. `consensus_matrix.js` (ECharts heatmap)
45. `indicator_card.js` (영역 1·2·3 + ECharts 신뢰구간)
46. `confidence_bar.js`
47. `hit_history_chart.js` (ECharts 시계열)
48. `filter_compliance_badge.js`
49. **`number_xai_explainer_card.js`** (신규 — Phase 5)

**페이지 컨트롤러**:
50. `js/deep_insight_panel_v3.js` (v2.0 폐기 후 v3.0)

**HTML 수정**:
51. `custom_analysis.html` — `dlInsightContainer` v3.0 구조
52. `ai_deep_learning.html` — 6 탭 내용 재구성
53. `verification.html` — 딥러닝분석필터 탭 서브탭 6개

**CSS**:
54. `css/components.css` (Tailwind utility 조합)

### 캐시·저장 모델 (총 12개)

55. `saved_models/tft.pt`, `catboost.pkl`, `tabnet.pt`, `nbeats.pt`, `mhn.pt`, `bayesian.pt`, `moe_router.pt`
56. `saved_models/pretrained_backbone.pt` (G-8)
57. `saved_models/pillar_meta_weights.json`
58. `saved_models/regression_meta_patterns.json`

---

## 11. 구현 우선순위 (병렬 동시 도입, 사용자 결정)

### Sprint 1 (1주차) — 인프라 + 가벼운 모델
- G-1~G-7 글로벌 수정 (이미 일부 완료)
- **G-8 Self-Supervised Pretraining 파이프라인 구축**
- **CatBoost 통합** (XGBoost 패턴 재사용, 가장 빠름)
- **N-BEATS** (스칼라 지표만)
- **MHN** (회귀 Tier 4 + Pillar 3)
- 21지표 IndependentCountPredictor 강화 패턴 (Phase 1 고저/홀짝부터)

### Sprint 2 (2주차) — 큰 변화
- **TFT** (LSTM/Transformer 흡수, 가장 큰 변화)
- **TabNet** (8번째 base, attention 통합)
- **Bayesian NN** (Pillar 1 보강)
- 21지표 Phase 1~4 진행 (끝수합·AC·총합 cross-feedback)

### Sprint 3 (3주차) — 메타 진화 + 회귀
- **MoE 라우팅** (메타러너 진화)
- 회귀 4 Tier 본격 구축
- 4 Pillar 추천/제외 엔진 통합

### Sprint 4 (4주차) — XAI + 프론트
- **NumberXAIExplainer 컴포넌트** (신규 Phase 5)
- 프론트 3 페이지 IndicatorCard / RankSliceSelector / NumberXAIExplainerCard
- ECharts 통합

### Sprint 5 (5주차) — 통합 검증
- 50회차 백테스트
- Pillar 가중치 동적 조정 시작
- 통합 narrative 품질 검수
- 4 plan 본문 갱신 + 본 unified plan 갱신

---

## 12. 검증 (성공 기준)

### 백엔드 검증

#### 모델 단독
- [ ] G-1~G-8 글로벌 수정 후 학습 수렴 정상화
- [ ] 11 base 각자 베이스라인 이김
- [ ] 11 base 다양성 — Pearson 상관 < 0.7 (페어별)
- [ ] Self-Supervised pretrain 후 모든 신경망 수렴 속도 30%+ 향상

#### 21지표
- [ ] 각 IndependentCountPredictor가 빈도분포 베이스라인 CE 이김
- [ ] 보조 일관성 Σ_k expected ≈ 6 (오차 <0.5)
- [ ] sum 추정 카르텟 SHAP 상위 7 진입 (4식 모두)
- [ ] 모든 카테고리 지표 출력에 "M중 N" 형식 통일

#### 회귀 4 Tier
- [ ] Tier 1 활성 N별 분류기 베이스라인 이김
- [ ] Tier 3-C 자동 룰 (사용자 항목 E "11/14/19 → 0-1 필터") 실제 데이터 검증
- [ ] Tier 4 MHN top-K 유사 회차 검색 정확도

#### 4 Pillar 추천/제외 (가장 중요)
- [ ] **추천 hit 평균 1 → 2~3** (50회차 백테스트)
- [ ] **제외 hit 평균 1-2 → 0~1** 감소
- [ ] consensus_score(Pillar 4) 메타러너 SHAP 상위 1~2
- [ ] Bayesian NN 분산 σ가 추천 신뢰도와 양의 상관

#### NumberXAIExplainer
- [ ] 11 base 모델 각자 XAI 출력 정상 수집
- [ ] L1 narrative 자연어 품질 (시그널/근거/결론)
- [ ] L2 4 Pillar 미니바 정확
- [ ] L3 SHAP·attention·VSN·MHN·Bayesian σ 시각화 정상

### 프론트엔드 검증

- [ ] AI 프리미엄 영역 B 페이지 컨텍스트별 활성 모델 정확
- [ ] Gemma narrative 두 형식 분기 (`mode="flow"` vs `"rationale"`)
- [ ] 21개 IndicatorCard 통일 구조
- [ ] RankSliceSelector 5분할 + 사용자 정의
- [ ] ConsensusMatrix [11×11] heatmap 정확
- [ ] **NumberXAIExplainerCard 3 Layer** (narrative + 미니바 + SHAP 시각화)
- [ ] ECharts 5 시각화 정상 렌더링
- [ ] 데스크탑 lg/xl 2~3 컬럼

### 통합 검증

- [ ] 모든 시스템 함께 실행 시 충돌 없음
- [ ] Phase 위계 0→4 cross-feedback 정상
- [ ] Gemma 4 LRU 캐시 hit율 ≥80%
- [ ] 주간 백테스트 + Pillar 가중치 자동 갱신
- [ ] MoE 라우팅 이상 회차 90%+ 정확

---

## 13. 미해결 / 추후 결정

- TFT 라이브러리 (PyTorch Forecasting vs 자체 구현)
- Bayesian NN 라이브러리 (pyro-ppl vs MC Dropout)
- MoE expert 개수 (3개로 시작, 학습 후 조정)
- Self-Supervised 마스킹 비율 (15% BERT 기본)
- LSTM/Transformer 즉시 삭제 vs deprecated 6개월 후 제거
- 모바일 우선순위 (현재 데스크탑 우선)
- 다크 모드 (현재 라이트 모드만)

---

## 14. 부록

### 보존된 원본 plan 파일 (디테일 참조용)
- `kind-hugging-matsumoto.md` — 19지표 + 글로벌 G-1~G-7
- `회귀-plan.md` — 회귀 4 Tier
- `number-recommendation-plan.md` — 4 Pillar
- `frontend-design-plan.md` — 3 페이지 UI/UX
- `lotto_lab-master-plan.md` — 이전 압축 마스터
- `advanced-models-plan.md` — 8 신규 모델 도입

### 메모리 파일
`C:\Users\user\.claude\projects\C--Users-user-Desktop-windhomepage\memory\`
- `lotto_lab_project.md`, `feedback_no_disclaimers.md`, `feedback_no_cost.md`
- `reference_lotto_lab_repo.md`, `project_indicators_plan.md`

### GitHub 리포 핵심 경로
- `langchain-backend/models/`, `services/`, `pipeline/`, `routes/`, `validation/`
- `docs/deeplearning_renewal.md` (사용자 자체 작성, 3192줄)

---

## 다음 단계 (시작 시)

1. 현재 GitHub commit 점검 (Phase A 인프라 검증)
2. **Sprint 1 시작**: Self-Supervised + CatBoost + N-BEATS + MHN + Phase 1 IndependentCountPredictor 1~2개
3. 각 Sprint 완료 후 본 unified plan 갱신
4. 최종 50회차 백테스트로 추천/제외 hit 목표 달성 검증
