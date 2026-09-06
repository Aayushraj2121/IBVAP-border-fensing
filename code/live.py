"""
IBVAP - Day 1: Live Person Detection
Sources: 0 = webcam | video file path | phone IP-Webcam URL
Press 'q' on the video window to quit.
"""
import sys, time, cv2
from ultralytics import YOLO

# ----------------- MODEL -----------------
model = YOLO("models/yolov8n.pt")

# ----------------- SOURCE -----------------
# Camera index from command line (default 0).
# NOTE: on this laptop the REAL camera is index 1 (index 0 is the IR camera),
# so we add +1 when a number is given. Files/URLs pass through unchanged.
src = sys.argv[1] if len(sys.argv) > 1 else "0"

if src.isdigit():
    cap = cv2.VideoCapture(int(src) + 1, cv2.CAP_DSHOW)   # DSHOW backend fix
else:
    cap = cv2.VideoCapture(src)                            # file or phone URL

if not cap.isOpened():
    print("ERROR: cannot open source:", src)
    sys.exit(1)

print("Source opened. FIRST detection takes 20-60s on CPU (warming up)...")
print(">>> DO NOT press Ctrl+C. Wait for the window! <<<")

# ----------------- MAIN LOOP -----------------
prev, fps, n = time.time(), 0.0, 0

while True:
    ok, frame = cap.read()
    if not ok:
        print("No more frames - exiting.")
        break

    frame = cv2.resize(frame, (640, 480))            # speed: smaller frame
    res = model(frame, verbose=False, imgsz=320)[0]  # speed: small inference size

    # draw every detection (person, car, dog, cow, ...)
    for b in res.boxes:
        cls = res.names[int(b.cls[0])]
        conf = float(b.conf[0])
        x1, y1, x2, y2 = map(int, b.xyxy[0])
        color = (0, 255, 0) if cls == "person" else (0, 150, 255)  # green=person, orange=other
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cv2.putText(frame, f"{cls} {conf:.0%}", (x1, y1 - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

    # FPS counter (updates every 10 frames)
    n += 1
    if n % 10 == 0:
        now = time.time()
        fps = 10 / (now - prev) if now > prev else 0.0
        prev = now
    cv2.putText(frame, f"FPS: {fps:.1f}", (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

    cv2.imshow("IBVAP - press q to quit", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
print("Day 1 complete - IBVAP signing off.")