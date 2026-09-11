import json
import tempfile
import unittest
from pathlib import Path

from nkc.install import install_hooks, uninstall_hooks, definition


class InstallTests(unittest.TestCase):
    def test_control_context_hook_only_matches_attention_session_controls(self):
        import re
        from scripts.build_marketplace import hooks
        for provider, variable in [('codex', '${PLUGIN_ROOT}'), ('claude-code', '${CLAUDE_PLUGIN_ROOT}')]:
            for config in (definition(provider), hooks(provider, variable)):
                if provider == 'codex':
                    self.assertEqual(set(config['hooks']), {'UserPromptSubmit', 'Stop'})
                    continue
                self.assertIn('PreToolUse', config['hooks'])
                group = config['hooks']['PreToolUse'][0]
                self.assertIn('hook control-context', group['hooks'][0]['command'])
                for name in ('mcp__attention__set_session_enabled', 'mcp__plugin_attention_attention__get_status'):
                    self.assertTrue(re.fullmatch(group['matcher'], name))
                for name in ('Bash', 'mcp__attention__set_summary_preferences', 'mcp__other__get_status'):
                    self.assertFalse(re.fullmatch(group['matcher'], name))

    def test_install_is_idempotent_and_preserves_existing_hooks_and_notify(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            original = {'hooks': {'Stop': [{'hooks': [{'type': 'command', 'command': 'existing-command'}]}]}}
            path = home / 'hooks.json'
            path.write_text(json.dumps(original))
            config = home / 'config.toml'
            config.write_text('notify = ["existing-notifier"]\n')
            install_hooks(home)
            once = path.read_bytes()
            install_hooks(home)
            self.assertEqual(path.read_bytes(), once)
            self.assertEqual(config.read_text(), 'notify = ["existing-notifier"]\n')
            merged = json.loads(path.read_text())
            self.assertEqual(merged['hooks']['Stop'][0], original['hooks']['Stop'][0])
            self.assertEqual(len(merged['hooks']['Stop']), 2)
            self.assertEqual(len(merged['hooks']['UserPromptSubmit']), 1)
            uninstall_hooks(home)
            self.assertEqual(json.loads(path.read_text()), original)

    def test_invalid_existing_json_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            path = home / 'hooks.json'
            path.write_text('{ broken')
            with self.assertRaises(ValueError):
                install_hooks(home)
            self.assertEqual(path.read_text(), '{ broken')


if __name__ == '__main__':
    unittest.main()
