"""
[Stage 1-4-D-2-fix-37] DB의 NULL evidence_text를 LLM 재호출로 채우기.

prompt가 강화되어 한국어 자연 문장만 출력. 후처리도 강화됨.
"""
import os
import sys
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.supabase_client import get_client
from chains.explain_chain import explain_number
from services.evidence_builder import extract_final_answer
import re


async def refill(target_round: int = 1222):
    client = get_client()
    res = client.table("weekly_number_xai") \
        .select("number, evidence_text") \
        .eq("target_round", target_round) \
        .execute()

    null_nums = [r["number"] for r in (res.data or []) if not r.get("evidence_text")]
    print(f"[fix-37] {target_round}회차 NULL 번호: {len(null_nums)}개 — {null_nums}")

    sem = asyncio.Semaphore(2)

    async def _one(n):
        async with sem:
            for attempt in range(2):  # 2회 재시도
                try:
                    text = await explain_number(
                        number=n,
                        user_query="이 번호에 대한 심층 분석을 해줘",
                        target_round=target_round,
                    )
                    if not text or text.startswith("죄송"):
                        continue
                    cleaned = extract_final_answer(text)
                    ko = len(re.findall(r'[가-힣]', cleaned or ""))
                    if ko >= 50:
                        client.table("weekly_number_xai") \
                            .update({"evidence_text": cleaned}) \
                            .eq("target_round", target_round) \
                            .eq("number", n) \
                            .execute()
                        print(f"  [{n:2d}] OK ({len(cleaned)}자, 시도 {attempt+1}): {cleaned[:80]}...")
                        return
                    else:
                        print(f"  [{n:2d}] 시도 {attempt+1} 한국어 부족({ko}자), 재시도")
                except Exception as e:
                    print(f"  [{n:2d}] 시도 {attempt+1} 오류: {e}")
            print(f"  [{n:2d}] FAIL — 한국어 답변 미생성")

    await asyncio.gather(*[_one(n) for n in null_nums])
    print("\n[fix-37] 재실행 완료")


if __name__ == "__main__":
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 1222
    asyncio.run(refill(target))
