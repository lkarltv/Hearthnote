const state = {
  clients: [],
  client: null,
  sessions: [],
  otherNotes: [],
  note: null,
  navigation: 0,
  etag: null,
  saveTimer: null,
  dirty: false,
  saving: null,
  creating: false,
};

const $ = (selector) => document.querySelector(selector);
const shell = $(".app-shell");
const authScreen = $("#auth-screen");
const authForm = $("#auth-form");
const authPassword = $("#auth-password");
const authConfirm = $("#auth-confirm");
const authSubmit = $("#auth-submit");
const authError = $("#auth-error");
const clientList = $("#client-list");
const sessionList = $("#session-list");
const otherNotesList = $("#other-notes-list");
const editor = $("#note-editor");
const preview = $("#note-preview");
const readButton = $("#read-note");
const editButton = $("#edit-note");
const saveState = $("#save-state");
const narrowViewport = window.matchMedia("(max-width: 1060px)");
const sectionPreferences = new Map();
const avatarColors = ["#d7c8b6", "#c8d7cf", "#d8c6c0", "#cbd2dc", "#ded4b8", "#d3c9dc"];
let authMode = "login";
let workspaceLoaded = false;

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (response.ok && !response.headers.get("Content-Type")?.includes("application/json")) {
    throw new Error("Hearthnote returned an unexpected response. Restart the server and refresh the page.");
  }
  const body = await response.json();
  if (!response.ok) {
    const error = new Error(body.error || "Something went wrong");
    error.status = response.status;
    error.body = body;
    if (error.status === 401 && !path.startsWith("/api/auth/") && !shell.hidden) {
      showAuth("login", "Your session expired. Sign in again to continue.");
    }
    throw error;
  }
  return body;
}

function showAuth(mode, message) {
  const setup = mode === "setup";
  authMode = mode;
  shell.hidden = true;
  authScreen.hidden = false;
  authForm.reset();
  authForm.hidden = false;
  $("#auth-retry").hidden = true;
  $("#auth-title").textContent = setup ? "Create your account" : "Sign in";
  $("#auth-description").textContent = message ?? (setup
    ? "Choose a username and a password with at least 8 characters."
    : "Sign in to access your coaching notes.");
  $("#auth-confirm-label").hidden = !setup;
  authConfirm.required = setup;
  authPassword.autocomplete = setup ? "new-password" : "current-password";
  authSubmit.textContent = setup ? "Create account" : "Sign in";
  authError.textContent = "";
  $("#auth-username").focus();
}

async function openWorkspace() {
  authScreen.hidden = true;
  shell.hidden = false;
  try {
    if (workspaceLoaded) {
      await saveNote();
    } else {
      await loadClients();
      workspaceLoaded = true;
    }
  } catch (error) {
    toast(error.message);
  }
}

