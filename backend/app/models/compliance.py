import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
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
    title: Mapped[str | None] = mapped_column(Text)
    requirement: Mapped[str | None] = mapped_column(Text)
    related_laws: Mapped[str | None] = mapped_column(Text)
    page: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped["Document"] = relationship(back_populates="clauses")
    checklist_items: Mapped[list["ChecklistItem"]] = relationship(back_populates="clause", cascade="all, delete-orphan")
    canonical_maps: Mapped[list["CanonicalMap"]] = relationship(back_populates="clause", cascade="all, delete-orphan")
    embedding: Mapped["Embedding | None"] = relationship(back_populates="clause", uselist=False, cascade="all, delete-orphan")


class ChecklistItem(Base):
    __tablename__ = "checklist_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    clause_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clauses.id", ondelete="CASCADE"))
    question: Mapped[str] = mapped_column(Text, nullable=False)
    order_no: Mapped[int] = mapped_column(Integer, nullable=False)

    clause: Mapped["Clause"] = relationship(back_populates="checklist_items")


class CanonicalItem(Base):
    __tablename__ = "canonical_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
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


class OrgStatus(Base):
    __tablename__ = "org_status"
    __table_args__ = (UniqueConstraint("org_id", "canonical_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    canonical_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("canonical_items.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="not_started")
    jira_key: Mapped[str | None] = mapped_column(String(100))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    canonical_item: Mapped["CanonicalItem"] = relationship(back_populates="org_statuses")


class Embedding(Base):
    __tablename__ = "embeddings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    clause_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clauses.id", ondelete="CASCADE"), unique=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(4096))

    clause: Mapped["Clause"] = relationship(back_populates="embedding")
