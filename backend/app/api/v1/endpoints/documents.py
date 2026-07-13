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
from app.services.rag import find_similar_canonical_items
from app.services.upstage import embed_text, generate_checklist_items, parse_document

# Cap on concurrent Upstage embedding calls during upload, so a large document
# doesn't fire 100+ simultaneous requests and trip rate limits.
_EMBED_CONCURRENCY = 8

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

    # 2) Embed clauses now (not in the background) — the duplicate-candidate
    # lookup below needs these embeddings before Solar runs. Concurrency is
    # capped so a large document doesn't fire 100+ simultaneous requests.
    summary_clauses = [c for c in created_clauses if c.requirement]
    clause_vecs = await _embed_many([c.requirement for c in summary_clauses])
    for clause, vec in zip(summary_clauses, clause_vecs):
        if vec is not None:
            db.add(Embedding(source_type="clause", source_id=clause.id, embedding=vec))
    await db.commit()

    # 3) Solar: generate checklist items (the primary deliverable) — commit
    cat_rows = (await db.execute(select(Category))).scalars().all()
    categories = sorted(c.name for c in cat_rows)
    cat_map = {c.name: c.id for c in cat_rows}
    # Normalized lookup (ignore spaces/·/및) so Solar variants still match a seed
    norm_map = {_norm_cat(name): cid for name, cid in cat_map.items()}

    clause_summaries = [{"title": c.title, "requirement": c.requirement} for c in summary_clauses]

    # For each clause, shortlist likely cross-document duplicates by embedding
    # similarity, so Solar only has to confirm/reject a handful of relevant
    # candidates instead of scanning every canonical item ever created.
    candidates_by_clause: dict[int, list[dict]] = {}
    for i, vec in enumerate(clause_vecs):
        if vec is None:
            continue
        candidates = await find_similar_canonical_items(db, vec)
        if candidates:
            candidates_by_clause[i] = candidates

    checklist_count = 0
    if clause_summaries and categories:
        items = await generate_checklist_items(
            clause_summaries, categories, candidates_by_clause=candidates_by_clause
        )
        for item in items:
            item_title = (item.get("title") or "").strip()
            item_cat = (item.get("category") or "").strip()
            if not item_title:
                continue

            # Figure out which newly-created clause this item was generated from
            target_clause = summary_clauses[0] if summary_clauses else None
            src = item.get("source")
            if isinstance(src, int) and 1 <= src <= len(summary_clauses):
                target_clause = summary_clauses[src - 1]

            # If Solar flagged this as a duplicate of an existing canonical item,
            # reuse that canonical_id and just add a new CanonicalMap row linking
            # THIS clause to it, instead of creating a new CanonicalItem.
            matches_id = item.get("matches_existing_id")
            canonical_id: uuid.UUID | None = None
            if matches_id and matches_id != "null":
                try:
                    canonical_id = uuid.UUID(str(matches_id))
                except (ValueError, TypeError):
                    canonical_id = None

            if canonical_id is None:
                canonical = CanonicalItem(
                    category_id=_match_category(item_cat, cat_map, norm_map),
                    merged_title=item_title,
                )
                db.add(canonical)
                await db.flush()
                canonical_id = canonical.id

            if target_clause is not None:
                db.add(CanonicalMap(canonical_id=canonical_id, clause_id=target_clause.id))
                db.add(ChecklistItem(clause_id=target_clause.id, question=item_title))
            checklist_count += 1

        await db.commit()

    return {
        "message": "파싱 및 체크리스트 생성 완료",
        "clauses": len(created_clauses),
        "checklist_items": checklist_count,
    }


def _norm_cat(s: str) -> str:
    """Normalize a category name for matching: drop spaces, 및, ·, /, commas."""
    import re as _re
    return _re.sub(r'[\s및·,/]+', '', s)


def _match_category(raw: str, cat_map: dict, norm_map: dict) -> uuid.UUID | None:
    """Map a Solar-returned category string to a seeded category id.
    Tries exact → normalized → substring → difflib closest match.
    """
    if not raw:
        return None
    if raw in cat_map:
        return cat_map[raw]

    n = _norm_cat(raw)
    if n in norm_map:
        return norm_map[n]

    # Substring either direction (e.g. "물리보안" ⊂ "물리적보안")
    for seed_norm, cid in norm_map.items():
        if n and (n in seed_norm or seed_norm in n):
            return cid

    # Fuzzy closest match (handles minor variations)
    import difflib
    close = difflib.get_close_matches(n, list(norm_map.keys()), n=1, cutoff=0.6)
    if close:
        return norm_map[close[0]]
    return None


