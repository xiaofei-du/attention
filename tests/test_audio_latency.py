import aifc
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from nkc import audio, language


class AudioLatencyTests(unittest.TestCase):
    settings = dict(voice='Meijia', english_voice='Samantha', voice_mode='auto',
                    voice_gender='default', rate=180)

    def test_inventory_queries_overlap_and_are_reused_by_voice_selection(self):
        self.assertTrue(callable(getattr(language, 'prepare_voice_inventory', None)),
                        'Rendering must prepare independent inventory queries concurrently')
        from nkc.voice_setup import refresh_voice_inventory
        refresh_voice_inventory()
        self.addCleanup(refresh_voice_inventory)
        barrier = threading.Barrier(2)
        calls = []
        def run(command, **kwargs):
            kind = 'voices' if command[0] == '/usr/bin/say' else 'metadata'
            calls.append(kind)
            barrier.wait(timeout=2)
            result = ('Samantha en_US # Hello.\n' if kind == 'voices' else
                      '[{"name":"Samantha","locale":"en_US","gender":"female"}]')
            return subprocess.CompletedProcess(command, 0, stdout=result)
        with patch('nkc.language.subprocess.run', side_effect=run):
            language.prepare_voice_inventory(dict(self.settings, voice_gender='female'))
            self.assertEqual(language.installed_voices(), {'Samantha': 'en'})
            self.assertEqual(language.installed_voice_metadata()[0]['name'], 'Samantha')
        self.assertCountEqual(calls, ['voices', 'metadata'])

    def test_parallel_synthesis_keeps_segment_order_and_one_final_file(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'spoken.aiff'
            barrier = threading.Barrier(2)
            def render(command, *args, **kwargs):
                index = int(Path(command[command.index('-o') + 1]).stem)
                # The second synthesis must start before the first can finish.
                barrier.wait(timeout=2)
                path = command[command.index('-o') + 1]
                with aifc.open(path, 'wb') as target:
                    target.setparams((1, 2, 22050, 0, b'NONE', b'not compressed'))
                    target.writeframes(bytes([index + 1, 0]) * 100)
                return True
            with patch('nkc.audio.speech_segments', return_value=[('Samantha', 'Hello.'), ('Meijia', '你好。')]), \
                    patch('nkc.audio.run_process', side_effect=render):
                self.assertTrue(audio.render_speech('Hello.你好。', self.settings, output))
            with aifc.open(str(output)) as result:
                self.assertEqual(result.readframes(200), b'\1\0' * 100 + b'\2\0' * 100)

    def test_failed_synthesis_cancels_its_peer_and_keeps_previous_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'spoken.aiff'
            output.write_bytes(b'previous output')
            barrier = threading.Barrier(2)
            stopped = threading.Event()
            def render(command, cancelled, **kwargs):
                index = int(Path(command[command.index('-o') + 1]).stem)
                barrier.wait(timeout=2)
                if index == 0:
                    raise RuntimeError('synthesis failed')
                for _ in range(200):
                    if cancelled():
                        stopped.set()
                        return False
                    stopped.wait(0.005)
                self.fail('Peer synthesis was left running after a failure')
            with patch('nkc.audio.speech_segments', return_value=[('Samantha', 'Hello.'), ('Meijia', '你好。')]), \
                    patch('nkc.audio.run_process', side_effect=render):
                with self.assertRaisesRegex(RuntimeError, 'synthesis failed'):
                    audio.render_speech('Hello.你好。', self.settings, output)
            self.assertTrue(stopped.is_set())
            self.assertEqual(output.read_bytes(), b'previous output')
            self.assertEqual(list(Path(directory).glob('nkc-render-*')), [])


if __name__ == '__main__':
    unittest.main()
