"""Install an immutable runtime outside ephemeral client plugin directories."""

import asyncio
import fcntl
import hashlib
import json
import os
import runpy
import shlex
import shutil
import sys
import tempfile
from pathlib import Path

from .platform_support import disabled_hook


from .payload import payload_manifest


def prepare_runtime(bundle, root):
    files, revision = payload_manifest(bundle)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    releases = root / 'r'
    releases.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = releases / revision
    with (root / 'setup.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not target.exists():
            temporary = Path(tempfile.mkdtemp(prefix='.install-', dir=releases))
            try:
                for relative in files:
                    path = temporary / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(bundle / relative, path)
                shutil.copy2(bundle / 'payload.json', temporary / 'payload.json')
                os.rename(temporary, target)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
        # Stored outside the hashed payload. A fixed version keeps old turns valid.
        if target.is_symlink() or payload_manifest(target) != (files, revision):
            raise ValueError('Attention! installed runtime failed integrity check')
        command = [sys.executable, '-I', str(target / 'attention.py'), '--data-dir', str(root)]
        wrapper = '#!/bin/sh\nexec ' + shlex.join(command) + ' "$@"\n'
        path = target / 'attention'
        if not path.exists() or path.read_text() != wrapper:
            temp = target / ('.launcher-' + str(os.getpid()))
            temp.write_text(wrapper)
            temp.chmod(0o700)
            os.replace(temp, path)
    return target


def legacy_hook_conflict(provider):
    home = (Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) if provider == 'codex'
            else Path(os.environ.get('CLAUDE_CONFIG_DIR', str(Path.home() / '.claude'))))
    path = home / ('hooks.json' if provider == 'codex' else 'settings.json')
    if not path.is_file():
        return False
    try:
        config = json.loads(path.read_text())
        for groups in config.get('hooks', {}).values():
            for group in groups:
                for handler in group.get('hooks', []):
                    if (str(handler.get('statusMessage', '')).startswith('no-keyboard-code:') and
                            'run.py' in str(handler.get('command', '')) and handler.get('enabled') is not False):
                        return True
    except (ValueError, TypeError, AttributeError):
        return False
    return False


def dispatch(bundle, root, arguments):
    is_hook = arguments[0] == 'hook'
    if arguments[0] == 'mcp' and any(legacy_hook_conflict(p) for p in ('codex', 'claude-code')):
        # Controls must not misleadingly edit a fresh queue while old hooks keep
        # using their legacy state. Report the migration requirement instead.
        os.environ['ATTENTION_SERVER_NAME'] = 'attention'
        from .mcp_server import serve
        asyncio.run(serve(root / 'state', availability={
            'supported': False, 'status': 'legacy_installation_detected',
            'message': 'Attention! detected existing no-keyboard-code hooks. Migrate that installation '
                       'before using these controls; its current speech settings have not changed.'}))
        return
    if is_hook:
        provider = arguments[arguments.index('--provider') + 1] if '--provider' in arguments else 'codex'
        if legacy_hook_conflict(provider):
            notice = {'message': 'Attention! detected the existing no-keyboard-code hooks. '
                      'The new plugin notifications are disabled to prevent duplicate speech. '
                      'Migrate the existing installation before enabling plugin notifications.'}
            print(json.dumps(disabled_hook(root, notice, arguments[1])))
            return
    runtime = prepare_runtime(bundle, root)
    os.environ['ATTENTION_PYTHON'] = sys.executable
    os.environ['ATTENTION_COMMAND'] = str(runtime / 'attention')
    os.environ['ATTENTION_BUILD_DIR'] = str(runtime / 'native-bin')
    os.environ['ATTENTION_SERVER_NAME'] = 'attention'
    # The initial launcher package has imported only platform/bootstrap modules.
    # All core/audio modules must now resolve from the durable versioned runtime.
    import nkc
    nkc.__path__ = [str(runtime / 'nkc')]
    state = root / 'state'
    if arguments[0] == 'mcp':
        from .mcp_server import serve
        import argparse
        parser = argparse.ArgumentParser(prog='attention mcp')
        parser.add_argument('--provider', choices=['codex', 'claude-code'], default='codex')
        options = parser.parse_args(arguments[1:])
        asyncio.run(serve(state, provider=options.provider))
    else:
        sys.argv = [str(runtime / 'run.py'), '--state-dir', str(state), *arguments]
        runpy.run_path(str(runtime / 'run.py'), run_name='__main__')
