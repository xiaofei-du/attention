# Attention! 📣

<p align="center">
  <a href="https://github.com/xiaofei-du/attention/actions/workflows/tests.yml">
    <img src="https://github.com/xiaofei-du/attention/actions/workflows/tests.yml/badge.svg?branch=main&amp;event=push" alt="macOS tests on main">
  </a>
  <a href="#requirements">
    <img src="https://img.shields.io/badge/macOS-14.2%2B-007AFF" alt="macOS 14.2 or later">
  </a>
  <a href="#add-the-plugin">
    <img src="https://img.shields.io/badge/Codex-plugin-17876D" alt="Codex plugin">
  </a>
  <a href="#add-the-plugin">
    <img src="https://img.shields.io/badge/Claude_Code-plugin-D97757" alt="Claude Code plugin">
  </a>
  <a href="LICENSE">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT license">
  </a>
  <a href="#install">
    <img src="https://img.shields.io/badge/status-alpha-E3A008" alt="Alpha release">
  </a>
</p>

<p align="center">
  <a href="https://giphy.com/gifs/cbbc-tracy-beaker-cbbc-star-cYaBD8kxE4PZudHBRA">
    <img src="https://media.giphy.com/media/cYaBD8kxE4PZudHBRA/giphy.gif" alt="Attention GIF by CBBC on GIPHY" width="360">
  </a>
</p>

Your agent would like a word.

Spoken task updates for **Codex and Claude Code on macOS**. When a round finishes,
Attention reads a short reply or a conversational summary written by that same
agent. Multiple sessions share one playback queue. One at a time, please.
Speech uses voices installed on your Mac. No separate LLM API key or cloud TTS
service is required.

## Who is this for?

This is for you if:

- Your usual notification has all the personality of a microwave.
- You're running five sessions and every ping starts a game of “Which one was that?”
- You work from home and could use a coworker with a mute button.

