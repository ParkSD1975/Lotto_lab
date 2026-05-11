# P5 옵션 A. 4-Pillar 실제 구현 패치

> **대상**: 신규 파일 `lotto-ai-backend/services/pillar_scorer.py` + 통합  
> **목적**: CNS/ENS/FLT/STA 4-Pillar 점수 실제 계산 구현  
> **근거**: `Lotto_lab_Root_Cause_Diagnosis.md` Finding #1  
> **예상 시간**: 1일

> **참고**: 옵션 B (임시 정리)는 `P5_pillar_scores_cleanup.sql` 참조.  
> 옵션 A는 본격 구현. 시간 여유 있을 때 진행.

---

## 🎯 4-Pillar 정의 (MASTER_PLAN #25)

| Pillar | 의미 | 계산 |
|--------|------|------|
| **CNS** Consensus | 11개 모델 간 합의도 | 1 / (1 + avg(std_rank)/10) |
| **ENS** Ensemble Probability | 평균 확률 신뢰도 | top-N 번호의 평균 probability |
| **FLT** Filter Compliance | 필터 통과율 | passing_filters / total_filters |
| **STA** Stability | 시간 안정성 | 직전 N회 top_5와 평균 overlap |

---

## 💻 신규 파일: `lotto-ai-backend/services/pillar_scorer.py`

