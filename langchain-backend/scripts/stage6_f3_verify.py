# -*- coding: utf-8 -*-
"""F-3 verification — strength 0.0/0.2/0.5/1.0/2.0 in same process."""
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

_GLOBAL = {"strength": 0.0}
_orig = NumberRecommender.select_recommendations

def _patched(self, *args, **kwargs):
    kwargs["gnn_diversity_strength"] = _GLOBAL["strength"]
    return _orig(self, *args, **kwargs)

NumberRecommender.select_recommendations = _patched

from scripts.stage6_full_backtest import run_single_round


def main():
    rounds = list(range(1201, 1223))
    draws_all = fetch_all_draws()
    pipeline = PredictorPipeline(feature_dim=24)
    try:
        pipeline.phase1.load_all(os.path.join(os.path.dirname(__file__), "..", "saved_models", "phase1"))
    except Exception:
        pass
    print("[init] LottoEnsemble singleton 로드...")
    ensemble = LottoEnsemble()

    strengths = [0.0, 0.2, 0.5, 1.0, 2.0]
    for s in strengths:
        _GLOBAL["strength"] = s
        results = []
        t0 = time.time()
        for r in rounds:
            results.append(run_single_round(r, draws_all, pipeline, ensemble=ensemble))
        valid = [x for x in results if not x.get("error")]
        hits = [x["hit_top5"] for x in valid]
        excls = [x["hit_exclude10"] for x in valid]
        top5_all = [n for x in valid for n in x["top5"]]
        # 첫 회차 picks 비교
        r1201 = next((x for x in valid if x["round"] == 1201), None)
        print(f"[s={s:.1f}] hit={float(np.mean(hits)):.3f}  excl={float(np.mean(excls)):.3f}  "
              f"uniq_t5={len(set(top5_all))}  R1201_picks={r1201['top5'] if r1201 else 'N/A'}  "
              f"({time.time()-t0:.1f}s)")


if __name__ == "__main__":
    main()
