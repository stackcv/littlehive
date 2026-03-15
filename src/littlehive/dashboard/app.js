/* ============================================================
   LittleHive Dashboard — Client-side logic
   ============================================================ */

let typingIndicator = null;
let cachedAgentName = "Assistant";
let cachedUserName = "User";
let typingInterval = null;
let isDarkMode = true;
let chatCursor = 0;

const thinkingMessages = [
    "is analyzing your request...",
    "is organizing the thought process...",
    "is searching through local memory...",
    "is double-checking the calendar...",
    "is sifting through recent emails...",
    "is drafting a thoughtful response...",
    "is prioritizing your pending tasks...",
    "is consulting the local model weights...",
    "is making sure everything is perfect..."
];

const toolFriendlyNames = {
    search_emails:        "Checking your emails",
    read_full_email:      "Reading an email",
    send_email:           "Sending an email",
    reply_to_email:       "Drafting a reply",
    manage_email:         "Managing your inbox",
    get_events:           "Browsing your calendar",
    create_event:         "Creating a calendar event",
    delete_event:         "Removing a calendar event",
    set_reminder:         "Setting a reminder",
    get_pending_reminders:"Checking reminders",
    mark_reminder_completed: "Clearing a reminder",
    search_past_conversations: "Recalling from memory",
    save_core_fact:       "Saving to memory",
    delete_core_fact:     "Updating memory",
    lookup_stakeholder:   "Looking up contacts",
    add_stakeholder:      "Adding a contact",
    update_stakeholder:   "Updating a contact",
    send_channel_message: "Sending a message",
    add_bill:             "Recording a bill",
    list_bills:           "Checking bills",
    mark_bill_paid:       "Marking a bill paid",
    get_tasks:            "Checking your tasks",
    create_task:          "Creating a task",
    update_task:          "Updating a task",
    web_search:           "Searching the web",
    fetch_webpage:        "Reading a webpage",
    call_api:             "Calling a custom API",
    register_api:         "Registering a new API",
    list_apis:            "Checking available APIs",
    github_create_issue:  "Creating a GitHub issue",
    github_list_issues:   "Checking GitHub issues",
    github_update_issue:  "Updating a GitHub issue",
    github_add_comment:   "Commenting on GitHub",
    exec_command:         "Running a shell command",
    read_file:            "Reading a file",
    write_file:           "Writing a file",
    list_directory:       "Listing directory contents",
    announce:             "Speaking aloud"
};

/* ---------- Connection status ---------- */
async function checkConnectionStatus() {
    try {
        const res = await fetch("/api/health", { cache: "no-store", signal: AbortSignal.timeout(3000) });
        const data = await res.json();
        const dot = document.getElementById("agent-status-dot");
        const text = document.getElementById("agent-status-text");
        if (data.status === "ok") {
            dot.className = "status-dot online";
            text.innerText = "Connected";
            const verEl = document.getElementById("sidebar-version");
            if (verEl && data.version) verEl.textContent = `v${data.version}`;
        } else {
            dot.className = "status-dot offline";
            text.innerText = "Error";
        }
    } catch (e) {
        const dot = document.getElementById("agent-status-dot");
        const text = document.getElementById("agent-status-text");
        dot.className = "status-dot offline";
        text.innerText = "Disconnected";
    }
    setTimeout(checkConnectionStatus, 5000);
}

/* ---------- Dashboard ---------- */
async function loadDashboard() {
    document.getElementById('page-title').innerText = "Dashboard";
    try {
        const res = await fetch('/api/dashboard', { cache: 'no-store' });
        const data = await res.json();

        document.getElementById('emails-count').innerText = data.emails ? data.emails.length : 0;
        document.getElementById('events-count').innerText = data.today_event_count !== undefined ? data.today_event_count : (data.events ? data.events.length : 0);
        document.getElementById('reminders-count').innerText = data.reminders ? data.reminders.length : 0;
        document.getElementById('tasks-count').innerText = data.pending_tasks ? data.pending_tasks.length : 0;
        document.getElementById('bills-count').innerText = data.bills ? data.bills.length : 0;
    } catch (e) {
        console.error('Error loading dashboard', e);
    }
}

/* ---------- Memories ---------- */
async function loadMemories() {
    document.getElementById('page-title').innerText = "Core Memory";
    try {
        const res = await fetch('/api/memories', { cache: 'no-store' });
        const data = await res.json();
        const table = document.getElementById('memories-table');
        table.innerHTML = '';

        if (!data.memories || data.memories.length === 0) {
            table.innerHTML = '<tr><td colspan="3" class="text-muted text-center py-4">No memories found.</td></tr>';
        } else {
            data.memories.forEach(m => {
                table.innerHTML += `<tr>
                    <td>${m.fact_text}</td>
                    <td><small class="text-muted">${m.timestamp || ''}</small></td>
                    <td class="text-center">
                        <button class="btn btn-sm btn-outline-secondary me-1" onclick="editMemory(${m.id}, '${encodeURIComponent(m.fact_text).replace(/'/g, "%27")}')">
                            <i class="bi bi-pencil"></i>
                        </button>
                        <button class="btn btn-sm btn-outline-danger" onclick="deleteMemory(${m.id})">
                            <i class="bi bi-trash"></i>
                        </button>
                    </td>
                </tr>`;
            });
        }
    } catch (e) {
        console.error('Error loading memories', e);
    }
}