def _segment_document(md: str) -> list[dict]:
    """Segment parsed markdown into clauses.
    Priority: clause tables (항목/인증기준 rows) > markdown headings >
    ISMS-P clause codes (1.2.3) > fixed-size chunks.
    """
    if not md:
        return []

    import re as _re

    # (a) clause tables: a markdown table row whose first cell is "항목" / "항 목"
    #     starts a new clause. Everything up to the next such row (or next
    #     top-level heading) belongs to this clause.
    clause_table_start = _re.compile(
        r'^\|\s*항\s*목\s*\|\s*(?P<body>.+?)\s*\|\s*$', _re.MULTILINE
    )
    table_matches = list(clause_table_start.finditer(md))

    if len(table_matches) >= 5:
        raw: list[dict] = []
        for i, m in enumerate(table_matches):
            header_cell = m.group("body").strip()
            code_match = _re.match(r'([\d.]+)\s*(.*)', header_cell)
            clause_no = code_match.group(1) if code_match else None
            title = (code_match.group(2) if code_match else header_cell).strip()

            block_start = m.start()
            block_end = table_matches[i + 1].start() if i + 1 < len(table_matches) else len(md)
            block = md[block_start:block_end]

            requirement = _extract_table_field(block, "인증기준")
            checklist_raw = _extract_table_field(block, "주요\\s*확인사항")
            related_laws = _extract_table_field(block, "관련\\s*법규")

            # Fold the checklist questions into requirement text if 인증기준 itself
            # is empty (some docs only have 주요확인사항, e.g. CSAP variants)
            body_text = requirement or checklist_raw or ""

            raw.append({
                "title": title[:255] or f"조항 {i + 1}",
                "clause_no": clause_no,
                "requirement": body_text.strip() or None,
                "related_laws_raw": related_laws,
            })
        return raw

    # (b) markdown headings — fallback for docs without the clause-table structure
    heading = list(_re.compile(r'^(#{1,4})\s+(.+)$', _re.MULTILINE).finditer(md))
    # (c) ISMS-P clause codes like "1.1.1 제목" or "2.5 제목"
    clause_code = list(_re.compile(r'^\s*(\d+\.\d+(?:\.\d+)?)\s+(.{2,80})$', _re.MULTILINE).finditer(md))

    LAW_KEYWORDS = ("관련 법규", "법적 근거", "관련 법령", "관련법령")

    def split_laws(body: str) -> tuple[str | None, str | None]:
        laws, req = [], []
        for line in body.splitlines():
            (laws if any(k in line for k in LAW_KEYWORDS) else req).append(line)
        return ("\n".join(req).strip() or None, "\n".join(laws).strip() or None)

    splits = heading if len(heading) >= 5 else (clause_code if len(clause_code) >= 5 else [])

    raw = []
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


def _extract_table_field(block: str, field_label_pattern: str) -> str | None:
    """Pull the value cell of a `| <라벨> | <값> |` row out of a clause table block.
    field_label_pattern is a regex fragment (spaces allowed) matching the row label,
    e.g. "인증기준" or "주요\\s*확인사항".

    Cell values may span multiple physical lines (bulleted 주요확인사항/관련법규
    text). The value runs until the start of the next row (a line beginning with
    a single "|") rather than until the current line closes with "|", so wrapped
    lines don't get truncated and don't bleed into the next field.
    """
    import re as _re
    m = _re.search(
        rf'^\|\s*{field_label_pattern}\s*\|\s*(?P<val>.*?)(?=\n\|(?!\|)|\Z)',
        block,
        _re.MULTILINE | _re.DOTALL,
    )
    if not m:
        return None
    val = m.group("val").strip().rstrip("|").strip()
    return val or None


async def _embed_many(texts: list[str]) -> list[list[float] | None]:
    """Embed multiple texts concurrently (capped) and best-effort skip failures,
    returning None in the corresponding slot for anything that failed."""
    import logging

    log = logging.getLogger(__name__)
    sem = asyncio.Semaphore(_EMBED_CONCURRENCY)

    async def _one(text: str) -> list[float] | None:
        async with sem:
            try:
                return await embed_text(text)
            except Exception as e:  # noqa: BLE001 — best-effort, keep going
                log.warning("embed skip: %s", e)
                return None

    return await asyncio.gather(*(_one(t) for t in texts))
