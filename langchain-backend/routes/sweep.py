"""
sweep.py

Formula Variable Sweep — API 엔드포인트 (Phase 4).

Stage 6-F-X: Formula Sweep Phase 4
"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from uuid import UUID
import asyncio
import time
from datetime import datetime

from db.supabase_client import get_client
from services.formula_sweep_engine import FormulaSweepEngine
from models.sweep_schemas import (
    FormulaV5Multi,
    VariablePath,
    SweepCriteria,
    SweepResult,
)

router = APIRouter(prefix="/api/sweep", tags=["sweep"])


# ─────────────────────────────────────────────────────────────────
# 요청 스키마
# ─────────────────────────────────────────────────────────────────


class SweepRunRequest(BaseModel):
    """Sweep 실행 요청"""

    formula: dict  # FormulaV5Multi 호환 dict
    variable_paths: List[dict]  # VariablePath 리스트
    variable_range: dict  # {min: int, max: int, step: int}
    criteria: dict  # {min_consecutive: int, include_bonus: bool, min_avg_gap: float}
    eval_rounds: Optional[List[int]] = None  # 평가 대상 회차 목록 (None=전체)


# ─────────────────────────────────────────────────────────────────
# 엔드포인트
# ─────────────────────────────────────────────────────────────────


@router.post("/run")
async def run_sweep(req: SweepRunRequest, background_tasks: BackgroundTasks):
    """
    Sweep 작업 큐 등록 + background 실행 시작.

    Returns:
        {"job_id": str, "status": "queued"}
    """
    supabase = get_client()

    # 1. variable_range 검증
    var_min = req.variable_range.get("min", 2)
    var_max = req.variable_range.get("max", 1000)
    var_step = req.variable_range.get("step", 1)

    if var_min >= var_max:
        raise HTTPException(
            status_code=400, detail="variable_range.min must be < max"
        )
    if var_step < 1:
        raise HTTPException(
            status_code=400, detail="variable_range.step must be >= 1"
        )

    total_iterations = (var_max - var_min) // var_step + 1

    # 2. formula_sweep_jobs INSERT
    job_row = (
        supabase.table("formula_sweep_jobs")
        .insert(
            {
                "formula": req.formula,
                "variable_paths": req.variable_paths,
                "variable_range": req.variable_range,
                "criteria": req.criteria,
                "eval_rounds": req.eval_rounds,
                "status": "queued",
                "progress": {
                    "current": 0,
                    "total": total_iterations,
                    "eta_seconds": None,
                },
            }
        )
        .execute()
    )

    if not job_row.data:
        raise HTTPException(status_code=500, detail="Failed to create job")

    job_id = job_row.data[0]["id"]

    # 3. background task로 sweep 실행
    background_tasks.add_task(_execute_sweep, job_id)

    return {"job_id": job_id, "status": "queued"}


@router.get("/{job_id}/status")
async def get_status(job_id: str):
    """
    진행률 조회.

    Returns:
        {
            "job_id": str,
            "status": "queued" | "running" | "complete" | "failed",
            "progress": {"current": int, "total": int, "eta_seconds": float | None},
            "created_at": str,
            "updated_at": str,
        }
    """
    supabase = get_client()

    response = (
        supabase.table("formula_sweep_jobs")
        .select("id, status, progress, created_at, updated_at")
        .eq("id", job_id)
        .single()
        .execute()
    )

    if not response.data:
        raise HTTPException(status_code=404, detail="Job not found")

    return response.data


@router.get("/{job_id}/results")
async def get_results(
    job_id: str,
    min_consecutive: int = 3,
    limit: int = 100,
    offset: int = 0,
):
    """
    결과 조회 (페이징 + 필터).

    Args:
        job_id: Job ID
        min_consecutive: 최소 N연속 hit 필터 (기본 3)
        limit: 페이지 크기 (기본 100)
        offset: 페이지 오프셋 (기본 0)

    Returns:
        {
            "results": [
                {
                    "variable_value": int,
                    "max_consecutive": int,
                    "hit_count": int,
                    "avg_gap_rounds": float,
                    "total_evaluated": int,
                    "target_numbers": list[int],
                },
                ...
            ],
            "total": int,
        }
    """
    supabase = get_client()

    # 1. Job 상태 확인
    job_response = (
        supabase.table("formula_sweep_jobs")
        .select("status")
        .eq("id", job_id)
        .single()
        .execute()
    )

    if not job_response.data:
        raise HTTPException(status_code=404, detail="Job not found")

    if job_response.data["status"] != "complete":
        return {"results": [], "total": 0}

    # 2. 결과 조회 (필터 + 페이징)
    query = (
        supabase.table("formula_sweep_results")
        .select("*", count="exact")
        .eq("job_id", job_id)
        .gte("max_consecutive", min_consecutive)
        .order("max_consecutive", desc=True)
        .order("hit_count", desc=True)
        .range(offset, offset + limit - 1)
    )

    response = query.execute()

    results = []
    for row in response.data:
        results.append(
            {
                "variable_value": row["variable_value"],
                "target_numbers": row.get("target_numbers", []),
                "max_consecutive": row["max_consecutive"],
                "hit_count": row["hit_count"],
                "avg_gap_rounds": row["avg_gap_rounds"],
                "total_evaluated": row.get("total_evaluated", 0),
            }
        )

    total_count = response.count if response.count is not None else len(results)

    return {"results": results, "total": total_count}


@router.get("/{job_id}/results/{variable_value}/history")
async def get_history(job_id: str, variable_value: int):
    """
    단일 변수값 과거 통계 상세.

    Returns:
        {
            "variable_value": int,
            "target_numbers": list[int],
            "max_consecutive": int,
            "hit_count": int,
            "avg_gap_rounds": float,
            "total_evaluated": int,
            "history": [
                {
                    "round": int,
                    "targets": list[int],
                    "hit_count": int,
                    "bonus_hit": bool,
                    "next_numbers": list[int],
                    "next_bonus": int | None,
                },
                ...
            ],
        }
    """
    supabase = get_client()

    response = (
        supabase.table("formula_sweep_results")
        .select("*")
        .eq("job_id", job_id)
        .eq("variable_value", variable_value)
        .single()
        .execute()
    )

    if not response.data:
        raise HTTPException(
            status_code=404, detail="Result not found for variable_value"
        )

    row = response.data
    history = row.get("history", [])

    return {
        "variable_value": row["variable_value"],
        "target_numbers": row.get("target_numbers", []),
        "max_consecutive": row["max_consecutive"],
        "hit_count": row["hit_count"],
        "avg_gap_rounds": row["avg_gap_rounds"],
        "total_evaluated": row.get("total_evaluated", 0),
        "history": history,
    }


# ─────────────────────────────────────────────────────────────────
# Background 실행
# ─────────────────────────────────────────────────────────────────


async def _execute_sweep(job_id: str):
    """Background sweep 실행 (ThreadPoolExecutor / asyncio)"""
    supabase = get_client()

    try:
        # 1. status = running
        supabase.table("formula_sweep_jobs").update(
            {"status": "running", "started_at": datetime.utcnow().isoformat()}
        ).eq("id", job_id).execute()

        # 2. job 정보 로드
        job_response = (
            supabase.table("formula_sweep_jobs")
            .select("*")
            .eq("id", job_id)
            .single()
            .execute()
        )

        if not job_response.data:
            raise Exception("Job not found")

        job = job_response.data

        # 3. FormulaV5Multi 파싱
        formula = FormulaV5Multi(**job["formula"])
        variable_paths = [VariablePath(**p) for p in job["variable_paths"]]
        criteria = SweepCriteria(**job["criteria"])

        # 4. draws 로드 (lotto_draws)
        draws_response = (
            supabase.table("lotto_draws")
            .select("*")
            .order("round", desc=True)
            .execute()
        )

        draws = draws_response.data

        # 5. eval_rounds 처리
        eval_rounds = job.get("eval_rounds")
        if eval_rounds is None:
            eval_rounds = [d.get("round") or d.get("drawNo") for d in draws]

        # 6. FormulaSweepEngine 생성
        engine = FormulaSweepEngine(formula, variable_paths, draws, max_ball=45)

        # 7. 진행 콜백 (progress 업데이트)
        start_time = time.time()

        def progress_callback(current: int, total: int, var_value: int):
            elapsed = time.time() - start_time
            eta_seconds = (
                (elapsed / current) * (total - current) if current > 0 else None
            )

            supabase.table("formula_sweep_jobs").update(
                {
                    "progress": {
                        "current": current,
                        "total": total,
                        "eta_seconds": eta_seconds,
                    },
                }
            ).eq("id", job_id).execute()

        # 8. Sweep 실행
        var_range = range(
            job["variable_range"]["min"],
            job["variable_range"]["max"] + 1,
            job["variable_range"]["step"],
        )

        results: List[SweepResult] = engine.sweep(
            var_range=var_range,
            criteria=criteria,
            eval_rounds=eval_rounds,
            progress_callback=progress_callback,
        )

        # 9. 결과 → formula_sweep_results 일괄 INSERT
        result_rows = []
        for r in results:
            # history를 dict로 변환
            history_dicts = [
                {
                    "round": h.round,
                    "targets": h.targets,
                    "hit_count": h.hit_count,
                    "bonus_hit": h.bonus_hit,
                    "next_numbers": h.next_numbers,
                    "next_bonus": h.next_bonus,
                }
                for h in r.history
            ]

            result_rows.append(
                {
                    "job_id": job_id,
                    "variable_value": r.variable_value,
                    "target_numbers": r.target_numbers,
                    "max_consecutive": r.max_consecutive,
                    "avg_gap_rounds": r.avg_gap_rounds,
                    "hit_count": r.hit_count,
                    "total_evaluated": r.total_evaluated,
                    "history": history_dicts,
                }
            )

        if result_rows:
            supabase.table("formula_sweep_results").insert(result_rows).execute()

        # 10. status = complete
        supabase.table("formula_sweep_jobs").update(
            {"status": "complete", "completed_at": datetime.utcnow().isoformat()}
        ).eq("id", job_id).execute()

    except Exception as e:
        # 실패 시 status = failed
        supabase.table("formula_sweep_jobs").update(
            {
                "status": "failed",
                "completed_at": datetime.utcnow().isoformat(),
                "error_message": str(e),
            }
        ).eq("id", job_id).execute()
        raise
