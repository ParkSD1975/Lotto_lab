"""
predictions_v4.py — Single Source of Truth API v4

weekly_* 테이블을 읽는 읽기 전용 엔드포인트.
실시간 딥러닝 없음 → 즉시 응답 (XAI 느림 문제 해결).

엔드포인트:
  GET /api/v4/status                  — 최신 파이프라인 실행 현황
  GET /api/v4/predictions/{round}     — 특정 회차 메인 예측 (top5 / excl10 / combos)
  GET /api/v4/xai/{round}             — 번호별 XAI 기여도 45행
  GET /api/v4/filters/{round}         — 필터별 예측 범위 (P8 CI 포함)
  GET /api/v4/regression/{round}      — 회귀분석 step별 결과
  GET /api/v4/recommendations/{round} — Top5 상세 (P4 CI·consensus)
  GET /api/v4/combinations/{round}    — 추천 조합 10게임
  POST /api/v4/run-pipeline           — 파이프라인 즉시 실행 트리거
"""

import json
import traceback
import threading
import time
from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import JSONResponse

from db.supabase_client import get_client, fetch_all_draws

router = APIRouter(prefix="/api/v4", tags=["predictions-v4"])

# Fire-and-forget 백필 작업 추적용 in-memory 상태 (HF Spaces 단일 머신 가정)
_PIPELINE_JOBS = {}  # job_id -> {"round": int, "status": "running"|"done"|"error", "started_at": ts, "ended_at": ts, "error": str}


def _ok(data: dict) -> JSONResponse:
    return JSONResponse({"success": True, **data})


def _err(msg: str, status: int = 500) -> JSONResponse:
    return JSONResponse({"success": False, "error": msg}, status_code=status)


def _latest_round(client) -> int:
    """최신 weekly_predictions 회차 반환"""
    res = client.table("weekly_predictions") \
        .select("target_round") \
        .order("target_round", desc=True) \
        .limit(1).execute()
    return res.data[0]["target_round"] if res.data else 0


# ─────────────────────────────────────────────────────────────────────────────
# 1. 파이프라인 상태
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/status")
async def get_v4_status():
    """
    weekly_predictions 최신 행 기준 파이프라인 상태.

    Returns:
        latest_round, has_data, top_5, meta_active, created_at
    """
    try:
        client = get_client()
        res = client.table("weekly_predictions") \
            .select("target_round, top_5, exclude_10, meta_active, meta_alpha, "
                    "pipeline_version, created_at, verified_at, top5_hit_count") \
            .order("target_round", desc=True).limit(1).execute()

        if not res.data:
            return _ok({"has_data": False, "latest_round": 0})

        row = res.data[0]
        return _ok({
            "has_data":       True,
            "latest_round":   row["target_round"],
            "top_5":          row.get("top_5", []),
            "exclude_10":     row.get("exclude_10", []),
            "meta_active":    row.get("meta_active", False),
            "meta_alpha":     row.get("meta_alpha", 0.0),
            "pipeline_version": row.get("pipeline_version"),
            "created_at":     row.get("created_at"),
            "verified_at":    row.get("verified_at"),
            "top5_hit_count": row.get("top5_hit_count"),
        })
    except Exception as e:
        traceback.print_exc()
        return _err(str(e))


