"""OAuth2 Code flow for Saxo OpenAPI with local redirect listener + token cache.

Tokens are cached at ~/.saxo-mcp/tokens.json (or tokens-<SAXO_PROFILE>.json per profile) and auto-refreshed when near expiry.
Saxo refresh tokens on SIM are short-lived (roughly 1h, rolling) — if the server
is idle past the refresh window, you must re-run `saxo-mcp login`.
"""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

TOKEN_DIR = Path.home() / ".saxo-mcp"
TOKEN_FILE = TOKEN_DIR / "tokens.json"  # legacy alias; use _token_file() — this ignores SAXO_PROFILE

# M-1: serialise the refresh+save critical section. A 10-min auth_keepalive
# refresh and a 401-triggered refresh must not interleave and clobber the
# rolling refresh token (each successful refresh ROLLS it).
_REFRESH_LOCK = threading.Lock()


def _token_file() -> Path:
    """Token cache path, profile-aware. SAXO_PROFILE=<name> isolates token
    chains per application (e.g. squeeze-aimbot on its own SIM account/user
    vs regime-allocator on the default), so two apps never clobber each
    other's refresh chain. Unset -> legacy tokens.json (back-compatible).

    H-1: the profile is interpolated straight into a filename, so it MUST be a
    safe slug — reject anything outside [A-Za-z0-9_-]{1,64} to prevent a token
    file escaping TOKEN_DIR (e.g. SAXO_PROFILE='../../etc/x' or 'a/b')."""
    profile = os.getenv("SAXO_PROFILE", "").strip()
    if profile and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", profile):
        raise RuntimeError("SAXO_PROFILE must match [A-Za-z0-9_-]{1,64}")
    name = f"tokens-{profile}.json" if profile else "tokens.json"
    # Defense-in-depth: even a slug-clean name must resolve inside TOKEN_DIR.
    assert (TOKEN_DIR / name).resolve().parent == TOKEN_DIR.resolve()
    return TOKEN_DIR / name


_SIM_AUTH = "https://sim.logonvalidation.net"
_LIVE_AUTH = "https://live.logonvalidation.net"
_SIM_API = "https://gateway.saxobank.com/sim/openapi"
_LIVE_API = "https://gateway.saxobank.com/openapi"


# ---- environment helpers ----------------------------------------------------


def env() -> str:
    return os.getenv("SAXO_ENV", "sim").lower()


def auth_base() -> str:
    return _SIM_AUTH if env() == "sim" else _LIVE_AUTH


def api_base() -> str:
    return _SIM_API if env() == "sim" else _LIVE_API


def _creds() -> tuple[str, str]:
    key = os.getenv("SAXO_APP_KEY")
    secret = os.getenv("SAXO_APP_SECRET")
    if not key or not secret:
        raise RuntimeError(
            "SAXO_APP_KEY and SAXO_APP_SECRET must be set in .env. "
            "Get them from https://www.developer.saxo/openapi/appmanagement#/"
        )
    return key, secret


def _redirect_uri() -> str:
    port = os.getenv("SAXO_REDIRECT_PORT", "52736")
    return f"http://localhost:{port}/callback"


def _basic_auth_header() -> str:
    key, secret = _creds()
    raw = f"{key}:{secret}".encode()
    return "Basic " + base64.b64encode(raw).decode()


# ---- token cache ------------------------------------------------------------


def _save_tokens(tokens: dict) -> None:
    # M-4: do NOT mutate the caller's dict — persist a copy with obtained_at.
    to_write = {**tokens, "obtained_at": time.time()}
    # M-3: 0700 dir + 0600 file so the refresh token isn't world-readable
    # (no-op on Windows, correct on POSIX).
    TOKEN_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = _token_file()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(to_write, indent=2))


def _load_tokens() -> dict | None:
    if not _token_file().exists():
        return None
    try:
        return json.loads(_token_file().read_text())
    except json.JSONDecodeError:
        return None


# ---- local callback server --------------------------------------------------


class _CallbackHandler(BaseHTTPRequestHandler):
    code: str | None = None
    received_state: str | None = None
    error: str | None = None

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        if "code" in qs:
            _CallbackHandler.code = qs["code"][0]
            _CallbackHandler.received_state = qs.get("state", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<html><body style='font-family:sans-serif'>"
                b"<h2>Saxo login successful</h2>"
                b"<p>You can close this tab and return to the terminal.</p>"
                b"</body></html>"
            )
        elif "error" in qs:
            _CallbackHandler.error = qs.get("error_description", qs["error"])[0]
            self.send_response(400)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(f"Error: {_CallbackHandler.error}".encode())
        else:
            # Ignore favicon and other stray requests.
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args, **kwargs):  # silence default stderr logging
        pass


