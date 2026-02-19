# 🗺️ AI 분석 확장 로드맵 - Phase 2 & 3 계획

## 📋 목차
1. [Phase 1.5: Hot/Cold 분석](#phase-15-hotcold-분석)
2. [Phase 2: 9궁 분석](#phase-2-9궁-분석)
3. [Phase 3: 로또용지 평가](#phase-3-로또용지-평가)
4. [일정 & 우선순위](#일정--우선순위)

---

## Phase 1.5: Hot/Cold 분석

### 목표
각 번호의 **미출현 기간(gap)**을 기반으로 상태를 분류하고, 권장 구성을 제시

### 상태 정의

```
현재 draw 이후 경과 기간(gap)별 분류:

🔥 HOT:       gap 0-2    (최근 3회 이내 출현)
             상승 추세, 모멘텀 있음
             추천: 2~3개 포함

⚪ ACTIVE:    gap 3-7    (최근 8~10회 범위)
             중간 활성도, 안정적
             추천: 2~3개 포함

🟡 COOLING:   gap 8-15   (중기 미출현)
             약화 단계, 서서히 나올 시간
             추천: 1~2개 포함

❄️  COLD:     gap 16-25  (장기 미출현)
             차갑지만 돌아올 시간 근처
             추천: 0~1개 포함

🧊 DEADCOLD:  gap 26+    (극도로 미출현)
             부활 임박 신호
             추천: 0~1개 포함 (매우 선택적)
```

### 구현 단계

#### 1단계: Helper 함수 추가 (위치: deep_analysis_v3.py 라인 165)

```python
def get_number_status(num: int, history_draws: list):
    """번호의 gap을 계산하고 상태를 반환"""
    # history_draws: 최근 N회 당첨번호 리스트
    # 예: [1, 5, 12], [3, 8, 15, 22, 35, 40], ...

    gap = 0
    for draw in history_draws:
        if num in draw:
            break
        gap += 1

    if gap <= 2:
        return "hot"
    elif gap <= 7:
        return "active"
    elif gap <= 15:
        return "cooling"
    elif gap <= 25:
        return "cold"
    else:
        return "deadcold"

# 사용 예:
status = get_number_status(27, history_draws)
# 반환: "cold" (또는 다른 상태)
```

#### 2단계: Matrix 데이터에 상태 정보 추가 (라인 210-220)

**현재 구조:**
```python
matrix_data.append({
    "num": n,
    "total": 점수,
    "models": {...},
    "gap": gap,
    "hot": streak
})
```

**확장 구조:**
```python
matrix_data.append({
    "num": n,
    "total": 점수,
    "models": {...},
    "gap": gap,
    "hot": streak,
    "status": get_number_status(n, history_draws)  # ← 새로 추가
})
```

#### 3단계: 기초분석에 상태별 집계 추가 (라인 90-110)

```python
# 각 상태별 권장 개수 계산
status_counts = {
    "hot": 0,
    "active": 0,
    "cooling": 0,
    "cold": 0,
    "deadcold": 0
}

for m in matrix_data:
    status_counts[m["status"]] += 1

# 프론트엔드로 전송
return {
    "status_analysis": {
        "hot_count": status_counts["hot"],
        "active_count": status_counts["active"],
        "cooling_count": status_counts["cooling"],
        "cold_count": status_counts["cold"],
        "deadcold_count": status_counts["deadcold"],
        "recommendation": {
            "hot": "2~3개 권장",
            "active": "2~3개 권장",
            "cooling": "1~2개 권장",
            "cold": "0~1개 권장"
        }
    }
}
```

#### 4단계: 프론트엔드 UI 추가 (ai_deep_learning.html 라인 700)

**새로운 "상태분석" 섹션:**

```html
<div class="section">
  <h3>📊 상태분석</h3>
  <div class="status-cards">
    <div class="status-card hot">
      <h4>🔥 HOT (최근 3회)</h4>
      <p>현재: <span id="hot-count">0</span>개</p>
      <p>권장: 2~3개</p>
      <div class="number-list" id="hot-numbers">12, 27, 39, ...</div>
    </div>

    <div class="status-card active">
      <h4>⚪ ACTIVE (최근 10회)</h4>
      <p>현재: <span id="active-count">0</span>개</p>
      <p>권장: 2~3개</p>
      <div class="number-list" id="active-numbers">5, 18, 34, ...</div>
    </div>

    <div class="status-card cooling">
      <h4>🟡 COOLING (중기)</h4>
      <p>현재: <span id="cooling-count">0</span>개</p>
      <p>권장: 1~2개</p>
      <div class="number-list" id="cooling-numbers">8, 23, ...</div>
    </div>

    <div class="status-card cold">
      <h4>❄️  COLD (장기)</h4>
      <p>현재: <span id="cold-count">0</span>개</p>
      <p>권장: 0~1개</p>
      <div class="number-list" id="cold-numbers">3, 15, ...</div>
    </div>
  </div>
</div>
```

**JavaScript 업데이트:**

```javascript
// API 응답의 status_analysis 데이터를 활용
const statusData = response.status_analysis;
document.getElementById('hot-count').textContent = statusData.hot_count;
document.getElementById('active-count').textContent = statusData.active_count;
document.getElementById('cooling-count').textContent = statusData.cooling_count;
document.getElementById('cold-count').textContent = statusData.cold_count;

// 각 상태의 번호들 표시
document.getElementById('hot-numbers').textContent = statusData.hot_numbers.join(', ');
document.getElementById('active-numbers').textContent = statusData.active_numbers.join(', ');
// ... 기타
```

### 예상 화면

```
📊 상태분석 섹션
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔥 HOT (최근 3회)          ⚪ ACTIVE (최근 10회)
현재: 5개                  현재: 8개
권장: 2~3개                권장: 2~3개
[12, 27, 39, 5, 18]        [1, 8, 15, 23, 30, 35, 40, 44]
└─ 4개 초과, 1개 감소 필요

🟡 COOLING (중기)           ❄️  COLD (장기)
현재: 2개                  현재: 1개
권장: 1~2개                권장: 0~1개
[6, 11]                    [3]
└─ 적정                     └─ 적정

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

💡 권장 조합: 3 hot + 2 active + 1 cooling + 0 cold
   = 총 6개 (기본 조합)
```

### 구현 예상 시간: 1시간

---

## Phase 2: 9궁 분석

### 목표
45개 번호를 3×3 격자로 나누어 **영역 불균형**을 분석

### 9궁 영역 정의

```
로또 번호의 9궁 분류:

       저(1~15)    중(16~30)    고(31~45)
상 (1-5)   상좌      상중       상우
   (6-10)  (1~5)    (6~10)     (11~15)

중 (16-20) 중좌      중중       중우
   (21-25) (16~20)  (21~25)    (26~30)
   (26-30)

하 (31-35) 하좌      하중       하우
   (36-40) (31~35)  (36~40)    (41~45)
   (41-45)

각 영역별:
  - 포함 번호: 5개씩
  - 총 9개 영역
  - 최대 포함: 6개 조합이므로 일부 영역은 0개 가능
```

### 구현 단계

#### 1단계: 영역 정의 함수 (deep_analysis_v3.py 라인 180)

```python
def get_palace_info(num: int):
    """번호의 9궁 위치 반환"""
    PALACES = {
        # 상좌 (1~5)
        (1, 2, 3, 4, 5): {"name": "상좌", "type": "수(水)", "yin_yang": "음"}
        # 상중 (6~10)
        (6, 7, 8, 9, 10): {"name": "상중", "type": "생(生)", "yin_yang": "양"}
        # 상우 (11~15)
        (11, 12, 13, 14, 15): {"name": "상우", "type": "목(木)", "yin_yang": "음"}
        # 중좌 (16~20)
        (16, 17, 18, 19, 20): {"name": "중좌", "type": "화(火)", "yin_yang": "양"}
        # 중중 (21~25)
        (21, 22, 23, 24, 25): {"name": "중중", "type": "토(土)", "yin_yang": "중"}
        # 중우 (26~30)
        (26, 27, 28, 29, 30): {"name": "중우", "type": "금(金)", "yin_yang": "음"}
        # 하좌 (31~35)
        (31, 32, 33, 34, 35): {"name": "하좌", "type": "수(水)", "yin_yang": "양"}
        # 하중 (36~40)
        (36, 37, 38, 39, 40): {"name": "하중", "type": "생(生)", "yin_yang": "음"}
        # 하우 (41~45)
        (41, 42, 43, 44, 45): {"name": "하우", "type": "목(木)", "yin_yang": "양"}
    }

    for palace_nums, palace_info in PALACES.items():
        if num in palace_nums:
            return palace_info
    return None
```

#### 2단계: 9궁 분석 함수 (라인 200)

```python
def analyze_9palace(combination: list, history_draws: list):
    """9궁 분석 수행"""
    # 각 영역별 포함 개수
    palace_distribution = {
        "상좌": 0, "상중": 0, "상우": 0,
        "중좌": 0, "중중": 0, "중우": 0,
        "하좌": 0, "하중": 0, "하우": 0
    }

    for num in combination:
        palace = get_palace_info(num)["name"]
        palace_distribution[palace] += 1

    # 패턴 분석
    values = list(palace_distribution.values())
    max_count = max(values)
    min_count = min(values)

    if max_count - min_count >= 3:
        balance = "편중 심함"
    elif max_count - min_count >= 2:
        balance = "편중 있음"
    else:
        balance = "균형 좋음"

    # 최근 빈도 분석
    recent_palace = {}
    for draw in history_draws[:50]:  # 최근 50회
        for num in draw:
            palace = get_palace_info(num)["name"]
            recent_palace[palace] = recent_palace.get(palace, 0) + 1

    return {
        "distribution": palace_distribution,
        "balance": balance,
        "recent_frequency": recent_palace,
        "recommendation": generate_palace_recommendation(palace_distribution, recent_palace)
    }
```

#### 3단계: 프론트엔드 시각화 (ai_deep_learning.html 라인 750)

**9궁 그리드 UI:**

```html
<div class="section">
  <h3>🔮 9궁 분석</h3>

  <div class="palace-grid">
    <!-- 상단 -->
    <div class="palace-cell palace-ul">
      <h4>상좌</h4>
      <p class="numbers">1-5</p>
      <p class="count" id="palace-ul">0개</p>
      <p class="recent">최근: <span id="freq-ul">0회</span></p>
    </div>
    <div class="palace-cell palace-uc">
      <h4>상중</h4>
      <p class="numbers">6-10</p>
      <p class="count" id="palace-uc">0개</p>
      <p class="recent">최근: <span id="freq-uc">0회</span></p>
    </div>
    <div class="palace-cell palace-ur">
      <h4>상우</h4>
      <p class="numbers">11-15</p>
      <p class="count" id="palace-ur">0개</p>
      <p class="recent">최근: <span id="freq-ur">0회</span></p>
    </div>

    <!-- 중단 -->
    <div class="palace-cell palace-ml">
      <h4>중좌</h4>
      <p class="numbers">16-20</p>
      <p class="count" id="palace-ml">0개</p>
      <p class="recent">최근: <span id="freq-ml">0회</span></p>
    </div>
    <div class="palace-cell palace-mc">
      <h4>중중</h4>
      <p class="numbers">21-25</p>
      <p class="count" id="palace-mc">0개</p>
      <p class="recent">최근: <span id="freq-mc">0회</span></p>
    </div>
    <div class="palace-cell palace-mr">
      <h4>중우</h4>
      <p class="numbers">26-30</p>
      <p class="count" id="palace-mr">0개</p>
      <p class="recent">최근: <span id="freq-mr">0회</span></p>
    </div>

    <!-- 하단 -->
    <div class="palace-cell palace-dl">
      <h4>하좌</h4>
      <p class="numbers">31-35</p>
      <p class="count" id="palace-dl">0개</p>
      <p class="recent">최근: <span id="freq-dl">0회</span></p>
    </div>
    <div class="palace-cell palace-dc">
      <h4>하중</h4>
      <p class="numbers">36-40</p>
      <p class="count" id="palace-dc">0개</p>
      <p class="recent">최근: <span id="freq-dc">0회</span></p>
    </div>
    <div class="palace-cell palace-dr">
      <h4>하우</h4>
      <p class="numbers">41-45</p>
      <p class="count" id="palace-dr">0개</p>
      <p class="recent">최근: <span id="freq-dr">0회</span></p>
    </div>
  </div>

  <div class="palace-info">
    <p class="balance-status" id="palace-balance">균형: ...</p>
    <p class="recommendation" id="palace-rec">추천: ...</p>
  </div>
</div>

<style>
.palace-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
  margin: 20px 0;
}

.palace-cell {
  border: 2px solid #ddd;
  padding: 15px;
  border-radius: 8px;
  text-align: center;
}

.palace-ul, .palace-ur, .palace-dl, .palace-dr {
  background: #f0f0f0;
}

.palace-uc, .palace-dc {
  background: #e8e8e8;
}

.palace-mc {
  background: #fff9e6;
  border-color: #ffd700;
}
</style>
```

### 예상 화면

```
🔮 9궁 분석
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┌─────────┬─────────┬─────────┐
│ 상좌    │ 상중    │ 상우    │
│ 1-5     │ 6-10    │ 11-15   │
│ 1개 ✓   │ 2개 ○   │ 0개 ✗   │
│ 최근:9회│ 최근:7회│ 최근:5회│
├─────────┼─────────┼─────────┤
│ 중좌    │ 중중    │ 중우    │
│ 16-20   │ 21-25   │ 26-30   │
│ 2개 ○   │ 1개 ✓   │ 0개 ✗   │
│ 최근:6회│ 최근:11회│최근:8회│
├─────────┼─────────┼─────────┤
│ 하좌    │ 하중    │ 하우    │
│ 31-35   │ 36-40   │ 41-45   │
│ 0개 ✗   │ 0개 ✗   │ 0개 ✗   │
│ 최근:4회│ 최근:3회│ 최근:6회│
└─────────┴─────────┴─────────┘

균형: 편중 있음 (최다/최소: 2개 차이)
추천: 상우(0개→1), 하단 영역 1~2개 추가
```

### 구현 예상 시간: 1.5시간

---

## Phase 3: 로또용지 평가

### 목표
사용자가 저장한 **개별 조합(Lottery Sheets)**을 자동 평가

### 구현 단계

#### 1단계: 로또용지 저장 구조 (Supabase)

**새 테이블: `user_lottery_sheets`**

```sql
CREATE TABLE user_lottery_sheets (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL,
  name VARCHAR(100),          -- "조합 A", "12월 추천" 등
  numbers INT[],              -- [1, 12, 23, 34, 39, 45]
  created_at TIMESTAMP,
  notes TEXT                  -- 사용자 메모
);
```

#### 2단계: 백엔드 평가 함수 (deep_analysis_v3.py 라인 600)

```python
async def evaluate_lottery_sheet(sheet_id: str, sheet_numbers: list, model_contributions: dict):
    """개별 로또용지 평가"""

    # 1. 각 모델의 점수 계산
    scores = {}
    for model in ["lstm", "xgboost", "cnn", "transformer", "markov"]:
        model_probs = model_contributions.get(model, {})
        sheet_prob = sum(model_probs.get(int(n), 0) for n in sheet_numbers)
        scores[model] = int(min(100, sheet_prob * 100 * 1.25))

    overall_score = int(sum(scores.values()) / 5)

    # 2. 필터 준수도 평가
    filter_compliance = {}
    for filter_name in ["sum", "ac", "odd", "high", "tail_sum", "prime", "composite", "consecutive", "square", "triangular", "twin", "mul3", "mul4", "mul5"]:
        expected = get_model_filter_expectations(filter_name, model_contributions)
        actual = calculate_filter_value(sheet_numbers, filter_name)

        # 범위 내인지 확인
        in_range = False
        reason = ""

        if filter_name in ["sum", "tail_sum", "consecutive"]:
            exp_min = min([e["min"] for e in expected.values()])
            exp_max = max([e["max"] for e in expected.values()])
            if exp_min <= actual <= exp_max:
                in_range = True
                reason = f"적정 범위 ({exp_min}~{exp_max})"
            else:
                reason = f"부족" if actual < exp_min else "초과"
        else:
            # 개수 필터: 여러 모델 평균 확인
            avg_min = sum([e["min"] for e in expected.values()]) / 5
            avg_max = sum([e["max"] for e in expected.values()]) / 5
            if avg_min <= actual <= avg_max:
                in_range = True
                reason = f"적정"
            else:
                reason = f"부족" if actual < avg_min else "초과"

        filter_compliance[filter_name] = {
            "actual": actual,
            "expected_min": exp_min if filter_name in ["sum", "tail_sum"] else int(avg_min),
            "expected_max": exp_max if filter_name in ["sum", "tail_sum"] else int(avg_max),
            "in_range": in_range,
            "reason": reason
        }

    # 3. 종합 평가
    compliance_count = sum(1 for v in filter_compliance.values() if v["in_range"])
    compliance_ratio = compliance_count / len(filter_compliance)

    return {
        "sheet_id": sheet_id,
        "numbers": sheet_numbers,
        "overall_score": overall_score,
        "model_scores": scores,
        "filter_compliance": filter_compliance,
        "compliance_ratio": int(compliance_ratio * 100),
        "recommendation": generate_sheet_recommendation(scores, filter_compliance)
    }
```

#### 3단계: 프론트엔드 로또용지 관리 (ai_deep_learning.html 라인 800)

**로또용지 목록 UI:**

```html
<div class="section">
  <h3>📋 내 로또용지</h3>

  <button id="add-sheet-btn">+ 새 조합 저장</button>

  <div id="sheets-list">
    <!-- 동적으로 생성됨 -->
  </div>
</div>

<!-- 로또용지 카드 템플릿 -->
<template id="sheet-card-template">
  <div class="sheet-card">
    <div class="sheet-header">
      <h4 id="sheet-name">조합 A</h4>
      <span class="overall-score" id="sheet-score">77점</span>
    </div>

    <div class="sheet-numbers">
      <span class="number-ball">12</span>
      <span class="number-ball">23</span>
      <!-- ... 기타 번호 -->
    </div>

    <div class="model-scores">
      <div>🔷 LSTM: <strong>82점</strong></div>
      <div>🔶 XGB: <strong>65점</strong></div>
      <div>🔹 CNN: <strong>78점</strong></div>
      <div>🟢 Trans: <strong>88점</strong></div>
      <div>🟦 Markov: <strong>71점</strong></div>
    </div>

    <div class="filter-compliance">
      <h5>필터 준수도: <strong id="compliance">71%</strong></h5>
      <div class="compliance-items">
        <span class="ok">✓ 합계</span>
        <span class="warning">⚠ 홀짝</span>
        <span class="bad">✗ 저고</span>
        <!-- 기타 -->
      </div>
    </div>

    <div class="sheet-actions">
      <button class="detail-btn">상세보기</button>
      <button class="edit-btn">수정</button>
      <button class="delete-btn">삭제</button>
    </div>
  </div>
</template>
```

**JavaScript:**

```javascript
async function loadLotterySheets() {
  const response = await fetch('/api/deep-analysis/v3/lottery-sheets');
  const data = await response.json();

  const container = document.getElementById('sheets-list');
  container.innerHTML = '';

  for (const sheet of data.sheets) {
    const template = document.getElementById('sheet-card-template');
    const card = template.content.cloneNode(true);

    card.getElementById('sheet-name').textContent = sheet.name;
    card.getElementById('sheet-score').textContent = `${sheet.overall_score}점`;
    card.getElementById('compliance').textContent = `${sheet.compliance_ratio}%`;

    // 번호 표시
    const numbersDiv = card.querySelector('.sheet-numbers');
    numbersDiv.innerHTML = sheet.numbers.map(n => `<span class="number-ball">${n}</span>`).join('');

    // 모델별 점수 표시
    const modelScores = card.querySelector('.model-scores');
    const scores = sheet.model_scores;
    modelScores.innerHTML = `
      <div>🔷 LSTM: <strong>${scores.lstm}점</strong></div>
      <div>🔶 XGB: <strong>${scores.xgboost}점</strong></div>
      <div>🔹 CNN: <strong>${scores.cnn}점</strong></div>
      <div>🟢 Trans: <strong>${scores.transformer}점</strong></div>
      <div>🟦 Markov: <strong>${scores.markov}점</strong></div>
    `;

    container.appendChild(card);
  }
}
```

### 예상 화면

```
📋 내 로또용지
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

조합 A (12월 추천)                     77점
────────────────────────────────────
[12] [23] [34] [39] [40] [45]

모델별 평가:
🔷 LSTM:       82점 ██████████░░
🔶 XGBoost:    65점 ████████░░░░
🔹 CNN:        78점 █████████░░░
🟢 Transformer: 88점 ███████████░░
🟦 Markov:     71점 ███████░░░░░

필터 준수도: 71% (10/14 필터 준수)
✓ 합계 ✓ AC값 ⚠ 홀짝 ✗ 저고 ✓ 끝수합
✓ 소수 ✓ 합성수 ✓ 연속 ✗ 제곱수 ⚠ 삼각수
✓ 쌍둥이 ✓ 3배수 ✓ 4배수 ✗ 5배수

💡 개선 권장:
   - 저번호 1~2개 추가 (현재 저번호 1개 부족)
   - 홀수 1개 추가 (홀짝 비율 조정)
   - 5배수 1개 추가 (5배수 부족)

[상세보기] [수정] [삭제]
```

### 구현 예상 시간: 1.5시간

---

## 일정 & 우선순위

### 우선순위 매트릭스

| Phase | 난이도 | 가치 | 유지보수 | 시간 | 우선순위 |
|-------|--------|------|---------|------|---------|
| 1.5 (Hot/Cold) | ⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | 1h | **1순위** |
| 2 (9궁) | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | 1.5h | 2순위 |
| 3 (로또용지) | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | 1.5h | 3순위 |

### 실행 계획

```
Week 1:
  [✅ DONE] Phase 1: mul4, mul5 필터 추가
  [ TODO ] Phase 1.5: Hot/Cold 분석 (1시간)
  [ TODO ] Phase 2: 9궁 분석 (1.5시간)

Week 2:
  [ TODO ] Phase 3: 로또용지 평가 (1.5시간)
  [ TODO ] 통합 테스트 & 버그 수정
  [ TODO ] 사용자 피드백 수집

Week 3+:
  [ PLAN ] 고급 기능 추가
  [ PLAN ] 성능 최적화
  [ PLAN ] 모바일 대응
```

---

## 📊 누적 진행률

```
Phase 1:   ████████████████████ 100% ✅
           (mul4, mul5 필터 추가)

Phase 1.5: ░░░░░░░░░░░░░░░░░░░░   0% ⏳
           (Hot/Cold 분석)

Phase 2:   ░░░░░░░░░░░░░░░░░░░░   0% ⏳
           (9궁 분석)

Phase 3:   ░░░░░░░░░░░░░░░░░░░░   0% ⏳
           (로또용지 평가)

Total:     █████░░░░░░░░░░░░░░░  25% 진행 중
```

