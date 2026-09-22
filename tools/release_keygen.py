r"""Create — or encrypt — the Ed25519 key that signs every Vigil release.

    python tools/release_keygen.py            create the key (run ONCE, ever)
    python tools/release_keygen.py --encrypt  put a passphrase on an existing key

Every installed copy of Vigil carries the matching PUBLIC key and refuses to
install an update whose signature does not verify. So this private key is the
single thing that can push code onto users' machines:

  * LOSE it  -> you can never ship another auto-update to existing installs.
               Everyone would have to download a fresh build by hand.
  * LEAK it  -> anyone holding it can push malware to every user.

Because of that second line the key is encrypted with a passphrase you type.
File permissions alone only stop other accounts on this machine; they do not
help if the laptop is stolen, backed up somewhere careless, or read by
something already running as you. The passphrase is asked for once per publish
and is never stored.

It is written to %USERPROFILE%\.vigil-signing\ — deliberately NOT inside the
repo, NOT inside OneDrive, and NOT inside ~/.vigil (Uninstall deletes that
folder). Back it up somewhere offline, e.g. a password manager's file vault.

This script refuses to overwrite an existing key, because replacing it
silently would strand every installed copy.
"""
import argparse
import base64
import getpass
import os
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

KEY_DIR = os.path.join(os.path.expanduser("~"), ".vigil-signing")
PRIVATE = os.path.join(KEY_DIR, "release-private.pem")
PUBLIC = os.path.join(KEY_DIR, "release-public.b64")
MIN_PASSPHRASE = 12


def ask_passphrase(confirm=True):
    """Ask twice, never echo, and allow an explicit empty answer to opt out."""
    while True:
        first = getpass.getpass(
            f"Passphrase for the signing key ({MIN_PASSPHRASE}+ characters, "
            "empty to store it unencrypted): ")
        if not first:
            print("Storing the key UNENCRYPTED. Anything running as you can "
                  "read it and sign releases in your name.")
            return None
        if len(first) < MIN_PASSPHRASE:
            print(f"Too short — use at least {MIN_PASSPHRASE} characters.")
            continue
        if not confirm or first == getpass.getpass("Again: "):
            return first.encode()
        print("They didn't match. Try again.")


def encryption(passphrase):
    return (serialization.BestAvailableEncryption(passphrase)
            if passphrase else serialization.NoEncryption())


def write_private(pem):
    """Owner-only from the moment it exists, on Windows and POSIX alike."""
    fd = os.open(PRIVATE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(pem)
    if os.name == "nt":
        # 0o600 is advisory on Windows; this is the real access control.
        os.system(f'icacls "{PRIVATE}" /inheritance:r /grant:r "%USERNAME%:F" >nul')


def encrypt_existing():
    """Add (or change) the passphrase on a key that already exists."""
    if not os.path.exists(PRIVATE):
        print(f"No key at {PRIVATE} to encrypt.")
        return 1
    current = getpass.getpass("Current passphrase (empty if unencrypted): ")
    try:
        key = serialization.load_pem_private_key(
            open(PRIVATE, "rb").read(),
            password=current.encode() if current else None)
    except Exception:
        print("That passphrase did not open the key. Nothing was changed.")
        return 1

    new = ask_passphrase()
    if new is None:
        print("Nothing changed.")
        return 1
    pem = key.private_bytes(serialization.Encoding.PEM,
                            serialization.PrivateFormat.PKCS8,
                            encryption(new))
    backup = PRIVATE + ".unencrypted.bak"
    os.replace(PRIVATE, backup)
    try:
        write_private(pem)
    except Exception:
        os.replace(backup, PRIVATE)          # put the original back
        raise
    print(f"Encrypted. The old copy is at {backup} — delete it once you have "
          "confirmed a publish works, and make sure your offline backup is the "
          "encrypted version.")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--encrypt", action="store_true",
                    help="put a passphrase on the key that already exists")
    args = ap.parse_args()

    os.makedirs(KEY_DIR, exist_ok=True)
    if args.encrypt:
        return encrypt_existing()

    if os.path.exists(PRIVATE):
        print(f"A signing key already exists at {PRIVATE}. Not replacing it.")
        print("Public key:", open(PUBLIC, encoding="ascii").read().strip())
        print("To add a passphrase to it: python tools/release_keygen.py --encrypt")
        return 1

    passphrase = ask_passphrase()
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(serialization.Encoding.PEM,
                            serialization.PrivateFormat.PKCS8,
                            encryption(passphrase))
    raw_pub = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    pub_b64 = base64.b64encode(raw_pub).decode("ascii")

    write_private(pem)
    with open(PUBLIC, "w", encoding="ascii") as f:
        f.write(pub_b64 + "\n")

    print(f"Private key: {PRIVATE}   <- back this up offline. Never commit it.")
    print(f"Public key:  {pub_b64}")
    print("Put the public key in app/vigil_version.py (RELEASE_PUBLIC_KEY).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
