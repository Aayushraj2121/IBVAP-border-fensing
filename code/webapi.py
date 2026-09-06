r"""
IBVAP - webapi.py: Web Zone Editor + MJPEG Live Stream + Zones REST API
Runs INSIDE rule.py as a background thread (port 8001).

  GET  /mjpeg      -> live ANNOTATED stream (boxes, trails, zones)
  GET  /api/zones  -> list zones (from data/zones.json)
  POST /api/zones  -> persist zones (rule.py hot-reloads within ~1s)
  GET  /editor     -> HTML5 canvas polygon editor  (the Q4 killer demo)

Usage note: rule.py calls webapi.set_frame(frame) every loop with the
fully annotated frame; this module only SERVES it.
"""
import os, sys, time, threading

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))

import cv2
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
import zones as zonestore

app = FastAPI(title="IBVAP Zone Editor")

_lock = threading.Lock()
_latest_jpeg = None

def set_frame(frame_bgr):
    """rule.py feeds the annotated frame here every loop."""
    global _latest_jpeg
    if frame_bgr is None:
        return
    ok, buf = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 70])
    if ok:
        with _lock:
            _latest_jpeg = buf.tobytes()

@app.get("/mjpeg")
def mjpeg():
    def gen():
        while True:
            with _lock:
                jpg = _latest_jpeg
            if jpg:
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n")
            time.sleep(0.08)
    return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")

@app.get("/api/zones")
def get_zones():
    return zonestore.load_zones()

@app.post("/api/zones")
async def post_zones(req: Request):
    body = await req.json()
    clean = []
    for z in body:
        pts = [[int(round(p[0])), int(round(p[1]))] for p in z.get("points", [])]
        if len(pts) >= 3:
            clean.append({"name": str(z.get("name", "zone"))[:40],
                          "type": "restricted", "points": pts})
    zonestore.save_zones(clean)
    return {"ok": True, "zones": len(clean)}

