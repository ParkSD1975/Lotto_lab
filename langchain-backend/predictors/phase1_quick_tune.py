"""Phase 1 predictor 빠른 가중치 튜닝 + 검증 게이트 테스트.

데이터 분할:
- train: 31~1050 (1020회차)
- validation: 1051~1100 (50회차) — 가중치 grid search
- test: 1101~1120 (20회차) — 게이트 측정
"""
import numpy as np
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
    (0.4, 0.4, 0.2),
    (0.3, 0.3, 0.4),
    (0.3, 0.4, 0.3),
    (0.2, 0.4, 0.4),
    (0.2, 0.3, 0.5),
    (0.15, 0.45, 0.40),  # 현재 기본값
    (0.1, 0.4, 0.5),
    (0.1, 0.3, 0.6),
]

def cross_entropy_safe(pred_dist, true_class):
    """7-class CE loss."""
    if not 0 <= true_class < 7:
        return 10.0  # invalid
    p = pred_dist[int(true_class)]
    return -np.log(max(p, 1e-9))

def tune_and_test_endings(draws, val_rounds, test_rounds):
    """endings_distribution: 10 카테고리 × grid search."""
    print("\n[1/5] endings_distribution (10 categories)")
    runner = BaselineRunner()

    # 카테고리별 최적 가중치 찾기
    best_weights_per_cat = {}

    for cat_idx in range(10):
        print(f"  digit_{cat_idx}: ", end="", flush=True)
        best_w = (0.2, 0.3, 0.5)  # fallback
        best_ce = 1e9

        # validation set에서 grid search
        for w_xgb, w_markov, w_freq in WEIGHT_GRID:
            ce_sum = 0
            n = 0
            for tr in val_rounds:
                hist = [d for d in draws if int(d.get("round", 0)) < tr]
                if len(hist) < 50:
                    continue

                p = EndingsDistributionPredictor()
                p.train(hist, 50)
                cm = p._extract(hist)
                s = cm[:, cat_idx]
                last = int(s[-1])

                # base 예측
                mp = p.markov_heads[cat_idx].predict(last)
                fp = _freq_dist_endings(s)

                xgb_prob = None
                if p.xgb_models and p.xgb_models[cat_idx] is not None:
                    X_query = p._build_features(cm, cat_idx, lookback=30)
                    if X_query is not None and len(X_query) > 0:
                        try:
                            raw = p.xgb_models[cat_idx].predict_proba(X_query[-1:])[0]
                            if len(raw) < 7:
                                xgb_prob = np.zeros(7)
                                xgb_prob[:len(raw)] = raw
                            else:
                                xgb_prob = raw[:7]
                            xgb_prob = xgb_prob / xgb_prob.sum()
                        except:
                            xgb_prob = None

                # 가중 결합
                if xgb_prob is not None:
                    ap = w_xgb * xgb_prob + w_markov * mp + w_freq * fp
                else:
                    ap = w_markov * mp + w_freq * fp
                ap = ap / ap.sum()

                # target
                tgt = next((d for d in draws if int(d["round"]) == tr), None)
                if tgt:
                    tc = sum(1 for x in tgt["numbers"] if x % 10 == cat_idx)
                    ce_sum += cross_entropy_safe(ap, tc)
                    n += 1

            if n > 0:
                avg_ce = ce_sum / n
                if avg_ce < best_ce:
                    best_ce = avg_ce
                    best_w = (w_xgb, w_markov, w_freq)

        best_weights_per_cat[cat_idx] = best_w
        print(f"best_w={best_w}, val_ce={best_ce:.4f}")

    # test set 측정 (카테고리별 + 전체 평균)
    cat_results = {}
    for cat_idx in range(10):
        pce_sum, fce_sum, n = 0, 0, 0
        w_xgb, w_markov, w_freq = best_weights_per_cat[cat_idx]

        for tr in test_rounds:
            hist = [d for d in draws if int(d.get("round", 0)) < tr]
            if len(hist) < 50:
                continue

            p = EndingsDistributionPredictor()
            p.train(hist, 50)
            cm = p._extract(hist)
            s = cm[:, cat_idx]
            last = int(s[-1])

            mp = p.markov_heads[cat_idx].predict(last)
            fp = _freq_dist_endings(s)

            xgb_prob = None
            if p.xgb_models and p.xgb_models[cat_idx] is not None:
                X_query = p._build_features(cm, cat_idx, lookback=30)
                if X_query is not None and len(X_query) > 0:
                    try:
                        raw = p.xgb_models[cat_idx].predict_proba(X_query[-1:])[0]
                        if len(raw) < 7:
                            xgb_prob = np.zeros(7)
                            xgb_prob[:len(raw)] = raw
                        else:
                            xgb_prob = raw[:7]
                        xgb_prob = xgb_prob / xgb_prob.sum()
                    except:
                        xgb_prob = None

            if xgb_prob is not None:
                ap = w_xgb * xgb_prob + w_markov * mp + w_freq * fp
            else:
                ap = w_markov * mp + w_freq * fp
            ap = ap / ap.sum()

            tgt = next((d for d in draws if int(d["round"]) == tr), None)
            if tgt:
                tc = sum(1 for x in tgt["numbers"] if x % 10 == cat_idx)
                pce_sum += cross_entropy_safe(ap, tc)
                fce_sum += cross_entropy_safe(fp, tc)
                n += 1

        if n > 0:
            cat_results[f"digit_{cat_idx}"] = {
                "predictor_ce": pce_sum / n,
                "frequency_ce": fce_sum / n,
                "n": n,
                "weights": best_weights_per_cat[cat_idx]
            }

    # 전체 평균
    avg_pce = np.mean([r["predictor_ce"] for r in cat_results.values()])
    avg_fce = np.mean([r["frequency_ce"] for r in cat_results.values()])

    return {
        "name": "endings_distribution",
        "avg_predictor_ce": avg_pce,
        "avg_frequency_ce": avg_fce,
        "improvement_pct": (avg_fce - avg_pce) / max(avg_fce, 1e-9) * 100,
        "wins": avg_pce < avg_fce,
        "per_category": cat_results
    }

