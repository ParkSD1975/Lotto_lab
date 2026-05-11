"""Phase 1 predictor 빠른 가중치 튜닝 (최적화 버전).

1회 학습 후 validation/test만 진행 → 10배 속도 향상
"""
import numpy as np
import sys
import warnings
warnings.filterwarnings('ignore')

from db.supabase_client import fetch_all_draws
from validation.baseline_runner import BaselineRunner

# 5개 predictor import
from predictors.phase1_endings_distribution import EndingsDistributionPredictor, DIGIT_POOL_SIZES, _freq_dist as _freq_dist_endings
from predictors.phase1_high_low import HighLowPredictor, LOW_SET, _freq_dist as _freq_dist_hl
from predictors.phase1_odd_even import OddEvenPredictor, ODD_SET, _freq_dist as _freq_dist_oe
from predictors.phase1_decade import DecadePredictor, DECADE_RANGES, _freq_dist as _freq_dist_decade
from predictors.phase1_gung import GungPredictor, GUNG_RANGES, _freq_dist as _freq_dist_gung

import time

# Grid search 후보 가중치 (XGB, Markov, Freq)
WEIGHT_GRID = [
    (0.5, 0.3, 0.2),
    (0.3, 0.3, 0.4),
    (0.2, 0.4, 0.4),
    (0.2, 0.3, 0.5),
    (0.15, 0.45, 0.40),  # 현재 기본값
    (0.1, 0.4, 0.5),
    (0.1, 0.3, 0.6),
]

def ce_safe(pred_dist, true_class):
    """7-class CE loss."""
    if not 0 <= true_class < 7:
        return 10.0
    p = pred_dist[int(true_class)]
    return -np.log(max(p, 1e-9))

def tune_endings(draws, val_rounds, test_rounds):
    """endings_distribution: 10 카테고리."""
    print("\n[1/5] endings_distribution")

    # 1회만 학습 (회차 1050까지)
    train_draws = [d for d in draws if int(d.get("round", 0)) <= 1050]
    p = EndingsDistributionPredictor()
    print(f"  Training on {len(train_draws)} rounds...", end="", flush=True)
    p.train(train_draws, 50)
    print(" Done")

    # validation: 카테고리별 최적 가중치 찾기
    best_w = {}
    for cat in range(10):
        best = (0.2, 0.3, 0.5)
        best_ce = 1e9
        for w in WEIGHT_GRID:
            ce_sum = 0
            n = 0
            for tr in val_rounds:
                hist = [d for d in draws if int(d.get("round", 0)) < tr]
                cm = p._extract(hist)
                s = cm[:, cat]
                last = int(s[-1])

                mp = p.markov_heads[cat].predict(last)
                fp = _freq_dist_endings(s)

                xgb_prob = None
                if p.xgb_models and p.xgb_models[cat]:
                    try:
                        X = p._build_features(cm, cat, 30)
                        if X is not None and len(X) > 0:
                            raw = p.xgb_models[cat].predict_proba(X[-1:])[0]
                            xgb_prob = np.zeros(7)
                            xgb_prob[:min(len(raw), 7)] = raw[:min(len(raw), 7)]
                            xgb_prob /= xgb_prob.sum()
                    except:
                        pass

                if xgb_prob is not None:
                    ap = w[0] * xgb_prob + w[1] * mp + w[2] * fp
                else:
                    ap = w[1] * mp + w[2] * fp
                ap /= ap.sum()

                tgt = next((d for d in draws if int(d["round"]) == tr), None)
                if tgt:
                    tc = sum(1 for x in tgt["numbers"] if x % 10 == cat)
                    ce_sum += ce_safe(ap, tc)
                    n += 1

            if n > 0:
                avg = ce_sum / n
                if avg < best_ce:
                    best_ce = avg
                    best = w

        best_w[cat] = best
        print(f"  digit_{cat}: {best} (val_ce={best_ce:.4f})")

    # test
    cat_res = {}
    for cat in range(10):
        w = best_w[cat]
        pce, fce, n = 0, 0, 0
        for tr in test_rounds:
            hist = [d for d in draws if int(d.get("round", 0)) < tr]
            cm = p._extract(hist)
            s = cm[:, cat]
            last = int(s[-1])

            mp = p.markov_heads[cat].predict(last)
            fp = _freq_dist_endings(s)

            xgb_prob = None
            if p.xgb_models and p.xgb_models[cat]:
                try:
                    X = p._build_features(cm, cat, 30)
                    if X is not None and len(X) > 0:
                        raw = p.xgb_models[cat].predict_proba(X[-1:])[0]
                        xgb_prob = np.zeros(7)
                        xgb_prob[:min(len(raw), 7)] = raw[:min(len(raw), 7)]
                        xgb_prob /= xgb_prob.sum()
                except:
                    pass

            if xgb_prob is not None:
                ap = w[0] * xgb_prob + w[1] * mp + w[2] * fp
            else:
                ap = w[1] * mp + w[2] * fp
            ap /= ap.sum()

            tgt = next((d for d in draws if int(d["round"]) == tr), None)
            if tgt:
                tc = sum(1 for x in tgt["numbers"] if x % 10 == cat)
                pce += ce_safe(ap, tc)
                fce += ce_safe(fp, tc)
                n += 1

        if n > 0:
            cat_res[f"digit_{cat}"] = {"pce": pce/n, "fce": fce/n, "w": w}

    avg_pce = np.mean([r["pce"] for r in cat_res.values()])
    avg_fce = np.mean([r["fce"] for r in cat_res.values()])

    return {
        "name": "endings_distribution",
        "pce": avg_pce,
        "fce": avg_fce,
        "imp": (avg_fce - avg_pce) / max(avg_fce, 1e-9) * 100,
        "wins": avg_pce < avg_fce,
        "cats": cat_res
    }

