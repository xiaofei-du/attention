import hashlib
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import unittest

import test_setup

ROOT = test_setup.ROOT


class SetupEntryTests(unittest.TestCase):
    setUp = test_setup.SetupTests.setUp
    save = test_setup.SetupTests.save
    mutations = test_setup.SetupTests.mutations

    def entry_env(self, uv=True):
        if uv:
            self.write_uv(self.bin / 'uv')
        return dict(self.env, TMPDIR=str(self.base))

    def write_uv(self, target):
        target.write_text('#!/bin/bash\n'
                          'if [[ "$1" == --version ]]; then echo "uv 0.12.10"; exit 0; fi\n'
                          '[[ "$1 $2 $3 $4 $5 $6 $7 $8" == '
                          '"run --no-config --no-project --isolated --python 3.12 python -I" ]] || exit 91\n'
                          'shift 8\nexec ' + repr(sys.executable) + ' -I "$@"\n')
        target.chmod(0o700)

    def run_entry(self, *args, script=None, env=None):
        self.assertTrue((ROOT / 'setup.sh').is_file(), 'The setup shell entry is not implemented')
        return subprocess.run(['/bin/bash', '-p', str(script or ROOT / 'setup.sh'), *args],
                              env=env or self.entry_env(), cwd=self.base, capture_output=True,
                              text=True, input='', start_new_session=True, timeout=20)

    def test_local_entry_installs_both_without_touching_project_python(self):
        (self.base / 'pyproject.toml').write_text('[project]\nname="untrusted"\nversion="0"\n')
        (self.base / '.python-version').write_text('2.7')
        result = self.run_entry('--client', 'both')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.mutations()), 4)
        self.assertFalse((self.base / '.venv').exists())

    def test_missing_uv_needs_explicit_consent_and_keeps_clients_unchanged(self):
        result = self.run_entry('--client', 'codex', env=self.entry_env(uv=False))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('uv', result.stderr)
        self.assertEqual(self.mutations(), [])

    def test_dry_run_with_missing_uv_never_installs_it(self):
        result = self.run_entry('--client', 'codex', '--dry-run', env=self.entry_env(uv=False))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('uv', result.stdout)
        self.assertFalse((self.bin / 'uv').exists())
        self.assertEqual(self.mutations(), [])

    def test_help_and_invalid_options_have_no_installation_side_effects(self):
        result = self.run_entry('--help', env=self.entry_env(uv=False))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--client', result.stdout)
        self.assertNotEqual(self.run_entry('--client', 'surprise').returncode, 0)
        self.assertEqual(self.mutations(), [])

    def test_modified_local_helper_is_rejected_without_execution(self):
        directory = self.base / 'download'
        (directory / 'scripts').mkdir(parents=True)
        self.assertTrue((ROOT / 'setup.sh').is_file(), 'The setup shell entry is not implemented')
        shutil.copy2(ROOT / 'setup.sh', directory / 'setup.sh')
        marker = self.base / 'executed'
        (directory / 'scripts/setup.py').write_text('open(' + repr(str(marker)) + ', "w").close()')
        result = self.run_entry('--client', 'codex', script=directory / 'setup.sh')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SHA-256', result.stderr)
        self.assertFalse(marker.exists())
        self.assertEqual(self.mutations(), [])

    def test_failed_brew_install_does_not_continue_to_plugin_installation(self):
        env = self.entry_env(uv=False)
        brew = self.bin / 'brew'
        brew.write_text('#!/bin/bash\n[[ "$1 $2" == "install uv" ]] || exit 91\nexit 8\n')
        brew.chmod(0o700)
        result = self.run_entry('--client', 'codex', '--install-uv', env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('uv', result.stderr)
        self.assertEqual(self.mutations(), [])

    def test_explicit_uv_install_can_continue_after_brew_succeeds(self):
        env = self.entry_env(uv=False)
        template = self.base / 'uv-template'
        self.write_uv(template)
        brew = self.bin / 'brew'
        brew.write_text('#!/bin/bash\n[[ "$1 $2" == "install uv" ]] || exit 91\n'
                        '/bin/cp "' + str(template) + '" "' + str(self.bin / 'uv') + '"\n')
        brew.chmod(0o700)
        result = self.run_entry('--client', 'codex', '--install-uv', env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.mutations()), 2)

    def test_missing_selected_client_does_not_install_uv(self):
        (self.bin / 'claude').unlink()
        result = self.run_entry('--client', 'both', '--install-uv', env=self.entry_env(uv=False))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('claude', result.stderr.lower())
        self.assertEqual(self.mutations(), [])

    def download_fixture(self, uv_installer=None, helper=None, fail=False):
        directory = self.base / 'download'
        directory.mkdir()
        helper_file = self.base / 'remote-helper'
        helper_file.write_bytes(helper if helper is not None else (ROOT / 'scripts/setup.py').read_bytes())
        uv_file = self.base / 'remote-uv-installer'
        uv_file.write_text(uv_installer or 'exit 77\n')
        curl = directory / 'curl'
        curl.write_text('#!/bin/bash\n' + ('exit 22\n' if fail else '') +
                        'for arg in "$@"; do case "$arg" in https://astral.sh/*) uv=true ;; esac; done\n'
                        'while [[ "$1" != -o ]]; do shift; done\n'
                        'if [[ "${uv:-}" == true ]]; then /bin/cp ' + shlex.quote(str(uv_file)) + ' "$2"; '
                        'else /bin/cp ' + shlex.quote(str(helper_file)) + ' "$2"; fi\n')
        curl.chmod(0o700)
        source = (ROOT / 'setup.sh').read_text().replace('/usr/bin/curl', shlex.quote(str(curl)))
        # This host has /sbin/sha256sum, while older supported Macs do not.
        # Exercise the standalone install on the latter system-tool inventory.
        source = source.replace('/usr/bin:/bin:/usr/sbin:/sbin', '/usr/bin:/bin:/usr/sbin')
        if uv_installer:
            source = source.replace('a3196b75f697a1adaa5e4af34ffba7629c710931ab1dac33bab59ecf228080bb',
                                    hashlib.sha256(uv_installer.encode()).hexdigest())
        entry = directory / 'setup.sh'
        entry.write_text(source)
        return entry

    def test_standalone_uv_path_supplies_a_working_binary_checksum_tool(self):
        template = self.base / 'uv-template'
        self.write_uv(template)
        checked = self.base / 'checksum-result'
        uv_script = ('#!/bin/sh\nset -eu\ncommand -v sha256sum >/dev/null\n'
                     'sha256sum -b "$0" > ' + shlex.quote(str(checked)) + '\n'
                     '/bin/mkdir -p "$UV_INSTALL_DIR"\n'
                     '/bin/cp ' + shlex.quote(str(template)) + ' "$UV_INSTALL_DIR/uv"\n')
        entry = self.download_fixture(uv_installer=uv_script)
        result = self.run_entry('--client', 'codex', '--install-uv', script=entry,
                                env=self.entry_env(uv=False))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(checked.read_text().split()[0], hashlib.sha256(uv_script.encode()).hexdigest())
        self.assertEqual(len(self.mutations()), 2)

    def test_wrong_downloaded_helper_never_executes(self):
        marker = self.base / 'executed'
        entry = self.download_fixture(helper=('open(' + repr(str(marker)) + ', "w").close()').encode())
        result = self.run_entry('--client', 'codex', script=entry)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SHA-256', result.stderr)
        self.assertFalse(marker.exists())
        self.assertEqual(self.mutations(), [])

    def test_network_failure_never_installs_plugins(self):
        result = self.run_entry('--client', 'codex', script=self.download_fixture(fail=True))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Download failed', result.stderr)
        self.assertEqual(self.mutations(), [])

    def test_streamed_entry_uses_the_verified_downloaded_helper(self):
        script = self.download_fixture()
        result = subprocess.run(['/bin/bash', '-p', '-s', '--', '--client', 'codex'],
                                input=script.read_text(), env=self.entry_env(), cwd=self.base,
                                capture_output=True, text=True, timeout=15, start_new_session=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.mutations()), 2)

    def test_changed_uv_installer_cannot_execute(self):
        script = self.download_fixture()
        marker = self.base / 'executed'
        (self.base / 'remote-uv-installer').write_text('touch ' + shlex.quote(str(marker)) + '\n')
        result = self.run_entry('--client', 'codex', '--install-uv', script=script,
                                env=self.entry_env(uv=False))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SHA-256', result.stderr)
        self.assertFalse(marker.exists())
        self.assertEqual(self.mutations(), [])

    def test_changed_helper_requires_refreshing_pins_before_release(self):
        checkout = self.base / 'checkout'
        for name in ('setup.sh', 'scripts/setup.py', 'scripts/update_setup_command.py',
                     'scripts/update_uninstall_command.py', 'docs/setup.md'):
            target = checkout / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, target)
        command = [sys.executable, '-I', str(checkout / 'scripts/update_setup_command.py')]
        self.assertEqual(subprocess.run([*command, '--check'], capture_output=True).returncode, 0)
        with (checkout / 'scripts/setup.py').open('a') as helper:
            helper.write('\n# changed release\n')
        result = subprocess.run([*command, '--check'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Stale setup', result.stderr)
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)
        self.assertEqual(subprocess.run([*command, '--check'], capture_output=True).returncode, 0)
