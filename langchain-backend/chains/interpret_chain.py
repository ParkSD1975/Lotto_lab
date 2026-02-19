import json
from langchain.prompts import PromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.schema.output_parser import StrOutputParser
import config

# AI가 이해해야 할 시스템의 명령어 구조 정의
INTERPRET_PROMPT = """
당신은 로또 분석 시스템의 '자연어 명령 해석기'입니다.
사용자의 입력을 분석하여, 우리 시스템이 이해할 수 있는 **JSON 포맷**으로 변환해주세요.

---
**[분석 가능한 의도(Intent) 및 파라미터 구조]**

1. **static_numbers (특정 번호 분석)**
   - 예: "1, 2, 3번 분석해줘", "내가 찍은 번호 5, 10, 15"
   - JSON: {{ "intent": "static_numbers", "params": {{ "target_numbers": [1, 2, 3] }} }}

2. **dynamic_formula (동적 수식/회귀 분석)**
   - 예: "전회차 +1 패턴", "2회귀 전수조사", "이월수 분석"
   - JSON: {{ "intent": "dynamic_formula", "params": {{ "rules": {{ "formula": "prev_plus_n", "value": 1, "regression_step": 1 }} }} }}
   - 공식유형: prev_plus_n (더하기), prev_minus_n (빼기), carryover (이월), draw_date_end (날짜끝수)

3. **group_condition (그룹/수열 분석)**
   - 예: "소수 분석", "루카스 수로 해줘", "피보나치 수열", "홀수 3개 짝수 3개"
   - **중요**: '루카스 수', '피보나치' 같은 특수 수열이 언급되면, **당신이 직접 해당 수열의 숫자(1~45 범위)를 계산해서 `numbers` 배열에 채워넣어야 합니다.**
   - JSON: {{ "intent": "group_condition", "params": {{ "config": {{ "groups": [{{ "name": "루카스 수", "numbers": [1, 3, 4, 7, 11, 18, 29, 47], "condition": {{ "min": 1, "max": 3 }} }}] }} }} }}

4. **regression_scan (회귀 전수조사)**
   - 예: "100회귀까지 스캔해줘", "전수조사 해봐"
   - JSON: {{ "intent": "regression_scan", "params": {{ "limit": 100 }} }}

---

**[사용자 입력]**
"{user_input}"

**[제약 사항]**
1. 오직 **JSON 데이터만** 출력하세요. (마크다운 ```json 태그 금지)
2. 모르는 의도라면 `intent`를 "unknown"으로 설정하세요.
3. 숫자는 반드시 1~45 사이여야 합니다.
"""

def create_interpret_chain():
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
        temperature=0.0, # 정확한 포맷 변환을 위해 창의성 0 설정
        google_api_key=config.GOOGLE_API_KEY
    )

    prompt = PromptTemplate(
        template=INTERPRET_PROMPT,
        input_variables=["user_input"]
    )

    return prompt | llm | StrOutputParser()

async def interpret_query(user_input: str):
    """사용자 자연어 명령을 구조화된 파라미터로 변환"""
    try:
        chain = create_interpret_chain()
        result_text = await chain.ainvoke({"user_input": user_input})
        
        # JSON 파싱 정제
        cleaned_text = result_text.replace("```json", "").replace("```", "").strip()
        return json.loads(cleaned_text)
    except Exception as e:
        print(f"Interpretation Error: {e}")
        return {"intent": "unknown", "error": str(e)}
