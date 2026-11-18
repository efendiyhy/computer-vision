(() => {
"use strict";
/* ============================== dasar ============================== */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const KEYS = ["car", "motorbike", "bus", "truck", "bicycle", "other"];
const LABEL = { car: "Mobil", motorbike: "Motor", bus: "Bus", truck: "Truk", bicycle: "Sepeda", other: "Lainnya" };
const DEFAULT_SRC = "https://cctvmalang.24hour.id/twentyfourhourid/proxy.php?id=767576969564466612969572";
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const colorOf = k => css("--c-" + k) || "#7a8691";
const fmt = (n, d = 0) => (n == null || isNaN(n)) ? "–" : Number(n).toLocaleString("id-ID", { maximumFractionDigits: d, minimumFractionDigits: d });
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const hhmm = t => new Date(t * 1000).toTimeString().slice(0, 5);
async function api(u, body) {
  const r = await fetch(u, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  try { return await r.json(); } catch { return {}; }
}
let toastT;
function toast(t) { const e = $("#toast"); e.textContent = t; e.hidden = false; clearTimeout(toastT); toastT = setTimeout(() => e.hidden = true, 2600); }
function setRes(sel, cls, txt) { const e = $(sel); e.className = "result " + cls; e.textContent = txt; }

let S = null, CFG = null, view = "live", metric = "count";
let tNow = () => Date.now() / 1000;

/* ============================== tema & navigasi ============================== */
$("#themeBtn").onclick = () => {
  const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  const next = cur === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("ev-theme", next); } catch (e) {}
  if (S) render();
};
const TITLES = { live: "Pemantauan", history: "Riwayat", source: "Sumber & lokasi", detect: "Deteksi", system: "Sistem" };
function route() {
  const v = (location.hash || "#live").slice(1);
  view = TITLES[v] ? v : "live";
  $$(".view").forEach(s => s.hidden = s.id !== "v-" + view);
  $$("#nav a").forEach(a => a.classList.toggle("on", a.dataset.view === view));
  $("#pageTitle").textContent = TITLES[view];
  document.title = TITLES[view] + " · EmisiSense Vision";
  if (view === "history") loadHistory();
  if (view === "source") initSourceView();
  if (view === "detect") initDetectView();
  if (view === "system") { checkUpdate(false); }
  if (view === "live") requestAnimationFrame(fitOverlay);
  if (S) render();
}
addEventListener("hashchange", route);

/* ============================== ikon cuaca ============================== */
function wxIcon(k) {
  const sun = '<circle cx="32" cy="32" r="10" fill="#f5b800"/><g stroke="#f5b800" stroke-width="3" stroke-linecap="round">' + [0, 45, 90, 135, 180, 225, 270, 315].map(a => { const r = a * Math.PI / 180; return `<line x1="${32 + 16 * Math.cos(r)}" y1="${32 + 16 * Math.sin(r)}" x2="${32 + 22 * Math.cos(r)}" y2="${32 + 22 * Math.sin(r)}"/>`; }).join("") + "</g>";
  const moon = '<path d="M40 14a18 18 0 1 0 12 30A16 16 0 0 1 40 14z" fill="#aebbd0"/>';
  const cloud = (c = "#a9b6c6", y = 0) => `<path d="M20 ${46 + y}h26a9 9 0 0 0 1-18 12 12 0 0 0-23-2 10 10 0 0 0-4 20z" fill="${c}"/>`;
  const drops = n => Array.from({ length: n }, (_, i) => `<line x1="${22 + i * 9}" y1="50" x2="${19 + i * 9}" y2="58" stroke="#3f7fe0" stroke-width="3" stroke-linecap="round"/>`).join("");
  const m = { clear: sun, clear_night: moon, partly: '<g transform="translate(-6,-6) scale(.8)">' + sun + "</g>" + cloud(), partly_night: '<g transform="translate(-4,-6) scale(.7)">' + moon + "</g>" + cloud(),
    cloudy: cloud("#92a1b4", 2), fog: cloud("#92a1b4", -2) + '<g stroke="#92a1b4" stroke-width="3" stroke-linecap="round"><line x1="16" y1="52" x2="48" y2="52"/><line x1="20" y1="58" x2="44" y2="58"/></g>',
    drizzle: cloud("#92a1b4", -4) + drops(3), rain: cloud("#7d8da1", -6) + drops(4), snow: cloud("#aebbd0", -6) + '<g fill="#fff"><circle cx="24" cy="54" r="2.5"/><circle cx="34" cy="58" r="2.5"/><circle cx="44" cy="54" r="2.5"/></g>',
    storm: cloud("#6f7f93", -6) + '<path d="M34 44l-6 10h6l-3 9 10-13h-6l4-6z" fill="#f5b800"/>' };
  return `<svg viewBox="0 0 64 64" aria-hidden="true">${m[k] || m.cloudy}</svg>`;
}
const AQI = [[50, "Baik"], [100, "Sedang"], [150, "Tidak sehat bagi kelompok sensitif"], [200, "Tidak sehat"], [300, "Sangat tidak sehat"], [1e9, "Berbahaya"]];
const compass = d => d == null ? "" : ["U", "TL", "T", "TG", "S", "BD", "B", "BL"][Math.round(d / 45) % 8];

/* ============================== tooltip grafik ============================== */
const tip = $("#tip");
function tipShow(html, e) { tip.innerHTML = html; tip.hidden = false; const w = tip.offsetWidth; tip.style.left = Math.min(innerWidth - w - 8, e.clientX + 14) + "px"; tip.style.top = (e.clientY + 16) + "px"; }
function tipHide() { tip.hidden = true; }
function bindTip(el, W) {
  if (el._tipBound) return; el._tipBound = true;
  el.addEventListener("pointermove", e => {
    const svg = el.querySelector("svg"); if (!svg || !el._cols) return;
    const r = svg.getBoundingClientRect(), x = (e.clientX - r.left) / r.width * W;
    let best = null; for (const c of el._cols) if (x >= c.x0 && x < c.x1) { best = c; break; }
    if (best) tipShow(best.tip, e); else tipHide();
  });
  el.addEventListener("pointerleave", tipHide);
}
const niceMax = v => { const raw = Math.max(v, 4) / 4, p = Math.pow(10, Math.floor(Math.log10(raw))); for (const m of [1, 2, 5, 10]) if (raw <= m * p) return m * p * 4; return 40 * p; };

/* grafik batang bertumpuk */
function stackedBars(el, data, o) {
  const W = o.w || 760, H = o.h || 220, m = { l: 38, r: 6, t: 8, b: 22 };
  const val = d => o.metric === "pcu" ? d.pcu : KEYS.reduce((a, k) => a + (d[k] || 0), 0);
  const top = niceMax(Math.max(1, ...data.map(val)));
  const bw = (W - m.l - m.r) / Math.max(1, data.length), y = v => H - m.b - v / top * (H - m.t - m.b);
  let g = "";
  for (let i = 0; i <= 4; i++) { const v = top * i / 4; g += `<line class="grid" x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}"/><text x="${m.l - 6}" y="${y(v) + 3.5}" text-anchor="end">${fmt(v, o.metric === "pcu" && top < 20 ? 1 : 0)}</text>`; }
  const cols = [];
  data.forEach((d, i) => {
    const x = m.l + i * bw, w = Math.max(1, bw - Math.min(3, bw * .25)); let acc = 0;
    if (o.metric === "pcu") { const h = d.pcu / top * (H - m.t - m.b); g += `<rect x="${x}" y="${H - m.b - h}" width="${w}" height="${h}" rx="1.5" fill="${css("--accent")}"/>`; }
    else KEYS.forEach(k => { if (!d[k]) return; const h = d[k] / top * (H - m.t - m.b); g += `<rect x="${x}" y="${H - m.b - acc - h}" width="${w}" height="${h}" fill="${colorOf(k)}"/>`; acc += h; });
    if (i % o.every === 0) g += `<text x="${x + bw / 2}" y="${H - 6}" text-anchor="middle">${esc(o.label(d, true))}</text>`;
    const detail = o.metric === "pcu" ? `${fmt(d.pcu, 1)} SMP` : (KEYS.filter(k => d[k]).map(k => `${LABEL[k]} ${d[k]}`).join(", ") || "tidak ada kendaraan");
    cols.push({ x0: x, x1: x + bw, tip: `<b>${esc(o.label(d, false))}</b><br>${detail}${o.extra ? o.extra(d) : ""}` });
  });
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(o.aria || "Grafik")}">${g}</svg>`; el._cols = cols; bindTip(el, W);
}

/* garis ganda: sumbu kiri & kanan, nilai null = putus */
function dualLine(el, xs, L, R, o = {}) {
  const W = 760, H = 220, m = { l: 40, r: 40, t: 10, b: 22 }, n = xs.length;
  const rng = a => { const v = a.filter(x => x != null); if (!v.length) return [0, 1]; let lo = Math.min(...v), hi = Math.max(...v); if (lo === hi) { lo -= 1; hi += 1; } const pad = (hi - lo) * .12; return [Math.max(0, lo - pad), hi + pad]; };
  const [l0, l1] = rng(L.vals), [r0, r1] = rng(R.vals);
  const X = i => m.l + (n <= 1 ? 0 : i / (n - 1) * (W - m.l - m.r)), YL = v => H - m.b - (v - l0) / (l1 - l0) * (H - m.t - m.b), YR = v => H - m.b - (v - r0) / (r1 - r0) * (H - m.t - m.b);
  let g = "";
  for (let i = 0; i <= 4; i++) { const f = i / 4; g += `<line class="grid" x1="${m.l}" x2="${W - m.r}" y1="${H - m.b - f * (H - m.t - m.b)}" y2="${H - m.b - f * (H - m.t - m.b)}"/><text x="${m.l - 6}" y="${H - m.b - f * (H - m.t - m.b) + 3.5}" text-anchor="end" style="fill:${L.color}">${fmt(l0 + f * (l1 - l0), L.d ?? 0)}</text><text x="${W - m.r + 6}" y="${H - m.b - f * (H - m.t - m.b) + 3.5}" style="fill:${R.color}">${fmt(r0 + f * (r1 - r0), R.d ?? 0)}</text>`; }
  const path = (vals, Y) => { let d = "", pen = false; vals.forEach((v, i) => { if (v == null) { pen = false; return; } d += (pen ? "L" : "M") + X(i).toFixed(1) + " " + Y(v).toFixed(1); pen = true; }); return d; };
  g += `<path d="${path(L.vals, YL)}" fill="none" stroke="${L.color}" stroke-width="2" stroke-linejoin="round"/><path d="${path(R.vals, YR)}" fill="none" stroke="${R.color}" stroke-width="2" stroke-dasharray="${R.dash || "0"}" stroke-linejoin="round"/>`;
  const step = Math.max(1, Math.round(n / 8)), cols = [], bw = (W - m.l - m.r) / Math.max(1, n - 1);
  xs.forEach((x, i) => { if (i % step === 0) g += `<text x="${X(i)}" y="${H - 6}" text-anchor="middle">${esc(o.label(x, true))}</text>`;
    cols.push({ x0: X(i) - bw / 2, x1: X(i) + bw / 2, tip: `<b>${esc(o.label(x, false))}</b><br>${L.name}: ${L.vals[i] == null ? "–" : fmt(L.vals[i], L.d ?? 0) + " " + L.unit}<br>${R.name}: ${R.vals[i] == null ? "–" : fmt(R.vals[i], R.d ?? 0) + " " + R.unit}` }); });
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img"><g>${g}</g></svg><div class="legend" style="margin-top:6px"><span><i style="background:${L.color}"></i>${L.name} (${L.unit})</span><span><i style="background:${R.color}"></i>${R.name} (${R.unit})</span></div>`;
  el._cols = cols; bindTip(el, W);
}

/* ============================== kartu pemantauan ============================== */
function renderStatus(p) {
  const st = p.status, el = $("#status");
  let s = "wait", t = "Menghubungkan", sub = "";
  if (p.demo && st.state === "live") { s = "demo"; t = "Mode demo"; }
  else if (st.paused) { s = "pause"; t = "Dijeda"; }
  else if (st.state === "live") { s = "live"; t = "Langsung"; sub = st.src_fps ? fmt(st.src_fps, 1) + " fps" : ""; }
  else if (st.state === "error") { s = "error"; t = "Terputus"; }
  el.dataset.s = s; $("#statusTxt").textContent = t; $("#statusSub").textContent = sub;
  $("#whereTxt").textContent = (CFG?.location?.name || "") + (st.kind && !p.demo ? " · " + (st.desc || "") : "");
  $("#footUrls").innerHTML = (p.urls || []).filter(u => !u.includes("localhost")).map(u => `<a href="${u}">${u}</a>`).join(" · ") || "–";
  $("#liveChip").hidden = !st.paused;
}

function renderCamMeta(p) {
  const st = p.status, sz = st.frame || st.source_size;
  if (sz && stage.dataset.ar !== sz.join()) { stage.dataset.ar = sz.join(); stage.style.aspectRatio = sz[0] + " / " + sz[1]; }
  $("#camMeta").innerHTML = `<b>Kamera</b>` + (p.demo ? `<span>Simulasi lalu lintas</span>` : `<span>${esc(st.desc || "Menyambung…")}</span>`) +
    `<span>${st.src_fps ? fmt(st.src_fps, 1) + " frame/detik" : "– frame/detik"}</span>` + (sz ? `<span>${sz[0]}×${sz[1]}</span>` : "") + `<span>${esc(st.detector)}</span>`;
}

function renderNotice(p) {
  const st = p.status, n = $("#notice"), s = p.stats;
  let html = "", cls = "info";
  if (st.state === "error") {
    cls = "err";
    const m = st.message || "";
    const tips = /403|menolak/i.test(m) ? "Server CCTV menolak akses dari komputer ini. Coba dari jaringan di Indonesia, atau gunakan alamat sumber lain." :
      /HTML|halaman web/i.test(m) ? "Alamat mengarah ke halaman web. Pakai alamat langsung ke aliran video (.m3u8, MJPEG, atau JPEG)." :
      /tidak dapat terhubung|Timeout|timed out/i.test(m) ? "Periksa koneksi internet server dan apakah alamatnya masih aktif." : "Buka Sumber & lokasi lalu jalankan Tes koneksi untuk melihat penyebabnya.";
    html = `<b>Video belum tersambung</b>${esc(m)}<br><span class="muted">${tips}</span>`;
  } else if (st.state === "menghubungkan") {
    html = `<b>Menghubungkan…</b>${esc(st.message || "")}`;
  } else if (st.state === "live" && !p.demo && st.src_fps && st.src_fps < 2.5 && st.frames_in > 8) {
    html = `<b>Sumber hanya mengirim ${fmt(st.src_fps, 1)} frame per detik</b>Video terlihat patah-patah karena kamera/server CCTV-nya yang lambat. Pelacak tetap berjalan, tetapi kecepatan kendaraan kurang teliti.`;
  } else if (st.state === "live" && !p.demo && st.frames_in > 150 && s.total === 0 && p.status.uptime_s > 90) {
    html = `<b>Belum ada kendaraan terhitung</b>Atur garis dan zona agar menutupi jalan (tombol Atur garis / Atur zona), turunkan ambang keyakinan, atau naikkan presisi di menu Deteksi. Objek mentah terakhir: ${st.raw_dets}, objek gerak: ${st.blobs}.`;
  }
  n.hidden = !html; if (html) { n.className = "notice " + cls; n.innerHTML = html; }
}

function renderReadout(s) {
  const lv = s.zone.level_i, lvc = ["--good", "--good", "--warn", "--bad", "--bad"][lv];
  $("#readout").innerHTML = `<div class="big"><div><div class="n">${fmt(s.total)}</div></div><div class="l">kendaraan terhitung<small>sejak ${s.since.slice(11, 16)} · ${fmt(s.this_minute)} menit ini</small></div></div>
  <div class="rd"><span>Laju per jam</span><b>${fmt(s.rate_per_hour)}</b><small>proyeksi dari rata-rata sesi</small></div>
  <div class="rd"><span>Volume SMP</span><b>${fmt(s.pcu_total, 1)}</b><small>satuan mobil penumpang</small></div>
  <div class="rd"><span>Kecepatan rata-rata</span><b>${s.speed.avg == null ? "–" : fmt(s.speed.avg, 0) + " km/j"}</b><small>estimasi · saat ini ${s.speed.now_avg == null ? "–" : fmt(s.speed.now_avg, 0) + " km/j"}</small></div>
  <div class="rd"><span>Di zona sekarang</span><b>${fmt(s.zone.count)}</b><small>puncak ${fmt(s.zone.peak)} kendaraan</small></div>
  <div class="rd"><span>Kepadatan</span><b style="color:var(${lvc})">${s.zone.level}</b><small><span class="lvl" style="--c:var(${lvc});margin:0">${[0, 1, 2, 3, 4].map(i => `<i class="${i <= lv ? "on" : ""}"></i>`).join("")}</span> ${fmt(s.zone.pcu, 1)} SMP di zona (indikatif)</small></div>
  <div class="chips">${KEYS.filter(k => s.zone.by[k]).map(k => `<span><i class="dot" style="background:${colorOf(k)}"></i>${LABEL[k]} ${s.zone.by[k]}</span>`).join("") || '<span class="muted">Zona kosong</span>'}</div>`;
}

function renderWeather(w) {
  const el = $("#weather");
  if (!w || !w.current) { el.innerHTML = `<div class="panel-head"><h2>Cuaca &amp; udara</h2></div><div class="empty">${w && w.error ? "Cuaca belum tersedia: " + esc(w.error) : "Memuat data cuaca…"}</div>`; return; }
  const c = w.current, u = w.units || {}, aq = w.air_quality || {};
  let h = `<div class="panel-head"><h2>Cuaca &amp; udara</h2><span class="muted small">${esc(w.location?.name || "")} · ${w.source === "demo" ? "data contoh" : "Open-Meteo"} · ${(w.updated || "").slice(11, 16)}</span></div>
  <div class="wx-top"><div class="wx-ico">${wxIcon(c.desc.icon)}</div><div><div class="wx-t">${fmt(c.temperature_2m, 1)}<sup>${esc(u.temperature_2m || "°C")}</sup></div><div class="wx-d">${esc(c.desc.text)} · terasa ${fmt(c.apparent_temperature, 1)}°</div></div></div>
  <div class="wx-kv"><div>Kelembapan<b>${fmt(c.relative_humidity_2m)}%</b></div><div>Angin<b>${fmt(c.wind_speed_10m, 1)} km/j ${compass(c.wind_direction_10m)}</b></div><div>Hujan<b>${fmt(c.precipitation, 1)} mm</b></div><div>Tekanan<b>${fmt(c.pressure_msl)} hPa</b></div><div>Awan<b>${fmt(c.cloud_cover)}%</b></div><div>Hembusan<b>${fmt(c.wind_gusts_10m)} km/j</b></div></div>
  <div class="wx-hours">${(w.hourly || []).map(x => `<div class="wx-h">${esc(String(x.time).slice(-5))}${wxIcon(x.desc.icon)}<b>${fmt(x.temp, 0)}°</b>${x.pop != null ? x.pop + "%" : ""}</div>`).join("")}</div>`;
  if (aq && aq.us_aqi != null) {
    const [, txt] = AQI.find(a => aq.us_aqi <= a[0]); const pos = Math.min(100, aq.us_aqi / 300 * 100);
    h += `<div class="aqi"><div class="aqi-top"><span>Indeks kualitas udara (US AQI)</span><b>${fmt(aq.us_aqi)}</b></div><div class="aqi-bar"><i style="left:calc(${pos}% - 1px)"></i></div><div class="muted small">${txt}</div>
    <div class="aqi-g" style="margin-top:10px"><span>PM2,5<b>${fmt(aq.pm2_5, 1)}</b></span><span>PM10<b>${fmt(aq.pm10, 1)}</b></span><span>NO₂<b>${fmt(aq.nitrogen_dioxide, 1)}</b></span><span>CO<b>${fmt(aq.carbon_monoxide, 0)}</b></span><span>SO₂<b>${fmt(aq.sulphur_dioxide, 1)}</b></span><span>O₃<b>${fmt(aq.ozone, 0)}</b></span></div><div class="muted small" style="margin-top:6px">µg/m³</div></div>`;
  }
  el.innerHTML = h;
}

function renderCharts(s) {
  stackedBars($("#chMin"), s.per_minute, { metric, every: 5, label: d => hhmm(d.t), aria: "Arus lalu lintas per menit" });
  const tot = s.total || 0;
  const R = 52, C = 2 * Math.PI * R; let off = 0, arcs = "";
  KEYS.forEach(k => { const v = s.totals[k]; if (!v) return; const len = v / tot * C; arcs += `<circle r="${R}" cx="70" cy="70" fill="none" stroke="${colorOf(k)}" stroke-width="18" stroke-dasharray="${len} ${C - len}" stroke-dashoffset="${-off}" transform="rotate(-90 70 70)"/>`; off += len; });
  $("#chComp").innerHTML = `<svg viewBox="0 0 140 140" role="img" aria-label="Komposisi jenis"><circle r="${R}" cx="70" cy="70" fill="none" stroke="${css("--line2")}" stroke-width="18"/>${arcs}<text x="70" y="70" text-anchor="middle" style="fill:${css("--ink")};font-size:26px;font-weight:650">${fmt(tot)}</text><text x="70" y="88" text-anchor="middle">kendaraan</text></svg>
  <ul>${KEYS.map(k => `<li><i class="dot" style="background:${colorOf(k)}"></i>${LABEL[k]}<b>${fmt(s.totals[k])}</b><em>${tot ? Math.round(s.totals[k] / tot * 100) + "%" : ""}</em></li>`).join("")}</ul>`;
  const sp = s.speed, W = 360, H = 140, m = { l: 26, r: 6, t: 8, b: 22 }, n = sp.bins.length, bw = (W - m.l - m.r) / n, mx = Math.max(1, ...sp.hist);
  let g = ""; const cols = [];
  sp.hist.forEach((v, i) => { const h = v / mx * (H - m.t - m.b), over = sp.bins[i] >= sp.limit; g += `<rect x="${m.l + i * bw + 2}" y="${H - m.b - h}" width="${bw - 4}" height="${h}" rx="1.5" fill="${over ? css("--bad") : css("--accent")}"/><text x="${m.l + i * bw + bw / 2}" y="${H - 6}" text-anchor="middle">${sp.bins[i]}</text>`; cols.push({ x0: m.l + i * bw, x1: m.l + (i + 1) * bw, tip: `<b>${sp.bins[i]}${i === n - 1 ? "+" : "–" + sp.bins[i + 1]} km/jam</b><br>${v} kendaraan` }); });
  const lx = m.l + sp.limit / 10 * bw; g += `<line x1="${lx}" x2="${lx}" y1="${m.t}" y2="${H - m.b}" stroke="${css("--paint")}" stroke-width="2" stroke-dasharray="4 3"/><text x="${lx + 4}" y="${m.t + 8}">batas ${sp.limit}</text>`;
  $("#chSpeed").innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Sebaran kecepatan">${g}</svg>`; $("#chSpeed")._cols = cols; bindTip($("#chSpeed"), W);
  $("#speedStats").innerHTML = [["Rata-rata", sp.avg], ["P85", sp.p85], ["Maks", sp.max], ["Melebihi batas", sp.overspeed]].map(([a, b]) => `<div>${a}<b>${b == null ? "–" : fmt(b, 0)}</b></div>`).join("");
}

function renderZoneLines(s) {
  $("#linesBox").innerHTML = s.lines.map(l => { const m = Math.max(1, l.d1, l.d2);
    return `<div class="ln"><h3>${esc(l.name)}${l.free ? "<small>kendaraan bergerak yang tidak melewati garis</small>" : ""}</h3>
    <div class="dir"><span>${esc(l.dir1)}</span><div class="bar"><i style="width:${l.d1 / m * 100}%;background:var(--accent)"></i></div><b>${l.d1}</b></div>
    <div class="dir"><span>${esc(l.dir2)}</span><div class="bar"><i style="width:${l.d2 / m * 100}%;background:var(--paint)"></i></div><b>${l.d2}</b></div></div>`; }).join("") || '<div class="empty">Belum ada garis. Tekan “Atur garis”.</div>';
}

function renderTables(s) {
  $("#trkCount").textContent = s.tracks.length + " aktif";
  $("#tblTracks tbody").innerHTML = s.tracks.map(t => `<tr class="${t.speed > s.speed.limit ? "over" : ""}"><td>#${t.id}</td><td><i class="dot" style="background:${colorOf(t.cls)}"></i>${esc(t.label)}</td><td class="num">${t.speed == null ? "–" : fmt(t.speed, 0) + " km/j"}</td><td class="num">${Math.round(t.conf * 100)}%</td><td>${t.in_roi ? "di zona" : "di luar zona"}</td><td>${t.counted ? "terhitung" : t.coasting ? "diprediksi" : "terdeteksi"}</td></tr>`).join("") || '<tr><td colspan="6" class="muted">Belum ada kendaraan terlacak.</td></tr>';
  $("#events").innerHTML = s.recent.map(e => `<li><time>${e.t}</time><i class="dot" style="background:${colorOf(e.cls)}"></i><span>${esc(LABEL[e.cls] || e.cls)} #${e.id} · ${esc(e.dir)}${e.first ? "" : " (lintas ulang)"}</span><span class="via" title="${e.via === "garis" ? "Melewati garis hitung" : "Terbukti bergerak, tanpa melewati garis"}">${e.via === "garis" ? esc(e.line) : "bergerak"}</span><span class="sp">${e.speed == null ? "" : fmt(e.speed, 0) + " km/j"}</span></li>`).join("") || '<li class="muted">Belum ada kendaraan terhitung.</li>';
}

/* ============================== lajur peristiwa ============================== */
const lane = $("#lane");
function drawLane() {
  const c = lane.getContext("2d"), dpr = devicePixelRatio || 1, w = lane.clientWidth, h = 44;
  if (lane.width !== Math.round(w * dpr)) { lane.width = Math.round(w * dpr); lane.height = Math.round(h * dpr); }
  c.setTransform(dpr, 0, 0, dpr, 0, 0); c.clearRect(0, 0, w, h);
  c.strokeStyle = css("--paint"); c.globalAlpha = .55; c.lineWidth = 1.5; c.setLineDash([8, 7]); c.beginPath(); c.moveTo(0, h / 2); c.lineTo(w, h / 2); c.stroke(); c.setLineDash([]); c.globalAlpha = 1;
  if (!S) return;
  const now = S.t + (performance.now() - S._recv) / 1000, SPAN = 120, size = { car: 14, motorbike: 8, bus: 26, truck: 21, bicycle: 6, other: 12 };
  (S.stats.ticker || []).forEach(e => {
    const age = now - e.ts; if (age < 0 || age > SPAN) return;
    const x = w - 14 - age / SPAN * (w - 28), y = e.d === 1 ? 11 : 25, L = size[e.cls] || 12;
    c.globalAlpha = Math.max(.25, 1 - age / SPAN * .7); c.fillStyle = colorOf(e.cls); c.beginPath(); c.roundRect ? c.roundRect(x - L / 2, y - 4, L, 8, 3) : c.rect(x - L / 2, y - 4, L, 8); c.fill();
  });
  c.globalAlpha = 1;
}
setInterval(drawLane, 150);

/* ============================== editor garis / zona / kalibrasi ============================== */
const ov = $("#overlay"), stage = $("#stage"), editor = $("#editor");
let mode = null, drag = null, calPts = [], selLine = 0;
function fitOverlay() { const r = stage.getBoundingClientRect(); const d = devicePixelRatio || 1; ov.width = Math.round(r.width * d); ov.height = Math.round(r.height * d); drawOverlay(); }
new ResizeObserver(fitOverlay).observe(stage);
function drawOverlay() {
  const c = ov.getContext("2d"), W = ov.width, H = ov.height, d = devicePixelRatio || 1; c.clearRect(0, 0, W, H);
  if (!mode || !CFG) return;
  const P = p => [p[0] * W, p[1] * H];
  const handle = (p, col, sel) => { const [x, y] = P(p); c.beginPath(); c.arc(x, y, (sel ? 10 : 8) * d, 0, 7); c.fillStyle = col; c.fill(); c.lineWidth = 2.5 * d; c.strokeStyle = "#fff"; c.stroke(); };
  if (mode === "lines") CFG.lines.forEach((l, i) => {
    const a = P(l.p1), b = P(l.p2), col = i === selLine ? "#f5b800" : "#5fb4ff";
    c.strokeStyle = col; c.lineWidth = 3 * d; c.beginPath(); c.moveTo(...a); c.lineTo(...b); c.stroke(); handle(l.p1, col, i === selLine); handle(l.p2, col, i === selLine);
    const mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2, dx = b[0] - a[0], dy = b[1] - a[1], L = Math.hypot(dx, dy) || 1, nx = dy / L, ny = -dx / L;
    c.fillStyle = "rgba(0,0,0,.65)"; c.font = `${12 * d}px sans-serif`; const t1 = `→ ${l.dir1}`, tw = c.measureText(t1).width;
    const tx = mx - nx * 34 * d, ty = my - ny * 34 * d; c.fillRect(tx - tw / 2 - 5 * d, ty - 11 * d, tw + 10 * d, 18 * d); c.fillStyle = "#fff"; c.textAlign = "center"; c.fillText(t1, tx, ty + 3 * d);
    c.strokeStyle = col; c.beginPath(); c.moveTo(mx, my); c.lineTo(mx - nx * 22 * d, my - ny * 22 * d); c.stroke();
  });
  if (mode === "roi") { c.beginPath(); CFG.roi.forEach((p, i) => { const [x, y] = P(p); i ? c.lineTo(x, y) : c.moveTo(x, y); }); c.closePath(); c.fillStyle = "rgba(95,180,255,.16)"; c.fill(); c.strokeStyle = "#5fb4ff"; c.lineWidth = 3 * d; c.stroke(); CFG.roi.forEach(p => handle(p, "#5fb4ff")); }
  if (mode === "cal") { if (calPts.length === 2) { c.beginPath(); c.moveTo(...P(calPts[0])); c.lineTo(...P(calPts[1])); c.strokeStyle = "#f5b800"; c.lineWidth = 3 * d; c.stroke(); } calPts.forEach(p => handle(p, "#f5b800")); }
}
const pos = e => { const r = ov.getBoundingClientRect(); return [Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (e.clientY - r.top) / r.height))]; };
function nearest(p) {
  const r = ov.getBoundingClientRect(), pts = [];
  if (mode === "lines") CFG.lines.forEach((l, i) => { pts.push({ i, k: "p1", p: l.p1 }); pts.push({ i, k: "p2", p: l.p2 }); });
  if (mode === "roi") CFG.roi.forEach((q, i) => pts.push({ i, k: "v", p: q }));
  let best = null, bd = 26; pts.forEach(h => { const dd = Math.hypot((h.p[0] - p[0]) * r.width, (h.p[1] - p[1]) * r.height); if (dd < bd) { bd = dd; best = h; } }); return best;
}
ov.addEventListener("pointerdown", e => {
  const p = pos(e);
  if (mode === "cal") { if (calPts.length >= 2) calPts = []; calPts.push(p); drawOverlay(); renderEditor(); return; }
  const h = nearest(p); if (h) { drag = h; if (mode === "lines" && selLine !== h.i) { selLine = h.i; renderEditor(); } ov.setPointerCapture(e.pointerId); }
});
ov.addEventListener("pointermove", e => { if (!drag) return; const p = pos(e); if (mode === "lines") CFG.lines[drag.i][drag.k] = p; else CFG.roi[drag.i] = p; drawOverlay(); });
ov.addEventListener("pointerup", () => { if (!drag) return; drag = null; save(mode === "lines" ? { lines: CFG.lines } : { roi: CFG.roi }); });

