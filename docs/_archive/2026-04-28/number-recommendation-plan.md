# 번호 추천/제외 엔진 재설계 — plan

## Context

### 문제 정의
현재 Lotto_lab의 개별 번호 분석 결과:
- **추천수 5개**: 평균 hit 1개 (목표: 2-3개)
- **제외수 10개**: 평균 hit 1-2개 (목표: 0-1개)

신뢰도가 우연 수준에 가까워 사용자 가치 부족. 6×5/45 ≈ 0.67 (랜덤 추천 hit 기댓값) 대비 의미 있는 신호 추출 실패.

### 진단 (현재 `models/ensemble.py` 분석)

**`predict_top5()`**:
- `final_probs` 상위 10 후보 → `consensus_count >= 4` 필터 → CI lower bound 정렬 → top 5
- ✅ 합의 카운트는 이미 존재
- ❌ 모델별 개별 ranking 추출 함수 없음 (`final_probs`만 사용)
- ❌ 21지표 필터 통과도 미반영
- ❌ 핫콜드·미출현·회귀 등 번호별 동적 상태 미활용
- ❌ 자연어 설명 부재

**`predict_exclusion_with_veto()`**:
- 낮은 prob 정렬 → GNN strong co-occurrence veto → 10개
- ❌ 다중 조건 부재 (점수 ↓ + 합의 ↓ + 필터 위반)

### 목표
4 Pillar 점수 시스템으로 추천/제외 신뢰도 향상:
- 추천 hit 1 → 2~3
- 제외 hit 1-2 → 0-1
- 사용자가 이해하는 자연어 설명 (수치 X)
- 모델별 순위 5분할 자유 슬라이스 + 합집합·공집합 분석

---

## 4 Pillar Number Scoring System

각 번호 1~45에 대해 4 Pillar 점수 계산 → 메타러너 Ridge가 가중치 학습 → 최종 score.

### Pillar 1: Ensemble Probability (기존 활용)
- 기존 7모델 가중평균 + AE 페널티 + 메타러너 → `final_probs[n]`
- 글로벌 G-1~G-6 수정(Focal Loss, Bidirectional, 정규화 등) 후 신뢰도 회복 가정

### Pillar 2: Filter Compliance — 신규
21지표 필터에 그 번호가 부합하는 정도:
```python
filter_compliance(n) = Σ_i (
    weight_i × compliance_i(n, predicted_filter_i)
)
```

각 21지표 필터별 통과 함수:
- 총합 필터: n이 예측된 sum 범위 내 평균값에서 가까운가
- 고저 필터: n이 예측된 고저 비율 카테고리에 속한가 (n≤22 또는 n>22)
- 끝수 필터: n의 끝수가 활성 끝수에 포함되는가
- 번호대 필터: n의 번호대가 예측된 강세 번호대인가
- 9궁/로또용지/배수/소수합성수/...

→ 각 필터 통과도 0~1 스칼라 → 가중 합산.

### Pillar 3: Individual State — 신규
번호별 동적 상태:
```python
individual_state(n) = w_a × hotcold_signal(n)
                    + w_b × dormancy_signal(n)
                    + w_c × regression_signal(n)
                    + w_d × carryover_signal(n)
                    + w_e × neighbor_signal(n)
```

각 신호 의미:
- `hotcold_signal`: 핫콜드 12 카테고리 중 n의 위치 (Hot일수록 ↑)
- `dormancy_signal`: 미출현 회차 + 회귀 활성도 결합
- `regression_signal`: Tier 2 압축 변수 8개 (회귀 plan 참조)
- `carryover_signal`: 직전 회차 출현 시 약간 ↑ (이월 후보)
- `neighbor_signal`: 이웃수 풀 멤버 시 ↑

### Pillar 4: Model Consensus — 신규 (가장 핵심)

**현재 `consensus_count`만 있음** → 4 메트릭으로 강화.

각 번호 n에 대해 7모델 순위 벡터:
```python
ranks(n) = [rank_lstm(n), rank_cnn(n), rank_gnn(n), rank_transformer(n),
            rank_xgboost(n), rank_markov(n), rank_ae(n)]
```

**4 메트릭**:
| 메트릭 | 정의 | 의미 |
|---|---|---|
| `mean_rank(n)` | 7모델 순위 평균 | 작을수록 추천 ↑ |
| `std_rank(n)` | 7모델 순위 표준편차 | **작을수록 합의 강함** |
| `top10_count(n)` | rank ≤ 10인 모델 수 | 5+이면 강한 추천 합의 |
| `bottom15_count(n)` | rank ≥ 31인 모델 수 | 5+이면 강한 제외 합의 |

