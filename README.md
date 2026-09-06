# IBVAP - Intelligent Border Video Analytics Platform
SIH26187 | Ministry of Home Affairs (SSB)
Software that turns existing CCTV into intelligent border surveillance.

## Features
- Human/vehicle detection & tracking (YOLOv8 + ByteTrack)
- Virtual fence intrusion detection
- Suspicious activity scoring (time + place + behavior)
- Night-time detection (low-light enhancement)
- Tamper-evident evidence ledger (SHA-256 hash chain)

## Setup
pip install -r requirements.txt
python code/live.py 0
