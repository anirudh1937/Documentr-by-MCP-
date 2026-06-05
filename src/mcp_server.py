"""
MCP Server for the Document Editor.

Exposes document CRUD, search, version history, and export as MCP tools/resources.
All tools act as HTTP clients to the Web Server, ensuring that AI activity is
logged in the Dashboard and instantly broadcast to Web UI clients via WebSocket.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import threading
import webbrowser
from typing import Optional

import httpx
from mcp.server.fastmcp import FastMCP
from .storage import agent_store
from .activity import tracker

logger = logging.getLogger("doc-editor.mcp")

# ── Initialise ─────────────────────────────────────────────────────────
mcp = FastMCP(
    "DocumentEditor",
    instructions=(
        "A collaborative document editor. Use these tools to create, read, "
        "update, delete, search, and export rich-text documents. Documents "
        "support version history and real-time collaborative editing via a "
        "built-in web UI."
    ),
)

WEB_PORT = 8765
API_BASE = f"http://localhost:{WEB_PORT}/api/documents"

async def _request(method: str, endpoint: str, data: dict | None = None, params: dict | None = None, headers: dict | None = None) -> httpx.Response:
    """Helper to make HTTP requests to the Web Server API."""
    url = f"http://localhost:{WEB_PORT}{endpoint}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            if method.upper() == "GET":
                return await client.get(url, params=params, headers=headers)
            elif method.upper() == "POST":
                return await client.post(url, data=data, headers=headers)
            elif method.upper() == "PUT":
                return await client.put(url, data=data, headers=headers)
            elif method.upper() == "DELETE":
                return await client.delete(url, headers=headers)
            else:
                raise ValueError(f"Unsupported method {method}")
    except httpx.ConnectError:
        raise ConnectionError("The Web Editor is offline. Please start it first (e.g., python main.py dev).")


# ═══════════════════════════════════════════════════════════════════════
#  MCP TOOLS
# ═══════════════════════════════════════════════════════════════════════


@mcp.tool()
async def create_document(
    title: str = "Untitled Document",
    content: str = "",
    tags: list[str] | None = None,
) -> str:
    """Create a new document with a title, optional HTML content, and tags."""
    try:
        form_data = {
            "title": title,
            "content": content,
            "tags": ",".join(tags) if tags else ""
        }
        resp = await _request("POST", "/api/documents", data=form_data)
        if resp.status_code >= 400:
            return json.dumps({"error": resp.text})
        
        doc = resp.json()
        return json.dumps(
            {"id": doc["id"], "title": doc["title"], "message": f"Document '{doc['title']}' created."},
            default=str,
        )
    except Exception as e:
        logger.error(f"create_document failed: {e}")
        return json.dumps({"error": f"Failed to create document: {e}"})


@mcp.tool()
async def read_document(doc_id: str) -> str:
    """Read the full content of a document by its ID."""
    if not doc_id or not doc_id.strip():
        return json.dumps({"error": "doc_id is required."})

    try:
        resp = await _request("GET", f"/api/documents/{doc_id}")
        if resp.status_code == 404:
            return json.dumps({"error": f"Document '{doc_id}' not found."})
        elif resp.status_code >= 400:
            return json.dumps({"error": resp.text})
            
        return json.dumps(resp.json(), default=str)
    except Exception as e:
        logger.error(f"read_document failed for '{doc_id}': {e}")
        return json.dumps({"error": f"Failed to read document: {e}"})


@mcp.tool()
async def read_document_summary(doc_id: str) -> str:
    """Read a summary and metadata of a document without loading the full content. Use this to inspect large documents."""
    if not doc_id or not doc_id.strip():
        return json.dumps({"error": "doc_id is required."})

    try:
        resp = await _request("GET", f"/api/documents/{doc_id}/summary")
        if resp.status_code == 404:
            return json.dumps({"error": f"Document '{doc_id}' not found."})
        elif resp.status_code >= 400:
            return json.dumps({"error": resp.text})
            
        return json.dumps(resp.json(), default=str)
    except Exception as e:
        logger.error(f"read_document_summary failed for '{doc_id}': {e}")
        return json.dumps({"error": f"Failed to read document summary: {e}"})


@mcp.tool()
async def read_document_chunk(doc_id: str, start_line: int = 0, end_line: int = 100) -> str:
    """Read a specific chunk (line range) of a document. Useful for paginating through large files."""
    if not doc_id or not doc_id.strip():
        return json.dumps({"error": "doc_id is required."})

    try:
        resp = await _request("GET", f"/api/documents/{doc_id}/chunk", params={"start": start_line, "end": end_line})
        if resp.status_code == 404:
            return json.dumps({"error": f"Document '{doc_id}' not found."})
        elif resp.status_code >= 400:
            return json.dumps({"error": resp.text})
            
        return json.dumps(resp.json(), default=str)
    except Exception as e:
        logger.error(f"read_document_chunk failed for '{doc_id}': {e}")
        return json.dumps({"error": f"Failed to read document chunk: {e}"})


@mcp.tool()
async def update_document(
    doc_id: str,
    content: str | None = None,
    title: str | None = None,
    tags: list[str] | None = None,
    change_summary: str = "",
    intent: str = "",
) -> str:
    """Update a document's content, title, and/or tags. Auto-saves a version."""
    if not doc_id or not doc_id.strip():
        return json.dumps({"error": "doc_id is required."})
    if not intent.strip():
        return json.dumps({"error": "intent is required for destructive actions. Please explain why you are making this update."})

    try:
        form_data = {"summary": change_summary}
        if content is not None: form_data["content"] = content
        if title is not None: form_data["title"] = title
        if tags is not None: form_data["tags"] = ",".join(tags)

        headers = {"X-Agent-Intent": intent}
        resp = await _request("PUT", f"/api/documents/{doc_id}", data=form_data, headers=headers)
        if resp.status_code == 404:
            return json.dumps({"error": f"Document '{doc_id}' not found."})
        elif resp.status_code >= 400:
            return json.dumps({"error": resp.text})
            
        return json.dumps(resp.json(), default=str)
    except Exception as e:
        logger.error(f"update_document failed for '{doc_id}': {e}")
        return json.dumps({"error": f"Failed to update document: {e}"})


