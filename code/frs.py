r"""
IBVAP - frs.py: Choke-Point Face Recognition (YuNet + SFace, 100% OpenCV)
Two modes:
  ENROLL:    python code/frs.py enroll "Name"     <- look at webcam, capture 5 faces
  RECOGNIZE: (imported by rule.py) match live faces vs watchlist
Watchlist:  data/face_gallery.json  (name -> [embeddings])
"""
import os, sys, json, time

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))

import cv2
import numpy as np

YUNET_PATH   = "models/face_detection_yunet_2023mar.onnx"
SFACE_PATH   = "models/face_recognition_sface_2021dec.onnx"
GALLERY_FILE = "data/face_gallery.json"
MATCH_THRESHOLD = 0.36          # OpenCV SFace standard: >=0.36 cosine = same person

_detector = None
_recognizer = None

def _models():
    """Lazy-load once."""
    global _detector, _recognizer
    if _detector is None:
        _detector = cv2.FaceDetectorYN.create(YUNET_PATH, "", (320, 320), 0.6)
    if _recognizer is None:
        _recognizer = cv2.FaceRecognizerSF.create(SFACE_PATH, "")
    return _detector, _recognizer

def detect_faces(frame):
    """Return list of (x, y, w, h) face boxes."""
    det, _ = _models()
    h, w = frame.shape[:2]
    det.setInputSize((w, h))
    _, faces = det.detect(frame)
    out = []
    if faces is not None:
        for f in faces:
            x, y, fw, fh = map(int, f[:4])
            out.append((x, y, fw, fh))
    return out

def get_embedding(frame, box):
    """Align (5-point) + 128-d embedding for one face box."""
    det, rec = _models()
    x, y, fw, fh = box
    fw, fh = max(fw, 2), max(fh, 2)
    det.setInputSize((frame.shape[1], frame.shape[0]))
    _, faces = det.detect(frame)
    if faces is not None:
        # pick the face closest to the requested box
        best = min(faces, key=lambda f: abs(int(f[0]) - x) + abs(int(f[1]) - y))
        aligned = frame.copy()
        emb = rec.feature(aligned, best)
        return emb.flatten()
    # fallback: crop-based embedding (less accurate)
    crop = frame[y:y+fh, x:x+fw]
    if crop.size == 0:
        return None
    crop = cv2.resize(crop, (112, 112))
    emb = rec.feature(crop)
    return emb.flatten() if emb is not None else None

def load_gallery():
    if os.path.exists(GALLERY_FILE):
        return json.load(open(GALLERY_FILE))
    return {}

def save_gallery(g):
    os.makedirs("data", exist_ok=True)
    json.dump(g, open(GALLERY_FILE, "w"), indent=2)

def match_faces(frame, boxes, gallery=None):
    """For each face box, return (box, best_name, best_score) or (box, None, score)."""
    g = gallery if gallery is not None else load_gallery()
    results = []
    for box in boxes:
        emb = get_embedding(frame, box)
        if emb is None:
            results.append((box, None, 0.0))
            continue
        best_name, best_score = None, -1.0
        for name, embs in g.items():
            for e in embs:
                e = np.array(e, dtype=np.float32)
                score = float(np.dot(emb, e) / (np.linalg.norm(emb) * np.linalg.norm(e) + 1e-9))
                if score > best_score:
                    best_name, best_score = name, score
        if best_name and best_score >= MATCH_THRESHOLD:
            results.append((box, best_name, best_score))
        else:
            results.append((box, None, max(best_score, 0.0)))
    return results

# ================= ENROLL CLI =================
def enroll():
    if len(sys.argv) < 3:
        print('Usage: python code/frs.py enroll "Full Name"')
        sys.exit(1)
    name = sys.argv[2]
    src = sys.argv[3] if len(sys.argv) > 3 else "0"

    if src.isdigit():
        idx = int(src)
        backend = cv2.CAP_DSHOW if sys.platform.startswith("win") else cv2.CAP_ANY
        cap = cv2.VideoCapture(idx, backend)
        if not cap.isOpened() and idx == 0 and sys.platform.startswith("win"):
            cap = cv2.VideoCapture(1, backend)
    else:
        cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        print("ERROR: cannot open source:", src); sys.exit(1)

    gallery = load_gallery()
    gallery.setdefault(name, [])
    captured = 0
    print(f"Enrolling '{name}' — look straight at the camera.")
    print("Move slightly (left/right/up/down) between captures. 'q' = finish early.")

    while captured < 5:
        ok, frame = cap.read()
        if not ok:
            break
        frame = cv2.resize(frame, (640, 480))
        boxes = detect_faces(frame)
        for (x, y, w, h) in boxes:
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
        cv2.putText(frame, f"Captured {captured}/5 — keep face in box", (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        cv2.imshow("FRS Enrollment - q finish", frame)
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        if boxes:
            emb = get_embedding(frame, boxes[0])
            if emb is not None:
                gallery[name].append([round(float(v), 4) for v in emb])
                captured += 1
                save_gallery(gallery)
                print(f"  captured embedding {captured}/5")
                time.sleep(1.0)          # give time to move slightly

    cap.release(); cv2.destroyAllWindows()
    print(f"✅ '{name}' enrolled with {captured} embeddings -> {GALLERY_FILE}")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "enroll":
        enroll()
    else:
        print(__doc__)