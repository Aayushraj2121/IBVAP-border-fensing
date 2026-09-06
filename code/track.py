"""
IBVAP - Day 2: Detection + Tracking (persistent IDs + trails + speed + age)
Sources: 0 = webcam (auto-maps to real camera index 1) | file | phone URL
Press 'q' on the video window to quit.
"""
import sys, time, cv2
from ultralytics import YOLO

# ----------------- MODEL -----------------
model = YOLO("models/yolov8n.pt")

# ----------------- SOURCE (same door as Day 1) -----------------
src = sys.argv[1] if len(sys.argv) > 1 else "0"
FALLBACK_CLIP = "data/recorded_clips/demo_surveillance.mp4"

cap = None
if src.isdigit():
    idx = int(src)
    backend = cv2.CAP_DSHOW if sys.platform.startswith("win") else cv2.CAP_ANY
    cap = cv2.VideoCapture(idx, backend)
    if not cap.isOpened() and idx == 0 and sys.platform.startswith("win"):
        cap = cv2.VideoCapture(1, backend)
    if not cap.isOpened() and os.path.exists(FALLBACK_CLIP):
        print(f"⚠️  Camera index {src} not accessible (macOS permissions or unavailable).")
        print(f"📹  Automatically falling back to sample video: {FALLBACK_CLIP}")
        src = FALLBACK_CLIP
        cap = cv2.VideoCapture(src)
else:
    cap = cv2.VideoCapture(src)

if cap is None or not cap.isOpened():
    print("ERROR: cannot open source:", src)
    sys.exit(1)

print("Source opened. First detection takes 20-60s on CPU (warming up)...")

# ----------------- TRACKING STATE -----------------
trails      = {}   # tid -> [(x, y), ...]  path history
first_seen  = {}   # tid -> timestamp     (for AGE)
last_pos    = {}   # tid -> (x, y, time)  (for SPEED)
speeds      = {}   # tid -> smoothed px/sec

PALETTE = [(0,255,0),(255,150,0),(0,200,255),(255,0,255),(0,255,255),
           (255,255,0),(0,165,255),(255,0,0),(150,255,180),(200,200,120)]

def id_color(tid):
    return PALETTE[tid % len(PALETTE)]

prev, fps, n = time.time(), 0.0, 0

# ----------------- MAIN LOOP -----------------
while True:
    ok, frame = cap.read()
    if not ok:
        print("No more frames - exiting.")
        break
    frame = cv2.resize(frame, (640, 480))

    # THE Day-2 change: .track() with persist=True  (ByteTrack built-in)
    res = model.track(frame, persist=True, tracker="bytetrack.yaml",
                      imgsz=320, verbose=False)[0]

    now = time.time()

    if res.boxes is not None and res.boxes.id is not None:
        for b in res.boxes:
            tid  = int(b.id[0])
            cls  = res.names[int(b.cls[0])]
            conf = float(b.conf[0])
            x1, y1, x2, y2 = map(int, b.xyxy[0])
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2

            # ---- new track? register it ----
            if tid not in first_seen:
                first_seen[tid] = now
                trails[tid] = []
                last_pos[tid] = (cx, cy, now)
                speeds[tid] = 0.0

            # ---- AGE (loitering foundation) ----
            age = now - first_seen[tid]

            # ---- SPEED (crawling foundation) ----
            lx, ly, lt = last_pos[tid]
            dt = max(now - lt, 1e-3)
            inst_speed = (((cx - lx) ** 2 + (cy - ly) ** 2) ** 0.5) / dt
            speeds[tid] = 0.7 * speeds[tid] + 0.3 * inst_speed   # smoothing
            last_pos[tid] = (cx, cy, now)

            # ---- TRAIL (movement path) ----
            trails[tid].append((cx, cy))
            if len(trails[tid]) > 40:
                trails[tid].pop(0)

            # ---- DRAW ----
            color = id_color(tid)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            if cls == "person":
                label = f"#{tid} {conf:.0%} | age {age:.0f}s | v={speeds[tid]:.0f}"
            else:
                label = f"#{tid} {cls} {conf:.0%}"
            cv2.putText(frame, label, (x1, y1 - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

            pts = trails[tid]
            for i in range(1, len(pts)):
                cv2.line(frame, pts[i - 1], pts[i], color, 2)

    # ---- cleanup: forget tracks not seen for 10s (memory hygiene) ----
    if n % 100 == 0:
        lost = [tid for tid, p in last_pos.items() if now - p[2] > 10]
        for tid in lost:
            trails.pop(tid, None); first_seen.pop(tid, None)
            last_pos.pop(tid, None); speeds.pop(tid, None)

    # ---- HUD ----
    n += 1
    if n % 10 == 0:
        now2 = time.time()
        fps = 10 / (now2 - prev) if now2 > prev else 0.0
        prev = now2
    cv2.putText(frame, f"FPS: {fps:.1f} | Active tracks: {len(trails)}", (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

    cv2.imshow("IBVAP Day2 Tracking - press q to quit", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
print("Day 2 complete - IBVAP signing off.")