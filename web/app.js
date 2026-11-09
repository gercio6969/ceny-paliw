"use strict";
// Ceny paliw – aplikacja PWA. Autor: Gerard Modlewski. Licencja MIT.

const DATA_URL = "data/prices.json";
const SVG_NS = "http://www.w3.org/2000/svg";
const FUELS = [
  { key: "pb95", badge: "95", short: "benzyna", name: "Benzyna bezołowiowa 95", color: "var(--pb95)" },
  { key: "pb98", badge: "98", short: "benzyna", name: "Benzyna bezołowiowa 98", color: "var(--pb98)" },
  { key: "on", badge: "ON", short: "diesel", name: "Olej napędowy", color: "var(--on)" },
];
const HISTORY_POINTS = 30;

const $ = (id) => document.getElementById(id);
const fmtPrice = new Intl.NumberFormat("pl-PL", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtDate = new Intl.DateTimeFormat("pl-PL", { weekday: "long", day: "numeric", month: "long" });
const fmtShort = new Intl.DateTimeFormat("pl-PL", { day: "numeric", month: "short" });
const fmtTime = new Intl.DateTimeFormat("pl-PL", { dateStyle: "short", timeStyle: "short" });
const fmtWeekday = new Intl.DateTimeFormat("pl-PL", { weekday: "short", day: "numeric", month: "numeric" });
const fmtRate = new Intl.NumberFormat("pl-PL", { minimumFractionDigits: 4, maximumFractionDigits: 4 });
const fmtPct = new Intl.NumberFormat("pl-PL", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const MARKET_URL = "data/market.json";

let state = { data: null, fuel: loadFuelPreference() };

function loadFuelPreference() {
  try {
    const saved = localStorage.getItem("fuel");
    return FUELS.some((f) => f.key === saved) ? saved : "pb95";
  } catch {
    return "pb95";
  }
}

function saveFuelPreference(key) {
  try {
    localStorage.setItem("fuel", key);
  } catch {
    /* tryb prywatny – pomijamy */
  }
}

/** Data ISO (YYYY-MM-DD) jako lokalna północ, bez przesunięć strefy czasowej. */
function parseDay(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "text") node.textContent = v;
    else if (k === "style") node.style.cssText = v;
    else node.setAttribute(k, v);
  }
  for (const child of [].concat(children)) if (child) node.append(child);
  return node;
}

function svg(tag, attrs = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}

function deltaNode(current, previous, inline = false) {
  const base = inline ? "delta inline" : "delta";
  if (previous == null) return el("span", { class: base, text: "—" });
  const diff = Math.round((current - previous) * 100); // w groszach
  if (diff === 0) return el("span", { class: base, text: inline ? "=" : "bez zmian" });
  const sign = diff > 0 ? "▲ +" : "▼ −";
  return el("span", {
    class: `${base} ${diff > 0 ? "up" : "down"}`,
    text: `${sign}${Math.abs(diff)} gr`,
  });
}

/** Zmiana procentowa dla danych rynkowych. */
function pctNode(value, previous) {
  if (!isNum(previous) || previous === 0) return el("span", { class: "delta", text: "" });
  const pct = ((value - previous) / previous) * 100;
  if (Math.abs(pct) < 0.005) return el("span", { class: "delta", text: "0,00%" });
  return el("span", {
    class: `delta ${pct > 0 ? "up" : "down"}`,
    text: `${pct > 0 ? "▲ +" : "▼ −"}${fmtPct.format(Math.abs(pct))}%`,
  });
}

function sparkline(history, color) {
  if (!Array.isArray(history)) return null;
  const values = history.map((point) => point?.[1]).filter(isNum);
  if (values.length < 2) return null;
  const w = 100;
  const h = 28;
  const min = Math.min(...values);
  const span = Math.max(...values) - min || 1;
  const d = values
    .map((v, i) => `${i ? "L" : "M"}${((i / (values.length - 1)) * w).toFixed(1)},${(h - 2 - ((v - min) / span) * (h - 4)).toFixed(1)}`)
    .join("");
  const node = svg("svg", { class: "spark", viewBox: `0 0 ${w} ${h}`, preserveAspectRatio: "none", "aria-hidden": "true" });
  node.style.setProperty("--fuel", color);
  node.append(svg("path", { d, "vector-effect": "non-scaling-stroke" }));
  return node;
}

