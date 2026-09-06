"""
IBVAP — A5: Automatic Number Plate Recognition (ANPR) Engine (Member A / Perception)
High-Speed Plate Localization + OCR (fast-alpr / fast-plate-ocr) + Indian Plate Regex Validator
+ Suspect Vehicle Hotlist Alerts (data/hotlist.json) -> Fills contract plates[]

Run from project root:  python3 code/anpr.py [source]  (ya python3 anpr.py)
Run from code/ folder:  python3 anpr.py [source]
"""

import os
import sys
import re
import time
import json
import cv2
import numpy as np

# Resolve base paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.normpath(os.path.join(BASE_DIR, ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# ---------------- ALL 36 INDIAN STATES & UNION TERRITORIES ----------------
INDIAN_STATES = {
    "AN": "Andaman & Nicobar", "AP": "Andhra Pradesh", "AR": "Arunachal Pradesh",
    "AS": "Assam", "BR": "Bihar", "CH": "Chandigarh", "CG": "Chhattisgarh",
    "DD": "Daman & Diu", "DL": "Delhi", "DN": "Dadra & Nagar Haveli",
    "GA": "Goa", "GJ": "Gujarat", "HP": "Himachal Pradesh", "HR": "Haryana",
    "JH": "Jharkhand", "JK": "Jammu & Kashmir", "KA": "Karnataka", "KL": "Kerala",
    "LA": "Ladakh", "LD": "Lakshadweep", "MH": "Maharashtra", "ML": "Meghalaya",
    "MN": "Manipur", "MP": "Madhya Pradesh", "MZ": "Mizoram", "NL": "Nagaland",
    "OD": "Odisha", "PB": "Punjab", "PY": "Puducherry", "RJ": "Rajasthan",
    "SK": "Sikkim", "TN": "Tamil Nadu", "TR": "Tripura", "TS": "Telangana",
    "UK": "Uttarakhand", "UP": "Uttar Pradesh", "WB": "West Bengal"
}

# Regex Patterns
# Standard Indian: e.g. HR26DQ5551, DL01AB1234, UP16B1234, JK02AK9999
STD_PLATE_REGEX = re.compile(r"^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{4}$")
# Bharat Series (BH): e.g. 22BH1234AA
BH_PLATE_REGEX  = re.compile(r"^[0-9]{2}BH[0-9]{4}[A-Z]{1,2}$")

DEFAULT_HOTLIST_PATH = os.path.normpath(os.path.join(ROOT_DIR, "data", "hotlist.json"))


def clean_plate_text(text: str) -> str:
    """Normalize OCR text: strip spaces/dashes and enforce alphanumeric uppercase."""
    if not text:
        return ""
    return re.sub(r"[^A-Za-z0-9]", "", text).upper()


def validate_indian_plate(text: str) -> tuple[bool, str, str, str]:
    """Validate plate string against Indian Motor Vehicles Act standards.
    Returns: (is_valid, cleaned_text, state_code, state_name)
    """
    clean = clean_plate_text(text)
    if not clean or len(clean) < 6:
        return False, clean, "UNKNOWN", "Invalid Syntax"

    # 1. Check Standard Indian Plate (e.g. HR26DQ5551)
    if STD_PLATE_REGEX.match(clean):
        st_code = clean[:2]
        st_name = INDIAN_STATES.get(st_code, "Unknown State")
        return True, clean, st_code, st_name

    # 2. Check Bharat Series (BH)
    if BH_PLATE_REGEX.match(clean):
        return True, clean, "BH", "BH (Bharat Series)"

    # Positional heuristics for common OCR confusions (e.g. 'O' as '0' or 'I' as '1')
    # If starts with letters, followed by digits, letters, digits:
    if len(clean) >= 9 and clean[:2].isalpha() and clean[-4:].isdigit():
        st_code = clean[:2]
        if st_code in INDIAN_STATES:
            return True, clean, st_code, INDIAN_STATES[st_code]

    return False, clean, clean[:2] if len(clean) >= 2 else "UNKNOWN", "Unverified Syntax"


