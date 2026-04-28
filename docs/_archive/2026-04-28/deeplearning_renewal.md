# Lotto_lab — 지표별 재설계 (현재 코드 기반)

## Context

사용자는 **이미 구축된 Lotto_lab 리포지토리**(https://github.com/ParkSD1975/Lotto_lab)의 딥러닝 설계가 잘못되어 학습 수렴 실패·정확도 바닥·mode collapse 등 모든 증상이 나타나고 있어, **지표를 하나씩 함께 재설계**한다. 본 plan은 진단 → 재설계 → 수정 파일 명시를 지표별로 누적한다.

### 21개 지표 마스터 리스트 (보너스 변형 + 독립 카테고리 분리 후 실제 필터 수 ~70+)

총합, 끝수합, AC값, 고저, 홀짝, **이월수(2변형: 정확/보너스포함)**, **연번**, **이웃수(2변형: 정확/보너스포함)**, 끝수0~9 (10개 독립), 번호대(5개 독립: 단번대/10대/20대/30대/40대), 9궁(5분할 9개 독립), 로또용지(가로7+세로7 = 14개 독립), 소수, 합성수, **제곱수**, 삼각수, 동형수, 배수(6개 독립: 3·4·5·7·8 + 배수외), 핫콜드(5/10/15/20기준), 미출현그룹(0-5/6-10/11-15/16+), 회귀(2~200)

### 사용자 정정 사항 (2개)

**정정 A — 이월수만 보너스 변형 2개 (이웃수는 단일)**:
- 현재 코드 `_carryover()`는 당첨 6개만 사용 (보너스 미포함)
- 사용자 의도: **이월수만** 보너스 포함 변형 추가 (이웃수는 6개 기준 단일 유지)
- 변형:
  - `carryover_exact`: 직전 당첨 6 ∩ 현재 6
  - `carryover_with_bonus`: 직전 (당첨 6 + 보너스 1) ∩ 현재 6
- 구현: `carryover_predictor`에 `include_bonus=True/False` 파라미터로 두 인스턴스 생성

**정정 B — 분포형 지표는 독립 카테고리 카운트 묶음**:
- 끝수/번호대/9궁/로또용지/배수 → 통째 NxD 분포 head 사용 ❌
- 각 카테고리가 0~6 독립 7-class 분류 ✅
- 통일 패턴 `IndependentCountPredictor`: 같은 백본 공유, 헤드만 카테고리별 분리

## 현재 코드 구조 요약 (진단 완료)

### 디렉터리
- `langchain-backend/models/`: lstm, cnn, gnn, transformer, xgboost, markov, autoencoder, ensemble, focal_loss
- `langchain-backend/pipeline/`: weekly_pipeline.py, weekly_pipeline_v2.py
- `langchain-backend/scripts/train_models.py`, `auto_train.py`
- `langchain-backend/config.py`: 모든 하이퍼파라미터
- `langchain-backend/services/filter_stats.py`

### 현재 아키텍처 (모든 모델 동일 타겟)
- **7개 base 모델 모두 1~45 이진 multi-label 분류** (출력=45 logits → sigmoid)
- LSTM: input (batch, 30, 65) — 65=45출현+12패턴+8주기, hidden=128 layer=2 bidirectional dropout=0.2
- Transformer: input (batch, 30, 57), d_model=128 nhead=4 layers=2 ffn=256 dropout=0.2
- CNN: input 7×7 grid 시계열, conv 64→128
- GNN: GAT 2-layer, 노드=45번호, 엣지=동반출현, **SoftmaxRankingLoss** 사용
- XGBoost: 45개 독립 binary classifier, 25 feature, scale_pos_weight=6.0
- 손실함수: 대부분 **Focal Loss (α=0.25, γ=2.0)**, LSTM은 추가로 pos_weight=6.5
- 학습: epochs=100, batch=64, patience=15, LR=0.001(LSTM/CNN)/0.0005(Transformer), weight_decay=1e-5
- 학습 순서: ~~Markov → XGBoost → CNN → LSTM → Transformer~~ — **[T-1-1 정정]** 실제로는 정해진 순서 없음. `LottoEnsemble.train_all()`이 dict 삽입 순서(xgb→lstm→cnn→transformer→ae→gnn) 우연 의존, Markov만 후처리. T-1 DAG 6 stage로 재정의됨
- 앙상블: 가중평균 → AE 페널티 → 메모필터 → MetaLearner stacking (alpha=0.30)

### 확인된/의심되는 결함
1. **Focal Loss(α=0.25,γ=2.0) + pos_weight=6.5 이중 보정** → mode collapse / 진동
2. **Bidirectional LSTM + hidden=128** → 1100여 회차 데이터에 파라미터 과대
3. **정규화 코드 부재** (pipeline_v2, train_models.py 모두 흔적 없음 — ensemble.train_all 내부에 있을 가능성)
4. **Train/Val split 로직 미공개** (LottoEnsemble.train_all 내부) — TimeSeries 분리 여부 불명
5. **베이스라인 비교 없음** (val_loss만 봐서는 1/45 균등 예측을 이기는지 모름)
6. **random seed 미설정** → 재현 불가
7. **19개 지표가 압축된 12 pattern 변수에 다 들어가는지 불명** → 사용자 의도("각 지표가 필터 예측")와 현재 구현(번호 출현 확률만 예측) 미스매치

---

## 재설계 작업 방식

**원칙**: 사용자와 지표 하나씩 차례로 검토.
각 지표마다:
1. **현재 코드에서 그 지표가 어떻게 다뤄지는지 구체적으로 파악** (어느 파일, 어떤 변수)
2. **무엇이 잘못됐는지 사용자와 합의**
3. **재설계안 도출** (계산 공식, feature 인코딩, 모델 적용, 정규화)
4. **수정해야 할 파일·함수 명시**

각 지표의 결과는 본 파일에 누적된다.

---

## 지표별 재설계

### 지표 1: 총합 (Sum)

#### 1-1. 현재 코드의 총합 처리 (진단 완료)

| 위치 | 역할 | 현재 방식 |
|---|---|---|
| `services/filter_stats.py::FilterStatsComputer._total_sum()` | 조합 필터 생성 | **룰베이스** — 최근 50회 `mean ± 1σ`, 출력은 `{min, max, evidence}` |
| `routes/deep_analysis_v3.py::simulate_all_filters` | 필터 적용 | 1~45 확률(corrected_probs)+draws → PB-PMF로 필터 범위 산출 |
| `models/xgboost_model.py` | feature 사용 | 25 feature 중 1개 = "직전 회차 합계" |
| `models/lstm_model.py`, `transformer_model.py` | feature 사용 | 65/57 dim의 "12 pattern"에 직전 sum 포함 추정 (미확인) |

#### 1-2. 결함

- **A**: 필터 산출이 단순 mean±1σ → 추세·평균회귀·변동성·교차항 무시, 커버리지 68%뿐
- **B**: 시계열 통계(rolling, zscore, 추세) 가 딥러닝에 안 들어감 → LSTM이 sum 패턴 학습 불가
- **C**: 총합을 예측하는 독립 모델 부재 → 사용자 목표("독립 필터 예측") 미구현
- **D**: 1~45 모델 mode collapse 시 simulate_all_filters 결과도 무의미

#### 1-3. 재설계 (목표: 독립 필터 예측 + feature 강화 둘 다)

**Part A — 독립 총합 예측 모델 신설 (5개 base 모델 통합)**

신규 파일: `langchain-backend/models/sum_predictor.py`
- **XGBoost Quantile Regressor** 3개 (q=0.10/0.50/0.90) — 메인 회귀기
- **경량 LSTM** (hidden=32, layer=1, unidirectional, dropout=0.1) — sum 시계열 흐름
- **경량 Transformer** (d_model=64, nhead=2, layer=1, dropout=0.2) — feature cross-attention
- **Markov** — sum을 6-bucket(<100/100-120/120-140/140-160/160-180/>180)으로 카테고리화한 전이행렬 P[6×6]. 다음 bucket 확률 6D 출력
- **Autoencoder 게이트** — 회차 feature 재구성오차로 LSTM/Transformer 신뢰도 동적 조정
- **GNN 집계** — 기존 GNN의 45 logits → `expected_sum = Σ(n × prob_n) × 6 / Σ(top6 probs)` (신규 GNN 학습 없이 1 base 모델 추가)

결합 (Layer 2): **Ridge meta-learner**
- 입력: [xgb_q10, xgb_q50, xgb_q90, lstm_pred, transformer_pred, markov_bucket_probs(6D), gnn_expected_sum, zscore_long, consecutive_up, ae_anomaly_score]
- 출력: 최종 q10/q50/q90 → 필터 `[lo, hi]`

**입력 Feature** (15~20개):
```
sum_lag_1, sum_lag_2, sum_lag_3, sum_lag_5
rolling_mean_5, rolling_mean_10, rolling_mean_20
rolling_std_5, rolling_std_10, rolling_std_20
rolling_min_10, rolling_max_10
zscore_short = (lag1 - mean_5)/std_5
zscore_long  = (lag1 - mean_20)/std_20
diff_1, diff_2
consecutive_up, consecutive_down
volatility_ratio = std_5/std_20
trend_pattern_5 (one-hot 5개 카테고리)
```

추가 (다른 지표 재설계 후): `predicted_high_count`, `predicted_large_endings_ratio`

**정규화**:
- Target sum: StandardScaler (예측 후 inverse_transform)
- lag/rolling_mean/diff: StandardScaler
- rolling_std/volatility: PowerTransformer (Yeo-Johnson)
- zscore/consecutive: 그대로
- trend_pattern: One-hot
- **fit은 train fold에만**

**출력 형태** (filter_stats 호환):
```python
{
  "key": "total_sum",
  "name": "총합",
  "type": "range",
  "recommendation": {
    "min": p10_pred,        # 학습 모델 산출
    "max": p90_pred,
    "median": p50_pred,
    "evidence": "ML quantile regression on rolling stats + zscore"
  },
  "stats": { ... 기존 필드 유지 ... }
}
```

**Part B-pre — Cross-feedback (Phase 4 위치, 가장 downstream)**

총합은 모든 다른 지표 예측 결과를 입력으로 받음. 한 시그널이 아닌 전체 흡수.

**받는 입력 매트릭스**:

*산술 시그널 (강)*:
- `predicted_endings_sum_p50`, `predicted_endings_sum_iqr` — `sum = 10×십의자리합 + 끝수합` 직접 결정
- `predicted_high_count_expected` — `expected_sum ≈ 11×low_count + 34×high_count` 직접 결정
- `predicted_high_count_dist[7]` (7D 분포) — sum 분포 형태 결정
- `predicted_low_count_expected = 6 - high_count_expected`

*통계 상관 시그널 (중)*:
- `predicted_large_endings_ratio` — 8/9끝 ↔ 18/19/28/29/38/39 → high count 부분 결정
- `predicted_ac_p50`, `predicted_ac_iqr` — AC ↓ → sum 변동성 ↓
- `predicted_ac_low_means_clustered_flag` — 군집이면 sum 극단값 가능성 ↑
- `predicted_odd_count_expected` — 약한 직접 상관 (홀=23평균, 짝=23평균이라 미미하나 극단 시 영향)

*Phase 5 추후 추가 예정*:
- `predicted_consecutive_count` (연번 → 군집 → sum 극단)
- `predicted_decade_dist[5]` (번호대 분포 → sum 직접)
- `predicted_zone_pattern_top` (9궁/로또용지 → sum 보조)

**구현 원칙**: 모든 입력을 sum_predictor의 base 모델들(XGBoost/LSTM/Transformer/Ridge meta)에 일괄 주입. XGBoost feature importance가 약한 시그널 자동으로 가중치 ↓.

**Part B — 메인 1~45 모델의 sum feature 강화** ⚠️ **[T-1 결정 A 폐기]**

> 본 절은 **T-1 결정 A에 의해 폐기**됨 (메인 모델 INPUT_DIM 65 동결). sum_predictor 출력은 `posthoc_gate.py` 후처리 게이트로만 결합. 본문은 설계 의도 보존용.

수정 대상: ~~`models/xgboost_model.py`, `models/lstm_model.py`, `models/transformer_model.py`~~
- ~~XGBoost 25 feature → 약 38 feature (위 sum feature 13개 추가)~~
- ~~LSTM 65 dim → 약 80 dim (sum 통계 15개 추가)~~
- ~~Transformer 57 dim → 약 72 dim~~
- ~~추가: `predicted_sum_p50`, `predicted_sum_iqr` (sum_predictor 출력을 메인 모델에 피드백)~~

**Part C — 학습/검증 인프라 (모든 지표 공통)**

신규 파일: `langchain-backend/validation/timeseries_cv.py`
- `TimeSeriesSplit(n_splits=5)` 또는 walk-forward expanding window
- 마지막 100회차는 hold-out 고정

**베이스라인** (`validation/baselines.py` 신규):
- B0: rolling_mean_20을 그대로 예측
- B1: Ridge regression
- 학습 시 매 epoch B0 대비 개선율 출력

**Random seed 고정** (`config.py`에 `RANDOM_SEED = 42`, 모든 모델에서 사용)

#### 1-4. 수정/신규 파일 목록

**신규**:
1. `langchain-backend/features/sum_features.py` — 13개 sum feature 빌더
2. `langchain-backend/models/sum_predictor.py` — XGBoost Quantile + LSTM stacking
3. `langchain-backend/validation/timeseries_cv.py` — 공통 walk-forward CV
4. `langchain-backend/validation/baselines.py` — rolling_mean / Ridge 베이스라인

**수정**:
5. `langchain-backend/services/filter_stats.py::_total_sum()` — sum_predictor 출력으로 recommendation 채우기 (기존 통계는 유지하고 추가)
6. `langchain-backend/pipeline/weekly_pipeline_v2.py::_run_analysis()` — sum_predictor 학습/추론 호출 추가
7. `langchain-backend/models/xgboost_model.py` — feature 13개 추가
8. ~~`langchain-backend/models/lstm_model.py` — INPUT_DIM 65 → 80, feature 빌더 호출~~ **[T-1 폐기]**
9. ~~`langchain-backend/models/transformer_model.py` — INPUT_DIM 57 → 72~~ **[T-1 폐기]**
10. `langchain-backend/config.py` — `SUM_PREDICTOR_*`, `RANDOM_SEED` 추가

#### 1-5. 검증

- [ ] sum_predictor가 베이스라인(rolling_mean_20)을 MAE 기준 이김
- [ ] 80% 신뢰구간이 실제 80% 회차를 커버
- [ ] 메인 1~45 모델의 valid AUC 가 sum feature 추가 후 개선됨
- [ ] filter_stats의 `total_sum` 필터 통과율이 합리적 (너무 좁지도 넓지도 않음)
- [ ] walk-forward 시뮬레이션 (마지막 50회차)에서 sum_predictor 의 q10/q90 커버리지 측정

---

### 지표 2: 끝수합 + 끝수 0~9 분포 (Endings)

#### 2-1. 현재 코드 진단

**확인된 코드** (`services/filter_stats.py`):
```python
def _tail_sum(self) -> dict:
    def calc(nums):
        return sum(n % 10 for n in nums)
    all_vals = [calc(nums) for nums in self.all_numbers]
    recent_vals = [calc(nums) for nums in self.recent_numbers]
    return self._build_range_filter(
        key="tail_sum", name="끝수합 (Tail Sum)",
        all_vals=all_vals, recent_vals=recent_vals, ...
    )
```
→ 총합과 동일한 룰베이스 mean±1σ. 학습 없음.

**결정적 결함**: `COUNT_TYPE_FILTERS`에 `digit0~9`가 언급되지만 **메서드 구현 없음** — 끝수 0~9 분포가 코드에 비어있다. 사용자 19지표 리스트의 "끝수(0끝-9끝)" 항목이 분석되지 않는 상태.

**부수 발견 → 사용자 정정**: 백엔드(Python) + 프론트엔드(HTML/JS) 분산 구조였음
- HTML: `magic_square.html`(9궁), `lotto_paper.html`(로또용지), `missing.html`(미출현그룹), `regression.html`(회귀 2~200), `multiple.html`(4/5배수)
- Python: `_twin_count`=동형수, `_square_count`=제곱수 (사용자 누락 지표 → **총 20개 지표**)
- 끝수 0~9 개별만 진짜로 비어있음 (`COUNT_TYPE_FILTERS`에 언급되나 메서드 미구현)

**재설계 시 매번 확인할 항목**: 각 지표가 Python(filter_stats.py)에 있나? HTML/JS에 있나? 양쪽? → 수정 대상 파일 결정에 영향

#### 2-2. 재설계 (Part A는 총합 템플릿 그대로, Part B~E가 끝수 고유)

**Part A — 끝수합 스칼라 예측기 (총합과 동일 5-모델 구조)**

신규 파일: `langchain-backend/models/endings_predictor.py`의 scalar head
- XGBoost Quantile + 경량 LSTM + 경량 Transformer + Markov(끝수합 6-bucket) + AE 게이트 → Ridge meta
- Feature 13개: tail_sum_lag_1~5, rolling_mean/std/min/max(5/10/20), zscore, diff, consecutive_up/down, volatility_ratio, trend_pattern_5
- 정규화: 총합과 동일 매핑

**Part B — 끝수 분포 예측기 10D (분포 고유, 5-모델 통합)**

> **[POST 9-2 정정] 본 1D-CNN 통합 분포 head는 폐기됨.** 지표 9의 `IndependentCountPredictor` 10개 분류기로 대체. 본 절은 설계 의도 보존용 — 구현 시에는 지표 9 (9-3 Part A) 모델 구성을 따른다.

같은 파일의 distribution head — **GNN과 1D-CNN이 핵심**:

- **1D-CNN** (메인 분포 학습)
  - 입력 shape: `(window=20, channels=10)`
  - conv 채널: 32 → 64 (kernel_size=3, padding=1)
  - 출력 head: Linear(64 → 10)
- **GNN 집계 (신규 GNN 학습 없이 기존 활용)** — 기존 45-노드 GNN의 logits를 `digit_k = Σ(prob_n where n%10==k)` 로 10D로 재투영. 같은 정보를 이중 학습할 이유가 없음
- **Transformer** (10채널 self-attention) — 채널 간 상호작용
- **Markov** — 각 끝수의 "출현/미출현" 2-state 전이확률 10개 (가벼움)
- **Autoencoder** — 10D 분포 압축(잠재 4dim) + 재구성오차로 이상 분포 감지

손실: **Multinomial CE** (합=6 제약) — 메인. CNN/GNN/Transformer 출력을 평균한 뒤 softmax×6.

출력: 10D 정수/실수 벡터, 합≈6

추가 보조 feature:
- **Dormancy 10D**: 각 끝수의 마지막 출현 후 경과 회차 (log1p + StandardScaler)
- **누적 빈도**: window 5/10/20 × 10채널 (PCA로 5~10dim 압축)
- **구간 비율**: small_endings(0~2끝), mid_endings(3~7끝), large_endings(8~9끝)

**Part C — `filter_stats.py` 신규 필터 추가**

`_endings_distribution()` 메서드 신설:
```python
def _endings_distribution(self) -> dict:
    return {
      "key": "endings_distribution",
      "name": "끝수 분포 (0~9)",
      "type": "distribution",
      "predicted": [...],      # endings_predictor 분포 head 출력
      "recommendation": {
        "large_endings_count_range": [1, 3],
        "small_endings_count_range": [0, 2],
        "by_digit": {0: [0,1], 1: [0,2], ..., 9: [0,2]}
      },
      ...
    }
```
`_tail_sum()`도 endings_predictor scalar head 출력으로 recommendation 강화.

**Part D — Cross-feedback (Phase 2 위치)**

**받는 입력** (Phase 1 → 끝수합):
- `predicted_digit_dist[10]` (끝수 0~9 각 출현 개수 예측)
- `predicted_large_endings_ratio` = (digit_8 + digit_9) / 6
- `predicted_high_count_expected` (8,9끝 ↔ 고번호 부분 상관)

**보내는 출력** (끝수합 → Phase 3·4):
- AC, 총합 모델 입력으로 흘러감 (해당 지표 매트릭스 참조)

산술 동치: `endings_sum = Σ(k × digit_count_k)` — 분포 head 출력으로 스칼라 head 직접 검증 가능

**Part E — 메인 1~45 모델에 endings feature 주입** ⚠️ **[T-1 결정 A 폐기]**

> 본 절은 폐기 — endings_predictor 출력은 posthoc gate에서 결합.

~~LSTM 80dim → 약 95dim:~~
- ~~추가: 끝수합 스칼라 통계 일부 (rolling_mean, zscore, consecutive)~~
- ~~추가: 끝수 분포 10D 직전값 + dormancy 10D 압축본~~
~~Transformer/XGBoost도 동일 비례 확장.~~

#### 2-3. 정규화 매핑 (sum과 다른 항목만)

| Feature | Scaler |
|---|---|
| Target tail_sum | StandardScaler |
| ending_count_0~9 (정수 0~6) | raw 또는 MinMax |
| 누적 빈도 | log1p + StandardScaler |
| dormancy_0~9 | log1p + StandardScaler |
| 구간 비율(small/mid/large) | 그대로 (0~1) |

#### 2-4. 수정/신규 파일

**신규**:
1. `langchain-backend/features/endings_features.py` — 스칼라 13개 + 분포 10D + dormancy 10D + 누적/비율
2. `langchain-backend/models/endings_predictor.py` — Quantile scalar head + 1D-CNN distribution head 결합

**수정**:
3. `langchain-backend/services/filter_stats.py::_tail_sum()` — endings_predictor scalar 결과 반영
4. `langchain-backend/services/filter_stats.py` — **`_endings_distribution()` 메서드 신규 추가** (compute_all에도 등록)
5. `langchain-backend/pipeline/weekly_pipeline_v2.py::_run_analysis()` — endings_predictor 학습/추론 호출
6. `langchain-backend/models/sum_predictor.py` — endings 피드백 입력 추가
7. ~~`langchain-backend/models/lstm_model.py` — INPUT_DIM 80 → ~95~~ **[T-1 폐기]**
8. ~~`langchain-backend/models/transformer_model.py` — INPUT_DIM 72 → ~85~~ **[T-1 폐기]**
9. ~~`langchain-backend/models/xgboost_model.py` — feature 약 13개 추가~~ **[T-1 폐기]**
10. `langchain-backend/config.py` — `ENDINGS_PREDICTOR_*` 추가

#### 2-5. 검증

- [ ] endings_predictor scalar head가 베이스라인(rolling_mean) 을 MAE 기준 이김
- [ ] distribution head의 10D 예측이 베이스라인(균등 0.6/채널)을 KL-divergence로 이김
- [ ] 분포 head 출력의 합이 5.5~6.5 범위 (정수 round 후 6과 일치율 ≥80%)
- [ ] sum_predictor에 endings 피드백 추가 후 sum MAE 개선 확인 (없으면 피드백 제거)
- [ ] `_endings_distribution` 필터의 권장 범위가 너무 좁지/넓지 않은지 검수

---

### 추가 컨텍스트: Gemma 4 LLM

사용자는 `langchain-backend/`의 `chains/`, `rag/`, `memory/`에서 **Gemma 4 LLM**을 사용 중. 역할 추정:
- XAI 자연어 설명 생성
- 사용자 질의 해석
- 분석 결과 종합 narrative

### 7개 모델 역할 분담 (지표 예측 공통 원칙)

각 지표 예측기는 사용자가 이미 구축한 7개 모델 자산을 **지표 특성에 맞춰 선택적 활용**한다 (XGBoost+LSTM 중심으로 좁히지 않음).

| 모델 | 강점 | 역할 |
|---|---|---|
| XGBoost | 정형 feature 회귀/분류 | 모든 지표의 메인 Quantile 회귀기 |
| LSTM | 시계열 순차 흐름 | 스칼라 지표(총합/AC/끝수합) 시계열 흐름 |
| Transformer | feature cross-attention | "어떤 통계가 지금 중요한가" 동적 가중 (작은 d_model=64) |
| Markov | 이산 상태 전이 | **bucket 전이** (sum 카테고리화 → 다음 bucket 확률), UDUDU 추세, hot↔cold |
| GNN(GAT) | 노드 관계성 | 분포형 지표: 끝수 10노드, 번호대 5노드, 9궁, 로또용지(49) |
| Autoencoder | 이상치/차원축소 | 이상 회차 감지 → **앙상블 가중치 동적 게이팅** + 분포 압축 |
| 1D-CNN | 로컬 패턴 | 분포 시퀀스 (10ch×20win), 7×7 그리드 |

**Autoencoder 게이팅 메커니즘 (모든 지표 공통)**:
```
회차별 feature → AE 재구성오차 e
e가 95 percentile 초과 시 "이상 회차"
복잡한 모델(LSTM, Transformer) 가중치 ↓
단순 모델(Markov, Ridge) 가중치 ↑
```

**Markov 카테고리화 원칙**:
- 스칼라 지표: 5~7 bucket으로 분할 (sum: <100/100-120/.../>180)
- 출력: bucket 전이 확률 벡터를 Ridge meta 입력으로 합류
- 파라미터 매우 적어 1100회차에 강건, mode collapse 없음

**기존 GNN 출력 집계 (Aggregation) 활용 — 모든 지표 공통**:

사용자께서 이미 구축한 GNN(45번호 동반출현 그래프, 출력=45 logits)을 **새 GNN 인스턴스 학습 없이 모든 지표 예측에 재활용**:

| 지표 | 집계식 |
|---|---|
| 총합 | `expected_sum = Σ(n × softmax(logit_n)) × 6 / Σ(top6 softmax)` |
| 끝수합 | `Σ((n%10) × prob_n)` |
| 끝수 분포 10D | `digit_k = Σ(prob_n where n%10==k)` |
| 고저 (고개수) | `Σ(prob_n where n>22)` |
| 홀짝 (홀개수) | `Σ(prob_n where n%2==1)` |
| 번호대 5D | 1-9/10대/20대/30대/40대 구간별 합 |
| 소수/합성수 | 소수 집합 ∈ {2,3,5,7,...43} 의 prob 합 |
| 배수 | 배수 집합의 prob 합 |

**구현**: `features/gnn_aggregation.py` 신규 파일 1개로 모든 집계식을 재사용. 각 지표 예측기는 이 집계 결과를 base 모델 1개로 추가.

**전제 조건**: 기존 GNN이 mode collapse 면 집계도 무의미 → 본 재설계의 글로벌 수정(focal loss, bidirectional, normalization, split)이 GNN에도 우선 적용되어야 함.

**기각**: 끝수 10-node 신규 GNN 제안은 위 집계로 대체 → 폐기 (기존 그래프가 이미 같은 정보를 담고 있음)

### "M중 N" 정규화 출력 형식 (모든 카테고리 지표 공통, 사용자 결정)

모든 카테고리 지표(끝수/번호대/9궁/로또용지/배수/소수합성수/삼각수/제곱수/동형수/미출현/핫콜드)는 다음 통일 출력 형식을 따름:

```python
{
  "category_k": {
    # 기존
    "absolute_dist": [P(0), ..., P(6)],
    "expected_count": E,
    "top_class": j,
    
    # 신규 (전 지표 소급 공통)
    "current_pool_size": M,                    # 현재 카테고리 풀 크기 (정적/동적)
    "expected_ratio": E / M,                   # 절대→상대 변환
    "ratio_dist_top": [{"out_of": (j, M), "prob": p}, ...],
    "narrative": "{category_name} 풀 {M}개 중 {j}개 출현 가능성 {p%}"
  }
}
```

**적용 이유**: 회차마다 그룹 크기가 변동하는 동적 카테고리(미출현/핫콜드/배수외)뿐 아니라, 고정 카테고리(끝수/번호대/9궁/배수)도 narrative 통일성으로 사용자 인터페이스 일관 매칭.

### Cross-feedback 매트릭스 (모든 지표 간 상호작용 — 순환 방지 위해 Phase 구조)

각 예측기는 **자신보다 상위 Phase 예측기들의 출력 전체**를 입력으로 받음. 한 시그널만 적용하지 않고 강·약 상관 모두 포함.

**의존성 위계**:
```
Phase 1 (독립): 끝수 분포 10D, 고개수 7-class, 홀개수 7-class, 핫콜드, 미출현그룹
Phase 2 (Phase 1 사용): 끝수합, 이월수, 연번, 동형수, 소수/합성수/삼각수/제곱수, 배수, 번호대 5D, 9궁 9D, 로또용지 14D
Phase 3 (Phase 1+2 사용): AC값
Phase 4 (모두 사용): 총합 (가장 downstream — 모든 시그널 흡수)
```

**예측기별 입력 매트릭스** (지표 추가 시 갱신):

| 예측기 | 받는 입력 (다른 예측기 출력) | 시그널 강도 |
|---|---|---|
| 끝수 분포 10D | (없음 — Phase 1) | - |
| 고개수 7-class | (없음 — Phase 1) | - |
| 홀개수 7-class | (없음 — Phase 1) | - |
| 끝수합 | digit_dist[10], large_endings_ratio (8,9끝) | 강(산술) |
| AC값 | high_count_expected, endings_sum_p50, large_endings_ratio, odd_count_extremity, low_count_extremity, consecutive_pred(추후) | 강·중 |
| 총합 | endings_sum_p50, endings_sum_iqr, large_endings_ratio, high_count_expected, high_count_dist[7], low_count_expected, odd_count_expected, ac_p50, ac_iqr, ac_low_means_clustered_flag | 강(산술 다수) |

**산술 결정 시그널 (강)**:
- `endings_sum → sum`: `sum = 10×Σ(십의자리) + 끝수합` (거의 결정)
- `digit_dist → endings_sum`: `Σ(k × digit_k)` 산술 동치
- `high_count → sum`: `expected_sum ≈ 11×low_count + 34×high_count`

**통계 상관 시그널 (중)**:
- `ac ↔ 연번`: 강한 음의 상관
- `ac ↔ 끝수 unique`: 양의 상관
- `high_count 극단 → ac 분산`: 영향
- `large_endings_ratio → high_count`: 18·19·28·29·38·39 → 양의 상관

**보조 시그널 (약)**:
- `홀짝 극단(0,6) → AC 분포 한쪽 쏠림`
- `AC ↓ (군집) → 총합 변동성 ↓`
- `끝수 unique → AC` 약한 양의 상관

**구현 원칙**:
- XGBoost feature importance가 자동으로 의미 없는 시그널 가중치 0에 가깝게 학습 → 약한 시그널까지 입력해도 안전
- Phase 위계 어기는 순환 참조 금지 (예: 끝수합 입력에 AC 넣으면 안 됨 — AC가 끝수합 사용하므로)
- 매트릭스의 빈 칸이 발견되면 해당 지표의 Part D에 추가

---

**모든 지표 예측기는 Gemma 4가 합성하기 좋은 evidence dict 출력 의무화**:
```python
{
  "predicted": {"min", "max", "median", "p10", "p90"},
  "evidence": {
    "rolling_mean_20": ..., "zscore_long": ...,
    "consecutive_up": ..., "trend_pattern": ...,
    "feature_contribution_top3": [(feature_name, shap_value), ...]
  },
  "narrative_seed": "한 문장 요약 — Gemma 4의 자연어 합성 시드"
}
```

---

### 지표 3: AC값 (Arithmetic Complexity)

#### 3-1. 현재 코드 진단

`services/filter_stats.py::_ac_value()`도 `_build_range_filter` helper 사용 → **mean±1σ 룰베이스**, 학습 없음. 총합/끝수합과 동일 패턴.

#### 3-2. AC값 특성과 총합과의 차이

| 항목 | 총합 | AC값 |
|---|---|---|
| 정의 | 6번호 합 | 6번호 쌍 차이의 distinct 개수 - 5 |
| 범위 | 21~255 (연속) | **0~10 (이산 정수, 좁음)** |
| 분포 | 종모양, 평균 138 | 종모양, 평균 7~8 |
| 상관 | 다른 지표들 | **연번 개수와 강한 음의 상관**, 분산도와 양의 상관 |

#### 3-3. 재설계

**Part A — ac_predictor (4-모델 통합)**

신규 파일: `models/ac_predictor.py`
- **XGBoost Quantile** (q=0.10/0.50/0.90) — 메인
- **경량 LSTM** — AC 시계열 흐름
- **경량 Transformer** (d_model=64) — feature cross-attention
- **Markov** — AC 11-state(0~10) 전이확률. **AC 자체가 자연스러운 이산 상태라 Markov가 가장 자연스럽게 들어맞는 지표**. 11×11 전이행렬 = 121 파라미터로 매우 가볍고 mode collapse 면역
- **GNN 집계 (간접)** — AC는 직접 식이 없지만, 기존 GNN top-6 번호의 차이값 distinct 개수를 시뮬레이션해 expected_AC 도출 가능. 보조 base 모델 1개 추가
- ❌ AE, CNN — 직접 적합도 낮음

결합: Ridge meta with [xgb_q10/50/90, lstm, transformer, markov_state_probs(11D), 컨텍스트]

**대안 방안 2**: 11-class 분류 헤드를 Markov와 결합 (Markov 전이확률 × 분류기 확률 곱) — 베이스라인 못 이기면 시도.

**Feature** (13 공통 + AC 고유 2개):
```
공통 13개: lag(1~5), rolling_mean/std/min/max(5/10/20),
          zscore(short/long), diff(1,2), consecutive_up/down,
          volatility_ratio, trend_pattern_5
AC 고유:
  ac_to_sum_ratio_lag_1 = AC ÷ sum (직전값)
  ac_to_consecutive_count_lag_1 (직전 연번 개수와의 비)
```

→ **공통 feature 빌더 일반화**: `features/sum_features.py` 대신 `features/scalar_features.py` 신규 작성. sum/ac/endings_sum 등 스칼라 지표가 공통 호출. 코드 재사용 ↑.

**Part B — Cross-feedback (Phase 3 위치)**

**받는 입력** (Phase 1+2 → AC):
- `predicted_high_count_expected`, `predicted_high_count_dist[7]` (4:2/2:4 극단성)
- `predicted_endings_sum_p50` (끝수 다양성 간접 신호)
- `predicted_large_endings_ratio`
- `predicted_odd_count_extremity = |odd - 3|` (균형 깨짐)
- `predicted_low_count_extremity = |low - 3|`
- 추후: `predicted_consecutive_count` (AC와 강한 음의 상관, 가장 중요한 신호)
- 추후: `predicted_endings_unique_count` (양의 상관)

**보내는 출력** (AC → Phase 4):
- `predicted_ac_p50`, `predicted_ac_iqr`, `predicted_ac_low_means_clustered_flag` → 총합 변동성 추정에 활용

**Part C — 메인 1~45 모델 feature 주입** ⚠️ **[T-1 결정 A 폐기]**

> 본 절은 폐기 — ac_predictor 출력은 posthoc gate에서 결합.

~~LSTM 95dim → 약 100dim:~~
- ~~추가 핵심 5개: ac_lag_1, ac_rolling_mean_20, ac_zscore_long, ac_consecutive_up, ac_to_consecutive_ratio~~

**Part D — Gemma 4 narrative**

`_ac_value()` 출력에 `narrative_seed` 추가:
```
"AC 평균 7.2 부근, z-score +0.5로 약간 분산 큼.
 직전 연번 1개 출현 시 다음 AC 7~8 예상"
```

#### 3-4. 정규화

총합과 동일 매핑 적용. AC가 정수지만 StandardScaler OK.

#### 3-5. 수정/신규 파일

**신규**:
1. `langchain-backend/features/scalar_features.py` — sum/ac/endings_sum 공통 feature 빌더 (sum_features 흡수/일반화)
2. `langchain-backend/models/ac_predictor.py`

**수정**:
3. `langchain-backend/services/filter_stats.py::_ac_value()` — ac_predictor 결과 + narrative_seed
4. `langchain-backend/pipeline/weekly_pipeline_v2.py::_run_analysis()` — ac_predictor 호출
5. `langchain-backend/models/sum_predictor.py` — predicted_ac_p50 입력 추가 (선택)
6. ~~`langchain-backend/models/lstm_model.py` — INPUT_DIM ~95 → ~100~~ **[T-1 폐기]**
7. ~~`langchain-backend/models/transformer_model.py` — INPUT_DIM ~85 → ~90~~ **[T-1 폐기]**
8. ~~`langchain-backend/models/xgboost_model.py` — feature 5개 추가~~ **[T-1 폐기]**
9. `langchain-backend/config.py` — `AC_PREDICTOR_*`

#### 3-6. 검증

- [ ] ac_predictor가 베이스라인(rolling_mean) MAE 이김
- [ ] q10/q90 80% 커버리지 검증
- [ ] AC↔연번 음의 상관이 모델 SHAP에 반영되는지 확인
- [ ] sum_predictor에 ac 피드백 추가 시 sum MAE 변화 측정 (개선 없으면 피드백 제거)
- [ ] narrative_seed가 Gemma 4 출력 자연어와 잘 어우러지는지 검수

---

### 지표 4·5: 고저 (High-Low) + 홀짝 (Odd-Even) — 공통 카테고리 카운트 지표

**구조 동일성**: 두 지표 모두 7-class(count 0~6) 분류 문제. 단일 모델 인스턴스 2개로 처리 가능.

#### 4-1. 현재 코드 진단

- `services/filter_stats.py::_low_high()` — 저번호(≤22) 개수, `_build_range_filter` 사용
- `services/filter_stats.py::_odd_even()` — 홀수 개수, 동일
- **결정적 결함**: 7가지 이산 카운트(0~6)를 연속 변수처럼 mean±1σ로 처리. 카테고리 분류 모델로 가야 정확

#### 4-2. 두 지표 구조 비교

| 항목 | 고저 | 홀짝 |
|---|---|---|
| 타겟 | 저개수 0~6 | 홀개수 0~6 |
| 임계값 | n ≤ 22 | n % 2 == 1 |
| GNN 집계식 | `Σ(prob_n where n≤22)` | `Σ(prob_n where n%2==1)` |
| 분포 mode | 3:3 (~30%) | 3:3 (~30%) |

#### 4-3. 재설계

**Part A — 7-class 카테고리 분류기 (둘 공용)**

신규 파일: `langchain-backend/models/categorical_count_predictor.py` — `target_type` 파라미터로 "low"/"odd" 분기
- **XGBoost Multiclass** (`objective=multi:softprob, num_class=7`) — 메인
- **Markov 7-state** — 0↔1↔2↔...↔6 점진 전이행렬 P[7×7]. 카운트 변화에 자연스러운 적합
- **GNN 집계** — 위 식으로 7D 확률 직접 산출 (binning 후)
- **경량 LSTM** (hidden=16, count 1D 시계열) — 단기 흐름
- ❌ Transformer/AE/CNN — 단순 카운트 분류엔 과함

결합: **Softmax 출력 평균** (Ridge meta 불필요)

**출력 형식 (옵션 Y-2 — 쌍 조인트)**:
- 클래스 = 7개 유효 쌍: `(6,0), (5,1), (4,2), (3,3), (2,4), (1,5), (0,6)` for 고저, 동일 패턴 홀짝
- 7-class softmax이지만 **클래스 자체가 쌍**이라 high+low=6 제약 위반 불가능
- 출력 예시:
```python
{"(6,0)": 0.04, "(5,1)": 0.12, "(4,2)": 0.28,
 "(3,3)": 0.30, "(2,4)": 0.16, "(1,5)": 0.07, "(0,6)": 0.03}
```
- 이월수는 짝 없으므로 단일 카운트 7-class `[P(0)...P(6)]` 그대로

**구현**: `PairOutputAdapter` 헬퍼 — `target_type` 파라미터로 분기
- `"low_high"` → (low, high) 쌍
- `"odd_even"` → (odd, even) 쌍
- `"carryover"` → 단일 카운트

**Part B — 필터 변환**

출력 dict는 **`pair_dist`(메인, 7-pair 조인트)와 `marginal_dist`(Cross-feedback용 단일 카운트 7D)를 분리** — 같은 모델 출력에 두 표현이 공존하는 모호성 제거 (이전 검토 4-3):

```python
# 고저/홀짝 (둘 다 공통 형식)
{
  "pair_dist": {                            # 7-pair 조인트 (메인 출력)
    "(6,0)": 0.04, "(5,1)": 0.12, "(4,2)": 0.28,
    "(3,3)": 0.30, "(2,4)": 0.16, "(1,5)": 0.07, "(0,6)": 0.03
  },
  "marginal_dist": [0.03, 0.07, 0.16, 0.30, 0.28, 0.12, 0.04],  # 단일 카운트 7D (Cross-feedback용)
  "top_pair": "4:2",
  "top_pair_prob": 0.28,
  "coverage_80": ["3:3", "4:2", "2:4"],     # 누적 80%
  "evidence": {...},
  "narrative_seed": "고저 4:2 (P=28%), 3:3 (P=30%) 누적 58%. 직전 4:2에서 3:3 회귀 모드"
}
# 이월수 (짝 없음 → marginal만)
{
  "marginal_dist": [...],
  "top_class": 1,
  "top_class_prob": 0.42,
  "coverage_80": [1, 0, 2],
  ...
}
```

**계산 관계**: `marginal_dist[k] = pair_dist[(6-k, k)]` (홀짝의 k=홀수개수). 두 필드는 항상 정합 — 외부 사용자(예: AC predictor)는 `marginal_dist`만 참조, 메인 출력 UI는 `pair_dist` 사용.

**Part C — 공통 Feature**

신규 파일: `langchain-backend/features/categorical_features.py`
- count_lag_1~5
- rolling_mean/std (5/10/20)
- balance_score = |count - 3|
- consecutive_imbalance_count
- class_dormancy[7]: 각 클래스 마지막 출현 후 경과 회차

**Part D — Cross-feedback (Phase 1 위치 — 받는 입력 없음, 보내는 출력 다수)**

고저·홀짝은 Phase 1이라 다른 예측기에서 입력 받지 않음. 대신 **다양한 출력을 다른 예측기에 보냄**:

*보내는 출력*:
- `predicted_high_count_top1`, `predicted_high_count_expected = Σ(k × P(k))`, `predicted_high_count_dist[7]` (전체 7D 확률)
- `predicted_high_count_extremity = |expected - 3|` (균형 깨짐 정도)
- `predicted_odd_count_top1`, `predicted_odd_count_expected`, `predicted_odd_count_dist[7]`, `predicted_odd_count_extremity`

*도달 경로*:
- → 끝수합 (Phase 2): high_count_expected 활용 (8,9끝 ↔ 고번호 부분 상관)
- → AC값 (Phase 3): 둘 다 expected + extremity 사용
- → 총합 (Phase 4): expected, dist[7], extremity 모두 사용

*메인 1~45 LSTM/Transformer 입력에도 7D 분포 합류*:
"고개수 4 가능성 ↑ → 23 이상 번호 prob ↑" 자동 추론

**Part E — 정규화**

| Feature | Scaler |
|---|---|
| count_lag, rolling_mean | StandardScaler |
| rolling_std | PowerTransformer |
| balance_score, consecutive_imbalance | 그대로 |
| class_dormancy[7] | log1p + StandardScaler |

타겟(0~6 정수 클래스 라벨)은 정규화 불필요.

**Part F — 손실함수**

**CrossEntropyLoss** — Focal 미사용. 클래스 분포가 그렇게 극단적이지 않음(mode=3:3 ~30%). 클래스 가중치는 학습 데이터 빈도 역수로 약하게 부여.

#### 4-4. 수정/신규 파일

**신규 2개**:
1. `langchain-backend/features/categorical_features.py` — 두 지표 공통 빌더
2. `langchain-backend/models/categorical_count_predictor.py` — target_type 분기로 두 지표 공용

**수정 6개**:
3. `services/filter_stats.py::_low_high()` — predictor("low") 결과 반영
4. `services/filter_stats.py::_odd_even()` — predictor("odd") 결과 반영
5. `pipeline/weekly_pipeline_v2.py::_run_analysis()` — 두 인스턴스 호출
6. `models/sum_predictor.py` — high_count/odd_count 피드백 입력
7. ~~`models/lstm/transformer/xgboost_model.py` — 7D 분포 + 통계 추가~~ **[T-1 폐기]**
8. `config.py` — `CATEGORICAL_PREDICTOR_*`

#### 4-5. 검증

- [ ] 두 모델 모두 균등(1/7) 베이스라인을 CE로 이김
- [ ] top-1 / top-3 정확도 측정
- [ ] sum_predictor에 high_count 피드백 추가 후 sum MAE 개선 확인
- [ ] Markov 전이행렬이 실제 데이터 전이 패턴과 일치하는지 검수
- [ ] CE loss 가 평탄(uniform) 예측 안 하고 분포가 의미 있게 형성되는지

---

### 지표 6: 이월수 (Carryover)

#### 6-1. 정의·특성

- 정의: 직전 회차 6번호 중 이번 회차에 다시 나온 개수
- 범위: 0~6 (7-class)
- 분포: **좌측 편향**, mode=1, P(0)+P(1)+P(2) 누적이 대부분
- **결정 메커니즘이 다른 지표들과 구조적으로 다름**: 직전 회차 6번호와의 교집합 → 다른 지표 예측 결과와 거의 무관

#### 6-2. 현재 코드

`services/filter_stats.py::_carryover()` — `_build_range_filter` 사용. mean±1σ 룰베이스 (학습 없음).

**결함**: 좌편향 카운트를 평균±편차로 다루면 비대칭 분포 정보 손실. 카테고리 분류로 가야 함.

#### 6-3. 재설계

**Part A — 4-모델 통합**

신규 파일: `models/carryover_predictor.py`
- **XGBoost Multiclass** — 메인
- **Markov 7-state** — 좌편향에서도 전이행렬 유효 (0/1/2 dominant)
- **GNN 집계 (가장 직접적)**:
  ```python
  prev_6 = draws[-1]["numbers"]
  expected_carryover = sum(gnn_probs[n-1] for n in prev_6)
  ```
  → 보조 헤드로 7-class로 변환
- **경량 LSTM** (hidden=16, 카운트 시계열)
- ❌ Transformer/AE/CNN

결합: Softmax 평균.

**보너스 변형 2개 인스턴스화** (정정 A):
- 동일 `CarryoverPredictor` 클래스를 `include_bonus={False, True}` 파라미터로 두 번 학습 → 2개 인스턴스
  - `carryover_predictor_exact` (직전 당첨 6 ∩ 현재 6)
  - `carryover_predictor_with_bonus` (직전 당첨 6 + 보너스 1 ∩ 현재 6)
- `services/filter_stats.py`에 두 메서드 노출:
  - `_carryover()` (기존, 정확 변형)
  - `_carryover_with_bonus()` (신규, 보너스 포함 변형)
- 각 인스턴스의 GNN 집계식만 풀이 다름 (정확=`prev_6`, 보너스=`prev_6 ∪ {bonus}`)
- Cross-feedback 출력도 `predicted_carryover_exact_*`와 `predicted_carryover_with_bonus_*` 두 셋

**Part B — 손실함수**

방안 1 (권장): CrossEntropyLoss + 클래스 가중치 = sqrt(빈도 역수). Focal 미사용.
방안 2: Poisson NLL — 베이스라인 못 이기면 시도.

**Part C — Feature**

`features/categorical_features.py`에 이월수 전용 함수 추가:
- carryover_lag_1~5, rolling_mean/std (5/10/20)
- **이월수 고유**:
  - `previous_round_avg_hot_streak`
  - `previous_round_avg_dormancy`
  - `previous_round_in_top10_count` (직전 6번호 중 GNN top-10 든 개수)
  - `class_dormancy[7]`

**Part D — Cross-feedback (Phase 1)**

받는 입력: 없음 (이월수는 다른 지표와 약한 상관)

보내는 출력:
- `predicted_carryover_top1`, `predicted_carryover_expected = Σ(k × P(k))`, `predicted_carryover_dist[7]`

도달 경로:
- ✅ 메인 1~45 모델: "이월=2 → 직전 6번호 중 2개 prob ↑" 자동 추론
- ⚠️ 다른 지표 예측기: 약한 시그널 → 매트릭스에 의도적 미포함 (입력 차원 절약)

**Part E — 정규화**

| Feature | Scaler |
|---|---|
| carryover_lag, rolling_mean | StandardScaler |
| rolling_std | PowerTransformer |
| previous_round_avg_hot_streak | StandardScaler |
| previous_round_avg_dormancy, class_dormancy[7] | log1p + StandardScaler |
| previous_round_in_top10_count | 그대로 |

#### 6-4. 수정/신규 파일

**신규 1**:
1. `langchain-backend/models/carryover_predictor.py`

**수정 4**:
2. `services/filter_stats.py::_carryover()` — predictor 결과 + narrative_seed
3. `pipeline/weekly_pipeline_v2.py::_run_analysis()` — Phase 1 호출
4. ~~`models/lstm/transformer/xgboost_model.py` — 7D 분포 + previous_round 변수 추가~~ **[T-1 폐기]**
5. `config.py` — `CARRYOVER_PREDICTOR_*`

#### 6-5. 검증

- [ ] 베이스라인(균등 + 빈도분포) 두 가지 모두 CE로 이김
- [ ] GNN expected_carryover와 실제 이월 평균 매칭도
- [ ] previous_round_avg_hot_streak ↔ 이월수 양의 상관 SHAP 확인
- [ ] 메인 1~45 모델에 이월 분포 추가 후 직전 6번호 prob 변화 합리성

#### 6-6. 매트릭스 갱신

Phase 1 항목에 `이월수 (carryover_predictor)` 등록. 메인 1~45 모델로의 시그널만 활성, Phase 2~4 매트릭스엔 추가 안 함.

---

### 지표 7: 연번 (Consecutive)

#### 7-1. 정확한 정의 (코드 확인 완료)

```python
def calc(nums):
    s = sorted(nums)
    return sum(1 for i in range(len(s)-1) if s[i+1] - s[i] == 1)
```
- 정렬 후 차이 1인 인접쌍 개수
- 예: [1,2,3,5,10,11] → 3쌍 (1,2)(2,3)(10,11)
- 범위: 0~5
- **현재 회차 6번호 내부만으로 결정** (이웃수와 다른 점)

#### 7-2. 현재 코드 진단

`_consecutive()`도 `_build_range_filter` 사용 → mean±1σ. 카테고리 분류로 가야 함.

#### 7-3. 재설계 (Phase 1 위치)

**Part A — 4-모델 통합**

`models/categorical_count_predictor.py`에 `target_type="consecutive"` 추가 (별도 파일 안 만듦):
- **XGBoost Multiclass** (6-class)
- **Markov 6-state** — 점진 전이
- **GNN edge_prob 직접 활용 — 가장 강한 시그널**:
  - 기존 GNN의 `predict_edge_prob()` 메서드 (코드에 이미 존재) 활용
  - `expected_pairs = Σ P((n,n+1)) for n in 1..44`
  - GNN top-6 번호 정렬 후 인접쌍 시뮬레이션
- **경량 LSTM** (hidden=16, 카운트 시계열)
- ❌ Transformer/AE/CNN

결합: Softmax 평균.

**Part B — 필터 변환**
```python
{
  "top_class": 0,
  "coverage_80": [0, 1],
  "evidence": {"gnn_top10_pair_count": ..., "gnn_total_edge_prob_sum": ...},
  "narrative_seed": "연번 0쌍 (P=55%), 1쌍 (P=30%) 누적 85%. GNN top10 내 인접쌍 1개 → AC 7.8 부근 예상"
}
```

**Part C — Feature**

`features/categorical_features.py`에 연번 함수 추가:
- consecutive_lag_1~5, rolling_mean/std (5/10/20)
- **고유 (강한 시그널)**:
  - `gnn_top10_pair_count` — GNN top10 중 인접쌍 개수
  - `gnn_total_edge_prob_sum` — 모든 (n,n+1) edge_prob 합
- **고유 (약한)**:
  - `previous_round_max_run_length`
  - `consecutive_class_dormancy[6]`

**Part D — Cross-feedback (Phase 1)**

받는 입력: 없음

보내는 출력:
- `predicted_consecutive_top1`, `predicted_consecutive_expected`, `predicted_consecutive_dist[6]`

도달 경로:
- ✅ AC predictor (Phase 3): **핵심 입력** — 강한 음의 상관 활성화
- ⚠️ 총합 (Phase 4): 약한 시그널 — 군집 → sum 극단 가능성. 매트릭스에 추가
- ✅ 메인 1~45 모델: "연번 1쌍 ↑ → 인접 prob ↑"

**Part E — 손실함수**

CrossEntropyLoss 6-class. Focal 미사용. 클래스 가중치 = sqrt(빈도 역수).

**Part F — 정규화**

| Feature | Scaler |
|---|---|
| consecutive_lag, rolling_mean | StandardScaler |
| rolling_std | PowerTransformer |
| gnn_total_edge_prob_sum | StandardScaler |
| class_dormancy[6] | log1p + StandardScaler |
| gnn_top10_pair_count, previous_round_max_run_length | 그대로 |

#### 7-4. 수정/신규 파일

**신규**: 없음 (기존 파일 재사용)

**수정**:
1. `models/categorical_count_predictor.py` — target_type="consecutive" 6-class
2. `features/categorical_features.py` — 연번 함수 추가
3. `services/filter_stats.py::_consecutive()` — predictor 반영
4. `pipeline/weekly_pipeline_v2.py::_run_analysis()` — Phase 1 호출
5. `models/ac_predictor.py` — predicted_consecutive_* 입력 활성화 (placeholder 해소)
6. `models/sum_predictor.py` — predicted_consecutive_expected 약한 시그널 추가
7. ~~`models/lstm/transformer/xgboost_model.py` — 6D + 4 컨텍스트 변수~~ **[T-1 폐기]**
8. `config.py` — `CONSECUTIVE_PREDICTOR_*`

#### 7-5. 검증

- [ ] 베이스라인(균등 1/6 + 빈도분포) CE로 이김
- [ ] GNN top10 인접쌍 개수와 실제 연번 양의 상관 (SHAP 확인)
- [ ] AC에 연번 추가 후 AC MAE 개선
- [ ] Markov 6-state 전이행렬 데이터 일치성 검수

#### 7-6. 매트릭스 갱신

- AC predictor 입력 매트릭스에서 `predicted_consecutive_*` placeholder → 활성화
- 총합(Phase 4) 매트릭스에 `predicted_consecutive_expected` 약한 시그널 신규 추가

---

### 지표 8: 이웃수 (Neighbor)

#### 8-1. 정확한 정의 (코드 확인 완료)

```python
# 직전 회차 번호의 ±1 범위에 있는 현재 회차 번호 개수
prev = set(draws[-1]["numbers"])
neighbors = {p-1, p, p+1 for p in prev} ∩ {1..45}
hit = sum(1 for n in current if n in neighbors)
```
- 이월수의 ±1 확장판 — **이웃수 ≥ 이월수** 항상 성립
- 범위: 0~6
- 분포: 우측 편향 (mode=2~3 추정), 이월수보다 평균 더 높음

#### 8-2. 현재 코드

`_neighbor_count()` — `_build_range_filter` 사용 (mean±1σ). 카테고리 분류 필요.

#### 8-3. 재설계 — 이월수 템플릿 재사용 (Phase 1)

**Part A — 4-모델 통합 (이월수와 동일 구조)**

`models/categorical_count_predictor.py`에 `target_type="neighbor"` 추가:
- XGBoost Multiclass (7-class) + Markov 7-state + GNN 집계 + 경량 LSTM
- ❌ Transformer/AE/CNN

**GNN 집계 — 이월수와 다른 부분**:
```python
prev_6 = draws[-1]["numbers"]
neighbor_pool = set()
for p in prev_6:
    neighbor_pool.update([p-1, p, p+1])
neighbor_pool &= set(range(1, 46))
expected_neighbor = sum(gnn_probs[n-1] for n in neighbor_pool)
```
이월수는 6개 풀, 이웃수는 ~18개 풀 (가장자리에서 13~17).

**Part B — 이웃수 고유 Feature** (이월수에서 추가)

- `neighbor_pool_size` (13~18, 직전 번호 위치 따라 변동)
- `prev_round_dense_overlap` (직전 6번호 중 인접 군집이 풀을 압축시키는 정도, 예: 10/11/12 → 풀 4개 단위)
- 그 외는 이월수 feature 동일

**Part C — 손실·정규화**

이월수와 동일. CE 7-class, 클래스 가중치 sqrt(빈도 역수).

**Part D — Cross-feedback (Phase 1)**

받는 입력: 없음

보내는 출력:
- `predicted_neighbor_top1`, `predicted_neighbor_expected`, `predicted_neighbor_dist[7]`

도달 경로:
- ✅ 메인 1~45: 강한 시그널 — 직전 ±1 풀의 prob 조정
- ⚠️ 다른 지표: 이월수와 동일하게 약함 → 매트릭스 미포함

**Part E — 일관성 검증**

`expected_neighbor ≥ expected_carryover` 수학적 제약. 위반 시:
- 학습 단계: 보조 손실(`max(0, expected_carryover - expected_neighbor)`) 미세 가중
- 추론 후처리: 이월수 expected를 이웃수 expected로 클리핑

#### 8-4. 수정/신규 파일

**신규**: 없음

**수정**:
1. `models/categorical_count_predictor.py` — target_type="neighbor"
2. `features/categorical_features.py` — neighbor_pool_size, prev_round_dense_overlap 함수
3. `services/filter_stats.py::_neighbor_count()` — predictor 반영 + 이월수 일관성 체크
4. `pipeline/weekly_pipeline_v2.py::_run_analysis()` — Phase 1 호출 (이월수 직후)
5. ~~`models/lstm/transformer/xgboost_model.py` — 7D + 2 컨텍스트~~ **[T-1 폐기]**
6. `config.py` — `NEIGHBOR_PREDICTOR_*`

#### 8-5. 검증

- [ ] 베이스라인 CE 이김
- [ ] **이웃수 expected ≥ 이월수 expected** 일관성 100%
- [ ] neighbor_pool_size 변동(가장자리)이 SHAP에 반영
- [ ] 우측 편향 분포(mode=2~3) 학습 확인

#### 8-6. 매트릭스 갱신

Phase 1에 `이웃수 (neighbor_predictor)` 등록. 메인 1~45만 시그널, Phase 2~4 미포함.

---

### 지표 9: 끝수 0~9 개별 (IndependentCountPredictor 대표설계)

#### 9-1. 정의

각 끝수 k ∈ {0..9}에 대해 다음 회차 출현 개수를 7-class 분류 (0~6). **10개 독립 분류기**.

#### 9-2. IndependentCountPredictor 패턴 (강화 버전 — 정정 B + 그룹간 강도)

사용자 정정 B-2: "각각 독립 필터지만 그룹간 강도도 측정해야 함"

```python
class IndependentCountPredictor:
    """
    카테고리별 독립 7-class 카운트 분류기 + 그룹간 상호작용 모델링.
    
    Shared Backbone:
      ├─ XGBoost (per-category multi:softprob 헤드 N개 + pairwise interaction features)
      ├─ Markov 7-state × N (개별 전이행렬)
      ├─ 기존 45-노드 GNN 집계 (카테고리별 expected)
      ├─ 경량 LSTM (카테고리별 카운트 시퀀스)
      └─ Category Interaction Module:
          ├─ Category GNN (노드 N개, 엣지=동시출현 상관, 2-layer GAT)
          ├─ 카테고리 임베딩 학습 (N×16 dim)
          └─ 임베딩을 per-category 헤드 입력에 주입
    
    Per-category Heads (N개):
      입력: own features + category embedding + pairwise features
      출력: Softmax 7-class P(count = 0..6)
    
    보조 출력 — 그룹간 강도:
      ├─ inter_category_correlation_matrix [N×N]
      ├─ category_dependency_graph (학습된 엣지 가중치)
      └─ joint_distribution_top_patterns (흔한 패턴 top-K + 확률)
    
    보조 손실:
      ├─ Σ_k expected_count_k ≈ 6 (λ=0.2)
      └─ 학습된 correlation_matrix vs 데이터 실제 상관 매칭 (λ=0.1)
    """
```

**그룹간 강도 측정 3가지 메커니즘**:

1. **Pairwise Interaction Features** (XGBoost용):
   ```python
   for i, j in combinations(categories, 2):
       pairwise_lag_1[i,j] = count_i_lag_1 × count_j_lag_1
       pairwise_rolling_corr_20[i,j] = corr(count_i_rolling_20, count_j_rolling_20)
   ```
   N=5 → 10 features, N=10 → 45 features

2. **Category GNN** (Neural용):
   - 노드 N개 = 카테고리, 엣지 = 동시출현 상관 (사전 계산 + 학습 가능)
   - 2-layer GAT → 카테고리 임베딩
   - per-category 헤드 입력에 concat

3. **Joint Distribution Top-K**:
   - 학습 데이터의 (c_0, c_1, ..., c_{N-1}) 튜플 빈도 분석
   - top-K 패턴 + 확률 출력

**출력 구조**:
```python
{
  "individual_filters": {  # 독립 필터 — 사용자 정정 B
    "category_k": {"dist": [...], "expected": ..., "top_class": ...} for k
  },
  "inter_category_strength": {  # NEW — 그룹간 강도
    "correlation_matrix": [[N×N]],
    "dependency_graph": {...},
    "negative_pairs": ["단번대 ↔ 40번대 (-0.22)"],
    "positive_pairs": ["10번대 ↔ 20번대 (+0.18)"]
  },
  "joint_distribution": {
    "top_patterns": [{"pattern": "1:2:1:2:0", "prob": 0.052}, ...]
  }
}
```

후속 적용 지표: 번호대(N=5), 9궁(N=9), 로또용지 가로(N=7) / 세로(N=7), 배수(N=5).

**끝수(지표 9)에도 소급 적용**: 끝수 10×10 상관 매트릭스, 끝수 패턴 top-K, Category GNN(끝수 10노드).

#### 9-3. 끝수 적용 (N=10)

**Part A — 모델 구성**

신규 파일 `models/independent_count_predictor.py`:
- XGBoost 10 헤드 (multi:softprob)
- Markov 10개 7-state 전이행렬
- GNN 집계 직접식: `digit_k_expected = Σ(gnn_probs[n-1] for n in 1..45 if n%10==k)`
- 경량 LSTM (10채널 카운트 시퀀스)

**Part B — Feature**

*공통*:
- `previous_round_digit_dist[10]`
- `gnn_top10_digit_dist[10]`, `gnn_top20_digit_dist[10]`

*각 끝수 k별 (10× 반복)*:
- digit_k_lag_1~5, rolling_mean/std (5/10/20)
- digit_k_dormancy (log1p + StandardScaler)
- digit_k_recent_ratio
- digit_k_position (one-hot)

**Part C — 손실함수**

```python
total_loss = Σ_k CE(head_k, label_k) + 0.2 × MSE(Σ_k expected_count_k, 6)
```

**Part D — Cross-feedback (Phase 1)**

받는 입력: 없음

보내는 출력:
- `predicted_digit_k_dist[7]` × 10
- `predicted_digit_k_expected` × 10
- `predicted_digit_k_top1` × 10

도달 경로:
- ✅ **끝수합 (Phase 2)**: digit_dist[10] 직접 사용 (산술 동치)
- ✅ 메인 1~45: "끝수 8 ↑ → 8/18/28/38 prob ↑"
- ⚠️ 총합 (Phase 4): `large_endings_ratio = (digit_8 + digit_9)/6` 매트릭스에 기존재

**Part E — 정정 B 적용: endings_predictor 분포 head 재정의**

지표 2의 endings 분포 head (1D-CNN + GNN + Transformer 통합) → **IndependentCountPredictor 10개 분류기로 대체**

장점: 사용자 정정 B 일치, 끝수별 dormancy/recent_ratio 등 개별 컨텍스트 활용, 일관성 자동 검증.

**Part F — 정규화**

| Feature | Scaler |
|---|---|
| digit_k_lag, rolling_mean | StandardScaler |
| rolling_std | PowerTransformer |
| digit_k_dormancy | log1p + StandardScaler |
| previous_round_digit_dist[10], gnn_top*_digit_dist[10] | 그대로 |
| digit_k_position | one-hot |
| digit_k_recent_ratio | 그대로 (0~1) |

#### 9-4. 수정/신규 파일

**신규 1**:
1. `models/independent_count_predictor.py` — 패턴 정의

**수정 5**:
2. `services/filter_stats.py::_endings_distribution()` — 신규 메서드 (지표 2에서 제안한 그대로) + 본 predictor 결과
3. `pipeline_v2._run_analysis()` — Phase 1 호출
4. `models/endings_predictor.py` — 분포 head를 IndependentCountPredictor 호출로 대체
5. ~~`models/lstm/transformer/xgboost_model.py` — 끝수별 expected 10 + dist 70(10×7) 추가~~ **[T-1 폐기]**
6. `config.py` — `INDEPENDENT_COUNT_PREDICTOR_*` + 카테고리 마커

#### 9-5. 검증

- [ ] 각 끝수 분류기 베이스라인 CE 이김
- [ ] 보조 일관성: Σexpected ≈ 6 (오차 < 0.5)
- [ ] endings scalar head 일관성: Σ(k × digit_k_expected) ≈ endings_sum_p50
- [ ] dormancy 효과 — 오래 안 나온 끝수 expected 점진 증가
- [ ] gnn_top10_digit_dist SHAP 기여도

#### 9-6. 후속 적용 안내

같은 `IndependentCountPredictor` 재사용 — 번호대/9궁/로또용지/배수 등은 **카테고리 정의 + GNN 집계식 + Category GNN 사전 상관 매트릭스**만 변경하여 빠르게 처리.

---

### 지표 10: 번호대 5개 (단번대/10대/20대/30대/40대)

#### 10-1. 정의·prior

| 카테고리 | 범위 | 풀 크기 | 출현 평균 |
|---|---|---|---|
| 단번대 | 1~9 | 9 | 1.20 |
| 10번대 | 10~19 | 10 | 1.33 |
| 20번대 | 20~29 | 10 | 1.33 |
| 30번대 | 30~39 | 10 | 1.33 |
| 40번대 | 40~45 | 6 | 0.80 |

40번대 풀이 작아 prior 다름. `decade_k_relative_ratio = count / size` feature로 정규화.

#### 10-2. 강화 IndependentCountPredictor 적용

**Part A — 모델 구성**

`IndependentCountPredictor(categories=DECADE_5)` 인스턴스:
- XGBoost 5 헤드 + 10 pairwise interaction features
- Markov 5×7-state
- 기존 45-노드 GNN 집계
- 경량 LSTM (5채널 시퀀스)
- Category GNN (5 노드, 엣지=동시출현 상관)

**Part B — Category GNN 사전 상관 (예상)**

```
단번대 ↔ 40번대: -0.22 (강한 음의 상관, 양극단 상호 배제)
10번대 ↔ 20번대: +0.18 (인접 동조)
30번대 ↔ 40번대: +0.12 (인접 동조)
```

학습 시 데이터에서 실제 매트릭스 산출, 사전값과 비교.

**Part C — 총합으로의 강한 시그널 (Phase 5 placeholder 활성화)**

```python
expected_sum_from_decades = (
    5.0 × decade_0_expected +    # 단번대 평균값
    14.5 × decade_1_expected +
    24.5 × decade_2_expected +
    34.5 × decade_3_expected +
    42.5 × decade_4_expected
)
```

→ sum_predictor 매트릭스에서 placeholder였던 부분 활성화.

**Part D — 번호대 고유 Feature**

*공통*: previous_round_decade_dist[5], gnn_top10/20_decade_dist[5]

*각 번호대 k별*:
- decade_k_lag_1~5, rolling_mean/std (5/10/20)
- decade_k_dormancy
- decade_k_size (9/10/10/10/6)
- decade_k_relative_ratio = count / size
- decade_k_avg_value (5/14.5/24.5/34.5/42.5)

*Pairwise (10개)*: pairwise_corr_20_{i}_{j}

*Category GNN 임베딩*: decade_k_gnn_embed[16] × 5 (총 80 dim)

**Part E — Cross-feedback (Phase 1)**

받는 입력: 없음

보내는 출력:
- `predicted_decade_k_dist[7]` × 5
- `predicted_decade_k_expected` × 5
- **`expected_sum_from_decades`** (강한 직접 시그널)
- `decade_correlation_matrix[5×5]`

도달 경로:
- ✅ **총합 (Phase 4)**: 매우 강한 시그널, sum_predictor 매트릭스 placeholder 해소
- ✅ 메인 1~45: 번호대 prob 직접 영향

**Part F — 정규화**

| Feature | Scaler |
|---|---|
| decade_k_lag, rolling_mean | StandardScaler |
| rolling_std | PowerTransformer |
| decade_k_dormancy | log1p + StandardScaler |
| decade_k_size, avg_value | 그대로 (상수) |
| decade_k_relative_ratio | 그대로 (0~1) |
| pairwise_corr | 그대로 (-1~1) |
| decade_k_gnn_embed | 그대로 |

#### 10-3. 수정/신규 파일

**신규**: 없음 (강화 패턴 재사용)

**수정**:
1. `pipeline_v2._run_analysis()` — Phase 1 호출
2. `services/filter_stats.py::_decade_distribution()` — 강화 + 5개 개별 결과 + inter_category_strength
3. `models/sum_predictor.py` — `expected_sum_from_decades` 입력, Phase 5 placeholder 해소
4. ~~`models/lstm/transformer/xgboost_model.py` — 5×7 분포 + 5 expected + 80 임베딩 + 10 pairwise~~ **[T-1 폐기]**
5. `config.py` — `DECADE_5_CATEGORIES`, prior 상관

#### 10-4. 검증

- [ ] 5개 분류기 베이스라인 CE 이김
- [ ] 보조 일관성 Σexpected ≈ 6
- [ ] **`expected_sum_from_decades`가 sum_predictor SHAP 상위 3** 진입
- [ ] 학습된 correlation_matrix가 실제 데이터 ±0.05 이내 일치
- [ ] negative/positive pairs가 도메인 직관 부합

#### 10-5. 매트릭스 갱신

- 총합(Phase 4) 매트릭스의 "Phase 5 추후 추가" → `expected_sum_from_decades`, `predicted_decade_k_dist[5×7]` 활성화

---

### 지표 11: 9궁 (5분할 9개)

#### 11-1. 정의

5분할 = 각 궁이 연속 5번호. 9궁 = 1~45를 5씩 9구간.

| 궁 | 범위 | 평균값 |
|---|---|---|
| 1궁 | 1~5 | 3 |
| 2궁 | 6~10 | 8 |
| 3궁 | 11~15 | 13 |
| 4궁 | 16~20 | 18 |
| 5궁 | 21~25 | 23 |
| 6궁 | 26~30 | 28 |
| 7궁 | 31~35 | 33 |
| 8궁 | 36~40 | 38 |
| 9궁 | 41~45 | 43 |

균등 풀(5개), 출현 평균 0.67.

**번호대와 상보 관계**: 9궁(5단위)이 번호대(10단위)보다 세밀. 둘 다 sum 강한 시그널.

#### 11-2. 강화 패턴 적용 (N=9)

**Part A — 모델 구성**

`IndependentCountPredictor(categories=GUNG_9)`:
- XGBoost 9 헤드 + 8 인접쌍 pairwise (1-2,...,8-9만)
- Markov 9×7-state
- 기존 GNN 집계
- 경량 LSTM (9채널)
- Category GNN — 9 노드 공간 그래프 (인접 엣지 + 학습 가능 비인접 엣지)

**Part B — 사전 상관 (예상)**

```
1궁↔2궁: +0.10 (인접 동조)
4궁↔5궁: +0.12
1궁↔9궁: -0.18 (양극단 배제)
```

**Part C — 총합 직접 시그널**

```python
expected_sum_from_gungs = 3×g0 + 8×g1 + 13×g2 + 18×g3 + 23×g4 +
                         28×g5 + 33×g6 + 38×g7 + 43×g8
```
번호대보다 세밀. sum_predictor에 둘 다 입력 (이중 추정).

**Part D — 9궁 고유 Feature**

*공통*: previous_round_gung_dist[9], gnn_top10/20_gung_dist[9]

*각 궁 k별*:
- gung_k_lag_1~5, rolling_mean/std (5/10/20)
- gung_k_dormancy
- gung_k_avg_value
- `gung_k_neighbor_active` — 인접 궁 expected 평균
- `gung_neighborhood_gradient` — 분포 공간 gradient

*Pairwise (선별 8개)*: 인접쌍만
*Category GNN 임베딩*: 144 dim (9×16)

**Part E — Cross-feedback (Phase 1)**

받는 입력: 없음

보내는 출력:
- `predicted_gung_k_dist[7]` × 9
- `predicted_gung_k_expected` × 9
- **`expected_sum_from_gungs`**
- `gung_correlation_matrix[9×9]`

도달 경로:
- ✅ **총합 (Phase 4)**: 강한 시그널, 번호대와 함께 이중 sum 추정
- ✅ 메인 1~45: 궁별 prob 직접 영향
- 번호대와 같은 Phase 1, 상호 입력 불필요

**Part F — 손실·정규화**

```
total_loss = Σ_k CE + 0.2 × MSE(Σexpected-6) + 0.1 × MSE(corr_learned - corr_data)
```

**Part G — 코드 위치**

filter_stats.py에 9궁 메서드 **없음** (magic_square.html 프론트에만 존재) → **신규 메서드 `_gung_distribution()` 추가 필요**.

#### 11-3. 수정/신규 파일

**신규**: 없음 (강화 패턴 재사용)

**수정**:
1. `pipeline_v2._run_analysis()` — Phase 1 호출
2. `services/filter_stats.py` — **`_gung_distribution()` 메서드 신규 추가** + compute_all 등록
3. `models/sum_predictor.py` — `expected_sum_from_gungs` 입력 추가
4. ~~`models/lstm/transformer/xgboost_model.py` — 9×7 분포 63 + 9 expected + 144 임베딩 + 8 인접쌍~~ **[T-1 폐기]**
5. `config.py` — `GUNG_9_CATEGORIES`, prior, 평균값

#### 11-4. 검증

- [ ] 9개 분류기 베이스라인(P(0)≈0.55) CE 이김
- [ ] 보조 일관성 Σexpected ≈ 6
- [ ] **`expected_sum_from_gungs`가 sum_predictor SHAP 상위 5**
- [ ] 9×9 corr이 인접 양/양극단 음 패턴
- [ ] gung_neighborhood_gradient SHAP 기여

#### 11-5. 매트릭스 갱신

- 총합(Phase 4)에 `expected_sum_from_gungs`, `predicted_gung_k_dist[9×7]`, `gung_correlation_matrix` 활성화

---

### 지표 12: 로또용지 가로/세로 (14개)

#### 12-1. 그리드 정의

```
가로1: 1~7 (7번호, 평균 4)      세로1: 1,8,15,22,29,36,43 (7개, 22)
가로2: 8~14 (7번호, 평균 11)    세로2: 2,9,16,23,30,37,44 (7개, 23)
가로3: 15~21 (7번호, 평균 18)   세로3: 3,10,17,24,31,38,45 (7개, 23)
가로4: 22~28 (7번호, 평균 25)   세로4: 4,11,18,25,32,39 (6개, 21.5)
가로5: 29~35 (7번호, 평균 32)   세로5: 5,12,19,26,33,40 (6개, 22.5)
가로6: 36~42 (7번호, 평균 39)   세로6: 6,13,20,27,34,41 (6개, 23.5)
가로7: 43~45 (3번호, 평균 44)   세로7: 7,14,21,28,35,42 (6개, 24.5)
```

#### 12-2. 다른 지표들과 구조적 차이

**차이 1**: 한 번호가 가로행 + 세로열 **두 카테고리에 동시 소속** → 보조 일관성 손실 가로/세로 각각:
- `Σ horizontal_expected ≈ 6`
- `Σ vertical_expected ≈ 6`

**차이 2**: 가로 vs 세로의 sum 시그널 비대칭
- **가로**: sum과 강한 직접 관계 (행마다 평균값이 4~44로 분명한 차이)
- **세로**: 모든 열 평균이 22~24로 비슷 → **sum 무관**, 대신 끝수/배수 패턴 시그널

#### 12-3. 강화 패턴 적용 (N=14)

**Part A — 모델 구성**

`IndependentCountPredictor(categories=PAPER_14)`:
- XGBoost 14 헤드 + 24 pairwise (가로인접 6 + 세로인접 6 + 가로↔세로 교차 12)
- Markov 14×7-state
- 기존 GNN 집계
- **기존 CNN 그리드 출력 집계 (신규 활용)** — cnn_grid_logits[49] 직접 입력
- 경량 LSTM (14채널)
- Category GNN — 14 노드, 직교 교차 + 같은 방향 인접 엣지

**Part B — 가로 → sum 강 시그널만**

```python
expected_sum_from_horizontal = 4×h0 + 11×h1 + 18×h2 + 25×h3 + 32×h4 + 39×h5 + 44×h6
```

세로는 sum 미사용. 끝수합·끝수 분포 보조 시그널로만 활용 (예: 세로7열 = 7끝과 강한 연관).

**Part C — 14개 카테고리 고유 Feature**

*공통*: previous_round_paper_dist[14], gnn_top10_paper_dist[14], **cnn_grid_logits[49]**

*각 카테고리 k별*:
- paper_k_lag_1~5, rolling_mean/std (5/10/20)
- paper_k_dormancy
- paper_k_size (3/6/7), paper_k_relative_ratio
- **paper_k_orientation** (horizontal=0, vertical=1)
- paper_k_avg_value

*Pairwise (24개)*: 가로 인접 6 + 세로 인접 6 + 교차 셀 12
*Category GNN 임베딩*: 14×16 = 224 dim

**Part D — Cross-feedback (Phase 1)**

받는 입력: 없음

보내는 출력:
- predicted_paper_k_dist[7] × 14
- predicted_paper_k_expected × 14
- **`expected_sum_from_horizontal`** (가로만)
- paper_correlation_matrix[14×14]

도달 경로:
- ✅ 총합 (Phase 4): 가로 강 시그널, 세로 미포함
- ✅ 메인 1~45: 14개 그리드 셀 추론
- ⚠️ 끝수합: 세로열 패턴 약 보조

**Part E — 손실**

```
total_loss = Σ_k CE 
           + 0.2 × MSE(Σh-6) + 0.2 × MSE(Σv-6)
           + 0.1 × MSE(corr_learned - corr_data)
           + 0.1 × cross_consistency_loss (가로↔세로 셀 단위)
```

**Part F — 코드 위치**

filter_stats.py 메서드 **없음** (lotto_paper.html 프론트만) → `_paper_distribution()` 신규 추가.

#### 12-4. 수정/신규 파일

**신규**: 없음

**수정 5**:
1. `pipeline_v2._run_analysis()` — Phase 1 호출
2. `services/filter_stats.py::_paper_distribution()` — **신규 메서드**
3. `models/sum_predictor.py` — `expected_sum_from_horizontal` 입력
4. ~~`models/lstm/transformer/xgboost_model.py` — 14×7 + 14 expected + 224 임베딩 + 24 pairwise + cnn_grid_logits[49]~~ **[T-1 폐기]**
5. `config.py` — `PAPER_14_CATEGORIES`, prior

#### 12-5. 검증

- [ ] 14개 분류기 베이스라인 CE 이김
- [ ] 가로 합·세로 합 각각 ≈6 일관성
- [ ] **`expected_sum_from_horizontal` SHAP 상위 7 진입** (번호대·9궁과 sum 트리오)
- [ ] 세로7열 SHAP에서 끝수 7과의 상관 검출
- [ ] cnn_grid_logits 활용도 측정 (CNN 출력 재사용 효과)

#### 12-6. 매트릭스 갱신

- 총합(Phase 4)에 `expected_sum_from_horizontal` 추가 (sum 추정 트리오: 번호대/9궁/가로행)
- 끝수합(Phase 2)에 `predicted_paper_vertical_dist[7×7]` 약한 시그널 추가

---

### 지표 13: 배수 5개 (3/4/5/7/8배수)

#### 13-1. 정의·prior

| 배수 | 멤버 | 풀 크기 | 출현 평균 |
|---|---|---|---|
| 3배수 | 3,6,...,45 | 15 | 2.00 (mode 2) |
| 4배수 | 4,8,...,44 | 11 | 1.47 (mode 1) |
| 5배수 | 5,10,...,45 | 9 | 1.20 (mode 1) |
| 7배수 | 7,14,...,42 | 6 | 0.80 (mode 0~1) |
| 8배수 | 8,16,...,40 | 5 | 0.67 (mode 0~1) |
| **배수외 (신규)** | 1,11,13,17,19,23,29,31,37,41,43 | 11 | **1.47** (mode 1) |

#### 13-2. 다른 카테고리 지표들과의 결정적 차이

**차이 1**: 번호의 **변동적 중복 소속**
- 24 = 3배수+4배수+8배수 (3개 동시)
- 40 = 4배수+5배수+8배수
- 1,11,13,17,...,43 = 어느 배수도 아님 → **"배수외" 6번째 카테고리로 추가** (사용자 정정, 2026-04-27)

**차이 2**: `Σ expected ≠ 6` (중복) → 기존 보조 일관성 손실 **부적합**

**차이 3**: sum 시그널 약함 (모든 배수 평균 ~24로 비슷) → sum_predictor에 미입력

#### 13-3. 매핑 매트릭스 기반 일관성 메커니즘

```python
M = mapping_matrix[5×45]  # M[k, n-1] = 1 if n is multiple_k
predicted_multiple_expected = M @ predicted_number_probs
# 메인 1~45 prob와 자동 정합

aux_loss = 0.05 × MSE(predictor_output_expected, M @ number_probs)
```

#### 13-4. 강화 패턴 적용 (N=6 — 배수 5 + 배수외 1)

**Part A — 모델 구성**

`IndependentCountPredictor(categories=MULTIPLE_6)`:
- XGBoost 6 헤드 + **15 pairwise** (6C2)
- Markov 6×7-state
- 기존 GNN 집계
- 경량 LSTM (6채널)
- Category GNN — 6 노드 (5 중복 관계 + 1 배제 관계)
  - 배수외 ↔ 각 배수: **음의 상관 (mutually exclusive)** — 배수외는 어느 배수도 아니므로 출현 시 다른 배수 카운트 감소

**배수외 카테고리 고유 Feature**:
- non_multiple_lag_1~5, rolling stats
- non_multiple_dormancy
- non_multiple_size = 11 (상수)
- non_multiple_relative_ratio = count / 11
- non_multiple_to_prime_overlap = 0.91 (상수, narrative용)

**Part B — 사전 상관 (예상)**

*배수 간 (양의 상관)*:
```
4배수 ↔ 8배수: +0.40 (8⊂4 100% 중복)
3배수 ↔ 6배수 영향: +0.20 (12,24,36 중복)
3배수 ↔ 5배수: +0.15 (15,30,45)
4배수 ↔ 5배수: +0.10 (20,40)
3배수 ↔ 8배수: +0.05 (24)
```

*배수외 ↔ 배수 (음의 상관)*:
```
배수외 ↔ 3배수: -0.30 (3배수 풀이 가장 커서 배제 강함)
배수외 ↔ 4배수: -0.18
배수외 ↔ 5배수: -0.13
배수외 ↔ 7배수: -0.08
배수외 ↔ 8배수: -0.07
```

**Part C — 배수 고유 Feature**

*공통*: previous_round_multiple_dist[5], gnn_top10_multiple_dist[5]

*각 배수 k별*:
- multiple_k_lag_1~5, rolling_mean/std (5/10/20)
- multiple_k_dormancy
- multiple_k_size (15/11/9/6/5)
- multiple_k_relative_ratio = count / size
- multiple_k_overlap_with_others (사전 상수)

*Pairwise (10개, 모두 보존)*:
- pairwise_corr_20[i,j]
- pairwise_overlap_count[i,j] (사전 계산 상수)

*Category GNN 임베딩*: 5×16 = 80 dim

**Part D — Cross-feedback (Phase 1)**

받는 입력: 없음

보내는 출력:
- predicted_multiple_k_dist[7] × 6 (배수 5 + 배수외 1)
- predicted_multiple_k_expected × 6

도달 경로:
- ⚠️ 총합 (Phase 4): **약 시그널만** (`expected_sum_from_multiples` 무용으로 미포함)
- ✅ 메인 1~45: 강 시그널 — "3배수 3개 ↑ → 3·6·9·...·45 prob 분배"
- ✅ **소수 지표 (Phase 1, 추후 설계)**: 배수외 ↔ 소수 강한 양의 상관 (~+0.95) — 배수외 멤버 11개 중 10개가 소수
- 다른 지표: 매트릭스 미포함

**Part E — 손실**

```
total_loss = Σ_k CE 
           + 0.05 × MSE(predictor_expected, M @ number_probs)  # 매핑 일관성 (대체)
           + 0.1 × MSE(corr_learned - corr_data)
```

`Σexpected ≈ 6` 손실 **사용 안 함**.

**Part F — 코드 위치**

filter_stats.py에 **`_multiple_3/7/8()` 기존**, **`_multiple_4/5()` 신규 추가 필요**.

#### 13-5. 수정/신규 파일

**신규**: 없음

**수정 5**:
1. `pipeline_v2._run_analysis()` — Phase 1 호출
2. `services/filter_stats.py` — `_multiple_4()`, `_multiple_5()` **신규** + 3/7/8 강화 + inter_category_strength
3. ~~`models/lstm/transformer/xgboost_model.py` — 5×7 + 5 expected + 80 임베딩 + 10 pairwise + 매핑 매트릭스~~ **[T-1 폐기]**
4. `config.py` — `MULTIPLE_5_CATEGORIES`, prior, 매핑 매트릭스 정의
5. (sum_predictor.py는 미수정 — sum 시그널 약함)

#### 13-6. 검증

- [ ] 5개 분류기 베이스라인 CE 이김
- [ ] **매핑 매트릭스 기반 자동 일관성** — predicted_expected ≈ M @ probs (오차 <0.3)
- [ ] **multiple_4 ↔ multiple_8 강한 양 상관** SHAP 검출
- [ ] prior 차이 학습 (3배수 mode=2 vs 8배수 mode=0~1)
- [ ] dormancy 효과

#### 13-7. 매트릭스 갱신

- 총합(Phase 4): 배수 시그널 미추가 (sum 무용)
- 메인 1~45 모델 입력만 활성화

---

### 지표 14: 소수 + 합성수 + 1 (3-카테고리, 비율 분석 포함)

#### 14-1. 정의

| 카테고리 | 멤버 | 풀 | 출현 평균 |
|---|---|---|---|
| 소수 | 2,3,5,7,11,13,17,19,23,29,31,37,41,43 | 14 | 1.87 (mode 2) |
| 합성수 | 4,6,8,9,...,44,45 | 30 | 4.00 (mode 4) |
| **1** | 1 | 1 | 0.13 (mode 0) |

합계 45 ✓. 매핑 매트릭스로 합=6 자동 보장.

#### 14-2. 사용자 요청: 비율 분석

```python
"ratio_analysis": {
  "prime_ratio": prime_expected / 6,
  "composite_ratio": composite_expected / 6,
  "prime_to_composite": prime_exp / composite_exp,
  "joint_top_patterns": [
    {"prime": 2, "composite": 4, "one": 0, "prob": 0.28},
    {"prime": 1, "composite": 5, "one": 0, "prob": 0.22},
    {"prime": 3, "composite": 3, "one": 0, "prob": 0.18},
    ...
  ],
  "narrative_seed": "소수 2 합성수 4 (P=28%) — 평균 비율. 직전 1:5 쏠림에서 회귀"
}
```

#### 14-3. 강화 패턴 적용 (N=3)

**Part A — 모델 구성**

`IndependentCountPredictor(categories=PRIME_3)`:
- XGBoost 3 헤드 + 3 pairwise
- Markov: 소수 7-state, 합성수 7-state, **1은 2-state(0/1)**
- 기존 GNN 집계
- 경량 LSTM
- Category GNN — 3 노드 mutually exclusive

**Part B — 사전 상관**

```
소수 ↔ 합성수: -0.65 (강한 음, 합=5~6 고정)
소수 ↔ 1: -0.10
합성수 ↔ 1: -0.20

— 배수외(지표 13)와 강한 양의 상관 —
소수 ↔ 배수외: +0.95 (10/11 멤버 일치)
```

**Part C — 매핑 매트릭스 자동 일관성**

```python
M[0] = primes_mask    # 14
M[1] = composites_mask # 30
M[2] = [1,0,0,...]     # 1만
expected = M @ probs   # 합=6 자동
```

**Part D — 총합 강 시그널 (sum 카르텟)**

```python
# 소수 평균값 19.43, 합성수 평균값 25.40, 1=1.0
expected_sum_from_prime_composite = (
    19.43 × prime_expected + 25.40 × composite_expected + 1.0 × one_expected
)
```

→ sum_predictor 매트릭스에 추가. **sum 추정 카르텟 완성**: 번호대 + 9궁 + 가로행 + 소수합성수.

**Part E — Feature**

*공통*: previous_round_dist[3], gnn_top10/20_dist[3]

*각 k별*: lag_1~5, rolling_mean/std, dormancy, size, relative_ratio

*비율 변수 (사용자 요청)*:
- prime_to_composite_ratio_lag_1~5
- prime_to_composite_rolling_mean_20
- ratio_zscore (평균회귀 시그널)
- one_appearance_streak

*Pairwise (3)*, Category GNN 임베딩 48 dim.

**Part F — Cross-feedback (Phase 1)**

받는 입력: 없음 (배수외와 같은 Phase, 메인에서 결합)

보내는 출력:
- predicted_prime_dist[7], predicted_composite_dist[7], predicted_one_dist[2]
- predicted_*_expected × 3
- **ratio_analysis** dict
- **`expected_sum_from_prime_composite`**
- prime_correlation_matrix[3×3]

도달 경로:
- ✅ **총합 (Phase 4)**: 강 시그널, sum 카르텟 진입
- ✅ 메인 1~45: 강 — 소수/합성수 prob 분배

**Part G — 손실**

```
total_loss = Σ_k CE + 0.2 × MSE(Σexpected-6) + 0.1 × MSE(corr_learned - corr_data)
```

#### 14-4. 수정/신규 파일

**신규**: 없음

**수정 5**:
1. `pipeline_v2._run_analysis()` — Phase 1 호출
2. `services/filter_stats.py` — `_prime_count`, `_composite_count` 강화 + **1 카테고리 처리 신규** + `ratio_analysis` + inter_category_strength
3. `models/sum_predictor.py` — `expected_sum_from_prime_composite` 입력 (sum 카르텟)
4. ~~`models/lstm/transformer/xgboost_model.py` — 3×7 + 3 expected + 48 임베딩 + 3 pairwise + 비율 변수 5개~~ **[T-1 폐기]**
5. `config.py` — `PRIME_3_CATEGORIES`, prior, 평균값 (19.43, 25.40, 1.0)

#### 14-5. 검증

- [ ] 3 분류기 베이스라인 CE 이김
- [ ] 매핑 매트릭스 자동 일관성 Σ≈6 (오차 <0.1)
- [ ] **소수 ↔ 배수외 +0.95** SHAP 검출
- [ ] 소수 ↔ 합성수 -0.65 SHAP
- [ ] **`expected_sum_from_prime_composite` SHAP 상위 7** (sum 카르텟)
- [ ] 비율 narrative 자연스러움
- [ ] 1 카테고리 binary 학습 정상

#### 14-6. 매트릭스 갱신

- 총합(Phase 4)에 `expected_sum_from_prime_composite` + `predicted_prime_dist[7]`, `predicted_composite_dist[7]`, `prime_to_composite_ratio` 활성화
- **sum 추정 카르텟**: 번호대 / 9궁 / 가로행 / 소수합성수

---

### 지표 15: 삼각수 (단일 카테고리)

#### 15-1. 정의

T_n = n(n+1)/2 in 1~45: **1, 3, 6, 10, 15, 21, 28, 36, 45** (9개)

| 항목 | 값 |
|---|---|
| 풀 크기 | 9 |
| 출현 평균 | 1.20 (mode 1) |
| 평균값 | 18.33 |

#### 15-2. 다른 카테고리 중복

- **3배수 6개 중복** (3,6,15,21,36,45) → +0.55 양의 상관
- 5배수 3개 중복 (10,15,45) → 약 양의 상관
- 소수 1개 (3), 1 카테고리 1개 (1)

#### 15-3. 단일 카테고리 7-class 분류 (N=1)

IndependentCountPredictor 패턴 단순화:
- XGBoost Multiclass 7-class
- Markov 7-state
- 기존 GNN 집계
- 경량 LSTM
- ❌ Category GNN, Pairwise (N=1)

**Sum 시그널**: 약함 (평균값 18.33 vs 전체 23 차이 작음). sum_predictor 미입력.

#### 15-4. Cross-feedback (Phase 1)

받는 입력: 없음

보내는 출력:
- predicted_triangular_dist[7], expected, top1

도달 경로:
- ✅ 메인 1~45: 강 — 삼각수 prob 분배
- ⚠️ 3배수와 +0.55 (Phase 1 동위, 메인에서 결합)
- ⚠️ 총합: 시그널 약함 미입력

#### 15-5. Feature

- triangular_lag_1~5, rolling_mean/std (5/10/20)
- triangular_dormancy
- triangular_size = 9
- triangular_relative_ratio = count / 9
- previous_round_triangular_count
- gnn_top10/20_triangular_count

#### 15-6. 손실
CE 7-class + 클래스 가중치 sqrt(빈도 역수).

#### 15-7. 수정/신규 파일

**신규**: 없음

**수정 4**:
1. `pipeline_v2._run_analysis()` — Phase 1 호출
2. `services/filter_stats.py::_triangular_count()` — predictor 결과 + 3배수 상관 narrative
3. ~~`models/lstm/transformer/xgboost_model.py` — 7 분포 + 1 expected + 5 컨텍스트~~ **[T-1 폐기]**
4. `config.py` — `TRIANGULAR_SET`

#### 15-8. 검증

- [ ] 빈도분포 베이스라인 CE 이김
- [ ] **삼각수 ↔ 3배수 +0.55** SHAP 검출
- [ ] dormancy 효과
- [ ] 빠른 수렴 (단일 카테고리)

#### 15-9. 매트릭스 갱신

- 메인 1~45에만 활성화
- sum 매트릭스 미추가

---

### 지표 16·17: 제곱수 + 동형수 (단일 카테고리 묶음)

#### 16-1. 제곱수 정의

n² ≤ 45: **1, 4, 9, 16, 25, 36** (6개)

| 항목 | 값 |
|---|---|
| 풀 크기 | 6 |
| 출현 평균 | 0.80 (mode 0~1) |
| 평균값 | 15.17 (sum 낮춤 약 시그널) |

**중복**: 합성수 5개 (4,9,16,25,36) → +0.85 강한 양의 상관

#### 16-2. 동형수 정의

자릿수 동일 두 자리 (코드: `_twin_count`): **11, 22, 33, 44** (4개)

| 항목 | 값 |
|---|---|
| 풀 크기 | 4 |
| 출현 평균 | 0.53 (mode 0) |
| 평균값 | 27.5 (sum 높임 약 시그널) |
| 특이 | **11배수와 100% 동치** |

**분포**: P(0)≈60%, P(1)≈32%, P(2+) 매우 드뭄

#### 16-3. 단일 카테고리 모델 (N=1, 각각)

각각:
- XGBoost Multiclass 7-class
- Markov 7-state
- 기존 GNN 집계
- 경량 LSTM
- ❌ Category GNN, Pairwise

#### 16-4. Cross-feedback (Phase 1)

**제곱수**:
- 메인 1~45: 강 (1/4/9/16/25/36 prob)
- 합성수 +0.85 (Phase 1 동위, 메인 결합)
- 총합: 약 (15.17, sum 낮춤)

**동형수**:
- 메인 1~45: 강 (11/22/33/44 prob)
- **11배수 정보 대체** (별도 11배수 predictor 불필요)
- 총합: 약 (27.5, sum 높임)

#### 16-5. Feature (양 지표 동일)

- {target}_lag_1~5, rolling_mean/std (5/10/20)
- {target}_dormancy
- size (6 또는 4)
- relative_ratio = count/size
- previous_round_count
- gnn_top10/20_count

#### 16-6. 손실

CE 7-class + 클래스 가중치 sqrt(빈도 역수). 동형수는 클래스 불균형 더 강하지만 Focal 미사용.

#### 16-7. 수정/신규 파일

**신규**: 없음

**수정 4**:
1. `pipeline_v2._run_analysis()` — Phase 1 호출 (둘 다)
2. `services/filter_stats.py` — `_square_count`, `_twin_count` 강화 + narrative
3. ~~`models/lstm/transformer/xgboost_model.py` — 각 7 분포 + 1 expected + 5 컨텍스트~~ **[T-1 폐기]**
4. `models/sum_predictor.py` — `predicted_square_expected × 15.17` + `predicted_twin_expected × 27.5` 약 시그널 (선택)
5. `config.py` — `SQUARE_SET`, `TWIN_SET`

#### 16-8. 검증

- [ ] 둘 다 빈도분포 베이스라인 CE 이김
- [ ] **제곱수 ↔ 합성수 +0.85** SHAP
- [ ] 동형수 클래스 불균형(P(0)≈60%) 정상 학습
- [ ] dormancy 효과
- [ ] sum_predictor 두 약 시그널 SHAP 미세 기여 (없어도 큰 문제 X)

#### 16-9. 매트릭스 갱신

- 메인 1~45 활성
- sum 매트릭스 약 시그널 추가 (선택)

---

### 지표 18: 미출현그룹 (광역 4 카테고리, 동적 멤버십)

#### 18-1. 정의 (사용자 정정 — 광역 4만 유지, 2026-04-27)

| 그룹 | 범위 | 명칭 |
|---|---|---|
| Group_0 | [0, 5] | Hot |
| Group_1 | [6, 10] | Warm |
| Group_2 | [11, 15] | Cool |
| Group_3 | ≥16 | Cold |

**기각 — 고정 세부 9 sub-bucket**: 매 회차 활성 dormancy N값이 동적 (16개 또는 30개 등 변동) → 고정 카테고리로 묶을 수 없음. 이 분석은 회귀(2~200) 지표에서 처리.

**역할 분담** (사용자 19지표 리스트 전체 관점):

| 분석 차원 | 담당 지표 |
|---|---|
| 큰 그림 4분할 | **미출현그룹** (현재) |
| 회차별 정확 N (동적, 매 회차 16~30+ 카테고리) | **회귀(2~200)** |
| 0회차 (직전 출현 매칭) | **이월수** (Hot-imm 동치) |

#### 18-2. 다른 카테고리 지표들과의 결정적 차이

**차이 1**: **동적 멤버십** — 한 번호가 시간에 따라 Hot→Warm→Cool→Cold→Hot 이동
- 매핑 매트릭스 M[4×45]가 **매 회차 변동**

**차이 2**: 시간 흐름 1방향 그래프 (Hot ← Warm ← Cool ← Cold + 모든 그룹 → Hot 출현 시)

**차이 3**: 그룹 크기 동적 — `current_group_size[4]` 변수 필요

#### 18-3. 강화 패턴 적용 (광역 4 헤드)

**Part A — 모델 구성**

`IndependentCountPredictor(categories=MISSING_4)`:
- XGBoost 4 헤드 + 6 pairwise (4C2)
- Markov 4×7-state
- 기존 GNN 집계 (동적 멤버)
- 경량 LSTM (4채널)
- **Category GNN — 4 노드 시간 흐름 방향성 그래프**

**시간 화살표 엣지** (Hot ← Warm ← Cool ← Cold + 모든 그룹 → Hot 출현 시).

**그룹 크기 정규화 ("M중 N" 형식, 사용자 결정 — 모든 카테고리 공통 적용)**:
각 4 헤드 출력에 absolute_dist + current_pool_size + expected_ratio + ratio_dist_top + narrative 모두 포함.

**Part B — 시간 화살표 엣지**

```
Hot ←─ Warm ←─ Cool ←─ Cold  (시간 진행)
모든 그룹 ──→ Hot              (출현 시)
```

Category GNN이 이 방향성을 학습.

**Part C — 미출현그룹 고유 Feature**

*공통*:
- previous_round_missing_group_count[4]
- gnn_top10_missing_group_count[4]
- **current_group_size[4]** (매 회차 동적)
- group_distribution_skewness

*각 그룹 k별*:
- group_k_lag_1~5
- rolling_mean/std (5/10/20)
- group_k_dormancy
- group_k_avg_dormancy (현재 멤버 평균 미출현 회차)

*Pairwise (6)*: 모두
*Category GNN 임베딩*: 4×16 = 64 dim

**Part D — Cross-feedback (Phase 1)**

받는 입력: 없음

보내는 출력:
- predicted_missing_group_k_dist[7] × 4
- predicted_missing_group_k_expected × 4

도달 경로:
- ✅ **메인 1~45: 매우 강** — Cold 번호 회귀 효과 prob 직접 영향
- ⚠️ 다른 지표: 매트릭스 미포함

**Part E — 손실**

```
total_loss = Σ_k(4개) CE 
           + 0.2 × MSE(Σexpected - 6)
           + 0.1 × MSE(corr_learned - corr_data)
           + 0.05 × time_arrow_loss
```

#### 18-4. 코드 위치

- `_hot_cold()` 다른 형태 기존
- 미출현그룹 `missing.html` 프론트만 → **`_missing_group_distribution()` 신규 추가 필요** (4 카테고리 + "M중 N" 형식)

#### 18-5. 수정/신규 파일

**신규**: 없음

**수정 4**:
1. `pipeline_v2._run_analysis()` — Phase 1 호출 (4 헤드)
2. `services/filter_stats.py::_missing_group_distribution()` — **신규** (광역 4 카테고리 + "M중 N" 형식) + compute_all 등록
3. ~~`models/lstm/transformer/xgboost_model.py` — 4×7 + 4 expected + 64 임베딩 + 6 pairwise + 4 current_group_size~~ **[T-1 폐기]**
4. `config.py` — `MISSING_GROUP_THRESHOLDS = [5, 10, 15]`

#### 18-6. 검증

- [ ] 4 분류기 베이스라인 CE 이김
- [ ] **동적 멤버십 정확 추적** — 매 회차 매트릭스 갱신
- [ ] Category GNN 시간 화살표 엣지 학습
- [ ] Cold dormancy ↑ → expected ↑ 회귀 효과
- [ ] Σexpected ≈ 6

#### 18-7. 매트릭스 갱신

- 메인 1~45 강 시그널 활성
- 다른 지표 매트릭스 미추가

---

### 지표 19: 핫콜드 (12 카테고리: 4 윈도우 × 3 그룹, 동적 멤버십)

#### 19-1. 정의 (사용자 정정 — 12 카테고리 + 모두 동적)

**4 윈도우 × 3 그룹 = 12 카테고리**:

| 윈도우 W | 그룹 | 임계값 (동적) |
|---|---|---|
| 5회차 | Hot/중립/Cold | 최근 5회 빈도 분포의 33%/66%로 분할 |
| 10회차 | Hot/중립/Cold | 최근 10회 빈도 |
| 15회차 | Hot/중립/Cold | 최근 15회 빈도 |
| 20회차 | Hot/중립/Cold | 최근 20회 빈도 |

#### 19-2. 결정적 동적 특성 (사용자 강조 4가지)

**특성 1**: **12 카테고리 풀 크기 M 모두 회차마다 동적**
- 같은 윈도우 안에서도 그룹간 번호 수 다름 (frequency 분포 plateau, 동률 처리)
- 예: W=5 Hot=16 / 중립=17 / Cold=12, 다음 회차엔 다른 분포
- → `current_pool_size[12]` 12개 모두 매 회차 갱신

**특성 2**: 윈도우마다 Hot/Cold 임계값 다름
- W=5 Hot 임계값 ≠ W=20 Hot 임계값

**특성 3**: 윈도우 간 계층 포함 관계 (약하게)
- W=20 Hot ⊃ W=10 Hot ⊃ W=5 Hot 일반 경향, 항상 X → Category GNN 학습

**특성 4**: 미출현그룹과 강한 연관
- Hot ↔ 미출현 Hot(0-5) 양 상관
- Cold ↔ 미출현 Cold(16+) 양 상관

#### 19-3. 강화 패턴 적용 (N=12)

**Part A — 모델 구성**

`IndependentCountPredictor(categories=HOTCOLD_12)`:
- XGBoost 12 헤드 + 30 선별 pairwise
- Markov 12×7-state
- 기존 GNN 집계 (동적 멤버 합산)
- 경량 LSTM (12채널)
- Category GNN — 12 노드 (윈도우 간 양 / 윈도우 내 음 상관)

**Part B — Pairwise 30개 선별**

*같은 윈도우 mutually exclusive (12개)*: 4 윈도우 × 3쌍 (H↔N, H↔C, N↔C)
*다른 윈도우 같은 라벨 양 상관 (18개)*: Hot 윈도우간 6쌍 + 중립 6 + Cold 6

**Part C — 손실 (윈도우 일관성)**

```python
total_loss = Σ_k(12개) CE 
           # H+N+C=6 윈도우별 자동 보장 (수학적)
           + 0.15 × window_hierarchy_loss   # W=5 Hot ⊂ W=10 Hot 약 강제
           + 0.1 × MSE(corr_learned - corr_data)
```

**Part D — Feature**

*공통*:
- previous_round_hotcold_count[12]
- gnn_top10_hotcold_count[12]
- **current_pool_size[12]** (모두 동적)
- current_pool_size_ratio[12] (45 대비 비율, 합=1)
- cross_window_hot_overlap

*각 카테고리 (W, g)*:
- hotcold_W{w}_g{g}_lag_1~5, rolling_mean/std (5/10/20)
- dormancy
- threshold_value (동적 임계값)

*Category GNN 임베딩*: 12×16 = 192 dim

**Part E — Cross-feedback (Phase 1)**

받는 입력: 없음

보내는 출력:
- predicted_hotcold_W{w}_g{g}_dist[7] × 12
- predicted_hotcold_W{w}_g{g}_expected × 12
- predicted_hotcold_W{w}_g{g}_pool_size × 12
- hotcold_correlation_matrix[12×12]

도달 경로:
- ✅ **메인 1~45: 매우 강** — 기존 GNN node feature `hot_streak` 사용 중
- ⚠️ 다른 지표: 매트릭스 미포함

**Part F — "M중 N" narrative**

```
"W=5 Hot 풀 16개 중 3개 출현 가능성 38%
 W=10 Hot 풀 14개 중 3개 가능성 32% → 단기·중기 일관 상승세
 W=20 Cold 풀 13개 중 0개 가능성 55% → 장기 침체"
```

#### 19-4. 코드 위치

- `_hot_cold()` 메서드 기존 (단일 형태) → **4 윈도우 × 3 그룹 12 출력으로 강화**

#### 19-5. 수정/신규 파일

**신규**: 없음

**수정 4**:
1. `pipeline_v2._run_analysis()` — Phase 1 호출 (12 헤드)
2. `services/filter_stats.py::_hot_cold()` — **12 카테고리 강화** + "M중 N" + inter_category_strength + 윈도우 계층 분석
3. ~~`models/lstm/transformer/xgboost_model.py` — 12×7 + 12 expected + 192 임베딩 + 30 pairwise + 12 pool_size~~ **[T-1 폐기]**
4. `config.py` — `HOTCOLD_WINDOWS = [5, 10, 15, 20]`, threshold 동적

#### 19-6. 검증

- [ ] 12 분류기 베이스라인 CE 이김
- [ ] **윈도우별 H+N+C=6 수학적 일관성**
- [ ] **W=5 Hot ⊂ W=10 Hot 포함 관계** SHAP 양 상관
- [ ] 미출현 Hot ↔ 핫콜드 Hot 강한 양 상관 (지표 결합 검증)
- [ ] current_pool_size 동적 변동이 expected에 영향 (SHAP 기여)

#### 19-7. 매트릭스 갱신

- 메인 1~45 매우 강 시그널 활성
- 다른 지표 매트릭스 미포함

---

### 지표 20: 회귀(2~200) — 별도 plan 파일로 분리 예정

#### 20-1. 분리 결정 근거

회귀 지표는 사용자 요구상 **거대한 분석 시스템**이라 본 plan에 포함하지 않고 별도 plan 파일로 분리. 사용자 결정(2026-04-27).

#### 20-2. 사용자 요구 7가지 분석 항목 (별도 plan에서 본격 설계)

| # | 분석 항목 | 차원 |
|---|---|---|
| A | 특정 회귀의 특정 번호 연속 출현 ("10회귀 2번 연속") | 번호×N×시간 |
| B | 각 번호의 전체 회귀 중첩 | 번호×N |
| C | 회귀별 연속 출현/미출현 길이 | N×시간 |
| D | 특정 회귀의 라인 패턴 | 라인×N |
| E | 번호대 + 회귀 결합 필터 | 번호대×N (의미 명확화 필요) |
| F | 라인 끝수의 다음 회차 출현 가능성 | 라인×끝수×N |
| G | 메타: 패턴이 자주 보이는 회귀 식별 | 메타 분석 |

#### 20-3. 4 Tier 시스템 청사진 (별도 plan에서 상세화)

- **Tier 1**: Per-N 회귀 카운트 199개 (DynamicIndependentCountPredictor — 가변 카테고리)
- **Tier 2**: 번호별 회귀 분석 (199 binary → 7~10 압축 변수)
- **Tier 3**: 라인·끝수·번호대 × 회귀 결합
- **Tier 4**: 메타 분석 (Gemma 4 narrative 입력)

#### 20-4. Phase 위치
Phase 1 (다른 지표 직접 입력 의존 없음).

#### 20-5. 본 plan에서의 임시 처리
- 미출현그룹(지표 18)이 광역 4 카테고리만 다루므로, 동적 N별 세부 분석은 회귀 plan 완성 시까지 미커버 상태
- 메인 1~45 모델은 임시로 단순 회귀 변수만 입력 (예: 각 번호의 N=직전출현후경과)

---

## 글로벌 파이프라인 수정 사항 (모든 지표 공통, 우선순위 최상)

지표별 재설계와 별개로, 다음 글로벌 결함이 모든 모델에 영향을 주므로 **구현 1순위**:

### G-1. Focal Loss 미스튜닝
- 현재: α=0.25, γ=2.0 (객체검출용 극단 imbalance 가정)
- 수정: 6/45=13% positive rate에 부적합
  - 옵션 A: BCEWithLogitsLoss + pos_weight=6.5 (XGBoost와 동일 매핑)
  - 옵션 B: Focal Loss 유지하되 α=0.5, pos_weight 제거
- 적용: 모든 1~45 binary 분류 모델 (LSTM, CNN, Transformer) — **GNN은 G-7에서 별도 처리** (SoftmaxRankingLoss + 0.3×BCE 결합)

### G-2. Bidirectional LSTM 축소
- 현재: bidirectional=True, hidden=128, layer=2, dropout=0.2
- 수정: bidirectional=False, hidden=64, layer=1~2 (1100여 회차 데이터 적합)

### G-3. 명시적 정규화
- 현재: pipeline·train_models에 정규화 코드 흔적 없음 (LottoEnsemble.train_all 내부 추정)
- 수정: 변수 그룹별 차등 정규화 명시 (StandardScaler / PowerTransformer / log1p / one-hot)
- **fit은 train fold에만**, walk-forward 매 fold 재fit

### G-4. Train/Val Split — TimeSeriesSplit walk-forward
- 현재: 명시 없음 (random split 가능성)
- 수정: `validation/timeseries_cv.py` 신규, n_splits=5, 마지막 100~200회차 hold-out

### G-5. 베이스라인 비교
- 현재: val_loss만, 베이스라인 없음
- 수정: `validation/baselines.py` 신규
  - rolling_mean / 균등 1/45 / 빈도분포 베이스라인
  - 매 epoch 베이스라인 대비 개선율 출력

### G-6. Random seed 고정
- 현재: 미설정
- 수정: `config.RANDOM_SEED = 42` 전역, 모든 모델·numpy·torch에서 사용

---

### G-7. GNN 자체 재설계

본 문서가 의존하는 7개 지표(총합/끝수합/끝수분포/고저/홀짝/번호대/소수합성)가 기존 GNN logits 집계에 의존하므로, GNN 자체의 안정성이 모든 downstream에 전파된다. 이전 문서가 다루지 않은 GNN 코드 진단·재설계.

#### G-7-1. 현재 코드 진단 (`langchain-backend/models/gnn_model.py` 530줄)

| 항목 | 현재 값 | 평가 |
|---|---|---|
| 구조 | 2-layer GAT 순수 PyTorch (10→64→32, heads=4→2) | OK |
| 손실 | `SoftmaxRankingLoss` — 45개 경쟁 + 정답 6개 log-prob 합산 | mode collapse 회피 시도 OK, 다만 이론 검증 부재 |
| 그래프 | 동반출현 카운트 → **Top-K=10 희소화** | over-smoothing 방지 OK. K=10이 1,100회차 dense graph에 적정한지 미검증 |
| 노드 피처 | 10 dim (출현율 3 + GAP 3 + hot_streak + parity + low_high + position) | 빈도 기반이 6/10 → 빈도 bias 위험 |
| Hyperparam | epochs=300, patience=30, LR=0.001, dropout=0.3 | 1,100 sample × 0.7 train ≈ 770에 epoch 300 과대 |
| Config 위치 | **`gnn_model.py` 24~33줄 내부 하드코딩** | `config.py` 다른 모델들과 통일 안 됨 |
| 메서드 | `forward()` → [45] logits, `predict_edge_prob()` 존재 (연속쌍 + top20 + attention) | 7개 지표가 의존 — 인터페이스 존속 필수 |

#### G-7-2. 재설계 결정 사항

**결정 A — SoftmaxRankingLoss 유지하되 보조 손실 추가**:
```
total_loss = SoftmaxRankingLoss + 0.3 × BCEWithLogitsLoss(pos_weight=6.5)
```
- Softmax 단독은 정답이 아닌 번호의 prob 미세 조정에 약함
- BCE 보조로 logit 안정성 확보, mode collapse 추가 방어

**결정 B — Hyperparameter 축소**:
- epochs: 300 → **80**, patience: 30 → **15**, LR: 0.001 → **0.0008**, dropout: 0.3 → **0.25**
- 모두 `config.py`로 이전: `GNN_EPOCHS`, `GNN_PATIENCE`, `GNN_LR`, `GNN_DROPOUT`, `GNN_HIDDEN_DIM=64`, `GNN_HEADS=[4,2]`, `GNN_TOPK=15`

**결정 C — Top-K 희소화 K=10 → K=15 (잠정)**:
- 1,100회차 누적 동반출현이 dense → K=10은 정보 손실 가능성
- **2단계 정책**:
  1. **잠정 default K=15** — `config.GNN_TOPK=15`로 시작. 본 default는 추측이 아닌 grid search 1차 결과 반영용 *seed*
  2. **검증 grid search** — `validation/timeseries_cv.py` 5-fold에서 K∈{10, 15, 20, 25} 검증, best K로 `config.GNN_TOPK` 갱신
- grid search 미수행 시 K=15 그대로 사용 (단, "잠정값"임을 학습 로그에 명시)

**결정 D — 노드 피처 정규화 명시**:
- 출현율 3개·GAP 3개·hot_streak: **PowerTransformer (Yeo-Johnson)** — long-tail 보정
- parity·low_high·position: **그대로** (binary 또는 이미 정규화된 0~1)
- fit은 train fold에만, walk-forward 매 fold 재fit

**결정 E — `predict_edge_prob()` 출력 안정화**:
- 현재 `attention_weights`는 정규화 인접 행렬의 log 스케일(그래프 구조 정보)
- 갱신: GAT layer 1의 *학습된* attention head 가중치도 함께 반환 → `gat_layer1_attn[heads=4, 45, 45]`
- 7개 지표가 그래프 구조 외에 학습된 attention도 활용 가능

**결정 F — Config 통합 + 가중치 마이그레이션**:
- `config.py`에 `GNN_*` 키 8개 추가 (`gnn_model.py` 내부 하드코딩 제거)
- 기존 `saved_models/gnn_model.pt` 가중치는 BCE head 추가로 호환 안 됨 → **0부터 재학습 필수**
- 마이그레이션: `gnn_force_retrain.flag` 파일 생성 시 `auto_train.py`가 GNN만 force_retrain=True

#### G-7-3. 수정 파일 목록

**수정 4**:
1. `langchain-backend/models/gnn_model.py` — Loss 결합, hyperparameter 외부화, attention 출력 추가
2. `langchain-backend/config.py` — `GNN_*` 키 8개 추가
3. `langchain-backend/scripts/auto_train.py` — `gnn_force_retrain.flag` 처리
4. `langchain-backend/models/ensemble.py` — `predict()` 내 GNN attention 출력 활용 (선택)

**신규 0** (gnn_model.py 내 강화)

#### G-7-4. 검증

- [ ] BCE 보조 추가 후 SoftmaxRankingLoss 단독 대비 val_loss 5-fold std 감소
- [ ] Top-K∈{10,15,20,25} grid search → 7개 지표 정확도
- [ ] mode collapse 진단 — 출력 logits entropy < 3.0 (균등 1/45=log45=3.81 대비)
- [ ] epoch 80 / patience 15에서 early stopping 정상 발동 (학습 곡선 검수)
- [ ] 7개 지표(총합/끝수합/끝수분포/고저/홀짝/번호대/소수합성)의 GNN 집계 결과 베이스라인 이상 정확도

---

## MetaLearner / Ensemble / 학습 순서 / SLA 인프라

### M-1. MetaLearner 재구축

본 문서가 다루지 않은 `LottoEnsemble` (1,108줄) 인프라 — **task 8종 가중치 매트릭스, DB 적중률 블렌딩, AE 페널티, hard filter, meta_log.jsonl 부트스트랩** 모두 이미 구현됨. 21지표 재설계가 이 인프라와 *충돌하지 않도록* 매핑 재정의.

#### M-1-1. 현재 코드 진단

```
LottoEnsemble (langchain-backend/models/ensemble.py):
  ├─ 기본 가중치: {xgb:0.25, lstm:0.20, cnn:0.10, transformer:0.18, gnn:0.15, markov:0.08, ae:0.04}
  ├─ saved_models/ensemble_weights.json (진화된 가중치)
  ├─ task 8종 가중치 매트릭스 (42~123줄):
  │    recommend_top, exclude, filter_range, filter_count_attr,
  │    filter_count_temporal, filter_count_relation, filter_spatial, regression
  ├─ MetaLearner stacking (alpha=0.30 고정): final = (1-α)·ensemble + α·meta
  ├─ DB 적중률 블렌딩 (50:50, 297~317줄): 최근 20회차 모델별 평균 적중수
  ├─ Autoencoder 페널티 (460~469줄): final_probs[n] *= (1.0 - ae_excl_val)
  ├─ Hard filter (사용자 메모, 474~483줄): excluded_numbers → 0.0 강제
  └─ meta_log.jsonl 부트스트랩 (989~1063줄)
```

#### M-1-2. 21지표 재설계와의 충돌 분석

| 충돌 영역 | 현재 | 재설계 후 충돌 |
|---|---|---|
| Task 8종 매트릭스 | filter_count_attr/temporal/relation 카테고리화 | 21지표가 새 카테고리 체계 → 매핑 미정 |
| Markov 별도 처리 | `_train_temp_markov()` JSON 파일 | 21개 predictor 각자 Markov 사용 → 중복 |
| `alpha=0.30` 고정 | 학습 X | 21지표 출력 통합 시 alpha 데이터 학습 필요 |
| Meta_log.jsonl | 단일 base 모델 → 정답 매핑 | 21 predictor 각각 메타 로그 필요 → 차원 폭증 |

#### M-1-3. 재설계 결정 사항

**결정 A — Task 8종 매트릭스를 21지표 Phase 1~4와 정합**:
```python
# config.py에 신규 매핑
TASK_PREDICTOR_MAP = {
    "recommend_top":          ["main_45"],
    "exclude":                ["main_45", "ae"],
    "filter_range":           ["sum", "ac", "endings_sum"],
    "filter_count_attr":      ["high_low", "odd_even", "carryover", "neighbor", "consecutive"],
    "filter_count_temporal":  ["hotcold_12", "missing_4"],
    "filter_count_relation":  ["decade_5", "gung_9", "paper_14", "multiple_6", "prime_3"],
    "filter_spatial":         ["paper_14", "gung_9"],
    "regression":             ["regression"],
}
```

**결정 B — Markov를 7번째 base 모델로 통합**:
- 신규 클래스: `models/markov_model.py::LottoMarkovModel`
- 인터페이스: 다른 6개 모델과 동일 (`fit()`, `predict()`, `save()`, `load()`)
- `LottoEnsemble.models` dict에 정식 등록 (별도 처리 제거)
- `_train_temp_markov()` 폐기

**결정 C — `alpha`를 학습 가능한 파라미터로**:
```python
from scipy.optimize import minimize_scalar
import numpy as np

class MetaLearner:
    def fit_alpha(self, ensemble_pred, meta_pred, val_labels):
        """
        모델: final = (1-α)·ensemble_pred + α·meta_pred
        목적: MSE(final, val_labels) 최소화, α ∈ [0, 1]

        주의: 일반 Ridge regression은 α ∈ [0,1] 보장 안 됨 (음수 coef·합≠1 가능).
              제약 최적화로 bounded scalar search 사용.
        """
        def loss(a):
            return np.mean((((1 - a) * ensemble_pred + a * meta_pred) - val_labels) ** 2)
        res = minimize_scalar(loss, bounds=(0.0, 1.0), method='bounded')
        self.alpha = float(res.x)
```
- weekly_pipeline_v2가 hold-out 100회차에서 매 학습 사이클마다 alpha 재산출
- 기본값 0.30은 first-run 시드로만 사용
- 검증 데이터가 부족(< 50회차)하면 alpha 학습 스킵하고 시드값 유지

**결정 D — 21 Predictor 메타 로그 분리 (jsonl → parquet)**:
- 현재 `meta_log.jsonl` 단일 → **3-level 분리**:
  - `meta_log_main.jsonl` — 메인 1~45 모델 base 7개 + ensemble + meta
  - `meta_log_phase1.parquet` — Phase 1 13개 predictor
  - `meta_log_phase234.parquet` — Phase 2~4 (끝수합/AC/총합)
- Parquet 사용 이유: 21 × 1100회 = 23K row × 50 col 누적 시 jsonl IO 병목

**결정 E — Autoencoder 게이팅을 *플래그 broadcast* 방식으로 통합**:

> 현재 AE는 1~45 prob 입력 → exclusion 출력. 17 predictor 출력은 7-class category 분포 → 형식 불일치.
> 따라서 AE를 각 predictor 출력에 *직접* 적용하지 않고, **회차 단위 "이상 회차" 플래그를 broadcast**.

- **AE 입력은 그대로 유지** (1~45 prob, 메인 ensemble에서만 평가)
- 회차별 산출: `is_anomaly_round = (ae_recon_error > train_fold_95p)` — boolean
- 17 predictor에는 *플래그만 broadcast* — 이상 회차 시 각 predictor의 *복잡 모델 가중치* dampening:
  ```python
  # 각 predictor 내부 결합 시
  if is_anomaly_round:
      lstm_weight *= 0.5
      transformer_weight *= 0.5
      markov_weight *= 1.5  # 단순 모델 보강
      ridge_weight *= 1.5
  ```
- 임계값: train fold AE 재구성오차 분포의 95p로 fit, hold-out에서만 평가
- 신규 메서드: `LottoEnsemble.compute_anomaly_flag(draws) -> bool` — 모든 17 predictor가 호출
- 형식 불일치 문제 자동 해소: AE 출력을 predictor마다 변환하지 않고 boolean만 사용

**결정 F — Task 가중치 매트릭스 학습 가능화**:
- 현재 하드코딩(42~123줄) → `saved_models/task_weights.json` 외부 파일 + walk-forward CV로 학습
- weekly_pipeline_v2가 매 학습 사이클마다 task 가중치 갱신

#### M-1-4. 수정 파일 목록

**신규 1**:
1. `langchain-backend/models/markov_model.py` — `LottoMarkovModel` 클래스

**수정 5**:
2. `langchain-backend/models/ensemble.py` — task 매트릭스 외부화, Markov 통합, AE 게이트 일반화, train_all 분해 (700줄+ → 300줄 목표)
3. `langchain-backend/models/meta_learner.py` — `fit_alpha()`, 21 predictor 로그 분리
4. `langchain-backend/pipeline/weekly_pipeline_v2.py` — meta 학습 호출 추가
5. `langchain-backend/config.py` — `TASK_PREDICTOR_MAP`, `META_ALPHA_DEFAULT=0.30`, `AE_GATE_PERCENTILE=95` 추가
6. `langchain-backend/scripts/auto_train.py` — `task_weights.json` 부트스트랩

#### M-1-5. 검증

- [ ] Markov 통합 후 기존 `_train_temp_markov()` 호출 0건 (grep)
- [ ] `fit_alpha()` 학습된 alpha가 hold-out 100회에서 alpha=0.30 고정 대비 정확도 ≥ 동등
- [ ] task_weights.json 학습 후 8종 task별 정확도 5-fold std 감소
- [ ] meta_log Parquet 변환 후 IO 시간 < jsonl 50%
- [ ] AE 게이트가 21 predictor 모두에 적용 (단위 테스트)

---

### T-1. 학습 순서 / 파이프라인 오케스트레이션

#### T-1-1. 현재 진단 (본 문서 26번 줄 추정과 다른 사실)

- 본 문서 추정: `Markov → XGBoost → CNN → LSTM → Transformer`
- **실제 코드**: 학습 순서 *없음*. `for name, model in self.models.items()` Python dict 삽입 순서(xgb→lstm→cnn→transformer→ae→gnn) 우연 의존. Markov만 후처리.
- 7개 모델은 *서로 의존성 없음* — 각 모델이 raw draws로부터 독립 학습

#### T-1-2. 21지표 재설계 후 학습 의존성 그래프 (DAG)

```
[Stage 0] 글로벌 인프라
  ├─ G-1~G-6 적용 (focal/bidir/정규화/CV/baseline/seed)
  ├─ G-7 GNN 재설계 학습 (다른 모든 단계 선행)
  └─ M-1 Markov 통합 클래스 학습

[Stage 1] Phase 1 Predictor 16개 + 이월수 보너스 변형 1 = 17 인스턴스 학습 (서로 의존 없음)
  ├─ 끝수 0~9 (IndependentCountPredictor, N=10)         # 1 predictor
  ├─ 번호대 5                                              # 1
  ├─ 9궁 9                                                # 1
  ├─ 로또용지 14                                          # 1
  ├─ 배수 6 (배수외 포함)                                 # 1
  ├─ 소수+합성수+1                                        # 1
  ├─ 삼각수 / 제곱수 / 동형수                              # 3 (각 단일 카테고리)
  ├─ 미출현그룹 4 / 핫콜드 12                              # 2
  ├─ 이월수(정확) + 이월수(보너스 포함) / 이웃수 / 연번    # 4 (이월수 2 인스턴스)
  ├─ 고저 / 홀짝                                          # 2
  └─ 회귀 Tier 1 (별도 plan에서 상세)                     # 1
  = 총 17 인스턴스 (16 predictor 모델 클래스, 이월수만 2 인스턴스)

[Stage 2] Phase 2 (Phase 1 출력 캐시)
  └─ 끝수합 (digit_dist[10] 입력)

[Stage 3] Phase 3 (Phase 1+2 캐시)
  └─ AC값 (high_count, endings_sum, consecutive 입력)

[Stage 4] Phase 4 (Phase 1+2+3 모두)
  └─ 총합 (sum 카르텟: 번호대/9궁/가로행/소수합성 + 모든 시그널)

[Stage 5] 메인 1~45 모델 (모든 Phase 출력을 외부 feature slot)
  ├─ LSTM, CNN, Transformer, XGBoost (INPUT_DIM 동결)
  └─ AE (재구성오차 base)

[Stage 6] MetaLearner 부트스트랩
  ├─ Task 8종 가중치 매트릭스 학습 (`task_weights.json`)
  ├─ alpha 학습 (`fit_alpha()`)
  └─ meta_log_*.parquet 생성
```

#### T-1-3. 핵심 결정 사항

**결정 A — 메인 1~45 모델은 외부 feature slot 인터페이스**:
- 메인 모델 `INPUT_DIM` **65 동결** (LSTM/Transformer/XGBoost)
- Phase 1~4 출력은 *후처리 게이트*로만 결합 (`ensemble.predict()` 후단)
- 본 문서의 "LSTM 65→80→95→100→…" 누적 확장은 **전부 폐기** (이전 검토 3-1 차원 폭발 위험 해소)
- 신규: `models/posthoc_gate.py` — 메인 prob × Phase 게이트 보정

**결정 B — Stage별 캐시 파일 명세**:
```
saved_models/cache/
  ├─ phase1/
  │   ├─ digit_predictor_outputs.parquet     # 회차×끝수×7-class
  │   ├─ decade_predictor_outputs.parquet
  │   └─ ... (Phase 1 13개)
  ├─ phase2/endings_sum_outputs.parquet
  ├─ phase3/ac_outputs.parquet
  ├─ phase4/sum_outputs.parquet
  └─ main/main_45_outputs.parquet
```
- 각 캐시: 회차 인덱스 + predictor 출력 dict (parquet 압축)
- weekly_pipeline_v2가 stage 진입 시 이전 stage 캐시 *읽기 전용* 로드
- 학습 실패 시 해당 stage 캐시만 무효화

**결정 C — v1 (`weekly_pipeline.py`) 제거**:
- v2가 single source of truth로 확정
- `weekly_pipeline.py` 파일 삭제 (코드 정리 PR 별건)
- `routes/`에서 v1 import 0건 확인

**결정 D — 학습 호출 통합 메서드**:
- 신규: `pipeline/training_orchestrator.py::TrainingOrchestrator`
  - `run_stage(stage_id, fold_id)` — DAG 1 stage 실행
  - `run_all_stages()` — 전체 6 stage 순차
  - `validate_dag()` — 캐시 파일 무결성 검증 (Stage N 진입 전 N-1 캐시 모두 존재)
- weekly_pipeline_v2._run_analysis()가 orchestrator 호출

**결정 E — Phase 1 병렬 학습 (조건부)**:
- Phase 1 21개 predictor는 서로 의존 없음 → 병렬 가능
- `concurrent.futures.ProcessPoolExecutor(max_workers=2)` (HF Spaces 2 cores 한도)
- 일단 순차 실행으로 시작, S-1 SLA 초과 시 병렬화

#### T-1-4. 수정 파일 목록

**신규 2**:
1. `langchain-backend/pipeline/training_orchestrator.py` — DAG 실행
2. `langchain-backend/models/posthoc_gate.py` — 메인 모델 외부 feature slot

**수정 4**:
3. `langchain-backend/pipeline/weekly_pipeline_v2.py` — orchestrator 호출
4. `langchain-backend/models/ensemble.py` — `train_all()` 분해 후 orchestrator로 이전
5. `langchain-backend/scripts/train_models.py` — orchestrator 호출 + stage별 출력 명시
6. `langchain-backend/scripts/auto_train.py` — orchestrator + force_retrain stage별 적용

**삭제 1**:
7. `langchain-backend/pipeline/weekly_pipeline.py` (v1 레거시)

#### T-1-5. 검증

- [ ] DAG 6 stage 모두 정상 실행 (`validate_dag()` 100% pass)
- [ ] Stage 1 캐시 21개가 Stage 2~5에서 정확히 로드 (회차 인덱스 정합)
- [ ] 메인 1~45 모델 INPUT_DIM 65 그대로 (변경 0건, grep)
- [ ] v1 import 0건 (grep `from .weekly_pipeline import`)
- [ ] Stage 실패 시 해당 stage 캐시만 무효화 (단위 테스트)
- [ ] Phase 1 병렬화 시 결과 동일성 (순차 vs 병렬 동일 출력)

---

### S-1. SLA — 추론 wall-time / 메모리 / 폭증 대응

#### S-1-1. 현재 환경 진단

| 항목 | 값 | 출처 |
|---|---|---|
| 배포 | HF Spaces 무료 | Dockerfile (port 7860) |
| RAM | 추정 15GB | HF Spaces 무료 spec |
| CPU | 2 cores | HF Spaces 무료 spec |
| GPU | 없음 (`torch+cpu`) | Dockerfile 6줄 |
| 요청 timeout | 추정 120s | HF Spaces 기본 |
| 학습 wall-time (현재) | **추정 4~6h** (순차) | LSTM 1 epoch ~30~60s × 100 epoch × 7 모델 |
| 추론 wall-time (현재) | 미측정 | - |

#### S-1-2. 21지표 재설계 후 폭증 위험 추정

| 변수 | 현재 | 재설계 후 | 배수 |
|---|---|---|---|
| 학습 모델 수 | 7 (base) | 7 (base) + 17 (Phase 1) + 3 (Phase 2~4) + 1 (meta) = **28 인스턴스** | ~4× |
| 학습 wall-time | 4~6h | **24~36h** (순차, 캐시 없음) | 6× |
| 메모리 peak (학습) | ~6GB | **12~14GB** (Category GNN 임베딩 + 캐시) | 2× |
| 메모리 peak (추론) — T-1 결정 A 적용 후 | ~2GB | **3~4GB** (메인 ensemble + 캐시 IO만, 17 predictor 동시 로드 X) | 1.5× |
| 메모리 peak (추론) — 캐시 미스 시 fallback | - | **6~8GB** (최악의 경우 17 predictor lazy load) | 3~4× |
| 추론 wall-time (단일 회차) | 미측정 | **15~40s** (캐시 hit) / **60~120s** (캐시 miss) | - |

→ HF Spaces 무료 한도(15GB / 120s) — T-1 결정 A 적용 후 캐시 hit 시 안전, 캐시 miss 시 위협. **캐시 신선도 관리가 핵심**.

#### S-1-3. SLA 목표 수치

| SLA | 목표 | 위반 시 액션 |
|---|---|---|
| **주간 학습 wall-time** | ≤ 24h (cron 1회/주) | 24h 초과 시 GPU 단계 유료 전환 검토 |
| **단일 회차 추론** | ≤ 30s (대시보드) | 30s 초과 시 Phase 캐시 hot-load |
| **추론 메모리 peak** | ≤ 12GB (15GB - 안전마진 3GB) | 12GB 초과 시 lazy load |
| **학습 메모리 peak** | ≤ 14GB | 14GB 초과 시 sequential train (병렬 X) |
| **API timeout** | ≤ 120s | timeout 시 Phase 1 출력만 반환 (graceful degradation) |

#### S-1-4. 측정 인프라

**신규 1**: `langchain-backend/pipeline/sla_monitor.py`
```python
class SLAMonitor:
    def __enter__(self):
        self.t0 = time.time()
        self.mem0 = psutil.Process().memory_info().rss
    def __exit__(self, *args):
        self.wall_time = time.time() - self.t0
        self.mem_peak = psutil.Process().memory_info().rss - self.mem0
        log_sla(self.tag, self.wall_time, self.mem_peak)

# 사용
with SLAMonitor("phase1_digit_predictor_train"):
    digit_predictor.fit(...)
```

**신규 2**: `saved_models/sla_history.parquet`
- 회차별 × stage별 wall_time, mem_peak, status
- 1~2년 누적 시 SLA 추세 분석 가능

#### S-1-5. 폭증 대응 전략 (우선순위 順)

**Tier 1 — 즉시 적용 (코드 변경)**:
1. **Phase 1~4 출력 캐시 적극 사용** — 회차 변경 없으면 캐시 히트, 학습 sub-stage 스킵
2. **모델 lazy load** — `ensemble.py`가 task별 필요한 모델만 메모리 로드
3. **Parquet 압축** — meta_log jsonl → parquet (M-1 결정 D)
4. **walk-forward 5-fold CV로만 학습** (full epoch 미적용 시 30%+ 시간 절감)

**Tier 2 — SLA 위반 시**:
5. **HF Spaces 유료 전환** — Pro ($9/월): RAM 32GB, GPU T4 옵션
6. **GPU 활용** — `torch+cu118` 재빌드, `Dockerfile --gpus all`
7. **Phase 1 병렬화** — `ProcessPoolExecutor(max_workers=2)`
8. **외부 학습 분리** — GitHub Actions cron으로 학습 (HF Spaces는 추론만)

**Tier 3 — 마지막 수단**:
9. **지표 우선순위 컷** — 베이스라인 못 이긴 predictor 폐기. 컷 기준은 *데이터 검증 결과*에 의존하며, 사용자가 추가한 지표(제곱수·동형수 등)는 *사전 컷 후보로 명시하지 않음*. 검증 후 5-fold CE/MAE가 베이스라인 대비 effect size < 0.1 이고 p-value > 0.1인 predictor만 컷 후보로 보고
10. **메인 1~45 모델만 hot-path** — Phase 1~4 출력은 cron 사전계산, 추론은 캐시 조회만

#### S-1-6. 수정 파일 목록

**신규 2**:
1. `langchain-backend/pipeline/sla_monitor.py` — `SLAMonitor` 컨텍스트 매니저
2. `langchain-backend/dashboards/sla_report.py` — 회차별 SLA 추세 (Gemma 4 narrative 보조)

**수정 5**:
3. `langchain-backend/Dockerfile` — `psutil` 추가, GPU 빌드 옵션 주석
4. `langchain-backend/pipeline/training_orchestrator.py` — 각 stage에 SLAMonitor 래핑
5. `langchain-backend/pipeline/weekly_pipeline_v2.py` — 추론 SLA 측정
6. `langchain-backend/models/ensemble.py` — lazy load 구현
7. `langchain-backend/config.py` — `SLA_*` 키 5개 (`SLA_TRAIN_WALL_TIME_MAX=86400`, `SLA_INFER_WALL_TIME_MAX=30`, `SLA_INFER_MEM_MAX_GB=12`, `SLA_TRAIN_MEM_MAX_GB=14`, `SLA_API_TIMEOUT=120`)

#### S-1-7. 검증

- [ ] SLAMonitor가 6 stage 모두 wall_time/mem_peak 기록
- [ ] sla_history.parquet 100회 누적 후 추세 분석 가능
- [ ] 추론 SLA 30s 미달성 회차 발생 시 자동 알림 (로그 ERROR)
- [ ] 메모리 12GB 초과 시 lazy load 트리거 정상 동작
- [ ] 학습 wall-time 24h 초과 시 GitHub Actions로 학습 분리 (Tier 2-8)

---

## U-1 ~ U-4. 보조 인프라 명세 (해결 완료)

이전 검토에서 미해결로 분류됐던 4개 항목을 본 문서 내에서 직접 명세화. 본 절은 G-1~G-7·M-1·T-1·S-1과 동급의 글로벌 인프라.

---

### U-1. 단위 테스트 명세 (이전 검토 L-8 해결)

#### U-1-1. 테스트 디렉터리 구조

```
tests/
  ├─ unit/
  │   ├─ test_filter_stats.py            # 20지표 계산 함수 정답 매칭
  │   ├─ test_predictors_scalar.py       # sum/ac/endings_sum predictor
  │   ├─ test_predictors_categorical.py  # 고저/홀짝/이월/이웃/연번
  │   ├─ test_predictors_independent.py  # IndependentCountPredictor 11개
  │   ├─ test_gnn_aggregation.py         # 7지표 GNN 집계식
  │   ├─ test_meta_learner.py            # alpha 학습 (D-2)
  │   ├─ test_ae_gate_flag.py            # AE boolean broadcast (D-6)
  │   └─ test_orchestrator_dag.py        # T-1 validate_dag()
  ├─ integration/
  │   ├─ test_walk_forward_5fold.py      # 마지막 50회차 시뮬레이션
  │   ├─ test_phase_cache_consistency.py # Phase 1→2→3→4 캐시 정합
  │   └─ test_sla_monitor.py             # SLAMonitor wall-time/메모리 측정
  └─ fixtures/
      └─ golden_draws_round100_to_120.json   # 알려진 정답 골든 데이터
```

#### U-1-2. 골든 데이터 정의

- 회차 100~120 (21회) draws — 실제 lottoanalysis DB에서 추출한 고정 fixture
- 각 회차에 대한 *수동 검증 정답* 포함:
  ```json
  {
    "round": 100,
    "numbers": [1, 7, 23, 35, 41, 45],
    "bonus": 12,
    "expected_indicators": {
      "sum": 152,
      "tail_sum": 22,
      "ac_value": 8,
      "low_count": 2, "high_count": 4,
      "odd_count": 4, "even_count": 2,
      "carryover_exact": 1, "carryover_with_bonus": 1,
      "neighbor_count": 2, "consecutive_count": 0,
      "digit_dist": [0, 1, 0, 1, 0, 1, 0, 1, 0, 2],
      "decade_dist": [1, 1, 1, 1, 2],
      "gung_dist": [1, 1, 0, 0, 1, 0, 1, 1, 1],
      "paper_horizontal_dist": [1, 1, 1, 0, 1, 1, 1],
      "paper_vertical_dist": [2, 0, 1, 0, 1, 0, 2],
      "multiple_3_count": 0, "multiple_4_count": 0, "multiple_5_count": 2,
      "multiple_7_count": 2, "multiple_8_count": 0, "non_multiple_count": 2,
      "prime_count": 3, "composite_count": 2, "one_count": 1,
      "triangular_count": 1, "square_count": 1, "twin_count": 0
    }
  }
  ```

#### U-1-3. 핵심 테스트 케이스 패턴

```python
# tests/unit/test_filter_stats.py
import pytest, json
from pathlib import Path
from langchain_backend.services.filter_stats import FilterStatsComputer

GOLDEN = json.loads(Path("tests/fixtures/golden_draws_round100_to_120.json").read_text())

@pytest.mark.parametrize("entry", GOLDEN)
def test_indicator_calculation_matches_golden(entry):
    fsc = FilterStatsComputer(all_numbers=[entry["numbers"]], recent_numbers=[entry["numbers"]])
    for indicator_name, expected_value in entry["expected_indicators"].items():
        actual = fsc.compute_indicator(indicator_name, entry["numbers"], entry["bonus"])
        assert actual == expected_value, f"R{entry['round']} {indicator_name}: {actual} != {expected_value}"
```

#### U-1-4. CI 통합

- GitHub Actions `.github/workflows/test.yml`: `pytest tests/unit -v --cov=langchain-backend --cov-fail-under=70`
- 통합 테스트 `tests/integration/`은 nightly cron (학습 fixture 필요해 느림)
- 각 PR에서 unit 테스트 100% 통과 + cov 70% 이상 강제

#### U-1-5. 검증

- [ ] 골든 데이터 21회차 모두에서 모든 20지표 계산 정답 일치
- [ ] CI에서 unit 테스트 < 30초, integration < 10분
- [ ] 각 predictor별 단위 테스트 (출력 형식 dict 키 + 합계 ≈6 등 보조 일관성) 통과
- [ ] T-1 orchestrator의 `validate_dag()` 단위 테스트 (Stage N 진입 전 N-1 캐시 모두 존재 검증)

---

### U-2. 16개 Predictor 하이퍼파라미터 명세 (이전 검토 L-9 해결)

#### U-2-1. 공통 정책 (1,100회차 데이터 적합)

모든 신규 predictor는 다음 공통 정책 따름:
- **epochs=80, patience=15** (G-7과 동일, early stopping 활성)
- **LR=0.0008** (G-7과 동일)
- **batch=32** (1,100 sample 작은 데이터에 64는 fold당 batch 수 부족)
- **dropout=0.25** (G-7과 동일)
- **RANDOM_SEED=42** (G-6 적용)
- **walk-forward 5-fold CV** (G-4 적용)
- **train fold normalize fit** (G-3 적용)
- 모든 base 모델은 G-1 적용 — Focal Loss 제거, BCE + pos_weight=6.5 (단 GNN은 G-7 별도)

#### U-2-2. 모델별 세부 하이퍼파라미터

```python
# config.py 신규 키 (모든 신규 predictor 공통 + 모델별)

# === 공통 정책 ===
PREDICTOR_EPOCHS = 80
PREDICTOR_PATIENCE = 15
PREDICTOR_LR = 0.0008
PREDICTOR_BATCH = 32
PREDICTOR_DROPOUT = 0.25

# === 경량 LSTM (sum/ac/endings_sum/categorical/independent 공통) ===
LIGHT_LSTM_HIDDEN = 32         # 메인 LSTM(128)의 1/4
LIGHT_LSTM_LAYERS = 1
LIGHT_LSTM_BIDIRECTIONAL = False  # G-2 적용
LIGHT_LSTM_DROPOUT = 0.1

# === 경량 Transformer (스칼라 predictor 전용) ===
LIGHT_TRANSFORMER_D_MODEL = 64
LIGHT_TRANSFORMER_NHEAD = 2
LIGHT_TRANSFORMER_LAYERS = 1
LIGHT_TRANSFORMER_FFN = 128
LIGHT_TRANSFORMER_DROPOUT = 0.2

# === XGBoost Quantile (sum/ac/endings_sum) ===
XGB_QUANTILE_N_ESTIMATORS = 150
XGB_QUANTILE_MAX_DEPTH = 5
XGB_QUANTILE_LR = 0.05
XGB_QUANTILE_QUANTILES = [0.10, 0.50, 0.90]
XGB_QUANTILE_SUBSAMPLE = 0.8

# === XGBoost Multiclass (categorical predictor) ===
XGB_MULTICLASS_N_ESTIMATORS = 100
XGB_MULTICLASS_MAX_DEPTH = 4   # 7-class에서 deep tree 과적합 위험
XGB_MULTICLASS_LR = 0.08
XGB_MULTICLASS_SUBSAMPLE = 0.8

# === Markov n-state ===
MARKOV_LAPLACE_SMOOTHING = 0.5  # 데이터 sparse 시 0이 되지 않도록
MARKOV_BUCKET_METHOD = "quantile"  # U-3 참조
```

#### U-2-3. Predictor별 하이퍼파라미터

```python
# === 스칼라 Predictor 3개 ===
SUM_PREDICTOR = {
    "feature_dim": 13,
    "markov_n_buckets": 6,        # U-3에서 데이터 분위수로 자동 산출
    "ridge_alpha": 1.0,           # meta layer Ridge regularization
    **공통 정책,
}
AC_PREDICTOR = {
    "feature_dim": 15,            # 공통 13 + ac 고유 2
    "markov_n_states": 11,        # AC가 자연 정수 0~10
    "ridge_alpha": 1.0,
    **공통 정책,
}
ENDINGS_SUM_PREDICTOR = {  # scalar head only
    "feature_dim": 13,
    "markov_n_buckets": 6,
    "ridge_alpha": 1.0,
    **공통 정책,
}

# === Categorical Count Predictor (5종 공유) ===
CATEGORICAL_PREDICTOR = {
    "n_classes": 7,               # 0~6 (연번은 6)
    "use_class_weight_sqrt_inverse": True,
    "ce_label_smoothing": 0.05,   # mode collapse 방어
    "use_focal": False,           # G-1 결정
    **공통 정책,
}
# 인스턴스: high_low / odd_even / carryover_exact / carryover_with_bonus / neighbor / consecutive(n_classes=6)

# === IndependentCountPredictor (11지표 공유) ===
INDEPENDENT_COUNT_PREDICTOR = {
    "n_classes": 7,
    "category_gnn_hidden": 16,
    "category_gnn_layers": 2,
    "category_gnn_heads": 2,
    "pairwise_feature_lag_window": 20,
    "aux_consistency_loss_weight": 0.2,    # Σexpected ≈ 6 강제
    "aux_corr_loss_weight": 0.1,            # 학습 corr ≈ 데이터 corr
    "use_focal": False,
    **공통 정책,
}
# 카테고리 마커별 인스턴스: digit_10 / decade_5 / gung_9 / paper_14 / multiple_6 / prime_3 /
#                            triangular / square / twin / missing_4 / hotcold_12
```

#### U-2-4. 검증

- [ ] 모든 predictor가 epochs=80, patience=15에서 수렴 (학습 곡선 검수)
- [ ] 베이스라인(rolling_mean / 균등 1/N / 빈도분포) 대비 5-fold CE/MAE 평균이 effect size ≥ 0.1로 우월
- [ ] Light LSTM(hidden=32)이 메인 LSTM(hidden=128) 대비 학습 시간 1/4 이하
- [ ] 1,100 sample × 0.7 train ≈ 770 batch_32 × 80 epoch이 SLA 24h 내 완수

---

### U-3. Markov Bucket 임계값 자동 도출 (이전 검토 L-11 해결)

#### U-3-1. 정책

지표 1·2·3 (sum/AC/endings_sum) Markov bucket 임계값은 **임의 하드코딩 금지**. 학습 fold 데이터의 *분위수* 기반 자동 산출.

#### U-3-2. 신규 모듈 — `langchain-backend/validation/bucket_calibration.py`

```python
import numpy as np

def calibrate_markov_buckets(values: np.ndarray, n_buckets: int = 6, method: str = "quantile") -> list[float]:
    """
    학습 fold 분위수 기반 자동 bucket 경계 산출.

    Args:
        values: 학습 fold의 지표값 배열 (예: 회차별 sum)
        n_buckets: bucket 개수 (sum=6, endings_sum=6, AC는 11-state로 자연 정수 사용 — 호출 안 함)
        method: "quantile" (분위수) | "kmeans" (1D k-means) | "uniform" (균등 width)

    Returns:
        bucket 내부 경계 (n_buckets-1개). 예: n_buckets=6 → 5개 경계.
    """
    if method == "quantile":
        # n_buckets=6: [16.7%, 33.3%, 50%, 66.7%, 83.3%]
        quantiles = np.linspace(0, 100, n_buckets + 1)[1:-1]  # 양 끝 제외
        return np.percentile(values, quantiles).tolist()
    elif method == "kmeans":
        from sklearn.cluster import KMeans
        km = KMeans(n_clusters=n_buckets, random_state=42).fit(values.reshape(-1, 1))
        centers = sorted(km.cluster_centers_.flatten())
        return [(centers[i] + centers[i+1]) / 2 for i in range(len(centers) - 1)]
    elif method == "uniform":
        v_min, v_max = values.min(), values.max()
        return np.linspace(v_min, v_max, n_buckets + 1)[1:-1].tolist()
```

#### U-3-3. AC 지표 예외 (자연 이산 정수)

- AC값은 0~10의 11-state 자연 이산 → bucket 산출 *호출 안 함*
- `MARKOV_AC_STATES = list(range(11))` 고정

#### U-3-4. Walk-forward 적용

- `validation/timeseries_cv.py` 5-fold 매 fold마다:
  ```python
  train_fold_values = train_data["sum"].values
  buckets = calibrate_markov_buckets(train_fold_values, n_buckets=6, method="quantile")
  sum_predictor.markov.fit_transitions(train_data, buckets=buckets)
  ```
- bucket 경계가 fold마다 다를 수 있음 — 본 fold의 transition 행렬에만 사용
- 마지막 inference fold(prediction)에서는 *전체 학습 데이터*의 분위수 기반 경계 사용

#### U-3-5. 검증

- [ ] sum/endings_sum bucket이 데이터 분포 균등 분할(각 bucket이 ~16.7% sample 보유)
- [ ] kmeans method가 quantile 대비 mode 보존(중앙값 영역에 buckets 더 조밀) — 비교 후 default 결정
- [ ] AC 11-state 고정값이 자연 정수 분포와 일치 (0이 가장 드물고 7~8이 mode)
- [ ] 매 fold bucket 변화 시 Markov 전이행렬이 적절히 재학습 (단위 테스트)

---

### U-4. Gemma 4 LLM 호출 인터페이스 (이전 검토 L-12 해결)

#### U-4-1. 호출 흐름

```
[weekly_pipeline_v2._run_analysis() 끝부분]
  │
  ├─ 17 predictor 모두 evidence dict + narrative_seed 산출 완료
  │
  ├─ batch narrative request 생성:
  │     {
  │       "predictor_id": "sum",
  │       "predicted": {"min", "max", "median", "p10", "p90"},
  │       "evidence": {"rolling_mean_20": ..., "feature_contribution_top3": [...]},
  │       "narrative_seed": "sum 138 부근, 직전 152 → 회귀 모드"
  │     } × 17
  │
  ├─ chains/narrative_chain.py::generate_batch_narratives(requests) 1회 호출
  │     │
  │     ├─ 각 request → Gemma 4 prompt 템플릿 적용 (병렬 처리)
  │     ├─ Gemma 4 inference (HF Spaces 내부 모델)
  │     └─ 자연어 narrative 17개 반환
  │
  └─ weekly_* 테이블에 narrative와 evidence 같이 저장
```

#### U-4-2. 신규 모듈 — `langchain-backend/chains/narrative_chain.py`

```python
from langchain.prompts import PromptTemplate
from langchain.schema.runnable import RunnableParallel
from .gemma_loader import get_gemma4_chain  # 기존 chains 인프라 재사용

NARRATIVE_PROMPT = PromptTemplate.from_template("""
당신은 로또 분석 보고서 작성자입니다. 아래 분석 결과를 한국어 1~2 문장 narrative로 요약하세요.

지표: {predictor_id}
예측 결과: {predicted}
근거 (top-3 feature): {evidence}
초안: {narrative_seed}

조건:
- 1~2 문장, 50~120 글자
- 통계 용어보다 자연어 흐름 우선
- 확률은 % 표기
- 추측·과장 금지

narrative:
""")

def generate_batch_narratives(requests: list[dict]) -> dict[str, str]:
    """
    17 predictor evidence dict → Gemma 4 narrative 일괄 생성.

    SLA: HF Spaces CPU에서 17 request 합쳐 < 20s (S-1 추론 SLA 30s 내).
    """
    chain = NARRATIVE_PROMPT | get_gemma4_chain()
    parallel = RunnableParallel({
        req["predictor_id"]: chain.partial(**req) for req in requests
    })
    return parallel.invoke({})
```

#### U-4-3. Evidence dict 표준 스키마 (모든 predictor 의무화)

```python
{
    "predictor_id": str,                     # "sum", "endings_sum", "high_low", ...
    "phase": int,                            # 1~4
    "predicted": {                           # 예측 결과 (predictor 타입별)
        # 스칼라: min/max/median/p10/p90
        # 카테고리: top_class/top_class_prob/coverage_80/dist
    },
    "evidence": {
        "feature_contribution_top3": [(feature_name, shap_value), ...],
        "rolling_mean_window20": float,
        "z_score": float,
        "trend_pattern": str,                # "consecutive_up" | "regression" | "stable"
        "anomaly_round_flag": bool,          # D-6 AE broadcast
    },
    "narrative_seed": str,                   # predictor가 생성하는 1문장 초안
}
```

#### U-4-4. 캐싱·재시도

- Gemma 4 호출 결과 LRU 캐시 (`functools.lru_cache(maxsize=128)`) — 동일 evidence dict 재호출 시 재사용
- 호출 실패 시 fallback: `narrative_seed` 그대로 반환 (graceful degradation)
- 호출 timeout: predictor당 1.5s, 17개 batch는 25s

#### U-4-5. 검증

- [ ] 17 predictor evidence dict가 모두 표준 스키마 준수 (단위 테스트)
- [ ] Gemma 4 batch 호출 < 25s (S-1 추론 SLA 30s 내)
- [ ] narrative 출력이 50~120 글자 범위 내, 한국어 자연 문장
- [ ] LRU 캐시 적중 시 호출 시간 < 100ms
- [ ] Gemma 4 호출 실패 시 narrative_seed로 fallback 정상 동작

---

## 누적 진행 현황 (20/20)

> **마스터 리스트 정정**: 본 문서 7번 줄의 "21지표"는 사용자 누락 지표(제곱수·동형수) 추가 후 실질적으로 **20지표**. 회귀(지표 20)는 별도 plan으로 분리되며 본 문서에서는 Tier 1만 인덱스. 21번 "(예비)" 행은 빈 슬롯이 아닌 *향후 사용자 결정 시 추가*용 placeholder로 남김.

| # | 지표 | Phase | 출력 형식 | 상태 |
|---|---|---|---|---|
| 1 | 총합 | 4 | 신뢰구간 [lo,hi] | ✅ |
| 2 | 끝수합+분포 | 2 | 스칼라+10D | ✅ |
| 3 | AC값 | 3 | 신뢰구간 | ✅ |
| 4 | 고저 | 1 | 7-pair 조인트 | ✅ |
| 5 | 홀짝 | 1 | 7-pair 조인트 | ✅ |
| 6 | 이월수 | 1 | 7-class (보너스 변형 2) | ✅ |
| 7 | 연번 | 1 | 6-class | ✅ |
| 8 | 이웃수 | 1 | 7-class | ✅ |
| 9 | 끝수 0~9 개별 | 1 | 10×7-class | ✅ |
| 10 | 번호대 5개 | 1 | 5×7-class | ✅ |
| 11 | 9궁 | 1 | 9×7-class | ✅ |
| 12 | 로또용지 14개 | 1 | 14×7-class | ✅ |
| 13 | 배수 6개 (배수외 포함) | 1 | 6×7-class | ✅ |
| 14 | 소수+합성수+1 | 1 | 3×7-class + 비율 | ✅ |
| 15 | 삼각수 | 1 | 7-class | ✅ |
| 16 | 제곱수 | 1 | 7-class | ✅ |
| 17 | 동형수 | 1 | 7-class | ✅ |
| 18 | 미출현그룹 | 1 | 4×7-class (광역만) | ✅ |
| 19 | 핫콜드 12개 | 1 | 12×7-class | ✅ |
| 20 | 회귀(2~200) | 1 | **별도 plan으로 분리** | ⏸ Deferred |
| 21 | (예비) | — | — | — |

### 글로벌 인프라
- ✅ 7개 모델 역할 분담 원칙
- ✅ 기존 GNN 출력 집계 전략
- ✅ Markov 카테고리화 원칙
- ✅ Autoencoder 게이트
- ✅ Cross-feedback 매트릭스 (Phase 1~4 위계)
- ✅ Gemma 4 evidence dict + narrative_seed
- ✅ "M중 N" 정규화 출력 형식 (모든 카테고리 지표)
- ✅ IndependentCountPredictor 강화 패턴 (Category GNN 포함)
- ✅ G-1 ~ G-6 글로벌 파이프라인 수정 사항 명시
- ✅ **G-7 GNN 자체 재설계** (BCE 보조 손실, Top-K=15, config 통합)
- ✅ **M-1 MetaLearner 재구축** (task 매트릭스 학습 가능화, Markov 통합, alpha bounded optimization)
- ✅ **T-1 학습 순서 / 파이프라인 오케스트레이션** (DAG 6 stage, 캐시 분리, 메인 INPUT_DIM 동결)
- ✅ **S-1 SLA / 추론 wall-time / 메모리** (24h/30s/12GB 한도, 폭증 대응 3 tier)
- ✅ **U-1 단위 테스트 명세** (pytest, 21회차 골든 데이터, CI 통합, cov 70%)
- ✅ **U-2 16개 Predictor 하이퍼파라미터** (epochs=80, batch=32, LR=0.0008 공통 정책)
- ✅ **U-3 Markov bucket 자동 도출** (학습 fold 분위수 기반 calibration)
- ✅ **U-4 Gemma 4 narrative 인터페이스** (batch 호출, LRU 캐시, 표준 evidence 스키마)

### 핵심 신규/수정 파일 요약

**신규 15** (G-7·M-1·T-1·S-1·U-1~U-4 통합):

*Predictor / 모델 (6)*
- `langchain-backend/models/sum_predictor.py`, `models/endings_predictor.py`, `models/ac_predictor.py`
- `langchain-backend/models/categorical_count_predictor.py` (고저/홀짝/이월/이웃/연번)
- `langchain-backend/models/independent_count_predictor.py` (강화 패턴, 11지표 공유)
- `langchain-backend/models/markov_model.py` (M-1: 7번째 base 모델 인터페이스 통합)

*Feature (2)*
- `langchain-backend/features/scalar_features.py` (sum/ac/endings_sum 공통 빌더)
- `langchain-backend/features/categorical_features.py` (고저/홀짝/이월/이웃/연번 공통)

*Validation (3 — U-3 추가)*
- `langchain-backend/validation/timeseries_cv.py`, `validation/baselines.py`
- `langchain-backend/validation/bucket_calibration.py` (U-3: Markov bucket 자동 도출)

*인프라 — T-1 (2)*
- `langchain-backend/pipeline/training_orchestrator.py` (DAG 6 stage 실행)
- `langchain-backend/models/posthoc_gate.py` (메인 1~45 ↔ Phase 출력 결합 — INPUT_DIM 동결)

*인프라 — S-1 (2)*
- `langchain-backend/pipeline/sla_monitor.py` (SLAMonitor 컨텍스트 매니저)
- `langchain-backend/dashboards/sla_report.py` (회차별 SLA 추세)

*인프라 — U-4 (1)*
- `langchain-backend/chains/narrative_chain.py` (Gemma 4 호출 batch + LRU 캐시)

*테스트 — U-1 (다수, 디렉터리 단위)*
- `tests/unit/` (8 파일: filter_stats, predictors_scalar/categorical/independent, gnn_aggregation, meta_learner, ae_gate_flag, orchestrator_dag)
- `tests/integration/` (3 파일: walk_forward_5fold, phase_cache_consistency, sla_monitor)
- `tests/fixtures/golden_draws_round100_to_120.json` (21회차 골든 데이터)
- `.github/workflows/test.yml` (CI 통합)

**수정 핵심**:
- `services/filter_stats.py` (대폭 — 모든 필터 메서드 강화 + 신규 메서드 6개+)
- `pipeline/weekly_pipeline_v2.py::_run_analysis()` (orchestrator 호출 + SLAMonitor 래핑)
- `models/lstm/transformer/cnn/xgboost/gnn_model.py` (G-1~G-7 적용 — Focal Loss·정규화·GNN 재설계)
- `models/ensemble.py::train_all` (분해 후 orchestrator로 이전, task 매트릭스 외부화, AE 게이트 일반화)
- `models/meta_learner.py` (`fit_alpha()` bounded optimization, 21 predictor 로그 분리)
- `config.py` (RANDOM_SEED, GNN_*, TASK_PREDICTOR_MAP, META_ALPHA_DEFAULT, AE_GATE_PERCENTILE, SLA_*, 모든 새 카테고리 정의)
- `Dockerfile` (`psutil` 추가, GPU 빌드 옵션 주석)
- `scripts/auto_train.py`, `scripts/train_models.py` (orchestrator 호출, force_retrain stage별)

**삭제 1**:
- `pipeline/weekly_pipeline.py` (v1 레거시 — T-1 결정 C)

---

## Verification (전체 완료 후)

- [ ] 각 재설계된 지표가 학습 시 베이스라인(rolling mean/uniform 1/45)을 이기는지 검증
- [ ] 단위 테스트: 지표 계산 함수가 알려진 값(예: 1회차) 정답과 일치
- [ ] walk-forward 시뮬레이션 (마지막 50회차) 정확도 보고
- [ ] 모델별 SHAP/Attention 시각화 → 사람이 봤을 때 합리적인 근거 제시 여부