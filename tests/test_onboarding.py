"""First-use guidance is bounded, shared, and never changes audio controls."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from nkc.runtime import handle_hook
from nkc.store import Store


WELCOME = 'Attention first-use introduction'


class OnboardingTests(unittest.TestCase):
    def setUp(self):
        # Installed plugins provide a compact launcher. A source checkout's
        # absolute path must not consume this fixture's inline-context budget.
        launcher = patch.dict('os.environ', {'ATTENTION_COMMAND': '/tmp/attention-test/attention'})
        launcher.start()
        self.addCleanup(launcher.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'state'
        self.store = Store(self.root)

    def prompt(self, session='A', provider='codex', turn='1', store=None, **fields):
        event = dict(hook_event_name='UserPromptSubmit', session_id=session,
                     turn_id=turn, prompt_id=turn)
        event.update(fields)
        return handle_hook('prompt', event, store or self.store, provider=provider,
                           start_worker=lambda root: self.fail('Welcome must not start audio'))

    def context(self, **fields):
        return self.prompt(**fields)['hookSpecificOutput']['additionalContext']

    def test_first_prompt_offers_guide_once_across_clients_and_restarts(self):
        self.assertIn(WELCOME, self.context())
        self.assertNotIn(WELCOME, self.context(turn='2'))
        self.assertNotIn(WELCOME, self.context(session='B', provider='claude-code',
                                              store=Store(self.root)))
        self.assertIn(WELCOME, self.context(store=Store(Path(self.temp.name) / 'other-install')))

    def test_parallel_sessions_offer_only_one_introduction(self):
        def prompt(index):
            return self.context(session=str(index), store=Store(self.root),
                                provider='codex' if index % 2 else 'claude-code')
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(prompt, range(12)))
        self.assertEqual(sum(WELCOME in context for context in results), 1)

    def test_introduction_does_not_unmute_change_preferences_or_touch_queue(self):
        self.store.set_start('keep this literal')
        self.store.configure(duck_media=True)
        token = self.store.begin_turn('codex', 'A', 'previous')
        self.store.set_session_enabled(token, False)
        self.store.set_global_enabled(False)
        settings = self.store.settings()
        preferences = self.store.summary_preferences()
        self.assertIn(WELCOME, self.context())
        self.assertEqual(self.store.settings(), settings)
        self.assertEqual(self.store.summary_preferences(), preferences)
        self.assertFalse(self.store.session_enabled('codex', 'A'))
        self.assertEqual(self.store.jobs(), [])

    def test_existing_pending_notification_is_not_replaced_by_welcome(self):
        self.store.enqueue('codex', 'B', '1', 'Existing update.', delay=0)
        jobs = self.store.jobs()
        self.assertIn(WELCOME, self.context())
        self.assertEqual(self.store.jobs(), jobs)

    def test_invalid_and_child_events_do_not_consume_first_use(self):
        self.assertEqual(self.prompt(session=''), {})
        self.assertEqual(self.prompt(provider='claude-code', agent_id='child'), {})
        self.assertEqual(self.prompt(hook_event_name='Stop'), {})
        self.assertIn(WELCOME, self.context())

    def test_oversized_context_defers_welcome_instead_of_truncating_instructions(self):
        template = Path(self.temp.name) / 'templates'
        template.mkdir()
        base = 'x' * 9850
        (template / 'summary-prompt.txt').write_text(base)
        with patch('nkc.runtime.PROJECT', template):
            self.assertEqual(self.context(), base)
        self.assertIn(WELCOME, self.context(turn='2'))

    def test_playback_notices_keep_priority_and_total_context_stays_inline(self):
        self.store.record_voice_notice('codex', 'A', 'Missing voice. ' * 100)
        self.store.record_voice_notice('codex', 'A', 'Ducking unavailable. ' * 100,
                                       category='media_ducking')
        first = self.context()
        self.assertIn('Missing voice.', first)
        self.assertIn('Ducking unavailable.', first)
        self.assertLessEqual(len(first.encode('utf-8')), 10000)
        second = self.context(turn='2')
        self.assertEqual(sum(WELCOME in text for text in (first, second)), 1)
        self.assertLessEqual(len(second.encode('utf-8')), 10000)


if __name__ == '__main__':
    unittest.main()
