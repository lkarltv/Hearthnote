import { initAppearance, setWorkspaceAppearance } from "./appearance.js";
import { initDeletion } from "./deletion.js";
import { renderMarkdown } from "./markdown.js";

const NO_SECURITY = { enabled: false, ask_on_open: false, idle_minutes: 0, require_on_delete: false };

const state = {
  clients: [],
  client: null,
  sessions: [],
  otherNotes: [],
  note: null,
  etag: null,
  saveTimer: null,
  dirty: false,
  saving: null,
  navigating: false,
  mode: "clients",
  source: null,
  sources: [],
  security: NO_SECURITY,
};

const $ = (selector) => document.querySelector(selector);
const shell = $(".app-shell");
const authScreen = $("#auth-screen");
const authForm = $("#auth-form");
const authUsername = $("#auth-username");
const authPassword = $("#auth-password");
const authConfirm = $("#auth-confirm");
const authSubmit = $("#auth-submit");
const authError = $("#auth-error");
const authPinForm = $("#auth-pin-form");
const authSignupPin = $("#auth-signup-pin");
const authPinSubmit = $("#auth-pin-submit");
const authPinSkip = $("#auth-pin-skip");
const authPinBack = $("#auth-pin-back");
const authPinError = $("#auth-pin-error");
const authUnlockForm = $("#auth-unlock-form");
const authUnlockPin = $("#auth-unlock-pin");
const authUnlockSubmit = $("#auth-unlock-submit");
const authUnlockError = $("#auth-unlock-error");
const authUsePassword = $("#auth-use-password");
const authUsePin = $("#auth-use-pin");
const authRetry = $("#auth-retry");
const authTitle = $("#auth-title");
const authDescription = $("#auth-description");
const clientList = $("#client-list");
const sessionList = $("#session-list");
const otherNotesList = $("#other-notes-list");
const materialList = $("#material-list");
const noteSections = $("#note-sections");
const sectionToggles = document.querySelectorAll(".section-toggle");
const editor = $("#note-editor");
const preview = $("#note-preview");
const readButton = $("#read-note");
const editButton = $("#edit-note");
const saveState = $("#save-state");
const avatarColors = ["#d7c8b6", "#c8d7cf", "#d8c6c0", "#cbd2dc", "#ded4b8", "#d3c9dc"];
const narrowViewport = window.matchMedia("(max-width: 720px)");
const sectionPreferences = new Map();
let authMode = "login";
let workspaceLoaded = false;
let authGeneration = 0;
let pageOpened = false;
let checkingSession = false;
let securityRevision = 0;
let activityTimer;
let lastActivityReported = -Infinity;
const SESSION_CHECK_INTERVAL = 4000;
const ACTIVITY_INTERVAL = 3000;

async function api(path, options = {}) {
  const generation = authGeneration;
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
    if (!shell.hidden && generation === authGeneration) {
      if (error.status === 423) showAuth("unlock");
      else if (error.status === 401) showAuth("login", expiredSessionMessage());
    }
    error.body = body;
    throw error;
  }
  return body;
}

function expiredSessionMessage() {
  return state.dirty
    ? "Your session expired. Sign in again to save the unsaved changes in this tab."
    : "Your session expired. Sign in again to continue.";
}

function showAuth(mode, message) {
  const setup = mode === "setup";
  const locked = mode === "unlock";
  const recover = mode === "recover";
  authMode = mode;
  authGeneration++;
  clearTimeout(state.saveTimer);
  cancelActivityReport();
  closeDelete();
  shell.hidden = true;
  document.querySelectorAll("dialog[open]").forEach((dialog) => dialog.close());
  $("#toast").classList.remove("visible");
  authScreen.hidden = false;
  authRetry.hidden = true;
  authForm.reset();
  authPinForm.reset();
  authUnlockForm.reset();
  authForm.hidden = locked;
  authPinForm.hidden = true;
  authUnlockForm.hidden = !locked;
  authTitle.textContent = setup ? "Create your account" : locked ? "Hearthnote is locked" : "Sign in";
  if (message) authDescription.textContent = message;
  else if (setup) authDescription.textContent = "Choose a username and a password with at least 8 characters.";
  else if (locked) authDescription.textContent = state.dirty
    ? "Enter your PIN to unlock and save the unsaved changes in this tab."
    : "Enter your PIN to unlock your coaching notes.";
  else if (recover) authDescription.textContent = state.dirty
    ? "Sign in with your account password to unlock and save the unsaved changes in this tab."
    : "Sign in with your account password to unlock Hearthnote.";
  else authDescription.textContent = "Sign in to access your coaching notes.";
  $("#auth-confirm-label").hidden = !setup;
  authConfirm.required = setup;
  authPassword.autocomplete = setup ? "new-password" : "current-password";
  authPassword.minLength = setup ? 8 : 0;
  authSubmit.textContent = setup ? "Continue" : "Sign in";
  authUsePin.hidden = !recover;
  authError.textContent = "";
  authPinError.textContent = "";
  authUnlockError.textContent = "";
  (locked ? authUnlockPin : authUsername).focus();
}

function showSignupPinStep(shown) {
  authForm.hidden = shown;
  authPinForm.hidden = !shown;
  authPinForm.reset();
  authError.textContent = "";
  authPinError.textContent = "";
  authTitle.textContent = shown ? "Add an optional PIN" : "Create your account";
  authDescription.textContent = shown
    ? "Use at least 4 digits for a PIN, or skip this step to use only your password."
    : "Choose a username and a password with at least 8 characters.";
  (shown ? authSignupPin : authPassword).focus();
}