class ANPREngine:
    """Automatic Number Plate Recognition Engine using fast-alpr + Indian Regex."""

    def __init__(self, hotlist_path=DEFAULT_HOTLIST_PATH, conf_thresh=0.35):
        self.conf_thresh = conf_thresh
        self.hotlist_path = hotlist_path
        self.hotlist = self._load_hotlist()
        self.alpr = None

        # Initialize fast-alpr with CPUExecutionProvider for maximum cross-platform stability
        try:
            from fast_alpr import ALPR
            self.alpr = ALPR(
                detector_model="yolo-v9-t-384-license-plate-end2end",
                detector_providers=["CPUExecutionProvider"],
                detector_conf_thresh=self.conf_thresh,
                ocr_model="cct-xs-v2-global-model",
                ocr_providers=["CPUExecutionProvider"]
            )
            print("✅ ANPR Engine initialized with fast-alpr (YOLOv9-t + CCT-XS OCR ONNX)!")
        except Exception as e:
            print(f"⚠️  fast-alpr initialization warning: {e}")
            self.alpr = None

    def _load_hotlist(self) -> dict:
        """Load flagged suspect vehicle watchlist from JSON."""
        if os.path.exists(self.hotlist_path):
            try:
                with open(self.hotlist_path, "r") as f:
                    data = json.load(f)
                    # Normalize keys
                    return {clean_plate_text(k): v for k, v in data.items()}
            except Exception as e:
                print(f"⚠️  Failed to load hotlist: {e}")
        return {}

    def reload_hotlist(self):
        self.hotlist = self._load_hotlist()

    def process_frame(self, frame: np.ndarray, vehicle_boxes=None) -> list[dict]:
        """Perform plate detection and OCR on frame.
        Returns list of structured plate records ready for frozen contract.
        """
        results = []
        if frame is None or self.alpr is None:
            return results

        try:
            # Predict full frame
            predictions = self.alpr.predict(frame)
            for p in predictions:
                if not p.ocr or not p.ocr.text:
                    continue

                raw_text = p.ocr.text
                if isinstance(p.ocr.confidence, (list, tuple, np.ndarray)) and len(p.ocr.confidence) > 0:
                    conf = float(np.mean(p.ocr.confidence))
                elif p.ocr.confidence is not None:
                    try:
                        conf = float(p.ocr.confidence)
                    except (TypeError, ValueError):
                        conf = 0.0
                else:
                    conf = 0.0

                if conf < self.conf_thresh:
                    continue

                # Bounding box
                x1, y1, x2, y2 = map(int, p.detection.bounding_box.xyxy)

                # Validate Indian plate syntax
                is_valid, plate_num, st_code, st_name = validate_indian_plate(raw_text)

                # Check against border security hotlist
                is_hotlist = plate_num in self.hotlist
                hotlist_meta = self.hotlist.get(plate_num, {})

                results.append({
                    "plate": plate_num,
                    "raw_text": raw_text,
                    "valid": is_valid,
                    "state_code": st_code,
                    "state": st_name,
                    "hotlist": is_hotlist,
                    "hotlist_info": hotlist_meta,
                    "conf": round(conf, 2),
                    "box": [x1, y1, x2, y2]
                })
        except Exception as e:
            # Non-fatal inference fallback
            pass

        return results

    def annotate(self, frame: np.ndarray, plates: list[dict]) -> np.ndarray:
        """Draw tactical ANPR bounding boxes and plate tags on video frame."""
        out = frame.copy()
        for p in plates:
            x1, y1, x2, y2 = p["box"]
            plate = p["plate"]
            is_hotlist = p["hotlist"]
            is_valid = p["valid"]

            # Color scheme:
            # RED = Flagged Hotlist Vehicle
            # GREEN = Valid Indian Registration Plate
            # YELLOW = Unverified Plate / Low OCR Confidence
            if is_hotlist:
                box_color = (0, 0, 255)       # Red
                reason = p["hotlist_info"].get("reason", "SUSPECT_VEHICLE")
                badge = f"⚠️ HOTLIST: {plate} [{reason}]"
            elif is_valid:
                box_color = (0, 255, 0)       # Green
                badge = f"{plate} ({p['state_code']})"
            else:
                box_color = (0, 215, 255)     # Yellow
                badge = f"{plate} [UNVERIFIED]"

            # Draw box with corner accents
            cv2.rectangle(out, (x1, y1), (x2, y2), box_color, 2)

            # Draw badge background
            font = cv2.FONT_HERSHEY_SIMPLEX
            (tw, th), _ = cv2.getTextSize(badge, font, 0.55, 2)
            bg_y1 = max(0, y1 - th - 10)
            cv2.rectangle(out, (x1, bg_y1), (x1 + tw + 10, y1), box_color, -1)
            text_color = (255, 255, 255) if is_hotlist else (0, 0, 0)
            cv2.putText(out, badge, (x1 + 5, y1 - 5), font, 0.55, text_color, 2)

        return out


