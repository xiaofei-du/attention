import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nkc.bootstrap import legacy_hook_conflict, prepare_runtime

PROJECT = Path(__file__).resolve().parent.parent


class PluginBootstrapTests(unittest.TestCase):
    def test_non_mac_entry_never_imports_audio_or_creates_queue(self):
        import sys
        for system, version in [('Windows', '11'), ('Linux', '6.8'), ('Darwin', '14.1')]:
            with self.subTest(system=system), tempfile.TemporaryDirectory() as temporary:
                script = '''
import builtins, runpy, sys
from nkc import platform_support
platform_support.platform_status = lambda: dict(supported=False, status='unsupported_platform', message='Attention! requires macOS 14.2+')
original = builtins.__import__
def safe_import(name, *args, **kwargs):
    if name in ('fcntl', 'aifc', 'nkc.audio', 'nkc.runtime', 'nkc.bootstrap'):
        raise AssertionError('Native import before platform check: ' + name)
    return original(name, *args, **kwargs)
builtins.__import__ = safe_import
sys.argv = ['attention.py', '--data-dir', sys.argv[1], 'hook', 'prompt', '--provider', 'codex']
runpy.run_path('attention.py', run_name='__main__')
'''
                result = subprocess.run([sys.executable, '-c', script, temporary], cwd=PROJECT,
                                        input='{}', text=True, capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('macOS 14.2', json.loads(result.stdout)['systemMessage'])
                self.assertFalse((Path(temporary) / 'state').exists())

    def test_runtime_survives_plugin_cache_removal_and_upgrade_keeps_user_data(self):
        import shutil
        with tempfile.TemporaryDirectory(prefix='attention spaces ') as temporary:
            base = Path(temporary)
            bundle = base / 'plugin cache'
            bundle.mkdir()
            root = base / 'Application Support' / 'Attention'
            def payload(text):
                (bundle / 'attention.py').write_text(text)
                (bundle / 'requirements.txt').write_text('')
                files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in bundle.iterdir() if p.name != 'payload.json'}
                (bundle / 'payload.json').write_text(json.dumps({'files': files}))
            payload('first version')
            with patch('nkc.bootstrap.shutil.which', return_value='/a path/uv'):
                first = prepare_runtime(bundle, root)
                self.assertNotIn("--with-requirements", (first / "attention").read_text())
                self.assertEqual(prepare_runtime(bundle, root), first)
                (root / 'state').mkdir()
                user_data = root / 'state' / 'preferences'
                user_data.write_text('my opening')
                payload('second version')
                second = prepare_runtime(bundle, root)
                self.assertNotEqual(first, second)
                shutil.rmtree(bundle)
                self.assertEqual((first / 'attention.py').read_text(), 'first version')
                self.assertEqual((second / 'attention.py').read_text(), 'second version')
                self.assertEqual(user_data.read_text(), 'my opening')

    def test_corrupt_payload_is_rejected_before_installing_a_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            bundle = base / 'plugin'
            bundle.mkdir()
            (bundle / 'attention.py').write_text('changed')
            (bundle / 'payload.json').write_text(json.dumps({'files': {'attention.py': '0' * 64}}))
            with self.assertRaisesRegex(ValueError, 'integrity'):
                prepare_runtime(bundle, base / 'data')
            self.assertFalse((base / 'data').exists())

    def test_legacy_hooks_are_detected_per_provider_without_changing_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hook = {'hooks': {'Stop': [{'hooks': [{'statusMessage': 'no-keyboard-code: spoken summary',
                                                 'command': '/python /old/run.py hook stop'}]}]}}
            path = root / 'hooks.json'
            path.write_text(json.dumps(hook))
            before = path.read_bytes()
            with patch.dict(os.environ, {'CODEX_HOME': str(root), 'CLAUDE_CONFIG_DIR': str(root)}):
                self.assertTrue(legacy_hook_conflict('codex'))
                self.assertFalse(legacy_hook_conflict('claude-code'))
            self.assertEqual(before, path.read_bytes())

    def test_installed_runtime_tampering_is_rejected_on_reuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            bundle = base / 'plugin'
            bundle.mkdir()
            source = bundle / 'attention.py'
            source.write_text('print("original")')
            (bundle / 'payload.json').write_text(json.dumps({'files': {
                'attention.py': hashlib.sha256(source.read_bytes()).hexdigest()}}))
            runtime = prepare_runtime(bundle, base / 'data')
            (runtime / 'attention.py').write_text('print("modified")')
            with self.assertRaisesRegex(ValueError, 'integrity'):
                prepare_runtime(bundle, base / 'data')

    def test_symlinked_payload_parent_is_not_followed(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            bundle = base / 'plugin'
            bundle.mkdir()
            outside = base / 'outside'
            outside.mkdir()
            (outside / 'code.py').write_text('print("outside")')
            (bundle / 'nkc').symlink_to(outside, target_is_directory=True)
            (bundle / 'payload.json').write_text(json.dumps({'files': {
                'nkc/code.py': hashlib.sha256((outside / 'code.py').read_bytes()).hexdigest()}}))
            with self.assertRaisesRegex(ValueError, 'integrity'):
                prepare_runtime(bundle, base / 'data')
            self.assertFalse((base / 'data').exists())
