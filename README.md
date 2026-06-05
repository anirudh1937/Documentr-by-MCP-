# 📝 MCP Document Editor

![Version](https://img.shields.io/badge/version-1.0.0-blue)
![Python](https://img.shields.io/badge/python-3.10+-blue)
![License](https://img.shields.io/badge/license-MIT-green)

A collaborative document editor exposed as an **MCP (Model Context Protocol)** server, with a beautiful web-based frontend for real-time editing.

## Screenshots

> **Note:** Add screenshots of the Web Editor, Admin Dashboard, and Version History panel here before publishing.
> 
> *Example:*
> `![Web Editor](docs/editor_screenshot.png)`
> `![Admin Dashboard](docs/admin_screenshot.png)`

## Features

- **11 MCP Tools** — Create, read, update, delete, search, search-and-replace, version history, restore, export, and launch editor
- **3 MCP Resources** — Document content, version history, and document list
- **Rich Text Editor** — Powered by [Quill.js](https://quilljs.com/) with formatting toolbar
- **Real-time Collaboration** — WebSocket-based live editing across multiple browser tabs
- **Admin Dashboard** — Desktop Tkinter GUI and web dashboard to monitor live server activity and memory usage
- **Version History** — Auto-versioning on every save with restore capability
- **Search & Replace** — Full-text search with regex support
- **Export** — Download documents as HTML or Markdown
- **Premium UI** — Dark mode with glassmorphism design and responsive layout

## Quick Start

### 1. Install Dependencies

```bash
# Using uv (recommended)
uv sync

# Or using pip
pip install -e .
```

### 2. Start the Application

You can start the application in different modes using the CLI:

```bash
# Start the web editor only
python main.py web

# Start with a custom port
python main.py web --port 9000

# Start both MCP server and Web Editor
python main.py dev

# Start the Desktop Admin GUI
python main.py admin
```

When the web server is running, open **http://localhost:8765** in your browser.
You can view the backend activity dashboard at **http://localhost:8765/dashboard**.

### 3. Connect to Claude Desktop (MCP)

Add this to your Claude Desktop MCP config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "document-editor": {
      "command": "uv",
      "args": ["run", "--directory", "f:/MCP_tool", "python", "main.py", "mcp"]
    }
  }
}
```

Restart Claude Desktop, and the Document Editor tools will be available.

## Admin Dashboard

The project includes two ways to monitor the backend:
1. **Web Dashboard**: Available at `/dashboard` when the web server is running. Shows live requests, WebSocket connections, memory usage, and error rates.
2. **Desktop Admin GUI**: Run `python main.py admin` to launch a standalone Tkinter application. This allows you to start/stop the server, view a color-coded live activity log, and monitor system resources without needing a browser.

## MCP Tools

| Tool | Description |
|------|-------------|
| `create_document` | Create a new document with title and content |
| `read_document` | Read full document content by ID |
| `update_document` | Update content/title/tags (auto-versions) |
| `delete_document` | Delete a document permanently |
| `list_documents` | List all documents with metadata |
| `search_documents` | Full-text search across all documents |
| `search_and_replace` | Find and replace text in a document |
| `get_version_history` | View version history for a document |
| `restore_version` | Restore to a previous version |
| `export_document` | Export as HTML or Markdown |
| `open_editor` | Launch the web editor in your browser |

## Project Structure

```
├── main.py              # CLI entry point
├── admin_gui.py         # Desktop admin GUI (Tkinter)
├── pyproject.toml       # Dependencies and metadata
├── src/
│   ├── models.py        # Pydantic data models
│   ├── storage.py       # Thread-safe document store
│   ├── activity.py      # Activity tracker and event queue
│   ├── mcp_server.py    # MCP server (FastMCP)
│   └── web_server.py    # FastAPI + WebSockets
├── static/
│   ├── index.html       # Web editor UI
│   ├── styles.css       # Premium dark-mode styles
│   ├── app.js           # Editor logic
│   ├── dashboard.html   # Web dashboard UI
│   └── dashboard.js     # Web dashboard logic
└── documents/           # Document storage (auto-created)
```

## Contributing

We welcome contributions! If you are integrating this tool into a larger IDE project:

1. **Architecture**: The `DocumentStore` in `src/storage.py` is the single source of truth. Both the `mcp_server` and `web_server` interact with it using `asyncio.Lock` for concurrency.
2. **Error Handling**: All MCP tools and API endpoints are wrapped in try/except blocks and return standard JSON error payloads.
3. **CORS**: The FastAPI app in `src/web_server.py` is configured with wildcard CORS to allow easy embedding in IDE webviews or iframes.
4. **Activity Monitoring**: The `ActivityMiddleware` logs all traffic to `src/activity.py`, which is then read by the Admin GUI and Dashboard WS.

## Tech Stack

- **MCP Server**: [FastMCP](https://github.com/modelcontextprotocol/python-sdk) (Python)
- **Backend**: [FastAPI](https://fastapi.tiangolo.com/) + [Uvicorn](https://www.uvicorn.org/)
- **Real-time**: WebSockets
- **Editor**: [Quill.js](https://quilljs.com/) v2
- **Storage**: JSON files on disk
- **Styling**: Vanilla CSS (Glassmorphism)

## License

MIT
