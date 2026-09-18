"""Checks for, verifies, stages and applies Vigil updates.

Runs inside the WIDGET only, on a background thread. The hook never imports
this: it runs on every agent event and must stay fast and offline.

The flow, and the one rule it is built around:

    check()  - once a day, ask vigilit.app whether a newer version exists.
               Also collects live settings (see vigil_remote).
    stage()  - on the user's click: download, then VERIFY, then unpack into
               ~/.vigil/app.next. Nothing is ever unpacked before it verifies.
    apply()  - on restart: a small script swaps app.next into place, keeps the
               old version as app.prev, and rolls back if the swap fails.

Verification is two checks, both required: the SHA-256 of the download must
match the manifest, and that digest must carry a valid Ed25519 signature from
the key in vigil_version.RELEASE_PUBLIC_KEY. The private half of that key never
leaves the publisher's machine, so a compromised website, database or storage
bucket still cannot get code onto a user's computer.

Every failure is quiet and leaves the installed version untouched.
"""
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile

import vigil_remote
from vigil_version import RELEASE_PUBLIC_KEY, UPDATE_URL, VERSION

CHECK_EVERY = 20 * 3600          # at most one check a day, give or take
TIMEOUT = 15
MAX_BYTES = 90 * 1024 * 1024     # hard ceiling on any download
STAGED_MARKER = ".vigil-staged"  # written LAST, only after a verified unpack

# Only these may be unpacked from a release zip. Anything else is ignored,
# and anything that tries to escape the target folder aborts the update.
_ALLOWED_ROOTS = ("Vigil.exe", "_internal/", "hook/", "README.txt", "Uninstall Vigil.bat")


# ─────────────────────────────────────────────────────────── locations
def _data_dir():
    d = os.environ.get("VIGIL_DATA_DIR") or os.path.join(os.path.expanduser("~"), ".vigil")
    os.makedirs(d, exist_ok=True)
    return d


def _install_dir():
    return os.path.join(os.path.expanduser("~"), ".vigil", "app")


def _state_path():
    return os.path.join(_data_dir(), "update_state.json")


def installed():
    """True only for a packaged build running from the standard install dir.

    Running from source, or straight out of an extracted zip, must never try to
    replace itself.
    """
    if not getattr(sys, "frozen", False):
        return False
    here = os.path.normcase(os.path.dirname(os.path.abspath(sys.executable)))
    return here == os.path.normcase(_install_dir())


# ─────────────────────────────────────────────────────────── helpers
def _newer(a, b):
    """True if version a is newer than version b."""
    try:
        return tuple(int(x) for x in a.split(".")) > tuple(int(x) for x in b.split("."))
    except Exception:
        return False


def _load_state():
    try:
        with open(_state_path(), encoding="utf-8") as f:
            s = json.load(f)
        return s if isinstance(s, dict) else {}
    except Exception:
        return {}


def _save_state(s):
    tmp = _state_path() + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(s, f)
        os.replace(tmp, _state_path())
    except Exception:
        pass


def _valid_manifest(m):
    if not isinstance(m, dict):
        return False
    need = {"version": str, "sha256": str, "signature": str, "url": str}
    if any(not isinstance(m.get(k), t) for k, t in need.items()):
        return False
    if not m["url"].startswith("https://"):
        return False
    if len(m["sha256"]) != 64:
        return False
    return _newer(m["version"], VERSION)


