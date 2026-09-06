"""
IBVAP - Day 5 v6: FULL MERGE + LEDGER + SMART NIGHT LOGIC
Day 2: persistent IDs, trails, age, speed display, per-ID colors
Day 3: click-drawn virtual fence, intrusion detection
Day 4: suspicion scoring engine, severity, annotated evidence snapshots
Day 5: every alert + snapshot SHA-256 sealed into the hash-chain ledger
v5 fixes: calibrated night threshold | FORCE_DAY switch | two-tier cooldown | path anchoring
v6 fix:  context-aware night - live sources use clock+darkness, file sources use
         frame darkness ONLY (a day video played at 1 AM scores as DAY)

Controls: click fence points -> 'c' arm | 'r' redraw | 'q' quit
Usage:
  python code/rule.py 0                                  <- live webcam (clock+darkness night logic)
  python code/rule.py data/recorded_clips/test.mp4       <- video file (darkness-only night logic)
  python code/rule.py <source> day                       <- force daytime scoring (test switch)
"""
import os, sys

# ====== path anchoring: always run from project root ======
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time, json, datetime, cv2
import numpy as np
from ultralytics import YOLO

# ====== ledger integration (ledger.py sits in the same folder) ======
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ledger import append_event, file_sha256

# ================= TUNING CONFIG =================
TH = {"base": 10, "night": 25, "zone": 35, "slow": 15,      # rebalanced: night alone can never alert
      "dwell": 15, "group": 10, "run": 10}

SLOW_PX, RUN_PX = 25.0, 350.0
DWELL_SEC       = 8.0
GROUP_N         = 2
DARK_MEAN       = 35.0            # frame brightness below this = dark (file & live)
NIGHT_HOURS     = (22, 5)         # clock hours (LIVE sources only!)
SEV_CRITICAL, SEV_MEDIUM = 70, 40
ALERT_COOLDOWN  = 8.0             # per-track cooldown (seconds)
GLOBAL_COOLDOWN = 3.0             # system-wide rate limit (seconds)
TRAIL_LEN       = 40

ANIMALS = {"cat","dog","cow","horse","sheep","bird","elephant","bear","zebra"}

# test switch: add "day" as second CLI argument
FORCE_DAY = (len(sys.argv) > 2 and sys.argv[2].lower() == "day")

PALETTE = [(0,255,0),(255,150,0),(0,200,255),(255,0,255),(0,255,255),
           (255,255,0),(0,165,255),(255,0,0),(150,255,180),(200,200,120)]
def id_color(tid):
    return PALETTE[tid % len(PALETTE)]

# ================= MODEL + SOURCE =================
model = YOLO("models/yolov8n.pt")
src = sys.argv[1] if len(sys.argv) > 1 else "0"
IS_LIVE = src.isdigit() or src.startswith(("http", "rtsp"))   # v6: source context

if src.isdigit():
    cap = cv2.VideoCapture(int(src) + 1, cv2.CAP_DSHOW)      # your real camera = index 1
else:
    cap = cv2.VideoCapture(src)
if not cap.isOpened():
    print("ERROR: cannot open source:", src); sys.exit(1)

print("Source opened. First detection takes 20-60s on CPU (warming up)...")
print(f"Source type : {'LIVE (clock + darkness decide night)' if IS_LIVE else 'FILE (darkness only decides night)'}")
print(f"Mode        : {'FORCE_DAY' if FORCE_DAY else 'normal'}")
print("Controls    : click points -> 'c' arm fence | 'r' redraw | 'q' quit")
print(">>> Fence must be ARMED ('c') before zone alerts can fire! <<<")

# ================= STATE =================
drawing_mode, fence_points, FENCE = True, [], None
inside_state, dwell_start, last_alert = {}, {}, {}
tracks_state = {}
alert_count = 0

def mouse_click(event, x, y, flags, param):
    if event == cv2.EVENT_LBUTTONDOWN and drawing_mode:
        fence_points.append((x, y))

cv2.namedWindow("IBVAP Rules")
cv2.setMouseCallback("IBVAP Rules", mouse_click)

