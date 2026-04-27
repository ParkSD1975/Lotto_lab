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
