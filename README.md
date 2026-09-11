# Attention! 📣

Your agent has something to report.

Spoken task updates for **Codex and Claude Code on macOS**. When a round finishes,
Attention reads a short reply or a conversational summary written by that same
agent. Multiple sessions share one playback queue, so updates take turns.
Speech uses voices installed on your Mac. No separate LLM API key or cloud TTS
service is required.

## Install

**Alpha:** install directly from [xiaofei-du/attention](https://github.com/xiaofei-du/attention).
The plugin manager downloads the package from GitHub; no ZIP download, local
marketplace folder, or compilation is needed.

### Requirements

- **macOS 14.2 or later.** Apple Silicon and Intel binaries are included in the
  bundle. Actual speaker playback has been tested on Apple Silicon; Intel and
  other audio devices still need hardware testing. Windows and Linux playback
  are not supported.
- **Codex or Claude Code**, with its `codex` or `claude` command available in
  Terminal. Native session controls have been tested with Codex CLI 0.154.0 and
  Claude Code 2.1.268; older clients may need an update.
- **uv**, available to both Terminal and the coding app. If you use Homebrew:

  ```sh
  brew install uv
  ```

  Other installation methods are in the [uv installation guide](https://docs.astral.sh/uv/getting-started/installation/).

The first launch downloads Python 3.12 and pinned MCP dependencies, so it needs
internet access and can take longer than later launches. Bundle users do not need
Xcode. Text playback needs an installed system voice; if none is usable, Attention
skips speech and explains how to download one.

### Add the plugin

Run these commands in Terminal from any directory. If you installed an earlier
local alpha, first follow [Switch from a local installation](docs/upgrading.md#switch-from-a-local-installation).

Run the commands for the client you use. To use both clients, run both sections;
they will share settings and the playback queue.

**Codex**

```sh
codex plugin marketplace add xiaofei-du/attention
codex plugin add attention@xiaofei-du
```

**Claude Code**

```sh
claude plugin marketplace add xiaofei-du/attention
claude plugin install attention@xiaofei-du
```

`xiaofei-du/attention` identifies the GitHub repository. `attention@xiaofei-du`
selects the Attention plugin from that publisher’s marketplace.

### Enable and try it

1. Reload the plugin or reopen your client after installation.
2. Review and enable the plugin's hooks when your client requests it. In Codex,
   open **Hooks** in the app or run `/hooks` in the CLI, find
   `attention@xiaofei-du`, and Trust **UserPromptSubmit** and **Stop**.
   Claude Code also has **PreToolUse**, used only to identify session-control calls.
3. Start a new conversation and ask a short question. On a fresh installation,
   the completed reply should be announced with **hey sunshine**.
4. Ask **“Attention help”** to see the available settings.

Ordinary playback does not need microphone or system-audio recording permission.
Lowering other media is an optional setting, off by default; enabling it may ask
for macOS system-audio permission. Installation does not change the client's
original notification sound.

## Make it yours

Change settings by talking to your agent. These requests are examples, not actions
performed during installation.

| What you want | Example request |
| --- | --- |
| A text opening | “Set my opening to hey sunshine.” |
| An Apple alert sound | “Show the available Apple starter sounds.” Then choose one. |
| Your own audio | “Use this file as my starter.” Provide a local audio file. |
| No opening | “Remove the opening.” |
| Session name first | “Enable session-name announcements.” |
| A different voice | “Show installed voices” or “Use a male voice.” |
| Quieter background media | “Lower Spotify and other media during announcements.” |
| Mute one session | “Turn off speech for this session.” |
| Mute everything | “Turn off speech globally.” |
| Clear waiting updates | “Clear the pending notification queue.” |
| Starter-only notifications | “Disable summaries; only play the starter.” |
| Adjust summaries | “Aim for 20 seconds and focus on next steps.” |

Starters support **text, Apple built-in sounds, custom audio, or none**. Custom
files can be **MP3, WAV, M4A, AIF/AIFF**, up to **30 seconds / 20 MiB**. Attention
copies the selected file locally. Audio replaces the text opening; it does not
upload the file. Your opening stays fixed until you change it.

Global mute stops current speech, clears pending updates, and discards new ones
while off. Re-enabling preserves individually muted sessions and does not replay
cancelled updates. New sessions default to enabled, subject to the global switch.

Disabling summaries applies to both clients: it clears pending updates and staged
summaries, then plays only the starter and optional session name. Ordinary rounds
add no Attention hook prompt in this mode and require no summary generation.
Existing conversations receive one revocation of earlier summary instructions;
MCP definitions and explicit setting changes can still use model context.

See [the full usage guide](packaging/PLUGIN-README.md#getting-started-and-help)
for controls, summary preferences, and privacy details.

## Troubleshooting

- **No speech:** check that the plugin loaded, its hooks are enabled/trusted, and
  global and session speech are on. Ask “Show Attention status.” A restored
  installation preserves previous mute choices.
- **`uv` not found or MCP startup timed out:** confirm `uv --version` works and
  the coding app can find it. Reload after dependency setup completes.
- **A voice is missing:** follow the download notice, then ask Attention to list
  voices again. Voice selection does not automatically download or preview audio.
- **Other media stays loud:** ask to enable media lowering and follow the system
  permission prompt. Bluetooth and multi-output setups have not been validated.
- **Updating an existing install:** finish active tasks first, then follow
  [the upgrade guide](docs/upgrading.md). Reload changed hooks and review them
  when requested. Shared preferences and imported starters are preserved.
- **Moving from the old no-keyboard-code prototype:** follow
  [the migration notes](docs/installation.md#existing-no-keyboard-code-users)
  before removing old hooks, to preserve settings and avoid duplicate notifications.

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

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for semantic commit messages, the PR
description format, and verification expectations.

## Build from source

Only source builds need **Apple's Xcode Command Line Tools** (`xcrun` and `clang`).
From this repository's root directory, run:

```sh
uv run --no-config --no-project --isolated --python 3.12 python scripts/build_marketplace.py --output .build/attention-marketplace
```

This creates both client packages and their catalogs. The builder requires a new
output directory; for another build, choose a different `--output` path. Before
publishing source changes, replace the checked-in `plugins/`, `claude-plugins/`,
`.agents/plugins/marketplace.json`, and `.claude-plugin/marketplace.json` with the
generated versions. The distribution tests catch stale runtime copies.

For development tests, return to the repository root:

```sh
uv sync --frozen --python 3.12
ATTENTION_TEST_MARKETPLACE="$PWD" .venv/bin/python -m unittest discover -s tests -v
```

Tests use disposable state and silent playback sinks. Host sandbox diagnostic
probes require a separate opt-in and are not enabled by this command.

Native binaries are currently ad-hoc signed, without Developer ID notarization.
The alpha still needs clean-machine and wider audio-device testing before a
stable release. [Security boundaries](docs/security-boundaries.md) describe what
has been checked and what remains unverified.
