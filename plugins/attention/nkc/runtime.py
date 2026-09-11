"""Provider hook boundary and serialized macOS speech playback."""

import fcntl
import json
import os
import shlex
import subprocess
import sys
import time
import warnings
from contextlib import nullcontext
from pathlib import Path

from .audio import speak, render_speech, MediaDuckingWarning
from .install import PROJECT, PYTHON
from .summary import notification_body, notification_text
from .summary_preferences import prompt_guidance
from .session_names import hook_source, resolve_session_name
from .voice_setup import MissingVoice, VoiceDownloadWarning, show_voice_notice, refresh_voice_inventory
from .voice_cache import voice_inventory
from .onboarding import INTRODUCTION
from .control_context import control_context


SUMMARY_DISABLED_NOTICE = (
    'Attention summary is disabled. This supersedes all earlier Attention instructions to '
    'generate or submit spoken summaries or read replies aloud. Do not prepare notification '
    'content or reuse old summary commands/tokens. Keep answering the user normally. '
    'The local hook handles starter/name playback. Resume summary preparation only when '
    'a new enabled-summary instruction arrives. No response to this notice is needed.'
)



def cli_command(root, *arguments):
    if os.environ.get('ATTENTION_COMMAND'):
        return [os.environ['ATTENTION_COMMAND'], *arguments]
    return [PYTHON, str(PROJECT / 'run.py'), '--state-dir', str(Path(root).resolve()), *arguments]


def start_worker(root):
    root = Path(root)
    with (root / 'worker.log').open('ab') as log:
        subprocess.Popen([PYTHON, '-I', str(PROJECT / 'run.py'), '--state-dir', str(root), 'worker'],
                         stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                         start_new_session=True, close_fds=True)


def start_voice_warmup(store, provider, session):
    settings = store.settings()
    if not settings['global_voice_enabled'] or not store.session_enabled(provider, session):
        return None
    needs_voice = (store.summary_preferences()['enabled'] or settings['announce_session_name'] or
                   (settings['start'] and not settings.get('start_audio')))
    if not needs_voice:
        return None
    try:
        # Only enumerate installed voice metadata: no speech, capture, or permissions.
        # A nonblocking cache lock makes simultaneous prompt warmups coalesce.
        return subprocess.Popen([PYTHON, '-I', str(PROJECT / 'run.py'), '--state-dir',
                                 str(store.root), 'warm-voices'], stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True, close_fds=True)
    except OSError:
        return None  # Playback retains the ordinary voice lookup/error path.