async function openWorkspace() {
  const generation = ++authGeneration;
  authForm.reset();
  authPinForm.reset();
  authUnlockForm.reset();
  authScreen.hidden = true;
  shell.hidden = false;
  lastActivityReported = -Infinity;
  if (state.saving) await state.saving;
  if (generation !== authGeneration) return;
  await navigate(async () => {
    if (!workspaceLoaded) await loadWorkspace(await api("/api/settings"));
  });
  if (generation !== authGeneration) return;
  const view = shell.dataset.mobileView;
  if (view === "editor" || (!narrowViewport.matches && state.note && !editor.hidden)) {
    if (state.mode === "knowledge") $("#reader-title").focus();
    else (editor.hidden ? $("#editor-title") : editor).focus();
  } else {
    (view === "sessions" && narrowViewport.matches ? $("#selected-client") : $("#panel-title")).focus();
  }
}

async function useSession(session) {
  state.security = session.security ?? NO_SECURITY;
  if (session.locked) showAuth("unlock");
  else if (session.authenticated) await openWorkspace();
  else showAuth(session.setup_required ? "setup" : "login");
}

async function checkAuthentication() {
  authForm.hidden = true;
  authPinForm.hidden = true;
  authUnlockForm.hidden = true;
  authRetry.hidden = true;
  authDescription.textContent = "Checking your account…";
  try {
    const session = pageOpened
      ? await api("/api/auth/status")
      : await api("/api/auth/open", { method: "POST", body: JSON.stringify({ opening: true }) });
    pageOpened = true;
    await useSession(session);
  } catch (error) {
    authDescription.textContent = error.message;
    authRetry.hidden = false;
    authRetry.focus();
  }
}

function applySessionCheck(session, generation, revision) {
  if (shell.hidden || generation !== authGeneration) return;
  if (revision === securityRevision) state.security = session.security ?? NO_SECURITY;
  if (session.locked) showAuth("unlock");
  else if (!session.authenticated) showAuth("login", expiredSessionMessage());
}

async function checkWorkspaceSession() {
  if (checkingSession || shell.hidden) return;
  const generation = authGeneration;
  const revision = securityRevision;
  checkingSession = true;
  try {
    applySessionCheck(await api("/api/auth/status"), generation, revision);
  } catch {
    // A temporary connection failure is not a lock; check again on the next poll or focus.
  } finally {
    checkingSession = false;
  }
}

function canReportActivity() {
  return !shell.hidden && !document.hidden && document.hasFocus() && state.security.idle_minutes > 0;
}

function cancelActivityReport() {
  clearTimeout(activityTimer);
  activityTimer = undefined;
}

async function reportActivity() {
  activityTimer = undefined;
  if (!canReportActivity()) return;
  const generation = authGeneration;
  const revision = securityRevision;
  lastActivityReported = performance.now();
  try {
    const session = await api("/api/auth/activity", { method: "POST" });
    applySessionCheck(session, generation, revision);
  } catch {
    // The API handler shows a lock or expired session; otherwise wait for further real input.
  }
}

