"""세션별 대화 기록 관리 (LangChain 의존 없이 자체 구현)."""

import time
from collections import deque
from langchain_core.messages import HumanMessage, AIMessage

_sessions: dict = {}
MAX_SESSIONS = 100
WINDOW_SIZE = 10


class SimpleConversationMemory:
    """최근 N턴의 대화를 저장하는 간단한 메모리."""

    def __init__(self, k: int = WINDOW_SIZE):
        self._messages: deque = deque(maxlen=k * 2)

    def load_memory_variables(self, _inputs: dict) -> dict:
        return {"chat_history": list(self._messages)}

    def save_context(self, inputs: dict, outputs: dict) -> None:
        self._messages.append(HumanMessage(content=inputs.get("input", "")))
        self._messages.append(AIMessage(content=outputs.get("output", "")))

    def clear(self) -> None:
        self._messages.clear()


def get_or_create(session_id: str) -> SimpleConversationMemory:
    """세션 ID에 대한 메모리를 반환하거나 생성한다."""
    if session_id not in _sessions:
        if len(_sessions) > MAX_SESSIONS:
            oldest = min(_sessions, key=lambda k: _sessions[k]["last_used"])
            del _sessions[oldest]
        _sessions[session_id] = {
            "memory": SimpleConversationMemory(k=WINDOW_SIZE),
            "last_used": time.time(),
        }
    _sessions[session_id]["last_used"] = time.time()
    return _sessions[session_id]["memory"]


def clear_session(session_id: str) -> None:
    """특정 세션의 대화 기록을 삭제한다."""
    if session_id in _sessions:
        del _sessions[session_id]
