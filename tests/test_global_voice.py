import json
import shlex
import sqlite3
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from nkc.install import PROJECT, PYTHON
from nkc.runtime import handle_hook, run_worker
from nkc.store import Store


class GlobalVoiceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = Store(self.root / 'queue')

    def cli(self, command, payload=None, success=True):
        process = subprocess.run([PYTHON, str(PROJECT / 'run.py'), '--state-dir', str(self.store.root), command],
                                 input=json.dumps(payload) if payload is not None else '', text=True,
                                 capture_output=True, timeout=15)
        if success:
            self.assertEqual(process.returncode, 0, process.stderr)
        else:
            self.assertNotEqual(process.returncode, 0)
        return process.stdout

    def hook(self, action, provider='codex', session='A', turn='one', **fields):
        event = dict(session_id=session, turn_id=turn, prompt_id=turn,
                     hook_event_name='UserPromptSubmit' if action == 'prompt' else 'Stop')
        event.update(fields)
        return handle_hook(action, event, self.store, provider=provider,
                           start_worker=lambda root: self.fail('A globally disabled Stop cannot start a worker'))

    def test_cli_toggles_shared_preference_and_rejects_non_boolean_or_extra_fields(self):
        for enabled in (False, True):
            self.assertEqual(json.loads(self.cli('global-voice', {'enabled': enabled})),
                             {'global_voice_enabled': enabled})
            self.assertEqual(Store(self.store.root).settings()['global_voice_enabled'], enabled)
        for payload in ({'enabled': 1}, {'enabled': 'false'}, {'enabled': False, 'extra': True}, []):
            self.cli('global-voice', payload, success=False)
            self.assertTrue(self.store.settings()['global_voice_enabled'])

    def test_off_cancels_current_and_pending_for_both_providers_and_clears_staged_summaries(self):
        tokens = []
        for provider in ('codex', 'claude-code'):
            token = self.store.begin_turn(provider, 'A', 'one')
            tokens.append(token)
            self.store.stage_summary(token, {'why': 'Queue test.', 'done': 'Old result.', 'next': ''})
            self.store.enqueue(provider, 'A', 'one', 'Old result.', delay=0)
        self.assertIsNotNone(self.store.claim())
        self.store.set_global_enabled(False)
        self.assertEqual([j['status'] for j in self.store.jobs()], ['cancelled', 'cancelled'])
        self.assertIsNone(self.store.claim())
        for provider, token in zip(('codex', 'claude-code'), tokens):
            self.assertIsNone(self.store.summary_for_turn(provider, 'A', 'one')['body'])
            with self.assertRaisesRegex(ValueError, 'Global'):
                self.store.stage_summary(token, {'why': 'Queue test.', 'done': 'Too late.', 'next': ''})
        self.assertFalse(Store(self.store.root).settings()['global_voice_enabled'])

    def test_completed_while_off_never_accumulates_pending_audio_or_replays_after_enable(self):
        self.store.set_global_enabled(False)
        for provider in ('codex', 'claude-code'):
            self.hook('prompt', provider=provider)
            self.hook('stop', provider=provider, last_assistant_message='Private result from muted time.')
        self.assertTrue(all(j['status'] == 'cancelled' and j['body'] == '' for j in self.store.jobs()))
        self.store.set_global_enabled(True)
        for provider in ('codex', 'claude-code'):
            self.hook('stop', provider=provider, last_assistant_message='Duplicate delayed result.')
        heard = []
        run_worker(self.store, play=lambda text, settings, stopped: heard.append(text) or True)
        self.assertEqual(heard, [])
        # A genuinely new round is still eligible.
        self.store.begin_turn('codex', 'A', 'two')
        self.store.enqueue('codex', 'A', 'two', 'Fresh result.', delay=0)
        run_worker(self.store, play=lambda text, settings, stopped: heard.append(text) or True)
        self.assertEqual(heard, ['hey boss Fresh result.'])

    def test_session_enable_cannot_bypass_global_off_and_preferences_survive(self):
        token = self.store.begin_turn('codex', 'A', 'one')
        other = self.store.begin_turn('claude-code', 'B', 'one')
        self.store.set_session_enabled(other, False)
        self.store.set_start('你好美女')
        self.store.set_announce_session_name(True)
        self.store.set_global_enabled(False)
        self.store.set_session_enabled(token, True)
        self.assertFalse(self.store.settings()['global_voice_enabled'])
        self.assertIsNone(self.store.enqueue('codex', 'A', 'one', 'Must not play.', delay=0))
        self.store.set_global_enabled(True)
        self.assertTrue(self.store.session_enabled('codex', 'A'))
        self.assertFalse(self.store.session_enabled('claude-code', 'B'))
        self.assertTrue(self.store.settings()['announce_session_name'])
        self.assertEqual(self.store.settings()['start'], '你好美女')
        for provider, session in [('codex', 'A'), ('claude-code', 'B')]:
            self.store.begin_turn(provider, session, 'two')
            self.store.enqueue(provider, session, 'two', session + ' result.', delay=0)
        heard = []
        run_worker(self.store, play=lambda text, settings, stopped: heard.append(text) or True)
        self.assertEqual(heard, ['你好美女 A result.'])

    def test_quick_off_on_cancels_active_playback_permanently_and_preserves_later_new_results(self):
        for session in ('A', 'B'):
            self.store.enqueue('codex', session, 'one', session + '.', delay=0)
        heard = []
        def sink(text, settings, stopped):
            heard.append(text)
            self.store.set_global_enabled(False)
            self.store.set_global_enabled(True)
            self.assertTrue(stopped(), 'Re-enable cannot revive a cancelled playback')
            return True  # Even a late success acknowledgement must not resurrect it.
        run_worker(self.store, play=sink)
        self.assertEqual(heard, ['hey boss A.'])
        self.assertEqual([j['status'] for j in self.store.jobs()], ['cancelled', 'cancelled'])
        self.store.enqueue('codex', 'B', 'two', 'Fresh.', delay=0)
        run_worker(self.store, play=lambda text, settings, stopped: heard.append(text) or True)
        self.assertEqual(heard[-1], 'hey boss Fresh.')

    def test_global_off_clears_backlog_and_on_accepts_only_new_notifications(self):
        self.store.enqueue('codex', 'A', 'one', 'Old.', delay=0)
        self.store.set_global_enabled(False)
        self.store.set_global_enabled(True)
        self.store.enqueue('codex', 'A', 'two', 'New.', delay=0)
        heard = []
        sink = lambda text, settings, stopped: heard.append(text) or True
        run_worker(self.store, play=sink)
        self.assertEqual(heard, ['hey boss New.'])

    def test_hook_controls_remain_available_while_both_global_and_session_are_disabled(self):
        self.store.set_global_enabled(False)
        for provider in ('codex', 'claude-code'):
            token = self.store.begin_turn(provider, 'A', 'one')
            self.store.set_session_enabled(token, False)
            result = self.hook('prompt', provider=provider)
            context = result['hookSpecificOutput']['additionalContext']
            self.assertIn('Global speech is currently disabled', context)
            self.assertIn('this session are currently disabled', context)
            self.assertNotIn('{{', context)
            command = next(line for line in context.splitlines() if line.endswith(' global-voice'))
            process = subprocess.run(shlex.split(command), input='{"enabled":true}', text=True,
                                     capture_output=True, timeout=15)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertTrue(self.store.settings()['global_voice_enabled'])
            self.assertFalse(self.store.session_enabled(provider, 'A'))
            self.store.set_global_enabled(False)

    def test_existing_active_installation_migrates_enabled_with_pending_queue(self):
        root = self.root / 'old'
        root.mkdir()
        with sqlite3.connect(str(root / 'queue.sqlite3')) as db:
            db.executescript("CREATE TABLE settings(id INTEGER PRIMARY KEY,paused INTEGER,name TEXT,voice TEXT,rate INTEGER);"
                             "INSERT INTO settings VALUES(1,0,'sunshine','Meijia',180);")
        store = Store(root)
        self.assertTrue(store.settings()['global_voice_enabled'])
        self.assertNotIn('paused', store.settings())
        self.assertIsNotNone(store.enqueue('codex', 'A', 'one', 'Old notification.', delay=0))
        self.assertEqual(Store(root).jobs()[0]['status'], 'pending')

    def test_concurrent_enqueue_and_global_off_leave_nothing_playable(self):
        started = threading.Event()
        errors = []
        def enqueue():
            try:
                other = Store(self.store.root)
                started.set()
                for i in range(30):
                    other.enqueue('codex', 'A', str(i), 'Result.', delay=0)
            except Exception as error:
                errors.append(error)
        thread = threading.Thread(target=enqueue)
        thread.start()
        try:
            self.assertTrue(started.wait(5))
            self.store.set_global_enabled(False)
        finally:
            thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(all(j['status'] == 'cancelled' for j in self.store.jobs()))
        self.store.set_global_enabled(True)
        self.assertIsNone(self.store.claim())

    def test_claude_background_wait_while_off_does_not_discard_later_real_completion(self):
        self.hook('prompt', provider='claude-code')
        self.store.set_global_enabled(False)
        self.hook('stop', provider='claude-code', last_assistant_message='Still waiting.',
                  background_tasks=[{'id': 'reviewer', 'status': 'running'}])
        self.store.set_global_enabled(True)
        self.assertIsNotNone(self.store.enqueue('claude-code', 'A', 'one', 'Now finished.', delay=0))
        heard = []
        run_worker(self.store, play=lambda text, settings, stopped: heard.append(text) or True)
        self.assertEqual(heard, ['hey boss Now finished.'])


if __name__ == '__main__':
    unittest.main()
