"""Run the installer against stateful client doubles in disposable profiles."""
import json
import os
import select
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/setup.py'

# These are the native CLI JSON shapes, observed with Codex 0.154.0 and
# Claude Code 2.1.268. The doubles replace only the external client processes;
# the real setup script owns discovery, source checks, decisions and recovery.
CLIENT = r'''#!PYTHON
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
root = pathlib.Path(os.environ['FIXTURE_ROOT'])
state = root / (name + '.json')
data = json.loads(state.read_text())
args = sys.argv[1:]
with (root / 'calls').open('a') as f:
    f.write(json.dumps([name, *args]) + '\n')
if args == ['plugin', 'marketplace', 'list', '--json']:
    print(json.dumps({'marketplaces': data['markets']} if name == 'codex' else data['markets']))
elif args == ['plugin', 'list', '--json']:
    if data.get('malformed'): print('{broken')
    else: print(json.dumps({'installed': data['plugins'], 'available': []} if name == 'codex' else data['plugins']))
elif args == ['plugin', 'marketplace', 'add', 'xiaofei-du/attention']:
    if data.get('fail_market'): sys.exit(12)
    data['markets'] = ([{'name':'xiaofei-du', 'root':'/cache/marketplace',
                        'marketplaceSource':{'sourceType':'git','source':'https://github.com/xiaofei-du/attention.git'}}]
                      if name == 'codex' else [{'name':'xiaofei-du','source':'github','repo':'xiaofei-du/attention','installLocation':'/cache/marketplace'}])
    state.write_text(json.dumps(data))
elif args == (['plugin','add','attention@xiaofei-du'] if name == 'codex' else
              ['plugin','install','attention@xiaofei-du','--scope','user']):
    if data.get('fail_install'): sys.exit(13)
    if not data.get('no_registration'):
        data['plugins'] = ([{'pluginId':'attention@xiaofei-du','name':'attention','marketplaceName':'xiaofei-du','version':'0.1.5','installed':True,'enabled':True}]
                           if name == 'codex' else [{'id':'attention@xiaofei-du','version':'0.1.5','scope':'user','enabled':True,'installPath':'/cache/attention/0.1.5'}])
        state.write_text(json.dumps(data))
else:
    print('Unexpected client command: ' + repr(args), file=sys.stderr)
    sys.exit(99)
'''


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='attention setup ')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        self.home = self.base / 'home'
        self.home.mkdir()
        self.env = dict(os.environ, HOME=str(self.home), PATH=str(self.bin),
                        FIXTURE_ROOT=str(self.base), CODEX_HOME=str(self.home / '.codex'),
                        CLAUDE_CONFIG_DIR=str(self.home / '.claude'))
        for name in ('codex', 'claude'):
            exe = self.bin / name
            exe.write_text(CLIENT.replace('PYTHON', sys.executable))
            exe.chmod(0o700)
            self.save(name, markets=[], plugins=[])
        (self.home / 'unrelated').write_text('keep me')

    def save(self, name, **data):
        path = self.base / (name + '.json')
        previous = json.loads(path.read_text()) if path.exists() else {}
        path.write_text(json.dumps(dict(previous, **data)))

    def run_setup(self, *args, env=None):
        self.assertTrue(SCRIPT.is_file(), 'The setup helper is not implemented')
        return subprocess.run([sys.executable, '-I', str(SCRIPT), *args],
                              cwd=self.base, env=env or self.env, text=True,
                              capture_output=True, timeout=15, start_new_session=True)

    def mutations(self):
        path = self.base / 'calls'
        calls = [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []
        return [c for c in calls if 'list' not in c]

    def test_both_clients_use_native_installation_and_second_run_skips(self):
        first = self.run_setup('--client', 'both')
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(self.mutations(), [
            ['codex','plugin','marketplace','add','xiaofei-du/attention'],
            ['codex','plugin','add','attention@xiaofei-du'],
            ['claude','plugin','marketplace','add','xiaofei-du/attention'],
            ['claude','plugin','install','attention@xiaofei-du','--scope','user'],
        ])
        before = self.mutations()
        second = self.run_setup('--client', 'both')
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.mutations(), before)
        self.assertIn('Trust', second.stdout)
        self.assertEqual((self.home / 'unrelated').read_text(), 'keep me')

    def test_missing_selected_client_fails_before_modifying_other_client(self):
        (self.bin / 'claude').unlink()
        result = self.run_setup('--client', 'both')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('claude', result.stderr.lower())
        self.assertEqual(self.mutations(), [])

    def test_name_collision_is_refused_before_any_installation(self):
        self.save('claude', markets=[{'name':'xiaofei-du','source':'github','repo':'someone/other'}])
        result = self.run_setup('--client', 'both')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('source', result.stderr.lower())
        self.assertEqual(self.mutations(), [])

    def test_legacy_plugin_requires_migration_instead_of_double_install(self):
        self.save('codex', plugins=[{'pluginId':'attention@attention-marketplace','installed':True}])
        result = self.run_setup('--client', 'codex')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('upgrading', result.stderr)
        self.assertEqual(self.mutations(), [])

    def test_disabled_existing_plugin_is_preserved(self):
        self.assertEqual(self.run_setup('--client','claude').returncode, 0)
        self.save('claude', plugins=[{'id':'attention@xiaofei-du','scope':'user','version':'0.1.2','enabled':False}])
        before = self.mutations()
        result = self.run_setup('--client','claude')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('disabled', result.stdout.lower())
        self.assertIn('upgrading', result.stdout)
        self.assertEqual(self.mutations(), before)

    def test_malformed_list_is_not_treated_as_empty_installation(self):
        self.save('codex', malformed=True)
        result = self.run_setup('--client', 'codex')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.mutations(), [])

    def test_partial_install_can_resume_without_reinstalling_first_client(self):
        self.save('claude', fail_install=True)
        first = self.run_setup('--client', 'both')
        self.assertNotEqual(first.returncode, 0)
        self.assertIn('claude', first.stderr.lower())
        self.save('claude', fail_install=False)
        second = self.run_setup('--client', 'both')
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(sum(c[:3] == ['codex','plugin','add'] for c in self.mutations()), 1)
        self.assertEqual(sum(c[:4] == ['claude','plugin','marketplace','add'] for c in self.mutations()), 1)

    def test_success_exit_without_registration_is_not_reported_as_installed(self):
        self.save('codex', no_registration=True)
        result = self.run_setup('--client', 'codex')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('registration', result.stderr.lower())

    def test_dry_run_does_not_add_sources_or_plugins(self):
        result = self.run_setup('--client', 'both', '--dry-run')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.mutations(), [])
        self.assertIn('Would', result.stdout)

    def test_noninteractive_invocation_requires_explicit_client(self):
        result = self.run_setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('--client', result.stderr)
        self.assertEqual(self.mutations(), [])

    def test_relative_path_client_is_not_executed(self):
        env = dict(self.env, PATH='bin')
        result = self.run_setup('--client', 'codex', env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.mutations(), [])

    def test_project_scope_is_not_silently_migrated_to_user(self):
        self.save('claude', plugins=[{'id':'attention@xiaofei-du','scope':'project','enabled':True}])
        result = self.run_setup('--client', 'claude')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.mutations(), [])

    def test_real_terminal_selection_installs_selected_clients(self):
        status = self.base / 'terminal-status'
        runner = self.base / 'runner.sh'
        runner.write_text('#!/bin/bash\n"$1" -I "$2"\nresult=$?\nprintf "%s" "$result" > "$3"\n')
        proc = subprocess.Popen(['/usr/bin/script', '-q', '/dev/null', '/bin/bash', str(runner),
                                 sys.executable, str(SCRIPT), str(status)],
                                cwd=self.base, env=self.env, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        def stop():
            if proc.poll() is None:
                proc.kill()
            proc.communicate(timeout=5)
        self.addCleanup(stop)
        output = b''
        deadline = time.monotonic() + 12
        while b'Choose 1' not in output and time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            if select.select([proc.stdout], [], [], .05)[0]:
                output += os.read(proc.stdout.fileno(), 4096)
        self.assertIn(b'Choose 1', output)
        self.assertEqual(self.mutations(), [])
        proc.stdin.write(b'3\n')
        proc.stdin.flush()
        while not status.exists() and time.monotonic() < deadline:
            if select.select([proc.stdout], [], [], .05)[0]:
                output += os.read(proc.stdout.fileno(), 4096)
        self.assertTrue(status.exists(), output.decode())
        out, _ = proc.communicate(timeout=5)
        self.assertEqual(status.read_text(), '0', (output + out).decode())
        self.assertEqual(len(self.mutations()), 4)
