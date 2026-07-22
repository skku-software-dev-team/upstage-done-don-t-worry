import uuid
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.compliance import (
    CanonicalItem,
    CanonicalMap,
    Category,
    Clause,
    Document,
    Embedding,
    Law,
    LawArticle,
)
from app.services.upstage import chat_completion, embed_text

SourceType = Literal["clause", "law_article", "all"]

# Cosine distance threshold for cross-document duplicate candidates.
# Lower = stricter. 0.35 (~0.65 cosine similarity) is a starting point —
# tune based on false positive/negative rate once tested against real data.
DUPLICATE_CANDIDATE_MAX_DISTANCE = 0.35

# Cosine distance threshold for RAG retrieval relevance. Measured against
# real DB data: on-topic questions land clauses in the ~0.49-0.62 range and
# law articles in ~0.44-0.75; off-topic questions (e.g. asking about GDPR
# when no GDPR document is uploaded) land both in ~0.65-0.69. 0.63 sits in
# the gap so irrelevant top-k results get dropped instead of always padding
# the source list.
RELEVANCE_MAX_DISTANCE = 0.63


async def search_similar_clauses(
    db: AsyncSession,
    query: str,
    organization_id: uuid.UUID,
    top_k: int = 5,
    source_type: SourceType = "all",
    max_distance: float = RELEVANCE_MAX_DISTANCE,
) -> list[Clause]:
    query_vec = await embed_text(query, is_query=True)
    distance = Embedding.embedding.cosine_distance(query_vec)

    stmt = (
        select(Clause)
        .options(selectinload(Clause.document))
        .join(Document, Document.id == Clause.document_id)
        .join(Embedding, (Embedding.source_id == Clause.id) & (Embedding.source_type == "clause"))
        .where(
            distance < max_distance,
            Document.organization_id == organization_id,
            Document.is_active.is_(True),
        )
        .order_by(distance)
        .limit(top_k)
    )
    if source_type == "law_article":
        return []

    result = await db.execute(stmt)
    return list(result.scalars().all())


async def search_similar_articles(
    db: AsyncSession,
    query: str,
    organization_id: uuid.UUID,
    top_k: int = 5,
    max_distance: float = RELEVANCE_MAX_DISTANCE,
) -> list[LawArticle]:
    query_vec = await embed_text(query, is_query=True)
    distance = Embedding.embedding.cosine_distance(query_vec)

    result = await db.execute(
        select(LawArticle)
        .options(selectinload(LawArticle.law))
        .join(Law, Law.id == LawArticle.law_id)
        .join(Embedding, (Embedding.source_id == LawArticle.id) & (Embedding.source_type == "law_article"))
        .where(
            distance < max_distance,
            Law.organization_id == organization_id,
            Law.is_active.is_(True),
        )
        .order_by(distance)
        .limit(top_k)
    )
    return list(result.scalars().all())


async def find_similar_canonical_items(
    db: AsyncSession,
    query_vec: list[float],
    organization_id: uuid.UUID,
    top_k: int = 3,
    max_distance: float = DUPLICATE_CANDIDATE_MAX_DISTANCE,
) -> list[dict]:
    """Shortlist existing canonical items that might be duplicates of a new
    clause, by comparing the new clause's embedding against the embeddings of
    clauses already linked to each canonical item via canonical_map.

    Returns compact dicts (id/title/category) meant to be shown to Solar as
    candidates, instead of the full canonical_items list.

    Deliberately not filtered by Document.is_active: when a revised guideline
    is uploaded and the old one gets deactivated, this is what lets Solar match
    the new clause back onto the same canonical item instead of forking a
    duplicate — keeping the checklist item (and its status history) continuous
    across the version change.
    """
    distance = Embedding.embedding.cosine_distance(query_vec)
    stmt = (
        select(
            CanonicalItem.id,
            CanonicalItem.merged_title,
            Category.name.label("category_name"),
            distance.label("distance"),
        )
        .join(CanonicalMap, CanonicalMap.canonical_id == CanonicalItem.id)
        .join(Embedding, (Embedding.source_id == CanonicalMap.clause_id) & (Embedding.source_type == "clause"))
        .outerjoin(Category, Category.id == CanonicalItem.category_id)
        .where(distance < max_distance, CanonicalItem.organization_id == organization_id)
        .order_by(distance)
        .limit(top_k * 3)  # over-fetch, then dedupe by canonical id below
    )
    result = await db.execute(stmt)

    seen: set = set()
    candidates: list[dict] = []
    for row in result.all():
        if row.id in seen:
            continue
        seen.add(row.id)
        candidates.append({"id": str(row.id), "title": row.merged_title, "category": row.category_name or ""})
        if len(candidates) >= top_k:
            break
    return candidates


async def answer_with_rag(
    db: AsyncSession,
    question: str,
    organization_id: uuid.UUID,
    source_type: SourceType = "all",
) -> tuple[str, list[Clause], list[LawArticle]]:
    clauses: list[Clause] = []
    articles: list[LawArticle] = []
    context_parts: list[str] = []

    if source_type in ("clause", "all"):
        clauses = await search_similar_clauses(db, question, organization_id, top_k=3, source_type="clause")
        context_parts.extend(
            f"[{c.document.doc_type if c.document else '문서'} {c.clause_no}] {c.requirement}"
            for c in clauses
            if c.requirement
        )

    if source_type in ("law_article", "all"):
        articles = await search_similar_articles(db, question, organization_id, top_k=3)
        context_parts.extend(
            f"[{a.law.name if a.law else '법률'} {a.article_no}] {a.article_text}"
            for a in articles
            if a.article_text
        )

    answer = await chat_completion(
        messages=[{"role": "user", "content": question}],
        context="\n\n".join(context_parts),
    )

    # Retrieval hands the LLM several candidates, but it only ends up citing
    # some of them. Only surface sources the answer actually references —
    # otherwise unused candidates show up as misleading "참고" entries.
    clauses = [c for c in clauses if not c.clause_no or c.clause_no in answer]
    articles = [a for a in articles if not a.article_no or a.article_no in answer]

    return answer, clauses, articles
