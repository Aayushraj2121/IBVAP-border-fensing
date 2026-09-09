"""
IBVAP — Identity, Behavior & Video Analytics Platform
BOP-7 Secure Node | v1.4

ledger.py — Append-only SHA-256 chained event ledger.

Each line in code/data/events.jsonl is a JSON object:
  {
    "seq": 1,
    "ts": 1788861245.913,
    "prev_hash": "0000...",
    "this_hash": "abcd...",
    "event": { ... arbitrary event payload ... }
  }

verify_chain() walks the file and confirms cryptographic hash linkage. Returns
{"status": "OK", "records": N, "head": "..."} or
{"status": "BROKEN", "broken_at_seq": N, "detail": "..."}.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_EVENTS_PATH = Path(__file__).resolve().parent / "data" / "events.jsonl"
_GENESIS_PREV = "0" * 64
CHAIN_FILE = str(_EVENTS_PATH)


def _events_path() -> Path:
    """Resolve the events file path. Created on first append if missing."""
    _EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not _EVENTS_PATH.exists():
        _EVENTS_PATH.touch()
    return _EVENTS_PATH


def file_sha256(path: str) -> str:
    """SHA-256 of a file (used for cryptographic snapshot verification)."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _hash_record(prev_hash: str, seq: int, ts: float, event: Dict[str, Any]) -> str:
    """SHA-256 over (prev_hash || seq || ts || canonical JSON of event)."""
    payload = prev_hash + str(seq) + repr(ts) + json.dumps(event, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_hash(event: dict, prev_hash: str) -> str:
    """Canonical hash computation."""
    payload = json.dumps(event, sort_keys=True, separators=(",", ":")) + prev_hash
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read_all_records() -> List[Dict[str, Any]]:
    """Read every line of the ledger into a list of dicts. Skips blank lines."""
    path = _events_path()
    records: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                # Malformed line — surface as raw record for verify_chain to flag.
                records.append({"_raw": line, "_malformed": True})
    return records


def load_chain(path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Legacy helper: loads all records from the ledger."""
    return _read_all_records()


def append_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Append a single event to the ledger with a chained SHA-256 hash.

    The event dict is wrapped with seq, ts, prev_hash, this_hash. The original
    event payload is preserved under the "event" key.
    """
    if not isinstance(event, dict):
        raise TypeError("event must be a dict")

    records = _read_all_records()
    if records:
        last = records[-1]
        prev_hash = last.get("this_hash", _GENESIS_PREV)
        next_seq = int(last.get("seq", 0)) + 1
    else:
        prev_hash = _GENESIS_PREV
        next_seq = 1

    ts = time.time()
    this_hash = _hash_record(prev_hash, next_seq, ts, event)
    record = {
        "seq": next_seq,
        "ts": ts,
        "prev_hash": prev_hash,
        "this_hash": this_hash,
        "hash": this_hash,
        "event": event,
    }

    path = _events_path()
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, separators=(",", ":")) + "\n")

    return record


def verify_chain() -> Dict[str, Any]:
    """
    Walk the ledger and confirm every record's this_hash matches
    SHA-256(prev_hash || seq || ts || event). Returns:
      {"status": "OK", "records": N, "head": "..."}     on success
      {"status": "BROKEN", "broken_at_seq": N, "detail": "..."}  on failure
    """
    records = _read_all_records()
    if not records:
        return {"status": "OK", "records": 0, "head": _GENESIS_PREV}

    prev_hash = _GENESIS_PREV
    for i, rec in enumerate(records, start=1):
        if rec.get("_malformed"):
            return {
                "status": "BROKEN",
                "broken_at_seq": i,
                "detail": f"malformed JSON at line {i}: {rec.get('_raw','')[:80]}",
                "head": prev_hash,
            }
        if rec.get("prev_hash") != prev_hash:
            return {
                "status": "BROKEN",
                "broken_at_seq": rec.get("seq", i),
                "detail": f"prev_hash mismatch at seq {rec.get('seq', i)}",
                "head": prev_hash,
            }
        recomputed = _hash_record(rec["prev_hash"], rec["seq"], rec["ts"], rec["event"])
        if recomputed != rec.get("this_hash"):
            return {
                "status": "BROKEN",
                "broken_at_seq": rec.get("seq", i),
                "detail": f"this_hash mismatch at seq {rec.get('seq', i)}",
                "head": prev_hash,
            }
        prev_hash = rec["this_hash"]

    return {"status": "OK", "records": len(records), "head": prev_hash}


def tail_records(n: int = 50) -> List[Dict[str, Any]]:
    """Return the last n ledger records (newest last)."""
    records = _read_all_records()
    return records[-n:] if n < len(records) else records


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "verify":
        print(json.dumps(verify_chain(), indent=2))
    else:
        print(f"ledger path: {_events_path()}")
        print(f"records: {len(_read_all_records())}")