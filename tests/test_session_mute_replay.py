"""Muted completions cannot reappear; all playback uses a silent sink."""

import tempfile
import unittest
from pathlib import Path

from nkc.runtime import handle_hook, run_worker
from nkc.store import Store


class SessionMuteReplayTests(unittest.TestCase):
    def stop(self, store, provider, turn='one', **fields):
        event = dict(hook_event_name='Stop', session_id='A', turn_id=turn,
                     prompt_id=turn, last_assistant_message='Finished while muted.')
        event.update(fields)
        return handle_hook('stop', event, store, provider=provider, start_worker=lambda root: None)

    def test_muted_stop_cannot_replay_after_same_turn_reenable_and_restart(self):
        for provider in ('codex', 'claude-code'):
            for summaries in (True, False):
                with self.subTest(provider=provider, summaries=summaries), tempfile.TemporaryDirectory() as root:
                    store = Store(Path(root))
                    store.set_summary_preferences(enabled=summaries)
                    token = store.begin_turn(provider, 'A', 'one')
                    store.set_session_enabled(token, False)
                    self.assertEqual(self.stop(store, provider), {})
                    self.assertEqual([(j['status'], j['body']) for j in store.jobs()], [('cancelled', '')])

                    # Reopening state must preserve the receipt, even before a
                    # new prompt invalidates the original turn's control token.
                    store = Store(Path(root))
                    store.set_session_enabled(token, True)
                    for _ in range(2):
                        self.stop(store, provider)
                    heard = []
                    sink = lambda text, settings, stopped: heard.append(text) or True
                    run_worker(store, play=sink)
                    self.assertEqual(heard, [])
                    self.assertEqual([(j['status'], j['body']) for j in store.jobs()], [('cancelled', '')])

                    store.begin_turn(provider, 'A', 'two')
                    self.stop(store, provider, turn='two', last_assistant_message='Fresh result.')
                    run_worker(store, play=sink)
                    run_worker(store, play=sink)
                    self.assertEqual(heard, ['hey sunshine Fresh result.' if summaries else 'hey sunshine'])

    def test_enqueue_rechecks_session_mute_and_remembers_rejected_completion(self):
        for provider in ('codex', 'claude-code'):
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as root:
                store = Store(Path(root))
                token = store.begin_turn(provider, 'A', 'one')
                # Another process can mute after the hook's initial check but
                # before its transaction inserts the completed notification.
                self.assertTrue(store.session_enabled(provider, 'A'))
                control = Store(Path(root))
                control.set_session_enabled(token, False)
                self.assertIsNone(store.enqueue(provider, 'A', 'one', 'Do not retain this content.'))
                control.set_session_enabled(token, True)
                self.assertIsNone(store.enqueue(provider, 'A', 'one', 'Delayed duplicate.'))
                self.assertIsNone(store.claim())
                self.assertEqual([(j['status'], j['body'], j['error']) for j in store.jobs()],
                                 [('cancelled', '', 'Session speech disabled')])

    def test_claude_muted_background_wait_does_not_suppress_later_completion(self):
        for scope in ('session', 'global'):
            for summaries in (True, False):
                with self.subTest(scope=scope, summaries=summaries), tempfile.TemporaryDirectory() as root:
                    store = Store(Path(root))
                    store.set_summary_preferences(enabled=summaries)
                    token = store.begin_turn('claude-code', 'A', 'one')
                    toggle = (lambda enabled: store.set_session_enabled(token, enabled)
                              ) if scope == 'session' else store.set_global_enabled
                    toggle(False)
                    self.stop(store, 'claude-code', background_tasks=[{'id': 'review', 'status': 'running'}])
                    self.assertEqual(store.jobs(), [])
                    toggle(True)
                    self.stop(store, 'claude-code', last_assistant_message='Background work finished.')
                    heard = []
                    run_worker(store, play=lambda text, settings, stopped: heard.append(text) or True)
                    self.assertEqual(heard, ['hey sunshine Background work finished.' if summaries else 'hey sunshine'])

    def test_reenable_before_any_completion_keeps_current_turn_eligible(self):
        for provider in ('codex', 'claude-code'):
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as root:
                store = Store(Path(root))
                token = store.begin_turn(provider, 'A', 'one')
                store.set_session_enabled(token, False)
                store.set_session_enabled(token, True)
                self.stop(store, provider, last_assistant_message='Finished after reenable.')
                heard = []
                run_worker(store, play=lambda text, settings, stopped: heard.append(text) or True)
                self.assertEqual(heard, ['hey sunshine Finished after reenable.'])


if __name__ == '__main__':
    unittest.main()