def tune_and_test_high_low(draws, val_rounds, test_rounds):
    """high_low: 1 카테고리 — XGB 활성화."""
    print("\n[2/5] high_low (1 category)")
    runner = BaselineRunner()

    # validation set에서 grid search
    best_w = (0.2, 0.3, 0.5)
    best_ce = 1e9

    print("  low_count: ", end="", flush=True)
    for w_xgb, w_markov, w_freq in WEIGHT_GRID:
        ce_sum = 0
        n = 0
        for tr in val_rounds:
            hist = [d for d in draws if int(d.get("round", 0)) < tr]
            if len(hist) < 50:
                continue

            p = HighLowPredictor()
            p.train(hist, 50)
            seq = p._extract(hist)
            last = int(seq[-1])

            mp = p.markov.predict(last)
            fp = _freq_dist_hl(seq)

            xgb_prob = None
            if p.xgb_model is not None:
                X_query = p._build_features(seq, lookback=30)
                if X_query is not None and len(X_query) > 0:
                    try:
                        raw = p.xgb_model.predict_proba(X_query[-1:])[0]
                        if len(raw) < 7:
                            xgb_prob = np.zeros(7)
                            xgb_prob[:len(raw)] = raw
                        else:
                            xgb_prob = raw[:7]
                        xgb_prob = xgb_prob / xgb_prob.sum()
                    except:
                        xgb_prob = None

            if xgb_prob is not None:
                ap = w_xgb * xgb_prob + w_markov * mp + w_freq * fp
            else:
                ap = w_markov * mp + w_freq * fp
            ap = ap / ap.sum()

            tgt = next((d for d in draws if int(d["round"]) == tr), None)
            if tgt:
                tc = sum(1 for x in tgt["numbers"] if x in LOW_SET)
                ce_sum += cross_entropy_safe(ap, tc)
                n += 1

        if n > 0:
            avg_ce = ce_sum / n
            if avg_ce < best_ce:
                best_ce = avg_ce
                best_w = (w_xgb, w_markov, w_freq)

    print(f"best_w={best_w}, val_ce={best_ce:.4f}")

    # test set
    w_xgb, w_markov, w_freq = best_w
    pce_sum, fce_sum, n = 0, 0, 0

    for tr in test_rounds:
        hist = [d for d in draws if int(d.get("round", 0)) < tr]
        if len(hist) < 50:
            continue

        p = HighLowPredictor()
        p.train(hist, 50)
        seq = p._extract(hist)
        last = int(seq[-1])

        mp = p.markov.predict(last)
        fp = _freq_dist_hl(seq)

        xgb_prob = None
        if p.xgb_model is not None:
            X_query = p._build_features(seq, lookback=30)
            if X_query is not None and len(X_query) > 0:
                try:
                    raw = p.xgb_model.predict_proba(X_query[-1:])[0]
                    if len(raw) < 7:
                        xgb_prob = np.zeros(7)
                        xgb_prob[:len(raw)] = raw
                    else:
                        xgb_prob = raw[:7]
                    xgb_prob = xgb_prob / xgb_prob.sum()
                except:
                    xgb_prob = None

        if xgb_prob is not None:
            ap = w_xgb * xgb_prob + w_markov * mp + w_freq * fp
        else:
            ap = w_markov * mp + w_freq * fp
        ap = ap / ap.sum()

        tgt = next((d for d in draws if int(d["round"]) == tr), None)
        if tgt:
            tc = sum(1 for x in tgt["numbers"] if x in LOW_SET)
            pce_sum += cross_entropy_safe(ap, tc)
            fce_sum += cross_entropy_safe(fp, tc)
            n += 1

    avg_pce = pce_sum / n if n > 0 else 10.0
    avg_fce = fce_sum / n if n > 0 else 10.0

    return {
        "name": "high_low",
        "avg_predictor_ce": avg_pce,
        "avg_frequency_ce": avg_fce,
        "improvement_pct": (avg_fce - avg_pce) / max(avg_fce, 1e-9) * 100,
        "wins": avg_pce < avg_fce,
        "weights": best_w,
        "n": n
    }

