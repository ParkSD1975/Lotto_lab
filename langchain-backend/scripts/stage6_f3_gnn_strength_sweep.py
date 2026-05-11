# -*- coding: utf-8 -*-
"""Stage 6-F-3 — GNN diversity strength sweep.

T=0.06 고정, gnn_diversity_strength=[0.0, 0.1, 0.2, 0.3, 0.5] sweep.
"""
from __future__ import annotations
import io, json, os, sys, time
from collections import Counter

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
from db.supabase_client import fetch_all_draws
from models.ensemble import LottoEnsemble
from models.number_recommender import NumberRecommender
from predictors.predictor_pipeline import PredictorPipeline

_GLOBAL = {"strength": 0.5, "T": 0.06}
_orig_rec = NumberRecommender.select_recommendations
_orig_exc = NumberRecommender.select_exclusions

def _patched_rec(self, *args, **kwargs):
    kwargs["diversity_temperature"] = _GLOBAL["T"]
    kwargs["gnn_diversity_strength"] = _GLOBAL["strength"]
    return _orig_rec(self, *args, **kwargs)

def _patched_exc(self, *args, **kwargs):
    kwargs["diversity_temperature"] = _GLOBAL["T"]
    return _orig_exc(self, *args, **kwargs)

NumberRecommender.select_recommendations = _patched_rec
NumberRecommender.select_exclusions = _patched_exc

from scripts.stage6_full_backtest import run_single_round


def run_for_strength(strength, rounds, draws_all, pipeline, ensemble):
    _GLOBAL["strength"] = strength
    results = []
    t0 = time.time()
    for r in rounds:
        results.append(run_single_round(r, draws_all, pipeline, ensemble=ensemble))
    valid = [x for x in results if not x.get("error")]
    hits = [x["hit_top5"] for x in valid]
    excls = [x["hit_exclude10"] for x in valid]
    top5_all = [n for x in valid for n in x["top5"]]
    excl_all = [n for x in valid for n in x["exclude10"]]
    return {
        "strength": strength,
        "avg_hit_top5": float(np.mean(hits)) if hits else 0.0,
        "avg_hit_excl10": float(np.mean(excls)) if excls else 0.0,
        "hit_dist": dict(Counter(hits)),
        "unique_top5": len(set(top5_all)),
        "unique_excl10": len(set(excl_all)),
        "elapsed_sec": time.time() - t0,
    }


def main():
    strengths = [0.0, 0.1, 0.2, 0.3, 0.5]
    rounds = list(range(1201, 1223))
    print("=" * 70)
    print(f"Stage 6-F-3 GNN diversity strength sweep (T=0.06)")
    print(f"Strengths: {strengths}")
    print(f"Rounds: {rounds[0]}~{rounds[-1]}")
    print("=" * 70)

    draws_all = fetch_all_draws()
    pipeline = PredictorPipeline(feature_dim=24)
    try:
        pipeline.phase1.load_all(os.path.join(os.path.dirname(__file__), "..", "saved_models", "phase1"))
    except Exception:
        pass
    print("[init] LottoEnsemble singleton 로드 중...")
    t0 = time.time()
    ensemble = LottoEnsemble()
    print(f"[init] 로드 완료: {time.time()-t0:.1f}초")

    results = {}
    for s in strengths:
        print(f"\n[sweep] strength={s:.1f}: 시작")
        r = run_for_strength(s, rounds, draws_all, pipeline, ensemble)
        results[f"{s:.1f}"] = r
        print(f"[sweep] strength={s:.1f}: hit={r['avg_hit_top5']:.3f}, "
              f"excl={r['avg_hit_excl10']:.3f}, "
              f"uniq_t5={r['unique_top5']}, "
              f"uniq_e10={r['unique_excl10']}, "
              f"elapsed={r['elapsed_sec']:.1f}s")

    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    print(f"{'strength':>9} | {'hit_top5':>9} | {'excl_hit':>9} | {'uniq_t5':>8} | {'uniq_e10':>9}")
    print("-" * 60)
    for s_str, r in results.items():
        print(f"{float(s_str):>9.1f} | {r['avg_hit_top5']:>9.3f} | {r['avg_hit_excl10']:>9.3f} | "
              f"{r['unique_top5']:>8} | {r['unique_excl10']:>9}")

    best = max(results.items(), key=lambda kv: kv[1]["avg_hit_top5"])
    print(f"\n최적 (hit 최대): strength={best[0]} hit={best[1]['avg_hit_top5']:.3f}")

    out_path = os.path.join(os.path.dirname(__file__), "..", "saved_models", "stage6_f3_gnn_strength_sweep.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"저장: {out_path}")


if __name__ == "__main__":
    main()
