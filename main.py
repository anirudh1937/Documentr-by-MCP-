"""
MCP Document Editor — CLI Entry Point

Usage:
  python main.py mcp         Launch MCP server (stdio)
  python main.py web          Launch web editor (HTTP + WebSocket)
  python main.py dev          Launch both MCP + Web simultaneously
  python main.py admin        Launch the desktop admin GUI
  python main.py web --port 9000   Use a custom port
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import threading

# ── Logging Setup ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-22s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("doc-editor")

# ── Ensure project root is on sys.path ─────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ── Load Environment Variables from .env ───────────────────────────
def load_env():
    env_path = os.path.join(PROJECT_ROOT, ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    os.environ[key] = val

load_env()

VERSION = "1.0.0"

BANNER = rf"""
  +-----------------------------------------------+
  |        MCP Document Editor  v{VERSION}         |
  |                                               |
  |  Tools: create, read, update, delete, search  |
  |  Features: versioning, export, real-time sync |
  +-----------------------------------------------+
"""


def run_mcp():
    """Launch MCP server over stdio."""
    from src.mcp_server import mcp
    logger.info("Starting MCP server (stdio)…")
    mcp.run(transport="stdio")


def run_web(port: int = 8765):
    """Launch the FastAPI web server with Uvicorn."""
    import uvicorn
    from src.mcp_server import WEB_PORT

    print(BANNER)
    logger.info(f"Starting web editor on http://localhost:{port}")
    logger.info(f"Dashboard at http://localhost:{port}/dashboard")

    uvicorn.run(
        "src.web_server:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
        reload=False,
    )


def run_dev(port: int = 8765):
    """Launch both MCP server and web server together."""
    print(BANNER)
    logger.info("Starting in DEV mode (MCP + Web)…")

    # Run web server in a background thread
    web_thread = threading.Thread(target=run_web, args=(port,), daemon=True)
    web_thread.start()

    # Run MCP server on main thread (stdio)
    run_mcp()


def run_admin():
    """Launch the desktop admin GUI (Tkinter)."""
    print(BANNER)
    logger.info("Starting admin GUI…")
    try:
        from admin_gui import AdminGUI
        gui = AdminGUI()
        gui.run()
    except ImportError as e:
        logger.error(f"Failed to import admin GUI: {e}")
        logger.error("Make sure admin_gui.py is in the project root.")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Admin GUI failed: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        prog="mcp-doc-editor",
        description="MCP Document Editor — AI-powered collaborative document editor",
    )
    parser.add_argument(
        "mode",
        choices=["mcp", "web", "dev", "admin"],
        help="mcp = stdio MCP server | web = HTTP editor | dev = both | admin = desktop GUI",
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=8765,
        help="Port for the web server (default: 8765)",
    )

    args = parser.parse_args()

    if args.mode == "mcp":
        run_mcp()
    elif args.mode == "web":
        run_web(port=args.port)
    elif args.mode == "dev":
        run_dev(port=args.port)
    elif args.mode == "admin":
        run_admin()


if __name__ == "__main__":
    main()