def tune_and_test_odd_even(draws, val_rounds, test_rounds):
    """odd_even: 1 카테고리."""
    print("\n[3/5] odd_even (1 category)")

    best_w = (0.2, 0.3, 0.5)
    best_ce = 1e9

    print("  odd_count: ", end="", flush=True)
    for w_xgb, w_markov, w_freq in WEIGHT_GRID:
        ce_sum = 0
        n = 0
        for tr in val_rounds:
            hist = [d for d in draws if int(d.get("round", 0)) < tr]
            if len(hist) < 50:
                continue

            p = OddEvenPredictor()
            p.train(hist, 50)
            seq = p._extract(hist)
            last = int(seq[-1])

            mp = p.markov.predict(last)
            fp = _freq_dist_oe(seq)

            xgb_prob = None
            if p.xgb_model is not None:
                X_query = p._build_features(seq, lookback=30)
                if X_query is not None and len(X_query) > 0:
                    try:
                        raw = p.xgb_model.predict_proba(X_query[-1:])[0]
                        if len(raw) < 7:
                            xgb_prob = np.zeros(7)
                            xgb_prob[:len(raw)] = raw
                        else:
                            xgb_prob = raw[:7]
                        xgb_prob = xgb_prob / xgb_prob.sum()
                    except:
                        xgb_prob = None

            if xgb_prob is not None:
                ap = w_xgb * xgb_prob + w_markov * mp + w_freq * fp
            else:
                ap = w_markov * mp + w_freq * fp
            ap = ap / ap.sum()

            tgt = next((d for d in draws if int(d["round"]) == tr), None)
            if tgt:
                tc = sum(1 for x in tgt["numbers"] if x in ODD_SET)
                ce_sum += cross_entropy_safe(ap, tc)
                n += 1

        if n > 0:
            avg_ce = ce_sum / n
            if avg_ce < best_ce:
                best_ce = avg_ce
                best_w = (w_xgb, w_markov, w_freq)

    print(f"best_w={best_w}, val_ce={best_ce:.4f}")

    # test set
    w_xgb, w_markov, w_freq = best_w
    pce_sum, fce_sum, n = 0, 0, 0

    for tr in test_rounds:
        hist = [d for d in draws if int(d.get("round", 0)) < tr]
        if len(hist) < 50:
            continue

        p = OddEvenPredictor()
        p.train(hist, 50)
        seq = p._extract(hist)
        last = int(seq[-1])

        mp = p.markov.predict(last)
        fp = _freq_dist_oe(seq)

        xgb_prob = None
        if p.xgb_model is not None:
            X_query = p._build_features(seq, lookback=30)
            if X_query is not None and len(X_query) > 0:
                try:
                    raw = p.xgb_model.predict_proba(X_query[-1:])[0]
                    if len(raw) < 7:
                        xgb_prob = np.zeros(7)
                        xgb_prob[:len(raw)] = raw
                    else:
                        xgb_prob = raw[:7]
                    xgb_prob = xgb_prob / xgb_prob.sum()
                except:
                    xgb_prob = None

        if xgb_prob is not None:
            ap = w_xgb * xgb_prob + w_markov * mp + w_freq * fp
        else:
            ap = w_markov * mp + w_freq * fp
        ap = ap / ap.sum()

        tgt = next((d for d in draws if int(d["round"]) == tr), None)
        if tgt:
            tc = sum(1 for x in tgt["numbers"] if x in ODD_SET)
            pce_sum += cross_entropy_safe(ap, tc)
            fce_sum += cross_entropy_safe(fp, tc)
            n += 1

    avg_pce = pce_sum / n if n > 0 else 10.0
    avg_fce = fce_sum / n if n > 0 else 10.0

    return {
        "name": "odd_even",
        "avg_predictor_ce": avg_pce,
        "avg_frequency_ce": avg_fce,
        "improvement_pct": (avg_fce - avg_pce) / max(avg_fce, 1e-9) * 100,
        "wins": avg_pce < avg_fce,
        "weights": best_w,
        "n": n
    }

