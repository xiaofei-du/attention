# Attention! Plugin Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Work inline in the existing unborn branch; do not commit unrelated untracked files.

**Goal:** Produce a locally validated Codex/Claude Code marketplace package for Attention!.
**Architecture:** Generate provider-specific manifests around a shared immutable payload; bootstrap pinned Python dependencies with uv and share persistent user data outside plugin caches.
**Tech Stack:** Python 3.12, official MCP Python SDK v1, macOS Core Audio, uv, native universal binaries.
**Spec:** docs/superpowers/specs/2026-09-11-attention-plugin.md

## Global Constraints
- Display name Attention!, identifier attention; macOS 14.2+.
- Fresh opening exactly hey sunshine. Existing selections survive.
- Nine existing MCP tools only; original session generates summaries.
- No live queue clearing, duplicate hooks, permission bypass, auto-publication or extra agent calls.
- Python requirements locked; no Xcode on recipient computer.

### Task 1: Platform-safe bootstrap and durable runtime
**Files:** attention.py, nkc/platform_support.py, nkc/mcp_server.py, nkc/install.py, nkc/runtime.py, tests/test_platform_support.py, tests/test_plugin_bootstrap.py.
**Interfaces:** platform_status(system=None, version=None, machine=None) returns supported/status/message; bootstrap prepares a stable runtime then dispatches existing run.py or MCP.
- [x] Add fake-platform tests for Linux, Windows, macOS 14.1, 14.2 and newer, including import and state side-effect checks.
- [x] Implement capability checks before importing native dependencies. Unsupported hooks return exit 0 and one systemMessage; subsequent hooks return {}. MCP handlers return the same unsupported status.
- [x] Build immutable runtime setup, shared state resolution, short stable CLI wrapper, and legacy-hook conflict detection.
- [x] Verify fresh defaults, upgrade persistence, paths with spaces, two providers sharing one queue and at-most-once notice behavior.

### Task 2: Generate self-contained provider plugins
**Files:** scripts/build_marketplace.py, packaging/, .agents/plugins/marketplace.json, .claude-plugin/marketplace.json, plugins/attention/, claude-plugins/attention/.
**Interfaces:** build_marketplace.py --output PATH produces an installable repo marketplace; payload hash selects immutable runtime.
- [x] Scaffold the Codex plugin using plugin-creator; use separate Claude manifests and shared core payload.
- [x] Export pinned requirements, cross-compile arm64/x86_64 native helpers, combine/sign universal binaries, copy only an explicit source allowlist.
- [x] Add relocatable uv launch commands and the two original lifecycle hooks. Never bundle .state, .venv, credentials, local config, logs or personal summaries.
- [x] Validate with plugin-creator and claude plugin validate. Verify every referenced path exists after copying the plugin alone.

### Task 3: Installation proof and handoff
**Files:** tests/test_marketplace.py, docs/installation.md, README.md, outputs/attention-marketplace.zip.
**Interfaces:** local marketplace CLI commands, native plugin MCP config, get_status.
- [x] Run applicable core regressions and the five real MCP protocol tests.
- [x] Install/list through both native client CLIs using isolated configuration, then initialize MCP and invoke read-only tools using the installed commands.
- [x] Check old macOS/non-Mac guard and no setup playback; verify the production user's settings/hooks remain identical.
- [x] Write accurate friend installation, requirements, permissions, conflict/migration and uninstall guidance; produce clean archive and checksum. State local versus published status.

## Results

175 core checks plus 8 real MCP/package protocol checks passed across the supported development runtimes. Native Codex/Claude plugin installation and discovery passed in isolated profiles. Codex native MCP startup initially revealed literal PLUGIN_ROOT arguments; changing only its MCP declaration to plugin-relative cwd fixed startup, with nine tools discovered. Claude native MCP health reports Connected. No model/agent session was created for verification. Public publication is pending the user’s GitHub destination; live legacy installation migration is outside this isolated packaging handoff.
