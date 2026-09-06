"""
IBVAP — A4: Dual-Path Night Vision & Detection Engine (Member A / Perception)
Path 1: CLAHE Low-Light Enhancement -> Feeds high-contrast frame to YOLOv8
Path 2: Denoised MOG2 Motion Gating -> Fallback alarm when confidence drops in pitch black

Run from project root:  python3 code/night.py
Run from code/ folder:  python3 night.py
Controls:
  'n' -> Toggle Force Night Mode ON/OFF
  's' -> Toggle Dark Scene Simulation (demonstrate night detection on day video)
  'm' -> Toggle MOG2 Motion Fallback boxes
  'd' -> Toggle Side-by-Side comparison view
  'q' -> Quit
"""

import os
import sys
import time
import cv2
import numpy as np

# Ensure project root is accessible for model loading
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.normpath(os.path.join(BASE_DIR, ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

try:
    from ultralytics import YOLO
    HAS_YOLO = True
except ImportError:
    HAS_YOLO = False

NIGHT_ON = 60.0       # Brightness below this -> Night mode ON
NIGHT_OFF = 75.0      # Brightness above this -> Night mode OFF (hysteresis)
MIN_AREA_FRAC = 0.0015  # Minimum contour area fraction for motion blobs

# Target classes for border surveillance
TARGET_CLASSES = {0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}


class NightEngine:
    """Per-camera Dual-Path Night Perception Engine."""

    def __init__(self, cam_id=0, model_path=None, yolo_conf=0.25):
        self.cam_id = cam_id
        self.yolo_conf = yolo_conf

        # Path 1: CLAHE setup (L-channel enhancement)
        self.clahe = cv2.createCLAHE(clipLimit=3.5, tileGridSize=(8, 8))

        # Path 2: MOG2 background subtractor (with noise suppression)
        self.mog2 = cv2.createBackgroundSubtractorMOG2(
            history=300, varThreshold=30, detectShadows=False
        )
        self.morph_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

        self.night = False
        self.brightness = 255.0

        # Load YOLO model
        self.model = None
        if HAS_YOLO:
            candidates = [
                model_path,
                os.path.join(ROOT_DIR, "models", "yolov8n.pt"),
                os.path.join(BASE_DIR, "..", "models", "yolov8n.pt"),
                "yolov8n.pt",
            ]
            for p in candidates:
                if p and os.path.exists(p):
                    try:
                        self.model = YOLO(p)
                        break
                    except Exception:
                        pass
            if self.model is None:
                try:
                    self.model = YOLO("yolov8n.pt")
                except Exception:
                    self.model = None

    def enhance(self, frame):
        """CLAHE on L-channel (LAB) — boosts low-light contrast without chrominance distortion."""
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        l_enhanced = self.clahe.apply(l)
        enhanced = cv2.cvtColor(cv2.merge((l_enhanced, a, b)), cv2.COLOR_LAB2BGR)
        return enhanced

    def motion_boxes(self, frame):
        """MOG2 motion detection with Gaussian pre-blur to suppress low-light ISO sensor grain."""
        blurred = cv2.GaussianBlur(frame, (5, 5), 0)
        fg = self.mog2.apply(blurred)
        fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, self.morph_kernel, iterations=1)
        fg = cv2.dilate(fg, self.morph_kernel, iterations=2)
        cnts, _ = cv2.findContours(fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        h, w = frame.shape[:2]
        min_area = MIN_AREA_FRAC * h * w
        boxes = []
        for c in cnts:
            if cv2.contourArea(c) < min_area:
                continue
            x, y, bw, bh = cv2.boundingRect(c)
            boxes.append([int(x), int(y), int(x + bw), int(y + bh)])
        return boxes

    def detect_yolo(self, frame):
        """Run YOLO inference on enhanced frame for human & vehicle classes."""
        detections = []
        if self.model is None:
            return detections

        try:
            results = self.model(frame, conf=self.yolo_conf, verbose=False)[0]
            for box in results.boxes:
                cls_id = int(box.cls[0])
                if cls_id in TARGET_CLASSES:
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    conf = float(box.conf[0])
                    detections.append({
                        "box": [x1, y1, x2, y2],
                        "cls": TARGET_CLASSES[cls_id],
                        "conf": round(conf, 2)
                    })
        except Exception:
            pass

        return detections

    def process(self, frame, force_night=False, simulate_dark=False, show_motion=True):
        """Full frame pipeline: Brightness check -> CLAHE enhance -> YOLO -> MOG2 -> Annotated output."""
        work_frame = frame.copy()

        # Optional: Dark scene simulation (useful to test night enhancement on daylight test clips)
        if simulate_dark:
            work_frame = np.clip(work_frame.astype(np.float32) * 0.25, 0, 255).astype(np.uint8)

        # 1. Brightness Calculation & Hysteresis Gate
        gray = cv2.cvtColor(work_frame, cv2.COLOR_BGR2GRAY)
        self.brightness = float(gray.mean())

        if force_night:
            self.night = True
        else:
            if self.night:
                if self.brightness > NIGHT_OFF:
                    self.night = False
            elif self.brightness < NIGHT_ON:
                self.night = True

        # 2. Path 1: CLAHE Enhancement (when in night mode)
        if self.night:
            enhanced = self.enhance(work_frame)
        else:
            enhanced = work_frame.copy()

        # 3. Path 1: YOLO Object Detection on Enhanced Frame
        detections = self.detect_yolo(enhanced)

        # 4. Path 2: MOG2 Motion Fallback
        motion = self.motion_boxes(work_frame) if show_motion else []

        # 5. Build Annotated Visual Output
        annotated = enhanced.copy()

        # Draw MOG2 Motion Fallback Bounding Boxes (Yellow/Orange)
        if show_motion:
            for x1, y1, x2, y2 in motion:
                cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 165, 255), 1)
                cv2.putText(annotated, "MOTION", (x1, max(15, y1 - 4)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 165, 255), 1)

        # Draw YOLO Object Detections (Green for Person, Cyan for Vehicles)
        for det in detections:
            x1, y1, x2, y2 = det["box"]
            is_person = (det["cls"] == "person")
            color = (0, 255, 0) if is_person else (255, 255, 0)
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
            label = f"{det['cls'].upper()} {int(det['conf']*100)}%"
            cv2.putText(annotated, label, (x1, max(20, y1 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

        return {
            "night": self.night,
            "brightness": round(self.brightness, 1),
            "raw": work_frame,
            "enhanced": enhanced,
            "detections": detections,
            "motion": motion,
            "annotated": annotated
        }


# ---------------------------------------------------------------
# STANDALONE TEST HARNESS
# ---------------------------------------------------------------
if __name__ == "__main__":
    NIGHT_CLIP = os.path.normpath(os.path.join(ROOT_DIR, "data", "test_videos", "night-surveillance.mp4"))
    PEOPLE_CLIP = os.path.normpath(os.path.join(ROOT_DIR, "data", "test_videos", "people-detection.mp4"))

    # Argument resolution: Default is LIVE WEBCAM (0)
    if len(sys.argv) > 1:
        raw_src = sys.argv[1].strip()
        if raw_src.isdigit():
            src = int(raw_src)
        elif raw_src.lower() in ("webcam", "cam", "live"):
            src = 0
        elif raw_src.lower() in ("night", "sample", "night-surveillance"):
            src = NIGHT_CLIP
        elif os.path.exists(raw_src):
            src = os.path.abspath(raw_src)
        elif os.path.exists(os.path.join(ROOT_DIR, raw_src)):
            src = os.path.normpath(os.path.join(ROOT_DIR, raw_src))
        else:
            src = os.path.abspath(raw_src)
    else:
        # Default: LIVE WEBCAM (Index 0)
        src = 0

    is_file = isinstance(src, str) and os.path.isfile(src)
    backend = cv2.CAP_ANY if is_file else (
        cv2.CAP_AVFOUNDATION if sys.platform == "darwin" else
        (cv2.CAP_V4L2 if sys.platform.startswith("linux") else cv2.CAP_DSHOW)
    )

    cap = cv2.VideoCapture(src, backend)
    if not cap.isOpened() and is_file:
        cap = cv2.VideoCapture(src)
    elif not cap.isOpened() and not is_file:
        cap = cv2.VideoCapture(src)

    if not cap.isOpened() and not is_file:
        fallback = NIGHT_CLIP if os.path.exists(NIGHT_CLIP) else PEOPLE_CLIP
        print(f"⚠️  Live webcam ({src}) not accessible (check macOS camera permissions in System Settings).")
        print(f"📹  Falling back to sample video: {fallback}")
        src = fallback
        is_file = True
        cap = cv2.VideoCapture(src)

    if not cap.isOpened():
        print(f"❌ ERROR: Cannot open video source: {src}")
        sys.exit(1)

    native_fps = cap.get(cv2.CAP_PROP_FPS)
    target_fps = native_fps if (native_fps and 1.0 <= native_fps <= 120.0) else 25.0
    frame_delay = 1.0 / target_fps

    engine = NightEngine(cam_id=0)

    # Interactive state
    force_night = False
    simulate_dark = False
    show_motion = True
    split_view = True

    print("=" * 68)
    print("  IBVAP — Dual-Path Night Vision & Detection Engine")
    print("=" * 68)
    source_label = "LIVE WEBCAM (0)" if src == 0 else str(src)
    print(f"Source       : {source_label}")
    if is_file:
        print(f"Playback     : Video file @ {target_fps:.1f} FPS (Paced loop)")
    else:
        print(f"Playback     : Real-time Live Camera Stream")
    print(f"YOLO Model   : {'Loaded ✅ (' + str(engine.model.model_name) + ')' if engine.model else 'Not found ⚠️'}")
    print("-" * 68)
    print("Controls:")
    print("  'n' -> Toggle Force Night Mode ON/OFF")
    print("  's' -> Toggle Dark Scene Simulation (test night on day clip)")
    print("  'm' -> Toggle MOG2 Motion Bounding Boxes")
    print("  'd' -> Toggle Side-by-Side Dual View vs Single View")
    print("  'q' -> Exit")
    print("=" * 68)

    try:
        while True:
            t_start = time.time()
            ok, frame = cap.read()
            if not ok:
                if is_file:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                else:
                    break

            res = engine.process(
                frame,
                force_night=force_night,
                simulate_dark=simulate_dark,
                show_motion=show_motion
            )

            raw = res["raw"]
            annotated = res["annotated"]

            # Overlay telemetry on raw frame
            status_tag = "🌙 NIGHT MODE" if res["night"] else "☀️ DAY MODE"
            sim_tag = " [SIMULATED DARK]" if simulate_dark else ""
            status_color = (0, 0, 255) if res["night"] else (0, 255, 0)

            cv2.putText(raw, f"RAW FEED | {status_tag}{sim_tag}", (15, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, status_color, 2)
            cv2.putText(raw, f"Brightness: {res['brightness']} (Threshold: {NIGHT_ON})", (15, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1)

            # Overlay telemetry on enhanced frame
            enh_tag = "CLAHE ENHANCED + YOLO" if res["night"] else "STANDARD YOLO"
            cv2.putText(annotated, f"IBVAP NIGHT ENGINE | {enh_tag}", (15, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2)
            cv2.putText(annotated,
                        f"Objects: {len(res['detections'])} | Motion Blobs: {len(res['motion'])}",
                        (15, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1)

            if split_view:
                # Resize if needed to match height
                h = min(raw.shape[0], annotated.shape[0])
                w_raw = int(raw.shape[1] * (h / raw.shape[0]))
                w_ann = int(annotated.shape[1] * (h / annotated.shape[0]))
                raw_resized = cv2.resize(raw, (w_raw, h))
                ann_resized = cv2.resize(annotated, (w_ann, h))
                display_frame = np.hstack([raw_resized, ann_resized])
            else:
                display_frame = annotated

            cv2.imshow("IBVAP - Dual-Path Night Vision Engine ('q' to exit)", display_frame)

            # Frame pacing for video files
            if is_file:
                elapsed = time.time() - t_start
                delay = frame_delay - elapsed
                if delay > 0:
                    time.sleep(delay)

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            elif key == ord('n'):
                force_night = not force_night
                print(f"👉 Force Night Mode: {'ON 🌙' if force_night else 'AUTO (Sensor Gate)'}")
            elif key == ord('s'):
                simulate_dark = not simulate_dark
                print(f"👉 Dark Scene Simulation: {'ON (Darkened 75%)' if simulate_dark else 'OFF (Natural Light)'}")
            elif key == ord('m'):
                show_motion = not show_motion
                print(f"👉 MOG2 Motion Fallback: {'ENABLED' if show_motion else 'DISABLED'}")
            elif key == ord('d'):
                split_view = not split_view
                print(f"👉 Display Mode: {'SIDE-BY-SIDE DUAL VIEW' if split_view else 'ENHANCED ONLY'}")

    finally:
        cap.release()
        cv2.destroyAllWindows()