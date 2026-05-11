# P3. WeeklyPipelineV2 추론 시점 가중치 갱신 패치

> **대상 파일**: `lotto-ai-backend/pipeline/weekly_pipeline_v2.py`  
> **목적**: 매 회차 추론 직전 ensemble 가중치 재계산 활성화  
> **근거**: `Lotto_lab_Root_Cause_Diagnosis.md` Finding #3  
> **예상 시간**: 2시간 (코드 + 백테스트)

---

## 🎯 문제 요약

### 현재 상태
- `self.ensemble = LottoEnsemble()` — `__init__`에서 한 번만 초기화
- `_update_meta_weights()`는 `train_all()` 안에서만 호출됨
- 매 회차 추론 시 **가중치 갱신 없음** → 회차 간 가중치 거의 동일
- 실측 데이터: 회차 1222와 1223의 model_weights 정확히 동일

### 패치 후 기대
- 매 회차 추론 직전 가중치 재계산
- 회차별 성능 반영된 동적 가중치
- EMA 평활화로 변동성 흡수

---

## 📝 변경 사항 (3가지)

### 변경 1. **`__init__`에 EMA 가중치 보관 필드 추가** (선택, 안정성용)
### 변경 2. **`_run_analysis()` 시작 부분에 가중치 갱신 호출 추가**
### 변경 3. **로깅 추가**

---

## 💻 패치 코드

### 변경 1: `__init__` 메서드 (옵션 — EMA용)

**위치**: 클래스 `__init__` 메서드 끝부분

**Before**:
```python
def __init__(self):
    self.supabase = get_client()
    self.ensemble = LottoEnsemble()

    # Master Plan Stage 1-4-E: predictor_pipeline 통합
    try:
        from predictors.predictor_pipeline import PredictorPipeline
        self.predictor_pipeline = PredictorPipeline(feature_dim=24)
    except Exception as e:
        logger.warning(f"  [WeeklyPipelineV2] predictor_pipeline init fail (skip): {e}")
        self.predictor_pipeline = None
```

**After**:
```python
def __init__(self):
    self.supabase = get_client()
    self.ensemble = LottoEnsemble()

    # Master Plan Stage 1-4-E: predictor_pipeline 통합
    try:
        from predictors.predictor_pipeline import PredictorPipeline
        self.predictor_pipeline = PredictorPipeline(feature_dim=24)
    except Exception as e:
        logger.warning(f"  [WeeklyPipelineV2] predictor_pipeline init fail (skip): {e}")
        self.predictor_pipeline = None

    # [P3 PATCH] EMA 평활화 — 회차 간 가중치 변동 흡수
    # 근거: Lotto_lab_Root_Cause_Diagnosis.md (Finding #3)
    self._prev_weights: dict | None = None
    self._ema_alpha: float = 0.85  # 0.85 = 기존 85%, 신규 15% 반영
```

---

### 변경 2: `_run_analysis()` 시작 부분에 가중치 갱신 추가

**위치**: `_run_analysis()` 메서드 안, B0 블록 **직전** (또는 B0 다음)

**찾을 위치** (대략 line 145):
```python
def _run_analysis(self, draws: list, target_round: int) -> dict:
    """
    전체 분석 실행.
    ...
    """
    # ── B0. predictor_pipeline 학습/추론 (Master Plan Stage 1-4-E) ──────
    ...
```

**다음과 같이 변경** (B0 직전에 [P3 PATCH] 블록 삽입):

