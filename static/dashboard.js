/**
 * MCP Document Editor — Backend Dashboard Logic
 *
 * Connects via WebSocket to receive live server activity events,
 * updates stats, logs, and connection panels in real-time.
 */

// ═══════════════════════════════════════════════════════════════════
//  STATE
// ═══════════════════════════════════════════════════════════════════

let dashWs = null;
let logEntries = [];
let totalRequests = 0;
let totalErrors = 0;
let latencies = [];
let startTime = null;
let reconnectAttempts = 0;
const MAX_LOG = 200;
const MAX_RECONNECT_DELAY = 30000; // 30s cap

// ═══════════════════════════════════════════════════════════════════
//  CONNECT TO DASHBOARD WEBSOCKET
// ═══════════════════════════════════════════════════════════════════

function connectDashboard() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${location.host}/ws/dashboard`;

    try {
        dashWs = new WebSocket(wsUrl);
    } catch (e) {
        console.error('Failed to create WebSocket:', e);
        scheduleReconnect();
        return;
    }

    dashWs.onopen = () => {
        reconnectAttempts = 0;
        setDashboardConnected(true);
        addLogEntry({
            type: 'system',
            method: 'SYSTEM',
            path: 'Dashboard connected',
            detail: 'WebSocket stream active',
            status: 200,
            duration: 0,
        });
    };

    dashWs.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            handleEvent(data);
        } catch (e) {
            console.warn('Malformed dashboard WS message:', e);
        }
    };

    dashWs.onclose = () => {
        setDashboardConnected(false);
        scheduleReconnect();
    };

    dashWs.onerror = () => {
        setDashboardConnected(false);
    };
}

function scheduleReconnect() {
    reconnectAttempts++;
    // Exponential backoff: 1s, 2s, 4s, 8s, 16s, 30s (capped)
    const delay = Math.min(1000 * Math.pow(2, reconnectAttempts - 1), MAX_RECONNECT_DELAY);
    console.log(`Dashboard WS reconnecting in ${delay}ms (attempt ${reconnectAttempts})`);
    setTimeout(connectDashboard, delay);
}

function setDashboardConnected(connected) {
    const statusEl = document.getElementById('footer-ws-status');
    const banner = document.getElementById('disconnect-banner');
    const footerDot = document.querySelector('.dash-footer .footer-dot');

    if (connected) {
        statusEl.textContent = 'Connected';
        banner.classList.remove('visible');
        if (footerDot) footerDot.className = 'footer-dot green';
    } else {
        statusEl.textContent = 'Disconnected';
        banner.classList.add('visible');
        if (footerDot) footerDot.className = 'footer-dot amber';
    }
}

// ═══════════════════════════════════════════════════════════════════
//  EVENT HANDLER
// ═══════════════════════════════════════════════════════════════════

function handleEvent(data) {
    switch (data.type) {
        case 'server_info':
            updateServerInfo(data);
            break;
        case 'stats':
            updateStats(data);
            break;
        case 'request':
            addLogEntry(data);
            totalRequests++;
            if (data.status >= 400) totalErrors++;
            if (data.duration) latencies.push(data.duration);
            if (latencies.length > 50) latencies.shift();
            updateStatCounters();
            break;
        case 'ws_event':
            addLogEntry(data);
            break;
        case 'connections':
            updateConnections(data.connections || []);
            break;
        default:
            addLogEntry(data);
    }
}

// ═══════════════════════════════════════════════════════════════════
//  SERVER INFO
// ═══════════════════════════════════════════════════════════════════

function updateServerInfo(data) {
    if (data.server_name) document.getElementById('info-server-name').textContent = data.server_name;
    if (data.transport) document.getElementById('info-transport').textContent = data.transport;
    if (data.runtime) document.getElementById('info-runtime').textContent = data.runtime;
    if (data.host) document.getElementById('info-host').textContent = data.host;
    if (data.memory) document.getElementById('info-memory').textContent = data.memory;
    if (data.pid) document.getElementById('footer-pid').textContent = data.pid;
    if (data.port) document.getElementById('footer-port').textContent = data.port;
    if (data.started_at) {
        startTime = new Date(data.started_at);
        document.getElementById('stat-started').textContent = `since ${startTime.toLocaleTimeString()}`;
    }
}

// ═══════════════════════════════════════════════════════════════════
//  STATS
// ═══════════════════════════════════════════════════════════════════

function updateStats(data) {
    if (data.documents !== undefined) {
        document.getElementById('stat-documents').textContent = data.documents;
    }
    if (data.ws_connections !== undefined) {
        document.getElementById('stat-ws').textContent = data.ws_connections;
    }
    if (data.ws_documents !== undefined) {
        document.getElementById('stat-ws-detail').textContent = `${data.ws_documents} document${data.ws_documents !== 1 ? 's' : ''}`;
    }
    if (data.memory) {
        document.getElementById('info-memory').textContent = data.memory;
    }
}

function updateStatCounters() {
    document.getElementById('stat-requests').textContent = totalRequests;
    document.getElementById('stat-errors').textContent = totalErrors;

    // Error rate
    const errorRate = totalRequests > 0 ? ((totalErrors / totalRequests) * 100).toFixed(1) : 0;
    document.getElementById('stat-error-rate').textContent = `${errorRate}%`;

    // Avg latency
    if (latencies.length > 0) {
        const avg = latencies.reduce((a, b) => a + b, 0) / latencies.length;
        document.getElementById('stat-latency').textContent = `${avg.toFixed(0)}ms`;
    }

    // RPS
    document.getElementById('stat-rps').textContent = `${totalRequests} total`;

    // Log count badge
    document.getElementById('log-count').textContent = `${logEntries.length} events`;
}

// ═══════════════════════════════════════════════════════════════════
//  ACTIVITY LOG
// ═══════════════════════════════════════════════════════════════════

function addLogEntry(data) {
    // Hide empty state
    const empty = document.getElementById('log-empty');
    if (empty) empty.style.display = 'none';

    const log = document.getElementById('activity-log');
    const entry = document.createElement('div');
    entry.className = 'log-entry';

    const now = new Date();
    const timeStr = now.toLocaleTimeString('en-US', { hour12: false });

    const method = (data.method || 'SYSTEM').toUpperCase();
    const methodClass = getMethodClass(method);
    const path = data.path || '--';
    const detail = data.detail || '';
    const status = data.status || '';
    const duration = data.duration ? `${data.duration}ms` : '';

    let statusClass = '';
    if (status) {
        if (status < 300) statusClass = 's2xx';
        else if (status < 500) statusClass = 's4xx';
        else statusClass = 's5xx';
    }

    entry.innerHTML = `
        <span class="log-time">${timeStr}</span>
        <span class="log-method ${methodClass}">${method}</span>
        <div class="log-body">
            <div class="log-path">${escapeHtml(path)}</div>
            ${detail ? `<div class="log-detail">${escapeHtml(detail)}</div>` : ''}
        </div>
        ${status ? `<span class="log-status ${statusClass}">${status}</span>` : ''}
        ${duration ? `<span class="log-duration">${duration}</span>` : ''}
    `;

    // Insert at top (newest first)
    log.insertBefore(entry, log.firstChild);

    logEntries.push(data);
    if (logEntries.length > MAX_LOG) {
        logEntries.shift();
        if (log.lastChild && log.lastChild !== empty) {
            log.removeChild(log.lastChild);
        }
    }

    document.getElementById('log-count').textContent = `${logEntries.length} events`;
}

function getMethodClass(method) {
    switch (method) {
        case 'GET': return 'get';
        case 'POST': return 'post';
        case 'PUT': return 'put';
        case 'DELETE': return 'delete';
        case 'WS': return 'ws';
        case 'MCP': return 'mcp';
        default: return 'system';
    }
}

// ═══════════════════════════════════════════════════════════════════
//  CONNECTIONS PANEL
// ═══════════════════════════════════════════════════════════════════

function updateConnections(connections) {
    const list = document.getElementById('connections-list');
    const empty = document.getElementById('conn-empty');

    // Remove existing items
    list.querySelectorAll('.conn-item').forEach(el => el.remove());

    // Filter out dashboard connection
    const docConns = connections.filter(c => c.doc_id !== 'dashboard');

    if (docConns.length === 0) {
        if (empty) empty.style.display = 'flex';
        document.getElementById('conn-count').textContent = '0';
        return;
    }

    if (empty) empty.style.display = 'none';

    let totalClients = 0;
    docConns.forEach(c => {
        totalClients += c.clients;
        const el = document.createElement('div');
        el.className = 'conn-item';
        el.innerHTML = `
            <div class="conn-doc-name">${escapeHtml(c.title || c.doc_id)}</div>
            <div class="conn-meta">
                <span class="conn-clients"><span class="dot"></span> ${c.clients} client${c.clients !== 1 ? 's' : ''}</span>
                <span class="conn-id">${c.doc_id}</span>
            </div>
        `;
        list.appendChild(el);
    });

    document.getElementById('conn-count').textContent = totalClients.toString();
}

// ═══════════════════════════════════════════════════════════════════
//  UPTIME CLOCK
// ═══════════════════════════════════════════════════════════════════

function updateUptime() {
    if (!startTime) return;
    const diff = Math.floor((Date.now() - startTime.getTime()) / 1000);

    const h = Math.floor(diff / 3600);
    const m = Math.floor((diff % 3600) / 60);
    const s = diff % 60;

    let str;
    if (h > 0) str = `${h}h ${m}m`;
    else if (m > 0) str = `${m}m ${s}s`;
    else str = `${s}s`;

    document.getElementById('stat-uptime').textContent = str;
}

function updateClock() {
    const now = new Date();
    document.getElementById('header-clock').textContent = now.toLocaleTimeString('en-US', { hour12: false });
}

// ═══════════════════════════════════════════════════════════════════
//  UTILITIES
// ═══════════════════════════════════════════════════════════════════

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str || '';
    return div.innerHTML;
}

// ═══════════════════════════════════════════════════════════════════
//  POLLING FOR STATS (fallback alongside WS)
// ═══════════════════════════════════════════════════════════════════

async function pollStats() {
    try {
        const res = await fetch('/api/dashboard/stats');
        if (res.ok) {
            const data = await res.json();
            handleEvent({ type: 'stats', ...data });
            handleEvent({ type: 'server_info', ...data });
            if (data.connections) {
                updateConnections(data.connections);
            }
        }
    } catch (e) { /* ignore — server may be down */ }
}

// ═══════════════════════════════════════════════════════════════════
//  INIT
// ═══════════════════════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {
    connectDashboard();
    pollStats();

    // Update clocks every second
    setInterval(() => {
        updateUptime();
        updateClock();
    }, 1000);

    // Poll stats every 5 seconds
    setInterval(pollStats, 5000);

    // Clear log button
    document.getElementById('btn-clear-log').addEventListener('click', () => {
        const log = document.getElementById('activity-log');
        log.querySelectorAll('.log-entry').forEach(el => el.remove());
        const empty = document.getElementById('log-empty');
        if (empty) empty.style.display = 'flex';
        logEntries = [];
        document.getElementById('log-count').textContent = '0 events';
    });

    updateClock();
});
