import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.compliance import (
    CanonicalItem,
    CanonicalMap,
    Category,
    ChecklistPeriod,
    Clause,
    Department,
    Document,
    Organization,
    OrgStatus,
    User,
)
from app.services import jira
from app.services.upstage import assign_departments_batch, is_transient_upstage_error
from app.schemas.compliance import (
    CategoryRead,
    ChecklistDocRef,
    ChecklistItemDetail,
    ChecklistPeriodCreate,
    ChecklistPeriodRead,
    DepartmentRead,
    OrgStatusRead,
    OrgStatusUpdate,
)

# Solar call size for department assignment — small enough to keep each
# chat_completion() call's prompt/response comfortably under its timeout,
# and small enough that a retry after a mid-run failure only redoes one
# batch's worth of items instead of the whole org's checklist.
_DEPARTMENT_ASSIGN_BATCH_SIZE = 40

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/checklist", tags=["checklist"], dependencies=[Depends(get_current_user)])


async def _get_current_period(db: AsyncSession, organization_id: uuid.UUID) -> ChecklistPeriod:
    result = await db.execute(
        select(ChecklistPeriod).where(
            ChecklistPeriod.organization_id == organization_id,
            ChecklistPeriod.is_current.is_(True),
        )
    )
    period = result.scalar_one_or_none()
    if period is None:
        period = ChecklistPeriod(organization_id=organization_id, label="진행중", is_current=True)
        db.add(period)
        await db.commit()
        await db.refresh(period)
    return period


@router.get("/categories", response_model=list[CategoryRead])
async def list_categories(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Category).order_by(Category.name))
    return result.scalars().all()


@router.get("/departments", response_model=list[DepartmentRead])
async def list_departments(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Department).order_by(Department.name))
    return result.scalars().all()


