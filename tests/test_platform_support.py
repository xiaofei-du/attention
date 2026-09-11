import json
import tempfile
import unittest
from pathlib import Path

from nkc.platform_support import platform_status, disabled_hook


class PlatformSupportTests(unittest.TestCase):
    def test_minimum_version_and_architecture(self):
        cases = [('Darwin', '14.2', 'arm64', True), ('Darwin', '14.2.1', 'x86_64', True),
                 ('Darwin', '26.0', 'arm64', True), ('Darwin', '14.1.9', 'arm64', False),
                 ('Darwin', '', 'arm64', False), ('Darwin', '14.2', 'other', False),
                 ('Linux', '6.8', 'x86_64', False), ('Windows', '11', 'AMD64', False)]
        for system, version, machine, expected in cases:
            with self.subTest(system=system, version=version, machine=machine):
                self.assertEqual(platform_status(system, version, machine)['supported'], expected)

    def test_unsupported_hooks_warn_once_without_creating_a_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            status = platform_status('Windows', '11', 'AMD64')
            self.assertEqual(disabled_hook(root, status, 'stop'), {})
            first = disabled_hook(root, status, 'prompt')
            self.assertIn('macOS 14.2', first['systemMessage'])
            self.assertNotIn('additionalContext', json.dumps(first))
            self.assertEqual(disabled_hook(root, status, 'prompt'), {})
            self.assertEqual(list(root.rglob('*.sqlite3')), [])
