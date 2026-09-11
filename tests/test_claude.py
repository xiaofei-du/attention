"""Claude wire payloads exercise the actual CLI, store and serialized workers."""

import json
import multiprocessing
import re
import shlex
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from nkc.install import PROJECT, PYTHON
from nkc.runtime import handle_hook, run_worker
from nkc.store import Store
from cli_helpers import quiet_cli_prefix


def drain(root):
    def sink(text, settings, cancelled):
        with (Path(root) / 'heard').open('a') as output:
            output.write('start:' + text + '\n')
        time.sleep(0.03)
        with (Path(root) / 'heard').open('a') as output:
            output.write('end:' + text + '\n')
        return True
    run_worker(Store(root), play=sink)


class ClaudeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root)

    def cli(self, *args, payload=None, parse=True):
        result = subprocess.run(quiet_cli_prefix() + ['--state-dir', str(self.root), *args],
                                input=json.dumps(payload) if payload is not None else '', text=True,
                                capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout) if parse else result.stdout

    def hook(self, action, session='A', turn='one', provider='claude-code', **fields):
        event = dict(session_id=session, transcript_path='/unused/transcript.jsonl', cwd=str(self.root),
                     permission_mode='default', hook_event_name='UserPromptSubmit' if action == 'prompt' else 'Stop')
        event['prompt_id' if provider == 'claude-code' else 'turn_id'] = turn
        if action == 'prompt':
            event['prompt'] = 'Review the queue implementation.'
        else:
            event.update(last_assistant_message='Done.', stop_hook_active=False,
                         background_tasks=[], session_crons=[])
        event.update(fields)
        return self.cli('hook', action, '--provider', provider, payload=event)

    def token(self, result):
        return re.search(r'--token ([a-f0-9-]+)', result['hookSpecificOutput']['additionalContext']).group(1)

    def test_claude_stages_its_own_summary_and_stop_uses_it_once(self):
        token = self.token(self.hook('prompt'))
        self.cli('summary', '--token', token, payload={
            'why': 'We are reviewing the notification queue.',
            'done': 'I found a duplicate playback bug.', 'next': 'Next I will fix it.'})
        self.assertEqual(self.store.jobs(), [])
        for _ in range(2):
            self.assertEqual(self.hook('stop', last_assistant_message='Detailed technical evidence. ' * 100), {})
        jobs = self.store.jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual((jobs[0]['provider'], jobs[0]['session_id'], jobs[0]['turn_id']),
                         ('claude-code', 'A', 'one'))
        self.assertEqual(jobs[0]['body'], 'We are reviewing the notification queue. '
                         'I found a duplicate playback bug. Next I will fix it.')

    def test_summary_instructions_fit_claudes_inline_hook_context_limit(self):
        # Claude persists oversized additionalContext and shows only a 2KB
        # preview. Keep all instructions inline, including with a custom start.
        self.store.set_start('好' * 120)
        context = self.hook('prompt')['hookSpecificOutput']['additionalContext']
        self.assertLessEqual(len(context.encode('utf-8')), 10000,
                             'Claude would replace the summary instructions with a file preview')

    def test_short_reply_reads_directly_without_metadata(self):
        self.hook('prompt')
        self.hook('stop', last_assistant_message='**改好了**，下次會保留你的設定。')
        self.assertEqual(self.store.jobs()[0]['body'], '改好了，下次會保留你的設定。')

    def test_missing_prompt_id_cannot_reuse_current_turn_or_codex_turn_id(self):
        self.hook('prompt')
        self.hook('stop', turn=None, turn_id='one')
        self.assertEqual(self.store.jobs(), [])
        self.assertEqual(self.store.events()[0]['kind'], 'invalid_event')

    def test_subagent_and_failed_turns_do_not_notify_or_replace_parent_token(self):
        token = self.token(self.hook('prompt'))
        for event in ('SubagentStop', 'StopFailure'):
            self.hook('stop', hook_event_name=event)
        self.assertEqual(self.hook('prompt', turn='child', agent_id='child-agent'), {})
        self.hook('stop', agent_id='child-agent')
        self.assertEqual(self.store.jobs(), [])
        self.cli('summary', '--token', token, payload={'why': 'We are testing notifications.',
                                                     'done': 'The parent context stayed intact.', 'next': ''})
        self.hook('stop')
        self.assertEqual(len(self.store.jobs()), 1)

    def test_background_wait_is_deferred_but_final_continued_stop_can_notify(self):
        token = self.token(self.hook('prompt'))
        self.cli('summary', '--token', token, payload={'why': 'We are reviewing the queue.',
                 'done': 'The background reviewer is still working.', 'next': 'I will wait for the review.'})
        self.hook('stop', background_tasks=[{'id': 'task', 'type': 'subagent', 'status': 'running',
                                           'description': 'Reviewing the changes'}])
        self.assertEqual(self.store.jobs(), [])
        self.hook('stop', stop_hook_active=True, last_assistant_message='The review is complete.')
        self.assertEqual(self.store.jobs()[0]['body'], 'The review is complete.')

    def test_followup_retains_queued_summary_and_rejects_late_old_stop(self):
        self.hook('prompt')
        self.hook('stop', last_assistant_message='The first result is ready.')
        self.hook('prompt', turn='two')
        self.hook('stop', turn='one', last_assistant_message='Late old response.')
        self.hook('stop', turn='two', last_assistant_message='The follow-up is ready.')
        self.assertEqual([(j['turn_id'], j['body'], j['status']) for j in self.store.jobs()],
                         [('one', 'The first result is ready.', 'pending'),
                          ('two', 'The follow-up is ready.', 'pending')])

    def test_same_session_ids_on_two_providers_have_independent_mute_preferences(self):
        claude = self.token(self.hook('prompt'))
        self.hook('prompt', provider='codex')
        self.hook('stop')
        self.cli('session-voice', '--token', claude, payload={'enabled': False})
        self.hook('stop', provider='codex')
        self.assertEqual([(j['provider'], j['status']) for j in self.store.jobs()],
                         [('claude-code', 'cancelled'), ('codex', 'pending')])
        next_token = self.token(self.hook('prompt', turn='two'))
        self.hook('stop', turn='two')
        self.assertEqual([j['status'] for j in self.store.jobs()], ['cancelled', 'pending', 'cancelled'])
        self.assertFalse(Store(self.root).session_enabled('claude-code', 'A'))
        self.cli('session-voice', '--token', next_token, payload={'enabled': True})
        self.hook('stop', turn='two')
        self.assertEqual([j['status'] for j in self.store.jobs()], ['cancelled', 'pending', 'cancelled'])
        self.hook('prompt', turn='three')
        self.hook('stop', turn='three')
        self.hook('prompt', session='new')
        self.hook('stop', session='new')
        self.assertEqual([j['status'] for j in self.store.jobs()],
                         ['cancelled', 'pending', 'cancelled', 'pending', 'pending'])

    def test_two_providers_share_one_fifo_even_with_competing_workers(self):
        self.store.set_start('')
        for provider, reply in [('claude-code', 'Claude finished.'), ('codex', 'Codex finished.')]:
            common = {'session_id': 'A', 'prompt_id': 'one', 'turn_id': 'one'}
            handle_hook('prompt', dict(common, hook_event_name='UserPromptSubmit'), self.store, provider=provider)
            handle_hook('stop', dict(common, hook_event_name='Stop', last_assistant_message=reply),
                        self.store, provider=provider, start_worker=lambda root: None)
        workers = [multiprocessing.get_context('spawn').Process(target=drain, args=(str(self.root),))
                   for _ in range(3)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(10)
            if worker.is_alive():
                worker.terminate()
                worker.join()
                self.fail('Worker failed to finish')
            self.assertEqual(worker.exitcode, 0)
        self.assertEqual((self.root / 'heard').read_text().splitlines(),
                         ['start:Claude finished.', 'end:Claude finished.',
                          'start:Codex finished.', 'end:Codex finished.'])
        self.assertEqual([j['status'] for j in self.store.jobs()], ['spoken', 'spoken'])

    def test_install_merges_claude_settings_idempotently_and_uninstall_keeps_codex_playing(self):
        home = self.root / 'claude'
        home.mkdir()
        path = home / 'settings.json'
        original = {'env': {'KEEP': 'yes'}, 'permissions': {'allow': ['Read']},
                    'hooks': {'Stop': [{'hooks': [{'type': 'command', 'command': 'cmux-notify'}]}]}}
        previous = json.dumps(original).encode()
        path.write_bytes(previous)
        for _ in range(2):
            self.cli('install', '--provider', 'claude-code', '--claude-home', str(home), parse=False)
        merged = json.loads(path.read_text())
        self.assertEqual(merged['env'], original['env'])
        self.assertEqual(merged['permissions'], original['permissions'])
        self.assertEqual(merged['hooks']['Stop'][0], original['hooks']['Stop'][0])
        self.assertEqual(len(merged['hooks']['Stop']), 2)
        self.assertEqual(len(merged['hooks']['UserPromptSubmit']), 1)
        self.assertEqual(len(list(home.glob('settings.json.nkc-backup-*'))), 1)
        self.assertEqual(next(home.glob('settings.json.nkc-backup-*')).read_bytes(), previous)
        for action, event in [('prompt', 'UserPromptSubmit'), ('stop', 'Stop')]:
            handler = merged['hooks'][event][-1]['hooks'][0]
            self.assertEqual(handler['type'], 'command')
            self.assertFalse(handler.get('async', False), 'Enqueue must finish before Claude tears down')
            command = shlex.split(handler['command'])
            self.assertEqual(command[-4:], ['hook', action, '--provider', 'claude-code'])
        self.assertFalse((home / 'hooks.json').exists())
        self.cli('uninstall', '--provider', 'claude-code', '--claude-home', str(home), parse=False)
        self.assertEqual(json.loads(path.read_text()), original)
        self.assertTrue(self.store.settings()['global_voice_enabled'], 'Uninstalling one provider cannot mute the other')

    def test_invalid_claude_settings_are_not_overwritten(self):
        home = self.root / 'claude'
        home.mkdir()
        path = home / 'settings.json'
        path.write_text('{ broken')
        result = subprocess.run([PYTHON, str(PROJECT / 'run.py'), '--state-dir', str(self.root),
                                 'install', '--provider', 'claude-code',
                                 '--claude-home', str(home)], text=True, capture_output=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('JSONDecodeError', result.stderr)
        self.assertEqual(path.read_text(), '{ broken')


if __name__ == '__main__':
    unittest.main()
