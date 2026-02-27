from langchain.prompts import PromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.schema.output_parser import StrOutputParser

import config
from models.ensemble import LottoEnsemble

# 모델 로드 (지연 초기화)
ensemble = None

def get_ensemble():
    global ensemble
    if ensemble is None:
        ensemble = LottoEnsemble()
    return ensemble

EXPLAIN_PROMPT = """
당신은 로또 AI 분석가입니다. 사용자가 특정 번호({target_number})에 대해 왜 추천되거나 제외되었는지 이유를 묻고 있습니다.
아래 AI 모델의 상세 분석 데이터를 바탕으로, 쉽고 설득력 있게 설명해주세요.

---
**[AI 분석 세부 데이터]**
1. **종합 예측 확률**: {total_prob:.2f}% (전체 번호 중 순위: {rank}위)
2. **모델별 기여도**:
   - LSTM (시계열 흐름): {lstm_prob:.2f}%
   - XGBoost (패턴 매칭): {xgb_prob:.2f}%
   - Markov (미출현 회귀): {markov_prob:.2f}%
3. **핵심 근거 (XAI)**:
   - {xai_reasoning}

**[사용자 질문]**
"{user_query}"
---

**[답변 가이드]**
- 전문적인 용어(LSTM, XGBoost 등)를 사용하되, 초보자도 이해하기 쉽게 풀어서 설명하세요.
- 수치(확률, 순위)를 인용하여 신뢰도를 높이세요.
- 긍정적 추천인지, 부정적 제외인지 결론부터 말하고 이유를 설명하세요.
- 답변은 3~4문장으로 간결하게 작성하세요.
"""

def create_explain_chain():
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
        temperature=0.5,
        google_api_key=config.GOOGLE_API_KEY
    )
    
    prompt = PromptTemplate(
        template=EXPLAIN_PROMPT,
        input_variables=["target_number", "total_prob", "rank", "lstm_prob", "xgb_prob", "markov_prob", "xai_reasoning", "user_query"]
    )
    
    return prompt | llm | StrOutputParser()

async def explain_number(number: int, user_query: str, draws_data: list):
    """특정 번호에 대한 AI 분석 근거 설명."""
    
    # 1. 모델 예측 데이터 확보
    try:
        result = get_ensemble().predict(draws_data)
        probs = result['probabilities']
        
        # 순위 계산
        sorted_nums = sorted(probs.items(), key=lambda x: x[1], reverse=True)
        rank = [n for n, p in sorted_nums].index(number) + 1
        
        # 개별 모델 확률
        lstm_p = result['model_contributions']['lstm'].get(number, 0) * 100
        xgb_p = result['model_contributions']['xgboost'].get(number, 0) * 100
        markov_p = result['model_contributions']['markov'].get(number, 0) * 100
        total_p = probs.get(number, 0) * 100
        
        # XAI 근거 (XGBoost 중요 피처 or Markov 설명)
        xai_text = "복합적인 패턴 분석 결과"
        xgb_feats = result.get('xgb_feature_importance', {})
        if number in xgb_feats and xgb_feats[number]:
            feats = xgb_feats[number]
            xai_text = f"XGBoost 주요 패턴: {feats[0][0]} 영향력 높음"
            
    except Exception as e:
        return f"죄송합니다. 해당 번호({number})에 대한 정밀 분석 데이터를 가져오는 중 오류가 발생했습니다."

    # 2. 설명 생성
    chain = create_explain_chain()
    response = await chain.ainvoke({
        "target_number": number,
        "total_prob": total_p,
        "rank": rank,
        "lstm_prob": lstm_p,
        "xgb_prob": xgb_p,
        "markov_prob": markov_p,
        "xai_reasoning": xai_text,
        "user_query": user_query
    })
    
    return response