async function editMemory(id, encodedText) {
    const text = decodeURIComponent(encodedText);
    const newText = prompt("Edit Memory:", text);
    if (newText !== null && newText.trim() !== "" && newText !== text) {
        try {
            const res = await fetch(`/api/memories/${id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ fact_text: newText })
            });
            if (res.ok) loadMemories();
            else alert('Failed to update memory');
        } catch (e) { console.error(e); }
    }
}

async function deleteMemory(id) {
    if (!confirm("Are you sure you want to delete this memory?")) return;
    try {
        const res = await fetch(`/api/memories/${id}`, { method: 'DELETE' });
        if (res.ok) loadMemories();
        else alert('Failed to delete memory');
    } catch (e) { console.error(e); }
}

/* ---------- Config ---------- */
async function loadConfig() {
    document.getElementById('page-title').innerText = "System Configuration";
    try {
        const res = await fetch('/api/config', { cache: 'no-store' });
        const config = await res.json();
        const container = document.getElementById('config-fields');

        const shellEnabled = config.shell_enabled || false;
        const shellWorkspace = config.shell_workspace || '~/littlehive-workspace';
        const shellTimeout = config.shell_max_timeout || 60;
        const ttsEngine = config.tts_engine || 'say';
        const shellAllowed = (config.shell_allowed_commands || []).join(', ');
        const shellLogged = (config.shell_logged_commands || []).join(', ');
        const shellBlocked = (config.shell_blocked_commands || []).join(', ');

        container.innerHTML = `
            <div class="row">
                <div class="col-md-6 mb-4">
                    <div class="config-section-title"><i class="bi bi-person-badge me-2"></i>General Identity</div>
                    <div class="mb-3">
                        <label class="form-label">Agent Name</label>
                        <input type="text" class="form-control" name="agent_name" value="${config.agent_name || ''}">
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Agent Title</label>
                        <input type="text" class="form-control" name="agent_title" value="${config.agent_title || ''}">
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Your Name</label>
                        <input type="text" class="form-control" name="user_name" value="${config.user_name || ''}">
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Home Location</label>
                        <input type="text" class="form-control" name="home_location" value="${config.home_location || ''}">
                    </div>

                    <div class="config-section-title mt-4"><i class="bi bi-moon-stars me-2"></i>Do Not Disturb</div>
                    <div class="row">
                        <div class="col-6 mb-3">
                            <label class="form-label">Start (24h)</label>
                            <input type="number" class="form-control" name="dnd_start" value="${config.dnd_start !== undefined ? config.dnd_start : 23}">
                        </div>
                        <div class="col-6 mb-3">
                            <label class="form-label">End (24h)</label>
                            <input type="number" class="form-control" name="dnd_end" value="${config.dnd_end !== undefined ? config.dnd_end : 7}">
                        </div>
                    </div>
                </div>
                <div class="col-md-6 mb-4">
                    <div class="config-section-title"><i class="bi bi-cpu me-2"></i>AI Engine</div>
                    <div class="mb-3">
                        <label class="form-label">Model <small class="attention-text ms-1">Requires restart</small></label>
                        <select class="form-select" name="model_path">
                            <option value="mlx-community/Ministral-3-3B-Instruct-2512-4bit" ${config.model_path === 'mlx-community/Ministral-3-3B-Instruct-2512-4bit' ? 'selected' : ''}>Ministral 3B Lite (4-bit)</option>
                            <option value="mlx-community/Ministral-3-8B-Instruct-2512-4bit" ${config.model_path === 'mlx-community/Ministral-3-8B-Instruct-2512-4bit' ? 'selected' : ''}>Ministral 8B (4-bit)</option>
                            <option value="mlx-community/mistralai_Ministral-3-14B-Instruct-2512-MLX-MXFP4" ${config.model_path === 'mlx-community/mistralai_Ministral-3-14B-Instruct-2512-MLX-MXFP4' ? 'selected' : ''}>Ministral 14B (MXFP4)</option>
                        </select>
                    </div>

                    <div class="config-section-title mt-4"><i class="bi bi-list-check me-2"></i>Task Management</div>
                    <div class="mb-3">
                        <label class="form-label">TODO Provider <small class="attention-text ms-1">Requires restart</small></label>
                        <select class="form-select" name="todo_provider">
                            <option value="internal" ${(config.todo_provider || 'internal') === 'internal' ? 'selected' : ''}>Internal TODO List</option>
                            <option value="google_tasks" ${config.todo_provider === 'google_tasks' ? 'selected' : ''}>Google Tasks</option>
                        </select>
                        <small class="text-muted">Internal stores tasks locally. Google Tasks syncs with your Google account.</small>
                    </div>

                    <div class="config-section-title mt-4"><i class="bi bi-send me-2"></i>Channels</div>
                    <div class="mb-3">
                        <label class="form-label">Telegram Bot Token</label>
                        <input type="password" class="form-control" name="telegram_bot_token" value="${config.telegram_bot_token || ''}">
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Telegram Chat ID</label>
                        <input type="text" class="form-control" name="telegram_chat_id" value="${config.telegram_chat_id || ''}">
                    </div>

                    <div class="config-section-title mt-4"><i class="bi bi-github me-2"></i>GitHub <small class="attention-text ms-1">Requires restart</small></div>
                    <div class="mb-3">
                        <label class="form-label">Personal Access Token</label>
                        <input type="password" class="form-control" name="github_token" value="${config.github_token || ''}" placeholder="ghp_...">
                        <small class="text-muted">Needs <code>repo</code> scope. <a href="https://github.com/settings/tokens/new?scopes=repo" target="_blank">Create one</a></small>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Default Repository</label>
                        <input type="text" class="form-control" name="github_default_repo" value="${config.github_default_repo || ''}" placeholder="owner/repo">
                    </div>
                </div>
            </div>

            <hr style="border-color:var(--border)">

            <div class="row">
                <div class="col-12 mb-2">
                    <div class="config-section-title"><i class="bi bi-terminal me-2"></i>Shell & File Tools <small class="attention-text ms-1">Requires restart</small></div>
                </div>
                <div class="col-md-6 mb-4">
                    <div class="mb-3">
                        <div class="form-check form-switch">
                            <input class="form-check-input" type="checkbox" id="shell-enabled-toggle" ${shellEnabled ? 'checked' : ''}>
                            <label class="form-check-label fw-semibold" for="shell-enabled-toggle">Enable Shell Tools</label>
                        </div>
                        <small class="text-muted">Allows the agent to run commands, read/write files, and use TTS</small>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Workspace Folder</label>
                        <input type="text" class="form-control" id="shell-workspace-input" value="${shellWorkspace}">
                        <small class="text-muted">Agent can only operate within this directory</small>
                    </div>
                    <div class="row">
                        <div class="col-6 mb-3">
                            <label class="form-label">Command Timeout</label>
                            <div class="input-group">
                                <input type="number" class="form-control" id="shell-timeout-input" value="${shellTimeout}" min="5" max="300">
                                <span class="input-group-text">sec</span>
                            </div>
                        </div>
                        <div class="col-6 mb-3">
                            <label class="form-label">TTS Engine</label>
                            <select class="form-select" id="shell-tts-input">
                                <option value="say" ${ttsEngine === 'say' ? 'selected' : ''}>say (macOS)</option>
                            </select>
                        </div>
                    </div>
                </div>
                <div class="col-md-6 mb-4">
                    <div class="mb-3">
                        <label class="form-label">Allowed Commands <small class="text-muted">(auto-execute, no logging)</small></label>
                        <textarea class="form-control" id="shell-allowed-input" rows="2" style="font-size:.85rem">${shellAllowed}</textarea>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Logged Commands <small class="text-muted">(execute + audit trail)</small></label>
                        <textarea class="form-control" id="shell-logged-input" rows="2" style="font-size:.85rem">${shellLogged}</textarea>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Blocked Commands <small class="text-muted">(always denied)</small></label>
                        <textarea class="form-control" id="shell-blocked-input" rows="2" style="font-size:.85rem">${shellBlocked}</textarea>
                    </div>
                </div>
            </div>
        `;

        var tooltipTriggerList = [].slice.call(document.querySelectorAll('[title]'));
        tooltipTriggerList.map(el => new bootstrap.Tooltip(el));

    } catch(e) { console.error(e); }
}

function _parseCommaSeparated(text) {
    return text.split(',').map(s => s.trim()).filter(Boolean);
}

async function saveConfig(e) {
    e.preventDefault();
    const formData = new FormData(e.target);
    const configData = {};
    formData.forEach((value, key) => {
        if (!isNaN(value) && value.trim() !== '') configData[key] = Number(value);
        else configData[key] = value;
    });

    const shellToggle = document.getElementById('shell-enabled-toggle');
    if (shellToggle) configData.shell_enabled = shellToggle.checked;

    const shellWs = document.getElementById('shell-workspace-input');
    if (shellWs) configData.shell_workspace = shellWs.value.trim();

    const shellTimeout = document.getElementById('shell-timeout-input');
    if (shellTimeout) configData.shell_max_timeout = parseInt(shellTimeout.value, 10) || 60;

    const ttsInput = document.getElementById('shell-tts-input');
    if (ttsInput) configData.tts_engine = ttsInput.value;

    const allowedInput = document.getElementById('shell-allowed-input');
    if (allowedInput) configData.shell_allowed_commands = _parseCommaSeparated(allowedInput.value);

    const loggedInput = document.getElementById('shell-logged-input');
    if (loggedInput) configData.shell_logged_commands = _parseCommaSeparated(loggedInput.value);

    const blockedInput = document.getElementById('shell-blocked-input');
    if (blockedInput) configData.shell_blocked_commands = _parseCommaSeparated(blockedInput.value);

    try {
        const res = await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(configData)
        });
        if (res.ok) {
            const status = document.getElementById('save-status');
            status.style.display = 'inline-flex';
            setTimeout(() => { status.style.display = 'none'; }, 2500);
            initConfig();
        }
    } catch (e) { console.error('Error saving config', e); }
}

/* ---------- Contacts ---------- */
async function loadContacts() {
    document.getElementById('page-title').innerText = "Contacts Directory";
    try {
        const res = await fetch('/api/contacts', { cache: 'no-store' });
        const contacts = await res.json();
        const tbody = document.getElementById('contacts-table-body');
        tbody.innerHTML = '';

        if (contacts.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted py-4">No contacts yet. Add one to get started.</td></tr>';
            return;
        }

        contacts.forEach(contact => {
            const encodedContact = encodeURIComponent(JSON.stringify(contact)).replace(/'/g, '%27');
            const autoOn = contact.auto_respond === 1 || contact.auto_respond === true;
            tbody.innerHTML += `
                <tr>
                    <td>
                        <span class="fw-semibold">${contact.name || '-'}</span>
                        ${contact.alias ? `<br><small class="text-muted">${contact.alias}</small>` : ''}
                    </td>
                    <td>
                        <div><i class="bi bi-envelope me-1 text-muted"></i>${contact.email || '-'}</div>
                        ${contact.phone ? `<div><i class="bi bi-telephone me-1 text-muted"></i>${contact.phone}</div>` : ''}
                        ${contact.telegram ? `<div><i class="bi bi-telegram me-1 text-muted"></i>${contact.telegram}</div>` : ''}
                    </td>
                    <td>
                        <span class="fw-semibold">${contact.relationship || 'Contact'}</span>
                        ${contact.preferences ? `<br><small class="text-muted">${contact.preferences}</small>` : ''}
                    </td>
                    <td class="text-center">
                        <div class="form-check form-switch d-inline-block">
                            <input class="form-check-input" type="checkbox" ${autoOn ? 'checked' : ''} onchange="toggleAutoReply(${contact.id}, this.checked)" ${!contact.email ? 'disabled title="Email required"' : ''}>
                        </div>
                    </td>
                    <td class="text-center">
                        <button class="btn btn-sm btn-outline-secondary me-1" onclick="openContactModal('${encodedContact}')">
                            <i class="bi bi-pencil"></i>
                        </button>
                        <button class="btn btn-sm btn-outline-danger" onclick="deleteContact(${contact.id})">
                            <i class="bi bi-trash"></i>
                        </button>
                    </td>
                </tr>
            `;
        });
    } catch(e) { console.error(e); }
}

function openContactModal(encodedContact = null) {
    document.getElementById('contact-form').reset();
    document.getElementById('contact-id').value = '';
    document.getElementById('contact-auto-respond').checked = false;

    if (encodedContact) {
        document.getElementById('contactModalTitle').innerText = 'Edit Contact';
        const contact = JSON.parse(decodeURIComponent(encodedContact));
        document.getElementById('contact-id').value = contact.id;
        document.getElementById('contact-name').value = contact.name || '';
        document.getElementById('contact-alias').value = contact.alias || '';
        document.getElementById('contact-email').value = contact.email || '';
        document.getElementById('contact-phone').value = contact.phone || '';
        document.getElementById('contact-telegram').value = contact.telegram || '';
        document.getElementById('contact-relationship').value = contact.relationship || '';
        document.getElementById('contact-preferences').value = contact.preferences || '';
        document.getElementById('contact-auto-respond').checked = contact.auto_respond === 1 || contact.auto_respond === true;
    } else {
        document.getElementById('contactModalTitle').innerText = 'Add Contact';
    }

    const modal = new bootstrap.Modal(document.getElementById('contactModal'));
    modal.show();
}

async function toggleAutoReply(contactId, enabled) {
    try {
        await fetch(`/api/contacts/${contactId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ auto_respond: enabled })
        });
    } catch (e) {
        console.error('Failed to toggle auto-reply', e);
        loadContacts();
    }
}

