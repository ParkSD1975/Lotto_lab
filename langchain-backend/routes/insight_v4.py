"""insight_v4.py — Master Plan Stage 5 v3 컴포넌트 backend.

deep_insight_panel_v3.js가 호출하는 단일 endpoint를 제공한다:
    GET /api/v4/insight/{indicator}

응답 구조 — v3.js의 render 함수가 기대하는 형식:
    {
      "indicator": str,
      "target_round": int,
      "consensus_strength": "강|중|약",
      "global_confidence": float (0~1),
      "pillars": {"ens","flt","sta","cns"} (각 0~1),
      "recommendations": [{number, score, narrative_seed, memo_forced, xai}],
      "exclusions": [{number, score, exclude_reason_label, force_exclude, xai}],
      "narrative": {"flow", "trend", "recommendation"},
      "timeseries": {"x": [...], "y": [...]}
    }

읽기 전용. weekly_* 테이블 + filter_stats ml_recommendation에서 indicator별로 조립.
"""

from __future__ import annotations

import traceback
from typing import Any, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from db.supabase_client import get_client


router = APIRouter(prefix="/api/v4", tags=["insight-v4"])


# 22 indicator allowlist (deep_insight_panel_v3.js INDICATOR_ACTIVE_MODELS와 동기화)
ALLOWED_INDICATORS = {
    "total_sum", "tail_sum", "ac_value",
    "low_high", "odd_even",
    "carryover", "consecutive_number", "neighbor_number",
    "tail_digit", "number_range", "magic_square", "lotto_paper",
    "multiple",
    "prime_number", "composite_number",
    "triangular_number", "square_number", "twin_number",
    "missing", "hot_cold", "regression",
    "custom_analysis",
}

# indicator → filter_stats key 매핑
INDICATOR_FILTER_KEY = {
    "total_sum": "total_sum",
    "tail_sum": "tail_sum",
    "ac_value": "ac_value",
    "low_high": "low_high",
    "odd_even": "odd_even",
    "carryover": "carryover",
    "consecutive_number": "consecutive",
    "neighbor_number": "neighbor_count",
    "tail_digit": "endings_distribution",
    "number_range": "decade_distribution",
    "magic_square": "zone_pattern",
    "lotto_paper": "zone_pattern",
    "multiple": "multiple_3",
    "prime_number": "prime_count",
    "composite_number": "composite_count",
    "triangular_number": "triangular_count",
    "square_number": "square_count",
    "twin_number": "twin_count",
    "missing": "missing_group",
    "hot_cold": "hot_cold",
    "regression": "regression_distribution",
}


# ────── helper ──────


def _ok(data: dict) -> JSONResponse:
    return JSONResponse({"success": True, **data})


def _err(msg: str, status: int = 500) -> JSONResponse:
    return JSONResponse({"success": False, "error": msg}, status_code=status)


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _latest_round(client) -> int:
    """최신 weekly_predictions 회차."""
    try:
        res = client.table("weekly_predictions") \
            .select("target_round") \
            .order("target_round", desc=True) \
            .limit(1).execute()
        return int(res.data[0]["target_round"]) if res.data else 0
    except Exception:
        return 0


def _consensus_label(std_rank_avg: float) -> str:
    """Pillar 4 std_rank 평균 → 강/중/약."""
    if std_rank_avg < 3.0:
        return "강"
    if std_rank_avg < 7.0:
        return "중"
    return "약"


# ────── 메인 endpoint ──────


@router.get("/insight/{indicator}")
async def get_insight(indicator: str):
    """22 분석 페이지 v3 컴포넌트의 단일 백엔드 endpoint.

    Stage 5-B 산출. indicator → 4 Pillar + 추천/제외 + narrative + 시계열 통합.
    실시간 딥러닝 X — weekly_* 테이블 읽기만.
    """
    if indicator not in ALLOWED_INDICATORS:
        return _err(f"unknown indicator: {indicator}", status=400)

    try:
        client = get_client()
        target_round = _latest_round(client)
        if not target_round:
            return _ok(_placeholder_response(indicator, target_round=0))

        payload = _build_payload(client, indicator, target_round)
        return _ok(payload)
    except Exception as e:
        traceback.print_exc()
        # Graceful fallback — placeholder
        return _ok(_placeholder_response(indicator, target_round=0, error=str(e)))