def tune_and_test_decade(draws, val_rounds, test_rounds):
    """decade: 5 카테고리."""
    print("\n[4/5] decade_distribution (5 categories)")

    best_weights_per_cat = {}

    for cat_idx in range(5):
        lab = f"{DECADE_RANGES[cat_idx][0]}-{DECADE_RANGES[cat_idx][1]}"
        print(f"  {lab}: ", end="", flush=True)
        best_w = (0.2, 0.3, 0.5)
        best_ce = 1e9

        for w_xgb, w_markov, w_freq in WEIGHT_GRID:
            ce_sum = 0
            n = 0
            for tr in val_rounds:
                hist = [d for d in draws if int(d.get("round", 0)) < tr]
                if len(hist) < 50:
                    continue

                p = DecadePredictor()
                p.train(hist, 50)
                cm = p._extract(hist)
                s = cm[:, cat_idx]
                last = int(s[-1])

                mp = p.markov_heads[cat_idx].predict(last)
                fp = _freq_dist_decade(s)

                xgb_prob = None
                if p.xgb_models and p.xgb_models[cat_idx] is not None:
                    X_query = p._build_features(cm, cat_idx, lookback=30)
                    if X_query is not None and len(X_query) > 0:
                        try:
                            raw = p.xgb_models[cat_idx].predict_proba(X_query[-1:])[0]
                            if len(raw) < 7:
                                xgb_prob = np.zeros(7)
                                xgb_prob[:len(raw)] = raw
                            else:
                                xgb_prob = raw[:7]
                            xgb_prob = xgb_prob / xgb_prob.sum()
                        except:
                            xgb_prob = None

                if xgb_prob is not None:
                    ap = w_xgb * xgb_prob + w_markov * mp + w_freq * fp
                else:
                    ap = w_markov * mp + w_freq * fp
                ap = ap / ap.sum()

                tgt = next((d for d in draws if int(d["round"]) == tr), None)
                if tgt:
                    lo, hi = DECADE_RANGES[cat_idx]
                    tc = sum(1 for x in tgt["numbers"] if lo <= x <= hi)
                    ce_sum += cross_entropy_safe(ap, tc)
                    n += 1

            if n > 0:
                avg_ce = ce_sum / n
                if avg_ce < best_ce:
                    best_ce = avg_ce
                    best_w = (w_xgb, w_markov, w_freq)

        best_weights_per_cat[cat_idx] = best_w
        print(f"best_w={best_w}, val_ce={best_ce:.4f}")

    # test set
    cat_results = {}
    for cat_idx in range(5):
        pce_sum, fce_sum, n = 0, 0, 0
        w_xgb, w_markov, w_freq = best_weights_per_cat[cat_idx]

        for tr in test_rounds:
            hist = [d for d in draws if int(d.get("round", 0)) < tr]
            if len(hist) < 50:
                continue

            p = DecadePredictor()
            p.train(hist, 50)
            cm = p._extract(hist)
            s = cm[:, cat_idx]
            last = int(s[-1])

            mp = p.markov_heads[cat_idx].predict(last)
            fp = _freq_dist_decade(s)

            xgb_prob = None
            if p.xgb_models and p.xgb_models[cat_idx] is not None:
                X_query = p._build_features(cm, cat_idx, lookback=30)
                if X_query is not None and len(X_query) > 0:
                    try:
                        raw = p.xgb_models[cat_idx].predict_proba(X_query[-1:])[0]
                        if len(raw) < 7:
                            xgb_prob = np.zeros(7)
                            xgb_prob[:len(raw)] = raw
                        else:
                            xgb_prob = raw[:7]
                        xgb_prob = xgb_prob / xgb_prob.sum()
                    except:
                        xgb_prob = None

            if xgb_prob is not None:
                ap = w_xgb * xgb_prob + w_markov * mp + w_freq * fp
            else:
                ap = w_markov * mp + w_freq * fp
            ap = ap / ap.sum()

            tgt = next((d for d in draws if int(d["round"]) == tr), None)
            if tgt:
                lo, hi = DECADE_RANGES[cat_idx]
                tc = sum(1 for x in tgt["numbers"] if lo <= x <= hi)
                pce_sum += cross_entropy_safe(ap, tc)
                fce_sum += cross_entropy_safe(fp, tc)
                n += 1

        if n > 0:
            lab = f"{DECADE_RANGES[cat_idx][0]}-{DECADE_RANGES[cat_idx][1]}"
            cat_results[lab] = {
                "predictor_ce": pce_sum / n,
                "frequency_ce": fce_sum / n,
                "n": n,
                "weights": best_weights_per_cat[cat_idx]
            }

    avg_pce = np.mean([r["predictor_ce"] for r in cat_results.values()])
    avg_fce = np.mean([r["frequency_ce"] for r in cat_results.values()])

    return {
        "name": "decade_distribution",
        "avg_predictor_ce": avg_pce,
        "avg_frequency_ce": avg_fce,
        "improvement_pct": (avg_fce - avg_pce) / max(avg_fce, 1e-9) * 100,
        "wins": avg_pce < avg_fce,
        "per_category": cat_results
    }

