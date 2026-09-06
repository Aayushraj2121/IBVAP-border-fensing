"""
IBVAP — Multi-Stream Video Manager (Member A / Perception Engine)
Threaded, auto-reconnecting capture for RTSP / files / webcams.
Supports FPS-paced smooth playback and seamless looping for video files.
Run from project root: python3 code/streammanager.py
Run from code/ folder: python3 streammanager.py
"""

import os
import cv2
import sys
import time
import threading
from collections import deque


# ---------------------------------------------------------------
# A1: CROSS-PLATFORM BACKEND FIX
# ---------------------------------------------------------------
def pick_backend(src):
    """Right OpenCV backend for any source + OS."""
    if isinstance(src, int) or (isinstance(src, str) and src.isdigit()):
        if sys.platform == "darwin":
            return cv2.CAP_AVFOUNDATION
        if sys.platform.startswith("linux"):
            return cv2.CAP_V4L2
        return cv2.CAP_DSHOW

    if isinstance(src, str) and (src.startswith("rtsp://") or src.startswith("http://")):
        return cv2.CAP_FFMPEG

    return cv2.CAP_ANY


# ---------------------------------------------------------------
# A2: THREADED SINGLE STREAM (one per camera, own thread)
# ---------------------------------------------------------------
class VideoStream:
    def __init__(self, src, cam_id, name=None, buffer_size=2, loop=True):
        self.src = int(src) if isinstance(src, str) and src.isdigit() else src
        self.cam_id = cam_id
        self.name = name or f"cam_{cam_id}"
        self.loop = loop
        self.is_file = isinstance(self.src, str) and os.path.isfile(self.src)
        self.buffer = deque(maxlen=buffer_size)
        self.lock = threading.Lock()
        self.running = True
        self.connected = False
        self._frames = 0
        self._t0 = time.time()
        # ⭐ FIX: instant-FPS tracking ke liye
        self._last_frames = 0
        self._last_ts = time.time()
        self._inst_fps = 0.0
        self.backend = pick_backend(self.src)
        threading.Thread(target=self._loop, daemon=True,
                         name=f"vs-{self.name}").start()

    def _loop(self):
        while self.running:
            cap = cv2.VideoCapture(self.src, self.backend)
            if not cap.isOpened():
                self.connected = False
                time.sleep(2)
                continue

            self.connected = True
            native_fps = cap.get(cv2.CAP_PROP_FPS)
            target_fps = native_fps if (native_fps and 1.0 <= native_fps <= 120.0) else 25.0
            frame_interval = 1.0 / target_fps
            last_frame_ts = time.time()

            while self.running:
                t_start = time.time()
                ok, frame = cap.read()

                if not ok:
                    if self.is_file and self.loop:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue
                    else:
                        self.connected = False
                        break

                last_frame_ts = time.time()
                if not self.connected:
                    self.connected = True

                with self.lock:
                    self.buffer.append(frame)
                    self._frames += 1

                if self.is_file:
                    elapsed = time.time() - t_start
                    delay = frame_interval - elapsed
                    if delay > 0:
                        time.sleep(delay)
                else:
                    if time.time() - last_frame_ts > 10:
                        self.connected = False
                        break

            cap.release()
            if self.running and not self.is_file:
                time.sleep(1)

    def read(self):
        """Latest frame (copy) or None. NEVER blocks the caller."""
        with self.lock:
            return self.buffer[-1].copy() if self.buffer else None

    def stats(self):
        """⭐ FIX: INSTANT fps (last ~1 sec ka real speed), + frames count."""
        now = time.time()
        with self.lock:
            f = self._frames
        dt = now - self._last_ts
        if dt >= 1.0:                          # har 1 sec me refresh
            self._inst_fps = (f - self._last_frames) / dt
            self._last_frames, self._last_ts = f, now
        return {"cam_id": self.cam_id, "name": self.name,
                "connected": self.connected,
                "frames": f, "fps": round(self._inst_fps, 1)}

    def stop(self):
        self.running = False


# ---------------------------------------------------------------
# A3: MANAGER (add N cameras, read any of them)
# ---------------------------------------------------------------
class StreamManager:
    def __init__(self):
        self.streams = {}

    def add(self, src, cam_id=None, name=None, loop=True):
        if cam_id is None:
            cam_id = max(self.streams.keys(), default=-1) + 1
        self.streams[cam_id] = VideoStream(src, cam_id, name, loop=loop)
        return cam_id

    def read(self, cam_id):
        s = self.streams.get(cam_id)
        return s.read() if s else None

    def all_stats(self):
        return [s.stats() for s in self.streams.values()]

    def stop_all(self):
        for s in self.streams.values():
            s.stop()


# ---------------------------------------------------------------
# STANDALONE TEST — run:  python code/streammanager.py
# ---------------------------------------------------------------
if __name__ == "__main__":
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    VIDEO_DIR = os.path.normpath(os.path.join(BASE_DIR, "..", "data", "test_videos"))

    SOURCES = [
        {"src": os.path.join(VIDEO_DIR, "people-detection.mp4"), "name": "cam_1 (People)"},
        {"src": os.path.join(VIDEO_DIR, "person-bicycle-car-detection.mp4"), "name": "cam_2 (Multi-Class)"},
    ]

    missing = [s["src"] for s in SOURCES
               if isinstance(s["src"], str) and not os.path.exists(s["src"])]
    if missing:
        for m in missing:
            print(f"❌ VIDEO NAHI MILI: {m}")
        print("👉 File ko data/test_videos folder me daalo ya spelling check karo.")
        sys.exit(1)

    mgr = StreamManager()
    for s in SOURCES:
        mgr.add(s["src"], name=s["name"])

    print("=" * 65)
    print("  IBVAP - Multi-Stream Video Manager Initialized")
    print("=" * 65)
    print("Active Streams:", [s["name"] for s in SOURCES])
    print("Controls      : Press 'q' on any video window to exit")
    print("=" * 65)

    # ⭐ FIX: stats printer timers
    last_print = time.time()

    try:
        while True:
            for cam_id, stream in mgr.streams.items():
                frame = stream.read()
                if frame is not None:
                    st = stream.stats()   # ⭐ FIX: ek baar stats nikalo
                    status = "LIVE" if st["connected"] else "DOWN"
                    # ⭐ FIX: overlay me ab FPS bhi dikhega
                    cv2.putText(frame, f"{stream.name} | {status} | {st['fps']} fps",
                                (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                                (0, 255, 0) if st["connected"] else (0, 0, 255), 2)
                    cv2.imshow(stream.name, frame)

            # ⭐ FIX: har 2 sec me console me stats print
            if time.time() - last_print >= 2:
                print(" | ".join(
                    f"{s['name']}: {'LIVE' if s['connected'] else 'DOWN'} "
                    f"fps={s['fps']} frames={s['frames']}"
                    for s in mgr.all_stats()))
                last_print = time.time()

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
    finally:
        mgr.stop_all()
        cv2.destroyAllWindows()