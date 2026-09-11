# Claude Code notification integration

> **For agentic workers:** Use superpowers:executing-plans to implement these tasks in this session. The user approved this implementation; no separate task or MCP is needed.

**Goal:** Let local Claude Code sessions use the existing spoken notifications alongside Codex.

**Architecture:** Normalize Claude's session_id + prompt_id at the hook boundary and retain the existing token-based summary protocol. Both providers use one SQLite queue and one native audio lock. Install only two command hooks into Claude's settings.json.

**Tech Stack:** Python standard library, SQLite, Claude Code command hooks, existing macOS player.

**Spec:** docs/plan.md and the approved two-hook proposal in this conversation.

## Global constraints

- Summary written by the original session; no separate LLM summarizer, prompt-type hook, MCP or plugin.
- Preserve the explicitly selected shared opening; the user changed it from Ping to the exact text 你好美女 during this implementation. Shared playback stays enabled. Default new-session speech enabled, per-provider session preferences isolated.
- Claude Code >= 2.1.196 provides prompt_id. Missing identity skips with a diagnostic, never guesses from another session or transcript.
- Existing Codex commands/configuration remain compatible, including hook trust.
- Preserve unrelated Claude settings/hooks, back up before atomic edits, make install/uninstall idempotent.
- Hook only stages/enqueues and exits. Detached worker owns synthesis/playback after claude -p exits.
- Main-session Stop only; ignore subagent events and StopFailure. Defer while background_tasks is nonempty, allow the later empty Stop even if stop_hook_active is true. Persistent background monitors therefore delay notification in this first version. Stop remains a provisional signal if another hook forces continuation.

## Task 1: Provider boundary and shared queue

**Files:** nkc/runtime.py, nkc/store.py, run.py, summary-prompt.txt, tests/test_claude.py.

**Interface:** handle_hook(action, event, store, start_worker=start_worker, provider='codex'). CLI: hook prompt|stop --provider codex|claude-code; default remains codex.

- [x] Add failing CLI tests: Claude UserPromptSubmit issues usable token; summary command stages the original session's prose; Stop queues that prose instead of the long final. No visible metadata.
- [x] Run `/usr/bin/python3 -m unittest discover -s tests -p test_claude.py -v`; confirm provider flag is unsupported.
- [x] Add explicit provider selection, map Claude prompt_id to store turn_id, keep Codex turn_id mapping. Use provider in all Store calls. Skip agent_id and in-flight background tasks for Claude.
- [x] Test direct replies, malformed/missing identities, repeated Stop, old Stop after a new prompt, and original queued-summary retention.
- [x] Test same session IDs across providers, per-session disable/re-enable/new-session default, and shared FIFO with competing workers.

Example contract:
```python
event = dict(hook_event_name='UserPromptSubmit', session_id='A', prompt_id='one')
result = handle_hook('prompt', event, store, provider='claude-code')
assert result['hookSpecificOutput']['hookEventName'] == 'UserPromptSubmit'
```

## Task 2: Installation and real Claude verification

**Files:** nkc/install.py, run.py, tests/test_claude.py, README.md, docs/plan.md.

**Interfaces:** definition(provider='codex'), install_hooks(home, provider='codex'), uninstall_hooks(home, provider='codex'). CLI install/uninstall/hooks --provider; --claude-home defaults to CLAUDE_CONFIG_DIR or ~/.claude. Existing --codex-home stays supported.

- [x] Add failing tests for Claude settings merging, backups, idempotency, invalid JSON untouched, provider-specific commands and synchronous enqueue hooks. Uninstall one provider must not pause both providers' shared player.
- [x] Select hooks.json for Codex and settings.json for Claude. Reuse existing atomic merge. Only Codex Stop uses async=true; Claude command finishes enqueue before exit.
- [x] Run targeted tests then the full suite with `/usr/bin/python3 -m unittest discover -s tests -q`.
- [x] Install the tested two Claude hooks in the user's settings, preserving other settings. Read back the actual config.
- [x] Run a bounded real Claude task on a local fixture, using only required tools and normal permissions. Verify injected context, original Claude summary submission, Stop identity, distinct queued summary, and completed playback. Test a concise follow-up and session mute with the same session where possible.
- [x] Document verified behavior and remaining limits; update the user's quickstart copy in outputs. Do not claim subjective audio quality from process status.

No commit required: this repository has no initial commit and contains all prior implementation as untracked files. Preserve that state.

## Findings during execution

- Added a failing reproduction for stale background summaries; deferral now clears the waiting summary without invalidating its token.
- Two real Claude long replies initially did not stage summaries. The installed 2.1.268 client replaced the original 10KB-plus additionalContext with a 2KB preview. Official docs confirm the 10,000-character cap. The shared prompt is now about 6.8KB after expansion and the original session sees all commands inline. Added the failing inline-limit regression before rewriting.
- New Claude session did call summary itself after the prompt fix. The non-interactive dontAsk acceptance harness rejected the quoted JSON heredoc despite narrow prefix rules. Continued with normal interactive approval of the specific local summary command; no general Bash allow or permission-mode change installed.
- Full suite after these changes: 103 tests passed. Interactive Claude staged its own 288-character summary, which entered live playback. Live job 52 completed playback (1485-character final -> 288-character original-session summary); job 53 completed direct playback (36-character final). Both have null error. The original Claude session then used its current injected token to disable only itself. The current Codex session and shared playback remain enabled.
