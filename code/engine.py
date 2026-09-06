"""
IBVAP — A4: Detection + Tracking + Night Dual-Path Engine (Member A / Perception)
YOLOv8n + ByteTrack + CLAHE/MOG2 night fallback on top of A2 StreamManager.
Fills the FROZEN contract dict (v1.1) for Member B's dashboard.

Run from project root:  python3 code/engine.py (ya python3 engine.py)
Run from code/ folder:  python3 engine.py
Keys: 'q' = quit | 'n' = toggle FAKE NIGHT (2AM IR demo simulate)
"""

import os
import sys
import time
import json
import math
from collections import deque, defaultdict

import cv2
import numpy as np
from ultralytics import YOLO

# Resolve paths
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR   = os.path.normpath(os.path.join(BASE_DIR, ".."))
if ROOT_DIR not in sys.path:
    sys.path.append(ROOT_DIR)
if BASE_DIR in sys.path:
    sys.path.remove(BASE_DIR)
sys.path.insert(0, BASE_DIR)

from streammanager import StreamManager
from night import NightEngine
from anpr import ANPREngine
from fence import VirtualFenceManager
from tamper import CameraTamperDetector

# ---------------- CONFIG ----------------
MODEL_PATH = os.path.normpath(os.path.join(BASE_DIR, "..", "models", "yolov8n.pt"))
STATE_PATH = os.path.normpath(os.path.join(BASE_DIR, "..", "data", "engine_state.json"))
EVENTS_PATH = os.path.normpath(os.path.join(BASE_DIR, "..", "data", "events.jsonl"))

# ⭐ A6: 5 Recognized Vehicle Classes (all others ignored for vehicle events)
VEHICLE_CLASSES = ["car", "truck", "bus", "motorcycle", "bicycle"]

TARGET_ANALYSIS_FPS = 6.0    # CPU-safe (Mac GPU chahiye to IBVAP_DEVICE=mps)
CONF_THRESH = 0.35
IMGSZ       = 512            # 320=fast, 512=balanced, 640=accurate
TRAIL_LEN   = 40             # v0.6 style 40-pt trails
DEVICE      = os.environ.get("IBVAP_DEVICE", "cpu")
FAKE_NIGHT_FACTOR = 0.22     # 'n' dabane pe frame is factor se dark hoga

# Border-relevant COCO classes (animals bhi — B inko filter karega)
CLS_COLORS = {
    "person": (0, 255, 0), "car": (255, 180, 0), "truck": (255, 120, 0),
    "bus": (255, 120, 0), "bicycle": (0, 200, 255), "motorcycle": (0, 200, 255),
    "bird": (200, 0, 255), "cat": (200, 0, 255), "dog": (200, 0, 255),
    "horse": (200, 0, 255), "sheep": (200, 0, 255), "cow": (200, 0, 255)
}


# ---------------- PER-CAMERA TRACK STATE ----------------
class CamState:
    def __init__(self):
        self.trails = defaultdict(lambda: deque(maxlen=TRAIL_LEN))
        self.first_seen = {}
        self.last_pos = {}                      # tid -> (cx, cy, ts)
        self.logged_vehicles = set()            # ⭐ A6: track_ids that already triggered vehicle event

    def update(self, tid, cx, cy, now):
        if tid not in self.first_seen:
            self.first_seen[tid] = now
        speed = 0.0
        if tid in self.last_pos:
            px, py, pt = self.last_pos[tid]
            dt = max(now - pt, 1e-3)
            speed = math.hypot(cx - px, cy - py) / dt    # px/sec
        self.last_pos[tid] = (cx, cy, now)
        self.trails[tid].append((cx, cy))
        return speed, now - self.first_seen[tid]         # speed, age

    def gc(self, now, max_idle=5.0):                     # dead tracks hatao
        dead = [t for t, (x, y, ts) in self.last_pos.items() if now - ts > max_idle]
        for t in dead:
            self.last_pos.pop(t, None)
            self.first_seen.pop(t, None)
            self.trails.pop(t, None)
            # Note: logged_vehicles retained to avoid duplicate event on track re-acquisition


