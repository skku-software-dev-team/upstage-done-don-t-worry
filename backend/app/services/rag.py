import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.compliance import Clause, Embedding
from app.services.upstage import embed_text, chat_completion


async def search_similar_clauses(
    db: AsyncSession, query: str, top_k: int = 5
) -> list[Clause]:
    query_vec = await embed_text(query)

    result = await db.execute(
        select(Clause)
        .join(Embedding, Embedding.clause_id == Clause.id)
        .order_by(Embedding.embedding.cosine_distance(query_vec))
        .limit(top_k)
    )
    return list(result.scalars().all())


async def answer_with_rag(db: AsyncSession, question: str, org_id: uuid.UUID | None = None) -> tuple[str, list[Clause]]:
    sources = await search_similar_clauses(db, question)
    context = "\n\n".join(
        f"[{c.clause_no}] {c.title}\n{c.requirement}" for c in sources if c.requirement
    )
    answer = await chat_completion(
        messages=[{"role": "user", "content": question}],
        context=context,
    )
    return answer, sources
