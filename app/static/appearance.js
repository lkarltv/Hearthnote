import { isDaylight } from "./sunlight.js";

const storageKey = "hearthnote.appearance";
const modes = ["light", "dark", "auto"];
const workspaces = ["clients", "knowledge"];
const defaultPalettes = {
  light: { clients: "default", knowledge: "default" },
  dark: { clients: "one-dark-pro", knowledge: "nord" },
};

// Sidebar, middle column, reading surface, text, secondary text, and accent.
// The original theme sources are listed in the README.
const themes = {
  "one-dark-pro": ["One Dark Pro", "dark", "#21252b", "#252931", "#282c34", "#abb2bf", "#a0a8b7", "#61afef"],
  dracula: ["Dracula", "dark", "#21222c", "#282a36", "#282a36", "#f8f8f2", "#b6b8d0", "#bd93f9"],
  "github-dark": ["GitHub Dark Default", "dark", "#010409", "#161b22", "#0d1117", "#e6edf3", "#9da7b3", "#58a6ff"],
  "github-light": ["GitHub Light Default", "light", "#eaeef2", "#f6f8fa", "#ffffff", "#24292f", "#57606a", "#0969da"],
  "night-owl": ["Night Owl", "dark", "#01111d", "#011627", "#011627", "#d6deeb", "#a4b6cf", "#82aaff"],
  "tokyo-night": ["Tokyo Night", "dark", "#16161e", "#1f2335", "#1a1b26", "#c0caf5", "#a9b1d6", "#7aa2f7"],
  "catppuccin-mocha": ["Catppuccin Mocha", "dark", "#181825", "#1e1e2e", "#1e1e2e", "#cdd6f4", "#a6adc8", "#cba6f7"],
  "catppuccin-latte": ["Catppuccin Latte", "light", "#dce0e8", "#e6e9ef", "#eff1f5", "#4c4f69", "#5c5f77", "#8839ef"],
  "gruvbox-dark": ["Gruvbox Dark", "dark", "#1d2021", "#32302f", "#282828", "#ebdbb2", "#bdae93", "#fabd2f"],
  nord: ["Nord", "dark", "#2e3440", "#3b4252", "#2e3440", "#eceff4", "#d8dee9", "#88c0d0"],
  monokai: ["Monokai", "dark", "#1e1f1c", "#33342e", "#272822", "#f8f8f2", "#c5c8b3", "#a6e22e"],
  "solarized-light": ["Solarized Light", "light", "#e6dec7", "#eee8d5", "#fdf6e3", "#073642", "#4d6269", "#106cae"],
};

const themeProperties = ["color-scheme", "--panel", "--surface", "--paper", "--ink", "--muted", "--accent"];
const defaultPreviews = {
  clients: ["#ebe6dc", "#f8f5ef", "#fffefa", "#24251f", "#66685f", "#d56c4b"],
  knowledge: ["#e7ece4", "#f1f4ed", "#fdfef9", "#40594b", "#66685f", "#617868"],
};

function validLocation(location) {
  return Number.isFinite(location?.latitude) && Math.abs(location.latitude) <= 90
    && Number.isFinite(location.longitude) && Math.abs(location.longitude) <= 180;
}

function matchesScheme(theme, scheme) {
  return (scheme === "light" && theme === "default")
    || (Object.hasOwn(themes, theme) && themes[theme][1] === scheme);
}

function loadPreferences() {
  let saved;
  try {
    saved = JSON.parse(localStorage.getItem(storageKey));
  } catch {
    saved = null;
  }
  const palettes = structuredClone(defaultPalettes);
  for (const scheme of ["light", "dark"]) {
    for (const workspace of workspaces) {
      const theme = saved?.palettes?.[scheme]?.[workspace] ?? saved?.[workspace];
      if (matchesScheme(theme, scheme)) palettes[scheme][workspace] = theme;
    }
  }
  const legacyTheme = saved?.clients ?? saved?.knowledge;
  const legacyMode = matchesScheme(legacyTheme, "dark") ? "dark" : "light";
  return {
    mode: modes.includes(saved?.mode) ? saved.mode : legacyMode,
    palettes,
    shortcuts: ["auto", "mac", "pc"].includes(saved?.shortcuts) ? saved.shortcuts : "auto",
    location: validLocation(saved?.location) ? saved.location : null,
  };
}

const preferences = loadPreferences();
let workspace = "clients";

function applyAppearance() {
  const scheme = preferences.mode === "auto"
    ? (isDaylight(new Date(), preferences.location) ? "light" : "dark")
    : preferences.mode;
  const theme = preferences.palettes[scheme][workspace];
  const colors = themes[theme]?.slice(1) || [];
  const body = document.body;
  if (body.dataset.workspace === workspace && body.dataset.theme === theme) return;
  body.dataset.workspace = workspace;
  body.dataset.theme = theme;
  body.dataset.colorScheme = scheme;
  for (const [index, property] of themeProperties.entries()) {
    const value = colors[index];
    if (value) body.style.setProperty(property, value);
    else body.style.removeProperty(property);
  }
}

export function setWorkspaceAppearance(nextWorkspace) {
  workspace = nextWorkspace;
  applyAppearance();
}