@mcp.tool()
async def delete_document(doc_id: str, intent: str = "") -> str:
    """Delete a document permanently by ID."""
    if not doc_id or not doc_id.strip():
        return json.dumps({"error": "doc_id is required."})
    if not intent.strip():
        return json.dumps({"error": "intent is required for destructive actions. Please explain why you are deleting this."})

    try:
        headers = {"X-Agent-Intent": intent}
        resp = await _request("DELETE", f"/api/documents/{doc_id}", headers=headers)
        if resp.status_code == 404:
            return json.dumps({"error": f"Document '{doc_id}' not found."})
        elif resp.status_code >= 400:
            return json.dumps({"error": resp.text})
            
        return json.dumps({"message": f"Document '{doc_id}' deleted."})
    except Exception as e:
        logger.error(f"delete_document failed for '{doc_id}': {e}")
        return json.dumps({"error": f"Failed to delete document: {e}"})


@mcp.tool()
async def list_documents() -> str:
    """List all documents with their metadata."""
    try:
        resp = await _request("GET", "/api/documents")
        if resp.status_code >= 400:
            return json.dumps({"error": resp.text})
        return json.dumps(resp.json(), default=str)
    except Exception as e:
        logger.error(f"list_documents failed: {e}")
        return json.dumps({"error": f"Failed to list documents: {e}"})


@mcp.tool()
async def search_documents(query: str) -> str:
    """Full-text search across all document titles and content."""
    if not query or not query.strip():
        return json.dumps({"error": "Search query is required."})

    try:
        resp = await _request("GET", "/api/documents", params={"q": query})
        if resp.status_code >= 400:
            return json.dumps({"error": resp.text})
        return json.dumps(resp.json(), default=str)
    except Exception as e:
        logger.error(f"search_documents failed for '{query}': {e}")
        return json.dumps({"error": f"Search failed: {e}"})


