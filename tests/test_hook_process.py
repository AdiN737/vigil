"""Exercise the actual stdin/file/stdout handshake; no real commands execute."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]

class HookProcessTests(unittest.TestCase):
    provider = 'codex'
    def invoke(self, state, event, data, **extra):
        payload = dict(session_id='codex-process-test', cwd='C:/VigilIsolatedFixture',
                       hook_event_name=event, **extra)
        return subprocess.run(self.command(state), input=json.dumps(payload),
                              text=True, capture_output=True, timeout=10,
                              env=dict(os.environ, VIGIL_DATA_DIR=data))

    def command(self, state):
        binary = os.environ.get('VIGIL_TEST_HOOK')
        return ([binary] if binary else [sys.executable, str(ROOT / 'app/vigil_hook_main.py')]) + [state, self.provider]

    def test_passive_lifecycle(self):
        with tempfile.TemporaryDirectory() as td:
            result = self.invoke('working', 'UserPromptSubmit', td)
            self.assertEqual(result.returncode, 0, result.stderr)
            files = list((Path(td) / 'sessions').glob('*.json'))
            self.assertEqual(len(files), 1)
            self.assertEqual(json.loads(files[0].read_text())['provider'], self.provider)
            result = self.invoke('done', 'Stop', td)
            self.assertEqual(result.stdout.strip(), '{}' if self.provider == 'codex' else '')
            self.invoke('idle', 'SessionEnd', td)
            self.assertEqual(list((Path(td) / 'sessions').glob('*.json')), [])

    def test_allow_and_deny_handshake(self):
        for decision in ('allow', 'deny'):
            with self.subTest(decision=decision), tempfile.TemporaryDirectory() as td:
                p = subprocess.Popen(self.command('blocked'), stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                    env=dict(os.environ, VIGIL_DATA_DIR=td))
                payload = dict(session_id='codex:thread/fixture', cwd='C:/VigilIsolatedFixture',
                    hook_event_name='PermissionRequest', permission_mode='default', tool_name='Bash',
                    tool_input={'command':'echo simulated-permission-test'})
                try:
                    p.stdin.write(json.dumps(payload)); p.stdin.close(); p.stdin = None
                    end = time.monotonic() + 8
                    requests = []
                    while time.monotonic() < end:
                        requests = list((Path(td) / 'requests').glob('*.json'))
                        if requests: break
                        time.sleep(.03)
                    self.assertTrue(requests, 'Hook failed to publish a Windows-safe request')
                    request = json.loads(requests[0].read_text())
                    self.assertEqual(request['provider'], self.provider)
                    dest = Path(td) / 'decisions' / (request['id'] + '.json')
                    temp = dest.with_suffix('.tmp')
                    temp.write_text(json.dumps({'decision':decision})); temp.replace(dest)
                    out, err = p.communicate(timeout=8)
                    self.assertEqual(p.returncode, 0, err)
                    # Expected wire format comes from the PermissionRequest contract,
                    # not approval_output(): PreToolUse fields must fail this test.
                    expected_decision = {'behavior': decision}
                    if self.provider == 'codex' and decision == 'deny':
                        expected_decision['message'] = 'Denied from Vigil'
                    self.assertEqual(json.loads(out), {'hookSpecificOutput': {
                        'hookEventName': 'PermissionRequest',
                        'decision': expected_decision,
                    }})
                    record = json.loads(next((Path(td) / 'sessions').glob('*.json')).read_text())
                    self.assertEqual((record['state'], record['tier']),
                                     ('working', 2) if decision == 'allow' else ('idle', 1))
                    self.assertEqual(list((Path(td) / 'decisions').glob('*.json')), [])
                    self.assertEqual(list((Path(td) / 'requests').glob('*.json')), [])
                finally:
                    if p.poll() is None: p.kill(); p.communicate()

    def test_timeout_returns_no_decision(self):
        with tempfile.TemporaryDirectory() as td:
            payload = dict(session_id='timeout-fixture', cwd='C:/VigilIsolatedFixture',
                hook_event_name='PermissionRequest', permission_mode='default', tool_name='Bash',
                tool_input={'command':'echo timeout-fixture'})
            started = time.monotonic()
            result = subprocess.run(self.command('blocked'), input=json.dumps(payload),
                text=True, capture_output=True, timeout=55,
                env=dict(os.environ, VIGIL_DATA_DIR=td))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), '')
            self.assertGreaterEqual(time.monotonic() - started, 44)
            record = json.loads(next((Path(td) / 'sessions').glob('*.json')).read_text())
            self.assertEqual(record['provider'], self.provider)
            self.assertEqual(record['state'], 'blocked')
            self.assertEqual(list((Path(td) / 'decisions').glob('*.json')), [])
            self.assertEqual(list((Path(td) / 'requests').glob('*.json')), [])


class ClaudeHookProcessTests(HookProcessTests):
    provider = 'claude'
