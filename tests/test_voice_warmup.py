import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from nkc import runtime
from nkc.store import Store


class VoiceWarmupTests(unittest.TestCase):
    def test_prompt_warmup_returns_before_the_slow_child_finishes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = Store(root / 'state')
            script = root / 'run.py'
            script.write_text('import json,sys,time\nfrom pathlib import Path\n'
                'root=Path(sys.argv[2])\n'
                '(root/"started").write_text(json.dumps(sys.argv[1:]))\n'
                'while not (root/"release").exists(): time.sleep(.01)\n')
            with patch.object(runtime, 'PROJECT', root), patch.object(runtime, 'PYTHON', sys.executable):
                child = runtime.start_voice_warmup(store, 'codex', 'A')
            try:
                deadline = time.monotonic() + 2
                while not (store.root / 'started').exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertIsNone(child.poll(), 'Prompt waits for neither enumeration nor playback')
                self.assertEqual(json.loads((store.root / 'started').read_text()),
                                 ['--state-dir', str(store.root), 'warm-voices'])
                self.assertEqual(store.jobs(), [], 'Warmup must never enqueue content')
            finally:
                (store.root / 'release').touch()
                child.wait(timeout=3)

    def test_muted_or_audio_only_sessions_need_no_voice_warmup(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            token = store.begin_turn('codex', 'A', '1')
            store.set_global_enabled(False)
            self.assertIsNone(runtime.start_voice_warmup(store, 'codex', 'A'))
            store.set_global_enabled(True)
            store.set_session_enabled(token, False)
            self.assertIsNone(runtime.start_voice_warmup(store, 'codex', 'A'))
            store.set_session_enabled(token, True)
            store.set_summary_preferences(enabled=False)
            store.set_starter_options(opening={'type': 'none'}, announce_session_name=False)
            self.assertIsNone(runtime.start_voice_warmup(store, 'codex', 'A'))


if __name__ == '__main__':
    unittest.main()