function recordActivity(event) {
  if (!event.isTrusted || activityTimer !== undefined || !canReportActivity()) return;
  const wait = ACTIVITY_INTERVAL - (performance.now() - lastActivityReported);
  if (wait <= 0) reportActivity();
  else activityTimer = setTimeout(reportActivity, wait);
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
  $("#note-date").textContent = state.note.number === undefined
    ? friendlyDate(note.modified_at)
    : sessionDate(note.content, note.modified_at);
}
function wordCount(content) {
  const words = content.trim().match(/[\p{L}\p{N}'’]+/gu) || [];
  return `${words.length} ${words.length === 1 ? "word" : "words"}`;
}
function toast(message) {
  if (shell.hidden) return;
  const element = $("#toast");
  element.textContent = message;
  element.classList.add("visible");
  clearTimeout(element.timer);
  element.timer = setTimeout(() => element.classList.remove("visible"), 3500);
}

function sourceApi(path, params = {}) {
  return `${path}?${new URLSearchParams({ source: state.source, ...params })}`;
}

function noteApi(note) {
  const root = `/api/clients/${encode(state.client)}`;
  return sourceApi(note.number === undefined ? `${root}/other-notes/${encode(note.filename)}` : `${root}/sessions/${note.number}`);
}

function deletionTarget(control) {
  const { mode, source, client, note, topic, material } = state;
  if (!source) return null;
  if (control === "note" && note && client) {
    const payload = note.number === undefined
      ? { kind: "other-note", client, filename: note.filename }
      : { kind: "session", client, number: note.number };
    return { mode, source, payload, label: noteTitle(note) };
  }
  if (control === "material" && material) {
    return { mode, source, payload: { kind: "material", path: material }, label: $("#reader-title").textContent };
  }
  if (control === "folder" && mode === "clients" && client) {
    return { mode, source, payload: { kind: "client", client }, label: client };
  }
  if (control === "folder" && topic && topic !== ".") {
    return { mode, source, payload: { kind: "topic", path: topic }, label: topicName(topic) };
  }
  return null;
}

async function refreshAfterDeletion({ mode, source, payload }, restored) {
  if (state.mode !== mode || state.source !== source) return;
  const { kind, client, path } = payload;
  const wasEditor = shell.dataset.mobileView === "editor";
  if (mode === "clients") {
    await loadClients(restored ? client : state.client);
    if (!state.clients.length) {
      await openSource(mode, source);
    } else if (restored && kind !== "client") {
      await selectNote(payload, wasEditor);
    } else if (!restored && kind === "client") {
      setMobileView("clients", $("#panel-title"));
    } else if (!state.note && wasEditor) {
      setMobileView("sessions", $("#selected-client"));
    }
    return;
  }

  ({ topics: state.topics } = await api(sourceApi("/api/knowledge")));
  if (!state.topics.length) {
    await openSource(mode, source);
    return;
  }
  const preferred = !restored ? state.topic : kind === "topic" ? path : path.split("/").slice(0, -1).join("/") || ".";
  const next = state.topics.find((item) => item.path === preferred) ?? state.topics[0];
  state.topic = null;
  await selectTopic(next.path, false);
  if (restored && kind === "material") await selectMaterial(path, wasEditor);
  else if (!restored && kind === "topic") setMobileView("clients", $("#panel-title"));
  else if (!state.material && wasEditor) setMobileView("sessions", $("#selected-client"));
}

function setMobileView(view, focusTarget) {
  if (shell.dataset.mobileView !== view) closeDelete();
  shell.dataset.mobileView = view;
  if (narrowViewport.matches) {
    window.scrollTo(0, 0);
    focusTarget.focus();
  }
}

function sectionKey(button) {
  return `hearthnote.sections/${encode(state.source)}/${encode(state.client)}/${button.id}`;
}

function setSectionExpanded(button, expanded) {
  button.setAttribute("aria-expanded", String(expanded));
  document.getElementById(button.getAttribute("aria-controls")).hidden = !expanded;
}

function restoreSections() {
  for (const button of sectionToggles) {
    const key = sectionKey(button);
    let preference = sectionPreferences.get(key);
    if (preference === undefined) {
      try { preference = window.localStorage.getItem(key); } catch {}
    }
    setSectionExpanded(button, preference !== "false");
  }
}

function modeSources(mode = state.mode) {
  return state.sources.filter((item) => item.type === mode);
}

function countLabel(count, singular) {
  return `${count} ${singular}${count === 1 ? "" : "s"}`;
}

function topicName(path) {
  return path === "." ? "General" : path.split("/").join(" / ");
}

function setSearch() {
  const knowledge = state.mode === "knowledge";
  const search = $("#client-search");
  search.value = "";
  search.placeholder = knowledge ? "Find a topic or material" : "Find a client";
  search.setAttribute("aria-label", search.placeholder);
}

async function loadWorkspace(settings) {
  state.sources = settings.sources;
  $("#vault-location").textContent = settings.notes_root;
  $("#vault-location").title = settings.notes_root;
  const current = modeSources().find((item) => item.path === state.source);
  const first = current || modeSources()[0] || state.sources[0];
  await openSource(first?.type || "clients", first?.path);
}

async function openSource(mode, path = modeSources(mode)[0]?.path) {
  workspaceLoaded = false;
  const knowledge = mode === "knowledge";
  const sources = modeSources(mode);
  Object.assign(state, {
    mode, source: path ?? null, client: null, note: null, etag: null,
    clients: [], sessions: [], otherNotes: [], topics: [], topic: null, material: null,
  });
  shell.dataset.mode = mode;
  setWorkspaceAppearance(mode);
  shell.dataset.mobileView = "clients";
  $(".clients-panel").setAttribute("aria-label", knowledge ? "Topics" : "Clients");
  $(".sessions-panel").setAttribute("aria-label", knowledge ? "Materials" : "Client notes");
  $("#back-to-clients").setAttribute("aria-label", knowledge ? "Back to topics" : "Back to clients");
  $("#back-to-clients-label").textContent = knowledge ? "Topics" : "Clients";
  $("#panel-eyebrow").textContent = knowledge ? "" : "Your practice";
  $("#panel-eyebrow").classList.toggle("hidden", knowledge);
  $("#panel-title").textContent = knowledge ? "Knowledge" : "Clients";
  $("#new-client").classList.toggle("hidden", knowledge || !path);
  $("#new-session").classList.toggle("hidden", knowledge);
  $("#new-session").disabled = true;
  $("#selected-eyebrow").textContent = knowledge ? "Topic" : "Working with";
  $("#selected-client").textContent = knowledge ? "Choose a topic" : "Choose a client";
  $("#selected-client").removeAttribute("title");
  $("#selected-avatar").replaceChildren();
  if (knowledge) {
    const icon = document.createElement("span");
    icon.className = "folder-glyph";
    icon.setAttribute("aria-hidden", "true");
    $("#selected-avatar").append(icon);
  }
  $("#selected-avatar").style.removeProperty("--avatar");
  $('[data-delete="folder"]').hidden = true;
  noteSections.hidden = true;
  $("#material-count").classList.toggle("hidden", !knowledge);
  materialList.classList.toggle("hidden", !knowledge);
  $("#material-count").textContent = "";
  materialList.replaceChildren();
  sessionList.replaceChildren();
  otherNotesList.replaceChildren();
  document.querySelectorAll("[data-mode]").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.mode === mode));
  });
  const picker = $("#source-select");
  picker.disabled = true;
  picker.replaceChildren(...sources.map((item) => new Option(item.path === "." ? item.name : item.path, item.path)));
  picker.value = state.source ?? "";
  $("#source-picker").classList.toggle("hidden", sources.length < 2);
  setSearch();
  showEmptyEditor();
  clientList.replaceChildren();
  try {
    if (!path) {
      renderEmptySource();
    } else if (knowledge) {
      ({ topics: state.topics } = await api(sourceApi("/api/knowledge")));
      renderTopics();
      if (state.topics.length) await selectTopic(state.topics[0].path, false);
    } else {
      await loadClients();
    }
    workspaceLoaded = true;
  } finally {
    picker.disabled = sources.length < 2;
  }
}

function renderEmptySource() {
  const empty = document.createElement("div");
  empty.className = "no-results";
  empty.textContent = "No folders added. ";
  const button = document.createElement("button");
  button.type = "button";
  button.className = "text-button";
  button.textContent = "Add folders";
  button.addEventListener("click", openSettings);
  empty.append(button);
  clientList.replaceChildren(empty);
}

