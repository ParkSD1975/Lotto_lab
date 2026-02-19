"""XGBoost 모델 - 45개 번호별 독립적 이진 분류."""

import os
import joblib
import numpy as np
import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import precision_score

import config


class LottoXGBoost:
    """번호별 45개 XGBClassifier 관리."""

    def __init__(self):
        self.models = {}  # {1: xgb_model, 2: xgb_model, ...}
        self.feature_names = [
            "total_freq",
            "recent_10_freq",
            "recent_50_freq",
            "current_gap",
            "avg_gap",
            "max_gap",
            "std_gap",
            "gap_percentile",
            "momentum",
            "trend_slope",
            "is_prime",
            "is_odd",
            "is_low",
            "last_sum",
            "last_odd_count",
            "last_low_count",
            "last_ac",
            "last_consec",
            "last_tail_sum",
            "avg_sum_5",
            "sum_std_5",
            "carryover_status",
            "freq_diff",
            "gap_position",
            "momentum_dup",
        ]

    def build_features_for_number(self, number: int, draws: list, target_idx: int):
        """특정 번호에 대한 피처 벡터 생성 (Target Leakage 방지)."""
        # target_idx 이전 데이터만 사용
        past_draws = draws[target_idx + 1 :]  # draws는 최신순이므로 index가 커질수록 과거
        if not past_draws:
            return np.zeros(len(self.feature_names))

        # 1. 빈도 피처
        total_count = sum(1 for d in past_draws if number in d["numbers"])
        recent_10 = sum(1 for d in past_draws[:10] if number in d["numbers"])
        recent_50 = sum(1 for d in past_draws[:50] if number in d["numbers"])

        # 2. Gap(미출현) 피처
        gaps = []
        current_gap = 0
        found = False
        for i, d in enumerate(past_draws):
            if number in d["numbers"]:
                gaps.append(i - current_gap if found else i)
                current_gap = i
                found = True

        if not gaps:
            gaps = [len(past_draws)]

        current_gap = 0
        for d in past_draws:
            if number in d["numbers"]:
                break
            current_gap += 1

        avg_gap = np.mean(gaps)
        max_gap = np.max(gaps)
        std_gap = np.std(gaps) if len(gaps) > 1 else 0

        # Gap 백분위 (현재 Gap이 과거 대비 얼마나 긴가)
        gap_percentile = 0.0
        if len(gaps) > 0:
            smaller_gaps = sum(1 for g in gaps if g < current_gap)
            gap_percentile = smaller_gaps / len(gaps)

        # 3. 모멘텀 (최근 빈도 vs 장기 빈도)
        long_term_prob = total_count / len(past_draws) if past_draws else 0
        short_term_prob = recent_10 / 10.0
        momentum = short_term_prob - long_term_prob

        # 4. 직전 회차 정보 (직전 회차의 통계적 특성)
        last_draw = past_draws[0]
        last_nums = last_draw.get("numbers", [])
        last_sum = sum(last_nums)
        last_odd = sum(1 for n in last_nums if n % 2 == 1)
        last_low = sum(1 for n in last_nums if n <= 22)
        
        # AC값 계산
        diffs = set()
        for i in range(len(last_nums)):
            for j in range(i + 1, len(last_nums)):
                diffs.add(abs(last_nums[i] - last_nums[j]))
        last_ac = len(diffs) - (len(last_nums) - 1) if last_nums else 0

        # 연번
        sorted_last = sorted(last_nums)
        last_consec = sum(
            1 for i in range(len(sorted_last) - 1) if sorted_last[i + 1] - sorted_last[i] == 1
        )
        last_tail_sum = sum(n % 10 for n in last_nums)

        # 5. 정적 속성
        is_prime = 1 if number in config.PRIMES else 0
        is_odd = 1 if number % 2 == 1 else 0
        is_low = 1 if number <= 22 else 0

        return np.array(
            [
                total_count,
                recent_10,
                recent_50,
                current_gap,
                avg_gap,
                max_gap,
                std_gap,
                gap_percentile,
                momentum,
                0.0,  # trend_slope (간소화)
                is_prime,
                is_odd,
                is_low,
                last_sum,
                last_odd,
                last_low,
                last_ac,
                last_consec,
                last_tail_sum,
                0.0,  # avg_sum_5
                0.0,  # sum_std_5
                1 if number in last_nums else 0,  # carryover
                0.0,  # freq_diff
                0.0,  # gap_position
                0.0,  # momentum_dup
            ]
        )

    def train(self, draws: list):
        """45개 모델 학습."""
        # draws: 최신 -> 과거
        X_data = {n: [] for n in range(1, 46)}
        y_data = {n: [] for n in range(1, 46)}

        # 최근 500회차만 사용 (너무 오래된 데이터는 노이즈)
        limit = min(len(draws) - 50, 500)
        
        print(f"  Training XGBoost on {limit} recent draws...")

        for i in range(limit):
            target_draw = draws[i]
            target_nums = set(target_draw["numbers"])

            for num in range(1, 46):
                features = self.build_features_for_number(num, draws, i)
                label = 1 if num in target_nums else 0
                X_data[num].append(features)
                y_data[num].append(label)

        # 모델 학습
        for num in range(1, 46):
            X = np.array(X_data[num])
            y = np.array(y_data[num])

            # 불균형 데이터 처리 (당첨 1 : 낙첨 6 비율)
            scale_pos_weight = 6.0

            model = xgb.XGBClassifier(
                n_estimators=config.XGB_N_ESTIMATORS,
                max_depth=config.XGB_MAX_DEPTH,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                scale_pos_weight=scale_pos_weight,
                n_jobs=1,  # 병렬 처리는 외부 루프에서 제어하지 않음
                device="cpu", # 기본 CPU 사용
            )
            model.fit(X, y)
            self.models[num] = model

        self._save_models()
        return {"success": True, "models_trained": 45}

    def predict(self, draws: list) -> dict:
        """다음 회차 예측."""
        if not self.models:
            self._load_models()

        if not self.models:
            return {n: 0.02 for n in range(1, 46)}

        result = {}
        for num in range(1, 46):
            # 타겟 인덱스 -1은 "미래"를 의미 (가상의 다음 회차)
            # build_features_for_number 로직 상 draws 전체를 과거로 봄
            
            # 실제로는 build_features에서 target_idx + 1 부터 과거로 보므로
            # -1을 넣으면 index 0 (가장 최신) 부터 과거로 사용됨.
            features = self.build_features_for_number(num, draws, -1)
            
            if num in self.models:
                prob = self.models[num].predict_proba([features])[0][1]
                result[num] = float(prob)
            else:
                result[num] = 0.0

        return result
    
    def get_top_features(self, number: int) -> list:
        """특정 번호 모델의 중요 피처 반환 (XAI용)."""
        if not self.models:
            self._load_models()
            
        if number not in self.models:
            return []
            
        model = self.models[number]
        importances = model.feature_importances_
        indices = np.argsort(importances)[::-1]
        
        top_features = []
        for i in range(min(5, len(indices))):
            idx = indices[i]
            top_features.append((self.feature_names[idx], float(importances[idx])))
            
        return top_features

    def _save_models(self):
        path = os.path.join(config.MODEL_DIR, "xgboost_models.pkl")
        joblib.dump(self.models, path)

    def _load_models(self):
        path = os.path.join(config.MODEL_DIR, "xgboost_models.pkl")
        if os.path.exists(path):
            self.models = joblib.load(path)
