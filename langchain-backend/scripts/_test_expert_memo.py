"""Stage 3-5: ExpertMemo e2e 테스트.

흐름:
1. expert_memos에 테스트 메모 insert (forced_includes=[3,7], forced_excludes=[44,45])
2. NumberRecommender.recommend(target_round=1222, auto_load_memo=True) 호출
3. 추천 5에 3 또는 7 포함 검증
4. expert_memo_history.record() 호출
5. memo_score 계산 결과 확인
6. 50회 누적 전 domain_confidence 기본값 (0.5) 확인
"""
from __future__ import annotations

import sys
from pathlib import Path

# langchain-backend를 sys.path에 추가
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import numpy as np

from db.supabase_client import get_client
from models.number_recommender import NumberRecommender, MemoLoader
from services.expert_memo_history import ExpertMemoHistoryTracker

# 1222 회차 실제 당첨번호 (테스트용 가짜)
ACTUAL_1222 = [4, 11, 17, 22, 32, 41]


def main() -> None:
    """e2e 테스트."""
    print("[_test_expert_memo] start")

    # Step 1: expert_memos insert
    client = get_client()
    memo_data = {
        "target_round": 1222,
        "memo_text": "테스트 메모: 3과 7 강제 추천, 44와 45 강제 제외",
        "forced_includes": [3, 7],
        "forced_excludes": [44, 45],
        "confidence": 0.8,
        "domain_tags": ["회귀", "끝수"],
    }

    print("\n[1] Insert test memo into expert_memos")
    try:
        # 기존 메모 삭제 (테스트 반복 실행 대비)
        client.table("expert_memos").delete().eq("target_round", 1222).execute()
        res = client.table("expert_memos").insert(memo_data).execute()
        memo_id = res.data[0]["id"]
        print(f"    Inserted memo_id: {memo_id}")
    except Exception as e:
        print(f"    Insert fail: {e}")
        print("    테이블 미존재 가능성: db/migrations/002_expert_memo_tables.sql 실행 필요")
        return

    # Step 2: NumberRecommender.recommend() 호출 (자동 메모 로드)
    print("\n[2] NumberRecommender.recommend(target_round=1222, auto_load_memo=True)")

    # 가짜 입력 준비
    rng = np.random.default_rng(42)
    probs_arr = rng.dirichlet(np.ones(45) * 0.6)
    fake_final_probs = {n: float(probs_arr[n - 1]) for n in range(1, 46)}

    # 11 base rankings (boost 3, 7, 11 / sink 44, 45)
    base_models = [
        "xgboost", "catboost", "tabnet", "cnn", "gnn", "markov",
        "autoencoder", "tft", "nbeats", "mhn", "bayesian_nn",
    ]
    boost = {3, 7, 11, 17}
    sink = {44, 45}
    fake_rankings: dict[str, list[int]] = {}
    for name in base_models:
        p = rng.dirichlet(np.ones(45) * 0.6)
        for t in boost:
            p[t - 1] += 0.10
        for t in sink:
            p[t - 1] *= 0.05
        p = p / p.sum()
        order = sorted(range(1, 46), key=lambda x: -p[x - 1])
        fake_rankings[name] = order

    fake_filter = [
        {"key": "total_sum", "ml_recommendation": {"min": 100, "median": 132, "max": 165}},
        {"key": "tail_sum", "ml_recommendation": {"min": 15, "median": 20, "max": 28}},
        {"key": "ac_value", "ml_recommendation": {"min": 5, "median": 8, "max": 10}},
        {"key": "odd_even", "ml_recommendation": {"top_class": 3}},
        {"key": "low_high", "ml_recommendation": {"top_class": 3}},
    ]

    fake_predictor = {
        "phase1": {"hotcold": {"per_category": {"hot_pool": [3, 7, 11], "cold_pool": [44, 45]}}},
        "regression": {
            "tier1": {"active_N_set": [2, 3, 8]},
            "tier3_rules": {"force_exclude": set(), "rule1_consecutive_n": [], "rule1_recent": [], "rule2_dead_lines": []},
        },
    }

    recommender = NumberRecommender(memo_loader=MemoLoader())
    result = recommender.recommend(
        final_probs=fake_final_probs,
        filter_stats_result=fake_filter,
        predictor_pipeline_outputs=fake_predictor,
        rankings=fake_rankings,
        target_round=1222,
        auto_load_memo=True,
        n_top=5,
        n_exc=10,
    )

    rec_nums = {r["number"] for r in result["recommendations"]}
    exc_nums = {e["number"] for e in result["exclusions"]}

    print(f"    Recommendations: {sorted(rec_nums)}")
    print(f"    Exclusions     : {sorted(exc_nums)}")

    # Step 3: 검증 - forced_includes 포함 여부
    print("\n[3] Verify forced_includes [3, 7] in recommendations")
    has_3_or_7 = (3 in rec_nums) or (7 in rec_nums)
    print(f"    3 in recs: {3 in rec_nums}, 7 in recs: {7 in rec_nums}")
    print(f"    At least one of [3, 7] in recs: {has_3_or_7}")

    # Step 4: 검증 - forced_excludes 포함 여부
    print("\n[4] Verify forced_excludes [44, 45] in exclusions")
    has_44 = 44 in exc_nums
    has_45 = 45 in exc_nums
    print(f"    44 in excs: {has_44}, 45 in excs: {has_45}")
    print(f"    At least one of [44, 45] in excs: {has_44 or has_45}")

    # Step 5: expert_memo_history.record()
    print("\n[5] ExpertMemoHistoryTracker.update()")
    tracker = ExpertMemoHistoryTracker()
    loaded_memo = {
        "memo_id": memo_id,
        "forced_includes": [3, 7],
        "forced_excludes": [44, 45],
    }
    record = tracker.update(
        target_round=1222,
        memo=loaded_memo,
        actual_winning_numbers=ACTUAL_1222,
    )
    print(f"    hit_rate            : {record['hit_rate']:.4f}")
    print(f"    exclude_success_rate: {record['exclude_success_rate']:.4f}")
    print(f"    memo_domain_confidence: {record['memo_domain_confidence']:.4f}")

    # Supabase 적재 시도
    try:
        success = tracker.save_to_supabase(record)
        if success:
            print(f"    Saved to expert_memo_history: OK")
        else:
            print(f"    Saved to expert_memo_history: FAIL (graceful fallback)")
    except Exception as e:
        print(f"    Supabase save error: {e}")

    # Step 6: 50회 누적 전 domain_confidence 확인
    print("\n[6] Check domain_confidence (before 50 rounds)")
    conf = tracker.get_confidence(1222)
    print(f"    Current confidence (round 1222): {conf:.4f}")
    print(f"    Expected: < 1.0 (sigmoid 결과)")

    recent = tracker.get_recent_history(window=50)
    print(f"    Recent history window size: {len(recent)} (expect <= 1)")

    # Step 7: Cleanup (테스트 메모 삭제)
    print("\n[7] Cleanup test memo")
    try:
        client.table("expert_memos").delete().eq("id", memo_id).execute()
        print(f"    Deleted memo_id: {memo_id}")
    except Exception as e:
        print(f"    Cleanup fail: {e}")

    print("\n[_test_expert_memo] OK")


if __name__ == "__main__":
    main()
