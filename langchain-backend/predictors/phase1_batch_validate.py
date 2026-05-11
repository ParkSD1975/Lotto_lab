"""Phase 1 Batch Validation — 8개 미검증 predictor 일괄 검증.

122회 hold-out 검증 (1101~1222).
Grid search per-category weights: (XGB, Markov, Freq).
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

# Grid search 후보 가중치 (XGB, Markov, Freq)
WEIGHT_GRID = [
    (0.2, 0.4, 0.4),
    (0.15, 0.45, 0.40),
    (0.1, 0.3, 0.6),
    (0.0, 0.5, 0.5),  # pure freq+markov
]

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

# ===== 1. Carryover (2 categories) =====
def validate_carryover(draws, val_rounds, test_rounds):
    """Carryover: 2 categories (main, bonus)."""
    print("\n[1/8] Carryover (2 categories)")

    train_draws = [d for d in draws if int(d.get("round", 0)) <= 1050]
    p = CarryoverPredictor()
    print(f"  Training on {len(train_draws)} rounds...", end="", flush=True)
    p.train(train_draws, 50)
    print(" Done")

    # validation: per-category grid search
    best_w = {}
    for cat in range(2):
        best = (0.15, 0.45, 0.40)
        best_ce = 1e9
        for w in WEIGHT_GRID:
            ce_sum, n = 0, 0
            for tr in val_rounds:
                hist = [d for d in draws if int(d.get("round", 0)) < tr]
                cm = p._extract(hist)
                s = cm[:, cat]
                last = int(s[-1])

                mp = p.markov_heads[cat].predict(last)
                fp = _freq_dist(s)

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
                    if cat == 0:
                        # carryover_main
                        if tr > 31:
                            prev_round = next((d for d in draws if int(d["round"]) == tr - 1), None)
                            if prev_round:
                                prev_main = set(prev_round["numbers"])
                                tc = sum(1 for x in tgt["numbers"] if x in prev_main)
                            else:
                                tc = 0
                        else:
                            tc = 0
                    else:
                        # carryover_bonus
                        if tr > 31:
                            prev_round = next((d for d in draws if int(d["round"]) == tr - 1), None)
                            if prev_round and prev_round.get("bonus_number"):
                                tc = 1 if prev_round["bonus_number"] in tgt["numbers"] else 0
                            else:
                                tc = 0
                        else:
                            tc = 0
                    ce_sum += ce_safe(ap, tc)
                    n += 1

            if n > 0:
                avg = ce_sum / n
                if avg < best_ce:
                    best_ce = avg
                    best = w

        best_w[cat] = best
        cat_label = ["carryover_main", "carryover_bonus"][cat]
        print(f"  {cat_label}: {best} (val_ce={best_ce:.4f})")

    # test
    cat_res = {}
    for cat in range(2):
        w = best_w[cat]
        pce, fce, n = 0, 0, 0
        for tr in test_rounds:
            hist = [d for d in draws if int(d.get("round", 0)) < tr]
            cm = p._extract(hist)
            s = cm[:, cat]
            last = int(s[-1])

            mp = p.markov_heads[cat].predict(last)
            fp = _freq_dist(s)

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
                if cat == 0:
                    prev_round = next((d for d in draws if int(d["round"]) == tr - 1), None)
                    if prev_round:
                        prev_main = set(prev_round["numbers"])
                        tc = sum(1 for x in tgt["numbers"] if x in prev_main)
                    else:
                        tc = 0
                else:
                    prev_round = next((d for d in draws if int(d["round"]) == tr - 1), None)
                    if prev_round and prev_round.get("bonus_number"):
                        tc = 1 if prev_round["bonus_number"] in tgt["numbers"] else 0
                    else:
                        tc = 0
                pce += ce_safe(ap, tc)
                fce += ce_safe(fp, tc)
                n += 1

        if n > 0:
            cat_label = ["carryover_main", "carryover_bonus"][cat]
            cat_res[cat_label] = {"pce": pce/n, "fce": fce/n, "w": w}

    avg_pce = np.mean([r["pce"] for r in cat_res.values()])
    avg_fce = np.mean([r["fce"] for r in cat_res.values()])

    return {
        "name": "carryover",
        "n_cats": 2,
        "pce": avg_pce,
        "fce": avg_fce,
        "imp": (avg_fce - avg_pce) / max(avg_fce, 1e-9) * 100,
        "wins": avg_pce < avg_fce,
        "cats": cat_res
    }

# ===== 2. Neighbor (1 category) =====
def validate_neighbor(draws, val_rounds, test_rounds):
    """Neighbor: 1 category."""
    print("\n[2/8] Neighbor (1 category)")

    train_draws = [d for d in draws if int(d.get("round", 0)) <= 1050]
    p = NeighborPredictor()
    print(f"  Training on {len(train_draws)} rounds...", end="", flush=True)
    p.train(train_draws, 50)
    print(" Done")

    # validation
    best = (0.15, 0.45, 0.40)
    best_ce = 1e9
    for w in WEIGHT_GRID:
        ce_sum, n = 0, 0
        for tr in val_rounds:
            hist = [d for d in draws if int(d.get("round", 0)) < tr]
            seq = p._extract(hist)
            last = int(seq[-1])

            mp = p.markov.predict(last)
            fp = _freq_dist(seq)

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
                nums = sorted(tgt["numbers"])
                n_count = 0
                for i in range(len(nums)):
                    for j in range(i+1, len(nums)):
                        if abs(nums[i] - nums[j]) == 1:
                            n_count += 1
                tc = n_count
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
        fp = _freq_dist(seq)

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
            nums = sorted(tgt["numbers"])
            n_count = 0
            for i in range(len(nums)):
                for j in range(i+1, len(nums)):
                    if abs(nums[i] - nums[j]) == 1:
                        n_count += 1
            tc = n_count
            pce += ce_safe(ap, tc)
            fce += ce_safe(fp, tc)
            n += 1

    avg_pce = pce / n if n > 0 else 10.0
    avg_fce = fce / n if n > 0 else 10.0

    return {
        "name": "neighbor",
        "n_cats": 1,
        "pce": avg_pce,
        "fce": avg_fce,
        "imp": (avg_fce - avg_pce) / max(avg_fce, 1e-9) * 100,
        "wins": avg_pce < avg_fce,
        "w": best
    }

# ===== 3. Consecutive (1 category) =====
def validate_consecutive(draws, val_rounds, test_rounds):
    """Consecutive: 1 category."""
    print("\n[3/8] Consecutive (1 category)")

    train_draws = [d for d in draws if int(d.get("round", 0)) <= 1050]
    p = ConsecutivePredictor()
    print(f"  Training on {len(train_draws)} rounds...", end="", flush=True)
    p.train(train_draws, 50)
    print(" Done")

    # validation
    best = (0.15, 0.45, 0.40)
    best_ce = 1e9
    for w in WEIGHT_GRID:
        ce_sum, n = 0, 0
        for tr in val_rounds:
            hist = [d for d in draws if int(d.get("round", 0)) < tr]
            seq = p._extract(hist)
            last = int(seq[-1])

            mp = p.markov.predict(last)
            fp = _freq_dist(seq)

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
                tc = min(consec, 6)
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
        fp = _freq_dist(seq)

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
            tc = min(consec, 6)
            pce += ce_safe(ap, tc)
            fce += ce_safe(fp, tc)
            n += 1

    avg_pce = pce / n if n > 0 else 10.0
    avg_fce = fce / n if n > 0 else 10.0

    return {
        "name": "consecutive",
        "n_cats": 1,
        "pce": avg_pce,
        "fce": avg_fce,
        "imp": (avg_fce - avg_pce) / max(avg_fce, 1e-9) * 100,
        "wins": avg_pce < avg_fce,
        "w": best
    }

# ===== 4. Lotto Paper (14 categories) =====
def validate_lotto_paper(draws, val_rounds, test_rounds):
    """Lotto Paper: 14 categories (7 rows + 7 cols)."""
    print("\n[4/8] Lotto Paper (14 categories)")

    train_draws = [d for d in draws if int(d.get("round", 0)) <= 1050]
    p = LottoPaperPredictor()
    print(f"  Training on {len(train_draws)} rounds...", end="", flush=True)
    p.train(train_draws, 50)
    print(" Done")

    # validation: per-category grid search
    best_w = {}
    for cat in range(14):
        best = (0.15, 0.45, 0.40)
        best_ce = 1e9
        for w in WEIGHT_GRID:
            ce_sum, n = 0, 0
            for tr in val_rounds:
                hist = [d for d in draws if int(d.get("round", 0)) < tr]
                cm = p._extract(hist)
                s = cm[:, cat]
                last = int(s[-1])

                mp = p.markov_heads[cat].predict(last)
                fp = _freq_dist(s)

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
                    nums = tgt["numbers"]
                    if cat < 7:
                        # row
                        row_idx = cat
                        tc = sum(1 for n in nums if (n-1)//7 == row_idx)
                    else:
                        # col
                        col_idx = cat - 7
                        tc = sum(1 for n in nums if (n-1)%7 == col_idx)
                    ce_sum += ce_safe(ap, tc)
                    n += 1

            if n > 0:
                avg = ce_sum / n
                if avg < best_ce:
                    best_ce = avg
                    best = w

        best_w[cat] = best
        cat_label = [f"row_{i}" for i in range(7)] + [f"col_{i}" for i in range(7)]
        print(f"  {cat_label[cat]}: {best} (val_ce={best_ce:.4f})")

    # test
    cat_res = {}
    for cat in range(14):
        w = best_w[cat]
        pce, fce, n = 0, 0, 0
        for tr in test_rounds:
            hist = [d for d in draws if int(d.get("round", 0)) < tr]
            cm = p._extract(hist)
            s = cm[:, cat]
            last = int(s[-1])

            mp = p.markov_heads[cat].predict(last)
            fp = _freq_dist(s)

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
                nums = tgt["numbers"]
                if cat < 7:
                    row_idx = cat
                    tc = sum(1 for n in nums if (n-1)//7 == row_idx)
                else:
                    col_idx = cat - 7
                    tc = sum(1 for n in nums if (n-1)%7 == col_idx)
                pce += ce_safe(ap, tc)
                fce += ce_safe(fp, tc)
                n += 1

        if n > 0:
            cat_label = [f"row_{i}" for i in range(7)] + [f"col_{i}" for i in range(7)]
            cat_res[cat_label[cat]] = {"pce": pce/n, "fce": fce/n, "w": w}

    avg_pce = np.mean([r["pce"] for r in cat_res.values()])
    avg_fce = np.mean([r["fce"] for r in cat_res.values()])

    return {
        "name": "lotto_paper",
        "n_cats": 14,
        "pce": avg_pce,
        "fce": avg_fce,
        "imp": (avg_fce - avg_pce) / max(avg_fce, 1e-9) * 100,
        "wins": avg_pce < avg_fce,
        "cats": cat_res
    }

# ===== 5. Multiple (6 categories) =====
def validate_multiple(draws, val_rounds, test_rounds):
    """Multiple: 6 categories."""
    print("\n[5/8] Multiple (6 categories)")

    from predictors.phase1_multiple import MULTIPLE_SETS

    train_draws = [d for d in draws if int(d.get("round", 0)) <= 1050]
    p = MultiplePredictor()
    print(f"  Training on {len(train_draws)} rounds...", end="", flush=True)
    p.train(train_draws, 50)
    print(" Done")

    # validation: per-category grid search
    best_w = {}
    for cat in range(6):
        best = (0.15, 0.45, 0.40)
        best_ce = 1e9
        for w in WEIGHT_GRID:
            ce_sum, n = 0, 0
            for tr in val_rounds:
                hist = [d for d in draws if int(d.get("round", 0)) < tr]
                cm = p._extract(hist)
                s = cm[:, cat]
                last = int(s[-1])

                mp = p.markov_heads[cat].predict(last)
                fp = _freq_dist(s)

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
                    nums = tgt["numbers"]
                    label = p.labels[cat]
                    tc = sum(1 for n in nums if n in MULTIPLE_SETS[label])
                    ce_sum += ce_safe(ap, tc)
                    n += 1

            if n > 0:
                avg = ce_sum / n
                if avg < best_ce:
                    best_ce = avg
                    best = w

        best_w[cat] = best
        print(f"  {p.labels[cat]}: {best} (val_ce={best_ce:.4f})")

    # test
    cat_res = {}
    for cat in range(6):
        w = best_w[cat]
        pce, fce, n = 0, 0, 0
        for tr in test_rounds:
            hist = [d for d in draws if int(d.get("round", 0)) < tr]
            cm = p._extract(hist)
            s = cm[:, cat]
            last = int(s[-1])

            mp = p.markov_heads[cat].predict(last)
            fp = _freq_dist(s)

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
                nums = tgt["numbers"]
                label = p.labels[cat]
                tc = sum(1 for n in nums if n in MULTIPLE_SETS[label])
                pce += ce_safe(ap, tc)
                fce += ce_safe(fp, tc)
                n += 1

        if n > 0:
            cat_res[p.labels[cat]] = {"pce": pce/n, "fce": fce/n, "w": w}

    avg_pce = np.mean([r["pce"] for r in cat_res.values()])
    avg_fce = np.mean([r["fce"] for r in cat_res.values()])

    return {
        "name": "multiple",
        "n_cats": 6,
        "pce": avg_pce,
        "fce": avg_fce,
        "imp": (avg_fce - avg_pce) / max(avg_fce, 1e-9) * 100,
        "wins": avg_pce < avg_fce,
        "cats": cat_res
    }

# ===== 6. Special Number (5 categories) =====
def validate_special_number(draws, val_rounds, test_rounds):
    """Special Number: 5 categories."""
    print("\n[6/8] Special Number (5 categories)")

    from predictors.phase1_special_number import SPECIAL_SETS

    train_draws = [d for d in draws if int(d.get("round", 0)) <= 1050]
    p = SpecialNumberPredictor()
    print(f"  Training on {len(train_draws)} rounds...", end="", flush=True)
    p.train(train_draws, 50)
    print(" Done")

    # validation: per-category grid search
    best_w = {}
    for cat in range(5):
        best = (0.15, 0.45, 0.40)
        best_ce = 1e9
        for w in WEIGHT_GRID:
            ce_sum, n = 0, 0
            for tr in val_rounds:
                hist = [d for d in draws if int(d.get("round", 0)) < tr]
                cm = p._extract(hist)
                s = cm[:, cat]
                last = int(s[-1])

                mp = p.markov_heads[cat].predict(last)
                fp = _freq_dist(s)

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
                    nums = tgt["numbers"]
                    label = p.labels[cat]
                    tc = sum(1 for n in nums if n in SPECIAL_SETS[label])
                    ce_sum += ce_safe(ap, tc)
                    n += 1

            if n > 0:
                avg = ce_sum / n
                if avg < best_ce:
                    best_ce = avg
                    best = w

        best_w[cat] = best
        print(f"  {p.labels[cat]}: {best} (val_ce={best_ce:.4f})")

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
            fp = _freq_dist(s)

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
                nums = tgt["numbers"]
                label = p.labels[cat]
                tc = sum(1 for n in nums if n in SPECIAL_SETS[label])
                pce += ce_safe(ap, tc)
                fce += ce_safe(fp, tc)
                n += 1

        if n > 0:
            cat_res[p.labels[cat]] = {"pce": pce/n, "fce": fce/n, "w": w}

    avg_pce = np.mean([r["pce"] for r in cat_res.values()])
    avg_fce = np.mean([r["fce"] for r in cat_res.values()])

    return {
        "name": "special_number",
        "n_cats": 5,
        "pce": avg_pce,
        "fce": avg_fce,
        "imp": (avg_fce - avg_pce) / max(avg_fce, 1e-9) * 100,
        "wins": avg_pce < avg_fce,
        "cats": cat_res
    }

# ===== 7. Missing Group (4 categories) =====
def validate_missing_group(draws, val_rounds, test_rounds):
    """Missing Group: 4 categories."""
    print("\n[7/8] Missing Group (4 categories)")

    train_draws = [d for d in draws if int(d.get("round", 0)) <= 1050]
    p = MissingGroupPredictor()
    print(f"  Training on {len(train_draws)} rounds...", end="", flush=True)
    p.train(train_draws, 50)
    print(" Done")

    # validation: per-category grid search
    best_w = {}
    for cat in range(4):
        best = (0.15, 0.45, 0.40)
        best_ce = 1e9
        for w in WEIGHT_GRID:
            ce_sum, n = 0, 0
            for tr in val_rounds:
                hist = [d for d in draws if int(d.get("round", 0)) < tr]
                cm = p._extract(hist)
                s = cm[:, cat]
                last = int(s[-1])

                mp = p.markov_heads[cat].predict(last)
                fp = _freq_dist(s)

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
                    # 정답 계산
                    tgt_cm = p._extract([d for d in draws if int(d.get("round", 0)) <= tr])
                    tc = int(tgt_cm[-1, cat])
                    ce_sum += ce_safe(ap, tc)
                    n += 1

            if n > 0:
                avg = ce_sum / n
                if avg < best_ce:
                    best_ce = avg
                    best = w

        best_w[cat] = best
        print(f"  {p.labels[cat]}: {best} (val_ce={best_ce:.4f})")

    # test
    cat_res = {}
    for cat in range(4):
        w = best_w[cat]
        pce, fce, n = 0, 0, 0
        for tr in test_rounds:
            hist = [d for d in draws if int(d.get("round", 0)) < tr]
            cm = p._extract(hist)
            s = cm[:, cat]
            last = int(s[-1])

            mp = p.markov_heads[cat].predict(last)
            fp = _freq_dist(s)

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
                tgt_cm = p._extract([d for d in draws if int(d.get("round", 0)) <= tr])
                tc = int(tgt_cm[-1, cat])
                pce += ce_safe(ap, tc)
                fce += ce_safe(fp, tc)
                n += 1

        if n > 0:
            cat_res[p.labels[cat]] = {"pce": pce/n, "fce": fce/n, "w": w}

    avg_pce = np.mean([r["pce"] for r in cat_res.values()])
    avg_fce = np.mean([r["fce"] for r in cat_res.values()])

    return {
        "name": "missing_group",
        "n_cats": 4,
        "pce": avg_pce,
        "fce": avg_fce,
        "imp": (avg_fce - avg_pce) / max(avg_fce, 1e-9) * 100,
        "wins": avg_pce < avg_fce,
        "cats": cat_res
    }

# ===== 8. Hot/Cold (12 categories) =====
def validate_hotcold(draws, val_rounds, test_rounds):
    """Hot/Cold: 12 categories."""
    print("\n[8/8] Hot/Cold (12 categories)")

    train_draws = [d for d in draws if int(d.get("round", 0)) <= 1050]
    p = HotColdPredictor()
    print(f"  Training on {len(train_draws)} rounds...", end="", flush=True)
    p.train(train_draws, 50)
    print(" Done")

    # validation: per-category grid search
    best_w = {}
    for cat in range(12):
        best = (0.15, 0.45, 0.40)
        best_ce = 1e9
        for w in WEIGHT_GRID:
            ce_sum, n = 0, 0
            for tr in val_rounds:
                hist = [d for d in draws if int(d.get("round", 0)) < tr]
                cm = p._extract(hist)
                s = cm[:, cat]
                last = int(s[-1])

                mp = p.markov_heads[cat].predict(last)
                fp = _freq_dist(s)

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
                    # 정답 계산
                    tgt_cm = p._extract([d for d in draws if int(d.get("round", 0)) <= tr])
                    tc = int(tgt_cm[-1, cat])
                    ce_sum += ce_safe(ap, tc)
                    n += 1

            if n > 0:
                avg = ce_sum / n
                if avg < best_ce:
                    best_ce = avg
                    best = w

        best_w[cat] = best
        print(f"  {p.labels[cat]}: {best} (val_ce={best_ce:.4f})")

    # test
    cat_res = {}
    for cat in range(12):
        w = best_w[cat]
        pce, fce, n = 0, 0, 0
        for tr in test_rounds:
            hist = [d for d in draws if int(d.get("round", 0)) < tr]
            cm = p._extract(hist)
            s = cm[:, cat]
            last = int(s[-1])

            mp = p.markov_heads[cat].predict(last)
            fp = _freq_dist(s)

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
                tgt_cm = p._extract([d for d in draws if int(d.get("round", 0)) <= tr])
                tc = int(tgt_cm[-1, cat])
                pce += ce_safe(ap, tc)
                fce += ce_safe(fp, tc)
                n += 1

        if n > 0:
            cat_res[p.labels[cat]] = {"pce": pce/n, "fce": fce/n, "w": w}

    avg_pce = np.mean([r["pce"] for r in cat_res.values()])
    avg_fce = np.mean([r["fce"] for r in cat_res.values()])

    return {
        "name": "hotcold",
        "n_cats": 12,
        "pce": avg_pce,
        "fce": avg_fce,
        "imp": (avg_fce - avg_pce) / max(avg_fce, 1e-9) * 100,
        "wins": avg_pce < avg_fce,
        "cats": cat_res
    }

def main():
    print("=" * 80)
    print("Phase 1 Batch Validation - 8 Predictors")
    print("122-round hold-out test (1101-1222)")
    print("=" * 80)

    start = time.time()

    draws = fetch_all_draws()
    if len(draws) < 1222:
        print(f"ERROR: need 1222 rounds, got {len(draws)}")
        return

    val_rounds = list(range(1076, 1101))  # 25 (reduced for speed)
    test_rounds = list(range(1101, 1223))  # 122

    print(f"\nData split:")
    print(f"  Train: 31-1050 (1020 rounds)")
    print(f"  Val:   1076-1100 (25 rounds)")
    print(f"  Test:  1101-1222 (122 rounds)")
    print(f"\nWeight grid ({len(WEIGHT_GRID)} candidates)")
    print(f"  Total validations per category: {len(WEIGHT_GRID) * 25} evals")

    results = []

    results.append(validate_carryover(draws, val_rounds, test_rounds))
    results.append(validate_neighbor(draws, val_rounds, test_rounds))
    results.append(validate_consecutive(draws, val_rounds, test_rounds))
    results.append(validate_lotto_paper(draws, val_rounds, test_rounds))
    results.append(validate_multiple(draws, val_rounds, test_rounds))
    results.append(validate_special_number(draws, val_rounds, test_rounds))
    results.append(validate_missing_group(draws, val_rounds, test_rounds))
    results.append(validate_hotcold(draws, val_rounds, test_rounds))

    elapsed = time.time() - start

    # ===== FINAL REPORT =====
    print("\n" + "=" * 80)
    print("FINAL RESULTS (122 test rounds: 1101~1222)")
    print("=" * 80)

    pass_count = 0
    for r in results:
        gate = "PASS" if r["wins"] else "FAIL"
        if r["wins"]:
            pass_count += 1

        print(f"\n{r['name']} ({r['n_cats']} categories):")
        print(f"  predictor_ce: {r['pce']:.4f}")
        print(f"  frequency_ce: {r['fce']:.4f}")
        print(f"  improvement:  {r['imp']:+.2f}%")
        print(f"  GATE: {gate}")

        if "w" in r:
            print(f"  best_weight: {r['w']}")
        elif "cats" in r:
            # 샘플 3개만 출력
            cat_items = list(r["cats"].items())[:3]
            print(f"  sample weights:")
            for cn, cd in cat_items:
                print(f"    {cn}: {cd['w']} (pce={cd['pce']:.4f}, fce={cd['fce']:.4f})")
            if len(r["cats"]) > 3:
                print(f"    ... ({len(r['cats'])-3} more)")

    print("\n" + "=" * 80)
    print(f"PASS rate: {pass_count}/8")
    print(f"Time: {elapsed:.1f}s ({elapsed/60:.1f}min)")
    print("=" * 80)

if __name__ == "__main__":
    main()
