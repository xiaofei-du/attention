"""Run against a generated marketplace with ATTENTION_TEST_MARKETPLACE set."""
import asyncio
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path

BUNDLE = os.environ.get('ATTENTION_TEST_MARKETPLACE')


@unittest.skipUnless(BUNDLE and importlib.util.find_spec('mcp'), 'Requires generated marketplace and MCP runtime')
class PluginMCPTests(unittest.TestCase):
    @asynccontextmanager
    async def connect(self, command, args, env=None, cwd=None):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        async with stdio_client(StdioServerParameters(command=command, args=args, env=env, cwd=cwd)) as (read, write):
            async with ClientSession(read, write) as client:
                initialized = await asyncio.wait_for(client.initialize(), 60)
                self.assertEqual(initialized.serverInfo.name, 'attention')
                self.assertEqual(len((await client.list_tools()).tools), 9)
                yield client

    async def call(self, client, name, args=None):
        result = await asyncio.wait_for(client.call_tool(name, args or {}), 20)
        self.assertFalse(result.isError, result)
        return result.structuredContent

    def test_relocated_plugins_share_state_and_survive_cache_deletion(self):
        async def check():
            with tempfile.TemporaryDirectory(prefix='attention plugin spaces ') as temporary:
                base = Path(temporary)
                data = base / 'user data'
                for provider, folder, variable in [('codex', 'plugins', '${PLUGIN_ROOT}'),
                                                   ('claude-code', 'claude-plugins', '${CLAUDE_PLUGIN_ROOT}')]:
                    plugin = base / provider / 'attention'
                    shutil.copytree(Path(BUNDLE) / folder / 'attention', plugin)
                    if provider == 'codex':
                        spec = json.loads((plugin / '.codex-plugin/plugin.json').read_text())['mcpServers']['attention']
                    else:
                        spec = json.loads((plugin / '.mcp.json').read_text())['mcpServers']['attention']
                    args = [part.replace(variable, str(plugin)) for part in spec['args']]
                    entry = args.index('mcp')
                    args[entry:entry] = ['--data-dir', str(data)]
                    env = dict(os.environ, CODEX_HOME=str(base / 'empty-codex'),
                               CLAUDE_CONFIG_DIR=str(base / 'empty-claude'))
                    async with self.connect(spec['command'], args, env,
                                            str(plugin / spec['cwd']) if 'cwd' in spec else None) as client:
                        status = await self.call(client, 'get_status')
                        expected = 'hey boss' if provider == 'codex' else 'Keep my opening'
                        self.assertEqual(status['starter']['opening']['text'], expected)
                        self.assertEqual(status['queue']['pending'], 0)
                        self.assertEqual(status['summary_preferences']['focus'],
                                         'balanced' if provider == 'codex' else 'next_steps')
                        await self.call(client, 'set_summary_preferences',
                                        {'tone': 'calm', 'focus': 'next_steps'})
                        self.assertEqual(status['voice_preferences']['duck_media'], provider != 'codex')
                        await self.call(client, 'set_voice_preferences', {'duck_media': True})
                        await self.call(client, 'set_global_enabled', {'enabled': False})
                        await self.call(client, 'set_starter_options', {'opening': {'type': 'text', 'text': 'Keep my opening'}})
                        await self.call(client, 'get_starter_sound_options')
                        voices = await self.call(client, 'list_voices')
                        self.assertGreater(len(voices['voices']), 0)
                    shutil.rmtree(plugin)
                runtimes = list((data / 'r').iterdir())
                self.assertEqual(len(runtimes), 1, 'Both providers must use one identical core payload')
                result = subprocess.run([str(runtimes[0] / 'attention'), 'status'], text=True,
                                        capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)['settings']['start'], 'Keep my opening')
                player = runtimes[0] / 'native-bin/Attention.app/Contents/MacOS/nkc-player'
                result = subprocess.run([str(player), '--output-info'], text=True, capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
        asyncio.run(check())

    def test_unsupported_mcp_is_healthy_without_native_modules_or_queue(self):
        async def check():
            with tempfile.TemporaryDirectory() as temporary:
                plugin = Path(BUNDLE) / 'plugins/attention'
                script = '''
import builtins, runpy, sys
from nkc import platform_support
platform_support.platform_status=lambda: dict(supported=False,status='unsupported_platform',message='Requires macOS 14.2+')
original=builtins.__import__
def safe_import(name,*args,**kwargs):
    if name in ('nkc.audio','nkc.controls','nkc.bootstrap','nkc.runtime'):
        raise AssertionError('Native import on unsupported platform: '+name)
    return original(name,*args,**kwargs)
builtins.__import__=safe_import
sys.argv=['attention.py','--data-dir',sys.argv[1],'mcp']
runpy.run_path('attention.py',run_name='__main__')
'''
                env = dict(os.environ, PYTHONPATH=str(plugin))
                # cwd is supplied in the script; stdio launch itself stays a normal Python process.
                script = 'import os; os.chdir(' + repr(str(plugin)) + ')\n' + script
                async with self.connect(sys.executable, ['-c', script, temporary], env) as client:
                    status = await self.call(client, 'get_status')
                    self.assertEqual(status['status'], 'unsupported_platform')
                    self.assertFalse(status['supported'])
                    result = await self.call(client, 'set_global_enabled', {'enabled': True})
                    self.assertEqual(result['status'], 'unsupported_platform')
                self.assertEqual(list(Path(temporary).iterdir()), [])
        asyncio.run(check())

    def test_legacy_installation_controls_do_not_create_an_unrelated_queue(self):
        async def check():
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / 'hooks.json').write_text(json.dumps({'hooks': {'Stop': [{'hooks': [{
                    'command': '/python /legacy/run.py hook stop',
                    'statusMessage': 'no-keyboard-code: spoken summary'}]}]}}))
                plugin = Path(BUNDLE) / 'plugins/attention'
                env = dict(os.environ, CODEX_HOME=str(root), CLAUDE_CONFIG_DIR=str(root / 'empty'),
                           ATTENTION_DATA_DIR=str(root / 'attention-data'))
                async with self.connect(sys.executable, [str(plugin / 'attention.py'), 'mcp'], env) as client:
                    result = await self.call(client, 'get_status')
                    self.assertEqual(result['status'], 'legacy_installation_detected')
                    result = await self.call(client, 'set_starter_options',
                                             {'opening': {'type': 'text', 'text': 'New opening'}})
                    self.assertEqual(result['status'], 'legacy_installation_detected')
                self.assertFalse((root / 'attention-data').exists())
        asyncio.run(check())
