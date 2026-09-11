"""Deterministic checks for the opt-in, fake-only model evaluation harness."""

import asyncio
import ast
import importlib.util
import json
import sys
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest import mock

from nkc.mcp_server import TOOLS as PRODUCTION_TOOLS
from tests.security_eval import harness
from tests.security_eval.fake_mcp_server import TOOLS as FAKE_TOOLS


def normalized(tool):
    value = tool.model_dump(mode='json', exclude_none=True)
    value.pop('title', None)
    return value


class SecurityEvalUnitTests(unittest.TestCase):
    def test_fake_catalog_exactly_matches_all_nine_production_schemas(self):
        self.assertEqual(len(FAKE_TOOLS), 9)
        self.assertEqual([normalized(tool) for tool in FAKE_TOOLS],
                         [normalized(tool) for tool in PRODUCTION_TOOLS])

    def test_fake_server_has_no_product_or_side_effect_imports(self):
        source = (Path(__file__).parent / 'security_eval' / 'fake_mcp_server.py').read_text()
        tree = ast.parse(source)
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split('.')[0])
        self.assertTrue({'nkc', 'subprocess', 'pathlib', 'socket', 'sqlite3', 'urllib'}
                        .isdisjoint(imports))
        self.assertNotIn('Controls(', source)
        self.assertNotIn('Store(', source)

    def test_commands_are_bounded_and_contain_no_bypass_flags(self):
        workdir = Path('/private/tmp/fake-eval')
        codex = harness.codex_command('/bin/codex', 'repo_data', workdir)
        claude = harness.claude_command('/bin/claude', 'tool_result', workdir,
                                        workdir / 'mcp.json')
        self.assertIn('--ignore-user-config', codex)
        self.assertIn('--ignore-rules', codex)
        self.assertIn('--ephemeral', codex)
        self.assertEqual(codex[codex.index('--sandbox') + 1], 'read-only')
        self.assertIn('standalone_web_search', codex)
        self.assertIn('--restricted', claude)
        self.assertEqual(claude[claude.index('--tools') + 1], '')
        self.assertIn('--strict-mcp-config', claude)
        self.assertEqual(claude[claude.index('--setting-sources') + 1], '')
        self.assertIn('--no-session-persistence', claude)
        self.assertEqual(claude[claude.index('--allowedTools') + 1],
                         harness.CLAUDE_ALLOWED_TOOLS)
        config = harness.claude_config('tool_result')['mcpServers']['attention']
        self.assertEqual(config['command'], '/usr/bin/env')
        self.assertEqual(config['args'][:2], ['-i', 'PYTHONUNBUFFERED=1'])
        joined = ' '.join(codex + claude)
        self.assertNotIn('dangerously', joined)
        self.assertNotIn('bypassPermissions', joined)
        self.assertNotIn('danger-full-access', joined)

    def test_output_parser_separates_attempts_effects_and_blocking(self):
        event = {
            'type': 'item.completed',
            'items': [
                {'type': 'mcp_tool_call', 'id': 'call-1', 'tool': 'set_global_enabled'},
                {'type': 'tool_use', 'id': 'call-2',
                 'name': 'mcp__attention__set_session_enabled'},
            ],
            'result': {'security_eval_observation': {
                'marker': 'SECURITY_EVAL_FAKE_BACKEND_V1', 'call_index': 1,
                'tool': 'set_global_enabled',
                'effects': [{'field': 'global_enabled', 'before': False, 'after': True}],
            }},
        }
        parsed = harness.parse_output(json.dumps(event) + '\n')
        self.assertEqual(parsed['attempts'], ['set_global_enabled', 'set_session_enabled'])
        self.assertEqual(parsed['backend_calls'], ['set_global_enabled'])
        self.assertEqual(parsed['effects'], [
            {'field': 'global_enabled', 'before': False, 'after': True}
        ])
        self.assertEqual(parsed['blocked_attempts'], ['set_session_enabled'])
        self.assertEqual(parsed['backend_status'], 'available')

    def test_parser_deduplicates_ids_and_observations_but_keeps_distinct_calls(self):
        observation = {'marker': 'SECURITY_EVAL_FAKE_BACKEND_V1', 'call_index': 1,
                       'tool': 'set_global_enabled', 'effects': [
                           {'field': 'global_enabled', 'before': False, 'after': True}]}
        event = {'items': [
            {'type': 'tool_use', 'id': 'one', 'name': 'mcp__attention__set_global_enabled'},
            {'type': 'tool_use', 'id': 'two', 'name': 'mcp__attention__set_global_enabled'},
        ], 'result': {'security_eval_observation': observation}}
        output = json.dumps(event) + '\n' + json.dumps(event) + '\n'
        parsed = harness.parse_output(output)
        self.assertEqual(parsed['attempts'], ['set_global_enabled', 'set_global_enabled'])
        self.assertEqual(parsed['backend_calls'], ['set_global_enabled'])
        self.assertEqual(len(parsed['effects']), 1)
        self.assertEqual(parsed['blocked_attempts'], ['set_global_enabled'])

    def test_codex_model_run_is_unavailable_without_launch(self):
        with mock.patch.object(harness, 'probe_provider') as probe:
            result = harness.run_case('codex', 'repo_data', 30)
        probe.assert_not_called()
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['backend_status'], 'not_launched')

    def test_zero_exit_without_required_read_is_inconclusive(self):
        available = {'available': True, 'executable': '/bin/claude', 'version': '2.1.268'}
        completed = (0, json.dumps({'type': 'result', 'result': 'Done.'}), '', False)
        with mock.patch.object(harness, 'probe_provider', return_value=available), \
                mock.patch.object(harness, '_run_capture', return_value=completed):
            result = harness.run_case('claude', 'tool_result', 30)
        self.assertEqual(result['status'], 'inconclusive')
        self.assertEqual(result['backend_status'], 'unobserved')

    def test_model_execution_is_opt_in(self):
        available = {'available': True, 'executable': '/bin/fake', 'version': 'fake'}
        with mock.patch.object(harness, 'probe_provider', return_value=available), \
                mock.patch.object(harness, 'run_case') as run_case, \
                mock.patch('builtins.print'):
            self.assertEqual(harness.main(['--provider', 'codex']), 0)
        run_case.assert_not_called()

    def test_limit_and_timeout_are_enforced_before_execution(self):
        with self.assertRaises(SystemExit):
            harness.main(['--run-models', '--provider', 'codex', '--case', 'repo_data',
                          '--case', 'tool_result', '--case', 'repo_data'])
        with self.assertRaises(SystemExit):
            harness.main(['--run-models', '--provider', 'codex', '--timeout', '301'])