@mcp.tool()
async def search_and_replace(
    doc_id: str,
    search: str,
    replace: str,
    regex: bool = False,
    intent: str = "",
) -> str:
    """Find and replace text within a document."""
    if not doc_id or not doc_id.strip():
        return json.dumps({"error": "doc_id is required."})
    if not search:
        return json.dumps({"error": "Search term is required."})
    if not intent.strip():
        return json.dumps({"error": "intent is required for destructive actions. Please explain why you are doing this search and replace."})

    try:
        form_data = {"search": search, "replace": replace, "regex": str(regex).lower()}
        headers = {"X-Agent-Intent": intent}
        resp = await _request("POST", f"/api/documents/{doc_id}/search-replace", data=form_data, headers=headers)
        if resp.status_code == 404:
            return json.dumps({"error": f"Document '{doc_id}' not found."})
        elif resp.status_code >= 400:
            return json.dumps({"error": resp.text})
            
        return json.dumps(resp.json(), default=str)
    except Exception as e:
        logger.error(f"search_and_replace failed: {e}")
        return json.dumps({"error": f"Search/replace failed: {e}"})


@mcp.tool()
async def get_version_history(doc_id: str) -> str:
    """Get the version history of a document."""
    if not doc_id or not doc_id.strip():
        return json.dumps({"error": "doc_id is required."})

    try:
        resp = await _request("GET", f"/api/documents/{doc_id}/versions")
        if resp.status_code == 404:
            return json.dumps({"error": f"Document '{doc_id}' not found."})
        elif resp.status_code >= 400:
            return json.dumps({"error": resp.text})
            
        return json.dumps(resp.json(), default=str)
    except Exception as e:
        logger.error(f"get_version_history failed for '{doc_id}': {e}")
        return json.dumps({"error": f"Failed to get version history: {e}"})


@mcp.tool()
async def restore_version(doc_id: str, version_id: str) -> str:
    """Restore a document to a previous version."""
    if not doc_id or not doc_id.strip():
        return json.dumps({"error": "doc_id is required."})
    if not version_id or not version_id.strip():
        return json.dumps({"error": "version_id is required."})

    try:
        resp = await _request("POST", f"/api/documents/{doc_id}/restore/{version_id}")
        if resp.status_code == 404:
            return json.dumps({"error": "Document or version not found."})
        elif resp.status_code >= 400:
            return json.dumps({"error": resp.text})
            
        return json.dumps(resp.json(), default=str)
    except Exception as e:
        logger.error(f"restore_version failed: {e}")
        return json.dumps({"error": f"Failed to restore version: {e}"})


@mcp.tool()
async def export_document(doc_id: str, format: str = "html") -> str:
    """Export a document as HTML or Markdown."""
    if not doc_id or not doc_id.strip():
        return json.dumps({"error": "doc_id is required."})

    fmt = format.lower().strip()
    if fmt not in ("html", "htm", "markdown", "md"):
        return json.dumps({"error": f"Unsupported format '{format}'. Use 'html' or 'markdown'."})

    try:
        resp = await _request("GET", f"/api/documents/{doc_id}/export/{fmt}")
        if resp.status_code == 404:
            return json.dumps({"error": f"Document '{doc_id}' not found."})
        elif resp.status_code >= 400:
            return json.dumps({"error": resp.text})
            
        return resp.text
    except Exception as e:
        logger.error(f"export_document failed: {e}")
        return json.dumps({"error": f"Export failed: {e}"})


@mcp.tool()
async def pin_document(doc_id: str) -> str:
    """Toggle the pinned/favorite status of a document."""
    if not doc_id or not doc_id.strip():
        return json.dumps({"error": "doc_id is required."})

    try:
        resp = await _request("POST", f"/api/documents/{doc_id}/pin")
        if resp.status_code == 404:
            return json.dumps({"error": f"Document '{doc_id}' not found."})
        elif resp.status_code >= 400:
            return json.dumps({"error": resp.text})

        return "Unpinned document successfully." if "Unpinned" in resp.text else "Pinned document successfully."
    except Exception as e:
        logger.error(f"pin_document failed for '{doc_id}': {e}")
        return json.dumps({"error": f"Failed to toggle pin: {e}"})

@mcp.tool()
async def create_document_draft(doc_id: str) -> str:
    """Create a safe sandbox copy of a document. Always use this before making massive rewrites."""
    if not doc_id or not doc_id.strip():
        return json.dumps({"error": "doc_id is required."})

    try:
        resp = await _request("POST", f"/api/documents/{doc_id}/draft")
        if resp.status_code >= 400:
            return json.dumps({"error": resp.text})
            
        return json.dumps(resp.json(), default=str)
    except Exception as e:
        logger.error(f"create_document_draft failed for '{doc_id}': {e}")
        return json.dumps({"error": f"Failed to create draft: {e}"})

