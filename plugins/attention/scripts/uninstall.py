#!/usr/bin/env python3
"""Completely remove Attention from both clients and erase all personal data.

Standalone, Python 3.11+ standard library only; it also works after native plugin
removal. Finish active tasks and quit both clients before running from Terminal.
"""
import argparse
import ctypes
import errno
import hashlib
import json
import os
import shutil
import sqlite3
import struct
import subprocess
import sys
import time
import tomllib
from pathlib import Path

PLUGIN = 'attention@xiaofei-du'
MARKET = 'xiaofei-du'
DATA_ENTRIES = {'state', 'r', 'e', 'notices', 'setup.lock', 'dependencies.lock', '.uninstall.json', '.uninstall.tmp'}


def checked_path(path):
    path = Path(os.path.abspath(Path(path).expanduser()))
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError('Refusing symlinked path: ' + str(part))
    return path


def read_object(path, toml=False):
    checked_path(path)
    if not path.exists():
        return {}
    value = tomllib.loads(path.read_text()) if toml else json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError('Unsupported metadata in ' + str(path))
    return value


def mapping(value, label):
    if not isinstance(value, dict):
        raise ValueError('Unsupported ' + label)
    return value


def pending_scopes(root):
    pending = read_object(root / '.uninstall.json')
    if not pending:
        return []
    if pending.get('application') != 'attention-uninstall-v1' or not isinstance(pending.get('scope_settings'), list):
        raise ValueError('Invalid uninstall progress record')
    paths = []
    for item in pending['scope_settings']:
        if not isinstance(item, str) or not Path(item).is_absolute():
            raise ValueError('Invalid saved scope settings path')
        path = checked_path(item)
        if path.name not in ('settings.json', 'settings.local.json'):
            raise ValueError('Invalid saved scope settings filename')
        paths.append(path)
    return paths


def validate_data(root):
    checked_path(root)
    if root in (Path('/'), Path.home(), Path.home() / 'Library', Path.home() / 'Library/Application Support'):
        raise ValueError('Refusing unsafe data root: ' + str(root))
    if not root.exists():
        return
    if not root.is_dir() or set(p.name for p in root.iterdir()) - DATA_ENTRIES:
        raise ValueError('Unexpected files in data root; refusing to erase ' + str(root))
    # Identify the app, not just SQLite: custom roots may be mistyped. Read a
    # immutable schema view so preview never creates journal/SHM files.
    children = set(p.name for p in root.iterdir())
    database = root / 'state/queue.sqlite3'
    identified = False
    if database.exists():
        checked_path(database)
        with sqlite3.connect(database.as_uri() + '?mode=ro&immutable=1', uri=True) as db:
            required = {
                'settings': {'id', 'name', 'voice', 'rate', 'start', 'global_voice_enabled'},
                'jobs': {'id', 'provider', 'session_id', 'turn_id', 'body', 'status'},
                'turn_summaries': {'provider', 'session_id', 'turn_id', 'token', 'body'},
            }
            identified = all(columns <= {row[1] for row in db.execute('PRAGMA table_info(' + table + ')')}
                             for table, columns in required.items())
        if not identified:
            raise ValueError('Database is not an Attention database; refusing to erase ' + str(root))
    elif (root / 'r').is_dir():
        checked_path(root / 'r')
        for manifest in (root / 'r').glob('*/payload.json'):
            checked_path(manifest)
            files = read_object(manifest).get('files', {})
            if not isinstance(files, dict) or not {'attention.py', 'nkc/store.py', 'nkc/runtime.py'} <= files.keys():
                continue
            valid = True
            for relative, digest in files.items():
                name = Path(relative)
                if name.is_absolute() or '..' in name.parts or not isinstance(digest, str):
                    valid = False
                    break
                source = checked_path(manifest.parent / name)
                if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != digest:
                    valid = False
                    break
            if valid:
                identified = True
                break
    elif children - {'.uninstall.json', '.uninstall.tmp'} == {'notices'}:
        checked_path(root / 'notices')
        notices = list((root / 'notices').iterdir())
        identified = bool(notices) and all(p.is_file() and not p.is_symlink() and
                                          p.read_text().startswith('Attention!') for p in notices)
    if children == {'.uninstall.json'} and pending_scopes(root):
        identified = True
    if children and not identified:
        raise ValueError('Cannot identify Attention data in ' + str(root))