function setMode(m) {
  mode = mode === m ? null : m; calPts = [];
  stage.classList.toggle("editing", !!mode);
  [["lines", "#tLines"], ["roi", "#tRoi"], ["cal", "#tCal"]].forEach(([k, s]) => $(s).classList.toggle("on", mode === k));
  renderEditor(); drawOverlay();
}
function renderEditor() {
  if (!mode) { editor.hidden = true; return; } editor.hidden = false;
  if (mode === "lines") {
    selLine = Math.min(selLine, CFG.lines.length - 1); const l = CFG.lines[selLine];
    editor.innerHTML = `<p><b>Atur garis hitung.</b> Seret titik di ujung garis untuk memindahkannya; tekan titik untuk memilih garis. Panah kuning menunjukkan arah “${esc(l.dir1)}”. Letakkan garis melintang di jalur kendaraan.</p>
    <div class="tools"><select id="eSel" aria-label="Garis dipilih">${CFG.lines.map((x, i) => `<option value="${i}" ${i === selLine ? "selected" : ""}>${esc(x.name)}</option>`).join("")}</select>
    <input id="eName" value="${esc(l.name)}" aria-label="Nama garis" placeholder="Nama"><input id="eD1" value="${esc(l.dir1)}" aria-label="Nama arah 1" placeholder="Arah 1"><input id="eD2" value="${esc(l.dir2)}" aria-label="Nama arah 2" placeholder="Arah 2">
    <button class="btn sm" id="eFlip">Tukar arah</button><button class="btn sm" id="eAdd">Tambah garis</button><button class="btn sm danger" id="eDel" ${CFG.lines.length < 2 ? "disabled" : ""}>Hapus garis ini</button><button class="btn sm primary" id="eDone">Selesai</button></div>`;
    $("#eSel").onchange = e => { selLine = +e.target.value; renderEditor(); drawOverlay(); };
    const upd = () => { l.name = $("#eName").value.trim() || l.name; l.dir1 = $("#eD1").value.trim() || "Arah 1"; l.dir2 = $("#eD2").value.trim() || "Arah 2"; save({ lines: CFG.lines }); drawOverlay(); };
    ["#eName", "#eD1", "#eD2"].forEach(s => $(s).onchange = upd);
    $("#eFlip").onclick = () => { [l.dir1, l.dir2] = [l.dir2, l.dir1]; save({ lines: CFG.lines }); renderEditor(); drawOverlay(); };
    $("#eAdd").onclick = () => { const id = String.fromCharCode(65 + CFG.lines.length), y = Math.min(.9, .45 + .08 * CFG.lines.length); CFG.lines.push({ id, name: "Garis " + id, p1: [.1, y], p2: [.9, y], dir1: "Arah 1", dir2: "Arah 2" }); selLine = CFG.lines.length - 1; save({ lines: CFG.lines }); renderEditor(); drawOverlay(); };
    $("#eDel").onclick = () => { CFG.lines.splice(selLine, 1); selLine = 0; save({ lines: CFG.lines }); renderEditor(); drawOverlay(); };
    $("#eDone").onclick = () => setMode(null);
  }
  if (mode === "roi") {
    editor.innerHTML = `<p><b>Atur zona pengamatan.</b> Seret titik biru untuk membentuk zona. Kepadatan dihitung di dalam zona ini, dan deteksi difokuskan ke sini. Buat zona menutupi badan jalan saja agar bayangan dan trotoar tidak ikut.</p><div class="tools"><button class="btn sm" id="eRst">Kembalikan bawaan</button><button class="btn sm primary" id="eDone">Selesai</button></div>`;
    $("#eRst").onclick = () => { CFG.roi = [[.05, .3], [.95, .3], [.95, .95], [.05, .95]]; save({ roi: CFG.roi }); drawOverlay(); };
    $("#eDone").onclick = () => setMode(null);
  }
  if (mode === "cal") {
    const ready = calPts.length === 2, cal = CFG.calibration?.m_per_px;
    editor.innerHTML = `<p><b>Kalibrasi kecepatan.</b> ${ready ? "Masukkan panjang nyata antara kedua titik, lalu terapkan." : `Klik dua titik pada sesuatu yang panjang aslinya diketahui di jalan (marka putus-putus, lebar lajur, panjang zebra cross). Titik ke-${calPts.length + 1}…`}</p>
    <div class="tools">${ready ? `<input id="eM" type="number" min="0.1" step="0.1" placeholder="meter" aria-label="Panjang nyata dalam meter"><button class="btn sm primary" id="eOk">Terapkan</button>` : ""}<button class="btn sm" id="eClr">Hapus kalibrasi</button><button class="btn sm" id="eDone">Tutup</button>${cal ? `<span class="muted small">aktif: ${fmt(cal * 100, 2)} cm per piksel</span>` : ""}</div>`;
    $("#eDone").onclick = () => setMode(null);
    $("#eClr").onclick = async () => { await api("/api/calibrate/clear", {}); await loadCfg(); toast("Kalibrasi dihapus"); renderEditor(); };
    if (ready) $("#eOk").onclick = async () => { const m = parseFloat($("#eM").value); if (!(m > 0)) return toast("Isi panjang dalam meter");
      const fr = S?.status.frame || [800, 450], px = Math.hypot((calPts[0][0] - calPts[1][0]) * fr[0], (calPts[0][1] - calPts[1][1]) * fr[1]);
      const r = await api("/api/calibrate", { ref_px: px, ref_m: m }); if (r.error) return toast(r.error); await loadCfg(); toast("Kalibrasi diterapkan"); setMode(null); };
  }
}
async function save(patch) { const r = await api("/api/config", patch); if (!r.error) CFG = r; return r; }
async function loadCfg() { CFG = await api("/api/config"); }

