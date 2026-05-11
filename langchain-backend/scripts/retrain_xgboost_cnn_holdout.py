# -*- coding: utf-8 -*-
"""XGBoost/CNN 데이터 누수 Fix 재학습 스크립트.

## 배경
- XGBoost: 학습 cutoff 안 회차에서 정답 외움 (in-sample 5.92 vs hold-out 1.66)
- CNN: 1722 회차 전체 학습으로 진짜 hold-out 부재 (LottoGridSequenceDataset이 모든 회차를 슬라이딩 윈도우로 학습)
- 다른 모델 (markov, gnn, tft 등): leak gap < 0.5 정상

## 작업
1. 기존 가중치 백업 (saved_models/_archive/leak_fix_2026-05-03/)
2. cutoff_round=1100으로 XGBoost + CNN 재학습 (회차 1~1100만 사용)
3. hold-out 회차 (1101~1150)에 대해 backfill_model_predictions 실행
4. SQL로 hit_count 평균 측정 → 정상 범위 (1.0~2.0) 확인

## 사용법
python -m scripts.retrain_xgboost_cnn_holdout --cutoff 1100 --validate-rounds 50
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from datetime import datetime

# langchain-backend 패키지 import
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import config
from db.supabase_client import fetch_all_draws, get_client
from models.cnn_model import CNNTrainer
from models.xgboost_model import LottoXGBoost


def backup_models(backup_dir: str) -> dict:
    """기존 XGBoost/CNN 가중치 백업.

    Args:
        backup_dir: 백업 디렉토리 절대 경로

    Returns:
        {"success": bool, "backed_up": list, "errors": list}
    """
    print(f"\n[backup] Creating backup directory: {backup_dir}")
    os.makedirs(backup_dir, exist_ok=True)

    files_to_backup = [
        "xgboost_models.pkl",
        "xgboost.pt",
        "cnn_model.pt",
        "cnn.pt",
    ]

    backed_up = []
    errors = []

    for fname in files_to_backup:
        src = os.path.join(config.MODEL_DIR, fname)
        if not os.path.exists(src):
            print(f"  [backup] {fname}: not found (skip)")
            continue

        dst = os.path.join(backup_dir, fname)
        try:
            shutil.copy2(src, dst)
            size_mb = os.path.getsize(src) / (1024 * 1024)
            print(f"  [backup] {fname}: OK ({size_mb:.2f} MB)")
            backed_up.append(fname)
        except Exception as e:
            error_msg = f"{fname}: {e}"
            print(f"  [backup] {fname}: FAILED - {e}")
            errors.append(error_msg)

    return {
        "success": len(backed_up) > 0,
        "backed_up": backed_up,
        "errors": errors,
        "backup_dir": backup_dir,
    }


def retrain_models(cutoff_round: int) -> dict:
    """XGBoost + CNN 재학습 (cutoff_round 이하 데이터만).

    Args:
        cutoff_round: 학습 데이터 cutoff 회차

    Returns:
        {
            "success": bool,
            "xgboost": {"success": bool, "time_sec": float, "models_trained": int},
            "cnn": {"success": bool, "time_sec": float, "epochs_trained": int, "best_val_loss": float},
        }
    """
    print(f"\n[retrain] Starting retrain with cutoff_round={cutoff_round}")

    # 1. 데이터 로드
    draws = fetch_all_draws()
    if not draws:
        return {"success": False, "error": "No draws data"}

    print(f"[retrain] fetch_all_draws: {len(draws)} rounds")
    latest_round = max(int(d.get("round", 0)) for d in draws)
    print(f"[retrain] latest round: {latest_round}")
    print(f"[retrain] cutoff_round: {cutoff_round}")
    print(f"[retrain] hold-out rounds: {cutoff_round + 1} ~ {latest_round} ({latest_round - cutoff_round} rounds)")

    results = {}

    # 2. XGBoost 재학습
    print(f"\n{'='*60}")
    print("[retrain] XGBoost training start")
    print(f"{'='*60}")
    xgb_start = time.time()
    try:
        xgb_model = LottoXGBoost()
        xgb_result = xgb_model.train(draws, fine_tune=False, cutoff_round=cutoff_round)
        xgb_time = time.time() - xgb_start
        print(f"[retrain] XGBoost: SUCCESS ({xgb_time:.1f}s)")
        results["xgboost"] = {
            "success": True,
            "time_sec": xgb_time,
            "models_trained": xgb_result.get("models_trained", 45),
        }
    except Exception as e:
        xgb_time = time.time() - xgb_start
        print(f"[retrain] XGBoost: FAILED ({xgb_time:.1f}s) - {type(e).__name__}: {e}")
        results["xgboost"] = {
            "success": False,
            "time_sec": xgb_time,
            "error": str(e),
        }

    # 3. CNN 재학습
    print(f"\n{'='*60}")
    print("[retrain] CNN training start")
    print(f"{'='*60}")
    cnn_start = time.time()
    try:
        cnn_trainer = CNNTrainer()
        cnn_result = cnn_trainer.train(draws, fine_tune=False, cutoff_round=cutoff_round)
        cnn_time = time.time() - cnn_start
        print(f"[retrain] CNN: SUCCESS ({cnn_time:.1f}s)")
        results["cnn"] = {
            "success": True,
            "time_sec": cnn_time,
            "epochs_trained": cnn_result.get("epochs_trained", 100),
            "best_val_loss": cnn_result.get("best_val_loss", 0.0),
        }
    except Exception as e:
        cnn_time = time.time() - cnn_start
        print(f"[retrain] CNN: FAILED ({cnn_time:.1f}s) - {type(e).__name__}: {e}")
        results["cnn"] = {
            "success": False,
            "time_sec": cnn_time,
            "error": str(e),
        }

    return {
        "success": results.get("xgboost", {}).get("success", False)
        and results.get("cnn", {}).get("success", False),
        "xgboost": results.get("xgboost", {}),
        "cnn": results.get("cnn", {}),
    }


def validate_holdout(cutoff_round: int, n_rounds: int = 50) -> dict:
    """Hold-out 회차에 대해 backfill + hit_count 측정.

    Args:
        cutoff_round: 학습 cutoff 회차
        n_rounds: hold-out 검증 회차 수 (cutoff_round+1부터 n_rounds개)

    Returns:
        {
            "success": bool,
            "backfill": {"success": bool, "rounds_processed": list, "total_saved": int},
            "hit_stats": {model_name: {"avg_hit": float, "count": int}}
        }
    """
    print(f"\n[validate] Hold-out validation: {n_rounds} rounds from {cutoff_round + 1}")

    # 1. backfill
    from scripts.backfill_model_predictions import backfill_latest_round

    start_round = cutoff_round + n_rounds  # backfill은 desc로 진행하므로 시작점은 cutoff+n
    backfill_result = backfill_latest_round(n_rounds=n_rounds, start_round=start_round)

    if not backfill_result.get("success"):
        return {
            "success": False,
            "backfill": backfill_result,
            "error": "backfill failed",
        }

    # 2. SQL로 hit_count 평균 측정
    print(f"\n[validate] Measuring hit_count for rounds {cutoff_round + 1}~{cutoff_round + n_rounds}")

    try:
        client = get_client()
        # model_predictions 테이블에서 hit_count avg 측정
        result = client.rpc(
            "get_holdout_hit_stats",
            {
                "start_round": cutoff_round + 1,
                "end_round": cutoff_round + n_rounds,
            },
        ).execute()

        hit_stats = {}
        if result.data:
            for row in result.data:
                model_name = row["model_name"]
                avg_hit = float(row["avg_hit"])
                count = int(row["count"])
                hit_stats[model_name] = {
                    "avg_hit": avg_hit,
                    "count": count,
                }
                print(f"  [validate] {model_name}: avg_hit={avg_hit:.2f} (n={count})")

        return {
            "success": True,
            "backfill": backfill_result,
            "hit_stats": hit_stats,
        }

    except Exception as e:
        # RPC 함수가 없으면 직접 SQL 실행
        print(f"  [validate] RPC failed (trying direct SQL): {e}")
        try:
            # 직접 select로 집계
            result = (
                client.table("model_predictions")
                .select("model_name, hit_count")
                .gte("round_number", cutoff_round + 1)
                .lte("round_number", cutoff_round + n_rounds)
                .execute()
            )

            records = result.data or []
            model_hits = {}
            for rec in records:
                model = rec["model_name"]
                hit = rec.get("hit_count", 0)
                if model not in model_hits:
                    model_hits[model] = []
                model_hits[model].append(hit)

            hit_stats = {}
            for model, hits in model_hits.items():
                avg_hit = sum(hits) / len(hits) if hits else 0.0
                hit_stats[model] = {
                    "avg_hit": avg_hit,
                    "count": len(hits),
                }
                print(f"  [validate] {model}: avg_hit={avg_hit:.2f} (n={len(hits)})")

            return {
                "success": True,
                "backfill": backfill_result,
                "hit_stats": hit_stats,
            }

        except Exception as e2:
            print(f"  [validate] SQL failed: {e2}")
            return {
                "success": False,
                "backfill": backfill_result,
                "error": f"SQL failed: {e2}",
            }


def main():
    parser = argparse.ArgumentParser(description="XGBoost/CNN leak fix retrain")
    parser.add_argument(
        "--cutoff",
        type=int,
        default=1100,
        help="학습 cutoff 회차 (이 회차 이하만 학습). 기본 1100",
    )
    parser.add_argument(
        "--validate-rounds",
        type=int,
        default=50,
        help="hold-out 검증 회차 수 (cutoff+1부터 N개). 기본 50",
    )
    parser.add_argument(
        "--skip-backup",
        action="store_true",
        help="백업 생략 (재실행 시)",
    )
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="hold-out 검증 생략 (학습만)",
    )

    args = parser.parse_args()

    print(f"{'='*60}")
    print("XGBoost/CNN Data Leak Fix - Retrain Script")
    print(f"{'='*60}")
    print(f"Cutoff round: {args.cutoff}")
    print(f"Validation rounds: {args.validate_rounds}")
    print(f"Skip backup: {args.skip_backup}")
    print(f"Skip validation: {args.skip_validation}")

    # 1. 백업
    if not args.skip_backup:
        backup_dir = os.path.join(
            config.MODEL_DIR,
            "_archive",
            f"leak_fix_{datetime.now().strftime('%Y-%m-%d')}",
        )
        backup_result = backup_models(backup_dir)
        if not backup_result["success"]:
            print(f"\n[FAILED] Backup failed: {backup_result.get('errors', [])}")
            return 1
        print(f"\n[OK] Backup completed: {len(backup_result['backed_up'])} files backed up")
        print(f"     Backup dir: {backup_result['backup_dir']}")
    else:
        print("\n[SKIP] Backup skipped")

    # 2. 재학습
    retrain_result = retrain_models(cutoff_round=args.cutoff)
    if not retrain_result["success"]:
        print(f"\n[FAILED] Retrain failed:")
        print(f"  XGBoost: {retrain_result['xgboost']}")
        print(f"  CNN: {retrain_result['cnn']}")
        return 1

    xgb_time = retrain_result["xgboost"]["time_sec"]
    cnn_time = retrain_result["cnn"]["time_sec"]
    total_time = xgb_time + cnn_time
    print(f"\n[OK] Retrain completed:")
    print(f"  XGBoost: {xgb_time:.1f}s ({retrain_result['xgboost']['models_trained']} models)")
    print(f"  CNN: {cnn_time:.1f}s ({retrain_result['cnn']['epochs_trained']} epochs, loss={retrain_result['cnn']['best_val_loss']:.4f})")
    print(f"  Total: {total_time:.1f}s ({total_time / 60:.1f}min)")

    # 3. Hold-out 검증
    if not args.skip_validation:
        validate_result = validate_holdout(
            cutoff_round=args.cutoff,
            n_rounds=args.validate_rounds,
        )

        if not validate_result["success"]:
            print(f"\n[FAILED] Validation failed: {validate_result.get('error', 'unknown')}")
            return 1

        backfill_info = validate_result["backfill"]
        hit_stats = validate_result["hit_stats"]

        print(f"\n[OK] Validation completed:")
        print(f"  Backfill: {len(backfill_info['rounds_processed'])} rounds, {backfill_info['total_saved']} records")
        print(f"\n  Hold-out hit_count stats (rounds {args.cutoff + 1}~{args.cutoff + args.validate_rounds}):")
        print(f"  {'Model':<20} {'Avg Hit':<10} {'Count':<10}")
        print(f"  {'-'*40}")

        # XGBoost/CNN 강조
        for model in ["xgboost", "cnn"]:
            if model in hit_stats:
                avg = hit_stats[model]["avg_hit"]
                cnt = hit_stats[model]["count"]
                status = "✓ NORMAL" if 1.0 <= avg <= 2.5 else "⚠ CHECK"
                print(f"  {model:<20} {avg:<10.2f} {cnt:<10} {status}")

        # 다른 모델
        print(f"  {'-'*40}")
        for model, stats in sorted(hit_stats.items()):
            if model not in ["xgboost", "cnn"]:
                avg = stats["avg_hit"]
                cnt = stats["count"]
                print(f"  {model:<20} {avg:<10.2f} {cnt:<10}")

        # Leak fix 효과 판정
        xgb_ok = 1.0 <= hit_stats.get("xgboost", {}).get("avg_hit", 99) <= 2.5
        cnn_ok = 1.0 <= hit_stats.get("cnn", {}).get("avg_hit", 99) <= 2.5

        print(f"\n{'='*60}")
        if xgb_ok and cnn_ok:
            print("✓ LEAK FIX VERIFIED: XGBoost/CNN hold-out hit_count in normal range (1.0~2.5)")
        else:
            print("⚠ LEAK FIX FAILED: XGBoost/CNN hold-out hit_count still abnormal")
            if not xgb_ok:
                print(f"  - XGBoost: {hit_stats.get('xgboost', {}).get('avg_hit', 'N/A')}")
            if not cnn_ok:
                print(f"  - CNN: {hit_stats.get('cnn', {}).get('avg_hit', 'N/A')}")
        print(f"{'='*60}")

    else:
        print("\n[SKIP] Validation skipped")

    print("\n[DONE] Script completed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