# ─────────────────────────────────────────────────────────────────────────────
# 2. 메인 예측 (top5 + excl10 + combos 통합)
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/predictions/{round_num}")
async def get_predictions(round_num: int = 0):
    """
    특정 회차 전체 예측 패키지.

    round_num=0 → 최신 회차 자동 선택.

    Returns:
        target_round, top_5, exclude_10, recommendations (P4 상세),
        combinations (10게임), model_weights, meta_active
    """
    try:
        client = get_client()
        r = round_num or _latest_round(client)
        if not r:
            return _err("데이터 없음", 404)

        # weekly_predictions
        wp = client.table("weekly_predictions") \
            .select("*").eq("target_round", r).maybeSingle().execute()
        if not wp.data:
            return _err(f"round {r} 데이터 없음 — 파이프라인 미실행", 404)

        # weekly_recommendations (P4)
        wr = client.table("weekly_recommendations") \
            .select("rank, number, ci_lower, ci_upper, consensus_count, "
                    "confidence_level, probability, hit") \
            .eq("target_round", r) \
            .order("rank").execute()

        # weekly_combinations
        wc = client.table("weekly_combinations") \
            .select("combo_rank, numbers, total_sum, odd_count, high_count") \
            .eq("target_round", r) \
            .order("combo_rank").execute()

        row = wp.data
        return _ok({
            "target_round":    r,
            "top_5":           row.get("top_5", []),
            "exclude_10":      row.get("exclude_10", []),
            "model_weights":   row.get("model_weights", {}),
            "meta_active":     row.get("meta_active", False),
            "meta_alpha":      row.get("meta_alpha", 0.0),
            "pipeline_version": row.get("pipeline_version"),
            "recommendations": wr.data or [],
            "combinations":    wc.data or [],
            "created_at":      row.get("created_at"),
        })
    except Exception as e:
        traceback.print_exc()
        return _err(str(e))


# ─────────────────────────────────────────────────────────────────────────────
# 3. XAI 기여도
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/xai/{round_num}")
async def get_xai(round_num: int = 0):
    """
    번호별 XAI 모델 기여도 (45행).

    round_num=0 → 최신 회차.

    Returns:
        target_round, xai: {1: {xgboost_pct, lstm_pct, ..., top_model, probability}, ...}
    """
    try:
        client = get_client()
        r = round_num or _latest_round(client)
        if not r:
            return _err("데이터 없음", 404)

        # Stage 1-4-D-2-fix-6: 11 base 통일 SELECT (catboost/tabnet/tft/mhn/bayesian_nn 추가)
        # Stage 1-4-D-2-fix-28: evidence_text 추가 (lazy fetch 폐기)
        res = client.table("weekly_number_xai") \
            .select("number, xgboost_pct, lstm_pct, cnn_pct, transformer_pct, "
                    "gnn_pct, markov_pct, autoencoder_pct, "
                    "catboost_pct, tabnet_pct, tft_pct, mhn_pct, bayesian_nn_pct, "
                    "top_model, veto, probability, evidence_text") \
            .eq("target_round", r) \
            .order("number").execute()

        if not res.data:
            return _err(f"round {r} XAI 데이터 없음", 404)

        xai_map = {}
        for row in res.data:
            n = row["number"]
            xai_map[n] = {
                # 7 base (legacy)
                "xgboost":     row.get("xgboost_pct", 0),
                "lstm":        row.get("lstm_pct", 0),
                "cnn":         row.get("cnn_pct", 0),
                "transformer": row.get("transformer_pct", 0),
                "gnn":         row.get("gnn_pct", 0),
                "markov":      row.get("markov_pct", 0),
                "autoencoder": row.get("autoencoder_pct", 0),
                # 5 신규 base (Stage 1-4-D-2)
                "catboost":    row.get("catboost_pct", 0),
                "tabnet":      row.get("tabnet_pct", 0),
                "tft":         row.get("tft_pct", 0),
                "mhn":         row.get("mhn_pct", 0),
                "bayesian_nn": row.get("bayesian_nn_pct", 0),
                # 메타
                "top_model":   row.get("top_model"),
                "veto":        row.get("veto"),
                "probability": row.get("probability"),
                # [Stage 1-4-D-2-fix-28] 사전 합성된 evidence reasons
                "evidence_text": row.get("evidence_text"),
            }

        return _ok({"target_round": r, "xai": xai_map})
    except Exception as e:
        traceback.print_exc()
        return _err(str(e))


