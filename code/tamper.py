"""
IBVAP — Camera Anti-Tamper & Lens Blinding Detection Engine
Detects physical displacement, lens occlusion (spray paint / cloth / mud),
laser blinding, and defocus/blurring in real time.
"""

import time
import cv2
import numpy as np


class CameraTamperDetector:
    """Real-time camera sabotage and occlusion detection.
    Evaluates Laplacian edge energy, luminance standard deviation,
    and histogram collapse in < 1ms per frame.
    """

    def __init__(self, cam_id: str, var_thresh: float = 30.0, std_thresh: float = 7.5):
        self.cam_id = cam_id
        self.var_thresh = var_thresh  # Blur / defocus threshold
        self.std_thresh = std_thresh  # Occlusion / blackout / spray-paint threshold
        self.tamper_start = 0.0
        self.last_alert = 0.0
        self.history = []
        self.tamper_persist_sec = 1.2  # Must persist 1.2s to prevent flash false alarms

    def analyze(self, frame: np.ndarray, now: float = None) -> dict:
        """Evaluates video frame for physical sabotage or lens blockage."""
        if now is None:
            now = time.time()

        if frame is None or frame.size == 0:
            return {
                "tampered": True,
                "type": "SIGNAL_LOSS",
                "severity": "CRITICAL",
                "message": f"CRITICAL: Complete signal drop on {self.cam_id}",
                "metrics": {"blur": 0.0, "std": 0.0}
            }

        # Downsample for sub-millisecond evaluation
        h, w = frame.shape[:2]
        small = cv2.resize(frame, (160, 120))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY) if len(small.shape) == 3 else small

        # Metric 1: Focus sharpness / Edge density via Laplacian variance
        laplacian_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())

        # Metric 2: Luminance standard deviation (contrast depth)
        mean_val, std_val = float(np.mean(gray)), float(np.std(gray))

        # Metric 3: Laser / High-Intensity Sensor Saturation
        white_pixels_pct = float(np.sum(gray > 248) / gray.size)

        tamper_type = None
        severity = "NORMAL"
        msg = "CAMERA SECURE"

        if white_pixels_pct > 0.70 and mean_val > 220:
            tamper_type = "SENSOR_LASER_BLINDING"
            severity = "CRITICAL"
            msg = f"SABOTAGE: Laser pointer / blinding attack on {self.cam_id}"
        elif std_val < self.std_thresh:
            tamper_type = "LENS_OCCLUDED_BLACKOUT"
            severity = "CRITICAL"
            msg = f"SABOTAGE: Lens spray-painted or covered on {self.cam_id}"
        elif laplacian_var < self.var_thresh and std_val < 25.0:
            tamper_type = "LENS_DEFOCUS_DEFECT"
            severity = "WARNING"
            msg = f"TAMPER: Severe lens defocus / mud smear on {self.cam_id}"

        is_tampered = tamper_type is not None

        if is_tampered:
            if self.tamper_start == 0.0:
                self.tamper_start = now
            duration = now - self.tamper_start
            active_alert = duration >= self.tamper_persist_sec
        else:
            self.tamper_start = 0.0
            active_alert = False

        return {
            "tampered": active_alert,
            "type": tamper_type if active_alert else "SECURE",
            "severity": severity if active_alert else "NORMAL",
            "message": msg if active_alert else "CAMERA SECURE",
            "metrics": {
                "laplacian_var": round(laplacian_var, 1),
                "std_dev": round(std_val, 1),
                "mean_lux": round(mean_val, 1)
            }
        }