@router.get("", response_model=list[ChecklistItemDetail])
async def list_canonical_items(
    category_id: uuid.UUID | None = Query(default=None, description="카테고리로 필터링"),
    department_id: uuid.UUID | None = Query(default=None, description="부서로 필터링"),
    document_id: uuid.UUID | None = Query(default=None, description="문서로 필터링"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # canonical_item → category/department (name) and → clause → document (doc_type)
    stmt = (
        select(
            CanonicalItem.id,
            CanonicalItem.merged_title,
            CanonicalItem.category_id,
            Category.name.label("category_name"),
            CanonicalItem.department_id,
            Department.name.label("department_name"),
            Document.id.label("document_id"),
            Document.doc_type,
            Document.name.label("document_name"),
        )
        .where(CanonicalItem.organization_id == current_user.organization_id)
        .outerjoin(Category, Category.id == CanonicalItem.category_id)
        .outerjoin(Department, Department.id == CanonicalItem.department_id)
        .outerjoin(CanonicalMap, CanonicalMap.canonical_id == CanonicalItem.id)
        .outerjoin(Clause, Clause.id == CanonicalMap.clause_id)
        .outerjoin(Document, Document.id == Clause.document_id)
        .order_by(Category.name, CanonicalItem.merged_title, Document.doc_type)
    )
    if category_id is not None:
        stmt = stmt.where(CanonicalItem.category_id == category_id)
    if department_id is not None:
        stmt = stmt.where(CanonicalItem.department_id == department_id)
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
                department_id=row.department_id,
                department_name=row.department_name,
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


@router.post("/assign-departments")
async def assign_departments(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """On-demand (button-triggered, not run during upload) — classifies every
    checklist item that doesn't have a department yet, in Solar calls capped
    at _DEPARTMENT_ASSIGN_BATCH_SIZE items each, committing after every batch.
    Deliberately not part of the upload pipeline: that already risks Upstage
    timeouts on its own Solar call (category assignment), and piling another
    whole-document Solar call on top of it would only make that worse. Each
    batch commits before the next one starts, so a 503 (retried once by the
    frontend, same as document/law upload) just resumes from whatever's still
    unassigned instead of redoing already-classified items."""
    rows = (
        await db.execute(
            select(CanonicalItem.id, CanonicalItem.merged_title, Category.name.label("category_name"))
            .outerjoin(Category, Category.id == CanonicalItem.category_id)
            .where(
                CanonicalItem.organization_id == current_user.organization_id,
                CanonicalItem.department_id.is_(None),
            )
        )
    ).all()

    if not rows:
        return {"assigned": 0, "remaining": 0}

    dept_rows = (await db.execute(select(Department))).scalars().all()
    dept_id_by_name = {d.name: d.id for d in dept_rows}
    department_names = sorted(dept_id_by_name)

    items = [
        {"id": str(r.id), "title": r.merged_title, "category": r.category_name or "미분류"}
        for r in rows
    ]

    assigned = 0
    for start in range(0, len(items), _DEPARTMENT_ASSIGN_BATCH_SIZE):
        batch = items[start : start + _DEPARTMENT_ASSIGN_BATCH_SIZE]
        try:
            assignments = await assign_departments_batch(batch, department_names)
        except Exception as e:
            if is_transient_upstage_error(e):
                raise HTTPException(503, detail="document_parse_timeout") from e
            raise

        for item_id_str, dept_name in assignments.items():
            dept_id = dept_id_by_name.get(dept_name)
            if dept_id is None:
                continue
            try:
                item_id = uuid.UUID(item_id_str)
            except ValueError:
                continue
            canonical = await db.get(CanonicalItem, item_id)
            if canonical is not None and canonical.organization_id == current_user.organization_id:
                canonical.department_id = dept_id
                assigned += 1
        await db.commit()

    return {"assigned": assigned, "remaining": len(items) - assigned}


@router.get("/periods", response_model=list[ChecklistPeriodRead])
async def list_periods(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ChecklistPeriod)
        .where(ChecklistPeriod.organization_id == current_user.organization_id)
        .order_by(ChecklistPeriod.created_at.desc())
    )
    return result.scalars().all()


@router.post("/periods", response_model=ChecklistPeriodRead)
async def save_period(
    body: ChecklistPeriodCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    current = await _get_current_period(db, current_user.organization_id)

    new_period = ChecklistPeriod(
        organization_id=current_user.organization_id,
        label=body.label,
        start_date=body.start_date,
        end_date=body.end_date,
        is_current=False,
    )
    db.add(new_period)
    await db.flush()

    rows = (
        await db.execute(select(OrgStatus).where(OrgStatus.period_id == current.id))
    ).scalars().all()
    for row in rows:
        db.add(
            OrgStatus(
                organization_id=current_user.organization_id,
                canonical_id=row.canonical_id,
                period_id=new_period.id,
                status=row.status,
                jira_key=row.jira_key,
            )
        )

    await db.commit()
    await db.refresh(new_period)
    return new_period


@router.get("/status", response_model=list[OrgStatusRead])
async def list_org_status(
    period_id: uuid.UUID | None = Query(default=None, description="기간 ID (없으면 진행중 기간)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if period_id is None:
        period_id = (await _get_current_period(db, current_user.organization_id)).id
    result = await db.execute(
        select(OrgStatus).where(
            OrgStatus.organization_id == current_user.organization_id,
            OrgStatus.period_id == period_id,
        )
    )
    return result.scalars().all()


@router.put("/item/{canonical_id}", response_model=OrgStatusRead)
async def upsert_org_status(
    canonical_id: uuid.UUID,
    body: OrgStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    period_id = body.period_id
    if period_id is None:
        period_id = (await _get_current_period(db, current_user.organization_id)).id

    result = await db.execute(
        select(OrgStatus).where(
            OrgStatus.organization_id == current_user.organization_id,
            OrgStatus.canonical_id == canonical_id,
            OrgStatus.period_id == period_id,
        )
    )
    status = result.scalar_one_or_none()

    if status is None:
        status = OrgStatus(
            organization_id=current_user.organization_id,
            canonical_id=canonical_id,
            period_id=period_id,
            status=body.status,
            jira_key=body.jira_key,
        )
        db.add(status)
    else:
        status.status = body.status
        if body.jira_key is not None:
            status.jira_key = body.jira_key

    # Lazy Jira ticket creation: first time an item reaches a tracked status
    # (미시작/진행중/완료) and has no linked ticket yet, create one that mirrors it.
    if status.jira_key is None and body.status in jira.CREATE_STATUSES:
        org = await db.get(Organization, current_user.organization_id)
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


@router.post("/jira/sync")
async def sync_from_jira(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org = await db.get(Organization, current_user.organization_id)
    if not jira.is_connected(org):
        raise HTTPException(status_code=400, detail="Jira가 연결되지 않았습니다.")

    rows = (
        await db.execute(
            select(OrgStatus).where(
                OrgStatus.organization_id == current_user.organization_id,
                OrgStatus.jira_key.is_not(None),
            )
        )
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
async def get_item_status(
    canonical_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(OrgStatus).where(
            OrgStatus.organization_id == current_user.organization_id,
            OrgStatus.canonical_id == canonical_id,
        )
    )
    return result.scalars().all()