# ---------------------------------------------------------------
# STANDALONE TEST HARNESS — run: python code/anpr.py [source]
if __name__ == "__main__":
    clip_cctv = os.path.normpath(os.path.join(ROOT_DIR, "data", "test_videos", "vehicle-cctv.mp4"))
    clip_cars = os.path.normpath(os.path.join(ROOT_DIR, "data", "test_videos", "person-bicycle-car-detection.mp4"))
    DEFAULT_CLIP = clip_cctv if os.path.exists(clip_cctv) else clip_cars

    # Argument resolution
    if len(sys.argv) > 1:
        raw_src = sys.argv[1].strip()
        if raw_src.isdigit():
            src = int(raw_src)
        elif raw_src.lower() in ("webcam", "cam", "live"):
            src = 0
        elif raw_src.lower() in ("cars", "vehicles", "sample"):
            src = DEFAULT_CLIP
        elif os.path.exists(raw_src):
            src = os.path.abspath(raw_src)
        elif os.path.exists(os.path.join(ROOT_DIR, raw_src)):
            src = os.path.normpath(os.path.join(ROOT_DIR, raw_src))
        else:
            src = os.path.abspath(raw_src)
    else:
        # Default: car surveillance clip if exists, otherwise webcam 0
        src = DEFAULT_CLIP if os.path.exists(DEFAULT_CLIP) else 0

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

    if not cap.isOpened():
        print(f"❌ ERROR: Cannot open video source: {src}")
        sys.exit(1)

    native_fps = cap.get(cv2.CAP_PROP_FPS)
    target_fps = native_fps if (native_fps and 1.0 <= native_fps <= 120.0) else 25.0
    frame_delay = 1.0 / target_fps

    anpr = ANPREngine()

    print("=" * 68)
    print("  IBVAP — A5: Automatic Number Plate Recognition (ANPR) Engine")
    print("=" * 68)
    source_label = "LIVE WEBCAM (0)" if src == 0 else str(src)
    print(f"Source       : {source_label}")
    print(f"Hotlist      : {len(anpr.hotlist)} flagged vehicles loaded from hotlist.json")
    print("Controls:")
    print("  'h' -> Print current Hotlist / Watchlist in console")
    print("  's' -> Simulate Hotlist Alert detection (test alert trigger)")
    print("  'q' -> Exit")
    print("=" * 68)

    simulated_alert = False

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

            plates = anpr.process_frame(frame)

            # Test simulation: if 's' pressed, inject a hotlist plate
            if simulated_alert and not plates:
                h, w = frame.shape[:2]
                plates.append({
                    "plate": "HR26DQ5551",
                    "raw_text": "HR26DQ5551",
                    "valid": True,
                    "state_code": "HR",
                    "state": "Haryana",
                    "hotlist": True,
                    "hotlist_info": anpr.hotlist.get("HR26DQ5551", {"reason": "NARCOTICS_SMUGGLING_SUSPECT"}),
                    "conf": 0.94,
                    "box": [w // 2 - 100, h // 2 - 25, w // 2 + 100, h // 2 + 25]
                })

            annotated = anpr.annotate(frame, plates)

            # Overlay HUD
            hud_color = (0, 0, 255) if any(p["hotlist"] for p in plates) else (0, 255, 0)
            cv2.putText(annotated, f"IBVAP ANPR ENGINE | PLATES: {len(plates)}", (15, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, hud_color, 2)
            cv2.putText(annotated, f"Hotlist Watch: {len(anpr.hotlist)} active entries", (15, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1)

            cv2.imshow("IBVAP - ANPR License Plate Engine ('q' to exit)", annotated)

            # Pacing
            if is_file:
                elapsed = time.time() - t_start
                delay = frame_delay - elapsed
                if delay > 0:
                    time.sleep(delay)

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            elif key == ord('h'):
                print("\n🚨 BORDER SECURITY HOTLIST ENTRIES:")
                for pl, info in anpr.hotlist.items():
                    print(f"  • {pl:12} [{info.get('severity','HIGH')}] {info.get('reason','')}: {info.get('description','')}")
                print()
            elif key == ord('s'):
                simulated_alert = not simulated_alert
                print(f"👉 Simulation Hotlist Flag: {'ACTIVE (HR26DQ5551 Injected)' if simulated_alert else 'OFF'}")

    finally:
        cap.release()
        cv2.destroyAllWindows()