def draw_fence_overlay(frame):
    global FENCE
    if FENCE is None:
        for p in fence_points:
            cv2.circle(frame, p, 5, (0, 0, 255), -1)
        if len(fence_points) > 1:
            cv2.polylines(frame, [np.array(fence_points, np.int32)], False, (0, 0, 255), 2)
        cv2.putText(frame, "CLICK points -> 'c' arm fence | 'q' quit", (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        return
    ov = frame.copy()
    cv2.fillPoly(ov, [FENCE], (0, 0, 180))
    cv2.addWeighted(ov, 0.3, frame, 0.7, 0, frame)
    cv2.polylines(frame, [FENCE], True, (0, 0, 255), 2)
    cv2.putText(frame, "FENCE ARMED | 'r' redraw | 'q' quit", (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

# ================= SCORING BRAIN =================
def evaluate(cls, inside, dwell_sec, speed, group_count, is_night):
    """Explainable scoring. Animals are fully suppressed."""
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
    if FENCE is not None:
        ov = ev.copy()
        cv2.fillPoly(ov, [FENCE], (0, 0, 180))
        cv2.addWeighted(ov, 0.3, ev, 0.7, 0, ev)
        cv2.polylines(ev, [FENCE], True, (0, 0, 255), 2)
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

# ================= MAIN LOOP =================
prev, fps, n = time.time(), 0.0, 0

while True:
    ok, frame = cap.read()
    if not ok:
        print("No more frames - exiting.")
        break
    frame = cv2.resize(frame, (640, 480))

    # ====== v6: CONTEXT-AWARE NIGHT DETECTION ======
    brightness = frame.mean()
    if FORCE_DAY:
        is_night = False                      # explicit test override
    elif IS_LIVE:
        # LIVE source: the real clock matters (border time) + darkness
        h = datetime.datetime.now().hour
        is_night = brightness < DARK_MEAN or (h >= NIGHT_HOURS[0] or h < NIGHT_HOURS[1])
    else:
        # FILE source: wall clock is meaningless — the video's own content decides
        is_night = brightness < DARK_MEAN

    res = model.track(frame, persist=True, tracker="bytetrack.yaml",
                      imgsz=320, verbose=False)[0]
    now = time.time()

    # group count = distinct person tracks visible right now
    person_ids = set()
    if res.boxes is not None and res.boxes.id is not None:
        for b in res.boxes:
            if res.names[int(b.cls[0])] == "person":
                person_ids.add(int(b.id[0]))
    group_count = len(person_ids)

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

            # ---- zone state + dwell ----
            inside = FENCE is not None and cv2.pointPolygonTest(FENCE, (cx, cy), False) >= 0
            if inside and not inside_state.get(tid, False):
                dwell_start[tid] = now
            dwell = now - dwell_start.get(tid, now) if inside else 0.0
            inside_state[tid] = inside

            # ---- SCORE ----
            score, breakdown = evaluate(cls, inside, dwell, st["v"],
                                        group_count, is_night)
            sev, sev_color = severity_of(score)

            # ---- DRAW BOX + LABELS (alert color wins over ID color) ----
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

            # ====== ALERT DISPATCH (two-tier cooldown + ledger seal) ======
            if (sev in ("CRITICAL", "MEDIUM")
                    and now - last_alert.get(tid, 0) > ALERT_COOLDOWN            # per-track 8s
                    and now - last_alert.get("GLOBAL", 0) > GLOBAL_COOLDOWN):    # system-wide 3s
                last_alert[tid] = now
                last_alert["GLOBAL"] = now
                alert_count += 1
                snap = save_evidence(tid, score, sev, breakdown, cx, cy,
                                     frame, x1, y1, x2, y2)
                snap_seal = file_sha256(snap)        # 🔐 SHA-256 of snapshot bytes
                rec = {"time": datetime.datetime.now().isoformat(timespec="seconds"),
                       "event": "SUSPICION_ALERT", "track_id": tid,
                       "score": score, "severity": sev,
                       "breakdown": breakdown,
                       "age_sec": round(age, 1), "speed_px_s": round(st["v"], 1),
                       "location": [int(cx), int(cy)], "snapshot": snap,
                       "snapshot_sha256": snap_seal}
                sealed = append_event(rec)           # 🔐 ONTO THE TAMPER-PROOF CHAIN
                with open("data/alerts_log.jsonl", "a") as f:
                    f.write(json.dumps(rec) + "\n")
                print("🚨", sev, "| score", score, "|", breakdown)
                print("🔐 sealed | head:", sealed["hash"][:16])
                print("\a", end="")

    # ---- cleanup dead tracks ----
    if n % 300 == 0:
        dead = [t for t, s in tracks_state.items() if now - s["lp"][2] > 10]
        for t in dead:
            tracks_state.pop(t, None)
            inside_state.pop(t, None)
            dwell_start.pop(t, None)
            last_alert.pop(t, None)

    draw_fence_overlay(frame)

    # ---- HUD ----
    n += 1
    if n % 10 == 0:
        t2 = time.time()
        fps = 10 / (t2 - prev) if t2 > prev else 0.0
        prev = t2
    night_txt = "NIGHT" if is_night else "DAY"
    cv2.putText(frame, f"FPS {fps:.1f} | {night_txt} | persons {group_count} | alerts {alert_count} | tracks {len(tracks_state)}",
                (10, 465), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)

    cv2.imshow("IBVAP Rules", frame)
    key = cv2.waitKey(1) & 0xFF
    if key == ord('q'):
        break
    elif key == ord('c') and drawing_mode and len(fence_points) >= 3:
        FENCE = np.array(fence_points, np.int32)
        drawing_mode = False
        print("FENCE ARMED:", fence_points)
    elif key == ord('r'):
        FENCE, drawing_mode = None, True
        fence_points.clear()
        inside_state.clear()
        dwell_start.clear()

cap.release()
cv2.destroyAllWindows()
print("Day 5 v6 complete - context-aware night + tamper-evident ledger.")