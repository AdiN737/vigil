"""The update path is the one place Vigil can put code on a user's machine,
so these tests are about what it REFUSES as much as what it accepts.

Nothing here touches the network or the real install directory.
"""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402

import vigil_remote  # noqa: E402
import vigil_update  # noqa: E402


def keypair():
    k = Ed25519PrivateKey.generate()
    pub = k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return k, base64.b64encode(pub).decode()


def build_zip(path, extra=None):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Vigil.exe", b"MZ fake widget")
        z.writestr("_internal/lib.dll", b"lib")
        z.writestr("hook/vigil-hook.exe", b"MZ fake hook")
        z.writestr("Install Vigil.bat", b"@echo off")   # not in the allow-list
        for name, data in (extra or {}).items():
            z.writestr(name, data)


def sign(path, key):
    digest = hashlib.sha256(Path(path).read_bytes()).digest()
    return digest.hex(), base64.b64encode(key.sign(digest)).decode()


class VerifyTests(unittest.TestCase):
    def setUp(self):
        self.key, self.pub = keypair()
        self._orig = vigil_update.RELEASE_PUBLIC_KEY
        vigil_update.RELEASE_PUBLIC_KEY = self.pub
        self.td = tempfile.TemporaryDirectory()
        self.zip = os.path.join(self.td.name, "u.zip")
        build_zip(self.zip)

    def tearDown(self):
        vigil_update.RELEASE_PUBLIC_KEY = self._orig
        self.td.cleanup()

    def test_accepts_correctly_signed_update(self):
        sha, sig = sign(self.zip, self.key)
        vigil_update.verify(self.zip, sha, sig)          # no exception

    def test_rejects_tampered_file(self):
        sha, sig = sign(self.zip, self.key)
        with open(self.zip, "ab") as f:
            f.write(b"injected")
        with self.assertRaisesRegex(ValueError, "hash"):
            vigil_update.verify(self.zip, sha, sig)

    def test_rejects_signature_from_another_key(self):
        attacker, _ = keypair()
        sha, forged = sign(self.zip, attacker)
        with self.assertRaisesRegex(ValueError, "signature"):
            vigil_update.verify(self.zip, sha, forged)

    def test_rejects_matching_hash_with_no_real_signature(self):
        # A compromised backend can publish the right hash for its own file;
        # without the private key it still cannot sign it.
        sha = hashlib.sha256(Path(self.zip).read_bytes()).hexdigest()
        with self.assertRaises(ValueError):
            vigil_update.verify(self.zip, sha, base64.b64encode(b"\0" * 64).decode())


class ExtractTests(unittest.TestCase):
    def test_extracts_only_allow_listed_files(self):
        with tempfile.TemporaryDirectory() as td:
            z = os.path.join(td, "u.zip"); build_zip(z)
            out = os.path.join(td, "out"); os.makedirs(out)
            vigil_update._safe_extract(z, out)
            self.assertTrue(os.path.isfile(os.path.join(out, "Vigil.exe")))
            self.assertTrue(os.path.isfile(os.path.join(out, "hook", "vigil-hook.exe")))
            self.assertFalse(os.path.exists(os.path.join(out, "Install Vigil.bat")))

    def test_refuses_path_traversal(self):
        for evil in ("../escape.exe", "hook/../../escape.exe", "C:/Windows/evil.exe", "/abs.exe"):
            with self.subTest(evil=evil), tempfile.TemporaryDirectory() as td:
                z = os.path.join(td, "u.zip")
                with zipfile.ZipFile(z, "w") as zf:
                    zf.writestr("Vigil.exe", b"MZ")
                    zf.writestr(evil, b"payload")
                out = os.path.join(td, "out"); os.makedirs(out)
                with self.assertRaisesRegex(ValueError, "unsafe"):
                    vigil_update._safe_extract(z, out)
                self.assertFalse(os.path.exists(os.path.join(td, "escape.exe")))


