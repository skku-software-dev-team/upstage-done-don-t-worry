from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.compliance import Organization, User
from app.schemas.compliance import OrganizationJiraUpdate, OrganizationRead
from app.services import jira

router = APIRouter(prefix="/org", tags=["org"], dependencies=[Depends(get_current_user)])


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
