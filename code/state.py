"""
state.py — Live state manager for IBVAP camera streams.

In a production deployment this module is fed by the CV pipeline
(YOLO tracker, ANPR, face recogniser, tamper detector). For the dashboard
it exposes the canonical state shape consumed by /api/state.

If data/engine_state.json exists and is active, snapshot() dynamically
serves real-time data from the CV pipeline; otherwise it falls back to
the deterministic seed payload below.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Dict

_ENGINE_STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "engine_state.json"

# Seed state — mirrors the canonical /api/state contract documented in
# the IBVAP build spec. Used as fallback when the CV engine is offline.
_SEED_STATE: Dict[str, Any] = {
    "CAM-01 (People)": {
        "ts": 1788861245.913,
        "stream_id": "CAM-01 (People)",
        "night": False,
        "fps": 5.0,
        "tracks": [
            {"tid": 196, "cls": "person", "conf": 0.9, "box": [180, 60, 299, 301], "age": 2.1, "speed": 51.1},
            {"tid": 200, "cls": "person", "conf": 0.91, "box": [468, 118, 605, 360], "age": 0.8, "speed": 56.7},
        ],
        "vehicles": {"car": 0, "truck": 0, "bus": 0, "motorcycle": 0, "bicycle": 0},
        "threat_level": "CRITICAL",
        "tamper": {
            "tampered": False,
            "type": "SECURE",
            "severity": "NORMAL",
            "message": "CAMERA SECURE",
            "metrics": {"laplacian_var": 1102.9, "std_dev": 45.1, "mean_lux": 111.7},
        },
        "zone_events": [
            {
                "zone_id": "CAM-0-CUSTOM-EXC",
                "zone_name": "Custom Exclusion Fence (CAM-01)",
                "zone_type": "EXCLUSION_ZONE",
                "track_id": 196,
                "cls": "person",
                "conf": 0.9,
                "box": [180, 60, 299, 301],
                "dwell_sec": 2.1,
                "aspect_ratio": 0.49,
                "posture": "UPRIGHT",
                "severity": "CRITICAL",
                "event_type": "PERIMETER_BREACH",
            }
        ],
        "faces": [],
        "plates": [],
        "motion": [
            [431, 304, 463, 334],
            [428, 257, 466, 287],
            [432, 92, 500, 228],
            [461, 75, 628, 373],
            [177, 58, 301, 315],
        ],
        "snapshot_url": "/snapshots/cam1_live.jpg",
    },
    "CAM-02 (Vehicles & ANPR)": {
        "ts": 1788861245.913,
        "stream_id": "CAM-02 (Vehicles & ANPR)",
        "night": False,
        "fps": 5.0,
        "tracks": [],
        "vehicles": {"car": 0, "truck": 0, "bus": 0, "motorcycle": 0, "bicycle": 0},
        "threat_level": "NORMAL",
        "tamper": {
            "tampered": False,
            "type": "SECURE",
            "severity": "NORMAL",
            "message": "CAMERA SECURE",
            "metrics": {"laplacian_var": 2926.1, "std_dev": 39.0, "mean_lux": 133.6},
        },
        "zone_events": [],
        "faces": [],
        "plates": [],
        "motion": [
            [573, 293, 640, 360],
            [0, 279, 54, 308],
            [568, 269, 601, 299],
            [601, 237, 640, 289],
            [570, 232, 600, 264],
            [513, 231, 569, 273],
            [491, 211, 521, 233],
            [167, 211, 190, 236],
            [609, 195, 640, 230],
            [370, 189, 397, 211],
            [549, 166, 573, 191],
            [261, 143, 293, 167],
            [319, 130, 339, 166],
            [0, 126, 79, 162],
            [353, 121, 386, 154],
            [291, 119, 314, 163],
            [77, 104, 95, 134],
            [112, 94, 150, 132],
            [61, 74, 93, 105],
            [340, 70, 396, 122],
            [293, 65, 330, 122],
            [0, 0, 640, 360],
        ],
        "snapshot_url": "/snapshots/cam2_live.jpg",
    },
    "CAM-03 (Night CCTV)": {
        "ts": 1788861245.913,
        "stream_id": "CAM-03 (Night CCTV)",
        "night": True,
        "fps": 5.0,
        "tracks": [],
        "vehicles": {"car": 0, "truck": 0, "bus": 0, "motorcycle": 0, "bicycle": 0},
        "threat_level": "NORMAL",
        "tamper": {
            "tampered": False,
            "type": "SECURE",
            "severity": "NORMAL",
            "message": "CAMERA SECURE",
            "metrics": {"laplacian_var": 3207.9, "std_dev": 54.9, "mean_lux": 30.1},
        },
        "zone_events": [],
        "faces": [],
        "plates": [],
        "motion": [
            [1004, 368, 1178, 451],
            [166, 314, 236, 383],
            [339, 311, 503, 387],
            [509, 141, 1488, 420],
        ],
        "snapshot_url": "/snapshots/cam3_live.jpg",
    },
    "CAM-04 (Thermal FLIR)": {
        "ts": 1788861245.913,
        "stream_id": "CAM-04 (Thermal FLIR)",
        "night": False,
        "fps": 5.0,
        "tracks": [],
        "vehicles": {"car": 0, "truck": 0, "bus": 0, "motorcycle": 0, "bicycle": 0},
        "threat_level": "NORMAL",
        "tamper": {
            "tampered": False,
            "type": "SECURE",
            "severity": "NORMAL",
            "message": "CAMERA SECURE",
            "metrics": {"laplacian_var": 659.8, "std_dev": 11.5, "mean_lux": 113.4},
        },
        "zone_events": [],
        "faces": [],
        "plates": [],
        "motion": [[549, 3, 596, 58]],
        "snapshot_url": "/snapshots/cam4_live.jpg",
    },
    "CAM-05 (Face Recognition)": {
        "ts": 1788861245.913,
        "stream_id": "CAM-05 (Face Recognition)",
        "night": False,
        "fps": 5.0,
        "tracks": [
            {"tid": 900, "cls": "person", "conf": 0.98, "box": [531, 78, 625, 217], "age": 84.2, "speed": 4.0},
            {"tid": 901, "cls": "person", "conf": 0.98, "box": [140, 101, 228, 222], "age": 84.2, "speed": 8.0},
        ],
        "vehicles": {"car": 0, "truck": 0, "bus": 0, "motorcycle": 0, "bicycle": 0},
        "threat_level": "CRITICAL",
        "tamper": {
            "tampered": False,
            "type": "SECURE",
            "severity": "NORMAL",
            "message": "CAMERA SECURE",
            "metrics": {"laplacian_var": 224.2, "std_dev": 49.3, "mean_lux": 111.8},
        },
        "zone_events": [
            {
                "zone_id": "CAM-0-CUSTOM-EXC",
                "zone_name": "Custom Exclusion Fence (CAM-05)",
                "zone_type": "EXCLUSION_ZONE",
                "track_id": 900,
                "cls": "person",
                "conf": 0.98,
                "box": [531, 78, 625, 217],
                "dwell_sec": 19.3,
                "aspect_ratio": 0.68,
                "posture": "UPRIGHT",
                "severity": "CRITICAL",
                "event_type": "PERIMETER_BREACH",
            },
            {
                "zone_id": "CAM-0-CUSTOM-EXC",
                "zone_name": "Custom Exclusion Fence (CAM-05)",
                "zone_type": "EXCLUSION_ZONE",
                "track_id": 901,
                "cls": "person",
                "conf": 0.98,
                "box": [140, 101, 228, 222],
                "dwell_sec": 22.8,
                "aspect_ratio": 0.73,
                "posture": "UPRIGHT",
                "severity": "CRITICAL",
                "event_type": "PERIMETER_BREACH",
            },
        ],
        "faces": [
            {"box": [531, 78, 94, 139], "name": "Suspect Tariq Ahmed (BOLO Watchlist)", "score": 0.98, "bolo": True},
            {"box": [140, 101, 88, 121], "name": "Suspect Tariq Ahmed (BOLO Watchlist)", "score": 0.98, "bolo": True},
        ],
        "plates": [],
        "motion": [],
        "snapshot_url": "/snapshots/cam5_live.jpg",
    },
}


class LiveState:
    """
    Thread-safe in-memory snapshot of all camera states.

    The CV pipeline writes to data/engine_state.json or calls .update(stream_name, payload);
    the dashboard calls .snapshot() to get the latest state.
    """

    def __init__(self, seed: Dict[str, Any] | None = None) -> None:
        self._lock = threading.RLock()
        self._state: Dict[str, Any] = dict(seed or _SEED_STATE)

    def snapshot(self) -> Dict[str, Any]:
        """Return a deep-ish copy of the full state.
        
        If data/engine_state.json exists and is active, dynamically reads from it;
        otherwise falls back to internal memory state.
        """
        if _ENGINE_STATE_PATH.exists():
            try:
                content = _ENGINE_STATE_PATH.read_text(encoding="utf-8").strip()
                if content:
                    data = json.loads(content)
                    if isinstance(data, dict) and len(data) > 0:
                        return data
            except Exception:
                pass

        with self._lock:
            return {k: dict(v) if isinstance(v, dict) else v for k, v in self._state.items()}

    def update(self, stream_name: str, payload: Dict[str, Any]) -> None:
        with self._lock:
            self._state[stream_name] = payload

    def set_all(self, state: Dict[str, Any]) -> None:
        with self._lock:
            self._state = dict(state)


# Singleton consumed by dashboard.py.
live_state = LiveState()
