# Lotto_lab 딥러닝 전면 개편 — 단일 마스터 Plan

## Context

### 본 plan의 위치 — 기존 plan 수용 + 충돌 해결 통합본
사용자는 그동안 다른 작업 환경에서 누적 5개 plan(`kind-hugging-matsumoto.md`, `회귀-plan.md`, `number-recommendation-plan.md`, `lotto_lab-unified-plan.md`, `deeplearning_renewal.md`)을 통해 22개 핵심 결정을 합의해 왔다. 이 결정들은 모두 유효하며 본 plan의 출발점이다.

본 plan은:
- **기존 4 plan의 22개 결정을 그대로 수용** (1 제외, 이월수 보너스 변형, 핫콜드 12, 미출현 광역 4, 4 Pillar, 11 base, TFT 흡수, 5분할 슬라이스, ECharts, 자동 룰 3개, 전문가 메모 학습 시그널 등 전부 보존)
- **외형적 충돌만 사용자 결정으로 통일** (메인 INPUT_DIM 동결 vs 확장 등 plan 사이에서 명시적으로 결정 안 된 항목)
- **이행 순서를 21지표 → 회귀 → 4 Pillar로 단계화**
- **단일 진실 공급원** 역할

### 사용자 결정 (본 plan 수립 시 추가 합의, 2026-04-28)
| # | 결정 | 영향 |
|---|---|---|
| 23 | T-1 결정 A 폐기 — 메인 1~45 INPUT_DIM 동결 해제 | kind-hugging-matsumoto/회귀-plan의 INPUT_DIM 확장 가정과 정합 |
| 24 | 11 base 모델 전면 도입 (unified-plan대로) | 이미 unified-plan #12에서 합의된 사항을 본 plan에서 실행 확정 |
| 25 | 진행 순서: 21지표 → 회귀 → 4 Pillar (단계 게이팅) | 4 plan 동시 진행 대신 의존성 순으로 |
| 26 | 본 plan을 단일 마스터로, 기존 4 plan은 `docs/_archive/`로 보관 | 향후 변경은 본 plan에만 누적 |

→ 이 4개 추가 결정은 기존 22개 결정을 **부정하지 않고 정리**하는 성격이다.

### 기존 plan 처리
- 기존 plan들: 본 plan 수립 후 `docs/_archive/2026-04-28/`로 이동 (삭제 아님 — 설계 의도·근거의 reference로 보존)
- 본 plan: `docs/MASTER_PLAN.md`에도 사본 배치 권장

---

## 현황 — 코드베이스와 plan 정리

### 코드 상태 (2026-04-28 시점)
| 영역 | 파일 | 상태 |
|---|---|---|
| 7 base 모델 | `models/{lstm,cnn,transformer,xgboost,gnn,markov,autoencoder}_model.py` | 학습 완료, saved_models/ 가중치 존재 |
| 앙상블 | `models/ensemble.py` | 7 base + meta(8번째) + task_weights 8종 + Bootstrap CI + GNN veto |
| 메타러너 | `models/meta_learner.py` | LightGBM/Logistic stacking, fit_alpha bounded optimization |
| 후처리 | `models/posthoc_gate.py` | T-1 A 결정 구현됨 — 본 개편 결정 #23으로 역할 축소 (Hard Filter 1·2 전용) |
| DAG | `pipeline/training_orchestrator.py` | Stage 0/5/6만 실 동작, Phase 1~4 predictor 미등록 (기존 plan 의도대로 별도 PR 예정 상태) |
| 인프라 | `validation/{seed_utils,normalization,timeseries_cv,baselines}.py`, `pipeline/sla_monitor.py` | G-3~G-6/S-1 골격 완성 |
| 필터 통계 | `services/filter_stats.py` | 룰베이스 mean±1σ, 21지표 IndependentCountPredictor는 기존 plan에서 신설 예정 |
| 회귀 | — | 회귀-plan에서 4 Tier 신설 예정 |
| 4 Pillar | — | number-recommendation-plan에서 신설 예정 |

### 통합 시 정리할 결정 충돌 — 사용자 결정 #23~26으로 해소
누적 plan들이 서로 다른 시점·관점에서 작성돼 일부 외형적으로 충돌하는 항목이 있었다. 본 plan은 사용자 결정 #23~26으로 모두 통일한다.

