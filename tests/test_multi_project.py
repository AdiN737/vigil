"""Four concurrent hook processes, two projects, no real agent commands."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
import vigil_hook as hook
import vigil_decide as decisions

class MultiProjectTests(unittest.TestCase):
    def test_distinct_native_ids_do_not_collide_on_disk(self):
        ids = ['worker/a', 'worker:a', 'x'*100+'1', 'x'*100+'2', 'CON', 'con', 'worker', 'WORKER']
        files = [hook.session_file(s) for s in ids]
        self.assertEqual(len(set(files)), len(ids))

    def test_same_folder_name_has_distinct_project_identity(self):
        self.assertNotEqual(hook.project_identity('C:/one/web'), hook.project_identity('C:/two/web'))
        self.assertEqual(hook.project_identity('C:/One/Web/'), hook.project_identity('c:\\one\\web'))

    def test_idless_projects_do_not_overwrite_each_other(self):
        with tempfile.TemporaryDirectory() as td:
            for cwd in ['C:/one/web', 'C:/two/web']:
                result = self.invoke(td, 'working', dict(cwd=cwd, hook_event_name='UserPromptSubmit'))
                self.assertEqual(result.returncode, 0, result.stderr)
            records = self.records(td)
            self.assertEqual(len(records), 2)
            self.assertEqual(len({r['project_id'] for r in records}), 2)

    def test_project_title_cannot_suppress_two_agents_in_the_same_project(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(hook, 'SESSIONS', td), mock.patch('vigil_platform.foreground_title', return_value='web - terminal'):
            for i in range(2):
                Path(td, f'{i}.json').write_text(json.dumps(dict(project='web', updated=time.time())))
            self.assertFalse(hook._user_is_at('web'))
            Path(td, '1.json').unlink()
            self.assertTrue(hook._user_is_at('web'))

    def command(self, state, provider):
        binary = os.environ.get('VIGIL_TEST_HOOK')
        return ([binary] if binary else [sys.executable, str(ROOT / 'app/vigil_hook_main.py')]) + [state, provider]

    def invoke(self, td, state, payload, provider='claude'):
        return subprocess.run(self.command(state, provider),
            input=json.dumps(payload), text=True, capture_output=True, timeout=10,
            env=dict(os.environ, VIGIL_DATA_DIR=td))

    def records(self, td):
        return [json.loads(p.read_text()) for p in (Path(td)/'sessions').glob('*.json')]

    def channel(self, td):
        return mock.patch.multiple(decisions, REQUESTS=str(Path(td)/'requests'), DECISIONS=str(Path(td)/'decisions'))

    def test_stale_missing_and_conflicting_decisions_are_rejected(self):
        with tempfile.TemporaryDirectory() as td, self.channel(td):
            self.assertFalse(decisions.decide('missing','allow'))
            self.assertFalse(decisions.decide('../escape','allow'))
            Path(decisions.request_path('malformed')).write_text('[]')
            self.assertFalse(decisions.decide('malformed','allow'))
            r = decisions.open_request('expired','session','project','Bash','echo test',5)
            r['expires']=time.time()-1
            Path(decisions.request_path('expired')).write_text(json.dumps(r))
            self.assertFalse(decisions.decide('expired','allow'))
            decisions.open_request('active','session','project','Bash','echo test',5)
            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes=list(pool.map(lambda d:decisions.decide('active',d),['allow','deny']))
            self.assertEqual(sum(outcomes),1)
            stored=json.loads(Path(decisions.decision_path('active')).read_text())
            self.assertEqual(stored['decision'], ['allow','deny'][outcomes.index(True)])
            self.assertEqual(stored['session_id'],'session')

    def test_four_sessions_route_overlapping_decisions_independently(self):
        with tempfile.TemporaryDirectory() as td, self.channel(td):
            payloads=[dict(session_id=f'session-{i}', cwd=f'C:/VigilFixture/Project-{i//2}',
                hook_event_name='PermissionRequest',tool_name='Bash',tool_input={'command':f'echo fixture-{i}'})
                for i in range(4)]
            processes=[]
            try:
                for i,payload in enumerate(payloads):
                    provider='claude' if i%2==0 else 'codex'
                    p=subprocess.Popen(self.command('blocked', provider),
                        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
                        env=dict(os.environ,VIGIL_DATA_DIR=td))
                    processes.append(p)
                    p.stdin.write(json.dumps(payload));p.stdin.close();p.stdin=None
                until=time.monotonic()+12
                requests=[]
                while time.monotonic()<until:
                    requests=decisions.pending()
                    if len(requests)==4:break
                    time.sleep(.03)
                self.assertEqual(len(requests),4)
                records=self.records(td)
                self.assertEqual(len(records),4)
                self.assertEqual(len({r['project_id'] for r in records}),2)
                by_detail={r['detail']:r for r in requests}
                for i in [3,0,2,1]:
                    req=by_detail[f'echo fixture-{i}']
                    verdict='deny' if i%2 else 'allow'
                    self.assertTrue(decisions.decide(req['id'],verdict))
                    out,err=processes[i].communicate(timeout=8)
                    self.assertEqual(processes[i].returncode,0,err)
                    self.assertEqual(json.loads(out)['hookSpecificOutput']['decision']['behavior'],verdict)
                    for j,p in enumerate(processes):
                        if j in [3,0,2,1][: [3,0,2,1].index(i)+1]:continue
                        self.assertIsNone(p.poll(),f'Session {j} answered by another request')
                self.assertEqual(len(decisions.pending()),0)
                final=self.records(td)
                self.assertEqual(sum(r['state']=='working' for r in final),2)
                self.assertEqual(sum(r['state']=='idle' for r in final),2)
                self.invoke(td,'idle',dict(payloads[0],hook_event_name='SessionEnd'))
                self.assertEqual(len(self.records(td)),3)
            finally:
                for p in processes:
                    if p.poll() is None:p.kill();p.communicate()

if __name__=='__main__':unittest.main()
