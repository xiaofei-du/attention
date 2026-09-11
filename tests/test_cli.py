import json
import re
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path

from nkc.install import PROJECT, PYTHON
from cli_helpers import quiet_cli_prefix


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def command(self, *args, payload=''):
        result = subprocess.run(quiet_cli_prefix() + ['--state-dir', str(self.root), *args],
                                input=payload, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_invalid_payload_cannot_block_the_original_task(self):
        for payload in ('not json', '[]', 'x' * 2_000_001):
            self.assertEqual(self.command('hook', 'stop', payload=payload), {})

    def test_real_hook_commands_persist_one_summary_before_worker_playback(self):
        common = {'session_id': 'cli-smoke', 'turn_id': 'round-1'}
        prompt = self.command('hook', 'prompt', payload=json.dumps(dict(common, hook_event_name='UserPromptSubmit')))
        context = prompt['hookSpecificOutput']['additionalContext']
        self.assertIn('Opening type: text', context)
        self.assertNotIn('hey sunshine', context)
        stop = dict(common, hook_event_name='Stop', last_assistant_message=(PROJECT / 'examples/notification-message.md').read_text())
        for _ in range(2):
            self.assertEqual(self.command('hook', 'stop', payload=json.dumps(stop)), {})
        status = self.command('status')
        self.assertTrue(status['settings']['global_voice_enabled'])
        self.assertEqual(len(status['jobs']), 1)
        self.assertEqual(status['jobs'][0]['status'], 'pending')
        self.assertEqual(status['settings']['name'], 'sunshine')
        self.assertEqual(status['settings']['start'], 'hey sunshine')

    def test_stop_queues_the_short_visible_reply_without_rewriting_it(self):
        reply = '**改好了**，音量維持原本的設定。'
        stop = {'session_id': 'direct-cli', 'turn_id': 'one', 'hook_event_name': 'Stop',
                'last_assistant_message': reply + '\n\n<!-- nkc-summary:v1\n{"mode":"direct"}\n-->'}
        self.assertEqual(self.command('hook', 'stop', payload=json.dumps(stop)), {})
        status = self.command('status')
        self.assertTrue(status['settings']['global_voice_enabled'])
        self.assertEqual(len(status['jobs']), 1)
        self.assertEqual(status['jobs'][0]['body'], '改好了，音量維持原本的設定。')

    def test_summary_command_stages_outside_the_answer_until_stop(self):
        common = {'session_id': 'no-comments', 'turn_id': 'one'}
        prompt = self.command('hook', 'prompt', payload=json.dumps(dict(common, hook_event_name='UserPromptSubmit')))
        context = prompt['hookSpecificOutput']['additionalContext']
        token = re.search(r'--token ([a-f0-9-]+)', context).group(1)
        payload = {'why': 'You wanted clean replies.', 'done': 'I moved the summary out of the reply.', 'next': ''}
        self.assertEqual(self.command('summary', '--token', token, payload=json.dumps(payload)), {'staged': True})
        self.assertEqual(self.command('status')['jobs'], [])
        stop = dict(common, hook_event_name='Stop', last_assistant_message='A long explanation. ' * 100)
        for _ in range(2):
            self.command('hook', 'stop', payload=json.dumps(stop))
        jobs = self.command('status')['jobs']
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]['body'], 'You wanted clean replies. I moved the summary out of the reply.')
        self.command('hook', 'prompt', payload=json.dumps(dict(common, turn_id='two',
                                                              hook_event_name='UserPromptSubmit')))
        retained = self.command('status')['jobs']
        self.assertEqual(len(retained), 1)
        self.assertEqual(retained[0]['body'], jobs[0]['body'])
        self.assertEqual(retained[0]['status'], 'pending')

    def test_prompt_provides_a_working_function_to_change_the_complete_start(self):
        from nkc.runtime import run_worker
        from nkc.store import Store
        common = {'session_id': 'conversational-name', 'turn_id': 'one'}
        prompt = self.command('hook', 'prompt', payload=json.dumps(dict(common, hook_event_name='UserPromptSubmit')))
        context = prompt['hookSpecificOutput']['additionalContext']
        commands = [line.strip() for line in context.splitlines()
                    if ' --state-dir ' in line and line.strip().endswith(' set-start')]
        self.assertEqual(len(commands), 1, 'The session needs a runnable start-setting function bound to this install')
        # The complete custom opening is literal JSON data, not a shell expression.
        start = '嘿，小太陽，你的任務有消息了。'
        result = subprocess.run(shlex.split(commands[0]), input=json.dumps({'text': start}),
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['start'], start)
        self.assertEqual(self.command('status')['jobs'], [], 'Changing an opening is not a notification')
        self.command('hook', 'stop', payload=json.dumps(dict(common, hook_event_name='Stop',
                                                           last_assistant_message='開場已更新。')))
        store = Store(self.root)
        with store.db() as db:
            db.execute('UPDATE jobs SET ready_after=0')
        heard = []
        def sink(text, settings, cancelled):
            heard.append(text)
            return True
        run_worker(store, play=sink)
        self.assertEqual(heard, [start + '開場已更新。'])
        next_prompt = self.command('hook', 'prompt', payload=json.dumps(dict(common, turn_id='two',
                                                          hook_event_name='UserPromptSubmit')))
        next_context = next_prompt['hookSpecificOutput']['additionalContext']
        self.assertNotIn(start, next_context)
        self.assertIn('Opening type: text', next_context)
        self.assertEqual(self.command('status')['settings']['start'], start)

    def test_set_start_rejects_unexpected_fields_without_changing_preferences(self):
        original = self.command('status')['settings']
        result = subprocess.run([PYTHON, str(PROJECT / 'run.py'), '--state-dir', str(self.root), 'set-start'],
                                input='{"text":"Changed","voice":"other"}', text=True,
                                capture_output=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.command('status')['settings'], original)

    def test_session_command_from_prompt_disables_only_that_session_and_can_reenable(self):
        from nkc.store import Store
        def prompt_for(session, turn):
            prompt = self.command('hook', 'prompt', payload=json.dumps({'hook_event_name':'UserPromptSubmit',
                                  'session_id':session, 'turn_id':turn}))
            return prompt['hookSpecificOutput']['additionalContext']
        def toggle(context, enabled):
            commands = [line.strip() for line in context.splitlines() if ' session-voice --token ' in line]
            self.assertEqual(len(commands), 1)
            result = subprocess.run(shlex.split(commands[0]), input=json.dumps({'enabled':enabled}),
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        first = prompt_for('A', '1')
        self.assertFalse(toggle(first, False)['enabled'])
        second = prompt_for('A', '2')
        prompt_for('B', '1')
        for session, turn in [('A','2'), ('B','1')]:
            self.command('hook', 'stop', payload=json.dumps({'hook_event_name':'Stop', 'session_id':session,
                         'turn_id':turn, 'last_assistant_message':'完成了。'}))
        jobs = self.command('status')['jobs']
        self.assertEqual([(job['session_id'], job['status']) for job in jobs],
                         [('A', 'cancelled'), ('B', 'pending')])
        self.assertEqual(jobs[0]['body'], '')
        self.assertFalse(Store(self.root).session_enabled('codex', 'A'))
        self.assertTrue(toggle(second, True)['enabled'])
        self.assertTrue(Store(self.root).session_enabled('codex', 'A'))
        self.assertTrue(self.command('status')['settings']['global_voice_enabled'])


if __name__ == '__main__':
    unittest.main()