| 항목 | 기존 상태 | 본 plan 통일 방향 (사용자 결정) |
|---|---|---|
| 메인 INPUT_DIM | T-1 A(동결, 코드 구현됨) vs kind-hugging/회귀(확장 가정) | **확장 (#23)** — kind-hugging·회귀-plan 가정 채택 |
| 모델 수 | 현 코드 7 base vs unified-plan 11 base | **11 base 도입 (#24, unified #12 그대로)** |
| LSTM/Transformer | 현 코드 유지 vs unified TFT 흡수 폐기 | **폐기 (#24, unified #13 그대로)** |
| 진행 단위 | 지표(kind-hugging) / Phase(unified) / Tier(회귀) | **Stage 단계 게이팅 (#25)** — 4 plan 모두 보존하되 의존성 순으로 |
| 단일 진실 공급원 | unified가 자칭 / 4 plan 분산 | **본 plan으로 통일 (#26)**, 4 plan은 archive |

→ 22개 누적 결정의 설계 내용은 모두 본 plan에 그대로 반영된다.

---

## 재설계 원칙

### A. 메인 1~45 모델 새 아키텍처 (T-1 A 폐기 후속)
- `posthoc_gate.py` 역할 축소 → 사용자 메모(Hard Filter 1순위) + 자동 룰(2순위) 강제 적용 전용
- 21지표·회귀 출력은 **메인 모델 학습 입력 feature로 직접 합류** (INPUT_DIM 자유 확장)
- **신규 메인 입력 dim 추정**: 65(현재 base) + 약 360(회귀 8×45) + 약 100(21지표 압축) + 90(메모 feature) ≈ **615 dim**
- 1100 회차로 615 dim 학습 — 11 base 중 트리 기반(XGB/CatBoost/TabNet)이 high-dim에 강건, 신경망(TFT)은 정규화·SSL pretrain·dropout 강화로 대응

### B. 11 Base 모델 통합 원칙
| # | 모델 | 역할 |
|---|---|---|
| 1 | XGBoost | 정형 회귀/분류 메인 |
| 2 | CatBoost | 카테고리 자동 처리 (XGB 병렬) |
| 3 | TabNet | Sparsemax attention feature selection |
| 4 | CNN | 7×7 그리드 (로또용지) |
| 5 | GNN(GAT) | 동반출현 그래프 (45 노드) |
| 6 | Markov | bucket 전이 (mode collapse 면역) |
| 7 | Autoencoder | 이상치 감지 → MoE 게이트로 진화 |
| 8 | TFT | 시계열+정형+카테고리 통합 (LSTM/Transformer 흡수) |
| 9 | N-BEATS | 스칼라 지표 trend/seasonality 분해 |
| 10 | MHN | 패턴 매칭 메모리 (회귀 Tier 4) |
| 11 | Bayesian NN | 불확실성 분포 추정 |

**2 인프라 기법**: SSL Pretraining(G-8), MoE 라우팅(M-1 진화)
**폐기**: LSTM, Transformer (saved_models 가중치는 `saved_models/_archive/` 보존)

### C. 단계 게이팅 (21지표 → 회귀 → 4 Pillar)
각 Stage는 **검증 게이트 통과 후 다음 Stage 진입**. 진행 중 모순 발견 시 본 plan 갱신.

### D. 학습 자원·SLA
- HF Spaces 16GB RAM 제약 → 모델별 lazy load + per-stage GC
- SSL pretrain은 1회성 작업 (saved_models/ssl_backbone.pt 캐시)
- 11 base 전부 학습 1 cycle 예상 시간: **8~12시간** (T-1 DAG 7 stage 순차)
- 매주 auto_train.py: incremental 학습만 (full retrain은 분기마다)

---

## 새 모델 토폴로지 다이어그램

```
[Self-Supervised Pretrain (G-8)]
  └─ 1100회차 마스킹+대조학습 → ssl_backbone.pt
                  │
                  ▼
[11 Base 모델 학습 (T-1 DAG Stage 1~5)]
  ├─ Stage 1: Markov (per-category bucket)
  ├─ Stage 2: 트리 (XGBoost + CatBoost)
  ├─ Stage 3: CNN (로또용지 그리드)
  ├─ Stage 4: TFT (정형+시계열+카테고리 통합)
  ├─ Stage 5: TabNet + N-BEATS + MHN + Bayesian NN
  ├─ Stage 6: AutoEncoder (이상 감지 헤드)
  └─ Stage 7: Meta Learner + MoE 라우팅
                  │
                  ▼
[21 IndependentCountPredictor (Phase 1~4)] ← Stage 1
[Regression DynamicICP + Tier 2~4]          ← Stage 2
[4 Pillar Score + NumberRecommender]        ← Stage 3
                  │
                  ▼
[Hard Filter 3계층]
  1. 사용자 메모 (forced_excl/incl)
  2. 자동 룰 (회귀 4연번 / 1회귀 4연번 / 데드 회귀×라인)
  3. 4 Pillar 점수 다중조건
                  │
                  ▼
[추천 5 + 제외 10] → [NumberXAIExplainer] → [Gemma 4 Narrative]
```

---

## Stage 0 — 정리 + 인프라 보강

### 0-1. 기존 plan archive
- `docs/kind-hugging-matsumoto.md`, `회귀-plan.md`, `number-recommendation-plan.md`, `lotto_lab-unified-plan.md`, `deeplearning_renewal.md` → `docs/_archive/2026-04-28/` 이동
- `docs/`에는 본 plan과 운영 문서(`lotto-db-schema.md`, `lotto-deeplearning-system.md` 등)만 잔존

### 0-2. saved_models 처리
- `saved_models/lstm_*.pt`, `transformer_*.pt` → `saved_models/_archive/2026-04-28/` 이동 (롤백 대비 1분기 보존)
- 11 base 신규 학습 후 archive 삭제

### 0-3. config 정리 — `langchain-backend/config.py`
- 신규 상수 추가:
  - `MODEL_TOPOLOGY = ['xgboost', 'catboost', 'tabnet', 'cnn', 'gnn', 'markov', 'autoencoder', 'tft', 'nbeats', 'mhn', 'bayesian_nn']`
  - `RANDOM_SEED = 42` (G-6, 이미 부분 존재)
  - `SSL_BACKBONE_PATH = 'saved_models/ssl_backbone.pt'`
  - `INPUT_DIM_FROZEN = False` (T-1 A 폐기 플래그)
  - `MAIN_MODEL_INPUT_DIM = None` (학습 시점 자동 결정)

### 0-4. 인프라 보강 신규 파일
| 파일 | 역할 |
|---|---|
| `langchain-backend/models/ssl_pretrainer.py` | G-8: 마스킹+대조학습, 모든 신경망 backbone 사전학습 |
| `langchain-backend/models/moe_router.py` | M-1: 4 expert 라우팅(정상/이상/회귀/메모) |
| `langchain-backend/validation/baseline_runner.py` | 베이스라인 비교 자동화 (rolling_mean, 균등, 빈도분포) |
| `langchain-backend/features/__init__.py` | feature 빌더 패키지 초기화 |
| `langchain-backend/predictors/__init__.py` | IndependentCountPredictor 패키지 |

### 0-5. Stage 0 검증 게이트
- [ ] archive 이동 완료, git status 깨끗
- [ ] config 신규 상수 import 가능
- [ ] SSL pretrain 1 epoch 완주 (오류 없이 backbone 저장)
- [ ] baseline_runner가 sum/AC/끝수합에 대해 rolling_mean 베이스라인 출력

---

## Stage 1 — 21지표 IndependentCountPredictor (11 base 통합)

### 1-1. 통합 패턴 — `langchain-backend/predictors/independent_count_predictor.py` (신규)
```python
class IndependentCountPredictor:
    """
    11 base 통합 카테고리별 7-class 카운트 분류기.
    
    Shared Backbone:
      - SSL-pretrained encoder (모든 신경망 backbone 초기화)
      - XGBoost/CatBoost (per-category 헤드)
      - TabNet (Sparsemax attention)
      - Markov 7-state × N
      - GNN 집계 (45-노드 → N개 카테고리)
      - TFT (정형+시계열+카테고리)
      - N-BEATS (스칼라 지표만, 분해 head)
      - Bayesian NN (분포 추정 σ)
      - Category Interaction Module (Category GNN, N 노드)
    
    Per-category Heads (N개):
      - Softmax 7-class P(count=0..6)
    
    출력 (각 카테고리별):
      {
        "absolute_dist": [P(0), ..., P(6)],
        "expected_count": E,
        "current_pool_size": M,
        "expected_ratio": E / M,
        "narrative": "{name} 풀 {M}개 중 {N}개 출현 가능성 {P}%",
        "model_contributions": {모델명: 기여도}  # XAI 입력
      }
    """
```

### 1-2. 21지표 매핑 (Phase 위계)
**Phase 1 (독립)**: 끝수0~9(10), 고저(7), 홀짝(7), 이월수×2(7), 이웃수(7), 연번(6), 번호대(5), 9궁(9), 로또용지(14), 배수(6), 소수합성수+1(3), 삼각수(1), 제곱수(1), 동형수(1), 미출현그룹(4), 핫콜드(12)

**Phase 2** (Phase 1 받음): 끝수합

**Phase 3** (Phase 1+2): AC값

**Phase 4** (모두): 총합 (sum 카르텟 + N-BEATS 분해 + 모든 약 시그널)

### 1-3. 신규 파일 (Stage 1)
| 파일 | 역할 |
|---|---|
| `predictors/independent_count_predictor.py` | 통합 패턴 |
| `predictors/sum_predictor.py` | Phase 4 총합 |
| `predictors/endings_predictor.py` | Phase 2 끝수합 + 끝수 분포 10D |
| `predictors/ac_predictor.py` | Phase 3 AC |
| `predictors/categorical_count_predictor.py` | 고저/홀짝/이월수/이웃수/연번 (target_type 분기) |
| `predictors/decade_predictor.py` | 번호대 5 |
| `predictors/gung_predictor.py` | 9궁 9 |
| `predictors/lotto_paper_predictor.py` | 로또용지 14 (CNN 그리드 메인) |
| `predictors/multiple_predictor.py` | 배수 6 (3·4·5·7·8 + 배수외) |
| `predictors/special_number_predictor.py` | 소수/합성수/삼각수/제곱수/동형수 (1 제외) |
| `predictors/missing_group_predictor.py` | 미출현그룹 광역 4 |
| `predictors/hotcold_predictor.py` | 핫콜드 12 (4 윈도우 × 3 그룹) |
| `features/scalar_features.py` | sum/ac/endings_sum 공통 13개 feature |
| `features/categorical_features.py` | 카운트형 공통 빌더 |
| `features/gnn_aggregation.py` | 기존 GNN 출력 → 21지표 집계식 재사용 |

### 1-4. 수정 파일 (Stage 1)
| 파일 | 수정 |
|---|---|
| `services/filter_stats.py` | 21개 메서드를 predictor 호출로 교체. 기존 mean±1σ는 fallback으로 보존 |
| `pipeline/training_orchestrator.py` | Phase 1~4 predictor 22개 등록(이월수 변형 1 포함) |
| `pipeline/weekly_pipeline_v2.py::_run_analysis()` | Phase 1→2→3→4 순차 호출, 캐시 parquet 활용 |
| `models/ensemble.py` | 메인 모델 입력에 predictor 출력 합류 (INPUT_DIM 동결 해제) |
| `routes/deep_analysis_v3.py` | predictor 출력 API 노출 |

### 1-5. Stage 1 검증 게이트
- [ ] Phase 1 16개 predictor 모두 베이스라인(균등 + 빈도) CE 이김
- [ ] Phase 2/3/4 predictor가 80% CI 커버리지 ≥75%
- [ ] sum 카르텟 일관성: `Σ_decades ≈ Σ_gungs ≈ Σ_horizontal` (오차 <5)
- [ ] 메인 ensemble.py 학습이 신규 INPUT_DIM으로 정상 수렴 (val AUC ≥ 베이스라인+0.05)
- [ ] HF Spaces에서 추론 시간 ≤ 30초/회차

---

## Stage 2 — 회귀(2~200) 4 Tier

### 2-1. Tier 1: DynamicIndependentCountPredictor — `predictors/regression_predictor.py` (신규)
- 가변 활성 N (16~30개) 동적 카테고리
- 11 base 통합 + Bayesian NN으로 sparse N(<50 sample) 불확실성 정량화
- Sparse N fallback: 빈도 베이스라인 + 신뢰도 가중

### 2-2. Tier 2: 번호별 압축 (8 변수 × 45 = 360 dim) — `features/regression_features.py` (신규)
| 변수 | 정의 |
|---|---|
| `regression_appearance_count` | 199 N 중 등장 누적 개수 |
| `regression_avg_gap` | 등장한 N들의 평균값 |
| `regression_max_consecutive` | 어느 N에서 가장 길게 연속 활성 |
| `regression_top3_active_N` | 가장 활성인 회귀 3개 |
| `regression_low/mid/high_N_density` | N≤10 / N=11~50 / N≥51 활성도 |
| `regression_sequence_dormancy` | 가장 최근 회귀 활성 후 경과 |
| `regression_mhn_similarity` | MHN retrieval top-K 유사 회귀 패턴 |

→ 메인 ensemble.py 입력에 360 dim 합류

### 2-3. Tier 3: 결합 필터 + 자동 룰 — `services/regression_filter_rules.py` (신규)
| Tier | 내용 |
|---|---|
| 3-A | 라인×N 매트릭스 (가로 7 × 활성N) |
| 3-B | 끝수×N 매트릭스 (10 × 활성N) |
| 3-C | 번호대×N + **자동 필터 룰 트리거** (3개 군집 → 다른 번호대 0~1개 제약) |
| 3-D | **★ 자동 룰 1·2 — 4연번 자동 제외** (회귀 N 4연번 / 1회귀 4연번) |
| 3-E | **★ 자동 룰 3 — 데드 회귀×라인 이월률** (≥2개 회귀 데드 → 자동 제외, 라인=정렬+보너스 1~7) |

자동 룰 → NumberRecommender의 `force_exclude` 우선 적용

### 2-4. Tier 4: 메타 분석 — `services/regression_meta_analyzer.py` (신규)
- 학습 데이터 walk-forward로 N별 자주 보이는 패턴 발견 (frequency≥0.20, support≥10)
- **MHN retrieval**: 현재 회차와 가장 유사한 과거 N회차 검색
- 출력: `saved_models/regression_meta_patterns.json` (주간 갱신)
- Gemma 4 narrative 입력으로 합류

### 2-5. Stage 2 신규/수정 파일
| 파일 | 역할 |
|---|---|
| `predictors/regression_predictor.py` (신규) | DynamicIndependentCountPredictor |
| `features/regression_features.py` (신규) | Tier 2 압축 변수 + Tier 3 매트릭스 |
| `services/regression_filter_rules.py` (신규) | Tier 3-D/E 자동 룰 트리거 |
| `services/regression_meta_analyzer.py` (신규) | Tier 4 메타 분석 |
| `services/filter_stats.py::_regression_distribution()` (수정) | Tier 1+3 출력 통합 |
| `pipeline/weekly_pipeline_v2.py::_run_analysis()` (수정) | Stage 2 호출 추가 |
| `pipeline/training_orchestrator.py` (수정) | regression_predictor 등록 |
| `models/ensemble.py` (수정) | 360 dim Tier 2 입력 합류 |

### 2-6. Stage 2 검증 게이트
- [ ] 활성 N 동적 식별 정확 (매 회차 16~30 N)
- [ ] 신뢰 N(sample≥50) 분류기가 빈도 베이스라인 CE 이김
- [ ] Tier 3-C 사용자 항목 E 검증: "11/14/19 → 0-1 필터" 자동 트리거 정확
- [ ] Tier 3-D/E 자동 룰이 NumberRecommender에 올바르게 force_exclude 전달
- [ ] Tier 4 frequency/support 임계값 통과 패턴이 도메인 직관과 일치

---

## Stage 3 — 4 Pillar + NumberRecommender + Hard Filter 3계층

### 3-1. 4 Pillar 점수 시스템 — `models/number_scorer.py` (신규)
```python
final_score(n) = MetaLearner.predict([
    pillar_1_ensemble_prob(n),       # 11 base 가중평균 + Bayesian σ
    pillar_2_filter_compliance(n),    # 21지표 필터 통과도
    pillar_3_individual_state(n),     # 핫콜드+미출현+회귀+MHN
    pillar_4_consensus_score(n),      # 11 base 순위 mean/std/top10/bottom15
])
```
- Ridge regression 메타러너
- 50회차 백테스트 기반 가중치 동적 갱신
- `saved_models/pillar_meta_weights.json` (주간 갱신)

### 3-2. ModelRankExtractor — `models/model_rank_extractor.py` (신규)
- 11 base 각자의 1~45 ranking 추출
- 5분할 default + 사용자 정의 슬라이스
- 합집합/공집합/per_number_count + pairwise [11×11] 매트릭스

### 3-3. ConsensusAnalyzer — `models/consensus_analyzer.py` (신규)
- Pillar 4: mean_rank, std_rank, top10_count, bottom15_count

### 3-4. NumberRecommender — `models/number_recommender.py` (신규)
**Hard Filter 3계층 우선순위**:
| 순위 | 종류 | 동작 |
|---|---|---|
| 1 (최우선) | 사용자 전문가 메모 | `prob = 0.0` 또는 강제 추천 |
| 2 | 자동 룰 1·2·3 (회귀 plan Tier 3-D/E) | force_exclude 추가 |
| 3 | 4 Pillar 점수 다중 조건 | 후보 풀 |

```python
def select_recommendations(...):
    # 1. 사용자 메모 forced_includes 우선
    # 2. final_score 정렬 → 상위 15
    # 3. consensus.top10_count >= 4 + filter_compliance >= median+0.1
    # 4. CI lower bound 정렬 → top 5

def select_exclusions(...):
    # 1. 사용자 메모 forced_excludes 강제
    # 2. 자동 룰 1·2·3 force_exclude 추가
    # 3. 4 Pillar 다중 조건 (점수↓ + 합의↓ + 필터위반)
    # 4. GNN co-occurrence veto 보강 → top 10
```

### 3-5. ExpertMemo 학습 시그널 (사용자 결정 #22)
| 메커니즘 | 파일 |
|---|---|
| Memo Feature Extractor (90D) | `models/expert_memo_extractor.py` (신규) |
| Memo Consistency Loss | `pipeline/memo_loss.py` (신규) |
| Memo History Tracker (적중률) | `services/expert_memo_history.py` (신규) |
| MoE Memo Expert | `models/moe_router.py` (Stage 0에서 신설, 여기서 메모 expert 활성) |
| Supabase 테이블 2개 | `expert_memos`, `expert_memo_history` |

→ **점진 도입**: 메모 데이터 50회차 누적 전까지는 `memo_domain_confidence=0.0` 시작, 누적되면서 자동 활성

### 3-6. 50회차 백테스트 — `validation/recommendation_backtest.py` (신규)
- walk-forward 50회차 시뮬레이션
- Pillar별 hit 기여도 측정
- Pillar 가중치 자동 갱신

### 3-7. Stage 3 신규/수정 파일
| 파일 | 역할 |
|---|---|
| `models/number_scorer.py` | 4 Pillar 통합 + 메타러너 |
| `models/model_rank_extractor.py` | 11 base ranking 추출 + 슬라이스 |
| `models/consensus_analyzer.py` | Pillar 4 4 메트릭 |
| `models/number_recommender.py` | Hard Filter 3계층 + 추천/제외 결정 |
| `models/expert_memo_extractor.py` | 메모 → 90D feature |
| `services/expert_memo_history.py` | 메모 적중률 추적 |
| `pipeline/memo_loss.py` | Memo Consistency Loss |
| `validation/recommendation_backtest.py` | 50회차 백테스트 |
| `models/ensemble.py::predict_top5/predict_exclusion_with_veto` (수정) | NumberRecommender 호출로 교체 |
| `models/posthoc_gate.py` (수정) | 역할 축소 — Hard Filter 1·2 강제 적용 전용 |

### 3-8. Stage 3 검증 게이트
- [ ] **추천 hit 평균 1 → 2~3 향상 (50회차 백테스트)**
- [ ] **제외 hit 평균 1-2 → 0~1 감소**
- [ ] consensus_score(Pillar 4)가 메타러너 SHAP 상위 1~2위 진입
- [ ] Hard Filter 3계층 우선순위 동작 검증 (메모 > 자동룰 > Pillar)
- [ ] 자동 룰 1·2·3 강제 제외가 `exclude_reason` 필드에 정확 기록

---

## Stage 4 — NumberXAIExplainer + Gemma 4 Narrative

### 4-1. 11 base XAI — `models/number_xai_explainer.py` (신규)
| 모델 | XAI 출력 |
|---|---|
| XGBoost/CatBoost | TreeSHAP |
| TabNet | Sparsemax attention mask |
| CNN | Grad-CAM |
| GNN(GAT) | Attention weights |
| Markov | 전이행렬 노출 |
| AE | 재구성 오차 |
| TFT | Variable selection weights |
| N-BEATS | trend/seasonality/residual 분해 |
| MHN | top-K 유사 과거 회차 |
| Bayesian NN | 분산 σ |

### 4-2. Gemma 4 Narrative 2형식
- **번호당**: 시그널 / 근거 / 결론 3섹션 한 문장씩 — `services/number_narrative.py` (신규)
- **페이지당**: 흐름 / 추세 / 추천 — `services/page_narrative.py` (신규)
- LRU 캐시(U-4) — `prompts/number_narrative_3section.txt`, `prompts/page_narrative.txt`

### 4-3. Stage 4 신규/수정 파일
| 파일 | 역할 |
|---|---|
| `models/number_xai_explainer.py` (신규) | 11 base XAI 통합 |
| `services/xai_aggregator.py` (신규) | XAI 통합기 |
| `services/number_narrative.py` (신규) | 번호당 3섹션 |
| `services/page_narrative.py` (신규) | 페이지당 흐름/추세/추천 |
| `prompts/number_narrative_3section.txt` (신규) | Gemma 4 system prompt |
| `prompts/page_narrative.txt` (신규) | 페이지 narrative prompt |
| `prompts/xai_narrative_prompt.txt` (신규) | XAI 합성 prompt |

### 4-4. 외부 라이브러리 추가
- `shap` (TreeSHAP)
- `captum` (PyTorch Integrated Gradients)
- `pytorch-forecasting` (TFT VSN)

### 4-5. Stage 4 검증 게이트
- [ ] Narrative 3섹션이 항상 한 문장씩
- [ ] 수치는 도메인 자연수만 등장 (SHAP 값 등 모델 내부 수치 부재)
- [ ] LRU 캐시 hit률 ≥80% (동일 회차 중복 호출 방지)
- [ ] Gemma 4 호출 평균 지연 ≤3초

---

## Stage 5 — UI 4 페이지 + ECharts

### 5-1. 페이지 매핑
| # | 페이지 | 파일 | 역할 |
|---|---|---|---|
| 1 | 분석 지표별 AI 프리미엄 (22개) | `total_sum.html` 등 22개 | `<div id="dlInsightContainer">` 자동 렌더링 |
| 2 | 딥러닝 분석 6 탭 | `ai_deep_learning.html` | 전체 대시보드 |
| 3 | AI 조합 | `ai_combination.html` | CombinationScorer 통합 |
| 4 | 검증 7 탭 | `verification.html` | 회차별 hit 검증 + Pillar 추적 |

### 5-2. 핵심 컴포넌트
- `js/deep_insight_panel_v3.js` (신규/갱신) — DeepInsightPanel v3.0
- `js/number_xai_card.js` (신규) — NumberXAIExplainerCard
- `js/rank_slice_selector.js` (신규) — 5분할 + 사용자 정의 슬라이스
- `js/consensus_matrix.js` (신규) — [11×11] heatmap (ECharts)
- `js/expert_memo_panel.js` (신규) — 사용자 메모 입력 UI

### 5-3. CombinationScorer — `models/combination_scorer.py` (신규)
```python
score(combo) = number_score (6번호 11 base 평균)
             + fixed_bonus (4 Pillar 추천 5 매칭)
             - exclude_penalty (4 Pillar 제외 10 매칭)
             + filter_compliance_score (21지표 통과)
             + diversity_bonus (GNN edge_prob + AE 이상도)
```

### 5-4. 11 모델 색상 토큰 (CSS)
```css
--c-xgb: #3B82F6;    --c-cat: #14B8A6;    --c-tabnet: #A855F7;
--c-cnn: #EC4899;    --c-gnn: #EF4444;    --c-markov: #10B981;
--c-ae: #8B5CF6;     --c-tft: #F97316;    --c-nbeats: #06B6D4;
--c-mhn: #84CC16;    --c-bayesian: #F59E0B;
```

### 5-5. Stage 5 검증 게이트
- [ ] 22개 분석 페이지 모두 `dlInsightContainer` 정상 렌더링
- [ ] 데스크탑/모바일 반응형 동작
- [ ] ECharts 5 시각화 정상 (heatmap×2, 신뢰구간, 시계열, sparkline)
- [ ] 사용자 메모 입력 → Supabase 저장 → 즉시 추천/제외 갱신
- [ ] AI 조합 페이지 점수 정렬·상위 N 토글 정상

---

## Stage 6 — 통합 검증 + 백테스트

### 6-1. 종합 백테스트
- 200회차 walk-forward 시뮬레이션 (최근 200 hold-out)
- 매 회차에서 각 Stage 출력 + 최종 추천/제외 + Hard Filter 3계층 동작 추적
- Pillar별 hit 기여도 SHAP attribution

### 6-2. 성능 목표
| 메트릭 | 현재 | 목표 |
|---|---|---|
| 추천 5 평균 hit | ~1 | **2~3** |
| 제외 10 평균 hit | 1~2 | **0~1** |
| 21지표 필터 통과율 | 측정 안 됨 | **베이스라인 대비 +20%** |
| HF Spaces 추론 시간 | 측정 안 됨 | ≤30초/회차 |
| 학습 1 cycle 시간 | 측정 안 됨 | ≤12시간 |

### 6-3. SLA 모니터 — `pipeline/sla_monitor.py` (기존 보강)
- 11 base 각자 wall-time + 메모리 추적
- 임계값 초과 시 fallback (해당 모델 비활성 + meta 가중치 재조정)

### 6-4. 통합 검증 항목
- [ ] Stage 1~5 모든 검증 게이트 통과
- [ ] 회귀 + 21지표 + 4 Pillar 동시 실행 시 충돌 없음
- [ ] Hard Filter 3계층 우선순위 정확
- [ ] 사용자 메모 → 학습 시그널 반영 (50회차 누적 후)
- [ ] Gemma 4 narrative 2형식(번호당/페이지당) 출력 일관

---

## Critical 파일 리스트 (전체)

### 신규 (총 약 35개)
**predictors/**: independent_count_predictor.py, sum_predictor.py, endings_predictor.py, ac_predictor.py, categorical_count_predictor.py, decade_predictor.py, gung_predictor.py, lotto_paper_predictor.py, multiple_predictor.py, special_number_predictor.py, missing_group_predictor.py, hotcold_predictor.py, regression_predictor.py

**features/**: scalar_features.py, categorical_features.py, gnn_aggregation.py, regression_features.py

**models/**: ssl_pretrainer.py, moe_router.py, catboost_model.py, tabnet_model.py, tft_model.py, nbeats_model.py, mhn_model.py, bayesian_nn_model.py, number_scorer.py, model_rank_extractor.py, consensus_analyzer.py, number_recommender.py, expert_memo_extractor.py, number_xai_explainer.py, combination_scorer.py

**services/**: expert_memo_history.py, regression_filter_rules.py, regression_meta_analyzer.py, number_narrative.py, page_narrative.py, xai_aggregator.py

**validation/**: baseline_runner.py, recommendation_backtest.py

**pipeline/**: memo_loss.py

**prompts/**: number_narrative_3section.txt, page_narrative.txt, xai_narrative_prompt.txt

**JS**: deep_insight_panel_v3.js, number_xai_card.js, rank_slice_selector.js, consensus_matrix.js, expert_memo_panel.js

### 수정 (총 약 12개)
- `models/ensemble.py` — INPUT_DIM 동결 해제, NumberRecommender 호출, 11 base 라우팅
- `models/posthoc_gate.py` — 역할 축소 (Hard Filter 1·2 전용)
- `models/meta_learner.py` — 4 Pillar 가중치 학습 path
- `services/filter_stats.py` — 21개 메서드 predictor 호출 교체 + `_regression_distribution()` 신설
- `pipeline/training_orchestrator.py` — Phase 1~4 + 회귀 + 4 Pillar predictor 등록
- `pipeline/weekly_pipeline_v2.py` — Stage 1~5 순차 호출
- `pipeline/sla_monitor.py` — 11 base 추적
- `routes/deep_analysis_v3.py` — predictor 출력 API
- `config.py` — MODEL_TOPOLOGY, INPUT_DIM_FROZEN=False, 신규 상수 다수
- `ai_combination.html` — CombinationScorer 통합
- `ai_deep_learning.html` — 6 탭 갱신
- `verification.html` — 7 탭 갱신

### 폐기/Archive
- `models/lstm_model.py` → `_archive/2026-04-28/` (TFT 흡수)
- `models/transformer_model.py` → `_archive/2026-04-28/` (TFT 흡수)
- `saved_models/lstm_*.pt`, `transformer_*.pt` → `saved_models/_archive/2026-04-28/`
- `docs/{kind-hugging-matsumoto,회귀-plan,number-recommendation-plan,lotto_lab-unified-plan,deeplearning_renewal}.md` → `docs/_archive/2026-04-28/`

### 신규 캐시·문서
- `saved_models/ssl_backbone.pt` (G-8)
- `saved_models/regression_meta_patterns.json` (Tier 4)
- `saved_models/pillar_meta_weights.json` (4 Pillar)
- `saved_models/cache/phase{1,2,3,4}/<predictor_id>_outputs.parquet`

### 신규 Supabase 테이블
- `expert_memos` — 회차별 메모 입력
- `expert_memo_history` — 적중률 누적
- `deep_analysis_history` — 분석 결과 캐시 (있으면 갱신)

---

## 자원·일정 가정

### 자원
- HF Spaces 16GB RAM (배포)
- 로컬 GPU 가정 (학습) — 없으면 Stage 1·2 학습 시간 ×3~5
- Supabase (메모 + 분석 캐시)

### 일정 (대략)
| Stage | 기간 | 핵심 산출물 |
|---|---|---|
| Stage 0 | 1주 | archive + SSL backbone |
| Stage 1 | 4주 | 21 predictor (Phase 1~4) |
| Stage 2 | 3주 | 회귀 4 Tier + 자동 룰 3개 |
| Stage 3 | 3주 | 4 Pillar + Hard Filter + 메모 학습 |
| Stage 4 | 2주 | XAI + Narrative |
| Stage 5 | 3주 | UI 4 페이지 + ECharts |
| Stage 6 | 1주 | 통합 검증 |
| **총계** | **17주 (약 4개월)** | — |

각 Stage 검증 게이트 미통과 시 다음 Stage 진입 보류 + 본 plan 갱신.

---

## 사용자 핵심 결정 누적 (본 plan에서 수용)

본 plan은 unified-plan의 22개 결정 + 회귀-plan의 자동 룰 3개 + number-recommendation-plan의 4 Pillar + kind-hugging-matsumoto의 21지표 IndependentCountPredictor 패턴을 모두 통합한다. 단, 이행은 **21지표 → 회귀 → 4 Pillar 순차 단계 게이팅**.

- 1 제외 (소수·합성수 분리), 이월수 보너스 변형 2개, 핫콜드 12 카테고리, 미출현그룹 광역 4 — 모두 유지
- 4연번/데드 회귀×라인 자동 룰 3개 — Stage 2 Tier 3-D/E에서 구현
- "M중 N" narrative 형식 — 전 predictor 공통
- TFT가 LSTM/Transformer 흡수 — saved_models archive
- 5분할 슬라이스 + 사용자 정의 — Stage 3 ModelRankExtractor
- 전문가 메모 Hard Filter 1순위 + 학습 시그널 — Stage 3 점진 도입

---

## 추후 calibration (구현 단계에서 자연스럽게 확정)

기존 4 plan에서도 calibration 단계로 분류한 항목들이다. 사전 결정 사항이 아니라 구현·백테스트 과정에서 데이터로 정한다.

1. **메모 학습 시그널 활성 임계값** — 메모 적중률 sample 누적 후 결정 (unified-plan #22의 점진 활성 정책 그대로)
2. **HF Spaces 자원 fallback 정책** — sla_monitor.py에서 11 base별 메모리 추적 후 정책 도출 (S-1)
3. **CombinationScorer의 diversity_bonus 가중치** — 백테스트 calibration (number-recommendation-plan과 동일)
4. **Pillar 가중치** — 50회차 백테스트 + Ridge 자동 학습 (number-recommendation-plan #4 그대로)
5. **Markov bucket 경계** — 학습 데이터 분포 기반 자동 결정 (kind-hugging-matsumoto와 동일)
6. **Tier 1 sparse N 임계값** — 회귀-plan에 명시된 sample≥50 기준 적용, 결과 보고 미세 조정

---

## Verification (실행 후 확인 방법)

### Stage별 게이트 명령
```bash
# Stage 0
python -m langchain-backend.scripts.archive_legacy_plans
python -m langchain-backend.models.ssl_pretrainer --epochs 50

# Stage 1
python -m langchain-backend.scripts.train_phase1_predictors
python -m langchain-backend.validation.baseline_runner --phase 1

# Stage 2
python -m langchain-backend.predictors.regression_predictor --train
python -m langchain-backend.services.regression_meta_analyzer --build

# Stage 3
python -m langchain-backend.validation.recommendation_backtest --window 50
python -m langchain-backend.models.number_scorer --calibrate

# Stage 4 (UI 미포함)
python -m langchain-backend.services.number_narrative --test

# Stage 5 (UI)
# 로컬 dev 서버에서 22개 페이지 각각 dlInsightContainer 렌더링 확인
# preview_screenshot으로 각 페이지 스크린샷 + preview_console_logs 에러 확인

# Stage 6
python -m langchain-backend.validation.recommendation_backtest --window 200 --report
```

### 통합 회귀 테스트
- `pytest langchain-backend/tests/` (각 Stage 단위 테스트 추가)
- HF Spaces 배포 후 실제 회차 데이터로 추천 5 + 제외 10 출력 검증
- 사용자 메모 입력 → 즉시 갱신 e2e 검증

---

## archive 처리 (Stage 0 첫 작업)

```bash
mkdir -p docs/_archive/2026-04-28
git mv docs/kind-hugging-matsumoto.md docs/_archive/2026-04-28/
git mv docs/회귀-plan.md docs/_archive/2026-04-28/
git mv docs/number-recommendation-plan.md docs/_archive/2026-04-28/
git mv docs/lotto_lab-unified-plan.md docs/_archive/2026-04-28/
git mv docs/deeplearning_renewal.md docs/_archive/2026-04-28/

mkdir -p saved_models/_archive/2026-04-28
git mv saved_models/lstm_*.pt saved_models/_archive/2026-04-28/ 2>/dev/null || true
git mv saved_models/transformer_*.pt saved_models/_archive/2026-04-28/ 2>/dev/null || true

git commit -m "chore: legacy plans + LSTM/Transformer 가중치 archive (재설계 Stage 0)"
```

본 plan(`C:\Users\psdet\.claude\plans\c-users-psdet-documents-lottoanalysis-d-quiet-perlis.md`)은 archive 대상 아님 — 단일 진실 공급원으로 `docs/`에도 사본 배치 권장 (`docs/MASTER_PLAN.md`).
