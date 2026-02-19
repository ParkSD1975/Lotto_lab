import json
import asyncio
import re
from langchain.prompts import PromptTemplate
from langchain.schema.runnable import RunnablePassthrough
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.schema.output_parser import StrOutputParser

import config
from models.ensemble import LottoEnsemble
from db.supabase_client import fetch_all_draws
from rag.retriever import retrieve_as_text

# 1. 모델 및 전역 변수 초기화 (지연 로딩)
ensemble = None

def get_ensemble():
    global ensemble
    if ensemble is None:
        try:
            ensemble = LottoEnsemble()
            print("[OK] LottoEnsemble loaded successfully.")
        except Exception as e:
            print(f"[WARN] LottoEnsemble Init Failed: {e}")
            ensemble = None
    return ensemble

# 2. [신규] 범용 템플릿 (페이지별 주제 자동 대응)
UNIVERSAL_PROMPT_TEMPLATE = """당신은 감정과 조언이 제거된 '로또 번호 통계 분석 엔진'입니다.
## 분석 주제: {topic}

아래 제공된 데이터만을 근거로 **{topic}**과 관련된 분석을 수행하고, 데이터에 없는 내용은 절대 지어내지 마시오.

### 1. 딥러닝 예측 데이터
{ai_prediction_summary}

### 2. RAG 과거 패턴 데이터
{rag_context}

### 3. 사용자 분석 요청 (핵심 데이터 포함)
- 유형: {analysis_type}
- 기준: {subject_round}회차
- 입력 데이터:
{user_context}

---

**[절대 금지 사항]**
다음 단어/표현이 출력에 포함되면 시스템 오류로 간주됨:
- 투자 조언: "소액으로", "분산 투자", "고액 투자는 지양", "무리한 투자", "책임", "재미로", "유연한 접근", "시나리오", "추천합니다", "추천드립니다"
- 비과학적 표현: "에너지 분석", "에너지가 응축", "에너지 분출", "기운", "흐름이 좋다"
- 모호한 서술: "고려해볼 수 있습니다", "가능성이 있습니다", "주시해야 합니다", "고려해볼 만합니다"
- 면책 문구: "적중률이 100%가 아니므로", "과거의 경향일 뿐", "미래를 보장하지 않습니다"

**[작성 규칙]**
1. **Trend**: {topic}에 초점을 맞춰 현재 상태를 수치적으로 진단. 역대 기록 대비 현재 위치를 백분율로 표현.
2. **Pattern**: {topic}과 관련된 최근 패턴만 서술. 구체적 수치와 함께 태그 활용: `{{{{good:번호}}}}`, `{{{{warn:번호}}}}`, `{{{{range:구간}}}}`.
3. **Recommendation**: {topic} 관점에서 유력 번호와 제외 번호를 제시. 데이터 근거 필수.

**[출력 형식 (JSON Only)]**
반드시 아래 JSON 형식으로만 출력하세요. 마크다운 코드블록 사용 금지.
{{
    "trend": "{topic} 기준 수치 진단...",
    "pattern": "{topic} 관련 최근 패턴...",
    "recommendation": "{topic} 관점 번호 전략..."
}}
"""

def create_chain():
    """LangChain 파이프라인 생성 (범용 템플릿)"""
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
        temperature=0.1, # 창의성 최소화 (사실 기반)
        google_api_key=config.GOOGLE_API_KEY
    )

    # * 핵심: topic 변수 추가
    prompt = PromptTemplate(
        template=UNIVERSAL_PROMPT_TEMPLATE,
        input_variables=["topic", "target_round", "ai_prediction_summary", "rag_context", "analysis_type", "subject_round", "user_context"]
    )

    return prompt | llm | StrOutputParser()

def clean_rag_context(text: str) -> str:
    """RAG 컨텍스트에서 도덕적 조언이나 불필요한 문장 제거"""
    if not text:
        return ""
    
    # 제거할 키워드 목록 (확장됨)
    forbidden_keywords = [
        "투자", "책임", "맹신", "신중", "과도한", "재미로", "도박", "유의", "권장합니다", "바랍니다",
        "분산", "리스크", "관리", "전략을 재검토", "소액", "예상치 못한 결과", "시나리오",
        "추천합니다", "추천드립니다", "에너지 분석", "에너지가 응축", "에너지 분출",
        "고려해볼 만합니다", "주시해야", "100%가 아니므로", "미래를 보장"
    ]
    
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        if any(keyword in line for keyword in forbidden_keywords):
            continue
        cleaned_lines.append(line)
    
    result = '\n'.join(cleaned_lines)
    return result if result.strip() else "(관련된 통계적 패턴 데이터가 없습니다.)"

