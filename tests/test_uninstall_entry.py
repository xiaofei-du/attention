"""Exercise the public shell entry against disposable profiles, never real installs."""
import os
import select
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

import test_uninstall

ROOT = Path(__file__).resolve().parents[1]


class UninstallEntryTests(unittest.TestCase):
    setUp = test_uninstall.UninstallTests.setUp

    def entry_env(self, python=True):
        entry = ROOT / 'uninstall.sh'
        self.assertTrue(entry.is_file(), 'The public uninstall entry is missing')
        binary = self.base / 'bin'
        binary.mkdir(exist_ok=True)
        interpreter = binary / 'python3'
        if python and not interpreter.exists():
            interpreter.symlink_to(sys.executable)
        return dict(self.env, HOME=str(self.base / 'home'), PATH=str(binary), TMPDIR=str(self.base))

    def run_entry(self, *args, script=None, input='', env=None, offline=True):
        env = env or self.entry_env()
        entry = ROOT / 'uninstall.sh'
        options = ['--offline'] if offline else []
        return subprocess.run(['/bin/bash', str(script or entry), *options, *args],
                              input=input, env=env, cwd=self.base, text=True,
                              capture_output=True, timeout=15, start_new_session=True)

    def detached_entry(self):
        directory = self.base / 'download'
        directory.mkdir(exist_ok=True)
        shutil.copy2(ROOT / 'uninstall.sh', directory / 'uninstall.sh')
        return directory / 'uninstall.sh'

    def interactive(self, answer, before_answer=None):
        env = self.entry_env()
        status = self.base / 'terminal-status'
        harness = self.base / 'terminal-harness.sh'
        harness.write_text('#!/bin/bash\n/bin/bash "$1" --offline\nresult=$?\n'
                           'printf "%s" "$result" > "$2"\nexit "$result"\n')
        command = ['/bin/bash', str(harness), str(ROOT / 'uninstall.sh'), str(status)]
        if sys.platform == 'darwin':
            command = ['/usr/bin/script', '-q', '/dev/null', *command]
        else:
            import shlex
            command = ['/usr/bin/script', '-q', '-e', '-c', shlex.join(command), '/dev/null']
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, env=env, cwd=self.base)
        def stop():
            if proc.poll() is None:
                proc.kill()
            proc.communicate(timeout=5)
        self.addCleanup(stop)
        prompt = b''
        deadline = time.monotonic() + 8
        while b'Type yes' not in prompt and time.monotonic() < deadline:
            if proc.poll() is not None:
                out, _ = proc.communicate()
                self.fail('Exited before terminal confirmation: ' + (prompt + out).decode())
            if select.select([proc.stdout], [], [], .05)[0]:
                prompt += os.read(proc.stdout.fileno(), 4096)
        self.assertIn(b'Type yes', prompt)
        self.assertTrue(self.data.exists(), 'Data deleted before consent')
        if before_answer:
            before_answer()
        proc.stdin.write((answer + '\n').encode())
        proc.stdin.flush()
        deadline = time.monotonic() + 8
        while not status.exists() and time.monotonic() < deadline:
            if select.select([proc.stdout], [], [], .05)[0]:
                prompt += os.read(proc.stdout.fileno(), 4096)
        self.assertTrue(status.exists(), prompt.decode())
        out, _ = proc.communicate(timeout=10)
        return subprocess.CompletedProcess(proc.args, int(status.read_text()), (prompt + out).decode(), '')

    def test_preview_works_with_local_python_without_uv_and_preserves_all_files(self):
        result = self.run_entry('--dry-run')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(self.data), result.stdout)
        self.assertTrue((self.data / test_uninstall.ASSET).is_file())
        self.assertEqual((self.base / 'unrelated').read_text(), 'keep me')

    def test_piped_yes_is_not_interactive_consent(self):
        result = self.run_entry(input='yes\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('terminal', result.stderr.lower())
        self.assertTrue(self.data.exists())

    def test_explicit_yes_removes_owned_data_but_preserves_neighbors(self):
        result = self.run_entry('--yes')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.data.exists())
        self.assertEqual((self.base / 'unrelated').read_text(), 'keep me')
        for home in (self.codex, self.claude):
            self.assertEqual((home / 'plugins/cache/xiaofei-du/other/file').read_text(), 'keep plugin')

    def test_modified_helper_is_rejected_before_it_can_execute(self):
        self.assertTrue((ROOT / 'uninstall.sh').is_file(), 'The public uninstall entry is missing')
        directory = self.base / 'download'
        (directory / 'scripts').mkdir(parents=True)
        shutil.copy2(ROOT / 'uninstall.sh', directory / 'uninstall.sh')
        marker = self.base / 'executed'
        (directory / 'scripts/uninstall.py').write_text(
            'from pathlib import Path\nPath(' + repr(str(marker)) + ').touch()\n')
        result = self.run_entry('--yes', script=directory / 'uninstall.sh')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(marker.exists())
        self.assertTrue(self.data.exists())

    def test_arbitrary_cwd_helper_is_never_discovered(self):
        self.assertTrue((ROOT / 'uninstall.sh').is_file(), 'The public uninstall entry is missing')
        directory = self.base / 'download'
        directory.mkdir()
        shutil.copy2(ROOT / 'uninstall.sh', directory / 'uninstall.sh')
        marker = self.base / 'executed'
        (self.base / 'scripts').mkdir()
        (self.base / 'scripts/uninstall.py').write_text(
            'from pathlib import Path\nPath(' + repr(str(marker)) + ').touch()\n')
        result = self.run_entry('--yes', script=directory / 'uninstall.sh')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(marker.exists())
        self.assertTrue(self.data.exists())

    def test_terminal_yes_deletes_only_after_confirmation(self):
        result = self.interactive('yes')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.data.exists())
        self.assertEqual((self.base / 'unrelated').read_text(), 'keep me')

    def test_terminal_no_leaves_installation_untouched(self):
        result = self.interactive('no')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Cancelled', result.stdout)
        self.assertTrue(self.data.exists())

    def test_changed_installation_after_preview_is_not_deleted(self):
        def change():
            (self.data / 'family-photos').mkdir()
            (self.data / 'family-photos/photo').write_text('keep family')
        result = self.interactive('yes', before_answer=change)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.data / 'family-photos/photo').read_text(), 'keep family')

    def test_local_helper_is_discovered_for_each_client_and_retained_runtime(self):
        script = self.detached_entry()
        for directory in (self.codex / 'plugins/cache/xiaofei-du/attention/0.1.5/scripts',
                          self.claude / 'plugins/cache/xiaofei-du/attention/0.1.5/scripts',
                          self.data / 'r/retained/scripts'):
            with self.subTest(directory=directory):
                directory.mkdir(parents=True)
                helper = directory / 'uninstall.py'
                test_uninstall.write_payload(directory.parent, {'scripts/uninstall.py': (ROOT / 'scripts/uninstall.py').read_bytes()})
                result = self.run_entry('--dry-run', script=script)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(str(self.data), result.stdout)
                shutil.rmtree(directory.parent)

    def test_symlink_helper_is_rejected_even_with_the_correct_bytes(self):
        script = self.detached_entry()
        directory = script.parent / 'scripts'
        directory.mkdir()
        (directory / 'uninstall.py').symlink_to(ROOT / 'scripts/uninstall.py')
        result = self.run_entry('--yes', script=script)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.data.exists())

    def test_shell_metacharacters_in_data_path_stay_literal(self):
        moved = self.base / 'Attention; touch HACKED; $(touch INJECTED)'
        self.data.rename(moved)
        result = self.run_entry('--yes', '--data-dir', str(moved))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(moved.exists())
        self.assertFalse((self.base / 'HACKED').exists())
        self.assertFalse((self.base / 'INJECTED').exists())
        self.assertEqual((self.base / 'unrelated').read_text(), 'keep me')

    def test_unsafe_data_directory_is_refused_by_existing_validator(self):
        result = self.run_entry('--yes', '--data-dir', str(self.base))
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.data.exists())
        self.assertEqual((self.base / 'unrelated').read_text(), 'keep me')

    def test_missing_python_and_uv_preserves_data(self):
        result = self.run_entry('--yes', env=self.entry_env(python=False))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Python', result.stderr)
        self.assertTrue(self.data.exists())

    def test_uv_can_find_an_existing_python_without_installing_dependencies(self):
        env = self.entry_env(python=False)
        uv = self.base / 'bin/uv'
        uv.write_text('#!/bin/sh\ncase "$*" in\n'
                      '"python find --no-project --system --no-config --offline --no-python-downloads 3.12") '
                      'printf "%s\\n" "' + sys.executable + '";;\n*) exit 88;;\nesac\n')
        uv.chmod(0o700)
        result = self.run_entry('--dry-run', env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(self.data), result.stdout)

    def test_wrong_download_bytes_cannot_execute(self):
        env = self.entry_env()
        script = self.detached_entry()
        curl = self.base / 'bin/curl'
        marker = self.base / 'executed'
        payload = 'from pathlib import Path\nPath(' + repr(str(marker)) + ').touch()\n'
        source = self.base / 'bad.py'
        source.write_text(payload)
        curl.write_text('#!/bin/sh\nwhile [ "$1" != "-o" ]; do shift; done\n'
                        '/bin/cp "' + str(source) + '" "$2"\n')
        curl.chmod(0o700)
        result = self.run_entry('--yes', script=script, env=env, offline=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SHA-256 mismatch', result.stderr)
        self.assertFalse(marker.exists())
        self.assertTrue(self.data.exists())

    def test_pythonpath_and_current_directory_cannot_inject_imports(self):
        env = self.entry_env()
        marker = self.base / 'executed'
        for name in ('sitecustomize.py', 'hashlib.py', 'json.py'):
            (self.base / name).write_text('from pathlib import Path\nPath(' + repr(str(marker)) + ').touch()\n')
        env['PYTHONPATH'] = str(self.base)
        result = self.run_entry('--dry-run', env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(marker.exists())

    def test_package_build_rejects_a_stale_helper_digest(self):
        from scripts import build_marketplace
        source = self.base / 'source'
        (source / 'scripts').mkdir(parents=True)
        shutil.copy2(ROOT / 'uninstall.sh', source / 'uninstall.sh')
        (source / 'scripts/uninstall.py').write_text('print("unexpected helper")\n')
        with patch.object(build_marketplace, 'ROOT', source):
            with self.assertRaises((ValueError, RuntimeError)) as failure:
                build_marketplace.build_payload(self.base / 'payload')
            self.assertRegex(str(failure.exception), 'uninstall.*SHA-256')

    def test_empty_relative_and_glob_path_entries_do_not_execute_cwd_programs(self):
        env = self.entry_env(python=False)
        marker = self.base / 'executed'
        fake = self.base / 'python3'
        fake.write_text('#!/bin/sh\nprintf hacked > "' + str(marker) + '"\nexit 1\n')
        fake.chmod(0o700)
        glob_root = self.base / 'glob'
        (glob_root / 'untrusted').mkdir(parents=True)
        shutil.copy2(fake, glob_root / 'untrusted/python3')
        for path in ('', '.', ':relative:.', str(glob_root / '*')):
            with self.subTest(path=path):
                marker.unlink(missing_ok=True)
                result = self.run_entry('--dry-run', env=dict(env, PATH=path))
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(marker.exists(), 'Untrusted PATH entry was executed')
                self.assertTrue(self.data.exists())

    def test_inherited_python_shell_function_is_not_an_interpreter(self):
        env = self.entry_env(python=False)
        marker = self.base / 'executed'
        result = subprocess.run(['/bin/bash', '-c',
                                 'export MARKER="$2"; python3() { printf hacked > "$MARKER"; }; export -f python3; '
                                 '/bin/bash "$1" --offline --dry-run', 'test',
                                 str(ROOT / 'uninstall.sh'), str(marker)],
                                env=env, cwd=self.base, capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(marker.exists())
        self.assertTrue(self.data.exists())

    def test_real_uv_does_not_probe_project_virtualenv_executable(self):
        uv = shutil.which('uv')
        if not uv:
            self.skipTest('uv is unavailable')
        env = self.entry_env(python=False)
        (self.base / 'bin/uv').symlink_to(uv)
        marker = self.base / 'executed'
        fake = self.base / '.venv/bin/python'
        fake.parent.mkdir(parents=True)
        fake.write_text('#!/bin/sh\nprintf hacked > "' + str(marker) + '"\nexit 1\n')
        fake.chmod(0o700)
        env.update(UV_CACHE_DIR=str(self.base / 'uv-cache'),
                   UV_PYTHON_INSTALL_DIR=str(self.base / 'uv-python'),
                   VIRTUAL_ENV=str(self.base / '.venv'))
        result = self.run_entry('--dry-run', env=env)
        self.assertFalse(marker.exists(), 'uv executed untrusted project virtualenv code')
        self.assertTrue(self.data.exists())

    def test_unrelated_shell_with_data_argument_still_blocks_deletion(self):
        proc = subprocess.Popen(['/bin/bash', '-c', 'read -r line', 'guard', str(self.data)],
                                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            result = self.run_entry('--yes')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Active Attention PIDs', result.stderr)
            self.assertTrue(self.data.exists())
        finally:
            proc.communicate(b'finish\n', timeout=5)

    def test_shipped_entries_remove_owned_data_from_both_provider_packages(self):
        from nkc.store import Store
        bundle = Path(os.environ.get('ATTENTION_TEST_MARKETPLACE', str(ROOT)))
        for folder in ('plugins', 'claude-plugins'):
            with self.subTest(provider=folder):
                Store(self.data / 'state')
                script = bundle / folder / 'attention/uninstall.sh'
                self.assertTrue(script.is_file(), 'The installed plugin needs an offline uninstall entry')
                result = self.run_entry('--yes', script=script)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(self.data.exists())
                self.assertEqual((self.base / 'unrelated').read_text(), 'keep me')

    def test_matching_download_executes_the_verified_helper(self):
        env = self.entry_env()
        script = self.detached_entry()
        curl = self.base / 'bin/curl'
        curl.write_text('#!/bin/sh\nwhile [ "$1" != "-o" ]; do shift; done\n'
                        '/bin/cp "' + str(ROOT / 'scripts/uninstall.py') + '" "$2"\n')
        curl.chmod(0o700)
        result = self.run_entry('--yes', script=script, env=env, offline=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.data.exists())
        self.assertEqual((self.base / 'unrelated').read_text(), 'keep me')

    def test_streamed_launcher_discovers_local_helper_without_script_directory(self):
        env = self.entry_env()
        helper = self.claude / 'plugins/cache/xiaofei-du/attention/0.1.5/scripts/uninstall.py'
        helper.parent.mkdir(parents=True)
        test_uninstall.write_payload(helper.parent.parent, {'scripts/uninstall.py': (ROOT / 'scripts/uninstall.py').read_bytes()})
        result = subprocess.run(['/bin/bash', '-s', '--', '--offline', '--yes'],
                                input=(ROOT / 'uninstall.sh').read_text(), env=env, cwd=self.base,
                                capture_output=True, text=True, timeout=15, start_new_session=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.data.exists())
        self.assertEqual((self.base / 'unrelated').read_text(), 'keep me')

    def test_online_command_verifies_entry_bytes_before_execution(self):
        from scripts.update_uninstall_command import command
        import shlex
        env = self.entry_env()
        marker = self.base / 'entry-executed'
        good = ('#!/bin/bash\nprintf verified > ' + shlex.quote(str(marker)) + '\n').encode()
        source = self.base / 'downloaded-entry'
        curl = self.base / 'mock-curl'
        curl.write_text('#!/bin/sh\nwhile [ "$1" != "-o" ]; do shift; done\n'
                        '/bin/cp ' + shlex.quote(str(source)) + ' "$2"\n')
        curl.chmod(0o700)
        snippet = command(good).replace('/usr/bin/curl', shlex.quote(str(curl)))
        for shell in ('/bin/bash', '/bin/zsh'):
            if not Path(shell).exists():
                continue
            for modified in (True, False):
                with self.subTest(shell=shell, modified=modified):
                    source.write_bytes(good + (b'# altered\n' if modified else b''))
                    marker.unlink(missing_ok=True)
                    result = subprocess.run([shell, '-c', snippet], env=env, cwd=self.base,
                                            capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode == 0, not modified, result.stderr)
                    self.assertEqual(marker.exists(), not modified)
                    self.assertFalse(list(self.base.glob('attention-uninstall.*')))

    def test_online_entry_does_not_load_inherited_bash_startup_code(self):
        from scripts.update_uninstall_command import command
        import shlex
        marker = self.base / 'injected'
        startup = self.base / 'bash-startup'
        startup.write_text('printf injected > ' + shlex.quote(str(marker)) + '\n')
        content = b'#!/bin/bash\nexit 0\n'
        source = self.base / 'entry'
        source.write_bytes(content)
        curl = self.base / 'mock-curl'
        curl.write_text('#!/bin/sh\nwhile [ "$1" != "-o" ]; do shift; done\n'
                        '/bin/cp ' + shlex.quote(str(source)) + ' "$2"\n')
        curl.chmod(0o700)
        snippet = command(content).replace('/usr/bin/curl', shlex.quote(str(curl)))
        env = dict(self.entry_env(), BASH_ENV=str(startup))
        # -p on the outer test shell prevents the harness itself from reading BASH_ENV.
        result = subprocess.run(['/bin/bash', '-p', '-c', snippet], env=env, cwd=self.base,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(marker.exists())


if __name__ == '__main__':
    unittest.main()
