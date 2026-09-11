"""Native host metadata drives real MCP session controls; no audio or live data."""
import asyncio
import json
import sys
import tempfile
import unittest
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from nkc.runtime import handle_hook
from nkc.store import Store

ROOT = Path(__file__).resolve().parents[1]


def codex_meta(session='A', turn='one', **extra):
    return {'threadId': session, 'x-codex-turn-metadata': {
        'thread_id': session, 'session_id': session, 'turn_id': turn,
        'thread_source': 'user', **extra}}


def bind(store, call='call-a', session='A', args=None, tool='set_session_enabled', **extra):
    return handle_hook('control-context', {
        'hook_event_name': 'PreToolUse', 'session_id': session, 'tool_use_id': call,
        'tool_name': 'mcp__plugin_attention_attention__' + tool,
        'tool_input': {'enabled': False} if args is None else args, **extra},
        store, provider='claude-code')


@contextmanager
def request_metadata(meta):
    from mcp.server.lowlevel.server import request_ctx
    from mcp.shared.context import RequestContext
    from mcp.types import RequestParams
    key = request_ctx.set(RequestContext(request_id=1, meta=RequestParams.Meta(**meta),
                                        session=None, lifespan_context=None))
    try:
        yield
    finally:
        request_ctx.reset(key)


class NativeIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.store.set_global_enabled(False)
        self.store.set_summary_preferences(enabled=False)
        for provider in ('codex', 'claude-code'):
            for session in ('A', 'B'):
                self.store.begin_turn(provider, session, 'one')

    @asynccontextmanager
    async def connect(self, provider='codex'):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        async with stdio_client(StdioServerParameters(command=sys.executable,
                args=[str(ROOT / 'mcp_server.py'), '--state-dir', self.tmp.name]
                     + (['--provider', provider] if provider != 'codex' else []), env={
                          'CLAUDE_CODE_SESSION_ID': 'wrong-startup-session',
                          'CODEX_THREAD_ID': 'wrong-inherited-session'})) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                yield client

    async def call(self, client, name='set_session_enabled', args=None, meta=None, error=False):
        result = await client.call_tool(name, {'enabled': False} if args is None else args, meta=meta)
        self.assertEqual(bool(result.isError), error, result)
        return result.structuredContent if not error else result

    def test_codex_parallel_sessions_follow_each_call_not_connection_or_environment(self):
        async def run():
            async with self.connect() as client:
                results = await asyncio.gather(
                    self.call(client, meta=codex_meta('A')),
                    self.call(client, meta=codex_meta('B')))
                self.assertEqual({r['session_id'] for r in results}, {'A', 'B'})
                self.assertFalse(self.store.session_enabled('codex', 'A'))
                self.assertFalse(self.store.session_enabled('codex', 'B'))
                self.assertTrue(self.store.session_enabled('claude-code', 'A'))
                status = await self.call(client, 'get_status', {'scope': 'session'}, codex_meta('A'))
                self.assertFalse(status['session']['effective_enabled'])
                self.assertIsNone((await self.call(client, 'get_status', {}))['session'])
                await self.call(client, args={'enabled': True}, meta=codex_meta('B'))
                self.assertFalse(self.store.session_enabled('codex', 'A'))
                self.assertTrue(self.store.session_enabled('codex', 'B'))
        asyncio.run(run())

    def test_codex_missing_conflicting_stale_child_and_model_identity_fail_closed(self):
        async def run():
            async with self.connect() as client:
                self.store.begin_turn('codex', 'A', 'two')
                cases = [None, {}, {'threadId': 'A'}, codex_meta('A', 'one'),
                         codex_meta('unknown'), codex_meta('A', 'two', thread_id='B'),
                         codex_meta('A', 'two', session_id='B'),
                         codex_meta('A', 'two', thread_source='subagent'),
                         codex_meta('A', 'two', thread_source=None),
                         {'claudecode/toolUseId': 'call-a'}]
                for meta in cases:
                    await self.call(client, meta=meta, error=True)
                for key in ('token', 'session_id', 'provider'):
                    await self.call(client, args={'enabled': False, key: 'B'},
                                    meta=codex_meta('A', 'two'), error=True)
                self.assertEqual(self.store.session_preferences(), [])
                await self.call(client, 'set_summary_preferences', {'enabled': True})
                self.assertTrue(self.store.summary_preferences()['enabled'])
        asyncio.run(run())

    def test_claude_silent_bridge_parallel_reordered_calls_and_reconnect(self):
        async def run():
            self.assertEqual(bind(self.store, 'a', 'A'), {})
            self.assertEqual(bind(self.store, 'b', 'B'), {})
            async with self.connect('claude-code') as client:
                result = await self.call(client, meta={'claudecode/toolUseId': 'b'})
                self.assertEqual(result['session_id'], 'B')
            async with self.connect('claude-code') as client:
                result = await self.call(client, meta={'claudecode/toolUseId': 'a'})
                self.assertEqual(result['session_id'], 'A')
                self.assertEqual(bind(self.store, 'a', 'A'), {})
                await self.call(client, meta={'claudecode/toolUseId': 'a'}, error=True)
                self.assertTrue(self.store.session_enabled('codex', 'A'))
                self.assertFalse(self.store.session_enabled('claude-code', 'A'))
                self.assertFalse(self.store.session_enabled('claude-code', 'B'))
                bind(self.store, 'status', 'A', {'scope': 'session'}, 'get_status')
                status = await self.call(client, 'get_status', {'scope': 'session'},
                                         {'claudecode/toolUseId': 'status'})
                self.assertEqual(status['session']['session_id'], 'A')
        asyncio.run(run())

    def test_claude_switched_session_stale_arguments_expiry_child_and_foreign_calls(self):
        async def run():
            async with self.connect('claude-code') as client:
                for call, session, extra in [('old', 'A', {}), ('child', 'B', {'agent_id': 'child'}),
                                              ('unknown', 'unknown', {})]:
                    self.assertEqual(bind(self.store, call, session, **extra), {})
                self.store.begin_turn('claude-code', 'A', 'two')
                for call in ('old', 'child', 'unknown', 'absent'):
                    await self.call(client, meta={'claudecode/toolUseId': call}, error=True)
                bind(self.store, 'changed', 'B')
                await self.call(client, args={'enabled': True}, meta={'claudecode/toolUseId': 'changed'}, error=True)
                await self.call(client, meta={'claudecode/toolUseId': 'changed'}, error=True)
                bind(self.store, 'expired', 'B')
                with self.store.db() as db:
                    db.execute('UPDATE control_bindings SET expires=0')
                await self.call(client, meta={'claudecode/toolUseId': 'expired'}, error=True)
                await self.call(client, meta=codex_meta('B'), error=True)
                self.assertEqual(self.store.session_preferences(), [])
                # Same running MCP connection, new native session/turn after a switch.
                self.store.begin_turn('claude-code', 'new-session', 'new-turn')
                bind(self.store, 'new-call', 'new-session')
                result = await self.call(client, meta={'claudecode/toolUseId': 'new-call'})
                self.assertEqual(result['session_id'], 'new-session')
                self.assertTrue(self.store.session_enabled('claude-code', 'A'))
        asyncio.run(run())

    def test_native_confirmation_cancellation_and_session_change_cannot_apply_old_call(self):
        from nkc.mcp_server import create_server
        from mcp.types import CallToolRequest, CallToolRequestParams
        async def run():
            for provider in ('codex', 'claude-code'):
                for outcome in ('deny', 'switch', 'cancel'):
                    self.store.begin_turn(provider, 'A', outcome)
                    meta = codex_meta('A', outcome)
                    if provider == 'claude-code':
                        bind(self.store, outcome, 'A')
                        meta = {'claudecode/toolUseId': outcome}
                    reviewed = []
                    async def approve(name, arguments):
                        reviewed.append((name, arguments))
                        if outcome == 'switch':
                            self.store.begin_turn(provider, 'A', outcome + '-next')
                            return True
                        if outcome == 'cancel':
                            raise asyncio.CancelledError()
                        return False
                    server = create_server(self.store, provider=provider, confirm_controls=True, approver=approve)
                    async def invoke():
                        with request_metadata(meta):
                            return (await server.request_handlers[CallToolRequest](CallToolRequest(
                                params=CallToolRequestParams(name='set_session_enabled',
                                                            arguments={'enabled': False})))).root
                    if outcome == 'cancel':
                        with self.assertRaises(asyncio.CancelledError):
                            await invoke()
                    else:
                        self.assertTrue((await invoke()).isError)
                    self.assertEqual(reviewed, [('set_session_enabled', {'enabled': False})])
                    self.assertTrue(self.store.session_enabled(provider, 'A'))
                    if provider == 'claude-code':
                        self.assertTrue((await invoke()).isError)
                        self.assertEqual(len(reviewed), 1)
        asyncio.run(run())

    def test_conflicting_duplicate_bindings_are_poisoned_and_only_digests_are_saved(self):
        from nkc.control_context import resolve_control_token
        bind(self.store, 'collision', 'A')
        bind(self.store, 'collision', 'B')
        with self.assertRaises(ValueError):
            resolve_control_token(self.store, 'claude-code', 'set_session_enabled', {'enabled': False},
                                  {'claudecode/toolUseId': 'collision'})
        bind(self.store, 'private', 'A', {'enabled': False, 'untrusted': 'private-argument-canary'})
        self.assertNotIn(b'private-argument-canary', (self.store.root / 'queue.sqlite3').read_bytes())
        with self.store.db() as db:
            db.execute('UPDATE control_bindings SET expires=0')
        with Store(self.store.root).db() as db:
            for row in db.execute('SELECT * FROM control_bindings'):
                self.assertEqual(row['session_id'], '')
                self.assertEqual(row['turn_id'], '')
                self.assertEqual(row['arguments_digest'], '')
                self.assertEqual(row['consumed'], 1)
        self.assertEqual(self.store.session_preferences(), [])

    def test_delayed_duplicate_after_expiry_cannot_rearm_or_bind_a_new_turn(self):
        from nkc.control_context import resolve_control_token
        for consumed in (False, True):
            call = str(consumed)
            bind(self.store, call, 'A')
            if consumed:
                resolve_control_token(self.store, 'claude-code', 'set_session_enabled', {'enabled': False},
                                      {'claudecode/toolUseId': call})
            with self.store.db() as db:
                db.execute('UPDATE control_bindings SET expires=0')
            self.store = Store(self.store.root)
            self.store.begin_turn('claude-code', 'A', 'new-' + call)
            bind(self.store, call, 'A')
            with self.assertRaises(ValueError):
                resolve_control_token(self.store, 'claude-code', 'set_session_enabled', {'enabled': False},
                                      {'claudecode/toolUseId': call})


if __name__ == '__main__':
    unittest.main()
