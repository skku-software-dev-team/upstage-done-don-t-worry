import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.compliance import Organization
from app.schemas.compliance import OrganizationJiraUpdate, OrganizationRead
from app.services import jira

router = APIRouter(prefix="/org", tags=["org"])


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


async def _get_or_create(org_id: uuid.UUID, db: AsyncSession) -> Organization:
    org = await db.get(Organization, org_id)
    if org is None:
        org = Organization(id=org_id, name="Default Organization")
        db.add(org)
        await db.commit()
        await db.refresh(org)
    return org


@router.get("/{org_id}", response_model=OrganizationRead)
async def get_org(org_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    org = await _get_or_create(org_id, db)
    return _to_read(org)


@router.put("/{org_id}/jira", response_model=OrganizationRead)
async def connect_jira(
    org_id: uuid.UUID,
    body: OrganizationJiraUpdate,
    db: AsyncSession = Depends(get_db),
):
    org = await _get_or_create(org_id, db)
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
