#!/usr/bin/env python3
"""Completely remove Attention from both clients and erase all personal data.

Standalone, Python 3.11+ standard library only; it also works after native plugin
removal. Finish active tasks and quit both clients before running from Terminal.
"""
import argparse
import base64
import contextlib
import csv
import ctypes
import errno
import hashlib
import json
import os
import re
import stat
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


# This inventory is an ownership boundary, not authentication of publisher code.
# Unknown files cause refusal before native clients can remove their caches.
STATE_FILES = {'queue.sqlite3', 'queue.sqlite3-wal', 'queue.sqlite3-shm',
               'queue.sqlite3-journal', 'worker.log', 'speaker.lock',
               'voice-inventory.json', 'voice-inventory.lock'}


def identity(info):
    return (info.st_dev, info.st_ino, info.st_uid, stat.S_IFMT(info.st_mode))


def inventory(root):
    """Never follow directory links or cross filesystems while enumerating."""
    if not root.exists():
        return {}
    device = root.lstat().st_dev
    result = {}
    def visit(path):
        info = path.lstat()
        if info.st_uid != os.geteuid():
            raise ValueError('Cleanup path has a different owner: ' + str(path))
        if info.st_dev != device:
            raise ValueError('Refusing to cross a filesystem boundary: ' + str(path))
        if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)):
            raise ValueError('Unexpected file type: ' + str(path))
        if stat.S_ISDIR(info.st_mode) and info.st_mode & 0o022:
            raise ValueError('Cleanup path is writable by other users: ' + str(path))
        result[path.relative_to(root).as_posix()] = identity(info)
        if stat.S_ISDIR(info.st_mode):
            for child in path.iterdir():
                visit(child)
    visit(root)
    return result


def file_digest(path, algorithm='sha256'):
    checked_path(path)
    with path.open('rb') as file:
        return hashlib.file_digest(file, algorithm).digest()


def payload_files(bundle, installed=False):
    files = read_object(bundle / 'payload.json').get('files', {})
    if not isinstance(files, dict) or not {'attention.py', 'nkc/store.py', 'nkc/runtime.py'} <= files.keys():
        raise ValueError('Cannot identify Attention payload: ' + str(bundle))
    allowed = {'payload.json'}
    for name, digest in files.items():
        relative = Path(name)
        if (not name or relative.is_absolute() or '..' in relative.parts or
                not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest)):
            raise ValueError('Invalid Attention payload entry')
        if file_digest(bundle / relative).hex() != digest:
            raise ValueError('Modified Attention payload file; preserved: ' + str(bundle / relative))
        allowed.add(name)
    if installed:
        allowed.add('attention')  # Generated local command wrapper, never executed here.
    else:
        allowed.update({'README.md', '.mcp.json', '.codex-plugin/plugin.json',
                        '.claude-plugin/plugin.json', 'hooks/hooks.json'})
    return allowed