def tune_and_test_gung(draws, val_rounds, test_rounds):
    """gung: 9 카테고리."""
    print("\n[5/5] gung_distribution (9 categories)")

    best_weights_per_cat = {}

    for cat_idx in range(9):
        lab = f"gung_{cat_idx}"
        print(f"  {lab}: ", end="", flush=True)
        best_w = (0.2, 0.3, 0.5)
        best_ce = 1e9

        for w_xgb, w_markov, w_freq in WEIGHT_GRID:
            ce_sum = 0
            n = 0
            for tr in val_rounds:
                hist = [d for d in draws if int(d.get("round", 0)) < tr]
                if len(hist) < 50:
                    continue

                p = GungPredictor()
                p.train(hist, 50)
                cm = p._extract(hist)
                s = cm[:, cat_idx]
                last = int(s[-1])

                mp = p.markov_heads[cat_idx].predict(last)
                fp = _freq_dist_gung(s)

                xgb_prob = None
                if p.xgb_models and p.xgb_models[cat_idx] is not None:
                    X_query = p._build_features(cm, cat_idx, lookback=30)
                    if X_query is not None and len(X_query) > 0:
                        try:
                            raw = p.xgb_models[cat_idx].predict_proba(X_query[-1:])[0]
                            if len(raw) < 7:
                                xgb_prob = np.zeros(7)
                                xgb_prob[:len(raw)] = raw
                            else:
                                xgb_prob = raw[:7]
                            xgb_prob = xgb_prob / xgb_prob.sum()
                        except:
                            xgb_prob = None

                if xgb_prob is not None:
                    ap = w_xgb * xgb_prob + w_markov * mp + w_freq * fp
                else:
                    ap = w_markov * mp + w_freq * fp
                ap = ap / ap.sum()

                tgt = next((d for d in draws if int(d["round"]) == tr), None)
                if tgt:
                    lo, hi = GUNG_RANGES[cat_idx]
                    tc = sum(1 for x in tgt["numbers"] if lo <= x <= hi)
                    ce_sum += cross_entropy_safe(ap, tc)
                    n += 1

            if n > 0:
                avg_ce = ce_sum / n
                if avg_ce < best_ce:
                    best_ce = avg_ce
                    best_w = (w_xgb, w_markov, w_freq)

        best_weights_per_cat[cat_idx] = best_w
        print(f"best_w={best_w}, val_ce={best_ce:.4f}")

    # test set
    cat_results = {}
    for cat_idx in range(9):
        pce_sum, fce_sum, n = 0, 0, 0
        w_xgb, w_markov, w_freq = best_weights_per_cat[cat_idx]

        for tr in test_rounds:
            hist = [d for d in draws if int(d.get("round", 0)) < tr]
            if len(hist) < 50:
                continue

            p = GungPredictor()
            p.train(hist, 50)
            cm = p._extract(hist)
            s = cm[:, cat_idx]
            last = int(s[-1])

            mp = p.markov_heads[cat_idx].predict(last)
            fp = _freq_dist_gung(s)

            xgb_prob = None
            if p.xgb_models and p.xgb_models[cat_idx] is not None:
                X_query = p._build_features(cm, cat_idx, lookback=30)
                if X_query is not None and len(X_query) > 0:
                    try:
                        raw = p.xgb_models[cat_idx].predict_proba(X_query[-1:])[0]
                        if len(raw) < 7:
                            xgb_prob = np.zeros(7)
                            xgb_prob[:len(raw)] = raw
                        else:
                            xgb_prob = raw[:7]
                        xgb_prob = xgb_prob / xgb_prob.sum()
                    except:
                        xgb_prob = None

            if xgb_prob is not None:
                ap = w_xgb * xgb_prob + w_markov * mp + w_freq * fp
            else:
                ap = w_markov * mp + w_freq * fp
            ap = ap / ap.sum()

            tgt = next((d for d in draws if int(d["round"]) == tr), None)
            if tgt:
                lo, hi = GUNG_RANGES[cat_idx]
                tc = sum(1 for x in tgt["numbers"] if lo <= x <= hi)
                pce_sum += cross_entropy_safe(ap, tc)
                fce_sum += cross_entropy_safe(fp, tc)
                n += 1

        if n > 0:
            lab = f"gung_{cat_idx}"
            cat_results[lab] = {
                "predictor_ce": pce_sum / n,
                "frequency_ce": fce_sum / n,
                "n": n,
                "weights": best_weights_per_cat[cat_idx]
            }

    avg_pce = np.mean([r["predictor_ce"] for r in cat_results.values()])
    avg_fce = np.mean([r["frequency_ce"] for r in cat_results.values()])

    return {
        "name": "gung_distribution",
        "avg_predictor_ce": avg_pce,
        "avg_frequency_ce": avg_fce,
        "improvement_pct": (avg_fce - avg_pce) / max(avg_fce, 1e-9) * 100,
        "wins": avg_pce < avg_fce,
        "per_category": cat_results
    }

