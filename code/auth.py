"""
auth.py — JWT issuance and verification for IBVAP BOP-7 node.

Roles: admin | operator | auditor
  - admin   : full read/write, zone config, user management, export
  - operator: live view, zone edit, acknowledge events
  - auditor: read-only view + export + ledger verify (no zone edits)

Token is HS256-signed, 8h expiry, stored client-side in localStorage and
sent as Authorization: Bearer <token> on every fetch.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# In production this MUST be injected from env / vault.
_SECRET = os.environ.get("IBVAP_JWT_SECRET", "ibvap-bop7-dev-secret-CHANGE-ME")
_ALG = "HS256"
_EXP_SECONDS = 8 * 3600  # 8 hours

_USERS_PATH = Path(__file__).resolve().parent / "data" / "users.json"

# For password hashing we use PBKDF2-HMAC-SHA256 (no extra deps).
_PBKDF2_ITERS = 200_000
_SALT_LEN = 16


def _hash_password(password: str, salt: Optional[bytes] = None) -> str:
    """PBKDF2-HMAC-SHA256. Returns 'pbkdf2$<iters>$<hex salt>$<hex hash>'."""
    if salt is None:
        salt = os.urandom(_SALT_LEN)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERS)
    return f"pbkdf2${_PBKDF2_ITERS}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters_s, salt_hex, _ = stored.split("$")
        if algo != "pbkdf2":
            return False
        iters = int(iters_s)
        salt = bytes.fromhex(salt_hex)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters)
        expected = bytes.fromhex(stored.split("$")[3])
        # Constant-time compare.
        return digest == expected
    except Exception:
        return False


def _load_users() -> Dict[str, Dict[str, Any]]:
    """Load user store. Seeds default credentials on first run."""
    if not _USERS_PATH.exists():
        _USERS_PATH.parent.mkdir(parents=True, exist_ok=True)
        seed = {
            "admin": {
                "password": _hash_password("admin123"),
                "role": "admin",
                "display_name": "SYSADMIN",
                "node": "BOP-7",
            },
            "operator": {
                "password": _hash_password("op123"),
                "role": "operator",
                "display_name": "OPERATOR-01",
                "node": "BOP-7",
            },
            "auditor": {
                "password": _hash_password("audit123"),
                "role": "auditor",
                "display_name": "AUDITOR",
                "node": "BOP-7",
            },
        }
        _USERS_PATH.write_text(json.dumps(seed, indent=2), encoding="utf-8")
        return seed
    return json.loads(_USERS_PATH.read_text(encoding="utf-8"))


def authenticate(username: str, password: str) -> Optional[Dict[str, Any]]:
    """Returns user record (minus password hash) on success, None otherwise."""
    users = _load_users()
    user = users.get(username)
    if not user:
        return None
    if not user.get("active", True):
        return None
    if not _verify_password(password, user["password"]):
        return None
    user["last_login"] = time.strftime("%Y-%m-%d %H:%M:%S IST", time.localtime())
    try:
        _USERS_PATH.write_text(json.dumps(users, indent=2), encoding="utf-8")
    except Exception:
        pass
    return {
        "username": username,
        "role": user["role"],
        "display_name": user.get("display_name", username.upper()),
        "node": user.get("node", "BOP-7"),
    }


def list_users() -> List[Dict[str, Any]]:
    users = _load_users()
    res = []
    for uname, u in users.items():
        res.append({
            "username": uname,
            "role": u.get("role", "operator"),
            "display_name": u.get("display_name", uname.upper()),
            "node": u.get("node", "BOP-7"),
            "active": u.get("active", True),
            "last_login": u.get("last_login", "—"),
        })
    return res


def toggle_user_active(username: str, active: bool) -> bool:
    users = _load_users()
    if username not in users:
        return False
    users[username]["active"] = active
    _USERS_PATH.write_text(json.dumps(users, indent=2), encoding="utf-8")
    return True


def remove_user(username: str) -> bool:
    users = _load_users()
    if username not in users:
        return False
    del users[username]
    _USERS_PATH.write_text(json.dumps(users, indent=2), encoding="utf-8")
    return True


def issue_token(user: Dict[str, Any]) -> str:
    now = int(time.time())
    payload = {
        "sub": user["username"],
        "role": user["role"],
        "display_name": user.get("display_name", user["username"]),
        "node": user.get("node", "BOP-7"),
        "iat": now,
        "exp": now + _EXP_SECONDS,
    }
    return jwt.encode(payload, _SECRET, algorithm=_ALG)


def decode_token(token: str) -> Dict[str, Any]:
    """Raise HTTPException(401) on invalid/expired token."""
    try:
        payload = jwt.decode(token, _SECRET, algorithms=[_ALG])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Normalize: expose `username` as an alias of the standard JWT `sub`
    # claim so downstream code can use either.
    if "sub" in payload and "username" not in payload:
        payload["username"] = payload["sub"]
    return payload


# --- FastAPI dependency wiring ---------------------------------------------

_bearer = HTTPBearer(auto_error=False)


async def current_user(request: Request) -> Dict[str, Any]:
    """
    Dependency: extract & verify the Bearer token. Raises 401 if missing/invalid.

    Token sources (checked in order):
      1. Authorization: Bearer <token>   — for fetch() / API calls
      2. ?token=<token> query parameter — for <img src="/api/stream/..."> and
                                            <a download> links, which cannot
                                            set headers themselves.
      3. ibvap.token cookie             — for top-level page navigations
                                            (GET /operator etc.) where the
                                            browser cannot set Authorization
                                            on the document request itself.
    """
    auth = request.headers.get("Authorization", "")
    token = ""
    if auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
    if not token:
        token = request.query_params.get("token", "").strip()
    if not token:
        token = request.cookies.get("ibvap.token", "").strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return decode_token(token)


async def optional_user(request: Request) -> Optional[Dict[str, Any]]:
    """Extract & verify token if present, otherwise return None."""
    auth = request.headers.get("Authorization", "")
    token = ""
    if auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
    if not token:
        token = request.query_params.get("token", "").strip()
    if not token:
        token = request.cookies.get("ibvap.token", "").strip()
    if not token:
        return None
    try:
        return decode_token(token)
    except HTTPException:
        return None


def require_role(*roles: str):
    """
    Dependency factory: returns a FastAPI dependency that requires the
    caller's role to be in `roles`. Else raises 403 ACCESS DENIED.

    Usage:
        @app.post("/api/zones")
        async def api_post_zones(
            payload: dict,
            user: dict = Depends(require_role("admin", "operator")),
        ):
            ...
    """
    async def _check(user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
        if user["role"] not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"ACCESS DENIED — role '{user['role']}' not permitted for this action",
            )
        return user
    return _check
