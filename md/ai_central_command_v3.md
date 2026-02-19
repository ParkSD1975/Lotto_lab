# 📘 Project: Lotto Lab - AI Central Command Center (Deep Learning v3)

> **Concept:** Dark Mode & Glassmorphism (압도적 전문성의 AI 연구소)  
> **Core Philosophy:** "Hybrid Intelligence" (딥러닝의 예측력 + 통계의 검증력)  
> **Goal:** 5대 딥러닝 모델(LSTM, Transformer, CNN, XGB, Markov)의 분석을 통합 관제하고, 최종 당첨 번호를 생성하는 최상위 컨트롤 타워 구축.

---

## 1. UI/UX 디자인 철학 (Visual Identity)

* **Theme:** **Deep Dark Mode** (`bg-slate-900`)를 베이스로 하여, 데이터의 가독성과 몰입감을 극대화.
* **Effect:** **Glassmorphism (유리 질감)** 패널을 사용하여 미래지향적인 느낌 부여.
    * *Backdrop Blur*: 배경의 흐릿한 투과 효과.
    * *Neon Glow*: 중요 수치(Top Pick, 적중률)에 Cyan, Magenta, Lime 등의 네온 컬러 포인트 사용.
* **Layout:** **LNB (Left Navigation Bar)** + **Single Page Scroll** (섹션별 스무스 스크롤).

---

## 2. 화면 구성 및 기능 명세 (Section Breakdown)

### ① 🎛️ 통합 관제 대시보드 (Main Dashboard)
* **목적:** 현재 AI 시스템의 상태와 이번 회차 예측의 신뢰도(Confidence) 브리핑.
* **주요 컴포넌트:**
    * **Model Confidence Radar:** 5개 모델의 이번 회차 예측 확신도를 레이더 차트로 비교. (예: "이번엔 XGBoost가 92% 확신 중")
    * **Ensemble Weight Pie:** 최종 결과에 반영된 각 모델의 가중치 비율.
    * **System Status:** 마지막 학습 시간, 데이터 동기화 상태, AI 엔진 가동 상태 표시 (System Online / Training...).

### ② 🔢 딥러닝 매트릭스 (The Matrix: 1~45 Analysis)
* **목적:** 1번부터 45번까지 **"각 모델은 이 숫자를 어떻게 평가했는가?"**를 정밀 타격.
* **구성 (Data Grid):**
    * **Row:** 1 ~ 45번 숫자.
    * **Col:** Total Score | LSTM | Transformer | XGBoost | CNN | Markov.
    * **Visual:** 수치(0~100)와 함께 **히트맵(Heatmap) 바**를 적용하여, 모델별 선호도를 색상 농도로 표현.
* **인터랙션:**
    * 숫자 클릭 시 해당 숫자의 **최근 10회차 적중 이력** 팝업 표시.
    * 헤더 클릭 시 특정 모델(예: CNN) 점수 기준으로 정렬.

### ③ 🧪 피처 역설계 연구소 (Feature Prediction Lab)
* **목적:** **"그래서 각 모델은 이번 회차 패턴을 어떻게 보고 있는가?"** (핵심 차별화 기능)
* **기능 정의:** 모델이 예측한 상위 번호들을 역산(Reverse Engineering)하여 패턴을 추정.
* **분석 항목 (Cards):**
    * **총합(Sum) 예측:** "LSTM은 130~140 구간을 보지만, Markov는 100 이하를 예측함."
    * **홀짝(Odd:Even):** "Transformer와 XGBoost 모두 4:2 패턴에 만장일치."
    * **고저(High:Low):** 각 모델의 고저 비율 예측 분포.
* **가치:** 사용자가 "나는 이번에 LSTM의 감을 믿겠다"고 판단하면, LSTM이 선호하는 합계/홀짝 범위를 필터로 적용 가능.

### ④ 🌟 최종 AI 생성 (Final Generation)
* **목적:** 분석된 데이터를 바탕으로 실전 조합 생성.
* **구성:**
    * **AI Picks:**
        * **Strong Recommend (Top 6):** 앙상블 점수 최상위.
        * **Risk / Exclude (Bottom 6):** 앙상블 점수 최하위 (제외수 추천).
    * **Combination Generator:**
        * 자동 생성된 10게임 리스트.
        * 각 조합별 **AI Score** 및 **특징 태그** 표시 (예: `#안전지향`, `#XGB선호`).
    * **Validation Check:** 생성된 조합이 기초 통계(AC값, 합계 등)를 통과했는지 O/X 표시.

---

## 3. 백엔드 로직 설계 (Python/FastAPI)

### 3.1. API Endpoint: `GET /api/deep-analysis/v3/analysis`
단 하나의 API로 모든 시각화 데이터를 제공하여 프론트엔드 성능 최적화.

### 3.2. 데이터 처리 흐름 (Process Flow)
1.  **Data Loading:** `lotto_draws`에서 전체 이력 로드.
2.  **Model Prediction (Parallel):** 5개 모델의 `.predict()` 메서드 동시 실행.
3.  **Score Normalization:** 각 모델의 출력값(Probability)을 0~100 스케일로 정규화.
4.  **Feature Reverse Engineering (신규 로직):**
    * 각 모델의 상위 10개 번호 추출.
    * 추출된 번호 조합의 **Sum, Odd/Even, AC** 등을 계산.
    * 프론트엔드로 전송할 `feature_analysis` 객체 생성.
5.  **Ensemble & Generation:**
    * 가중치 적용하여 최종 확률 계산.
    * `CombinationGenerator`를 통해 10개 조합 생성.

---

## 4. 프론트엔드 기술 스택 (UI Stack)

* **Framework:** HTML5 + Vanilla JS (속도 최우선).
* **Styling:** **Tailwind CSS** (Dark Mode, Gradients, Blur 효과).
* **Chart Lib:** **Chart.js** (Radar, Doughnut 차트 커스터마이징).
* **Icons:** Google Material Symbols (Outlined 스타일).
* **Fonts:** `Pretendard` (본문), `JetBrains Mono` (수치 데이터).

---

## 5. 기대 효과

1.  **신뢰성 확보:** 블랙박스였던 딥러닝 결과를 **"모델별/숫자별 점수표"**로 투명하게 공개하여 사용자 신뢰도 상승.
2.  **전략적 선택:** 맹목적인 추천이 아니라, 사용자가 특정 모델(예: 최근 적중률 좋은 CNN)의 의견을 선택적으로 수용 가능.
3.  **시각적 압도:** 기존의 분석 사이트와 차별화된 **"연구소/관제센터"** 컨셉의 디자인으로 프리미엄 이미지 구축.
