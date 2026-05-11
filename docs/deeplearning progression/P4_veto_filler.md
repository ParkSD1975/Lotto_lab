# P4. Veto 로직 활성화 패치

> **대상**: 신규 파일 `lotto-ai-backend/services/veto_filler.py` + 호출 통합  
> **목적**: `weekly_number_xai.veto` 컬럼 활성화 (현재 50회 모두 빈 값)  
> **근거**: `Lotto_lab_Root_Cause_Diagnosis.md` Finding #5  
> **예상 시간**: 2시간

---

## 🎯 문제 요약

### 현재 상태
- DB: `weekly_number_xai.veto` 컬럼 존재, 데이터 전부 빈 문자열
- 코드: `weekly_pipeline_v2.py`에서 `"veto": x.get("veto")` 저장만 함
- `x` (xai_contributions)에 veto 키가 거의 없어 None 저장됨

### 패치 후 기대
- 매 회차 11개 모델의 _rank 컬럼 기반으로 veto 자동 채움
- 값: `'safe'` / `'exclude:m1,m2,...'` / `'neutral:m1,...'`
- 추천수 5는 `veto='safe'` 번호 중에서만 선정 가능

---

## 📝 구현 전략

### 접근 방식
**Post-processing**: weekly_number_xai에 데이터 저장된 직후, _rank 컬럼을 읽어 veto 컬럼만 업데이트.

→ 기존 코드 최소 수정.  
→ 신규 파일 `services/veto_filler.py` + `weekly_pipeline_v2.py`에서 호출 1줄.

---

## 💻 신규 파일: `lotto-ai-backend/services/veto_filler.py`

전체 파일 내용 (그대로 생성):