def tune_high_low(draws, val_rounds, test_rounds):
    """high_low: 1 카테고리."""
    print("\n[2/5] high_low")

    train_draws = [d for d in draws if int(d.get("round", 0)) <= 1050]
    p = HighLowPredictor()
    print(f"  Training on {len(train_draws)} rounds...", end="", flush=True)
    p.train(train_draws, 50)
    print(" Done")

    # validation
    best = (0.2, 0.3, 0.5)
    best_ce = 1e9
    for w in WEIGHT_GRID:
        ce_sum = 0
        n = 0
        for tr in val_rounds:
            hist = [d for d in draws if int(d.get("round", 0)) < tr]
            seq = p._extract(hist)
            last = int(seq[-1])

            mp = p.markov.predict(last)
            fp = _freq_dist_hl(seq)

            xgb_prob = None
            if p.xgb_model:
                try:
                    X = p._build_features(seq, 30)
                    if X is not None and len(X) > 0:
                        raw = p.xgb_model.predict_proba(X[-1:])[0]
                        xgb_prob = np.zeros(7)
                        xgb_prob[:min(len(raw), 7)] = raw[:min(len(raw), 7)]
                        xgb_prob /= xgb_prob.sum()
                except:
                    pass

            if xgb_prob is not None:
                ap = w[0] * xgb_prob + w[1] * mp + w[2] * fp
            else:
                ap = w[1] * mp + w[2] * fp
            ap /= ap.sum()

            tgt = next((d for d in draws if int(d["round"]) == tr), None)
            if tgt:
                tc = sum(1 for x in tgt["numbers"] if x in LOW_SET)
                ce_sum += ce_safe(ap, tc)
                n += 1

        if n > 0:
            avg = ce_sum / n
            if avg < best_ce:
                best_ce = avg
                best = w

    print(f"  best_w: {best} (val_ce={best_ce:.4f})")

    # test
    w = best
    pce, fce, n = 0, 0, 0
    for tr in test_rounds:
        hist = [d for d in draws if int(d.get("round", 0)) < tr]
        seq = p._extract(hist)
        last = int(seq[-1])

        mp = p.markov.predict(last)
        fp = _freq_dist_hl(seq)

        xgb_prob = None
        if p.xgb_model:
            try:
                X = p._build_features(seq, 30)
                if X is not None and len(X) > 0:
                    raw = p.xgb_model.predict_proba(X[-1:])[0]
                    xgb_prob = np.zeros(7)
                    xgb_prob[:min(len(raw), 7)] = raw[:min(len(raw), 7)]
                    xgb_prob /= xgb_prob.sum()
            except:
                pass

        if xgb_prob is not None:
            ap = w[0] * xgb_prob + w[1] * mp + w[2] * fp
        else:
            ap = w[1] * mp + w[2] * fp
        ap /= ap.sum()

        tgt = next((d for d in draws if int(d["round"]) == tr), None)
        if tgt:
            tc = sum(1 for x in tgt["numbers"] if x in LOW_SET)
            pce += ce_safe(ap, tc)
            fce += ce_safe(fp, tc)
            n += 1

    avg_pce = pce / n if n > 0 else 10.0
    avg_fce = fce / n if n > 0 else 10.0

    return {
        "name": "high_low",
        "pce": avg_pce,
        "fce": avg_fce,
        "imp": (avg_fce - avg_pce) / max(avg_fce, 1e-9) * 100,
        "wins": avg_pce < avg_fce,
        "w": best
    }

