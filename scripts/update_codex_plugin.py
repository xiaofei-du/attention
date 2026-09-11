#!/usr/bin/env python3
"""Local marketplace upgrade: preserve launchers referenced by running tasks."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nkc.payload import payload_manifest


@contextmanager
def preserve_launchers(cache_root):
    """Restore only removed, validated versions; never overwrite the current install."""
    cache_root = Path(cache_root)
    if cache_root.is_symlink():
        raise ValueError('Refusing a symlinked plugin cache')
    with tempfile.TemporaryDirectory(prefix='attention-upgrade-') as temporary:
        backup = Path(temporary)
        saved = []
        for version in sorted(cache_root.iterdir()) if cache_root.exists() else []:
            if version.name.startswith('.'):
                continue
            if version.is_symlink() or not version.is_dir() or any(p.is_symlink() for p in version.rglob('*')):
                raise ValueError('Refusing an unexpected plugin cache entry')
            manifest = json.loads((version / '.codex-plugin/plugin.json').read_text())
            if manifest.get('name') != 'attention' or manifest.get('version') != version.name:
                raise ValueError('Unexpected cached Attention version')
            expected = payload_manifest(version)
            snapshot = backup / version.name
            shutil.copytree(version, snapshot, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.DS_Store'))
            if payload_manifest(snapshot) != expected:
                raise ValueError('Plugin cache changed during snapshot')
            saved.append((version.name, expected))
        try:
            yield
        finally:
            for name, expected in saved:
                target = cache_root / name
                if target.exists() or target.is_symlink():
                    continue  # Native installer owns every existing version.
                cache_root.mkdir(parents=True, exist_ok=True)
                stage = Path(tempfile.mkdtemp(prefix='.attention-restore-', dir=cache_root))
                try:
                    shutil.copytree(backup / name, stage, dirs_exist_ok=True)
                    if payload_manifest(stage) != expected:
                        raise ValueError('Cached launcher restore failed verification')
                    # A concurrent installer may have recreated this version.
                    if not target.exists() and not target.is_symlink():
                        os.rename(stage, target)
                finally:
                    if stage.exists():
                        shutil.rmtree(stage)


def main():
    codex_home = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
    cache = codex_home / 'plugins/cache/attention-marketplace/attention'
    with preserve_launchers(cache):
        subprocess.run(['codex', 'plugin', 'add', 'attention@attention-marketplace', '--json'], check=True)


if __name__ == '__main__':
    main()
