const CHECK_KEY = "kyhi-checklist-v1";
const addressInput = document.querySelector("#address");
const outageInput = document.querySelector("#outage");
const form = document.querySelector("#lookup");
const statusEl = document.querySelector("#status");
const errorEl = document.querySelector("#error");
const resultsEl = document.querySelector("#results");
const checklistEl = document.querySelector("#checklist");
const examplesEl = document.querySelector("#examples");

let checklist = [];
let selectedDay = null;
let fireMap = null;

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
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

async function loadMeta() {
  const response = await fetch("/api/health");
  const body = await response.json();
  if (body.disclaimer) document.querySelector("#disclaimer").textContent = body.disclaimer;
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
  if (body.examples && body.examples[0]) addressInput.placeholder = body.examples[0].address;
  renderChecklist();
}

function renderChecklist() {
  const done = checks();
  const open = checklist.filter((item) => !done.has(item.id)).sort((a, b) => b.weight - a.weight);
  const covered = checklist.reduce((sum, item) => sum + (done.has(item.id) ? item.weight : 0), 0);
  const rank = open.map((item) => `<li>${esc(item.title)} <span class="points">${item.weight}</span></li>`).join("");
  const rows = checklist.map((item) => `
    <label class="check">
      <input type="checkbox" data-id="${esc(item.id)}" ${done.has(item.id) ? "checked" : ""}>
      <span><strong>${esc(item.title)}</strong><br><span class="meta">${esc(item.detail)} ${esc(item.source)}</span></span>
      <span class="points">${item.weight}</span>
    </label>`).join("");
  checklistEl.innerHTML = `
    <h2>Safer from Wildfires</h2>
    <p>${covered} of 100 mitigation points done. ${100 - covered} still open. These points rank unfinished work. They do not change the weather score and they are not a premium.</p>
    <ol class="rank">${rank || "<li>Nothing left on the list.</li>"}</ol>
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

function rawText(raw) {
  if (!raw || !Object.keys(raw).length) return "—";
  return Object.entries(raw).map(([key, value]) => `${key} ${value ?? "—"}`).join(" · ");
}

function renderResults(report) {
  errorEl.hidden = true;
  resultsEl.hidden = false;
  selectedDay = report.highest_risk_day || (report.days[0] && report.days[0].date);
  draw(report);
}

function draw(report) {
  const day = report.days.find((item) => item.date === selectedDay) || report.days[0];
  const days = report.days.map((item) => `
    <button type="button" data-date="${esc(item.date)}" aria-pressed="${item.date === day.date}">
      <span class="meta">${esc(item.label)}</span>
      <strong>${item.score ?? "—"}</strong>
      <span>${esc(item.band || "no score")}${item.partial ? " · partial" : ""}</span>
    </button>`).join("");
  const rows = (day.breakdown || []).map((item) => `
    <tr>
      <td>${esc(item.label)}${item.available ? "" : " (left out)"}</td>
      <td>${esc(rawText(item.raw_input))}</td>
      <td>${item.normalized ?? "—"}</td>
      <td>${item.effective_weight ?? item.weight}</td>
      <td>${item.contribution ?? "—"}</td>
    </tr>`).join("");
  const fires = (report.fires || []).map((fire) => {
    const incident = fire.incident
      ? ` · ${esc(fire.incident.name)} (${esc(fire.incident.type_label)})`
      : "";
    return `<div class="fire">${fire.distance_km} km / ${fire.distance_mi} mi ${esc(fire.bearing)} · FRP ${fire.frp ?? "—"} MW · ${esc(fire.confidence)} · ${esc(fire.satellite)} ${esc(fire.acq_date)} ${esc(fire.acq_time)}${incident}</div>`;
  }).join("") || `<p class="meta">${esc((report.fire_summary && report.fire_summary.available) ? "No detection left after filtering." : "Satellite detections were not used in this score.")}</p>`;
  const summary = report.fire_summary || {};
  const sites = (summary.industrial_by_site || []).map((site) => `${esc(site.name)} (${site.count})`).join(", ");
  const feeds = (report.feeds || []).map((feed) => `
    <div class="feed"><strong>${esc(feed.label)}</strong> · ${esc(feed.status)} · ${esc(feed.age_label)} · dropped ${feed.dropped}
      ${(feed.notes || []).map((note) => `<div class="meta">${esc(note)}</div>`).join("")}
    </div>`).join("");
  const incidents = (report.incidents || []).map((item) =>
    `<div class="fire">${esc(item.name)} · ${esc(item.type || "—")} ${esc(item.type_label)} · ${item.acres ?? "—"} acres · ${item.percent_contained ?? "—"}% contained · ${item.distance_km} km ${esc(item.bearing)}</div>`
  ).join("");
  const reasons = (report.partial_reasons || []).map((reason) => `<div class="meta">${esc(reason)}</div>`).join("");
  resultsEl.innerHTML = `
    <p class="meta">${esc(report.address.label)}</p>
    <div class="score-row">
      <p class="score-num">${report.score ?? "—"}</p>
      <p class="band">${esc(report.band || "No score")}${report.partial ? " · partial" : ""}</p>
    </div>
    <p class="alert">${esc(report.alert)}</p>
    ${report.banner ? `<p class="banner">${esc(report.banner)}</p>` : ""}
    ${reasons}
    <div class="days">${days}</div>
    <h2>Score breakdown · ${esc(day.label)}</h2>
    <table>
      <thead><tr><th>Component</th><th>Input</th><th>0–100</th><th>Weight</th><th>Points</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <h2>Fire proximity gradient</h2>
    <div class="map-block">
      <div id="map" role="region" aria-label="Fire proximity gradient"></div>
      <p class="meta">Fire proximity gradient at 5, 15, and 50 km. Black dots are detections used in the score. Gray dots were filtered out (industrial flares, low confidence, or persistent low-FRP heat).</p>
    </div>
    <h2>Nearby satellite detections</h2>
    ${fires}
    <p class="meta">Filtered industrial ${summary.industrial_count || 0}${sites ? ": " + sites : ""}. Low confidence ${summary.low_confidence_count || 0}. Possible static heat ${summary.possible_static_count || 0}. Kept ${summary.kept_count || 0}.</p>
    ${incidents ? `<h2>Named incidents</h2>${incidents}` : ""}
    <h2>Data freshness</h2>
    ${feeds}
    <p class="meta">${esc(report.disclaimer)}</p>`;
  resultsEl.querySelectorAll(".days button").forEach((button) => {
    button.addEventListener("click", () => {
      selectedDay = button.dataset.date;
      draw(report);
    });
  });
  try {
    renderMap(report);
  } catch (err) {
    console.error(err);
  }
}

function dotIcon(kind) {
  const muted = kind !== "kept";
  return L.divIcon({
    className: muted ? "dot-muted" : "dot-kept",
    iconSize: muted ? [8, 8] : [10, 10],
    iconAnchor: muted ? [4, 4] : [5, 5],
  });
}

function addPoint(layer, point, kind) {
  if (point == null || point.lat == null || point.lon == null) return;
  const marker = L.marker([point.lat, point.lon], { icon: dotIcon(kind), keyboard: false });
  const bits = [kind === "kept" ? "Used in the score" : "Filtered"];
  if (point.frp != null) bits.push(`FRP ${point.frp} MW`);
  if (point.max_frp != null) bits.push(`max FRP ${point.max_frp} MW`);
  if (point.distance_km != null) bits.push(`${point.distance_km} km`);
  if (point.site) bits.push(point.site);
  if (point.reason) bits.push(point.reason);
  marker.bindTooltip(bits.join(" · "));
  marker.addTo(layer);
}

function renderMap(report) {
  if (fireMap) {
    fireMap.remove();
    fireMap = null;
  }
  const el = document.querySelector("#map");
  if (!el || !window.L || !report.address) return;
  const lat = report.address.lat;
  const lon = report.address.lon;
  fireMap = L.map(el, { scrollWheelZoom: false }).setView([lat, lon], 9);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(fireMap);
  const rings = [
    { km: 50, opacity: 0.05 },
    { km: 15, opacity: 0.09 },
    { km: 5, opacity: 0.16 },
  ];
  for (const ring of rings) {
    L.circle([lat, lon], {
      radius: ring.km * 1000,
      color: "#111111",
      weight: 1,
      fillColor: "#111111",
      fillOpacity: ring.opacity,
    }).bindTooltip(`${ring.km} km · fire proximity gradient`).addTo(fireMap);
  }
  const summary = report.fire_summary || {};
  for (const point of summary.industrial_points || []) addPoint(fireMap, point, "industrial");
  for (const point of summary.low_confidence_points || report.low_confidence || []) addPoint(fireMap, point, "low");
  for (const point of summary.possible_static || []) addPoint(fireMap, point, "low-frp");
  for (const point of summary.kept || report.fires || []) addPoint(fireMap, point, "kept");
  L.marker([lat, lon], {
    icon: L.divIcon({ className: "home-mark", iconSize: [14, 14], iconAnchor: [7, 7] }),
    keyboard: false,
    zIndexOffset: 1000,
  }).bindTooltip(report.address.label || "Address").addTo(fireMap);
  fireMap.fitBounds(L.latLng(lat, lon).toBounds(50000), { padding: [18, 18] });
  setTimeout(() => fireMap && fireMap.invalidateSize(), 0);
}

function showError(body) {
  if (fireMap) {
    fireMap.remove();
    fireMap = null;
  }
  resultsEl.hidden = true;
  errorEl.hidden = false;
  const candidates = body.candidates || [];
  errorEl.innerHTML = `<p>${esc(body.message || "Lookup failed.")}</p>`;
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

async function lookup(params) {
  statusEl.textContent = "Reading public feeds…";
  errorEl.hidden = true;
  const url = new URL("/api/risk", location.origin);
  if (params.address) url.searchParams.set("address", params.address);
  if (params.lat != null) url.searchParams.set("lat", params.lat);
  if (params.lon != null) url.searchParams.set("lon", params.lon);
  const outage = outageInput.value.trim();
  if (outage) url.searchParams.set("simulate_outage", outage);
  try {
    const response = await fetch(url);
    const body = await response.json();
    statusEl.textContent = "";
    if (!body.ok) showError(body);
    else renderResults(body);
  } catch {
    statusEl.textContent = "";
    showError({ message: "The page could not read a result. No score was invented." });
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  lookup({ address: addressInput.value.trim() });
});

loadMeta().catch(() => {
  statusEl.textContent = "The example addresses could not be loaded. You can still type an address.";
});
