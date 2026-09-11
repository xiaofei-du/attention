"""No per-round prompt while summaries are off; control identity is on demand."""

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from nkc.controls import Controls
from nkc.runtime import handle_hook
from nkc.store import Store


class QuietContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root)

    def prompt(self, turn, provider='codex', session='A', **kwargs):
        return handle_hook('prompt', dict(hook_event_name='UserPromptSubmit',
            session_id=session, turn_id=turn, prompt_id=turn), self.store,
            provider=provider, **kwargs)

    def test_fresh_off_session_has_no_context_or_onboarding_in_both_modes(self):
        self.store.set_summary_preferences(enabled=False)
        for provider in ('codex', 'claude-code'):
            for socket in (None, self.root / 'summary.sock'):
                for turn in ('1', '2'):
                    self.assertEqual(self.prompt(turn, provider, summary_socket=socket), {})
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM onboarding').fetchone()[0], 0)

    def test_disable_invalidates_old_instructions_once_and_enable_restores_next_turn(self):
        for provider in ('codex', 'claude-code'):
            self.assertIn('additionalContext', self.prompt('1', provider)['hookSpecificOutput'])
        Controls(self.store).set_summary_preferences(enabled=False)
        for provider in ('codex', 'claude-code'):
            message = self.prompt('2', provider)['hookSpecificOutput']['additionalContext']
            self.assertIn('supersedes', message)
            self.assertNotIn('--token', message)
            self.assertLess(len(message), 500)
            self.assertEqual(self.prompt('2', provider), {})
            self.store = Store(self.root)  # Survives a process/runtime restart.
            self.assertEqual(self.prompt('3', provider), {})
        Controls(self.store).set_summary_preferences(enabled=True)
        self.assertIn('summary --token', self.prompt('4')['hookSpecificOutput']['additionalContext'])
        Controls(self.store).set_summary_preferences(enabled=False)
        self.assertIn('supersedes', self.prompt('5')['hookSpecificOutput']['additionalContext'])
        self.assertEqual(self.prompt('6'), {})
        # The other provider never received a new enabled instruction.
        self.assertEqual(self.prompt('5', 'claude-code'), {})

    def test_upgrade_invalidates_existing_sessions_but_not_new_ones(self):
        self.store.begin_turn('codex', 'old', '1')
        self.store.set_summary_preferences(enabled=False)
        # Reproduce a pre-upgrade database with old turns but no new receipt table.
        with self.store.db() as db:
            db.execute('DROP TABLE IF EXISTS summary_context')
        self.store = Store(self.root)
        self.assertIn('supersedes', self.prompt('2', session='old')['hookSpecificOutput']['additionalContext'])
        self.assertEqual(self.prompt('3', session='old'), {})
        self.assertEqual(self.prompt('1', session='new'), {})

    def test_duplicate_disabled_prompt_claims_only_one_revocation(self):
        self.prompt('1')
        self.store.set_summary_preferences(enabled=False)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.prompt('2'), range(8)))
        self.assertEqual(sum(bool(result) for result in results), 1)

    def test_valid_off_prompt_still_warms_without_speech_or_context(self):
        self.store.set_summary_preferences(enabled=False)
        received = []
        result = self.prompt('1', warmup=lambda store, provider, session:
                             received.append((provider, session)))
        self.assertEqual(result, {})
        self.assertEqual(received, [('codex', 'A')])
        self.assertEqual(self.store.jobs(), [])



if __name__ == "__main__":
    unittest.main()