def tune_odd_even(draws, val_rounds, test_rounds):
    """odd_even: 1 카테고리."""
    print("\n[3/5] odd_even")

    train_draws = [d for d in draws if int(d.get("round", 0)) <= 1050]
    p = OddEvenPredictor()
    print(f"  Training on {len(train_draws)} rounds...", end="", flush=True)
    p.train(train_draws, 50)
    print(" Done")

    # validation
    best = (0.2, 0.3, 0.5)
    best_ce = 1e9
    for w in WEIGHT_GRID:
        ce_sum = 0
        n = 0
        for tr in val_rounds:
            hist = [d for d in draws if int(d.get("round", 0)) < tr]
            seq = p._extract(hist)
            last = int(seq[-1])

            mp = p.markov.predict(last)
            fp = _freq_dist_oe(seq)

            xgb_prob = None
            if p.xgb_model:
                try:
                    X = p._build_features(seq, 30)
                    if X is not None and len(X) > 0:
                        raw = p.xgb_model.predict_proba(X[-1:])[0]
                        xgb_prob = np.zeros(7)
                        xgb_prob[:min(len(raw), 7)] = raw[:min(len(raw), 7)]
                        xgb_prob /= xgb_prob.sum()
                except:
                    pass

            if xgb_prob is not None:
                ap = w[0] * xgb_prob + w[1] * mp + w[2] * fp
            else:
                ap = w[1] * mp + w[2] * fp
            ap /= ap.sum()

            tgt = next((d for d in draws if int(d["round"]) == tr), None)
            if tgt:
                tc = sum(1 for x in tgt["numbers"] if x in ODD_SET)
                ce_sum += ce_safe(ap, tc)
                n += 1

        if n > 0:
            avg = ce_sum / n
            if avg < best_ce:
                best_ce = avg
                best = w

    print(f"  best_w: {best} (val_ce={best_ce:.4f})")

    # test
    w = best
    pce, fce, n = 0, 0, 0
    for tr in test_rounds:
        hist = [d for d in draws if int(d.get("round", 0)) < tr]
        seq = p._extract(hist)
        last = int(seq[-1])

        mp = p.markov.predict(last)
        fp = _freq_dist_oe(seq)

        xgb_prob = None
        if p.xgb_model:
            try:
                X = p._build_features(seq, 30)
                if X is not None and len(X) > 0:
                    raw = p.xgb_model.predict_proba(X[-1:])[0]
                    xgb_prob = np.zeros(7)
                    xgb_prob[:min(len(raw), 7)] = raw[:min(len(raw), 7)]
                    xgb_prob /= xgb_prob.sum()
            except:
                pass

        if xgb_prob is not None:
            ap = w[0] * xgb_prob + w[1] * mp + w[2] * fp
        else:
            ap = w[1] * mp + w[2] * fp
        ap /= ap.sum()

        tgt = next((d for d in draws if int(d["round"]) == tr), None)
        if tgt:
            tc = sum(1 for x in tgt["numbers"] if x in ODD_SET)
            pce += ce_safe(ap, tc)
            fce += ce_safe(fp, tc)
            n += 1

    avg_pce = pce / n if n > 0 else 10.0
    avg_fce = fce / n if n > 0 else 10.0

    return {
        "name": "odd_even",
        "pce": avg_pce,
        "fce": avg_fce,
        "imp": (avg_fce - avg_pce) / max(avg_fce, 1e-9) * 100,
        "wins": avg_pce < avg_fce,
        "w": best
    }