async function saveContact() {
    const id = document.getElementById('contact-id').value;
    const data = {
        name: document.getElementById('contact-name').value,
        alias: document.getElementById('contact-alias').value,
        email: document.getElementById('contact-email').value,
        phone: document.getElementById('contact-phone').value,
        telegram: document.getElementById('contact-telegram').value,
        relationship: document.getElementById('contact-relationship').value,
        preferences: document.getElementById('contact-preferences').value,
        auto_respond: document.getElementById('contact-auto-respond').checked
    };

    if (!data.name) { alert('Name is required'); return; }

    const method = id ? 'PUT' : 'POST';
    const url = id ? `/api/contacts/${id}` : '/api/contacts';

    try {
        const res = await fetch(url, {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        if (res.ok) {
            bootstrap.Modal.getInstance(document.getElementById('contactModal')).hide();
            loadContacts();
        } else {
            alert('Failed to save contact');
        }
    } catch (e) {
        console.error(e);
        alert('Error saving contact');
    }
}

async function deleteContact(id) {
    if (!confirm('Are you sure you want to delete this contact?')) return;
    try {
        const res = await fetch(`/api/contacts/${id}`, { method: 'DELETE' });
        if (res.ok) loadContacts();
        else alert('Failed to delete contact');
    } catch (e) { console.error(e); alert('Error deleting contact'); }
}

/* ---------- Contact Import ---------- */
let _pendingCsvText = null;

function openImportModal() {
    _pendingCsvText = null;
    document.getElementById('import-csv-file').value = '';
    document.getElementById('import-preview').style.display = 'none';
    document.getElementById('import-result').style.display = 'none';
    document.getElementById('import-submit-btn').disabled = true;
    const modal = new bootstrap.Modal(document.getElementById('importModal'));
    modal.show();

    document.getElementById('import-csv-file').addEventListener('change', handleCsvFile);
}

function handleCsvFile(e) {
    const file = e.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (evt) => {
        _pendingCsvText = evt.target.result;
        const lines = _pendingCsvText.trim().split('\n');
        if (lines.length < 2) {
            alert('CSV must have a header row and at least one data row.');
            return;
        }

        const headers = lines[0].split(',').map(h => h.trim().replace(/^"|"$/g, ''));
        const previewRows = lines.slice(1, 6);

        let headHtml = '<tr>' + headers.map(h => `<th>${h}</th>`).join('') + '</tr>';
        let bodyHtml = previewRows.map(row => {
            const cols = row.match(/(".*?"|[^",\s]+)(?=\s*,|\s*$)/g) || row.split(',');
            return '<tr>' + cols.map(c => `<td>${(c || '').replace(/^"|"$/g, '')}</td>`).join('') + '</tr>';
        }).join('');

        document.getElementById('import-preview-head').innerHTML = headHtml;
        document.getElementById('import-preview-body').innerHTML = bodyHtml;
        document.getElementById('import-preview-count').textContent = `(${lines.length - 1} rows found)`;
        document.getElementById('import-preview').style.display = 'block';
        document.getElementById('import-submit-btn').disabled = false;
    };
    reader.readAsText(file);
}

async function submitImport() {
    if (!_pendingCsvText) return;
    const btn = document.getElementById('import-submit-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Importing...';

    try {
        const res = await fetch('/api/contacts/import', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ csv: _pendingCsvText })
        });
        const data = await res.json();
        const resultEl = document.getElementById('import-result');

        if (data.error) {
            resultEl.innerHTML = `<div class="alert alert-danger py-2">${data.error}</div>`;
        } else {
            let msg = `<strong>${data.imported}</strong> contacts imported`;
            if (data.skipped > 0) msg += `, <strong>${data.skipped}</strong> skipped (duplicates or missing name)`;
            if (data.errors && data.errors.length > 0) msg += `<br><small class="text-danger">${data.errors.slice(0, 3).join('<br>')}</small>`;
            resultEl.innerHTML = `<div class="alert alert-success py-2">${msg}</div>`;
            loadContacts();
        }
        resultEl.style.display = 'block';
    } catch (e) {
        console.error(e);
        alert('Import failed: ' + e.message);
    }

    btn.innerHTML = '<i class="bi bi-upload me-1"></i>Import';
    btn.disabled = false;
}

/* ---------- Custom APIs ---------- */
async function loadApis() {
    document.getElementById('page-title').innerText = "Custom APIs";
    try {
        const res = await fetch('/api/custom-apis', { cache: 'no-store' });
        const apis = await res.json();
        const tbody = document.getElementById('apis-table-body');
        tbody.innerHTML = '';

        if (!Array.isArray(apis) || apis.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted py-4">No custom APIs registered yet.</td></tr>';
            return;
        }

        apis.forEach(api => {
            const shortUrl = api.url.length > 60 ? api.url.substring(0, 57) + '...' : api.url;
            tbody.innerHTML += `
                <tr>
                    <td><code class="fw-semibold">${api.name}</code></td>
                    <td><span class="badge bg-secondary">${api.method || 'GET'}</span></td>
                    <td><small title="${api.url}">${shortUrl}</small></td>
                    <td><small class="text-muted">${api.description || '-'}</small></td>
                    <td class="text-center">
                        <button class="btn btn-sm btn-outline-danger" onclick="deleteApi('${api.name}')">
                            <i class="bi bi-trash"></i>
                        </button>
                    </td>
                </tr>
            `;
        });
    } catch (e) {
        console.error('Error loading APIs', e);
    }
}

function openApiModal() {
    document.getElementById('api-form').reset();
    document.getElementById('api-edit-name').value = '';
    document.getElementById('apiModalTitle').innerText = 'Register Custom API';
    const modal = new bootstrap.Modal(document.getElementById('apiModal'));
    modal.show();
}

async function saveApi() {
    const name = document.getElementById('api-name').value.trim().toLowerCase().replace(/\s+/g, '_');
    const url = document.getElementById('api-url').value.trim();
    if (!name || !url) { alert('Name and URL are required'); return; }

    let headersObj = null;
    const headersStr = document.getElementById('api-headers').value.trim();
    if (headersStr) {
        try { headersObj = JSON.parse(headersStr); }
        catch (e) { alert('Headers must be valid JSON'); return; }
    }

    const data = {
        name: name,
        url: url,
        method: document.getElementById('api-method').value,
        headers: headersObj,
        body_template: document.getElementById('api-body').value.trim(),
        description: document.getElementById('api-description').value.trim()
    };

    try {
        const res = await fetch('/api/custom-apis', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        if (res.ok) {
            bootstrap.Modal.getInstance(document.getElementById('apiModal')).hide();
            loadApis();
        } else {
            const err = await res.json();
            alert('Failed: ' + (err.error || 'Unknown error'));
        }
    } catch (e) {
        console.error(e);
        alert('Error saving API');
    }
}

async function deleteApi(name) {
    if (!confirm(`Delete custom API "${name}"?`)) return;
    try {
        const res = await fetch(`/api/custom-apis/${name}`, { method: 'DELETE' });
        if (res.ok) loadApis();
        else alert('Failed to delete API');
    } catch (e) { console.error(e); alert('Error deleting API'); }
}

/* ---------- Scheduler ---------- */
async function loadScheduler() {
    document.getElementById('page-title').innerText = "System";
    try {
        const res = await fetch('/api/config', { cache: 'no-store' });
        const config = await res.json();

        document.getElementById('poll_reminders_enabled').checked = config.poll_reminders_enabled !== false;
        document.getElementById('poll_reminders_interval').value = config.poll_reminders_interval || config.fast_polling_seconds || 30;

        document.getElementById('poll_tasks_enabled').checked = config.poll_tasks_enabled !== false;
        document.getElementById('poll_tasks_interval').value = config.poll_tasks_interval || 5;

        document.getElementById('poll_apis_enabled').checked = config.poll_apis_enabled !== false;
        document.getElementById('poll_apis_interval').value = config.poll_apis_interval || config.proactive_polling_minutes || 20;

        if (!config.has_google_auth) {
            document.getElementById('poll_apis_enabled').checked = false;
            document.getElementById('poll_apis_enabled').disabled = true;
            const lbl = document.getElementById('poll_apis_label');
            if (!lbl.innerText.includes('Missing')) lbl.innerText += " (Auth Missing)";
        }

        document.getElementById('nightly_cleanup_enabled').checked = config.nightly_cleanup_enabled !== false;
        document.getElementById('nightly_cleanup_time').value = config.nightly_cleanup_time || "03:00";

        document.getElementById('nightly_memory_enabled').checked = config.nightly_memory_enabled !== false;
        document.getElementById('nightly_memory_time').value = config.nightly_memory_time || "03:15";

    } catch(e) { console.error(e); }

    loadShellAudit();
}

async function saveScheduler(e) {
    e.preventDefault();
    const configData = {
        poll_reminders_enabled: document.getElementById('poll_reminders_enabled').checked,
        poll_reminders_interval: parseInt(document.getElementById('poll_reminders_interval').value, 10),
        poll_tasks_enabled: document.getElementById('poll_tasks_enabled').checked,
        poll_tasks_interval: parseInt(document.getElementById('poll_tasks_interval').value, 10),
        poll_apis_enabled: document.getElementById('poll_apis_enabled').checked,
        poll_apis_interval: parseInt(document.getElementById('poll_apis_interval').value, 10),
        nightly_cleanup_enabled: document.getElementById('nightly_cleanup_enabled').checked,
        nightly_cleanup_time: document.getElementById('nightly_cleanup_time').value,
        nightly_memory_enabled: document.getElementById('nightly_memory_enabled').checked,
        nightly_memory_time: document.getElementById('nightly_memory_time').value
    };

    try {
        const res = await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(configData)
        });
        if (res.ok) {
            const status = document.getElementById('save-scheduler-status');
            status.style.display = 'inline-flex';
            setTimeout(() => { status.style.display = 'none'; }, 3000);
        }
    } catch (e) { console.error('Error saving scheduler config', e); }
}

/* ---------- Flush controls ---------- */
async function _flushTarget(target, confirmMsg) {
    if (!confirm(confirmMsg)) return;
    try {
        const res = await fetch('/api/flush', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target })
        });
        const data = await res.json();
        const status = document.getElementById('flush-status');
        if (status) {
            status.textContent = data.message || 'Done!';
            status.style.display = 'inline-flex';
            setTimeout(() => { status.style.display = 'none'; }, 3000);
        }
        loadDashboard();
    } catch (e) { console.error('Flush failed', e); alert('Flush failed'); }
}

