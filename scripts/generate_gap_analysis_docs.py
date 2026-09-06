"""
Comprehensive Script to generate:
1. IBVAP_Gap_Analysis_and_Feature_Roadmap.docx (Microsoft Word Document)
2. IBVAP_Gap_Analysis_and_Feature_Roadmap.pdf (Defense-grade styled PDF)

Author: Antigravity AI Senior Defense CV/ML Architect
Date: September 2026
"""

import os
import sys
import datetime
import docx
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, HRFlowable
)
from reportlab.pdfgen import canvas

# ==============================================================================
# 1. WORD DOCUMENT GENERATION (.DOCX)
# ==============================================================================

def set_cell_background(cell, fill_hex):
    """Set the background color of a docx table cell."""
    tcPr = cell._tc.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>')
    tcPr.append(shd)

def set_cell_margins(cell, top=100, bottom=100, left=150, right=150):
    """Set cell padding in twips."""
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = OxmlElement('w:tcMar')
    for m, val in [('top', top), ('bottom', bottom), ('left', left), ('right', right)]:
        node = OxmlElement(f'w:{m}')
        node.set(qn('w:w'), str(val))
        node.set(qn('w:type'), 'dxa')
        tcMar.append(node)
    tcPr.append(tcMar)

def add_callout(doc, text, title="KEY ARCHITECTURAL DIRECTIVE", border_color="0284C7", bg_color="F0F9FF"):
    """Adds a defense styled callout box in Word."""
    tbl = doc.add_table(rows=1, cols=1)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.autofit = False
    cell = tbl.cell(0, 0)
    cell.width = Inches(7.0)
    set_cell_background(cell, bg_color)
    set_cell_margins(cell, top=120, bottom=120, left=180, right=180)
    
    # Left border only
    tcPr = cell._tc.get_or_add_tcPr()
    tcBorders = parse_xml(
        f'<w:tcBorders {nsdecls("w")}>'
        f'<w:left w:val="single" w:sz="24" w:space="0" w:color="{border_color}"/>'
        f'<w:top w:val="none"/>'
        f'<w:right w:val="none"/>'
        f'<w:bottom w:val="none"/>'
        f'</w:tcBorders>'
    )
    tcPr.append(tcBorders)
    
    p = cell.paragraphs[0]
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(2)
    run_t = p.add_run(f"[{title}] ")
    run_t.bold = True
    run_t.font.name = 'Segoe UI'
    run_t.font.size = Pt(9.5)
    run_t.font.color.rgb = RGBColor(15, 37, 55)
    
    run_body = p.add_run(text)
    run_body.font.name = 'Segoe UI'
    run_body.font.size = Pt(9)
    run_body.font.color.rgb = RGBColor(51, 65, 85)
    doc.add_paragraph()

def style_table(table, col_widths, header_bg="0F2537", alt_bg="F8FAFC"):
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, row in enumerate(table.rows):
        trPr = row._tr.get_or_add_trPr()
        trPr.append(OxmlElement('w:cantSplit'))
        if i == 0:
            trPr.append(OxmlElement('w:tblHeader'))
            for j, cell in enumerate(row.cells):
                cell.width = col_widths[j]
                set_cell_background(cell, header_bg)
                set_cell_margins(cell, top=120, bottom=120, left=120, right=120)
                cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
                for p in cell.paragraphs:
                    p.paragraph_format.space_before = Pt(2)
                    p.paragraph_format.space_after = Pt(2)
                    for r in p.runs:
                        r.font.bold = True
                        r.font.name = 'Segoe UI'
                        r.font.size = Pt(8.5)
                        r.font.color.rgb = RGBColor(255, 255, 255)
        else:
            bg = alt_bg if i % 2 == 1 else "FFFFFF"
            for j, cell in enumerate(row.cells):
                cell.width = col_widths[j]
                set_cell_background(cell, bg)
                set_cell_margins(cell, top=80, bottom=80, left=100, right=100)
                cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
                for p in cell.paragraphs:
                    p.paragraph_format.space_before = Pt(2)
                    p.paragraph_format.space_after = Pt(2)
                    for r in p.runs:
                        r.font.name = 'Segoe UI'
                        r.font.size = Pt(8)
                        r.font.color.rgb = RGBColor(30, 41, 59)


