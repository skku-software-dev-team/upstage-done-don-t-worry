from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.models.compliance import Invite, Organization, User
from app.schemas.compliance import (
    AcceptInviteRequest,
    AuthMeResponse,
    LoginRequest,
    OrganizationRead,
    SignupRequest,
    TokenResponse,
    UserRead,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=TokenResponse, status_code=201)
async def signup(body: SignupRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.scalar(select(User).where(User.email == body.email))
    if existing is not None:
        raise HTTPException(status_code=400, detail="이미 가입된 이메일입니다.")

    org = Organization(name=body.org_name)
    db.add(org)
    await db.flush()

    user = User(
        organization_id=org.id,
        email=body.email,
        hashed_password=hash_password(body.password),
        role="admin",
    )
    db.add(user)
    await db.commit()

    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/accept-invite", response_model=TokenResponse, status_code=201)
async def accept_invite(body: AcceptInviteRequest, db: AsyncSession = Depends(get_db)):
    invite = await db.scalar(select(Invite).where(Invite.token == body.token))
    if invite is None or invite.accepted_at is not None:
        raise HTTPException(status_code=400, detail="유효하지 않은 초대 링크입니다.")
    if invite.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="만료된 초대 링크입니다.")

    existing = await db.scalar(select(User).where(User.email == body.email))
    if existing is not None:
        raise HTTPException(status_code=400, detail="이미 가입된 이메일입니다.")

    user = User(
        organization_id=invite.organization_id,
        email=body.email,
        hashed_password=hash_password(body.password),
        role="member",
    )
    db.add(user)
    invite.accepted_at = datetime.now(timezone.utc)
    await db.commit()

    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await db.scalar(select(User).where(User.email == body.email))
    if user is None or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다.")

    return TokenResponse(access_token=create_access_token(user.id))


@router.get("/me", response_model=AuthMeResponse)
async def me(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org = await db.get(Organization, current_user.organization_id)
    connected = bool(
        org.jira_base_url and org.jira_email and org.jira_api_token and org.jira_project_key
    )
    return AuthMeResponse(
        user=UserRead.model_validate(current_user),
        organization=OrganizationRead(
            id=org.id,
            name=org.name,
            jira_base_url=org.jira_base_url,
            jira_email=org.jira_email,
            jira_project_key=org.jira_project_key,
            jira_connected=connected,
            updated_at=org.updated_at,
        ),
    )