function tile({ label, value, unit, sub, change, spark, date, stale }) {
  return el("div", { class: `tile${stale ? " stale" : ""}` }, [
    el("span", { class: "tile-label", text: label }),
    el("span", { class: "tile-value" }, [value, el("span", { class: "price-unit", text: unit })]),
    sub ? el("span", { class: "tile-sub", text: sub }) : null,
    change,
    spark,
    el("span", {
      class: "tile-date",
      text: date ? `${stale ? "nieaktualne · " : ""}${fmtShort.format(parseDay(date))}` : "",
    }),
  ]);
}

function renderMarket(market) {
  const items = market?.items ?? {};
  const tiles = [];
  const ok = (item) => item && isNum(item.value);
  const { brent, usdpln, orlen_wholesale: hurt, orlen_shares: shares } = items;

  if (ok(brent)) {
    tiles.push(tile({
      label: "Ropa Brent",
      value: fmtPrice.format(brent.value),
      unit: "$/bbl",
      sub: isNum(brent.value_pln) ? `${fmtPrice.format(brent.value_pln)} zł za baryłkę` : null,
      change: pctNode(brent.value, brent.previous),
      spark: sparkline(brent.history ?? [], "var(--digit)"),
      date: brent.date,
      stale: brent.stale,
    }));
  }
  if (ok(usdpln)) {
    tiles.push(tile({
      label: "Kurs USD/PLN (NBP)",
      value: fmtRate.format(usdpln.value),
      unit: "zł",
      change: pctNode(usdpln.value, usdpln.previous),
      spark: sparkline(usdpln.history ?? [], "var(--pb98)"),
      date: usdpln.date,
      stale: usdpln.stale,
    }));
  }
  if (hurt?.products) {
    for (const fuel of FUELS) {
      const p = hurt.products[fuel.key];
      if (!ok(p) || fuel.key === "pb98") continue; // 95 i ON wystarczą na telefon
      tiles.push(tile({
        label: `Hurt ORLEN ${fuel.badge}`,
        value: fmtPrice.format(p.value),
        unit: "zł/l",
        sub: "netto, bez VAT",
        date: p.date,
        stale: hurt.stale,
      }));
    }
  }
  if (ok(shares)) {
    tiles.push(tile({
      label: "Akcje ORLEN",
      value: fmtPrice.format(shares.value),
      unit: "zł",
      change: pctNode(shares.value, shares.previous),
      spark: sparkline(shares.history ?? [], "var(--pb95)"),
      date: shares.date,
      stale: shares.stale,
    }));
  }

  $("market-section").hidden = tiles.length === 0;
  $("market").replaceChildren(...tiles);
}

const SOURCE_ORIGINS = ["https://monitorpolski.gov.pl", "https://api.sejm.gov.pl"];

/** Link do źródła tylko w obrębie API Sejmu – nawet gdyby plik danych został podmieniony. */
function safeSourceUrl(value) {
  try {
    const url = new URL(value);
    if (SOURCE_ORIGINS.includes(url.origin)) return url.href;
  } catch {
    /* nieprawidłowy URL */
  }
  return "https://monitorpolski.gov.pl/MP";
}

const isNum = (v) => typeof v === "number" && Number.isFinite(v);

function startOfToday() {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return today;
}

/** Relatywna nazwa dnia: „jutro” albo nazwa dnia tygodnia. */
function dayLabel(day) {
  const diff = Math.round((day - startOfToday()) / 86400000);
  if (diff === 1) return "jutro";
  return fmtWeekday.format(day);
}

/**
 * Dzieli historię (od najnowszego) na obwieszczenie obowiązujące dziś,
 * poprzednie (do porównania) i ogłoszone na kolejne dni.
 */
function splitByToday(history) {
  const today = startOfToday();
  const upcoming = history.filter((n) => parseDay(n.valid_from) > today).reverse();
  const pastIndex = history.findIndex((n) => parseDay(n.valid_from) <= today);
  // Brak obwieszczenia sprzed dziś (np. tylko jedno, na jutro) – pokaż najstarsze znane.
  const currentIndex = pastIndex === -1 ? history.length - 1 : pastIndex;
  return {
    current: history[currentIndex],
    previous: history[currentIndex + 1],
    upcoming: pastIndex === -1 ? upcoming.slice(1) : upcoming,
  };
}

