import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_admin_user, get_current_user
from app.core.database import get_db
from app.models.compliance import Invite, Organization, User
from app.schemas.compliance import InviteRead, MemberRead, OrganizationJiraUpdate, OrganizationRead
from app.services import jira

router = APIRouter(prefix="/org", tags=["org"], dependencies=[Depends(get_current_user)])

INVITE_EXPIRE_DAYS = 7


def _to_read(org: Organization) -> OrganizationRead:
    connected = bool(
        org.jira_base_url and org.jira_email and org.jira_api_token and org.jira_project_key
    )
    return OrganizationRead(
        id=org.id,
        name=org.name,
        jira_base_url=org.jira_base_url,
        jira_email=org.jira_email,
        jira_project_key=org.jira_project_key,
        jira_connected=connected,
        updated_at=org.updated_at,
    )


@router.get("", response_model=OrganizationRead)
async def get_org(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org = await db.get(Organization, current_user.organization_id)
    return _to_read(org)


@router.put("/jira", response_model=OrganizationRead)
async def connect_jira(
    body: OrganizationJiraUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org = await db.get(Organization, current_user.organization_id)
    org.jira_base_url = body.jira_base_url.rstrip("/")
    org.jira_email = body.jira_email
    org.jira_api_token = body.jira_api_token
    org.jira_project_key = body.jira_project_key
    # Resolve the numeric cloudId now so runtime calls can use the api.atlassian.com
    # gateway (required for scoped API tokens).
    org.jira_cloud_id = await jira.resolve_cloud_id(org.jira_base_url)
    await db.commit()
    await db.refresh(org)
    return _to_read(org)


@router.get("/members", response_model=list[MemberRead])
async def list_members(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.scalars(
        select(User)
        .options(selectinload(User.department))
        .where(User.organization_id == current_user.organization_id)
        .order_by(User.created_at)
    )
    return [
        MemberRead(
            id=u.id,
            email=u.email,
            name=u.name,
            department_name=u.department.name if u.department else None,
            role=u.role,
            created_at=u.created_at,
        )
        for u in result.all()
    ]


@router.get("/invites", response_model=list[InviteRead])
async def list_invites(current_user: User = Depends(get_current_admin_user), db: AsyncSession = Depends(get_db)):
    result = await db.scalars(
        select(Invite)
        .where(Invite.organization_id == current_user.organization_id)
        .order_by(Invite.created_at.desc())
    )
    return list(result.all())


@router.post("/invites", response_model=InviteRead, status_code=201)
async def create_invite(current_user: User = Depends(get_current_admin_user), db: AsyncSession = Depends(get_db)):
    invite = Invite(
        organization_id=current_user.organization_id,
        token=secrets.token_urlsafe(24),
        created_by_id=current_user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=INVITE_EXPIRE_DAYS),
    )
    db.add(invite)
    await db.commit()
    await db.refresh(invite)
    return invite


@router.delete("/invites/{invite_id}", status_code=204)
async def revoke_invite(
    invite_id: str,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    invite = await db.get(Invite, invite_id)
    if invite is None or invite.organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="초대를 찾을 수 없습니다.")
    await db.delete(invite)
    await db.commit()