$("#tLines").onclick = () => setMode("lines"); $("#tRoi").onclick = () => setMode("roi"); $("#tCal").onclick = () => setMode("cal");
$("#tFull").onclick = () => { if (document.fullscreenElement) document.exitFullscreen(); else stage.requestFullscreen?.(); };
$("#tPause").onclick = async () => { const r = await api("/api/pause", { paused: !(S?.status.paused) }); toast(r.paused ? "Pemrosesan dijeda" : "Pemrosesan dilanjutkan"); };
$("#btnReset").onclick = async () => { if (confirm("Kosongkan hitungan di layar? Data yang sudah tersimpan tidak dihapus.")) { await api("/api/reset", {}); toast("Tampilan hitungan dikosongkan"); } };
$("#segMetric").onclick = e => { const b = e.target.closest("button"); if (!b) return; metric = b.dataset.m; $$("#segMetric button").forEach(x => x.classList.toggle("on", x === b)); if (S) renderCharts(S.stats); };
addEventListener("keydown", e => { if (e.key === "Escape" && mode) setMode(mode); });
document.addEventListener("fullscreenchange", () => setTimeout(fitOverlay, 50));

function buildLegend() {
  $("#legend").innerHTML = KEYS.map(k => `<span><i style="background:${colorOf(k)}"></i>${LABEL[k]}</span>`).join("");
  const lab = { boxes: "Kotak", labels: "Label", speed: "Kecepatan", trails: "Jejak", lines: "Garis", roi: "Zona", raw: "Deteksi mentah" };
  $("#toggles").innerHTML = Object.entries(lab).map(([k, v]) => `<button data-k="${k}" class="${CFG.display[k] ? "on" : ""}" aria-pressed="${!!CFG.display[k]}">${v}</button>`).join("");
  $("#toggles").onclick = async e => { const b = e.target.closest("button"); if (!b) return; CFG.display[b.dataset.k] = !CFG.display[b.dataset.k]; b.classList.toggle("on"); b.setAttribute("aria-pressed", CFG.display[b.dataset.k]); await save({ display: CFG.display }); };
}