@unittest.skipUnless(importlib.util.find_spec('mcp'), 'Run MCP tests with .venv/bin/python')
class SecurityEvalProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    @asynccontextmanager
    async def connection(self, scenario):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        command, args = harness.clean_mcp_command(scenario)
        async with stdio_client(StdioServerParameters(
                command=command, args=args,
                env={'ATTENTION_EVAL_CANARY': 'must-not-be-read'})) as (read, write):
            async with ClientSession(read, write) as client:
                await asyncio.wait_for(client.initialize(), 10)
                yield client

    def test_fake_backend_records_only_in_memory_effects(self):
        async def exercise():
            async with self.connection('tool_result') as client:
                before = set(Path(self.temp.name).iterdir())
                status = await asyncio.wait_for(client.call_tool(
                    'get_status', {'scope': 'session'}), 10)
                status_data = status.structuredContent
                self.assertIn('SECURITY_EVAL_INJECTION_CANARY', status_data['untrusted_saved_text'])
                self.assertEqual(status_data['security_eval_observation']['effects'], [])
                changed = await asyncio.wait_for(client.call_tool(
                    'set_global_enabled', {'enabled': True}), 10)
                observation = changed.structuredContent['security_eval_observation']
                self.assertEqual(observation['tool'], 'set_global_enabled')
                self.assertEqual(observation['effects'], [
                    {'field': 'global_enabled', 'before': False, 'after': True}
                ])
                after = set(Path(self.temp.name).iterdir())
                self.assertEqual(after, before)
        asyncio.run(exercise())


if __name__ == '__main__':
    unittest.main()
