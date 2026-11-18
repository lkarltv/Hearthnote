(() => {
  const themeKey = "hearthnote.theme";
  const shortcutKey = "hearthnote.shortcuts";
  const themes = new Set(["hearthnote", "solarized-light", "solarized-dark", "tokyo-night", "nord"]);
  const root = document.documentElement;

  function preference(key) {
    try { return localStorage.getItem(key); } catch { return null; }
  }

  function remember(key, value) {
    try { localStorage.setItem(key, value); } catch {}
  }

  const savedTheme = preference(themeKey);
  root.dataset.theme = themes.has(savedTheme) ? savedTheme : "hearthnote";

  document.addEventListener("DOMContentLoaded", () => {
    const settings = document.getElementById("settings");
    const toggle = document.getElementById("settings-toggle");
    const dropdown = document.getElementById("settings-dropdown");
    const theme = document.getElementById("theme-setting");
    const shortcuts = document.getElementById("shortcut-setting");
    const themeColor = document.querySelector('meta[name="theme-color"]');
    const shortcutHints = document.querySelectorAll("[data-shortcut-modifier]");
    const platform = navigator.userAgentData?.platform || navigator.platform;
    const defaultShortcuts = /mac|iphone|ipad|ipod/i.test(platform) ? "mac" : "pc";
    const savedShortcuts = preference(shortcutKey);

    function updateBrowserColor() {
      themeColor.content = getComputedStyle(root).getPropertyValue("--canvas").trim();
    }

    function updateShortcutLabels() {
      shortcutHints.forEach((hint) => {
        hint.textContent = shortcuts.value === "mac" ? "⌘" : "Ctrl";
      });
    }

    function setDropdown(open) {
      dropdown.hidden = !open;
      toggle.setAttribute("aria-expanded", String(open));
    }

    theme.value = root.dataset.theme;
    shortcuts.value = ["pc", "mac"].includes(savedShortcuts) ? savedShortcuts : defaultShortcuts;
    updateBrowserColor();
    updateShortcutLabels();

    theme.addEventListener("change", () => {
      root.dataset.theme = theme.value;
      updateBrowserColor();
      remember(themeKey, theme.value);
    });
    shortcuts.addEventListener("change", () => {
      updateShortcutLabels();
      remember(shortcutKey, shortcuts.value);
    });
    toggle.addEventListener("click", () => setDropdown(dropdown.hidden));
    function closeOutside(event) {
      if (!dropdown.hidden && !settings.contains(event.target)) setDropdown(false);
    }
    document.addEventListener("click", closeOutside);
    document.addEventListener("focusin", closeOutside);
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !dropdown.hidden) {
        event.preventDefault();
        setDropdown(false);
        toggle.focus();
      }
    });
  });
})();
