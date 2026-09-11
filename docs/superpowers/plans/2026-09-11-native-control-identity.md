# Native control identity implementation plan

**Goal:** Make session controls one MCP call with no model-supplied identity, using two hooks in Codex and a silent third hook in Claude Code.

**Architecture:** Resolve identity from Codex per-call metadata or Claude's native tool-use ID joined to a short-lived private SQLite record. Translate the resolved current turn to the existing internal control capability so atomic stale-turn checks and cancellation stay shared with CLI controls. Summary submission retains its separate public token workflow.

**Spec:** Local session-identity design artifact (not included in this repository)

**Constraints:** Existing uncommitted source is the approved working branch; no unrelated changes or blanket git operations. Preserve live settings, hook trust, native confirmation, queue privacy, summary-off empty prompts and one-time revocation. No startup-environment identity fallback. Tests and live probes use private disposable data, with speech off.

## Steps

- [x] Add failing real MCP protocol tests: tokenless Codex calls, silent Claude calls, concurrent sessions, stale/missing/foreign identity, subagents, replay/expiry/argument mismatch and approval cancellation/delay. Remove only tests requiring the retired deny/retry contract.
- [x] Implement `resolve_control_token(store, provider, name, arguments, meta)` in `nkc/control_context.py`. Codex requires consistent thread/turn metadata and original-user source; Claude requires an unconsumed exact native call binding. Global controls skip identity.
- [x] Extend `nkc/store.py` with expiring hashed-argument bindings. Bind once, atomically consume, preserve stale current-turn checks after confirmation. Do not store argument values or speech bodies.
- [x] Update MCP schema: `get_status(scope="shared"|"session")` and `set_session_enabled(enabled)`; pass explicit provider through source CLI, bootstrap, marketplace launch configs and isolation profiles. Preserve CLI capability inputs.
- [x] Generate two Codex hooks and three Claude hooks in every install path. Claude bridge returns `{}` without approval decisions or context. Update summary templates, help and human documentation plus independent evaluation catalog.
- [x] Run targeted tests, build new packages, run full suite and native sandbox probes; fix only observed failures. Exercise actual host calls with the built plugin in disposable state, including parallel session separation and available lifecycle switches.
- [x] Back up package files only, update existing local marketplace through build/helper and native install commands. Verify installed payload, discovered hooks and unchanged preferences. Report live coverage and any remaining host reload/trust requirement precisely.

## Result

Implemented and installed on 2026-09-11. Full suite: 322 passing tests against the second candidate; 21 targeted tests passed after the final removal of an unused prompt substitution. Both provider native calls passed, and the final installed Claude plugin completed a native round. Codex native discovery shows exactly two trusted hooks. Interactive /clear and the currently open Desktop MCP connection were not driven; same-connection switch/restart behavior is covered by real stdio protocol tests. Details and evidence: local native-identity verification artifact (not included in this repository).
