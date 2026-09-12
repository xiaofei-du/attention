#!/usr/bin/env python3
"""Build a self-contained Attention! marketplace without personal state."""

import argparse
import base64
import hashlib
import json
import os
import plistlib
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION = '0.1.4'
MARKETPLACE_NAME = 'xiaofei-du'


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def run(command):
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError(result.stderr[-4000:])


def build_native(target):
    app = target / 'Attention.app'
    executable = app / 'Contents' / 'MacOS' / 'nkc-player'
    executable.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        scratch = Path(directory)
        for name, sources, frameworks in [
            ('player', ['player.m', 'duck.m'], ['Foundation', 'AVFAudio', 'CoreAudio']),
            ('language', ['language.m'], ['Foundation', 'NaturalLanguage', 'AppKit']),
        ]:
            binaries = []
            for arch in ('arm64', 'x86_64'):
                output = scratch / (name + '-' + arch)
                command = ['xcrun', 'clang', '-target', arch + '-apple-macos14.2', '-fobjc-arc',
                           '-Wall', '-Wextra', '-Werror', *[str(ROOT / 'native' / p) for p in sources]]
                for framework in frameworks:
                    command.extend(['-framework', framework])
                run([*command, '-o', str(output)])
                binaries.append(str(output))
            output = executable if name == 'player' else target / 'nkc-language'
            run(['xcrun', 'lipo', '-create', *binaries, '-output', str(output)])
            output.chmod(0o755)
            run(['/usr/bin/codesign', '--force', '--sign', '-', str(output)])
    (app / 'Contents' / 'Info.plist').write_bytes(plistlib.dumps({
        'CFBundleIdentifier': 'local.attention.audio', 'CFBundleExecutable': 'nkc-player',
        'CFBundleName': 'Attention!', 'CFBundlePackageType': 'APPL', 'CFBundleVersion': '1',
        'CFBundleShortVersionString': VERSION, 'LSMinimumSystemVersion': '14.2', 'LSUIElement': True,
        'NSAudioCaptureUsageDescription': 'Temporarily lower other apps’ media while a task update speaks. '
        'Audio stays on this Mac, without microphone access, saving or uploading it.',
    }))
    run(['/usr/bin/codesign', '--force', '--sign', '-', str(app)])


