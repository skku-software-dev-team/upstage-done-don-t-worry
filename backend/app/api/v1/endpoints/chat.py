from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.compliance import ChatMessage, ChatResponse
from app.services.rag import answer_with_rag

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/", response_model=ChatResponse)
async def chat(body: ChatMessage, db: AsyncSession = Depends(get_db)):
    answer, sources = await answer_with_rag(db, body.message, body.org_id)
    return ChatResponse(answer=answer, sources=sources)
