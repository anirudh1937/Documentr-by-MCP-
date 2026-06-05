/**
 * MCP Document Editor — Frontend Application Logic (Phase 2)
 *
 * Handles document CRUD, WebSocket real-time sync, Quill.js editor,
 * version history, search/replace, export, collaborative presence,
 * markdown mode, document pinning, and native HUD backend monitor.
 */

// ═══════════════════════════════════════════════════════════════════
//  STATE
// ═══════════════════════════════════════════════════════════════════

const API = '/api/documents';
let currentDocId = null;
let ws = null;
let quill = null;
let saveTimeout = null;
let isRemoteUpdate = false;
let pendingDeleteId = null;
let isMarkdownMode = false;
let typingTimeout = null;
let typingIndicatorTimeout = null;

// ── User Identity (Collaborative Presence) ──
const USER_COLORS = [
    '#6366f1', '#8b5cf6', '#ec4899', '#f43f5e', '#10b981',
    '#06b6d4', '#f59e0b', '#a855f7', '#3b82f6', '#14b8a6',
    '#f97316', '#84cc16', '#e879f9', '#22d3ee', '#fb7185',
];

const ADJECTIVES = [
    'Coral', 'Azure', 'Sage', 'Ruby', 'Amber', 'Jade', 'Onyx',
    'Pearl', 'Slate', 'Violet', 'Crimson', 'Golden', 'Frost',
    'Storm', 'Lunar', 'Solar', 'Misty', 'Swift', 'Bold', 'Calm',
];

const ANIMALS = [
    'Fox', 'Wolf', 'Bear', 'Hawk', 'Lynx', 'Raven', 'Otter',
    'Puma', 'Heron', 'Eagle', 'Falcon', 'Dove', 'Owl', 'Crane',
    'Tiger', 'Stag', 'Viper', 'Finch', 'Robin', 'Lark',
];

function generateUserIdentity() {
    const stored = localStorage.getItem('mcp-editor-user');
    if (stored) {
        try {
            return JSON.parse(stored);
        } catch (e) { /* regenerate */ }
    }

    const adj = ADJECTIVES[Math.floor(Math.random() * ADJECTIVES.length)];
    const animal = ANIMALS[Math.floor(Math.random() * ANIMALS.length)];
    const color = USER_COLORS[Math.floor(Math.random() * USER_COLORS.length)];
    const identity = { name: `${adj} ${animal}`, color };
    localStorage.setItem('mcp-editor-user', JSON.stringify(identity));
    return identity;
}

const userIdentity = generateUserIdentity();


// ═══════════════════════════════════════════════════════════════════
//  INITIALISE QUILL EDITOR
// ═══════════════════════════════════════════════════════════════════

function initQuill() {
    if (typeof Quill === 'undefined') {
        console.warn('Quill editor library not loaded. Falling back to plain text area.');
        toast('Quill editor failed to load. Falling back to basic editor.', 'info');
        
        // Hide Quill toolbar
        const toolbar = document.getElementById('quill-toolbar');
        if (toolbar) toolbar.style.display = 'none';

        // Show fallback textarea
        const wrapper = document.getElementById('editor-richtext');
        if (wrapper) {
            wrapper.innerHTML = `<textarea id="quill-fallback-editor" style="width:100%; height:100%; border:none; padding:20px 24px; background:transparent; color:var(--text-primary); font-family:inherit; font-size:14px; line-height:1.6; outline:none; resize:none;" placeholder="Start writing something amazing…"></textarea>`;
            const textarea = document.getElementById('quill-fallback-editor');
            textarea.addEventListener('input', () => {
                // Update word count
                updateWordCount();

                // Update local graph connections in real time
                updateLocalGraph();

                // Auto-save with debounce
                clearTimeout(saveTimeout);
                setStatusSaving();
                saveTimeout = setTimeout(() => saveDocument(), 800);

                // Send via WebSocket
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({
                        type: 'edit',
                        content: textarea.value,
                    }));
                    sendTypingIndicator();
                }
            });
        }
        return;
    }

    const modules = {
        toolbar: '#quill-toolbar',
    };

    if (window.hljs) {
        modules.syntax = { hljs: window.hljs };
    }

    quill = new Quill('#quill-editor', {
        modules: modules,
        theme: 'snow',
        placeholder: 'Start writing something amazing…',
    });

    quill.on('text-change', (delta, oldDelta, source) => {
        if (source !== 'user') return;
        if (isRemoteUpdate) return;

        // Update word count
        updateWordCount();

        // Update local graph connections in real time
        updateLocalGraph();

        // Auto-save with debounce
        clearTimeout(saveTimeout);
        setStatusSaving();
        saveTimeout = setTimeout(() => saveDocument(), 800);

        // Send via WebSocket
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({
                type: 'edit',
                content: quill.root.innerHTML,
            }));

            // Send typing indicator (throttled)
            sendTypingIndicator();
        }
    });
}


// ═══════════════════════════════════════════════════════════════════
//  DOCUMENT OPERATIONS
// ═══════════════════════════════════════════════════════════════════

async function fetchDocuments(query = '') {
    const url = query ? `${API}?q=${encodeURIComponent(query)}` : API;
    try {
        const res = await fetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return await res.json();
    } catch (e) {
        console.error('Failed to fetch documents:', e);
        toast('Failed to load documents', 'error');
        return [];
    }
}

