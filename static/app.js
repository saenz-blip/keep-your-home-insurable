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
let globe = null;

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
  try {
    plotGlobe(report);
  } catch (err) {
    console.error(err);
  }
}

function riskClass(band) {
  const name = String(band || "").toLowerCase();
  return name === "high" || name === "extreme" ? " risk" : "";
}

function draw(report) {
  const day = report.days.find((item) => item.date === selectedDay) || report.days[0];
  const days = report.days.map((item) => `
    <button type="button" data-date="${esc(item.date)}" aria-pressed="${item.date === day.date}">
      <span class="meta">${esc(item.label)}</span>
      <strong>${item.score ?? "—"}</strong>
      <span class="day-band${riskClass(item.band)}">${esc(item.band || "no score")}${item.partial ? " · partial" : ""}</span>
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
  const addressLine = report.address && report.address.did_you_mean
    ? `<p class="did-you-mean">Did you mean: ${esc(report.address.label)}?</p>`
    : `<p class="meta">${esc(report.address.label)}</p>`;
  resultsEl.innerHTML = `
    ${addressLine}
    <div class="score-row">
      <p class="score-num${riskClass(report.band)}">${report.score ?? "—"}</p>
      <p class="band${riskClass(report.band)}">${esc(report.band || "No score")}${report.partial ? " · partial" : ""}</p>
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
    ${aerialBlock(report)}
    ${orbitBlock(report)}
    <h2>Fire proximity gradient</h2>
    <div class="map-block">
      <div id="map" role="region" aria-label="Fire proximity gradient"></div>
      <p class="meta">Fire proximity gradient at 5, 15, and 50 km. Orange dots are detections used in the score. Gray dots were filtered out (industrial flares, low confidence, or persistent low-FRP heat).</p>
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
  watchAerial(resultsEl.querySelector("#aerial"));
  watchOrbit(resultsEl.querySelector("#orbit"), report);
  try {
    renderMap(report);
  } catch (err) {
    console.error(err);
  }
}

function aerialUrl(lat, lon) {
  const dlat = 0.0018;
  const dlon = 0.0018 / Math.cos((lat * Math.PI) / 180);
  const bbox = [lon - dlon, lat - dlat, lon + dlon, lat + dlat].map((n) => n.toFixed(6)).join(",");
  return `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?bbox=${bbox}&bboxSR=4326&imageSR=3857&size=800,800&format=jpg&f=image`;
}

function aerialBlock(report) {
  const lat = report.address && report.address.lat;
  const lon = report.address && report.address.lon;
  if (lat == null || lon == null) return "";
  return `
    <figure class="aerial" id="aerial">
      <div class="aerial-frame">
        <img alt="Aerial photo of the address" src="${esc(aerialUrl(lat, lon))}">
        <span class="crosshair" aria-hidden="true"></span>
      </div>
      <figcaption>Aerial photo: USDA NAIP via USGS, ~1 m resolution, updated every 2–3 years. Not today's image.</figcaption>
    </figure>`;
}

function utcDay(daysAgo) {
  const day = new Date();
  day.setUTCDate(day.getUTCDate() - daysAgo);
  return day.toISOString().slice(0, 10);
}

function orbitUrl(lat, lon, day) {
  const dLat = 0.27;
  const dLon = 0.27 / Math.cos((lat * Math.PI) / 180);
  const bbox = [lat - dLat, lon - dLon, lat + dLat, lon + dLon].map((n) => n.toFixed(5)).join(",");
  const layers = [
    "VIIRS_NOAA20_CorrectedReflectance_TrueColor",
    "VIIRS_NOAA20_Thermal_Anomalies_375m_All",
    "VIIRS_NOAA21_Thermal_Anomalies_375m_All",
  ].join(",");
  return "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"
    + "?SERVICE=WMS&REQUEST=GetMap&VERSION=1.3.0&CRS=EPSG:4326"
    + `&BBOX=${bbox}&WIDTH=800&HEIGHT=800&FORMAT=image/png&TIME=${day}`
    + `&LAYERS=${layers}&STYLES=`;
}

function orbitBlock(report) {
  const lat = report.address && report.address.lat;
  const lon = report.address && report.address.lon;
  if (lat == null || lon == null) return "";
  return `
    <figure class="orbit" id="orbit">
      <h2>Today from orbit</h2>
      <img alt="Today from orbit">
      <figcaption></figcaption>
    </figure>`;
}

function watchOrbit(figure, report) {
  const img = figure && figure.querySelector("img");
  if (!img || !report.address) return;
  const lat = report.address.lat;
  const lon = report.address.lon;
  const caption = figure.querySelector("figcaption");
  const today = utcDay(0);
  const yesterday = utcDay(1);
  let triedYesterday = false;
  const show = (day) => {
    caption.textContent = `NASA VIIRS true color + fire detections, ${day}.`;
    img.src = orbitUrl(lat, lon, day);
  };
  img.addEventListener("error", () => {
    if (!triedYesterday) {
      triedYesterday = true;
      show(yesterday);
      return;
    }
    figure.hidden = true;
  });
  show(today);
}

function aerialLooksBlank(img) {
  const canvas = document.createElement("canvas");
  const size = 24;
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  ctx.drawImage(img, 0, 0, size, size);
  const data = ctx.getImageData(0, 0, size, size).data;
  let min = 255;
  let max = 0;
  for (let i = 0; i < data.length; i += 4) {
    const value = (data[i] + data[i + 1] + data[i + 2]) / 3;
    if (value < min) min = value;
    if (value > max) max = value;
  }
  return max - min < 8;
}

function watchAerial(figure) {
  const img = figure && figure.querySelector("img");
  if (!img) return;
  const hide = () => { figure.hidden = true; };
  img.addEventListener("error", hide);
  img.addEventListener("load", () => {
    const probe = new Image();
    probe.crossOrigin = "anonymous";
    probe.onload = () => {
      try {
        if (aerialLooksBlank(probe)) hide();
      } catch {
        // Pixel read failed. The photo itself loaded, so leave it up.
      }
    };
    probe.src = img.src;
  });
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
    { km: 50, opacity: 0.04 },
    { km: 15, opacity: 0.08 },
    { km: 5, opacity: 0.14 },
  ];
  for (const ring of rings) {
    L.circle([lat, lon], {
      radius: ring.km * 1000,
      color: "#EDEBE6",
      weight: 1,
      fillColor: "#EDEBE6",
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

function hideHero() {
  const hero = document.querySelector("#hero");
  if (hero) hero.hidden = true;
}

function mountGlobe() {
  const hero = document.querySelector("#hero");
  const el = document.querySelector("#globe");
  if (!hero || !el || typeof Globe !== "function") {
    hideHero();
    return;
  }
  try {
    globe = Globe()
      .globeImageUrl("//unpkg.com/three-globe/example/img/earth-night.jpg")
      .backgroundImageUrl("//unpkg.com/three-globe/example/img/night-sky.png")
      .backgroundColor("#0B0B0C")
      .showAtmosphere(true)
      .atmosphereColor("#9A9892")
      .atmosphereAltitude(0.16)
      .pointsData([])
      .pointLat("lat")
      .pointLng("lon")
      .pointColor("color")
      .pointAltitude(0.01)
      .pointRadius(0.35)
      .ringsData([])
      .ringLat("lat")
      .ringLng("lon")
      .ringColor(() => "#ffffff")
      .ringAltitude(0.002)
      .ringMaxRadius(3)
      .ringPropagationSpeed(1.4)
      .ringRepeatPeriod(900)
      .width(el.clientWidth || hero.clientWidth)
      .height(el.clientHeight || 480)
      (el);
    globe.pointOfView({ lat: 25, lng: -40, altitude: 2.2 });
    const controls = globe.controls();
    controls.autoRotate = true;
    controls.autoRotateSpeed = 0.35;
    controls.enableZoom = false;
    window.addEventListener("resize", () => {
      if (!globe || hero.hidden) return;
      globe.width(el.clientWidth);
      globe.height(el.clientHeight);
    });
  } catch (err) {
    console.error(err);
    globe = null;
    hideHero();
  }
}

function plotGlobe(report) {
  if (!globe || !report.address || report.address.lat == null || report.address.lon == null) return;
  const summary = report.fire_summary || {};
  const points = [];
  const add = (list, color) => {
    for (const point of list || []) {
      if (point == null || point.lat == null || point.lon == null) continue;
      points.push({ lat: point.lat, lon: point.lon, color });
    }
  };
  add(summary.kept || report.fires, "#F26B2A");
  add(summary.industrial_points, "#8A8882");
  add(summary.low_confidence_points || report.low_confidence, "#8A8882");
  add(summary.possible_static, "#8A8882");
  globe.pointsData(points);
  globe.ringsData([{ lat: report.address.lat, lon: report.address.lon }]);
  const controls = globe.controls();
  if (controls) controls.autoRotate = false;
  globe.pointOfView({ lat: report.address.lat, lng: report.address.lon, altitude: 1.5 }, 1500);
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

mountGlobe();
