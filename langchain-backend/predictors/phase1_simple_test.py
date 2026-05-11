"""Phase 1 predictor 단순 테스트 - 몇 가지 고정 가중치만 test set에서 비교.

시간 절약을 위해 validation skip, test set에서 직접 3가지 가중치만 비교.
"""
import numpy as np
import warnings
warnings.filterwarnings('ignore')

from db.supabase_client import fetch_all_draws
from validation.baseline_runner import BaselineRunner

from predictors.phase1_endings_distribution import EndingsDistributionPredictor, DIGIT_POOL_SIZES, _freq_dist as _freq_dist_endings
from predictors.phase1_high_low import HighLowPredictor, LOW_SET, _freq_dist as _freq_dist_hl
from predictors.phase1_odd_even import OddEvenPredictor, ODD_SET, _freq_dist as _freq_dist_oe
from predictors.phase1_decade import DecadePredictor, DECADE_RANGES, _freq_dist as _freq_dist_decade
from predictors.phase1_gung import GungPredictor, GUNG_RANGES, _freq_dist as _freq_dist_gung

import time

# 간단한 가중치 후보 3가지만 (XGB, Markov, Freq)
WEIGHT_CANDIDATES = [
    ("freq_heavy", (0.1, 0.3, 0.6)),  # 주파수 중심
    ("balanced", (0.2, 0.4, 0.4)),     # 균형
    ("current", (0.15, 0.45, 0.40)),   # 현재 기본값
]

def ce_safe(pred_dist, true_class):
    if not 0 <= true_class < 7:
        return 10.0
    p = pred_dist[int(true_class)]
    return -np.log(max(p, 1e-9))

def test_one_predictor(pred_class, extract_fn, freq_fn, target_fn, test_rounds, draws, num_cats, cat_labels):
    """하나의 predictor 테스트."""
    print(f"\n[{pred_class.__name__}]")

    # 1회 학습
    train_draws = [d for d in draws if int(d.get("round", 0)) <= 1100]
    p = pred_class()
    print(f"  Training on {len(train_draws)} rounds...", end="", flush=True)
    p.train(train_draws, 50)
    print(" Done")

    # 각 카테고리별로 3가지 가중치 테스트
    cat_results = {}

    for cat_idx in range(num_cats):
        cat_label = cat_labels[cat_idx]
        best_name = ""
        best_w = (0, 0, 0)
        best_ce = 1e9

        for w_name, w in WEIGHT_CANDIDATES:
            pce_sum = 0
            n = 0

            for tr in test_rounds:
                hist = [d for d in draws if int(d.get("round", 0)) < tr]

                # 예측 분포 계산
                if num_cats > 1:  # multi-category
                    cm = extract_fn(p, hist)
                    s = cm[:, cat_idx]
                    last = int(s[-1])
                    mp = p.markov_heads[cat_idx].predict(last)
                    fp = freq_fn(s)

                    xgb_prob = None
                    if hasattr(p, 'xgb_models') and p.xgb_models and p.xgb_models[cat_idx]:
                        try:
                            X = p._build_features(cm, cat_idx, 30)
                            if X is not None and len(X) > 0:
                                raw = p.xgb_models[cat_idx].predict_proba(X[-1:])[0]
                                xgb_prob = np.zeros(7)
                                xgb_prob[:min(len(raw), 7)] = raw[:min(len(raw), 7)]
                                xgb_prob /= xgb_prob.sum()
                        except:
                            pass
                else:  # single-category
                    seq = extract_fn(p, hist)
                    last = int(seq[-1])
                    mp = p.markov.predict(last)
                    fp = freq_fn(seq)

                    xgb_prob = None
                    if hasattr(p, 'xgb_model') and p.xgb_model:
                        try:
                            X = p._build_features(seq, 30)
                            if X is not None and len(X) > 0:
                                raw = p.xgb_model.predict_proba(X[-1:])[0]
                                xgb_prob = np.zeros(7)
                                xgb_prob[:min(len(raw), 7)] = raw[:min(len(raw), 7)]
                                xgb_prob /= xgb_prob.sum()
                        except:
                            pass

                # 가중 결합
                if xgb_prob is not None:
                    ap = w[0] * xgb_prob + w[1] * mp + w[2] * fp
                else:
                    ap = w[1] * mp + w[2] * fp
                ap /= ap.sum()

                # target 계산
                tgt = next((d for d in draws if int(d["round"]) == tr), None)
                if tgt:
                    tc = target_fn(tgt, cat_idx)
                    pce_sum += ce_safe(ap, tc)
                    n += 1

            if n > 0:
                avg_ce = pce_sum / n
                if avg_ce < best_ce:
                    best_ce = avg_ce
                    best_name = w_name
                    best_w = w

        # 최적 가중치로 frequency baseline과 비교
        fce_sum = 0
        pce_sum = 0
        n = 0

        for tr in test_rounds:
            hist = [d for d in draws if int(d.get("round", 0)) < tr]

            if num_cats > 1:
                cm = extract_fn(p, hist)
                s = cm[:, cat_idx]
                last = int(s[-1])
                mp = p.markov_heads[cat_idx].predict(last)
                fp = freq_fn(s)

                xgb_prob = None
                if hasattr(p, 'xgb_models') and p.xgb_models and p.xgb_models[cat_idx]:
                    try:
                        X = p._build_features(cm, cat_idx, 30)
                        if X is not None and len(X) > 0:
                            raw = p.xgb_models[cat_idx].predict_proba(X[-1:])[0]
                            xgb_prob = np.zeros(7)
                            xgb_prob[:min(len(raw), 7)] = raw[:min(len(raw), 7)]
                            xgb_prob /= xgb_prob.sum()
                    except:
                        pass
            else:
                seq = extract_fn(p, hist)
                last = int(seq[-1])
                mp = p.markov.predict(last)
                fp = freq_fn(seq)

                xgb_prob = None
                if hasattr(p, 'xgb_model') and p.xgb_model:
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
                ap = best_w[0] * xgb_prob + best_w[1] * mp + best_w[2] * fp
            else:
                ap = best_w[1] * mp + best_w[2] * fp
            ap /= ap.sum()

            tgt = next((d for d in draws if int(d["round"]) == tr), None)
            if tgt:
                tc = target_fn(tgt, cat_idx)
                pce_sum += ce_safe(ap, tc)
                fce_sum += ce_safe(fp, tc)
                n += 1

        if n > 0:
            avg_pce = pce_sum / n
            avg_fce = fce_sum / n
            cat_results[cat_label] = {
                "pce": avg_pce,
                "fce": avg_fce,
                "w": best_w,
                "w_name": best_name
            }
            print(f"  {cat_label}: {best_name} {best_w} pce={avg_pce:.4f} fce={avg_fce:.4f} {'PASS' if avg_pce < avg_fce else 'FAIL'}")

    # 전체 평균
    if cat_results:
        avg_pce = np.mean([r["pce"] for r in cat_results.values()])
        avg_fce = np.mean([r["fce"] for r in cat_results.values()])
        wins = avg_pce < avg_fce
        print(f"  OVERALL: pce={avg_pce:.4f} fce={avg_fce:.4f} imp={((avg_fce-avg_pce)/max(avg_fce,1e-9)*100):+.2f}% GATE={'PASS' if wins else 'FAIL'}")
        return {"wins": wins, "pce": avg_pce, "fce": avg_fce}
    else:
        return {"wins": False, "pce": 10, "fce": 10}