def sanitize_output(text: str) -> str:
    """최종 출력에서 도덕적 조언/비과학적 표현이 포함된 문장을 강제로 제거 (Safety Net)"""
    try:
        data = json.loads(text)

        # 필터링할 키워드 (확장됨)
        forbidden_keywords = [
            "분산 투자", "리스크 관리", "소액", "책임", "맹신", "신중", "재미",
            "고액 투자는 지양", "무리한 투자", "추천합니다", "추천드립니다",
            "에너지 분석", "에너지가 응축", "에너지 분출", "에너지가 폭발",
            "고려해볼 만합니다", "주시해야 합니다", "가능성이 있습니다",
            "적중률이 100%가 아니므로", "과거의 경향일 뿐", "미래를 보장하지 않습니다",
            "유연한 접근", "시나리오", "100%가 아니므로"
        ]
        
        for key in ["trend", "pattern", "recommendation"]:
            if key in data:
                sentences = re.split(r'(?<=[.!?])\s+', data[key])
                clean_sentences = []
                for s in sentences:
                    if not any(bad in s for bad in forbidden_keywords):
                        clean_sentences.append(s)
                data[key] = " ".join(clean_sentences)
                
                # 만약 다 지워져서 비었다면 기본 메시지
                if not data[key].strip():
                    data[key] = "통계적 유의성이 낮은 구간입니다."

        return json.dumps(data, ensure_ascii=False)
    except:
        # JSON 파싱 실패 시 원본 반환 (어차피 run_analysis에서 처리됨)
        return text

