const CHECK_KEY = "kyhi-checklist-v1";
const DEFAULT_LAT = 37.87;
const DEFAULT_LON = -122.23;
const DEFAULT_PLACE = "Berkeley hills";

const TIER_LABELS = {
  low: "Low",
  moderate: "Moderate",
  elevated: "Elevated",
  high: "High",
  extreme: "Extreme",
};

const INSURABILITY = {
  Low: (place) =>
    `${place} is in a quieter fire-weather stretch, so a carrier is less likely to treat this week as a reason to hesitate.`,
  Moderate: (place) =>
    `${place} has enough heat, wind, or dryness that an agent would look twice, though many homes here are still written.`,
  Elevated: (place) =>
    `${place} sits in a window where wildfire weather can make a new policy harder to place or renew.`,
  High: (place) =>
    `${place} sits in a window where wildfire weather can make a new policy harder to place or renew.`,
  Extreme: (place) =>
    `${place} is in the kind of fire-weather window where many carriers pause new homes or decline to renew.`,
};

const page = document.querySelector("#page");
const addressInput = document.querySelector("#address");
const outageInput = document.querySelector("#outage");
const form = document.querySelector("#lookup");
const statusEl = document.querySelector("#status");
const errorEl = document.querySelector("#error");
const examplesEl = document.querySelector("#examples");
const checklistEl = document.querySelector("#checklist");
const checklistWrap = document.querySelector("#checklist-wrap");
const legendEl = document.querySelector("#legend");

const placeEl = document.querySelector("#place");
const coordsEl = document.querySelector("#coords");
const tierEl = document.querySelector("#tier");
const tierMetaEl = document.querySelector("#tier-meta");
const takeawayEl = document.querySelector("#takeaway");
const daysEl = document.querySelector("#days");
const fosbergScoreEl = document.querySelector("#fosberg-score");
const fosbergBarEl = document.querySelector("#fosberg-bar");
const breakdownEl = document.querySelector("#breakdown");
const notesEl = document.querySelector("#notes");
const footEl = document.querySelector("#foot");

let checklist = [];
let report = null;
let selectedDay = null;
let globe = null;

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

function reducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function formatCoords(lat, lon) {
  const ns = lat >= 0 ? "N" : "S";
  const ew = lon >= 0 ? "E" : "W";
  return `${Math.abs(lat).toFixed(2)}° ${ns} \u00a0 ${Math.abs(lon).toFixed(2)}° ${ew}`;
}

function nearBay(lat, lon) {
  return Math.abs(lat - 37.95) < 1.15 && Math.abs(lon + 122.25) < 1.15;
}

function checks() {
  try {
    return new Set(JSON.parse(localStorage.getItem(CHECK_KEY) || "[]"));
  } catch {
    return new Set();
  }
}

function saveChecks(set) {
  localStorage.setItem(CHECK_KEY, JSON.stringify([...set]));
}

function tierKey(name) {
  return String(name || "").trim().toLowerCase();
}

function component(day, key) {
  return (day?.breakdown || []).find((item) => item.key === key) || null;
}

function activeDay() {
  const days = report?.days || [];
  return days.find((day) => day.date === selectedDay) || days[0] || null;
}

function fitGlobe() {
  if (!globe) return;
  const el = document.querySelector("#globe");
  globe.width(el.clientWidth);
  globe.height(el.clientHeight);
}