```python
"""
[P4 PATCH] Veto Filler

weekly_number_xai.veto 컬럼 자동 채움.

근거: Lotto_lab_Root_Cause_Diagnosis.md (Finding #5)
패치 일자: 2026-05-11

원리:
    11개 모델(_rank 컬럼)에서 각 번호의 순위를 보고,
    rank >= 36 (하위 10) 모델이 일정 개수 이상이면 'exclude' 처리.
    
값 의미:
    'safe'                 — 어떤 모델도 하위 추천 안 함 (추천 후보)
    'exclude:m1,m2,...'    — 3개 이상 모델이 하위 추천 (강한 제외)
    'neutral:m1,...'       — 1~2개 모델만 하위 추천 (모호)
    NULL                   — 미평가 (legacy 또는 오류)
"""
from __future__ import annotations

import logging
from typing import Any

from db.supabase_client import get_client

logger = logging.getLogger("VetoFiller")


# 11-base 모델의 _rank 컬럼 명세
MODEL_RANK_COLUMNS: list[tuple[str, str]] = [
    ("xgboost",     "xgboost_rank"),
    ("catboost",    "catboost_rank"),
    ("tabnet",      "tabnet_rank"),
    ("cnn",         "cnn_rank"),
    ("gnn",         "gnn_rank"),
    ("markov",      "markov_rank"),
    ("autoencoder", "autoencoder_rank"),
    ("tft",         "tft_rank"),
    ("mhn",         "mhn_rank"),
    ("bayesian_nn", "bayesian_nn_rank"),
    # ("nbeats",      "nbeats_rank"),   # DB C3 패치 후 활성화
]

# 임계 파라미터
VETO_RANK_THRESHOLD: int = 36     # rank >= 36 = 하위 10개
VETO_MODEL_COUNT_HIGH: int = 3     # 이 이상 모델이 하위 추천 → exclude
VETO_MODEL_COUNT_MID: int = 1      # 이 이상 → neutral


def compute_veto_value(rank_dict: dict[str, int]) -> str:
    """
    단일 번호의 모델 rank 사전을 받아 veto 값 결정.
    
    Args:
        rank_dict: {'xgboost': 5, 'catboost': 38, ...}
    
    Returns:
        'safe' | 'exclude:m1,m2,...' | 'neutral:m1,...'
    """
    veto_models: list[str] = []
    for model_name, rank in rank_dict.items():
        if rank is None:
            continue
        try:
            r = int(rank)
        except (ValueError, TypeError):
            continue
        if r >= VETO_RANK_THRESHOLD:
            veto_models.append(model_name)
    
    if len(veto_models) >= VETO_MODEL_COUNT_HIGH:
        return "exclude:" + ",".join(sorted(veto_models))
    elif len(veto_models) == 0:
        return "safe"
    else:
        return "neutral:" + ",".join(sorted(veto_models))


def fill_veto_for_round(target_round: int) -> dict[str, Any]:
    """
    특정 회차의 weekly_number_xai 모든 행에 veto 컬럼 채움.
    
    Args:
        target_round: 대상 회차
    
    Returns:
        {
            'success': bool,
            'updated': int,        # 업데이트된 행 수
            'distribution': {'safe': n, 'exclude': n, 'neutral': n},
            'error': str | None,
        }
    """
    try:
        supabase = get_client()
        
        # SELECT 컬럼 구성
        rank_columns = [col for (_, col) in MODEL_RANK_COLUMNS]
        select_cols = "id, number, " + ", ".join(rank_columns)
        
        # 회차 데이터 조회
        response = supabase.table("weekly_number_xai") \
            .select(select_cols) \
            .eq("target_round", target_round) \
            .execute()
        
        rows = response.data or []
        if not rows:
            logger.warning(f"  [VetoFiller] No rows for target_round={target_round}")
            return {
                "success": False,
                "updated": 0,
                "distribution": {},
                "error": "no rows",
            }
        
        # 각 번호의 veto 계산
        distribution = {"safe": 0, "exclude": 0, "neutral": 0}
        updates = []
        
        for row in rows:
            rank_dict = {
                model_name: row.get(col_name)
                for (model_name, col_name) in MODEL_RANK_COLUMNS
            }
            veto = compute_veto_value(rank_dict)
            
            # 분포 카운트
            if veto == "safe":
                distribution["safe"] += 1
            elif veto.startswith("exclude:"):
                distribution["exclude"] += 1
            else:
                distribution["neutral"] += 1
            
            updates.append({"id": row["id"], "veto": veto})
        
        # 일괄 업데이트
        update_count = 0
        for upd in updates:
            try:
                supabase.table("weekly_number_xai") \
                    .update({"veto": upd["veto"]}) \
                    .eq("id", upd["id"]) \
                    .execute()
                update_count += 1
            except Exception as e:
                logger.warning(f"  [VetoFiller] update fail for id={upd['id']}: {e}")
        
        logger.info(
            f"  [VetoFiller] target_round={target_round} "
            f"updated={update_count}/{len(rows)} dist={distribution}"
        )
        
        return {
            "success": True,
            "updated": update_count,
            "distribution": distribution,
            "error": None,
        }
    
    except Exception as e:
        logger.error(f"  [VetoFiller] FAILED for target_round={target_round}: {e}")
        return {
            "success": False,
            "updated": 0,
            "distribution": {},
            "error": str(e),
        }


def get_safe_numbers(target_round: int, limit: int = 5) -> list[int]:
    """
    Veto='safe'인 번호 중 probability 상위 N개 반환.
    
    추천수 5 선정에 활용:
        - 어떤 모델도 거부 안 한 번호만
        - 그 중 종합 확률 가장 높은 N개
    
    Args:
        target_round: 대상 회차
        limit: 반환할 번호 개수 (기본 5)
    
    Returns:
        [번호1, 번호2, ...] (확률 내림차순)
    """
    try:
        supabase = get_client()
        response = supabase.table("weekly_number_xai") \
            .select("number, probability") \
            .eq("target_round", target_round) \
            .eq("veto", "safe") \
            .order("probability", desc=True) \
            .limit(limit) \
            .execute()
        
        return [int(r["number"]) for r in (response.data or [])]
    except Exception as e:
        logger.error(f"  [VetoFiller.get_safe_numbers] FAILED: {e}")
        return []


def backfill_all_rounds(start_round: int = None, end_round: int = None) -> dict[str, Any]:
    """
    과거 회차 일괄 veto 채움 (history backfill).
    
    Args:
        start_round: 시작 회차 (None=최소값)
        end_round: 종료 회차 (None=최대값)
    
    Returns:
        {'total_rounds': n, 'success': n, 'failed': n}
    """
    try:
        supabase = get_client()
        
        # 회차 범위 조회
        query = supabase.table("weekly_number_xai") \
            .select("target_round", count="exact")
        if start_round is not None:
            query = query.gte("target_round", start_round)
        if end_round is not None:
            query = query.lte("target_round", end_round)
        
        response = query.execute()
        all_rounds = sorted(set(r["target_round"] for r in (response.data or [])))
        
        total = len(all_rounds)
        success = 0
        failed = 0
        
        logger.info(f"  [VetoFiller.backfill] {total} rounds to process...")
        for i, rnd in enumerate(all_rounds, 1):
            result = fill_veto_for_round(rnd)
            if result["success"]:
                success += 1
            else:
                failed += 1
            
            if i % 10 == 0:
                logger.info(f"  [VetoFiller.backfill] {i}/{total} done")
        
        return {
            "total_rounds": total,
            "success": success,
            "failed": failed,
        }
    
    except Exception as e:
        logger.error(f"  [VetoFiller.backfill] FAILED: {e}")
        return {"total_rounds": 0, "success": 0, "failed": 0, "error": str(e)}


# ── 스크립트 직접 실행 지원 ────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Veto Filler — fill weekly_number_xai.veto")
    parser.add_argument("--round", type=int, default=None, help="단일 회차 처리")
    parser.add_argument("--backfill", action="store_true", help="전체 회차 backfill")
    parser.add_argument("--start", type=int, default=None, help="backfill 시작 회차")
    parser.add_argument("--end", type=int, default=None, help="backfill 종료 회차")
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO)
    
    if args.backfill:
        result = backfill_all_rounds(args.start, args.end)
        print(f"Backfill: {result}")
    elif args.round:
        result = fill_veto_for_round(args.round)
        print(f"Round {args.round}: {result}")
    else:
        print("Usage:")
        print("  python -m services.veto_filler --round 1224")
        print("  python -m services.veto_filler --backfill")
        print("  python -m services.veto_filler --backfill --start 1173 --end 1222")
```