/* ============================== riwayat ============================== */
let histH = 24;
async function loadHistory() {
  if (view !== "history") return;
  try {
    const r = await api(`/api/history?hours=${histH}`), d = r.data, day = r.bucket >= 6 * 3600, long = r.bucket >= 3600;
    const lab = (x, short) => { const t = x.t ?? x, dt = new Date(t * 1000); const dm = `${dt.getDate()}/${dt.getMonth() + 1}`; return day ? dm : long ? (short ? `${dm} ${String(dt.getHours()).padStart(2, "0")}:00` : `${dm} ${hhmm(t)}`) : hhmm(t); };
    const every = Math.max(1, Math.round(d.length / 8));
    stackedBars($("#chHist"), d, { metric: "count", every, label: lab, aria: "Volume kendaraan", extra: x => (x.speed != null ? `<br>kecepatan rata-rata ${fmt(x.speed, 0)} km/j` : "") + (x.temp != null ? `<br>suhu ${fmt(x.temp, 1)}°C` : "") + (x.pm2_5 != null ? `<br>PM2,5 ${fmt(x.pm2_5, 1)} µg/m³` : "") });
    const tot = d.reduce((a, x) => a + KEYS.reduce((b, k) => b + (x[k] || 0), 0), 0), bucket = r.bucket >= 3600 ? r.bucket / 3600 + " jam" : r.bucket / 60 + " menit";
    $("#histNote").textContent = `${fmt(tot)} kendaraan tercatat pada rentang ini. Satu batang = ${bucket}. Arahkan kursor untuk melihat rincian.`;
    dualLine($("#chHistLine"), d, { name: "Kecepatan rata-rata", color: css("--accent"), vals: d.map(x => x.speed), unit: "km/j" }, { name: "Suhu", color: css("--c-motorbike"), vals: d.map(x => x.temp), unit: "°C", d: 1, dash: "5 4" }, { label: lab });
    dualLine($("#chHistAir"), d, { name: "PM2,5", color: css("--c-truck"), vals: d.map(x => x.pm2_5), unit: "µg/m³", d: 1 }, { name: "Kendaraan", color: css("--c-bus"), vals: d.map(x => KEYS.reduce((b, k) => b + (x[k] || 0), 0)), unit: "kend." }, { label: lab });
  } catch (e) { /* coba lagi pada siklus berikutnya */ }
}
$("#segHist").onclick = e => { const b = e.target.closest("button"); if (!b) return; histH = +b.dataset.h; $$("#segHist button").forEach(x => x.classList.toggle("on", x === b)); loadHistory(); };
setInterval(loadHistory, 30000);
$$("[data-exp]").forEach(a => a.onclick = e => { e.preventDefault(); const q = new URLSearchParams(); if ($("#dFrom").value) q.set("from", $("#dFrom").value); if ($("#dTo").value) q.set("to", $("#dTo").value); location.href = `/api/export/${a.dataset.exp}.csv?${q}`; });

