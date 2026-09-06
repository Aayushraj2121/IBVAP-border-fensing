r"""
IBVAP - rule.py v7: FULL INTEGRATION
  - YOLOv8n detection + ByteTrack persistent tracking (IDs, trails, age, speed)
  - Virtual fence: web-drawn zones (zones.json, hot-reload) + manual CV fallback
  - Explainable suspicion scoring engine (context: night/zone/slow/dwell/group/run)
  - Context-aware night detection (live: darkness+clock | file: darkness only)
  - Dual-path night engine: CLAHE enhancement + MOG2 motion anomaly fallback
  - FRS choke-point watchlist (YuNet+SFace) - graceful if models missing
  - C2 webhook dispatcher (Feature #8)
  - SHA-256 tamper-evident ledger sealing + evidence snapshots (Day 5)

Usage:
  python code/rule.py 0                                  <- live webcam
  python code/rule.py data/recorded_clips/test.mp4       <- video file
  python code/rule.py <source> day                       <- force daytime scoring

Web UIs (while running):
  http://127.0.0.1:8001/editor   <- draw zones in browser (hot-reload)
  http://127.0.0.1:8001/mjpeg    <- live annotated stream
  http://127.0.0.1:8000          <- command centre dashboard (separate terminal)

Keys: click fence points -> 'c' arm (fallback) | 'r' clear all zones | 'q' quit
"""
import os, sys

# ====== path anchoring: always run from project root ======
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time, json, datetime, threading
import cv2
import numpy as np
from ultralytics import YOLO

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from ledger import append_event, file_sha256
import zones as zonestore
import webapi

# ====== optional FRS (engine runs fine without it) ======
try:
    import frs as frslib
    _FACE_GALLERY = frslib.load_gallery()
    FRS_ENABLED = len(_FACE_GALLERY) > 0
except Exception as _e:
    frslib = None
    FRS_ENABLED = False
    _FACE_GALLERY = {}
    print("FRS disabled (", type(_e).__name__, ") - run frs.py enroll to enable")

# ================= TUNING CONFIG =================
TH = {"base": 10, "night": 25, "zone": 35, "slow": 15,
      "dwell": 15, "group": 10, "run": 10}          # night alone can NEVER alert

SLOW_PX, RUN_PX = 25.0, 350.0
DWELL_SEC       = 8.0
GROUP_N         = 2
DARK_MEAN       = 35.0
NIGHT_HOURS     = (22, 5)
SEV_CRITICAL, SEV_MEDIUM = 70, 40
ALERT_COOLDOWN  = 8.0             # per-track / per-identity
GLOBAL_COOLDOWN = 3.0             # system-wide rate limit
TRAIL_LEN       = 40
MOTION_PIX_THRESHOLD = 900        # MOG2: white px inside zone = motion

ANIMALS = {"cat","dog","cow","horse","sheep","bird","elephant","bear","zebra"}

# ============ C2 WEBHOOK (Feature #8) ============
# Paste a Sector HQ endpoint here. For testing: https://webhook.site free URL.
WEBHOOK_URL = ""                  # empty = disabled

def dispatch_webhook(rec: dict):
    """Fire-and-forget POST to external C2. Never breaks the pipeline."""
    if not WEBHOOK_URL:
        return
    try:
        import requests
        requests.post(WEBHOOK_URL, json=rec, timeout=2)
        print("📡 webhook dispatched ->", WEBHOOK_URL[:40])
    except Exception as e:
        print("⚠️ webhook unreachable (alert still sealed locally):", type(e).__name__)

# ============ FORCE_DAY test switch ============
FORCE_DAY = (len(sys.argv) > 2 and sys.argv[2].lower() == "day")

PALETTE = [(0,255,0),(255,150,0),(0,200,255),(255,0,255),(0,255,255),
           (255,255,0),(0,165,255),(255,0,0),(150,255,180),(200,200,120)]
def id_color(tid):
    return PALETTE[tid % len(PALETTE)]

os.makedirs("data/snapshots", exist_ok=True)
os.makedirs("data/recorded_clips", exist_ok=True)

