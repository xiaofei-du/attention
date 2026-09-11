"""Notification-only mode never consumes the agent's answer or a staged body."""

import aifc
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nkc.audio import render_speech
from nkc.runtime import handle_hook, run_worker
from nkc.store import Store


class SummaryToggleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root)

    def stop(self, provider='codex', session='A', turn='1', **fields):
        event = dict(hook_event_name='Stop', session_id=session,
                     turn_id=turn, prompt_id=turn,
                     last_assistant_message='A long or technical response. ' * 200)
        event.update(fields)
        return handle_hook('stop', event, self.store, provider=provider, start_worker=lambda _: None)

    def test_default_persistence_strict_boolean_and_other_preferences_preserved(self):
        self.assertTrue(self.store.summary_preferences()['enabled'])
        self.store.set_summary_preferences(tone='calm', target_seconds=20)
        original = self.store.settings()
        self.store.set_summary_preferences(enabled=False)
        expected = dict(enabled=False, target_seconds=20, tone='calm', focus='balanced')
        self.assertEqual(Store(self.root).summary_preferences(), expected)
        for value in ('false', 0, 1, None, [], {}):
            with self.assertRaises(ValueError):
                self.store.set_summary_preferences(enabled=value, tone='upbeat')
            self.assertEqual(self.store.summary_preferences(), expected)
        self.assertEqual(self.store.settings(), original)
        self.store.set_summary_preferences(enabled=True)
        self.assertEqual(self.store.summary_preferences(), dict(expected, enabled=True))

    def test_cli_fallback_accepts_the_shared_summary_switch(self):
        runner = Path(__file__).resolve().parents[1] / 'run.py'
        for enabled in (False, True):
            result = subprocess.run([sys.executable, str(runner), '--state-dir', str(self.root),
                                     'set-summary-preferences'], input=json.dumps({'enabled': enabled}),
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['enabled'], enabled)
            self.assertEqual(self.store.summary_preferences()['enabled'], enabled)

    def test_off_prompt_has_no_recurring_context(self):
        self.store.set_summary_preferences(enabled=False)
        for provider in ('codex', 'claude-code'):
            for socket in (None, self.root / 'summary.sock'):
                result = handle_hook('prompt', dict(hook_event_name='UserPromptSubmit', session_id='A',
                              turn_id='1', prompt_id='1'), self.store, provider=provider,
                              summary_socket=socket)
                self.assertEqual(result, {})

    def test_stop_ignores_all_final_content_and_needs_no_summary_submission(self):
        self.store.set_summary_preferences(enabled=False)
        with patch('nkc.runtime.notification_body', side_effect=AssertionError('Must not inspect the reply')):
            for provider in ('codex', 'claude-code'):
                self.stop(provider=provider)
                self.stop(provider=provider)
                self.stop(provider=provider, session='B', last_assistant_message=None)
        self.assertEqual(len(self.store.jobs()), 4)
        self.assertTrue(all(job['body'] == '' for job in self.store.jobs()))
        heard = []
        run_worker(self.store, play=lambda text, settings, cancelled: heard.append(text) or True)
        run_worker(self.store, play=lambda *args: self.fail('No replay'))
        self.assertEqual(heard, ['hey sunshine'] * 4)

    def test_global_and_session_off_still_win_and_claude_waits_for_background_tasks(self):
        self.store.set_summary_preferences(enabled=False)
        token = self.store.begin_turn('codex', 'muted', '1')
        self.store.set_session_enabled(token, False)
        self.stop(session='muted')
        self.stop(provider='claude-code', background_tasks=[{'id':'pending'}])
        self.assertEqual([(j['provider'], j['session_id'], j['status'], j['body']) for j in self.store.jobs()],
                         [('codex', 'muted', 'cancelled', '')])
        self.store.set_global_enabled(False)
        self.stop()
        self.assertFalse(any(j['status']=='pending' for j in self.store.jobs()))
        self.store.set_global_enabled(True)
        self.stop()  # The completion discarded during global off stays discarded.
        self.stop(provider='claude-code', background_tasks=[])
        self.assertEqual([(j['provider'],j['body']) for j in self.store.jobs() if j['status']=='pending'],
                         [('claude-code','')])

    def test_switching_off_clears_queue_erases_staged_and_cancels_inflight_content(self):
        token = self.store.begin_turn('codex', 'staged', '1')
        self.store.stage_summary(token, {'why':'We are testing.', 'done':'A private detail.', 'next':''})
        active = self.store.enqueue('codex', 'active', '1', 'Playing a private detail.')
        pending = self.store.enqueue('claude-code', 'waiting', '1', 'Waiting private detail.')
        self.assertEqual(self.store.claim()['id'], active)
        self.store.set_summary_preferences(enabled=False)
        self.assertTrue(self.store.playback_cancelled(active))
        self.assertIsNone(self.store.summary_for_turn('codex','staged','1')['body'])
        self.assertEqual(self.store.jobs()[1]['body'], '')
        self.assertEqual(self.store.jobs()[1]['status'], 'cancelled')
        with self.assertRaisesRegex(ValueError, 'Summary.*disabled'):
            self.store.stage_summary(token, {'why':'We are testing.', 'done':'Late old agent.', 'next':''})
        self.store.set_summary_preferences(enabled=True)
        heard = []
        run_worker(self.store, play=lambda text, settings, cancelled: heard.append(text) or True)
        self.assertEqual(heard, [])
        self.assertEqual(self.store.jobs()[1]['id'], pending)

    def test_switching_off_clears_even_preexisting_starter_only_jobs(self):
        self.store.enqueue('codex', 'A', '1', '')
        self.store.set_summary_preferences(enabled=False)
        self.assertEqual(self.store.queue_status()['pending'], 0)
        self.stop()
        self.assertEqual(self.store.queue_status()['pending'], 0)
        self.stop(turn='2')
        self.assertEqual(self.store.queue_status()['pending'], 1)

    def test_late_writers_and_stale_enqueue_cannot_restore_bodies_while_off(self):
        token = self.store.begin_turn('codex', 'A', '1')
        self.store.set_summary_preferences(enabled=False)
        self.store.enqueue('codex', 'A', '1', 'A stale caller already parsed this body.')
        with self.store.db() as db:
            db.execute("INSERT INTO jobs(provider,session_id,turn_id,body,received,ready_after) "
                       "VALUES('codex','old-runtime','1','Old runtime body',9999999999,0)")
            db.execute("UPDATE jobs SET body='Late body' WHERE session_id='A'")
        self.assertTrue(all(job['body']=='' for job in self.store.jobs()))
        with self.assertRaises(sqlite3.IntegrityError):
            with self.store.db() as db:
                db.execute('UPDATE turn_summaries SET body=? WHERE token=?', ('Late summary',token))

    def test_no_starter_or_resolvable_name_is_silent_and_keeps_a_receipt(self):
        self.store.set_summary_preferences(enabled=False)
        self.store.set_starter_options(opening={'type':'none'}, announce_session_name=True)
        self.stop()
        with patch('nkc.runtime.resolve_session_name', return_value=''), \
             patch('nkc.runtime.voice_inventory', side_effect=AssertionError('No voice lookup')):
            run_worker(self.store, play=lambda *args: self.fail('No content to play'))
        self.assertEqual(self.store.jobs()[0]['status'], 'skipped')
        self.stop()
        self.assertEqual(len(self.store.jobs()), 1)

    def test_session_name_comes_from_metadata_without_reading_reply(self):
        self.store.set_summary_preferences(enabled=False)
        self.store.set_starter_options(opening={'type':'text','text':'Hi'}, announce_session_name=True)
        self.stop()
        heard=[]
        with patch('nkc.runtime.resolve_session_name', return_value='Test project'):
            run_worker(self.store, play=lambda text,settings,cancelled: heard.append(text) or True)
        self.assertEqual(heard, ['Hi Session: Test project.'])

    def test_disable_racing_reply_parsing_still_enqueues_only_a_starter(self):
        def race(*args, **kwargs):
            self.store.set_summary_preferences(enabled=False)
            raise ValueError('Old mode had no summary')
        with patch('nkc.runtime.notification_body', side_effect=race):
            self.stop()
        self.assertEqual([job['body'] for job in self.store.jobs()], [''])

    def test_audio_only_worker_skips_voice_inventory_and_preserves_ducking(self):
        self.store.set_summary_preferences(enabled=False)
        self.store.configure(duck_media=True)
        with self.store.db() as db:
            db.execute('UPDATE settings SET start_audio=?', ('{"type":"custom","file":"/local/clip.aiff"}',))
        self.stop()
        calls=[]
        def player(body, settings, cancelled, **kwargs):
            calls.append((body, settings['duck_media'], settings['start_audio']['file']))
            return True
        with patch('nkc.runtime.voice_inventory', side_effect=AssertionError('No speech voice is needed')), \
             patch('nkc.runtime.speak', side_effect=player):
            run_worker(self.store)
        self.assertEqual(calls, [('',True,'/local/clip.aiff')])

    def test_audio_only_renders_without_voices_language_detection_or_tts(self):
        audio = self.root/'opening.aiff'
        frames = b'\0\1' * 2205
        with aifc.open(str(audio),'wb') as stream:
            stream.setparams((1,2,22050,0,b'NONE',b'not compressed'))
            stream.writeframes(frames)
        settings=dict(self.store.settings(), start='', start_audio={'file':str(audio),'type':'custom'})
        output=self.root/'notification.aiff'
        with patch('nkc.audio.prepare_voice_inventory', side_effect=AssertionError('No voice discovery')), \
             patch('nkc.audio.notification_speech_segments', side_effect=AssertionError('No language routing')), \
             patch('nkc.audio.run_process', side_effect=AssertionError('No synthesizer')):
            self.assertTrue(render_speech('',settings,output,session_name=''))
        with aifc.open(str(output),'rb') as stream:
            self.assertTrue(stream.readframes(stream.getnframes()).startswith(frames))


if __name__=='__main__':
    unittest.main()
