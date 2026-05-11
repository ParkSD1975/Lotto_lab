"""Phase 1-1: 끝수 0~9 카테고리별 7-class 카운트 분류 (11 base 통합 강화)."""
import numpy as np
from db.supabase_client import fetch_all_draws
from validation.baseline_runner import BaselineRunner

DIGIT_POOL_SIZES = [4,5,5,5,5,5,5,5,5,4]  # 끝수별 번호 개수

try:
    import xgboost as xgb
    XGB_AVAILABLE = True
except ImportError:
    XGB_AVAILABLE = False

try:
    from models.catboost_model import LottoCatBoost, CATBOOST_AVAILABLE
except ImportError:
    CATBOOST_AVAILABLE = False
    LottoCatBoost = None

class _Markov7:
    def __init__(self):
        self.T = np.full((7,7), 1/7)
    def fit(self, seq):
        if len(seq) < 2: return
        T = np.zeros((7,7))
        for i in range(len(seq)-1):
            a, b = int(seq[i]), int(seq[i+1])
            if 0<=a<7 and 0<=b<7: T[a,b]+=1
        T+=1; T/=T.sum(axis=1, keepdims=True); self.T=T
    def predict(self, last):
        return self.T[int(last)] if 0<=last<7 else np.full(7,1/7)

def _freq_dist(hist):
    if len(hist)==0: return np.full(7,1/7)
    c=np.bincount(hist.astype(np.int64), minlength=7)
    return c/max(c.sum(),1)

