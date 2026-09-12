"""Exercise the actual marketplace launch command against a harmless local wheel."""
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts.build_marketplace import server, hooks

PROJECT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(shutil.which('uv'), 'requires uv')
class DependencyInstallTests(unittest.TestCase):
    def fixture(self, base, valid, bundled=False):
        plugin = base / 'plugin with spaces'
        plugin.mkdir()
        shutil.copytree(PROJECT / 'nkc', plugin / 'nkc', ignore=shutil.ignore_patterns('__pycache__'))
        if (PROJECT / 'launch.py').exists():
            shutil.copy2(PROJECT / 'launch.py', plugin / 'launch.py')
        wheel = base / 'attention_probe-1.0-py3-none-any.whl'
        with zipfile.ZipFile(wheel, 'w') as archive:
            archive.writestr('attention_probe.py', "VALUE = 'verified dependency executed'\n")
            archive.writestr('attention_probe-1.0.dist-info/METADATA',
                             'Metadata-Version: 2.1\nName: attention-probe\nVersion: 1.0\n')
            archive.writestr('attention_probe-1.0.dist-info/WHEEL',
                             'Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n')
            archive.writestr('attention_probe-1.0.dist-info/RECORD', '')
        digest = hashlib.sha256(wheel.read_bytes()).hexdigest() if valid else '0' * 64
        if bundled:
            (plugin / 'wheels').mkdir()
            wheel = wheel.rename(plugin / 'wheels' / wheel.name)
        requirement = 'attention-probe==1.0' if bundled else f'attention-probe @ {wheel.as_uri()}'
        (plugin / 'requirements.txt').write_text(
            f'{requirement} --hash=sha256:{digest}\n')
        (plugin / 'attention.py').write_text('import attention_probe\nprint(attention_probe.VALUE)\n')
        files = {p.relative_to(plugin).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in plugin.rglob('*') if p.is_file()}
        (plugin / 'payload.json').write_text(json.dumps({'files': files}))
        return plugin, wheel

    def launch(self, plugin, base, provider):
        placeholder = '${PLUGIN_ROOT}' if provider == 'codex' else '${CLAUDE_PLUGIN_ROOT}'
        config = server(placeholder)
        command = [config['command'], *[a.replace(placeholder, str(plugin)) for a in config['args']]]
        env = {**os.environ, 'ATTENTION_DATA_DIR': str(base / 'data'),
               'UV_CACHE_DIR': str(base / 'cache'), 'UV_NO_PROGRESS': '1'}
        return subprocess.run(command, cwd=plugin, env=env, text=True,
                              capture_output=True, timeout=120)

    def test_relocated_bundled_wheel_starts_both_clients(self):
        for provider in ('codex', 'claude-code'):
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                plugin, _ = self.fixture(base, valid=True, bundled=True)
                plugin = plugin.rename(base / 'relocated plugin')
                result = self.launch(plugin, base, provider)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('verified dependency executed', result.stdout)

    def test_wrong_bundled_wheel_hash_blocks_both_clients(self):
        for provider in ('codex', 'claude-code'):
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                plugin, _ = self.fixture(base, valid=False, bundled=True)
                result = self.launch(plugin, base, provider)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Hash mismatch', result.stderr)
                self.assertNotIn('verified dependency executed', result.stdout)
                self.assertFalse(list((base / 'data').glob('e/*/.verified')))

    def test_different_process_architectures_do_not_share_dependency_environments(self):
        from nkc.dependencies import verified_python
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            plugin, _ = self.fixture(base, valid=True)
            interpreters = []
            for architecture in ('arm64', 'x86_64'):
                with patch('platform.machine', return_value=architecture):
                    interpreters.append(verified_python(plugin / 'requirements.txt', base / 'data'))
            self.assertNotEqual(*interpreters)

    def test_wrong_hash_blocks_dependency_and_entry_point_for_both_clients(self):
        for provider in ('codex', 'claude-code'):
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                plugin, _ = self.fixture(base, valid=False)
                result = self.launch(plugin, base, provider)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertNotIn('verified dependency executed', result.stdout)
                self.assertIn('Hash mismatch', result.stderr)
                self.assertFalse(list((base / 'data').glob('e/*/.verified')))

    def test_verified_environment_is_reused_without_downloading_again(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            plugin, wheel = self.fixture(base, valid=True)
            result = self.launch(plugin, base, 'codex')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('verified dependency executed', result.stdout)

            wheel.unlink()
            shutil.rmtree(base / 'cache')
            result = self.launch(plugin, base, 'claude-code')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('verified dependency executed', result.stdout)

    def test_hook_hash_failure_skips_plugin_without_blocking_original_turn(self):
        for provider, variable in [('codex', '${PLUGIN_ROOT}'), ('claude-code', '${CLAUDE_PLUGIN_ROOT}')]:
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                plugin, _ = self.fixture(base, valid=False)
                handler = hooks(provider, variable)['hooks']['UserPromptSubmit'][0]['hooks'][0]
                command = shlex.split(handler['command'].replace(variable, str(plugin)))
                result = subprocess.run(command, cwd=plugin, input='{}', text=True, capture_output=True,
                                        timeout=120, env=dict(os.environ, ATTENTION_DATA_DIR=str(base / 'data'),
                                                             UV_CACHE_DIR=str(base / 'cache')))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn('verified dependency executed', result.stdout)
                self.assertIn('could not verify', json.loads(result.stdout)['systemMessage'])
                self.assertFalse(list((base / 'data').glob('e/*/.verified')))
