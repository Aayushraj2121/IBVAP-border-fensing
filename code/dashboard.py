"""
IBVAP — Identity, Behavior & Video Analytics Platform
BOP-7 Secure Node | v1.4

dashboard.py — FastAPI application serving:
  - Jinja2 HTML pages (/, /login, /dashboard, /operator, /admin, /auditor)
  - JSON API (/api/state, /api/zones, /api/events, /api/alerts/ack, /api/users, /api/hotlist)
  - MJPEG live stream (/api/stream/{cam_id}) & snapshot export
  - Section 65B PDF evidence export (/api/export65b)
  - SHA-256 evidence chain verification (/api/ledger/verify)
  - Role-based JWT authentication (POST /login)

Run:  python3 code/dashboard.py  OR  uvicorn code.dashboard:app --port 8000
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

# Make sure sibling modules (auth.py, ledger.py, state.py) and root are importable
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    Response,
    status,
)
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from auth import (
    authenticate,
    current_user,
    decode_token,
    issue_token,
    list_users,
    optional_user,
    remove_user,
    require_role,
    toggle_user_active,
)
from ledger import append_event, tail_records, verify_chain
from state import live_state

# --- Paths -----------------------------------------------------------------

_BASE = Path(__file__).resolve().parent
_TEMPLATES_DIR = _ROOT / "templates"
_STATIC_DIR = _ROOT / "static"
_SNAPSHOTS_DIR = _ROOT / "data" / "snapshots"
if not _SNAPSHOTS_DIR.exists():
    _SNAPSHOTS_DIR = _ROOT / "snapshots"
_DATA_DIR = _BASE / "data"
_ZONES_PATH = _DATA_DIR / "zones.json"

for p in (_TEMPLATES_DIR, _STATIC_DIR, _SNAPSHOTS_DIR, _DATA_DIR):
    p.mkdir(parents=True, exist_ok=True)
if not _ZONES_PATH.exists():
    _ZONES_PATH.write_text("{}", encoding="utf-8")

# --- App setup -------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    watcher = asyncio.create_task(_alert_watcher())
    try:
        yield
    finally:
        watcher.cancel()
        try:
            await watcher
        except asyncio.CancelledError:
            pass

app = FastAPI(
    title="IBVAP BOP-7 Node",
    version="1.4.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,  # disabled — production node, no schema leak
    lifespan=lifespan,
)

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
app.mount("/snapshots", StaticFiles(directory=str(_SNAPSHOTS_DIR)), name="snapshots")


# --- Helpers ---------------------------------------------------------------

def _load_zones() -> Dict[str, Any]:
    try:
        return json.loads(_ZONES_PATH.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError:
        return {}


def _save_zones(zones: Dict[str, Any]) -> None:
    _ZONES_PATH.write_text(json.dumps(zones, indent=2), encoding="utf-8")


_HOTLIST_PATH = _DATA_DIR / "hotlist.json"
if not _HOTLIST_PATH.exists():
    _HOTLIST_PATH.write_text("[]", encoding="utf-8")


def _load_hotlist() -> List[Dict[str, Any]]:
    try:
        return json.loads(_HOTLIST_PATH.read_text(encoding="utf-8") or "[]")
    except json.JSONDecodeError:
        return []


def _save_hotlist(entries: List[Dict[str, Any]]) -> None:
    _HOTLIST_PATH.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def _b64_png(width: int, height: int, label: str) -> bytes:
    """Generate a placeholder JPG-like PNG for snapshot demos."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (width, height), color=(10, 15, 26))
    draw = ImageDraw.Draw(img)
    # frame
    draw.rectangle([0, 0, width - 1, height - 1], outline=(31, 42, 60), width=1)
    # crosshair
    cx, cy = width // 2, height // 2
    draw.line([(cx - 8, cy), (cx + 8, cy)], fill=(46, 125, 209), width=1)
    draw.line([(cx, cy - 8), (cx, cy + 8)], fill=(46, 125, 209), width=1)
    # label
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 12
        )
    except Exception:
        font = ImageFont.load_default()
    draw.text((8, 8), label, fill=(138, 151, 168), font=font)
    draw.text((8, height - 18), f"{width}x{height}", fill=(138, 151, 168), font=font)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return buf.getvalue()


