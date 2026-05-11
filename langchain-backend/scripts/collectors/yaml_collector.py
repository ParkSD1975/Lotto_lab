"""YAML Collector: manual_operations.yaml에서 operations/statistics/time_windows 추출.

Stage 6-1-A-5: Self-Discovery NLP Phase 1 - YAML 소스
"""
from __future__ import annotations
import yaml
from typing import Dict, Any


def collect_from_yaml(yaml_path: str) -> Dict[str, Any]:
    """manual_operations.yaml에서 operations/statistics/time_windows 추출.

    Returns:
        {
            "operations": [...],
            "statistics": [...],
            "time_windows": [...]
        }
    """
    result = {"operations": [], "statistics": [], "time_windows": []}
    try:
        with open(yaml_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        for category in ['operations', 'statistics', 'time_windows']:
            items = data.get(category, [])
            for item in items:
                result[category].append({
                    "key": item.get("key", ""),
                    "name_kr": item.get("name_kr", ""),
                    "aliases": item.get("aliases", []),
                    "description": item.get("description", ""),
                    "source": "manual_operations.yaml"
                })

        print(f"[yaml_collector] {len(result['operations'])}개 operations, "
              f"{len(result['statistics'])}개 statistics, "
              f"{len(result['time_windows'])}개 time_windows 수집 완료")
        return result

    except Exception as e:
        print(f"[yaml_collector] 오류: {e}")
        return result