function flushTaskQueue() {
    _flushTarget('task_queue', 'This will remove all queued, stuck, and failed tasks. Continue?');
}
function flushReminders() {
    _flushTarget('completed_reminders', 'Remove all completed reminders?');
}
function flushAllReminders() {
    _flushTarget('all_reminders', 'This will delete ALL reminders (pending and completed). Are you sure?');
}

/* ---------- Shell Audit Log ---------- */
async function loadShellAudit() {
    try {
        const res = await fetch('/api/shell-audit', { cache: 'no-store' });
        const entries = await res.json();
        const tbody = document.getElementById('shell-audit-body');
        if (!tbody) return;
        tbody.innerHTML = '';

        if (!Array.isArray(entries) || entries.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted py-3">No shell commands recorded yet.</td></tr>';
            return;
        }

        entries.forEach(e => {
            const statusBadge = e.status === 'success'
                ? '<span class="badge bg-success">OK</span>'
                : e.status === 'denied'
                ? '<span class="badge bg-danger">Denied</span>'
                : `<span class="badge bg-warning text-dark">${e.status}</span>`;

            const shortCmd = e.command.length > 80 ? e.command.substring(0, 77) + '...' : e.command;
            const shortOut = (e.output_summary || '-').length > 60
                ? (e.output_summary || '').substring(0, 57) + '...'
                : (e.output_summary || '-');

            tbody.innerHTML += `<tr>
                <td><small>${e.executed_at || ''}</small></td>
                <td><code title="${e.command.replace(/"/g, '&quot;')}">${shortCmd}</code></td>
                <td class="text-center">${statusBadge}</td>
                <td><small class="text-muted">${shortOut}</small></td>
            </tr>`;
        });
    } catch (e) {
        console.error('Error loading shell audit', e);
    }
}