function renderTopics() {
  const query = $("#client-search").value.trim().toLowerCase();
  const topics = state.topics.filter((topic) => topicName(topic.path).toLowerCase().includes(query)
    || topic.materials.some((item) => item.title.toLowerCase().includes(query)));
  clientList.replaceChildren(...topics.map((topic) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "client-card topic-card";
    button.classList.toggle("active", state.topic === topic.path);
    if (state.topic === topic.path) button.setAttribute("aria-current", "true");
    button.innerHTML = `<span class="topic-icon" aria-hidden="true"><span class="folder-glyph"></span></span>
      <span class="client-copy"><strong>${escapeHtml(topicName(topic.path))}</strong>
      <span>${countLabel(topic.materials.length, "material")}</span></span>
      <span class="client-arrow" aria-hidden="true">›</span>`;
    button.addEventListener("click", () => navigate(() => selectTopic(topic.path)));
    return button;
  }));
  if (!topics.length) {
    clientList.innerHTML = `<div class="no-results">${query ? "No matching topics or materials" : "No Markdown materials in this folder"}</div>`;
  }
}

function visibleMaterials(path) {
  const materials = state.topics.find((topic) => topic.path === path)?.materials ?? [];
  const query = $("#client-search").value.trim().toLowerCase();
  return topicName(path).toLowerCase().includes(query)
    ? materials
    : materials.filter((item) => item.title.toLowerCase().includes(query));
}

async function selectTopic(path, switchView = true) {
  const materials = visibleMaterials(path);
  if (state.topic === path) {
    if (switchView) setMobileView("sessions", $("#selected-client"));
    if (materials.length && !materials.some((item) => item.path === state.material)) {
      await selectMaterial(materials[0].path, false);
    }
    return;
  }
  state.topic = path;
  $('[data-delete="folder"]').hidden = path === ".";
  state.material = null;
  $("#selected-client").textContent = topicName(path);
  $("#selected-client").title = topicName(path);
  renderTopics();
  renderMaterials();
  showEmptyEditor();
  if (switchView) setMobileView("sessions", $("#selected-client"));
  if (materials.length) await selectMaterial(materials[0].path, false);
}

function renderMaterials() {
  if (state.topic === null) return;
  const materials = visibleMaterials(state.topic);
  $("#material-count").textContent = countLabel(materials.length, "material");
  materialList.replaceChildren(...materials.map((material) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "session-card material-card";
    button.classList.toggle("active", state.material === material.path);
    if (state.material === material.path) button.setAttribute("aria-current", "true");
    button.innerHTML = `<span class="material-icon" aria-hidden="true"></span><strong>${escapeHtml(material.title)}</strong>`;
    button.addEventListener("click", () => navigate(() => selectMaterial(material.path)));
    return button;
  }));
}

async function selectMaterial(path, switchView = true) {
  if (state.material !== path) {
    const item = await api(sourceApi("/api/material", { path }));
    closeDelete();
    const source = modeSources().find((folder) => folder.path === state.source);
    $("#reader-crumb").textContent = state.topic === "." ? source.name : `${source.name}  /  ${topicName(state.topic)}`;
    $("#reader-title").textContent = item.title;
    renderMarkdown($("#material-content"), item.content);
    $("#reader-workspace").scrollTop = 0;
    state.material = path;
    renderMaterials();
    $("#empty-state").classList.add("hidden");
    $("#reader-workspace").classList.remove("hidden");
  }
  if (switchView) setMobileView("editor", $("#reader-title"));
}

async function navigate(action) {
  if (state.navigating || shell.hidden) return;
  state.navigating = true;
  editor.readOnly = true;
  try {
    if (await saveNote()) return await action();
  } catch (error) {
    toast(error.message);
  } finally {
    editor.readOnly = false;
    state.navigating = false;
  }
}