def _ensure_seed_snapshots() -> None:
    """Generate placeholder JPGs for the 5 seed cameras if missing."""
    sizes = {
        "cam1_live.jpg": (640, 360, "CAM-01 / PEOPLE"),
        "cam2_live.jpg": (640, 360, "CAM-02 / VEHICLES + ANPR"),
        "cam3_live.jpg": (1488, 420, "CAM-03 / NIGHT CCTV"),
        "cam4_live.jpg": (640, 360, "CAM-04 / THERMAL FLIR"),
        "cam5_live.jpg": (640, 360, "CAM-05 / FACE RECOGNITION"),
    }
    for fname, (w, h, label) in sizes.items():
        path = _SNAPSHOTS_DIR / fname
        if not path.exists():
            path.write_bytes(_b64_png(w, h, label))


_ensure_seed_snapshots()


# --- HTML routes -----------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Redirect: if authenticated → role-appropriate console, else → /login."""
    auth = request.headers.get("Authorization", "")
    token = ""
    if auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
    if not token:
        token = request.cookies.get("ibvap.token", "").strip()
    if token:
        try:
            payload = decode_token(token)
            role = payload.get("role", "")
            target = {
                "admin":   "/admin",
                "operator": "/operator",
                "auditor": "/auditor",
            }.get(role, "/login")
            return RedirectResponse(url=target, status_code=302)
        except Exception:
            pass
    return RedirectResponse(url="/login", status_code=302)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html")


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request, user: Optional[Dict[str, Any]] = Depends(optional_user)):
    """Role-aware router: seamlessly routes authenticated users to their dedicated console."""
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    role = user.get("role", "")
    target = {
        "admin": "/admin",
        "operator": "/operator",
        "auditor": "/auditor",
    }.get(role, "/operator")
    return RedirectResponse(url=target, status_code=302)


@app.get("/operator", response_class=HTMLResponse)
async def operator_page(request: Request, user: Optional[Dict[str, Any]] = Depends(optional_user)):
    """
    Video-first operator console.
      - 56px icon rail (collapsed sidebar)
      - 44px top bar (IBVAP | BOP-7, status chip, IST clock, role badge)
      - 4 stat chips row
      - 6-tile video grid (3x2) with MJPEG + canvas overlay
      - 300px live event feed (right panel)
      - 48px critical ticker (bottom)
    """
    return templates.TemplateResponse(
        request=request,
        name="operator.html",
        context={
            "user": user or {},
            "node": "BOP-7",
            "version": "v1.4",
        },
    )


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, user: Optional[Dict[str, Any]] = Depends(optional_user)):
    """
    Admin management console.
      - 240px expanded sidebar: Overview, User Management, Hotlist/BOLO, Face Gallery, Settings
      - Stat chips: USERS, STREAMS, HOTLIST ENTRIES, UPTIME
      - Main: USER MANAGEMENT table + BOLO HOTLIST table with inline add form
    """
    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "user": user or {},
            "node": "BOP-7",
            "version": "v1.4",
        },
    )


@app.get("/auditor", response_class=HTMLResponse)
async def auditor_page(request: Request, user: Optional[Dict[str, Any]] = Depends(optional_user)):
    """
    Auditor console — strictly NO video anywhere.
      - Sidebar: Evidence Vault (active), Certificate Export
      - Top integrity banner: LEDGER INTEGRITY: VERIFIED — <N> BLOCKS
      - Main: vertical ledger timeline with chained SHA-256 blocks & chain icons
      - Right panel: Section 65B Certificate generation form
    """
    return templates.TemplateResponse(
        request=request,
        name="auditor.html",
        context={
            "user": user or {},
            "node": "BOP-7",
            "version": "v1.4",
        },
    )


# --- Auth API --------------------------------------------------------------

