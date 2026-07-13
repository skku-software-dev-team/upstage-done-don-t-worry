from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.compliance import CanonicalItem, CanonicalMap, Category, Clause, Embedding, LawArticle
from app.services.upstage import chat_completion, embed_text

SourceType = Literal["clause", "law_article", "all"]

# Cosine distance threshold for cross-document duplicate candidates.
# Lower = stricter. 0.35 (~0.65 cosine similarity) is a starting point —
# tune based on false positive/negative rate once tested against real data.
DUPLICATE_CANDIDATE_MAX_DISTANCE = 0.35


async def search_similar_clauses(
    db: AsyncSession,
    query: str,
    top_k: int = 5,
    source_type: SourceType = "all",
) -> list[Clause]:
    query_vec = await embed_text(query, is_query=True)

    stmt = (
        select(Clause)
        .join(Embedding, (Embedding.source_id == Clause.id) & (Embedding.source_type == "clause"))
        .order_by(Embedding.embedding.cosine_distance(query_vec))
        .limit(top_k)
    )
    if source_type == "law_article":
        return []

    result = await db.execute(stmt)
    return list(result.scalars().all())


async def search_similar_articles(
    db: AsyncSession,
    query: str,
    top_k: int = 5,
) -> list[LawArticle]:
    query_vec = await embed_text(query, is_query=True)

    result = await db.execute(
        select(LawArticle)
        .join(Embedding, (Embedding.source_id == LawArticle.id) & (Embedding.source_type == "law_article"))
        .order_by(Embedding.embedding.cosine_distance(query_vec))
        .limit(top_k)
    )
    return list(result.scalars().all())


async def find_similar_canonical_items(
    db: AsyncSession,
    query_vec: list[float],
    top_k: int = 3,
    max_distance: float = DUPLICATE_CANDIDATE_MAX_DISTANCE,
) -> list[dict]:
    """Shortlist existing canonical items that might be duplicates of a new
    clause, by comparing the new clause's embedding against the embeddings of
    clauses already linked to each canonical item via canonical_map.

    Returns compact dicts (id/title/category) meant to be shown to Solar as
    candidates, instead of the full canonical_items list.
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
        .where(distance < max_distance)
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
    source_type: SourceType = "all",
) -> tuple[str, list[Clause]]:
    clauses: list[Clause] = []
    context_parts: list[str] = []

    if source_type in ("clause", "all"):
        clauses = await search_similar_clauses(db, question, source_type="clause")
        context_parts.extend(
            f"[조항 {c.clause_no}] {c.requirement}" for c in clauses if c.requirement
        )

    if source_type in ("law_article", "all"):
        articles = await search_similar_articles(db, question)
        context_parts.extend(
            f"[법조문 {a.article_no}] {a.article_text}" for a in articles if a.article_text
        )

    answer = await chat_completion(
        messages=[{"role": "user", "content": question}],
        context="\n\n".join(context_parts),
    )
    return answer, clauses
