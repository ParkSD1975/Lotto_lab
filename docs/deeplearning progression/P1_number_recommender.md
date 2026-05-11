# P1. NumberRecommender 빈도 페널티 패치

> **대상 파일**: `lotto-ai-backend/models/number_recommender.py`  
> **목적**: favorite number bias 해소 (18, 14, 43 등이 매주 추천되는 문제)  
> **근거**: `Lotto_lab_Root_Cause_Diagnosis.md` Finding #2  
> **예상 시간**: 30분 (코드 수정) + 1시간 (백테스트)

---

## 🎯 문제 요약

### 현재 상태
- 50회차 분석 결과 18은 60%, 14·43은 각 50% 회차에 추천됨
- `models/number_recommender.py.select_recommendations()`는 `draws_so_far` 파라미터 미수신
- 회차별 상황 무관한 historical-bias 추천 발생

### 패치 후 기대
- 18 추천률 60% → 25% 이하
- Top-5 hit 평균 0.78 → 0.95+
- 3개+ 적중 0건 → 2~5건 / 50회

---

## 📝 변경 사항 3가지

### 변경 1. **유틸 함수 신규 추가**
위치: 파일 상단 `_ci_lower_estimate()` 함수 **다음**

### 변경 2. **`select_recommendations()` 시그니처 + 본문 수정**
위치: 메서드 시그니처에 `draws_so_far` 파라미터 추가, 본문 맨 앞에 페널티 적용 블록 삽입

### 변경 3. **`recommend()` 내부 호출 수정**
위치: `self.select_recommendations(...)` 호출 시 `draws_so_far` 전달

---

## 💻 패치 코드 (그대로 복사 가능)

### [변경 1] 유틸 함수 추가

`_ci_lower_estimate()` 함수 정의 다음에 아래 블록 추가:

```python
# ──────────────────────────────────────────────────────────────────────
# [P1 PATCH] 빈도 페널티 — favorite bias 해소
# 근거: Lotto_lab_Root_Cause_Diagnosis.md (Finding #2)
# 패치 일자: 2026-05-11
# ──────────────────────────────────────────────────────────────────────
def _compute_frequency_penalty(
    n: int,
    draws_so_far: list[dict] | None,
    recent_window: int = 3,
    recent_penalty: float = 0.7,
    historical_threshold_high: float = 0.18,
    historical_penalty_high: float = 0.85,
    historical_threshold_mid: float = 0.16,
    historical_penalty_mid: float = 0.92,
    min_rounds_for_hist: int = 50,
) -> float:
    """
    빈도 페널티 곱셈 계수 반환 (1.0 = 페널티 없음, < 1.0 = 감점).

    Args:
        n: 평가할 번호 (1~45)
        draws_so_far: 회차 history. 각 요소는 {'numbers': [...]} 또는 list of int.
        recent_window: 최근 N회 회피 윈도우 (기본 3)
        recent_penalty: 최근 N회 출현 시 곱셈 계수 (기본 0.7 = 30% 감점)
        historical_threshold_high: 자연 빈도 대비 high 임계 (기본 0.18)
        historical_penalty_high: high 페널티 (기본 0.85 = 15% 감점)
        historical_threshold_mid: mid 임계 (기본 0.16)
        historical_penalty_mid: mid 페널티 (기본 0.92 = 8% 감점)
        min_rounds_for_hist: 히스토리컬 페널티 적용 최소 회차 수

    Returns:
        곱셈 계수 (예: 0.7 × 0.85 = 0.595)

    Examples:
        >>> _compute_frequency_penalty(18, [{'numbers': [18,14,...]}, ...])
        0.595  # 최근 출현 + 자연 빈도 초과
    """
    if not draws_so_far:
        return 1.0

    coef = 1.0

    # 1) 직전 N회 출현 페널티
    recent_numbers: set[int] = set()
    for draw in draws_so_far[-recent_window:]:
        nums = draw.get("numbers") if isinstance(draw, dict) else draw
        if isinstance(nums, (list, tuple, set)):
            for x in nums:
                try:
                    recent_numbers.add(int(x))
                except (ValueError, TypeError):
                    continue
    if n in recent_numbers:
        coef *= recent_penalty

    # 2) Historical 빈도 페널티
    total_rounds = len(draws_so_far)
    if total_rounds >= min_rounds_for_hist:
        appear_count = 0
        for draw in draws_so_far:
            nums = draw.get("numbers") if isinstance(draw, dict) else draw
            if isinstance(nums, (list, tuple, set)):
                for x in nums:
                    try:
                        if int(x) == n:
                            appear_count += 1
                            break
                    except (ValueError, TypeError):
                        continue
        hist_freq = appear_count / total_rounds

        if hist_freq > historical_threshold_high:
            coef *= historical_penalty_high
        elif hist_freq > historical_threshold_mid:
            coef *= historical_penalty_mid

    return coef
```

