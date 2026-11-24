import { initAppearance, setWorkspaceAppearance } from "./appearance.js";
import { renderMarkdown } from "./markdown.js";

const state = {
  clients: [],
  client: null,
  sessions: [],
  session: null,
  etag: null,
  saveTimer: null,
  dirty: false,
  saving: null,
  navigating: false,
  mode: "clients",
  source: null,
  sources: [],
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

function sourceApi(path, params = {}) {
  return `${path}?${new URLSearchParams({ source: state.source, ...params })}`;
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
  const knowledge = mode === "knowledge";
  const sources = modeSources(mode);
  Object.assign(state, {
    mode, source: path ?? null, client: null, session: null, etag: null,
    clients: [], sessions: [], topics: [], topic: null, material: null,
  });
  shell.dataset.mode = mode;
  setWorkspaceAppearance(mode);
  shell.dataset.mobileView = "clients";
  $(".clients-panel").setAttribute("aria-label", knowledge ? "Topics" : "Clients");
  $(".sessions-panel").setAttribute("aria-label", knowledge ? "Materials" : "Sessions");
  $("#back-to-clients").setAttribute("aria-label", knowledge ? "Back to topics" : "Back to clients");
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
  $("#session-count").textContent = "";
  sessionList.replaceChildren();
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
  if (switchView) shell.dataset.mobileView = "sessions";
  const materials = visibleMaterials(path);
  if (state.topic === path) {
    if (materials.length && !materials.some((item) => item.path === state.material)) {
      await selectMaterial(materials[0].path, false);
    }
    return;
  }
  state.topic = path;
  state.material = null;
  $("#selected-client").textContent = topicName(path);
  $("#selected-client").title = topicName(path);
  renderTopics();
  renderMaterials();
  showEmptyEditor();
  if (materials.length) await selectMaterial(materials[0].path, false);
}

function renderMaterials() {
  if (state.topic === null) return;
  const materials = visibleMaterials(state.topic);
  $("#session-count").textContent = countLabel(materials.length, "material");
  sessionList.replaceChildren(...materials.map((material) => {
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
  if (switchView) shell.dataset.mobileView = "editor";
}

async function navigate(action) {
  if (state.navigating) return;
  state.navigating = true;
  editor.readOnly = true;
  try {
    if (await saveNote()) await action();
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
    <button class="client-card ${client.name === state.client ? "active" : ""}" data-client="${escapeHtml(client.name)}">
      <span class="avatar" style="--avatar:${colorFor(client.name)}">${escapeHtml(client.initials)}</span>
      <span class="client-copy"><strong title="${escapeHtml(client.name)}">${escapeHtml(client.name)}</strong><span>${client.session_count} ${client.session_count === 1 ? "session" : "sessions"}</span></span>
      <span class="client-arrow">›</span>
    </button>`).join("");
  clientList.querySelectorAll("[data-client]").forEach((button) => button.addEventListener("click", () => navigate(() => selectClient(button.dataset.client))));
}

async function selectClient(name, switchView = true) {
  const result = await api(sourceApi(`/api/clients/${encode(name)}/sessions`));
  state.client = name;
  state.session = null;
  state.etag = null;
  renderClients();
  const client = state.clients.find((item) => item.name === name);
  $("#selected-client").textContent = name;
  $("#selected-client").title = name;
  $("#selected-avatar").textContent = client?.initials || "";
  $("#selected-avatar").style.setProperty("--avatar", colorFor(name));
  $("#new-session").disabled = false;
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
  sessionList.querySelectorAll("[data-session]").forEach((button) => button.addEventListener("click", () => navigate(() => selectSession(Number(button.dataset.session)))));
}

async function selectSession(number, switchView = true) {
  if (state.session === number && !$("#editor-workspace").classList.contains("hidden")) {
    if (switchView) shell.dataset.mobileView = "editor";
    return;
  }
  const note = await api(sourceApi(`/api/clients/${encode(state.client)}/sessions/${number}`));
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
  if (!state.dirty || !state.client || !state.session) return true;
  if (state.saving) return saveNote();
  state.saving = writeNote();
  return state.saving;
}

async function writeNote() {
  clearTimeout(state.saveTimer);
  const contentAtStart = editor.value;
  setSaveStatus("saving");
  try {
    const note = await api(sourceApi(`/api/clients/${encode(state.client)}/sessions/${state.session}`), {
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
    state.saving = null;
  }
}

async function createSession() {
  if (!state.client) return;
  try {
    const note = await api(sourceApi(`/api/clients/${encode(state.client)}/sessions`), { method: "POST", body: "{}" });
    const result = await api(sourceApi(`/api/clients/${encode(state.client)}/sessions`));
    state.sessions = result.sessions;
    state.session = null;
    renderSessions();
    await selectSession(note.number);
    editor.focus();
    toast(`Session ${note.number} created`);
  } catch (error) { toast(error.message); }
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
  try {
    const settings = await api("/api/settings");
    notesRoot.value = settings.notes_root;
    Object.assign(settingsDraft, {
      root: settings.notes_root, input: "", parent: ".", folders: null, sources: settings.sources,
    });
    settingsMessage();
    renderFolderSettings();
    activateSettingsTab($("#vault-tab"));
    $("#settings-dialog").showModal();
    $("#vault-tab").focus();
    await browseFolders();
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
$("#back-to-materials").addEventListener("click", () => { shell.dataset.mobileView = "sessions"; });
$("#new-session").addEventListener("click", () => navigate(createSession));
editor.addEventListener("input", scheduleSave);
$("#back-to-clients").addEventListener("click", () => shell.dataset.mobileView = "clients");
$("#back-to-sessions").addEventListener("click", () => navigate(() => { shell.dataset.mobileView = "sessions"; }));
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
});
$("#open-settings").addEventListener("click", openSettings);
$("#settings-close").addEventListener("click", () => $("#settings-dialog").close());
$("#settings-cancel").addEventListener("click", () => $("#settings-dialog").close());
$("#settings-form").addEventListener("submit", changeVault);
$("#client-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const name = $("#client-name").value.trim();
  if (!name) return;
  navigate(async () => {
    await api(sourceApi("/api/clients"), { method: "POST", body: JSON.stringify({ name }) });
    $("#client-dialog").close();
    $("#client-name").value = "";
    await loadClients(name);
    shell.dataset.mobileView = "sessions";
    toast(`${name} added`);
  });
});
document.addEventListener("keydown", async (event) => {
  if (document.querySelector("dialog[open]")) return;
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); $("#client-search").focus(); }
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") { event.preventDefault(); await saveNote(); }
});
window.addEventListener("beforeunload", (event) => { if (state.dirty) { event.preventDefault(); event.returnValue = ""; } });

initAppearance();
shell.dataset.mobileView = "clients";
navigate(async () => loadWorkspace(await api("/api/settings")));

