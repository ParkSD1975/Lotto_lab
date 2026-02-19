"""Markov Model - Gap(미출현 기간) 기반 전이 확률."""

import os
import json
import numpy as np
import config


class MarkovLottoModel:
    """각 번호별 Gap 상태 전이 확률 계산."""

    def __init__(self):
        self.matrices = {}  # {num: {gap: {next_state_probs}}}
        # 실제로는 단순화하여 P(출현 | 현재 Gap) 만 저장
        self.gap_probs = {} # {num: {gap: {'appear_prob': 0.1, 'count': 5}}}

    def train(self, draws: list):
        """전이 행렬 구성."""
        # draws: 최신 -> 과거
        # 시간순 처리를 위해 뒤집음
        sorted_draws = list(reversed(draws))
        
        self.gap_probs = {n: {} for n in range(1, 46)}
        
        # 번호별 Gap 추적
        current_gaps = {n: 0 for n in range(1, 46)}
        
        for draw in sorted_draws:
            nums = set(draw["numbers"])
            
            for n in range(1, 46):
                gap = current_gaps[n]
                
                # 기록이 없으면 초기화
                if gap not in self.gap_probs[n]:
                    self.gap_probs[n][gap] = {"appear": 0, "total": 0}
                
                self.gap_probs[n][gap]["total"] += 1
                
                if n in nums:
                    self.gap_probs[n][gap]["appear"] += 1
                    current_gaps[n] = 0 # 출현했으므로 Gap 리셋
                else:
                    current_gaps[n] += 1 # 미출현, Gap 증가

        self._save_model()
        return {"success": True}

    def predict(self, draws: list) -> dict:
        """현재 Gap 상태 기반 출현 확률 예측."""
        if not self.gap_probs:
            self._load_model()
            
        current_gaps = {n: 0 for n in range(1, 46)}
        
        # 현재 시점의 Gap 계산 (최신 회차부터 거슬러 올라감)
        for n in range(1, 46):
            gap = 0
            for d in draws:
                if n in d["numbers"]:
                    break
                gap += 1
            current_gaps[n] = gap
            
        result = {}
        for n in range(1, 46):
            gap = current_gaps[n]
            stats = self.gap_probs.get(str(n), {}).get(str(gap)) 
            # JSON 로드시 key가 문자열로 변환됨을 고려
            
            if not stats:
                 # 해당 Gap 데이터가 없으면 베이지안 평활화 (평균 확률로 회귀)
                 prob = config.RANDOM_BASELINE
            else:
                # 관측 데이터가 적으면 신뢰도 낮춤
                appear = stats["appear"]
                total = stats["total"]
                raw_prob = appear / total if total > 0 else 0
                
                # 베이지안 추정 (가상의 사전 데이터 5개 추가)
                alpha = 1 # 출현 가중치
                beta = 44 # 미출현 가중치 (약 1/45 확률)
                prob = (appear + alpha) / (total + alpha + beta)
                
            result[n] = float(prob)
            
        return result

    def get_reasoning(self, number: int, current_gap: int) -> str:
        """XAI를 위한 추론 문장 생성."""
        if not self.gap_probs:
            self._load_model()
            
        stats = self.gap_probs.get(str(number), {}).get(str(current_gap))
        
        if stats:
            prob = (stats["appear"] / stats["total"]) * 100
            return (
                f"현재 {current_gap}회 연속 미출현 중입니다. "
                f"과거 동일한 상황이 {stats['total']}번 있었으며, "
                f"그 중 {stats['appear']}회 당첨되어 약 {prob:.1f}%의 확률을 보였습니다."
            )
        else:
            return (
                f"현재 {current_gap}회 연속 미출현 중입니다. "
                f"이토록 오랫동안 나오지 않은 적은 과거에 드물었습니다 (데이터 부족)."
            )

    def _save_model(self):
        path = os.path.join(config.MODEL_DIR, "markov_matrices.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.gap_probs, f)

    def _load_model(self):
        path = os.path.join(config.MODEL_DIR, "markov_matrices.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                self.gap_probs = json.load(f)
