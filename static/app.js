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
const extrasEl = document.querySelector("#extras");
let fireMap = null;

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

  globe.controls().autoRotate = false;
  globe
    .ringsData([{ lat, lng: lon }])
    .ringLat("lat")
    .ringLng("lng")
    .ringColor(() => (t) => `rgba(255,120,0,${1 - t})`)
    .ringMaxRadius(4)
    .ringPropagationSpeed(3)
    .ringRepeatPeriod(600);
  globe.pointOfView({ lat, lng: lon, altitude: 2.5 }, 600);
  setTimeout(() => {
    if (globe) globe.pointOfView({ lat, lng: lon, altitude: 0.3 }, 1600);
  }, 600);
  const lines = ["Bright pin is this address."];
  if (heat.length || showFlares) lines.push("Orange marks are satellite heat kept in the score.");
  if (showFlares) lines.push("Refinery flares are left out of the score.");
  legendEl.hidden = false;
  legendEl.textContent = lines.join(" ");
}

const STATE_ABBR = {Alabama:"AL",Alaska:"AK",Arizona:"AZ",Arkansas:"AR",California:"CA",Colorado:"CO",Connecticut:"CT",Delaware:"DE",Florida:"FL",Georgia:"GA",Hawaii:"HI",Idaho:"ID",Illinois:"IL",Indiana:"IN",Iowa:"IA",Kansas:"KS",Kentucky:"KY",Louisiana:"LA",Maine:"ME",Maryland:"MD",Massachusetts:"MA",Michigan:"MI",Minnesota:"MN",Mississippi:"MS",Missouri:"MO",Montana:"MT",Nebraska:"NE",Nevada:"NV","New Hampshire":"NH","New Jersey":"NJ","New Mexico":"NM","New York":"NY","North Carolina":"NC","North Dakota":"ND",Ohio:"OH",Oklahoma:"OK",Oregon:"OR",Pennsylvania:"PA","Rhode Island":"RI","South Carolina":"SC","South Dakota":"SD",Tennessee:"TN",Texas:"TX",Utah:"UT",Vermont:"VT",Virginia:"VA",Washington:"WA","West Virginia":"WV",Wisconsin:"WI",Wyoming:"WY","District of Columbia":"DC"};

