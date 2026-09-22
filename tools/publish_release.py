"""Sign, upload and go live with a Vigil release — plus live settings.

Run these in YOUR terminal. Each one asks for your vigilit.app password; it is
sent only to Supabase to sign you in and is never saved or printed.

    python tools/publish_release.py upload [--notes "What changed"]
        Signs dist/Vigil-<version>-windows.zip with your private key, uploads
        it, and records it as a DRAFT. Nobody sees a draft.

    python tools/publish_release.py publish 0.2.0
        Makes that version live. New downloads get it, and every installed
        copy offers it within a day.

    python tools/publish_release.py unpublish 0.2.0
        Takes a bad release back down. Copies that already installed it keep
        it; everyone else stops being offered it.

    python tools/publish_release.py message "Text shown in the tray menu"
    python tools/publish_release.py message --clear
    python tools/publish_release.py approvals off|on
        Live settings, picked up at each installed copy's next daily check.
        "approvals off" is the kill switch: Vigil stops answering permission
        requests and every agent shows its own prompt instead.

    python tools/publish_release.py status
        What is live, what is drafted, and the current settings.

Only an account listed in admin_emails can do any of this; the database
refuses everyone else, whatever this script says.
"""
import argparse
import base64
import getpass
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from vigil_version import RELEASE_PUBLIC_KEY, VERSION  # noqa: E402

SUPABASE_URL = "https://wanzdgzxytkjazhdmnzw.supabase.co"
PUBLISHABLE_KEY = "sb_publishable_0LzaFdVmAh_C3FXTnDCbvQ_eRzQzDzh"   # public by design
ADMIN_EMAIL = os.environ.get("VIGIL_ADMIN_EMAIL", "adityanair.737@gmail.com")
KEY_PATH = Path(os.environ.get(
    "VIGIL_SIGNING_KEY",
    Path.home() / ".vigil-signing" / "release-private.pem"))


# ─────────────────────────────────────────────────────────── http
def call(method, path, token=None, body=None, headers=None, raw=None):
    h = {"apikey": PUBLISHABLE_KEY}
    if token:
        h["Authorization"] = f"Bearer {token}"
    data = raw
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    h.update(headers or {})
    req = urllib.request.Request(SUPABASE_URL + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            text = r.read().decode() or "null"
            return json.loads(text)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:400]
        sys.exit(f"{method} {path.split('?')[0]} failed ({e.code}): {detail}")


def sign_in():
    print(f"Signing in to vigilit.app as {ADMIN_EMAIL}")
    password = getpass.getpass("Password (not shown): ")
    res = call("POST", "/auth/v1/token?grant_type=password",
               body={"email": ADMIN_EMAIL, "password": password})
    del password
    token = res.get("access_token") if isinstance(res, dict) else None
    if not token:
        sys.exit("Sign-in failed.")
    return token


def rest(method, table, token, query="", body=None):
    return call(method, f"/rest/v1/{table}{query}", token, body,
                headers={"Prefer": "return=representation"})


# ─────────────────────────────────────────────────────────── signing
def sign(digest):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    if not KEY_PATH.exists():
        sys.exit(f"Signing key not found at {KEY_PATH}. Restore it from your backup.")
    pem = KEY_PATH.read_bytes()
    # An encrypted key is the norm; an old unencrypted one still works, with
    # a nudge, so nobody is locked out of publishing by this change.
    encrypted = b"ENCRYPTED" in pem[:200]
    if not encrypted:
        print("Note: your signing key is stored unencrypted. Add a passphrase "
              "with: python tools/release_keygen.py --encrypt")
    try:
        key = serialization.load_pem_private_key(
            pem,
            password=(getpass.getpass("Signing key passphrase: ").encode()
                      if encrypted else None))
    except Exception:
        sys.exit("That passphrase did not open the signing key. "
                 "Nothing was uploaded.")
    if not isinstance(key, Ed25519PrivateKey):
        sys.exit("The signing key is not an Ed25519 key.")

    # Refuse to publish something installed copies would reject.
    pub = key.public_key().public_bytes(serialization.Encoding.Raw,
                                        serialization.PublicFormat.Raw)
    if base64.b64encode(pub).decode() != RELEASE_PUBLIC_KEY:
        sys.exit("This private key does not match RELEASE_PUBLIC_KEY in "
                 "app/vigil_version.py. Installed copies would reject the update.")
    sig = key.sign(digest)
    key.public_key().verify(sig, digest)
    return base64.b64encode(sig).decode()


