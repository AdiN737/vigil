import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app")
sys.path.insert(0, APP)

import vigil_hook
import vigil_setup


class ProviderContractTests(unittest.TestCase):
    def test_provider_detection_uses_documented_codex_extensions(self):
        self.assertEqual(vigil_hook.provider_for({"model": "gpt-6-astra"}), "codex")
        self.assertEqual(vigil_hook.provider_for({"turn_id": "turn_1"}), "codex")
        self.assertEqual(vigil_hook.provider_for({}), "claude")
        self.assertEqual(vigil_hook.provider_for({}, "codex"), "codex")

    def test_codex_subagents_get_distinct_session_rows(self):
        sid, native = vigil_hook.identity_for(
            {"session_id": "thr_1", "agent_id": "agent_2"}, "codex"
        )
        self.assertEqual(sid, "codex:thr_1:agent_2")
        self.assertEqual(native, "thr_1")

    def test_claude_session_ids_remain_backward_compatible(self):
        sid, native = vigil_hook.identity_for({"session_id": "abc"}, "claude")
        self.assertEqual((sid, native), ("abc", "abc"))

    def test_approval_outputs_match_each_provider_contract(self):
        claude = vigil_hook.approval_output("claude", "allow")
        codex = vigil_hook.approval_output("codex", "deny")
        self.assertEqual(
            claude["hookSpecificOutput"]["permissionDecision"], "allow"
        )
        self.assertEqual(
            codex["hookSpecificOutput"]["decision"],
            {"behavior": "deny", "message": "Denied from Vigil"},
        )

    def test_codex_stop_emits_valid_empty_json(self):
        payload = {
            "session_id": "thr_stop",
            "turn_id": "turn_stop",
            "cwd": "C:/work/api",
            "hook_event_name": "Stop",
        }
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(vigil_hook, "SESSIONS", os.path.join(td, "sessions")), \
             mock.patch.object(vigil_hook, "LOG", os.path.join(td, "log")), \
             mock.patch("sys.stdin", io.StringIO(json.dumps(payload))), \
             mock.patch("sys.stdout", out):
            self.assertEqual(vigil_hook.main("done", "codex"), 0)
        self.assertEqual(json.loads(out.getvalue()), {})

    def test_codex_description_is_human_readable(self):
        payload = {
            "cwd": "C:/work/api",
            "tool_name": "apply_patch",
            "tool_input": {"description": "Edit the deployment config"},
        }
        self.assertEqual(
            vigil_hook.describe(payload)[:3],
            ("api", "apply_patch", "Edit the deployment config"),
        )

    def test_normalized_codex_record_is_written(self):
        payload = {
            "session_id": "thr_9",
            "turn_id": "turn_4",
            "model": "gpt-6-astra",
            "cwd": "C:/work/web",
            "hook_event_name": "UserPromptSubmit",
        }
        with tempfile.TemporaryDirectory() as td:
            sessions = os.path.join(td, "sessions")
            with mock.patch.object(vigil_hook, "SESSIONS", sessions), \
                 mock.patch.object(vigil_hook, "LOG", os.path.join(td, "log")), \
                 mock.patch("sys.stdin", io.StringIO(json.dumps(payload))):
                self.assertEqual(vigil_hook.main("working", "codex"), 0)
            with open(os.path.join(sessions, "codex_thr_9.json"),
                      encoding="utf-8") as f:
                record = json.load(f)
        self.assertEqual(record["schema"], 1)
        self.assertEqual(record["provider"], "codex")
        self.assertEqual(record["native_session_id"], "thr_9")
        self.assertEqual(record["tier"], 2)


class SetupTests(unittest.TestCase):
    def test_codex_install_preserves_other_hooks(self):
        with tempfile.TemporaryDirectory() as td:
            hooks_path = os.path.join(td, "hooks.json")
            existing = {
                "hooks": {
                    "Stop": [{"hooks": [{"type": "command", "command": "keep-me"}]}]
                }
            }
            with open(hooks_path, "w", encoding="utf-8") as f:
                json.dump(existing, f)
            with mock.patch.object(vigil_setup, "CODEX_HOOKS", hooks_path):
                ok, _ = vigil_setup.install_codex_hooks()
            self.assertTrue(ok)
            with open(hooks_path, encoding="utf-8") as f:
                installed = json.load(f)
            self.assertEqual(
                installed["hooks"]["Stop"][0]["hooks"][0]["command"], "keep-me"
            )