# ---------------- TRACK EXTRACTION -> CONTRACT ----------------
def extract_tracks(result, state, now):
    tracks = []
    b = result.boxes
    if b is None or b.id is None:
        return tracks
    ids   = b.id.int().cpu().tolist()
    clss  = b.cls.int().cpu().tolist()
    confs = b.conf.float().cpu().tolist()
    xyxys = b.xyxy.float().cpu().tolist()
    for tid, cls_i, conf, (x1, y1, x2, y2) in zip(ids, clss, confs, xyxys):
        name = result.names.get(cls_i, str(cls_i))
        cx, cy = int((x1 + x2) / 2), int((y1 + y2) / 2)
        speed, age = state.update(tid, cx, cy, now)
        tracks.append({
            "tid": int(tid), "cls": name, "conf": round(float(conf), 2),
            "box": [int(x1), int(y1), int(x2), int(y2)],
            "age": round(age, 1), "speed": round(speed, 1),
        })
    return tracks


def log_vehicle_events(tracks, state, stream_name, now, events_path):
    """⭐ A6: Vehicle Classification Events.
    Fires ONCE per vehicle track_id on entry (deduplicated via state.logged_vehicles).
    Only logs recognized vehicle classes (car, truck, bus, motorcycle, bicycle).
    Appends to data/events.jsonl and prints to console.
    """
    for t in tracks:
        cls_name = t["cls"]
        tid = t["tid"]
        if cls_name in VEHICLE_CLASSES:
            if tid not in state.logged_vehicles:
                state.logged_vehicles.add(tid)
                event = {
                    "ts": round(now, 3),
                    "cam_id": stream_name,
                    "stream_id": stream_name,
                    "cls": cls_name,
                    "track_id": tid,
                    "conf": t["conf"],
                    "box": t["box"]
                }
                try:
                    with open(events_path, "a") as f:
                        f.write(json.dumps(event) + "\n")
                except Exception as e:
                    print(f"⚠️ Event logging failed: {e}")

                print(f"🚗 EVENT: {cls_name}#{tid} entered {stream_name} (conf {t['conf']})")


def build_contract(stream_name, tracks, now, ana_fps, zone_events=None, tamper_status=None):
    # FROZEN CONTRACT v1.3 — B isi ko consume karega (backward compatible)
    vehicle_counts = {v_cls: 0 for v_cls in VEHICLE_CLASSES}
    for t in tracks:
        cls_name = t.get("cls")
        if cls_name in vehicle_counts:
            vehicle_counts[cls_name] += 1

    zone_events = zone_events or []
    tamper_status = tamper_status or {
        "tampered": False, "type": "SECURE", "severity": "NORMAL", "message": "CAMERA SECURE"
    }

    # Determine Tactical Threat Level
    has_crit = any(ze.get("severity") == "CRITICAL" for ze in zone_events) or tamper_status.get("tampered", False)
    has_warn = any(ze.get("severity") == "WARNING" for ze in zone_events)

    if has_crit:
        threat_level = "CRITICAL"
    elif has_warn:
        threat_level = "WARNING"
    else:
        threat_level = "NORMAL"

    return {
        "ts": round(now, 3),
        "stream_id": stream_name,
        "night": False,              # process() se REAL value aayegi
        "fps": ana_fps,              # ANALYSIS fps (capture nahi)
        "tracks": tracks,
        "vehicles": vehicle_counts,  # ⭐ A6: Active vehicle count per class
        "threat_level": threat_level,# ⭐ Tactical Threat Level (NORMAL/WARNING/CRITICAL)
        "tamper": tamper_status,     # ⭐ Camera anti-tamper / sabotage state
        "zone_events": zone_events,  # ⭐ Virtual fence intrusion / crawling events
        "faces": [],                 # FRS — B ka domain
        "plates": [],                # A5 domain
        "motion": [],                # MOG2 motion boxes (night safety-net)
    }


