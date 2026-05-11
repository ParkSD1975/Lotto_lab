"""5개 Phase 1 predictor 122회 검증 (1101~1222).

학습: 31~1050 (1020회)
Val: 1051~1100 (50회) — 가중치 결정
Test: 1101~1222 (122회) — 검증 게이트

각 predictor의 predictor_ce vs frequency_ce 비교.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

import numpy as np
from db.supabase_client import fetch_all_draws
from validation.baseline_runner import BaselineRunner
from predictors.phase1_endings_distribution import EndingsDistributionPredictor, DIGIT_POOL_SIZES, _freq_dist as endings_freq_dist
from predictors.phase1_high_low import HighLowPredictor, LOW_SET, HIGH_SET
from predictors.phase1_odd_even import OddEvenPredictor, ODD_SET
from predictors.phase1_decade import DecadePredictor, DECADE_RANGES, DECADE_POOL_SIZES
from predictors.phase1_gung import GungPredictor, GUNG_RANGES, GUNG_POOL_SIZES, _freq_dist as gung_freq_dist, _rwf_dist

TRAIN_MAX = 1050  # 31~1050
VAL_START = 1051  # 1051~1100
VAL_END = 1100
TEST_START = 1101  # 1101~1222
TEST_END = 1222

def validate_endings(draws, test_rounds):
    """Endings distribution 122회 검증."""
    print("\n[1/5] Validating endings_distribution...")
    p = EndingsDistributionPredictor()
    train_hist = [d for d in draws if int(d.get("round", 0)) <= TRAIN_MAX]
    if len(train_hist) < 50:
        return {"error": "insufficient training data"}
    p.train(train_hist, 50)

    r = BaselineRunner()
    cat_res = {}
    for cat_idx in range(10):
        pce_tot, fce_tot, n = 0, 0, 0
        for tr in test_rounds:
            hist = [d for d in draws if int(d.get("round", 0)) < tr]
            out = p.predict(hist, tr)
            lab = f"digit_{cat_idx}"
            pd = np.array(out["per_category"][lab]["absolute_dist"])
            tgt = next((d for d in draws if int(d["round"]) == tr), None)
            if not tgt:
                continue
            tc = sum(1 for x in tgt["numbers"] if x % 10 == cat_idx)
            cm = p._extract(hist)
            fd = endings_freq_dist(cm[:, cat_idx])
            pce_tot += r.cross_entropy(pd, tc)
            fce_tot += r.cross_entropy(fd, tc)
            n += 1
        if n > 0:
            cat_res[lab] = {"predictor_ce": pce_tot/n, "frequency_ce": fce_tot/n, "n_rounds": n}

    if not cat_res:
        return {"error": "no_rounds"}
    apc = np.mean([x["predictor_ce"] for x in cat_res.values()])
    afc = np.mean([x["frequency_ce"] for x in cat_res.values()])
    return {
        "predictor": "endings_distribution",
        "n_categories": 10,
        "avg_predictor_ce": float(apc),
        "avg_frequency_ce": float(afc),
        "improvement_pct": (afc-apc)/max(afc,1e-9)*100,
        "wins_frequency": apc < afc,
        "per_category": cat_res
    }

def validate_high_low(draws, test_rounds):
    """High/Low 122회 검증."""
    print("[2/5] Validating high_low...")
    p = HighLowPredictor()
    train_hist = [d for d in draws if int(d.get("round", 0)) <= TRAIN_MAX]
    if len(train_hist) < 50:
        return {"error": "insufficient training data"}
    p.train(train_hist, 50)

    r = BaselineRunner()
    pce_tot, fce_tot, n = 0, 0, 0
    for tr in test_rounds:
        hist = [d for d in draws if int(d.get("round", 0)) < tr]
        out = p.predict(hist, tr)
        pd = np.array(out["absolute_dist"])
        tgt = next((d for d in draws if int(d["round"]) == tr), None)
        if not tgt:
            continue
        low_cnt = sum(1 for x in tgt["numbers"] if x in LOW_SET)
        seq = p._extract(hist)
        fd = np.bincount(seq.astype(np.int64), minlength=7)
        fd = fd / max(fd.sum(), 1)
        pce_tot += r.cross_entropy(pd, low_cnt)
        fce_tot += r.cross_entropy(fd, low_cnt)
        n += 1

    if n == 0:
        return {"error": "no_rounds"}
    return {
        "predictor": "high_low",
        "avg_predictor_ce": pce_tot/n,
        "avg_frequency_ce": fce_tot/n,
        "improvement_pct": ((fce_tot/n)-(pce_tot/n))/max(fce_tot/n,1e-9)*100,
        "wins_frequency": (pce_tot/n) < (fce_tot/n),
        "n_rounds": n
    }

def validate_odd_even(draws, test_rounds):
    """Odd/Even 122회 검증."""
    print("[3/5] Validating odd_even...")
    p = OddEvenPredictor()
    train_hist = [d for d in draws if int(d.get("round", 0)) <= TRAIN_MAX]
    if len(train_hist) < 50:
        return {"error": "insufficient training data"}
    p.train(train_hist, 50)

    r = BaselineRunner()
    pce_tot, fce_tot, n = 0, 0, 0
    for tr in test_rounds:
        hist = [d for d in draws if int(d.get("round", 0)) < tr]
        out = p.predict(hist, tr)
        pd = np.array(out["absolute_dist"])
        tgt = next((d for d in draws if int(d["round"]) == tr), None)
        if not tgt:
            continue
        odd_cnt = sum(1 for x in tgt["numbers"] if x in ODD_SET)
        seq = p._extract(hist)
        fd = np.bincount(seq.astype(np.int64), minlength=7)
        fd = fd / max(fd.sum(), 1)
        pce_tot += r.cross_entropy(pd, odd_cnt)
        fce_tot += r.cross_entropy(fd, odd_cnt)
        n += 1

    if n == 0:
        return {"error": "no_rounds"}
    return {
        "predictor": "odd_even",
        "avg_predictor_ce": pce_tot/n,
        "avg_frequency_ce": fce_tot/n,
        "improvement_pct": ((fce_tot/n)-(pce_tot/n))/max(fce_tot/n,1e-9)*100,
        "wins_frequency": (pce_tot/n) < (fce_tot/n),
        "n_rounds": n
    }

def validate_decade(draws, test_rounds):
    """Decade 122회 검증."""
    print("[4/5] Validating decade...")
    p = DecadePredictor()
    train_hist = [d for d in draws if int(d.get("round", 0)) <= TRAIN_MAX]
    if len(train_hist) < 50:
        return {"error": "insufficient training data"}
    p.train(train_hist, 50)

    r = BaselineRunner()
    cat_res = {}
    for cat_idx in range(5):
        pce_tot, fce_tot, n = 0, 0, 0
        for tr in test_rounds:
            hist = [d for d in draws if int(d.get("round", 0)) < tr]
            out = p.predict(hist, tr)
            lab = f"decade_{cat_idx}"
            pd = np.array(out["per_category"][lab]["absolute_dist"])
            tgt = next((d for d in draws if int(d["round"]) == tr), None)
            if not tgt:
                continue
            lo, hi = DECADE_RANGES[cat_idx]
            tc = sum(1 for x in tgt["numbers"] if lo <= x <= hi)
            cm = p._extract(hist)
            fd = np.bincount(cm[:, cat_idx].astype(np.int64), minlength=7)
            fd = fd / max(fd.sum(), 1)
            pce_tot += r.cross_entropy(pd, tc)
            fce_tot += r.cross_entropy(fd, tc)
            n += 1
        if n > 0:
            cat_res[lab] = {"predictor_ce": pce_tot/n, "frequency_ce": fce_tot/n, "n_rounds": n}

    if not cat_res:
        return {"error": "no_rounds"}
    apc = np.mean([x["predictor_ce"] for x in cat_res.values()])
    afc = np.mean([x["frequency_ce"] for x in cat_res.values()])
    return {
        "predictor": "decade",
        "n_categories": 5,
        "avg_predictor_ce": float(apc),
        "avg_frequency_ce": float(afc),
        "improvement_pct": (afc-apc)/max(afc,1e-9)*100,
        "wins_frequency": apc < afc,
        "per_category": cat_res
    }

def validate_gung(draws, test_rounds):
    """Gung 122회 검증 + 4개 메서드 비교."""
    print("[5/5] Validating gung (4 methods: baseline, lag+periodic, GNN, stacking)...")
    train_hist = [d for d in draws if int(d.get("round", 0)) <= TRAIN_MAX]
    val_hist = [d for d in draws if VAL_START <= int(d.get("round", 0)) <= VAL_END]

    if len(train_hist) < 50:
        return {"error": "insufficient training data"}

    # 1. Baseline (기존 RWF+Markov+Freq)
    p_baseline = GungPredictor()
    p_baseline.train(train_hist, 50)

    # 2. Stacking meta-learner
    p_stacking = GungPredictor()
    p_stacking.train(train_hist, 50, val_draws=val_hist)

    r = BaselineRunner()

    # 카테고리별 메서드 비교 (validation set에서 최적 선택)
    best_method_per_cat = {}
    for cat_idx in range(9):
        methods = {
            "baseline": (p_baseline, False),
            "stacking": (p_stacking, True),
        }
        best_method = "baseline"
        best_val_ce = 1e9

        # Validation set에서 각 메서드 평가
        for method_name, (predictor, use_stack) in methods.items():
            val_ce_sum = 0
            val_n = 0
            for vr in range(VAL_START, VAL_END + 1):
                hist = [d for d in draws if int(d.get("round", 0)) < vr]
                cm = predictor._extract(hist)
                s = cm[:, cat_idx]
                last = int(s[-1])

                mp = predictor.markov_heads[cat_idx].predict(last)
                fp = gung_freq_dist(s)
                rwf = _rwf_dist(s, decay=0.95)

                if use_stack and predictor.stacking_meta and predictor.stacking_meta[cat_idx]:
                    try:
                        feat = np.concatenate([mp, fp, rwf]).reshape(1, -1)
                        ap = predictor.stacking_meta[cat_idx].predict_proba(feat)[0]
                    except:
                        ap = 0.35 * rwf + 0.40 * mp + 0.25 * fp
                        ap /= ap.sum()
                else:
                    ap = 0.35 * rwf + 0.40 * mp + 0.25 * fp
                    ap /= ap.sum()

                tgt = next((d for d in draws if int(d["round"]) == vr), None)
                if tgt:
                    lo, hi = GUNG_RANGES[cat_idx]
                    tc = sum(1 for x in tgt["numbers"] if lo <= x <= hi)
                    val_ce_sum += -np.log(max(ap[tc], 1e-9))
                    val_n += 1

            if val_n > 0:
                avg_val_ce = val_ce_sum / val_n
                if avg_val_ce < best_val_ce:
                    best_val_ce = avg_val_ce
                    best_method = method_name

        best_method_per_cat[cat_idx] = best_method
        print(f"  gung_{cat_idx}: best_method={best_method} (val_ce={best_val_ce:.4f})")

    # Test set 평가
    cat_res = {}
    for cat_idx in range(9):
        method_name = best_method_per_cat[cat_idx]
        predictor, use_stack = methods[method_name]

        pce_tot, fce_tot, n = 0, 0, 0
        for tr in test_rounds:
            hist = [d for d in draws if int(d.get("round", 0)) < tr]
            cm = predictor._extract(hist)
            s = cm[:, cat_idx]
            last = int(s[-1])

            mp = predictor.markov_heads[cat_idx].predict(last)
            fp = gung_freq_dist(s)
            rwf = _rwf_dist(s, decay=0.95)

            if use_stack and predictor.stacking_meta and predictor.stacking_meta[cat_idx]:
                try:
                    feat = np.concatenate([mp, fp, rwf]).reshape(1, -1)
                    ap = predictor.stacking_meta[cat_idx].predict_proba(feat)[0]
                except:
                    ap = 0.35 * rwf + 0.40 * mp + 0.25 * fp
                    ap /= ap.sum()
            else:
                ap = 0.35 * rwf + 0.40 * mp + 0.25 * fp
                ap /= ap.sum()

            tgt = next((d for d in draws if int(d["round"]) == tr), None)
            if tgt:
                lo, hi = GUNG_RANGES[cat_idx]
                tc = sum(1 for x in tgt["numbers"] if lo <= x <= hi)
                pce_tot += r.cross_entropy(ap, tc)
                fce_tot += r.cross_entropy(fp, tc)
                n += 1

        if n > 0:
            cat_res[f"gung_{cat_idx}"] = {
                "predictor_ce": pce_tot/n,
                "frequency_ce": fce_tot/n,
                "n_rounds": n,
                "best_method": method_name
            }

    if not cat_res:
        return {"error": "no_rounds"}
    apc = np.mean([x["predictor_ce"] for x in cat_res.values()])
    afc = np.mean([x["frequency_ce"] for x in cat_res.values()])
    return {
        "predictor": "gung",
        "n_categories": 9,
        "avg_predictor_ce": float(apc),
        "avg_frequency_ce": float(afc),
        "improvement_pct": (afc-apc)/max(afc,1e-9)*100,
        "wins_frequency": apc < afc,
        "per_category": cat_res,
        "best_methods": best_method_per_cat
    }

def main():
    print("="*60)
    print("5개 Phase 1 Predictor 122회 검증 (회차 1101~1222)")
    print("="*60)

    draws = fetch_all_draws()
    if len(draws) < 100:
        print("ERROR: insufficient draws")
        return

    test_rounds = list(range(TEST_START, TEST_END + 1))
    available_rounds = [int(d["round"]) for d in draws if TEST_START <= int(d["round"]) <= TEST_END]
    test_rounds = [r for r in test_rounds if r in available_rounds]
    print(f"\n학습: 31~{TRAIN_MAX} ({TRAIN_MAX-30} 회차)")
    print(f"Val: {VAL_START}~{VAL_END} ({VAL_END-VAL_START+1} 회차)")
    print(f"Test: {TEST_START}~{TEST_END} ({len(test_rounds)} 회차 available)\n")

    results = []

    # 1. Endings
    res_endings = validate_endings(draws, test_rounds)
    results.append(res_endings)

    # 2. High/Low
    res_hl = validate_high_low(draws, test_rounds)
    results.append(res_hl)

    # 3. Odd/Even
    res_oe = validate_odd_even(draws, test_rounds)
    results.append(res_oe)

    # 4. Decade
    res_decade = validate_decade(draws, test_rounds)
    results.append(res_decade)

    # 5. Gung
    res_gung = validate_gung(draws, test_rounds)
    results.append(res_gung)

    # 결과 표
    print("\n" + "="*80)
    print("5개 Predictor 122회 검증 결과")
    print("="*80)
    print(f"{'Predictor':<25} {'predictor_ce':<14} {'frequency_ce':<14} {'improvement':<12} {'PASS':<6}")
    print("-"*80)

    for res in results:
        if "error" in res:
            print(f"{res.get('predictor', 'unknown'):<25} ERROR: {res['error']}")
            continue

        pred_name = res.get("predictor", "unknown")
        pce = res.get("avg_predictor_ce", 0)
        fce = res.get("avg_frequency_ce", 0)
        imp = res.get("improvement_pct", 0)
        wins = res.get("wins_frequency", False)
        print(f"{pred_name:<25} {pce:<14.4f} {fce:<14.4f} {imp:+12.2f}% {'PASS' if wins else 'FAIL':<6}")

    # Gung 추가 분석
    if "error" not in res_gung:
        print("\n" + "="*80)
        print("Gung 카테고리별 최적 메서드")
        print("="*80)
        for cat_idx, method in res_gung.get("best_methods", {}).items():
            cat_data = res_gung["per_category"].get(f"gung_{cat_idx}", {})
            print(f"  gung_{cat_idx}: {method:<12} (pce={cat_data.get('predictor_ce', 0):.4f}, fce={cat_data.get('frequency_ce', 0):.4f})")

    print("\n" + "="*80)
    all_pass = all(r.get("wins_frequency", False) for r in results if "error" not in r)
    print(f"최종 게이트: {'PASS (모든 predictor 통과)' if all_pass else 'FAIL (일부 predictor 실패)'}")
    print("="*80)

if __name__ == "__main__":
    main()