def tune_decade(draws, val_rounds, test_rounds):
    """decade: 5 카테고리."""
    print("\n[4/5] decade")

    train_draws = [d for d in draws if int(d.get("round", 0)) <= 1050]
    p = DecadePredictor()
    print(f"  Training on {len(train_draws)} rounds...", end="", flush=True)
    p.train(train_draws, 50)
    print(" Done")

    # validation
    best_w = {}
    for cat in range(5):
        best = (0.2, 0.3, 0.5)
        best_ce = 1e9
        for w in WEIGHT_GRID:
            ce_sum = 0
            n = 0
            for tr in val_rounds:
                hist = [d for d in draws if int(d.get("round", 0)) < tr]
                cm = p._extract(hist)
                s = cm[:, cat]
                last = int(s[-1])

                mp = p.markov_heads[cat].predict(last)
                fp = _freq_dist_decade(s)

                xgb_prob = None
                if p.xgb_models and p.xgb_models[cat]:
                    try:
                        X = p._build_features(cm, cat, 30)
                        if X is not None and len(X) > 0:
                            raw = p.xgb_models[cat].predict_proba(X[-1:])[0]
                            xgb_prob = np.zeros(7)
                            xgb_prob[:min(len(raw), 7)] = raw[:min(len(raw), 7)]
                            xgb_prob /= xgb_prob.sum()
                    except:
                        pass

                if xgb_prob is not None:
                    ap = w[0] * xgb_prob + w[1] * mp + w[2] * fp
                else:
                    ap = w[1] * mp + w[2] * fp
                ap /= ap.sum()

                tgt = next((d for d in draws if int(d["round"]) == tr), None)
                if tgt:
                    lo, hi = DECADE_RANGES[cat]
                    tc = sum(1 for x in tgt["numbers"] if lo <= x <= hi)
                    ce_sum += ce_safe(ap, tc)
                    n += 1

            if n > 0:
                avg = ce_sum / n
                if avg < best_ce:
                    best_ce = avg
                    best = w

        best_w[cat] = best
        lab = f"{DECADE_RANGES[cat][0]}-{DECADE_RANGES[cat][1]}"
        print(f"  {lab}: {best} (val_ce={best_ce:.4f})")

    # test
    cat_res = {}
    for cat in range(5):
        w = best_w[cat]
        pce, fce, n = 0, 0, 0
        for tr in test_rounds:
            hist = [d for d in draws if int(d.get("round", 0)) < tr]
            cm = p._extract(hist)
            s = cm[:, cat]
            last = int(s[-1])

            mp = p.markov_heads[cat].predict(last)
            fp = _freq_dist_decade(s)

            xgb_prob = None
            if p.xgb_models and p.xgb_models[cat]:
                try:
                    X = p._build_features(cm, cat, 30)
                    if X is not None and len(X) > 0:
                        raw = p.xgb_models[cat].predict_proba(X[-1:])[0]
                        xgb_prob = np.zeros(7)
                        xgb_prob[:min(len(raw), 7)] = raw[:min(len(raw), 7)]
                        xgb_prob /= xgb_prob.sum()
                except:
                    pass

            if xgb_prob is not None:
                ap = w[0] * xgb_prob + w[1] * mp + w[2] * fp
            else:
                ap = w[1] * mp + w[2] * fp
            ap /= ap.sum()

            tgt = next((d for d in draws if int(d["round"]) == tr), None)
            if tgt:
                lo, hi = DECADE_RANGES[cat]
                tc = sum(1 for x in tgt["numbers"] if lo <= x <= hi)
                pce += ce_safe(ap, tc)
                fce += ce_safe(fp, tc)
                n += 1

        if n > 0:
            lab = f"{DECADE_RANGES[cat][0]}-{DECADE_RANGES[cat][1]}"
            cat_res[lab] = {"pce": pce/n, "fce": fce/n, "w": w}

    avg_pce = np.mean([r["pce"] for r in cat_res.values()])
    avg_fce = np.mean([r["fce"] for r in cat_res.values()])

    return {
        "name": "decade_distribution",
        "pce": avg_pce,
        "fce": avg_fce,
        "imp": (avg_fce - avg_pce) / max(avg_fce, 1e-9) * 100,
        "wins": avg_pce < avg_fce,
        "cats": cat_res
    }

