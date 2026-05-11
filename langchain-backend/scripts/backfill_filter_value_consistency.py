"""
backfill_filter_value_consistency.py

1222·1223회 weekly_filter_predictions 데이터를 단일 앙상블 산출로 통합.

문제:
  - filter_value: simulate_all_filters MC 결과 (corrected_probs 기반)
  - ensemble_min/max: 가중평균 결과
  - 두 값이 불일치하여 프론트 페이지가 모순된 결과 표시

해결:
  - filter_value = [ensemble_min, ensemble_max] 로 통일
  - model_expectations에서 __ensemble__ 추출하여 일관성 확보
  - deep_analysis_history.analysis_data.range_analysis도 동일하게 갱신

주의:
  - 데이터 누수 방지: target_round 이전 데이터만 사용
  - ensemble_ci는 유지 (Bootstrap CI 부수 정보)
"""

from __future__ import annotations
import sys
import io
import json
import logging
import os
from datetime import datetime, timezone

# Windows cp949 회피
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 상위 디렉토리를 Python 경로에 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.supabase_client import get_client

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("backfill_filter_value")


def backfill_weekly_filter_predictions(target_rounds: list[int]) -> None:
    """
    weekly_filter_predictions 테이블의 filter_value를 ensemble_min/max로 통일.

    Args:
        target_rounds: 갱신할 회차 목록 (예: [1222, 1223])
    """
    sb = get_client()

    for target_round in target_rounds:
        logger.info(f"=== {target_round}회차 weekly_filter_predictions backfill 시작 ===")

        # 1. 현재 데이터 조회
        result = sb.table("weekly_filter_predictions") \
            .select("*") \
            .eq("target_round", target_round) \
            .execute()

        if not result.data:
            logger.warning(f"  {target_round}회차 데이터 없음 (skip)")
            continue

        logger.info(f"  {len(result.data)}개 필터 row 조회")

        # 2. 각 row 갱신
        updated_count = 0
        for row in result.data:
            fk = row["filter_key"]
            ens_min = row["ensemble_min"]
            ens_max = row["ensemble_max"]

            # filter_value를 ensemble_min/max로 통일
            new_filter_value = [ens_min if ens_min is not None else 0,
                                 ens_max if ens_max is not None else 6]

            # 기존 filter_value
            old_filter_value = json.loads(row["filter_value"]) if isinstance(row["filter_value"], str) else row["filter_value"]

            # 변경 사항 있으면 업데이트
            if old_filter_value != new_filter_value:
                logger.info(f"  [{fk}] filter_value: {old_filter_value} → {new_filter_value}")

                sb.table("weekly_filter_predictions") \
                    .update({
                        "filter_value": json.dumps(new_filter_value, ensure_ascii=False),
                    }) \
                    .eq("target_round", target_round) \
                    .eq("filter_key", fk) \
                    .execute()

                updated_count += 1

        logger.info(f"  {target_round}회차 {updated_count}개 필터 갱신 완료")


def backfill_deep_analysis_history(target_rounds: list[int]) -> None:
    """
    deep_analysis_history 테이블의 analysis_data.range_analysis를 ensemble_min/max로 통일.

    Args:
        target_rounds: 갱신할 회차 목록 (예: [1222, 1223])
    """
    sb = get_client()

    for target_round in target_rounds:
        logger.info(f"=== {target_round}회차 deep_analysis_history backfill 시작 ===")

        # 1. deep_analysis_history 조회
        result = sb.table("deep_analysis_history") \
            .select("id, analysis_data") \
            .eq("target_round", target_round) \
            .execute()

        if not result.data:
            logger.warning(f"  {target_round}회차 deep_analysis_history 데이터 없음 (skip)")
            continue

        for hist_row in result.data:
            hist_id = hist_row["id"]
            analysis_data = hist_row.get("analysis_data", {})

            if not isinstance(analysis_data, dict):
                logger.warning(f"  history id={hist_id} analysis_data가 dict 아님 (skip)")
                continue

            range_analysis = analysis_data.get("range_analysis", {})
            if not isinstance(range_analysis, dict):
                logger.warning(f"  history id={hist_id} range_analysis가 dict 아님 (skip)")
                continue

            # 2. weekly_filter_predictions에서 ensemble_min/max 조회
            filter_result = sb.table("weekly_filter_predictions") \
                .select("filter_key, ensemble_min, ensemble_max") \
                .eq("target_round", target_round) \
                .execute()

            if not filter_result.data:
                logger.warning(f"  {target_round}회차 weekly_filter_predictions 데이터 없음 (skip)")
                continue

            # 3. range_analysis 갱신
            updated = False
            for filter_row in filter_result.data:
                fk = filter_row["filter_key"]
                ens_min = filter_row["ensemble_min"]
                ens_max = filter_row["ensemble_max"]

                if fk in range_analysis:
                    old_range = range_analysis[fk].get("range")
                    new_range = [ens_min if ens_min is not None else 0,
                                  ens_max if ens_max is not None else 6]

                    if old_range != new_range:
                        logger.info(f"  [{fk}] range_analysis.range: {old_range} → {new_range}")
                        range_analysis[fk]["range"] = new_range
                        range_analysis[fk]["ensemble_min"] = ens_min
                        range_analysis[fk]["ensemble_max"] = ens_max
                        updated = True

            # 4. analysis_data 업데이트
            if updated:
                analysis_data["range_analysis"] = range_analysis

                sb.table("deep_analysis_history") \
                    .update({
                        "analysis_data": analysis_data,
                    }) \
                    .eq("id", hist_id) \
                    .execute()

                logger.info(f"  history id={hist_id} range_analysis 갱신 완료")


def main():
    """메인 실행 함수."""
    target_rounds = [1222, 1223]

    logger.info("=" * 80)
    logger.info("백엔드 앙상블 산출 일관성 Backfill 시작")
    logger.info(f"대상 회차: {target_rounds}")
    logger.info("=" * 80)

    # 1. weekly_filter_predictions 갱신
    backfill_weekly_filter_predictions(target_rounds)

    # 2. deep_analysis_history 갱신
    backfill_deep_analysis_history(target_rounds)

    logger.info("=" * 80)
    logger.info("Backfill 완료")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
