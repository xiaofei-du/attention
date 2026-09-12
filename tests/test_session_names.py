import json
import os
import shlex
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nkc.install import PROJECT, PYTHON
from nkc.runtime import handle_hook, run_worker
from nkc.store import Store
from nkc.summary import notification_text
from nkc.session_names import resolve_session_name


class SessionNameTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = Store(self.root / 'queue')
        self.home = self.root / 'codex'
        self.home.mkdir()
        self.transcript = self.root / 'claude.jsonl'

    def codex(self, name='Original', title='First prompt', legacy=False):
        path = self.home / 'state_5.sqlite'
        with sqlite3.connect(str(path)) as db:
            if legacy:
                db.execute('CREATE TABLE threads(id TEXT PRIMARY KEY, title TEXT)')
                db.execute('INSERT INTO threads VALUES(?,?)', ('A', title))
            else:
                db.execute('CREATE TABLE threads(id TEXT PRIMARY KEY, name TEXT, title TEXT)')
                db.execute('INSERT INTO threads VALUES(?,?,?)', ('A', name, title))
        return path

    def append(self, kind, title, session='A'):
        key = 'customTitle' if kind == 'custom-title' else 'aiTitle'
        with self.transcript.open('a') as stream:
            stream.write(json.dumps({'type': kind, key: title, 'sessionId': session}) + '\n')

    def resolve(self, provider):
        return resolve_session_name(provider, 'A', {'config_home': str(self.home),
                                                    'transcript_path': str(self.transcript)})

    def test_preference_defaults_off_and_survives_other_settings_and_restarts(self):
        self.assertFalse(self.store.settings()['announce_session_name'])
        self.store.set_start('你好美女')
        self.store.set_announce_session_name(True)
        token = self.store.begin_turn('codex', 'A', 'one')
        self.store.set_session_enabled(token, False)
        self.store.configure(rate=200)
        settings = Store(self.store.root).settings()
        self.assertTrue(settings['announce_session_name'])
        self.assertEqual(settings['start'], '你好美女')
        for value in (1, 'false', None, []):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.store.set_announce_session_name(value)
        self.assertTrue(self.store.settings()['announce_session_name'])
        self.store.set_announce_session_name(False)
        self.assertFalse(Store(self.store.root).settings()['announce_session_name'])

    def test_prompt_supplies_executable_control_for_both_providers_even_when_muted(self):
        for provider in ('codex', 'claude-code'):
            token = self.store.begin_turn(provider, 'A', 'one')
            self.store.set_session_enabled(token, False)
            result = handle_hook('prompt', {'hook_event_name': 'UserPromptSubmit', 'session_id': 'A',
                                 'turn_id': 'one', 'prompt_id': 'one'}, self.store, provider=provider)
            context = result['hookSpecificOutput']['additionalContext']
            self.assertNotIn('{{', context)
            command = next(line for line in context.splitlines() if line.endswith('set-session-name-report'))
            process = subprocess.run(shlex.split(command), input='{"enabled":true}', text=True,
                                     capture_output=True, timeout=15)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(json.loads(process.stdout), {'announce_session_name': True})
        for payload in ('{"enabled":"false"}', '{"enabled":true,"extra":1}', '[]'):
            process = subprocess.run(shlex.split(command), input=payload, text=True,
                                     capture_output=True, timeout=15)
            self.assertNotEqual(process.returncode, 0)
            self.assertTrue(self.store.settings()['announce_session_name'])

    def test_codex_reads_display_name_and_live_rename_in_preference_to_prompt_preview(self):
        path = self.codex()
        self.assertEqual(self.resolve('codex'), 'Original')
        with sqlite3.connect(str(path)) as db:
            db.execute('UPDATE threads SET name=? WHERE id=?', ('Renamed task', 'A'))
        self.assertEqual(self.resolve('codex'), 'Renamed task')

    def test_codex_supports_legacy_title_schema_and_skips_missing_identity(self):
        self.codex(title='Legacy name', legacy=True)
        self.assertEqual(self.resolve('codex'), 'Legacy name')
        self.assertEqual(resolve_session_name('codex', 'B', {'config_home': str(self.home)}), '')

    def test_codex_missing_or_corrupt_metadata_does_not_create_or_change_files(self):
        self.assertEqual(self.resolve('codex'), '')
        self.assertEqual(list(self.home.iterdir()), [])
        path = self.home / 'state_5.sqlite'
        path.write_bytes(b'broken')
        self.assertEqual(self.resolve('codex'), '')
        self.assertEqual(path.read_bytes(), b'broken')

    def test_claude_latest_custom_title_wins_even_over_newer_ai_titles(self):
        self.append('ai-title', 'Generated')
        self.append('custom-title', 'Chosen')
        self.append('ai-title', 'New generated')
        self.assertEqual(self.resolve('claude-code'), 'Chosen')
        self.append('custom-title', 'Renamed')
        self.assertEqual(self.resolve('claude-code'), 'Renamed')
        self.append('custom-title', '')
        self.assertEqual(self.resolve('claude-code'), 'New generated')

    def test_claude_uses_latest_ai_title_and_ignores_messages_other_sessions_and_partial_writes(self):
        self.append('ai-title', 'Old')
        self.append('ai-title', 'Current')
        self.append('custom-title', 'Wrong session', session='B')
        with self.transcript.open('a') as stream:
            stream.write(json.dumps({'type': 'assistant', 'sessionId': 'A',
                                     'customTitle': 'Not metadata'}) + '\n')
            stream.write('invalid json\n')
            stream.write('{"type":"custom-title","customTitle":"unfinished')
        self.assertEqual(self.resolve('claude-code'), 'Current')

    def test_claude_title_before_large_message_and_chunk_boundaries_is_found(self):
        self.append('custom-title', 'Earlier chosen name')
        with self.transcript.open('ab') as stream:
            stream.write(b'{"type":"assistant","body":"' + b'x' * 200000 + b'"}\n')
        self.append('ai-title', 'Recent generated name')
        self.assertEqual(self.resolve('claude-code'), 'Earlier chosen name')

    def test_unknown_invalid_and_speech_markup_names_are_skipped(self):
        self.assertEqual(self.resolve('claude-code'), '')
        self.assertEqual(self.resolve('unknown'), '')
        for title in (None, '[[slnc 999999]]', 'x' * 201, 'Title\nInjected line', '<speak>hi</speak>'):
            with self.subTest(title=title):
                self.transcript.write_text('')
                self.append('custom-title', title)
                self.assertEqual(self.resolve('claude-code'), '')

    def test_text_audio_and_empty_openings_have_ordered_optional_session_clause(self):
        self.store.set_announce_session_name(True)
        self.store.set_start('你好美女')
        settings = self.store.settings()
        self.assertEqual(notification_text('改好了。', settings, 'codex lazy'),
                         '你好美女 Session: codex lazy. 改好了。')
        for modified in (dict(settings, start=''), dict(settings, start_audio={'type': 'system'})):
            self.assertEqual(notification_text('改好了。', modified, 'codex lazy'),
                             'Session: codex lazy. 改好了。')
        for modified, name in ((dict(settings, announce_session_name=False), 'codex lazy'),
                               (settings, ''), (settings, '[[slnc 1000]]')):
            self.assertEqual(notification_text('改好了。', modified, name), '你好美女 改好了。')

    def test_queue_reads_renames_at_playback_with_provider_and_home_isolation(self):
        path = self.codex()
        self.append('ai-title', 'Claude original')
        for provider in ('codex', 'claude-code'):
            with patch.dict(os.environ, {'CODEX_HOME': str(self.home)}):
                handle_hook('prompt', {'hook_event_name': 'UserPromptSubmit', 'session_id': 'A',
                            'turn_id': 'one', 'prompt_id': 'one', 'transcript_path': str(self.transcript)},
                            self.store, provider=provider)
            self.store.enqueue(provider, 'A', 'one', provider + ' done.', delay=0)
        # Source metadata survives a stop without a transcript, and process restart.
        handle_hook('stop', {'hook_event_name': 'Stop', 'session_id': 'A', 'prompt_id': 'one'},
                    self.store, provider='claude-code')
        with sqlite3.connect(str(path)) as db:
            db.execute('UPDATE threads SET name=?', ('Codex renamed',))
        self.append('custom-title', 'Claude renamed')
        self.store.set_start('你好美女')
        self.store.set_announce_session_name(True)
        heard = []
        def sink(text, settings, cancelled):
            heard.append(text)
            return True
        with patch.dict(os.environ, {'CODEX_HOME': str(self.root / 'wrong-home')}):
            run_worker(Store(self.store.root), play=sink)
        self.assertEqual(heard, [
            '你好美女 Session: Codex renamed. codex done.',
            '你好美女 Session: Claude renamed. claude-code done.'])
        self.assertEqual([job['status'] for job in self.store.jobs()], ['spoken', 'spoken'])

    def test_disabled_setting_does_no_metadata_io_and_lookup_failure_does_not_drop_summary(self):
        for enabled in (False, True):
            self.store.set_announce_session_name(enabled)
            self.store.enqueue('claude-code', 'A', str(enabled), 'Done.', delay=0)
            heard = []
            with patch('nkc.runtime.resolve_session_name', side_effect=OSError('unavailable')) as lookup:
                run_worker(self.store, play=lambda text, settings, cancelled: heard.append(text) or True)
            self.assertEqual(lookup.call_count, int(enabled))
            self.assertEqual(heard, ['hey boss Done.'])
        self.assertEqual([job['status'] for job in self.store.jobs()], ['spoken', 'spoken'])

    def test_malformed_optional_source_cannot_block_prompt_or_stop(self):
        for source in ('bad\x00path', 'x' * 5000, {'not': 'a path'}):
            with self.subTest(source=source):
                event = dict(session_id='A', prompt_id=str(source), transcript_path=source)
                prompt = handle_hook('prompt', dict(event, hook_event_name='UserPromptSubmit'),
                                     self.store, provider='claude-code')
                self.assertIn('hookSpecificOutput', prompt)
                handle_hook('stop', dict(event, hook_event_name='Stop', last_assistant_message='Done.'),
                            self.store, provider='claude-code', start_worker=lambda root: None)
        self.assertEqual(len(self.store.jobs()), 3)

    def test_turning_name_report_off_affects_already_queued_jobs_without_muting_them(self):
        self.store.set_announce_session_name(True)
        self.store.enqueue('codex', 'A', 'one', 'Done.', delay=0)
        self.store.set_announce_session_name(False)
        heard = []
        with patch('nkc.runtime.resolve_session_name') as lookup:
            run_worker(self.store, play=lambda text, settings, cancelled: heard.append(text) or True)
        lookup.assert_not_called()
        self.assertEqual(heard, ['hey boss Done.'])

    def test_claude_scan_limit_does_not_substitute_ai_for_an_unseen_older_custom_title(self):
        from nkc.session_names import _reverse_records
        self.append('custom-title', 'Chosen name')
        with self.transcript.open('a') as stream:
            stream.write('x' * 200000 + '\n')
        self.append('ai-title', 'Recent generated name')
        with patch('nkc.session_names._reverse_records',
                   side_effect=lambda path: _reverse_records(path, max_scan=100000)):
            self.assertEqual(self.resolve('claude-code'), '')

    def test_existing_queue_migrates_with_opening_and_pending_notification_intact(self):
        root = self.root / 'old'
        root.mkdir()
        with sqlite3.connect(str(root / 'queue.sqlite3')) as db:
            db.executescript("CREATE TABLE settings(id INTEGER PRIMARY KEY,paused INTEGER,name TEXT,voice TEXT,"
                             "rate INTEGER,start TEXT,start_audio TEXT);"
                             "INSERT INTO settings VALUES(1,0,'unused','Meijia',180,'你好美女','');"
                             "CREATE TABLE jobs(id INTEGER PRIMARY KEY,provider TEXT,session_id TEXT,turn_id TEXT,"
                             "body TEXT,status TEXT,received REAL,ready_after REAL,error TEXT,"
                             "UNIQUE(provider,session_id,turn_id));"
                             "INSERT INTO jobs VALUES(1,'claude-code','A','one','Done.','pending',0,0,NULL);")
            db.execute("UPDATE jobs SET received=strftime('%s','now')")
        migrated = Store(root)
        self.assertFalse(migrated.settings()['announce_session_name'])
        self.assertEqual(migrated.settings()['start'], '你好美女')
        self.assertEqual(migrated.jobs()[0]['status'], 'pending')
        migrated.set_announce_session_name(True)
        heard = []
        run_worker(migrated, play=lambda text, settings, cancelled: heard.append(text) or True)
        self.assertEqual(heard, ['你好美女 Done.'])


if __name__ == '__main__':
    unittest.main()