def tune_gung(draws, val_rounds, test_rounds):
    """gung: 9 카테고리."""
    print("\n[5/5] gung")

    train_draws = [d for d in draws if int(d.get("round", 0)) <= 1050]
    p = GungPredictor()
    print(f"  Training on {len(train_draws)} rounds...", end="", flush=True)
    p.train(train_draws, 50)
    print(" Done")

    # validation
    best_w = {}
    for cat in range(9):
        best = (0.2, 0.3, 0.5)
        best_ce = 1e9
        for w in WEIGHT_GRID:
            ce_sum = 0
            n = 0
            for tr in val_rounds:
                hist = [d for d in draws if int(d.get("round", 0)) < tr]
                cm = p._extract(hist)
                s = cm[:, cat]
                last = int(s[-1])

                mp = p.markov_heads[cat].predict(last)
                fp = _freq_dist_gung(s)

                xgb_prob = None
                if p.xgb_models and p.xgb_models[cat]:
                    try:
                        X = p._build_features(cm, cat, 30)
                        if X is not None and len(X) > 0:
                            raw = p.xgb_models[cat].predict_proba(X[-1:])[0]
                            xgb_prob = np.zeros(7)
                            xgb_prob[:min(len(raw), 7)] = raw[:min(len(raw), 7)]
                            xgb_prob /= xgb_prob.sum()
                    except:
                        pass

                if xgb_prob is not None:
                    ap = w[0] * xgb_prob + w[1] * mp + w[2] * fp
                else:
                    ap = w[1] * mp + w[2] * fp
                ap /= ap.sum()

                tgt = next((d for d in draws if int(d["round"]) == tr), None)
                if tgt:
                    lo, hi = GUNG_RANGES[cat]
                    tc = sum(1 for x in tgt["numbers"] if lo <= x <= hi)
                    ce_sum += ce_safe(ap, tc)
                    n += 1

            if n > 0:
                avg = ce_sum / n
                if avg < best_ce:
                    best_ce = avg
                    best = w

        best_w[cat] = best
        print(f"  gung_{cat}: {best} (val_ce={best_ce:.4f})")

    # test
    cat_res = {}
    for cat in range(9):
        w = best_w[cat]
        pce, fce, n = 0, 0, 0
        for tr in test_rounds:
            hist = [d for d in draws if int(d.get("round", 0)) < tr]
            cm = p._extract(hist)
            s = cm[:, cat]
            last = int(s[-1])

            mp = p.markov_heads[cat].predict(last)
            fp = _freq_dist_gung(s)

            xgb_prob = None
            if p.xgb_models and p.xgb_models[cat]:
                try:
                    X = p._build_features(cm, cat, 30)
                    if X is not None and len(X) > 0:
                        raw = p.xgb_models[cat].predict_proba(X[-1:])[0]
                        xgb_prob = np.zeros(7)
                        xgb_prob[:min(len(raw), 7)] = raw[:min(len(raw), 7)]
                        xgb_prob /= xgb_prob.sum()
                except:
                    pass

            if xgb_prob is not None:
                ap = w[0] * xgb_prob + w[1] * mp + w[2] * fp
            else:
                ap = w[1] * mp + w[2] * fp
            ap /= ap.sum()

            tgt = next((d for d in draws if int(d["round"]) == tr), None)
            if tgt:
                lo, hi = GUNG_RANGES[cat]
                tc = sum(1 for x in tgt["numbers"] if lo <= x <= hi)
                pce += ce_safe(ap, tc)
                fce += ce_safe(fp, tc)
                n += 1

        if n > 0:
            lab = f"gung_{cat}"
            cat_res[lab] = {"pce": pce/n, "fce": fce/n, "w": w}

    avg_pce = np.mean([r["pce"] for r in cat_res.values()])
    avg_fce = np.mean([r["fce"] for r in cat_res.values()])

    return {
        "name": "gung_distribution",
        "pce": avg_pce,
        "fce": avg_fce,
        "imp": (avg_fce - avg_pce) / max(avg_fce, 1e-9) * 100,
        "wins": avg_pce < avg_fce,
        "cats": cat_res
    }

