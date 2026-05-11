"""S-1: SLAMonitor 컨텍스트 매니저 + sla_history.

학습/추론 wall-time과 메모리 peak을 자동 측정·기록한다.
HF Spaces 무료 단계(RAM 15GB / 2 cores / timeout 120s) 한도 위협 감지용.

사용 예:
    >>> from pipeline.sla_monitor import SLAMonitor
    >>> with SLAMonitor("phase1_digit_predictor_train") as m:
    ...     train_predictor(...)
    >>> print(m.wall_time, m.mem_peak_mb)

기록:
    saved_models/sla_history.parquet (또는 jsonl fallback)
    각 row: {ts, tag, wall_time, mem_peak_mb, mem_peak_gb, status, sla_violation}
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any

import config

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False


def _history_path() -> str:
    return os.path.join(config.MODEL_DIR, getattr(config, "SLA_HISTORY_FILE",
                                                   "sla_history.parquet"))


def _jsonl_fallback_path() -> str:
    return os.path.join(config.MODEL_DIR, "sla_history.jsonl")


# ────────────────── SLA 한도 조회 ──────────────────


def get_sla_limits() -> dict:
    """config의 SLA_* 키를 dict로 반환."""
    return {
        "train_wall_time_max": getattr(config, "SLA_TRAIN_WALL_TIME_MAX", 86400),
        "infer_wall_time_max": getattr(config, "SLA_INFER_WALL_TIME_MAX", 30),
        "infer_mem_max_gb":    getattr(config, "SLA_INFER_MEM_MAX_GB", 12),
        "train_mem_max_gb":    getattr(config, "SLA_TRAIN_MEM_MAX_GB", 14),
        "api_timeout":         getattr(config, "SLA_API_TIMEOUT", 120),
    }


def check_violation(tag: str, wall_time: float, mem_peak_gb: float) -> dict:
    """tag에 따라 적절한 SLA 한도와 비교 → 위반 여부 dict.

    tag 규약:
        "train_*" 또는 "stage*_train" → 학습 한도 적용
        "infer_*" 또는 "predict_*"    → 추론 한도 적용
        그 외                         → 추론 한도 적용 (보수적)

    Returns:
        {wall_violation, mem_violation, limit_used: dict}
    """
    limits = get_sla_limits()
    is_train = tag.startswith("train_") or "_train" in tag
    if is_train:
        wall_lim = limits["train_wall_time_max"]
        mem_lim = limits["train_mem_max_gb"]
    else:
        wall_lim = limits["infer_wall_time_max"]
        mem_lim = limits["infer_mem_max_gb"]

    return {
        "wall_violation": wall_time > wall_lim,
        "mem_violation": mem_peak_gb > mem_lim,
        "wall_limit": wall_lim,
        "mem_limit_gb": mem_lim,
    }


# ────────────────── SLAMonitor 컨텍스트 매니저 ──────────────────


class SLAMonitor:
    """학습/추론 단위의 wall-time + 메모리 peak 측정.

    Args:
        tag: 식별 문자열 (예: "phase1_digit_predictor_train")
        log_to_history: True면 sla_history에 자동 기록 (기본 True)
        threshold_wall_seconds: 위반 alert 임계값 (None이면 config SLA_* 사용)

    속성 (with 블록 종료 후 사용 가능):
        wall_time:    float (seconds)
        mem_peak_mb:  float (MB)
        mem_peak_gb:  float (GB)
        violation:    {wall_violation, mem_violation, ...}
    """

    def __init__(self, tag: str, log_to_history: bool = True):
        self.tag = tag
        self.log_to_history = log_to_history
        self.wall_time: float = 0.0
        self.mem_peak_mb: float = 0.0
        self.mem_peak_gb: float = 0.0
        self.violation: dict = {}
        self.status: str = "pending"
        self._t0: float = 0.0
        self._mem0: int = 0

    def __enter__(self) -> "SLAMonitor":
        self._t0 = time.time()
        self._mem0 = self._current_rss()
        self.status = "running"
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.wall_time = time.time() - self._t0
        mem_now = self._current_rss()
        # 단일 측정점이지만 일관성 위해 max(0, end - start) 적용
        delta = max(0, mem_now - self._mem0)
        # peak으로 mem_now 자체를 사용 (process RSS는 monotonic 누적)
        self.mem_peak_mb = mem_now / (1024.0 * 1024.0) if mem_now > 0 else 0.0
        self.mem_peak_gb = self.mem_peak_mb / 1024.0
        self.status = "error" if exc_type is not None else "ok"

        self.violation = check_violation(self.tag, self.wall_time, self.mem_peak_gb)

        if self.log_to_history:
            try:
                log_sla(
                    tag=self.tag,
                    wall_time=self.wall_time,
                    mem_peak_mb=self.mem_peak_mb,
                    status=self.status,
                    violation=self.violation,
                )
            except Exception as e:
                print(f"  [SLAMonitor] history 기록 실패 (skip): {e}")

        # exception 전파
        return False

    @staticmethod
    def _current_rss() -> int:
        """현재 프로세스 RSS (bytes). psutil 없으면 0."""
        if not _HAS_PSUTIL:
            return 0
        try:
            return int(psutil.Process().memory_info().rss)
        except Exception:
            return 0


# ────────────────── 기록 ──────────────────


def log_sla(
    tag: str,
    wall_time: float,
    mem_peak_mb: float,
    status: str = "ok",
    violation: dict | None = None,
) -> None:
    """sla_history에 1 entry 추가.

    parquet 기본, pandas/pyarrow 미설치 시 jsonl로 fallback.
    """
    entry: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "tag": tag,
        "wall_time": float(wall_time),
        "mem_peak_mb": float(mem_peak_mb),
        "mem_peak_gb": float(mem_peak_mb / 1024.0) if mem_peak_mb else 0.0,
        "status": status,
        "wall_violation": bool(violation.get("wall_violation")) if violation else False,
        "mem_violation":  bool(violation.get("mem_violation"))  if violation else False,
    }

    # parquet 시도 (pandas + pyarrow 필요)
    try:
        import pandas as pd
        path = _history_path()
        new_df = pd.DataFrame([entry])
        if os.path.exists(path):
            existing = pd.read_parquet(path)
            df = pd.concat([existing, new_df], ignore_index=True)
        else:
            df = new_df
        df.to_parquet(path, index=False)
        return
    except Exception:
        pass

    # jsonl fallback
    path = _jsonl_fallback_path()
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_sla_history(limit: int | None = None) -> list[dict]:
    """sla_history 전체 또는 최근 limit개 entry 반환."""
    # parquet 우선
    parquet_path = _history_path()
    if os.path.exists(parquet_path):
        try:
            import pandas as pd
            df = pd.read_parquet(parquet_path)
            if limit:
                df = df.tail(limit)
            return df.to_dict(orient="records")
        except Exception:
            pass

    # jsonl fallback
    jsonl_path = _jsonl_fallback_path()
    if not os.path.exists(jsonl_path):
        return []
    rows = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    if limit:
        rows = rows[-limit:]
    return rows


# ────────────────── 11 base 모델별 SLA 통계 ──────────────────


def get_model_sla_stats(model_name: str, recent_n: int = 100) -> dict:
    """특정 11 base 모델의 최근 N회 SLA 통계 반환.

    Args:
        model_name: "xgboost", "cnn", "gnn", "markov", "autoencoder",
                    "catboost", "tabnet", "tft", "mhn", "bayesian_nn", "nbeats"
        recent_n: 최근 N개 entry

    Returns:
        {
            'count': int,
            'avg_wall_time': float (seconds),
            'max_wall_time': float,
            'avg_mem_mb': float,
            'max_mem_mb': float,
            'violation_count': int,
        }
    """
    history = read_sla_history(limit=1000)  # 최근 1000개 조회
    filtered = [
        h for h in history
        if model_name.lower() in h.get("tag", "").lower()
    ][-recent_n:]

    if not filtered:
        return {
            'count': 0,
            'avg_wall_time': 0,
            'max_wall_time': 0,
            'avg_mem_mb': 0,
            'max_mem_mb': 0,
            'violation_count': 0,
        }

    import numpy as np
    wall_times = [h.get("wall_time", 0) for h in filtered]
    mem_mbs = [h.get("mem_peak_mb", 0) for h in filtered]
    violations = sum(
        1 for h in filtered
        if h.get("wall_violation") or h.get("mem_violation")
    )

    return {
        'count': len(filtered),
        'avg_wall_time': float(np.mean(wall_times)),
        'max_wall_time': float(np.max(wall_times)),
        'avg_mem_mb': float(np.mean(mem_mbs)),
        'max_mem_mb': float(np.max(mem_mbs)),
        'violation_count': violations,
    }


# ────────────────── model_latency_log 테이블 동기화 ──────────────────


def sync_sla_to_latency_log(
    supabase_client=None,
    recent_n: int = 100,
    model_names: list | None = None,
) -> dict:
    """sla_history에서 11 base 모델별 최근 추론시간을 model_latency_log 테이블에 동기화.

    Args:
        supabase_client: Supabase 클라이언트 (None이면 get_client 호출)
        recent_n: 각 모델당 최근 N개 entry 조회
        model_names: 동기화 대상 모델 리스트 (None이면 11 base 전체)

    Returns:
        {success: bool, rows_inserted: int, models_synced: list, error: str?}

    Supabase 테이블 스키마 (실제):
        model_name (varchar, not null)
        operation (varchar, not null) — 'predict' 또는 'train'
        target_round (int, nullable)
        elapsed_ms (int, not null) — milliseconds
        memory_mb (float, nullable)
        threshold_ms (int, nullable)
        fallback_triggered (bool, default false)
        error_msg (text, nullable)
        created_at (timestamptz)
    """
    if supabase_client is None:
        try:
            from db.supabase_client import get_client
            supabase_client = get_client()
        except Exception as e:
            return {"success": False, "rows_inserted": 0, "error": f"supabase unavailable: {e}"}

    if model_names is None:
        model_names = [
            "xgboost", "catboost", "tabnet", "cnn", "gnn",
            "markov", "autoencoder", "tft", "mhn", "bayesian_nn", "nbeats"
        ]

    history = read_sla_history(limit=recent_n * len(model_names))
    if not history:
        return {"success": False, "rows_inserted": 0, "error": "no sla_history entries"}

    rows = []
    models_synced = []

    # [개선] predict + train 양쪽 다 적재 (검증 페이지 SLA 학습/추론 분리 지원)
    op_keywords = {
        "predict": ["infer", "predict"],
        "train":   ["train", "fit"],
    }

    for model_name in model_names:
        for op_label, keywords in op_keywords.items():
            # 모델별 + operation별 필터링 (tag에 모델명 + 키워드 포함)
            filtered = [
                h for h in history
                if model_name.lower() in h.get("tag", "").lower()
                and any(kw in h.get("tag", "").lower() for kw in keywords)
            ]
            if not filtered:
                continue

            # 최근 1개만 적재
            latest = filtered[-1]
            wall_time = float(latest.get("wall_time", 0))  # seconds
            mem_mb = float(latest.get("mem_peak_mb", 0))

            # [방어] sub-millisecond 추론(예: tft 0.0001s)은 int 변환 시 0이 됨 → 최소 1ms 보장
            elapsed_ms = max(1, int(round(wall_time * 1000))) if wall_time > 0 else 0
            rows.append({
                "model_name": model_name,
                "operation": op_label,
                "elapsed_ms": elapsed_ms,
                "memory_mb": round(mem_mb, 2) if mem_mb > 0 else None,
            })
            if model_name not in models_synced:
                models_synced.append(model_name)

    if not rows:
        return {"success": False, "rows_inserted": 0, "error": "no valid model entries"}

    try:
        # 일괄 INSERT
        supabase_client.table("model_latency_log").insert(rows).execute()
        return {"success": True, "rows_inserted": len(rows), "models_synced": models_synced}
    except Exception as e:
        return {"success": False, "rows_inserted": 0, "error": str(e)}
