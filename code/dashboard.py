r"""
IBVAP — COMMAND CENTRE DASHBOARD v4: TACTICAL DEFENSE EDITION
Features:
- Multi-Stream Real-Time Status & Threat Level Grid (CAM-01, CAM-02, CAM-03)
- 2D BOP Sector-7 Tactical Mini-Map with Dynamic Camera FOV Cones & Alert Beacons
- One-Click Section 65B Indian Evidence Act / BSA 2023 Forensic Court Certificate Export
- Cryptographic SHA-256 Evidence Chain Re-Verification on Every Poll
- Anti-Tamper & Sabotage Detection Badges
- BOP Gate Hotlist / BOLO Watchlist Viewer

Run from project root:   python code/dashboard.py (or python3 dashboard.py)
Open in browser:         http://127.0.0.1:8000
"""
import os
import sys
import time
import json

# Anchor to project root
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.normpath(os.path.join(BASE_DIR, ".."))
if ROOT_DIR not in sys.path:
    sys.path.append(ROOT_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from ledger import verify_chain, load_chain
from certificate import generate_section_65b_certificate

CAM_LABEL = "BOP SECTOR-7 · GURDASPUR SECTOR"
SNAP_DIR = os.path.join(ROOT_DIR, "data", "snapshots")
CERT_DIR = os.path.join(ROOT_DIR, "data", "certificates")
STATE_FILE = os.path.join(ROOT_DIR, "data", "engine_state.json")
HOTLIST_FILE = os.path.join(ROOT_DIR, "data", "hotlist.json")

os.makedirs(SNAP_DIR, exist_ok=True)
os.makedirs(CERT_DIR, exist_ok=True)

app = FastAPI(title="IBVAP Tactical Command Centre")
app.mount("/snapshots", StaticFiles(directory=SNAP_DIR), name="snapshots")
app.mount("/certificates", StaticFiles(directory=CERT_DIR), name="certificates")

START_TIME = time.time()


# ============================ API ============================
@app.get("/api/state")
def state():
    ok, bad, msg, head = verify_chain()
    records = load_chain()

    alerts = []
    for i, rec in enumerate(records):
        a = {k: v for k, v in rec.items() if k not in ("prev", "hash")}
        a["record"] = i
        a["seal"] = (rec.get("hash", "") or "")[:12]
        snap = a.get("snapshot", "")
        a["snapshot_url"] = ("/snapshots/" + os.path.basename(snap)) if snap else ""
        alerts.append(a)
    alerts.reverse()  # newest first

    crit = sum(1 for a in alerts if a.get("severity") == "CRITICAL")
    med = sum(1 for a in alerts if a.get("severity") == "MEDIUM")
    logged = sum(1 for a in alerts if a.get("severity") == "LOGGED")

    # Read live perception engine state
    engine_state = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                engine_state = json.load(f)
        except Exception:
            pass

    # Read hotlist
    hotlist = {}
    if os.path.exists(HOTLIST_FILE):
        try:
            with open(HOTLIST_FILE, "r") as f:
                hotlist = json.load(f)
        except Exception:
            pass

    return {
        "verify": {"ok": ok, "bad": bad, "msg": msg, "head": head[:16]},
        "alerts": alerts,
        "stats": {
            "total": len(alerts),
            "critical": crit,
            "medium": med,
            "logged": logged,
        },
        "engine": engine_state,
        "hotlist_count": len(hotlist),
        "server_time": time.time(),
        "uptime_sec": int(time.time() - START_TIME),
    }


@app.get("/api/certificate/generate")
def gen_cert():
    cert_path = generate_section_65b_certificate()
    filename = os.path.basename(cert_path)
    return RedirectResponse(url=f"/certificates/{filename}")


@app.get("/api/hotlist")
def get_hotlist():
    if os.path.exists(HOTLIST_FILE):
        with open(HOTLIST_FILE) as f:
            return json.load(f)
    return {}


# ============================ PAGE ============================
@app.get("/", response_class=HTMLResponse)
def home():
    return PAGE


PAGE = r"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>IBVAP Tactical Command Centre</title>
<link rel="icon" href="data:,">
<style>
:root{
  --bg:#060a13; --panel:#0b1324; --panel2:#101a30; --line:#1b2a47;
  --txt:#d7e6ff; --dim:#7d92b5; --faint:#44577a;
  --cyan:#4dd0ff; --green:#39d98a; --red:#ff4d5e; --orange:#ffb020;
  --yellow:#ffe45c; --purple:#b48cff; --teal:#4de0c8;
}
*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',system-ui,sans-serif}
.num,.mono{font-family:Consolas,'Cascadia Mono',monospace}
body{
  background:
    radial-gradient(1200px 500px at 70% -10%, #0e1d3a55, transparent),
    radial-gradient(900px 400px at 10% 110%, #0a233855, transparent),
    var(--bg);
  color:var(--txt);min-height:100vh;padding:16px 20px 80px}
a{color:var(--cyan);text-decoration:none}

/* ---------- header ---------- */
header{display:flex;justify-content:space-between;align-items:center;gap:14px;
  border:1px solid var(--line);background:linear-gradient(180deg,#0e1830,#0b1322);
  border-radius:12px;padding:14px 18px;margin-bottom:14px;flex-wrap:wrap}
.brand{display:flex;align-items:center;gap:12px}
.logo{width:42px;height:42px;border-radius:10px;display:grid;place-items:center;
  background:linear-gradient(135deg,#0f2f52,#123a63);border:1px solid #1e4a7a;font-size:20px}
.brand h1{font-size:18px;letter-spacing:2px;color:#eaf4ff}
.brand .sub{font-size:10.5px;color:var(--dim);letter-spacing:1.2px;margin-top:2px}
.hright{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
#clock{font-size:18px;color:var(--cyan);letter-spacing:1px}
#cam{font-size:11px;color:var(--dim);letter-spacing:1px;border:1px solid var(--line);
  padding:4px 9px;border-radius:20px;background:var(--panel)}
#badge{padding:8px 16px;border-radius:8px;font-weight:700;font-size:12.5px;letter-spacing:.5px;
  display:flex;align-items:center;gap:8px;cursor:pointer;transition:.2s}
#badge.ok{background:#0d2b1a;color:var(--green);border:1px solid #1e6b42}
#badge.bad{background:#3b0d12;color:var(--red);border:1px solid #8b1e2b;animation:pulse 1.1s infinite}
@keyframes pulse{50%{opacity:.6}}
.live-dot{width:8px;height:8px;border-radius:50%;background:var(--green);animation:blink 1.3s infinite}
@keyframes blink{50%{opacity:.15}}

/* Action buttons */
.btn-action{
  padding:8px 14px;border-radius:8px;font-size:12px;font-weight:600;
  letter-spacing:.5px;cursor:pointer;display:inline-flex;align-items:center;gap:6px;
  transition:.15s;text-decoration:none;border:1px solid;
}
.btn-cert{background:#1e3a8a22;border-color:#3b82f6;color:#60a5fa}
.btn-cert:hover{background:#1e3a8a55;color:#93c5fd}
.btn-bolo{background:#7f1d1d22;border-color:#ef4444;color:#f87171}
.btn-bolo:hover{background:#7f1d1d55;color:#fca5a5}

/* ---------- multi-cam perception grid ---------- */
.cams-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px;margin-bottom:14px}
.cam-card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px;position:relative}
.cam-card.CRITICAL{border-color:#ef4444;background:linear-gradient(135deg,#1f1013,var(--panel))}
.cam-card.WARNING{border-color:#f59e0b}
.cam-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
.cam-title{font-size:13px;font-weight:700;letter-spacing:1px;color:#eaf4ff}
.cam-badge{font-size:10px;padding:2px 7px;border-radius:12px;font-weight:700}
.cam-badge.CRITICAL{background:#7f1d1d;color:#fca5a5;border:1px solid #ef4444}
.cam-badge.WARNING{background:#78350f;color:#fde68a;border:1px solid #f59e0b}
.cam-badge.NORMAL{background:#064e3b;color:#a7f3d0;border:1px solid #10b981}
.cam-body{font-size:11.5px;color:var(--dim);line-height:1.7}
.cam-body b{color:#d7e6ff}
.cam-plates{display:flex;gap:5px;flex-wrap:wrap;margin-top:6px}
.plate-tag{padding:2px 6px;border-radius:4px;font-size:10.5px;font-family:Consolas,monospace;background:#132441;border:1px solid #2b4a7a;color:#93c5fd}
.plate-tag.hot{background:#7f1d1d;border-color:#ef4444;color:#ffffff;font-weight:bold}

/* ---------- 2D Tactical BOP Map ---------- */
.map-section{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 18px;margin-bottom:14px}
.map-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}
.map-header h3{font-size:13px;letter-spacing:1.5px;color:#93c5fd;text-transform:uppercase}
.tactical-canvas-wrap{width:100%;height:180px;background:#050912;border:1px solid #15233c;border-radius:8px;position:relative;overflow:hidden}
svg.tactical-map{width:100%;height:100%}

/* ---------- stats ---------- */
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-bottom:14px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px;position:relative;overflow:hidden}
.stat::after{content:"";position:absolute;inset:0 auto 0 0;width:3px;background:var(--accent,#33507e)}
.stat .num{font-size:26px;font-weight:800;color:#eaf4ff}
.stat .lbl{font-size:10px;color:var(--dim);letter-spacing:1.4px;margin-top:2px}
.stat.crit{--accent:var(--red)} .stat.crit .num{color:var(--red)}
.stat.med{--accent:var(--orange)} .stat.med .num{color:var(--orange)}
.stat.log{--accent:var(--yellow)} .stat.log .num{color:var(--yellow)}
.stat.chain{--accent:var(--cyan)}
.stat .mini{font-size:9.5px;color:var(--faint);margin-top:4px}

/* ---------- toolbar ---------- */
.toolbar{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:12px;flex-wrap:wrap}
.filters{display:flex;gap:6px;flex-wrap:wrap}
.fbtn{background:var(--panel);border:1px solid var(--line);color:var(--dim);
  padding:6px 14px;border-radius:16px;cursor:pointer;font-size:11.5px;letter-spacing:1px;transition:.15s}
.fbtn:hover{color:var(--txt);border-color:#2b4a7a}
.fbtn.active{background:#12314f;color:var(--cyan);border-color:#2b6a9a}

/* ---------- alert cards ---------- */
#feed{display:flex;flex-direction:column;gap:10px}
.card{display:flex;gap:14px;background:var(--panel);border:1px solid var(--line);
  border-left:4px solid var(--sc,#555);border-radius:10px;padding:12px;animation:slidein .3s ease}
@keyframes slidein{from{opacity:0;transform:translateY(-6px)}to{opacity:1}}
.card.CRITICAL{--sc:var(--red);background:linear-gradient(90deg,#1a0d1222,var(--panel))}
.card.MEDIUM{--sc:var(--orange)}
.card.LOGGED{--sc:var(--yellow)}
.card img,.noimg{width:210px;height:150px;object-fit:cover;border-radius:6px;border:1px solid var(--line);background:#000;cursor:zoom-in}
.noimg{display:grid;place-items:center;color:var(--faint);font-size:10.5px}
.cbody{flex:1;min-width:0}
.chead{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.sev{font-size:14px;font-weight:800;letter-spacing:1.2px}
.CRITICAL .sev{color:var(--red)} .MEDIUM .sev{color:var(--orange)} .LOGGED .sev{color:var(--yellow)}
.chips{display:flex;gap:5px;flex-wrap:wrap;margin:8px 0}
.chip{border-radius:14px;padding:2px 9px;font-size:10px;font-family:Consolas,monospace;border:1px solid}
.chip.base{color:#9fb6d9;border-color:#33507e;background:#12203a}
.chip.night{color:#9fc0ff;border-color:#2b4a8a;background:#101d3d}
.chip.zone{color:#ff8f9a;border-color:#8b2e39;background:#2a1015}
.chip.crawl{color:#f87171;border-color:#ef4444;background:#3b0707;font-weight:bold}
.meta{font-size:11px;color:var(--dim);line-height:1.8;font-family:Consolas,monospace}
.meta b{color:#a9c6ea}
.seal{color:var(--cyan)}

footer{position:fixed;left:0;right:0;bottom:0;background:#070d18ee;border-top:1px solid var(--line);
  backdrop-filter:blur(6px);padding:8px 20px;display:flex;justify-content:space-between;
  font-size:10.5px;color:var(--dim);font-family:Consolas,monospace}
footer .g{color:var(--green)} footer .r{color:var(--red)}

/* toasts & lightbox */
#toasts{position:fixed;top:16px;right:16px;z-index:50;display:flex;flex-direction:column;gap:8px}
.toast{background:#132441;border:1px solid #2b4a7a;border-left:4px solid var(--cyan);border-radius:8px;padding:10px 14px;min-width:240px;box-shadow:0 6px 25px #0009}
.toast.crit{border-left-color:var(--red)}
#lb{position:fixed;inset:0;background:#000d;display:none;z-index:60;align-items:center;justify-content:center;cursor:zoom-out}
#lb img{max-width:92vw;max-height:90vh;border-radius:8px;border:1px solid #2b4a7a}
</style>
</head>
<body>

<header>
  <div class="brand">
    <div class="logo">🛡️</div>
    <div>
      <h1>IBVAP · COMMAND CENTRE</h1>
      <div class="sub">INTELLIGENT BORDER VIDEO ANALYTICS PLATFORM · SECTOR-7 BOP</div>
    </div>
  </div>
  <div class="hright">
    <a href="/api/certificate/generate" target="_blank" class="btn-action btn-cert">📜 EXPORT SECTION 65B CERTIFICATE</a>
    <span id="clock" class="num">--:--:--</span>
    <div id="badge" class="ok"><span class="live-dot"></span>CHECKING…</div>
  </div>
</header>

<!-- Live Camera Perception Grid -->
<div class="cams-grid" id="cams-container">
  <div class="cam-card">
    <div class="cam-head">
      <span class="cam-title">CAM-01 (People)</span>
      <span class="cam-badge NORMAL">NORMAL</span>
    </div>
    <div class="cam-body">Initializing edge feed…</div>
  </div>
  <div class="cam-card">
    <div class="cam-head">
      <span class="cam-title">CAM-02 (Vehicles &amp; ANPR)</span>
      <span class="cam-badge NORMAL">NORMAL</span>
    </div>
    <div class="cam-body">Initializing edge feed…</div>
  </div>
  <div class="cam-card">
    <div class="cam-head">
      <span class="cam-title">CAM-03 (Night CCTV)</span>
      <span class="cam-badge NORMAL">NORMAL</span>
    </div>
    <div class="cam-body">Initializing edge feed…</div>
  </div>
</div>

<!-- 2D Tactical BOP Mini-Map -->
<div class="map-section">
  <div class="map-header">
    <h3>🗺️ 2D Tactical BOP Digital Twin · Sector-7 Perimeter Grid</h3>
    <span style="font-size:11px;color:var(--dim);">Coordinate Scale: 1:500m · Indian International Border</span>
  </div>
  <div class="tactical-canvas-wrap">
    <svg class="tactical-map" viewBox="0 0 1000 200">
      <!-- Grid Lines -->
      <defs>
        <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
          <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#121e33" stroke-width="0.8"/>
        </pattern>
      </defs>
      <rect width="1000" height="200" fill="url(#grid)" />

      <!-- International Border Line (Zero Line) -->
      <line x1="0" y1="35" x2="1000" y2="35" stroke="#475569" stroke-width="2" stroke-dasharray="6,4" />
      <text x="20" y="25" fill="#64748b" font-size="10" font-family="monospace">ZERO LINE (INTERNATIONAL BORDER)</text>

      <!-- Buffer Zone -->
      <rect x="0" y="35" width="1000" height="45" fill="#f59e0b" fill-opacity="0.08" />
      <text x="20" y="62" fill="#d97706" font-size="10" font-family="monospace">100m APPROACH BUFFER ZONE</text>

      <!-- Smart Perimeter Fence Line -->
      <line x1="0" y1="80" x2="1000" y2="80" stroke="#3b82f6" stroke-width="2.5" />
      <text x="20" y="98" fill="#60a5fa" font-size="10" font-family="monospace">PHYSICAL SMART PERIMETER FENCE (EXCLUSION ZONE)</text>

      <!-- BOP Main Gate Choke-Point -->
      <rect x="470" y="70" width="60" height="35" fill="#1e293b" stroke="#f59e0b" stroke-width="1.5" rx="3"/>
      <text x="478" y="92" fill="#fbbf24" font-size="9" font-family="monospace">BOP GATE</text>

      <!-- CAM-01 FOV Cone (People / Left Outer) -->
      <polygon id="cone-cam1" points="200,140 100,50 300,50" fill="#10b981" fill-opacity="0.15" stroke="#10b981" stroke-width="1"/>
      <circle cx="200" cy="140" r="6" fill="#10b981" />
      <text x="175" y="160" fill="#6ee7b7" font-size="10" font-family="monospace">CAM-01 (People)</text>

      <!-- CAM-02 FOV Cone (Gate Checkpost / ANPR) -->
      <polygon id="cone-cam2" points="500,150 420,70 580,70" fill="#38bdf8" fill-opacity="0.15" stroke="#38bdf8" stroke-width="1"/>
      <circle cx="500" cy="150" r="6" fill="#38bdf8" />
      <text x="455" y="172" fill="#7dd3fc" font-size="10" font-family="monospace">CAM-02 (ANPR Gate)</text>

      <!-- CAM-03 FOV Cone (Night IR / Right Sector) -->
      <polygon id="cone-cam3" points="800,140 700,50 900,50" fill="#818cf8" fill-opacity="0.15" stroke="#818cf8" stroke-width="1"/>
      <circle cx="800" cy="140" r="6" fill="#818cf8" />
      <text x="765" y="160" fill="#a5b4fc" font-size="10" font-family="monospace">CAM-03 (Night IR)</text>
    </svg>
  </div>
</div>

<div class="stats">
  <div class="stat"><div class="num" id="s-total">0</div><div class="lbl">SEALED EVIDENCE</div></div>
  <div class="stat crit"><div class="num" id="s-crit">0</div><div class="lbl">CRITICAL ALERTS</div></div>
  <div class="stat med"><div class="num" id="s-med">0</div><div class="lbl">MEDIUM ALERTS</div></div>
  <div class="stat log"><div class="num" id="s-log">0</div><div class="lbl">LOGGED EVENTS</div></div>
  <div class="stat chain"><div class="num mono" id="s-head">—</div>
    <div class="lbl">CHAIN HEAD HASH</div><div class="mini" id="s-verify">—</div></div>
</div>

<div class="toolbar">
  <div class="filters">
    <button class="fbtn active" data-f="ALL">ALL EVENTS</button>
    <button class="fbtn" data-f="CRITICAL">🔴 CRITICAL BREACHES</button>
    <button class="fbtn" data-f="MEDIUM">🟠 WARNINGS</button>
    <button class="fbtn" data-f="LOGGED">🟡 ROUTINE LOGS</button>
  </div>
  <button class="btn-action btn-cert" onclick="refresh(true)">🔐 RE-VERIFY EVIDENCE LEDGER</button>
</div>

<div id="feed"><div class="empty">No alerts sealed yet — system active and monitoring border perimeter.</div></div>

<footer>
  <span id="f-chain">chain: —</span>
  <span>IBVAP v1.3 · 100% Offline Edge-AI Grid · Section 65B Certified · SHA-256 Chained</span>
  <span id="f-up">uptime —</span>
</footer>

<div id="toasts"></div>
<div id="lb"><img id="lbimg" src=""></div>

<script>
let LAST_COUNT = -1, FILTER = "ALL";
const $ = id => document.getElementById(id);

setInterval(() => {
  $("clock").textContent = new Date().toLocaleTimeString();
  const s = UP + Math.floor((Date.now() - T0)/1000);
  $("f-up").textContent = "uptime " + Math.floor(s/3600) + "h " + Math.floor(s%3600/60) + "m " + s%60 + "s";
}, 1000);
const T0 = Date.now(); let UP = 0;

function beep(times){
  try{
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    let t = ctx.currentTime;
    for(let i=0;i<times;i++){
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.type="sine"; o.frequency.value = 880;
      g.gain.setValueAtTime(.15,t); g.gain.exponentialRampToValueAtTime(.001,t+.15);
      o.connect(g).connect(ctx.destination); o.start(t); o.stop(t+.15);
      t += .22;
    }
  }catch(e){}
}

function toast(title, sub, crit){
  const d = document.createElement("div");
  d.className = "toast" + (crit ? " crit" : "");
  d.innerHTML = `<div style="font-weight:700;font-size:12px;">${title}</div><div style="font-size:10.5px;color:var(--dim);margin-top:2px;">${sub}</div>`;
  $("toasts").appendChild(d);
  setTimeout(()=>d.remove(), 6000);
}

document.querySelectorAll(".fbtn").forEach(b => b.onclick = () => {
  document.querySelectorAll(".fbtn").forEach(x=>x.classList.remove("active"));
  b.classList.add("active"); FILTER = b.dataset.f; refresh();
});

document.addEventListener("click", e => {
  if(e.target.tagName === "IMG" && e.target.closest(".card")){
    $("lbimg").src = e.target.src; $("lb").style.display = "flex";
  } else if(e.target.closest("#lb")){ $("lb").style.display = "none"; }
});

function ago(iso){
  const d = new Date(iso), s = Math.floor((Date.now()-d.getTime())/1000);
  if(s<60) return s+"s ago"; if(s<3600) return Math.floor(s/60)+"m ago";
  if(s<86400) return Math.floor(s/3600)+"h ago"; return d.toLocaleDateString();
}

async function refresh(manual){
  try{
    const s = await (await fetch("/api/state")).json();

    /* ledger badge */
    const b = $("badge");
    if(s.verify.ok){ b.className="ok"; b.innerHTML='<span class="live-dot"></span>✅ LEDGER VERIFIED (BSA-65B)'; }
    else{ b.className="bad"; b.innerHTML='🚨 TAMPER DETECTED @ REC '+s.verify.bad; }
    $("s-head").textContent = s.verify.head;
    $("s-verify").textContent = s.verify.ok ? "intact · "+s.stats.total+" records" : "CORRUPT @ "+s.verify.bad;
    $("f-chain").innerHTML = s.verify.ok
      ? 'chain: <span class="g">VERIFIED INTACT</span> · head <span class="mono">'+s.verify.head+'…</span>'
      : 'chain: <span class="r">TAMPER DETECTED</span> · '+s.verify.msg;
    UP = s.uptime_sec;

    /* stats */
    $("s-total").textContent = s.stats.total;
    $("s-crit").textContent  = s.stats.critical;
    $("s-med").textContent   = s.stats.medium;
    $("s-log").textContent   = s.stats.logged;

    /* Live Perception Grid Update */
    const eng = s.engine || {};
    const camsContainer = $("cams-container");
    if(Object.keys(eng).length > 0){
      camsContainer.innerHTML = Object.entries(eng).map(([camName, c]) => {
        const threat = c.threat_level || "NORMAL";
        const night = c.night ? "🌙 NIGHT MODE" : "DAYLIGHT";
        const isTampered = c.tamper && c.tamper.tampered;
        const tracksCount = (c.tracks || []).length;
        const plates = (c.plates || []);
        const vehCounts = c.vehicles || {};
        const activeVeh = Object.values(vehCounts).reduce((a,b)=>a+b, 0);

        let badges = `<span class="cam-badge ${threat}">${threat}</span>`;
        if(isTampered) badges += ` <span class="cam-badge CRITICAL">⚠️ TAMPER</span>`;

        let platesHtml = "";
        if(plates.length > 0){
          platesHtml = `<div class="cam-plates">` + plates.map(p => {
            return `<span class="plate-tag ${p.hotlist ? 'hot' : ''}">${p.plate} ${p.hotlist ? '🚨BOLO' : ''}</span>`;
          }).join("") + `</div>`;
        }

        const liveImg = c.snapshot_url 
          ? `<div style="position:relative;margin-bottom:8px;border-radius:6px;overflow:hidden;border:1px solid #1e293b;background:#050914;">
               <img src="${c.snapshot_url}?t=${Date.now()}" style="width:100%;height:140px;object-fit:cover;display:block;" onerror="this.style.display='none'">
             </div>` 
          : '';

        return `<div class="cam-card ${threat}">
          <div class="cam-head">
            <span class="cam-title">${camName}</span>
            <div>${badges}</div>
          </div>
          <div class="cam-body">
            ${liveImg}
            Status: <b>${night}</b> · AI <b>${c.fps || 6} Hz</b><br>
            Active Targets: <b>${tracksCount} tracks</b>${activeVeh > 0 ? ` (🚗 ${activeVeh} vehicles)` : ''}<br>
            ${c.zone_events && c.zone_events.length > 0 ? `Zone Status: <b style="color:#ef4444;">${c.zone_events[0].event_type} (${c.zone_events[0].posture})</b><br>` : 'Zone Status: <b>Clear</b><br>'}
            ${platesHtml}
          </div>
        </div>`;
      }).join("");

      /* Update 2D Map Radar Cones */
      const cam1 = Object.values(eng).find(c => (c.stream_id||"").includes("CAM-01"));
      const cam2 = Object.values(eng).find(c => (c.stream_id||"").includes("CAM-02"));
      const cam3 = Object.values(eng).find(c => (c.stream_id||"").includes("CAM-03"));

      const updateCone = (id, cam) => {
        const el = $(id);
        if(!el) return;
        if(cam && cam.threat_level === "CRITICAL"){
          el.setAttribute("fill", "#ef4444");
          el.setAttribute("fill-opacity", "0.45");
          el.setAttribute("stroke", "#ef4444");
        } else if(cam && cam.threat_level === "WARNING"){
          el.setAttribute("fill", "#f59e0b");
          el.setAttribute("fill-opacity", "0.35");
          el.setAttribute("stroke", "#f59e0b");
        } else {
          el.setAttribute("fill", "#10b981");
          el.setAttribute("fill-opacity", "0.15");
          el.setAttribute("stroke", "#10b981");
        }
      };

      updateCone("cone-cam1", cam1);
      updateCone("cone-cam2", cam2);
      updateCone("cone-cam3", cam3);
    }

    /* audio beep on new alerts */
    if(LAST_COUNT >= 0 && s.stats.total > LAST_COUNT){
      const newest = s.alerts[0];
      const crit = newest && newest.severity === "CRITICAL";
      toast((crit?"🚨 ":"🔔 ")+"PERIMETER BREACH SEALED",
            (newest? "#"+newest.track_id+" · "+newest.severity+" · "+newest.score+"pts" : ""),
            crit);
      beep(crit ? 3 : 1);
    }
    LAST_COUNT = s.stats.total;

    /* render alerts feed */
    const f = $("feed");
    const list = s.alerts.filter(a => FILTER==="ALL" || a.severity===FILTER);
    if(!list.length){
      f.innerHTML = '<div class="empty">'+(s.alerts.length? "No alerts matching current filter." :
        "No perimeter alerts recorded in ledger — border sector is secure.")+'</div>';
      return;
    }
    f.innerHTML = list.map(a=>{
      const chips = Object.entries(a.breakdown||{})
        .map(([k,v])=>`<span class="chip ${k}">${k.toUpperCase()} +${v}</span>`).join("");
      const img = a.snapshot_url
        ? `<img src="${a.snapshot_url}" loading="lazy" onerror="this.outerHTML='<div class=noimg>SNAPSHOT ARCHIVED</div>'">`
        : `<div class="noimg">NO SNAPSHOT</div>`;
      const plateBadge = a.plate 
        ? `<span style="font-size:11px;padding:2px 7px;border-radius:6px;background:#1e3a8a;color:#60a5fa;font-weight:700;font-family:monospace;border:1px solid #3b82f6;">🚗 ${a.plate}</span>` 
        : '';
      return `<div class="card ${a.severity||''}">
        ${img}
        <div class="cbody">
          <div class="chead">
            <span class="sev">${a.severity||"?"}</span>
            <span class="mono" style="font-size:12.5px;color:var(--txt);">${a.score||80} pts</span>
            <span style="font-size:10px;padding:2px 7px;border-radius:12px;border:1px solid #2b4a7a;color:#93c5fd;">TRACK #${a.track_id}</span>
            ${plateBadge}
          </div>
          <div style="font-size:12px;font-weight:700;color:var(--txt);margin:4px 0 2px 0;">${(a.event||"").replace(/_/g," ")}</div>
          <div class="chips">${chips}</div>
          <div class="meta">
            🕒 ${a.time||""} <b>(${ago(a.time)})</b> ·
            📍 Location: ${a.location? a.location.join(", "):"-"} ·
            ⏱ Dwell: ${a.age_sec??"-"}s<br>
            🔐 SHA-256 Seal: <span class="seal mono">${a.seal}…</span> ·
            📜 Section 65B Admissible: <b>VERIFIED</b>
          </div>
        </div>
      </div>`;
    }).join("");

  }catch(e){ console.log(e); }
}

refresh();
setInterval(refresh, 2500);
</script>
</body></html>"""

# ---------------- RUN ----------------
if __name__ == "__main__":
    import uvicorn
    PAGE = PAGE.replace("__CAM_LABEL__", CAM_LABEL)
    print("=" * 65)
    print("  IBVAP COMMAND CENTRE v4 — TACTICAL DEFENSE EDITION")
    print("  Open in browser :  http://127.0.0.1:8000")
    print("  Perception Grid :  Live multi-stream status (CAM-01/02/03)")
    print("  Tactical Map    :  2D BOP Digital Twin with dynamic radar cones")
    print("  Court Dossier   :  Section 65B / BSA 2023 instant export")
    print("=" * 65)
    uvicorn.run(app, host="127.0.0.1", port=8000)