---

## 💻 `weekly_pipeline_v2.py`에 호출 통합

### 변경 위치: `_save_to_weekly_tables()` 메서드 끝, return 직전

**찾을 위치** (대략 line 380~):
```python
            self.supabase.table("weekly_combinations").insert(rows).execute()
            saved["weekly_combinations"] = f"OK ({len(rows)}rows)"
            logger.info(f"  [C6] weekly_combinations 저장: {len(rows)}행")
        except Exception as e:
            saved["weekly_combinations"] = f"ERR: {e}"
            logger.error(f"  [C6] weekly_combinations 실패: {e}")

        return saved
```

**다음과 같이 변경** (return 직전에 P4 블록 삽입):

```python
            self.supabase.table("weekly_combinations").insert(rows).execute()
            saved["weekly_combinations"] = f"OK ({len(rows)}rows)"
            logger.info(f"  [C6] weekly_combinations 저장: {len(rows)}행")
        except Exception as e:
            saved["weekly_combinations"] = f"ERR: {e}"
            logger.error(f"  [C6] weekly_combinations 실패: {e}")

        # ── [P4 PATCH] C7. weekly_number_xai.veto 채움 ────────────────────
        # weekly_number_xai 저장 직후 _rank 컬럼 기반으로 veto 컬럼 채움
        # 근거: Lotto_lab_Root_Cause_Diagnosis.md (Finding #5)
        try:
            from services.veto_filler import fill_veto_for_round
            veto_result = fill_veto_for_round(target_round)
            if veto_result["success"]:
                saved["weekly_number_xai_veto"] = (
                    f"OK ({veto_result['updated']}rows, "
                    f"safe={veto_result['distribution']['safe']}, "
                    f"exclude={veto_result['distribution']['exclude']}, "
                    f"neutral={veto_result['distribution']['neutral']})"
                )
                logger.info(
                    f"  [C7/P4] veto 채움: {veto_result['distribution']}"
                )
            else:
                saved["weekly_number_xai_veto"] = f"WARN: {veto_result.get('error')}"
        except Exception as e:
            saved["weekly_number_xai_veto"] = f"ERR: {e}"
            logger.error(f"  [C7/P4] veto 채움 실패: {e}")
        # ── /P4 PATCH ──────────────────────────────────────────────────────

        return saved
```

---

## 🧪 검증 절차

### 1. 단일 회차 테스트
```bash
cd lotto-ai-backend

# veto_filler 단독 실행
python -m services.veto_filler --round 1224
```

**기대 로그**:
```
[VetoFiller] target_round=1224 updated=45/45 dist={'safe': 5, 'exclude': 12, 'neutral': 28}
Round 1224: {'success': True, 'updated': 45, 'distribution': {...}}
```

### 2. DB 확인
```sql
SELECT
  veto,
  COUNT(*) as count
FROM weekly_number_xai
WHERE target_round = 1224
GROUP BY veto
ORDER BY count DESC;
```

