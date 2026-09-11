#!/usr/bin/python3
"""No-keyboard-code: summary hooks and a local spoken-notification queue."""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nkc.audio import build_player
from nkc.language import build_detector
from nkc.controls import Controls
from nkc.voice_cache import invalidate_voice_inventory, load_inventory
from nkc.install import PROJECT, definition, install_hooks, uninstall_hooks
from nkc.runtime import handle_hook, render, run_worker, start_voice_warmup
from nkc.store import Store
from nkc.summary import notification_body, notification_text
from nkc.opening import system_sounds, preview_audio
from nkc.voice_setup import MissingVoice, DOWNLOAD_HELP


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', type=Path, default=PROJECT / '.state')
    parser.add_argument('--summary-socket', type=Path, help='Trusted isolated-hook summary endpoint')
    commands = parser.add_subparsers(dest='command', required=True)
    hook = commands.add_parser('hook', help='Agent lifecycle entry point; JSON on stdin/stdout')
    hook.add_argument('action', choices=['prompt', 'stop', 'control-context'])
    hook.add_argument('--provider', choices=['codex', 'claude-code'], default='codex')
    definitions = commands.add_parser('hooks')
    definitions.add_argument('--provider', choices=['codex', 'claude-code'], default='codex')
    for name in ('worker', 'warm-voices', 'status', 'build', 'set-start', 'set-start-audio', 'list-start-sounds',
                 'set-session-name-report', 'global-voice', 'set-voice-gender', 'list-voices',
                 'clear-queue', 'set-summary-preferences'):
        commands.add_parser(name)
    for name in ('install', 'uninstall'):
        command = commands.add_parser(name)
        command.add_argument('--provider', choices=['codex', 'claude-code'], default='codex')
        command.add_argument('--codex-home', type=Path,
                             default=Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))))
        command.add_argument('--claude-home', type=Path,
                             default=Path(os.environ.get('CLAUDE_CONFIG_DIR', str(Path.home() / '.claude'))))
    configure = commands.add_parser('configure')
    configure.add_argument('--name')
    configure.add_argument('--voice')
    configure.add_argument('--rate', type=int)
    configure.add_argument('--voice-mode', choices=['auto', 'fixed'])
    configure.add_argument('--english-voice')
    configure.add_argument('--duck-media', choices=['on', 'off'],
                           help='Opt in/out of system-audio capture for lowering other media')
    summary = commands.add_parser('summary', help='Stage this turn’s spoken summary as JSON on stdin; does not play')
    summary.add_argument('--token', required=True)
    session_voice = commands.add_parser('session-voice', help='Set only this session’s speech preference; JSON on stdin')
    session_voice.add_argument('--token', required=True)
    preview = commands.add_parser('render', help='Render a final-answer summary to an audio file; does not play it')
    preview.add_argument('--message-file', type=Path, required=True)
    preview.add_argument('--output', type=Path, required=True)
    sound_preview = commands.add_parser('preview-start-audio', help='Render an opening audition file; JSON on stdin, no playback or selection')
    sound_preview.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()

    # Hook failures are recorded, but never block or continue the original task.
    if args.command == 'hook':
        try:
            store = Store(args.state_dir)
            raw = sys.stdin.buffer.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ValueError('Hook payload exceeds two megabytes')
            event = json.loads(raw)
            if not isinstance(event, dict):
                raise ValueError('Hook payload must be an object')
            result = handle_hook(args.action, event, store, provider=args.provider,
                                 summary_socket=args.summary_socket, warmup=start_voice_warmup)
        except Exception as error:
            print('no-keyboard-code hook: ' + type(error).__name__ + ': ' + str(error)[:200], file=sys.stderr)
            result = {}
        print(json.dumps(result, ensure_ascii=False))
        return

    if args.command == 'hooks':
        print(json.dumps(definition(args.provider), indent=2, ensure_ascii=False))
        return
    if args.command == 'warm-voices':
        # Launched by the prompt hook; never block another refresh or request audio.
        load_inventory(args.state_dir, nonblocking=True)
        return
    store = Store(args.state_dir)
    if args.command == 'install':
        build_detector()
        build_player()
        home = args.claude_home if args.provider == 'claude-code' else args.codex_home
        path = install_hooks(home, args.provider)
        print('Installed hook definitions at ' + str(path))
        if args.provider == 'codex':
            print('Codex must review/trust these hooks before they run. Existing notify and trust settings were preserved.')
        else:
            print('Claude Code 2.1.196+ required. Run /hooks to inspect. Existing settings and hooks were preserved.')
        settings = store.settings()
        print('Playback is ' + ('globally disabled.' if not settings['global_voice_enabled'] else 'enabled.'))
    elif args.command == 'build':
        build_detector()
        print('Built native speech and media-ducking player at ' + str(build_player()))
    elif args.command == 'uninstall':
        home = args.claude_home if args.provider == 'claude-code' else args.codex_home
        print('Removed our hook definitions from ' + str(uninstall_hooks(home, args.provider)))
        print('Shared playback and accepted notifications are unchanged; use global-voice to turn all speech off.')
    elif args.command == 'configure':
        store.configure(name=args.name, voice=args.voice, rate=args.rate,
                        voice_mode=args.voice_mode, english_voice=args.english_voice,
                        duck_media=None if args.duck_media is None else args.duck_media == 'on')
        if any(value is not None for value in (args.voice, args.voice_mode, args.english_voice)):
            invalidate_voice_inventory(store.root)
        print(json.dumps(store.settings(), ensure_ascii=False))
    elif args.command == 'summary':
        raw = sys.stdin.buffer.read(8001)
        if len(raw) > 8000:
            raise ValueError('Summary payload exceeds eight kilobytes')
        store.stage_summary(args.token, json.loads(raw))
        print(json.dumps({'staged': True}))
    elif args.command == 'set-start':
        raw = sys.stdin.buffer.read(8001)
        if len(raw) > 8000:
            raise ValueError('Start payload exceeds eight kilobytes')
        payload = json.loads(raw)
        if not isinstance(payload, dict) or set(payload) != {'text'}:
            raise ValueError('Set-start requires exactly one text field')
        store.set_start(payload['text'])
        print(json.dumps({'start': store.settings()['start']}, ensure_ascii=False))
    elif args.command == 'set-session-name-report':
        raw = sys.stdin.buffer.read(8001)
        if len(raw) > 8000:
            raise ValueError('Session name report payload exceeds eight kilobytes')
        payload = json.loads(raw)
        if not isinstance(payload, dict) or set(payload) != {'enabled'}:
            raise ValueError('Set-session-name-report requires exactly one enabled field')
        store.set_announce_session_name(payload['enabled'])
        print(json.dumps({'announce_session_name': store.settings()['announce_session_name']}))
    elif args.command == 'set-voice-gender':
        raw = sys.stdin.buffer.read(8001)
        if len(raw) > 8000:
            raise ValueError('Voice gender payload exceeds eight kilobytes')
        payload = json.loads(raw)
        if not isinstance(payload, dict) or set(payload) != {'gender'}:
            raise ValueError('Set-voice-gender requires exactly one gender field')
        result = Controls(store).set_voice_preferences(gender=payload['gender'])
        print(json.dumps(result['availability'], ensure_ascii=False))
    elif args.command == 'list-voices':
        result = Controls(store).list_voices()
        print(json.dumps(result, ensure_ascii=False))
    elif args.command == 'list-start-sounds':
        print(json.dumps({'sounds': system_sounds()}, ensure_ascii=False))
    elif args.command in ('set-start-audio', 'preview-start-audio'):
        raw = sys.stdin.buffer.read(8001)
        if len(raw) > 8000:
            raise ValueError('Audio opening payload exceeds eight kilobytes')
        payload = json.loads(raw)
        result = ({'start_audio': store.set_start_audio(payload)} if args.command == 'set-start-audio'
                  else preview_audio(payload, args.output))
        print(json.dumps(result, ensure_ascii=False))
    elif args.command == 'session-voice':
        raw = sys.stdin.buffer.read(8001)
        if len(raw) > 8000:
            raise ValueError('Session preference payload exceeds eight kilobytes')
        payload = json.loads(raw)
        if not isinstance(payload, dict) or set(payload) != {'enabled'}:
            raise ValueError('Session-voice requires exactly one enabled field')
        print(json.dumps(store.set_session_enabled(args.token, payload['enabled']), ensure_ascii=False))
    elif args.command == 'global-voice':
        raw = sys.stdin.buffer.read(8001)
        if len(raw) > 8000:
            raise ValueError('Global preference payload exceeds eight kilobytes')
        payload = json.loads(raw)
        if not isinstance(payload, dict) or set(payload) != {'enabled'}:
            raise ValueError('Global-voice requires exactly one enabled field')
        store.set_global_enabled(payload['enabled'])
        print(json.dumps({'global_voice_enabled': store.global_enabled()}))
    elif args.command == 'worker':
        run_worker(store)
    elif args.command == 'clear-queue':
        print(json.dumps({'cleared': store.clear_queue()}))
    elif args.command == 'set-summary-preferences':
        raw = sys.stdin.buffer.read(8001)
        if len(raw) > 8000:
            raise ValueError('Summary preferences payload exceeds eight kilobytes')
        payload = json.loads(raw)
        if (not isinstance(payload, dict) or not payload
                or not set(payload) <= {'enabled', 'target_seconds', 'tone', 'focus'}
                or any(value is None for value in payload.values())):
            raise ValueError('Provide enabled, target_seconds, tone and/or focus; no null or free-form values')
        print(json.dumps(store.set_summary_preferences(**payload), ensure_ascii=False))
    elif args.command == 'status':
        print(json.dumps({'settings': store.settings(), 'sessions': store.session_preferences(),
                          'jobs': store.jobs(), 'events': store.events(),
                          'summary_preferences': store.summary_preferences()},
                         ensure_ascii=False, indent=2))
    elif args.command == 'render':
        settings = store.settings()
        body = notification_body(args.message_file.read_text(), allow_direct=True)
        text = notification_text(body, settings)
        try:
            path = render(text, settings, args.output)
            result = {'audio': str(path), 'text': text, 'characters': len(text)}
        except MissingVoice as notice:
            result = {'audio': None, 'status': 'needs_voice_download', 'message': str(notice),
                      'download_help': DOWNLOAD_HELP}
        print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
