# Guided setup

One installer for Codex, Claude Code, or both. It uses the same native plugin
installation as the manual commands; it does not create another copy of your
hooks or change your speech preferences.

On **macOS 14.2+**, with Homebrew installed:

```sh
brew install xiaofei-du/tap/attention
attention setup
```

Homebrew installs `uv` and the small command wrapper. Run `attention setup` to
choose your clients and install their plugins. Homebrew installation alone does
not change your client profiles. See [Homebrew setup and removal](homebrew.md).

## Without Homebrew

Open Terminal and run:

```sh
curl -fsSL https://raw.githubusercontent.com/xiaofei-du/attention/main/setup.sh | /bin/bash -p
```

Choose Codex, Claude Code, or both. Their terminal commands must already be
available. Setup checks for `uv`; if it is missing, it asks before installing it.
With Homebrew present, it runs `brew install uv`. Otherwise, it uses a pinned,
SHA-256-checked Astral installer, including binary checksum verification. That
installer writes to `~/.local/bin` and updates shell startup files for PATH.
It does not install Homebrew or change your Conda environment.

Setup prepares a uv-managed Python 3.12 to inspect the clients' JSON status, then
adds `xiaofei-du/attention` and installs `attention@xiaofei-du` using their native
plugin commands. Initial Python and plugin downloads need internet access.
No model call, speech playback, or audio permission request is part of setup.

After installation, **reopen your clients and review Attention's hooks**. In
Codex, open Hooks or run `/hooks`, find `attention@xiaofei-du`, and Trust
`UserPromptSubmit` and `Stop`. In Claude Code, reopen or use `/reload-plugins`
and review permissions when prompted. Setup cannot grant this trust for you.
The first plugin launch also prepares its pinned MCP dependencies. Then try a
short question in a new session.

If uv was just installed, restart your terminal and coding app so they receive
the updated PATH. Check `uv --version` in the client's terminal if uv cannot be
found. See [manual installation](../README.md#add-the-plugin) if you prefer to
install dependencies yourself.

## Existing installations and recovery

- Already-installed plugins are preserved, including disabled plugins. Setup
  does not enable, update or reset them. Use the [upgrade guide](upgrading.md)
  for updates or an earlier local alpha installation.
- An older Attention marketplace, another installation scope, or a different
  source using the same marketplace name needs review. Setup stops rather than
  replacing it or risking duplicate notifications.
- If one client installs successfully and the other fails, the successful
  installation remains. Fix the reported error and rerun setup; it will skip
  the completed client and continue.
- Shared uv/Python installations remain available after Attention is removed.
  The [Attention uninstaller](../README.md#uninstall) retains these dependencies
  because other programs may use them.

From a source checkout, run `bash setup.sh`. Options:

```sh
bash setup.sh --client codex --dry-run
bash setup.sh --client both
bash setup.sh --client claude --install-uv
```

`--install-uv` explicitly permits installing uv when missing. Without it, setup
asks in the terminal. `--client` selects a client without a menu. `--dry-run`
does not install uv, marketplaces or plugins; with uv present, preparing the
Python interpreter for inspection may still download/cache Python.

## Verify the entry before running it

<details>
<summary>Advanced: fixed download plus an external SHA-256 check</summary>

The short command trusts the initial script served by this GitHub repository
over HTTPS. It verifies the subsequent setup helper and standalone uv installer
before executing them. Homebrew and the client plugin managers remain trusted
installers; the script does not replace their package verification or pin the
plugin manager's selected release. Hashes detect mismatches; they do not prove
the publisher is trustworthy.

For a fixed entry checked **before its first execution**, copy this whole block
from a version of the documentation you trust:

<!-- attention-setup:start -->
```sh
(
  set -eu
  entry="$(/usr/bin/mktemp "${TMPDIR:-/tmp}/attention-setup.XXXXXXXX")"
  trap '/bin/rm -f -- "$entry"' EXIT
  /usr/bin/curl -qfsSL --proto '=https' --proto-redir '=https' --max-time 30 --max-filesize 1048576 \
    -H 'Accept: application/vnd.github.raw+json' \
    https://api.github.com/repos/xiaofei-du/attention/git/blobs/af5fef8db683b7dd523939cb44cc0272cada31ac -o "$entry"
  digest="$(/usr/bin/env -u PERL5OPT -u PERL5LIB /usr/bin/shasum -a 256 "$entry")"
  [ "${digest%% *}" = '9b5bb431563316e4ac3d5a7c530033363d86213abc27bb3c01bba81ac15fd843' ] || {
    printf '%s\n' 'Attention launcher checksum mismatch; nothing was run.' >&2; exit 1;
  }
  /bin/bash -p "$entry"
)
```
<!-- attention-setup:end -->

This does not need `gh` or a separate verification tool. macOS supplies curl,
shasum and bash. Both entry points use the same setup helper and client selection.

</details>
