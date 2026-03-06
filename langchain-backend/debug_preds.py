import sys
sys.path.append(r'c:\Users\psdet\Desktop\로또개발\langchain-backend')
from models.ensemble import LottoEnsemble
from db.repository import fetch_all_draws

print("Fetching draws...")
draws = fetch_all_draws()
print(f"Fetched {len(draws)} draws")
draws = [d for d in draws if 'round' in d]
draws = sorted(draws, key=lambda x: x['round'])

print("Init Ensemble...")
ens = LottoEnsemble()
print("Predicting...")
pred = ens.predict(draws[-200:])

con = pred['model_contributions']
for m in ['cnn', 'gnn', 'autoencoder']:
    vals = list(con.get(m, {}).values())
    if vals:
        print(f'{m}: count={len(vals)}, min={min(vals):.5f}, max={max(vals):.5f}')
        if min(vals) == max(vals): print(f'  [Flat! all values {max(vals):.5f}]')
    else: print(f'{m}: empty')
