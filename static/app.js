// Wrapper for making GET requests to the backend with basic error handling
async function apiGet(url) {
  const r = await fetch(url);
  if (!r.ok) {
    let msg = await r.text();
    try {
      const j = JSON.parse(msg);
      if (j.detail) msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch(e) {}
    alert("Ошибка: " + msg);
    throw new Error(msg);
  }
  return r.json();
}

// Wrapper for making POST/PUT/DELETE requests to the backend
async function apiSend(url, method, bodyObj) {
  const r = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: bodyObj ? JSON.stringify(bodyObj) : undefined
  });
  if (!r.ok) {
    let msg = await r.text();
    try {
      const j = JSON.parse(msg);
      if (j.detail) msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch(e) {}
    alert("Ошибка: " + msg);
    throw new Error(msg);
  }
  return r.json();
}

// Prevent XSS attacks by escaping unsafe HTML characters
function escapeHtml(s) {
  return String(s)
    .replaceAll("&","&amp;")
    .replaceAll("<","&lt;")
    .replaceAll(">","&gt;")
    .replaceAll('"',"&quot;")
    .replaceAll("'","&#39;");
}

let i18n = {};
const currentLang = localStorage.getItem("lang") || "en";

// Loads language dictionary from static JSON file if not using English (default)
async function initLang() {
  if (currentLang !== "en") {
    try {
      const r = await fetch(`/static/${currentLang}.json`);
      if (r.ok) i18n = await r.json();
    } catch(e) {
      console.error("Failed to load language file", e);
    }
  }
}

// Translation helper: searches the loaded dictionary for the key, returns original if missing
function t(key) {
  if (typeof key !== "string") return key;
  // If the key exists in the dictionary, return the translation, otherwise return the original key
  return i18n[key] || key;
}

// Sort array of keys considering localization (alphabet of the current language)
function sortTranslated(items) {
  // localeCompare applies the sorting rules for the provided language (ru or en)
  return items.sort((a, b) => {
    // Handle both flat strings and arrays of objects gracefully
    const valA = (a && typeof a === 'object') ? (a.key || a.name || a.stat || a.id) : a;
    const valB = (b && typeof b === 'object') ? (b.key || b.name || b.stat || b.id) : b;
    
    const strA = String(t(valA));
    const strB = String(t(valB));
    
    // sensitivity: 'base' ignores case differences for accurate alphabetical sorting
    return strA.localeCompare(strB, currentLang, { sensitivity: 'base' });
  });
}

// Returns the corresponding hex color code for a given item rarity
function getRarityColor(rarity) {
  const colors = {
    "Zenith": "#2EE5B5",
    "Mythic": "#F4B43E",
    "Legend": "#9B59B6",
    "Epic": "#B92D4B",
    "Unique": "#3498DB",
    "Rare": "#27AE60",
    "Common": "#BDC3C7"
  };
  return colors[rarity] || "";
}

// Retrieves the saved UI theme from browser local storage
function getTheme() {
  return localStorage.getItem("theme") || "dark";
}

// Applies the CSS theme attribute to the main HTML document
function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme === "light" ? "light" : "dark");
  localStorage.setItem("theme", theme);
}

function toggleTheme() {
  const cur = getTheme();
  const next = (cur === "light") ? "dark" : "light";
  applyTheme(next);
  const btn = document.getElementById("themeBtn");
  if (btn) btn.textContent = next === "light" ? "Light" : "Dark";
}

function toggleLang() {
  localStorage.setItem("lang", currentLang === "en" ? "ru" : "en");
  location.reload();
}

// Generates the navigation header HTML
function navHtml() {
  const theme = getTheme();
  return `
  <header>
    <nav>
      <a href="/">${t("Home")}</a>
      <a href="/data">${t("Data")}</a>
      <a href="/inventory">${t("My Items")}</a>
      <a href="/finder">Finder</a>
      <span style="flex:1;"></span>
      <button id="themeBtn" type="button">${theme === "light" ? "Light" : "Dark"}</button>
      <button id="langBtn" type="button" style="margin-left: 8px;">${currentLang === "en" ? "EN" : "RU"}</button>
    </nav>
  </header>`;
}

// Initializes application globals: translations, themes, and navigation bar
async function mountNav() {
  await initLang();
  applyTheme(getTheme());
  const nav = document.getElementById("nav");
  if (nav) nav.innerHTML = navHtml();
  const btn = document.getElementById("themeBtn");
  if (btn) btn.onclick = toggleTheme;
  const langBtn = document.getElementById("langBtn");
  if (langBtn) langBtn.onclick = toggleLang;
}

// Triggers a browser download of the user's inventory encoded as JSON
async function doExportOwned() {
  try {
    const data = await apiGet('/api/export_owned');
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'l2m_owned_inventory.json';
    a.click();
    URL.revokeObjectURL(url);
  } catch (err) {
    console.error(err);
  }
}

// Uploads a user inventory JSON file and sends it to the backend to update `owned.db`
async function doImportOwned(file) {
  if (!file) return;
  try {
    const text = await file.text();
    const json = JSON.parse(text);
    if (!json.owned) {
      alert("Неверный формат файла: отсутствует массив 'owned'.");
      return;
    }
    
    const result = await apiSend('/api/import_owned', 'POST', json);
    if (result.ok) {
      alert(`Инвентарь успешно импортирован! Загружено предметов: ${result.imported_owned}`);
      location.reload();
    }
  } catch (err) {
    console.error(err);
    alert("Ошибка импорта инвентаря. Проверьте консоль.");
  }
}