# ─────────────────────────────────────────────────────────── commands
def cmd_upload(args):
    zip_path = ROOT / "dist" / f"Vigil-{VERSION}-windows.zip"
    if not zip_path.exists():
        sys.exit(f"{zip_path.name} not found. Run: python tools/build_release.py")
    data = zip_path.read_bytes()
    digest = hashlib.sha256(data).digest()
    signature = sign(digest)
    print(f"Signed Vigil {VERSION}: {len(data) / 1048576:.1f} MB, sha256 {digest.hex()[:16]}…")

    token = sign_in()
    storage_path = f"{VERSION}/{zip_path.name}"
    print("Uploading…")
    call("POST", f"/storage/v1/object/builds/{storage_path}", token, raw=data,
         headers={"Content-Type": "application/zip", "x-upsert": "true"})

    row = dict(version=VERSION, channel=args.channel, notes=args.notes,
               storage_path=storage_path, sha256=digest.hex(), signature=signature,
               size_bytes=len(data))
    existing = rest("GET", "releases", token,
                    f"?version=eq.{VERSION}&channel=eq.{args.channel}&select=id,published")
    if existing:
        if existing[0]["published"]:
            sys.exit(f"{VERSION} is already live. Bump VERSION for a new release; "
                     "never change a published build in place.")
        rest("PATCH", "releases", token, f"?id=eq.{existing[0]['id']}", row)
    else:
        rest("POST", "releases", token, body=dict(row, published=False))
    print(f"\nDraft saved. To go live:\n  python tools/publish_release.py publish {VERSION}")


def set_published(args, value):
    token = sign_in()
    rows = rest("PATCH", "releases", token,
                f"?version=eq.{args.version}&channel=eq.{args.channel}",
                {"published": value})
    if not rows:
        sys.exit(f"No {args.channel} release {args.version} (or you are not an admin).")
    print(f"{args.version} is now {'LIVE' if value else 'unpublished'}.")


def set_config(key, value):
    token = sign_in()
    rows = rest("PATCH", "remote_config", token, f"?key=eq.{key}", {"value": value})
    if not rows:
        sys.exit(f"Could not change {key} (are you signed in as an admin?).")
    print(f"{key} = {json.dumps(value)}. Installed copies pick this up within a day.")


def cmd_status(_args):
    token = sign_in()
    for r in rest("GET", "releases", token,
                  "?select=version,channel,published,size_bytes,created_at"
                  "&order=version_key.desc&limit=10"):
        state = "LIVE " if r["published"] else "draft"
        print(f"  {state}  {r['channel']:<6} {r['version']:<10} "
              f"{(r['size_bytes'] or 0) / 1048576:5.1f} MB  {r['created_at'][:10]}")
    for c in rest("GET", "remote_config", token, "?select=key,value&order=key"):
        print(f"  config  {c['key']} = {json.dumps(c['value'])}")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    u = sub.add_parser("upload")
    u.add_argument("--notes", default=None)
    u.add_argument("--channel", default="stable", choices=["stable", "beta"])
    for name in ("publish", "unpublish"):
        s = sub.add_parser(name)
        s.add_argument("version")
        s.add_argument("--channel", default="stable", choices=["stable", "beta"])
    m = sub.add_parser("message")
    m.add_argument("text", nargs="?")
    m.add_argument("--clear", action="store_true")
    a = sub.add_parser("approvals")
    a.add_argument("state", choices=["on", "off"])
    sub.add_parser("status")

    args = p.parse_args()
    if args.cmd == "upload":
        cmd_upload(args)
    elif args.cmd == "publish":
        set_published(args, True)
    elif args.cmd == "unpublish":
        set_published(args, False)
    elif args.cmd == "message":
        if args.clear == bool(args.text):
            sys.exit('Give a message, or --clear.')
        if args.text and len(args.text) > 200:
            sys.exit("Keep it under 200 characters; longer is cut off in the app.")
        set_config("message", None if args.clear else args.text)
    elif args.cmd == "approvals":
        set_config("approvals_enabled", args.state == "on")
    elif args.cmd == "status":
        cmd_status(args)


if __name__ == "__main__":
    main()