async function createDocument() {
    try {
        const res = await fetch(API, {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: 'title=Untitled+Document&content=&tags=',
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        toast('Document created', 'success');
        await refreshDocList();
        await openDocument(data.id);
        return data;
    } catch (e) {
        console.error('Failed to create document:', e);
        toast('Failed to create document', 'error');
        return null;
    }
}

async function openDocument(docId) {
    try {
        const res = await fetch(`${API}/${docId}`);
        if (!res.ok) {
            toast('Document not found', 'error');
            return;
        }
        const doc = await res.json();

        currentDocId = docId;

        // Show editor
        const welcomeScreen = document.getElementById('welcome-screen');
        if (welcomeScreen) welcomeScreen.style.display = 'none';
        const editorContainer = document.getElementById('editor-content-wrapper');
        if (editorContainer) editorContainer.style.display = 'flex';

        // Set content
        const titleEl = document.getElementById('doc-title');
        if (titleEl) titleEl.value = doc.title;

        if (isMarkdownMode) {
            // Convert HTML to markdown for the markdown editor
            const mdInput = document.getElementById('markdown-input');
            if (mdInput) mdInput.value = htmlToMarkdown(doc.content || '');
            renderMarkdownPreview();
        } else {
            isRemoteUpdate = true;
            if (quill) {
                quill.root.innerHTML = doc.content || '';
            } else {
                const textarea = document.getElementById('quill-fallback-editor');
                if (textarea) textarea.value = doc.content || '';
            }
            isRemoteUpdate = false;
        }

        // Update UI
        updateWordCount();
        const versionCount = document.getElementById('version-count');
        if (versionCount) versionCount.textContent = `${doc.version_count} versions`;
        highlightActiveDoc(docId);

        // Connect WebSocket
        connectWebSocket(docId);

        // Close mobile sidebar
        document.getElementById('sidebar')?.classList.remove('mobile-open');
    } catch (e) {
        console.error('Failed to open document:', e);
        toast('Failed to open document', 'error');
    }
}

async function saveDocument() {
    if (!currentDocId) return;

    let content;
    if (isMarkdownMode) {
        const md = document.getElementById('markdown-input').value;
        content = marked.parse(md);
    } else {
        if (quill) {
            content = quill.root.innerHTML;
        } else {
            const textarea = document.getElementById('quill-fallback-editor');
            content = textarea ? textarea.value : '';
        }
    }
    const title = document.getElementById('doc-title').value;

    const body = new URLSearchParams({
        content: content,
        title: title,
        summary: 'Auto-save',
    });

    try {
        const res = await fetch(`${API}/${currentDocId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: body.toString(),
        });

        if (res.ok) {
            const data = await res.json();
            setStatusSaved();
            updateWordCount();
            document.getElementById('version-count').textContent =
                `${data.version_count || 0} versions`;
        } else {
            setStatusError();
        }
    } catch (e) {
        console.error('Failed to save document:', e);
        setStatusError();
    }
}

function requestDeleteDocument(docId, docTitle) {
    pendingDeleteId = docId;
    const nameEl = document.getElementById('delete-doc-name');
    nameEl.textContent = docTitle || docId;
    document.getElementById('delete-modal').classList.add('active');
}

async function confirmDeleteDocument() {
    if (!pendingDeleteId) return;
    const docId = pendingDeleteId;
    closeDeleteModal();

    try {
        const res = await fetch(`${API}/${docId}`, { method: 'DELETE' });
        if (res.ok) {
            toast('Document deleted', 'info');
            if (currentDocId === docId) {
                currentDocId = null;
                const editorContainer = document.getElementById('editor-content-wrapper');
                if (editorContainer) editorContainer.style.display = 'none';
                const welcomeScreen = document.getElementById('welcome-screen');
                if (welcomeScreen) welcomeScreen.style.display = 'flex';
                disconnectWebSocket();
            }
            await refreshDocList();
        } else {
            toast('Failed to delete document', 'error');
        }
    } catch (e) {
        console.error('Failed to delete document:', e);
        toast('Failed to delete document', 'error');
    }
}

function closeDeleteModal() {
    document.getElementById('delete-modal').classList.remove('active');
    pendingDeleteId = null;
}

// ═══════════════════════════════════════════════════════════════════
//  DOCUMENT LIST (with Pinning)
// ═══════════════════════════════════════════════════════════════════

async function refreshDocList(query = '') {
    const listInternal = document.getElementById('editor-doc-list');
    const listDash = document.getElementById('dash-documents-list');

    const docs = await fetchDocuments(query);

    // 1. Populate Editor Doc List
    if (listInternal) {
        listInternal.innerHTML = '';
        if (docs.length === 0) {
            listInternal.innerHTML = '<div class="empty-scan-state">No documents yet.</div>';
        } else {
            const pinnedDocs = docs.filter(d => d.pinned);
            const unpinnedDocs = docs.filter(d => !d.pinned);

            if (pinnedDocs.length > 0) {
                const header = document.createElement('div');
                header.className = 'doc-pinned-header';
                header.innerHTML = '📌 Pinned';
                listInternal.appendChild(header);
                pinnedDocs.forEach(doc => listInternal.appendChild(createDocItem(doc)));
            }

            if (unpinnedDocs.length > 0 && pinnedDocs.length > 0) {
                const header = document.createElement('div');
                header.className = 'doc-unpinned-header';
                header.innerHTML = 'All Documents';
                listInternal.appendChild(header);
            }
            unpinnedDocs.forEach(doc => listInternal.appendChild(createDocItem(doc)));
        }
    }

    // 2. Populate Dashboard Doc List
    if (listDash) {
        listDash.innerHTML = '';
        if (docs.length === 0) {
            listDash.innerHTML = '<div class="empty-scan-state">No documents in library.</div>';
        } else {
            // Take the top 5 recent documents
            const recentDocs = docs.slice(0, 5);
            recentDocs.forEach(doc => listDash.appendChild(createDashDocItem(doc)));
        }
    }

    // 3. Update Dashboard KPI count
    const kpiCount = document.getElementById('kpi-docs-count');
    if (kpiCount) kpiCount.innerText = docs.length;

    // 4. Update Donut Chart
    updateDonutChart(docs);

    // 5. Update Health Score Circular Gauge
    updateWorkspaceHealth(docs);
}

function createDocItem(doc) {
    const el = document.createElement('div');
    el.className = `doc-item${doc.id === currentDocId ? ' active' : ''}${doc.pinned ? ' pinned' : ''}`;
    el.dataset.id = doc.id;

    const updated = new Date(doc.updated_at);
    const timeStr = formatRelativeTime(updated);
    const safeName = escapeHtml(doc.title).replace(/'/g, "\\'");

    el.innerHTML = `
        <div class="doc-item-title">${escapeHtml(doc.title)}</div>
        <div class="doc-item-meta">
            <span>${doc.word_count} words</span>
            <span class="dot"></span>
            <span>${timeStr}</span>
        </div>
        <button class="doc-item-pin ${doc.pinned ? 'is-pinned' : ''}" title="${doc.pinned ? 'Unpin' : 'Pin'}" aria-label="${doc.pinned ? 'Unpin' : 'Pin'} ${escapeHtml(doc.title)}" onclick="event.stopPropagation(); togglePin('${doc.id}')">📌</button>
        <button class="doc-item-delete" title="Delete" aria-label="Delete ${escapeHtml(doc.title)}" onclick="event.stopPropagation(); requestDeleteDocument('${doc.id}', '${safeName}')">✕</button>
    `;
    el.addEventListener('click', () => openDocument(doc.id));
    return el;
}

function createDashDocItem(doc) {
    const el = document.createElement('div');
    el.className = 'dash-doc-item';
    
    const updated = new Date(doc.updated_at);
    const timeStr = formatRelativeTime(updated);
    const icon = doc.pinned ? '📌' : '📄';
    
    el.innerHTML = `
        <div class="doc-info-left">
            <span class="doc-item-icon">${icon}</span>
            <div>
                <div class="doc-title-bold">${escapeHtml(doc.title)}</div>
                <div class="doc-meta-small">${doc.word_count} words • updated ${timeStr}</div>
            </div>
        </div>
        <button class="btn-open-doc-dash" data-id="${doc.id}">Open</button>
    `;
    el.querySelector('.btn-open-doc-dash').addEventListener('click', () => {
        openDocument(doc.id);
        switchView('workspace');
    });
    return el;
}

function updateDonutChart(docs) {
    const total = docs.length;
    const totalLabel = document.getElementById('dash-total-docs');
    if (totalLabel) totalLabel.innerText = total;

    const pinnedCount = docs.filter(d => d.pinned).length;
    const unpinnedCount = total - pinnedCount;

    const legendPinned = document.getElementById('legend-count-pinned');
    const legendUnpinned = document.getElementById('legend-count-unpinned');
    if (legendPinned) legendPinned.innerText = pinnedCount;
    if (legendUnpinned) legendUnpinned.innerText = unpinnedCount;

    const segPinned = document.getElementById('donut-seg-pinned');
    const segUnpinned = document.getElementById('donut-seg-unpinned');

    if (total === 0) {
        segPinned?.setAttribute('stroke-dasharray', '0 100');
        segUnpinned?.setAttribute('stroke-dasharray', '0 100');
        return;
    }

    const pinnedPercent = (pinnedCount / total) * 100;
    const unpinnedPercent = (unpinnedCount / total) * 100;

    segPinned?.setAttribute('stroke-dasharray', `${pinnedPercent} 100`);
    
    // Position unpinned segment after pinned segment
    segUnpinned?.setAttribute('stroke-dasharray', `${unpinnedPercent} 100`);
    segUnpinned?.setAttribute('stroke-dashoffset', `${100 - pinnedPercent + 25}`);
}

function updateWorkspaceHealth(docs) {
    if (docs.length === 0) {
        const score = document.getElementById('gauge-score');
        if (score) score.innerText = '0';
        document.getElementById('health-gauge-value')?.setAttribute('stroke-dasharray', '0 100');
        
        const fVal = document.getElementById('bar-val-formatting');
        const fFill = document.getElementById('bar-fill-formatting');
        if (fVal) fVal.innerText = '0%';
        if (fFill) fFill.style.width = '0%';
        
        const vVal = document.getElementById('bar-val-vocabulary');
        const vFill = document.getElementById('bar-fill-vocabulary');
        if (vVal) vVal.innerText = '0%';
        if (vFill) vFill.style.width = '0%';
        return;
    }

    let totalWords = 0;
    let pinnedRatio = docs.filter(d => d.pinned).length / docs.length;
    docs.forEach(d => {
        totalWords += d.word_count || 0;
    });

    const avgWords = totalWords / docs.length;
    
    // Formatting score: based on avg word counts and pinned documents structure
    let formattingScore = Math.min(Math.round(40 + (avgWords / 15) + (pinnedRatio * 20)), 95);
    // Vocabulary score: based on variety and document counts
    let vocabularyScore = Math.min(Math.round(50 + (docs.length * 4) + (avgWords / 30)), 98);
    
    // Overall Health Score
    let overallScore = Math.round((formattingScore + vocabularyScore) / 2);

    const score = document.getElementById('gauge-score');
    if (score) score.innerText = overallScore;
    document.getElementById('health-gauge-value')?.setAttribute('stroke-dasharray', `${overallScore} 100`);

    const fVal = document.getElementById('bar-val-formatting');
    const fFill = document.getElementById('bar-fill-formatting');
    if (fVal) fVal.innerText = `${formattingScore}%`;
    if (fFill) fFill.style.width = `${formattingScore}%`;

    const vVal = document.getElementById('bar-val-vocabulary');
    const vFill = document.getElementById('bar-fill-vocabulary');
    if (vVal) vVal.innerText = `${vocabularyScore}%`;
    if (vFill) vFill.style.width = `${vocabularyScore}%`;
}

function updateLangSmithStatus(langsmith) {
    const badge = document.getElementById('obs-status-badge');
    const projectName = document.getElementById('obs-project-name');
    const desc = document.getElementById('obs-status-description');
    const icon = document.getElementById('obs-status-icon');

    if (!badge || !projectName || !desc) return;

    if (langsmith && langsmith.tracing) {
        badge.innerText = 'Active';
        badge.className = 'obs-badge active';
        projectName.innerText = langsmith.project || 'mcp-document-editor';
        desc.innerText = 'LangChain telemetry is tracing your MCP tool calls and document queries in real-time.';
        if (icon) {
            icon.innerText = '🟢';
            icon.style.background = '#dcfce7';
        }
    } else {
        badge.innerText = 'Off';
        badge.className = 'obs-badge inactive';
        projectName.innerText = 'Telemetry Inactive';
        desc.innerText = 'Set LANGCHAIN_TRACING_V2=true and LANGCHAIN_API_KEY in your .env file to trace MCP executions.';
        if (icon) {
            icon.innerText = '🔍';
            icon.style.background = 'var(--bg-tertiary)';
        }
    }
}

async function handleFileUpload(file) {
    const formData = new FormData();
    formData.append('file', file);

    try {
        toast('Uploading file...', 'info');
        const res = await fetch('/api/documents/import', {
            method: 'POST',
            body: formData
        });
        if (!res.ok) throw new Error(`Status ${res.status}`);
        const data = await res.json();
        toast(`File imported: ${data.title}`, 'success');
        
        await refreshDocList();
        await openDocument(data.id);
        switchView('workspace');
    } catch (e) {
        console.error('File import failed:', e);
        toast(`File import failed: ${e.message}`, 'error');
    }
}

async function scanLocalFolder() {
    try {
        toast('Scanning workspace folder...', 'info');
        const res = await fetch('/api/documents/scan');
        if (!res.ok) throw new Error(`Status ${res.status}`);
        const data = await res.json();
        renderScannedFiles(data.files || []);
        toast(`Scan complete. Found ${data.files ? data.files.length : 0} files.`, 'success');
    } catch (e) {
        console.error('Directory scan failed:', e);
        toast(`Scan failed: ${e.message}`, 'error');
    }
}

function renderScannedFiles(files) {
    const list = document.getElementById('local-files-list');
    if (!list) return;

    list.innerHTML = '';
    if (files.length === 0) {
        list.innerHTML = `<div class="empty-scan-state">📂 No untracked .md or .txt files found in workspace root.</div>`;
        return;
    }

    files.forEach(file => {
        const el = document.createElement('div');
        el.className = 'local-file-item';
        
        const sizeKB = (file.size / 1024).toFixed(1);
        
        el.innerHTML = `
            <div>
                <div class="local-file-name" title="${escapeHtml(file.path)}">${escapeHtml(file.name)}</div>
                <div class="local-file-size">${sizeKB} KB</div>
            </div>
            <button class="btn-import-local">Import</button>
        `;
        el.querySelector('.btn-import-local').addEventListener('click', async () => {
            await importLocalFile(file.path);
        });
        list.appendChild(el);
    });
}

async function importLocalFile(filePath) {
    try {
        toast('Importing local file...', 'info');
        const formData = new FormData();
        formData.append('path', filePath);
        
        const res = await fetch('/api/documents/import-local', {
            method: 'POST',
            body: formData
        });
        if (!res.ok) throw new Error(`Status ${res.status}`);
        const data = await res.json();
        toast(`Imported: ${data.title}`, 'success');
        
        await refreshDocList();
        await openDocument(data.id);
        switchView('workspace');
    } catch (e) {
        console.error('Local file import failed:', e);
        toast(`Import failed: ${e.message}`, 'error');
    }
}

function switchView(view) {
    const globalTab = document.getElementById('tab-global-view');
    const workspaceTab = document.getElementById('tab-workspace-view');
    const dashboardPane = document.getElementById('dashboard-pane');
    const editorPane = document.getElementById('editor-pane');

    if (view === 'global') {
        globalTab?.classList.add('active');
        workspaceTab?.classList.remove('active');
        dashboardPane?.classList.add('active');
        editorPane?.classList.remove('active');
        setActiveNavItem('nav-dashboard');
    } else {
        globalTab?.classList.remove('active');
        workspaceTab?.classList.add('active');
        dashboardPane?.classList.remove('active');
        editorPane?.classList.add('active');
        setActiveNavItem('nav-library');
    }
}

function setActiveNavItem(id) {
    document.querySelectorAll('.global-sidebar .nav-item').forEach(btn => {
        btn.classList.remove('active');
    });
    document.getElementById(id)?.classList.add('active');
}

async function togglePin(docId) {
    try {
        const res = await fetch(`${API}/${docId}/pin`, { method: 'POST' });
        if (res.ok) {
            const data = await res.json();
            toast(data.message, 'info');
            await refreshDocList();
        } else {
            toast('Failed to toggle pin', 'error');
        }
    } catch (e) {
        console.error('Failed to toggle pin:', e);
        toast('Failed to toggle pin', 'error');
    }
}

function highlightActiveDoc(docId) {
    document.querySelectorAll('.doc-item').forEach(el => {
        el.classList.toggle('active', el.dataset.id === docId);
    });
}


// ═══════════════════════════════════════════════════════════════════
//  WEBSOCKET — REAL-TIME COLLABORATION
// ═══════════════════════════════════════════════════════════════════

function connectWebSocket(docId) {
    disconnectWebSocket();

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${location.host}/ws/${docId}`;

    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        setStatusConnected();
        // Announce our identity
        ws.send(JSON.stringify({
            type: 'join',
            name: userIdentity.name,
            color: userIdentity.color,
        }));
    };

    ws.onmessage = (event) => {
        let data;
        try {
            data = JSON.parse(event.data);
        } catch (e) {
            console.warn('Malformed WebSocket message:', e);
            return;
        }

        // If graph view is active, refresh graph data on structural changes
        if (data.type === 'update' || data.type === 'title') {
            const overlay = document.getElementById('graph-modal-overlay');
            if (overlay && overlay.classList.contains('active')) {
                refreshGraphData();
            }
        }

        switch (data.type) {
            case 'init':
                renderAvatarStack(data.users || []);
                break;

            case 'update':
                // Remote edit — update editor preserving cursor
                if (isMarkdownMode) {
                    // In markdown mode, convert incoming HTML to markdown
                    document.getElementById('markdown-input').value = htmlToMarkdown(data.content);
                    renderMarkdownPreview();
                } else {
                    isRemoteUpdate = true;
                    if (quill) {
                        const selection = quill.getSelection();
                        const scrollTop = quill.root.parentElement?.scrollTop || 0;
                        quill.root.innerHTML = data.content;
                        if (selection) {
                            try {
                                quill.setSelection(selection.index, selection.length, 'silent');
                            } catch (e) { /* cursor position may be out of bounds */ }
                        }
                        if (quill.root.parentElement) {
                            quill.root.parentElement.scrollTop = scrollTop;
                        }
                    } else {
                        const textarea = document.getElementById('quill-fallback-editor');
                        if (textarea) textarea.value = data.content || '';
                    }
                    isRemoteUpdate = false;
                }
                updateWordCount();
                break;

            case 'title':
                document.getElementById('doc-title').value = data.title;
                refreshDocList();
                break;

            case 'presence':
                renderAvatarStack(data.users || []);
                break;

            case 'typing':
                showTypingIndicator(data.name, data.color);
                break;
        }
    };

    ws.onclose = () => {
        setStatusDisconnected();
        // Auto-reconnect after 3 seconds
        setTimeout(() => {
            if (currentDocId === docId) {
                connectWebSocket(docId);
            }
        }, 3000);
    };

    ws.onerror = () => {
        setStatusError();
    };
}

function disconnectWebSocket() {
    if (ws) {
        try {
            ws.close();
        } catch (e) { /* already closed */ }
        ws = null;
    }
}


// ═══════════════════════════════════════════════════════════════════
//  COLLABORATIVE PRESENCE
// ═══════════════════════════════════════════════════════════════════

function renderAvatarStack(users) {
    const stack = document.getElementById('avatar-stack');
    stack.innerHTML = '';

    if (!users || users.length === 0) return;

    // Show up to 5 avatars, then a +N circle
    const maxShow = 5;
    const toShow = users.slice(0, maxShow);
    const overflow = users.length - maxShow;

    toShow.forEach(u => {
        const circle = document.createElement('div');
        circle.className = 'avatar-circle';
        circle.style.background = u.color || '#6366f1';
        const initials = (u.name || 'A').split(' ').map(w => w[0]).join('').slice(0, 2);
        circle.textContent = initials;

        const tooltip = document.createElement('span');
        tooltip.className = 'avatar-tooltip';
        tooltip.textContent = u.name || 'Anonymous';
        circle.appendChild(tooltip);

        stack.appendChild(circle);
    });

    if (overflow > 0) {
        const more = document.createElement('div');
        more.className = 'avatar-circle';
        more.style.background = 'var(--bg-tertiary)';
        more.textContent = `+${overflow}`;
        stack.appendChild(more);
    }
}

function sendTypingIndicator() {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;

    clearTimeout(typingTimeout);
    typingTimeout = setTimeout(() => {
        // Throttle: only send typing once every 2s
    }, 2000);

    // Send immediately if not recently sent
    if (!typingTimeout._sent) {
        ws.send(JSON.stringify({ type: 'typing' }));
        typingTimeout._sent = true;
        setTimeout(() => { typingTimeout._sent = false; }, 2000);
    }
}

function showTypingIndicator(name, color) {
    const indicator = document.getElementById('typing-indicator');
    const nameEl = document.getElementById('typing-name');
    nameEl.textContent = name || 'Someone';
    nameEl.style.color = color || 'var(--accent-primary)';
    indicator.style.display = 'flex';

    clearTimeout(typingIndicatorTimeout);
    typingIndicatorTimeout = setTimeout(() => {
        indicator.style.display = 'none';
    }, 3000);
}


// ═══════════════════════════════════════════════════════════════════
//  MARKDOWN MODE
// ═══════════════════════════════════════════════════════════════════

function toggleMarkdownMode() {
    isMarkdownMode = !isMarkdownMode;

    const richEditor = document.getElementById('editor-richtext');
    const mdEditor = document.getElementById('editor-markdown');
    const toggleBtn = document.getElementById('btn-markdown-toggle');
    const modeBadge = document.getElementById('editor-mode-badge');

    if (isMarkdownMode) {
        // Switch to Markdown mode
        const html = quill.root.innerHTML;
        const md = htmlToMarkdown(html);
        document.getElementById('markdown-input').value = md;
        renderMarkdownPreview();

        richEditor.style.display = 'none';
        mdEditor.style.display = 'flex';
        toggleBtn.classList.add('active');
        modeBadge.textContent = '💻 Markdown';
    } else {
        // Switch to Rich Text mode
        const md = document.getElementById('markdown-input').value;
        const html = marked.parse(md);
        isRemoteUpdate = true;
        quill.root.innerHTML = html;
        isRemoteUpdate = false;

        richEditor.style.display = 'flex';
        mdEditor.style.display = 'none';
        toggleBtn.classList.remove('active');
        modeBadge.textContent = '📝 Rich Text';
    }

    // Save mode preference
    localStorage.setItem('mcp-editor-mode', isMarkdownMode ? 'markdown' : 'richtext');
    updateWordCount();
}

function renderMarkdownPreview() {
    const md = document.getElementById('markdown-input').value;
    const preview = document.getElementById('markdown-preview');
    try {
        preview.innerHTML = marked.parse(md);
    } catch (e) {
        preview.innerHTML = '<p style="color: var(--accent-rose);">Error rendering markdown</p>';
    }
}

// Simple HTML to Markdown converter
function htmlToMarkdown(html) {
    if (!html || html === '<p><br></p>') return '';

    let md = html;

    // Headers
    md = md.replace(/<h1[^>]*>(.*?)<\/h1>/gi, '# $1\n\n');
    md = md.replace(/<h2[^>]*>(.*?)<\/h2>/gi, '## $1\n\n');
    md = md.replace(/<h3[^>]*>(.*?)<\/h3>/gi, '### $1\n\n');

    // Bold / Italic / Strike
    md = md.replace(/<strong>(.*?)<\/strong>/gi, '**$1**');
    md = md.replace(/<b>(.*?)<\/b>/gi, '**$1**');
    md = md.replace(/<em>(.*?)<\/em>/gi, '*$1*');
    md = md.replace(/<i>(.*?)<\/i>/gi, '*$1*');
    md = md.replace(/<s>(.*?)<\/s>/gi, '~~$1~~');
    md = md.replace(/<del>(.*?)<\/del>/gi, '~~$1~~');
    md = md.replace(/<u>(.*?)<\/u>/gi, '$1');

    // Links and images
    md = md.replace(/<a[^>]*href="([^"]*)"[^>]*>(.*?)<\/a>/gi, '[$2]($1)');
    md = md.replace(/<img[^>]*src="([^"]*)"[^>]*alt="([^"]*)"[^>]*\/?>/gi, '![$2]($1)');
    md = md.replace(/<img[^>]*src="([^"]*)"[^>]*\/?>/gi, '![]($1)');

    // Code blocks
    md = md.replace(/<pre[^>]*><code[^>]*>([\s\S]*?)<\/code><\/pre>/gi, '```\n$1\n```\n\n');
    md = md.replace(/<pre[^>]*>([\s\S]*?)<\/pre>/gi, '```\n$1\n```\n\n');

    // Inline code
    md = md.replace(/<code>(.*?)<\/code>/gi, '`$1`');

    // Blockquote
    md = md.replace(/<blockquote>([\s\S]*?)<\/blockquote>/gi, (match, content) => {
        return content.replace(/<p>(.*?)<\/p>/gi, '> $1\n').replace(/<br\s*\/?>/gi, '\n> ');
    });

    // Lists
    md = md.replace(/<ul>([\s\S]*?)<\/ul>/gi, (match, content) => {
        return content.replace(/<li>(.*?)<\/li>/gi, '- $1\n') + '\n';
    });
    md = md.replace(/<ol>([\s\S]*?)<\/ol>/gi, (match, content) => {
        let i = 0;
        return content.replace(/<li>(.*?)<\/li>/gi, () => `${++i}. ` + '$1\n') + '\n';
    });

    // Paragraphs and line breaks
    md = md.replace(/<p>(.*?)<\/p>/gi, '$1\n\n');
    md = md.replace(/<br\s*\/?>/gi, '\n');

    // Strip remaining HTML tags
    md = md.replace(/<[^>]+>/g, '');

    // Decode HTML entities
    md = md.replace(/&amp;/g, '&');
    md = md.replace(/&lt;/g, '<');
    md = md.replace(/&gt;/g, '>');
    md = md.replace(/&quot;/g, '"');
    md = md.replace(/&#39;/g, "'");
    md = md.replace(/&nbsp;/g, ' ');

    // Clean up extra whitespace
    md = md.replace(/\n{3,}/g, '\n\n');
    return md.trim();
}


// ═══════════════════════════════════════════════════════════════════
//  VERSION HISTORY
// ═══════════════════════════════════════════════════════════════════

async function openVersionPanel() {
    if (!currentDocId) return;

    try {
        const res = await fetch(`${API}/${currentDocId}/versions`);
        if (!res.ok) {
            toast('Failed to load version history', 'error');
            return;
        }

        const versions = await res.json();
        const list = document.getElementById('version-list');
        list.innerHTML = '';

        if (versions.length === 0) {
            list.innerHTML = '<p style="color:var(--text-muted); text-align:center; padding:20px;">No versions yet.</p>';
        } else {
            versions.forEach(v => {
                const el = document.createElement('div');
                el.className = 'version-item';
                const time = new Date(v.timestamp);
                el.innerHTML = `
                    <div class="version-summary">${escapeHtml(v.summary || 'Snapshot')}</div>
                    <div class="version-time">${time.toLocaleString()}</div>
                    <button class="version-restore" onclick="restoreVersion('${v.version_id}')">Restore</button>
                `;
                list.appendChild(el);
            });
        }

        document.getElementById('version-panel').classList.add('active');
        document.getElementById('panel-overlay').classList.add('active');
    } catch (e) {
        console.error('Failed to load versions:', e);
        toast('Failed to load version history', 'error');
    }
}

function closeVersionPanel() {
    document.getElementById('version-panel').classList.remove('active');
    document.getElementById('panel-overlay').classList.remove('active');
}

async function restoreVersion(versionId) {
    if (!currentDocId) return;

    try {
        const res = await fetch(`${API}/${currentDocId}/restore/${versionId}`, { method: 'POST' });
        if (res.ok) {
            toast('Version restored', 'success');
            closeVersionPanel();
            await openDocument(currentDocId);
        } else {
            toast('Failed to restore version', 'error');
        }
    } catch (e) {
        console.error('Failed to restore version:', e);
        toast('Failed to restore version', 'error');
    }
}


// ═══════════════════════════════════════════════════════════════════
//  SEARCH & REPLACE
// ═══════════════════════════════════════════════════════════════════

function openSearchModal() {
    if (!currentDocId) return;
    document.getElementById('search-modal').classList.add('active');
    document.getElementById('search-input').focus();
    document.getElementById('search-result').classList.remove('visible');
}

function closeSearchModal() {
    document.getElementById('search-modal').classList.remove('active');
}

async function executeSearchReplace() {
    const search = document.getElementById('search-input').value;
    const replace = document.getElementById('replace-input').value;
    const regex = document.getElementById('regex-toggle').checked;

    if (!search) return;

    const body = new URLSearchParams({ search, replace, regex: regex.toString() });

    try {
        const res = await fetch(`${API}/${currentDocId}/search-replace`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: body.toString(),
        });

        const resultEl = document.getElementById('search-result');

        if (res.ok) {
            const data = await res.json();
            resultEl.textContent = data.message;
            resultEl.className = 'modal-result visible';
            // Refresh editor content
            await openDocument(currentDocId);
            toast(data.message, 'success');
        } else {
            const err = await res.json();
            resultEl.textContent = err.error || 'An error occurred';
            resultEl.className = 'modal-result visible error';
        }
    } catch (e) {
        console.error('Search/replace failed:', e);
        toast('Search/replace failed', 'error');
    }
}


// ═══════════════════════════════════════════════════════════════════
//  EXPORT
// ═══════════════════════════════════════════════════════════════════

function toggleExportDropdown() {
    document.getElementById('export-dropdown').classList.toggle('active');
}

async function exportDocument(format) {
    if (!currentDocId) return;

    document.getElementById('export-dropdown').classList.remove('active');

    const url = `${API}/${currentDocId}/export/${format}`;

    try {
        const res = await fetch(url);

        if (!res.ok) {
            toast('Export failed', 'error');
            return;
        }

        const blob = await res.blob();
        const ext = format === 'md' ? 'md' : 'html';
        const title = document.getElementById('doc-title').value || 'document';
        const filename = `${title.replace(/[^a-zA-Z0-9]/g, '_')}.${ext}`;

        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = filename;
        a.click();
        URL.revokeObjectURL(a.href);

        toast(`Exported as ${ext.toUpperCase()}`, 'success');
    } catch (e) {
        console.error('Export failed:', e);
        toast('Export failed', 'error');
    }
}


// ═══════════════════════════════════════════════════════════════════
//  NATIVE HUD — BACKEND MONITOR (Glassmorphism)
// ═══════════════════════════════════════════════════════════════════

const HUD = {
    ws: null,
    logEntries: [],
    MAX_LOG: 100,
    isOpen: false,
    isPinned: false,
    isCollapsed: false,

    open() {
        this.isOpen = true;
        document.getElementById('hud-window').classList.remove('hidden');
        document.getElementById('btn-toggle-hud').classList.add('active');
        this.connect();
    },

    close() {
        this.isOpen = false;
        document.getElementById('hud-window').classList.add('hidden');
        document.getElementById('btn-toggle-hud').classList.remove('active');
        this.disconnect();
    },

    toggle() {
        this.isOpen ? this.close() : this.open();
    },

    toggleCollapse() {
        this.isCollapsed = !this.isCollapsed;
        document.getElementById('hud-window').classList.toggle('collapsed', this.isCollapsed);
    },

    togglePin() {
        this.isPinned = !this.isPinned;
        document.getElementById('hud-window').classList.toggle('pinned', this.isPinned);
        document.getElementById('btn-pin-hud').classList.toggle('pinned', this.isPinned);
    },

    connect() {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) return;

        const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${location.host}/ws/dashboard`;

        try {
            this.ws = new WebSocket(wsUrl);
        } catch (e) {
            console.error('HUD WS failed:', e);
            return;
        }

        this.ws.onopen = () => {
            const liveDot = document.querySelector('.hud-live-dot');
            if (liveDot) liveDot.style.background = 'var(--accent-emerald)';
            this.addLogEntry({
                method: 'SYSTEM',
                path: 'Monitor connected',
                detail: 'Dashboard WebSocket stream active',
                status: 200
            });
        };

        this.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                this.handleEvent(data);
            } catch (e) { /* ignore */ }
        };

        this.ws.onclose = () => {
            const liveDot = document.querySelector('.hud-live-dot');
            if (liveDot) liveDot.style.background = 'var(--accent-rose)';

            // Auto-reconnect if still open
            if (this.isOpen) {
                setTimeout(() => this.connect(), 3000);
            }
        };
    },

    disconnect() {
        if (this.ws) {
            try { this.ws.close(); } catch (e) { /* ok */ }
            this.ws = null;
        }
    },

    handleEvent(data) {
        if (data.type === 'server_info') {
            this.updateServerInfo(data);
            this.updateStats(data);
        } else if (data.type === 'stats') {
            this.updateStats(data);
        } else if (data.type === 'connections') {
            this.updateConnections(data.connections || []);
        } else if (data.type === 'request' || data.type === 'ws_event') {
            this.addLogEntry(data);
        }
    },

    updateServerInfo(data) {
        if (data.server_name) document.getElementById('hud-info-server-name').textContent = data.server_name;
        if (data.transport) document.getElementById('hud-info-transport').textContent = data.transport;
        if (data.api_server) document.getElementById('hud-info-api').textContent = data.api_server;
        if (data.runtime) document.getElementById('hud-info-runtime').textContent = data.runtime;
        if (data.storage) document.getElementById('hud-info-storage').textContent = data.storage;
        if (data.host) document.getElementById('hud-info-host').textContent = data.host;
        if (data.pid) document.getElementById('hud-info-pid').textContent = data.pid;
        
        // Render MCP Tools list
        const toolsList = document.getElementById('hud-tools-list');
        if (toolsList) {
            toolsList.innerHTML = '';
            const tools = [
                'create_document', 'read_document', 'update_document', 'delete_document',
                'list_documents', 'search_documents', 'search_and_replace', 'get_version_history',
                'restore_version', 'export_document', 'open_editor', 'get_document_graph',
                'create_by_title'
            ];
            tools.forEach(tool => {
                const span = document.createElement('span');
                span.className = 'hud-tool-tag';
                span.textContent = tool;
                toolsList.appendChild(span);
            });
        }
    },

    updateStats(data) {
        if (data.total_requests !== undefined) {
            const el = document.getElementById('hud-requests');
            if (el) el.textContent = data.total_requests;
            const kpi = document.getElementById('kpi-reqs-count');
            if (kpi) kpi.textContent = data.total_requests;
        }
        if (data.total_errors !== undefined) {
            const el = document.getElementById('hud-errors');
            if (el) el.textContent = data.total_errors;
        }
        if (data.avg_latency_ms !== undefined) {
            const valStr = `${Math.round(data.avg_latency_ms)}ms`;
            const el = document.getElementById('hud-latency');
            if (el) el.textContent = valStr;
            const kpi = document.getElementById('kpi-health-latency');
            if (kpi) kpi.textContent = `Lat: ${valStr}`;
        }
        if (data.ws_connections !== undefined) {
            const el = document.getElementById('hud-ws');
            if (el) el.textContent = data.ws_connections;
            const kpi = document.getElementById('kpi-conns-count');
            if (kpi) kpi.textContent = data.ws_connections;
        }
        if (data.memory) {
            const el = document.getElementById('hud-memory');
            if (el) el.textContent = data.memory;
        }
        if (data.uptime) {
            const el = document.getElementById('hud-uptime');
            if (el) el.textContent = data.uptime;
            const kpi = document.getElementById('kpi-health-uptime');
            if (kpi) kpi.textContent = data.uptime;
        }
        if (data.documents !== undefined) {
            const el = document.getElementById('hud-documents-count');
            if (el) el.textContent = data.documents;
        }
        if (data.error_rate !== undefined) {
            const el = document.getElementById('hud-error-rate');
            if (el) el.textContent = `${data.error_rate}%`;
            const kpi = document.getElementById('kpi-reqs-speed');
            if (kpi) kpi.textContent = `Err: ${data.error_rate}%`;
        }
        
        // ── Observability Telemetry Card ──
        if (data.langsmith) {
            updateLangSmithStatus(data.langsmith);
        }
    },

    updateConnections(connections) {
        const list = document.getElementById('hud-connections-list');
        const empty = document.getElementById('hud-conn-empty');
        if (!list) return;

        // Clear connections
        list.querySelectorAll('.hud-conn-item').forEach(el => el.remove());

        const docConns = connections.filter(c => c.doc_id !== 'dashboard');
        if (docConns.length === 0) {
            if (empty) empty.style.display = 'flex';
            return;
        }

        if (empty) empty.style.display = 'none';

        docConns.forEach(c => {
            const el = document.createElement('div');
            el.className = 'hud-conn-item';
            el.innerHTML = `
                <div class="hud-conn-doc-name">${escapeHtml(c.title || c.doc_id)}</div>
                <span class="hud-conn-clients">${c.clients} client${c.clients !== 1 ? 's' : ''}</span>
            `;
            list.appendChild(el);
        });
    },

    addLogEntry(data) {
        const empty = document.getElementById('hud-log-empty');
        if (empty) empty.style.display = 'none';

        const log = document.getElementById('hud-log');
        if (!log) return;

        const entry = document.createElement('div');
        entry.className = 'hud-log-entry';

        const now = new Date();
        const timeStr = now.toLocaleTimeString('en-US', { hour12: false });

        const method = (data.method || 'SYSTEM').toUpperCase();
        const methodClass = method.toLowerCase();
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
            <span class="hud-log-time">${timeStr}</span>
            <span class="hud-log-method ${methodClass}">${method}</span>
            <span class="hud-log-path" title="${escapeHtml(path)}${detail ? ' - ' + escapeHtml(detail) : ''}">${escapeHtml(path)}${detail ? ' (' + escapeHtml(detail) + ')' : ''}</span>
            ${status ? `<span class="hud-log-status ${statusClass}">${status}</span>` : ''}
            ${duration ? `<span style="font-size: 9px; color: var(--text-muted); flex-shrink: 0;">${duration}</span>` : ''}
        `;

        log.insertBefore(entry, log.firstChild);

        this.logEntries.push(entry);
        if (this.logEntries.length > this.MAX_LOG) {
            const old = this.logEntries.shift();
            if (old.parentElement) old.remove();
        }

        const logCount = document.getElementById('hud-log-count');
        if (logCount) logCount.textContent = `${this.logEntries.length} events`;

        // ── Stream to Dashboard logs container ──
        const dashLog = document.getElementById('dash-logs-container');
        if (dashLog) {
            const dashEmpty = dashLog.querySelector('.log-empty-state');
            if (dashEmpty) dashEmpty.remove();

            const dashEntry = document.createElement('div');
            dashEntry.className = 'log-line';
            
            dashEntry.innerHTML = `
                <span class="log-time">[${timeStr}]</span>
                <span class="log-method ${methodClass}">${method}</span>
                <span class="log-path">${escapeHtml(path)}</span>
                ${status ? `<span class="log-status ${statusClass}">${status}</span>` : ''}
                ${detail ? `<span class="log-detail">(${escapeHtml(detail)})</span>` : ''}
                ${duration ? `<span class="log-detail">- ${duration}</span>` : ''}
            `;
            dashLog.insertBefore(dashEntry, dashLog.firstChild);

            while (dashLog.children.length > this.MAX_LOG) {
                dashLog.lastChild.remove();
            }
        }
    },

    clearLog() {
        const log = document.getElementById('hud-log');
        if (log) {
            log.querySelectorAll('.hud-log-entry').forEach(el => el.remove());
        }
        const empty = document.getElementById('hud-log-empty');
        if (empty) empty.style.display = 'flex';

        // Clear dashboard log
        const dashLog = document.getElementById('dash-logs-container');
        if (dashLog) {
            dashLog.innerHTML = `<div class="log-empty-state"><span>📡</span> Listening for network and collaborative events...</div>`;
        }

        this.logEntries = [];
        const logCount = document.getElementById('hud-log-count');
        if (logCount) logCount.textContent = '0 events';
    },
};


