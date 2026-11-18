(() => {
"use strict";
const $ = (s, r = document) => r.querySelector(s);
const CLS = { car: ["Mobil", "#37adf6"], motorbike: ["Motor", "#ffc83c"], bus: ["Bus", "#78d66e"], truck: ["Truk", "#ff785a"], bicycle: ["Sepeda", "#dc78e6"] };
const KEYS = Object.keys(CLS);
let S = null, CFG = null, metric = "count", mode = null, drag = null, calPts = [];
const DEFAULT_SRC = "https://cctvmalang.24hour.id/twentyfourhourid/proxy.php?id=767576969564466612969572";

const fmt = (n, d = 0) => (n == null || isNaN(n)) ? "–" : Number(n).toLocaleString("id-ID", { maximumFractionDigits: d, minimumFractionDigits: d });
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const api = (u, body) => fetch(u, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(r => r.json());
function toast(t) { const e = $("#toast"); e.textContent = t; e.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => e.hidden = true, 2600); }

/* ---------------- ikon cuaca ---------------- */
function icon(k) {
  const sun = '<circle cx="32" cy="32" r="11" fill="#ffc83c"/><g stroke="#ffc83c" stroke-width="3" stroke-linecap="round">' + [0, 45, 90, 135, 180, 225, 270, 315].map(a => `<line x1="${32 + 17 * Math.cos(a * Math.PI / 180)}" y1="${32 + 17 * Math.sin(a * Math.PI / 180)}" x2="${32 + 23 * Math.cos(a * Math.PI / 180)}" y2="${32 + 23 * Math.sin(a * Math.PI / 180)}"/>`).join("") + "</g>";
  const moon = '<path d="M40 14a18 18 0 1 0 12 30A16 16 0 0 1 40 14z" fill="#cfe0f3"/>';
  const cloud = (c = "#b9cbe0", y = 0) => `<path d="M20 ${46 + y}h26a9 9 0 0 0 1-18 12 12 0 0 0-23-2 10 10 0 0 0-4 20z" fill="${c}"/>`;
  const drops = n => Array.from({ length: n }, (_, i) => `<line x1="${22 + i * 9}" y1="50" x2="${19 + i * 9}" y2="58" stroke="#5aa9ff" stroke-width="3" stroke-linecap="round"/>`).join("");
  const m = {
    clear: sun, clear_night: moon,
    partly: '<g transform="translate(-6,-6) scale(.8)">' + sun + "</g>" + cloud(), partly_night: '<g transform="translate(-4,-6) scale(.7)">' + moon + "</g>" + cloud(),
    cloudy: cloud("#9fb4cc", 2), fog: cloud("#9fb4cc", -2) + '<g stroke="#9fb4cc" stroke-width="3" stroke-linecap="round"><line x1="16" y1="52" x2="48" y2="52"/><line x1="20" y1="58" x2="44" y2="58"/></g>',
    drizzle: cloud("#9fb4cc", -4) + drops(3), rain: cloud("#8aa0b8", -6) + drops(4), snow: cloud("#b9cbe0", -6) + '<g fill="#fff"><circle cx="24" cy="54" r="2.5"/><circle cx="34" cy="58" r="2.5"/><circle cx="44" cy="54" r="2.5"/></g>',
    storm: cloud("#7a8ea6", -6) + '<path d="M34 44l-6 10h6l-3 9 10-13h-6l4-6z" fill="#ffc83c"/>'
  };
  return `<svg viewBox="0 0 64 64" aria-hidden="true">${m[k] || m.cloudy}</svg>`;
}
const AQI = [[50, "#4fd18b", "Baik"], [100, "#ffd84d", "Sedang"], [150, "#ff9f43", "Tidak sehat bagi kelompok sensitif"], [200, "#ff6b5a", "Tidak sehat"], [300, "#b277ff", "Sangat tidak sehat"], [1e9, "#a23a4a", "Berbahaya"]];
const aqiInfo = v => AQI.find(a => v <= a[0]);
const compass = d => d == null ? "–" : ["U", "TL", "T", "TG", "S", "BD", "B", "BL"][Math.round(d / 45) % 8];

/* ---------------- render ---------------- */
function renderStatus(st) {
  const p = $("#pill"), t = $("#pillText");
  const map = { live: ["pill-live", st.demo ? "Mode demo" : "Langsung"], error: ["pill-err", "Terputus"], menghubungkan: ["pill-wait", "Menghubungkan"], mulai: ["pill-wait", "Memulai"] };
  const [c, l] = st.demo && st.state === "live" ? ["pill-demo", "Mode demo"] : (map[st.state] || ["pill-wait", st.state]);
  p.className = "pill " + c; t.textContent = l;
  $("#hudFps").textContent = fmt(st.fps, 1) + " FPS";
  $("#hudDet").textContent = st.detector;
  $("#hudLat").textContent = st.latency_ms ? fmt(st.latency_ms) + " ms/deteksi" : "";
  $("#footDet").textContent = st.detector;
  const b = $("#banner");
  if (st.state === "error" || st.state === "menghubungkan") { b.hidden = false; b.className = "banner" + (st.state === "error" ? "" : " info"); b.textContent = st.message; }
  else b.hidden = true;
  const src = $("#hudSrc"); src.textContent = st.demo ? "Simulasi" : (/^https?:/.test(st.source) ? "CCTV · " + new URL(st.source).hostname : st.source);
  $("#tPause").textContent = (window._paused ? "▶ Lanjut" : "⏸ Jeda");
}

function renderKpis(s) {
  const lvlCol = ["#4fd18b", "#8fdc6a", "#ffd84d", "#ff9f43", "#ff6b5a"][s.zone.level_i];
  $("#kpis").innerHTML = [
    ["Total terhitung", fmt(s.total), `sejak ${s.since.slice(11, 16)}`],
    ["Per jam (proyeksi)", fmt(s.rate_per_hour), `${fmt(s.this_minute)} kend. menit ini`],
    ["Volume SMP", fmt(s.pcu_total, 1), "satuan mobil penumpang"],
    ["Kecepatan rata-rata", s.speed.avg == null ? "–" : fmt(s.speed.avg, 0) + " km/j", `estimasi · kini ${s.speed.now_avg == null ? "-" : fmt(s.speed.now_avg, 0)}`],
    ["Di zona sekarang", fmt(s.zone.count), `puncak ${fmt(s.zone.peak)}`],
    ["Kepadatan", `<span style="color:${lvlCol}">${s.zone.level}</span>`, `${fmt(s.zone.pcu, 1)} SMP di zona`],
  ].map(k => `<div class="kpi"><label>${k[0]}</label><b>${k[1]}</b><small>${k[2]}</small></div>`).join("");
}

function renderWeather(w) {
  const el = $("#wxBody");
  if (!w || !w.current) { el.className = "skeleton-box"; el.innerHTML = w && w.error ? `Cuaca belum tersedia: ${esc(w.error)}` : "Memuat data cuaca…"; return; }
  el.className = "";
  const c = w.current, u = w.units || {}, aq = w.air_quality || {}, au = w.air_units || {};
  $("#wxSrc").innerHTML = `${esc(w.location?.name || "")} · ${w.source === "demo" ? "data contoh" : "Open-Meteo"} · ${(w.updated || "").slice(11, 16)}`;
  let html = `<div class="wx-main"><div class="wx-ico">${icon(c.desc.icon)}</div><div><div class="wx-temp">${fmt(c.temperature_2m, 1)}<sup>${esc(u.temperature_2m || "°C")}</sup></div><div class="wx-desc">${esc(c.desc.text)} · terasa ${fmt(c.apparent_temperature, 1)}°</div></div></div>
  <div class="wx-grid">
   <div>Kelembapan<b>${fmt(c.relative_humidity_2m)}%</b></div>
   <div>Angin<b>${fmt(c.wind_speed_10m, 1)} km/j ${compass(c.wind_direction_10m)}</b></div>
   <div>Hujan<b>${fmt(c.precipitation, 1)} mm</b></div>
   <div>Tekanan<b>${fmt(c.pressure_msl)} hPa</b></div>
   <div>Awan<b>${fmt(c.cloud_cover)}%</b></div>
   <div>Hembusan<b>${fmt(c.wind_gusts_10m, 0)} km/j</b></div></div>`;
  html += `<div class="wx-hours">${(w.hourly || []).map(h => `<div class="wx-h">${esc(h.time.slice(-5))}${icon(h.desc.icon)}<b>${fmt(h.temp, 0)}°</b>${h.pop != null ? h.pop + "%" : ""}</div>`).join("")}</div>`;
  if (aq && aq.us_aqi != null) {
    const [, col, txt] = aqiInfo(aq.us_aqi);
    html += `<div class="aqi"><div class="aqi-n" style="background:${col}">${fmt(aq.us_aqi)}</div><div class="aqi-t"><b>${txt}</b>Indeks kualitas udara (US AQI)</div></div>
    <div class="aqi-grid"><span>PM2.5<b>${fmt(aq.pm2_5, 1)} µg/m³</b></span><span>PM10<b>${fmt(aq.pm10, 1)} µg/m³</b></span><span>NO₂<b>${fmt(aq.nitrogen_dioxide, 1)} µg/m³</b></span><span>CO<b>${fmt(aq.carbon_monoxide, 0)} µg/m³</b></span><span>SO₂<b>${fmt(aq.sulphur_dioxide, 1)} µg/m³</b></span><span>O₃<b>${fmt(aq.ozone, 0)} µg/m³</b></span></div>`;
  }
  el.innerHTML = html;
}

/* grafik batang bertumpuk per menit */
function chartMinutes(s) {
  const W = 760, H = 230, m = { l: 34, r: 8, t: 10, b: 24 }, data = s.per_minute;
  const val = d => metric === "pcu" ? d.pcu : KEYS.reduce((a, k) => a + d[k], 0);
  const max = Math.max(4, ...data.map(val)), top = Math.ceil(max / 2) * 2 || 2;
  const bw = (W - m.l - m.r) / data.length, y = v => H - m.b - (v / top) * (H - m.t - m.b);
  let g = "";
  for (let i = 0; i <= 4; i++) { const v = top * i / 4; g += `<line x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}" stroke="#1f3652" stroke-dasharray="3 4"/><text x="${m.l - 6}" y="${y(v) + 3}" text-anchor="end">${fmt(v, metric === "pcu" ? 1 : 0)}</text>`; }
  data.forEach((d, i) => {
    const x = m.l + i * bw + 1.5; let acc = 0;
    const tip = `${new Date(d.t * 1000).toTimeString().slice(0, 5)} · ` + (metric === "pcu" ? `${fmt(d.pcu, 1)} SMP` : KEYS.filter(k => d[k]).map(k => `${CLS[k][0]} ${d[k]}`).join(", ") || "0 kendaraan");
    if (metric === "pcu") { const h = (d.pcu / top) * (H - m.t - m.b); g += `<rect x="${x}" y="${H - m.b - h}" width="${bw - 3}" height="${Math.max(h, 0)}" rx="3" fill="#37adf6"><title>${tip}</title></rect>`; }
    else KEYS.forEach(k => { if (!d[k]) return; const h = (d[k] / top) * (H - m.t - m.b); g += `<rect x="${x}" y="${H - m.b - acc - h}" width="${bw - 3}" height="${h}" fill="${CLS[k][1]}"><title>${tip}</title></rect>`; acc += h; });
    if (i % 5 === 0) g += `<text x="${x + bw / 2}" y="${H - 6}" text-anchor="middle">${new Date(d.t * 1000).toTimeString().slice(0, 5)}</text>`;
  });
  $("#chartMin").innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Grafik arus lalu lintas per menit">${g}</svg>`;
}

function chartComp(s) {
  const tot = s.total, R = 54, C = 2 * Math.PI * R; let off = 0, arcs = "";
  KEYS.forEach(k => { const v = s.totals[k]; if (!v) return; const len = v / tot * C; arcs += `<circle r="${R}" cx="70" cy="70" fill="none" stroke="${CLS[k][1]}" stroke-width="20" stroke-dasharray="${len} ${C - len}" stroke-dashoffset="${-off}" transform="rotate(-90 70 70)"><title>${CLS[k][0]}: ${v}</title></circle>`; off += len; });
  $("#chartComp").innerHTML = `<svg viewBox="0 0 140 140" width="150" height="150"><circle r="${R}" cx="70" cy="70" fill="none" stroke="#14283f" stroke-width="20"/>${arcs}<text x="70" y="68" text-anchor="middle" style="fill:#e6eef8;font-size:24px;font-weight:700">${fmt(tot)}</text><text x="70" y="86" text-anchor="middle">kendaraan</text></svg>
  <ul>${KEYS.map(k => `<li><i style="background:${CLS[k][1]}"></i>${CLS[k][0]}<b>${fmt(s.totals[k])}</b></li>`).join("")}</ul>`;
}

function chartSpeed(s) {
  const sp = s.speed, W = 360, H = 150, m = { l: 26, r: 6, t: 8, b: 22 }, bins = sp.bins, n = bins.length, bw = (W - m.l - m.r) / n, max = Math.max(1, ...sp.hist);
  let g = "";
  sp.hist.forEach((v, i) => { const h = v / max * (H - m.t - m.b), over = bins[i] >= sp.limit; g += `<rect x="${m.l + i * bw + 2}" y="${H - m.b - h}" width="${bw - 4}" height="${h}" rx="3" fill="${over ? "#ff6b5a" : "#37adf6"}"><title>${bins[i]}${i === n - 1 ? "+" : "–" + bins[i + 1]} km/j: ${v}</title></rect><text x="${m.l + i * bw + bw / 2}" y="${H - 6}" text-anchor="middle">${bins[i]}</text>`; });
  const lx = m.l + sp.limit / 10 * bw; g += `<line x1="${lx}" x2="${lx}" y1="${m.t}" y2="${H - m.b}" stroke="#ffc83c" stroke-dasharray="4 3"/><text x="${lx + 3}" y="${m.t + 8}" style="fill:#ffc83c">batas ${sp.limit}</text>`;
  $("#chartSpeed").innerHTML = `<svg viewBox="0 0 ${W} ${H}">${g}</svg>`;
  $("#speedStats").innerHTML = [["Rata-rata", sp.avg], ["P85", sp.p85], ["Maks", sp.max], ["> batas", sp.overspeed]].map(([a, b]) => `<div>${a}<b>${b == null ? "–" : fmt(b, a === "> batas" ? 0 : 0)}</b></div>`).join("");
}

function renderZone(s) {
  const z = s.zone, pct = Math.min(100, z.pcu / 14 * 100), col = ["#4fd18b", "#8fdc6a", "#ffd84d", "#ff9f43", "#ff6b5a"][z.level_i];
  $("#zoneBody").innerHTML = `<div class="zone-level" style="color:${col}">${z.level}</div><div class="gauge"><i style="width:${pct}%;background:${col}"></i></div>
  <div class="zone-sub" style="margin-top:8px">${fmt(z.count)} kendaraan · ${fmt(z.pcu, 1)} SMP di zona pengamatan (puncak ${fmt(z.peak)})</div>
  <div class="chips">${KEYS.filter(k => z.by[k]).map(k => `<span><i class="dot" style="background:${CLS[k][1]}"></i>${CLS[k][0]} ${z.by[k]}</span>`).join("") || '<span class="muted">Zona kosong</span>'}</div>
  <div class="zone-sub" style="margin-top:10px">Level bersifat indikatif (bukan LOS resmi).</div>`;
}

function renderLines(s) {
  $("#linesBody").innerHTML = s.lines.map(l => { const m = Math.max(1, l.d1, l.d2);
    return `<div class="line-item"><h3>${esc(l.name)}</h3>
    <div class="dir-row"><span style="min-width:74px">${esc(l.dir1)}</span><div class="bar"><i style="width:${l.d1 / m * 100}%"></i></div><b>${l.d1}</b></div>
    <div class="dir-row"><span style="min-width:74px">${esc(l.dir2)}</span><div class="bar"><i style="width:${l.d2 / m * 100}%;background:#ffc83c"></i></div><b>${l.d2}</b></div></div>`; }).join("") || '<span class="muted">Belum ada garis. Klik “Garis”.</span>';
}

function renderTracks(s) {
  $("#trackCount").textContent = s.tracks.length + " aktif";
  const lim = s.speed.limit;
  $("#tracksTbl tbody").innerHTML = s.tracks.map(t => `<tr class="${t.speed > lim ? "over" : ""}"><td>#${t.id}</td><td><i class="dot" style="background:${CLS[t.cls]?.[1] || "#999"}"></i>${esc(t.label)}</td><td>${t.speed == null ? "–" : fmt(t.speed, 0) + " km/j"}</td><td>${Math.round(t.conf * 100)}%</td><td>${t.in_roi ? "di zona" : "luar"}</td><td>${t.counted ? "terhitung" : t.coasting ? "terprediksi" : "terdeteksi"}</td></tr>`).join("") || '<tr><td colspan="6" class="muted">Belum ada kendaraan terlacak</td></tr>';
}
function renderEvents(s) {
  $("#events").innerHTML = s.recent.map(e => `<li><time>${e.t}</time><i class="dot" style="background:${CLS[e.cls]?.[1] || "#999"}"></i><span>${esc(CLS[e.cls]?.[0] || e.cls)} #${e.id} · ${esc(e.line)} · ${esc(e.dir)}${e.first ? "" : " (lintas ulang)"}</span><span class="sp">${e.speed == null ? "" : fmt(e.speed, 0) + " km/j"}</span></li>`).join("") || '<li class="muted">Belum ada kendaraan melintasi garis.</li>';
}

function render(p) {
  S = p;
  renderStatus(p.status); renderKpis(p.stats); renderWeather(p.weather);
  chartMinutes(p.stats); chartComp(p.stats); chartSpeed(p.stats); renderZone(p.stats); renderLines(p.stats); renderTracks(p.stats); renderEvents(p.stats);
  drawOverlay();
}

/* ---------------- editor di atas video ---------------- */
const ov = $("#overlay"), stage = $("#stage"), bar = $("#editbar");
function fit() { const r = stage.getBoundingClientRect(); ov.width = r.width * devicePixelRatio; ov.height = r.height * devicePixelRatio; drawOverlay(); }
addEventListener("resize", fit);
function drawOverlay() {
  const c = ov.getContext("2d"), W = ov.width, H = ov.height; c.clearRect(0, 0, W, H);
  if (!mode || !CFG) return;
  const dpr = devicePixelRatio, P = p => [p[0] * W, p[1] * H];
  const handle = (p, col) => { const [x, y] = P(p); c.beginPath(); c.arc(x, y, 8 * dpr, 0, 7); c.fillStyle = col; c.fill(); c.lineWidth = 2 * dpr; c.strokeStyle = "#fff"; c.stroke(); };
  if (mode === "lines") CFG.lines.forEach(l => { const a = P(l.p1), b = P(l.p2); c.strokeStyle = "#28b4ff"; c.lineWidth = 3 * dpr; c.beginPath(); c.moveTo(...a); c.lineTo(...b); c.stroke(); handle(l.p1, "#28b4ff"); handle(l.p2, "#28b4ff");
    const mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2, dx = b[0] - a[0], dy = b[1] - a[1], L = Math.hypot(dx, dy) || 1, nx = dy / L, ny = -dx / L; // panah arah 1 (kiri vektor)
    c.strokeStyle = "#ffc83c"; c.fillStyle = "#ffc83c"; c.beginPath(); c.moveTo(mx, my); c.lineTo(mx - nx * 28 * dpr, my - ny * 28 * dpr); c.stroke(); c.font = `${12 * dpr}px sans-serif`; c.fillText(l.dir1, mx - nx * 36 * dpr - 10, my - ny * 36 * dpr); });
  if (mode === "roi") { c.beginPath(); CFG.roi.forEach((p, i) => { const [x, y] = P(p); i ? c.lineTo(x, y) : c.moveTo(x, y); }); c.closePath(); c.fillStyle = "rgba(79,209,139,.15)"; c.fill(); c.strokeStyle = "#4fd18b"; c.lineWidth = 3 * dpr; c.stroke(); CFG.roi.forEach(p => handle(p, "#4fd18b")); }
  if (mode === "cal") calPts.forEach(p => handle(p, "#ffc83c")), calPts.length === 2 && (c.beginPath(), c.moveTo(...P(calPts[0])), c.lineTo(...P(calPts[1])), c.strokeStyle = "#ffc83c", c.lineWidth = 3 * dpr, c.stroke());
}
function pos(e) { const r = ov.getBoundingClientRect(); return [Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (e.clientY - r.top) / r.height))]; }
function nearest(p) {
  const pts = []; const r = ov.getBoundingClientRect(), W = r.width, H = r.height;
  if (mode === "lines") CFG.lines.forEach((l, i) => { pts.push({ i, k: "p1", p: l.p1 }); pts.push({ i, k: "p2", p: l.p2 }); });
  if (mode === "roi") CFG.roi.forEach((q, i) => pts.push({ i, k: "v", p: q }));
  let best = null, bd = 22; pts.forEach(h => { const d = Math.hypot((h.p[0] - p[0]) * W, (h.p[1] - p[1]) * H); if (d < bd) { bd = d; best = h; } }); return best;
}
ov.addEventListener("pointerdown", e => {
  const p = pos(e);
  if (mode === "cal") { if (calPts.length >= 2) calPts = []; calPts.push(p); drawOverlay(); renderEditBar(); return; }
  const h = nearest(p); if (h) { drag = h; ov.setPointerCapture(e.pointerId); }
});
ov.addEventListener("pointermove", e => {
  if (!drag) return; const p = pos(e);
  if (mode === "lines") CFG.lines[drag.i][drag.k] = p; else if (mode === "roi") CFG.roi[drag.i] = p;
  drawOverlay();
});
ov.addEventListener("pointerup", () => { if (!drag) return; drag = null; save(mode === "lines" ? { lines: CFG.lines } : { roi: CFG.roi }); });