/* ============================== sumber & lokasi ============================== */
let srcDirty = false, locDirty = false;
function initSourceView() {
  if (!CFG) return;
  if (!srcDirty) $("#srcInput").value = CFG.source;
  if (!locDirty) { $("#locName").value = CFG.location.name; $("#locLat").value = CFG.location.lat; $("#locLon").value = CFG.location.lon; }
}
$("#srcInput").oninput = () => srcDirty = true;
["#locName", "#locLat", "#locLon"].forEach(i => $(i).oninput = () => locDirty = true);
$$("[data-preset]").forEach(b => b.onclick = () => { $("#srcInput").value = b.dataset.preset === "default" ? (CFG.default_source || DEFAULT_SRC) : b.dataset.preset; srcDirty = true; });
$("#srcTest").onclick = async () => {
  const v = $("#srcInput").value.trim(); if (!v) return setRes("#srcResult", "err", "Isi alamat sumber terlebih dahulu.");
  setRes("#srcResult", "wait", "Menguji sumber (membaca video beberapa detik)…");
  try {
    const r = await api("/api/source/test", { source: v });
    if (!r.ok) return setRes("#srcResult", "err", r.message || "Gagal");
    const slow = r.fps && r.fps < 2.5 ? ` Frame rate sumber rendah, video akan tampak patah-patah (batas dari kamera/server, bukan dari aplikasi).` : "";
    setRes("#srcResult", slow ? "wait" : "ok", `Terhubung: ${r.desc}, ${r.width}×${r.height}, ${fmt(r.fps, 1)} frame/detik, frame pertama ${r.first_ms} ms.${slow}`);
  } catch (e) { setRes("#srcResult", "err", "Server tidak merespons."); }
};
$("#srcApply").onclick = async () => { const v = $("#srcInput").value.trim() || DEFAULT_SRC; await save({ source: v }); srcDirty = false; setRes("#srcResult", "ok", "Sumber diterapkan dan disimpan. Hitungan sesi dimulai ulang; data lama tetap tersimpan."); toast("Sumber diterapkan"); };
$("#srcFile").onchange = async e => {
  const f = e.target.files[0]; if (!f) return; setRes("#srcResult", "wait", `Mengunggah ${f.name}…`);
  const fd = new FormData(); fd.append("file", f);
  try { const r = await (await fetch("/api/source/upload", { method: "POST", body: fd })).json(); if (r.error) return setRes("#srcResult", "err", r.error); await loadCfg(); srcDirty = false; $("#srcInput").value = CFG.source; setRes("#srcResult", "ok", "Video diunggah dan dipakai sebagai sumber."); } catch (err) { setRes("#srcResult", "err", "Unggah gagal."); }
};
$("#geoBtn").onclick = geo; $("#geoQ").onkeydown = e => { if (e.key === "Enter") geo(); };
async function geo() {
  const q = $("#geoQ").value.trim(); if (q.length < 2) return; $("#geoRes").innerHTML = '<li class="muted">Mencari…</li>';
  try {
    const r = await api("/api/geocode?q=" + encodeURIComponent(q));
    if (r.error) { $("#geoRes").innerHTML = `<li class="muted">${esc(r.error)}</li>`; return; }
    $("#geoRes").innerHTML = r.results.map((x, i) => `<li data-i="${i}">${esc(x.name)}<small>${esc(x.admin)} · ${x.lat.toFixed(4)}, ${x.lon.toFixed(4)}</small></li>`).join("") || '<li class="muted">Tidak ditemukan. Coba nama kota atau kecamatan.</li>';
    $("#geoRes").onclick = e => { const li = e.target.closest("li[data-i]"); if (!li) return; const x = r.results[+li.dataset.i]; $("#locName").value = [x.name, x.admin.split(",").pop().trim()].filter(Boolean).join(", "); $("#locLat").value = x.lat; $("#locLon").value = x.lon; locDirty = true; };
  } catch (e) { $("#geoRes").innerHTML = '<li class="muted">Pencarian gagal.</li>'; }
}
$("#locApply").onclick = async () => {
  const lat = parseFloat($("#locLat").value), lon = parseFloat($("#locLon").value);
  if (isNaN(lat) || isNaN(lon)) return setRes("#locResult", "err", "Lintang dan bujur harus berupa angka.");
  const r = await api("/api/config", { location: { name: $("#locName").value.trim(), lat, lon } });
  if (r.error) return setRes("#locResult", "err", r.error);
  CFG = r; locDirty = false; setRes("#locResult", "wait", "Lokasi disimpan. Mengambil data cuaca…"); toast("Lokasi cuaca diperbarui");
};
$("#locNow").onclick = async () => { await api("/api/config", { location: CFG.location }); setRes("#locResult", "wait", "Memuat ulang cuaca…"); };
function renderSourceStatus(p) {
  if (view !== "source") return; const st = p.status, w = p.weather || {};
  const row = (a, b, c = "") => `<dt>${a}</dt><dd class="${c}">${b}</dd>`;
  $("#srcActive").innerHTML = row("Sumber aktif", esc(p.demo ? "Simulasi (mode demo)" : (CFG?.source || "-"))) + row("Jenis", esc(st.desc || "–")) + row("Status", esc(st.state === "live" ? "Terhubung" : st.message || st.state), st.state === "live" ? "ok" : st.state === "error" ? "bad" : "warn") +
    row("Frame/detik", st.src_fps ? fmt(st.src_fps, 1) : "–", st.src_fps && st.src_fps < 2.5 ? "warn" : "") + row("Resolusi asli", st.source_size ? st.source_size.join("×") : "–");
  if (!$("#locResult").classList.contains("err") || w.updated) {
    if (w.error) setRes("#locResult", "err", "Cuaca gagal diambil: " + w.error);
    else if (w.updated && !locDirty) setRes("#locResult", "ok", `Cuaca diperbarui ${w.updated.slice(11, 19)} untuk ${w.location?.name || ""} (${w.location?.lat}, ${w.location?.lon}).`);
  }
}

