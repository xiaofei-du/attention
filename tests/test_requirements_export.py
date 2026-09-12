"""Bundled dependency hashes must match both the wheel and locked version."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.export_requirements import with_bundled_hash


class RequirementsExportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.wheel = self.root / 'cryptography-50.0.1-cp312-abi3-macosx_14_0_x86_64.whl'
        self.wheel.write_bytes(b'wheel fixture')
        self.digest = hashlib.sha256(b'wheel fixture').hexdigest()
        self.manifest = {'distribution': 'cryptography', 'version': '50.0.1',
                         'wheel': self.wheel.name, 'sha256': self.digest}
        self.save_manifest()
        self.original = 'cryptography==50.0.1 \\\n    --hash=sha256:' + 'a' * 64 + '\nother==1.0\n'

    def save_manifest(self):
        (self.root / 'manifest.json').write_text(json.dumps(self.manifest))

    def test_adds_local_hash_without_losing_official_hashes_or_other_packages(self):
        expected = ('cryptography==50.0.1 \\\n    --hash=sha256:' + self.digest + ' \\\n    --hash=sha256:' +
                    'a' * 64 + '\nother==1.0\n')
        self.assertEqual(with_bundled_hash(self.original, self.root), expected)

    def test_modified_wheel_and_version_mismatch_are_rejected(self):
        self.wheel.write_bytes(b'changed')
        with self.assertRaises(ValueError):
            with_bundled_hash(self.original, self.root)
        self.wheel.write_bytes(b'wheel fixture')
        with self.assertRaises(ValueError):
            with_bundled_hash(self.original.replace('50.0.1', '50.0.2'), self.root)

    def test_manifest_cannot_point_outside_the_wheel_directory(self):
        self.manifest['wheel'] = '../' + self.wheel.name
        self.save_manifest()
        with self.assertRaises(ValueError):
            with_bundled_hash(self.original, self.root)