class EndingsDistributionPredictor:
    def __init__(self):
        self.markov_heads=[_Markov7() for _ in range(10)]
        self.xgb_models=None  # 10개 카테고리별 XGBoost 모델 리스트
        self.catboost_models=None  # 10개 카테고리별 CatBoost 모델 리스트
        self._trained=False

    def _extract(self, draws):
        """회차별 끝수 카운트 추출 (역순)."""
        chron=list(reversed(draws))
        counts=[]
        for d in chron:
            nums=d.get("numbers",[])
            c=[sum(1 for n in nums if n%10==i) for i in range(10)]
            counts.append(c)
        return np.array(counts, dtype=np.int64)

    def _build_features(self, count_matrix, cat_idx, lookback=30):
        """카테고리 cat_idx의 과거 통계 특징 벡터 생성 (강화 버전).

        count_matrix: (T, 10) 끝수 카운트 행렬
        cat_idx: 0~9 카테고리 인덱스
        lookback: 직전 N회차 사용

        Returns: (T-lookback, feature_dim) 특징 행렬 (~25 dim)
        """
        T = count_matrix.shape[0]
        if T <= lookback:
            return None

        features = []
        for t in range(lookback, T):
            window = count_matrix[t-lookback:t, cat_idx]  # 직전 N회차
            # 강화 통계 특징 (~25 dim)
            f = [
                # 기본 통계 (7)
                float(window.mean()),
                float(window.std() + 1e-6),  # 0 방지
                float(window[-5:].mean()),
                float(window[-10:].mean()),
                float(window.max()),
                float(window.min()),
                float(np.median(window)),

                # 직전 상태 (4)
                float(window[-1]),             # lag-1
                float(window[-2] if len(window) >= 2 else 0),  # lag-2
                float(window[-3] if len(window) >= 3 else 0),  # lag-3
                float(window[-1] - window[-2] if len(window) >= 2 else 0),  # 변화량

                # 빈도 통계 (5)
                float((window == 0).sum() / len(window)),  # 0회 비율
                float((window == 1).sum() / len(window)),
                float((window >= 2).sum() / len(window)),
                float((window >= 3).sum() / len(window)),
                float((window >= 4).sum() / len(window)),

                # 롤링 통계 (4)
                float(window[-3:].mean() if len(window) >= 3 else window.mean()),
                float(window[-7:].mean() if len(window) >= 7 else window.mean()),
                float(window[:10].mean() if len(window) >= 10 else window.mean()),  # 초기
                float(window[10:20].mean() if len(window) >= 20 else window.mean()),  # 중기

                # 주기성 (3)
                float(t % 10),                 # 10회차 주기
                float(t % 52),                 # 연중 주기
                float(t / 1000),               # 절대 회차 (정규화)

                # 분산 기반 (2)
                float(window[-5:].std() if len(window) >= 5 else 0),
                float((window - window.mean()).max()),  # 최대 편차
            ]
            features.append(f)
        return np.array(features, dtype=np.float32)

    def train(self, draws, min_hist=50):
        """11 base 통합 학습: Markov + XGBoost."""
        if len(draws)<min_hist: raise ValueError("insufficient")
        cm=self._extract(draws)

        # 1) Markov 학습 (기존)
        for i in range(10):
            self.markov_heads[i].fit(cm[:,i])

        # 2) XGBoost 학습 (추가)
        if XGB_AVAILABLE:
            self.xgb_models = []
            for cat_idx in range(10):
                X = self._build_features(cm, cat_idx, lookback=30)
                if X is None:
                    self.xgb_models.append(None)
                    continue
                y = cm[30:, cat_idx]  # target: lookback 이후 카운트

                # XGBoost 7-class classifier
                # 보수적 하이퍼파라미터 (overfitting 방지)
                model = xgb.XGBClassifier(
                    objective="multi:softprob",
                    num_class=7,
                    n_estimators=50,          # 100 -> 50 축소
                    max_depth=3,              # 4 -> 3 축소
                    learning_rate=0.05,       # 0.1 -> 0.05 축소
                    min_child_weight=3,       # 정규화 증가
                    subsample=0.8,            # 데이터 샘플링
                    colsample_bytree=0.8,     # 특징 샘플링
                    reg_alpha=0.5,            # L1 정규화
                    reg_lambda=1.0,           # L2 정규화
                    random_state=42,
                    eval_metric="mlogloss",
                    use_label_encoder=False,
                )
                try:
                    model.fit(X, y, verbose=False)
                    self.xgb_models.append(model)
                except Exception as e:
                    print(f"[Endings] XGB cat {cat_idx} train fail: {e}")
                    self.xgb_models.append(None)

        # 3) CatBoost 학습 (XGB 병렬 base)
        if CATBOOST_AVAILABLE:
            self.catboost_models = []
            for cat_idx in range(10):
                X = self._build_features(cm, cat_idx, lookback=30)
                if X is None:
                    self.catboost_models.append(None)
                    continue
                y = cm[30:, cat_idx]

                try:
                    model = LottoCatBoost(
                        task_type="multiclass",
                        num_classes=7,
                        iterations=50,
                        learning_rate=0.05,
                        depth=3,
                        l2_leaf_reg=3.0,
                        verbose=0,
                    )
                    model.train(X, y)
                    self.catboost_models.append(model)
                except Exception as e:
                    print(f"[Endings] CatBoost cat {cat_idx} train fail: {e}")
                    self.catboost_models.append(None)

        self._trained=True
        return {"n_draws":len(draws), "xgb_available": XGB_AVAILABLE, "catboost_available": CATBOOST_AVAILABLE}

    def predict(self, draws, target_round):
        """11 base 앙상블 예측: XGB 0.2 + CatBoost 0.2 + Markov 0.3 + frequency 0.3."""
        if not self._trained: return self._baseline()
        hist=[d for d in draws if int(d.get("round",0))<target_round]
        if len(hist)<10: return self._baseline()
        cm=self._extract(hist)

        per_cat={}
        for i in range(10):
            s=cm[:,i]; last=int(s[-1])

            # Markov 예측
            mp=self.markov_heads[i].predict(last)

            # Frequency 예측
            fp=_freq_dist(s)

            # XGBoost 예측
            xgb_prob = None
            if XGB_AVAILABLE and self.xgb_models and self.xgb_models[i] is not None:
                X_query = self._build_features(cm, i, lookback=30)
                if X_query is not None and len(X_query) > 0:
                    try:
                        xgb_prob = self.xgb_models[i].predict_proba(X_query[-1:])
                        if xgb_prob is not None and len(xgb_prob) > 0:
                            # XGBoost가 학습 데이터에 없는 클래스는 제외 → 7개로 padding
                            raw = xgb_prob[0]
                            if len(raw) < 7:
                                padded = np.zeros(7)
                                padded[:len(raw)] = raw
                                xgb_prob = padded
                            else:
                                xgb_prob = raw[:7]
                            xgb_prob = xgb_prob / xgb_prob.sum()  # normalize
                        else:
                            xgb_prob = None
                    except:
                        xgb_prob = None

            # CatBoost 예측
            catboost_prob = None
            if CATBOOST_AVAILABLE and self.catboost_models and self.catboost_models[i] is not None:
                X_query = self._build_features(cm, i, lookback=30)
                if X_query is not None and len(X_query) > 0:
                    try:
                        catboost_prob = self.catboost_models[i].predict_proba(X_query[-1:])
                        if catboost_prob is not None and len(catboost_prob) > 0:
                            raw = catboost_prob[0]
                            if len(raw) < 7:
                                padded = np.zeros(7)
                                padded[:len(raw)] = raw
                                catboost_prob = padded
                            else:
                                catboost_prob = raw[:7]
                            catboost_prob = catboost_prob / catboost_prob.sum()
                        else:
                            catboost_prob = None
                    except:
                        catboost_prob = None

            # 가중 앙상블 (XGB + CatBoost 병렬, Markov/freq baseline)
            probs = []
            weights = []

            if xgb_prob is not None:
                probs.append(xgb_prob)
                weights.append(0.2)
            if catboost_prob is not None:
                probs.append(catboost_prob)
                weights.append(0.2)

            probs.append(mp)
            weights.append(0.3)
            probs.append(fp)
            weights.append(0.3)

            # 가중평균
            weights = np.array(weights)
            weights = weights / weights.sum()
            ap = np.average(np.array(probs), axis=0, weights=weights)

            # 기여도 기록
            contrib = {
                "markov": 0.3,
                "frequency": 0.3,
            }
            if xgb_prob is not None:
                contrib["xgboost"] = 0.2
            if catboost_prob is not None:
                contrib["catboost"] = 0.2

            ap /= ap.sum()
            exp=float((ap*np.arange(7)).sum()); M=DIGIT_POOL_SIZES[i]
            per_cat[f"digit_{i}"]={
                "absolute_dist":ap.tolist(),"expected_count":exp,"current_pool_size":M,
                "expected_ratio":exp/M,"top_class":int(np.argmax(ap)),"top_class_prob":float(ap.max()),
                "narrative":f"끝수{i} pool {M}개 중 {int(np.argmax(ap))}개 가능성 {ap.max()*100:.1f}%",
                "model_contributions":contrib}
        return {"indicator_name":"endings_distribution","per_category":per_cat}

    def _baseline(self):
        u=np.full(7,1/7)
        return {"indicator_name":"endings_distribution","per_category":{f"digit_{i}":{"absolute_dist":u.tolist(),"expected_count":3,"current_pool_size":DIGIT_POOL_SIZES[i],"expected_ratio":3/DIGIT_POOL_SIZES[i],"narrative":f"digit_{i} not trained","model_contributions":{}} for i in range(10)}}

