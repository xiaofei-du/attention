# Codex completion handoff

Codex cancels unfinished background hooks when a session ends. With `async: true`
on Attention's `Stop`, a one-shot `codex exec` can exit before the hook reaches
SQLite. A persistent app-server session leaves enough time for the same handler
to finish, which explains why manually invoking hooks or testing only the desktop
path did not expose the problem.

Reference: [Codex background hook limitations](https://learn.chatgpt.com/docs/hooks#limitations).

All generated Codex completion handlers now use the default synchronous execution.
The hook validates the event, persists the notification (or a body-free cancellation
receipt when globally or individually muted), starts a detached worker when needed, and returns.
It does not wait for synthesis or playback. Claude's completion hook already used
this arrangement.

Cancelled receipts contain no reply text and prevent delayed duplicate completions
from replaying after re-enable, including within the same turn. Session mute is
checked again inside the queue transaction to cover changes after the hook's
initial check. Claude background waits discard any staged summary but create no
completion receipt, so a real completion after re-enable remains eligible.

The three configuration entry points are the local installer, marketplace builder,
and optional isolation profile generator. Their regression checks prevent an
asynchronous completion handler from being reintroduced into any of them.

## Live verification

After installing and trusting the generated hooks, leave global speech disabled
and explicitly run:

```sh
.venv/bin/python scripts/verify_codex_hooks.py --run-live
```

This uses the local Codex account for one short, ephemeral model turn. It does not
generate a summary or change speech settings. After Codex exits, it checks that
both prompt and completion events reached the installed Attention database, no
playable jobs or notification bodies remain, and global speech is still off.
Only records belonging to the disposable test session are then removed. The test
fails if the hooks are disabled, untrusted, or completion is lost during shutdown.

Changing `Stop` from asynchronous to synchronous changes its trusted definition.
Review the updated hook in Codex before repeating the native test; do not bypass
hook trust or copy trusted hashes. Config-generation tests alone do not prove the
updated host lifecycle works.

## Upgrades while tasks are running

The verified durable runtime is not enough to preserve an already loaded hook:
the host's command still starts at its original `${PLUGIN_ROOT}/launch.py`.
Codex 0.154.0 removed the previous version's cache during a version-changing
native install, leaving an active desktop Stop hook pointing to a missing file.

For this repository's local updates, publish the new bundle to the existing
marketplace, then use:

```sh
.venv/bin/python scripts/update_codex_plugin.py
```

This still invokes native `codex plugin add attention@attention-marketplace`.
It validates and temporarily snapshots existing Attention packages, then restores
only version directories removed by that command. Restored content is unchanged;
current installed packages and native trust records are not overwritten. Cached
old launchers and durable old runtimes must remain until their tasks have finished.

This is a local update helper, not a change to Codex's own marketplace updater.
Direct native updates outside this helper can still remove launchers referenced
by running tasks. Public updates should wait for those tasks to finish unless
the host supports retaining their old plugin roots.

Verified on macOS with Codex 0.154.0 on 2026-09-11: after reviewing the updated
installed hook, the real CLI exited successfully and both prompt and Stop events
were present. Global speech remained off, no active jobs or bodies remained, and
the test session made no tool calls. The pre-fix CLI run missed Stop; the same
one-shot lifecycle succeeds with the synchronous queue handoff.

## 0.1.1 follow-up: retained runtime as the actual hook entry

A restored 0.1.0 cache disappeared again on 2026-09-11 while the old task was
running. The observed cleanup coincided with plugin discovery, but isolated
`hooks/list`, `plugin/list` and `plugin/installed` calls did not reproduce deletion;
the exact cleaner has not been established. Snapshotting around explicit updates
was not sufficient protection.

The new regression runs real generated hook commands with disposable settings:
bootstrap normally, remove the plugin root, then run its saved Stop command.
Both providers failed with missing `launch.py` before the change. Version 0.1.1
embeds a small stdlib entry in the hook command and pins the full payload digest.
The same saved command now verifies and runs the exact retained runtime without
its former cache. Missing, modified and alternative-version runtimes never lead
to execution of substitute code. Existing 0.1.0 commands still require a reload.
