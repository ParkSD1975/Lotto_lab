"""번호별 narrative 생성 — Gemma 4 시그널/근거/결론 3섹션 합성.

Master Plan Stage 4-B. NumberXAIExplainer Layer 1 narrative seed를 받아
Gemma 4로 자연어 합성. LRU 캐시(U-4)로 중복 호출 방지.

출력 형식 (사용자 결정 #8):
{
  "number": int,
  "type": "recommend" | "exclude",
  "narrative": {
    "signal": str,    # 한 문장
    "rationale": str, # 한 문장
    "conclusion": str,# 한 문장
  }
}
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import OrderedDict
from typing import Optional

import config

PROMPT_PATH = os.path.join(os.path.dirname(__file__), "..", "prompts", "number_narrative_3section.txt")


# ────── LangChain LLM (lazy init) ──────

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
        print(f"[number_narrative] LLM init fail: {e}")
        return None


# ────── LRU 캐시 ──────


class _LRUCache:
    """가벼운 LRU. functools.lru_cache는 dict unhashable 입력 X."""

    def __init__(self, maxsize: int = 256):
        self.maxsize = maxsize
        self._d: OrderedDict = OrderedDict()

    def get(self, key: str):
        if key in self._d:
            self._d.move_to_end(key)
            return self._d[key]
        return None

    def set(self, key: str, value):
        if key in self._d:
            self._d.move_to_end(key)
        self._d[key] = value
        if len(self._d) > self.maxsize:
            self._d.popitem(last=False)

    def stats(self) -> dict:
        return {"size": len(self._d), "maxsize": self.maxsize}


_CACHE = _LRUCache(maxsize=512)


# ────── prompt ──────


def _load_prompt() -> str:
    try:
        with open(PROMPT_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def _format_prompt(template: str, evidence: dict) -> str:
    """단순 placeholder 치환 (LangChain PromptTemplate 우회 — 안정성 우선)."""
    out = template
    mapping = {
        "{number}": str(evidence.get("number", "?")),
        "{type}": str(evidence.get("type", "?")),
        "{pillar_1}": json.dumps(evidence.get("pillar_1") or {}, ensure_ascii=False),
        "{pillar_2}": json.dumps(evidence.get("pillar_2") or {}, ensure_ascii=False),
        "{pillar_3}": json.dumps(evidence.get("pillar_3") or {}, ensure_ascii=False),
        "{pillar_4}": json.dumps(evidence.get("pillar_4") or {}, ensure_ascii=False),
        "{auto_rule_reason}": str(evidence.get("auto_rule_reason", "없음")),
        "{memo_forced_inc}": str(evidence.get("memo_forced_inc", False)),
        "{memo_forced_exc}": str(evidence.get("memo_forced_exc", False)),
    }
    for k, v in mapping.items():
        out = out.replace(k, v)
    return out


def _cache_key(evidence: dict) -> str:
    norm = json.dumps(
        {
            "number": evidence.get("number"),
            "type": evidence.get("type"),
            "p1": evidence.get("pillar_1"),
            "p2": evidence.get("pillar_2"),
            "p3": evidence.get("pillar_3"),
            "p4": evidence.get("pillar_4"),
            "rule": evidence.get("auto_rule_reason"),
            "fi": evidence.get("memo_forced_inc"),
            "fe": evidence.get("memo_forced_exc"),
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.md5(norm.encode("utf-8")).hexdigest()


# ────── 응답 파싱 ──────


def _parse_3section(text: str) -> dict:
    """LLM 출력에서 시그널/근거/결론 3섹션 추출."""
    sec = {"signal": "", "rationale": "", "conclusion": ""}
    if not text:
        return sec

    # "시그널:", "근거:", "결론:" 키 매핑
    patterns = {
        "signal": r"시그널\s*[:：]\s*(.+?)(?=\n\s*(?:근거|결론)|$)",
        "rationale": r"근거\s*[:：]\s*(.+?)(?=\n\s*(?:시그널|결론)|$)",
        "conclusion": r"결론\s*[:：]\s*(.+?)(?=\n\s*(?:시그널|근거)|$)",
    }
    for key, pat in patterns.items():
        m = re.search(pat, text, re.DOTALL)
        if m:
            sec[key] = m.group(1).strip().split("\n")[0].strip()
    return sec


# ────── 메인 ──────


def generate_narrative(evidence: dict, fallback: bool = True) -> dict:
    """단일 번호 narrative 생성 (LRU 캐시 + LLM 호출 + 파싱)."""
    key = _cache_key(evidence)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    template = _load_prompt()
    if not template:
        if fallback:
            return _fallback_narrative(evidence)
        return {"signal": "", "rationale": "", "conclusion": "", "error": "prompt_missing"}

    full_prompt = _format_prompt(template, evidence)

    llm = _get_llm()
    if llm is None:
        if fallback:
            return _fallback_narrative(evidence)
        return {"signal": "", "rationale": "", "conclusion": "", "error": "llm_unavailable"}

    try:
        response = llm.invoke(full_prompt)
        text = getattr(response, "content", str(response))
        parsed = _parse_3section(text)
        out = {
            "number": evidence.get("number"),
            "type": evidence.get("type"),
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
        return {"signal": "", "rationale": "", "conclusion": "", "error": str(e)}


def _fallback_narrative(evidence: dict) -> dict:
    """LLM 미가용 시 evidence seed 기반 단순 narrative."""
    typ = evidence.get("type", "recommend")
    p4 = evidence.get("pillar_4") or {}
    p2 = evidence.get("pillar_2") or {}
    p3 = evidence.get("pillar_3") or {}
    rule = evidence.get("auto_rule_reason")
    forced_inc = evidence.get("memo_forced_inc")
    forced_exc = evidence.get("memo_forced_exc")

    # signal: top10_count 또는 ensemble 강조
    top10 = p4.get("top10_count", 0)
    bottom15 = p4.get("bottom15_count", 0)
    if forced_inc:
        signal = "전문가 메모로 강제 추천된 번호"
    elif forced_exc:
        signal = "전문가 메모로 강제 제외된 번호"
    elif top10 >= 5:
        signal = f"7 모델 중 {top10}개가 상위 10위로 추천 합의"
    elif bottom15 >= 5:
        signal = f"7 모델 중 {bottom15}개가 하위 15위로 제외 합의"
    else:
        signal = "Pillar 합산 점수 기반 후보"

    # rationale
    parts = []
    if p2.get("passed_filters"):
        parts.append(f"필터 {len(p2['passed_filters'])}개 통과")
    if p3.get("hotcold"):
        parts.append(f"핫콜드 {p3['hotcold']}")
    if p3.get("dormancy"):
        parts.append(f"미출 {p3['dormancy']}회")
    rationale = ", ".join(parts) + " 정합" if parts else "상세 신호 부족"

    # conclusion
    if typ == "recommend":
        conclusion = f"다음 회차 출현 가능성 높음 (Pillar 합의 {p4.get('agreement_strength', '보통')})"
    else:
        if rule:
            conclusion = f"미출현 가능성 높음 ({rule})"
        else:
            conclusion = "미출현 가능성 높음 (Pillar 다중 조건 미통과)"

    return {
        "number": evidence.get("number"),
        "type": typ,
        "narrative": {
            "signal": signal,
            "rationale": rationale,
            "conclusion": conclusion,
        },
        "fallback": True,
    }


def generate_batch(
    explanations: list[dict], fallback: bool = True
) -> list[dict]:
    """추천 5 + 제외 10 일괄 narrative 생성."""
    results = []
    for ex in explanations or []:
        try:
            seed = ex.get("layer_1_narrative", {}).get("evidence_full") or {}
            evidence = {
                "number": ex.get("number"),
                "type": ex.get("type"),
                "pillar_1": seed.get("pillar_1"),
                "pillar_2": seed.get("pillar_2"),
                "pillar_3": seed.get("pillar_3"),
                "pillar_4": seed.get("pillar_4"),
                "auto_rule_reason": seed.get("auto_rule_reason"),
                "memo_forced_inc": seed.get("memo_active") and ex.get("type") == "recommend",
                "memo_forced_exc": (ex.get("memo_signals") or {}).get("forced_exc", False),
            }
            results.append(generate_narrative(evidence, fallback=fallback))
        except Exception as e:
            results.append({"number": ex.get("number"), "error": str(e)})
    return results


def cache_stats() -> dict:
    return _CACHE.stats()


def main():
    """smoke — fallback 모드 검증."""
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--smoke", action="store_true")
    args = p.parse_args()

    if args.smoke:
        ev_rec = {
            "number": 23,
            "type": "recommend",
            "pillar_1": {"value": 0.62},
            "pillar_2": {"passed_filters": ["sum", "endings"]},
            "pillar_3": {"hotcold": "Warm", "dormancy": 12,
                         "regression_top3_active_N": [2, 8, 22]},
            "pillar_4": {"top10_count": 7, "agreement_strength": "강"},
            "auto_rule_reason": None,
            "memo_forced_inc": False,
            "memo_forced_exc": False,
        }
        out = generate_narrative(ev_rec, fallback=True)
        print("[number_narrative] smoke (recommend, fallback)")
        print(f"  number={out['number']} type={out['type']}")
        print(f"  signal: {out['narrative']['signal']}")
        print(f"  rationale: {out['narrative']['rationale']}")
        print(f"  conclusion: {out['narrative']['conclusion']}")

        ev_exc = {
            "number": 22,
            "type": "exclude",
            "pillar_4": {"bottom15_count": 6, "agreement_strength": "강"},
            "auto_rule_reason": "regression_consecutive_N12",
            "memo_forced_inc": False,
            "memo_forced_exc": False,
        }
        out2 = generate_narrative(ev_exc, fallback=True)
        print(f"\n[number_narrative] smoke (exclude, auto rule)")
        print(f"  signal: {out2['narrative']['signal']}")
        print(f"  conclusion: {out2['narrative']['conclusion']}")

        print(f"\n[cache stats] {cache_stats()}")


if __name__ == "__main__":
    main()