// ═══════════════════════════════════════════════════════════════════
//  STATUS BAR
// ═══════════════════════════════════════════════════════════════════

function setStatusConnected() {
    const dot = document.getElementById('status-dot');
    const text = document.getElementById('status-text');
    dot.className = 'status-dot connected';
    text.textContent = 'Connected';
}

function setStatusDisconnected() {
    const dot = document.getElementById('status-dot');
    const text = document.getElementById('status-text');
    dot.className = 'status-dot disconnected';
    text.textContent = 'Reconnecting…';
}

function setStatusSaving() {
    document.getElementById('status-save').textContent = '⏳ Saving…';
}

function setStatusSaved() {
    document.getElementById('status-save').textContent = '💾 Saved';
}

function setStatusError() {
    document.getElementById('status-save').textContent = '❌ Error';
}

function updateWordCount() {
    let text;
    if (isMarkdownMode) {
        text = document.getElementById('markdown-input').value.trim();
    } else {
        if (quill) {
            text = quill.getText().trim();
        } else {
            const textarea = document.getElementById('quill-fallback-editor');
            text = textarea ? textarea.value.trim() : '';
        }
    }
    const words = text ? text.split(/\s+/).length : 0;
    document.getElementById('word-count').textContent = `${words} words`;
}


// ═══════════════════════════════════════════════════════════════════
//  TOAST NOTIFICATIONS
// ═══════════════════════════════════════════════════════════════════