function setMode(m) {
  mode = mode === m ? null : m; calPts = [];
  stage.classList.toggle("editing", !!mode);
  ["lines", "roi", "cal"].forEach(k => $({ lines: "#tLines", roi: "#tRoi", cal: "#tCal" }[k]).classList.toggle("on", mode === k));
  renderEditBar(); drawOverlay();
}
function renderEditBar() {
  if (!mode) { bar.hidden = true; return; } bar.hidden = false;
  if (mode === "lines") { bar.innerHTML = `<span>Seret titik biru untuk memindah garis. Panah kuning = arah “${esc(CFG.lines[0]?.dir1 || "Arah 1")}”.</span><button class="chip" id="eAdd">＋ Tambah garis</button><button class="chip" id="eDel">− Hapus garis terakhir</button><button class="chip" id="eFlip">⇄ Tukar nama arah</button>`;
    $("#eAdd").onclick = () => { const id = String.fromCharCode(65 + CFG.lines.length); CFG.lines.push({ id, name: "Garis " + id, p1: [0.1, 0.45 + 0.08 * CFG.lines.length], p2: [0.9, 0.45 + 0.08 * CFG.lines.length], dir1: "Arah 1", dir2: "Arah 2" }); save({ lines: CFG.lines }); drawOverlay(); };
    $("#eDel").onclick = () => { if (CFG.lines.length > 1) { CFG.lines.pop(); save({ lines: CFG.lines }); drawOverlay(); } };
    $("#eFlip").onclick = () => { CFG.lines.forEach(l => [l.dir1, l.dir2] = [l.dir2, l.dir1]); save({ lines: CFG.lines }); drawOverlay(); renderEditBar(); }; }
  if (mode === "roi") { bar.innerHTML = `<span>Seret titik hijau untuk membentuk zona pengamatan (kepadatan dihitung &amp; deteksi difokuskan di zona ini).</span><button class="chip" id="eRst">Reset zona</button>`;
    $("#eRst").onclick = () => { CFG.roi = [[.05, .3], [.95, .3], [.95, .95], [.05, .95]]; save({ roi: CFG.roi }); drawOverlay(); }; }
  if (mode === "cal") { const ready = calPts.length === 2; bar.innerHTML = `<span>${ready ? "Masukkan panjang nyata antara dua titik:" : `Klik dua titik pada objek yang panjangnya diketahui (mis. marka jalan, lebar lajur). Titik ke-${calPts.length + 1}…`}</span>${ready ? `<input id="eM" type="number" min="0.1" step="0.1" placeholder="meter"> <button class="chip" id="eOk">Terapkan</button>` : ""}<button class="chip" id="eClr">Hapus kalibrasi</button>${CFG.calibration?.m_per_px ? `<span class="muted">aktif: ${fmt(CFG.calibration.m_per_px * 100, 2)} cm/px</span>` : ""}`;
    $("#eClr").onclick = async () => { await api("/api/calibrate/clear", {}); await loadCfg(); toast("Kalibrasi dihapus (skala otomatis dipakai)"); renderEditBar(); };
    if (ready) $("#eOk").onclick = async () => { const m = parseFloat($("#eM").value); if (!(m > 0)) return toast("Isi panjang dalam meter");
      const W = S?.status.frame?.[0] || 960, H = S?.status.frame?.[1] || 540, px = Math.hypot((calPts[0][0] - calPts[1][0]) * W, (calPts[0][1] - calPts[1][1]) * H);
      const r = await api("/api/calibrate", { ref_px: px, ref_m: m }); if (r.error) return toast(r.error); await loadCfg(); toast("Kalibrasi diterapkan"); setMode(null); }; }
}
async function save(patch) { CFG = await api("/api/config", patch); }
async function loadCfg() { CFG = await api("/api/config"); }

