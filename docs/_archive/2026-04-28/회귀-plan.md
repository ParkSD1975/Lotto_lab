# 회귀(2~200) 지표 재설계 — 별도 plan

## Context

본 plan은 어제 수립한 21지표 재설계 plan(`kind-hugging-matsumoto.md`)에서 **별도 분리 결정**된 회귀(2~200) 지표를 본격 설계한다. 어제 plan과 같은 인프라/패턴을 활용하되, 회귀의 동적·다차원 특성으로 인해 단일 IndependentCountPredictor로 다룰 수 없어 **4 Tier 시스템**으로 분해한다.

회귀는 사용자 19지표 리스트의 마지막 항목이지만 **분석해야 할 차원이 가장 많음** (사용자 표현: "분석해야할 게 너무나도 많다"). Tier 1만 다른 지표와 비슷하고, Tier 2~4는 회귀 고유 분석.

---

## 사용자 7가지 분석 항목 (요구사항 매핑)

| # | 분석 항목 | 담당 Tier |
|---|---|---|
| A | 특정 회귀의 특정 번호 연속 출현 ("10회귀에 2번이 몇 번 연속") | Tier 1 + Tier 2 |
| B | 각 번호의 전체 회귀 중첩 (1~45번이 어느 N들에 출현) | Tier 2 |
| C | 회귀별 연속 출현/미출현 길이 | Tier 2 |
| D | 특정 회귀의 라인 패턴 ("1번/6번라인 연속 미출") | Tier 3-A |
| E | 번호대 + 회귀 결합 필터 — **자동 룰 트리거** | Tier 3-C |
| ★ | **4연번 자동 제외 룰** (회귀 N 4연번 / 1회귀 4연번) | Tier 3-D (사용자 정정 추가) |
| ★ | **데드 회귀×라인 이월률 자동 제외** (≥ 2개 회귀 데드 → 제외) | Tier 3-E (사용자 정정 추가) |
| F | 라인 끝수의 다음 회차 출현 가능성 | Tier 3-B |
| G | 메타: 자주 보이는 패턴이 있는 회귀 식별 | Tier 4 |

### 항목 E 사용자 명확화 (2026-04-28)

> "2회귀에서 대상번호가 11, 14, 19가 같은 10번대에서 3개가 나온다면 이 경우 0-1 필터를 적용할 것을 참조하라"

**해석**: 회귀 N=2 시점에서 같은 번호대에 멤버 3개 이상 군집 발견 시, 자동으로 *"다른 번호대는 0~1개"* 필터 룰을 다음 회차 분석에 트리거. 회귀 분석이 단순 카운트가 아니라 **조합 필터 룰을 도출하는 분석 엔진**.

---

## 4 Tier 시스템 개관

```
Tier 1: Per-N 회귀 카운트 (가변 199 카테고리, 매 회차 활성 16~30개)
   ↓
Tier 2: 번호별 회귀 압축 변수 (1~45 각 번호 × 7~10 압축 변수)
   ↓
Tier 3: 결합 필터 (라인×N, 끝수×N, 번호대×N) + 자동 룰 트리거
   ↓
Tier 4: 메타 분석 (자주 보이는 패턴 N 발견)
```

각 Tier가 다음 Tier에 입력 제공. Phase 위계상 회귀 전체는 Phase 1 (다른 지표 입력 의존 없음).

---

## Tier 1: DynamicIndependentCountPredictor

### 1-1. 정의

각 회차 t에서 활성 N값 = `{N : 풀(N회 전 출현) 멤버 ≥ 1개}`.

예시:
- 회차 t: 활성 N = {0, 1, 2, 3, 5, 7, 8, 10, 12, 15, 18, 22, 30} → 13개
- 회차 t+1: 활성 N = {0, 1, 2, 4, 6, 9, 11, 14, 17, 23, 27, 31, 35, 50} → 14개

→ **카테고리 수가 매 회차 변동**. 어제 IndependentCountPredictor의 동적 확장 버전 필요.

### 1-2. 아키텍처

