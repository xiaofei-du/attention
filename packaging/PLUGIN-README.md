# Attention! 📣

Your agent has something to report.

Local spoken notifications for Codex and Claude Code. Short replies can be read directly; longer rounds receive a conversational update written by the original agent. Multiple sessions share one queue. No extra LLM API or API key.

## Requirements

- macOS 14.2+ on Apple Silicon or Intel. Real speaker playback has been verified on the developer's Apple Silicon MacBook Pro; Intel binaries are built and inspected, not hardware-tested.
- `uv` available on the client process PATH. Install it once from https://docs.astral.sh/uv/getting-started/installation/ (Homebrew: `brew install uv`). The first launch downloads Python 3.12 and pinned MCP dependencies; SDK wheels are installed with mandatory SHA-256 verification into a private environment, reused on later launches without re-resolving dependencies. Source builds are disabled and the index is fixed to PyPI. Xcode is not required on recipient computers.
- Codex with lifecycle hooks, or Claude Code 2.1.196+.
- Review/trust the plugin hooks in your client. Ordinary playback needs no system-audio recording permission. Lowering other media is optional and off on new installs. Explicitly enable it before granting macOS system-audio permission. No microphone, media saving or uploading.

## Install from GitHub

Run these commands from any directory. The plugin manager downloads the package
from [xiaofei-du/attention](https://github.com/xiaofei-du/attention). No local
marketplace folder or source build is needed.

Codex:

```sh
codex plugin marketplace add xiaofei-du/attention
codex plugin add attention@xiaofei-du
```

Claude Code:

```sh
claude plugin marketplace add xiaofei-du/attention
claude plugin install attention@xiaofei-du
```

Reopen the client or reload its plugins, then review the hooks. First dependency setup can take longer than a normal launch; reopen once setup finishes if your client times out. This is the publisher’s GitHub marketplace, not an official OpenAI or Anthropic directory listing.

## Updating an existing installation

For GitHub updates and migration from `attention@attention-marketplace`, read
[the upgrade guide](https://github.com/xiaofei-du/attention/blob/main/docs/upgrading.md).
Finish active tasks before replacing an old installation. Shared Attention data
is preserved; do not delete its Application Support directory.

Version 0.1.1 pins each hook command to its exact payload. After its first normal
startup, the hook can run from Attention's retained runtime even if the client
removes the plugin cache. It verifies the pinned manifest and all payload files
before running code, and never substitutes a newer version. If neither verified
copy is available, speech is skipped and the next prompt requests plugin repair.

When upgrading from 0.1.0, finish active tasks and reload the plugin or restart the
client so it loads the new hook commands. Review changed hooks when requested.
Already-loaded old commands cannot gain this protection from a package update.
The bundled Codex update helper preserves old launchers during its own install
operation, but cannot prevent a later independent cache cleanup.
See `docs/upgrading.md` inside either plugin directory for details.

## Getting started and help

After the hooks are trusted, Attention offers one brief first-use introduction
across the shared Codex/Claude installation. The agent presents it in your language
when the answer allows ordinary prose. Strict output formats take priority, and a
busy hook context can defer the introduction. No preferences change during help.

Ask **“Attention help”** or **“Attention 怎麼用”** at any time. The bundled help skill
is also available as `$attention:attention-help` in Codex and `/attention:attention-help` in
Claude Code. Its full guide loads on demand, not on every coding turn.

### Choose your starter

The starter comes before the spoken update. It can be:

| Type | Example request | What happens |
|---|---|---|
| **Text** | “開場改成『你好美女』” | Speaks your exact text, kept until you change it. |
| **Apple built-in alert sound** | “列出 Apple 自帶提示音” | Choose from sounds available on your Mac. |
| **Custom audio file** | “用這個 MP3 當開場” and provide the local file | Imports a copy and plays your clip. |
| **No starter** | “不要開場” | Goes straight to the update. |

Apple sounds and custom clips replace the text opening, then the update is spoken.
Custom files support **MP3, WAV, M4A, AIF/AIFF**, up to **30 seconds / 20 MiB**.
Provide a local file/path through your client; Attention has no separate upload UI
and does not upload the audio. Optional session-name reporting is controlled
separately and can still play when the starter is empty.

### Useful things to ask

- “播報時把 Spotify 等背景媒體降低” — enables optional media lowering. It is off
  on new installs and may need macOS system-audio permission; no microphone.
- “換男聲” or “有哪些音色？” — choose a voice preference or list installed voices.
- “關閉這個 session 語音” — mutes only this session.
- “全域關閉語音” — stops speech, clears pending updates, and discards new ones
  while off. Re-enabling preserves individually muted sessions.
- “清掉待播通知” — clears the queue while current speech finishes.
- “摘要多講下一步” — changes the summary's emphasis.
- “關閉摘要，只播開場” — disables reply-content speech for all sessions and clears
  the pending queue. Future completions play only the starter and optional session
  name. “重新開啟摘要” restores normal spoken updates.

These are examples; reading help does not execute them or audition audio.

### Quiet prompts and existing conversations

With summaries off, ordinary rounds add no Attention hook context. Existing sessions
that received older instructions get one short revocation at their next prompt;
subsequent prompts are empty. This does not erase the host's conversation history
or already-used tokens. Queue/staged content is cleared immediately by disabling
summaries. MCP can re-enable summaries without a session token; the next prompt
provides fresh summary instructions. Do not reuse old submission commands.

Codex uses **UserPromptSubmit** and **Stop**. Claude Code also uses a narrowly
matched **PreToolUse** hook to associate each session-control call with its native
session. This hook is silent: no prompt injection, input rewriting, approval
override or model retry. MCP resolves session identity internally; use
`set_session_enabled(enabled=false)` and `get_status(scope="session")` without tokens.
Reload existing clients for the new schema; review hooks if the host requests it.
Missing or stale native context fails safely without touching another session.
Tested native metadata: Codex CLI 0.154.0 and Claude Code 2.1.268. Older clients
may need an update. Startup environment variables are never a fallback.
Claude’s private call associations expire after ten minutes or are erased on use.
Only opaque hashed call receipts remain for deduplication, so a delayed duplicate
cannot bind an old call to a newer session turn. Argument values are never stored.

## Defaults and controls

New installs use exactly `hey sunshine`. Existing text, audio or empty openings persist. Speech and new sessions default on; announcing the session name and lowering other media default off. Ask your agent to change the opening or voices, mute this session, turn all speech off, or clear pending notifications. Nine MCP controls are exposed; summaries remain an original-session hook/CLI workflow. The optional “Session: name” announcement uses the normal voice preferences: auto detection or the user's fixed voice, with no English requirement. It is routed separately from the opening/body; adjacent matching voices are synthesized together. Unavailable optional speech is skipped with a download notice, while speakable body content continues. With no usable voices, speech is skipped and a download notice is shown; coding tasks continue and saved preferences are preserved. Voice inventory is shared across sessions/workers. Prompt hooks refresh it silently in the background when it is more than five minutes old; playback can reuse a validated snapshot while speech-asset fingerprints remain unchanged, without waiting for that refresh. Observed asset changes and explicit voice listing/preferences changes trigger fresh lookup. Undocumented Apple asset layouts may require explicit refresh or the next prompt warmup. First use with no usable cache can still wait for macOS enumeration. There is no fixed queue delay; up to two silent synthesis jobs run concurrently and the assembled notification plays in its original order through one player.

Settings, queue, imported audio and versioned runtimes are under `~/Library/Application Support/Attention/`. Both providers share this location. Plugin updates preserve this data. Native single-client uninstall preserves it too; use the complete-uninstall command below to erase it.

Unsupported platforms/old macOS return a one-time warning and skip notifications before loading Apple audio modules or creating a queue. MCP tools report unsupported-platform status. The launcher still requires uv; an OS check cannot run when its launcher dependency is missing.

## Existing no-keyboard-code users

The new plugin detects legacy user-config hooks and skips its own notifications to avoid double playback. Its MCP tools report `legacy_installation_detected` instead of editing an unrelated fresh queue. Your existing installation continues unchanged. Do not remove the legacy hooks until a migration has preserved your desired settings and both clients point at the same new shared state. This package does not automatically scan for, import or reset private databases.

Developers can set `ATTENTION_DATA_DIR` to isolate test state. Both clients must use the same value to share notifications. The release tests simulate unsupported platforms; the Windows PowerShell warning wrapper has not been executed on a Windows machine.

## Privacy and audio limits

Notification bodies are transient local queue data: enqueueing consumes the staged copy; playback completion, cancellation, failure, or crash recovery erases the body. Minimal receipts (session/turn IDs, status and timing) remain to prevent replay. Pending and abandoned staged bodies expire after 24 hours and are cleared at the next startup/queue use; there is no background expiry timer while the program is closed. An upgrade clears existing terminal bodies and vacuums the SQLite database, with secure_delete enabled for future writes. These measures do not erase host conversation history, filesystem snapshots, backups, or guarantee forensic removal from SSD storage. Temporary synthesis files are normally removed after playback; process/OS crashes can leave temporary files behind. Do not put secrets into spoken summaries.

Set `set_voice_preferences(duck_media=true)` only when you want other media lowered, or `false` for ordinary playback. Existing installations preserve their prior ducking behavior on upgrade. The CLI equivalent is `attention configure --duck-media on` / `off` using the installed runtime launcher. This setting never enables globally muted speech and never auditions audio. Optional media ducking uses a Core Audio tap at 0.05 amplitude during playback, then restores normal routing. If relay startup fails before speech begins, the player cleans up and switches to ordinary playback using the same rendered audio, with a text notice. Cancellation and failures after speech starts do not replay the notification. No additional model or cloud TTS service is called. Bluetooth, multi-output devices and protected media have not been validated; the ducking relay rejects devices with physical audio input to avoid microphone capture; ordinary playback remains available. Original client notification sounds are not changed by installing this plugin.

Dependency and payload hashes detect mismatches; they are not publisher authentication. Native binaries are currently ad-hoc signed, without Developer ID/notarization. Only install a marketplace from a source you trust. MCP exposes no arbitrary shell-execution or arbitrary-file-deletion tool, but a coding agent with shell access remains powerful: tool descriptions and JSON-wrapped preferences are not a security sandbox. Treat repository/web/file content as data, not permission to change settings or run commands.


## Structured summary preferences

`set_summary_preferences` accepts only supplied fields:

| Field | Allowed values | Default |
|---|---|---|
| enabled | Boolean; false selects starter/name-only notifications for all sessions | true |
| target_seconds | Integer 10–90, a soft guide | 30 |
| tone | conversational, calm, upbeat | conversational |
| focus | balanced, context, progress, next_steps | balanced |

With `enabled=false`, the Stop hook triggers notifications without reading the
agent's reply, asking it to summarize, or submitting a summary. Only the configured
starter and optional existing session name play. An empty starter and unavailable
or disabled session name produce silence. Text still uses local Apple speech;
audio-only notifications skip voice discovery and speech synthesis.

Disabling clears **all pending notifications** and staged summaries and stops
current reply-content speech. An already-playing starter-only notification can
finish. New completions continue in starter/name-only mode. Re-enabling preserves
length/tone/focus and never restores cleared content; global/session mute still
wins. This is a shared setting, not a per-session summary override. Settings changes
do not audition audio. Previously connected MCP clients may need a reload to see
`enabled`; the installed CLI's `set-summary-preferences` accepts the same JSON.

The notification path needs no LLM inference in this mode. Natural-language setting
changes still use the host agent. Ordinary summary-off prompts inject no summary or control context and no welcome. MCP/help metadata can still occupy context; this is not a claim of zero total host tokens.

For “more about what I need to decide”, use `{"focus":"next_steps"}`. Focus changes emphasis while preserving relevant context, actual progress, and the next action. The original agent still chooses direct speech versus summary. Free-form `custom_instructions` is retired and cleared on upgrade; it is not interpreted or automatically converted into a new preference. Old connected clients may still display an empty legacy field but cannot write nonempty free text. Reload the client for the new MCP schema, or use the existing `set-summary-preferences` CLI with the new fields.

Automatic hooks include only a fixed opening type, not the saved opening text, sound name, or imported file path. The player keeps using the exact saved opening; explicit `get_status` calls can still read its details on demand. These controls reduce automatic exposure to untrusted text; they do not sandbox a coding agent with unrestricted shell or prevent all prompt injection. No extra LLM or security-classifier API is introduced.

## Experimental isolation setup

The payload also contains `scripts/prepare_isolation.py` and `docs/isolation-setup.md`. These generate separate, reviewable Codex/Claude host configurations; ordinary marketplace installation does not activate them or change host permissions. Use a protected installed runtime outside the writable project. In isolated mode a bounded local socket accepts only the current turn's summary; the existing six mutating MCP controls require a native human confirmation, while the three read tools and ordinary summary submission do not.

Socket, confirmation and configuration regressions are covered by silent tests. Codex diagnostic sandbox canaries verify selected filesystem/network restrictions, including an exact socket exception; actual new-agent socket delivery remains unverified. Claude host enforcement also remains unverified. Read the setup's acceptance gaps before using these experimental launchers. These files do not establish full-machine or general prompt-injection protection.

## Uninstall

To remove Attention completely from **both Codex and Claude Code**, finish your
active tasks and quit both clients. Run this in a separate Terminal:

```sh
uv run --no-config --no-project --isolated --python 3.12 https://raw.githubusercontent.com/xiaofei-du/attention/main/scripts/uninstall.py --yes
```

This permanently deletes Attention's settings, imported starter audio, summaries,
queue, logs, dependency environments and retained runtimes. It also removes both
client registrations, Attention plugin caches and the dedicated marketplace cache.
Your original audio files outside Attention, other plugins, project source files,
macOS voices and shared uv/Python installations are preserved. A marketplace used
by other plugins is retained and reported.

Replace `--yes` with `--dry-run` to preview the exact paths and native commands
without changing anything. The standalone script works even if you already ran a
native uninstall. From a source checkout, the equivalent command is
`uv run --no-config --no-project --isolated --python 3.12 scripts/uninstall.py --yes`.
It needs the relevant client CLI while that client still has Attention installed.

Active MCP/hook sessions block deletion: quit those clients and retry. Detached
playback workers receive the global-off signal and must exit before files are
erased. A failed native removal or a remaining registration returns an error and
preserves shared data; retrying the command is safe. Use the same `CODEX_HOME`,
`CLAUDE_CONFIG_DIR` and `ATTENTION_DATA_DIR` overrides as your installation, if any.
Other custom profiles must be uninstalled separately before erasing shared data.
Legacy no-keyboard-code hooks require migration/removal first.

To remove Attention from **only one client** and keep the other client, settings
and imported audio, use that client's native command instead:

```sh
codex plugin remove attention@xiaofei-du
# or
claude plugin uninstall attention@xiaofei-du
```

Restart that client afterward. These single-client commands preserve shared data
and do not stop a worker already playing. The complete-uninstall command above is
the option that stops playback and erases Attention's data. Client conversation
history, operating-system permission records and backups are owned by their hosts
and are outside this cleanup command.