def handle_hook(action, event, store, start_worker=start_worker, provider='codex', summary_socket=None,
                warmup=None):
    if provider not in ('codex', 'claude-code'):
        raise ValueError('Unsupported hook provider')
    if action == 'control-context':
        return control_context(event, store, provider)
    expected = {'prompt': 'UserPromptSubmit', 'stop': 'Stop'}.get(action)
    if event.get('hook_event_name') != expected:
        return {}
    if provider == 'claude-code' and event.get('agent_id'):
        return {}
    session = event.get('session_id')
    turn_field = 'prompt_id' if provider == 'claude-code' else 'turn_id'
    turn = event.get(turn_field)
    if not isinstance(session, str) or not session or not isinstance(turn, str) or not turn:
        store.event('', 'invalid_event', provider + ': Missing session_id or ' + turn_field)
        return {}
    store.record_session_source(provider, session, **hook_source(provider, event))
    if action == 'prompt':
        token = store.begin_turn(provider, session, turn)
        if warmup is not None:
            warmup(store, provider, session)
        summary_preferences, revoke = store.claim_summary_context(provider, session)
        template = ('summary-isolated-prompt.txt' if summary_socket else 'summary-prompt.txt')
        if not summary_preferences['enabled']:
            if revoke:
                return {'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit',
                                               'additionalContext': SUMMARY_DISABLED_NOTICE}}
            return {}
        prompt = (PROJECT / template).read_text()
        controls = ('Mutating controls require native confirmation. Cancellation means no change. '
                    'Do not retry automatically, weaken isolation, use control CLI fallbacks, '
                    'or send controls through the summary-only socket.' if summary_socket else
                    'If the MCP schema lacks enabled, send only the requested JSON patch '
                    '(e.g. {"enabled":true}) on stdin to: {{SUMMARY_PREFERENCES_COMMAND}}\n'
                    'CLI fallback for an explicit status inquiry: {{STATUS_COMMAND}}\n'
                    'Only for explicit mute/unmute, send {"enabled":false} or {"enabled":true} on stdin '
                    'to {{SESSION_COMMAND}} for this session, or {{GLOBAL_VOICE_COMMAND}} for ALL sessions. '
                    'Use a quoted heredoc or JSON file; never shell interpolation.')
        prompt = prompt.replace('{{CONTROL_RULES}}', controls)
        prompt = prompt.replace('{{SUMMARY_PREFERENCES}}', prompt_guidance(summary_preferences))
        settings = store.settings()
        prompt = prompt.replace('{{DUCK_MEDIA_STATUS}}', 'enabled' if settings['duck_media'] else 'disabled')
        prompt = prompt.replace('{{DUCK_MEDIA_COMMAND}}', shlex.join(cli_command(store.root, 'configure')))
        prompt = prompt.replace('{{VOICE_GENDER}}', settings['voice_gender'])
        prompt = prompt.replace('{{GLOBAL_STATUS}}', 'enabled' if settings['global_voice_enabled'] else 'disabled')
        if settings['start_audio']:
            kind = settings['start_audio'].get('type') if isinstance(settings['start_audio'], dict) else None
            opening_type = kind if kind in ('system', 'custom') else 'unknown'
        else:
            opening_type = 'text' if settings['start'] else 'none'
        prompt = prompt.replace('{{OPENING_TYPE}}', opening_type)
        prompt = prompt.replace('{{SESSION_NAME_STATUS}}', 'enabled' if settings['announce_session_name'] else 'disabled')
        prompt = prompt.replace('{{STATUS_COMMAND}}', shlex.join(cli_command(store.root, 'status')))
        start_command = shlex.join(cli_command(store.root, 'set-start'))
        prompt = prompt.replace('{{START_COMMAND}}', start_command)
        for placeholder, action in [('{{AUDIO_START_COMMAND}}', 'set-start-audio'),
                                    ('{{GLOBAL_VOICE_COMMAND}}', 'global-voice'),
                                    ('{{VOICE_GENDER_COMMAND}}', 'set-voice-gender'),
                                    ('{{VOICE_LIST_COMMAND}}', 'list-voices'),
                                    ('{{SESSION_NAME_COMMAND}}', 'set-session-name-report'),
                                    ('{{SOUND_LIST_COMMAND}}', 'list-start-sounds'),
                                    ('{{CLEAR_QUEUE_COMMAND}}', 'clear-queue'),
                                    ('{{SUMMARY_PREFERENCES_COMMAND}}', 'set-summary-preferences'),
                                    ('{{SOUND_PREVIEW_COMMAND}}', 'preview-start-audio')]:
            prompt = prompt.replace(placeholder, shlex.join(cli_command(store.root, action)))
        command = shlex.join(cli_command(store.root, 'summary', '--token', token))
        if summary_socket:
            command = shlex.join([sys.executable, '-I', str(PROJECT / 'submit.py'), '--socket',
                                  str(summary_socket), '--token', token])
        prompt = prompt.replace('{{SUMMARY_COMMAND}}', command)
        session_command = shlex.join(cli_command(store.root, 'session-voice', '--token', token))
        prompt = prompt.replace('{{SESSION_COMMAND}}', session_command)
        prompt = prompt.replace('{{SESSION_STATUS}}', 'enabled' if store.session_enabled(provider, session) else 'disabled')
        notices = []
        for category, header in [
            ('media_ducking', '\nPrevious media playback notice: explain briefly; no automatic retry or setting changes.\n'),
            ('voice_download', '\nPrevious playback notice: explain the missing voice and download steps briefly. Recheck if downloaded; no replay.\n'),
        ]:
            detail = store.take_voice_notice(provider, session, category=category)
            if detail:
                notices.append((header, detail))
        # Share the remaining Claude inline-context budget across all notices.
        # Settings and executable control commands must never be truncated.
        remaining = 9900 - len(prompt.encode('utf-8')) - sum(len(h.encode('utf-8')) + 1 for h, _ in notices)
        for index, (header, detail) in enumerate(notices):
            budget = min(502, remaining // (len(notices) - index))
            if budget < 2:
                continue
            while len(json.dumps(detail, ensure_ascii=False).encode('utf-8')) > budget:
                detail = detail[:-1]
            encoded = json.dumps(detail, ensure_ascii=False)
            prompt += header + encoded + '\n'
            remaining -= len(encoded.encode('utf-8'))
        # Controls and actionable playback notices have priority. Defer the
        # guide if it would push Claude into an oversized-context file preview.
        # The receipt is shared by both clients and survives runtime upgrades.
        if len((prompt + INTRODUCTION).encode('utf-8')) <= 9900 and store.claim_onboarding():
            prompt += INTRODUCTION
        return {'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': prompt}}
    if not store.global_enabled():
        if provider == 'claude-code' and event.get('background_tasks'):
            # This is only a wait, not a completed round. A real completion
            # after global re-enable must still be eligible to notify.
            store.discard_summary(provider, session, turn)
        else:
            store.suppress_notification(provider, session, turn)
        store.event(session, 'global_disabled', 'Spoken notification discarded while global speech is disabled')
        return {}
    if not store.session_enabled(provider, session):
        if provider == 'claude-code' and event.get('background_tasks'):
            store.discard_summary(provider, session, turn)
        else:
            store.suppress_notification(provider, session, turn, reason='Session speech disabled')
        store.event(session, 'session_disabled', 'Spoken notification discarded while session speech is disabled')
        return {}
    if provider == 'claude-code' and event.get('background_tasks'):
        store.discard_summary(provider, session, turn)
        store.event(session, 'background_pending', 'Claude still has in-flight background work; notification deferred')
        return {}
    body = ''
    if store.summary_preferences()['enabled']:
        try:
            staged = store.summary_for_turn(provider, session, turn)
            body = notification_body(event.get('last_assistant_message'),
                                     staged=staged['body'] if staged else None, allow_direct=staged is not None)
        except (ValueError, TypeError) as error:
            if store.summary_preferences()['enabled']:
                store.event(session, 'summary_skipped', error)
                return {}
    job = store.enqueue(provider, session, turn, body)
    if job is not None:
        start_worker(store.root)
    return {}


