import json
import sqlite3
import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

from nkc.audio import speak
from nkc.controls import Controls
from nkc.store import Store
from nkc.runtime import handle_hook, run_worker
from nkc.audio import MediaDuckingWarning


class OptionalDuckingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.log = self.root / 'calls.jsonl'

    def player(self, failure=0):
        path = self.root / 'fake-player'
        path.write_text(f'''#!{sys.executable}
import json, sys
from pathlib import Path
with Path({str(self.log)!r}).open('a') as f:
    f.write(json.dumps(sys.argv[1:]) + '\\n')
sys.exit({failure} if '--duck' in sys.argv else 0)
''')
        path.chmod(0o700)
        return path

    def play(self, settings, failure=0, cancelled=lambda: False):
        def render(text, settings, output, *args, **kwargs):
            output.write_bytes(b'harmless fake audio')
            return True
        with patch('nkc.audio.render_speech', side_effect=render) as renderer:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter('always')
                result = speak('Private update.', settings, cancelled, player=self.player(failure))
            self.assertEqual(renderer.call_count, 1)
        calls = [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []
        return result, calls, caught

    def test_fresh_install_uses_plain_playback_without_audio_capture(self):
        store = Store(self.root)
        result, calls, caught = self.play(store.settings())
        self.assertTrue(result)
        self.assertEqual(len(calls), 1)
        self.assertNotIn('--duck', calls[0])
        self.assertFalse(caught)
        self.assertFalse(store.settings()['duck_media'])

    def test_explicit_opt_in_uses_ducking(self):
        store = Store(self.root)
        with patch('nkc.controls.voice_inventory', side_effect=AssertionError('No voice discovery needed')):
            result = Controls(store).set_voice_preferences(duck_media=True)
        self.assertTrue(result['voice_preferences']['duck_media'])
        result, calls, _ = self.play(store.settings())
        self.assertTrue(result)
        self.assertEqual(calls[0][0], '--duck')

    def test_duck_start_failure_falls_back_to_same_audio_once_and_warns(self):
        result, calls, caught = self.play({'duck_media': True}, failure=75)
        self.assertTrue(result)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], ['--duck', calls[1][0]])
        self.assertEqual(len(caught), 1)
        self.assertIn('ordinary playback', str(caught[0].message))

    def test_failure_after_playback_started_must_not_replay(self):
        with self.assertRaises(RuntimeError):
            self.play({'duck_media': True}, failure=1)
        self.assertEqual(len(self.log.read_text().splitlines()), 1)

    def test_cancellation_never_starts_plain_fallback(self):
        result, calls, _ = self.play({'duck_media': True}, failure=75, cancelled=lambda: True)
        self.assertFalse(result)
        self.assertEqual(calls, [])

    def test_existing_install_preserves_ducking_and_global_mute(self):
        with sqlite3.connect(self.root / 'queue.sqlite3') as db:
            db.executescript("CREATE TABLE settings(id INTEGER PRIMARY KEY, name TEXT,voice TEXT,rate INTEGER,"
                             "global_voice_enabled INTEGER); INSERT INTO settings VALUES(1,'sunshine','Meijia',180,0);")
        store = Store(self.root)
        self.assertTrue(store.settings()['duck_media'])
        self.assertFalse(store.global_enabled())
        store.set_voice_preferences(duck_media=False)
        self.assertFalse(Store(self.root).settings()['duck_media'])
        self.assertFalse(Store(self.root).global_enabled())

    def test_invalid_permission_preference_is_rejected_without_changing_other_fields(self):
        store = Store(self.root)
        before = store.settings()
        with self.assertRaises(ValueError):
            store.set_voice_preferences(duck_media='false', rate=210)
        self.assertEqual(store.settings(), before)

    def test_ducking_notice_reaches_original_session_without_voice_download_advice(self):
        store = Store(self.root)
        store.enqueue('codex', 'A', '1', 'Done.')
        def play(*args):
            warnings.warn('Media ducking unavailable; ordinary playback continued.', MediaDuckingWarning)
            return True
        notices = []
        run_worker(store, play=play, notify=notices.append)
        self.assertEqual(len(notices), 1)
        self.assertEqual(store.jobs()[0]['status'], 'spoken')
        event = {'hook_event_name': 'UserPromptSubmit', 'session_id': 'A', 'turn_id': '2'}
        context = handle_hook('prompt', event, store)['hookSpecificOutput']['additionalContext']
        self.assertIn('Media ducking unavailable; ordinary playback continued.', context)
        self.assertNotIn('explain the missing voice', context)
        again = handle_hook('prompt', event, store)['hookSpecificOutput']['additionalContext']
        self.assertNotIn('Media ducking unavailable; ordinary playback continued.', again)
