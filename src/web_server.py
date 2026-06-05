"""
FastAPI web server with REST API, WebSocket collaboration, and activity tracking.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Form, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from .storage import store  # shared singleton
from .activity import tracker
from .ai_assistant import AIChatRequest, AIActionRequest, chat_with_assistant, run_document_action
from .graph_service import build_graph

logger = logging.getLogger("doc-editor.web")


# ── Activity Tracking Middleware ───────────────────────────────────────
SKIP_LOG_PATHS = frozenset({"/favicon.ico", "/api/dashboard/stats"})


class ActivityMiddleware(BaseHTTPMiddleware):
    """Logs every HTTP request to the activity tracker for the admin dashboard."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        start = time.time()
        try:
            response = await call_next(request)
        except Exception as e:
            duration_ms = (time.time() - start) * 1000
            tracker.log(
                method=request.method,
                path=path,
                status=500,
                duration_ms=duration_ms,
                detail=f"Internal error: {type(e).__name__}",
                client=request.client.host if request.client else "",
                intent=request.headers.get("X-Agent-Intent", ""),
            )
            # Broadcast error request to dashboards
            await manager.broadcast_dashboard({
                "type": "request",
                "method": request.method,
                "path": path,
                "status": 500,
                "duration": round(duration_ms, 1),
                "client": request.client.host if request.client else "",
                "detail": f"Internal error: {type(e).__name__}",
            })
            raise
        duration_ms = (time.time() - start) * 1000

        # Skip static files, favicon, and dashboard polling
        if not path.startswith("/static/") and path not in SKIP_LOG_PATHS:
            tracker.log(
                method=request.method,
                path=path,
                status=response.status_code,
                duration_ms=duration_ms,
                client=request.client.host if request.client else "",
                intent=request.headers.get("X-Agent-Intent", ""),
            )
            # Broadcast successful request to dashboards
            await manager.broadcast_dashboard({
                "type": "request",
                "method": request.method,
                "path": path,
                "status": response.status_code,
                "duration": round(duration_ms, 1),
                "client": request.client.host if request.client else "",
            })
        return response


# ── App Setup ──────────────────────────────────────────────────────────
app = FastAPI(title="MCP Document Editor", version="1.0.0")

# CORS — needed when IDE hosts the editor in an iframe/webview
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(ActivityMiddleware)

# Serve static files
STATIC_DIR = Path(__file__).parent.parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
else:
    logger.warning(f"Static directory not found: {STATIC_DIR}")

# Log server start
tracker.log(method="SYSTEM", path="Server started", detail="FastAPI + Uvicorn ready")


# ── WebSocket Connection Manager ──────────────────────────────────────
class ConnectionManager:
    """Manages WebSocket connections per document for real-time sync."""

    def __init__(self):
        self.active: dict[str, set[WebSocket]] = {}
        self.user_meta: dict[int, dict] = {}  # ws id -> {name, color}
        self.dashboards: set[WebSocket] = set()

    async def broadcast_dashboard(self, event: dict):
        """Send a real-time event log to all open dashboard connections."""
        if not self.dashboards:
            return
        dead: list[WebSocket] = []
        for ws in list(self.dashboards):
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.dashboards.discard(ws)

    async def connect(self, ws: WebSocket, doc_id: str, user_meta: dict | None = None):
        await ws.accept()
        if doc_id not in self.active:
            self.active[doc_id] = set()
        self.active[doc_id].add(ws)
        if user_meta:
            self.user_meta[id(ws)] = user_meta
        tracker.log(
            method="WS",
            path=f"/ws/{doc_id}",
            detail=f"Client connected ({len(self.active[doc_id])} total)",
        )
        await self.broadcast_dashboard({
            "type": "ws_event",
            "method": "WS",
            "path": f"/ws/{doc_id}",
            "detail": f"Client connected (total: {len(self.active[doc_id])})",
            "status": 101,
        })

    def disconnect(self, ws: WebSocket, doc_id: str):
        if doc_id in self.active:
            self.active[doc_id].discard(ws)
            count = len(self.active[doc_id])
            if not self.active[doc_id]:
                del self.active[doc_id]
            tracker.log(
                method="WS",
                path=f"/ws/{doc_id}",
                detail=f"Client disconnected ({count} remaining)",
            )
            # We schedule broadcasting to dashboards asynchronously
            asyncio.create_task(self.broadcast_dashboard({
                "type": "ws_event",
                "method": "WS",
                "path": f"/ws/{doc_id}",
                "detail": f"Client disconnected (remaining: {count})",
                "status": 1000,
            }))
        self.user_meta.pop(id(ws), None)

    def set_user_meta(self, ws: WebSocket, meta: dict):
        self.user_meta[id(ws)] = meta

    def get_users(self, doc_id: str) -> list[dict]:
        """Get list of user metadata dicts for a document."""
        if doc_id not in self.active:
            return []
        users = []
        for ws in self.active[doc_id]:
            meta = self.user_meta.get(id(ws), {"name": "Anonymous", "color": "#6366f1"})
            users.append(meta)
        return users

    async def broadcast(self, doc_id: str, message: dict, sender: WebSocket | None = None):
        """Broadcast a message to all clients on the same document except sender."""
        if doc_id not in self.active:
            return
        dead: list[WebSocket] = []
        for ws in self.active[doc_id]:
            if ws is sender:
                continue
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.active[doc_id].discard(ws)

    async def broadcast_all(self, doc_id: str, message: dict):
        """Broadcast a message to ALL clients on a document (including sender)."""
        if doc_id not in self.active:
            return
        dead: list[WebSocket] = []
        for ws in self.active[doc_id]:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.active[doc_id].discard(ws)

    def get_client_count(self, doc_id: str) -> int:
        return len(self.active.get(doc_id, set()))

    def get_all_connections(self) -> list[dict]:
        """Return connection info for the dashboard."""
        result = []
        for doc_id, clients in self.active.items():
            if doc_id == "dashboard":
                continue
            result.append({
                "doc_id": doc_id,
                "clients": len(clients),
                "title": doc_id,  # will be enriched later
            })
        return result

    @property
    def total_client_count(self) -> int:
        return sum(
            len(clients) for doc_id, clients in self.active.items()
            if doc_id != "dashboard"
        )