def _build_payload(client, indicator: str, target_round: int) -> dict:
    """weekly_* 테이블 + filter_stats에서 v3 응답 조립."""

    # 1. weekly_predictions / weekly_recommendations
    rec_data = []
    exc_data = []
    pillars = {"ens": 0.5, "flt": 0.5, "sta": 0.5, "cns": 0.5}
    consensus_strength = "중"
    global_confidence = 0.0

    try:
        res = client.table("weekly_recommendations") \
            .select("*") \
            .eq("target_round", target_round) \
            .execute()
        rows = res.data or []
        rec_rows = [r for r in rows if r.get("type") == "recommend"][:5]
        exc_rows = [r for r in rows if r.get("type") == "exclude"][:10]

        for r in rec_rows:
            rec_data.append({
                "number": int(r.get("number", 0)),
                "score": _safe_float(r.get("score"), 0.0),
                "narrative_seed": r.get("narrative_seed") or r.get("rationale") or "",
                "memo_forced": bool(r.get("memo_forced", False)),
                "xai": r.get("xai_payload") or {},
            })

        for r in exc_rows:
            reason = r.get("exclude_reason") or "pillar_score_low"
            exc_data.append({
                "number": int(r.get("number", 0)),
                "score": _safe_float(r.get("score"), 0.0),
                "exclude_reason": reason,
                "exclude_reason_label": _reason_label(reason),
                "force_exclude": bool(r.get("force_exclude", False)),
                "xai": r.get("xai_payload") or {},
            })
    except Exception as e:
        print(f"[insight_v4] weekly_recommendations fail: {e}")

    # 2. Pillar 가중치 (saved_models/pillar_meta_weights.json 우선, fallback uniform)
    pillars = _load_pillar_weights() or pillars

    # 3. Pillar 4 합의 강도 (consensus_metrics 평균 std_rank)
    try:
        cons_res = client.table("weekly_consensus_metrics") \
            .select("std_rank_avg, agreement_strength") \
            .eq("target_round", target_round) \
            .limit(1).execute()
        if cons_res.data:
            row = cons_res.data[0]
            consensus_strength = row.get("agreement_strength") \
                or _consensus_label(_safe_float(row.get("std_rank_avg"), 5.0))
            global_confidence = max(0.0, min(1.0,
                1.0 - _safe_float(row.get("std_rank_avg"), 5.0) / 22.0))
    except Exception:
        pass

    # 4. filter_stats ml_recommendation (해당 indicator)
    filter_key = INDICATOR_FILTER_KEY.get(indicator, indicator)
    ml_rec = None
    timeseries = {"x": [], "y": []}
    narrative = {"flow": "", "trend": "", "recommendation": ""}

    try:
        fs_res = client.table("weekly_filter_stats") \
            .select("filter_key, ml_recommendation, stats, timeseries") \
            .eq("target_round", target_round) \
            .eq("filter_key", filter_key) \
            .limit(1).execute()
        if fs_res.data:
            fs_row = fs_res.data[0]
            ml_rec = fs_row.get("ml_recommendation") or {}
            ts = fs_row.get("timeseries")
            if isinstance(ts, dict):
                timeseries = {
                    "x": ts.get("x") or [],
                    "y": ts.get("y") or [],
                }
            # narrative_seed 추출
            if ml_rec:
                narrative_text = ml_rec.get("narrative", "")
                narrative = _split_narrative(narrative_text)
    except Exception as e:
        print(f"[insight_v4] weekly_filter_stats fail: {e}")

    return {
        "indicator": indicator,
        "target_round": target_round,
        "consensus_strength": consensus_strength,
        "global_confidence": global_confidence,
        "pillars": pillars,
        "recommendations": rec_data,
        "exclusions": exc_data,
        "narrative": narrative,
        "timeseries": timeseries,
        "ml_recommendation": ml_rec,
    }


def _placeholder_response(indicator: str, target_round: int = 0, error: Optional[str] = None) -> dict:
    """데이터 없을 때 안전 fallback (v3 컴포넌트가 그래도 렌더 가능)."""
    out = {
        "indicator": indicator,
        "target_round": target_round,
        "consensus_strength": "중",
        "global_confidence": 0.0,
        "pillars": {"ens": 0.5, "flt": 0.5, "sta": 0.5, "cns": 0.5},
        "recommendations": [],
        "exclusions": [],
        "narrative": {
            "flow": "분석 데이터 준비 중입니다.",
            "trend": "주간 파이프라인 실행 후 갱신됩니다.",
            "recommendation": "최신 회차 분석을 기다려주세요.",
        },
        "timeseries": {"x": [], "y": []},
    }
    if error:
        out["error_hint"] = error
    return out


# ────── helper subroutines ──────


def _load_pillar_weights() -> Optional[dict]:
    """saved_models/pillar_meta_weights.json 에서 4 Pillar 가중치."""
    import json
    import os
    import config

    path = getattr(config, "PILLAR_META_LEARNER_PATH", None)
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        weights = data.get("pillar_weights") or data.get("weights") or {}
        # 키 정규화
        return {
            "ens": _safe_float(weights.get("pillar_1") or weights.get("ens"), 0.25),
            "flt": _safe_float(weights.get("pillar_2") or weights.get("flt"), 0.25),
            "sta": _safe_float(weights.get("pillar_3") or weights.get("sta"), 0.25),
            "cns": _safe_float(weights.get("pillar_4") or weights.get("cns"), 0.25),
        }
    except Exception:
        return None


def _reason_label(reason: str) -> str:
    """exclude_reason → 한국어 라벨."""
    labels = {
        "memo": "전문가 메모",
        "regression_consecutive": "회귀 4연번",
        "recent_4_consecutive": "1회귀 4연번",
        "dead_carryover_lines": "데드 라인",
        "pillar_score_low": "Pillar 점수 미달",
    }
    for prefix, label in labels.items():
        if reason.startswith(prefix):
            return label
    return reason


def _split_narrative(text: str) -> dict:
    """단일 narrative 텍스트 → {flow, trend, recommendation} 분할.

    형식 자유. 줄바꿈/문장 단위로 분할 시도, 최소 한 문장은 recommendation에.
    """
    if not text:
        return {"flow": "", "trend": "", "recommendation": ""}
    parts = [s.strip() for s in str(text).split(".") if s.strip()]
    if len(parts) >= 3:
        return {"flow": parts[0] + ".", "trend": parts[1] + ".", "recommendation": ". ".join(parts[2:]) + "."}
    if len(parts) == 2:
        return {"flow": parts[0] + ".", "trend": "", "recommendation": parts[1] + "."}
    return {"flow": "", "trend": "", "recommendation": parts[0] + "." if parts else ""}
