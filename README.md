# IBVAP — Intelligent Border Video Analytics Platform
**SIH26187 | Ministry of Home Affairs (SSB) | Sector-7 Tactical Border Outpost (BOP)**

> Software-defined border surveillance platform converting legacy CCTV infrastructure into a real-time, AI-driven tactical intelligence network with Section 65B Indian Evidence Act certified forensic ledgers.

---

## 🛡️ Core Capabilities

| Capability | Module & Technology | Operational Description |
|:---|:---|:---|
| **Human Detection & Tracking** | YOLOv8n + ByteTrack | Multi-target persistent tracking with 40-point movement trajectories, speed calculation, and dwell monitoring. |
| **Prone & Crawling Detection** | Aspect-Ratio Invariant Analysis | Flags low-profile crawling / crouching perimeter breaches (`CRAWLING_PRONE`) vs upright walking. |
| **5-Class Vehicle Classification** | YOLOv8n Multi-Class | Categorizes border vehicles into **Car, Truck, Bus, Motorcycle, Bicycle** with entry event logging. |
| **Automatic Number Plate (ANPR)** | Fast-ALPR [ONNX] + Indian Parser | Automated license plate recognition with Indian state-code parsing and BOLO hotlist cross-referencing. |
| **Night Vision Enhancement** | Dual-Path CLAHE + MOG2 | 2AM Moonlight CCTV detection with adaptive histogram contrast enhancement and motion safety-net. |
| **Thermal FLIR Surveillance** | FLIR LWIR (8–14 µm) Simulation | Long-wave infrared heat signature surveillance in Inferno/Ironbow colormap with standoff boundary intrusion detection. |
| **Choke-Point Biometric FRS** | YuNet + SFace (OpenCV 100% On-Premise) | Facial recognition at border choke-points with cosine similarity matching against suspect BOLO watchlists. |
| **Interactive Virtual Fencing** | Dynamic Multi-Zone Polygon Engine | Custom polygon fences drawn directly on screen with mouse clicks (`[C]` Arm, `[R]` Clear, `[P]` Preset). |
| **Camera Anti-Tamper & Sabotage** | Multi-Metric Anomaly Detection | Detects lens blinding, spray-painting, defocus, and signal loss in real-time. |
| **Cryptographic Evidence Ledger** | SHA-256 Chained Blocks | Tamper-evident, hash-chained evidence ledger recording all intrusion snapshots and telemetry. |
| **Section 65B Legal Certificate** | Automated PDF Generation | One-click export of court-admissible electronic evidence certificates complying with Section 65B Indian Evidence Act. |

---

## 🚀 Quick Start Guide (For Any Laptop)

### 1. Clone & Install Dependencies
```bash
# Clone the repository
git clone https://github.com/Aayushraj2121/IBVAP-border-fensing.git
cd IBVAP-border-fensing

# Install required Python packages (Python 3.9+ recommended)
pip install -r requirements.txt
```

> **Note:** All 5 surveillance test video streams (`data/test_videos/*.mp4`) and neural network model weights (`models/*.pt`, `models/*.onnx`) are bundled directly inside this repository. **Zero external downloads required.**

---

### 2. Run the Unified 6-Split Tactical Command Grid
Launch all 5 cameras and tactical telemetry in a single synchronized 1440×720 window:
```bash
python3 code/engine.py
```

#### 🖥️ 6-Split Grid Layout:
```
+---------------------------+---------------------------+---------------------------+
| TILE 1: CAM-01 (People)   | TILE 2: CAM-02 (Vehicles) | TILE 3: CAM-03 (Night IR) |
| • Human Detection & Tracks| • 5-Class Vehicle Tracking| • Low-Light Moonlight     |
| • Crawling/Prone Detection| • Fast-ALPR Number Plates | • Dual-Path CLAHE Enhance |
| • Perimeter Fence Breach  | • Hotlist BOLO Matching   | • MOG2 Motion Safety-Net  |
+---------------------------+---------------------------+---------------------------+
| TILE 4: CAM-04 (Thermal)  | TILE 5: CAM-05 (Biometric)| TILE 6: Tactical C2 HUD   |
| • FLIR LWIR 8-14µm Inferno| • YuNet Face Detection    | • Multi-Stream AI FPS     |
| • Heat Signature Tracking | • SFace Watchlist Match   | • Sector Threat Telemetry |
| • Standoff Tripwire Alert | • Suspect BOLO Alert Seal | • SHA-256 Ledger & Keys   |
+---------------------------+---------------------------+---------------------------+
```

