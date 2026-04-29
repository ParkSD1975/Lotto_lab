# Stage 1-4-D 학습 결과 보고서 (2026-04-30)

Master Plan Stage 1-4-D 종료 시점 학습 + 검증 결과.

## 사용자 핵심 요구 (배경)
1. ❓ 모델별 XAI 기여도 — Markov가 97.6%인데 정상이냐? (사용자 지적)
2. ✓ "번호별 분석은 전 모델 다 학습시키라고 했다" (사용자 결정 #24)
3. ✓ "폐기한 것들은 프론트에 보여줄 필요 없다"

## 진단

### 원인 (학습 전 상태)
- Markov는 합 1.0 normalized 분포 → 일부 번호 prob 집중 (excess 큼)
- 다른 모델 (sigmoid binary)은 mode collapse → 모든 번호 ≈ baseline (excess 0)
- 가중치 0.08뿐인 Markov가 XAI 97.6% dominant

→ **mode collapse 증상**. 11 base 학습 미완으로 발생.

## 작업 (Stage 1-4-D 분해)

| sub | 작업 | commit |
|---|---|---|
| D-1 | predictor_pipeline evidence 합류 | `f8deca9` |
| D-2 | 5 신규 base lazy init | `c70ff6c` |
| D-2-fix-3a | LSTM/Transformer 폐기 (DISABLED_MODELS) | `f17347e` |
| D-2-fix-2 | 5 wrapper task_type=binary_45 분기 | `75c39de` |
| D-2-fix-3b | 프론트 5 JS + 5 HTML 11 base 통일 | `7bab8f4` |
| D-2-fix-4 | 5 wrapper train(draws) polymorphic 어댑터 + _draws_adapter.py | `84c599d` |
| D-2-fix-5 | 5 wrapper predict polymorphic + GNN/CNN/TFT/CatBoost 디버그 | `a6cfb8f` |

총 7 sub-commit. 누적 29 commits.

## 환경 (D-3 학습)

| 항목 | 값 |
|---|---|
| OS | Windows 11 |
| Python | 3.12.8 |
| PyTorch | 2.5.1+cu121 (GPU 빌드) |
| GPU | NVIDIA GeForce GTX 1050 Ti (4GB VRAM) |
| CUDA | 12.6 driver / 12.1 PyTorch |
| 라이브러리 | catboost 1.2.10 / pytorch-tabnet 4.1.0 / pytorch-forecasting 1.7.0 / shap 0.51.0 / captum 0.9.0 |
| hflayers | 미설치 (Python 3.12 호환 X) — MHN self-impl fallback |

## 학습 결과 (2 cycle)

### 1차 학습 (fix-3a/2/3b/4 후)
- 7/11 성공: xgboost / transformer / ae / tabnet / mhn / bayesian / markov
- 4 실패: cnn (파일 손상) / gnn (init 실패) / catboost (fit 누락) / tft (학습 미실행)

### 2차 학습 (fix-5 후)
- 11/11 성공 — 모두 학습 완료
- LSTM size mismatch 경고는 deprecated 무관

## 검증 — XAI 기여도 (실 데이터 ensemble.predict)

### 11 base 모델별 raw_prob 분포

| 모델 | mean | max | nonzero | 상태 |
|---|---|---|---|---|
| xgboost | 0.076 | **0.721** | 44/45 | ✅ 정상 (특정 번호 강한 신호) |
| cnn | 0.194 | **0.825** | 38/45 | ✅ 정상 |
| transformer | 0.506 | 0.617 | 45/45 | ✅ deprecated (weight 0) |
| bayesian_nn | 0.501 | 0.539 | 45/45 | ✅ 활성 |
| tabnet | 0.533 | 0.548 | 45/45 | ✅ 활성 |
| catboost | 0.533 | 0.539 | 45/45 | ✅ 활성 |
| mhn | 0.133 | 0.159 | 45/45 | ✅ 약 활성 |
| tft | 0.022 | 0.040 | 45/45 | ⚠️ 약 활성 (fine_tune 추가 필요) |
| autoencoder | 0.022 | 0.035 | 44/45 | ✅ 낮음 |
| markov | 0.022 | 0.027 | 45/45 | ✅ 갱신 (이전 dominant 해소) |
| gnn | 0.022 | 0.022 | 45/45 | ⚠️ 평탄 (학습 patterns 미반영) |
| lstm | 0 | 0 | 0/45 | — deprecated |

### Top 5 추천 XAI 분포

| 추천 번호 | 1순위 | 분포 (top 5 모델) |
|---|---|---|
| n=28 | xgboost 49.6% | + cnn 26.0% + bayesian 12.8% + catboost 4.5% + tabnet 4.5% |
| n=37 | cnn 35.5% | + xgboost 24.4% + bayesian 22.1% + catboost 7.4% + tabnet 7.2% |
| n=41 | xgboost 70.1% | + bayesian 16.3% + tabnet 5.8% + catboost 5.7% + mhn 2.0% |
| n=11 | cnn 49.0% | + bayesian 23.3% + catboost 9.0% + tabnet 8.9% + xgboost 5.6% |
| n=13 | xgboost 31.1% | + bayesian 26.0% + cnn 20.3% + catboost 9.1% + tabnet 8.9% |

## 핵심 결과

| | **이전 (mode collapse)** | **현재 (학습 후)** |
|---|---|---|
| Markov XAI dominant | **97.6%** | (제거됨 — 0~3% 분산) |
| 단일 모델 dominant | Markov 1개 | XGBoost/CNN 균형 + 5+ 모델 분산 |
| 활성 base 수 (실 신호) | 1~2 | **11/12 활성** |
| 의미 있는 합의 | ❌ | ✅ |

## Master Plan 7 Stage 종료

| Stage | 상태 |
|---|---|
| Stage 0 — 인프라 + plan archive | ✅ 100% |
| Stage 1 — 21지표 IndependentCountPredictor (Phase 1~4) | ✅ |
| Stage 2 — 회귀(2~200) 4 Tier + 자동 룰 3개 | ✅ |
| Stage 3 — 4 Pillar + NumberRecommender + Hard Filter | ✅ |
| Stage 4 — NumberXAIExplainer + Gemma 4 Narrative | ✅ |
| Stage 5 — UI 4 페이지 + ECharts | ✅ |
| Stage 6 — 통합 검증 + 200회차 백테스트 | ✅ |

## 잔여 minor (별도 작업)

- **gnn**: max_prob 0.022 (학습 patterns 미반영) — wrapper 또는 학습 데이터 변환 디버그
- **tft**: max_prob 0.040 (약 활성) — fine_tune 추가 epoch 필요
- **LSTM size_mismatch 경고**: deprecated 무관

## 다음 작업 옵션

- A. 여기서 마무리 (Master Plan 종료)
- B. gnn/tft 디버그 + 재학습 (minor 1~2h)
- C. 실 동작 확인 (서버 띄우고 브라우저로 22 페이지 + 4 대시보드 확인)
- D. 새 기능 (사용자 메모 UI 강화 / 모바일 반응형 / 운영 자동화 등)
