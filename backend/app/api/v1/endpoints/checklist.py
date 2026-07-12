import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.compliance import CanonicalItem, OrgStatus
from app.schemas.compliance import CanonicalItemRead, OrgStatusRead, OrgStatusUpdate

router = APIRouter(prefix="/checklist", tags=["checklist"])


@router.get("/", response_model=list[CanonicalItemRead])
async def list_canonical_items(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(CanonicalItem))
    return result.scalars().all()


@router.get("/org/{org_id}", response_model=list[OrgStatusRead])
async def org_checklist(org_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(OrgStatus).where(OrgStatus.org_id == org_id)
    )
    return result.scalars().all()


@router.put("/org/{org_id}/item/{canonical_id}", response_model=OrgStatusRead)
async def update_org_status(
    org_id: uuid.UUID,
    canonical_id: uuid.UUID,
    body: OrgStatusUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(OrgStatus).where(
            OrgStatus.org_id == org_id,
            OrgStatus.canonical_id == canonical_id,
        )
    )
    status = result.scalar_one_or_none()

    if status is None:
        status = OrgStatus(org_id=org_id, canonical_id=canonical_id, **body.model_dump())
        db.add(status)
    else:
        status.status = body.status
        if body.jira_key is not None:
            status.jira_key = body.jira_key

    await db.commit()
    await db.refresh(status)
    return status
