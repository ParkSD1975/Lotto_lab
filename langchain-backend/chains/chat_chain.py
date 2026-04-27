"""RAG 기반 Q&A 대화 체인."""

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage
from config import GOOGLE_API_KEY, LLM_MODEL
from rag.retriever import retrieve
from memory.session_store import get_or_create


def get_llm() -> ChatGoogleGenerativeAI:
    llm_kwargs = {"model": LLM_MODEL, "temperature": 0.7}
    if GOOGLE_API_KEY:
        llm_kwargs["google_api_key"] = GOOGLE_API_KEY
    return ChatGoogleGenerativeAI(**llm_kwargs)


SYSTEM_PROMPT = """당신은 대한민국 로또(Lotto 6/45) 분석 전문 AI 어시스턴트입니다.
사용자의 질문에 대해 제공된 과거 로또 데이터를 근거로 정확하고 통찰력 있는 답변을 제공하세요.

규칙:
- 항상 구체적인 데이터와 회차 번호를 근거로 답변하라
- 추측이 아닌 통계적 사실에 기반하라
- 한국어로 자연스럽게 답변하라
- 핵심 숫자는 {{good:숫자}} 또는 {{warn:숫자}} 태그로 강조하라"""


async def run_chat(
    message: str,
    session_id: str,
    analysis_type: str | None = None,
    context_data: str | None = None,
) -> dict:
    """RAG 기반 대화를 수행한다."""
    llm = get_llm()
    memory = get_or_create(session_id)

    # RAG 검색
    search_query = message
    if analysis_type:
        search_query = f"[{analysis_type}] {message}"

    rag_results = retrieve(search_query, analysis_type, k=8)
    rag_text = "\n".join(doc.page_content for doc, _ in rag_results) if rag_results else "(관련 데이터 없음)"

    # 페이지 컨텍스트 추가
    page_ctx = ""
    if context_data:
        page_ctx = f"\n\n## 현재 페이지 데이터\n{context_data[:1000]}"

    # 대화 기록 로드
    chat_history = memory.load_memory_variables({}).get("chat_history", [])

    # 프롬프트 구성
    full_prompt = f"""{SYSTEM_PROMPT}

## 검색된 과거 데이터 (RAG)
{rag_text}
{page_ctx}

## 대화 기록
{_format_history(chat_history)}

## 사용자 질문
{message}

위 데이터를 근거로 답변하세요. 근거가 되는 회차 번호를 함께 언급하세요."""

    result = await llm.ainvoke(full_prompt)
    answer = result.content

    # 메모리에 저장
    memory.save_context({"input": message}, {"output": answer})

    # 출처 정보
    sources = []
    for doc, _ in rag_results[:3]:
        sources.append({
            "round": doc.metadata.get("round"),
            "content": doc.page_content[:100],
        })

    return {"answer": answer, "sources": sources}


def _format_history(messages: list) -> str:
    """대화 기록을 텍스트로 포맷한다."""
    if not messages:
        return "(없음)"
    lines = []
    for msg in messages[-6:]:  # 최근 6개만
        role = "사용자" if isinstance(msg, HumanMessage) else "AI"
        lines.append(f"{role}: {msg.content[:200]}")
    return "\n".join(lines)
