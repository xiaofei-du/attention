"""Generate opt-in host files without changing or launching either host."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import shutil
import sys
import tempfile
from .control_context import CONTROL_MATCHER

PROFILE = 'nkc-isolated'


def _path(value, label):
    path = Path(value).expanduser()
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError(f'{label} must be an absolute path without traversal')
    if any(c in str(path) for c in '\n\r\0*?[]{}'):
        raise ValueError(f'{label} contains control characters or policy glob syntax')
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError(f'{label} contains a symlink: {part}')
    return path


def _overlap(a, b):
    return a == b or a in b.parents or b in a.parents


def _toml(value):
    """Encode our bounded JSON-compatible values as TOML literals."""
    if isinstance(value, dict):
        return '{' + ', '.join(json.dumps(str(k)) + ' = ' + _toml(v) for k, v in value.items()) + '}'
    if isinstance(value, list):
        return '[' + ', '.join(_toml(v) for v in value) + ']'
    return json.dumps(value, ensure_ascii=False)


def _hooks(python, runtime, state, endpoint, provider):
    result = {}
    for event, action in [('UserPromptSubmit', 'prompt'), ('Stop', 'stop'), ('PreToolUse', 'control-context')]:
        if event == 'PreToolUse' and provider == 'codex':
            continue
        command = [str(python), '-I', str(runtime/'run.py'), '--state-dir', str(state),
                   '--summary-socket', str(endpoint), 'hook', action, '--provider', provider]
        handler = {'type': 'command', 'command': shlex.join(command), 'timeout': 5}
        # Codex cancels async hooks at session end. Keep the queue handoff
        # synchronous; the speech worker is independently detached.
        result[event] = [{'hooks': [handler]}]
        if event == 'PreToolUse':
            result[event][0]['matcher'] = CONTROL_MATCHER
    return result


def prepare_isolation(*, project, runtime, state, socket_path, output, python,
                      credential_paths=(), runtime_read_paths=()):
    """Create a NEW 0700 bundle. macOS only; never copy credentials or apply config.

    All supplied directories must exist except output and the socket. Symlinks,
    policy globs, protected/project overlap and mutable interpreter placement fail.
    The operator must install/review the trusted runtime before calling this.
    """
    if sys.platform != 'darwin':
        raise ValueError('This reviewed isolation recipe supports macOS only')
    project, runtime, state, endpoint, output, python = [
        _path(v, label) for v, label in [(project, 'project'), (runtime, 'runtime'),
        (state, 'state'), (socket_path, 'socket'), (output, 'output'), (python, 'python')]]
    credentials = [_path(p, 'credential') for p in credential_paths]
    read_roots = [_path(p, 'runtime read root') for p in runtime_read_paths]
    for directory in (project, runtime, state, endpoint.parent, output.parent):
        if not directory.is_dir():
            raise ValueError(f'Directory must already exist: {directory}')
    if output.exists():
        raise ValueError('Output already exists; choose a new private directory')
    if endpoint.exists() or len(os.fsencode(endpoint)) > 103:
        raise ValueError('Socket must not exist and must fit macOS 103-byte pathname limit')
    if not python.is_file() or not os.access(python, os.X_OK):
        raise ValueError('Python must be an existing executable with no symlink components')
    for name in ('run.py', 'mcp_server.py', 'submit.py'):
        entry = _path(runtime/name, 'runtime entry')
        if not entry.is_file():
            raise ValueError(f'Missing installed runtime entry: {entry}')
    # Protect the full import/dependency tree, including venv links. A venv whose
    # interpreter is a symlink is fine only when the explicit interpreter input
    # names its resolved executable outside every writable project directory.
    for entry in runtime.rglob('*'):
        if entry.is_symlink():
            raise ValueError(f'Trusted runtime must not contain symlinks: {entry}')
    protected = [runtime, state, endpoint.parent, output]
    # Codex 0.154 macOS grants ambient access to temp paths even when explicitly
    # denied; real probes demonstrated this. Never place protected files there.
    temp_roots = [Path('/private/tmp'), Path('/private/var/tmp'), Path('/private/var/folders'),
                  Path(tempfile.gettempdir()).resolve()]
    for path in [python, *protected, *credentials, *read_roots]:
        if any(path == tmp or tmp in path.parents for tmp in temp_roots):
            raise ValueError('Protected paths must be outside macOS temporary directories')
    for path in read_roots:
        if not path.is_dir() or any(_overlap(path, p) for p in [project, state, output, endpoint.parent, *credentials]):
            raise ValueError('Runtime read roots must be existing, narrow, disjoint from project/private paths')
    for i, path in enumerate([project, *protected]):
        for other in [project, *protected][i+1:]:
            if _overlap(path, other):
                raise ValueError(f'Project/protected paths must be disjoint: {path}, {other}')
    for path in credentials:
        if any(_overlap(path, p) for p in [project, runtime, endpoint.parent]):
            raise ValueError('Credential denial must not overlap any readable exception')
    if _overlap(python, project) or any(python == p or p in python.parents for p in [state, output, *credentials]):
        raise ValueError('Interpreter must be outside project and denied private paths')

    filesystem = {':minimal': 'read', ':workspace_roots': 'write',
                  str(runtime): 'read', str(python): 'read',
                  str(endpoint.parent): 'read', str(state): 'deny', str(output): 'deny'}
    filesystem.update({str(p): 'deny' for p in credentials})
    filesystem.update({str(p): 'read' for p in read_roots})
    mcp = {'command': str(python), 'args': ['-I', str(runtime/'mcp_server.py'),
           '--state-dir', str(state), '--summary-socket', str(endpoint), '--confirm-controls']}
    codex = {
        'approval_policy': 'never', 'default_permissions': PROFILE, 'web_search': 'disabled',
        'features': {'hooks': True},
        'shell_environment_policy': {'inherit': 'none', 'set': {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin'}},
        'permissions': {PROFILE: {'filesystem': filesystem, 'network': {
            'enabled': False, 'unix_sockets': {str(endpoint): 'allow'}}}},
        'mcp_servers': {'attention': dict(mcp, args=[*mcp['args'], '--provider', 'codex'])},
        'hooks': _hooks(python, runtime, state, endpoint, 'codex'),
        # A fresh config home does not by itself suppress project config.
        'projects': {str(project): {'trust_level': 'untrusted'}},
    }
    read_denied = [state, output, *credentials]
    write_denied = [*protected, python, *read_roots, *credentials]
    # Claude's absolute permission syntax has TWO leading slashes. Include both
    # the root itself and descendants, so directory replacement is also denied.
    deny = []
    for tool, paths in [('Read', read_denied), ('Edit', write_denied), ('Write', write_denied)]:
        for path in paths:
            deny.extend([f'{tool}(/{path})', f'{tool}(/{path}/**)'])
    claude = {
        'permissions': {'deny': deny, 'allow': ['mcp__attention__*']},
        'sandbox': {'enabled': True, 'failIfUnavailable': True,
            'autoAllowBashIfSandboxed': True, 'allowUnsandboxedCommands': False,
            'excludedCommands': [],
            'filesystem': {'denyRead': list(map(str, read_denied)),
                           'denyWrite': list(map(str, write_denied))},
            'network': {'allowedDomains': [], 'allowUnixSockets': [str(endpoint)],
                        'allowAllUnixSockets': False, 'allowLocalBinding': False}},
        'hooks': _hooks(python, runtime, state, endpoint, 'claude-code'),
    }
    # Pin each complete top-level table on the Codex command line, as well as
    # choosing an untrusted project, so project files cannot widen this recipe.
    # This launcher does not accept arguments that could override these controls.
    host_commands = {}
    for name in ('codex', 'claude'):
        found = shutil.which(name)
        if not found:
            raise ValueError(f'{name} CLI must be installed before generating launch instructions')
        host_commands[name] = Path(found).resolve()
        if any(host_commands[name] == tmp or tmp in host_commands[name].parents for tmp in temp_roots):
            raise ValueError('Host executable must be installed outside temporary directories')
        if project == host_commands[name] or project in host_commands[name].parents:
            raise ValueError('Host executable must be installed outside the project')
    codex_args = [str(host_commands['codex']), '--strict-config', '-C', str(project)]
    for key, value in codex.items():
        codex_args += ['-c', key + '=' + _toml(value)]
    claude_args = [str(host_commands['claude']), '--restricted', '--setting-sources', '', '--settings',
                  str(output/'claude-settings.json'), '--strict-mcp-config', '--mcp-config',
                  str(output/'claude-mcp.json'), '--tools', 'Bash,Read,Edit,Write,Glob,Grep', '--no-chrome']
    # Host credentials remain in each host's own authentication flow. No auth
    # files or environment secrets are copied into the output or child tools.
    env = ['/usr/bin/env', '-i', 'HOME='+str(Path.home()), 'USER='+os.environ.get('USER', ''),
           'PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin']
    def launcher(args, host_env):
        return '#!/bin/sh\nset -eu\n' + 'if [ "$#" -ne 0 ]; then echo "This reviewed launcher accepts no overrides" >&2; exit 2; fi\n' + \
            'cd ' + shlex.quote(str(project)) + '\nexec ' + shlex.join([*env, host_env, *args]) + '\n'
    files = {
        'codex-home/config.toml': '\n'.join(k+' = '+_toml(v) for k,v in codex.items())+'\n',
        'claude-settings.json': json.dumps(claude, indent=2)+'\n',
        'claude-mcp.json': json.dumps({'mcpServers': {'attention': dict(mcp, args=[*mcp['args'], '--provider', 'claude-code'])}}, indent=2)+'\n',
        'launch-codex.sh': launcher(codex_args, 'CODEX_HOME='+str(output/'codex-home')),
        'launch-claude.sh': launcher(claude_args, 'CLAUDE_CONFIG_DIR='+str(output/'claude-home')),
        'README.md': '# Review before launching\n\nGenerated only; no host was started and no live settings were changed.\n\n'
            'Use only a new task and the stable shared summary socket. Review every generated file. '
            'Authenticate the fresh host configuration through its normal login flow; do not copy credentials. '
            'Trust the reviewed hooks through the host UI if required. Do not enable project configuration, '
            'other plugins/MCPs, GUI tools, network domains, extra writable roots or sandbox escapes.\n\n'
            'Launch from a trusted terminal after review:\n\n```sh\n'+shlex.quote(str(output/'launch-codex.sh'))+
            '\n# OR\n'+shlex.quote(str(output/'launch-claude.sh'))+'\n```\n\n'
            'Both launchers discard inherited environment secrets. Native controls require a separate concrete '
            'human confirmation. This is a local shell/file boundary, not full-machine protection. '
            'Claude enforcement still requires real-host acceptance probes; see docs/isolation-setup.md.\n',
    }
    output.mkdir(mode=0o700)
    (output/'codex-home').mkdir(mode=0o700)
    (output/'claude-home').mkdir(mode=0o700)
    for name, content in files.items():
        path = output/name
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700 if name.endswith('.sh') else 0o600)
        with os.fdopen(fd, 'w') as file:
            file.write(content)
    return output