@mcp.tool()
async def propose_draft_merge(draft_id: str, intent: str) -> str:
    """Request that your drafted changes be merged into the main live document. Requires explicit intent."""
    if not draft_id or not draft_id.strip():
        return json.dumps({"error": "draft_id is required."})
    if not intent or not intent.strip():
        return json.dumps({"error": "intent is required. Explain what changes you are merging."})

    try:
        form_data = {"intent": intent}
        headers = {"X-Agent-Intent": intent}
        resp = await _request("POST", f"/api/documents/drafts/{draft_id}/merge", data=form_data, headers=headers)
        if resp.status_code >= 400:
            return json.dumps({"error": resp.text})
            
        return json.dumps(resp.json(), default=str)
    except Exception as e:
        logger.error(f"propose_draft_merge failed for '{draft_id}': {e}")
        return json.dumps({"error": f"Failed to merge draft: {e}"})


@mcp.tool()
async def write_agent_memory(key: str, value: str) -> str:
    """Store persistent state or memory. Use this as a scratchpad to remember context across turns."""
    await agent_store.set_memory(key, value)
    tracker.log("MCP", "/agent/memory", detail=f"Wrote memory: {key}")
    return json.dumps({"message": f"Saved '{key}' to persistent memory."})

@mcp.tool()
async def read_agent_memory(key: str = "") -> str:
    """Read a specific key from memory, or leave key blank to list all memory contents."""
    tracker.log("MCP", "/agent/memory", detail=f"Read memory: {key if key else 'ALL'}")
    if key:
        val = await agent_store.get_memory(key)
        if val is None:
            return json.dumps({"error": f"Key '{key}' not found in memory."})
        return json.dumps({key: val})
    else:
        all_mem = await agent_store.list_memory()
        return json.dumps(all_mem, indent=2)

@mcp.tool()
async def create_execution_plan(task_description: str, steps: list[str]) -> str:
    """Initialize a formal execution plan for a long-horizon task. The plan acts as a structured todo-list."""
    plan = await agent_store.create_plan(task_description, steps)
    tracker.log("MCP", "/agent/plan", detail=f"Created plan with {len(steps)} steps")
    return json.dumps({"message": "Execution plan initialized.", "plan": plan}, indent=2)

@mcp.tool()
async def mark_plan_step_complete(step_index: int) -> str:
    """Mark a specific step in the current execution plan as completed."""
    plan = await agent_store.complete_step(step_index)
    if plan is None:
        return json.dumps({"error": f"Invalid step_index {step_index}."})
    tracker.log("MCP", "/agent/plan", detail=f"Completed plan step {step_index}")
    return json.dumps({"message": f"Step {step_index} completed.", "current_plan": plan}, indent=2)


@mcp.tool()
async def open_editor(doc_id: str | None = None) -> str:
    """Launch the web-based document editor in your default browser."""
    url = f"http://localhost:{WEB_PORT}"
    if doc_id:
        url += f"?doc={doc_id}"

    # Check if server is already running before starting
    def _start_server():
        import socket
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                result = s.connect_ex(("localhost", WEB_PORT))
                if result == 0:
                    logger.info(f"Server already running on port {WEB_PORT}")
                    return  # Already running
        except Exception:
            pass

        try:
            subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "src.web_server:app",
                 "--host", "0.0.0.0", "--port", str(WEB_PORT), "--log-level", "warning"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info(f"Started web server on port {WEB_PORT}")
        except Exception as e:
            logger.error(f"Failed to start web server: {e}")

    threading.Thread(target=_start_server, daemon=True).start()

    # Open browser
    try:
        webbrowser.open(url)
    except Exception as e:
        logger.warning(f"Could not open browser: {e}")

    return json.dumps({"url": url, "message": f"Editor opened at {url}"})