function toast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const el = document.createElement('div');
    el.className = `toast ${type}`;

    const icons = { success: '✅', error: '❌', info: 'ℹ️' };
    el.innerHTML = `<span>${icons[type] || 'ℹ️'}</span><span>${escapeHtml(message)}</span>`;

    container.appendChild(el);

    setTimeout(() => {
        el.style.opacity = '0';
        el.style.transform = 'translateX(20px)';
        el.style.transition = 'all 300ms';
        setTimeout(() => el.remove(), 300);
    }, 3500);
}


// ═══════════════════════════════════════════════════════════════════
//  UTILITIES
// ═══════════════════════════════════════════════════════════════════

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function formatRelativeTime(date) {
    const now = new Date();
    const diffMs = now - date;
    const diffSecs = Math.floor(diffMs / 1000);
    const diffMins = Math.floor(diffSecs / 60);
    const diffHours = Math.floor(diffMins / 60);
    const diffDays = Math.floor(diffHours / 24);

    if (diffSecs < 60) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString();
}


// ═══════════════════════════════════════════════════════════════════
//  EVENT BINDINGS
// ═══════════════════════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {
    try {
        initQuill();
    } catch (e) {
        console.error('Failed to initialize Quill editor:', e);
    }
    
    try {
        refreshDocList();
    } catch (e) {
        console.error('Failed to refresh document list:', e);
    }
    
    try {
        initAIAssistant();
    } catch (e) {
        console.error('Failed to initialize AI Assistant:', e);
    }
    
    try {
        initGraphView();
    } catch (e) {
        console.error('Failed to initialize Graph View:', e);
    }

    // Configure marked.js
    if (window.marked) {
        marked.setOptions({
            breaks: true,
            gfm: true,
        });
    }

    // Check for ?doc= or ?hud= param
    const params = new URLSearchParams(window.location.search);
    const docParam = params.get('doc');
    if (docParam) {
        openDocument(docParam);
    }
    if (params.get('hud') === '1') {
        setTimeout(() => {
            if (typeof HUD !== 'undefined') HUD.open();
        }, 300);
    }

    // ── HUD Monitor Tabs ──
    document.querySelectorAll('.hud-tabs .hud-tab-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const tabName = btn.dataset.tab;
            // Toggle tab button active state
            document.querySelectorAll('.hud-tabs .hud-tab-btn').forEach(el => el.classList.remove('active'));
            btn.classList.add('active');
            
            // Toggle tab content pane active state
            document.querySelectorAll('#hud-body .hud-tab-content').forEach(el => {
                el.classList.remove('active');
                el.style.display = 'none';
            });
            const contentPane = document.getElementById(`hud-tab-${tabName}`);
            if (contentPane) {
                contentPane.classList.add('active');
                contentPane.style.display = 'flex';
            }
        });
    });

    // ── Auto-connect live metrics telemetry stream ──
    try {
        HUD.connect();
    } catch (e) {
        console.error('Failed to auto-connect HUD metrics:', e);
    }

    // ── Sidebar Note Creation ──
    document.getElementById('btn-new-doc-dash')?.addEventListener('click', createDocument);
    document.getElementById('btn-new-doc-internal')?.addEventListener('click', createDocument);

    // ── Library Document Filtering ──
    let searchTimeout;
    document.getElementById('editor-search-input')?.addEventListener('input', (e) => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => refreshDocList(e.target.value), 300);
    });

    // ── Global Sidebar Tab Switches ──
    document.getElementById('nav-dashboard')?.addEventListener('click', () => switchView('global'));
    document.getElementById('nav-library')?.addEventListener('click', () => switchView('workspace'));
    document.getElementById('nav-graph')?.addEventListener('click', openGraphModal);
    document.getElementById('nav-hud')?.addEventListener('click', () => HUD.toggle());
    document.getElementById('nav-settings')?.addEventListener('click', () => {
        if (!isAIOpen) toggleAIPanel();
        toggleAISettings();
    });

    // ── View Toggle Tabs (Header) ──
    document.getElementById('tab-global-view')?.addEventListener('click', () => switchView('global'));
    document.getElementById('tab-workspace-view')?.addEventListener('click', () => switchView('workspace'));

    // ── Corp AI Button ──
    document.getElementById('btn-corp-ai')?.addEventListener('click', () => toggleAIPanel());

    // ── Local System Files Upload (Drag & Drop) ──
    const fileDropZone = document.getElementById('file-drop-zone');
    const fileInputUploader = document.getElementById('file-input-uploader');
    if (fileDropZone && fileInputUploader) {
        fileDropZone.addEventListener('click', () => fileInputUploader.click());
        fileInputUploader.addEventListener('change', () => {
            if (fileInputUploader.files && fileInputUploader.files[0]) {
                handleFileUpload(fileInputUploader.files[0]);
            }
        });

        ['dragenter', 'dragover'].forEach(eventName => {
            fileDropZone.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
                fileDropZone.classList.add('dragover');
            }, false);
        });

        ['dragleave', 'drop'].forEach(eventName => {
            fileDropZone.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
                fileDropZone.classList.remove('dragover');
            }, false);
        });

        fileDropZone.addEventListener('drop', (e) => {
            const dt = e.dataTransfer;
            const files = dt.files;
            if (files && files[0]) {
                handleFileUpload(files[0]);
            }
        }, false);
    }

    // ── Folder Scanner Button ──
    document.getElementById('btn-scan-files')?.addEventListener('click', () => scanLocalFolder());

    // ── Mobile sidebar toggle (optional fallback) ──
    document.getElementById('mobile-menu-btn')?.addEventListener('click', () => {
        document.getElementById('sidebar')?.classList.toggle('mobile-open');
    });

    // Close sidebar on outside click (mobile optional fallback)
    document.getElementById('main-area')?.addEventListener('click', () => {
        document.getElementById('sidebar')?.classList.remove('mobile-open');
    });

    // ── Title change ──
    document.getElementById('doc-title')?.addEventListener('change', () => {
        if (!currentDocId) return;
        clearTimeout(saveTimeout);
        saveTimeout = setTimeout(() => {
            saveDocument();
            refreshDocList();
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({
                    type: 'title',
                    title: document.getElementById('doc-title').value,
                }));
            }
        }, 500);
    });

    // ── Version History ──
    document.getElementById('btn-versions')?.addEventListener('click', openVersionPanel);
    document.getElementById('version-panel-close')?.addEventListener('click', closeVersionPanel);
    document.getElementById('panel-overlay')?.addEventListener('click', closeVersionPanel);

    // ── Search/Replace ──
    document.getElementById('btn-search-replace')?.addEventListener('click', openSearchModal);
    document.getElementById('search-cancel')?.addEventListener('click', closeSearchModal);
    document.getElementById('search-execute')?.addEventListener('click', executeSearchReplace);
    document.getElementById('search-modal')?.addEventListener('click', (e) => {
        if (e.target === document.getElementById('search-modal')) closeSearchModal();
    });

    // ── Delete Confirmation ──
    document.getElementById('delete-cancel')?.addEventListener('click', closeDeleteModal);
    document.getElementById('delete-confirm')?.addEventListener('click', confirmDeleteDocument);
    document.getElementById('delete-modal')?.addEventListener('click', (e) => {
        if (e.target === document.getElementById('delete-modal')) closeDeleteModal();
    });

    // ── Export ──
    document.getElementById('btn-export')?.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleExportDropdown();
    });

    document.querySelectorAll('#export-dropdown .dropdown-item').forEach(item => {
        item.addEventListener('click', () => exportDocument(item.dataset.format));
    });

    // Close dropdown on outside click
    document.addEventListener('click', () => {
        document.getElementById('export-dropdown')?.classList.remove('active');
    });

    // ── Markdown Mode ──
    document.getElementById('btn-markdown-toggle')?.addEventListener('click', toggleMarkdownMode);

    // Markdown input handler
    const mdInput = document.getElementById('markdown-input');
    let mdSaveTimeout;
    if (mdInput) {
        mdInput.addEventListener('input', () => {
            renderMarkdownPreview();
            updateWordCount();

            // Update local graph connections in real time
            updateLocalGraph();

            // Auto-save
            clearTimeout(mdSaveTimeout);
            setStatusSaving();
            mdSaveTimeout = setTimeout(() => saveDocument(), 800);

            // Send via WebSocket
            if (ws && ws.readyState === WebSocket.OPEN) {
                const html = marked.parse(mdInput.value);
                ws.send(JSON.stringify({
                    type: 'edit',
                    content: html,
                }));
                sendTypingIndicator();
            }
        });
    }

    // Markdown toolbar buttons
    document.getElementById('md-btn-bold')?.addEventListener('click', () => mdInsert('**', '**'));
    document.getElementById('md-btn-italic')?.addEventListener('click', () => mdInsert('*', '*'));
    document.getElementById('md-btn-code')?.addEventListener('click', () => mdInsert('`', '`'));
    document.getElementById('md-btn-link')?.addEventListener('click', () => mdInsert('[', '](url)'));
    document.getElementById('md-btn-heading')?.addEventListener('click', () => mdInsert('## ', ''));

    // ── HUD Backend Monitor ──
    document.getElementById('btn-toggle-hud')?.addEventListener('click', () => HUD.toggle());
    document.getElementById('btn-close-hud')?.addEventListener('click', () => HUD.close());
    document.getElementById('btn-collapse-hud')?.addEventListener('click', () => HUD.toggleCollapse());
    document.getElementById('btn-pin-hud')?.addEventListener('click', () => HUD.togglePin());
    document.getElementById('hud-clear-log')?.addEventListener('click', () => HUD.clearLog());

    // Make HUD Draggable
    setupHUDDragging();
    setupHUDResizing();

    // ── Keyboard Shortcuts ──
    document.addEventListener('keydown', (e) => {
        // Ctrl+N: New document
        if (e.ctrlKey && e.key === 'n') {
            e.preventDefault();
            createDocument();
        }
        // Ctrl+S: Save
        if (e.ctrlKey && e.key === 's') {
            e.preventDefault();
            saveDocument();
        }
        // Ctrl+H: Search/Replace
        if (e.ctrlKey && e.key === 'h') {
            e.preventDefault();
            openSearchModal();
        }
        // Ctrl+M: Toggle Markdown mode
        if (e.ctrlKey && e.key === 'm') {
            e.preventDefault();
            if (currentDocId) toggleMarkdownMode();
        }
        // Ctrl+D: Open dashboard
        if (e.ctrlKey && e.key === 'd') {
            e.preventDefault();
            window.open('/dashboard', '_blank');
        }
        // Escape: Close modals/panels
        if (e.key === 'Escape') {
            closeSearchModal();
            closeDeleteModal();
            closeVersionPanel();
            document.getElementById('export-dropdown').classList.remove('active');
            document.getElementById('sidebar').classList.remove('mobile-open');
        }
        // Enter in search modal
        if (e.key === 'Enter' && document.getElementById('search-modal').classList.contains('active')) {
            e.preventDefault();
            executeSearchReplace();
        }
    });
});


