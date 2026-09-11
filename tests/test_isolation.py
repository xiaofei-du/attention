import json
import os
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from nkc.isolation import prepare_isolation


class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='.nkc-iso-', dir=Path.home())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        for name in ('project', 'runtime', 'state', 'control', 'credentials'):
            (self.root / name).mkdir(mode=0o700)
        for name in ('run.py', 'mcp_server.py', 'submit.py'):
            (self.root / 'runtime' / name).write_text('# trusted\n')
        self.python = Path('/usr/bin/python3')
        self.args = dict(project=self.root/'project', runtime=self.root/'runtime',
                         state=self.root/'state', socket_path=self.root/'control'/'s.sock',
                         output=self.root/'generated', python=self.python,
                         credential_paths=[self.root/'credentials'])

    def generate(self, **changes):
        with patch('nkc.isolation.sys.platform', 'darwin'):
            return prepare_isolation(**(self.args | changes))

    def test_private_reviewable_files_and_exact_socket(self):
        out = self.generate()
        self.assertEqual(out.stat().st_mode & 0o777, 0o700)
        cfg = tomllib.loads((out/'codex-home'/'config.toml').read_text())
        profile = cfg['permissions']['nkc-isolated']
        self.assertEqual(profile['network'], {'enabled': False, 'unix_sockets': {str(self.args['socket_path']): 'allow'}})
        self.assertEqual(profile['filesystem'][str(self.args['state'])], 'deny')
        self.assertEqual(profile['filesystem'][str(self.args['runtime'])], 'read')
        self.assertEqual(cfg['approval_policy'], 'never')
        self.assertIn('--confirm-controls', cfg['mcp_servers']['attention']['args'])
        self.assertIn('--summary-socket', cfg['hooks']['Stop'][0]['hooks'][0]['command'])
        settings = json.loads((out/'claude-settings.json').read_text())
        self.assertFalse(settings['sandbox']['allowUnsandboxedCommands'])
        self.assertTrue(settings['sandbox']['failIfUnavailable'])
        self.assertEqual(settings['sandbox']['excludedCommands'], [])
        self.assertEqual(settings['sandbox']['network']['allowUnixSockets'], [str(self.args['socket_path'])])
        self.assertEqual(settings['sandbox']['network']['allowedDomains'], [])
        self.assertNotIn('ask', settings['permissions'])
        self.assertIn('--setting-sources', (out/'launch-claude.sh').read_text())
        for file in out.rglob('*'):
            if file.is_file(): self.assertEqual(file.stat().st_mode & 0o077, 0)

    def test_existing_output_fails_without_overwrite(self):
        self.generate()
        marker = self.args['output']/'keep'
        marker.write_text('untouched')
        with self.assertRaises(ValueError): self.generate()
        self.assertEqual(marker.read_text(), 'untouched')

    def test_unsupported_platform_fails(self):
        with patch('nkc.isolation.sys.platform', 'linux'):
            with self.assertRaises(ValueError): prepare_isolation(**self.args)
        self.assertFalse(self.args['output'].exists())

    def test_protected_paths_cannot_overlap_project_or_each_other(self):
        for changes in ({'runtime': self.args['project']}, {'output': self.args['project']/'out'},
                        {'state': self.args['runtime']/'state'}, {'project': self.root},
                        {'socket_path': self.args['state']/'s.sock'},
                        {'credential_paths': [self.args['runtime']/'secret']},
                        {'credential_paths': [self.args['project']/'secret']}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): self.generate(**changes)

    def test_symlinks_in_paths_fail(self):
        link = self.root/'alias'
        link.symlink_to(self.args['project'], target_is_directory=True)
        with self.assertRaises(ValueError): self.generate(project=link)
        (self.args['runtime']/'submit.py').unlink()
        (self.args['runtime']/'submit.py').symlink_to(self.python)
        with self.assertRaises(ValueError): self.generate()

    def test_ambient_temporary_protection_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            with self.assertRaises(ValueError): self.generate(output=base/'out')
            fake_python = base/'python'
            fake_python.write_text('#!/bin/sh\nexit 0\n')
            fake_python.chmod(0o700)
            with self.assertRaises(ValueError): self.generate(python=fake_python)

    def test_read_roots_cannot_reopen_private_or_project_paths(self):
        for path in [self.root, self.args['project'], self.args['state'], Path.home()]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.generate(runtime_read_paths=[path])

    def test_relative_long_socket_and_glob_paths_fail(self):
        for changes in ({'project': Path('relative')}, {'socket_path': self.root/'control'/('é'*70)},
                        {'output': self.root/'*glob'}, {'output': self.root/'line\nbreak'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): self.generate(**changes)

    def test_shell_quoting_preserves_literal_metacharacters(self):
        project = self.root / "project 'with $dollar `tick`"
        project.mkdir()
        out = self.generate(project=project)
        launch = (out/'launch-claude.sh').read_text()
        import shlex
        cd_line = next(x for x in launch.splitlines() if x.startswith('cd '))
        self.assertEqual(shlex.split(cd_line)[1:], [str(project)])



@unittest.skipUnless(os.environ.get('NKC_RUN_CODEX_SANDBOX_PROBE') == '1',
                     'Explicit opt-in real Codex sandbox probe; no model/audio')
class RealCodexSandboxProbe(unittest.TestCase):
    setUp = IsolationTests.setUp
    generate = IsolationTests.generate

    def test_sandboxed_client_stages_summary_with_database_denied(self):
        import shutil
        import subprocess
        import sys
        from nkc.isolation import _toml
        from nkc.runtime import handle_hook, run_worker
        from nkc.store import Store
        from nkc.submission import SharedSummaryBroker
        source = Path(__file__).resolve().parents[1]
        runtime = self.args['runtime']
        shutil.copy2(source/'submit.py', runtime/'submit.py')
        shutil.copytree(source/'nkc', runtime/'nkc', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        python = Path(sys.executable).resolve()
        out = self.generate(python=python, runtime_read_paths=[Path(sys.base_prefix).resolve()])
        cfg = tomllib.loads((out/'codex-home/config.toml').read_text())
        store = Store(self.args['state'])
        token = store.begin_turn('codex', 'fake-session', 'one')
        command = ['codex', 'sandbox', '-P', 'nkc-isolated', '-C', str(self.args['project']),
                   '--allow-unix-socket', str(self.args['socket_path'])]
        for key, value in cfg.items(): command += ['-c', key+'='+_toml(value)]
        payload = {'why': 'Protect task notifications.', 'done': 'Private database stayed protected.', 'next': ''}
        with SharedSummaryBroker(store, self.args['socket_path']):
            result = subprocess.run([*command, '--', str(python), '-I', str(runtime/'submit.py'),
                '--socket', str(self.args['socket_path']), '--token', token], input=json.dumps(payload),
                text=True, capture_output=True, timeout=20,
                env=dict(os.environ, CODEX_HOME=str(out/'codex-home')))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {'staged': True})
            denied = subprocess.run([*command, '--', '/bin/cat', str(store.root/'queue.sqlite3')],
                text=True, capture_output=True, timeout=10,
                env=dict(os.environ, CODEX_HOME=str(out/'codex-home')))
            self.assertNotEqual(denied.returncode, 0)
            self.assertEqual(denied.stdout, '')
        handle_hook('stop', {'hook_event_name': 'Stop', 'session_id': 'fake-session', 'turn_id': 'one',
                            'last_assistant_message': 'Long technical answer. ' * 100}, store,
                    start_worker=lambda _: None)
        with store.db() as db: db.execute('UPDATE jobs SET ready_after=0')
        heard = []
        run_worker(store, play=lambda text, settings, cancelled: heard.append(text) or True)
        self.assertEqual(len(heard), 1)
        self.assertIn(payload['done'], heard[0])

    def test_generated_profile_file_and_network_boundaries(self):
        import socket
        import subprocess
        import sys
        from nkc.isolation import _toml
        (self.args['state']/'secret').write_text('fake-state')
        (self.root/'credentials'/'secret').write_text('fake-credential')
        (self.args['project']/'state-link').symlink_to(self.args['state']/'secret')
        python = Path(sys.executable).resolve()
        out = self.generate(python=python, runtime_read_paths=[Path(sys.base_prefix).resolve()])
        cfg = tomllib.loads((out/'codex-home/config.toml').read_text())
        listeners = []
        for endpoint in (self.args['socket_path'], self.root/'control'/'other.sock'):
            listener = socket.socket(socket.AF_UNIX)
            listener.bind(str(endpoint)); listener.listen(2)
            listeners.append(listener); self.addCleanup(listener.close)
        tcp = socket.socket()
        tcp.bind(('127.0.0.1', 0)); tcp.listen(1)
        self.addCleanup(tcp.close)
        fake_token = 'nkc-canary-token-no-authority'
        dummy = subprocess.Popen([str(python), '-c', 'import time; time.sleep(20)', '--token', fake_token])
        self.addCleanup(lambda: (dummy.terminate(), dummy.wait(timeout=5)))
        code = '''from pathlib import Path
import json,socket,subprocess
root=Path(ROOT)
results={}
def connect(address, family):
 with socket.socket(family) as client:
  client.settimeout(1)
  client.connect(address)
for name, operation in [
 ('project_write',lambda:(root/'project'/'ok').write_text('yes')),
 ('runtime_read',lambda:(root/'runtime'/'submit.py').read_text()),
 ('state_read',lambda:(root/'state'/'secret').read_text()),
 ('credential_read',lambda:(root/'credentials'/'secret').read_text()),
 ('symlink_read',lambda:(root/'project'/'state-link').read_text()),
 ('runtime_write',lambda:(root/'runtime'/'submit.py').write_text('bad')),
 ('config_write',lambda:(root/'generated'/'claude-settings.json').write_text('bad')),
 ('runtime_rename',lambda:(root/'runtime').rename(root/'renamed')),
 ('parent_rename',lambda:root.rename(root.with_name(root.name+'-moved'))),
 ('state_delete',lambda:(root/'state'/'secret').unlink()),
 ('socket_unlink',lambda:(root/'control'/'s.sock').unlink()),
 ('summary_socket',lambda:connect(str(root/'control'/'s.sock'),socket.AF_UNIX)),
 ('other_socket',lambda:connect(str(root/'control'/'other.sock'),socket.AF_UNIX)),
 ('tcp_network',lambda:connect(('127.0.0.1',PORT),socket.AF_INET))]:
 try: operation(); results[name]='allowed'
 except OSError as exc: results[name]='blocked'
try:
 args = subprocess.check_output(['/bin/ps','-p',str(DUMMY_PID),'-o','args='],text=True,stderr=subprocess.DEVNULL)
 results['fake_token_argv'] = 'visible' if 'nkc-canary-token-no-authority' in args else 'not-visible'
except (OSError,subprocess.CalledProcessError): results['fake_token_argv'] = 'blocked'
print(json.dumps(results))
'''.replace('ROOT', repr(str(self.root))).replace('PORT', str(tcp.getsockname()[1])).replace('DUMMY_PID', str(dummy.pid))
        command = ['codex', 'sandbox', '-P', 'nkc-isolated', '-C', str(self.args['project']), '--allow-unix-socket', str(self.args['socket_path'])]
        for key, value in cfg.items(): command += ['-c', key+'='+_toml(value)]
        command += ['--', str(python), '-I', '-c', code]
        result = subprocess.run(command, text=True, capture_output=True, timeout=20,
                                env=dict(os.environ, CODEX_HOME=str(out/'codex-home')))
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads(result.stdout)
        argv_result = observed.pop('fake_token_argv')
        self.assertEqual(argv_result, 'blocked', 'Known fake-token process argv was readable')
        print('Known dummy process argv:', argv_result)
        allowed = {'project_write', 'runtime_read', 'summary_socket'}
        expected = {key: 'allowed' if key in allowed else 'blocked' for key in observed}
        self.assertEqual(observed, expected)
        self.assertEqual(len(observed), 14)
        print('Codex sandbox canaries:', json.dumps(observed, sort_keys=True))


if __name__ == '__main__': unittest.main()
