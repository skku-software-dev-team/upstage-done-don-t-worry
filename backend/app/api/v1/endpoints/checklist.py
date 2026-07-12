import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.compliance import CanonicalItem, Category, OrgStatus
from app.schemas.compliance import CanonicalItemRead, CategoryRead, OrgStatusRead, OrgStatusUpdate

router = APIRouter(prefix="/checklist", tags=["checklist"])


@router.get("/categories", response_model=list[CategoryRead])
async def list_categories(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Category).order_by(Category.name))
    return result.scalars().all()


@router.get("", response_model=list[CanonicalItemRead])
async def list_canonical_items(
    category_id: uuid.UUID | None = Query(default=None, description="카테고리로 필터링"),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(CanonicalItem)
    if category_id is not None:
        stmt = stmt.where(CanonicalItem.category_id == category_id)
    result = await db.execute(stmt)
    return result.scalars().all()


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