async def run_analysis(context: str, analysis_type: str, target_round: int, subject_round: int, topic: str = "", response_style: str = "default", history_data: list = None):
    """
    통합 분석 실행 함수 (딥러닝 예측 상세 데이터 포함)
    """
    try:
        # 1. 데이터 로드
        draws = fetch_all_draws()

        # [Universal Prompt Logic]
        # topic이 존재하면 무조건 범용 프롬프트를 사용합니다.
        if topic and topic.strip():
            print(f"[Analysis Chain] Universal Prompt Activated for topic: {topic}")
            prompt_template = UNIVERSAL_PROMPT_TEMPLATE
        
        # topic이 없지만 분석 타입이 'hot_cold'인 경우 (안전장치)
        elif analysis_type == 'hot_cold':
            topic = "핫/콜드(Hot/Cold) 패턴"
            print(f"[Analysis Chain] Hot/Cold Analysis Detected (Fallback)")
            prompt_template = UNIVERSAL_PROMPT_TEMPLATE
        
        # 기존 레거시 로직 (필요시 유지 또는 점진적 교체)
        else:
            # 기본값 (topic이 없고 hot_cold도 아닌 경우)
            # 기존 로직을 따르거나, 만능 프롬프트 기본값 설정
            if not topic:
                topic = "로또 번호 종합 분석"
            prompt_template = UNIVERSAL_PROMPT_TEMPLATE

        # 2. 딥러닝 모델 예측 (상세 데이터 전달)
        current_ensemble = get_ensemble()
        if current_ensemble and len(draws) > 50:
            predictions = current_ensemble.predict(draws)
            probs = predictions.get('probabilities', {})
            
            # * [긴급 패치] 음수 확률 제거 (0~1 사이로 보정)
            # 만약 값이 음수라면 Sigmoid 함수 등을 안 거친 Logit 값일 수 있음.
            # 임시로 0보다 작은 값은 0.0001로, 1보다 큰 값은 0.9999로 보정
            safe_probs = {}
            for k, v in probs.items():
                val = float(v)
                if val < 0: val = 0.0001  # 음수 제거
                if val > 1: val = 0.9999
                safe_probs[k] = val
            probs = safe_probs  # 교체 완료
            
            weights_used = predictions.get('weights_used', {})
            contributions = predictions.get('model_contributions', {})
            xgb_features = predictions.get('xgb_feature_importance', {})

            # 상위 15개 번호 확률 상세
            sorted_probs = sorted(probs.items(), key=lambda x: x[1], reverse=True)
            top_15 = sorted_probs[:15]
            bottom_10 = sorted_probs[-10:]

            top_detail = "\n".join(
                f"  {n}번: 앙상블확률 {p:.4f} (Trans: {contributions.get('transformer',{}).get(n,0):.4f}, LSTM: {contributions.get('lstm',{}).get(n,0):.4f}, CNN: {contributions.get('cnn',{}).get(n,0):.4f}, XGB: {contributions.get('xgboost',{}).get(n,0):.4f}, Markov: {contributions.get('markov',{}).get(n,0):.4f})"
                for n, p in top_15
            )
            bottom_detail = ", ".join(f"{n}번({p:.4f})" for n, p in bottom_10)

            # XGBoost 피처 중요도 (상위 번호)
            xgb_detail = ""
            for n, feats in list(xgb_features.items())[:5]:
                if feats:
                    feat_str = ", ".join(f"{fname}({fval:.3f})" for fname, fval in feats[:3])
                    xgb_detail += f"  {n}번 핵심 피처: {feat_str}\n"

            # [핵심] 번호 예측 분석인 경우에만 딥러닝 예측 데이터를 LLM에 전달
            # 그 외 분석(AC값, 이월수, 홀짝 등)에서는 번호 확률을 보여주면 안 됨
            is_number_prediction = (
                not topic  # topic이 비어있으면 기본 번호 예측으로 간주
                or "번호" in topic
                or "예측" in topic
                or analysis_type in ('general', '', 'prediction', 'deep')
            )

            if is_number_prediction:
                ai_summary = f"""[5중 앙상블 모델 가중치] Transformer: {weights_used.get('transformer',0):.2f}, LSTM: {weights_used.get('lstm',0):.2f}, CNN: {weights_used.get('cnn',0):.2f}, XGBoost: {weights_used.get('xgboost',0):.2f}, Markov: {weights_used.get('markov',0):.2f}

[상위 15개 번호 확률 (모델별 상세)]
{top_detail}

[하위 10개 번호 (제외 권고)]
{bottom_detail}

[XGBoost 피처 중요도 분석]
{xgb_detail if xgb_detail else '(피처 데이터 없음)'}"""
            else:
                ai_summary = f"(이 분석은 '{topic}' 주제 분석입니다. 개별 번호 확률 데이터는 생략하고, 사용자가 제공한 컨텍스트 데이터만으로 분석하세요.)"
        else:
            ai_summary = "DATA_INSUFFICIENT_FOR_PREDICTION (데이터 50회 미만 또는 모델 미로드)"

    except Exception as e:
        print(f"AI Prediction Error: {e}")
        import traceback
        traceback.print_exc()
        ai_summary = f"PREDICTION_ERROR: {str(e)}"

    # 3. RAG 검색 및 정제 (핵심)
    try:
        rag_raw = retrieve_as_text(query=context, analysis_type=analysis_type, k=5)
        rag_context = clean_rag_context(rag_raw)
        print(f"[RAG] Cleaned Context:\n{rag_context}")
    except Exception as e:
        print(f"RAG Error: {e}")
        rag_context = "RAG_RETRIEVAL_FAILED"

    # 4. LangChain 실행
    try:
        chain = create_chain()
        result_text = await chain.ainvoke({
            "topic": topic,  # * 핵심: 프론트엔드가 보낸 주제
            "target_round": target_round,
            "ai_prediction_summary": ai_summary,
            "rag_context": rag_context,
            "analysis_type": analysis_type,
            "subject_round": subject_round,
            "user_context": context
        })

        cleaned_text = result_text.replace("```json", "").replace("```", "").strip()

        # [New] 최종 결과 강제 정제
        sanitized_text = sanitize_output(cleaned_text)

        try:
            return json.loads(sanitized_text)
        except:
            return {
                "trend": "JSON Parsing Error (Sanitized)",
                "pattern": sanitized_text,
                "recommendation": "Retry Required"
            }

    except Exception as e:
        print(f"Chain Execution Error: {e}")
        return {
            "trend": f"System Error: {str(e)}",
            "pattern": "Check Server Logs",
            "recommendation": "Error"
        }