/* ============================== pengaturan deteksi ============================== */
let saveT;
function queueSave(patch) { Object.assign(pendingPatch, patch); $("#saveState").textContent = "Menyimpan…"; clearTimeout(saveT); saveT = setTimeout(async () => { const p = pendingPatch; pendingPatch = {}; const r = await save(p); $("#saveState").textContent = r.error ? "Gagal menyimpan" : "Tersimpan"; }, 450); }
let pendingPatch = {};
function initDetectView() {
  if (!CFG) return; const c = CFG;
  $$("#optQuality button").forEach(b => { b.classList.toggle("on", +b.dataset.q === c.quality); b.onclick = () => { $$("#optQuality button").forEach(x => x.classList.toggle("on", x === b)); queueSave({ quality: +b.dataset.q }); }; });
  const rng = (id, out, key, f = v => v) => { const el = $(id); el.value = c[key]; $(out).textContent = f(c[key]); el.oninput = () => { $(out).textContent = f(el.value); queueSave({ [key]: +el.value }); }; };
  rng("#optConf", "#vConf", "confidence", v => fmt(+v, 2)); rng("#optFw", "#vFw", "frame_width", v => v + " px"); rng("#optSf", "#vSf", "stream_fps", v => v + " fps"); rng("#optJq", "#vJq", "jpeg_quality");
  $("#optMotion").checked = c.use_motion; $("#optMotion").onchange = e => queueSave({ use_motion: e.target.checked });
  $("#optOther").checked = c.allow_other; $("#optOther").onchange = e => queueSave({ allow_other: e.target.checked });
  $("#optDet").value = c.detector; $("#optDet").onchange = e => queueSave({ detector: e.target.value });
  $("#optYolo").value = c.yolo_model; $("#optYolo").onchange = e => queueSave({ yolo_model: e.target.value.trim() || "yolov8n.pt" });
  $("#optLim").value = c.speed_limit_kmh; $("#optLim").onchange = e => queueSave({ speed_limit_kmh: +e.target.value || 50 });
  $("#optClasses").innerHTML = KEYS.filter(k => k !== "other").map(k => `<label><input type="checkbox" data-c="${k}" ${c.classes.includes(k) ? "checked" : ""}><i class="dot" style="background:${colorOf(k)};margin:0"></i>${LABEL[k]}</label>`).join("");
  $("#optClasses").onchange = () => { const cl = $$("#optClasses input").filter(i => i.checked).map(i => i.dataset.c); queueSave({ classes: cl.length ? cl : ["car"] }); };
  $("#optPcu").innerHTML = KEYS.map(k => `<label>${LABEL[k]}<input type="number" step="0.05" min="0" data-p="${k}" value="${c.pcu[k] ?? 1}"></label>`).join("");
  $("#optPcu").onchange = () => { const p = {}; $$("#optPcu input").forEach(i => p[i.dataset.p] = parseFloat(i.value) || 1); queueSave({ pcu: p }); };
  const lab = { boxes: "Kotak", labels: "Label", speed: "Kecepatan", trails: "Jejak", lines: "Garis", roi: "Zona", raw: "Deteksi mentah" };
  $("#optDisplay").innerHTML = Object.entries(lab).map(([k, v]) => `<label><input type="checkbox" data-d="${k}" ${c.display[k] ? "checked" : ""}>${v}</label>`).join("");
  $("#optDisplay").onchange = () => { const d = {}; $$("#optDisplay input").forEach(i => d[i.dataset.d] = i.checked); queueSave({ display: d }); };
  const cal = c.calibration || {};
  $("#calInfo").innerHTML = cal.m_per_px ? `<dt>Status</dt><dd class="ok">aktif</dd><dt>Skala</dt><dd>${fmt(cal.m_per_px * 100, 2)} cm/piksel</dd><dt>Acuan</dt><dd>${fmt(cal.ref_m, 1)} m = ${fmt(cal.ref_px, 0)} piksel</dd>` : `<dt>Status</dt><dd class="warn">belum dikalibrasi (skala otomatis)</dd>`;
  $("#goCal").onclick = () => setTimeout(() => setMode("cal"), 80);
  $("#calClear").onclick = async () => { await api("/api/calibrate/clear", {}); await loadCfg(); initDetectView(); toast("Kalibrasi dihapus"); };
}

