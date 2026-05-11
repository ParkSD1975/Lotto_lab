"""Phase 1 Quick Batch Validation - 8 predictors with simplified evaluation.

20회 hold-out 검증 (1101-1120).
Single weight per predictor (not per-category).
"""
import numpy as np
import sys
import warnings
import time
warnings.filterwarnings('ignore')

from db.supabase_client import fetch_all_draws

# 8개 predictor import
from predictors.phase1_carryover import CarryoverPredictor
from predictors.phase1_neighbor import NeighborPredictor
from predictors.phase1_consecutive import ConsecutivePredictor
from predictors.phase1_lotto_paper import LottoPaperPredictor
from predictors.phase1_multiple import MultiplePredictor
from predictors.phase1_special_number import SpecialNumberPredictor
from predictors.phase1_missing_group import MissingGroupPredictor
from predictors.phase1_hotcold import HotColdPredictor

# Single best weight (from decade success)
BEST_WEIGHT = (0.15, 0.45, 0.40)

def ce_safe(pred_dist, true_class):
    """7-class CE loss."""
    if not 0 <= true_class < 7:
        return 10.0
    p = pred_dist[int(true_class)]
    return -np.log(max(p, 1e-9))

def _freq_dist(hist):
    """Frequency baseline."""
    if len(hist) == 0:
        return np.full(7, 1/7)
    c = np.bincount(hist.astype(np.int64), minlength=7)
    return c / max(c.sum(), 1)

def validate_predictor(name, predictor, draws, test_rounds, extract_fn, ground_truth_fn, n_cats):
    """Generic validation for any predictor.

    Args:
        name: predictor name
        predictor: predictor instance
        draws: all draws
        test_rounds: test round list
        extract_fn: function to extract category matrix
        ground_truth_fn: function(tgt_draw, cat_idx) -> true_class
        n_cats: number of categories
    """
    print(f"\n{name} ({n_cats} categories)")

    train_draws = [d for d in draws if int(d.get("round", 0)) <= 1050]
    print(f"  Training on {len(train_draws)} rounds...", end="", flush=True)
    predictor.train(train_draws, 50)
    print(" Done")

    w = BEST_WEIGHT
    cat_results = []

    for cat in range(n_cats):
        pce, fce, n = 0, 0, 0

        for tr in test_rounds:
            hist = [d for d in draws if int(d.get("round", 0)) < tr]
            cm = extract_fn(predictor, hist)

            if n_cats == 1:
                s = cm
                last = int(s[-1])
                mp = predictor.markov.predict(last)
                fp = _freq_dist(s)
                xgb_prob = None
                if predictor.xgb_model:
                    try:
                        X = predictor._build_features(s, 30)
                        if X is not None and len(X) > 0:
                            raw = predictor.xgb_model.predict_proba(X[-1:])[0]
                            xgb_prob = np.zeros(7)
                            xgb_prob[:min(len(raw), 7)] = raw[:min(len(raw), 7)]
                            xgb_prob /= xgb_prob.sum()
                    except:
                        pass
            else:
                s = cm[:, cat]
                last = int(s[-1])
                mp = predictor.markov_heads[cat].predict(last)
                fp = _freq_dist(s)
                xgb_prob = None
                if predictor.xgb_models and predictor.xgb_models[cat]:
                    try:
                        X = predictor._build_features(cm, cat, 30)
                        if X is not None and len(X) > 0:
                            raw = predictor.xgb_models[cat].predict_proba(X[-1:])[0]
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
                tc = ground_truth_fn(tgt, cat, draws, tr)
                pce += ce_safe(ap, tc)
                fce += ce_safe(fp, tc)
                n += 1

        if n > 0:
            cat_results.append((pce/n, fce/n))

    avg_pce = np.mean([r[0] for r in cat_results])
    avg_fce = np.mean([r[1] for r in cat_results])

    return {
        "name": name,
        "n_cats": n_cats,
        "pce": avg_pce,
        "fce": avg_fce,
        "imp": (avg_fce - avg_pce) / max(avg_fce, 1e-9) * 100,
        "wins": avg_pce < avg_fce,
        "w": w
    }