async function loadClients(selectName = state.client) {
  const { clients } = await api(sourceApi("/api/clients"));
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
    <button type="button" class="client-card${client.name === state.client ? " active" : ""}"${client.name === state.client ? ' aria-current="true"' : ""} data-client="${escapeHtml(client.name)}">
      <span class="avatar" style="--avatar:${colorFor(client.name)}">${escapeHtml(client.initials)}</span>
      <span class="client-copy"><strong title="${escapeHtml(client.name)}">${escapeHtml(client.name)}</strong><span>${client.session_count} ${client.session_count === 1 ? "session" : "sessions"}</span></span>
      <span class="client-arrow" aria-hidden="true">›</span>
    </button>`).join("");
  clientList.querySelectorAll("[data-client]").forEach((button) => button.addEventListener("click", () => navigate(() => selectClient(button.dataset.client))));
}

async function selectClient(name, switchView = true) {
  const root = `/api/clients/${encode(name)}`;
  const [sessions, otherNotes] = await Promise.all([api(sourceApi(`${root}/sessions`)), api(sourceApi(`${root}/other-notes`))]);
  state.client = name;
  state.note = null;
  state.etag = null;
  renderClients();
  const client = state.clients.find((item) => item.name === name);
  $("#selected-client").textContent = name;
  $("#selected-client").title = name;
  $("#selected-avatar").textContent = client?.initials || "";
  $("#selected-avatar").style.setProperty("--avatar", colorFor(name));
  $('[data-delete="folder"]').hidden = false;
  $("#new-session").disabled = false;
  state.sessions = sessions.sessions;
  state.otherNotes = otherNotes.notes;
  restoreSections();
  noteSections.hidden = false;
  renderNotes();
  showEmptyEditor();
  if (switchView) setMobileView("sessions", $("#selected-client"));
  const firstNote = state.sessions[0] ?? state.otherNotes[0];
  if (firstNote) await selectNote(firstNote, false);
}

function noteTitle(note) {
  return note.number === undefined ? note.filename.slice(0, -3) : `Session ${note.number}`;
}

function renderNoteList(list, notes, emptyMessage, timeline = false) {
  list.innerHTML = notes.map((note) => `
    <button type="button" class="session-card${timeline ? " timeline-card" : ""}" data-note-path="${escapeHtml(noteApi(note))}">
      <strong>${escapeHtml(noteTitle(note))}</strong><span>${friendlyDate(note.modified_at)}</span>
    </button>`).join("") || emptyMessage;
  list.querySelectorAll("button").forEach((button, index) => {
    button.addEventListener("click", () => navigate(() => selectNote(notes[index])));
  });
}

function renderNotes() {
  $("#session-count").textContent = countLabel(state.sessions.length, "session");
  renderNoteList(sessionList, state.sessions, '<div class="empty-sessions">No sessions yet.<br>Create the first session when you’re ready.</div>', true);
  renderNoteList(otherNotesList, state.otherNotes, '<p class="empty-other-notes">No other Markdown files.</p>');
  updateNoteSelection();
}

function updateNoteSelection() {
  const path = state.note ? noteApi(state.note) : null;
  noteSections.querySelectorAll("[data-note-path]").forEach((button) => {
    const active = button.dataset.notePath === path;
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "true");
    else button.removeAttribute("aria-current");
  });
}

async function selectNote(reference, switchView = true) {
  const path = noteApi(reference);
  if (!state.note || path !== noteApi(state.note)) {
    const note = await api(path);
    closeDelete();
    state.note = reference;
    state.etag = note.etag;
    state.dirty = false;
    editor.value = note.content;
    editor.setSelectionRange(0, 0);
    $("#crumb-client").textContent = state.client;
    $("#crumb-note").textContent = note.filename;
    $("#editor-title").textContent = noteTitle(reference);
    updateNoteDate(note);
    $("#word-count").textContent = wordCount(note.content);
    $("#empty-state").classList.add("hidden");
    $("#editor-workspace").classList.remove("hidden");
    setNoteMode("read");
    setSaveStatus("saved");
    updateNoteSelection();
  }
  if (switchView) setMobileView("editor", $("#editor-title"));
}

function setNoteMode(mode) {
  const editing = mode === "edit";
  editor.hidden = !editing;
  preview.hidden = editing;
  $("#editor-footer").hidden = !editing;
  readButton.setAttribute("aria-pressed", String(!editing));
  editButton.setAttribute("aria-pressed", String(editing));
  if (!editing) {
    if (editor.value.trim()) {
      renderMarkdown(preview, editor.value);
    } else {
      preview.innerHTML = '<p class="empty-preview">This note is empty.</p>';
    }
    preview.scrollTop = 0;
  }
}

function showEmptyEditor() {
  closeDelete();
  $("#empty-state").classList.remove("hidden");
  $("#editor-workspace").classList.add("hidden");
  $("#reader-workspace").classList.add("hidden");
  const knowledge = state.mode === "knowledge";
  $("#empty-title").textContent = knowledge ? "Choose a material to read." : "Select a client to open their notes.";
  $("#empty-description").classList.toggle("hidden", knowledge);
  $("#empty-state .eyebrow").classList.toggle("hidden", knowledge);
  $("#empty-state .empty-orbit span").textContent = knowledge ? "" : "✦";
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
  if (state.saving && !await state.saving) return false;
  if (!state.dirty || !state.note) return true;
  if (shell.hidden) return false;
  if (state.saving) return saveNote();
  state.saving = writeNote();
  return state.saving;
}

async function writeNote() {
  clearTimeout(state.saveTimer);
  const contentAtStart = editor.value;
  setSaveStatus("saving");
  try {
    const note = await api(noteApi(state.note), {
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
  } finally {
    state.saving = null;
  }
}

async function createSession() {
  if (!state.client) return;
  const path = sourceApi(`/api/clients/${encode(state.client)}/sessions`);
  const note = await api(path, { method: "POST", body: "{}" });
  ({ sessions: state.sessions } = await api(path));
  renderNotes();
  await selectNote(note);
  setNoteMode("edit");
  toast(`Session ${note.number} created`);
  return true;
}

const settingsTabs = [...document.querySelectorAll(".settings-tabs [role=tab]")];

function activateSettingsTab(active) {
  for (const tab of settingsTabs) {
    const selected = tab === active;
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1;
    document.getElementById(tab.getAttribute("aria-controls")).classList.toggle("hidden", !selected);
  }
}

for (const [index, tab] of settingsTabs.entries()) {
  tab.addEventListener("click", () => activateSettingsTab(tab));
  tab.addEventListener("keydown", (event) => {
    let next;
    if (event.key === "Home") next = 0;
    else if (event.key === "End") next = settingsTabs.length - 1;
    else if (event.key === "ArrowRight") next = (index + 1) % settingsTabs.length;
    else if (event.key === "ArrowLeft") next = (index + settingsTabs.length - 1) % settingsTabs.length;
    else return;
    event.preventDefault();
    activateSettingsTab(settingsTabs[next]);
    settingsTabs[next].focus();
  });
}

const settingsDraft = { root: "", input: "", parent: ".", folders: null, sources: [], request: 0 };
const folderChoice = $("#folder-choice");
const notesRoot = $("#notes-root");
const securityForm = $("#security-form");
const securityEnabled = $("#security-enabled");
const securityPinOptions = $("#security-pin-options");
const securityAskOnOpen = $("#security-ask-on-open");
const securityIdleMinutes = $("#security-idle-minutes");
const securityRequireOnDelete = $("#security-require-on-delete");
const securityChangePin = $("#security-change-pin");
const securityNewPinField = $("#security-new-pin-field");
const securityNewPin = $("#security-new-pin");
const securityPassword = $("#security-password");
const securityMessageElement = $("#security-message");
const securityDraft = { configured: false, changingPin: false, ready: false, saving: false, request: 0 };

function securityMessage(message = "", error = false) {
  securityMessageElement.textContent = message;
  securityMessageElement.classList.toggle("error", error);
}

function renderSecurityControls() {
  const enabled = securityEnabled.checked;
  const editPin = enabled && (!securityDraft.configured || securityDraft.changingPin);
  const disabled = !securityDraft.ready || securityDraft.saving;
  securityPinOptions.hidden = !enabled;
  securityChangePin.hidden = !enabled || !securityDraft.configured;
  securityChangePin.textContent = securityDraft.changingPin ? "Cancel PIN change" : "Change PIN";
  securityNewPinField.hidden = !editPin;
  securityNewPin.required = editPin;
  for (const control of securityForm.elements) control.disabled = disabled;
  securityNewPin.disabled = disabled || !editPin;
  securityAskOnOpen.disabled = disabled || !enabled;
  securityIdleMinutes.disabled = disabled || !enabled;
  securityRequireOnDelete.disabled = disabled || !enabled;
}

function resetSecurityForm() {
  securityForm.reset();
  securityDraft.request++;
  Object.assign(securityDraft, { configured: false, changingPin: false, ready: false, saving: false });
  renderSecurityControls();
  securityMessage();
}

function fillSecurityForm(settings) {
  securityForm.reset();
  Object.assign(securityDraft, { configured: settings.enabled, changingPin: false, ready: true });
  securityEnabled.checked = settings.enabled;
  securityAskOnOpen.checked = settings.ask_on_open;
  securityIdleMinutes.value = settings.idle_minutes;
  securityRequireOnDelete.checked = settings.require_on_delete;
  renderSecurityControls();
}

function installSecuritySettings(settings) {
  securityRevision++;
  state.security = settings;
}

async function loadSecuritySettings() {
  resetSecurityForm();
  const request = securityDraft.request;
  securityMessage("Loading security settings…");
  try {
    const settings = await api("/api/security");
    if (request !== securityDraft.request || !settingsDialog.open) return;
    installSecuritySettings(settings);
    fillSecurityForm(settings);
    securityMessage();
  } catch (error) {
    if (request === securityDraft.request && settingsDialog.open) securityMessage(error.message, true);
  }
}

async function changeSecurity(event) {
  event.preventDefault();
  if (!securityDraft.ready || securityDraft.saving) return;
  const enabled = securityEnabled.checked;
  const payload = {
    enabled,
    ask_on_open: enabled && securityAskOnOpen.checked,
    idle_minutes: enabled ? Number(securityIdleMinutes.value) : 0,
    require_on_delete: enabled && securityRequireOnDelete.checked,
    password: securityPassword.value,
  };
  if (!securityNewPin.disabled) payload.new_pin = securityNewPin.value;
  const request = securityDraft.request;
  const generation = authGeneration;
  securityDraft.saving = true;
  renderSecurityControls();
  securityMessage("Saving security settings…");
  try {
    const settings = await api("/api/security", { method: "PUT", body: JSON.stringify(payload) });
    if (generation === authGeneration) installSecuritySettings(settings);
    if (request !== securityDraft.request || !settingsDialog.open) return;
    fillSecurityForm(settings);
    securityMessage("Security settings saved.");
  } catch (error) {
    if (request !== securityDraft.request || !settingsDialog.open) return;
    securityPassword.value = "";
    securityMessage(error.message, true);
  } finally {
    if (request === securityDraft.request && settingsDialog.open) {
      securityDraft.saving = false;
      renderSecurityControls();
    }
  }
}

function settingsMessage(message = "", error = false) {
  const summary = $("#settings-summary");
  summary.textContent = message;
  summary.classList.toggle("error", error);
}

function renderFolderSettings() {
  const rows = settingsDraft.sources.map((item) => {
    const row = document.createElement("div");
    row.className = "configured-folder";
    const name = document.createElement("span");
    name.textContent = item.path === "." ? "Coaching root" : item.path;
    const type = $("#folder-type").cloneNode(true);
    type.removeAttribute("id");
    type.setAttribute("aria-label", `Content type for ${name.textContent}`);
    type.value = item.type;
    type.addEventListener("change", () => { item.type = type.value; });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "secondary-button";
    remove.textContent = "Remove";
    remove.setAttribute("aria-label", `Remove ${name.textContent}`);
    remove.addEventListener("click", () => {
      settingsDraft.sources = settingsDraft.sources.filter((source) => source !== item);
      renderFolderSettings();
    });
    row.append(name, type, remove);
    return row;
  });
  $("#configured-folders").replaceChildren(...rows);
  const current = settingsDraft.parent;
  folderChoice.replaceChildren(new Option(current === "." ? "Coaching root" : current, current),
    ...(settingsDraft.folders || []).map((folder) => new Option(folder.path, folder.path)));
  updateFolderButtons();
}

function updateFolderButtons() {
  const available = Boolean(settingsDraft.folders);
  folderChoice.disabled = !available;
  $("#folder-up").disabled = !available || settingsDraft.parent === ".";
  $("#folder-open").disabled = !available || folderChoice.value === settingsDraft.parent;
  $("#folder-add").disabled = !available || settingsDraft.sources.some((source) => source.path === folderChoice.value);
}

async function browseFolders(parent = ".") {
  const input = notesRoot.value.trim();
  const request = ++settingsDraft.request;
  settingsDraft.folders = null;
  updateFolderButtons();
  try {
    const result = await api(`/api/folders?${new URLSearchParams({ root: input, parent })}`);
    if (request !== settingsDraft.request || notesRoot.value.trim() !== input) return false;
    if (result.notes_root !== settingsDraft.root) {
      settingsDraft.sources = result.suggested_sources;
    }
    settingsDraft.root = result.notes_root;
    settingsDraft.input = input;
    settingsDraft.parent = parent;
    settingsDraft.folders = result.folders;
    renderFolderSettings();
    settingsMessage();
    return true;
  } catch (error) {
    if (request === settingsDraft.request) settingsMessage(error.message, true);
    return false;
  }
}

async function openSettings() {
  const generation = authGeneration;
  try {
    const settings = await api("/api/settings");
    if (shell.hidden || generation !== authGeneration) return;
    notesRoot.value = settings.notes_root;
    Object.assign(settingsDraft, {
      root: settings.notes_root, input: "", parent: ".", folders: null, sources: settings.sources,
    });
    settingsMessage();
    renderFolderSettings();
    activateSettingsTab($("#vault-tab"));
    settingsDialog.showModal();
    $("#vault-tab").focus();
    await Promise.all([browseFolders(), loadSecuritySettings()]);
  } catch (error) { toast(error.message); }
}

async function changeVault(event) {
  event.preventDefault();
  if (state.navigating) return;
  const submit = event.currentTarget.querySelector('[type="submit"]');
  submit.disabled = true;
  try {
    if (notesRoot.value.trim() !== settingsDraft.input && !await browseFolders()) return;
    if (!await saveNote()) {
      settingsMessage("Resolve the current note’s save error before changing folders.", true);
      return;
    }
    const settings = await api("/api/settings", {
      method: "PUT",
      body: JSON.stringify({ notes_root: settingsDraft.root, sources: settingsDraft.sources }),
    });
    $("#settings-dialog").close();
    await navigate(() => loadWorkspace(settings));
    toast("Vault settings saved");
  } catch (error) {
    settingsMessage(error.message, true);
  } finally {
    submit.disabled = false;
  }
}

let rootTimer;
notesRoot.addEventListener("input", () => {
  settingsDraft.request++;
  settingsDraft.folders = null;
  updateFolderButtons();
  clearTimeout(rootTimer);
  rootTimer = setTimeout(() => browseFolders(), 300);
});
notesRoot.addEventListener("change", () => {
  clearTimeout(rootTimer);
  if (notesRoot.value.trim() !== settingsDraft.input) browseFolders();
});
folderChoice.addEventListener("change", updateFolderButtons);
$("#folder-open").addEventListener("click", () => browseFolders(folderChoice.value));
$("#folder-up").addEventListener("click", () => browseFolders(settingsDraft.parent.split("/").slice(0, -1).join("/") || "."));
$("#folder-add").addEventListener("click", () => {
  settingsDraft.sources.push({ path: folderChoice.value, type: $("#folder-type").value });
  renderFolderSettings();
});

function escapeHtml(value) {
  return value.replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);
}

authRetry.addEventListener("click", checkAuthentication);
authForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (authSubmit.disabled || authForm.hidden) return;
  if (authMode === "setup") {
    if (authPassword.value !== authConfirm.value) {
      authError.textContent = "The passwords do not match.";
      authConfirm.focus();
      return;
    }
    showSignupPinStep(true);
    return;
  }
  authSubmit.disabled = true;
  authUsePin.disabled = true;
  authError.textContent = "";
  try {
    const session = await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username: authUsername.value, password: authPassword.value }),
    });
    await useSession(session);
  } catch (error) {
    authError.textContent = error.message;
    if (error.status === 401) {
      authPassword.value = "";
      authPassword.focus();
    }
  } finally {
    authSubmit.disabled = false;
    authUsePin.disabled = false;
  }
});

async function createAccount(pin) {
  if (authPinSubmit.disabled || authPinForm.hidden) return;
  authPinSubmit.disabled = authPinSkip.disabled = true;
  authPinBack.disabled = true;
  authPinError.textContent = "";
  const credentials = { username: authUsername.value, password: authPassword.value };
  if (pin !== undefined) credentials.pin = pin;
  try {
    const session = await api("/api/auth/setup", { method: "POST", body: JSON.stringify(credentials) });
    await useSession(session);
  } catch (error) {
    if (error.status === 409) await checkAuthentication();
    else authPinError.textContent = error.message;
  } finally {
    authPinSubmit.disabled = authPinSkip.disabled = false;
    authPinBack.disabled = false;
  }
}

authPinForm.addEventListener("submit", (event) => {
  event.preventDefault();
  createAccount(authSignupPin.value);
});
authPinSkip.addEventListener("click", () => createAccount());
authPinBack.addEventListener("click", () => showSignupPinStep(false));
authUsePassword.addEventListener("click", () => showAuth("recover"));
authUsePin.addEventListener("click", () => showAuth("unlock"));
authUnlockForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (authUnlockSubmit.disabled || authUnlockForm.hidden) return;
  authUnlockSubmit.disabled = authUsePassword.disabled = true;
  authUnlockError.textContent = "";
  try {
    const session = await api("/api/auth/unlock", {
      method: "POST",
      body: JSON.stringify({ pin: authUnlockPin.value }),
    });
    await useSession(session);
  } catch (error) {
    if (error.status === 401) showAuth("login", expiredSessionMessage());
    else {
      authUnlockPin.value = "";
      authUnlockPin.focus();
      authUnlockError.textContent = error.message;
    }
  } finally {
    authUnlockSubmit.disabled = authUsePassword.disabled = false;
  }
});
$("#sign-out").addEventListener("click", (event) => {
  const button = event.currentTarget;
  navigate(async () => {
    button.disabled = true;
    try {
      await api("/api/auth/logout", { method: "POST" });
      window.location.reload();
    } finally {
      button.disabled = false;
    }
  });
});
for (const button of sectionToggles) {
  button.addEventListener("click", () => {
    const expanded = button.getAttribute("aria-expanded") === "false";
    setSectionExpanded(button, expanded);
    const key = sectionKey(button);
    sectionPreferences.set(key, String(expanded));
    try { window.localStorage.setItem(key, String(expanded)); } catch {}
  });
}
readButton.addEventListener("click", () => {
  if (state.navigating || editor.hidden) return;
  setNoteMode("read");
  saveNote();
});
editButton.addEventListener("click", () => {
  if (state.navigating) return;
  setNoteMode("edit");
  editor.focus();
});

document.querySelectorAll("[data-mode]").forEach((button) => {
  button.addEventListener("click", () => {
    if (state.mode !== button.dataset.mode) navigate(() => openSource(button.dataset.mode));
  });
});
$("#source-select").addEventListener("change", (event) => {
  const path = event.target.value;
  event.target.value = state.source;
  navigate(() => openSource(state.mode, path));
});
$("#client-search").addEventListener("input", () => {
  if (!state.source) return;
  if (state.mode === "knowledge") {
    renderTopics();
    renderMaterials();
  } else {
    renderClients();
  }
});
$("#back-to-materials").addEventListener("click", () => {
  setMobileView("sessions", materialList.querySelector(".active") ?? $("#selected-client"));
});
$("#new-session").addEventListener("click", async () => {
  if (await navigate(createSession)) editor.focus();
});
editor.addEventListener("input", scheduleSave);
$("#back-to-clients").addEventListener("click", () => {
  setMobileView("clients", clientList.querySelector(".active") ?? $("#panel-title"));
});
$("#back-to-notes").addEventListener("click", () => navigate(() => {
  const active = noteSections.querySelector(".session-list:not([hidden]) .active");
  setMobileView("sessions", active ?? $("#selected-client"));
}));
$("#new-client").addEventListener("click", () => { $("#client-dialog").showModal(); setTimeout(() => $("#client-name").focus(), 50); });
$("#dialog-close").addEventListener("click", () => $("#client-dialog").close());
$("#dialog-cancel").addEventListener("click", () => $("#client-dialog").close());
const settingsDialog = $("#settings-dialog");
function onSettingsBackdrop(event) {
  if (event.target !== settingsDialog) return false;
  const { left, top, right, bottom } = settingsDialog.getBoundingClientRect();
  return event.clientX < left || event.clientX > right || event.clientY < top || event.clientY > bottom;
}
let settingsPressOnBackdrop = false;
settingsDialog.addEventListener("pointerdown", (event) => {
  settingsPressOnBackdrop = onSettingsBackdrop(event);
});
settingsDialog.addEventListener("click", (event) => {
  if (settingsDialog.open && settingsPressOnBackdrop && onSettingsBackdrop(event)) settingsDialog.close();
  settingsPressOnBackdrop = false;
});
settingsDialog.addEventListener("close", () => {
  settingsPressOnBackdrop = false;
  clearTimeout(rootTimer);
  settingsDraft.request++;
  if (!settingsDialog.open) resetSecurityForm();
});
$("#open-settings").addEventListener("click", openSettings);
$("#settings-close").addEventListener("click", () => $("#settings-dialog").close());
$("#settings-cancel").addEventListener("click", () => $("#settings-dialog").close());
$("#settings-form").addEventListener("submit", changeVault);
securityForm.addEventListener("submit", changeSecurity);
securityEnabled.addEventListener("change", () => {
  if (!securityEnabled.checked) {
    securityDraft.changingPin = false;
    securityNewPin.value = "";
  }
  renderSecurityControls();
});
securityChangePin.addEventListener("click", () => {
  securityDraft.changingPin = !securityDraft.changingPin;
  securityNewPin.value = "";
  renderSecurityControls();
  if (securityDraft.changingPin) securityNewPin.focus();
});
$("#client-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const name = $("#client-name").value.trim();
  if (!name) return;
  navigate(async () => {
    await api(sourceApi("/api/clients"), { method: "POST", body: JSON.stringify({ name }) });
    $("#client-dialog").close();
    $("#client-name").value = "";
    await loadClients(name);
    setMobileView("sessions", $("#selected-client"));
    toast(`${name} added`);
  });
});
document.addEventListener("keydown", async (event) => {
  if (shell.hidden || document.querySelector("dialog[open]")) return;
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); $("#client-search").focus(); }
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") { event.preventDefault(); await saveNote(); }
});
for (const type of ["pointerdown", "pointermove", "keydown", "click", "input", "wheel"]) {
  window.addEventListener(type, recordActivity, { capture: true, passive: true });
}
window.addEventListener("blur", cancelActivityReport);
window.addEventListener("focus", checkWorkspaceSession);
window.addEventListener("pageshow", checkWorkspaceSession);
document.addEventListener("visibilitychange", () => {
  if (document.hidden) cancelActivityReport();
  else checkWorkspaceSession();
});
setInterval(checkWorkspaceSession, SESSION_CHECK_INTERVAL);
window.addEventListener("beforeunload", (event) => { if (state.dirty) { event.preventDefault(); event.returnValue = ""; } });

const closeDelete = initDeletion({
  api, navigate, targetFor: deletionTarget, requirePin: () => state.security.require_on_delete, refresh: refreshAfterDeletion,
});
initAppearance();
shell.dataset.mobileView = "clients";
checkAuthentication();

