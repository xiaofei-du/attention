"""Local installed-voice inventory shared by short-lived notification workers."""

import fcntl
import hashlib
import json
import os
import platform
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from . import language
from .voice_setup import refresh_voice_inventory

MAX_AGE_SECONDS = 300
ASSET_ROOTS = (
    Path('/System/Library/AssetsV2'), Path('/Library/AssetsV2'),
    Path('/System/Library/Speech/Voices'), Path('/Library/Speech/Voices'),
    Path.home() / 'Library/Speech/Voices',
)


def asset_fingerprint():
    # Inspect only speech asset directory/manifest timestamps, never media or
    # transcript contents. TTL/explicit refresh cover undocumented asset layouts.
    records = [('macOS', platform.mac_ver()[0])]

    def record(path):
        try:
            stat = path.stat()
            records.append((str(path), stat.st_mtime_ns, stat.st_size))
        except OSError:
            records.append((str(path), None))

    for root in ASSET_ROOTS:
        record(root)
        try:
            entries = sorted(root.iterdir())
        except OSError:
            continue
        if root.name == 'AssetsV2':
            entries = [path for path in entries if any(word in path.name.lower()
                       for word in ('voice', 'speech', 'tts', 'vocal'))]
        for entry in entries[:1000]:
            record(entry)
            try:
                children = sorted(entry.iterdir())[:1000]
            except OSError:
                children = []
            for child in children:
                record(child)
                if child.is_dir():
                    record(child / 'Info.plist')
                    record(child / 'AssetData')
    return hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()


def read_inventory():
    # Obtain both kinds once, even if the current preference doesn't filter gender.
    language.prepare_voice_inventory({'voice_gender': 'female'})
    voices = language.installed_voices()
    try:
        metadata = language.installed_voice_metadata()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        return None  # Existing playback fallback handles unavailable gender metadata.
    return {'voices': voices, 'metadata': metadata}


def valid_inventory(value):
    if not isinstance(value, dict):
        return False
    voices, metadata = value.get('voices'), value.get('metadata')
    if not isinstance(voices, dict) or not 0 < len(voices) <= 2000 or not isinstance(metadata, list):
        return False
    if not all(isinstance(name, str) and 0 < len(name) <= 200 and isinstance(code, str)
               and code.isalpha() and 2 <= len(code) <= 3 for name, code in voices.items()):
        return False
    return 0 < len(metadata) <= 2000 and all(
        isinstance(item, dict) and item.get('name') in voices and
        item.get('language') == voices[item['name']] and isinstance(item.get('locale'), str) and
        item.get('gender') in ('male', 'female', 'unknown') for item in metadata)


def cached_inventory(path, fingerprint, allow_stale=False):
    try:
        if path.stat().st_size <= 512 * 1024:
            saved = json.loads(path.read_text())
            age = time.time() - saved['created']
            if (saved.get('version') == 1 and saved.get('fingerprint') == fingerprint and
                    age >= 0 and (allow_stale or age < MAX_AGE_SECONDS) and
                    valid_inventory(saved.get('inventory'))):
                return saved['inventory']
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        pass
    return None


def load_inventory(root, force=False, *, allow_stale=False, nonblocking=False):
    path = root / 'voice-inventory.json'
    fingerprint = asset_fingerprint()
    # Atomic cache replacement lets playback use unchanged voices without
    # waiting for a slow macOS enumeration already running in another process.
    if not force:
        saved = cached_inventory(path, fingerprint, allow_stale)
        if saved is not None:
            return saved
    with (root / 'voice-inventory.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0))
        except BlockingIOError:
            return None
        if not force:
            saved = cached_inventory(path, fingerprint, allow_stale)
            if saved is not None:
                return saved
        # Keep a last-known-good cache readable during refresh, but never keep
        # an invalid snapshot after macOS reports no usable inventory.
        try:
            inventory = read_inventory()
        except Exception:
            path.unlink(missing_ok=True)
            raise
        if inventory is not None and valid_inventory(inventory):
            fd, temporary = tempfile.mkstemp(prefix='voice-inventory-', dir=str(root))
            try:
                with os.fdopen(fd, 'w') as output:
                    json.dump({'version': 1, 'created': time.time(), 'fingerprint': fingerprint,
                               'inventory': inventory}, output, ensure_ascii=False)
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        else:
            path.unlink(missing_ok=True)
        return inventory


def invalidate_voice_inventory(root):
    root = Path(root)
    with (root / 'voice-inventory.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        (root / 'voice-inventory.json').unlink(missing_ok=True)


@contextmanager
def voice_inventory(root, force=False, *, allow_stale=False):
    refresh_voice_inventory()
    try:
        snapshot = load_inventory(Path(root), force=force, allow_stale=allow_stale)
        # Clear the temporary query memoization before switching the source.
        refresh_voice_inventory()
        language._inventory_snapshot = snapshot
        yield
    finally:
        refresh_voice_inventory()
