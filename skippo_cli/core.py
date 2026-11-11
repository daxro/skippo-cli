"""Session management and constrained HTTP transport."""
import base64
import contextlib
import http.client
import json
import math
import os
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from platformdirs import user_config_dir

HUB = "https://nautical-hub.skippo.io"
IDENTITY = "https://identitytoolkit.googleapis.com"
TOKEN = "https://securetoken.googleapis.com"
FIRESTORE = "https://firestore.googleapis.com"
MAX_RESPONSE = 8 * 1024 * 1024
REQUEST_TIMEOUT = 30


class Error(Exception):
    def __init__(self, message, code=1, kind="error"):
        super().__init__(message)
        self.code, self.kind = code, kind
        self.status = None
        self.reason = None


def directory():
    try:
        path = Path(user_config_dir("skippo-cli"))
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name == "posix":
            path.chmod(0o700)
    except (OSError, ValueError):
        raise Error("Cannot access local configuration; check its directory and permissions.", 2, "config") from None
    return path


@contextlib.contextmanager
def locked():
    # Lock across read/refresh/write and logout so refresh cannot resurrect a session.
    path = directory() / "lock"
    fd = None
    try:
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        if os.name == "posix":
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX)
    except OSError:
        if fd is not None:
            os.close(fd)
        raise Error("Cannot lock local configuration; check its permissions.", 2, "config") from None
    try:
        yield
    finally:
        # Closing the descriptor also releases its advisory lock.
        os.close(fd)


def read(name):
    try:
        result = json.loads((directory() / name).read_text())
        if not isinstance(result, dict):
            raise TypeError
        return result
    except FileNotFoundError:
        return {}
    except (TypeError, ValueError, OSError):
        raise Error(f"Cannot read {name}; check local configuration.", 2, "config") from None


def save(name, obj):
    path = directory() / name
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        with os.fdopen(fd, "w") as out:
            json.dump(obj, out)
        os.replace(tmp, path)
    except OSError:
        raise Error(f"Cannot save {name}; check local configuration permissions.", 2, "config") from None
    finally:
        if tmp is not None:
            with contextlib.suppress(OSError):
                os.unlink(tmp)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# Only expose known provider codes. Arbitrary server messages can contain secrets.
PROVIDER_REASONS = {
    "EMAIL_NOT_FOUND", "INVALID_PASSWORD", "INVALID_LOGIN_CREDENTIALS",
    "INVALID_EMAIL", "USER_DISABLED", "USER_NOT_FOUND", "INVALID_ID_TOKEN",
    "TOKEN_EXPIRED", "INVALID_REFRESH_TOKEN", "USER_TOKEN_EXPIRED",
    "TOO_MANY_ATTEMPTS_TRY_LATER", "OPERATION_NOT_ALLOWED", "MISSING_PASSWORD",
    "PERMISSION_DENIED", "NOT_FOUND", "INVALID_ARGUMENT", "UNAUTHENTICATED",
    "RESOURCE_EXHAUSTED", "INTERNAL", "UNAVAILABLE", "DEADLINE_EXCEEDED",
}


def http_error(error, *, authentication=False, service="Service"):
    code = 3 if error.code in (401, 403) or (authentication and error.code == 400) else 4 if error.code == 404 else 5
    reason = None
    try:
        body = error.read(65537)
        if len(body) <= 65536:
            data = json.loads(body)
            item = data.get("error", {}) if isinstance(data, dict) else {}
            if isinstance(item, dict):
                # Firebase can append account-specific details after a colon.
                candidates = [item.get("message"), item.get("status")]
                for candidate in candidates:
                    if isinstance(candidate, str):
                        candidate = candidate.split(":", 1)[0].strip()
                        if candidate in PROVIDER_REASONS:
                            reason = candidate
                            break
    except (ValueError, OSError, UnicodeDecodeError, http.client.HTTPException):
        pass
    message = f"{service} returned HTTP {error.code}"
    if reason:
        message += f" ({reason})"
    result = Error(message + ".", code, "http_error")
    result.status, result.reason = error.code, reason
    return result


def request(base, path, *, method="GET", payload=None, headers=None, form=False):
    if base not in (HUB, IDENTITY, TOKEN, FIRESTORE) or not path.startswith("/"):
        raise Error("Invalid API target.", 2, "config")
    clean_path = urllib.parse.urlsplit(path).path
    allowed = (
        (base == IDENTITY and method == "POST" and clean_path in ("/v1/accounts:signInWithPassword", "/v1/accounts:lookup"))
        or (base == FIRESTORE and method == "GET" and re.fullmatch(r"/v1/projects/nautical-app-se/databases/\(default\)/documents/users/[^/]+/tracks2026(?:/[^/]+)?", clean_path))
        or (base == TOKEN and method == "POST" and clean_path == "/v1/token")
        or (base == HUB and method == "GET" and (clean_path in ("/boat-profiles", "/insurances/companies/list") or re.fullmatch(r"/boat-profiles/[^/]+/(?:boat-events|notes)/all", clean_path)))
        or (base == HUB and method == "POST" and re.fullmatch(r"/boat-profiles/[^/]+/(?:base-data|home-harbor|engine|safety|boat-events|notes/note|navigation-settings|boat-insurance)", clean_path))
        or (base == HUB and method == "POST" and re.fullmatch(r"/checklists/[^/]+/item", clean_path))
        or (base == HUB and method == "DELETE" and (re.fullmatch(r"/checklists/item/[^/]+", clean_path) or re.fullmatch(r"/boat-profiles/[^/]+/(?:boat-events/event|boat-insurance/insurance)/[^/]+", clean_path)))
        or (base == HUB and method == "PUT" and re.fullmatch(r"/checklists/item/[^/]+", clean_path))
        or (base == HUB and method == "DELETE" and re.fullmatch(r"/boat-profiles/[^/]+/notes/note/[^/]+", clean_path))
    )
    if not allowed:
        raise Error("API operation is not allowed.", 2, "config")
    data = None
    hdr = dict(headers or {})
    if payload is not None:
        data = (urllib.parse.urlencode(payload).encode() if form else json.dumps(payload).encode())
        hdr["Content-Type"] = "application/x-www-form-urlencoded" if form else "application/json"
    req = urllib.request.Request(base + path, data=data, headers=hdr, method=method)
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=REQUEST_TIMEOUT) as res:
            raw = res.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise Error("Service response exceeded size limit.", 5, "service")
        return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raise http_error(e, authentication=base in (IDENTITY, TOKEN)) from None
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
        raise Error("Could not reach service; check your connection.", 5, "network") from None
    except (ValueError, UnicodeDecodeError):
        raise Error("Service returned invalid JSON.", 5, "service") from None