```python
"""
[P5 PATCH 옵션 A] 4-Pillar Consensus Scorer

CNS / ENS / FLT / STA 점수 계산 + recommendation_backtest_runs 저장.

근거: Lotto_lab_Root_Cause_Diagnosis.md (Finding #1)
       MASTER_PLAN.md 결정 #25

패치 일자: 2026-05-11
"""
from __future__ import annotations

import logging
import statistics
from typing import Any

from db.supabase_client import get_client

logger = logging.getLogger("PillarScorer")


# 11-base 모델 _rank 컬럼
MODEL_RANK_COLUMNS: list[str] = [
    "xgboost_rank", "catboost_rank", "tabnet_rank",
    "cnn_rank", "gnn_rank", "markov_rank",
    "autoencoder_rank", "tft_rank", "mhn_rank", "bayesian_nn_rank",
    # "nbeats_rank",   # C3 패치 후 추가
]


def compute_cns(rows: list[dict]) -> float:
    """
    CNS — Consensus Strength
    
    11개 모델 간 rank의 표준편차 평균. 작을수록 합의 강함.
    정규화: 1 / (1 + avg_std/10) → [0, 1]
    
    Args:
        rows: weekly_number_xai 한 회차 45행 (각 행에 _rank 컬럼들)
    
    Returns:
        CNS 점수 [0, 1]. 1에 가까울수록 합의 강함.
    """
    if not rows:
        return 0.0
    
    rank_stds = []
    for row in rows:
        ranks = []
        for col in MODEL_RANK_COLUMNS:
            v = row.get(col)
            if v is not None:
                try:
                    ranks.append(int(v))
                except (ValueError, TypeError):
                    continue
        if len(ranks) >= 2:
            rank_stds.append(statistics.stdev(ranks))
    
    if not rank_stds:
        return 0.0
    
    avg_std = statistics.mean(rank_stds)
    return round(1 / (1 + avg_std / 10), 4)


def compute_ens(rows: list[dict], top_n: int = 10) -> float:
    """
    ENS — Ensemble Probability
    
    상위 N개 번호의 평균 probability. 자연 평균(0.022) 대비 얼마나 강한가.
    정규화: avg_prob / 0.022 - 1, clipped to [0, 1]
    
    Args:
        rows: weekly_number_xai 한 회차 행
        top_n: 상위 N개 (기본 10)
    
    Returns:
        ENS 점수 [0, 1]
    """
    if not rows:
        return 0.0
    
    probs = []
    for row in rows:
        v = row.get("probability")
        if v is not None:
            try:
                probs.append(float(v))
            except (ValueError, TypeError):
                continue
    
    if not probs:
        return 0.0
    
    probs.sort(reverse=True)
    top_probs = probs[:top_n]
    avg_top = sum(top_probs) / len(top_probs)
    
    # 자연 평균 대비 lift (1/45 ≈ 0.0222)
    natural = 1 / 45
    lift = (avg_top / natural) - 1.0
    
    # [0, 1] 클램프 (lift 1.0 이상은 1.0으로 처리)
    return round(max(0.0, min(1.0, lift)), 4)


def compute_flt(target_round: int, supabase) -> float:
    """
    FLT — Filter Compliance Rate
    
    weekly_filter_predictions에서 통과한 필터 비율.
    
    Args:
        target_round: 대상 회차
        supabase: DB 클라이언트
    
    Returns:
        FLT 점수 [0, 1]
    """
    try:
        response = supabase.table("weekly_filter_predictions") \
            .select("filter_key, in_range") \
            .eq("target_round", target_round) \
            .execute()
        
        rows = response.data or []
        if not rows:
            return 0.0
        
        verified_rows = [r for r in rows if r.get("in_range") is not None]
        if not verified_rows:
            # 미검증 회차 — 0.5 반환 (중립)
            return 0.5
        
        pass_count = sum(1 for r in verified_rows if r["in_range"] is True)
        return round(pass_count / len(verified_rows), 4)
    
    except Exception as e:
        logger.warning(f"  [PillarScorer.compute_flt] FAILED: {e}")
        return 0.0


def compute_sta(target_round: int, supabase, lookback: int = 5) -> float:
    """
    STA — Stability Over Time
    
    직전 N회의 top_5와 현재 top_5의 평균 overlap.
    
    Args:
        target_round: 대상 회차
        supabase: DB 클라이언트
        lookback: 직전 N회 (기본 5)
    
    Returns:
        STA 점수 [0, 1]. 0=완전 다름, 1=완전 동일
    """
    try:
        # 현재 회차 top_5
        cur_response = supabase.table("weekly_predictions") \
            .select("top_5") \
            .eq("target_round", target_round) \
            .execute()
        
        if not cur_response.data:
            return 0.0
        
        current_top5 = set(cur_response.data[0].get("top_5") or [])
        if not current_top5:
            return 0.0
        
        # 직전 N회 top_5
        prev_response = supabase.table("weekly_predictions") \
            .select("target_round, top_5") \
            .lt("target_round", target_round) \
            .order("target_round", desc=True) \
            .limit(lookback) \
            .execute()
        
        prev_rounds = prev_response.data or []
        if not prev_rounds:
            return 0.0
        
        overlaps = []
        for prev in prev_rounds:
            prev_top5 = set(prev.get("top_5") or [])
            if prev_top5:
                overlap = len(current_top5 & prev_top5) / 5.0
                overlaps.append(overlap)
        
        if not overlaps:
            return 0.0
        
        # 평균 overlap. 너무 높으면 (>0.8) 변덕 없음이 아니라 favorite bias 신호 가능
        # 자연스러운 안정성은 0.2~0.5 정도
        return round(sum(overlaps) / len(overlaps), 4)
    
    except Exception as e:
        logger.warning(f"  [PillarScorer.compute_sta] FAILED: {e}")
        return 0.0


def compute_pillar_scores(target_round: int) -> dict[str, float]:
    """
    4-Pillar 점수 통합 계산.
    
    Args:
        target_round: 대상 회차
    
    Returns:
        {'CNS': float, 'ENS': float, 'FLT': float, 'STA': float}
    """
    try:
        supabase = get_client()
        
        # weekly_number_xai 데이터 조회 (CNS, ENS용)
        select_cols = "number, probability, " + ", ".join(MODEL_RANK_COLUMNS)
        xai_response = supabase.table("weekly_number_xai") \
            .select(select_cols) \
            .eq("target_round", target_round) \
            .execute()
        
        xai_rows = xai_response.data or []
        
        # 각 Pillar 계산
        cns = compute_cns(xai_rows)
        ens = compute_ens(xai_rows)
        flt = compute_flt(target_round, supabase)
        sta = compute_sta(target_round, supabase)
        
        scores = {
            "CNS": cns,
            "ENS": ens,
            "FLT": flt,
            "STA": sta,
        }
        
        logger.info(
            f"  [PillarScorer] target_round={target_round} "
            f"CNS={cns:.4f} ENS={ens:.4f} FLT={flt:.4f} STA={sta:.4f}"
        )
        
        return scores
    
    except Exception as e:
        logger.error(f"  [PillarScorer.compute_pillar_scores] FAILED: {e}")
        return {"CNS": 0.0, "ENS": 0.0, "FLT": 0.0, "STA": 0.0}


def save_pillar_scores(target_round: int) -> dict[str, Any]:
    """
    4-Pillar 점수 계산 후 recommendation_backtest_runs에 저장.
    
    Args:
        target_round: 대상 회차
    
    Returns:
        {'success': bool, 'scores': dict, 'updated': int, 'error': str | None}
    """
    try:
        supabase = get_client()
        scores = compute_pillar_scores(target_round)
        
        # recommendation_backtest_runs 해당 회차 행 UPDATE
        response = supabase.table("recommendation_backtest_runs") \
            .update({"pillar_scores": scores}) \
            .eq("target_round", target_round) \
            .execute()
        
        updated = len(response.data or [])
        
        return {
            "success": True,
            "scores": scores,
            "updated": updated,
            "error": None,
        }
    
    except Exception as e:
        logger.error(f"  [PillarScorer.save_pillar_scores] FAILED: {e}")
        return {
            "success": False,
            "scores": {},
            "updated": 0,
            "error": str(e),
        }


def backfill_all_rounds(start_round: int = None, end_round: int = None) -> dict[str, Any]:
    """
    과거 회차 일괄 pillar_scores 계산 + 저장.
    
    Args:
        start_round, end_round: 회차 범위 (None=전체)
    """
    try:
        supabase = get_client()
        
        query = supabase.table("recommendation_backtest_runs") \
            .select("target_round")
        if start_round is not None:
            query = query.gte("target_round", start_round)
        if end_round is not None:
            query = query.lte("target_round", end_round)
        
        response = query.execute()
        all_rounds = sorted(set(r["target_round"] for r in (response.data or [])))
        
        total = len(all_rounds)
        success = 0
        failed = 0
        
        logger.info(f"  [PillarScorer.backfill] {total} rounds to process...")
        for i, rnd in enumerate(all_rounds, 1):
            result = save_pillar_scores(rnd)
            if result["success"]:
                success += 1
            else:
                failed += 1
            
            if i % 10 == 0:
                logger.info(f"  [PillarScorer.backfill] {i}/{total} done")
        
        return {
            "total_rounds": total,
            "success": success,
            "failed": failed,
        }
    
    except Exception as e:
        logger.error(f"  [PillarScorer.backfill] FAILED: {e}")
        return {"total_rounds": 0, "success": 0, "failed": 0, "error": str(e)}


# ── 스크립트 직접 실행 ────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    import json
    
    parser = argparse.ArgumentParser(description="Pillar Scorer — compute and save CNS/ENS/FLT/STA")
    parser.add_argument("--round", type=int, default=None, help="단일 회차 처리")
    parser.add_argument("--backfill", action="store_true", help="전체 backfill")
    parser.add_argument("--start", type=int, default=None)
    parser.add_argument("--end", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true", help="DB 저장 없이 계산만")
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO)
    
    if args.backfill:
        result = backfill_all_rounds(args.start, args.end)
        print(f"Backfill: {result}")
    elif args.round:
        if args.dry_run:
            scores = compute_pillar_scores(args.round)
            print(f"Round {args.round} pillar_scores (DRY RUN):")
            print(json.dumps(scores, indent=2))
        else:
            result = save_pillar_scores(args.round)
            print(f"Round {args.round}: {result}")
    else:
        print("Usage:")
        print("  python -m services.pillar_scorer --round 1224")
        print("  python -m services.pillar_scorer --round 1224 --dry-run")
        print("  python -m services.pillar_scorer --backfill --start 1173 --end 1222")
```