def main():
    print("Phase 1 Fast Tune (30min box)")
    print("=" * 60)

    start = time.time()

    draws = fetch_all_draws()
    if len(draws) < 1120:
        print(f"ERROR: need 1120 rounds, got {len(draws)}")
        return

    val_rounds = list(range(1051, 1101))  # 50
    test_rounds = list(range(1101, 1121))  # 20

    print(f"\nData split:")
    print(f"  Train: 31-1050 (1020 rounds)")
    print(f"  Val:   1051-1100 (50 rounds)")
    print(f"  Test:  1101-1120 (20 rounds)")
    print(f"\nWeight grid ({len(WEIGHT_GRID)} candidates):")
    for w in WEIGHT_GRID:
        print(f"  {w}")

    results = []

    r1 = tune_endings(draws, val_rounds, test_rounds)
    results.append(r1)

    r2 = tune_high_low(draws, val_rounds, test_rounds)
    results.append(r2)

    r3 = tune_odd_even(draws, val_rounds, test_rounds)
    results.append(r3)

    r4 = tune_decade(draws, val_rounds, test_rounds)
    results.append(r4)

    r5 = tune_gung(draws, val_rounds, test_rounds)
    results.append(r5)

    elapsed = time.time() - start

    print("\n" + "=" * 60)
    print("FINAL RESULTS (test set 20 rounds)")
    print("=" * 60)

    pass_count = 0
    for r in results:
        gate = "PASS" if r["wins"] else "FAIL"
        if r["wins"]:
            pass_count += 1
        print(f"\n{r['name']}:")
        print(f"  predictor_ce: {r['pce']:.4f}")
        print(f"  frequency_ce: {r['fce']:.4f}")
        print(f"  improvement:  {r['imp']:+.2f}%")
        print(f"  GATE: {gate}")

        if "w" in r:
            print(f"  best_weight: {r['w']}")
        elif "cats" in r:
            print(f"  category weights:")
            for cn, cd in r["cats"].items():
                print(f"    {cn}: {cd['w']}")

    print("\n" + "=" * 60)
    print(f"PASS rate: {pass_count}/5")
    print(f"Time: {elapsed:.1f}s ({elapsed/60:.1f}min)")
    print("=" * 60)

if __name__ == "__main__":
    main()
