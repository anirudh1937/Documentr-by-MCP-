"""
Pydantic data models for the Document Editor.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


class DocumentVersion(BaseModel):
    """A snapshot of a document at a point in time."""

    version_id: str = Field(default_factory=_new_id)
    content: str = ""
    title: str = ""
    timestamp: datetime = Field(default_factory=_utc_now)
    summary: str = ""  # optional change summary

    def __repr__(self) -> str:
        return f"<Version {self.version_id} '{self.summary}' @ {self.timestamp:%Y-%m-%d %H:%M}>"


class DocumentMetadata(BaseModel):
    """Lightweight metadata returned when listing documents."""

    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    tags: list[str] = []
    word_count: int = 0
    version_count: int = 0
    pinned: bool = False
    is_draft: bool = False
    draft_of: str | None = None

    def __repr__(self) -> str:
        return f"<DocMeta {self.id} '{self.title}' ({self.word_count}w, {self.version_count}v)>"


class Document(BaseModel):
    """A full document with content and version history."""

    id: str = Field(default_factory=_new_id)
    title: str = "Untitled Document"
    content: str = ""  # current HTML content
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    tags: list[str] = []
    pinned: bool = False
    is_draft: bool = False
    draft_of: str | None = None
    versions: list[DocumentVersion] = []
    max_versions: int = 50  # keep last N versions

    def __repr__(self) -> str:
        return f"<Document {self.id} '{self.title}' ({self.word_count}w, {len(self.versions)}v)>"

    @property
    def word_count(self) -> int:
        """Count words in the plain-text content."""
        import re
        # Strip HTML tags for word count
        text = re.sub(r"<[^>]+>", " ", self.content)
        return len(text.split())

    @property
    def metadata(self) -> DocumentMetadata:
        return DocumentMetadata(
            id=self.id,
            title=self.title,
            created_at=self.created_at,
            updated_at=self.updated_at,
            tags=self.tags,
            word_count=self.word_count,
            version_count=len(self.versions),
            pinned=self.pinned,
            is_draft=self.is_draft,
            draft_of=self.draft_of,
        )

    def snapshot(self, summary: str = "") -> None:
        """Save the current state as a version snapshot."""
        version = DocumentVersion(
            content=self.content,
            title=self.title,
            timestamp=_utc_now(),
            summary=summary,
        )
        self.versions.append(version)
        # Trim to max versions
        if len(self.versions) > self.max_versions:
            self.versions = self.versions[-self.max_versions :]

    def restore(self, version_id: str) -> Optional[DocumentVersion]:
        """Restore document to a previous version, returns the version or None."""
        for v in self.versions:
            if v.version_id == version_id:
                self.snapshot(summary=f"Before restore to {version_id}")
                self.content = v.content
                self.title = v.title
                self.updated_at = _utc_now()
                return v
        return None
