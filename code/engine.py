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
from ledger import append_event, file_sha256
try:
    import frs as frslib
except Exception:
    frslib = None

# ---------------- CONFIG ----------------
MODEL_PATH = os.path.normpath(os.path.join(BASE_DIR, "..", "models", "yolov8n.pt"))
STATE_PATH = os.path.normpath(os.path.join(BASE_DIR, "..", "data", "engine_state.json"))
EVENTS_PATH = os.path.normpath(os.path.join(BASE_DIR, "..", "data", "events.jsonl"))

# ⭐ A6: 5 Recognized Vehicle Classes (all others ignored for vehicle events)
VEHICLE_CLASSES = ["car", "truck", "bus", "motorcycle", "bicycle"]

TARGET_ANALYSIS_FPS = 5.0    # CPU-safe (Mac GPU chahiye to IBVAP_DEVICE=mps)
CONF_THRESH = 0.35
IMGSZ       = 416            # 320=fast, 416=balanced, 640=accurate
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


def log_vehicle_events(tracks, state, stream_name, now, events_path, frame=None, plates=None):
    """⭐ A6: Vehicle Classification Events.
    Fires ONCE per vehicle track_id on entry (deduplicated via state.logged_vehicles).
    Only logs recognized vehicle classes (car, truck, bus, motorcycle, bicycle).
    Appends to data/events.jsonl, seals cryptographic snapshot into evidence ledger, and prints to console.
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

                # ⭐ Save evidence snapshot and seal onto cryptographic ledger for dashboard display
                if frame is not None:
                    try:
                        snap_name = f"car_trk_{tid}_{int(now*1000)}.jpg"
                        snap_path = os.path.join(ROOT_DIR, "data", "snapshots", snap_name)
                        cv2.imwrite(snap_path, frame)
                        snap_hash = file_sha256(snap_path)
                        plate_val = plates[0]["plate"] if (plates and len(plates) > 0) else None
                        is_bolo = plates[0].get("hotlist", False) if (plates and len(plates) > 0) else False

                        ledger_rec = {
                            "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
                            "event": "HOTLIST_VEHICLE_BOLO" if is_bolo else f"VEHICLE_{cls_name.upper()}_DETECTED",
                            "stream_id": stream_name,
                            "track_id": tid,
                            "score": 90 if is_bolo else 55,
                            "severity": "CRITICAL" if is_bolo else "INFO",
                            "breakdown": {"vehicle": 25, "speed": int(t.get("speed", 0)), "bolo": 50 if is_bolo else 0},
                            "snapshot": snap_path,
                            "snapshot_sha256": snap_hash,
                            "location": [(t["box"][0] + t["box"][2]) // 2, (t["box"][1] + t["box"][3]) // 2],
                            "speed_px_s": round(t.get("speed", 0), 1),
                            "age_sec": round(t.get("age", 0), 1),
                            "plate": plate_val,
                        }
                        append_event(ledger_rec)
                    except Exception as e:
                        print(f"⚠️ Ledger append failed for vehicle #{tid}: {e}")

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
         fence_manager=None, show_zones=True, tamper_status=None, faces=None):

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
                tag += " [CRAWL !]"
            else:
                tag += " [BREACH !]"
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
            badge = f"[!] HOTLIST: {plate}" if is_hotlist else f"{plate} ({p.get('state_code', 'IN')})"
            font = cv2.FONT_HERSHEY_SIMPLEX
            (tw, th), _ = cv2.getTextSize(badge, font, 0.5, 2)
            cv2.rectangle(frame, (x1, max(0, y1 - th - 8)), (x1 + tw + 8, y1), box_color, -1)
            cv2.putText(frame, badge, (x1 + 4, y1 - 4), font, 0.5, (255, 255, 255) if is_hotlist else (0, 0, 0), 2)

    # 4. Biometric Face Recognition Overlay (CAM-05)
    if faces:
        for f in faces:
            bx, by, bw, bh = f["box"]
            fname = f.get("name", "Unknown")
            fscore = f.get("score", 0.0)
            is_bolo = f.get("bolo", False)
            fcolor = (0, 0, 255) if is_bolo else (0, 255, 120)
            cv2.rectangle(frame, (bx, by), (bx + bw, by + bh), fcolor, 2)

            badge = f"[!] BOLO MATCH: {fname[:18]} ({int(fscore*100)}%)" if is_bolo else f"FACE: {fname} ({int(fscore*100)}%)"
            font = cv2.FONT_HERSHEY_SIMPLEX
            (tw, th), _ = cv2.getTextSize(badge, font, 0.46, 2)
            cv2.rectangle(frame, (bx, max(0, by - th - 8)), (bx + tw + 8, by), fcolor, -1)
            cv2.putText(frame, badge, (bx + 4, by - 4), font, 0.46, (255, 255, 255) if is_bolo else (0, 0, 0), 2)

            if is_bolo:
                cv2.rectangle(frame, (0, frame.shape[0] - 32), (frame.shape[1], frame.shape[0]), (0, 0, 200), -1)
                cv2.putText(frame, f"[!] CRITICAL BIOMETRIC ALERT: Watchlist Match - {fname}", (15, frame.shape[0] - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 2)

    # 5. FLIR Thermal LWIR Telemetry Overlay (CAM-04)
    if "CAM-04" in stream_name:
        cv2.putText(frame, "FLIR SC6000 LWIR 8-14um | PALETTE: INFERNO", (frame.shape[1] - 380, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 220, 255), 2)
        cv2.putText(frame, "STANDOFF HEAT EMISSIVITY: 0.98", (frame.shape[1] - 300, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 180, 240), 1)

    # 6. MOG2 Motion
    if night and motion:
        for (x1, y1, x2, y2) in motion:
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 165, 255), 2)
            cv2.putText(frame, "MOTION", (x1, max(y1 - 6, 14)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 165, 255), 2)

    # 7. Night badge
    if night:
        cv2.putText(frame, "[NIGHT MODE]", (frame.shape[1] // 2 - 80, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 0, 255), 2)

    # 8. Tamper Sabotage Banner
    if tamper_status and tamper_status.get("tampered", False):
        t_msg = f"[!] {tamper_status['message']}"
        cv2.rectangle(frame, (0, frame.shape[0] - 45), (frame.shape[1], frame.shape[0]), (0, 0, 220), -1)
        cv2.putText(frame, t_msg, (15, frame.shape[0] - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)

    # 9. Status HUD
    hud_col = (0, 255, 0) if connected else (0, 0, 255)
    cv2.putText(frame, f'{stream_name} | {"LIVE" if connected else "DOWN"} | '
                f'{cap_fps} fps | AI {ana_fps} Hz',
                (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.62, hud_col, 2)
    return frame


def build_tactical_grid(annotated, mgr, contracts, fake_night, simulated_hotlist, simulated_tamper, show_zones, ana_fps, user_points=None, drawing_cam=None):
    """Composes 5 active tactical surveillance streams + 1 C2 Telemetry HUD into a unified 1440x720 6-Split Grid."""
    TW, TH = 480, 360
    grid = np.zeros((TH * 2, TW * 3, 3), dtype=np.uint8)

    cams = {}
    for cam_id, stream in mgr.streams.items():
        frame = annotated.get(cam_id)
        if frame is None:
            continue
        if "CAM-01" in stream.name:
            cams["CAM-01"] = frame
        elif "CAM-02" in stream.name:
            cams["CAM-02"] = frame
        elif "CAM-03" in stream.name:
            cams["CAM-03"] = frame
        elif "CAM-04" in stream.name:
            cams["CAM-04"] = frame
        elif "CAM-05" in stream.name:
            cams["CAM-05"] = frame

    # Row 1 (Top):
    # Tile 1 (0, 0): CAM-01 (People & Perimeter)
    if "CAM-01" in cams:
        grid[0:TH, 0:TW] = cv2.resize(cams["CAM-01"], (TW, TH))
    else:
        cv2.putText(grid, "CAM-01 (People) - INITIALIZING", (20, TH // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (180, 180, 180), 1)

    # Tile 2 (1, 0): CAM-02 (Vehicles & ANPR)
    if "CAM-02" in cams:
        grid[0:TH, TW:TW * 2] = cv2.resize(cams["CAM-02"], (TW, TH))
    else:
        cv2.putText(grid, "CAM-02 (Vehicles & ANPR) - INITIALIZING", (TW + 20, TH // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (180, 180, 180), 1)

    # Tile 3 (2, 0): CAM-03 (Night CCTV)
    if "CAM-03" in cams:
        grid[0:TH, TW * 2:TW * 3] = cv2.resize(cams["CAM-03"], (TW, TH))
    else:
        cv2.putText(grid, "CAM-03 (Night CCTV) - INITIALIZING", (TW * 2 + 20, TH // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (180, 180, 180), 1)

    # Row 2 (Bottom):
    # Tile 4 (0, 1): CAM-04 (Thermal FLIR)
    if "CAM-04" in cams:
        grid[TH:TH * 2, 0:TW] = cv2.resize(cams["CAM-04"], (TW, TH))
    else:
        cv2.putText(grid, "CAM-04 (Thermal FLIR) - INITIALIZING", (20, TH + TH // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (180, 180, 180), 1)

    # Tile 5 (1, 1): CAM-05 (Face Recognition)
    if "CAM-05" in cams:
        grid[TH:TH * 2, TW:TW * 2] = cv2.resize(cams["CAM-05"], (TW, TH))
    else:
        cv2.putText(grid, "CAM-05 (Face Recognition) - INITIALIZING", (TW + 20, TH + TH // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (180, 180, 180), 1)

    # Interactive User-Drawn Fence Overlay
    if user_points and drawing_cam:
        tile_offsets = {
            "CAM-01": (0, 0),
            "CAM-02": (TW, 0),
            "CAM-03": (TW * 2, 0),
            "CAM-04": (0, TH),
            "CAM-05": (TW, TH),
        }
        tox, toy = (0, 0)
        for k, v in tile_offsets.items():
            if k in drawing_cam:
                tox, toy = v
                break
        pts_px = [(int(tox + p[0] * TW), int(toy + p[1] * TH)) for p in user_points]
        for p in pts_px:
            cv2.circle(grid, p, 5, (0, 255, 255), -1)
            cv2.circle(grid, p, 7, (0, 0, 255), 1)
        if len(pts_px) > 1:
            for i in range(1, len(pts_px)):
                cv2.line(grid, pts_px[i - 1], pts_px[i], (0, 255, 255), 2)
            if len(pts_px) >= 3:
                cv2.line(grid, pts_px[-1], pts_px[0], (0, 180, 255), 1)
        cv2.putText(grid, f"DRAWING FENCE: {len(user_points)} pts | [C] ARM | [R] CLEAR",
                    (tox + 10, toy + 28), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 255, 255), 2)

    # Tile 6 (2, 1): Tactical C2 Telemetry & Control HUD
    hud = np.zeros((TH, TW, 3), dtype=np.uint8)
    hud[:] = (12, 16, 26)  # Tactical slate background
    cv2.rectangle(hud, (2, 2), (TW - 2, TH - 2), (40, 60, 90), 1)

    # Header
    cv2.rectangle(hud, (0, 0), (TW, 34), (20, 32, 54), -1)
    cv2.putText(hud, "IBVAP - 6-SPLIT TACTICAL C2", (15, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 240, 255), 2)
    cv2.putText(hud, f"AI {ana_fps:.1f} Hz", (TW - 95, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 255, 150), 2)

    y = 56
    c_p = contracts.get("CAM-01 (People)", {})
    c_v = contracts.get("CAM-02 (Vehicles & ANPR)", {})
    c_n = contracts.get("CAM-03 (Night CCTV)", {})
    c_t = contracts.get("CAM-04 (Thermal FLIR)", {})
    c_f = contracts.get("CAM-05 (Face Recognition)", {})

    # Sector Telemetry
    p_trks = len(c_p.get("tracks", []))
    p_threat = c_p.get("threat_level", "NORMAL")
    p_col = (0, 0, 255) if p_threat == "CRITICAL" else ((0, 200, 255) if p_threat == "WARNING" else (0, 255, 0))
    cv2.putText(hud, f"CAM-01 [People]  : {p_trks} Trk | Threat: {p_threat}", (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.42, p_col, 1)
    y += 20

    v_dict = c_v.get("vehicles", {})
    v_cnt = sum(v_dict.values())
    plates = c_v.get("plates", [])
    p_str = plates[0]["plate"] if plates else "Scanning..."
    cv2.putText(hud, f"CAM-02 [Vehicles]: {v_cnt} Veh | Plate: {p_str}", (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 220, 255), 1)
    y += 20

    n_lux = c_n.get("tamper", {}).get("metrics", {}).get("mean_lux", 20.0)
    cv2.putText(hud, f"CAM-03 [Night IR]: MOONLIGHT (Lux {n_lux:.0f}) | CLAHE", (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 180, 50), 1)
    y += 20

    t_trks = len(c_t.get("tracks", []))
    cv2.putText(hud, f"CAM-04 [Thermal] : FLIR LWIR 8-14um | {t_trks} Heat Trk", (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 200, 255), 1)
    y += 20

    f_faces = c_f.get("faces", [])
    f_str = f_faces[0]["name"][:20] if f_faces else "Watchlist Scan"
    f_threat = c_f.get("threat_level", "NORMAL")
    f_col = (0, 0, 255) if f_threat == "CRITICAL" else (0, 255, 120)
    cv2.putText(hud, f"CAM-05 [Biometric]: YuNet FRS | {f_str}", (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.42, f_col, 1)
    y += 24

    cv2.line(hud, (15, y), (TW - 15, y), (45, 60, 85), 1)
    y += 18

    # System Defense & Shortcuts
    fn_status = "2AM DARK (ON)" if fake_night else "NORMAL"
    cv2.putText(hud, f"[N] Fake Night Sim : {fn_status}", (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (0, 160, 255) if fake_night else (160, 160, 160), 1)
    y += 18

    ht_status = "HR26DQ5551 [!]" if simulated_hotlist else "STANDBY"
    cv2.putText(hud, f"[H] Hotlist BOLO    : {ht_status}", (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (0, 0, 255) if simulated_hotlist else (160, 160, 160), 1)
    y += 18

    tp_status = "LENS BLINDED [!]" if simulated_tamper else "SECURE (Normal)"
    cv2.putText(hud, f"[T] Tamper Sabotage: {tp_status}", (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (0, 0, 255) if simulated_tamper else (0, 255, 150), 1)
    y += 18

    # Cryptographic SHA-256 Evidence Ledger
    try:
        with open(os.path.join(ROOT_DIR, "data", "evidence_chain.jsonl"), "r") as ef:
            l_lines = ef.readlines()
            ledg_cnt = len(l_lines)
            last_rec = json.loads(l_lines[-1]) if l_lines else {}
            head_hash = last_rec.get("block_hash", "GENESIS")[:10] + ".."
    except Exception:
        ledg_cnt, head_hash = 0, "SECURE"
    cv2.putText(hud, f"Ledger: {ledg_cnt} Sealed | Head: {head_hash}", (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (160, 190, 220), 1)
    y += 18

    zn_status = "ACTIVE" if show_zones else "HIDDEN"
    cv2.putText(hud, f"[Z] Zones: {zn_status}  |  [G] Grid  |  [Q] Quit", (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (0, 200, 255), 1)
    y += 18

    cv2.putText(hud, "Draw: Click cam | [C] Arm | [X] Wipe | [P] Preset", (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 240, 255), 1)

    grid[TH:TH * 2, TW * 2:TW * 3] = hud

    # Grid dividing lines
    cv2.line(grid, (0, TH), (TW * 3, TH), (0, 220, 255), 2)
    cv2.line(grid, (TW, 0), (TW, TH * 2), (0, 220, 255), 2)
    cv2.line(grid, (TW * 2, 0), (TW * 2, TH * 2), (0, 220, 255), 2)
    return grid



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
        {"src": os.path.join(VIDEO_DIR, "night-surveillance.mp4"), "name": "CAM-03 (Night CCTV)"},
        {"src": os.path.join(VIDEO_DIR, "thermal-ir-surveillance.mp4"), "name": "CAM-04 (Thermal FLIR)"},
        {"src": os.path.join(VIDEO_DIR, "face-checkpoint.mp4"), "name": "CAM-05 (Face Recognition)"},
    ]

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

    # ⭐ Choke-Point Biometric Face Recognition Watchlist
    face_gallery = frslib.load_gallery() if frslib else {}

    fake_night = False
    simulated_hotlist = False
    simulated_tamper = False
    show_zones = True
    use_grid = True
    headless = "--headless" in sys.argv or os.environ.get("IBVAP_HEADLESS", "0") == "1"
    annotated = {cam_id: None for cam_id in mgr.streams}
    contracts = {}
    breach_cooldown = {}

    user_points = []
    drawing_cam = None

    WIN_NAME = "IBVAP Tactical Multi-Camera Command Grid (6-Split)"

    def on_mouse(event, x, y, flags, param):
        nonlocal user_points, drawing_cam
        if event == cv2.EVENT_LBUTTONDOWN and use_grid:
            TW, TH = 480, 360
            col = x // TW
            row = y // TH
            cam_map = {
                (0, 0): "CAM-01 (People)",
                (1, 0): "CAM-02 (Vehicles & ANPR)",
                (2, 0): "CAM-03 (Night CCTV)",
                (0, 1): "CAM-04 (Thermal FLIR)",
                (1, 1): "CAM-05 (Face Recognition)",
            }
            target = cam_map.get((col, row))
            if target:
                if drawing_cam != target:
                    user_points = []
                    drawing_cam = target
                nx = max(0.0, min(1.0, (x - col * TW) / float(TW)))
                ny = max(0.0, min(1.0, (y - row * TH) / float(TH)))
                user_points.append([round(nx, 4), round(ny, 4)])
                print(f"📍 Point #{len(user_points)} clicked on {target}: ({nx:.2f}, {ny:.2f}) -> Press [C] to ARM, [R] to CLEAR")

    if not headless:
        try:
            cv2.namedWindow(WIN_NAME, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(WIN_NAME, 1440, 720)
            cv2.setMouseCallback(WIN_NAME, on_mouse)
        except Exception:
            pass

    print("=" * 65)
    print("  IBVAP — Tactical Border Intelligence & Perception Platform")
    print("=" * 65)
    print(f"Device: {DEVICE} | Analysis target: {TARGET_ANALYSIS_FPS} Hz | imgsz={IMGSZ}")
    print(f"Active Cameras: {[s['name'] for s in SOURCES]}")
    print(f"Events Ledger : {EVENTS_PATH}")
    print(f"Hotlist Watch : {len(anpr_engine.hotlist)} suspect vehicles loaded")
    print(f"Biometric FRS : {len(face_gallery)} suspects on BOLO watchlist")
    print("Controls HUD  : 'q'=quit | 'n'=fake night | 'h'=hotlist | 't'=tamper | 'z'=zones | 'g'=grid")
    print("Draw Fence    : Click camera tile with mouse -> [C]=Arm | [X]=Wipe all | [R]=Clear pts | [P]=Reset preset")
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

                    faces_data = []
                    plates = []
                    zone_events = []

                    if "CAM-05" in st["name"]:
                        # ⭐ CAM-05: Choke-Point Biometric Face Recognition (YuNet + SFace)
                        tracks = []
                        if frslib:
                            f_boxes = frslib.detect_faces(frame)
                            if f_boxes:
                                m_results = frslib.match_faces(frame, f_boxes, gallery=face_gallery)
                                for idx_f, ((bx, by, bw, bh), m_name, m_score) in enumerate(m_results):
                                    is_bolo = bool(m_name and "BOLO" in m_name)
                                    faces_data.append({
                                        "box": [bx, by, bw, bh],
                                        "name": m_name or "Unknown",
                                        "score": round(float(m_score), 2),
                                        "bolo": is_bolo
                                    })
                                    speed, age = states[cam_id].update(900 + idx_f, bx + bw // 2, by + bh // 2, now)
                                    tracks.append({
                                        "tid": 900 + idx_f, "cls": "person", "conf": round(float(m_score), 2),
                                        "box": [bx, by, bx + bw, by + bh], "age": round(age, 1), "speed": round(speed, 1)
                                    })
                                    if is_bolo:
                                        b_key = ("CAM-05", m_name)
                                        if now - breach_cooldown.get(b_key, 0) > 8.0:
                                            breach_cooldown[b_key] = now
                                            print(f"🚨 CRITICAL BIOMETRIC ALERT [{st['name']}]: Watchlist Suspect: {m_name} ({m_score*100:.1f}%)")
                                            try:
                                                snap_name = f"face_bolo_{int(now*1000)}.jpg"
                                                snap_path = os.path.join(ROOT_DIR, "data", "snapshots", snap_name)
                                                cv2.imwrite(snap_path, frame)
                                                snap_hash = file_sha256(snap_path)
                                                append_event({
                                                    "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
                                                    "event": "WATCHLIST_FACE_MATCH",
                                                    "stream_id": st["name"],
                                                    "track_id": 900 + idx_f,
                                                    "score": 98,
                                                    "severity": "CRITICAL",
                                                    "breakdown": {"biometric_confidence": round(float(m_score)*100, 1), "watchlist_match": 100},
                                                    "snapshot": snap_path,
                                                    "snapshot_sha256": snap_hash,
                                                    "location": [bx + bw // 2, by + bh // 2],
                                                })
                                            except Exception as e:
                                                print(f"⚠️ Face ledger append failed: {e}")
                        states[cam_id].gc(now)
                        zone_events = fence_manager.evaluate_tracks(st["name"], tracks, frame.shape, now)
                    else:
                        # YOLOv8n inference on enhanced frame (CAM-01, CAM-02, CAM-03, CAM-04)
                        result = models[cam_id].track(
                            nr["enhanced"], persist=True, conf=CONF_THRESH,
                            imgsz=IMGSZ, device=DEVICE, verbose=False)[0]

                        tracks = extract_tracks(result, states[cam_id], now)
                        states[cam_id].gc(now)

                        # Virtual fence evaluation
                        zone_events = fence_manager.evaluate_tracks(st["name"], tracks, frame.shape, now)
                        for ze in zone_events:
                            if ze["severity"] == "CRITICAL":
                                b_key = (st["name"], ze["track_id"], ze["zone_id"])
                                if now - breach_cooldown.get(b_key, 0) > 6.0:
                                    breach_cooldown[b_key] = now
                                    print(f"🚨 PERIMETER BREACH [{st['name']}]: {ze['event_type']} - "
                                          f"{ze['cls']}#{ze['track_id']} in {ze['zone_name']} (Posture: {ze['posture']})")
                                    try:
                                        snap_name = f"breach_{ze['track_id']}_{int(now*1000)}.jpg"
                                        snap_path = os.path.join(ROOT_DIR, "data", "snapshots", snap_name)
                                        cv2.imwrite(snap_path, frame)
                                        snap_hash = file_sha256(snap_path)
                                        append_event({
                                            "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
                                            "event": ze["event_type"],
                                            "stream_id": st["name"],
                                            "track_id": ze["track_id"],
                                            "score": 95 if ze["posture"] == "CRAWLING_PRONE" else 85,
                                            "severity": "CRITICAL",
                                            "breakdown": {"zone": 50, "posture": 35 if ze["posture"] == "CRAWLING_PRONE" else 15},
                                            "snapshot": snap_path,
                                            "snapshot_sha256": snap_hash,
                                            "location": [(ze["box"][0] + ze["box"][2]) // 2, (ze["box"][1] + ze["box"][3]) // 2],
                                        })
                                    except Exception as e:
                                        print(f"⚠️ Breach ledger append failed: {e}")

                        # ANPR for vehicles (CAM-02)
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

                        # Vehicle classification events
                        log_vehicle_events(tracks, states[cam_id], st["name"], now, EVENTS_PATH, frame=frame, plates=plates)

                    c = build_contract(st["name"], tracks, now, TARGET_ANALYSIS_FPS,
                                       zone_events=zone_events, tamper_status=tamper_status)
                    c["night"] = nr["night"]           # real boolean
                    c["motion"] = nr["motion"]         # safety-net boxes
                    c["plates"] = plates               # ⭐ A5: Populated ANPR plates!
                    c["faces"] = faces_data            # ⭐ Biometric FRS faces!
                    if faces_data and any(f.get("bolo") for f in faces_data):
                        c["threat_level"] = "CRITICAL"

                    annotated[cam_id] = draw(
                        frame.copy(), tracks, states[cam_id], st["name"],
                        st["fps"], st["connected"], TARGET_ANALYSIS_FPS,
                        night=nr["night"], motion=nr["motion"], plates=plates,
                        zone_events=zone_events, fence_manager=fence_manager,
                        show_zones=show_zones, tamper_status=tamper_status, faces=faces_data)

                    # Save live preview image for dashboard cards
                    try:
                        if "CAM-01" in st["name"]: tag = "cam1"
                        elif "CAM-02" in st["name"]: tag = "cam2"
                        elif "CAM-03" in st["name"]: tag = "cam3"
                        elif "CAM-04" in st["name"]: tag = "cam4"
                        elif "CAM-05" in st["name"]: tag = "cam5"
                        else: tag = "cam1"
                        live_snap = os.path.join(ROOT_DIR, "data", "snapshots", f"{tag}_live.jpg")
                        cv2.imwrite(live_snap, annotated[cam_id])
                        c["snapshot_url"] = f"/snapshots/{tag}_live.jpg"
                    except Exception:
                        pass

                    contracts[st["name"]] = c

                # Member B ke liye atomic state dump (dashboard isse poll karega)
                try:
                    tmp_state = STATE_PATH + ".tmp"
                    with open(tmp_state, "w") as f:
                        json.dump(contracts, f)
                    os.replace(tmp_state, STATE_PATH)
                except Exception:
                    pass

            # ---- DISPLAY (latest annotated frames) ----
            if not headless:
                curr_fps = tick_count / max(now - print_t0, 1e-3)
                if use_grid:
                    grid = build_tactical_grid(annotated, mgr, contracts, fake_night, simulated_hotlist,
                                               simulated_tamper, show_zones, curr_fps,
                                               user_points=user_points, drawing_cam=drawing_cam)
                    cv2.imshow(WIN_NAME, grid)
                else:
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

            if not headless:
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
                elif key == ord('c'):
                    if len(user_points) >= 3 and drawing_cam:
                        tz_path = os.path.join(ROOT_DIR, "data", "tactical_zones.json")
                        try:
                            with open(tz_path, "r") as f:
                                all_zones = json.load(f)
                        except Exception:
                            all_zones = {}
                        all_zones[drawing_cam] = [
                            {
                                "id": f"{drawing_cam[:5]}-CUSTOM-EXC",
                                "name": f"Custom Exclusion Fence ({drawing_cam[:6]})",
                                "type": "EXCLUSION_ZONE",
                                "severity": "CRITICAL",
                                "color": [0, 0, 240],
                                "points_norm": list(user_points)
                            }
                        ]
                        with open(tz_path, "w") as f:
                            json.dump(all_zones, f, indent=2)
                        fence_manager.reload()
                        print(f"🛡️ Custom fence ARMED for {drawing_cam} with {len(user_points)} points! ✅")
                        user_points = []
                        drawing_cam = None
                    else:
                        print("⚠️ Click at least 3 points on a camera tile first with mouse, then press 'c' to arm.")
                elif key == ord('r'):
                    if user_points:
                        user_points = []
                        drawing_cam = None
                        print("🔄 Cleared custom drawing points.")
                    else:
                        print("🔄 Ready to draw. Click any camera tile with mouse to draw a new fence.")
                elif key == ord('x'):
                    tz_path = os.path.join(ROOT_DIR, "data", "tactical_zones.json")
                    try:
                        with open(tz_path, "w") as f:
                            json.dump({}, f, indent=2)
                        fence_manager.reload()
                        user_points = []
                        drawing_cam = None
                        print("🗑️ ALL VIRTUAL FENCES WIPED! Screen is clean (0 fences). Ready to draw fresh with mouse! ✅")
                    except Exception as e:
                        print(f"❌ Error wiping zones: {e}")
                elif key == ord('p'):
                    preset_p = os.path.join(ROOT_DIR, "data", "tactical_zones_preset.json")
                    tz_path = os.path.join(ROOT_DIR, "data", "tactical_zones.json")
                    if os.path.exists(preset_p):
                        import shutil
                        shutil.copy(preset_p, tz_path)
                        fence_manager.reload()
                        print("🔄 Standard Tactical Border Presets RESTORED! ✅")
                elif key == ord('g'):
                    use_grid = not use_grid
                    cv2.destroyAllWindows()
                    print(f"🖥️ DISPLAY MODE: {'Unified 6-Split Tactical Grid' if use_grid else 'Individual Windows'}")
            else:
                time.sleep(0.005)
    except KeyboardInterrupt:
        pass
    finally:
        mgr.stop_all()
        if not headless:
            cv2.destroyAllWindows()
        print("Engine stopped cleanly. ✅")


if __name__ == "__main__":
    main()