# ─────────────────────────────────────────────────────────────────────────────
# 4. 필터 범위 예측 (P8 CI 포함)
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/filters/{round_num}")
async def get_filter_predictions(round_num: int = 0):
    """
    필터별 앙상블 예측 범위.

    P8 Bootstrap CI (sum/tail_sum/ac 등) 포함.

    Returns:
        target_round,
        filters: {
          "sum": {
            ensemble_min, ensemble_max,
            ci: {lo_p10, lo_p90, hi_p10, hi_p90, band, level},
            model_expectations: {lstm: {min,max,weight}, ...},
            primary_task, filter_value
          }, ...
        }
    """
    try:
        client = get_client()
        r = round_num or _latest_round(client)
        if not r:
            return _err("데이터 없음", 404)

        res = client.table("weekly_filter_predictions") \
            .select("filter_key, filter_value, primary_task, "
                    "ensemble_min, ensemble_max, ensemble_ci, model_expectations, "
                    "actual_value, in_range") \
            .eq("target_round", r) \
            .order("filter_key").execute()

        if not res.data:
            return _err(f"round {r} 필터 데이터 없음", 404)

        filters = {}
        for row in res.data:
            fv = row.get("filter_value")
            if isinstance(fv, str):
                try:
                    fv = json.loads(fv)
                except Exception:
                    pass
            filters[row["filter_key"]] = {
                "ensemble_min":       row.get("ensemble_min"),
                "ensemble_max":       row.get("ensemble_max"),
                "ci":                 row.get("ensemble_ci"),
                "model_expectations": row.get("model_expectations", {}),
                "primary_task":       row.get("primary_task"),
                "filter_value":       fv,
                "actual_value":       row.get("actual_value"),
                "in_range":           row.get("in_range"),
            }

        return _ok({"target_round": r, "filters": filters})
    except Exception as e:
        traceback.print_exc()
        return _err(str(e))


# ─────────────────────────────────────────────────────────────────────────────
# 5. 회귀분석
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/regression/{round_num}")
async def get_regression(round_num: int = 0):
    """
    회귀분석 step별 예측.

    Returns:
        target_round,
        regression: {
          2: {window_type, predicted_numbers, model_exp, primary_method, confidence},
          5: {...}, ...
        }
    """
    try:
        client = get_client()
        r = round_num or _latest_round(client)
        if not r:
            return _err("데이터 없음", 404)

        res = client.table("weekly_regression_analysis") \
            .select("step, window_type, predicted_numbers, "
                    "model_exp, primary_method, confidence") \
            .eq("target_round", r) \
            .order("step").execute()

        if not res.data:
            return _err(f"round {r} 회귀분석 데이터 없음", 404)

        regression = {
            row["step"]: {
                "window_type":        row.get("window_type"),
                "predicted_numbers":  row.get("predicted_numbers", []),
                "model_exp":          row.get("model_exp", {}),
                "primary_method":     row.get("primary_method"),
                "confidence":         row.get("confidence", 0),
            }
            for row in res.data
        }

        return _ok({"target_round": r, "regression": regression})
    except Exception as e:
        traceback.print_exc()
        return _err(str(e))


# ─────────────────────────────────────────────────────────────────────────────
# 6. Top5 추천 상세 (P4 CI·consensus)
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/recommendations/{round_num}")
async def get_recommendations(round_num: int = 0):
    """
    Top5 추천 상세 (P4 Bootstrap CI + consensus_count + confidence_level).

    Returns:
        target_round,
        recommendations: [
          {rank, number, ci_lower, ci_upper, consensus_count,
           confidence_level, probability, hit}, ...
        ]
    """
    try:
        client = get_client()
        r = round_num or _latest_round(client)
        if not r:
            return _err("데이터 없음", 404)

        res = client.table("weekly_recommendations") \
            .select("rank, number, ci_lower, ci_upper, "
                    "consensus_count, confidence_level, probability, hit") \
            .eq("target_round", r) \
            .order("rank").execute()

        if not res.data:
            return _err(f"round {r} 추천 데이터 없음", 404)

        return _ok({"target_round": r, "recommendations": res.data})
    except Exception as e:
        traceback.print_exc()
        return _err(str(e))


