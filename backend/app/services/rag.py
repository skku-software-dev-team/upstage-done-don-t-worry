import json
import logging
import re
import uuid
from datetime import date, timedelta
from typing import Literal, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.compliance import (
    CanonicalItem,
    CanonicalMap,
    Category,
    Clause,
    ChecklistPeriod,
    Document,
    Embedding,
    Law,
    LawArticle,
    OrgStatus,
)
from app.services.upstage import chat_completion, chat_completion_with_tools, embed_text

logger = logging.getLogger(__name__)

SourceType = Literal["clause", "law_article", "all"]

T = TypeVar("T")

STATUS_LABELS = {
    "not_started": "미시작",
    "in_progress": "진행중",
    "completed": "완료",
    "not_applicable": "해당없음",
}

# Round-trips through Solar in the tool-calling loop before giving up on a
# final answer — guards against the model looping on tool calls forever.
MAX_TOOL_ITERATIONS = 4

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


async def search_checklist_history(
    db: AsyncSession,
    organization_id: uuid.UUID,
    status: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 30,
) -> list[dict]:
    """Query checklist completion history by status/date range — across every
    saved period, not just the current one. This is a structured DB lookup,
    not semantic search: "완료한 항목" is a status+timestamp filter on
    org_status, not something clause/law embeddings can answer."""

    def _parse(s) -> date | None:
        if not isinstance(s, str) or not s:
            return None
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            return None

    stmt = (
        select(
            CanonicalItem.merged_title,
            OrgStatus.status,
            OrgStatus.updated_at,
            ChecklistPeriod.label,
        )
        .join(CanonicalItem, CanonicalItem.id == OrgStatus.canonical_id)
        .join(ChecklistPeriod, ChecklistPeriod.id == OrgStatus.period_id)
        .where(OrgStatus.organization_id == organization_id)
        .order_by(OrgStatus.updated_at.desc())
        .limit(limit)
    )
    if status:
        stmt = stmt.where(OrgStatus.status == status)
    parsed_start = _parse(start_date)
    if parsed_start:
        stmt = stmt.where(OrgStatus.updated_at >= parsed_start)
    parsed_end = _parse(end_date)
    if parsed_end:
        stmt = stmt.where(OrgStatus.updated_at < parsed_end + timedelta(days=1))

    result = await db.execute(stmt)
    return [
        {
            "title": row.merged_title,
            "status": STATUS_LABELS.get(row.status, row.status),
            "updated_at": row.updated_at.date().isoformat(),
            "period": row.label,
        }
        for row in result.all()
    ]


def _build_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "search_document_clauses",
                "description": (
                    "업로드된 보안/컴플라이언스 가이드라인 문서(ISMS-P, CSAP, ISO27001 등)에서 "
                    "조항을 검색합니다. 인증기준, 요구사항 등 문서 내용에 대한 질문에 사용하세요."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "검색할 질문 또는 키워드"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_law_articles",
                "description": (
                    "업로드된 법률 문서(개인정보 보호법 등)에서 조문을 검색합니다. "
                    "법 조항, 법적 근거에 대한 질문에 사용하세요."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "검색할 질문 또는 키워드"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_checklist_history",
                "description": (
                    "조직의 체크리스트 완료 이력을 날짜/진행상태로 조회합니다. "
                    "'언제 뭘 완료했는지', '이번 달에 처리한 것' 등 히스토리·진행상황 질문에 "
                    "사용하세요. 조항 내용 자체를 찾는 질문에는 사용하지 마세요."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "enum": list(STATUS_LABELS.keys()),
                            "description": "필터링할 상태 (생략하면 전체 상태)",
                        },
                        "start_date": {
                            "type": "string",
                            "description": "조회 시작일, YYYY-MM-DD 형식 (생략 가능)",
                        },
                        "end_date": {
                            "type": "string",
                            "description": "조회 종료일, YYYY-MM-DD 형식 (생략 가능)",
                        },
                    },
                    "required": [],
                },
            },
        },
    ]


def _agent_system_prompt() -> str:
    today = date.today().isoformat()
    return (
        "당신은 정보보호 인증(ISMS-P, CSAP, ISO27001) 전문 어시스턴트입니다. "
        f"오늘 날짜는 {today}입니다.\n\n"
        "질문에 답하기 위해 필요하면 아래 도구를 사용하세요:\n"
        "- 인증기준/요구사항 등 문서 조항 내용 질문 → search_document_clauses\n"
        "- 법률/법조문 질문 → search_law_articles\n"
        "- '언제 뭘 완료했는지', '이번 달 진행상황' 등 체크리스트 이력/날짜 질문 → "
        "search_checklist_history (\"7월 후반\", \"지난주\" 같은 상대적 날짜 표현은 오늘 "
        "날짜를 기준으로 YYYY-MM-DD로 직접 환산해서 전달하세요)\n\n"
        "도구 결과에 없는 내용은 답하지 말고, 결과가 비어 있으면 모른다고 답하세요. "
        "일반 상식으로 채워 넣지 마세요. 문서 조항/법조문을 인용할 때는 결과에 표시된 "
        "[문서명 조항번호] 또는 [법률명 조항번호] 형식을 답변 문장 안에 그대로 살려서 쓰세요 "
        "(예: '[ISMS-P 2.4.1]에 따르면...'). "
        "인용하는 조항 번호와 문서명은 반드시 도구 결과에 실제로 등장한 [문서명 조항번호] "
        "태그를 글자 그대로 복사한 것이어야 합니다 — 비슷하거나 그럴듯해 보이는 번호를 "
        "새로 만들어내지 마세요. 도구를 아직 호출하지 않았거나 결과를 받기 전에는 조항 "
        "번호나 구체적 내용을 절대 미리 답하지 마세요.\n\n"
        "최종 답변 텍스트에는 도구/함수 이름(search_document_clauses 등)이나 호출 문법을 "
        "절대 언급하지 마세요 — 사용자는 내부적으로 어떤 도구가 쓰였는지 알 필요가 없습니다."
    )