function updateShortcutHints() {
  const platform = navigator.userAgentData?.platform || navigator.platform || "";
  const mac = preferences.shortcuts === "mac" || (preferences.shortcuts === "auto" && /^Mac/i.test(platform));
  document.querySelectorAll("[data-shortcut-key]").forEach((hint) => {
    const key = hint.dataset.shortcutKey;
    hint.textContent = mac ? `⌘ ${key}` : `Ctrl + ${key}`;
  });
}

function updatePreview(preview, workspaceName, theme) {
  const [panel, middle, paper, ink, , accent] = themes[theme]?.slice(2) || defaultPreviews[workspaceName];
  const colors = [panel, middle, paper, ink, accent];
  ["--preview-panel", "--preview-middle", "--preview-paper", "--preview-ink", "--preview-accent"]
    .forEach((property, index) => preview.style.setProperty(property, colors[index]));
}

function savePreferences() {
  try {
    localStorage.setItem(storageKey, JSON.stringify(preferences));
  } catch {
    document.getElementById("appearance-status").textContent = "Browser storage is unavailable. Changes apply for this visit.";
  }
}

function initPalette(scheme) {
  const template = document.getElementById("theme-palette-template");
  const panel = template.content.cloneNode(true);
  const title = scheme === "light" ? "Light" : "Dark";
  panel.querySelector("legend").textContent = `${title} palettes`;
  for (const [index, choice] of [...panel.querySelectorAll(".theme-choice")].entries()) {
    const workspaceName = workspaces[index];
    const label = workspaceName === "clients" ? "Clients" : "Knowledge";
    const picker = choice.querySelector("select");
    const preview = choice.querySelector(".theme-preview");
    picker.setAttribute("aria-label", `${label} ${scheme} theme`);
    if (scheme === "light") picker.append(new Option("Hearthnote (default)", "default"));
    for (const [id, [name, themeScheme]] of Object.entries(themes)) {
      if (themeScheme === scheme) picker.append(new Option(name, id));
    }
    picker.value = preferences.palettes[scheme][workspaceName];
    picker.addEventListener("change", () => {
      preferences.palettes[scheme][workspaceName] = picker.value;
      savePreferences();
      updatePreview(preview, workspaceName, picker.value);
      applyAppearance();
    });
    updatePreview(preview, workspaceName, picker.value);
  }
  document.getElementById("theme-palettes").append(panel);
}

function initLocation() {
  const latitude = document.getElementById("sun-latitude");
  const longitude = document.getElementById("sun-longitude");
  const locate = document.getElementById("sun-use-location");
  const clear = document.getElementById("sun-clear-location");
  const status = document.getElementById("sun-location-status");

  function updateLocationFields() {
    latitude.value = preferences.location?.latitude ?? "";
    longitude.value = preferences.location?.longitude ?? "";
    clear.disabled = !preferences.location;
    status.textContent = preferences.location
      ? "Location saved. Auto follows local sunrise and sunset."
      : "Until you set a location, Auto uses light mode from 07:00 to 19:00 device time.";
  }

  function storeLocation(location) {
    preferences.location = location;
    savePreferences();
    updateLocationFields();
    applyAppearance();
  }

  document.getElementById("sun-location-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const location = { latitude: latitude.valueAsNumber, longitude: longitude.valueAsNumber };
    if (validLocation(location)) storeLocation(location);
  });
  clear.addEventListener("click", () => storeLocation(null));
  locate.hidden = !window.isSecureContext || !navigator.geolocation;
  locate.addEventListener("click", () => {
    locate.disabled = true;
    status.textContent = "Looking up your location…";
    navigator.geolocation.getCurrentPosition(({ coords }) => {
      locate.disabled = false;
      storeLocation({
        latitude: Math.round(coords.latitude * 100) / 100,
        longitude: Math.round(coords.longitude * 100) / 100,
      });
    }, () => {
      locate.disabled = false;
      status.textContent = "Location is unavailable. Enter latitude and longitude manually.";
    }, { timeout: 10_000, maximumAge: 3_600_000 });
  });
  updateLocationFields();
}

export function initAppearance() {
  initPalette("light");
  initPalette("dark");
  initLocation();
  const buttons = document.querySelectorAll("[data-color-mode]");
  function markSelectedMode() {
    for (const button of buttons) {
      button.setAttribute("aria-pressed", String(button.dataset.colorMode === preferences.mode));
    }
  }
  for (const button of buttons) {
    button.addEventListener("click", () => {
      preferences.mode = button.dataset.colorMode;
      savePreferences();
      markSelectedMode();
      applyAppearance();
    });
  }
  const shortcuts = document.getElementById("shortcut-style");
  shortcuts.value = preferences.shortcuts;
  shortcuts.addEventListener("change", () => {
    preferences.shortcuts = shortcuts.value;
    savePreferences();
    updateShortcutHints();
  });
  markSelectedMode();
  applyAppearance();
  updateShortcutHints();

  function refreshAuto() {
    if (preferences.mode === "auto" && !document.hidden) applyAppearance();
  }
  setInterval(refreshAuto, 30_000);
  document.addEventListener("visibilitychange", refreshAuto);
  window.addEventListener("pageshow", refreshAuto);
}
