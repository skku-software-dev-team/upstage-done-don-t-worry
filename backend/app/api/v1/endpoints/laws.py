import re
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.compliance import Clause, ClauseLawRef, Embedding, Law, LawArticle
from app.schemas.compliance import LawArticleRead, LawCreate, LawRead
from app.services.upstage import embed_text, parse_document

router = APIRouter(prefix="/laws", tags=["laws"])

# "제29조" or "제29조의2" — the standard Korean statute article-number format.
ARTICLE_HEADER_PATTERN = re.compile(r'^제\s*(\d+조(?:의\d+)?)\s*(?:\(([^)]*)\))?', re.MULTILINE)
ARTICLE_REF_PATTERN = re.compile(r'제\s*\d+조(?:의\d+)?')


@router.get("", response_model=list[LawRead])
async def list_laws(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Law).order_by(Law.name))
    return result.scalars().all()


@router.post("", response_model=LawRead, status_code=201)
async def create_law(body: LawCreate, db: AsyncSession = Depends(get_db)):
    law = Law(**body.model_dump())
    db.add(law)
    await db.commit()
    await db.refresh(law)
    return law


@router.delete("/{law_id}", status_code=204)
async def delete_law(law_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    law = await db.get(Law, law_id)
    if not law:
        raise HTTPException(404, "Law not found")
    await db.delete(law)
    await db.commit()


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

    md = (parsed.get("content") or {}).get("markdown", "").strip()
    if not md:
        md = (parsed.get("content") or {}).get("text", "").strip()

    raw_articles = _segment_law(md)

    created_articles: list[LawArticle] = []
    for a in raw_articles:
        article = LawArticle(law_id=law_id, article_no=a["article_no"], article_text=a["article_text"])
        db.add(article)
        await db.flush()
        created_articles.append(article)
    await db.commit()

    for article in created_articles:
        if not article.article_text:
            continue
        vec = await embed_text(article.article_text)
        db.add(Embedding(source_type="law_article", source_id=article.id, embedding=vec))
    await db.commit()

    linked = await _link_clauses_to_law(db, law, created_articles)

    return {
        "message": "파싱 및 조항 연결 완료",
        "articles": len(created_articles),
        "linked_clauses": linked,
    }


def _segment_law(md: str) -> list[dict]:
    """Segment law text into articles using '제N조(제목)' headers.
    Falls back to blank-line paragraph splitting (no article_no) if fewer
    than 3 article headers are found — e.g. a short amendment excerpt
    rather than a full statute."""
    if not md:
        return []

    matches = list(ARTICLE_HEADER_PATTERN.finditer(md))
    if len(matches) < 3:
        return [
            {"article_no": None, "article_text": p.strip()}
            for p in re.split(r'\n{2,}', md)
            if p.strip()
        ]

    articles: list[dict] = []
    for i, m in enumerate(matches):
        article_no = "제" + m.group(1)
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md)
        text = md[start:end].strip()
        articles.append({"article_no": article_no, "article_text": text or None})
    return articles


def _matched_articles(text: str, article_by_no: dict[str, LawArticle]) -> list[LawArticle]:
    """Extract '제N조' references from text and resolve them against a
    {article_no: LawArticle} map, dropping anything that doesn't match a
    parsed article.

    A reference that doesn't resolve (typo, or an article outside what was
    uploaded) is silently dropped rather than recorded — ClauseLawRef.article_id
    is a required part of its composite primary key, so there's no
    "unmatched, needs manual review" row to create for that case with the
    current schema. Only real regex matches are recorded (match_method='regex').
    """
    found_nos = {m.group().replace(" ", "") for m in ARTICLE_REF_PATTERN.finditer(text)}
    return [article_by_no[no] for no in found_nos if no in article_by_no]


async def _link_clauses_to_law(db: AsyncSession, law: Law, articles: list[LawArticle]) -> int:
    """Called after a law's articles are parsed: find existing clauses whose
    related_laws_raw mentions this law by name and link the ones citing an
    article we just parsed."""
    article_by_no = {a.article_no: a for a in articles if a.article_no}
    if not article_by_no:
        return 0

    candidates = (
        await db.execute(
            select(Clause).where(Clause.related_laws_raw.ilike(f"%{law.name}%"))
        )
    ).scalars().all()

    linked = 0
    for clause in candidates:
        if not clause.related_laws_raw:
            continue
        for article in _matched_articles(clause.related_laws_raw, article_by_no):
            db.add(ClauseLawRef(clause_id=clause.id, article_id=article.id, match_method="regex"))
            linked += 1

    if linked:
        await db.commit()
    return linked


async def link_new_clauses_to_laws(db: AsyncSession, clauses: list[Clause]) -> int:
    """Reverse direction of _link_clauses_to_law: called after a compliance
    document (ISMS-P/CSAP/...) is parsed, so clauses that reference a law
    already uploaded get linked too, regardless of which was uploaded first."""
    mentionable = [c for c in clauses if c.related_laws_raw]
    if not mentionable:
        return 0

    laws = (await db.execute(select(Law))).scalars().all()
    if not laws:
        return 0

    linked = 0
    for law in laws:
        matching_clauses = [c for c in mentionable if law.name in c.related_laws_raw]
        if not matching_clauses:
            continue
        articles = (
            await db.execute(select(LawArticle).where(LawArticle.law_id == law.id))
        ).scalars().all()
        article_by_no = {a.article_no: a for a in articles if a.article_no}
        if not article_by_no:
            continue
        for clause in matching_clauses:
            for article in _matched_articles(clause.related_laws_raw, article_by_no):
                db.add(ClauseLawRef(clause_id=clause.id, article_id=article.id, match_method="regex"))
                linked += 1

    if linked:
        await db.commit()
    return linked
