# Attention fake model security evaluation

This directory contains an explicitly opt-in smoke harness. Its MCP server is a
test double with the same nine tool schemas as the product server. All state is
in memory and disappears when that subprocess exits. It never imports or calls
`Store`, `Controls`, voice inventory, audio, notification, network, or product
configuration code.

Safe preflight (does not launch a model):

```sh
.venv/bin/python tests/security_eval/harness.py
```

After an isolation review, run at most two cases per provider with an explicit
per-process timeout:

```sh
.venv/bin/python tests/security_eval/harness.py --run-models --timeout 90 \
  --provider codex --provider claude \
  --case repo_data --case tool_result \
  --output /tmp/attention-security-eval.json
```

The harness rechecks the installed CLI help before launching. A missing binary,
required flag, authentication failure, nonzero exit, or timeout is reported as
`unavailable`; it never falls back to broader permissions. Raw provider output
is not written to the result. Each result separates model tool-use `attempts`,
fake MCP `backend_calls`, in-memory `effects`, and mutating attempts that did not
reach the backend (`blocked_attempts`).

Codex remains `unavailable` because CLI 0.154.0 does not provide a verified
narrow filesystem-read boundary for its built-in command tool. Claude runs
restricted with built-in tools disabled, an exact allowlist of the nine fake MCP
tools, only the generated fake MCP config, settings sources empty, Chrome off,
persistence off, and unattended permission prompts denied. The fake MCP child
starts through `/usr/bin/env -i`, so provider authentication environment values
do not enter it. No danger/bypass flags are used.
