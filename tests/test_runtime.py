import json
import multiprocessing
import tempfile
import time
import unittest
from pathlib import Path

from nkc.runtime import handle_hook, run_worker
from nkc.store import Store


def message():
    return '<!-- nkc-summary:v1\n' + json.dumps({
        'why': '你希望通知能說清楚進展。',
        'done': '我已完成摘要和隊列的實作。',
        'next': '接下來驗證朗讀效果。',
    }, ensure_ascii=False) + '\n-->'


def drain_to_file(root):
    def sink(text, settings, is_cancelled):
        path = Path(root) / 'heard.txt'
        with path.open('a') as stream:
            stream.write('START ' + text + '\n')
        time.sleep(0.04)
        with path.open('a') as stream:
            stream.write('END ' + text + '\n')
        return True
    run_worker(Store(root), play=sink)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root)

    def test_prompt_context_is_returned_on_the_correct_hook_and_keeps_queued_speech(self):
        self.store.enqueue('codex', 'A', 'old', '舊通知。', delay=0)
        result = handle_hook('prompt', {'hook_event_name': 'UserPromptSubmit', 'session_id': 'A', 'turn_id': 'new'}, self.store)
        self.assertEqual(result['hookSpecificOutput']['hookEventName'], 'UserPromptSubmit')
        self.assertTrue(result['hookSpecificOutput']['additionalContext'])
        self.assertNotIn('decision', result)
        self.assertEqual(self.store.jobs()[0]['status'], 'pending')

    def test_stop_persists_summary_without_continuing_or_blocking_the_task(self):
        result = handle_hook('stop', {'hook_event_name': 'Stop', 'session_id': 'A', 'turn_id': '1',
                                     'last_assistant_message': message()}, self.store, start_worker=lambda root: None)
        self.assertEqual(result, {})
        self.assertEqual(len(self.store.jobs()), 1)
        self.assertEqual(self.store.jobs()[0]['body'], '你希望通知能說清楚進展。我已完成摘要和隊列的實作。接下來驗證朗讀效果。')

    def test_subagent_stop_is_not_a_main_task_notification(self):
        self.assertEqual(handle_hook('stop', {'hook_event_name': 'SubagentStop', 'session_id': 'A',
                                             'turn_id': '1', 'last_assistant_message': message()}, self.store), {})
        self.assertEqual(self.store.jobs(), [])

    def test_disabled_session_stop_records_cancellation_without_starting_a_worker(self):
        token = self.store.begin_turn('codex', 'A', '1')
        self.store.set_session_enabled(token, False)
        def forbidden_worker(root):
            self.fail('A disabled session must not start playback')
        self.assertEqual(handle_hook('stop', {'hook_event_name': 'Stop', 'session_id': 'A', 'turn_id': '1',
                         'last_assistant_message': message()}, self.store, start_worker=forbidden_worker), {})
        self.assertEqual([(j['status'], j['body']) for j in self.store.jobs()], [('cancelled', '')])
        self.assertIsNone(self.store.claim())

    def test_disabling_current_playback_stops_it_and_advances_to_another_session(self):
        token = self.store.begin_turn('codex', 'A', '1')
        self.store.enqueue('codex', 'A', '1', '甲。', delay=0)
        self.store.enqueue('codex', 'B', '1', '乙。', delay=0)
        heard = []
        def sink(text, settings, is_stopped):
            if '甲' in text:
                self.store.set_session_enabled(token, False)
                self.assertTrue(is_stopped())
                return False
            heard.append(text)
            return True
        run_worker(self.store, play=sink)
        self.assertEqual(heard, ['hey sunshine 乙。'])
        self.assertEqual([job['status'] for job in self.store.jobs()], ['cancelled', 'spoken'])

    def test_quick_reenable_does_not_resurrect_an_interrupted_notification(self):
        token = self.store.begin_turn('codex', 'A', '1')
        self.store.enqueue('codex', 'A', '1', '甲。', delay=0)
        def sink(text, settings, is_stopped):
            self.store.set_session_enabled(token, False)
            self.store.set_session_enabled(token, True)
            self.assertTrue(is_stopped(), 'Cancellation belongs to the job even after reenable')
            return False
        run_worker(self.store, play=sink)
        self.assertEqual(self.store.jobs()[0]['status'], 'cancelled')

    def test_missing_or_malformed_summary_is_recorded_without_reading_logs(self):
        result = handle_hook('stop', {'hook_event_name': 'Stop', 'session_id': 'A', 'turn_id': '1',
                                     'last_assistant_message': 'A normal answer without a notification'}, self.store)
        self.assertEqual(result, {})
        self.assertEqual(self.store.jobs(), [])
        self.assertEqual(self.store.events()[0]['kind'], 'summary_skipped')

    def test_missing_identity_cannot_queue_to_a_guessed_task(self):
        result = handle_hook('stop', {'hook_event_name': 'Stop', 'last_assistant_message': message()}, self.store)
        self.assertEqual(result, {})
        self.assertEqual(self.store.jobs(), [])

    def test_registered_short_reply_needs_no_visible_metadata(self):
        self.store.begin_turn('codex', 'A', '1')
        handle_hook('stop', {'hook_event_name': 'Stop', 'session_id': 'A', 'turn_id': '1',
                    'last_assistant_message': '**改好了**，直接看正常回覆就好。'}, self.store,
                    start_worker=lambda root: None)
        self.assertEqual(self.store.jobs()[0]['body'], '改好了，直接看正常回覆就好。')

    def test_long_reply_uses_only_its_own_staged_summary_after_stop(self):
        token = self.store.begin_turn('codex', 'A', '1')
        self.store.begin_turn('codex', 'B', '1')
        self.store.stage_summary(token, {'why': '你想移除註釋。', 'done': '我改好了。', 'next': ''})
        for session in ('B', 'A'):
            handle_hook('stop', {'hook_event_name': 'Stop', 'session_id': session, 'turn_id': '1',
                        'last_assistant_message': '詳細說明。' * 100}, self.store,
                        start_worker=lambda root: None)
        self.assertEqual([(j['session_id'], j['body']) for j in self.store.jobs()],
                         [('A', '你想移除註釋。我改好了。')])

    def test_staged_context_is_kept_even_for_a_short_answer_but_never_an_empty_final(self):
        token = self.store.begin_turn('codex', 'A', '1')
        self.store.stage_summary(token, {'why': '我們在做語音通知，讓你能同時追蹤多個任務。',
                                        'done': '我已改好摘要的上下文提示。', 'next': ''})
        event = {'hook_event_name': 'Stop', 'session_id': 'A', 'turn_id': '1'}
        handle_hook('stop', dict(event, last_assistant_message=''), self.store, start_worker=lambda root: None)
        self.assertEqual(self.store.jobs(), [])
        handle_hook('stop', dict(event, last_assistant_message='好了。'), self.store, start_worker=lambda root: None)
        self.assertEqual(self.store.jobs()[0]['body'],
                         '我們在做語音通知，讓你能同時追蹤多個任務。我已改好摘要的上下文提示。')

    def test_queued_summary_survives_followup_and_plays_once_in_received_order(self):
        token = self.store.begin_turn('codex', 'A', '1')
        self.store.stage_summary(token, {'why': '我們在做語音通知。',
                                        'done': '長回覆已整理成摘要。', 'next': ''})
        stop = {'hook_event_name': 'Stop', 'session_id': 'A', 'turn_id': '1',
                'last_assistant_message': '詳細技術說明。' * 100}
        for _ in range(2):
            handle_hook('stop', stop, self.store, start_worker=lambda root: None)
        handle_hook('prompt', {'hook_event_name': 'UserPromptSubmit', 'session_id': 'A',
                              'turn_id': '2'}, self.store)
        self.store.begin_turn('codex', 'B', '1')
        for session, turn, reply in [('B', '1', '另一個任務完成了。'), ('A', '2', '追問已回答。')]:
            handle_hook('stop', {'hook_event_name': 'Stop', 'session_id': session, 'turn_id': turn,
                                'last_assistant_message': reply}, self.store, start_worker=lambda root: None)
        # Advance only the debounce clock; use the real durable queue and worker.
        with self.store.db() as db:
            db.execute('UPDATE jobs SET ready_after=0')
        heard = []
        def sink(text, settings, is_stopped):
            self.assertFalse(is_stopped())
            heard.append(text)
            return True
        run_worker(Store(self.root), play=sink)
        run_worker(Store(self.root), play=sink)
        self.assertEqual(heard, ['hey sunshine 我們在做語音通知。長回覆已整理成摘要。',
                                 'hey sunshine 另一個任務完成了。', 'hey sunshine 追問已回答。'])
        self.assertEqual([job['status'] for job in self.store.jobs()], ['spoken'] * 3)

    def test_readable_reply_is_not_forced_into_summary_at_160_characters(self):
        self.store.begin_turn('codex', 'A', '1')
        reply = '這是一段內容完整、適合直接朗讀的普通回覆。' * 9
        self.assertGreater(len(reply), 160)
        handle_hook('stop', {'hook_event_name': 'Stop', 'session_id': 'A', 'turn_id': '1',
                    'last_assistant_message': reply}, self.store, start_worker=lambda root: None)
        self.assertEqual([job['body'] for job in self.store.jobs()], [reply])

    def test_missing_summary_cannot_read_an_entire_article(self):
        self.store.begin_turn('codex', 'A', '1')
        handle_hook('stop', {'hook_event_name': 'Stop', 'session_id': 'A', 'turn_id': '1',
                    'last_assistant_message': '這是長篇文章的一段內容。' * 100}, self.store,
                    start_worker=lambda root: None)
        self.assertEqual(self.store.jobs(), [])
        self.assertEqual(self.store.events()[0]['kind'], 'summary_skipped')

    def test_concurrent_workers_never_overlap_or_repeat_speech(self):
        self.store.enqueue('codex', 'A', '1', '甲。', delay=0)
        self.store.enqueue('codex', 'B', '1', '乙。', delay=0)
        # Production workers start fresh interpreters. Forking an initialized
        # macOS SQLite runtime can crash before the queue code runs.
        context = multiprocessing.get_context('spawn')
        workers = [context.Process(target=drain_to_file, args=(str(self.root),)) for _ in range(3)]
        for worker in workers:
            worker.start()
        try:
            for worker in workers:
                worker.join(5)
                self.assertFalse(worker.is_alive(), 'Worker did not exit')
                self.assertEqual(worker.exitcode, 0)
        finally:
            for worker in workers:
                if worker.is_alive():
                    worker.terminate()
                worker.join()
        self.assertEqual((self.root / 'heard.txt').read_text().splitlines(), [
            'START hey sunshine 甲。', 'END hey sunshine 甲。',
            'START hey sunshine 乙。', 'END hey sunshine 乙。',
        ])
        self.assertEqual([j['status'] for j in self.store.jobs()], ['spoken', 'spoken'])

    def test_disabling_playback_cancels_current_and_next_notifications(self):
        self.store.enqueue('codex', 'A', '1', '甲。', delay=0)
        self.store.enqueue('codex', 'B', '1', '乙。', delay=0)
        def cancelled_sink(text, settings, is_cancelled):
            self.store.set_global_enabled(False)
            return False
        run_worker(self.store, play=cancelled_sink)
        self.assertEqual([j['status'] for j in self.store.jobs()], ['cancelled', 'cancelled'])
        self.store.set_global_enabled(True)
        drain_to_file(str(self.root))
        self.assertEqual([j['status'] for j in self.store.jobs()], ['cancelled', 'cancelled'])

    def test_playback_error_is_visible_and_not_retried_automatically(self):
        self.store.enqueue('codex', 'A', '1', '甲。', delay=0)
        def failure(text, settings, is_cancelled):
            raise RuntimeError('Audio device unavailable')
        run_worker(self.store, play=failure)
        self.assertEqual(self.store.jobs()[0]['status'], 'failed')
        self.assertEqual(self.store.jobs()[0]['error'], 'Audio device unavailable')

    def test_empty_start_removes_the_opening_without_changing_the_answer(self):
        self.store.set_start('')
        self.store.enqueue('codex', 'A', '1', '改好了。', delay=0)
        heard = []
        def sink(text, settings, cancelled):
            heard.append(text)
            return True
        run_worker(self.store, play=sink)
        self.assertEqual(heard, ['改好了。'])


if __name__ == '__main__':
    unittest.main()
