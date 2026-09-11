"""Exercise the packaged hook command after the host removes its plugin root."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from nkc.store import Store

BUNDLE = os.environ.get('ATTENTION_TEST_MARKETPLACE')


@unittest.skipUnless(BUNDLE, 'Requires a generated marketplace')
class PackagedHookEntryTests(unittest.TestCase):
    def test_stop_uses_the_exact_retained_runtime_after_cache_removal(self):
        for provider, folder, variable in [('codex', 'plugins', 'PLUGIN_ROOT'),
                                           ('claude-code', 'claude-plugins', 'CLAUDE_PLUGIN_ROOT')]:
            with self.subTest(provider=provider), tempfile.TemporaryDirectory(prefix='attention deleted cache ') as directory:
                root = Path(directory)
                cache = root / "plugin's cache $literal"
                shutil.copytree(Path(BUNDLE) / folder / 'attention', cache)
                hooks = json.loads((cache / 'hooks/hooks.json').read_text())['hooks']
                data = root / 'data'
                store = Store(data / 'state')
                store.set_global_enabled(False)
                store.set_summary_preferences(enabled=False)
                env = dict(os.environ, ATTENTION_DATA_DIR=str(data),
                           CODEX_HOME=str(root / 'empty-codex'), CLAUDE_CONFIG_DIR=str(root / 'empty-claude'))
                env[variable] = str(cache)
                def invoke(event, turn):
                    command = hooks[event][0]['hooks'][0]['command']
                    result = subprocess.run(command, shell=True, executable='/bin/sh', cwd=root, env=env,
                        input=json.dumps({'hook_event_name': event, 'session_id': 'cache-regression',
                                          'turn_id': turn, 'prompt_id': turn,
                                          'last_assistant_message': 'Never speak this fixture.'}),
                        capture_output=True, text=True, timeout=60)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(json.loads(result.stdout), {})
                invoke('UserPromptSubmit', 'one')
                runtimes = list((data / 'r').iterdir())
                self.assertEqual(len(runtimes), 1)
                shutil.rmtree(cache)
                invoke('Stop', 'one')
                with store.db() as db:
                    jobs = [dict(row) for row in db.execute('SELECT body,status FROM jobs')]
                self.assertEqual(jobs, [{'body': '', 'status': 'cancelled'}])
                # Neither altered installed code nor an unrelated newer version
                # may substitute for the payload pinned in the saved command.
                marker = root / 'unexpected-execution'
                malicious = 'from pathlib import Path; Path(' + repr(str(marker)) + ').touch()\n'
                (runtimes[0] / 'launch.py').write_text(malicious)
                alternate = data / 'r' / 'ffffffffffffffff'
                alternate.mkdir()
                (alternate / 'launch.py').write_text(malicious)
                invoke('Stop', 'two')
                self.assertFalse(marker.exists())
                shutil.rmtree(runtimes[0])
                invoke('Stop', 'three')
                self.assertFalse(marker.exists())


if __name__ == '__main__':
    unittest.main()