def main():
    print("=" * 80)
    print("Phase 1 Quick Batch Validation - 8 Predictors")
    print("122-round hold-out test (1101-1222)")
    print("=" * 80)

    start = time.time()

    draws = fetch_all_draws()
    if len(draws) < 1222:
        print(f"ERROR: need 1222 rounds, got {len(draws)}")
        return

    test_rounds = list(range(1101, 1223))  # 122

    print(f"\nData split:")
    print(f"  Train: 31-1050 (1020 rounds)")
    print(f"  Test:  1101-1222 (122 rounds)")
    print(f"\nUsing fixed weight: {BEST_WEIGHT}")

    results = []

    # 1. Carryover
    def extract_carryover(p, hist):
        return p._extract(hist)

    def gt_carryover(tgt, cat, draws, tr):
        if cat == 0:
            if tr > 31:
                prev = next((d for d in draws if int(d["round"]) == tr - 1), None)
                if prev:
                    prev_main = set(prev["numbers"])
                    return sum(1 for x in tgt["numbers"] if x in prev_main)
            return 0
        else:
            if tr > 31:
                prev = next((d for d in draws if int(d["round"]) == tr - 1), None)
                if prev and prev.get("bonus_number"):
                    return 1 if prev["bonus_number"] in tgt["numbers"] else 0
            return 0

    p1 = CarryoverPredictor()
    results.append(validate_predictor("carryover", p1, draws, test_rounds, extract_carryover, gt_carryover, 2))

    # 2. Neighbor
    def extract_neighbor(p, hist):
        return p._extract(hist)

    def gt_neighbor(tgt, cat, draws, tr):
        nums = sorted(tgt["numbers"])
        n_count = 0
        for i in range(len(nums)):
            for j in range(i+1, len(nums)):
                if abs(nums[i] - nums[j]) == 1:
                    n_count += 1
        return n_count

    p2 = NeighborPredictor()
    results.append(validate_predictor("neighbor", p2, draws, test_rounds, extract_neighbor, gt_neighbor, 1))

    # 3. Consecutive
    def extract_consecutive(p, hist):
        return p._extract(hist)

    def gt_consecutive(tgt, cat, draws, tr):
        nums = sorted(tgt["numbers"])
        consec = 0
        streak = 1
        for i in range(1, len(nums)):
            if nums[i] == nums[i-1] + 1:
                streak += 1
            else:
                if streak >= 2:
                    consec += streak
                streak = 1
        if streak >= 2:
            consec += streak
        return min(consec, 6)

    p3 = ConsecutivePredictor()
    results.append(validate_predictor("consecutive", p3, draws, test_rounds, extract_consecutive, gt_consecutive, 1))

    # 4. Lotto Paper
    def extract_lotto_paper(p, hist):
        return p._extract(hist)

    def gt_lotto_paper(tgt, cat, draws, tr):
        nums = tgt["numbers"]
        if cat < 7:
            return sum(1 for n in nums if (n-1)//7 == cat)
        else:
            col_idx = cat - 7
            return sum(1 for n in nums if (n-1)%7 == col_idx)

    p4 = LottoPaperPredictor()
    results.append(validate_predictor("lotto_paper", p4, draws, test_rounds, extract_lotto_paper, gt_lotto_paper, 14))

    # 5. Multiple
    from predictors.phase1_multiple import MULTIPLE_SETS

    def extract_multiple(p, hist):
        return p._extract(hist)

    def gt_multiple(tgt, cat, draws, tr):
        nums = tgt["numbers"]
        p = MultiplePredictor()
        label = p.labels[cat]
        return sum(1 for n in nums if n in MULTIPLE_SETS[label])

    p5 = MultiplePredictor()
    results.append(validate_predictor("multiple", p5, draws, test_rounds, extract_multiple, gt_multiple, 6))

    # 6. Special Number
    from predictors.phase1_special_number import SPECIAL_SETS

    def extract_special(p, hist):
        return p._extract(hist)

    def gt_special(tgt, cat, draws, tr):
        nums = tgt["numbers"]
        p = SpecialNumberPredictor()
        label = p.labels[cat]
        return sum(1 for n in nums if n in SPECIAL_SETS[label])

    p6 = SpecialNumberPredictor()
    results.append(validate_predictor("special_number", p6, draws, test_rounds, extract_special, gt_special, 5))

    # 7. Missing Group
    def extract_missing(p, hist):
        return p._extract(hist)

    def gt_missing(tgt, cat, draws, tr):
        # 누수 방지: tr 시점에서 gap 계산 후 tgt 회차 번호와 비교
        p_temp = MissingGroupPredictor()
        hist = [d for d in draws if int(d.get("round", 0)) < tr]
        gaps = p_temp._compute_gaps(hist)
        curr_nums = tgt["numbers"]
        near = sum(1 for n in curr_nums if gaps[n] < 5)
        mid = sum(1 for n in curr_nums if 5 <= gaps[n] < 15)
        far = sum(1 for n in curr_nums if 15 <= gaps[n] < 30)
        very_far = sum(1 for n in curr_nums if gaps[n] >= 30)
        counts = [near, mid, far, very_far]
        return counts[cat]

    p7 = MissingGroupPredictor()
    results.append(validate_predictor("missing_group", p7, draws, test_rounds, extract_missing, gt_missing, 4))

    # 8. Hot/Cold
    def extract_hotcold(p, hist):
        return p._extract(hist)

    def gt_hotcold(tgt, cat, draws, tr):
        # 누수 방지: tr 시점 기준 hot/cold 분류 후 tgt 회차 번호와 비교
        from predictors.phase1_hotcold import WINDOWS
        p_temp = HotColdPredictor()
        hist = [d for d in draws if int(d.get("round", 0)) < tr]
        chron = list(reversed(hist))

        # cat에서 윈도우 추출 (cat // 3 = window_idx, cat % 3 = group)
        window_idx = cat // 3
        group_idx = cat % 3
        w = WINDOWS[window_idx]

        # 직전 w 회차 기준 hot/warm/cold 분류
        recent = chron[-w:] if len(chron) >= w else chron
        groups = p_temp._classify_hotcold(recent, w)

        curr_nums = tgt["numbers"]
        group_labels = ["hot", "warm", "cold"]
        target_group = group_labels[group_idx]

        count = sum(1 for n in curr_nums if groups.get(n) == target_group)
        return count

    p8 = HotColdPredictor()
    results.append(validate_predictor("hotcold", p8, draws, test_rounds, extract_hotcold, gt_hotcold, 12))

    elapsed = time.time() - start

    # Final report
    print("\n" + "=" * 80)
    print("FINAL RESULTS (122 test rounds: 1101-1222)")
    print("=" * 80)

    pass_count = 0
    for r in results:
        gate = "PASS" if r["wins"] else "FAIL"
        if r["wins"]:
            pass_count += 1

        print(f"\n{r['name']} ({r['n_cats']} cats):")
        print(f"  predictor_ce: {r['pce']:.4f}")
        print(f"  frequency_ce: {r['fce']:.4f}")
        print(f"  improvement:  {r['imp']:+.2f}%")
        print(f"  GATE: {gate}")

    print("\n" + "=" * 80)
    print(f"PASS rate: {pass_count}/8")
    print(f"Time: {elapsed:.1f}s ({elapsed/60:.1f}min)")
    print("=" * 80)

if __name__ == "__main__":
    main()