---

### [변경 2] `select_recommendations()` 수정

#### 2-A. 메서드 시그니처 수정

**Before**:
```python
def select_recommendations(
    self,
    scores: dict[int, float],
    consensus_metrics: dict[int, dict],
    filter_compliance: np.ndarray,
    expert_memo: dict | None = None,
    n_top: int = 5,
    bayesian_sigma: dict[int, float] | None = None,
) -> list[dict]:
```

**After** (`draws_so_far` 파라미터 추가):
```python
def select_recommendations(
    self,
    scores: dict[int, float],
    consensus_metrics: dict[int, dict],
    filter_compliance: np.ndarray,
    expert_memo: dict | None = None,
    n_top: int = 5,
    bayesian_sigma: dict[int, float] | None = None,
    draws_so_far: list[dict] | None = None,  # [P1 PATCH]
) -> list[dict]:
```

#### 2-B. 메서드 docstring 수정

**Before**:
```
"""추천 5 선출 (Hard Filter 3계층).

흐름:
1. 사용자 메모 forced_includes 우선 (최대 n_top까지 강제 포함)
2. final_score 정렬 -> 상위 15 후보
3. consensus_metrics.top10_count >= REC_TOP10_THR 통과
4. filter_compliance >= median + 0.1 통과
5. CI lower bound 정렬 -> top n_top
"""
```

**After**:
```
"""추천 5 선출 (Hard Filter 3계층 + [P1] 빈도 페널티).

흐름:
1. 사용자 메모 forced_includes 우선 (최대 n_top까지 강제 포함)
2. [P1 PATCH] 빈도 페널티 적용 (favorite bias 해소)
3. final_score 정렬 -> 상위 15 후보
4. consensus_metrics.top10_count >= REC_TOP10_THR 통과
5. filter_compliance >= median + 0.1 통과
6. CI lower bound 정렬 -> top n_top
"""
```

#### 2-C. 본문 — comp 계산 다음에 페널티 블록 삽입

**찾을 위치** (대략 line 156):
```python
comp = _coerce_filter_compliance(filter_compliance)
median_comp = float(np.median(comp))
thr_comp = median_comp + 0.1

# 메모 forced_includes
memo_forced: set[int] = set()
```

**`thr_comp = ...` 다음, `# 메모 forced_includes` 줄 직전에 삽입**:

```python
    comp = _coerce_filter_compliance(filter_compliance)
    median_comp = float(np.median(comp))
    thr_comp = median_comp + 0.1

    # ── [P1 PATCH] 빈도 페널티 적용 ────────────────────────
    # favorite bias 해소: 직전 3회 출현 + historical 과빈출 감점
    # 단, memo_forced_includes는 페널티 면제
    _memo_forced_for_penalty: set[int] = set()
    if isinstance(expert_memo, dict):
        _memo_forced_for_penalty = _safe_int_set(
            expert_memo.get("forced_includes")
        )

    if draws_so_far:
        _adjusted_scores: dict[int, float] = {}
        for _n in range(1, 46):
            _base = float(scores.get(_n, 0.0))
            if _n in _memo_forced_for_penalty:
                _adjusted_scores[_n] = _base
            else:
                _coef = _compute_frequency_penalty(_n, draws_so_far)
                _adjusted_scores[_n] = _base * _coef
        scores = _adjusted_scores
    # ── /P1 PATCH ─────────────────────────────────────────

    # 메모 forced_includes
    memo_forced: set[int] = set()
```

---

### [변경 3] `recommend()` 내부 호출 수정

**찾을 위치** (대략 line 498~510):

**Before**:
```python
        # 5) 추천 + 제외
        recommendations = self.select_recommendations(
            scores=scores,
            consensus_metrics=consensus_metrics,
            filter_compliance=comp,
            expert_memo=expert_memo,
            n_top=n_top,
            bayesian_sigma=bayesian_sigma,
        )
```

**After** (`draws_so_far` 전달 추가):
```python
        # 5) 추천 + 제외
        recommendations = self.select_recommendations(
            scores=scores,
            consensus_metrics=consensus_metrics,
            filter_compliance=comp,
            expert_memo=expert_memo,
            n_top=n_top,
            bayesian_sigma=bayesian_sigma,
            draws_so_far=draws_so_far,  # [P1 PATCH]
        )
```

---

## 🧪 검증 절차

### 1. Smoke 테스트
```bash
cd lotto-ai-backend
python -m models.number_recommender
```

**기대 결과**: 기존 smoke main의 모든 assert 통과 + 새 페널티 동작

