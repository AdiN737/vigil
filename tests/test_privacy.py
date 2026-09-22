"""The promises on the README, turned into tests.

Every claim here was checked by an outside reviewer once. These exist so it
stays true without anyone having to check again.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import vigil_hook as VH  # noqa: E402

SECRET = "sk-proj-Ab3d9Xq7ZzT1kLm8Nv0Wp2Yr4Hs6Jd5Fg"


class ScrubTests(unittest.TestCase):
    def test_api_keys_are_redacted(self):
        out = VH.scrub(f'curl -H "Authorization: Bearer {SECRET}" https://api.x.com')
        self.assertNotIn(SECRET, out)
        self.assertIn("[redacted]", out)
        self.assertIn("curl", out)                     # still recognisable

    def test_assigned_secrets_are_redacted_but_the_name_survives(self):
        out = VH.scrub(f"export OPENAI_API_KEY={SECRET}")
        self.assertNotIn(SECRET, out)
        self.assertIn("OPENAI_API_KEY", out)

    def test_ordinary_commands_are_left_alone(self):
        for cmd in ("npm run build -- --watch",
                    "git reset --hard 3f2a9b1c4d5e6f708192a3b4c5d6e7f8091a2b3c",
                    r"python C:\work\project\scripts\generate_report.py --full"):
            self.assertEqual(VH.scrub(cmd), cmd)

    def test_scrub_never_lengthens_beyond_reason(self):
        self.assertLess(len(VH.scrub(SECRET * 3)), len(SECRET * 3))


class HookOutputTests(unittest.TestCase):
    """Run the real hook and inspect everything it wrote."""

    def run_hook(self, payload, state="question"):
        td = tempfile.mkdtemp()
        binary = os.environ.get("VIGIL_TEST_HOOK")
        cmd = ([binary] if binary else
               [sys.executable, str(ROOT / "app/vigil_hook_main.py")]) + [state, "claude"]
        subprocess.run(cmd, input=json.dumps(payload), text=True,
                       capture_output=True, timeout=30,
                       env=dict(os.environ, VIGIL_DATA_DIR=td))
        written = ""
        for p in Path(td).rglob("*"):
            if p.is_file():
                written += p.read_text(encoding="utf-8", errors="replace")
        return td, written

    def test_the_prompt_is_never_written_anywhere(self):
        secret_prompt = "refactor the billing module and delete the old invoices"
        _, written = self.run_hook(dict(
            session_id="p1", cwd="C:/work/demo", hook_event_name="Notification",
            tool_name="Task", tool_input={"prompt": secret_prompt}))
        self.assertNotIn("refactor the billing module", written)
        self.assertIn("Task", written)          # the tool name is fine to show

    def test_a_credential_in_a_command_is_not_written(self):
        _, written = self.run_hook(dict(
            session_id="p2", cwd="C:/work/demo", hook_event_name="Notification",
            tool_name="Bash", tool_input={"command": f"curl -H 'X-Api-Key: {SECRET}'"}))
        self.assertNotIn(SECRET, written)

    def test_file_contents_are_never_written(self):
        _, written = self.run_hook(dict(
            session_id="p3", cwd="C:/work/demo", hook_event_name="Notification",
            tool_name="Write", tool_input={"file_path": "C:/work/demo/app.py",
                                           "content": "TOP_SECRET_FILE_BODY"}))
        self.assertNotIn("TOP_SECRET_FILE_BODY", written)
        self.assertIn("app.py", written)

    def test_the_hook_opens_no_network_connection(self):
        """The hook must stay offline even when the payload invites it."""
        source = (ROOT / "app/vigil_hook.py").read_text(encoding="utf-8")
        for forbidden in ("urllib", "requests", "http.client", "socket"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
