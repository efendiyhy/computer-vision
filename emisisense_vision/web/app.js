(() => {
"use strict";
/* ============================== dasar ============================== */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const KEYS = ["car", "motorbike", "bus", "truck", "bicycle", "other"];
const LABEL = { car: "Mobil", motorbike: "Motor", bus: "Bus", truck: "Truk", bicycle: "Sepeda", other: "Lainnya", person: "Pejalan kaki" };
const ALLK = [...KEYS, "person"];
const ZONE = "#22d3ee", LINE_COLORS = ["#ffd400", "#ff4fa3", "#7cff4f", "#ff8a00", "#c77dff", "#ffffff"];
const DEFAULT_SRC = "https://cctvmalang.24hour.id/twentyfourhourid/proxy.php?id=767576969564466612969572";
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const colorOf = k => css("--c-" + k) || "#7a8691";
const fmt = (n, d = 0) => (n == null || isNaN(n)) ? "–" : Number(n).toLocaleString("id-ID", { maximumFractionDigits: d, minimumFractionDigits: d });
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const TZ = "Asia/Jakarta"; // semua waktu ditampilkan WIB (GMT+7), apa pun zona waktu perangkat
const WIBF = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
const wibParts = t => Object.fromEntries(WIBF.formatToParts(new Date(t * 1000)).map(p => [p.type, p.value]));
const hhmm = t => { const p = wibParts(t); return `${p.hour}:${p.minute}`; };
async function api(u, body) {
  const r = await fetch(u, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  try { return await r.json(); } catch { return {}; }
}
let toastT;
function toast(t, ms = 2600) { const e = $("#toast"); e.textContent = t; e.hidden = false; clearTimeout(toastT); toastT = setTimeout(() => e.hidden = true, ms); }
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
  syncBars();
};
/* jembatan ke aplikasi Android (ada hanya di dalam aplikasi) */
const NA = () => window.EmisiApp || null;
function syncBars() {
  const a = NA(); if (!a || !a.setBars) return;
  const cs = getComputedStyle(document.documentElement), dark = (document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")) === "dark";
  const top = cs.getPropertyValue("--bg").trim() || "#ecf0f3", bot = cs.getPropertyValue("--rail").trim() || "#1c232b";
  try { a.setBars(top, bot, dark); } catch (e) { /* abaikan */ }
}
const isApp = document.documentElement.classList.contains("native");
if (isApp) {
  addEventListener("focusin", e => { if (/INPUT|SELECT|TEXTAREA/.test(e.target.tagName)) document.documentElement.classList.add("kb"); });
  addEventListener("focusout", () => document.documentElement.classList.remove("kb"));
  document.addEventListener("DOMContentLoaded", () => { syncBars(); const a = NA(); if (a) { $("#appInfo").innerHTML = `<dt>Server</dt><dd>${esc(a.server ? a.server() : location.host)}</dd><dt>Aplikasi</dt><dd>${esc(a.version ? a.version() : "")}</dd>`; $("#appChange").onclick = () => a.changeServer(); } });
  $$("#nav a").forEach(a => a.addEventListener("click", () => { try { NA()?.tick?.(); } catch (e) { /* abaikan */ } }));
}
const TITLES = { live: "Pemantauan", history: "Riwayat", source: "Sumber & lokasi", detect: "Deteksi", system: "Sistem" };
function route() {
  const v = (location.hash || "#live").slice(1);
  view = TITLES[v] ? v : "live";
  $$(".view").forEach(s => s.hidden = s.id !== "v-" + view);
  $$("#nav a").forEach(a => a.classList.toggle("on", a.dataset.view === view));
  $("#pageTitle").textContent = TITLES[view];
  document.title = TITLES[view] + " · EmisiSense Vision";
  if (view === "history") { loadHistory(); loadWind(); loadRecs(); $("#recOverlay").checked = CFG?.record_overlay !== false; }
  if (view === "live") loadWind();
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
const C16 = ["U", "UTL", "TL", "TTL", "T", "TTG", "TG", "STG", "S", "SBD", "BD", "BBD", "B", "BBL", "BL", "UBL"];
const C16N = ["Utara", "Utara-timur laut", "Timur laut", "Timur-timur laut", "Timur", "Timur-tenggara", "Tenggara", "Selatan-tenggara", "Selatan", "Selatan-barat daya", "Barat daya", "Barat-barat daya", "Barat", "Barat-barat laut", "Barat laut", "Utara-barat laut"];
const sec16 = d => Math.floor((((d % 360) + 360) % 360 + 11.25) / 22.5) % 16;
const compass = d => d == null ? "" : C16[sec16(d)];
const compassName = d => d == null ? "" : C16N[sec16(d)];
const polar = (cx, cy, r, deg) => [cx + r * Math.sin(deg * Math.PI / 180), cy - r * Math.cos(deg * Math.PI / 180)];
const wedge = (cx, cy, r0, r1, a0, a1) => { const p = (r, a) => polar(cx, cy, r, a).map(v => v.toFixed(1)).join(" "); return `M${p(r1, a0)} A${r1} ${r1} 0 0 1 ${p(r1, a1)} L${p(r0, a1)} ${r0 > 0 ? `A${r0} ${r0} 0 0 0 ${p(r0, a0)}` : ""} Z`; };

/* kompas kecil untuk kartu cuaca: panah menunjuk ke mana angin bertiup (kebalikan dari arah asal) */
function windCompass(deg) {
  const c = 39, to = ((deg || 0) + 180) % 360, tip = polar(c, c, 27, to), tail = polar(c, c, 14, deg || 0);
  const l = polar(c, c, 8, to + 90), r = polar(c, c, 8, to - 90), back = polar(c, c, 22, to);
  return `<svg viewBox="0 0 78 78" role="img" aria-label="Arah angin"><circle cx="${c}" cy="${c}" r="35" fill="none" stroke="${css("--line")}" stroke-width="1.5"/>${[0, 90, 180, 270].map(a => { const p1 = polar(c, c, 35, a), p2 = polar(c, c, 30, a); return `<line x1="${p1[0]}" y1="${p1[1]}" x2="${p2[0]}" y2="${p2[1]}" stroke="${css("--mute")}" stroke-width="1.5"/>`; }).join("")}
  <text x="${c}" y="9" text-anchor="middle" style="font:700 8px sans-serif;fill:${css("--ink")}">U</text><text x="${c}" y="75" text-anchor="middle" style="font:700 8px sans-serif;fill:${css("--mute")}">S</text><text x="72" y="${c + 3}" text-anchor="middle" style="font:700 8px sans-serif;fill:${css("--mute")}">T</text><text x="6" y="${c + 3}" text-anchor="middle" style="font:700 8px sans-serif;fill:${css("--mute")}">B</text>
  <polygon points="${tip[0]},${tip[1]} ${l[0]},${l[1]} ${back[0]},${back[1]} ${r[0]},${r[1]}" fill="${css("--accent")}"/><circle cx="${c}" cy="${c}" r="2.5" fill="${css("--accent-ink")}"/></svg>`;
}

/* mawar angin: 16 arah, batang bertumpuk menurut kelas kecepatan; panjang = persen waktu angin datang dari arah itu */
const WR_OP = [.28, .45, .62, .8, 1];
function windRose(el, w) {
  if (!w || !w.n) { el.innerHTML = '<div class="empty">Belum ada data angin untuk rentang ini. Data muncul setelah cuaca Open-Meteo terambil.</div>'; return; }
  const S = 300, cx = 150, cy = 150, R = 100, mx = Math.max(...w.sectors.map(s => s.pct), 1), top = Math.max(2, Math.ceil(mx * 1.15 / 4) * 4), ring = top / 4;
  const rr = v => v / top * R; let g = "";
  for (let i = 1; i <= 4; i++) g += `<circle cx="${cx}" cy="${cy}" r="${rr(ring * i)}" fill="none" stroke="${css("--line2")}" stroke-width="1"/><text x="${cx + 3}" y="${cy - rr(ring * i) - 2}" style="font-size:9px">${fmt(ring * i, ring < 1 ? 1 : 0)}%</text>`;
  for (let i = 0; i < 16; i++) { const p = polar(cx, cy, R, i * 22.5); g += `<line x1="${cx}" y1="${cy}" x2="${p[0]}" y2="${p[1]}" stroke="${css("--line2")}" stroke-width="1"/>`; }
  const cols = [];
  w.sectors.forEach(s => {
    let acc = 0; const a0 = s.deg - 9.6, a1 = s.deg + 9.6;
    s.bins.forEach((b, k) => { if (!b) return; g += `<path d="${wedge(cx, cy, rr(acc), rr(acc + b), a0, a1)}" fill="${css("--accent")}" fill-opacity="${WR_OP[k]}" stroke="${css("--panel")}" stroke-width=".6"/>`; acc += b; });
  });
  w.sectors.forEach(s => { const main = s.i % 4 === 0, p = polar(cx, cy, R + (main ? 13 : 11), s.deg); g += `<text x="${p[0]}" y="${p[1] + 3.5}" text-anchor="middle" class="${main ? "wr-card" : ""}" style="${main ? "" : "font-size:9px"}">${s.abbr}</text>`; });
  g += `<circle cx="${cx}" cy="${cy}" r="17" fill="${css("--panel")}" stroke="${css("--line")}"/><text x="${cx}" y="${cy - 1}" text-anchor="middle" style="font-size:8.5px">tenang</text><text x="${cx}" y="${cy + 9}" text-anchor="middle" class="wr-card" style="font-size:10px">${fmt(w.calm_pct, 0)}%</text>`;
  el.innerHTML = `<svg viewBox="0 0 ${S} ${S}" role="img" aria-label="Mawar angin 16 arah">${g}</svg><div class="legend">${w.bins.map((b, k) => `<span><i class="sq" style="background:${css("--accent")};opacity:${WR_OP[k]}"></i>${b}</span>`).join("")}<span class="muted">km/jam</span></div>`;
  const svg = el.querySelector("svg"); el._cols = null;
  if (!svg._bound) { svg._bound = true;
    svg.addEventListener("pointermove", e => { const r = svg.getBoundingClientRect(), x = (e.clientX - r.left) / r.width * S - cx, y = (e.clientY - r.top) / r.height * S - cy, d = Math.hypot(x, y); if (d < 17 || d > R + 6) return tipHide();
      const ang = (Math.atan2(x, -y) * 180 / Math.PI + 360) % 360, s = el._w.sectors[sec16(ang)];
      tipShow(`<b>Dari ${esc(s.name)} (${s.abbr})</b><br>${fmt(s.pct, 1)}% dari waktu<br>${s.bins.map((b, k) => b ? `${el._w.bins[k]} km/j: ${fmt(b, 1)}%` : "").filter(Boolean).join("<br>")}`, e); });
    svg.addEventListener("pointerleave", tipHide); }
  el._w = w;
}
function windTable(w) {
  const top = [...(w.sectors || [])].sort((a, b) => b.pct - a.pct).filter(s => s.pct > 0).slice(0, 8);
  return w.n ? `<p>${windNote(w)}</p><table><thead><tr><th>Dari arah</th><th class="num">Persen waktu</th><th class="num">Kecepatan (perkiraan)</th></tr></thead><tbody>${top.map(s => `<tr><td>${esc(s.name)} (${s.abbr})</td><td class="num">${fmt(s.pct, 1)}%</td><td class="num">${fmt(((s.bins.reduce((a, b, k) => a + b * [3, 7.5, 15, 25, 35][k], 0)) / (s.pct || 1)), 1)} km/j</td></tr>`).join("")}</tbody></table>` : "";
}
function windNote(w) { return !w || !w.n ? "" : `${w.prevailing ? `Angin paling sering datang dari <b>${esc(w.prevailing.name)}</b> (${fmt(w.prevailing.pct, 0)}% waktu). ` : ""}Kecepatan rata-rata ${fmt(w.mean_speed, 1)} km/jam, tertinggi ${fmt(w.max_speed, 0)}; tenang ${fmt(w.calm_pct, 0)}%. ${w.n} jam pengamatan.`; }
let windH = 24;
async function loadWind() {
  try {
    if (view === "live") { const w = await api(`/api/windrose?hours=${windH}`); windRose($("#windRose"), w); $("#windNote").innerHTML = windTable(w); }
    if (view === "history") {
      const w = await api(`/api/windrose?hours=${histH}`); windRose($("#histRose"), w);
      $("#histWindRange").textContent = `${histH >= 48 ? Math.round(histH / 24) + " hari" : histH + " jam"} terakhir · ${w.n || 0} jam data`;
      const top = [...(w.sectors || [])].sort((a, b) => b.pct - a.pct).filter(s => s.pct > 0).slice(0, 8);
      $("#histWindTbl").innerHTML = windTable(w);
    }
  } catch (e) { /* ulangi pada siklus berikutnya */ }
}
setInterval(loadWind, 60000);
document.addEventListener("click", e => { const b = e.target.closest("#segWind button"); if (!b) return; windH = +b.dataset.h; $$("#segWind button").forEach(x => x.classList.toggle("on", x === b)); loadWind(); });

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
  $("#tPeople").classList.toggle("on", !!s.people.enabled);
  $("#readout").innerHTML = `<div class="big"><div><div class="n">${fmt(s.total)}</div></div><div class="l">kendaraan terhitung<small>sejak ${s.since.slice(11, 16)} · ${fmt(s.this_minute)} menit ini</small></div></div>
  <div class="rd"><span>Laju per jam</span><b>${fmt(s.rate_per_hour)}</b><small>proyeksi dari rata-rata sesi</small></div>
  <div class="rd"><span>Volume SMP</span><b>${fmt(s.pcu_total, 1)}</b><small>satuan mobil penumpang</small></div>
  <div class="rd"><span>Kecepatan rata-rata</span><b>${s.speed.avg == null ? "–" : fmt(s.speed.avg, 0) + " km/j"}</b><small>estimasi · saat ini ${s.speed.now_avg == null ? "–" : fmt(s.speed.now_avg, 0) + " km/j"}</small></div>
  <div class="rd"><span>Di zona sekarang</span><b>${fmt(s.zone.count)}</b><small>puncak ${fmt(s.zone.peak)} kendaraan</small></div>
  <div class="rd"><span>Kepadatan</span><b style="color:var(${lvc})">${s.zone.level}</b><small><span class="lvl" style="--c:var(${lvc});margin:0">${[0, 1, 2, 3, 4].map(i => `<i class="${i <= lv ? "on" : ""}"></i>`).join("")}</span> ${fmt(s.zone.pcu, 1)} SMP di zona (indikatif)</small></div>
  <div class="rd"><span>Pejalan kaki</span><b>${s.people.enabled ? fmt(s.people.total) : "nonaktif"}</b><small>${s.people.enabled ? `${fmt(s.people.zone)} di zona sekarang · ${fmt(s.people.this_minute)} menit ini` : "deteksi pejalan kaki dimatikan"}</small></div>
  <div class="chips">${KEYS.filter(k => s.zone.by[k]).map(k => `<span><i class="dot" style="background:${colorOf(k)}"></i>${LABEL[k]} ${s.zone.by[k]}</span>`).join("") || '<span class="muted">Zona kosong</span>'}</div>`;
}

function renderWeather(w) {
  const el = $("#weather");
  if (!w || !w.current) { el.innerHTML = `<div class="panel-head"><h2>Cuaca &amp; udara</h2></div><div class="empty">${w && w.error ? "Cuaca belum tersedia: " + esc(w.error) : "Memuat data cuaca…"}</div>`; return; }
  const c = w.current, u = w.units || {}, aq = w.air_quality || {};
  let h = `<div class="panel-head"><h2>Cuaca &amp; udara</h2><span class="muted small">${esc(w.location?.name || "")} · ${w.source === "demo" ? "data contoh" : "Open-Meteo"} · ${(w.updated || "").slice(11, 16)}</span></div>
  <div class="wx-top"><div class="wx-ico">${wxIcon(c.desc.icon)}</div><div><div class="wx-t">${fmt(c.temperature_2m, 1)}<sup>${esc(u.temperature_2m || "°C")}</sup></div><div class="wx-d">${esc(c.desc.text)} · terasa ${fmt(c.apparent_temperature, 1)}°</div></div></div>
  <div class="wx-kv"><div>Kelembapan<b>${fmt(c.relative_humidity_2m)}%</b></div><div>Hujan<b>${fmt(c.precipitation, 1)} mm</b></div><div>Tekanan<b>${fmt(c.pressure_msl)} hPa</b></div><div>Awan<b>${fmt(c.cloud_cover)}%</b></div></div>
  <div class="wx-wind">${windCompass(c.wind_direction_10m)}<div><b>Angin dari ${esc(compassName(c.wind_direction_10m))} (${esc(compass(c.wind_direction_10m))}, ${fmt(c.wind_direction_10m)}°)</b><div>${fmt(c.wind_speed_10m, 1)} km/jam · hembusan ${fmt(c.wind_gusts_10m)} km/jam</div><div class="muted">bertiup ke ${esc(compassName((c.wind_direction_10m + 180) % 360))}</div></div></div>
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
  <ul>${KEYS.map(k => `<li><i class="dot" style="background:${colorOf(k)}"></i>${LABEL[k]}<b>${fmt(s.totals[k])}</b><em>${tot ? Math.round(s.totals[k] / tot * 100) + "%" : ""}</em></li>`).join("")}<li class="sep"><i class="dot" style="background:${colorOf("person")}"></i>Pejalan kaki<b>${s.people.enabled ? fmt(s.people.total) : "–"}</b><em>terpisah</em></li></ul>`;
  const sp = s.speed, W = 360, H = 140, m = { l: 26, r: 6, t: 8, b: 22 }, n = sp.bins.length, bw = (W - m.l - m.r) / n, mx = Math.max(1, ...sp.hist);
  let g = ""; const cols = [];
  sp.hist.forEach((v, i) => { const h = v / mx * (H - m.t - m.b), over = sp.bins[i] >= sp.limit; g += `<rect x="${m.l + i * bw + 2}" y="${H - m.b - h}" width="${bw - 4}" height="${h}" rx="1.5" fill="${over ? css("--bad") : css("--accent")}"/><text x="${m.l + i * bw + bw / 2}" y="${H - 6}" text-anchor="middle">${sp.bins[i]}</text>`; cols.push({ x0: m.l + i * bw, x1: m.l + (i + 1) * bw, tip: `<b>${sp.bins[i]}${i === n - 1 ? "+" : "–" + sp.bins[i + 1]} km/jam</b><br>${v} kendaraan` }); });
  const lx = m.l + sp.limit / 10 * bw; g += `<line x1="${lx}" x2="${lx}" y1="${m.t}" y2="${H - m.b}" stroke="${css("--paint")}" stroke-width="2" stroke-dasharray="4 3"/><text x="${lx + 4}" y="${m.t + 8}">batas ${sp.limit}</text>`;
  $("#chSpeed").innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Sebaran kecepatan">${g}</svg>`; $("#chSpeed")._cols = cols; bindTip($("#chSpeed"), W);
  $("#speedStats").innerHTML = [["Rata-rata", sp.avg], ["P85", sp.p85], ["Maks", sp.max], ["Melebihi batas", sp.overspeed]].map(([a, b]) => `<div>${a}<b>${b == null ? "–" : fmt(b, 0)}</b></div>`).join("");
}

function renderZoneLines(s) {
  const mx = Math.max(1, ...s.lines.map(l => l.count));
  $("#linesBox").innerHTML = s.lines.map(l => {
    const col = l.free ? "var(--mute)" : (l.color || "var(--accent)");
    const chips = ALLK.filter(k => l.by[k]).map(k => `<span><i class="dot" style="background:${colorOf(k)}"></i>${LABEL[k]} ${l.by[k]}</span>`).join("");
    return `<div class="ln"><h3><i class="swatch" style="background:${col}"></i>${esc(l.name)}<small>${l.free ? "bergerak tanpa melewati garis" : "→ " + esc(l.dir)}</small></h3>
    <div class="dir"><span>${l.free ? "Lainnya" : "Dihitung"}</span><div class="bar"><i style="width:${l.count / mx * 100}%;background:${col}"></i></div><b>${l.count}</b></div>${chips ? `<div class="chips">${chips}</div>` : ""}</div>`; }).join("") || '<div class="empty">Belum ada garis. Tekan “Atur garis”.</div>';
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
/* panah blok di sepanjang garis: menunjuk ke arah yang dihitung (kanan orang yang berjalan dari p1 ke p2); sama dengan gambar di video */
function arrowGlyphs(c, a, b, col, d) {
  const dx = b[0] - a[0], dy = b[1] - a[1], L = Math.hypot(dx, dy); if (L < 14 * d) return;
  const ux = dx / L, uy = dy / L, vx = -uy, vy = ux, sc = Math.max(.8, ov.width / d / 800) * d, len = 34 * sc, sw = 5.5 * sc, hw = 13 * sc, hl = 15 * sc, sh = len - hl;
  [.18, .5, .82].forEach(f => {
    const ox = a[0] + dx * f + vx * 7 * sc, oy = a[1] + dy * f + vy * 7 * sc;
    const pts = [[0, -sw], [sh, -sw], [sh, -hw], [len, 0], [sh, hw], [sh, sw], [0, sw]].map(([x, y]) => [ox + vx * x + ux * y, oy + vy * x + uy * y]);
    c.beginPath(); pts.forEach((p, i) => i ? c.lineTo(...p) : c.moveTo(...p)); c.closePath(); c.fillStyle = col; c.fill(); c.lineWidth = 1.6 * d; c.strokeStyle = "#000"; c.stroke();
  });
}
function drawOverlay() {
  const c = ov.getContext("2d"), W = ov.width, H = ov.height, d = devicePixelRatio || 1; c.clearRect(0, 0, W, H);
  if (!mode || !CFG) return;
  const P = p => [p[0] * W, p[1] * H];
  const handle = (p, col, sel) => { const [x, y] = P(p); c.beginPath(); c.arc(x, y, (sel ? 10 : 8) * d, 0, 7); c.fillStyle = col; c.fill(); c.lineWidth = 2.5 * d; c.strokeStyle = "#fff"; c.stroke(); };
  if (mode === "lines") CFG.lines.forEach((l, i) => {
    const a = P(l.p1), b = P(l.p2), col = l.color || LINE_COLORS[i % LINE_COLORS.length], sel = i === selLine;
    c.lineCap = "round"; c.strokeStyle = "#000"; c.lineWidth = (sel ? 8 : 6.5) * d; c.beginPath(); c.moveTo(...a); c.lineTo(...b); c.stroke();
    c.strokeStyle = col; c.lineWidth = (sel ? 4.5 : 3.5) * d; c.beginPath(); c.moveTo(...a); c.lineTo(...b); c.stroke();
    arrowGlyphs(c, a, b, col, d); handle(l.p1, col, sel); handle(l.p2, col, sel);
    const txt = `${l.name}: ${l.dir}`; c.font = `600 ${12.5 * d}px sans-serif`; const tw = c.measureText(txt).width;
    c.fillStyle = col; c.fillRect(a[0] + 8 * d, a[1] - 24 * d, tw + 12 * d, 19 * d); c.fillStyle = "#1a1a1a"; c.textAlign = "left"; c.fillText(txt, a[0] + 14 * d, a[1] - 10 * d);
  });
  if (mode === "roi") { c.beginPath(); CFG.roi.forEach((p, i) => { const [x, y] = P(p); i ? c.lineTo(x, y) : c.moveTo(x, y); }); c.closePath(); c.fillStyle = "rgba(34,211,238,.14)"; c.fill(); c.strokeStyle = "#000"; c.lineWidth = 5.5 * d; c.stroke(); c.strokeStyle = ZONE; c.lineWidth = 3 * d; c.stroke(); CFG.roi.forEach(p => handle(p, ZONE)); }
  if (mode === "cal") { if (calPts.length === 2) { c.beginPath(); c.moveTo(...P(calPts[0])); c.lineTo(...P(calPts[1])); c.strokeStyle = "#34d399"; c.lineWidth = 3 * d; c.stroke(); } calPts.forEach(p => handle(p, "#34d399")); }
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
  if (mode === "cal") { if (calPts.length >= 2) calPts = []; calPts.push(p); drawOverlay(); renderEditor(); if (calPts.length === 2) calModal(); return; }
  const h = nearest(p); if (h) { drag = h; if (mode === "lines" && selLine !== h.i) { selLine = h.i; renderEditor(); } ov.setPointerCapture(e.pointerId); }
});
ov.addEventListener("pointermove", e => { if (!drag) return; const p = pos(e); if (mode === "lines") CFG.lines[drag.i][drag.k] = p; else CFG.roi[drag.i] = p; drawOverlay(); });
ov.addEventListener("pointerup", () => { if (!drag) return; drag = null; save(mode === "lines" ? { lines: CFG.lines } : { roi: CFG.roi }); });

/* ============================== popup ==============================
   Popup hanya bisa ditutup dengan tombol X: klik di luar kotak atau tombol Esc tidak menutupnya, supaya isian tidak hilang. */
function openModal({ title, body, el, okText = "Simpan", danger = false, onOk, onClose, wide = false }) {
  const back = document.createElement("div"); back.className = "modal-back";
  back.innerHTML = `<div class="modal${wide ? " wide" : ""}" role="dialog" aria-modal="true" aria-label="${esc(title)}"><div class="modal-head"><h2>${esc(title)}</h2><button class="modal-x" type="button" aria-label="Tutup (X)" title="Tutup">✕</button></div><div class="modal-body"></div>${onOk ? `<div class="modal-foot"><span class="modal-err" role="alert"></span><button class="btn ${danger ? "danger" : "primary"}" type="button">${esc(okText)}</button></div>` : ""}</div>`;
  const host = back.querySelector(".modal-body"); let ph = null;
  if (el) { ph = document.createComment("popup"); el.before(ph); el.hidden = false; host.append(el); } else host.innerHTML = body;
  const close = () => { if (el) { el.hidden = true; ph.replaceWith(el); } back.remove(); onClose && onClose(); };
  back.querySelector(".modal-x").onclick = close;
  const okBtn = back.querySelector(".modal-foot .btn");
  back.addEventListener("keydown", e => { if (e.key === "Escape") e.preventDefault(); if (e.key === "Enter" && okBtn && e.target.tagName === "INPUT" && e.target.type !== "file") { e.preventDefault(); okBtn.click(); } });
  const err = t => back.querySelector(".modal-err").textContent = t || "";
  if (okBtn) okBtn.onclick = async () => { err(""); const r = await onOk(host, err); if (r !== false) close(); };
  document.body.append(back);
  (host.querySelector("input,select,button") || back.querySelector(".modal-x")).focus();
  return { close, root: host };
}

function lineModal(l) {
  const isNew = !l, used = CFG.lines.map(x => x.id);
  let k = 0; while (used.includes(String.fromCharCode(65 + k))) k++;
  const id = String.fromCharCode(65 + k);
  openModal({ title: isNew ? "Tambah garis" : "Ubah nama & arah", okText: isNew ? "Tambah garis" : "Simpan",
    body: `<label class="fld">Nama garis<input type="text" id="mName" value="${esc(isNew ? "Garis " + id : l.name)}" maxlength="40" placeholder="mis. Garis A"></label>
    <label class="fld">Nama arah yang dihitung<input type="text" id="mDir" value="${esc(isNew ? "" : l.dir)}" maxlength="40" placeholder="mis. Mendekat, Ke selatan"><small>Kendaraan yang lewat searah panah dicatat dengan nama ini. Arah panah bisa dibalik setelah garis dibuat.</small></label>`,
    onOk: async (root, err) => {
      const name = root.querySelector("#mName").value.trim(), dir = root.querySelector("#mDir").value.trim();
      if (!name) { err("Isi nama garis."); return false; } if (!dir) { err("Isi nama arah."); return false; }
      if (isNew) {
        const usedC = CFG.lines.map(x => x.color), color = LINE_COLORS.find(x => !usedC.includes(x)) || LINE_COLORS[CFG.lines.length % LINE_COLORS.length], y = Math.min(.9, .45 + .08 * CFG.lines.length);
        CFG.lines.push({ id, name, p1: [.1, y], p2: [.9, y], dir, color }); selLine = CFG.lines.length - 1;
      } else { l.name = name; l.dir = dir; }
      await save({ lines: CFG.lines }); refreshLegend(); renderEditor(); drawOverlay(); toast(isNew ? "Garis ditambahkan" : "Disimpan"); } });
}
function calModal() {
  openModal({ title: "Panjang nyata", okText: "Terapkan kalibrasi",
    body: `<label class="fld">Panjang nyata antara kedua titik (meter)<input type="number" id="mMeter" min="0.1" step="0.1" placeholder="mis. 4"><small>Ukur dengan meteran pada jalan: marka putus-putus, lebar lajur, atau panjang zebra cross.</small></label>`,
    onOk: async (root, err) => {
      const m = parseFloat(root.querySelector("#mMeter").value); if (!(m > 0)) { err("Isi panjang dalam meter."); return false; }
      const fr = S?.status.frame || [800, 450], px = Math.hypot((calPts[0][0] - calPts[1][0]) * fr[0], (calPts[0][1] - calPts[1][1]) * fr[1]);
      const r = await api("/api/calibrate", { ref_px: px, ref_m: m }); if (r.error) { err(r.error); return false; }
      await loadCfg(); toast("Kalibrasi diterapkan"); setMode(null); } });
}

function setMode(m) {
  mode = mode === m ? null : m; calPts = [];
  stage.classList.toggle("editing", !!mode);
  try { NA()?.lockRefresh?.(!!mode); } catch (e) { /* abaikan */ }
  [["lines", "#tLines"], ["roi", "#tRoi"], ["cal", "#tCal"]].forEach(([k, s]) => $(s).classList.toggle("on", mode === k));
  renderEditor(); drawOverlay();
}
function renderEditor() {
  if (!mode) { editor.hidden = true; return; } editor.hidden = false;
  if (mode === "lines") {
    const n = CFG.lines.length; selLine = Math.max(0, Math.min(selLine, n - 1)); const l = CFG.lines[selLine];
    editor.innerHTML = `<p><b>Atur garis hitung.</b> Satu garis menghitung <b>satu arah saja</b>: kendaraan yang lewat searah panah. Seret titik di ujung garis untuk memindahkan; tekan titik untuk memilih garis. Jalan dua arah: buat dua garis dengan panah berlawanan. ${n ? "" : "<b>Belum ada garis, jadi tidak ada kendaraan yang dihitung.</b>"}</p>
    <div class="tools">${n ? `<span class="swatch" style="background:${l.color}" title="Warna garis ini"></span><select id="eSel" aria-label="Garis dipilih">${CFG.lines.map((x, i) => `<option value="${i}" ${i === selLine ? "selected" : ""}>${esc(x.name)} → ${esc(x.dir)}</option>`).join("")}</select>
    <button class="btn sm" id="eEdit">Ubah nama &amp; arah</button><button class="btn sm" id="eFlip">Balik arah panah</button>` : ""}<button class="btn sm primary" id="eAdd">Tambah garis</button>${n ? `<button class="btn sm danger" id="eDel">Hapus garis ini</button>` : ""}<button class="btn sm" id="eDone">Selesai</button></div>`;
    if (n) {
      $("#eSel").onchange = e => { selLine = +e.target.value; renderEditor(); drawOverlay(); };
      $("#eFlip").onclick = () => { [l.p1, l.p2] = [l.p2, l.p1]; save({ lines: CFG.lines }); drawOverlay(); toast("Arah panah dibalik"); };
      $("#eEdit").onclick = () => lineModal(l);
      $("#eDel").onclick = () => openModal({ title: "Hapus garis", okText: "Hapus garis", danger: true,
        body: `<p>Hapus <b>${esc(l.name)}</b> (→ ${esc(l.dir)})? Hitungan baru pada garis ini berhenti. Data yang sudah tersimpan tidak dihapus.${n === 1 ? " Ini garis terakhir: setelah dihapus <b>tidak ada kendaraan yang dihitung</b> sampai Anda menambah garis lagi." : ""}</p>`,
        onOk: async () => { CFG.lines.splice(selLine, 1); selLine = 0; await save({ lines: CFG.lines }); refreshLegend(); renderEditor(); drawOverlay(); toast("Garis dihapus"); } });
    }
    $("#eAdd").onclick = () => lineModal(null);
    $("#eDone").onclick = () => setMode(null);
  }
  if (mode === "roi") {
    editor.innerHTML = `<p><b>Atur zona pengamatan.</b> Seret titik cyan untuk membentuk zona. Kepadatan dihitung di dalam zona ini, dan deteksi difokuskan ke sini. Buat zona menutupi badan jalan saja agar bayangan dan trotoar tidak ikut.</p><div class="tools"><span class="swatch" style="background:#22d3ee" title="Warna zona"></span><button class="btn sm" id="eRst">Kembalikan bawaan</button><button class="btn sm primary" id="eDone">Selesai</button></div>`;
    $("#eRst").onclick = () => { CFG.roi = [[.05, .3], [.95, .3], [.95, .95], [.05, .95]]; save({ roi: CFG.roi }); drawOverlay(); };
    $("#eDone").onclick = () => setMode(null);
  }
  if (mode === "cal") {
    const ready = calPts.length === 2, cal = CFG.calibration?.m_per_px;
    editor.innerHTML = `<p><b>Kalibrasi kecepatan.</b> ${ready ? "Kedua titik sudah dipasang. Isi panjang nyata di antara keduanya." : `Klik dua titik pada sesuatu yang panjang aslinya diketahui di jalan (marka putus-putus, lebar lajur, panjang zebra cross). Titik ke-${calPts.length + 1}…`}</p>
    <div class="tools">${ready ? `<button class="btn sm primary" id="eOk">Isi panjang nyata</button>` : ""}<button class="btn sm" id="eClr">Hapus kalibrasi</button><button class="btn sm" id="eDone">Tutup</button>${cal ? `<span class="muted small">aktif: ${fmt(cal * 100, 2)} cm per piksel</span>` : ""}</div>`;
    $("#eDone").onclick = () => setMode(null);
    $("#eClr").onclick = async () => { await api("/api/calibrate/clear", {}); await loadCfg(); toast("Kalibrasi dihapus"); renderEditor(); };
    if (ready) $("#eOk").onclick = calModal;
  }
}
async function save(patch) { const r = await api("/api/config", patch); if (!r.error) CFG = r; return r; }
async function loadCfg() { CFG = await api("/api/config"); }

$("#tPeople").onclick = async () => { const on = CFG.count_people === false; await save({ count_people: on }); $("#tPeople").classList.toggle("on", on); refreshLegend(); toast(on ? "Hitung pejalan kaki: aktif" : "Hitung pejalan kaki: nonaktif"); };
$("#tLines").onclick = () => setMode("lines"); $("#tRoi").onclick = () => setMode("roi"); $("#tCal").onclick = () => setMode("cal");
$("#tFull").onclick = () => { if (document.fullscreenElement) document.exitFullscreen(); else stage.requestFullscreen?.(); };
$("#tPause").onclick = async () => { const r = await api("/api/pause", { paused: !(S?.status.paused) }); toast(r.paused ? "Pemrosesan dijeda" : "Pemrosesan dilanjutkan"); };
$("#btnReset").onclick = () => openModal({ title: "Kosongkan tampilan", okText: "Kosongkan", danger: true, body: "<p>Kosongkan hitungan di layar? Data yang sudah tersimpan tidak dihapus.</p>", onOk: async () => { await api("/api/reset", {}); toast("Tampilan hitungan dikosongkan"); } });
$("#segMetric").onclick = e => { const b = e.target.closest("button"); if (!b) return; metric = b.dataset.m; $$("#segMetric button").forEach(x => x.classList.toggle("on", x === b)); if (S) renderCharts(S.stats); };
addEventListener("keydown", e => { if (e.key === "Escape" && mode && !document.querySelector(".modal-back")) setMode(mode); });
document.addEventListener("fullscreenchange", () => setTimeout(fitOverlay, 50));

function refreshLegend() {
  $("#legend").innerHTML = (CFG.count_people === false ? KEYS : ALLK).map(k => `<span><i style="background:${colorOf(k)}"></i>${LABEL[k]}</span>`).join("") +
    `<span class="lg-sep"></span><span><i class="sq" style="background:${ZONE}"></i>Zona</span>` + CFG.lines.map(l => `<span><i class="sq" style="background:${l.color}"></i>${esc(l.name)} → ${esc(l.dir)}</span>`).join("");
}
function buildLegend() {
  refreshLegend();
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
    const lab = (x, short) => { const t = x.t ?? x, p = wibParts(t); const dm = `${p.day}/${p.month}`; return day ? dm : long ? (short ? `${dm} ${p.hour}:00` : `${dm} ${hhmm(t)}`) : hhmm(t); };
    const every = Math.max(1, Math.round(d.length / 8));
    stackedBars($("#chHist"), d, { metric: "count", every, label: lab, aria: "Volume kendaraan", extra: x => (x.speed != null ? `<br>kecepatan rata-rata ${fmt(x.speed, 0)} km/j` : "") + (x.temp != null ? `<br>suhu ${fmt(x.temp, 1)}°C` : "") + (x.pm2_5 != null ? `<br>PM2,5 ${fmt(x.pm2_5, 1)} µg/m³` : "") });
    const tot = d.reduce((a, x) => a + KEYS.reduce((b, k) => b + (x[k] || 0), 0), 0), bucket = r.bucket >= 3600 ? r.bucket / 3600 + " jam" : r.bucket / 60 + " menit";
    const ppl = d.reduce((a, x) => a + (x.person || 0), 0);
    $("#histNote").textContent = `${fmt(tot)} kendaraan${ppl ? ` dan ${fmt(ppl)} pejalan kaki` : ""} tercatat pada rentang ini. Satu batang = ${bucket}. Arahkan kursor untuk melihat rincian.`;
    dualLine($("#chHistLine"), d, { name: "Kecepatan rata-rata", color: css("--accent"), vals: d.map(x => x.speed), unit: "km/j" }, { name: "Suhu", color: css("--c-motorbike"), vals: d.map(x => x.temp), unit: "°C", d: 1, dash: "5 4" }, { label: lab });
    dualLine($("#chHistAir"), d, { name: "PM2,5", color: css("--c-truck"), vals: d.map(x => x.pm2_5), unit: "µg/m³", d: 1 }, { name: "Kendaraan", color: css("--c-bus"), vals: d.map(x => KEYS.reduce((b, k) => b + (x[k] || 0), 0)), unit: "kend." }, { label: lab });
  } catch (e) { /* coba lagi pada siklus berikutnya */ }
}
$("#segHist").onclick = e => { const b = e.target.closest("button"); if (!b) return; histH = +b.dataset.h; $$("#segHist button").forEach(x => x.classList.toggle("on", x === b)); loadHistory(); loadWind(); };
setInterval(loadHistory, 30000);
$$("[data-exp]").forEach(a => a.onclick = e => { e.preventDefault(); const q = new URLSearchParams(); if ($("#dFrom").value) q.set("from", $("#dFrom").value); if ($("#dTo").value) q.set("to", $("#dTo").value); location.href = `/api/export/${a.dataset.exp}.csv?${q}`; });

/* ============================== sumber & lokasi ============================== */
let srcDirty = false, locDirty = false;
function initSourceView() {
  if (!CFG) return;
  if (!srcDirty) $("#srcInput").value = CFG.source;
  $("#locSummary").innerHTML = `<dt>Nama</dt><dd>${esc(CFG.location.name)}</dd><dt>Koordinat</dt><dd>${fmt(CFG.location.lat, 4)}, ${fmt(CFG.location.lon, 4)}</dd>`;
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
  $("#optPeople").checked = c.count_people !== false; $("#optPeople").onchange = e => queueSave({ count_people: e.target.checked });
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
  const host = ((p.urls || []).map(u => { try { return new URL(u).hostname; } catch (e) { return ""; } }).find(h => h && h !== "localhost" && h !== "127.0.0.1")) || "IP-ORANGEPI";
  const dbp = sto?.path || "~/emisisense-vision/data/emisisense.db", dirp = dbp.includes("/") ? dbp.slice(0, dbp.lastIndexOf("/")) : ".";
  $$("pre[data-tpl]").forEach(el => { const t = el.dataset.tpl.replaceAll("{IP}", host).replaceAll("{DB}", dbp).replaceAll("{DIR}", dirp); if (el.textContent !== t) el.textContent = t; });
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

/* ============================== rekam video ============================== */
const mmss = s => { s = Math.max(0, s | 0); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60, p = n => String(n).padStart(2, "0"); return (h ? h + ":" : "") + p(m) + ":" + p(x); };
const bytesTxt = b => b >= 1073741824 ? fmt(b / 1073741824, 2) + " GB" : b >= 1048576 ? fmt(b / 1048576, 1) + " MB" : fmt(b / 1024, 0) + " KB";
let recOn = false, recMsg = "";
function renderRec(r) {
  if (!r) return; const on = !!r.recording;
  $("#tRec").classList.toggle("on", on); $("#tRecTxt").textContent = on ? "Berhenti " + mmss(r.seconds) : "Rekam";
  $("#recChip").hidden = !on; if (on) $("#recChip").textContent = "● REC " + mmss(r.seconds) + (r.bytes ? " · " + bytesTxt(r.bytes) : "");
  $("#recToggle2 span").textContent = on ? "Hentikan rekam " + mmss(r.seconds) : "Mulai rekam";
  $("#recToggle2").classList.toggle("danger", on);
  if (r.message && r.message !== recMsg) { recMsg = r.message; toast(r.message); }
  if (recOn && !on) loadRecs();
  recOn = on;
}
async function toggleRec() {
  const r = await api("/api/record", { on: !recOn });
  if (r.message) toast(r.message); else toast(r.recording ? "Mulai merekam" : "Rekaman disimpan");
  renderRec(r); if (!r.recording) loadRecs();
}
async function loadRecs() {
  if (view !== "history") return;
  let d; try { d = await api("/api/recordings"); } catch (e) { return; }
  const rows = d.items;
  $("#tblRec tbody").innerHTML = rows.map(x => `<tr><td>${esc(x.name)}${x.active ? ' <span class="tag">merekam</span>' : ""}</td><td>${new Date(x.mtime * 1000).toLocaleString("id-ID", { dateStyle: "medium", timeStyle: "short", timeZone: TZ })}</td><td class="num">${bytesTxt(x.bytes)}</td><td class="num">${x.active ? "" : `<button class="btn sm" data-rec="play" data-n="${esc(x.name)}">Putar</button><a class="btn sm" href="/api/recordings/${encodeURIComponent(x.name)}?dl=1">Unduh</a><button class="btn sm danger" data-rec="del" data-n="${esc(x.name)}">Hapus</button>`}</td></tr>`).join("") || '<tr><td colspan="4" class="muted">Belum ada rekaman. Tekan “Rekam” di halaman Pemantauan.</td></tr>';
  const st = d.status; $("#recNote").textContent = `Disimpan di folder data (recordings). Sisa ruang disk ${st.free_mb == null ? "–" : fmt(st.free_mb / 1024, 1) + " GB"}. Rekaman dipotong tiap 10 menit dan berhenti otomatis bila disk hampir penuh. Setiap rekaman memuat watermark dan cap waktu.`;
}
$("#tblRec").addEventListener("click", e => {
  const b = e.target.closest("button[data-rec]"); if (!b) return; const n = b.dataset.n;
  if (b.dataset.rec === "play") openModal({ title: n, wide: true, body: `<video controls autoplay playsinline src="/api/recordings/${encodeURIComponent(n)}"></video><p class="muted small vmsg"></p>`,
    onClose: () => 0 }).root.querySelector("video").onerror = ev => { const m = ev.target.closest(".modal-body").querySelector(".vmsg"); m.textContent = "Video ini tidak bisa diputar di browser (format MP4V tanpa ffmpeg). Gunakan tombol Unduh lalu putar dengan pemutar video."; };
  if (b.dataset.rec === "del") openModal({ title: "Hapus rekaman", okText: "Hapus rekaman", danger: true, body: `<p>Hapus <b>${esc(n)}</b>? Berkas ini tidak bisa dikembalikan.</p>`, onOk: async () => { await fetch("/api/recordings/" + encodeURIComponent(n), { method: "DELETE" }); toast("Rekaman dihapus"); loadRecs(); } });
});
$("#tRec").onclick = toggleRec; $("#recToggle2").onclick = toggleRec;
$("#recOverlay").onchange = e => save({ record_overlay: e.target.checked });

/* ============================== menu samping ============================== */
function setRail(min) {
  if (min) document.documentElement.dataset.rail = "min"; else delete document.documentElement.dataset.rail;
  const t = $("#railToggle"); t.setAttribute("aria-expanded", String(!min)); t.title = t.ariaLabel = min ? "Perluas menu" : "Kecilkan menu";
  try { localStorage.setItem("ev-rail", min ? "1" : "0"); } catch (e) { /* abaikan */ }
}
$("#railToggle").onclick = () => setRail(document.documentElement.dataset.rail !== "min");
$$("#nav a").forEach(a => a.title = a.querySelector("span").textContent);
setRail(document.documentElement.dataset.rail === "min");

function render() {
  if (!S) return; const p = S;
  renderStatus(p); renderRec(p.recording);
  if (view === "live") { renderCamMeta(p); renderNotice(p); renderReadout(p.stats); renderWeather(p.weather); renderCharts(p.stats); renderZoneLines(p.stats); renderTables(p.stats); drawOverlay(); }
  renderSourceStatus(p); renderSystem(p);
}
setInterval(() => $("#clock").textContent = new Date().toLocaleTimeString("id-ID", { timeZone: TZ }) + " WIB", 1000);

// Orange Pi tanpa internet (mode hotspot) tidak punya jam yang benar: kirim waktu perangkat ini (server hanya menerapkannya bila perlu).
const syncClock = () => fetch("/api/time", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ t: Date.now() / 1000 }) }).catch(() => {});
syncClock(); setInterval(syncClock, 600000);

