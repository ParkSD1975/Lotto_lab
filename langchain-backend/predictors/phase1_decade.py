"""Phase 1-4: 번호대 5D (1-9, 10-19, 20-29, 30-39, 40-45) — 11 base 통합 강화."""
import numpy as np
from db.supabase_client import fetch_all_draws
from validation.baseline_runner import BaselineRunner

DECADE_RANGES=[(1,9),(10,19),(20,29),(30,39),(40,45)]
DECADE_POOL_SIZES=[9,10,10,10,6]

try:
    import xgboost as xgb
    XGB_AVAILABLE = True
except ImportError:
    XGB_AVAILABLE = False

class _Markov7:
    def __init__(self):
        self.T=np.full((7,7),1/7)
    def fit(self,seq):
        if len(seq)<2: return
        T=np.zeros((7,7))
        for i in range(len(seq)-1):
            a,b=int(seq[i]),int(seq[i+1])
            if 0<=a<7 and 0<=b<7: T[a,b]+=1
        T+=1; T/=T.sum(axis=1,keepdims=True); self.T=T
    def predict(self,last):
        return self.T[int(last)] if 0<=last<7 else np.full(7,1/7)

def _freq_dist(hist):
    if len(hist)==0: return np.full(7,1/7)
    c=np.bincount(hist.astype(np.int64),minlength=7)
    return c/max(c.sum(),1)

class DecadePredictor:
    def __init__(self):
        self.markov_heads=[_Markov7() for _ in range(5)]
        self.xgb_models=None
        self._trained=False

    def _extract(self,draws):
        chron=list(reversed(draws))
        counts=[]
        for d in chron:
            nums=d.get("numbers",[])
            c=[0]*5
            for n in nums:
                for i,(lo,hi) in enumerate(DECADE_RANGES):
                    if lo<=n<=hi: c[i]+=1; break
            counts.append(c)
        return np.array(counts, dtype=np.int64)

    def _build_features(self, count_matrix, cat_idx, lookback=30):
        T = count_matrix.shape[0]
        if T <= lookback:
            return None
        features = []
        for t in range(lookback, T):
            window = count_matrix[t-lookback:t, cat_idx]
            f = [
                float(window.mean()),
                float(window.std() + 1e-6),
                float(window[-5:].mean()),
                float(window[-10:].mean()),
                float(window.max()),
                float(window.min()),
                float(np.median(window)),
                float(window[-1]),
                float(window[-2] if len(window) >= 2 else 0),
                float(window[-3] if len(window) >= 3 else 0),
                float(window[-1] - window[-2] if len(window) >= 2 else 0),
                float((window == 0).sum() / len(window)),
                float((window == 1).sum() / len(window)),
                float((window >= 2).sum() / len(window)),
                float((window >= 3).sum() / len(window)),
                float((window >= 4).sum() / len(window)),
                float(window[-3:].mean() if len(window) >= 3 else window.mean()),
                float(window[-7:].mean() if len(window) >= 7 else window.mean()),
                float(window[:10].mean() if len(window) >= 10 else window.mean()),
                float(window[10:20].mean() if len(window) >= 20 else window.mean()),
                float(t % 10),
                float(t % 52),
                float(t / 1000),
                float(window[-5:].std() if len(window) >= 5 else 0),
                float((window - window.mean()).max()),
            ]
            features.append(f)
        return np.array(features, dtype=np.float32)

    def train(self,draws,min_hist=50):
        if len(draws)<min_hist: raise ValueError("insufficient")
        cm=self._extract(draws)
        for i in range(5):
            self.markov_heads[i].fit(cm[:,i])

        if XGB_AVAILABLE:
            self.xgb_models = []
            for cat_idx in range(5):
                X = self._build_features(cm, cat_idx, lookback=30)
                if X is None:
                    self.xgb_models.append(None)
                    continue
                y = cm[30:, cat_idx]
                model = xgb.XGBClassifier(
                    objective="multi:softprob",
                    num_class=7,
                    n_estimators=50,
                    max_depth=3,
                    learning_rate=0.05,
                    min_child_weight=3,
                    subsample=0.8,
                    colsample_bytree=0.8,
                    reg_alpha=0.5,
                    reg_lambda=1.0,
                    random_state=42,
                    eval_metric="mlogloss",
                    use_label_encoder=False,
                )
                try:
                    model.fit(X, y, verbose=False)
                    self.xgb_models.append(model)
                except Exception as e:
                    print(f"[Decade] XGB cat {cat_idx} train fail: {e}")
                    self.xgb_models.append(None)

        self._trained=True
        return {"n_draws":len(draws), "xgb_available": XGB_AVAILABLE}

    def predict(self,draws,target_round):
        if not self._trained: return self._baseline()
        hist=[d for d in draws if int(d.get("round",0))<target_round]
        if len(hist)<10: return self._baseline()
        cm=self._extract(hist)
        per_cat={}
        for i in range(5):
            s=cm[:,i]; last=int(s[-1])
            mp=self.markov_heads[i].predict(last)
            fp=_freq_dist(s)

            xgb_prob = None
            if XGB_AVAILABLE and self.xgb_models and self.xgb_models[i] is not None:
                X_query = self._build_features(cm, i, lookback=30)
                if X_query is not None and len(X_query) > 0:
                    try:
                        raw = self.xgb_models[i].predict_proba(X_query[-1:])[0]
                        if len(raw) < 7:
                            xgb_prob = np.zeros(7)
                            xgb_prob[:len(raw)] = raw
                        else:
                            xgb_prob = raw[:7]
                        xgb_prob = xgb_prob / xgb_prob.sum()
                    except:
                        xgb_prob = None

            if xgb_prob is not None:
                ap = 0.15 * xgb_prob + 0.45 * mp + 0.40 * fp
                contrib = {"xgboost": 0.15, "markov": 0.45, "frequency": 0.40}
            else:
                ap = (mp + fp) / 2
                contrib = {"markov": 0.5, "frequency": 0.5}

            ap/=ap.sum()
            exp=float((ap*np.arange(7)).sum()); M=DECADE_POOL_SIZES[i]
            lab=f"{DECADE_RANGES[i][0]}-{DECADE_RANGES[i][1]}"
            per_cat[lab]={"absolute_dist":ap.tolist(),"expected_count":exp,"current_pool_size":M,"expected_ratio":exp/M,
                          "top_class":int(np.argmax(ap)),"top_class_prob":float(ap.max()),
                          "narrative":f"{lab} pool {M}개 중 {int(np.argmax(ap))}개 가능성 {ap.max()*100:.1f}%",
                          "model_contributions":contrib}
        return {"indicator_name":"decade_distribution","per_category":per_cat}

    def _baseline(self):
        u=np.full(7,1/7)
        return {"indicator_name":"decade_distribution","per_category":{f"{DECADE_RANGES[i][0]}-{DECADE_RANGES[i][1]}":{"absolute_dist":u.tolist(),"expected_count":3,"current_pool_size":DECADE_POOL_SIZES[i],"expected_ratio":3/DECADE_POOL_SIZES[i],"narrative":"not trained","model_contributions":{}} for i in range(5)}}

