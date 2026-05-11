"""Build Vocabulary: Self-Discovery NLP Phase 1 Entry Point.

6곳 소스에서 도메인 용어 자동 수집 → vocabulary.json 단일 진실 소스 생성.

Usage:
    python scripts/build_vocabulary.py --output js/vocabulary.json
    python scripts/build_vocabulary.py --dry-run

Stage 6-1-A-0: Self-Discovery NLP Phase 1 - Main
"""
from __future__ import annotations
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import os
import json
import argparse
from datetime import datetime, timezone


def main():
    parser = argparse.ArgumentParser(description='Build vocabulary.json from 6 sources')
    parser.add_argument('--output', default='js/vocabulary.json', help='Output path')
    parser.add_argument('--dry-run', action='store_true', help='Validation only (no write)')
    args = parser.parse_args()

    # ==========================================
    # Stage 6-1-A-1~5: 4개 Collector 실행
    # ==========================================
    print("=" * 60)
    print("Self-Discovery NLP Phase 1: Vocabulary Registry 자동 수집")
    print("=" * 60)

    # 경로 설정 (langchain-backend 기준)
    backend_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    repo_root = os.path.abspath(os.path.join(backend_root, '..'))
    js_root = os.path.join(repo_root, 'js')

    # Collector import
    from collectors.db_collector import collect_filters_from_db
    from collectors.python_ast_collector import (
        collect_models_from_ensemble,
        collect_predictors_from_init
    )
    from collectors.js_collector import (
        collect_from_js,
        collect_from_verification_html
    )
    from collectors.yaml_collector import collect_from_yaml
    from merger import merge_filters, merge_models, merge_yaml_items
    from validator import validate_vocabulary

    # 1. DB 필터
    print("\n[1/6] DB filter_definitions...")
    db_filters = collect_filters_from_db()

    # 2. Python 모델 (ensemble.py)
    print("\n[2/6] Python ensemble.py TASK_WEIGHTS...")
    ensemble_path = os.path.join(backend_root, 'models', 'ensemble.py')
    py_models = collect_models_from_ensemble(ensemble_path)

    # 3. Python predictors (predictors/__init__.py)
    print("\n[3/6] Python predictors/__init__.py...")
    predictors_init_path = os.path.join(backend_root, 'predictors', '__init__.py')
    predictors = collect_predictors_from_init(predictors_init_path)

    # 4. JS ai_deep_learning.js
    print("\n[4/6] JS ai_deep_learning.js...")
    js_path = os.path.join(js_root, 'ai_deep_learning.js')
    js_data = collect_from_js(js_path)

    # 5. JS verification.html
    print("\n[5/6] JS verification.html...")
    vfy_path = os.path.join(repo_root, 'verification.html')
    vfy_filters = collect_from_verification_html(vfy_path)

    # 6. YAML manual_operations.yaml
    print("\n[6/6] YAML manual_operations.yaml...")
    yaml_path = os.path.join(backend_root, 'data', 'manual_operations.yaml')
    yaml_data = collect_from_yaml(yaml_path)

    # ==========================================
    # Stage 6-1-A-7: Merger 실행 (통합 + alias 생성)
    # ==========================================
    print("\n" + "=" * 60)
    print("Merging & Alias Generation...")
    print("=" * 60)

    filters = merge_filters(db_filters, js_data['filters'], vfy_filters)
    models = merge_models(py_models, js_data['models'])
    operations = merge_yaml_items(yaml_data['operations'])
    statistics = merge_yaml_items(yaml_data['statistics'])
    time_windows = merge_yaml_items(yaml_data['time_windows'])

    # ==========================================
    # vocabulary.json 생성
    # ==========================================
    vocabulary = {
        "version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": [
            "filter_definitions (Supabase)",
            "ensemble.py TASK_WEIGHTS",
            "predictors/__init__.py",
            "ai_deep_learning.js",
            "verification.html FILTER_META",
            "manual_operations.yaml"
        ],
        "filters": sorted(filters, key=lambda x: x['key']),
        "models": sorted(models, key=lambda x: x['key']),
        "operations": operations,
        "statistics": statistics,
        "time_windows": time_windows,
        "intents": []  # Phase 2에서 채워질 예정
    }

    # ==========================================
    # Stage 6-1-A-8: Validator 실행
    # ==========================================
    print("\n" + "=" * 60)
    print("Validation...")
    print("=" * 60)

    if not validate_vocabulary(vocabulary):
        print("\n[ERROR] 검증 실패 — vocabulary.json 생성 중단")
        sys.exit(1)

    # ==========================================
    # 출력
    # ==========================================
    if args.dry_run:
        print("\n[DRY-RUN] 검증만 수행 (파일 미생성)")
        print(f"  - {len(filters)}개 필터")
        print(f"  - {len(models)}개 모델")
        print(f"  - {len(operations)}개 operations")
        print(f"  - {len(statistics)}개 statistics")
        print(f"  - {len(time_windows)}개 time_windows")
        return

    output_path = os.path.join(repo_root, args.output)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(vocabulary, f, ensure_ascii=False, indent=2)

    print(f"\n[SUCCESS] vocabulary.json 생성 완료: {output_path}")
    print(f"  - {len(filters)}개 필터")
    print(f"  - {len(models)}개 모델")
    print(f"  - {len(operations)}개 operations")
    print(f"  - {len(statistics)}개 statistics")
    print(f"  - {len(time_windows)}개 time_windows")

    # 파일 크기 확인
    file_size = os.path.getsize(output_path)
    print(f"  - 파일 크기: {file_size:,} bytes ({file_size / 1024:.1f} KB)")

    if file_size > 50 * 1024:
        print("  [WARNING] 파일 크기 50KB 초과 — gzip 압축 권장")

    # 샘플 출력 (filters/models/operations 각 1개)
    print("\n샘플:")
    if filters:
        print(f"  [Filter] {filters[0]['key']}: {filters[0]['name_kr']} (aliases: {filters[0]['aliases'][:3]}...)")
    if models:
        print(f"  [Model] {models[0]['key']}: {models[0]['name_kr']} (aliases: {models[0]['aliases'][:3]}...)")
    if operations:
        print(f"  [Operation] {operations[0]['key']}: {operations[0]['name_kr']} (aliases: {operations[0]['aliases'][:3]}...)")


if __name__ == '__main__':
    main()
