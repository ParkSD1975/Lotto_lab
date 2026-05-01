"""[fix-77] 1222 회차에 prime_hot / prime_cold row 시드.

weekly_pipeline 전체 재실행은 무거우므로, 기존 prime row의 model_expectations를
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


def _split(val, ratio):
    if val is None:
        return None
    return max(0, min(6, round(val * ratio)))


def seed(target_round: int = 1222):
    client = get_client()

    # 1) 최근 3회차 가져와서 prime_hot/prime_cold 풀 계산
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
    hot_pool = PRIMES & last_3_set
    cold_pool = PRIMES - hot_pool
    H = len(hot_pool)
    C = len(cold_pool)
    print(f"[seed] target_round={target_round}, last_3 rounds={[d['round'] for d in last_3]}")
    print(f"[seed] hot_pool({H}개)={sorted(hot_pool)}")
    print(f"[seed] cold_pool({C}개)={sorted(cold_pool)}")

    if H + C != 14:
        print(f"[seed] ERROR: H+C != 14")
        return

    # 2) 기존 prime row 조회
    prime_res = client.table("weekly_filter_predictions") \
        .select("*") \
        .eq("target_round", target_round) \
        .eq("filter_key", "prime") \
        .execute()
    prime_rows = prime_res.data or []
    if not prime_rows:
        print(f"[seed] ERROR: prime row 없음 ({target_round})")
        return
    prime_row = prime_rows[0]

    # 3) 핫/콜드 row 빌드 (비율 분할)
    for new_key, ratio, label_kr, pool_size in [
        ("prime_hot", H / 14.0 if H else 0.0, "소수(핫)", H),
        ("prime_cold", C / 14.0 if C else 0.0, "소수(콜드)", C),
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
            print(f"[seed] {new_key} OK ({label_kr}, 풀 {pool_size}개) → "
                  f"ensemble {new_min}~{new_max}")
        except Exception as e:
            print(f"[seed] {new_key} FAIL: {e}")


if __name__ == "__main__":
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 1222
    seed(target)
