#!/usr/bin/env python3
"""Opt-in real Codex CLI smoke test. Requires global speech OFF; never changes it.

Runs one short model turn using the user's installed plugins and native hook
trust. Checks the actual queue database after the CLI has exited. No audio,
summary submission, alternate model, trust bypass, or configuration changes.
"""
import argparse
import json
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path


def state(database, session=None):
    with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as db:
        result = {'global_enabled': bool(db.execute(
            'SELECT global_voice_enabled FROM settings WHERE id=1').fetchone()[0])}
        if session:
            result.update(
                prompt_seen=bool(db.execute('SELECT 1 FROM turns WHERE provider=? AND session_id=?',
                                            ('codex', session)).fetchone()),
                stop_seen=bool(db.execute('SELECT 1 FROM events WHERE session_id=? AND kind=?',
                                          (session, 'global_disabled')).fetchone()),
                active_jobs=db.execute("SELECT COUNT(*) FROM jobs WHERE provider=? AND session_id=? "
                                       "AND status IN ('pending','speaking')", ('codex', session)).fetchone()[0],
                stored_bodies=db.execute("SELECT COUNT(*) FROM jobs WHERE provider=? AND session_id=? "
                                         "AND body<>''", ('codex', session)).fetchone()[0]
                              + db.execute('SELECT COUNT(*) FROM turn_summaries WHERE provider=? AND session_id=? '
                                           'AND body IS NOT NULL', ('codex', session)).fetchone()[0],
            )
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-live', action='store_true', help='Explicitly allow one real Codex model turn')
    parser.add_argument('--data-dir', type=Path,
                        default=Path.home() / 'Library/Application Support/Attention')
    args = parser.parse_args()
    if not args.run_live:
        parser.error('--run-live is required; this test uses your Codex account')
    database = args.data_dir / 'state/queue.sqlite3'
    if state(database)['global_enabled']:
        parser.error('Global speech must already be OFF; this test will not change your settings')
    prompt = ('This is a silent installation smoke test. Reply exactly ATTENTION_HOOK_SMOKE_OK. '
              'Do not call tools, read files, alter settings, or generate or submit spoken summaries. '
              'Global voice must remain disabled.')
    with tempfile.TemporaryDirectory(prefix='attention-hook-smoke-') as cwd:
        completed = subprocess.run(
            ['codex', 'exec', '--ephemeral', '--skip-git-repo-check', '--sandbox', 'read-only',
             '--color', 'never', '--json', '-C', cwd, prompt],
            capture_output=True, text=True, timeout=180,
        )
        events = []
        for line in completed.stdout.splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                pass
        session = next((e.get('thread_id') for e in events if e.get('type') == 'thread.started'), None)
        finals = [e['item'].get('text') for e in events if e.get('type') == 'item.completed'
                  and e.get('item', {}).get('type') == 'agent_message']
        tools = [e['item'].get('type') for e in events if e.get('type') == 'item.started'
                 and e.get('item', {}).get('type') in
                 ('command_execution', 'mcp_tool_call', 'web_search', 'file_change')]
        observed = state(database, session)
        deadline = time.monotonic() + 10
        while session and not observed['stop_seen'] and time.monotonic() < deadline:
            time.sleep(0.2)
            observed = state(database, session)
        ok = (completed.returncode == 0 and session and finals == ['ATTENTION_HOOK_SMOKE_OK']
              and not tools and observed['prompt_seen'] and observed['stop_seen']
              and not observed['global_enabled'] and not observed['active_jobs'] and not observed['stored_bodies'])
        print(json.dumps({'passed': bool(ok), 'exit_code': completed.returncode,
                          'expected_final': finals == ['ATTENTION_HOOK_SMOKE_OK'],
                          'tool_items': tools, **observed}, indent=2))
        if session:
            # Only this disposable test session; keep settings and other sessions.
            with sqlite3.connect(database) as db:
                for table in ('jobs', 'events', 'turn_summaries', 'turns', 'session_sources', 'session_preferences'):
                    db.execute('DELETE FROM ' + table + ' WHERE session_id=?', (session,))
        return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