// ═══════════════════════════════════════════════════════════════════
//  MARKDOWN TOOLBAR HELPERS
// ═══════════════════════════════════════════════════════════════════

function mdInsert(before, after) {
    const ta = document.getElementById('markdown-input');
    const start = ta.selectionStart;
    const end = ta.selectionEnd;
    const text = ta.value;
    const selected = text.substring(start, end) || 'text';

    ta.value = text.substring(0, start) + before + selected + after + text.substring(end);
    ta.selectionStart = start + before.length;
    ta.selectionEnd = start + before.length + selected.length;
    ta.focus();

    renderMarkdownPreview();
}


// ═══════════════════════════════════════════════════════════════════
//  HUD DRAGGING & RESIZING
// ═══════════════════════════════════════════════════════════════════

function setupHUDDragging() {
    const hudWindow = document.getElementById('hud-window');
    const hudHeader = document.getElementById('hud-header');

    let isDragging = false;
    let dragStartX, dragStartY;
    let initialLeft, initialTop;

    hudHeader.addEventListener('mousedown', (e) => {
        // Don't drag if clicking on buttons
        if (e.target.closest('.hud-ctrl-btn')) return;

        isDragging = true;
        dragStartX = e.clientX;
        dragStartY = e.clientY;
        const rect = hudWindow.getBoundingClientRect();
        initialLeft = rect.left;
        initialTop = rect.top;
        document.body.style.userSelect = 'none';
    });

    document.addEventListener('mousemove', (e) => {
        if (!isDragging) return;
        const dx = e.clientX - dragStartX;
        const dy = e.clientY - dragStartY;
        hudWindow.style.left = `${initialLeft + dx}px`;
        hudWindow.style.top = `${initialTop + dy}px`;
        hudWindow.style.right = 'auto';
    });

    document.addEventListener('mouseup', () => {
        isDragging = false;
        document.body.style.userSelect = '';
    });
}

