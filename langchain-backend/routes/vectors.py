from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class VectorUpdateRequest(BaseModel):
    round: int | None = None


@router.post("/vectors/update")
async def update_vectors(req: VectorUpdateRequest):
    from rag.embedder import update_incremental
    from db.vector_store import get_document_count

    after_round = req.round - 1 if req.round else 0
    count = update_incremental(after_round)
    total = get_document_count()
    return {"updated": count, "total": total}


@router.get("/vectors/status")
async def vector_status():
    from db.vector_store import get_document_count

    return {"total_documents": get_document_count()}