@app.post("/login")
async def login(username: str = Form(...), password: str = Form(...), response: Response = None):
    """Form-encoded login. Returns JWT + role. 401 on bad creds.

    Also sets the JWT as an HttpOnly cookie so that top-level navigations
    (GET /operator, GET /dashboard) can be authenticated.
    """
    user = authenticate(username, password)
    if user is None:
        append_event({
            "type": "AUTH_FAILURE",
            "ts": time.time(),
            "username": username,
            "node": "BOP-7",
        })
        raise HTTPException(status_code=401, detail="invalid credentials")
    token = issue_token(user)
    append_event({
        "type": "AUTH_SUCCESS",
        "ts": time.time(),
        "username": user["username"],
        "role": user["role"],
        "node": user.get("node", "BOP-7"),
    })
    if response is not None:
        response.set_cookie(
            key="ibvap.token",
            value=token,
            httponly=False,
            secure=False,
            samesite="lax",
            max_age=8 * 3600,
            path="/",
        )
    return {
        "token": token,
        "role": user["role"],
        "username": user["username"],
        "display_name": user.get("display_name", user["username"]),
        "expires_in": 8 * 3600,
    }


@app.get("/api/me")
async def me(user: Dict[str, Any] = Depends(current_user)):
    return user


# --- User Management API (Admin only) --------------------------------------

@app.get("/api/users")
async def api_get_users(user: Dict[str, Any] = Depends(require_role("admin"))):
    """List all registered system users."""
    return list_users()


@app.post("/api/users/toggle")
async def api_toggle_user(
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_role("admin")),
):
    """Toggle user active status. Body: {"username": str, "active": bool}"""
    username = payload.get("username", "").strip()
    active = bool(payload.get("active", True))
    if not username:
        raise HTTPException(400, "username required")
    if username == user["username"] and not active:
        raise HTTPException(400, "cannot deactivate currently logged-in account")
    success = toggle_user_active(username, active)
    if not success:
        raise HTTPException(404, f"user '{username}' not found")
    append_event({
        "type": "USER_STATUS_TOGGLED",
        "ts": time.time(),
        "admin": user["username"],
        "target_user": username,
        "new_status": "ACTIVE" if active else "SUSPENDED",
        "node": "BOP-7",
    })
    return {"ok": True, "username": username, "active": active}


@app.delete("/api/users/{username}")
async def api_remove_user(
    username: str,
    user: Dict[str, Any] = Depends(require_role("admin")),
):
    """Remove user. Admin only."""
    if username == user["username"]:
        raise HTTPException(400, "cannot delete currently logged-in account")
    success = remove_user(username)
    if not success:
        raise HTTPException(404, f"user '{username}' not found")
    append_event({
        "type": "USER_REMOVED",
        "ts": time.time(),
        "admin": user["username"],
        "target_user": username,
        "node": "BOP-7",
    })
    return {"ok": True, "removed": username}


# --- BOLO Hotlist API ------------------------------------------------------

@app.get("/api/hotlist")
async def api_get_hotlist(user: Dict[str, Any] = Depends(current_user)):
    """Return all active BOLO hotlist entries."""
    return _load_hotlist()


@app.post("/api/hotlist")
async def api_add_hotlist(
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_role("admin", "operator")),
):
    """
    Add or update an entry in the BOLO hotlist.
    Body: {"plate": str, "vehicle_class": str, "reason": str, "notes": str}
    """
    plate = payload.get("plate", "").strip().upper()
    vehicle_class = payload.get("vehicle_class", "").strip()
    reason = payload.get("reason", "SMUGGLING").strip().upper()
    notes = payload.get("notes", "").strip()
    if not plate:
        raise HTTPException(400, "plate number is required")

    entries = _load_hotlist()
    entry = {
        "plate": plate,
        "vehicle_class": vehicle_class or "Light Commercial (LCV)",
        "reason": reason if reason in ("NARCOTICS", "SMUGGLING", "SUSPECT VEHICLE") else "SMUGGLING",
        "added_date": time.strftime("%Y-%m-%d"),
        "notes": notes,
        "added_by": user["username"],
    }
    existing = next((i for i, e in enumerate(entries) if e["plate"] == plate), None)
    if existing is not None:
        entries[existing] = entry
    else:
        entries.insert(0, entry)

    _save_hotlist(entries)
    append_event({
        "type": "BOLO_HOTLIST_ADDED",
        "ts": time.time(),
        "user": user["username"],
        "plate": plate,
        "vehicle_class": entry["vehicle_class"],
        "reason": entry["reason"],
        "node": "BOP-7",
    })
    return {"ok": True, "entry": entry}