def environment_files(environment):
    saved = read_object(environment / '.verified')
    if not {'requirements', 'python', 'platform', 'architecture'} <= saved.keys():
        raise ValueError('Cannot identify Attention Python environment: ' + str(environment))
    cfg = checked_path(environment / 'pyvenv.cfg').read_text()
    if 'include-system-site-packages = false' not in cfg:
        raise ValueError('Unexpected Python environment configuration')
    allowed = {'.verified', 'pyvenv.cfg', '.lock', '.gitignore', 'CACHEDIR.TAG'}
    allowed.update('bin/' + name for name in ('python', 'python3', 'python3.11', 'python3.12', 'python3.13',
        'activate', 'activate.csh', 'activate.fish', 'activate.nu', 'activate.ps1',
        'activate.bat', 'activate.xsh', 'activate_this.py', 'deactivate.bat', 'pydoc.bat'))
    packages = list(environment.glob('lib/python*/site-packages'))
    if len(packages) != 1:
        raise ValueError('Cannot identify Python site-packages')
    package_root = checked_path(packages[0])
    for name in ('_virtualenv.pth', '_virtualenv.py'):
        allowed.add((package_root / name).relative_to(environment).as_posix())
    records = list(package_root.glob('*.dist-info/RECORD'))
    if not records:
        raise ValueError('Python environment has no installed-file records')
    for record in records:
        checked_path(record)
        with record.open(newline='') as file:
            for name, digest, size in csv.reader(file):
                target = Path(os.path.abspath(package_root / name))
                if environment not in target.parents:
                    raise ValueError('Python file record escapes its environment')
                relative = target.relative_to(environment).as_posix()
                if digest:
                    algorithm, encoded = digest.split('=', 1)
                    if algorithm not in ('sha256', 'sha384', 'sha512'):
                        raise ValueError('Unsupported Python file digest')
                    actual = base64.urlsafe_b64encode(file_digest(target, algorithm)).rstrip(b'=').decode()
                    if actual != encoded:
                        raise ValueError('Modified Python environment file; preserved: ' + str(target))
                elif target != record:
                    # Bytecode is admitted below only when its source is owned.
                    if target.suffix == '.pyc':
                        continue
                    raise ValueError('Unverifiable Python file record: ' + str(target))
                allowed.add(relative)
    return allowed


def allow_bytecode(names, allowed):
    for name in names:
        relative = Path(name)
        match = re.fullmatch(r'(.+)\.cpython-\d+(?:\.opt-[12])?\.pyc', relative.name)
        if relative.parent.name == '__pycache__' and match:
            source = relative.parent.parent / (match[1] + '.py')
            if source.as_posix() in allowed:
                allowed.add(name)


