"""
IBVAP - Day 5: Tamper-Evident Evidence Ledger
- Hash chain: each record's SHA-256 includes the previous record's hash
- verify: recompute whole chain; any edit/delete/reorder = TAMPERED
- anchor: publish chain head externally (anti-truncation)

Commands:
  python code/ledger.py demo      <- SAFE automated tamper demo (separate file)
  python code/ledger.py verify    <- verify REAL evidence chain
  python code/ledger.py status    <- show chain head + record count
  python code/ledger.py anchor    <- anchor current head (publish seal)
"""
import hashlib, json, datetime, sys, os

CHAIN_FILE = "data/evidence_chain.jsonl"
ANCHOR_FILE = "data/anchor.txt"
DEMO_FILE = "data/demo_chain.jsonl"

# ---------------- core primitives ----------------
def _canonical(event: dict) -> str:
    """Stable JSON (sorted keys, no spaces) -> deterministic hashing."""
    return json.dumps(event, sort_keys=True, separators=(",", ":"))

def compute_hash(event: dict, prev_hash: str) -> str:
    """Seal = SHA256(canonical(event) + previous seal)."""
    return hashlib.sha256((_canonical(event) + prev_hash).encode()).hexdigest()

def file_sha256(path: str) -> str:
    """SHA-256 of a file (seals the snapshot JPG itself!)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

# ---------------- chain operations ----------------
def load_chain(path: str = CHAIN_FILE) -> list:
    if not os.path.exists(path):
        return []
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out

def append_event(event: dict, path: str = CHAIN_FILE) -> dict:
    """Seal event onto the chain. Returns the full sealed record."""
    records = load_chain(path)
    prev = records[-1]["hash"] if records else "GENESIS"
    rec = dict(event)
    rec["prev"] = prev
    rec["hash"] = compute_hash(event, prev)
    with open(path, "a") as f:
        f.write(json.dumps(rec) + "\n")
    return rec

def verify_chain(path: str = CHAIN_FILE):
    """Returns (ok, bad_index_or_None, message, head_hash)."""
    records = load_chain(path)
    prev = "GENESIS"
    for i, rec in enumerate(records):
        event = {k: v for k, v in rec.items() if k not in ("prev", "hash")}
        if compute_hash(event, prev) != rec.get("hash"):
            return False, i, f"Record {i}: content hash mismatch (EDITED)", rec.get("hash", "?")
        if rec.get("prev") != prev:
            return False, i, f"Record {i}: prev-link broken (DELETED/REORDERED)", rec.get("hash", "?")
        prev = rec["hash"]
    head = records[-1]["hash"] if records else "GENESIS"
    return True, None, f"Chain intact - {len(records)} records verified", head

def anchor_head(path: str = CHAIN_FILE):
    """Publish current head hash to anchor file (external trusted point)."""
    ok, _, msg, head = verify_chain(path)
    if not ok:
        print("❌ Cannot anchor a broken chain:", msg)
        return
    with open(ANCHOR_FILE, "a") as f:
        f.write(json.dumps({"time": datetime.datetime.now().isoformat(timespec="seconds"),
                            "head": head, "records": len(load_chain(path))}) + "\n")
    print("📌 Anchored head:", head[:24], "->", ANCHOR_FILE)

def check_anchor(path: str = CHAIN_FILE):
    """If anchored: detect TRUNCATION (records deleted after anchoring)."""
    if not os.path.exists(ANCHOR_FILE):
        return
    ok, _, _, head = verify_chain(path)
    if not ok:
        return
    anchors = [json.loads(l) for l in open(ANCHOR_FILE) if l.strip()]
    last = anchors[-1]
    if head != last["head"]:
        print("⚠️  WARNING: current head differs from last anchor.")
        print("   Anchored records:", last["records"], "| current:", len(load_chain(path)))
        print("   -> Possible TRUNCATION (tail records removed after anchoring)!")
    else:
        print("✅ Head matches last anchor - no truncation.")

# ---------------- CLI ----------------
def cmd_status():
    records = load_chain()
    if not records:
        print("Chain is EMPTY (no evidence sealed yet).")
        return
    print(f"Records: {len(records)}")
    print("Head seal:", records[-1]["hash"])

def cmd_verify():
    ok, bad, msg, head = verify_chain()
    print("=" * 55)
    if ok:
        print("✅ EVIDENCE CHAIN VERIFIED")
        print("   ", msg)
        print("    Head:", head[:32], "...")
        check_anchor()
    else:
        print("🚨 TAMPERED — EVIDENCE CHAIN BROKEN 🚨")
        print("   ", msg)
        print('    → Record index', bad, 'was modified/deleted after sealing!')
    print("=" * 55)

def cmd_demo():
    """SAFE end-to-end tamper demo on a separate file."""
    path = DEMO_FILE
    if os.path.exists(path):
        os.remove(path)
    print("--- 1. Sealing 3 sample alerts ---")
    for i in range(3):
        rec = append_event({"event": "SUSPICION_ALERT", "track_id": i + 1,
                            "score": 70 + i, "severity": "CRITICAL",
                            "time": datetime.datetime.now().isoformat(timespec="seconds")},
                           path)
        print(f"   sealed record {i} -> {rec['hash'][:20]}...")

    print("\n--- 2. Verifying intact chain ---")
    ok, _, msg, _ = verify_chain(path)
    print("   ✅ VERIFIED" if ok else "   ❌", "|", msg)

    print("\n--- 3. INSIDER ATTACK: editing record 1 (CRITICAL -> LOGGED) ---")
    lines = open(path).readlines()
    rec = json.loads(lines[1])
    rec["severity"] = "LOGGED"                     # the tamper!
    lines[1] = json.dumps(rec) + "\n"
    open(path, "w").writelines(lines)
    print("   (record edited and saved)")

    print("\n--- 4. Verifying tampered chain ---")
    ok, bad, msg, _ = verify_chain(path)
    if not ok:
        print("   🚨 TAMPERED DETECTED!", msg)
    else:
        print("   ❌ tamper NOT caught (bug!)")

    print("\n--- 5. Restoring original chain ---")
    lines[1] = json.dumps({**json.loads(lines[1]), "severity": "CRITICAL"}) + "\n"
    open(path, "w").writelines(lines)
    ok, _, msg, _ = verify_chain(path)
    print("   ✅ VERIFIED again" if ok else "   ❌", "|", msg)
    print("\nDemo complete. This is why insiders cannot quietly rewrite history.")

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "verify"
    if cmd == "demo":   cmd_demo()
    elif cmd == "verify": cmd_verify()
    elif cmd == "status": cmd_status()
    elif cmd == "anchor": anchor_head()
    else: print("Unknown command. Use: demo | verify | status | anchor")