manager = ConnectionManager()


# ── Root → serve editor ───────────────────────────────────────────────
@app.get("/")
async def root():
    index = STATIC_DIR / "index.html"
    if not index.exists():
        return HTMLResponse("<h1>Editor not found</h1><p>Static files missing.</p>", status_code=404)
    return HTMLResponse(content=index.read_text(encoding="utf-8"))


# ── Dashboard page ────────────────────────────────────────────────────
@app.get("/dashboard")
async def dashboard_page():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/?hud=1")


# ═══════════════════════════════════════════════════════════════════════
#  REST API
# ═══════════════════════════════════════════════════════════════════════


@app.post("/api/documents")
async def api_create_document(
    title: str = Form("Untitled Document"),
    content: str = Form(""),
    tags: str = Form(""),
):
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    doc = await store.create(title=title, content=content, tags=tag_list)
    return {"id": doc.id, "title": doc.title, "created_at": str(doc.created_at)}


@app.post("/api/documents/import")
async def api_import_file(file: UploadFile = File(...)):
    """Import an uploaded markdown or text file into the database."""
    try:
        filename = file.filename
        content_bytes = await file.read()
        content = content_bytes.decode("utf-8", errors="ignore")
        
        # Format title from filename
        title = Path(filename).stem
        title = title.replace("_", " ").replace("-", " ").title()
        
        # Create a document
        doc = await store.create(title=title, content=content, tags=["Imported"])
        return {"id": doc.id, "title": doc.title, "filename": filename}
    except Exception as e:
        logger.error(f"Failed to import file: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/documents/scan")
async def api_scan_workspace():
    """Scan the workspace directory for untracked .md or .txt files."""
    try:
        project_root = Path(__file__).parent.parent
        files = []
        # Exclude hidden files or config files
        for file in project_root.glob("*"):
            if file.is_file() and file.suffix.lower() in (".md", ".txt") and not file.name.startswith("."):
                stat = file.stat()
                files.append({
                    "name": file.name,
                    "path": str(file.resolve()),
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                })
        return {"files": files}
    except Exception as e:
        logger.error(f"Failed to scan workspace: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/documents/import-local")
async def api_import_local_file(path: str = Form(...)):
    """Import a local file from a given path on disk."""
    try:
        file_path = Path(path)
        if not file_path.exists() or not file_path.is_file():
            return JSONResponse({"error": "File not found or is not a file"}, status_code=404)
        
        content = await asyncio.to_thread(file_path.read_text, encoding="utf-8", errors="ignore")
        
        title = file_path.stem.replace("_", " ").replace("-", " ").title()
        doc = await store.create(title=title, content=content, tags=["Local System"])
        return {"id": doc.id, "title": doc.title, "path": path}
    except Exception as e:
        logger.error(f"Failed to import local file: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/documents")