# ─────────────────────────────────────────────────────────────────────────────
# 7. 추천 조합
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/combinations/{round_num}")
async def get_combinations(round_num: int = 0):
    """
    추천 조합 10게임.

    Returns:
        target_round,
        combinations: [
          {combo_rank, numbers, total_sum, odd_count, high_count}, ...
        ]
    """
    try:
        client = get_client()
        r = round_num or _latest_round(client)
        if not r:
            return _err("데이터 없음", 404)

        res = client.table("weekly_combinations") \
            .select("combo_rank, numbers, total_sum, odd_count, high_count") \
            .eq("target_round", r) \
            .order("combo_rank").execute()

        if not res.data:
            return _err(f"round {r} 조합 데이터 없음", 404)

        return _ok({"target_round": r, "combinations": res.data})
    except Exception as e:
        traceback.print_exc()
        return _err(str(e))


# ─────────────────────────────────────────────────────────────────────────────
# 8. 파이프라인 즉시 실행
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/run-pipeline")
async def run_pipeline_now(body: dict = None):
    """
    weekly_pipeline_v2 fire-and-forget 백그라운드 실행 트리거.

    body (optional): {"target_round": 1234, "sync": false}
      - sync=false (기본): 즉시 202 + job_id 반환, 백그라운드 실행
      - sync=true: 완료까지 대기 (gateway timeout 위험, 디버그용)

    완료 확인: GET /api/v4/pipeline-status/{job_id}
    """
    body = body or {}
    target_round = body.get("target_round")
    sync_mode = bool(body.get("sync", False))

    if sync_mode:
        # 레거시 동기 경로 (HF Spaces 게이트웨이가 ~120s에 끊으므로 디버그용)
        import asyncio
        from concurrent.futures import ThreadPoolExecutor
        try:
            from pipeline.weekly_pipeline_v2 import WeeklyPipelineV2
            def _run():
                pipeline = WeeklyPipelineV2()
                return pipeline.run(target_round=target_round)
            loop = asyncio.get_event_loop()
            with ThreadPoolExecutor(max_workers=1) as executor:
                result = await loop.run_in_executor(executor, _run)
            return JSONResponse(result)
        except Exception as e:
            traceback.print_exc()
            return _err(str(e))

    # Fire-and-forget: thread 분리 실행
    job_id = f"job_{int(time.time())}_{target_round or 'auto'}"
    _PIPELINE_JOBS[job_id] = {
        "round": target_round,
        "status": "running",
        "started_at": time.time(),
        "ended_at": None,
        "error": None,
    }

    def _bg_run():
        try:
            from pipeline.weekly_pipeline_v2 import WeeklyPipelineV2
            pipeline = WeeklyPipelineV2()
            pipeline.run(target_round=target_round)
            _PIPELINE_JOBS[job_id]["status"] = "done"
        except Exception as ex:
            _PIPELINE_JOBS[job_id]["status"] = "error"
            _PIPELINE_JOBS[job_id]["error"] = str(ex)
            traceback.print_exc()
        finally:
            _PIPELINE_JOBS[job_id]["ended_at"] = time.time()

    thread = threading.Thread(target=_bg_run, daemon=True, name=f"pipeline-{job_id}")
    thread.start()

    return JSONResponse(
        {"success": True, "job_id": job_id, "round": target_round, "status": "running",
         "poll_url": f"/api/v4/pipeline-status/{job_id}"},
        status_code=202,
    )


@router.get("/pipeline-status/{job_id}")
async def get_pipeline_status(job_id: str):
    """fire-and-forget 백필 작업 상태 조회."""
    job = _PIPELINE_JOBS.get(job_id)
    if not job:
        return _err(f"unknown job_id: {job_id}", status=404)
    elapsed = (job["ended_at"] or time.time()) - job["started_at"]
    return _ok({
        "job_id": job_id,
        "round": job["round"],
        "status": job["status"],
        "elapsed_seconds": round(elapsed, 1),
        "error": job["error"],
    })


@router.get("/pipeline-jobs")
async def list_pipeline_jobs():
    """모든 백필 작업 일람."""
    return _ok({"jobs": _PIPELINE_JOBS, "total": len(_PIPELINE_JOBS)})