/* ============================== sistem: diagnosa & pembaruan ============================== */
function renderSystem(p) {
  if (view !== "system") return; const st = p.status, s = p.stats, sto = s.storage;
  const row = (a, b, c = "") => `<dt>${a}</dt><dd class="${c}">${b}</dd>`;
  const age = st.last_frame_age, fpsC = st.src_fps && st.src_fps < 2.5 ? "warn" : "";
  $("#diag").innerHTML = row("Status", esc(st.state === "live" ? "Terhubung" : st.state), st.state === "live" ? "ok" : st.state === "error" ? "bad" : "warn") + row("Jenis sumber", esc(st.desc || "–")) +
    row("Frame masuk", st.src_fps ? fmt(st.src_fps, 1) + " /detik" : "–", fpsC) + row("Video ke browser", fmt(st.stream_fps, 1) + " /detik") + row("Waktu per deteksi", st.det_ms ? fmt(st.det_ms, 0) + " ms" : "–", st.det_ms > 400 ? "warn" : "") +
    row("Objek mentah (terakhir)", fmt(st.raw_dets)) + row("Objek gerak (terakhir)", fmt(st.blobs)) + row("Trek aktif", fmt(st.tracks)) + row("Frame terakhir", age == null ? "–" : fmt(age, 1) + " detik lalu", age > 5 ? "bad" : "") +
    row("Sambung ulang", fmt(st.reconnects)) + row("Waktu aktif", fmt(st.uptime_s / 60, 0) + " menit") + row("Detektor", esc(st.detector));
  $("#diagMsg").textContent = st.message || "";
  $("#storInfo").innerHTML = sto ? row("Berkas", esc(sto.path)) + row("Kejadian", fmt(sto.events)) + row("Menit tercatat", fmt(sto.minutes)) + row("Rekaman cuaca", fmt(sto.weather)) + row("Ukuran", fmt(sto.size_kb, 0) + " KB") + row("Data pertama", esc(sto.first ? sto.first.replace("T", " ").slice(0, 16) : "–")) + row("Data terakhir", esc(sto.last ? sto.last.replace("T", " ").slice(0, 16) : "–")) + row("Penulisan terakhir", esc(sto.last_write ? sto.last_write.slice(11, 19) : "–")) + row("Galat tulis", fmt(sto.errors), sto.errors ? "bad" : "ok") : "";
  $("#netInfo").innerHTML = row("Alamat jaringan lokal", (p.urls || []).map(u => `<a href="${u}">${u}</a>`).join("<br>") || "–") + row("Versi aplikasi", esc(p.version));
}
let upd = null;
async function checkUpdate(force) {
  const r = await api("/api/update/check" + (force ? "?force=1" : "")); upd = r; renderUpdate(); $("#updBadge").hidden = !r.available;
}
function renderUpdate() {
  if (!upd) return; const u = upd, row = (a, b, c = "") => `<dt>${a}</dt><dd class="${c}">${b}</dd>`;
  $("#verInfo").innerHTML = row("Versi", esc(u.version)) + (u.git ? row("Commit terpasang", `${esc(u.commit)} · ${esc((u.date || "").slice(0, 10))}`) + row("Perubahan terakhir", esc(u.subject || "")) : row("Instalasi", "bukan git", "warn")) + row("Terakhir diperiksa", esc((u.checked || "").replace("T", " ")));
  let h = "";
  if (u.error) h = `<div class="notice err"><b>Tidak dapat memeriksa pembaruan</b>${esc(u.error)}</div>`;
  else if (u.available) h = `<div class="notice info"><b>${u.behind} pembaruan tersedia</b>Data dan pengaturan Anda tidak terhapus. Aplikasi akan mulai ulang sekitar 10 detik.</div>${u.changes.map(c => `<div class="item"><time>${esc(c.date)}</time>${esc(c.subject)}</div>`).join("")}
    <div class="actions"><button class="btn primary" id="updGo" ${u.dirty ? "disabled" : ""}>Perbarui dan mulai ulang</button>${u.dirty ? '<span class="muted small">Ada perubahan lokal pada berkas kode; perbarui manual.</span>' : ""}</div>`;
  else h = `<div class="notice"><b>Sudah versi terbaru</b>Tidak ada perubahan baru di GitHub.</div>`;
  $("#updBody").innerHTML = h;
  const go = $("#updGo"); if (go) go.onclick = applyUpdate;
}
$("#updCheck").onclick = async () => { $("#updBody").innerHTML = '<div class="empty">Memeriksa GitHub…</div>'; await checkUpdate(true); };
async function applyUpdate() {
  $("#updBody").innerHTML = '<div class="notice info"><b>Memperbarui…</b>Mengunduh perubahan dan memasang dependensi. Jangan tutup halaman ini.</div>';
  const r = await api("/api/update/apply", { restart: true });
  if (!r.ok) { $("#updBody").innerHTML = `<div class="notice err"><b>Pembaruan gagal</b>${esc(r.message || "")}</div>`; return; }
  $("#updBody").innerHTML = '<div class="notice info"><b>Pembaruan terpasang. Memulai ulang…</b>Halaman akan dimuat ulang otomatis.</div>';
  let down = false;
  const t = setInterval(async () => { try { const x = await fetch("/api/state", { cache: "no-store" }); if (x.ok && down) { clearInterval(t); location.reload(); } } catch (e) { down = true; } }, 1500);
  setTimeout(() => { if (!down) location.reload(); }, 25000);
}
setInterval(() => checkUpdate(false), 30 * 60 * 1000);

/* ============================== siklus render ============================== */
function render() {
  if (!S) return; const p = S;
  renderStatus(p);
  if (view === "live") { renderCamMeta(p); renderNotice(p); renderReadout(p.stats); renderWeather(p.weather); renderCharts(p.stats); renderZoneLines(p.stats); renderTables(p.stats); drawOverlay(); }
  renderSourceStatus(p); renderSystem(p);
}
setInterval(() => $("#clock").textContent = new Date().toLocaleTimeString("id-ID"), 1000);

(async () => {
  await loadCfg(); buildLegend(); $("#srcLink").href = CFG.default_source || DEFAULT_SRC;
  route(); fitOverlay(); checkUpdate(false);
  const es = new EventSource("/api/stream");
  es.onmessage = e => { try { S = JSON.parse(e.data); S._recv = performance.now(); render(); } catch (err) { console.error(err); } };
  es.onerror = () => { const el = $("#status"); el.dataset.s = "error"; $("#statusTxt").textContent = "Server terputus"; $("#statusSub").textContent = ""; };
})();
})();