**Consensus Score**:
```python
consensus_score(n) = -mean_rank(n)
                   - 0.5 × std_rank(n)
                   + 2.0 × (top10_count(n) >= 5)    # 강한 추천 보너스
                   - 2.0 × (bottom15_count(n) >= 5) # 강한 제외 페널티
```

→ **분산이 큰 번호는 자동 감점** (노이즈 모델 영향 제거).

### 메타러너 4 Pillar 가중치 학습

```python
final_score(n) = MetaLearner.predict([
    pillar_1_ensemble_prob(n),
    pillar_2_filter_compliance(n),
    pillar_3_individual_state(n),
    pillar_4_consensus_score(n),
])
```

**학습**:
- Ridge regression
- 입력: 4 Pillar 점수 (각 정규화)
- 라벨: 학습 데이터의 실제 출현 binary
- **최근 50회차 적중률 기반 동적 조정** (주 1회 재학습)
- 가중치 저장: `saved_models/pillar_meta_weights.json`

---

## 모델별 자유 슬라이스 + 합집합/공집합

### 5분할 default + 사용자 설정

기본 5분할:
```python
DEFAULT_SLICES = [
    (1, 9),    # Slice 1: 1~9위
    (10, 19),  # Slice 2: 10~19위
    (20, 29),  # Slice 3: 20~29위
    (30, 39),  # Slice 4: 30~39위
    (40, 45),  # Slice 5: 40~45위
]
```

사용자가 UI 또는 API에서 자유 변경 가능:
```python
# 사용자 정의 예시
custom_slices = [(1, 5), (6, 10), (11, 20), (21, 30), (31, 45)]
custom_slices = [(1, 10)]  # top 10만
custom_slices = [(1, 20), (30, 45)]  # 상위 20 + 하위 16 동시
```

### `ModelRankExtractor` 신규 컴포넌트

```python
class ModelRankExtractor:
    """7모델 각자의 1~45 순위 추출 + 슬라이스 + 합집합/공집합."""
    
    def extract_rankings(self, model_outputs):
        """
        model_outputs: {model_name: {n: prob for n in 1..45}}
        Returns: {model_name: [number_at_rank_1, ..., number_at_rank_45]}
        """
    
    def slice_by_ranges(self, ranges):
        """
        ranges: [(a, b), ...] (1-indexed inclusive)
        Returns: {model_name: {f"rank_{a}-{b}": [numbers]}}
        """
    
    def consensus_within_slice(self, slice_range):
        """
        slice_range: (a, b)
        Returns:
          - intersection: 모든 모델이 슬라이스에 포함한 번호
          - union: 어느 한 모델이라도 포함한 번호
          - per_number_count: {n: count of models having n in slice}
          - pairwise_overlap: 모델 쌍 [7×7] 매트릭스
        """
    
    def consensus_across_slices(self, slices):
        """
        slices: 사용자 5분할 (default 또는 custom)
        Returns: 슬라이스별 합집합/공집합/카운트 매트릭스
        """
```

### 합집합/공집합 통계 출력

```python
{
  "slice_1_top1-9": {
    "intersection": [3, 23, 38],          # 7모델 모두 1-9위에 둔 번호
    "union": [1, 3, 5, 7, 12, 23, 28, 31, 38, 42],  # 어느 한 모델이라도
    "per_number_count": {3: 7, 23: 7, 38: 7, 7: 5, 12: 4, ...},
    "consensus_strength": 0.71,           # intersection / union 비율
    "pairwise_overlap_matrix": [[7, 6, 5, ...], ...]
  },
  "slice_5_bottom40-45": {
    "intersection": [42, 44],              # 모든 모델이 하위에 둔 번호 (제외 강 합의)
    ...
  }
}
```

→ 사용자가 슬라이스별 모델 합의를 한눈에 비교.

---

## 추천/제외 결정 로직 (`NumberRecommender`)

### 추천 5개 — 다중 조건 통과

```python
def select_recommendations(scores, consensus, filter_compliance, n_top=5):
    """
    1. final_score 정렬 → 상위 15 후보
    2. consensus.top10_count >= 4 통과 (4모델 이상 top 10) — 강화 (현재 4 그대로 유지 가능)
    3. filter_compliance >= median + 0.1 통과 (필터 통과도 평균 이상)
    4. CI lower bound 정렬 → top n_top
    """
```

