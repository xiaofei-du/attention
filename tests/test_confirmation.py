import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from nkc.confirmation import MUTATIONS, confirm_change, review_text
from nkc.mcp_server import create_server
from nkc.store import Store
from tests.test_native_identity import codex_meta, request_metadata


class ConfirmationTests(unittest.TestCase):
    def test_all_mutators_denied_and_invalid_schema_never_prompts(self):
        from mcp.types import CallToolRequest, CallToolRequestParams
        async def check():
            with tempfile.TemporaryDirectory() as tmp:
                store = Store(Path(tmp))
                token = store.begin_turn('codex', 'A', 'one')
                store.enqueue('codex', 'A', 'one', 'Pending canary.', delay=0)
                before = (store.settings(), store.session_preferences(), store.jobs())
                approver = AsyncMock(return_value=False)
                server = create_server(store, confirm_controls=True, approver=approver)
                invoke = server.request_handlers[CallToolRequest]
                patches = {
                    'set_voice_preferences': {'duck_media': True},
                    'set_starter_options': {'opening': {'type': 'text', 'text': 'Injected'}},
                    'set_global_enabled': {'enabled': False},
                    'set_session_enabled': {'enabled': False},
                    'set_summary_preferences': {'tone': 'upbeat'},
                    'clear_queue': {},
                }
                self.assertEqual(set(patches), MUTATIONS)
                for name, arguments in patches.items():
                    with request_metadata(codex_meta()):
                        result = (await invoke(CallToolRequest(params=CallToolRequestParams(
                            name=name, arguments=arguments)))).root
                    self.assertTrue(result.isError, name)
                self.assertEqual(approver.await_count, 6)
                self.assertEqual((store.settings(), store.session_preferences(), store.jobs()), before)
                result = (await invoke(CallToolRequest(params=CallToolRequestParams(
                    name='set_global_enabled', arguments={'enabled': True, 'confirmed': True})))).root
                self.assertTrue(result.isError)
                self.assertEqual(approver.await_count, 6)
        asyncio.run(check())

    def test_cancelled_confirmation_does_not_apply_later(self):
        from mcp.types import CallToolRequest, CallToolRequestParams
        async def check():
            with tempfile.TemporaryDirectory() as tmp:
                store = Store(Path(tmp))
                entered = asyncio.Event()
                async def approve(*args):
                    entered.set()
                    await asyncio.Event().wait()
                    return True
                server = create_server(store, confirm_controls=True, approver=approve)
                task = asyncio.create_task(server.request_handlers[CallToolRequest](CallToolRequest(
                    params=CallToolRequestParams(name='set_global_enabled', arguments={'enabled': False}))))
                await asyncio.wait_for(entered.wait(), 1)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertTrue(store.global_enabled())
        asyncio.run(check())

    def test_real_stdio_controls_and_summary_socket_use_same_private_store(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from nkc.submission import submit
        root = Path(__file__).resolve().parents[1]
        # Test-only dependency injection; production has no auto-approval flag.
        code = '''import asyncio, sys
sys.path.insert(0, sys.argv[1])
import nkc.mcp_server as module
original = module.create_server
async def deny(name, args):
    return False
def factory(*args, **kwargs):
    return original(*args, **kwargs, approver=deny)
module.create_server = factory
asyncio.run(module.serve(sys.argv[2], confirm_controls=True, summary_socket=sys.argv[3]))
'''
        async def check():
            with tempfile.TemporaryDirectory(prefix='ac-', dir='/tmp') as tmp:
                base = Path(tmp).resolve()
                store = Store(base / 'private')
                token = store.begin_turn('codex', 'A', 'one')
                endpoint = base / 'control' / 's.sock'
                params = StdioServerParameters(command=sys.executable,
                    args=['-I', '-c', code, str(root), str(store.root), str(endpoint)])
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as client:
                        await asyncio.wait_for(client.initialize(), 10)
                        self.assertEqual(len((await client.list_tools()).tools), 9)
                        result = await client.call_tool('set_global_enabled', {'enabled': False})
                        self.assertTrue(result.isError)
                        self.assertTrue(store.global_enabled())
                        result = await asyncio.to_thread(submit, endpoint, token,
                            {'why': 'Protect notifications.', 'done': 'Transport works.', 'next': ''})
                        self.assertEqual(result, {'staged': True})
                        status = await client.call_tool('get_status', {})
                        self.assertNotIn(token, json.dumps(status.structuredContent))
                self.assertFalse(endpoint.exists())
        asyncio.run(check())

    def test_full_review_escapes_display_controls_and_rejects_oversized_requests(self):
        text = review_text('set_starter_options', {'opening': {'type': 'text', 'text': '你好\u202eguy'}})
        self.assertIn('你好', text)
        self.assertNotIn('\u202e', text)
        self.assertIn('\\u202e', text)
        with self.assertRaises(ValueError):
            review_text('unknown', {})
        with self.assertRaises(ValueError):
            review_text('set_starter_options', {'opening': {'path': 'x' * 5000}})

    def test_cancel_timeout_and_process_errors_fail_closed(self):
        async def check():
            for result in (None, type('Result', (), {'returncode': 1, 'stdout': b''})(),
                           type('Result', (), {'returncode': 0, 'stdout': b'Cancel\n'})()):
                with patch('nkc.confirmation.anyio.run_process', new=AsyncMock(return_value=result)):
                    self.assertFalse(await confirm_change('set_global_enabled', {'enabled': True}))
            with patch('nkc.confirmation.anyio.run_process', new=AsyncMock(side_effect=TimeoutError)):
                self.assertFalse(await confirm_change('set_global_enabled', {'enabled': True}))
            with patch('nkc.confirmation.anyio.run_process', new=AsyncMock(side_effect=FileNotFoundError)):
                self.assertFalse(await confirm_change('set_global_enabled', {'enabled': True}))
            with patch('nkc.confirmation.anyio.run_process', new=AsyncMock(return_value=
                       type('Result', (), {'returncode': 0, 'stdout': b'Allow\n'})())) as process:
                self.assertTrue(await confirm_change('set_global_enabled', {'enabled': True}))
                self.assertEqual(process.call_args.args[0][0], '/usr/bin/osascript')
                self.assertNotIn('shell', process.call_args.kwargs)
        asyncio.run(check())

    def test_mutating_tool_gate_runs_per_call_reads_do_not_prompt(self):
        from mcp.types import CallToolRequest, CallToolRequestParams
        async def check():
            with tempfile.TemporaryDirectory() as tmp:
                store = Store(Path(tmp))
                store.set_global_enabled(False)
                approver = AsyncMock(return_value=False)
                server = create_server(store, confirm_controls=True, approver=approver)
                invoke = server.request_handlers[CallToolRequest]
                async def call(name, args):
                    return (await invoke(CallToolRequest(params=CallToolRequestParams(name=name, arguments=args)))).root
                await call('get_status', {})
                approver.assert_not_awaited()
                result = await call('set_global_enabled', {'enabled': True})
                self.assertTrue(result.isError)
                self.assertFalse(store.global_enabled())
                approver.return_value = True
                result = await call('set_global_enabled', {'enabled': True})
                self.assertFalse(result.isError)
                self.assertTrue(store.global_enabled())
                approver.return_value = False
                await call('set_global_enabled', {'enabled': False})
                self.assertTrue(store.global_enabled())
                self.assertEqual(approver.await_count, 3)
        asyncio.run(check())