def _session_response(result, *, refresh=False, previous=None):
    """Validate an authentication reply completely before replacing local state."""
    try:
        if not isinstance(result, dict):
            raise TypeError
        id_token = result["id_token" if refresh else "idToken"]
        refresh_token = result["refresh_token" if refresh else "refreshToken"]
        for token in (id_token, refresh_token):
            if (not isinstance(token, str) or not token
                    or any(not 33 <= ord(c) <= 126 for c in token)):
                raise ValueError
        lifetime = result["expires_in" if refresh else "expiresIn"]
        if isinstance(lifetime, bool) or not isinstance(lifetime, (str, int)):
            raise TypeError
        if isinstance(lifetime, str) and not re.fullmatch(r"[0-9]{1,16}", lifetime):
            raise ValueError
        seconds = int(lifetime)
        expires_at = time.time() + seconds
        if seconds <= 0 or not math.isfinite(expires_at):
            raise ValueError
        uid = (result.get("user_id", (previous or {}).get("uid")) if refresh
               else result.get("localId"))
        if uid is not None and (not isinstance(uid, str) or not uid or any(c.isspace() for c in uid)):
            raise ValueError
        return {"id_token": id_token, "refresh_token": refresh_token,
                "expires_at": expires_at, "uid": uid}
    except (KeyError, TypeError, ValueError, OverflowError):
        label = "token refresh" if refresh else "login"
        raise Error(f"Invalid {label} response; existing session was not changed.", 5, "service") from None


def login(email, password):
    from .public_config import api_key
    result = request(IDENTITY, "/v1/accounts:signInWithPassword?key=" + urllib.parse.quote(api_key(), safe=""),
                     method="POST", payload={"email": email, "password": password,
                                             "returnSecureToken": True})
    session = _session_response(result)
    with locked():
        save("session.json", session)


def session(force=False):
    from .public_config import api_key
    with locked():
        s = read("session.json")
        if not s.get("refresh_token") or not s.get("id_token"):
            raise Error("Not signed in. Run skippo auth login.", 3, "authentication")
        expiry = s.get("expires_at", 0)
        if isinstance(expiry, bool) or not isinstance(expiry, (int, float)) or not math.isfinite(expiry):
            raise Error("Invalid local session expiry; run skippo auth login.", 2, "config")
        if force or expiry <= time.time() + 60:
            result = request(TOKEN, "/v1/token?key=" + urllib.parse.quote(api_key(), safe=""), method="POST", form=True,
                             payload={"grant_type": "refresh_token", "refresh_token": s["refresh_token"]})
            s = _session_response(result, refresh=True, previous=s)
            save("session.json", s)
        return s


def logout():
    with locked():
        try:
            for name in ("session.json", "config.json"):
                (directory() / name).unlink(missing_ok=True)
        except OSError:
            raise Error("Cannot remove local session; check configuration permissions.", 2, "config") from None


def client_header():
    from .public_config import client
    return 'Basic ' + base64.b64encode(client().encode()).decode()


def hub(path, method="GET", payload=None):
    s = session()
    headers = {"id-token": s["id_token"], "target": "SE", "Authorization": client_header()}
    try:
        return request(HUB, path, method=method, payload=payload, headers=headers)
    except Error as e:
        if method == "GET" and e.code == 3:
            s = session(force=True)
            headers["id-token"] = s["id_token"]
            return request(HUB, path, headers=headers)
        raise


def firestore(path):
    from .public_config import api_key
    s = session()
    if not s.get("uid"):
        with locked():
            s = read("session.json")
            lookup = request(IDENTITY, "/v1/accounts:lookup?key=" + urllib.parse.quote(api_key(), safe=""), method="POST", payload={"idToken": s["id_token"]})
            try:
                s["uid"] = lookup["users"][0]["localId"]
            except (KeyError, IndexError, TypeError):
                raise Error("Could not identify account for trips.", 3, "authentication") from None
            save("session.json", s)
    prefix = "/v1/projects/nautical-app-se/databases/(default)/documents/users/" + urllib.parse.quote(s["uid"], safe="") + "/tracks2026"
    for attempt in range(2):
        try:
            return request(FIRESTORE, prefix + path, headers={"Authorization": "Bearer " + s["id_token"]})
        except Error as e:
            if getattr(e, "status", None) == 403:
                denied = Error("Trips access was denied by the service for this account.", 5, "permission_denied")
                denied.status, denied.reason = e.status, e.reason
                raise denied from None
            if getattr(e, "status", None) == 401 and attempt == 0:
                s = session(force=True)
                continue
            raise