function setupHUDResizing() {
    const hudWindow = document.getElementById('hud-window');
    const resizeHandle = document.getElementById('hud-resize-handle');

    let isResizing = false;
    let startX, startY, startW, startH;

    resizeHandle.addEventListener('mousedown', (e) => {
        e.preventDefault();
        e.stopPropagation();
        isResizing = true;
        startX = e.clientX;
        startY = e.clientY;
        startW = hudWindow.offsetWidth;
        startH = hudWindow.offsetHeight;
        document.body.style.userSelect = 'none';
    });

    document.addEventListener('mousemove', (e) => {
        if (!isResizing) return;
        const dx = e.clientX - startX;
        const dy = e.clientY - startY;
        const newW = Math.max(340, startW + dx);
        const newH = Math.max(200, startH + dy);
        hudWindow.style.width = `${newW}px`;
        hudWindow.style.height = `${newH}px`;
    });

    document.addEventListener('mouseup', () => {
        isResizing = false;
        document.body.style.userSelect = '';
    });
}


// ═══════════════════════════════════════════════════════════════════
//  AI ASSISTANT SIDEBAR LOGIC
// ═══════════════════════════════════════════════════════════════════

let isAIOpen = false;
let aiConfig = {
    provider: 'google',
    model: 'gemini-3.5-flash',
    key: '',
    endpoint: 'http://localhost:11434/v1'
};
let aiChatHistory = [];

function initAIAssistant() {
    loadAIConfig();
    
    // Bind toggle buttons
    document.getElementById('btn-ai-assistant')?.addEventListener('click', toggleAIPanel);
    document.getElementById('ai-panel-close')?.addEventListener('click', toggleAIPanel);
    document.getElementById('btn-ai-settings')?.addEventListener('click', toggleAISettings);
    document.getElementById('btn-save-ai-settings')?.addEventListener('click', saveAIConfig);
    
    // Bind Send action
    document.getElementById('btn-ai-send')?.addEventListener('click', sendAIChatMessage);
    document.getElementById('ai-chat-input')?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendAIChatMessage();
        }
    });

    // Toggle Ollama URL field based on provider
    document.getElementById('ai-provider')?.addEventListener('change', (e) => {
        const ollamaField = document.getElementById('ollama-url-field');
        const modelInput = document.getElementById('ai-model');
        
        if (e.target.value === 'ollama') {
            if (ollamaField) ollamaField.style.display = 'flex';
            if (modelInput) modelInput.value = 'llama3';
        } else {
            if (ollamaField) ollamaField.style.display = 'none';
            if (e.target.value === 'google' && modelInput) modelInput.value = 'gemini-3.5-flash';
            if (e.target.value === 'openai' && modelInput) modelInput.value = 'gpt-4o-mini';
            if (e.target.value === 'anthropic' && modelInput) modelInput.value = 'claude-3-5-sonnet-20240620';
        }
    });

    // Bind Quick Action buttons
    document.querySelectorAll('.ai-panel .ai-quick-actions button.ai-chip').forEach(btn => {
        btn.addEventListener('click', () => {
            const action = btn.dataset.action;
            if (action) runAIQuickAction(action);
        });
    });
}