```python
class DynamicIndependentCountPredictor:
    """
    가변 카테고리 IndependentCountPredictor.
    
    Shared Backbone (모든 활성 N 공유):
      ├─ XGBoost (활성 N마다 multi:softprob 7-class 헤드 생성)
      ├─ Markov 7-state per active N (활성 N마다 전이행렬)
      ├─ 기존 45-노드 GNN 집계 (N별 멤버 prob 합 → 7-class 분포)
      └─ 경량 LSTM (활성 N별 카운트 시퀀스, multi-task)
    
    Per-N Heads (가변):
      └─ 각 활성 N: Softmax 7-class P(count=0..6)
    
    Sparsity 처리:
      - 학습 데이터에서 N별 등장 sample 카운트
      - sample ≥ 50인 N만 신뢰 헤드로 학습
      - 그 외 N은 빈도 베이스라인(룰베이스 P 분포)으로 fallback
    
    "M중 N" 정규화 (어제 결정 적용):
      - 각 N별 current_pool_size_N (1~여러 개)
      - absolute count, expected_ratio = E/M, narrative
    """
```

### 1-3. Feature

**공통**:
- `previous_round_active_N_count_dist[max_active_N]`
- `gnn_top10_N_dist[active_N]`
- `current_active_N_set_size` — 매 회차 활성 N 개수 (16~30 변동)

**각 활성 N별**:
- `N_lag_1~5` (직전 5회차 N 출현 개수 시계열, 활성이 아닐 수 있음 — 0 패딩)
- `N_rolling_mean/std (5/10/20)`
- `N_dormancy` (이 N이 비활성이었던 연속 회차)
- `N_pool_size` (현재 풀 크기)
- `N_avg_value_in_pool` (풀 멤버 평균값, sum 추정 보조)

### 1-4. 손실

```python
total_loss = Σ_N CE(head_N, label_N) for each active N
           + 0.2 × MSE(Σ_N expected_count_N, 6)  # 자동 일관성
           + 0.1 × MSE(corr_learned, corr_data)  # N 간 상관
```

`Σ_N expected = 6` 자동 — 6번호가 정확히 활성 N 카테고리에 분배.

### 1-5. Sample sparsity 처리

199개 N 중 일부는 학습 데이터 적음:
- N=2~30: 일반적으로 충분 (빈번 활성)
- N=50+: 매우 드뭄 (해당 N 활성 회차 ≤10회 가능)
- 신뢰 학습 가능 N: 약 30~80개 추정

**Fallback 룰**:
- 신뢰 헤드: ML 분류기 P(count=0..6)
- Sparse N: 빈도 베이스라인 (학습 데이터에서 N별 평균 출현 개수 prior)
- Mixed: 신뢰도 점수에 따라 가중

### 1-6. 출력 (Tier 2~4 입력)

```python
{
  "active_N_set": [0, 1, 2, 3, 5, 8, 12, 18, 30, ...],
  "per_N_dist": {N: [P(0), ..., P(6)] for N in active},
  "per_N_expected": {N: E for N in active},
  "per_N_pool_size": {N: M for N in active},
  "per_N_narrative": {N: "N=8 풀 3개 중 1개 출현 가능성 42%"}
}
```

---

## Tier 2: 번호별 회귀 압축 변수 (메인 1~45 feature)

### 2-1. 압축 동기

각 번호 × 199 N = 8,955 binary 변수 → 메인 모델 학습 비효율. 7~10 변수로 의미 보존 압축.

### 2-2. 압축 변수 정의 (각 번호 1~45별)

| 변수 | 정의 |
|---|---|
| `regression_appearance_count` | 199 N 중 등장 누적 개수 (역사 전체) |
| `regression_avg_gap` | 등장한 N들의 평균값 (높을수록 장기 회귀 우세) |
| `regression_max_consecutive` | 어느 N에서 가장 길게 연속 활성 |
| `regression_top3_active_N` | 가장 활성인 회귀 3개 (예: [2, 8, 22]) |
| `regression_low_N_density` | N≤10 활성도 (단기 회귀 빈도) |
| `regression_mid_N_density` | N=11~50 (중기) |
| `regression_high_N_density` | N≥51 (장기) |
| `regression_sequence_dormancy` | 가장 최근 회귀 활성 후 경과 회차 |