# ─────────────────────────────────────────────────────────── check
def check(force=False, channel="stable"):
    """Ask for the latest version. Returns the manifest if newer, else None.

    Also refreshes live settings. Throttled to once per CHECK_EVERY unless
    forced. Any network or parse failure returns the last cached result.
    """
    state = _load_state()
    now = time.time()
    if not force and now - state.get("last_check", 0) < CHECK_EVERY:
        latest = state.get("latest")
        return latest if _valid_manifest(latest) else None

    query = urllib.parse.urlencode({"v": VERSION, "channel": channel})
    req = urllib.request.Request(
        f"{UPDATE_URL}?{query}",
        headers={"User-Agent": f"Vigil/{VERSION}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = json.loads(r.read(256 * 1024).decode("utf-8"))
    except Exception:
        latest = state.get("latest")
        return latest if _valid_manifest(latest) else None

    vigil_remote.save(body.get("config") if isinstance(body, dict) else None)
    latest = body.get("latest") if isinstance(body, dict) else None
    latest = latest if _valid_manifest(latest) else None

    state.update(last_check=now, latest=latest)
    _save_state(state)
    return latest


# ─────────────────────────────────────────────────────────── verify
def verify(path, sha256_hex, signature_b64):
    """Raise unless the file matches the hash AND the hash is signed by us."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    if h.hexdigest() != sha256_hex.lower():
        raise ValueError("download does not match the published hash")

    key = Ed25519PublicKey.from_public_bytes(base64.b64decode(RELEASE_PUBLIC_KEY))
    try:
        key.verify(base64.b64decode(signature_b64), h.digest())
    except InvalidSignature:
        raise ValueError("update signature is not valid — refusing to install")


def _safe_extract(zip_path, dest):
    """Unpack only known files, and never anything outside `dest`."""
    dest_real = os.path.realpath(dest)
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or ":" in name or ".." in name.split("/"):
                raise ValueError(f"unsafe path in update: {name!r}")
            if not any(name == r or name.startswith(r) for r in _ALLOWED_ROOTS):
                continue
            target = os.path.realpath(os.path.join(dest, name))
            if not target.startswith(dest_real + os.sep):
                raise ValueError(f"unsafe path in update: {name!r}")
            if info.is_dir():
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)


# ─────────────────────────────────────────────────────────── stage
def stage(manifest, progress=None):
    """Download, verify, and unpack an update next to the install.

    Returns the staged version. Raises with a human-readable message on any
    failure; the installed version is never touched here.
    """
    if not installed():
        raise RuntimeError("updates only apply to an installed copy of Vigil")
    if not _valid_manifest(manifest):
        raise ValueError("the update information is incomplete")

    version = manifest["version"]
    updates = os.path.join(_data_dir(), "updates")
    os.makedirs(updates, exist_ok=True)
    part = os.path.join(updates, f"Vigil-{version}.zip.part")

    expected = manifest.get("size") if isinstance(manifest.get("size"), int) else None
    limit = min(MAX_BYTES, expected + 1024) if expected else MAX_BYTES

    req = urllib.request.Request(manifest["url"], headers={"User-Agent": f"Vigil/{VERSION}"})
    got = 0
    with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as out:
        for chunk in iter(lambda: r.read(1 << 16), b""):
            got += len(chunk)
            if got > limit:
                raise ValueError("update is larger than expected — refusing it")
            out.write(chunk)
            if progress and expected:
                progress(got / expected)

    try:
        verify(part, manifest["sha256"], manifest["signature"])

        nxt = _install_dir() + ".next"
        if os.path.exists(nxt):
            shutil.rmtree(nxt, ignore_errors=True)
        os.makedirs(nxt)
        _safe_extract(part, nxt)
        for required in ("Vigil.exe", os.path.join("hook", "vigil-hook.exe")):
            if not os.path.isfile(os.path.join(nxt, required)):
                raise ValueError(f"update is missing {required}")

        # The marker is the commit point. apply() refuses a folder without it,
        # so a crash halfway through unpacking can never be installed.
        with open(os.path.join(nxt, STAGED_MARKER), "w", encoding="utf-8") as f:
            f.write(version)
    except Exception:
        shutil.rmtree(_install_dir() + ".next", ignore_errors=True)
        raise
    finally:
        try:
            os.remove(part)
        except OSError:
            pass

    state = _load_state()
    state["staged"] = version
    _save_state(state)
    return version


def staged_version():
    """The verified version waiting in app.next, or None."""
    marker = os.path.join(_install_dir() + ".next", STAGED_MARKER)
    try:
        with open(marker, encoding="utf-8") as f:
            v = f.read().strip()
        return v if _newer(v, VERSION) else None
    except Exception:
        return None


# ─────────────────────────────────────────────────────────── apply
_SWAP = r"""@echo off
rem Written by Vigil. Swaps a verified update into place, keeps the previous
rem version, and rolls back if anything fails. Safe to delete.
setlocal
set "APP=%USERPROFILE%\.vigil\app"
set "NEXT=%APP%.next"
set "PREV=%APP%.prev"
set /a WAITED=0
cd /d "%USERPROFILE%"

:wait
tasklist /FI "IMAGENAME eq Vigil.exe" 2>nul | find /I "Vigil.exe" >nul
if errorlevel 1 goto ready
set /a WAITED+=1
if %WAITED% GEQ 40 goto abort
ping -n 2 127.0.0.1 >nul
goto wait

:ready
if not exist "%NEXT%\.vigil-staged" goto abort
if exist "%PREV%" rmdir /s /q "%PREV%"
set /a TRIES=0

:swap
rem A hook call from the agent can hold a file open for a moment. Retry.
move "%APP%" "%PREV%" >nul 2>&1
if not errorlevel 1 goto moved
set /a TRIES+=1
if %TRIES% GEQ 20 goto abort
ping -n 2 127.0.0.1 >nul
goto swap

:moved
move "%NEXT%" "%APP%" >nul 2>&1
if errorlevel 1 goto rollback
del /q "%APP%\.vigil-staged" >nul 2>&1
start "" "%APP%\Vigil.exe"
exit /b 0

:rollback
move "%PREV%" "%APP%" >nul 2>&1

:abort
if exist "%APP%\Vigil.exe" start "" "%APP%\Vigil.exe"
exit /b 1
"""


def apply():
    """Launch the swap script. The caller must quit the app straight after.

    Returns False if nothing verified is staged, in which case nothing happens.
    """
    if not installed() or not staged_version():
        return False
    script = os.path.join(_data_dir(), "apply-update.cmd")
    with open(script, "w", encoding="ascii", newline="\r\n") as f:
        f.write(_SWAP)
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    # cwd must NOT be inside the install dir, or Windows refuses the move.
    subprocess.Popen(["cmd", "/c", script], cwd=os.path.expanduser("~"),
                     creationflags=flags, close_fds=True)
    return True


def cleanup():
    """Run at startup: remove the previous version once the new one is up."""
    if not installed():
        return
    shutil.rmtree(_install_dir() + ".prev", ignore_errors=True)
    state = _load_state()
    if state.get("staged") and not staged_version():
        state.pop("staged", None)
        _save_state(state)