### 제외 10개 — 다중 조건 + 자동 제외 룰 (★사용자 정정 추가, 2026-04-28)

```python
def select_exclusions(scores, consensus, filter_compliance, regression_data, target_round, history, n_exc=10):
    """
    1. 자동 제외 룰 강제 적용 (force_exclude 우선)
       - 룰 1: 회귀 N(2~200)에서 4연번 이상
       - 룰 2: 1회귀에서 4연번 (직전 4회차 연속 출현)
       - 룰 3: 데드 회귀×라인 이월률 ≥ 2개 회귀 (라인=정렬 위치 1~6+보너스 7)
    
    2. 자동 룰 미충족 → 4 Pillar 다중 조건 통과 후보로 보완
       - final_score 하위 정렬 → 하위 15 후보
       - consensus.bottom15_count >= 4 (4모델 이상 31위 이하)
       - filter_compliance < median - 0.1 (필터 위반 강함)
       - GNN co-occurrence veto 적용
    
    3. 통합: 자동 룰(force_exclude) + Pillar 보완 = top n_exc
    """
    # 자동 룰 1·2·3 적용
    auto_excluded = []
    auto_excluded += apply_consecutive_4_rule(regression_data)         # 룰 1
    auto_excluded += apply_recent_4_consecutive_rule(history)           # 룰 2
    auto_excluded += detect_dead_carryover_lines(target_round, history, active_N)  # 룰 3
    
    # 4 Pillar 다중 조건 후보
    pillar_excluded = select_pillar_exclusion_candidates(scores, consensus, filter_compliance)
    
    # 통합: 자동 우선 + Pillar 보완
    return merge_with_priority(auto_excluded, pillar_excluded, n=n_exc)
```

**자동 제외 룰 3개 상세** (각 룰의 정확한 알고리즘은 회귀-plan.md Tier 3-D, 3-E 참조):

| 룰 | 조건 | 근거 |
|---|---|---|
| **룰 1: 회귀 4연번** | 어느 N회귀(2~200)에서든 4연번 이상 | 회귀 패턴 한계 → 미출현 |
| **룰 2: 1회귀 4연번** | 직전 4회차 연속 출현 | 핫스트릭 한계 → 평균회귀 |
| **룰 3: 데드 회귀×라인 이월률** | 2개 이상 (N, 라인 k) 조합에서 학습 데이터 이월률 0 | 강한 미출현 시그널 |

**라인 정의** (룰 3): 정렬된 당첨번호+보너스 7개 위치 (1라인=1처, 6라인=6처, 7라인=보너스볼)

**핵심 변경 vs 현재**:
- 추천: `final_probs` 단순 정렬 → **4 Pillar score** 정렬
- 추천 필터: `consensus_count >= 4` → **consensus + filter_compliance** 둘 다 통과
- 제외: 단순 `final_probs` 하위 → **다중 조건** (점수 ↓ + 합의 ↓ + 필터 위반)

---

## Gemma 4 Narrative — 3섹션 구조 (사용자 결정)

### 출력 형식

각 추천/제외 번호당 3섹션, 각 한 문장:
```python
{
  "number": 23,
  "type": "recommend",
  "narrative": {
    "signal": "7모델 중 5개가 상위 10위로 추천 합의.",
    "rationale": "최근 12회차 미출현 + 끝수 3 활성 + 평균회귀 시그널 + 20번대 군집 패턴 정합.",
    "conclusion": "다음 회차 출현 가능성 높음."
  }
}
```

### Gemma 4 입력 (자연어 합성용 evidence)

```python
gemma_input = {
  "number": 23,
  "type": "recommend",
  "pillar_1": {
    "ensemble_prob_rank": 4,
    "ci_lower": 0.62,
  },
  "pillar_2_filter_compliance": {
    "passed_filters": ["sum_range", "highlow_4_2", "endings_3", "decade_20s"],
    "failed_filters": ["odd_even_4_2"],
    "score": 0.78
  },
  "pillar_3_individual_state": {
    "hotcold": "Warm (W=10)",
    "dormancy": 12,
    "regression_top3_N": [2, 8, 22],
    "is_carryover_candidate": False
  },
  "pillar_4_consensus": {
    "top10_count": 5,
    "mean_rank": 6.3,
    "std_rank": 2.8,
    "agreement_strength": "강"
  }
}
```