def validate_walk_forward(n_rounds=50):
    draws=fetch_all_draws()
    if len(draws)<100: return {"error":"insufficient"}
    rounds=sorted([int(d["round"]) for d in draws])[-n_rounds:]
    p=DecadePredictor(); r=BaselineRunner()
    cat_res={}
    for di in range(5):
        pce_tot,fce_tot,n=0,0,0
        for tr in rounds:
            hist=[d for d in draws if int(d.get("round",0))<tr]
            if len(hist)<50: continue
            p.train(hist,50)
            out=p.predict(hist,tr)
            lab=f"{DECADE_RANGES[di][0]}-{DECADE_RANGES[di][1]}"
            pd=np.array(out["per_category"][lab]["absolute_dist"])
            tgt=next((d for d in draws if int(d["round"])==tr),None)
            if not tgt: continue
            lo,hi=DECADE_RANGES[di]
            tc=sum(1 for x in tgt["numbers"] if lo<=x<=hi)
            cm=p._extract(hist); fd=_freq_dist(cm[:,di])
            pce_tot+=r.cross_entropy(pd,tc); fce_tot+=r.cross_entropy(fd,tc); n+=1
        if n>0: cat_res[lab]={"predictor_ce":pce_tot/n,"frequency_ce":fce_tot/n,"n_rounds":n}
    if not cat_res: return {"error":"no_rounds"}
    apc=np.mean([x["predictor_ce"] for x in cat_res.values()])
    afc=np.mean([x["frequency_ce"] for x in cat_res.values()])
    return {"n_categories":5,"avg_predictor_ce":float(apc),"avg_frequency_ce":float(afc),"improvement_pct":(afc-apc)/max(afc,1e-9)*100,"wins_frequency":apc<afc,"per_category":cat_res}

def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--validate",type=int,default=0)
    args=parser.parse_args()
    if args.validate>0:
        print(f"[Decade] validating {args.validate} rounds...")
        res=validate_walk_forward(args.validate)
        if "error" in res: print(f"ERROR: {res['error']}"); return
        print(f"\n카테고리:{res['n_categories']}, predictor_ce:{res['avg_predictor_ce']:.4f}, frequency_ce:{res['avg_frequency_ce']:.4f}, improvement:{res['improvement_pct']:+.2f}%, wins:{res['wins_frequency']}")
        print(f"[게이트]: {'PASS' if res['wins_frequency'] else 'FAIL'}")

if __name__=="__main__": main()
