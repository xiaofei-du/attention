"""Exercise the installed entry with real safe cleanup and disposable user data."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

import test_uninstall
import test_uninstall_entry

ROOT = Path(__file__).resolve().parents[1]


class HomebrewEntryTests(unittest.TestCase):
    interactive = test_uninstall_entry.UninstallEntryTests.interactive

    def setUp(self):
        test_uninstall.UninstallTests.setUp(self)
        self.home = self.base / 'home'
        self.home.mkdir()
        self.codex.rename(self.home / '.codex')
        self.claude.rename(self.home / '.claude')
        self.codex, self.claude = self.home / '.codex', self.home / '.claude'
        standard = self.home / 'Library/Application Support/Attention'
        standard.parent.mkdir(parents=True)
        self.data.rename(standard)
        self.data = standard
        self.keg = self.base / 'Cellar/attention/0.1.6/libexec'
        self.keg.mkdir(parents=True)
        self.assertTrue((ROOT / 'homebrew/attention').is_file(), 'Homebrew command is not implemented')
        shutil.copy2(ROOT / 'homebrew/attention', self.keg / 'attention')
        for name in ('setup.sh', 'uninstall.sh'):
            shutil.copy2(ROOT / name, self.keg / name)
        (self.keg / 'scripts').mkdir()
        for name in ('setup.py', 'uninstall.py'):
            shutil.copy2(ROOT / 'scripts' / name, self.keg / 'scripts' / name)
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        (self.bin / 'python3').symlink_to(sys.executable)
        uv = self.bin / 'uv'
        uv.write_text('#!/bin/bash\nprintf "%s\\n" "' + sys.executable + '"\n')
        uv.chmod(0o700)
        (self.bin / 'attention').symlink_to(self.keg / 'attention')
        self.brew_calls = self.base / 'brew-calls'
        brew = self.bin / 'brew'
        brew.write_text('#!/bin/bash\nprintf "%s\\n" "$@" > "$BREW_CALLS"\n'
                        'printf "%s" "$HOMEBREW_NO_AUTOREMOVE" > "$BREW_CALLS.env"\n'
                        'exit "${BREW_RESULT:-0}"\n')
        brew.chmod(0o700)
        (self.keg / 'brew-path').write_text(str(brew) + '\n')
        (self.keg / 'uv-bin').write_text(str(self.bin) + '\n')
        (self.keg / 'VERSION').write_text('0.1.6\n')
        self.env = dict(os.environ, HOME=str(self.home), PATH=str(self.bin), TMPDIR=str(self.base),
                        BREW_CALLS=str(self.brew_calls))
        for name in ('CODEX_HOME', 'CLAUDE_CONFIG_DIR', 'ATTENTION_DATA_DIR'):
            self.env.pop(name, None)

    def run_entry(self, *args):
        return subprocess.run(['/bin/bash', '-p', str(self.bin / 'attention'), *args],
                              env=self.env, cwd=self.base, capture_output=True, text=True,
                              timeout=15, start_new_session=True)

    def test_help_version_and_invalid_commands_do_not_change_profiles(self):
        self.assertIn('attention setup', self.run_entry('--help').stdout)
        self.assertIn('0.1.6', self.run_entry('--version').stdout)
        self.assertEqual(self.run_entry('garbage').returncode, 2)
        self.assertTrue(self.data.exists())
        self.assertFalse(self.brew_calls.exists())

    def test_uninstall_preview_keeps_data_and_brew_entry(self):
        result = self.run_entry('uninstall', '--dry-run', '--offline')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(self.data), result.stdout)
        self.assertIn('Homebrew', result.stdout)
        self.assertTrue(self.data.exists())
        self.assertFalse(self.brew_calls.exists())

    def test_confirmed_cleanup_delegates_only_attention_to_brew(self):
        result = self.run_entry('uninstall', '--yes', '--offline')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.data.exists())
        self.assertEqual(self.brew_calls.read_text().splitlines(),
                         ['uninstall', '--formula', '--force', 'xiaofei-du/tap/attention'])
        self.assertEqual(Path(str(self.brew_calls) + '.env').read_text(), '1')
        self.assertEqual((self.base / 'unrelated').read_text(), 'keep me')
        self.assertTrue((self.codex / 'plugins/cache/xiaofei-du/other/file').exists())

    def test_cancel_keeps_brew_entry_and_all_data(self):
        result = self.interactive('no', entry=self.bin / 'attention',
                                  arguments=['uninstall', '--offline'], env=self.env)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertTrue(self.data.exists())
        self.assertFalse(self.brew_calls.exists())

    def test_cleanup_failure_does_not_remove_brew_entry(self):
        (self.data / 'family-photos').mkdir()
        result = self.run_entry('uninstall', '--yes', '--offline')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.data.exists())
        self.assertFalse(self.brew_calls.exists())

    def test_brew_failure_is_reported_with_retry_command(self):
        self.env['BREW_RESULT'] = '9'
        result = self.run_entry('uninstall', '--yes', '--offline')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.data.exists())
        self.assertIn('brew uninstall', result.stderr)

    def test_custom_profile_cleanup_preserves_shared_brew_entry(self):
        self.env['ATTENTION_DATA_DIR'] = str(self.data)
        result = self.run_entry('uninstall', '--yes', '--offline')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.data.exists())
        self.assertFalse(self.brew_calls.exists())
        self.assertIn('custom', result.stdout.lower())

    def test_uninstall_help_never_removes_entry(self):
        result = self.run_entry('uninstall', '--help')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.brew_calls.exists())

    def test_project_bashenv_and_brew_cannot_hijack_entry(self):
        attack = self.base / 'attack'
        attack.write_text('/usr/bin/touch "' + str(self.base / 'hacked') + '"\n')
        self.env['BASH_ENV'] = str(attack)
        self.env['PATH'] = '.:' + str(self.bin)
        (self.base / 'brew').write_text('#!/bin/bash\n/usr/bin/touch hacked\n')
        (self.base / 'brew').chmod(0o700)
        result = self.run_entry('uninstall', '--yes', '--offline')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.base / 'hacked').exists())

    def check_project_python_is_not_executed(self, *arguments):
        project_bin = self.base / 'project/.venv/bin'
        project_bin.mkdir(parents=True)
        attack = project_bin / 'python3'
        attack.write_text('#!/bin/bash\n/usr/bin/touch "' + str(self.base / 'python-hijacked') + '"\n'
                          'exec "' + sys.executable + '" "$@"\n')
        attack.chmod(0o700)
        self.env['PATH'] = str(project_bin) + ':' + str(self.bin)
        # The uv bin is distinct from the ordinary Python shim directory.
        uv_bin = self.base / 'pinned-uv'
        uv_bin.mkdir()
        uv = uv_bin / 'uv'
        uv.write_text('#!/bin/bash\nprintf "%s\\n" "' + sys.executable + '"\n')
        uv.chmod(0o700)
        (self.keg / 'uv-bin').write_text(str(uv_bin) + '\n')
        result = self.run_entry('uninstall', *arguments)
        self.assertFalse((self.base / 'python-hijacked').exists())
        return result

    def test_project_python_is_not_executed_during_uninstall(self):
        result = self.check_project_python_is_not_executed('--dry-run', '--offline')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_help_as_a_data_path_cannot_skip_managed_python(self):
        result = self.check_project_python_is_not_executed('--data-dir', '--help')
        self.assertNotEqual(result.returncode, 0)

    def test_setup_delegates_invalid_options_without_touching_profiles(self):
        result = self.run_entry('setup', '--client', 'bogus')
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('--client', result.stderr)
        self.assertTrue(self.data.exists())

    @unittest.skipUnless(shutil.which('uv'), 'real uv is needed for interpreter-discovery regression')
    def test_real_uv_does_not_inspect_active_project_virtualenv(self):
        uv_bin = self.base / 'real-uv'
        uv_bin.mkdir()
        (uv_bin / 'uv').symlink_to(shutil.which('uv'))
        (self.keg / 'uv-bin').write_text(str(uv_bin) + '\n')
        project = self.base / 'active-project/.venv'
        (project / 'bin').mkdir(parents=True)
        (project / 'pyvenv.cfg').write_text('home = /usr/bin\n')
        marker = self.base / 'active-python-executed'
        python = project / 'bin/python3'
        python.write_text('#!/bin/bash\n/usr/bin/touch "' + str(marker) + '"\nexit 1\n')
        python.chmod(0o700)
        self.env.update(VIRTUAL_ENV=str(project), UV_CACHE_DIR=str(self.base / 'uv-cache'),
                        UV_PYTHON_INSTALL_DIR=str(self.base / 'no-managed-python'))
        result = self.run_entry('uninstall', '--dry-run', '--offline')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(marker.exists(), 'uv executed the active project interpreter')
        self.assertTrue(self.data.exists())
        self.assertFalse(self.brew_calls.exists())
