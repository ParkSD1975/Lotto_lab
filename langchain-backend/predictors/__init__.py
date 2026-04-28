"""IndependentCountPredictor 패키지.

Stage 1 (21지표): independent_count_predictor 통합 패턴 + 22 인스턴스 (Phase 1~4)
Stage 2 (회귀): regression_predictor (DynamicIndependentCountPredictor)

각 predictor는 11 base 모델을 통합하며 SSL pretrained backbone을 공유한다.
"""