→ Gemma 4가 위 evidence를 받아 3섹션 한국어 자연어 생성. **수치(7, 5, 12 등 도메인 자연수만 등장), SHAP value 같은 모델 내부 수치 X**.

### 시그널/근거/결론 작성 규칙 (Gemma 4 system prompt)

- **시그널** (한 문장): 가장 강한 단일 신호 — Pillar 4 합의 또는 Pillar 1 ensemble 중 더 강한 것
- **근거** (한 문장): Pillar 2·3에서 통과한 핵심 신호 3~4개 압축
- **결론** (한 문장): "출현/미출현 가능성 높음/낮음" + 핵심 사유 짧게

---

## 50회차 적중률 백테스트 + 메타러너 동적 조정

### 백테스트 메커니즘

```python
class RecommendationBacktest:
    """
    walk-forward로 최근 50회차에 대해 모델 추천/제외 시뮬레이션.
    
    각 회차에서:
    - 4 Pillar 점수 계산 (그 회차 시점의 데이터만 사용)
    - 추천 5 + 제외 10 선출
    - 실제 당첨번호와 비교 → hit count 집계
    
    Returns:
      - recommend_hit_history[50]
      - exclude_hit_history[50]
      - per_pillar_contribution: 어느 Pillar이 hit에 기여했는지
    """
```

### 메타러너 동적 조정

```python
# 매 주 (auto_train.py 호출 시):
1. 최근 50회차 백테스트 실행
2. 각 Pillar별 hit 기여도 측정 (SHAP-style attribution)
3. Pillar 가중치 업데이트:
   - hit 기여 큰 Pillar → 가중치 ↑
   - hit 기여 작거나 음의 기여 → ↓
4. saved_models/pillar_meta_weights.json 갱신
```

### 자동 안전장치

- 최근 50회차 추천 hit이 1.5 이하면 경고 로그 + Pillar 가중치 큰 변화 적용
- 제외 hit이 2 이상이면 제외 임계값 강화 (consensus.bottom15_count 4 → 5)

---

## 4 Pillar 정규화

| Pillar | Scaler |
|---|---|
| ensemble_prob (Pillar 1) | 그대로 (이미 0~1) |
| filter_compliance (Pillar 2) | 그대로 (0~1) |
| individual_state (Pillar 3) | StandardScaler (학습 fold에만 fit) |
| consensus_score (Pillar 4) | StandardScaler |

메타러너 입력 직전 정규화. fit은 train fold에만, test/inference는 transform.

---

## Cross-feedback (다른 plan과 통합)

### 받는 입력
- `kind-hugging-matsumoto.md` 19지표 모든 predictor 출력 → Pillar 2 filter_compliance 입력
- `회귀-plan.md` Tier 2 압축 변수 + Tier 3 자동 필터 룰 → Pillar 3 individual_state 입력
- 기존 `ensemble.predict()` 결과 → Pillar 1

### 보내는 출력
- 추천 5 + 제외 10 + Narrative
- consensus_matrix (5분할 합집합/공집합)
- 메타러너 학습된 4 Pillar 가중치

→ 본 plan은 다른 plan들의 **하류 통합 단계**. 19지표 + 회귀가 작동해야 본 plan도 정상 작동.

---

## 신규/수정 파일

### 신규 6개

1. `langchain-backend/models/number_scorer.py` — 4 Pillar 통합 + 메타러너 Ridge 학습
2. `langchain-backend/models/model_rank_extractor.py` — 7모델 ranking 추출 + 슬라이스 + 합집합/공집합
3. `langchain-backend/models/consensus_analyzer.py` — Pillar 4 4 메트릭 (mean/std/top10_count/bottom15_count)
4. `langchain-backend/models/number_recommender.py` — 추천/제외 결정 (다중 조건)
5. `langchain-backend/services/number_narrative.py` — Gemma 4 3섹션 narrative 생성기
6. `langchain-backend/validation/recommendation_backtest.py` — 50회차 적중률 평가 + Pillar 가중치 동적 조정

### 수정 5개