async def api_list_documents(q: Optional[str] = Query(None)):
    if q:
        docs = await store.search(q)
    else:
        docs = await store.list_all()
    return [d.model_dump() for d in docs]


@app.get("/api/documents/{doc_id}")
async def api_get_document(doc_id: str):
    doc = await store.get(doc_id)
    if doc is None:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return {
        "id": doc.id,
        "title": doc.title,
        "content": doc.content,
        "word_count": doc.word_count,
        "tags": doc.tags,
        "created_at": str(doc.created_at),
        "updated_at": str(doc.updated_at),
        "version_count": len(doc.versions),
        "clients": manager.get_client_count(doc_id),
    }


@app.get("/api/documents/{doc_id}/chunk")
async def api_get_document_chunk(doc_id: str, start: int = 0, end: int = 100):
    doc = await store.get(doc_id)
    if doc is None:
        return JSONResponse({"error": "Not found"}, status_code=404)
    lines = doc.content.splitlines()
    chunk = "\n".join(lines[start:end])
    return {
        "id": doc.id,
        "title": doc.title,
        "total_lines": len(lines),
        "start_line": start,
        "end_line": end,
        "content_chunk": chunk,
    }


@app.get("/api/documents/{doc_id}/summary")
async def api_get_document_summary(doc_id: str):
    doc = await store.get(doc_id)
    if doc is None:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return {
        "id": doc.id,
        "title": doc.title,
        "word_count": doc.word_count,
        "tags": doc.tags,
        "created_at": str(doc.created_at),
        "updated_at": str(doc.updated_at),
        "version_count": len(doc.versions),
        "pinned": doc.pinned,
        "content_preview": doc.content[:200] + "..." if len(doc.content) > 200 else doc.content,
    }


@app.put("/api/documents/{doc_id}")
async def api_update_document(
    doc_id: str,
    title: Optional[str] = Form(None),
    content: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    summary: str = Form(""),
):
    # Fix: only split tags if explicitly provided (not None)
    tag_list = None
    if tags is not None:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

    doc = await store.update(
        doc_id,
        content=content,
        title=title,
        tags=tag_list,
        change_summary=summary,
        auto_version=True,  # explicit saves always create a version
    )
    if doc is None:
        return JSONResponse({"error": "Not found"}, status_code=404)

    # Broadcast update to other connected clients
    await manager.broadcast(doc_id, {
        "type": "update",
        "content": doc.content,
        "title": doc.title,
        "updated_at": str(doc.updated_at),
    })

    return {
        "id": doc.id,
        "title": doc.title,
        "word_count": doc.word_count,
        "version_count": len(doc.versions),
        "message": "Updated",
    }


@app.delete("/api/documents/{doc_id}")
async def api_delete_document(doc_id: str):
    deleted = await store.delete(doc_id)
    if not deleted:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return {"message": "Deleted"}


@app.post("/api/documents/{doc_id}/draft")
async def api_create_draft(doc_id: str):
    draft = await store.create_draft(doc_id)
    if draft is None:
        return JSONResponse({"error": "Document not found or already a draft"}, status_code=400)
    return {"id": draft.id, "title": draft.title, "message": "Draft created successfully"}


@app.post("/api/documents/drafts/{draft_id}/merge")
async def api_merge_draft(
    draft_id: str,
    intent: str = Form("Merged from draft"),
):
    doc = await store.merge_draft(draft_id, intent=intent)
    if doc is None:
        return JSONResponse({"error": "Draft not found or invalid"}, status_code=404)
        
    await manager.broadcast(doc.id, {
        "type": "update",
        "content": doc.content,
        "title": doc.title,
        "updated_at": str(doc.updated_at),
    })
    return {"id": doc.id, "title": doc.title, "message": "Draft merged successfully"}


@app.get("/api/documents/{doc_id}/versions")
async def api_get_versions(doc_id: str):
    versions = await store.get_versions(doc_id)
    if versions is None:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return [
        {
            "version_id": v.version_id,
            "timestamp": str(v.timestamp),
            "summary": v.summary,
            "title": v.title,
        }
        for v in versions
    ]


@app.post("/api/documents/{doc_id}/restore/{version_id}")
async def api_restore_version(doc_id: str, version_id: str):
    doc = await store.restore_version(doc_id, version_id)
    if doc is None:
        return JSONResponse({"error": "Document or version not found"}, status_code=404)

    await manager.broadcast(doc_id, {
        "type": "update",
        "content": doc.content,
        "title": doc.title,
        "updated_at": str(doc.updated_at),
    })

    return {"id": doc.id, "title": doc.title, "message": f"Restored to version {version_id}"}


