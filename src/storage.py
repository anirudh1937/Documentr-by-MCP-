"""
Document storage layer — manages CRUD operations on disk using JSON files.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

from .models import Document, DocumentMetadata, DocumentVersion

logger = logging.getLogger("doc-editor.storage")


class DocumentStore:
    """Thread-safe document store backed by JSON files on disk."""

    def __init__(self, storage_dir: str = "documents"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    def _doc_path(self, doc_id: str) -> Path:
        # Sanitize ID — only allow alphanumeric, hyphens, and underscores
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", doc_id)
        if not safe_id:
            raise ValueError(f"Invalid document ID: '{doc_id}'")
        return self.storage_dir / f"{safe_id}.json"

    async def _save(self, doc: Document) -> None:
        """Save document to disk."""
        path = self._doc_path(doc.id)
        try:
            data = doc.model_dump_json(indent=2)
            await asyncio.to_thread(path.write_text, data, encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to save document {doc.id}: {e}")
            raise

    async def _load(self, doc_id: str) -> Optional[Document]:
        """Load document from disk."""
        try:
            path = self._doc_path(doc_id)
        except ValueError:
            return None

        if not path.exists():
            return None
        try:
            text = await asyncio.to_thread(path.read_text, encoding="utf-8")
            return Document.model_validate_json(text)
        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"Failed to load document {doc_id} (corrupt?): {e}")
            return None

    # ── CRUD ───────────────────────────────────────────────────────────

    async def create(
        self,
        title: str = "Untitled Document",
        content: str = "",
        tags: list[str] | None = None,
    ) -> Document:
        """Create a new document and save it to disk."""
        async with self._lock:
            doc = Document(title=title, content=content, tags=tags or [])
            doc.snapshot(summary="Initial creation")
            await self._save(doc)
            logger.info(f"Created document: {doc!r}")
            return doc

    async def get(self, doc_id: str) -> Optional[Document]:
        """Get a document by ID."""
        async with self._lock:
            return await self._load(doc_id)

    async def update(
        self,
        doc_id: str,
        content: str | None = None,
        title: str | None = None,
        tags: list[str] | None = None,
        change_summary: str = "",
        auto_version: bool = True,
    ) -> Optional[Document]:
        """Update a document. Optionally creates a version snapshot before updating."""
        async with self._lock:
            doc = await self._load(doc_id)
            if doc is None:
                return None

            # Snapshot current state before changes (skip for real-time WS edits)
            if auto_version:
                doc.snapshot(summary=change_summary or "Content update")

            if content is not None:
                doc.content = content
            if title is not None:
                doc.title = title
            if tags is not None:
                doc.tags = tags

            from .models import _utc_now
            doc.updated_at = _utc_now()

            await self._save(doc)
            return doc

    async def delete(self, doc_id: str) -> bool:
        """Delete a document. Returns True if deleted, False if not found."""
        async with self._lock:
            try:
                path = self._doc_path(doc_id)
            except ValueError:
                return False
            if path.exists():
                await asyncio.to_thread(path.unlink)
                logger.info(f"Deleted document: {doc_id}")
                return True
            return False

    async def toggle_pin(self, doc_id: str) -> Optional[Document]:
        """Toggle the pinned state of a document."""
        async with self._lock:
            doc = await self._load(doc_id)
            if doc is None:
                return None
            doc.pinned = not doc.pinned
            from .models import _utc_now
            doc.updated_at = _utc_now()
            await self._save(doc)
            logger.info(f"{'Pinned' if doc.pinned else 'Unpinned'} document: {doc_id}")
            return doc

    async def create_draft(self, doc_id: str) -> Optional[Document]:
        """Clone a live document into a draft sandbox."""
        async with self._lock:
            parent_doc = await self._load(doc_id)
            if parent_doc is None or parent_doc.is_draft:
                return None
            
            draft = Document(
                title=f"[DRAFT] {parent_doc.title}",
                content=parent_doc.content,
                tags=parent_doc.tags.copy(),
                is_draft=True,
                draft_of=doc_id,
            )
            draft.snapshot(summary="Draft initialized from live document")
            await self._save(draft)
            logger.info(f"Created draft {draft.id} of document {doc_id}")
            return draft

    async def merge_draft(self, draft_id: str, intent: str = "Merged from draft") -> Optional[Document]:
        """Merge a draft back into its parent live document."""
        async with self._lock:
            draft = await self._load(draft_id)
            if draft is None or not draft.is_draft or not draft.draft_of:
                return None
            
            parent_doc = await self._load(draft.draft_of)
            if parent_doc is None:
                return None
            
            parent_doc.snapshot(summary=f"Before merge: {intent}")
            
            # Remove the [DRAFT] prefix if unchanged
            new_title = draft.title
            if new_title.startswith("[DRAFT] "):
                new_title = new_title[8:]
                
            parent_doc.title = new_title
            parent_doc.content = draft.content
            parent_doc.tags = draft.tags
            
            from .models import _utc_now
            parent_doc.updated_at = _utc_now()
            
            await self._save(parent_doc)
            
            # Delete the draft
            path = self._doc_path(draft.id)
            if path.exists():
                await asyncio.to_thread(path.unlink)
            
            logger.info(f"Merged draft {draft_id} into document {parent_doc.id}")
            return parent_doc

    async def list_all(self) -> list[DocumentMetadata]:
        """List metadata for all documents, pinned first."""
        async with self._lock:
            docs: list[DocumentMetadata] = []
            for f in sorted(self.storage_dir.glob("*.json")):
                try:
                    text = await asyncio.to_thread(f.read_text, encoding="utf-8")
                    doc = Document.model_validate_json(text)
                    docs.append(doc.metadata)
                except Exception as e:
                    logger.warning(f"Skipping corrupt document file {f.name}: {e}")
                    continue
            # Sort: pinned first, then by updated_at descending
            docs.sort(key=lambda d: (not d.pinned, -d.updated_at.timestamp()))
            return docs

    # ── Search ─────────────────────────────────────────────────────────

    async def search(self, query: str) -> list[DocumentMetadata]:
        """Full-text search across titles and content (case-insensitive)."""
        if not query or not query.strip():
            return await self.list_all()

        async with self._lock:
            results: list[DocumentMetadata] = []
            query_lower = query.lower()
            for f in sorted(self.storage_dir.glob("*.json")):
                try:
                    text = await asyncio.to_thread(f.read_text, encoding="utf-8")
                    doc = Document.model_validate_json(text)
                    # Strip HTML tags for search
                    plain_content = re.sub(r"<[^>]+>", " ", doc.content).lower()
                    if query_lower in doc.title.lower() or query_lower in plain_content:
                        results.append(doc.metadata)
                except Exception as e:
                    logger.warning(f"Skipping file during search {f.name}: {e}")
                    continue
            # Sort: pinned first, then by updated_at descending
            results.sort(key=lambda d: (not d.pinned, -d.updated_at.timestamp()))
            return results

    async def search_and_replace(
        self, doc_id: str, search: str, replace: str, regex: bool = False
    ) -> Optional[tuple[Document, int]]:
        """
        Search and replace text within a document.
        Returns (updated_doc, replacement_count) or None if doc not found.
        """
        if not search:
            return None

        async with self._lock:
            doc = await self._load(doc_id)
            if doc is None:
                return None

            doc.snapshot(summary=f"Before search/replace: '{search}' → '{replace}'")

            try:
                if regex:
                    new_content, count = re.subn(search, replace, doc.content)
                else:
                    count = doc.content.count(search)
                    new_content = doc.content.replace(search, replace)
            except re.error as e:
                logger.warning(f"Invalid regex pattern '{search}': {e}")
                raise ValueError(f"Invalid regex pattern: {e}")

            doc.content = new_content

            from .models import _utc_now
            doc.updated_at = _utc_now()

            await self._save(doc)
            return doc, count

    # ── Version History ────────────────────────────────────────────────

    async def get_versions(self, doc_id: str) -> Optional[list[DocumentVersion]]:
        """Get version history for a document."""
        doc = await self.get(doc_id)
        if doc is None:
            return None
        return list(reversed(doc.versions))  # newest first

    async def restore_version(
        self, doc_id: str, version_id: str
    ) -> Optional[Document]:
        """Restore a document to a previous version."""
        async with self._lock:
            doc = await self._load(doc_id)
            if doc is None:
                return None

            result = doc.restore(version_id)
            if result is None:
                return None

            await self._save(doc)
            logger.info(f"Restored document {doc_id} to version {version_id}")
            return doc

    # ── Export ──────────────────────────────────────────────────────────

    async def export_html(self, doc_id: str) -> Optional[str]:
        """Export document as a standalone HTML file."""
        doc = await self.get(doc_id)
        if doc is None:
            return None

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{doc.title}</title>
    <style>
        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            max-width: 800px;
            margin: 2rem auto;
            padding: 0 1rem;
            line-height: 1.7;
            color: #1a1a2e;
        }}
        h1 {{ color: #6366f1; border-bottom: 2px solid #e0e7ff; padding-bottom: 0.5rem; }}
        code {{ background: #f1f5f9; padding: 2px 6px; border-radius: 4px; }}
        pre {{ background: #1e1e2e; color: #cdd6f4; padding: 1rem; border-radius: 8px; overflow-x: auto; }}
        blockquote {{ border-left: 4px solid #8b5cf6; margin-left: 0; padding-left: 1rem; color: #64748b; }}
        img {{ max-width: 100%; border-radius: 8px; }}
    </style>
</head>
<body>
    <h1>{doc.title}</h1>
    {doc.content}
    <footer style="margin-top: 3rem; padding-top: 1rem; border-top: 1px solid #e2e8f0; color: #94a3b8; font-size: 0.85rem;">
        Created: {doc.created_at.strftime('%Y-%m-%d %H:%M')} | 
        Last updated: {doc.updated_at.strftime('%Y-%m-%d %H:%M')} |
        Words: {doc.word_count}
    </footer>
</body>
</html>"""

    async def export_markdown(self, doc_id: str) -> Optional[str]:
        """Export document as Markdown."""
        doc = await self.get(doc_id)
        if doc is None:
            return None

        try:
            from markdownify import markdownify as md
            md_content = md(doc.content, heading_style="ATX", strip=["img"])
        except ImportError:
            # Fallback: basic HTML → text stripping
            md_content = re.sub(r"<[^>]+>", "", doc.content)

        header = f"# {doc.title}\n\n"
        footer = (
            f"\n\n---\n"
            f"*Created: {doc.created_at.strftime('%Y-%m-%d %H:%M')} | "
            f"Updated: {doc.updated_at.strftime('%Y-%m-%d %H:%M')} | "
            f"Words: {doc.word_count}*\n"
        )
        return header + md_content + footer


