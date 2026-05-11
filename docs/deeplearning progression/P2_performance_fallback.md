# P2. Performance Fallback 가중치 11-base 교체 패치

> **대상 파일**: `lotto-ai-backend/routes/performance.py`  
> **목적**: DB 조회 실패 시 fallback에 deprecated LSTM 35% 박혀 있는 문제 수정  
> **근거**: `Lotto_lab_Root_Cause_Diagnosis.md` Finding #4  
> **예상 시간**: 10분

---

## 🎯 문제 요약

### 현재 상태 (line ~50, 52)
```python
return {"lstm": 0.35, "xgboost": 0.40, "markov": 0.25}
```

- `lstm`: 11-base 체계에서 **archive (deprecated)** 됨
- 11-base 모델 중 **3개만** 포함 (나머지 8개 누락)
- 합 = 1.0이지만 정상 모델 분배 아님

### Fallback 발동 시나리오
1. `ai_predictions` 테이블 비어있음 (신규 회차)
2. DB 조회 예외 (네트워크/타임아웃)
3. `ensemble_weights` 컬럼이 NULL

→ 위 3가지 상황에서 시스템이 **deprecated 모델 35% 비중으로 작동**

---

## 📝 변경 사항 (2가지)

### 변경 1. 모듈 상단에 `DEFAULT_WEIGHTS` 상수 추가
### 변경 2. `get_ensemble_weights()` 내부 2곳 fallback 교체

---

## 💻 패치 코드 (그대로 복사)

### 전체 파일 (변경 후)

```python
from fastapi import APIRouter
from typing import List, Dict, Any
from db.supabase_client import get_client

router = APIRouter(
    prefix="/api/performance",
    tags=["Performance"]
)

# ──────────────────────────────────────────────────────────────────────
# [P2 PATCH] 11-base 정합 fallback 가중치
# 근거: Lotto_lab_Root_Cause_Diagnosis.md (Finding #4)
# 패치 일자: 2026-05-11
#
# 변경 이유:
#   - 기존 fallback (lstm/xgboost/markov 3개)에서
#     LSTM이 deprecated 됐는데 35% 비중 유지
#   - 11-base 중 8개 모델이 fallback에 누락
#
# 변경 후:
#   - 11-base 11개 모델 전체 포함
#   - LSTM, Transformer 제외 (deprecated)
#   - 합 = 1.0 정규화
# ──────────────────────────────────────────────────────────────────────
DEFAULT_WEIGHTS: Dict[str, float] = {
    "xgboost":     0.15,
    "catboost":    0.12,
    "tabnet":      0.08,
    "cnn":         0.10,
    "gnn":         0.13,
    "markov":      0.09,
    "autoencoder": 0.05,
    "tft":         0.15,
    "mhn":         0.05,
    "bayesian_nn": 0.05,
    "nbeats":      0.03,
}
# Sanity check: sum should be ~1.0
assert abs(sum(DEFAULT_WEIGHTS.values()) - 1.0) < 0.001, \
    f"DEFAULT_WEIGHTS sum != 1.0: {sum(DEFAULT_WEIGHTS.values())}"


@router.get("/summary")
async def get_performance_summary():
    """모델별 평균 적중률 요약."""
    supabase = get_client()

    # 최근 20회차 데이터 기준 성능 평균 계산 (DB 함수 대신 파이썬에서 집계)
    response = supabase.table("model_performance_log")\
        .select("model_name, hit_count, round")\
        .order("round", desc=True)\
        .limit(100)\
        .execute()

    data = response.data
    summary = {}

    for row in data:
        model = row['model_name']
        if model not in summary:
            summary[model] = {'total_hits': 0, 'count': 0, 'rounds': []}

        summary[model]['total_hits'] += row['hit_count']
        summary[model]['count'] += 1
        summary[model]['rounds'].append(row['round'])

    result = []
    for model, stats in summary.items():
        avg_hit = stats['total_hits'] / stats['count'] if stats['count'] > 0 else 0
        result.append({
            "model_name": model,
            "avg_hit": round(avg_hit, 2),
            "sample_size": stats['count'],
            "last_round": max(stats['rounds']) if stats['rounds'] else 0
        })

    return result


@router.get("/weights")
async def get_ensemble_weights():
    """현재 앙상블 모델 가중치 조회.

    우선순위:
      1. ai_predictions 최신 레코드의 ensemble_weights
      2. DEFAULT_WEIGHTS (11-base 정합 fallback)  ← [P2 PATCH]
    """
    try:
        supabase = get_client()
        # ai_predictions 테이블의 최신 레코드에서 가중치 정보 추출
        response = supabase.table("ai_predictions")\
            .select("ensemble_weights")\
            .order("created_at", desc=True)\
            .limit(1)\
            .execute()

        if response.data and response.data[0].get('ensemble_weights'):
            return response.data[0]['ensemble_weights']

        # [P2 PATCH] 기본값 반환 (11-base fallback)
        return DEFAULT_WEIGHTS
    except Exception:
        # [P2 PATCH] 예외 시 11-base fallback
        return DEFAULT_WEIGHTS
```

