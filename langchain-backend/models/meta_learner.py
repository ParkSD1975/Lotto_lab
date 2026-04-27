"""
P7: Stacking Meta-Learner

7개 기본 모델(XGBoost/LSTM/CNN/Transformer/GNN/Markov/Autoencoder)의
per-number 예측 확률을 피처로 받아 LightGBM(없으면 LogisticRegression)으로
최적 앙상블 보정 확률을 출력한다.

학습 데이터: JSONL 예측 로그 (meta_log.jsonl)
  - 한 항목 = 한 회차 예측 → 45개 샘플 (번호별 binary label)
  - 최소 100회차 이상 로그가 쌓여야 자동 학습

Bootstrap: bootstrap_meta_log(draws)
  - 역대 이력으로 stride 단위 Rolling 시뮬레이션
  - 모델을 여러 번 돌리므로 stride=10 기본
"""

import os
import json
import pickle
import numpy as np
from datetime import datetime

# ── LightGBM / sklearn fallback ──────────────────────────────────────────────
try:
    import lightgbm as lgb
    HAS_LGB = True
except ImportError:
    HAS_LGB = False
    print("[MetaLearner] LightGBM 없음 → LogisticRegression 폴백")

MODEL_NAMES = [
    "xgboost", "lstm", "cnn", "transformer",
    "gnn", "markov", "autoencoder",
]
MIN_ROUNDS   = 100   # 메타러너 학습 최소 회차