class AgentStateStore:
    """Thread-safe state store for agent memory and planning artifacts."""

    def __init__(self, storage_dir: str = "agent_state"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._memory_file = self.storage_dir / "memory.json"
        self._plan_file = self.storage_dir / "plan.json"
        self._lock = asyncio.Lock()

        if not self._memory_file.exists():
            self._memory_file.write_text("{}", encoding="utf-8")
        if not self._plan_file.exists():
            self._plan_file.write_text("[]", encoding="utf-8")

    async def _read_json(self, path: Path) -> any:
        text = await asyncio.to_thread(path.read_text, encoding="utf-8")
        return json.loads(text)

    async def _write_json(self, path: Path, data: any):
        text = json.dumps(data, indent=2)
        await asyncio.to_thread(path.write_text, text, encoding="utf-8")

    async def get_memory(self, key: str) -> Optional[str]:
        async with self._lock:
            data = await self._read_json(self._memory_file)
            return data.get(key)

    async def set_memory(self, key: str, value: str):
        async with self._lock:
            data = await self._read_json(self._memory_file)
            data[key] = value
            await self._write_json(self._memory_file, data)

    async def list_memory(self) -> dict:
        async with self._lock:
            return await self._read_json(self._memory_file)

    async def create_plan(self, task: str, steps: list[str]):
        async with self._lock:
            plan = {
                "task": task,
                "steps": [{"step": s, "completed": False} for s in steps]
            }
            await self._write_json(self._plan_file, plan)
            return plan

    async def get_plan(self) -> dict:
        async with self._lock:
            try:
                return await self._read_json(self._plan_file)
            except Exception:
                return []

    async def complete_step(self, step_idx: int) -> Optional[dict]:
        async with self._lock:
            plan = await self._read_json(self._plan_file)
            if not isinstance(plan, dict) or "steps" not in plan:
                return None
            if 0 <= step_idx < len(plan["steps"]):
                plan["steps"][step_idx]["completed"] = True
                await self._write_json(self._plan_file, plan)
                return plan
            return None

# Global store instances
store = DocumentStore()
agent_store = AgentStateStore()

