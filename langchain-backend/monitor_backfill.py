"""1223회 backfill 진행 상황 모니터"""
from db.supabase_client import get_client

sb = get_client()
rows = sb.table('weekly_regression_analysis').select('step,model_exp').eq('target_round', 1223).order('step').execute().data

# 8개 모델 (이전 32까지만 적재)
models_8 = ['catboost', 'tabnet', 'cnn', 'gnn', 'tft', 'nbeats', 'mhn', 'bayesian_nn']

for m in models_8:
    steps = [r['step'] for r in rows if r.get('model_exp', {}) and r.get('model_exp', {}).get(m) is not None]
    if steps:
        print(f'{m}: {len(steps)} steps (range {min(steps)}-{max(steps)})')
    else:
        print(f'{m}: 0 steps')

# Overall progress
step_33_plus = [r['step'] for r in rows if r['step'] >= 33]
models_complete_33 = sum(1 for r in rows if r['step'] >= 33 and all(r.get('model_exp', {}).get(m) is not None for m in models_8))
print(f'\nStep 33+ 전체: {len(step_33_plus)} rows')
print(f'Step 33+ 8 모델 완전 적재: {models_complete_33}/{len(step_33_plus)} rows')
