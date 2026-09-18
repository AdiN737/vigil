"""Create the Ed25519 key that signs every Vigil release. Run ONCE, ever.

Every installed copy of Vigil carries the matching PUBLIC key and refuses to
install an update whose signature does not verify. So this private key is the
single thing that can push code onto users' machines:

  * LOSE it  -> you can never ship another auto-update to existing installs.
               Everyone would have to download a fresh build by hand.
  * LEAK it  -> anyone holding it can push malware to every user.

It is written to %USERPROFILE%\.vigil-signing\ — deliberately NOT inside the
repo, NOT inside OneDrive, and NOT inside ~/.vigil (Uninstall deletes that
folder). Back it up somewhere offline, e.g. a password manager's file vault.

This script refuses to overwrite an existing key, because replacing it
silently would strand every installed copy.
"""
import base64
import os
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

KEY_DIR = os.path.join(os.path.expanduser("~"), ".vigil-signing")
PRIVATE = os.path.join(KEY_DIR, "release-private.pem")
PUBLIC = os.path.join(KEY_DIR, "release-public.b64")


def main():
    if os.path.exists(PRIVATE):
        print(f"A signing key already exists at {PRIVATE}. Not replacing it.")
        print("Public key:", open(PUBLIC, encoding="ascii").read().strip())
        return 1

    os.makedirs(KEY_DIR, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    raw_pub = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    pub_b64 = base64.b64encode(raw_pub).decode("ascii")

    # Create the private key file with owner-only access from the start.
    fd = os.open(PRIVATE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(pem)
    with open(PUBLIC, "w", encoding="ascii") as f:
        f.write(pub_b64 + "\n")

    print(f"Private key: {PRIVATE}   <- back this up offline. Never commit it.")
    print(f"Public key:  {pub_b64}")
    print("Put the public key in app/vigil_version.py (RELEASE_PUBLIC_KEY).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
