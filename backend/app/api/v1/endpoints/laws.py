import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.compliance import Embedding, Law, LawArticle
from app.schemas.compliance import LawArticleRead, LawRead
from app.services.upstage import embed_text, parse_document

router = APIRouter(prefix="/laws", tags=["laws"])


@router.get("/", response_model=list[LawRead])
async def list_laws(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Law).order_by(Law.name))
    return result.scalars().all()


@router.get("/{law_id}/articles", response_model=list[LawArticleRead])
async def list_articles(law_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(LawArticle).where(LawArticle.law_id == law_id))
    return result.scalars().all()


@router.post("/{law_id}/upload", status_code=202)
async def upload_law(
    law_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    law = await db.get(Law, law_id)
    if not law:
        raise HTTPException(404, "Law not found")

    content = await file.read()
    parsed = await parse_document(content, file.filename or "law.pdf")

    pages = parsed.get("pages", [])
    for page in pages:
        article = LawArticle(
            law_id=law_id,
            article_text=page.get("text", ""),
        )
        db.add(article)
        await db.flush()

        vec = await embed_text(article.article_text or "")
        db.add(Embedding(source_type="law_article", source_id=article.id, embedding=vec))

    await db.commit()
    return {"message": "Parsed and embedded", "pages": len(pages)}
