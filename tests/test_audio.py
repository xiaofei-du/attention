import os
import aifc
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nkc.audio import render_speech, run_process, speak
from nkc.opening import prepare_audio


class AudioProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_already_cancelled_does_not_start_audio(self):
        touched = self.root / 'started'
        result = run_process([sys.executable, '-c', 'from pathlib import Path; Path(__import__("sys").argv[1]).touch()', str(touched)],
                             lambda: True, timeout=1)
        self.assertFalse(result)
        self.assertFalse(touched.exists())

    def test_cancellation_waits_for_child_cleanup_and_reaps_the_process(self):
        ready, restored = self.root / 'ready', self.root / 'restored'
        code = ('import os,signal,sys,time; from pathlib import Path; '
                'signal.signal(signal.SIGTERM, lambda *_: (Path(sys.argv[2]).touch(), sys.exit(0))); '
                'Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(10)')
        result = run_process([sys.executable, '-c', code, str(ready), str(restored)], ready.exists, timeout=2)
        self.assertFalse(result)
        self.assertTrue(restored.exists(), 'Cleanup must finish before the next notification can start')
        with self.assertRaises(ProcessLookupError):
            os.kill(int(ready.read_text()), 0)

    def test_timeout_stops_and_reaps_the_child(self):
        ready = self.root / 'ready'
        code = 'import os,sys,time; from pathlib import Path; Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(10)'
        with self.assertRaisesRegex(RuntimeError, 'timeout'):
            run_process([sys.executable, '-c', code, str(ready)], lambda: False, timeout=0.3)
        with self.assertRaises(ProcessLookupError):
            os.kill(int(ready.read_text()), 0)

    def test_audio_failure_is_reported(self):
        with self.assertRaisesRegex(RuntimeError, 'device unavailable'):
            run_process([sys.executable, '-c', 'import sys; sys.stderr.write("device unavailable"); sys.exit(7)'],
                        lambda: False, timeout=1)

    def test_missing_native_player_does_not_fall_back_to_overlapping_media(self):
        with self.assertRaisesRegex(RuntimeError, 'build'):
            speak('Hello, sunshine。', {'voice': 'Meijia', 'rate': 180}, lambda: False,
                  player=self.root / 'missing-player')

    def test_queue_uses_ducking_player_after_rendering_and_keeps_lock(self):
        player = self.root / 'native-player'
        observed = self.root / 'player-observed.jsonl'
        opening = prepare_audio({'type': 'system', 'name': 'Glass'}, self.root / 'opening-audio')
        with (self.root / 'speaker.lock').open('a') as lock:
            player.write_text('#!' + sys.executable + '\n' +
                'import aifc,json,os,sys\n' +
                'assert sys.argv[1] == "--duck"\n' +
                'os.fstat(' + str(lock.fileno()) + ')\n' +
                'with aifc.open(sys.argv[2], "rb") as f:\n' +
                '    result = {"frames":f.getnframes(),"rate":f.getframerate()}\n' +
                'with open(' + repr(str(observed)) + ', "a") as output:\n' +
                '    output.write(json.dumps(result) + "\\n")\n')
            player.chmod(0o755)
            self.assertTrue(speak('Hello, sunshine。改好了。The tests passed.',
                                 {'voice': 'Meijia', 'rate': 180, 'start_audio': opening, 'duck_media': True}, lambda: False,
                                 player=player, lock_fd=lock.fileno()))
        observations = observed.read_text().splitlines()
        self.assertEqual(len(observations), 1, 'One complete file must share one ducking lifetime')
        self.assertGreater(json.loads(observations[0])['frames'], 22050)

    def test_language_segments_are_concatenated_without_losing_audio(self):
        settings = {'voice': 'Meijia', 'rate': 180, 'voice_mode': 'auto'}
        parts = [('Samantha', 'Hello, sunshine。'), ('Meijia', '改好了。')]
        expected = b''
        for index, (voice, text) in enumerate(parts):
            path = self.root / (str(index) + '.aiff')
            render_speech(text, dict(settings, voice=voice, voice_mode='fixed'), path)
            with aifc.open(str(path), 'rb') as file:
                expected += file.readframes(file.getnframes())
        output = self.root / 'mixed.aiff'
        render_speech(''.join(text for _, text in parts), settings, output)
        with aifc.open(str(output), 'rb') as file:
            self.assertEqual(file.getframerate(), 22050)
            self.assertEqual(len(file.readframes(file.getnframes())), len(expected))

    def test_cancelled_render_does_not_replace_a_previous_output(self):
        output = self.root / 'previous.aiff'
        output.write_bytes(b'previous output')
        with patch('nkc.audio.run_process', return_value=False):
            self.assertFalse(render_speech('Hello, sunshine。改好了。',
                                          {'voice': 'Meijia', 'rate': 180}, output))
        self.assertEqual(output.read_bytes(), b'previous output')
        self.assertEqual(list(self.root.glob('nkc-render-*')), [])


if __name__ == '__main__':
    unittest.main()
