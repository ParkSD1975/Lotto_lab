# 해외 로또 DB 스키마 설계

## 설계 원칙

- **당첨번호 + 드로우 레벨 고정 지표**는 수집 시 1회 계산 후 저장
- **번호별 빈도·패턴 통계**는 실시간 SQL 집계로 계산 (데이터 수천 건 수준이라 성능 문제 없음)
- 모든 로또는 `lotteries` 테이블로 통합 관리, 국가별 분리 없음

---

## 테이블 구조

### `lotteries` — 로또 종류 목록

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `id` | uuid (PK) | |
| `name` | text | 표시 이름 (예: `Netherlands Lotto`) |
| `country` | text | 국가 코드 (예: `NL`, `KR`, `AU`) |
| `format` | text | 포맷 (예: `6/45`) |
| `ball_count` | int | 메인 번호 개수 (6) |
| `max_number` | int | 최대 번호 (45) |
| `bonus_count` | int | 보너스 번호 개수 (0~2) |
| `draw_days` | text[] | 추첨 요일 (예: `["SAT"]`, `["WED","SAT"]`) |
| `source` | text | 수집 소스 (`rss` / `scrape`) |
| `source_url` | text | RSS URL 또는 스크래핑 URL |
| `is_active` | bool | 수집 활성화 여부 |
| `created_at` | timestamptz | |

**샘플 데이터:**
```
id | name                  | country | format | ball_count | max_number | bonus_count | draw_days           | source
---+-----------------------+---------+--------+------------+------------+-------------+---------------------+--------
.. | 한국 로또 6/45        | KR      | 6/45   | 6          | 45         | 1           | ["SAT"]             | scrape
.. | Netherlands Lotto     | NL      | 6/45   | 6          | 45         | 1           | ["SAT"]             | scrape
.. | Netherlands Lotto XL  | NL      | 6/45   | 6          | 45         | 1           | ["WED"]             | scrape
.. | Saturday Lotto        | AU      | 6/45   | 6          | 45         | 2           | ["SAT"]             | scrape
.. | Monday Lotto          | AU      | 6/45   | 6          | 45         | 2           | ["MON"]             | scrape
.. | Wednesday Lotto       | AU      | 6/45   | 6          | 45         | 2           | ["WED"]             | scrape
.. | Austria Lotto 6/45    | AT      | 6/45   | 6          | 45         | 1           | ["WED","SUN"]       | scrape
.. | Hatoslottó            | HU      | 6/45   | 6          | 45         | 0           | ["THU","SUN"]       | scrape
.. | Loto 6/45             | HR      | 6/45   | 6          | 45         | 1           | ["WED"]             | scrape
.. | Belgium Lotto         | BE      | 6/45   | 6          | 45         | 1           | ["WED","SAT"]       | scrape
.. | Mega Lotto 6/45       | PH      | 6/45   | 6          | 45         | 0           | ["MON","WED","FRI"] | rss
.. | Mega 645 (수)         | PH      | 6/45   | 6          | 45         | 0           | ["WED"]             | rss
.. | Mega 645 (금)         | PH      | 6/45   | 6          | 45         | 0           | ["FRI"]             | rss
.. | Mega 645 (일)         | PH      | 6/45   | 6          | 45         | 0           | ["SUN"]             | rss
```

---

### `draws` — 추첨 결과 + 기초지표

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `id` | uuid (PK) | |
| `lottery_id` | uuid (FK → lotteries) | |
| `draw_date` | date | 추첨일 |
| `draw_no` | int | 회차 번호 (없으면 null) |
| `n1` ~ `n6` | int | 메인 번호 (오름차순 정렬 저장) |
| `b1` | int | 보너스 번호 1 (없으면 null) |
| `b2` | int | 보너스 번호 2 (없으면 null) |

#### 기초지표 — 합계·복잡도

| 컬럼 | 타입 | 설명 | 계산 방법 |
|------|------|------|-----------|
| `sum` | int | 총합 | n1+n2+n3+n4+n5+n6 |
| `tail_sum` | int | 끝수합 | 각 번호의 1의 자리 합 (예: 13→3, 27→7) |
| `ac` | int | AC값 | 모든 쌍의 절댓값 차이 중 고유값 수 − 5 (범위: 0~10) |

#### 기초지표 — 홀짝·고저

| 컬럼 | 타입 | 설명 | 기준 |
|------|------|------|------|
| `odd_count` | int | 홀수 개수 | 홀수 번호 수 (0~6) |
| `even_count` | int | 짝수 개수 | 짝수 번호 수 (0~6) |
| `low_count` | int | 저번호 개수 | 1~22 (0~6) |
| `high_count` | int | 고번호 개수 | 23~45 (0~6) |

#### 기초지표 — 수 유형별

| 컬럼 | 타입 | 설명 | 1~45 내 해당 번호 |
|------|------|------|-------------------|
| `prime_count` | int | 소수 개수 | 2,3,5,7,11,13,17,19,23,29,31,37,41,43 (14개) |
| `composite_count` | int | 합성수 개수 | 4,6,8,9,10,12,14,15,16,18,20,21,22,24,25,26,27,28,30,32,33,34,35,36,38,39,40,42,44,45 |
| `mult3_count` | int | 3의 배수 개수 | 3,6,9,12,15,18,21,24,27,30,33,36,39,42,45 (15개) |
| `mult4_count` | int | 4의 배수 개수 | 4,8,12,16,20,24,28,32,36,40,44 (11개) |
| `mult5_count` | int | 5의 배수 개수 | 5,10,15,20,25,30,35,40,45 (9개) |
| `mult7_count` | int | 7의 배수 개수 | 7,14,21,28,35,42 (6개) |
| `triangle_count` | int | 삼각수 개수 | 1,3,6,10,15,21,28,36,45 (9개) |