def main():
    print("Phase 1 Simple Test (3 weight candidates)")
    print("=" * 60)

    start = time.time()

    draws = fetch_all_draws()
    if len(draws) < 1120:
        print(f"ERROR: need 1120 rounds, got {len(draws)}")
        return

    test_rounds = list(range(1101, 1121))  # 20 rounds

    print(f"\nTest set: 1101-1120 (20 rounds)")
    print(f"Weight candidates:")
    for name, w in WEIGHT_CANDIDATES:
        print(f"  {name}: {w}")

    results = []

    # 1. endings_distribution
    r = test_one_predictor(
        EndingsDistributionPredictor,
        lambda p, hist: p._extract(hist),
        _freq_dist_endings,
        lambda tgt, cat: sum(1 for x in tgt["numbers"] if x % 10 == cat),
        test_rounds,
        draws,
        10,
        [f"digit_{i}" for i in range(10)]
    )
    results.append(("endings_distribution", r))

    # 2. high_low
    r = test_one_predictor(
        HighLowPredictor,
        lambda p, hist: p._extract(hist),
        _freq_dist_hl,
        lambda tgt, cat: sum(1 for x in tgt["numbers"] if x in LOW_SET),
        test_rounds,
        draws,
        1,
        ["low_count"]
    )
    results.append(("high_low", r))

    # 3. odd_even
    r = test_one_predictor(
        OddEvenPredictor,
        lambda p, hist: p._extract(hist),
        _freq_dist_oe,
        lambda tgt, cat: sum(1 for x in tgt["numbers"] if x in ODD_SET),
        test_rounds,
        draws,
        1,
        ["odd_count"]
    )
    results.append(("odd_even", r))

    # 4. decade
    r = test_one_predictor(
        DecadePredictor,
        lambda p, hist: p._extract(hist),
        _freq_dist_decade,
        lambda tgt, cat: sum(1 for x in tgt["numbers"] if DECADE_RANGES[cat][0] <= x <= DECADE_RANGES[cat][1]),
        test_rounds,
        draws,
        5,
        [f"{DECADE_RANGES[i][0]}-{DECADE_RANGES[i][1]}" for i in range(5)]
    )
    results.append(("decade_distribution", r))

    # 5. gung
    r = test_one_predictor(
        GungPredictor,
        lambda p, hist: p._extract(hist),
        _freq_dist_gung,
        lambda tgt, cat: sum(1 for x in tgt["numbers"] if GUNG_RANGES[cat][0] <= x <= GUNG_RANGES[cat][1]),
        test_rounds,
        draws,
        9,
        [f"gung_{i}" for i in range(9)]
    )
    results.append(("gung_distribution", r))

    elapsed = time.time() - start

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    pass_count = 0
    for name, r in results:
        if r["wins"]:
            pass_count += 1
        print(f"{name}: {'PASS' if r['wins'] else 'FAIL'} (pce={r['pce']:.4f}, fce={r['fce']:.4f})")

    print(f"\nPASS rate: {pass_count}/5")
    print(f"Time: {elapsed:.1f}s ({elapsed/60:.1f}min)")
    print("=" * 60)

if __name__ == "__main__":
    main()