If it gets too noisy, ask your agent to **“Turn off speech globally.”** Quiet alone
time is a feature too. Turn it back on whenever you like; see [Make it yours](#make-it-yours)
below for the controls.

## Contact

If you find Attention useful or have an idea for what to add, give me a shout:

[![X: @xiaofeidu283](https://img.shields.io/badge/X-%40xiaofeidu283-9A4329?style=flat-square&logo=x&logoColor=white&labelColor=9A4329)](https://x.com/xiaofeidu283)
[![Threads: @smilefei.du](https://img.shields.io/badge/Threads-%40smilefei.du-9A4329?style=flat-square&logo=threads&logoColor=white&labelColor=9A4329)](https://www.threads.com/@smilefei.du)

## Install

**Alpha · macOS 14.2+ · Codex and/or Claude Code.** With Homebrew installed:

```sh
brew install xiaofei-du/tap/attention
attention setup
```

Choose Codex, Claude Code, or both, then follow [Enable and try it](#enable-and-try-it).
Homebrew prepares `uv`; the wizard installs through your native plugin
managers. Existing settings and disabled plugins stay as you left them.

No Homebrew? Use the [terminal setup wizard](docs/setup.md#without-homebrew) or the
manual steps below. No ZIP download, local marketplace folder, or compilation is
needed. After installation, use `attention update` to update your existing enabled
plugins, and `attention uninstall` for complete removal. See the
[Homebrew command guide](docs/homebrew.md) for details.

### Requirements

- **macOS 14.2 or later on Apple Silicon or Intel.** CI tests installation and
  hooks on both architectures using macOS 15. Actual speaker playback has been
  tested on Apple Silicon; Intel speakers and other audio devices still need
  testing. Windows and Linux playback are not supported.
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
2. In **Codex**, open **Hooks** in the app or run `/hooks` in the CLI, find
   `attention@xiaofei-du`, and Trust **UserPromptSubmit** and **Stop**.
   **Claude Code** loads the hooks when the plugin is enabled; it does not require
   Codex's per-hook Trust step. Reopen Claude Code or run `/reload-plugins` to load
   a newly installed plugin. It also has **PreToolUse**, used only to identify
   session-control calls.
3. Start a new conversation and paste:

   > Please reply only with: “This is an Attention voice notification.”

   With fresh-install defaults, you should hear **hey sunshine**, followed by
   **This is an Attention voice notification.** Hearing it confirms playback;
   seeing the text alone does not. Existing speech preferences stay unchanged.
4. Ask **“Attention help”** to see the available settings.

Ordinary playback does not need microphone or system-audio recording permission.
Lowering other media is an optional setting, off by default; enabling it may ask
for macOS system-audio permission. Installation does not change the client's
original notification sound.

## Make it yours

Give your agent an entrance: a friendly greeting, a Mac chime, or a tiny bit of
drama. Change settings by talking to your agent. These requests are examples,
not actions performed during installation.

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

**Try a starter:** [📣 Download the “Attention!” audio example](docs/assets/attention-starter.mp3?raw=1)
(MP3 · 1.7 seconds · 29 KB). Listen to the downloaded file, then give it to your
agent and say **“Use this file as my starter.”** This is a custom opening sound;
the spoken reply or summary follows it. Subtlety is optional.

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

Finish your active tasks and quit Codex and Claude Code. If you installed through
Homebrew, run this in a separate Terminal:

```sh
attention uninstall
```

It previews the cleanup, asks you to type **yes**, removes Attention from both
clients and erases its data, then removes the Homebrew command. Cancelling or a
cleanup failure keeps the command available for retry. Shared `uv`/Python and the
publisher tap remain. `brew uninstall attention` alone removes only the command;
it leaves the plugins and speech settings intact. Custom-profile cleanup also
keeps the command; see [Homebrew removal](docs/homebrew.md#uninstall).

<details>
<summary>Installed without Homebrew, or already removed the command?</summary>

Paste this block once; it downloads a fixed version and checks its SHA-256
**before running it**:

<!-- attention-uninstall:start -->
```sh
(
  set -eu
  entry="$(/usr/bin/mktemp "${TMPDIR:-/tmp}/attention-uninstall.XXXXXXXX")"
  trap '/bin/rm -f -- "$entry"' EXIT
  /usr/bin/curl -qfsSL --proto '=https' --proto-redir '=https' --max-time 30 --max-filesize 1048576 \
    -H 'Accept: application/vnd.github.raw+json' \
    https://api.github.com/repos/xiaofei-du/attention/git/blobs/5fae362726a1f27e83d731c22572f2fcbf17fcfc -o "$entry"
  digest="$(/usr/bin/env -u PERL5OPT -u PERL5LIB /usr/bin/shasum -a 256 "$entry")"
  [ "${digest%% *}" = '5f55fb75227bb6162a5a869e6054f8486ffb67c4c1ad89a438c7e273fe3a3859' ] || {
    printf '%s\n' 'Attention launcher checksum mismatch; nothing was run.' >&2; exit 1;
  }
  /bin/bash -p "$entry"
)
```
<!-- attention-uninstall:end -->

The launcher finds an existing Python and a verified local uninstall helper, or
fetches the matching helper by its immutable Git object ID from GitHub. It shows the cleanup paths and asks you
to type **yes** before removing Attention from **both clients**.

</details>

This permanently deletes Attention's settings, imported audio copies, summaries,
queue, logs, private dependency environments and retained runtimes. Your original
audio files, other plugins, projects, macOS voices and shared Python/uv installations
are preserved. A marketplace shared with other plugins is kept and reported. Unknown nested files,
modified packaged files and unsafe directory ownership stop cleanup before native
uninstall commands run. Move a reported personal file outside Attention and retry;
there is no force-delete option. Never run this command with sudo.

<details>
<summary>Preview, offline removal, custom profiles and single-client uninstall</summary>

Every plugin package includes `uninstall.sh`. From a source checkout or a plugin
package directory, preview without deleting anything:

```sh
bash -p uninstall.sh --dry-run --offline
```

Run `bash -p uninstall.sh --offline` to preview and confirm locally. There is no
version number in the command. If you saved the script elsewhere, it also checks
the usual Codex/Claude plugin caches and Attention's retained runtimes for a
matching helper. `--offline` refuses to download anything. An older launcher must
use its matching helper; a checksum mismatch stops it before any helper executes.

The launcher uses an existing **Python 3.11+** (including a suitable Conda Python),
or asks uv to locate an already-installed Python 3.12. It does not install Python,
SDK dependencies or sound libraries. If neither is available, restore the Python
used by Attention and retry. Only use a launcher from a source you trust; its
SHA-256 check detects changed/mismatched helpers, not a compromised publisher.
The online command separately checks the outer launcher against the hash in this
README. You still need to trust these instructions and your local executables;
this is not a publisher signature. The fixed Git object IDs never follow changes
to `main`; GitHub API rate limits or a missing object stop the download safely.

Our cleanup uses an exact file inventory and does not recursively erase new files
added during deletion. Native client commands manage their own caches; the
uninstaller rechecks before calling them but cannot sandbox those commands or a
compromised process running as your user. Keep both clients closed during removal.

Use `--yes` only when you explicitly want to skip confirmation; piped text such
as `echo yes` does not answer the default terminal prompt. The standalone Python
entry remains available as `python3 -I scripts/uninstall.py --dry-run` or `--yes`.
Run `bash uninstall.sh --help` for the launcher options.

Use the same `CODEX_HOME`, `CLAUDE_CONFIG_DIR` and `ATTENTION_DATA_DIR` overrides as
your installation. `--data-dir PATH` also selects a custom Attention data root.
Other custom profiles must be uninstalled separately before erasing shared data.
Legacy no-keyboard-code hooks require migration/removal first.

Active MCP/hook sessions block deletion. Detached playback workers receive the
global-off signal and must exit before files are erased. A failed client removal,
remaining registration or changed cleanup scope stops the operation; fix the
reported problem and retry. The relevant client CLI must remain available while
that client still has Attention installed. If a download fails certificate
validation, use the local copy; do not disable TLS verification.

To remove Attention from **only one client**, keeping shared settings and audio:

```sh
codex plugin remove attention@xiaofei-du
# or
claude plugin uninstall attention@xiaofei-du
```

Restart that client afterward. These single-client commands preserve shared data
and do not stop a worker already playing. Client conversation history, operating-system
permission records and backups are owned by their hosts and are outside Attention's
cleanup command.

</details>

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for semantic commit messages, the PR
description format, and verification expectations.

## Build from source

Only source builds need **Xcode 26 or later** with the macOS 26 SDK (`xcrun` and
`clang`). The newer SDK compiles APIs guarded for macOS 26; the deployment target
remains macOS 14.2. From this repository's root directory, run:

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
uv lock --check
uv venv --managed-python --python 3.12 .venv
uv pip sync --python .venv/bin/python --require-hashes --only-binary :all: --find-links packaging/wheels --index-url https://pypi.org/simple packaging/requirements.txt
ATTENTION_TEST_MARKETPLACE="$PWD" .venv/bin/python -m unittest discover -s tests -v
```

Tests use disposable state and silent playback sinks. Host sandbox diagnostic
probes require a separate opt-in and are not enabled by this command.

Native binaries are currently ad-hoc signed, without Developer ID notarization.
The alpha still needs clean-machine and wider audio-device testing before a
stable release. [Security boundaries](docs/security-boundaries.md) describe what
has been checked and what remains unverified.

## License

Attention's code and documentation are available under the [MIT License](LICENSE).
Third-party dependencies, the demo audio, and the linked GIF retain their
respective licenses and rights.