function mountGlobe() {
  const el = document.querySelector("#globe");
  if (!el || typeof Globe !== "function") return;
  try {
    globe = Globe()
      .width(el.clientWidth)
      .height(Math.max(el.clientHeight, 280))
      .backgroundColor("rgba(0,0,0,0)")
      .globeImageUrl("https://unpkg.com/three-globe/example/img/earth-blue-marble.jpg")
      .bumpImageUrl("https://unpkg.com/three-globe/example/img/earth-topology.png")
      .showAtmosphere(true)
      .atmosphereColor("#b7c9d4")
      .atmosphereAltitude(0.18)
      .pointOfView({ lat: DEFAULT_LAT, lng: DEFAULT_LON, altitude: 1.08 }, 0)
      .onGlobeClick((pos) => {
        if (!pos || pos.lat == null || pos.lng == null) return;
        addressInput.value = "";
        lookup({ lat: pos.lat, lon: pos.lng });
      })(el);
    const controls = globe.controls();
    controls.autoRotate = false;
    controls.enablePan = false;
    controls.rotateSpeed = 0.45;
    controls.zoomSpeed = 0.55;
    controls.minDistance = 150;
    controls.maxDistance = 520;
    window.addEventListener("resize", fitGlobe);
  } catch {
    globe = null;
  }
}

function syncGlobe(lat, lon, fires) {
  if (!globe || lat == null || lon == null) return;
  const heat = (fires || [])
    .filter((fire) => fire.lat != null && fire.lon != null)
    .map((fire) => ({ lat: fire.lat, lng: fire.lon, kind: "heat" }));
  const showFlares = nearBay(lat, lon);
  globe
    .pointsData([])
    .htmlElementsData([{ lat, lng: lon, kind: "pin" }, ...heat])
    .htmlLat("lat")
    .htmlLng("lng")
    .htmlAltitude(0.012)
    .htmlElement((point) => {
      const marker = document.createElement("div");
      marker.className = point.kind === "pin" ? "pin" : `dot dot-${point.kind}`;
      marker.title = point.kind === "heat"
        ? "Satellite heat kept in the score"
        : point.kind === "flare"
          ? "Refinery flare left out"
          : "Selected location";
      return marker;
    });

  const altitude = nearBay(lat, lon) ? 1.05 : 1.45;
  globe.pointOfView({ lat, lng: lon, altitude }, reducedMotion() ? 0 : 900);
  const lines = ["Bright pin is this address."];
  if (heat.length || showFlares) lines.push("Orange marks are satellite heat kept in the score.");
  if (showFlares) lines.push("Refinery flares are left out of the score.");
  legendEl.hidden = false;
  legendEl.textContent = lines.join(" ");
}

function insurabilitySentence(name, place) {
  const writer = INSURABILITY[name];
  if (writer) return writer(place);
  return "Not enough public data at this pin to say what a carrier would do.";
}

function powerNote(data) {
  const lead = "POWER data ~3 days behind (filtered −999s).";
  const feed = (data.feeds || []).find((item) => item.id === "power");
  const notes = feed?.notes || [];
  if (!feed || feed.status === "unavailable") return `${lead} Rain history left out.`;
  const dropped = notes.find((note) => /fill values/i.test(note));
  const latest = notes.find((note) => /^Latest valid POWER day/i.test(note));
  const count = dropped && dropped.match(/(\d+)/);
  const day = latest && latest.match(/(\d{4}-\d{2}-\d{2})/);
  const bits = [];
  if (count) bits.push(`${count[1]} fill days dropped`);
  if (day) bits.push(`latest ${day[1]}`);
  return bits.length ? `${lead} ${bits.join(", ")}.` : lead;
}

function flareNote(data) {
  const summary = data.fire_summary || {};
  const feed = (data.feeds || []).find((item) => item.id === "firms");
  const lead = "Filtered known industrial heat sources (refinery flares).";
  if (summary.available === false || feed?.status === "unavailable") return `${lead} Live heat left out.`;
  const count = data.filtered_firms_count ?? summary.industrial_count;
  if (count == null) return lead;
  if (!count) return `${lead} None in this window.`;
  return `${lead} ${count} kept out.`;
}

function renderNotes(data) {
  const items = [powerNote(data), flareNote(data)];
  if (data.fhsz_zone) items.push(`CAL FIRE Fire Hazard Severity Zone: ${data.fhsz_zone}.`);
  notesEl.innerHTML = items.map((item) => `<li>${esc(item)}</li>`).join("");
}

