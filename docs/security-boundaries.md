# Host isolation and adversarial validation

Status: 2026-09-11. Data-boundary tests, a summary-only socket, native control
confirmation and an opt-in host configuration generator are implemented. The
experimental host setup has not been activated in the user's current installation.
Two Claude model smoke cases passed against a fake backend. Codex model cases
were left unavailable because the evaluation harness lacks a verified narrow
read policy. Neither result establishes general prompt-injection resistance.

## Verified boundaries

`tests/test_adversarial_data.py` covers:

- Command-like text in prompt/event data cannot change notification preferences
  or start a worker while global speech is off, for both providers.
- Staged instruction text stays with its own turn, does not enter subsequent
  automatic hook prompts, and cannot be resubmitted with an expired token.
- A hostile Claude transcript title is treated as literal speech at a silent
  playback sink; it is not executed and does not change settings.
- Shell-substitution syntax submitted as a text opening through the real CLI
  remains literal data. A temporary canary file is not created.
- Invalid, SQL-like, and expired bearer tokens cannot change another session.
  Identical session IDs in different providers retain separate preferences.
- Status responses and the current hook do not disclose other bearer tokens.

`tests/test_mcp_protocol.py` also exercises forged session/provider arguments and
embedded tool calls through real stdio MCP. Unsupported fields and invalid token
arguments are rejected without changing preferences. A schema-valid global
control call is deliberately used as a negative control: it succeeds. This
documents that MCP schema validation does not authenticate human intent.

These tests do not run an LLM. Passing them establishes application invariants,
not that a model will ignore instructions in a repository, webpage or tool result.
The earlier `test_prompt_boundaries.py` additionally covers saved opening/audio
metadata and retired free-form preferences.

## Host capability probe

On Codex CLI 0.154.0, an explicitly selected temporary permission profile allowed
writing in the temporary project and blocked reads, writes and deletion in a
denied directory within that project. Only disposable canary files were used.
With network disabled, a connection to a local ephemeral test listener failed
with a permission error; the same probe without the sandbox connected. No
external endpoint or real secret was used.

This probe did not alter the user's host configuration, protect the current
running task, test other MCP/app tools, or prove equivalent enforcement in
Claude Code. The current task still has its existing broad filesystem/network
access. Claude Code 2.1.268 is installed, but no Claude model or sandbox session
was launched for this investigation.

Codex's [configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
supports named filesystem permissions and command network restrictions. Its
network rules explicitly do not restrict web search, apps or MCP servers.
Claude's [sandbox documentation](https://code.claude.com/docs/en/sandboxing)
distinguishes Bash subprocess isolation from permissions on all tools; hooks
and MCP servers require separate trust and authorization considerations.

## Implemented opt-in boundaries

Use an opt-in host isolation setup, selected for a new task after review, with
the following two boundaries. Do not silently rewrite shared Codex/Claude
settings, widen existing permissions, or label a full-access session protected.

1. **Protect the installed runtime and private state from agent shell/file
   tools.** The agent can work in its chosen project but cannot modify Attention's
   installed code, dependency environment, private SQLite database, or security
   configuration. Deny reading private state to avoid disclosure of another
   session's bearer tokens. Installation and maintenance stay outside that
   sandbox. An Attention development checkout is distinct from its protected
   installed runtime. `scripts/prepare_isolation.py` generates new private host
   files, never rewrites live settings, and rejects overlapping, symlinked or
   temporary protected paths. Details and remaining host acceptance gaps are in
   [the setup guide](isolation-setup.md).
2. **Keep a narrow submission path and separately authorize controls.** Today
   `run.py summary` creates a Store and writes SQLite directly, so denying database
   access breaks it. Isolated mode instead uses `submit.py` and a local Unix
   socket: accept bounded summary text for the current turn; trusted code
   validates the schema, live token, provider, turn, mute state and dedupe rules
   before writing SQLite. It must not accept settings changes or arbitrary
   commands. No `submit_summary` MCP tool was added. The socket is owned by one
   trusted MCP process, with other sessions standing by to take over. Tests cover
   symlink/lock rejection, malformed and oversized frames, absolute read deadlines,
   bounded concurrent connections, stale tokens, provider separation and silent
   Stop/queue delivery. Short SQLite waits, cancellation checks and worker joins
   prevent the reproduced write-after-shutdown race before releasing ownership.

The existing nine-tool MCP remains the configuration channel. The optional
`--confirm-controls` mode requires a native Cancel/Allow dialog for each of its
six mutating calls. The full bounded request is shown, display-control characters
are escaped, Cancel is the default, and rejection/timeout/process failure leaves
settings unchanged. Schema checks happen first. Three read tools bypass the
gate. All dialog tests use mocks and never display a popup or play audio. An
agent-provided `confirmed: true` field, a prompt instruction or a tool annotation
cannot replace that decision. Shell/CLI fallbacks must not bypass this boundary.

This introduces a product choice: stronger protection means conversational
setting changes may require a host confirmation. Ordinary summary submission
should stay automatic. Removing all confirmations while permitting the same
agent to change any setting cannot establish reliable human authorization.

Do not promise that the isolated agent cannot damage files it legitimately may
edit in its project. Keep normal backups/version control. Domain allowlists also
do not guarantee that data cannot be sent to an allowed service. Filesystem,
environment credentials, network, other MCP tools and GUI automation all need
explicit coverage before claiming broader exfiltration protection.

## Verification and remaining acceptance checks

- Real stdio MCP tests and a temporary socket demonstrate summary staging without
  an MCP summary tool, rejected control calls, current-token validation and private
  state unchanged on denial. The tests do not depend on a model refusing bad text.
- `tests/security_eval/` is an explicit opt-in, fake-only model harness, capped at
  two cases per provider. Claude Code 2.1.268 made only the required read calls in
  both cases: zero mutating attempts and zero fake effects. Codex 0.154.0 was not
  launched. Both host version drift and unavailable isolation fail closed.
- Independent review reproduced and then rechecked fixes for temporary-interpreter
  placement, trickle-client slot exhaustion and writes surviving broker shutdown.
- New Codex canaries under home (outside ambient temp access) verified project
  writes/runtime reads while blocking private reads, protected writes/deletions,
  parent renames, a second Unix socket, local TCP and one known dummy process's
  argv. The exact diagnostic socket flag was needed to connect. This is **not**
  proof that a new Codex agent applies the generated socket entry correctly.

- Prove private runtime/state denial through every enabled shell and file tool
  in both hosts, including links, parent-directory replacement and config edits.
- Verify real new-host summary delivery with the generated files. The deterministic
  transport path is tested, but the Codex diagnostic socket allowance and actual
  agent allowance must not be assumed equivalent.
- Prove a state-changing MCP call cannot bypass the host's chosen human approval
  boundary; deny unapproved calls rather than infer consent from content.
- Test selected network and credential restrictions in both hosts. If a feature
  is unavailable or bypassed, report the gap instead of claiming protection.
- Extend model evaluation only after reviewing the provider's actual tool/read
  boundary. Keep attempts, host blocks and fake backend effects separate; never
  equate a passing sample with immunity to prompt injection.

No meeting mute lock or session-only listening mode is part of these changes.