# ---- public API -------------------------------------------------------------


def login() -> None:
    """Run OAuth2 Code flow: open browser, catch redirect, exchange code."""
    key, _ = _creds()
    port = int(os.getenv("SAXO_REDIRECT_PORT", "52736"))
    state = secrets.token_urlsafe(16)

    params = {
        "response_type": "code",
        "client_id": key,
        "redirect_uri": _redirect_uri(),
        "state": state,
    }
    authorize_url = f"{auth_base()}/authorize?" + urllib.parse.urlencode(params)

    print(f"Opening browser for Saxo login ({env()})...")
    print(f"If it doesn't open, visit:\n  {authorize_url}\n")
    webbrowser.open(authorize_url)

    # Reset class-level state in case of a second login in the same process.
    _CallbackHandler.code = None
    _CallbackHandler.received_state = None
    _CallbackHandler.error = None

    httpd = HTTPServer(("localhost", port), _CallbackHandler)
    print(f"Listening on http://localhost:{port}/callback ...")
    while _CallbackHandler.code is None and _CallbackHandler.error is None:
        httpd.handle_request()

    if _CallbackHandler.error:
        raise RuntimeError(f"Saxo returned auth error: {_CallbackHandler.error}")
    if _CallbackHandler.received_state != state:
        raise RuntimeError("OAuth state mismatch — possible CSRF, aborting")

    code = _CallbackHandler.code
    _CallbackHandler.code = None  # clear after use

    resp = httpx.post(
        f"{auth_base()}/token",
        headers={
            "Authorization": _basic_auth_header(),
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": _redirect_uri(),
        },
        timeout=30,
    )
    if not resp.is_success:
        raise RuntimeError(f"Token exchange failed: {resp.status_code} {resp.text}")

    _save_tokens(resp.json())
    print(f"Tokens saved to {_token_file()}")


def _refresh(tokens: dict) -> dict:
    # M-1: hold _REFRESH_LOCK across the whole refresh+save so a keepalive
    # refresh and a 401-triggered refresh can't interleave and clobber the
    # rolling refresh token. Re-load the freshest token under the lock: if a
    # concurrent thread already rolled it while we waited, use its result
    # instead of replaying our (now-consumed) refresh token.
    with _REFRESH_LOCK:
        latest = _load_tokens() or tokens
        refresh_token = latest.get("refresh_token")
        if not refresh_token:
            raise RuntimeError("No refresh token cached — run `saxo-mcp login` again")

        resp = httpx.post(
            f"{auth_base()}/token",
            headers={
                "Authorization": _basic_auth_header(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            timeout=30,
        )
        if not resp.is_success:
            raise RuntimeError(
                f"Refresh failed ({resp.status_code}): {resp.text}\n"
                f"Run `saxo-mcp login` to re-authenticate."
            )
        new_tokens = resp.json()
        _save_tokens(new_tokens)
        return new_tokens


def get_access_token() -> str:
    """Return a valid access token, refreshing automatically if near expiry."""
    tokens = _load_tokens()
    if not tokens:
        raise RuntimeError("Not authenticated. Run: saxo-mcp login")

    obtained = tokens.get("obtained_at", 0)
    expires_in = tokens.get("expires_in", 0)
    # Refresh if within 60s of expiry (or already expired).
    if time.time() >= obtained + expires_in - 60:
        tokens = _refresh(tokens)
    return tokens["access_token"]


def status() -> dict:
    tokens = _load_tokens()
    if not tokens:
        return {"authenticated": False, "env": env()}
    obtained = tokens.get("obtained_at", 0)
    expires_in = tokens.get("expires_in", 0)
    remaining = max(0, int(obtained + expires_in - time.time()))
    return {
        "authenticated": True,
        "env": env(),
        "access_token_expires_in_seconds": remaining,
        "has_refresh_token": bool(tokens.get("refresh_token")),
        "token_file": str(_token_file()),
    }


def logout() -> None:
    tf = _token_file()
    if tf.exists():
        tf.unlink()