/* ---------------- legenda & toggle tampilan ---------------- */
function buildStatic() {
  $("#legend").innerHTML = KEYS.map(k => `<span><i style="background:${CLS[k][1]}"></i>${CLS[k][0]}</span>`).join("");
  const labels = { boxes: "Kotak", labels: "Label", speed: "Kecepatan", trails: "Jejak", lines: "Garis", roi: "Zona" };
  $("#toggles").innerHTML = Object.entries(labels).map(([k, v]) => `<button class="chip ${CFG.display[k] ? "on" : ""}" data-k="${k}">${v}</button>`).join("");
  $("#toggles").onclick = async e => { const b = e.target.closest("button"); if (!b) return; CFG.display[b.dataset.k] = !CFG.display[b.dataset.k]; b.classList.toggle("on"); await save({ display: CFG.display }); };
  const s = CFG.source; $("#srcLink").href = /^https?:/.test(CFG.default_source) ? CFG.default_source : "#";
}

/* ---------------- pengaturan ---------------- */
function openSettings() {
  const c = CFG, ck = k => c.classes.includes(k) ? "checked" : "";
  $("#settingsBody").innerHTML = `
  <div class="f"><label>Sumber video (URL CCTV / RTSP / berkas / indeks kamera)</label><input type="text" id="sSrc" value="${esc(c.source)}">
    <div class="row" style="margin-top:8px"><button class="btn primary" id="sApplySrc">Terapkan sumber</button><button class="btn" id="sResetSrc">Pakai CCTV acuan</button></div>
    <div class="hint">CCTV acuan penelitian: Kota Malang (tautan tetap tersimpan sebagai bawaan).</div></div>
  <div class="f"><label>Detektor</label><select id="sDet"><option value="ssd" ${c.detector === "ssd" ? "selected" : ""}>MobileNet-SSD (bawaan, ringan)</option><option value="yolo" ${c.detector === "yolo" ? "selected" : ""}>YOLO (akurat, butuh ultralytics)</option></select>
    <input type="text" id="sYolo" value="${esc(c.yolo_model)}" style="margin-top:6px" placeholder="yolov8n.pt"></div>
  <div class="f"><label>Ambang keyakinan: <b id="vConf">${c.confidence}</b></label><input type="range" id="sConf" min="0.15" max="0.9" step="0.05" value="${c.confidence}"><div class="hint">Turunkan bila banyak kendaraan terlewat; naikkan bila banyak salah deteksi.</div></div>
  <div class="f"><label>Deteksi tiap N frame: <b id="vEv">${c.detect_every}</b></label><input type="range" id="sEv" min="1" max="6" step="1" value="${c.detect_every}"><div class="hint">1 = paling teliti (lebih berat). Frame lain diprediksi oleh pelacak.</div></div>
  <div class="f"><label>Lebar frame proses (px): <b id="vFw">${c.frame_width}</b></label><input type="range" id="sFw" min="480" max="1280" step="80" value="${c.frame_width}"></div>
  <div class="f"><label>Jenis kendaraan</label><div class="checks">${KEYS.map(k => `<label><input type="checkbox" data-c="${k}" ${ck(k)}>${CLS[k][0]}</label>`).join("")}</div><div class="hint">Truk hanya terdeteksi pada detektor YOLO.</div></div>
  <div class="f"><label>Batas kecepatan (km/jam)</label><input type="number" id="sLim" value="${c.speed_limit_kmh}" min="10" max="120"></div>
  <div class="f"><h3>Lokasi cuaca (Open-Meteo)</h3><label>Nama lokasi</label><input type="text" id="sLocN" value="${esc(c.location.name)}">
    <div class="row" style="margin-top:8px"><input type="number" step="0.0001" id="sLat" value="${c.location.lat}"><input type="number" step="0.0001" id="sLon" value="${c.location.lon}"></div>
    <div class="hint">Isi koordinat titik CCTV (lintang, bujur) agar cuaca &amp; kualitas udara sesuai lokasi.</div></div>
  <div class="f"><h3>Bobot SMP</h3><div class="row">${["car", "motorbike", "bus", "truck", "bicycle"].map(k => `<div><label>${CLS[k][0]}</label><input type="number" step="0.05" data-p="${k}" value="${c.pcu[k]}"></div>`).join("")}</div></div>
  <div class="f"><button class="btn primary" id="sSave" style="width:100%">Simpan pengaturan</button></div>`;
  $("#sConf").oninput = e => $("#vConf").textContent = e.target.value; $("#sEv").oninput = e => $("#vEv").textContent = e.target.value; $("#sFw").oninput = e => $("#vFw").textContent = e.target.value;
  $("#sApplySrc").onclick = async () => { await save({ source: $("#sSrc").value.trim() || DEFAULT_SRC }); toast("Sumber diperbarui"); };
  $("#sResetSrc").onclick = async () => { await api("/api/source/reset", {}); await loadCfg(); $("#sSrc").value = CFG.source; toast("Kembali ke CCTV acuan"); };
  $("#sSave").onclick = async () => {
    const pcu = {}; document.querySelectorAll("[data-p]").forEach(i => pcu[i.dataset.p] = parseFloat(i.value) || 1);
    const classes = [...document.querySelectorAll("[data-c]")].filter(i => i.checked).map(i => i.dataset.c);
    await save({ detector: $("#sDet").value, yolo_model: $("#sYolo").value.trim() || "yolov8n.pt", confidence: +$("#sConf").value, detect_every: +$("#sEv").value, frame_width: +$("#sFw").value,
      classes: classes.length ? classes : ["car"], speed_limit_kmh: +$("#sLim").value || 50, pcu,
      location: { name: $("#sLocN").value, lat: +$("#sLat").value, lon: +$("#sLon").value } });
    toast("Pengaturan disimpan"); closeSettings();
  };
  $("#drawer").classList.add("open"); $("#scrim").hidden = false; $("#drawer").setAttribute("aria-hidden", "false");
}
function closeSettings() { $("#drawer").classList.remove("open"); $("#scrim").hidden = true; $("#drawer").setAttribute("aria-hidden", "true"); }

