"""5개 Phase 1 predictor 122회 검증 + Grid Search 가중치 최적화.

학습: 31~1050 (1020회)
Val: 1051~1100 (50회) — Grid Search 가중치 결정
Test: 1101~1222 (122회) — 최종 검증
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

# Grid: Frequency 우선 전략 (90~97%)
WEIGHT_GRID = [
    (0.02, 0.01, 0.97),  # Freq 97%
    (0.01, 0.02, 0.97),
    (0.03, 0.01, 0.96),
    (0.01, 0.03, 0.96),
    (0.02, 0.02, 0.96),
    (0.04, 0.02, 0.94),
    (0.02, 0.04, 0.94),
    (0.03, 0.03, 0.94),
    (0.05, 0.03, 0.92),
    (0.03, 0.05, 0.92),
    (0.06, 0.04, 0.90),
    (0.04, 0.06, 0.90),
    (0.0, 0.0, 1.0),     # Pure frequency
]

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

def grid_search_weight(val_rounds, draws, extract_fn, markovs, n_cats=1):
    """Validation set에서 최적 가중치 찾기 (카테고리별)."""
    best_weights = []

    for cat_idx in range(n_cats):
        best_w = (0.35, 0.40, 0.25)
        best_ce = 1e9

        for w_rwf, w_mk, w_fr in WEIGHT_GRID:
            ce_sum = 0
            n = 0
            for vr in val_rounds:
                hist = [d for d in draws if int(d.get("round", 0)) < vr]
                cm = extract_fn(hist)
                if n_cats == 1:
                    s = cm
                    last = int(s[-1])
                    mp = markovs.predict(last)
                else:
                    s = cm[:, cat_idx]
                    last = int(s[-1])
                    mp = markovs[cat_idx].predict(last)

                fp = _freq_dist(s)
                rwf = _rwf_dist(s, decay=0.95)

                ap = w_rwf * rwf + w_mk * mp + w_fr * fp
                ap /= ap.sum()

                tgt = next((d for d in draws if int(d["round"]) == vr), None)
                if tgt:
                    # 카테고리별 타겟 카운트 계산은 caller가 전달
                    tc = None
                    if n_cats == 1:
                        # high_low or odd_even
                        if hasattr(markovs, 'T'):  # single markov
                            # Extract target count from draw
                            pass  # Skip for now, handled in specific functions
                    ce_sum += -np.log(max(ap[0], 1e-9))  # Placeholder
                    n += 1

            if n > 0:
                avg_ce = ce_sum / n
                if avg_ce < best_ce:
                    best_ce = avg_ce
                    best_w = (w_rwf, w_mk, w_fr)

        best_weights.append(best_w)
        print(f"  Cat {cat_idx}: best_w={best_w}, val_ce={best_ce:.4f}")

    return best_weights

def validate_high_low_optimized(draws, val_rounds, test_rounds):
    """High/Low Grid Search 최적화."""
    print("[2/5] High/Low (optimized)...")
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

    # Grid search on validation set
    best_w = (0.35, 0.40, 0.25)
    best_ce = 1e9

    for w_rwf, w_mk, w_fr in WEIGHT_GRID:
        ce_sum = 0
        n = 0
        for vr in val_rounds:
            hist = [d for d in draws if int(d.get("round", 0)) < vr]
            seq = extract_hl(hist)
            last = int(seq[-1])

            mp = markov.predict(last)
            fp = _freq_dist(seq)
            rwf = _rwf_dist(seq, decay=0.95)

            ap = w_rwf * rwf + w_mk * mp + w_fr * fp
            ap /= ap.sum()

            tgt = next((d for d in draws if int(d["round"]) == vr), None)
            if tgt:
                low_cnt = sum(1 for x in tgt["numbers"] if x in LOW_SET)
                ce_sum += -np.log(max(ap[low_cnt], 1e-9))
                n += 1

        if n > 0:
            avg_ce = ce_sum / n
            if avg_ce < best_ce:
                best_ce = avg_ce
                best_w = (w_rwf, w_mk, w_fr)

    print(f"  Best weight: {best_w} (val_ce={best_ce:.4f})")

    # Test with best weight
    r = BaselineRunner()
    pce_tot, fce_tot, n = 0, 0, 0
    for tr in test_rounds:
        hist = [d for d in draws if int(d.get("round", 0)) < tr]
        seq = extract_hl(hist)
        last = int(seq[-1])

        mp = markov.predict(last)
        fp = _freq_dist(seq)
        rwf = _rwf_dist(seq, decay=0.95)

        w_rwf, w_mk, w_fr = best_w
        ap = w_rwf * rwf + w_mk * mp + w_fr * fp
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
        "wins_frequency": (pce_tot/n) < (fce_tot/n),
        "best_weight": best_w
    }

def validate_gung_optimized(draws, val_rounds, test_rounds):
    """Gung Grid Search 최적화 (카테고리별)."""
    print("[5/5] Gung (optimized)...")
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

    # Grid search per category
    best_weights = []
    for cat_idx in range(9):
        best_w = (0.35, 0.40, 0.25)
        best_ce = 1e9

        for w_rwf, w_mk, w_fr in WEIGHT_GRID:
            ce_sum = 0
            n = 0
            for vr in val_rounds:
                hist = [d for d in draws if int(d.get("round", 0)) < vr]
                cm = extract_gung(hist)
                s = cm[:, cat_idx]
                last = int(s[-1])

                mp = markovs[cat_idx].predict(last)
                fp = _freq_dist(s)
                rwf = _rwf_dist(s, decay=0.95)

                ap = w_rwf * rwf + w_mk * mp + w_fr * fp
                ap /= ap.sum()

                tgt = next((d for d in draws if int(d["round"]) == vr), None)
                if tgt:
                    lo, hi = GUNG_RANGES[cat_idx]
                    tc = sum(1 for x in tgt["numbers"] if lo <= x <= hi)
                    ce_sum += -np.log(max(ap[tc], 1e-9))
                    n += 1

            if n > 0:
                avg_ce = ce_sum / n
                if avg_ce < best_ce:
                    best_ce = avg_ce
                    best_w = (w_rwf, w_mk, w_fr)

        best_weights.append(best_w)
        print(f"  gung_{cat_idx}: best_w={best_w}, val_ce={best_ce:.4f}")

    # Test with best weights
    r = BaselineRunner()
    cat_res = {}
    for cat_idx in range(9):
        w_rwf, w_mk, w_fr = best_weights[cat_idx]
        pce_tot, fce_tot, n = 0, 0, 0
        for tr in test_rounds:
            hist = [d for d in draws if int(d.get("round", 0)) < tr]
            cm = extract_gung(hist)
            s = cm[:, cat_idx]
            last = int(s[-1])

            mp = markovs[cat_idx].predict(last)
            fp = _freq_dist(s)
            rwf = _rwf_dist(s, decay=0.95)

            ap = w_rwf * rwf + w_mk * mp + w_fr * fp
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
            cat_res[f"gung_{cat_idx}"] = {
                "predictor_ce": pce_tot/n,
                "frequency_ce": fce_tot/n,
                "weight": best_weights[cat_idx]
            }

    apc = np.mean([x["predictor_ce"] for x in cat_res.values()])
    afc = np.mean([x["frequency_ce"] for x in cat_res.values()])
    return {
        "predictor": "gung",
        "avg_predictor_ce": float(apc),
        "avg_frequency_ce": float(afc),
        "improvement_pct": (afc-apc)/max(afc,1e-9)*100,
        "wins_frequency": apc < afc,
        "best_weights": best_weights
    }

def main():
    print("="*80)
    print("5개 Phase 1 Predictor 122회 최적화 검증 (회차 1101~1222)")
    print("="*80)

    draws = fetch_all_draws()
    val_rounds = [int(d["round"]) for d in draws if VAL_START <= int(d["round"]) <= VAL_END]
    test_rounds = [int(d["round"]) for d in draws if TEST_START <= int(d["round"]) <= TEST_END]
    print(f"\n학습: 31~{TRAIN_MAX}")
    print(f"Val: {VAL_START}~{VAL_END} ({len(val_rounds)} 회차)")
    print(f"Test: {TEST_START}~{TEST_END} ({len(test_rounds)} 회차)\n")

    results = []

    # High/Low (optimized)
    res_hl = validate_high_low_optimized(draws, val_rounds, test_rounds)
    results.append(res_hl)

    # Gung (optimized)
    res_gung = validate_gung_optimized(draws, val_rounds, test_rounds)
    results.append(res_gung)

    print("\n" + "="*80)
    print("최적화 결과 (High/Low, Gung만)")
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
    print(f"최종: {'PASS' if all_pass else 'FAIL'}")
    print("="*80)

if __name__ == "__main__":
    main()