def main():
    print("Phase 1 빠른 가중치 튜닝 + 검증 게이트 (30분 박스)")
    print("=" * 70)

    start_time = time.time()

    # 데이터 로드
    draws = fetch_all_draws()
    if len(draws) < 1120:
        print(f"ERROR: 최소 1120 회차 필요, 현재 {len(draws)}회차")
        return

    # 데이터 분할
    val_rounds = list(range(1051, 1101))  # 50회차
    test_rounds = list(range(1101, 1121))  # 20회차

    print(f"\n데이터 분할:")
    print(f"  Train: 31~1050 (1020회차)")
    print(f"  Validation: 1051~1100 (50회차) - grid search")
    print(f"  Test: 1101~1120 (20회차) - 게이트 측정")
    print(f"\nGrid search 후보 가중치 (XGB, Markov, Freq):")
    for w in WEIGHT_GRID:
        print(f"  {w}")

    # 5개 predictor 튜닝 + 테스트
    results = []

    # 1. endings_distribution
    r1 = tune_and_test_endings(draws, val_rounds, test_rounds)
    results.append(r1)

    # 2. high_low
    r2 = tune_and_test_high_low(draws, val_rounds, test_rounds)
    results.append(r2)

    # 3. odd_even
    r3 = tune_and_test_odd_even(draws, val_rounds, test_rounds)
    results.append(r3)

    # 4. decade
    r4 = tune_and_test_decade(draws, val_rounds, test_rounds)
    results.append(r4)

    # 5. gung
    r5 = tune_and_test_gung(draws, val_rounds, test_rounds)
    results.append(r5)

    elapsed = time.time() - start_time

    # 결과 요약
    print("\n" + "=" * 70)
    print("최종 결과 (test set 20회차)")
    print("=" * 70)

    pass_count = 0
    for r in results:
        gate = "PASS" if r["wins"] else "FAIL"
        if r["wins"]:
            pass_count += 1
        print(f"\n{r['name']}:")
        print(f"  predictor_ce: {r['avg_predictor_ce']:.4f}")
        print(f"  frequency_ce: {r['avg_frequency_ce']:.4f}")
        print(f"  improvement: {r['improvement_pct']:+.2f}%")
        print(f"  게이트: {gate}")

        # 가중치 출력
        if "weights" in r:
            print(f"  최적 가중치: {r['weights']}")
        elif "per_category" in r:
            print(f"  카테고리별 최적 가중치:")
            for cat_name, cat_data in r["per_category"].items():
                if "weights" in cat_data:
                    print(f"    {cat_name}: {cat_data['weights']}")

    print("\n" + "=" * 70)
    print(f"PASS rate: {pass_count}/5")
    print(f"실행 시간: {elapsed:.1f}초 ({elapsed/60:.1f}분)")
    print("=" * 70)

if __name__ == "__main__":
    main()