/* ---------- Theme ---------- */
function applyTheme(dark) {
    isDarkMode = dark;
    if (dark) {
        document.documentElement.setAttribute('data-theme', 'dark');
        const btn = document.getElementById('theme-toggle-btn');
        if (btn) { btn.classList.remove('bi-moon-fill'); btn.classList.add('bi-sun-fill'); }
    } else {
        document.documentElement.removeAttribute('data-theme');
        const btn = document.getElementById('theme-toggle-btn');
        if (btn) { btn.classList.remove('bi-sun-fill'); btn.classList.add('bi-moon-fill'); }
    }
}

async function toggleTheme() {
    applyTheme(!isDarkMode);
    localStorage.setItem('theme', isDarkMode ? 'dark' : 'light');
    try {
        await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ dark_mode: isDarkMode })
        });
    } catch(e) { console.error('Failed to save theme', e); }
}

/* ---------- Context stats ---------- */
async function updateContextStats() {
    try {
        const res = await fetch('/api/context', { cache: 'no-store', signal: AbortSignal.timeout(3000) });
        const data = await res.json();
        const el = document.getElementById('context-usage');
        const chip = document.getElementById('context-chip');
        if (!el || !data.max_tokens) return;
        const pct = ((data.tokens_used / data.max_tokens) * 100).toFixed(0);
        el.textContent = `${pct}%`;
        chip.title = `Context: ${data.tokens_used.toLocaleString()} / ${data.max_tokens.toLocaleString()} tokens (${data.messages} msgs)`;
        chip.classList.remove('context-ok', 'context-warn', 'context-high');
        if (pct < 50) chip.classList.add('context-ok');
        else if (pct < 60) chip.classList.add('context-warn');
        else chip.classList.add('context-high');
    } catch (e) { /* silent */ }
}

