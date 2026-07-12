import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class DocumentBase(BaseModel):
    name: str
    doc_type: str


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


class CanonicalItemRead(BaseModel):
    id: uuid.UUID
    category_id: uuid.UUID | None
    merged_title: str

    model_config = {"from_attributes": True}


class OrgStatusRead(BaseModel):
    id: uuid.UUID
    canonical_id: uuid.UUID
    status: str
    jira_key: str | None
    updated_at: datetime

    model_config = {"from_attributes": True}


class OrgStatusUpdate(BaseModel):
    status: str
    jira_key: str | None = None


# Laws
class LawRead(BaseModel):
    id: uuid.UUID
    name: str
    version: str
    enacted_date: date | None

    model_config = {"from_attributes": True}


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
class ChatMessage(BaseModel):
    message: str
    source_type: Literal["clause", "law_article", "all"] = "all"


class ChatResponse(BaseModel):
    answer: str
    sources: list[ClauseRead] = []
