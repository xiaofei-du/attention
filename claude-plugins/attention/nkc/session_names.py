"""Read current local session titles without invoking an agent or changing its data."""

import json
import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from .summary import spoken_session_name


def hook_source(provider, event):
    source = {}
    values = [('transcript_path', event.get('transcript_path'))]
    if provider == 'codex':
        values.append(('config_home', os.environ.get('CODEX_HOME') or str(Path.home() / '.codex')))
    for key, value in values:
        if isinstance(value, str) and value and len(value) <= 4096:
            try:
                source[key] = str(Path(value).expanduser().resolve())
            except (OSError, ValueError, RuntimeError):
                pass
    return source


def _codex_name(session_id, home):
    paths = []
    for path in home.glob('state_*.sqlite'):
        version = re.fullmatch(r'state_(\d+)\.sqlite', path.name)
        if version and path.is_file():
            paths.append((int(version[1]), path))
    for _, path in sorted(paths, reverse=True)[:4]:
        try:
            with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=0.1)) as db:
                columns = {row[1] for row in db.execute('PRAGMA table_info(threads)')}
                if 'id' not in columns:
                    continue
                fields = [key for key in ('name', 'title') if key in columns]
                if not fields:
                    continue
                row = db.execute('SELECT ' + ','.join(fields) + ' FROM threads WHERE id=?',
                                 (session_id,)).fetchone()
                if row is not None:
                    # In the current app name is the display name; title may be
                    # the first-message preview. Older schemas only have title.
                    for value in row:
                        if value:
                            return spoken_session_name(value)
                    return ''
        except sqlite3.Error:
            continue
    return ''


def _reverse_records(path, max_scan=64 * 1024 * 1024):
    """Yield complete small JSONL records newest-first, with bounded memory/I/O."""
    with path.open('rb') as stream:
        position = stream.seek(0, os.SEEK_END)
        floor = max(0, position - max_scan)
        carry = b''
        oversized = False
        at_end = True
        while position > floor:
            count = min(65536, position - floor)
            position -= count
            stream.seek(position)
            parts = stream.read(count).split(b'\n')
            if len(parts) == 1:
                carry = parts[0] + carry
                if len(carry) > 16384:
                    carry, oversized = b'', True
                continue
            # The first suffix is an unfinished append (or empty after the last
            # newline). Never consume it as a committed metadata record.
            joined = parts[-1] + carry
            if not at_end and not oversized and len(joined) <= 16384:
                yield joined
            at_end = False
            for line in reversed(parts[1:-1]):
                if len(line) <= 16384:
                    yield line
            carry = parts[0]
            oversized = len(carry) > 16384
            if oversized:
                carry = b''
        if floor:
            # An older custom title might still override a recent AI title.
            raise ValueError('Session title scan limit reached')
        if not at_end and not oversized:
            yield carry


def _claude_name(session_id, path):
    if not path.is_file():
        return ''
    ai_title = None
    custom_cleared = False
    for line in _reverse_records(path):
        if b'custom-title' not in line and b'ai-title' not in line:
            continue
        try:
            record = json.loads(line)
        except (ValueError, UnicodeError):
            continue
        if not isinstance(record, dict) or record.get('sessionId') != session_id:
            continue
        if record.get('type') == 'ai-title' and ai_title is None:
            ai_title = spoken_session_name(record.get('aiTitle'))
        elif record.get('type') == 'custom-title' and not custom_cleared:
            value = record.get('customTitle')
            if value != '':
                return spoken_session_name(value)
            custom_cleared = True
        if custom_cleared and ai_title is not None:
            return ai_title
    return ai_title or ''


def resolve_session_name(provider, session_id, source=None):
    source = source or {}
    try:
        if provider == 'codex':
            home = source.get('config_home') or os.environ.get('CODEX_HOME') or str(Path.home() / '.codex')
            return _codex_name(session_id, Path(home).expanduser())
        if provider == 'claude-code' and source.get('transcript_path'):
            return _claude_name(session_id, Path(source['transcript_path']))
    except (OSError, ValueError, sqlite3.Error):
        pass  # Missing, locked, incompatible, or incomplete metadata must not lose speech.
    return ''
