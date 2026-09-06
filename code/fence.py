"""
IBVAP — Tactical Multi-Zone Virtual Fencing & Crawling Intrusion Engine
Provides config-driven dynamic polygon zones (data/zones.json),
point-in-polygon containment testing, dwell time tracking,
and crawling/crouching posture detection.
"""

import os
import json
import time
import cv2
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.normpath(os.path.join(BASE_DIR, ".."))
DEFAULT_ZONES_PATH = os.path.join(ROOT_DIR, "data", "tactical_zones.json")
if not os.path.exists(DEFAULT_ZONES_PATH):
    DEFAULT_ZONES_PATH = os.path.join(ROOT_DIR, "data", "zones.json")


class VirtualFenceManager:
    """Manages multi-zone polygon virtual fencing per camera stream."""

    def __init__(self, zones_file: str = None):
        if zones_file is None:
            tactical = os.path.join(ROOT_DIR, "data", "tactical_zones.json")
            zones_file = tactical if os.path.exists(tactical) else os.path.join(ROOT_DIR, "data", "zones.json")
        self.zones_file = zones_file
        self.last_mtime = 0
        self.zones_by_stream = {}
        self.dwell_times = {}  # (stream_id, tid, zone_id) -> enter_ts
        self.reload()

    def reload(self):
        """Loads or reloads zone definitions from JSON."""
        if os.path.exists(self.zones_file):
            try:
                mtime = os.path.getmtime(self.zones_file)
                if mtime != self.last_mtime:
                    with open(self.zones_file, "r") as f:
                        self.zones_by_stream = json.load(f)
                    self.last_mtime = mtime
            except Exception as e:
                print(f"⚠️ Failed to load {self.zones_file}: {e}")
        else:
            self.zones_by_stream = {}

    def get_zones_for_stream(self, stream_name: str, width: int, height: int) -> list[dict]:
        """Returns pixel-scaled polygons and metadata for a specific stream."""
        self.reload()  # Hot-reload if file touched
        if isinstance(self.zones_by_stream, dict):
            raw_zones = self.zones_by_stream.get(stream_name, [])
            if not raw_zones:
                # Fallback: match by prefix (e.g. CAM-01)
                for k, v in self.zones_by_stream.items():
                    if k.split()[0] in stream_name and isinstance(v, list):
                        raw_zones = v
                        break
        elif isinstance(self.zones_by_stream, list):
            raw_zones = self.zones_by_stream
        else:
            raw_zones = []

        scaled_zones = []
        for rz in raw_zones:
            pts = rz.get("points_norm") or rz.get("points", [])
            if len(pts) < 3:
                continue
            is_norm = any(isinstance(p[0], float) and p[0] <= 1.0 for p in pts)
            if is_norm:
                poly_px = np.array(
                    [[int(x * width), int(y * height)] for (x, y) in pts],
                    dtype=np.int32
                )
            else:
                poly_px = np.array(pts, dtype=np.int32)
            scaled_zones.append({
                "id": rz.get("id", rz.get("name", "ZONE")),
                "name": rz.get("name", "Tactical Zone"),
                "type": rz.get("type", "BUFFER_ZONE"),
                "severity": rz.get("severity", "WARNING"),
                "color": tuple(rz.get("color", [0, 200, 255])),
                "poly": poly_px,
                "poly_norm": pts,
            })
        return scaled_zones

    def evaluate_tracks(
        self,
        stream_name: str,
        tracks: list[dict],
        frame_shape: tuple,
        now: float
    ) -> list[dict]:
        """Evaluates all active tracks against stream virtual zones.
        Returns active breach and warning events with posture & dwell analysis.
        """
        h, w = frame_shape[:2]
        zones = self.get_zones_for_stream(stream_name, w, h)
        if not zones:
            return []

        events = []
        for t in tracks:
            tid = t["tid"]
            cls_name = t["cls"]
            conf = t["conf"]
            x1, y1, x2, y2 = t["box"]
            bw = max(1, x2 - x1)
            bh = max(1, y2 - y1)
            aspect_ratio = round(bw / bh, 2)

            # Test using ground contact point (cx, y2) and centroid (cx, cy)
            cx = (x1 + x2) // 2
            cy = (y1 + y2) // 2
            ground_pt = (float(cx), float(y2))
            center_pt = (float(cx), float(cy))

            for z in zones:
                # cv2.pointPolygonTest returns > 0 (inside), 0 (edge), < 0 (outside)
                dist_ground = cv2.pointPolygonTest(z["poly"], ground_pt, False)
                dist_center = cv2.pointPolygonTest(z["poly"], center_pt, False)
                is_inside = (dist_ground >= 0) or (dist_center >= 0)

                dwell_key = (stream_name, tid, z["id"])
                if is_inside:
                    if dwell_key not in self.dwell_times:
                        self.dwell_times[dwell_key] = now
                    dwell_sec = round(now - self.dwell_times[dwell_key], 1)

                    # Crawling / Crouching detection logic:
                    # Normal standing person: bw / bh is 0.3 to 0.6
                    # Crawling / prone human: bw / bh > 1.15
                    is_crawling = (cls_name == "person" and aspect_ratio >= 1.15)
                    posture = "CRAWLING_PRONE" if is_crawling else "UPRIGHT"

                    # Event severity escalation
                    if z["type"] == "EXCLUSION_ZONE":
                        severity = "CRITICAL"
                        event_type = "PERIMETER_BREACH"
                    elif is_crawling:
                        severity = "CRITICAL"
                        event_type = "STEALTH_CRAWL_INTRUSION"
                    elif dwell_sec > 6.0:
                        severity = "HIGH"
                        event_type = "ZONE_LOITERING"
                    else:
                        severity = z["severity"]
                        event_type = "ZONE_ENCROACHMENT"

                    events.append({
                        "zone_id": z["id"],
                        "zone_name": z["name"],
                        "zone_type": z["type"],
                        "track_id": tid,
                        "cls": cls_name,
                        "conf": conf,
                        "box": [x1, y1, x2, y2],
                        "dwell_sec": dwell_sec,
                        "aspect_ratio": aspect_ratio,
                        "posture": posture,
                        "severity": severity,
                        "event_type": event_type
                    })
                else:
                    self.dwell_times.pop(dwell_key, None)

        return events

    def draw_zones(
        self,
        frame: np.ndarray,
        stream_name: str,
        active_events: list[dict] = None
    ) -> np.ndarray:
        """Renders tactical military HUD polygons on video frame."""
        h, w = frame.shape[:2]
        zones = self.get_zones_for_stream(stream_name, w, h)
        if not zones:
            return frame

        overlay = frame.copy()
        breached_zones = {e["zone_id"] for e in (active_events or []) if e["severity"] == "CRITICAL"}

        for z in zones:
            poly = z["poly"]
            color = z["color"]
            is_breached = z["id"] in breached_zones

            # If breached, flash high-intensity red
            if is_breached:
                fill_color = (0, 0, 255)
                line_color = (0, 0, 255)
                alpha = 0.35
            else:
                fill_color = color
                line_color = color
                alpha = 0.18

            cv2.fillPoly(overlay, [poly], fill_color)
            cv2.polylines(frame, [poly], True, line_color, 2)

            # Zone label badge
            pts = poly.reshape(-1, 2)
            top_pt = pts[np.argmin(pts[:, 1])]
            bx, by = int(top_pt[0]), max(20, int(top_pt[1]) - 8)
            label = f"[{z['type']}] {z['name']}"
            if is_breached:
                label += " 🚨 BREACH ACTIVE!"

            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
            cv2.rectangle(frame, (bx - 2, by - th - 4), (bx + tw + 6, by + 2), (10, 15, 25), -1)
            cv2.rectangle(frame, (bx - 2, by - th - 4), (bx + tw + 6, by + 2), line_color, 1)
            text_color = (255, 255, 255) if is_breached else (220, 230, 255)
            cv2.putText(frame, label, (bx + 2, by - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.45, text_color, 1)

        # Blend semi-transparent polygon fills
        cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)
        return frame