def generate_word_document(filepath):
    doc = Document()
    
    # 0.75 in margins
    for section in doc.sections:
        section.top_margin = Inches(0.75)
        section.bottom_margin = Inches(0.75)
        section.left_margin = Inches(0.75)
        section.right_margin = Inches(0.75)
        
        # Header / Footer
        header = section.header
        hp = header.paragraphs[0]
        hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        hrun = hp.add_run("IBVAP · MHA/BSF Problem Statement Deep-Dive & Gap Analysis Report")
        hrun.font.name = 'Segoe UI'
        hrun.font.size = Pt(8)
        hrun.font.color.rgb = RGBColor(148, 163, 184)
        
        footer = section.footer
        fp = footer.paragraphs[0]
        fp.alignment = WD_ALIGN_PARAGRAPH.LEFT
        frun = fp.add_run("CONFIDENTIAL & DEFENSE AUDIT READY | Smart India Hackathon | SSB/BSF Border Surveillance")
        frun.font.name = 'Segoe UI'
        frun.font.size = Pt(8)
        frun.font.color.rgb = RGBColor(148, 163, 184)

    # Styles
    styles = doc.styles
    normal_style = styles['Normal']
    normal_style.font.name = 'Segoe UI'
    normal_style.font.size = Pt(10)
    normal_style.font.color.rgb = RGBColor(30, 41, 59)
    normal_style.paragraph_format.space_after = Pt(6)
    normal_style.paragraph_format.line_spacing = 1.15

    # Title Block
    title_p = doc.add_paragraph()
    title_p.paragraph_format.space_before = Pt(0)
    title_p.paragraph_format.space_after = Pt(2)
    run_sub = title_p.add_run("MINISTRY OF HOME AFFAIRS (MHA) · BORDER SECURITY FORCES (BSF / SSB)\n")
    run_sub.font.name = 'Segoe UI'
    run_sub.font.size = Pt(9.5)
    run_sub.font.bold = True
    run_sub.font.color.rgb = RGBColor(2, 132, 199)

    run_title = title_p.add_run("INTELLIGENT BORDER VIDEO ANALYTICS PLATFORM (IBVAP)\n")
    run_title.font.name = 'Segoe UI'
    run_title.font.size = Pt(18)
    run_title.font.bold = True
    run_title.font.color.rgb = RGBColor(15, 37, 55)

    run_sub2 = title_p.add_run("Comprehensive Codebase Audit, Judge Requirement Gap Analysis, and Feature Addition Roadmap")
    run_sub2.font.name = 'Segoe UI'
    run_sub2.font.size = Pt(11)
    run_sub2.font.color.rgb = RGBColor(71, 85, 105)

    # Meta Table
    meta_table = doc.add_table(rows=2, cols=4)
    meta_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    meta_data = [
        [("Platform Version", "v0.6 (Prototype Baseline)"), ("Target Domain", "MHA / CAPF / BSF BOPs"), ("Evaluation Stage", "Hackathon Finale (36-hr)"), ("Architecture", "Edge AI (100% On-Prem)")],
        [("Primary Model", "YOLOv8n + ByteTrack"), ("Tamper Defense", "SHA-256 Ledger + Anchor"), ("Report Date", datetime.datetime.now().strftime("%B %d, %Y")), ("Verdict", "Yellow → Green Acceleration")]
    ]
    for r_idx, row in enumerate(meta_table.rows):
        for c_idx, cell in enumerate(row.cells):
            lbl, val = meta_data[r_idx][c_idx]
            cell.width = Inches(1.75)
            set_cell_background(cell, "F1F5F9")
            set_cell_margins(cell, top=60, bottom=60, left=80, right=80)
            p = cell.paragraphs[0]
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(0)
            r1 = p.add_run(f"{lbl}: ")
            r1.font.size = Pt(7.5)
            r1.font.bold = True
            r1.font.color.rgb = RGBColor(100, 116, 139)
            r2 = p.add_run(val)
            r2.font.size = Pt(8)
            r2.font.bold = True
            r2.font.color.rgb = RGBColor(15, 23, 42)
    doc.add_paragraph()

    add_callout(
        doc,
        "The primary mandate of this evaluation is transforming existing, legacy analog/IP CCTV cameras along thousands of kilometers of Indian international border into an autonomous, proactive sensor grid without procurement of proprietary smart cameras or recurring cloud subscriptions. This document establishes an engineering blueprint to eliminate critical codebase gaps and secure maximum points under Defence Evaluator criteria.",
        title="EXECUTIVE MISSION STATEMENT",
        border_color="0284C7",
        bg_color="F0F9FF"
    )

    # 1. EXECUTIVE SUMMARY
    h1 = doc.add_paragraph()
    h1.paragraph_format.space_before = Pt(14)
    h1.paragraph_format.space_after = Pt(4)
    r = h1.add_run("1. Executive Summary & Strategic Context")
    r.font.size = Pt(14)
    r.font.bold = True
    r.font.color.rgb = RGBColor(15, 37, 55)

    doc.add_paragraph(
        "Border Out Posts (BOPs) operated by the Border Security Force (BSF), Sashastra Seema Bal (SSB), and Indo-Tibetan Border Police (ITBP) operate thousands of legacy fixed and PTZ cameras. However, the surveillance paradigm remains entirely reactive: security personnel face rapid human vigilance collapse after just 20 to 30 minutes of continuous monitoring. Consequently, perimeter intrusions, cattle rustling, narcotics drops via low-flying drones, and cross-border loitering are discovered post-facto via tedious forensic footage scrubbing."
    )
    doc.add_paragraph(
        "Hardware-replacement proposals (e.g., procurement of thermal/optical smart cameras with built-in NPUs) present prohibitive capital expenditure: approximately Rs. 80,000 to Rs. 2,00,000+ per camera unit. Across a single border sector comprising 1,000 cameras, hardware upgrades demand Rs. 8 to Rs. 20 Crores, alongside supply-chain security risks stemming from foreign/Chinese OEM chipsets."
    )
    doc.add_paragraph(
        "IBVAP (Intelligent Border Video Analytics Platform) answers this crisis by introducing a pure software edge-AI gateway. By intercepting existing RTSP/ONVIF video feeds over the local BOP Ethernet switch and processing streams on a single localized industrial edge GPU server (Rs. 2.0 to 2.5 Lakhs per 10-16 camera cluster), IBVAP delivers real-time detection, virtual-fence intrusion monitoring, explainable suspicion scoring, anti-fatigue alert triage, and cryptographically tamper-evident evidence logging."
    )

    # 2. AUDIT OF CURRENT CODEBASE
    h1 = doc.add_paragraph()
    h1.paragraph_format.space_before = Pt(14)
    h1.paragraph_format.space_after = Pt(4)
    r = h1.add_run("2. Forensic Audit of Current Codebase (v0.6 Baseline)")
    r.font.size = Pt(14)
    r.font.bold = True
    r.font.color.rgb = RGBColor(15, 37, 55)

    doc.add_paragraph(
        "The repository currently reflects rapid prototype development across 6 sequential milestones (Day 1 through Day 6). The following file-by-file audit analyzes architectural strengths and immediate technical vulnerabilities:"
    )

    audit_table = doc.add_table(rows=7, cols=4)
    audit_widths = [Inches(1.3), Inches(1.9), Inches(1.9), Inches(1.9)]
    audit_data = [
        ["Module / File", "Functional Implementation", "Current Architectural Strengths", "Critical Gaps & Vulnerabilities"],
        [
            "code/live.py (Day 1)",
            "Single-stream YOLOv8n object detection via OpenCV loop.",
            "Minimalist CPU inference pipeline; downsamples to 320x320 for speed (~15-20 FPS on CPU).",
            "CRITICAL BUG: Hardcodes cv2.CAP_DSHOW and int(src)+1. Fails immediately on macOS and Linux. Synchronous loop blocks on frame drops."
        ],
        [
            "code/track.py (Day 2)",
            "YOLOv8 + ByteTrack integration with persistent tracking IDs.",
            "Maintains 40-point historical trails; estimates smoothed pixel velocity; calculates track age for loitering.",
            "Pure 2D pixel speed has no real-world perspective calibration. Track memory purge is naive (unseen for >10s)."
        ],
        [
            "code/fence.py (Day 3)",
            "Interactive polygon virtual fence drawing via OpenCV window clicks.",
            "Sub-millisecond polygon hit testing via cv2.pointPolygonTest; state transition tripwire logic.",
            "STRESS-TEST VULNERABILITY: Zone is drawn on an OpenCV window; lost on script restart; cannot be edited from Web UI; supports only 1 zone."
        ],
        [
            "code/rule.py (Day 4/5)",
            "Integrated pipeline: Tracking, virtual fence, rule scoring engine, night mode, ledger.",
            "Explainable point breakdown; two-tier cooldown (8s per-track, 3s global); automatic COCO animal suppression.",
            "Single threaded; night mode relies on mean frame brightness; lacks image enhancement (CLAHE/Zero-DCE); no motion-gated fallback."
        ],
        [
            "code/ledger.py (Day 5)",
            "Tamper-evident SHA-256 hash-chain evidence ledger and anchor system.",
            "OUTSTANDING DEFENSE USP: Canonical JSON hashing, image binary hashing, verification CLI, anchor file anti-truncation.",
            "Chain is stored in flat JSONL file. Lacks exportable PDF legal audit certificate complying with Section 65B of Indian Evidence Act."
        ],
        [
            "code/dashboard.py (Day 6)",
            "FastAPI command center dashboard with tactical dark theme.",
            "Data-only polling (4s); live ledger integrity badge; audio alerts; severity filters; lightbox snapshot viewer.",
            "High Latency: Polling instead of WebSockets; snapshots only—no live video canvas stream; no dynamic zone drawing; no BOP tactical map."
        ]
    ]
    for i, row in enumerate(audit_table.rows):
        for j, cell in enumerate(row.cells):
            cell.text = audit_data[i][j]
    style_table(audit_table, audit_widths)
    doc.add_paragraph()

    # 3. REQUIREMENT VS CODEBASE GAP MATRIX
    h1 = doc.add_paragraph()
    h1.paragraph_format.space_before = Pt(14)
    h1.paragraph_format.space_after = Pt(4)
    r = h1.add_run("3. Requirement vs. Codebase Gap Matrix (MHA / BSF Scoring Criteria)")
    r.font.size = Pt(14)
    r.font.bold = True
    r.font.color.rgb = RGBColor(15, 37, 55)

    gap_table = doc.add_table(rows=13, cols=5)
    gap_widths = [Inches(1.4), Inches(1.4), Inches(1.4), Inches(1.1), Inches(1.7)]
    gap_data = [
        ["PS Capability Requirement", "Evaluator Expectations", "Current State (v0.6)", "Gap Severity", "Required Action for Victory"],
        [
            "Multi-Camera RTSP Stream Ingestion",
            "Simultaneous ingestion of 8-12 legacy RTSP streams; auto-reconnect on dropped frames; local RTSP simulator.",
            "Single-camera synchronous cv2.VideoCapture loop; crashes on platform backend mismatch.",
            "CRITICAL (Red)",
            "Build Threaded RTSP Stream Manager with ring buffers, automatic reconnection, and MediaMTX multi-stream harness."
        ],
        [
            "Human & Vehicle Classification",
            "Robust person detection; vehicle classification (trucks, 4x4, bikes); separation of livestock vs intruders.",
            "YOLOv8n default COCO classes. Animals suppressed. Vehicles lumped into general bounding boxes.",
            "MODERATE (Amber)",
            "Elevate vehicle attributes (loitering vehicles near perimeter) and fine-tune thresholding."
        ],
        [
            "Dynamic Virtual Fence & Zones",
            "Multi-zone config stored in DB/JSON; dynamic drawing on web UI at runtime without code restart.",
            "OpenCV click-window; hardcoded single polygon; erased upon script termination.",
            "CRITICAL (Red)",
            "Web-based HTML5 Canvas polygon drawer saving to zones.json via FastAPI REST endpoints."
        ],
        [
            "Choke-Point Face Recognition (FRS)",
            "Gate scenario (5-10m); face detection + ArcFace embeddings; watchlist hotlist alerts; NIST FRVT pixel awareness.",
            "COMPLETELY ABSENT. Zero face detection or recognition modules in repository.",
            "MAJOR (Red)",
            "Implement Choke-Point FRS module with RetinaFace/YuNet + MobileFaceNet gallery matching and DPDP Act compliance."
        ],
        [
            "Automatic Number Plate Recognition (ANPR)",
            "Vehicle entry logging at BOP gates; Indian license plate OCR (PaddleOCR/fast-plate-ocr); hotlist matching.",
            "COMPLETELY ABSENT. No plate localization, OCR, or vehicle registration logs.",
            "MAJOR (Red)",
            "Deploy YOLO plate detector + PaddleOCR with Indian registration syntax regex parser."
        ],
        [
            "Night / Adverse Weather Vision",
            "IR monochrome noise suppression; low-light enhancement (CLAHE/Zero-DCE); motion-gated fallback when YOLO conf drops.",
            "Naive frame mean brightness check (brightness < 35); adds +25 points to score. No image enhancement.",
            "HIGH (Amber)",
            "Dual-Path Night Pipeline: CLAHE contrast booster + MOG2 motion-differencing safety net for pitch-black footage."
        ],
        [
            "Suspicious Activity & Loitering",
            "Loitering dwell time; crawling/crouching (aspect ratio + crawling speed); directional vectors toward fence.",
            "Heuristic rules for dwell (>8s), slow/fast speed, and group count (>=2).",
            "LOW/MODERATE (Green)",
            "Add crawling detection (bbox w/h > 1.2 at fence) and directional velocity vector dot-product."
        ],
        [
            "Anti-Fatigue Alert Triage",
            "Deduplication (1 alert per intrusion episode); priority ranking; <5 actionable alerts/camera/day.",
            "Two-tier cooldown (8s per track, 3s global); animal suppression; severity categories.",
            "COMPLIANT (Green)",
            "Expose alert suppression metrics on UI to prove anti-fatigue efficacy to defence judges."
        ],
        [
            "Evidence Ledger & Chain of Custody",
            "SHA-256 hash chaining of metadata + image bytes; external anchor; proof against internal tampering.",
            "Fully implemented in code/ledger.py. Built-in tamper detection demo.",
            "EXCELLENT (Green)",
            "Add exportable Section 65B Indian Evidence Act / BSA 2023 tamper-verification PDF certificate."
        ],
        [
            "Command & Control (C2) Integration",
            "Standardized REST/Webhook API for external VMS / Dial-112 / Sector HQ; OpenAPI schema; event push.",
            "Basic /api/state GET endpoint for frontend dashboard.",
            "MODERATE (Amber)",
            "Add outgoing Webhook dispatcher and formal Swagger/OpenAPI documentation page at /docs."
        ],
        [
            "Tactical Web Dashboard & UI",
            "Live streaming video grid; interactive zone editing; BOP digital twin 2D map with alert pins.",
            "Static snapshot feed with 4s polling; no live video stream; no zone editing; no map.",
            "HIGH (Amber)",
            "Modernize dashboard: MJPEG live video feed, interactive zone drawing canvas, and 2D BOP tactical map."
        ],
        [
            "Edge Deployment & Air-Gap Realism",
            "100% on-premise; zero external cloud API dependencies; runs fully offline on standard laptop or edge server.",
            "Runs locally with PyTorch. No cloud APIs called.",
            "COMPLIANT (Green)",
            "Package into air-gapped Docker Compose stack; document exact TensorRT INT8 GPU capacity plan."
        ]
    ]
    for i, row in enumerate(gap_table.rows):
        for j, cell in enumerate(row.cells):
            cell.text = gap_data[i][j]
    style_table(gap_table, gap_widths)
    doc.add_paragraph()

    # 4. JUDGE STRESS-TEST DEFENSE STRATEGY
    h1 = doc.add_paragraph()
    h1.paragraph_format.space_before = Pt(14)
    h1.paragraph_format.space_after = Pt(4)
    r = h1.add_run("4. Defense Evaluator Stress-Test & Vulnerability Pre-Emption")
    r.font.size = Pt(14)
    r.font.bold = True
    r.font.color.rgb = RGBColor(15, 37, 55)

    qa_table = doc.add_table(rows=6, cols=3)
    qa_widths = [Inches(1.8), Inches(2.2), Inches(3.0)]
    qa_data = [
        ["Stress-Test Question", "Evaluator's Hidden Trap", "Our Winning Engineering Response"],
        [
            "Q1: You claim 'no specialized hardware'—but you still need a GPU server. Isn't that the same capex burden?",
            "Testing if the team understands procurement mathematics vs per-unit hardware economics.",
            "Winning Counter: 'No, Sir. Commercial smart cameras cost Rs. 80,000 to Rs. 2,00,000 per unit multiplied by 1,000 cameras (Rs. 8 to 20 Crores). Our architecture clusters 10–16 cameras onto a single commercial edge GPU server (Rs. 2.5 Lakhs). That reduces capex by 25× to 50×. Furthermore, we decouple software from camera vendor lifecycles, eliminating Chinese OEM lock-in.'"
        ],
        [
            "Q2: Infiltration occurs at 02:00 AM under IR illumination. YOLO trained on COCO daylight fails completely. What happens?",
            "Exposing naive teams who run daytime models on pitch-black night footage.",
            "Winning Counter: 'We deploy a Dual-Path Night Engine. For low-light scenes, we run CLAHE adaptive contrast booster. Under zero-lux IR conditions where object features degrade, our Motion-Gated MOG2 fallback trips zone alarms even if neural confidence drops below 0.3. We alert on movement inside the exclusion zone first—identification is secondary to interdiction.'"
        ],
        [
            "Q3: Faces at 200 meters are 15 pixels wide. Is your Face Recognition claim science fiction?",
            "Detecting fraudulent FRS claims that violate basic optical diffraction and pixel density laws.",
            "Winning Counter: 'We scope FRS strictly to Choke-Point Gates (5–10 meters) where faces achieve 80–120 pixels, complying with NIST FRVT standards. At perimeter distances (50–300m), we do not attempt face recognition; instead, we deploy Appearance-Based Person Re-Identification (Re-ID) and trajectory tracking across camera corridors.'"
        ],
        [
            "Q4: Live Judge Challenge: 'Draw a new virtual fence on Camera 2 right now from your UI without editing code.'",
            "The fatal killer for hardcoded academic prototypes.",
            "Winning Counter: 'Demonstrated live in 5 seconds: Operator clicks 'Configure Zones' on the Web Dashboard, selects Camera 2, draws a 4-point polygon on the video canvas, names it 'Buffer Zone North', and clicks Save. The REST API persists it to zones.json, and the inference engine reloads zone coordinates dynamically in memory.'"
        ],
        [
            "Q5: Cattle and stray animals will generate 200 false alarms a night. How do you prevent alarm fatigue?",
            "Testing whether the system will be switched off by real BSF operators within 48 hours.",
            "Winning Counter: 'Our Explainable Rule Engine explicitly classifies COCO animal classes (cow, dog, sheep, bird) and routes them to low-priority background logging with zero operator alarm. Furthermore, tracking-ID cooldowns ensure that a human pacing inside a zone generates one consolidated event dossier, not 50 repeat alarms. Target: <5 actionable alarms/cam/day.'"
        ]
    ]
    for i, row in enumerate(qa_table.rows):
        for j, cell in enumerate(row.cells):
            cell.text = qa_data[i][j]
    style_table(qa_table, qa_widths)
    doc.add_paragraph()

    # 5. FEATURE ADDITION BLUEPRINT
    h1 = doc.add_paragraph()
    h1.paragraph_format.space_before = Pt(14)
    h1.paragraph_format.space_after = Pt(4)
    r = h1.add_run("5. Architectural Blueprint: Mandatory Feature Additions")
    r.font.size = Pt(14)
    r.font.bold = True
    r.font.color.rgb = RGBColor(15, 37, 55)

    features = [
        ("Feature 1: Multi-Stream RTSP Ingestion & Concurrency Engine",
         "Implement a dedicated VideoStreamManager using Python threading and multiprocessing. Decouple frame grabbing from model inference using double-buffered ring queues. Implement cross-platform backend detection (AVFoundation on macOS, V4L2 on Linux, DirectShow on Windows). Add keyframe decimation (sample at 6 FPS for detection while maintaining 25 FPS display) to allow a single RTX 3060/4060 or Apple Silicon M-series chip to concurrently process 8 to 12 streams."),
        
        ("Feature 2: Config-Driven Dynamic Web Polygon Fence Editor",
         "Eliminate the legacy OpenCV click-drawing window. Build HTML5 Canvas polygon drawing tools directly into the web dashboard. Add FastAPI endpoints (GET/POST /api/zones) saving zone definitions to a persistent data/zones.json file. Support multiple named zones per camera: Exclusion Zones (immediate Critical alarm), Warning Buffer Zones (Medium alarm), and Directional Tripwires (alert only when crossing borderward)."),
        
        ("Feature 3: BOP Choke-Point ANPR & Vehicle Inspection Engine",
         "Create a dedicated check-post module for BOP entry gates. Utilize YOLOv8 plate detection paired with PaddleOCR or localized fast-plate-ocr to extract vehicle registration numbers. Validate plate numbers against standard Indian registration regex (e.g., ^[A-Z]{2}[0-9]{2}[A-Z]{1,2}[0-9]{4}$). Cross-reference extracted plates against a local SQLite hotlist (stolen, suspicious, or unauthorized vehicles) and trigger high-priority gate lock alerts."),
        
        ("Feature 4: Choke-Point Face Recognition (FRS) & Watchlist Hotlist",
         "Deploy a specialized gate face recognition pipeline. Use YuNet / RetinaFace for ultra-fast face localization at 5-10m gate choke-points, followed by MobileFaceNet / ArcFace 512-dimensional embedding generation. Store suspect profiles in a local encrypted SQLite gallery. Compute cosine similarity against live visitors. Display matched suspect profile, confidence percentage, and warrant details on the dashboard while adhering to the Digital Personal Data Protection (DPDP) Act 2023."),
        
        ("Feature 5: Dual-Path Night Vision & IR Motion-Gated Fallback",
         "Implement intelligent low-light compensation. When frame brightness drops below threshold (or IR mode is activated), pass frames through CLAHE (Contrast Limited Adaptive Histogram Equalization) to boost high-frequency edge gradients prior to YOLO inference. Concurrently run an OpenCV MOG2 background subtractor over the virtual fence polygon: if significant motion occurs inside an exclusion zone while YOLO confidence is low (due to IR bloom or thermal noise), trigger a 'Motion Intrusion (Night Degraded)' alert."),
        
        ("Feature 6: Tactical Digital-Twin BOP Mini-Map & Live Stream Relay",
         "Add an interactive 2D SVG/Canvas tactical overview map of the Border Out Post to the Command Centre UI. Display camera mounting points, field-of-view (FOV) coverage cones, and real-time pulsing red beacons whenever an intrusion occurs. Embed live MJPEG video streams into the dashboard interface so operators can click any camera on the map to instantly view its live annotated feed."),
        
        ("Feature 7: Camera Tamper & Lens Occlusion Detection",
         "Border cameras are highly vulnerable to sabotage (spray paint, cloth covering, blinding laser pointers, or cable tampering). Implement real-time scene change detection: calculate frame histogram shift and Laplacian variance (defocus). If a camera feed goes black, freezes, or experiences sudden structural blur exceeding 3 seconds, generate an instant high-priority 'CAMERA TAMPER / OCCLUSION' alert sealed directly into the evidence ledger."),
        
        ("Feature 8: Standardized Command & Control (C2) Integration & Webhooks",
         "Implement a robust C2 dispatch subsystem. When an alert fires, dispatch a structured JSON payload via asynchronous HTTP POST webhooks to external Command & Control servers (simulating BSF Sector Headquarters or Dial-112). Provide an interactive OpenAPI / Swagger specification page at http://127.0.0.1:8000/docs allowing evaluators to test and verify C2 interoperability."),
        
        ("Feature 9: Legal Evidence Dossier & Section 65B Audit Certificate",
         "Elevate the Day 5 SHA-256 ledger into a courtroom-ready evidence package. Add a 'Generate Legal Certificate' button on the dashboard that produces a signed PDF certificate under Section 65B of the Indian Evidence Act / Section 63 of Bharatiya Sakshya Adhiniyam 2023. The certificate embeds the alert snapshot, tamper-evident hash chain head, camera calibration parameters, timestamp, and an automated officer signature block.")
    ]

    for title, desc in features:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(2)
        r_t = p.add_run(f"• {title}: ")
        r_t.bold = True
        r_t.font.color.rgb = RGBColor(2, 132, 199)
        r_d = p.add_run(desc)
        r_d.font.color.rgb = RGBColor(51, 65, 85)

    # 6. ECONOMIC JUSTIFICATION
    h1 = doc.add_paragraph()
    h1.paragraph_format.space_before = Pt(14)
    h1.paragraph_format.space_after = Pt(4)
    r = h1.add_run("6. Capex Economics & Edge Hardware Sizing")
    r.font.size = Pt(14)
    r.font.bold = True
    r.font.color.rgb = RGBColor(15, 37, 55)

    econ_table = doc.add_table(rows=6, cols=3)
    econ_widths = [Inches(2.3), Inches(2.3), Inches(2.4)]
    econ_data = [
        ["Cost Dimension (100-Camera BOP Sector)", "Legacy Hardware Replacement Model", "IBVAP Edge-AI Software Gateway Model"],
        [
            "Edge Camera / Sensor Unit Cost",
            "Rs. 80,000 to Rs. 1,80,000 per smart camera (built-in NPU/optical FRS/ANPR).",
            "Rs. 0 (Retains existing legacy analog / IP cameras already deployed)."
        ],
        [
            "Total Sensor Hardware Capex",
            "Rs. 80 Lakhs to Rs. 1.80 Crores (for 100 cameras).",
            "Rs. 0 for camera replacement."
        ],
        [
            "Compute / Server Infrastructure",
            "Central NVRs / Cloud VMS servers: Rs. 15,00,000 to Rs. 25,00,000.",
            "10× Edge Industrial GPU Nodes (e.g. RTX 4060 / Jetson Orin): Rs. 20,00,000."
        ],
        [
            "Recurring Cloud / License Fees",
            "Rs. 3,000 to Rs. 8,000 per camera/year VMS licenses (Rs. 3L–8L annually).",
            "Rs. 0 (100% On-Premise, Open Architecture, Indigenous IP)."
        ],
        [
            "NET 5-YEAR SECTOR TCO",
            "Rs. 1.10 Crores to Rs. 2.20 Crores",
            "Rs. 20 Lakhs (82% to 91% Direct Capex Savings!)"
        ]
    ]
    for i, row in enumerate(econ_table.rows):
        for j, cell in enumerate(row.cells):
            cell.text = econ_data[i][j]
    style_table(econ_table, econ_widths)
    doc.add_paragraph()

    # 7. 36-HOUR EXECUTION PLAN
    h1 = doc.add_paragraph()
    h1.paragraph_format.space_before = Pt(14)
    h1.paragraph_format.space_after = Pt(4)
    r = h1.add_run("7. 36-Hour Hackathon Execution Roadmap & Demo Battleplan")
    r.font.size = Pt(14)
    r.font.bold = True
    r.font.color.rgb = RGBColor(15, 37, 55)

    phases = [
        ("Hours 00 - 08: Core Engine Refactoring & Cross-Platform Stability",
         "Fix cv2.VideoCapture camera indexing for macOS/Linux; implement VideoStreamManager with background thread queueing; replace OpenCV click-drawing with persistent zones.json; implement REST API endpoints for dynamic zone creation."),
        
        ("Hours 08 - 18: Check-Point Intelligence (ANPR + Choke-Point FRS)",
         "Integrate PaddleOCR / fast-plate-ocr on vehicle crops; build Indian license plate regex validator; integrate lightweight face detection (YuNet/RetinaFace) + MobileFaceNet gallery matcher; implement gate alert escalation logic."),
        
        ("Hours 18 - 28: Tactical Dashboard, 2D BOP Mini-Map & Night Vision",
         "Modernize dashboard.py: implement MJPEG video stream streaming into HTML5 canvas; build interactive polygon zone drawing directly in browser; add 2D BOP mini-map with real-time pulsing alert beacons; implement CLAHE low-light enhancement and MOG2 motion-gating fallback."),
        
        ("Hours 28 - 36: C2 Webhook Integration, Section 65B Dossier & Demo Rehearsal",
         "Add C2 outgoing webhook dispatcher and FastAPI /docs Swagger interface; build Section 65B legal certificate generator; conduct 3 end-to-end demo dress rehearsals: (1) Unplug internet to prove 100% offline edge capability, (2) Draw a new virtual fence live on Camera 2 at runtime, (3) Execute ledger tamper demo showing immediate red badge detection.")
    ]

    for title, desc in phases:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(4)
        p.paragraph_format.space_after = Pt(2)
        r_t = p.add_run(f"• {title}: ")
        r_t.bold = True
        r_t.font.color.rgb = RGBColor(15, 37, 55)
        r_d = p.add_run(desc)
        r_d.font.color.rgb = RGBColor(71, 85, 105)

    doc.add_paragraph()
    add_callout(
        doc,
        "By systematically addressing the multi-stream concurrency, dynamic web zone editing, choke-point FRS/ANPR, and night motion-gating pipelines, IBVAP transitions from a promising Day 5 prototype into an unassailable, competition-winning defense intelligence platform. The technical foundation in code/ledger.py and rule.py is robust—now we complete the operational operationalization.",
        title="ROADMAP CONCLUSION & NEXT STEPS",
        border_color="39D98A",
        bg_color="F0FDF4"
    )

    doc.save(filepath)
    print(f"✅ Word Document successfully generated: {filepath}")