```python
def _run_analysis(self, draws: list, target_round: int) -> dict:
    """
    전체 분석 실행.

    [P3 PATCH] 추론 직전 ensemble 가중치 재계산 추가.

    Returns dict with keys:
      prediction, contribs, xai, top5_result, excl_result,
      final_probs, range_analysis, regression_analysis, combinations,
      predictor_pipeline_outputs (Master Plan Stage 1-4-E 신설)
    """
    # ── [P3 PATCH] 추론 시점 ensemble 가중치 재계산 ─────────────────────────
    # 근거: 회차별 model_performance_log 기반 동적 가중치 적용
    # EMA 평활화: 0.85 × 기존 + 0.15 × 신규
    logger.info(f"  [P3] ensemble 가중치 재계산 (target_round={target_round})...")
    try:
        # _update_meta_weights() 호출 (모델 재학습 없이 가중치만 갱신)
        if hasattr(self.ensemble, "_update_meta_weights"):
            # 신규 가중치 계산
            new_weights = self.ensemble._update_meta_weights()

            # EMA 평활화 적용
            if self._prev_weights is not None and new_weights:
                smoothed = {}
                all_keys = set(self._prev_weights.keys()) | set(new_weights.keys())
                for k in all_keys:
                    prev_v = self._prev_weights.get(k, 0.0)
                    new_v = new_weights.get(k, 0.0)
                    smoothed[k] = self._ema_alpha * prev_v + (1 - self._ema_alpha) * new_v
                # 재정규화
                total = sum(smoothed.values()) or 1.0
                smoothed = {k: v / total for k, v in smoothed.items()}

                # ensemble에 반영 (속성 이름은 LottoEnsemble 구현에 따라 조정)
                if hasattr(self.ensemble, "current_weights"):
                    self.ensemble.current_weights = smoothed
                elif hasattr(self.ensemble, "weights"):
                    self.ensemble.weights = smoothed
                elif hasattr(self.ensemble, "meta_weights"):
                    self.ensemble.meta_weights = smoothed

                self._prev_weights = smoothed
                logger.info(f"  [P3] EMA 적용 후 weights (top3): "
                            f"{dict(sorted(smoothed.items(), key=lambda kv: -kv[1])[:3])}")
            else:
                # 첫 회차 — EMA 적용 안 함
                self._prev_weights = new_weights
                logger.info(f"  [P3] 초기 weights: "
                            f"{dict(sorted((new_weights or {}).items(), key=lambda kv: -kv[1])[:3])}")
        else:
            logger.warning("  [P3] ensemble._update_meta_weights() 없음 — 스킵")
    except Exception as e:
        logger.warning(f"  [P3] 가중치 갱신 실패 (기존 가중치 유지): {e}")
    # ── /P3 PATCH ──────────────────────────────────────────────────────────

    # ── B0. predictor_pipeline 학습/추론 (Master Plan Stage 1-4-E) ──────
    # Phase 1~4 22 predictor — filter_stats ml_recommendation 입력 제공
    predictor_pipeline_outputs = None
    if self.predictor_pipeline is not None:
        ...
```

---

### 변경 3: (옵션) 로깅 강화 — `_save_to_weekly_tables` 진입 전

**위치**: `run()` 메서드 안, Phase C 직전

선택 사항 — 디버깅 강화용. 현재 가중치 상태를 명시적으로 로깅:

```python
# Phase B 다음, Phase C 직전
logger.info(f"  [P3] 현재 ensemble 가중치 (저장 전):")
if hasattr(self.ensemble, "current_weights"):
    w = self.ensemble.current_weights
elif hasattr(self.ensemble, "weights"):
    w = self.ensemble.weights
else:
    w = {}
for k, v in sorted(w.items(), key=lambda kv: -kv[1])[:5]:
    logger.info(f"      {k}: {v:.4f}")
```

---

## 🧪 검증 절차

### 1. Smoke 테스트 (단일 회차)
```bash
cd lotto-ai-backend
python -m pipeline.weekly_pipeline_v2 --round 1224
```

**로그 확인 사항**:
```
[P3] ensemble 가중치 재계산 (target_round=1224)...
[P3] 초기 weights: {'xgboost': 0.18, 'tft': 0.16, ...}
```

### 2. 3회차 연속 실행 → 가중치 변동 확인
```bash
python -m pipeline.weekly_pipeline_v2 --round 1222
python -m pipeline.weekly_pipeline_v2 --round 1223
python -m pipeline.weekly_pipeline_v2 --round 1224
```

**기대**: 회차마다 가중치가 EMA 적용되어 점진 변화

### 3. SQL 검증
```sql
SELECT
  target_round,
  model_weights->'xgboost' as w_xg,
  model_weights->'tft' as w_tft,
  model_weights->'gnn' as w_gnn,
  model_weights->'catboost' as w_cb
FROM weekly_predictions
WHERE target_round BETWEEN 1222 AND 1224
ORDER BY target_round;
```

