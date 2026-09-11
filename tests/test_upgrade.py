"""An in-flight hook must retain its exact verified launcher after native upgrade."""
import hashlib
import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class UpgradeTests(unittest.TestCase):
    def test_native_upgrade_can_remove_old_cache_but_old_hook_entry_is_restored(self):
        bundle = os.environ.get('ATTENTION_TEST_MARKETPLACE')
        path = (Path(bundle) / 'plugins/attention' if bundle else ROOT) / 'scripts/update_codex_plugin.py'
        self.assertTrue(path.exists(), 'Native upgrades need an active-hook preservation wrapper')
        spec = importlib.util.spec_from_file_location('attention_upgrade', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / 'cache'
            old = cache / '0.1.0'
            old.mkdir(parents=True)
            launch = b'print("old hook still works")\n'
            (old / 'launch.py').write_bytes(launch)
            (old / 'payload.json').write_text(json.dumps({'files': {
                'launch.py': hashlib.sha256(launch).hexdigest()}}))
            (old / '.codex-plugin').mkdir()
            (old / '.codex-plugin/plugin.json').write_text('{"name":"attention","version":"0.1.0"}')
            for failure in (False, True):
                try:
                    with module.preserve_launchers(cache):
                        shutil.rmtree(old)
                        current = cache / 'new'
                        current.mkdir(exist_ok=True)
                        (current / 'current').write_text('new version stays installed')
                        if failure:
                            raise RuntimeError('native install failed')
                except RuntimeError:
                    self.assertTrue(failure)
                self.assertEqual((old / 'launch.py').read_bytes(), launch)
                self.assertEqual((cache / 'new/current').read_text(), 'new version stays installed')
                shutil.rmtree(cache / 'new')


if __name__ == '__main__':
    unittest.main()