function loadAIConfig() {
    const stored = localStorage.getItem('mcp-ai-config');
    if (stored) {
        try {
            aiConfig = { ...aiConfig, ...JSON.parse(stored) };
            // Auto-migrate deprecated 1.5 model to 3.5 model
            if (aiConfig.model === 'gemini-1.5-flash') {
                aiConfig.model = 'gemini-3.5-flash';
                localStorage.setItem('mcp-ai-config', JSON.stringify(aiConfig));
            }
        } catch (e) {
            console.error('Failed to parse stored AI config', e);
        }
    }
    
    // Update inputs
    const providerEl = document.getElementById('ai-provider');
    const modelEl = document.getElementById('ai-model');
    const keyEl = document.getElementById('ai-key');
    const endpointEl = document.getElementById('ai-endpoint');
    
    if (providerEl) providerEl.value = aiConfig.provider;
    if (modelEl) modelEl.value = aiConfig.model;
    if (keyEl) keyEl.value = aiConfig.key;
    if (endpointEl) endpointEl.value = aiConfig.endpoint;

    // Trigger change event to set up visible fields
    if (providerEl) {
        providerEl.dispatchEvent(new Event('change'));
    }
}

function saveAIConfig() {
    const providerEl = document.getElementById('ai-provider');
    const modelEl = document.getElementById('ai-model');
    const keyEl = document.getElementById('ai-key');
    const endpointEl = document.getElementById('ai-endpoint');

    if (providerEl) aiConfig.provider = providerEl.value;
    if (modelEl) aiConfig.model = modelEl.value;
    if (keyEl) aiConfig.key = keyEl.value;
    if (endpointEl) aiConfig.endpoint = endpointEl.value;
    
    localStorage.setItem('mcp-ai-config', JSON.stringify(aiConfig));
    toast('AI Configuration Saved', 'success');
    
    // Auto collapse settings container after saving
    const settingsContainer = document.getElementById('ai-settings-container');
    if (settingsContainer) settingsContainer.style.display = 'none';
}

function toggleAIPanel() {
    const panel = document.getElementById('ai-panel');
    const btn = document.getElementById('btn-ai-assistant');
    if (!panel) return;
    
    isAIOpen = !isAIOpen;
    if (isAIOpen) {
        panel.style.display = 'flex';
        btn?.classList.add('active');
        // Scroll chat to bottom
        const chatBody = document.getElementById('ai-chat-body');
        if (chatBody) chatBody.scrollTop = chatBody.scrollHeight;
    } else {
        panel.style.display = 'none';
        btn?.classList.remove('active');
    }
}

function toggleAISettings() {
    const container = document.getElementById('ai-settings-container');
    if (!container) return;
    container.style.display = container.style.display === 'none' ? 'flex' : 'none';
}

function appendAIBubble(role, content) {
    const chatBody = document.getElementById('ai-chat-body');
    if (!chatBody) return null;
    
    const msgEl = document.createElement('div');
    msgEl.className = `ai-message ${role}`;
    
    const metaEl = document.createElement('div');
    metaEl.className = 'ai-bubble-meta';
    metaEl.textContent = role === 'user' ? 'You' : 'Assistant';
    msgEl.appendChild(metaEl);
    
    const contentEl = document.createElement('div');
    contentEl.className = 'ai-bubble-content';
    
    // Parse markdown if marked is loaded
    if (window.marked && role === 'assistant') {
        try {
            contentEl.innerHTML = marked.parse(content);
        } catch (e) {
            contentEl.textContent = content;
        }
    } else {
        contentEl.textContent = content;
    }
    msgEl.appendChild(contentEl);
    
    // If assistant, add quick insert/replace buttons
    if (role === 'assistant' && content.trim()) {
        const actionsEl = document.createElement('div');
        actionsEl.className = 'ai-bubble-actions';
        
        const insertBtn = document.createElement('button');
        insertBtn.className = 'ai-bubble-btn';
        insertBtn.textContent = '📥 Insert at Cursor';
        insertBtn.addEventListener('click', () => {
            // Strip code block backticks if AI wrapped it
            let cleanContent = content;
            if (content.startsWith('```') && content.endsWith('```')) {
                cleanContent = content.substring(content.indexOf('\n') + 1, content.length - 3);
            }
            insertTextAtCursor(cleanContent);
            toast('Inserted into document', 'success');
        });
        actionsEl.appendChild(insertBtn);

        const replaceBtn = document.createElement('button');
        replaceBtn.className = 'ai-bubble-btn';
        replaceBtn.textContent = '🔄 Replace Content';
        replaceBtn.addEventListener('click', () => {
            let cleanContent = content;
            if (content.startsWith('```') && content.endsWith('```')) {
                cleanContent = content.substring(content.indexOf('\n') + 1, content.length - 3);
            }
            replaceDocumentWithText(cleanContent);
            toast('Replaced document content', 'info');
        });
        actionsEl.appendChild(replaceBtn);

        msgEl.appendChild(actionsEl);
    }
    
    chatBody.appendChild(msgEl);
    chatBody.scrollTop = chatBody.scrollHeight;
    
    return msgEl;
}

function showAILoading() {
    const chatBody = document.getElementById('ai-chat-body');
    if (!chatBody) return null;
    
    const loader = document.createElement('div');
    loader.className = 'ai-typing-indicator';
    loader.id = 'ai-chat-loader';
    loader.innerHTML = '<span></span><span></span><span></span>';
    chatBody.appendChild(loader);
    chatBody.scrollTop = chatBody.scrollHeight;
    return loader;
}

function hideAILoading() {
    const loader = document.getElementById('ai-chat-loader');
    if (loader) loader.remove();
}

async function sendAIChatMessage() {
    const inputEl = document.getElementById('ai-chat-input');
    const query = inputEl.value.trim();
    if (!query) return;
    
    inputEl.value = '';
    appendAIBubble('user', query);
    
    const scope = document.querySelector('input[name="ai-scope"]:checked')?.value || 'document';
    
    showAILoading();
    
    try {
        const res = await fetch('/api/ai/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                provider: aiConfig.provider,
                model: aiConfig.model,
                api_key: aiConfig.key,
                endpoint: aiConfig.endpoint,
                message: query,
                chat_history: aiChatHistory,
                active_doc_id: currentDocId,
                scope: scope
            })
        });
        
        hideAILoading();
        
        if (!res.ok) {
            const err = await res.json();
            appendAIBubble('assistant', `❌ Error: ${err.error || 'Server error'}`);
            return;
        }
        
        const data = await res.json();
        const reply = data.response || '';
        appendAIBubble('assistant', reply);
        
        // Update history
        aiChatHistory.push({ role: 'user', content: query });
        aiChatHistory.push({ role: 'assistant', content: reply });
        
        // Keep history to last 10 exchanges
        if (aiChatHistory.length > 20) {
            aiChatHistory = aiChatHistory.slice(-20);
        }
        
    } catch (e) {
        hideAILoading();
        console.error('AI chat failed:', e);
        appendAIBubble('assistant', `❌ Connection failed: ${e.message}`);
    }
}

async function runAIQuickAction(action) {
    if (!currentDocId) {
        toast('No active document to process', 'warning');
        return;
    }
    
    // Toggle AI panel open to show output
    if (!isAIOpen) toggleAIPanel();
    
    // Get text to process: selection first, then full doc
    let textToProcess = '';
    const range = quill ? quill.getSelection() : null;
    if (quill && !isMarkdownMode && range && range.length > 0) {
        textToProcess = quill.getText(range.index, range.length);
    } else if (!quill && !isMarkdownMode) {
        const fallbackEditor = document.getElementById('quill-fallback-editor');
        if (fallbackEditor) {
            const start = fallbackEditor.selectionStart;
            const end = fallbackEditor.selectionEnd;
            if (start !== end) {
                textToProcess = fallbackEditor.value.substring(start, end);
            }
        }
    } else if (isMarkdownMode) {
        const ta = document.getElementById('markdown-input');
        const start = ta.selectionStart;
        const end = ta.selectionEnd;
        if (start !== end) {
            textToProcess = ta.value.substring(start, end);
        }
    }
    
    // Fallback to full document if no selection
    if (!textToProcess) {
        if (isMarkdownMode) {
            textToProcess = document.getElementById('markdown-input').value;
        } else {
            if (quill) {
                textToProcess = quill.getText();
            } else {
                const fallbackEditor = document.getElementById('quill-fallback-editor');
                textToProcess = fallbackEditor ? fallbackEditor.value : '';
            }
        }
    }
    
    if (!textToProcess.trim()) {
        toast('Document is empty', 'warning');
        return;
    }

    const targetLang = document.getElementById('ai-target-lang').value;
    
    appendAIBubble('user', `Run Action: "${action}" on document text`);
    showAILoading();
    
    try {
        const res = await fetch('/api/ai/action', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                provider: aiConfig.provider,
                model: aiConfig.model,
                api_key: aiConfig.key,
                endpoint: aiConfig.endpoint,
                action: action,
                text: textToProcess,
                target_lang: action === 'translate' ? targetLang : null
            })
        });
        
        hideAILoading();
        
        if (!res.ok) {
            const err = await res.json();
            appendAIBubble('assistant', `❌ Action failed: ${err.error || 'Server error'}`);
            return;
        }
        
        const data = await res.json();
        appendAIBubble('assistant', data.response);
        
    } catch (e) {
        hideAILoading();
        console.error('AI Action failed:', e);
        appendAIBubble('assistant', `❌ Connection failed: ${e.message}`);
    }
}