@mcp.tool()
async def ai_query_document(
    doc_id: str,
    query: str,
    provider: str = "google",
    model: str = "gemini-1.5-flash",
) -> str:
    """
    Ask the AI Assistant a question about a specific document's content.
    Uses LangChain to process the prompt with the document as context.
    """
    import os
    # Resolve API Key from environment
    api_key = None
    if provider == "google":
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    elif provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
    elif provider == "anthropic":
        api_key = os.getenv("ANTHROPIC_API_KEY")
        
    url = f"http://localhost:{WEB_PORT}/api/ai/chat"
    payload = {
        "provider": provider,
        "model": model,
        "api_key": api_key,
        "message": query,
        "active_doc_id": doc_id,
        "scope": "document",
        "chat_history": []
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code >= 400:
                return json.dumps({"error": resp.text})
            return json.dumps(resp.json())
    except Exception as e:
        logger.error(f"ai_query_document failed: {e}")
        return json.dumps({"error": f"AI query failed: {e}"})


@mcp.tool()
async def ai_summarize_document(
    doc_id: str,
    provider: str = "google",
    model: str = "gemini-1.5-flash",
) -> str:
    """
    Summarize a document's content using the LangChain AI Assistant.
    """
    import os
    # Read the document content first
    try:
        doc_resp = await _request("GET", f"/api/documents/{doc_id}")
        if doc_resp.status_code >= 400:
            return json.dumps({"error": f"Failed to read document: {doc_resp.text}"})
        doc_data = doc_resp.json()
        content = doc_data.get("content", "")
    except Exception as e:
        return json.dumps({"error": f"Failed to fetch document content: {e}"})
        
    # Resolve API Key from environment
    api_key = None
    if provider == "google":
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    elif provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
    elif provider == "anthropic":
        api_key = os.getenv("ANTHROPIC_API_KEY")
        
    url = f"http://localhost:{WEB_PORT}/api/ai/action"
    payload = {
        "provider": provider,
        "model": model,
        "api_key": api_key,
        "action": "summarize",
        "text": content,
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code >= 400:
                return json.dumps({"error": resp.text})
            return json.dumps(resp.json())
    except Exception as e:
        logger.error(f"ai_summarize_document failed: {e}")
        return json.dumps({"error": f"AI summary failed: {e}"})


@mcp.tool()
async def get_document_graph() -> str:
    """
    Get the network graph (brain map) of all documents showing how they link to each other.
    Returns nodes and links representation including document titles and missing (ghost) note connections.
    """
    try:
        resp = await _request("GET", "/api/documents/graph")
        if resp.status_code >= 400:
            return json.dumps({"error": resp.text})
        return json.dumps(resp.json(), indent=2)
    except Exception as e:
        logger.error(f"get_document_graph failed: {e}")
        return json.dumps({"error": f"Failed to get graph: {e}"})


# ═══════════════════════════════════════════════════════════════════════
#  MCP RESOURCES
# ═══════════════════════════════════════════════════════════════════════


@mcp.resource("doc://{doc_id}")
async def resource_document(doc_id: str) -> str:
    """Read a document's content by ID."""
    try:
        resp = await _request("GET", f"/api/documents/{doc_id}")
        if resp.status_code == 404:
            return json.dumps({"error": f"Document '{doc_id}' not found."})
        elif resp.status_code >= 400:
            return json.dumps({"error": resp.text})
            
        doc = resp.json()
        return json.dumps(
            {"id": doc["id"], "title": doc["title"], "content": doc["content"]},
            default=str,
        )
    except Exception as e:
        return json.dumps({"error": f"Failed to read document: {e}"})


@mcp.resource("doc://{doc_id}/versions")
async def resource_versions(doc_id: str) -> str:
    """Read version history for a document."""
    try:
        resp = await _request("GET", f"/api/documents/{doc_id}/versions")
        if resp.status_code == 404:
            return json.dumps({"error": f"Document '{doc_id}' not found."})
        elif resp.status_code >= 400:
            return json.dumps({"error": resp.text})
            
        return json.dumps(resp.json(), default=str)
    except Exception as e:
        return json.dumps({"error": f"Failed to read versions: {e}"})


@mcp.resource("docs://list")
async def resource_list() -> str:
    """List all documents."""
    try:
        resp = await _request("GET", "/api/documents")
        if resp.status_code >= 400:
            return json.dumps({"error": resp.text})
        return json.dumps(resp.json(), default=str)
    except Exception as e:
        return json.dumps({"error": f"Failed to list documents: {e}"})
