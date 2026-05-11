"""Alias Generator: 한글/영문 변형 자동 생성.

Stage 6-1-A-6: Self-Discovery NLP Phase 1 - Alias 생성
"""
from __future__ import annotations
from typing import List


# 숫자 한글 매핑 (1~9)
NUM_TO_KR = {
    "1": "일", "2": "이", "3": "삼", "4": "사", "5": "오",
    "6": "육", "7": "칠", "8": "팔", "9": "구", "0": "영"
}


def generate_aliases(key: str, name_kr: str, existing_aliases: List[str] = None) -> List[str]:
    """key/name_kr 기반으로 자동 alias 생성.

    Args:
        key: 필터/모델 키 (mul7, xgboost 등)
        name_kr: 한글 이름 (7배수, XGBoost 등)
        existing_aliases: 기존 수동 정의 alias (우선순위)

    Returns:
        alias list (중복 제거됨)
    """
    aliases = set(existing_aliases or [])

    # 1. 원본 추가
    aliases.add(key)
    aliases.add(name_kr)

    # 2. 한글 변형 (배수, 홀짝 등)
    if '배수' in name_kr:
        # "7배수" → "7의배수", "7의 배수", "칠배수"
        num = ''.join(c for c in name_kr if c.isdigit())
        if num:
            kr_num = NUM_TO_KR.get(num, num)
            aliases.add(f"{num}의배수")
            aliases.add(f"{num}의 배수")
            aliases.add(f"{kr_num}배수")

    if '홀짝' in name_kr or 'odd' in key.lower():
        aliases.update(['홀수', '짝수', '홀', '짝', 'odd', 'even'])

    if '저고' in name_kr or 'high' in key.lower() or 'low' in key.lower():
        aliases.update(['저번호', '고번호', '저', '고', 'low', 'high'])

    if '연번' in name_kr or 'consecutive' in key.lower():
        aliases.update(['연속', '연속번호', 'consecutive', 'consec'])

    if '소수' in name_kr or 'prime' in key.lower():
        aliases.update(['소수', 'prime', '프라임'])

    if '합성수' in name_kr or 'composite' in key.lower():
        aliases.update(['합성', 'composite'])

    if '총합' in name_kr or 'sum' in key.lower():
        aliases.update(['합', '합계', 'sum', 'total'])

    if '끝수' in name_kr or 'tail' in key.lower() or 'ending' in key.lower():
        aliases.update(['끝자리', '일의자리', 'tail', 'ending', 'digit'])

    if 'AC' in name_kr or 'ac' in key.lower():
        aliases.update(['AC', 'ac', 'AC값', '복잡도', 'complexity'])

    # 3. 모델 영문 약어 (XGBoost → xgb, Temporal Fusion Transformer → tft)
    if 'xgboost' in key.lower():
        aliases.update(['xgb', 'xgboost', '엑스지비', 'XGBoost'])

    if 'catboost' in key.lower():
        aliases.update(['catboost', 'cat', '캣부스트', 'CatBoost'])

    if 'tabnet' in key.lower():
        aliases.update(['tabnet', 'tab', '탭넷', 'TabNet'])

    if 'cnn' in key.lower():
        aliases.update(['cnn', 'CNN', '씨엔엔', 'convolution'])

    if 'gnn' in key.lower():
        aliases.update(['gnn', 'GNN', '지엔엔', 'graph'])

    if 'markov' in key.lower():
        aliases.update(['markov', 'Markov', '마르코프', '마코프'])

    if 'autoencoder' in key.lower():
        aliases.update(['autoencoder', 'ae', 'AE', '오토인코더'])

    if 'tft' in key.lower() or 'temporal' in name_kr.lower():
        aliases.update(['tft', 'TFT', 'temporal', '템포럴', 'transformer'])

    if 'mhn' in key.lower() or 'hopfield' in name_kr.lower():
        aliases.update(['mhn', 'MHN', 'hopfield', '홉필드', 'modern hopfield'])

    if 'bayesian' in key.lower():
        aliases.update(['bayesian', 'bayes', '베이지안', 'bayesian_nn'])

    if 'nbeats' in key.lower():
        aliases.update(['nbeats', 'NBEATS', 'N-BEATS', 'n-beats'])

    # 4. 빈 문자열 제거
    aliases.discard('')

    return sorted(list(aliases))