# ==============================================================================
# 2. DEFENSE-GRADE PDF GENERATION (.PDF)
# ==============================================================================

class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas to dynamically compute and draw running headers and 'Page X of Y' footers."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_decorations(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748B"))
        
        # Running Header (pages > 1)
        if self._pageNumber > 1:
            self.drawString(54, 750, "IBVAP · MHA/BSF Problem Statement Deep-Dive & Gap Analysis Report")
            self.drawRightString(558, 750, "DEFENSE INTELLIGENCE PLATFORM")
            self.setStrokeColor(colors.HexColor("#CBD5E1"))
            self.setLineWidth(0.5)
            self.line(54, 742, 558, 742)
        
        # Running Footer (all pages)
        self.setStrokeColor(colors.HexColor("#CBD5E1"))
        self.setLineWidth(0.5)
        self.line(54, 45, 558, 45)
        self.drawString(54, 32, "CONFIDENTIAL & PROPRIETARY — DEFENSE EVALUATION AUDIT REPORT")
        page_text = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(558, 32, page_text)
        self.restoreState()


def generate_pdf_document(filepath):
    doc = SimpleDocTemplate(
        filepath,
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54
    )
    
    styles = getSampleStyleSheet()
    
    # Custom Palette
    c_primary = colors.HexColor("#0F2537")
    c_accent = colors.HexColor("#0284C7")
    c_text = colors.HexColor("#1E293B")
    c_dim = colors.HexColor("#64748B")
    c_bg_light = colors.HexColor("#F8FAFC")
    c_line = colors.HexColor("#E2E8F0")
    c_callout_bg = colors.HexColor("#F0F9FF")
    
    # Typography Styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=17,
        leading=21,
        textColor=c_primary,
        spaceAfter=3
    )
    sub_style = ParagraphStyle(
        'DocSub',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8.5,
        leading=11,
        textColor=c_accent,
        spaceAfter=2
    )
    desc_style = ParagraphStyle(
        'DocDesc',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9.5,
        leading=13,
        textColor=c_dim,
        spaceAfter=8
    )
    h1_style = ParagraphStyle(
        'SectionH1',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=15,
        textColor=c_primary,
        spaceBefore=10,
        spaceAfter=5
    )
    body_style = ParagraphStyle(
        'BodyDark',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=12.5,
        textColor=c_text,
        spaceAfter=5
    )
    bullet_style = ParagraphStyle(
        'BulletText',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=11.5,
        textColor=c_text,
        spaceAfter=3.5
    )
    callout_style = ParagraphStyle(
        'CalloutText',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=11.5,
        textColor=colors.HexColor("#0F2537")
    )
    th_style = ParagraphStyle(
        'TH',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=7.2,
        leading=9.2,
        textColor=colors.white,
        alignment=0
    )
    td_style = ParagraphStyle(
        'TD',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=7.2,
        leading=9.5,
        textColor=c_text
    )
    td_bold = ParagraphStyle(
        'TDBold',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=7.2,
        leading=9.5,
        textColor=c_primary
    )

    story = []
    
    # -------------------------------------------------------------
    # PAGE 1: TITLE, AUDIT & CONTEXT
    # -------------------------------------------------------------
    story.append(Paragraph("MINISTRY OF HOME AFFAIRS (MHA) · BORDER SECURITY FORCES (BSF / SSB)", sub_style))
    story.append(Paragraph("INTELLIGENT BORDER VIDEO ANALYTICS PLATFORM (IBVAP)", title_style))
    story.append(Paragraph("Comprehensive Codebase Audit, Judge Requirement Gap Analysis, and Feature Addition Roadmap", desc_style))
    
    meta_data = [
        [
            Paragraph("<b>Platform:</b> v0.6 Baseline", td_style),
            Paragraph("<b>Sponsor:</b> MHA / BSF / SSB", td_style),
            Paragraph("<b>Target:</b> Hackathon Finale", td_style),
            Paragraph("<b>Deployment:</b> 100% On-Prem", td_style)
        ],
        [
            Paragraph("<b>Model:</b> YOLOv8n + ByteTrack", td_style),
            Paragraph("<b>Ledger:</b> SHA-256 Hash Chain", td_style),
            Paragraph(f"<b>Date:</b> {datetime.datetime.now().strftime('%b %d, %Y')}", td_style),
            Paragraph("<b>Status:</b> Roadmap Active", td_style)
        ]
    ]
    meta_table = Table(meta_data, colWidths=[126, 126, 126, 126])
    meta_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#F1F5F9")),
        ('BOX', (0,0), (-1,-1), 0.5, c_line),
        ('INNERGRID', (0,0), (-1,-1), 0.5, c_line),
        ('TOPPADDING', (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('LEFTPADDING', (0,0), (-1,-1), 5),
        ('RIGHTPADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 8))

    callout_data = [[
        Paragraph("<b>[EXECUTIVE MANDATE]</b> Transform legacy analog/IP CCTV cameras along Indian borders into an autonomous, alert-driven sensor grid without purchasing expensive smart cameras (Rs. 80K-2L/unit) or recurring cloud subscriptions. This audit establishes the engineering plan to bridge existing code gaps and maximize defense evaluation scores.", callout_style)
    ]]
    callout_tbl = Table(callout_data, colWidths=[504])
    callout_tbl.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), c_callout_bg),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#BAE6FD")),
        ('LINELEFT', (0,0), (0,-1), 3.5, c_accent),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(callout_tbl)
    story.append(Spacer(1, 8))

    story.append(Paragraph("1. Executive Summary & Strategic Context", h1_style))
    story.append(Paragraph("Border Out Posts (BOPs) operated by BSF, SSB, and ITBP manage thousands of legacy cameras, yet face rapid human vigilance collapse after 20-30 minutes of continuous screen watching. Infiltration, smuggling, and drone activity are discovered only post-facto. While vendors push proprietary smart cameras costing Rs. 80,000 to Rs. 2,00,000+ per unit (Rs. 8-20 Cr per 1,000 cameras), IBVAP introduces a pure edge-software gateway. By processing RTSP feeds locally on a single Rs. 2.5L edge GPU server per 10-16 camera cluster, IBVAP delivers 20-50x capex savings, eliminates foreign OEM lock-in, and enforces Atmanirbhar Bharat defense autonomy.", body_style))

    story.append(Paragraph("2. Forensic Audit of Current Codebase (v0.6 Baseline)", h1_style))
    audit_rows = [
        [Paragraph("Module / File", th_style), Paragraph("Implementation", th_style), Paragraph("Current Strengths", th_style), Paragraph("Critical Gaps & Vulnerabilities", th_style)],
        [
            Paragraph("<b>code/live.py</b>", td_bold),
            Paragraph("YOLOv8n CPU detection loop.", td_style),
            Paragraph("320x320 downsampling (~18 FPS CPU).", td_style),
            Paragraph("<b>CRITICAL BUG:</b> Uses cv2.CAP_DSHOW. Fails on macOS/Linux.", td_style)
        ],
        [
            Paragraph("<b>code/track.py</b>", td_bold),
            Paragraph("YOLO + ByteTrack tracking.", td_style),
            Paragraph("40-pt trails; px speed; track age.", td_style),
            Paragraph("No real-world metric calibration; naive 10s track purge.", td_style)
        ],
        [
            Paragraph("<b>code/fence.py</b>", td_bold),
            Paragraph("OpenCV click-drawn polygon fence.", td_style),
            Paragraph("Sub-ms pointPolygonTest; tripwire logic.", td_style),
            Paragraph("<b>STRESS-TEST FLAW:</b> Drawn on CV window; lost on restart; no Web UI.", td_style)
        ],
        [
            Paragraph("<b>code/rule.py</b>", td_bold),
            Paragraph("Integrated pipeline & scoring brain.", td_style),
            Paragraph("Explainable score; cooldowns; animal filter.", td_style),
            Paragraph("Single-threaded; naive night check; lacks CLAHE/MOG2 fallback.", td_style)
        ],
        [
            Paragraph("<b>code/ledger.py</b>", td_bold),
            Paragraph("SHA-256 tamper-evident ledger.", td_style),
            Paragraph("<b>TOP DEFENSE USP:</b> Chain verify + anchor head.", td_style),
            Paragraph("Needs exportable Section 65B court evidence certificate PDF.", td_style)
        ],
        [
            Paragraph("<b>code/dashboard.py</b>", td_bold),
            Paragraph("FastAPI dark command centre UI.", td_style),
            Paragraph("Data polling; live ledger badge; audio beeps.", td_style),
            Paragraph("4s polling latency; no live video canvas; no map; no zone drawing.", td_style)
        ]
    ]
    t_audit = Table(audit_rows, colWidths=[90, 120, 134, 160])
    t_audit.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), c_primary),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, c_bg_light]),
        ('GRID', (0,0), (-1,-1), 0.5, c_line),
        ('TOPPADDING', (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('LEFTPADDING', (0,0), (-1,-1), 4),
        ('RIGHTPADDING', (0,0), (-1,-1), 4),
    ]))
    story.append(t_audit)

    # -------------------------------------------------------------
    # PAGE 2: GAP MATRIX & STRESS TEST
    # -------------------------------------------------------------
    story.append(PageBreak())
    
    story.append(Paragraph("3. Requirement vs. Codebase Gap Matrix (MHA / BSF Scoring Rubric)", h1_style))
    gap_rows = [
        [Paragraph("Capability", th_style), Paragraph("Evaluator Expectation", th_style), Paragraph("Current State (v0.6)", th_style), Paragraph("Severity", th_style), Paragraph("Required Action", th_style)],
        [
            Paragraph("<b>Multi-RTSP Streams</b>", td_bold),
            Paragraph("8-12 streams concurrent; auto-reconnect.", td_style),
            Paragraph("Single-stream sync loop; crashes on Mac.", td_style),
            Paragraph("<font color='#DC2626'><b>CRITICAL</b></font>", td_style),
            Paragraph("Threaded queue stream manager + MediaMTX harness.", td_style)
        ],
        [
            Paragraph("<b>Dynamic Zones</b>", td_bold),
            Paragraph("Web UI polygon drawing; DB/JSON persistence.", td_style),
            Paragraph("OpenCV window click; erased on quit.", td_style),
            Paragraph("<font color='#DC2626'><b>CRITICAL</b></font>", td_style),
            Paragraph("HTML5 Canvas polygon editor + REST API to zones.json.", td_style)
        ],
        [
            Paragraph("<b>Choke-Point FRS</b>", td_bold),
            Paragraph("5-10m gate recognition; NIST pixel realism.", td_style),
            Paragraph("Completely absent in codebase.", td_style),
            Paragraph("<font color='#DC2626'><b>MAJOR</b></font>", td_style),
            Paragraph("YuNet/RetinaFace + MobileFaceNet gallery matching.", td_style)
        ],
        [
            Paragraph("<b>Check-Point ANPR</b>", td_bold),
            Paragraph("Indian vehicle plate detection & OCR.", td_style),
            Paragraph("Completely absent in codebase.", td_style),
            Paragraph("<font color='#DC2626'><b>MAJOR</b></font>", td_style),
            Paragraph("YOLO plate detector + PaddleOCR with regex filter.", td_style)
        ],
        [
            Paragraph("<b>Night Vision</b>", td_bold),
            Paragraph("IR noise filtering + low-light enhancement.", td_style),
            Paragraph("Brightness mean check only (+25 pts).", td_style),
            Paragraph("<font color='#D97706'><b>HIGH</b></font>", td_style),
            Paragraph("Dual-Path: CLAHE contrast booster + MOG2 motion gating.", td_style)
        ],
        [
            Paragraph("<b>Anti-Fatigue Triage</b>", td_bold),
            Paragraph("<5 actionable alerts/cam/day; dedup.", td_style),
            Paragraph("Cooldowns (8s/3s) + animal suppression.", td_style),
            Paragraph("<font color='#16A34A'><b>PASS</b></font>", td_style),
            Paragraph("Expose suppression analytics counter on dashboard.", td_style)
        ],
        [
            Paragraph("<b>Evidence Ledger</b>", td_bold),
            Paragraph("SHA-256 hash chaining; court validity.", td_style),
            Paragraph("Fully working in ledger.py with verify.", td_style),
            Paragraph("<font color='#16A34A'><b>PASS</b></font>", td_style),
            Paragraph("Exportable Section 65B Indian Evidence Act certificate.", td_style)
        ],
        [
            Paragraph("<b>C2 Integration</b>", td_bold),
            Paragraph("REST/Webhook API for external VMS/C2.", td_style),
            Paragraph("Basic GET /api/state for frontend.", td_style),
            Paragraph("<font color='#D97706'><b>HIGH</b></font>", td_style),
            Paragraph("Asynchronous Webhook POST + OpenAPI /docs swagger.", td_style)
        ],
        [
            Paragraph("<b>Tactical UI / Map</b>", td_bold),
            Paragraph("Live video stream; 2D BOP digital twin map.", td_style),
            Paragraph("Static snapshot feed with 4s poll.", td_style),
            Paragraph("<font color='#D97706'><b>HIGH</b></font>", td_style),
            Paragraph("MJPEG live video canvas + 2D BOP tactical map.", td_style)
        ]
    ]
    t_gap = Table(gap_rows, colWidths=[80, 105, 105, 54, 160])
    t_gap.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), c_primary),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, c_bg_light]),
        ('GRID', (0,0), (-1,-1), 0.5, c_line),
        ('TOPPADDING', (0,0), (-1,-1), 2.5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2.5),
        ('LEFTPADDING', (0,0), (-1,-1), 3),
        ('RIGHTPADDING', (0,0), (-1,-1), 3),
    ]))
    story.append(t_gap)
    story.append(Spacer(1, 8))

    story.append(Paragraph("4. Defense Evaluator Stress-Test Q&A Pre-Emption", h1_style))
    qa_rows = [
        [Paragraph("Judge Stress Question", th_style), Paragraph("Hidden Trap", th_style), Paragraph("Winning Engineering Response", th_style)],
        [
            Paragraph("<b>Q1: 'You still need an edge GPU server—isn't that the same cost?'</b>", td_bold),
            Paragraph("Testing capex math understanding.", td_style),
            Paragraph("'No, Sir: Smart cameras cost Rs. 80k–2L per unit × 1,000 cams (Rs. 8–20 Cr). One Rs. 2.5L edge GPU server runs 12–16 streams, cutting capex by 25–50x while eliminating vendor lock-in.'", td_style)
        ],
        [
            Paragraph("<b>Q2: 'Infiltration happens at 2 AM in IR. Daylight YOLO fails. What happens?'</b>", td_bold),
            Paragraph("Exposing daylight-only models.", td_style),
            Paragraph("'We run a Dual-Path Night Engine: CLAHE enhances low-light edges, and an MOG2 motion-differencing safety net trips zone alarms even if neural confidence drops in pitch darkness.'", td_style)
        ],
        [
            Paragraph("<b>Q3: 'Faces at 200m are 15px. Is FRS science fiction?'</b>", td_bold),
            Paragraph("Detecting fake optical claims.", td_style),
            Paragraph("'FRS is strictly scoped to Choke-Point Gates (5–10m, 80–120px) under NIST FRVT standards. At perimeter distance (50–300m), we use Appearance-Based Re-ID and trajectory tracking.'", td_style)
        ],
        [
            Paragraph("<b>Q4: Live Challenge: 'Draw a fence on Cam 2 right now from UI without code.'</b>", td_bold),
            Paragraph("The fatal prototype killer.", td_style),
            Paragraph("'Demonstrated live in 5 seconds: Operator clicks Configure Zones on Web UI, draws polygon on canvas, clicks Save. REST API writes to zones.json and updates inference in memory.'", td_style)
        ],
        [
            Paragraph("<b>Q5: 'Animals trigger 200 false alarms a night. How to avoid fatigue?'</b>", td_bold),
            Paragraph("Operational reality test.", td_style),
            Paragraph("'COCO animal classes are filtered to background logs with 0 alarm. Track-ID cooldowns group loitering into one consolidated dossier. Target: <5 actionable alarms/cam/day.'", td_style)
        ]
    ]
    t_qa = Table(qa_rows, colWidths=[120, 110, 274])
    t_qa.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), c_primary),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, c_bg_light]),
        ('GRID', (0,0), (-1,-1), 0.5, c_line),
        ('TOPPADDING', (0,0), (-1,-1), 2.5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2.5),
        ('LEFTPADDING', (0,0), (-1,-1), 4),
        ('RIGHTPADDING', (0,0), (-1,-1), 4),
    ]))
    story.append(t_qa)

    # -------------------------------------------------------------
    # PAGE 3: FEATURE BLUEPRINT, ECONOMICS & ROADMAP
    # -------------------------------------------------------------
    story.append(PageBreak())

    story.append(Paragraph("5. Architectural Blueprint: 9 Core Feature Additions", h1_style))
    feat_bullets = [
        "<b>1. Multi-Stream RTSP Concurrency Engine:</b> Threaded VideoStreamManager with ring buffer queues and keyframe decimation (6 FPS analysis, 25 FPS display) supporting 8-12 streams per GPU/CPU node.",
        "<b>2. Config-Driven Dynamic Web Polygon Editor:</b> HTML5 Canvas polygon drawer with REST endpoints (GET/POST /api/zones) persisting to data/zones.json for live runtime boundary modifications.",
        "<b>3. BOP Gate ANPR Engine:</b> YOLO plate detector + PaddleOCR with Indian plate regex validation (^[A-Z]{2}[0-9]{2}[A-Z]{1,2}[0-9]{4}$) and stolen/suspect vehicle hotlist alerts.",
        "<b>4. Choke-Point FRS (Gate Watchlist):</b> YuNet/RetinaFace + MobileFaceNet 512-dim embeddings for 5-10m choke-points with local encrypted SQLite gallery and DPDP Act 2023 safeguards.",
        "<b>5. Dual-Path Night Vision & IR Motion Gating:</b> CLAHE contrast boosting for low-light plus MOG2 motion differencing fallback inside virtual fences when neural confidence drops.",
        "<b>6. Tactical Digital-Twin 2D BOP Mini-Map:</b> Interactive map with camera FOV coverage cones, real-time pulsing alert beacons, and instant live MJPEG video stream popups.",
        "<b>7. Camera Tamper & Lens Occlusion Detection:</b> Real-time histogram shift and Laplacian variance analysis detecting camera blinding, spray paint, physical displacement, or cable cuts.",
        "<b>8. Standardized C2 Integration & Webhooks:</b> Outgoing HTTP POST webhook dispatcher pushing structured alert JSON to Sector HQ plus interactive Swagger documentation at /docs.",
        "<b>9. Section 65B Court Evidence Certificate:</b> Exportable legally defensible PDF audit dossier embedding SHA-256 chain seal, snapshot, and officer signature block under Bharatiya Sakshya Adhiniyam 2023."
    ]
    for b in feat_bullets:
        story.append(Paragraph(f"• {b}", bullet_style))
    story.append(Spacer(1, 6))

    story.append(Paragraph("6. Capex Economics: 100-Camera BOP Sector Model", h1_style))
    econ_rows = [
        [Paragraph("Cost Dimension", th_style), Paragraph("Smart Camera Hardware Replacement", th_style), Paragraph("IBVAP Edge Software Gateway", th_style)],
        [Paragraph("<b>Camera Unit Cost</b>", td_bold), Paragraph("Rs. 80,000 to Rs. 1,80,000 / camera", td_style), Paragraph("Rs. 0 (Uses existing legacy CCTV)", td_style)],
        [Paragraph("<b>Total Camera Capex</b>", td_bold), Paragraph("Rs. 80 Lakhs to Rs. 1.80 Crores", td_style), Paragraph("Rs. 0 for camera replacement", td_style)],
        [Paragraph("<b>Compute Infrastructure</b>", td_bold), Paragraph("Central NVRs / Cloud VMS: Rs. 15L–25L", td_style), Paragraph("10× Edge GPU Nodes: Rs. 20L–25L", td_style)],
        [Paragraph("<b>Recurring Cloud Licenses</b>", td_bold), Paragraph("Rs. 3,000 to Rs. 8,000 / cam / year", td_style), Paragraph("Rs. 0 (100% On-Premise, Open IP)", td_style)],
        [Paragraph("<b>TOTAL 5-YR SECTOR TCO</b>", td_bold), Paragraph("<font color='#DC2626'><b>Rs. 1.10 Cr to Rs. 2.20 Crores</b></font>", td_style), Paragraph("<font color='#16A34A'><b>Rs. 20 Lakhs (82-91% Savings!)</b></font>", td_style)]
    ]
    t_econ = Table(econ_rows, colWidths=[130, 184, 190])
    t_econ.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), c_primary),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, c_bg_light]),
        ('GRID', (0,0), (-1,-1), 0.5, c_line),
        ('TOPPADDING', (0,0), (-1,-1), 2.5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2.5),
        ('LEFTPADDING', (0,0), (-1,-1), 4),
        ('RIGHTPADDING', (0,0), (-1,-1), 4),
    ]))
    story.append(t_econ)
    story.append(Spacer(1, 6))

    story.append(Paragraph("7. 36-Hour Hackathon Execution Roadmap & Demo Moves", h1_style))
    phases = [
        "<b>Hours 00 - 08 (Engine Core & Cross-Platform):</b> Fix macOS/Linux camera indexing; build Threaded VideoStreamManager; implement persistent data/zones.json REST API.",
        "<b>Hours 08 - 18 (Check-Point Intelligence):</b> Integrate PaddleOCR for Indian plates; add YuNet+MobileFaceNet choke-point FRS; implement gate alert escalation.",
        "<b>Hours 18 - 28 (Tactical UI & Night Pipeline):</b> Build MJPEG live video canvas; implement browser polygon drawing tool; add 2D BOP map; add CLAHE/MOG2 night path.",
        "<b>Hours 28 - 36 (C2 Webhooks & Demo Rehearsal):</b> Finalize C2 webhook dispatcher; test Section 65B PDF certificate; rehearse 3 killer demo moves (unplug internet, draw zone live, tamper ledger demo)."
    ]
    for p in phases:
        story.append(Paragraph(f"• {p}", bullet_style))
    story.append(Spacer(1, 8))

    final_callout = [[
        Paragraph("<b>[DEMO DAY FORMULA]</b> Walk in with this single opening sentence: <i>'We do not sell expensive new cameras. We turn the thousands of cameras already guarding our borders into an intelligent, alert-driven defense grid—100% offline, on-premise, tonight.'</i>", callout_style)
    ]]
    final_tbl = Table(final_callout, colWidths=[504])
    final_tbl.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#F0FDF4")),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#BBF7D0")),
        ('LINELEFT', (0,0), (0,-1), 3.5, colors.HexColor("#16A34A")),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(final_tbl)

    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"✅ PDF Document successfully generated: {filepath}")


if __name__ == "__main__":
    os.makedirs("docs", exist_ok=True)
    docx_path = os.path.abspath("docs/IBVAP_Gap_Analysis_and_Feature_Roadmap.docx")
    pdf_path = os.path.abspath("docs/IBVAP_Gap_Analysis_and_Feature_Roadmap.pdf")
    
    print("Generating defense-grade documents...")
    generate_word_document(docx_path)
    generate_pdf_document(pdf_path)
    print("Done! Both documents are ready in docs/")
