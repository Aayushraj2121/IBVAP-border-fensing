"""
IBVAP - Day 3: Virtual Fence Intrusion Detection
- Click 4+ points on screen to draw the fence (press 'c' to close/confirm)
- Any tracked person CROSSING into the fence -> ALERT (red + beep + log)
Press 'r' to redraw fence | 'q' to quit
"""
import sys, time, json, datetime, cv2
import numpy as np
from ultralytics import YOLO

# ----------------- MODEL + SOURCE -----------------
model = YOLO("models/yolov8n.pt")

src = sys.argv[1] if len(sys.argv) > 1 else "0"
if src.isdigit():
    cap = cv2.VideoCapture(int(src) + 1, cv2.CAP_DSHOW)
else:
    cap = cv2.VideoCapture(src)

if not cap.isOpened():
    print("ERROR: cannot open source:", src)
    sys.exit(1)

# ----------------- FENCE DRAWING STATE -----------------
drawing_mode = True
fence_points = []          # clicked points
FENCE = None               # final np array
inside_state = {}          # tid -> True/False (was inside last frame?)
dwell_start = {}           # tid -> time when entered zone
alerts_log = []            # all alert records

LOG_FILE = "data/alerts_log.jsonl"

def mouse_click(event, x, y, flags, param):
    """Left-click adds a fence corner point."""
    if event == cv2.EVENT_LBUTTONDOWN and drawing_mode:
        fence_points.append((x, y))

cv2.namedWindow("IBVAP Fence")
cv2.setMouseCallback("IBVAP Fence", mouse_click)

def finalize_fence():
    """Turn clicked points into the fence polygon."""
    global FENCE, drawing_mode
    if len(fence_points) >= 3:
        FENCE = np.array(fence_points, np.int32)
        drawing_mode = False
        print(f"FENCE ACTIVE with {len(fence_points)} points:", fence_points)
    else:
        print("Need at least 3 points! Click more.")

def draw_fence_overlay(frame):
    """Red transparent zone + border line."""
    if FENCE is None:
        # still drawing: show current points + lines
        for p in fence_points:
            cv2.circle(frame, p, 5, (0, 0, 255), -1)
        if len(fence_points) > 1:
            pts = np.array(fence_points, np.int32)
            cv2.polylines(frame, [pts], False, (0, 0, 255), 2)
        cv2.putText(frame, "CLICK points -> 'c' confirm fence | 'q' quit",
                    (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        return
    overlay = frame.copy()
    cv2.fillPoly(overlay, [FENCE], (0, 0, 180))
    cv2.addWeighted(overlay, 0.3, frame, 0.7, 0, frame)
    cv2.polylines(frame, [FENCE], True, (0, 0, 255), 2)
    cv2.putText(frame, "FENCE ARMED | 'r' redraw | 'q' quit",
                (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

def beep():
    """Alarm sound without any library (Windows beep via print bell)."""
    print("\a")   # terminal bell; on most Windows setups this plays a sound

def log_alert(tid, cls, conf, severity, cx, cy):
    """Write alert to JSONL file (Day 5 will hash-chain this)."""
    rec = {
        "time": datetime.datetime.now().isoformat(timespec="seconds"),
        "event": "FENCE_INTRUSION",
        "track_id": tid,
        "class": cls,
        "confidence": round(conf, 2),
        "location": [int(cx), int(cy)],
        "severity": severity
    }
    alerts_log.append(rec)
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(rec) + "\n")
    print("🚨 ALERT:", rec)

prev, fps, n = time.time(), 0.0, 0

# ----------------- MAIN LOOP -----------------
while True:
    ok, frame = cap.read()
    if not ok:
        break
    frame = cv2.resize(frame, (640, 480))

    res = model.track(frame, persist=True, tracker="bytetrack.yaml",
                      imgsz=320, verbose=False)[0]

    now = time.time()

    if res.boxes is not None and res.boxes.id is not None and FENCE is not None:
        for b in res.boxes:
            tid  = int(b.id[0])
            cls  = res.names[int(b.cls[0])]
            conf = float(b.conf[0])
            x1, y1, x2, y2 = map(int, b.xyxy[0])
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2

            if cls != "person":        # animals/vehicles don't trip the fence (yet)
                continue

            # ---- INSIDE TEST ----
            inside = cv2.pointPolygonTest(FENCE, (cx, cy), False) >= 0
            was    = inside_state.get(tid, False)

            # ---- CROSSING DETECTED? ----
            if inside and not was:
                dwell_start[tid] = now
                # simple scoring: night adds severity (Day 5 upgrades this fully)
                hour = datetime.datetime.now().hour
                severity = "CRITICAL" if (hour >= 22 or hour < 5) else "HIGH"
                color = (0, 0, 255)
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3)
                cv2.putText(frame, f"#{tid} INTRUSION! {severity}", (x1, y1 - 25),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
                beep()
                log_alert(tid, cls, conf, severity, cx, cy)
            elif inside:
                # standing inside: show dwell
                dwell = now - dwell_start.get(tid, now)
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 3)
                cv2.putText(frame, f"#{tid} IN ZONE {dwell:.0f}s", (x1, y1 - 25),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
            else:
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(frame, f"#{tid}", (x1, y1 - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

            inside_state[tid] = inside

    # ---- cleanup lost tracks ----
    if n % 100 == 0:
        lost = [tid for tid, val in inside_state.items()]
        # (simple version: states persist; fine for demo scale)

    draw_fence_overlay(frame)

    # ---- HUD ----
    n += 1
    if n % 10 == 0:
        now2 = time.time()
        fps = 10 / (now2 - prev) if now2 > prev else 0.0
        prev = now2
    cv2.putText(frame, f"FPS: {fps:.1f} | Alerts today: {len(alerts_log)}", (10, 465),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

    cv2.imshow("IBVAP Fence", frame)
    key = cv2.waitKey(1) & 0xFF

    if key == ord('q'):
        break
    elif key == ord('c') and drawing_mode:
        finalize_fence()
    elif key == ord('r'):
        FENCE = None
        fence_points.clear()
        drawing_mode = True
        inside_state.clear()
        print("Fence cleared - redraw.")

cap.release()
cv2.destroyAllWindows()
print("Day 3 complete - alerts saved to", LOG_FILE)