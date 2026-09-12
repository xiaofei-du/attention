"""Full removal must erase owned data without touching unrelated profiles/files."""
import hashlib
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/uninstall.py'
ASSET = 'state/opening-audio/' + hashlib.sha256(b'personal audio').hexdigest() + '.aiff'

def write_payload(directory, extra=None):
    directory.mkdir(parents=True, exist_ok=True)
    files = {'attention.py': b'# fixture', 'nkc/store.py': b'# fixture', 'nkc/runtime.py': b'# fixture'}
    files.update(extra or {})
    for name, content in files.items():
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    (directory / 'payload.json').write_text(json.dumps({'version': '0.1.5', 'files': {
        name: hashlib.sha256(content).hexdigest() for name, content in files.items()}}))


class UninstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='attention uninstall ')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.data = self.base / 'Attention'
        self.codex = self.base / 'codex'
        self.claude = self.base / 'claude'
        self.codex.mkdir()
        self.claude.mkdir()
        (self.data / 'state/opening-audio').mkdir(parents=True)
        from nkc.store import Store
        Store(self.data / 'state')
        (self.data / ASSET).write_bytes(b'personal audio')
        write_payload(self.data / 'r/old')
        (self.data / 'e/old').mkdir(parents=True)
        (self.base / 'unrelated').write_text('keep me')
        for home in (self.codex, self.claude):
            (home / 'plugins/cache/xiaofei-du/attention/0.1.2').mkdir(parents=True)
            (home / 'plugins/cache/xiaofei-du/other').mkdir()
            (home / 'plugins/cache/xiaofei-du/other/file').write_text('keep plugin')
        self.env = dict(os.environ, CODEX_HOME=str(self.codex), CLAUDE_CONFIG_DIR=str(self.claude),
                        ATTENTION_DATA_DIR=str(self.data))

    def run_cli(self, *args):
        return subprocess.run([sys.executable, '-I', str(SCRIPT), *args], env=self.env,
                              cwd=self.base, capture_output=True, text=True, timeout=15)

    def module(self):
        spec = importlib.util.spec_from_file_location('attention_uninstall', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_preview_is_read_only_and_lists_personal_data(self):
        before = sorted(str(p.relative_to(self.base)) for p in self.base.rglob('*'))
        result = self.run_cli('--dry-run')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(self.data), result.stdout)
        self.assertIn('settings', result.stdout)
        self.assertEqual(before, sorted(str(p.relative_to(self.base)) for p in self.base.rglob('*')))

    def test_requires_explicit_yes_before_erasing_data(self):
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.data / ASSET).exists())

    def test_removes_both_caches_all_personal_data_and_is_idempotent(self):
        for _ in range(2):
            result = self.run_cli('--yes')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(self.data.exists())
            for home in (self.codex, self.claude):
                self.assertFalse((home / 'plugins/cache/xiaofei-du/attention').exists())
                self.assertEqual((home / 'plugins/cache/xiaofei-du/other/file').read_text(), 'keep plugin')
            self.assertEqual((self.base / 'unrelated').read_text(), 'keep me')

    def test_unsafe_root_and_unknown_root_content_refuse_before_mutation(self):
        (self.data / 'family-photos').mkdir()
        result = self.run_cli('--yes')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.data / ASSET).exists())
        self.env['ATTENTION_DATA_DIR'] = str(self.base)
        result = self.run_cli('--yes')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.base / 'unrelated').exists())

    def test_unknown_nested_files_block_all_removal(self):
        for relative in ('state/personal-note.txt', 'state/opening-audio/family-photo.jpg',
                         'r/old/private.txt', 'e/old/private.txt'):
            with self.subTest(relative=relative):
                self.setUp()
                canary = self.data / relative
                canary.write_text('unrelated personal file')
                result = self.run_cli('--yes')
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertEqual(canary.read_text(), 'unrelated personal file')
                self.assertTrue((self.codex / 'plugins/cache/xiaofei-du/attention').exists())
                canary.unlink()

    def test_unknown_cache_file_blocks_native_client_before_removal(self):
        canary = self.codex / 'plugins/cache/xiaofei-du/attention/0.1.2/private.txt'
        canary.write_text('keep me')
        (self.codex / 'config.toml').write_text('[plugins."attention@xiaofei-du"]\nenabled = true\n')
        binary = self.base / 'bin'
        binary.mkdir()
        marker = self.base / 'client-was-executed'
        (binary / 'codex').write_text('#!/bin/sh\ntouch "' + str(marker) + '"\n')
        (binary / 'codex').chmod(0o700)
        self.env['PATH'] = str(binary) + ':/usr/bin:/bin'
        result = self.run_cli('--yes')
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(canary.read_text(), 'keep me')
        self.assertTrue(self.data.exists())
        self.assertFalse(marker.exists())

    def test_foreign_owned_directory_is_preserved(self):
        mod = self.module()
        real_stat = Path.lstat
        def foreign(path):
            result = real_stat(path)
            if path == self.data / 'state':
                fields = list(result)
                fields[4] = os.geteuid() + 1
                return os.stat_result(fields)
            return result
        with patch.object(Path, 'lstat', foreign):
            with self.assertRaisesRegex(ValueError, 'owner'):
                mod.plan(self.data, self.codex, self.claude)
        self.assertTrue(self.data.exists())

    def test_other_user_writable_directory_is_preserved(self):
        (self.data / 'state').chmod(0o777)
        result = self.run_cli('--yes')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.data / ASSET).exists())

    def test_file_added_during_cleanup_survives(self):
        mod = self.module()
        removal = mod.plan(self.data, self.codex, self.claude)
        real_remove = mod.remove_inventory
        canary = self.data / 'state/private.txt'
        def add_file(path, expected):
            if path == self.data:
                canary.write_text('keep this new file')
            real_remove(path, expected)
        with patch.object(mod, 'remove_inventory', side_effect=add_file):
            with self.assertRaises(OSError):
                mod.execute(removal)
        self.assertEqual(canary.read_text(), 'keep this new file')

    def test_hard_linked_database_is_never_modified_or_deleted(self):
        original = self.base / 'private.sqlite3'
        os.link(self.data / 'state/queue.sqlite3', original)
        before = original.read_bytes()
        result = self.run_cli('--yes')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(original.read_bytes(), before)
        self.assertTrue(self.data.exists())

    def test_hard_linked_progress_file_does_not_overwrite_private_file(self):
        original = self.base / 'private.txt'
        original.write_text('my original private content')
        os.link(original, self.data / '.uninstall.tmp')
        result = self.run_cli('--yes')
        self.assertEqual(original.read_text(), 'my original private content')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_real_dependency_environment_is_removed_without_touching_shared_python(self):
        import shutil
        environment = self.data / 'e/installed'
        shutil.copytree(ROOT / '.venv', environment, symlinks=True)
        (environment / '.verified').write_text(json.dumps({
            'requirements': 'fixture', 'python': sys.version,
            'platform': sys.platform, 'architecture': 'fixture'}))
        original = Path(sys.executable).resolve()
        before = original.stat()
        result = self.run_cli('--yes')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(environment.exists())
        self.assertEqual(original.stat().st_ino, before.st_ino)
        self.assertEqual(original.stat().st_size, before.st_size)

    def test_clean_marketplace_clone_is_removed_but_untracked_file_blocks_removal(self):
        clone = self.codex / '.tmp/marketplaces/xiaofei-du'
        clone.parent.mkdir(parents=True)
        subprocess.run(['/usr/bin/git', 'clone', '--quiet', '--template=', '--no-hardlinks', str(ROOT), str(clone)],
                       check=True, capture_output=True)
        canary = clone / 'private.txt'
        canary.write_text('keep my note')
        result = self.run_cli('--yes')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(canary.read_text(), 'keep my note')
        canary.unlink()
        result = self.run_cli('--yes')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(clone.exists())

    def test_root_execution_is_refused_even_with_yes(self):
        mod = self.module()
        with patch.object(mod.os, 'geteuid', return_value=0):
            with self.assertRaisesRegex(ValueError, 'root|sudo'):
                mod.plan(self.data, self.codex, self.claude)
        self.assertTrue(self.data.exists())

    def test_replaced_directory_after_preview_is_preserved(self):
        mod = self.module()
        removal = mod.plan(self.data, self.codex, self.claude)
        original = self.base / 'original'
        self.data.rename(original)
        import shutil
        shutil.copytree(original, self.data)
        with self.assertRaisesRegex((ValueError, RuntimeError), 'changed|replaced'):
            mod.execute(removal)
        self.assertTrue((self.data / 'state/queue.sqlite3').exists())
        self.assertTrue((original / 'state/queue.sqlite3').exists())

    def test_directory_replaced_while_stopping_worker_is_not_written(self):
        mod = self.module()
        removal = mod.plan(self.data, self.codex, self.claude)
        def replace(found, root):
            root.rename(self.base / 'original-data')
            root.mkdir()
            (root / '.uninstall.json').write_text('unrelated replacement file')
        with patch.object(mod, 'stop_workers', side_effect=replace):
            with self.assertRaisesRegex(RuntimeError, 'replaced|changed'):
                mod.execute(removal)
        self.assertEqual((self.data / '.uninstall.json').read_text(), 'unrelated replacement file')

    def test_symlinked_root_and_cache_are_never_followed(self):
        alias = self.base / 'alias'
        alias.symlink_to(self.data, target_is_directory=True)
        self.env['ATTENTION_DATA_DIR'] = str(alias)
        self.assertNotEqual(self.run_cli('--yes').returncode, 0)
        self.env['ATTENTION_DATA_DIR'] = str(self.data)
        cache = self.codex / 'plugins/cache/xiaofei-du/attention'
        import shutil
        shutil.rmtree(cache)
        cache.symlink_to(self.data, target_is_directory=True)
        self.assertNotEqual(self.run_cli('--yes').returncode, 0)
        self.assertTrue((self.data / ASSET).exists())

    def test_unknown_symlink_inside_data_preserves_everything(self):
        (self.data / 'state/opening-audio/link').symlink_to(self.base / 'unrelated')
        result = self.run_cli('--yes')
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.base / 'unrelated').read_text(), 'keep me')

    def test_malformed_client_metadata_preserves_everything(self):
        (self.claude / 'plugins/installed_plugins.json').write_text('{broken')
        result = self.run_cli('--yes')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.data.exists())
        self.assertTrue((self.codex / 'plugins/cache/xiaofei-du/attention').exists())

    def test_missing_native_cli_cannot_claim_success_or_delete_shared_state(self):
        (self.codex / 'config.toml').write_text('[plugins."attention@xiaofei-du"]\nenabled = true\n')
        self.env['PATH'] = str(self.base / 'missing-bin')
        result = self.run_cli('--yes')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.data.exists())
        self.assertIn('codex', result.stderr)

    def test_active_mcp_blocks_purge(self):
        mod = self.module()
        plan = mod.plan(self.data, self.codex, self.claude)
        active = {'pid': 12345, 'argv': ['python', str(self.data / 'r/old/attention.py'), 'mcp'],
                  'start': 'test'}
        with patch.object(mod, 'processes', return_value=[active]):
            with self.assertRaisesRegex(RuntimeError, 'Close'):
                mod.execute(plan)
        self.assertTrue(self.data.exists())

    def test_real_silent_worker_exits_before_data_is_deleted(self):
        mod = self.module()
        from nkc.store import Store
        store = Store(self.data / 'state')
        store.enqueue('codex', 'test', 'turn', 'never spoken')
        ready = self.base / 'ready'
        runtime = self.data / 'r/old/run.py'
        runtime.write_text("""import sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from nkc.store import Store
from nkc.runtime import run_worker
root = Path(sys.argv[-2])
def silent(text, settings, cancelled):
    Path(sys.argv[2]).touch()
    while not cancelled():
        time.sleep(.02)
    return False
run_worker(Store(root), play=silent)
""")
        write_payload(runtime.parent, {'run.py': runtime.read_bytes()})
        proc = subprocess.Popen([sys.executable, str(runtime), str(ROOT), str(ready),
                                 '--state-dir', str(self.data / 'state'), 'worker'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        import time
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertTrue(ready.exists(), 'silent worker failed to start')
        result = self.run_cli('--yes')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(proc.wait(timeout=5), 0, proc.stderr.read().decode())
        proc.stderr.close()
        self.assertFalse(self.data.exists())

    def test_success_exit_from_native_cli_is_not_sufficient(self):
        (self.codex / 'config.toml').write_text('[plugins."attention@xiaofei-du"]\nenabled = true\n')
        binary = self.base / 'bin'
        binary.mkdir()
        (binary / 'codex').write_text('#!/bin/sh\nexit 0\n')
        (binary / 'codex').chmod(0o700)
        self.env['PATH'] = str(binary)
        result = self.run_cli('--yes')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.data.exists())
        self.assertIn('still registered', result.stderr)

    def test_remaining_claude_project_scope_prevents_shared_data_deletion(self):
        project = self.base / 'project'
        project.mkdir()
        registry = {'version': 2, 'plugins': {'attention@xiaofei-du': [
            {'scope': 'project', 'projectPath': str(project),
             'installPath': str(self.claude / 'plugins/cache/xiaofei-du/attention/0.1.2')}]}}
        (self.claude / 'plugins/installed_plugins.json').write_text(json.dumps(registry))
        binary = self.base / 'bin'
        binary.mkdir()
        (binary / 'claude').write_text('#!/bin/sh\nexit 0\n')
        (binary / 'claude').chmod(0o700)
        self.env['PATH'] = str(binary)
        result = self.run_cli('--yes')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.data.exists())
        self.assertIn('still registered', result.stderr)

    def test_restarted_process_prevents_deleting_state(self):
        mod = self.module()
        removal = mod.plan(self.data, self.codex, self.claude)
        with patch.object(mod, 'processes', side_effect=[[], [{'pid': 123}]]):
            with self.assertRaisesRegex(RuntimeError, 'restarted'):
                mod.execute(removal)
        self.assertTrue(self.data.exists())

    def test_recreated_files_after_delete_are_reported_as_incomplete(self):
        mod = self.module()
        removal = mod.plan(self.data, self.codex, self.claude)
        real_remove = mod.remove_inventory
        def recreate(path, expected):
            real_remove(path, expected)
            if path == self.data:
                (path / 'notices').mkdir(parents=True)
        with patch.object(mod, 'remove_inventory', side_effect=recreate):
            with self.assertRaisesRegex(RuntimeError, 'incomplete'):
                mod.execute(removal)

    def test_shared_marketplace_registration_and_source_are_preserved(self):
        clone = self.codex / '.tmp/marketplaces/xiaofei-du'
        clone.mkdir(parents=True)
        (clone / 'other').write_text('shared source')
        (self.codex / 'config.toml').write_text(
            '[plugins."other@xiaofei-du"]\nenabled=true\n'
            '[marketplaces.xiaofei-du]\nsource_type="git"\n'
            'source="https://github.com/xiaofei-du/attention.git"\n')
        result = self.run_cli('--yes')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((clone / 'other').read_text(), 'shared source')
        self.assertIn('shared with other plugins', result.stdout)
        self.assertFalse(self.data.exists())

    def test_marketplace_registration_must_also_disappear(self):
        (self.codex / 'config.toml').write_text(
            '[marketplaces.xiaofei-du]\nsource_type="git"\n'
            'source="https://github.com/xiaofei-du/attention.git"\n')
        binary = self.base / 'bin'
        binary.mkdir()
        (binary / 'codex').write_text('#!/bin/sh\nexit 0\n')
        (binary / 'codex').chmod(0o700)
        self.env['PATH'] = str(binary)
        result = self.run_cli('--yes')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.data.exists())

    def test_scoped_setting_is_verified_across_partial_uninstall_retries(self):
        mod = self.module()
        from nkc.store import Store
        binary = self.base / 'bin'
        binary.mkdir()
        (binary / 'claude').write_text('#!/bin/sh\nexit 1\n')
        (binary / 'claude').chmod(0o700)
        for scope, name in [('project', 'settings.json'), ('local', 'settings.local.json')]:
            with self.subTest(scope=scope):
                Store(self.data / 'state')
                project = self.base / scope
                settings = project / '.claude' / name
                settings.parent.mkdir(parents=True)
                settings.write_text(json.dumps({'enabledPlugins': {'attention@xiaofei-du': True}}))
                registry = self.claude / 'plugins/installed_plugins.json'
                registry.write_text(json.dumps({'version': 2, 'plugins': {'attention@xiaofei-du': [
                    {'scope': scope, 'projectPath': str(project)}]}}))
                removal = mod.plan(self.data, self.codex, self.claude)
                def incomplete(command, **kwargs):
                    registry.write_text('{"version":2,"plugins":{}}')
                    return subprocess.CompletedProcess(command, 0)
                with patch.dict(os.environ, {'PATH': str(binary)}), \
                        patch.object(mod, 'processes', return_value=[]), \
                        patch.object(mod.subprocess, 'run', side_effect=incomplete):
                    with self.assertRaisesRegex(RuntimeError, 'still registered'):
                        mod.execute(removal)
                    retry = mod.plan(self.data, self.codex, self.claude)
                    with self.assertRaisesRegex(RuntimeError, 'still registered'):
                        mod.execute(retry)
                    self.assertTrue(self.data.exists())
                    settings.write_text('{"enabledPlugins":{}}')
                    mod.execute(mod.plan(self.data, self.codex, self.claude))
                    self.assertFalse(self.data.exists())

    def test_unrelated_sqlite_database_and_fake_payload_are_not_ownership(self):
        import shutil
        shutil.rmtree(self.data)
        (self.data / 'state').mkdir(parents=True)
        with sqlite3.connect(self.data / 'state/queue.sqlite3') as db:
            db.execute('create table unrelated_payroll (salary integer)')
        for fake_payload in (False, True):
            if fake_payload:
                (self.data / 'r/fake').mkdir(parents=True)
                (self.data / 'r/fake/payload.json').write_text('{}')
            result = self.run_cli('--yes')
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue((self.data / 'state/queue.sqlite3').exists())

    def test_notice_only_unsupported_installation_can_be_fully_removed(self):
        import shutil
        shutil.rmtree(self.data)
        (self.data / 'notices').mkdir(parents=True)
        (self.data / 'notices/0123456789abcdef').write_text('Attention! requires macOS 14.2+')
        result = self.run_cli('--yes')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.data.exists())

    def test_failed_native_remove_preserves_shared_data_and_reports_failure(self):
        (self.codex / 'config.toml').write_text('[plugins."attention@xiaofei-du"]\nenabled = true\n')
        binary = self.base / 'bin'
        binary.mkdir()
        (binary / 'codex').write_text('#!/bin/sh\nexit 23\n')
        (binary / 'codex').chmod(0o700)
        self.env['PATH'] = str(binary)
        result = self.run_cli('--yes')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.data.exists())


if __name__ == '__main__':
    unittest.main()