def owned_inventory(root, kind):
    names = inventory(root)
    if not names:
        return names
    allowed = set()
    empty_dirs = {'.'}
    if kind == 'data':
        allowed.update({'setup.lock', 'dependencies.lock', '.uninstall.json', '.uninstall.tmp'})
        allowed.update('state/' + name for name in STATE_FILES)
        empty_dirs.update({'state', 'state/opening-audio', 'r', 'e', 'notices'})
        database = root / 'state/queue.sqlite3'
        if database.exists() and database.lstat().st_nlink != 1:
            raise ValueError('Refusing a hard-linked Attention database')
        for name in names:
            relative = Path(name)
            if relative.parent.as_posix() == 'state/opening-audio' and re.fullmatch(r'[0-9a-f]{64}\.aiff', relative.name):
                if file_digest(root / name).hex() == relative.stem:
                    allowed.add(name)
            elif relative.parent.as_posix() == 'notices' and (root / name).is_file():
                checked_path(root / name)
                if (re.fullmatch('[0-9a-f]{16}', relative.name) and (root / name).read_text().startswith('Attention!')):
                    allowed.add(name)
        for folder, loader in [('r', lambda p: payload_files(p, installed=True)), ('e', environment_files)]:
            directory = root / folder
            if directory.exists():
                checked_path(directory)
                for version in directory.iterdir():
                    checked_path(version)
                    if not version.is_dir():
                        raise ValueError('Unknown Attention version entry: ' + str(version))
                    prefix = version.relative_to(root).as_posix()
                    empty_dirs.add(prefix)
                    if any(version.iterdir()):
                        allowed.update(prefix + '/' + name for name in loader(version))
    elif kind == 'cache':
        for version in root.iterdir():
            checked_path(version)
            if not version.is_dir():
                raise ValueError('Unknown plugin cache entry: ' + str(version))
            empty_dirs.add(version.name)
            if any(version.iterdir()):
                allowed.update(version.name + '/' + name for name in payload_files(version))
    elif kind == 'marketplace':
        # Git only reads its index. Disable filesystem-monitor commands and ignore
        # inherited Git overrides; no checkout, filters, hooks or project code.
        env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
        result = subprocess.run(['/usr/bin/git', '--no-optional-locks', '-c', 'core.fsmonitor=false',
                                 '--git-dir', str(root / '.git'), 'ls-files', '--stage', '-z'],
                                env=env, capture_output=True, timeout=10)
        if result.returncode:
            raise ValueError('Cannot inventory marketplace clone; preserved: ' + str(root))
        for entry in result.stdout.decode().rstrip('\0').split('\0'):
            metadata, name = entry.split('\t', 1)
            mode, digest, stage = metadata.split()
            relative = Path(name)
            if relative.is_absolute() or '..' in relative.parts or mode not in ('100644', '100755') or stage != '0':
                raise ValueError('Unsupported marketplace index entry; preserved')
            source = checked_path(root / name)
            if source.exists():
                content = source.read_bytes()
                actual = hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()
                if actual != digest:
                    raise ValueError('Modified marketplace file; preserved: ' + str(source))
            allowed.add(name)
        for name in names:
            if re.fullmatch(r'\.git/(?:HEAD|config|description|index|packed-refs|shallow|FETCH_HEAD|ORIG_HEAD|'
                            r'info/exclude|hooks/[\w.-]+\.sample|objects/[0-9a-f]{2}/[0-9a-f]{38}|'
                            r'objects/pack/pack-[0-9a-f]{40}\.(?:pack|idx|rev)|'
                            r'(?:refs|logs/refs)/(?:heads|remotes|tags)/[\w./-]+|logs/HEAD)', name):
                allowed.add(name)
        empty_dirs.update({'.git/hooks', '.git/info', '.git/branches', '.git/objects/info',
                           '.git/objects/pack', '.git/refs', '.git/refs/heads', '.git/refs/remotes',
                           '.git/refs/tags', '.git/logs', '.git/logs/refs',
                           '.git/logs/refs/heads', '.git/logs/refs/remotes'})
    # Native Claude data is not used by Attention; only an empty directory is owned.
    allow_bytecode(names, allowed)
    directories = set(empty_dirs)
    for name in allowed:
        directories.update(p.as_posix() for p in Path(name).parents)
    for name, info in names.items():
        if info[3] == stat.S_IFDIR:
            known = name in directories
        else:
            known = name in allowed
            if info[3] == stat.S_IFLNK:
                known = known and bool(re.fullmatch(r'e/[^/]+/bin/python(?:3(?:\.\d+)?)?', name))
        if not known:
            raise ValueError('Unknown file or directory; nothing will be erased: ' + str(root / name))
    return names


@contextlib.contextmanager
def directory_fd(path):
    """Anchor every component from / without following a replacement symlink."""
    descriptor = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor
    finally:
        os.close(descriptor)


def remove_inventory(root, expected):
    """Delete only preflighted names; rmdir preserves anything added afterwards."""
    if not expected:
        return
    children = {}
    for relative in expected:
        if relative != '.':
            children.setdefault(Path(relative).parent.as_posix(), []).append(relative)
    with directory_fd(root.parent) as parent:
        if identity(os.stat(root.name, dir_fd=parent, follow_symlinks=False)) != expected['.']:
            raise RuntimeError('Cleanup directory was replaced: ' + str(root))
        def remove(name, parent_fd, relative):
            info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if identity(info) != expected[relative]:
                raise RuntimeError('Cleanup entry changed: ' + str(root / relative))
            if stat.S_ISDIR(info.st_mode):
                descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
                try:
                    if identity(os.fstat(descriptor)) != expected[relative]:
                        raise RuntimeError('Cleanup directory changed')
                    for child in children.get(relative, []):
                        remove(Path(child).name, descriptor, child)
                    if identity(os.stat(name, dir_fd=parent_fd, follow_symlinks=False)) != expected[relative]:
                        raise RuntimeError('Cleanup directory changed')
                    os.rmdir(name, dir_fd=parent_fd)
                finally:
                    os.close(descriptor)
            else:
                os.unlink(name, dir_fd=parent_fd)
        remove(root.name, parent, '.')