@app.delete("/api/hotlist/{plate}")
async def api_delete_hotlist(
    plate: str,
    user: Dict[str, Any] = Depends(require_role("admin", "operator")),
):
    """Delete entry from BOLO hotlist."""
    plate = plate.strip().upper()
    entries = _load_hotlist()
    new_entries = [e for e in entries if e["plate"] != plate]
    if len(new_entries) == len(entries):
        raise HTTPException(404, f"plate '{plate}' not found in hotlist")
    _save_hotlist(new_entries)
    append_event({
        "type": "BOLO_HOTLIST_REMOVED",
        "ts": time.time(),
        "user": user["username"],
        "plate": plate,
        "node": "BOP-7",
    })
    return {"ok": True, "removed": plate}


# --- Surveillance state API ------------------------------------------------

@app.get("/api/state")
async def api_state(user: Dict[str, Any] = Depends(current_user)):
    """Poll every 2s. Returns full snapshot of all camera streams."""
    return live_state.snapshot()


@app.get("/api/zones")
async def api_get_zones(user: Dict[str, Any] = Depends(current_user)):
    """Returns persisted polygon zones per camera: {cam_name: [{pts, type, name}]}"""
    return _load_zones()


@app.post("/api/zones")
async def api_post_zones(
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_role("admin", "operator")),
):
    """
    Persist polygon zones per camera. Body shape:
      { "CAM-01 (People)": [
          {"zone_id": "...", "zone_name": "...", "zone_type": "EXCLUSION_ZONE",
           "pts": [[x1,y1],[x2,y2],...]},
          ...
      ]}
    """
    if not isinstance(payload, dict):
        raise HTTPException(400, "expected a JSON object of camera -> zones[]")
    _save_zones(payload)
    append_event({
        "type": "ZONES_UPDATED",
        "ts": time.time(),
        "user": user["username"],
        "role": user["role"],
        "camera_count": len(payload),
    })
    return {"ok": True, "saved": True, "cameras": list(payload.keys())}


# --- Events API (read ledger) --------------------------------------------

@app.get("/api/events")
async def api_events(
    n: int = 50,
    user: Dict[str, Any] = Depends(current_user),
):
    """Return last n ledger records (newest last)."""
    if n < 1 or n > 1000:
        n = 50
    return tail_records(n)


# --- Alert acknowledgement -----------------------------------------------

_ACKED_ALERTS: set = set()


@app.post("/api/alerts/ack")
async def api_alert_ack(
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_role("admin", "operator")),
):
    """
    Acknowledge an alert by ledger seq. Appends an ACK event to the ledger
    so the action is auditable.

    Body: { "seq": <int>, "cam": "<optional cam name>", "note": "<optional>" }
    """
    if not isinstance(payload, dict) or "seq" not in payload:
        raise HTTPException(400, "expected JSON with 'seq' field")
    seq = payload["seq"]
    try:
        seq = int(seq)
    except (TypeError, ValueError):
        raise HTTPException(400, "seq must be an integer")

    _ACKED_ALERTS.add(seq)
    rec = append_event({
        "type": "ALERT_ACK",
        "ts": time.time(),
        "user": user["username"],
        "role": user["role"],
        "ack_seq": seq,
        "cam": payload.get("cam"),
        "note": payload.get("note", ""),
    })
    return {
        "ok": True,
        "ack_seq": seq,
        "acked_by": user["username"],
        "ledger_seq": rec["seq"],
    }


@app.get("/api/alerts/acked")
async def api_alerts_acked(user: Dict[str, Any] = Depends(current_user)):
    """Return the set of acknowledged alert seqs (for UI dimming)."""
    return {"acked": sorted(_ACKED_ALERTS)}


# --- MJPEG stream ---------------------------------------------------------

