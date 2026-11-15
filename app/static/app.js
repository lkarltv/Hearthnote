const state = {
  clients: [],
  client: null,
  sessions: [],
  session: null,
  etag: null,
  saveTimer: null,
  dirty: false,
  saving: false,
};

const $ = (selector) => document.querySelector(selector);
const shell = $(".app-shell");
const clientList = $("#client-list");
const sessionList = $("#session-list");
const editor = $("#note-editor");
const saveState = $("#save-state");
const avatarColors = ["#d7c8b6", "#c8d7cf", "#d8c6c0", "#cbd2dc", "#ded4b8", "#d3c9dc"];

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const body = await response.json();
  if (!response.ok) {
    const error = new Error(body.error || "Something went wrong");
    error.status = response.status;
    error.body = body;
    throw error;
  }
  return body;
}

function encode(value) { return encodeURIComponent(value); }
function colorFor(name) {
  return avatarColors[[...name].reduce((sum, char) => sum + char.charCodeAt(0), 0) % avatarColors.length];
}
function friendlyDate(value) {
  if (!value) return "No sessions yet";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" }).format(new Date(value));
}
function sessionDate(content, fallback) {
  const match = content.match(/^\*\*Date:\*\*\s*(.+)$/m);
  return match ? match[1] : friendlyDate(fallback);
}
function wordCount(content) {
  const words = content.trim().match(/[\p{L}\p{N}'’]+/gu) || [];
  return `${words.length} ${words.length === 1 ? "word" : "words"}`;
}
function toast(message) {
  const element = $("#toast");
  element.textContent = message;
  element.classList.add("visible");
  clearTimeout(element.timer);
  element.timer = setTimeout(() => element.classList.remove("visible"), 3500);
}

async function loadClients(selectName = state.client) {
  const { clients } = await api("/api/clients");
  state.clients = clients;
  renderClients();
  const target = selectName && clients.some((client) => client.name === selectName)
    ? selectName
    : clients[0]?.name;
  if (target) await selectClient(target, false);
}

function renderClients() {
  const query = $("#client-search").value.trim().toLowerCase();
  const clients = state.clients.filter((client) => client.name.toLowerCase().includes(query));
  if (!clients.length) {
    clientList.innerHTML = '<div class="no-results">No clients found</div>';
    return;
  }
  clientList.innerHTML = clients.map((client) => `
    <button class="client-card ${client.name === state.client ? "active" : ""}" data-client="${escapeHtml(client.name)}">
      <span class="avatar" style="--avatar:${colorFor(client.name)}">${escapeHtml(client.initials)}</span>
      <span class="client-copy"><strong>${escapeHtml(client.name)}</strong><span>${client.session_count} ${client.session_count === 1 ? "session" : "sessions"}</span></span>
      <span class="client-arrow">›</span>
    </button>`).join("");
  clientList.querySelectorAll("[data-client]").forEach((button) => button.addEventListener("click", () => selectClient(button.dataset.client)));
}

async function selectClient(name, switchView = true) {
  if (state.dirty && !await saveNote()) return;
  state.client = name;
  state.session = null;
  state.etag = null;
  renderClients();
  const client = state.clients.find((item) => item.name === name);
  $("#selected-client").textContent = name;
  $("#selected-avatar").textContent = client?.initials || "";
  $("#selected-avatar").style.setProperty("--avatar", colorFor(name));
  $("#new-session").disabled = false;
  const result = await api(`/api/clients/${encode(name)}/sessions`);
  state.sessions = result.sessions;
  renderSessions();
  showEmptyEditor();
  if (switchView) shell.dataset.mobileView = "sessions";
  if (state.sessions.length) await selectSession(state.sessions[0].number, false);
}

function renderSessions() {
  $("#session-count").textContent = `${state.sessions.length} ${state.sessions.length === 1 ? "session" : "sessions"}`;
  if (!state.sessions.length) {
    sessionList.innerHTML = '<div class="empty-sessions">No notes yet.<br>Create the first session when you’re ready.</div>';
    return;
  }
  sessionList.innerHTML = state.sessions.map((session) => `
    <button class="session-card ${session.number === state.session ? "active" : ""}" data-session="${session.number}">
      <strong>Session ${session.number}</strong><span>${friendlyDate(session.modified_at)}</span>
    </button>`).join("");
  sessionList.querySelectorAll("[data-session]").forEach((button) => button.addEventListener("click", () => selectSession(Number(button.dataset.session))));
}

async function selectSession(number, switchView = true) {
  if (state.session === number && !$("#editor-workspace").classList.contains("hidden")) {
    if (switchView) shell.dataset.mobileView = "editor";
    return;
  }
  if (state.dirty && !await saveNote()) return;
  const note = await api(`/api/clients/${encode(state.client)}/sessions/${number}`);
  state.session = number;
  state.etag = note.etag;
  state.dirty = false;
  editor.value = note.content;
  $("#crumb-client").textContent = state.client;
  $("#crumb-session").textContent = note.filename;
  $("#editor-title").textContent = `Session ${number}`;
  $("#session-date").textContent = sessionDate(note.content, note.modified_at);
  $("#word-count").textContent = wordCount(note.content);
  $("#empty-state").classList.add("hidden");
  $("#editor-workspace").classList.remove("hidden");
  setSaveStatus("saved");
  renderSessions();
  if (switchView) shell.dataset.mobileView = "editor";
}

function showEmptyEditor() {
  $("#empty-state").classList.remove("hidden");
  $("#editor-workspace").classList.add("hidden");
}

function setSaveStatus(status, label) {
  saveState.className = `save-state ${status === "saved" ? "" : status}`;
  saveState.lastElementChild.textContent = label || ({ saved: "All changes saved", saving: "Saving…", error: "Couldn’t save" }[status]);
}

function scheduleSave() {
  state.dirty = true;
  $("#word-count").textContent = wordCount(editor.value);
  setSaveStatus("saving", "Unsaved changes");
  clearTimeout(state.saveTimer);
  state.saveTimer = setTimeout(saveNote, 900);
}

async function saveNote() {
  if (!state.dirty || !state.client || !state.session) return true;
  if (state.saving) return false;
  clearTimeout(state.saveTimer);
  state.saving = true;
  const contentAtStart = editor.value;
  setSaveStatus("saving");
  try {
    const note = await api(`/api/clients/${encode(state.client)}/sessions/${state.session}`, {
      method: "PUT",
      body: JSON.stringify({ content: contentAtStart, etag: state.etag }),
    });
    state.etag = note.etag;
    state.dirty = editor.value !== contentAtStart;
    if (state.dirty) {
      setSaveStatus("saving", "Unsaved changes");
      state.saveTimer = setTimeout(saveNote, 250);
    } else {
      setSaveStatus("saved");
    }
    $("#session-date").textContent = sessionDate(note.content, note.modified_at);
    return true;
  } catch (error) {
    if (error.status === 409) {
      setSaveStatus("error", "Conflict detected");
      toast("This note changed outside Hearthnote. Your text is still here; copy it before reloading.");
    } else {
      setSaveStatus("error");
      toast(error.message);
    }
    return false;
  } finally {
    state.saving = false;
  }
}

async function createSession() {
  if (!state.client || !await saveNote()) return;
  try {
    const note = await api(`/api/clients/${encode(state.client)}/sessions`, { method: "POST", body: "{}" });
    const result = await api(`/api/clients/${encode(state.client)}/sessions`);
    state.sessions = result.sessions;
    state.session = null;
    renderSessions();
    await selectSession(note.number);
    editor.focus();
    toast(`Session ${note.number} created`);
  } catch (error) { toast(error.message); }
}

function escapeHtml(value) {
  return value.replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);
}

$("#client-search").addEventListener("input", renderClients);
$("#new-session").addEventListener("click", createSession);
editor.addEventListener("input", scheduleSave);
$("#back-to-clients").addEventListener("click", () => shell.dataset.mobileView = "clients");
$("#back-to-sessions").addEventListener("click", async () => { await saveNote(); shell.dataset.mobileView = "sessions"; });
$("#new-client").addEventListener("click", () => { $("#client-dialog").showModal(); setTimeout(() => $("#client-name").focus(), 50); });
$("#dialog-close").addEventListener("click", () => $("#client-dialog").close());
$("#dialog-cancel").addEventListener("click", () => $("#client-dialog").close());
$("#client-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const name = $("#client-name").value.trim();
  if (!name) return;
  try {
    await api("/api/clients", { method: "POST", body: JSON.stringify({ name }) });
    $("#client-dialog").close();
    $("#client-name").value = "";
    await loadClients(name);
    shell.dataset.mobileView = "sessions";
    toast(`${name} added`);
  } catch (error) { toast(error.message); }
});
document.addEventListener("keydown", async (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); $("#client-search").focus(); }
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") { event.preventDefault(); await saveNote(); }
});
window.addEventListener("beforeunload", (event) => { if (state.dirty) { event.preventDefault(); event.returnValue = ""; } });

shell.dataset.mobileView = "clients";
loadClients().catch((error) => toast(error.message));