/* ---------------- start ---------------- */
$("#btnSettings").onclick = openSettings; $("#btnCloseSettings").onclick = closeSettings; $("#scrim").onclick = closeSettings;
$("#tLines").onclick = () => setMode("lines"); $("#tRoi").onclick = () => setMode("roi"); $("#tCal").onclick = () => setMode("cal");
$("#tPause").onclick = async () => { const r = await api("/api/pause", { paused: !window._paused }); window._paused = r.paused; $("#tPause").textContent = r.paused ? "▶ Lanjut" : "⏸ Jeda"; };
$("#btnReset").onclick = async () => { if (confirm("Reset semua hitungan?")) { await api("/api/reset", {}); toast("Hitungan direset"); } };
$("#segMetric").onclick = e => { const b = e.target.closest("button"); if (!b) return; metric = b.dataset.m; document.querySelectorAll("#segMetric button").forEach(x => x.classList.toggle("on", x === b)); if (S) chartMinutes(S.stats); };
addEventListener("keydown", e => { if (e.key === "Escape") { closeSettings(); if (mode) setMode(mode); } });
setInterval(() => $("#clock").textContent = new Date().toLocaleTimeString("id-ID"), 1000);

(async () => {
  await loadCfg(); buildStatic(); fit();
  const es = new EventSource("/api/stream");
  es.onmessage = e => { try { render(JSON.parse(e.data)); } catch (err) { console.error(err); } };
  es.onerror = () => { $("#pill").className = "pill pill-err"; $("#pillText").textContent = "Server terputus"; };
  new ResizeObserver(fit).observe(stage);
})();
})();