@app.post("/api/documents/{doc_id}/search-replace")
async def api_search_replace(
    doc_id: str,
    search: str = Form(""),
    replace: str = Form(""),
    regex: bool = Form(False),
):
    if not search:
        return JSONResponse({"error": "Search term required"}, status_code=400)
    try:
        result = await store.search_and_replace(doc_id, search, replace, regex=regex)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    if result is None:
        return JSONResponse({"error": "Not found"}, status_code=404)
    doc, count = result
    return {"replacements": count, "message": f"Replaced {count} occurrence(s)"}


@app.post("/api/documents/{doc_id}/pin")
async def api_toggle_pin(doc_id: str):
    doc = await store.toggle_pin(doc_id)
    if doc is None:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return {"id": doc.id, "pinned": doc.pinned, "message": f"{'Pinned' if doc.pinned else 'Unpinned'}"}


@app.get("/api/documents/{doc_id}/export/{fmt}")
async def api_export(doc_id: str, fmt: str):
    if fmt in ("html", "htm"):
        result = await store.export_html(doc_id)
        if result is None:
            return JSONResponse({"error": "Not found"}, status_code=404)
        return HTMLResponse(
            content=result,
            headers={"Content-Disposition": "attachment; filename=document.html"},
        )
    elif fmt in ("markdown", "md"):
        result = await store.export_markdown(doc_id)
        if result is None:
            return JSONResponse({"error": "Not found"}, status_code=404)
        return PlainTextResponse(
            content=result,
            headers={"Content-Disposition": "attachment; filename=document.md"},
        )
    return JSONResponse({"error": "Unsupported format"}, status_code=400)


# ═══════════════════════════════════════════════════════════════════════
#  AI Assistant API
# ═══════════════════════════════════════════════════════════════════════


@app.post("/api/ai/chat")
async def api_ai_chat(req: AIChatRequest):
    try:
        response_text = await chat_with_assistant(req)
        return {"response": response_text}
    except Exception as e:
        logger.error(f"AI Chat failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/ai/action")
