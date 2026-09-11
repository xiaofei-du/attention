# Updating Attention

Public installs use the GitHub repository `xiaofei-du/attention` and plugin
`attention@xiaofei-du`. Updates preserve shared settings and imported starters.
Finish active tasks before updating, then reload your client and review changed
hooks when requested.

## Update from GitHub

Codex:

```sh
codex plugin marketplace upgrade xiaofei-du
codex plugin add attention@xiaofei-du
```

Claude Code:

```sh
claude plugin marketplace update xiaofei-du
claude plugin update attention@xiaofei-du
```

## Switch from a local installation

Finish active tasks first. Remove the old plugin from each client where it is
installed, then use the GitHub installation commands in the README. Do not keep
both marketplace copies enabled at the same time.

```sh
codex plugin remove attention@attention-marketplace
claude plugin uninstall attention@attention-marketplace
```

Run only the removal command for a client that has that old installation. These
commands remove the old plugin registration/cache, not Attention's shared
`~/Library/Application Support/Attention/` directory. Keep that directory: it
contains your settings, mute choices and imported audio. The new plugin reads the
same shared data, so an existing global mute remains in effect.

The notes below describe the earlier local-alpha upgrade mechanism. The legacy
helper targets `attention@attention-marketplace` only; use the commands above for
GitHub installs.

## Moving from 0.1.0 to 0.1.1

Finish active tasks, update the plugin, and reload it or restart the client.
Review changed hooks when prompted. An old task can retain the exact command
it loaded before the update; installing 0.1.1 cannot rewrite that cached command.

Old commands start at the host's plugin-cache path. We observed that path being
removed while an old task was still running. A retained Attention runtime alone
cannot help a command which first tries to open that missing file.

## Hooks loaded from 0.1.1

The hook entry code is embedded in the command, with the complete payload digest.
It first looks for the retained runtime with that exact revision, then for the
original plugin copy. It verifies the manifest digest and all files before loading
any Attention code. A different or modified runtime is rejected.

After one normal startup has created the retained runtime, deleting the host's
plugin cache no longer breaks these hooks. If both copies are missing, the hook
skips speech; the next prompt asks to reload or reinstall. This mechanism does
not install a background watcher or repeatedly recreate the host cache.

Do not remove retained runtime versions while tasks using them are active. MCP
connections and newly installed schemas may still require a client reload.

## Legacy Codex update helper

From the extracted marketplace directory, when its updated source is already
registered as `attention-marketplace`:

```sh
uv run --no-config --no-project --isolated --python 3.12 python -I plugins/attention/scripts/update_codex_plugin.py
```

This invokes the native installer and restores only verified old version
directories removed during that operation. It does not overwrite existing newer
installs or trust records. It is a best-effort bridge for older hook commands,
not protection against subsequent independent cleanup. Reload old tasks to use
the new hook entry. The helper does not manage Claude's cache.

Both clients keep shared data under `~/Library/Application Support/Attention/`.
Do not remove that directory as an update step.
