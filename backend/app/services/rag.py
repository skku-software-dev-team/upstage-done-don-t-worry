import re
import uuid
from typing import Literal, TypeVar

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

T = TypeVar("T")

# Clause numbers ("2.1.5", "1.1.2") and law article numbers ("제34조",
# "제7조의2") — dense (embedding) search misses these because a bare number
# carries no semantic content, and a Korean question glues particles onto it
# with no space ("2.1.5는", "제34조가"), so even naive substring/tsvector
# matching misses too. Extracting the number and comparing directly against
# clause_no/article_no is the only approach proven correct so far.
#
# A broader keyword/tsvector fallback (matching arbitrary terms, not just
# numbers) was tried and reverted: on off-topic questions like "GDPR
# 요구사항 알려줘", generic OR-matching on common words ("요구사항") pulled in
# unrelated clauses with no relevance threshold to filter them, regressing
# the "no sources for off-topic questions" baseline behavior. Revisit only
# if a real (non-number) retrieval miss is measured — same rule the 0.63
# cosine threshold below was tuned under.
CLAUSE_NO_RE = re.compile(r"\d+(?:\.\d+){1,2}")
ARTICLE_NO_RE = re.compile(r"제\s?\d+조(?:의\s?\d+)?")

# RRF fusion constant — smaller than the usual default (60, tuned for
# thousands of candidates) since our corpus is only ~200 clauses/articles.
RRF_K = 10

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
        .where(distance < max_distance, Document.organization_id == organization_id)
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
        .where(distance < max_distance, Law.organization_id == organization_id)
        .order_by(distance)
        .limit(top_k)
    )
    return list(result.scalars().all())


async def search_clauses_by_keyword(
    db: AsyncSession, query: str, organization_id: uuid.UUID, top_n: int = 10
) -> list[Clause]:
    """Exact-match lookup on clause numbers ("2.1.5") extracted from the
    question by regex — catches what dense (embedding) search misses, since
    a bare number carries no semantic content for the embedding model."""
    results: list[Clause] = []
    seen: set = set()

    for no in CLAUSE_NO_RE.findall(query):
        stmt = (
            select(Clause)
            .options(selectinload(Clause.document))
            .join(Document, Document.id == Clause.document_id)
            .where(Clause.clause_no == no, Document.organization_id == organization_id)
        )
        for c in (await db.execute(stmt)).scalars().all():
            if c.id not in seen:
                seen.add(c.id)
                results.append(c)

    return results[:top_n]


async def search_articles_by_keyword(
    db: AsyncSession, query: str, organization_id: uuid.UUID, top_n: int = 10
) -> list[LawArticle]:
    """Same as search_clauses_by_keyword, for law articles ("제34조")."""
    results: list[LawArticle] = []
    seen: set = set()

    for no in ARTICLE_NO_RE.findall(query):
        no = no.replace(" ", "")
        stmt = (
            select(LawArticle)
            .options(selectinload(LawArticle.law))
            .join(Law, Law.id == LawArticle.law_id)
            .where(LawArticle.article_no == no, Law.organization_id == organization_id)
        )
        for a in (await db.execute(stmt)).scalars().all():
            if a.id not in seen:
                seen.add(a.id)
                results.append(a)

    return results[:top_n]


def _rrf_merge(dense_ranked: list[T], sparse_ranked: list[T], top_k: int = 3, k: int = RRF_K) -> list[T]:
    """Reciprocal Rank Fusion: combine two ranked lists using rank position
    only (not raw scores), since cosine distance and ts_rank live on
    unrelated scales. score(item) = sum of 1/(k + rank) across lists it
    appears in — an item ranked highly in either list, or moderately in
    both, rises to the top."""
    scores: dict = {}
    by_id: dict = {}
    for rank, item in enumerate(dense_ranked, start=1):
        scores[item.id] = scores.get(item.id, 0.0) + 1 / (k + rank)
        by_id[item.id] = item
    for rank, item in enumerate(sparse_ranked, start=1):
        scores[item.id] = scores.get(item.id, 0.0) + 1 / (k + rank)
        by_id[item.id] = item
    ordered_ids = sorted(scores, key=lambda i: scores[i], reverse=True)
    return [by_id[i] for i in ordered_ids[:top_k]]


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
        dense_clauses = await search_similar_clauses(db, question, organization_id, top_k=10, source_type="clause")
        sparse_clauses = await search_clauses_by_keyword(db, question, organization_id, top_n=10)
        clauses = _rrf_merge(dense_clauses, sparse_clauses, top_k=3)
        context_parts.extend(
            f"[{c.document.doc_type if c.document else '문서'} {c.clause_no}] {c.requirement}"
            for c in clauses
            if c.requirement
        )

    if source_type in ("law_article", "all"):
        dense_articles = await search_similar_articles(db, question, organization_id, top_k=10)
        sparse_articles = await search_articles_by_keyword(db, question, organization_id, top_n=10)
        articles = _rrf_merge(dense_articles, sparse_articles, top_k=3)
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
