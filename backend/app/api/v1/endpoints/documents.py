import asyncio
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.compliance import (
    CanonicalItem,
    CanonicalMap,
    Category,
    ChecklistItem,
    Clause,
    Document,
    Embedding,
)
from app.schemas.compliance import ClauseRead, DocumentCreate, DocumentRead
from app.services.upstage import embed_text, generate_checklist_items, parse_document

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


@router.delete("/{doc_id}", status_code=204)
async def delete_document(doc_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    doc = await db.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    await db.delete(doc)
    await db.commit()


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

    # Use top-level content.markdown (full doc as one markdown string)
    md = (parsed.get("content") or {}).get("markdown", "").strip()
    if not md:
        md = (parsed.get("content") or {}).get("text", "").strip()

    raw_clauses = _segment_document(md)

    # 1) Persist clauses first (no embeddings yet), then commit — never lose parse
    created_clauses: list[Clause] = []
    for c in raw_clauses:
        clause = Clause(
            document_id=doc_id,
            title=c["title"],
            clause_no=c["clause_no"],
            requirement=c["requirement"],
            related_laws_raw=c["related_laws_raw"],
        )
        db.add(clause)
        await db.flush()
        created_clauses.append(clause)

    await db.commit()

    # 2) Solar: generate checklist items (the primary deliverable) — commit
    cat_rows = (await db.execute(select(Category))).scalars().all()
    categories = sorted(c.name for c in cat_rows)
    cat_map = {c.name: c.id for c in cat_rows}

    clause_summaries = [
        {"title": c.title, "requirement": c.requirement}
        for c in created_clauses
        if c.requirement
    ]

    checklist_count = 0
    if clause_summaries and categories:
        items = await generate_checklist_items(clause_summaries, categories)
        for item in items:
            item_title = (item.get("title") or "").strip()
            item_cat = (item.get("category") or "").strip()
            if not item_title:
                continue

            canonical = CanonicalItem(
                category_id=cat_map.get(item_cat),
                merged_title=item_title,
            )
            db.add(canonical)
            await db.flush()

            if created_clauses:
                db.add(CanonicalMap(canonical_id=canonical.id, clause_id=created_clauses[0].id))
                db.add(ChecklistItem(clause_id=created_clauses[0].id, question=item_title))
            checklist_count += 1

        await db.commit()

    # 3) Embeddings — best-effort, in background so upload returns fast
    asyncio.create_task(_embed_clauses_bg([c.id for c in created_clauses if c.requirement]))

    return {
        "message": "파싱 및 체크리스트 생성 완료",
        "clauses": len(created_clauses),
        "checklist_items": checklist_count,
    }


def _segment_document(md: str) -> list[dict]:
    """Segment parsed markdown into clauses.
    Priority: markdown headings > ISMS-P clause codes (1.2.3) > fixed-size chunks.
    """
    LAW_KEYWORDS = ("관련 법규", "법적 근거", "관련 법령", "관련법령")

    def split_laws(body: str) -> tuple[str | None, str | None]:
        laws, req = [], []
        for line in body.splitlines():
            (laws if any(k in line for k in LAW_KEYWORDS) else req).append(line)
        return ("\n".join(req).strip() or None, "\n".join(laws).strip() or None)

    if not md:
        return []

    import re as _re

    # (a) markdown headings
    heading = list(_re.compile(r'^(#{1,4})\s+(.+)$', _re.MULTILINE).finditer(md))
    # (b) ISMS-P clause codes like "1.1.1 제목" or "2.5 제목"
    clause_code = list(_re.compile(r'^\s*(\d+\.\d+(?:\.\d+)?)\s+(.{2,80})$', _re.MULTILINE).finditer(md))

    splits = heading if len(heading) >= 5 else (clause_code if len(clause_code) >= 5 else [])

    raw: list[dict] = []
    if splits:
        for i, m in enumerate(splits):
            groups = m.groups()
            title = groups[-1].strip()
            clause_no = groups[0].strip() if splits is clause_code else None
            body = md[m.end(): splits[i + 1].start() if i + 1 < len(splits) else len(md)].strip()
            req, laws = split_laws(body)
            raw.append({"title": title[:255], "clause_no": clause_no,
                        "requirement": req, "related_laws_raw": laws})
    else:
        # Fixed-size chunk fallback (~1500 chars), cap at 200 chunks
        CHUNK = 1500
        for i in range(0, min(len(md), CHUNK * 200), CHUNK):
            chunk = md[i:i + CHUNK].strip()
            if chunk:
                raw.append({"title": chunk.splitlines()[0][:255], "clause_no": None,
                            "requirement": chunk, "related_laws_raw": None})
    return raw


async def _embed_clauses_bg(clause_ids: list[uuid.UUID]) -> None:
    """Background best-effort embedding. Uses its own DB session; skips failures."""
    import logging

    from app.core.database import AsyncSessionLocal

    log = logging.getLogger(__name__)
    async with AsyncSessionLocal() as db:
        for cid in clause_ids:
            clause = await db.get(Clause, cid)
            if not clause or not clause.requirement:
                continue
            try:
                vec = await embed_text(clause.requirement)
                db.add(Embedding(source_type="clause", source_id=clause.id, embedding=vec))
                await db.commit()
            except Exception as e:  # noqa: BLE001 — best-effort, keep going
                await db.rollback()
                log.warning("embed skip clause %s: %s", cid, e)
