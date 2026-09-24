"""Isolated Qt regressions: no live startup, hooks, preferences or agent state."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

APP = Path(__file__).resolve().parents[1] / "app"


class WidgetProjectsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_env = patch.dict(os.environ, QT_QPA_PLATFORM="offscreen")
        cls.qt_env.start()
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls):
        cls.qt_env.stop()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.enterContext(patch.dict(os.environ, VIGIL_DATA_DIR=self.temp.name))
        self.enterContext(patch.object(sys, "path", [str(APP)] + sys.path))
        self.requests = []
        self.focus = Mock(return_value="")
        self.decide = Mock(return_value=False)
        self.metrics = Mock()
        self.enterContext(patch.dict(sys.modules, {
            "vigil_setup": types.SimpleNamespace(load_prefs=lambda: {}),
            "vigil_decide": types.SimpleNamespace(pending=lambda: list(self.requests), decide=self.decide),
            "vigil_metrics": types.SimpleNamespace(record=self.metrics),
            "vigil_platform": types.SimpleNamespace(foreground_title=self.focus,
                focus_window_for=Mock(), single_instance=Mock()),
        }))
        spec = importlib.util.spec_from_file_location("widget_projects_under_test", APP / "vigil_widget.py")
        self.vw = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.vw)
        self.now = 10000.0
        self.enterContext(patch.object(self.vw.time, "time", side_effect=lambda: self.now))
        self.stack = self.vw.Stack()
        for timer in self.stack._timers:
            timer.stop()
        self.stack.greet_until = 0
        self.addCleanup(self.dispose)

    def dispose(self):
        self.stack.anim.stop()
        self.stack.close()
        self.stack.deleteLater()

    def session(self, project, agent, tier=2):
        return dict(session_id=f"{project}-{agent}", project=project,
                    cwd=f"C:/work/{project}", provider="codex" if agent == "agent2" else "claude",
                    tier=tier, since=self.now - 10, updated=self.now, detail="test")

    def write(self, sessions):
        folder = Path(self.vw.SESSIONS)
        folder.mkdir(exist_ok=True)
        for path in folder.glob("*.json"):
            path.unlink()
        for index, session in enumerate(sessions):
            (folder / f"{index}.json").write_text(json.dumps(session), encoding="utf-8")
        self.vw._CACHE.clear()

    def four(self, tier=2):
        return [self.session(project, agent, tier) for project in ("alpha", "beta")
                for agent in ("agent1", "agent2")]

    def manual_open(self):
        from PySide6.QtCore import Qt, QPoint
        from PySide6.QtTest import QTest
        self.stack._poll()
        QTest.mouseClick(self.stack, Qt.LeftButton, pos=QPoint(12, 12))
        self.stack.anim.stop()
        self.stack._place(animate=False)

    def batch(self):
        self.stack._poll()
        self.now += self.vw.BATCH_MS / 1000 + .01
        self.stack._poll()

    def shown_ids(self):
        return {s["session_id"] for s in self.stack.shown}

    def test_data_dir_is_isolated(self):
        self.assertEqual(self.vw.DATA, self.temp.name)
        self.assertEqual(Path(self.vw.PREFS).parent, Path(self.temp.name))
        self.assertEqual(self.stack.sessions, [])

    def test_manual_four_working_agents_visible_and_distinguishable(self):
        sessions = self.four()
        self.write(sessions)
        self.manual_open()
        self.assertTrue(self.stack.manual)
        self.assertEqual(self.shown_ids(), {s["session_id"] for s in sessions})
        self.assertEqual(len(self.stack.rows), 4)
        self.assertEqual(len({self.vw.Stack._session_title(self.stack, s) for s in sessions}), 4)
        self.assertIn("CLAUDE", self.stack.toolTip())
        self.assertIn("CODEX", self.stack.toolTip())
        self.assertGreaterEqual(self.stack.height(), self.stack.rows[-1][0] + self.stack.rows[-1][1])

    def test_manual_poll_keeps_working_agents_and_resizes(self):
        sessions = self.four()
        self.write(sessions[:1])
        self.manual_open()
        old_height = self.stack.height()
        sessions[1]["tier"] = 5
        self.write(sessions)
        self.stack._poll()
        self.assertEqual(len(self.stack.rows), 4)
        self.assertGreater(self.stack.height(), old_height)
        self.assertEqual(self.stack.height(), self.stack._size()[1])
        self.write(sessions[:1])
        self.stack._poll()
        self.assertEqual(self.stack.height(), self.vw.PILL_H)

    def test_focused_project_does_not_suppress_other_project_or_replay(self):
        sessions = [self.session("alpha", "agent1", 5),
                    self.session("beta", "agent1", 5), self.session("beta", "agent2", 5)]
        self.write(sessions)
        self.focus.return_value = "ALPHA - editor"
        self.batch()
        self.assertEqual(self.shown_ids(), {s["session_id"] for s in sessions if s["project"] == "beta"})
        self.assertEqual(len(self.stack.ping_log), 1)
        self.stack._close()
        self.focus.return_value = "elsewhere"
        self.now += 1000
        self.batch()
        self.assertFalse(self.stack.expanded)
        self.assertEqual(len(self.stack.ping_log), 1)

    def test_shared_project_title_does_not_suppress_either_agent(self):
        sessions = self.four(tier=5)
        self.write(sessions)
        self.focus.return_value = "C:/work/alpha - ALPHA - editor"
        self.batch()
        self.assertEqual(self.shown_ids(), {s["session_id"] for s in sessions})
        self.assertEqual(len(self.stack.ping_log), 1)

    def test_working_agent_makes_project_focus_ambiguous(self):
        sessions = [self.session("alpha", "agent1", 2), self.session("alpha", "agent2", 5)]
        self.write(sessions)
        self.focus.return_value = "alpha - editor"
        self.batch()
        self.assertEqual(self.shown_ids(), {sessions[1]["session_id"]})

    def test_explicit_session_title_suppresses_only_that_agent(self):
        sessions = self.four(tier=5)
        self.write(sessions)
        self.focus.return_value = "alpha - alpha-agent1 - editor"
        self.batch()
        self.assertEqual(self.shown_ids(), {s["session_id"] for s in sessions[1:]})

    def test_distinct_path_disambiguates_duplicate_project_names(self):
        sessions = [self.session("alpha", "agent1", 5), self.session("alpha", "agent2", 5)]
        sessions[1]["cwd"] = "D:/other/alpha"
        self.write(sessions)
        self.focus.return_value = "C:\\work\\alpha - editor"
        self.batch()
        self.assertEqual(self.shown_ids(), {sessions[1]["session_id"]})

    def test_only_actionable_sessions_notify(self):
        sessions = self.four()
        sessions[0]["tier"] = 3
        self.write(sessions)
        self.batch()
        self.assertFalse(self.stack.expanded)
        sessions[2]["tier"] = 4
        self.write(sessions)
        self.batch()
        self.assertEqual(self.shown_ids(), {sessions[2]["session_id"]})

    def test_resolved_session_does_not_clear_other_approval(self):
        sessions = self.four(tier=5)[:2]
        self.requests = [dict(id="req1", session_id=sessions[0]["session_id"], expires=self.now+40),
                         dict(id="req2", session_id=sessions[1]["session_id"], expires=self.now+40)]
        self.write(sessions)
        self.batch()
        sessions[0]["tier"] = 2
        self.requests.pop(0)
        self.write(sessions)
        self.stack._poll()
        self.assertTrue(self.stack.expanded)
        self.assertEqual(self.shown_ids(), {sessions[1]["session_id"]})
        self.assertEqual(self.stack.rows[0][3]["id"], "req2")
        self.assertEqual(self.stack.height(), self.vw.PILL_APPROVE_H)

    def test_answer_last_approval_keeps_unrelated_question(self):
        sessions = self.four(tier=4)[:2]
        req = dict(id="req1", session_id=sessions[0]["session_id"], expires=self.now+40)
        self.requests = [req]
        self.write(sessions)
        self.batch()
        def accept(*args):
            self.requests.clear()
            sessions[0]["tier"] = 2
            self.write(sessions)
            return True
        self.decide.side_effect = accept
        self.assertTrue(self.stack._answer(req, "allow"))
        self.assertTrue(self.stack.expanded)
        self.assertEqual(self.shown_ids(), {sessions[1]["session_id"]})
        self.assertIsNone(self.stack.rows[0][3])

    def test_failed_answer_refreshes_without_falsely_resolving(self):
        sessions = self.four(tier=5)[:2]
        old = dict(id="expired", session_id=sessions[0]["session_id"], expires=self.now+40)
        self.requests = [old]
        self.write(sessions)
        self.batch()
        replacement = dict(old, id="new-request")
        self.requests = [replacement]
        self.assertFalse(self.stack._answer(old, "allow"))
        self.assertEqual(len(self.stack.shown), 2)
        self.assertEqual(self.stack.rows[0][3]["id"], "new-request")
        self.decide.assert_called_once_with("expired", "allow", "widget")

    def test_expired_approval_refreshes_rows_and_height(self):
        sessions = self.four()
        self.write(sessions)
        self.manual_open()
        self.requests = [dict(id="req", session_id=sessions[0]["session_id"], expires=self.now+40)]
        self.stack._poll()
        tall = self.stack.height()
        self.assertIsNotNone(self.stack.rows[0][3])
        self.requests.clear()
        self.stack._poll()
        self.assertTrue(all(row[3] is None for row in self.stack.rows))
        self.assertEqual(tall - self.stack.height(), self.vw.PILL_APPROVE_H - self.vw.PILL_H)
        self.assertEqual(len(self.stack.shown), 4)

    def test_overflow_click_opens_chooser_and_selected_approval_stays_accessible(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        sessions = self.four(tier=5) + [self.session("alpha", "agent3", 5)]
        sessions[-1]["cwd"] = "D:/other/alpha"
        self.requests = [dict(id=f"req{i}", session_id=s["session_id"], expires=self.now+40+i)
                         for i, s in enumerate(sessions)]
        self.write(sessions)
        self.manual_open()
        rect = self.stack._overflow_rect()
        last = self.stack.rows[-1]
        self.assertGreaterEqual(rect.top(), last[0] + last[1])
        self.assertLessEqual(rect.bottom(), self.stack.height())
        QTest.mouseClick(self.stack, Qt.LeftButton, pos=rect.center())
        menu = self.stack._session_menu
        self.assertEqual(len(menu.actions()), 5)
        self.assertIn("D:/other/alpha", menu.actions()[-1].text())
        menu.actions()[-1].trigger()
        menu.hide()
        self.stack._poll()
        self.assertEqual(self.stack.rows[0][2]["session_id"], sessions[-1]["session_id"])
        self.assertEqual(self.stack.rows[0][3]["id"], "req4")

    def test_manual_overflow_is_unseen_until_chooser_selection(self):
        sessions = self.four(tier=5) + [self.session("alpha", "agent3", 5),
                                      self.session("beta", "agent3", 5)]
        self.requests = [dict(id=f"req{i}", session_id=s["session_id"], expires=self.now+40+i)
                         for i, s in enumerate(sessions)]
        self.write(sessions)
        self.manual_open()
        painted = {s["session_id"] for s in sessions[:self.vw.MAX_PILLS]}
        self.assertEqual(self.stack.pinged_ids, painted)
        self.stack._poll()
        self.assertEqual(self.stack.pinged_ids, painted)
        self.stack._show_session_chooser()
        menu = self.stack._session_menu
        menu.actions()[4].trigger()
        menu.hide()
        selected_id = sessions[4]["session_id"]
        self.assertEqual(self.stack.rows[0][2]["session_id"], selected_id)
        self.assertEqual(self.stack.pinged_ids, painted | {selected_id})
        self.stack._poll()
        self.assertEqual(self.stack.pinged_ids, painted | {selected_id})
        self.assertNotIn(sessions[5]["session_id"], self.stack.pinged_ids)

    def test_closing_manual_overflow_allows_unviewed_request_to_notify(self):
        sessions = self.four(tier=5) + [self.session("alpha", "agent3", 5)]
        self.write(sessions)
        self.manual_open()
        self.stack._poll()
        hidden_id = sessions[-1]["session_id"]
        self.assertNotIn(hidden_id, self.stack.pinged_ids)
        self.stack._close()
        self.batch()
        self.assertTrue(self.stack.expanded)
        self.assertEqual(self.shown_ids(), {hidden_id})
        self.assertEqual(len(self.stack.ping_log), 1)

    def test_manual_view_does_not_replay_seen_requests(self):
        self.write(self.four(tier=5))
        self.stack.sessions = self.vw.read_sessions()
        self.stack._open(self.stack.sessions, manual=True)
        self.stack._close()
        self.now += 1000
        self.batch()
        self.assertFalse(self.stack.expanded)
        self.assertEqual(self.stack.ping_log, [])


    def fake_monitors(self):
        from PySide6.QtCore import QRect
        screens = [types.SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1280, 752)),
                   types.SimpleNamespace(availableGeometry=lambda: QRect(1920, 0, 1920, 1032)),
                   types.SimpleNamespace(availableGeometry=lambda: QRect(-1600, -200, 1600, 900))]
        fake = types.SimpleNamespace(screens=lambda: screens, primaryScreen=lambda: screens[0],
            screenAt=lambda p: next((s for s in screens if s.availableGeometry().contains(p)), None))
        self.enterContext(patch.object(self.vw, "QGuiApplication", fake))
        return screens

    def test_saved_secondary_anchor_ignores_old_window_position(self):
        from PySide6.QtCore import QPoint
        self.fake_monitors()
        self.stack.move(100, 100)
        self.stack.corner = QPoint(2860, 400)
        self.stack._place(animate=False)
        self.assertEqual(self.stack.pos(), QPoint(2860, 400))
        self.stack._save_corner()
        self.assertEqual(self.stack._load_corner(), QPoint(2860, 400))
        self.stack._open(self.four(), manual=True)
        self.stack._place(animate=False)
        self.assertGreaterEqual(self.stack.geometry().left(), 1920)
        self.stack._close()
        self.stack._place(animate=False)
        self.assertEqual(self.stack.pos(), QPoint(2860, 400))

    def test_drag_crosses_gap_both_ways_and_supports_negative_coordinates(self):
        from PySide6.QtCore import QPoint, QPointF, Qt
        self.fake_monitors()
        self.stack.corner = QPoint(1100, 400)
        self.stack._place(animate=False)
        def event(x, y):
            return types.SimpleNamespace(button=lambda: Qt.LeftButton,
                position=lambda: QPointF(8, 8), globalPosition=lambda: QPointF(x, y))
        self.stack.mousePressEvent(event(1108, 408))
        self.stack.mouseMoveEvent(event(1608, 408))
        self.assertEqual(self.stack.corner, QPoint(1600, 400))
        self.stack.mouseMoveEvent(event(2408, 408))
        self.stack.mouseReleaseEvent(event(2408, 408))
        self.assertEqual(self.stack.pos(), QPoint(2400, 400))
        self.assertEqual(self.stack._load_corner(), QPoint(2400, 400))
        self.stack.mousePressEvent(event(2408, 408))
        self.stack.mouseMoveEvent(event(1608, 408))
        self.stack.mouseMoveEvent(event(508, 408))
        self.stack.mouseReleaseEvent(event(508, 408))
        self.assertEqual(self.stack.pos(), QPoint(500, 400))
        self.stack.mousePressEvent(event(508, 408))
        self.stack.mouseMoveEvent(event(-792, 108))
        self.stack.mouseReleaseEvent(event(-792, 108))
        self.assertEqual(self.stack.pos(), QPoint(-800, 100))
        self.assertEqual(self.stack._load_corner(), QPoint(-800, 100))

    def test_release_inside_gap_clamps_to_nearest_display(self):
        from PySide6.QtCore import QPoint
        self.fake_monitors()
        self.stack.corner = QPoint(1850, 400)
        self.stack.drag = QPoint(1858, 408)
        self.stack._moved = True
        self.stack.mouseReleaseEvent(None)
        self.assertEqual(self.stack.corner, QPoint(1920, 400))
        self.assertEqual(self.stack._load_corner(), self.stack.corner)

    def test_empty_manual_panel_paints_an_explanation(self):
        self.stack._open([], manual=True)
        with patch.object(self.stack, "_paint_pill") as paint:
            self.stack._paint_stack(Mock())
        self.assertEqual(paint.call_args.args[3], "Vigil is watching")


if __name__ == "__main__":
    unittest.main()
