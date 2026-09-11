import tempfile
import unittest
import sqlite3
from pathlib import Path

from nkc.store import Store


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root)

    def test_same_turn_is_queued_once_across_two_connections(self):
        one = self.store.enqueue("codex", "A", "1", "甲。", delay=0)
        two = Store(self.root).enqueue("codex", "A", "1", "不同的重複內容。", delay=0)
        self.assertEqual(one, two)
        self.assertEqual([(j['session_id'], j['body']) for j in self.store.jobs()], [("A", "甲。")])

    def test_queue_plays_in_received_order_without_an_extra_resume_step(self):
        self.store.enqueue("codex", "B", "1", "乙。", delay=0)
        self.store.enqueue("codex", "A", "1", "甲。", delay=0)
        first = self.store.claim()
        self.assertEqual(first['session_id'], "B")
        self.store.finish(first['id'], "spoken")
        self.assertEqual(self.store.claim()['session_id'], "A")

    def test_same_native_ids_on_different_platforms_do_not_collide(self):
        self.store.enqueue("codex", "A", "1", "甲。", delay=0)
        self.store.enqueue("claude-code", "A", "1", "乙。", delay=0)
        self.assertEqual(len(self.store.jobs()), 2)

    def test_a_new_turn_keeps_queued_results_but_rejects_late_unqueued_results(self):
        self.store.enqueue("codex", "A", "1", "舊結果。", delay=0)
        self.store.enqueue("codex", "B", "1", "另一個結果。", delay=0)
        self.store.begin_turn("codex", "A", "2")
        self.assertEqual([j['status'] for j in self.store.jobs()], ["pending", "pending"])
        # Preserving accepted jobs does not admit a previously unqueued old Stop.
        self.assertIsNone(self.store.enqueue("codex", "A", "0", "過時。", delay=0))

    def test_debounce_holds_an_early_stop_candidate(self):
        self.store.enqueue("codex", "A", "1", "甲。", delay=60)
        self.assertIsNone(self.store.claim())
        self.assertGreater(self.store.wait_seconds(), 0)

    def test_default_enqueue_is_ready_without_an_artificial_wait(self):
        self.store.enqueue('codex', 'A', '1', 'Done.')
        job = self.store.claim()
        self.assertIsNotNone(job)
        self.assertEqual(job['ready_after'], job['received'])

    def test_crashed_playback_is_not_automatically_repeated(self):
        self.store.enqueue("codex", "A", "1", "甲。", delay=0)
        self.assertIsNotNone(self.store.claim())
        self.store.recover_playback()
        self.assertEqual(self.store.jobs()[0]['status'], "uncertain")
        self.assertIsNone(self.store.claim())

    def test_settings_and_queue_survive_reopening(self):
        self.store.configure(name="sunshine", voice="Meijia", rate=210)
        self.store.enqueue("codex", "A", "1", "甲。", delay=0)
        other = Store(self.root)
        self.assertEqual(other.settings()['name'], "sunshine")
        self.assertEqual(len(other.jobs()), 1)

    def test_session_disable_persists_but_other_and_new_sessions_default_to_enabled(self):
        token = self.store.begin_turn('codex', 'A', '1')
        self.assertTrue(self.store.session_enabled('codex', 'A'))
        self.store.set_session_enabled(token, False)
        other = Store(self.root)
        other.begin_turn('codex', 'A', '2')
        self.assertFalse(other.session_enabled('codex', 'A'))
        self.assertTrue(other.session_enabled('codex', 'B'))
        self.assertTrue(other.session_enabled('claude-code', 'A'))
        self.assertTrue(other.global_enabled(), 'A session toggle must not change the global switch')

    def test_disabling_cancels_only_its_pending_jobs_and_reenable_never_replays_them(self):
        token = self.store.begin_turn('codex', 'A', '1')
        self.store.enqueue('codex', 'A', '1', '舊通知。', delay=0)
        self.store.enqueue('codex', 'B', '1', '另一個任務。', delay=0)
        token = self.store.begin_turn('codex', 'A', '2')
        self.store.enqueue('codex', 'A', '2', '接著完成的通知。', delay=0)
        self.assertEqual([job['status'] for job in self.store.jobs()], ['pending'] * 3)
        self.store.set_session_enabled(token, False)
        self.assertEqual([job['status'] for job in self.store.jobs()], ['cancelled', 'pending', 'cancelled'])
        self.assertIsNone(self.store.enqueue('codex', 'A', '2', '不應加入。', delay=0))
        self.store.set_session_enabled(token, True)
        self.assertEqual(self.store.claim()['session_id'], 'B')
        self.assertEqual(self.store.jobs()[0]['status'], 'cancelled')
        self.store.begin_turn('codex', 'A', '3')
        self.assertIsNotNone(self.store.enqueue('codex', 'A', '3', '新通知。', delay=0))

    def test_expired_token_cannot_toggle_a_session_and_invalid_flag_is_rejected(self):
        token = self.store.begin_turn('codex', 'A', '1')
        with self.assertRaises(ValueError):
            self.store.set_session_enabled(token, 'false')
        self.store.begin_turn('codex', 'A', '2')
        with self.assertRaises(ValueError):
            self.store.set_session_enabled(token, False)
        self.assertTrue(self.store.session_enabled('codex', 'A'))

    def test_disabling_clears_staged_summary_and_rejects_new_staging(self):
        token = self.store.begin_turn('codex', 'A', '1')
        payload = {'why': '語音通知。', 'done': '完成測試。', 'next': ''}
        self.store.stage_summary(token, payload)
        self.store.set_session_enabled(token, False)
        self.assertIsNone(self.store.summary_for_turn('codex', 'A', '1')['body'])
        with self.assertRaises(ValueError):
            self.store.stage_summary(token, payload)

    def test_late_worker_result_cannot_overwrite_session_cancellation(self):
        token = self.store.begin_turn('codex', 'A', '1')
        job_id = self.store.enqueue('codex', 'A', '1', '甲。', delay=0)
        self.assertEqual(self.store.claim()['id'], job_id)
        self.store.set_session_enabled(token, False)
        self.store.finish(job_id, 'spoken')
        self.store.set_session_enabled(token, True)
        with self.assertRaises(ValueError):
            self.store.finish(job_id, 'pending')
        self.assertEqual(self.store.jobs()[0]['status'], 'cancelled')

    def test_old_settings_migrate_without_resetting_user_choices(self):
        root = self.root / 'old-install'
        root.mkdir()
        with sqlite3.connect(str(root / 'queue.sqlite3')) as db:
            db.executescript("CREATE TABLE settings(id INTEGER PRIMARY KEY, paused INTEGER, name TEXT, voice TEXT, rate INTEGER);"
                             "INSERT INTO settings VALUES(1,0,'sunshine','Tingting',210);")
        migrated = Store(root)
        migrated.configure(voice_mode='fixed', english_voice='Daniel')
        self.assertEqual(Store(root).settings(), dict(id=1, name='sunshine',
                         voice='Tingting', rate=210, voice_mode='fixed', english_voice='Daniel',
                         start='Hello, sunshine。', start_audio=None, announce_session_name=False,
                         global_voice_enabled=True, voice_gender='default', duck_media=True))

    def test_custom_start_is_stable_across_turns_restarts_and_other_settings(self):
        self.store.set_start('Hey teammate!')
        self.store.begin_turn('codex', 'A', '1')
        self.store.begin_turn('codex', 'A', '2')
        self.store.configure(voice='Tingting', rate=200)
        self.assertEqual(Store(self.root).settings()['start'], 'Hey teammate!')

    def test_invalid_start_never_overwrites_the_saved_opening(self):
        self.store.set_start('早安。')
        for text in ('[[rate 1000]]', 'x' * 121, '<speak>hi</speak>', 'hi\nthere', 42):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.store.set_start(text)
            self.assertEqual(self.store.settings()['start'], '早安。')

    def test_staged_summary_is_bound_to_one_turn_and_never_starts_playback(self):
        token = self.store.begin_turn('codex', 'A', '1')
        self.assertEqual(token, self.store.begin_turn('codex', 'A', '1'))
        self.store.stage_summary(token, {'why': '你想聽到結果。', 'done': '我完成了。', 'next': ''})
        self.assertEqual(self.store.summary_for_turn('codex', 'A', '1')['body'], '你想聽到結果。我完成了。')
        self.assertIsNone(self.store.summary_for_turn('codex', 'B', '1'))
        self.assertEqual(self.store.jobs(), [])
        self.store.begin_turn('codex', 'A', '2')
        with self.assertRaises(ValueError):
            self.store.stage_summary(token, {'why': '舊輪次。', 'done': '不能重播。', 'next': ''})

    def test_turns_registered_before_upgrade_still_allow_direct_reading(self):
        with self.store.db() as db:
            db.execute("INSERT INTO turns VALUES('codex','old-session','old-turn')")
        self.assertEqual(self.store.summary_for_turn('codex', 'old-session', 'old-turn'),
                         {'token': None, 'body': None})
        self.assertIsNone(self.store.summary_for_turn('codex', 'old-session', 'another-turn'))


if __name__ == '__main__':
    unittest.main()
