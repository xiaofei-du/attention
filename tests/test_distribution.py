"""The GitHub checkout itself must be an installable, current marketplace."""
import json
import unittest
from pathlib import Path

from nkc.payload import payload_manifest
from scripts.build_marketplace import VERSION


ROOT = Path(__file__).resolve().parents[1]


class DistributionTests(unittest.TestCase):
    def test_github_catalogs_resolve_self_contained_plugins(self):
        for provider, catalog, folder, manifest in (
            ('codex', '.agents/plugins/marketplace.json', 'plugins', '.codex-plugin/plugin.json'),
            ('claude-code', '.claude-plugin/marketplace.json', 'claude-plugins', '.claude-plugin/plugin.json'),
        ):
            with self.subTest(provider=provider):
                self.assertTrue((ROOT / catalog).is_file(), 'GitHub install requires a root marketplace catalog')
                data = json.loads((ROOT / catalog).read_text())
                self.assertEqual(data['name'], 'xiaofei-du')
                entry, = data['plugins']
                self.assertEqual(entry['name'], 'attention')
                path = entry['source']['path'] if provider == 'codex' else entry['source']
                plugin = ROOT / path
                self.assertEqual(plugin.resolve(), ROOT / folder / 'attention')
                spec = json.loads((plugin / manifest).read_text())
                self.assertEqual((spec['name'], spec['version']), ('attention', VERSION))
                payload_manifest(plugin)
                for required in ('launch.py', '.mcp.json', 'hooks/hooks.json',
                                 'native-bin/Attention.app/Contents/MacOS/nkc-player', 'native-bin/nkc-language'):
                    self.assertTrue((plugin / required).is_file(), required)

    def test_published_runtime_is_not_stale_after_source_changes(self):
        for folder in ('plugins', 'claude-plugins'):
            with self.subTest(provider=folder):
                plugin = ROOT / folder / 'attention'
                self.assertTrue((plugin / 'payload.json').is_file(), 'Build the GitHub distribution first')
                files = json.loads((plugin / 'payload.json').read_text())['files']
                for source_name, packaged_name in (
                    ('packaging/requirements.txt', 'requirements.txt'),
                    ('packaging/PLUGIN-README.md', 'README.md'),
                ):
                    self.assertEqual((plugin / packaged_name).read_bytes(), (ROOT / source_name).read_bytes(),
                                     'Rebuild the published distribution after changing ' + source_name)
                for name in files:
                    source = ROOT / name
                    if source.is_file() and not name.startswith('native-bin/'):
                        expected = source.read_bytes()
                        if name == 'summary-prompt.txt':
                            expected = expected.replace(b'no-keyboard-code MCP', b'attention MCP')
                        self.assertEqual((plugin / name).read_bytes(), expected,
                                         'Rebuild the published distribution after changing ' + name)


if __name__ == '__main__':
    unittest.main()
