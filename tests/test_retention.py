import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from nkc.store import Store


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root)

    def staged_job(self, session='A'):
        token = self.store.begin_turn('codex', session, '1')
        self.store.stage_summary(token, {'why': 'Update.', 'next': '', 'done': 'Confidential customer update.'})
        job = self.store.enqueue('codex', session, '1', 'Confidential customer update.')
        return token, job

    def test_enqueue_consumes_staged_copy_and_terminal_states_erase_body(self):
        for state in ('spoken', 'failed', 'skipped', 'uncertain', 'cancelled'):
            with self.subTest(state=state):
                token, job = self.staged_job(state)
                self.assertIsNone(self.store.summary_for_turn('codex', state, '1')['body'])
                self.assertEqual(self.store.claim()['id'], job)
                self.store.finish(job, state)
                self.assertEqual(self.store.jobs()[-1]['body'], '')
                self.store.stage_summary(token, {'why': 'Update.', 'next': '', 'done': 'Late duplicate summary.'})
                self.store.enqueue('codex', state, '1', 'Late duplicate summary.')
                self.assertIsNone(self.store.claim())
                self.assertEqual(self.store.jobs()[-1]['body'], '')
                self.assertIsNone(self.store.summary_for_turn('codex', state, '1')['body'])

    def test_clear_queue_session_disable_global_disable_and_crash_erase_bodies(self):
        for action in ('clear', 'session', 'global', 'crash'):
            with self.subTest(action=action):
                self.store.set_global_enabled(True)
                token, job = self.staged_job(action)
                if action == 'clear':
                    self.store.clear_queue()
                elif action == 'session':
                    self.store.set_session_enabled(token, False)
                elif action == 'global':
                    self.store.set_global_enabled(False)
                else:
                    self.store.claim()
                    self.store.recover_playback()
                self.assertEqual(self.store.jobs()[-1]['body'], '')

    def test_stale_pending_and_orphan_staged_summaries_expire_on_next_use(self):
        self.staged_job()
        token = self.store.begin_turn('claude-code', 'orphan', '1')
        self.store.stage_summary(token, {'why': 'Update.', 'next': '', 'done': 'Unfinished summary.'})
        with patch('nkc.store.time.time', return_value=time.time() + 25 * 3600):
            reopened = Store(self.root)
            self.assertIsNone(reopened.claim())
            self.assertEqual(reopened.jobs()[0]['body'], '')
            self.assertIsNone(reopened.summary_for_turn('claude-code', 'orphan', '1')['body'])

    def test_old_process_status_updates_also_erase_body(self):
        _, job = self.staged_job()
        with sqlite3.connect(self.root / 'queue.sqlite3') as db:
            db.execute("UPDATE jobs SET status='cancelled' WHERE id=?", (job,))
        self.assertEqual(self.store.jobs()[0]['body'], '')

    def test_legacy_migration_clears_history_and_free_pages_but_preserves_preferences_and_pending(self):
        root = self.root / 'legacy'
        root.mkdir()
        secret = 'OLD_PLAINTEXT_SENTINEL_9de0a66' * 500
        with sqlite3.connect(root / 'queue.sqlite3') as db:
            db.executescript('''
                CREATE TABLE jobs(id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT, session_id TEXT,
                    turn_id TEXT, body TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                    received REAL, ready_after REAL, error TEXT, UNIQUE(provider,session_id,turn_id));
            ''')
            for turn, state, text in [('1', 'spoken', secret), ('2', 'pending', 'Keep until playback')]:
                db.execute('INSERT INTO jobs(provider,session_id,turn_id,body,status,received,ready_after) '
                           'VALUES(?,?,?,?,?,?,0)', ('codex', 'A', turn, text, state, time.time()))
        migrated = Store(root)
        self.assertEqual([j['body'] for j in migrated.jobs()], ['', 'Keep until playback'])
        self.assertNotIn(b'OLD_PLAINTEXT_SENTINEL_9de0a66', (root / 'queue.sqlite3').read_bytes())
        with migrated.db() as db:
            self.assertEqual(db.execute('PRAGMA secure_delete').fetchone()[0], 1)
        migrated.set_global_enabled(False)
        migrated.set_start('My greeting')
        again = Store(root)
        self.assertFalse(again.global_enabled())
        self.assertEqual(again.settings()['start'], 'My greeting')