→ 8 변수 × 45 번호 = 360 dim → 메인 모델 입력 추가

### 2-3. 사용자 항목 A·B·C 매핑

- A ("10회귀에 2번이 몇 번 연속"): `regression_max_consecutive` + Tier 1 N=10 head
- B ("각 번호의 전체 회귀 중첩"): `regression_appearance_count` + `regression_top3_active_N`
- C ("회귀별 연속 출현/미출현 길이"): `regression_max_consecutive` + Tier 1 dormancy

### 2-4. 정규화

| 변수 | Scaler |
|---|---|
| appearance_count, avg_gap | StandardScaler |
| max_consecutive | log1p + StandardScaler |
| top3_active_N | One-hot 또는 임베딩 (3 정수) |
| low/mid/high_N_density | 그대로 (0~1 비율) |
| sequence_dormancy | log1p + StandardScaler |

---

## Tier 3: 결합 필터 (사용자 항목 D, E, F)

### 3-A. 라인 × N (항목 D)

**매트릭스**: `line_x_N[7×|active_N|]` (가로 7행, 세로 7열은 별도)
- 각 셀 (k, N): "라인 k에서 N회귀 멤버 중 다음 회차 출현 확률"

**감지 패턴**:
- 라인 k에서 N=5,10,15 모두 미출 연속 → "**라인 k 미출 라인**" 감지
- 라인 k에서 특정 N 회귀에서 반복 출현 → "라인 k가 N회귀 강세" 감지

**출력**:
```python
{
  "horizontal_lines": [
    {"line": 1, "consecutive_miss": 5, "active_N_pattern": "5,10,15 모두 미출",
     "narrative": "1번 가로라인 5회 연속 미출, 단기·중기 회귀 모두 미활성"},
    ...
  ],
  "vertical_lines": [...]
}
```

### 3-B. 끝수 × N (항목 F)

**매트릭스**: `ending_x_N[10×|active_N|]`
- 각 셀 (k, N): 끝수 k가 N회귀 멤버 중 다음 회차 출현 확률

**감지 패턴**:
- "끝수 8이 N=12 회귀에서 다음 회차 출현 가능성 ↑"
- "특정 라인의 끝수가 다음 회차 출현 가능성 ↑" — 라인×끝수×N 3D 결합

**출력**:
```python
{
  "ending_x_regression": [
    {"ending": 8, "regression_N": 12, "next_appearance_prob": 0.42,
     "linked_lines": ["가로3", "세로7"],
     "narrative": "끝수 8 (12회귀) 다음 출현 가능성 42% — 가로3, 세로7 라인 연관"}
  ]
}
```

### 3-C. 번호대 × N + 자동 필터 룰 트리거 (항목 E 핵심)

**매트릭스**: `decade_x_N[5×|active_N|]`
- 각 셀 (k, N): 번호대 k에서 N회귀 멤버 중 회차 t에 출현한 개수

**자동 룰 트리거 (사용자 항목 E)**:

```python
def detect_decade_cluster_and_apply_filter(decade_x_N_matrix, threshold=3):
    """
    번호대 × N 매트릭스에서 군집 감지 → 자동 필터 룰 생성
    
    사용자 룰 (2026-04-28 명확화):
    "2회귀에서 같은 번호대 3개 이상 군집 → 다른 번호대 0~1개 필터 자동 적용"
    """
    triggered_filters = []
    
    for k in range(5):  # 5 번호대
        for N in active_N_set:
            cluster_count = decade_x_N_matrix[k][N]
            
            if cluster_count >= threshold:
                # 같은 번호대 3+ 군집 → 다른 번호대 제약 룰 트리거
                rule = {
                    "trigger": f"번호대 {k}에 N={N} 회귀 멤버 {cluster_count}개 군집",
                    "applied_filter": {
                        f"decade_{j}_max_count": 1 for j in range(5) if j != k
                    },
                    "scope": f"다음 회차 분석",
                    "evidence": [...],
                    "narrative": f"번호대 {k}에 N={N} 회귀 멤버 군집 → 다른 번호대 0~1개로 제약"
                }
                triggered_filters.append(rule)
    
    return triggered_filters
```

