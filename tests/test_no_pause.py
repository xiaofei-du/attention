import json
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

from nkc.install import PROJECT, PYTHON
from nkc.runtime import handle_hook, run_worker
from nkc.store import Store


class NoPauseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_new_install_has_only_global_and_session_gates(self):
        store = Store(self.root)
        self.assertNotIn('paused', store.settings())
        self.assertTrue(store.global_enabled())
        store.enqueue('codex', 'A', 'one', 'Ready.', delay=0)
        self.assertIsNotNone(store.claim(), 'No extra resume should be required')

    def test_removed_cli_commands_fail_without_changing_settings(self):
        store = Store(self.root)
        before = store.settings()
        for command in ('pause', 'resume'):
            result = subprocess.run([PYTHON, str(PROJECT / 'run.py'), '--state-dir', str(self.root), command],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(store.settings(), before)

    def test_legacy_pause_converts_to_off_and_cancels_backlog_once(self):
        with sqlite3.connect(str(self.root / 'queue.sqlite3')) as db:
            db.executescript("CREATE TABLE settings(id INTEGER PRIMARY KEY,paused INTEGER NOT NULL,name TEXT,voice TEXT,"
                             "rate INTEGER,start TEXT,global_voice_enabled INTEGER);"
                             "INSERT INTO settings VALUES(1,1,'unused','Meijia',190,'你好美女',1);"
                             "CREATE TABLE jobs(id INTEGER PRIMARY KEY,provider TEXT,session_id TEXT,turn_id TEXT,"
                             "body TEXT,status TEXT NOT NULL DEFAULT 'pending',received REAL,ready_after REAL,error TEXT,"
                             "UNIQUE(provider,session_id,turn_id));"
                             "INSERT INTO jobs VALUES(1,'codex','A','one','Old.','pending',0,0,NULL);")
        store = Store(self.root)
        self.assertFalse(store.global_enabled())
        self.assertNotIn('paused', store.settings())
        self.assertEqual(store.jobs()[0]['status'], 'cancelled')
        self.assertEqual(store.settings()['start'], '你好美女')
        token = store.begin_turn('claude-code', 'muted', 'one')
        store.set_session_enabled(token, False)
        store.set_global_enabled(True)
        store = Store(self.root)
        self.assertTrue(store.global_enabled(), 'Migration must not reapply after a later enable')
        self.assertFalse(store.session_enabled('claude-code', 'muted'))
        store.enqueue('codex', 'A', 'two', 'Fresh.', delay=0)
        heard = []
        run_worker(store, play=lambda text, settings, cancelled: heard.append(text) or True)
        self.assertEqual(heard, ['你好美女 Fresh.'])

    def test_legacy_unpaused_preserves_explicit_global_off(self):
        with sqlite3.connect(str(self.root / 'queue.sqlite3')) as db:
            db.executescript("CREATE TABLE settings(id INTEGER PRIMARY KEY,paused INTEGER,name TEXT,voice TEXT,rate INTEGER,"
                             "global_voice_enabled INTEGER);"
                             "INSERT INTO settings VALUES(1,0,'sunshine','Meijia',180,0);")
        store = Store(self.root)
        self.assertFalse(store.global_enabled())
        self.assertNotIn('paused', store.settings())

    def test_prompt_has_no_pause_workflow_and_keeps_existing_controls(self):
        store = Store(self.root)
        for provider in ('codex', 'claude-code'):
            context = handle_hook('prompt', dict(hook_event_name='UserPromptSubmit', session_id='A',
                                  turn_id='one', prompt_id='one'), store, provider=provider)
            text = context['hookSpecificOutput']['additionalContext']
            self.assertNotIn('pause', text.lower())
            self.assertIn(' global-voice', text)
            self.assertIn(' session-voice --token ', text)

    def test_interrupted_playback_without_toggle_never_returns_to_pending(self):
        store = Store(self.root)
        store.enqueue('codex', 'A', 'one', 'Ready.', delay=0)
        run_worker(store, play=lambda text, settings, cancelled: False)
        self.assertEqual(store.jobs()[0]['status'], 'failed')
        self.assertIsNone(store.claim())


if __name__ == '__main__':
    unittest.main()
