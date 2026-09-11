"""New MCP preferences remain available to both providers through existing hooks."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from nkc.install import PROJECT, PYTHON
from nkc.runtime import handle_hook
from nkc.store import Store


class ControlHookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)

    def test_max_preferences_and_opening_fit_context_and_reach_both_providers(self):
        self.store.set_start('好' * 120)
        self.store.set_summary_preferences(target_seconds=90, tone='conversational', focus='next_steps')
        for provider in ('codex', 'claude-code'):
            self.store.record_voice_notice(provider, 'A', 'Please download the missing voice. ' * 60)
            self.store.record_voice_notice(provider, 'A', 'Media ducking unavailable. ' * 60, category='media_ducking')
            context = handle_hook('prompt', {'hook_event_name': 'UserPromptSubmit', 'session_id': 'A',
                        'turn_id': 'one', 'prompt_id': 'one'}, self.store,
                        provider=provider)['hookSpecificOutput']['additionalContext']
            self.assertLessEqual(len(context.encode('utf-8')), 10000)
            self.assertIn('Target seconds: 90', context)
            self.assertIn('Focus: next_steps', context)
            self.assertNotIn('好' * 120, context)
            self.assertIn('no-keyboard-code MCP', context)
            self.assertIn('set_starter_options', context)
            self.assertIn('clear_queue', context)
            self.assertIn(' set-summary-preferences', context)
            self.assertIn(' clear-queue', context)
            self.assertIn('summary --token ', context)
            self.assertNotIn('{{', context)

    def test_cli_preferences_validate_and_clear_does_not_stop_current_speech(self):
        prefix = [PYTHON, str(PROJECT / 'run.py'), '--state-dir', str(self.store.root)]
        def cli(command, payload=None):
            return subprocess.run(prefix + [command], input=json.dumps(payload) if payload is not None else '',
                                  text=True, capture_output=True, timeout=10)
        result = cli('set-summary-preferences', {'target_seconds': 20, 'tone': 'calm', 'focus': 'next_steps'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['target_seconds'], 20)
        for payload in ({'target_seconds': None}, {'unknown': 'x'}, {'target_seconds': 45, 'custom_instructions': 'obsolete'},
                        {'target_seconds': 45, 'tone': 'unrecognized'}, {'target_seconds': 45, 'focus': 'unrecognized'}, []):
            self.assertNotEqual(cli('set-summary-preferences', payload).returncode, 0)
            self.assertEqual(self.store.summary_preferences()['target_seconds'], 20)
        for session in ('active', 'queued'):
            self.store.begin_turn('codex', session, 'one')
            self.store.enqueue('codex', session, 'one', 'A result.', delay=0)
        job = self.store.claim()
        result = cli('clear-queue')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'cleared': 1})
        self.assertFalse(self.store.playback_cancelled(job['id']))