**출력 (사용자 명확화 직접 매핑)**:
```python
{
  "decade_clusters": [
    {"decade": 1, "regression_N": 2, "cluster_members": [11, 14, 19], 
     "cluster_count": 3,
     "triggered_rule": "다른 번호대 0~1개 필터",
     "narrative": "10번대에 2회귀 멤버 11/14/19 군집 → 단번대·20대·30대·40대 각 0~1개 제약"}
  ],
  "auto_applied_filters": [
    {"category": "decade_0_max_count", "value": 1, "source": "decade_1_cluster_N2"},
    ...
  ]
}
```

이 자동 룰들은 **메인 1~45 모델 출력의 후처리 mask로 적용** — `posthoc_gate.py` 또는 후처리 단계에서.

### 3-D. 4연번 자동 제외 룰 (★사용자 정정 추가, 2026-04-28)

NumberRecommender의 제외수 10 결정에 강제 적용:

**룰 1: 회귀 N (2~200)에서 4연번 이상**
```python
for N in active_regression_N:
    for n in 1..45:
        if regression_data[n][N].max_consecutive >= 4:
            auto_exclude.add(n, reason=f'regression_consecutive_N{N}')
```
근거: 회귀 패턴 한계 도달 → 다음 회차 미출현 시그널.

**룰 2: 1회귀에서 4연번 (직전 4회차 연속 출현)**
```python
for n in 1..45:
    if consecutive_recent_appearance(n, lookback=4) >= 4:
        auto_exclude.add(n, reason='recent_4_consecutive')
```
근거: 핫스트릭 한계 → 평균회귀 시그널.

**narrative 예시**:
- "42번: 12회귀에서 4연번 활성 → 회귀 패턴 한계 → 다음 회차 미출현 가능성 높음"
- "23번: 직전 4회차 연속 출현 → 핫스트릭 한계, 평균회귀 시그널"

### 3-E. 데드 회귀×라인 이월률 자동 제외 룰 (★사용자 정정 추가, 2026-04-28)

**라인 정의** (옵션 A 확정): 정렬된 당첨번호+보너스 위치
- 1라인 = 가장 작은 번호 (1처)
- 2라인 = 2처
- ...
- 6라인 = 6처 (가장 큰 번호)
- **7라인 = 보너스볼**

**사용자 명세 예시** (현재 = 2121회차):
- 2회귀 = 2119회차 [1,2,3,4,5,6,7] (정렬+보너스)
  - 3라인 위치 번호 = 3
  - (2회귀, 3라인) 학습 데이터 이월률 0 → 3번 데드 카운트 +1
- 100회귀 = 2021회차 [2,3,4,5,6,7,8]
  - 2라인 위치 번호 = 3
  - (100회귀, 2라인) 학습 데이터 이월률 0 → 3번 데드 카운트 +1
- **3번 데드 카운트 = 2 ≥ 2 → 자동 제외**