// ---- Alamat video untuk program lain
{
  const o = location.origin;
  const rows = [["Aliran video (MJPEG)", `${o}/video/raw`], ["Satu gambar (JPEG)", `${o}/snapshot/raw.jpg`], ["Dengan garis & deteksi", `${o}/video`], ["Python / OpenCV", `cv2.VideoCapture("${o}/video/raw")`]];
  $("#vidInfo").innerHTML = rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd class="selectable" style="word-break:break-all">${esc(v)}</dd>`).join("");
}

// ---- Sinkronisasi cuaca (Open-Meteo) untuk data yang direkam saat offline
let syncState = null;
function syncRender() {
  const s = syncState, n = s?.pending?.minutes || 0, b = $("#syncBadge");
  b.hidden = !n; b.textContent = n > 99 ? "99+" : n;
  $("#syncBtn").title = n ? `${n} menit data belum punya cuaca. Tekan untuk mengambil dari Open-Meteo.` : "Ambil data cuaca Open-Meteo untuk data yang direkam saat offline";
  const l = s?.last, f = t => t ? t.replace("T", " ").slice(0, 16) : "–";
  const rows = [["Menit tanpa cuaca", n ? `${fmt(n)} menit (${f(isoOf(s.pending.first))} s.d. ${f(isoOf(s.pending.last))})` : "Tidak ada"],
    ["Cuaca saat ini", s?.online_weather ? "Tersambung ke Open-Meteo" : "Belum tersambung (offline)"],
    ["Sinkronisasi terakhir", l ? `${f(l.time)} · ${l.ok ? esc2(l.message) : "gagal"}` : "Belum pernah"]];
  $("#syncInfo").innerHTML = rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join("");
}
const esc2 = t => esc(t || "");
const isoOf = t => t ? new Date(t * 1000 - new Date().getTimezoneOffset() * 60000).toISOString() : null;
async function syncLoad() {
  try { syncState = await (await fetch("/api/sync", { cache: "no-store" })).json(); syncRender(); } catch (e) { /* server belum siap */ }
}
$("#syncBtn").onclick = async () => {
  const btn = $("#syncBtn"); btn.classList.add("busy"); toast("Menyinkronkan data cuaca…", 30000);
  let r;
  try { r = await (await fetch("/api/sync", { method: "POST" })).json(); } catch (e) { r = { ok: false, message: "Tidak dapat menghubungi server." }; }
  btn.classList.remove("busy"); await syncLoad();
  if (r.ok) toast(r.message, 5000);
  else { $("#toast").hidden = true; openModal({ title: "Sinkronisasi gagal", okText: "Tutup", body: `<p>${esc2(r.message)}</p>${r.detail ? `<p class="muted small selectable">${esc2(r.detail)}</p>` : ""}` }); }
  if (r.ok && r.warnings && r.warnings.length) setTimeout(() => toast(r.warnings.join(" · "), 6000), 5200);
};
syncLoad(); setInterval(() => { if (!document.hidden) syncLoad(); }, 20000);

// ---- Jaringan Orange Pi: hotspot atau Wi-Fi pilihan
let netPoll = null;
async function netLoad() {
  let r = null;
  try { r = await (await fetch("/api/net", { cache: "no-store" })).json(); } catch (e) { return null; }
  const panel = $("#netPanel");
  if (!r || !r.available) { netUnavailable(r); return null; }
  panel.hidden = false; $("#netUnavail").hidden = true; $("#netControls").hidden = false; $("#netScan").hidden = false;
  const port = location.port ? ":" + location.port : "";
  const modeTxt = { hotspot: "Hotspot Orange Pi", wifi: "Tersambung ke Wi-Fi", disconnected: "Belum tersambung", "no-wifi": "Adaptor Wi-Fi tidak ditemukan" }[r.state] || r.state;
  const rows = [["Mode", modeTxt], ["Nama jaringan", r.ssid || "–"], ["Alamat IP", r.ip || "–"], ["Alamat web", r.ip ? `http://${r.ip}${port}` : "–"]];
  if (r.state !== "hotspot") rows.push(["Hotspot cadangan", `${r.hotspot.ssid} (sandi ${r.hotspot.password}), http://${r.hotspot.ip}${port}`]);
  else rows.push(["Sandi hotspot", r.hotspot.password]);
  const l = r.last;
  if (l && l.state === "error") rows.push(["Percobaan terakhir", l.message || "Gagal"]);
  if (l && l.state === "connecting") rows.push(["Sedang berpindah", l.target === "hotspot" ? "ke hotspot…" : `ke ${l.ssid}…`]);
  $("#netState").innerHTML = rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd class="selectable">${esc(v)}</dd>`).join("");
  return r;
}
function netUnavailable(r) {
  $("#netPanel").hidden = false; $("#netControls").hidden = true; $("#netScan").hidden = true; $("#netState").innerHTML = ""; $("#netUnavail").hidden = false;
  const m = r && r.message ? esc(r.message) : "Tidak dapat memeriksa jaringan.";
  $("#netUnavail").innerHTML = `<p>${m}</p>` + (r && r.installed === false ? `<p class="muted small">Pasang sekali lewat SSH di Orange Pi (akan menyalakan hotspot sendiri saat boot):</p><pre class="cmd selectable">cd ~/emisisense-vision && ./update.sh && sudo ./hotspot/install-hotspot.sh</pre>` : "");
}
function netWatch() { // setelah pindah jaringan koneksi putus sebentar; pantau sampai server kembali
  clearInterval(netPoll); let n = 0;
  netPoll = setInterval(async () => { if (++n > 40) clearInterval(netPoll); const r = await netLoad(); if (r && r.last && r.last.state !== "connecting") { clearInterval(netPoll); } }, 3000);
}
function netSwitchedNotice(txt) {
  openModal({ title: "Orange Pi sedang berpindah jaringan", body: `<p>${txt}</p><p class="muted small">Sambungan ke halaman ini akan terputus beberapa detik. Bila Wi-Fi tidak berhasil tersambung (sandi salah/di luar jangkauan), hotspot Orange Pi menyala kembali otomatis dalam sekitar satu menit.</p>`, });
}
function netConnectDialog(ssid, secure) {
  openModal({ title: `Sambungkan ke “${ssid}”`, okText: "Sambungkan",
    body: `<div class="fld"><label>Nama Wi-Fi</label><input type="text" id="nSsid" value="${esc(ssid)}" ${ssid ? "readonly" : 'placeholder="Nama Wi-Fi (SSID)"'}></div>${secure ? '<div class="fld"><label>Kata sandi Wi-Fi</label><input type="password" id="nPass" autocomplete="off" placeholder="8–63 karakter (kosongkan bila Wi-Fi terbuka)"></div>' : ""}<p class="muted small">Setelah tersambung, alamat Orange Pi berubah mengikuti Wi-Fi tersebut. Sambungkan ponsel ke Wi-Fi yang sama lalu masukkan IP barunya di aplikasi.</p>`,
    onOk: async (host, err) => {
      const name = host.querySelector("#nSsid").value.trim(), pw = host.querySelector("#nPass")?.value || "";
      if (!name) { err("Isi nama Wi-Fi."); return false; }
      if (pw && (pw.length < 8 || pw.length > 63)) { err("Kata sandi 8–63 karakter."); return false; }
      const r = await fetch("/api/net/connect", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ssid: name, password: pw }) }).then(x => x.json()).catch(() => ({ ok: false, message: "Gagal menghubungi server" }));
      if (!r.ok) { err(r.message || "Gagal"); return false; }
      setTimeout(() => { netSwitchedNotice(`Orange Pi menyambung ke <b>${esc(name)}</b>.`); netWatch(); }, 50);
    } });
}
$("#netScan").onclick = async () => {
  const box = $("#netList"); box.innerHTML = '<div class="empty">Mencari Wi-Fi…</div>';
  const r = await fetch("/api/net/scan").then(x => x.json()).catch(() => ({ networks: [] }));
  const nets = r.networks || [];
  box.innerHTML = nets.length ? nets.map(n => `<button class="net-row" type="button" data-ssid="${esc(n.ssid)}" data-sec="${n.secure ? 1 : 0}"><span class="net-name">${esc(n.ssid)}${n.inuse ? ' <span class="tag">dipakai</span>' : ""}</span><span class="net-meta">${n.secure ? "🔒 " : ""}<span class="net-sig">${n.signal}%</span></span></button>`).join("")
    : '<div class="empty">Tidak ada Wi-Fi terdeteksi. Saat hotspot menyala, sebagian adaptor tidak bisa memindai; pakai “Wi-Fi lain (ketik nama)”.</div>';
};
$("#netList").addEventListener("click", e => { const b = e.target.closest(".net-row"); if (b) { NA()?.tick?.(); netConnectDialog(b.dataset.ssid, b.dataset.sec === "1"); } });
$("#netManual").onclick = () => netConnectDialog("", true);
$("#netHotspot").onclick = () => openModal({ title: "Gunakan hotspot Orange Pi", okText: "Nyalakan hotspot",
  body: "<p>Orange Pi memancarkan hotspot sendiri dan memutus Wi-Fi yang sedang dipakai. Sambungkan ponsel ke hotspot, lalu buka <b>10.42.0.1</b>.</p><p class=\"muted small\">Dalam mode hotspot Orange Pi tidak punya internet kecuali lewat kabel LAN, sehingga CCTV daring tidak terbaca; gunakan kamera USB/berkas video.</p>",
  onOk: async (host, err) => {
    const r = await fetch("/api/net/hotspot", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }).then(x => x.json()).catch(() => ({ ok: false, message: "Gagal menghubungi server" }));
    if (!r.ok) { err(r.message || "Gagal"); return false; }
    setTimeout(() => { netSwitchedNotice("Orange Pi menyalakan hotspot. Sambungkan ponsel ke hotspot Orange Pi lalu buka <b>http://10.42.0.1:5000</b>."); netWatch(); }, 50);
  } });
netLoad(); setInterval(() => { if (!document.hidden && !$("#v-system").hidden) netLoad(); }, 15000);

(async () => {
  await loadCfg(); buildLegend(); $("#srcLink").href = CFG.default_source || DEFAULT_SRC;
  route(); fitOverlay(); checkUpdate(false);
  const es = new EventSource("/api/stream");
  es.onmessage = e => { try { S = JSON.parse(e.data); S._recv = performance.now(); render(); } catch (err) { console.error(err); } };
  es.onerror = () => { const el = $("#status"); el.dataset.s = "error"; $("#statusTxt").textContent = "Server terputus"; $("#statusSub").textContent = ""; };
})();
$("#srcOpen").onclick = () => openModal({ title: "Ubah sumber video", el: $("#srcForm") });
$("#locOpen").onclick = () => openModal({ title: "Ubah lokasi cuaca", el: $("#locForm") });
})();
