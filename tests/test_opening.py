import aifc
import json
import struct
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

from nkc.audio import render_speech
from nkc.install import PROJECT, PYTHON
from nkc.runtime import handle_hook, run_worker
from nkc.store import Store


class OpeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.state = self.root / 'state'
        self.source = self.root / 'my opening.wav'
        with wave.open(str(self.source), 'wb') as file:
            file.setparams((2, 2, 48000, 0, 'NONE', 'not compressed'))
            file.writeframes(struct.pack('<hh', 500, 500) * 4800)

    def command(self, *args, payload=None, success=True):
        result = subprocess.run([PYTHON, str(PROJECT / 'run.py'), '--state-dir', str(self.state), *args],
                                input=json.dumps(payload) if payload is not None else '',
                                text=True, capture_output=True, timeout=30)
        if not success:
            self.assertNotEqual(result.returncode, 0)
            return result.stderr
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def select_custom(self, path=None):
        return self.command('set-start-audio', payload={'type': 'custom', 'path': str(path or self.source)})

    def test_lists_actual_apple_sounds_and_keeps_selection_across_restarts(self):
        sounds = self.command('list-start-sounds')['sounds']
        self.assertEqual(sounds, sorted(p.stem for p in Path('/System/Library/Sounds').glob('*.aiff')))
        self.assertIn('Glass', sounds)
        self.command('set-start', payload={'text': '原來的開場。'})
        selected = self.command('set-start-audio', payload={'type': 'system', 'name': 'Glass'})
        settings = self.command('status')['settings']
        self.assertEqual(settings['start_audio'], selected['start_audio'])
        self.assertEqual(settings['start_audio']['type'], 'system')
        self.assertEqual(settings['start_audio']['name'], 'Glass')
        self.assertEqual(settings['start'], '原來的開場。')
        self.assertEqual(self.command('status')['jobs'], [])

    def test_import_accepts_wav_aiff_m4a_and_mp3_and_copies_audio(self):
        sources = [self.source, PROJECT / 'tests/fixtures/short-tone.mp3']
        for extension, fmt, data in [('aiff', 'AIFF', 'BEI16'), ('m4a', 'm4af', 'aac')]:
            path = self.root / ('source.' + extension)
            subprocess.run(['/usr/bin/afconvert', str(self.source), str(path), '-f', fmt, '-d', data],
                           check=True, capture_output=True)
            sources.append(path)
        for path in sources:
            with self.subTest(format=path.suffix):
                audio = self.select_custom(path)['start_audio']
                managed = Path(audio['file'])
                self.assertEqual(managed.parent, self.state / 'opening-audio')
                with aifc.open(str(managed), 'rb') as file:
                    self.assertEqual((file.getnchannels(), file.getsampwidth(), file.getframerate()), (1, 2, 22050))
                    self.assertGreater(file.getnframes(), 0)
                self.assertLess(audio['seconds'], 1)
        audio = self.select_custom()['start_audio']
        self.source.unlink()
        self.assertTrue(Path(audio['file']).is_file())
        self.assertEqual(Store(self.state).settings()['start_audio'], audio)

    def test_invalid_import_keeps_previous_selection(self):
        self.select_custom()
        previous = self.command('status')['settings']
        bad = self.root / 'broken.mp3'
        bad.write_bytes(b'not audio')
        cases = [({'type': 'system', 'name': '../Glass'}, 'Unknown system sound'),
                 ({'type': 'custom', 'path': str(bad)}, 'decode'),
                 ({'type': 'custom', 'path': str(self.root / 'missing.wav')}, 'file'),
                 ({'type': 'custom', 'path': str(self.root)}, 'file'),
                 ({'type': 'custom', 'path': str(self.source), 'extra': True}, 'requires')]
        for payload, message in cases:
            with self.subTest(payload=payload):
                error = self.command('set-start-audio', payload=payload, success=False)
                self.assertIn(message, error)
                self.assertEqual(self.command('status')['settings'], previous)

    def test_long_or_oversized_import_is_rejected_without_truncation(self):
        self.select_custom()
        previous = self.command('status')['settings']
        long = self.root / 'long.wav'
        with wave.open(str(long), 'wb') as file:
            file.setparams((1, 2, 22050, 0, 'NONE', 'not compressed'))
            file.writeframes(b'\0\0' * 22050 * 31)
        huge = self.root / 'huge.wav'
        with huge.open('wb') as file:
            file.truncate(20 * 1024 * 1024 + 1)
        for path, message in [(long, '30 seconds'), (huge, '20 MiB')]:
            error = self.command('set-start-audio', payload={'type': 'custom', 'path': str(path)}, success=False)
            self.assertIn(message, error)
            self.assertEqual(self.command('status')['settings'], previous)

    def test_text_or_empty_start_explicitly_switches_away_from_audio(self):
        for text in ('新的稱呼。', ''):
            self.select_custom()
            self.command('set-start', payload={'text': text})
            settings = self.command('status')['settings']
            self.assertEqual(settings['start'], text)
            self.assertIsNone(settings['start_audio'])

    def test_voice_or_rate_edits_do_not_change_audio_opening(self):
        selected = self.select_custom()['start_audio']
        settings = self.command('configure', '--rate', '210', '--voice-mode', 'fixed')
        self.assertEqual(settings['start_audio'], selected)

    def test_audio_replaces_greeting_and_is_prepended_to_summary_in_one_file(self):
        self.command('set-start', payload={'text': '不應朗讀這句開場。'})
        audio = self.select_custom()['start_audio']
        store = Store(self.state)
        token = store.begin_turn('codex', 'A', '1')
        store.stage_summary(token, {'why': '我們在做音效開場。', 'done': '已經接好。', 'next': ''})
        handle_hook('stop', {'hook_event_name': 'Stop', 'session_id': 'A', 'turn_id': '1',
                            'last_assistant_message': '詳細技術說明。' * 100}, store, start_worker=lambda root: None)
        with store.db() as db:
            db.execute('UPDATE jobs SET ready_after=0')
        with aifc.open(audio['file'], 'rb') as file:
            intro = file.readframes(file.getnframes())
        heard = []
        def sink(text, settings, cancelled):
            heard.append(text)
            output = self.root / 'whole.aiff'
            self.assertTrue(render_speech(text, settings, output, cancelled))
            with aifc.open(str(output), 'rb') as file:
                self.assertEqual(file.readframes(len(intro) // 2), intro)
                self.assertGreater(file.getnframes(), len(intro) // 2 + 22050)
            return True
        run_worker(store, play=sink)
        self.assertEqual(heard, ['我們在做音效開場。已經接好。'])
        self.assertEqual(store.jobs()[0]['status'], 'spoken')

    def test_preview_returns_audio_without_changing_selection_or_queuing(self):
        self.select_custom()
        previous = self.command('status')['settings']
        output = self.root / 'preview.wav'
        preview = self.command('preview-start-audio', '--output', str(output),
                               payload={'type': 'system', 'name': 'Glass'})
        self.assertEqual(preview['file'], str(output))
        with wave.open(str(output), 'rb') as file:
            self.assertGreater(file.getnframes(), 0)
        self.assertEqual(self.command('status')['settings'], previous)
        self.assertEqual(self.command('status')['jobs'], [])

    def test_audio_opening_then_live_session_name_then_summary_render_as_one_file(self):
        audio = self.select_custom()['start_audio']
        store = Store(self.state)
        store.set_announce_session_name(True)
        transcript = self.root / 'session.jsonl'
        transcript.write_text(json.dumps({'type': 'custom-title', 'sessionId': 'A',
                                          'customTitle': 'Queue review'}) + '\n')
        handle_hook('prompt', {'hook_event_name': 'UserPromptSubmit', 'session_id': 'A',
                    'prompt_id': 'one', 'transcript_path': str(transcript)}, store, provider='claude-code')
        store.enqueue('claude-code', 'A', 'one', 'Done.', delay=0)
        with aifc.open(audio['file'], 'rb') as source:
            intro = source.readframes(source.getnframes())
        heard = []
        def sink(text, settings, cancelled):
            heard.append(text)
            output = self.root / 'with-name.aiff'
            self.assertTrue(render_speech(text, settings, output, cancelled))
            with aifc.open(str(output), 'rb') as rendered:
                self.assertEqual(rendered.readframes(len(intro) // 2), intro)
                self.assertGreater(rendered.getnframes(), len(intro) // 2 + 22050)
            return True
        run_worker(store, play=sink)
        self.assertEqual(heard, ['Session: Queue review. Done.'])
        self.assertEqual(store.jobs()[0]['status'], 'spoken')

    def test_prompt_provides_audio_commands_and_type_without_saved_metadata(self):
        selected = self.select_custom()['start_audio']
        prompt = self.command('hook', 'prompt', payload={'hook_event_name': 'UserPromptSubmit',
                                                       'session_id': 'A', 'turn_id': '1'})
        context = prompt['hookSpecificOutput']['additionalContext']
        self.assertIn(' set-start-audio', context)
        self.assertIn(' list-start-sounds', context)
        self.assertIn(' preview-start-audio', context)
        self.assertIn('Opening type: custom', context)
        self.assertNotIn(selected['name'], context)
        self.assertNotIn(selected['file'], context)
        self.assertEqual(self.command('status')['settings']['start_audio'], selected)
        self.assertNotIn('{{', context)


if __name__ == '__main__':
    unittest.main()
