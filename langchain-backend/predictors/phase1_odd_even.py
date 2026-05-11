"""Phase 1-3: 홀짝 7-class (홀수 1,3,5...45, 짝수 2,4,6...44) — 11 base 통합 강화."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
from db.supabase_client import fetch_all_draws
from validation.baseline_runner import BaselineRunner

ODD_SET={n for n in range(1,46) if n%2==1}

try:
    import xgboost as xgb
    XGB_AVAILABLE = True
except ImportError:
    XGB_AVAILABLE = False

class _Markov7:
    def __init__(self, alpha=2.0):
        self.T=np.full((7,7),1/7)
        self.alpha=alpha  # Bayesian smoothing
    def fit(self,seq):
        if len(seq)<2: return
        T=np.zeros((7,7))
        for i in range(len(seq)-1):
            a,b=int(seq[i]),int(seq[i+1])
            if 0<=a<7 and 0<=b<7: T[a,b]+=1
        T+=self.alpha  # Bayesian smoothing
        T/=T.sum(axis=1,keepdims=True)
        self.T=T
    def predict(self,last):
        return self.T[int(last)] if 0<=last<7 else np.full(7,1/7)

def _freq_dist(hist):
    if len(hist)==0: return np.full(7,1/7)
    c=np.bincount(hist.astype(np.int64),minlength=7)
    return c/max(c.sum(),1)

def _rwf_dist(hist, decay=0.95):
    """Recency-weighted frequency: 최근 회차에 가중치 부여."""
    if len(hist)==0: return np.full(7,1/7)
    T = len(hist)
    c = np.zeros(7)
    for i, val in enumerate(hist):
        if 0 <= val < 7:
            weight = decay ** (T - 1 - i)
            c[int(val)] += weight
    return c / max(c.sum(), 1e-9)

def _adaptive_dist(hist, freq_dist, rwf_dist, markov_dist):
    """Adaptive ensemble: 최근 변동성 기반 가중치 조정."""
    if len(hist) < 10:
        return (freq_dist + rwf_dist + markov_dist) / 3.0

    # 최근 10회차 변동성 측정
    recent_std = np.std(hist[-10:])

    # 변동성이 높으면 RWF+Markov 가중치 증가, 낮으면 Freq 가중치 증가
    if recent_std > 1.5:
        # 높은 변동성: RWF와 Markov에 더 의존
        return 0.45 * rwf_dist + 0.35 * markov_dist + 0.20 * freq_dist
    elif recent_std < 0.8:
        # 낮은 변동성: Freq에 더 의존
        return 0.20 * rwf_dist + 0.25 * markov_dist + 0.55 * freq_dist
    else:
        # 중간 변동성: 균형
        return 0.35 * rwf_dist + 0.35 * markov_dist + 0.30 * freq_dist

class OddEvenPredictor:
    def __init__(self):
        self.markov=_Markov7()
        self.xgb_model=None
        self._trained=False

    def _extract(self,draws):
        chron=list(reversed(draws))
        counts=[]
        for d in chron:
            nums=d.get("numbers",[])
            odd_cnt=sum(1 for n in nums if n in ODD_SET)
            counts.append(odd_cnt)
        return np.array(counts, dtype=np.int64)

    def _build_features(self, count_seq, lookback=30):
        T = len(count_seq)
        if T <= lookback:
            return None
        features = []
        for t in range(lookback, T):
            window = count_seq[t-lookback:t]
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
                    print(f"[OddEven] XGB train fail: {e}")
                    self.xgb_model = None

        self._trained=True
        return {"n_draws":len(draws), "xgb_available": XGB_AVAILABLE}

    def predict(self,draws,target_round,decay=0.95,weights=None):
        if not self._trained: return self._baseline()
        hist=[d for d in draws if int(d.get("round",0))<target_round]
        if len(hist)<10: return self._baseline()
        seq=self._extract(hist); last=int(seq[-1])

        mp=self.markov.predict(last)
        fp=_freq_dist(seq)
        rwf=_rwf_dist(seq, decay=decay)

        # Default: RWF + Markov + Freq 가중치
        if weights is None:
            weights = (0.35, 0.40, 0.25)

        ap = weights[0] * rwf + weights[1] * mp + weights[2] * fp
        ap/=ap.sum()

        contrib = {"rwf": weights[0], "markov": weights[1], "frequency": weights[2]}

        exp=float((ap*np.arange(7)).sum())
        return {"indicator_name":"odd_even","per_category":{"odd_count":{
            "absolute_dist":ap.tolist(),"expected_count":exp,"current_pool_size":23,
            "expected_ratio":exp/23,"top_class":int(np.argmax(ap)),"top_class_prob":float(ap.max()),
            "narrative":f"홀수 23개 중 {int(np.argmax(ap))}개 가능성 {ap.max()*100:.1f}%",
            "model_contributions":contrib}}}

    def _baseline(self):
        u=np.full(7,1/7)
        return {"indicator_name":"odd_even","per_category":{"odd_count":{"absolute_dist":u.tolist(),"expected_count":3,"current_pool_size":23,"expected_ratio":3/23,"narrative":"not trained","model_contributions":{}}}}

def validate_walk_forward(n_rounds=50, use_grid_search=False):
    draws=fetch_all_draws()
    if len(draws)<100: return {"error":"insufficient"}
    all_rounds = sorted([int(d["round"]) for d in draws])

    # Grid search: RWF, Markov, Freq 가중치 (세밀한 그리드)
    WEIGHT_GRID = []
    for rwf_w in [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50]:
        for mk_w in [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50]:
            fr_w = 1.0 - rwf_w - mk_w
            if 0.15 <= fr_w <= 0.50:
                WEIGHT_GRID.append((rwf_w, mk_w, fr_w))

    DECAY_GRID = [0.85, 0.88, 0.90, 0.92, 0.95, 0.97, 0.98, 0.99]

    if use_grid_search:
        # validation: 회차 1051~1100 (50회)
        # test: 회차 1101~1120 (20회)
        val_rounds = list(range(1051, 1101))
        test_rounds = list(range(1101, 1121))

        best_w = (0.35, 0.40, 0.25)
        best_decay = 0.95
        best_ce = 1e9

        p = OddEvenPredictor()
        train_cutoff = 1050
        train_hist = [d for d in draws if int(d.get("round", 0)) <= train_cutoff]
        if len(train_hist) < 50:
            return {"error": "insufficient training data"}
        p.train(train_hist, 50)

        for decay in DECAY_GRID:
            for w_rwf, w_mk, w_fr in WEIGHT_GRID:
                ce_sum = 0
                n = 0
                for tr in val_rounds:
                    hist = [d for d in draws if int(d.get("round", 0)) < tr]
                    seq = p._extract(hist)
                    last = int(seq[-1])

                    mp = p.markov.predict(last)
                    fp = _freq_dist(seq)
                    rwf = _rwf_dist(seq, decay=decay)

                    ap = w_rwf * rwf + w_mk * mp + w_fr * fp
                    ap /= ap.sum()

                    tgt = next((d for d in draws if int(d["round"]) == tr), None)
                    if tgt:
                        tc = sum(1 for x in tgt["numbers"] if x in ODD_SET)
                        ce_sum += -np.log(max(ap[tc], 1e-9))
                        n += 1

                if n > 0:
                    avg = ce_sum / n
                    if avg < best_ce:
                        best_ce = avg
                        best_w = (w_rwf, w_mk, w_fr)
                        best_decay = decay

        print(f"[OddEven] Best weight: {best_w}, decay={best_decay}, val_ce={best_ce:.4f}")

        # test
        r = BaselineRunner()
        pce_tot, fce_tot, n = 0, 0, 0
        for tr in test_rounds:
            hist = [d for d in draws if int(d.get("round", 0)) < tr]
            seq = p._extract(hist)
            last = int(seq[-1])

            mp = p.markov.predict(last)
            fp = _freq_dist(seq)
            rwf = _rwf_dist(seq, decay=best_decay)

            ap = best_w[0] * rwf + best_w[1] * mp + best_w[2] * fp
            ap /= ap.sum()

            tgt = next((d for d in draws if int(d["round"]) == tr), None)
            if tgt:
                tc = sum(1 for x in tgt["numbers"] if x in ODD_SET)
                pce_tot += r.cross_entropy(ap, tc)
                fce_tot += r.cross_entropy(fp, tc)
                n += 1

        apc, afc = pce_tot/n, fce_tot/n
        return {
            "n_categories": 1,
            "avg_predictor_ce": float(apc),
            "avg_frequency_ce": float(afc),
            "improvement_pct": (afc-apc)/max(afc,1e-9)*100,
            "wins_frequency": apc < afc,
            "best_weight": best_w,
            "best_decay": best_decay
        }

    # 기존 방식 (grid search 없음)
    rounds = all_rounds[-n_rounds:]
    p=OddEvenPredictor(); r=BaselineRunner()
    pce_tot,fce_tot,n=0,0,0
    for tr in rounds:
        hist=[d for d in draws if int(d.get("round",0))<tr]
        if len(hist)<50: continue
        p.train(hist,50)
        out=p.predict(hist,tr)
        pd=np.array(out["per_category"]["odd_count"]["absolute_dist"])
        tgt=next((d for d in draws if int(d["round"])==tr),None)
        if not tgt: continue
        tc=sum(1 for x in tgt["numbers"] if x in ODD_SET)
        seq=p._extract(hist); fd=_freq_dist(seq)
        pce_tot+=r.cross_entropy(pd,tc); fce_tot+=r.cross_entropy(fd,tc); n+=1
    if n==0: return {"error":"no_rounds"}
    apc,afc=pce_tot/n,fce_tot/n
    return {"n_categories":1,"avg_predictor_ce":float(apc),"avg_frequency_ce":float(afc),"improvement_pct":(afc-apc)/max(afc,1e-9)*100,"wins_frequency":apc<afc}

def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--validate",type=int,default=0)
    parser.add_argument("--grid-search",action="store_true",help="Enable grid search for weights")
    args=parser.parse_args()
    if args.validate>0:
        print(f"[OddEven] validating {args.validate} rounds (grid_search={args.grid_search})...")
        res=validate_walk_forward(args.validate, use_grid_search=args.grid_search)
        if "error" in res: print(f"ERROR: {res['error']}"); return
        print(f"\n카테고리:{res['n_categories']}, predictor_ce:{res['avg_predictor_ce']:.4f}, frequency_ce:{res['avg_frequency_ce']:.4f}, improvement:{res['improvement_pct']:+.2f}%, wins:{res['wins_frequency']}")
        if "best_weight" in res:
            print(f"Best weight (RWF,MK,FR,XGB): {res['best_weight']}, decay={res['best_decay']}")
        print(f"[게이트]: {'PASS' if res['wins_frequency'] else 'FAIL'}")

if __name__=="__main__": main()