**알고리즘**:
```python
def detect_dead_carryover_lines(target_round, history, active_N_list):
    """
    각 번호 X에 대해:
    1. 각 활성 N회귀의 N회 전 회차에서 X가 있던 라인 k 식별
    2. 학습 데이터 전체에서 (N, k) 조합 이월률 계산
       = t회차 라인 k 번호가 t+N회차에 출현하는 비율
    3. 이월률 = 0 (한 번도 이월 안 됨) → X 데드 카운트 +1
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

### 3-F. 모델 적용

Tier 3는 ML 학습보다 **룰 기반 + 통계 분석** 위주:
- 매트릭스 계산: 매 회차 결정적
- 패턴 감지: 룰 베이스 임계값
- 자동 필터 룰: 결정적 매핑

ML 학습 부분:
- "어떤 임계값이 다음 회차 적중에 효과적인가" — 임계값 학습 (예: cluster ≥3 vs ≥4)
- 학습 데이터에서 fold별 임계값 calibration

---

## Tier 4: 메타 분석 (항목 G — 자주 보이는 패턴 N)

### 4-1. 분석 대상

학습 데이터(약 1100여 회차)에서:
- 각 N에 대해 다음 패턴 빈도 측정:
  - "N회귀 후 sum 변화 패턴" (예: N=8 회귀 활성 후 sum +5~10 평균)
  - "N회귀 후 끝수 패턴 변화" (예: N=12 후 큰 끝수 비율 ↑)
  - "N회귀 후 번호대 군집 발생률"
  - "N회귀 후 라인 변화 패턴"

### 4-2. 출력

```python
{
  "frequent_patterns_by_N": {
    "N=2": [
      {"pattern": "10번대 군집3 → 다음 회차 4:2 분포 우세", 
       "frequency": 0.34, "support": 47},
      {"pattern": "끝수 8 출현 → 다음 회차 sum +5~10", 
       "frequency": 0.22, "support": 31},
    ],
    "N=8": [
      {"pattern": "8회귀 미출 후 출현 시 80% 확률 sum 130~150", 
       "frequency": 0.41, "support": 28},
    ],
    "N=22": [
      {"pattern": "22회귀 활성 후 그 번호 다음 회차 prob 60% 이상", 
       "frequency": 0.55, "support": 12},
    ],
    ...
  }
}
```

### 4-3. Gemma 4 narrative 입력

Tier 4 출력은 LLM이 받아 자연어 설명 생성:

```
"이번 회차 활성 회귀는 N=2, 8, 12, 22.
 N=2 회귀에 10번대 군집 3개 발견 → 다른 번호대 0~1개 필터 트리거.
 N=8 회귀 패턴: 미출 후 출현 시 80% 확률 sum 130~150.
 종합: sum 130~150, 10번대 3개, 다른 번호대 각 0~1개 제약 추천."
```

### 4-4. 구현

```python
class RegressionMetaAnalyzer:
    """
    학습 데이터에서 N별 자주 보이는 패턴 자동 발견.
    
    1. 학습 데이터 walk-forward 시뮬레이션
    2. 각 N에서 N회귀 활성 회차들의 다음 회차 분석
    3. 빈도 ≥ 0.20 + support ≥ 10 패턴만 보존
    4. Gemma 4 narrative 입력으로 출력
    """