/* ---------- Live clock ---------- */
function updateClock() {
    const el = document.getElementById('live-clock');
    if (!el) return;
    const now = new Date();
    let h = now.getHours();
    const ampm = h >= 12 ? 'PM' : 'AM';
    h = h % 12 || 12;
    const m = now.getMinutes().toString().padStart(2, '0');
    el.textContent = `${h}:${m} ${ampm}`;
}

/* ---------- Model display ---------- */
function friendlyModelName(modelPath) {
    if (!modelPath) return 'Unknown';
    if (modelPath.includes('14B')) return 'Ministral 14B';
    if (modelPath.includes('8B')) return 'Ministral 8B';
    if (modelPath.includes('3B')) return 'Ministral 3B Lite';
    const parts = modelPath.split('/');
    return parts[parts.length - 1].substring(0, 20);
}

/* ---------- Init config / agent header ---------- */
async function initConfig() {
    try {
        const res = await fetch('/api/config', { cache: 'no-store' });
        const config = await res.json();
        cachedAgentName = config.agent_name || "Agent";
        cachedUserName = config.user_name || "User";
        document.getElementById('agent-name').innerText = cachedAgentName;

        const modelEl = document.getElementById('model-name');
        if (modelEl) modelEl.textContent = friendlyModelName(config.model_path);

        const localTheme = localStorage.getItem('theme');
        if (localTheme === 'light') applyTheme(false);
        else if (localTheme === 'dark' || config.dark_mode !== false) applyTheme(true);
        else applyTheme(true);
    } catch(e) { console.error(e); }
}

