"""DB Collector: Supabase filter_definitions 테이블에서 필터 추출.

Stage 6-1-A-1: Self-Discovery NLP Phase 1 - DB 소스
"""
from __future__ import annotations
from typing import List, Dict, Any


def collect_filters_from_db() -> List[Dict[str, Any]]:
    """Supabase filter_definitions 테이블에서 22+ 필터 추출.

    Returns:
        필터 dict list [
            {
                "key": "mul7",
                "name_kr": "7배수",
                "name_en": "Multiple of 7",
                "category": "multiple",
                "description": "...",
                "source": "filter_definitions"
            },
            ...
        ]
    """
    try:
        # langchain-backend/db/supabase_client 동적 import (경로 문제 회피)
        import os
        import sys
        backend_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        if backend_root not in sys.path:
            sys.path.insert(0, backend_root)

        from db.supabase_client import supabase

        result = supabase.table('filter_definitions') \
            .select('filter_key, filter_name, filter_name_en, ui_group, category, description, ai_metadata') \
            .eq('is_active', True) \
            .execute()

        filters = []
        for row in result.data:
            key = row.get('filter_key', '')
            if not key:
                continue

            # ai_metadata에서 members/value_range 추출 (JSON 필드)
            ai_meta = row.get('ai_metadata') or {}
            members = ai_meta.get('members', [])
            value_range = ai_meta.get('value_range', {})

            filters.append({
                "key": key,
                "name_kr": row.get('filter_name', key),
                "name_en": row.get('filter_name_en', ''),
                "category": row.get('category') or row.get('ui_group', 'basic'),
                "description": row.get('description', ''),
                "members": members,
                "value_range": value_range,
                "source": "filter_definitions"
            })

        print(f"[db_collector] {len(filters)}개 필터 수집 완료")
        return filters

    except Exception as e:
        print(f"[db_collector] 오류: {e}")
        return []
