"""FAISS 벡터 저장소 초기화 및 관리."""

import os
from langchain_community.vectorstores import FAISS
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from config import CHROMA_DB_PATH, EMBEDDING_MODEL, GOOGLE_API_KEY

_vector_store: FAISS | None = None


def get_embeddings() -> GoogleGenerativeAIEmbeddings:
    return GoogleGenerativeAIEmbeddings(
        model=EMBEDDING_MODEL,
        google_api_key=GOOGLE_API_KEY,
    )


def get_vector_store() -> FAISS:
    """FAISS 벡터 저장소 싱글턴을 반환한다."""
    global _vector_store
    if _vector_store is None:
        if os.path.exists(CHROMA_DB_PATH) and os.path.exists(os.path.join(CHROMA_DB_PATH, "index.faiss")):
            try:
                _vector_store = FAISS.load_local(
                    CHROMA_DB_PATH, 
                    get_embeddings(), 
                    allow_dangerous_deserialization=True
                )
            except Exception as e:
                print(f"FAISS 로드 실패 (새로 생성함): {e}")
                # 빈 인덱스로 초기화하려면 문서가 필요하므로 None 유지 -> add_documents에서 처리
                pass
    return _vector_store


def add_documents(docs: list) -> None:
    """문서를 벡터 저장소에 추가한다."""
    global _vector_store
    
    if not docs:
        return

    embeddings = get_embeddings()
    
    # 저장소가 없으면 새로 생성
    if _vector_store is None:
        # 기존 파일이 있는지 재확인 (get_vector_store에서 로드 실패했을 수도 있음)
        if os.path.exists(CHROMA_DB_PATH) and os.path.exists(os.path.join(CHROMA_DB_PATH, "index.faiss")):
             try:
                _vector_store = FAISS.load_local(CHROMA_DB_PATH, embeddings, allow_dangerous_deserialization=True)
                _vector_store.add_documents(docs)
             except:
                _vector_store = FAISS.from_documents(docs, embeddings)
        else:
            _vector_store = FAISS.from_documents(docs, embeddings)
    else:
        _vector_store.add_documents(docs)
    
    # 로컬 저장
    _vector_store.save_local(CHROMA_DB_PATH)


def get_document_count() -> int:
    """저장된 문서 수를 반환한다."""
    store = get_vector_store()
    if store is None:
        return 0
    return store.index.ntotal
