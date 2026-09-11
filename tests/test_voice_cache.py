import importlib.util
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from nkc import language
from nkc.voice_setup import MissingVoice


class VoiceCacheTests(unittest.TestCase):
    snapshot = {'voices': {'Samantha': 'en'}, 'metadata': [
        {'name': 'Samantha', 'language': 'en', 'locale': 'en_US', 'gender': 'female'}]}

    def cache_module(self):
        self.assertIsNotNone(importlib.util.find_spec('nkc.voice_cache'),
                             'Workers need a shared inventory cache across processes')
        from nkc import voice_cache
        return voice_cache

    def test_new_worker_reuses_inventory_without_native_queries(self):
        cache = self.cache_module()
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(cache, 'asset_fingerprint', return_value='unchanged'), \
                patch.object(cache, 'read_inventory', return_value=self.snapshot) as read:
            for _ in range(2):
                with cache.voice_inventory(Path(directory)):
                    self.assertEqual(language.installed_voices(), self.snapshot['voices'])
                    self.assertEqual(language.installed_voice_metadata(), self.snapshot['metadata'])
                self.assertIsNone(language._inventory_snapshot)
            self.assertEqual(read.call_count, 1)

    def test_asset_change_expiry_and_explicit_force_refresh(self):
        cache = self.cache_module()
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(cache, 'asset_fingerprint', return_value='one') as fingerprint, \
                patch.object(cache.time, 'time', return_value=1000) as clock, \
                patch.object(cache, 'read_inventory', return_value=self.snapshot) as read:
            root = Path(directory)
            with cache.voice_inventory(root): pass
            fingerprint.return_value = 'two'
            with cache.voice_inventory(root): pass
            clock.return_value += cache.MAX_AGE_SECONDS + 1
            with cache.voice_inventory(root): pass
            with cache.voice_inventory(root, force=True): pass
            self.assertEqual(read.call_count, 4)

    def test_corrupt_cache_recovers_and_missing_voices_are_not_cached(self):
        cache = self.cache_module()
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(cache, 'asset_fingerprint', return_value='same'), \
                patch.object(cache, 'read_inventory', side_effect=MissingVoice('No installed voices')):
            root = Path(directory)
            (root / 'voice-inventory.json').write_text('{bad json')
            with self.assertRaises(MissingVoice):
                with cache.voice_inventory(root): pass
            self.assertIsNone(language._inventory_snapshot)
            self.assertFalse((root / 'voice-inventory.json').exists())

    def test_optional_metadata_failure_keeps_normal_fallback_without_persisting_a_bad_cache(self):
        cache = self.cache_module()
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(cache, 'asset_fingerprint', return_value='same'), \
                patch.object(cache, 'read_inventory', return_value=None):
            root = Path(directory)
            with cache.voice_inventory(root):
                self.assertIsNone(language._inventory_snapshot)
            self.assertFalse((root / 'voice-inventory.json').exists())

    def test_asset_manifest_changes_invalidate_fingerprint(self):
        cache = self.cache_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'AssetsV2'
            collection = root / 'com_apple_MobileAsset_VoiceServices_Test'
            collection.mkdir(parents=True)
            manifest = collection / 'catalog.xml'
            manifest.write_text('old')
            with patch.object(cache, 'ASSET_ROOTS', (root,)):
                before = cache.asset_fingerprint()
                manifest.write_text('new downloaded voice')
                self.assertNotEqual(cache.asset_fingerprint(), before)

    def test_playback_reuses_unchanged_expired_inventory_while_refresh_is_running(self):
        # Slow Apple enumeration must not hold up playback of unchanged voices.
        cache = self.cache_module()
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(cache, 'asset_fingerprint', return_value='same'), \
                patch.object(cache.time, 'time', return_value=1000) as clock, \
                patch.object(cache, 'read_inventory', return_value=self.snapshot):
            root = Path(directory)
            cache.load_inventory(root)
            clock.return_value += cache.MAX_AGE_SECONDS + 1
            entered, release = threading.Event(), threading.Event()
            refreshed = {'voices': {'Daniel': 'en'}, 'metadata': [
                {'name': 'Daniel', 'language': 'en', 'locale': 'en_GB', 'gender': 'male'}]}
            def enumerate_voices():
                entered.set()
                self.assertTrue(release.wait(2))
                return refreshed
            with patch.object(cache, 'read_inventory', side_effect=enumerate_voices):
                thread = threading.Thread(target=cache.load_inventory, args=(root,))
                thread.start()
                try:
                    self.assertTrue(entered.wait(1))
                    self.assertEqual(cache.load_inventory(root, allow_stale=True), self.snapshot)
                finally:
                    release.set()
                    thread.join(3)
            self.assertEqual(cache.load_inventory(root), refreshed)

    def test_playback_does_not_reuse_inventory_after_assets_change(self):
        cache = self.cache_module()
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(cache, 'asset_fingerprint', return_value='old') as fingerprint, \
                patch.object(cache, 'read_inventory', return_value=self.snapshot):
            root = Path(directory)
            cache.load_inventory(root)
            fingerprint.return_value = 'new'
            with patch.object(cache, 'read_inventory', side_effect=MissingVoice('Voices were removed')):
                with self.assertRaises(MissingVoice):
                    cache.load_inventory(root, allow_stale=True)
            self.assertFalse((root / 'voice-inventory.json').exists())

    def test_prewarm_does_not_wait_for_another_enumeration(self):
        cache = self.cache_module()
        import fcntl
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (root / 'voice-inventory.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                self.assertIsNone(cache.load_inventory(root, nonblocking=True))


if __name__ == '__main__':
    unittest.main()