### 2. 단일 회차 테스트 (수동)
```python
from models.number_recommender import _compute_frequency_penalty

# 최근 출현 + 자연 빈도 초과 → 0.595
draws = [
    {"numbers": [18, 14, 43, 7, 22, 35]},  # 직전 회차
    {"numbers": [3, 18, 27, 11, 39, 5]},   # 2회 전
] * 60  # 120회 history

coef_18 = _compute_frequency_penalty(18, draws)
print(f"18 penalty: {coef_18:.3f}")  # ~0.595 예상

coef_4 = _compute_frequency_penalty(4, draws)
print(f"4 penalty: {coef_4:.3f}")    # 1.0 (출현 X)
```

### 3. 50회 백테스트
```bash
python -m pipeline.weekly_pipeline_v2 --backtest --rounds 1173-1222
```

### 4. 효과 측정 SQL (Supabase)
```sql
WITH stats AS (
  SELECT 
    target_round,
    top_5,
    top5_hit_count,
    18 = ANY(top_5) AS has_18,
    14 = ANY(top_5) AS has_14,
    43 = ANY(top_5) AS has_43
  FROM weekly_predictions
  WHERE target_round BETWEEN 1173 AND 1222
)
SELECT 
  ROUND(100.0 * SUM(CASE WHEN has_18 THEN 1 ELSE 0 END) / COUNT(*), 1) as pct_18,
  ROUND(100.0 * SUM(CASE WHEN has_14 THEN 1 ELSE 0 END) / COUNT(*), 1) as pct_14,
  ROUND(100.0 * SUM(CASE WHEN has_43 THEN 1 ELSE 0 END) / COUNT(*), 1) as pct_43,
  ROUND(AVG(top5_hit_count)::numeric, 3) as avg_hit_top5,
  SUM(CASE WHEN top5_hit_count >= 3 THEN 1 ELSE 0 END) as count_hit_3plus
FROM stats;
```

**목표 (50회 기준)**:
| 메트릭 | 패치 전 | 목표 |
|--------|---------|------|
| pct_18 | 60.0 | < 30.0 |
| pct_14 | 50.0 | < 30.0 |
| pct_43 | 50.0 | < 30.0 |
| avg_hit_top5 | 0.78 | > 0.95 |
| count_hit_3plus | 0 | ≥ 2 |

---

## ⚠️ 주의 사항

### 1. 파라미터 튜닝
첫 적용은 기본값으로. 효과 미흡하면:

| 파라미터 | 더 강한 페널티 | 더 약한 페널티 |
|---------|-------------|-------------|
| recent_penalty | 0.5~0.6 | 0.8~0.85 |
| historical_penalty_high | 0.7~0.8 | 0.88~0.92 |
| recent_window | 5 | 2 |
| historical_threshold_high | 0.16 | 0.20 |

### 2. memo_forced_includes 면제
사용자가 `forced_includes=[18]` 지정 시 페널티 면제됨 (의도된 동작).  
원치 않으면 패치 코드에서 `if _n in _memo_forced_for_penalty:` 분기 제거.

### 3. `select_exclusions()`에는 패치 안 함
제외수 로직은 그대로 유지.  
필요 시 P1-extended로 별도 패치.

### 4. backward compatibility
`draws_so_far=None`이면 페널티 비활성 → **기존 호출 코드 변경 없이도 작동**.

---

## 🔄 롤백 절차

```bash
cd lotto-ai-backend
git checkout models/number_recommender.py
# 또는
git revert <patch-commit-hash>
```

---

## ✅ 적용 체크리스트

```
□ 백업 (git branch 생성)
□ 변경 1: _compute_frequency_penalty 함수 추가
□ 변경 2-A: select_recommendations 시그니처 수정
□ 변경 2-B: docstring 수정
□ 변경 2-C: 페널티 블록 삽입
□ 변경 3: recommend() 내부 호출 수정
□ Smoke 테스트 (python -m models.number_recommender)
□ 50회 백테스트
□ 효과 측정 SQL 실행
□ 18/14/43 등장률 30% 이하 확인
□ avg_hit_top5 0.95 이상 확인
□ Git commit + push
```

---

## 📝 Git Commit 메시지 예시

```
fix(recommender): apply frequency penalty to break favorite bias [P1]

- Add _compute_frequency_penalty utility for recent/historical penalty
- Modify select_recommendations to accept draws_so_far param
- Apply penalty before score-based filtering (memo_forced exempted)
- Update recommend() to forward draws_so_far

Diagnosis evidence: number 18 appeared in 60% of top_5 across 50 rounds,
14 and 43 in 50% each. After patch, expected drop to < 30% with
top5_hit improvement from 0.78 → 0.95+.

Refs: Lotto_lab_Root_Cause_Diagnosis.md (Finding #2)
```

---

## 🔗 관련 문서

- `../Lotto_lab_Root_Cause_Diagnosis.md` — 진단 (왜 이 패치가 필요)
- `../Lotto_lab_Logic_Enhancements.md` — 로드맵 (P 영역)
- `README.md` — 전체 패치 가이드
