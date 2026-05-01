"""[fix-77/79] 1222 회차에 prime_hot/prime_cold + composite_hot/composite_cold row 시드.

weekly_pipeline 전체 재실행은 무거우므로, 기존 prime/composite row의 model_expectations를
핫 풀(H개) / 콜드 풀(C개) 크기 비율로 분할한 임시값을 INSERT.
다음 weekly run 시 정확값으로 자동 갱신됨.
"""
import os
import sys
import io
import json

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.supabase_client import get_client


PRIMES = {2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43}
COMPOSITES = {4, 6, 8, 9, 10, 12, 14, 15, 16, 18, 20, 21, 22, 24, 25, 26, 27, 28,
              30, 32, 33, 34, 35, 36, 38, 39, 40, 42, 44, 45}


def _split(val, ratio):
    if val is None:
        return None
    return max(0, min(6, round(val * ratio)))


def _seed_one_pair(client, target_round: int, base_key: str, base_pool: set, label_base: str):
    """공통 시드 함수 — base_key의 row를 핫/콜드 풀 비율로 분할하여 INSERT."""
    pool_total = len(base_pool)

    # 1) 최근 3회차 가져와서 핫/콜드 풀 계산
    draws_res = client.table("lotto_draws") \
        .select("round, numbers") \
        .lt("round", target_round) \
        .order("round", desc=True) \
        .limit(3) \
        .execute()
    last_3 = draws_res.data or []
    last_3_set = set()
    for d in last_3:
        for n in d.get("numbers", []) or []:
            last_3_set.add(n)
    hot_pool = base_pool & last_3_set
    cold_pool = base_pool - hot_pool
    H = len(hot_pool)
    C = len(cold_pool)
    print(f"\n[seed:{base_key}] target_round={target_round}, last_3 rounds={[d['round'] for d in last_3]}")
    print(f"[seed:{base_key}] hot_pool({H}개)={sorted(hot_pool)}")
    print(f"[seed:{base_key}] cold_pool({C}개)={sorted(cold_pool)}")

    if H + C != pool_total:
        print(f"[seed:{base_key}] ERROR: H+C != {pool_total}")
        return

    # 2) 기존 base row 조회
    base_res = client.table("weekly_filter_predictions") \
        .select("*") \
        .eq("target_round", target_round) \
        .eq("filter_key", base_key) \
        .execute()
    base_rows = base_res.data or []
    if not base_rows:
        print(f"[seed:{base_key}] ERROR: {base_key} row 없음 ({target_round})")
        return
    prime_row = base_rows[0]

    # 3) 핫/콜드 row 빌드 (비율 분할)
    for new_key, ratio, label_kr, pool_size in [
        (f"{base_key}_hot", H / float(pool_total) if H else 0.0, f"{label_base}(핫)", H),
        (f"{base_key}_cold", C / float(pool_total) if C else 0.0, f"{label_base}(콜드)", C),
    ]:
        # model_expectations 분할
        new_me = {}
        for m, e in (prime_row.get("model_expectations") or {}).items():
            if not isinstance(e, dict):
                continue
            new_me[m] = {
                **{k: v for k, v in e.items() if k not in ("min", "max")},
                "min": _split(e.get("min"), ratio),
                "max": _split(e.get("max"), ratio),
            }
        # ensemble min/max 분할
        new_min = _split(prime_row.get("ensemble_min"), ratio)
        new_max = _split(prime_row.get("ensemble_max"), ratio)

        # ensemble_ci 분할 (가능하면 band string도 새로 만들기)
        ci = prime_row.get("ensemble_ci") or {}
        new_ci = dict(ci) if isinstance(ci, dict) else {}
        if isinstance(ci, dict):
            for k_band in ("lo_p10", "hi_p90"):
                if ci.get(k_band) is not None:
                    new_ci[k_band] = _split(ci.get(k_band), ratio)
            if new_ci.get("lo_p10") is not None and new_ci.get("hi_p90") is not None:
                new_ci["band"] = f"{new_ci['lo_p10']} ~ {new_ci['hi_p90']}"

        new_row = {
            "target_round":       target_round,
            "filter_key":         new_key,
            "ensemble_min":       new_min,
            "ensemble_max":       new_max,
            "ensemble_ci":        new_ci,
            "model_expectations": new_me,
            "primary_task":       prime_row.get("primary_task", "filter_count_attr"),
            "filter_value":       prime_row.get("filter_value"),
            "evidence_text":      None,  # refill에서 LLM 재생성
        }

        # upsert
        try:
            client.table("weekly_filter_predictions") \
                .upsert(new_row, on_conflict="target_round,filter_key") \
                .execute()
            print(f"[seed:{base_key}] {new_key} OK ({label_kr}, 풀 {pool_size}개) → "
                  f"ensemble {new_min}~{new_max}")
        except Exception as e:
            print(f"[seed:{base_key}] {new_key} FAIL: {e}")


def seed(target_round: int = 1222):
    """[fix-77/79] prime_hot/cold + composite_hot/cold 둘 다 시드."""
    client = get_client()
    _seed_one_pair(client, target_round, "prime", PRIMES, "소수")
    _seed_one_pair(client, target_round, "composite", COMPOSITES, "합성수")


if __name__ == "__main__":
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 1222
    seed(target)
