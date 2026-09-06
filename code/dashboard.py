r"""
IBVAP - Day 6 v3: COMMAND CENTRE DASHBOARD (UI/UX redesign)
- Data-only polling (no page reloads - lag fixed)
- Live tamper badge (re-verifies ledger every poll)
- Severity filters, toasts, image lightbox, alert sounds
- Live clock, relative timestamps, chain head display

Run FROM PROJECT ROOT:   python code/dashboard.py
Open in browser:         http://127.0.0.1:8000
"""
import os, time

# anchor to project root (immune to launch directory)
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from ledger import verify_chain, load_chain

CAM_LABEL = "CAM-01 · BOP SECTOR-7"          # customize per camera
os.makedirs("data/snapshots", exist_ok=True)

app = FastAPI(title="IBVAP Command Centre")
app.mount("/snapshots", StaticFiles(directory="data/snapshots"), name="snapshots")

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
    alerts.reverse()                                   # newest first

    crit = sum(1 for a in alerts if a.get("severity") == "CRITICAL")
    med  = sum(1 for a in alerts if a.get("severity") == "MEDIUM")
    logged = sum(1 for a in alerts if a.get("severity") == "LOGGED")

    return {"verify": {"ok": ok, "bad": bad, "msg": msg, "head": head[:16]},
            "alerts": alerts,
            "stats": {"total": len(alerts), "critical": crit,
                      "medium": med, "logged": logged},
            "server_time": time.time(), "uptime_sec": int(time.time() - START_TIME)}

# ============================ PAGE ============================
@app.get("/", response_class=HTMLResponse)
def home():
    return PAGE