class ManifestTests(unittest.TestCase):
    def good(self, **over):
        m = dict(version="99.0.0", sha256="a" * 64, signature="x",
                 url="https://example.supabase.co/storage/v1/object/sign/builds/x.zip")
        m.update(over)
        return m

    def test_accepts_newer_https_release(self):
        self.assertTrue(vigil_update._valid_manifest(self.good()))

    def test_rejects_plain_http(self):
        self.assertFalse(vigil_update._valid_manifest(self.good(url="http://example.com/x.zip")))

    def test_rejects_same_or_older_version(self):
        self.assertFalse(vigil_update._valid_manifest(self.good(version=vigil_update.VERSION)))
        self.assertFalse(vigil_update._valid_manifest(self.good(version="0.0.1")))

    def test_rejects_missing_fields(self):
        m = self.good(); m.pop("signature")
        self.assertFalse(vigil_update._valid_manifest(m))

    def test_version_ordering_is_numeric(self):
        self.assertTrue(vigil_update._newer("0.10.0", "0.9.0"))
        self.assertFalse(vigil_update._newer("0.9.0", "0.10.0"))

    def test_stage_refuses_outside_an_install(self):
        # Tests run from source, never from ~/.vigil/app.
        with self.assertRaisesRegex(RuntimeError, "installed"):
            vigil_update.stage(self.good())

    def test_check_survives_an_unreachable_server(self):
        with tempfile.TemporaryDirectory() as td:
            os.environ["VIGIL_DATA_DIR"] = td
            orig = vigil_update.UPDATE_URL
            vigil_update.UPDATE_URL = "https://127.0.0.1:9/nothing"
            try:
                self.assertIsNone(vigil_update.check(force=True))
            finally:
                vigil_update.UPDATE_URL = orig
                os.environ.pop("VIGIL_DATA_DIR", None)


class RemoteConfigTests(unittest.TestCase):
    def test_defaults_when_nothing_cached(self):
        with tempfile.TemporaryDirectory() as td:
            os.environ["VIGIL_DATA_DIR"] = td
            try:
                self.assertTrue(vigil_remote.approvals_enabled())
                self.assertIsNone(vigil_remote.load()["message"])
            finally:
                os.environ.pop("VIGIL_DATA_DIR", None)

    def test_ignores_unknown_keys_and_bad_types(self):
        clean = vigil_remote.sanitize({
            "approvals_enabled": "false",      # string, not bool -> ignored
            "run_command": "format c:",        # unknown key -> dropped
            "message": "x" * 500,              # truncated
        })
        self.assertEqual(set(clean), {"approvals_enabled", "message"})
        self.assertTrue(clean["approvals_enabled"])
        self.assertEqual(len(clean["message"]), 200)

    def test_corrupt_cache_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as td:
            os.environ["VIGIL_DATA_DIR"] = td
            try:
                Path(td, "remote.json").write_text("{not json", encoding="utf-8")
                self.assertTrue(vigil_remote.approvals_enabled())
            finally:
                os.environ.pop("VIGIL_DATA_DIR", None)


class KillSwitchTests(unittest.TestCase):
    """With approvals switched off remotely, the hook must not intercept a
    permission request: it returns promptly with no decision, so the agent
    shows its own prompt."""

    def test_disabled_approvals_fall_through_to_the_agent(self):
        with tempfile.TemporaryDirectory() as td:
            Path(td, "remote.json").write_text(json.dumps({"approvals_enabled": False}),
                                               encoding="utf-8")
            payload = dict(session_id="kill-switch", cwd="C:/VigilIsolatedFixture",
                           hook_event_name="PermissionRequest", tool_name="Bash",
                           tool_input={"command": "npm run build"})
            binary = os.environ.get("VIGIL_TEST_HOOK")
            cmd = ([binary] if binary else [sys.executable, str(ROOT / "app/vigil_hook_main.py")]) \
                + ["blocked", "claude"]
            result = subprocess.run(cmd, input=json.dumps(payload), text=True,
                                    capture_output=True, timeout=10,
                                    env=dict(os.environ, VIGIL_DATA_DIR=td))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("decision", result.stdout)
            requests = Path(td, "requests")
            self.assertFalse(requests.exists() and any(requests.iterdir()))


if __name__ == "__main__":
    unittest.main()
