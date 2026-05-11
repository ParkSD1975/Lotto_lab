# Phase 1 Predictor 5개 신설 (Stage 1-2)

## 신설 파일

1. **phase1_endings_distribution.py** (102 lines)
   - 끝수 0~9 카테고리별 7-class 카운트 분류
   - 풀 사이즈: [4,5,5,5,5,5,5,5,5,4]
   - Markov 7-state + 빈도 분포 결합

2. **phase1_high_low.py** (93 lines)
   - 고저 단일 카테고리 7-class
   - 저번호 1~22 (풀 22개), 고번호 23~45 (풀 23개)
   - 저번호 카운트 예측

3. **phase1_odd_even.py** (93 lines)
   - 홀짝 단일 카테고리 7-class
   - 홀수 1,3,5,...,45 (풀 23개), 짝수 2,4,...,44 (풀 22개)
   - 홀수 카운트 예측

4. **phase1_decade.py** (107 lines)
   - 번호대 5 카테고리 × 7-class
   - (1-9, 10-19, 20-29, 30-39, 40-45)
   - 풀 사이즈: [9, 10, 10, 10, 6]

5. **phase1_gung.py** (107 lines)
   - 9궁 9 카테고리 × 7-class
   - (1-5, 6-10, 11-15, ..., 41-45)
   - 풀 사이즈: [5] × 9

**총 502 lines** (주석 제외 실제 코드)

---

## 9궁 정의 (phase1_gung.py)

```python
GUNG_RANGES = [
    (1, 5),    # 9궁 0
    (6, 10),   # 9궁 1
    (11, 15),  # 9궁 2
    (16, 20),  # 9궁 3
    (21, 25),  # 9궁 4
    (26, 30),  # 9궁 5
    (31, 35),  # 9궁 6
    (36, 40),  # 9궁 7
    (41, 45),  # 9궁 8
]
```

※ `phase1_registry.py` 기존 정의 `(n-1)//5`와 동일 (1~45를 5개씩 균등 분할)

---

## Walk-Forward 검증 (50 rounds)

| Predictor | 카테고리 수 | predictor_ce | frequency_ce | improvement_pct | wins | gate |
|-----------|-------------|--------------|--------------|-----------------|------|------|
| endings_distribution | 10 | 0.9782 | 0.9724 | -0.60% | False | **FAIL** |
| high_low | 1 | 1.5937 | 1.5895 | -0.27% | False | **FAIL** |
| odd_even | 1 | 1.6736 | 1.6689 | -0.28% | False | **FAIL** |
| decade | 5 | 1.2509 | 1.2446 | -0.50% | False | **FAIL** |
| gung | 9 | 1.0298 | 1.0231 | -0.65% | False | **FAIL** |

**모든 5개 predictor가 frequency baseline을 이기지 못함**.

---

## 원인 분석

현재 구현은 **Markov 7-state 전이행렬 + 빈도 분포 단순 평균** (각 50% 가중치).

마스터 플랜 지시:
> 베이스 통합: Markov + 빈도 (sum_predictor와 동일 단순화). 11 base 전체 통합은 추후

즉, 이번 PR에서는 **단순 베이스라인** 구현만 완료하고, 검증 게이트 통과는 **11 base 통합 후**로 미룹니다.

---

## 다음 우선순위

1. **Phase 1 나머지 12개 predictor 신설** (배수/로또용지/미출현/핫콜드/소수/...)
2. **11 base 통합** (XGBoost/CatBoost/TabNet/Bayesian/TFT/N-BEATS/MHN)
   - IndependentCountPredictor 베이스 클래스 활용
   - per-category 7-class softmax head
   - walk-forward CE 검증 게이트 PASS 목표
3. **Phase 2 endings_sum / ac_predictor 신설**

---

## 검증 명령

```bash
cd langchain-backend
python -m predictors.phase1_endings_distribution --validate 50
python -m predictors.phase1_high_low --validate 50
python -m predictors.phase1_odd_even --validate 50
python -m predictors.phase1_decade --validate 50
python -m predictors.phase1_gung --validate 50
```