---

## 📋 변경 부분 요약 (diff)

```diff
 from fastapi import APIRouter
 from typing import List, Dict, Any
 from db.supabase_client import get_client

 router = APIRouter(
     prefix="/api/performance",
     tags=["Performance"]
 )

+# ──────────────────────────────────────────────────────────────────────
+# [P2 PATCH] 11-base 정합 fallback 가중치
+# ──────────────────────────────────────────────────────────────────────
+DEFAULT_WEIGHTS: Dict[str, float] = {
+    "xgboost":     0.15,
+    "catboost":    0.12,
+    "tabnet":      0.08,
+    "cnn":         0.10,
+    "gnn":         0.13,
+    "markov":      0.09,
+    "autoencoder": 0.05,
+    "tft":         0.15,
+    "mhn":         0.05,
+    "bayesian_nn": 0.05,
+    "nbeats":      0.03,
+}
+assert abs(sum(DEFAULT_WEIGHTS.values()) - 1.0) < 0.001
+

 @router.get("/summary")
 ...

 @router.get("/weights")
 async def get_ensemble_weights():
-    """현재 앙상블 모델 가중치 조회."""
-    # 실제로는 ensemble_weights.json 파일을 읽거나 DB에서 조회
+    """현재 앙상블 모델 가중치 조회.
+
+    우선순위:
+      1. ai_predictions 최신 레코드의 ensemble_weights
+      2. DEFAULT_WEIGHTS (11-base 정합 fallback)
+    """
     try:
         supabase = get_client()
         response = supabase.table("ai_predictions")\
             .select("ensemble_weights")\
             .order("created_at", desc=True)\
             .limit(1)\
             .execute()

         if response.data and response.data[0].get('ensemble_weights'):
             return response.data[0]['ensemble_weights']

-        # 기본값 반환
-        return {"lstm": 0.35, "xgboost": 0.40, "markov": 0.25}
+        return DEFAULT_WEIGHTS
     except Exception:
-        return {"lstm": 0.35, "xgboost": 0.40, "markov": 0.25}
+        return DEFAULT_WEIGHTS
```

---

## 🧪 검증 절차

### 1. Import 테스트
```bash
cd lotto-ai-backend
python -c "from routes.performance import DEFAULT_WEIGHTS; print(sum(DEFAULT_WEIGHTS.values())); print(DEFAULT_WEIGHTS)"
```

**기대 출력**:
```
1.0
{'xgboost': 0.15, 'catboost': 0.12, ..., 'nbeats': 0.03}
```

### 2. API 엔드포인트 테스트 (서버 실행 중일 때)
```bash
curl http://localhost:7860/api/performance/weights
```

