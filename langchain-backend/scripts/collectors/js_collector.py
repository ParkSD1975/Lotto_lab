"""JS Collector: JavaScript 파일에서 FILTER_LABELS/MODEL_CONFIG 추출.

Stage 6-1-A-3: Self-Discovery NLP Phase 1 - JS 소스
"""
from __future__ import annotations
import re
import json
from typing import List, Dict, Any


def collect_from_js(js_path: str) -> Dict[str, Any]:
    """ai_deep_learning.js에서 FILTER_LABELS, FILTER_DESC, MODEL_CONFIG 추출.

    Returns:
        {
            "filters": [...],
            "models": [...]
        }
    """
    result = {"filters": [], "models": []}
    try:
        with open(js_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # FILTER_LABELS 추출 (간단 regex)
        filter_labels = _extract_js_object(content, 'FILTER_LABELS')
        filter_desc = _extract_js_object(content, 'FILTER_DESC')

        for key, name_kr in filter_labels.items():
            result["filters"].append({
                "key": key,
                "name_kr": name_kr,
                "description": filter_desc.get(key, ''),
                "source": "ai_deep_learning.js"
            })

        # MODEL_CONFIG 추출
        model_config = _extract_js_object(content, 'MODEL_CONFIG')
        for key, cfg in model_config.items():
            if isinstance(cfg, dict):
                result["models"].append({
                    "key": key,
                    "name_kr": cfg.get("label", key),
                    "color": cfg.get("color", "#64748b"),
                    "source": "ai_deep_learning.js"
                })

        print(f"[js_collector] {len(result['filters'])}개 필터, {len(result['models'])}개 모델 수집 완료 (JS)")
        return result

    except Exception as e:
        print(f"[js_collector] 오류: {e}")
        return result


def collect_from_verification_html(html_path: str) -> List[Dict[str, Any]]:
    """verification.html에서 FILTER_META 추출.

    Returns:
        필터 dict list
    """
    filters = []
    try:
        with open(html_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # FILTER_META = { ... } 블록 추출
        match = re.search(r'const\s+FILTER_META\s*=\s*\{(.+?)\n\s*\};', content, re.DOTALL)
        if not match:
            print(f"[js_collector] FILTER_META not found in {html_path}")
            return []

        meta_block = match.group(1)
        # sum: { label: '총합', ... } 형태 파싱
        entries = re.findall(r'(\w+):\s*\{[^}]*label:\s*["\']([^"\']+)["\'][^}]*desc:\s*["\']([^"\']+)["\'][^}]*\}', meta_block)

        for key, label, desc in entries:
            filters.append({
                "key": key,
                "name_kr": label,
                "description": desc,
                "source": "verification.html"
            })

        print(f"[js_collector] {len(filters)}개 필터 수집 완료 (verification.html)")
        return filters

    except Exception as e:
        print(f"[js_collector] 오류: {e}")
        return []


def _extract_js_object(content: str, var_name: str) -> Dict[str, Any]:
    """JS 코드에서 const VAR = { ... } 객체 추출 (간단 regex)."""
    try:
        # 단순 key: 'value' 형태만 처리
        match = re.search(rf'const\s+{var_name}\s*=\s*\{{(.+?)\n\s*\}};', content, re.DOTALL)
        if not match:
            return {}

        obj_block = match.group(1)
        result = {}

        # key: 'value' 또는 key: { ... } 추출
        # 1. 문자열 value
        for m in re.finditer(r'(\w+):\s*["\']([^"\']+)["\']', obj_block):
            result[m.group(1)] = m.group(2)

        # 2. 객체 value (MODEL_CONFIG 케이스)
        # xgboost: { label: 'XGBoost', color: '#3b82f6' }
        for m in re.finditer(r'(\w+):\s*\{([^}]+)\}', obj_block):
            key = m.group(1)
            inner = m.group(2)
            label_m = re.search(r'label:\s*["\']([^"\']+)["\']', inner)
            color_m = re.search(r'color:\s*["\']([^"\']+)["\']', inner)
            result[key] = {
                "label": label_m.group(1) if label_m else key,
                "color": color_m.group(1) if color_m else "#64748b"
            }

        return result
    except Exception as e:
        print(f"[js_collector] _extract_js_object 오류: {e}")
        return {}
