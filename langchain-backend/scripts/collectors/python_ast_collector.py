"""Python AST Collector: Python 파일에서 모델/predictor 용어 추출.

Stage 6-1-A-2: Self-Discovery NLP Phase 1 - Python 소스
"""
from __future__ import annotations
import ast
import os
from typing import List, Dict, Any


def collect_models_from_ensemble(ensemble_path: str) -> List[Dict[str, Any]]:
    """models/ensemble.py에서 TASK_WEIGHTS dict 파싱하여 11 base 모델 추출.

    Returns:
        모델 dict list [
            {
                "key": "xgboost",
                "name_kr": "XGBoost",
                "category": "base_model",
                "source": "ensemble.py"
            },
            ...
        ]
    """
    models = []
    try:
        with open(ensemble_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # TASK_WEIGHTS 변수 찾기 (정규식 간단 파싱)
        import re
        match = re.search(r'TASK_WEIGHTS\s*=\s*\{(.+?)\n\}', content, re.DOTALL)
        if not match:
            print(f"[python_ast_collector] TASK_WEIGHTS not found in {ensemble_path}")
            return []

        # 첫 번째 task의 모델 키 추출
        task_content = match.group(1)
        # "recommend_top": { ... } 블록에서 모델명 추출
        models_match = re.search(r'"recommend_top":\s*\{(.+?)\}', task_content, re.DOTALL)
        if not models_match:
            print(f"[python_ast_collector] recommend_top task not found")
            return []

        model_block = models_match.group(1)
        # "xgboost": 0.20, 형태 추출
        model_keys = re.findall(r'"(\w+)":\s*[\d.]+', model_block)

        # 한글 이름 매핑 (수동 정의)
        kr_names = {
            "xgboost": "XGBoost",
            "catboost": "CatBoost",
            "tabnet": "TabNet",
            "cnn": "CNN",
            "gnn": "GNN",
            "markov": "Markov Chain",
            "autoencoder": "Autoencoder",
            "tft": "Temporal Fusion Transformer",
            "mhn": "Modern Hopfield Network",
            "bayesian_nn": "Bayesian Neural Network",
            "nbeats": "N-BEATS"
        }

        for key in model_keys:
            if key in ('lstm', 'transformer'):  # DEPRECATED 모델 제외
                continue
            models.append({
                "key": key,
                "name_kr": kr_names.get(key, key.upper()),
                "category": "base_model",
                "source": "ensemble.py"
            })

        print(f"[python_ast_collector] {len(models)}개 모델 수집 완료 (ensemble.py)")
        return models

    except Exception as e:
        print(f"[python_ast_collector] 오류: {e}")
        return []


def collect_predictors_from_init(init_path: str) -> List[Dict[str, Any]]:
    """predictors/__init__.py에서 __all__ export list 파싱하여 predictor 추출.

    Returns:
        predictor dict list (21개 예상)
    """
    predictors = []
    try:
        with open(init_path, 'r', encoding='utf-8') as f:
            tree = ast.parse(f.read())

        # __all__ 변수 찾기
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == '__all__':
                        if isinstance(node.value, ast.List):
                            for elt in node.value.elts:
                                if isinstance(elt, ast.Constant):
                                    name = elt.value
                                    # Predictor로 끝나는 것만
                                    if name.endswith('Predictor'):
                                        # Phase1*, Phase2*, Phase3* 등으로 분류
                                        if 'Phase1' in name or 'Phase2' in name or 'Phase3' in name:
                                            predictors.append({
                                                "key": _snake_case(name),
                                                "name_kr": _humanize(name),
                                                "category": "predictor",
                                                "source": "predictors/__init__.py"
                                            })

        print(f"[python_ast_collector] {len(predictors)}개 predictor 수집 완료")
        return predictors

    except Exception as e:
        print(f"[python_ast_collector] 오류: {e}")
        return []


def _snake_case(name: str) -> str:
    """CamelCase → snake_case."""
    import re
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()


def _humanize(name: str) -> str:
    """EndingsDistributionPredictor → 끝수 분포."""
    mapping = {
        "EndingsDistributionPredictor": "끝수 분포",
        "HighLowPredictor": "저고 비율",
        "OddEvenPredictor": "홀짝 비율",
        "DecadePredictor": "번호대 분포",
        "GungPredictor": "9궁 분포",
        "CarryoverPredictor": "이월수",
        "NeighborPredictor": "이웃수",
        "ConsecutivePredictor": "연번",
        "LottoPaperPredictor": "로또용지 분포",
        "MultiplePredictor": "배수",
        "SpecialNumberPredictor": "특수 번호",
        "MissingGroupPredictor": "미출수 그룹",
        "HotColdPredictor": "Hot/Cold",
        "Phase2EndingsSumPredictor": "끝수합",
        "Phase3ACPredictor": "AC값"
    }
    return mapping.get(name, name.replace('Predictor', ''))
