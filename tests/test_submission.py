import json
import socket
import tempfile
import threading
import time
from unittest.mock import patch
import unittest
from pathlib import Path

from nkc.store import Store
from nkc.runtime import handle_hook, run_worker
from nkc.submission import SummaryBroker, SharedSummaryBroker, submit


class SubmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='as-', dir='/tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.store = Store(self.root / 'private')
        self.endpoint = self.root / 'control' / 's.sock'
        self.token = self.store.begin_turn('codex', 'A', 'one')
        self.payload = {'why': 'We are protecting notifications.', 'done': 'The change is ready.', 'next': ''}

    def raw(self, value):
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(3)
            client.connect(str(self.endpoint))
            client.sendall(value + b'\n')
            with client.makefile('rb') as response:
                return json.loads(response.readline(1024))

    def test_current_turn_stages_then_stop_uses_original_queue_without_playing(self):
        with SummaryBroker(self.store, self.endpoint):
            self.assertEqual(submit(self.endpoint, self.token, self.payload), {'staged': True})
        self.assertFalse(self.endpoint.exists())
        self.assertEqual(self.store.jobs(), [])
        handle_hook('stop', {'hook_event_name': 'Stop', 'session_id': 'A', 'turn_id': 'one',
                            'last_assistant_message': 'Technical explanation. ' * 100}, self.store,
                    start_worker=lambda _: None)
        with self.store.db() as db:
            db.execute('UPDATE jobs SET ready_after=0')
        heard = []
        run_worker(self.store, play=lambda text, settings, cancelled: heard.append(text) or True)
        self.assertIn('The change is ready.', heard[0])
        self.assertEqual(len(heard), 1)

    def test_controls_invalid_frames_and_stale_tokens_cannot_mutate_preferences(self):
        before = self.store.settings()
        with SummaryBroker(self.store, self.endpoint):
            for value in [b'not json', b'[]', b'x' * 10001,
                          json.dumps({'token': self.token, 'summary': self.payload, 'enabled': True}).encode(),
                          json.dumps({'token': self.token, 'summary': {'why': 'x', 'done': 'y', 'next': '', 'tool': 'set_global_enabled'}}).encode(),
                          json.dumps({'token': 'other', 'summary': self.payload}).encode()]:
                self.assertFalse(self.raw(value)['staged'])
            self.store.begin_turn('codex', 'A', 'two')
            with self.assertRaises(ValueError):
                submit(self.endpoint, self.token, self.payload)
        self.assertEqual(self.store.settings(), before)

    def test_muted_summary_is_discarded_and_never_changes_mute(self):
        self.store.set_global_enabled(False)
        with SummaryBroker(self.store, self.endpoint), self.assertRaises(ValueError):
            submit(self.endpoint, self.token, self.payload)
        self.assertFalse(self.store.global_enabled())
        self.assertIsNone(self.store.summary_for_turn('codex', 'A', 'one')['body'])

    def test_other_provider_keeps_its_own_turn_and_no_tokens_are_returned(self):
        other = self.store.begin_turn('claude-code', 'A', 'one')
        with SummaryBroker(self.store, self.endpoint):
            result = submit(self.endpoint, self.token, self.payload)
        self.assertNotIn(other, json.dumps(result))
        self.assertIsNone(self.store.summary_for_turn('claude-code', 'A', 'one')['body'])

    def test_symlink_regular_file_and_competing_listener_are_not_overwritten(self):
        self.endpoint.parent.mkdir(mode=0o700)
        target = self.root / 'keep'
        target.write_text('keep')
        self.endpoint.symlink_to(target)
        with self.assertRaises(ValueError):
            with SummaryBroker(self.store, self.endpoint):
                pass
        self.assertEqual(target.read_text(), 'keep')
        self.endpoint.unlink()
        self.endpoint.write_text('keep')
        with self.assertRaises(ValueError):
            with SummaryBroker(self.store, self.endpoint):
                pass
        self.endpoint.unlink()
        with SummaryBroker(self.store, self.endpoint):
            with self.assertRaises((ValueError, BlockingIOError)):
                with SummaryBroker(self.store, self.endpoint):
                    pass
            self.assertEqual(submit(self.endpoint, self.token, self.payload), {'staged': True})

    def test_isolated_prompt_uses_only_socket_submission_and_mcp_controls(self):
        prompt = handle_hook('prompt', {'hook_event_name': 'UserPromptSubmit', 'session_id': 'A',
                              'turn_id': 'one'}, self.store, summary_socket=self.endpoint)
        context = prompt['hookSpecificOutput']['additionalContext']
        self.assertIn('submit.py', context)
        self.assertIn(str(self.endpoint), context)
        self.assertNotIn('--state-dir', context)
        self.assertNotIn('run.py', context)
        self.assertNotIn('global-voice', context)
        self.assertIn('confirmation', context)

    def test_two_mcp_owners_share_and_survivor_takes_over(self):
        first = SharedSummaryBroker(self.store, self.endpoint)
        second = SharedSummaryBroker(self.store, self.endpoint)
        with first, second:
            self.assertEqual(submit(self.endpoint, self.token, self.payload), {'staged': True})
            first.__exit__(None, None, None)
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                try:
                    result = submit(self.endpoint, self.token, self.payload)
                    break
                except (OSError, ValueError):
                    time.sleep(.02)
            else:
                self.fail('Surviving MCP did not acquire the summary socket')
            self.assertEqual(result, {'staged': True})
        self.assertFalse(self.endpoint.exists())

    def test_slow_connections_are_bounded_and_shutdown_does_not_wait_for_them(self):
        with SummaryBroker(self.store, self.endpoint) as broker:
            clients = []
            try:
                for _ in range(8):
                    client = socket.socket(socket.AF_UNIX)
                    client.settimeout(1)
                    clients.append(client)
                    try:
                        client.connect(str(self.endpoint))
                    except OSError:
                        pass  # A full listen backlog may reject excess clients.
                time.sleep(.1)
                with broker.clients_lock:
                    self.assertLessEqual(len(broker.clients), 4)
                started = time.monotonic()
            finally:
                broker.__exit__(None, None, None)
                for client in clients:
                    client.close()
            self.assertLess(time.monotonic() - started, 1.5)

    def test_lock_symlinks_and_hard_links_are_refused(self):
        self.endpoint.parent.mkdir(mode=0o700)
        target = self.root / 'keep'
        target.write_text('keep')
        lock = self.endpoint.with_name(self.endpoint.name + '.lock')
        lock.symlink_to(target)
        with self.assertRaises(OSError):
            with SummaryBroker(self.store, self.endpoint):
                pass
        lock.unlink()
        import os
        os.link(target, lock)
        with self.assertRaises(ValueError):
            with SummaryBroker(self.store, self.endpoint):
                pass
        self.assertEqual(target.read_text(), 'keep')

    def test_trickle_bytes_cannot_extend_absolute_frame_deadline(self):
        with SummaryBroker(self.store, self.endpoint):
            with socket.socket(socket.AF_UNIX) as client:
                client.settimeout(.5)
                client.connect(str(self.endpoint))
                deadline = time.monotonic() + 2.3
                while time.monotonic() < deadline:
                    try:
                        client.sendall(b' ')
                    except OSError:
                        break
                    time.sleep(.15)
                result = json.loads(client.recv(1024))
                self.assertEqual(result, {'staged': False})
                self.assertEqual(submit(self.endpoint, self.token, self.payload), {'staged': True})

    def test_shutdown_during_database_contention_cannot_commit_after_lease_release(self):
        broker = SummaryBroker(self.store, self.endpoint).__enter__()
        entered = threading.Event()
        original = self.store.stage_summary
        def observed(*args, **kwargs):
            entered.set()
            return original(*args, **kwargs)
        with self.store.db() as lock:
            lock.execute('BEGIN IMMEDIATE')
            with patch.object(self.store, 'stage_summary', side_effect=observed):
                with socket.socket(socket.AF_UNIX) as client:
                    client.connect(str(self.endpoint))
                    client.sendall((json.dumps({'token': self.token, 'summary': self.payload}) + '\n').encode())
                    self.assertTrue(entered.wait(1))
                    started = time.monotonic()
                    broker.__exit__(None, None, None)
                    self.assertLess(time.monotonic() - started, 2)
        time.sleep(.1)
        self.assertIsNone(self.store.summary_for_turn('codex', 'A', 'one')['body'])