# ---------------- DRAWING ----------------
def draw(frame, tracks, state, stream_name, cap_fps, connected, ana_fps,
         night=False, motion=None, plates=None, zone_events=None,
         fence_manager=None, show_zones=True, tamper_status=None):

    # 1. Render Virtual Zones if enabled
    if show_zones and fence_manager is not None:
        frame = fence_manager.draw_zones(frame, stream_name, zone_events)

    # 2. Tracks with posture & breach tagging
    crit_tracks = {ze["track_id"]: ze for ze in (zone_events or []) if ze.get("severity") == "CRITICAL"}
    warn_tracks = {ze["track_id"]: ze for ze in (zone_events or []) if ze.get("severity") == "WARNING"}

    for t in tracks:
        x1, y1, x2, y2 = t["box"]
        tid = t["tid"]
        color = CLS_COLORS.get(t["cls"], (255, 255, 255))
        tag = f'{t["cls"]} #{tid} {t["conf"]}'

        if tid in crit_tracks:
            color = (0, 0, 255)  # Red
            if crit_tracks[tid].get("posture") == "CRAWLING_PRONE":
                tag += " [CRAWL 🚨]"
            else:
                tag += " [BREACH 🚨]"
        elif tid in warn_tracks:
            color = (0, 200, 255)  # Yellow

        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cv2.putText(frame, tag, (x1, max(y1 - 8, 14)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.52, color, 2)

        pts = state.trails.get(tid)
        if pts and len(pts) > 1:
            for i in range(1, len(pts)):
                cv2.line(frame, pts[i - 1], pts[i], color, 2)

    # 3. ANPR License Plate Overlay
    if plates:
        for p in plates:
            x1, y1, x2, y2 = p["box"]
            plate = p["plate"]
            is_hotlist = p.get("hotlist", False)
            is_valid = p.get("valid", False)
            box_color = (0, 0, 255) if is_hotlist else ((0, 255, 0) if is_valid else (0, 215, 255))
            cv2.rectangle(frame, (x1, y1), (x2, y2), box_color, 2)
            badge = f"⚠️ HOTLIST: {plate}" if is_hotlist else f"{plate} ({p.get('state_code', 'IN')})"
            font = cv2.FONT_HERSHEY_SIMPLEX
            (tw, th), _ = cv2.getTextSize(badge, font, 0.5, 2)
            cv2.rectangle(frame, (x1, max(0, y1 - th - 8)), (x1 + tw + 8, y1), box_color, -1)
            cv2.putText(frame, badge, (x1 + 4, y1 - 4), font, 0.5, (255, 255, 255) if is_hotlist else (0, 0, 0), 2)

    # 4. MOG2 Motion
    if night and motion:
        for (x1, y1, x2, y2) in motion:
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 165, 255), 2)
            cv2.putText(frame, "MOTION", (x1, max(y1 - 6, 14)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 165, 255), 2)

    # 5. Night badge
    if night:
        cv2.putText(frame, "🌙 NIGHT MODE", (frame.shape[1] // 2 - 90, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 0, 255), 2)

    # 6. Tamper Sabotage Banner
    if tamper_status and tamper_status.get("tampered", False):
        t_msg = f"⚠️ {tamper_status['message']}"
        cv2.rectangle(frame, (0, frame.shape[0] - 45), (frame.shape[1], frame.shape[0]), (0, 0, 220), -1)
        cv2.putText(frame, t_msg, (15, frame.shape[0] - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)

    # 7. Status HUD
    hud_col = (0, 255, 0) if connected else (0, 0, 255)
    cv2.putText(frame, f'{stream_name} | {"LIVE" if connected else "DOWN"} | '
                f'{cap_fps} fps | AI {ana_fps} Hz',
                (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.62, hud_col, 2)
    return frame


# ---------------- MAIN ----------------
def main():
    VIDEO_DIR = os.path.normpath(os.path.join(BASE_DIR, "..", "data", "test_videos"))
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    os.makedirs(os.path.dirname(EVENTS_PATH), exist_ok=True)

    vehicle_vid = os.path.join(VIDEO_DIR, "vehicle-cctv.mp4")
    cam2_src = vehicle_vid if os.path.exists(vehicle_vid) else os.path.join(VIDEO_DIR, "person-bicycle-car-detection.mp4")

    SOURCES = [
        {"src": os.path.join(VIDEO_DIR, "people-detection.mp4"), "name": "CAM-01 (People)"},
        {"src": cam2_src, "name": "CAM-02 (Vehicles & ANPR)"},
    ]

    # Optional: agar night-surveillance video ho to CAM-03 bhi add kar sakte hain
    night_vid = os.path.join(VIDEO_DIR, "night-surveillance.mp4")
    if os.path.exists(night_vid):
        SOURCES.append({"src": night_vid, "name": "CAM-03 (Night CCTV)"})

    missing = [s["src"] for s in SOURCES if not os.path.exists(s["src"])]
    if missing:
        for m in missing:
            print(f"❌ VIDEO NAHI MILI: {m}")
        sys.exit(1)

    mgr = StreamManager()
    for s in SOURCES:
        mgr.add(s["src"], name=s["name"])

    # Har camera ka APNA model (ByteTrack state isolate rahega)
    models = {cam_id: YOLO(MODEL_PATH) for cam_id in mgr.streams}
    states = {cam_id: CamState() for cam_id in mgr.streams}
    
    # Har camera ka APNA NightEngine (MOG2 background model isolate rahega)
    night_engines = {cam_id: NightEngine(cam_id) for cam_id in mgr.streams}

    # ⭐ A5: Automatic Number Plate Recognition Engine
    anpr_engine = ANPREngine()

    # ⭐ Tactical Virtual Fencing & Camera Anti-Tamper Engines
    fence_manager = VirtualFenceManager()
    tamper_detectors = {cam_id: CameraTamperDetector(mgr.streams[cam_id].name) for cam_id in mgr.streams}

    fake_night = False
    simulated_hotlist = False
    simulated_tamper = False
    show_zones = True
    annotated = {cam_id: None for cam_id in mgr.streams}
    contracts = {}
    breach_cooldown = {}

    print("=" * 65)
    print("  IBVAP — Tactical Border Intelligence & Perception Platform")
    print("=" * 65)
    print(f"Device: {DEVICE} | Analysis target: {TARGET_ANALYSIS_FPS} Hz | imgsz={IMGSZ}")
    print(f"Active Cameras: {[s['name'] for s in SOURCES]}")
    print(f"Events Ledger : {EVENTS_PATH}")
    print(f"Hotlist Watch : {len(anpr_engine.hotlist)} suspect vehicles loaded")
    print("Keys : 'q'=quit | 'n'=night | 'h'=hotlist | 't'=tamper demo | 'z'=zones HUD")
    print("=" * 65)

    interval = 1.0 / TARGET_ANALYSIS_FPS
    last_tick, last_print, tick_count, print_t0 = 0.0, time.time(), 0, time.time()

    try:
        while True:
            now = time.time()

            # ---- ANALYSIS TICK (pace-bound, capture se decoupled) ----
            if now - last_tick >= interval:
                last_tick = now
                tick_count += 1
                for cam_id, stream in mgr.streams.items():
                    frame = stream.read()
                    if frame is None:
                        continue
                    st = stream.stats()

                    # Tamper Simulation test toggle (e.g. spray paint on CAM-01)
                    if simulated_tamper and "CAM-01" in st["name"]:
                        frame = np.zeros_like(frame)

                    # Camera Anti-Tamper & Sabotage Evaluation
                    tamper_status = tamper_detectors[cam_id].analyze(frame, now=now)
                    if tamper_status["tampered"]:
                        print(f"🚨 TAMPER ALERT [{st['name']}]: {tamper_status['message']}")

                    # Demo toggle — frame ko 2AM jaisa dark karo
                    if fake_night:
                        frame = (frame * FAKE_NIGHT_FACTOR).astype(np.uint8)

                    # Dual-path night processing (brightness gate + CLAHE enhance + MOG2 motion)
                    nr = night_engines[cam_id].process(frame)

                    # YOLO ko ENHANCED frame do (night me CLAHE wala)
                    result = models[cam_id].track(
                        nr["enhanced"], persist=True, conf=CONF_THRESH,
                        imgsz=IMGSZ, device=DEVICE, verbose=False)[0]

                    tracks = extract_tracks(result, states[cam_id], now)
                    states[cam_id].gc(now)

                    # ⭐ Virtual Fence Intrusion & Posture Evaluation (Upright / Crawling)
                    zone_events = fence_manager.evaluate_tracks(st["name"], tracks, frame.shape, now)
                    for ze in zone_events:
                        if ze["severity"] == "CRITICAL":
                            b_key = (st["name"], ze["track_id"], ze["zone_id"])
                            if now - breach_cooldown.get(b_key, 0) > 6.0:
                                breach_cooldown[b_key] = now
                                print(f"🚨 PERIMETER BREACH [{st['name']}]: {ze['event_type']} - "
                                      f"{ze['cls']}#{ze['track_id']} in {ze['zone_name']} (Posture: {ze['posture']})")

                    # ⭐ A6: Vehicle Classification Events (Deduplicated per track_id)
                    log_vehicle_events(tracks, states[cam_id], st["name"], now, EVENTS_PATH)

                    # ⭐ A5: ANPR Detection on vehicles
                    has_vehicles = any(t["cls"] in VEHICLE_CLASSES for t in tracks)
                    plates = anpr_engine.process_frame(frame) if has_vehicles else []

                    # Test simulation hotlist injection on CAM-02
                    if simulated_hotlist and "CAM-02" in st["name"] and not plates:
                        h, w = frame.shape[:2]
                        plates.append({
                            "plate": "HR26DQ5551", "raw_text": "HR26DQ5551", "valid": True,
                            "state_code": "HR", "state": "Haryana", "hotlist": True,
                            "hotlist_info": anpr_engine.hotlist.get("HR26DQ5551", {"reason": "NARCOTICS_SMUGGLING_SUSPECT"}),
                            "conf": 0.94, "box": [w // 2 - 80, h // 2 - 20, w // 2 + 80, h // 2 + 20]
                        })

                    c = build_contract(st["name"], tracks, now, TARGET_ANALYSIS_FPS,
                                       zone_events=zone_events, tamper_status=tamper_status)
                    c["night"] = nr["night"]           # real boolean
                    c["motion"] = nr["motion"]         # safety-net boxes
                    c["plates"] = plates               # ⭐ A5: Populated ANPR plates!
                    contracts[st["name"]] = c

                    annotated[cam_id] = draw(
                        frame.copy(), tracks, states[cam_id], st["name"],
                        st["fps"], st["connected"], TARGET_ANALYSIS_FPS,
                        night=nr["night"], motion=nr["motion"], plates=plates,
                        zone_events=zone_events, fence_manager=fence_manager,
                        show_zones=show_zones, tamper_status=tamper_status)

                # Member B ke liye atomic state dump (dashboard isse poll karega)
                try:
                    tmp_state = STATE_PATH + ".tmp"
                    with open(tmp_state, "w") as f:
                        json.dump(contracts, f)
                    os.replace(tmp_state, STATE_PATH)
                except Exception:
                    pass

            # ---- DISPLAY (latest annotated frames) ----
            for cam_id, stream in mgr.streams.items():
                if annotated[cam_id] is not None:
                    cv2.imshow(stream.name, annotated[cam_id])

            # ---- CONSOLE SUMMARY (har 2 sec) ----
            if now - last_print >= 2:
                ana_fps = tick_count / max(now - print_t0, 1e-3)
                tick_count, print_t0 = 0, now
                print(f"--- AI {ana_fps:.1f} Hz ---")
                for name, c in contracts.items():
                    tl = ", ".join(f'{t["cls"]}#{t["tid"]}'
                                   f'({t["speed"]}px/s)' for t in c["tracks"]) or "—"
                    night_tag = "🌙NIGHT" if c["night"] else "DAY"
                    threat = c.get("threat_level", "NORMAL")
                    threat_tag = f" | 🚨{threat}" if threat != "NORMAL" else ""
                    plate_str = ", ".join(f"{p['plate']}{' 🚨HOTLIST' if p['hotlist'] else ''}" for p in c.get("plates", []))
                    plate_tag = f" | 🚗 {plate_str}" if plate_str else ""
                    v_dict = c.get("vehicles", {})
                    v_active = sum(v_dict.values())
                    veh_tag = f" | 🚙 {v_active} veh" if v_active > 0 else ""
                    print(f'{name}: {night_tag}{threat_tag} | motion={len(c["motion"])} '
                          f'| {len(c["tracks"])} tracks{veh_tag}{plate_tag} | {tl}')
                last_print = now

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            elif key == ord('n'):
                fake_night = not fake_night
                print(f"🌙 FAKE NIGHT: {fake_night}")
            elif key == ord('h'):
                simulated_hotlist = not simulated_hotlist
                print(f"🚨 HOTLIST SIMULATION: {'ACTIVE (HR26DQ5551 Injected)' if simulated_hotlist else 'OFF'}")
            elif key == ord('t'):
                simulated_tamper = not simulated_tamper
                print(f"🚨 CAMERA TAMPER DEMO: {'ACTIVE (Lens Blinded on CAM-01)' if simulated_tamper else 'OFF'}")
            elif key == ord('z'):
                show_zones = not show_zones
                print(f"🛡️ VIRTUAL ZONES OVERLAY: {'ENABLED' if show_zones else 'DISABLED'}")
    except KeyboardInterrupt:
        pass
    finally:
        mgr.stop_all()
        cv2.destroyAllWindows()
        print("Engine stopped cleanly. ✅")


if __name__ == "__main__":
    main()