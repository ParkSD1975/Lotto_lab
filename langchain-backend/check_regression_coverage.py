"""Check regression analysis DB coverage for 1223."""
from db.supabase_client import get_client
import json

sb = get_client()
rows = sb.table('weekly_regression_analysis').select('step,model_exp').eq('target_round', 1223).order('step').execute().data

print(f'Total rows: {len(rows)}')

# Check each model coverage
models = ['xgboost', 'autoencoder', 'catboost', 'tabnet', 'cnn', 'gnn', 'tft', 'nbeats', 'mhn', 'bayesian_nn', 'markov']

for m in models:
    steps = [r['step'] for r in rows if r.get('model_exp', {}) and r.get('model_exp', {}).get(m) is not None]
    if steps:
        print(f'{m}: {len(steps)} steps (range {min(steps)}-{max(steps)})')
    else:
        print(f'{m}: 0 steps')

# Find gaps
all_steps = sorted(set(r['step'] for r in rows))
print(f'\nStep coverage: {all_steps[0]}-{all_steps[-1]} ({len(all_steps)} steps)')
expected = list(range(2, 201))
missing = [s for s in expected if s not in all_steps]
if missing:
    print(f'Missing steps: {missing[:10]}... (total {len(missing)})')
else:
    print('No missing steps')
