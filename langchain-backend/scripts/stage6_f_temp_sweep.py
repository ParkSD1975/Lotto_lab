# -*- coding: utf-8 -*-
"""Stage 6-F-1 — Diversity Temperature Sweep

stage6_full_backtest.run_single_round을 monkey-patch로 temperature 주입.

각 T에 대해 1201~1222 22회 backtest, hit / excl_hit / unique 번호 수 기록.
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
from collections import Counter

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np

from db.supabase_client import fetch_all_draws
from models.ensemble import LottoEnsemble
from models.number_recommender import NumberRecommender
from predictors.predictor_pipeline import PredictorPipeline


# ★ select_recommendations / select_exclusions를 wrap해 temperature 글로벌 주입
_GLOBAL_TEMPERATURE = {"T": 0.04}

_orig_select_rec = NumberRecommender.select_recommendations
_orig_select_exc = NumberRecommender.select_exclusions


def _patched_select_rec(self, *args, **kwargs):
    kwargs["diversity_temperature"] = _GLOBAL_TEMPERATURE["T"]
    return _orig_select_rec(self, *args, **kwargs)


def _patched_select_exc(self, *args, **kwargs):
    kwargs["diversity_temperature"] = _GLOBAL_TEMPERATURE["T"]
    return _orig_select_exc(self, *args, **kwargs)


NumberRecommender.select_recommendations = _patched_select_rec
NumberRecommender.select_exclusions = _patched_select_exc

# ★ run_single_round 재사용
from scripts.stage6_full_backtest import run_single_round


def run_sweep_for_temperature(
    temperature: float,
    rounds: list[int],
    draws_all: list,
    pipeline: PredictorPipeline,
    ensemble: LottoEnsemble,
) -> dict:
    """단일 temperature로 모든 회차 백테스트."""
    _GLOBAL_TEMPERATURE["T"] = temperature
    results = []
    t0 = time.time()
    for round_no in rounds:
        r = run_single_round(round_no, draws_all, pipeline, ensemble=ensemble)
        results.append(r)

    valid = [r for r in results if not r.get("error")]
    hits = [r["hit_top5"] for r in valid]
    excls = [r["hit_exclude10"] for r in valid]

    top5_all = [n for r in valid for n in r["top5"]]
    excl_all = [n for r in valid for n in r["exclude10"]]

    return {
        "temperature": temperature,
        "n_rounds": len(valid),
        "avg_hit_top5": float(np.mean(hits)) if hits else 0.0,
        "avg_hit_excl10": float(np.mean(excls)) if excls else 0.0,
        "hit_dist": dict(Counter(hits)),
        "unique_top5": len(set(top5_all)),
        "unique_excl10": len(set(excl_all)),
        "elapsed_sec": time.time() - t0,
    }


def main():
    temperatures = [0.02, 0.04, 0.06, 0.08, 0.12, 0.20]
    rounds = list(range(1201, 1223))

    print("=" * 70)
    print("Stage 6-F-1 — Diversity Temperature Sweep")
    print(f"Temperatures: {temperatures}")
    print(f"Rounds: {rounds[0]}~{rounds[-1]} ({len(rounds)} rounds)")
    print("=" * 70)

    print("\n[init] 데이터 + 모델 로드...")
    draws_all = fetch_all_draws()

    pipeline = PredictorPipeline(feature_dim=24)
    try:
        phase1_dir = os.path.join(os.path.dirname(__file__), "..", "saved_models", "phase1")
        pipeline.phase1.load_all(phase1_dir)
        print(f"[init] Phase1 predictors loaded")
    except Exception as e:
        print(f"[init] Phase1 load skip: {e}")

    print("[init] LottoEnsemble singleton 로드 중...")
    t0 = time.time()
    ensemble = LottoEnsemble()
    print(f"[init] LottoEnsemble 로드 완료: {time.time() - t0:.1f}초")

    sweep_results = {}
    for T in temperatures:
        print(f"\n[sweep] T={T:.2f}: 백테스트 시작...")
        result = run_sweep_for_temperature(T, rounds, draws_all, pipeline, ensemble)
        sweep_results[f"{T:.2f}"] = result
        print(f"[sweep] T={T:.2f}: hit_top5={result['avg_hit_top5']:.3f}, "
              f"hit_excl10={result['avg_hit_excl10']:.3f}, "
              f"uniq_t5={result['unique_top5']}, "
              f"uniq_e10={result['unique_excl10']}, "
              f"elapsed={result['elapsed_sec']:.1f}s")

    # 요약 표
    print("\n" + "=" * 70)
    print("Sweep Summary")
    print("=" * 70)
    print(f"{'T':>6} | {'hit_top5':>9} | {'excl_hit':>9} | {'uniq_t5':>8} | {'uniq_e10':>9} | {'hit_dist'}")
    print("-" * 70)
    for T_str, r in sweep_results.items():
        hd = ", ".join(f"{k}:{v}" for k, v in sorted(r["hit_dist"].items(), key=lambda x: int(x[0])))
        print(f"{float(T_str):>6.2f} | {r['avg_hit_top5']:>9.3f} | {r['avg_hit_excl10']:>9.3f} | "
              f"{r['unique_top5']:>8} | {r['unique_excl10']:>9} | {hd}")

    best_hit = max(sweep_results.items(), key=lambda kv: kv[1]["avg_hit_top5"])
    best_combined = max(sweep_results.items(),
                       key=lambda kv: kv[1]["avg_hit_top5"] - 0.3 * kv[1]["avg_hit_excl10"])
    print(f"\n최적 (hit_top5 최대): T={best_hit[0]} hit={best_hit[1]['avg_hit_top5']:.3f}")
    print(f"최적 (종합 hit-0.3*excl): T={best_combined[0]} score={best_combined[1]['avg_hit_top5'] - 0.3 * best_combined[1]['avg_hit_excl10']:.4f}")

    out_path = os.path.join(os.path.dirname(__file__), "..", "saved_models", "stage6_f_temp_sweep.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(sweep_results, f, indent=2, ensure_ascii=False)
    print(f"\n결과 저장: {out_path}")


if __name__ == "__main__":
    main()