PAGE = r"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>IBVAP Command Centre</title>
<link rel="icon" href="data:,">
<style>
:root{
  --bg:#070b14; --panel:#0d1526; --panel2:#101a30; --line:#1b2a47;
  --txt:#d7e6ff; --dim:#7d92b5; --faint:#44577a;
  --cyan:#4dd0ff; --green:#39d98a; --red:#ff4d5e; --orange:#ffb020;
  --yellow:#ffe45c; --purple:#b48cff; --teal:#4de0c8;
}
*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',system-ui,sans-serif}
.num,.mono{font-family:Consolas,'Cascadia Mono',monospace}
body{background:
  radial-gradient(1200px 500px at 70% -10%, #0e1d3a55, transparent),
  radial-gradient(900px 400px at 10% 110%, #0a233855, transparent),
  var(--bg);
  color:var(--txt);min-height:100vh;padding:20px 22px 90px}
a{color:var(--cyan)}

/* ---------- header ---------- */
header{display:flex;justify-content:space-between;align-items:center;gap:16px;
  border:1px solid var(--line);background:linear-gradient(180deg,#0e1830,#0b1322);
  border-radius:14px;padding:16px 20px;margin-bottom:14px;flex-wrap:wrap}
.brand{display:flex;align-items:center;gap:14px}
.logo{width:44px;height:44px;border-radius:10px;display:grid;place-items:center;
  background:linear-gradient(135deg,#0f2f52,#123a63);border:1px solid #1e4a7a;
  font-size:20px}
.brand h1{font-size:19px;letter-spacing:3px;color:#eaf4ff}
.brand .sub{font-size:11px;color:var(--dim);letter-spacing:1.5px;margin-top:2px}
.hright{display:flex;align-items:center;gap:14px;flex-wrap:wrap}
#clock{font-size:20px;color:var(--cyan);letter-spacing:1px}
#cam{font-size:11px;color:var(--dim);letter-spacing:1px;border:1px solid var(--line);
  padding:5px 10px;border-radius:20px;background:var(--panel)}
#badge{padding:11px 20px;border-radius:10px;font-weight:700;font-size:14px;letter-spacing:.5px;
  display:flex;align-items:center;gap:9px;cursor:pointer;transition:.2s}
#badge.ok{background:#0d2b1a;color:var(--green);border:1px solid #1e6b42}
#badge.bad{background:#3b0d12;color:var(--red);border:1px solid #8b1e2b;
  animation:pulse 1.1s infinite}
@keyframes pulse{50%{opacity:.6}}
.live-dot{width:8px;height:8px;border-radius:50%;background:var(--green);
  animation:blink 1.3s infinite}
@keyframes blink{50%{opacity:.15}}

/* ---------- stats ---------- */
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
  gap:12px;margin-bottom:14px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:12px;
  padding:14px 16px;position:relative;overflow:hidden}
.stat::after{content:"";position:absolute;inset:0 auto 0 0;width:3px;
  background:var(--accent,#33507e)}
.stat .num{font-size:30px;font-weight:800;color:#eaf4ff}
.stat .lbl{font-size:10.5px;color:var(--dim);letter-spacing:1.6px;margin-top:3px}
.stat.crit{--accent:var(--red)} .stat.crit .num{color:var(--red)}
.stat.med{--accent:var(--orange)} .stat.med .num{color:var(--orange)}
.stat.log{--accent:var(--yellow)} .stat.log .num{color:var(--yellow)}
.stat.chain{--accent:var(--cyan)}
.stat .mini{font-size:10px;color:var(--faint);margin-top:6px}

/* ---------- toolbar ---------- */
.toolbar{display:flex;justify-content:space-between;align-items:center;gap:12px;
  margin-bottom:14px;flex-wrap:wrap}
.filters{display:flex;gap:8px;flex-wrap:wrap}
.fbtn{background:var(--panel);border:1px solid var(--line);color:var(--dim);
  padding:8px 16px;border-radius:20px;cursor:pointer;font-size:12px;letter-spacing:1px;
  transition:.15s}
.fbtn:hover{color:var(--txt);border-color:#2b4a7a}
.fbtn.active{background:#12314f;color:var(--cyan);border-color:#2b6a9a}
#verifybtn{background:linear-gradient(180deg,#123a5e,#0e2c48);color:var(--cyan);
  border:1px solid #2b6a9a;border-radius:10px;padding:11px 22px;cursor:pointer;
  font-size:12.5px;letter-spacing:1.2px;font-weight:600;transition:.15s}
#verifybtn:hover{filter:brightness(1.25)}
#verifybtn:active{transform:scale(.97)}

/* ---------- alert cards ---------- */
#feed{display:flex;flex-direction:column;gap:10px}
.card{display:flex;gap:14px;background:var(--panel);border:1px solid var(--line);
  border-left:4px solid var(--sc,#555);border-radius:12px;padding:12px;
  animation:slidein .35s ease}
@keyframes slidein{from{opacity:0;transform:translateY(-8px)}to{opacity:1}}
.card.CRITICAL{--sc:var(--red);background:linear-gradient(90deg,#1a0d1222,var(--panel))}
.card.MEDIUM{--sc:var(--orange)}
.card.LOGGED{--sc:var(--yellow)}
.card img,.noimg{width:230px;height:172px;object-fit:cover;border-radius:8px;
  border:1px solid var(--line);background:#000;cursor:zoom-in;transition:.2s}
.card img:hover{filter:brightness(1.1)}
.noimg{display:grid;place-items:center;color:var(--faint);font-size:11px;cursor:default}
.cbody{flex:1;min-width:0}
.chead{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.sev{font-size:15px;font-weight:800;letter-spacing:1.5px}
.CRITICAL .sev{color:var(--red)} .MEDIUM .sev{color:var(--orange)}
.LOGGED .sev{color:var(--yellow)}
.score{font-size:13px;color:var(--txt)}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin:9px 0}
.chip{border-radius:20px;padding:3px 11px;font-size:10.5px;letter-spacing:.8px;
  border:1px solid;font-family:Consolas,monospace}
.chip.base{color:#9fb6d9;border-color:#33507e;background:#12203a}
.chip.night{color:#9fc0ff;border-color:#2b4a8a;background:#101d3d}
.chip.zone{color:#ff8f9a;border-color:#8b2e39;background:#2a1015}
.chip.slow{color:#ffcf8f;border-color:#8a6a2b;background:#241b0d}
.chip.dwell{color:#d0b6ff;border-color:#5c3f8a;background:#170f2a}
.chip.group{color:#8fe6d8;border-color:#2b7a6a;background:#0d2420}
.chip.run{color:#ff9f7a;border-color:#8a4a2b;background:#241410}
.meta{font-size:11.5px;color:var(--dim);line-height:1.9;font-family:Consolas,monospace}
.meta b{color:#a9c6ea;font-weight:600}
.seal{color:var(--cyan)}
.cardfoot{display:flex;gap:10px;margin-top:8px}
.pill{font-size:10px;letter-spacing:1px;color:var(--dim);border:1px solid var(--line);
  padding:3px 9px;border-radius:20px}
.pill.trk{color:#8fb6ff;border-color:#2b4a7a}

/* ---------- misc ---------- */
.empty{border:1px dashed var(--line);border-radius:14px;padding:70px 20px;
  text-align:center;color:var(--faint);font-size:13.5px;letter-spacing:.5px}
footer{position:fixed;left:0;right:0;bottom:0;background:#0a1120ee;
  border-top:1px solid var(--line);backdrop-filter:blur(6px);
  padding:9px 22px;display:flex;justify-content:space-between;gap:14px;
  font-size:11px;color:var(--dim);font-family:Consolas,monospace;flex-wrap:wrap}
footer .g{color:var(--green)} footer .r{color:var(--red)}

/* toast */
#toasts{position:fixed;top:18px;right:18px;z-index:50;display:flex;
  flex-direction:column;gap:10px}
.toast{background:#132441;border:1px solid #2b4a7a;border-left:4px solid var(--cyan);
  border-radius:10px;padding:12px 16px;min-width:260px;box-shadow:0 8px 30px #0009;
  animation:tin .3s ease}
.toast.crit{border-left-color:var(--red)}
.toast .t1{font-size:12.5px;font-weight:700;letter-spacing:.5px}
.toast .t2{font-size:11px;color:var(--dim);margin-top:3px;font-family:Consolas,monospace}
@keyframes tin{from{opacity:0;transform:translateX(30px)}to{opacity:1}}

/* lightbox */
#lb{position:fixed;inset:0;background:#000d;display:none;z-index:60;
  align-items:center;justify-content:center;cursor:zoom-out}
#lb img{max-width:92vw;max-height:90vh;border-radius:10px;border:1px solid #2b4a7a}
</style>
</head>
<body>

<header>
  <div class="brand">
    <div class="logo">🛡️</div>
    <div>
      <h1>IBVAP · COMMAND CENTRE</h1>
      <div class="sub">INTELLIGENT BORDER VIDEO ANALYTICS PLATFORM</div>
    </div>
  </div>
  <div class="hright">
    <span id="cam">📡 __CAM_LABEL__</span>
    <span id="clock" class="num">--:--:--</span>
    <div id="badge" class="ok"><span class="live-dot"></span>CHECKING…</div>
  </div>
</header>

<div class="stats">
  <div class="stat"><div class="num" id="s-total">0</div><div class="lbl">SEALED ALERTS</div></div>
  <div class="stat crit"><div class="num" id="s-crit">0</div><div class="lbl">CRITICAL</div></div>
  <div class="stat med"><div class="num" id="s-med">0</div><div class="lbl">MEDIUM</div></div>
  <div class="stat log"><div class="num" id="s-log">0</div><div class="lbl">LOGGED</div></div>
  <div class="stat chain"><div class="num mono" id="s-head">—</div>
    <div class="lbl">CHAIN HEAD</div><div class="mini" id="s-verify">—</div></div>
</div>

<div class="toolbar">
  <div class="filters">
    <button class="fbtn active" data-f="ALL">ALL</button>
    <button class="fbtn" data-f="CRITICAL">🔴 CRITICAL</button>
    <button class="fbtn" data-f="MEDIUM">🟠 MEDIUM</button>
    <button class="fbtn" data-f="LOGGED">🟡 LOGGED</button>
  </div>
  <button id="verifybtn" onclick="refresh(true)">🔐 VERIFY EVIDENCE CHAIN</button>
</div>

<div id="feed"><div class="empty">No alerts sealed yet — run rule.py, arm the fence, and trigger an intrusion.</div></div>

<footer>
  <span id="f-chain">chain: —</span>
  <span>poll 4s · offline-capable · SHA-256 hash-chained evidence</span>
  <span id="f-up">uptime —</span>
</footer>

<div id="toasts"></div>
<div id="lb"><img id="lbimg" src=""></div>

<script>
let LAST_COUNT = -1, FILTER = "ALL";
const $ = id => document.getElementById(id);

/* ---------- clock + uptime ---------- */
setInterval(() => {
  $("clock").textContent = new Date().toLocaleTimeString();
  const s = UP + Math.floor((Date.now() - T0)/1000);
  $("f-up").textContent = "uptime " + Math.floor(s/3600) + "h " + Math.floor(s%3600/60) + "m " + s%60 + "s";
}, 1000);
const T0 = Date.now(); let UP = 0;

/* ---------- sound (Web Audio, no files) ---------- */
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

/* ---------- toast ---------- */
function toast(title, sub, crit){
  const d = document.createElement("div");
  d.className = "toast" + (crit ? " crit" : "");
  d.innerHTML = `<div class="t1">${title}</div><div class="t2">${sub}</div>`;
  $("toasts").appendChild(d);
  setTimeout(()=>d.remove(), 6000);
}

/* ---------- filters ---------- */
document.querySelectorAll(".fbtn").forEach(b => b.onclick = () => {
  document.querySelectorAll(".fbtn").forEach(x=>x.classList.remove("active"));
  b.classList.add("active"); FILTER = b.dataset.f; refresh();
});

/* ---------- lightbox ---------- */
document.addEventListener("click", e => {
  if(e.target.tagName === "IMG" && e.target.closest(".card")){
    $("lbimg").src = e.target.src; $("lb").style.display = "flex";
  } else if(e.target.closest("#lb")){ $("lb").style.display = "none"; }
});

/* ---------- relative time ---------- */
function ago(iso){
  const d = new Date(iso), s = Math.floor((Date.now()-d.getTime())/1000);
  if(s<60) return s+"s ago"; if(s<3600) return Math.floor(s/60)+"m ago";
  if(s<86400) return Math.floor(s/3600)+"h ago"; return d.toLocaleDateString();
}

/* ---------- main refresh (data only — never reloads page) ---------- */
async function refresh(manual){
  try{
    const s = await (await fetch("/api/state")).json();

    /* badge */
    const b = $("badge");
    if(s.verify.ok){ b.className="ok"; b.innerHTML='<span class="live-dot"></span>✅ EVIDENCE CHAIN VERIFIED'; }
    else{ b.className="bad"; b.innerHTML='🚨 EVIDENCE CHAIN TAMPERED — record '+s.verify.bad; }
    $("s-head").textContent = s.verify.head;
    $("s-verify").textContent = s.verify.ok ? "intact · "+s.stats.total+" records" : "BROKEN @ "+s.verify.bad;
    $("f-chain").innerHTML = s.verify.ok
      ? 'chain: <span class="g">VERIFIED</span> · head <span class="mono">'+s.verify.head+'…</span>'
      : 'chain: <span class="r">TAMPERED</span> · '+s.verify.msg;
    UP = s.uptime_sec;

    /* stats */
    $("s-total").textContent = s.stats.total;
    $("s-crit").textContent  = s.stats.critical;
    $("s-med").textContent   = s.stats.medium;
    $("s-log").textContent   = s.stats.logged;

    /* new-alert detection → toast + sound */
    if(LAST_COUNT >= 0 && s.stats.total > LAST_COUNT){
      const newest = s.alerts[0];
      const crit = newest && newest.severity === "CRITICAL";
      toast((crit?"🚨 ":"🔔 ")+"NEW ALERT SEALED",
            (newest? "#"+newest.track_id+" · "+newest.severity+" · "+newest.score+"pts" : ""),
            crit);
      beep(crit ? 3 : 1);
    }
    LAST_COUNT = s.stats.total;

    /* feed */
    const f = $("feed");
    const list = s.alerts.filter(a => FILTER==="ALL" || a.severity===FILTER);
    if(!list.length){
      f.innerHTML = '<div class="empty">'+(s.alerts.length? "No alerts in this filter." :
        "No alerts sealed yet — run rule.py, arm the fence, and trigger an intrusion.")+'</div>';
      return;
    }
    f.innerHTML = list.map(a=>{
      const chips = Object.entries(a.breakdown||{})
        .map(([k,v])=>`<span class="chip ${k}">${k.toUpperCase()} +${v}</span>`).join("");
      const img = a.snapshot_url
        ? `<img src="${a.snapshot_url}" loading="lazy" onerror="this.outerHTML='<div class=noimg>IMAGE MISSING</div>'">`
        : `<div class="noimg">NO SNAPSHOT</div>`;
      return `<div class="card ${a.severity||''}">
        ${img}
        <div class="cbody">
          <div class="chead">
            <span class="sev">${a.severity||"?"}</span>
            <span class="score mono">${a.score} pts</span>
            <span class="pill trk">TRACK #${a.track_id}</span>
          </div>
          <div class="chips">${chips}</div>
          <div class="meta">
            🕒 ${a.time||""} <b>(${ago(a.time)})</b> ·
            📍 x,y ${a.location? a.location.join(", "):"-"} ·
            ⏱ age ${a.age_sec??"-"}s · v ${a.speed_px_s??"-"}px/s<br>
            🔐 sealed rec <b>#${a.record}</b> · seal <span class="seal mono">${a.seal}…</span> ·
            📄 ${a.snapshot? a.snapshot.split("/").pop() : "-"}<br>
            🧬 snapshot SHA-256 <span class="mono">${(a.snapshot_sha256||"").slice(0,24)}…</span>
          </div>
          <div class="cardfoot">
            <span class="pill">${(a.event||"").replace(/_/g," ")}</span>
          </div>
        </div>
      </div>`;
    }).join("");
  }catch(e){ console.log(e); }
}

refresh();
setInterval(refresh, 4000);
</script>
</body></html>"""

# ---------------- RUN ----------------
if __name__ == "__main__":
    import uvicorn
    PAGE = PAGE.replace("__CAM_LABEL__", CAM_LABEL)
    print("=" * 60)
    print("  IBVAP COMMAND CENTRE  v3")
    print("  Open in browser :  http://127.0.0.1:8000")
    print("  Polling         :  /api/state every 4s (data-only)")
    print("  Badge           :  live ledger re-verification")
    print("=" * 60)
    uvicorn.run(app, host="127.0.0.1", port=8000)