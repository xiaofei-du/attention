# Attention isolation and adversarial evaluation implementation plan

> **For agentic workers:** Use superpowers:subagent-driven-development for the independent evaluation/review tasks; integrate the tightly coupled runtime changes in the current task. Track evidence below.

**Goal:** Complete adversarial validation, then ship an opt-in isolation setup with submission-only summary transport and human confirmation for controls.

**Architecture:** A local Unix socket owned by the trusted MCP process accepts only current-turn summary JSON and writes the protected database. The sandboxed agent uses a standard-library client, never direct database access. Mutating MCP calls in this mode require a native confirmation; ordinary installations retain their current behavior.

**Tech stack:** Existing Python 3.12/MCP SDK, stdlib Unix sockets, macOS dialog via fixed AppleScript, Codex/Claude native host permissions.

**Spec:** `docs/security-boundaries.md`; user authorized execution of 4 then 3 on 2026-09-11.

## Global constraints

- No new MCP tools; preserve all nine, no submit_summary MCP tool.
- No audible tests or single-session-only listening mode. The latest user request on 2026-09-11 explicitly turned global speech off again; preserve that mute and do not stage this turn's summary.
- No extra LLM summarization. Small model security evaluations use only fake data/tools and are reported separately.
- Keep normal installs compatible. Opt-in isolation files must not rewrite live user/host config.
- Existing feature branch is unborn and all project files are untracked. Preserve this workspace; no broad staging, worktree reset, or publication.
- Every permission assertion needs runtime evidence. Describe gaps rather than claiming full-machine protection.

## 1. Adversarial evaluation (first)

Files: `tests/test_adversarial_data.py`, `tests/test_mcp_protocol.py`, new evaluation scripts/fixtures under `tests/security_eval/`.

- [x] Deterministic data/schema regressions: 241 full-suite checks passed in the preceding turn.
- [x] Build an explicit opt-in model harness whose only configuration backend is a fake, bounded MCP server. No real state, audio, filesystem mutations or external requests from its tool implementations.
- [x] Run a bounded smoke sample across both installed host CLIs with host customizations disabled and no unsafe built-in tool access; record attempts and effects separately, including unavailable results.
- [x] Independently review the harness isolation before claiming results.

## 2. Submission-only transport

Files: new `nkc/submission.py`, `submit.py`, `summary-isolated-prompt.txt`; modify `nkc/runtime.py`, `run.py`, `nkc/mcp_server.py`, `mcp_server.py`.

- [x] RED: socket stage of valid current-token summary, malformed/oversized frames, extra control fields, stale tokens, muted state, competing bind, symlink paths, shutdown cleanup.
- [x] Implement `SummaryBroker(store, socket_path)` as a bounded context manager; `submit(socket_path, token, payload)` as a stdlib client. The only accepted object is `{token, summary}`; summary retains the current exact why/done/next schema. No settings dispatch or file-path API.
- [x] Start broker only with explicit `--summary-socket` on the trusted MCP entry point. Hook takes the same option, uses a compact isolated prompt and emits a client-only submission command.
- [x] Verify original-turn Stop consumes staged text through the existing queue, with a silent sink, while direct SQLite access is sandbox-denied.

## 3. Control authorization

Files: new `nkc/confirmation.py`; modify MCP factory/entry point.

- [x] RED: all six mutating tools blocked on rejection/cancellation/timeout; three reads bypass confirmation; approving one concrete patch does not authorize a future call; nine schemas unchanged.
- [x] Implement `--confirm-controls` gate before invoking any mutating control. Use fixed executable/script with JSON arguments as data, show the full bounded request, default Cancel, and fail closed. No caller-supplied approval boolean, shell string execution or headless auto-approve.
- [x] Exercise real stdio using injected test approvers only in test code; never provide a production bypass flag.

## 4. Opt-in host configuration and delivery

Files: new `nkc/isolation.py`, `scripts/prepare_isolation.py`; packaging builder and docs.

- [x] Generate reviewable per-host configuration fragments for a specified project/runtime/state/socket. Runtime read-only, private state and credentials denied, project writable, shell network disabled except exact summary socket; no broad unsandboxed-command exceptions.
- [x] Include isolated hook and MCP command lines, with native confirmation enabled. Preserve existing live host settings by generating files rather than applying them.
- [x] Test schema, paths, overlap, shell quoting, protected config placement, socket length and platform checks. Probe actual Codex sandbox plus documented Claude settings; report any unverified surface.
- [x] Run focused tests, build the marketplace once, run the complete suite against it, review the cross-component security boundary, and update ZIP/checksums and evidence.

## Progress / decisions

- User explicitly deferred the single-session-only mode.
- The opt-in setup adds strong guarantees only when its host sandbox and trusted control process are actually selected. It cannot retroactively sandbox this full-access desktop task.
- Model evaluation and production code changes are separate: no model can receive live Attention state or a playable backend during evaluation.

## Final evidence

- 279 full-suite checks passed with the final generated marketplace and explicit Codex sandbox probes (66.737 seconds).
- Two Claude fake-backend model cases completed with zero mutation attempts/effects. Codex model cases remained unavailable and were not launched.
- Independent review findings fixed: temporary interpreter placement, slow-frame resource exhaustion and receiver writes surviving shutdown.
- Actual sandboxed submit client staged a summary while database reads were denied; trusted Stop used a silent sink. Diagnostic exact socket flag remains distinct from actual host activation.
- Native dialog script compiled; automated confirmations were mocked, with no actual dialog/audio test.
- Final package: 250021 bytes, 84 files; SHA-256 54cd2db0c9b0daa1f96f1b338582093aa34a36f5df7b2f49d5fb347c2e1b9e4c.
- No live host isolation was applied; new Codex socket delivery and Claude enforcement remain documented acceptance gaps. Global speech is OFF per the latest user request.
