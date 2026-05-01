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

function t(key) {
  if (typeof key !== "string") return key;
  // Если ключ есть в словаре - возвращаем перевод, иначе оригинальный ключ
  return i18n[key] || key;
}

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

function getTheme() {
  return localStorage.getItem("theme") || "dark";
}

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
