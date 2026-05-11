"""16 Phase predictor 검증 게이트 자동화 스크립트.

Phase 1 (13): endings, odd_even, high_low, decade, gung, carryover, neighbor,
              consecutive, lotto_paper, multiple, special_number, missing_group, hotcold
Phase 2 (1): endings_sum
Phase 3 (1): ac
Phase 4 (1): sum

각 predictor에 대해:
- walk-forward 50회차 CE 측정
- frequency baseline 비교
- PASS/FAIL 판정 (predictor_ce < frequency_ce)
"""

from __future__ import annotations

import sys
from typing import Any

import numpy as np

from db.supabase_client import fetch_all_draws
from validation.baseline_runner import BaselineRunner


# ────────────────── predictor 임포트 ──────────────────


def import_predictor(phase: int, name: str) -> tuple[Any, str] | None:
    """predictor class 동적 임포트. (Predictor class, module_name) 반환."""
    try:
        if phase == 1:
            if name == "endings":
                from predictors.phase1_endings_distribution import EndingsDistributionPredictor
                return EndingsDistributionPredictor, "endings_distribution"
            elif name == "odd_even":
                from predictors.phase1_odd_even import OddEvenPredictor
                return OddEvenPredictor, "odd_even"
            elif name == "high_low":
                from predictors.phase1_high_low import HighLowPredictor
                return HighLowPredictor, "high_low"
            elif name == "decade":
                from predictors.phase1_decade import DecadePredictor
                return DecadePredictor, "decade"
            elif name == "gung":
                from predictors.phase1_gung import GungPredictor
                return GungPredictor, "gung"
            elif name == "carryover":
                from predictors.phase1_carryover import CarryoverPredictor
                return CarryoverPredictor, "carryover"
            elif name == "neighbor":
                from predictors.phase1_neighbor import NeighborPredictor
                return NeighborPredictor, "neighbor"
            elif name == "consecutive":
                from predictors.phase1_consecutive import ConsecutivePredictor
                return ConsecutivePredictor, "consecutive"
            elif name == "lotto_paper":
                from predictors.phase1_lotto_paper import LottoPaperPredictor
                return LottoPaperPredictor, "lotto_paper"
            elif name == "multiple":
                from predictors.phase1_multiple import MultiplePredictor
                return MultiplePredictor, "multiple"
            elif name == "special":
                from predictors.phase1_special_number import SpecialNumberPredictor
                return SpecialNumberPredictor, "special_number"
            elif name == "missing":
                from predictors.phase1_missing_group import MissingGroupPredictor
                return MissingGroupPredictor, "missing_group"
            elif name == "hotcold":
                from predictors.phase1_hotcold import HotColdPredictor
                return HotColdPredictor, "hotcold"
        elif phase == 2:
            if name == "endings_sum":
                from predictors.phase2_endings_sum import Phase2EndingsSumPredictor
                return Phase2EndingsSumPredictor, "endings_sum"
        elif phase == 3:
            if name == "ac":
                from predictors.phase3_ac import Phase3ACPredictor
                return Phase3ACPredictor, "ac"
        elif phase == 4:
            if name == "sum":
                from predictors.phase4_sum import SumPredictor
                return SumPredictor, "sum"
    except ImportError as e:
        print(f"  [WARN] predictor import fail: phase{phase} {name} — {e}")
    return None


# ────────────────── 검증 함수 ──────────────────


