import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.compliance import (
    CanonicalItem,
    CanonicalMap,
    Category,
    Clause,
    Document,
    OrgStatus,
)
from app.schemas.compliance import (
    CategoryRead,
    ChecklistItemDetail,
    OrgStatusRead,
    OrgStatusUpdate,
)

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
        .order_by(Category.name, CanonicalItem.merged_title)
    )
    if category_id is not None:
        stmt = stmt.where(CanonicalItem.category_id == category_id)
    if document_id is not None:
        stmt = stmt.where(Clause.document_id == document_id)

    result = await db.execute(stmt)
    return [
        ChecklistItemDetail(
            id=row.id,
            merged_title=row.merged_title,
            category_id=row.category_id,
            category_name=row.category_name,
            document_id=row.document_id,
            doc_type=row.doc_type,
            document_name=row.document_name,
        )
        for row in result.all()
    ]


@router.get("/org/{org_id}", response_model=list[OrgStatusRead])
async def list_org_status(org_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(OrgStatus))
    return result.scalars().all()


@router.put("/org/{org_id}/item/{canonical_id}", response_model=OrgStatusRead)
async def upsert_org_status(
    org_id: str,
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

    await db.commit()
    await db.refresh(status)
    return status


@router.get("/item/{canonical_id}/status", response_model=list[OrgStatusRead])
async def get_item_status(canonical_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(OrgStatus).where(OrgStatus.canonical_id == canonical_id)
    )
    return result.scalars().all()