/**
 * Cena na jutro dla danego paliwa:
 *  - z obwieszczenia ogłoszonego na jutro, jeśli już jest,
 *  - w sobotę i niedzielę z obwieszczenia obowiązującego dziś (piątkowe obowiązuje
 *    do poniedziałku włącznie, a poniedziałkowe dopiero od wtorku),
 *  - w pozostałe dni nieznana, dopóki minister nie ogłosi nowej.
 */
function tomorrowInfo(data) {
  const { current, upcoming } = splitByToday(data.history);
  const tomorrow = new Date(startOfToday());
  tomorrow.setDate(tomorrow.getDate() + 1);
  const next = upcoming.find((n) => parseDay(n.valid_from) <= tomorrow);
  if (next) return { notice: next, state: "announced", day: tomorrow };
  const weekend = [0, 6].includes(startOfToday().getDay());
  if (weekend) return { notice: current, state: "unchanged", day: tomorrow };
  return { notice: null, state: "pending", day: tomorrow };
}

function renderPylon(data) {
  const { current, previous } = splitByToday(data.history);
  const tm = tomorrowInfo(data);
  const today = startOfToday();

  const head = el("div", { class: "cols" }, [
    el("span"),
    el("span", { class: "col-head" }, ["Dziś", el("small", { text: fmtWeekday.format(today) })]),
    el("span", { class: "col-head next-head" }, [
      "Jutro",
      el("small", { text: fmtWeekday.format(tm.day) }),
    ]),
  ]);

  const rows = FUELS.map((fuel) => {
    const p = current.prices[fuel.key];
    if (!p) return null;
    const t = tm.notice?.prices[fuel.key];

    let tomorrowCell;
    if (tm.state === "pending" || !t) {
      tomorrowCell = el("div", { class: "price next pending" }, [
        el("span", { class: "price-value", text: "—" }),
        el("span", { class: "delta", text: "czeka na obwieszczenie" }),
      ]);
    } else {
      tomorrowCell = el("div", { class: "price next" }, [
        el("span", { class: "price-value", text: fmtPrice.format(t.gross) }),
        tm.state === "unchanged"
          ? el("span", { class: "delta", text: "bez zmian" })
          : deltaNode(t.gross, p.gross),
      ]);
    }

    return el("div", { class: "row", "data-fuel": fuel.key, style: `--fuel: ${fuel.color}` }, [
      el("div", { class: "fuel" }, [
        el("span", { class: "badge", text: fuel.badge }),
        el("span", { class: "fuel-short", text: fuel.short }),
      ]),
      el("div", { class: "price today" }, [
        el("span", { class: "price-value", text: fmtPrice.format(p.gross) }),
        deltaNode(p.gross, previous?.prices[fuel.key]?.gross),
        el("span", { class: "net", text: `netto ${fmtPrice.format(p.net)}` }),
      ]),
      tomorrowCell,
    ]);
  });
  $("pylon").replaceChildren(head, ...rows.filter(Boolean));
}

function renderValidity(data) {
  const tm = tomorrowInfo(data);
  const texts = {
    announced: "Ceny na jutro już ogłoszone.",
    unchanged: "W weekend obowiązują ceny z piątkowego obwieszczenia.",
    pending: "Ceny na jutro jeszcze nieogłoszone – sprawdzamy co 20 minut.",
  };
  $("validity").textContent = `Ceny maksymalne w zł/l. ${texts[tm.state]}`;

  const newest = data.latest;
  $("source-link").href = safeSourceUrl(newest.source_url);
  $("source-link").textContent = `Źródło: Monitor Polski ${newest.eli.replace("MP/", "").replace("/", " poz. ")}`;
  $("updated").textContent = `sprawdzono ${fmtTime.format(new Date(data.updated_at))}`;
}

function renderTabs() {
  const tabs = FUELS.map((fuel) => {
    const button = el("button", {
      class: "tab",
      type: "button",
      role: "tab",
      "aria-selected": String(fuel.key === state.fuel),
      text: fuel.badge,
    });
    button.addEventListener("click", () => {
      state.fuel = fuel.key;
      saveFuelPreference(fuel.key);
      renderTabs();
      renderHistory(state.data);
    });
    return button;
  });
  $("tabs").replaceChildren(...tabs);
}