function shortPlace(label) {
  const parts = String(label || "").split(",").map((p) => p.trim()).filter(Boolean);
  const si = parts.findIndex((p) => STATE_ABBR[p]);
  if (si < 0) return label;
  const state = STATE_ABBR[parts[si]];
  let ci = si - 1;
  if (ci >= 0 && /County$/i.test(parts[ci]) && ci - 1 >= 1) ci -= 1;
  const city = ci >= 0 ? parts[ci] : "";
  return city ? `${city}, ${state}` : state;
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

function rawText(raw) {
  if (!raw || !Object.keys(raw).length) return "—";
  return Object.entries(raw).map(([key, value]) => `${key} ${value ?? "—"}`).join(" · ");
}

function aerialUrl(lat, lon) {
  const dlat = 0.0018;
  const dlon = 0.0018 / Math.cos((lat * Math.PI) / 180);
  const bbox = [lon - dlon, lat - dlat, lon + dlon, lat + dlat].map((n) => n.toFixed(6)).join(",");
  return `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?bbox=${bbox}&bboxSR=4326&imageSR=3857&size=800,800&format=jpg&f=image`;
}

function aerialBlock(data) {
  const lat = data.address && data.address.lat;
  const lon = data.address && data.address.lon;
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

function orbitBlock() {
  return `
    <figure class="orbit" id="orbit">
      <h2>Today from orbit</h2>
      <img alt="Today from orbit">
      <figcaption></figcaption>
    </figure>`;
}

function watchOrbit(figure, data) {
  const img = figure && figure.querySelector("img");
  if (!img || !data.address) return;
  const lat = data.address.lat;
  const lon = data.address.lon;
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

function renderMap(data) {
  if (fireMap) {
    fireMap.remove();
    fireMap = null;
  }
  const el = document.querySelector("#map");
  if (!el || !window.L || !data.address) return;
  const lat = data.address.lat;
  const lon = data.address.lon;
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
  const summary = data.fire_summary || {};
  for (const point of summary.industrial_points || []) addPoint(fireMap, point, "industrial");
  for (const point of summary.low_confidence_points || data.low_confidence || []) addPoint(fireMap, point, "low");
  for (const point of summary.possible_static || []) addPoint(fireMap, point, "low-frp");
  for (const point of summary.kept || data.fires || []) addPoint(fireMap, point, "kept");
  L.marker([lat, lon], {
    icon: L.divIcon({ className: "home-mark", iconSize: [14, 14], iconAnchor: [7, 7] }),
    keyboard: false,
    zIndexOffset: 1000,
  }).bindTooltip(data.address.label || "Address").addTo(fireMap);
  fireMap.fitBounds(L.latLng(lat, lon).toBounds(50000), { padding: [18, 18] });
  setTimeout(() => fireMap && fireMap.invalidateSize(), 0);
}

function fillExtras() {
  if (!report || !extrasEl) return;
  const day = activeDay();
  if (!day) {
    extrasEl.hidden = true;
    return;
  }
  extrasEl.hidden = false;
  const rows = (day.breakdown || []).map((item) => `
    <tr>
      <td>${esc(item.label)}${item.available ? "" : " (left out)"}</td>
      <td>${esc(rawText(item.raw_input))}</td>
      <td>${item.normalized ?? "—"}</td>
      <td>${item.effective_weight ?? item.weight}</td>
      <td>${item.contribution ?? "—"}</td>
    </tr>`).join("");
  const firesHtml = (report.fires || []).map((fire) => {
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
    : "";
  extrasEl.innerHTML = `
    ${addressLine}
    <p class="alert">${esc(report.alert || "")}</p>
    ${report.banner ? `<p class="banner">${esc(report.banner)}</p>` : ""}
    ${reasons}
    <h2>Score breakdown · ${esc(day.label)}</h2>
    <table>
      <thead><tr><th>Component</th><th>Input</th><th>0–100</th><th>Weight</th><th>Points</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    ${aerialBlock(report)}
    ${orbitBlock()}
    <h2>Fire proximity gradient</h2>
    <div class="map-block">
      <div id="map" role="region" aria-label="Fire proximity gradient"></div>
      <p class="meta">Fire proximity gradient at 5, 15, and 50 km. Orange dots are detections used in the score. Gray dots were filtered out (industrial flares, low confidence, or persistent low-FRP heat).</p>
    </div>
    <h2>Nearby satellite detections</h2>
    ${firesHtml}
    <p class="meta">Filtered industrial ${summary.industrial_count || 0}${sites ? ": " + sites : ""}. Low confidence ${summary.low_confidence_count || 0}. Possible static heat ${summary.possible_static_count || 0}. Kept ${summary.kept_count || 0}.</p>
    ${incidents ? `<h2>Named incidents</h2>${incidents}` : ""}
    <h2>Data freshness</h2>
    ${feeds}
    <p class="meta">${esc(report.disclaimer || "")}</p>`;
  watchAerial(extrasEl.querySelector("#aerial"));
  watchOrbit(extrasEl.querySelector("#orbit"), report);
  try { renderMap(report); } catch (err) { console.error(err); }
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

const INSURANCE_BOX = {
  low: "Carriers are unlikely to flag this week.",
  moderate: "Carriers are unlikely to flag this week.",
  elevated: "Expect closer review at renewal. Do the checklist below for California Safer from Wildfires discounts.",
  high: "Expect closer review at renewal. Do the checklist below for California Safer from Wildfires discounts.",
  extreme: "Active fire nearby. Insurers often pause new policies in this area until it is contained.",
};

function renderInsuranceBox(key) {
  const box = document.querySelector("#insurance-box");
  const text = document.querySelector("#insurance-box-text");
  if (!box || !text) return;
  const msg = INSURANCE_BOX[key];
  box.hidden = !msg;
  box.dataset.tier = msg ? key : "";
  text.textContent = msg || "";
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
  renderInsuranceBox(key);

  const custom = report.plain_language_takeaway;
  takeawayEl.textContent = custom || insurabilitySentence(TIER_LABELS[key] || name, shortPlace(place));
  renderDays();
  renderBreakdown(day);
  renderNotes(report);
  fillExtras();
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
