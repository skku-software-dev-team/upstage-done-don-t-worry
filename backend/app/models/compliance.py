import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    clauses: Mapped[list["Clause"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)

    canonical_items: Mapped[list["CanonicalItem"]] = relationship(back_populates="category")


class Clause(Base):
    __tablename__ = "clauses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"))
    clause_no: Mapped[str | None] = mapped_column(String(50))
    title: Mapped[str | None] = mapped_column(String(255))
    requirement: Mapped[str | None] = mapped_column(Text)
    related_laws_raw: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped["Document"] = relationship(back_populates="clauses")
    checklist_items: Mapped[list["ChecklistItem"]] = relationship(back_populates="clause", cascade="all, delete-orphan")
    canonical_maps: Mapped[list["CanonicalMap"]] = relationship(back_populates="clause", cascade="all, delete-orphan")
    law_refs: Mapped[list["ClauseLawRef"]] = relationship(back_populates="clause", cascade="all, delete-orphan")


class ChecklistItem(Base):
    __tablename__ = "checklist_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    clause_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clauses.id", ondelete="CASCADE"))
    question: Mapped[str] = mapped_column(Text, nullable=False)

    clause: Mapped["Clause"] = relationship(back_populates="checklist_items")


class CanonicalItem(Base):
    __tablename__ = "canonical_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"))
    category_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("categories.id"))
    merged_title: Mapped[str] = mapped_column(Text, nullable=False)

    category: Mapped["Category | None"] = relationship(back_populates="canonical_items")
    canonical_maps: Mapped[list["CanonicalMap"]] = relationship(back_populates="canonical_item", cascade="all, delete-orphan")
    org_statuses: Mapped[list["OrgStatus"]] = relationship(back_populates="canonical_item", cascade="all, delete-orphan")


class CanonicalMap(Base):
    __tablename__ = "canonical_map"

    canonical_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("canonical_items.id", ondelete="CASCADE"), primary_key=True)
    clause_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clauses.id", ondelete="CASCADE"), primary_key=True)

    canonical_item: Mapped["CanonicalItem"] = relationship(back_populates="canonical_maps")
    clause: Mapped["Clause"] = relationship(back_populates="canonical_maps")


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="Default Organization")
    jira_base_url: Mapped[str | None] = mapped_column(String(255))
    jira_email: Mapped[str | None] = mapped_column(String(255))
    jira_api_token: Mapped[str | None] = mapped_column(Text)
    jira_project_key: Mapped[str | None] = mapped_column(String(50))
    jira_cloud_id: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"))
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChecklistPeriod(Base):
    __tablename__ = "checklist_periods"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    org_statuses: Mapped[list["OrgStatus"]] = relationship(back_populates="period", cascade="all, delete-orphan")


class OrgStatus(Base):
    __tablename__ = "org_status"
    __table_args__ = (UniqueConstraint("canonical_id", "period_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"))
    canonical_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("canonical_items.id", ondelete="CASCADE"))
    period_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("checklist_periods.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="not_started")
    jira_key: Mapped[str | None] = mapped_column(String(100))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    canonical_item: Mapped["CanonicalItem"] = relationship(back_populates="org_statuses")
    period: Mapped["ChecklistPeriod"] = relationship(back_populates="org_statuses")


class Law(Base):
    __tablename__ = "laws"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    enacted_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    articles: Mapped[list["LawArticle"]] = relationship(back_populates="law", cascade="all, delete-orphan")


class LawArticle(Base):
    __tablename__ = "law_articles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    law_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("laws.id", ondelete="CASCADE"))
    article_no: Mapped[str | None] = mapped_column(String(50))
    article_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    law: Mapped["Law"] = relationship(back_populates="articles")
    clause_refs: Mapped[list["ClauseLawRef"]] = relationship(back_populates="article", cascade="all, delete-orphan")


class ClauseLawRef(Base):
    __tablename__ = "clause_law_ref"

    clause_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clauses.id", ondelete="CASCADE"), primary_key=True)
    article_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("law_articles.id", ondelete="CASCADE"), primary_key=True)
    match_method: Mapped[str] = mapped_column(String(50), nullable=False, default="regex")

    clause: Mapped["Clause"] = relationship(back_populates="law_refs")
    article: Mapped["LawArticle"] = relationship(back_populates="clause_refs")


class Embedding(Base):
    __tablename__ = "embeddings"
    __table_args__ = (UniqueConstraint("source_type", "source_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'clause' | 'law_article'
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(4096))