function renderBreakdown(day) {
  const ffwi = component(day, "ffwi");
  const raw = ffwi?.raw_input || {};
  const explicit = day?.fosberg_score ?? report?.fosberg_score;
  const score = explicit ?? (ffwi?.available ? ffwi.normalized : null);
  fosbergScoreEl.textContent = score == null ? "—" : Math.round(score);
  const width = score == null ? 0 : Math.max(0, Math.min(100, Number(score)));
  fosbergBarEl.style.width = `${width}%`;

  const rows = [];
  if (raw.temp_f != null) rows.push(["Temperature", `${raw.temp_f}°F`]);
  if (raw.rh_pct != null) rows.push(["Humidity", `${raw.rh_pct}%`]);
  if (raw.wind_mph != null) rows.push(["Wind", `${raw.wind_mph} mph`]);
  if (raw.emc != null) rows.push(["Fuel moisture", raw.emc]);
  if (raw.eta != null) rows.push(["Damping η", raw.eta]);
  const dryness = component(day, "dryness");
  const dryDays = dryness?.raw_input?.days_since_meaningful_rain;
  if (dryDays != null) rows.push(["Days since rain", dryDays]);
  if (!rows.length) {
    rows.push(["Afternoon weather", ffwi?.available ? "In the score" : "Left out"]);
  }
  breakdownEl.innerHTML = rows.map(([label, value]) =>
    `<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`
  ).join("");
}

function renderDays() {
  const days = report?.days || [];
  if (!days.length) {
    daysEl.hidden = true;
    daysEl.innerHTML = "";
    return;
  }
  daysEl.hidden = false;
  const scores = days.map((day) => day.score).filter((score) => score != null);
  const max = scores.length ? Math.max(...scores) : null;
  const peakCount = max == null ? 0 : days.filter((day) => day.score === max).length;
  const markPeak = max != null && peakCount < days.length;
  daysEl.innerHTML = days.map((day) => {
    const height = day.score == null || max == null
      ? 4
      : Math.max(6, Math.round((Number(day.score) / (max || 1)) * 28));
    const peak = markPeak && day.score === max;
    return `
      <button type="button" data-date="${esc(day.date)}" class="${peak ? "is-peak" : ""}" aria-pressed="${day.date === selectedDay}">
        <span class="day-bar" style="height:${height}px"></span>
        ${esc(day.label)}
        <strong>${day.score ?? "—"}</strong>
      </button>`;
  }).join("");
  daysEl.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => {
      selectedDay = button.dataset.date;
      draw();
    });
  });
}

function draw() {
  if (!report) return;
  const day = activeDay();
  const address = report.address || {};
  const place = address.label || DEFAULT_PLACE;
  const name = report.risk_tier || day?.band || report.band || "";
  const key = tierKey(name);
  document.body.dataset.tier = TIER_LABELS[key] ? key : "";
  placeEl.textContent = place;
  if (address.lat != null && address.lon != null) coordsEl.textContent = formatCoords(address.lat, address.lon);
  tierEl.textContent = TIER_LABELS[key] || name || "—";

  const bits = [];
  if (day?.score != null) bits.push(String(day.score));
  if (day?.label) bits.push(day.label);
  if (report.partial || day?.partial) bits.push("partial");
  const flag = component(day, "red_flag");
  if (flag?.available && flag.normalized >= 100) bits.push("red flag");
  tierMetaEl.textContent = bits.length ? bits.join(" · ") : "Insurance risk signal";

  const custom = report.plain_language_takeaway;
  takeawayEl.textContent = custom || insurabilitySentence(TIER_LABELS[key] || name, place);
  renderDays();
  renderBreakdown(day);
  renderNotes(report);
  if (report.disclaimer) footEl.textContent = report.disclaimer;
}

function showError(body) {
  errorEl.hidden = false;
  const candidates = body.candidates || [];
  errorEl.innerHTML = `<p>${esc(body.message || "Lookup failed.")}</p>`;
  if (!report) {
    tierEl.textContent = "—";
    takeawayEl.textContent = body.message || "The lookup failed. No score was invented.";
    document.body.dataset.tier = "";
  }
  if (!candidates.length) return;
  const box = document.createElement("div");
  box.className = "candidates";
  for (const candidate of candidates) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = candidate.label;
    button.addEventListener("click", () => lookup({
      lat: candidate.lat,
      lon: candidate.lon,
      address: candidate.label,
    }));
    box.appendChild(button);
  }
  errorEl.appendChild(box);
}