def plan(root, codex, claude):
    root, codex, claude = (checked_path(p) for p in (root, codex, claude))
    validate_data(root)
    for left, right in ((root, codex), (root, claude), (codex, claude)):
        if left == right or left in right.parents or right in left.parents:
            raise ValueError('Data and client profiles must be separate directories')
    config = read_object(codex / 'config.toml', toml=True)
    codex_plugins = mapping(config.get('plugins', {}), 'Codex plugin settings')
    installed = read_object(claude / 'plugins/installed_plugins.json')
    claude_plugins = mapping(installed.get('plugins', {}), 'Claude plugin registry')
    claude_settings = read_object(claude / 'settings.json')
    commands = []
    scope_settings = list(dict.fromkeys([claude / 'settings.json', *pending_scopes(root)]))
    if PLUGIN in codex_plugins:
        commands.append((['codex', 'plugin', 'remove', PLUGIN], codex))
    entries = claude_plugins.get(PLUGIN, [])
    if not isinstance(entries, list):
        raise ValueError('Unsupported Claude Attention installation records')
    for entry in entries:
        if not isinstance(entry, dict) or entry.get('scope') not in ('user', 'project', 'local'):
            raise ValueError('Unsupported Claude installation scope; remove it natively first')
        scope = entry['scope']
        cwd = claude if scope == 'user' else checked_path(entry.get('projectPath', ''))
        if scope != 'user' and (not entry.get('projectPath') or not cwd.is_dir()):
            raise ValueError('Missing Claude project; restore its path or uninstall that scope first')
        if scope != 'user':
            settings_path = cwd / '.claude' / ('settings.local.json' if scope == 'local' else 'settings.json')
            read_object(settings_path)
            scope_settings.append(settings_path)
        commands.append((['claude', 'plugin', 'uninstall', PLUGIN, '--scope', scope], cwd))
    enabled = mapping(claude_settings.get('enabledPlugins', {}), 'Claude plugin settings')
    if PLUGIN in enabled and not any(e['scope'] == 'user' for e in entries):
        raise ValueError('Claude settings and plugin registry disagree; repair native uninstall first')

    targets = [codex / 'plugins/cache' / MARKET / 'attention',
               claude / 'plugins/cache' / MARKET / 'attention',
               claude / 'plugins/data' / PLUGIN]
    retained = []
    markets = mapping(config.get('marketplaces', {}), 'Codex marketplaces')
    known = read_object(claude / 'plugins/known_marketplaces.json')
    for provider, registry, plugins, path in (
        ('codex', markets, codex_plugins, codex / '.tmp/marketplaces' / MARKET),
        ('claude', known, claude_plugins, claude / 'plugins/marketplaces' / MARKET),
    ):
        entry = registry.get(MARKET)
        other_plugins = any(k != PLUGIN and k.endswith('@' + MARKET) for k in plugins)
        if other_plugins:
            retained.append(provider + ': marketplace is shared with other plugins')
            continue
        if entry is not None:
            if not isinstance(entry, dict):
                raise ValueError('Unsupported marketplace record')
            source = entry.get('source')
            own_source = (source in ('https://github.com/xiaofei-du/attention.git',
                                     'https://github.com/xiaofei-du/attention') if provider == 'codex'
                          else isinstance(source, dict) and source.get('repo') == 'xiaofei-du/attention')
            if not own_source:
                retained.append(provider + ': marketplace has a different/local source; source checkout preserved')
                continue
            if provider == 'claude' and Path(entry.get('installLocation', '')) != path:
                raise ValueError('Unexpected Claude marketplace cache path')
            commands.append(([provider, 'plugin', 'marketplace', 'remove', MARKET],
                             codex if provider == 'codex' else claude))
        # Orphan clone after native removal, if present. Do not infer ownership
        # merely from a marketplace directory name.
        if path.exists():
            catalog = path / ('.agents/plugins/marketplace.json' if provider == 'codex'
                              else '.claude-plugin/marketplace.json')
            content = read_object(catalog)
            catalog_plugins = content.get('plugins')
            if (content.get('name') == MARKET and isinstance(catalog_plugins, list)
                    and catalog_plugins and all(isinstance(p, dict) and p.get('name') == 'attention'
                                                for p in catalog_plugins)):
                targets.append(path)
            elif entry is not None:
                raise ValueError('Marketplace contains unexpected plugins; refusing whole-source removal')
            else:
                raise ValueError('Cannot identify orphan marketplace: ' + str(path))
    for target in targets:
        checked_path(target)
        if target.exists() and not target.is_dir():
            raise ValueError('Unexpected cleanup target: ' + str(target))
    # Legacy hooks can revive a different database. Do not silently remove old
    # user configuration or guess which source checkout/data directory it owns.
    for home, name in ((codex, 'hooks.json'), (claude, 'settings.json')):
        hooks = read_object(home / name).get('hooks', {})
        if 'no-keyboard-code:' in json.dumps(hooks):
            raise ValueError('Legacy no-keyboard-code hooks remain; migrate/remove those hooks first')
    return {'data': root, 'codex': codex, 'claude': claude, 'commands': commands,
            'targets': targets, 'retained': retained, 'scope_settings': scope_settings}


