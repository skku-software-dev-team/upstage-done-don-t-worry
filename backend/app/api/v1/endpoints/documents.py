import asyncio
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.compliance import (
    CanonicalItem,
    CanonicalMap,
    Category,
    ChecklistItem,
    Clause,
    Document,
    Embedding,
    OrgStatus,
    User,
)
from app.api.v1.endpoints.laws import link_new_clauses_to_laws
from app.schemas.compliance import ClauseRead, DocumentActiveUpdate, DocumentCreate, DocumentRead
from app.services.rag import find_similar_canonical_items
from app.services.upstage import embed_text, generate_checklist_items, parse_document

# Cap on concurrent Upstage embedding calls during upload, so a large document
# doesn't fire 100+ simultaneous requests and trip rate limits.
_EMBED_CONCURRENCY = 8

router = APIRouter(prefix="/documents", tags=["documents"], dependencies=[Depends(get_current_user)])


async def _get_owned_document(doc_id: uuid.UUID, organization_id: uuid.UUID, db: AsyncSession) -> Document:
    doc = await db.get(Document, doc_id)
    if not doc or doc.organization_id != organization_id:
        raise HTTPException(404, "Document not found")
    return doc


@router.get("", response_model=list[DocumentRead])
async def list_documents(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Document)
        .where(Document.organization_id == current_user.organization_id)
        .order_by(Document.created_at.desc())
    )
    return result.scalars().all()


@router.post("", response_model=DocumentRead, status_code=201)
async def create_document(
    body: DocumentCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    data = body.model_dump(exclude={"supersedes_document_id"})
    doc = Document(organization_id=current_user.organization_id, **data)
    db.add(doc)

    if body.supersedes_document_id is not None:
        old_doc = await _get_owned_document(body.supersedes_document_id, current_user.organization_id, db)
        old_doc.is_active = False

    await db.commit()
    await db.refresh(doc)
    return doc


@router.patch("/{doc_id}/active", response_model=DocumentRead)
async def set_document_active(
    doc_id: uuid.UUID,
    body: DocumentActiveUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    doc = await _get_owned_document(doc_id, current_user.organization_id, db)
    doc.is_active = body.is_active
    await db.commit()
    await db.refresh(doc)
    return doc


@router.delete("/{doc_id}", status_code=204)
async def delete_document(
    doc_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    doc = await _get_owned_document(doc_id, current_user.organization_id, db)
    await db.delete(doc)
    await db.flush()  # apply cascade deletes (clauses, canonical_map) before the cleanup query below

    # Deleting a document cascades to its clauses and canonical_map rows, but
    # CanonicalItem itself isn't cascade-deleted — if this was the last clause
    # mapped to a canonical item, that item would otherwise be left behind as
    # an orphan (never shown as deletable, but still counted/re-duplicated on
    # the next upload).
    #
    # Only sweep up items with NO org_status anywhere (never checked off in any
    # period) — org_status.canonical_id is ON DELETE CASCADE, so deleting a
    # CanonicalItem that already has history would silently wipe checklist
    # completion records from past (already-saved) periods, not just the
    # current one.
    orphaned_ids = (
        await db.execute(
            select(CanonicalItem.id)
            .outerjoin(CanonicalMap, CanonicalMap.canonical_id == CanonicalItem.id)
            .outerjoin(OrgStatus, OrgStatus.canonical_id == CanonicalItem.id)
            .where(
                CanonicalItem.organization_id == current_user.organization_id,
                CanonicalMap.canonical_id.is_(None),
                OrgStatus.canonical_id.is_(None),
            )
        )
    ).scalars().all()
    if orphaned_ids:
        await db.execute(delete(CanonicalItem).where(CanonicalItem.id.in_(orphaned_ids)))

    await db.commit()


@router.get("/{doc_id}/clauses", response_model=list[ClauseRead])
async def list_clauses(
    doc_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_owned_document(doc_id, current_user.organization_id, db)
    result = await db.execute(select(Clause).where(Clause.document_id == doc_id))
    return result.scalars().all()


@router.post("/{doc_id}/upload", status_code=202)
async def upload_and_parse(
    doc_id: uuid.UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    doc = await _get_owned_document(doc_id, current_user.organization_id, db)

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
        candidates = await find_similar_canonical_items(db, vec, current_user.organization_id)
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
                    organization_id=current_user.organization_id,
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

    # Link any clauses citing a law that's already been uploaded (the
    # reverse of laws.py's own linking, which only fires when a law is
    # uploaded after these clauses already exist).
    linked_laws = await link_new_clauses_to_laws(db, created_clauses, current_user.organization_id)

    return {
        "message": "파싱 및 체크리스트 생성 완료",
        "clauses": len(created_clauses),
        "checklist_items": checklist_count,
        "linked_laws": linked_laws,
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
    #
    # Only capture the FIRST cell after the label (up to the next "|"), not
    # the rest of the line — some documents (e.g. control-mapping tables with
    # per-service-model applicability columns like "IaaS | SaaS | ○ | | ○")
    # have several more columns on the same "항목" row, and capturing to
    # end-of-line would pull all of that into the title.
    clause_table_start = _re.compile(
        r'^\|\s*항\s*목\s*\|\s*(?P<body>[^|\n]+?)\s*\|', _re.MULTILINE
    )
    table_matches = list(clause_table_start.finditer(md))

    # Parsing artifacts that occasionally get captured as if they were real
    # 인증기준/주요확인사항 content: a leaked markdown table separator row
    # ("| --- | --- |", from a table nested inside the cell) or an image
    # placeholder the parser couldn't turn into text.
    junk_content_pattern = _re.compile(r'!\[image\]\(|\|\s*-{2,}\s*(\||$)')

    if len(table_matches) >= 5:
        raw: list[dict] = []
        seen: set[tuple[str, str]] = set()
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
            body_text = (requirement or checklist_raw or "").strip()

            if body_text and junk_content_pattern.search(body_text):
                continue

            dedup_key = (title, body_text)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            raw.append({
                "title": title[:255] or f"조항 {i + 1}",
                "clause_no": clause_no,
                "requirement": body_text or None,
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

    Uses [ \\t]* (not \\s*) right before the value group — \\s* would swallow the
    newline after the label cell, which shifts where capture starts and makes
    the "next line starts with |" boundary check fire one row too late,
    letting an entire adjacent row (e.g. a nested table's header) leak in.
    """
    import re as _re
    m = _re.search(
        rf'^\|\s*{field_label_pattern}\s*\|[ \t]*(?P<val>.*?)(?=\n\|(?!\|)|\Z)',
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