**기대 결과** (패치 후):
```
target_round | w_xg  | w_tft | w_gnn | w_cb
─────────────┼───────┼───────┼───────┼──────
   1222      | 0.232 | 0.199 | 0.139 | 0.084
   1223      | 0.228 | 0.198 | 0.142 | 0.086    ← 약간 변동 (EMA)
   1224      | 0.226 | 0.197 | 0.143 | 0.087    ← 변동 지속
```

패치 전엔 3회차 모두 동일 값이었음 → 변동이 보이면 성공.

### 4. 50회 백테스트
```bash
python -m pipeline.weekly_pipeline_v2 --backtest --rounds 1173-1222
```

회차별 가중치 변동 + Top-5 hit 향상 확인.

---

## ⚠️ 주의 사항

### 1. **`_update_meta_weights()` 메서드 존재 확인**
`models/ensemble.py`에서 이 메서드가 실제로 가중치 dict을 반환하는지 확인 필요:
```bash
grep -n "_update_meta_weights" lotto-ai-backend/models/ensemble.py
```

만약 반환값이 없으면 (`None`이면), 패치를 다음과 같이 조정:
```python
# Before (반환값 사용)
new_weights = self.ensemble._update_meta_weights()

# After (속성 직접 읽기)
self.ensemble._update_meta_weights()
new_weights = getattr(self.ensemble, "current_weights", None) \
            or getattr(self.ensemble, "weights", None) \
            or {}
```

### 2. **EMA alpha 튜닝**
| alpha | 효과 |
|-------|------|
| 0.95 | 매우 안정적, 변동 적음 (보수적) |
| **0.85** | 기본값 (적당한 안정성) |
| 0.7 | 빠른 적응, 변동 큼 |
| 0.5 | 매 회차 거의 절반 갱신 |

패치는 0.85로 시작. 백테스트 후 조정.

### 3. **첫 실행 시 EMA 미적용**
`self._prev_weights is None`이면 EMA 안 함. 정상.

### 4. **모델 재학습 트리거 X**
`_update_meta_weights()`만 호출하므로 모델 학습은 안 됨. **추론 가중치만 조정**.  
모델 재학습은 별도 cron이나 train_all() 호출 시점에 진행.

### 5. **predict_top5() 등이 self.ensemble 가중치를 자동 사용해야 함**
LottoEnsemble의 predict 메서드들이 현재 가중치를 어떻게 참조하는지 확인:
- `self.weights[model]`로 직접 참조 → 자동 반영 ✅
- 매번 파일에서 로드 → 효과 없음 (별도 패치 필요)

---

## 🔄 롤백 절차

```bash
cd lotto-ai-backend
git checkout pipeline/weekly_pipeline_v2.py
```

---

## ✅ 적용 체크리스트

```
□ 백업 (git branch)
□ __init__ 에 _prev_weights, _ema_alpha 필드 추가
□ _run_analysis 시작에 [P3 PATCH] 블록 삽입
□ Smoke 테스트: python -m pipeline.weekly_pipeline_v2 --round 1224
□ 로그에 [P3] 출력 확인
□ 3회차 연속 실행 후 가중치 SQL 비교
□ 회차별 변동 확인 (이전엔 동일 → 패치 후 점진 변화)
□ 50회 백테스트
□ Git commit
```

---

## 📝 Git Commit 메시지 예시

```
fix(pipeline): activate per-round ensemble weight update [P3]

- Call ensemble._update_meta_weights() before predictions in _run_analysis
- Add EMA smoothing (alpha=0.85) to absorb round-to-round variance
- Add _prev_weights field for EMA state
- Add logging for weight changes

Diagnosis: model_weights stayed static across rounds (1222 == 1223),
indicating no per-round adaptation. After patch, weights should drift
based on recent 20-round performance from model_performance_log.

Refs: Lotto_lab_Root_Cause_Diagnosis.md (Finding #3)
```

---

## 🔗 관련 문서

- `../Lotto_lab_Root_Cause_Diagnosis.md` — 진단 (Finding #3)
- `../Lotto_lab_Logic_Enhancements.md` — Phase 0 P3
- `README.md` — 전체 패치 가이드
- `P1_number_recommender.md` — 빈도 페널티 (먼저 적용)
- `P2_performance_fallback.md` — Fallback 가중치