def process_argv(pid):
    """Read exact argument boundaries; ps display text is insufficient for paths with spaces."""
    if sys.platform == 'darwin':
        libc = ctypes.CDLL(None, use_errno=True)
        mib = (ctypes.c_int * 3)(1, 49, pid)  # CTL_KERN, KERN_PROCARGS2
        # Darwin does not support the usual NULL-buffer size query here.
        size = ctypes.c_size_t(os.sysconf('SC_ARG_MAX'))
        buffer = ctypes.create_string_buffer(size.value)
        if libc.sysctl(mib, 3, buffer, ctypes.byref(size), None, 0):
            error = ctypes.get_errno()
            if error in (errno.ESRCH, errno.EINVAL):
                return []
            raise OSError(error, 'Cannot inspect Attention process')
        raw = buffer.raw[:size.value]
        argc = struct.unpack_from('i', raw)[0]
        start = raw.index(b'\0', 4) + 1
        while start < len(raw) and raw[start] == 0:
            start += 1
        return [os.fsdecode(value) for value in raw[start:].split(b'\0')[:argc]]
    try:
        return [os.fsdecode(value) for value in Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0') if value]
    except FileNotFoundError:
        return []


def process_start(pid):
    return subprocess.run(['/bin/ps', '-p', str(pid), '-o', 'lstart='], capture_output=True,
                          text=True, timeout=5).stdout.strip()


def processes(roots):
    output = subprocess.run(['/bin/ps', '-ww', '-axo', 'pid=,uid=,command='], capture_output=True,
                            text=True, check=True, timeout=10).stdout
    result = []
    for line in output.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) != 3 or int(parts[1]) != os.getuid() or int(parts[0]) == os.getpid():
            continue
        if not any(str(root) in parts[2] for root in roots):
            continue
        pid = int(parts[0])
        argv = process_argv(pid)
        # Exact path arguments, never a matching substring in a prompt or shell
        # command. Ancestor uv launchers are not killed along with their children.
        owned = any(Path(arg).is_absolute() and any(Path(arg) == root or root in Path(arg).parents
                                                    for root in roots) for arg in argv)
        if owned and not any(Path(arg).name == 'uninstall.py' for arg in argv):
            result.append({'pid': pid, 'argv': argv, 'start': process_start(pid)})
    return result


def worker(proc, root):
    argv = proc['argv']
    return (len(argv) >= 5 and argv[-1] in ('worker', 'warm-voices')
            and argv[-3:-1] == ['--state-dir', str(root / 'state')]
            and any(Path(arg).name == 'run.py' and root in Path(arg).parents for arg in argv))


def stop_workers(found, root):
    workers = [p for p in found if worker(p, root)]
    # A native player is allowed only alongside the worker that owns playback.
    # It exits cooperatively with the worker, restoring ducking and temp files.
    def player(proc):
        return any(Path(arg).name == 'nkc-player' and root in Path(arg).parents for arg in proc['argv'])
    blocking = [p for p in found if not worker(p, root) and not (workers and player(p))]
    if blocking:
        raise RuntimeError('Close Codex and Claude Code, then retry from Terminal. Active Attention PIDs: ' +
                           ', '.join(str(p['pid']) for p in blocking))
    if not found:
        return
    database = checked_path(root / 'state/queue.sqlite3')
    # No Store import: uninstall must not bootstrap dependencies or recreate a
    # missing database. Existing workers observe the same cancellation switch.
    with sqlite3.connect(database.as_uri() + '?mode=rw', uri=True, timeout=5) as db:
        db.execute('UPDATE settings SET global_voice_enabled=0 WHERE id=1')
        db.execute("UPDATE jobs SET status='cancelled',body='' WHERE status IN ('pending','speaking')")
        db.execute('UPDATE turn_summaries SET body=NULL')
    deadline = time.monotonic() + 5
    while found and time.monotonic() < deadline:
        found = [p for p in found if process_start(p['pid']) == p['start'] and process_argv(p['pid']) == p['argv']]
        if found:
            time.sleep(0.05)
    if found:
        raise RuntimeError('Attention workers did not stop; speech is off and data was preserved. Quit them and retry.')


