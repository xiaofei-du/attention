import json
import struct
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

from nkc.audio import build_player
from nkc.install import PROJECT


class NativeAudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.player = build_player()

    def test_empty_audio_is_rejected_before_activating_ducking(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'empty.wav'
            with wave.open(str(path), 'wb') as output:
                output.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            result = subprocess.run([str(self.player), str(path)], capture_output=True, text=True, timeout=3)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('media-relay:', result.stderr)

    def test_real_file_conversion_preserves_duration_and_level(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sample.wav'
            with wave.open(str(path), 'wb') as output:
                output.setparams((1, 2, 16000, 16000, 'NONE', 'not compressed'))
                output.writeframes(struct.pack('<h', 8192) * 16000)
            result = subprocess.run([str(self.player), '--inspect', str(path)], capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            info = json.loads(result.stdout)
            self.assertAlmostEqual(info['duration'], 1.0, delta=0.003)
            self.assertAlmostEqual(info['rms'], 0.25, delta=0.005)

    def test_missing_audio_file_fails_before_starting_native_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([str(self.player), str(Path(directory) / 'missing.aiff')],
                                    capture_output=True, text=True, timeout=3)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('open audio file', result.stderr)
            self.assertNotIn('media-relay:', result.stderr)

    def test_relay_gain_and_invalid_buffers_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = str(Path(directory) / 'relay-check')
            subprocess.run(['xcrun', 'clang', '-Wall', '-Wextra', '-Werror',
                            '-I', str(PROJECT / 'native'), str(PROJECT / 'tests' / 'relay_check.c'),
                            '-o', binary], check=True, capture_output=True, timeout=30)
            result = subprocess.run([binary], capture_output=True, text=True, timeout=3)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_invalid_media_gain_is_rejected_before_audio_or_permission(self):
        for gain in ('0', '1.1', 'nan', '0.05junk'):
            result = subprocess.run([str(self.player), '--duck-test', '/missing.aiff', gain],
                                    capture_output=True, text=True, timeout=3)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('media gain', result.stderr)
            self.assertNotIn('media-relay:', result.stderr)


if __name__ == '__main__':
    unittest.main()