function renderHistory(data) {
  const fuel = FUELS.find((f) => f.key === state.fuel);
  const points = data.history
    .filter((n) => n.prices[fuel.key])
    .slice(0, HISTORY_POINTS)
    .reverse()
    .map((n) => ({ day: parseDay(n.valid_from), value: n.prices[fuel.key].gross }));

  $("history-section").hidden = points.length === 0;
  if (points.length === 0) return;

  // wykres
  const chart = $("chart");
  chart.style.setProperty("--fuel", fuel.color);
  const width = chart.clientWidth || 480;
  const height = 150;
  const pad = { top: 16, right: 14, bottom: 22, left: 44 };
  chart.setAttribute("viewBox", `0 0 ${width} ${height}`);

  const values = points.map((p) => p.value);
  let min = Math.min(...values);
  let max = Math.max(...values);
  if (max - min < 0.1) {
    min -= 0.05;
    max += 0.05;
  }
  const x = (i) =>
    pad.left + (points.length === 1 ? 0.5 : i / (points.length - 1)) * (width - pad.left - pad.right);
  const y = (v) => pad.top + (1 - (v - min) / (max - min)) * (height - pad.top - pad.bottom);

  const nodes = [];
  for (const v of [max, (min + max) / 2, min]) {
    nodes.push(svg("line", { class: "grid", x1: pad.left, x2: width - pad.right, y1: y(v), y2: y(v) }));
    const label = svg("text", { x: pad.left - 6, y: y(v) + 4, "text-anchor": "end" });
    label.textContent = fmtPrice.format(v);
    nodes.push(label);
  }
  const line = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join("");
  const baseY = height - pad.bottom;
  nodes.push(svg("path", { class: "area", d: `${line}L${x(points.length - 1)},${baseY}L${x(0)},${baseY}Z` }));
  nodes.push(svg("path", { class: "line", d: line }));
  for (const [i, anchor] of [[0, "start"], [points.length - 1, "end"]]) {
    const label = svg("text", { x: x(i), y: height - 6, "text-anchor": anchor });
    label.textContent = fmtShort.format(points[i].day);
    nodes.push(label);
  }
  chart.replaceChildren(...nodes);

  // lista ostatnich zmian
  const items = points
    .slice()
    .reverse()
    .slice(0, 7)
    .map((p) =>
      el("li", {}, [
        el("span", { text: fmtDate.format(p.day) }),
        el("span", { class: "val", text: `${fmtPrice.format(p.value)} zł` }),
      ]),
    );
  $("history-list").replaceChildren(...items);
}

function render(data) {
  if (!data?.latest) {
    $("validity").textContent = "Brak danych – czekam na pierwsze obwieszczenie.";
    return;
  }
  state.data = data;
  renderValidity(data);
  renderPylon(data);
  renderTabs();
  renderHistory(data);
}

async function load() {
  const button = $("refresh");
  button.classList.add("spinning");
  $("error").hidden = true;
  try {
    const response = await fetch(DATA_URL, { cache: "no-cache" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    $("offline").hidden = response.headers.get("X-Served-From") !== "cache";
    render(await response.json());
  } catch (error) {
    $("error").textContent = `Nie udało się pobrać cen (${error.message}).`;
    $("error").hidden = false;
  } finally {
    button.classList.remove("spinning");
  }
  loadMarket(); // niezależnie od cen paliw; błąd tylko ukrywa sekcję
}

async function loadMarket() {
  try {
    const response = await fetch(MARKET_URL, { cache: "no-cache" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    renderMarket(await response.json());
  } catch {
    $("market-section").hidden = true;
  }
}

function setupInstallHints() {
  const standalone =
    window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
  const isIos = /iphone|ipad|ipod/i.test(navigator.userAgent);
  $("install-ios").hidden = standalone || !isIos;

  let deferredPrompt = null;
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    deferredPrompt = event;
    $("install-android").hidden = false;
  });
  $("install-android").addEventListener("click", async () => {
    if (!deferredPrompt) return;
    deferredPrompt.prompt();
    await deferredPrompt.userChoice;
    deferredPrompt = null;
    $("install-android").hidden = true;
  });
}

$("pylon").append(el("div", { class: "skeleton", text: "Wczytywanie cen…" }));
$("refresh").addEventListener("click", load);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") load();
});
window.addEventListener("resize", () => state.data && renderHistory(state.data));
setupInstallHints();
load();

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("sw.js").catch((error) => console.warn("SW:", error));
}