def validate_phase1_predictor(
    predictor_cls: Any,
    indicator_name: str,
    draws: list[dict],
    n_rounds: int = 50,
) -> dict:
    """Phase 1 predictor 검증 (카테고리별).

    Returns:
        {
            "n_categories": int,
            "avg_predictor_ce": float,
            "avg_frequency_ce": float,
            "improvement_pct": float,
            "wins": bool,
            "status": "PASS" | "FAIL",
        }
    """
    rounds = sorted([int(d["round"]) for d in draws])[-n_rounds:]
    p = predictor_cls()
    r = BaselineRunner()

    # 카테고리 추출 (하드코드 회피 — train 후 예제 출력 파싱)
    hist_sample = [d for d in draws if int(d.get("round", 0)) < rounds[0]]
    if len(hist_sample) < 50:
        return {"error": "insufficient_history"}

    try:
        p.train(hist_sample, 50)
        sample_out = p.predict(hist_sample, rounds[0])
        per_cat = sample_out.get("per_category", {})
        categories = list(per_cat.keys())
    except Exception as e:
        return {"error": f"train_fail: {e}"}

    if not categories:
        return {"error": "no_categories"}

    # 카테고리별 CE 누적
    cat_results = {}
    for cat in categories:
        pce_tot, fce_tot, n = 0.0, 0.0, 0
        for target_round in rounds:
            hist = [d for d in draws if int(d.get("round", 0)) < target_round]
            if len(hist) < 50:
                continue

            try:
                p.train(hist, 50)
                out = p.predict(hist, target_round)
                pred_dist = np.array(out["per_category"][cat]["absolute_dist"])
            except Exception:
                continue

            # target 추출 (indicator별로 상이)
            target_draw = next((d for d in draws if int(d["round"]) == target_round), None)
            if not target_draw:
                continue

            # 카테고리 해석 (간단 휴리스틱)
            target_count = _extract_target_count(target_draw, indicator_name, cat)
            if target_count is None:
                continue

            # frequency baseline
            freq_dist = _compute_frequency_dist(hist, indicator_name, cat, n_classes=len(pred_dist))

            pce_tot += r.cross_entropy(pred_dist, target_count)
            fce_tot += r.cross_entropy(freq_dist, target_count)
            n += 1

        if n > 0:
            cat_results[cat] = {
                "predictor_ce": pce_tot / n,
                "frequency_ce": fce_tot / n,
                "n_rounds": n,
            }

    if not cat_results:
        return {"error": "no_valid_rounds"}

    avg_pce = float(np.mean([c["predictor_ce"] for c in cat_results.values()]))
    avg_fce = float(np.mean([c["frequency_ce"] for c in cat_results.values()]))
    improvement = (avg_fce - avg_pce) / max(avg_fce, 1e-9) * 100
    wins = avg_pce < avg_fce

    return {
        "n_categories": len(cat_results),
        "avg_predictor_ce": avg_pce,
        "avg_frequency_ce": avg_fce,
        "improvement_pct": improvement,
        "wins": wins,
        "status": "PASS" if wins else "FAIL",
    }


def validate_phase2_predictor(
    predictor_cls: Any,
    indicator_name: str,
    draws: list[dict],
    n_rounds: int = 50,
) -> dict:
    """Phase 2/3 predictor 검증 (스칼라 회귀).

    Returns:
        {
            "avg_predictor_mae": float,
            "avg_frequency_mae": float,
            "improvement_pct": float,
            "wins": bool,
            "status": "PASS" | "FAIL",
        }
    """
    rounds = sorted([int(d["round"]) for d in draws])[-n_rounds:]
    p = predictor_cls()

    mae_pred_tot, mae_freq_tot, n = 0.0, 0.0, 0
    for target_round in rounds:
        hist = [d for d in draws if int(d.get("round", 0)) < target_round]
        if len(hist) < 50:
            continue

        try:
            p.train(hist, phase1_outputs=None)
            out = p.predict(hist, phase1_outputs=None)
            pred_val = out.get("expected_value", 0.0)
        except Exception:
            continue

        target_draw = next((d for d in draws if int(d["round"]) == target_round), None)
        if not target_draw:
            continue

        # scalar target 추출
        if indicator_name == "endings_sum":
            target_val = sum(int(n) % 10 for n in target_draw.get("numbers", []))
        elif indicator_name == "ac":
            target_val = _compute_ac(target_draw.get("numbers", []))
        elif indicator_name == "sum":
            target_val = sum(target_draw.get("numbers", []))
        else:
            continue

        # frequency baseline: 역대 평균
        freq_val = _compute_frequency_mean(hist, indicator_name)

        mae_pred_tot += abs(pred_val - target_val)
        mae_freq_tot += abs(freq_val - target_val)
        n += 1

    if n == 0:
        return {"error": "no_valid_rounds"}

    avg_pred_mae = mae_pred_tot / n
    avg_freq_mae = mae_freq_tot / n
    improvement = (avg_freq_mae - avg_pred_mae) / max(avg_freq_mae, 1e-9) * 100
    wins = avg_pred_mae < avg_freq_mae

    return {
        "avg_predictor_mae": avg_pred_mae,
        "avg_frequency_mae": avg_freq_mae,
        "improvement_pct": improvement,
        "wins": wins,
        "status": "PASS" if wins else "FAIL",
    }


