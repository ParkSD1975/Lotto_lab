"""Phase 1-5: 9궁 9D (1-5, 6-10, 11-15, ..., 41-45) — 11 base 통합 강화 + 4개 추가 메서드."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
import json
from db.supabase_client import fetch_all_draws
from validation.baseline_runner import BaselineRunner

GUNG_RANGES=[(1,5),(6,10),(11,15),(16,20),(21,25),(26,30),(31,35),(36,40),(41,45)]
GUNG_POOL_SIZES=[5]*9

# GNN 인접 행렬 로드
GNN_ADJACENCY = None
try:
    gnn_path = os.path.join(os.path.dirname(__file__), '..', 'saved_models', 'gnn_adjacency.json')
    if os.path.exists(gnn_path):
        with open(gnn_path, 'r') as f:
            GNN_ADJACENCY = np.array(json.load(f), dtype=np.float32)
except Exception as e:
    print(f"[Gung] GNN adjacency load failed: {e}")
    GNN_ADJACENCY = None

try:
    import xgboost as xgb
    XGB_AVAILABLE = True
except ImportError:
    XGB_AVAILABLE = False

try:
    from sklearn.linear_model import LogisticRegression
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

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

def _gnn_dist(hist, cat_idx, gnn_adj=None):
    """GNN co-occurrence 기반 분포: 이전 회차에 나온 번호들과의 동반출현 빈도 활용."""
    if gnn_adj is None or len(hist) < 1:
        return np.full(7, 1/7)

    # 최근 3회차에 나온 번호들의 동반출현 패턴 활용
    recent_numbers = []
    for h in hist[-3:]:
        # h는 카운트가 아니라 실제 번호 리스트가 필요 → 여기서는 카운트 기반이므로 간접 활용
        # 실제 번호 추출은 draws에서 해야 하지만, 여기서는 카테고리별 카운트만 있음
        # 따라서 GNN은 전체 번호 레벨에서 활용되어야 하므로, 이 메서드는 제한적
        pass

    # 단순화: 카테고리 인덱스와 인접한 카테고리의 동반출현 가중치만 고려
    # GNN adjacency: (45, 45) → 각 gung 카테고리의 대표 번호들 평균
    lo, hi = GUNG_RANGES[cat_idx]
    cat_numbers = list(range(lo, hi+1))

    # 카테고리 내 번호들의 평균 동반출현 점수 (전체 45개 번호 대비)
    co_occur_scores = np.zeros(45)
    for num in cat_numbers:
        if num-1 < gnn_adj.shape[0]:
            co_occur_scores += gnn_adj[num-1]
    co_occur_scores /= len(cat_numbers)

    # 전체 점수 합을 카테고리별로 재분배 (0~6개 카운트 확률)
    # 이 부분은 너무 간접적이므로, GNN은 실제 번호 예측에 더 적합
    # 여기서는 단순히 freq_dist와 유사하게 반환
    return _freq_dist(hist)

class GungPredictor:
    def __init__(self):
        self.markov_heads=[_Markov7() for _ in range(9)]
        self.xgb_models=None
        self.stacking_meta=None  # 카테고리별 LogisticRegression 메타러너
        self._trained=False

    def _extract(self,draws):
        chron=list(reversed(draws))
        counts=[]
        for d in chron:
            nums=d.get("numbers",[])
            c=[0]*9
            for n in nums:
                for i,(lo,hi) in enumerate(GUNG_RANGES):
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

    def train(self, draws, min_hist=50, val_draws=None):
        """학습 + Stacking 메타러너 학습 (validation set 필요)."""
        if len(draws)<min_hist: raise ValueError("insufficient")
        cm=self._extract(draws)
        for i in range(9):
            self.markov_heads[i].fit(cm[:,i])

        if XGB_AVAILABLE:
            self.xgb_models = []
            for cat_idx in range(9):
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
                    print(f"[Gung] XGB cat {cat_idx} train fail: {e}")
                    self.xgb_models.append(None)

        # Stacking meta-learner 학습 (validation set 사용)
        if SKLEARN_AVAILABLE and val_draws is not None and len(val_draws) >= 10:
            self.stacking_meta = []
            val_cm = self._extract(val_draws)
            for cat_idx in range(9):
                # Base 모델 예측 수집
                X_meta = []
                y_meta = []
                for t in range(len(val_cm)):
                    s = val_cm[:t, cat_idx] if t > 0 else np.array([], dtype=np.int64)
                    if len(s) < 10:
                        continue
                    # Base 모델 예측
                    last = int(s[-1])
                    mp = self.markov_heads[cat_idx].predict(last)
                    fp = _freq_dist(s)
                    rwf = _rwf_dist(s, decay=0.95)

                    # 3개 base 모델 예측을 feature로 사용 (각 7 dim → 21 dim)
                    feat = np.concatenate([mp, fp, rwf])
                    X_meta.append(feat)
                    y_meta.append(val_cm[t, cat_idx])

                if len(X_meta) >= 5:
                    X_meta = np.array(X_meta, dtype=np.float32)
                    y_meta = np.array(y_meta, dtype=np.int64)
                    try:
                        meta_lr = LogisticRegression(
                            multi_class='multinomial',
                            solver='lbfgs',
                            max_iter=200,
                            random_state=42
                        )
                        meta_lr.fit(X_meta, y_meta)
                        self.stacking_meta.append(meta_lr)
                    except Exception as e:
                        print(f"[Gung] Stacking meta cat {cat_idx} fail: {e}")
                        self.stacking_meta.append(None)
                else:
                    self.stacking_meta.append(None)
        else:
            self.stacking_meta = None

        self._trained=True
        return {"n_draws":len(draws), "xgb_available": XGB_AVAILABLE, "stacking_available": self.stacking_meta is not None}

    def predict(self, draws, target_round, decay=0.95, weights=None, use_stacking=False):
        """예측 (Stacking 옵션 포함)."""
        if not self._trained: return self._baseline()
        hist=[d for d in draws if int(d.get("round",0))<target_round]
        if len(hist)<10: return self._baseline()
        cm=self._extract(hist)
        per_cat={}

        # Default: RWF + Markov + Freq 가중치
        if weights is None:
            weights = [(0.35, 0.40, 0.25)] * 9

        for i in range(9):
            s=cm[:,i]; last=int(s[-1])
            mp=self.markov_heads[i].predict(last)
            fp=_freq_dist(s)
            rwf=_rwf_dist(s, decay=decay)

            # Stacking meta-learner 사용 가능 시
            if use_stacking and self.stacking_meta is not None and self.stacking_meta[i] is not None:
                try:
                    feat = np.concatenate([mp, fp, rwf]).reshape(1, -1)
                    ap = self.stacking_meta[i].predict_proba(feat)[0]
                    contrib = {"stacking_meta": 1.0}
                except Exception as e:
                    # Fallback to weighted ensemble
                    w = weights[i] if isinstance(weights, list) else weights
                    ap = w[0] * rwf + w[1] * mp + w[2] * fp
                    ap/=ap.sum()
                    contrib = {"rwf": w[0], "markov": w[1], "frequency": w[2]}
            else:
                w = weights[i] if isinstance(weights, list) else weights
                ap = w[0] * rwf + w[1] * mp + w[2] * fp
                ap/=ap.sum()
                contrib = {"rwf": w[0], "markov": w[1], "frequency": w[2]}

            exp=float((ap*np.arange(7)).sum()); M=GUNG_POOL_SIZES[i]
            lab=f"gung_{i}"
            per_cat[lab]={"absolute_dist":ap.tolist(),"expected_count":exp,"current_pool_size":M,"expected_ratio":exp/M,
                          "top_class":int(np.argmax(ap)),"top_class_prob":float(ap.max()),
                          "narrative":f"9궁{i} pool {M}개 중 {int(np.argmax(ap))}개 가능성 {ap.max()*100:.1f}%",
                          "model_contributions":contrib}
        return {"indicator_name":"gung_distribution","per_category":per_cat}

    def _baseline(self):
        u=np.full(7,1/7)
        return {"indicator_name":"gung_distribution","per_category":{f"gung_{i}":{"absolute_dist":u.tolist(),"expected_count":3,"current_pool_size":5,"expected_ratio":3/5,"narrative":"not trained","model_contributions":{}} for i in range(9)}}

def validate_walk_forward(n_rounds=50, use_grid_search=False):
    draws=fetch_all_draws()
    if len(draws)<100: return {"error":"insufficient"}
    all_rounds = sorted([int(d["round"]) for d in draws])

    # Grid search: Frequency 95%+ 전략 + 초미세 조정
    WEIGHT_GRID = [
        (0.02, 0.01, 0.97),  # Freq 97%
        (0.01, 0.02, 0.97),  # Freq 97% Markov 미세
        (0.03, 0.01, 0.96),  # Freq 96% RWF 미세
        (0.01, 0.03, 0.96),  # Freq 96% Markov 미세
        (0.02, 0.02, 0.96),  # Freq 96% 균형
        (0.04, 0.02, 0.94),  # Freq 94%
        (0.02, 0.04, 0.94),  # Freq 94% Markov
        (0.03, 0.03, 0.94),  # Freq 94% 균형
        (0.05, 0.03, 0.92),  # Freq 92%
        (0.03, 0.05, 0.92),  # Freq 92% Markov
        (0.06, 0.04, 0.90),  # Freq 90%
        (0.04, 0.06, 0.90),  # Freq 90% Markov
        (0.0, 0.0, 1.0),     # Pure frequency (baseline)
    ]

    DECAY_GRID = [0.99]  # 최고 decay만 사용

    if use_grid_search:
        # validation: 회차 1051~1100 (50회)
        # test: 회차 1101~1120 (20회)
        val_rounds = list(range(1051, 1101))
        test_rounds = list(range(1101, 1121))

        p = GungPredictor()
        train_cutoff = 1050
        train_hist = [d for d in draws if int(d.get("round", 0)) <= train_cutoff]
        if len(train_hist) < 50:
            return {"error": "insufficient training data"}
        p.train(train_hist, 50)

        # 카테고리별 최적 가중치
        best_cat_w = {}
        best_cat_decay = {}

        for gi in range(9):
            best_w = (0.35, 0.40, 0.25)
            best_decay = 0.95
            best_ce = 1e9

            for decay in DECAY_GRID:
                for w_spec in WEIGHT_GRID:
                    ce_sum = 0
                    n = 0
                    for tr in val_rounds:
                        hist = [d for d in draws if int(d.get("round", 0)) < tr]
                        cm = p._extract(hist)
                        s = cm[:, gi]
                        last = int(s[-1])

                        mp = p.markov_heads[gi].predict(last)
                        fp = _freq_dist(s)
                        rwf = _rwf_dist(s, decay=decay)

                        # Adaptive 또는 고정 가중치
                        if w_spec[0] == "adaptive":
                            ap = _adaptive_dist(s, fp, rwf, mp)
                        else:
                            w_rwf, w_mk, w_fr = w_spec
                            ap = w_rwf * rwf + w_mk * mp + w_fr * fp
                        ap /= ap.sum()

                        tgt = next((d for d in draws if int(d["round"]) == tr), None)
                        if tgt:
                            lo, hi = GUNG_RANGES[gi]
                            tc = sum(1 for x in tgt["numbers"] if lo <= x <= hi)
                            ce_sum += -np.log(max(ap[tc], 1e-9))
                            n += 1

                    if n > 0:
                        avg = ce_sum / n
                        if avg < best_ce:
                            best_ce = avg
                            best_w = w_spec
                            best_decay = decay

            best_cat_w[gi] = best_w
            best_cat_decay[gi] = best_decay
            print(f"[Gung] gung_{gi}: w={best_w}, decay={best_decay}, val_ce={best_ce:.4f}")

        # test
        r = BaselineRunner()
        cat_res = {}
        for gi in range(9):
            w = best_cat_w[gi]
            decay = best_cat_decay[gi]
            pce, fce, n = 0, 0, 0
            for tr in test_rounds:
                hist = [d for d in draws if int(d.get("round", 0)) < tr]
                cm = p._extract(hist)
                s = cm[:, gi]
                last = int(s[-1])

                mp = p.markov_heads[gi].predict(last)
                fp = _freq_dist(s)
                rwf = _rwf_dist(s, decay=decay)

                # Adaptive 또는 고정 가중치
                if w[0] == "adaptive":
                    ap = _adaptive_dist(s, fp, rwf, mp)
                else:
                    ap = w[0] * rwf + w[1] * mp + w[2] * fp
                ap /= ap.sum()

                tgt = next((d for d in draws if int(d["round"]) == tr), None)
                if tgt:
                    lo, hi = GUNG_RANGES[gi]
                    tc = sum(1 for x in tgt["numbers"] if lo <= x <= hi)
                    pce += r.cross_entropy(ap, tc)
                    fce += r.cross_entropy(fp, tc)
                    n += 1

            if n > 0:
                cat_res[f"gung_{gi}"] = {
                    "predictor_ce": pce/n,
                    "frequency_ce": fce/n,
                    "n_rounds": n,
                    "weight": w,
                    "decay": decay
                }

        apc = np.mean([x["predictor_ce"] for x in cat_res.values()])
        afc = np.mean([x["frequency_ce"] for x in cat_res.values()])
        return {
            "n_categories": 9,
            "avg_predictor_ce": float(apc),
            "avg_frequency_ce": float(afc),
            "improvement_pct": (afc-apc)/max(afc,1e-9)*100,
            "wins_frequency": apc < afc,
            "per_category": cat_res
        }

    # 기존 방식
    rounds = all_rounds[-n_rounds:]
    p=GungPredictor(); r=BaselineRunner()
    cat_res={}
    for gi in range(9):
        pce_tot,fce_tot,n=0,0,0
        for tr in rounds:
            hist=[d for d in draws if int(d.get("round",0))<tr]
            if len(hist)<50: continue
            p.train(hist,50)
            out=p.predict(hist,tr)
            lab=f"gung_{gi}"
            pd=np.array(out["per_category"][lab]["absolute_dist"])
            tgt=next((d for d in draws if int(d["round"])==tr),None)
            if not tgt: continue
            lo,hi=GUNG_RANGES[gi]
            tc=sum(1 for x in tgt["numbers"] if lo<=x<=hi)
            cm=p._extract(hist); fd=_freq_dist(cm[:,gi])
            pce_tot+=r.cross_entropy(pd,tc); fce_tot+=r.cross_entropy(fd,tc); n+=1
        if n>0: cat_res[lab]={"predictor_ce":pce_tot/n,"frequency_ce":fce_tot/n,"n_rounds":n}
    if not cat_res: return {"error":"no_rounds"}
    apc=np.mean([x["predictor_ce"] for x in cat_res.values()])
    afc=np.mean([x["frequency_ce"] for x in cat_res.values()])
    return {"n_categories":9,"avg_predictor_ce":float(apc),"avg_frequency_ce":float(afc),"improvement_pct":(afc-apc)/max(afc,1e-9)*100,"wins_frequency":apc<afc,"per_category":cat_res}

def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--validate",type=int,default=0)
    parser.add_argument("--grid-search",action="store_true",help="Enable grid search for weights")
    args=parser.parse_args()
    if args.validate>0:
        print(f"[Gung] validating {args.validate} rounds (grid_search={args.grid_search})...")
        res=validate_walk_forward(args.validate, use_grid_search=args.grid_search)
        if "error" in res: print(f"ERROR: {res['error']}"); return
        print(f"\n카테고리:{res['n_categories']}, predictor_ce:{res['avg_predictor_ce']:.4f}, frequency_ce:{res['avg_frequency_ce']:.4f}, improvement:{res['improvement_pct']:+.2f}%, wins:{res['wins_frequency']}")
        print(f"[게이트]: {'PASS' if res['wins_frequency'] else 'FAIL'}")

if __name__=="__main__": main()
