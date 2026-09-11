"""Control changes use isolated durable state; never clear the user's queue."""

import tempfile
import threading
import unittest
from pathlib import Path

from nkc.store import Store


class ControlStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name))

    def job(self, provider, session, turn='one'):
        token = self.store.begin_turn(provider, session, turn)
        job = self.store.enqueue(provider, session, turn, 'A result.', delay=0)
        return token, job

    def test_clear_cancels_only_pending_and_preserves_receipts_staged_and_settings(self):
        _, active = self.job('codex', 'speaking')
        self.assertEqual(self.store.claim()['id'], active)
        _, a = self.job('codex', 'A')
        _, b = self.job('claude-code', 'B')
        token = self.store.begin_turn('codex', 'staged', 'one')
        self.store.stage_summary(token, {'why': 'We are testing notifications.',
            'done': 'This summary is not queued yet.', 'next': ''})
        original = self.store.settings()
        self.assertEqual(self.store.clear_queue(), 2)
        self.assertEqual(self.store.clear_queue(), 0)
        self.assertEqual({j['id']: j['status'] for j in self.store.jobs()},
                         {active: 'speaking', a: 'cancelled', b: 'cancelled'})
        self.assertFalse(self.store.playback_cancelled(active))
        self.assertEqual(self.store.settings(), original)
        self.assertIsNotNone(self.store.summary_for_turn('codex', 'staged', 'one')['body'])
        self.assertIsNone(self.store.enqueue('codex', 'A', 'one', 'Duplicate stop.', delay=0))
        self.store.finish(active, 'spoken')
        _, new = self.job('claude-code', 'new')
        self.assertEqual(self.store.claim()['id'], new)

    def test_clear_racing_claim_never_cancels_claimed_job(self):
        for i in range(12):
            self.job('codex', str(i))
        barrier = threading.Barrier(2)
        claimed = []
        errors = []
        def claim():
            try:
                barrier.wait()
                claimed.append(self.store.claim())
            except Exception as error:
                errors.append(error)
        thread = threading.Thread(target=claim)
        thread.start()
        barrier.wait()
        count = self.store.clear_queue()
        thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        active = [job for job in claimed if job is not None]
        self.assertEqual(count + len(active), 12)
        for job in active:
            self.assertFalse(self.store.playback_cancelled(job['id']))

    def test_summary_preferences_patch_persists_and_invalid_update_is_atomic(self):
        self.assertEqual(self.store.summary_preferences(), {'enabled': True, 'target_seconds': 30, 'tone': 'conversational', 'focus': 'balanced'})
        self.store.set_summary_preferences(target_seconds=20, tone='calm', focus='context')
        self.store.set_summary_preferences(target_seconds=45)
        saved = {'enabled': True, 'target_seconds': 45, 'tone': 'calm', 'focus': 'context'}
        self.assertEqual(Store(self.store.root).summary_preferences(), saved)
        for invalid in (True, 0, 91, '30', 20.5):
            with self.assertRaises(ValueError):
                self.store.set_summary_preferences(target_seconds=invalid, tone='upbeat')
            self.assertEqual(self.store.summary_preferences(), saved)
        with self.assertRaises(ValueError):
            self.store.set_summary_preferences(target_seconds=10, tone='unrecognized')
        self.assertEqual(self.store.summary_preferences(), saved)
        self.store.set_summary_preferences(tone='conversational', focus='balanced')
        self.assertEqual(self.store.summary_preferences(),
                         {'enabled': True, 'target_seconds': 45, 'tone': 'conversational', 'focus': 'balanced'})

    def test_starter_update_validates_all_fields_before_saving(self):
        self.store.set_starter_options(opening={'type': 'text', 'text': '你好美女'}, announce_session_name=True)
        saved = self.store.settings()
        for opening, announce in [({'type': 'custom', 'path': '/does-not-exist.wav'}, False),
                                  ({'type': 'text', 'text': 'new'}, 'false'),
                                  ({'type': 'none', 'text': 'extra'}, False)]:
            with self.assertRaises(ValueError):
                self.store.set_starter_options(opening=opening, announce_session_name=announce)
            self.assertEqual(self.store.settings(), saved)
        self.store.set_starter_options(announce_session_name=False)
        self.assertEqual(self.store.settings()['start'], '你好美女')
        self.store.set_starter_options(opening={'type': 'none'})
        self.assertEqual(self.store.settings()['start'], '')
        self.assertIsNone(self.store.settings()['start_audio'])

    def test_voice_patch_is_atomic_and_does_not_reset_unmentioned_options(self):
        self.store.set_voice_preferences(gender='male', rate=200)
        saved = self.store.settings()
        for patch in ({'gender': 'female', 'rate': False}, {'gender': 'female', 'voice_mode': 'bad'},
                      {'gender': 'female', 'voice': ''}):
            with self.assertRaises(ValueError):
                self.store.set_voice_preferences(**patch)
            self.assertEqual(self.store.settings(), saved)
        self.store.set_voice_preferences(english_voice='Daniel')
        after = self.store.settings()
        self.assertEqual(after, dict(saved, english_voice='Daniel'))

    def test_status_token_cannot_leak_other_tokens_or_use_expired_identity(self):
        token = self.store.begin_turn('codex', 'A', 'one')
        other = self.store.begin_turn('claude-code', 'A', 'one')
        self.store.set_session_enabled(other, False)
        self.assertEqual(self.store.session_for_token(token),
                         {'provider': 'codex', 'session_id': 'A', 'enabled': True})
        self.store.begin_turn('codex', 'A', 'two')
        for invalid in (token, 'unknown'):
            with self.assertRaises(ValueError):
                self.store.session_for_token(invalid)