7. `langchain-backend/models/ensemble.py::predict_top5/predict_exclusion_with_veto` — `NumberRecommender` 호출로 교체 (구 로직 보존, 토글 가능)
8. `langchain-backend/models/meta_learner.py` — 4 Pillar 가중치 학습 path 추가
9. `langchain-backend/pipeline/weekly_pipeline_v2.py::_run_analysis()` — 신규 컴포넌트 호출 (NumberScorer + Recommender + Narrative)
10. `langchain-backend/services/filter_stats.py` — `compute_filter_compliance(n)` 출력 추가 (Pillar 2 입력 제공)
11. `langchain-backend/config.py` — 신규 설정:
    - `PILLAR_META_LEARNER_PATH = 'pillar_meta_weights.json'`
    - `DEFAULT_RANK_SLICES = [(1,9), (10,19), (20,29), (30,39), (40,45)]`
    - `RECOMMEND_CONSENSUS_TOP10_THRESHOLD = 4`
    - `EXCLUDE_CONSENSUS_BOTTOM15_THRESHOLD = 4`
    - `RECOMMENDATION_BACKTEST_WINDOW = 50`
    - `NARRATIVE_GEMMA_PROMPT_PATH = 'prompts/number_narrative_3section.txt'`

### 신규 캐시·문서

12. `saved_models/pillar_meta_weights.json` — Pillar 가중치 (주간 갱신)
13. `prompts/number_narrative_3section.txt` — Gemma 4 system prompt (시그널/근거/결론 3섹션 규칙)

---

## 진행 우선순위 (구현 시)

1. **`ModelRankExtractor`** — 7모델 ranking 추출 (가장 기초, 다른 컴포넌트 입력 제공)
2. **`ConsensusAnalyzer`** — Pillar 4 4 메트릭
3. **`NumberScorer`** — 4 Pillar 통합 + 메타러너 (Pillar 2·3 입력은 기존 컴포넌트 호출)
4. **`NumberRecommender`** — 다중 조건 추천/제외 결정
5. **`RecommendationBacktest`** — 50회차 검증 시작
6. **`NumberNarrativeGenerator`** — Gemma 4 통합 (마지막)

---

## 검증

### 기능 검증
- [ ] `ModelRankExtractor`가 7모델 ranking 정확히 추출
- [ ] 5분할 슬라이스 + 사용자 정의 슬라이스 정상 동작
- [ ] 합집합/공집합/per_number_count 매트릭스 정확
- [ ] 4 Pillar 점수 각각 정상 계산 + 메타러너 가중치 학습
- [ ] 추천/제외 결정 다중 조건 통과 검증
- [ ] Narrative 3섹션 Gemma 4 출력 형식 일관

### 성능 검증 (핵심)
- [ ] **50회차 백테스트에서 추천 hit 평균 1 → 2~3 향상**
- [ ] **50회차 백테스트에서 제외 hit 평균 1-2 → 0~1 감소**
- [ ] 베이스라인 대비 통계적 유의성 (랜덤 추천 hit 0.67 대비 +1 이상)
- [ ] consensus_score (Pillar 4)가 메타러너 SHAP 상위 1~2 진입 (가장 신뢰성 있는 신호 검증)

### 통합 검증
- [ ] 19지표 plan + 회귀 plan + 본 plan 함께 실행 시 충돌 없음
- [ ] Pillar 2 filter_compliance가 21지표 출력에서 정확 계산
- [ ] Pillar 3 individual_state가 핫콜드/미출현/회귀 출력에서 정확 계산
- [ ] Gemma 4 narrative가 LLM 호출 캐시(LRU)와 정상 통합
- [ ] 주간 백테스트 + 메타 가중치 갱신 자동 실행

### Narrative 품질 검증
- [ ] 3섹션이 항상 한 문장씩 (사용자 명세)
- [ ] 수치는 도메인 자연수만(회차 수, 모델 수 등), SHAP/p값 같은 모델 내부 수치 부재
- [ ] 시그널·근거·결론 흐름이 자연스러움
- [ ] 한국어 도메인 용어 정확성 (핫콜드/미출현/회귀/끝수 등)

---

## 미해결 / 추후 결정

- **Filter compliance 가중치**: 21지표 중 일부가 더 강한 신호(예: 끝수합·번호대 vs 이웃수). 학습 데이터에서 자동 도출 권장 — 메타러너에 위임
- **Narrative 다국어**: 현재 한국어만 명시. 영어 등 추후 필요시 별도 prompt
- **Pillar 가중치 신뢰구간**: 50회차 백테스트가 적은 sample이라 가중치 변동 클 수 있음 → 100회차 또는 200회차로 확장 검토
- **Cold start (학습 데이터 적은 N회귀)**: 회귀 plan의 sparse N 처리 영향 — Pillar 3 individual_state에 noise 가능
