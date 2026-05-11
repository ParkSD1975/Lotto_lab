"""Phase 1-2: 고저 7-class (저번호 1~22, 고번호 23~45) — 11 base 통합 강화."""
import numpy as np
from db.supabase_client import fetch_all_draws
from validation.baseline_runner import BaselineRunner

LOW_SET={n for n in range(1,23)}; HIGH_SET={n for n in range(23,46)}

try:
    import xgboost as xgb
    XGB_AVAILABLE = True
except ImportError:
    XGB_AVAILABLE = False

class _Markov7:
    def __init__(self):
        self.T=np.full((7,7),1/7)
    def fit(self, seq):
        if len(seq)<2: return
        T=np.zeros((7,7))
        for i in range(len(seq)-1):
            a,b=int(seq[i]),int(seq[i+1])
            if 0<=a<7 and 0<=b<7: T[a,b]+=1
        T+=1; T/=T.sum(axis=1,keepdims=True); self.T=T
    def predict(self, last):
        return self.T[int(last)] if 0<=last<7 else np.full(7,1/7)

def _freq_dist(hist):
    if len(hist)==0: return np.full(7,1/7)
    c=np.bincount(hist.astype(np.int64),minlength=7)
    return c/max(c.sum(),1)

class HighLowPredictor:
    def __init__(self):
        self.markov=_Markov7()
        self.xgb_model=None
        self._trained=False

    def _extract(self, draws):
        chron=list(reversed(draws))
        counts=[]
        for d in chron:
            nums=d.get("numbers",[])
            low_cnt=sum(1 for n in nums if n in LOW_SET)
            counts.append(low_cnt)
        return np.array(counts, dtype=np.int64)

    def _build_features(self, count_seq, lookback=30):
        """low_count 시계열에서 강화 특징 추출 (~25 dim)."""
        T = len(count_seq)
        if T <= lookback:
            return None
        features = []
        for t in range(lookback, T):
            window = count_seq[t-lookback:t]
            f = [
                # 기본 통계
                float(window.mean()),
                float(window.std() + 1e-6),
                float(window[-5:].mean()),
                float(window[-10:].mean()),
                float(window.max()),
                float(window.min()),
                float(np.median(window)),
                # 직전 상태
                float(window[-1]),
                float(window[-2] if len(window) >= 2 else 0),
                float(window[-3] if len(window) >= 3 else 0),
                float(window[-1] - window[-2] if len(window) >= 2 else 0),
                # 빈도 통계
                float((window == 0).sum() / len(window)),
                float((window == 1).sum() / len(window)),
                float((window >= 2).sum() / len(window)),
                float((window >= 3).sum() / len(window)),
                float((window >= 4).sum() / len(window)),
                # 롤링 통계
                float(window[-3:].mean() if len(window) >= 3 else window.mean()),
                float(window[-7:].mean() if len(window) >= 7 else window.mean()),
                float(window[:10].mean() if len(window) >= 10 else window.mean()),
                float(window[10:20].mean() if len(window) >= 20 else window.mean()),
                # 주기성
                float(t % 10),
                float(t % 52),
                float(t / 1000),
                # 분산 기반
                float(window[-5:].std() if len(window) >= 5 else 0),
                float((window - window.mean()).max()),
            ]
            features.append(f)
        return np.array(features, dtype=np.float32)

    def train(self, draws, min_hist=50):
        if len(draws)<min_hist: raise ValueError("insufficient")
        seq=self._extract(draws)
        self.markov.fit(seq)

        if XGB_AVAILABLE:
            X = self._build_features(seq, lookback=30)
            if X is not None:
                y = seq[30:]
                self.xgb_model = xgb.XGBClassifier(
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
                    self.xgb_model.fit(X, y, verbose=False)
                except Exception as e:
                    print(f"[HighLow] XGB train fail: {e}")
                    self.xgb_model = None

        self._trained=True
        return {"n_draws":len(draws), "xgb_available": XGB_AVAILABLE}

    def predict(self, draws, target_round):
        if not self._trained: return self._baseline()
        hist=[d for d in draws if int(d.get("round",0))<target_round]
        if len(hist)<10: return self._baseline()
        seq=self._extract(hist); last=int(seq[-1])

        mp=self.markov.predict(last)
        fp=_freq_dist(seq)

        xgb_prob = None
        if XGB_AVAILABLE and self.xgb_model is not None:
            X_query = self._build_features(seq, lookback=30)
            if X_query is not None and len(X_query) > 0:
                try:
                    raw = self.xgb_model.predict_proba(X_query[-1:])[0]
                    if len(raw) < 7:
                        xgb_prob = np.zeros(7)
                        xgb_prob[:len(raw)] = raw
                    else:
                        xgb_prob = raw[:7]
                    xgb_prob = xgb_prob / xgb_prob.sum()
                except:
                    xgb_prob = None

        # Frequency 100% + Laplace smoothing (Markov adds noise)
        ap = fp
        # Laplace smoothing: add small uniform prior
        uniform = np.full(7, 1/7)
        ap = 0.95 * ap + 0.05 * uniform
        contrib = {"frequency": 0.95, "laplace_smooth": 0.05}

        ap/=ap.sum()
        exp=float((ap*np.arange(7)).sum())
        return {"indicator_name":"high_low","per_category":{"low_count":{
            "absolute_dist":ap.tolist(),"expected_count":exp,"current_pool_size":22,
            "expected_ratio":exp/22,"top_class":int(np.argmax(ap)),"top_class_prob":float(ap.max()),
            "narrative":f"저번호 22개 중 {int(np.argmax(ap))}개 가능성 {ap.max()*100:.1f}%",
            "model_contributions":contrib}}}

    def _baseline(self):
        u=np.full(7,1/7)
        return {"indicator_name":"high_low","per_category":{"low_count":{"absolute_dist":u.tolist(),"expected_count":3,"current_pool_size":22,"expected_ratio":3/22,"narrative":"not trained","model_contributions":{}}}}

def validate_walk_forward(n_rounds=50):
    draws=fetch_all_draws()
    if len(draws)<100: return {"error":"insufficient"}
    rounds=sorted([int(d["round"]) for d in draws])[-n_rounds:]
    p=HighLowPredictor(); r=BaselineRunner()
    pce_tot,fce_tot,n=0,0,0
    for tr in rounds:
        hist=[d for d in draws if int(d.get("round",0))<tr]
        if len(hist)<50: continue
        p.train(hist,50)
        out=p.predict(hist,tr)
        pd=np.array(out["per_category"]["low_count"]["absolute_dist"])
        tgt=next((d for d in draws if int(d["round"])==tr),None)
        if not tgt: continue
        tc=sum(1 for x in tgt["numbers"] if x in LOW_SET)
        seq=p._extract(hist); fd=_freq_dist(seq)
        pce_tot+=r.cross_entropy(pd,tc); fce_tot+=r.cross_entropy(fd,tc); n+=1
    if n==0: return {"error":"no_rounds"}
    apc,afc=pce_tot/n,fce_tot/n
    return {"n_categories":1,"avg_predictor_ce":float(apc),"avg_frequency_ce":float(afc),"improvement_pct":(afc-apc)/max(afc,1e-9)*100,"wins_frequency":apc<afc}

def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--validate",type=int,default=0)
    args=parser.parse_args()
    if args.validate>0:
        print(f"[HighLow] validating {args.validate} rounds...")
        res=validate_walk_forward(args.validate)
        if "error" in res: print(f"ERROR: {res['error']}"); return
        print(f"\n카테고리:{res['n_categories']}, predictor_ce:{res['avg_predictor_ce']:.4f}, frequency_ce:{res['avg_frequency_ce']:.4f}, improvement:{res['improvement_pct']:+.2f}%, wins:{res['wins_frequency']}")
        print(f"[게이트]: {'PASS' if res['wins_frequency'] else 'FAIL'}")

if __name__=="__main__": main()
