"""Merger: 4개 collector 결과 통합 + 충돌 해결.

Stage 6-1-A-7: Self-Discovery NLP Phase 1 - 통합
"""
from __future__ import annotations
from typing import List, Dict, Any
from alias_generator import generate_aliases


def merge_filters(db_filters: List[Dict], js_filters: List[Dict], vfy_filters: List[Dict]) -> List[Dict[str, Any]]:
    """필터 3개 소스 통합.

    우선순위: DB > JS > verification.html
    """
    merged = {}

    # 1. DB (최우선)
    for f in db_filters:
        key = f['key']
        merged[key] = {
            "key": key,
            "name_kr": f['name_kr'],
            "name_en": f.get('name_en', ''),
            "category": f.get('category', 'basic'),
            "description": f.get('description', ''),
            "members": f.get('members', []),
            "value_range": f.get('value_range', {}),
            "aliases": [],
            "source": f['source']
        }

    # 2. JS (name_kr/description 보강)
    for f in js_filters:
        key = f['key']
        if key in merged:
            # DB 우선, JS는 빈 필드만 채움
            if not merged[key]['description']:
                merged[key]['description'] = f.get('description', '')
        else:
            # DB에 없으면 JS 추가
            merged[key] = {
                "key": key,
                "name_kr": f['name_kr'],
                "name_en": '',
                "category": 'basic',
                "description": f.get('description', ''),
                "members": [],
                "value_range": {},
                "aliases": [],
                "source": f['source']
            }

    # 3. verification.html (보강)
    for f in vfy_filters:
        key = f['key']
        if key in merged:
            if not merged[key]['description']:
                merged[key]['description'] = f.get('description', '')
        else:
            merged[key] = {
                "key": key,
                "name_kr": f['name_kr'],
                "name_en": '',
                "category": 'basic',
                "description": f.get('description', ''),
                "members": [],
                "value_range": {},
                "aliases": [],
                "source": f['source']
            }

    # 4. alias 자동 생성
    for key, data in merged.items():
        data['aliases'] = generate_aliases(key, data['name_kr'])

    print(f"[merger] {len(merged)}개 필터 통합 완료")
    return list(merged.values())


def merge_models(py_models: List[Dict], js_models: List[Dict]) -> List[Dict[str, Any]]:
    """모델 2개 소스 통합.

    우선순위: Python (ensemble.py) > JS
    """
    merged = {}

    # 1. Python (최우선)
    for m in py_models:
        key = m['key']
        merged[key] = {
            "key": key,
            "name_kr": m['name_kr'],
            "category": m.get('category', 'base_model'),
            "color": '',
            "aliases": [],
            "source": m['source']
        }

    # 2. JS (color 보강)
    for m in js_models:
        key = m['key']
        if key in merged:
            merged[key]['color'] = m.get('color', '#64748b')
        else:
            merged[key] = {
                "key": key,
                "name_kr": m['name_kr'],
                "category": 'base_model',
                "color": m.get('color', '#64748b'),
                "aliases": [],
                "source": m['source']
            }

    # 3. alias 자동 생성
    for key, data in merged.items():
        data['aliases'] = generate_aliases(key, data['name_kr'])

    print(f"[merger] {len(merged)}개 모델 통합 완료")
    return list(merged.values())


def merge_yaml_items(items: List[Dict]) -> List[Dict[str, Any]]:
    """YAML operations/statistics/time_windows는 이미 완전한 형태 → 그대로 반환."""
    # alias 자동 생성은 이미 manual_operations.yaml에 정의됨
    print(f"[merger] {len(items)}개 YAML 항목 처리 완료")
    return items