# Injected as the tool result whenever a search comes back empty. Solar was
# observed to otherwise fall back to its own general knowledge and fabricate
# plausible-looking clause numbers (e.g. invented "ISMS-P 2.4.1"~"2.4.5")
# instead of admitting the corpus has nothing — a plain "검색 결과 없음" alone
# wasn't a strong enough signal to stop that. This spells out the required
# behavior directly inside the tool result so it's re-asserted every time,
# not just once in the system prompt.
NO_RESULTS_DIRECTIVE = (
    "검색 결과 없음. 업로드된 문서/법령/이력에 이 질문과 관련된 내용이 없습니다. "
    "일반 지식이나 추측으로 답을 채우지 말고, 반드시 '해당 내용을 찾을 수 없습니다'라고 "
    "답한 뒤 관련 문서를 업로드하라고 안내하세요. 이 규칙에는 예외가 없습니다."
)


def _format_clauses_for_tool(clauses: list[Clause]) -> str:
    if not clauses:
        return NO_RESULTS_DIRECTIVE
    return "\n\n".join(
        f"[{c.document.doc_type if c.document else '문서'} {c.clause_no}] {c.requirement}"
        for c in clauses
        if c.requirement
    ) or NO_RESULTS_DIRECTIVE


def _format_articles_for_tool(articles: list[LawArticle]) -> str:
    if not articles:
        return NO_RESULTS_DIRECTIVE
    return "\n\n".join(
        f"[{a.law.name if a.law else '법률'} {a.article_no}] {a.article_text}"
        for a in articles
        if a.article_text
    ) or NO_RESULTS_DIRECTIVE


def _format_history_for_tool(rows: list[dict]) -> str:
    if not rows:
        return "검색 결과 없음 (해당 조건에 맞는 체크리스트 이력이 없습니다. 이 사실을 그대로 답하세요.)"
    return "\n".join(
        f"- {r['title']} | 상태: {r['status']} | 최종 변경일: {r['updated_at']} | 기간: {r['period']}"
        for r in rows
    )


async def answer_with_rag(
    db: AsyncSession,
    question: str,
    organization_id: uuid.UUID,
    source_type: SourceType = "all",
) -> tuple[str, list[Clause], list[LawArticle]]:
    clauses: list[Clause] = []
    articles: list[LawArticle] = []

    tools = [
        t
        for t in _build_tools()
        if (source_type == "all")
        or (source_type == "clause" and t["function"]["name"] != "search_law_articles")
        or (source_type == "law_article" and t["function"]["name"] != "search_document_clauses")
    ]
    system_prompt = _agent_system_prompt()
    messages: list[dict] = [{"role": "user", "content": question}]
    answer = ""

    for _ in range(MAX_TOOL_ITERATIONS):
        message = await chat_completion_with_tools(messages, tools, system_prompt)
        tool_calls = message.get("tool_calls")

        if not tool_calls:
            answer = message.get("content") or ""
            break

        # Solar sometimes drafts a guessed answer in the same turn it
        # requests tools (before seeing real results). Echoing that guess
        # back as assistant history measurably biased later turns toward
        # repeating it instead of the actual tool output — so keep the
        # tool_calls (required to correlate the tool responses below) but
        # drop the premature content.
        messages.append({"role": "assistant", "content": None, "tool_calls": tool_calls})
        for call in tool_calls:
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}

            if name == "search_document_clauses":
                dense = await search_similar_clauses(
                    db, args.get("query", question), organization_id, top_k=10, source_type="clause"
                )
                sparse = await search_clauses_by_keyword(db, args.get("query", question), organization_id, top_n=10)
                found = _rrf_merge(dense, sparse, top_k=3)
                clauses.extend(c for c in found if c.id not in {x.id for x in clauses})
                tool_content = _format_clauses_for_tool(found)
            elif name == "search_law_articles":
                dense = await search_similar_articles(db, args.get("query", question), organization_id, top_k=10)
                sparse = await search_articles_by_keyword(db, args.get("query", question), organization_id, top_n=10)
                found = _rrf_merge(dense, sparse, top_k=3)
                articles.extend(a for a in found if a.id not in {x.id for x in articles})
                tool_content = _format_articles_for_tool(found)
            elif name == "search_checklist_history":
                history = await search_checklist_history(
                    db,
                    organization_id,
                    status=args.get("status"),
                    start_date=args.get("start_date"),
                    end_date=args.get("end_date"),
                )
                tool_content = _format_history_for_tool(history)
            else:
                tool_content = "알 수 없는 도구입니다."
                logger.warning("chat agent requested unknown tool: %s", name)

            messages.append({"role": "tool", "tool_call_id": call["id"], "content": tool_content})
    else:
        logger.warning("chat agent hit MAX_TOOL_ITERATIONS without a final answer")
        answer = "죄송합니다, 답변을 생성하지 못했습니다. 다시 시도해주세요."

    # Retrieval (any tool call) hands the LLM several candidates, but it only
    # ends up citing some of them. Only surface sources the answer actually
    # references — otherwise unused candidates show up as misleading "참고" entries.
    clauses = [c for c in clauses if not c.clause_no or c.clause_no in answer]
    articles = [a for a in articles if not a.article_no or a.article_no in answer]

    return answer, clauses, articles
