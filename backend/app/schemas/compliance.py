import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class DocumentBase(BaseModel):
    name: str
    doc_type: str


class DocumentCreate(DocumentBase):
    supersedes_document_id: uuid.UUID | None = None


class DocumentRead(DocumentBase):
    id: uuid.UUID
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentActiveUpdate(BaseModel):
    is_active: bool


class ClauseBase(BaseModel):
    document_id: uuid.UUID
    clause_no: str | None = None
    title: str | None = None
    requirement: str | None = None
    related_laws_raw: str | None = None


class ClauseCreate(ClauseBase):
    pass


class ClauseRead(ClauseBase):
    id: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class ChecklistItemRead(BaseModel):
    id: uuid.UUID
    clause_id: uuid.UUID
    question: str

    model_config = {"from_attributes": True}


class CategoryRead(BaseModel):
    id: uuid.UUID
    name: str

    model_config = {"from_attributes": True}


class DepartmentRead(BaseModel):
    id: uuid.UUID
    name: str

    model_config = {"from_attributes": True}


class CanonicalItemRead(BaseModel):
    id: uuid.UUID
    category_id: uuid.UUID | None
    department_id: uuid.UUID | None
    merged_title: str

    model_config = {"from_attributes": True}


class ChecklistDocRef(BaseModel):
    document_id: uuid.UUID
    doc_type: str
    document_name: str


class ChecklistItemDetail(BaseModel):
    """Enriched checklist item: canonical item + category + source document(s).

    A single item can list multiple documents when cross-document duplicate
    detection merged clauses from more than one source (e.g. the same
    requirement appearing in both ISMS-P and CSAP)."""
    id: uuid.UUID
    merged_title: str
    category_id: uuid.UUID | None
    category_name: str | None
    department_id: uuid.UUID | None
    department_name: str | None
    documents: list[ChecklistDocRef]


class OrgStatusRead(BaseModel):
    id: uuid.UUID
    canonical_id: uuid.UUID
    period_id: uuid.UUID
    status: str
    jira_key: str | None
    updated_at: datetime

    model_config = {"from_attributes": True}


class OrgStatusUpdate(BaseModel):
    status: str
    jira_key: str | None = None
    period_id: uuid.UUID | None = None


class ChecklistPeriodRead(BaseModel):
    id: uuid.UUID
    label: str
    start_date: date | None
    end_date: date | None
    is_current: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ChecklistPeriodCreate(BaseModel):
    label: str
    start_date: date | None = None
    end_date: date | None = None


# Auth
class SignupRequest(BaseModel):
    org_name: str
    email: str
    password: str
    name: str
    department_id: uuid.UUID | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserRead(BaseModel):
    id: uuid.UUID
    email: str
    name: str | None
    department_id: uuid.UUID | None
    role: str

    model_config = {"from_attributes": True}


class AcceptInviteRequest(BaseModel):
    token: str
    email: str
    password: str
    name: str
    department_id: uuid.UUID | None = None


class InviteRead(BaseModel):
    id: uuid.UUID
    token: str
    expires_at: datetime
    accepted_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


# Organization / Jira connection
class OrganizationRead(BaseModel):
    id: uuid.UUID
    name: str
    jira_base_url: str | None
    jira_email: str | None
    jira_project_key: str | None
    jira_connected: bool  # true when all required Jira fields are set (token never returned)
    updated_at: datetime


class AuthMeResponse(BaseModel):
    user: UserRead
    organization: OrganizationRead


class MemberRead(BaseModel):
    id: uuid.UUID
    email: str
    name: str | None
    department_name: str | None = None
    role: str
    created_at: datetime

    model_config = {"from_attributes": True}


class OrganizationJiraUpdate(BaseModel):
    jira_base_url: str
    jira_email: str
    jira_api_token: str
    jira_project_key: str


# Laws
class LawCreate(BaseModel):
    name: str
    version: str
    enacted_date: date | None = None
    supersedes_law_id: uuid.UUID | None = None


class LawRead(BaseModel):
    id: uuid.UUID
    name: str
    version: str
    enacted_date: date | None
    is_active: bool

    model_config = {"from_attributes": True}


class LawActiveUpdate(BaseModel):
    is_active: bool


class LawArticleRead(BaseModel):
    id: uuid.UUID
    law_id: uuid.UUID
    article_no: str | None
    article_text: str | None

    model_config = {"from_attributes": True}


class ClauseLawRefRead(BaseModel):
    clause_id: uuid.UUID
    article_id: uuid.UUID
    match_method: str

    model_config = {"from_attributes": True}


# Chat
class ChatHistoryTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatMessage(BaseModel):
    message: str
    source_type: Literal["clause", "law_article", "all"] = "all"
    history: list[ChatHistoryTurn] = []


class ChatSource(BaseModel):
    id: uuid.UUID
    source_type: Literal["clause", "law_article"]
    clause_no: str | None
    title: str | None
    document_name: str | None
    doc_type: str | None


class ChatResponse(BaseModel):
    answer: str
    sources: list[ChatSource] = []
