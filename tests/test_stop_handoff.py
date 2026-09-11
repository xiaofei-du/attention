"""Completion hooks must finish queue handoff before the host may exit.

Regression: codex exec cancels unfinished async hooks on session shutdown.
The real CLI failure is captured by scripts/verify_codex_hooks.py; these tests
cover every configuration entry point that can reintroduce that race.
"""
import unittest
from pathlib import Path

from nkc.install import definition
from nkc.isolation import _hooks
from scripts.build_marketplace import hooks


class StopHandoffTests(unittest.TestCase):
    def assert_waits_for_handoff(self, definitions):
        for group in definitions['Stop']:
            for handler in group['hooks']:
                self.assertFalse(handler.get('async', False),
                                 'Codex can cancel an async Stop before the notification is stored')

    def test_local_installer_waits_for_completion_handoff(self):
        self.assert_waits_for_handoff(definition('codex')['hooks'])

    def test_marketplace_waits_for_completion_handoff(self):
        self.assert_waits_for_handoff(hooks('codex', '${PLUGIN_ROOT}')['hooks'])

    def test_isolated_profile_waits_for_completion_handoff(self):
        self.assert_waits_for_handoff(_hooks(Path('/python'), Path('/runtime'),
                                          Path('/state'), Path('/ipc/summary.sock'), 'codex'))


if __name__ == '__main__':
    unittest.main()
