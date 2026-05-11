"""Phase 1-6: 이월수 2개 카테고리 — 11 base 통합 강화."""
import numpy as np
from db.supabase_client import fetch_all_draws
from validation.baseline_runner import BaselineRunner

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

class CarryoverPredictor:
    """이월수 예측기.

    카테고리 2개:
    - carryover_main: 직전 회차 본번호 6개 중 현 회차에 재출현하는 수 (0~6)
    - carryover_bonus: 직전 보너스가 현 회차 본번호에 출현 (0 or 1, 7-class로 확장)
    """
    def __init__(self):
        self.markov_heads=[_Markov7() for _ in range(2)]
        self.xgb_models=None
        self._trained=False

    def _extract(self,draws):
        """카테고리별 카운트 시계열 추출.

        returns: (T, 2) 배열
          [:,0] = 이월수 메인 (0~6)
          [:,1] = 이월수 보너스 (0~1)
        """
        chron=list(reversed(draws))
        counts=[]
        for i in range(len(chron)):
            if i==0:
                counts.append([0,0])  # 첫 회차는 이월 없음
                continue
            prev_main=set(chron[i-1].get("numbers",[]))
            prev_bonus=chron[i-1].get("bonus_number")
            curr_main=chron[i].get("numbers",[])

            co_main=sum(1 for n in curr_main if n in prev_main)
            co_bonus=1 if (prev_bonus and prev_bonus in curr_main) else 0
            counts.append([co_main, co_bonus])
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
        for i in range(2):
            self.markov_heads[i].fit(cm[:,i])

        if XGB_AVAILABLE:
            self.xgb_models = []
            for cat_idx in range(2):
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
                    print(f"[Carryover] XGB cat {cat_idx} train fail: {e}")
                    self.xgb_models.append(None)

        self._trained=True
        return {"n_draws":len(draws), "xgb_available": XGB_AVAILABLE}

    def predict(self,draws,target_round):
        if not self._trained: return self._baseline()
        hist=[d for d in draws if int(d.get("round",0))<target_round]
        if len(hist)<10: return self._baseline()
        cm=self._extract(hist)
        per_cat={}
        labels=["carryover_main","carryover_bonus"]
        pool_sizes=[6,1]

        for i in range(2):
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
            exp=float((ap*np.arange(7)).sum()); M=pool_sizes[i]
            lab=labels[i]
            per_cat[lab]={"absolute_dist":ap.tolist(),"expected_count":exp,"current_pool_size":M,"expected_ratio":exp/M,
                          "top_class":int(np.argmax(ap)),"top_class_prob":float(ap.max()),
                          "narrative":f"{lab} pool {M}개 중 {int(np.argmax(ap))}개 가능성 {ap.max()*100:.1f}%",
                          "model_contributions":contrib}
        return {"indicator_name":"carryover_distribution","per_category":per_cat}

    def _baseline(self):
        u=np.full(7,1/7)
        labels=["carryover_main","carryover_bonus"]
        pool_sizes=[6,1]
        return {"indicator_name":"carryover_distribution","per_category":{labels[i]:{"absolute_dist":u.tolist(),"expected_count":3,"current_pool_size":pool_sizes[i],"expected_ratio":3/pool_sizes[i],"top_class":0,"top_class_prob":1/7,"narrative":"not trained","model_contributions":{}} for i in range(2)}}

def validate_walk_forward(n_rounds=50):
    draws=fetch_all_draws()
    if len(draws)<100: return {"error":"insufficient"}
    rounds=sorted([int(d["round"]) for d in draws])[-n_rounds:]
    p=CarryoverPredictor(); r=BaselineRunner()
    cat_res={}
    labels=["carryover_main","carryover_bonus"]

    for ci,lab in enumerate(labels):
        pce_tot,fce_tot,n=0,0,0
        for tr in rounds:
            hist=[d for d in draws if int(d.get("round",0))<tr]
            if len(hist)<50: continue
            p.train(hist,50)
            out=p.predict(hist,tr)
            pd=np.array(out["per_category"][lab]["absolute_dist"])
            tgt=next((d for d in draws if int(d["round"])==tr),None)
            if not tgt: continue
            # 실제 값 계산
            cm_all=p._extract([d for d in draws if int(d.get("round",0))<=tr])
            idx=[int(d["round"]) for d in draws].index(tr)
            tc=cm_all[idx,ci]
            cm_hist=p._extract(hist); fd=_freq_dist(cm_hist[:,ci])
            pce_tot+=r.cross_entropy(pd,tc); fce_tot+=r.cross_entropy(fd,tc); n+=1
        if n>0: cat_res[lab]={"predictor_ce":pce_tot/n,"frequency_ce":fce_tot/n,"n_rounds":n}
    if not cat_res: return {"error":"no_rounds"}
    apc=np.mean([x["predictor_ce"] for x in cat_res.values()])
    afc=np.mean([x["frequency_ce"] for x in cat_res.values()])
    return {"n_categories":2,"avg_predictor_ce":float(apc),"avg_frequency_ce":float(afc),"improvement_pct":(afc-apc)/max(afc,1e-9)*100,"wins_frequency":apc<afc,"per_category":cat_res}

def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--smoke",action="store_true")
    parser.add_argument("--validate",type=int,default=0)
    args=parser.parse_args()

    if args.smoke:
        print("[Carryover] smoke test...")
        draws=fetch_all_draws()
        if len(draws)<50: print("insufficient draws"); return
        p=CarryoverPredictor()
        p.train(draws[:100],50)
        out=p.predict(draws[:100],100)
        print(f"  categories: {list(out['per_category'].keys())}")
        for k,v in out["per_category"].items():
            print(f"  {k}: top={v['top_class']} P={v['top_class_prob']:.3f}")
        print("[Carryover] smoke PASS")

    if args.validate>0:
        print(f"[Carryover] validating {args.validate} rounds...")
        res=validate_walk_forward(args.validate)
        if "error" in res: print(f"ERROR: {res['error']}"); return
        print(f"\n카테고리:{res['n_categories']}, predictor_ce:{res['avg_predictor_ce']:.4f}, frequency_ce:{res['avg_frequency_ce']:.4f}, improvement:{res['improvement_pct']:+.2f}%, wins:{res['wins_frequency']}")
        print(f"[게이트]: {'PASS' if res['wins_frequency'] else 'FAIL'} (참고용, 강제 안 함)")

if __name__=="__main__": main()