class MetaLearner:
    """
    Stacking 메타러너

    피처 (per number, 7차원):
        [xgb_prob, lstm_prob, cnn_prob, transformer_prob,
         gnn_prob, markov_prob, ae_prob]

    레이블: 해당 번호가 실제 당첨됐는지 (binary: 0/1)

    predict() 반환: {1~45: float}  — 합이 1이 되도록 정규화된 보정 확률
    """

    def __init__(self, save_dir: str = "saved_models"):
        self.save_dir   = save_dir
        self.log_path   = os.path.join(save_dir, "meta_log.jsonl")
        self.model_path = os.path.join(save_dir, "meta_learner.pkl")
        self.alpha_path = os.path.join(save_dir, "meta_alpha.json")  # M-1-C
        self.meta_model = None   # lgb.Booster 또는 sklearn estimator
        # M-1-C: alpha 학습 가능 파라미터 — first-run은 config 기본값
        try:
            import config
            self._default_alpha = config.META_ALPHA_DEFAULT
            self._min_val = config.META_ALPHA_MIN_VAL_SAMPLES
        except Exception:
            self._default_alpha = 0.30
            self._min_val = 50
        self.alpha = self._default_alpha
        self._load_alpha()
        os.makedirs(save_dir, exist_ok=True)

    # ── M-1-C: alpha bounded optimization ─────────────────────────────────
    def fit_alpha(self,
                  ensemble_pred: np.ndarray,
                  meta_pred: np.ndarray,
                  val_labels: np.ndarray) -> dict:
        """검증 데이터에서 (1-α)·ensemble + α·meta = label MSE 최소 α 산출.

        Args:
            ensemble_pred: shape (n,) — 베이스 ensemble 확률
            meta_pred:     shape (n,) — MetaLearner 출력 확률
            val_labels:    shape (n,) — 0/1 정답

        주의:
            일반 Ridge regression은 두 계수 합=1 강제 안 됨 (음수 coef·합≠1 가능).
            scipy.optimize.minimize_scalar(bounds=(0,1)) 제약 최적화 사용.

        Returns:
            {alpha, mse_at_alpha, n_samples, fitted}
        """
        ensemble_pred = np.asarray(ensemble_pred, dtype=np.float64).ravel()
        meta_pred     = np.asarray(meta_pred,     dtype=np.float64).ravel()
        val_labels    = np.asarray(val_labels,    dtype=np.float64).ravel()

        n = len(val_labels)
        if not (len(ensemble_pred) == len(meta_pred) == n):
            raise ValueError("ensemble_pred / meta_pred / val_labels length mismatch")

        if n < self._min_val:
            return {
                "alpha":         self.alpha,
                "mse_at_alpha":  None,
                "n_samples":     n,
                "fitted":        False,
                "reason":        f"insufficient validation data ({n} < {self._min_val})",
            }

        try:
            from scipy.optimize import minimize_scalar
        except ImportError:
            return {
                "alpha":         self.alpha,
                "mse_at_alpha":  None,
                "n_samples":     n,
                "fitted":        False,
                "reason":        "scipy not installed",
            }

        def loss(a: float) -> float:
            blend = (1.0 - a) * ensemble_pred + a * meta_pred
            return float(np.mean((blend - val_labels) ** 2))

        res = minimize_scalar(loss, bounds=(0.0, 1.0), method="bounded")
        self.alpha = float(res.x)
        self._save_alpha()

        return {
            "alpha":         self.alpha,
            "mse_at_alpha":  float(res.fun),
            "n_samples":     n,
            "fitted":        True,
        }

    def _save_alpha(self) -> None:
        try:
            with open(self.alpha_path, "w") as f:
                json.dump({"alpha": float(self.alpha),
                           "default": float(self._default_alpha)}, f)
        except Exception as e:
            print(f"  [MetaLearner] alpha 저장 실패: {e}")

    def _load_alpha(self) -> None:
        if not os.path.exists(self.alpha_path):
            return
        try:
            with open(self.alpha_path, "r") as f:
                data = json.load(f)
            a = float(data.get("alpha", self._default_alpha))
            if 0.0 <= a <= 1.0:
                self.alpha = a
        except Exception:
            self.alpha = self._default_alpha

    # ── 1. 예측 로그 기록 ─────────────────────────────────────────────────
    def log(self, model_probs: dict, actual_numbers: list) -> None:
        """
        한 회차 예측 결과를 로그에 기록.

        Args:
            model_probs    : {model_name: {num(int): prob(float)}}
            actual_numbers : 실제 당첨 번호 리스트 [int]
        """
        entry = {
            "ts":          datetime.now().isoformat(),
            "model_probs": {
                m: {str(n): float(model_probs.get(m, {}).get(n, 1/45))
                    for n in range(1, 46)}
                for m in MODEL_NAMES
            },
            "actual": [int(x) for x in actual_numbers],
        }
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # ── 2. 로그 → 학습 데이터 변환 ────────────────────────────────────────
    def build_training_data(self) -> tuple:
        """
        JSONL 로그 → (X, y) numpy arrays.

        X shape: (n_samples, 7)  — n_samples = 회차수 × 45
        y shape: (n_samples,)    — 0/1
        """
        if not os.path.exists(self.log_path):
            return None, None

        X_rows, y_rows = [], []
        with open(self.log_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry  = json.loads(line)
                    mprobs = entry["model_probs"]
                    actual = set(int(x) for x in entry["actual"])
                    for num in range(1, 46):
                        feats = [
                            float(mprobs.get(m, {}).get(str(num), 1/45))
                            for m in MODEL_NAMES
                        ]
                        X_rows.append(feats)
                        y_rows.append(1 if num in actual else 0)
                except Exception:
                    continue

        n_rounds = len(X_rows) // 45
        if n_rounds < MIN_ROUNDS:
            return None, None

        return (
            np.array(X_rows, dtype=np.float32),
            np.array(y_rows, dtype=np.int32),
        )

    # ── 3. 메타러너 학습 ──────────────────────────────────────────────────
    def train(self) -> dict:
        """
        로그 데이터로 메타러너 학습.

        Returns:
            {success, n_rounds, n_samples, method, feature_importance}
        """
        X, y = self.build_training_data()
        log_count = self._log_count()

        if X is None:
            return {
                "success": False,
                "error":   f"학습 데이터 부족 (현재: {log_count}회차 / 최소: {MIN_ROUNDS}회차)",
                "log_rounds": log_count,
            }

        n_samples = len(X)
        n_rounds  = n_samples // 45

        if HAS_LGB:
            method = "LightGBM"
            self.meta_model = self._train_lgb(X, y)
        else:
            method = "LogisticRegression (LightGBM 미설치)"
            self.meta_model = self._train_lr(X, y)

        self._save()

        return {
            "success":            True,
            "n_rounds":           n_rounds,
            "n_samples":          n_samples,
            "method":             method,
            "feature_importance": self.get_feature_importance(),
        }

    def _train_lgb(self, X: np.ndarray, y: np.ndarray):
        """LightGBM binary classifier"""
        # 클래스 불균형 보정 (6당첨/39비당첨 ≈ 1:6.5)
        pos_w = float((y == 0).sum()) / max(float((y == 1).sum()), 1)

        params = {
            "objective":        "binary",
            "metric":           "binary_logloss",
            "num_leaves":       15,
            "learning_rate":    0.05,
            "feature_fraction": 0.8,
            "bagging_fraction": 0.8,
            "bagging_freq":     5,
            "min_child_samples": 30,
            "scale_pos_weight": pos_w,
            "verbose":          -1,
        }

        dtrain = lgb.Dataset(X, label=y)
        booster = lgb.train(
            params,
            dtrain,
            num_boost_round=300,
            valid_sets=[dtrain],
            callbacks=[
                lgb.early_stopping(30, verbose=False),
                lgb.log_evaluation(period=0),
            ],
        )
        return booster

    def _train_lr(self, X: np.ndarray, y: np.ndarray):
        """sklearn LogisticRegression (LightGBM 없을 때 폴백)"""
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler
        from sklearn.pipeline import Pipeline

        pipe = Pipeline([
            ("scaler", StandardScaler()),
            ("lr",     LogisticRegression(
                C=1.0, max_iter=1000,
                class_weight="balanced",
                solver="lbfgs",
            )),
        ])
        pipe.fit(X, y)
        return pipe

    # ── 4. 예측 ───────────────────────────────────────────────────────────
    def predict(self, model_probs: dict) -> dict:
        """
        7모델 확률 → 메타러너 보정 확률.

        Args:
            model_probs: {model_name: {num(int): float}}

        Returns:
            {1~45: float}  — 합=1 정규화
        """
        if self.meta_model is None:
            self._load()
        if self.meta_model is None:
            return {}

        X = np.array(
            [
                [float(model_probs.get(m, {}).get(n, 1/45)) for m in MODEL_NAMES]
                for n in range(1, 46)
            ],
            dtype=np.float32,
        )

        if HAS_LGB and isinstance(self.meta_model, lgb.Booster):
            raw = self.meta_model.predict(X)              # sigmoid 출력
        else:
            raw = self.meta_model.predict_proba(X)[:, 1]  # sklearn

        total = raw.sum()
        norm  = raw / total if total > 0 else np.ones(45) / 45.0
        return {n: float(norm[n - 1]) for n in range(1, 46)}

    # ── 5. 부트스트랩 (역대 이력 → 가상 로그 생성) ──────────────────────
    def bootstrap_meta_log(
        self,
        draws: list,
        ensemble_obj,
        stride:     int  = 10,
        max_rounds: int  = 300,
        warmup:     int  = 50,
    ) -> dict:
        """
        역대 이력(draws)에서 Rolling 시뮬레이션으로 메타 학습용 로그를 생성.

        draws 는 최신순(draws[0] = 최신) 목록.
        stride 회차마다 1회 inference → 로그 기록.

        Returns:
            {added, skipped, total_log_rounds}
        """
        draws_sorted = sorted(draws, key=lambda x: x["round"])
        n = len(draws_sorted)
        added = 0
        skipped = 0

        eval_indices = list(range(warmup + stride - 1, min(n, warmup + max_rounds), stride))

        print(f"  [MetaLearner] Bootstrap 시작: {len(eval_indices)}회 시뮬레이션 예정")

        for idx in eval_indices:
            history  = draws_sorted[:idx]        # idx 회차 이전 이력
            actual   = draws_sorted[idx]         # idx 회차 실제 결과

            # 각 모델 개별 inference
            model_probs: dict = {}
            all_ok = True
            for m_name, m_obj in ensemble_obj.models.items():
                try:
                    pred = m_obj.predict(history)
                    model_probs[m_name] = {
                        n_: float(pred.get(n_, 1/45)) for n_ in range(1, 46)
                    }
                except Exception as _e:
                    model_probs[m_name] = {n_: 1/45 for n_ in range(1, 46)}
                    all_ok = False

            # Markov 별도 처리 (ensemble 내 models dict에 없을 수 있음)
            if "markov" not in model_probs:
                model_probs["markov"] = {n_: 1/45 for n_ in range(1, 46)}
                all_ok = False

            if not all_ok:
                skipped += 1

            actual_nums = actual.get("numbers", [])
            self.log(model_probs, actual_nums)
            added += 1

            if added % 10 == 0:
                print(f"  [MetaLearner] Bootstrap 진행 중: {added}/{len(eval_indices)} 완료")

        total_log = self._log_count()
        print(f"  [MetaLearner] Bootstrap 완료: {added}개 추가 (총 {total_log}회차)")
        return {
            "added":            added,
            "skipped":          skipped,
            "total_log_rounds": total_log,
        }

    # ── 6. 모델 중요도 ────────────────────────────────────────────────────
    def get_feature_importance(self) -> dict:
        """모델별 피처 중요도 반환"""
        if self.meta_model is None:
            return {}

        if HAS_LGB and isinstance(self.meta_model, lgb.Booster):
            imp = self.meta_model.feature_importance(importance_type="gain")
            total = imp.sum()
            if total > 0:
                imp = imp / total * 100.0
            return {m: round(float(v), 2) for m, v in zip(MODEL_NAMES, imp)}

        # sklearn 파이프라인 (LogisticRegression)
        if hasattr(self.meta_model, "named_steps"):
            lr = self.meta_model.named_steps.get("lr")
            if lr is not None and hasattr(lr, "coef_"):
                coef = np.abs(lr.coef_[0])
                total = coef.sum()
                if total > 0:
                    coef = coef / total * 100.0
                return {m: round(float(v), 2) for m, v in zip(MODEL_NAMES, coef)}

        return {}

    # ── 7. 로그 상태 조회 ─────────────────────────────────────────────────
    def status(self) -> dict:
        """메타러너 현황 요약"""
        log_rounds = self._log_count()
        return {
            "log_rounds":   log_rounds,
            "min_required": MIN_ROUNDS,
            "ready":        log_rounds >= MIN_ROUNDS,
            "model_loaded": self.meta_model is not None or os.path.exists(self.model_path),
            "method":       "LightGBM" if HAS_LGB else "LogisticRegression",
        }

    # ── Private ──────────────────────────────────────────────────────────
    def _log_count(self) -> int:
        if not os.path.exists(self.log_path):
            return 0
        count = 0
        with open(self.log_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    count += 1
        return count

    def _save(self) -> None:
        if self.meta_model is None:
            return
        with open(self.model_path, "wb") as f:
            pickle.dump(self.meta_model, f)
        print(f"  [MetaLearner] 모델 저장 완료: {self.model_path}")

    def _load(self) -> None:
        if not os.path.exists(self.model_path):
            return
        try:
            with open(self.model_path, "rb") as f:
                self.meta_model = pickle.load(f)
            print(f"  [MetaLearner] 모델 로드 완료: {self.model_path}")
        except Exception as e:
            print(f"  [MetaLearner] 로드 실패: {e}")
            self.meta_model = None