async function checkAuthentication() {
  $("#auth-retry").hidden = true;
  $("#auth-description").textContent = "Checking your account…";
  try {
    const session = await api("/api/auth/status");
    if (session.authenticated) await openWorkspace();
    else showAuth(session.setup_required ? "setup" : "login");
  } catch (error) {
    $("#auth-description").textContent = error.message;
    $("#auth-retry").hidden = false;
  }
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
function updateNoteDate(note) {
  $("#session-date").textContent = note.number === undefined
    ? friendlyDate(note.modified_at)
    : sessionDate(note.content, note.modified_at);
}
function wordCount(content) {
  const words = content.trim().match(/[\p{L}\p{N}'’]+/gu) || [];
  return `${words.length} ${words.length === 1 ? "word" : "words"}`;
}

function notePath(client, note) {
  const root = `/api/clients/${encode(client)}`;
  return note.number !== undefined
    ? `${root}/sessions/${note.number}`
    : `${root}/other-notes/${encode(note.filename)}`;
}

function setMobileView(view, focusTarget) {
  shell.dataset.mobileView = view;
  if (narrowViewport.matches) {
    window.scrollTo(0, 0);
    focusTarget.focus();
  }
}

function sectionKey(client, button) {
  return `hearthnote.sections.${encode(client)}.${button.id}`;
}

function setSectionExpanded(button, expanded) {
  button.setAttribute("aria-expanded", String(expanded));
  document.getElementById(button.getAttribute("aria-controls")).hidden = !expanded;
}

function restoreSections(client) {
  document.querySelectorAll(".section-toggle").forEach((button) => {
    const key = sectionKey(client, button);
    let preference = sectionPreferences.get(key);
    if (preference === undefined) {
      try { preference = window.localStorage.getItem(key); } catch {}
    }
    setSectionExpanded(button, preference !== "false");
  });
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
  clientList.querySelectorAll("[data-client]").forEach((button) => {
    button.addEventListener("click", () => selectClient(button.dataset.client).catch((error) => toast(error.message)));
  });
}

async function selectClient(name, switchView = true) {
  const navigation = ++state.navigation;
  if (!await flushChanges() || navigation !== state.navigation) return;
  const root = `/api/clients/${encode(name)}`;
  const [sessions, otherNotes] = await Promise.all([api(`${root}/sessions`), api(`${root}/other-notes`)]);
  if (navigation !== state.navigation || !await flushChanges() || navigation !== state.navigation) return;
  state.client = name;
  state.note = null;
  state.etag = null;
  state.sessions = sessions.sessions;
  state.otherNotes = otherNotes.notes;
  renderClients();
  const client = state.clients.find((item) => item.name === name);
  $("#selected-client").textContent = name;
  $("#selected-avatar").textContent = client?.initials || "";
  $("#selected-avatar").style.setProperty("--avatar", colorFor(name));
  $("#new-session").disabled = state.creating;
  restoreSections(name);
  $("#note-sections").hidden = false;
  renderNotes();
  showEmptyEditor();
  if (switchView) setMobileView("sessions", $("#selected-client"));
  const firstNote = state.sessions[0] ?? state.otherNotes[0];
  if (firstNote && !narrowViewport.matches) await selectNote(firstNote, false);
}

function noteTitle(note) {
  return note.number !== undefined ? `Session ${note.number}` : note.filename.slice(0, -3);
}

function renderNoteList(list, notes, emptyMessage, timeline = false) {
  list.innerHTML = notes.map((note) => `
    <button class="session-card${timeline ? " timeline-card" : ""}" data-note-path="${escapeHtml(notePath(state.client, note))}">
      <strong>${escapeHtml(noteTitle(note))}</strong><span>${friendlyDate(note.modified_at)}</span>
    </button>`).join("") || emptyMessage;
  list.querySelectorAll("button").forEach((button, index) => {
    button.addEventListener("click", () => selectNote(notes[index]).catch((error) => toast(error.message)));
  });
}

function renderNotes() {
  $("#session-count").textContent = `${state.sessions.length} ${state.sessions.length === 1 ? "session" : "sessions"}`;
  renderNoteList(otherNotesList, state.otherNotes, '<p class="empty-other-notes">No other Markdown files.</p>');
  renderNoteList(sessionList, state.sessions, '<div class="empty-sessions">No notes yet.<br>Create the first session when you’re ready.</div>', true);
  updateNoteSelection();
}

function updateNoteSelection() {
  const path = state.note ? notePath(state.client, state.note) : null;
  document.querySelectorAll("[data-note-path]").forEach((button) => {
    const active = button.dataset.notePath === path;
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "true");
    else button.removeAttribute("aria-current");
  });
}

async function selectNote(reference, switchView = true) {
  const navigation = ++state.navigation;
  const path = notePath(state.client, reference);
  if (state.note && path === notePath(state.client, state.note)) {
    if (switchView) setMobileView("editor", $("#editor-title"));
    return;
  }
  if (!await flushChanges() || navigation !== state.navigation) return;
  const note = await api(path);
  if (navigation !== state.navigation || !await flushChanges() || navigation !== state.navigation) return;
  state.note = reference;
  state.etag = note.etag;
  state.dirty = false;
  editor.value = note.content;
  editor.scrollTop = 0;
  $("#crumb-client").textContent = state.client;
  $("#crumb-session").textContent = note.filename;
  $("#editor-title").textContent = noteTitle(note);
  updateNoteDate(note);
  $("#word-count").textContent = wordCount(note.content);
  $("#empty-state").classList.add("hidden");
  $("#editor-workspace").classList.remove("hidden");
  setNoteMode("read");
  setSaveStatus("saved");
  updateNoteSelection();
  if (switchView) setMobileView("editor", $("#editor-title"));
}

function showEmptyEditor() {
  $("#empty-state").classList.remove("hidden");
  $("#editor-workspace").classList.add("hidden");
}

function setNoteMode(mode) {
  const editing = mode === "edit";
  editor.hidden = !editing;
  preview.hidden = editing;
  $("#editor-footer").hidden = !editing;
  readButton.setAttribute("aria-pressed", String(!editing));
  editButton.setAttribute("aria-pressed", String(editing));
  if (!editing) {
    preview.innerHTML = editor.value.trim()
      ? markdown.render(editor.value)
      : '<p class="empty-preview">This note is empty.</p>';
    preview.scrollTop = 0;
  }
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

function saveNote() {
  if (state.saving) return state.saving;
  if (!state.dirty || !state.note) return Promise.resolve(true);
  state.saving = writeNote().finally(() => { state.saving = null; });
  return state.saving;
}

async function flushChanges() {
  while (state.dirty) {
    if (!await saveNote()) return false;
  }
  return true;
}

async function writeNote() {
  clearTimeout(state.saveTimer);
  const contentAtStart = editor.value;
  setSaveStatus("saving");
  try {
    const note = await api(notePath(state.client, state.note), {
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
    updateNoteDate(note);
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
  }
}

async function createSession() {
  if (!state.client || state.creating) return;
  const client = state.client;
  const navigation = state.navigation;
  state.creating = true;
  $("#new-session").disabled = true;
  try {
    if (!await flushChanges() || navigation !== state.navigation) return;
    const path = `/api/clients/${encode(client)}/sessions`;
    const note = await api(path, { method: "POST", body: "{}" });
    const result = await api(path);
    if (client !== state.client) return;
    state.sessions = result.sessions;
    renderNotes();
    if (navigation === state.navigation) {
      await selectNote(note);
      if (state.client === client && state.note?.number === note.number) {
        setNoteMode("edit");
        editor.focus();
      }
    }
    toast(`Session ${note.number} created`);
  } catch (error) { toast(error.message); }
  finally {
    state.creating = false;
    $("#new-session").disabled = !state.client;
  }
}

function escapeHtml(value) {
  return value.replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);
}

$("#client-search").addEventListener("input", renderClients);
$("#auth-retry").addEventListener("click", checkAuthentication);
authForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (authSubmit.disabled) return;
  if (authMode === "setup" && authPassword.value !== authConfirm.value) {
    authError.textContent = "The passwords do not match.";
    authConfirm.focus();
    return;
  }
  authSubmit.disabled = true;
  authError.textContent = "";
  try {
    await api(`/api/auth/${authMode}`, {
      method: "POST",
      body: JSON.stringify({ username: $("#auth-username").value, password: authPassword.value }),
    });
    authForm.reset();
    await openWorkspace();
  } catch (error) {
    if (error.status === 409) {
      await checkAuthentication();
    } else {
      authError.textContent = error.message;
      if (error.status === 401) {
        authPassword.value = "";
        authPassword.focus();
      }
    }
  } finally {
    authSubmit.disabled = false;
  }
});
$("#sign-out").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  editor.readOnly = true;
  try {
    if (!await flushChanges()) return;
    await api("/api/auth/logout", { method: "POST" });
    window.location.reload();
  } catch (error) {
    toast(error.message);
  } finally {
    editor.readOnly = false;
    button.disabled = false;
  }
});
$("#new-session").addEventListener("click", createSession);
editor.addEventListener("input", scheduleSave);
readButton.addEventListener("click", () => {
  if (!preview.hidden) return;
  setNoteMode("read");
  saveNote();
});
editButton.addEventListener("click", () => {
  setNoteMode("edit");
  editor.focus();
});
document.querySelectorAll(".section-toggle").forEach((button) => {
  button.addEventListener("click", () => {
    if (!state.client) return;
    const expanded = button.getAttribute("aria-expanded") === "false";
    const key = sectionKey(state.client, button);
    setSectionExpanded(button, expanded);
    sectionPreferences.set(key, String(expanded));
    try { window.localStorage.setItem(key, String(expanded)); } catch {}
  });
});
$("#back-to-clients").addEventListener("click", () => {
  state.navigation += 1;
  setMobileView("clients", clientList.querySelector(".active") ?? $("#clients-heading"));
});
$("#back-to-notes").addEventListener("click", async () => {
  const navigation = ++state.navigation;
  if (!await flushChanges() || navigation !== state.navigation) return;
  const active = $(".note-section [aria-current]:not([hidden] *)");
  setMobileView("sessions", active ?? $("#selected-client"));
});
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
    setMobileView("sessions", $("#selected-client"));
    toast(`${name} added`);
  } catch (error) { toast(error.message); }
});
document.addEventListener("keydown", async (event) => {
  if (shell.hidden) return;
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); $("#client-search").focus(); }
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") { event.preventDefault(); await saveNote(); }
});
window.addEventListener("beforeunload", (event) => { if (state.dirty) { event.preventDefault(); event.returnValue = ""; } });

shell.dataset.mobileView = "clients";
checkAuthentication();

