"""5개 Phase 1 predictor 122회 빠른 검증 (XGBoost 제외).

학습: 31~1050 (1020회)
Val: 1051~1100 (50회)
Test: 1101~1222 (122회)
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

import numpy as np
from db.supabase_client import fetch_all_draws
from validation.baseline_runner import BaselineRunner

TRAIN_MAX = 1050
VAL_START = 1051
VAL_END = 1100
TEST_START = 1101
TEST_END = 1222

# Simple Markov
class _Markov7:
    def __init__(self):
        self.T = np.full((7,7), 1/7)
    def fit(self, seq):
        if len(seq) < 2: return
        T = np.zeros((7,7))
        for i in range(len(seq)-1):
            a, b = int(seq[i]), int(seq[i+1])
            if 0<=a<7 and 0<=b<7: T[a,b]+=1
        T+=1; T/=T.sum(axis=1, keepdims=True); self.T=T
    def predict(self, last):
        return self.T[int(last)] if 0<=last<7 else np.full(7,1/7)

def _freq_dist(hist):
    if len(hist)==0: return np.full(7,1/7)
    c=np.bincount(hist.astype(np.int64), minlength=7)
    return c/max(c.sum(),1)

def _rwf_dist(hist, decay=0.95):
    if len(hist)==0: return np.full(7,1/7)
    T = len(hist)
    c = np.zeros(7)
    for i, val in enumerate(hist):
        if 0 <= val < 7:
            weight = decay ** (T - 1 - i)
            c[int(val)] += weight
    return c / max(c.sum(), 1e-9)

# Endings
def validate_endings_fast(draws, test_rounds):
    print("[1/5] Endings (fast)...")
    train_hist = [d for d in draws if int(d.get("round", 0)) <= TRAIN_MAX]

    # Extract counts
    def extract_endings(dlist):
        chron = list(reversed(dlist))
        counts = []
        for d in chron:
            nums = d.get("numbers", [])
            c = [sum(1 for n in nums if n%10==i) for i in range(10)]
            counts.append(c)
        return np.array(counts, dtype=np.int64)

    cm_train = extract_endings(train_hist)
    markovs = [_Markov7() for _ in range(10)]
    for i in range(10):
        markovs[i].fit(cm_train[:, i])

    r = BaselineRunner()
    cat_res = {}
    for cat_idx in range(10):
        pce_tot, fce_tot, n = 0, 0, 0
        for tr in test_rounds:
            hist = [d for d in draws if int(d.get("round", 0)) < tr]
            cm = extract_endings(hist)
            s = cm[:, cat_idx]
            last = int(s[-1])

            mp = markovs[cat_idx].predict(last)
            fp = _freq_dist(s)
            rwf = _rwf_dist(s, decay=0.95)

            # 최적 가중치 (기존 검증 결과 참고)
            ap = 0.35 * rwf + 0.40 * mp + 0.25 * fp
            ap /= ap.sum()

            tgt = next((d for d in draws if int(d["round"]) == tr), None)
            if not tgt:
                continue
            tc = sum(1 for x in tgt["numbers"] if x % 10 == cat_idx)
            pce_tot += r.cross_entropy(ap, tc)
            fce_tot += r.cross_entropy(fp, tc)
            n += 1

        if n > 0:
            cat_res[f"digit_{cat_idx}"] = {"predictor_ce": pce_tot/n, "frequency_ce": fce_tot/n, "n_rounds": n}

    apc = np.mean([x["predictor_ce"] for x in cat_res.values()])
    afc = np.mean([x["frequency_ce"] for x in cat_res.values()])
    return {
        "predictor": "endings_distribution",
        "avg_predictor_ce": float(apc),
        "avg_frequency_ce": float(afc),
        "improvement_pct": (afc-apc)/max(afc,1e-9)*100,
        "wins_frequency": apc < afc
    }

# High/Low
def validate_high_low_fast(draws, test_rounds):
    print("[2/5] High/Low (fast)...")
    LOW_SET = {n for n in range(1,23)}
    train_hist = [d for d in draws if int(d.get("round", 0)) <= TRAIN_MAX]

    def extract_hl(dlist):
        chron = list(reversed(dlist))
        counts = []
        for d in chron:
            nums = d.get("numbers", [])
            low_cnt = sum(1 for n in nums if n in LOW_SET)
            counts.append(low_cnt)
        return np.array(counts, dtype=np.int64)

    seq_train = extract_hl(train_hist)
    markov = _Markov7()
    markov.fit(seq_train)

    r = BaselineRunner()
    pce_tot, fce_tot, n = 0, 0, 0
    for tr in test_rounds:
        hist = [d for d in draws if int(d.get("round", 0)) < tr]
        seq = extract_hl(hist)
        last = int(seq[-1])

        mp = markov.predict(last)
        fp = _freq_dist(seq)
        rwf = _rwf_dist(seq, decay=0.95)

        ap = 0.35 * rwf + 0.40 * mp + 0.25 * fp
        ap /= ap.sum()

        tgt = next((d for d in draws if int(d["round"]) == tr), None)
        if not tgt:
            continue
        low_cnt = sum(1 for x in tgt["numbers"] if x in LOW_SET)
        pce_tot += r.cross_entropy(ap, low_cnt)
        fce_tot += r.cross_entropy(fp, low_cnt)
        n += 1

    return {
        "predictor": "high_low",
        "avg_predictor_ce": pce_tot/n,
        "avg_frequency_ce": fce_tot/n,
        "improvement_pct": ((fce_tot/n)-(pce_tot/n))/max(fce_tot/n,1e-9)*100,
        "wins_frequency": (pce_tot/n) < (fce_tot/n)
    }

# Odd/Even
def validate_odd_even_fast(draws, test_rounds):
    print("[3/5] Odd/Even (fast)...")
    ODD_SET = {n for n in range(1,46) if n%2==1}
    train_hist = [d for d in draws if int(d.get("round", 0)) <= TRAIN_MAX]

    def extract_oe(dlist):
        chron = list(reversed(dlist))
        counts = []
        for d in chron:
            nums = d.get("numbers", [])
            odd_cnt = sum(1 for n in nums if n in ODD_SET)
            counts.append(odd_cnt)
        return np.array(counts, dtype=np.int64)

    seq_train = extract_oe(train_hist)
    markov = _Markov7()
    markov.fit(seq_train)

    r = BaselineRunner()
    pce_tot, fce_tot, n = 0, 0, 0
    for tr in test_rounds:
        hist = [d for d in draws if int(d.get("round", 0)) < tr]
        seq = extract_oe(hist)
        last = int(seq[-1])

        mp = markov.predict(last)
        fp = _freq_dist(seq)
        rwf = _rwf_dist(seq, decay=0.95)

        ap = 0.35 * rwf + 0.40 * mp + 0.25 * fp
        ap /= ap.sum()

        tgt = next((d for d in draws if int(d["round"]) == tr), None)
        if not tgt:
            continue
        odd_cnt = sum(1 for x in tgt["numbers"] if x in ODD_SET)
        pce_tot += r.cross_entropy(ap, odd_cnt)
        fce_tot += r.cross_entropy(fp, odd_cnt)
        n += 1

    return {
        "predictor": "odd_even",
        "avg_predictor_ce": pce_tot/n,
        "avg_frequency_ce": fce_tot/n,
        "improvement_pct": ((fce_tot/n)-(pce_tot/n))/max(fce_tot/n,1e-9)*100,
        "wins_frequency": (pce_tot/n) < (fce_tot/n)
    }

# Decade
def validate_decade_fast(draws, test_rounds):
    print("[4/5] Decade (fast)...")
    DECADE_RANGES = [(1,9),(10,19),(20,29),(30,39),(40,45)]
    train_hist = [d for d in draws if int(d.get("round", 0)) <= TRAIN_MAX]

    def extract_decade(dlist):
        chron = list(reversed(dlist))
        counts = []
        for d in chron:
            nums = d.get("numbers", [])
            c = [0]*5
            for n in nums:
                for i, (lo, hi) in enumerate(DECADE_RANGES):
                    if lo <= n <= hi:
                        c[i] += 1
                        break
            counts.append(c)
        return np.array(counts, dtype=np.int64)

    cm_train = extract_decade(train_hist)
    markovs = [_Markov7() for _ in range(5)]
    for i in range(5):
        markovs[i].fit(cm_train[:, i])

    r = BaselineRunner()
    cat_res = {}
    for cat_idx in range(5):
        pce_tot, fce_tot, n = 0, 0, 0
        for tr in test_rounds:
            hist = [d for d in draws if int(d.get("round", 0)) < tr]
            cm = extract_decade(hist)
            s = cm[:, cat_idx]
            last = int(s[-1])

            mp = markovs[cat_idx].predict(last)
            fp = _freq_dist(s)
            rwf = _rwf_dist(s, decay=0.95)

            ap = 0.35 * rwf + 0.40 * mp + 0.25 * fp
            ap /= ap.sum()

            tgt = next((d for d in draws if int(d["round"]) == tr), None)
            if not tgt:
                continue
            lo, hi = DECADE_RANGES[cat_idx]
            tc = sum(1 for x in tgt["numbers"] if lo <= x <= hi)
            pce_tot += r.cross_entropy(ap, tc)
            fce_tot += r.cross_entropy(fp, tc)
            n += 1

        if n > 0:
            cat_res[f"decade_{cat_idx}"] = {"predictor_ce": pce_tot/n, "frequency_ce": fce_tot/n}

    apc = np.mean([x["predictor_ce"] for x in cat_res.values()])
    afc = np.mean([x["frequency_ce"] for x in cat_res.values()])
    return {
        "predictor": "decade",
        "avg_predictor_ce": float(apc),
        "avg_frequency_ce": float(afc),
        "improvement_pct": (afc-apc)/max(afc,1e-9)*100,
        "wins_frequency": apc < afc
    }

# Gung
def validate_gung_fast(draws, test_rounds):
    print("[5/5] Gung (fast)...")
    GUNG_RANGES = [(1,5),(6,10),(11,15),(16,20),(21,25),(26,30),(31,35),(36,40),(41,45)]
    train_hist = [d for d in draws if int(d.get("round", 0)) <= TRAIN_MAX]

    def extract_gung(dlist):
        chron = list(reversed(dlist))
        counts = []
        for d in chron:
            nums = d.get("numbers", [])
            c = [0]*9
            for n in nums:
                for i, (lo, hi) in enumerate(GUNG_RANGES):
                    if lo <= n <= hi:
                        c[i] += 1
                        break
            counts.append(c)
        return np.array(counts, dtype=np.int64)

    cm_train = extract_gung(train_hist)
    markovs = [_Markov7() for _ in range(9)]
    for i in range(9):
        markovs[i].fit(cm_train[:, i])

    r = BaselineRunner()
    cat_res = {}
    for cat_idx in range(9):
        pce_tot, fce_tot, n = 0, 0, 0
        for tr in test_rounds:
            hist = [d for d in draws if int(d.get("round", 0)) < tr]
            cm = extract_gung(hist)
            s = cm[:, cat_idx]
            last = int(s[-1])

            mp = markovs[cat_idx].predict(last)
            fp = _freq_dist(s)
            rwf = _rwf_dist(s, decay=0.95)

            ap = 0.35 * rwf + 0.40 * mp + 0.25 * fp
            ap /= ap.sum()

            tgt = next((d for d in draws if int(d["round"]) == tr), None)
            if not tgt:
                continue
            lo, hi = GUNG_RANGES[cat_idx]
            tc = sum(1 for x in tgt["numbers"] if lo <= x <= hi)
            pce_tot += r.cross_entropy(ap, tc)
            fce_tot += r.cross_entropy(fp, tc)
            n += 1

        if n > 0:
            cat_res[f"gung_{cat_idx}"] = {"predictor_ce": pce_tot/n, "frequency_ce": fce_tot/n}

    apc = np.mean([x["predictor_ce"] for x in cat_res.values()])
    afc = np.mean([x["frequency_ce"] for x in cat_res.values()])
    return {
        "predictor": "gung",
        "avg_predictor_ce": float(apc),
        "avg_frequency_ce": float(afc),
        "improvement_pct": (afc-apc)/max(afc,1e-9)*100,
        "wins_frequency": apc < afc
    }

def main():
    print("="*80)
    print("5개 Phase 1 Predictor 122회 빠른 검증 (회차 1101~1222)")
    print("="*80)

    draws = fetch_all_draws()
    test_rounds = [int(d["round"]) for d in draws if TEST_START <= int(d["round"]) <= TEST_END]
    print(f"\n학습: 31~{TRAIN_MAX}")
    print(f"Test: {TEST_START}~{TEST_END} ({len(test_rounds)} 회차)\n")

    results = [
        validate_endings_fast(draws, test_rounds),
        validate_high_low_fast(draws, test_rounds),
        validate_odd_even_fast(draws, test_rounds),
        validate_decade_fast(draws, test_rounds),
        validate_gung_fast(draws, test_rounds),
    ]

    print("\n" + "="*80)
    print("결과")
    print("="*80)
    print(f"{'Predictor':<25} {'predictor_ce':<14} {'frequency_ce':<14} {'improvement':<12} {'PASS':<6}")
    print("-"*80)

    for res in results:
        pred_name = res.get("predictor", "unknown")
        pce = res.get("avg_predictor_ce", 0)
        fce = res.get("avg_frequency_ce", 0)
        imp = res.get("improvement_pct", 0)
        wins = res.get("wins_frequency", False)
        print(f"{pred_name:<25} {pce:<14.4f} {fce:<14.4f} {imp:+12.2f}% {'PASS' if wins else 'FAIL':<6}")

    all_pass = all(r.get("wins_frequency", False) for r in results)
    print("\n" + "="*80)
    print(f"최종: {'PASS (모든 predictor 통과)' if all_pass else 'FAIL (일부 predictor 실패)'}")
    print("="*80)

if __name__ == "__main__":
    main()
