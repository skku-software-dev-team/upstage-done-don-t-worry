import uuid
from datetime import datetime

from pydantic import BaseModel


class DocumentBase(BaseModel):
    name: str
    doc_type: str
    version: str


class DocumentCreate(DocumentBase):
    pass


class DocumentRead(DocumentBase):
    id: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class ClauseBase(BaseModel):
    document_id: uuid.UUID
    clause_no: str | None = None
    title: str | None = None
    requirement: str | None = None
    related_laws: str | None = None
    page: int | None = None


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
    order_no: int

    model_config = {"from_attributes": True}


class CategoryRead(BaseModel):
    id: uuid.UUID
    name: str

    model_config = {"from_attributes": True}


class CanonicalItemRead(BaseModel):
    id: uuid.UUID
    category_id: uuid.UUID | None
    merged_title: str

    model_config = {"from_attributes": True}


class OrgStatusRead(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    canonical_id: uuid.UUID
    status: str
    jira_key: str | None
    updated_at: datetime

    model_config = {"from_attributes": True}


class OrgStatusUpdate(BaseModel):
    status: str
    jira_key: str | None = None


class ChatMessage(BaseModel):
    message: str
    org_id: uuid.UUID | None = None


class ChatResponse(BaseModel):
    answer: str
    sources: list[ClauseRead] = []
