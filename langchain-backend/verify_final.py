"""최종 검증: 1222·1223회 11 base 모델 전체 적재 확인"""
from db.supabase_client import get_client

sb = get_client()

expected_models = [
    "xgboost", "cnn", "gnn", "markov", "autoencoder",
    "catboost", "tabnet", "tft", "mhn", "bayesian_nn", "nbeats"
]

for target_round in [1222, 1223]:
    print("=" * 80)
    print(f"{target_round}회 weekly_regression_analysis 최종 검증")
    print("=" * 80)

    rows = sb.table('weekly_regression_analysis') \
        .select('step,model_exp') \
        .eq('target_round', target_round) \
        .order('step') \
        .execute().data

    print(f"총 {len(rows)}행 적재됨 (기대: 199)\n")

    all_pass = True
    for m in expected_models:
        steps = [r['step'] for r in rows if r.get('model_exp', {}) and r.get('model_exp', {}).get(m) is not None]
        coverage = len(steps)

        if coverage == 199:
            print(f"  {m:<15}: {coverage}/199 ✓")
        else:
            step_range = f"{min(steps)}-{max(steps)}" if steps else "none"
            print(f"  {m:<15}: {coverage}/199 ✗ (range: {step_range})")
            all_pass = False

    if all_pass:
        print(f"\n✓ {target_round}회 11 base 모델 전체 100% 적재 완료!")
    else:
        print(f"\n✗ {target_round}회 일부 모델 누락")

    # Cell count
    total_cells = sum(
        1 for r in rows
        for m in expected_models
        if r.get('model_exp', {}) and r.get('model_exp', {}).get(m) is not None
    )
    expected_cells = 199 * 11  # 2189
    print(f"\n총 cell 적재: {total_cells}/{expected_cells} ({total_cells / expected_cells * 100:.1f}%)")

print("\n" + "=" * 80)
print("전체 검증 완료")
print("=" * 80)