def execute(removal):
    root = removal['data']
    roots = [root, *removal['targets']]
    # Preflight every dependency before the first native mutation.
    for command, _ in removal['commands']:
        if not shutil.which(command[0]):
            raise RuntimeError('Required client command is missing: ' + command[0])
    stop_workers(processes(roots), root)
    # Keep verification paths through a partially successful native uninstall.
    # Otherwise a retry could forget a project once its registry row disappears.
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    progress = checked_path(root / '.uninstall.tmp')
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
    with os.fdopen(os.open(progress, flags, 0o600), 'w') as file:
        json.dump({'application': 'attention-uninstall-v1',
                   'scope_settings': [str(p) for p in removal['scope_settings']]}, file)
        file.flush()
        os.fsync(file.fileno())
    os.replace(progress, checked_path(root / '.uninstall.json'))
    env = dict(os.environ, CODEX_HOME=str(removal['codex']), CLAUDE_CONFIG_DIR=str(removal['claude']))
    for command, cwd in removal['commands']:
        result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise RuntimeError('Native uninstall failed: ' + ' '.join(command) +
                               '. Shared data was preserved; retry after fixing the client.')
    # Re-read native registrations, never trust an exit status alone. Partial
    # removal is safe to retry; shared state is not erased while either remains.
    remaining = plan(root, removal['codex'], removal['claude'])
    if remaining['commands'] or any(PLUGIN in mapping(read_object(p).get('enabledPlugins', {}),
                                                     'Claude plugin settings') for p in removal['scope_settings']):
        raise RuntimeError('Attention is still registered in a client; shared data was preserved')
    if processes(roots):
        raise RuntimeError('Attention restarted during uninstall. Close both clients and retry.')
    for target in [*removal['targets'], root]:
        checked_path(target)
        if target == root:
            validate_data(root)
        if target.exists():
            if not shutil.rmtree.avoids_symlink_attacks:
                raise RuntimeError('This Python cannot safely remove directory trees')
            shutil.rmtree(target)
    leftovers = [str(p) for p in roots if p.exists() or p.is_symlink()]
    if leftovers or processes(roots):
        raise RuntimeError('Uninstall incomplete; a client recreated Attention files/processes. Close it and retry.')
    return {'status': 'removed', 'removed': [str(p) for p in roots], 'retained_shared_sources': removal['retained']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--yes', action='store_true', help='Erase settings, imported audio and all Attention data')
    parser.add_argument('--dry-run', action='store_true', help='List exact targets without changing anything')
    parser.add_argument('--data-dir', type=Path, default=os.environ.get('ATTENTION_DATA_DIR',
                        str(Path.home() / 'Library/Application Support/Attention') if sys.platform == 'darwin' else
                        str(Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'attention')))
    args = parser.parse_args()
    if sys.platform not in ('darwin', 'linux'):
        parser.error('This cleanup command supports macOS and Linux only')
    try:
        removal = plan(args.data_dir, os.environ.get('CODEX_HOME', str(Path.home() / '.codex')),
                       os.environ.get('CLAUDE_CONFIG_DIR', str(Path.home() / '.claude')))
        if args.dry_run or not args.yes:
            print(json.dumps({'status': 'preview', 'erase': ['settings', 'custom audio', 'queue', 'logs', 'runtimes', 'dependencies'],
                              'paths': [str(p) for p in [*removal['targets'], removal['data']]],
                              'commands': [{'argv': cmd, 'cwd': str(cwd)} for cmd, cwd in removal['commands']],
                              'retained_shared_sources': removal['retained']}, indent=2))
            if not args.dry_run:
                print('Close both clients, then rerun with --yes to delete all listed Attention data.', file=sys.stderr)
                return 2
            return 0
        print(json.dumps(execute(removal), indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error, subprocess.SubprocessError) as error:
        print('Attention uninstall incomplete: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