def validate_walk_forward(n_rounds=50):
    draws=fetch_all_draws()
    if len(draws)<100: return {"error":"insufficient"}
    rounds=sorted([int(d["round"]) for d in draws])[-n_rounds:]
    p=EndingsDistributionPredictor(); r=BaselineRunner()
    cat_res={}
    for di in range(10):
        pce_tot, fce_tot, n = 0,0,0
        for tr in rounds:
            hist=[d for d in draws if int(d.get("round",0))<tr]
            if len(hist)<50: continue
            p.train(hist,50)
            out=p.predict(hist,tr)
            pd=np.array(out["per_category"][f"digit_{di}"]["absolute_dist"])
            tgt=next((d for d in draws if int(d["round"])==tr),None)
            if not tgt: continue
            tc=sum(1 for x in tgt["numbers"] if x%10==di)
            cm=p._extract(hist); fd=_freq_dist(cm[:,di])
            pce_tot+=r.cross_entropy(pd,tc); fce_tot+=r.cross_entropy(fd,tc); n+=1
        if n>0: cat_res[f"digit_{di}"]={"predictor_ce":pce_tot/n,"frequency_ce":fce_tot/n,"n_rounds":n}
    if not cat_res: return {"error":"no_rounds"}
    apc=np.mean([x["predictor_ce"] for x in cat_res.values()])
    afc=np.mean([x["frequency_ce"] for x in cat_res.values()])
    return {"n_categories":10,"avg_predictor_ce":float(apc),"avg_frequency_ce":float(afc),"improvement_pct":(afc-apc)/max(afc,1e-9)*100,"wins_frequency":apc<afc,"per_category":cat_res}

def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--validate",type=int,default=0)
    args=parser.parse_args()
    if args.validate>0:
        print(f"[EndingsDistribution] validating {args.validate} rounds...")
        res=validate_walk_forward(args.validate)
        if "error" in res: print(f"ERROR: {res['error']}"); return
        print(f"\n카테고리:{res['n_categories']}, predictor_ce:{res['avg_predictor_ce']:.4f}, frequency_ce:{res['avg_frequency_ce']:.4f}, improvement:{res['improvement_pct']:+.2f}%, wins:{res['wins_frequency']}")
        print(f"[게이트]: {'PASS' if res['wins_frequency'] else 'FAIL'}")

if __name__=="__main__": main()
