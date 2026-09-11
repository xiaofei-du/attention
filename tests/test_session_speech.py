import aifc
import tempfile
import warnings
import unittest
from pathlib import Path
from unittest.mock import patch

from nkc import audio, language
from nkc.runtime import run_worker
from nkc.store import Store
from nkc.summary import notification_text


class SessionSpeechTests(unittest.TestCase):
    settings = dict(start='你好美女', start_audio=None, announce_session_name=True,
                    voice='Meijia', english_voice='Samantha', voice_mode='auto',
                    voice_gender='default', rate=180)

    def segments(self, name, body='改好了。', **settings):
        return language.notification_speech_segments(body, dict(self.settings, **settings), name)

    def test_label_is_shortened_without_changing_name_or_body(self):
        self.assertEqual(notification_text('改好了。', self.settings, '語音播報'),
                         '你好美女 Session: 語音播報. 改好了。')

    def test_chinese_opening_does_not_change_english_announcement_voice(self):
        self.assertEqual(self.segments('codex lazy'), [
            ('Meijia', '你好美女 '), ('Samantha', 'Session: codex lazy. '),
            ('Meijia', '改好了。')])

    def test_english_label_and_name_merge_for_continuous_synthesis(self):
        self.assertEqual(self.segments('codex lazy', start=''), [
            ('Samantha', 'Session: codex lazy. '), ('Meijia', '改好了。')])

    def test_announcement_is_detected_independently_of_body(self):
        with patch('nkc.language.installed_voices', return_value={'Samantha': 'en', 'Kyoko': 'ja'}), \
                patch('nkc.language.detect_languages', side_effect=[['ja'], ['en']]) as detector:
            self.assertEqual(self.segments('音声通知', body='All done.', start=''), [
                ('Kyoko', 'Session: 音声通知. '), ('Samantha', 'All done.')])
        self.assertEqual([call.args[0] for call in detector.call_args_list],
                         [['Session: 音声通知. '], ['All done.']])

    def test_fixed_voice_setting_applies_to_announcement_and_body(self):
        self.assertEqual(self.segments('語音播報', start='', body='All done.',
                                       voice_mode='fixed', voice='Samantha'), [
            ('Samantha', 'Session: 語音播報. All done.')])

    def test_explicit_english_voice_still_applies(self):
        self.assertEqual(self.segments('codex lazy', start='', english_voice='Daniel'), [
            ('Daniel', 'Session: codex lazy. '), ('Meijia', '改好了。')])

    def test_label_respects_male_voice_preference(self):
        with patch('nkc.language.installed_voices', return_value={'Samantha': 'en', 'Daniel': 'en'}), \
                patch('nkc.language.installed_voice_metadata', return_value=[
                    dict(name='Samantha', language='en', gender='female'),
                    dict(name='Daniel', language='en', gender='male')]), \
                patch('nkc.language.detect_languages', return_value=['en']):
            self.assertEqual(self.segments('codex lazy', body='Done.', start='', voice_gender='male'),
                             [('Daniel', 'Session: codex lazy. Done.')])

    def test_audio_opening_replaces_text_and_missing_or_disabled_name_skips_label(self):
        self.assertEqual(self.segments('語音播報', start_audio={'type': 'custom'}), [
            ('Meijia', 'Session: 語音播報. 改好了。')])
        for name, extra in [('', {}), ('[[slnc 1000]]', {}),
                            ('語音播報', dict(announce_session_name=False))]:
            with self.subTest(name=name, extra=extra):
                settings = dict(self.settings, **extra)
                self.assertEqual(language.notification_speech_segments('改好了。', settings, name),
                                 language.speech_segments(notification_text('改好了。', settings, name), settings))

    def test_chinese_announcement_requires_no_english_voice_or_download_notice(self):
        with patch('nkc.language.installed_voices', return_value={'Meijia': 'zh'}), \
                warnings.catch_warnings(record=True) as notices:
            warnings.simplefilter('always')
            self.assertEqual(self.segments('語音播報', start=''),
                             [('Meijia', 'Session: 語音播報. 改好了。')])
        self.assertEqual(notices, [])

    def test_absent_configured_english_voice_uses_another_installed_english_voice(self):
        with patch('nkc.language.installed_voices', return_value={'Daniel': 'en', 'Meijia': 'zh'}):
            self.assertEqual(self.segments('codex lazy', start=''), [
                ('Daniel', 'Session: codex lazy. '), ('Meijia', '改好了。')])

    def test_missing_title_language_skips_whole_header_instead_of_labelling_body_as_title(self):
        with patch('nkc.language.installed_voices', return_value={'Samantha': 'en'}), \
                patch('nkc.language.detect_languages', side_effect=[['ja'], ['en']]):
            with self.assertWarnsRegex(language.VoiceDownloadWarning, 'session name.*download'):
                self.assertEqual(self.segments('音声通知', body='All done.', start=''),
                                 [('Samantha', 'All done.')])

    def test_missing_optional_english_opening_does_not_block_chinese_content(self):
        with patch('nkc.language.installed_voices', return_value={'Meijia': 'zh'}):
            with self.assertWarns(language.VoiceDownloadWarning):
                self.assertEqual(self.segments('語音播報', start='hey sunshine'),
                                 [('Meijia', 'Session: 語音播報. 改好了。')])

    def test_missing_announcement_voice_warns_once_without_failing_queue_or_changing_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'state')
            store.set_start('')
            store.set_announce_session_name(True)
            before = store.settings()
            for turn in ('1', '2'):
                store.enqueue('codex', 'A', turn, '改好了。', delay=0)
            heard, shown = [], []
            def speak(text, settings, cancelled, **kwargs):
                heard.extend(language.notification_speech_segments(text, settings, kwargs['session_name']))
                return True
            with patch('nkc.runtime.resolve_session_name', return_value='codex lazy'), \
                    patch('nkc.runtime.speak', side_effect=speak), \
                    patch('nkc.language.installed_voices', return_value={'Meijia': 'zh'}):
                run_worker(store, notify=shown.append)
            self.assertEqual([job['status'] for job in store.jobs()], ['spoken', 'spoken'])
            self.assertEqual(heard, [('Meijia', '改好了。')] * 2)
            self.assertEqual(len(shown), 1)
            self.assertIn('download', shown[0])
            self.assertEqual(store.settings(), before)

    def test_worker_carries_session_name_to_real_render_path_for_both_providers(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'state')
            store.set_start('')
            store.set_announce_session_name(True)
            for provider in ('codex', 'claude-code'):
                store.enqueue(provider, 'A', '1', '改好了。', delay=0)
            rendered = []
            def render(text, settings, output, *args, **kwargs):
                # The real speak path must preserve the title separately until synthesis.
                name = kwargs.get('session_name')
                self.assertEqual(name, '語音播報')
                self.assertEqual(text, '改好了。')
                rendered.append(language.notification_speech_segments(text, settings, name))
                Path(output).write_bytes(b'audio fixture')
                return True
            with patch('nkc.runtime.resolve_session_name', return_value='語音播報'), \
                    patch('nkc.audio.render_speech', side_effect=render), \
                    patch('nkc.audio.run_process', return_value=True):
                run_worker(store)
            self.assertEqual(len(rendered), 2)
            self.assertEqual([job['status'] for job in store.jobs()], ['spoken', 'spoken'])

    def test_real_synthesis_uses_separate_voices_and_one_complete_audio_file(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'summary.aiff'
            calls = []
            original = audio.run_process
            def observe(command, *args, **kwargs):
                if command[0] == '/usr/bin/say':
                    calls.append((command[command.index('-v') + 1],
                                  Path(command[command.index('-f') + 1]).read_text()))
                return original(command, *args, **kwargs)
            with patch('nkc.audio.run_process', side_effect=observe):
                self.assertTrue(audio.render_speech('改好了。', dict(self.settings, start=''),
                                                    output, session_name='codex lazy'))
            self.assertCountEqual(calls, [('Samantha', 'Session: codex lazy. '), ('Meijia', '改好了。')])
            with aifc.open(str(output)) as rendered:
                self.assertGreater(rendered.getnframes(), 22050)


if __name__ == '__main__':
    unittest.main()