# ================= MODEL + SOURCE =================
model = YOLO("models/yolov8n.pt")
src = sys.argv[1] if len(sys.argv) > 1 else "0"
FALLBACK_CLIP = "data/test_videos/people-detection.mp4"
if not os.path.exists(FALLBACK_CLIP):
    FALLBACK_CLIP = "data/recorded_clips/demo_surveillance.mp4"

IS_LIVE = src.isdigit() or src.startswith(("http", "rtsp"))

cap = None
if src.isdigit():
    idx = int(src)
    backend = cv2.CAP_DSHOW if sys.platform.startswith("win") else cv2.CAP_ANY
    cap = cv2.VideoCapture(idx, backend)
    
    # On some Windows machines, internal webcam is index 1
    if not cap.isOpened() and idx == 0 and sys.platform.startswith("win"):
        cap = cv2.VideoCapture(1, backend)
        if cap.isOpened():
            idx = 1
            
    # Fallback to demo video if camera is blocked/unauthorized (common on macOS)
    if not cap.isOpened() and os.path.exists(FALLBACK_CLIP):
        print(f"⚠️  Live camera index {src} cannot be opened (macOS camera permissions may be restricted).")
        print(f"📹  Automatically falling back to sample border surveillance clip: {FALLBACK_CLIP}")
        src = FALLBACK_CLIP
        cap = cv2.VideoCapture(src)
        IS_LIVE = False
else:
    cap = cv2.VideoCapture(src)

if cap is None or not cap.isOpened():
    print("ERROR: cannot open source:", src)
    if src.isdigit():
        print("💡 Hint on macOS: Grant camera permission to Terminal/IDE in System Settings -> Privacy & Security -> Camera")
        print(f"   Or run with a video file: python3 code/rule.py {FALLBACK_CLIP}")
    sys.exit(1)

print("=" * 65)
print("  IBVAP - Intelligent Border Video Analytics Platform (Rules Engine)")
print("=" * 65)
print(f"Source      : {src}")
print(f"Source type : {'LIVE (clock + darkness decide night)' if IS_LIVE else 'FILE (darkness only decides night)'}")
print(f"Mode        : {'FORCE_DAY' if FORCE_DAY else 'normal'}")
print("Controls    : Click 3+ points -> 'c' arm fence | 'p' preset fence | 'r' redraw | 'q' quit")
print(">>> Fence must be ARMED before zone intrusion alerts can fire! <<<")
print("=" * 65)

# ================= STATE =================
drawing_mode, fence_points = True, []
FENCE = None                      # manual fallback polygon
ACTIVE_ZONES = []                 # web-drawn polygons (zones.json)
inside_state, dwell_start, last_alert = {}, {}, {}
tracks_state = {}
alert_count = 0
ZONES_MTIME = -1
FRS_COOLDOWN = {}
frs_matches = []                  # last FRS results (kept visible between passes)

def refresh_zones():
    """Hot-reload zones.json (web editor) — no restart needed."""
    global ZONES_MTIME, ACTIVE_ZONES, FENCE, drawing_mode
    m = zonestore.file_mtime()
    if m == ZONES_MTIME:
        return
    ZONES_MTIME = m
    zs = zonestore.load_zones()
    ACTIVE_ZONES = [np.array(z["points"], np.int32) for z in zs
                    if len(z.get("points", [])) >= 3]
    if ACTIVE_ZONES:
        FENCE = ACTIVE_ZONES[0]        # backward-compat with dwell/scoring
        drawing_mode = False
        print("🌐 ZONES hot-reloaded:", [z.get("name", "zone") for z in zs])
    elif FENCE is not None:
        FENCE = None
        print("🌐 Web zones cleared — fence disarmed")

refresh_zones()

def mouse_click(event, x, y, flags, param):
    if event == cv2.EVENT_LBUTTONDOWN and drawing_mode:
        fence_points.append((x, y))

cv2.namedWindow("IBVAP Rules")
cv2.setMouseCallback("IBVAP Rules", mouse_click)