EDITOR_PAGE = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>IBVAP Zone Editor</title>
<link rel="icon" href="data:,">
<style>
  body{background:#070b14;color:#d7e6ff;font-family:'Segoe UI',system-ui,sans-serif;padding:18px}
  h1{font-size:17px;letter-spacing:2px;color:#4dd0ff;margin-bottom:4px}
  .sub{font-size:11px;color:#7d92b5;margin-bottom:14px}
  .wrap{display:flex;gap:18px;flex-wrap:wrap}
  .stage{position:relative;width:640px;height:480px;border-radius:10px;
         overflow:hidden;border:1px solid #1b2a47}
  img{width:640px;height:480px;display:block}
  canvas{position:absolute;left:0;top:0;cursor:crosshair}
  .panel{width:300px}
  input{background:#101a30;border:1px solid #1b2a47;color:#d7e6ff;border-radius:8px;
        padding:9px 12px;width:calc(100% - 24px);font-size:13px;margin-bottom:10px}
  button{background:#12314f;color:#4dd0ff;border:1px solid #2b6a9a;border-radius:8px;
         padding:9px 14px;cursor:pointer;font-size:12.5px;letter-spacing:1px;margin:0 6px 10px 0}
  button:hover{filter:brightness(1.3)}
  button.danger{color:#ff4d5e;border-color:#8b1e2b;background:#2a1015}
  .zlist{margin-top:10px}
  .zitem{background:#101a30;border:1px solid #1b2a47;border-left:3px solid #ff4d5e;
         border-radius:8px;padding:9px 12px;margin-bottom:8px;display:flex;
         justify-content:space-between;align-items:center;font-size:12.5px}
  .hint{font-size:11.5px;color:#7d92b5;line-height:1.7;margin-top:12px}
  .ok{color:#39d98a}
</style></head>
<body>
<h1>IBVAP &middot; ZONE EDITOR</h1>
<div class="sub">Click points on the live view &rarr; Save. rule.py hot-reloads instantly — no restart, no code.</div>
<div class="wrap">
  <div class="stage">
    <img src="/mjpeg">
    <canvas id="cv" width="640" height="480"></canvas>
  </div>
  <div class="panel">
    <input id="zname" placeholder="Zone name (e.g. FENCE-LINE-SECTOR3)">
    <button onclick="saveZone()">💾 SAVE ZONE</button>
    <button onclick="pts=[];draw()">↺ CLEAR POINTS</button>
    <button onclick="pts.pop();draw()">↩ UNDO POINT</button>
    <div class="zlist" id="zlist"></div>
    <div class="hint">
      • Polygon needs ≥ 3 points (click the points in order).<br>
      • Right-click on canvas = undo last point.<br>
      • Zones persist to data/zones.json — they survive restarts.<br>
      • rule.py hot-reloads on every save.<br>
      • <span class="ok">Judge challenge:</span> "draw a fence without code" → done in 10 seconds.
    </div>
  </div>
</div>
<script>
const cv = document.getElementById('cv'), ctx = cv.getContext('2d');
let pts = [], zones = [];

async function loadZones(){
  zones = await (await fetch('/api/zones')).json();
  renderList(); draw();
}
function draw(){
  ctx.clearRect(0,0,640,480);
  for(const z of zones){
    const p = z.points;
    ctx.beginPath(); ctx.moveTo(p[0][0], p[0][1]);
    for(let i=1;i<p.length;i++) ctx.lineTo(p[i][0], p[i][1]);
    ctx.closePath();
    ctx.fillStyle='rgba(0,0,180,0.25)'; ctx.fill();
    ctx.strokeStyle='#ff4d5e'; ctx.lineWidth=2; ctx.stroke();
    ctx.fillStyle='#ff4d5e'; ctx.font='12px Consolas';
    ctx.fillText(z.name||'zone', p[0][0]+4, Math.max(14, p[0][1]-4));
  }
  if(pts.length){
    ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1]);
    for(let i=1;i<pts.length;i++) ctx.lineTo(pts[i][0], pts[i][1]);
    if(pts.length>2) ctx.closePath();
    ctx.strokeStyle='#ffe45c'; ctx.lineWidth=2; ctx.stroke();
    for(const p of pts){ ctx.beginPath(); ctx.arc(p[0],p[1],4,0,7);
      ctx.fillStyle='#ffe45c'; ctx.fill(); }
  }
}
cv.addEventListener('click', e=>{
  const r = cv.getBoundingClientRect();
  const x = Math.round((e.clientX - r.left) * (cv.width  / r.width));
  const y = Math.round((e.clientY - r.top)  * (cv.height / r.height));
  pts.push([x, y]); draw();
});
cv.addEventListener('contextmenu', e=>{
  e.preventDefault(); pts.pop(); draw();
});
async function pushZones(){
  await fetch('/api/zones',{method:'POST',headers:{'Content-Type':'application/json'},
    body: JSON.stringify(zones)});
}
async function saveZone(){
  if(pts.length<3){ alert('Need at least 3 points — click them on the video first'); return; }
  const name = document.getElementById('zname').value.trim() || ('ZONE-'+(zones.length+1));
  zones.push({name: name, type:'restricted', points: pts});
  await pushZones();
  pts = []; document.getElementById('zname').value='';
  await loadZones();
  flash('✅ Zone "'+name+'" saved — rule.py reloaded it live');
}
async function delZone(i){
  zones.splice(i,1);
  await pushZones();
  await loadZones();
  flash('Zone deleted — rule.py disarmed it');
}
function renderList(){
  document.getElementById('zlist').innerHTML = zones.length ? zones.map((z,i)=>
    '<div class="zitem"><span>'+(z.name||'zone')+' · '+z.points.length+' pts</span>'+
    '<button class="danger" onclick="delZone('+i+')">✕</button></div>').join('')
    : '<div style="color:#44577a;font-size:12px">No zones yet — click points on the video.</div>';
}
function flash(msg){
  const d=document.createElement('div');
  d.className='zitem'; d.style.borderLeftColor='#39d98a'; d.textContent=msg;
  document.getElementById('zlist').prepend(d);
  setTimeout(()=>d.remove(), 4000);
}
loadZones();
</script></body></html>"""

@app.get("/editor", response_class=HTMLResponse)
def editor():
    return EDITOR_PAGE