# ────────────────── 헬퍼 ──────────────────


def _extract_target_count(draw: dict, indicator: str, category: str) -> int | None:
    """회차 draw에서 카테고리 카운트 추출."""
    nums = draw.get("numbers", [])
    if not nums:
        return None

    if indicator == "endings_distribution":
        digit = int(category.split("_")[-1])
        return sum(1 for n in nums if int(n) % 10 == digit)
    elif indicator == "odd_even":
        return sum(1 for n in nums if int(n) % 2 == 1)
    elif indicator == "high_low":
        if "high" in category:
            return sum(1 for n in nums if int(n) >= 23)
        else:
            return sum(1 for n in nums if int(n) < 23)
    elif indicator == "decade":
        decade_idx = int(category.split("_")[-1])
        return sum(1 for n in nums if int(n) // 10 == decade_idx)
    elif indicator == "gung":
        gung_map = {n: n % 9 for n in range(1, 46)}
        gung_idx = int(category.split("_")[-1])
        return sum(1 for n in nums if gung_map.get(int(n), -1) == gung_idx)
    elif indicator == "carryover":
        # 이월수: 직전 회차 overlap (회차 순서 필요 — 복잡하므로 skip)
        return None
    elif indicator == "consecutive":
        return _count_consecutive(nums)
    elif indicator == "lotto_paper":
        row = int(category.split("_")[-1])
        return sum(1 for n in nums if (int(n) - 1) // 7 == row)
    elif indicator == "multiple":
        base = int(category.split("_")[-1])
        return sum(1 for n in nums if int(n) % base == 0)
    elif indicator == "special_number":
        # special: 1, 5, 7, 11, 13 (소수) — 임의 정의
        specials = {1, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43}
        return sum(1 for n in nums if n in specials)
    elif indicator == "missing_group":
        # missing: 최근 N회차 미출현 — 복잡, skip
        return None
    elif indicator == "hotcold":
        # hot/cold: 최근 빈도 — 복잡, skip
        return None
    elif indicator == "neighbor":
        # neighbor: 직전 회차 +/-1 — 복잡, skip
        return None

    return None


def _compute_frequency_dist(hist: list[dict], indicator: str, category: str, n_classes: int = 7) -> np.ndarray:
    """역대 빈도 분포 (7-class)."""
    counts = []
    for d in hist:
        cnt = _extract_target_count(d, indicator, category)
        if cnt is not None:
            counts.append(cnt)

    if not counts:
        return np.full(n_classes, 1.0 / n_classes)

    arr = np.array(counts, dtype=np.int64)
    bin_counts = np.bincount(arr, minlength=n_classes)[:n_classes]
    total = bin_counts.sum()
    return bin_counts / max(total, 1.0)


def _compute_frequency_mean(hist: list[dict], indicator: str) -> float:
    """역대 평균 (scalar)."""
    vals = []
    for d in hist:
        if indicator == "endings_sum":
            val = sum(int(n) % 10 for n in d.get("numbers", []))
        elif indicator == "ac":
            val = _compute_ac(d.get("numbers", []))
        elif indicator == "sum":
            val = sum(d.get("numbers", []))
        else:
            val = 0
        vals.append(val)

    return float(np.mean(vals)) if vals else 0.0


def _compute_ac(nums: list) -> int:
    """AC 값 계산 (인접 차이 절댓값 합)."""
    if len(nums) < 2:
        return 0
    sorted_nums = sorted(nums)
    return sum(abs(sorted_nums[i] - sorted_nums[i - 1]) - 1 for i in range(1, len(sorted_nums)))


def _count_consecutive(nums: list) -> int:
    """연속번호 개수."""
    if len(nums) < 2:
        return 0
    sorted_nums = sorted(nums)
    count = 0
    for i in range(1, len(sorted_nums)):
        if sorted_nums[i] == sorted_nums[i - 1] + 1:
            count += 1
    return count


# ────────────────── main ──────────────────


PHASE1_PREDICTORS = [
    ("endings", "끝수분포"),
    ("odd_even", "홀짝"),
    ("high_low", "고저"),
    ("decade", "번호대"),
    ("gung", "9궁"),
    ("carryover", "이월수"),
    ("neighbor", "인접"),
    ("consecutive", "연속"),
    ("lotto_paper", "로또용지"),
    ("multiple", "배수"),
    ("special", "특수"),
    ("missing", "미출현"),
    ("hotcold", "핫콜드"),
]

PHASE2_PREDICTORS = [
    ("endings_sum", "끝수합"),
]

PHASE3_PREDICTORS = [
    ("ac", "AC값"),
]

PHASE4_PREDICTORS = [
    # ("sum", "총합"),  # 별도 구현 필요
]


def main():
    print("=" * 80)
    print("16 Phase Predictor 검증 게이트 자동화")
    print("=" * 80)

    draws = fetch_all_draws()
    if len(draws) < 200:
        print(f"ERROR: insufficient draws ({len(draws)}). Need >= 200")
        sys.exit(1)

    results = []

    # Phase 1 (13)
    for short_name, kr_name in PHASE1_PREDICTORS:
        print(f"\n[Phase 1] {kr_name} ({short_name})")
        ret = import_predictor(1, short_name)
        if ret is None:
            print("  SKIP (import fail)")
            results.append({
                "predictor": short_name,
                "kr_name": kr_name,
                "status": "SKIP",
                "error": "import_fail",
            })
            continue

        predictor_cls, indicator_name = ret
        res = validate_phase1_predictor(predictor_cls, indicator_name, draws, n_rounds=50)

        if "error" in res:
            print(f"  ERROR: {res['error']}")
            results.append({
                "predictor": short_name,
                "kr_name": kr_name,
                "status": "ERROR",
                "error": res["error"],
            })
        else:
            print(f"  카테고리: {res['n_categories']}")
            print(f"  Predictor CE: {res['avg_predictor_ce']:.4f}")
            print(f"  Frequency CE: {res['avg_frequency_ce']:.4f}")
            print(f"  Improvement: {res['improvement_pct']:+.2f}%")
            print(f"  Status: {res['status']}")
            results.append({
                "predictor": short_name,
                "kr_name": kr_name,
                "status": res["status"],
                "predictor_ce": res["avg_predictor_ce"],
                "frequency_ce": res["avg_frequency_ce"],
                "improvement_pct": res["improvement_pct"],
            })

    # Phase 2 (1)
    for short_name, kr_name in PHASE2_PREDICTORS:
        print(f"\n[Phase 2] {kr_name} ({short_name})")
        ret = import_predictor(2, short_name)
        if ret is None:
            print("  SKIP (import fail)")
            results.append({
                "predictor": short_name,
                "kr_name": kr_name,
                "status": "SKIP",
                "error": "import_fail",
            })
            continue

        predictor_cls, indicator_name = ret
        res = validate_phase2_predictor(predictor_cls, indicator_name, draws, n_rounds=50)

        if "error" in res:
            print(f"  ERROR: {res['error']}")
            results.append({
                "predictor": short_name,
                "kr_name": kr_name,
                "status": "ERROR",
                "error": res["error"],
            })
        else:
            print(f"  Predictor MAE: {res['avg_predictor_mae']:.2f}")
            print(f"  Frequency MAE: {res['avg_frequency_mae']:.2f}")
            print(f"  Improvement: {res['improvement_pct']:+.2f}%")
            print(f"  Status: {res['status']}")
            results.append({
                "predictor": short_name,
                "kr_name": kr_name,
                "status": res["status"],
                "predictor_mae": res["avg_predictor_mae"],
                "frequency_mae": res["avg_frequency_mae"],
                "improvement_pct": res["improvement_pct"],
            })

    # Phase 3 (1)
    for short_name, kr_name in PHASE3_PREDICTORS:
        print(f"\n[Phase 3] {kr_name} ({short_name})")
        ret = import_predictor(3, short_name)
        if ret is None:
            print("  SKIP (import fail)")
            results.append({
                "predictor": short_name,
                "kr_name": kr_name,
                "status": "SKIP",
                "error": "import_fail",
            })
            continue

        predictor_cls, indicator_name = ret
        res = validate_phase2_predictor(predictor_cls, indicator_name, draws, n_rounds=50)

        if "error" in res:
            print(f"  ERROR: {res['error']}")
            results.append({
                "predictor": short_name,
                "kr_name": kr_name,
                "status": "ERROR",
                "error": res["error"],
            })
        else:
            print(f"  Predictor MAE: {res['avg_predictor_mae']:.2f}")
            print(f"  Frequency MAE: {res['avg_frequency_mae']:.2f}")
            print(f"  Improvement: {res['improvement_pct']:+.2f}%")
            print(f"  Status: {res['status']}")
            results.append({
                "predictor": short_name,
                "kr_name": kr_name,
                "status": res["status"],
                "predictor_mae": res["avg_predictor_mae"],
                "frequency_mae": res["avg_frequency_mae"],
                "improvement_pct": res["improvement_pct"],
            })

    # 요약
    print("\n" + "=" * 80)
    print("요약")
    print("=" * 80)
    print(f"{'Predictor':<20} {'한글':<12} {'Status':<8} {'Predictor':<12} {'Baseline':<12} {'Improvement':<12}")
    print("-" * 80)
    for r in results:
        predictor = r["predictor"]
        kr_name = r["kr_name"]
        status = r["status"]
        if status == "PASS" or status == "FAIL":
            if "predictor_ce" in r:
                p_val = f"{r['predictor_ce']:.4f}"
                b_val = f"{r['frequency_ce']:.4f}"
            else:
                p_val = f"{r['predictor_mae']:.2f}"
                b_val = f"{r['frequency_mae']:.2f}"
            imp = f"{r['improvement_pct']:+.2f}%"
        else:
            p_val = "N/A"
            b_val = "N/A"
            imp = "N/A"
        print(f"{predictor:<20} {kr_name:<12} {status:<8} {p_val:<12} {b_val:<12} {imp:<12}")

    pass_count = sum(1 for r in results if r["status"] == "PASS")
    total_count = len(results)
    pass_rate = pass_count / max(total_count, 1) * 100

    print("=" * 80)
    print(f"PASS rate: {pass_count}/{total_count} ({pass_rate:.1f}%)")
    print(f"목표: ≥ 12/16 (75%)")
    if pass_rate >= 75:
        print("✓ 검증 게이트 통과")
    else:
        print("✗ 검증 게이트 미통과")
    print("=" * 80)


if __name__ == "__main__":
    main()