---

### 3. Run the Web Command Centre Dashboard (Optional / Simultaneous)
In a second terminal, start the Sector BOP Web Command Centre:
```bash
python3 code/dashboard.py
```
Open **[http://127.0.0.1:8000](http://127.0.0.1:8000)** in any browser to access:
* **Live 5-Camera Perception Feed** with real-time target bounding boxes, plates, and BOLO alerts.
* **2D Tactical BOP Mini-Map** featuring 5 interactive green/yellow/red radar FOV cones.
* **Tamper-Evident Evidence Ledger** with instantaneous snapshot archiving and SHA-256 hashes.
* **Section 65B Certificate Export** for judicial submission.

---

## 🎮 Keyboard & Mouse Controls (In Command Grid Window)

| Key / Action | Operation | Description |
|:---:|:---|:---|
| **Mouse Left-Click** | **Draw Custom Fence** | Click 3+ points on any camera tile to trace a custom exclusion fence |
| **`[C]`** | **Arm Custom Fence** | Locks and activates the custom drawn fence for perimeter breach detection |
| **`[R]`** | **Clear Points** | Clears in-progress drawing points or resets drawn fence |
| **`[P]`** | **Restore Preset** | Restores the default military tactical border zones |
| **`[Z]`** | **Toggle Zones** | Shows or hides virtual perimeter boundary overlays |
| **`[N]`** | **Toggle Fake Night** | Simulates 2AM pitch-dark moonlight to test CLAHE night enhancement |
| **`[H]`** | **Simulate Hotlist BOLO** | Injects suspect vehicle `HR26DQ5551` to trigger automated checkpoint alarm |
| **`[T]`** | **Simulate Tamper** | Simulates camera lens spray-paint / blinding on CAM-01 |
| **`[G]`** | **Toggle Display** | Switches between 6-Split Unified Grid and Individual Windows |
| **`[Q]`** | **Clean Quit** | Stops all stream capture threads and engines safely |

---

## 📁 Repository Structure

```
IBVAP-border-fensing/
├── code/
│   ├── engine.py           # Unified 6-Split Multi-Stream Perception & Tracking Engine
│   ├── dashboard.py        # FastAPI/HTML5 Web Command Centre & 2D Tactical Digital Twin
│   ├── streammanager.py    # Decoupled Multi-Threaded Low-Latency RTSP/File Ingestion
│   ├── fence.py            # Multi-Zone Virtual Fencing & Crawling Posture Engine
│   ├── anpr.py             # Automatic Number Plate Recognition & BOLO Hotlist Matcher
│   ├── night.py            # Dual-Path Night Vision Engine (CLAHE + MOG2 Anomaly)
│   ├── frs.py              # YuNet Face Detection + SFace Choke-Point Recognition
│   ├── tamper.py           # Camera Tamper, Blinding & Sabotage Detection Engine
│   └── ledger.py           # Tamper-Evident SHA-256 Cryptographic Evidence Ledger
├── data/
│   ├── test_videos/        # 8 High-Definition Realistic Surveillance Video Streams
│   ├── tactical_zones.json # Configured Standoff, Buffer & Exclusion Zones
│   ├── hotlist.json        # Suspect Vehicle Watchlist Database
│   ├── face_gallery.json   # Enrolled Suspect Biometric Face Embeddings
│   └── snapshots/          # Captured Forensic Evidence Snapshots (SHA-256 Hashed)
├── models/
│   ├── yolov8n.pt          # YOLOv8 Nano Object Detection Model Weights
│   ├── face_detection_yunet_2023mar.onnx
│   └── face_recognition_sface_2021dec.onnx
└── requirements.txt        # Turnkey Python Dependencies
```

---

## ⚖️ Compliance & Forensic Admissibility
Every intrusion snapshot captured by IBVAP is immediately hashed using **SHA-256** and appended to a forward-chained cryptographic ledger (`data/evidence_chain.jsonl`). Any alteration to historic images breaks the hash verification, ensuring complete compliance with **Section 65B of the Indian Evidence Act, 1872**.
