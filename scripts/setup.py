#!/usr/bin/env python3
"""Install through native plugin managers. Never edit hooks, trust or speech state."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

REPO = 'xiaofei-du/attention'
MARKETPLACE = 'xiaofei-du'
PLUGIN = 'attention@xiaofei-du'
UPGRADING = 'https://github.com/xiaofei-du/attention/blob/main/docs/upgrading.md'


class SetupError(Exception):
    pass


def command(executable, arguments, cwd):
    try:
        result = subprocess.run([executable, *arguments], cwd=cwd, stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SetupError(f'{Path(executable).name}: could not finish {" ".join(arguments)}. '
                         'Check the client and network, then rerun setup.') from error
    if result.returncode:
        detail = ''.join(c for c in result.stderr[-1500:] if c.isprintable() or c == '\n')
        raise SetupError(f'{Path(executable).name}: {" ".join(arguments)} failed.\n{detail}\n'
                         'Completed installations are kept. Fix this step and rerun setup.')
    return result.stdout


def listing(executable, args, cwd, key=None):
    try:
        data = json.loads(command(executable, args, cwd))
        if key:
            data = data[key]
        if not isinstance(data, list) or not all(isinstance(x, dict) for x in data):
            raise ValueError('Expected a list of objects')
        return data
    except (ValueError, KeyError, TypeError) as error:
        raise SetupError(f'{Path(executable).name}: unrecognized plugin list JSON. '
                         'Update your client and retry; setup will not guess its state.') from error


def official_source(market, client):
    if client == 'codex':
        source = market.get('marketplaceSource', {})
        return source.get('sourceType') == 'git' and source.get('source') in (
            f'https://github.com/{REPO}', f'https://github.com/{REPO}.git')
    return ((market.get('source') == 'github' and market.get('repo') == REPO) or
            (market.get('source') == 'git' and market.get('url') in (
                f'https://github.com/{REPO}', f'https://github.com/{REPO}.git')))


def inspect_client(client, executable, cwd):
    markets = listing(executable, ['plugin', 'marketplace', 'list', '--json'], cwd,
                      'marketplaces' if client == 'codex' else None)
    plugins = listing(executable, ['plugin', 'list', '--json'], cwd,
                      'installed' if client == 'codex' else None)
    if any(not isinstance(m.get('name'), str) for m in markets):
        raise SetupError(f'{client}: unrecognized marketplace list. Update your client and retry.')
    ours = [m for m in markets if m['name'] == MARKETPLACE]
    if len(ours) > 1 or (ours and not official_source(ours[0], client)):
        raise SetupError(f'{client}: the marketplace name {MARKETPLACE} has a different source. '
                         f'Nothing will be replaced. Review it in your client; see {UPGRADING}')
    installed = []
    for plugin in plugins:
        identifier = plugin.get('pluginId' if client == 'codex' else 'id')
        if not isinstance(identifier, str):
            raise SetupError(f'{client}: unrecognized installed plugin record; update your client.')
        if identifier.startswith('attention@') and identifier != PLUGIN:
            raise SetupError(f'{client}: an older Attention installation needs migration: {UPGRADING}')
        if identifier == PLUGIN:
            if client == 'claude' and plugin.get('scope') != 'user':
                raise SetupError(f'{client}: Attention already exists in another scope. '
                                 f'Review it before adding a user installation: {UPGRADING}')
            if client == 'codex' and plugin.get('installed') is not True:
                raise SetupError(f'{client}: ambiguous installation record; review it in your client.')
            installed.append(plugin)
    if len(installed) > 1 or (installed and not ours):
        raise SetupError(f'{client}: inconsistent Attention registration; review it in your client. '
                         f'See {UPGRADING}')
    return bool(ours), installed[0] if installed else None


def choose_client():
    try:
        with open('/dev/tty', 'w') as terminal, open('/dev/tty', 'r') as keyboard:
            terminal.write('Install for:\n  1. Codex\n  2. Claude Code\n  3. Both\n'
                           'Choose 1, 2 or 3 (Enter cancels): ')
            terminal.flush()
            choice = keyboard.readline().strip()
    except OSError as error:
        raise SetupError('Run setup in a terminal, or specify --client codex|claude|both.') from error
    if not choice:
        return None
    if choice not in ('1', '2', '3'):
        raise SetupError('Invalid selection. Rerun setup and choose 1, 2 or 3.')
    return {'1': 'codex', '2': 'claude', '3': 'both'}[choice]


def update_client(client, executable, installed, cwd, dry_run):
    if installed.get('enabled') is not True:
        # Codex plugin add re-enables disabled plugins. Do not change that choice.
        print(f'{client}: disabled plugin skipped; enable it in your client before updating.')
        return
    if dry_run:
        print(f'Would update {PLUGIN} for {client}, preserving its registration and settings.')
        return
    print(f'{client}: refreshing the marketplace and updating Attention…', flush=True)
    command(executable, ['plugin', 'marketplace', 'upgrade' if client == 'codex' else 'update',
                         MARKETPLACE], cwd)
    _, current = inspect_client(client, executable, cwd)
    if not current or current.get('enabled') is not True:
        raise SetupError(f'{client}: plugin state changed during refresh. No plugin update was attempted.')
    args = (['plugin', 'add', PLUGIN, '--json'] if client == 'codex' else
            ['plugin', 'update', PLUGIN, '--scope', 'user', '--json'])
    try:
        report = json.loads(command(executable, args, cwd))
        version = report.get('version' if client == 'codex' else 'newVersion')
        if report.get('pluginId') != PLUGIN or not isinstance(version, str) or not version:
            raise ValueError('Missing version or plugin identity')
        if client == 'claude' and report.get('outcome') != 'ok':
            raise ValueError('Update did not report success')
    except (ValueError, AttributeError) as error:
        raise SetupError(f'{client}: unrecognized update result. Check its installed version in the client.') from error
    _, registered = inspect_client(client, executable, cwd)
    if not registered or registered.get('version') != version or registered.get('enabled') is not True:
        raise SetupError(f'{client}: installed version/state does not match the update result. Check the client.')
    print(f'{client}: updated {installed.get("version", "unknown")} → {version}; one plugin registration.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', choices=('codex', 'claude', 'both'))
    parser.add_argument('--dry-run', action='store_true', help='Inspect and preview without installing plugins')
    parser.add_argument('--update', action='store_true', help='Update existing enabled plugins; never install into another client')
    args = parser.parse_args(argv)
    if sys.platform != 'darwin' or os.geteuid() == 0 or os.geteuid() != os.getuid():
        raise SetupError('Run Attention setup as your normal user on macOS 14.2+, without sudo.')
    # Exclude relative/empty PATH entries: a project must not supply a client shim.
    os.environ['PATH'] = os.pathsep.join(p for p in os.environ.get('PATH', '').split(os.pathsep)
                                       if os.path.isabs(p))
    print('Attention! 📣\nInstall from xiaofei-du/attention using your native plugin managers.', flush=True)
    selected = args.client or ('available' if args.update else choose_client())
    if selected is None:
        print('Cancelled. No plugins were changed.')
        return 0
    clients = (tuple(name for name in ('codex', 'claude') if shutil.which(name)) if selected == 'available'
               else ('codex', 'claude') if selected == 'both' else (selected,))
    if not clients:
        raise SetupError('No Codex or Claude Code terminal command was found.')
    executables = {}
    # Preflight every requested client before modifying either one.
    for client in clients:
        executable = shutil.which(client)
        if not executable or not os.path.isabs(executable):
            raise SetupError(f'{client} was not found on PATH. Install/open the client and make its '
                             'terminal command available, then retry. No plugins were changed.')
        executables[client] = executable
    # A neutral cwd prevents project-scoped configuration from changing this user installation.
    with tempfile.TemporaryDirectory(prefix='attention-setup-client-') as cwd:
        states = {client: inspect_client(client, executables[client], cwd) for client in clients}
        for client in clients:
            executable = executables[client]
            has_market, installed = states[client]
            if args.update:
                if installed:
                    update_client(client, executable, installed, cwd, args.dry_run)
                else:
                    print(f'{client}: Attention is not installed; skipped. Use attention setup to add it.')
                continue
            if installed:
                state = 'disabled' if installed.get('enabled') is False else 'installed'
                print(f'{client}: already {state} (version {installed.get("version", "unknown")}); preserved.')
                print(f'For updates or migration: {UPGRADING}')
                continue
            if args.dry_run:
                print(f'Would install {PLUGIN} for {client}' +
                      ('.' if has_market else f', adding {REPO} first.'))
                continue
            if not has_market:
                print(f'{client}: adding the Attention marketplace…', flush=True)
                command(executable, ['plugin', 'marketplace', 'add', REPO], cwd)
                has_market, installed = inspect_client(client, executable, cwd)
                if not has_market or installed:
                    raise SetupError(f'{client}: marketplace registration changed unexpectedly; review it and retry.')
            print(f'{client}: installing Attention…', flush=True)
            arguments = (['plugin', 'add', PLUGIN] if client == 'codex' else
                         ['plugin', 'install', PLUGIN, '--scope', 'user'])
            command(executable, arguments, cwd)
            _, registered = inspect_client(client, executable, cwd)
            if not registered:
                raise SetupError(f'{client}: the command returned without an Attention registration. '
                                 'Check your client and rerun setup.')
            print(f'{client}: Attention plugin installed.')
    if args.dry_run:
        print('Preview complete. No plugins were changed.')
        return 0
    print('\nNext: reopen your clients and review Attention’s hooks when prompted.')
    if 'codex' in clients:
        print('Codex: open Hooks or run /hooks; find attention@xiaofei-du and Trust UserPromptSubmit and Stop.')
    if 'claude' in clients:
        print('Claude Code: reopen or run /reload-plugins to load the enabled plugin’s hooks; '
              'no Codex-style per-hook Trust step is required.')
    print('First launch downloads Python/MCP dependencies and can take a little longer.\n'
          'Then start a new conversation and paste:\n'
          '  Please reply only with: “This is an Attention voice notification.”\n'
          'With fresh-install defaults, listen for “hey boss”, then the sentence above.\n'
          'Hearing it confirms playback; seeing the text alone does not.\n'
          'Existing disabled plugins and speech preferences stay unchanged.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (SetupError, KeyboardInterrupt) as error:
        print(f'Attention setup stopped: {error or "interrupted; rerun setup to continue"}', file=sys.stderr)
        sys.exit(1)