/* ---------- Chat ---------- */
function appendMessage(text, isUser, isSystem = false) {
    const chatWindow = document.getElementById('chat-window');
    if (chatWindow.innerHTML.includes("Ready to assist you")) chatWindow.innerHTML = '';

    const msgDiv = document.createElement('div');
    if (isSystem) {
        msgDiv.className = 'chat-message mx-auto text-center text-muted';
        msgDiv.style.fontSize = '0.82rem';
        msgDiv.textContent = text;
    } else {
        msgDiv.className = 'chat-message ' + (isUser ? 'msg-user' : 'msg-assistant');
        if (isUser) msgDiv.textContent = text;
        else msgDiv.innerHTML = marked.parse(text);
    }

    chatWindow.appendChild(msgDiv);
    chatWindow.scrollTop = chatWindow.scrollHeight;
    return msgDiv;
}

function toolStartText(tools) {
    if (!tools || tools.length === 0) {
        return `${cachedAgentName} is working on it...`;
    }
    const friendly = tools.map(t => toolFriendlyNames[t] || t.replace(/_/g, ' ')).filter(Boolean);
    const unique = [...new Set(friendly)];
    if (unique.length === 1) return unique[0] + "...";
    if (unique.length <= 3) return unique.slice(0, -1).join(', ') + ' & ' + unique[unique.length - 1] + "...";
    return unique[0] + " and more...";
}

