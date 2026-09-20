"""The numbers have to be trustworthy, or they are worse than no numbers.

These tests pin down three things: what gets counted, what must never be
counted twice, and that nothing recorded here can grow without bound or
contain the contents of anyone's work.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import vigil_metrics as VM  # noqa: E402
import vigil_widget as VW   # noqa: E402  (imports Qt, but creates no window)


class TempData(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        os.environ["VIGIL_DATA_DIR"] = self.td.name

    def tearDown(self):
        os.environ.pop("VIGIL_DATA_DIR", None)
        self.td.cleanup()


class RecordTests(TempData):
    def test_summary_counts_what_was_recorded(self):
        VM.record("waited", secs=30, tier=5, sid="a", by="vigil")
        VM.record("waited", secs=90, tier=4, sid="b", by="terminal")
        VM.record("answered", secs=6, verdict="allow", tier=5, sid="a", away=True)
        VM.record("fellthrough", secs=45, tier=4, sid="b")
        VM.record("notified", ms=180, pills=1)
        VM.record("quiet", why="looking", sid="c")

        s = VM.summary(7)
        self.assertEqual(s["idle_secs"], 120)
        self.assertEqual(s["blocks"], 2)
        self.assertEqual((s["asked"], s["answered"], s["fellthrough"]), (2, 1, 1))
        self.assertEqual(s["coverage"], 0.5)
        self.assertEqual(s["answered_away"], 1)
        self.assertEqual(s["notify_p50_ms"], 180)
        self.assertEqual(s["quiet_why"], {"looking": 1})

    def test_old_events_fall_outside_the_window(self):
        VM.record("waited", secs=10, tier=4, sid="a")
        path = Path(self.td.name, "metrics.jsonl")
        old = json.loads(path.read_text().strip())
        old["t"] -= 40 * 86400
        path.write_text(json.dumps(old) + "\n")
        self.assertEqual(VM.summary(7)["blocks"], 0)
        self.assertEqual(VM.summary(90)["blocks"], 1)

    def test_nothing_is_recorded_that_reveals_the_work(self):
        # Sessions ids are truncated and no command, path or prompt is stored.
        VM.record("answered", secs=1, verdict="allow", tier=5,
                  sid="x" * 200, away=False)
        line = Path(self.td.name, "metrics.jsonl").read_text()
        rec = json.loads(line)
        self.assertLessEqual(len(rec["sid"]), 40)
        self.assertEqual(set(rec) - {"e", "t", "secs", "verdict", "tier",
                                     "sid", "away"}, set())

    def test_file_is_capped(self):
        VM.MAX_BYTES, original = 4096, VM.MAX_BYTES
        try:
            for _ in range(500):
                VM.record("quiet", why="rate_limited", sid="s")
            size = Path(self.td.name, "metrics.jsonl").stat().st_size
            self.assertLess(size, 8192)
            self.assertGreater(VM.summary(7)["quiet"], 0)    # still usable
        finally:
            VM.MAX_BYTES = original

    def test_corrupt_lines_are_skipped_not_fatal(self):
        Path(self.td.name, "metrics.jsonl").write_text("{bad\n", encoding="utf-8")
        VM.record("waited", secs=5, tier=4, sid="a")
        self.assertEqual(VM.summary(7)["blocks"], 1)

    def test_report_reads_as_english_with_no_data(self):
        text = VM.report(7)
        self.assertIn("Agent idle time", text)
        self.assertIn("Nothing here leaves this computer", text)


class PriorityTests(unittest.TestCase):
    """Which agent gets the top pill when several want you at once."""

    def session(self, sid, tier, since):
        return {"session_id": sid, "tier": tier, "since": since}

    def test_a_pending_approval_outranks_everything_else(self):
        now = 1_000_000.0
        sessions = [self.session("failed", 6, now - 600),
                    self.session("approval", 5, now - 2)]
        pending = {"approval": {"id": "r", "expires": now + 40}}
        self.assertEqual(VW.prioritize(sessions, pending)[0]["session_id"],
                         "approval")

    def test_the_approval_closest_to_expiring_goes_first(self):
        now = 1_000_000.0
        sessions = [self.session("later", 5, now), self.session("sooner", 5, now)]
        pending = {"later": {"expires": now + 40}, "sooner": {"expires": now + 5}}
        self.assertEqual([s["session_id"] for s in VW.prioritize(sessions, pending)],
                         ["sooner", "later"])

    def test_without_approvals_risk_then_waiting_longest_wins(self):
        now = 1_000_000.0
        sessions = [self.session("old_question", 4, now - 900),
                    self.session("new_destructive", 7, now - 1),
                    self.session("new_question", 4, now - 5)]
        order = [s["session_id"] for s in VW.prioritize(sessions, {})]
        self.assertEqual(order, ["new_destructive", "old_question", "new_question"])

    def test_one_session_is_unchanged(self):
        s = [self.session("only", 4, 1.0)]
        self.assertEqual(VW.prioritize(s, {}), s)


if __name__ == "__main__":
    unittest.main()