---

## 💻 `weekly_pipeline_v2.py` 통합

P4 패치 다음 블록 (return 직전)에 추가:

```python
        # ── [P5 PATCH 옵션 A] C8. recommendation_backtest_runs.pillar_scores ─
        # 4-Pillar Consensus Score (CNS/ENS/FLT/STA) 계산 + 저장
        # 근거: Lotto_lab_Root_Cause_Diagnosis.md (Finding #1)
        try:
            from services.pillar_scorer import save_pillar_scores
            pillar_result = save_pillar_scores(target_round)
            if pillar_result["success"]:
                saved["pillar_scores"] = (
                    f"OK (updated={pillar_result['updated']}, "
                    f"CNS={pillar_result['scores']['CNS']:.3f}, "
                    f"ENS={pillar_result['scores']['ENS']:.3f}, "
                    f"FLT={pillar_result['scores']['FLT']:.3f}, "
                    f"STA={pillar_result['scores']['STA']:.3f})"
                )
                logger.info(f"  [C8/P5] pillar_scores: {pillar_result['scores']}")
            else:
                saved["pillar_scores"] = f"WARN: {pillar_result.get('error')}"
        except Exception as e:
            saved["pillar_scores"] = f"ERR: {e}"
            logger.error(f"  [C8/P5] pillar_scores 실패: {e}")
        # ── /P5 PATCH ──────────────────────────────────────────────────────

        return saved
```

---

## 🧪 검증 절차

### 1. 단일 회차 dry-run
```bash
cd lotto-ai-backend
python -m services.pillar_scorer --round 1224 --dry-run
```

