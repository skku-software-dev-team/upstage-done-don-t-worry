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

# English security acronyms the embedding model doesn't reliably bridge to the
# Korean phrasing these documents actually use — measured against ISMS-P
# 2.5.3's "강화된 인증방식" clause, cosine distance (relevance cutoff is 0.63,
# see RELEVANCE_MAX_DISTANCE):
#   "MFA" alone                                          -> 0.93
#   "MFA가 ISMS-P의 어떤 부분을 만족하는거야?" (unmodified) -> 0.67
#   same question with "MFA" appended-not-replaced        -> 0.70 (worse!)
#   same question with "MFA" substituted in place          -> 0.54
# Substituting in place (not appending) is what actually closes the gap —
# it keeps the rest of the question's sentence structure intact, which
# measurably matters more than just having the right words present somewhere
# in the text. One primary Korean term per acronym, not several: testing
# showed piling on synonyms ("다중 인증 강화된 인증방식 이중 인증") scored
# *worse* than the single closest-matching term alone.
ACRONYM_SYNONYMS: dict[str, str] = {
    "MFA": "강화된 인증방식",
    "2FA": "이중 인증",
    "SSO": "통합 인증",
    "OTP": "일회용 비밀번호",
    "RBAC": "역할기반 접근통제",
    "IAM": "계정 및 권한 관리",
    "DLP": "정보유출 방지",
    "SIEM": "보안관제",
    "VPN": "가상사설망",
    "WAF": "웹방화벽",
    "IDS": "침입탐지",
    "IPS": "침입차단",
    "SOC": "보안관제센터",
    "DR": "재해복구",
    "BCP": "업무연속성계획",
    "KMS": "암호키 관리",
    "MDM": "모바일 기기 관리",
    "EDR": "엔드포인트 탐지대응",
}
# (?<![A-Za-z0-9]) / (?![A-Za-z0-9]) instead of \b: Korean questions glue
# particles straight onto the acronym with no space ("MFA가", "SSO는") — \b
# doesn't fire there because Python's \w treats Hangul as a word character
# too, so "A" and "가" don't count as a boundary. Only ASCII letters/digits
# should block a match (so "SOC" doesn't match inside "SOCIAL").
ACRONYM_RE = re.compile(
    r"(?<![A-Za-z0-9])(" + "|".join(re.escape(k) for k in ACRONYM_SYNONYMS) + r")(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def _expand_query_for_embedding(query: str) -> str:
    """Substitute recognized English security acronyms with their Korean
    equivalent in place before embedding (see ACRONYM_SYNONYMS comment for
    why substitution, not appending). No-op if the query has none of these
    acronyms."""
    return ACRONYM_RE.sub(lambda m: ACRONYM_SYNONYMS[m.group(1).upper()], query)


async def search_similar_clauses(
    db: AsyncSession,
    query: str,
    organization_id: uuid.UUID,
    top_k: int = 5,
    source_type: SourceType = "all",
    max_distance: float = RELEVANCE_MAX_DISTANCE,
) -> list[Clause]:
    query_vec = await embed_text(_expand_query_for_embedding(query), is_query=True)
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
    query_vec = await embed_text(_expand_query_for_embedding(query), is_query=True)
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


def _norm_text(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


async def _match_clauses_for_diff(
    db: AsyncSession, old_doc_id: uuid.UUID, new_doc_id: uuid.UUID
) -> tuple[list[Clause], list[Clause], list[tuple[Clause, Clause]], list[tuple[Clause, Clause]]]:
    """Classify every clause between two document versions as added / removed /
    modified / unchanged. Matching is layered, most-confident first:
    1. clauses already linked to the same CanonicalItem via CanonicalMap —
       reuses the Solar-driven duplicate detection that already ran at upload
       time, so a clause that got renumbered or reworded but is still the same
       requirement still matches.
    2. exact clause_no match, for whatever step 1 didn't resolve.
    3. exact title match, for whatever step 2 didn't resolve.
    Anything left unmatched on the new side is added; on the old side, removed.

    Returns (added_clauses, removed_clauses, modified_pairs, unchanged_pairs).
    """
    old_clauses = (
        await db.execute(select(Clause).where(Clause.document_id == old_doc_id))
    ).scalars().all()
    new_clauses = (
        await db.execute(select(Clause).where(Clause.document_id == new_doc_id))
    ).scalars().all()

    all_clause_ids = [c.id for c in old_clauses] + [c.id for c in new_clauses]
    canonical_by_clause: dict[uuid.UUID, uuid.UUID] = {}
    if all_clause_ids:
        rows = await db.execute(
            select(CanonicalMap.clause_id, CanonicalMap.canonical_id).where(
                CanonicalMap.clause_id.in_(all_clause_ids)
            )
        )
        for clause_id, canonical_id in rows.all():
            canonical_by_clause.setdefault(clause_id, canonical_id)

    matched_old_ids: set[uuid.UUID] = set()
    matched_new_ids: set[uuid.UUID] = set()
    pairs: list[tuple[Clause, Clause]] = []

    old_by_canonical: dict[uuid.UUID, Clause] = {}
    for c in old_clauses:
        cid = canonical_by_clause.get(c.id)
        if cid is not None:
            old_by_canonical.setdefault(cid, c)
    new_by_canonical: dict[uuid.UUID, Clause] = {}
    for c in new_clauses:
        cid = canonical_by_clause.get(c.id)
        if cid is not None:
            new_by_canonical.setdefault(cid, c)
    for cid, old_c in old_by_canonical.items():
        new_c = new_by_canonical.get(cid)
        if new_c is not None:
            pairs.append((old_c, new_c))
            matched_old_ids.add(old_c.id)
            matched_new_ids.add(new_c.id)

    old_by_no = {c.clause_no: c for c in old_clauses if c.id not in matched_old_ids and c.clause_no}
    new_by_no = {c.clause_no: c for c in new_clauses if c.id not in matched_new_ids and c.clause_no}
    for no, old_c in old_by_no.items():
        new_c = new_by_no.get(no)
        if new_c is not None:
            pairs.append((old_c, new_c))
            matched_old_ids.add(old_c.id)
            matched_new_ids.add(new_c.id)

    old_by_title = {_norm_text(c.title): c for c in old_clauses if c.id not in matched_old_ids and _norm_text(c.title)}
    new_by_title = {_norm_text(c.title): c for c in new_clauses if c.id not in matched_new_ids and _norm_text(c.title)}
    for title, old_c in old_by_title.items():
        new_c = new_by_title.get(title)
        if new_c is not None:
            pairs.append((old_c, new_c))
            matched_old_ids.add(old_c.id)
            matched_new_ids.add(new_c.id)

    added = [c for c in new_clauses if c.id not in matched_new_ids]
    removed = [c for c in old_clauses if c.id not in matched_old_ids]
    modified = [(o, n) for o, n in pairs if _norm_text(o.requirement) != _norm_text(n.requirement)]
    modified_ids = {n.id for _, n in modified}
    unchanged = [(o, n) for o, n in pairs if n.id not in modified_ids]

    return added, removed, modified, unchanged


async def compare_document_versions(
    db: AsyncSession, organization_id: uuid.UUID, doc_type_query: str
) -> str:
    """Find the current version of a document (by doc_type or name, fuzzy
    match) and its most recent earlier version, then return a text block
    listing added/removed/modified clauses for Solar to read and explain in
    its own words — this tool deliberately does NOT generate the explanation
    itself, it just hands Solar the raw before/after clause text.

    "Current" = the active document among matches (or the newest match if
    none are active); "previous" = the newest match created before that one.
    No explicit supersedes link is stored — created_at + doc_type is what
    every other version-supersession feature in this app already relies on
    (see documents.py's is_active toggling).
    """
    doc_type_query = (doc_type_query or "").strip()
    if not doc_type_query:
        return "비교할 문서 유형을 알 수 없습니다."

    docs = (
        await db.execute(select(Document).where(Document.organization_id == organization_id))
    ).scalars().all()
    if not docs:
        return "업로드된 문서가 없습니다."

    q = doc_type_query.lower()
    matching = [d for d in docs if q in d.doc_type.lower() or q in d.name.lower()]
    if not matching:
        return f"'{doc_type_query}'에 해당하는 문서를 찾을 수 없습니다."

    active_matches = [d for d in matching if d.is_active]
    new_doc = max(active_matches, key=lambda d: d.created_at) if active_matches else max(matching, key=lambda d: d.created_at)

    # <= (not <): Postgres's now() is transaction-time, so two documents
    # created in the same transaction/millisecond can carry an identical
    # timestamp — id != new_doc.id already rules out comparing new_doc to itself.
    older = [d for d in matching if d.id != new_doc.id and d.created_at <= new_doc.created_at]
    if not older:
        return f"'{new_doc.name}'과 비교할 이전 버전 문서를 찾을 수 없습니다."
    old_doc = max(older, key=lambda d: d.created_at)

    added, removed, modified, unchanged = await _match_clauses_for_diff(db, old_doc.id, new_doc.id)

    if not added and not removed and not modified:
        return f"[{old_doc.name}] → [{new_doc.name}] 비교 결과: 변경된 조항이 없습니다 (동일 {len(unchanged)}개)."

    # Cap how many "동일한 조항" get listed by identity — this is here purely so
    # Solar has real clause_no/title to cite if it mentions unchanged clauses at
    # all; it was observed inventing a plausible-looking clause number when the
    # tool only reported a bare count with nothing concrete backing it.
    UNCHANGED_LIST_CAP = 15

    parts = [f"[{old_doc.name}] (이전) → [{new_doc.name}] (신규) 비교 결과"]
    if modified:
        parts.append(f"\n변경된 조항 ({len(modified)}개):")
        for old_c, new_c in modified:
            no = new_c.clause_no or old_c.clause_no or "?"
            title = new_c.title or old_c.title or ""
            parts.append(
                f"- {no} {title}\n  이전: {old_c.requirement or '(내용 없음)'}\n  신규: {new_c.requirement or '(내용 없음)'}"
            )
    if added:
        parts.append(f"\n추가된 조항 ({len(added)}개):")
        for c in added:
            parts.append(f"- {c.clause_no or '?'} {c.title or ''}: {c.requirement or '(내용 없음)'}")
    if removed:
        parts.append(f"\n삭제된 조항 ({len(removed)}개):")
        for c in removed:
            parts.append(f"- {c.clause_no or '?'} {c.title or ''}: {c.requirement or '(내용 없음)'}")
    if unchanged:
        parts.append(f"\n동일한 조항 ({len(unchanged)}개):")
        for _, new_c in unchanged[:UNCHANGED_LIST_CAP]:
            parts.append(f"- {new_c.clause_no or '?'} {new_c.title or ''}")
        if len(unchanged) > UNCHANGED_LIST_CAP:
            parts.append(f"- ... 외 {len(unchanged) - UNCHANGED_LIST_CAP}개")

    return "\n".join(parts)


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
        {
            "type": "function",
            "function": {
                "name": "compare_document_versions",
                "description": (
                    "같은 종류 문서의 최신 버전과 그 이전 버전을 비교해서 추가/삭제/변경된 "
                    "조항을 조회합니다. '이번 개정판에서 뭐가 바뀌었어', '작년 버전이랑 "
                    "달라진 점' 같은 문서 버전 비교 질문에 사용하세요. 특정 조항 하나의 "
                    "내용을 묻는 질문에는 사용하지 마세요."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "doc_type": {
                            "type": "string",
                            "description": "비교할 문서의 유형 또는 이름 (예: ISMS-P, CSAP)",
                        },
                    },
                    "required": ["doc_type"],
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
        "날짜를 기준으로 YYYY-MM-DD로 직접 환산해서 전달하세요)\n"
        "- '이번 개정판에서 뭐가 바뀌었어', '작년 버전이랑 달라진 점' 등 문서 버전 비교 질문 → "
        "compare_document_versions. 도구 결과에는 조항별 이전/신규 원문이 그대로 담겨 있으니, "
        "그 내용을 직접 비교해서 무엇이 어떻게 달라졌는지 자연스러운 문장으로 요약해서 "
        "답하세요 (도구가 이미 판단한 추가/삭제/변경 분류를 그대로 나열하지만 말고, 각 "
        "변경이 실질적으로 무슨 의미인지 설명하세요).\n\n"
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
            elif name == "compare_document_versions":
                tool_content = await compare_document_versions(db, organization_id, args.get("doc_type", ""))
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