function insertTextAtCursor(text) {
    if (isMarkdownMode) {
        const ta = document.getElementById('markdown-input');
        const start = ta.selectionStart;
        const end = ta.selectionEnd;
        const val = ta.value;
        ta.value = val.substring(0, start) + text + val.substring(end);
        ta.selectionStart = start + text.length;
        ta.selectionEnd = start + text.length;
        ta.focus();
        renderMarkdownPreview();
        saveDocument();
    } else {
        if (quill) {
            const range = quill.getSelection();
            if (range) {
                quill.insertText(range.index, text);
                quill.setSelection(range.index + text.length);
            } else {
                const length = quill.getLength();
                quill.insertText(length - 1, "\n" + text);
            }
        } else {
            const textarea = document.getElementById('quill-fallback-editor');
            if (textarea) {
                const start = textarea.selectionStart;
                const end = textarea.selectionEnd;
                const val = textarea.value;
                textarea.value = val.substring(0, start) + text + val.substring(end);
                textarea.selectionStart = start + text.length;
                textarea.selectionEnd = start + text.length;
                textarea.focus();
            }
        }
        saveDocument();
    }
}

function replaceDocumentWithText(text) {
    if (isMarkdownMode) {
        document.getElementById('markdown-input').value = text;
        renderMarkdownPreview();
    } else {
        if (quill) {
            let html = text;
            try {
                if (window.marked) {
                    html = marked.parse(text);
                }
            } catch (e) {}
            quill.root.innerHTML = html;
        } else {
            const textarea = document.getElementById('quill-fallback-editor');
            if (textarea) textarea.value = text;
        }
    }
    saveDocument();
}


// ═══════════════════════════════════════════════════════════════════
//  GRAPH VIEW (BRAIN MAPPING) LOGIC
// ═══════════════════════════════════════════════════════════════════

let graphInstance = null;
let rawGraphData = null;
let graphSearchQuery = '';

function initGraphView() {
    // Bind open and close actions
    document.getElementById('btn-graph-view')?.addEventListener('click', openGraphModal);
    document.getElementById('graph-modal-close')?.addEventListener('click', closeGraphModal);
    document.getElementById('graph-modal-overlay')?.addEventListener('click', (e) => {
        if (e.target === document.getElementById('graph-modal-overlay')) closeGraphModal();
    });

    // Bind search/filter action
    document.getElementById('graph-search')?.addEventListener('input', (e) => {
        graphSearchQuery = e.target.value;
        if (graphInstance) {
            // Re-render to apply search dimming
            graphInstance.nodeCanvasObject(graphInstance.nodeCanvasObject());
        }
    });

    // Close on Escape key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeGraphModal();
    });
}

async function openGraphModal() {
    const overlay = document.getElementById('graph-modal-overlay');
    if (overlay) {
        overlay.classList.add('active');
        await refreshGraphData();
    }
}

function closeGraphModal() {
    const overlay = document.getElementById('graph-modal-overlay');
    if (overlay) {
        overlay.classList.remove('active');
    }
}

async function refreshGraphData() {
    try {
        const res = await fetch('/api/documents/graph');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        rawGraphData = await res.json();
        renderGraph();
    } catch (e) {
        console.error('Failed to load graph data:', e);
        toast('Failed to load graph view', 'error');
    }
}

function renderGraph() {
    const container = document.getElementById('graph-canvas-container');
    if (!container || !rawGraphData) return;

    const width = container.offsetWidth;
    const height = container.offsetHeight;

    if (!graphInstance) {
        // Initialize ForceGraph
        graphInstance = ForceGraph()(container)
            .width(width)
            .height(height)
            .backgroundColor('transparent')
            .nodeRelSize(6)
            .linkWidth(1.5)
            .linkColor(() => 'rgba(100, 100, 255, 0.15)')
            .linkDirectionalParticles(2)
            .linkDirectionalParticleWidth(2.5)
            .linkDirectionalParticleSpeed(0.006)
            .linkDirectionalParticleColor(() => 'rgba(168, 85, 247, 0.4)')
            .nodeCanvasObject((node, ctx, globalScale) => {
                const label = node.title;
                const fontSize = 11 / globalScale;
                ctx.font = `${fontSize}px Sans-Serif`;
                
                let color = '#6366f1'; // Indigo
                let shadowColor = 'rgba(99, 102, 241, 0.5)';
                let radius = 6;
                const isGhost = !node.exists;

                if (node.id === currentDocId) {
                    color = '#a855f7'; // Purple active
                    shadowColor = 'rgba(168, 85, 247, 0.9)';
                    radius = 8;
                } else if (node.pinned) {
                    color = '#f59e0b'; // Gold pinned
                    shadowColor = 'rgba(245, 158, 11, 0.8)';
                    radius = 7;
                } else if (node.is_draft) {
                    color = '#06b6d4'; // Cyan draft
                    shadowColor = 'rgba(6, 182, 212, 0.6)';
                } else if (isGhost) {
                    color = '#64748b'; // Slate grey ghost
                    shadowColor = 'transparent';
                }

                // Handle search dimming
                if (graphSearchQuery && !label.toLowerCase().includes(graphSearchQuery.toLowerCase())) {
                    ctx.globalAlpha = 0.15;
                } else {
                    ctx.globalAlpha = 1.0;
                }

                // Draw glow
                if (shadowColor !== 'transparent') {
                    ctx.shadowColor = shadowColor;
                    ctx.shadowBlur = 8;
                }

                // Draw circle
                ctx.beginPath();
                if (isGhost) {
                    ctx.setLineDash([2, 2]);
                    ctx.strokeStyle = color;
                    ctx.lineWidth = 1;
                    ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI, false);
                    ctx.stroke();
                    ctx.setLineDash([]); // reset
                } else {
                    ctx.fillStyle = color;
                    ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI, false);
                    ctx.fill();
                }

                // Reset shadow
                ctx.shadowBlur = 0;

                // Draw label
                if (globalScale > 0.8 || node.id === currentDocId) {
                    ctx.textAlign = 'center';
                    ctx.textBaseline = 'top';
                    ctx.fillStyle = isGhost ? '#64748b' : '#e2e8f0';
                    ctx.fillText(label, node.x, node.y + radius + 4);
                }
            })
            .onNodeClick(async (node) => {
                if (node.exists) {
                    closeGraphModal();
                    openDocument(node.id);
                } else {
                    // Clicked a ghost node
                    if (confirm(`Do you want to create the new document "${node.title}"?`)) {
                        closeGraphModal();
                        await createDocumentFromGhost(node.title);
                    }
                }
            })
            .nodePointerAreaPaint((node, color, ctx) => {
                // Expand click target area
                ctx.fillStyle = color;
                ctx.beginPath();
                ctx.arc(node.x, node.y, 10, 0, 2 * Math.PI, false);
                ctx.fill();
            });

        // Set custom tooltip
        const tooltip = document.createElement('div');
        tooltip.className = 'graph-tooltip';
        tooltip.style.display = 'none';
        document.body.appendChild(tooltip);

        container.addEventListener('mousemove', (e) => {
            if (tooltip.style.display === 'block') {
                tooltip.style.left = `${e.pageX}px`;
                tooltip.style.top = `${e.pageY}px`;
            }
        });

        graphInstance
            .onNodeHover((node) => {
                if (node) {
                    tooltip.style.display = 'block';
                    let typeStr = 'Document';
                    if (node.id === currentDocId) typeStr = 'Active Document';
                    else if (node.pinned) typeStr = 'Pinned Document';
                    else if (node.is_draft) typeStr = 'Draft';
                    else if (!node.exists) typeStr = 'Ghost Note (Uncreated)';

                    tooltip.innerHTML = `
                        <div class="graph-tooltip-title">${escapeHtml(node.title)}</div>
                        <div class="graph-tooltip-meta">${typeStr}</div>
                    `;
                } else {
                    tooltip.style.display = 'none';
                }
            });
            
        // Resize listener
        window.addEventListener('resize', () => {
            if (graphInstance) {
                graphInstance.width(container.offsetWidth).height(container.offsetHeight);
            }
        });
    }

    graphInstance.graphData(rawGraphData);
}

async function createDocumentFromGhost(title) {
    try {
        const body = new URLSearchParams({ title });
        const res = await fetch('/api/documents/create-by-title', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: body.toString(),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        toast(`Document "${title}" created`, 'success');
        await refreshDocList();
        await openDocument(data.id);
    } catch (e) {
        console.error('Failed to create document from ghost node:', e);
        toast('Failed to create document', 'error');
    }
}

function updateLocalGraph() {
    // Check if graph modal is active and graphInstance initialized
    if (!graphInstance || !rawGraphData || !currentDocId) return;

    let content = '';
    if (isMarkdownMode) {
        content = document.getElementById('markdown-input').value;
    } else {
        content = quill.root.innerHTML;
    }

    // Parse links locally
    const wikiPattern = /\[\[([^\]\|]+)(?:\|[^\]]+)?\]\]/g;
    const matches = [];
    let match;
    while ((match = wikiPattern.exec(content)) !== null) {
        const t = match[1].trim();
        if (t) matches.push(t.toLowerCase());
    }

    // Map existing nodes by lower title and ID
    const titleToId = {};
    const idToNode = {};
    rawGraphData.nodes.forEach(n => {
        titleToId[n.title.toLowerCase().trim()] = n.id;
        idToNode[n.id] = n;
    });

    const activeNode = idToNode[currentDocId];
    if (!activeNode) return;

    // Filter out existing links from active node in rawGraphData
    rawGraphData.links = rawGraphData.links.filter(l => {
        const srcId = typeof l.source === 'object' ? l.source.id : l.source;
        return srcId !== currentDocId;
    });

    const seenTargets = new Set();

    // Add new links parsed locally
    matches.forEach(targetStr => {
        if (seenTargets.has(targetStr)) return;
        seenTargets.add(targetStr);

        let targetId = null;
        if (idToNode[targetStr]) {
            targetId = targetStr;
        } else if (titleToId[targetStr]) {
            targetId = titleToId[targetStr];
        } else {
            // New ghost node
            const ghostId = `ghost:${targetStr}`;
            targetId = ghostId;
            if (!idToNode[ghostId]) {
                const newGhost = {
                    id: ghostId,
                    title: targetStr,
                    pinned: false,
                    is_draft: false,
                    exists: false
                };
                rawGraphData.nodes.push(newGhost);
                idToNode[ghostId] = newGhost;
            }
        }

        if (targetId !== currentDocId) {
            rawGraphData.links.push({
                source: currentDocId,
                target: targetId
            });
        }
    });

    // Refresh graph data in-place (keeps simulation running smoothly)
    graphInstance.graphData(rawGraphData);
}