def draw_fence_overlay(frame):
    if ACTIVE_ZONES:
        for zp in ACTIVE_ZONES:
            ov = frame.copy()
            cv2.fillPoly(ov, [zp], (0, 0, 180))
            cv2.addWeighted(ov, 0.3, frame, 0.7, 0, frame)
            cv2.polylines(frame, [zp], True, (0, 0, 255), 2)
        cv2.putText(frame, f"{len(ACTIVE_ZONES)} ZONE(S) ARMED via web editor | 'q' quit",
                    (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        return
    if FENCE is None:
        for p in fence_points:
            cv2.circle(frame, p, 5, (0, 0, 255), -1)
        if len(fence_points) > 1:
            cv2.polylines(frame, [np.array(fence_points, np.int32)], False, (0, 0, 255), 2)
        cv2.putText(frame, "fallback: click points -> 'c' | or use Web UI /editor", (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2)
        return
    ov = frame.copy()
    cv2.fillPoly(ov, [FENCE], (0, 0, 180))
    cv2.addWeighted(ov, 0.3, frame, 0.7, 0, frame)
    cv2.polylines(frame, [FENCE], True, (0, 0, 255), 2)
    cv2.putText(frame, "FENCE ARMED (manual) | 'r' clear | 'q' quit", (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

# ================= SCORING BRAIN =================
def evaluate(cls, inside, dwell_sec, speed, group_count, is_night):
    if cls in ANIMALS:
        return 0, {"animal": "suppressed"}
    b = {"base": TH["base"]}
    if is_night:                          b["night"] = TH["night"]
    if inside:                            b["zone"]  = TH["zone"]
    if inside and dwell_sec > DWELL_SEC:  b["dwell"] = TH["dwell"]
    if inside and speed < SLOW_PX:        b["slow"]  = TH["slow"]
    if inside and speed > RUN_PX:         b["run"]   = TH["run"]
    if inside and group_count >= GROUP_N: b["group"] = TH["group"]
    return sum(b.values()), b

def severity_of(score):
    if score >= SEV_CRITICAL: return "CRITICAL", (0, 0, 255)
    if score >= SEV_MEDIUM:   return "MEDIUM",   (0, 140, 255)
    if score > 0:             return "LOGGED",   (0, 255, 255)
    return "IGNORE", (180, 180, 180)

# ================= EVIDENCE SNAPSHOT =================
def save_evidence(tid, score, sev, breakdown, cx, cy, frame, x1, y1, x2, y2):
    ev = frame.copy()
    for zp in (ACTIVE_ZONES if ACTIVE_ZONES else ([FENCE] if FENCE is not None else [])):
        ov = ev.copy()
        cv2.fillPoly(ov, [zp], (0, 0, 180))
        cv2.addWeighted(ov, 0.3, ev, 0.7, 0, ev)
        cv2.polylines(ev, [zp], True, (0, 0, 255), 2)
    tr = tracks_state.get(tid, {}).get("trail", [])
    for i in range(1, len(tr)):
        cv2.line(ev, tr[i-1], tr[i], (0, 0, 255), 2)
    cv2.rectangle(ev, (x1, y1), (x2, y2), (0, 0, 255), 3)
    cv2.circle(ev, (cx, y2), 4, (0, 0, 255), -1)
    reasons = "+".join(k.upper() for k in breakdown if k != "animal")
    cv2.putText(ev, f"ALERT #{tid} | {sev} | {score}pts [{reasons}]",
                (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    cv2.putText(ev, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                (10, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
    fname = f"data/snapshots/alert_{tid}_{int(now*1000)}.jpg"
    cv2.imwrite(fname, ev)
    return fname

# ================= DUAL-PATH NIGHT ENGINE =================
_mog2 = cv2.createBackgroundSubtractorMOG2(history=300, varThreshold=40,
                                           detectShadows=False)

def enhance_low_light(frame):
    """Path 1: CLAHE on L-channel — makes dark edges visible to YOLO."""
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    l = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(l)
    return cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)

def motion_in_zones(frame):
    """Path 2: MOG2 motion differencing, gated to armed zones only."""
    polys = ACTIVE_ZONES if ACTIVE_ZONES else ([FENCE] if FENCE is not None else [])
    if not polys:
        return False
    fg = _mog2.apply(frame)
    for zp in polys:
        mask = np.zeros_like(fg)
        cv2.fillPoly(mask, [zp], 255)
        if cv2.countNonZero(cv2.bitwise_and(fg, mask)) > MOTION_PIX_THRESHOLD:
            return True
    return False

# ================= WEB API THREAD (MJPEG + zone editor :8001) =================
def _run_webapi():
    import uvicorn
    uvicorn.run(webapi.app, host="127.0.0.1", port=8001, log_level="error")
threading.Thread(target=_run_webapi, daemon=True).start()
print("🌐 Zone editor : http://127.0.0.1:8001/editor")
print("🌐 Live stream : http://127.0.0.1:8001/mjpeg")

# ================= FRS bootstrap =================
if FRS_ENABLED:
    print("👤 FRS watchlist:", list(_FACE_GALLERY.keys()))
else:
    print("👤 FRS: gallery empty — enroll with: python code/frs.py enroll \"Name\"")

# ================= MAIN LOOP =================
prev, fps, n = time.time(), 0.0, 0

while True:
    ok, frame = cap.read()
    if not ok:
        print("No more frames - exiting.")
        break
    frame = cv2.resize(frame, (640, 480))

    # ---- hot-reload web zones ----
    refresh_zones()

    # ---- context-aware night detection ----
    brightness = frame.mean()
    if FORCE_DAY:
        is_night = False
    elif IS_LIVE:
        h = datetime.datetime.now().hour
        is_night = brightness < DARK_MEAN or (h >= NIGHT_HOURS[0] or h < NIGHT_HOURS[1])
    else:
        is_night = brightness < DARK_MEAN

    # ---- PATH 1: CLAHE enhancement before inference (dark frames) ----
    clahe_active = False
    if is_night and brightness < DARK_MEAN:
        frame = enhance_low_light(frame)
        clahe_active = True

    res = model.track(frame, persist=True, tracker="bytetrack.yaml",
                      imgsz=320, verbose=False)[0]
    now = time.time()

    # ---- group count ----
    person_ids = set()
    if res.boxes is not None and res.boxes.id is not None:
        for b in res.boxes:
            if res.names[int(b.cls[0])] == "person":
                person_ids.add(int(b.id[0]))
    group_count = len(person_ids)

    # ---- FRS: detect + match (throttled ~every 1s) ----
    if FRS_ENABLED and n % 15 == 0:
        try:
            fboxes = frslib.detect_faces(frame)
            frs_matches = frslib.match_faces(frame, fboxes, _FACE_GALLERY)
        except Exception as e:
            print("⚠️ FRS error (continuing):", type(e).__name__)

    if res.boxes is not None and res.boxes.id is not None:
        for b in res.boxes:
            tid  = int(b.id[0])
            cls  = res.names[int(b.cls[0])]
            conf = float(b.conf[0])
            x1, y1, x2, y2 = map(int, b.xyxy[0])
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2

            # ---- register track ----
            st = tracks_state.setdefault(tid, {"lp": (cx, cy, now), "v": 0.0,
                                               "trail": [], "born": now})

            # ---- speed (smoothed) ----
            lx, ly, lt = st["lp"]
            inst = (((cx - lx) ** 2 + (cy - ly) ** 2) ** 0.5) / max(now - lt, 1e-3)
            st["v"] = 0.7 * st["v"] + 0.3 * inst
            st["lp"] = (cx, cy, now)

            # ---- AGE ----
            age = now - st["born"]

            # ---- TRAIL ----
            st["trail"].append((cx, cy))
            if len(st["trail"]) > TRAIL_LEN:
                st["trail"].pop(0)
            color = id_color(tid)
            tr = st["trail"]
            for i in range(1, len(tr)):
                cv2.line(frame, tr[i-1], tr[i], color, 2)

            # ---- zone test (web zones first, then manual fence) ----
            inside = False
            for zp in ACTIVE_ZONES:
                if cv2.pointPolygonTest(zp, (cx, cy), False) >= 0:
                    inside = True
                    break
            if not inside and FENCE is not None:
                inside = cv2.pointPolygonTest(FENCE, (cx, cy), False) >= 0

            if inside and not inside_state.get(tid, False):
                dwell_start[tid] = now
            dwell = now - dwell_start.get(tid, now) if inside else 0.0
            inside_state[tid] = inside

            # ---- SCORE ----
            score, breakdown = evaluate(cls, inside, dwell, st["v"],
                                        group_count, is_night)
            sev, sev_color = severity_of(score)

            # ---- DRAW BOX + LABELS ----
            box_color = sev_color if sev in ("CRITICAL", "MEDIUM") else color
            cv2.rectangle(frame, (x1, y1), (x2, y2), box_color, 3 if inside else 2)
            reasons = "+".join(k.upper() for k in breakdown if k != "animal")
            if cls in ANIMALS:
                line1 = f"#{tid} {cls} - IGNORED"
            elif sev == "IGNORE":
                line1 = f"#{tid} person {score}pts"
            else:
                line1 = f"#{tid} {sev} {score}pts [{reasons}]"
            line2 = f"age {age:.0f}s | v={st['v']:.0f} | conf {conf:.0%}"
            if inside:
                line2 += f" | dwell {dwell:.0f}s"
            cv2.putText(frame, line1, (x1, y1 - 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, box_color, 2)
            cv2.putText(frame, line2, (x1, y1 - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42, color, 1)

            # ---- ALERT DISPATCH (two-tier cooldown + ledger + webhook) ----
            if (sev in ("CRITICAL", "MEDIUM")
                    and now - last_alert.get(tid, 0) > ALERT_COOLDOWN
                    and now - last_alert.get("GLOBAL", 0) > GLOBAL_COOLDOWN):
                last_alert[tid] = now
                last_alert["GLOBAL"] = now
                alert_count += 1
                snap = save_evidence(tid, score, sev, breakdown, cx, cy,
                                     frame, x1, y1, x2, y2)
                snap_seal = file_sha256(snap)
                rec = {"time": datetime.datetime.now().isoformat(timespec="seconds"),
                       "event": "SUSPICION_ALERT", "track_id": tid,
                       "score": score, "severity": sev,
                       "breakdown": breakdown,
                       "age_sec": round(age, 1), "speed_px_s": round(st["v"], 1),
                       "location": [int(cx), int(cy)], "snapshot": snap,
                       "snapshot_sha256": snap_seal}
                sealed = append_event(rec)          # 🔐 ledger
                dispatch_webhook(rec)               # 📡 C2
                print("🚨", sev, "| score", score, "|", breakdown)
                print("🔐 sealed | head:", sealed["hash"][:16])
                print("\a", end="")

    # ---- PATH 2: MOG2 motion anomaly in zones (works when YOLO sees nothing) ----
    if is_night and now - last_alert.get("GLOBAL", 0) > GLOBAL_COOLDOWN:
        if motion_in_zones(frame):
            last_alert["GLOBAL"] = now
            alert_count += 1
            fname = f"data/snapshots/motion_anomaly_{int(now*1000)}.jpg"
            cv2.imwrite(fname, frame)
            rec = {"time": datetime.datetime.now().isoformat(timespec="seconds"),
                   "event": "MOTION_ANOMALY_NIGHT",
                   "severity": "MEDIUM", "score": 45,
                   "breakdown": {"base": 10, "night": 25, "zone": 35, "mog2_motion": 0},
                   "snapshot": fname, "snapshot_sha256": file_sha256(fname)}
            sealed = append_event(rec)              # 🔐 sealed
            dispatch_webhook(rec)                   # 📡 pushed to C2
            print("🌙 MOG2 anomaly in zone | sealed:", sealed["hash"][:12])

    # ---- FRS watchlist alerts (independent of zones) ----
    for (fbx, fby, fbw, fbh), name, score in frs_matches:
        if name and now - FRS_COOLDOWN.get(name, 0) > ALERT_COOLDOWN:
            FRS_COOLDOWN[name] = now
            cv2.rectangle(frame, (fbx, fby), (fbx + fbw, fby + fbh), (255, 0, 255), 3)
            cv2.putText(frame, f"WATCHLIST: {name} {score:.2f}", (fbx, max(20, fby - 10)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 255), 2)
            fname = f"data/snapshots/frs_{name}_{int(now*1000)}.jpg"
            cv2.imwrite(fname, frame)
            rec = {"time": datetime.datetime.now().isoformat(timespec="seconds"),
                   "event": "WATCHLIST_FACE_MATCH", "identity": name,
                   "match_score": round(score, 3),
                   "severity": "CRITICAL", "score": 100,
                   "breakdown": {"watchlist_face": 100},
                   "location": [fbx, fby], "snapshot": fname,
                   "snapshot_sha256": file_sha256(fname)}
            sealed = append_event(rec)              # 🔐 sealed
            dispatch_webhook(rec)                   # 📡 C2
            print("🚨 FRS WATCHLIST MATCH:", name, "|", round(score, 3),
                  "| sealed:", sealed["hash"][:12])
            print("\a", end="")
        elif name:
            cv2.rectangle(frame, (fbx, fby), (fbx + fbw, fby + fbh), (255, 0, 255), 2)
            cv2.putText(frame, f"{name} {score:.2f}", (fbx, max(16, fby - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 0, 255), 2)

    # ---- cleanup dead tracks ----
    if n % 300 == 0:
        dead = [t for t, s in tracks_state.items() if now - s["lp"][2] > 10]
        for t in dead:
            tracks_state.pop(t, None)
            inside_state.pop(t, None)
            dwell_start.pop(t, None)
            last_alert.pop(t, None)

    draw_fence_overlay(frame)

    # ---- feed MJPEG (browser live stream) ----
    webapi.set_frame(frame)

    # ---- HUD ----
    n += 1
    if n % 10 == 0:
        t2 = time.time()
        fps = 10 / (t2 - prev) if t2 > prev else 0.0
        prev = t2
    night_txt = ("NIGHT+CLAHE" if clahe_active else "NIGHT") if is_night else "DAY"
    cv2.putText(frame, f"FPS {fps:.1f} | {night_txt} | persons {group_count} | alerts {alert_count} | tracks {len(tracks_state)}",
                (10, 465), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)

    cv2.imshow("IBVAP Rules", frame)
    key = cv2.waitKey(1) & 0xFF
    if key == ord('q'):
        break
    elif key == ord('c') and drawing_mode and len(fence_points) >= 3:
        zs = zonestore.load_zones()
        zs.append({"name": f"Manual-{datetime.datetime.now().strftime('%H%M%S')}",
                   "type": "restricted",
                   "points": [list(p) for p in fence_points]})
        zonestore.save_zones(zs)          # persistent — survives restarts
        fence_points.clear()
        drawing_mode = False
        ZONES_MTIME = -1                  # force immediate reload
        refresh_zones()
        print("ZONE SAVED + ARMED (persistent):", [z["name"] for z in zs])
    elif key == ord('p'):
        # Arm a preset virtual fence covering the center corridor
        zs = zonestore.load_zones()
        zs.append({"name": f"Preset-Corridor-{datetime.datetime.now().strftime('%H%M%S')}",
                   "type": "restricted",
                   "points": [[80, 160], [560, 160], [590, 430], [50, 430]]})
        zonestore.save_zones(zs)
        fence_points.clear()
        drawing_mode = False
        ZONES_MTIME = -1
        refresh_zones()
        print("ZONE ARMED (Preset Border Corridor Loaded)")
    elif key == ord('r'):
        zonestore.save_zones([])
        fence_points.clear()
        drawing_mode = True
        inside_state.clear()
        dwell_start.clear()
        ZONES_MTIME = -1
        refresh_zones()
        print("All zones cleared.")

cap.release()
cv2.destroyAllWindows()
print("rule.py v7 complete - full pipeline: perception + zones + scoring + night engine + FRS + ledger + C2.")