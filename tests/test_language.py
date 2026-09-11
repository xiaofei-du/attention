import unittest
import json
import subprocess
from unittest.mock import patch

from nkc import audio, language


class VoiceInventoryTests(unittest.TestCase):
    listing = '''Samantha en_US # Hello.
Haohao (Enhanced) zh_CN_U_SD@sd=cnsn # 你好！我叫浩浩。
Dongmei (Enhanced) zh_CN_U_SD@sd=cnln # 你好！我叫冬梅。
Script Voice zh_Hant_TW # 你好。
BCP Voice zh-Hant-TW # 你好。
Latin American Voice es_419 # Hola.
Regional Voice fil_PH # Kumusta.
Keyword Voice en_US@calendar=gregorian # Hello.
'''

    def setUp(self):
        for function in [language.installed_voices, language.installed_voice_metadata, language.native_voice_metadata]:
            function.cache_clear()
            self.addCleanup(function.cache_clear)

    def test_extended_locales_do_not_hide_downloaded_voices(self):
        with patch('nkc.language.subprocess.run', return_value=subprocess.CompletedProcess(
                [], 0, stdout=self.listing, stderr='')):
            self.assertEqual(language.installed_voices(), {
                'Samantha': 'en', 'Haohao (Enhanced)': 'zh', 'Dongmei (Enhanced)': 'zh',
                'Script Voice': 'zh', 'BCP Voice': 'zh', 'Latin American Voice': 'es',
                'Regional Voice': 'fil', 'Keyword Voice': 'en'})

    def test_downloaded_male_voice_survives_metadata_filter_and_is_selected(self):
        actual_run = subprocess.run
        def native(args, **kwargs):
            if args[0] == '/usr/bin/say':
                return subprocess.CompletedProcess(args, 0, stdout=self.listing, stderr='')
            if args[-1] == '--voices':
                records = [dict(name='Haohao (Enhanced)', locale='zh_CN_U_SD@sd=cnsn', gender='male'),
                           dict(name='Samantha', locale='en_US', gender='female')]
                return subprocess.CompletedProcess(args, 0, stdout=json.dumps(records), stderr='')
            return actual_run(args, **kwargs)
        with patch('nkc.language.subprocess.run', side_effect=native):
            self.assertEqual(language.speech_segments('現在測試中文男聲。',
                             dict(voice='Meijia', english_voice='Samantha', voice_mode='auto', voice_gender='male')),
                             [('Haohao (Enhanced)', '現在測試中文男聲。')])
            catalog = language.installed_voice_metadata()
            self.assertEqual(catalog[0]['locale'], 'zh_CN_U_SD@sd=cnsn')
            self.assertEqual(catalog[0]['gender'], 'male')


class AdaptiveVoiceTests(unittest.TestCase):
    settings = {'voice': 'Meijia', 'english_voice': 'Samantha', 'voice_mode': 'auto', 'rate': 180}

    def test_greeting_chinese_and_english_sentences_choose_their_own_voices(self):
        self.assertEqual(audio.speech_segments('Hello, sunshine。改好了。The tests passed.', self.settings), [
            ('Samantha', 'Hello, sunshine。'), ('Meijia', '改好了。'), ('Samantha', 'The tests passed.')])

    def test_embedded_english_terms_do_not_switch_every_word(self):
        self.assertEqual(audio.speech_segments('這個 session 的 API 已經修好了。', self.settings),
                         [('Meijia', '這個 session 的 API 已經修好了。')])

    def test_adjacent_english_sentences_render_together_without_losing_text(self):
        text = 'Hello, sunshine。Version 2.1 is ready. All tests passed!'
        self.assertEqual(audio.speech_segments(text, self.settings), [('Samantha', text)])

    def test_fixed_mode_preserves_the_user_selected_voice(self):
        settings = dict(self.settings, voice_mode='fixed', voice='Daniel')
        text = 'Hello, sunshine。改好了。'
        self.assertEqual(audio.speech_segments(text, settings), [('Daniel', text)])

    def test_configured_english_voice_is_used_for_an_english_reply(self):
        self.assertEqual(audio.speech_segments('All done.', dict(self.settings, english_voice='Daniel')),
                         [('Daniel', 'All done.')])

    def test_ok_does_not_unexpectedly_select_a_different_language(self):
        self.assertEqual(audio.speech_segments('OK.', self.settings), [('Samantha', 'OK.')])

    def test_missing_voice_is_reported_instead_of_using_a_wrong_language(self):
        from unittest.mock import patch
        with patch('nkc.language.installed_voices', return_value={'Meijia': 'zh', 'Samantha': 'en'}):
            with self.assertRaisesRegex(RuntimeError, 'No installed voice'):
                audio.speech_segments('Bonjour, les notifications utilisent la langue de votre réponse.', self.settings)

    def test_other_installed_languages_can_be_selected_without_translation(self):
        samples = [
            ('Kyoko', 'こんにちは。通知の音声が自動的に日本語に切り替わります。'),
            ('Yuna', '안녕하세요. 이제 알림을 한국어로 들을 수 있습니다.'),
            ('Thomas', 'Bonjour, les notifications utilisent maintenant la langue de votre réponse.'),
            ('Anna', 'Die Benachrichtigungen verwenden jetzt automatisch die Sprache Ihrer Antwort.'),
            ('Mónica', 'Las notificaciones ahora utilizan automáticamente el idioma de tu respuesta.'),
        ]
        for voice, text in samples:
            with self.subTest(voice=voice):
                self.assertEqual(audio.speech_segments(text, self.settings), [(voice, text)])


if __name__ == '__main__':
    unittest.main()