**기대 응답** (DB 정상):
```json
{"xgboost": 0.2315, "tft": 0.1992, ...}    # DB의 동적 가중치
```

**기대 응답** (DB fallback):
```json
{"xgboost": 0.15, "catboost": 0.12, ..., "nbeats": 0.03}    # 새 fallback
```

### 3. Fallback 강제 발동 테스트 (선택)
ai_predictions 테이블 비운 상태 또는 DB 연결 차단 후:
```bash
curl http://localhost:7860/api/performance/weights
```

→ 11개 모델 fallback 응답 확인

---

## ⚠️ 주의 사항

### 1. **합 = 1.0 보장**
`assert` 줄이 모듈 import 시 합산 검증. 만약 가중치 조정 시 합이 안 맞으면 import 실패하므로 즉시 인지 가능.

### 2. **가중치 비율 근거**
| 모델 | 가중치 | 근거 |
|------|--------|------|
| xgboost, tft | 0.15 | 핵심 모델 (역사적 검증) |
| gnn, catboost | 0.12~0.13 | 관계/범주 강점 |
| cnn, markov | 0.09~0.10 | 보조 |
| tabnet | 0.08 | 신규, 검증 중 |
| autoencoder | 0.05 | 이상 탐지 보조 |
| mhn, bayesian_nn | 0.05 | 신규 |
| nbeats | 0.03 | 가장 신규 |

비율은 **임시 추정값**. 실제 운영 데이터 누적 후 `_update_meta_weights()`로 동적 보정됨. fallback은 어디까지나 비상용.

### 3. **이 패치만으로는 부족**
- fallback이 발동하는 빈도는 낮음 (정상 운영 시 DB에서 가중치 옴)
- 진짜 문제는 **P3 (추론 시 가중치 갱신 미작동)**
- P2는 비상망 정비, P3가 본 처치

### 4. **`ensemble_weights.json` 파일도 있을 수 있음**
주석에 "ensemble_weights.json 파일을 읽거나"라고 적혀 있음. 해당 파일도 LSTM이 포함됐는지 확인 필요:
```bash
find lotto-ai-backend -name "ensemble_weights.json" -exec cat {} \;
```

발견 시 동일하게 11-base로 교체 권장.

---

## 🔄 롤백 절차

```bash
cd lotto-ai-backend
git checkout routes/performance.py
```

---

## ✅ 적용 체크리스트

```
□ 백업 (git branch 또는 commit)
□ DEFAULT_WEIGHTS 상수 추가
□ fallback 2곳 교체 (line ~50, ~52)
□ import 테스트: from routes.performance import DEFAULT_WEIGHTS
□ assert 합=1.0 통과
□ /api/performance/weights 엔드포인트 테스트
□ (선택) ensemble_weights.json 파일 확인 및 교체
□ Git commit + 메시지에 패치 ID 포함
```

---

## 📝 Git Commit 메시지 예시

```
fix(performance): replace deprecated LSTM fallback with 11-base weights [P2]

- Remove hardcoded LSTM 35% from DEFAULT_WEIGHTS fallback
- Add 11-base model fallback (xgboost, catboost, tabnet, cnn, gnn,
  markov, autoencoder, tft, mhn, bayesian_nn, nbeats)
- Add module-level DEFAULT_WEIGHTS constant for DRY
- Add assert for sum validation

Refs: Lotto_lab_Root_Cause_Diagnosis.md (Finding #4)
```

---

## 🔗 관련 문서

- `../Lotto_lab_Root_Cause_Diagnosis.md` — 진단 (Finding #4)
- `../Lotto_lab_Logic_Enhancements.md` — Phase 0 P2
- `README.md` — 전체 패치 가이드
- `P1_number_recommender.md` — 빈도 페널티 (먼저 적용)
- `P3_weekly_pipeline.md` — 추론 시 가중치 갱신 (다음 패치)
