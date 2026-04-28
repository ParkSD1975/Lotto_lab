"""페이지별 narrative 생성 — Gemma 4 흐름/추세/추천 3섹션.

Master Plan Stage 4-B. 각 분석 지표 페이지(22개)의 dlInsightContainer에 표시할
narrative를 Gemma 4로 합성. number_narrative.py와 동일 패턴 (LRU + fallback).
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Optional

import config

PROMPT_PATH = os.path.join(os.path.dirname(__file__), "..", "prompts", "page_narrative.txt")


# ────── LLM lazy init ──────

_LLM = None


def _get_llm():
    global _LLM
    if _LLM is not None:
        return _LLM
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        kwargs = {"model": config.LLM_MODEL, "temperature": 0.4}
        if config.GOOGLE_API_KEY:
            kwargs["google_api_key"] = config.GOOGLE_API_KEY
        _LLM = ChatGoogleGenerativeAI(**kwargs)
        return _LLM
    except Exception as e:
        print(f"[page_narrative] LLM init fail: {e}")
        return None


# ────── LRU ──────

from services.number_narrative import _LRUCache  # 동일 구현 재사용

_CACHE = _LRUCache(maxsize=128)


# ────── prompt ──────


def _load_prompt() -> str:
    try:
        with open(PROMPT_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def _format_prompt(template: str, evidence: dict) -> str:
    out = template
    mapping = {
        "{indicator_name}": str(evidence.get("indicator_name", "?")),
        "{recent_stats}": json.dumps(evidence.get("recent_stats") or {}, ensure_ascii=False),
        "{ml_prediction}": json.dumps(evidence.get("ml_prediction") or {}, ensure_ascii=False),
        "{nbeats}": json.dumps(evidence.get("nbeats") or {}, ensure_ascii=False),
        "{consensus}": str(evidence.get("consensus", "보통")),
    }
    for k, v in mapping.items():
        out = out.replace(k, v)
    return out


def _cache_key(evidence: dict) -> str:
    norm = json.dumps(
        {
            "ind": evidence.get("indicator_name"),
            "rs": evidence.get("recent_stats"),
            "ml": evidence.get("ml_prediction"),
            "nb": evidence.get("nbeats"),
            "cs": evidence.get("consensus"),
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.md5(norm.encode("utf-8")).hexdigest()


# ────── 파싱 ──────


def _parse_3section(text: str) -> dict:
    import re
    sec = {"flow": "", "trend": "", "recommendation": ""}
    if not text:
        return sec
    patterns = {
        "flow": r"흐름\s*[:：]\s*(.+?)(?=\n\s*(?:추세|추천)|$)",
        "trend": r"추세\s*[:：]\s*(.+?)(?=\n\s*(?:흐름|추천)|$)",
        "recommendation": r"추천\s*[:：]\s*(.+?)(?=\n\s*(?:흐름|추세)|$)",
    }
    for key, pat in patterns.items():
        m = re.search(pat, text, re.DOTALL)
        if m:
            content = m.group(1).strip()
            sec[key] = " ".join(content.split("\n")[:2]).strip()
    return sec


# ────── 메인 ──────


def generate_page_narrative(evidence: dict, fallback: bool = True) -> dict:
    """페이지 narrative 생성 (흐름/추세/추천)."""
    key = _cache_key(evidence)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    template = _load_prompt()
    if not template:
        if fallback:
            return _fallback_narrative(evidence)
        return {"flow": "", "trend": "", "recommendation": "", "error": "prompt_missing"}

    full_prompt = _format_prompt(template, evidence)
    llm = _get_llm()
    if llm is None:
        if fallback:
            return _fallback_narrative(evidence)
        return {"flow": "", "trend": "", "recommendation": "", "error": "llm_unavailable"}

    try:
        response = llm.invoke(full_prompt)
        text = getattr(response, "content", str(response))
        parsed = _parse_3section(text)
        out = {
            "indicator_name": evidence.get("indicator_name"),
            "narrative": parsed,
            "raw": text,
            "from_cache": False,
        }
        _CACHE.set(key, out)
        return out
    except Exception as e:
        if fallback:
            fb = _fallback_narrative(evidence)
            fb["llm_error"] = str(e)
            return fb
        return {"flow": "", "trend": "", "recommendation": "", "error": str(e)}


def _fallback_narrative(evidence: dict) -> dict:
    """LLM 미가용 시 evidence 기반 단순 narrative."""
    indicator = evidence.get("indicator_name", "지표")
    rs = evidence.get("recent_stats") or {}
    ml = evidence.get("ml_prediction") or {}
    nb = evidence.get("nbeats") or {}
    cons = evidence.get("consensus", "보통")

    # 흐름
    rolling_mean = rs.get("rolling_mean_10") or rs.get("rolling_mean") or rs.get("mean")
    rolling_std = rs.get("rolling_std_10") or rs.get("rolling_std") or rs.get("std")
    if rolling_mean is not None and rolling_std is not None:
        flow = f"최근 10회차 {indicator} 평균 {rolling_mean:.1f}, 표준편차 {rolling_std:.1f}"
    else:
        flow = f"최근 회차 {indicator} 통계 일반 수준"

    # 추세
    trend_parts = []
    if "trend_pattern" in rs:
        trend_parts.append(f"추세 {rs['trend_pattern']}")
    if "volatility_ratio" in rs:
        vr = rs["volatility_ratio"]
        if vr > 1.2:
            trend_parts.append(f"단기 변동성 {vr:.1f}배 증가")
        elif vr < 0.8:
            trend_parts.append(f"단기 변동성 {vr:.1f}배 감소")
    if not trend_parts:
        trend_parts.append("추세 안정")
    trend = ", ".join(trend_parts)

    # 추천
    q10 = ml.get("q10")
    q90 = ml.get("q90")
    q50 = ml.get("q50")
    if q10 is not None and q90 is not None:
        recommendation = f"다음 회차 {indicator} 권장 범위 {q10:.1f}~{q90:.1f} (중앙 {q50:.1f})"
    elif "narrative" in ml:
        recommendation = str(ml["narrative"])
    else:
        recommendation = f"다음 회차 {indicator} 평균 수준 예상 (Pillar 합의 {cons})"

    return {
        "indicator_name": indicator,
        "narrative": {
            "flow": flow,
            "trend": trend,
            "recommendation": recommendation,
        },
        "fallback": True,
    }


def cache_stats() -> dict:
    return _CACHE.stats()


def main():
    """smoke — fallback 모드 검증."""
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--smoke", action="store_true")
    args = p.parse_args()

    if args.smoke:
        ev = {
            "indicator_name": "총합",
            "recent_stats": {
                "rolling_mean_10": 138.5,
                "rolling_std_10": 28.3,
                "trend_pattern": "mild_up",
                "volatility_ratio": 1.3,
            },
            "ml_prediction": {"q10": 110.0, "q50": 138.0, "q90": 168.0},
            "nbeats": {"trend": "+5", "seasonality": "weekly"},
            "consensus": "강",
        }
        out = generate_page_narrative(ev, fallback=True)
        print("[page_narrative] smoke (fallback)")
        print(f"  indicator: {out['indicator_name']}")
        print(f"  flow: {out['narrative']['flow']}")
        print(f"  trend: {out['narrative']['trend']}")
        print(f"  recommendation: {out['narrative']['recommendation']}")
        print(f"\n[cache stats] {cache_stats()}")


if __name__ == "__main__":
    main()
