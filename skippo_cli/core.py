"""Session management and constrained HTTP transport."""
import base64
import contextlib
import http.client
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from platformdirs import user_config_dir

API_KEY = "AIzaSyCoTfmf7CxX3IQ-d2vNRFzRfwPs-w5MCpw"
CLIENT = base64.b64encode(b"bpClient:nFGce2nYqgz6a6xK").decode()
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


def directory():
    path = Path(user_config_dir("skippo-cli"))
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name == "posix":
        path.chmod(0o700)
    return path


@contextlib.contextmanager
def locked():
    # Lock across read/refresh/write and logout so refresh cannot resurrect a session.
    path = directory() / "lock"
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        if os.name == "posix":
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        if os.name == "posix":
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def read(name):
    try:
        return json.loads((directory() / name).read_text())
    except FileNotFoundError:
        return {}
    except (ValueError, OSError):
        raise Error(f"Cannot read {name}; check local configuration.", 2, "config") from None


def save(name, obj):
    path = directory() / name
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w") as out:
            json.dump(obj, out)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(base, path, *, method="GET", payload=None, headers=None, form=False):
    if base not in (HUB, IDENTITY, TOKEN, FIRESTORE) or not path.startswith("/"):
        raise Error("Invalid API target.", 2, "config")
    clean_path = urllib.parse.urlsplit(path).path
    allowed = (
        (base == IDENTITY and method == "POST" and clean_path in ("/v1/accounts:signInWithPassword", "/v1/accounts:lookup"))
        or (base == FIRESTORE and method == "GET" and re.fullmatch(r"/v1/projects/nautical-app-se/databases/\(default\)/documents/users/[^/]+/tracks2026(?:/[^/]+)?", clean_path))
        or (base == TOKEN and method == "POST" and clean_path == "/v1/token")
        or (base == HUB and method == "GET" and (clean_path == "/boat-profiles" or re.fullmatch(r"/boat-profiles/[^/]+/(?:boat-events|notes)/all", clean_path)))
        or (base == HUB and method == "POST" and re.fullmatch(r"/boat-profiles/[^/]+/(?:base-data|home-harbor|engine|boat-events|notes/note)", clean_path))
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
        code = 3 if e.code in (401, 403) or (base in (IDENTITY, TOKEN) and e.code == 400) else 4 if e.code == 404 else 5
        error = Error(f"Service returned HTTP {e.code}.", code, "http_error")
        error.status = e.code
        raise error from None
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
        raise Error("Could not reach service; check your connection.", 5, "network") from None
    except (ValueError, UnicodeDecodeError):
        raise Error("Service returned invalid JSON.", 5, "service") from None


def login(email, password):
    result = request(IDENTITY, "/v1/accounts:signInWithPassword?key=" + API_KEY,
                     method="POST", payload={"email": email, "password": password,
                                             "returnSecureToken": True})
    try:
        session = {"id_token": result["idToken"], "refresh_token": result["refreshToken"],
                   "expires_at": time.time() + int(result["expiresIn"]), "uid": result.get("localId")}
    except (KeyError, TypeError, ValueError):
        raise Error("Invalid login response.", 5, "service") from None
    with locked():
        save("session.json", session)


def session(force=False):
    with locked():
        s = read("session.json")
        if not s.get("refresh_token") or not s.get("id_token"):
            raise Error("Not signed in. Run skippo auth login.", 3, "authentication")
        if force or s.get("expires_at", 0) <= time.time() + 60:
            result = request(TOKEN, "/v1/token?key=" + API_KEY, method="POST", form=True,
                             payload={"grant_type": "refresh_token", "refresh_token": s["refresh_token"]})
            try:
                s = {"id_token": result["id_token"], "refresh_token": result["refresh_token"],
                     "expires_at": time.time() + int(result["expires_in"]), "uid": result.get("user_id") or s.get("uid")}
            except (KeyError, TypeError, ValueError):
                raise Error("Invalid token refresh response.", 3, "authentication") from None
            save("session.json", s)
        return s


def logout():
    with locked():
        for name in ("session.json", "config.json"):
            (directory() / name).unlink(missing_ok=True)


def hub(path, method="GET", payload=None):
    s = session()
    headers = {"id-token": s["id_token"], "target": "SE", "Authorization": "Basic " + CLIENT}
    try:
        return request(HUB, path, method=method, payload=payload, headers=headers)
    except Error as e:
        if method == "GET" and e.code == 3:
            s = session(force=True)
            headers["id-token"] = s["id_token"]
            return request(HUB, path, headers=headers)
        raise


def firestore(path):
    s = session()
    if not s.get("uid"):
        with locked():
            s = read("session.json")
            lookup = request(IDENTITY, "/v1/accounts:lookup?key=" + API_KEY, method="POST", payload={"idToken": s["id_token"]})
            try:
                s["uid"] = lookup["users"][0]["localId"]
            except (KeyError, IndexError, TypeError):
                raise Error("Could not identify account for trips.", 3, "authentication") from None
            save("session.json", s)
    prefix = "/v1/projects/nautical-app-se/databases/(default)/documents/users/" + urllib.parse.quote(s["uid"], safe="") + "/tracks2026"
    try:
        return request(FIRESTORE, prefix + path, headers={"Authorization": "Bearer " + s["id_token"]})
    except Error as e:
        if getattr(e, "status", None) == 403:
            raise Error("Trips access was denied by the service for this account.", 5, "permission_denied") from None
        if getattr(e, "status", None) == 401:
            s = session(force=True)
            return request(FIRESTORE, prefix + path, headers={"Authorization": "Bearer " + s["id_token"]})
        raise
