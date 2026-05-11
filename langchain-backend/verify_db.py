"""
DB 저장 확인 스크립트
"""
from __future__ import annotations
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from db.supabase_client import get_client

def verify_db():
    """1223회 step=2 DB 저장 확인"""
    supabase = get_client()
    result = supabase.table('weekly_regression_analysis').select('*').eq('target_round', 1223).eq('step', 2).execute()

    if result.data:
        row = result.data[0]
        model_exp = row.get('model_exp', {})

        print('1223회 step=2 DB 저장 확인:')
        print('-' * 80)

        models = ['xgboost', 'cnn', 'gnn', 'markov', 'autoencoder',
                  'catboost', 'tabnet', 'tft', 'mhn', 'bayesian_nn', 'nbeats']

        missing = []
        for m in models:
            val = model_exp.get(m)
            if val is None:
                print(f'  {m:<15}: None ✗')
                missing.append(m)
            else:
                print(f'  {m:<15}: {val} ✓')

        print('-' * 80)
        if missing:
            print(f'\n누락: {", ".join(missing)}')
        else:
            print('\n모든 모델 적재 확인됨 ✓')
    else:
        print('데이터 없음')

if __name__ == "__main__":
    verify_db()
