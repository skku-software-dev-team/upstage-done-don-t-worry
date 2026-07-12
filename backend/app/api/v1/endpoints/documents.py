import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.compliance import Clause, Document, Embedding
from app.schemas.compliance import ClauseRead, DocumentCreate, DocumentRead
from app.services.upstage import embed_text, parse_document

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("", response_model=list[DocumentRead])
async def list_documents(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Document).order_by(Document.created_at.desc()))
    return result.scalars().all()


@router.post("", response_model=DocumentRead, status_code=201)
async def create_document(body: DocumentCreate, db: AsyncSession = Depends(get_db)):
    doc = Document(**body.model_dump())
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return doc


@router.get("/{doc_id}/clauses", response_model=list[ClauseRead])
async def list_clauses(doc_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Clause).where(Clause.document_id == doc_id))
    return result.scalars().all()


@router.post("/{doc_id}/upload", status_code=202)
async def upload_and_parse(
    doc_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    doc = await db.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")

    content = await file.read()
    parsed = await parse_document(content, file.filename or "upload.pdf")

    # Document Parse returns elements[] grouped by category
    # heading* = clause boundary, paragraph/table = requirement body
    elements = parsed.get("elements", [])
    HEADING_CATS = {"heading1", "heading2", "heading3", "heading4"}
    LAW_KEYWORDS = ("관련 법규", "법적 근거", "관련 법령", "관련법령")

    clauses: list[Clause] = []
    current: dict | None = None

    for el in elements:
        cat = el.get("category", "")
        text = (el.get("content") or {}).get("markdown", "").strip()
        page = el.get("page", 0)

        if cat in HEADING_CATS:
            if current:
                clauses.append(current)
            current = {"clause_no": None, "title": text.lstrip("# "), "requirement": "", "related_laws_raw": "", "page": page}
        elif current is not None and text:
            if any(kw in text for kw in LAW_KEYWORDS):
                current["related_laws_raw"] += text + "\n"
            else:
                current["requirement"] += text + "\n"

    if current:
        clauses.append(current)

    for c in clauses:
        clause = Clause(document_id=doc_id, **{k: (v.strip() or None) for k, v in c.items()})
        db.add(clause)
        await db.flush()

        if clause.requirement:
            vec = await embed_text(clause.requirement)
            db.add(Embedding(source_type="clause", source_id=clause.id, embedding=vec))

    await db.commit()
    return {"message": "Parsed and embedded", "pages": len(clauses)}
