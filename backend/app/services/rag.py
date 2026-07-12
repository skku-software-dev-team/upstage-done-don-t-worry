from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.compliance import Clause, Embedding, LawArticle
from app.services.upstage import chat_completion, embed_text

SourceType = Literal["clause", "law_article", "all"]


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