def run_worker(store, play=None, notify=None):
    # Each enqueue starts a short-lived worker. Blocking lock acquisition prevents
    # a lost-wakeup race if another worker exits while the next event is arriving.
    with (store.root / 'speaker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        # The native child inherits the lock. If this worker dies, the next
        # worker waits for the child to stop audio and release ducking.
        notify = notify or show_voice_notice

        def report_notice(job, notice):
            if store.playback_cancelled(job['id']):
                return
            if store.record_voice_notice(job['provider'], job['session_id'], notice,
                                         category='media_ducking' if isinstance(notice, MediaDuckingWarning) else 'voice_download'):
                try:
                    notify(str(notice))
                except Exception as error:
                    # macOS may suppress notifications. The original session's
                    # next prompt still receives the durable installation notice.
                    store.event(job['session_id'], 'voice_notice_delivery', str(error))
        store.recover_playback()
        while True:
            settings = store.settings()
            if not settings['global_voice_enabled']:
                return
            job = store.claim()
            if job is None:
                delay = store.wait_seconds()
                if delay is None:
                    return
                time.sleep(min(max(delay, 0.02), 0.1))
                continue
            settings = store.settings()
            if store.playback_cancelled(job['id']):
                continue
            session_name = ''
            if settings['announce_session_name']:
                try:
                    session_name = resolve_session_name(job['provider'], job['session_id'],
                                                        store.session_source(job['provider'], job['session_id']))
                except (OSError, ValueError):
                    pass
            missing = None
            caught = []
            try:
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter('always')
                    spoken = notification_text(job['body'], settings, session_name)
                    if not spoken.strip() and not settings.get('start_audio'):
                        store.finish(job['id'], 'skipped')
                        continue
                    cancelled = lambda: store.playback_cancelled(job['id'])
                    if play is not None:
                        refresh_voice_inventory()
                        complete = play(spoken, settings, cancelled)
                    else:
                        with voice_inventory(store.root, allow_stale=True) if spoken.strip() else nullcontext():
                            complete = speak(job['body'], settings, cancelled, lock_fd=lock.fileno(),
                                             session_name=session_name)
            except MissingVoice as notice:
                missing = notice
            except Exception as error:
                store.finish(job['id'], 'failed', str(error)[:500])
                continue
            for warning in caught:
                if isinstance(warning.message, (VoiceDownloadWarning, MediaDuckingWarning)):
                    report_notice(job, warning.message)
                else:
                    store.event(job['session_id'], 'voice_warning', warning.message)
            if missing is not None:
                report_notice(job, missing)
                store.finish(job['id'], 'skipped')
                continue
            if complete:
                store.finish(job['id'], 'spoken')
            elif store.playback_cancelled(job['id']):
                continue
            else:
                store.finish(job['id'], 'failed', 'Playback ended without completing; no automatic replay')


def render(text, settings, output):
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    render_speech(text, settings, output)
    return output