**기대 결과**:
```
veto                              | count
──────────────────────────────────┼──────
exclude:catboost,gnn,markov       | 1
exclude:cnn,markov,tft            | 1
...
neutral:gnn                       | 5
safe                              | 5
```

### 3. 추천수 5 추출 (veto='safe' 기준)
```python
from services.veto_filler import get_safe_numbers
top5_safe = get_safe_numbers(1224, limit=5)
print(top5_safe)  # 예: [27, 14, 36, 23, 8]
```

### 4. 과거 회차 backfill
```bash
# 50회차 backfill (시간 좀 걸림 — 회차당 ~5초)
python -m services.veto_filler --backfill --start 1173 --end 1222
```

**기대 로그**:
```
[VetoFiller.backfill] 50 rounds to process...
[VetoFiller.backfill] 10/50 done
[VetoFiller.backfill] 20/50 done
...
Backfill: {'total_rounds': 50, 'success': 50, 'failed': 0}
```

### 5. 통합 파이프라인 테스트
```bash
python -m pipeline.weekly_pipeline_v2 --round 1225
```

로그에서 `[C7/P4] veto 채움: ...` 확인.

---

## ⚠️ 주의 사항

### 1. **임계 파라미터 튜닝**
```python
VETO_RANK_THRESHOLD = 36    # 하위 N개 기준
VETO_MODEL_COUNT_HIGH = 3   # exclude 판정 모델 수
```

| 조정 | 효과 |
|------|------|
| THRESHOLD=40 | 더 엄격한 하위 (exclude 적어짐) |
| THRESHOLD=30 | 더 관대한 (exclude 많아짐) |
| COUNT_HIGH=2 | 2개 모델만 거부해도 exclude |
| COUNT_HIGH=5 | 5개 이상이어야 exclude (보수) |

### 2. **N-BEATS rank 컬럼 없음 (현재)**
DB C3 패치 (nbeats_rank 추가) 적용 후 `MODEL_RANK_COLUMNS`에 추가:
```python
("nbeats", "nbeats_rank"),  # C3 패치 후 활성화
```

### 3. **`get_safe_numbers()` 활용 위치**
이 함수를 어디서 호출해서 실제 추천수 5에 반영할지는 추후 결정:
- `NumberRecommender.select_recommendations`에서 사용
- 또는 별도 API 엔드포인트로 노출

지금은 데이터만 채움.

### 4. **속도**
회차당 ~5초 (45행 update). backfill 50회차 = ~4분.  
필요 시 batch_update로 최적화 가능.

---

## 🔄 롤백 절차

```bash
# 신규 파일 제거
rm lotto-ai-backend/services/veto_filler.py

# weekly_pipeline_v2.py 복구
cd lotto-ai-backend
git checkout pipeline/weekly_pipeline_v2.py

# DB veto 컬럼 비우기 (선택)
UPDATE weekly_number_xai SET veto = NULL;
```

---

## ✅ 적용 체크리스트

```
□ 백업 (git branch)
□ services/veto_filler.py 신규 파일 생성
□ pipeline/weekly_pipeline_v2.py 에 P4 블록 추가
□ Smoke 테스트: python -m services.veto_filler --round 1224
□ DB 분포 확인 (safe/exclude/neutral)
□ 50회차 backfill 실행
□ 통합 파이프라인 테스트
□ Git commit (file add + edit)
```

---

## 📝 Git Commit 메시지 예시

```
feat(veto): activate weekly_number_xai.veto column [P4]

- Add services/veto_filler.py with compute_veto_value and fill_veto_for_round
- Integrate veto filler in weekly_pipeline_v2._save_to_weekly_tables
- Use 11-base model _rank columns (threshold rank>=36, count>=3 for exclude)
- Add get_safe_numbers() helper for future top-5 selection

Diagnosis: weekly_number_xai.veto column had been empty across 50 rounds,
preventing safe-number based recommendation. After patch, distribution
expected ~5 safe / ~10 exclude / ~30 neutral per round.

Refs: Lotto_lab_Root_Cause_Diagnosis.md (Finding #5)
```

---

## 🔗 관련 문서

- `../Lotto_lab_Root_Cause_Diagnosis.md` — 진단 (Finding #5)
- `../Lotto_lab_DB_Consistency_Issues.md` — C6 (veto 컬럼)
- `../Lotto_lab_Logic_Enhancements.md` — Phase 0 P4
- `README.md` — 전체 패치 가이드
