from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.compliance import ChatMessage, ChatResponse, ChatSource
from app.services.rag import answer_with_rag

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(body: ChatMessage, db: AsyncSession = Depends(get_db)):
    answer, clauses = await answer_with_rag(db, body.message, body.source_type)
    sources = [
        ChatSource(
            id=c.id,
            clause_no=c.clause_no,
            title=c.title,
            document_name=c.document.name if c.document else None,
            doc_type=c.document.doc_type if c.document else None,
        )
        for c in clauses
    ]
    return ChatResponse(answer=answer, sources=sources)