**기대 출력**:
```
[PillarScorer] target_round=1224 CNS=0.4523 ENS=0.0823 FLT=0.6667 STA=0.4000
Round 1224 pillar_scores (DRY RUN):
{
  "CNS": 0.4523,
  "ENS": 0.0823,
  "FLT": 0.6667,
  "STA": 0.4000
}
```

### 2. 단일 회차 저장
```bash
python -m services.pillar_scorer --round 1224
```

### 3. DB 확인
```sql
SELECT 
  target_round,
  pillar_scores
FROM recommendation_backtest_runs
WHERE target_round BETWEEN 1220 AND 1224
ORDER BY target_round;
```

**기대**: 회차별로 **다른 값**이 나와야 함 (이전엔 모두 동일했음).

### 4. 50회차 backfill
```bash
python -m services.pillar_scorer --backfill --start 1173 --end 1222
```

### 5. 통합 파이프라인
```bash
python -m pipeline.weekly_pipeline_v2 --round 1225
```

---

## ⚠️ 주의 사항

### 1. **FLT 계산 한계**
`weekly_filter_predictions.in_range`는 회차 검증 후에 값 채워짐.  
미검증 회차는 FLT=0.5 (중립) 반환.

### 2. **STA — 과도한 안정성 ≠ 좋음**
STA가 0.8 이상이면 → top_5가 거의 동일 = favorite bias 신호.  
자연스러운 STA는 0.2~0.5 정도.  
P1 패치 적용 후 STA가 너무 낮아지면 (< 0.1) 페널티 너무 강함을 의미.

### 3. **각 Pillar 정규화 기준**
| Pillar | 0 | 0.5 | 1 |
|--------|---|-----|---|
| CNS | 모델 완전 불일치 | 보통 | 완전 합의 |
| ENS | 자연 빈도 | lift 0.5× | lift 1.0× |
| FLT | 모든 필터 실패 | 절반 통과 | 모두 통과 |
| STA | 완전 다른 추천 | 약한 안정 | 매번 동일 |

### 4. **종합 점수 산식** (선택 — 별도 구현)
```python
def composite_pillar_score(scores: dict) -> float:
    """4-Pillar 가중 종합 (간단 평균)"""
    return (
        0.3 * scores['CNS'] +
        0.3 * scores['ENS'] +
        0.2 * scores['FLT'] +
        0.2 * scores['STA']
    )
```

### 5. **`pillar_shap` 컬럼**
이 패치는 `pillar_scores`만 채움. `pillar_shap`은 별도 작업.  
필요 시 옵션 B SQL로 NULL 처리:
```sql
UPDATE recommendation_backtest_runs SET pillar_shap = NULL;
```

---

## 🔄 롤백 절차

```bash
rm lotto-ai-backend/services/pillar_scorer.py
cd lotto-ai-backend
git checkout pipeline/weekly_pipeline_v2.py
```

DB 데이터는 옵션 B SQL로 NULL 복원 가능.

---

## ✅ 적용 체크리스트

```
□ 백업 (git branch)
□ services/pillar_scorer.py 신규 파일 생성
□ pipeline/weekly_pipeline_v2.py 에 P5 블록 추가
□ Dry-run 테스트: python -m services.pillar_scorer --round 1224 --dry-run
□ 단일 회차 저장 테스트
□ DB 확인 — 회차별로 다른 값 나오는지 검증
□ 50회차 backfill
□ 통합 파이프라인 테스트
□ Git commit
```

---

## 📝 Git Commit 메시지

```
feat(pillar): implement 4-Pillar Consensus Scoring [P5-A]

- Add services/pillar_scorer.py with compute_cns/ens/flt/sta
- Integrate in weekly_pipeline_v2._save_to_weekly_tables (C8)
- CNS: 1 / (1 + avg(std_rank)/10)
- ENS: top-10 avg prob / natural_freq - 1, clamped [0,1]
- FLT: passed filters / total verified filters
- STA: avg overlap with previous 5 rounds' top_5

Diagnosis: recommendation_backtest_runs.pillar_scores was static
(50 rounds identical dummy values). 4-Pillar code did not exist
in repository. After patch, scores computed per round from real data.

Refs: Lotto_lab_Root_Cause_Diagnosis.md (Finding #1)
      MASTER_PLAN.md decision #25
```

---

## 🔗 관련 문서

- `../Lotto_lab_Root_Cause_Diagnosis.md` — 진단 (Finding #1)
- `../Lotto_lab_DB_Consistency_Issues.md` — C5 (pillar_scores 컬럼)
- `../Lotto_lab_Logic_Enhancements.md` — Phase 0 P5
- `P5_pillar_scores_cleanup.sql` — 옵션 B (임시 정리, P5-A 적용 전 사용)
- `README.md` — 전체 패치 가이드
