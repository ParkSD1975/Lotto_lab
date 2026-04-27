import json
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.output_parsers import StrOutputParser
import config

SYSTEM_MSG = (
    "You are a JSON-only output engine. "
    "Your response MUST be a single valid JSON array. "
    "Do NOT output any text, explanation, markdown, or code blocks — only the raw JSON array."
)

HUMAN_TEMPLATE = """아래 로또 AI 추천 조합 통계를 분석하여 각 필터의 최적 설정값을 JSON 배열로 반환하세요.

## AI 추천 조합 ({combo_count}게임)
{combinations_text}

## 필터별 통계
{filter_stats}

## 출력 규칙
- 반드시 아래 형식의 JSON 배열만 출력하세요. 다른 텍스트, 설명, 마크다운 일절 금지.
- 숫자는 위 통계 데이터 기반으로 작성. evidence는 한국어 1문장, 수치 포함.

[
  {{"filter": "총합", "min": 숫자, "max": 숫자, "evidence": "근거"}},
  {{"filter": "홀짝비율", "pattern": "홀N짝M", "evidence": "근거"}},
  {{"filter": "저고비율", "pattern": "저N고M", "evidence": "근거"}},
  {{"filter": "AC값", "min": 숫자, "max": 숫자, "evidence": "근거"}},
  {{"filter": "끝수합", "min": 숫자, "max": 숫자, "evidence": "근거"}},
  {{"filter": "연속번호", "max": 숫자, "evidence": "근거"}},
  {{"filter": "이월수", "min": 숫자, "max": 숫자, "evidence": "근거"}},
  {{"filter": "소수개수", "min": 숫자, "max": 숫자, "evidence": "근거"}}
]"""


PRIMES = {2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43}


def compute_filter_stats(combinations: list) -> str:
    """조합 리스트에서 필터별 통계 계산"""
    sums, odds, highs, acs, tail_sums, consecs, prime_counts = [], [], [], [], [], [], []

    for combo in combinations:
        nums = sorted(combo.get("numbers", []))
        if len(nums) < 6:
            continue

        sums.append(sum(nums))
        odds.append(sum(1 for n in nums if n % 2 != 0))
        highs.append(sum(1 for n in nums if n >= 24))

        # AC값
        diffs = set()
        for i in range(len(nums)):
            for j in range(i + 1, len(nums)):
                diffs.add(abs(nums[i] - nums[j]))
        acs.append(len(diffs) - (len(nums) - 1))

        # 끝수합
        tail_sums.append(sum(n % 10 for n in nums))

        # 연속번호 최대 길이
        max_c, cur = 0, 1
        for i in range(1, len(nums)):
            if nums[i] == nums[i - 1] + 1:
                cur += 1
                max_c = max(max_c, cur)
            else:
                cur = 1
        consecs.append(max_c if max_c > 1 else 0)

        # 소수 개수
        prime_counts.append(sum(1 for n in nums if n in PRIMES))

    def s(arr, name):
        if not arr:
            return f"{name}: 데이터 없음"
        return f"{name}: 최소 {min(arr)}, 최대 {max(arr)}, 평균 {sum(arr)/len(arr):.1f}"

    # 홀짝 최빈
    od = {}
    for o in odds:
        k = f"홀{o}짝{6-o}"
        od[k] = od.get(k, 0) + 1
    most_odd = max(od, key=od.get) if od else "홀3짝3"
    od_str = ", ".join(f"{k}({v}회)" for k, v in sorted(od.items(), key=lambda x: -x[1])[:3])

    # 저고 최빈
    hd = {}
    for h in highs:
        k = f"저{6-h}고{h}"
        hd[k] = hd.get(k, 0) + 1
    most_high = max(hd, key=hd.get) if hd else "저3고3"
    hd_str = ", ".join(f"{k}({v}회)" for k, v in sorted(hd.items(), key=lambda x: -x[1])[:3])

    return (
        f"{s(sums, '총합')}\n"
        f"홀짝비율 분포: {od_str} → 최빈: {most_odd}\n"
        f"저고비율 분포: {hd_str} → 최빈: {most_high}\n"
        f"{s(acs, 'AC값')}\n"
        f"{s(tail_sums, '끝수합')}\n"
        f"연속번호: 최대 {max(consecs) if consecs else 0}개 연속, 평균 {sum(consecs)/len(consecs):.1f}개\n"
        f"{s(prime_counts, '소수개수')}"
    )


async def run_llm_filter(combinations: list):
    """LLM으로 필터 추천 생성. 반환값: (recommendations: list, error: str|None)"""
    try:
        # 조합 텍스트
        lines = []
        for i, combo in enumerate(combinations[:10]):
            nums = combo.get("numbers", [])
            score = combo.get("score", 0)
            lines.append(f"  조합{i+1}: {nums}  (점수: {score:.4f})")
        combinations_text = "\n".join(lines)

        filter_stats = compute_filter_stats(combinations)

        print(f"[LLM Filter] model={config.LLM_MODEL}, api_key={'set' if config.GOOGLE_API_KEY else 'MISSING(env fallback)'}")

        llm_kwargs = {
            "model": config.LLM_MODEL,
            "temperature": 0.1,
        }
        if config.GOOGLE_API_KEY:
            llm_kwargs["google_api_key"] = config.GOOGLE_API_KEY

        # response_mime_type으로 JSON 강제 (지원 모델에서만 동작, 미지원 시 무시됨)
        try:
            llm = ChatGoogleGenerativeAI(**llm_kwargs, model_kwargs={"response_mime_type": "application/json"})
        except Exception:
            llm = ChatGoogleGenerativeAI(**llm_kwargs)

        # ChatPromptTemplate: system(JSON 전용) + human(데이터)
        prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_MSG),
            ("human", HUMAN_TEMPLATE),
        ])

        chain = prompt | llm | StrOutputParser()

        result = await chain.ainvoke({
            "combo_count": len(combinations),
            "combinations_text": combinations_text,
            "filter_stats": filter_stats,
        })

        print(f"[LLM Filter] Raw result (len={len(result)}): {result[:300]}")

        if not result or not result.strip():
            return [], f"LLM이 빈 응답을 반환했습니다. model={config.LLM_MODEL}"

        # JSON 추출 - dict 배열을 찾을 때까지 모든 '[' 위치 시도
        cleaned = result.replace("```json", "").replace("```", "").strip()
        decoder = json.JSONDecoder()

        for i, ch in enumerate(cleaned):
            if ch == "[":
                try:
                    obj, _ = decoder.raw_decode(cleaned, i)
                    if isinstance(obj, list) and len(obj) > 0 and isinstance(obj[0], dict):
                        return obj, None
                except json.JSONDecodeError:
                    continue

        try:
            return json.loads(cleaned), None
        except json.JSONDecodeError:
            return [], f"JSON 파싱 실패. LLM 응답: {result[:300]}"

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(f"[LLM Filter] Error: {e}\n{tb}")
        return [], str(e)
