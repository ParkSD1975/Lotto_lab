"""Phase 1 빠른 검증 (20회차).

실행 시간 절감을 위해 walk-forward 20회차로 축소.
"""

import sys
import os
import warnings

warnings.filterwarnings("ignore", category=UserWarning)

script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(script_dir)
sys.path.insert(0, backend_dir)

from predictors.phase1_endings_distribution import validate_walk_forward as validate_endings
from predictors.phase1_high_low import validate_walk_forward as validate_high_low
from predictors.phase1_odd_even import validate_walk_forward as validate_odd_even
from predictors.phase1_decade import validate_walk_forward as validate_decade
from predictors.phase1_gung import validate_walk_forward as validate_gung


def main():
    n_rounds = 20  # 축소 (50 -> 20)
    print(f"\n{'='*80}")
    print(f"Phase 1 Quick Validation - Last {n_rounds} rounds walk-forward")
    print(f"{'='*80}\n")

    validators = [
        ("endings_distribution", validate_endings),
        ("high_low", validate_high_low),
        ("odd_even", validate_odd_even),
        ("decade", validate_decade),
        ("gung", validate_gung),
    ]

    results = []
    for name, validate_fn in validators:
        print(f"[{name}] validating...")
        res = validate_fn(n_rounds)
        if "error" in res:
            print(f"  ERROR: {res['error']}\n")
            results.append({
                "name": name,
                "predictor_ce": None,
                "frequency_ce": None,
                "improvement_pct": None,
                "wins": False,
                "error": res["error"],
            })
        else:
            pce = res["avg_predictor_ce"]
            fce = res["avg_frequency_ce"]
            imp = res["improvement_pct"]
            wins = res["wins_frequency"]
            print(f"  predictor_ce={pce:.4f}, frequency_ce={fce:.4f}, improvement={imp:+.2f}%, wins={wins}\n")
            results.append({
                "name": name,
                "predictor_ce": pce,
                "frequency_ce": fce,
                "improvement_pct": imp,
                "wins": wins,
                "error": None,
            })

    print(f"\n{'='*80}")
    print(f"Quick Validation Summary (n_rounds={n_rounds})")
    print(f"{'='*80}")
    print(f"{'Predictor':<25} {'Pred CE':>10} {'Freq CE':>10} {'Improve':>10} {'Gate':>6}")
    print(f"{'-'*80}")

    pass_count = 0
    for r in results:
        if r["error"]:
            print(f"{r['name']:<25} {'ERROR':<10} {'-':<10} {'-':<10} {'FAIL':>6}")
        else:
            pce = f"{r['predictor_ce']:.4f}"
            fce = f"{r['frequency_ce']:.4f}"
            imp = f"{r['improvement_pct']:+.2f}%"
            gate = "PASS" if r["wins"] else "FAIL"
            if r["wins"]:
                pass_count += 1
            print(f"{r['name']:<25} {pce:>10} {fce:>10} {imp:>10} {gate:>6}")

    print(f"{'-'*80}")
    print(f"\nPassed: {pass_count}/5 predictor(s)")
    if pass_count == 5:
        print("\nAll predictors beat frequency baseline! Run full 50-round validation next.")
    elif pass_count >= 3:
        print(f"\n{pass_count}/5 predictors passed. Promising - run full validation.")
    else:
        print(f"\nOnly {pass_count}/5 passed. Need stronger features or ensemble.")

    print(f"\n{'='*80}\n")


if __name__ == "__main__":
    main()
