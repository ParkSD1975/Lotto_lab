"""Validator: vocabulary.json 스키마 검증.

Stage 6-1-A-8: Self-Discovery NLP Phase 1 - 검증
"""
from __future__ import annotations
from typing import Dict, Any, List


def validate_vocabulary(vocab: Dict[str, Any]) -> bool:
    """vocabulary.json 스키마 검증.

    필수 키: version, generated_at, sources, filters, models, operations, statistics, time_windows
    필터 22개 이상, 모델 11개 확인
    """
    errors = []

    # 1. 필수 최상위 키
    required_keys = ['version', 'generated_at', 'sources', 'filters', 'models',
                     'operations', 'statistics', 'time_windows']
    for key in required_keys:
        if key not in vocab:
            errors.append(f"필수 키 누락: {key}")

    # 2. 필터 개수 (22개 이상)
    filters = vocab.get('filters', [])
    if len(filters) < 22:
        errors.append(f"필터 개수 부족: {len(filters)}개 (최소 22개 필요)")

    # 3. 모델 개수 (11개 정확히)
    models = vocab.get('models', [])
    if len(models) != 11:
        errors.append(f"모델 개수 오류: {len(models)}개 (정확히 11개 필요)")

    # 4. 중복 key 검사
    def check_duplicates(items: List[Dict], category: str):
        keys = [item.get('key') for item in items]
        dups = [k for k in keys if keys.count(k) > 1]
        if dups:
            errors.append(f"{category}에 중복 key: {set(dups)}")

    check_duplicates(filters, 'filters')
    check_duplicates(models, 'models')
    check_duplicates(vocab.get('operations', []), 'operations')

    # 5. 필수 필드 검사
    for f in filters:
        if not f.get('key'):
            errors.append(f"필터 key 누락: {f}")
        if not f.get('name_kr'):
            errors.append(f"필터 name_kr 누락: {f.get('key')}")

    for m in models:
        if not m.get('key'):
            errors.append(f"모델 key 누락: {m}")
        if not m.get('name_kr'):
            errors.append(f"모델 name_kr 누락: {m.get('key')}")

    # 6. 결과
    if errors:
        print("[validator] 검증 실패:")
        for err in errors:
            print(f"  - {err}")
        return False

    print(f"[validator] 검증 성공: {len(filters)}개 필터, {len(models)}개 모델")
    return True
