"""
MCP Document Editor — Desktop Admin Panel

A tkinter-based GUI that runs the web server and displays live backend activity.
This is admin-only — not served on the web, only visible on the local machine.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser
import tkinter as tk
from tkinter import font as tkfont
from datetime import datetime

# ═══════════════════════════════════════════════════════════════════
#  COLORS
# ═══════════════════════════════════════════════════════════════════

BG          = "#0a0a1a"
BG_CARD     = "#111128"
BG_HEADER   = "#0d0d24"
BG_INPUT    = "#1a1a3e"
BG_BTN      = "#252560"
TEXT        = "#e2e8f0"
TEXT_SEC     = "#94a3b8"
TEXT_DIM     = "#64748b"
ACCENT      = "#6366f1"
VIOLET      = "#8b5cf6"
PURPLE      = "#a855f7"
CYAN        = "#06b6d4"
EMERALD     = "#10b981"
AMBER       = "#f59e0b"
ROSE        = "#f43f5e"
PINK        = "#ec4899"
BORDER      = "#1e1e4a"

METHOD_COLORS = {
    "GET":    CYAN,
    "POST":   EMERALD,
    "PUT":    AMBER,
    "DELETE": ROSE,
    "WS":     VIOLET,
    "MCP":    PURPLE,
    "SYSTEM": ACCENT,
}

# ═══════════════════════════════════════════════════════════════════
#  ADMIN GUI
# ═══════════════════════════════════════════════════════════════════

class AdminGUI:
    """Desktop admin panel for the MCP Document Editor."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("⚡ MCP Document Editor — Admin Panel")
        self.root.geometry("1100x700")
        self.root.minsize(900, 500)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # Try to set icon (cross-platform safe)
        try:
            if sys.platform == "win32":
                self.root.iconbitmap(default="")
        except Exception:
            pass

        # Server state
        self.server_thread: threading.Thread | None = None
        self.uvicorn_server = None
        self.server_running = False
        self.log_count = 0

        # Fonts
        self.font_title = tkfont.Font(family="Segoe UI", size=14, weight="bold")
        self.font_subtitle = tkfont.Font(family="Segoe UI", size=9)
        self.font_heading = tkfont.Font(family="Segoe UI", size=11, weight="bold")
        self.font_body = tkfont.Font(family="Segoe UI", size=10)
        self.font_small = tkfont.Font(family="Segoe UI", size=9)
        self.font_mono = tkfont.Font(family="Consolas", size=10)
        self.font_mono_sm = tkfont.Font(family="Consolas", size=9)
        self.font_stat = tkfont.Font(family="Consolas", size=20, weight="bold")
        self.font_stat_label = tkfont.Font(family="Segoe UI", size=8)

        self._build_ui()
        self._setup_log_tags()
        self._poll_activity()
        self._update_clock()

    # ═══════════════════════════════════════════════════════════════
    #  BUILD UI
    # ═══════════════════════════════════════════════════════════════

    def _build_ui(self):
        # ── Header ──
        header = tk.Frame(self.root, bg=BG_HEADER, height=56)
        header.pack(fill=tk.X, side=tk.TOP)
        header.pack_propagate(False)

        tk.Label(
            header, text="  ⚡ MCP Document Editor", font=self.font_title,
            bg=BG_HEADER, fg=ACCENT,
        ).pack(side=tk.LEFT, padx=(12, 4))

        tk.Label(
            header, text="Admin Panel", font=self.font_subtitle,
            bg=BG_HEADER, fg=TEXT_DIM,
        ).pack(side=tk.LEFT)

        # Header right — clock + buttons
        self.clock_label = tk.Label(
            header, text="00:00:00", font=self.font_mono_sm,
            bg=BG_HEADER, fg=TEXT_DIM,
        )
        self.clock_label.pack(side=tk.RIGHT, padx=12)

        btn_open = tk.Button(
            header, text="🌐 Open Editor", font=self.font_small,
            bg=BG_BTN, fg=CYAN, bd=0, padx=12, pady=4,
            activebackground=BORDER, activeforeground=CYAN,
            cursor="hand2", command=self.open_editor,
        )
        btn_open.pack(side=tk.RIGHT, padx=4, pady=10)

        self.btn_stop = tk.Button(
            header, text="⏹ Stop", font=self.font_small,
            bg=BG_BTN, fg=ROSE, bd=0, padx=12, pady=4,
            activebackground=BORDER, activeforeground=ROSE,
            cursor="hand2", command=self.stop_server, state=tk.DISABLED,
        )
        self.btn_stop.pack(side=tk.RIGHT, padx=4, pady=10)

        self.btn_start = tk.Button(
            header, text="▶ Start Server", font=self.font_small,
            bg=BG_BTN, fg=EMERALD, bd=0, padx=12, pady=4,
            activebackground=BORDER, activeforeground=EMERALD,
            cursor="hand2", command=self.start_server,
        )
        self.btn_start.pack(side=tk.RIGHT, padx=4, pady=10)

        self.status_label = tk.Label(
            header, text="● Stopped", font=self.font_small,
            bg=BG_HEADER, fg=ROSE,
        )
        self.status_label.pack(side=tk.RIGHT, padx=12)

        # ── Stats Row ──
        stats_frame = tk.Frame(self.root, bg=BG, height=80)
        stats_frame.pack(fill=tk.X, padx=12, pady=(10, 6))

        self.stat_widgets = {}
        stats_config = [
            ("uptime",     "UPTIME",       "0s",    ACCENT),
            ("requests",   "REQUESTS",     "0",     CYAN),
            ("documents",  "DOCUMENTS",    "0",     EMERALD),
            ("ws_conns",   "WS CONNS",     "0",     VIOLET),
            ("errors",     "ERRORS",       "0",     ROSE),
            ("latency",    "AVG LATENCY",  "0ms",   AMBER),
        ]

        for i, (key, label, default, color) in enumerate(stats_config):
            card = tk.Frame(stats_frame, bg=BG_CARD, highlightbackground=BORDER,
                           highlightthickness=1, padx=16, pady=8)
            card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=3)

            # Colored top accent line
            accent = tk.Frame(card, bg=color, height=2)
            accent.pack(fill=tk.X, side=tk.TOP, pady=(0, 6))

            lbl = tk.Label(card, text=label, font=self.font_stat_label,
                          bg=BG_CARD, fg=TEXT_DIM)
            lbl.pack(anchor=tk.W)

            val = tk.Label(card, text=default, font=self.font_stat,
                          bg=BG_CARD, fg=color)
            val.pack(anchor=tk.W)

            self.stat_widgets[key] = val

        # ── Main Content ──
        main = tk.PanedWindow(
            self.root, orient=tk.HORIZONTAL, bg=BG,
            sashwidth=4, sashrelief=tk.FLAT, opaqueresize=True,
        )
        main.pack(fill=tk.BOTH, expand=True, padx=12, pady=(6, 4))

        # ── Left Panel: Server Info ──
        left_frame = tk.Frame(main, bg=BG_CARD, highlightbackground=BORDER,
                             highlightthickness=1)

        left_header = tk.Frame(left_frame, bg=BG_CARD)
        left_header.pack(fill=tk.X, padx=12, pady=(10, 6))
        tk.Label(left_header, text="🖥️ Server Info", font=self.font_heading,
                bg=BG_CARD, fg=TEXT).pack(anchor=tk.W)

        left_body = tk.Frame(left_frame, bg=BG_CARD)
        left_body.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        self.info_widgets = {}
        info_items = [
            ("server",    "🤖 MCP Server",   "DocumentEditor",           ACCENT),
            ("transport", "🔌 Transport",     "stdio (MCP) + HTTP (Web)", CYAN),
            ("api",       "📡 API Server",    "FastAPI + Uvicorn",        EMERALD),
            ("runtime",   "🐍 Runtime",       f"Python {sys.version.split()[0]}", TEXT),
            ("storage",   "💾 Storage",       "JSON / disk",              AMBER),
            ("host",      "🌐 Host",          "localhost:8765",           TEXT),
            ("memory",    "🧠 Memory",        "--",                       VIOLET),
            ("pid",       "🆔 PID",           str(os.getpid()),           TEXT_DIM),
        ]

        for key, label_text, default, color in info_items:
            row = tk.Frame(left_body, bg="#0d0d26", padx=8, pady=5)
            row.pack(fill=tk.X, pady=2)

            tk.Label(row, text=label_text, font=self.font_small,
                    bg="#0d0d26", fg=TEXT_DIM, width=16, anchor=tk.W).pack(side=tk.LEFT)
            val = tk.Label(row, text=default, font=self.font_mono_sm,
                          bg="#0d0d26", fg=color, anchor=tk.W)
            val.pack(side=tk.LEFT, fill=tk.X, expand=True)
            self.info_widgets[key] = val

        # MCP Tools list
        tools_header = tk.Frame(left_body, bg=BG_CARD)
        tools_header.pack(fill=tk.X, padx=4, pady=(12, 4))
        tk.Label(tools_header, text="🔧 MCP Tools (11)", font=self.font_small,
                bg=BG_CARD, fg=TEXT).pack(anchor=tk.W)

        tools = [
            "create_document", "read_document", "update_document",
            "delete_document", "list_documents", "search_documents",
            "search_and_replace", "get_version_history", "restore_version",
            "export_document", "open_editor",
        ]

        tools_wrap = tk.Frame(left_body, bg=BG_CARD)
        tools_wrap.pack(fill=tk.X, padx=4, pady=2)

        for tool in tools:
            tk.Label(
                tools_wrap, text=f" {tool} ", font=self.font_mono_sm,
                bg="#14143a", fg=ACCENT, padx=4, pady=1,
                highlightbackground="#252566", highlightthickness=1,
            ).pack(side=tk.LEFT, padx=2, pady=2)

        # Resources list
        res_header = tk.Frame(left_body, bg=BG_CARD)
        res_header.pack(fill=tk.X, padx=4, pady=(8, 4))
        tk.Label(res_header, text="📦 MCP Resources (3)", font=self.font_small,
                bg=BG_CARD, fg=TEXT).pack(anchor=tk.W)

        resources_wrap = tk.Frame(left_body, bg=BG_CARD)
        resources_wrap.pack(fill=tk.X, padx=4, pady=2)
        for res in ["doc://{id}", "doc://{id}/versions", "docs://list"]:
            tk.Label(
                resources_wrap, text=f" {res} ", font=self.font_mono_sm,
                bg="#14143a", fg=VIOLET, padx=4, pady=1,
                highlightbackground="#252566", highlightthickness=1,
            ).pack(side=tk.LEFT, padx=2, pady=2)

        main.add(left_frame, width=310, minsize=250)

        # ── Right Panel: Live Activity Log ──
        right_frame = tk.Frame(main, bg=BG_CARD, highlightbackground=BORDER,
                              highlightthickness=1)

        right_header = tk.Frame(right_frame, bg=BG_CARD)
        right_header.pack(fill=tk.X, padx=12, pady=(10, 6))

        tk.Label(right_header, text="📊 Live Activity", font=self.font_heading,
                bg=BG_CARD, fg=TEXT).pack(side=tk.LEFT)

        self.log_count_label = tk.Label(
            right_header, text="0 events", font=self.font_mono_sm,
            bg="#0d1a2a", fg=CYAN, padx=8, pady=2,
        )
        self.log_count_label.pack(side=tk.RIGHT)

        btn_clear = tk.Button(
            right_header, text="Clear", font=self.font_small,
            bg=BG_BTN, fg=TEXT_DIM, bd=0, padx=8, pady=2,
            activebackground=BORDER, activeforeground=TEXT,
            cursor="hand2", command=self.clear_log,
        )
        btn_clear.pack(side=tk.RIGHT, padx=6)

        # Log Text widget
        log_container = tk.Frame(right_frame, bg=BG)
        log_container.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))

        self.log_text = tk.Text(
            log_container, bg="#08081a", fg=TEXT, font=self.font_mono_sm,
            bd=0, highlightthickness=0, wrap=tk.NONE,
            insertbackground=TEXT, selectbackground=ACCENT,
            padx=12, pady=8, state=tk.DISABLED, cursor="arrow",
        )

        scrollbar = tk.Scrollbar(
            log_container, orient=tk.VERTICAL,
            command=self.log_text.yview, bg=BG_CARD, troughcolor=BG,
        )
        self.log_text.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        main.add(right_frame, minsize=400)

        # ── Footer ──
        footer = tk.Frame(self.root, bg=BG_HEADER, height=28)
        footer.pack(fill=tk.X, side=tk.BOTTOM)
        footer.pack_propagate(False)

        self.footer_status = tk.Label(
            footer, text="  ● Stopped", font=self.font_mono_sm,
            bg=BG_HEADER, fg=ROSE,
        )
        self.footer_status.pack(side=tk.LEFT, padx=8)

        self.footer_port = tk.Label(
            footer, text="Port: 8765", font=self.font_mono_sm,
            bg=BG_HEADER, fg=TEXT_DIM,
        )
        self.footer_port.pack(side=tk.LEFT, padx=12)

        self.footer_pid = tk.Label(
            footer, text=f"PID: {os.getpid()}", font=self.font_mono_sm,
            bg=BG_HEADER, fg=TEXT_DIM,
        )
        self.footer_pid.pack(side=tk.LEFT, padx=12)

        self.footer_info = tk.Label(
            footer, text="MCP Document Editor v1.0.0", font=self.font_mono_sm,
            bg=BG_HEADER, fg=TEXT_DIM,
        )
        self.footer_info.pack(side=tk.RIGHT, padx=12)

    # ═══════════════════════════════════════════════════════════════
    #  LOG TAGS
    # ═══════════════════════════════════════════════════════════════

    def _setup_log_tags(self):
        """Configure text tags for colored log entries."""
        for method, color in METHOD_COLORS.items():
            self.log_text.tag_config(method, foreground=color)

        self.log_text.tag_config("time", foreground=TEXT_DIM)
        self.log_text.tag_config("path", foreground=TEXT_SEC)
        self.log_text.tag_config("detail", foreground=TEXT_DIM)
        self.log_text.tag_config("status_ok", foreground=EMERALD)
        self.log_text.tag_config("status_warn", foreground=AMBER)
        self.log_text.tag_config("status_err", foreground=ROSE)
        self.log_text.tag_config("duration", foreground=TEXT_DIM)
        self.log_text.tag_config("separator", foreground="#1a1a40")

    # ═══════════════════════════════════════════════════════════════
    #  SERVER CONTROL
    # ═══════════════════════════════════════════════════════════════

    def start_server(self):
        """Start the FastAPI server in a background thread."""
        if self.server_running:
            return

        self.server_running = True
        self.btn_start.configure(state=tk.DISABLED, fg=TEXT_DIM)
        self.btn_stop.configure(state=tk.NORMAL, fg=ROSE)
        self.status_label.configure(text="● Running", fg=EMERALD)
        self.footer_status.configure(text="  ● Server Online", fg=EMERALD)

        self._add_system_log("Server starting on http://localhost:8765")

        self.server_thread = threading.Thread(target=self._run_server, daemon=True)
        self.server_thread.start()

    def _run_server(self):
        """Run uvicorn in a background thread."""
        try:
            import uvicorn
            config = uvicorn.Config(
                "src.web_server:app",
                host="0.0.0.0",
                port=8765,
                log_level="warning",
            )
            self.uvicorn_server = uvicorn.Server(config)
            self.uvicorn_server.run()
        except Exception as e:
            self.root.after(0, lambda: self._add_system_log(f"Server error: {e}"))
            self.root.after(0, self._on_server_stopped)

    def stop_server(self):
        """Stop the server gracefully."""
        if not self.server_running:
            return

        self._add_system_log("Server stopping…")

        if self.uvicorn_server:
            self.uvicorn_server.should_exit = True

        self._on_server_stopped()

    def _on_server_stopped(self):
        """Update UI when server stops."""
        self.server_running = False
        self.btn_start.configure(state=tk.NORMAL, fg=EMERALD)
        self.btn_stop.configure(state=tk.DISABLED, fg=TEXT_DIM)
        self.status_label.configure(text="● Stopped", fg=ROSE)
        self.footer_status.configure(text="  ● Stopped", fg=ROSE)

    def open_editor(self):
        """Open the web editor in the default browser."""
        if not self.server_running:
            self._add_system_log("Cannot open editor — server is not running")
            return
        webbrowser.open("http://localhost:8765")
        self._add_system_log("Opened editor in browser")

    # ═══════════════════════════════════════════════════════════════
    #  ACTIVITY POLLING
    # ═══════════════════════════════════════════════════════════════

    def _poll_activity(self):
        """Poll the activity tracker for new events (runs on main thread)."""
        try:
            from src.activity import tracker

            # Drain new events
            events = tracker.drain_events()
            for event in events:
                self._add_log_entry(event)

            # Update stats
            if self.server_running:
                self.stat_widgets["uptime"].configure(text=tracker.uptime_str)
                self.stat_widgets["requests"].configure(text=str(tracker.total_requests))
                self.stat_widgets["errors"].configure(text=str(tracker.total_errors))
                self.stat_widgets["latency"].configure(
                    text=f"{tracker.avg_latency_ms:.0f}ms"
                )

                # Get server info for memory
                info = tracker.get_server_info()
                self.info_widgets["memory"].configure(text=info.get("memory", "--"))

                # Count documents on disk
                docs_dir = os.path.join(os.getcwd(), "documents")
                if os.path.isdir(docs_dir):
                    doc_count = len([f for f in os.listdir(docs_dir) if f.endswith(".json")])
                    self.stat_widgets["documents"].configure(text=str(doc_count))

                # WS connections — try to get from web_server
                try:
                    from src.web_server import manager
                    ws_count = manager.total_client_count
                    self.stat_widgets["ws_conns"].configure(text=str(ws_count))
                except Exception:
                    pass

        except ImportError:
            pass
        except Exception:
            pass

        self.root.after(250, self._poll_activity)

    def _update_clock(self):
        """Update the header clock every second."""
        now = datetime.now().strftime("%H:%M:%S")
        self.clock_label.configure(text=now)
        self.root.after(1000, self._update_clock)

    # ═══════════════════════════════════════════════════════════════
    #  LOG RENDERING
    # ═══════════════════════════════════════════════════════════════

    def _add_log_entry(self, event):
        """Add a formatted log entry to the log text widget."""
        self.log_text.configure(state=tk.NORMAL)

        timestamp = event.timestamp.strftime("%H:%M:%S")
        method = event.method.upper()
        method_padded = f"{method:<7}"
        path = event.path
        status = event.status
        duration = f"{event.duration_ms:.0f}ms" if event.duration_ms else ""
        detail = event.detail
        intent = getattr(event, "intent", "")

        # Insert timestamp
        self.log_text.insert(tk.END, f"  {timestamp}  ", "time")

        # Insert method with color
        tag = method if method in METHOD_COLORS else "SYSTEM"
        self.log_text.insert(tk.END, f"{method_padded} ", tag)

        # Insert path
        self.log_text.insert(tk.END, f"{path}", "path")

        # Insert detail if any
        if detail:
            self.log_text.insert(tk.END, f"  {detail}", "detail")

        if intent:
            self.log_text.insert(tk.END, f"  [Intent: {intent}]", "status_warn")

        # Insert status
        if status:
            if status < 300:
                status_tag = "status_ok"
            elif status < 500:
                status_tag = "status_warn"
            else:
                status_tag = "status_err"
            self.log_text.insert(tk.END, f"  [{status}]", status_tag)

        # Insert duration
        if duration:
            self.log_text.insert(tk.END, f"  {duration}", "duration")

        self.log_text.insert(tk.END, "\n")

        # Auto-scroll to bottom
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

        self.log_count += 1
        self.log_count_label.configure(text=f"{self.log_count} events")

        # Trim log if too long (keep last 500 lines)
        line_count = int(self.log_text.index("end-1c").split(".")[0])
        if line_count > 500:
            self.log_text.configure(state=tk.NORMAL)
            self.log_text.delete("1.0", f"{line_count - 500}.0")
            self.log_text.configure(state=tk.DISABLED)

    def _add_system_log(self, message: str):
        """Add a system message to the log."""
        self.log_text.configure(state=tk.NORMAL)

        now = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"  {now}  ", "time")
        self.log_text.insert(tk.END, "SYSTEM  ", "SYSTEM")
        self.log_text.insert(tk.END, f"{message}\n", "path")

        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

        self.log_count += 1
        self.log_count_label.configure(text=f"{self.log_count} events")

    def clear_log(self):
        """Clear the activity log."""
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)
        self.log_count = 0
        self.log_count_label.configure(text="0 events")

    # ═══════════════════════════════════════════════════════════════
    #  LIFECYCLE
    # ═══════════════════════════════════════════════════════════════

    def on_close(self):
        """Cleanup on window close."""
        if self.server_running:
            self.stop_server()
        self.root.destroy()

    def run(self):
        """Start the GUI main loop."""
        # Add welcome message
        self._add_system_log("Admin panel initialized")
        self._add_system_log(f"Python {sys.version.split()[0]} | PID {os.getpid()}")
        self._add_system_log("Click 'Start Server' to begin")

        self.root.mainloop()


# ═══════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════

def main():
    gui = AdminGUI()
    gui.run()


if __name__ == "__main__":
    main()
