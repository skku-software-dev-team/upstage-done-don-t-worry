import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.compliance import (
    CanonicalItem,
    CanonicalMap,
    Category,
    Clause,
    Document,
    Organization,
    OrgStatus,
)
from app.services import jira
from app.schemas.compliance import (
    CategoryRead,
    ChecklistDocRef,
    ChecklistItemDetail,
    OrgStatusRead,
    OrgStatusUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/checklist", tags=["checklist"])


@router.get("/categories", response_model=list[CategoryRead])
async def list_categories(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Category).order_by(Category.name))
    return result.scalars().all()


@router.get("", response_model=list[ChecklistItemDetail])
async def list_canonical_items(
    category_id: uuid.UUID | None = Query(default=None, description="카테고리로 필터링"),
    document_id: uuid.UUID | None = Query(default=None, description="문서로 필터링"),
    db: AsyncSession = Depends(get_db),
):
    # canonical_item → category (name) and → clause → document (doc_type)
    stmt = (
        select(
            CanonicalItem.id,
            CanonicalItem.merged_title,
            CanonicalItem.category_id,
            Category.name.label("category_name"),
            Document.id.label("document_id"),
            Document.doc_type,
            Document.name.label("document_name"),
        )
        .outerjoin(Category, Category.id == CanonicalItem.category_id)
        .outerjoin(CanonicalMap, CanonicalMap.canonical_id == CanonicalItem.id)
        .outerjoin(Clause, Clause.id == CanonicalMap.clause_id)
        .outerjoin(Document, Document.id == Clause.document_id)
        .order_by(Category.name, CanonicalItem.merged_title, Document.doc_type)
    )
    if category_id is not None:
        stmt = stmt.where(CanonicalItem.category_id == category_id)
    if document_id is not None:
        stmt = stmt.where(Clause.document_id == document_id)

    result = await db.execute(stmt)

    # One canonical item can map to clauses in multiple documents (cross-doc
    # duplicate merge) — collapse those into a single row with multiple
    # document badges instead of repeating the row once per clause mapping.
    items: dict[uuid.UUID, ChecklistItemDetail] = {}
    for row in result.all():
        item = items.get(row.id)
        if item is None:
            item = ChecklistItemDetail(
                id=row.id,
                merged_title=row.merged_title,
                category_id=row.category_id,
                category_name=row.category_name,
                documents=[],
            )
            items[row.id] = item
        if row.document_id is not None and not any(
            d.document_id == row.document_id for d in item.documents
        ):
            item.documents.append(
                ChecklistDocRef(
                    document_id=row.document_id,
                    doc_type=row.doc_type,
                    document_name=row.document_name,
                )
            )

    return list(items.values())


@router.get("/org/{org_id}", response_model=list[OrgStatusRead])
async def list_org_status(org_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(OrgStatus))
    return result.scalars().all()


@router.put("/org/{org_id}/item/{canonical_id}", response_model=OrgStatusRead)
async def upsert_org_status(
    org_id: uuid.UUID,
    canonical_id: uuid.UUID,
    body: OrgStatusUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(OrgStatus).where(OrgStatus.canonical_id == canonical_id)
    )
    status = result.scalar_one_or_none()

    if status is None:
        status = OrgStatus(canonical_id=canonical_id, **body.model_dump())
        db.add(status)
    else:
        status.status = body.status
        if body.jira_key is not None:
            status.jira_key = body.jira_key

    # Lazy Jira ticket creation: first time an item reaches a tracked status
    # (미시작/진행중/완료) and has no linked ticket yet, create one that mirrors it.
    if status.jira_key is None and body.status in jira.CREATE_STATUSES:
        org = await db.get(Organization, org_id)
        if jira.is_connected(org):
            title = await db.scalar(
                select(CanonicalItem.merged_title).where(CanonicalItem.id == canonical_id)
            )
            try:
                status.jira_key = await jira.create_issue(
                    org, title or "체크리스트 항목", body.status
                )
            except Exception:  # Jira failure must not block the status update
                logger.exception("Jira issue creation failed for %s", canonical_id)

    await db.commit()
    await db.refresh(status)
    return status


@router.post("/org/{org_id}/jira/sync")
async def sync_from_jira(org_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    org = await db.get(Organization, org_id)
    if not jira.is_connected(org):
        raise HTTPException(status_code=400, detail="Jira가 연결되지 않았습니다.")

    rows = (
        await db.execute(select(OrgStatus).where(OrgStatus.jira_key.is_not(None)))
    ).scalars().all()
    keys = [r.jira_key for r in rows if r.jira_key]

    try:
        mapping = await jira.get_statuses(org, keys)
    except Exception as e:
        logger.exception("Jira sync failed")
        raise HTTPException(status_code=502, detail="Jira 동기화에 실패했습니다.") from e

    updated = 0
    for row in rows:
        new_status = mapping.get(row.jira_key or "")
        if new_status and new_status != row.status:
            row.status = new_status
            updated += 1

    await db.commit()
    return {"synced": len(keys), "updated": updated}


@router.get("/item/{canonical_id}/status", response_model=list[OrgStatusRead])
async def get_item_status(canonical_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(OrgStatus).where(OrgStatus.canonical_id == canonical_id)
    )
    return result.scalars().all()