def verify_identities(removal):
    for path, expected in removal['identities'].items():
        actual = identity(Path(path).lstat()) if Path(path).exists() else None
        if actual != expected:
            raise RuntimeError('Installation directory changed after preview: ' + path)


def plan(root, codex, claude):
    if os.geteuid() == 0 or os.getuid() != os.geteuid():
        raise ValueError('Do not run Attention uninstall with sudo/root or elevated privileges')
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
    kinds = {root: 'data', targets[0]: 'cache', targets[1]: 'cache', targets[2]: 'native-data'}
    kinds.update({path: 'marketplace' for path in targets[3:]})
    snapshots = {path: owned_inventory(path, kind) for path, kind in kinds.items()}
    identities = {str(path / name): info for path, entries in snapshots.items()
                  for name, info in entries.items() if info[3] == stat.S_IFDIR}
    for path in kinds:
        if not path.exists():
            identities[str(path)] = None
    return {'data': root, 'codex': codex, 'claude': claude, 'commands': commands,
            'identities': identities, 'kinds': kinds,
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
    output = subprocess.run(['/bin/ps', '-ww', '-axo', 'pid=,ppid=,uid=,command='], capture_output=True,
                            text=True, check=True, timeout=10).stdout
    rows = [line.strip().split(None, 3) for line in output.splitlines()]
    parents = {int(row[0]): int(row[1]) for row in rows if len(row) == 4}
    ancestors = set()
    parent = os.getppid()
    while parent > 1 and parent not in ancestors:
        ancestors.add(parent)
        parent = parents.get(parent, 0)
    result = []
    for parts in rows:
        if len(parts) != 4 or int(parts[2]) != os.getuid() or int(parts[0]) == os.getpid():
            continue
        if not any(str(root) in parts[3] for root in roots):
            continue
        pid = int(parts[0])
        argv = process_argv(pid)
        # A shell launching this very uninstaller can carry --data-dir. Do not
        # mistake that argument for an active client; unrelated shells still block.
        if pid in ancestors and argv and Path(argv[0]).name in ('bash', 'sh'):
            continue
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
    if os.geteuid() == 0 or os.getuid() != os.geteuid():
        raise ValueError('Do not run Attention uninstall with sudo/root or elevated privileges')
    verify_identities(removal)
    for path, kind in removal['kinds'].items():
        owned_inventory(path, kind)
    root = removal['data']
    roots = [root, *removal['targets']]
    # Preflight every dependency before the first native mutation.
    for command, _ in removal['commands']:
        if not shutil.which(command[0]):
            raise RuntimeError('Required client command is missing: ' + command[0])
    stop_workers(processes(roots), root)
    # Keep verification paths through a partially successful native uninstall.
    # Otherwise a retry could forget a project once its registry row disappears.
    expected_root = removal['identities'][str(root)]
    if expected_root is None:
        # Refuse an unexpected directory created while workers were stopping.
        root.parent.mkdir(parents=True, exist_ok=True)
        root.mkdir(mode=0o700)
        expected_root = identity(root.lstat())
        removal['identities'][str(root)] = expected_root
    # A fresh, exclusive name cannot truncate a pre-existing hard link.
    with directory_fd(root) as descriptor:
        if identity(os.fstat(descriptor)) != expected_root:
            raise RuntimeError('Installation directory replaced before writing uninstall progress')
        name = '.uninstall-' + os.urandom(12).hex()
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        created = False
        try:
            pending = os.open(name, flags, 0o600, dir_fd=descriptor)
            created = True
            with os.fdopen(pending, 'w') as file:
                json.dump({'application': 'attention-uninstall-v1',
                           'scope_settings': [str(p) for p in removal['scope_settings']]}, file)
                file.flush()
                os.fsync(file.fileno())
            os.replace(name, '.uninstall.json', src_dir_fd=descriptor, dst_dir_fd=descriptor)
        finally:
            if created:
                try:
                    os.unlink(name, dir_fd=descriptor)
                except FileNotFoundError:
                    pass
    env = dict(os.environ, CODEX_HOME=str(removal['codex']), CLAUDE_CONFIG_DIR=str(removal['claude']))
    for command, cwd in removal['commands']:
        # Native clients own their internal removal operation. Recheck immediately
        # before handing over; never claim to sandbox a concurrently hostile client.
        for path, kind in removal['kinds'].items():
            if path.exists():
                expected = removal['identities'].get(str(path))
                if expected is not None and identity(path.lstat()) != expected:
                    raise RuntimeError('Installation directory replaced before native cleanup')
                owned_inventory(path, kind)
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
    # Native removal may remove cache roots, but must never replace a surviving one.
    for path, info in removal['identities'].items():
        target = Path(path)
        if info is not None and target.exists() and identity(target.lstat()) != info:
            raise RuntimeError('Installation directory replaced during uninstall: ' + path)
    snapshots = {path: owned_inventory(path, kind) for path, kind in removal['kinds'].items()}
    for target in [*removal['targets'], root]:
        remove_inventory(target, snapshots[target])
    leftovers = [str(p) for p in roots if p.exists() or p.is_symlink()]
    if leftovers or processes(roots):
        raise RuntimeError('Uninstall incomplete; a client recreated Attention files/processes. Close it and retry.')
    return {'status': 'removed', 'removed': [str(p) for p in roots], 'retained_shared_sources': removal['retained']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--yes', action='store_true', help='Erase settings, imported audio and all Attention data')
    parser.add_argument('--dry-run', action='store_true', help='List exact targets without changing anything')
    parser.add_argument('--interactive', action='store_true', help='Preview and ask in the terminal before erasing')
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
            preview = {'status': 'preview', 'erase': ['settings', 'custom audio', 'queue', 'logs', 'runtimes', 'dependencies'],
                       'paths': [str(p) for p in [*removal['targets'], removal['data']]],
                       'commands': [{'argv': cmd, 'cwd': str(cwd)} for cmd, cwd in removal['commands']],
                       'retained_shared_sources': removal['retained']}
            if args.interactive:
                print('Attention uninstall\n\nPermanently removes Attention settings, imported audio, '
                      'summaries, queue, logs and private runtimes.\nCleanup paths:')
                for path in preview['paths']:
                    print('  ' + json.dumps(path, ensure_ascii=False))
                for command in preview['commands']:
                    print('Client command: ' + json.dumps(command, ensure_ascii=False))
                for reason in removal['retained']:
                    print('Keeping: ' + reason)
                print('Original audio files, other plugins, projects and shared Python/uv are preserved.\n', flush=True)
            else:
                print(json.dumps(preview, indent=2))
            if args.dry_run:
                return 0
            if args.interactive:
                try:
                    terminal = open('/dev/tty', 'rb+', buffering=0)
                except OSError:
                    raise RuntimeError('Interactive uninstall needs a terminal. Use --dry-run to preview, '
                                       'or explicitly pass --yes to delete.')
                with terminal:
                    if not os.isatty(terminal.fileno()):
                        raise RuntimeError('Interactive uninstall needs a terminal; nothing was removed.')
                    terminal.write(b'Remove Attention from both clients and permanently delete the listed data? '
                                   b'Type yes to continue: ')
                    terminal.flush()
                    if terminal.readline().strip() != b'yes':
                        print('Cancelled. Nothing was removed.')
                        # Let wrappers preserve themselves when the user cancels.
                        return 3
                # Preview is not a deletion authorization for a changed installation.
                if plan(args.data_dir, removal['codex'], removal['claude']) != removal:
                    raise RuntimeError('Installation changed after preview. Nothing was removed; run again.')
            else:
                print('Close both clients, then rerun with --yes to delete all listed Attention data.', file=sys.stderr)
                return 2
        print(json.dumps(execute(removal), indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error, csv.Error, subprocess.SubprocessError) as error:
        print('Attention uninstall incomplete: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
