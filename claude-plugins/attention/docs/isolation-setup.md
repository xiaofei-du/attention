# Opt-in Attention isolation setup

This generator writes reviewable files for a **new macOS task**. It does not
install a runtime, copy credentials, edit existing host settings, start either
host, or protect an already running full-access task. The production broker and
confirmation gate must be present in the installed runtime before use.

## Prepare protected locations

Choose one writable project and separate installed runtime, private state,
control directory and generated output. All five must be disjoint. Protected
locations must be outside the project **and outside temporary directories**.
Codex CLI 0.154.0 probes found that explicit denies on sibling files under
`/private/tmp` did not prevent access; the generator rejects macOS temp trees.
Use an existing private parent under the user's home, not `/tmp`.

Create the runtime, state and control directories yourself, with mode 0700 for
private directories. Install reviewed runtime code and its dependencies from a
trusted terminal. Do not put credentials inside the runtime or project. The
runtime includes `run.py`, `mcp_server.py`, `submit.py` and the `nkc` package;
its entire tree must be free of symlinks. No runtime installation or copying is
performed by this generator.

Use an absolute, non-symlink Python executable. A materialized virtual environment
created with `python3 -m venv --copies` preserves its own installed MCP dependencies;
verify its executable and runtime tree contain no symlinks. Do not resolve a
symlink from an ordinary venv to the base interpreter and assume its packages
remain available. The submit client needs only Python's standard library.

Add the specific protected base-Python/dependency installation directories with
`--runtime-read-root` when necessary. For the Homebrew Python canaries, the
resolved base interpreter framework directory supplied all required standard-library
and dynamic-library reads. The generator rejects read roots overlapping the
project or private state/config/credentials, and protects those roots from
writes. Do not grant the home directory or a shared writable dependency tree.

A sample layout, to adapt to your actual reviewed installation:

```sh
python3 scripts/prepare_isolation.py \
  --project /Users/you/workspace/example \
  --runtime /Users/you/Attention/runtime \
  --state /Users/you/Attention/state \
  --socket /Users/you/Attention/control/summary.sock \
  --output /Users/you/Attention/review-2026-09-11 \
  --python /Users/you/Attention/venv/bin/python3 \
  --runtime-read-root /Users/you/Attention/venv \
  --runtime-read-root /opt/homebrew/Cellar/python@3.12/3.12.11/Frameworks/Python.framework/Versions/3.12 \
  --deny-credential /Users/you/company-private-credentials
```

The socket's absolute UTF-8 pathname must fit 103 bytes. It must not exist when
preparing the files. An existing output directory, relative/traversal paths,
symlink components, overlapping boundaries, unsupported platforms, policy glob
characters, or missing installed CLI/runtime entries cause generation to fail.
The output directory is 0700; configs are 0600 and launchers 0700. Both CLIs must
already be installed. Resolved host executable paths are saved in the launchers.

## Review and select the files

The output contains:

- `codex-home/config.toml`: named filesystem/network profile, inline lifecycle
  hooks, and the existing Attention MCP server with `--confirm-controls`.
- `claude-settings.json` and `claude-mcp.json`: sandbox restrictions, explicit
  private-file permission denies, lifecycle hooks and the same MCP server.
- `launch-codex.sh`, `launch-claude.sh` and `README.md`: exact launch commands.

Launch one of those scripts from a trusted terminal after reviewing its contents.
The scripts reject additional arguments and discard inherited environment secrets.
Use each fresh host config's normal authentication flow; no credentials are
copied or shared by this setup. Existing shared host settings are not edited.
Trust the reviewed hooks through the host's ordinary UI if requested. No hook
trust bypass flag is generated. Default Cancel, cancellation and timeout on
native control confirmation reject the change. There are still nine MCP tools;
ordinary summary submission goes through the socket without a control dialog.

Codex launch pins the generated settings on its command line, selects the named
permission profile with `default_permissions`, and marks the project untrusted
to suppress project configuration. Shell approval is `never`, network is disabled
with an exact Unix socket entry, and shell environment inheritance is disabled.
Claude launch uses `--restricted --setting-sources '' --settings FILE
--strict-mcp-config --mcp-config FILE --tools Bash,Read,Edit,Write,Glob,Grep
--no-chrome`. Restricted mode confines native file tools to the working
directories; the explicit Read/Edit/Write denies and sandbox rules additionally
name protected paths. No `allowRead`, unsandboxed command exception, network
domain or all-sockets grant is generated. MCP calls can reach the trusted native
confirmation gate without a duplicate per-tool host confirmation policy.

Do not add writable roots, project configuration, other plugins/MCPs, GUI tools,
network exceptions or sandbox escapes to this reviewed launch and retain the
same isolation claim. Managed host settings still need independent review. The
host process and reviewed hooks/MCP run with trusted user privileges; they need
that access to write protected state and display native confirmation.

## What was actually verified

Run the focused unit suite without any host session or audio:

```sh
python3 -m unittest discover -s tests -p test_isolation.py
```

The explicitly opted-in, local canary test runs only `codex sandbox`, a Python
subprocess, temporary fake files, listeners and a known dummy process:

```sh
NKC_RUN_CODEX_SANDBOX_PROBE=1 python3 -m unittest discover -s tests -p test_isolation.py
```

On macOS with Codex CLI 0.154.0, the generated profile allowed project writes and
runtime reads. It blocked state/credential reads (including a project symlink),
runtime/config writes, runtime and parent-directory replacement, state deletion,
socket unlinking, a second Unix socket, and local TCP. A `ps` query targeting only
a known dummy child containing a fake token in its argv was blocked. No real
process listing, credential, model call or audio backend was involved.

A separate end-to-end diagnostic test ran the actual `submit.py` in that sandbox
against a real broker with disposable state. The client staged its current-token
summary, direct database reads were denied, and the trusted Stop/queue path
consumed the summary using a silent playback sink. This caught and removed an
unnecessary client-side SQLite import; SQLite is loaded only by the trusted
broker. The tested Python 3.12 client required only its standard library.

**The diagnostic sandbox command needed `--allow-unix-socket EXACT_PATH` in
addition to the generated named profile** to connect to the summary socket.
With that exact flag the socket connected and all other canaries remained
blocked. The profile's `network.unix_sockets` entry alone did not enable the
socket in this diagnostic CLI. This is a diagnostic-interface result, not proof
that a newly launched Codex agent applies the socket entry correctly. A real
new-host acceptance check of summary delivery remains required; do not broaden
the socket policy to compensate.

Claude Code 2.1.268 supports the generated launch flags according to its local
`--help`; its sandbox keys and file rule syntax were checked against the official
[settings](https://code.claude.com/docs/en/settings) and
[sandbox](https://code.claude.com/docs/en/sandboxing) documentation. No Claude model
or sandbox session was launched. Native Read/Edit/Write/**Glob/Grep**, Bash
filesystem/network restrictions, process-argument visibility, managed-setting
interaction, and real summary delivery therefore remain acceptance gaps.
Documentation/schema review is not enforcement evidence. Codex profile syntax
is documented in its [configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).

The sandbox protects only the selected shell/file surfaces. Other MCP servers,
apps, web retrieval and GUI automation are separate capabilities. It does not
stop damage to files the agent may legitimately edit inside its project, protect
secrets already present in that project, or establish full-machine protection.