> 참고: 1은 소수도 합성수도 아님. `prime_count + composite_count + (1이 포함된 경우 1) = 6`

#### 기초지표 — 끝수별 (1의 자리 분포)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `tail_0` | int | 끝자리 0인 번호 수 (10,20,30,40) |
| `tail_1` | int | 끝자리 1인 번호 수 (1,11,21,31,41) |
| `tail_2` | int | 끝자리 2인 번호 수 (2,12,22,32,42) |
| `tail_3` | int | 끝자리 3인 번호 수 (3,13,23,33,43) |
| `tail_4` | int | 끝자리 4인 번호 수 (4,14,24,34,44) |
| `tail_5` | int | 끝자리 5인 번호 수 (5,15,25,35,45) |
| `tail_6` | int | 끝자리 6인 번호 수 (6,16,26,36) |
| `tail_7` | int | 끝자리 7인 번호 수 (7,17,27,37) |
| `tail_8` | int | 끝자리 8인 번호 수 (8,18,28,38) |
| `tail_9` | int | 끝자리 9인 번호 수 (9,19,29,39) |

> tail_0 ~ tail_9 합계 = 6

#### 기초지표 — 번호대별 (십의 자리 구간)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `range_1` | int | 단번대 (1~9) 개수 |
| `range_10` | int | 10번대 (10~19) 개수 |
| `range_20` | int | 20번대 (20~29) 개수 |
| `range_30` | int | 30번대 (30~39) 개수 |
| `range_40` | int | 40번대 (40~45) 개수 |

> range_1 ~ range_40 합계 = 6

#### 기타

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `consecutive_pairs` | int | 연속번호 쌍 수 (예: 3,4 → 1쌍 / 3,4,5 → 2쌍) |
| `created_at` | timestamptz | 수집 시각 |

**Unique 제약:** `(lottery_id, draw_date)`

---

## AC값 계산 방법

```
AC = (6개 번호에서 모든 쌍의 절댓값 차이 중 고유한 값의 수) − (6 − 1)

예시: [3, 13, 22, 28, 35, 44]
모든 쌍 차이: |13-3|=10, |22-3|=19, |22-13|=9, |28-3|=25, |28-13|=15,
              |28-22|=6, |35-3|=32, |35-13|=22, |35-22|=13, |35-28|=7,
              |44-3|=41, |44-13|=31, |44-22|=22, |44-28|=16, |44-35|=9
고유값: {10,19,9,25,15,6,32,22,13,7,41,31,16} → 13개 (22와 9가 중복)
AC = 13 − 5 = 8
```

- **최솟값 0**: 차이가 5가지뿐 (극단적 등차수열)
- **최댓값 10**: 15가지 차이 모두 고유

---

## 끝수합 계산 방법

```
끝수합 = 각 번호의 1의 자리 숫자 합계
예시: [3, 13, 22, 28, 35, 44]
끝수: 3 + 3 + 2 + 8 + 5 + 4 = 25
```

---

## 실시간 계산 통계 (SQL 예시)

저장 없이 쿼리로 계산하는 지표들:

```sql
-- 번호별 출현 빈도 (전체)
SELECT
  unnest(ARRAY[n1,n2,n3,n4,n5,n6]) AS number,
  COUNT(*) AS freq
FROM draws
WHERE lottery_id = :id
GROUP BY 1
ORDER BY 1;

-- 최근 50회 기준 출현 빈도
SELECT
  unnest(ARRAY[n1,n2,n3,n4,n5,n6]) AS number,
  COUNT(*) AS freq
FROM (
  SELECT * FROM draws
  WHERE lottery_id = :id
  ORDER BY draw_date DESC
  LIMIT 50
) recent
GROUP BY 1
ORDER BY 1;

-- 번호별 미출현 연속 횟수
WITH ranked AS (
  SELECT
    draw_date,
    unnest(ARRAY[n1,n2,n3,n4,n5,n6]) AS n,
    ROW_NUMBER() OVER (ORDER BY draw_date DESC) AS rn
  FROM draws
  WHERE lottery_id = :id
)
SELECT n, MIN(rn) - 1 AS games_out
FROM ranked
WHERE n = :number
GROUP BY n;
```

---

## 인덱스

```sql
CREATE INDEX idx_draws_lottery_date ON draws (lottery_id, draw_date DESC);
CREATE INDEX idx_draws_lottery_no   ON draws (lottery_id, draw_no DESC);
```

---

## 수집 로그 테이블

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `id` | uuid (PK) | |
| `lottery_id` | uuid (FK) | |
| `collected_at` | timestamptz | 수집 실행 시각 |
| `draws_added` | int | 이번 수집에서 추가된 추첨 수 |
| `status` | text | `success` / `error` |
| `error_msg` | text | 에러 메시지 (null이면 성공) |

---

## 데이터 흐름

```
수집 (RSS / 스크래퍼)
  → 당첨번호 파싱
  → 기초지표 계산
      합계류: sum, tail_sum, ac
      홀짝·고저: odd_count, even_count, low_count, high_count
      수유형: prime_count, composite_count, mult3/4/5/7_count, triangle_count
      끝수별: tail_0 ~ tail_9
      번호대별: range_1, range_10, range_20, range_30, range_40
      기타: consecutive_pairs
  → draws 테이블 UPSERT (on conflict (lottery_id, draw_date) do nothing)
  → collect_logs INSERT
```

---

## 관련 문서

- 데이터 수집 전략: 소스 2곳 (lottolyzer RSS + lotteryextreme 스크래핑)
- 대상 로또: 14개 (한국 포함)