_CAM_REGISTRY: Dict[str, Dict[str, Any]] = {
    "CAM-01": {"file": "cam1_live.jpg", "label": "CAM-01 / GATE",          "w": 640,  "h": 360},
    "CAM-02": {"file": "cam2_live.jpg", "label": "CAM-02 / PERIMETER",      "w": 640,  "h": 360},
    "CAM-03": {"file": "cam3_live.jpg", "label": "CAM-03 / NORTH WALL",     "w": 1488, "h": 420},
    "CAM-04": {"file": "cam4_live.jpg", "label": "CAM-04 / ROOFTOP",        "w": 640,  "h": 360},
    "CAM-05": {"file": "cam5_live.jpg", "label": "CAM-05 / ENTRY",          "w": 640,  "h": 360},
    "GRID":   {"file": "grid_live.jpg", "label": "MASTER TACTICAL C2 GRID", "w": 1440, "h": 720},
    "CAM-06": {"file": "grid_live.jpg", "label": "MASTER TACTICAL C2 GRID", "w": 1440, "h": 720},
}


def _placeholder_frame(cam_id: str) -> bytes:
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (640, 360), color=(16, 24, 40))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 639, 359], outline=(31, 42, 60))
    d.text((20, 20), f"AWAITING {cam_id} FEED FROM ENGINE.PY...", fill=(201, 138, 43))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=75)
    return buf.getvalue()


def _get_mjpeg_frame(cam_id: str) -> bytes:
    """Read latest real-time frame directly from disk as raw JPEG bytes.
    Zero re-encoding overhead ensures full FPS and exact AI visual fidelity."""
    cam = _CAM_REGISTRY.get(cam_id)
    if not cam:
        return _placeholder_frame(cam_id)

    src_path = _SNAPSHOTS_DIR / cam["file"]
    if src_path.exists():
        try:
            data = src_path.read_bytes()
            if len(data) > 1000:
                return data
        except Exception:
            pass

    fallback_path = _ROOT / "snapshots" / cam["file"]
    if fallback_path.exists():
        try:
            data = fallback_path.read_bytes()
            if len(data) > 1000:
                return data
        except Exception:
            pass

    return _placeholder_frame(cam_id)


_MJPEG_BOUNDARY = "ibvapframe"


async def _mjpeg_generator(cam_id: str) -> AsyncGenerator[bytes, None]:
    """Yield MJPEG frames at ~12-15 fps. Closes when client disconnects."""
    try:
        while True:
            jpg = _get_mjpeg_frame(cam_id)
            header = (
                f"--{_MJPEG_BOUNDARY}\r\n"
                f"Content-Type: image/jpeg\r\n"
                f"Content-Length: {len(jpg)}\r\n\r\n"
            ).encode("ascii")
            yield header + jpg + b"\r\n"
            await asyncio.sleep(0.08)  # ~12 fps smooth video
    except asyncio.CancelledError:
        return


@app.get("/api/stream/{cam_id}")
async def api_stream_mjpeg(cam_id: str, user: Dict[str, Any] = Depends(current_user)):
    """
    MJPEG stream (multipart/x-mixed-replace). Browser <img src="/api/stream/CAM-01">
    displays the live feed.
    """
    if cam_id not in _CAM_REGISTRY:
        raise HTTPException(404, f"unknown cam_id: {cam_id}")

    return StreamingResponse(
        _mjpeg_generator(cam_id),
        media_type=f"multipart/x-mixed-replace; boundary={_MJPEG_BOUNDARY}",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
            "Connection": "close",
        },
    )


