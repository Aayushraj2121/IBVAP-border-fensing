r"""
IBVAP - certgen.py: Court-Ready Evidence Certificate (v2 - stable layout)
Section 63(4), Bharatiya Sakshya Adhiniyam 2023 (successor to Sec 65B, IEA 1872)

Usage:
  python code/certgen.py            <- certificate for the LATEST record
  python code/certgen.py 2          <- certificate for record index 2
"""
import os, sys, datetime

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))

from ledger import load_chain, verify_chain, file_sha256
from fpdf import FPDF, XPos, YPos
from PIL import Image as PILImage

OUT_DIR = "data/certificates"

def ascii_safe(s):
    return "".join(ch for ch in str(s) if 32 <= ord(ch) < 127) or "-"

def mc(pdf, txt, border=0, fill=False):
    """Bulletproof multi-line text: always starts at left margin."""
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(0, 5.5, txt, border=border, fill=fill,
                   new_x=XPos.LMARGIN, new_y=YPos.NEXT)

def build_certificate(idx: int, rec: dict, verdict: dict) -> str:
    ok, bad, msg, head = verdict["ok"], verdict["bad"], verdict["msg"], verdict["head"]
    chain_ok = ok

    # ---------- snapshot integrity pre-check ----------
    snap_path = rec.get("snapshot", "")
    snap_ok, snap_note = False, "No snapshot attached to this record"
    if snap_path and os.path.exists(snap_path):
        actual = file_sha256(snap_path)
        if actual == rec.get("snapshot_sha256"):
            snap_ok, snap_note = True, "Snapshot SHA-256 MATCHES the sealed hash"
        else:
            snap_note = ("SNAPSHOT HASH MISMATCH - file was modified after sealing! "
                         f"expected {rec.get('snapshot_sha256','?')[:24]} got {actual[:24]}")
    elif snap_path:
        snap_note = "Snapshot file MISSING (record persists - deletion is detectable)"

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(True, margin=16)
    pdf.add_page()

    # ================= header =================
    pdf.set_fill_color(10, 20, 40)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 12, "IBVAP - EVIDENCE INTEGRITY CERTIFICATE", fill=True, align="C",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 8.5)
    pdf.cell(0, 7, "Intelligent Border Video Analytics Platform  |  SIH26187  |  MHA / SSB  |  "
                   "Generated: " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
             fill=True, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(3)
    pdf.set_text_color(0, 0, 0)

    # ================= 1. event record =================
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 8, "1. Sealed Event Record", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_draw_color(120, 120, 120)
    rows = [
        ("Ledger record index", "#" + str(idx)),
        ("Event type", ascii_safe(rec.get("event", "-"))),
        ("Timestamp (system)", ascii_safe(rec.get("time", "-"))),
        ("Track ID", ascii_safe(rec.get("track_id", "-"))),
        ("Severity / Score", ascii_safe(rec.get("severity", "-")) + " / " + str(rec.get("score", "-")) + " pts"),
        ("Age (s) / Speed (px/s)", str(rec.get("age_sec", "-")) + " / " + str(rec.get("speed_px_s", "-"))),
        ("Location (x,y)", ascii_safe(rec.get("location", "-"))),
        ("Plate (if ANPR)", ascii_safe(rec.get("plate", "n/a"))),
    ]
    pdf.set_font("Courier", "", 9.5)
    for k, v in rows:
        pdf.cell(65, 7, k, border=1)
        pdf.cell(0, 7, ascii_safe(v), border=1, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # ================= 2. scoring breakdown =================
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 8, "2. Alert Justification (Explainable Scoring Breakdown)",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Courier", "", 9.5)
    total = 0
    for k, v in (rec.get("breakdown") or {}).items():
        pdf.cell(65, 7, k.upper(), border=1)
        pdf.cell(0, 7, "+" + str(v) + " points", border=1, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        total += v
    pdf.set_font("Courier", "B", 9.5)
    pdf.cell(65, 7, "TOTAL", border=1)
    pdf.cell(0, 7, str(total) + " points", border=1, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # ================= 3. snapshot =================
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 8, "3. Evidence Snapshot", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    if snap_ok:
        try:
            with PILImage.open(snap_path) as im:
                iw, ih = im.size
            w_img = 120.0
            h_img = w_img * ih / iw
            y_before = pdf.get_y()
            pdf.image(snap_path, x=pdf.l_margin, w=w_img)
            pdf.set_xy(pdf.l_margin, max(pdf.get_y(), y_before + h_img) + 2)
        except Exception as e:
            pdf.set_font("Helvetica", "", 9)
            mc(pdf, "[snapshot present but could not be embedded: " + type(e).__name__ + "]")
            pdf.set_font("Courier", "", 9)
    pdf.set_font("Courier", "", 9)
    mc(pdf, "Snapshot file: " + ascii_safe(snap_path))
    mc(pdf, "Integrity check: " + ascii_safe(snap_note))
    mc(pdf, "Sealed snapshot SHA-256: " + ascii_safe(rec.get("snapshot_sha256", "-")))
    pdf.ln(2)

    # ================= 4. chain verification =================
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 8, "4. Tamper-Evidence Ledger Verification",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Courier", "", 9)
    mc(pdf, "Record seal (SHA-256): " + ascii_safe(rec.get("hash", "-")))
    mc(pdf, "Previous record seal : " + ascii_safe(rec.get("prev", "-")))
    mc(pdf, "Chain head           : " + ascii_safe(head))
    mc(pdf, "Full-chain replay    : " + ascii_safe(msg))
    if chain_ok:
        pdf.set_text_color(0, 110, 0)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 8, "VERDICT: CHAIN VERIFIED - record is intact since sealing",
                 new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    else:
        pdf.set_text_color(170, 0, 0)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 8, "VERDICT: CHAIN TAMPERED at record " + str(bad) + " - do not rely on this evidence",
                 new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(0, 0, 0)

    # ================= 5. certificate statement =================
    pdf.ln(2)
    pdf.set_fill_color(240, 244, 250)
    pdf.set_font("Helvetica", "", 9)
    mc(pdf,
       "CERTIFICATE STATEMENT: This document certifies that the electronic record "
       "described above was produced by the IBVAP evidence system and sealed into a "
       "SHA-256 hash-linked, append-only ledger at the stated time, and that the full "
       "chain was replayed and verified at generation time of this certificate. This "
       "certificate is issued for the purposes of Section 63(4) of the Bharatiya "
       "Sakshya Adhiniyam, 2023 (successor provision to Section 65B of the Indian "
       "Evidence Act, 1872) identifying the electronic record and the manner of its "
       "integrity assurance. Any alteration of the underlying ledger after sealing is "
       "mathematically detectable and would be reported in Section 4 above.",
       border=1, fill=True)

    # ================= 6. officer block =================
    pdf.ln(6)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 8, "6. Verification Officer", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 9.5)
    pdf.cell(85, 8, "Name & Rank: ______________________")
    pdf.cell(0, 8, "Unit / Post: ____________________", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.cell(85, 8, "Signature: ______________________")
    pdf.cell(0, 8, "Date & Time: ____________________", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.cell(85, 8, "Badge No:   ______________________")
    pdf.cell(0, 8, "BOP / Sector: ___________________", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "certificate_record_" + str(idx) + "_" +
                       datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".pdf")
    pdf.output(out)
    return out

def main():
    records = load_chain()
    if not records:
        print("Ledger is empty - nothing to certify.")
        return
    idx = int(sys.argv[1]) if len(sys.argv) > 1 else len(records) - 1
    if idx < 0 or idx >= len(records):
        print("Invalid record index " + str(idx) + " (valid: 0.." + str(len(records) - 1) + ")")
        return
    ok, bad, msg, head = verify_chain()
    verdict = {"ok": ok, "bad": bad, "msg": msg, "head": head}
    path = build_certificate(idx, records[idx], verdict)
    print("=" * 55)
    print("  CERTIFICATE GENERATED:", path)
    print("  Chain verdict:", "VERIFIED" if ok else ("TAMPERED at " + str(bad)))
    print("=" * 55)

if __name__ == "__main__":
    main()