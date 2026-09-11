import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run
from nkc import language
from nkc.runtime import handle_hook, run_worker
from nkc.store import Store


class MissingVoiceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = Store(self.root)
        self.store.set_start('')

    def test_missing_language_skips_without_error_then_processes_next_job(self):
        self.store.enqueue('codex', 'A', '1', 'Bonjour.', delay=0)
        self.store.enqueue('claude-code', 'B', '1', 'Done.', delay=0)
        shown = []
        heard = []
        def play(text, settings, cancelled):
            heard.extend(language.speech_segments(text, settings))
            return True
        with patch('nkc.language.installed_voices', return_value={'Samantha': 'en'}), \
                patch('nkc.language.detect_languages', side_effect=lambda texts: ['fr' if t.startswith('Bonjour') else 'en' for t in texts]):
            run_worker(self.store, play=play, notify=shown.append)
        self.assertEqual([j['status'] for j in self.store.jobs()], ['skipped', 'spoken'])
        self.assertIsNone(self.store.jobs()[0]['error'])
        self.assertEqual(heard, [('Samantha', 'Done.')])
        self.assertEqual(len(shown), 1)
        self.assertIn('fr', shown[0])
        self.assertIn('download', shown[0].lower())
        # A desktop banner may be suppressed by macOS; the original session also
        # receives the saved notice on its next prompt, once, without cross-talk.
        def prompt(provider, session, turn):
            key = 'prompt_id' if provider == 'claude-code' else 'turn_id'
            return handle_hook('prompt', {'hook_event_name': 'UserPromptSubmit', 'session_id': session, key: turn},
                               self.store, provider=provider)['hookSpecificOutput']['additionalContext']
        self.assertNotIn('Previous playback notice:', prompt('claude-code', 'A', '2'))
        self.assertIn('Previous playback notice:', prompt('codex', 'A', '2'))
        self.assertNotIn('Previous playback notice:', prompt('codex', 'A', '3'))

    def test_missing_gender_uses_fallback_and_deduplicates_download_reminder(self):
        self.store.set_voice_gender('male')
        for provider, session in [('codex', 'A'), ('claude-code', 'B')]:
            self.store.enqueue(provider, session, '1', '改好了。', delay=0)
        shown, heard = [], []
        def play(text, settings, cancelled):
            heard.extend(language.speech_segments(text, settings))
            return True
        with patch('nkc.language.installed_voices', return_value={'Meijia': 'zh'}), \
                patch('nkc.language.installed_voice_metadata', return_value=[
                    dict(name='Meijia', language='zh', locale='zh_TW', gender='female')]):
            run_worker(self.store, play=play, notify=shown.append)
        self.assertEqual([j['status'] for j in self.store.jobs()], ['spoken', 'spoken'])
        self.assertTrue(all(j['error'] is None for j in self.store.jobs()))
        self.assertEqual(heard, [('Meijia', '改好了。')] * 2)
        self.assertEqual(len(shown), 1)
        self.assertIn('download', shown[0].lower())
        self.assertEqual(Store(self.root).settings()['voice_gender'], 'male')

    def test_native_notification_failure_does_not_fail_or_block_queue(self):
        self.store.enqueue('codex', 'A', '1', 'Bonjour.', delay=0)
        def unavailable(message):
            raise OSError('notifications unavailable')
        with patch('nkc.language.installed_voices', return_value={'Samantha': 'en'}), \
                patch('nkc.language.detect_languages', return_value=['fr']):
            run_worker(self.store, play=lambda t,s,c: language.speech_segments(t,s), notify=unavailable)
        self.assertEqual(self.store.jobs()[0]['status'], 'skipped')
        self.assertIsNone(self.store.jobs()[0]['error'])
        context = handle_hook('prompt', {'hook_event_name': 'UserPromptSubmit', 'session_id': 'A', 'turn_id': '2'},
                              self.store)['hookSpecificOutput']['additionalContext']
        self.assertIn('Previous playback notice:', context)

    def test_actual_player_errors_still_fail(self):
        self.store.enqueue('codex', 'A', '1', 'Done.', delay=0)
        shown = []
        def broken(text, settings, cancelled):
            raise RuntimeError('Audio device disconnected')
        run_worker(self.store, play=broken, notify=shown.append)
        self.assertEqual(self.store.jobs()[0]['status'], 'failed')
        self.assertEqual(self.store.jobs()[0]['error'], 'Audio device disconnected')
        self.assertEqual(shown, [])

    def test_cancellation_wins_over_missing_voice(self):
        self.store.enqueue('codex', 'A', '1', 'Bonjour.', delay=0)
        shown = []
        def play(text, settings, cancelled):
            self.store.set_global_enabled(False)
            return language.speech_segments(text, settings)
        with patch('nkc.language.installed_voices', return_value={'Samantha': 'en'}), \
                patch('nkc.language.detect_languages', return_value=['fr']):
            run_worker(self.store, play=play, notify=shown.append)
        self.assertEqual(self.store.jobs()[0]['status'], 'cancelled')
        self.assertEqual(shown, [])

    def test_missing_fixed_voice_never_reaches_say(self):
        with patch('nkc.language.installed_voices', return_value={'Samantha': 'en'}):
            try:
                language.speech_segments('Done.', {'voice_mode': 'fixed', 'voice': 'Deleted voice'})
            except RuntimeError as error:
                self.assertIn('download', str(error).lower())
            else:
                self.fail('A missing fixed voice must request installation before synthesis')

    def test_cli_no_installed_voices_reports_setup_instead_of_traceback(self):
        argv = ['run.py', '--state-dir', str(self.root), 'list-voices']
        language.installed_voices.cache_clear()
        language.installed_voice_metadata.cache_clear()
        self.addCleanup(language.installed_voices.cache_clear)
        self.addCleanup(language.installed_voice_metadata.cache_clear)
        output = io.StringIO()
        def inventory(args, **kwargs):
            return subprocess.CompletedProcess(args, 0, stdout='' if args[0] == '/usr/bin/say' else '[]', stderr='')
        with patch.object(sys, 'argv', argv), patch('nkc.language.subprocess.run',
                side_effect=inventory), contextlib.redirect_stdout(output):
            run.main()
        result = json.loads(output.getvalue())
        self.assertEqual(result['voices'], [])
        self.assertEqual(result['status'], 'needs_voice_download')
        self.assertIn('download', result['message'].lower())

    def test_report_includes_download_guidance_for_missing_gender(self):
        with patch('nkc.language.installed_voices', return_value={'Meijia': 'zh'}), \
                patch('nkc.language.installed_voice_metadata', return_value=[
                    dict(name='Meijia', language='zh', locale='zh_TW', gender='female')]):
            report = language.voice_report(dict(voice='Meijia', voice_gender='male'))
        self.assertTrue(any('download' in item.lower() for item in report['warnings']))
        self.assertEqual(report['download_help']['settings_path'],
                         'System Settings > Accessibility > Read & Speak > System voice')

    def test_long_setup_notice_keeps_claude_controls_inline(self):
        self.store.set_start('好' * 120)
        self.store.record_voice_notice('claude-code', 'A', '聲音' * 180)
        result = handle_hook('prompt', {'hook_event_name': 'UserPromptSubmit', 'session_id': 'A', 'prompt_id': '1'},
                             self.store, provider='claude-code')['hookSpecificOutput']['additionalContext']
        self.assertIn('Previous playback notice:', result)
        self.assertIn('download', result)
        self.assertIn('set-voice-gender', result)
        self.assertLessEqual(len(result.encode('utf-8')), 10000)

    def test_downloaded_voice_is_discovered_for_future_jobs_without_replay(self):
        self.store.set_voice_gender('male')
        for turn in ['1', '2']:
            self.store.enqueue('codex', 'A', turn, 'Done.', delay=0)
        inventories = iter(['', 'Daniel en_GB # Hello\n'])
        actual_run = language.subprocess.run
        def inventory(args, **kwargs):
            if args[0] == '/usr/bin/say' and args[-1] == '?':
                return subprocess.CompletedProcess(args, 0, stdout=next(inventories), stderr='')
            return actual_run(args, **kwargs)
        heard, shown = [], []
        def play(text, settings, cancelled):
            heard.extend(language.speech_segments(text, settings))
            return True
        with patch('nkc.language.subprocess.run', side_effect=inventory):
            run_worker(self.store, play=play, notify=shown.append)
            run_worker(self.store, play=play, notify=shown.append)
        self.assertEqual([j['status'] for j in self.store.jobs()], ['skipped', 'spoken'])
        self.assertEqual(heard, [('Daniel', 'Done.')])
        self.assertEqual(len(shown), 1)
        language.installed_voices.cache_clear()
        language.installed_voice_metadata.cache_clear()


if __name__ == '__main__':
    unittest.main()