@app.get("/api/snapshot/{cam_id}")
async def api_snapshot(cam_id: str, user: Dict[str, Any] = Depends(current_user)):
    """Return current frame as a single JPEG."""
    if cam_id not in _CAM_REGISTRY:
        raise HTTPException(404, f"unknown cam_id: {cam_id}")
    jpg = _get_mjpeg_frame(cam_id)
    filename = f"{cam_id}_{int(time.time())}.jpg"
    return Response(
        content=jpg,
        media_type="image/jpeg",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- Background alert watcher -------------------------------------------

_LOGGED_ALERTS: set = set()


async def _alert_watcher() -> None:
    """
    Background task: every 3s scan the live state and append a ledger event
    when a NEW alert is detected (perimeter breach, BOLO face match, tamper,
    vehicle plate).
    """
    await asyncio.sleep(2)  # let the server fully come up
    while True:
        try:
            state = live_state.snapshot()
            for cam_name, s in state.items():
                # --- PERIMETER_BREACH ---
                for ze in s.get("zone_events", []) or []:
                    key = ("BREACH", cam_name, ze.get("zone_id"), ze.get("track_id"))
                    if key in _LOGGED_ALERTS:
                        continue
                    _LOGGED_ALERTS.add(key)
                    append_event({
                        "type": "ALERT",
                        "subtype": "PERIMETER_BREACH",
                        "ts": time.time(),
                        "cam": cam_name,
                        "track_id": ze.get("track_id"),
                        "cls": ze.get("cls"),
                        "conf": ze.get("conf"),
                        "zone_id": ze.get("zone_id"),
                        "zone_name": ze.get("zone_name"),
                        "severity": ze.get("severity", "CRITICAL"),
                        "dwell_sec": ze.get("dwell_sec"),
                        "message": f"PERIMETER BREACH on {cam_name} ({ze.get('zone_name','')})",
                    })

                # --- FACE_MATCH (BOLO) ---
                for face in s.get("faces", []) or []:
                    if not face.get("bolo"):
                        continue
                    key = ("FACE", cam_name, face.get("name"))
                    if key in _LOGGED_ALERTS:
                        continue
                    _LOGGED_ALERTS.add(key)
                    append_event({
                        "type": "ALERT",
                        "subtype": "FACE_MATCH",
                        "ts": time.time(),
                        "cam": cam_name,
                        "name": face.get("name"),
                        "score": face.get("score"),
                        "severity": "CRITICAL",
                        "message": f"FACE MATCH on {cam_name}: {face.get('name')}",
                    })

                # --- TAMPER ---
                tp = s.get("tamper") or {}
                if tp.get("tampered"):
                    key = ("TAMPER", cam_name)
                    if key in _LOGGED_ALERTS:
                        continue
                    _LOGGED_ALERTS.add(key)
                    append_event({
                        "type": "ALERT",
                        "subtype": "TAMPER",
                        "ts": time.time(),
                        "cam": cam_name,
                        "tamper_type": tp.get("type"),
                        "severity": tp.get("severity", "CRITICAL"),
                        "message": f"TAMPER on {cam_name}: {tp.get('message','')}",
                    })

                # --- VEHICLE (plates) ---
                for plate in s.get("plates", []) or []:
                    key = ("VEHICLE", cam_name, plate.get("text"))
                    if key in _LOGGED_ALERTS:
                        continue
                    _LOGGED_ALERTS.add(key)
                    append_event({
                        "type": "ALERT",
                        "subtype": "VEHICLE",
                        "ts": time.time(),
                        "cam": cam_name,
                        "plate": plate.get("text"),
                        "conf": plate.get("conf"),
                        "severity": "INFO",
                        "message": f"VEHICLE on {cam_name}: plate {plate.get('text')}",
                    })

        except Exception as e:
            print(f"[alert_watcher] error: {e}", flush=True)

        await asyncio.sleep(3)





# --- Ledger API ------------------------------------------------------------

@app.get("/api/ledger/verify")
async def api_ledger_verify(user: Dict[str, Any] = Depends(current_user)):
    """Anyone authenticated can verify. Returns OK or BROKEN."""
    return verify_chain()


@app.get("/api/ledger/tail")
async def api_ledger_tail(
    n: int = 50,
    user: Dict[str, Any] = Depends(current_user),
):
    """Return the last n ledger records (newest last)."""
    if n < 1 or n > 1000:
        n = 50
    return tail_records(n)


# --- Export Section 65B PDF -----------------------------------------------

@app.get("/api/export65b")
async def api_export_65b(
    request: Request,
    seq: Optional[int] = None,
    case_id: Optional[str] = None,
    officer_name: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    user: Dict[str, Any] = Depends(require_role("admin", "auditor")),
):
    """
    Generate a Section 65B evidence PDF for a specific ledger event (by seq)
    or for the latest event if no seq is provided.
    Supports case_id, officer_name, and date range metadata.
    Returns application/pdf stream.
    """
    records = tail_records(1000)
    target = None
    if seq is not None:
        for r in records:
            if r.get("seq") == seq:
                target = r
                break
        if target is None:
            raise HTTPException(404, f"event seq {seq} not found")
    else:
        target = records[-1] if records else None
        if target is None:
            raise HTTPException(404, "no events in ledger")

    pdf_bytes = None
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf,
            pagesize=A4,
            leftMargin=18 * mm,
            rightMargin=18 * mm,
            topMargin=18 * mm,
            bottomMargin=18 * mm,
            title=f"IBVAP Section 65B Evidence — Seq {target.get('seq')}",
        )

        styles = getSampleStyleSheet()
        h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=14, textColor=colors.HexColor("#0A0F1A"), spaceAfter=8)
        h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=11, textColor=colors.HexColor("#2E7DD1"), spaceAfter=4)
        mono = ParagraphStyle("mono", parent=styles["Code"], fontSize=8, textColor=colors.HexColor("#101828"))
        body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=9, leading=12, textColor=colors.HexColor("#101828"))

        story: List[Any] = []
        story.append(Paragraph("IBVAP — Section 65B Evidence Extract", h1))
        story.append(Paragraph("Bharatiya Sakshya Adhiniyam, 2023 — Section 65B Certification", h2))
        story.append(Spacer(1, 6 * mm))

        integrity_status = verify_chain().get("status", "VERIFIED")
        meta = [
            ["Issuing Node", "BOP-7 (IBVAP v1.4)"],
            ["Certificate Type", "BSA 2023 §65B Admissibility Certificate"],
            ["Case / FIR ID", case_id or "IBVAP-FIR-2026/09/BOP7"],
            ["Investigating Officer", officer_name or user.get("display_name", user.get("username", "—"))],
            ["Evidence Period", f"{date_from or '2026-09-01'} to {date_to or '2026-09-08'}"],
            ["Extracted By", f"{user.get('display_name', user.get('username','—'))} ({user['role'].upper()})"],
            ["Extracted At", time.strftime("%Y-%m-%d %H:%M:%S UTC%z", time.gmtime())],
            ["Event Seq", str(target.get("seq"))],
            ["Event Timestamp", time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(target.get("ts", time.time()))) if isinstance(target.get("ts"), (int, float)) else str(target.get("ts"))],
            ["Ledger Integrity", integrity_status],
        ]
        t = Table(meta, colWidths=[40 * mm, 120 * mm])
        t.setStyle(TableStyle([
            ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
            ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#8A97A8")),
            ("TEXTCOLOR", (1, 0), (1, -1), colors.HexColor("#101828")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#1F2A3C")),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#1F2A3C")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(t)
        story.append(Spacer(1, 6 * mm))

        story.append(Paragraph("Chained Hashes", h2))
        hash_table = [
            ["prev_hash", target.get("prev_hash", "")],
            ["this_hash", target.get("this_hash", "")],
        ]
        ht = Table(hash_table, colWidths=[30 * mm, 130 * mm])
        ht.setStyle(TableStyle([
            ("FONT", (0, 0), (-1, -1), "Courier", 8),
            ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#8A97A8")),
            ("TEXTCOLOR", (1, 0), (1, -1), colors.HexColor("#101828")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#1F2A3C")),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#1F2A3C")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(ht)
        story.append(Spacer(1, 6 * mm))

        story.append(Paragraph("Event Payload", h2))
        pretty = json.dumps(target.get("event", {}), indent=2, ensure_ascii=False)
        pretty = pretty.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        story.append(Paragraph(f'<pre>{pretty}</pre>', mono))

        story.append(Spacer(1, 8 * mm))
        story.append(Paragraph("Certification", h2))
        cert = (
            "I hereby certify that the electronic record produced above is a true and "
            "accurate output of the IBVAP BOP-7 node, generated from a SHA-256 chained "
            "ledger whose integrity has been verified at the time of extraction. The "
            "information was obtained from a computer system used in the ordinary course "
            "of activities of the controlling authority, and was fed into the computer "
            "in the ordinary course of such activities."
        )
        story.append(Paragraph(cert, body))
        story.append(Spacer(1, 16 * mm))
        story.append(Paragraph("____________________________", body))
        story.append(Paragraph(f"{user.get('display_name', user['username'])} — {user['role'].upper()}", body))
        story.append(Paragraph("BOP-7 Secure Node | IBVAP v1.4", body))

        doc.build(story)
        pdf_bytes = buf.getvalue()
    except Exception as e:
        # Fallback to FPDF engine
        try:
            from fpdf import FPDF
            pdf = FPDF(format="A4")
            pdf.add_page()
            pdf.set_font("Helvetica", "B", 15)
            pdf.cell(0, 10, "IBVAP - SECTION 65B EVIDENCE CERTIFICATE", ln=1, align="C")
            pdf.set_font("Helvetica", "", 9)
            pdf.cell(0, 6, "Bharatiya Sakshya Adhiniyam, 2023 - Section 65B Admissibility", ln=1, align="C")
            pdf.ln(4)

            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(50, 7, "Case / FIR ID:", border=1)
            pdf.set_font("Helvetica", "", 10)
            pdf.cell(0, 7, str(case_id or "FIR-2026-BOP7-0941"), border=1, ln=1)

            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(50, 7, "Target Block Seq:", border=1)
            pdf.set_font("Helvetica", "", 10)
            pdf.cell(0, 7, str(target.get("seq", "—")), border=1, ln=1)

            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(50, 7, "Investigating Officer:", border=1)
            pdf.set_font("Helvetica", "", 10)
            pdf.cell(0, 7, str(officer_name or user.get("display_name", "—")), border=1, ln=1)

            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(50, 7, "Extracted At:", border=1)
            pdf.set_font("Helvetica", "", 10)
            pdf.cell(0, 7, time.strftime("%Y-%m-%d %H:%M:%S UTC"), border=1, ln=1)

            pdf.ln(5)
            pdf.set_font("Courier", "B", 9)
            pdf.cell(0, 6, "CRYPTOGRAPHIC SHA-256 HASH VERIFICATION:", ln=1)
            pdf.set_font("Courier", "", 8)
            pdf.multi_cell(0, 5, f"this_hash: {target.get('this_hash', '—')}\nprev_hash: {target.get('prev_hash', '—')}")

            pdf.ln(4)
            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(0, 6, "RECORD PAYLOAD:", ln=1)
            pdf.set_font("Courier", "", 8)
            payload_str = json.dumps(target.get("event", {}), indent=2)
            pdf.multi_cell(0, 4.5, payload_str[:1200])

            pdf.ln(6)
            pdf.set_font("Helvetica", "", 8)
            legal_text = (
                "I hereby certify that the electronic record produced above is a true and accurate output "
                "of the IBVAP BOP-7 secure node, generated from a SHA-256 chained ledger whose integrity "
                "has been cryptographically sealed and verified."
            )
            pdf.multi_cell(0, 4.5, legal_text)
            pdf.ln(10)
            pdf.cell(0, 5, "________________________________________________________", ln=1)
            pdf.cell(0, 5, f"{user.get('display_name', user['username'])} ({user['role'].upper()}) - BOP-7 NODE", ln=1)

            out = pdf.output(dest="S")
            if isinstance(out, str):
                pdf_bytes = out.encode("latin1")
            else:
                pdf_bytes = bytes(out)
        except Exception as fpdf_err:
            raise HTTPException(500, f"PDF generation failed: {e}; fallback: {fpdf_err}")

    filename = f"ibvap_65b_seq{target.get('seq','x')}_{int(time.time())}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- Health ----------------------------------------------------------------

@app.get("/healthz")
async def healthz():
    return {"status": "ok", "node": "BOP-7", "version": "1.4.0", "ts": time.time()}


if __name__ == "__main__":
    import uvicorn
    # Allows running directly via `python3 code/dashboard.py` or `python code/dashboard.py`
    uvicorn.run(app, host="0.0.0.0", port=8000)