function renderChecklist() {
  if (!checklist.length) {
    checklistWrap.hidden = true;
    return;
  }
  checklistWrap.hidden = false;
  const done = checks();
  const open = checklist.filter((item) => !done.has(item.id)).sort((a, b) => b.weight - a.weight);
  const covered = checklist.reduce((sum, item) => sum + (done.has(item.id) ? item.weight : 0), 0);
  const rank = open.slice(0, 3).map((item) => `<li>${esc(item.title)}</li>`).join("");
  const rows = checklist.map((item) => `
    <label class="check">
      <input type="checkbox" data-id="${esc(item.id)}" ${done.has(item.id) ? "checked" : ""}>
      <span><strong>${esc(item.title)}</strong><br><span class="meta">${esc(item.detail)}</span></span>
      <span class="points">${item.weight}</span>
    </label>`).join("");
  checklistEl.innerHTML = `
    <p class="meta">${covered} of 100 mitigation points done. These rank unfinished work. They do not change the score.</p>
    <ol class="rank">${rank}</ol>
    ${rows}`;
  checklistEl.querySelectorAll("input").forEach((box) => {
    box.addEventListener("change", () => {
      const next = checks();
      if (box.checked) next.add(box.dataset.id);
      else next.delete(box.dataset.id);
      saveChecks(next);
      renderChecklist();
    });
  });
}

async function loadMeta() {
  const response = await fetch("/api/health");
  const body = await response.json();
  checklist = body.checklist || [];
  examplesEl.replaceChildren();
  for (const example of body.examples || []) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = example.address;
    button.addEventListener("click", () => {
      addressInput.value = example.address;
      form.requestSubmit();
    });
    examplesEl.appendChild(button);
  }
  renderChecklist();
}

async function lookup(params) {
  page.classList.add("is-loading");
  statusEl.textContent = "Reading public feeds";
  errorEl.hidden = true;
  const url = new URL("/api/risk", location.origin);
  if (params.address) url.searchParams.set("address", params.address);
  if (params.lat != null) url.searchParams.set("lat", params.lat);
  if (params.lon != null) url.searchParams.set("lon", params.lon);
  const outage = outageInput.value.trim();
  if (outage) url.searchParams.set("simulate_outage", outage);
  if (params.lat != null && params.lon != null) syncGlobe(params.lat, params.lon, report?.fires || []);
  try {
    const response = await fetch(url);
    const body = await response.json();
    statusEl.textContent = "";
    if (!body.ok) showError(body);
    else {
      report = body;
      selectedDay = body.highest_risk_day || (body.days && body.days[0] && body.days[0].date) || null;
      draw();
      const point = body.address || {};
      syncGlobe(point.lat, point.lon, body.fires || []);
    }
  } catch {
    statusEl.textContent = "";
    showError({ message: "The page could not read a result. No score was invented." });
  } finally {
    page.classList.remove("is-loading");
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const address = addressInput.value.trim();
  if (!address) return;
  lookup({ address });
});

mountGlobe();
fitGlobe();

const initial = new URLSearchParams(location.search);
if (initial.get("simulate_outage")) outageInput.value = initial.get("simulate_outage");

loadMeta().catch(() => {
  statusEl.textContent = "Example addresses could not be loaded. You can still search or click the Earth.";
});

if (initial.get("address") && !initial.get("lat")) {
  addressInput.value = initial.get("address");
  lookup({ address: initial.get("address") });
} else {
  lookup({
    lat: Number(initial.get("lat")) || DEFAULT_LAT,
    lon: Number(initial.get("lon")) || DEFAULT_LON,
    address: initial.get("address") || DEFAULT_PLACE,
  });
}