def build_payload(directory):
    run([sys.executable, str(ROOT / 'scripts/export_requirements.py'), '--check'])
    directory.mkdir(parents=True)
    for name in ['launch.py', 'attention.py', 'run.py', 'mcp_server.py', 'submit.py',
                 'summary-prompt.txt', 'summary-isolated-prompt.txt']:
        shutil.copy2(ROOT / name, directory / name)
    shutil.copytree(ROOT / 'nkc', directory / 'nkc', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copytree(ROOT / 'skills', directory / 'skills', ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.DS_Store'))
    (directory / 'scripts').mkdir()
    for name in ('prepare_isolation.py', 'update_codex_plugin.py', 'uninstall.py'):
        shutil.copy2(ROOT / 'scripts' / name, directory / 'scripts' / name)
    (directory / 'docs').mkdir()
    for name in ('isolation-setup.md', 'upgrading.md'):
        shutil.copy2(ROOT / 'docs' / name, directory / 'docs' / name)
    shutil.copy2(ROOT / 'packaging/requirements.txt', directory / 'requirements.txt')
    shutil.copytree(ROOT / 'packaging/wheels', directory / 'wheels')
    prompt = directory / 'summary-prompt.txt'
    prompt.write_text(prompt.read_text().replace('no-keyboard-code MCP', 'attention MCP'))
    build_native(directory / 'native-bin')
    files = {p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(directory.rglob('*')) if p.is_file()}
    write_json(directory / 'payload.json', {'version': VERSION, 'files': files})


def server(root_var):
    # Only a clean interpreter starts here. launch.py installs all SDK dependencies
    # with --require-hashes before running the MCP process.
    arguments = ['run', '--no-config', '--no-project', '--isolated', '--python', '3.12', 'python', '-I']
    if root_var == '${PLUGIN_ROOT}':
        return {'command': 'uv', 'cwd': '.', 'args': [*arguments, 'launch.py', 'mcp', '--provider', 'codex']}
    return {'command': 'uv', 'args': [*arguments, root_var + '/launch.py', 'mcp', '--provider', 'claude-code']}


def windows_disabled_command(action):
    if action != 'prompt':
        return 'echo {}'
    # EncodedCommand preserves the static script across cmd/PowerShell quoting.
    # It neither changes execution policy nor runs downloaded/user-provided code.
    script = r'''
$ErrorActionPreference = 'Stop'
$result = '{}'
try {
  $root = if ($env:ATTENTION_DATA_DIR) { $env:ATTENTION_DATA_DIR } else { Join-Path $env:LOCALAPPDATA 'Attention' }
  $directory = Join-Path $root 'notices'
  [void][IO.Directory]::CreateDirectory($directory)
  $path = Join-Path $directory 'windows-unsupported'
  if (-not [IO.File]::Exists($path)) {
    $file = [IO.File]::Open($path, [IO.FileMode]::CreateNew)
    $file.Dispose()
    $result = '{"systemMessage":"Attention! requires macOS 14.2+. Spoken notifications are disabled; your coding session can continue normally."}'
  }
} catch { }
[Console]::Out.WriteLine($result)
'''
    encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    return 'powershell.exe -NoProfile -NonInteractive -EncodedCommand ' + encoded


def hooks(provider, root_var, payload_digest=None):
    result = {}
    for event, action in [('UserPromptSubmit', 'prompt'), ('Stop', 'stop'), ('PreToolUse', 'control-context')]:
        if event == 'PreToolUse' and provider == 'codex':
            continue
        command = ('uv run --no-config --no-project --isolated --python 3.12 python -I "' +
                   root_var + '/launch.py" hook ' + action + ' --provider ' + provider)
        if payload_digest is not None:
            entry = (ROOT / 'packaging/hook_entry.py').read_text().replace('{{payload_digest}}', payload_digest)
            command = ('uv run --no-config --no-project --isolated --python 3.12 python -I -c ' +
                       shlex.quote(entry) + ' "' + root_var + '" hook ' + action + ' --provider ' + provider)
        handler = {'type': 'command', 'command': command, 'timeout': 240,
                   'statusMessage': 'Attention!: ' + {'prompt': 'summary context', 'stop': 'spoken update',
                                                      'control-context': 'session control context'}[action]}
        if provider == 'codex':
            # Unsupported Windows hosts must not interpret POSIX environment syntax.
            handler['command_windows'] = windows_disabled_command(action)
        # Stop must finish its queue handoff before codex exec shuts down.
        # Only the hook is synchronous; playback runs in a detached worker.
        result[event] = [{'hooks': [handler]}]
        if event == 'PreToolUse':
            result[event][0]['matcher'] = r'^mcp__(?:attention|plugin_attention_attention)__(?:get_status|set_session_enabled)$'
    return {'hooks': result}


def build(output):
    if output.exists():
        raise ValueError('Output must be a new directory; choose a fresh output or remove an old generated build explicitly')
    output.mkdir(parents=True)
    try:
        with tempfile.TemporaryDirectory() as temporary:
            payload = Path(temporary) / 'payload'
            build_payload(payload)
            files = json.loads((payload / 'payload.json').read_text())['files']
            payload_digest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            for provider, folder, root_var in [('codex', 'plugins', '${PLUGIN_ROOT}'),
                                               ('claude-code', 'claude-plugins', '${CLAUDE_PLUGIN_ROOT}')]:
                plugin = output / folder / 'attention'
                shutil.copytree(payload, plugin)
                description = 'Your agent has something to report. Local spoken updates for macOS 14.2+.'
                manifest = {'name': 'attention', 'version': VERSION, 'description': description,
                            'author': {'name': 'Xiaofei Du'}, 'keywords': ['voice', 'notifications', 'macos']}
                if provider == 'codex':
                    scaffold = json.loads((ROOT / 'packaging/codex/attention/.codex-plugin/plugin.json').read_text())
                    scaffold.update(manifest)
                    manifest = scaffold
                    manifest['mcpServers'] = {'attention': server(root_var)}
                    manifest['interface'] = {'displayName': 'Attention!', 'shortDescription': description,
                        'longDescription': 'Your original agent reports context, progress and next steps with local Mac voices. '
                                           'One shared queue and nine controls work across Codex and Claude Code.',
                        'category': 'Productivity', 'developerName': 'Xiaofei Du',
                        'capabilities': ['Read', 'Write'],
                        'defaultPrompt': 'Help me use Attention and explain the starter options.'}
                    write_json(plugin / '.codex-plugin/plugin.json', manifest)
                    # Companion schema for validation and discovery; explicit manifest config takes precedence.
                    write_json(plugin / '.mcp.json', {'mcpServers': {'attention': server(root_var)}})
                else:
                    write_json(plugin / '.claude-plugin/plugin.json', manifest)
                    write_json(plugin / '.mcp.json', {'mcpServers': {'attention': server(root_var)}})
                write_json(plugin / 'hooks/hooks.json', hooks(provider, root_var, payload_digest))
                shutil.copy2(ROOT / 'packaging/PLUGIN-README.md', plugin / 'README.md')
        write_json(output / '.agents/plugins/marketplace.json', {
            'name': MARKETPLACE_NAME, 'interface': {'displayName': 'Attention!'},
            'plugins': [{'name': 'attention', 'source': {'source': 'local', 'path': './plugins/attention'},
                         'policy': {'installation': 'AVAILABLE', 'authentication': 'ON_INSTALL'},
                         'category': 'Productivity'}]})
        write_json(output / '.claude-plugin/marketplace.json', {
            'name': MARKETPLACE_NAME, 'owner': {'name': 'Xiaofei Du'},
            'metadata': {'description': 'Local spoken updates for coding agents on macOS 14.2+.'},
            'plugins': [{'name': 'attention', 'source': './claude-plugins/attention',
                         'description': 'Local spoken task updates for macOS 14.2+.'}]})
        shutil.copy2(ROOT / 'packaging/PLUGIN-README.md', output / 'README.md')
        (output / '.gitignore').write_text('__pycache__/\n*.pyc\n.state/\n.venv/\n.DS_Store\n')
    except Exception:
        # Only a new directory exclusively created by this invocation is removed.
        shutil.rmtree(output)
        raise
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(build(args.output.resolve()))