function showTypingIndicator(show, customText = null) {
    const chatWindow = document.getElementById('chat-window');

    if (typingInterval) { clearInterval(typingInterval); typingInterval = null; }

    if (show) {
        if (!typingIndicator) {
            typingIndicator = document.createElement('div');
            typingIndicator.className = 'chat-message msg-assistant';
            typingIndicator.style.fontStyle = 'italic';
            typingIndicator.style.opacity = '0.65';
            chatWindow.appendChild(typingIndicator);
        }

        const updateText = (text) => {
            typingIndicator.innerHTML = `<span class="spinner-grow spinner-grow-sm me-2" role="status"></span> ${text}`;
            chatWindow.scrollTop = chatWindow.scrollHeight;
        };

        if (customText) {
            updateText(customText);
        } else {
            updateText(`${cachedAgentName} is thinking...`);
            typingInterval = setInterval(() => {
                const msg = thinkingMessages[Math.floor(Math.random() * thinkingMessages.length)];
                updateText(`${cachedAgentName} ${msg}`);
            }, 8000);
        }

    } else if (typingIndicator) {
        typingIndicator.remove();
        typingIndicator = null;
    }
}

async function sendChatMessage(e) {
    e.preventDefault();
    const input = document.getElementById('chat-input');
    const rawMsg = input.value;
    if (!rawMsg.trim()) return;

    if (rawMsg.trim().toLowerCase() === '/clear') {
        document.getElementById('chat-window').innerHTML = '<div class="text-center text-muted mt-5" style="font-size:.9rem;">Ready to assist you.</div>';
        input.value = '';
        return;
    }

    let msgToSend = rawMsg;
    let attachment = null;
    let displayMsg = rawMsg;

    if (rawMsg.length > 1000) {
        let splitIndex = rawMsg.indexOf('\n\n');
        if (splitIndex === -1 || splitIndex > 200) splitIndex = 200;
        msgToSend = rawMsg.substring(0, splitIndex).trim() + "...";
        attachment = rawMsg.substring(splitIndex).trim();
        displayMsg = msgToSend + "\n\n📎 Large text block attached";
    }

    input.value = '';

    const btn = document.getElementById('chat-submit');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status"></span>';

    appendMessage(displayMsg, true);
    showTypingIndicator(true);

    try {
        const payload = { message: msgToSend };
        if (attachment) payload.attachment = attachment;

        await fetch('/api/chat/send', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
    } catch(e) {
        showTypingIndicator(false);
        appendMessage("Error: Could not reach backend.", false);
        btn.disabled = false;
        btn.innerHTML = '<i class="bi bi-send me-1"></i>Send';
    }
}

async function pollChat() {
    try {
        const res = await fetch(`/api/chat/poll?cursor=${chatCursor}`, { cache: 'no-store' });
        if (res.status === 200) {
            const data = await res.json();
            if (data && data.messages) {
                data.messages.forEach(msg => {
                    const btn = document.getElementById('chat-submit');

                    if (msg.type === "user") {
                        // Already rendered client-side in sendChatMessage; skip
                    }
                    else if (msg.type === "tool_start") {
                        const label = toolStartText(msg.tools);
                        showTypingIndicator(true, label);
                    }
                    else if (msg.type === "done") {
                        showTypingIndicator(false);
                        if (msg.content && msg.content.trim()) appendMessage(msg.content, false);
                        btn.disabled = false;
                        btn.innerHTML = '<i class="bi bi-send me-1"></i>Send';
                        checkConnectionStatus();
                        loadDashboard();
                    }
                    else if (msg.type === "error") {
                        showTypingIndicator(false);
                        appendMessage("Error: " + msg.content, false);
                        btn.disabled = false;
                        btn.innerHTML = '<i class="bi bi-send me-1"></i>Send';
                    }
                    else if (msg.type === "proactive_start") {
                        showTypingIndicator(true, "Proactive Update...");
                    }
                });

                if (data.next_cursor !== undefined) chatCursor = data.next_cursor;
            }
        }
    } catch (e) { /* silently retry */ }

    setTimeout(pollChat, 500);
}

/* ---------- Rotating placeholder hints ---------- */
const placeholderHints = [
    "Ask anything... or try /remind 5pm call mom",
    "Try: /email john about meeting: Let's sync tomorrow",
    "Try: /cal tomorrow — instant calendar check",
    "Try: /search latest AI news — quick web search",
    "Try: /bill 50 electric due March 20",
    "Try: /bills — list pending bills",
    "Try: /reminders — see all reminders",
    "Ask your agent anything...",
];
let _placeholderIdx = 0;

function rotatePlaceholder() {
    const input = document.getElementById('chat-input');
    if (input && !input.value && document.activeElement !== input) {
        _placeholderIdx = (_placeholderIdx + 1) % placeholderHints.length;
        input.placeholder = placeholderHints[_placeholderIdx];
    }
}

/* ---------- Boot ---------- */
document.addEventListener("DOMContentLoaded", () => {
    const chatInput = document.getElementById('chat-input');
    if (chatInput) {
        // Enter submits; Shift+Enter inserts a newline for multiline prompts.
        chatInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
                e.preventDefault();
                document.getElementById('chat-form')?.requestSubmit();
            }
        });
    }

    initConfig();
    checkConnectionStatus();
    loadDashboard();
    pollChat();
    updateClock();
    setInterval(updateClock, 1000);
    updateContextStats();
    setInterval(updateContextStats, 5000);
    rotatePlaceholder();
    setInterval(rotatePlaceholder, 5000);
});
