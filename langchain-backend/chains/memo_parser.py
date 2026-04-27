import json
import logging
from typing import Dict, Any, List
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate
from config import GOOGLE_API_KEY, LLM_MODEL
import config

logger = logging.getLogger(__name__)

class MemoParser:
    def __init__(self):
        llm_kwargs = {"model": LLM_MODEL, "temperature": 0.1}
        if GOOGLE_API_KEY:
            llm_kwargs["google_api_key"] = GOOGLE_API_KEY
        self.llm = ChatGoogleGenerativeAI(**llm_kwargs)
        
        self.prompt = PromptTemplate(
            input_variables=["memo"],
            template="""
# 역할: 로또 분석 전문가 메모 해석기
당신의 역할은 사용자가 작성한 자연어 메모를 분석하여, 로또 번호 가중치 조절을 위한 JSON 규칙으로 변환하는 것입니다.

# 규칙:
1. '제외' 또는 '빼라'는 번호는 'excluded_numbers' 리스트에 넣으세요.
2. '강세', '나온다', '유리'와 같은 범위(10번대, 20번대 등)는 'boost_ranges'에 넣으세요.
3. 범위는 다음과 같이 정의합니다:
   - "단번대": 1-10
   - "10번대": 11-20
   - "20번대": 21-30
   - "30번대": 31-40
   - "40번대": 41-45
4. 끝수(끝이 3인 경우 등)는 해당되는 모든 번호(3, 13, 23, 33, 43)를 찾아 리스트에 넣으세요.

# 출력 형식 (반드시 유효한 JSON만 출력):
{{
  "summary": "메모 내용 요약 (한 문장)",
  "excluded_numbers": [번호 리스트],
  "boost_ranges": [
    {{"range_name": "범위이름", "start": N, "end": M}}
  ],
  "fixed_numbers": [고정수 리스트]
}}

# 사용자 메모:
{memo}

# JSON 출력:
"""
        )
        self.chain = self.prompt | self.llm

    def parse(self, memo_text: str) -> Dict[str, Any]:
        if not memo_text:
            return {
                "summary": "메모 없음",
                "excluded_numbers": [],
                "boost_ranges": [],
                "fixed_numbers": []
            }
        
        try:
            response = self.chain.invoke({"memo": memo_text})
            # 마크다운 제거
            content = response.content.replace("```json", "").replace("```", "").strip()
            result = json.loads(content)
            return result
        except Exception as e:
            logger.error(f"메모 파싱 오류: {e}")
            return {
                "summary": "파싱 실패",
                "excluded_numbers": [],
                "boost_ranges": [],
                "fixed_numbers": []
            }

def parse_expert_memo(memo_text: str) -> Dict[str, Any]:
    parser = MemoParser()
    return parser.parse(memo_text)