async def api_ai_action(req: AIActionRequest):
    try:
        response_text = await run_document_action(req)
        return {"response": response_text}
    except Exception as e:
        logger.error(f"AI Action failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════════════════
#  Graph View API
# ═══════════════════════════════════════════════════════════════════════


@app.get("/api/documents/graph")
async def api_get_graph():
    try:
        graph_data = await build_graph()
        return graph_data
    except Exception as e:
        logger.error(f"Failed to build graph: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/documents/create-by-title")
async def api_create_by_title(title: str = Form(...)):
    try:
        doc = await store.create(title=title, content=f"<h1>{title}</h1><p>Start writing here...</p>")
        return {"id": doc.id, "title": doc.title, "created_at": str(doc.created_at)}
    except Exception as e:
        logger.error(f"Failed to create document by title: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════════════════
#  Dashboard Stats API
# ═══════════════════════════════════════════════════════════════════════


@app.get("/api/dashboard/stats")
async def api_dashboard_stats():
    """Return server stats for the admin dashboard."""
    import os
    docs = await store.list_all()
    info = tracker.get_server_info()
    
    # Check LangSmith telemetry settings
    langchain_tracing = os.getenv("LANGCHAIN_TRACING_V2", "").lower() == "true"
    langchain_api_key_set = bool(os.getenv("LANGCHAIN_API_KEY"))
    langchain_project = os.getenv("LANGCHAIN_PROJECT", "mcp-document-editor")
    
    return {
        **info,
        "documents": len(docs),
        "total_requests": tracker.total_requests,
        "total_errors": tracker.total_errors,
        "avg_latency_ms": round(tracker.avg_latency_ms, 1),
        "error_rate": round(tracker.error_rate, 1),
        "uptime": tracker.uptime_str,
        "uptime_seconds": tracker.uptime_seconds,
        "started_at": str(tracker.start_time),
        "ws_connections": manager.total_client_count,
        "ws_documents": len([d for d in manager.active if d != "dashboard"]),
        "connections": manager.get_all_connections(),
        "langsmith": {
            "tracing": langchain_tracing,
            "has_key": langchain_api_key_set,
            "project": langchain_project,
        }
    }


# ═══════════════════════════════════════════════════════════════════════
#  WebSocket — Real-time Collaboration
# ═══════════════════════════════════════════════════════════════════════


@app.websocket("/ws/{doc_id}")
async def websocket_endpoint(ws: WebSocket, doc_id: str):
    # Dashboard WebSocket — stream stats and active connections
    if doc_id == "dashboard":
        await ws.accept()
        manager.dashboards.add(ws)
        try:
            # Send initial stats and info immediately
            data = await api_dashboard_stats()
            await ws.send_json({"type": "server_info", **data})
            await ws.send_json({"type": "stats", **data})
            await ws.send_json({"type": "connections", "connections": data.get("connections", [])})
            
            while True:
                data = await api_dashboard_stats()
                await ws.send_json({"type": "server_info", **data})
                await ws.send_json({"type": "stats", **data})
                await ws.send_json({"type": "connections", "connections": data.get("connections", [])})
                await asyncio.sleep(3)
        except WebSocketDisconnect:
            logger.debug("Dashboard WS disconnected")
        except Exception as e:
            logger.debug(f"Dashboard WS closed: {type(e).__name__}")
        finally:
            manager.dashboards.discard(ws)
        return

    # Document WebSocket — real-time editing
    await manager.connect(ws, doc_id)

    # Send current doc state on connect
    doc = await store.get(doc_id)
    if doc:
        await ws.send_json({
            "type": "init",
            "content": doc.content,
            "title": doc.title,
            "clients": manager.get_client_count(doc_id),
            "users": manager.get_users(doc_id),
        })

    # Broadcast updated user list to all clients
    await manager.broadcast_all(doc_id, {
        "type": "presence",
        "clients": manager.get_client_count(doc_id),
        "users": manager.get_users(doc_id),
    })

    try:
        while True:
            try:
                data = await ws.receive_json()
            except json.JSONDecodeError:
                logger.warning(f"Malformed JSON from WS client on doc {doc_id}")
                continue

            msg_type = data.get("type", "")

            if msg_type == "join":
                # Client is announcing their user info
                meta = {
                    "name": data.get("name", "Anonymous"),
                    "color": data.get("color", "#6366f1"),
                }
                manager.set_user_meta(ws, meta)
                # Broadcast updated user list to everyone
                await manager.broadcast_all(doc_id, {
                    "type": "presence",
                    "clients": manager.get_client_count(doc_id),
                    "users": manager.get_users(doc_id),
                })
                # Broadcast join event to dashboards
                await manager.broadcast_dashboard({
                    "type": "ws_event",
                    "method": "WS",
                    "path": f"/ws/{doc_id}",
                    "detail": f"User '{meta['name']}' joined collaboration",
                    "status": 200,
                })

            elif msg_type == "edit":
                # Save WITHOUT version (avoids version spam on every keystroke)
                content = data.get("content", "")
                await store.update(
                    doc_id,
                    content=content,
                    change_summary="Real-time edit",
                    auto_version=False,  # ← no version snapshot for live edits
                )
                await manager.broadcast(doc_id, {
                    "type": "update",
                    "content": content,
                }, sender=ws)
                # Broadcast edit event to dashboards
                await manager.broadcast_dashboard({
                    "type": "ws_event",
                    "method": "WS",
                    "path": f"/ws/{doc_id}",
                    "detail": f"Edit by user: {len(content)} chars",
                    "status": 200,
                })

            elif msg_type == "title":
                title = data.get("title", "")
                await store.update(
                    doc_id,
                    title=title,
                    change_summary="Title change",
                    auto_version=False,
                )
                await manager.broadcast(doc_id, {
                    "type": "title",
                    "title": title,
                }, sender=ws)
                # Broadcast title event to dashboards
                await manager.broadcast_dashboard({
                    "type": "ws_event",
                    "method": "WS",
                    "path": f"/ws/{doc_id}",
                    "detail": f"Title updated to '{title}'",
                    "status": 200,
                })

            elif msg_type == "typing":
                # Forward typing indicator to other clients
                meta = manager.user_meta.get(id(ws), {})
                await manager.broadcast(doc_id, {
                    "type": "typing",
                    "name": meta.get("name", data.get("name", "Someone")),
                    "color": meta.get("color", "#6366f1"),
                }, sender=ws)

            elif msg_type == "cursor":
                meta = manager.user_meta.get(id(ws), {})
                await manager.broadcast(doc_id, {
                    "type": "cursor",
                    "position": data.get("position"),
                    "user": meta.get("name", data.get("user", "Anonymous")),
                }, sender=ws)

    except WebSocketDisconnect:
        manager.disconnect(ws, doc_id)
        await manager.broadcast_all(doc_id, {
            "type": "presence",
            "clients": manager.get_client_count(doc_id),
            "users": manager.get_users(doc_id),
        })
    except Exception as e:
        logger.error(f"WebSocket error on doc {doc_id}: {e}")
        manager.disconnect(ws, doc_id)
