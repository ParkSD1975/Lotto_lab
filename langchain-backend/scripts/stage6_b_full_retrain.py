# -*- coding: utf-8 -*-
"""Stage 6-B — 11 base + 메타러너 데이터 누수 차단 전체 재학습.

## 배경 (사용자 결정 B, 2026-05-04)
Stage 6 50회 백테스트 결과 추천 hit 0.84 (목표 2.0 미달). 원인 후보:
- gnn / autoencoder / markov / catboost / tabnet / tft / mhn / bayesian_nn:
  cutoff_round 인자 없이 전체 1222회차로 학습 → hold-out 1101~1200 누수 가능
- meta_learner: cutoff 명시 없이 학습된 모델 출력으로 fit

## 작업
1. 기존 11 base + meta_learner 가중치 백업 (saved_models/_archive/stage6_b_2026-05-04/)
2. cutoff_round=1100 필터된 draws로 LottoEnsemble.train_all(force_retrain=True) 실행
   → 모든 11 base가 1~1100 회차만으로 from-scratch 학습
3. meta_log.jsonl 초기화 후 1101~1200 walk-forward bootstrap (stride=1)
   → 누수 없는 stacking 학습 데이터 100회차 확보
4. meta_learner 재학습 (LightGBM 또는 LR 폴백)
5. 보고: 학습 시간, 가중치 파일 크기, meta_log 회차 수

## 사용법
python langchain-backend/scripts/stage6_b_full_retrain.py [--cutoff 1100] [--meta-end 1200]
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import config
from db.supabase_client import fetch_all_draws


# 백업 대상 (전체 11 base + 메타 + 캐시)
BACKUP_FILES = [
    # 11 base 가중치
    "xgboost.pt", "xgboost_models.pkl",
    "cnn.pt", "cnn_model.pt",
    "gnn_model.pt", "gnn_adjacency.json", "gnn_feature_transformer.pkl",
    "autoencoder.pt", "autoencoder_model.pt",
    "markov.json", "markov_matrices.json",
    "catboost_main45.cbm",
    "tabnet_main45.zip",
    "tft_main45.pt",
    "mhn_main45.pt",
    "bayesian_nn_main45.pt",
    "nbeats_sum.pt",
    # 메타 + 보조
    "meta_learner.pkl",
    "meta_log.jsonl",
    "ensemble_weights.json",
]


def backup_existing_weights(backup_dir: str) -> dict:
    """현재 가중치 백업."""
    print(f"\n[backup] Creating backup directory: {backup_dir}")
    os.makedirs(backup_dir, exist_ok=True)

    backed_up = []
    skipped = []

    for fname in BACKUP_FILES:
        src = os.path.join(config.MODEL_DIR, fname)
        if not os.path.exists(src):
            skipped.append(fname)
            continue
        dst = os.path.join(backup_dir, fname)
        try:
            shutil.copy2(src, dst)
            size_kb = os.path.getsize(src) / 1024
            print(f"  [backup] {fname}: OK ({size_kb:.1f} KB)")
            backed_up.append(fname)
        except Exception as e:
            print(f"  [backup] {fname}: FAILED - {e}")

    return {"backed_up": backed_up, "skipped": skipped, "backup_dir": backup_dir}


def filter_draws_by_cutoff(draws: list, cutoff_round: int) -> list:
    """cutoff_round 이하만 남김. 최신순(latest first) 정렬 유지."""
    filtered = [d for d in draws if int(d.get("round", 0)) <= cutoff_round]
    filtered_sorted = sorted(filtered, key=lambda x: int(x["round"]), reverse=True)
    return filtered_sorted


def retrain_all_base(draws_filtered: list, cutoff_round: int) -> dict:
    """LottoEnsemble.train_all(force_retrain=True)로 11 base 일괄 재학습."""
    from models.ensemble import LottoEnsemble

    print(f"\n[retrain] LottoEnsemble.train_all(force_retrain=True)")
    print(f"[retrain] cutoff_round = {cutoff_round}")
    print(f"[retrain] filtered draws: {len(draws_filtered)} rounds (max round = {draws_filtered[0]['round'] if draws_filtered else 'N/A'})")

    # ensemble.train_all 내부에서 _init_new_base_models로 11 base 등록
    ensemble = LottoEnsemble()

    t0 = time.time()
    try:
        result = ensemble.train_all(draws_filtered, force_retrain=True)
        elapsed = time.time() - t0
        print(f"[retrain] ensemble.train_all DONE ({elapsed:.1f}s)")
        return {"success": result.get("success", False), "elapsed": elapsed, "raw": result, "ensemble": ensemble}
    except Exception as e:
        elapsed = time.time() - t0
        import traceback
        print(f"[retrain] ensemble.train_all FAILED ({elapsed:.1f}s): {type(e).__name__}: {e}")
        traceback.print_exc()
        return {"success": False, "elapsed": elapsed, "error": str(e), "ensemble": None}


def reset_and_bootstrap_meta_log(draws_all: list, ensemble, cutoff_round: int, meta_end: int) -> dict:
    """meta_log.jsonl 초기화 후 cutoff+1 ~ meta_end walk-forward bootstrap.

    각 회차마다 'round 이전 history만'을 사용해 11 base inference → meta_log에 한 줄 추가.
    """
    from models.meta_learner import MetaLearner

    meta_log_path = os.path.join(config.MODEL_DIR, "meta_log.jsonl")
    if os.path.exists(meta_log_path):
        os.remove(meta_log_path)
        print(f"[meta] meta_log.jsonl 초기화 완료")

    meta = MetaLearner(save_dir=config.MODEL_DIR)

    # walk-forward: cutoff+1 ~ meta_end
    target_rounds = list(range(cutoff_round + 1, meta_end + 1))
    n_targets = len(target_rounds)
    print(f"[meta] walk-forward bootstrap: rounds {target_rounds[0]} ~ {target_rounds[-1]} ({n_targets}회)")

    draws_sorted_desc = sorted(draws_all, key=lambda x: int(x["round"]), reverse=True)
    by_round = {int(d["round"]): d for d in draws_sorted_desc}

    added = 0
    skipped = 0
    t0 = time.time()

    for target_round in target_rounds:
        if target_round not in by_round:
            skipped += 1
            continue

        # target_round 이전 history만 (round < target_round)
        history = [d for d in draws_sorted_desc if int(d["round"]) < target_round]
        actual_nums = by_round[target_round].get("numbers", [])

        # 11 base 개별 inference
        model_probs: dict = {}
        all_ok = True
        for m_name, m_obj in ensemble.models.items():
            try:
                pred = m_obj.predict(history)
                model_probs[m_name] = {
                    n_: float(pred.get(n_, 1 / 45)) for n_ in range(1, 46)
                }
            except Exception:
                model_probs[m_name] = {n_: 1 / 45 for n_ in range(1, 46)}
                all_ok = False

        if "markov" not in model_probs:
            model_probs["markov"] = {n_: 1 / 45 for n_ in range(1, 46)}
            all_ok = False

        if not all_ok:
            skipped += 1

        meta.log(model_probs, actual_nums)
        added += 1

        if added % 10 == 0:
            elapsed = time.time() - t0
            eta = elapsed / added * (n_targets - added)
            print(f"  [meta] {added}/{n_targets} 회차 (ETA {eta:.0f}s)")

    elapsed = time.time() - t0
    print(f"[meta] bootstrap DONE: {added}/{n_targets} 추가 ({elapsed:.1f}s)")

    return {"added": added, "skipped": skipped, "elapsed": elapsed, "meta": meta}


def train_meta_learner(meta) -> dict:
    """메타러너 학습."""
    print(f"\n[meta] meta_learner.train() 호출")
    t0 = time.time()
    result = meta.train()
    elapsed = time.time() - t0
    if result.get("success"):
        print(f"[meta] 학습 완료 ({elapsed:.1f}s)")
        print(f"  method: {result.get('method')}")
        print(f"  n_rounds: {result.get('n_rounds')}, n_samples: {result.get('n_samples')}")
        fi = result.get("feature_importance", {})
        if fi:
            print(f"  feature_importance:")
            for k, v in sorted(fi.items(), key=lambda x: -x[1])[:10]:
                print(f"    {k}: {v:.4f}")
    else:
        print(f"[meta] 학습 실패: {result.get('error')}")
    return result


def main():
    parser = argparse.ArgumentParser(description="Stage 6-B: 11 base + 메타 데이터 누수 차단 재학습")
    parser.add_argument("--cutoff", type=int, default=1100, help="학습 cutoff 회차 (기본 1100)")
    parser.add_argument("--meta-end", type=int, default=1200, help="메타 bootstrap 종료 회차 (기본 1200)")
    parser.add_argument("--skip-backup", action="store_true", help="백업 생략")
    parser.add_argument("--skip-base", action="store_true", help="11 base 재학습 생략 (메타만)")
    args = parser.parse_args()

    # Windows cp949 회피: stdout을 utf-8로 강제
    import io
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

    print("=" * 70)
    print(f"Stage 6-B Full Retrain - cutoff={args.cutoff}, meta_end={args.meta_end}")
    print("=" * 70)

    # 1. 백업
    if not args.skip_backup:
        backup_dir = os.path.join(
            config.MODEL_DIR, "_archive", f"stage6_b_{datetime.now().strftime('%Y-%m-%d')}"
        )
        backup_existing_weights(backup_dir)

    # 2. 데이터 로드
    print(f"\n[data] fetch_all_draws()")
    draws_all = fetch_all_draws()
    print(f"[data] total: {len(draws_all)} rounds")
    latest_round = max(int(d.get("round", 0)) for d in draws_all)
    print(f"[data] latest round: {latest_round}")

    draws_filtered = filter_draws_by_cutoff(draws_all, args.cutoff)
    print(f"[data] filtered (round<={args.cutoff}): {len(draws_filtered)} rounds")

    if len(draws_filtered) < 100:
        print(f"[ERROR] cutoff 회차 너무 적음 ({len(draws_filtered)} < 100)")
        return 1

    # 3. 11 base 재학습
    if not args.skip_base:
        retrain_result = retrain_all_base(draws_filtered, args.cutoff)
        if not retrain_result.get("success"):
            print(f"\n[FAILED] 11 base 재학습 실패: {retrain_result.get('error')}")
            return 1
        ensemble = retrain_result["ensemble"]
        print(f"\n[OK] 11 base 재학습 완료 ({retrain_result['elapsed']:.1f}s)")
    else:
        print(f"\n[SKIP] 11 base 재학습 생략, 기존 가중치로 메타 부트스트랩")
        from models.ensemble import LottoEnsemble
        ensemble = LottoEnsemble()

    # 4. 메타 로그 초기화 + 부트스트랩
    boot_result = reset_and_bootstrap_meta_log(draws_all, ensemble, args.cutoff, args.meta_end)
    if boot_result.get("added", 0) < 50:
        print(f"\n[WARN] 메타 부트스트랩 회차 부족: {boot_result['added']}")

    # 5. 메타러너 학습
    meta_result = train_meta_learner(boot_result["meta"])

    # 6. 최종 보고
    print("\n" + "=" * 70)
    print("Stage 6-B Retrain 완료")
    print("=" * 70)
    print(f"  11 base 재학습:      {'OK' if not args.skip_base else 'SKIPPED'}")
    print(f"  메타 bootstrap:     {boot_result.get('added', 0)} rounds")
    print(f"  메타러너 학습:       {'OK' if meta_result.get('success') else 'FAIL'}")
    print(f"\n다음: python langchain-backend/scripts/stage6_full_backtest.py --start 1201 --end 1210 (10회 미니 검증)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