```

### 4-5. 정기 갱신

- 매주 새 회차 추가 시 메타 분석 재실행
- `saved_models/regression_meta_patterns.json` 캐시 갱신

---

## Cross-feedback 매트릭스 (어제 plan에 통합)

회귀(지표 20)는 Phase 1 (받는 입력 없음).

**보내는 출력**:
- Tier 1: per_N_dist, per_N_expected (16~30 활성 N)
- Tier 2: 번호별 8 압축 변수 × 45 = 360 dim
- Tier 3: 자동 필터 룰 (decade/line/ending × N)
- Tier 4: 메타 패턴 narrative

**도달 경로**:
- ✅ 메인 1~45 모델: Tier 2 압축 변수 + Tier 3 mask (강 시그널)
- ✅ 미출현그룹(지표 18): Tier 1 활성 N 정보가 동적 세부 분석 보강
- ✅ 핫콜드(지표 19): N과 hot/cold 상관 활용 (Hot ↔ N≤5 / Cold ↔ N≥16)
- ⚠️ 다른 지표: 매트릭스 미포함 (직접 sum/AC 영향 약)

---

## "M중 N" 정규화 출력 (어제 결정 적용)

회귀의 모든 Tier 출력에도 어제 결정한 "M중 N" 형식 적용:

**Tier 1**:
```
"N=8 회귀 풀 3개 중 1개 출현 가능성 42%"
"N=22 회귀 풀 1개 중 0개 가능성 65%"
```

**Tier 3-C**:
```
"10번대 풀 9개 중 N=2 멤버 3개 군집 → 0-1 필터 트리거"
```

**Tier 4**:
```
"N=8 회귀 패턴: 풀 평균 3개 중 다음 출현 1개 (P=80%, support=28회)"
```

---

## 수정/신규 파일

### 신규 5개

1. `langchain-backend/models/regression_predictor.py` — DynamicIndependentCountPredictor (Tier 1)
2. `langchain-backend/features/regression_features.py` — Tier 2 압축 변수 빌더 + Tier 3 매트릭스 계산
3. `langchain-backend/services/regression_filter_rules.py` — Tier 3 자동 필터 룰 트리거 (`detect_decade_cluster_and_apply_filter` 등)
4. `langchain-backend/services/regression_meta_analyzer.py` — Tier 4 패턴 빈도 분석
5. `langchain-backend/services/filter_stats.py::_regression_distribution()` — 신규 메서드 (Tier 1+3 출력 통합)

### 수정 4개

6. `pipeline/weekly_pipeline_v2.py::_run_analysis()` — Phase 1 호출 (regression_predictor + meta_analyzer)
7. `models/lstm/transformer/xgboost_model.py` — Tier 2 압축 변수 8×45=360 dim 추가
8. `services/filter_stats.py::compute_all()` — `_regression_distribution()` 등록
9. `config.py` — 신규 설정:
   - `REGRESSION_N_RANGE = (2, 200)`
   - `REGRESSION_SAMPLE_THRESHOLD = 50` (신뢰 학습 가능 N 임계값)
   - `REGRESSION_DECADE_CLUSTER_THRESHOLD = 3` (Tier 3 룰 트리거)
   - `REGRESSION_META_FREQUENCY_MIN = 0.20`
   - `REGRESSION_META_SUPPORT_MIN = 10`

### 신규 캐시 파일

10. `saved_models/regression_meta_patterns.json` — Tier 4 메타 분석 결과 (주간 갱신)

---

## 검증

### Tier 1
- [ ] 활성 N 동적 식별 정확성 (매 회차 16~30 활성 N 체크)
- [ ] 신뢰 N 분류기가 빈도 베이스라인 CE 이김
- [ ] Sparse N (sample <50) 자동 fallback 동작
- [ ] Σ_N expected ≈ 6 자동 일관성 (오차 <0.5)

### Tier 2
- [ ] 압축 8 변수 × 45 = 360 dim이 메인 1~45 모델 SHAP에 의미 있는 기여
- [ ] regression_top3_active_N이 실제 학습 데이터의 자주 활성 N과 일치
- [ ] regression_max_consecutive 효과 — 길수록 다음 출현 확률 ↑ 패턴

### Tier 3
- [ ] **사용자 항목 E 직접 검증**: "11/14/19 → 0-1 필터" 자동 트리거 정확
- [ ] 라인 미출 라인 감지 → 도메인 직관 부합
- [ ] 끝수×N 매트릭스 패턴 감지 정확

### Tier 4
- [ ] frequency ≥0.20 + support ≥10 패턴만 보존
- [ ] Gemma 4 narrative가 Tier 4 출력을 자연어로 합성
- [ ] 주간 갱신 정상 동작 (`regression_meta_patterns.json` 갱신)

### 통합
- [ ] 회귀 plan과 어제 19지표 plan 함께 실행 시 충돌 없음
- [ ] 미출현그룹·핫콜드와의 cross-feedback 합리성 (Hot ↔ N≤5 등)
- [ ] 메인 1~45 모델 입력에 Tier 2 (360 dim) + Tier 3 mask 통합 시 메모리/학습 시간 측정 (사용자 자원 제약 필요시 조정)

---

## 미해결 사항

- 사용자 docs/deeplearning_renewal.md의 T-1 결정 A (메인모델 INPUT_DIM 65 동결 + posthoc_gate)와 본 plan의 Tier 2 (메인 모델에 360 dim 추가) 충돌 가능성. 사용자가 T-1 A 의미를 모른다고 표현 → 추후 명확화 시점에 Tier 2 통합 방식 재조정 (현재 plan은 dim 확장 가정).

---

## 진행 우선순위 (구현 시)

1. **Tier 1** (DynamicIndependentCountPredictor) — 어제 인프라(`independent_count_predictor.py` 패턴) 확장
2. **Tier 2** (압축 변수 빌더) — 메인 모델 feature 추가
3. **Tier 3-C** (사용자 항목 E 자동 필터 룰) — 가장 명확한 사용자 요구
4. **Tier 3-A, 3-B** (라인×N, 끝수×N) — 보강
5. **Tier 4** (메타 분석) — 마무리, Gemma 4 통합

각 Tier 완료 시 검증 항목 통과 후 다음 단계.
