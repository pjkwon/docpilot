from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

EMBEDDING_DIM = 768  # intfloat/multilingual-e5-base (default); change if using a different model


class Base(DeclarativeBase):
    pass


class Document(Base):
    """One record per ingested source file."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    collection: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    chunks: Mapped[list[Chunk]] = relationship(
        "Chunk", back_populates="document", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("source", name="uq_document_source"),)


class Chunk(Base):
    """Chunked content with vector embedding for similarity search."""

    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    document: Mapped[Document] = relationship("Document", back_populates="chunks")

    # Embeddings are stored separately:
    # - SQLite: vec_chunks virtual table (sqlite-vec)
    # - PostgreSQL: embedding vector(768) column (pgvector, added via DDL)


class TemplateRecord(Base):
    """
    Saved section0.xml templates with LLM-generated descriptions for natural language search.

    Stored path points to a section0.xml file that can be passed directly to HwpxBuilder.
    The description field is embedded (vec_templates) for vector similarity search.
    Tags are also indexed in FTS5 (fts_templates) for morpheme-based search.
    """

    __tablename__ = "template_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    header_xml: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class TermAlias(Base):
    """
    Korean term <-> Latin/romanized alias pairs, extracted from bilingual
    parenthetical notation found in indexed documents (e.g. "에코플라스틱(Ecoplastic)").

    Used to expand search queries so a Latin-script query term (e.g. "eco",
    "ecoplastic") can retrieve chunks that only contain the Korean form.
    """

    __tablename__ = "term_aliases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    korean_term: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    latin_alias: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    source_document_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (UniqueConstraint("korean_term", "latin_alias", name="uq_term_alias"),)
