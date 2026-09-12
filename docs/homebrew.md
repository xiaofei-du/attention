# Attention with Homebrew

On macOS 14.2+ with Homebrew and the `codex` and/or `claude` terminal command:

```sh
brew install xiaofei-du/tap/attention
attention setup
```

The formula lives in [xiaofei-du/homebrew-tap](https://github.com/xiaofei-du/homebrew-tap).
It installs a small command wrapper and declares `uv` as a shared dependency.
Homebrew checks a fixed source archive against its SHA-256. It does not install
client plugins, edit hooks, trust code or start audio during `brew install`.

`attention setup` runs the same [guided setup](setup.md) as the standalone entry.
Choose Codex, Claude Code, or both. Then reopen/reload your clients and review the
native hook trust prompts. First use downloads Python and plugin dependencies.
The coding apps must inherit Homebrew's PATH; reopen them if `uv` was just installed.

```sh
attention setup --client both
attention setup --client codex --dry-run
attention --help
attention --version
```

Rerunning setup preserves existing plugins, including disabled ones. Conflicting
marketplaces or legacy installs stop with migration instructions instead of
creating duplicate hooks.

## Upgrade

```sh
attention update
```

This refreshes the official marketplace and updates the existing Attention plugin
in each available client. It does not add Attention to clients where it is absent.
You can target one client with `--client codex` or `--client claude`, and preview
with `--dry-run`. It verifies the reported version against each client's installed
registration. Finish active tasks first, then reload clients and review changed
hooks when prompted. Settings and mute choices are retained.

Disabled plugins are reported and skipped: Codex's reinstall command would
otherwise re-enable them. Enable a plugin in its client first if you want it
updated. If one client fails, the earlier successful update remains; fix the
reported problem and rerun. No second marketplace or plugin registration is added.

Homebrew distributes the management command, not a second copy of the running
plugin. `brew upgrade xiaofei-du/tap/attention` updates that command itself;
`attention update` is the command for updating your client plugins.

## Uninstall

Finish active tasks and quit both coding clients, then run from a separate Terminal:

```sh
attention uninstall
```

This prints the scope, asks you to type `yes`, runs the existing verified cleanup,
and only after successful cleanup calls Homebrew to remove every installed version of the command. Cancelling,
a changed cleanup scope or a cleanup error leaves the command installed. If only
the final Homebrew step fails, it prints a retry command.

```sh
attention uninstall --dry-run
attention uninstall --offline
```

`--dry-run` changes nothing. The bundled helper supports offline removal using
the uv-managed Python 3.12 prepared during setup, using the formula's `uv` path.
It does not execute a project's active virtualenv Python. Uninstall never downloads Python. If you have only installed the command and
never run setup, you can simply use `brew uninstall --formula --force xiaofei-du/tap/attention`.

Complete cleanup permanently removes Attention's settings, imported audio copies,
queue, summaries, logs and private runtimes. Original audio files, other plugins,
projects, system voices and shared uv/Python are retained. Homebrew autoremove is
disabled for this operation. The publisher tap is also retained because it may
provide other formulae; remove it separately with `brew untap xiaofei-du/tap` if
nothing else uses it. See the [cleanup boundaries](../README.md#uninstall).

`brew uninstall attention` by itself removes only the Homebrew command. If you
already ran it, use the README's verified standalone uninstall entry to remove
remaining plugins and Attention data.

When `CODEX_HOME`, `CLAUDE_CONFIG_DIR`, `ATTENTION_DATA_DIR` or `--data-dir` selects
a custom profile, cleanup keeps the shared Homebrew command so you can remove
other profiles too. Use the same overrides as installation. After every profile
is clean, remove the wrapper yourself with:

```sh
HOMEBREW_NO_AUTOREMOVE=1 brew uninstall --formula --force xiaofei-du/tap/attention
```
