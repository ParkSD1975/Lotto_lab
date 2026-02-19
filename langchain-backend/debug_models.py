import sys, os, json
sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))

import urllib.request

# API로 과거 회차 데이터 가져오기
try:
    resp = urllib.request.urlopen('http://localhost:8000/api/draws?limit=200', timeout=10)
    draws_data = json.loads(resp.read())
    history = draws_data if isinstance(draws_data, list) else draws_data.get('data', [])
except Exception as e:
    print(f"draws API error: {e}")
    # supabase 직접 호출
    import config
    from supabase import create_client
    client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
    res = client.table("lotto_draws").select("round,numbers").order("round", desc=True).limit(200).execute()
    history = res.data or []

history = sorted(history, key=lambda x: x.get('round', 0), reverse=True)
history = [d for d in history if d.get('round', 9999) < 1212]
print(f"history count: {len(history)}")
if history:
    print(f"latest round: {history[0].get('round')}")

from models.lstm_model import LSTMTrainer
from models.cnn_model import CNNTrainer
from models.transformer_model import TransformerTrainer

for name, trainer in [("lstm", LSTMTrainer()), ("cnn", CNNTrainer()), ("transformer", TransformerTrainer())]:
    try:
        preds = trainer.predict(history)
        sorted_preds = sorted(preds.items(), key=lambda x: x[1], reverse=True)[:10]
        vals = list(preds.values())
        print(f"\n{name} top10: {sorted_preds}")
        print(f"  min={min(vals):.6f}  max={max(vals):.6f}  unique_count={len(set(round(v,6) for v in vals))}")
        print(f"  all same? {len(set(round(v,8) for v in vals)) == 1}")
    except Exception as e:
        import traceback
        print(f"\n{name} ERROR: {e}")
        traceback.print_exc()
