import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nkc import language
from nkc.runtime import handle_hook
from nkc.store import Store
from cli_helpers import quiet_cli_prefix


VOICES = {'Meijia': 'zh', 'Samantha': 'en', 'Daniel': 'en',
          'Reed (Chinese (Taiwan))': 'zh', 'Thomas': 'fr', 'Amélie': 'fr'}
CATALOG = [dict(name=name, language=lang, gender=gender, locale=locale) for name, lang, gender, locale in [
    ('Meijia', 'zh', 'female', 'zh_TW'), ('Samantha', 'en', 'female', 'en_US'),
    ('Daniel', 'en', 'male', 'en_GB'), ('Reed (Chinese (Taiwan))', 'zh', 'unknown', 'zh_TW'),
    ('Thomas', 'fr', 'male', 'fr_FR'), ('Amélie', 'fr', 'female', 'fr_CA'),
    # Metadata alone must not select a voice absent from say's installed list.
    ('Unavailable', 'zh', 'male', 'zh_TW'),
]]
SETTINGS = dict(voice='Meijia', english_voice='Samantha', voice_mode='auto', rate=180)


class GenderSelectionTests(unittest.TestCase):
    def setUp(self):
        for target, result in [('installed_voices', VOICES), ('installed_voice_metadata', CATALOG)]:
            patcher = patch('nkc.language.' + target, return_value=result)
            patcher.start()
            self.addCleanup(patcher.stop)

    def segments(self, text, **settings):
        return language.speech_segments(text, dict(SETTINGS, **settings))

    def test_default_preserves_named_voices_and_does_not_query_gender(self):
        self.assertEqual(self.segments('改好了。All done.'), [('Meijia', '改好了。'), ('Samantha', 'All done.')])
        language.installed_voice_metadata.assert_not_called()

    def test_male_switches_english_but_missing_chinese_keeps_original_and_warns(self):
        with self.assertWarnsRegex(RuntimeWarning, 'zh.*Meijia'):
            segments = self.segments('改好了。All done.', voice_gender='male')
        self.assertEqual(segments, [('Meijia', '改好了。'), ('Daniel', 'All done.')])

    def test_female_applies_across_languages_and_keeps_text(self):
        text = 'Bonjour, les notifications fonctionnent.'
        self.assertEqual(self.segments(text, voice_gender='female'), [('Amélie', text)])

    def test_matching_user_voice_takes_priority_and_default_restores_it(self):
        self.assertEqual(self.segments('All done.', voice_gender='male', english_voice='Daniel'),
                         [('Daniel', 'All done.')])
        self.assertEqual(self.segments('All done.', voice_gender='default'), [('Samantha', 'All done.')])

    def test_fixed_mode_keeps_one_language_and_default_restores_exact_voice(self):
        text = 'All done. 改好了。'
        self.assertEqual(self.segments(text, voice='Samantha', voice_mode='fixed', voice_gender='male'),
                         [('Daniel', text)])
        self.assertEqual(self.segments(text, voice='Samantha', voice_mode='fixed', voice_gender='default'),
                         [('Samantha', text)])

    def test_metadata_failure_keeps_language_voice_with_warning(self):
        language.installed_voice_metadata.side_effect = RuntimeError('catalog unavailable')
        with self.assertWarnsRegex(RuntimeWarning, 'metadata'):
            self.assertEqual(self.segments('All done.', voice_gender='male'), [('Samantha', 'All done.')])

    def test_report_exposes_missing_gender_instead_of_claiming_success(self):
        report = language.voice_report(dict(SETTINGS, voice_gender='male'))
        self.assertEqual(report['languages']['en']['voice'], 'Daniel')
        self.assertTrue(report['languages']['en']['matched_preference'])
        self.assertEqual(report['languages']['zh']['voice'], 'Meijia')
        self.assertFalse(report['languages']['zh']['matched_preference'])
        self.assertTrue(any('zh' in warning for warning in report['warnings']))

    def test_failed_metadata_is_attempted_once_per_report(self):
        language.installed_voice_metadata.side_effect = RuntimeError('catalog unavailable')
        report = language.voice_report(dict(SETTINGS, voice_gender='male'))
        self.assertTrue(report['warnings'])
        language.installed_voice_metadata.assert_called_once()

    def test_unavailable_voice_inventory_reports_saved_preference_as_unverified(self):
        language.installed_voices.side_effect = OSError('say unavailable')
        report = language.voice_report(dict(SETTINGS, voice_gender='male'))
        self.assertEqual(report['voice_gender'], 'male')
        self.assertEqual(report['languages'], {})
        self.assertIn('unverified', report['warnings'][0])


class GenderControlTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.store = Store(self.root)

    def cli(self, *args, payload=None):
        return subprocess.run(quiet_cli_prefix() + ['--state-dir', str(self.root), *args],
                              input=json.dumps(payload), capture_output=True, text=True, timeout=30)

    def test_migration_and_roundtrip_only_change_gender(self):
        self.store.set_start('你好美女')
        self.store.set_announce_session_name(True)
        token = self.store.begin_turn('codex', 'muted', 'one')
        self.store.set_session_enabled(token, False)
        self.store.set_global_enabled(False)
        self.store.configure(voice='Tingting', english_voice='Daniel', rate=200)
        before = self.store.settings()
        self.assertEqual(before['voice_gender'], 'default')
        # An existing installation migrates without changing other preferences.
        with self.store.db() as db:
            db.execute('ALTER TABLE settings DROP COLUMN voice_gender')
        self.assertEqual(Store(self.root).settings(), before)
        for gender in ('male', 'female', 'default'):
            self.store.set_voice_gender(gender)
            self.assertEqual(Store(self.root).settings(), dict(before, voice_gender=gender))
            self.assertFalse(self.store.session_enabled('codex', 'muted'))
        self.assertEqual(self.store.jobs(), [])

    def test_invalid_values_and_payloads_preserve_preference(self):
        self.store.set_voice_gender('female')
        for value in ('neutral', 'Male', '', None, True, [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.store.set_voice_gender(value)
        for payload in ({'gender': 'neutral'}, {'gender': 'male', 'enabled': True}, []):
            self.assertNotEqual(self.cli('set-voice-gender', payload=payload).returncode, 0)
        self.assertEqual(self.store.settings()['voice_gender'], 'female')

    def test_cli_reports_real_choices_and_listing_does_not_select_or_play(self):
        result = self.cli('set-voice-gender', payload={'gender': 'male'})
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['voice_gender'], 'male')
        self.assertIn('en', report['languages'])
        before = self.store.settings()
        listed = self.cli('list-voices')
        self.assertEqual(listed.returncode, 0, listed.stderr)
        voices = json.loads(listed.stdout)['voices']
        self.assertTrue(voices)
        for voice in voices:
            self.assertIn(voice['name'], language.installed_voices())
            self.assertIn(voice['gender'], ('male', 'female', 'unknown'))
        self.assertEqual(self.store.settings(), before)
        self.assertEqual(self.store.jobs(), [])

    def test_both_provider_prompts_include_persistent_control_while_disabled(self):
        self.store.set_voice_gender('male')
        self.store.set_global_enabled(False)
        self.store.set_start('好' * 120)
        for provider, field in [('codex', 'turn_id'), ('claude-code', 'prompt_id')]:
            event = {'session_id': provider, field: 'one', 'hook_event_name': 'UserPromptSubmit'}
            prompt = handle_hook('prompt', event, self.store, provider=provider)['hookSpecificOutput']['additionalContext']
            self.assertIn('set-voice-gender', prompt)
            self.assertIn('list-voices', prompt)
            self.assertIn('Shared gender: male', prompt)
            self.assertNotIn('{{', prompt)
            self.assertLessEqual(len(prompt.encode('utf-8')), 10000)


if __name__ == '__main__':
    unittest.main()
